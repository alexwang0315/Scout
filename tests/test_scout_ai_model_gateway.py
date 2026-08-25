from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, ValidationError
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from scout.nextgen.model_gateway import (
    BackendInferenceResult,
    ModelInferencePriority,
    ModelInferenceRequest,
    ModelInferenceTimeout,
    ModelOutputValidationError,
    ModelRequestBudgetExceeded,
    ModelSessionCancelled,
    PydanticAIStructuredBackend,
    ScoutModelGateway,
)
from scout.nextgen.model_runtime import (
    AcceleratorKind,
    Locality,
    ModelRuntimeCapability,
    ModelRuntimeHostKind,
    ModelRuntimeProfile,
    ModelRuntimeRequest,
    ModelRuntimeTier,
    default_runtime_profiles,
)


class _ProbeOutput(BaseModel):
    value: str


def _profile() -> ModelRuntimeProfile:
    return ModelRuntimeProfile(
        runtime_id="local.fast.function",
        tier=ModelRuntimeTier.LOCAL_FAST,
        provider="scout",
        model_id="resident-replay-model",
        locality=Locality.EDGE,
        accelerator=AcceleratorKind.CPU,
        capabilities=frozenset(
            {
                ModelRuntimeCapability.CHAT,
                ModelRuntimeCapability.STRUCTURED_OUTPUT,
                ModelRuntimeCapability.OFFLINE,
            }
        ),
        context_limit_tokens=4096,
        max_concurrency=1,
        offline_capable=True,
        privacy_preserving=True,
        experimental=True,
    )


def _request(
    *,
    task: str = "terrain specialist",
    timeout_seconds: float = 2,
    priority: ModelInferencePriority = ModelInferencePriority.NORMAL,
    parent_request_id: UUID | None = None,
) -> ModelInferenceRequest:
    return ModelInferenceRequest(
        parent_request_id=parent_request_id or uuid4(),
        task=task,
        prompt=f"Return the typed result for {task}.",
        required_capabilities=frozenset(
            {
                ModelRuntimeCapability.CHAT,
                ModelRuntimeCapability.STRUCTURED_OUTPUT,
            }
        ),
        allowed_tiers=frozenset({ModelRuntimeTier.LOCAL_FAST}),
        prefer_local=True,
        allow_cloud=False,
        requires_offline=True,
        privacy_sensitive=True,
        estimated_input_tokens=100,
        timeout_seconds=timeout_seconds,
        priority=priority,
    )


class _RecordingBackend:
    runtime_id = "local.fast.function"
    model_id = "resident-replay-model"

    def __init__(
        self,
        *,
        runtime_id: str = "local.fast.function",
        model_id: str = "resident-replay-model",
        delay_seconds: float = 0,
        output: dict[str, Any] | None = None,
        model_request_count: int = 1,
    ) -> None:
        self.runtime_id = runtime_id
        self.model_id = model_id
        self.delay_seconds = delay_seconds
        self.output = output
        self.model_request_count = model_request_count
        self.calls = 0
        self.active = 0
        self.max_active = 0
        self.started = threading.Event()
        self._lock = threading.Lock()

    def infer(
        self,
        *,
        request: ModelInferenceRequest,
        output_type: type[BaseModel],
        model_request_limit: int,
        cancellation_event: threading.Event,
    ) -> BackendInferenceResult:
        del output_type
        assert model_request_limit >= 1
        with self._lock:
            self.calls += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.started.set()
        try:
            if self.delay_seconds:
                time.sleep(self.delay_seconds)
            if cancellation_event.is_set():
                raise RuntimeError("cancelled")
            output = self.output or {"value": request.task}
            return BackendInferenceResult(
                output=output,
                model_request_count=self.model_request_count,
                input_tokens=17,
                output_tokens=5,
            )
        finally:
            with self._lock:
                self.active -= 1


def test_model_gateway_selects_registered_local_backend_and_records_execution() -> None:
    backend = _RecordingBackend()
    with ScoutModelGateway(
        profiles=(_profile(),),
        backends=(backend,),
        max_local_concurrency=1,
    ) as gateway:
        session = gateway.open_session(
            parent_request_id=uuid4(),
            max_model_requests=10,
        )
        result = session.infer(
            _request(parent_request_id=session.parent_request_id),
            output_type=_ProbeOutput,
        )

    assert result.output == _ProbeOutput(value="terrain specialist")
    assert result.selection.selected_runtime is not None
    assert result.selection.selected_runtime.runtime_id == backend.runtime_id
    assert result.execution_record.runtime_id == backend.runtime_id
    assert result.execution_record.model_id == backend.model_id
    assert result.execution_record.model_request_count == 1
    assert result.execution_record.status == "completed"
    assert session.remaining_model_requests == 9


