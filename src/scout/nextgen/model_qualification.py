"""Executable qualification for one explicit OpenAI-compatible model runtime."""

from __future__ import annotations

import hashlib
import json
import resource
import sys
import time
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from scout.agents.pydantic_ai_compat import pydantic_result_output
from scout.nextgen.intelligence_gateway import (
    CapabilityBroker,
    FORBIDDEN_INTELLIGENCE_CAPABILITIES,
    GeoScope,
    IntelligenceRequest,
    IntelligenceTaskType,
    ModelExecutionRecord,
    WorkspaceBinding,
)
from scout.nextgen.intelligence_mcp import (
    IntelligenceGatewayExecution,
    IntelligenceMcpClientConfig,
    IntelligenceTransportStatus,
    McpIntelligenceGateway,
)
from scout.nextgen.model_gateway import (
    ModelGatewayExecutionError,
    ModelInferenceRequest,
    ModelRuntimeUnavailable,
    ScoutModelGateway,
)
from scout.nextgen.model_runtime import (
    ModelCapabilityAttestation,
    ModelRuntimeCapability,
    ModelRuntimeProfile,
)
from scout.nextgen.openai_compatible_backend import (
    OpenAICompatibleBackendConfig,
    OpenAICompatiblePydanticBackend,
)
from scout.nextgen.praison_service import EvidenceCatalog
from scout.schemas.base import NonEmptyStr, SchemaModel

MAX_QUALIFICATION_CASE_BYTES = 64 * 1024
QUALIFICATION_EXPERIMENT_ID = "SCOUT-AI-EXP-MODEL-RUNTIME-QUAL-005"
_BASIC_CHAT_MARKER = "SCOUT_BASIC_CHAT_OK"
_TYPED_OUTPUT_MARKER = "SCOUT_TYPED_OUTPUT_OK"
TOOL_CALLING_PROBE_NAME = "read_terrain_qualification_evidence"
TOOL_CALLING_EVIDENCE_REF = "qualification:terrain:ridge-candidate"
TOOL_CALLING_OUTPUT_MARKER = "SCOUT_TOOL_CALLING_OK"
MODEL_CAPABILITY_ATTESTATION_TTL_SECONDS = 24 * 60 * 60
_CHECK_ORDER = (
    "configuration",
    "basic_chat",
    "typed_output",
    "tool_calling",
    "praison_mcp",
    "authority_boundary",
)
_UNAVAILABLE_ERROR_TYPES = frozenset(
    {
        "APIConnectionError",
        "ConnectError",
        "ConnectionRefusedError",
    }
)
_TIMEOUT_ERROR_TYPES = frozenset(
    {
        "APITimeoutError",
        "ConnectTimeout",
        "InferenceSchedulerTimeout",
        "ReadTimeout",
        "TimeoutError",
    }
)


class ModelQualificationStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    UNAVAILABLE = "unavailable"
    NOT_RUN = "not_run"


class ModelQualificationDisposition(StrEnum):
    PASSED = "passed"
    PARTIAL = "partial"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    UNAVAILABLE = "unavailable"


class ModelRuntimeQualificationCase(SchemaModel):
    case_id: NonEmptyStr
    workspace_id: NonEmptyStr
    workspace_revision: NonEmptyStr
    mission_id: NonEmptyStr
    mission_version: NonEmptyStr
    route_id: NonEmptyStr
    route_version: NonEmptyStr
    question: NonEmptyStr
    geographic_scope: GeoScope
    evidence_refs: tuple[NonEmptyStr, ...]
    allowed_capabilities: tuple[NonEmptyStr, ...]
    expected_min_findings: int = Field(default=1, ge=1)
    expected_tool_calls: tuple[NonEmptyStr, ...] = ()
    max_runtime_seconds: int = Field(default=30, ge=1, le=300)
    max_model_requests: int = Field(default=10, ge=10)
    timeout_seconds: float = Field(default=30, ge=0.25, le=300)
    privacy_sensitive: bool = True
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @model_validator(mode="after")
    def validate_case_boundary(self) -> "ModelRuntimeQualificationCase":
        if self.geographic_scope.route_id not in {None, self.route_id}:
            raise ValueError("qualification geographic route must match the case")
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("qualification evidence refs must be unique")
        if len(self.allowed_capabilities) != len(set(self.allowed_capabilities)):
            raise ValueError("qualification capabilities must be unique")
        if len(self.expected_tool_calls) != len(set(self.expected_tool_calls)):
            raise ValueError("qualification expected tool calls must be unique")
        forbidden = set(self.allowed_capabilities).intersection(
            FORBIDDEN_INTELLIGENCE_CAPABILITIES
        )
        if forbidden:
            raise ValueError("qualification case requested a forbidden capability")
        if not set(self.expected_tool_calls).issubset(self.allowed_capabilities):
            raise ValueError("expected tool calls must be allowed by the case")
        return self

    @classmethod
    def from_json_file(cls, path: Path) -> "ModelRuntimeQualificationCase":
        raw = path.read_bytes()
        if len(raw) > MAX_QUALIFICATION_CASE_BYTES:
            raise ValueError("model qualification case exceeds the Scout size limit")
        return cls.model_validate_json(raw)


