from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from runtime_load_dry_run import RuntimeLoadDryRunReport, build_runtime_load_dry_run_report
from safety_models import Observation
from safety_runtime_session import SafetyRuntimeSession


DEFAULT_RUNTIME_ACTIVATION_RECORD_DIR = "activation_records"
DEFAULT_RUNTIME_OBSERVATION_START_RECORD_DIR = "observation_start_records"
DEFAULT_RUNTIME_OBSERVATION_BATCH_RECORD_DIR = "observation_batch_records"
DEFAULT_RUNTIME_LIFECYCLE_RECORD_DIR = "lifecycle_records"
DEFAULT_RUNTIME_STREAM_GUARD_RECORD_DIR = "stream_guard_records"
DEFAULT_RUNTIME_ACTIVATION_BLOCKED_REPORT_NAME = "runtime_activation_blocked_report.json"


class RuntimeActivationLoaderStatus(StrEnum):
    LOADED_NOT_OBSERVING = "loaded_not_observing"
    OBSERVING = "observing"
    PAUSED = "paused"
    ENDED = "ended"
    ABORTED = "aborted"
    ACTIVATION_BLOCKED = "activation_blocked"


class RuntimeLifecycleAction(StrEnum):
    PAUSE = "pause"
    RESUME = "resume"
    END = "end"
    ABORT = "abort"


class StrictRuntimeActivationLoaderModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuntimeActivationLoaderFinding(StrictRuntimeActivationLoaderModel):
    finding_id: str = Field(min_length=1)
    severity: Literal["blocker", "info"] = "blocker"
    check_name: str = Field(min_length=1)
    summary: str = Field(min_length=1)


class RuntimeActivationLoaderCounts(StrictRuntimeActivationLoaderModel):
    runtime_activation_attempt_count: Literal[1] = 1
    runtime_activation_record_count: int = Field(ge=0)
    safety_runtime_session_count: int = Field(ge=0)
    observations_processed_count: int = Field(default=0, ge=0)
    incident_package_count: int = Field(default=0, ge=0)
    stored_incident_path_count: int = Field(default=0, ge=0)
    safety_api_call_count: Literal[0] = 0
    phase2_writeback_count: Literal[0] = 0
    raw_payload_copy_count: Literal[0] = 0
    blocker_count: int = Field(ge=0)


class RuntimeActivationLoaderBoundary(StrictRuntimeActivationLoaderModel):
    phase1_runtime_loader: Literal[True] = True
    creates_safety_runtime_session: bool
    starts_observation_processing: Literal[False] = False
    calls_safety_api: Literal[False] = False
    writes_phase2_brain: Literal[False] = False
    mutates_runtime_export: Literal[False] = False
    mutates_activation_request: Literal[False] = False
    incident_bridge_enabled: Literal[False] = False
    raw_payloads_embedded: Literal[False] = False
    activation_state: RuntimeActivationLoaderStatus
    notes: list[str]


class RuntimeObservationStartBoundary(StrictRuntimeActivationLoaderModel):
    phase1_runtime_loader: Literal[True] = True
    uses_existing_safety_runtime_session: Literal[True] = True
    starts_observation_processing: Literal[True] = True
    accepts_single_initial_observation: Literal[True] = True
    calls_safety_api: Literal[False] = False
    writes_phase2_brain: Literal[False] = False
    mutates_runtime_export: Literal[False] = False
    mutates_activation_request: Literal[False] = False
    incident_bridge_enabled: Literal[False] = False
    raw_observation_embedded: Literal[False] = False
    activation_state: Literal[RuntimeActivationLoaderStatus.OBSERVING] = (
        RuntimeActivationLoaderStatus.OBSERVING
    )
    notes: list[str] = Field(
        default_factory=lambda: [
            "Observing / 現場觀測中 starts with one explicit initial observation.",
            "This slice does not connect a continuous sensor stream or HTTP safety API.",
            "Phase 2 writeback and incident bridge remain disabled.",
        ]
    )


class RuntimeLifecycleControlBoundary(StrictRuntimeActivationLoaderModel):
    phase1_runtime_lifecycle_control: Literal[True] = True
    uses_existing_safety_runtime_session: Literal[True] = True
    processes_observation: Literal[False] = False
    calls_safety_api: Literal[False] = False
    writes_phase2_brain: Literal[False] = False
    mutates_runtime_export: Literal[False] = False
    mutates_activation_request: Literal[False] = False
    incident_bridge_enabled: Literal[False] = False
    raw_payloads_embedded: Literal[False] = False
    notes: list[str] = Field(
        default_factory=lambda: [
            "Runtime lifecycle controls / runtime 生命週期控制 update local runtime state only.",
            "Pause, resume, end, and abort do not process new observations.",
            "Safety APIs, incident bridge, and Phase 2 writeback remain disabled.",
        ]
    )


