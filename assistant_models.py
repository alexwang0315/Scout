from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scout.schemas.agent_runtime import AgentRequestLedger


class AssistantSurface(str, Enum):
    DEBUG = "debug"
    ADMIN = "admin"
    PRETRIP = "pretrip"
    HARDWARE_READINESS = "hardware_readiness"


class AssistantSurfaceConstraint(str, Enum):
    DEBUG_READ_ONLY = "debug_read_only"
    ADMIN_AFTER_ACTION_READ_ONLY = "admin_after_action_read_only"
    PRETRIP_READ_ONLY = "pretrip_read_only"
    HARDWARE_READINESS_READ_ONLY = "hardware_readiness_read_only"


class AssistantRuntimePreference(str, Enum):
    CLOUD = "cloud"
    AI_HAT_PLUS_2_FALLBACK = "ai_hat_plus_2_fallback"


class AssistantSourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1)
    source_path: str | None = None
    evidence_type: str | None = None
    selected: bool = False
    context_summary: dict[str, Any] | None = None


class AssistantBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    surface: AssistantSurface
    read_only: Literal[True] = True
    model_interpretation: Literal[True] = True
    phase1_mutation_allowed: Literal[False] = False
    safety_mutation_allowed: Literal[False] = False
    phase2_writeback_allowed: Literal[False] = False
    observed_fact_write_allowed: Literal[False] = False
    derived_measurement_write_allowed: Literal[False] = False
    incident_store_write_allowed: Literal[False] = False
    human_review_mutation_allowed: Literal[False] = False
    pretrip_review_mutation_allowed: Literal[False] = False
    outbound_send_allowed: Literal[False] = False
    real_sos_allowed: Literal[False] = False
    real_sms_allowed: Literal[False] = False
    real_satellite_allowed: Literal[False] = False
    hardware_control_allowed: Literal[False] = False


class AssistantObservability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_class: str
    source_count: int = Field(ge=0)
    selected_source_count: int = Field(ge=0)
    context_size_chars: int = Field(ge=0)
    latency_ms: int = Field(ge=0)
    latency_class: Literal["fast", "slow", "timeout_or_error"]
    safe_failure: bool = False
    model_profile_used: str | None = None
    failover_reason: str | None = None
    local_model_name: str | None = None
    request_count: int | None = Field(default=None, ge=0)
    tool_call_count: int | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    cache_write_tokens: int | None = Field(default=None, ge=0)
    cache_read_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    system_chars: int | None = Field(default=None, ge=0)
    tool_schema_count: int | None = Field(default=None, ge=0)
    tool_schema_chars: int | None = Field(default=None, ge=0)
    user_history_chars: int | None = Field(default=None, ge=0)
    tool_result_chars: int | None = Field(default=None, ge=0)
    estimated_cost: float | None = Field(default=None, ge=0.0)
    cost_estimate_available: bool | None = None
    budget_remaining: dict[str, int | float | None] | None = None
    budget_stop_reason: str | None = None
    selected_tool_ids: list[str] = Field(default_factory=list)
    executed_tool_ids: list[str] = Field(default_factory=list)
    mser_mode: Literal["off", "shadow", "enforce"] | None = None
    mser_sufficiency_status: str | None = None
    mser_reasoning_disposition: str | None = None
    mser_selected_tool_ids: list[str] = Field(default_factory=list)
    mser_answer_verification_passed: bool | None = None
    retry_count: int | None = Field(default=None, ge=0)
    repair_count: int | None = Field(default=None, ge=0, le=1)
    request_ledger: list[AgentRequestLedger] = Field(default_factory=list)


class AssistantOfflineFallbackSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    prompt_id: str
    summary_zh: str
    risk_signals: list[str] = Field(default_factory=list)
    operator_checks: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"]
    read_only: Literal[True] = True
    model_interpretation: Literal[True] = True
    safety_authority: Literal[False] = False
    phase1_state_change_allowed: Literal[False] = False
    observed_fact_write_allowed: Literal[False] = False
    outbound_action_allowed: Literal[False] = False
    hardware_control_allowed: Literal[False] = False


class AssistantSurfacePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    surface: AssistantSurface
    constraint: AssistantSurfaceConstraint
    allowed_reads: tuple[str, ...]
    may_answer: tuple[str, ...]
    forbidden_actions: tuple[str, ...]