class ModelQualificationCheck(SchemaModel):
    check_id: NonEmptyStr
    status: ModelQualificationStatus
    summary: NonEmptyStr
    started_at: datetime
    completed_at: datetime
    latency_ms: int = Field(ge=0)
    model_request_count: int = Field(default=0, ge=0)
    tool_call_count: int = Field(default=0, ge=0)
    tools_called: tuple[NonEmptyStr, ...] = ()
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    requested_model_id: NonEmptyStr | None = None
    observed_model_id: NonEmptyStr | None = None
    output_hash: NonEmptyStr | None = None
    error_type: NonEmptyStr | None = None
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @model_validator(mode="after")
    def validate_check_timing(self) -> "ModelQualificationCheck":
        if _as_utc(self.completed_at) < _as_utc(self.started_at):
            raise ValueError("qualification check completed before it started")
        if self.tool_call_count != len(self.tools_called):
            raise ValueError("tool_call_count must match the audited tool call list")
        return self


class QualificationResourceRecord(SchemaModel):
    wall_latency_ms: int = Field(ge=0)
    parent_peak_rss_bytes_before: int | None = Field(default=None, ge=0)
    parent_peak_rss_bytes_after: int | None = Field(default=None, ge=0)
    memory_scope: Literal["qualification_parent_ru_maxrss"] = (
        "qualification_parent_ru_maxrss"
    )


class ModelRuntimeQualificationReport(SchemaModel):
    schema_version: Literal["scout.model_runtime_qualification.v1"] = (
        "scout.model_runtime_qualification.v1"
    )
    experiment_id: Literal["SCOUT-AI-EXP-MODEL-RUNTIME-QUAL-005"] = (
        QUALIFICATION_EXPERIMENT_ID
    )
    qualification_id: UUID = Field(default_factory=uuid4)
    generated_at: datetime
    disposition: ModelQualificationDisposition
    runtime_id: NonEmptyStr
    provider: NonEmptyStr
    requested_model_id: NonEmptyStr
    accepted_observed_model_ids: tuple[NonEmptyStr, ...]
    transport_scope: NonEmptyStr
    locality: NonEmptyStr
    accelerator: NonEmptyStr
    endpoint_sha256: NonEmptyStr
    runtime_config_sha256: NonEmptyStr
    case_sha256: NonEmptyStr
    evidence_catalog_sha256: NonEmptyStr
    case_id: NonEmptyStr
    request_id: UUID
    workspace_binding: WorkspaceBinding
    checks: tuple[ModelQualificationCheck, ...]
    resources: QualificationResourceRecord
    intelligence_execution: IntelligenceGatewayExecution | None = None
    report_hash: NonEmptyStr
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @model_validator(mode="after")
    def validate_report_shape(self) -> "ModelRuntimeQualificationReport":
        if tuple(check.check_id for check in self.checks) != _CHECK_ORDER:
            raise ValueError("qualification checks are missing or out of order")
        if self.disposition is ModelQualificationDisposition.PASSED:
            if any(
                check.status is not ModelQualificationStatus.PASSED
                for check in self.checks
            ):
                raise ValueError("passed qualification requires every check to pass")
            if self.intelligence_execution is None:
                raise ValueError("passed qualification requires MCP intelligence output")
        return self


class _TypedQualificationOutput(SchemaModel):
    marker: Literal["SCOUT_TYPED_OUTPUT_OK"]
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