class RuntimeObservationBatchBoundary(StrictRuntimeActivationLoaderModel):
    phase1_runtime_loader: Literal[True] = True
    uses_existing_safety_runtime_session: Literal[True] = True
    starts_observation_processing: Literal[True] = True
    accepts_bounded_observation_batch: Literal[True] = True
    connects_continuous_sensor_stream: Literal[False] = False
    calls_safety_api: Literal[False] = False
    writes_phase2_brain: Literal[False] = False
    mutates_runtime_export: Literal[False] = False
    mutates_activation_request: Literal[False] = False
    incident_bridge_enabled: Literal[False] = False
    raw_observations_embedded: Literal[False] = False
    activation_state: Literal[RuntimeActivationLoaderStatus.OBSERVING] = (
        RuntimeActivationLoaderStatus.OBSERVING
    )
    notes: list[str] = Field(
        default_factory=lambda: [
            "Runtime observation batch / 現場觀測批次 accepts a bounded list of observations.",
            "This is not a continuous sensor stream or HTTP safety API.",
            "Phase 2 writeback and incident bridge remain disabled.",
        ]
    )


class RuntimeStreamGuardBoundary(StrictRuntimeActivationLoaderModel):
    continuous_sensor_stream_allowed: Literal[False] = False
    hardware_stream_control_allowed: Literal[False] = False
    safety_api_calls_allowed: Literal[False] = False
    writes_phase2_brain: Literal[False] = False
    mutates_runtime_export: Literal[False] = False
    mutates_activation_request: Literal[False] = False
    incident_bridge_enabled: Literal[False] = False
    raw_stream_payloads_embedded: Literal[False] = False
    requires_future_stream_protocol: Literal[True] = True
    notes: list[str] = Field(
        default_factory=lambda: [
            "Runtime stream guard / 連續串流守門 blocks continuous stream start in this slice.",
            "Bounded observation batches are allowed, but live device or HTTP streams require a future protocol.",
            "Safety APIs, incident bridge, and Phase 2 writeback remain disabled.",
        ]
    )


class RuntimeActivationRecord(StrictRuntimeActivationLoaderModel):
    activation_id: str = Field(min_length=1)
    artifact_kind: Literal["runtime_activation_record"] = "runtime_activation_record"
    status: Literal[RuntimeActivationLoaderStatus.LOADED_NOT_OBSERVING] = (
        RuntimeActivationLoaderStatus.LOADED_NOT_OBSERVING
    )
    activation_performed: Literal[True] = True
    project_id: str = Field(min_length=1)
    export_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    runtime_target: dict[str, Any]
    mission_graph_version: str = Field(min_length=1)
    mission_graph_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    route_source_ref: str | None = None
    route_artifact_runtime_ref: str | None = None
    route_point_count: int = Field(ge=0)
    dry_run_report_id: str = Field(min_length=1)
    dry_run_report_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    activated_by: str = Field(min_length=1)
    activated_at: str = Field(min_length=1)
    activation_reason: str = Field(min_length=1)
    counts: RuntimeActivationLoaderCounts
    boundary: RuntimeActivationLoaderBoundary
    findings: list[RuntimeActivationLoaderFinding] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_activation_record_contract(self) -> "RuntimeActivationRecord":
        if self.counts.runtime_activation_record_count != 1:
            raise ValueError("successful activation must write exactly one activation record")
        if self.counts.safety_runtime_session_count != 1:
            raise ValueError("successful activation must create exactly one SafetyRuntimeSession")
        if self.counts.blocker_count != 0 or self.findings:
            raise ValueError("successful activation record cannot contain blockers")
        if self.boundary.activation_state != RuntimeActivationLoaderStatus.LOADED_NOT_OBSERVING:
            raise ValueError("activation record boundary must be loaded_not_observing")
        if not self.boundary.creates_safety_runtime_session:
            raise ValueError("activation record must mark SafetyRuntimeSession creation")
        _assert_no_raw_payload_fragments(self.model_dump(mode="json"))
        return self

    def to_json(self) -> str:
        return _canonical_json_text(self.model_dump(mode="json"))


class RuntimeActivationBlockedReport(StrictRuntimeActivationLoaderModel):
    activation_id: str = Field(min_length=1)
    artifact_kind: Literal["runtime_activation_blocked_report"] = (
        "runtime_activation_blocked_report"
    )
    status: Literal[RuntimeActivationLoaderStatus.ACTIVATION_BLOCKED] = (
        RuntimeActivationLoaderStatus.ACTIVATION_BLOCKED
    )
    activation_performed: Literal[False] = False
    export_id: str = Field(min_length=1)
    request_id: str | None = None
    dry_run_report_id: str | None = None
    dry_run_report_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    activated_by: str = Field(min_length=1)
    activated_at: str = Field(min_length=1)
    activation_reason: str = Field(min_length=1)
    counts: RuntimeActivationLoaderCounts
    boundary: RuntimeActivationLoaderBoundary
    findings: list[RuntimeActivationLoaderFinding]

    @model_validator(mode="after")
    def enforce_blocked_report_contract(self) -> "RuntimeActivationBlockedReport":
        blocker_count = sum(1 for finding in self.findings if finding.severity == "blocker")
        if self.counts.blocker_count != blocker_count:
            raise ValueError("blocked activation blocker_count must match findings")
        if self.counts.runtime_activation_record_count != 0:
            raise ValueError("blocked activation cannot write activation records")
        if self.counts.safety_runtime_session_count != 0:
            raise ValueError("blocked activation cannot create SafetyRuntimeSession")
        if self.boundary.activation_state != RuntimeActivationLoaderStatus.ACTIVATION_BLOCKED:
            raise ValueError("blocked activation boundary must be activation_blocked")
        if self.boundary.creates_safety_runtime_session:
            raise ValueError("blocked activation cannot mark SafetyRuntimeSession creation")
        _assert_no_raw_payload_fragments(self.model_dump(mode="json"))
        return self

    def to_json(self) -> str:
        return _canonical_json_text(self.model_dump(mode="json"))