ASSISTANT_SURFACE_CONSTRAINTS: dict[AssistantSurface, AssistantSurfacePolicy] = {
    AssistantSurface.DEBUG: AssistantSurfacePolicy(
        surface=AssistantSurface.DEBUG,
        constraint=AssistantSurfaceConstraint.DEBUG_READ_ONLY,
        allowed_reads=(
            "debug events",
            "selected timeline node",
            "debug state",
            "debug messages",
            "Phase 3.5 boundary snapshot",
        ),
        may_answer=(
            "runtime timeline explanation",
            "L0-L4 transition explanation",
            "provider degraded status",
            "mock outbound status",
            "Ln gate and skill run visibility",
        ),
        forbidden_actions=(
            "mutate safety runtime",
            "call /safety/*",
            "send outbound",
            "change debug log",
        ),
    ),
    AssistantSurface.ADMIN: AssistantSurfacePolicy(
        surface=AssistantSurface.ADMIN,
        constraint=AssistantSurfaceConstraint.ADMIN_AFTER_ACTION_READ_ONLY,
        allowed_reads=(
            "after-action evidence tree",
            "incident package refs",
            "map/evidence selection",
            "Phase 2 preview snapshots",
        ),
        may_answer=(
            "what happened",
            "which evidence supports it",
            "which persisted package or adapter output exists",
        ),
        forbidden_actions=(
            "rewrite historical incident/evidence",
            "write Brain nodes",
            "alter after-action package",
        ),
    ),
    AssistantSurface.PRETRIP: AssistantSurfacePolicy(
        surface=AssistantSurface.PRETRIP,
        constraint=AssistantSurfaceConstraint.PRETRIP_READ_ONLY,
        allowed_reads=(
            "project manifest",
            "candidates",
            "source registry",
            "review queue",
            "readiness/departure gate artifacts",
        ),
        may_answer=(
            "planning state",
            "candidate provenance",
            "missing review items",
            "readiness blockers",
        ),
        forbidden_actions=(
            "accept/reject candidates",
            "create reviewed facts",
            "compile runtime handoff",
            "approve departure",
        ),
    ),
    AssistantSurface.HARDWARE_READINESS: AssistantSurfacePolicy(
        surface=AssistantSurface.HARDWARE_READINESS,
        constraint=AssistantSurfaceConstraint.HARDWARE_READINESS_READ_ONLY,
        allowed_reads=(
            "provider health fixture",
            "sample replay timeline",
            "runtime debug log",
            "mock transport queue",
        ),
        may_answer=(
            "provider status",
            "sample replay interpretation",
            "debug readiness checklist",
        ),
        forbidden_actions=(
            "control hardware",
            "change provider state",
            "open real transport",
            "start Pi/Docker deployment",
        ),
    ),
}


class ScoutAssistantQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    surface: AssistantSurface
    question: str = Field(min_length=1, max_length=2000)
    context_ref: str | None = Field(default=None, max_length=255)
    selected_event_id: str | None = None
    selected_artifact_id: str | None = None
    project_id: str | None = Field(default=None, max_length=255)
    runtime_preference: AssistantRuntimePreference | None = None
    ai_hat_raw_eval: bool = False
    live_navigation_snapshot: dict[str, Any] | None = None

    @field_validator("context_ref", "project_id")
    @classmethod
    def validate_workspace_identifier(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value in {".", ".."} or any(char in value for char in ("/", "\\", "\x00")):
            raise ValueError("workspace identifiers must not contain path components")
        return value


class AssistantLocalModelAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_index: int = Field(ge=1)
    answer: str = Field(min_length=1)
    grounding_ok: bool
    brief_violations: list[str] = Field(default_factory=list)
    selected: bool = False


class ScoutAssistantResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    surface: AssistantSurface
    answer: str = Field(min_length=1)
    local_model_answer: str | None = None
    local_model_attempts: list[AssistantLocalModelAttempt] = Field(default_factory=list)
    evidence_backed_answer: str | None = None
    model_interpretation: Literal[True] = True
    read_only: Literal[True] = True
    sources: list[AssistantSourceRef] = Field(default_factory=list)
    boundary: AssistantBoundary
    limitations: list[str] = Field(default_factory=list)
    observability: AssistantObservability | None = None
    offline_fallback: AssistantOfflineFallbackSummary | None = None

    @model_validator(mode="after")
    def boundary_must_match_surface(self) -> "ScoutAssistantResponse":
        if self.boundary.surface != self.surface:
            raise ValueError("assistant boundary surface must match response surface")
        return self
