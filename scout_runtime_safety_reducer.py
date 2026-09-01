from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scout_energy_models import aggregate_sha256, sha256_file
from scout_runtime_safety_gate_models import (
    PRIMARY_SAFETY_GATE_IDS,
    SafetyGateId,
    SafetyGateConfidence,
    SafetyGateSeverity,
    SafetyLnLevelCandidate,
    SafetyLnTransitionCandidate,
    ScoutRuntimeSafetyGateEvent,
    ScoutRuntimeSafetyGateEventBatch,
    build_runtime_safety_gate_event_batch,
)
from scout_wearable_validator import FORBIDDEN_RAW_KEYS


ReducerRecommendation = Literal[
    "continue_monitoring",
    "watch_and_recheck",
    "slow_down_or_rest",
    "stop_and_rest",
    "retreat_review",
    "alert_review",
]
ReducerState = Literal[
    "normal",
    "watch",
    "rest",
    "retreat_review",
    "alert_review",
]
Phase1AdapterStatus = Literal[
    "blocked_feature_flag_disabled",
    "blocked_review_required",
    "transition_request_prepared",
]
ProductionGateResidencyStatus = Literal[
    "resident_ready",
    "shadow_only",
    "not_resident",
]
ProductionGateResidencyAuditStatus = Literal[
    "all_resident",
    "partial_residency",
    "not_resident",
]
ProductionLiveEvidenceContractStatus = Literal[
    "live_contract_ready",
    "contract_gap",
    "not_present",
]
ProductionLiveEvidenceContractAuditStatus = Literal[
    "all_live_contracts_ready",
    "partial_live_contracts",
    "no_live_contracts",
]

_TRANSITION_BY_SEVERITY: dict[str, SafetyLnTransitionCandidate] = {
    "none": "none",
    "watch": "candidate_watch",
    "rest": "candidate_rest",
    "retreat_review": "candidate_retreat",
    "alert_review": "candidate_alert_review",
}
_LEVEL_BY_TRANSITION: dict[str, SafetyLnLevelCandidate] = {
    "none": "L0_NORMAL",
    "candidate_watch": "L1_CAUTION",
    "candidate_rest": "L2_CONCERN",
    "candidate_retreat": "L3_RETREAT",
    "candidate_alert_review": "L4_ALERT_REVIEW",
}
_STATE_BY_TRANSITION: dict[str, ReducerState] = {
    "none": "normal",
    "candidate_watch": "watch",
    "candidate_rest": "rest",
    "candidate_retreat": "retreat_review",
    "candidate_alert_review": "alert_review",
}
_RECOMMENDATION_BY_TRANSITION: dict[str, ReducerRecommendation] = {
    "none": "continue_monitoring",
    "candidate_watch": "watch_and_recheck",
    "candidate_rest": "stop_and_rest",
    "candidate_retreat": "retreat_review",
    "candidate_alert_review": "alert_review",
}
_HARD_SINGLE_GATE_ESCALATORS = {"weather_gate", "environment_threat_gate", "darkness_gate"}
_PRODUCTION_SOURCE_PREFIXES = ("runtime://", "resident://", "prod://")
_LIVE_EVIDENCE_GATE_IDS: tuple[SafetyGateId, ...] = (
    "weather_gate",
    "environment_threat_gate",
)
_LIVE_SOURCE_PREFIXES = (
    "runtime://",
    "resident://",
    "prod://",
    "provider://",
    "cwa://",
    "weather://",
)
_LIVE_ATTESTATION_PREFIXES = (
    "attestation://",
    "provider://",
    "cwa://",
    "field://",
    "device://",
    "operator://",
)
_FIELD_VALIDATION_PREFIXES = (
    "field://",
    "operator://",
    "device://",
    "attestation://",
    "reviewed://field",
)


class RuntimeSafetyReducerBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_only: bool = True
    reducer_dry_run: bool = True
    runtime_safety_truth: bool = False
    phase1_runtime_safety_truth: bool = False
    phase1_runtime_mutation_allowed: bool = False
    phase1_l0_l4_state_mutated: bool = False
    safety_api_called: bool = False
    outbound_alert_sent: bool = False
    medical_diagnosis: bool = False
    raw_health_payload_shared: bool = False
    raw_track_shared: bool = False
    precise_timestamps_shared: bool = False
    home_work_trace_shared: bool = False

    @model_validator(mode="after")
    def enforce_dry_run_boundary(self) -> "RuntimeSafetyReducerBoundary":
        if not self.candidate_only or not self.reducer_dry_run:
            raise ValueError("runtime safety reducer artifact must be dry-run candidate evidence")
        if (
            self.runtime_safety_truth
            or self.phase1_runtime_safety_truth
            or self.phase1_runtime_mutation_allowed
            or self.phase1_l0_l4_state_mutated
        ):
            raise ValueError("runtime safety reducer dry-run cannot mutate Phase 1 state")
        if self.safety_api_called:
            raise ValueError("runtime safety reducer dry-run cannot call /safety/*")
        if self.outbound_alert_sent:
            raise ValueError("runtime safety reducer dry-run cannot send outbound alerts")
        if self.medical_diagnosis:
            raise ValueError("runtime safety reducer dry-run cannot be a medical diagnosis")
        if (
            self.raw_health_payload_shared
            or self.raw_track_shared
            or self.precise_timestamps_shared
            or self.home_work_trace_shared
        ):
            raise ValueError("runtime safety reducer dry-run cannot share raw private payloads")
        return self


class RuntimeSafetyReducerPrivacy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_only: bool = True
    aggregate_only: bool = True
    raw_health_payload_shared: bool = False
    raw_track_shared: bool = False
    precise_timestamps_shared: bool = False
    home_work_trace_shared: bool = False
    shareable_by_default: bool = False