class RuntimeObservationStartRecord(StrictRuntimeActivationLoaderModel):
    observing_id: str = Field(min_length=1)
    artifact_kind: Literal["runtime_observation_start_record"] = (
        "runtime_observation_start_record"
    )
    status: Literal[RuntimeActivationLoaderStatus.OBSERVING] = (
        RuntimeActivationLoaderStatus.OBSERVING
    )
    activation_id: str = Field(min_length=1)
    activation_status_before_start: Literal[
        RuntimeActivationLoaderStatus.LOADED_NOT_OBSERVING
    ] = RuntimeActivationLoaderStatus.LOADED_NOT_OBSERVING
    project_id: str = Field(min_length=1)
    export_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    mission_graph_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    observation_source: str = Field(min_length=1)
    observation_timestamp: float
    route_progress_sample_available: bool
    checkpoint_arrival_id: str | None = None
    safety_state: dict[str, Any]
    safety_event_count: int = Field(ge=0)
    recording_policy_profile: str = Field(min_length=1)
    started_by: str = Field(min_length=1)
    started_at: str = Field(min_length=1)
    start_reason: str = Field(min_length=1)
    counts: RuntimeActivationLoaderCounts
    boundary: RuntimeObservationStartBoundary = Field(
        default_factory=RuntimeObservationStartBoundary
    )
    findings: list[RuntimeActivationLoaderFinding] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_observing_record_contract(self) -> "RuntimeObservationStartRecord":
        if self.counts.safety_runtime_session_count != 1:
            raise ValueError("observing start must use exactly one SafetyRuntimeSession")
        if self.counts.observations_processed_count < 1:
            raise ValueError("observing start must process at least one observation")
        if self.counts.safety_api_call_count != 0:
            raise ValueError("observing start must not call safety APIs")
        if self.counts.phase2_writeback_count != 0:
            raise ValueError("observing start must not write Phase 2")
        if self.findings:
            raise ValueError("observing start record cannot contain findings")
        _assert_no_raw_payload_fragments(self.model_dump(mode="json"))
        return self

    def to_json(self) -> str:
        return _canonical_json_text(self.model_dump(mode="json"))


class RuntimeLifecycleControlRecord(StrictRuntimeActivationLoaderModel):
    control_id: str = Field(min_length=1)
    artifact_kind: Literal["runtime_lifecycle_control_record"] = (
        "runtime_lifecycle_control_record"
    )
    action: RuntimeLifecycleAction
    previous_status: RuntimeActivationLoaderStatus
    status: RuntimeActivationLoaderStatus
    terminal_state: bool
    activation_id: str = Field(min_length=1)
    observing_id: str = Field(min_length=1)
    controlled_by: str = Field(min_length=1)
    controlled_at: str = Field(min_length=1)
    control_reason: str = Field(min_length=1)
    counts: RuntimeActivationLoaderCounts
    boundary: RuntimeLifecycleControlBoundary = Field(
        default_factory=RuntimeLifecycleControlBoundary
    )
    findings: list[RuntimeActivationLoaderFinding] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_lifecycle_record_contract(self) -> "RuntimeLifecycleControlRecord":
        if self.counts.safety_runtime_session_count != 1:
            raise ValueError("lifecycle control must reference one SafetyRuntimeSession")
        if self.counts.safety_api_call_count != 0:
            raise ValueError("lifecycle control must not call safety APIs")
        if self.counts.phase2_writeback_count != 0:
            raise ValueError("lifecycle control must not write Phase 2")
        if self.findings:
            raise ValueError("lifecycle control record cannot contain findings")
        if self.terminal_state != (self.status in _TERMINAL_RUNTIME_STATUSES):
            raise ValueError("terminal_state must match lifecycle status")
        _assert_no_raw_payload_fragments(self.model_dump(mode="json"))
        return self

    def to_json(self) -> str:
        return _canonical_json_text(self.model_dump(mode="json"))