def run_openai_compatible_qualification(
    *,
    runtime_config_path: Path,
    case_path: Path,
    evidence_catalog_path: Path,
    python_executable: str = sys.executable,
    pythonpath: str | None = None,
    stop_after: Literal["basic_chat", "typed_output", "tool_calling"] | None = None,
    continue_after_tool_failure: bool = False,
) -> ModelRuntimeQualificationReport:
    started_monotonic = time.monotonic()
    rss_before = _peak_rss_bytes()
    config = OpenAICompatibleBackendConfig.from_json_file(runtime_config_path)
    case = ModelRuntimeQualificationCase.from_json_file(case_path)
    catalog = EvidenceCatalog.from_json_file(evidence_catalog_path)
    request = _build_intelligence_request(case, catalog)
    checks = [_configuration_check(config)]
    execution: IntelligenceGatewayExecution | None = None

    basic_backend = OpenAICompatiblePydanticBackend(config=config)
    try:
        basic_check = _run_basic_chat_probe(basic_backend, config, case)
    finally:
        basic_backend.close()
    checks.append(basic_check)
    if basic_check.status is not ModelQualificationStatus.PASSED:
        checks.extend(_not_run_checks("basic chat qualification did not pass"))
        return _build_report(
            config=config,
            case=case,
            request=request,
            checks=checks,
            execution=None,
            disposition=_failure_disposition(basic_check.status),
            runtime_config_path=runtime_config_path,
            case_path=case_path,
            evidence_catalog_path=evidence_catalog_path,
            started_monotonic=started_monotonic,
            rss_before=rss_before,
        )
    if stop_after == "basic_chat":
        checks.extend(_not_run_checks("qualification stopped after basic chat"))
        return _build_report(
            config=config,
            case=case,
            request=request,
            checks=checks,
            execution=None,
            disposition=ModelQualificationDisposition.PARTIAL,
            runtime_config_path=runtime_config_path,
            case_path=case_path,
            evidence_catalog_path=evidence_catalog_path,
            started_monotonic=started_monotonic,
            rss_before=rss_before,
        )

    typed_backend = OpenAICompatiblePydanticBackend(config=config)
    with ScoutModelGateway(
        profiles=(config.to_runtime_profile(),),
        backends=(typed_backend,),
        max_local_concurrency=1,
        max_cloud_concurrency=(
            config.max_concurrency if config.locality.value == "cloud" else 1
        ),
    ) as gateway:
        typed_check = _run_typed_output_probe(gateway, config, case, request.request_id)
    checks.append(typed_check)
    if typed_check.status is not ModelQualificationStatus.PASSED:
        checks.extend(
            _not_run_checks(
                "typed output qualification did not pass",
                starting_at="tool_calling",
            )
        )
        return _build_report(
            config=config,
            case=case,
            request=request,
            checks=checks,
            execution=None,
            disposition=_failure_disposition(typed_check.status),
            runtime_config_path=runtime_config_path,
            case_path=case_path,
            evidence_catalog_path=evidence_catalog_path,
            started_monotonic=started_monotonic,
            rss_before=rss_before,
        )
    if stop_after == "typed_output":
        checks.extend(
            _not_run_checks(
                "qualification stopped after typed output",
                starting_at="tool_calling",
            )
        )
        return _build_report(
            config=config,
            case=case,
            request=request,
            checks=checks,
            execution=None,
            disposition=ModelQualificationDisposition.PARTIAL,
            runtime_config_path=runtime_config_path,
            case_path=case_path,
            evidence_catalog_path=evidence_catalog_path,
            started_monotonic=started_monotonic,
            rss_before=rss_before,
        )

    tool_backend = OpenAICompatiblePydanticBackend(config=config)
    try:
        tool_check = _run_tool_calling_probe(tool_backend, config, case)
    finally:
        tool_backend.close()
    checks.append(tool_check)
    if (
        tool_check.status is not ModelQualificationStatus.PASSED
        and (not continue_after_tool_failure or stop_after == "tool_calling")
    ):
        checks.extend(
            _not_run_checks(
                "tool calling qualification did not pass",
                starting_at="praison_mcp",
            )
        )
        return _build_report(
            config=config,
            case=case,
            request=request,
            checks=checks,
            execution=None,
            disposition=_failure_disposition(tool_check.status),
            runtime_config_path=runtime_config_path,
            case_path=case_path,
            evidence_catalog_path=evidence_catalog_path,
            started_monotonic=started_monotonic,
            rss_before=rss_before,
        )
    if stop_after == "tool_calling":
        checks.extend(
            _not_run_checks(
                "qualification stopped after tool calling",
                starting_at="praison_mcp",
            )
        )
        return _build_report(
            config=config,
            case=case,
            request=request,
            checks=checks,
            execution=None,
            disposition=ModelQualificationDisposition.PARTIAL,
            runtime_config_path=runtime_config_path,
            case_path=case_path,
            evidence_catalog_path=evidence_catalog_path,
            started_monotonic=started_monotonic,
            rss_before=rss_before,
        )

    execution, mcp_check = _run_praison_mcp_probe(
        config=config,
        case=case,
        request=request,
        runtime_config_path=runtime_config_path,
        evidence_catalog_path=evidence_catalog_path,
        python_executable=python_executable,
        pythonpath=pythonpath,
    )
    checks.append(mcp_check)
    authority_check = _authority_check(execution)
    checks.append(authority_check)
    failed_check = next(
        (
            check
            for check in checks
            if check.status is not ModelQualificationStatus.PASSED
        ),
        None,
    )
    disposition = (
        ModelQualificationDisposition.PASSED
        if failed_check is None
        else _failure_disposition(failed_check.status)
    )
    return _build_report(
        config=config,
        case=case,
        request=request,
        checks=checks,
        execution=execution,
        disposition=disposition,
        runtime_config_path=runtime_config_path,
        case_path=case_path,
        evidence_catalog_path=evidence_catalog_path,
        started_monotonic=started_monotonic,
        rss_before=rss_before,
    )


def qualification_report_hash(report: ModelRuntimeQualificationReport) -> str:
    payload = report.model_dump(mode="json")
    payload.pop("report_hash", None)
    return _canonical_hash(payload)


def build_model_capability_attestation(
    report: ModelRuntimeQualificationReport,
    *,
    ttl_seconds: int = MODEL_CAPABILITY_ATTESTATION_TTL_SECONDS,
) -> ModelCapabilityAttestation:
    """Promote only independently qualified model capabilities."""

    if ttl_seconds <= 0:
        raise ValueError("model capability attestation ttl must be positive")
    if qualification_report_hash(report) != report.report_hash:
        raise ValueError("qualification report hash does not validate")
    checks = {check.check_id: check for check in report.checks}
    required_passes = ("configuration", "basic_chat", "typed_output", "tool_calling")
    if any(
        checks[check_id].status is not ModelQualificationStatus.PASSED
        for check_id in required_passes
    ):
        raise ValueError("tool calling capability was not independently qualified")
    tool_check = checks["tool_calling"]
    if (
        tool_check.tool_call_count != 1
        or tool_check.tools_called != (TOOL_CALLING_PROBE_NAME,)
        or tool_check.model_request_count < 2
    ):
        raise ValueError("tool calling qualification trace is incomplete")
    qualified_at = tool_check.completed_at
    return ModelCapabilityAttestation(
        runtime_id=report.runtime_id,
        provider=report.provider,
        model_id=report.requested_model_id,
        runtime_config_sha256=report.runtime_config_sha256,
        qualification_report_hash=report.report_hash,
        capabilities=frozenset({ModelRuntimeCapability.TOOL_CALLING}),
        qualified_at=qualified_at,
        expires_at=qualified_at + timedelta(seconds=ttl_seconds),
    )