class RuntimeSafetyReducerDataQuality(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confidence: SafetyGateConfidence = "low"
    gate_event_count: int = Field(default=0, ge=0)
    contributing_gate_count: int = Field(default=0, ge=0)
    missing_gate_ids: list[str] = Field(default_factory=list)
    stale_signal_names: list[str] = Field(default_factory=list)
    live_network_calls_made: bool = False
    limitations: list[str] = Field(default_factory=list)


class RuntimeSafetyReducerHysteresisInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    previous_ln_level: SafetyLnLevelCandidate = "L0_NORMAL"
    previous_reducer_state: ReducerState = "normal"
    clear_window_count: int = Field(default=0, ge=0)
    stable_window_count: int = Field(default=0, ge=0)


class RuntimeSafetyReducerHysteresisResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    applied: bool = True
    escalated_immediately: bool = False
    deescalation_held: bool = False
    required_clear_windows: int = 2
    previous_ln_level: SafetyLnLevelCandidate
    proposed_ln_level: SafetyLnLevelCandidate
    final_ln_level: SafetyLnLevelCandidate
    suppressed_reasons: list[str] = Field(default_factory=list)


class RuntimeSafetyReducerDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_runtime_safety_reducer_dry_run"
    artifact_version: str = "runtime_safety_reducer_dry_run.v1"
    source_provider: str = "scout_runtime_safety_reducer"
    source_path: str
    sha256: str
    gate_event_count: int = Field(ge=0)
    contributing_gate_ids: list[str] = Field(default_factory=list)
    corroborating_gate_ids: list[str] = Field(default_factory=list)
    suppressed_gate_ids: list[str] = Field(default_factory=list)
    selected_event_id: str | None = None
    selected_event_sha256: str | None = None
    selected_gate_id: str | None = None
    highest_severity: SafetyGateSeverity = "none"
    proposed_ln_transition_candidate: SafetyLnTransitionCandidate = "none"
    proposed_ln_level_candidate: SafetyLnLevelCandidate = "L0_NORMAL"
    ln_transition_candidate: SafetyLnTransitionCandidate = "none"
    ln_level_candidate: SafetyLnLevelCandidate = "L0_NORMAL"
    reducer_state: ReducerState = "normal"
    recommendation: ReducerRecommendation = "continue_monitoring"
    route_pressure_review_required: bool = False
    eta_delay_minutes: int = Field(default=0, ge=0)
    policy_trace: list[str] = Field(default_factory=list)
    suppressed_reasons: list[str] = Field(default_factory=list)
    gate_summaries: list[dict[str, Any]] = Field(default_factory=list)
    hysteresis: RuntimeSafetyReducerHysteresisResult
    data_quality: RuntimeSafetyReducerDataQuality = Field(default_factory=RuntimeSafetyReducerDataQuality)
    privacy: RuntimeSafetyReducerPrivacy = Field(default_factory=RuntimeSafetyReducerPrivacy)
    boundary: RuntimeSafetyReducerBoundary = Field(default_factory=RuntimeSafetyReducerBoundary)

    @model_validator(mode="after")
    def enforce_decision(self) -> "RuntimeSafetyReducerDecision":
        if self.gate_event_count < len(self.contributing_gate_ids):
            raise ValueError("contributing gates cannot exceed gate event count")
        if self.proposed_ln_level_candidate != _LEVEL_BY_TRANSITION[
            self.proposed_ln_transition_candidate
        ]:
            raise ValueError("proposed level must match proposed transition")
        if self.ln_level_candidate != _LEVEL_BY_TRANSITION[self.ln_transition_candidate]:
            raise ValueError("level must match transition")
        forbidden_paths = _forbidden_key_paths(self.gate_summaries)
        if forbidden_paths:
            raise ValueError(f"forbidden reducer fields present: {', '.join(forbidden_paths)}")
        if self.privacy.raw_health_payload_shared or self.privacy.precise_timestamps_shared:
            raise ValueError("reducer privacy flags are invalid")
        return self


class RuntimeSafetyPhase1AdapterBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    controlled_adapter: bool = True
    reducer_owned: bool = True
    individual_gate_owned: bool = False
    feature_flag_required: bool = True
    human_review_required: bool = True
    runtime_safety_truth: bool = False
    phase1_l0_l4_state_mutated: bool = False
    safety_api_called: bool = False
    outbound_alert_sent: bool = False
    medical_diagnosis: bool = False
    raw_health_payload_shared: bool = False
    raw_track_shared: bool = False
    precise_timestamps_shared: bool = False
    home_work_trace_shared: bool = False

    @model_validator(mode="after")
    def enforce_adapter_boundary(self) -> "RuntimeSafetyPhase1AdapterBoundary":
        if not self.controlled_adapter or not self.reducer_owned:
            raise ValueError("Phase 1 adapter must be controlled by the reducer")
        if self.individual_gate_owned:
            raise ValueError("individual gates cannot own the Phase 1 adapter")
        if self.runtime_safety_truth or self.phase1_l0_l4_state_mutated:
            raise ValueError("adapter artifact cannot claim Phase 1 mutation was performed")
        if self.safety_api_called:
            raise ValueError("adapter artifact cannot call /safety/* in this slice")
        if self.outbound_alert_sent:
            raise ValueError("adapter artifact cannot send outbound alerts")
        if self.medical_diagnosis:
            raise ValueError("adapter artifact cannot be a medical diagnosis")
        if (
            self.raw_health_payload_shared
            or self.raw_track_shared
            or self.precise_timestamps_shared
            or self.home_work_trace_shared
        ):
            raise ValueError("adapter artifact cannot share raw private payloads")
        return self


class RuntimeSafetyPhase1AdapterResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_runtime_safety_phase1_adapter_result"
    artifact_version: str = "runtime_safety_phase1_adapter_result.v1"
    source_provider: str = "scout_runtime_safety_reducer"
    source_path: str
    sha256: str
    status: Phase1AdapterStatus
    phase1_adapter_enabled: bool = False
    human_review_approved: bool = False
    transition_request_prepared: bool = False
    phase1_transition_candidate: dict[str, Any] | None = None
    selected_reducer_sha256: str
    selected_reducer_level_candidate: SafetyLnLevelCandidate
    selected_reducer_transition_candidate: SafetyLnTransitionCandidate
    boundary: RuntimeSafetyPhase1AdapterBoundary = Field(
        default_factory=RuntimeSafetyPhase1AdapterBoundary
    )

    @model_validator(mode="after")
    def enforce_adapter_result(self) -> "RuntimeSafetyPhase1AdapterResult":
        if self.transition_request_prepared != (
            self.status == "transition_request_prepared"
        ):
            raise ValueError("transition_request_prepared must match status")
        if self.status == "transition_request_prepared" and not self.phase1_transition_candidate:
            raise ValueError("prepared adapter result requires a transition candidate")
        forbidden_paths = _forbidden_key_paths(self.phase1_transition_candidate or {})
        if forbidden_paths:
            raise ValueError(f"forbidden adapter fields present: {', '.join(forbidden_paths)}")
        return self


class ProductionGateResidencyRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gate_id: SafetyGateId
    status: ProductionGateResidencyStatus
    event_present: bool
    event_id: str | None = None
    event_sha256: str | None = None
    source_provider: str | None = None
    source_path: str | None = None
    source_gate_sha256: str | None = None
    resident_evidence_present: bool
    freshness_evidence_present: bool
    route_context_joined: bool
    field_validation_present: bool
    boundary_clean: bool
    blockers: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    candidate_only: bool = True
    runtime_safety_truth: bool = False
    phase1_l0_l4_state_mutated: bool = False
    safety_api_called: bool = False
    outbound_alert_sent: bool = False
    hardware_control_performed: bool = False

    @model_validator(mode="after")
    def enforce_residency_row_boundary(self) -> "ProductionGateResidencyRow":
        ready = (
            self.event_present
            and self.resident_evidence_present
            and self.freshness_evidence_present
            and self.route_context_joined
            and self.field_validation_present
            and self.boundary_clean
            and not self.blockers
        )
        if ready and self.status != "resident_ready":
            raise ValueError("ready residency row must use resident_ready")
        if self.status == "resident_ready" and not ready:
            raise ValueError("resident_ready row requires every residency check")
        if (
            self.runtime_safety_truth
            or self.phase1_l0_l4_state_mutated
            or self.safety_api_called
            or self.outbound_alert_sent
            or self.hardware_control_performed
        ):
            raise ValueError("production gate residency audit cannot perform runtime effects")
        return self


class ProductionGateResidencyAudit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_gate_residency_audit"
    artifact_version: str = "production_gate_residency_audit.v0"
    source_provider: str = "scout_runtime_safety_reducer"
    source_path: str
    sha256: str
    status: ProductionGateResidencyAuditStatus
    gate_count: int = Field(ge=0)
    resident_ready_count: int = Field(ge=0)
    shadow_only_count: int = Field(ge=0)
    not_resident_count: int = Field(ge=0)
    required_gate_ids: list[SafetyGateId]
    missing_gate_ids: list[SafetyGateId]
    rows: list[ProductionGateResidencyRow]
    reducer_candidate_allowed: bool
    production_runtime_enabled: bool = False
    candidate_only: bool = True
    runtime_safety_truth: bool = False
    phase1_l0_l4_state_mutated: bool = False
    safety_api_called: bool = False
    outbound_alert_sent: bool = False
    hardware_control_performed: bool = False
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_audit_boundary(self) -> "ProductionGateResidencyAudit":
        if self.gate_count != len(self.rows):
            raise ValueError("gate_count must match residency rows")
        if self.required_gate_ids != list(PRIMARY_SAFETY_GATE_IDS):
            raise ValueError("residency audit must cover the primary safety gate set")
        if self.resident_ready_count != sum(
            row.status == "resident_ready" for row in self.rows
        ):
            raise ValueError("resident_ready_count does not match rows")
        if self.shadow_only_count != sum(row.status == "shadow_only" for row in self.rows):
            raise ValueError("shadow_only_count does not match rows")
        if self.not_resident_count != sum(row.status == "not_resident" for row in self.rows):
            raise ValueError("not_resident_count does not match rows")
        if self.reducer_candidate_allowed != (self.status == "all_resident"):
            raise ValueError("reducer_candidate_allowed must reflect all_resident status")
        if self.status == "all_resident" and self.missing_gate_ids:
            raise ValueError("all_resident audit cannot report missing gate ids")
        if (
            self.production_runtime_enabled
            or self.runtime_safety_truth
            or self.phase1_l0_l4_state_mutated
            or self.safety_api_called
            or self.outbound_alert_sent
            or self.hardware_control_performed
        ):
            raise ValueError("production gate residency audit cannot perform runtime effects")
        return self


class ProductionLiveEvidenceContractRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gate_id: SafetyGateId
    status: ProductionLiveEvidenceContractStatus
    event_present: bool
    event_id: str | None = None
    event_sha256: str | None = None
    source_provider: str | None = None
    source_path: str | None = None
    source_gate_sha256: str | None = None
    live_source_present: bool
    freshness_contract_present: bool
    current_observation_present: bool
    route_scope_present: bool
    provider_or_field_attestation_present: bool
    boundary_clean: bool
    blockers: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    candidate_only: bool = True
    runtime_safety_truth: bool = False
    phase1_l0_l4_state_mutated: bool = False
    safety_api_called: bool = False
    outbound_alert_sent: bool = False
    hardware_control_performed: bool = False

    @model_validator(mode="after")
    def enforce_live_evidence_row(self) -> "ProductionLiveEvidenceContractRow":
        if self.gate_id not in _LIVE_EVIDENCE_GATE_IDS:
            raise ValueError("live evidence contract audit only covers weather/threat gates")
        ready = (
            self.event_present
            and bool(self.source_gate_sha256)
            and self.live_source_present
            and self.freshness_contract_present
            and self.current_observation_present
            and self.route_scope_present
            and self.provider_or_field_attestation_present
            and self.boundary_clean
            and not self.blockers
        )
        if ready and self.status != "live_contract_ready":
            raise ValueError("ready live evidence row must use live_contract_ready")
        if self.status == "live_contract_ready" and not ready:
            raise ValueError("live_contract_ready requires every live evidence check")
        if (
            self.runtime_safety_truth
            or self.phase1_l0_l4_state_mutated
            or self.safety_api_called
            or self.outbound_alert_sent
            or self.hardware_control_performed
        ):
            raise ValueError("live evidence contract audit cannot perform runtime effects")
        return self


class ProductionLiveEvidenceContractAudit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_live_evidence_contract_audit"
    artifact_version: str = "production_live_evidence_contract_audit.v0"
    source_provider: str = "scout_runtime_safety_reducer"
    source_path: str
    sha256: str
    status: ProductionLiveEvidenceContractAuditStatus
    required_gate_ids: list[SafetyGateId]
    live_contract_ready_count: int = Field(ge=0)
    contract_gap_count: int = Field(ge=0)
    not_present_count: int = Field(ge=0)
    rows: list[ProductionLiveEvidenceContractRow]
    production_weather_environment_ready: bool
    candidate_only: bool = True
    runtime_safety_truth: bool = False
    phase1_l0_l4_state_mutated: bool = False
    safety_api_called: bool = False
    outbound_alert_sent: bool = False
    hardware_control_performed: bool = False
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_live_evidence_audit(self) -> "ProductionLiveEvidenceContractAudit":
        if self.required_gate_ids != list(_LIVE_EVIDENCE_GATE_IDS):
            raise ValueError("live evidence audit must cover weather and threat gates")
        if len(self.rows) != len(_LIVE_EVIDENCE_GATE_IDS):
            raise ValueError("live evidence audit must include one row per required gate")
        if self.live_contract_ready_count != sum(
            row.status == "live_contract_ready" for row in self.rows
        ):
            raise ValueError("live_contract_ready_count does not match rows")
        if self.contract_gap_count != sum(row.status == "contract_gap" for row in self.rows):
            raise ValueError("contract_gap_count does not match rows")
        if self.not_present_count != sum(row.status == "not_present" for row in self.rows):
            raise ValueError("not_present_count does not match rows")
        if self.production_weather_environment_ready != (
            self.status == "all_live_contracts_ready"
        ):
            raise ValueError("production readiness flag must reflect audit status")
        if (
            self.runtime_safety_truth
            or self.phase1_l0_l4_state_mutated
            or self.safety_api_called
            or self.outbound_alert_sent
            or self.hardware_control_performed
        ):
            raise ValueError("live evidence contract audit cannot perform runtime effects")
        return self


def reduce_runtime_safety_gate_events(
    gate_events: (
        ScoutRuntimeSafetyGateEventBatch
        | list[ScoutRuntimeSafetyGateEvent | dict[str, Any]]
        | dict[str, Any]
    ),
    *,
    source_path: str = "inline:runtime-safety-gate-reducer",
    hysteresis_input: RuntimeSafetyReducerHysteresisInput | dict[str, Any] | None = None,
) -> RuntimeSafetyReducerDecision:
    batch = _event_batch(gate_events)
    events = batch.events
    contributing = [event for event in events if event.severity != "none"]
    selected = _selected_event(contributing)
    proposed_transition = selected.ln_transition_candidate if selected else "none"
    highest_severity = selected.severity if selected else "none"
    policy_trace: list[str] = []
    suppressed_reasons: list[str] = []
    suppressed_gate_ids: list[str] = []
    corroborating_gate_ids = _corroborating_gate_ids(contributing)

    proposed_transition = _apply_cross_gate_policy(
        contributing,
        proposed_transition,
        policy_trace=policy_trace,
        suppressed_reasons=suppressed_reasons,
        suppressed_gate_ids=suppressed_gate_ids,
        corroborating_gate_ids=corroborating_gate_ids,
    )
    proposed_level = _LEVEL_BY_TRANSITION[proposed_transition]
    hysteresis_model = (
        hysteresis_input
        if isinstance(hysteresis_input, RuntimeSafetyReducerHysteresisInput)
        else RuntimeSafetyReducerHysteresisInput.model_validate(hysteresis_input or {})
    )
    final_transition, hysteresis_result = _apply_hysteresis(
        proposed_transition,
        hysteresis_model,
    )
    final_level = _LEVEL_BY_TRANSITION[final_transition]
    suppressed_reasons.extend(hysteresis_result.suppressed_reasons)
    reducer_state = _STATE_BY_TRANSITION[final_transition]
    recommendation = _RECOMMENDATION_BY_TRANSITION[final_transition]
    route_pressure_review_required = any(
        event.route_pressure_review_required for event in contributing
    )
    eta_delay_minutes = max([event.eta_delay_minutes for event in events], default=0)
    gate_summaries = [_event_summary(event) for event in events]
    digest_payload = {
        "source_path": source_path,
        "batch_sha256": batch.sha256,
        "event_ids": [event.event_id for event in events],
        "proposed_transition": proposed_transition,
        "final_transition": final_transition,
        "hysteresis": hysteresis_result.model_dump(mode="json"),
    }
    digest = aggregate_sha256([digest_payload])

    return RuntimeSafetyReducerDecision(
        source_path=source_path,
        sha256=digest,
        gate_event_count=len(events),
        contributing_gate_ids=[event.gate_id for event in contributing],
        corroborating_gate_ids=_unique_string_list(corroborating_gate_ids),
        suppressed_gate_ids=_unique_string_list(suppressed_gate_ids),
        selected_event_id=selected.event_id if selected else None,
        selected_event_sha256=selected.sha256 if selected else None,
        selected_gate_id=selected.gate_id if selected else None,
        highest_severity=highest_severity,
        proposed_ln_transition_candidate=proposed_transition,
        proposed_ln_level_candidate=proposed_level,
        ln_transition_candidate=final_transition,
        ln_level_candidate=final_level,
        reducer_state=reducer_state,
        recommendation=recommendation,
        route_pressure_review_required=route_pressure_review_required,
        eta_delay_minutes=eta_delay_minutes,
        policy_trace=policy_trace,
        suppressed_reasons=_unique_string_list(suppressed_reasons),
        gate_summaries=gate_summaries,
        hysteresis=hysteresis_result,
        data_quality=RuntimeSafetyReducerDataQuality(
            confidence=_max_confidence([event.confidence for event in events]),
            gate_event_count=len(events),
            contributing_gate_count=len(contributing),
            missing_gate_ids=[
                gate_id
                for gate_id in (
                    "pace_gate",
                    "delay_gate",
                    "physiologic_gate",
                    "weather_gate",
                    "darkness_gate",
                    "environment_threat_gate",
                )
                if gate_id not in {event.gate_id for event in events}
            ],
            stale_signal_names=_unique_string_list(
                [
                    stale
                    for event in events
                    for stale in event.data_quality.stale_signal_names
                ]
            ),
            live_network_calls_made=any(
                event.data_quality.live_network_calls_made for event in events
            ),
            limitations=[
                "dry-run reducer candidate only",
                "Phase 1 adapter must be explicitly enabled and reviewed",
            ],
        ),
        privacy=RuntimeSafetyReducerPrivacy(),
        boundary=RuntimeSafetyReducerBoundary(),
    )


def build_phase1_adapter_result(
    decision: RuntimeSafetyReducerDecision | dict[str, Any],
    *,
    source_path: str = "inline:runtime-safety-phase1-adapter",
    phase1_adapter_enabled: bool = False,
    human_review_approved: bool = False,
) -> RuntimeSafetyPhase1AdapterResult:
    reducer_decision = (
        decision
        if isinstance(decision, RuntimeSafetyReducerDecision)
        else RuntimeSafetyReducerDecision.model_validate(decision)
    )
    status: Phase1AdapterStatus
    transition_request: dict[str, Any] | None = None
    if not phase1_adapter_enabled:
        status = "blocked_feature_flag_disabled"
    elif not human_review_approved:
        status = "blocked_review_required"
    else:
        status = "transition_request_prepared"
        transition_request = {
            "adapter_kind": "phase1_l0_l4_transition_candidate",
            "requested_ln_level": reducer_decision.ln_level_candidate,
            "requested_ln_transition": reducer_decision.ln_transition_candidate,
            "reducer_recommendation": reducer_decision.recommendation,
            "selected_gate_id": reducer_decision.selected_gate_id,
            "selected_event_sha256": reducer_decision.selected_event_sha256,
            "corroborating_gate_ids": reducer_decision.corroborating_gate_ids,
            "phase1_l0_l4_state_mutated": False,
            "safety_api_called": False,
        }
    digest = aggregate_sha256(
        [
            {
                "source_path": source_path,
                "decision_sha256": reducer_decision.sha256,
                "status": status,
                "phase1_adapter_enabled": phase1_adapter_enabled,
                "human_review_approved": human_review_approved,
                "transition_request": transition_request,
            }
        ]
    )
    return RuntimeSafetyPhase1AdapterResult(
        source_path=source_path,
        sha256=digest,
        status=status,
        phase1_adapter_enabled=phase1_adapter_enabled,
        human_review_approved=human_review_approved,
        transition_request_prepared=status == "transition_request_prepared",
        phase1_transition_candidate=transition_request,
        selected_reducer_sha256=reducer_decision.sha256,
        selected_reducer_level_candidate=reducer_decision.ln_level_candidate,
        selected_reducer_transition_candidate=reducer_decision.ln_transition_candidate,
        boundary=RuntimeSafetyPhase1AdapterBoundary(),
    )


def build_production_gate_residency_audit(
    gate_events: (
        ScoutRuntimeSafetyGateEventBatch
        | list[ScoutRuntimeSafetyGateEvent | dict[str, Any]]
        | dict[str, Any]
    ),
    *,
    source_path: str = "inline:production-gate-residency-audit",
) -> ProductionGateResidencyAudit:
    batch = _event_batch(gate_events)
    latest_by_gate: dict[str, ScoutRuntimeSafetyGateEvent] = {}
    for event in batch.events:
        current = latest_by_gate.get(event.gate_id)
        if current is None or event.observed_at_offset_s >= current.observed_at_offset_s:
            latest_by_gate[event.gate_id] = event
    rows = [
        _production_gate_residency_row(
            cast(SafetyGateId, gate_id),
            latest_by_gate.get(gate_id),
        )
        for gate_id in PRIMARY_SAFETY_GATE_IDS
    ]
    ready_count = sum(row.status == "resident_ready" for row in rows)
    shadow_count = sum(row.status == "shadow_only" for row in rows)
    not_resident_count = sum(row.status == "not_resident" for row in rows)
    if ready_count == len(PRIMARY_SAFETY_GATE_IDS):
        status: ProductionGateResidencyAuditStatus = "all_resident"
    elif shadow_count or ready_count:
        status = "partial_residency"
    else:
        status = "not_resident"
    missing_gate_ids = [
        row.gate_id for row in rows if row.status != "resident_ready"
    ]
    payload = {
        "source_path": source_path,
        "batch_sha256": batch.sha256,
        "status": status,
        "rows": [row.model_dump(mode="json") for row in rows],
    }
    digest = aggregate_sha256([payload])
    return ProductionGateResidencyAudit(
        source_path=source_path,
        sha256=digest,
        status=status,
        gate_count=len(rows),
        resident_ready_count=ready_count,
        shadow_only_count=shadow_count,
        not_resident_count=not_resident_count,
        required_gate_ids=[
            cast(SafetyGateId, gate_id) for gate_id in PRIMARY_SAFETY_GATE_IDS
        ],
        missing_gate_ids=missing_gate_ids,
        rows=rows,
        reducer_candidate_allowed=status == "all_resident",
        limitations=[
            "local residency audit only",
            "does not enable production runtime, Phase 1 mutation, safety API calls, outbound alerts, or hardware control",
        ],
    )


def build_production_live_evidence_contract_audit(
    gate_events: (
        ScoutRuntimeSafetyGateEventBatch
        | list[ScoutRuntimeSafetyGateEvent | dict[str, Any]]
        | dict[str, Any]
    ),
    *,
    source_path: str = "inline:production-live-evidence-contract-audit",
) -> ProductionLiveEvidenceContractAudit:
    batch = _event_batch(gate_events)
    latest_by_gate: dict[str, ScoutRuntimeSafetyGateEvent] = {}
    for event in batch.events:
        if event.gate_id not in _LIVE_EVIDENCE_GATE_IDS:
            continue
        current = latest_by_gate.get(event.gate_id)
        if current is None or event.observed_at_offset_s >= current.observed_at_offset_s:
            latest_by_gate[event.gate_id] = event
    rows = [
        _production_live_evidence_contract_row(
            gate_id,
            latest_by_gate.get(gate_id),
        )
        for gate_id in _LIVE_EVIDENCE_GATE_IDS
    ]
    ready_count = sum(row.status == "live_contract_ready" for row in rows)
    gap_count = sum(row.status == "contract_gap" for row in rows)
    not_present_count = sum(row.status == "not_present" for row in rows)
    if ready_count == len(_LIVE_EVIDENCE_GATE_IDS):
        status: ProductionLiveEvidenceContractAuditStatus = (
            "all_live_contracts_ready"
        )
    elif ready_count or gap_count:
        status = "partial_live_contracts"
    else:
        status = "no_live_contracts"
    payload = {
        "source_path": source_path,
        "batch_sha256": batch.sha256,
        "status": status,
        "rows": [row.model_dump(mode="json") for row in rows],
    }
    digest = aggregate_sha256([payload])
    return ProductionLiveEvidenceContractAudit(
        source_path=source_path,
        sha256=digest,
        status=status,
        required_gate_ids=list(_LIVE_EVIDENCE_GATE_IDS),
        live_contract_ready_count=ready_count,
        contract_gap_count=gap_count,
        not_present_count=not_present_count,
        rows=rows,
        production_weather_environment_ready=status == "all_live_contracts_ready",
        limitations=[
            "local live-evidence contract audit only",
            "does not call weather providers, safety APIs, outbound transports, or hardware",
        ],
    )


def write_production_gate_residency_audit(
    audit: ProductionGateResidencyAudit,
    output_path: Path | str,
) -> ProductionGateResidencyAudit:
    path = Path(output_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(audit.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return ProductionGateResidencyAudit.model_validate_json(path.read_text(encoding="utf-8"))


def load_production_gate_residency_audit(path: Path | str) -> ProductionGateResidencyAudit:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    payload["source_path"] = payload.get("source_path") or str(path)
    payload["sha256"] = payload.get("sha256") or sha256_file(Path(path).expanduser())
    return ProductionGateResidencyAudit.model_validate(payload)


def write_production_live_evidence_contract_audit(
    audit: ProductionLiveEvidenceContractAudit,
    output_path: Path | str,
) -> ProductionLiveEvidenceContractAudit:
    path = Path(output_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(audit.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return ProductionLiveEvidenceContractAudit.model_validate_json(
        path.read_text(encoding="utf-8")
    )


def load_production_live_evidence_contract_audit(
    path: Path | str,
) -> ProductionLiveEvidenceContractAudit:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    payload["source_path"] = payload.get("source_path") or str(path)
    payload["sha256"] = payload.get("sha256") or sha256_file(Path(path).expanduser())
    return ProductionLiveEvidenceContractAudit.model_validate(payload)


def write_runtime_safety_reducer_decision(
    decision: RuntimeSafetyReducerDecision,
    output_path: Path | str,
) -> RuntimeSafetyReducerDecision:
    path = Path(output_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(decision.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return RuntimeSafetyReducerDecision.model_validate_json(path.read_text(encoding="utf-8"))


def load_runtime_safety_reducer_decision(path: Path | str) -> RuntimeSafetyReducerDecision:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    payload["source_path"] = payload.get("source_path") or str(path)
    payload["sha256"] = payload.get("sha256") or sha256_file(Path(path).expanduser())
    return RuntimeSafetyReducerDecision.model_validate(payload)


def write_phase1_adapter_result(
    result: RuntimeSafetyPhase1AdapterResult,
    output_path: Path | str,
) -> RuntimeSafetyPhase1AdapterResult:
    path = Path(output_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return RuntimeSafetyPhase1AdapterResult.model_validate_json(path.read_text(encoding="utf-8"))


def load_phase1_adapter_result(path: Path | str) -> RuntimeSafetyPhase1AdapterResult:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    payload["source_path"] = payload.get("source_path") or str(path)
    payload["sha256"] = payload.get("sha256") or sha256_file(Path(path).expanduser())
    return RuntimeSafetyPhase1AdapterResult.model_validate(payload)


def _production_gate_residency_row(
    gate_id: SafetyGateId,
    event: ScoutRuntimeSafetyGateEvent | None,
) -> ProductionGateResidencyRow:
    if event is None:
        return ProductionGateResidencyRow(
            gate_id=gate_id,
            status="not_resident",
            event_present=False,
            resident_evidence_present=False,
            freshness_evidence_present=False,
            route_context_joined=False,
            field_validation_present=False,
            boundary_clean=True,
            blockers=[
                "gate_event_missing",
                "production_resident_evidence_missing",
                "freshness_evidence_missing",
                "route_context_join_missing",
                "field_validation_missing",
            ],
        )

    refs = _unique_string_list([event.source_path, *event.evidence_refs])
    lower_provider = event.source_provider.casefold()
    inline_or_fixture = (
        event.source_path.startswith("inline:")
        or "fixture" in lower_provider
        or "test" in lower_provider
    )
    production_ref_present = any(
        ref.startswith(_PRODUCTION_SOURCE_PREFIXES) for ref in refs
    )
    resident_evidence_present = (
        bool(event.source_gate_sha256)
        and bool(event.evidence_refs)
        and production_ref_present
        and not inline_or_fixture
    )
    freshness_evidence_present = (
        event.confidence in {"medium", "high"}
        and not event.data_quality.missing_signal_names
        and not event.data_quality.stale_signal_names
    )
    route_context = event.route_context
    route_context_joined = bool(route_context.route_id) and bool(
        route_context.segment_id
        or route_context.checkpoint_id
        or route_context.map_target_ids
    )
    field_validation_present = any(
        ref.startswith(_FIELD_VALIDATION_PREFIXES) for ref in event.evidence_refs
    )
    boundary = event.boundary
    boundary_clean = (
        boundary.candidate_only
        and boundary.reducer_required
        and not boundary.runtime_safety_truth
        and not boundary.phase1_runtime_safety_truth
        and not boundary.phase1_runtime_mutation_allowed
        and not boundary.phase1_l0_l4_state_mutated
        and not boundary.direct_phase1_mutation_performed
        and not boundary.direct_safety_api_call_allowed
        and not boundary.direct_safety_api_call_performed
        and not boundary.safety_api_called
        and not boundary.outbound_alert_sent
        and not boundary.medical_diagnosis
    )
    blockers: list[str] = []
    if inline_or_fixture:
        blockers.append("fixture_or_inline_source")
    if not resident_evidence_present:
        blockers.append("production_resident_evidence_missing")
    if not freshness_evidence_present:
        blockers.append("freshness_evidence_missing")
    if not route_context_joined:
        blockers.append("route_context_join_missing")
    if not field_validation_present:
        blockers.append("field_validation_missing")
    if not boundary_clean:
        blockers.append("boundary_not_clean")
    status: ProductionGateResidencyStatus = (
        "resident_ready" if not blockers else "shadow_only"
    )
    return ProductionGateResidencyRow(
        gate_id=gate_id,
        status=status,
        event_present=True,
        event_id=event.event_id,
        event_sha256=event.sha256,
        source_provider=event.source_provider,
        source_path=event.source_path,
        source_gate_sha256=event.source_gate_sha256,
        resident_evidence_present=resident_evidence_present,
        freshness_evidence_present=freshness_evidence_present,
        route_context_joined=route_context_joined,
        field_validation_present=field_validation_present,
        boundary_clean=boundary_clean,
        blockers=blockers,
        evidence_refs=event.evidence_refs,
    )


def _production_live_evidence_contract_row(
    gate_id: SafetyGateId,
    event: ScoutRuntimeSafetyGateEvent | None,
) -> ProductionLiveEvidenceContractRow:
    if event is None:
        return ProductionLiveEvidenceContractRow(
            gate_id=gate_id,
            status="not_present",
            event_present=False,
            live_source_present=False,
            freshness_contract_present=False,
            current_observation_present=False,
            route_scope_present=False,
            provider_or_field_attestation_present=False,
            boundary_clean=True,
            blockers=[
                "gate_event_missing",
                "production_live_source_missing",
                "freshness_contract_missing",
                "current_observation_missing",
                "route_scope_missing",
                "provider_or_field_attestation_missing",
            ],
        )

    refs = _unique_string_list([event.source_path, *event.evidence_refs])
    lower_provider = event.source_provider.casefold()
    inline_or_fixture = (
        event.source_path.startswith("inline:")
        or "fixture" in lower_provider
        or "test" in lower_provider
    )
    live_source_present = any(ref.startswith(_LIVE_SOURCE_PREFIXES) for ref in refs)
    freshness_contract_present = _live_freshness_contract_present(event)
    current_observation_present = _live_current_observation_present(event)
    route_context = event.route_context
    route_scope_present = bool(route_context.route_id) and bool(
        route_context.segment_id
        or route_context.checkpoint_id
        or route_context.map_target_ids
    )
    provider_or_field_attestation_present = any(
        ref.startswith(_LIVE_ATTESTATION_PREFIXES) for ref in refs
    )
    boundary_clean = _event_boundary_clean(event)
    blockers: list[str] = []
    if inline_or_fixture:
        blockers.append("fixture_or_inline_source")
    if not event.source_gate_sha256:
        blockers.append("source_gate_hash_missing")
    if not live_source_present:
        blockers.append("production_live_source_missing")
    if not freshness_contract_present:
        blockers.append("freshness_contract_missing")
    if not current_observation_present:
        blockers.append("current_observation_missing")
    if not route_scope_present:
        blockers.append("route_scope_missing")
    if not provider_or_field_attestation_present:
        blockers.append("provider_or_field_attestation_missing")
    if not boundary_clean:
        blockers.append("boundary_not_clean")
    status: ProductionLiveEvidenceContractStatus = (
        "live_contract_ready" if not blockers else "contract_gap"
    )
    return ProductionLiveEvidenceContractRow(
        gate_id=gate_id,
        status=status,
        event_present=True,
        event_id=event.event_id,
        event_sha256=event.sha256,
        source_provider=event.source_provider,
        source_path=event.source_path,
        source_gate_sha256=event.source_gate_sha256,
        live_source_present=live_source_present,
        freshness_contract_present=freshness_contract_present,
        current_observation_present=current_observation_present,
        route_scope_present=route_scope_present,
        provider_or_field_attestation_present=provider_or_field_attestation_present,
        boundary_clean=boundary_clean,
        blockers=blockers,
        evidence_refs=event.evidence_refs,
    )


def _live_freshness_contract_present(event: ScoutRuntimeSafetyGateEvent) -> bool:
    if event.data_quality.missing_signal_names or event.data_quality.stale_signal_names:
        return False
    if event.gate_id == "weather_gate":
        age = event.gate_payload.get("source_age_minutes")
        return isinstance(age, (int, float)) and age <= 180
    return any(
        ref.startswith(("attestation://freshness", "field://", "device://"))
        for ref in event.evidence_refs
    )


def _live_current_observation_present(event: ScoutRuntimeSafetyGateEvent) -> bool:
    payload = event.gate_payload
    if event.gate_id == "weather_gate":
        return bool(
            payload.get("warning_level") is not None
            and payload.get("source_age_minutes") is not None
            and event.data_quality.signal_count >= 2
        )
    return bool(
        payload.get("threat_type")
        and payload.get("passability")
        and payload.get("immediacy")
    )


def _event_boundary_clean(event: ScoutRuntimeSafetyGateEvent) -> bool:
    boundary = event.boundary
    return (
        boundary.candidate_only
        and boundary.reducer_required
        and not boundary.runtime_safety_truth
        and not boundary.phase1_runtime_safety_truth
        and not boundary.phase1_runtime_mutation_allowed
        and not boundary.phase1_l0_l4_state_mutated
        and not boundary.direct_phase1_mutation_performed
        and not boundary.direct_safety_api_call_allowed
        and not boundary.direct_safety_api_call_performed
        and not boundary.safety_api_called
        and not boundary.outbound_alert_sent
        and not boundary.medical_diagnosis
    )


def _event_batch(
    value: (
        ScoutRuntimeSafetyGateEventBatch
        | list[ScoutRuntimeSafetyGateEvent | dict[str, Any]]
        | dict[str, Any]
    ),
) -> ScoutRuntimeSafetyGateEventBatch:
    if isinstance(value, ScoutRuntimeSafetyGateEventBatch):
        return value
    if isinstance(value, list):
        return build_runtime_safety_gate_event_batch(value)
    return ScoutRuntimeSafetyGateEventBatch.model_validate(value)


def _selected_event(
    events: list[ScoutRuntimeSafetyGateEvent],
) -> ScoutRuntimeSafetyGateEvent | None:
    if not events:
        return None
    return max(
        events,
        key=lambda event: (
            _transition_rank(event.ln_transition_candidate),
            _confidence_rank(event.confidence),
            event.eta_delay_minutes,
            -events.index(event),
        ),
    )


def _apply_cross_gate_policy(
    events: list[ScoutRuntimeSafetyGateEvent],
    proposed_transition: SafetyLnTransitionCandidate,
    *,
    policy_trace: list[str],
    suppressed_reasons: list[str],
    suppressed_gate_ids: list[str],
    corroborating_gate_ids: list[str],
) -> SafetyLnTransitionCandidate:
    if not events:
        policy_trace.append("no contributing gates")
        return "none"

    gate_ids = {event.gate_id for event in events}
    physiologic = [event for event in events if event.gate_id == "physiologic_gate"]
    route_pressure_gate_ids = {
        "pace_gate",
        "delay_gate",
        "darkness_gate",
    } & gate_ids
    hard_gate_events = [
        event
        for event in events
        if event.gate_id in _HARD_SINGLE_GATE_ESCALATORS
        and event.confidence in {"medium", "high"}
    ]

    if physiologic and route_pressure_gate_ids:
        max_physio = max(
            _transition_rank(event.ln_transition_candidate) for event in physiologic
        )
        if max_physio >= _transition_rank("candidate_rest"):
            policy_trace.append("physiologic pressure corroborated by route pressure")
            corroborating_gate_ids.extend(sorted(route_pressure_gate_ids | {"physiologic_gate"}))
            proposed_transition = _max_transition(
                proposed_transition,
                "candidate_retreat",
            )

    if proposed_transition == "candidate_alert_review":
        hard_alert = any(
            event.gate_id in _HARD_SINGLE_GATE_ESCALATORS
            and event.ln_transition_candidate == "candidate_alert_review"
            and event.confidence in {"medium", "high"}
            for event in events
        )
        strong_multi_gate = len(corroborating_gate_ids) >= 2 and any(
            _transition_rank(event.ln_transition_candidate)
            >= _transition_rank("candidate_retreat")
            for event in events
        )
        if hard_alert or strong_multi_gate:
            policy_trace.append("alert review supported by hard gate or corroboration")
        else:
            proposed_transition = "candidate_retreat"
            suppressed_reasons.append("alert review requires hard current evidence or corroboration")
            suppressed_gate_ids.extend(event.gate_id for event in events if event.severity == "alert_review")

    if proposed_transition == "candidate_retreat" and len(events) == 1:
        event = events[0]
        if (
            event.gate_id not in _HARD_SINGLE_GATE_ESCALATORS
            and event.confidence == "low"
            and not event.route_pressure_review_required
        ):
            proposed_transition = "candidate_rest"
            policy_trace.append("weak single-gate retreat candidate suppressed")
            suppressed_reasons.append("single low-confidence non-hard gate cannot own retreat")
            suppressed_gate_ids.append(event.gate_id)
    elif hard_gate_events:
        policy_trace.append("hard gate evidence can escalate without physiologic corroboration")

    return proposed_transition


def _apply_hysteresis(
    proposed_transition: SafetyLnTransitionCandidate,
    hysteresis: RuntimeSafetyReducerHysteresisInput,
) -> tuple[SafetyLnTransitionCandidate, RuntimeSafetyReducerHysteresisResult]:
    previous_transition = _transition_for_level(hysteresis.previous_ln_level)
    proposed_rank = _transition_rank(proposed_transition)
    previous_rank = _transition_rank(previous_transition)
    suppressed_reasons: list[str] = []
    final_transition = proposed_transition
    escalated = proposed_rank > previous_rank
    held = False
    if proposed_rank < previous_rank:
        if hysteresis.clear_window_count < 2:
            final_transition = previous_transition
            held = True
            suppressed_reasons.append("de-escalation held until two clear windows")
        else:
            final_transition = proposed_transition
    return (
        final_transition,
        RuntimeSafetyReducerHysteresisResult(
            escalated_immediately=escalated,
            deescalation_held=held,
            previous_ln_level=hysteresis.previous_ln_level,
            proposed_ln_level=_LEVEL_BY_TRANSITION[proposed_transition],
            final_ln_level=_LEVEL_BY_TRANSITION[final_transition],
            suppressed_reasons=suppressed_reasons,
        ),
    )


def _corroborating_gate_ids(events: list[ScoutRuntimeSafetyGateEvent]) -> list[str]:
    gate_ids = {event.gate_id for event in events}
    corroborating = set()
    if "physiologic_gate" in gate_ids and (
        {"pace_gate", "delay_gate", "darkness_gate"} & gate_ids
    ):
        corroborating.update({"physiologic_gate"} | (gate_ids & {"pace_gate", "delay_gate", "darkness_gate"}))
    if "weather_gate" in gate_ids and "environment_threat_gate" in gate_ids:
        corroborating.update({"weather_gate", "environment_threat_gate"})
    return sorted(corroborating)


def _event_summary(event: ScoutRuntimeSafetyGateEvent) -> dict[str, Any]:
    return {
        "gate_id": event.gate_id,
        "event_id": event.event_id,
        "sha256": event.sha256,
        "severity": event.severity,
        "ln_transition_candidate": event.ln_transition_candidate,
        "ln_level_candidate": event.ln_level_candidate,
        "state_candidate": event.state_candidate,
        "confidence": event.confidence,
        "route_pressure_review_required": event.route_pressure_review_required,
        "eta_delay_minutes": event.eta_delay_minutes,
        "route_id": event.route_context.route_id,
        "segment_id": event.route_context.segment_id,
        "checkpoint_id": event.route_context.checkpoint_id,
        "dominant_reasons": event.dominant_reasons,
        "evidence_refs": event.evidence_refs,
        "map_target_ids": event.route_context.map_target_ids,
        "source_path": event.source_path,
        "source_provider": event.source_provider,
    }


def _transition_for_level(level: SafetyLnLevelCandidate) -> SafetyLnTransitionCandidate:
    by_level = {level_value: transition for transition, level_value in _LEVEL_BY_TRANSITION.items()}
    return by_level[level]


def _max_transition(
    left: SafetyLnTransitionCandidate,
    right: SafetyLnTransitionCandidate,
) -> SafetyLnTransitionCandidate:
    return left if _transition_rank(left) >= _transition_rank(right) else right


def _transition_rank(value: str) -> int:
    order = {
        "none": 0,
        "candidate_watch": 1,
        "candidate_rest": 2,
        "candidate_retreat": 3,
        "candidate_alert_review": 4,
    }
    return order.get(value, 0)


def _confidence_rank(value: str) -> int:
    order = {"low": 0, "medium": 1, "high": 2}
    return order.get(value, 0)


def _max_confidence(values: list[Any]) -> SafetyGateConfidence:
    rank = {"low": 0, "medium": 1, "high": 2}
    valid = [str(value) for value in values if str(value) in rank]
    if not valid:
        return "low"
    return max(valid, key=lambda item: rank[item])  # type: ignore[return-value]


def _forbidden_key_paths(value: Any, prefix: str = "") -> list[str]:
    if isinstance(value, dict):
        paths: list[str] = []
        for key, child in value.items():
            child_path = f"{prefix}.{key}" if prefix else str(key)
            if str(key).lower() in FORBIDDEN_RAW_KEYS:
                paths.append(child_path)
            paths.extend(_forbidden_key_paths(child, child_path))
        return paths
    if isinstance(value, list):
        paths = []
        for index, child in enumerate(value):
            paths.extend(_forbidden_key_paths(child, f"{prefix}[{index}]"))
        return paths
    return []


def _unique_string_list(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value is None or value == "":
            continue
        item = str(value)
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