class RuntimeObservationBatchRecord(StrictRuntimeActivationLoaderModel):
    batch_id: str = Field(min_length=1)
    artifact_kind: Literal["runtime_observation_batch_record"] = (
        "runtime_observation_batch_record"
    )
    previous_status: Literal[RuntimeActivationLoaderStatus.OBSERVING] = (
        RuntimeActivationLoaderStatus.OBSERVING
    )
    status: Literal[RuntimeActivationLoaderStatus.OBSERVING] = (
        RuntimeActivationLoaderStatus.OBSERVING
    )
    activation_id: str = Field(min_length=1)
    observing_id: str = Field(min_length=1)
    observation_count: int = Field(gt=0)
    first_observation_timestamp: float
    last_observation_timestamp: float
    observation_sources: list[str] = Field(min_length=1)
    route_progress_sample_count: int = Field(ge=0)
    checkpoint_arrival_ids: list[str] = Field(default_factory=list)
    safety_state: dict[str, Any]
    safety_event_count: int = Field(ge=0)
    recording_policy_profiles: list[str] = Field(min_length=1)
    processed_by: str = Field(min_length=1)
    processed_at: str = Field(min_length=1)
    process_reason: str = Field(min_length=1)
    counts: RuntimeActivationLoaderCounts
    boundary: RuntimeObservationBatchBoundary = Field(
        default_factory=RuntimeObservationBatchBoundary
    )
    findings: list[RuntimeActivationLoaderFinding] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_observation_batch_record_contract(self) -> "RuntimeObservationBatchRecord":
        if self.counts.safety_runtime_session_count != 1:
            raise ValueError("observation batch must use exactly one SafetyRuntimeSession")
        if self.counts.observations_processed_count < self.observation_count:
            raise ValueError("observation batch count cannot exceed processed observations")
        if self.counts.safety_api_call_count != 0:
            raise ValueError("observation batch must not call safety APIs")
        if self.counts.phase2_writeback_count != 0:
            raise ValueError("observation batch must not write Phase 2")
        if self.findings:
            raise ValueError("observation batch record cannot contain findings")
        if self.first_observation_timestamp > self.last_observation_timestamp:
            raise ValueError("observation batch timestamps must be chronological")
        _assert_no_raw_payload_fragments(self.model_dump(mode="json"))
        return self

    def to_json(self) -> str:
        return _canonical_json_text(self.model_dump(mode="json"))


class RuntimeStreamGuardRecord(StrictRuntimeActivationLoaderModel):
    stream_request_id: str = Field(min_length=1)
    artifact_kind: Literal["runtime_stream_guard_record"] = "runtime_stream_guard_record"
    status: Literal["stream_blocked"] = "stream_blocked"
    requested_from_status: RuntimeActivationLoaderStatus
    activation_id: str = Field(min_length=1)
    observing_id: str = Field(min_length=1)
    stream_source_kind: str = Field(min_length=1)
    requested_by: str = Field(min_length=1)
    requested_at: str = Field(min_length=1)
    request_reason: str = Field(min_length=1)
    counts: RuntimeActivationLoaderCounts
    boundary: RuntimeStreamGuardBoundary = Field(default_factory=RuntimeStreamGuardBoundary)
    findings: list[RuntimeActivationLoaderFinding]

    @model_validator(mode="after")
    def enforce_stream_guard_record_contract(self) -> "RuntimeStreamGuardRecord":
        if self.counts.safety_runtime_session_count != 1:
            raise ValueError("stream guard must reference one SafetyRuntimeSession")
        if self.counts.safety_api_call_count != 0:
            raise ValueError("stream guard must not call safety APIs")
        if self.counts.phase2_writeback_count != 0:
            raise ValueError("stream guard must not write Phase 2")
        if not self.findings:
            raise ValueError("stream guard must explain why stream is blocked")
        if any(finding.severity != "blocker" for finding in self.findings):
            raise ValueError("stream guard findings must be blockers")
        _assert_no_raw_payload_fragments(self.model_dump(mode="json"))
        return self

    def to_json(self) -> str:
        return _canonical_json_text(self.model_dump(mode="json"))


@dataclass(frozen=True)
class RuntimeActivationLoaderResult:
    status: RuntimeActivationLoaderStatus
    activation_record: RuntimeActivationRecord | None
    blocked_report: RuntimeActivationBlockedReport | None
    session: SafetyRuntimeSession | None


@dataclass(frozen=True)
class RuntimeObservationStartResult:
    status: RuntimeActivationLoaderStatus
    observation_start_record: RuntimeObservationStartRecord
    session: SafetyRuntimeSession


@dataclass(frozen=True)
class RuntimeLifecycleControlResult:
    status: RuntimeActivationLoaderStatus
    lifecycle_record: RuntimeLifecycleControlRecord
    session: SafetyRuntimeSession


@dataclass(frozen=True)
class RuntimeObservationBatchResult:
    status: RuntimeActivationLoaderStatus
    observation_batch_record: RuntimeObservationBatchRecord
    session: SafetyRuntimeSession


@dataclass(frozen=True)
class RuntimeStreamGuardResult:
    status: Literal["stream_blocked"]
    stream_guard_record: RuntimeStreamGuardRecord
    session: SafetyRuntimeSession