def apply_model_capability_attestation(
    *,
    config: OpenAICompatibleBackendConfig,
    runtime_config_path: Path,
    attestation: ModelCapabilityAttestation,
    now: datetime | None = None,
) -> ModelRuntimeProfile:
    """Build a selectable profile only after binding and expiry validation."""

    if attestation.is_expired(now=now):
        raise ValueError("model capability attestation is expired")
    if (
        attestation.runtime_id != config.runtime_id
        or attestation.provider != config.provider
        or attestation.model_id != config.model_id
    ):
        raise ValueError("model capability attestation runtime binding mismatch")
    if attestation.runtime_config_sha256 != _file_hash(runtime_config_path):
        raise ValueError("model capability attestation config hash mismatch")
    profile = config.to_runtime_profile()
    return profile.model_copy(
        update={
            "capabilities": frozenset(
                {*profile.capabilities, *attestation.capabilities}
            ),
            "capability_attestation_refs": (
                attestation.qualification_report_hash,
            ),
        }
    )


def _configuration_check(
    config: OpenAICompatibleBackendConfig,
) -> ModelQualificationCheck:
    now = datetime.now(UTC)
    return ModelQualificationCheck(
        check_id="configuration",
        status=ModelQualificationStatus.PASSED,
        summary="Typed runtime configuration passed Scout validation.",
        started_at=now,
        completed_at=now,
        latency_ms=0,
        requested_model_id=config.model_id,
    )


def _run_basic_chat_probe(
    backend: OpenAICompatiblePydanticBackend,
    config: OpenAICompatibleBackendConfig,
    case: ModelRuntimeQualificationCase,
) -> ModelQualificationCheck:
    from pydantic_ai import Agent, UsageLimits

    started_at = datetime.now(UTC)
    started_monotonic = time.monotonic()
    model = backend.resident_model
    request_scope = model.begin_request_scope()
    request_count = 0
    try:
        agent = Agent(
            model,
            output_type=str,
            instructions=(
                "This is a non-authoritative Scout model transport qualification. "
                "Return the requested marker exactly and do not claim any action authority."
            ),
            retries=10,
        )
        result = agent.run_sync(
            f"Return exactly this marker: {_BASIC_CHAT_MARKER}",
            model_settings=config.model_settings(
                timeout_seconds=case.timeout_seconds,
            ),
            usage_limits=UsageLimits(request_limit=10, tool_calls_limit=10),
        )
        request_count = model.finish_request_scope(request_scope)
        text = str(pydantic_result_output(result)).strip()
        observed_model_id = _observed_model_id(result)
        usage = _result_usage(result)
        if text != _BASIC_CHAT_MARKER:
            return _check(
                check_id="basic_chat",
                status=ModelQualificationStatus.FAILED,
                summary="The endpoint did not follow the bounded basic chat probe.",
                started_at=started_at,
                started_monotonic=started_monotonic,
                config=config,
                request_count=request_count,
                usage=usage,
                observed_model_id=observed_model_id,
                output_hash=_text_hash(text),
                error_type="BasicChatMarkerMismatch",
            )
        if not _observed_model_is_allowed(config, observed_model_id):
            return _check(
                check_id="basic_chat",
                status=ModelQualificationStatus.FAILED,
                summary="The endpoint returned an unapproved observed model identity.",
                started_at=started_at,
                started_monotonic=started_monotonic,
                config=config,
                request_count=request_count,
                usage=usage,
                observed_model_id=observed_model_id,
                output_hash=_text_hash(text),
                error_type="ObservedModelMismatch",
            )
        return _check(
            check_id="basic_chat",
            status=ModelQualificationStatus.PASSED,
            summary="Basic chat transport and observed model identity passed.",
            started_at=started_at,
            started_monotonic=started_monotonic,
            config=config,
            request_count=request_count,
            usage=usage,
            observed_model_id=observed_model_id,
            output_hash=_text_hash(text),
        )
    except Exception as exc:
        if request_count == 0:
            request_count = model.finish_request_scope(request_scope)
        error_type = _root_error_type(exc)
        status = _error_status(error_type)
        return _check(
            check_id="basic_chat",
            status=status,
            summary=(
                "The configured model endpoint was unavailable."
                if status is ModelQualificationStatus.UNAVAILABLE
                else (
                    "The configured model endpoint timed out."
                    if status is ModelQualificationStatus.TIMED_OUT
                    else "The configured endpoint failed the basic chat probe."
                )
            ),
            started_at=started_at,
            started_monotonic=started_monotonic,
            config=config,
            request_count=request_count,
            error_type=error_type,
        )


