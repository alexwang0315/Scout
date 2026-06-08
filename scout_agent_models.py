from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ScoutAgentBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScoutAgentActionMode(StrEnum):
    LOCAL_EVIDENCE_QUERY = "local_evidence_query"
    DECISION_SUPPORT = "decision_support"
    PROPOSAL_WRITE = "proposal_write"
    WORKSPACE_WRITE = "workspace_write"
    PACKAGE_WRITE = "package_write"
    OUTBOUND_PREVIEW = "outbound_preview"
    OUTBOUND_SEND = "outbound_send"
    HARDWARE_ACTION = "hardware_action"
    OPERATOR_TRIGGERED_TOOL = "operator_triggered_tool"
    EPHEMERAL_SAFETY_ACTION = "ephemeral_safety_action"
    SOS_DELEGATED_EMERGENCY = "sos_delegated_emergency"
    RUNTIME_SAFETY_MUTATION = "runtime_safety_mutation"


class ScoutAgentAuthorizationKind(StrEnum):
    NONE = "none"
    USER = "user"
    OPERATOR = "operator"
    USER_OR_OPERATOR = "user_or_operator"
    MANUAL_SEND = "manual_send"
    USER_TRIGGERED = "user_triggered"
    SOS_DELEGATED = "sos_delegated"


class ScoutAgentToolStatus(StrEnum):
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    PARTIAL = "partial"


class ScoutAgentToolCommand(ScoutAgentBaseModel):
    argv: list[str] = Field(min_length=1)
    cwd: str | None = None
    dry_run_argument: str | None = "--dry-run"


class ScoutAgentToolAuthorization(ScoutAgentBaseModel):
    kind: ScoutAgentAuthorizationKind = ScoutAgentAuthorizationKind.NONE


class ScoutAgentToolTraceConfig(ScoutAgentBaseModel):
    required: bool = True
    event_kind: str = "agent_tool_invocation"


class ScoutAgentToolManifest(ScoutAgentBaseModel):
    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.:-]+$")
    version: str = Field(min_length=1)
    description: str = Field(min_length=1)
    command: ScoutAgentToolCommand
    mode: ScoutAgentActionMode
    input_schema_ref: str | None = None
    output_schema_ref: str | None = None
    allowed_reads: list[str] = Field(default_factory=list)
    allowed_writes: list[str] = Field(default_factory=list)
    forbidden_writes: list[str] = Field(default_factory=list)
    supports_dry_run: bool = True
    requires_authorization: ScoutAgentToolAuthorization = Field(
        default_factory=ScoutAgentToolAuthorization
    )
    trace: ScoutAgentToolTraceConfig = Field(default_factory=ScoutAgentToolTraceConfig)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_tool_boundary(self) -> "ScoutAgentToolManifest":
        if self.mode == ScoutAgentActionMode.RUNTIME_SAFETY_MUTATION:
            raise ValueError("runtime_safety_mutation tools are not allowed in this registry")
        overlap = set(self.allowed_writes) & set(self.forbidden_writes)
        if overlap:
            joined = ", ".join(sorted(overlap))
            raise ValueError(f"allowed_writes overlaps forbidden_writes: {joined}")
        blocked = [
            target
            for target in self.allowed_writes
            if _is_forbidden_runtime_write_surface(target)
        ]
        if blocked:
            joined = ", ".join(sorted(blocked))
            raise ValueError(f"tool manifest allows forbidden runtime write surface: {joined}")
        return self


class ScoutAgentSourceRef(ScoutAgentBaseModel):
    source_id: str = Field(min_length=1)
    source_path: str | None = None
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    evidence_type: str | None = None


class ScoutAgentToolEffects(ScoutAgentBaseModel):
    workspace_write_count: int = Field(default=0, ge=0)
    package_write_count: int = Field(default=0, ge=0)
    outbound_send_count: int = Field(default=0, ge=0)
    hardware_action_count: int = Field(default=0, ge=0)
    phase1_safety_mutation_count: Literal[0] = 0


class ScoutAgentToolBoundary(ScoutAgentBaseModel):
    runtime_safety_truth: Literal[False] = False
    autonomous_mutation: bool = False
    operator_or_user_triggered: bool = False
    live_safety_api_calls_allowed: Literal[False] = False
    phase1_safety_mutation_allowed: Literal[False] = False
    model_output_is_runtime_truth: Literal[False] = False
    remote_outbound_send_allowed: bool = False
    hardware_control_allowed: bool = False


class ScoutAgentToolResult(ScoutAgentBaseModel):
    artifact_kind: Literal["scout_agent_tool_result"] = "scout_agent_tool_result"
    tool_id: str = Field(min_length=1)
    tool_version: str = Field(min_length=1)
    action_id: str = Field(min_length=1)
    agent_run_id: str = Field(min_length=1)
    status: ScoutAgentToolStatus
    mode: ScoutAgentActionMode
    started_at: str
    ended_at: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    effects: ScoutAgentToolEffects = Field(default_factory=ScoutAgentToolEffects)
    boundary: ScoutAgentToolBoundary = Field(default_factory=ScoutAgentToolBoundary)
    source_refs: list[ScoutAgentSourceRef] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    receipt_refs: list[str] = Field(default_factory=list)

    @field_validator("started_at", "ended_at")
    @classmethod
    def validate_datetime(cls, value: str) -> str:
        parse_agent_datetime(value)
        return value


def parse_agent_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def scout_agent_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_forbidden_runtime_write_surface(value: str) -> bool:
    normalized = value.strip().lower()
    blocked_prefixes = (
        "phase1.runtime",
        "phase1.safety",
        "live.safety_api",
        "safety_api",
    )
    if normalized in blocked_prefixes:
        return True
    if any(normalized.startswith(f"{prefix}.") for prefix in blocked_prefixes):
        return True
    return "/safety/" in normalized or normalized.startswith("/safety/")
