from __future__ import annotations

import json
import importlib.util
import socket
import sys
import re
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, ValidationError
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from scout.nextgen.model_gateway import (
    ModelGatewayExecutionError,
    ModelInferencePriority,
    ModelInferenceRequest,
    PydanticAIStructuredBackend,
    ScoutModelGateway,
)
from scout.nextgen import (
    CapabilityBroker,
    GeoScope,
    IntelligenceRequest,
    IntelligenceTaskType,
    WorkspaceBinding,
)
from scout.nextgen.intelligence_mcp import (
    IntelligenceMcpClientConfig,
    IntelligenceTransportStatus,
    McpIntelligenceGateway,
)
from scout.nextgen.intelligence_gateway import Finding
from scout.nextgen.model_runtime import (
    AcceleratorKind,
    Locality,
    ModelRuntimeCapability,
    ModelRuntimeHostKind,
    ModelRuntimeProfile,
    ModelRuntimeTier,
)
from scout.nextgen.openai_compatible_backend import (
    OpenAICompatibleBackendConfig,
    OpenAICompatibleConfigurationError,
    OpenAICompatiblePydanticBackend,
    OpenAICompatibleTransportScope,
    _RequestCountingModel,
    build_praison_openai_compatible_runtime,
)
from scout.nextgen.praison_service import (
    EvidenceCatalog,
    EvidenceCatalogItem,
    PraisonIntelligenceService,
    SPECIALIST_INPUT_MARKER,
    SpecialistModelInput,
    SpecialistReport,
    SpecialistRole,
    _ground_specialist_report,
    replay_specialist_report,
)


class _ProbeOutput(BaseModel):
    value: str


class _ReplayState:
    def __init__(
        self,
        *,
        output_arguments: dict[str, Any] | None = None,
        failure_status: int | None = None,
        responder: Any | None = None,
        created_timestamp: int | None = None,
    ) -> None:
        self.output_arguments = output_arguments or {"value": "http-replay-ok"}
        self.failure_status = failure_status
        self.responder = responder
        self.created_timestamp = created_timestamp
        self.requests: list[dict[str, Any]] = []
        self.paths: list[str] = []
        self.lock = threading.Lock()


@contextmanager
def _openai_replay_server(
    *,
    output_arguments: dict[str, Any] | None = None,
    failure_status: int | None = None,
    responder: Any | None = None,
    created_timestamp: int | None = None,
) -> Iterator[tuple[str, _ReplayState]]:
    state = _ReplayState(
        output_arguments=output_arguments,
        failure_status=failure_status,
        responder=responder,
        created_timestamp=created_timestamp,
    )

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            with state.lock:
                state.requests.append(payload)
                state.paths.append(self.path)
            if state.failure_status is not None:
                body = {
                    "error": {
                        "message": "replay provider failure",
                        "type": "replay_error",
                    }
                }
                self.send_response(state.failure_status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(body).encode("utf-8"))
                return
            output_arguments = (
                state.responder(payload)
                if callable(state.responder)
                else state.output_arguments
            )
            tools = payload.get("tools") or []
            if tools:
                output_tool = tools[0]["function"]["name"]
                message = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-scout-replay",
                            "type": "function",
                            "function": {
                                "name": output_tool,
                                "arguments": json.dumps(output_arguments),
                            },
                        }
                    ],
                }
                finish_reason = "tool_calls"
            else:
                message = {
                    "role": "assistant",
                    "content": json.dumps(output_arguments),
                }
                finish_reason = "stop"
            body = {
                "id": "chatcmpl-scout-replay",
                "object": "chat.completion",
                "created": state.created_timestamp or int(time.time()),
                "model": payload["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": finish_reason,
                    }
                ],
                "usage": {
                    "prompt_tokens": 17,
                    "completion_tokens": 5,
                    "total_tokens": 22,
                },
            }
            encoded = json.dumps(body).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format: str, *args: Any) -> None:
            del format, args

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}/v1", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _config(
    base_url: str,
    **overrides: Any,
) -> OpenAICompatibleBackendConfig:
    payload = {
        "runtime_id": "local.http.replay",
        "provider": "openai-compatible-replay",
        "model_id": "scout-http-replay-model",
        "base_url": base_url,
        "transport_scope": OpenAICompatibleTransportScope.LOOPBACK,
        "tier": ModelRuntimeTier.LOCAL_FAST,
        "locality": Locality.EDGE,
        "accelerator": AcceleratorKind.CPU,
        "context_limit_tokens": 8192,
        "max_concurrency": 1,
        "offline_capable": True,
        "privacy_preserving": True,
    }
    payload.update(overrides)
    return OpenAICompatibleBackendConfig(**payload)