def _run_typed_output_probe(
    gateway: ScoutModelGateway,
    config: OpenAICompatibleBackendConfig,
    case: ModelRuntimeQualificationCase,
    parent_request_id: UUID,
) -> ModelQualificationCheck:
    started_at = datetime.now(UTC)
    started_monotonic = time.monotonic()
    session = gateway.open_session(
        parent_request_id=parent_request_id,
        max_model_requests=case.max_model_requests,
    )
    profile = config.to_runtime_profile()
    typed_output_capability = (
        ModelRuntimeCapability.SMALL_TYPED_OUTPUT
        if ModelRuntimeCapability.SMALL_TYPED_OUTPUT in profile.capabilities
        else ModelRuntimeCapability.STRUCTURED_OUTPUT
    )
    request = ModelInferenceRequest(
        parent_request_id=parent_request_id,
        task="Scout OpenAI-compatible typed output qualification",
        prompt=(
            "Return exactly one JSON object: "
            '{"marker":"SCOUT_TYPED_OUTPUT_OK","candidate_only":true,'
            '"runtime_safety_truth":false}. '
            "Do not include Markdown or any text before or after the object."
        ),
        required_capabilities=frozenset(
            {
                ModelRuntimeCapability.CHAT,
                typed_output_capability,
            }
        ),
        allowed_tiers=frozenset({config.tier}),
        prefer_local=config.locality.value != "cloud",
        allow_cloud=config.locality.value == "cloud",
        requires_offline=config.offline_capable,
        privacy_sensitive=case.privacy_sensitive,
        timeout_seconds=case.timeout_seconds,
    )
    try:
        result = session.infer(request, output_type=_TypedQualificationOutput)
    except ModelGatewayExecutionError as exc:
        status = _error_status(exc.record.error_type)
        return _check_from_execution_record(
            check_id="typed_output",
            status=status,
            summary="The endpoint failed the typed Pydantic output probe.",
            record=exc.record,
            error_type=exc.record.error_type or type(exc).__name__,
        )
    except ModelRuntimeUnavailable as exc:
        return _check(
            check_id="typed_output",
            status=ModelQualificationStatus.FAILED,
            summary="Model policy routing rejected the configured runtime.",
            started_at=started_at,
            started_monotonic=started_monotonic,
            config=config,
            error_type=type(exc).__name__,
        )
    record = result.execution_record
    if not _observed_model_is_allowed(config, record.observed_model_id):
        return _check_from_execution_record(
            check_id="typed_output",
            status=ModelQualificationStatus.FAILED,
            summary="Typed output used an unapproved observed model identity.",
            record=record,
            output_hash=_canonical_hash(result.output.model_dump(mode="json")),
            error_type="ObservedModelMismatch",
        )
    return _check_from_execution_record(
        check_id="typed_output",
        status=ModelQualificationStatus.PASSED,
        summary=(
            "Structured output, Pydantic validation, and typed authority flags passed."
        ),
        record=record,
        output_hash=_canonical_hash(result.output.model_dump(mode="json")),
    )