def test_model_gateway_exposes_queryable_runtime_capability_matrix() -> None:
    selected_profiles = tuple(
        profile
        for profile in default_runtime_profiles()
        if profile.tier
        in {ModelRuntimeTier.HAILO_LOCAL, ModelRuntimeTier.LOCAL_REASONING}
    )
    backends = tuple(
        _RecordingBackend(
            runtime_id=profile.runtime_id,
            model_id=profile.model_id,
        )
        for profile in selected_profiles
    )

    with ScoutModelGateway(
        profiles=selected_profiles,
        backends=backends,
    ) as gateway:
        matrix = gateway.capability_matrix()

    by_tier = {entry.tier: entry for entry in matrix}
    hailo = by_tier[ModelRuntimeTier.HAILO_LOCAL]
    ollama = by_tier[ModelRuntimeTier.LOCAL_REASONING]
    assert hailo.capabilities == frozenset(
        {
            ModelRuntimeCapability.CHAT,
            ModelRuntimeCapability.SMALL_TYPED_OUTPUT,
            ModelRuntimeCapability.OFFLINE,
        }
    )
    assert hailo.recommended_priority is ModelInferencePriority.NORMAL
    assert ollama.capabilities.issuperset(
        {
            ModelRuntimeCapability.CHAT,
            ModelRuntimeCapability.STRUCTURED_OUTPUT,
            ModelRuntimeCapability.SLOW_BACKGROUND_REASONING,
        }
    )
    assert ollama.runtime_id == "edge.pi.ollama.cpu.background"
    assert ollama.locality is Locality.EDGE
    assert ollama.required_host_kind is ModelRuntimeHostKind.RASPBERRY_PI
    assert ollama.recommended_priority is ModelInferencePriority.BACKGROUND


def test_model_gateway_rejects_backend_model_identity_mismatch() -> None:
    backend = _RecordingBackend()
    mismatched_profile = _profile().model_copy(
        update={"model_id": "different-model"}
    )

    with pytest.raises(ValueError, match="model_id does not match"):
        ScoutModelGateway(
            profiles=(mismatched_profile,),
            backends=(backend,),
        )


def test_model_gateway_serializes_two_sessions_on_one_resident_local_model() -> None:
    backend = _RecordingBackend(delay_seconds=0.08)
    with ScoutModelGateway(
        profiles=(_profile(),),
        backends=(backend,),
        max_local_concurrency=1,
    ) as gateway:
        sessions = [
            gateway.open_session(
                parent_request_id=uuid4(),
                max_model_requests=10,
            )
            for _ in range(2)
        ]
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    session.infer,
                    _request(
                        task=f"specialist-{index}",
                        parent_request_id=session.parent_request_id,
                    ),
                    output_type=_ProbeOutput,
                )
                for index, session in enumerate(sessions)
            ]
            outputs = [future.result().output.value for future in futures]

    assert outputs == ["specialist-0", "specialist-1"]
    assert backend.calls == 2
    assert backend.max_active == 1


def test_model_gateway_shared_session_stops_at_ten_actual_model_requests() -> None:
    backend = _RecordingBackend()
    with ScoutModelGateway(
        profiles=(_profile(),),
        backends=(backend,),
    ) as gateway:
        session = gateway.open_session(
            parent_request_id=uuid4(),
            max_model_requests=10,
        )
        for index in range(10):
            session.infer(
                _request(
                    task=f"specialist-{index}",
                    parent_request_id=session.parent_request_id,
                ),
                output_type=_ProbeOutput,
            )

        with pytest.raises(ModelRequestBudgetExceeded):
            session.infer(
                _request(
                    task="eleventh",
                    parent_request_id=session.parent_request_id,
                ),
                output_type=_ProbeOutput,
            )

    assert backend.calls == 10
    assert session.remaining_model_requests == 0


def test_model_gateway_rejects_malformed_structured_output_and_records_failure() -> None:
    backend = _RecordingBackend(output={"wrong": "shape"})
    with ScoutModelGateway(
        profiles=(_profile(),),
        backends=(backend,),
    ) as gateway:
        session = gateway.open_session(
            parent_request_id=uuid4(),
            max_model_requests=10,
        )

        with pytest.raises(ModelOutputValidationError):
            session.infer(
                _request(parent_request_id=session.parent_request_id),
                output_type=_ProbeOutput,
            )

    assert session.records[-1].status == "failed"
    assert session.records[-1].model_request_count == 1