def activate_runtime_export(
    export_root: Path | str,
    runtime_state_root: Path | str,
    *,
    activation_id: str,
    activated_by: str,
    activated_at: str,
    activation_reason: str,
) -> RuntimeActivationLoaderResult:
    export_path = Path(export_root)
    state_root = _require_runtime_state_root(runtime_state_root)
    record_path = _activation_record_path(state_root, activation_id)
    blocked_path = state_root / DEFAULT_RUNTIME_ACTIVATION_BLOCKED_REPORT_NAME

    dry_run = build_runtime_load_dry_run_report(export_path)
    if record_path.exists():
        report = _blocked_report(
            activation_id=activation_id,
            dry_run=dry_run,
            activated_by=activated_by,
            activated_at=activated_at,
            activation_reason=activation_reason,
            findings=[
                _blocker(
                    "runtime_activation_record_exists",
                    "runtime_activation_duplicate_guard",
                    "Runtime activation record already exists for this activation id.",
                )
            ],
        )
        _replace_json(blocked_path, report.to_json())
        return RuntimeActivationLoaderResult(
            status=RuntimeActivationLoaderStatus.ACTIVATION_BLOCKED,
            activation_record=None,
            blocked_report=report,
            session=None,
        )

    if not dry_run.dry_run_passed:
        report = _blocked_report(
            activation_id=activation_id,
            dry_run=dry_run,
            activated_by=activated_by,
            activated_at=activated_at,
            activation_reason=activation_reason,
            findings=[
                RuntimeActivationLoaderFinding.model_validate(
                    finding.model_dump(mode="json")
                )
                for finding in dry_run.findings
            ],
        )
        _replace_json(blocked_path, report.to_json())
        return RuntimeActivationLoaderResult(
            status=RuntimeActivationLoaderStatus.ACTIVATION_BLOCKED,
            activation_record=None,
            blocked_report=report,
            session=None,
        )

    session = SafetyRuntimeSession(
        export_path / "mission_graph.json",
        incident_store_path=state_root / "incidents" / activation_id,
        incident_bridge=None,
    )
    snapshot = session.snapshot()
    if snapshot.observations_processed != 0:
        raise RuntimeError("runtime activation must not process observations")
    if snapshot.incident_packages or snapshot.stored_incident_paths:
        raise RuntimeError("runtime activation must not create incidents")

    record = RuntimeActivationRecord(
        activation_id=activation_id,
        project_id=dry_run.project_id,
        export_id=dry_run.export_id,
        request_id=dry_run.request_id or "",
        runtime_target=dry_run.runtime_target or {},
        mission_graph_version=dry_run.mission_graph_version or "",
        mission_graph_sha256=dry_run.mission_graph_sha256 or "",
        route_source_ref=dry_run.route_source_ref,
        route_artifact_runtime_ref=dry_run.route_artifact_runtime_ref,
        route_point_count=dry_run.route_point_count,
        dry_run_report_id=dry_run.report_id,
        dry_run_report_sha256=_sha256_json(dry_run.model_dump(mode="json")),
        activated_by=activated_by,
        activated_at=activated_at,
        activation_reason=activation_reason,
        counts=RuntimeActivationLoaderCounts(
            runtime_activation_record_count=1,
            safety_runtime_session_count=1,
            blocker_count=0,
        ),
        boundary=RuntimeActivationLoaderBoundary(
            creates_safety_runtime_session=True,
            activation_state=RuntimeActivationLoaderStatus.LOADED_NOT_OBSERVING,
            notes=[
                "Actual Runtime Activation / 實際啟動現場 runtime loads the session only.",
                "The first implemented state is loaded_not_observing / 已載入未觀測.",
                "Observation processing, safety APIs, incident bridge, and Phase 2 writeback remain closed.",
            ],
        ),
    )
    _replace_json(record_path, record.to_json())
    return RuntimeActivationLoaderResult(
        status=RuntimeActivationLoaderStatus.LOADED_NOT_OBSERVING,
        activation_record=record,
        blocked_report=None,
        session=session,
    )


def load_runtime_activation_record(path: Path | str) -> RuntimeActivationRecord:
    return RuntimeActivationRecord.model_validate_json(Path(path).read_text(encoding="utf-8"))


def load_runtime_activation_blocked_report(
    path: Path | str,
) -> RuntimeActivationBlockedReport:
    return RuntimeActivationBlockedReport.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def start_runtime_observing(
    activation_result: RuntimeActivationLoaderResult,
    runtime_state_root: Path | str,
    observation: Observation,
    *,
    observing_id: str,
    started_by: str,
    started_at: str,
    start_reason: str,
) -> RuntimeObservationStartResult:
    if activation_result.status != RuntimeActivationLoaderStatus.LOADED_NOT_OBSERVING:
        raise ValueError("runtime observing requires loaded_not_observing activation")
    if activation_result.activation_record is None or activation_result.session is None:
        raise ValueError("runtime observing requires activation record and live session")

    state_root = _require_runtime_state_root(runtime_state_root)
    record_path = _observation_start_record_path(state_root, observing_id)
    if record_path.exists():
        raise FileExistsError(f"runtime observation start record already exists: {record_path}")

    update = activation_result.session.observe(observation)
    snapshot = activation_result.session.snapshot()
    checkpoint_arrival_id = None
    if update.checkpoint_arrival is not None:
        checkpoint_arrival_id = update.checkpoint_arrival.checkpoint.checkpoint_id
    record = RuntimeObservationStartRecord(
        observing_id=observing_id,
        activation_id=activation_result.activation_record.activation_id,
        project_id=activation_result.activation_record.project_id,
        export_id=activation_result.activation_record.export_id,
        request_id=activation_result.activation_record.request_id,
        mission_graph_sha256=activation_result.activation_record.mission_graph_sha256,
        observation_source=observation.source,
        observation_timestamp=observation.timestamp,
        route_progress_sample_available=update.route_progress_sample is not None,
        checkpoint_arrival_id=checkpoint_arrival_id,
        safety_state=update.safety_state.model_dump(mode="json"),
        safety_event_count=len(update.safety_events),
        recording_policy_profile=update.recording_decision.profile,
        started_by=started_by,
        started_at=started_at,
        start_reason=start_reason,
        counts=RuntimeActivationLoaderCounts(
            runtime_activation_record_count=1,
            safety_runtime_session_count=1,
            observations_processed_count=snapshot.observations_processed,
            incident_package_count=len(snapshot.incident_packages),
            stored_incident_path_count=len(snapshot.stored_incident_paths),
            blocker_count=0,
        ),
        boundary=RuntimeObservationStartBoundary(
            notes=[
                "Observing / 現場觀測中 starts with one explicit initial observation.",
                "This slice does not connect a continuous sensor stream or HTTP safety API.",
                "Phase 2 writeback and incident bridge remain disabled.",
            ],
        ),
    )
    _replace_json(record_path, record.to_json())
    return RuntimeObservationStartResult(
        status=RuntimeActivationLoaderStatus.OBSERVING,
        observation_start_record=record,
        session=activation_result.session,
    )