def _run_tool_calling_probe(
    backend: OpenAICompatiblePydanticBackend,
    config: OpenAICompatibleBackendConfig,
    case: ModelRuntimeQualificationCase,
) -> ModelQualificationCheck:
    """Prove one model-selected read tool call independently of PraisonAI."""

    from pydantic_ai import Agent, UsageLimits

    started_at = datetime.now(UTC)
    started_monotonic = time.monotonic()
    model = backend.resident_model
    request_scope = model.begin_request_scope()
    request_count = 0
    invocations: list[tuple[str, str]] = []
    agent = Agent(
        model,
        output_type=str,
        instructions=(
            "This is a bounded, read-only Scout tool-calling qualification. "
            f"You must call {TOOL_CALLING_PROBE_NAME} exactly once with the "
            f"evidence_ref {TOOL_CALLING_EVIDENCE_REF}. After reading the tool "
            "result, do not call any tool again. Return the tool result's "
            f"required_final_output value, exactly {TOOL_CALLING_OUTPUT_MARKER}. "
            "Do not infer or claim any runtime, route, permission, notification, "
            "emergency, device, or safety authority."
        ),
        retries=10,
    )

    @agent.tool_plain
    def read_terrain_qualification_evidence(evidence_ref: str) -> str:
        invocations.append((TOOL_CALLING_PROBE_NAME, evidence_ref))
        if evidence_ref != TOOL_CALLING_EVIDENCE_REF:
            return json.dumps(
                {
                    "status": "unknown",
                    "evidence_ref": evidence_ref,
                    "tool_call_complete": True,
                    "required_final_output": TOOL_CALLING_OUTPUT_MARKER,
                    "next_action": "return required_final_output without another tool call",
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                },
                sort_keys=True,
            )
        return json.dumps(
            {
                "status": "available",
                "evidence_ref": TOOL_CALLING_EVIDENCE_REF,
                "summary": "Candidate ridge evidence is available for qualification.",
                "tool_call_complete": True,
                "required_final_output": TOOL_CALLING_OUTPUT_MARKER,
                "next_action": "return required_final_output without another tool call",
                "candidate_only": True,
                "runtime_safety_truth": False,
            },
            sort_keys=True,
        )

    try:
        result = agent.run_sync(
            (
                "Use the required Scout read tool before returning the fixed "
                f"marker {TOOL_CALLING_OUTPUT_MARKER}."
            ),
            model_settings=config.model_settings(
                timeout_seconds=case.timeout_seconds,
            ),
            usage_limits=UsageLimits(request_limit=10, tool_calls_limit=10),
        )
        request_count = model.finish_request_scope(request_scope)
        text = str(pydantic_result_output(result)).strip()
        observed_model_id = _observed_model_id(result)
        usage = _result_usage(result)
        tool_names = tuple(name for name, _ in invocations)
        if text != TOOL_CALLING_OUTPUT_MARKER:
            return _check(
                check_id="tool_calling",
                status=ModelQualificationStatus.FAILED,
                summary="The model did not return the tool-calling completion marker.",
                started_at=started_at,
                started_monotonic=started_monotonic,
                config=config,
                request_count=request_count,
                tool_call_count=len(invocations),
                tools_called=tool_names,
                usage=usage,
                observed_model_id=observed_model_id,
                output_hash=_text_hash(text),
                error_type="ToolCallingMarkerMismatch",
            )
        if invocations != [
            (TOOL_CALLING_PROBE_NAME, TOOL_CALLING_EVIDENCE_REF)
        ]:
            return _check(
                check_id="tool_calling",
                status=ModelQualificationStatus.FAILED,
                summary=(
                    "The model returned the marker without the exact bounded tool call."
                ),
                started_at=started_at,
                started_monotonic=started_monotonic,
                config=config,
                request_count=request_count,
                tool_call_count=len(invocations),
                tools_called=tool_names,
                usage=usage,
                observed_model_id=observed_model_id,
                output_hash=_text_hash(text),
                error_type=(
                    "ToolCallingProbeNotExecuted"
                    if not invocations
                    else "ToolCallingContractMismatch"
                ),
            )
        if not _observed_model_is_allowed(config, observed_model_id):
            return _check(
                check_id="tool_calling",
                status=ModelQualificationStatus.FAILED,
                summary="Tool calling used an unapproved observed model identity.",
                started_at=started_at,
                started_monotonic=started_monotonic,
                config=config,
                request_count=request_count,
                tool_call_count=1,
                tools_called=tool_names,
                usage=usage,
                observed_model_id=observed_model_id,
                output_hash=_text_hash(text),
                error_type="ObservedModelMismatch",
            )
        return _check(
            check_id="tool_calling",
            status=ModelQualificationStatus.PASSED,
            summary=(
                "The model selected one bounded read tool and consumed its result."
            ),
            started_at=started_at,
            started_monotonic=started_monotonic,
            config=config,
            request_count=request_count,
            tool_call_count=1,
            tools_called=tool_names,
            usage=usage,
            observed_model_id=observed_model_id,
            output_hash=_text_hash(text),
        )
    except Exception as exc:
        if request_count == 0:
            request_count = model.finish_request_scope(request_scope)
        error_type = _root_error_type(exc)
        status = _error_status(error_type)
        return _check(
            check_id="tool_calling",
            status=status,
            summary="The endpoint failed the independent tool-calling probe.",
            started_at=started_at,
            started_monotonic=started_monotonic,
            config=config,
            request_count=request_count,
            tool_call_count=len(invocations),
            tools_called=tuple(name for name, _ in invocations),
            error_type=error_type,
        )


def _run_praison_mcp_probe(
    *,
    config: OpenAICompatibleBackendConfig,
    case: ModelRuntimeQualificationCase,
    request: IntelligenceRequest,
    runtime_config_path: Path,
    evidence_catalog_path: Path,
    python_executable: str,
    pythonpath: str | None,
) -> tuple[IntelligenceGatewayExecution, ModelQualificationCheck]:
    started_at = datetime.now(UTC)
    started_monotonic = time.monotonic()
    command = (
        python_executable,
        "-m",
        "scout.nextgen.intelligence_mcp_server",
        "--mode",
        "praison-openai-compatible",
        "--evidence-catalog",
        str(evidence_catalog_path),
        "--model-runtime-config",
        str(runtime_config_path),
    )
    credential_names = (config.api_key_env,) if config.api_key_env else ()
    with McpIntelligenceGateway(
        IntelligenceMcpClientConfig(
            command=command,
            timeout_seconds=min(300, max(0.25, case.max_runtime_seconds + 5)),
            pythonpath=pythonpath,
            credential_env_names=credential_names,
        )
    ) as gateway:
        execution = gateway.execute(
            request,
            current_binding=request.workspace_binding,
        )
    records = execution.response.provenance.model_execution_records
    request_count = sum(record.model_request_count for record in records)
    observed_ids = {
        record.observed_model_id
        for record in records
        if record.observed_model_id is not None
    }
    observed_model_id = next(iter(observed_ids)) if len(observed_ids) == 1 else None
    error_type = next(
        (record.error_type for record in records if record.error_type),
        None,
    )
    timed_out = (
        execution.status is IntelligenceTransportStatus.TIMEOUT
        or error_type in _TIMEOUT_ERROR_TYPES
    )
    unavailable = (
        execution.status is IntelligenceTransportStatus.UNAVAILABLE
        or error_type in _UNAVAILABLE_ERROR_TYPES
    )
    tools = set(execution.response.provenance.tools_called)
    model_ids_valid = bool(records) and all(
        record.model_id == config.model_id
        and _observed_model_is_allowed(config, record.observed_model_id)
        for record in records
    )
    passed = (
        execution.status is IntelligenceTransportStatus.OK
        and not execution.degraded
        and len(execution.response.findings) >= case.expected_min_findings
        and set(case.expected_tool_calls).issubset(tools)
        and 1 <= request_count <= case.max_model_requests
        and model_ids_valid
    )
    status = (
        ModelQualificationStatus.PASSED
        if passed
        else (
            ModelQualificationStatus.TIMED_OUT
            if timed_out
            else (
                ModelQualificationStatus.UNAVAILABLE
                if unavailable
                else ModelQualificationStatus.FAILED
            )
        )
    )
    return execution, _check(
        check_id="praison_mcp",
        status=status,
        summary=(
            "PraisonAI specialists completed through isolated MCP and the shared model gateway."
            if passed
            else "The PraisonAI MCP intelligence probe did not satisfy the fixed corpus."
        ),
        started_at=started_at,
        started_monotonic=started_monotonic,
        config=config,
        request_count=request_count,
        tool_call_count=len(tools),
        tools_called=tuple(sorted(tools)),
        input_tokens=_sum_optional(record.input_tokens for record in records),
        output_tokens=_sum_optional(record.output_tokens for record in records),
        observed_model_id=observed_model_id,
        output_hash=execution.response.provenance.output_hash,
        error_type=error_type or (None if passed else "PraisonMcpQualificationFailed"),
    )