def _request(parent_request_id: UUID) -> ModelInferenceRequest:
    return ModelInferenceRequest(
        parent_request_id=parent_request_id,
        task="openai-compatible typed replay",
        prompt="Return the typed replay result.",
        allowed_tiers=frozenset({ModelRuntimeTier.LOCAL_FAST}),
        prefer_local=True,
        allow_cloud=False,
        requires_offline=True,
        timeout_seconds=10,
    )


def test_config_rejects_remote_plain_http_and_url_credentials() -> None:
    base_payload = _config("http://127.0.0.1:8000/v1").model_dump()
    with pytest.raises(ValidationError, match="remote_https requires HTTPS"):
        OpenAICompatibleBackendConfig.model_validate(
            {
                **base_payload,
                "base_url": "http://models.example.com/v1",
                "transport_scope": OpenAICompatibleTransportScope.REMOTE_HTTPS,
                "locality": Locality.CLOUD,
                "offline_capable": False,
            }
        )

    with pytest.raises(ValidationError, match="must not contain credentials"):
        OpenAICompatibleBackendConfig(
            **{
                **base_payload,
                "base_url": "http://user:password@127.0.0.1:8000/v1",
            }
        )


def test_remote_backend_requires_named_environment_credential() -> None:
    config = OpenAICompatibleBackendConfig(
        runtime_id="remote.https.test",
        provider="remote-openai-compatible",
        model_id="remote-test-model",
        base_url="https://models.example.com/v1",
        transport_scope=OpenAICompatibleTransportScope.REMOTE_HTTPS,
        tier=ModelRuntimeTier.CLOUD_REASONING,
        locality=Locality.CLOUD,
        accelerator=AcceleratorKind.NONE,
        context_limit_tokens=8192,
        max_concurrency=1,
        offline_capable=False,
        privacy_preserving=False,
        api_key_env="SCOUT_TEST_REMOTE_MODEL_KEY",
    )

    with pytest.raises(
        OpenAICompatibleConfigurationError,
        match="credential environment variable is unavailable",
    ):
        OpenAICompatiblePydanticBackend(config=config, environ={})


def test_private_pi_endpoint_requires_explicit_private_network_scope() -> None:
    payload = _config("http://127.0.0.1:8000/v1").model_dump(mode="json")
    payload.update(
        {
            "base_url": "http://scout.local:8000/v1",
            "transport_scope": "private_network",
        }
    )
    config = OpenAICompatibleBackendConfig.model_validate(payload)

    assert config.normalized_base_url == "http://scout.local:8000/v1"
    with pytest.raises(ValidationError, match="loopback hostname"):
        OpenAICompatibleBackendConfig.model_validate(
            {**payload, "transport_scope": "loopback"}
        )


def test_named_private_endpoint_credential_fails_closed_when_missing() -> None:
    payload = _config("http://127.0.0.1:8000/v1").model_dump(mode="json")
    payload.update(
        {
            "base_url": "https://scout.local:8443/v1",
            "transport_scope": "private_network",
        }
    )
    payload["api_key_env"] = "SCOUT_PRIVATE_MODEL_KEY"
    config = OpenAICompatibleBackendConfig.model_validate(payload)

    with pytest.raises(
        OpenAICompatibleConfigurationError,
        match="credential environment variable is unavailable",
    ):
        OpenAICompatiblePydanticBackend(config=config, environ={})


def test_runtime_config_cannot_exfiltrate_arbitrary_environment_secret() -> None:
    payload = _config("http://127.0.0.1:8000/v1").model_dump(mode="json")
    payload.update(
        {
            "base_url": "https://models.example.com/v1",
            "transport_scope": "remote_https",
            "tier": "cloud_reasoning",
            "locality": "cloud",
            "accelerator": "none",
            "offline_capable": False,
            "privacy_preserving": False,
            "api_key_env": "AWS_SECRET_ACCESS_KEY",
        }
    )

    with pytest.raises(ValidationError, match="Scout-owned"):
        OpenAICompatibleBackendConfig.model_validate(payload)


