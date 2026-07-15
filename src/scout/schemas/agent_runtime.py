"""Bounded context, tool, evidence, and run-budget contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from scout.schemas.base import NonEmptyStr, SchemaModel


class ContextHandle(SchemaModel):
    """Small discovery result that points to a workspace artifact."""

    context_id: NonEmptyStr
    domain_id: NonEmptyStr
    artifact_kind: NonEmptyStr
    title: NonEmptyStr
    source_ref: NonEmptyStr
    observed_at: datetime | None = None
    freshness: NonEmptyStr = "unknown"
    scope_metadata: dict[str, Any] = Field(default_factory=dict)
    time_metadata: dict[str, Any] = Field(default_factory=dict)
    spatial_metadata: dict[str, Any] = Field(default_factory=dict)
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    estimated_tokens: int = Field(default=0, ge=0)
    sensitivity: NonEmptyStr = "internal"
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


class ContextReadResult(SchemaModel):
    """Bounded content returned after explicitly reading a context handle."""

    context_id: NonEmptyStr
    source_ref: NonEmptyStr
    selector: str | None = None
    content: Any
    truncated: bool = False
    continuation_handle: str | None = None
    estimated_tokens: int = Field(default=0, ge=0)
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


class ToolCard(SchemaModel):
    """Compact tool discovery metadata. Full schemas intentionally live elsewhere."""

    tool_id: NonEmptyStr
    purpose: NonEmptyStr
    required_inputs: list[NonEmptyStr] = Field(default_factory=list)
    output_artifact_kind: NonEmptyStr
    risk_level: NonEmptyStr
    estimated_cost: float = Field(default=0.0, ge=0.0)
    availability: NonEmptyStr
    implementation_status: NonEmptyStr


class PlannedToolCall(SchemaModel):
    tool_id: NonEmptyStr
    arguments: dict[str, Any] = Field(default_factory=dict)
    reason: NonEmptyStr
    expected_evidence: list[NonEmptyStr] = Field(default_factory=list)


class QuestionClass(StrEnum):
    STATIC_WORKSPACE_FACT = "static_workspace_fact"
    AGGREGATE_WORKSPACE_FACT = "aggregate_workspace_fact"
    CROSS_ARTIFACT_JOIN = "cross_artifact_join"
    SPATIAL_ROUTE_FACT = "spatial_route_fact"
    WEATHER_TERRAIN_COMPOUND = "weather_terrain_compound"
    LIVE_RUNTIME_FACT = "live_runtime_fact"
    SAFETY_DECISION = "safety_decision"
    UNKNOWN = "unknown"


class AgentRecoveryStage(StrEnum):
    """Finite recovery ladder; every stage receives a fresh call budget."""

    INITIAL = "initial"
    CONTINUATION = "continuation"
    TOOL_REPAIR = "tool_repair"
    MODEL_SWITCH = "model_switch"
    CODEX_REVIEW = "codex_review"
    KNOWN_ISSUE = "known_issue"


class AgentAttemptStatus(StrEnum):
    RUNNING = "running"
    STAGE_COMPLETE = "stage_complete"
    EXTERNAL_LIMIT = "external_limit"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class AgentRecoveryRootCause(StrEnum):
    TOOL_GAP = "Tool Gap"
    MODEL_WEAKNESS = "Model Weakness"
    MISSING_EVIDENCE = "Missing Evidence"
    AMBIGUOUS_EXPECTATION = "Ambiguous Expectation"
    HARNESS_FAILURE = "Harness Failure"
    BENCHMARK_DEFECT = "Benchmark Defect"


class AgentQueryStage(StrEnum):
    DISCOVER = "discover"
    QUERY = "query"
    JOIN = "join"
    VERIFY = "verify"
    SYNTHESIS = "synthesis"
    REPAIR = "repair"


class ToolPlan(SchemaModel):
    """Typed plan consumed by deterministic tool execution."""

    selected_tool_ids: list[NonEmptyStr] = Field(default_factory=list)
    tool_calls: list[PlannedToolCall] = Field(default_factory=list)
    estimated_input_tokens: int = Field(default=0, ge=0)
    estimated_output_tokens: int = Field(default=0, ge=0)
    required_bundle_expansion: list[NonEmptyStr] = Field(default_factory=list)
    stop_or_replan_condition: NonEmptyStr

    @model_validator(mode="after")
    def validate_tool_ids(self) -> "ToolPlan":
        if len(set(self.selected_tool_ids)) != len(self.selected_tool_ids):
            raise ValueError("selected_tool_ids must be unique")
        call_ids = [call.tool_id for call in self.tool_calls]
        if call_ids != self.selected_tool_ids:
            raise ValueError("selected_tool_ids must match tool_calls in order")
        return self


class EvidenceRecord(SchemaModel):
    """Stable record-level proof retained through synthesis and verification."""

    evidence_id: NonEmptyStr
    source_ref: NonEmptyStr
    record_id: NonEmptyStr
    locator: NonEmptyStr
    source_hash: NonEmptyStr
    data: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


class EvidenceCard(SchemaModel):
    """Bounded model-facing projection of a raw deterministic tool result."""

    tool_id: NonEmptyStr
    claim_summary: str = ""
    key_values: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    freshness: NonEmptyStr = "unknown"
    quality: NonEmptyStr = "unknown"
    source_refs: list[NonEmptyStr] = Field(default_factory=list)
    evidence_records: list[EvidenceRecord] = Field(default_factory=list)
    result_count: int = Field(default=0, ge=0)
    truncated: bool = False
    continuation_handle: str | None = None
    estimated_tokens: int = Field(default=0, ge=0)
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


class AgentStageBudget(SchemaModel):
    """Minimum per-stage capacities nested under one attempt budget."""

    discover_tool_calls: int = Field(default=10, ge=10)
    query_tool_calls: int = Field(default=10, ge=10)
    join_tool_calls: int = Field(default=10, ge=10)
    verify_tool_calls: int = Field(default=10, ge=10)
    planner_model_requests: int = Field(default=10, ge=10)
    retriever_model_requests: int = Field(default=10, ge=10)
    synthesis_model_requests: int = Field(default=10, ge=10)
    verifier_model_requests: int = Field(default=10, ge=10)
    reviewer_model_requests: int = Field(default=10, ge=10)
    repair_model_requests: int = Field(default=10, ge=10)
    retry_model_requests: int = Field(default=10, ge=10)
    replan_model_requests: int = Field(default=10, ge=10)
    browser_model_requests: int = Field(default=10, ge=10)
    subagent_model_requests: int = Field(default=10, ge=10)

    def tool_call_limit(self, stage: AgentQueryStage) -> int:
        return {
            AgentQueryStage.DISCOVER: self.discover_tool_calls,
            AgentQueryStage.QUERY: self.query_tool_calls,
            AgentQueryStage.JOIN: self.join_tool_calls,
            AgentQueryStage.VERIFY: self.verify_tool_calls,
            AgentQueryStage.SYNTHESIS: 0,
            AgentQueryStage.REPAIR: 0,
        }[stage]


class AgentRunBudget(SchemaModel):
    """Per-attempt call capacity and optional product resource ceilings."""

    question_class: QuestionClass = QuestionClass.UNKNOWN
    recovery_stage: AgentRecoveryStage = AgentRecoveryStage.INITIAL
    attempt_index: int = Field(default=1, ge=1)
    max_requests: int = Field(default=10, ge=10)
    max_tool_calls: int = Field(default=10, ge=10)
    max_input_tokens: int | None = Field(default=None, ge=1)
    max_output_tokens: int | None = Field(default=None, ge=1)
    max_total_tokens: int | None = Field(default=None, ge=1)
    max_repairs: int = Field(default=10, ge=10)
    max_tool_result_tokens: int | None = Field(default=None, ge=50)
    max_estimated_cost: float | None = Field(default=None, gt=0.0)
    enforce_resource_limits: bool = False
    stage_budget: AgentStageBudget = Field(default_factory=AgentStageBudget)


class AgentProgressState(SchemaModel):
    """Immutable no-progress state for staged progressive retrieval."""

    stage: AgentQueryStage = AgentQueryStage.DISCOVER
    canonical_call_keys: list[NonEmptyStr] = Field(default_factory=list)
    evidence_ids: list[NonEmptyStr] = Field(default_factory=list)
    consecutive_calls_without_new_evidence: int = Field(default=0, ge=0)
    safe_retry_root_causes: list[NonEmptyStr] = Field(default_factory=list)
    stage_tool_call_counts: dict[AgentQueryStage, int] = Field(default_factory=dict)
    stop_reason: str | None = None


class AgentRequestLedger(SchemaModel):
    """Overhead and provider usage for one provider request."""

    request_index: int = Field(ge=1)
    system_chars: int = Field(default=0, ge=0)
    tool_schema_count: int = Field(default=0, ge=0)
    tool_schema_chars: int = Field(default=0, ge=0)
    user_history_chars: int = Field(default=0, ge=0)
    tool_result_chars: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    cache_write_tokens: int = Field(default=0, ge=0)
    cache_read_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    tool_call_count: int = Field(default=0, ge=0)
    retry_count: int = Field(default=0, ge=0)
    repair_count: int = Field(default=0, ge=0)
    estimated_cost: float = Field(default=0.0, ge=0.0)
    cost_estimate_available: bool = False


class AgentRunLedger(SchemaModel):
    """Aggregate accounting and stop state for one user turn."""

    budget: AgentRunBudget = Field(default_factory=AgentRunBudget)
    requests: list[AgentRequestLedger] = Field(default_factory=list)
    request_count: int = Field(default=0, ge=0)
    tool_call_count: int = Field(default=0, ge=0)
    system_chars: int = Field(default=0, ge=0)
    tool_schema_count: int = Field(default=0, ge=0)
    tool_schema_chars: int = Field(default=0, ge=0)
    user_history_chars: int = Field(default=0, ge=0)
    tool_result_chars: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    cache_write_tokens: int = Field(default=0, ge=0)
    cache_read_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    estimated_cost: float = Field(default=0.0, ge=0.0)
    cost_estimate_available: bool = False
    budget_remaining: dict[str, int | float | None] = Field(default_factory=dict)
    budget_stop_reason: str | None = None
    selected_tool_ids: list[str] = Field(default_factory=list)
    executed_tool_ids: list[str] = Field(default_factory=list)
    retry_count: int = Field(default=0, ge=0)
    repair_count: int = Field(default=0, ge=0)


class AgentAttemptState(SchemaModel):
    """One isolated attempt; counters never carry into a recovery stage."""

    attempt_id: NonEmptyStr
    question: NonEmptyStr
    question_class: QuestionClass
    recovery_stage: AgentRecoveryStage
    attempt_index: int = Field(ge=1)
    budget: AgentRunBudget
    ledger: AgentRunLedger
    status: AgentAttemptStatus = AgentAttemptStatus.RUNNING
    model_id: str | None = None
    continuation_of: str | None = None
    parent_recovery_stage: AgentRecoveryStage | None = None

    @model_validator(mode="after")
    def validate_attempt_budget(self) -> "AgentAttemptState":
        if self.budget.attempt_index != self.attempt_index:
            raise ValueError("attempt budget index must match attempt state")
        if self.budget.recovery_stage != self.recovery_stage:
            raise ValueError("attempt budget stage must match attempt state")
        if self.ledger.budget != self.budget:
            raise ValueError("attempt ledger must use the fresh attempt budget")
        return self


class AgentContinuationCheckpoint(SchemaModel):
    """Compacted state persisted when an external platform interrupts a run."""

    checkpoint_id: NonEmptyStr
    attempt_id: NonEmptyStr
    question: NonEmptyStr
    recovery_stage: AgentRecoveryStage
    attempt_index: int = Field(ge=1)
    reason: NonEmptyStr
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    source_refs: list[NonEmptyStr] = Field(default_factory=list)
    call_trace: list[dict[str, Any]] = Field(default_factory=list)
    state: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    external_limit: Literal[True] = True
    compacted: Literal[True] = True
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


class AgentReviewArtifact(SchemaModel):
    """Complete handoff package for independent Codex diagnosis."""

    artifact_kind: Literal["scout_agent_codex_review"] = "scout_agent_codex_review"
    review_id: NonEmptyStr
    recovery_stage: Literal[AgentRecoveryStage.CODEX_REVIEW] = (
        AgentRecoveryStage.CODEX_REVIEW
    )
    original_question: NonEmptyStr
    expected_answer_or_success_condition: NonEmptyStr
    available_evidence: list[dict[str, Any]] = Field(default_factory=list)
    source_references: list[NonEmptyStr] = Field(default_factory=list)
    complete_call_trace: list[dict[str, Any]] = Field(default_factory=list)
    tool_outputs: list[dict[str, Any]] = Field(default_factory=list)
    models_used: list[NonEmptyStr] = Field(default_factory=list)
    repairs_applied: list[NonEmptyStr] = Field(default_factory=list)
    actual_failure_symptom: NonEmptyStr
    candidate_answer: str | None = None
    root_cause_options: list[AgentRecoveryRootCause] = Field(
        default_factory=lambda: list(AgentRecoveryRootCause)
    )
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


class AgentKnownIssue(SchemaModel):
    """Terminal record used only after the fixed recovery ladder is exhausted."""

    artifact_kind: Literal["scout_agent_known_issue"] = "scout_agent_known_issue"
    status: Literal["KNOWN_ISSUE"] = "KNOWN_ISSUE"
    stable_id: NonEmptyStr
    original_question: NonEmptyStr
    root_cause: AgentRecoveryRootCause
    reproduction: NonEmptyStr
    last_evidence: list[dict[str, Any]] = Field(default_factory=list)
    tool_repairs_tried: list[NonEmptyStr] = Field(default_factory=list)
    models_tried: list[NonEmptyStr] = Field(default_factory=list)
    current_blocker: NonEmptyStr
    explicit_unblock_condition: NonEmptyStr
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


class GroundingVerification(SchemaModel):
    passed: bool
    output_disposition: Literal["grounded", "needs_repair", "fail_closed"] = (
        "grounded"
    )
    cited_source_refs: list[str] = Field(default_factory=list)
    invalid_source_refs: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    rejected_draft_claims: list[str] = Field(default_factory=list)
    repair_items: list[str] = Field(default_factory=list)


__all__ = [
    "AgentAttemptState",
    "AgentAttemptStatus",
    "AgentContinuationCheckpoint",
    "AgentKnownIssue",
    "AgentProgressState",
    "AgentQueryStage",
    "AgentRecoveryStage",
    "AgentRequestLedger",
    "AgentReviewArtifact",
    "AgentRecoveryRootCause",
    "AgentRunBudget",
    "AgentRunLedger",
    "AgentStageBudget",
    "ContextHandle",
    "ContextReadResult",
    "EvidenceCard",
    "EvidenceRecord",
    "GroundingVerification",
    "PlannedToolCall",
    "QuestionClass",
    "ToolCard",
    "ToolPlan",
]