def test_model_gateway_accounts_for_backend_budget_overrun_and_fails_closed() -> None:
    backend = _RecordingBackend(model_request_count=11)
    with ScoutModelGateway(
        profiles=(_profile(),),
        backends=(backend,),
    ) as gateway:
        session = gateway.open_session(
            parent_request_id=uuid4(),
            max_model_requests=10,
        )

        with pytest.raises(ModelRequestBudgetExceeded):
            session.infer(
                _request(parent_request_id=session.parent_request_id),
                output_type=_ProbeOutput,
            )

        with pytest.raises(ModelRequestBudgetExceeded):
            session.infer(
                _request(parent_request_id=session.parent_request_id),
                output_type=_ProbeOutput,
            )

    assert backend.calls == 1
    assert session.records[-1].status == "failed"
    assert session.records[-1].model_request_count == 11
    assert session.remaining_model_requests == 0


def test_model_gateway_cancelled_session_never_reaches_backend() -> None:
    backend = _RecordingBackend()
    with ScoutModelGateway(
        profiles=(_profile(),),
        backends=(backend,),
    ) as gateway:
        session = gateway.open_session(
            parent_request_id=uuid4(),
            max_model_requests=10,
        )
        session.cancel()

        with pytest.raises(ModelSessionCancelled):
            session.infer(
                _request(parent_request_id=session.parent_request_id),
                output_type=_ProbeOutput,
            )

    assert backend.calls == 0
    assert session.records == ()


def test_model_gateway_timeout_cancels_queued_request() -> None:
    backend = _RecordingBackend(delay_seconds=0.2)
    with ScoutModelGateway(
        profiles=(_profile(),),
        backends=(backend,),
        max_local_concurrency=1,
    ) as gateway:
        first = gateway.open_session(
            parent_request_id=uuid4(),
            max_model_requests=10,
        )
        second = gateway.open_session(
            parent_request_id=uuid4(),
            max_model_requests=10,
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            first_future = executor.submit(
                first.infer,
                _request(
                    task="occupy-model",
                    timeout_seconds=1,
                    parent_request_id=first.parent_request_id,
                ),
                output_type=_ProbeOutput,
            )
            assert backend.started.wait(timeout=1)
            with pytest.raises(ModelInferenceTimeout):
                second.infer(
                    _request(
                        task="queued",
                        timeout_seconds=0.05,
                        parent_request_id=second.parent_request_id,
                    ),
                    output_type=_ProbeOutput,
                )
            first_future.result()

    assert backend.calls == 1
    assert second.records[-1].status == "timed_out"


def test_pydantic_ai_backend_uses_one_resident_model_for_typed_output() -> None:
    calls: list[str] = []

    def model_function(
        messages: list[object],
        info: AgentInfo,
    ) -> ModelResponse:
        del messages
        calls.append("called")
        output_tool = info.output_tools[0]
        args: Any = {"value": "typed-through-pydantic-ai"}
        if output_tool.outer_typed_dict_key:
            args = {output_tool.outer_typed_dict_key: args}
        return ModelResponse(
            parts=[
                ToolCallPart(
                    output_tool.name,
                    args,
                    tool_call_id="model-gateway-output",
                )
            ],
            model_name="resident-function-model",
        )

    resident_model = FunctionModel(
        model_function,
        model_name="resident-function-model",
    )
    backend = PydanticAIStructuredBackend(
        runtime_id="local.fast.function",
        model_id="resident-function-model",
        model=resident_model,
    )
    with ScoutModelGateway(
        profiles=(
            _profile().model_copy(
                update={"model_id": "resident-function-model"}
            ),
        ),
        backends=(backend,),
    ) as gateway:
        session = gateway.open_session(
            parent_request_id=uuid4(),
            max_model_requests=10,
        )
        result = session.infer(
            _request(
                parent_request_id=session.parent_request_id,
                timeout_seconds=10,
            ),
            output_type=_ProbeOutput,
        )

    assert result.output.value == "typed-through-pydantic-ai"
    assert calls == ["called"]
    assert backend.resident_model is resident_model
    assert result.execution_record.model_request_count == 1


def test_model_runtime_request_rejects_call_ceiling_below_ten() -> None:
    with pytest.raises(ValidationError):
        ModelRuntimeRequest(
            request_id=uuid4(),
            task="invalid low budget",
            max_model_requests=9,
        )