def test_max_local_server_is_non_cloud_without_claiming_offline_capability() -> None:
    payload = _config("http://127.0.0.1:8000/v1").model_dump(mode="json")
    payload.update(
        {
            "runtime_id": "server.max.http-test",
            "provider": "max",
            "model_id": "max-served-test-model",
            "tier": "max_local_or_server",
            "locality": "mac_server",
            "accelerator": "gpu",
            "offline_capable": False,
        }
    )
    config = OpenAICompatibleBackendConfig.model_validate(payload)
    runtime = build_praison_openai_compatible_runtime(config=config, environ={})
    try:
        assert runtime.allowed_tiers == {
            ModelRuntimeTier.MAX_LOCAL_OR_SERVER
        }
        assert runtime.allow_cloud is False
        assert runtime.requires_offline is False
    finally:
        runtime.close()


def test_openai_compatible_backend_executes_real_http_typed_output() -> None:
    with _openai_replay_server() as (base_url, state):
        config = _config(base_url)
        backend = OpenAICompatiblePydanticBackend(config=config, environ={})
        with ScoutModelGateway(
            profiles=(config.to_runtime_profile(),),
            backends=(backend,),
            max_local_concurrency=1,
        ) as gateway:
            session = gateway.open_session(
                parent_request_id=uuid4(),
                max_model_requests=10,
            )
            result = session.infer(
                _request(session.parent_request_id),
                output_type=_ProbeOutput,
            )

    assert result.output == _ProbeOutput(value="http-replay-ok")
    assert state.paths == ["/v1/chat/completions"]
    assert state.requests[0]["model"] == config.model_id
    assert state.requests[0]["tools"]
    assert result.execution_record.provider == config.provider
    assert result.execution_record.model_id == config.model_id
    assert result.execution_record.observed_model_id == config.model_id
    assert result.execution_record.model_request_count == 1
    assert result.execution_record.input_tokens == 17
    assert result.execution_record.output_tokens == 5


def test_openai_compatible_backend_executes_native_json_schema_output() -> None:
    with _openai_replay_server() as (base_url, state):
        config = _config(base_url, structured_output_mode="native")
        backend = OpenAICompatiblePydanticBackend(config=config, environ={})
        with ScoutModelGateway(
            profiles=(config.to_runtime_profile(),),
            backends=(backend,),
            max_local_concurrency=1,
        ) as gateway:
            session = gateway.open_session(
                parent_request_id=uuid4(),
                max_model_requests=10,
            )
            result = session.infer(
                _request(session.parent_request_id),
                output_type=_ProbeOutput,
            )

    payload = state.requests[0]
    assert result.output == _ProbeOutput(value="http-replay-ok")
    assert payload.get("tools") is None
    assert payload["response_format"]["type"] == "json_schema"


def test_hailo_timestamp_mode_normalizes_nanoseconds_before_pydantic_ai() -> None:
    with _openai_replay_server(
        created_timestamp=1_787_463_187_012_202_212,
    ) as (base_url, state):
        config = _config(
            base_url,
            provider="hailo_ollama",
            response_created_timestamp_mode="auto_to_seconds",
        )
        backend = OpenAICompatiblePydanticBackend(config=config, environ={})
        with ScoutModelGateway(
            profiles=(config.to_runtime_profile(),),
            backends=(backend,),
            max_local_concurrency=1,
        ) as gateway:
            session = gateway.open_session(
                parent_request_id=uuid4(),
                max_model_requests=10,
            )
            result = session.infer(
                _request(session.parent_request_id),
                output_type=_ProbeOutput,
            )

    assert result.output == _ProbeOutput(value="http-replay-ok")
    assert state.requests[0]["model"] == config.model_id


def test_timestamp_normalization_is_restricted_to_hailo_provider() -> None:
    with pytest.raises(ValidationError, match="only available for hailo_ollama"):
        _config(
            "http://127.0.0.1:8000/v1",
            response_created_timestamp_mode="auto_to_seconds",
        )


