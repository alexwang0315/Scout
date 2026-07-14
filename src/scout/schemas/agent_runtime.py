"""Bounded context, tool, evidence, and run-budget contracts."""

from __future__ import annotations

from datetime import datetime
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


class ToolPlan(SchemaModel):
    """Typed, hard-capped plan consumed by deterministic tool execution."""

    selected_tool_ids: list[NonEmptyStr] = Field(default_factory=list, max_length=5)
    tool_calls: list[PlannedToolCall] = Field(default_factory=list, max_length=5)
    estimated_input_tokens: int = Field(default=0, ge=0)
    estimated_output_tokens: int = Field(default=0, ge=0)
    required_bundle_expansion: list[NonEmptyStr] = Field(default_factory=list)
    stop_or_replan_condition: NonEmptyStr

    @model_validator(mode="after")
    def validate_tool_ids(self) -> "ToolPlan":
        if len(self.selected_tool_ids) > 5 or len(self.tool_calls) > 5:
            raise ValueError("a ToolPlan may select at most 5 tools")
        if len(set(self.selected_tool_ids)) != len(self.selected_tool_ids):
            raise ValueError("selected_tool_ids must be unique")
        call_ids = [call.tool_id for call in self.tool_calls]
        if call_ids != self.selected_tool_ids:
            raise ValueError("selected_tool_ids must match tool_calls in order")
        return self


class EvidenceCard(SchemaModel):
    """Bounded model-facing projection of a raw deterministic tool result."""

    tool_id: NonEmptyStr
    claim_summary: str = ""
    key_values: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    freshness: NonEmptyStr = "unknown"
    quality: NonEmptyStr = "unknown"
    source_refs: list[NonEmptyStr] = Field(default_factory=list)
    result_count: int = Field(default=0, ge=0)
    truncated: bool = False
    continuation_handle: str | None = None
    estimated_tokens: int = Field(default=0, ge=0)
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


class AgentRunBudget(SchemaModel):
    """Deterministic hard limits for one user turn."""

    max_requests: int = Field(default=2, ge=1, le=3)
    max_tool_calls: int = Field(default=3, ge=0, le=5)
    max_input_tokens: int = Field(default=20_000, ge=1)
    max_output_tokens: int = Field(default=2_000, ge=1)
    max_total_tokens: int = Field(default=22_000, ge=1)
    max_repairs: int = Field(default=1, ge=0, le=1)
    max_tool_result_tokens: int = Field(default=1_000, ge=50, le=2_000)
    max_estimated_cost: float | None = Field(default=None, gt=0.0)


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
    repair_count: int = Field(default=0, ge=0, le=1)
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
    repair_count: int = Field(default=0, ge=0, le=1)


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
    "AgentRequestLedger",
    "AgentRunBudget",
    "AgentRunLedger",
    "ContextHandle",
    "ContextReadResult",
    "EvidenceCard",
    "GroundingVerification",
    "PlannedToolCall",
    "ToolCard",
    "ToolPlan",
]