def _authority_check(
    execution: IntelligenceGatewayExecution,
) -> ModelQualificationCheck:
    started_at = datetime.now(UTC)
    response = execution.response
    accepted = bool(
        execution.remote_validation is not None
        and execution.remote_validation.accepted
        and response.candidate_only is True
        and response.runtime_safety_truth is False
        and all(finding.candidate_only is True for finding in response.findings)
        and all(evidence.candidate_only is True for evidence in response.evidence)
    )
    return ModelQualificationCheck(
        check_id="authority_boundary",
        status=(
            ModelQualificationStatus.PASSED
            if accepted
            else ModelQualificationStatus.FAILED
        ),
        summary=(
            "Pydantic Contract Gateway preserved the candidate-only authority boundary."
            if accepted
            else "The intelligence response did not pass the authority boundary check."
        ),
        started_at=started_at,
        completed_at=datetime.now(UTC),
        latency_ms=0,
        output_hash=response.provenance.output_hash,
        error_type=None if accepted else "AuthorityBoundaryRejected",
    )


def _build_intelligence_request(
    case: ModelRuntimeQualificationCase,
    catalog: EvidenceCatalog,
) -> IntelligenceRequest:
    available_refs = {item.source_ref for item in catalog.items}
    missing_refs = set(case.evidence_refs).difference(available_refs)
    if missing_refs:
        raise ValueError("qualification evidence catalog is missing required refs")
    request_id = uuid4()
    input_hash = _canonical_hash(
        {
            "case": case.model_dump(mode="json"),
            "catalog": catalog.model_dump(mode="json"),
        }
    )
    binding = WorkspaceBinding(
        workspace_id=case.workspace_id,
        workspace_revision=case.workspace_revision,
        mission_id=case.mission_id,
        mission_version=case.mission_version,
        route_id=case.route_id,
        route_version=case.route_version,
        input_hash=input_hash,
        generated_at=datetime.now(UTC),
    )
    grant = CapabilityBroker().issue_grant(
        request_id=request_id,
        mission_id=case.mission_id,
        task_type=IntelligenceTaskType.TERRAIN_ANALYSIS,
        allowed_capabilities=case.allowed_capabilities,
        evidence_refs_allowed=case.evidence_refs,
        ttl_seconds=case.max_runtime_seconds + 60,
        max_runtime_seconds=case.max_runtime_seconds,
        max_model_requests=case.max_model_requests,
        max_tool_calls=10,
        provenance_ref="scout.model_runtime_qualification.v1",
    )
    return IntelligenceRequest(
        request_id=request_id,
        mission_id=case.mission_id,
        task_type=IntelligenceTaskType.TERRAIN_ANALYSIS,
        question=case.question,
        workspace_binding=binding,
        capability_grant=grant,
        geographic_scope=case.geographic_scope,
        evidence_refs=case.evidence_refs,
        max_runtime_seconds=case.max_runtime_seconds,
        max_model_requests=case.max_model_requests,
    )


def _build_report(
    *,
    config: OpenAICompatibleBackendConfig,
    case: ModelRuntimeQualificationCase,
    request: IntelligenceRequest,
    checks: list[ModelQualificationCheck],
    execution: IntelligenceGatewayExecution | None,
    disposition: ModelQualificationDisposition,
    runtime_config_path: Path,
    case_path: Path,
    evidence_catalog_path: Path,
    started_monotonic: float,
    rss_before: int | None,
) -> ModelRuntimeQualificationReport:
    report = ModelRuntimeQualificationReport(
        generated_at=datetime.now(UTC),
        disposition=disposition,
        runtime_id=config.runtime_id,
        provider=config.provider,
        requested_model_id=config.model_id,
        accepted_observed_model_ids=tuple(
            sorted({config.model_id, *config.accepted_observed_model_ids})
        ),
        transport_scope=config.transport_scope.value,
        locality=config.locality.value,
        accelerator=config.accelerator.value,
        endpoint_sha256=_text_hash(config.normalized_base_url),
        runtime_config_sha256=_file_hash(runtime_config_path),
        case_sha256=_file_hash(case_path),
        evidence_catalog_sha256=_file_hash(evidence_catalog_path),
        case_id=case.case_id,
        request_id=request.request_id,
        workspace_binding=request.workspace_binding,
        checks=tuple(checks),
        resources=QualificationResourceRecord(
            wall_latency_ms=max(0, int((time.monotonic() - started_monotonic) * 1000)),
            parent_peak_rss_bytes_before=rss_before,
            parent_peak_rss_bytes_after=_peak_rss_bytes(),
        ),
        intelligence_execution=execution,
        report_hash="pending",
    )
    return report.model_copy(update={"report_hash": qualification_report_hash(report)})


