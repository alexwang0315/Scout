from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


RUNTIME_AUDIT_SCHEMA_VERSION = "scout_runtime_audit_event.v1"
RUNTIME_AUDIT_LIST_SCHEMA_VERSION = "scout_runtime_audit_list.v1"
RUNTIME_AUDIT_MANIFEST_SCHEMA_VERSION = "scout_runtime_audit_manifest.v1"

RuntimeAuditEventType = Literal[
    "runtime.instance.started",
    "runtime.instance.ended",
    "ui.session.started",
    "ui.session.heartbeat",
    "ui.session.expired",
    "http.request.completed",
    "provider.call.completed",
    "workspace.io.completed",
    "agent.run.completed",
    "background_job.completed",
    "audit.degraded",
]
RuntimeAuditOutcome = Literal[
    "started",
    "succeeded",
    "failed",
    "rejected",
    "cancelled",
    "timed_out",
    "degraded",
    "unknown",
]
RuntimeAuditSeverity = Literal["debug", "info", "warning", "error"]
RuntimeAuditCategory = Literal[
    "runtime",
    "dashboard",
    "provider",
    "workspace",
    "agent",
    "job",
    "audit",
]

_SAFE_SLUG_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"
_SAFE_WORKSPACE_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"
_SHA256_PATTERN = r"^[a-f0-9]{64}$"
_DATE_INDEX_KEY_PATTERN = r"^\d{4}-\d{2}(?:-\d{2})?$"


class RuntimeAuditRecordInput(BaseModel):
    """Typed, payload-free input accepted by the durable ledger."""

    model_config = ConfigDict(extra="forbid")

    event_type: RuntimeAuditEventType
    outcome: RuntimeAuditOutcome
    severity: RuntimeAuditSeverity = "info"
    category: RuntimeAuditCategory
    subcategory: str = Field(pattern=_SAFE_SLUG_PATTERN)
    module: str = Field(pattern=_SAFE_SLUG_PATTERN)
    feature: str = Field(pattern=_SAFE_SLUG_PATTERN)
    operation: str = Field(pattern=_SAFE_SLUG_PATTERN)
    summary: str = Field(min_length=1, max_length=280)
    detail: str | None = Field(default=None, max_length=500)
    detail_code: str | None = Field(default=None, pattern=_SAFE_SLUG_PATTERN)
    occurred_at: str | None = None

    ui_session_id: str | None = Field(default=None, pattern=_SAFE_SLUG_PATTERN)
    request_id: str | None = Field(default=None, pattern=_SAFE_SLUG_PATTERN)
    operation_id: str | None = Field(default=None, pattern=_SAFE_SLUG_PATTERN)
    agent_run_id: str | None = Field(default=None, pattern=_SAFE_SLUG_PATTERN)
    provider_call_id: str | None = Field(default=None, pattern=_SAFE_SLUG_PATTERN)
    workspace_io_id: str | None = Field(default=None, pattern=_SAFE_SLUG_PATTERN)
    parent_event_id: str | None = Field(default=None, pattern=_SAFE_SLUG_PATTERN)

    workspace_id: str | None = Field(default=None, pattern=_SAFE_WORKSPACE_PATTERN)
    artifact_kind: str | None = Field(default=None, pattern=_SAFE_SLUG_PATTERN)
    artifact_ref_hash: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    before_sha256: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    after_sha256: str | None = Field(default=None, pattern=_SHA256_PATTERN)

    provider: str | None = Field(default=None, max_length=120)
    model: str | None = Field(default=None, max_length=160)
    http_method: str | None = Field(
        default=None,
        pattern=r"^(GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)$",
    )
    route_template: str | None = Field(default=None, max_length=240)
    status_code: int | None = Field(default=None, ge=100, le=599)
    error_code: str | None = Field(default=None, pattern=_SAFE_SLUG_PATTERN)

    duration_ms: int | None = Field(default=None, ge=0)
    record_count: int | None = Field(default=None, ge=0)
    byte_count: int | None = Field(default=None, ge=0)
    attempt: int | None = Field(default=None, ge=1)
    retry_count: int | None = Field(default=None, ge=0)
    request_count: int | None = Field(default=None, ge=0)
    tool_call_count: int | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)

    telemetry_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @field_validator("occurred_at")
    @classmethod
    def validate_occurred_at(cls, value: str | None) -> str | None:
        if value is None:
            return None
        _validate_iso8601(value, field_name="occurred_at")
        return value


class RuntimeAuditEvent(RuntimeAuditRecordInput):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scout_runtime_audit_event.v1"] = (
        RUNTIME_AUDIT_SCHEMA_VERSION
    )
    event_id: str = Field(pattern=_SAFE_SLUG_PATTERN)
    sequence: int = Field(ge=1)
    recorded_at: str
    runtime_instance_id: str = Field(pattern=_SAFE_SLUG_PATTERN)
    previous_event_hash: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    event_hash: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("recorded_at")
    @classmethod
    def validate_recorded_at(cls, value: str) -> str:
        _validate_iso8601(value, field_name="recorded_at")
        return value


class RuntimeAuditIntegrity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verified: bool
    checked_event_count: int = Field(ge=0)
    error_count: int = Field(ge=0)
    first_error_code: str | None = None


class RuntimeAuditSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_events: int = Field(ge=0)
    succeeded_events: int = Field(ge=0)
    failed_events: int = Field(ge=0)
    degraded_events: int = Field(ge=0)
    internal_api_calls: int = Field(ge=0)
    provider_calls: int = Field(ge=0)
    workspace_reads: int = Field(ge=0)
    workspace_writes: int = Field(ge=0)
    agent_runs: int = Field(ge=0)
    background_jobs: int = Field(ge=0)
    total_records_touched: int = Field(ge=0)
    total_bytes_touched: int = Field(ge=0)
    by_category: dict[str, int] = Field(default_factory=dict)
    by_event_type: dict[str, int] = Field(default_factory=dict)
    by_outcome: dict[str, int] = Field(default_factory=dict)


class RuntimeAuditBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    telemetry_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    raw_payloads_embedded: Literal[False] = False


class RuntimeAuditCoverageItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["covered", "partial", "not_instrumented"]
    detail_code: str = Field(pattern=_SAFE_SLUG_PATTERN)


class RuntimeAuditCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runtime_lifecycle: RuntimeAuditCoverageItem
    internal_http: RuntimeAuditCoverageItem
    external_provider: RuntimeAuditCoverageItem
    workspace_io: RuntimeAuditCoverageItem
    agent_runs: RuntimeAuditCoverageItem
    background_jobs: RuntimeAuditCoverageItem


class RuntimeAuditWriterHealth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["healthy", "degraded"]
    dropped_event_count: int = Field(ge=0)
    last_error_code: str | None = Field(default=None, pattern=_SAFE_SLUG_PATTERN)


class RuntimeAuditDateIndexItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=_DATE_INDEX_KEY_PATTERN)
    event_count: int = Field(ge=0)


class RuntimeAuditDateIndex(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timezone_offset_minutes: int = Field(ge=-720, le=840)
    selected_day: str | None = Field(
        default=None,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    )
    selected_month: str | None = Field(
        default=None,
        pattern=r"^\d{4}-\d{2}$",
    )
    days: list[RuntimeAuditDateIndexItem] = Field(default_factory=list)
    months: list[RuntimeAuditDateIndexItem] = Field(default_factory=list)
    matched_event_count: int = Field(ge=0)
    returned_event_count: int = Field(ge=0)
    truncated: bool


class RuntimeAuditListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scout_runtime_audit_list.v1"] = (
        RUNTIME_AUDIT_LIST_SCHEMA_VERSION
    )
    generated_at: str
    status: Literal["ready", "empty", "degraded"]
    current_runtime_instance_id: str
    summary: RuntimeAuditSummary
    selected_summary: RuntimeAuditSummary
    integrity: RuntimeAuditIntegrity
    events: list[RuntimeAuditEvent] = Field(default_factory=list)
    available_runtime_instances: list[str] = Field(default_factory=list)
    date_index: RuntimeAuditDateIndex
    boundary: RuntimeAuditBoundary = Field(default_factory=RuntimeAuditBoundary)
    coverage: RuntimeAuditCoverage
    writer_health: RuntimeAuditWriterHealth


class RuntimeAuditManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scout_runtime_audit_manifest.v1"] = (
        RUNTIME_AUDIT_MANIFEST_SCHEMA_VERSION
    )
    runtime_instance_id: str = Field(pattern=_SAFE_SLUG_PATTERN)
    application: str = Field(pattern=_SAFE_SLUG_PATTERN)
    runtime_profile: str = Field(pattern=_SAFE_SLUG_PATTERN)
    workspace_id: str | None = Field(default=None, pattern=_SAFE_WORKSPACE_PATTERN)
    status: Literal["running", "ended", "interrupted"]
    started_at: str
    ended_at: str | None = None
    interruption_detected_at: str | None = None
    shutdown_reason: str | None = Field(default=None, pattern=_SAFE_SLUG_PATTERN)
    sequence_max: int = Field(ge=0)
    segment_count: int = Field(ge=0)
    last_event_hash: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    telemetry_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @field_validator("started_at", "ended_at", "interruption_detected_at")
    @classmethod
    def validate_manifest_times(cls, value: str | None) -> str | None:
        if value is None:
            return None
        _validate_iso8601(value, field_name="manifest timestamp")
        return value


def _validate_iso8601(value: str, *, field_name: str) -> None:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be ISO-8601 compatible") from exc


__all__ = [
    "RUNTIME_AUDIT_LIST_SCHEMA_VERSION",
    "RUNTIME_AUDIT_MANIFEST_SCHEMA_VERSION",
    "RUNTIME_AUDIT_SCHEMA_VERSION",
    "RuntimeAuditBoundary",
    "RuntimeAuditCategory",
    "RuntimeAuditCoverage",
    "RuntimeAuditCoverageItem",
    "RuntimeAuditDateIndex",
    "RuntimeAuditDateIndexItem",
    "RuntimeAuditEvent",
    "RuntimeAuditEventType",
    "RuntimeAuditIntegrity",
    "RuntimeAuditListResponse",
    "RuntimeAuditManifest",
    "RuntimeAuditOutcome",
    "RuntimeAuditRecordInput",
    "RuntimeAuditSeverity",
    "RuntimeAuditSummary",
    "RuntimeAuditWriterHealth",
]