def load_runtime_observation_start_record(
    path: Path | str,
) -> RuntimeObservationStartRecord:
    return RuntimeObservationStartRecord.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def process_runtime_observation_batch(
    current: RuntimeObservationStartResult | RuntimeLifecycleControlResult | RuntimeObservationBatchResult,
    runtime_state_root: Path | str,
    observations: list[Observation],
    *,
    batch_id: str,
    processed_by: str,
    processed_at: str,
    process_reason: str,
) -> RuntimeObservationBatchResult:
    if current.status != RuntimeActivationLoaderStatus.OBSERVING:
        raise ValueError("runtime observation batch requires observing runtime state")
    if not observations:
        raise ValueError("runtime observation batch requires at least one observation")

    state_root = _require_runtime_state_root(runtime_state_root)
    record_path = _observation_batch_record_path(state_root, batch_id)
    if record_path.exists():
        raise FileExistsError(f"runtime observation batch record already exists: {record_path}")

    route_progress_sample_count = 0
    checkpoint_arrival_ids: list[str] = []
    safety_event_count = 0
    recording_policy_profiles: list[str] = []
    last_safety_state: dict[str, Any] | None = None
    for observation in observations:
        update = current.session.observe(observation)
        if update.route_progress_sample is not None:
            route_progress_sample_count += 1
        if update.checkpoint_arrival is not None:
            checkpoint_arrival_ids.append(update.checkpoint_arrival.checkpoint.checkpoint_id)
        safety_event_count += len(update.safety_events)
        recording_policy_profiles.append(update.recording_decision.profile)
        last_safety_state = update.safety_state.model_dump(mode="json")

    activation_id, observing_id = _current_runtime_ids(current)
    snapshot = current.session.snapshot()
    record = RuntimeObservationBatchRecord(
        batch_id=batch_id,
        activation_id=activation_id,
        observing_id=observing_id,
        observation_count=len(observations),
        first_observation_timestamp=observations[0].timestamp,
        last_observation_timestamp=observations[-1].timestamp,
        observation_sources=sorted({observation.source for observation in observations}),
        route_progress_sample_count=route_progress_sample_count,
        checkpoint_arrival_ids=checkpoint_arrival_ids,
        safety_state=last_safety_state or {},
        safety_event_count=safety_event_count,
        recording_policy_profiles=sorted(set(recording_policy_profiles)),
        processed_by=processed_by,
        processed_at=processed_at,
        process_reason=process_reason,
        counts=RuntimeActivationLoaderCounts(
            runtime_activation_record_count=1,
            safety_runtime_session_count=1,
            observations_processed_count=snapshot.observations_processed,
            incident_package_count=len(snapshot.incident_packages),
            stored_incident_path_count=len(snapshot.stored_incident_paths),
            blocker_count=0,
        ),
        boundary=RuntimeObservationBatchBoundary(
            notes=[
                "Runtime observation batch / 現場觀測批次 accepts a bounded list of observations.",
                "This is not a continuous sensor stream or HTTP safety API.",
                "Phase 2 writeback and incident bridge remain disabled.",
            ],
        ),
    )
    _replace_json(record_path, record.to_json())
    return RuntimeObservationBatchResult(
        status=RuntimeActivationLoaderStatus.OBSERVING,
        observation_batch_record=record,
        session=current.session,
    )