def test_hailo_prompted_output_flattens_message_control_characters() -> None:
    with _openai_replay_server() as (base_url, state):
        config = _config(
            base_url,
            provider="hailo_ollama",
            structured_output_mode="prompted",
            request_message_control_mode="replace_controls_with_spaces",
        )
        backend = OpenAICompatiblePydanticBackend(config=config, environ={})
        with ScoutModelGateway(
            profiles=(config.to_runtime_profile(),),
            backends=(backend,),
            max_local_concurrency=1,
        ) as gateway:
            session = gateway.open_session(
                parent_request_id=uuid4(),
                max_model_requests=10,
            )
            request = _request(session.parent_request_id).model_copy(
                update={"prompt": "Return\nthis\ttyped replay result."}
            )
            result = session.infer(request, output_type=_ProbeOutput)

    assert result.output == _ProbeOutput(value="http-replay-ok")
    assert state.requests[0].get("tools") is None
    message_text = json.dumps(
        state.requests[0]["messages"],
        ensure_ascii=False,
    )
    assert re.search(r"[\x00-\x1f\x7f-\x9f]", message_text) is None


def test_hailo_request_control_mode_is_restricted_to_hailo_provider() -> None:
    with pytest.raises(ValidationError, match="only available for hailo_ollama"):
        _config(
            "http://127.0.0.1:8000/v1",
            request_message_control_mode="replace_controls_with_spaces",
        )


def test_openai_compatible_backend_applies_bounded_inference_defaults() -> None:
    with _openai_replay_server() as (base_url, state):
        config = _config(
            base_url,
            max_output_tokens=128,
            temperature=0,
            thinking=False,
            supports_reasoning_control=True,
            uses_max_completion_tokens=False,
        )
        backend = OpenAICompatiblePydanticBackend(config=config, environ={})
        with ScoutModelGateway(
            profiles=(config.to_runtime_profile(),),
            backends=(backend,),
            max_local_concurrency=1,
        ) as gateway:
            session = gateway.open_session(
                parent_request_id=uuid4(),
                max_model_requests=10,
            )
            session.infer(
                _request(session.parent_request_id),
                output_type=_ProbeOutput,
            )

    payload = state.requests[0]
    assert payload["max_tokens"] == 128
    assert "max_completion_tokens" not in payload
    assert payload["temperature"] == 0
    assert payload["reasoning_effort"] == "none"


def test_openai_compatible_http_failure_is_counted_and_fails_closed() -> None:
    with _openai_replay_server(failure_status=503) as (base_url, state):
        config = _config(base_url)
        backend = OpenAICompatiblePydanticBackend(config=config, environ={})
        with ScoutModelGateway(
            profiles=(config.to_runtime_profile(),),
            backends=(backend,),
            max_local_concurrency=1,
        ) as gateway:
            session = gateway.open_session(
                parent_request_id=uuid4(),
                max_model_requests=10,
            )
            with pytest.raises(ModelGatewayExecutionError):
                session.infer(
                    _request(session.parent_request_id),
                    output_type=_ProbeOutput,
                )

    assert len(state.requests) == 1
    assert len(session.records) == 1
    assert session.records[0].status == "failed"
    assert session.records[0].model_request_count == 1
    assert session.remaining_model_requests == 9


