from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import fcntl
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Callable, Iterator, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


DEFAULT_WORKBENCH_SEED_REF = Path(
    "outputs/contextual_permission/workbench_seed.json"
)
DEFAULT_CONTEXTUAL_PERMISSION_RULES_REF = Path(
    "candidates/contextual_permission_rules.json"
)
CONTEXTUAL_PERMISSION_REDUCER_VERSION = "contextual-permission.reducer.v1"
BASELINE_AUTO_PROPOSAL_VERSION = "reference-gpx-auto-proposal.v1"
_SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_STORE_LOCK = threading.RLock()
REQUIRED_NIGHT_GATE_IDS = (
    "gate.reviewed_alternative",
    "gate.segment_policy",
    "gate.terrain_route",
    "gate.lighting_power",
    "gate.navigation_resources",
    "gate.team",
    "gate.weather_threat",
    "gate.communication",
    "gate.runtime_lineage",
)


class ContextualPermissionConflict(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class WorkbenchModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=True)


class AdjustmentPolicy(StrEnum):
    AUTO_REDUCE = "auto_reduce"
    PROTECTED_FLOOR = "protected_floor"
    REVIEW_ONLY = "review_only"


class CauseSourceKind(StrEnum):
    SAFETY_EMERGENCY_TRIGGER = "safety_emergency_trigger"
    WEATHER_FACT = "weather_fact"
    MOVEMENT_FACT = "movement_fact"
    GNSS_FACT = "gnss_fact"
    HUMAN_OPERATION = "human_operation"


class EmergencyReviewDecision(StrEnum):
    SELECT_HOLD_OR_BIVY = "select_hold_or_bivy"
    REJECT_NIGHT_TRAVEL = "reject_night_travel"
    APPROVE_FOR_RUNTIME_CONSIDERATION = "approve_for_runtime_consideration"
    ESCALATE_EMERGENCY = "escalate_emergency"


class AuthorityBoundary(WorkbenchModel):
    runtime_authorization_performed: bool = False
    phase1_l0_l4_state_mutated: bool = False
    safety_api_called: bool = False
    outbound_action_performed: bool = False
    outbound_transport_invoked: bool = False
    external_send_performed: bool = False
    hardware_control_performed: bool = False


class CanonicalCommandContext(WorkbenchModel):
    session_id: str
    group_id: str
    mission_day_instance_id: str
    membership_revision: int = Field(ge=1)
    expected_baseline_sha256: str
    expected_aggregate_sha256: str
    expected_sequence: int = Field(ge=0)
    idempotency_key: str

    @field_validator("expected_baseline_sha256", "expected_aggregate_sha256")
    @classmethod
    def validate_context_sha256(cls, value: str) -> str:
        if not _SHA256_PATTERN.fullmatch(value):
            raise ValueError("command hashes must be lowercase SHA-256 digests")
        return value

    @field_validator("session_id", "group_id", "mission_day_instance_id", "idempotency_key")
    @classmethod
    def validate_context_id(cls, value: str) -> str:
        if not _SAFE_ID_PATTERN.fullmatch(value):
            raise ValueError("invalid canonical command identifier")
        return value


class CanonicalGroupAggregate(WorkbenchModel):
    session_id: str
    reducer_version: Literal["contextual-permission.reducer.v1"] = (
        CONTEXTUAL_PERMISSION_REDUCER_VERSION
    )
    baseline_candidate_id: str
    baseline_version_id: str
    baseline_schema_version: str
    baseline_sha256: str
    accepted_receipt_ref: str
    contextual_permission_rules_ref: str
    contextual_permission_rules_sha256: str
    binding_sha256: str
    group_id: str
    group_label: str
    membership_revision: int = Field(ge=1)
    membership_sha256: str
    mission_day_id: str
    mission_day_instance_id: str
    mission_day_plan_sha256: str
    review_generation: int = Field(ge=1)
    through_sequence: int = Field(ge=0)
    event_count: int = Field(ge=0)
    aggregate_sha256: str
    server_owned: bool = True
    candidate_only: bool = True
    runtime_safety_truth: bool = False


class CanonicalEvent(WorkbenchModel):
    event_id: str
    event_sha256: str
    command_sha256: str
    event_kind: str
    project_id: str
    session_id: str
    group_id: str
    binding_sha256: str
    sequence: int = Field(ge=1)
    previous_sequence: int = Field(ge=0)
    idempotency_key: str
    recorded_at: datetime
    payload: dict[str, object]
    candidate_projection_updated: bool = True
    authority: AuthorityBoundary = Field(default_factory=AuthorityBoundary)