def load_runtime_observation_batch_record(
    path: Path | str,
) -> RuntimeObservationBatchRecord:
    return RuntimeObservationBatchRecord.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def request_runtime_stream_start(
    current: RuntimeObservationStartResult
    | RuntimeLifecycleControlResult
    | RuntimeObservationBatchResult,
    runtime_state_root: Path | str,
    *,
    stream_request_id: str,
    stream_source_kind: str,
    requested_by: str,
    requested_at: str,
    request_reason: str,
) -> RuntimeStreamGuardResult:
    state_root = _require_runtime_state_root(runtime_state_root)
    record_path = _stream_guard_record_path(state_root, stream_request_id)
    if record_path.exists():
        raise FileExistsError(f"runtime stream guard record already exists: {record_path}")

    activation_id, observing_id = _current_runtime_ids(current)
    snapshot = current.session.snapshot()
    record = RuntimeStreamGuardRecord(
        stream_request_id=stream_request_id,
        requested_from_status=current.status,
        activation_id=activation_id,
        observing_id=observing_id,
        stream_source_kind=stream_source_kind,
        requested_by=requested_by,
        requested_at=requested_at,
        request_reason=request_reason,
        counts=RuntimeActivationLoaderCounts(
            runtime_activation_record_count=1,
            safety_runtime_session_count=1,
            observations_processed_count=snapshot.observations_processed,
            incident_package_count=len(snapshot.incident_packages),
            stored_incident_path_count=len(snapshot.stored_incident_paths),
            blocker_count=1,
        ),
        boundary=RuntimeStreamGuardBoundary(
            notes=[
                "Runtime stream guard / 連續串流守門 blocks continuous stream start in this slice.",
                "Bounded observation batches are allowed, but live device or HTTP streams require a future protocol.",
                "Safety APIs, incident bridge, and Phase 2 writeback remain disabled.",
            ],
        ),
        findings=[
            _blocker(
                "runtime_stream_protocol_not_defined",
                "runtime_stream_guard",
                "Continuous runtime streams require a future stream protocol and are blocked in this slice.",
            )
        ],
    )
    _replace_json(record_path, record.to_json())
    return RuntimeStreamGuardResult(
        status="stream_blocked",
        stream_guard_record=record,
        session=current.session,
    )


def load_runtime_stream_guard_record(path: Path | str) -> RuntimeStreamGuardRecord:
    return RuntimeStreamGuardRecord.model_validate_json(Path(path).read_text(encoding="utf-8"))


def apply_runtime_lifecycle_control(
    current: RuntimeObservationStartResult | RuntimeLifecycleControlResult | RuntimeObservationBatchResult,
    runtime_state_root: Path | str,
    *,
    action: RuntimeLifecycleAction | str,
    control_id: str,
    controlled_by: str,
    controlled_at: str,
    control_reason: str,
) -> RuntimeLifecycleControlResult:
    lifecycle_action = RuntimeLifecycleAction(action)
    previous_status = current.status
    next_status = _next_lifecycle_status(previous_status, lifecycle_action)
    state_root = _require_runtime_state_root(runtime_state_root)
    record_path = _lifecycle_record_path(state_root, control_id)
    if record_path.exists():
        raise FileExistsError(f"runtime lifecycle control record already exists: {record_path}")

    activation_id, observing_id = _current_runtime_ids(current)
    snapshot = current.session.snapshot()
    record = RuntimeLifecycleControlRecord(
        control_id=control_id,
        action=lifecycle_action,
        previous_status=previous_status,
        status=next_status,
        terminal_state=next_status in _TERMINAL_RUNTIME_STATUSES,
        activation_id=activation_id,
        observing_id=observing_id,
        controlled_by=controlled_by,
        controlled_at=controlled_at,
        control_reason=control_reason,
        counts=RuntimeActivationLoaderCounts(
            runtime_activation_record_count=1,
            safety_runtime_session_count=1,
            observations_processed_count=snapshot.observations_processed,
            incident_package_count=len(snapshot.incident_packages),
            stored_incident_path_count=len(snapshot.stored_incident_paths),
            blocker_count=0,
        ),
        boundary=RuntimeLifecycleControlBoundary(
            notes=[
                "Runtime lifecycle controls / runtime 生命週期控制 update local runtime state only.",
                "Pause, resume, end, and abort do not process new observations.",
                "Safety APIs, incident bridge, and Phase 2 writeback remain disabled.",
            ],
        ),
    )
    _replace_json(record_path, record.to_json())
    return RuntimeLifecycleControlResult(
        status=next_status,
        lifecycle_record=record,
        session=current.session,
    )


def load_runtime_lifecycle_control_record(
    path: Path | str,
) -> RuntimeLifecycleControlRecord:
    return RuntimeLifecycleControlRecord.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def _blocked_report(
    *,
    activation_id: str,
    dry_run: RuntimeLoadDryRunReport,
    activated_by: str,
    activated_at: str,
    activation_reason: str,
    findings: list[RuntimeActivationLoaderFinding],
) -> RuntimeActivationBlockedReport:
    blocker_count = sum(1 for finding in findings if finding.severity == "blocker")
    return RuntimeActivationBlockedReport(
        activation_id=activation_id,
        export_id=dry_run.export_id,
        request_id=dry_run.request_id,
        dry_run_report_id=dry_run.report_id,
        dry_run_report_sha256=_sha256_json(dry_run.model_dump(mode="json")),
        activated_by=activated_by,
        activated_at=activated_at,
        activation_reason=activation_reason,
        counts=RuntimeActivationLoaderCounts(
            runtime_activation_record_count=0,
            safety_runtime_session_count=0,
            blocker_count=blocker_count,
        ),
        boundary=RuntimeActivationLoaderBoundary(
            creates_safety_runtime_session=False,
            activation_state=RuntimeActivationLoaderStatus.ACTIVATION_BLOCKED,
            notes=[
                "Actual Runtime Activation / 實際啟動現場 runtime was blocked before session creation.",
                "Blocked activation writes a report only; it does not mutate export or request artifacts.",
            ],
        ),
        findings=findings,
    )