def test_request_counter_is_isolated_across_parallel_cloud_sessions() -> None:
    barrier = threading.Barrier(2)

    def model_function(messages: list[object], info: AgentInfo) -> ModelResponse:
        del messages
        barrier.wait(timeout=2)
        output_tool = info.output_tools[0]
        arguments: Any = {"value": "parallel-scope-ok"}
        if output_tool.outer_typed_dict_key:
            arguments = {output_tool.outer_typed_dict_key: arguments}
        return ModelResponse(
            parts=[
                ToolCallPart(
                    output_tool.name,
                    arguments,
                    tool_call_id=f"parallel-{threading.get_ident()}",
                )
            ],
            model_name="parallel-scope-model",
        )

    counted_model = _RequestCountingModel(
        FunctionModel(model_function, model_name="parallel-scope-model")
    )
    backend = PydanticAIStructuredBackend(
        runtime_id="cloud.parallel.scope",
        model_id="parallel-scope-model",
        model=counted_model,
    )
    profile = ModelRuntimeProfile(
        runtime_id=backend.runtime_id,
        tier=ModelRuntimeTier.CLOUD_REASONING,
        provider="scope-test",
        model_id=backend.model_id,
        locality=Locality.CLOUD,
        accelerator=AcceleratorKind.NONE,
        capabilities=frozenset(
            {
                ModelRuntimeCapability.CHAT,
                ModelRuntimeCapability.STRUCTURED_OUTPUT,
            }
        ),
        context_limit_tokens=8192,
        max_concurrency=2,
        offline_capable=False,
        privacy_preserving=True,
    )
    with ScoutModelGateway(
        profiles=(profile,),
        backends=(backend,),
        max_cloud_concurrency=2,
    ) as gateway:
        sessions = [
            gateway.open_session(parent_request_id=uuid4(), max_model_requests=10)
            for _ in range(2)
        ]

        def infer(session: Any) -> Any:
            return session.infer(
                ModelInferenceRequest(
                    parent_request_id=session.parent_request_id,
                    task="parallel cloud counter scope",
                    prompt="Return the typed parallel result.",
                    allowed_tiers=frozenset(
                        {ModelRuntimeTier.CLOUD_REASONING}
                    ),
                    prefer_local=False,
                    allow_cloud=True,
                    requires_offline=False,
                    timeout_seconds=10,
                ),
                output_type=_ProbeOutput,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(infer, sessions))
        _, cloud_snapshot = gateway.scheduler_snapshots()

    assert [result.output.value for result in results] == [
        "parallel-scope-ok",
        "parallel-scope-ok",
    ]
    assert [result.execution_record.model_request_count for result in results] == [
        1,
        1,
    ]
    assert cloud_snapshot.max_observed_concurrency == 2


def test_runtime_profile_does_not_self_attest_tool_calling() -> None:
    profile = _config("http://127.0.0.1:8000/v1").to_runtime_profile()

    assert profile.capabilities.issuperset(
        {
            ModelRuntimeCapability.CHAT,
            ModelRuntimeCapability.STRUCTURED_OUTPUT,
            ModelRuntimeCapability.OFFLINE,
        }
    )
    assert ModelRuntimeCapability.TOOL_CALLING not in profile.capabilities
    assert profile.capability_attestation_refs == ()
    assert profile.candidate_only is True
    assert profile.runtime_safety_truth is False


def _binding() -> WorkspaceBinding:
    return WorkspaceBinding(
        workspace_id="workspace-http-replay",
        workspace_revision="revision-1",
        mission_id="mission-http-replay",
        mission_version="mission-version-1",
        route_id="route-http-replay",
        route_version="route-version-1",
        input_hash="http-replay-input-hash",
        generated_at=datetime(2026, 8, 22, tzinfo=UTC),
    )


def _intelligence_request() -> IntelligenceRequest:
    request_id = uuid4()
    evidence_refs = (
        "route:http-replay",
        "dem:http-replay",
        "qgis:http-replay",
    )
    grant = CapabilityBroker().issue_grant(
        request_id=request_id,
        mission_id="mission-http-replay",
        task_type=IntelligenceTaskType.TERRAIN_ANALYSIS,
        allowed_capabilities=(
            "route.read",
            "dem.read",
            "qgis.processing.slope",
            "workspace.evidence.read",
        ),
        evidence_refs_allowed=evidence_refs,
        max_model_requests=10,
        max_tool_calls=10,
    )
    return IntelligenceRequest(
        request_id=request_id,
        mission_id="mission-http-replay",
        task_type=IntelligenceTaskType.TERRAIN_ANALYSIS,
        question="Find ridge, saddle, and steep terrain candidate evidence.",
        workspace_binding=_binding(),
        capability_grant=grant,
        geographic_scope=GeoScope(
            route_id="route-http-replay",
            corridor_meters=250,
        ),
        evidence_refs=evidence_refs,
        max_model_requests=10,
    )


