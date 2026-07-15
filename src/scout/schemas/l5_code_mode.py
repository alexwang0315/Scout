"""Typed contracts for Scout's system-activated L5 Code Mode."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import ConfigDict, Field

from scout.schemas.base import NonEmptyStr, SchemaModel


class L5SafetyLevel(StrEnum):
    """Safety signal accepted by the L5 activation policy.

    L5 is intentionally absent: it is a computation mode, not a replacement
    for the canonical L0-L4 human-safety signal.
    """

    NORMAL = "L0_NORMAL"
    WATCH = "L1_WATCH"
    CONCERN = "L2_CONCERN"
    DISTRESS = "L3_DISTRESS"
    EMERGENCY = "L4_EMERGENCY"


class L5ActivationState(StrEnum):
    BLOCKED = "blocked"
    ENABLED_UNDER_CONSTRUCTION = "enabled_under_construction"
    ENABLED_SYSTEM = "enabled_system"


class L5ExecutionBoundary(SchemaModel):
    """Immutable authority boundary shared by development and production L5."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ephemeral_sandbox_required: Literal[True] = True
    workspace_read_allowed: Literal[True] = True
    host_shell_allowed: Literal[False] = False
    workspace_write_allowed: Literal[False] = False
    unrestricted_network_allowed: Literal[False] = False
    secret_access_allowed: Literal[False] = False
    hardware_control_allowed: Literal[False] = False
    direct_outbound_send_allowed: Literal[False] = False
    production_database_write_allowed: Literal[False] = False
    runtime_safety_truth_mutation_allowed: Literal[False] = False


class L5ActivationRequest(SchemaModel):
    """Inputs to the deterministic L5 eligibility decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    under_construction: bool = False
    safety_level: L5SafetyLevel = L5SafetyLevel.NORMAL
    critical_capability_gap: bool = False
    sandbox_available: bool = False
    resource_budget_available: bool = False
    expected_information_value: float = Field(default=0.0, ge=0.0, le=1.0)
    system_assessment: bool = False
    human_requested: bool = False


class L5ActivationDecision(SchemaModel):
    """Machine-readable decision that other agents must honor."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_kind: Literal["scout_l5_code_mode_activation_decision"] = (
        "scout_l5_code_mode_activation_decision"
    )
    schema_version: Literal["scout.l5_code_mode.activation.v1"] = (
        "scout.l5_code_mode.activation.v1"
    )
    l5_code_mode: bool
    state: L5ActivationState
    reason: NonEmptyStr
    blockers: list[NonEmptyStr] = Field(default_factory=list)
    requires_human_approval: Literal[False] = False
    human_can_activate_l5: Literal[False] = False
    model_can_activate_l5: Literal[False] = False
    boundary: L5ExecutionBoundary = Field(default_factory=L5ExecutionBoundary)


class L5RuntimeStatus(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    backend: Literal["pydantic_ai_harness.CodeMode"] = (
        "pydantic_ai_harness.CodeMode"
    )
    available: bool
    reason: NonEmptyStr
    install_hint: str = ""
    stop_condition: str = ""
    harness_version: str | None = None
    monty_version: str | None = None
    runtime_attested: bool = False


class L5NestedToolCallReceipt(SchemaModel):
    """Redacted proof for one host tool called from inside Monty."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int = Field(ge=1)
    tool_id: NonEmptyStr
    tool_name: NonEmptyStr
    arguments_sha256: NonEmptyStr
    operation: str | None = None
    status: Literal["success", "error"]
    source_refs: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    error_code: str | None = None


class L5ExecutionReceipt(SchemaModel):
    """Immutable, secret-minimized receipt for one ephemeral L5 run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_kind: Literal["scout_l5_code_mode_execution_receipt"] = (
        "scout_l5_code_mode_execution_receipt"
    )
    schema_version: Literal["scout.l5_code_mode.execution.v1"] = (
        "scout.l5_code_mode.execution.v1"
    )
    receipt_id: NonEmptyStr
    created_at: datetime
    status: Literal["success", "fail_closed"]
    activation_state: L5ActivationState
    activation_request_sha256: NonEmptyStr
    activation_decision_sha256: NonEmptyStr
    policy_version: Literal["scout.l5.policy.v1"] = "scout.l5.policy.v1"
    backend: Literal["pydantic_ai_harness.CodeMode"] = (
        "pydantic_ai_harness.CodeMode"
    )
    harness_version: NonEmptyStr
    monty_version: NonEmptyStr
    runtime_attested: Literal[True] = True
    project_id: NonEmptyStr
    project_identity_sha256: NonEmptyStr
    prompt_sha256: NonEmptyStr
    generated_code_sha256: list[NonEmptyStr] = Field(default_factory=list)
    generated_code_char_count: int = Field(default=0, ge=0)
    generated_code: Literal[None] = None
    code_mode_call_count: int = Field(default=0, ge=0)
    nested_tool_call_count: int = Field(default=0, ge=0)
    allowed_tool_ids: list[NonEmptyStr] = Field(default_factory=list)
    nested_tool_calls: list[L5NestedToolCallReceipt] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    duration_ms: float = Field(ge=0.0)
    output_sha256: NonEmptyStr
    output_disposition: Literal["candidate_only"] = "candidate_only"
    stop_reason: str | None = None
    sandbox_state_discarded: Literal[True] = True
    boundary: L5ExecutionBoundary = Field(default_factory=L5ExecutionBoundary)
    receipt_sha256: NonEmptyStr


__all__ = [
    "L5ActivationDecision",
    "L5ActivationRequest",
    "L5ActivationState",
    "L5ExecutionBoundary",
    "L5ExecutionReceipt",
    "L5NestedToolCallReceipt",
    "L5RuntimeStatus",
    "L5SafetyLevel",
]
