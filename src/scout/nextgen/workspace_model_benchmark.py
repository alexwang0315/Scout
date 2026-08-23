"""Model-scored Workspace dependency benchmark for experimental runtimes."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from scout.nextgen.intelligence_gateway import ModelExecutionRecord
from scout.nextgen.model_gateway import (
    ModelGatewayExecutionError,
    ModelInferenceRequest,
    ModelInferenceTimeout,
    ModelOutputValidationError,
    ModelRequestBudgetExceeded,
    ModelRuntimeUnavailable,
    ScoutModelGateway,
)
from scout.nextgen.model_runtime import (
    Locality,
    ModelRuntimeCapability,
)
from scout.nextgen.openai_compatible_backend import (
    OpenAICompatibleBackendConfig,
    OpenAICompatiblePydanticBackend,
)
from scout.nextgen.workspace_snapshot import (
    ScoutWorkspaceSnapshot,
    WorkspaceAnswerBehavior,
    WorkspaceBenchmarkCase,
    WorkspaceDomain,
    WorkspaceSnapshotMode,
)
from scout.schemas.base import NonEmptyStr, SchemaModel


class WorkspaceModelCaseStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    TIMED_OUT = "timed_out"
    INVALID_OUTPUT = "invalid_output"
    EXECUTION_FAILED = "execution_failed"


class WorkspaceModelBenchmarkDisposition(StrEnum):
    PASSED = "passed"
    PARTIAL = "partial"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class WorkspaceModelAnswer(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["scout.workspace_model_answer.v0"] = (
        "scout.workspace_model_answer.v0"
    )
    behavior: WorkspaceAnswerBehavior
    summary: str = Field(min_length=1, max_length=2000)
    cited_evidence_refs: tuple[NonEmptyStr, ...] = ()
    candidate_feature_ids: tuple[NonEmptyStr, ...] = ()
    missing_domains: tuple[WorkspaceDomain, ...] = ()
    stale_domains: tuple[WorkspaceDomain, ...] = ()
    conflicted_domains: tuple[WorkspaceDomain, ...] = ()
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @model_validator(mode="after")
    def validate_unique_references(self) -> "WorkspaceModelAnswer":
        if len(self.cited_evidence_refs) != len(set(self.cited_evidence_refs)):
            raise ValueError("Workspace model evidence refs must be unique")
        if len(self.candidate_feature_ids) != len(
            set(self.candidate_feature_ids)
        ):
            raise ValueError("Workspace model feature ids must be unique")
        return self


class WorkspaceModelCaseResult(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: NonEmptyStr
    mode: WorkspaceSnapshotMode
    snapshot_hash: NonEmptyStr
    status: WorkspaceModelCaseStatus
    passed: bool
    reasons: tuple[NonEmptyStr, ...]
    answer: WorkspaceModelAnswer | None = None
    execution_record: ModelExecutionRecord | None = None
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @model_validator(mode="after")
    def validate_status(self) -> "WorkspaceModelCaseResult":
        if self.passed != (self.status is WorkspaceModelCaseStatus.PASSED):
            raise ValueError("Workspace model case status is inconsistent")
        if not self.reasons:
            raise ValueError("Workspace model case requires a result reason")
        return self


class WorkspaceModelBenchmarkMetrics(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    total_cases: int = Field(ge=1)
    passed_cases: int = Field(ge=0)
    structured_output_valid_cases: int = Field(ge=0)
    workspace_dependency_score: float = Field(ge=0, le=1)
    total_model_requests: int = Field(ge=0)
    total_input_tokens: int | None = Field(default=None, ge=0)
    total_output_tokens: int | None = Field(default=None, ge=0)
    total_model_latency_ms: int = Field(ge=0)


class WorkspaceModelBenchmarkReport(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["scout.workspace_model_benchmark.v0"] = (
        "scout.workspace_model_benchmark.v0"
    )
    generated_at: datetime
    disposition: WorkspaceModelBenchmarkDisposition
    runtime_id: NonEmptyStr
    provider: NonEmptyStr
    model_id: NonEmptyStr
    runtime_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    workspace_benchmark_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_results: tuple[WorkspaceModelCaseResult, ...]
    metrics: WorkspaceModelBenchmarkMetrics
    report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @model_validator(mode="after")
    def validate_report(self) -> "WorkspaceModelBenchmarkReport":
        if self.metrics.total_cases != len(self.case_results):
            raise ValueError("Workspace model metric case count is inconsistent")
        if self.report_hash != workspace_model_benchmark_report_hash(self):
            raise ValueError("Workspace model report hash is invalid")
        return self


def workspace_model_prompt(snapshot: ScoutWorkspaceSnapshot) -> str:
    payload = json.dumps(
        {
            "schema_version": snapshot.schema_version,
            "snapshot_hash": snapshot.snapshot_hash,
            "mode": snapshot.mode.value,
            "question": snapshot.question,
            "facts": [
                {
                    "domain": fact.domain.value,
                    "status": fact.status.value,
                    "authority": fact.authority.value,
                    "evidence_ref": fact.evidence_ref,
                    "candidate_features": [
                        feature.model_dump(mode="json")
                        for feature in fact.candidate_features
                    ],
                }
                for fact in snapshot.facts
            ],
            "sufficiency": snapshot.sufficiency.model_dump(mode="json"),
            "candidate_only": snapshot.candidate_only,
            "runtime_safety_truth": snapshot.runtime_safety_truth,
        },
        indent=2,
        ensure_ascii=True,
    )
    return (
        "Execute the Scout Workspace dependency benchmark using only the immutable "
        "snapshot below. Do not use pretrained route or terrain priors to fill "
        "missing evidence. Copy missing, stale, and conflicted domains exactly. "
        "Use answer_with_evidence only when sufficiency is true; otherwise preserve "
        "more_evidence_required, refresh_required, or preserve_conflict. Cite every "
        "available evidence_ref and no others. For a full snapshot, return every "
        "candidate_features.feature_id. For every non-full mode, return no candidate "
        "feature ids. The result is candidate-only and never runtime safety truth.\n\n"
        f"ScoutWorkspaceSnapshot:\n{payload}"
    )


def evaluate_workspace_model_answer(
    *,
    case: WorkspaceBenchmarkCase,
    answer: WorkspaceModelAnswer,
    execution_record: ModelExecutionRecord | None = None,
) -> WorkspaceModelCaseResult:
    snapshot = case.snapshot
    reasons: list[str] = []
    if answer.behavior is not case.expected_behavior:
        reasons.append("answer behavior does not match Workspace sufficiency")
    if answer.cited_evidence_refs != snapshot.evidence_refs:
        reasons.append("answer evidence refs do not exactly match the snapshot")
    if answer.missing_domains != snapshot.sufficiency.missing_domains:
        reasons.append("answer missing domains do not match the snapshot")
    if answer.stale_domains != snapshot.sufficiency.stale_domains:
        reasons.append("answer stale domains do not match the snapshot")
    if answer.conflicted_domains != snapshot.sufficiency.conflicted_domains:
        reasons.append("answer conflict domains do not match the snapshot")
    expected_features = (
        tuple(
            feature.feature_id
            for fact in snapshot.facts
            for feature in fact.candidate_features
        )
        if snapshot.mode is WorkspaceSnapshotMode.FULL
        else ()
    )
    if answer.candidate_feature_ids != expected_features:
        reasons.append("answer candidate features are missing or unsupported")
    passed = not reasons
    return WorkspaceModelCaseResult(
        case_id=case.case_id,
        mode=case.mode,
        snapshot_hash=snapshot.snapshot_hash,
        status=(
            WorkspaceModelCaseStatus.PASSED
            if passed
            else WorkspaceModelCaseStatus.FAILED
        ),
        passed=passed,
        reasons=tuple(reasons or ("typed Workspace behavior is fully grounded",)),
        answer=answer,
        execution_record=execution_record,
    )


def run_workspace_model_benchmark(
    *,
    runtime_config_path: Path,
    workspace_benchmark_path: Path,
    timeout_seconds: float = 120,
    max_output_tokens: int | None = None,
) -> WorkspaceModelBenchmarkReport:
    if max_output_tokens is not None and max_output_tokens < 1:
        raise ValueError("Workspace benchmark output budget must be positive")
    config = OpenAICompatibleBackendConfig.from_json_file(runtime_config_path)
    benchmark_bytes = workspace_benchmark_path.read_bytes()
    benchmark_payload = json.loads(benchmark_bytes)
    _validate_workspace_benchmark_artifact(benchmark_payload)
    cases = tuple(
        WorkspaceBenchmarkCase.model_validate(item)
        for item in benchmark_payload["cases"]
    )
    backend = OpenAICompatiblePydanticBackend(config=config)
    gateway = ScoutModelGateway(
        profiles=(config.to_runtime_profile(),),
        backends=(backend,),
        max_local_concurrency=1,
        max_cloud_concurrency=(
            config.max_concurrency if config.locality is Locality.CLOUD else 1
        ),
    )
    case_results: list[WorkspaceModelCaseResult] = []
    try:
        for case in cases:
            session = gateway.open_session(
                parent_request_id=case.snapshot.snapshot_id,
                max_model_requests=10,
            )
            request = ModelInferenceRequest(
                parent_request_id=case.snapshot.snapshot_id,
                task=f"workspace_dependency:{case.mode.value}",
                prompt=workspace_model_prompt(case.snapshot),
                structured_input={
                    "snapshot_hash": case.snapshot.snapshot_hash,
                    "mode": case.mode.value,
                },
                required_capabilities=frozenset(
                    {
                        ModelRuntimeCapability.CHAT,
                        ModelRuntimeCapability.STRUCTURED_OUTPUT,
                    }
                ),
                allowed_tiers=frozenset({config.tier}),
                prefer_local=config.locality is not Locality.CLOUD,
                allow_cloud=config.locality is Locality.CLOUD,
                requires_offline=config.offline_capable,
                privacy_sensitive=config.privacy_preserving,
                estimated_input_tokens=max(
                    1,
                    len(workspace_model_prompt(case.snapshot)) // 4,
                ),
                timeout_seconds=timeout_seconds,
                max_output_tokens=(
                    max_output_tokens
                    if max_output_tokens is not None
                    else config.max_output_tokens
                ),
                temperature=config.temperature,
                thinking=config.thinking,
            )
            try:
                result = session.infer(request, output_type=WorkspaceModelAnswer)
            except ModelInferenceTimeout as exc:
                case_results.append(
                    _failed_case_result(
                        case,
                        status=WorkspaceModelCaseStatus.TIMED_OUT,
                        reason="model inference timed out",
                        execution_record=exc.record,
                    )
                )
            except ModelOutputValidationError as exc:
                case_results.append(
                    _failed_case_result(
                        case,
                        status=WorkspaceModelCaseStatus.INVALID_OUTPUT,
                        reason="model output failed the Workspace answer schema",
                        execution_record=exc.record,
                    )
                )
            except ModelRuntimeUnavailable:
                case_results.append(
                    _failed_case_result(
                        case,
                        status=WorkspaceModelCaseStatus.UNAVAILABLE,
                        reason="no model runtime satisfied the benchmark request",
                    )
                )
            except (ModelGatewayExecutionError, ModelRequestBudgetExceeded) as exc:
                case_results.append(
                    _failed_case_result(
                        case,
                        status=WorkspaceModelCaseStatus.EXECUTION_FAILED,
                        reason=f"model execution failed: {type(exc).__name__}",
                        execution_record=getattr(exc, "record", None),
                    )
                )
            else:
                case_results.append(
                    evaluate_workspace_model_answer(
                        case=case,
                        answer=result.output,
                        execution_record=result.execution_record,
                    )
                )
    finally:
        gateway.close()
    return _build_report(
        config=config,
        runtime_config_path=runtime_config_path,
        workspace_benchmark_sha256=hashlib.sha256(benchmark_bytes).hexdigest(),
        case_results=tuple(case_results),
    )


def workspace_model_benchmark_report_hash(
    report: WorkspaceModelBenchmarkReport,
) -> str:
    payload = report.model_dump(mode="json")
    payload.pop("report_hash", None)
    return _canonical_hash(payload)


def _failed_case_result(
    case: WorkspaceBenchmarkCase,
    *,
    status: WorkspaceModelCaseStatus,
    reason: str,
    execution_record: ModelExecutionRecord | None = None,
) -> WorkspaceModelCaseResult:
    return WorkspaceModelCaseResult(
        case_id=case.case_id,
        mode=case.mode,
        snapshot_hash=case.snapshot.snapshot_hash,
        status=status,
        passed=False,
        reasons=(reason,),
        execution_record=execution_record,
    )


def _build_report(
    *,
    config: OpenAICompatibleBackendConfig,
    runtime_config_path: Path,
    workspace_benchmark_sha256: str,
    case_results: tuple[WorkspaceModelCaseResult, ...],
) -> WorkspaceModelBenchmarkReport:
    passed_cases = sum(result.passed for result in case_results)
    execution_records = tuple(
        result.execution_record
        for result in case_results
        if result.execution_record is not None
    )
    valid_cases = sum(result.answer is not None for result in case_results)
    unavailable_cases = sum(
        result.status is WorkspaceModelCaseStatus.UNAVAILABLE
        for result in case_results
    )
    if passed_cases == len(case_results):
        disposition = WorkspaceModelBenchmarkDisposition.PASSED
    elif unavailable_cases == len(case_results):
        disposition = WorkspaceModelBenchmarkDisposition.UNAVAILABLE
    elif passed_cases:
        disposition = WorkspaceModelBenchmarkDisposition.PARTIAL
    else:
        disposition = WorkspaceModelBenchmarkDisposition.FAILED
    input_tokens = tuple(
        record.input_tokens
        for record in execution_records
        if record.input_tokens is not None
    )
    output_tokens = tuple(
        record.output_tokens
        for record in execution_records
        if record.output_tokens is not None
    )
    provisional = WorkspaceModelBenchmarkReport.model_construct(
        generated_at=datetime.now(UTC),
        disposition=disposition,
        runtime_id=config.runtime_id,
        provider=config.provider,
        model_id=config.model_id,
        runtime_config_sha256=hashlib.sha256(
            runtime_config_path.read_bytes()
        ).hexdigest(),
        workspace_benchmark_sha256=workspace_benchmark_sha256,
        case_results=case_results,
        metrics=WorkspaceModelBenchmarkMetrics(
            total_cases=len(case_results),
            passed_cases=passed_cases,
            structured_output_valid_cases=valid_cases,
            workspace_dependency_score=passed_cases / len(case_results),
            total_model_requests=sum(
                record.model_request_count for record in execution_records
            ),
            total_input_tokens=sum(input_tokens) if input_tokens else None,
            total_output_tokens=sum(output_tokens) if output_tokens else None,
            total_model_latency_ms=sum(
                record.latency_ms for record in execution_records
            ),
        ),
        report_hash="0" * 64,
        candidate_only=True,
        runtime_safety_truth=False,
    )
    payload = provisional.model_dump(mode="json")
    payload.pop("report_hash", None)
    payload["report_hash"] = _canonical_hash(payload)
    return WorkspaceModelBenchmarkReport.model_validate(payload)


def _validate_workspace_benchmark_artifact(payload: dict[str, object]) -> None:
    if payload.get("schema_version") != "scout.workspace_snapshot_benchmark.v0":
        raise ValueError("unsupported Workspace benchmark schema")
    if payload.get("candidate_only") is not True:
        raise ValueError("Workspace benchmark must remain candidate-only")
    if payload.get("runtime_safety_truth") is not False:
        raise ValueError("Workspace benchmark cannot be runtime safety truth")
    declared_hash = payload.get("artifact_hash")
    content = dict(payload)
    content.pop("artifact_hash", None)
    if declared_hash != _canonical_hash(content):
        raise ValueError("Workspace benchmark artifact hash is invalid")
    if not isinstance(payload.get("cases"), list):
        raise ValueError("Workspace benchmark cases are missing")


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "WorkspaceModelAnswer",
    "WorkspaceModelBenchmarkDisposition",
    "WorkspaceModelBenchmarkMetrics",
    "WorkspaceModelBenchmarkReport",
    "WorkspaceModelCaseResult",
    "WorkspaceModelCaseStatus",
    "evaluate_workspace_model_answer",
    "run_workspace_model_benchmark",
    "workspace_model_benchmark_report_hash",
    "workspace_model_prompt",
]