def _catalog() -> EvidenceCatalog:
    return EvidenceCatalog(
        items=(
            EvidenceCatalogItem(
                evidence_id="ev-http-route",
                source_ref="route:http-replay",
                source_type="route_geometry",
                content_hash="route-http-hash",
                summary="Reviewed route geometry used as read-only analysis input.",
            ),
            EvidenceCatalogItem(
                evidence_id="ev-http-dem",
                source_ref="dem:http-replay",
                source_type="prepared_dem",
                content_hash="dem-http-hash",
                summary="Prepared DEM candidate artifact.",
                attributes={
                    "candidate_features": [
                        {
                            "kind": "ridge",
                            "claim": "HTTP model suggests a ridge candidate near CP2.",
                            "confidence": 0.7,
                        },
                        {
                            "kind": "saddle",
                            "claim": "HTTP model suggests a saddle candidate near CP3.",
                            "confidence": 0.6,
                        },
                    ]
                },
            ),
            EvidenceCatalogItem(
                evidence_id="ev-http-qgis",
                source_ref="qgis:http-replay",
                source_type="qgis_candidate_artifact",
                content_hash="qgis-http-hash",
                summary="QGIS slope candidate artifact.",
                attributes={
                    "candidate_features": [
                        {
                            "kind": "steep_terrain",
                            "claim": "HTTP model suggests steep terrain in the corridor.",
                            "confidence": 0.8,
                        }
                    ]
                },
            ),
        )
    )


def test_specialist_grounding_preserves_typed_features_and_scope() -> None:
    request = _intelligence_request()
    dem_item = next(
        item for item in _catalog().items if item.evidence_id == "ev-http-dem"
    )
    model_input = SpecialistModelInput(
        request_id=request.request_id,
        mission_id=request.mission_id,
        role=SpecialistRole.TERRAIN,
        question=request.question,
        workspace_binding=request.workspace_binding,
        geographic_scope=request.geographic_scope,
        evidence=(dem_item,),
        capabilities_used=("dem.read",),
    )

    grounded = _ground_specialist_report(
        model_input=model_input,
        model_report=SpecialistReport(role=SpecialistRole.TERRAIN),
    )

    assert [finding.claim for finding in grounded.findings] == [
        "HTTP model suggests a ridge candidate near CP2.",
        "HTTP model suggests a saddle candidate near CP3.",
    ]
    quarantined = _ground_specialist_report(
        model_input=model_input,
        model_report=SpecialistReport(
            role=SpecialistRole.TERRAIN,
            findings=(
                Finding(
                    finding_id="out-of-scope",
                    claim="An unscoped candidate claim.",
                    confidence=0.5,
                    evidence_ids=("ev-http-qgis",),
                ),
            ),
        ),
    )

    assert all(
        finding.finding_id != "out-of-scope" for finding in quarantined.findings
    )
    assert quarantined.uncertainties[0].uncertainty_id == (
        "terrain:model_finding:0:ungrounded"
    )

    scoped_extra = _ground_specialist_report(
        model_input=model_input,
        model_report=SpecialistReport(
            role=SpecialistRole.TERRAIN,
            findings=(
                Finding(
                    finding_id="scoped-but-not-normalized",
                    claim="The DEM artifact itself is available.",
                    confidence=1.0,
                    evidence_ids=("ev-http-dem",),
                ),
            ),
        ),
    )

    assert all(
        finding.finding_id != "scoped-but-not-normalized"
        for finding in scoped_extra.findings
    )
    assert scoped_extra.uncertainties[0].uncertainty_id == (
        "terrain:model_finding:0:not_normalized_candidate"
    )


def _specialist_responder(payload: dict[str, Any]) -> dict[str, Any]:
    for message in reversed(payload["messages"]):
        content = message.get("content")
        if not isinstance(content, str) or SPECIALIST_INPUT_MARKER not in content:
            continue
        model_input = SpecialistModelInput.model_validate_json(
            content.split(SPECIALIST_INPUT_MARKER, 1)[1].strip()
        )
        return replay_specialist_report(model_input).model_dump(mode="json")
    raise AssertionError("Scout specialist input marker was absent from HTTP request")


def _unused_loopback_base_url() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    return f"http://127.0.0.1:{port}/v1"


def test_runtime_config_file_rejects_embedded_secret(tmp_path: Path) -> None:
    payload = _config("http://127.0.0.1:8000/v1").model_dump(mode="json")
    payload["api_key"] = "must-not-be-accepted"
    path = tmp_path / "runtime-with-secret.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValidationError, match="api_key"):
        OpenAICompatibleBackendConfig.from_json_file(path)