class BoundedSourceRef(WorkbenchModel):
    source_id: str
    source_kind: str
    source_ref: str
    source_sha256: str
    freshness: Literal["fresh", "stale", "unknown", "not_applicable"]
    candidate_only: bool = True
    runtime_safety_truth: bool = False
    summary: str

    @field_validator("source_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if not _SHA256_PATTERN.fullmatch(value):
            raise ValueError("source_sha256 must be a lowercase SHA-256 digest")
        return value


class CauseEvidence(WorkbenchModel):
    cause_id: str
    source_kind: CauseSourceKind
    source_ref: str
    source_sha256: str
    verified: bool

    @field_validator("source_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if not _SHA256_PATTERN.fullmatch(value):
            raise ValueError("source_sha256 must be a lowercase SHA-256 digest")
        return value


class ScoutActionEvent(WorkbenchModel):
    event_id: str
    sequence: int = Field(ge=0)
    action_id: str
    status: Literal["started", "completed", "cancelled", "overrun"]
    authorized_duration_minutes: int = Field(ge=0)
    observed_duration_minutes: int = Field(ge=0)
    debt_minutes: int = Field(ge=0)
    causes: list[CauseEvidence]
    safety_trigger_locked: bool


class BaselineIdentity(WorkbenchModel):
    baseline_id: str
    revision_id: str
    baseline_sha256: str
    reviewed_receipt_ref: str
    source_mode: Literal["human_text", "reference_gpx"]
    baseline_candidate_id: str | None = None
    baseline_version_id: str | None = None
    baseline_schema_version: str = "missionBaselineCandidate.v1"
    accepted_receipt_id: str | None = None
    parent_version_id: str | None = None
    immutable: bool = True
    accepted_by_human: bool = True
    candidate_only: bool = True
    runtime_safety_truth: bool = False
    departure_approval_granted: bool = False
    contextual_permission_rules_ref: str | None = None
    contextual_permission_rules_sha256: str | None = None
    contextual_permission_rules_reviewed_by_human: bool = True
    source_hashes: dict[str, str] = Field(default_factory=dict)


class RemainingPlanNode(WorkbenchModel):
    node_id: str
    action_id: str
    label: str
    mission_day_id: str
    kind: str
    declared_adjustment_policy: str | None = None
    adjustment_policy: AdjustmentPolicy
    cancellable: bool = False
    priority: int = Field(default=50, ge=0, le=100)
    policy_reason: str
    policy_source: str
    source_refs: list[str]
    baseline_duration_minutes: int = Field(ge=0)
    minimum_duration_minutes: int = Field(ge=0)
    discretionary_excess_minutes: int = Field(default=0, ge=0)
    available_reducible_minutes: int = Field(default=0, ge=0)
    applied_reduction_minutes: int = Field(default=0, ge=0)
    effective_duration_minutes: int = Field(ge=0)
    absorbed_debt_minutes: int = Field(ge=0)
    protected: bool
    adjustment_state: Literal[
        "unchanged", "shortened", "cancelled", "protected", "review_required"
    ]
    source_rule_ref: str
    source_rule_sha256: str
    data_quality: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def fail_closed_unknown_policy(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        declared = normalized.get(
            "declared_adjustment_policy", normalized.get("adjustment_policy")
        )
        normalized["declared_adjustment_policy"] = (
            str(declared) if declared is not None else None
        )
        if declared not in {item.value for item in AdjustmentPolicy}:
            normalized["adjustment_policy"] = AdjustmentPolicy.REVIEW_ONLY.value
            gaps = list(normalized.get("data_quality") or [])
            gaps.append(
                "Missing or unknown reviewed adjustment policy; effective policy is review_only."
            )
            normalized["data_quality"] = gaps
        normalized.setdefault("action_id", str(normalized.get("kind") or "unknown"))
        normalized.setdefault("policy_reason", "Reviewed plan-node policy.")
        normalized.setdefault("policy_source", str(normalized.get("source_rule_ref") or "missing"))
        normalized.setdefault(
            "source_refs", [str(normalized.get("source_rule_ref") or "missing")]
        )
        return normalized

    @model_validator(mode="after")
    def validate_duration_floor(self) -> "RemainingPlanNode":
        if self.effective_duration_minutes < self.minimum_duration_minutes:
            raise ValueError("effective duration cannot cross the reviewed minimum")
        if self.applied_reduction_minutes != self.absorbed_debt_minutes:
            raise ValueError("applied reduction and absorbed debt must match")
        if self.adjustment_policy == AdjustmentPolicy.PROTECTED_FLOOR:
            if not self.protected:
                raise ValueError("protected-floor node must be marked protected")
            maximum = min(
                self.discretionary_excess_minutes,
                self.baseline_duration_minutes - self.minimum_duration_minutes,
            )
            if self.baseline_duration_minutes - self.effective_duration_minutes > maximum:
                raise ValueError(
                    "protected-floor reduction exceeds explicitly discretionary excess"
                )
        if (
            self.adjustment_policy == AdjustmentPolicy.REVIEW_ONLY
            and self.effective_duration_minutes != self.baseline_duration_minutes
        ):
            raise ValueError("review-only duration cannot be changed automatically")
        if (
            not self.cancellable
            and self.baseline_duration_minutes > 0
            and self.effective_duration_minutes == 0
        ):
            raise ValueError("non-cancellable node cannot be reduced to zero")
        return self


class ReviewedPlanNodePolicy(WorkbenchModel):
    node_id: str
    mission_day_id: str
    adjustment_policy: AdjustmentPolicy
    minimum_duration_minutes: int = Field(ge=0)
    policy_ref: str
    policy_sha256: str
    reviewed: bool

    @field_validator("policy_sha256")
    @classmethod
    def validate_policy_sha256(cls, value: str) -> str:
        if not _SHA256_PATTERN.fullmatch(value):
            raise ValueError("policy_sha256 must be a lowercase SHA-256 digest")
        return value


class ContextualPermissionRulesArtifact(WorkbenchModel):
    artifact_kind: Literal["pretrip_contextual_permission_rules"]
    schema_version: str
    project_id: str
    reviewed_baseline_ref: str
    reviewed_baseline_sha256: str
    reviewed_by_human: bool
    review_receipt_ref: str
    review_receipt_sha256: str
    plan_node_policies: list[ReviewedPlanNodePolicy] = Field(min_length=1)
    candidate_only: Literal[True]
    runtime_safety_truth: Literal[False]

    @field_validator("reviewed_baseline_sha256", "review_receipt_sha256")
    @classmethod
    def validate_rules_sha256(cls, value: str) -> str:
        if not _SHA256_PATTERN.fullmatch(value):
            raise ValueError("rules lineage must use lowercase SHA-256 digests")
        return value

    @model_validator(mode="after")
    def validate_review_scope(self) -> "ContextualPermissionRulesArtifact":
        if self.reviewed_by_human:
            if any(not policy.reviewed for policy in self.plan_node_policies):
                raise ValueError("human-reviewed rules require every policy to be reviewed")
            return self
        if any(policy.reviewed for policy in self.plan_node_policies):
            raise ValueError("bootstrap rules cannot mark individual policies reviewed")
        if any(
            policy.adjustment_policy != AdjustmentPolicy.REVIEW_ONLY
            for policy in self.plan_node_policies
        ):
            raise ValueError(
                "unreviewed bootstrap rules must remain fail-closed review_only"
            )
        return self


class ProtectedReserve(WorkbenchModel):
    reserve_id: str
    label: str
    baseline_minutes: int = Field(ge=0)
    effective_minutes: int = Field(ge=0)
    protected: bool = True
    status: Literal["held", "threatened", "unknown"] = "held"


class RiskBudgetLedger(WorkbenchModel):
    time_debt_minutes: int = Field(ge=0)
    absorbed_debt_minutes: int = Field(ge=0)
    unabsorbed_debt_minutes: int = Field(ge=0)
    protected_reserves: list[ProtectedReserve]
    discretionary_minutes_remaining: int = Field(ge=0)
    debt_counted_event_ids: list[str]


class CurrentDecision(WorkbenchModel):
    state: Literal["stored_evaluation", "candidate_simulation"]
    decision: Literal[
        "GO",
        "CONDITIONAL_GO",
        "GUIDED_ONLY",
        "CHANGE_PLAN",
        "DELAY",
        "NO_GO",
        "ESCALATE",
    ]
    action_id: str
    authorized_duration_minutes: int = Field(ge=0)
    observed_duration_minutes: int = Field(ge=0)
    limit_summary: str
    reason: str
    next_step: str
    confidence: Literal["low", "medium", "high"]
    candidate_only: bool = True
    runtime_authority: bool = False


class ScoutPaceAdvice(WorkbenchModel):
    recommendation_id: str
    recommendation: Literal[
        "maintain_reduced_pace",
        "shorten_discretionary_stops",
        "hold_position",
        "open_alternative_review",
        "continue_hold",
        "departure_review_ready",
        "insufficient_evidence",
    ]
    summary: str
    authority: Literal["candidate_advice"] = "candidate_advice"
    safety_subordinate: bool = True
    source_fact_refs: list[str]
    suspended_by_trigger_ref: str | None = None


class FreshnessInput(WorkbenchModel):
    gate_id: str
    evidence_ref: str
    evidence_sha256: str
    valid_until: datetime | None
    refresh_warning_at: datetime | None = None
    required: bool = True

    @field_validator("evidence_sha256")
    @classmethod
    def validate_evidence_sha256(cls, value: str) -> str:
        if not _SHA256_PATTERN.fullmatch(value):
            raise ValueError("freshness evidence hash must be a lowercase SHA-256 digest")
        return value


class ExpiryDriver(WorkbenchModel):
    gate_id: str
    evidence_ref: str
    valid_until: datetime
    reason: str


class EligibilityGate(WorkbenchModel):
    gate_id: str
    label: str
    state: Literal["pass", "blocked", "missing", "unknown"]
    hard_gate: bool
    reason: str
    source_ref: str
    source_sha256: str


class ReviewedTargetRef(WorkbenchModel):
    target_ref: str
    target_sha256: str
    target_label: str

    @field_validator("target_sha256")
    @classmethod
    def validate_target_sha256(cls, value: str) -> str:
        if not _SHA256_PATTERN.fullmatch(value):
            raise ValueError("reviewed target hash must be a lowercase SHA-256 digest")
        return value


class NightAlternativePacket(WorkbenchModel):
    packet_id: str
    sha256: str
    project_id: str
    session_id: str
    mission_day_id: str
    mission_day_instance_id: str
    movement_group_id: str = "group.ridge"
    membership_revision: int = Field(default=1, ge=1)
    membership_sha256: str | None = None
    review_generation: int = Field(ge=1)
    reviewed_sequence: int = Field(ge=0)
    alternative_id: str
    alternative_label: str
    from_target_ref: str
    from_target_sha256: str
    from_target_label: str
    to_target_ref: str
    to_target_sha256: str
    to_target_label: str
    direction: str
    maximum_night_duration_minutes: int = Field(gt=0)
    stop_objective: str
    retreat_candidate_refs: list[str] = Field(min_length=1)
    emergency_bivy_candidate_refs: list[str] = Field(min_length=1)
    retreat_candidates: list[ReviewedTargetRef] = Field(min_length=1)
    emergency_bivy_candidates: list[ReviewedTargetRef] = Field(min_length=1)
    requires_daylight: bool | None
    reviewed_envelope_sha256: str
    eligibility: Literal[
        "not_assessed", "ineligible", "eligible_for_human_review"
    ]
    approval_granted: bool = False
    safety_state: str
    server_now: datetime
    built_at: datetime
    expires_at: datetime | None
    freshness_state: Literal[
        "fresh",
        "expiring",
        "refresh_due",
        "expired",
        "freshness_unknown",
        "invalidated",
    ]
    expiry_driver: ExpiryDriver | None
    freshness_inputs: list[FreshnessInput]
    invalidated_by: list[str] = Field(default_factory=list)
    gates: list[EligibilityGate]
    source_refs: list[str]
    aggregate: CanonicalGroupAggregate | None = None
    candidate_only: bool = True
    runtime_safety_truth: bool = False


class EmergencyReviewReceipt(WorkbenchModel):
    receipt_id: str
    receipt_sha256: str
    request_sha256: str
    project_id: str
    session_id: str
    mission_day_id: str
    mission_day_instance_id: str
    movement_group_id: str = "group.ridge"
    membership_revision: int = Field(default=1, ge=1)
    review_generation: int
    reviewed_sequence: int
    packet_id: str
    packet_sha256: str
    reviewed_envelope_sha256: str
    decision: EmergencyReviewDecision
    reviewer_alias: str
    idempotency_key: str
    event_sequence: int = Field(default=0, ge=0)
    binding_sha256: str = "0" * 64
    aggregate_sha256_before: str = "0" * 64
    recorded_at: datetime
    human_review_recorded: bool = True
    candidate_projection_updated: bool = True
    production_approval_granted: bool = False
    real_world_effect_performed: bool = False
    runtime_authorization_performed: bool = False
    phase1_l0_l4_state_mutated: bool = False
    safety_api_called: bool = False
    outbound_action_performed: bool = False
    outbound_transport_invoked: bool = False
    external_send_performed: bool = False


class DailyEmergencyReviewSession(WorkbenchModel):
    session_id: str
    project_id: str
    mission_day_id: str
    mission_day_instance_id: str
    movement_group_id: str = "group.ridge"
    membership_revision: int = Field(default=1, ge=1)
    mission_day_plan_ref: str
    mission_day_plan_sha256: str
    review_generation: int = Field(ge=1)
    state: Literal[
        "pending_day_start",
        "not_started",
        "in_review",
        "partially_reviewed",
        "reviewed",
        "reviewed_evidence_refresh_required",
        "re_review_required",
        "day_closed",
    ]
    planned_day_end_target_ref: str
    planned_day_end_target_sha256: str
    planned_day_end_target_label: str
    effective_day_end_target_ref: str
    effective_day_end_target_sha256: str
    day_end_state: str
    alternatives: list[NightAlternativePacket]
    receipts: list[EmergencyReviewReceipt] = Field(default_factory=list)
    aggregate: CanonicalGroupAggregate | None = None
    current_day_only: bool = True
    future_day_preview: bool = False


class DailyReviewSummary(WorkbenchModel):
    mission_day_id: str
    mission_day_instance_id: str
    state: str
    reviewed_count: int = Field(ge=0)
    alternative_count: int = Field(ge=0)
    selected_alternative_state: str
    review_generation: int
    handoff_route: str = "emergency"
    permission_page_can_decide: bool = False


class ShelterHoldProjection(WorkbenchModel):
    hold_id: str | None
    state: Literal[
        "not_required",
        "hold_review_required",
        "active",
        "evidence_refresh_required",
        "departure_review_candidate",
        "ready_to_resume",
        "closed",
        "escalated",
    ]
    target_label: str | None
    location_target_ref: str | None = None
    location_target_sha256: str | None = None
    location_kind: Literal[
        "planned_day_end", "emergency_bivy", "reviewed_safe_shelter"
    ] | None = None
    closed_mission_day_instance_id: str | None = None
    pending_next_mission_day_id: str | None = None
    calendar_days_elapsed: int = Field(ge=0)
    mission_days_consumed: int = Field(ge=0)
    automatic_cause_refs: list[str] = Field(default_factory=list)
    human_trigger_refs: list[str] = Field(default_factory=list)
    weather_and_threat_evidence_refs: list[str] = Field(default_factory=list)
    team_and_resource_state_refs: list[str] = Field(default_factory=list)
    started_at: datetime | None = None
    last_reviewed_at: datetime | None = None
    next_step: str


class DayEndProjection(WorkbenchModel):
    planned_target_label: str
    effective_target_label: str
    planned_target_ref: str = "target://unresolved"
    planned_target_sha256: str = "0" * 64
    effective_target_ref: str = "target://unresolved"
    effective_target_sha256: str = "0" * 64
    feasibility: Literal["reachable", "at_risk", "unreachable", "unknown"]
    state: Literal[
        "en_route_to_planned_day_end",
        "planned_day_end_arrival_unconfirmed",
        "planned_day_end_reached",
        "day_end_at_risk",
        "day_end_unreachable",
        "emergency_bivy_review_required",
        "emergency_bivy_selected",
        "emergency_bivy_establishment_unconfirmed",
        "emergency_bivy_established",
        "day_closed_planned",
        "day_closed_contingency",
    ]
    completion: Literal["open", "planned_closed", "contingency_closed"]
    baseline_day_end_reached: bool
    close_receipt_ref: str | None
    correction_receipt_ref: str | None = None
    confirmation_mode: Literal[
        "none", "manual_on_site", "automatic_gnss_dwell"
    ] = "none"
    clock_can_close_day: bool = False


class DepartureChecklistRow(WorkbenchModel):
    row_id: Literal[
        "weather_threats",
        "route_navigation",
        "team",
        "equipment_power",
        "supplies_shelter",
        "communication_plan",
    ]
    label: str
    source_mode: Literal["scout_auto", "leader_attestation", "hybrid"]
    state: Literal["pass", "blocked", "unknown", "leader_check_required"]
    evidence_summary: str
    evidence_ref: str | None
    evidence_sha256: str | None = None
    freshness: Literal["fresh", "stale", "unknown", "not_applicable"]
    field_condition_differs_available: bool
    blocker: str | None = None

    @field_validator("evidence_sha256")
    @classmethod
    def validate_optional_evidence_sha256(cls, value: str | None) -> str | None:
        if value is not None and not _SHA256_PATTERN.fullmatch(value):
            raise ValueError("checklist evidence hash must be a lowercase SHA-256 digest")
        return value


class DepartureChecklistProjection(WorkbenchModel):
    checklist_id: str
    checklist_sha256: str = "0" * 64
    pending_day_plan_sha256: str = "0" * 64
    rows: list[DepartureChecklistRow]
    open_conflict_count: int = Field(ge=0)
    scout_suggestion_code: Literal[
        "continue_shelter_hold",
        "refresh_evidence",
        "departure_review_ready",
        "relocate_or_escalate_review",
    ]
    scout_suggestion: str
    scout_suggestion_suspended: bool
    can_confirm_departure: bool
    final_confirmation_required: bool = True
    mission_day_started: bool = False

    @model_validator(mode="after")
    def validate_six_rows(self) -> "DepartureChecklistProjection":
        expected = {
            "weather_threats",
            "route_navigation",
            "team",
            "equipment_power",
            "supplies_shelter",
            "communication_plan",
        }
        actual = {row.row_id for row in self.rows}
        if len(self.rows) != 6 or actual != expected:
            raise ValueError("departure checklist must contain exactly six canonical rows")
        if self.can_confirm_departure and any(row.state != "pass" for row in self.rows):
            raise ValueError("departure cannot be confirmed while a row is not pass")
        return self


class ActivitySummary(WorkbenchModel):
    states: dict[str, int]
    fresh_count: int = Field(ge=0)
    stale_count: int = Field(ge=0)
    contradiction_count: int = Field(ge=0)
    leader_sleep_roll_call_required: bool = False
    team_safe_claimed: bool = False
    raw_sensor_data_exposed: bool = False


class ArrivalDwellProjection(WorkbenchModel):
    state: Literal["idle", "counting", "complete", "blocked", "pending_sync"]
    required_seconds: int = 600
    elapsed_seconds: int = Field(ge=0)
    dwell_remaining_seconds: int = Field(ge=0)
    target_ref: str
    target_sha256: str
    arrival_zone_ref: str
    arrival_zone_sha256: str
    route_progress_ref: str
    route_progress_sha256: str
    dwell_policy_ref: str
    dwell_policy_sha256: str
    individual_activity_summary_ref: str
    individual_activity_summary_sha256: str
    target_match: bool
    gnss_confidence: Literal["high", "medium", "low", "unknown"]
    manual_complete_available: bool
    blocked_by: list[str] = Field(default_factory=list)
    blocking_contradictions: list[str] = Field(default_factory=list)
    day_close_receipt_ref: str | None = None
    day_close_receipt_sha256: str | None = None

    @model_validator(mode="after")
    def validate_dwell_countdown(self) -> "ArrivalDwellProjection":
        expected = max(0, self.required_seconds - self.elapsed_seconds)
        if self.dwell_remaining_seconds != expected:
            raise ValueError("dwell_remaining_seconds must match the monotonic dwell")
        return self


class CommunicationProjection(WorkbenchModel):
    policy_id: str
    policy_sha256: str
    state: Literal[
        "contact_available",
        "expected_blackout",
        "check_in_window_open",
        "check_in_due",
        "contact_overdue",
        "contact_loss_review_required",
        "escalation_candidate",
        "contact_restored",
        "unknown",
    ]
    membership_revision: int = Field(ge=1)
    route_scope_ref: str
    route_scope_sha256: str
    route_scope_label: str
    viewpoint: Literal["local", "remote", "synchronized"]
    next_check_in_target: str
    baseline_window: str
    effective_window: str
    deadline_driver: str
    next_check_in_target_ref: str
    next_check_in_target_sha256: str
    adjustment_receipt_ref: str | None = None
    adjustment_receipt_sha256: str | None = None
    last_verified_receipt_ref: str | None
    last_verified_receipt_sha256: str | None = None
    local_group_contact_state: str
    remote_observed_contact_state: str
    automatic_contradictions: list[str] = Field(default_factory=list)
    contact_loss_review_receipt_ref: str | None = None
    contact_loss_review_receipt_sha256: str | None = None
    scout_recommendation: Literal[
        "monitor_reviewed_window",
        "check_in_when_available",
        "coordinate_rendezvous_review",
        "open_emergency_call_out_review",
    ] = "monitor_reviewed_window"
    contact_overdue: bool
    emergency_declared: bool
    continuous_heartbeat_required: bool = False
    transport_attempt_counts_as_check_in: bool = False


class MovementGroupProjection(WorkbenchModel):
    group_id: str
    group_label: str
    formation_kind: Literal["baseline_reviewed", "field_explicit"]
    membership_revision: int = Field(ge=1)
    membership_sha256: str
    participant_refs_hash: str
    coordinator_ref: str
    shared_dependency_refs: list[str] = Field(default_factory=list)
    shared_dependency_hashes: list[str] = Field(default_factory=list)
    formation_receipt_ref: str
    formation_receipt_sha256: str
    status: Literal[
        "not_started",
        "in_progress",
        "day_closed",
        "shelter_hold",
        "pending_day_start",
        "cross_group_review_required",
        "unexpected_separation",
    ]
    mission_day_id: str
    mission_day_instance_id: str
    day_end: DayEndProjection
    shelter_hold: ShelterHoldProjection
    pending_next_day: str | None
    departure_checklist: DepartureChecklistProjection
    activity_summary: ActivitySummary
    arrival_dwell: ArrivalDwellProjection
    communication: CommunicationProjection
    unexpected_separation: bool
    independent_day_state: bool = True


class ExpeditionRollup(WorkbenchModel):
    state: Literal["all_open", "partially_closed", "all_closed", "reconciliation_required"]
    group_count: int = Field(ge=1)
    open_group_count: int = Field(ge=0)
    closed_group_count: int = Field(ge=0)
    read_only: bool = True
    can_close_or_start_group: bool = False


class ContextualPermissionWorkbenchSeed(WorkbenchModel):
    artifact_kind: Literal["contextual_permission_workbench_seed"]
    schema_version: Literal["contextualPermissionWorkbenchSeed.v1"]
    project_id: str
    lens: Literal["baseline", "replay", "live_observer"]
    replay_session_id: str
    baseline: BaselineIdentity
    action_events: list[ScoutActionEvent]
    remaining_plan: list[RemainingPlanNode]
    daily_review: DailyEmergencyReviewSession
    movement_groups: list[MovementGroupProjection]
    evidence: list[BoundedSourceRef]


class ContextualPermissionProjection(WorkbenchModel):
    artifact_kind: Literal["contextual_permission_dashboard_projection"]
    schema_version: Literal["contextualPermissionDashboard.v1"]
    project_id: str
    projection_sha256: str
    server_now: datetime
    status: Literal["ready", "degraded", "blocked"]
    lens: Literal["baseline", "replay", "live_observer"]
    available_lenses: list[Literal["baseline", "replay", "live_observer"]]
    lens_notice: str
    inspection_state: Literal[
        "INSPECTING_STORED",
        "DIRTY_NOT_EVALUATED",
        "SIMULATING",
        "SIMULATION_READY",
        "SIMULATION_FAILED",
    ]
    baseline: BaselineIdentity
    current_decision: CurrentDecision
    remaining_plan: list[RemainingPlanNode]
    risk_budget: RiskBudgetLedger
    action_events: list[ScoutActionEvent]
    scout_pace_advice: ScoutPaceAdvice
    daily_review: DailyReviewSummary
    movement_groups: list[MovementGroupProjection]
    expedition_rollup: ExpeditionRollup
    evidence: list[BoundedSourceRef]
    missing_inputs: list[str]
    conflicting_inputs: list[str]
    day_boundary_policy: Literal["destination_receipt_only"]
    primary_aggregate: CanonicalGroupAggregate
    group_aggregates: list[CanonicalGroupAggregate]
    candidate_only: bool = True
    runtime_safety_truth: bool = False
    authority: AuthorityBoundary = Field(default_factory=AuthorityBoundary)


class CauseInput(WorkbenchModel):
    cause_id: str
    source_kind: CauseSourceKind
    source_ref: str
    source_sha256: str
    verified: bool


class CandidateSimulationRequest(WorkbenchModel):
    action_id: str
    authorized_duration_minutes: int = Field(ge=0, le=1440)
    observed_duration_minutes: int = Field(ge=0, le=2880)
    causes: list[CauseInput] = Field(min_length=1, max_length=8)


class CandidateSimulationResult(WorkbenchModel):
    artifact_kind: Literal["contextual_permission_candidate_simulation"]
    schema_version: Literal["contextualPermissionSimulation.v1"]
    scenario_sha256: str
    projection: ContextualPermissionProjection
    writes_performed: bool = False
    replaces_current_decision: bool = False
    candidate_only: bool = True
    runtime_safety_truth: bool = False
    authority: AuthorityBoundary = Field(default_factory=AuthorityBoundary)


class EmergencyReviewDecisionRequest(WorkbenchModel):
    command_context: CanonicalCommandContext | None = None
    packet_id: str
    packet_sha256: str
    mission_day_instance_id: str
    review_generation: int = Field(ge=1)
    reviewed_sequence: int = Field(ge=0)
    decision: EmergencyReviewDecision
    reviewer_alias: str = Field(min_length=1, max_length=80)
    idempotency_key: str | None = None
    explicit_confirmation: bool

    @field_validator("idempotency_key")
    @classmethod
    def validate_idempotency_key(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not _SAFE_ID_PATTERN.fullmatch(value):
            raise ValueError("invalid idempotency key")
        return value

    @model_validator(mode="after")
    def normalize_idempotency_contract(self) -> "EmergencyReviewDecisionRequest":
        if self.command_context is None and self.idempotency_key is None:
            raise ValueError("command_context or idempotency_key is required")
        if (
            self.command_context is not None
            and self.idempotency_key is not None
            and self.idempotency_key != self.command_context.idempotency_key
        ):
            raise ValueError("idempotency key conflicts with command_context")
        return self


class DailyReviewInvalidationRequest(WorkbenchModel):
    command_context: CanonicalCommandContext
    reason_kind: Literal[
        "new_alternative",
        "route_or_direction_changed",
        "reviewed_policy_changed",
        "safety_emergency_trigger",
        "team_condition_outside_envelope",
        "lineage_mismatch",
    ]
    source_refs: list[str] = Field(min_length=1, max_length=12)
    source_hashes: list[str] = Field(min_length=1, max_length=12)
    reviewed_envelope_crossed: bool
    reporter_alias: str | None = Field(default=None, max_length=80)
    explicit_confirmation: bool = False


class OfflineEmergencyReviewIntent(WorkbenchModel):
    intent_id: str
    idempotency_key: str
    packet_id: str
    packet_sha256: str
    mission_day_instance_id: str
    review_generation: int = Field(ge=1)
    reviewed_sequence: int = Field(ge=0)
    decision: EmergencyReviewDecision
    reviewer_alias: str = Field(min_length=1, max_length=80)
    device_instance_id: str
    pending_sync: Literal[True]
    device_local_encrypted: Literal[True] = True
    supersedes_intent_id: str | None = None
    candidate_only: Literal[True] = True
    production_approval_granted: Literal[False] = False
    runtime_authorization_performed: Literal[False] = False
    phase1_l0_l4_state_mutated: Literal[False] = False
    safety_api_called: Literal[False] = False
    outbound_action_performed: Literal[False] = False
    outbound_transport_invoked: Literal[False] = False
    external_send_performed: Literal[False] = False
    hardware_control_performed: Literal[False] = False

    @field_validator("idempotency_key", "intent_id", "device_instance_id")
    @classmethod
    def validate_safe_id(cls, value: str) -> str:
        if not _SAFE_ID_PATTERN.fullmatch(value):
            raise ValueError("invalid offline intent identifier")
        return value


class OfflineIntentSyncResult(WorkbenchModel):
    status: Literal["receipt_appended", "already_recorded", "rejected_sync_audit"]
    receipt_ref: str | None
    receipt_sha256: str | None
    audit_ref: str | None
    reasons: list[str]
    runtime_authorization_performed: bool = False
    phase1_l0_l4_state_mutated: bool = False
    safety_api_called: bool = False
    outbound_action_performed: bool = False
    outbound_transport_invoked: bool = False
    external_send_performed: bool = False
    hardware_control_performed: bool = False


class BaselineAuthoringRequest(WorkbenchModel):
    mode: Literal["human_text", "reference_gpx"]
    human_text: str | None = Field(default=None, max_length=20_000)
    reference_route_ref: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_mode_inputs(self) -> "BaselineAuthoringRequest":
        if self.mode == "human_text" and not (self.human_text or "").strip():
            raise ValueError("human_text is required for human_text mode")
        if self.mode == "reference_gpx" and not (self.reference_route_ref or "").strip():
            raise ValueError("reference_route_ref is required for reference_gpx mode")
        return self


class BaselineArtifactBinding(WorkbenchModel):
    ref: str
    sha256: str

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if not _SHA256_PATTERN.fullmatch(value):
            raise ValueError("artifact binding requires a lowercase SHA-256 digest")
        return value


class BaselineRouteAnchor(WorkbenchModel):
    anchor_id: str
    display_label: str
    artifact: BaselineArtifactBinding
    route_order_m: float = Field(ge=0)


class BaselineEtaProposal(WorkbenchModel):
    state: Literal["complete_derived", "partial_derived", "unknown"]
    method: Literal[
        "sum_segment_quantiles",
        "sum_supported_segment_quantiles",
        "no_numeric_eta",
    ]
    method_version: Literal["1"] = "1"
    confidence: Literal["medium", "low", "unknown"]
    segment_p50_sum_minutes: float | None = Field(default=None, ge=0)
    segment_p75_sum_minutes: float | None = Field(default=None, ge=0)
    supported_segment_p50_sum_minutes: float | None = Field(default=None, ge=0)
    supported_segment_p75_sum_minutes: float | None = Field(default=None, ge=0)
    supporting_segment_ids: list[str] = Field(default_factory=list)
    unsupported_segment_ids: list[str] = Field(default_factory=list)
    gap_ids: list[str] = Field(default_factory=list)
    reason: Literal[
        "no_usable_segment_p75",
        "timing_evidence_absent",
        "segment_mapping_unavailable",
    ] | None = None

    @model_validator(mode="after")
    def validate_eta_state(self) -> "BaselineEtaProposal":
        if set(self.supporting_segment_ids).intersection(self.unsupported_segment_ids):
            raise ValueError("supported and unsupported timing segments must be disjoint")
        if self.state == "complete_derived":
            if (
                self.method != "sum_segment_quantiles"
                or self.confidence != "medium"
                or not self.supporting_segment_ids
                or self.unsupported_segment_ids
                or self.segment_p75_sum_minutes is None
                or self.supported_segment_p50_sum_minutes is not None
                or self.supported_segment_p75_sum_minutes is not None
                or self.reason is not None
            ):
                raise ValueError("invalid complete-derived ETA shape")
            if (
                self.segment_p50_sum_minutes is not None
                and self.segment_p50_sum_minutes > self.segment_p75_sum_minutes
            ):
                raise ValueError("complete p50 sum cannot exceed p75 sum")
            return self
        if self.state == "partial_derived":
            if (
                self.method != "sum_supported_segment_quantiles"
                or self.confidence != "low"
                or not self.supporting_segment_ids
                or not self.unsupported_segment_ids
                or not self.gap_ids
                or self.supported_segment_p75_sum_minutes is None
                or self.segment_p50_sum_minutes is not None
                or self.segment_p75_sum_minutes is not None
                or self.reason is not None
            ):
                raise ValueError("invalid partial-derived ETA shape")
            if (
                self.supported_segment_p50_sum_minutes is not None
                and self.supported_segment_p50_sum_minutes
                > self.supported_segment_p75_sum_minutes
            ):
                raise ValueError("supported p50 subtotal cannot exceed p75 subtotal")
            return self
        numeric_values = (
            self.segment_p50_sum_minutes,
            self.segment_p75_sum_minutes,
            self.supported_segment_p50_sum_minutes,
            self.supported_segment_p75_sum_minutes,
        )
        if (
            self.method != "no_numeric_eta"
            or self.confidence != "unknown"
            or any(value is not None for value in numeric_values)
            or self.supporting_segment_ids
            or not self.unsupported_segment_ids
            or not self.gap_ids
            or self.reason is None
        ):
            raise ValueError("invalid unknown ETA shape")
        return self


class BaselineTargetProposal(WorkbenchModel):
    proposal_id: str
    kind: Literal["day_end", "retreat", "emergency_bivy"]
    mission_day_id: str
    target: BaselineRouteAnchor
    confidence: Literal["high", "medium", "low", "unknown"]
    rationale: str
    evidence: list[BaselineArtifactBinding] = Field(min_length=1)
    required_review_surface: Literal["permission", "safety_emergency"]
    candidate_only: bool = True
    runtime_safety_truth: bool = False
    departure_approval_granted: bool = False

    @model_validator(mode="after")
    def validate_review_surface(self) -> "BaselineTargetProposal":
        required = "permission" if self.kind == "day_end" else "safety_emergency"
        if self.required_review_surface != required:
            raise ValueError("target kind is routed to the wrong review surface")
        return self


class BaselineUncertainty(WorkbenchModel):
    uncertainty_id: str
    code: Literal[
        "missing_historical_p75",
        "destination_ambiguity",
        "external_safety_review",
        "insufficient_evidence",
        "strategy_target_exceeded",
    ]
    affected_day_ids: list[str] = Field(default_factory=list)
    affected_segment_ids: list[str] = Field(default_factory=list)
    related_target_proposal_ids: list[str] = Field(default_factory=list)
    summary: str
    disposition: Literal["acknowledgeable", "blocking", "external_review_pending"]
    required_review_surface: Literal["permission", "safety_emergency"]
    evidence: list[BaselineArtifactBinding] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_uncertainty(self) -> "BaselineUncertainty":
        if not (
            self.affected_day_ids
            or self.affected_segment_ids
            or self.related_target_proposal_ids
        ):
            raise ValueError("uncertainty must identify an affected object")
        valid_pair = (
            self.disposition == "acknowledgeable"
            and self.required_review_surface == "permission"
        ) or (
            self.disposition == "blocking"
            and self.required_review_surface == "permission"
        ) or (
            self.disposition == "external_review_pending"
            and self.required_review_surface == "safety_emergency"
        )
        if not valid_pair:
            raise ValueError("invalid uncertainty disposition and review surface")
        return self


class BaselineReviewRequirements(WorkbenchModel):
    contract_version: Literal["baseline_permission_review.v1"] = (
        "baseline_permission_review.v1"
    )
    required_reviewed_day_ids: list[str] = Field(default_factory=list)
    required_acknowledgment_uncertainty_ids: list[str] = Field(default_factory=list)
    pending_safety_handoff_item_ids: list[str] = Field(default_factory=list)
    safety_handoff_required: bool

    @model_validator(mode="after")
    def validate_handoff_requirement(self) -> "BaselineReviewRequirements":
        if self.safety_handoff_required != bool(self.pending_safety_handoff_item_ids):
            raise ValueError("Safety handoff requirement must match pending item IDs")
        return self


class BaselineProposalSummary(WorkbenchModel):
    day_count: int = Field(ge=0)
    route_length_m: float = Field(ge=0)
    timing_segment_count: int = Field(ge=0)
    observed_p75_segment_count: int = Field(ge=0)
    missing_p75_segment_count: int = Field(ge=0)
    permission_uncertainty_count: int = Field(ge=0)
    safety_pending_count: int = Field(ge=0)
    blocking_gap_count: int = Field(ge=0)
    target_p75_minutes_per_day: int = Field(ge=1)
    source_route_days_metadata: int | None = Field(default=None, ge=0)
    source_route_days_planning_authority: bool = False


class BaselineDayDraft(WorkbenchModel):
    mission_day_id: str
    source_text: str
    day_kind: Literal["logistics", "on_trail"] = "on_trail"
    ordered_place_mentions: list[str] = Field(default_factory=list)
    resolved_targets: list[str]
    resolved_target_refs: dict[str, str] = Field(default_factory=dict)
    resolved_target_hashes: dict[str, str] = Field(default_factory=dict)
    unresolved_names: list[str]
    operator_aliases: list[str] = Field(default_factory=list)
    coordinate_hints: list[dict[str, object]] = Field(default_factory=list)
    branch_candidates: list[dict[str, object]] = Field(default_factory=list)
    start_anchor: BaselineRouteAnchor | None = None
    primary_day_end_proposal: BaselineTargetProposal | None = None
    eta_proposal: BaselineEtaProposal | None = None
    segment_ids: list[str] = Field(default_factory=list)
    retreat_candidates: list[BaselineTargetProposal] = Field(default_factory=list)
    emergency_bivy_candidates: list[BaselineTargetProposal] = Field(
        default_factory=list
    )
    uncertainty_ids: list[str] = Field(default_factory=list)
    review_summary: str | None = None


class MissionBaselineDraft(WorkbenchModel):
    artifact_kind: Literal["mission_baseline_candidate"]
    schema_version: Literal["missionBaselineCandidate.v1"]
    draft_id: str
    source_mode: Literal["human_text", "reference_gpx"]
    source_sha256: str
    source_text: str
    source_refs: list[str] = Field(default_factory=list)
    source_hashes: dict[str, str] = Field(default_factory=dict)
    route_axis_validation: dict[str, Literal["pass", "blocked", "unknown"]] = Field(
        default_factory=dict
    )
    days: list[BaselineDayDraft]
    assumptions: list[str] = Field(default_factory=list)
    conversation_refs: list[str] = Field(default_factory=list)
    base_candidate_ref: str | None = None
    base_candidate_sha256: str | None = None
    patch_sha256: str | None = None
    validation_state: Literal["valid", "needs_review", "blocked"]
    unresolved_gaps: list[str]
    proposal_profile: Literal["legacy_sparse", "ref_gpx_proposal_v1"] = (
        "legacy_sparse"
    )
    proposal_strategy_id: str | None = None
    proposal_strategy_version: str | None = None
    timing_evidence: BaselineArtifactBinding | None = None
    proposal_summary: BaselineProposalSummary | None = None
    uncertainties: list[BaselineUncertainty] = Field(default_factory=list)
    review_requirements: BaselineReviewRequirements | None = None
    safety_handoff_summary: str | None = None
    writes_performed: bool = False
    candidate_only: bool = True
    runtime_safety_truth: bool = False
    departure_approval_granted: bool = False


class BaselineCandidateSaveRequest(WorkbenchModel):
    draft: MissionBaselineDraft
    expected_source_sha256: str
    idempotency_key: str
    explicit_confirmation: bool


class BaselineCandidateSaveReceipt(WorkbenchModel):
    baseline_id: str
    version_id: str
    version_ref: str
    version_sha256: str
    source_sha256: str
    idempotency_key: str
    parent_version_id: str | None = None
    validation_state: Literal["valid", "needs_review", "blocked"]
    unresolved_gaps: list[str]
    review_ready: bool
    writes_performed: bool = True
    candidate_only: bool = True
    runtime_safety_truth: bool = False
    departure_approval_granted: bool = False


class BaselinePatchOperation(WorkbenchModel):
    operation: Literal[
        "add_target",
        "remove_target",
        "reorder_target",
        "resolve_target",
        "confirm_coordinate_crs",
        "review_branch",
        "confirm_route_axis",
        "bind_reviewed_graph",
        "add_assumption",
    ]
    mission_day_id: str | None = None
    target_label: str | None = None
    target_ref: str | None = None
    target_sha256: str | None = None
    from_index: int | None = Field(default=None, ge=0)
    to_index: int | None = Field(default=None, ge=0)
    coordinate_text: str | None = None
    confirmed_crs: str | None = None
    assumption: str | None = Field(default=None, max_length=500)


class BaselinePatchPreviewRequest(WorkbenchModel):
    base_candidate_ref: str
    base_candidate_sha256: str
    operations: list[BaselinePatchOperation] = Field(min_length=1, max_length=100)
    conversation_refs: list[str] = Field(default_factory=list, max_length=20)
    conversation_hashes: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_conversation_lineage(self) -> "BaselinePatchPreviewRequest":
        if len(self.conversation_refs) != len(self.conversation_hashes):
            raise ValueError("conversation refs and hashes must have equal length")
        if any(
            not _SHA256_PATTERN.fullmatch(item)
            for item in self.conversation_hashes
        ):
            raise ValueError("conversation hashes must be lowercase SHA-256 digests")
        return self


class BaselinePatchPreviewResult(WorkbenchModel):
    artifact_kind: Literal["mission_baseline_patch_preview"]
    schema_version: Literal["missionBaselinePatchPreview.v1"]
    base_candidate_ref: str
    base_candidate_sha256: str
    patch_sha256: str
    operations: list[BaselinePatchOperation]
    conversation_refs: list[str]
    conversation_hashes: list[str]
    additions: list[str]
    removals: list[str]
    reordered: list[str]
    new_assumptions: list[str]
    unresolved_items: list[str]
    draft: MissionBaselineDraft
    writes_performed: bool = False
    candidate_only: bool = True
    runtime_safety_truth: bool = False


class BaselinePatchSaveRequest(WorkbenchModel):
    patch: BaselinePatchPreviewResult
    expected_base_candidate_sha256: str
    idempotency_key: str
    explicit_confirmation: bool


class BaselineReviewAcceptRequest(WorkbenchModel):
    candidate_ref: str
    candidate_sha256: str
    reviewer_alias: str = Field(min_length=1, max_length=80)
    idempotency_key: str
    explicit_confirmation: bool
    reviewed_day_ids: list[str] = Field(default_factory=list)
    acknowledged_uncertainty_ids: list[str] = Field(default_factory=list)
    safety_handoff_acknowledged: bool = False

    @field_validator("reviewed_day_ids", "acknowledged_uncertainty_ids")
    @classmethod
    def normalize_review_ids(cls, value: list[str]) -> list[str]:
        if any(not _SAFE_ID_PATTERN.fullmatch(item) for item in value):
            raise ValueError("review identifiers must be safe stable IDs")
        if len(value) != len(set(value)):
            raise ValueError("review identifiers cannot contain duplicates")
        return value


class BaselineReviewAcceptReceipt(WorkbenchModel):
    review_id: str
    review_ref: str
    review_sha256: str
    reviewed_baseline_ref: str
    reviewed_baseline_sha256: str
    candidate_ref: str
    candidate_sha256: str
    stale_dependency_refs: list[str]
    reviewed_day_ids: list[str] = Field(default_factory=list)
    acknowledged_uncertainty_ids: list[str] = Field(default_factory=list)
    safety_handoff_acknowledged: bool = False
    writes_performed: bool = True
    candidate_only: bool = True
    runtime_safety_truth: bool = False
    departure_approval_granted: bool = False
    final_mission_graph_generated: bool = False
    active_runtime_session_updated: bool = False
    safety_api_called: bool = False
    outbound_action_performed: bool = False
    outbound_transport_invoked: bool = False
    external_send_performed: bool = False
    hardware_control_performed: bool = False


class ContextualPermissionProjectionRebuildRequest(WorkbenchModel):
    expected_reviewed_baseline_sha256: str
    idempotency_key: str
    explicit_confirmation: bool

    @field_validator("expected_reviewed_baseline_sha256")
    @classmethod
    def validate_expected_baseline_sha256(cls, value: str) -> str:
        if not _SHA256_PATTERN.fullmatch(value):
            raise ValueError("expected reviewed baseline must be a lowercase SHA-256 digest")
        return value

    @field_validator("idempotency_key")
    @classmethod
    def validate_rebuild_idempotency_key(cls, value: str) -> str:
        if not _SAFE_ID_PATTERN.fullmatch(value):
            raise ValueError("invalid Contextual Permission rebuild idempotency key")
        return value


class ContextualPermissionProjectionRebuildReceipt(WorkbenchModel):
    rebuild_id: str
    rebuild_ref: str
    rebuild_sha256: str
    request_sha256: str
    idempotency_key: str
    reviewed_baseline_ref: str
    reviewed_baseline_sha256: str
    planned_eta_ref: str
    planned_eta_sha256: str
    contextual_permission_rules_ref: str
    contextual_permission_rules_sha256: str
    workbench_seed_ref: str
    workbench_seed_sha256: str
    rule_review_state: Literal["pending_review_only"]
    writes_performed: bool = True
    candidate_only: bool = True
    runtime_safety_truth: bool = False
    departure_approval_granted: bool = False
    active_runtime_session_updated: bool = False
    safety_api_called: bool = False
    outbound_action_performed: bool = False
    outbound_transport_invoked: bool = False
    external_send_performed: bool = False
    hardware_control_performed: bool = False


class ArrivalDwellObservationRequest(WorkbenchModel):
    command_context: CanonicalCommandContext
    target_ref: str
    target_sha256: str
    elapsed_seconds: int = Field(ge=0, le=86_400)
    target_match: bool
    route_progress_match: bool
    gnss_confidence: Literal["high", "medium", "low", "unknown"]
    zone_exit: bool
    continued_route_travel: bool
    unexpected_separation: bool


class FieldConflictRequest(WorkbenchModel):
    command_context: CanonicalCommandContext
    checklist_id: str
    row_id: Literal[
        "weather_threats",
        "route_navigation",
        "equipment_power",
        "supplies_shelter",
        "communication_plan",
    ]
    category: Literal[
        "actual_condition_worse",
        "source_stale_or_wrong",
        "location_or_route_mismatch",
        "device_reading_mismatch",
    ]
    affected_fact_refs: list[str] = Field(min_length=1, max_length=12)
    affected_fact_hashes: list[str] = Field(min_length=1, max_length=12)
    reporter_alias: str = Field(min_length=1, max_length=80)
    optional_note: str | None = Field(default=None, max_length=280)
    explicit_confirmation: bool


class FieldConflictResolutionRequest(WorkbenchModel):
    command_context: CanonicalCommandContext
    conflict_event_id: str
    row_id: str
    fresh_evidence_refs: list[str] = Field(max_length=12)
    fresh_evidence_hashes: list[str] = Field(max_length=12)
    leader_confirms_field_conflict_cleared: bool
    reviewer_alias: str = Field(min_length=1, max_length=80)
    explicit_confirmation: bool

    @field_validator("fresh_evidence_hashes")
    @classmethod
    def validate_fresh_evidence_hashes(cls, value: list[str]) -> list[str]:
        if any(not _SHA256_PATTERN.fullmatch(item) for item in value):
            raise ValueError("fresh evidence hashes must be lowercase SHA-256 digests")
        return value


class IndividualActionTransitionRequest(WorkbenchModel):
    command_context: CanonicalCommandContext
    participant_ref: str
    device_ref: str
    activity_episode_id: str
    prior_state: Literal[
        "route_travel",
        "stationary_candidate",
        "resting",
        "lying",
        "sleeping",
        "resumed_movement",
        "unknown",
    ]
    new_state: Literal[
        "route_travel",
        "stationary_candidate",
        "resting",
        "lying",
        "sleeping",
        "resumed_movement",
        "unknown",
    ]
    transition_kind: Literal["started", "ended", "resumed", "corrected"]
    confidence: Literal["high", "medium", "low", "unknown"]
    freshness: Literal["fresh", "stale", "unknown"]
    evidence_hashes: list[str] = Field(min_length=1, max_length=8)
    self_correction: bool


class DepartureStartRequest(WorkbenchModel):
    command_context: CanonicalCommandContext
    checklist_id: str
    checklist_sha256: str
    pending_mission_day_id: str
    pending_day_plan_sha256: str
    leader_attestations: dict[str, bool]
    reviewer_alias: str = Field(min_length=1, max_length=80)
    explicit_confirmation: bool


class CommunicationEventRequest(WorkbenchModel):
    command_context: CanonicalCommandContext
    event_kind: Literal[
        "deadline_elapsed",
        "verified_check_in",
        "contact_restored",
        "forward_window_adjusted",
    ]
    communication_policy_id: str
    communication_policy_sha256: str
    route_scope_match: bool
    acknowledged_receipt_ref: str | None
    compound_evidence_refs: list[str] = Field(max_length=12)
    retroactive: bool
    new_effective_window: str | None = Field(default=None, max_length=160)
    adjustment_event_ref: str | None = None
    adjustment_event_sha256: str | None = None
    reviewer_alias: str | None = Field(default=None, max_length=80)
    explicit_confirmation: bool = False

    @model_validator(mode="after")
    def validate_reviewed_window_adjustment(self) -> "CommunicationEventRequest":
        if self.event_kind == "forward_window_adjusted" and (
            not self.reviewer_alias or not self.explicit_confirmation
        ):
            raise ValueError(
                "forward communication-window adjustment requires explicit review"
            )
        return self


class ContactLossReviewRequest(WorkbenchModel):
    command_context: CanonicalCommandContext
    communication_policy_id: str
    communication_policy_sha256: str
    decision: Literal[
        "continue_monitoring",
        "request_check_in_when_available",
        "coordinate_rendezvous_review",
        "escalate_emergency_call_out",
    ]
    overdue_fact_refs: list[str] = Field(min_length=1, max_length=12)
    overdue_fact_hashes: list[str] = Field(min_length=1, max_length=12)
    compound_evidence_refs: list[str] = Field(max_length=12)
    compound_evidence_hashes: list[str] = Field(max_length=12)
    safety_emergency_trigger_refs: list[str] = Field(max_length=12)
    safety_emergency_trigger_hashes: list[str] = Field(max_length=12)
    reviewer_alias: str = Field(min_length=1, max_length=80)
    explicit_confirmation: bool

    @model_validator(mode="after")
    def validate_contact_review_lineage(self) -> "ContactLossReviewRequest":
        ref_hash_pairs = (
            (self.overdue_fact_refs, self.overdue_fact_hashes),
            (self.compound_evidence_refs, self.compound_evidence_hashes),
            (
                self.safety_emergency_trigger_refs,
                self.safety_emergency_trigger_hashes,
            ),
        )
        if any(len(refs) != len(hashes) for refs, hashes in ref_hash_pairs):
            raise ValueError("contact-loss evidence refs and hashes must align")
        hashes = [item for _, items in ref_hash_pairs for item in items]
        if any(not _SHA256_PATTERN.fullmatch(item) for item in hashes):
            raise ValueError("contact-loss evidence hashes must be SHA-256 digests")
        if any(
            not item.startswith("automatic://communication/contact-overdue/")
            for item in self.overdue_fact_refs
        ):
            raise ValueError("contact overdue must remain an automatic fact")
        if any(
            not item.startswith("trigger://safety-emergency/")
            for item in self.safety_emergency_trigger_refs
        ):
            raise ValueError("human concern requires a Safety / Emergency trigger")
        return self


class MovementGroupFormationRequest(WorkbenchModel):
    command_context: CanonicalCommandContext
    new_group_id: str
    display_name: str = Field(min_length=1, max_length=80)
    formation_kind: Literal["baseline_reviewed", "field_explicit"]
    participant_refs_hash: str
    coordinator_ref: str
    mission_day_id: str
    mission_day_instance_id: str
    target_ref: str
    target_sha256: str
    shared_dependency_refs: list[str] = Field(max_length=12)
    shared_dependency_hashes: list[str] = Field(default_factory=list, max_length=12)
    reporter_alias: str = Field(min_length=1, max_length=80)
    explicit_confirmation: bool

    @model_validator(mode="after")
    def validate_formation_lineage(self) -> "MovementGroupFormationRequest":
        if len(self.shared_dependency_refs) != len(self.shared_dependency_hashes):
            raise ValueError("shared dependency refs and hashes must have equal length")
        hashes = [
            self.participant_refs_hash,
            self.target_sha256,
            *self.shared_dependency_hashes,
        ]
        if any(not _SHA256_PATTERN.fullmatch(item) for item in hashes):
            raise ValueError("movement-group lineage hashes must be SHA-256 digests")
        return self


class ManualDayEndConfirmationRequest(WorkbenchModel):
    command_context: CanonicalCommandContext
    target_ref: str
    target_sha256: str
    target_label: str = Field(min_length=1, max_length=120)
    target_kind: Literal["planned_day_end", "emergency_bivy"]
    confirmation_kind: Literal["arrived", "camp_established"]
    authorized_on_site_participant: bool
    participant_alias: str = Field(min_length=1, max_length=80)
    explicit_confirmation: bool
    uncertainty_acknowledgement: bool

    @model_validator(mode="after")
    def validate_manual_confirmation(self) -> "ManualDayEndConfirmationRequest":
        if self.explicit_confirmation and not self.uncertainty_acknowledgement:
            raise ValueError("uncertainty acknowledgement is required")
        return self


class DayEndUnreachableRequest(WorkbenchModel):
    command_context: CanonicalCommandContext
    cause_kind: Literal["automatic_feasibility", "human_safety_trigger"]
    cause_refs: list[str] = Field(min_length=1, max_length=12)
    cause_hashes: list[str] = Field(min_length=1, max_length=12)
    reporter_alias: str | None = Field(default=None, max_length=80)
    explicit_confirmation: bool

    @field_validator("cause_hashes")
    @classmethod
    def validate_cause_hashes(cls, value: list[str]) -> list[str]:
        if any(not _SHA256_PATTERN.fullmatch(item) for item in value):
            raise ValueError("cause hashes must be lowercase SHA-256 digests")
        return value

    @model_validator(mode="after")
    def validate_cause_boundary(self) -> "DayEndUnreachableRequest":
        if self.cause_kind == "human_safety_trigger" and any(
            not item.startswith("trigger://safety-emergency/")
            for item in self.cause_refs
        ):
            raise ValueError(
                "human-driven cause evidence must be a Safety / Emergency trigger"
            )
        return self


class EmergencyBivySelectionRequest(WorkbenchModel):
    command_context: CanonicalCommandContext
    target_ref: str
    target_sha256: str
    target_label: str = Field(min_length=1, max_length=120)
    reviewer_alias: str = Field(min_length=1, max_length=80)
    explicit_confirmation: bool


class DayEndCloseCorrectionRequest(WorkbenchModel):
    command_context: CanonicalCommandContext
    close_event_id: str
    reason: Literal[
        "wrong_target", "still_travelling", "zone_mismatch", "group_mismatch"
    ]
    reporter_alias: str = Field(min_length=1, max_length=80)
    explicit_confirmation: bool


class ShelterHoldReviewRequest(WorkbenchModel):
    command_context: CanonicalCommandContext
    decision: Literal[
        "continue_hold", "departure_review_candidate", "relocate_or_escalate_review"
    ]
    calendar_days_elapsed: int = Field(ge=0, le=365)
    automatic_fact_refs: list[str] = Field(max_length=12)
    human_trigger_refs: list[str] = Field(max_length=12)
    reviewer_alias: str = Field(min_length=1, max_length=80)
    explicit_confirmation: bool


class MovementGroupRevisionRequest(WorkbenchModel):
    command_context: CanonicalCommandContext
    expected_membership_sha256: str
    participant_refs_hash: str
    coordinator_ref: str
    reporter_alias: str = Field(min_length=1, max_length=80)
    explicit_confirmation: bool


class MovementGroupMergeRequest(WorkbenchModel):
    command_context: CanonicalCommandContext
    source_group_ids: list[str] = Field(min_length=2, max_length=8)
    source_membership_revisions: dict[str, int]
    new_group_id: str
    display_name: str = Field(min_length=1, max_length=80)
    participant_refs_hash: str
    mission_day_id: str
    mission_day_instance_id: str
    target_ref: str
    target_sha256: str
    coordinator_ref: str | None = None
    shared_dependency_refs: list[str] = Field(default_factory=list, max_length=12)
    shared_dependency_hashes: list[str] = Field(default_factory=list, max_length=12)
    reconciliation_reviewed: bool
    reviewer_alias: str = Field(min_length=1, max_length=80)
    explicit_confirmation: bool

    @model_validator(mode="after")
    def validate_merge_lineage(self) -> "MovementGroupMergeRequest":
        if len(self.shared_dependency_refs) != len(self.shared_dependency_hashes):
            raise ValueError("shared dependency refs and hashes must have equal length")
        if any(
            not _SHA256_PATTERN.fullmatch(item)
            for item in [
                self.participant_refs_hash,
                self.target_sha256,
                *self.shared_dependency_hashes,
            ]
        ):
            raise ValueError("movement-group merge hashes must be SHA-256 digests")
        return self


class OfflineDayEndIntent(WorkbenchModel):
    intent_id: str
    idempotency_key: str
    command_context: CanonicalCommandContext
    target_ref: str
    target_sha256: str
    target_label: str = Field(min_length=1, max_length=120)
    target_kind: Literal["planned_day_end", "emergency_bivy"]
    confirmation_kind: Literal["arrived", "camp_established"]
    authorized_on_site_participant: Literal[True] = True
    participant_alias: str = Field(min_length=1, max_length=80)
    uncertainty_acknowledgement: bool
    explicit_confirmation: Literal[True] = True
    pending_sync: Literal[True]
    device_local_encrypted: Literal[True] = True
    candidate_only: Literal[True] = True
    runtime_authorization_performed: Literal[False] = False
    phase1_l0_l4_state_mutated: Literal[False] = False
    safety_api_called: Literal[False] = False
    outbound_action_performed: Literal[False] = False
    outbound_transport_invoked: Literal[False] = False
    external_send_performed: Literal[False] = False
    hardware_control_performed: Literal[False] = False

    @model_validator(mode="after")
    def validate_offline_day_end_intent(self) -> "OfflineDayEndIntent":
        if self.idempotency_key != self.command_context.idempotency_key:
            raise ValueError("offline intent and command idempotency keys must match")
        if not _SAFE_ID_PATTERN.fullmatch(self.intent_id):
            raise ValueError("invalid offline day-end intent id")
        if not _SHA256_PATTERN.fullmatch(self.target_sha256):
            raise ValueError("target_sha256 must be a SHA-256 digest")
        return self


class OfflineFieldConflictIntent(WorkbenchModel):
    intent_id: str
    idempotency_key: str
    command_context: CanonicalCommandContext
    checklist_id: str
    row_id: Literal[
        "weather_threats",
        "route_navigation",
        "equipment_power",
        "supplies_shelter",
        "communication_plan",
    ]
    category: Literal[
        "actual_condition_worse",
        "source_stale_or_wrong",
        "location_or_route_mismatch",
        "device_reading_mismatch",
    ]
    affected_fact_refs: list[str] = Field(min_length=1, max_length=12)
    affected_fact_hashes: list[str] = Field(min_length=1, max_length=12)
    reporter_alias: str = Field(min_length=1, max_length=80)
    optional_note: str | None = Field(default=None, max_length=280)
    explicit_confirmation: Literal[True] = True
    pending_sync: Literal[True]
    device_local_encrypted: Literal[True] = True
    candidate_only: Literal[True] = True
    runtime_authorization_performed: Literal[False] = False
    phase1_l0_l4_state_mutated: Literal[False] = False
    safety_api_called: Literal[False] = False
    outbound_action_performed: Literal[False] = False
    outbound_transport_invoked: Literal[False] = False
    external_send_performed: Literal[False] = False
    hardware_control_performed: Literal[False] = False

    @model_validator(mode="after")
    def validate_offline_field_conflict(self) -> "OfflineFieldConflictIntent":
        if self.idempotency_key != self.command_context.idempotency_key:
            raise ValueError("offline intent and command idempotency keys must match")
        if not _SAFE_ID_PATTERN.fullmatch(self.intent_id):
            raise ValueError("invalid offline field-conflict intent id")
        if len(self.affected_fact_refs) != len(self.affected_fact_hashes):
            raise ValueError("affected fact refs and hashes must align")
        if any(
            not _SHA256_PATTERN.fullmatch(item)
            for item in self.affected_fact_hashes
        ):
            raise ValueError("affected fact hashes must be SHA-256 digests")
        return self


class OfflineMovementGroupIntent(WorkbenchModel):
    intent_kind: Literal["formation", "membership_revision"]
    intent_id: str
    idempotency_key: str
    command_context: CanonicalCommandContext
    new_group_id: str | None = None
    display_name: str | None = Field(default=None, max_length=80)
    formation_kind: Literal["baseline_reviewed", "field_explicit"] | None = None
    participant_refs_hash: str
    coordinator_ref: str
    mission_day_id: str | None = None
    mission_day_instance_id: str | None = None
    target_ref: str | None = None
    target_sha256: str | None = None
    shared_dependency_refs: list[str] = Field(default_factory=list, max_length=12)
    shared_dependency_hashes: list[str] = Field(default_factory=list, max_length=12)
    reporter_alias: str = Field(min_length=1, max_length=80)
    expected_membership_sha256: str | None = None
    explicit_confirmation: Literal[True] = True
    pending_sync: Literal[True]
    device_local_encrypted: Literal[True] = True
    candidate_only: Literal[True] = True
    runtime_authorization_performed: Literal[False] = False
    phase1_l0_l4_state_mutated: Literal[False] = False
    safety_api_called: Literal[False] = False
    outbound_action_performed: Literal[False] = False
    outbound_transport_invoked: Literal[False] = False
    external_send_performed: Literal[False] = False
    hardware_control_performed: Literal[False] = False

    @model_validator(mode="after")
    def validate_offline_group_intent(self) -> "OfflineMovementGroupIntent":
        if self.idempotency_key != self.command_context.idempotency_key:
            raise ValueError("offline intent and command idempotency keys must match")
        if not _SAFE_ID_PATTERN.fullmatch(self.intent_id):
            raise ValueError("invalid offline movement-group intent id")
        if not _SHA256_PATTERN.fullmatch(self.participant_refs_hash):
            raise ValueError("participant_refs_hash must be a SHA-256 digest")
        if len(self.shared_dependency_refs) != len(self.shared_dependency_hashes):
            raise ValueError("shared dependency refs and hashes must align")
        if self.intent_kind == "formation":
            required = (
                self.new_group_id,
                self.display_name,
                self.formation_kind,
                self.mission_day_id,
                self.mission_day_instance_id,
                self.target_ref,
                self.target_sha256,
            )
            if not all(required):
                raise ValueError("offline group formation fields are incomplete")
            if not _SHA256_PATTERN.fullmatch(str(self.target_sha256)):
                raise ValueError("target_sha256 must be a SHA-256 digest")
        elif not self.expected_membership_sha256:
            raise ValueError("membership revision requires the prior membership hash")
        return self


def _canonical_payload(value: object) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        default=_canonical_json_default,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _canonical_json_default(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    raise TypeError(f"Unsupported canonical JSON value: {type(value).__name__}")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_payload(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _formatted_json_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        default=_canonical_json_default,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _fixed_hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _packet_hash(packet: dict[str, object]) -> str:
    return _digest(
        {
            key: value
            for key, value in packet.items()
            if key not in {"sha256", "server_now"}
        }
    )


def build_reference_workbench_seed(
    project_id: str,
) -> ContextualPermissionWorkbenchSeed:
    if not _SAFE_ID_PATTERN.fullmatch(project_id):
        raise ValueError("invalid project id")
    built_at = datetime(2026, 8, 2, 5, 30, tzinfo=timezone.utc)
    freshness_inputs = [
        FreshnessInput(
            gate_id="gate.weather_window",
            evidence_ref="evidence://weather/corridor-summary",
            evidence_sha256=_fixed_hash(f"{project_id}:weather"),
            valid_until=datetime(2099, 1, 1, 1, 0, tzinfo=timezone.utc),
            refresh_warning_at=datetime(2099, 1, 1, 0, 45, tzinfo=timezone.utc),
        ),
        FreshnessInput(
            gate_id="gate.route_progress",
            evidence_ref="evidence://movement/progress-summary",
            evidence_sha256=_fixed_hash(f"{project_id}:movement"),
            valid_until=datetime(2099, 1, 1, 1, 20, tzinfo=timezone.utc),
            refresh_warning_at=datetime(2099, 1, 1, 1, 5, tzinfo=timezone.utc),
        ),
        FreshnessInput(
            gate_id="gate.reviewed_policy",
            evidence_ref="reviewed://permission/policy-v1",
            evidence_sha256=_fixed_hash(f"{project_id}:policy"),
            valid_until=datetime(2099, 1, 2, 0, 0, tzinfo=timezone.utc),
        ),
    ]
    packet_payload: dict[str, object] = {
        "packet_id": "night.packet.D1.001",
        "sha256": "0" * 64,
        "project_id": project_id,
        "session_id": "session.replay.rest-overrun.v1",
        "mission_day_id": "D1",
        "mission_day_instance_id": "D1.instance.001",
        "movement_group_id": "group.ridge",
        "membership_revision": 1,
        "membership_sha256": _fixed_hash(f"{project_id}:group-ridge-membership"),
        "review_generation": 1,
        "reviewed_sequence": 12,
        "alternative_id": "alternative.night-to-reviewed-camp",
        "alternative_label": "Continue to the reviewed camp after dark",
        "from_target_ref": "target://reviewed-junction",
        "from_target_sha256": _fixed_hash(f"{project_id}:reviewed-junction"),
        "from_target_label": "Reviewed junction",
        "to_target_ref": "target://reviewed-camp",
        "to_target_sha256": _fixed_hash(f"{project_id}:reviewed-camp"),
        "to_target_label": "Reviewed camp",
        "direction": "reviewed-junction-to-reviewed-camp",
        "maximum_night_duration_minutes": 90,
        "stop_objective": "Reach the reviewed camp or use the reviewed retreat/bivy branch.",
        "retreat_candidate_refs": ["candidate://retreat/branch-A"],
        "emergency_bivy_candidate_refs": ["candidate://bivy/site-A"],
        "retreat_candidates": [
            ReviewedTargetRef(
                target_ref="candidate://retreat/branch-A",
                target_sha256=_fixed_hash(f"{project_id}:retreat-branch-A"),
                target_label="Reviewed retreat branch A",
            )
        ],
        "emergency_bivy_candidates": [
            ReviewedTargetRef(
                target_ref="candidate://bivy/site-A",
                target_sha256=_fixed_hash(f"{project_id}:bivy-site-A"),
                target_label="Reviewed bivy site A",
            )
        ],
        "requires_daylight": False,
        "reviewed_envelope_sha256": _fixed_hash(f"{project_id}:night-envelope"),
        "eligibility": "eligible_for_human_review",
        "approval_granted": False,
        "safety_state": "review_required",
        "server_now": built_at,
        "built_at": built_at,
        "expires_at": min(
            item.valid_until for item in freshness_inputs if item.valid_until is not None
        ),
        "freshness_state": "fresh",
        "expiry_driver": ExpiryDriver(
            gate_id="gate.weather_window",
            evidence_ref="evidence://weather/corridor-summary",
            valid_until=datetime(2099, 1, 1, 1, 0, tzinfo=timezone.utc),
            reason="Earliest required eligibility evidence deadline.",
        ),
        "freshness_inputs": freshness_inputs,
        "invalidated_by": [],
        "gates": [
            EligibilityGate(
                gate_id="gate.reviewed_alternative",
                label="Reviewed alternative",
                state="pass",
                hard_gate=True,
                reason="Exact route, stop objective, retreat, and bivy candidates are reviewed.",
                source_ref="reviewed://mission/day-D1",
                source_sha256=_fixed_hash(f"{project_id}:day-plan"),
            ),
            EligibilityGate(
                gate_id="gate.segment_policy",
                label="Segment policy",
                state="pass",
                hard_gate=True,
                reason="The reviewed segment explicitly declares requires_daylight=false.",
                source_ref="reviewed://permission/segment-D1",
                source_sha256=_fixed_hash(f"{project_id}:segment-policy"),
            ),
            EligibilityGate(
                gate_id="gate.terrain_route",
                label="Terrain / route",
                state="pass",
                hard_gate=True,
                reason="No unresolved geometry or incompatible terrain condition is present.",
                source_ref="evidence://route/terrain-night-summary",
                source_sha256=_fixed_hash(f"{project_id}:terrain-route"),
            ),
            EligibilityGate(
                gate_id="gate.lighting_power",
                label="Lighting / power",
                state="pass",
                hard_gate=True,
                reason="Primary and backup lighting cover duration plus reviewed reserve.",
                source_ref="evidence://equipment/lighting-power-summary",
                source_sha256=_fixed_hash(f"{project_id}:lighting-power"),
            ),
            EligibilityGate(
                gate_id="gate.navigation_resources",
                label="Navigation / resources",
                state="pass",
                hard_gate=True,
                reason="Offline navigation and bounded resource readiness cover the alternative.",
                source_ref="evidence://resources/night-navigation-summary",
                source_sha256=_fixed_hash(f"{project_id}:navigation-resources"),
            ),
            EligibilityGate(
                gate_id="gate.team",
                label="Team",
                state="pass",
                hard_gate=True,
                reason="Privacy-safe group readiness has no incompatible hold or separation.",
                source_ref="evidence://team/bounded-night-readiness",
                source_sha256=_fixed_hash(f"{project_id}:team"),
            ),
            EligibilityGate(
                gate_id="gate.weather_threat",
                label="Weather / threat",
                state="pass",
                hard_gate=True,
                reason="Fresh reviewed weather and threat thresholds pass.",
                source_ref="evidence://weather/corridor-summary",
                source_sha256=_fixed_hash(f"{project_id}:weather"),
            ),
            EligibilityGate(
                gate_id="gate.communication",
                label="Communication",
                state="pass",
                hard_gate=True,
                reason="The route-scoped communication or reviewed blackout plan covers the segment.",
                source_ref="reviewed://communication/window-D1",
                source_sha256=_fixed_hash(f"{project_id}:communication"),
            ),
            EligibilityGate(
                gate_id="gate.runtime_lineage",
                label="Runtime lineage",
                state="pass",
                hard_gate=True,
                reason="Project, baseline, session, group, sequence, and evidence hashes match.",
                source_ref="runtime://session/replay-rest-overrun-v1",
                source_sha256=_fixed_hash(f"{project_id}:runtime-lineage"),
            ),
        ],
        "source_refs": [
            "evidence://weather/corridor-summary",
            "evidence://movement/progress-summary",
            "reviewed://mission/day-D1",
        ],
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    packet_payload["sha256"] = _packet_hash(packet_payload)
    packet = NightAlternativePacket.model_validate(packet_payload)

    checklist_rows = [
        DepartureChecklistRow(
            row_id="weather_threats",
            label="Weather / threats",
            source_mode="scout_auto",
            state="pass",
            evidence_summary="Weather improved, but a new departure review is still required.",
            evidence_ref="evidence://weather/departure-summary",
            evidence_sha256=_fixed_hash(f"{project_id}:departure-weather"),
            freshness="fresh",
            field_condition_differs_available=True,
        ),
        DepartureChecklistRow(
            row_id="route_navigation",
            label="Route / navigation",
            source_mode="scout_auto",
            state="pass",
            evidence_summary="Reviewed route axis and next target are available.",
            evidence_ref="reviewed://route/day-D2",
            evidence_sha256=_fixed_hash(f"{project_id}:departure-route"),
            freshness="fresh",
            field_condition_differs_available=True,
        ),
        DepartureChecklistRow(
            row_id="team",
            label="Team",
            source_mode="leader_attestation",
            state="leader_check_required",
            evidence_summary="Leader must attest the field team condition.",
            evidence_ref=None,
            evidence_sha256=None,
            freshness="not_applicable",
            field_condition_differs_available=False,
            blocker="Leader attestation is not yet recorded.",
        ),
        DepartureChecklistRow(
            row_id="equipment_power",
            label="Equipment / power",
            source_mode="hybrid",
            state="pass",
            evidence_summary="Bounded device readiness is current; field difference may be reported.",
            evidence_ref="evidence://equipment/readiness-summary",
            evidence_sha256=_fixed_hash(f"{project_id}:departure-equipment"),
            freshness="fresh",
            field_condition_differs_available=True,
        ),
        DepartureChecklistRow(
            row_id="supplies_shelter",
            label="Supplies / shelter fallback",
            source_mode="hybrid",
            state="leader_check_required",
            evidence_summary="Existing readiness summary is available; field fallback needs attestation.",
            evidence_ref="evidence://resource/readiness-summary",
            evidence_sha256=_fixed_hash(f"{project_id}:departure-resources"),
            freshness="fresh",
            field_condition_differs_available=True,
            blocker="Shelter fallback attestation is not yet recorded.",
        ),
        DepartureChecklistRow(
            row_id="communication_plan",
            label="Communication / next-day plan",
            source_mode="hybrid",
            state="pass",
            evidence_summary="The next route-scoped communication window is reviewed.",
            evidence_ref="reviewed://communication/window-D2",
            evidence_sha256=_fixed_hash(f"{project_id}:departure-communication"),
            freshness="fresh",
            field_condition_differs_available=True,
        ),
    ]
    checklist = DepartureChecklistProjection(
        checklist_id="departure.checklist.D2.camp-group.v1",
        checklist_sha256=_fixed_hash(f"{project_id}:departure-checklist-camp-D2"),
        pending_day_plan_sha256=_fixed_hash(f"{project_id}:day-plan-D2"),
        rows=checklist_rows,
        open_conflict_count=0,
        scout_suggestion_code="departure_review_ready",
        scout_suggestion="Departure review may continue after the two field attestations.",
        scout_suggestion_suspended=False,
        can_confirm_departure=False,
        mission_day_started=False,
    )
    closed_checklist = checklist.model_copy(
        update={
            "checklist_id": "departure.checklist.D2.ridge-group.v1",
            "checklist_sha256": _fixed_hash(
                f"{project_id}:departure-checklist-ridge-D2"
            ),
            "rows": [
                row.model_copy(
                    update={
                        "state": "blocked",
                        "blocker": "Current mission day remains open.",
                    }
                )
                for row in checklist.rows
            ],
            "scout_suggestion_code": "continue_shelter_hold",
            "scout_suggestion": "Complete or contingently close D1 before any D2 review.",
            "can_confirm_departure": False,
        }
    )
    movement_groups = [
        MovementGroupProjection(
            group_id="group.ridge",
            group_label="Ridge group",
            formation_kind="baseline_reviewed",
            membership_revision=1,
            membership_sha256=_fixed_hash(f"{project_id}:group-ridge-membership"),
            participant_refs_hash=_fixed_hash(
                f"{project_id}:group-ridge-membership"
            ),
            coordinator_ref="participant://pseudo-ridge-coordinator",
            shared_dependency_refs=[],
            shared_dependency_hashes=[],
            formation_receipt_ref="reviewed://mission-baseline/group-ridge",
            formation_receipt_sha256=_fixed_hash(
                f"{project_id}:group-ridge-formation"
            ),
            status="in_progress",
            mission_day_id="D1",
            mission_day_instance_id="D1.instance.001",
            day_end=DayEndProjection(
                planned_target_label="Reviewed camp",
                effective_target_label="Reviewed camp",
                planned_target_ref="target://reviewed-camp",
                planned_target_sha256=_fixed_hash(f"{project_id}:reviewed-camp"),
                effective_target_ref="target://reviewed-camp",
                effective_target_sha256=_fixed_hash(f"{project_id}:reviewed-camp"),
                feasibility="at_risk",
                state="day_end_at_risk",
                completion="open",
                baseline_day_end_reached=False,
                close_receipt_ref=None,
            ),
            shelter_hold=ShelterHoldProjection(
                hold_id=None,
                state="not_required",
                target_label=None,
                calendar_days_elapsed=0,
                mission_days_consumed=0,
                next_step="Reach the reviewed target or open Emergency Bivy Review.",
            ),
            pending_next_day=None,
            departure_checklist=closed_checklist,
            activity_summary=ActivitySummary(
                states={
                    "route_travel": 3,
                    "resting": 1,
                    "lying": 0,
                    "sleeping": 0,
                    "resumed_movement": 0,
                    "unknown": 1,
                },
                fresh_count=4,
                stale_count=0,
                contradiction_count=0,
            ),
            arrival_dwell=ArrivalDwellProjection(
                state="idle",
                elapsed_seconds=0,
                dwell_remaining_seconds=600,
                target_ref="target://reviewed-camp",
                target_sha256=_fixed_hash(f"{project_id}:reviewed-camp"),
                arrival_zone_ref="reviewed://arrival-zone/ridge-camp",
                arrival_zone_sha256=_fixed_hash(
                    f"{project_id}:arrival-zone-ridge-camp"
                ),
                route_progress_ref="evidence://movement/progress-summary",
                route_progress_sha256=_fixed_hash(f"{project_id}:movement"),
                dwell_policy_ref="reviewed://dwell-policy/default-600s",
                dwell_policy_sha256=_fixed_hash(
                    f"{project_id}:dwell-policy-default-600s"
                ),
                individual_activity_summary_ref="evidence://activity/group-ridge",
                individual_activity_summary_sha256=_fixed_hash(
                    f"{project_id}:activity-group-ridge"
                ),
                target_match=False,
                gnss_confidence="unknown",
                manual_complete_available=False,
                blocked_by=["Reviewed arrival zone has not been entered."],
            ),
            communication=CommunicationProjection(
                policy_id="comm-window.ridge.D1.v1",
                policy_sha256=_fixed_hash(f"{project_id}:comm-ridge"),
                state="expected_blackout",
                membership_revision=1,
                route_scope_ref="reviewed://route/ridge-blackout-D1",
                route_scope_sha256=_fixed_hash(
                    f"{project_id}:route-ridge-blackout-D1"
                ),
                route_scope_label="Ridge traverse blackout envelope",
                viewpoint="local",
                next_check_in_target="Reviewed camp arrival",
                baseline_window="At reviewed camp arrival",
                effective_window="At reviewed camp arrival + accepted forward delay",
                deadline_driver="Reviewed arrival event; not a wall-clock heartbeat",
                next_check_in_target_ref="target://reviewed-camp",
                next_check_in_target_sha256=_fixed_hash(
                    f"{project_id}:reviewed-camp"
                ),
                last_verified_receipt_ref="receipt://check-in/ridge-previous",
                last_verified_receipt_sha256=_fixed_hash(
                    f"{project_id}:check-in-ridge-previous"
                ),
                local_group_contact_state="expected_blackout",
                remote_observed_contact_state="unknown",
                scout_recommendation="monitor_reviewed_window",
                contact_overdue=False,
                emergency_declared=False,
            ),
            unexpected_separation=False,
        ),
        MovementGroupProjection(
            group_id="group.camp",
            group_label="Camp group",
            formation_kind="baseline_reviewed",
            membership_revision=1,
            membership_sha256=_fixed_hash(f"{project_id}:group-camp-membership"),
            participant_refs_hash=_fixed_hash(
                f"{project_id}:group-camp-membership"
            ),
            coordinator_ref="participant://pseudo-camp-coordinator",
            shared_dependency_refs=[],
            shared_dependency_hashes=[],
            formation_receipt_ref="reviewed://mission-baseline/group-camp",
            formation_receipt_sha256=_fixed_hash(
                f"{project_id}:group-camp-formation"
            ),
            status="pending_day_start",
            mission_day_id="D1",
            mission_day_instance_id="D1.instance.002",
            day_end=DayEndProjection(
                planned_target_label="Reviewed camp",
                effective_target_label="Reviewed camp",
                planned_target_ref="target://reviewed-camp",
                planned_target_sha256=_fixed_hash(f"{project_id}:reviewed-camp"),
                effective_target_ref="target://reviewed-camp",
                effective_target_sha256=_fixed_hash(f"{project_id}:reviewed-camp"),
                feasibility="reachable",
                state="day_closed_planned",
                completion="planned_closed",
                baseline_day_end_reached=True,
                close_receipt_ref="receipt://day-end/camp-group-D1",
            ),
            shelter_hold=ShelterHoldProjection(
                hold_id="hold.camp-group.001",
                state="departure_review_candidate",
                target_label="Reviewed camp",
                location_target_ref="target://reviewed-camp",
                location_target_sha256=_fixed_hash(f"{project_id}:reviewed-camp"),
                location_kind="planned_day_end",
                closed_mission_day_instance_id="D1.instance.002",
                pending_next_mission_day_id="D2",
                calendar_days_elapsed=3,
                mission_days_consumed=0,
                automatic_cause_refs=["evidence://weather/extreme-hold"],
                next_step="Finish the six-row review before a separate D2 start receipt.",
            ),
            pending_next_day="D2",
            departure_checklist=checklist,
            activity_summary=ActivitySummary(
                states={
                    "route_travel": 0,
                    "resting": 1,
                    "lying": 1,
                    "sleeping": 2,
                    "resumed_movement": 0,
                    "unknown": 0,
                },
                fresh_count=4,
                stale_count=0,
                contradiction_count=0,
            ),
            arrival_dwell=ArrivalDwellProjection(
                state="complete",
                elapsed_seconds=600,
                dwell_remaining_seconds=0,
                target_ref="target://reviewed-camp",
                target_sha256=_fixed_hash(f"{project_id}:reviewed-camp"),
                arrival_zone_ref="reviewed://arrival-zone/camp",
                arrival_zone_sha256=_fixed_hash(f"{project_id}:arrival-zone-camp"),
                route_progress_ref="evidence://movement/camp-arrival",
                route_progress_sha256=_fixed_hash(
                    f"{project_id}:movement-camp-arrival"
                ),
                dwell_policy_ref="reviewed://dwell-policy/default-600s",
                dwell_policy_sha256=_fixed_hash(
                    f"{project_id}:dwell-policy-default-600s"
                ),
                individual_activity_summary_ref="evidence://activity/group-camp",
                individual_activity_summary_sha256=_fixed_hash(
                    f"{project_id}:activity-group-camp"
                ),
                target_match=True,
                gnss_confidence="high",
                manual_complete_available=True,
                day_close_receipt_ref="receipt://day-end/camp-group-D1",
                day_close_receipt_sha256=_fixed_hash(
                    f"{project_id}:day-end-camp-group-D1"
                ),
            ),
            communication=CommunicationProjection(
                policy_id="comm-window.camp.D1.v1",
                policy_sha256=_fixed_hash(f"{project_id}:comm-camp"),
                state="contact_available",
                membership_revision=1,
                route_scope_ref="reviewed://route/camp-D1",
                route_scope_sha256=_fixed_hash(f"{project_id}:route-camp-D1"),
                route_scope_label="Reviewed camp",
                viewpoint="synchronized",
                next_check_in_target="D2 departure review",
                baseline_window="After D2 start receipt",
                effective_window="After D2 start receipt",
                deadline_driver="Pending mission-day start event",
                next_check_in_target_ref="reviewed://event/D2-start",
                next_check_in_target_sha256=_fixed_hash(f"{project_id}:D2-start"),
                last_verified_receipt_ref="receipt://check-in/camp-arrival",
                last_verified_receipt_sha256=_fixed_hash(
                    f"{project_id}:check-in-camp-arrival"
                ),
                local_group_contact_state="contact_available",
                remote_observed_contact_state="contact_available",
                scout_recommendation="monitor_reviewed_window",
                contact_overdue=False,
                emergency_declared=False,
            ),
            unexpected_separation=False,
        ),
    ]
    return ContextualPermissionWorkbenchSeed(
        artifact_kind="contextual_permission_workbench_seed",
        schema_version="contextualPermissionWorkbenchSeed.v1",
        project_id=project_id,
        lens="replay",
        replay_session_id="session.replay.rest-overrun.v1",
        baseline=BaselineIdentity(
            baseline_id=f"baseline.{project_id}",
            revision_id="revision.001",
            baseline_sha256=_fixed_hash(f"{project_id}:reviewed-baseline"),
            reviewed_receipt_ref="reviewed://mission-baseline/review.001",
            source_mode="human_text",
            baseline_candidate_id=f"baseline.{project_id}",
            baseline_version_id="revision.001",
            accepted_receipt_id="review.001",
        ),
        action_events=[
            ScoutActionEvent(
                event_id="event.rest.001",
                sequence=12,
                action_id="rest",
                status="overrun",
                authorized_duration_minutes=6,
                observed_duration_minutes=16,
                debt_minutes=10,
                causes=[
                    CauseEvidence(
                        cause_id="fact.weather.rain-cell",
                        source_kind="weather_fact",
                        source_ref="evidence://weather/rain-cell",
                        source_sha256=_fixed_hash(f"{project_id}:rain-cell"),
                        verified=True,
                    ),
                    CauseEvidence(
                        cause_id="trigger.leader.extended-rest",
                        source_kind="safety_emergency_trigger",
                        source_ref="receipt://safety/extended-rest",
                        source_sha256=_fixed_hash(f"{project_id}:extended-rest"),
                        verified=True,
                    ),
                ],
                safety_trigger_locked=True,
            )
        ],
        remaining_plan=[
            RemainingPlanNode(
                node_id="node.photo_stop",
                label="Optional photo stop",
                mission_day_id="D1",
                kind="discretionary_event",
                adjustment_policy="auto_reduce",
                baseline_duration_minutes=8,
                minimum_duration_minutes=2,
                effective_duration_minutes=8,
                absorbed_debt_minutes=0,
                protected=False,
                adjustment_state="unchanged",
                source_rule_ref="candidate://permission/photo-stop",
                source_rule_sha256=_fixed_hash(f"{project_id}:photo-stop"),
            ),
            RemainingPlanNode(
                node_id="node.wait_view",
                label="Optional viewpoint wait",
                mission_day_id="D1",
                kind="discretionary_event",
                adjustment_policy="auto_reduce",
                baseline_duration_minutes=7,
                minimum_duration_minutes=3,
                effective_duration_minutes=7,
                absorbed_debt_minutes=0,
                protected=False,
                adjustment_state="unchanged",
                source_rule_ref="candidate://permission/view-wait",
                source_rule_sha256=_fixed_hash(f"{project_id}:view-wait"),
            ),
            RemainingPlanNode(
                node_id="node.route_floor",
                label="Reviewed route-travel floor",
                mission_day_id="D1",
                kind="route_travel",
                adjustment_policy="protected_floor",
                baseline_duration_minutes=45,
                minimum_duration_minutes=45,
                effective_duration_minutes=45,
                absorbed_debt_minutes=0,
                protected=True,
                adjustment_state="protected",
                source_rule_ref="reviewed://permission/route-floor",
                source_rule_sha256=_fixed_hash(f"{project_id}:route-floor"),
            ),
            RemainingPlanNode(
                node_id="node.daylight_reserve",
                label="Daylight / retreat reserve",
                mission_day_id="D1",
                kind="protected_reserve",
                adjustment_policy="protected_floor",
                baseline_duration_minutes=30,
                minimum_duration_minutes=30,
                effective_duration_minutes=30,
                absorbed_debt_minutes=0,
                protected=True,
                adjustment_state="protected",
                source_rule_ref="reviewed://permission/daylight-reserve",
                source_rule_sha256=_fixed_hash(f"{project_id}:daylight-reserve"),
            ),
            RemainingPlanNode(
                node_id="node.night_alternative",
                label="Night continuation alternative",
                mission_day_id="D1",
                kind="night_alternative",
                adjustment_policy="review_only",
                baseline_duration_minutes=0,
                minimum_duration_minutes=0,
                effective_duration_minutes=0,
                absorbed_debt_minutes=0,
                protected=False,
                adjustment_state="review_required",
                source_rule_ref="candidate://permission/night-alternative",
                source_rule_sha256=_fixed_hash(f"{project_id}:night-alternative"),
            ),
        ],
        daily_review=DailyEmergencyReviewSession(
            session_id="daily-review.D1.001",
            project_id=project_id,
            mission_day_id="D1",
            mission_day_instance_id="D1.instance.001",
            movement_group_id="group.ridge",
            membership_revision=1,
            mission_day_plan_ref="reviewed://mission/day-D1",
            mission_day_plan_sha256=_fixed_hash(f"{project_id}:day-plan"),
            review_generation=1,
            state="not_started",
            planned_day_end_target_ref="target://reviewed-camp",
            planned_day_end_target_sha256=_fixed_hash(f"{project_id}:reviewed-camp"),
            planned_day_end_target_label="Reviewed camp",
            effective_day_end_target_ref="target://reviewed-camp",
            effective_day_end_target_sha256=_fixed_hash(f"{project_id}:reviewed-camp"),
            day_end_state="day_end_at_risk",
            alternatives=[packet],
        ),
        movement_groups=movement_groups,
        evidence=[
            BoundedSourceRef(
                source_id="source.reviewed-graph",
                source_kind="reviewed_mission_graph",
                source_ref="outputs/compiled_mission_graph.reviewed.json",
                source_sha256=_fixed_hash(f"{project_id}:graph-placeholder"),
                freshness="not_applicable",
                summary="Reviewed mission graph identity and route-node order.",
            ),
            BoundedSourceRef(
                source_id="source.planned-eta",
                source_kind="planned_eta",
                source_ref="outputs/planned_eta.json",
                source_sha256=_fixed_hash(f"{project_id}:eta-placeholder"),
                freshness="fresh",
                summary="Bounded timing and reviewed target names; no raw track exposed.",
            ),
            BoundedSourceRef(
                source_id="source.weather",
                source_kind="normalized_weather_fact",
                source_ref="evidence://weather/corridor-summary",
                source_sha256=_fixed_hash(f"{project_id}:weather"),
                freshness="fresh",
                summary="Normalized weather fact used only for candidate pace advice.",
            ),
            BoundedSourceRef(
                source_id="source.movement",
                source_kind="normalized_movement_fact",
                source_ref="evidence://movement/progress-summary",
                source_sha256=_fixed_hash(f"{project_id}:movement"),
                freshness="fresh",
                summary="Privacy-bounded movement/progress state without raw IMU or track data.",
            ),
        ],
    )


class ContextualPermissionWorkbench:
    def __init__(
        self,
        *,
        project_root: Path,
        store_root: Path,
        now_factory: Callable[[], datetime] | None = None,
        seed_override: ContextualPermissionWorkbenchSeed | None = None,
        allow_stale_projection: bool = False,
    ) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.store_root = Path(store_root).expanduser().resolve()
        self.now_factory = now_factory or (lambda: datetime.now(timezone.utc))
        self._seed_override = seed_override
        self._allow_stale_projection = allow_stale_projection
        self._seed = self._load_seed()
        self.project_id = self._seed.project_id

    def _load_seed(self) -> ContextualPermissionWorkbenchSeed:
        seed_path = (self.project_root / DEFAULT_WORKBENCH_SEED_REF).resolve()
        if self.project_root not in seed_path.parents:
            raise ContextualPermissionConflict(
                "invalid_seed_ref", "Workbench seed resolved outside the project root."
            )
        if not seed_path.is_file() and self._seed_override is None:
            raise ContextualPermissionConflict(
                "contextual_permission_seed_missing",
                f"Contextual Permission seed is missing: {DEFAULT_WORKBENCH_SEED_REF}",
            )
        if seed_path.is_file():
            try:
                payload = json.loads(seed_path.read_text(encoding="utf-8"))
                seed = ContextualPermissionWorkbenchSeed.model_validate(payload)
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                raise ContextualPermissionConflict(
                    "invalid_contextual_permission_seed",
                    f"Contextual Permission seed is invalid: {exc}",
                ) from exc
        else:
            seed = self._seed_override
            if seed is None:  # pragma: no cover - guarded above
                raise ContextualPermissionConflict(
                    "contextual_permission_seed_missing",
                    "Contextual Permission seed is missing.",
                )
        if not _SAFE_ID_PATTERN.fullmatch(seed.project_id):
            raise ContextualPermissionConflict(
                "invalid_project_id",
                "Workbench project identity is not safe for canonical storage.",
            )
        project_path = self._resolve_project_ref("project.json")
        if not project_path.is_file():
            raise ContextualPermissionConflict(
                "project_manifest_missing", "project.json is required."
            )
        try:
            project = json.loads(project_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContextualPermissionConflict(
                "invalid_project_manifest", f"project.json is invalid: {exc}"
            ) from exc
        manifest_project_id = str(project.get("project_id") or self.project_root.name)
        if seed.project_id != manifest_project_id:
            raise ContextualPermissionConflict(
                "project_identity_mismatch",
                "Workbench seed does not match the selected project.",
            )
        if self._allow_stale_projection:
            # Baseline authoring and an explicit rebuild are independently
            # source/hash-bound. A stale or invalid derived Permission rule/ETA
            # must not make those recovery surfaces unreachable.
            return seed
        source_hashes: dict[str, str] = {}
        for ref_key in (
            "compiled_mission_graph_reviewed_ref",
            "planned_eta_ref",
        ):
            ref = project.get(ref_key)
            if not isinstance(ref, str) or not ref.strip():
                raise ContextualPermissionConflict(
                    "reviewed_baseline_input_missing",
                    f"{ref_key} is required for the workbench projection.",
                )
            path = self._resolve_project_ref(ref)
            if not path.is_file():
                raise ContextualPermissionConflict(
                    "reviewed_baseline_input_missing",
                    f"Required baseline input is missing: {ref}",
                )
            source_hashes[ref_key] = _file_sha256(path)
        selected_baseline_sha = project.get("reviewed_mission_baseline_sha256")
        if (
            isinstance(selected_baseline_sha, str)
            and selected_baseline_sha
            and selected_baseline_sha != seed.baseline.baseline_sha256
        ):
            raise ContextualPermissionConflict(
                "contextual_permission_projection_stale",
                "A newer reviewed baseline is selected; rebuild Contextual Permission artifacts explicitly.",
            )
        rules_ref = str(
            project.get("contextual_permission_rules_ref")
            or DEFAULT_CONTEXTUAL_PERMISSION_RULES_REF.as_posix()
        )
        rules_path = self._resolve_project_ref(rules_ref)
        if not rules_path.is_file():
            raise ContextualPermissionConflict(
                "contextual_permission_rules_missing",
                "Reviewed contextual_permission_rules.json is required.",
            )
        try:
            rules_artifact = ContextualPermissionRulesArtifact.model_validate_json(
                rules_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise ContextualPermissionConflict(
                "invalid_contextual_permission_rules",
                f"Contextual permission rules are invalid: {exc}",
            ) from exc
        if rules_artifact.project_id != seed.project_id:
            raise ContextualPermissionConflict(
                "contextual_permission_rules_project_mismatch",
                "Contextual permission rules belong to another project.",
            )
        if rules_artifact.reviewed_baseline_sha256 != seed.baseline.baseline_sha256:
            raise ContextualPermissionConflict(
                "contextual_permission_rules_baseline_mismatch",
                "Contextual permission rules are bound to another reviewed baseline.",
            )
        policies = {
            policy.node_id: policy for policy in rules_artifact.plan_node_policies
        }
        if len(policies) != len(rules_artifact.plan_node_policies):
            raise ContextualPermissionConflict(
                "contextual_permission_rules_duplicate_node",
                "Contextual permission rules contain a duplicate plan-node policy.",
            )
        for node in seed.remaining_plan:
            policy = policies.get(node.node_id)
            if policy is None:
                raise ContextualPermissionConflict(
                    "contextual_permission_rule_missing",
                    f"Reviewed policy is missing for plan node: {node.node_id}",
                )
            if (
                policy.mission_day_id != node.mission_day_id
                or policy.adjustment_policy != node.adjustment_policy
                or policy.minimum_duration_minutes != node.minimum_duration_minutes
                or policy.policy_ref != node.source_rule_ref
                or policy.policy_sha256 != node.source_rule_sha256
            ):
                raise ContextualPermissionConflict(
                    "contextual_permission_rule_mismatch",
                    f"Reviewed policy does not match plan node: {node.node_id}",
                )
        rules_sha256 = _file_sha256(rules_path)
        source_hashes["contextual_permission_rules_ref"] = rules_sha256
        evidence = []
        evidence_by_kind = {item.source_kind: item for item in seed.evidence}
        for source_kind, ref_key in (
            ("reviewed_mission_graph", "compiled_mission_graph_reviewed_ref"),
            ("planned_eta", "planned_eta_ref"),
        ):
            item = evidence_by_kind.get(source_kind)
            if item is not None:
                evidence.append(
                    item.model_copy(update={"source_sha256": source_hashes[ref_key]})
                )
        evidence.extend(
            item
            for item in seed.evidence
            if item.source_kind not in {"reviewed_mission_graph", "planned_eta"}
        )
        evidence.append(
            BoundedSourceRef(
                source_id="source.contextual-permission-rules",
                source_kind=(
                    "reviewed_contextual_permission_rules"
                    if rules_artifact.reviewed_by_human
                    else "contextual_permission_rule_bootstrap"
                ),
                source_ref=rules_ref,
                source_sha256=rules_sha256,
                freshness="not_applicable",
                summary=(
                    "Reviewed plan-node permission policies bound to the selected mission baseline."
                    if rules_artifact.reviewed_by_human
                    else "Fail-closed review-only bootstrap policies; human review is pending."
                ),
            )
        )
        return seed.model_copy(
            update={
                "baseline": seed.baseline.model_copy(
                    update={
                        "contextual_permission_rules_ref": rules_ref,
                        "contextual_permission_rules_sha256": rules_sha256,
                        "contextual_permission_rules_reviewed_by_human": (
                            rules_artifact.reviewed_by_human
                        ),
                        "source_hashes": source_hashes,
                    }
                ),
                "evidence": evidence,
            }
        )

    def _resolve_project_ref(self, ref: str) -> Path:
        candidate = Path(ref)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ContextualPermissionConflict(
                "unsafe_project_ref", "Project refs must be relative and contained."
            )
        resolved = (self.project_root / candidate).resolve()
        if self.project_root != resolved and self.project_root not in resolved.parents:
            raise ContextualPermissionConflict(
                "unsafe_project_ref", "Project ref resolved outside the project root."
            )
        return resolved

    def _resolve_project_write_path(self, *parts: str) -> Path:
        resolved = self.project_root.joinpath(*parts).resolve(strict=False)
        if self.project_root != resolved and self.project_root not in resolved.parents:
            raise ContextualPermissionConflict(
                "unsafe_project_write_path",
                "Project write path resolved outside the project root.",
            )
        return resolved

    def _resolve_store_path(self, *parts: str) -> Path:
        resolved = self.store_root.joinpath(*parts).resolve(strict=False)
        if self.store_root != resolved and self.store_root not in resolved.parents:
            raise ContextualPermissionConflict(
                "unsafe_store_write_path",
                "Canonical store path resolved outside the configured store root.",
            )
        return resolved

    def _load_immutable_baseline_candidate(
        self,
        ref: str,
        expected_sha256: str,
    ) -> tuple[Path, dict[str, object]]:
        candidate_path = self._resolve_project_ref(ref)
        if not candidate_path.is_file():
            raise ContextualPermissionConflict(
                "baseline_candidate_missing", "The baseline candidate version is missing."
            )
        try:
            candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContextualPermissionConflict(
                "invalid_baseline_candidate", "The baseline candidate is not valid JSON."
            ) from exc
        if not isinstance(candidate, dict):
            raise ContextualPermissionConflict(
                "invalid_baseline_candidate", "The baseline candidate must be an object."
            )
        if (
            candidate.get("artifact_kind") != "mission_baseline_candidate_version"
            or candidate.get("schema_version") != "missionBaselineCandidate.v1"
        ):
            raise ContextualPermissionConflict(
                "invalid_baseline_candidate", "The baseline candidate contract is invalid."
            )
        for field in ("baseline_id", "version_id"):
            value = str(candidate.get(field) or "")
            if not _SAFE_ID_PATTERN.fullmatch(value):
                raise ContextualPermissionConflict(
                    "invalid_baseline_candidate_id",
                    f"The baseline candidate {field} is not safe for storage.",
                )
        stored_sha256 = str(candidate.get("version_sha256") or "")
        if (
            not _SHA256_PATTERN.fullmatch(expected_sha256)
            or stored_sha256 != expected_sha256
        ):
            raise ContextualPermissionConflict(
                "stale_candidate_hash", "The baseline candidate hash no longer matches."
            )
        computed_sha256 = _digest(
            {
                key: value
                for key, value in candidate.items()
                if key != "version_sha256"
            }
        )
        if computed_sha256 != stored_sha256:
            raise ContextualPermissionConflict(
                "baseline_candidate_hash_mismatch",
                "The immutable baseline candidate payload was modified after save.",
            )
        return candidate_path, candidate

    def _seed_group(self, group_id: str) -> MovementGroupProjection:
        for group in self._seed.movement_groups:
            if group.group_id == group_id:
                return group
        for group in self._reduce_movement_groups(self._load_all_canonical_events()):
            if group.group_id == group_id:
                return group
        raise ContextualPermissionConflict(
            "movement_group_not_found", "The movement group is not part of this session."
        )

    def _base_sequence(self, group_id: str) -> int:
        if group_id != self._seed.daily_review.movement_group_id:
            return 0
        return max((event.sequence for event in self._seed.action_events), default=0)

    def _canonical_session_root(self) -> Path:
        session_id = self._seed.replay_session_id
        if not _SAFE_ID_PATTERN.fullmatch(session_id):
            raise ContextualPermissionConflict(
                "invalid_session_id", "Invalid canonical session identifier."
            )
        return self._resolve_store_path(
            self.project_id,
            "sessions",
            session_id,
        )

    @contextmanager
    def _canonical_stream_lock(self) -> Iterator[None]:
        """Serialize compare-and-append across every process in one session."""
        session_root = self._canonical_session_root()
        session_root.mkdir(parents=True, exist_ok=True)
        lock_path = session_root / ".canonical-append.lock"
        with lock_path.open("a+b") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

    def _canonical_event_dir(self, group_id: str) -> Path:
        if not _SAFE_ID_PATTERN.fullmatch(group_id):
            raise ContextualPermissionConflict(
                "invalid_movement_group_id", "Invalid movement-group identifier."
            )
        return self._resolve_store_path(
            self.project_id,
            "sessions",
            self._seed.replay_session_id,
            "groups",
            group_id,
            "events",
        )

    def _load_group_events(self, group_id: str) -> list[CanonicalEvent]:
        event_dir = self._canonical_event_dir(group_id)
        if not event_dir.is_dir():
            return []
        events: list[CanonicalEvent] = []
        for path in sorted(event_dir.glob("*.json")):
            try:
                events.append(
                    CanonicalEvent.model_validate_json(path.read_text(encoding="utf-8"))
                )
            except (OSError, ValueError) as exc:
                raise ContextualPermissionConflict(
                    "invalid_canonical_event",
                    f"Stored contextual-permission event is invalid: {path.name}: {exc}",
                ) from exc
        events.sort(key=lambda item: item.sequence)
        expected = self._base_sequence(group_id)
        for event in events:
            if event.previous_sequence != expected or event.sequence != expected + 1:
                raise ContextualPermissionConflict(
                    "canonical_event_sequence_conflict",
                    "The group event stream is not contiguous.",
                )
            expected = event.sequence
        return events

    def _load_all_canonical_events(self) -> list[CanonicalEvent]:
        group_ids = {group.group_id for group in self._seed.movement_groups}
        groups_root = self._resolve_store_path(
            self.project_id,
            "sessions",
            self._seed.replay_session_id,
            "groups",
        )
        if groups_root.is_dir():
            group_ids.update(path.name for path in groups_root.iterdir() if path.is_dir())
        events: list[CanonicalEvent] = []
        for group_id in sorted(group_ids):
            if _SAFE_ID_PATTERN.fullmatch(group_id):
                events.extend(self._load_group_events(group_id))
        return sorted(events, key=lambda item: (item.recorded_at, item.group_id, item.sequence))

    def canonical_aggregate(self, group_id: str) -> CanonicalGroupAggregate:
        events = self._load_group_events(group_id)
        groups = self._reduce_movement_groups(self._load_all_canonical_events())
        group = next((item for item in groups if item.group_id == group_id), None)
        if group is None:
            raise ContextualPermissionConflict(
                "movement_group_not_found", "The movement group is not part of this session."
            )
        baseline = self._seed.baseline
        day_plan_sha = (
            self._seed.daily_review.mission_day_plan_sha256
            if group.mission_day_instance_id
            == self._seed.daily_review.mission_day_instance_id
            else _fixed_hash(
                f"{self.project_id}:{group.group_id}:{group.mission_day_id}:day-plan"
            )
        )
        initial_membership_revision, initial_membership_sha256 = (
            self._initial_group_membership(group_id)
        )
        binding_payload = {
            "project_id": self.project_id,
            "session_id": self._seed.replay_session_id,
            "reducer_version": CONTEXTUAL_PERMISSION_REDUCER_VERSION,
            "baseline_candidate_id": baseline.baseline_candidate_id or baseline.baseline_id,
            "baseline_version_id": baseline.baseline_version_id or baseline.revision_id,
            "baseline_schema_version": baseline.baseline_schema_version,
            "baseline_sha256": baseline.baseline_sha256,
            "accepted_receipt_ref": baseline.reviewed_receipt_ref,
            "contextual_permission_rules_ref": (
                baseline.contextual_permission_rules_ref
            ),
            "contextual_permission_rules_sha256": (
                baseline.contextual_permission_rules_sha256
            ),
            "group_id": group.group_id,
            "membership_revision": initial_membership_revision,
            "membership_sha256": initial_membership_sha256,
            "initial_mission_day_instance_id": self._initial_group_day_instance(group_id),
        }
        binding_sha = _digest(binding_payload)
        for event in events:
            if event.binding_sha256 != binding_sha:
                raise ContextualPermissionConflict(
                    "baseline_session_binding_mismatch",
                    "Stored events are bound to another baseline or group revision.",
                )
        seed_event_hashes = (
            [_digest(event) for event in self._seed.action_events]
            if group_id == self._seed.daily_review.movement_group_id
            else []
        )
        through_sequence = events[-1].sequence if events else self._base_sequence(group_id)
        aggregate_sha = _digest(
            {
                "binding_sha256": binding_sha,
                "seed_event_hashes": seed_event_hashes,
                "event_sha256s": [event.event_sha256 for event in events],
                "through_sequence": through_sequence,
            }
        )
        return CanonicalGroupAggregate(
            session_id=self._seed.replay_session_id,
            baseline_candidate_id=baseline.baseline_candidate_id or baseline.baseline_id,
            baseline_version_id=baseline.baseline_version_id or baseline.revision_id,
            baseline_schema_version=baseline.baseline_schema_version,
            baseline_sha256=baseline.baseline_sha256,
            accepted_receipt_ref=baseline.reviewed_receipt_ref,
            contextual_permission_rules_ref=(
                baseline.contextual_permission_rules_ref
                or DEFAULT_CONTEXTUAL_PERMISSION_RULES_REF.as_posix()
            ),
            contextual_permission_rules_sha256=(
                baseline.contextual_permission_rules_sha256 or "0" * 64
            ),
            binding_sha256=binding_sha,
            group_id=group.group_id,
            group_label=group.group_label,
            membership_revision=group.membership_revision,
            membership_sha256=group.membership_sha256,
            mission_day_id=group.mission_day_id,
            mission_day_instance_id=group.mission_day_instance_id,
            mission_day_plan_sha256=day_plan_sha,
            review_generation=self._review_generation_for(group_id, events),
            through_sequence=through_sequence,
            event_count=len(events),
            aggregate_sha256=aggregate_sha,
        )

    def _initial_group_membership(self, group_id: str) -> tuple[int, str]:
        for group in self._seed.movement_groups:
            if group.group_id == group_id:
                return group.membership_revision, group.membership_sha256
        formation = next(
            (
                event
                for event in self._load_all_canonical_events()
                if event.event_kind in {"movement_group_formed", "movement_groups_merged"}
                and event.payload.get("new_group_id") == group_id
            ),
            None,
        )
        if formation is None:
            raise ContextualPermissionConflict(
                "movement_group_not_found", "Initial group membership is unavailable."
            )
        return 1, str(formation.payload["participant_refs_hash"])

    def _initial_group_day_instance(self, group_id: str) -> str:
        for group in self._seed.movement_groups:
            if group.group_id == group_id:
                return group.mission_day_instance_id
        formation = next(
            (
                event
                for event in self._load_all_canonical_events()
                if event.event_kind in {"movement_group_formed", "movement_groups_merged"}
                and event.payload.get("new_group_id") == group_id
            ),
            None,
        )
        if formation is None:
            return "unknown.instance"
        return str(formation.payload["mission_day_instance_id"])

    def _review_generation_for(
        self, group_id: str, events: list[CanonicalEvent]
    ) -> int:
        generation = (
            self._seed.daily_review.review_generation
            if group_id == self._seed.daily_review.movement_group_id
            else 1
        )
        generation += sum(
            event.event_kind in {"daily_review_invalidated", "mission_day_started"}
            for event in events
        )
        return generation

    def _append_canonical_event(
        self,
        *,
        context: CanonicalCommandContext,
        event_kind: str,
        payload: dict[str, object],
    ) -> CanonicalEvent:
        command_sha = _digest(
            {
                "context": context.model_dump(mode="json"),
                "event_kind": event_kind,
                "payload": payload,
            }
        )
        with _STORE_LOCK, self._canonical_stream_lock():
            existing_events = self._load_group_events(context.group_id)
            existing = next(
                (
                    event
                    for event in existing_events
                    if event.idempotency_key == context.idempotency_key
                ),
                None,
            )
            if existing is not None:
                if existing.command_sha256 != command_sha:
                    raise ContextualPermissionConflict(
                        "idempotency_conflict",
                        "The idempotency key was already used for another command.",
                    )
                return existing
            aggregate = self.canonical_aggregate(context.group_id)
            if context.session_id != aggregate.session_id:
                raise ContextualPermissionConflict(
                    "session_binding_mismatch", "The session binding has changed."
                )
            if context.expected_baseline_sha256 != aggregate.baseline_sha256:
                raise ContextualPermissionConflict(
                    "baseline_binding_mismatch", "The reviewed baseline has changed."
                )
            if context.membership_revision != aggregate.membership_revision:
                raise ContextualPermissionConflict(
                    "movement_group_revision_mismatch",
                    "The movement-group membership revision has changed.",
                )
            if context.mission_day_instance_id != aggregate.mission_day_instance_id:
                raise ContextualPermissionConflict(
                    "wrong_mission_day", "The mission-day instance has changed."
                )
            if context.expected_sequence != aggregate.through_sequence:
                raise ContextualPermissionConflict(
                    "stale_sequence", "The group event sequence has advanced."
                )
            if context.expected_aggregate_sha256 != aggregate.aggregate_sha256:
                raise ContextualPermissionConflict(
                    "stale_aggregate", "The group aggregate hash has changed."
                )
            sequence = aggregate.through_sequence + 1
            event_id = f"{event_kind}.{context.idempotency_key}"
            body: dict[str, object] = {
                "event_id": event_id,
                "event_sha256": "0" * 64,
                "command_sha256": command_sha,
                "event_kind": event_kind,
                "project_id": self.project_id,
                "session_id": aggregate.session_id,
                "group_id": context.group_id,
                "binding_sha256": aggregate.binding_sha256,
                "sequence": sequence,
                "previous_sequence": aggregate.through_sequence,
                "idempotency_key": context.idempotency_key,
                "recorded_at": self._now(),
                "payload": payload,
                "candidate_projection_updated": True,
                "authority": AuthorityBoundary().model_dump(mode="json"),
            }
            body["event_sha256"] = _digest(
                {key: value for key, value in body.items() if key != "event_sha256"}
            )
            event = CanonicalEvent.model_validate(body)
            path = self._canonical_event_dir(context.group_id) / (
                f"{sequence:08d}-{_fixed_hash(context.idempotency_key)[:16]}.json"
            )
            self._write_new_json(path, event.model_dump(mode="json"))
            return event

    def _reduce_movement_groups(
        self, events: list[CanonicalEvent]
    ) -> list[MovementGroupProjection]:
        groups = {group.group_id: group for group in self._seed.movement_groups}
        for event in sorted(events, key=lambda item: (item.recorded_at, item.sequence)):
            if event.event_kind in {"movement_group_formed", "movement_groups_merged"}:
                self._apply_group_formation(groups, event)
                continue
            group = groups.get(event.group_id)
            if group is None:
                continue
            payload = event.payload
            if event.event_kind == "individual_activity_transitioned":
                states = dict(group.activity_summary.states)
                prior = str(payload["prior_state"])
                new = str(payload["new_state"])
                if states.get(prior, 0) > 0:
                    states[prior] -= 1
                states[new] = states.get(new, 0) + 1
                group = group.model_copy(
                    update={
                        "activity_summary": group.activity_summary.model_copy(
                            update={"states": states}
                        )
                    }
                )
            elif event.event_kind == "arrival_dwell_observed":
                blocked_by = list(payload.get("blocked_by") or [])
                is_emergency_bivy = (
                    group.day_end.effective_target_ref
                    != group.day_end.planned_target_ref
                )
                group = group.model_copy(
                    update={
                        "arrival_dwell": group.arrival_dwell.model_copy(
                            update={
                                "state": "blocked" if blocked_by else "counting",
                                "elapsed_seconds": int(payload["elapsed_seconds"]),
                                "dwell_remaining_seconds": max(
                                    0,
                                    group.arrival_dwell.required_seconds
                                    - int(payload["elapsed_seconds"]),
                                ),
                                "target_match": bool(payload["target_match"]),
                                "gnss_confidence": str(payload["gnss_confidence"]),
                                "manual_complete_available": bool(
                                    payload["target_match"]
                                ),
                                "blocked_by": blocked_by,
                                "blocking_contradictions": blocked_by,
                            }
                        ),
                        "day_end": group.day_end.model_copy(
                            update={
                                "state": (
                                    "emergency_bivy_establishment_unconfirmed"
                                    if is_emergency_bivy
                                    else "planned_day_end_arrival_unconfirmed"
                                )
                            }
                        ),
                    }
                )
            elif event.event_kind == "day_end_closed":
                contingency = payload.get("target_kind") == "emergency_bivy"
                target_ref = str(payload["target_ref"])
                target_sha = str(payload["target_sha256"])
                target_label = str(payload.get("target_label") or group.day_end.planned_target_label)
                pending_next_day = str(payload["pending_next_day"])
                departure_checklist = self._departure_checklist_after_day_close(
                    group=group,
                    pending_mission_day_id=pending_next_day,
                    event_sequence=event.sequence,
                )
                group = group.model_copy(
                    update={
                        "day_end": group.day_end.model_copy(
                            update={
                                "effective_target_label": target_label,
                                "effective_target_ref": target_ref,
                                "effective_target_sha256": target_sha,
                                "feasibility": "unreachable" if contingency else "reachable",
                                "state": (
                                    "day_closed_contingency"
                                    if contingency
                                    else "day_closed_planned"
                                ),
                                "completion": (
                                    "contingency_closed" if contingency else "planned_closed"
                                ),
                                "baseline_day_end_reached": not contingency,
                                "close_receipt_ref": f"event://{event.event_id}",
                                "confirmation_mode": str(payload["confirmation_mode"]),
                            }
                        ),
                        "shelter_hold": ShelterHoldProjection(
                            hold_id=f"hold.{group.group_id}.{event.sequence}",
                            state="active",
                            target_label=target_label,
                            location_target_ref=target_ref,
                            location_target_sha256=target_sha,
                            location_kind=(
                                "emergency_bivy" if contingency else "planned_day_end"
                            ),
                            closed_mission_day_instance_id=group.mission_day_instance_id,
                            pending_next_mission_day_id=pending_next_day,
                            calendar_days_elapsed=0,
                            mission_days_consumed=0,
                            automatic_cause_refs=list(payload.get("evidence_refs") or []),
                            weather_and_threat_evidence_refs=list(
                                payload.get("evidence_refs") or []
                            ),
                            started_at=event.recorded_at,
                            last_reviewed_at=event.recorded_at,
                            next_step=(
                                "Keep the next mission day pending until a reviewed start receipt."
                            ),
                        ),
                        "pending_next_day": pending_next_day,
                        "status": "pending_day_start",
                        "departure_checklist": departure_checklist,
                        "arrival_dwell": group.arrival_dwell.model_copy(
                            update={
                                "state": "complete",
                                "elapsed_seconds": max(
                                    600, int(payload.get("elapsed_seconds") or 0)
                                ),
                                "dwell_remaining_seconds": 0,
                                "target_ref": target_ref,
                                "target_sha256": target_sha,
                                "target_match": True,
                                "manual_complete_available": True,
                                "blocked_by": [],
                                "blocking_contradictions": [],
                                "day_close_receipt_ref": f"event://{event.event_id}",
                                "day_close_receipt_sha256": event.event_sha256,
                            }
                        ),
                    }
                )
            elif event.event_kind == "day_end_unreachable_reported":
                group = group.model_copy(
                    update={
                        "day_end": group.day_end.model_copy(
                            update={
                                "feasibility": "unreachable",
                                "state": "emergency_bivy_review_required",
                                "completion": "open",
                            }
                        )
                    }
                )
            elif event.event_kind == "emergency_bivy_selected":
                group = group.model_copy(
                    update={
                        "day_end": group.day_end.model_copy(
                            update={
                                "effective_target_label": str(payload["target_label"]),
                                "effective_target_ref": str(payload["target_ref"]),
                                "effective_target_sha256": str(payload["target_sha256"]),
                                "state": "emergency_bivy_selected",
                                "completion": "open",
                                "baseline_day_end_reached": False,
                            }
                        )
                    }
                )
            elif event.event_kind == "day_end_close_corrected":
                group = group.model_copy(
                    update={
                        "day_end": group.day_end.model_copy(
                            update={
                                "effective_target_label": group.day_end.planned_target_label,
                                "effective_target_ref": group.day_end.planned_target_ref,
                                "effective_target_sha256": group.day_end.planned_target_sha256,
                                "feasibility": "unknown",
                                "state": "en_route_to_planned_day_end",
                                "completion": "open",
                                "baseline_day_end_reached": False,
                                "correction_receipt_ref": f"event://{event.event_id}",
                                "confirmation_mode": "none",
                            }
                        ),
                        "shelter_hold": ShelterHoldProjection(
                            hold_id=None,
                            state="not_required",
                            target_label=None,
                            calendar_days_elapsed=0,
                            mission_days_consumed=0,
                            next_step="Re-establish the exact day-end target state.",
                        ),
                        "pending_next_day": None,
                        "arrival_dwell": group.arrival_dwell.model_copy(
                            update={
                                "state": "blocked",
                                "elapsed_seconds": 0,
                                "target_match": False,
                                "blocked_by": ["Prior day close was corrected."],
                                "blocking_contradictions": [
                                    "Prior day close was corrected."
                                ],
                                "dwell_remaining_seconds": (
                                    group.arrival_dwell.required_seconds
                                ),
                                "day_close_receipt_ref": None,
                                "day_close_receipt_sha256": None,
                            }
                        ),
                        "status": "in_progress",
                    }
                )
            elif event.event_kind == "shelter_hold_reviewed":
                decision = str(payload["decision"])
                hold_state = (
                    "active"
                    if decision == "continue_hold"
                    else "departure_review_candidate"
                    if decision == "departure_review_candidate"
                    else "escalated"
                )
                group = group.model_copy(
                    update={
                        "shelter_hold": group.shelter_hold.model_copy(
                            update={
                                "state": hold_state,
                                "calendar_days_elapsed": int(
                                    payload["calendar_days_elapsed"]
                                ),
                                "mission_days_consumed": 0,
                                "automatic_cause_refs": list(
                                    payload.get("automatic_fact_refs") or []
                                ),
                                "human_trigger_refs": list(
                                    payload.get("human_trigger_refs") or []
                                ),
                                "weather_and_threat_evidence_refs": list(
                                    payload.get("automatic_fact_refs") or []
                                ),
                                "last_reviewed_at": event.recorded_at,
                                "next_step": (
                                    "Continue Shelter Hold and refresh evidence."
                                    if decision == "continue_hold"
                                    else "Complete the six-row departure review."
                                    if decision == "departure_review_candidate"
                                    else "Open relocation or escalation review."
                                ),
                            }
                        )
                    }
                )
            elif event.event_kind == "movement_group_membership_revised":
                group = group.model_copy(
                    update={
                        "membership_revision": group.membership_revision + 1,
                        "membership_sha256": str(payload["participant_refs_hash"]),
                        "participant_refs_hash": str(
                            payload["participant_refs_hash"]
                        ),
                        "coordinator_ref": str(payload["coordinator_ref"]),
                        "communication": group.communication.model_copy(
                            update={
                                "membership_revision": group.membership_revision + 1
                            }
                        ),
                    }
                )
            elif event.event_kind == "field_conflict_reported":
                rows = []
                for row in group.departure_checklist.rows:
                    if row.row_id != payload["row_id"]:
                        rows.append(row)
                        continue
                    state = (
                        "blocked"
                        if payload["category"]
                        in {"actual_condition_worse", "location_or_route_mismatch"}
                        else "unknown"
                    )
                    rows.append(
                        row.model_copy(
                            update={
                                "state": state,
                                "blocker": "Leader field conflict is open.",
                            }
                        )
                    )
                checklist = group.departure_checklist.model_copy(
                    update={
                        "rows": rows,
                        "open_conflict_count": group.departure_checklist.open_conflict_count
                        + 1,
                        "scout_suggestion_code": "relocate_or_escalate_review",
                        "scout_suggestion": "Suspended; the field conflict has precedence.",
                        "scout_suggestion_suspended": True,
                        "can_confirm_departure": False,
                    }
                )
                group = group.model_copy(
                    update={"departure_checklist": self._rehash_checklist(checklist)}
                )
            elif event.event_kind == "field_conflict_resolved":
                original = next(
                    (
                        seed_group
                        for seed_group in self._seed.movement_groups
                        if seed_group.group_id == group.group_id
                    ),
                    None,
                )
                original_rows = {
                    row.row_id: row
                    for row in (
                        original.departure_checklist.rows if original else []
                    )
                }
                rows = []
                for row in group.departure_checklist.rows:
                    if row.row_id != payload["row_id"]:
                        rows.append(row)
                        continue
                    restored = original_rows.get(row.row_id, row)
                    fresh_refs = list(payload.get("fresh_evidence_refs") or [])
                    fresh_hashes = list(payload.get("fresh_evidence_hashes") or [])
                    rows.append(
                        restored.model_copy(
                            update={
                                "evidence_ref": fresh_refs[0]
                                if fresh_refs
                                else restored.evidence_ref,
                                "evidence_sha256": fresh_hashes[0]
                                if fresh_hashes
                                else restored.evidence_sha256,
                                "freshness": "fresh",
                                "blocker": None,
                            }
                        )
                    )
                remaining = max(0, group.departure_checklist.open_conflict_count - 1)
                checklist = group.departure_checklist.model_copy(
                    update={
                        "rows": rows,
                        "open_conflict_count": remaining,
                        "scout_suggestion": (
                            "Departure review may continue after all field attestations."
                        ),
                        "scout_suggestion_code": (
                            "departure_review_ready"
                            if remaining == 0
                            else "relocate_or_escalate_review"
                        ),
                        "scout_suggestion_suspended": remaining > 0,
                        "can_confirm_departure": remaining == 0
                        and all(row.state == "pass" for row in rows),
                    }
                )
                group = group.model_copy(
                    update={"departure_checklist": self._rehash_checklist(checklist)}
                )
            elif event.event_kind == "mission_day_started":
                next_day = str(payload["pending_mission_day_id"])
                next_instance = str(payload["next_mission_day_instance_id"])
                group = group.model_copy(
                    update={
                        "mission_day_id": next_day,
                        "mission_day_instance_id": next_instance,
                        "day_end": DayEndProjection(
                            planned_target_label=f"Reviewed {next_day} day-end target",
                            effective_target_label=f"Reviewed {next_day} day-end target",
                            planned_target_ref=f"target://{group.group_id}/{next_day}/end",
                            planned_target_sha256=_fixed_hash(
                                f"{self.project_id}:{group.group_id}:{next_day}:end"
                            ),
                            effective_target_ref=f"target://{group.group_id}/{next_day}/end",
                            effective_target_sha256=_fixed_hash(
                                f"{self.project_id}:{group.group_id}:{next_day}:end"
                            ),
                            feasibility="unknown",
                            state="en_route_to_planned_day_end",
                            completion="open",
                            baseline_day_end_reached=False,
                            close_receipt_ref=None,
                        ),
                        "shelter_hold": ShelterHoldProjection(
                            hold_id=group.shelter_hold.hold_id,
                            state="closed",
                            target_label=group.shelter_hold.target_label,
                            location_target_ref=group.shelter_hold.location_target_ref,
                            location_target_sha256=(
                                group.shelter_hold.location_target_sha256
                            ),
                            location_kind=group.shelter_hold.location_kind,
                            closed_mission_day_instance_id=(
                                group.shelter_hold.closed_mission_day_instance_id
                            ),
                            pending_next_mission_day_id=next_day,
                            calendar_days_elapsed=(
                                group.shelter_hold.calendar_days_elapsed
                            ),
                            mission_days_consumed=0,
                            automatic_cause_refs=(
                                group.shelter_hold.automatic_cause_refs
                            ),
                            human_trigger_refs=group.shelter_hold.human_trigger_refs,
                            weather_and_threat_evidence_refs=(
                                group.shelter_hold.weather_and_threat_evidence_refs
                            ),
                            team_and_resource_state_refs=(
                                group.shelter_hold.team_and_resource_state_refs
                            ),
                            started_at=group.shelter_hold.started_at,
                            last_reviewed_at=event.recorded_at,
                            next_step=f"Follow the reviewed {next_day} plan.",
                        ),
                        "status": "in_progress",
                        "pending_next_day": None,
                        "departure_checklist": group.departure_checklist.model_copy(
                            update={"mission_day_started": True, "can_confirm_departure": False}
                        ),
                        "arrival_dwell": ArrivalDwellProjection(
                            state="idle",
                            elapsed_seconds=0,
                            dwell_remaining_seconds=600,
                            target_ref=f"target://{group.group_id}/{next_day}/end",
                            target_sha256=_fixed_hash(
                                f"{self.project_id}:{group.group_id}:{next_day}:end"
                            ),
                            arrival_zone_ref=(
                                f"reviewed://arrival-zone/{group.group_id}/{next_day}"
                            ),
                            arrival_zone_sha256=_fixed_hash(
                                f"{self.project_id}:{group.group_id}:{next_day}:arrival-zone"
                            ),
                            route_progress_ref=(
                                f"evidence://movement/{group.group_id}/{next_day}"
                            ),
                            route_progress_sha256=_fixed_hash(
                                f"{self.project_id}:{group.group_id}:{next_day}:movement"
                            ),
                            dwell_policy_ref="reviewed://dwell-policy/default-600s",
                            dwell_policy_sha256=_fixed_hash(
                                f"{self.project_id}:dwell-policy-default-600s"
                            ),
                            individual_activity_summary_ref=(
                                f"evidence://activity/{group.group_id}"
                            ),
                            individual_activity_summary_sha256=_fixed_hash(
                                f"{self.project_id}:activity:{group.group_id}:{next_day}"
                            ),
                            target_match=False,
                            gnss_confidence="unknown",
                            manual_complete_available=False,
                            blocked_by=["Reviewed arrival zone has not been entered."],
                        ),
                    }
                )
            elif event.event_kind == "communication_deadline_elapsed":
                group = group.model_copy(
                    update={
                        "communication": group.communication.model_copy(
                            update={
                                "state": (
                                    "escalation_candidate"
                                    if payload.get("compound_evidence_refs")
                                    else "contact_overdue"
                                ),
                                "remote_observed_contact_state": "contact_overdue",
                                "automatic_contradictions": list(
                                    payload.get("compound_evidence_refs") or []
                                ),
                                "scout_recommendation": (
                                    "open_emergency_call_out_review"
                                    if payload.get("compound_evidence_refs")
                                    else "monitor_reviewed_window"
                                ),
                                "contact_overdue": True,
                                "emergency_declared": False,
                            }
                        )
                    }
                )
            elif event.event_kind in {
                "communication_check_in_verified",
                "communication_contact_restored",
            }:
                group = group.model_copy(
                    update={
                        "communication": group.communication.model_copy(
                            update={
                                "state": (
                                    "contact_restored"
                                    if event.event_kind == "communication_contact_restored"
                                    else "contact_available"
                                ),
                                "last_verified_receipt_ref": payload.get(
                                    "acknowledged_receipt_ref"
                                ),
                                "contact_overdue": False,
                                "emergency_declared": False,
                                "local_group_contact_state": "contact_available",
                                "remote_observed_contact_state": "contact_available",
                                "scout_recommendation": "monitor_reviewed_window",
                            }
                        )
                    }
                )
            elif event.event_kind == "communication_window_adjusted":
                group = group.model_copy(
                    update={
                        "communication": group.communication.model_copy(
                            update={
                                "effective_window": str(payload["new_effective_window"]),
                                "deadline_driver": str(payload["adjustment_event_ref"]),
                                "adjustment_receipt_ref": f"event://{event.event_id}",
                                "adjustment_receipt_sha256": event.event_sha256,
                            }
                        )
                    }
                )
            elif event.event_kind == "contact_loss_review_recorded":
                decision = str(payload["decision"])
                recommendations = {
                    "continue_monitoring": "monitor_reviewed_window",
                    "request_check_in_when_available": "check_in_when_available",
                    "coordinate_rendezvous_review": "coordinate_rendezvous_review",
                    "escalate_emergency_call_out": "open_emergency_call_out_review",
                }
                group = group.model_copy(
                    update={
                        "communication": group.communication.model_copy(
                            update={
                                "state": (
                                    "escalation_candidate"
                                    if decision == "escalate_emergency_call_out"
                                    else "contact_loss_review_required"
                                ),
                                "contact_loss_review_receipt_ref": (
                                    f"event://{event.event_id}"
                                ),
                                "contact_loss_review_receipt_sha256": (
                                    event.event_sha256
                                ),
                                "automatic_contradictions": list(
                                    payload.get("compound_evidence_refs") or []
                                ),
                                "scout_recommendation": recommendations[decision],
                                "emergency_declared": False,
                            }
                        )
                    }
                )
            groups[group.group_id] = group
        return list(groups.values())

    def _rehash_checklist(
        self, checklist: DepartureChecklistProjection
    ) -> DepartureChecklistProjection:
        payload = checklist.model_dump(mode="json")
        payload.pop("checklist_sha256", None)
        return checklist.model_copy(update={"checklist_sha256": _digest(payload)})

    def _departure_checklist_after_day_close(
        self,
        *,
        group: MovementGroupProjection,
        pending_mission_day_id: str,
        event_sequence: int,
    ) -> DepartureChecklistProjection:
        template_group = next(
            (
                candidate
                for candidate in self._seed.movement_groups
                if candidate.pending_next_day == pending_mission_day_id
                and any(
                    row.state in {"pass", "leader_check_required"}
                    for row in candidate.departure_checklist.rows
                )
            ),
            None,
        )
        if template_group is None:
            rows = [
                row.model_copy(
                    update={
                        "state": "unknown",
                        "blocker": "Reviewed next-day departure evidence is unavailable.",
                    }
                )
                for row in group.departure_checklist.rows
            ]
            checklist = group.departure_checklist.model_copy(
                update={
                    "checklist_id": (
                        f"departure.checklist.{pending_mission_day_id}."
                        f"{group.group_id}.{event_sequence}"
                    ),
                    "rows": rows,
                    "open_conflict_count": 0,
                    "scout_suggestion_code": "continue_shelter_hold",
                    "scout_suggestion": (
                        "Remain in Shelter Hold until reviewed next-day evidence is available."
                    ),
                    "scout_suggestion_suspended": False,
                    "can_confirm_departure": False,
                    "mission_day_started": False,
                }
            )
            return self._rehash_checklist(checklist)
        template = template_group.departure_checklist
        checklist = template.model_copy(
            update={
                "checklist_id": (
                    f"departure.checklist.{pending_mission_day_id}."
                    f"{group.group_id}.{event_sequence}"
                ),
                "rows": [row.model_copy(deep=True) for row in template.rows],
                "open_conflict_count": 0,
                "scout_suggestion_code": template.scout_suggestion_code,
                "mission_day_started": False,
            }
        )
        return self._rehash_checklist(checklist)

    def _apply_group_formation(
        self,
        groups: dict[str, MovementGroupProjection],
        event: CanonicalEvent,
    ) -> None:
        payload = event.payload
        new_group_id = str(payload["new_group_id"])
        if new_group_id in groups:
            return
        source = groups[event.group_id]
        blocked_rows = [
            row.model_copy(
                update={
                    "state": "blocked",
                    "blocker": "A new group requires its own reviewed day context.",
                }
            )
            for row in source.departure_checklist.rows
        ]
        checklist = self._rehash_checklist(
            source.departure_checklist.model_copy(
                update={
                    "checklist_id": f"departure.checklist.{new_group_id}.v1",
                    "rows": blocked_rows,
                    "open_conflict_count": 0,
                    "scout_suggestion_code": "refresh_evidence",
                    "scout_suggestion": "Review this group's independent day context.",
                    "scout_suggestion_suspended": False,
                    "can_confirm_departure": False,
                    "mission_day_started": False,
                }
            )
        )
        target_ref = str(payload["target_ref"])
        target_sha = str(payload["target_sha256"])
        groups[new_group_id] = MovementGroupProjection(
            group_id=new_group_id,
            group_label=str(payload["display_name"]),
            formation_kind=str(payload["formation_kind"]),
            membership_revision=1,
            membership_sha256=str(payload["participant_refs_hash"]),
            participant_refs_hash=str(payload["participant_refs_hash"]),
            coordinator_ref=str(payload["coordinator_ref"]),
            shared_dependency_refs=list(payload.get("shared_dependency_refs") or []),
            shared_dependency_hashes=list(
                payload.get("shared_dependency_hashes") or []
            ),
            formation_receipt_ref=f"event://{event.event_id}",
            formation_receipt_sha256=event.event_sha256,
            status="in_progress",
            mission_day_id=str(payload["mission_day_id"]),
            mission_day_instance_id=str(payload["mission_day_instance_id"]),
            day_end=DayEndProjection(
                planned_target_label="Reviewed movement-group target",
                effective_target_label="Reviewed movement-group target",
                planned_target_ref=target_ref,
                planned_target_sha256=target_sha,
                effective_target_ref=target_ref,
                effective_target_sha256=target_sha,
                feasibility="unknown",
                state="en_route_to_planned_day_end",
                completion="open",
                baseline_day_end_reached=False,
                close_receipt_ref=None,
            ),
            shelter_hold=ShelterHoldProjection(
                hold_id=None,
                state="not_required",
                target_label=None,
                calendar_days_elapsed=0,
                mission_days_consumed=0,
                next_step="Reach the reviewed group target.",
            ),
            pending_next_day=None,
            departure_checklist=checklist,
            activity_summary=ActivitySummary(
                states={
                    "route_travel": 0,
                    "stationary_candidate": 0,
                    "resting": 0,
                    "lying": 0,
                    "sleeping": 0,
                    "resumed_movement": 0,
                    "unknown": 1,
                },
                fresh_count=0,
                stale_count=0,
                contradiction_count=0,
            ),
            arrival_dwell=ArrivalDwellProjection(
                state="idle",
                elapsed_seconds=0,
                dwell_remaining_seconds=600,
                target_ref=target_ref,
                target_sha256=target_sha,
                arrival_zone_ref=f"reviewed://arrival-zone/{new_group_id}",
                arrival_zone_sha256=_fixed_hash(
                    f"{self.project_id}:{new_group_id}:arrival-zone"
                ),
                route_progress_ref=f"evidence://movement/{new_group_id}",
                route_progress_sha256=_fixed_hash(
                    f"{self.project_id}:{new_group_id}:movement"
                ),
                dwell_policy_ref="reviewed://dwell-policy/default-600s",
                dwell_policy_sha256=_fixed_hash(
                    f"{self.project_id}:dwell-policy-default-600s"
                ),
                individual_activity_summary_ref=f"evidence://activity/{new_group_id}",
                individual_activity_summary_sha256=_fixed_hash(
                    f"{self.project_id}:{new_group_id}:activity"
                ),
                target_match=False,
                gnss_confidence="unknown",
                manual_complete_available=False,
                blocked_by=["Reviewed arrival zone has not been entered."],
            ),
            communication=CommunicationProjection(
                policy_id=f"comm-window.{new_group_id}.pending",
                policy_sha256=_fixed_hash(f"{self.project_id}:{new_group_id}:comm"),
                state="unknown",
                membership_revision=1,
                route_scope_ref=f"reviewed://route/{new_group_id}/pending",
                route_scope_sha256=_fixed_hash(
                    f"{self.project_id}:{new_group_id}:route-pending"
                ),
                route_scope_label="Reviewed policy required",
                viewpoint="local",
                next_check_in_target="Review required",
                baseline_window="Unknown",
                effective_window="Unknown",
                deadline_driver="Reviewed policy missing",
                next_check_in_target_ref="reviewed://communication/target-pending",
                next_check_in_target_sha256=_fixed_hash(
                    f"{self.project_id}:{new_group_id}:check-in-target-pending"
                ),
                last_verified_receipt_ref=None,
                local_group_contact_state="unknown",
                remote_observed_contact_state="unknown",
                scout_recommendation="monitor_reviewed_window",
                contact_overdue=False,
                emergency_declared=False,
            ),
            unexpected_separation=False,
        )

    def projection(
        self,
        lens: Literal["baseline", "replay", "live_observer"] | None = None,
    ) -> ContextualPermissionProjection:
        selected_lens = lens or self._seed.lens
        if selected_lens == "live_observer":
            raise ContextualPermissionConflict(
                "live_observer_unavailable",
                "No hash-matching active runtime session is available.",
            )
        return self._build_projection(
            events=self._seed.action_events if selected_lens == "replay" else [],
            inspection_state="INSPECTING_STORED",
            current_state="stored_evaluation",
            projection_lens=selected_lens,
        )

    def _build_projection(
        self,
        *,
        events: list[ScoutActionEvent],
        inspection_state: Literal[
            "INSPECTING_STORED",
            "DIRTY_NOT_EVALUATED",
            "SIMULATING",
            "SIMULATION_READY",
            "SIMULATION_FAILED",
        ],
        current_state: Literal["stored_evaluation", "candidate_simulation"],
        projection_lens: Literal["baseline", "replay", "live_observer"],
    ) -> ContextualPermissionProjection:
        unique_events = {event.event_id: event for event in events}
        ordered_events = sorted(unique_events.values(), key=lambda item: item.sequence)
        total_debt = sum(event.debt_minutes for event in ordered_events)
        remaining_debt = total_debt
        adjusted_nodes: list[RemainingPlanNode] = []
        for node in self._seed.remaining_plan:
            if node.adjustment_policy == AdjustmentPolicy.AUTO_REDUCE:
                minimum_floor = node.minimum_duration_minutes
                if (
                    minimum_floor == 0
                    and node.baseline_duration_minutes > 0
                    and not node.cancellable
                ):
                    minimum_floor = 1
                available = max(
                    0,
                    node.baseline_duration_minutes - minimum_floor,
                )
            elif node.adjustment_policy == AdjustmentPolicy.PROTECTED_FLOOR:
                available = min(
                    node.discretionary_excess_minutes,
                    max(
                        0,
                        node.baseline_duration_minutes
                        - node.minimum_duration_minutes,
                    ),
                )
            else:
                available = 0
            absorbed = min(available, remaining_debt)
            effective = node.baseline_duration_minutes - absorbed
            remaining_debt -= absorbed
            if node.adjustment_policy == AdjustmentPolicy.REVIEW_ONLY:
                state = "review_required"
            elif node.adjustment_policy == AdjustmentPolicy.PROTECTED_FLOOR:
                state = "shortened" if absorbed else "protected"
            else:
                state = (
                    "cancelled"
                    if effective == 0 and absorbed > 0 and node.cancellable
                    else "shortened"
                    if absorbed > 0
                    else "unchanged"
                )
            adjusted_nodes.append(
                node.model_copy(
                    update={
                        "effective_duration_minutes": effective,
                        "available_reducible_minutes": available,
                        "applied_reduction_minutes": absorbed,
                        "absorbed_debt_minutes": absorbed,
                        "adjustment_state": state,
                    }
                )
            )
        absorbed_debt = total_debt - remaining_debt
        protected_reserves = [
            ProtectedReserve(
                reserve_id=node.node_id,
                label=node.label,
                baseline_minutes=node.baseline_duration_minutes,
                effective_minutes=node.effective_duration_minutes,
            )
            for node in adjusted_nodes
            if node.protected
        ]
        discretionary_remaining = sum(
            max(0, node.available_reducible_minutes - node.applied_reduction_minutes)
            for node in adjusted_nodes
            if node.adjustment_policy
            in {AdjustmentPolicy.AUTO_REDUCE, AdjustmentPolicy.PROTECTED_FLOOR}
        )
        missing_inputs = [
            gap
            for node in adjusted_nodes
            for gap in node.data_quality
        ]
        baseline_review_pending = (
            not self._seed.baseline.accepted_by_human
            or not self._seed.baseline.immutable
            or not self._seed.baseline.contextual_permission_rules_reviewed_by_human
        )
        latest_event = ordered_events[-1] if ordered_events else None
        if baseline_review_pending:
            decision = "ESCALATE"
            if (
                self._seed.baseline.accepted_by_human
                and self._seed.baseline.immutable
                and not self._seed.baseline.contextual_permission_rules_reviewed_by_human
            ):
                next_step = (
                    "Review the baseline-bound adjustment policies separately; every "
                    "policy remains fail-closed review_only."
                )
                reason = (
                    "The human-reviewed daily endpoints are bound to this projection, "
                    "but Contextual Permission adjustment rules have not been reviewed."
                )
            else:
                next_step = (
                    "Review the candidate baseline and resolve every daily endpoint before "
                    "enabling forward adjustment rules."
                )
                reason = (
                    "The Permission bootstrap is available for authoring, but its daily "
                    "itinerary or reviewed inputs are still incomplete."
                )
            advice = ScoutPaceAdvice(
                recommendation_id="advice.bootstrap.review-required",
                recommendation="insufficient_evidence",
                summary=(
                    "Scout will not adjust the forward plan until the baseline gaps "
                    "are reviewed."
                ),
                source_fact_refs=[],
            )
        elif latest_event is None:
            decision = "GO"
            next_step = "Select Replay only when you want to inspect the sealed field example."
            reason = (
                "This is the immutable reviewed baseline. No field event has been merged "
                "into the baseline lens."
            )
            advice = ScoutPaceAdvice(
                recommendation_id="advice.baseline.inspect",
                recommendation="maintain_reduced_pace",
                summary="No forward adjustment is applied in the baseline lens.",
                source_fact_refs=[],
            )
        elif remaining_debt:
            decision = "CHANGE_PLAN"
            next_step = (
                "Open the bounded alternative in Safety / Emergency for human review."
            )
            reason = (
                f"{remaining_debt} minutes of time debt remain after every reviewed "
                "discretionary reduction; protected reserves remain unchanged."
            )
            advice = ScoutPaceAdvice(
                recommendation_id=f"advice.{latest_event.event_id}.alternative-review",
                recommendation="open_alternative_review",
                summary="Scout cannot repay the remaining debt without crossing a reviewed floor.",
                source_fact_refs=[cause.source_ref for cause in latest_event.causes],
                suspended_by_trigger_ref=next(
                    (
                        cause.source_ref
                        for cause in latest_event.causes
                        if cause.source_kind == CauseSourceKind.SAFETY_EMERGENCY_TRIGGER
                    ),
                    None,
                ),
            )
        else:
            decision = "CONDITIONAL_GO"
            next_step = (
                "Inspect the effective remaining plan and keep every protected reserve."
            )
            reason = (
                f"{total_debt} minutes of time debt were applied once to reviewed "
                "discretionary nodes; protected reserves were not spent."
            )
            advice = ScoutPaceAdvice(
                recommendation_id=f"advice.{latest_event.event_id}.reduced-stops",
                recommendation="shorten_discretionary_stops",
                summary="Use the reduced optional stops and preserve the reviewed travel floor.",
                source_fact_refs=[cause.source_ref for cause in latest_event.causes],
                suspended_by_trigger_ref=next(
                    (
                        cause.source_ref
                        for cause in latest_event.causes
                        if cause.source_kind == CauseSourceKind.SAFETY_EMERGENCY_TRIGGER
                    ),
                    None,
                ),
            )
        canonical_events = (
            self._load_all_canonical_events() if projection_lens == "replay" else []
        )
        movement_groups = self._reduce_movement_groups(canonical_events)
        primary_group = next(
            group
            for group in movement_groups
            if group.group_id == self._seed.daily_review.movement_group_id
        )
        session = self.daily_emergency_review(
            primary_group.mission_day_instance_id,
            _skip_projection=True,
        )
        daily_summary = self._daily_summary(session)
        closed_groups = sum(
            group.day_end.completion != "open" for group in movement_groups
        )
        open_groups = len(movement_groups) - closed_groups
        rollup_state = (
            "all_open"
            if closed_groups == 0
            else "all_closed"
            if open_groups == 0
            else "partially_closed"
        )
        stable_payload = {
            "project_id": self.project_id,
            "baseline_sha256": self._seed.baseline.baseline_sha256,
            "event_ids": [event.event_id for event in ordered_events],
            "event_hash": _digest(ordered_events),
            "remaining_plan": [node.model_dump(mode="json") for node in adjusted_nodes],
            "receipt_hashes": [receipt.receipt_sha256 for receipt in session.receipts],
            "canonical_event_hashes": [event.event_sha256 for event in canonical_events],
            "inspection_state": inspection_state,
            "lens": projection_lens,
        }
        group_aggregates = [
            self.canonical_aggregate(group.group_id) for group in movement_groups
        ]
        primary_aggregate = next(
            aggregate
            for aggregate in group_aggregates
            if aggregate.group_id == self._seed.daily_review.movement_group_id
        )
        return ContextualPermissionProjection(
            artifact_kind="contextual_permission_dashboard_projection",
            schema_version="contextualPermissionDashboard.v1",
            project_id=self.project_id,
            projection_sha256=_digest(stable_payload),
            server_now=self._now(),
            status="degraded" if baseline_review_pending else "ready",
            lens=projection_lens,
            available_lenses=["baseline", "replay"],
            lens_notice=(
                "Reviewed baseline bound · adjustment-policy review pending · no runtime session merged"
                if (
                    self._seed.baseline.accepted_by_human
                    and self._seed.baseline.immutable
                    and not self._seed.baseline.contextual_permission_rules_reviewed_by_human
                )
                else "Reference-GPX bootstrap candidate · itinerary review pending · no runtime session merged"
                if baseline_review_pending
                else "Immutable reviewed baseline · no runtime session merged"
                if projection_lens == "baseline"
                else "Sealed candidate replay · not live runtime truth"
            ),
            inspection_state=inspection_state,
            baseline=self._seed.baseline,
            current_decision=CurrentDecision(
                state=current_state,
                decision=decision,
                action_id=latest_event.action_id if latest_event else "continue",
                authorized_duration_minutes=(
                    latest_event.authorized_duration_minutes if latest_event else 0
                ),
                observed_duration_minutes=(
                    latest_event.observed_duration_minutes if latest_event else 0
                ),
                limit_summary=(
                    "Only reviewed discretionary nodes may contract; protected floors stay fixed."
                ),
                reason=reason,
                next_step=next_step,
                confidence=(
                    "low"
                    if baseline_review_pending
                    else "high"
                    if not remaining_debt
                    else "medium"
                ),
            ),
            remaining_plan=adjusted_nodes,
            risk_budget=RiskBudgetLedger(
                time_debt_minutes=total_debt,
                absorbed_debt_minutes=absorbed_debt,
                unabsorbed_debt_minutes=remaining_debt,
                protected_reserves=protected_reserves,
                discretionary_minutes_remaining=discretionary_remaining,
                debt_counted_event_ids=[event.event_id for event in ordered_events],
            ),
            action_events=ordered_events,
            scout_pace_advice=advice,
            daily_review=daily_summary,
            movement_groups=movement_groups,
            expedition_rollup=ExpeditionRollup(
                state=rollup_state,
                group_count=len(movement_groups),
                open_group_count=open_groups,
                closed_group_count=closed_groups,
            ),
            evidence=self._seed.evidence,
            missing_inputs=missing_inputs,
            conflicting_inputs=[],
            day_boundary_policy="destination_receipt_only",
            primary_aggregate=primary_aggregate,
            group_aggregates=group_aggregates,
        )

    def simulate(
        self, request: CandidateSimulationRequest
    ) -> CandidateSimulationResult:
        causes: list[CauseEvidence] = []
        canonical_trigger_hashes = self._canonical_safety_trigger_hashes()
        normalized_automatic_ref_prefixes = {
            CauseSourceKind.WEATHER_FACT: (
                "evidence://weather/",
                "automatic://weather/",
            ),
            CauseSourceKind.MOVEMENT_FACT: (
                "evidence://movement/",
                "automatic://movement/",
                "evidence://imu/",
                "automatic://imu/",
                "evidence://pdr/",
                "automatic://pdr/",
            ),
            CauseSourceKind.GNSS_FACT: (
                "evidence://gnss/",
                "automatic://gnss/",
                "evidence://movement/",
                "automatic://movement/",
            ),
        }
        for cause in request.causes:
            if cause.source_kind == CauseSourceKind.HUMAN_OPERATION:
                raise ContextualPermissionConflict(
                    "verified_safety_trigger_required",
                    "Human-driven causes require a verified Safety / Emergency trigger receipt.",
                )
            automatic_prefixes = normalized_automatic_ref_prefixes.get(
                cause.source_kind
            )
            if automatic_prefixes is not None and not cause.verified:
                raise ContextualPermissionConflict(
                    "verified_automatic_fact_required",
                    "Scout automatic causes require verified normalized evidence.",
                )
            if automatic_prefixes is not None and not cause.source_ref.startswith(
                automatic_prefixes
            ):
                raise ContextualPermissionConflict(
                    "normalized_automatic_fact_required",
                    "Scout automatic causes require a privacy-bounded normalized fact ref.",
                )
            if (
                cause.source_kind == CauseSourceKind.SAFETY_EMERGENCY_TRIGGER
                and (
                    not cause.verified
                    or canonical_trigger_hashes.get(cause.source_ref)
                    != cause.source_sha256
                )
            ):
                raise ContextualPermissionConflict(
                    "verified_safety_trigger_required",
                    "The Safety / Emergency trigger receipt is not canonical or hash-matching.",
                )
            causes.append(
                CauseEvidence(
                    cause_id=cause.cause_id,
                    source_kind=cause.source_kind,
                    source_ref=cause.source_ref,
                    source_sha256=cause.source_sha256,
                    verified=cause.verified,
                )
            )
        debt = max(
            0,
            request.observed_duration_minutes - request.authorized_duration_minutes,
        )
        scenario_payload = request.model_dump(mode="json")
        scenario_sha = _digest(scenario_payload)
        event = ScoutActionEvent(
            event_id=f"simulation.{scenario_sha[:16]}",
            sequence=max((event.sequence for event in self._seed.action_events), default=0),
            action_id=request.action_id,
            status="overrun" if debt else "completed",
            authorized_duration_minutes=request.authorized_duration_minutes,
            observed_duration_minutes=request.observed_duration_minutes,
            debt_minutes=debt,
            causes=causes,
            safety_trigger_locked=any(
                cause.source_kind == CauseSourceKind.SAFETY_EMERGENCY_TRIGGER
                for cause in causes
            ),
        )
        return CandidateSimulationResult(
            artifact_kind="contextual_permission_candidate_simulation",
            schema_version="contextualPermissionSimulation.v1",
            scenario_sha256=scenario_sha,
            projection=self._build_projection(
                events=[event],
                inspection_state="SIMULATION_READY",
                current_state="candidate_simulation",
                projection_lens="replay",
            ),
        )

    def _canonical_safety_trigger_hashes(self) -> dict[str, str]:
        trigger_hashes = {
            cause.source_ref: cause.source_sha256
            for event in self._seed.action_events
            for cause in event.causes
            if cause.source_kind == CauseSourceKind.SAFETY_EMERGENCY_TRIGGER
            and cause.verified
        }
        for event in self._load_all_canonical_events():
            if event.event_kind in {
                "field_conflict_reported",
                "human_day_end_unreachable_reported",
                "night_review_decision_recorded",
            }:
                trigger_hashes[f"event://{event.event_id}"] = event.event_sha256
        return trigger_hashes

    def daily_emergency_review(
        self,
        mission_day_instance_id: str,
        *,
        _skip_projection: bool = False,
    ) -> DailyEmergencyReviewSession:
        del _skip_projection
        seed = self._seed.daily_review
        groups = self._reduce_movement_groups(self._load_all_canonical_events())
        group = next(
            (
                item
                for item in groups
                if item.mission_day_instance_id == mission_day_instance_id
            ),
            None,
        )
        if group is None:
            raise ContextualPermissionConflict(
                "wrong_mission_day",
                "Only a current movement-group mission-day instance can be reviewed.",
            )
        aggregate = self.canonical_aggregate(group.group_id)
        packets: list[NightAlternativePacket] = []
        for packet in (
            item
            for item in seed.alternatives
            if item.movement_group_id == group.group_id
            and item.mission_day_id == group.mission_day_id
        ):
            packet_payload = packet.model_dump(mode="json")
            packet_payload.update(
                {
                    "sha256": "0" * 64,
                    "session_id": aggregate.session_id,
                    "mission_day_id": aggregate.mission_day_id,
                    "mission_day_instance_id": aggregate.mission_day_instance_id,
                    "movement_group_id": aggregate.group_id,
                    "membership_revision": aggregate.membership_revision,
                    "membership_sha256": aggregate.membership_sha256,
                    "review_generation": aggregate.review_generation,
                    "reviewed_sequence": aggregate.through_sequence,
                    "aggregate": aggregate.model_dump(mode="json"),
                }
            )
            packets.append(self._revalidate_night_packet(packet_payload))
        all_receipts = self._load_receipts(group.group_id)
        receipts = [
            receipt
            for receipt in all_receipts
            if receipt.mission_day_instance_id == aggregate.mission_day_instance_id
            and receipt.review_generation == aggregate.review_generation
        ]
        reviewed_alternatives = {receipt.packet_id for receipt in receipts}
        invalidated = any(
            event.event_kind == "daily_review_invalidated"
            and event.sequence > max(
                (
                    receipt.event_sequence
                    for receipt in all_receipts
                    if receipt.mission_day_instance_id
                    == aggregate.mission_day_instance_id
                ),
                default=0,
            )
            for event in self._load_group_events(group.group_id)
        )
        packet_requires_refresh = any(
            packet.freshness_state
            in {"expired", "freshness_unknown", "invalidated"}
            for packet in packets
        )
        if group.day_end.completion != "open":
            state = "day_closed"
        elif invalidated and not receipts:
            state = "re_review_required"
        elif receipts and packet_requires_refresh:
            state = "reviewed_evidence_refresh_required"
        elif not receipts:
            state = "not_started"
        elif len(reviewed_alternatives) < len(packets):
            state = "partially_reviewed"
        else:
            state = "reviewed"
        return seed.model_copy(
            update={
                "mission_day_id": aggregate.mission_day_id,
                "mission_day_instance_id": aggregate.mission_day_instance_id,
                "movement_group_id": aggregate.group_id,
                "membership_revision": aggregate.membership_revision,
                "review_generation": aggregate.review_generation,
                "mission_day_plan_sha256": aggregate.mission_day_plan_sha256,
                "planned_day_end_target_ref": group.day_end.planned_target_ref,
                "planned_day_end_target_sha256": group.day_end.planned_target_sha256,
                "planned_day_end_target_label": group.day_end.planned_target_label,
                "effective_day_end_target_ref": group.day_end.effective_target_ref,
                "effective_day_end_target_sha256": group.day_end.effective_target_sha256,
                "day_end_state": group.day_end.state,
                "alternatives": packets,
                "receipts": receipts,
                "state": state,
                "aggregate": aggregate,
            }
        )

    def _revalidate_night_packet(
        self, packet_payload: dict[str, object]
    ) -> NightAlternativePacket:
        now = self._now()
        raw_gates = list(packet_payload.get("gates") or [])
        gate_by_id = {
            str(item.get("gate_id")): dict(item)
            for item in raw_gates
            if isinstance(item, dict)
        }
        for gate_id in REQUIRED_NIGHT_GATE_IDS:
            gate_by_id.setdefault(
                gate_id,
                {
                    "gate_id": gate_id,
                    "label": gate_id.removeprefix("gate.").replace("_", " / ").title(),
                    "state": "missing",
                    "hard_gate": True,
                    "reason": "Required night-alternative gate is missing.",
                    "source_ref": "missing://night-gate",
                    "source_sha256": _fixed_hash(
                        f"{self.project_id}:{gate_id}:missing"
                    ),
                },
            )
        segment_gate = gate_by_id["gate.segment_policy"]
        if packet_payload.get("requires_daylight") is not False:
            segment_gate.update(
                {
                    "state": "blocked",
                    "reason": "Explicit reviewed requires_daylight=false is required.",
                }
            )
        aggregate = packet_payload.get("aggregate")
        if isinstance(aggregate, dict):
            gate_by_id["gate.runtime_lineage"].update(
                {
                    "source_ref": (
                        f"aggregate://{aggregate.get('group_id')}/"
                        f"{aggregate.get('through_sequence')}"
                    ),
                    "source_sha256": str(
                        aggregate.get("aggregate_sha256") or "0" * 64
                    ),
                }
            )
        gates = [
            EligibilityGate.model_validate(gate_by_id[gate_id])
            for gate_id in REQUIRED_NIGHT_GATE_IDS
        ]
        freshness_inputs = [
            FreshnessInput.model_validate(item)
            for item in list(packet_payload.get("freshness_inputs") or [])
        ]
        required_inputs = [item for item in freshness_inputs if item.required]
        unknown_freshness = any(
            item.valid_until is None for item in required_inputs
        )
        dated_inputs = [
            item for item in required_inputs if item.valid_until is not None
        ]
        driver_input = min(
            dated_inputs,
            key=lambda item: item.valid_until,
            default=None,
        )
        expires_at = driver_input.valid_until if driver_input else None
        invalidated_by = list(packet_payload.get("invalidated_by") or [])
        if invalidated_by:
            freshness_state = "invalidated"
        elif unknown_freshness or expires_at is None:
            freshness_state = "freshness_unknown"
        elif now >= expires_at:
            freshness_state = "expired"
        elif any(
            item.refresh_warning_at is not None
            and now >= item.refresh_warning_at
            for item in required_inputs
        ):
            freshness_state = "refresh_due"
        else:
            freshness_state = "fresh"
        hard_gates_pass = all(
            gate.state == "pass" for gate in gates if gate.hard_gate
        )
        eligibility = (
            "eligible_for_human_review"
            if hard_gates_pass
            and freshness_state in {"fresh", "refresh_due"}
            else "ineligible"
        )
        expiry_driver = (
            ExpiryDriver(
                gate_id=driver_input.gate_id,
                evidence_ref=driver_input.evidence_ref,
                valid_until=driver_input.valid_until,
                reason="Earliest required eligibility evidence deadline.",
            )
            if driver_input is not None and driver_input.valid_until is not None
            else None
        )
        packet_payload.update(
            {
                "sha256": "0" * 64,
                "server_now": now,
                "expires_at": expires_at,
                "freshness_state": freshness_state,
                "expiry_driver": (
                    expiry_driver.model_dump(mode="json")
                    if expiry_driver is not None
                    else None
                ),
                "eligibility": eligibility,
                "approval_granted": False,
                "gates": [gate.model_dump(mode="json") for gate in gates],
            }
        )
        normalized = NightAlternativePacket.model_validate(packet_payload)
        normalized_sha256 = _packet_hash(normalized.model_dump(mode="json"))
        return normalized.model_copy(update={"sha256": normalized_sha256})

    def rebuild_packet_hash(self, packet: NightAlternativePacket) -> str:
        return _packet_hash(packet.model_dump(mode="json"))

    def _daily_summary(
        self, session: DailyEmergencyReviewSession
    ) -> DailyReviewSummary:
        latest = session.receipts[-1] if session.receipts else None
        selected_state = (
            {
                EmergencyReviewDecision.SELECT_HOLD_OR_BIVY: (
                    "hold_or_bivy_selected"
                ),
                EmergencyReviewDecision.REJECT_NIGHT_TRAVEL: "rejected",
                EmergencyReviewDecision.APPROVE_FOR_RUNTIME_CONSIDERATION: (
                    "consideration_reviewed"
                ),
                EmergencyReviewDecision.ESCALATE_EMERGENCY: "escalated",
            }.get(latest.decision, "not_reviewed")
            if latest
            else "not_reviewed"
        )
        return DailyReviewSummary(
            mission_day_id=session.mission_day_id,
            mission_day_instance_id=session.mission_day_instance_id,
            state=session.state,
            reviewed_count=len({receipt.packet_id for receipt in session.receipts}),
            alternative_count=len(session.alternatives),
            selected_alternative_state=selected_state,
            review_generation=session.review_generation,
        )

    def record_night_decision(
        self, request: EmergencyReviewDecisionRequest
    ) -> EmergencyReviewReceipt:
        if not request.explicit_confirmation:
            raise ContextualPermissionConflict(
                "explicit_confirmation_required",
                "The second, consequence-labelled confirmation is required.",
            )
        request_sha = _digest(request)
        context = request.command_context
        if context is None:
            aggregate = self.canonical_aggregate(
                self._seed.daily_review.movement_group_id
            )
            context = CanonicalCommandContext(
                session_id=aggregate.session_id,
                group_id=aggregate.group_id,
                mission_day_instance_id=aggregate.mission_day_instance_id,
                membership_revision=aggregate.membership_revision,
                expected_baseline_sha256=aggregate.baseline_sha256,
                expected_aggregate_sha256=aggregate.aggregate_sha256,
                expected_sequence=aggregate.through_sequence,
                idempotency_key=request.idempotency_key or "missing-idempotency-key",
            )
        with _STORE_LOCK:
            existing_event = next(
                (
                    event
                    for event in self._load_group_events(context.group_id)
                    if event.idempotency_key == context.idempotency_key
                ),
                None,
            )
            if existing_event is not None:
                if (
                    existing_event.event_kind != "night_review_decision_recorded"
                    or existing_event.payload.get("request_sha256") != request_sha
                ):
                    raise ContextualPermissionConflict(
                        "idempotency_conflict",
                        "The idempotency key was already used for another decision.",
                    )
                return self._receipt_from_event(existing_event)
            existing_receipt = next(
                (
                    receipt
                    for receipt in self._load_receipts(context.group_id)
                    if receipt.packet_id == request.packet_id
                    and receipt.review_generation == request.review_generation
                )
                ,
                None,
            )
            if existing_receipt is not None:
                raise ContextualPermissionConflict(
                    "already_decided",
                    "This exact alternative already has a decision for the review generation.",
                )
            packet = self._current_packet(
                request.packet_id, request.mission_day_instance_id
            )
            self._validate_packet_request(packet, request, context=context)
            event = self._append_canonical_event(
                context=context,
                event_kind="night_review_decision_recorded",
                payload={
                    "request_sha256": request_sha,
                    "packet_id": request.packet_id,
                    "packet_sha256": request.packet_sha256,
                    "reviewed_envelope_sha256": packet.reviewed_envelope_sha256,
                    "mission_day_id": packet.mission_day_id,
                    "mission_day_instance_id": packet.mission_day_instance_id,
                    "movement_group_id": packet.movement_group_id,
                    "membership_revision": packet.membership_revision,
                    "review_generation": packet.review_generation,
                    "reviewed_sequence": packet.reviewed_sequence,
                    "decision": request.decision,
                    "reviewer_alias": request.reviewer_alias,
                    "aggregate_sha256_before": context.expected_aggregate_sha256,
                },
            )
            return self._receipt_from_event(event)

    def invalidate_daily_review(
        self, request: DailyReviewInvalidationRequest
    ) -> CanonicalEvent:
        if len(request.source_refs) != len(request.source_hashes):
            raise ContextualPermissionConflict(
                "daily_review_lineage_mismatch",
                "Daily-review invalidation refs and hashes must have equal length.",
            )
        if not request.reviewed_envelope_crossed:
            raise ContextualPermissionConflict(
                "routine_refresh_does_not_invalidate_daily_review",
                "Routine in-envelope evidence refresh must rebuild eligibility without renewing human review.",
            )
        if request.reason_kind == "safety_emergency_trigger":
            if not request.explicit_confirmation or not request.reporter_alias:
                raise ContextualPermissionConflict(
                    "verified_safety_trigger_required",
                    "Human-driven invalidation requires a confirmed Safety / Emergency trigger receipt.",
                )
        elif request.explicit_confirmation:
            raise ContextualPermissionConflict(
                "automatic_fact_confirmation_forbidden",
                "Automatic out-of-envelope evidence is not a human attestation.",
            )
        return self._append_canonical_event(
            context=request.command_context,
            event_kind="daily_review_invalidated",
            payload={
                "reason_kind": request.reason_kind,
                "source_refs": request.source_refs,
                "source_hashes": request.source_hashes,
                "reviewed_envelope_crossed": True,
                "reporter_alias": request.reporter_alias,
                "prior_receipts_preserved": True,
            },
        )

    def sync_offline_intent(
        self, intent: OfflineEmergencyReviewIntent
    ) -> OfflineIntentSyncResult:
        if not intent.pending_sync:
            raise ContextualPermissionConflict(
                "pending_sync_required", "Offline intent must declare pending_sync=true."
            )
        if not intent.device_local_encrypted:
            raise ContextualPermissionConflict(
                "encrypted_offline_intent_required",
                "Offline intent must originate from encrypted device-local storage.",
            )
        packet = self._current_packet(
            intent.packet_id, intent.mission_day_instance_id
        )
        aggregate = self.canonical_aggregate(packet.movement_group_id)
        existing_sync_event = next(
            (
                event
                for event in self._load_group_events(aggregate.group_id)
                if event.idempotency_key == intent.idempotency_key
            ),
            None,
        )
        if existing_sync_event is not None:
            same_intent = (
                existing_sync_event.payload.get("decision") == intent.decision
                and (
                    existing_sync_event.payload.get("packet_id") == intent.packet_id
                    or existing_sync_event.payload.get("intent_id") == intent.intent_id
                )
            )
            if not same_intent:
                raise ContextualPermissionConflict(
                    "idempotency_conflict",
                    "The offline-sync idempotency key was used for another intent.",
                )
            if existing_sync_event.event_kind == "night_review_decision_recorded":
                receipt = self._receipt_from_event(existing_sync_event)
                return OfflineIntentSyncResult(
                    status="already_recorded",
                    receipt_ref=(
                        f"event://{existing_sync_event.group_id}/"
                        f"{existing_sync_event.sequence}"
                    ),
                    receipt_sha256=receipt.receipt_sha256,
                    audit_ref=None,
                    reasons=[],
                )
            return OfflineIntentSyncResult(
                status="rejected_sync_audit",
                receipt_ref=None,
                receipt_sha256=None,
                audit_ref=(
                    f"event://{existing_sync_event.group_id}/"
                    f"{existing_sync_event.sequence}"
                ),
                reasons=[str(existing_sync_event.payload.get("reason_code") or "rejected")],
            )
        context = CanonicalCommandContext(
            session_id=aggregate.session_id,
            group_id=aggregate.group_id,
            mission_day_instance_id=aggregate.mission_day_instance_id,
            membership_revision=aggregate.membership_revision,
            expected_baseline_sha256=aggregate.baseline_sha256,
            expected_aggregate_sha256=aggregate.aggregate_sha256,
            expected_sequence=aggregate.through_sequence,
            idempotency_key=intent.idempotency_key,
        )
        if intent.decision == EmergencyReviewDecision.APPROVE_FOR_RUNTIME_CONSIDERATION:
            audit = self._append_canonical_event(
                context=context,
                event_kind="offline_intent_sync_rejected",
                payload={
                    "intent_id": intent.intent_id,
                    "decision": intent.decision,
                    "reason_code": "offline_approval_forbidden",
                    "supersedes_intent_id": intent.supersedes_intent_id,
                    "pending_sync": False,
                    "canonical_receipt_appended": False,
                },
            )
            return OfflineIntentSyncResult(
                status="rejected_sync_audit",
                receipt_ref=None,
                receipt_sha256=None,
                audit_ref=f"event://{audit.group_id}/{audit.sequence}",
                reasons=["offline_approval_forbidden"],
            )
        request = EmergencyReviewDecisionRequest(
            command_context=context,
            packet_id=intent.packet_id,
            packet_sha256=intent.packet_sha256,
            mission_day_instance_id=intent.mission_day_instance_id,
            review_generation=intent.review_generation,
            reviewed_sequence=intent.reviewed_sequence,
            decision=intent.decision,
            reviewer_alias=intent.reviewer_alias,
            explicit_confirmation=True,
        )
        existed = any(
            event.idempotency_key == intent.idempotency_key
            for event in self._load_group_events(aggregate.group_id)
        )
        try:
            receipt = self.record_night_decision(request)
        except ContextualPermissionConflict as exc:
            audit_context = context
            current = self.canonical_aggregate(context.group_id)
            if current.aggregate_sha256 != context.expected_aggregate_sha256:
                audit_context = context.model_copy(
                    update={
                        "mission_day_instance_id": current.mission_day_instance_id,
                        "membership_revision": current.membership_revision,
                        "expected_aggregate_sha256": current.aggregate_sha256,
                        "expected_sequence": current.through_sequence,
                    }
                )
            audit = self._append_canonical_event(
                context=audit_context,
                event_kind="offline_intent_sync_rejected",
                payload={
                    "intent_id": intent.intent_id,
                    "decision": intent.decision,
                    "reason_code": exc.code,
                    "supersedes_intent_id": intent.supersedes_intent_id,
                    "pending_sync": False,
                    "canonical_receipt_appended": False,
                },
            )
            return OfflineIntentSyncResult(
                status="rejected_sync_audit",
                receipt_ref=None,
                receipt_sha256=None,
                audit_ref=f"event://{audit.group_id}/{audit.sequence}",
                reasons=[exc.code],
            )
        return OfflineIntentSyncResult(
            status="already_recorded" if existed else "receipt_appended",
            receipt_ref=f"event://{aggregate.group_id}/{receipt.event_sequence}",
            receipt_sha256=receipt.receipt_sha256,
            audit_ref=None,
            reasons=[],
        )

    def _existing_offline_sync_result(
        self,
        *,
        group_id: str,
        idempotency_key: str,
        success_event_kinds: set[str],
    ) -> OfflineIntentSyncResult | None:
        existing = next(
            (
                event
                for event in self._load_group_events(group_id)
                if event.idempotency_key == idempotency_key
            ),
            None,
        )
        if existing is None:
            return None
        if existing.event_kind in success_event_kinds:
            return OfflineIntentSyncResult(
                status="already_recorded",
                receipt_ref=f"event://{existing.group_id}/{existing.sequence}",
                receipt_sha256=existing.event_sha256,
                audit_ref=None,
                reasons=[],
            )
        if existing.event_kind.endswith("_sync_rejected"):
            return OfflineIntentSyncResult(
                status="rejected_sync_audit",
                receipt_ref=None,
                receipt_sha256=None,
                audit_ref=f"event://{existing.group_id}/{existing.sequence}",
                reasons=[str(existing.payload.get("reason_code") or "rejected")],
            )
        raise ContextualPermissionConflict(
            "idempotency_conflict",
            "The offline-sync idempotency key was used for another command.",
        )

    def _record_offline_sync_rejection(
        self,
        *,
        original_context: CanonicalCommandContext,
        intent_id: str,
        event_kind: str,
        reason_code: str,
    ) -> OfflineIntentSyncResult:
        aggregate = self.canonical_aggregate(original_context.group_id)
        current_context = CanonicalCommandContext(
            session_id=aggregate.session_id,
            group_id=aggregate.group_id,
            mission_day_instance_id=aggregate.mission_day_instance_id,
            membership_revision=aggregate.membership_revision,
            expected_baseline_sha256=aggregate.baseline_sha256,
            expected_aggregate_sha256=aggregate.aggregate_sha256,
            expected_sequence=aggregate.through_sequence,
            idempotency_key=original_context.idempotency_key,
        )
        audit = self._append_canonical_event(
            context=current_context,
            event_kind=event_kind,
            payload={
                "intent_id": intent_id,
                "reason_code": reason_code,
                "pending_sync": False,
                "canonical_receipt_appended": False,
                "original_expected_aggregate_sha256": (
                    original_context.expected_aggregate_sha256
                ),
                "original_expected_sequence": original_context.expected_sequence,
            },
        )
        return OfflineIntentSyncResult(
            status="rejected_sync_audit",
            receipt_ref=None,
            receipt_sha256=None,
            audit_ref=f"event://{audit.group_id}/{audit.sequence}",
            reasons=[reason_code],
        )

    def sync_offline_day_end_intent(
        self, intent: OfflineDayEndIntent
    ) -> OfflineIntentSyncResult:
        existing = self._existing_offline_sync_result(
            group_id=intent.command_context.group_id,
            idempotency_key=intent.idempotency_key,
            success_event_kinds={"day_end_closed"},
        )
        if existing is not None:
            return existing
        try:
            event = self.confirm_day_end(
                ManualDayEndConfirmationRequest(
                    command_context=intent.command_context,
                    target_ref=intent.target_ref,
                    target_sha256=intent.target_sha256,
                    target_label=intent.target_label,
                    target_kind=intent.target_kind,
                    confirmation_kind=intent.confirmation_kind,
                    authorized_on_site_participant=(
                        intent.authorized_on_site_participant
                    ),
                    participant_alias=intent.participant_alias,
                    explicit_confirmation=intent.explicit_confirmation,
                    uncertainty_acknowledgement=(
                        intent.uncertainty_acknowledgement
                    ),
                )
            )
        except ContextualPermissionConflict as exc:
            return self._record_offline_sync_rejection(
                original_context=intent.command_context,
                intent_id=intent.intent_id,
                event_kind="offline_day_end_intent_sync_rejected",
                reason_code=exc.code,
            )
        return OfflineIntentSyncResult(
            status="receipt_appended",
            receipt_ref=f"event://{event.group_id}/{event.sequence}",
            receipt_sha256=event.event_sha256,
            audit_ref=None,
            reasons=[],
        )

    def sync_offline_field_conflict_intent(
        self, intent: OfflineFieldConflictIntent
    ) -> OfflineIntentSyncResult:
        existing = self._existing_offline_sync_result(
            group_id=intent.command_context.group_id,
            idempotency_key=intent.idempotency_key,
            success_event_kinds={"field_conflict_reported"},
        )
        if existing is not None:
            return existing
        try:
            event = self.report_field_conflict(
                FieldConflictRequest(
                    command_context=intent.command_context,
                    checklist_id=intent.checklist_id,
                    row_id=intent.row_id,
                    category=intent.category,
                    affected_fact_refs=intent.affected_fact_refs,
                    affected_fact_hashes=intent.affected_fact_hashes,
                    reporter_alias=intent.reporter_alias,
                    optional_note=intent.optional_note,
                    explicit_confirmation=intent.explicit_confirmation,
                )
            )
        except ContextualPermissionConflict as exc:
            return self._record_offline_sync_rejection(
                original_context=intent.command_context,
                intent_id=intent.intent_id,
                event_kind="offline_field_conflict_intent_sync_rejected",
                reason_code=exc.code,
            )
        return OfflineIntentSyncResult(
            status="receipt_appended",
            receipt_ref=f"event://{event.group_id}/{event.sequence}",
            receipt_sha256=event.event_sha256,
            audit_ref=None,
            reasons=[],
        )

    def sync_offline_movement_group_intent(
        self, intent: OfflineMovementGroupIntent
    ) -> OfflineIntentSyncResult:
        success_kinds = (
            {"movement_group_formed"}
            if intent.intent_kind == "formation"
            else {"movement_group_membership_revised"}
        )
        existing = self._existing_offline_sync_result(
            group_id=intent.command_context.group_id,
            idempotency_key=intent.idempotency_key,
            success_event_kinds=success_kinds,
        )
        if existing is not None:
            return existing
        try:
            if intent.intent_kind == "formation":
                event = self.form_movement_group(
                    MovementGroupFormationRequest(
                        command_context=intent.command_context,
                        new_group_id=str(intent.new_group_id),
                        display_name=str(intent.display_name),
                        formation_kind=str(intent.formation_kind),
                        participant_refs_hash=intent.participant_refs_hash,
                        coordinator_ref=intent.coordinator_ref,
                        mission_day_id=str(intent.mission_day_id),
                        mission_day_instance_id=str(
                            intent.mission_day_instance_id
                        ),
                        target_ref=str(intent.target_ref),
                        target_sha256=str(intent.target_sha256),
                        shared_dependency_refs=intent.shared_dependency_refs,
                        shared_dependency_hashes=intent.shared_dependency_hashes,
                        reporter_alias=intent.reporter_alias,
                        explicit_confirmation=intent.explicit_confirmation,
                    )
                )
            else:
                event = self.revise_movement_group(
                    MovementGroupRevisionRequest(
                        command_context=intent.command_context,
                        expected_membership_sha256=str(
                            intent.expected_membership_sha256
                        ),
                        participant_refs_hash=intent.participant_refs_hash,
                        coordinator_ref=intent.coordinator_ref,
                        reporter_alias=intent.reporter_alias,
                        explicit_confirmation=intent.explicit_confirmation,
                    )
                )
        except ContextualPermissionConflict as exc:
            return self._record_offline_sync_rejection(
                original_context=intent.command_context,
                intent_id=intent.intent_id,
                event_kind="offline_movement_group_intent_sync_rejected",
                reason_code=exc.code,
            )
        return OfflineIntentSyncResult(
            status="receipt_appended",
            receipt_ref=f"event://{event.group_id}/{event.sequence}",
            receipt_sha256=event.event_sha256,
            audit_ref=None,
            reasons=[],
        )

    def _current_group_projection(self, group_id: str) -> MovementGroupProjection:
        group = next(
            (
                item
                for item in self._reduce_movement_groups(
                    self._load_all_canonical_events()
                )
                if item.group_id == group_id
            ),
            None,
        )
        if group is None:
            raise ContextualPermissionConflict(
                "movement_group_not_found", "The movement group is not current."
            )
        return group

    def record_arrival_observation(
        self, request: ArrivalDwellObservationRequest
    ) -> CanonicalEvent:
        group = self._current_group_projection(request.command_context.group_id)
        is_emergency_bivy = group.day_end.state == "emergency_bivy_selected"
        expected_ref = (
            group.day_end.effective_target_ref
            if is_emergency_bivy
            else group.day_end.planned_target_ref
        )
        expected_sha = (
            group.day_end.effective_target_sha256
            if is_emergency_bivy
            else group.day_end.planned_target_sha256
        )
        expected_label = (
            group.day_end.effective_target_label
            if is_emergency_bivy
            else group.day_end.planned_target_label
        )
        if request.target_ref != expected_ref:
            raise ContextualPermissionConflict(
                "target_mismatch", "Arrival evidence does not match the reviewed target."
            )
        if request.target_sha256 != expected_sha:
            raise ContextualPermissionConflict(
                "target_mismatch", "Arrival target hash does not match the reviewed target."
            )
        blocked_by = []
        if not request.target_match:
            blocked_by.append("Reviewed arrival target does not match.")
        if not request.route_progress_match:
            blocked_by.append("Route progress does not match the reviewed target.")
        if request.gnss_confidence not in {"high", "medium"}:
            blocked_by.append("GNSS confidence is insufficient for automatic close.")
        if request.zone_exit:
            blocked_by.append("Positive reviewed-zone exit evidence is present.")
        if request.continued_route_travel:
            blocked_by.append("Continued route travel is present.")
        if request.unexpected_separation:
            blocked_by.append("Unexpected same-group separation is present.")
        if request.elapsed_seconds < group.arrival_dwell.elapsed_seconds:
            raise ContextualPermissionConflict(
                "non_monotonic_dwell", "Arrival dwell cannot move backwards."
            )
        if request.elapsed_seconds >= group.arrival_dwell.required_seconds and not blocked_by:
            return self._append_canonical_event(
                context=request.command_context,
                event_kind="day_end_closed",
                payload={
                    "target_ref": request.target_ref,
                    "target_sha256": request.target_sha256,
                    "target_label": expected_label,
                    "target_kind": (
                        "emergency_bivy" if is_emergency_bivy else "planned_day_end"
                    ),
                    "confirmation_mode": "automatic_gnss_dwell",
                    "elapsed_seconds": request.elapsed_seconds,
                    "evidence_refs": [
                        "normalized://gnss/reviewed-zone-entry",
                        "normalized://movement/route-progress-match",
                    ],
                    "pending_next_day": self._next_day_id(group.mission_day_id),
                },
            )
        return self._append_canonical_event(
            context=request.command_context,
            event_kind="arrival_dwell_observed",
            payload={
                "target_ref": request.target_ref,
                "target_sha256": request.target_sha256,
                "elapsed_seconds": request.elapsed_seconds,
                "target_match": request.target_match,
                "route_progress_match": request.route_progress_match,
                "gnss_confidence": request.gnss_confidence,
                "blocked_by": blocked_by,
            },
        )

    def _next_day_id(self, mission_day_id: str) -> str:
        match = re.fullmatch(r"D(\d+)", mission_day_id)
        if match is None:
            raise ContextualPermissionConflict(
                "invalid_mission_day", "Mission day must use the D_n vocabulary."
            )
        return f"D{int(match.group(1)) + 1}"

    def report_field_conflict(
        self, request: FieldConflictRequest
    ) -> CanonicalEvent:
        if not request.explicit_confirmation:
            raise ContextualPermissionConflict(
                "explicit_confirmation_required",
                "The consequence-labelled conflict action is required.",
            )
        if len(request.affected_fact_refs) != len(request.affected_fact_hashes):
            raise ContextualPermissionConflict(
                "field_conflict_lineage_mismatch",
                "Affected fact refs and hashes must have the same length.",
            )
        group = self._current_group_projection(request.command_context.group_id)
        checklist = group.departure_checklist
        if request.checklist_id != checklist.checklist_id:
            raise ContextualPermissionConflict(
                "checklist_replaced", "The departure checklist has changed."
            )
        row = next((item for item in checklist.rows if item.row_id == request.row_id), None)
        if row is None or not row.field_condition_differs_available:
            raise ContextualPermissionConflict(
                "field_conflict_not_available",
                "This checklist row has no automatic-fact conflict path.",
            )
        evidence_pairs = dict(
            zip(request.affected_fact_refs, request.affected_fact_hashes, strict=True)
        )
        if (
            row.evidence_ref is None
            or row.evidence_sha256 is None
            or evidence_pairs.get(row.evidence_ref) != row.evidence_sha256
        ):
            raise ContextualPermissionConflict(
                "field_conflict_lineage_mismatch",
                "The field conflict must bind the current row evidence ref and hash.",
            )
        return self._append_canonical_event(
            context=request.command_context,
            event_kind="field_conflict_reported",
            payload={
                "checklist_id": checklist.checklist_id,
                "checklist_sha256": checklist.checklist_sha256,
                "row_id": request.row_id,
                "category": request.category,
                "affected_fact_refs": request.affected_fact_refs,
                "affected_fact_hashes": request.affected_fact_hashes,
                "optional_bounded_note": request.optional_note,
                "reporter_alias": request.reporter_alias,
                "privacy": "bounded_refs_only",
                "human_cause_receipt": True,
            },
        )

    def resolve_field_conflict(
        self, request: FieldConflictResolutionRequest
    ) -> CanonicalEvent:
        if not request.explicit_confirmation:
            raise ContextualPermissionConflict(
                "explicit_confirmation_required", "Conflict resolution must be confirmed."
            )
        if not request.fresh_evidence_refs or not request.fresh_evidence_hashes:
            raise ContextualPermissionConflict(
                "fresh_evidence_required",
                "Fresh affected evidence is required before conflict resolution.",
            )
        if len(request.fresh_evidence_refs) != len(request.fresh_evidence_hashes):
            raise ContextualPermissionConflict(
                "field_conflict_lineage_mismatch",
                "Fresh evidence refs and hashes must have the same length.",
            )
        if not request.leader_confirms_field_conflict_cleared:
            raise ContextualPermissionConflict(
                "field_conflict_still_open",
                "The direct field conflict remains open.",
            )
        conflict = next(
            (
                event
                for event in self._load_group_events(request.command_context.group_id)
                if event.event_id == request.conflict_event_id
                and event.event_kind == "field_conflict_reported"
            ),
            None,
        )
        if conflict is None or conflict.payload.get("row_id") != request.row_id:
            raise ContextualPermissionConflict(
                "field_conflict_not_found", "The field conflict is not current."
            )
        already_resolved = any(
            event.event_kind == "field_conflict_resolved"
            and event.payload.get("conflict_event_id") == request.conflict_event_id
            for event in self._load_group_events(request.command_context.group_id)
        )
        if already_resolved:
            raise ContextualPermissionConflict(
                "field_conflict_already_resolved", "The field conflict is already resolved."
            )
        return self._append_canonical_event(
            context=request.command_context,
            event_kind="field_conflict_resolved",
            payload={
                "conflict_event_id": request.conflict_event_id,
                "row_id": request.row_id,
                "fresh_evidence_refs": request.fresh_evidence_refs,
                "fresh_evidence_hashes": request.fresh_evidence_hashes,
                "reviewer_alias": request.reviewer_alias,
                "resolution_state": "resolved_consistent",
                "deterministic_gate_rebuilt": True,
            },
        )

    def record_individual_activity(
        self, request: IndividualActionTransitionRequest
    ) -> CanonicalEvent:
        if request.participant_ref.startswith("person://"):
            raise ContextualPermissionConflict(
                "pseudonymous_participant_required",
                "Dashboard activity records require a pseudonymous participant ref.",
            )
        return self._append_canonical_event(
            context=request.command_context,
            event_kind="individual_activity_transitioned",
            payload={
                "participant_ref": request.participant_ref,
                "device_ref": request.device_ref,
                "activity_episode_id": request.activity_episode_id,
                "prior_state": request.prior_state,
                "new_state": request.new_state,
                "transition_kind": request.transition_kind,
                "confidence": request.confidence,
                "freshness": request.freshness,
                "evidence_hashes": request.evidence_hashes,
                "self_correction": request.self_correction,
                "raw_sensor_data_exposed": False,
            },
        )

    def start_mission_day(self, request: DepartureStartRequest) -> CanonicalEvent:
        if not request.explicit_confirmation:
            raise ContextualPermissionConflict(
                "explicit_confirmation_required", "Mission-day start must be confirmed."
            )
        group = self._current_group_projection(request.command_context.group_id)
        checklist = group.departure_checklist
        if request.checklist_id != checklist.checklist_id:
            raise ContextualPermissionConflict(
                "checklist_replaced", "The departure checklist has changed."
            )
        if request.checklist_sha256 != checklist.checklist_sha256:
            raise ContextualPermissionConflict(
                "checklist_replaced", "The departure checklist hash has changed."
            )
        if request.pending_day_plan_sha256 != checklist.pending_day_plan_sha256:
            raise ContextualPermissionConflict(
                "pending_day_plan_mismatch", "The pending day plan has changed."
            )
        if request.pending_mission_day_id != group.pending_next_day:
            raise ContextualPermissionConflict(
                "pending_mission_day_mismatch", "The pending mission day has changed."
            )
        blockers = []
        if group.shelter_hold.state not in {
            "departure_review_candidate",
            "ready_to_resume",
        }:
            blockers.append("Shelter Hold is not ready for departure review.")
        if checklist.open_conflict_count:
            blockers.append("A leader field conflict remains open.")
        effective_rows = []
        for row in checklist.rows:
            if row.state in {"blocked", "unknown"}:
                blockers.append(f"{row.label}: {row.blocker or row.state}")
                effective_rows.append(row)
            elif row.state == "leader_check_required":
                if request.leader_attestations.get(row.row_id) is not True:
                    blockers.append(f"{row.label}: leader attestation required")
                effective_rows.append(
                    row.model_copy(
                        update={
                            "state": (
                                "pass"
                                if request.leader_attestations.get(row.row_id) is True
                                else row.state
                            )
                        }
                    )
                )
            else:
                effective_rows.append(row)
        if blockers:
            raise ContextualPermissionConflict(
                "departure_checklist_blocked",
                "Mission day not started: " + "; ".join(blockers),
            )
        return self._append_canonical_event(
            context=request.command_context,
            event_kind="mission_day_started",
            payload={
                "checklist_id": checklist.checklist_id,
                "checklist_sha256": checklist.checklist_sha256,
                "pending_mission_day_id": request.pending_mission_day_id,
                "pending_day_plan_sha256": request.pending_day_plan_sha256,
                "leader_attestations": request.leader_attestations,
                "reviewer_alias": request.reviewer_alias,
                "next_mission_day_instance_id": (
                    f"{request.pending_mission_day_id}.instance."
                    f"{request.command_context.group_id}.{request.command_context.expected_sequence + 1}"
                ),
                "runtime_authorization_performed": False,
            },
        )

    def record_communication_event(
        self, request: CommunicationEventRequest
    ) -> CanonicalEvent:
        group = self._current_group_projection(request.command_context.group_id)
        current = group.communication
        if request.communication_policy_id != current.policy_id:
            raise ContextualPermissionConflict(
                "communication_policy_mismatch", "The communication policy has changed."
            )
        if request.communication_policy_sha256 != current.policy_sha256:
            raise ContextualPermissionConflict(
                "communication_policy_mismatch", "The communication policy hash has changed."
            )
        if request.event_kind == "forward_window_adjusted":
            if request.retroactive or current.contact_overdue:
                raise ContextualPermissionConflict(
                    "retroactive_window_adjustment_forbidden",
                    "A communication window cannot be extended retroactively.",
                )
            if (
                not request.new_effective_window
                or not request.adjustment_event_ref
                or not request.adjustment_event_sha256
            ):
                raise ContextualPermissionConflict(
                    "reviewed_window_adjustment_required",
                    "A reviewed forward event and effective window are required.",
                )
            event_kind = "communication_window_adjusted"
        elif request.event_kind in {"verified_check_in", "contact_restored"}:
            if not (request.acknowledged_receipt_ref or "").startswith("receipt://"):
                raise ContextualPermissionConflict(
                    "acknowledged_receipt_required",
                    "Only an acknowledged receipt proves group check-in.",
                )
            event_kind = (
                "communication_check_in_verified"
                if request.event_kind == "verified_check_in"
                else "communication_contact_restored"
            )
        else:
            if not request.route_scope_match:
                raise ContextualPermissionConflict(
                    "communication_route_scope_mismatch",
                    "The reviewed blackout/window scope no longer matches progress.",
                )
            event_kind = "communication_deadline_elapsed"
        return self._append_canonical_event(
            context=request.command_context,
            event_kind=event_kind,
            payload={
                "communication_policy_id": request.communication_policy_id,
                "communication_policy_sha256": request.communication_policy_sha256,
                "route_scope_match": request.route_scope_match,
                "acknowledged_receipt_ref": request.acknowledged_receipt_ref,
                "compound_evidence_refs": request.compound_evidence_refs,
                "retroactive": request.retroactive,
                "new_effective_window": request.new_effective_window,
                "adjustment_event_ref": request.adjustment_event_ref,
                "adjustment_event_sha256": request.adjustment_event_sha256,
                "reviewer_alias": request.reviewer_alias,
                "explicit_confirmation": request.explicit_confirmation,
            },
        )

    def review_contact_loss(
        self, request: ContactLossReviewRequest
    ) -> CanonicalEvent:
        if not request.explicit_confirmation:
            raise ContextualPermissionConflict(
                "explicit_confirmation_required",
                "Contact-loss review must be explicitly confirmed.",
            )
        group = self._current_group_projection(request.command_context.group_id)
        communication = group.communication
        if (
            request.communication_policy_id != communication.policy_id
            or request.communication_policy_sha256 != communication.policy_sha256
        ):
            raise ContextualPermissionConflict(
                "communication_policy_mismatch",
                "The reviewed communication policy has changed.",
            )
        if not communication.contact_overdue:
            raise ContextualPermissionConflict(
                "contact_overdue_required",
                "Contact-loss review requires a current automatic overdue fact.",
            )
        if (
            request.decision == "escalate_emergency_call_out"
            and not request.compound_evidence_refs
            and not request.safety_emergency_trigger_refs
        ):
            raise ContextualPermissionConflict(
                "contact_escalation_basis_required",
                "Missed contact alone cannot create an emergency escalation candidate.",
            )
        return self._append_canonical_event(
            context=request.command_context,
            event_kind="contact_loss_review_recorded",
            payload={
                "communication_policy_id": request.communication_policy_id,
                "communication_policy_sha256": (
                    request.communication_policy_sha256
                ),
                "decision": request.decision,
                "overdue_fact_refs": request.overdue_fact_refs,
                "overdue_fact_hashes": request.overdue_fact_hashes,
                "compound_evidence_refs": request.compound_evidence_refs,
                "compound_evidence_hashes": request.compound_evidence_hashes,
                "safety_emergency_trigger_refs": (
                    request.safety_emergency_trigger_refs
                ),
                "safety_emergency_trigger_hashes": (
                    request.safety_emergency_trigger_hashes
                ),
                "reviewer_alias": request.reviewer_alias,
                "emergency_declared": False,
                "emergency_call_out_opened": False,
                "outbound_transport_invoked": False,
                "external_send_performed": False,
            },
        )

    def group_communication_projection(self, group_id: str) -> dict[str, object]:
        group = self._current_group_projection(group_id)
        return {
            "artifact_kind": "movement_group_communication_projection",
            "schema_version": "movementGroupCommunicationProjection.v1",
            "project_id": self.project_id,
            "movement_group_id": group.group_id,
            "membership_revision": group.membership_revision,
            "membership_sha256": group.membership_sha256,
            "mission_day_instance_id": group.mission_day_instance_id,
            "communication": group.communication.model_dump(mode="json"),
            "aggregate": self.canonical_aggregate(group_id).model_dump(mode="json"),
            "candidate_only": True,
            "runtime_safety_truth": False,
            "authority": AuthorityBoundary().model_dump(mode="json"),
        }

    def communication_rollup(self) -> dict[str, object]:
        groups = self._reduce_movement_groups(self._load_all_canonical_events())
        return {
            "artifact_kind": "movement_group_communication_rollup",
            "schema_version": "movementGroupCommunicationRollup.v1",
            "project_id": self.project_id,
            "groups": [
                {
                    "movement_group_id": group.group_id,
                    "group_label": group.group_label,
                    "membership_revision": group.membership_revision,
                    "state": group.communication.state,
                    "viewpoint": group.communication.viewpoint,
                    "local_group_contact_state": (
                        group.communication.local_group_contact_state
                    ),
                    "remote_observed_contact_state": (
                        group.communication.remote_observed_contact_state
                    ),
                    "next_check_in_target": (
                        group.communication.next_check_in_target
                    ),
                    "effective_window": group.communication.effective_window,
                    "contact_overdue": group.communication.contact_overdue,
                    "emergency_declared": False,
                }
                for group in groups
            ],
            "candidate_only": True,
            "runtime_safety_truth": False,
            "authority": AuthorityBoundary().model_dump(mode="json"),
        }

    def form_movement_group(
        self, request: MovementGroupFormationRequest
    ) -> CanonicalEvent:
        if not request.explicit_confirmation:
            raise ContextualPermissionConflict(
                "explicit_confirmation_required", "Movement-group formation must be confirmed."
            )
        if any(
            group.group_id == request.new_group_id
            for group in self._reduce_movement_groups(self._load_all_canonical_events())
        ):
            raise ContextualPermissionConflict(
                "movement_group_already_exists", "The movement group already exists."
            )
        if not _SAFE_ID_PATTERN.fullmatch(request.new_group_id):
            raise ContextualPermissionConflict(
                "invalid_movement_group_id", "Invalid movement-group identifier."
            )
        return self._append_canonical_event(
            context=request.command_context,
            event_kind="movement_group_formed",
            payload={
                "new_group_id": request.new_group_id,
                "display_name": request.display_name,
                "formation_kind": request.formation_kind,
                "participant_refs_hash": request.participant_refs_hash,
                "coordinator_ref": request.coordinator_ref,
                "mission_day_id": request.mission_day_id,
                "mission_day_instance_id": request.mission_day_instance_id,
                "target_ref": request.target_ref,
                "target_sha256": request.target_sha256,
                "shared_dependency_refs": request.shared_dependency_refs,
                "shared_dependency_hashes": request.shared_dependency_hashes,
                "reporter_alias": request.reporter_alias,
                "inferred_from_distance_or_pace": False,
            },
        )

    def confirm_day_end(
        self, request: ManualDayEndConfirmationRequest
    ) -> CanonicalEvent:
        if not request.explicit_confirmation:
            raise ContextualPermissionConflict(
                "explicit_confirmation_required", "Day-end completion must be confirmed."
            )
        if not request.authorized_on_site_participant:
            raise ContextualPermissionConflict(
                "authorized_on_site_participant_required",
                "Only an authorized on-site participant may confirm the exact target.",
            )
        group = self._current_group_projection(request.command_context.group_id)
        if group.day_end.completion != "open":
            raise ContextualPermissionConflict(
                "day_already_closed", "This movement group's mission day is already closed."
            )
        if request.target_kind == "planned_day_end":
            if request.confirmation_kind != "arrived":
                raise ContextualPermissionConflict(
                    "invalid_day_end_confirmation",
                    "A planned target requires Arrived confirmation.",
                )
            expected_ref = group.day_end.planned_target_ref
            expected_sha = group.day_end.planned_target_sha256
            expected_label = group.day_end.planned_target_label
        else:
            if request.confirmation_kind != "camp_established":
                raise ContextualPermissionConflict(
                    "invalid_day_end_confirmation",
                    "A bivy target requires Camp established confirmation.",
                )
            if group.day_end.state != "emergency_bivy_selected":
                raise ContextualPermissionConflict(
                    "emergency_bivy_selection_required",
                    "The exact reviewed emergency bivy must be selected first.",
                )
            expected_ref = group.day_end.effective_target_ref
            expected_sha = group.day_end.effective_target_sha256
            expected_label = group.day_end.effective_target_label
        if (
            request.target_ref != expected_ref
            or request.target_sha256 != expected_sha
            or request.target_label != expected_label
        ):
            raise ContextualPermissionConflict(
                "target_mismatch", "The confirmed target does not match current reviewed truth."
            )
        return self._append_canonical_event(
            context=request.command_context,
            event_kind="day_end_closed",
            payload={
                "target_ref": request.target_ref,
                "target_sha256": request.target_sha256,
                "target_label": request.target_label,
                "target_kind": request.target_kind,
                "confirmation_mode": "manual_on_site",
                "confirmation_kind": request.confirmation_kind,
                "participant_alias": request.participant_alias,
                "uncertainty_acknowledgement": (
                    request.uncertainty_acknowledgement
                ),
                "elapsed_seconds": 0,
                "evidence_refs": ["receipt://on-site/day-end-confirmation"],
                "pending_next_day": self._next_day_id(group.mission_day_id),
                "individual_sleep_or_safety_attested": False,
            },
        )

    def report_day_end_unreachable(
        self, request: DayEndUnreachableRequest
    ) -> CanonicalEvent:
        if len(request.cause_refs) != len(request.cause_hashes):
            raise ContextualPermissionConflict(
                "cause_lineage_mismatch", "Cause refs and hashes must have the same length."
            )
        if request.cause_kind == "human_safety_trigger":
            if not request.explicit_confirmation or not request.reporter_alias:
                raise ContextualPermissionConflict(
                    "verified_safety_trigger_required",
                    "A human cannot-reach report requires a confirmed Safety / Emergency receipt.",
                )
        elif request.explicit_confirmation:
            raise ContextualPermissionConflict(
                "automatic_fact_confirmation_forbidden",
                "Automatic feasibility facts are not human attestations.",
            )
        group = self._current_group_projection(request.command_context.group_id)
        if group.day_end.completion != "open":
            raise ContextualPermissionConflict(
                "day_already_closed", "A closed day cannot become unreachable."
            )
        return self._append_canonical_event(
            context=request.command_context,
            event_kind="day_end_unreachable_reported",
            payload={
                "cause_kind": request.cause_kind,
                "cause_refs": request.cause_refs,
                "cause_hashes": request.cause_hashes,
                "reporter_alias": request.reporter_alias,
                "safety_emergency_trigger_receipt": (
                    request.cause_kind == "human_safety_trigger"
                ),
                "automatic_site_selection_performed": False,
            },
        )

    def select_emergency_bivy(
        self, request: EmergencyBivySelectionRequest
    ) -> CanonicalEvent:
        if not request.explicit_confirmation:
            raise ContextualPermissionConflict(
                "explicit_confirmation_required", "Bivy selection must be confirmed."
            )
        group = self._current_group_projection(request.command_context.group_id)
        if group.day_end.state != "emergency_bivy_review_required":
            raise ContextualPermissionConflict(
                "emergency_bivy_review_required",
                "Emergency Bivy Review must be open before target selection.",
            )
        review = self.daily_emergency_review(group.mission_day_instance_id)
        reviewed_candidates = [
            candidate
            for packet in review.alternatives
            if packet.movement_group_id == group.group_id
            for candidate in packet.emergency_bivy_candidates
        ]
        if not any(
            candidate.target_ref == request.target_ref
            and candidate.target_sha256 == request.target_sha256
            and candidate.target_label == request.target_label
            for candidate in reviewed_candidates
        ):
            raise ContextualPermissionConflict(
                "reviewed_emergency_bivy_required",
                "The selected bivy is not an exact reviewed candidate for this group and mission day.",
            )
        return self._append_canonical_event(
            context=request.command_context,
            event_kind="emergency_bivy_selected",
            payload={
                "target_ref": request.target_ref,
                "target_sha256": request.target_sha256,
                "target_label": request.target_label,
                "reviewer_alias": request.reviewer_alias,
                "day_closed": False,
            },
        )

    def correct_day_end_close(
        self, request: DayEndCloseCorrectionRequest
    ) -> CanonicalEvent:
        if not request.explicit_confirmation:
            raise ContextualPermissionConflict(
                "explicit_confirmation_required", "Day-end correction must be confirmed."
            )
        close_event = next(
            (
                event
                for event in self._load_group_events(request.command_context.group_id)
                if event.event_id == request.close_event_id
                and event.event_kind == "day_end_closed"
            ),
            None,
        )
        if close_event is None:
            raise ContextualPermissionConflict(
                "day_end_close_not_found", "The original day-end close receipt is missing."
            )
        if any(
            event.event_kind == "day_end_close_corrected"
            and event.payload.get("close_event_id") == request.close_event_id
            for event in self._load_group_events(request.command_context.group_id)
        ):
            raise ContextualPermissionConflict(
                "day_end_close_already_corrected",
                "The original close already has a correction receipt.",
            )
        return self._append_canonical_event(
            context=request.command_context,
            event_kind="day_end_close_corrected",
            payload={
                "close_event_id": request.close_event_id,
                "reason": request.reason,
                "reporter_alias": request.reporter_alias,
                "original_close_preserved": True,
            },
        )

    def review_shelter_hold(self, request: ShelterHoldReviewRequest) -> CanonicalEvent:
        if not request.explicit_confirmation:
            raise ContextualPermissionConflict(
                "explicit_confirmation_required", "Shelter Hold review must be confirmed."
            )
        group = self._current_group_projection(request.command_context.group_id)
        if group.shelter_hold.state in {"not_required", "closed"}:
            raise ContextualPermissionConflict(
                "shelter_hold_not_active", "No Shelter Hold is active for this group."
            )
        if request.calendar_days_elapsed < group.shelter_hold.calendar_days_elapsed:
            raise ContextualPermissionConflict(
                "non_monotonic_hold_audit",
                "Calendar hold duration cannot move backwards.",
            )
        return self._append_canonical_event(
            context=request.command_context,
            event_kind="shelter_hold_reviewed",
            payload={
                "decision": request.decision,
                "calendar_days_elapsed": request.calendar_days_elapsed,
                "automatic_fact_refs": request.automatic_fact_refs,
                "human_trigger_refs": request.human_trigger_refs,
                "reviewer_alias": request.reviewer_alias,
                "mission_day_rollover_performed": False,
            },
        )

    def revise_movement_group(
        self, request: MovementGroupRevisionRequest
    ) -> CanonicalEvent:
        if not request.explicit_confirmation:
            raise ContextualPermissionConflict(
                "explicit_confirmation_required",
                "Movement-group membership revision must be confirmed.",
            )
        group = self._current_group_projection(request.command_context.group_id)
        if request.expected_membership_sha256 != group.membership_sha256:
            raise ContextualPermissionConflict(
                "movement_group_revision_mismatch",
                "The movement-group membership hash has changed.",
            )
        return self._append_canonical_event(
            context=request.command_context,
            event_kind="movement_group_membership_revised",
            payload={
                "prior_membership_revision": group.membership_revision,
                "prior_membership_sha256": group.membership_sha256,
                "membership_revision": group.membership_revision + 1,
                "participant_refs_hash": request.participant_refs_hash,
                "coordinator_ref": request.coordinator_ref,
                "reporter_alias": request.reporter_alias,
            },
        )

    def merge_movement_groups(
        self, request: MovementGroupMergeRequest
    ) -> CanonicalEvent:
        if not request.explicit_confirmation:
            raise ContextualPermissionConflict(
                "explicit_confirmation_required", "Movement-group merge must be confirmed."
            )
        groups = {
            group.group_id: group
            for group in self._reduce_movement_groups(self._load_all_canonical_events())
        }
        source_groups = []
        for group_id in request.source_group_ids:
            group = groups.get(group_id)
            if group is None:
                raise ContextualPermissionConflict(
                    "movement_group_not_found", f"Source group is missing: {group_id}"
                )
            if request.source_membership_revisions.get(group_id) != group.membership_revision:
                raise ContextualPermissionConflict(
                    "movement_group_revision_mismatch",
                    f"Source group revision changed: {group_id}",
                )
            source_groups.append(group)
        contexts = {
            (group.mission_day_id, group.mission_day_instance_id, group.day_end.state)
            for group in source_groups
        }
        if len(contexts) > 1 and not request.reconciliation_reviewed:
            raise ContextualPermissionConflict(
                "movement_group_reconciliation_required",
                "Different day or route contexts require explicit reconciliation review.",
            )
        if request.new_group_id in groups:
            raise ContextualPermissionConflict(
                "movement_group_already_exists", "The merged group already exists."
            )
        return self._append_canonical_event(
            context=request.command_context,
            event_kind="movement_groups_merged",
            payload={
                "new_group_id": request.new_group_id,
                "display_name": request.display_name,
                "formation_kind": "field_explicit",
                "participant_refs_hash": request.participant_refs_hash,
                "coordinator_ref": request.coordinator_ref or request.reviewer_alias,
                "mission_day_id": request.mission_day_id,
                "mission_day_instance_id": request.mission_day_instance_id,
                "target_ref": request.target_ref,
                "target_sha256": request.target_sha256,
                "shared_dependency_refs": request.shared_dependency_refs,
                "shared_dependency_hashes": request.shared_dependency_hashes,
                "reporter_alias": request.reviewer_alias,
                "source_group_ids": request.source_group_ids,
                "source_membership_revisions": request.source_membership_revisions,
                "reconciliation_reviewed": request.reconciliation_reviewed,
                "prior_histories_preserved": True,
            },
        )

    def _load_optional_baseline_source(
        self,
        project: dict[str, object],
        project_key: str,
        *,
        default_ref: str | None = None,
    ) -> tuple[str, str, object] | None:
        raw_ref = project.get(project_key) or default_ref
        if not isinstance(raw_ref, str) or not raw_ref.strip():
            return None
        ref = raw_ref.strip()
        path = self._resolve_project_ref(ref)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContextualPermissionConflict(
                "baseline_source_invalid",
                f"The typed baseline source is invalid: {ref}",
            ) from exc
        return ref, _file_sha256(path), payload

    @staticmethod
    def _interpolate_route_distance(
        route_point_index: int,
        index_distance_pairs: list[tuple[int, float]],
    ) -> float | None:
        if len(index_distance_pairs) < 2:
            return None
        ordered = sorted(index_distance_pairs)
        for (left_index, left_distance), (right_index, right_distance) in zip(
            ordered,
            ordered[1:],
            strict=False,
        ):
            if not left_index <= route_point_index <= right_index:
                continue
            if right_index == left_index:
                return left_distance
            fraction = (route_point_index - left_index) / (right_index - left_index)
            return left_distance + ((right_distance - left_distance) * fraction)
        return None

    def _build_reference_gpx_auto_draft(
        self,
        *,
        project: dict[str, object],
        route_ref: str,
        route_sha: str,
        timing_ref: str,
        timing_sha: str,
        timing_payload: object,
    ) -> MissionBaselineDraft:
        if not isinstance(timing_payload, dict):
            raise ContextualPermissionConflict(
                "reference_timing_invalid",
                "Reference timing must be a typed object.",
            )
        raw_segments = timing_payload.get("segments")
        raw_matches = timing_payload.get("checkpoint_match_quality")
        if not isinstance(raw_segments, list) or not isinstance(raw_matches, dict):
            raise ContextualPermissionConflict(
                "reference_timing_invalid",
                "Reference timing is missing ordered segments or route anchors.",
            )
        anchors = sorted(
            (
                {
                    "label": str(value.get("label") or key),
                    "source_id": str(value.get("source_id") or key),
                    "source_kind": str(value.get("source_kind") or "checkpoint"),
                    "distance_m": float(value["route_distance_m"]),
                    "artifact_ref": timing_ref,
                    "artifact_sha256": timing_sha,
                    "confidence": "high",
                    "classes": [],
                }
                for key, value in raw_matches.items()
                if isinstance(value, dict)
                and isinstance(value.get("route_distance_m"), (int, float))
            ),
            key=lambda item: float(item["distance_m"]),
        )
        if len(anchors) != len(raw_segments) + 1 or len(anchors) < 2:
            raise ContextualPermissionConflict(
                "reference_timing_alignment_invalid",
                "Timing segments must align one-to-one with ordered route anchors.",
            )

        normalized_segments: list[dict[str, object]] = []
        for index, raw_segment in enumerate(raw_segments):
            if not isinstance(raw_segment, dict):
                raise ContextualPermissionConflict(
                    "reference_timing_invalid",
                    "Every timing segment must be a typed object.",
                )
            start_anchor = anchors[index]
            end_anchor = anchors[index + 1]
            if (
                str(raw_segment.get("from_node_name") or "")
                != str(start_anchor["label"])
                or str(raw_segment.get("to_node_name") or "")
                != str(end_anchor["label"])
            ):
                raise ContextualPermissionConflict(
                    "reference_timing_alignment_invalid",
                    "Timing labels do not match the ordered route anchors.",
                )
            durations = raw_segment.get("duration_minutes")
            durations = durations if isinstance(durations, dict) else {}
            p50 = durations.get("p50")
            p75 = durations.get("p75")
            normalized_segments.append(
                {
                    "segment_id": str(
                        raw_segment.get("segment_id") or f"timing.segment.{index + 1:03d}"
                    ),
                    "start_m": float(start_anchor["distance_m"]),
                    "end_m": float(end_anchor["distance_m"]),
                    "p50": float(p50) if isinstance(p50, (int, float)) else None,
                    "p75": float(p75) if isinstance(p75, (int, float)) else None,
                }
            )

        source_refs = [route_ref, timing_ref]
        source_hashes = {route_ref: route_sha, timing_ref: timing_sha}
        optional_sources = {
            key: self._load_optional_baseline_source(project, key, default_ref=default_ref)
            for key, default_ref in (
                ("rest_area_candidates_ref", None),
                ("mcp_candidates_ref", None),
                ("retreat_routes_ref", None),
                ("checkpoints_ref", "candidates/checkpoints.json"),
            )
        }
        for source in optional_sources.values():
            if source is None:
                continue
            source_refs.append(source[0])
            source_hashes[source[0]] = source[1]

        mcp_source = optional_sources["mcp_candidates_ref"]
        mcp_by_label: dict[str, dict[str, object]] = {}
        if mcp_source is not None and isinstance(mcp_source[2], dict):
            mcp_by_label = {
                str(item.get("label") or ""): item
                for item in (mcp_source[2].get("mcp_candidates") or [])
                if isinstance(item, dict) and item.get("label")
            }
        endpoint_candidates = [
            {
                **anchor,
                "classes": list(
                    (mcp_by_label.get(str(anchor["label"])) or {}).get("mcp_classes")
                    or []
                ),
                "confidence": str(
                    (mcp_by_label.get(str(anchor["label"])) or {}).get("confidence")
                    or anchor["confidence"]
                ),
            }
            for anchor in anchors
        ]

        checkpoint_source = optional_sources["checkpoints_ref"]
        checkpoint_indexes: dict[str, int] = {}
        if checkpoint_source is not None and isinstance(checkpoint_source[2], list):
            checkpoint_indexes = {
                str(item.get("candidate_id")): int(item["route_point_index"])
                for item in checkpoint_source[2]
                if isinstance(item, dict)
                and item.get("candidate_id")
                and isinstance(item.get("route_point_index"), int)
            }
        index_distance_pairs = [
            (checkpoint_indexes[str(anchor["source_id"])], float(anchor["distance_m"]))
            for anchor in anchors
            if str(anchor["source_id"]) in checkpoint_indexes
        ]
        rest_source = optional_sources["rest_area_candidates_ref"]
        rest_endpoints: list[dict[str, object]] = []
        if rest_source is not None and isinstance(rest_source[2], dict):
            for item in rest_source[2].get("candidates") or []:
                if not isinstance(item, dict) or not isinstance(
                    item.get("route_point_index"), int
                ):
                    continue
                distance_m = self._interpolate_route_distance(
                    int(item["route_point_index"]), index_distance_pairs
                )
                if distance_m is None:
                    continue
                rest_endpoints.append(
                    {
                        "label": str(item.get("label") or "Rest / camp candidate"),
                        "source_id": str(
                            item.get("candidate_id") or item.get("checkpoint_candidate_id")
                        ),
                        "source_kind": "rest_area",
                        "distance_m": distance_m,
                        "artifact_ref": rest_source[0],
                        "artifact_sha256": rest_source[1],
                        "confidence": str(item.get("confidence") or "medium"),
                        "classes": ["rest_or_camp"],
                    }
                )
        target_day_p75 = 480.0
        route_length_m = float(anchors[-1]["distance_m"])
        eligible_anchor_rows = [
            (index, item)
            for index, item in enumerate(endpoint_candidates)
            if index > 0
            and (
                index == len(endpoint_candidates) - 1
                or item.get("source_kind") == "checkpoint"
                or "camp_or_hut"
                in {str(value).casefold() for value in item.get("classes") or []}
            )
        ]
        selected_boundaries: list[dict[str, object]] = []
        current_anchor_index = 0
        while current_anchor_index < len(anchors) - 1:
            candidate_rows: list[dict[str, object]] = []
            for end_index, item in eligible_anchor_rows:
                if end_index <= current_anchor_index:
                    continue
                day_segments = normalized_segments[current_anchor_index:end_index]
                missing_ids = [
                    str(segment["segment_id"])
                    for segment in day_segments
                    if not isinstance(segment.get("p75"), (int, float))
                ]
                known_p75_sum = sum(
                    float(segment["p75"])
                    for segment in day_segments
                    if isinstance(segment.get("p75"), (int, float))
                )
                candidate_rows.append(
                    {
                        "item": item,
                        "end_index": end_index,
                        "missing_ids": missing_ids,
                        "known_p75_sum": known_p75_sum,
                    }
                )
            if not candidate_rows:
                raise ContextualPermissionConflict(
                    "reference_day_segmentation_failed",
                    "No deterministic destination candidate covers the remaining route.",
                )
            fully_supported = [
                row for row in candidate_rows if not row["missing_ids"]
            ]
            within_target = [
                row
                for row in fully_supported
                if float(row["known_p75_sum"]) <= target_day_p75
            ]
            if within_target:
                chosen_row = max(within_target, key=lambda row: int(row["end_index"]))
                target_exceeded = False
            elif fully_supported:
                chosen_row = min(fully_supported, key=lambda row: int(row["end_index"]))
                target_exceeded = True
            else:
                chosen_row = min(
                    candidate_rows,
                    key=lambda row: (
                        len(row["missing_ids"]),
                        abs(float(row["known_p75_sum"]) - target_day_p75),
                        int(row["end_index"]),
                        str(row["item"]["artifact_ref"]),
                        str(row["item"]["artifact_sha256"]),
                    ),
                )
                target_exceeded = False
            next_index = int(chosen_row["end_index"])
            if next_index <= current_anchor_index:
                raise ContextualPermissionConflict(
                    "reference_day_segmentation_failed",
                    "Automatic day segmentation did not advance along the route.",
                )
            selected_boundaries.append(
                {
                    **chosen_row,
                    "start_index": current_anchor_index,
                    "target_exceeded": target_exceeded,
                }
            )
            current_anchor_index = next_index
            if len(selected_boundaries) > 50:
                raise ContextualPermissionConflict(
                    "reference_day_segmentation_failed",
                    "Automatic day segmentation exceeded the bounded day count.",
                )

        retreat_source = optional_sources["retreat_routes_ref"]
        retreat_items = (
            retreat_source[2]
            if retreat_source is not None and isinstance(retreat_source[2], list)
            else []
        )
        def anchor_binding(item: dict[str, object]) -> BaselineRouteAnchor:
            return BaselineRouteAnchor(
                anchor_id=str(item["source_id"]),
                display_label=str(item["label"]),
                artifact=BaselineArtifactBinding(
                    ref=str(item["artifact_ref"]),
                    sha256=str(item["artifact_sha256"]),
                ),
                route_order_m=round(float(item["distance_m"]), 1),
            )

        def target_proposal(
            item: dict[str, object],
            *,
            day_id: str,
            kind: Literal["day_end", "retreat", "emergency_bivy"],
            review_surface: Literal["permission", "safety_emergency"],
            rationale: str,
        ) -> BaselineTargetProposal:
            artifact_ref = str(item["artifact_ref"])
            artifact_sha = str(item["artifact_sha256"])
            return BaselineTargetProposal(
                proposal_id=f"proposal.{_fixed_hash(f'{day_id}:{kind}:{item["source_id"]}:{artifact_sha}')[:20]}",
                kind=kind,
                mission_day_id=day_id,
                target=anchor_binding(item),
                confidence=(
                    str(item.get("confidence"))
                    if str(item.get("confidence")) in {"high", "medium", "low", "unknown"}
                    else "unknown"
                ),
                rationale=rationale,
                evidence=[BaselineArtifactBinding(ref=artifact_ref, sha256=artifact_sha)],
                required_review_surface=review_surface,
            )

        days: list[BaselineDayDraft] = [
            BaselineDayDraft(
                mission_day_id="D0",
                source_text="Reference route staging",
                day_kind="logistics",
                ordered_place_mentions=["Trailhead staging"],
                resolved_targets=["Trailhead staging"],
                resolved_target_refs={
                    "Trailhead staging": "reviewed://route/trailhead-staging"
                },
                resolved_target_hashes={
                    "Trailhead staging": _fixed_hash(
                        f"{self.project_id}:trailhead-staging"
                    )
                },
                unresolved_names=[],
                review_summary="Logistics staging remains separate from on-trail days.",
            )
        ]
        uncertainties: list[BaselineUncertainty] = []
        generic_handoff_item_ids = [
            f"branch:{str(item.get('candidate_id') or 'retreat.reversed-primary')}"
            for item in retreat_items
            if isinstance(item, dict)
        ]
        bivy_candidate_ids: list[str] = []
        for ordinal, boundary in enumerate(selected_boundaries, 1):
            day_id = f"D{ordinal}"
            start_index = int(boundary["start_index"])
            end_index = int(boundary["end_index"])
            start_item = anchors[start_index]
            end_item = boundary["item"]
            start_distance_m = float(start_item["distance_m"])
            end_distance_m = float(end_item["distance_m"])
            overlapping_segments = normalized_segments[start_index:end_index]
            segment_ids = [str(segment["segment_id"]) for segment in overlapping_segments]
            unsupported_ids = [
                str(segment["segment_id"])
                for segment in overlapping_segments
                if not isinstance(segment.get("p75"), (int, float))
            ]
            supporting_segments = [
                segment
                for segment in overlapping_segments
                if isinstance(segment.get("p75"), (int, float))
            ]
            supporting_ids = [
                str(segment["segment_id"]) for segment in supporting_segments
            ]
            gap_ids: list[str] = []
            if unsupported_ids:
                uncertainty_id = f"uncertainty.{_fixed_hash(f'{day_id}:{":".join(unsupported_ids)}')[:20]}"
                gap_ids = [uncertainty_id]
                uncertainties.append(
                    BaselineUncertainty(
                        uncertainty_id=uncertainty_id,
                        code="missing_historical_p75",
                        affected_day_ids=[day_id],
                        affected_segment_ids=unsupported_ids,
                        summary=(
                            f"{len(unsupported_ids)} segment(s) have no usable historical "
                            "p75; Scout does not fill them."
                        ),
                        disposition="acknowledgeable",
                        required_review_surface="permission",
                        evidence=[
                            BaselineArtifactBinding(ref=timing_ref, sha256=timing_sha)
                        ],
                    )
                )
            if boundary["target_exceeded"]:
                target_gap_id = f"uncertainty.{_fixed_hash(f'{day_id}:target-exceeded')[:20]}"
                gap_ids.append(target_gap_id)
                uncertainties.append(
                    BaselineUncertainty(
                        uncertainty_id=target_gap_id,
                        code="strategy_target_exceeded",
                        affected_day_ids=[day_id],
                        affected_segment_ids=segment_ids,
                        summary=(
                            "The nearest fully supported destination exceeds the "
                            "strategy timing target; the target is a proposal heuristic."
                        ),
                        disposition="acknowledgeable",
                        required_review_surface="permission",
                        evidence=[
                            BaselineArtifactBinding(ref=timing_ref, sha256=timing_sha)
                        ],
                    )
                )
            supported_p75 = round(
                sum(float(segment["p75"]) for segment in supporting_segments), 1
            )
            all_supported_p50 = bool(supporting_segments) and all(
                isinstance(segment.get("p50"), (int, float))
                for segment in supporting_segments
            )
            supported_p50 = (
                round(sum(float(segment["p50"]) for segment in supporting_segments), 1)
                if all_supported_p50
                else None
            )
            if not unsupported_ids:
                eta = BaselineEtaProposal(
                    state="complete_derived",
                    method="sum_segment_quantiles",
                    confidence="medium",
                    segment_p50_sum_minutes=supported_p50,
                    segment_p75_sum_minutes=supported_p75,
                    supporting_segment_ids=segment_ids,
                )
            elif supporting_ids:
                eta = BaselineEtaProposal(
                    state="partial_derived",
                    method="sum_supported_segment_quantiles",
                    confidence="low",
                    supported_segment_p50_sum_minutes=supported_p50,
                    supported_segment_p75_sum_minutes=supported_p75,
                    supporting_segment_ids=supporting_ids,
                    unsupported_segment_ids=unsupported_ids,
                    gap_ids=gap_ids,
                )
            else:
                eta = BaselineEtaProposal(
                    state="unknown",
                    method="no_numeric_eta",
                    confidence="unknown",
                    unsupported_segment_ids=unsupported_ids,
                    gap_ids=gap_ids,
                    reason="no_usable_segment_p75",
                )
            end_proposal = target_proposal(
                end_item,
                day_id=day_id,
                kind="day_end",
                review_surface="permission",
                rationale=(
                    "Scout-selected destination balancing the declared day-duration target, "
                    "route order and available rest/camp evidence."
                ),
            )
            bivy_rows = sorted(
                (
                    item
                    for item in rest_endpoints
                    if start_distance_m < float(item["distance_m"]) <= end_distance_m
                ),
                key=lambda item: abs(end_distance_m - float(item["distance_m"])),
            )[:2]
            bivy_candidates = [
                target_proposal(
                    item,
                    day_id=day_id,
                    kind="emergency_bivy",
                    review_surface="safety_emergency",
                    rationale=(
                        "Candidate-only rest/camp evidence near this day interval; "
                        "Safety / Emergency must review it."
                    ),
                )
                for item in bivy_rows
            ]
            bivy_candidate_ids.extend(item.proposal_id for item in bivy_candidates)
            days.append(
                BaselineDayDraft(
                    mission_day_id=day_id,
                    source_text=f"{start_item['label']} -> {end_item['label']}",
                    ordered_place_mentions=[
                        str(start_item["label"]),
                        str(end_item["label"]),
                    ],
                    resolved_targets=[str(end_item["label"])],
                    resolved_target_refs={
                        str(end_item["label"]): str(end_item["artifact_ref"])
                    },
                    resolved_target_hashes={
                        str(end_item["label"]): str(end_item["artifact_sha256"])
                    },
                    unresolved_names=[],
                    start_anchor=anchor_binding(start_item),
                    primary_day_end_proposal=end_proposal,
                    eta_proposal=eta,
                    segment_ids=segment_ids,
                    retreat_candidates=[],
                    emergency_bivy_candidates=bivy_candidates,
                    uncertainty_ids=gap_ids,
                    review_summary=(
                        f"{start_item['label']} → {end_item['label']} · "
                        + (
                            f"derived segment sums p50 {supported_p50:g} / p75 {supported_p75:g} min"
                            if eta.state == "complete_derived" and supported_p50 is not None
                            else f"derived segment p75 sum {supported_p75:g} min"
                            if eta.state == "complete_derived"
                            else f"supported p75 subtotal {supported_p75:g} min · {len(unsupported_ids)} segment(s) missing"
                            if eta.state == "partial_derived"
                            else f"ETA unknown · {len(unsupported_ids)} segment(s) without usable p75"
                        )
                    ),
                )
            )

        pending_handoff_ids = list(dict.fromkeys(
            [*generic_handoff_item_ids, *(f"target:{item}" for item in bivy_candidate_ids)]
        ))
        safety_required = bool(pending_handoff_ids)
        if safety_required:
            handoff_evidence = [
                BaselineArtifactBinding(ref=source[0], sha256=source[1])
                for source in (retreat_source, rest_source)
                if source is not None
            ]
            uncertainties.append(
                BaselineUncertainty(
                    uncertainty_id=f"uncertainty.{_fixed_hash('safety-emergency-handoff')[:20]}",
                    code="external_safety_review",
                    affected_day_ids=[
                        day.mission_day_id for day in days if day.day_kind == "on_trail"
                    ],
                    related_target_proposal_ids=bivy_candidate_ids,
                    summary=(
                        "Retreat and emergency-bivy items remain pending in "
                        "Safety / Emergency; Permission cannot approve them."
                    ),
                    disposition="external_review_pending",
                    required_review_surface="safety_emergency",
                    evidence=handoff_evidence,
                )
            )
        permission_uncertainty_ids = [
            item.uncertainty_id
            for item in uncertainties
            if item.disposition == "acknowledgeable"
            and item.required_review_surface == "permission"
        ]
        review_requirements = BaselineReviewRequirements(
            required_reviewed_day_ids=[
                day.mission_day_id for day in days if day.day_kind == "on_trail"
            ],
            required_acknowledgment_uncertainty_ids=permission_uncertainty_ids,
            pending_safety_handoff_item_ids=pending_handoff_ids,
            safety_handoff_required=safety_required,
        )
        source_refs = list(dict.fromkeys(source_refs))
        source_hashes = {ref: source_hashes[ref] for ref in source_refs}
        source = json.dumps(
            {
                "generator_version": BASELINE_AUTO_PROPOSAL_VERSION,
                "source_hashes": source_hashes,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        source_sha = _fixed_hash(source)
        missing_p75_count = sum(
            1
            for segment in normalized_segments
            if not isinstance(segment.get("p75"), (int, float))
        )
        return MissionBaselineDraft(
            artifact_kind="mission_baseline_candidate",
            schema_version="missionBaselineCandidate.v1",
            draft_id=f"baseline-draft.{source_sha[:16]}",
            source_mode="reference_gpx",
            source_sha256=source_sha,
            source_text=source,
            source_refs=source_refs,
            source_hashes=source_hashes,
            route_axis_validation={
                "track_order": "pass",
                "endpoint_continuity": "pass",
                "resume_gaps": "pass",
                "route_direction": "pass",
            },
            days=days,
            assumptions=[
                "Scout proposed destination-defined days using a 480-minute p75 target.",
                (
                    "Missing historical p75 values remain unsupported. Partial ETA "
                    "objects expose only supported segment-quantile subtotals."
                ),
            ],
            validation_state="valid",
            unresolved_gaps=[],
            proposal_profile="ref_gpx_proposal_v1",
            proposal_strategy_id="destination-boundary.segment-quantile-target",
            proposal_strategy_version=BASELINE_AUTO_PROPOSAL_VERSION,
            timing_evidence=BaselineArtifactBinding(
                ref=timing_ref,
                sha256=timing_sha,
            ),
            proposal_summary=BaselineProposalSummary(
                day_count=len(days) - 1,
                route_length_m=round(route_length_m, 1),
                timing_segment_count=len(normalized_segments),
                observed_p75_segment_count=len(normalized_segments) - missing_p75_count,
                missing_p75_segment_count=missing_p75_count,
                permission_uncertainty_count=len(permission_uncertainty_ids),
                safety_pending_count=len(pending_handoff_ids),
                blocking_gap_count=0,
                target_p75_minutes_per_day=int(target_day_p75),
                source_route_days_metadata=(
                    int(project["route_days"])
                    if isinstance(project.get("route_days"), int)
                    else None
                ),
            ),
            uncertainties=uncertainties,
            review_requirements=review_requirements,
            safety_handoff_summary=(
                f"{len(pending_handoff_ids)} item(s) pending Safety / Emergency review."
                if safety_required
                else "No Safety / Emergency handoff item was proposed."
            ),
        )

    def preview_baseline(self, request: BaselineAuthoringRequest) -> MissionBaselineDraft:
        if request.mode == "human_text":
            source = (request.human_text or "").strip()
            days: list[BaselineDayDraft] = []
            unresolved: list[str] = []
            for line in source.splitlines():
                match = re.match(r"^\s*(D\d+)\s*[:：]\s*(.+?)\s*$", line)
                if not match:
                    if line.strip():
                        unresolved.append(f"unparsed_line:{line.strip()}")
                    continue
                day_id, day_text = match.groups()
                tokens = [token.strip() for token in re.split(r"\s*[-–—>]\s*", day_text)]
                mentions: list[str] = []
                aliases: list[str] = []
                coordinate_hints: list[dict[str, object]] = []
                branches: list[dict[str, object]] = []
                day_unresolved: list[str] = []
                for token in (item for item in tokens if item):
                    aliases.extend(
                        re.findall(r"(?<![A-Za-z0-9])C\d+(?!\d)", token)
                    )
                    for coordinate in re.findall(r"\((\d{5,7}/\d{6,8})\)", token):
                        coordinate_hints.append(
                            {
                                "raw_text": coordinate,
                                "confirmed_crs": None,
                                "reviewed": False,
                            }
                        )
                    cleaned = re.sub(r"\(\d{5,7}/\d{6,8}\)", "", token)
                    cleaned = re.sub(
                        r"(?<![A-Za-z0-9])C\d+(?!\d)", "", cleaned
                    ).strip()
                    is_branch = cleaned.startswith("單攻")
                    cleaned = re.sub(r"^單攻\s*", "", cleaned).strip()
                    if cleaned:
                        mentions.append(cleaned)
                        if day_id != "D0":
                            day_unresolved.append(cleaned)
                    if is_branch:
                        branches.append(
                            {
                                "label": cleaned or token,
                                "kind": "out_and_back_candidate",
                                "reviewed": False,
                            }
                        )
                if day_id != "D0":
                    day_unresolved.extend(f"alias:{alias}" for alias in aliases)
                    day_unresolved.extend(
                        f"coordinate_crs:{item['raw_text']}"
                        for item in coordinate_hints
                    )
                    day_unresolved.extend(
                        f"branch_review:{item['label']}" for item in branches
                    )
                unresolved.extend(f"{day_id}:{item}" for item in day_unresolved)
                days.append(
                    BaselineDayDraft(
                        mission_day_id=day_id,
                        source_text=day_text,
                        day_kind="logistics" if day_id == "D0" else "on_trail",
                        ordered_place_mentions=mentions,
                        resolved_targets=mentions if day_id == "D0" else [],
                        unresolved_names=day_unresolved,
                        operator_aliases=aliases,
                        coordinate_hints=coordinate_hints,
                        branch_candidates=branches,
                    )
                )
            if not days:
                raise ContextualPermissionConflict(
                    "baseline_days_missing", "No D0...Dn itinerary lines were found."
                )
            route_axis_validation = {
                "track_order": "unknown",
                "endpoint_continuity": "unknown",
                "resume_gaps": "unknown",
                "route_direction": "unknown",
            }
            source_refs: list[str] = []
            source_hashes: dict[str, str] = {}
        else:
            ref = (request.reference_route_ref or "").strip()
            route_path = self._resolve_project_ref(ref)
            if not route_path.is_file():
                raise ContextualPermissionConflict(
                    "reference_route_missing", "The selected reference route is missing."
                )
            project = json.loads(
                self._resolve_project_ref("project.json").read_text(encoding="utf-8")
            )
            route_sha = _file_sha256(route_path)
            timing_source = self._load_optional_baseline_source(
                project, "reference_segment_timing_ref"
            )
            if project.get("reference_segment_timing_ref") and timing_source is None:
                raise ContextualPermissionConflict(
                    "reference_timing_missing",
                    "The declared reference timing artifact is missing.",
                )
            if timing_source is not None:
                return self._build_reference_gpx_auto_draft(
                    project=project,
                    route_ref=ref,
                    route_sha=route_sha,
                    timing_ref=timing_source[0],
                    timing_sha=timing_source[1],
                    timing_payload=timing_source[2],
                )
            eta_path = self._resolve_project_ref(str(project["planned_eta_ref"]))
            eta = json.loads(eta_path.read_text(encoding="utf-8"))
            assumption = eta.get("assumption") if isinstance(eta, dict) else {}
            target = str((assumption or {}).get("day1_target_node_name") or "Reviewed day-end target")
            turn_back = str((assumption or {}).get("turn_back_checkpoint_node_name") or "Reviewed junction")
            source = f"{ref}:{route_sha}"
            days = [
                BaselineDayDraft(
                    mission_day_id="D0",
                    source_text="Reference route staging",
                    day_kind="logistics",
                    ordered_place_mentions=["Trailhead staging"],
                    resolved_targets=["Trailhead staging"],
                    resolved_target_refs={
                        "Trailhead staging": "reviewed://route/trailhead-staging"
                    },
                    resolved_target_hashes={
                        "Trailhead staging": _fixed_hash(
                            f"{self.project_id}:trailhead-staging"
                        )
                    },
                    unresolved_names=[],
                ),
                BaselineDayDraft(
                    mission_day_id="D1",
                    source_text="Reference route axis",
                    ordered_place_mentions=[turn_back, target],
                    resolved_targets=[turn_back, target],
                    resolved_target_refs={
                        turn_back: "reviewed://route/day-D1/turn-back",
                        target: "reviewed://route/day-D1/end",
                    },
                    resolved_target_hashes={
                        turn_back: _fixed_hash(f"{self.project_id}:{turn_back}"),
                        target: _fixed_hash(f"{self.project_id}:{target}"),
                    },
                    unresolved_names=[],
                ),
            ]
            unresolved = []
            route_axis_validation = {
                "track_order": "pass",
                "endpoint_continuity": "pass",
                "resume_gaps": "pass",
                "route_direction": "pass",
            }
            source_refs = [ref]
            source_hashes = {ref: route_sha}
        source_sha = _fixed_hash(source)
        return MissionBaselineDraft(
            artifact_kind="mission_baseline_candidate",
            schema_version="missionBaselineCandidate.v1",
            draft_id=f"baseline-draft.{source_sha[:16]}",
            source_mode=request.mode,
            source_sha256=source_sha,
            source_text=source,
            source_refs=source_refs,
            source_hashes=source_hashes,
            route_axis_validation=route_axis_validation,
            days=days,
            validation_state="needs_review" if unresolved else "valid",
            unresolved_gaps=unresolved,
            proposal_profile="legacy_sparse",
        )

    def generate_baseline_draft(
        self, request: BaselineAuthoringRequest
    ) -> MissionBaselineDraft:
        return self.preview_baseline(request)

    def preview_baseline_patch(
        self, request: BaselinePatchPreviewRequest
    ) -> BaselinePatchPreviewResult:
        _, candidate = self._load_immutable_baseline_candidate(
            request.base_candidate_ref,
            request.base_candidate_sha256,
        )
        draft_payload = candidate.get("draft")
        if not isinstance(draft_payload, dict):
            draft_payload = {
                "artifact_kind": "mission_baseline_candidate",
                "schema_version": "missionBaselineCandidate.v1",
                "draft_id": str(candidate.get("source_draft_id") or "legacy-draft"),
                "source_mode": candidate["source_mode"],
                "source_sha256": candidate["source_sha256"],
                "source_text": str(candidate.get("source_text") or ""),
                "source_refs": list(candidate.get("source_refs") or []),
                "source_hashes": dict(candidate.get("source_hashes") or {}),
                "route_axis_validation": dict(
                    candidate.get("route_axis_validation") or {}
                ),
                "days": candidate["days"],
                "validation_state": candidate["validation_state"],
                "unresolved_gaps": candidate["unresolved_gaps"],
            }
        draft = MissionBaselineDraft.model_validate(draft_payload)
        day_payloads = {
            day.mission_day_id: day.model_dump(mode="json") for day in draft.days
        }
        assumptions = list(draft.assumptions)
        additions: list[str] = []
        removals: list[str] = []
        reordered: list[str] = []
        route_axis_validation = dict(draft.route_axis_validation)
        source_refs = list(draft.source_refs)
        source_hashes = dict(draft.source_hashes)
        for operation in request.operations:
            if operation.operation == "add_assumption":
                if not operation.assumption:
                    raise ContextualPermissionConflict(
                        "invalid_baseline_patch", "add_assumption requires text."
                    )
                assumptions.append(operation.assumption)
                continue
            if operation.operation in {"confirm_route_axis", "bind_reviewed_graph"}:
                if not operation.target_ref or not operation.target_sha256:
                    raise ContextualPermissionConflict(
                        "invalid_baseline_patch",
                        f"{operation.operation} requires a reviewed ref and hash.",
                    )
                if not _SHA256_PATTERN.fullmatch(operation.target_sha256):
                    raise ContextualPermissionConflict(
                        "invalid_baseline_patch", "Reviewed evidence hash is invalid."
                    )
                source_refs.append(operation.target_ref)
                source_hashes[operation.target_ref] = operation.target_sha256
                if operation.operation == "confirm_route_axis":
                    route_axis_validation = {
                        "track_order": "pass",
                        "endpoint_continuity": "pass",
                        "resume_gaps": "pass",
                        "route_direction": "pass",
                    }
                continue
            if not operation.mission_day_id or operation.mission_day_id not in day_payloads:
                raise ContextualPermissionConflict(
                    "invalid_baseline_patch", "Patch mission day is not present."
                )
            day = day_payloads[operation.mission_day_id]
            mentions = list(day.get("ordered_place_mentions") or [])
            aliases = list(day.get("operator_aliases") or [])
            resolved = list(day.get("resolved_targets") or [])
            unresolved_names = list(day.get("unresolved_names") or [])
            if operation.operation == "add_target":
                if not operation.target_label:
                    raise ContextualPermissionConflict(
                        "invalid_baseline_patch", "add_target requires a label."
                    )
                mentions.append(operation.target_label)
                unresolved_names.append(operation.target_label)
                additions.append(
                    f"{operation.mission_day_id}:{operation.target_label}"
                )
            elif operation.operation == "remove_target":
                if operation.target_label not in mentions:
                    raise ContextualPermissionConflict(
                        "invalid_baseline_patch", "remove_target label is missing."
                    )
                mentions.remove(str(operation.target_label))
                resolved = [
                    item for item in resolved if item != operation.target_label
                ]
                unresolved_names = [
                    item for item in unresolved_names if item != operation.target_label
                ]
                removals.append(
                    f"{operation.mission_day_id}:{operation.target_label}"
                )
            elif operation.operation == "reorder_target":
                if operation.from_index is None or operation.to_index is None:
                    raise ContextualPermissionConflict(
                        "invalid_baseline_patch", "reorder_target requires two indexes."
                    )
                try:
                    moved = mentions.pop(operation.from_index)
                    mentions.insert(operation.to_index, moved)
                except IndexError as exc:
                    raise ContextualPermissionConflict(
                        "invalid_baseline_patch", "Target reorder index is out of range."
                    ) from exc
                reordered.append(
                    f"{operation.mission_day_id}:{moved}:{operation.from_index}->{operation.to_index}"
                )
            elif operation.operation == "resolve_target":
                if (
                    not operation.target_label
                    or not operation.target_ref
                    or not operation.target_sha256
                    or not _SHA256_PATTERN.fullmatch(operation.target_sha256)
                ):
                    raise ContextualPermissionConflict(
                        "invalid_baseline_patch",
                        "resolve_target requires label, reviewed ref, and hash.",
                    )
                if (
                    operation.target_label not in mentions
                    and operation.target_label not in aliases
                ):
                    raise ContextualPermissionConflict(
                        "invalid_baseline_patch",
                        "Resolved target or operator alias is not in this day.",
                    )
                if operation.target_label not in resolved:
                    resolved.append(operation.target_label)
                unresolved_names = [
                    item
                    for item in unresolved_names
                    if item not in {operation.target_label, f"alias:{operation.target_label}"}
                ]
                refs = dict(day.get("resolved_target_refs") or {})
                hashes = dict(day.get("resolved_target_hashes") or {})
                refs[operation.target_label] = operation.target_ref
                hashes[operation.target_label] = operation.target_sha256
                day["resolved_target_refs"] = refs
                day["resolved_target_hashes"] = hashes
                additions.append(
                    f"resolved:{operation.mission_day_id}:{operation.target_label}"
                )
            elif operation.operation == "confirm_coordinate_crs":
                coordinates = list(day.get("coordinate_hints") or [])
                matched = False
                for coordinate in coordinates:
                    if coordinate.get("raw_text") == operation.coordinate_text:
                        coordinate["confirmed_crs"] = operation.confirmed_crs
                        coordinate["reviewed"] = bool(operation.confirmed_crs)
                        matched = True
                if not matched:
                    raise ContextualPermissionConflict(
                        "invalid_baseline_patch", "Coordinate hint is not present."
                    )
                unresolved_names = [
                    item
                    for item in unresolved_names
                    if item != f"coordinate_crs:{operation.coordinate_text}"
                ]
                day["coordinate_hints"] = coordinates
            elif operation.operation == "review_branch":
                branches = list(day.get("branch_candidates") or [])
                matched = False
                for branch in branches:
                    if branch.get("label") == operation.target_label:
                        branch["reviewed"] = True
                        matched = True
                if not matched:
                    raise ContextualPermissionConflict(
                        "invalid_baseline_patch", "Branch candidate is not present."
                    )
                unresolved_names = [
                    item
                    for item in unresolved_names
                    if item != f"branch_review:{operation.target_label}"
                ]
                day["branch_candidates"] = branches
            day["ordered_place_mentions"] = mentions
            day["resolved_targets"] = resolved
            day["unresolved_names"] = unresolved_names
            day_payloads[operation.mission_day_id] = day
        days = [
            BaselineDayDraft.model_validate(day_payloads[day.mission_day_id])
            for day in draft.days
        ]
        unresolved_items = [
            f"{day.mission_day_id}:{item}"
            for day in days
            if day.day_kind == "on_trail"
            for item in day.unresolved_names
        ]
        axis_pass = route_axis_validation and all(
            state == "pass" for state in route_axis_validation.values()
        )
        graph_bound = any(
            "graph" in ref.casefold() for ref in source_refs
        )
        if not graph_bound:
            unresolved_items.append("reviewed_mission_graph_binding")
        if not axis_pass:
            unresolved_items.append("route_axis_admission")
        provisional_draft = draft.model_copy(
            update={
                "draft_id": "baseline-patch.pending",
                "source_refs": list(dict.fromkeys(source_refs)),
                "source_hashes": source_hashes,
                "route_axis_validation": route_axis_validation,
                "days": days,
                "assumptions": assumptions,
                "conversation_refs": request.conversation_refs,
                "base_candidate_ref": request.base_candidate_ref,
                "base_candidate_sha256": request.base_candidate_sha256,
                "patch_sha256": None,
                "validation_state": "valid" if not unresolved_items else "needs_review",
                "unresolved_gaps": unresolved_items,
            }
        )
        patch_sha = _digest(
            {
                "base_candidate_ref": request.base_candidate_ref,
                "base_candidate_sha256": request.base_candidate_sha256,
                "operations": request.operations,
                "conversation_refs": request.conversation_refs,
                "conversation_hashes": request.conversation_hashes,
                "draft": provisional_draft,
            }
        )
        patched_draft = provisional_draft.model_copy(
            update={
                "draft_id": f"baseline-patch.{patch_sha[:16]}",
                "patch_sha256": patch_sha,
            }
        )
        return BaselinePatchPreviewResult(
            artifact_kind="mission_baseline_patch_preview",
            schema_version="missionBaselinePatchPreview.v1",
            base_candidate_ref=request.base_candidate_ref,
            base_candidate_sha256=request.base_candidate_sha256,
            patch_sha256=patch_sha,
            operations=request.operations,
            conversation_refs=request.conversation_refs,
            conversation_hashes=request.conversation_hashes,
            additions=additions,
            removals=removals,
            reordered=reordered,
            new_assumptions=[
                item for item in assumptions if item not in draft.assumptions
            ],
            unresolved_items=unresolved_items,
            draft=patched_draft,
        )

    def save_baseline_candidate(
        self, request: BaselineCandidateSaveRequest
    ) -> BaselineCandidateSaveReceipt:
        if request.expected_source_sha256 != request.draft.source_sha256:
            raise ContextualPermissionConflict(
                "stale_source_hash", "The baseline source changed before save."
            )
        return self._persist_baseline_candidate(
            draft=request.draft,
            idempotency_key=request.idempotency_key,
            explicit_confirmation=request.explicit_confirmation,
            parent_candidate=None,
            request_payload=request,
        )

    def save_baseline_patch(
        self, request: BaselinePatchSaveRequest
    ) -> BaselineCandidateSaveReceipt:
        patch = request.patch
        if request.expected_base_candidate_sha256 != patch.base_candidate_sha256:
            raise ContextualPermissionConflict(
                "stale_candidate_hash", "The patch base hash changed before save."
            )
        _, parent = self._load_immutable_baseline_candidate(
            patch.base_candidate_ref,
            patch.base_candidate_sha256,
        )
        provisional_draft = patch.draft.model_copy(
            update={"draft_id": "baseline-patch.pending", "patch_sha256": None}
        )
        expected_patch_sha = _digest(
            {
                "base_candidate_ref": patch.base_candidate_ref,
                "base_candidate_sha256": patch.base_candidate_sha256,
                "operations": patch.operations,
                "conversation_refs": patch.conversation_refs,
                "conversation_hashes": patch.conversation_hashes,
                "draft": provisional_draft,
            }
        )
        if (
            patch.patch_sha256 != expected_patch_sha
            or patch.draft.patch_sha256 != patch.patch_sha256
        ):
            raise ContextualPermissionConflict(
                "patch_hash_mismatch", "The proposed patch hash no longer matches."
            )
        return self._persist_baseline_candidate(
            draft=patch.draft,
            idempotency_key=request.idempotency_key,
            explicit_confirmation=request.explicit_confirmation,
            parent_candidate=parent,
            request_payload=request,
        )

    def _recompute_baseline_review_requirements(
        self, draft: MissionBaselineDraft
    ) -> BaselineReviewRequirements:
        day_ids = [
            day.mission_day_id
            for day in draft.days
            if day.day_kind == "on_trail"
            and day.primary_day_end_proposal is not None
        ]
        uncertainty_ids = [
            item.uncertainty_id
            for item in draft.uncertainties
            if item.disposition == "acknowledgeable"
            and item.required_review_surface == "permission"
        ]
        generic_handoff_ids: list[str] = []
        for ref in draft.source_refs:
            if "retreat" not in ref.casefold():
                continue
            expected_sha = draft.source_hashes.get(ref)
            path = self._resolve_project_ref(ref)
            if not expected_sha or not path.is_file() or _file_sha256(path) != expected_sha:
                raise ContextualPermissionConflict(
                    "baseline_source_binding_mismatch",
                    f"The bound Safety / Emergency handoff source changed: {ref}",
                )
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                generic_handoff_ids.extend(
                    f"branch:{str(item.get('candidate_id'))}"
                    for item in payload
                    if isinstance(item, dict) and item.get("candidate_id")
                )
        concrete_handoff_ids = [
            f"target:{proposal.proposal_id}"
            for day in draft.days
            for proposal in [*day.retreat_candidates, *day.emergency_bivy_candidates]
        ]
        pending_ids = list(dict.fromkeys([*generic_handoff_ids, *concrete_handoff_ids]))
        return BaselineReviewRequirements(
            required_reviewed_day_ids=day_ids,
            required_acknowledgment_uncertainty_ids=uncertainty_ids,
            pending_safety_handoff_item_ids=pending_ids,
            safety_handoff_required=bool(pending_ids),
        )

    def _validate_proposal_first_draft(self, draft: MissionBaselineDraft) -> None:
        project = json.loads(
            self._resolve_project_ref("project.json").read_text(encoding="utf-8")
        )
        rich_reference_declared = bool(project.get("reference_segment_timing_ref"))
        proposal_fields_present = bool(
            draft.timing_evidence
            or draft.proposal_summary
            or draft.review_requirements
            or any(day.primary_day_end_proposal for day in draft.days)
        )
        if draft.proposal_profile == "legacy_sparse":
            if proposal_fields_present or (
                draft.source_mode == "reference_gpx" and rich_reference_declared
            ):
                raise ContextualPermissionConflict(
                    "baseline_proposal_profile_downgrade",
                    "A proposal-first Ref. GPX draft cannot use the legacy acceptance profile.",
                )
            return
        if (
            draft.source_mode != "reference_gpx"
            or draft.proposal_strategy_id
            != "destination-boundary.segment-quantile-target"
            or draft.proposal_strategy_version != BASELINE_AUTO_PROPOSAL_VERSION
            or draft.timing_evidence is None
            or draft.proposal_summary is None
            or draft.review_requirements is None
        ):
            raise ContextualPermissionConflict(
                "baseline_proposal_contract_incomplete",
                "The Ref. GPX proposal profile is missing its strategy, timing, summary, or review contract.",
            )
        if draft.unresolved_gaps or any(
            item.disposition == "blocking" for item in draft.uncertainties
        ):
            raise ContextualPermissionConflict(
                "baseline_promotion_blocked",
                "Blocking baseline gaps cannot be acknowledged through compact review.",
            )
        timing_path = self._resolve_project_ref(draft.timing_evidence.ref)
        if (
            not timing_path.is_file()
            or _file_sha256(timing_path) != draft.timing_evidence.sha256
        ):
            raise ContextualPermissionConflict(
                "baseline_timing_binding_mismatch",
                "The bound timing evidence is missing or changed.",
            )
        timing_payload = json.loads(timing_path.read_text(encoding="utf-8"))
        timing_segments = (
            timing_payload.get("segments") if isinstance(timing_payload, dict) else None
        )
        if not isinstance(timing_segments, list):
            raise ContextualPermissionConflict(
                "baseline_timing_binding_mismatch",
                "The bound timing evidence has no ordered segment contract.",
            )
        source_segment_ids = [
            str(item.get("segment_id"))
            for item in timing_segments
            if isinstance(item, dict) and item.get("segment_id")
        ]
        trail_days = [day for day in draft.days if day.day_kind == "on_trail"]
        if not trail_days:
            raise ContextualPermissionConflict(
                "baseline_proposal_contract_incomplete",
                "The proposal-first baseline contains no on-trail day.",
            )
        previous_end: BaselineRouteAnchor | None = None
        proposed_segment_ids: list[str] = []
        proposal_ids: set[str] = set()
        for day in trail_days:
            if (
                day.start_anchor is None
                or day.primary_day_end_proposal is None
                or day.eta_proposal is None
                or not day.segment_ids
            ):
                raise ContextualPermissionConflict(
                    "baseline_proposal_contract_incomplete",
                    f"{day.mission_day_id} is missing a start, day end, ETA, or segment list.",
                )
            if previous_end is not None and day.start_anchor != previous_end:
                raise ContextualPermissionConflict(
                    "baseline_day_continuity_invalid",
                    "Each proposal day must start at the previous proposed day end.",
                )
            target = day.primary_day_end_proposal
            if (
                target.mission_day_id != day.mission_day_id
                or target.kind != "day_end"
                or target.target.route_order_m <= day.start_anchor.route_order_m
                or target.proposal_id in proposal_ids
            ):
                raise ContextualPermissionConflict(
                    "baseline_day_destination_invalid",
                    f"{day.mission_day_id} has an invalid primary destination proposal.",
                )
            proposal_ids.add(target.proposal_id)
            eta_ids = [
                *day.eta_proposal.supporting_segment_ids,
                *day.eta_proposal.unsupported_segment_ids,
            ]
            if set(eta_ids) != set(day.segment_ids) or len(eta_ids) != len(day.segment_ids):
                raise ContextualPermissionConflict(
                    "baseline_eta_segment_mismatch",
                    f"{day.mission_day_id} ETA coverage does not match its segments.",
                )
            proposed_segment_ids.extend(day.segment_ids)
            previous_end = target.target
        if proposed_segment_ids != source_segment_ids:
            raise ContextualPermissionConflict(
                "baseline_segment_coverage_invalid",
                "Proposal days must cover every timing segment exactly once and in order.",
            )
        expected_requirements = self._recompute_baseline_review_requirements(draft)
        if draft.review_requirements != expected_requirements:
            raise ContextualPermissionConflict(
                "baseline_review_requirements_mismatch",
                "Stored compact-review requirements do not match deterministic recomputation.",
            )

    def _persist_baseline_candidate(
        self,
        *,
        draft: MissionBaselineDraft,
        idempotency_key: str,
        explicit_confirmation: bool,
        parent_candidate: dict[str, object] | None,
        request_payload: WorkbenchModel,
    ) -> BaselineCandidateSaveReceipt:
        self._validate_proposal_first_draft(draft)
        if not explicit_confirmation:
            raise ContextualPermissionConflict(
                "explicit_confirmation_required",
                "Saving a candidate version requires explicit confirmation.",
            )
        if not _SAFE_ID_PATTERN.fullmatch(idempotency_key):
            raise ContextualPermissionConflict(
                "invalid_idempotency_key", "Invalid idempotency key."
            )
        baseline_id = str(
            parent_candidate.get("baseline_id")
            if parent_candidate is not None
            else f"baseline.{draft.source_sha256[:16]}"
        )
        if not _SAFE_ID_PATTERN.fullmatch(baseline_id):
            raise ContextualPermissionConflict(
                "invalid_baseline_candidate_id",
                "The baseline candidate id is not safe for storage.",
            )
        request_sha = _digest(request_payload)
        version_id = f"version.{_fixed_hash(idempotency_key)[:16]}"
        version_path = self._resolve_project_write_path(
            "candidates",
            "mission_baselines",
            baseline_id,
            "versions",
            f"{version_id}.json",
        )
        payload: dict[str, object] = {
            "artifact_kind": "mission_baseline_candidate_version",
            "schema_version": "missionBaselineCandidate.v1",
            "baseline_id": baseline_id,
            "version_id": version_id,
            "parent_version_id": (
                str(parent_candidate.get("version_id"))
                if parent_candidate is not None
                else None
            ),
            "supersedes_version_id": (
                str(parent_candidate.get("version_id"))
                if parent_candidate is not None
                else None
            ),
            "request_sha256": request_sha,
            "idempotency_key": idempotency_key,
            "source_mode": draft.source_mode,
            "source_sha256": draft.source_sha256,
            "source_text": draft.source_text,
            "source_refs": draft.source_refs,
            "source_hashes": draft.source_hashes,
            "source_draft_id": draft.draft_id,
            "base_candidate_ref": draft.base_candidate_ref,
            "base_candidate_sha256": draft.base_candidate_sha256,
            "patch_sha256": draft.patch_sha256,
            "conversation_refs": draft.conversation_refs,
            "route_axis_validation": draft.route_axis_validation,
            "days": [day.model_dump(mode="json") for day in draft.days],
            "draft": draft.model_dump(mode="json"),
            "unresolved_gaps": draft.unresolved_gaps,
            "validation_state": draft.validation_state,
            "proposal_profile": draft.proposal_profile,
            "proposal_strategy_id": draft.proposal_strategy_id,
            "proposal_strategy_version": draft.proposal_strategy_version,
            "timing_evidence": (
                draft.timing_evidence.model_dump(mode="json")
                if draft.timing_evidence is not None
                else None
            ),
            "proposal_summary": (
                draft.proposal_summary.model_dump(mode="json")
                if draft.proposal_summary is not None
                else None
            ),
            "uncertainties": [
                item.model_dump(mode="json") for item in draft.uncertainties
            ],
            "review_requirements": (
                draft.review_requirements.model_dump(mode="json")
                if draft.review_requirements is not None
                else None
            ),
            "safety_handoff_summary": draft.safety_handoff_summary,
            "promotion_gates": {
                "route_critical_names_resolved": not draft.unresolved_gaps,
                "route_axis_order_pass": draft.route_axis_validation.get("track_order")
                == "pass",
                "endpoint_continuity_pass": draft.route_axis_validation.get(
                    "endpoint_continuity"
                )
                == "pass",
                "resume_gap_pass": draft.route_axis_validation.get("resume_gaps")
                == "pass",
                "route_direction_pass": draft.route_axis_validation.get(
                    "route_direction"
                )
                == "pass",
                "overnight_and_day_boundaries_reviewed": all(
                    day.day_kind == "logistics" or bool(day.resolved_targets)
                    for day in draft.days
                ),
                "graph_compilation_pass": any(
                    "graph" in ref.casefold() for ref in draft.source_refs
                ),
                "deterministic_validation_pass": draft.validation_state == "valid",
            },
            "review_ready": False,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "departure_approval_granted": False,
            "writes_performed": True,
            "version_sha256": "0" * 64,
        }
        payload["review_ready"] = all(payload["promotion_gates"].values())
        payload["version_sha256"] = _digest(
            {key: value for key, value in payload.items() if key != "version_sha256"}
        )
        with _STORE_LOCK:
            if version_path.is_file():
                existing = json.loads(version_path.read_text(encoding="utf-8"))
                if existing.get("request_sha256") != request_sha:
                    raise ContextualPermissionConflict(
                        "idempotency_conflict",
                        "The candidate idempotency key was already used.",
                    )
                payload = existing
            else:
                self._write_new_json(version_path, payload)
        return BaselineCandidateSaveReceipt(
            baseline_id=baseline_id,
            version_id=version_id,
            version_ref=version_path.relative_to(self.project_root).as_posix(),
            version_sha256=str(payload["version_sha256"]),
            source_sha256=str(payload["source_sha256"]),
            idempotency_key=idempotency_key,
            parent_version_id=(
                str(payload["parent_version_id"])
                if payload.get("parent_version_id")
                else None
            ),
            validation_state=str(payload["validation_state"]),
            unresolved_gaps=list(payload["unresolved_gaps"]),
            review_ready=bool(payload["review_ready"]),
        )

    def accept_reviewed_baseline(
        self, request: BaselineReviewAcceptRequest
    ) -> BaselineReviewAcceptReceipt:
        if not request.explicit_confirmation:
            raise ContextualPermissionConflict(
                "explicit_confirmation_required",
                "Accept Reviewed Baseline requires explicit confirmation.",
            )
        _, candidate = self._load_immutable_baseline_candidate(
            request.candidate_ref,
            request.candidate_sha256,
        )
        candidate_draft = MissionBaselineDraft.model_validate(candidate.get("draft"))
        self._validate_proposal_first_draft(candidate_draft)
        if not candidate.get("review_ready"):
            raise ContextualPermissionConflict(
                "baseline_promotion_blocked",
                "The candidate has unresolved promotion gates.",
            )
        if not all(candidate.get("promotion_gates", {}).values()):
            raise ContextualPermissionConflict(
                "baseline_promotion_blocked",
                "Every deterministic baseline promotion gate must pass.",
            )
        proposal_first = candidate.get("proposal_profile") == "ref_gpx_proposal_v1"
        review_requirements = candidate.get("review_requirements")
        requirements = (
            review_requirements if isinstance(review_requirements, dict) else {}
        )
        required_day_ids = list(requirements.get("required_reviewed_day_ids") or [])
        required_uncertainty_ids = list(
            requirements.get("required_acknowledgment_uncertainty_ids") or []
        )
        pending_handoff_ids = list(
            requirements.get("pending_safety_handoff_item_ids") or []
        )
        safety_handoff_required = bool(requirements.get("safety_handoff_required"))
        if proposal_first and (
            set(request.reviewed_day_ids) != set(required_day_ids)
            or set(request.acknowledged_uncertainty_ids)
            != set(required_uncertainty_ids)
            or request.safety_handoff_acknowledged != safety_handoff_required
        ):
            raise ContextualPermissionConflict(
                "baseline_review_set_mismatch",
                "The compact review must enumerate the exact day, uncertainty, and Safety / Emergency handoff sets.",
            )
        canonical_reviewed_day_ids = required_day_ids if proposal_first else request.reviewed_day_ids
        canonical_uncertainty_ids = (
            required_uncertainty_ids
            if proposal_first
            else request.acknowledged_uncertainty_ids
        )
        normalized_request = request.model_copy(
            update={
                "reviewed_day_ids": canonical_reviewed_day_ids,
                "acknowledged_uncertainty_ids": canonical_uncertainty_ids,
            }
        )
        request_sha = _digest(normalized_request)
        review_id = f"review.{_fixed_hash(request.idempotency_key)[:16]}"
        receipt_path = self._resolve_project_write_path(
            "reviews",
            "mission_baseline_accept_receipts",
            f"{review_id}.json",
        )
        baseline_id = str(candidate["baseline_id"])
        reviewed_path = self._resolve_project_write_path(
            "outputs",
            "mission_baselines",
            baseline_id,
            "reviewed",
            f"{review_id}.json",
        )
        stale_refs = [
            "outputs/contextual_permission/workbench_seed.json",
            "candidates/contextual_permission_rules.json",
            "outputs/planned_eta.json",
        ]
        reviewed_day_end_bindings = [
            {
                "day_id": str(day["mission_day_id"]),
                "proposal_id": str(day["primary_day_end_proposal"]["proposal_id"]),
                "target_ref": str(
                    day["primary_day_end_proposal"]["target"]["artifact"]["ref"]
                ),
                "target_sha256": str(
                    day["primary_day_end_proposal"]["target"]["artifact"]["sha256"]
                ),
            }
            for day in candidate.get("days") or []
            if isinstance(day, dict)
            and str(day.get("mission_day_id")) in canonical_reviewed_day_ids
            and isinstance(day.get("primary_day_end_proposal"), dict)
            and isinstance(day["primary_day_end_proposal"].get("target"), dict)
        ]
        reviewed_payload: dict[str, object] = {
            "artifact_kind": "reviewed_mission_baseline",
            "schema_version": "reviewedMissionBaseline.v1",
            "review_id": review_id,
            "candidate_ref": request.candidate_ref,
            "candidate_sha256": request.candidate_sha256,
            "baseline_id": baseline_id,
            "version_id": candidate["version_id"],
            "source_mode": candidate["source_mode"],
            "source_sha256": candidate["source_sha256"],
            "days": candidate["days"],
            "proposal_profile": candidate.get("proposal_profile"),
            "proposal_strategy_id": candidate.get("proposal_strategy_id"),
            "proposal_strategy_version": candidate.get("proposal_strategy_version"),
            "timing_evidence": candidate.get("timing_evidence"),
            "proposal_summary": candidate.get("proposal_summary"),
            "uncertainties": candidate.get("uncertainties") or [],
            "reviewed_day_ids": canonical_reviewed_day_ids,
            "review_scope": "permission_day_end_only",
            "reviewed_day_end_bindings": reviewed_day_end_bindings,
            "acknowledged_uncertainty_ids": canonical_uncertainty_ids,
            "safety_handoff_acknowledged": request.safety_handoff_acknowledged,
            "pending_safety_handoff_item_ids": pending_handoff_ids,
            "safety_handoff_scope": "visibility_and_cross_feature_handoff_only",
            "reviewer_alias": request.reviewer_alias,
            "accepted_at": self._now(),
            "candidate_only": True,
            "runtime_safety_truth": False,
            "departure_approval_granted": False,
            "reviewed_baseline_sha256": "0" * 64,
        }
        reviewed_payload["reviewed_baseline_sha256"] = _digest(
            {
                key: value
                for key, value in reviewed_payload.items()
                if key != "reviewed_baseline_sha256"
            }
        )
        receipt_payload: dict[str, object] = {
            "artifact_kind": "mission_baseline_review_decision",
            "schema_version": "missionBaselineReviewDecision.v1",
            "review_id": review_id,
            "request_sha256": request_sha,
            "idempotency_key": request.idempotency_key,
            "candidate_ref": request.candidate_ref,
            "candidate_sha256": request.candidate_sha256,
            "reviewed_baseline_ref": reviewed_path.relative_to(self.project_root).as_posix(),
            "reviewed_baseline_sha256": reviewed_payload[
                "reviewed_baseline_sha256"
            ],
            "reviewer_alias": request.reviewer_alias,
            "reviewed_day_ids": canonical_reviewed_day_ids,
            "review_scope": "permission_day_end_only",
            "reviewed_day_end_bindings": reviewed_day_end_bindings,
            "acknowledged_uncertainty_ids": canonical_uncertainty_ids,
            "safety_handoff_acknowledged": request.safety_handoff_acknowledged,
            "pending_safety_handoff_item_ids": pending_handoff_ids,
            "safety_handoff_scope": "visibility_and_cross_feature_handoff_only",
            "stale_dependency_refs": stale_refs,
            "review_sha256": "0" * 64,
            "writes_performed": True,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "departure_approval_granted": False,
            "final_mission_graph_generated": False,
            "active_runtime_session_updated": False,
            "safety_api_called": False,
            "outbound_action_performed": False,
            "outbound_transport_invoked": False,
            "external_send_performed": False,
            "hardware_control_performed": False,
        }
        receipt_payload["review_sha256"] = _digest(
            {key: value for key, value in receipt_payload.items() if key != "review_sha256"}
        )
        with _STORE_LOCK:
            if receipt_path.is_file():
                existing = json.loads(receipt_path.read_text(encoding="utf-8"))
                if existing.get("request_sha256") != request_sha:
                    raise ContextualPermissionConflict(
                        "idempotency_conflict",
                        "The review idempotency key was already used.",
                    )
                receipt_payload = existing
            else:
                self._write_new_json(reviewed_path, reviewed_payload)
                self._write_new_json(receipt_path, receipt_payload)
                self._append_review_decision_log(receipt_payload)
                self._record_baseline_selection_and_staleness(
                    reviewed_path=reviewed_path,
                    reviewed_sha256=str(reviewed_payload["reviewed_baseline_sha256"]),
                    review_id=review_id,
                    stale_refs=stale_refs,
                )
        return BaselineReviewAcceptReceipt(
            review_id=review_id,
            review_ref=receipt_path.relative_to(self.project_root).as_posix(),
            review_sha256=str(receipt_payload["review_sha256"]),
            reviewed_baseline_ref=str(receipt_payload["reviewed_baseline_ref"]),
            reviewed_baseline_sha256=str(
                receipt_payload["reviewed_baseline_sha256"]
            ),
            candidate_ref=request.candidate_ref,
            candidate_sha256=request.candidate_sha256,
            stale_dependency_refs=list(receipt_payload["stale_dependency_refs"]),
            reviewed_day_ids=list(receipt_payload.get("reviewed_day_ids") or []),
            acknowledged_uncertainty_ids=list(
                receipt_payload.get("acknowledged_uncertainty_ids") or []
            ),
            safety_handoff_acknowledged=bool(
                receipt_payload.get("safety_handoff_acknowledged")
            ),
        )

    def _append_review_decision_log(self, receipt: dict[str, object]) -> None:
        log_path = self._resolve_project_write_path(
            "reviews", "review_decision_log.json"
        )
        if log_path.is_file():
            current = json.loads(log_path.read_text(encoding="utf-8"))
            if not isinstance(current, list):
                raise ContextualPermissionConflict(
                    "invalid_review_decision_log", "Review decision log must be a list."
                )
        else:
            current = []
        if not any(item.get("review_id") == receipt["review_id"] for item in current):
            self._write_replace_json(log_path, [*current, receipt])

    def _record_baseline_selection_and_staleness(
        self,
        *,
        reviewed_path: Path,
        reviewed_sha256: str,
        review_id: str,
        stale_refs: list[str],
    ) -> None:
        project_path = self._resolve_project_ref("project.json")
        project = json.loads(project_path.read_text(encoding="utf-8"))
        updated_project = {
            **project,
            "reviewed_mission_baseline_ref": reviewed_path.relative_to(
                self.project_root
            ).as_posix(),
            "reviewed_mission_baseline_sha256": reviewed_sha256,
            "reviewed_mission_baseline_receipt_id": review_id,
        }
        self._write_replace_json(project_path, updated_project)
        marker_path = self._resolve_project_write_path(
            "outputs",
            "contextual_permission",
            "stale_after_baseline_acceptance.json",
        )
        marker = {
            "artifact_kind": "contextual_permission_dependency_staleness",
            "schema_version": "contextualPermissionDependencyStaleness.v1",
            "review_id": review_id,
            "reviewed_baseline_sha256": reviewed_sha256,
            "stale_dependency_refs": stale_refs,
            "requires_explicit_rebuild": True,
            "active_runtime_session_updated": False,
        }
        self._write_replace_json(marker_path, marker)

    def rebuild_contextual_permission_projection(
        self,
        request: ContextualPermissionProjectionRebuildRequest,
    ) -> ContextualPermissionProjectionRebuildReceipt:
        if not request.explicit_confirmation:
            raise ContextualPermissionConflict(
                "explicit_confirmation_required",
                "Contextual Permission projection rebuild requires explicit confirmation.",
            )
        project_path = self._resolve_project_ref("project.json")
        project = json.loads(project_path.read_text(encoding="utf-8"))
        reviewed_ref = str(project.get("reviewed_mission_baseline_ref") or "")
        reviewed_sha256 = str(project.get("reviewed_mission_baseline_sha256") or "")
        if not reviewed_ref or not _SHA256_PATTERN.fullmatch(reviewed_sha256):
            raise ContextualPermissionConflict(
                "reviewed_baseline_input_missing",
                "A selected reviewed baseline is required before projection rebuild.",
            )
        if reviewed_sha256 != request.expected_reviewed_baseline_sha256:
            raise ContextualPermissionConflict(
                "reviewed_baseline_replaced",
                "The selected reviewed baseline changed before projection rebuild.",
            )
        reviewed_path = self._resolve_project_ref(reviewed_ref)
        try:
            reviewed = json.loads(reviewed_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContextualPermissionConflict(
                "invalid_reviewed_baseline",
                "The selected reviewed baseline is unavailable or invalid.",
            ) from exc
        self._validate_selected_reviewed_baseline(
            reviewed=reviewed,
            reviewed_ref=reviewed_ref,
            reviewed_sha256=reviewed_sha256,
        )
        days = [
            BaselineDayDraft.model_validate(day)
            for day in reviewed.get("days") or []
            if isinstance(day, dict) and day.get("day_kind") == "on_trail"
        ]
        if not days or any(day.primary_day_end_proposal is None for day in days):
            raise ContextualPermissionConflict(
                "reviewed_baseline_missing_day_end_bindings",
                "The selected baseline predates proposal-first day-end bindings; generate and accept a new Ref. GPX proposal first.",
            )
        reviewed_day_ids = list(reviewed.get("reviewed_day_ids") or [])
        if reviewed_day_ids != [day.mission_day_id for day in days]:
            raise ContextualPermissionConflict(
                "reviewed_baseline_day_set_mismatch",
                "The reviewed baseline does not enumerate the exact on-trail day set.",
            )
        review_id = str(reviewed.get("review_id") or "")
        if not _SAFE_ID_PATTERN.fullmatch(review_id):
            raise ContextualPermissionConflict(
                "invalid_reviewed_baseline",
                "The reviewed baseline has no safe acceptance receipt identity.",
            )
        review_receipt_ref = (
            f"reviews/mission_baseline_accept_receipts/{review_id}.json"
        )
        review_receipt_path = self._resolve_project_ref(review_receipt_ref)
        self._validate_baseline_review_receipt(
            path=review_receipt_path,
            reviewed_ref=reviewed_ref,
            reviewed_sha256=reviewed_sha256,
        )
        review_receipt_sha256 = _file_sha256(review_receipt_path)
        request_sha256 = _digest(request)
        rebuild_id = f"permission-rebuild.{_fixed_hash(request.idempotency_key)[:16]}"
        rebuild_path = self._resolve_project_write_path(
            "reviews", "contextual_permission_rebuild_receipts", f"{rebuild_id}.json"
        )
        with _STORE_LOCK:
            if rebuild_path.is_file():
                return self._load_existing_projection_rebuild_receipt(
                    rebuild_path,
                    request_sha256=request_sha256,
                )
            plan_nodes = self._reviewed_baseline_plan_nodes(
                reviewed_sha256=reviewed_sha256,
                days=days,
            )
            rules = ContextualPermissionRulesArtifact(
                artifact_kind="pretrip_contextual_permission_rules",
                schema_version="contextual_permission_rules.v2",
                project_id=self.project_id,
                reviewed_baseline_ref=reviewed_ref,
                reviewed_baseline_sha256=reviewed_sha256,
                reviewed_by_human=False,
                review_receipt_ref=review_receipt_ref,
                review_receipt_sha256=review_receipt_sha256,
                plan_node_policies=[
                    ReviewedPlanNodePolicy(
                        node_id=node.node_id,
                        mission_day_id=node.mission_day_id,
                        adjustment_policy=node.adjustment_policy,
                        minimum_duration_minutes=node.minimum_duration_minutes,
                        policy_ref=node.source_rule_ref,
                        policy_sha256=node.source_rule_sha256,
                        reviewed=False,
                    )
                    for node in plan_nodes
                ],
                candidate_only=True,
                runtime_safety_truth=False,
            )
            rules_payload = rules.model_dump(mode="json")
            rules_sha256 = _formatted_json_sha256(rules_payload)
            planned_eta_ref = str(project.get("planned_eta_ref") or "outputs/planned_eta.json")
            planned_eta_path = self._resolve_project_ref(planned_eta_ref)
            planned_eta_payload = self._rebound_planned_eta(
                path=planned_eta_path,
                reviewed=reviewed,
                reviewed_ref=reviewed_ref,
                reviewed_sha256=reviewed_sha256,
                days=days,
            )
            planned_eta_sha256 = _formatted_json_sha256(planned_eta_payload)
            seed = self._rebound_workbench_seed(
                project=project,
                reviewed=reviewed,
                reviewed_ref=reviewed_ref,
                reviewed_sha256=reviewed_sha256,
                review_receipt_ref=review_receipt_ref,
                review_receipt_sha256=review_receipt_sha256,
                rules_sha256=rules_sha256,
                planned_eta_ref=planned_eta_ref,
                planned_eta_sha256=planned_eta_sha256,
                plan_nodes=plan_nodes,
                days=days,
            )
            seed_payload = seed.model_dump(mode="json")
            seed_sha256 = _formatted_json_sha256(seed_payload)
            rules_ref = DEFAULT_CONTEXTUAL_PERMISSION_RULES_REF.as_posix()
            seed_ref = DEFAULT_WORKBENCH_SEED_REF.as_posix()
            receipt_payload: dict[str, object] = {
                "rebuild_id": rebuild_id,
                "rebuild_ref": rebuild_path.relative_to(self.project_root).as_posix(),
                "rebuild_sha256": "0" * 64,
                "request_sha256": request_sha256,
                "idempotency_key": request.idempotency_key,
                "reviewed_baseline_ref": reviewed_ref,
                "reviewed_baseline_sha256": reviewed_sha256,
                "planned_eta_ref": planned_eta_ref,
                "planned_eta_sha256": planned_eta_sha256,
                "contextual_permission_rules_ref": rules_ref,
                "contextual_permission_rules_sha256": rules_sha256,
                "workbench_seed_ref": seed_ref,
                "workbench_seed_sha256": seed_sha256,
                "rule_review_state": "pending_review_only",
                "writes_performed": True,
                "candidate_only": True,
                "runtime_safety_truth": False,
                "departure_approval_granted": False,
                "active_runtime_session_updated": False,
                "safety_api_called": False,
                "outbound_action_performed": False,
                "outbound_transport_invoked": False,
                "external_send_performed": False,
                "hardware_control_performed": False,
            }
            receipt_payload["rebuild_sha256"] = _digest(
                {
                    key: value
                    for key, value in receipt_payload.items()
                    if key != "rebuild_sha256"
                }
            )
            receipt = ContextualPermissionProjectionRebuildReceipt.model_validate(
                receipt_payload
            )
            rules_path = self._resolve_project_write_path(*Path(rules_ref).parts)
            seed_path = self._resolve_project_write_path(*Path(seed_ref).parts)
            stale_marker_path = self._resolve_project_write_path(
                "outputs", "contextual_permission", "stale_after_baseline_acceptance.json"
            )
            updated_project = {
                **project,
                "planned_eta_ref": planned_eta_ref,
                "contextual_permission_rules_ref": rules_ref,
                "contextual_permission_bootstrap_ref": seed_ref,
                "contextual_permission_baseline_candidate_ref": reviewed.get(
                    "candidate_ref"
                ),
                "contextual_permission_baseline_candidate_sha256": reviewed.get(
                    "candidate_sha256"
                ),
                "contextual_permission_bootstrap_state": (
                    "baseline_bound_rule_review_pending"
                ),
                "contextual_permission_rule_count": len(plan_nodes),
                "contextual_permission_projection_rebuild_ref": receipt.rebuild_ref,
                "contextual_permission_projection_rebuild_sha256": (
                    receipt.rebuild_sha256
                ),
                "contextual_permission_collection_updated_at": self._now(),
            }
            resolved_marker = {
                "artifact_kind": "contextual_permission_dependency_staleness",
                "schema_version": "contextualPermissionDependencyStaleness.v1",
                "review_id": review_id,
                "reviewed_baseline_sha256": reviewed_sha256,
                "stale_dependency_refs": [],
                "resolved_dependency_refs": [planned_eta_ref, rules_ref, seed_ref],
                "requires_explicit_rebuild": False,
                "rebuild_receipt_ref": receipt.rebuild_ref,
                "rebuild_receipt_sha256": receipt.rebuild_sha256,
                "active_runtime_session_updated": False,
            }
            self._write_replace_json(planned_eta_path, planned_eta_payload)
            self._write_replace_json(rules_path, rules_payload)
            self._write_replace_json(seed_path, seed_payload)
            self._write_replace_json(stale_marker_path, resolved_marker)
            self._write_replace_json(project_path, updated_project)
            self._write_new_json(rebuild_path, receipt.model_dump(mode="json"))
            return receipt

    def _validate_selected_reviewed_baseline(
        self,
        *,
        reviewed: object,
        reviewed_ref: str,
        reviewed_sha256: str,
    ) -> None:
        if not isinstance(reviewed, dict):
            raise ContextualPermissionConflict(
                "invalid_reviewed_baseline", "The reviewed baseline must be an object."
            )
        if (
            reviewed.get("artifact_kind") != "reviewed_mission_baseline"
            or reviewed.get("schema_version") != "reviewedMissionBaseline.v1"
            or reviewed.get("reviewed_baseline_sha256") != reviewed_sha256
        ):
            raise ContextualPermissionConflict(
                "invalid_reviewed_baseline", "The reviewed baseline contract is invalid."
            )
        computed = _digest(
            {
                key: value
                for key, value in reviewed.items()
                if key != "reviewed_baseline_sha256"
            }
        )
        if computed != reviewed_sha256:
            raise ContextualPermissionConflict(
                "reviewed_baseline_hash_mismatch",
                "The selected reviewed baseline no longer matches its immutable hash.",
            )
        candidate_ref = str(reviewed.get("candidate_ref") or "")
        candidate_sha256 = str(reviewed.get("candidate_sha256") or "")
        _, candidate = self._load_immutable_baseline_candidate(
            candidate_ref,
            candidate_sha256,
        )
        candidate_draft = MissionBaselineDraft.model_validate(candidate.get("draft"))
        self._validate_proposal_first_draft(candidate_draft)
        if (
            candidate.get("baseline_id") != reviewed.get("baseline_id")
            or candidate.get("version_id") != reviewed.get("version_id")
            or reviewed.get("review_scope") != "permission_day_end_only"
            or reviewed_ref == candidate_ref
        ):
            raise ContextualPermissionConflict(
                "reviewed_baseline_lineage_mismatch",
                "The reviewed baseline is not bound to its immutable proposal candidate.",
            )

    def _validate_baseline_review_receipt(
        self,
        *,
        path: Path,
        reviewed_ref: str,
        reviewed_sha256: str,
    ) -> None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContextualPermissionConflict(
                "baseline_review_receipt_missing",
                "The reviewed baseline acceptance receipt is unavailable.",
            ) from exc
        if (
            not isinstance(payload, dict)
            or payload.get("artifact_kind") != "mission_baseline_review_decision"
            or payload.get("reviewed_baseline_ref") != reviewed_ref
            or payload.get("reviewed_baseline_sha256") != reviewed_sha256
        ):
            raise ContextualPermissionConflict(
                "baseline_review_receipt_mismatch",
                "The acceptance receipt does not bind the selected reviewed baseline.",
            )
        expected = _digest(
            {key: value for key, value in payload.items() if key != "review_sha256"}
        )
        if payload.get("review_sha256") != expected:
            raise ContextualPermissionConflict(
                "baseline_review_receipt_hash_mismatch",
                "The acceptance receipt no longer matches its immutable hash.",
            )

    def _load_existing_projection_rebuild_receipt(
        self,
        path: Path,
        *,
        request_sha256: str,
    ) -> ContextualPermissionProjectionRebuildReceipt:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            receipt = ContextualPermissionProjectionRebuildReceipt.model_validate(
                payload
            )
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise ContextualPermissionConflict(
                "invalid_projection_rebuild_receipt",
                "The existing projection rebuild receipt is invalid.",
            ) from exc
        expected_rebuild_sha256 = _digest(
            {
                key: value
                for key, value in payload.items()
                if key != "rebuild_sha256"
            }
        )
        if receipt.rebuild_sha256 != expected_rebuild_sha256:
            raise ContextualPermissionConflict(
                "projection_rebuild_receipt_hash_mismatch",
                "The projection rebuild receipt no longer matches its immutable hash.",
            )
        if receipt.request_sha256 != request_sha256:
            raise ContextualPermissionConflict(
                "idempotency_conflict",
                "The projection rebuild idempotency key was already used.",
            )
        for ref, expected_sha256 in (
            (receipt.planned_eta_ref, receipt.planned_eta_sha256),
            (
                receipt.contextual_permission_rules_ref,
                receipt.contextual_permission_rules_sha256,
            ),
            (receipt.workbench_seed_ref, receipt.workbench_seed_sha256),
        ):
            artifact_path = self._resolve_project_ref(ref)
            if not artifact_path.is_file() or _file_sha256(artifact_path) != expected_sha256:
                raise ContextualPermissionConflict(
                    "projection_rebuild_artifact_mismatch",
                    "A previously rebuilt projection artifact has changed.",
                )
        return receipt

    def _reviewed_baseline_plan_nodes(
        self,
        *,
        reviewed_sha256: str,
        days: list[BaselineDayDraft],
    ) -> list[RemainingPlanNode]:
        nodes: list[RemainingPlanNode] = []
        rules_ref = DEFAULT_CONTEXTUAL_PERMISSION_RULES_REF.as_posix()
        for day in days:
            proposal = day.primary_day_end_proposal
            if proposal is None:  # pragma: no cover - guarded by caller
                continue
            eta = day.eta_proposal
            baseline_minutes = (
                int(round(eta.segment_p75_sum_minutes))
                if eta is not None
                and eta.state == "complete_derived"
                and eta.segment_p75_sum_minutes is not None
                else 0
            )
            eta_gap = (
                "Segment p50/p75 sums are complete; the adjustment policy still requires separate review."
                if eta is not None and eta.state == "complete_derived"
                else "Whole-day duration remains unknown; supported subtotals are never promoted to a full-day ETA."
            )
            definitions = (
                (
                    f"node.route-axis.{day.mission_day_id}",
                    "route_axis",
                    f"{day.mission_day_id} route to {proposal.target.display_label}",
                    baseline_minutes,
                    False,
                    eta_gap,
                ),
                (
                    f"node.day-end.{day.mission_day_id}",
                    "day_end_target",
                    f"{day.mission_day_id} reviewed day end: {proposal.target.display_label}",
                    0,
                    True,
                    "The destination binding is reviewed; arrival and day close still require their own receipts.",
                ),
                (
                    f"node.reserve.{day.mission_day_id}",
                    "weather_daylight_retreat_reserve",
                    f"{day.mission_day_id} weather / daylight / retreat reserve",
                    0,
                    True,
                    "Reserve size and retreat authority remain pending separate Permission and Safety / Emergency review.",
                ),
            )
            for node_id, kind, label, duration, protected, quality in definitions:
                policy_ref = f"{rules_ref}#{node_id}"
                policy_sha256 = _fixed_hash(
                    f"{reviewed_sha256}:{node_id}:review-only.v1"
                )
                nodes.append(
                    RemainingPlanNode(
                        node_id=node_id,
                        action_id=kind,
                        label=label,
                        mission_day_id=day.mission_day_id,
                        kind=kind,
                        declared_adjustment_policy="review_only",
                        adjustment_policy="review_only",
                        cancellable=False,
                        priority=100 if kind != "weather_daylight_retreat_reserve" else 95,
                        policy_reason=(
                            "Baseline acceptance reviewed day endpoints only; forward "
                            "adjustment remains fail-closed until separately reviewed."
                        ),
                        policy_source=policy_ref,
                        source_refs=[policy_ref, proposal.target.artifact.ref],
                        baseline_duration_minutes=duration,
                        minimum_duration_minutes=duration,
                        discretionary_excess_minutes=0,
                        available_reducible_minutes=0,
                        applied_reduction_minutes=0,
                        effective_duration_minutes=duration,
                        absorbed_debt_minutes=0,
                        protected=protected,
                        adjustment_state="review_required",
                        source_rule_ref=policy_ref,
                        source_rule_sha256=policy_sha256,
                        data_quality=[quality],
                    )
                )
        return nodes

    def _rebound_planned_eta(
        self,
        *,
        path: Path,
        reviewed: dict[str, object],
        reviewed_ref: str,
        reviewed_sha256: str,
        days: list[BaselineDayDraft],
    ) -> dict[str, object]:
        try:
            existing = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        except (OSError, json.JSONDecodeError) as exc:
            raise ContextualPermissionConflict(
                "invalid_planned_eta", "The existing planned ETA artifact is invalid."
            ) from exc
        if not isinstance(existing, dict):
            raise ContextualPermissionConflict(
                "invalid_planned_eta", "The planned ETA artifact must be an object."
            )
        source_refs = list(existing.get("source_refs") or [])
        if reviewed_ref not in source_refs:
            source_refs.append(reviewed_ref)
        source_hashes = dict(existing.get("source_hashes") or {})
        source_hashes[reviewed_ref] = reviewed_sha256
        mission_day_estimates = []
        for day in days:
            eta = day.eta_proposal
            mission_day_estimates.append(
                {
                    "mission_day_id": day.mission_day_id,
                    "eta": eta.model_dump(mode="json") if eta is not None else None,
                    "segment_ids": day.segment_ids,
                    "primary_day_end_proposal_id": (
                        day.primary_day_end_proposal.proposal_id
                        if day.primary_day_end_proposal is not None
                        else None
                    ),
                }
            )
        return {
            **existing,
            "artifact_kind": "pretrip_planned_eta",
            "schema_version": "plannedEta.v1",
            "project_id": self.project_id,
            "plan_id": f"eta.permission.{reviewed_sha256[:16]}.v1",
            "status": "baseline_bound_rule_review_pending",
            "generated_at": self._now(),
            "reviewed_baseline_ref": reviewed_ref,
            "reviewed_baseline_sha256": reviewed_sha256,
            "review_scope": reviewed.get("review_scope"),
            "mission_day_estimates": mission_day_estimates,
            "source_refs": source_refs,
            "source_hashes": source_hashes,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "departure_approval_granted": False,
            "external_api_calls_made": False,
        }

    def _rebound_workbench_seed(
        self,
        *,
        project: dict[str, object],
        reviewed: dict[str, object],
        reviewed_ref: str,
        reviewed_sha256: str,
        review_receipt_ref: str,
        review_receipt_sha256: str,
        rules_sha256: str,
        planned_eta_ref: str,
        planned_eta_sha256: str,
        plan_nodes: list[RemainingPlanNode],
        days: list[BaselineDayDraft],
    ) -> ContextualPermissionWorkbenchSeed:
        first_day = days[0]
        first_proposal = first_day.primary_day_end_proposal
        if first_proposal is None:  # pragma: no cover - guarded by caller
            raise ContextualPermissionConflict(
                "reviewed_baseline_missing_day_end_bindings",
                "The first mission day has no reviewed destination binding.",
            )
        target = first_proposal.target
        next_day = days[1].mission_day_id if len(days) > 1 else None
        graph_ref = str(project.get("compiled_mission_graph_reviewed_ref") or "")
        graph_path = self._resolve_project_ref(graph_ref)
        if not graph_path.is_file():
            raise ContextualPermissionConflict(
                "reviewed_baseline_input_missing",
                "The reviewed mission graph is required for projection rebuild.",
            )
        graph_sha256 = _file_sha256(graph_path)
        membership_sha256 = _fixed_hash(
            f"{reviewed_sha256}:group.main:baseline-reviewed-membership"
        )
        day_instance_id = (
            f"{first_day.mission_day_id}.instance.{reviewed_sha256[:12]}"
        )
        old_group = self._seed.movement_groups[0]
        checklist_rows = []
        pending_handoff_ids = list(
            reviewed.get("pending_safety_handoff_item_ids") or []
        )
        for row in old_group.departure_checklist.rows:
            if row.row_id == "route_navigation":
                checklist_rows.append(
                    row.model_copy(
                        update={
                            "state": "pass",
                            "evidence_summary": (
                                "Reviewed route axis and exact current-day destination are bound."
                            ),
                            "evidence_ref": reviewed_ref,
                            "evidence_sha256": reviewed_sha256,
                            "freshness": "not_applicable",
                            "blocker": None,
                        }
                    )
                )
            elif row.row_id == "supplies_shelter" and pending_handoff_ids:
                checklist_rows.append(
                    row.model_copy(
                        update={
                            "state": "leader_check_required",
                            "evidence_summary": (
                                f"{len(pending_handoff_ids)} retreat/bivy handoff item(s) remain pending in Safety / Emergency."
                            ),
                            "blocker": "Safety / Emergency review remains required.",
                        }
                    )
                )
            else:
                checklist_rows.append(row)
        checklist = DepartureChecklistProjection(
            checklist_id=f"departure.checklist.{first_day.mission_day_id}.{reviewed_sha256[:12]}",
            checklist_sha256=_digest(
                [row.model_dump(mode="json") for row in checklist_rows]
            ),
            pending_day_plan_sha256=reviewed_sha256,
            rows=checklist_rows,
            open_conflict_count=sum(row.state != "pass" for row in checklist_rows),
            scout_suggestion_code="refresh_evidence",
            scout_suggestion=(
                "日終點已綁定；先審核 review-only 調整規則、天氣與行前六項檢核。"
            ),
            scout_suggestion_suspended=False,
            can_confirm_departure=False,
            mission_day_started=False,
        )
        day_end = DayEndProjection(
            planned_target_label=target.display_label,
            effective_target_label=target.display_label,
            planned_target_ref=target.artifact.ref,
            planned_target_sha256=target.artifact.sha256,
            effective_target_ref=target.artifact.ref,
            effective_target_sha256=target.artifact.sha256,
            feasibility="unknown",
            state="day_end_at_risk",
            completion="open",
            baseline_day_end_reached=False,
            close_receipt_ref=None,
        )
        group = MovementGroupProjection(
            group_id="group.main",
            group_label=f"{self.project_id} main movement group",
            formation_kind="baseline_reviewed",
            membership_revision=1,
            membership_sha256=membership_sha256,
            participant_refs_hash=membership_sha256,
            coordinator_ref="participant://leader-unassigned",
            shared_dependency_refs=[],
            shared_dependency_hashes=[],
            formation_receipt_ref=review_receipt_ref,
            formation_receipt_sha256=review_receipt_sha256,
            status="not_started",
            mission_day_id=first_day.mission_day_id,
            mission_day_instance_id=day_instance_id,
            day_end=day_end,
            shelter_hold=ShelterHoldProjection(
                hold_id=None,
                state="not_required",
                target_label=None,
                calendar_days_elapsed=0,
                mission_days_consumed=0,
                next_step="Proceed only after separate departure and rule review.",
            ),
            pending_next_day=next_day,
            departure_checklist=checklist,
            activity_summary=ActivitySummary(
                states={
                    "route_travel": 0,
                    "resting": 0,
                    "lying": 0,
                    "sleeping": 0,
                    "resumed_movement": 0,
                    "unknown": 1,
                },
                fresh_count=0,
                stale_count=0,
                contradiction_count=0,
            ),
            arrival_dwell=ArrivalDwellProjection(
                state="idle",
                elapsed_seconds=0,
                dwell_remaining_seconds=600,
                target_ref=target.artifact.ref,
                target_sha256=target.artifact.sha256,
                arrival_zone_ref=f"candidate://permission/{first_day.mission_day_id}/arrival-zone",
                arrival_zone_sha256=_fixed_hash(
                    f"{reviewed_sha256}:{first_day.mission_day_id}:arrival-zone"
                ),
                route_progress_ref="evidence://movement/not-started",
                route_progress_sha256=_fixed_hash(
                    f"{reviewed_sha256}:movement:not-started"
                ),
                dwell_policy_ref="reviewed://dwell-policy/default-600s",
                dwell_policy_sha256=_fixed_hash(
                    f"{self.project_id}:dwell-policy:600s"
                ),
                individual_activity_summary_ref="evidence://activity/not-started",
                individual_activity_summary_sha256=_fixed_hash(
                    f"{reviewed_sha256}:activity:not-started"
                ),
                target_match=False,
                gnss_confidence="unknown",
                manual_complete_available=False,
                blocked_by=["Mission day has not started."],
            ),
            communication=CommunicationProjection(
                policy_id=f"comm-window.{first_day.mission_day_id}.{reviewed_sha256[:12]}",
                policy_sha256=_fixed_hash(
                    f"{reviewed_sha256}:communication:review-pending"
                ),
                state="unknown",
                membership_revision=1,
                route_scope_ref=graph_ref,
                route_scope_sha256=graph_sha256,
                route_scope_label="Reviewed route axis; communication window review pending",
                viewpoint="local",
                next_check_in_target=target.display_label,
                baseline_window="pending separate review",
                effective_window="pending separate review",
                deadline_driver="Destination receipt only; wall-clock time cannot close the day.",
                next_check_in_target_ref=target.artifact.ref,
                next_check_in_target_sha256=target.artifact.sha256,
                last_verified_receipt_ref=None,
                local_group_contact_state="unknown",
                remote_observed_contact_state="unknown",
                scout_recommendation="monitor_reviewed_window",
                contact_overdue=False,
                emergency_declared=False,
            ),
            unexpected_separation=False,
        )
        evidence = [
            BoundedSourceRef(
                source_id="source.reviewed-baseline",
                source_kind="reviewed_mission_baseline",
                source_ref=reviewed_ref,
                source_sha256=reviewed_sha256,
                freshness="not_applicable",
                summary="Human-reviewed day endpoints; Permission scope only.",
            ),
            BoundedSourceRef(
                source_id="source.reviewed-graph",
                source_kind="reviewed_mission_graph",
                source_ref=graph_ref,
                source_sha256=graph_sha256,
                freshness="not_applicable",
                summary="Reviewed route node order without departure authority.",
            ),
            BoundedSourceRef(
                source_id="source.planned-eta",
                source_kind="planned_eta",
                source_ref=planned_eta_ref,
                source_sha256=planned_eta_sha256,
                freshness="not_applicable",
                summary="Baseline-bound segment sums; partial subtotals remain visibly incomplete.",
            ),
        ]
        timing_ref = project.get("reference_segment_timing_ref")
        if isinstance(timing_ref, str) and timing_ref:
            timing_path = self._resolve_project_ref(timing_ref)
            if timing_path.is_file():
                evidence.append(
                    BoundedSourceRef(
                        source_id="source.reference-segment-timing",
                        source_kind="reference_segment_timing",
                        source_ref=timing_ref,
                        source_sha256=_file_sha256(timing_path),
                        freshness="not_applicable",
                        summary="Historical segment timing used only for candidate planning.",
                    )
                )
        evidence.extend(
            source
            for source in self._seed.evidence
            if source.source_kind == "normalized_weather_fact"
        )
        return ContextualPermissionWorkbenchSeed(
            artifact_kind="contextual_permission_workbench_seed",
            schema_version="contextualPermissionWorkbenchSeed.v1",
            project_id=self.project_id,
            lens="baseline",
            replay_session_id=f"session.permission.{reviewed_sha256[:16]}.v1",
            baseline=BaselineIdentity(
                baseline_id=str(reviewed.get("baseline_id")),
                revision_id=str(reviewed.get("version_id")),
                baseline_sha256=reviewed_sha256,
                reviewed_receipt_ref=review_receipt_ref,
                source_mode=str(reviewed.get("source_mode")),
                baseline_candidate_id=str(reviewed.get("baseline_id")),
                baseline_version_id=str(reviewed.get("version_id")),
                accepted_receipt_id=str(reviewed.get("review_id")),
                immutable=True,
                accepted_by_human=True,
                candidate_only=True,
                runtime_safety_truth=False,
                departure_approval_granted=False,
                contextual_permission_rules_ref=(
                    DEFAULT_CONTEXTUAL_PERMISSION_RULES_REF.as_posix()
                ),
                contextual_permission_rules_sha256=rules_sha256,
                contextual_permission_rules_reviewed_by_human=False,
                source_hashes={
                    "reviewed_mission_baseline_ref": reviewed_sha256,
                    "planned_eta_ref": planned_eta_sha256,
                    "compiled_mission_graph_reviewed_ref": graph_sha256,
                },
            ),
            action_events=[],
            remaining_plan=plan_nodes,
            daily_review=DailyEmergencyReviewSession(
                session_id=f"daily-review.{first_day.mission_day_id}.{reviewed_sha256[:12]}",
                project_id=self.project_id,
                mission_day_id=first_day.mission_day_id,
                mission_day_instance_id=day_instance_id,
                movement_group_id=group.group_id,
                membership_revision=1,
                mission_day_plan_ref=reviewed_ref,
                mission_day_plan_sha256=reviewed_sha256,
                review_generation=1,
                state="not_started",
                planned_day_end_target_ref=target.artifact.ref,
                planned_day_end_target_sha256=target.artifact.sha256,
                planned_day_end_target_label=target.display_label,
                effective_day_end_target_ref=target.artifact.ref,
                effective_day_end_target_sha256=target.artifact.sha256,
                day_end_state="day_end_at_risk",
                alternatives=[],
            ),
            movement_groups=[group],
            evidence=evidence,
        )

    def _validate_packet_request(
        self,
        packet: NightAlternativePacket,
        request: EmergencyReviewDecisionRequest,
        *,
        context: CanonicalCommandContext,
    ) -> None:
        if request.packet_sha256 != packet.sha256:
            raise ContextualPermissionConflict(
                "packet_replaced", "The packet hash no longer matches current truth."
            )
        if request.mission_day_instance_id != packet.mission_day_instance_id:
            raise ContextualPermissionConflict(
                "wrong_mission_day", "The decision is not scoped to the current mission day."
            )
        if request.review_generation != packet.review_generation:
            raise ContextualPermissionConflict(
                "packet_invalidated", "The review generation has changed."
            )
        if request.reviewed_sequence != packet.reviewed_sequence:
            raise ContextualPermissionConflict(
                "packet_replaced", "The event sequence has changed."
            )
        if packet.aggregate is None:
            raise ContextualPermissionConflict(
                "packet_invalidated", "The packet lacks a canonical aggregate binding."
            )
        if context.group_id != packet.movement_group_id:
            raise ContextualPermissionConflict(
                "movement_group_revision_mismatch",
                "The packet belongs to another movement group.",
            )
        if context.membership_revision != packet.membership_revision:
            raise ContextualPermissionConflict(
                "movement_group_revision_mismatch",
                "The packet membership revision has changed.",
            )
        if context.expected_aggregate_sha256 != packet.aggregate.aggregate_sha256:
            raise ContextualPermissionConflict(
                "packet_replaced", "The packet aggregate no longer matches current truth."
            )
        if packet.eligibility != "eligible_for_human_review":
            raise ContextualPermissionConflict(
                "packet_ineligible", "The alternative is not eligible for human review."
            )
        if packet.freshness_state in {"expired", "freshness_unknown", "invalidated"}:
            raise ContextualPermissionConflict(
                "packet_expired", "The packet is not fresh enough to record a decision."
            )
        if packet.expires_at is None or self._now() >= packet.expires_at:
            raise ContextualPermissionConflict(
                "packet_expired", "The packet expired before confirmation."
            )

    def _current_packet(
        self, packet_id: str, mission_day_instance_id: str
    ) -> NightAlternativePacket:
        session = self.daily_emergency_review(mission_day_instance_id)
        for packet in session.alternatives:
            if packet.packet_id == packet_id:
                return packet
        raise ContextualPermissionConflict(
            "packet_replaced", "The selected packet is not current."
        )

    def _receipt_dir(self) -> Path:
        return self._resolve_store_path(
            self.project_id,
            "night_review_receipts",
        )

    def _receipt_path(self, idempotency_key: str) -> Path:
        if not _SAFE_ID_PATTERN.fullmatch(idempotency_key):
            raise ContextualPermissionConflict(
                "invalid_idempotency_key", "Invalid idempotency key."
            )
        return self._receipt_dir() / f"{idempotency_key}.json"

    def _load_receipts(
        self, group_id: str | None = None
    ) -> list[EmergencyReviewReceipt]:
        selected_group = group_id or self._seed.daily_review.movement_group_id
        receipts = [
            self._receipt_from_event(event)
            for event in self._load_group_events(selected_group)
            if event.event_kind == "night_review_decision_recorded"
        ]
        return sorted(receipts, key=lambda item: (item.event_sequence, item.receipt_id))

    def _receipt_from_event(self, event: CanonicalEvent) -> EmergencyReviewReceipt:
        payload = event.payload
        body: dict[str, object] = {
            "receipt_id": f"review-receipt.{event.idempotency_key}",
            "receipt_sha256": "0" * 64,
            "request_sha256": str(payload["request_sha256"]),
            "project_id": self.project_id,
            "session_id": event.session_id,
            "mission_day_id": str(payload["mission_day_id"]),
            "mission_day_instance_id": str(payload["mission_day_instance_id"]),
            "movement_group_id": event.group_id,
            "membership_revision": int(payload["membership_revision"]),
            "review_generation": int(payload["review_generation"]),
            "reviewed_sequence": int(payload["reviewed_sequence"]),
            "packet_id": str(payload["packet_id"]),
            "packet_sha256": str(payload["packet_sha256"]),
            "reviewed_envelope_sha256": str(payload["reviewed_envelope_sha256"]),
            "decision": str(payload["decision"]),
            "reviewer_alias": str(payload["reviewer_alias"]),
            "idempotency_key": event.idempotency_key,
            "event_sequence": event.sequence,
            "binding_sha256": event.binding_sha256,
            "aggregate_sha256_before": str(payload["aggregate_sha256_before"]),
            "recorded_at": event.recorded_at,
            "human_review_recorded": True,
            "candidate_projection_updated": True,
            "production_approval_granted": False,
            "real_world_effect_performed": False,
            "runtime_authorization_performed": False,
            "phase1_l0_l4_state_mutated": False,
            "safety_api_called": False,
            "outbound_action_performed": False,
            "outbound_transport_invoked": False,
            "external_send_performed": False,
        }
        body["receipt_sha256"] = _digest(
            {key: value for key, value in body.items() if key != "receipt_sha256"}
        )
        return EmergencyReviewReceipt.model_validate(body)

    def _write_new_json(self, path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=_canonical_json_default,
        ).encode("utf-8")
        descriptor, raw_temp_path = tempfile.mkstemp(
            prefix=f".{path.name}.tmp-", dir=path.parent
        )
        temp_path = Path(raw_temp_path)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                # A hard link makes the final name appear atomically and fails if
                # another process already appended the same immutable record.
                os.link(temp_path, path)
            except FileExistsError as exc:
                raise ContextualPermissionConflict(
                    "append_only_conflict", "Append-only record already exists."
                ) from exc
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def _write_replace_json(self, path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(f".tmp-{threading.get_ident()}")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=_canonical_json_default),
            encoding="utf-8",
        )
        try:
            temp_path.replace(path)
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def _relative_store_ref(self, path: Path) -> str:
        return path.relative_to(self.store_root).as_posix()

    def _now(self) -> datetime:
        now = self.now_factory()
        if now.tzinfo is None:
            return now.replace(tzinfo=timezone.utc)
        return now.astimezone(timezone.utc)


__all__ = [
    "ArrivalDwellObservationRequest",
    "AuthorityBoundary",
    "BaselineAuthoringRequest",
    "BaselineCandidateSaveRequest",
    "BaselinePatchPreviewRequest",
    "BaselinePatchPreviewResult",
    "BaselinePatchSaveRequest",
    "BaselineReviewAcceptRequest",
    "CandidateSimulationRequest",
    "CanonicalCommandContext",
    "CommunicationEventRequest",
    "ContactLossReviewRequest",
    "ContextualPermissionRulesArtifact",
    "ContextualPermissionConflict",
    "ContextualPermissionProjectionRebuildRequest",
    "ContextualPermissionProjectionRebuildReceipt",
    "ContextualPermissionWorkbench",
    "ContextualPermissionWorkbenchSeed",
    "DailyReviewInvalidationRequest",
    "DayEndCloseCorrectionRequest",
    "DayEndUnreachableRequest",
    "DepartureStartRequest",
    "EmergencyBivySelectionRequest",
    "EmergencyReviewDecisionRequest",
    "FieldConflictRequest",
    "FieldConflictResolutionRequest",
    "IndividualActionTransitionRequest",
    "ManualDayEndConfirmationRequest",
    "MovementGroupFormationRequest",
    "MovementGroupMergeRequest",
    "MovementGroupRevisionRequest",
    "OfflineDayEndIntent",
    "OfflineEmergencyReviewIntent",
    "OfflineFieldConflictIntent",
    "OfflineIntentSyncResult",
    "OfflineMovementGroupIntent",
    "ShelterHoldReviewRequest",
    "build_reference_workbench_seed",
]