def _blocker(
    finding_id: str,
    check_name: str,
    summary: str,
) -> RuntimeActivationLoaderFinding:
    return RuntimeActivationLoaderFinding(
        finding_id=finding_id,
        check_name=check_name,
        summary=summary,
    )


def _activation_record_path(state_root: Path, activation_id: str) -> Path:
    return state_root / DEFAULT_RUNTIME_ACTIVATION_RECORD_DIR / f"{activation_id}.json"


def _observation_start_record_path(state_root: Path, observing_id: str) -> Path:
    return state_root / DEFAULT_RUNTIME_OBSERVATION_START_RECORD_DIR / f"{observing_id}.json"


def _observation_batch_record_path(state_root: Path, batch_id: str) -> Path:
    return state_root / DEFAULT_RUNTIME_OBSERVATION_BATCH_RECORD_DIR / f"{batch_id}.json"


def _lifecycle_record_path(state_root: Path, control_id: str) -> Path:
    return state_root / DEFAULT_RUNTIME_LIFECYCLE_RECORD_DIR / f"{control_id}.json"


def _stream_guard_record_path(state_root: Path, stream_request_id: str) -> Path:
    return state_root / DEFAULT_RUNTIME_STREAM_GUARD_RECORD_DIR / f"{stream_request_id}.json"


def _current_runtime_ids(
    current: RuntimeObservationStartResult | RuntimeLifecycleControlResult | RuntimeObservationBatchResult,
) -> tuple[str, str]:
    if isinstance(current, RuntimeObservationStartResult):
        return (
            current.observation_start_record.activation_id,
            current.observation_start_record.observing_id,
        )
    if isinstance(current, RuntimeObservationBatchResult):
        return (
            current.observation_batch_record.activation_id,
            current.observation_batch_record.observing_id,
        )
    return (
        current.lifecycle_record.activation_id,
        current.lifecycle_record.observing_id,
    )


def _next_lifecycle_status(
    previous_status: RuntimeActivationLoaderStatus,
    action: RuntimeLifecycleAction,
) -> RuntimeActivationLoaderStatus:
    if previous_status in _TERMINAL_RUNTIME_STATUSES:
        raise ValueError("terminal runtime lifecycle state cannot transition")
    if action == RuntimeLifecycleAction.PAUSE:
        if previous_status != RuntimeActivationLoaderStatus.OBSERVING:
            raise ValueError("pause requires observing runtime state")
        return RuntimeActivationLoaderStatus.PAUSED
    if action == RuntimeLifecycleAction.RESUME:
        if previous_status != RuntimeActivationLoaderStatus.PAUSED:
            raise ValueError("resume requires paused runtime state")
        return RuntimeActivationLoaderStatus.OBSERVING
    if action == RuntimeLifecycleAction.END:
        if previous_status not in {
            RuntimeActivationLoaderStatus.OBSERVING,
            RuntimeActivationLoaderStatus.PAUSED,
        }:
            raise ValueError("end requires observing or paused runtime state")
        return RuntimeActivationLoaderStatus.ENDED
    if action == RuntimeLifecycleAction.ABORT:
        if previous_status not in {
            RuntimeActivationLoaderStatus.OBSERVING,
            RuntimeActivationLoaderStatus.PAUSED,
        }:
            raise ValueError("abort requires observing or paused runtime state")
        return RuntimeActivationLoaderStatus.ABORTED
    raise ValueError(f"unsupported lifecycle action: {action}")


def _require_runtime_state_root(path: Path | str) -> Path:
    root = Path(path)
    root.mkdir(parents=True, exist_ok=True)
    resolved = root.resolve()
    parts = resolved.parts
    if "tests" in parts and "fixtures" in parts and "pretrip" in parts:
        raise ValueError("runtime activation state must not be written to repo fixtures")
    return root


def _replace_json(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp_file:
            tmp_name = tmp_file.name
            tmp_file.write(payload)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        os.replace(tmp_name, path)
    finally:
        if tmp_name and Path(tmp_name).exists():
            Path(tmp_name).unlink()


def _canonical_json_text(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _sha256_json(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _assert_no_raw_payload_fragments(payload: Any) -> None:
    for text in _walk_strings(payload):
        lowered = text.lower()
        if any(fragment in lowered for fragment in _FORBIDDEN_LOWERCASE_FRAGMENTS):
            raise ValueError("forbidden runtime activation loader fragment")


def _walk_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        strings: list[str] = []
        for item in value.values():
            strings.extend(_walk_strings(item))
        return strings
    if isinstance(value, list):
        strings: list[str] = []
        for item in value:
            strings.extend(_walk_strings(item))
        return strings
    return []


_FORBIDDEN_LOWERCASE_FRAGMENTS = {
    "<gpx",
    "pdrsample",
    "sensor_records",
    "imu_records",
    "/private/",
    "/users/alexwang0315/downloads",
    "/users/alexwang0315/scout-fusion/catographydata",
}


_TERMINAL_RUNTIME_STATUSES = {
    RuntimeActivationLoaderStatus.ENDED,
    RuntimeActivationLoaderStatus.ABORTED,
}