def test_checked_in_max_runtime_example_stays_valid_and_candidate_only() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "configs"
        / "scout-nextgen-openai-compatible.max.example.json"
    )
    config = OpenAICompatibleBackendConfig.from_json_file(path)

    assert config.tier == ModelRuntimeTier.MAX_LOCAL_OR_SERVER
    assert config.locality == Locality.MAC_SERVER
    assert config.max_concurrency == 1
    assert config.candidate_only is True
    assert config.runtime_safety_truth is False


def test_hailo_config_declares_only_chat_and_small_typed_output() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "configs"
        / "scout-nextgen-openai-compatible.hailo-qwen3-1.7b.json"
    )
    config = OpenAICompatibleBackendConfig.from_json_file(path)
    profile = config.to_runtime_profile()
    runtime = build_praison_openai_compatible_runtime(config=config, environ={})
    try:
        assert profile.capabilities == frozenset(
            {
                ModelRuntimeCapability.CHAT,
                ModelRuntimeCapability.SMALL_TYPED_OUTPUT,
                ModelRuntimeCapability.OFFLINE,
            }
        )
        assert runtime.required_capabilities == frozenset(
            {
                ModelRuntimeCapability.CHAT,
                ModelRuntimeCapability.SMALL_TYPED_OUTPUT,
            }
        )
        assert runtime.inference_priority is ModelInferencePriority.NORMAL
    finally:
        runtime.close()


def test_pi_cpu_ollama_config_is_background_reasoning_runtime() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "configs"
        / "scout-nextgen-openai-compatible.pi-cpu-ollama-qwen3-1.7b.json"
    )
    old_mac_path = (
        Path(__file__).resolve().parents[1]
        / "configs"
        / "scout-nextgen-openai-compatible.ollama-qwen3-1.7b.json"
    )
    config = OpenAICompatibleBackendConfig.from_json_file(path)
    profile = config.to_runtime_profile()
    runtime = build_praison_openai_compatible_runtime(config=config, environ={})
    try:
        assert old_mac_path.exists() is False
        assert config.transport_scope is OpenAICompatibleTransportScope.LOOPBACK
        assert config.base_url == "http://127.0.0.1:11434/v1"
        assert profile.runtime_id == "edge.pi.ollama.cpu.background"
        assert profile.locality is Locality.EDGE
        assert profile.accelerator is AcceleratorKind.CPU
        assert profile.required_host_kind is ModelRuntimeHostKind.RASPBERRY_PI
        assert profile.capabilities.issuperset(
            {
                ModelRuntimeCapability.CHAT,
                ModelRuntimeCapability.STRUCTURED_OUTPUT,
                ModelRuntimeCapability.SLOW_BACKGROUND_REASONING,
                ModelRuntimeCapability.OFFLINE,
            }
        )
        assert ModelRuntimeCapability.SLOW_BACKGROUND_REASONING in (
            runtime.required_capabilities
        )
        assert runtime.inference_priority is ModelInferencePriority.BACKGROUND
    finally:
        runtime.close()