def _not_run_checks(
    reason: str,
    *,
    starting_at: str = "typed_output",
) -> list[ModelQualificationCheck]:
    start_index = _CHECK_ORDER.index(starting_at)
    checks = []
    for check_id in _CHECK_ORDER[start_index:]:
        now = datetime.now(UTC)
        checks.append(
            ModelQualificationCheck(
                check_id=check_id,
                status=ModelQualificationStatus.NOT_RUN,
                summary=reason,
                started_at=now,
                completed_at=now,
                latency_ms=0,
            )
        )
    return checks


def _check(
    *,
    check_id: str,
    status: ModelQualificationStatus,
    summary: str,
    started_at: datetime,
    started_monotonic: float,
    config: OpenAICompatibleBackendConfig,
    request_count: int = 0,
    tool_call_count: int = 0,
    tools_called: tuple[str, ...] = (),
    usage: Any | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    observed_model_id: str | None = None,
    output_hash: str | None = None,
    error_type: str | None = None,
) -> ModelQualificationCheck:
    return ModelQualificationCheck(
        check_id=check_id,
        status=status,
        summary=summary,
        started_at=started_at,
        completed_at=datetime.now(UTC),
        latency_ms=max(0, int((time.monotonic() - started_monotonic) * 1000)),
        model_request_count=request_count,
        tool_call_count=tool_call_count,
        tools_called=tools_called,
        input_tokens=(input_tokens if input_tokens is not None else _usage_int(usage, "input_tokens")),
        output_tokens=(output_tokens if output_tokens is not None else _usage_int(usage, "output_tokens")),
        requested_model_id=config.model_id,
        observed_model_id=observed_model_id,
        output_hash=output_hash,
        error_type=error_type,
    )


def _check_from_execution_record(
    *,
    check_id: str,
    status: ModelQualificationStatus,
    summary: str,
    record: ModelExecutionRecord,
    output_hash: str | None = None,
    error_type: str | None = None,
) -> ModelQualificationCheck:
    return ModelQualificationCheck(
        check_id=check_id,
        status=status,
        summary=summary,
        started_at=record.started_at,
        completed_at=record.completed_at,
        latency_ms=record.latency_ms,
        model_request_count=record.model_request_count,
        input_tokens=record.input_tokens,
        output_tokens=record.output_tokens,
        requested_model_id=record.model_id,
        observed_model_id=record.observed_model_id,
        output_hash=output_hash,
        error_type=error_type,
    )


def _observed_model_is_allowed(
    config: OpenAICompatibleBackendConfig,
    observed_model_id: str | None,
) -> bool:
    return observed_model_id in {config.model_id, *config.accepted_observed_model_ids}


def _observed_model_id(result: Any) -> str | None:
    all_messages = getattr(result, "all_messages", None)
    if not callable(all_messages):
        return None
    for message in reversed(all_messages()):
        value = getattr(message, "model_name", None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _result_usage(result: Any) -> Any | None:
    value = getattr(result, "usage", None)
    return value() if callable(value) else value


def _usage_int(usage: Any | None, name: str) -> int | None:
    value = getattr(usage, name, None) if usage is not None else None
    return int(value) if isinstance(value, int) else None


def _root_error_type(exc: BaseException) -> str:
    current: BaseException = exc
    seen: set[int] = set()
    while current.__cause__ is not None and id(current.__cause__) not in seen:
        seen.add(id(current))
        current = current.__cause__
    return type(current).__name__


def _failure_disposition(
    status: ModelQualificationStatus,
) -> ModelQualificationDisposition:
    if status is ModelQualificationStatus.TIMED_OUT:
        return ModelQualificationDisposition.TIMED_OUT
    if status is ModelQualificationStatus.UNAVAILABLE:
        return ModelQualificationDisposition.UNAVAILABLE
    return ModelQualificationDisposition.FAILED


def _error_status(error_type: str | None) -> ModelQualificationStatus:
    if error_type in _TIMEOUT_ERROR_TYPES:
        return ModelQualificationStatus.TIMED_OUT
    if error_type in _UNAVAILABLE_ERROR_TYPES:
        return ModelQualificationStatus.UNAVAILABLE
    return ModelQualificationStatus.FAILED


def _sum_optional(values: Any) -> int | None:
    present = [value for value in values if value is not None]
    return sum(present) if present else None


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _peak_rss_bytes() -> int | None:
    try:
        value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    except (OSError, ValueError):
        return None
    return value if sys.platform == "darwin" else value * 1024


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "MODEL_CAPABILITY_ATTESTATION_TTL_SECONDS",
    "ModelQualificationDisposition",
    "ModelQualificationStatus",
    "ModelRuntimeQualificationCase",
    "ModelRuntimeQualificationReport",
    "TOOL_CALLING_EVIDENCE_REF",
    "TOOL_CALLING_OUTPUT_MARKER",
    "TOOL_CALLING_PROBE_NAME",
    "apply_model_capability_attestation",
    "build_model_capability_attestation",
    "qualification_report_hash",
    "run_openai_compatible_qualification",
]