@pytest.mark.skipif(
    importlib.util.find_spec("praisonaiagents") is None,
    reason="optional praisonaiagents dependency is not installed",
)
def test_praison_openai_compatible_runtime_uses_one_http_model() -> None:
    request = _intelligence_request()
    with _openai_replay_server(responder=_specialist_responder) as (base_url, state):
        config = _config(
            base_url,
            max_output_tokens=256,
            temperature=0,
            thinking=False,
            supports_reasoning_control=True,
            uses_max_completion_tokens=False,
            structured_output_mode="native",
        )
        runtime = build_praison_openai_compatible_runtime(config=config, environ={})
        try:
            response = PraisonIntelligenceService(
                runtime=runtime,
                evidence_catalog=_catalog(),
                max_concurrency=1,
            ).execute(request)
        finally:
            runtime.close()

    assert len(response.findings) == 3, response.model_dump_json(indent=2)
    assert len(state.requests) == 1
    assert {item["model"] for item in state.requests} == {config.model_id}
    assert all(item["max_tokens"] == 256 for item in state.requests)
    assert all(item["temperature"] == 0 for item in state.requests)
    assert all(item["reasoning_effort"] == "none" for item in state.requests)
    assert all(item.get("tools") is None for item in state.requests)
    assert all(
        item["response_format"]["json_schema"]["schema"]["properties"][
            "findings"
        ]["minItems"]
        == 1
        for item in state.requests
    )
    assert all(
        "Return one Finding for every valid candidate_features entry"
        in "\n".join(
            message.get("content") or "" for message in item["messages"]
        )
        for item in state.requests
    )
    assert len(response.provenance.model_execution_records) == 1
    assert sum(
        record.model_request_count
        for record in response.provenance.model_execution_records
    ) == 1
    assert response.provenance.agent_path == (
        "praisonai.orchestrator",
        "praisonai.router.deterministic.v1",
        "terrain",
        "qgis.deterministic",
    )
    assert response.provenance.model_runtimes == (config.runtime_id,)
    assert response.runtime_safety_truth is False


@pytest.mark.skipif(
    importlib.util.find_spec("praisonaiagents") is None,
    reason="optional praisonaiagents dependency is not installed",
)
def test_openai_compatible_praison_runtime_runs_behind_mcp(tmp_path: Path) -> None:
    request = _intelligence_request()
    catalog_path = tmp_path / "http-evidence-catalog.json"
    catalog_path.write_text(_catalog().model_dump_json(), encoding="utf-8")
    with _openai_replay_server(responder=_specialist_responder) as (base_url, state):
        runtime_path = tmp_path / "http-model-runtime.json"
        runtime_path.write_text(_config(base_url).model_dump_json(), encoding="utf-8")
        mcp_config = IntelligenceMcpClientConfig(
            command=(
                sys.executable,
                "-m",
                "scout.nextgen.intelligence_mcp_server",
                "--mode",
                "praison-openai-compatible",
                "--evidence-catalog",
                str(catalog_path),
                "--model-runtime-config",
                str(runtime_path),
            ),
            pythonpath=str(Path("src").resolve()),
            timeout_seconds=20,
        )
        with McpIntelligenceGateway(mcp_config) as gateway:
            execution = gateway.execute(
                request,
                current_binding=request.workspace_binding,
            )

    assert execution.status == IntelligenceTransportStatus.OK
    assert len(execution.response.findings) == 3
    assert len(state.requests) == 1
    assert len(execution.response.provenance.model_execution_records) == 1
    assert execution.response.runtime_safety_truth is False


@pytest.mark.skipif(
    importlib.util.find_spec("praisonaiagents") is None,
    reason="optional praisonaiagents dependency is not installed",
)
def test_unavailable_openai_endpoint_degrades_with_failed_model_audit(
    tmp_path: Path,
) -> None:
    request = _intelligence_request()
    catalog_path = tmp_path / "unavailable-evidence-catalog.json"
    catalog_path.write_text(_catalog().model_dump_json(), encoding="utf-8")
    runtime_path = tmp_path / "unavailable-model-runtime.json"
    runtime_path.write_text(
        _config(_unused_loopback_base_url()).model_dump_json(),
        encoding="utf-8",
    )
    mcp_config = IntelligenceMcpClientConfig(
        command=(
            sys.executable,
            "-m",
            "scout.nextgen.intelligence_mcp_server",
            "--mode",
            "praison-openai-compatible",
            "--evidence-catalog",
            str(catalog_path),
            "--model-runtime-config",
            str(runtime_path),
        ),
        pythonpath=str(Path("src").resolve()),
        timeout_seconds=20,
    )

    with McpIntelligenceGateway(mcp_config) as gateway:
        execution = gateway.execute(
            request,
            current_binding=request.workspace_binding,
        )

    records = execution.response.provenance.model_execution_records
    assert execution.status == IntelligenceTransportStatus.OK
    assert execution.response.findings == ()
    assert execution.response.uncertainties[0].uncertainty_id == (
        "praison_runtime_unavailable"
    )
    assert records
    assert all(record.status == "failed" for record in records)
    assert 1 <= sum(record.model_request_count for record in records) <= 10
    assert execution.response.runtime_safety_truth is False
