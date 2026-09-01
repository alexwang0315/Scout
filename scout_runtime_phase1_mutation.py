from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from safety_models import (
    SafetyEvent,
    SafetyEventType,
    SafetyLevel,
    SafetyState,
    SafetyTransition,
)
from safety_state_machine import SafetyStateMachine
from scout_energy_models import aggregate_sha256, sha256_file
from scout_runtime_safety_gate_models import (
    SafetyGateConfidence,
    SafetyLnLevelCandidate,
    SafetyLnTransitionCandidate,
)
from scout_runtime_safety_reducer import (
    ProductionGateResidencyAudit,
    ProductionLiveEvidenceContractAudit,
    RuntimeSafetyPhase1AdapterResult,
    RuntimeSafetyReducerDecision,
    RuntimeSafetyReducerDataQuality,
)
from scout_runtime_safety_state_store import RuntimeSafetyStateSnapshot
from scout_wearable_validator import FORBIDDEN_RAW_KEYS


Phase1MutationStatus = Literal["applied_transition", "accepted_no_transition"]
Phase1RuntimePromotionReadinessStatus = Literal[
    "blocked_lineage_mismatch",
    "blocked_adapter_not_prepared",
    "blocked_production_gate_residency",
    "blocked_live_evidence_contract",
    "blocked_runtime_authority_missing",
    "blocked_operator_review_missing",
    "ready_for_deterministic_writer",
]
Phase1RuntimeWriterInvocationMode = Literal["dry_run", "local_test_writer"]
Phase1RuntimeWriterInvocationStatus = Literal[
    "blocked_request_mismatch",
    "blocked_readiness_not_ready",
    "blocked_requires_authenticated_operator",
    "blocked_requires_explicit_confirmation",
    "dry_run_ready",
    "local_writer_invoked",
]
Phase1RuntimeWriterDeploymentReadinessStatus = Literal[
    "blocked_writer_invocation_not_ready",
    "blocked_deployment_lineage_mismatch",
    "blocked_runtime_boundary_missing",
    "blocked_rollback_plan_missing",
    "blocked_operator_review_missing",
    "ready_for_reviewed_production_deployment",
]

_PHASE1_RUNTIME_WRITER_CONFIRMATION_PHRASE = "APPLY PHASE 1 LOCAL WRITER"

_PHASE1_LEVEL_BY_CANDIDATE: dict[str, SafetyLevel] = {
    "L0_NORMAL": SafetyLevel.NORMAL,
    "L1_CAUTION": SafetyLevel.WATCH,
    "L2_CONCERN": SafetyLevel.CONCERN,
    "L3_RETREAT": SafetyLevel.DISTRESS,
    "L4_ALERT_REVIEW": SafetyLevel.EMERGENCY,
}
_EVENT_TYPE_BY_GATE: dict[str, SafetyEventType] = {
    "pace_gate": SafetyEventType.PACE_PRESSURE,
    "delay_gate": SafetyEventType.DELAY_PRESSURE,
    "physiologic_gate": SafetyEventType.PHYSIOLOGIC_PRESSURE,
    "weather_gate": SafetyEventType.WEATHER_THREAT,
    "darkness_gate": SafetyEventType.DARKNESS_RISK,
    "environment_threat_gate": SafetyEventType.ENVIRONMENT_THREAT,
}
_CONFIDENCE_SCORE: dict[str, float] = {"low": 0.45, "medium": 0.7, "high": 0.9}
_PHASE1_STATE_MACHINE_ALLOWED_KEYS = {"timestamp"}


class Phase1TransitionPrivacy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_only: bool = True
    aggregate_only: bool = True
    raw_health_payload_shared: bool = False
    raw_track_shared: bool = False
    raw_gpx_shared: bool = False
    precise_timestamps_shared: bool = False
    home_work_trace_shared: bool = False
    shareable_by_default: bool = False

    @model_validator(mode="after")
    def enforce_privacy(self) -> "Phase1TransitionPrivacy":
        if (
            self.raw_health_payload_shared
            or self.raw_track_shared
            or self.raw_gpx_shared
            or self.precise_timestamps_shared
            or self.home_work_trace_shared
        ):
            raise ValueError("Phase 1 mutation artifacts cannot share raw private payloads")
        return self


class Phase1TransitionDataQuality(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confidence: SafetyGateConfidence = "low"
    gate_event_count: int = Field(default=0, ge=0)
    contributing_gate_count: int = Field(default=0, ge=0)
    missing_gate_ids: list[str] = Field(default_factory=list)
    stale_signal_names: list[str] = Field(default_factory=list)
    live_network_calls_made: bool = False
    limitations: list[str] = Field(default_factory=list)

    @classmethod
    def from_reducer(
        cls,
        data_quality: RuntimeSafetyReducerDataQuality,
        *,
        extra_limitations: list[str] | None = None,
    ) -> "Phase1TransitionDataQuality":
        return cls(
            confidence=data_quality.confidence,
            gate_event_count=data_quality.gate_event_count,
            contributing_gate_count=data_quality.contributing_gate_count,
            missing_gate_ids=data_quality.missing_gate_ids,
            stale_signal_names=data_quality.stale_signal_names,
            live_network_calls_made=data_quality.live_network_calls_made,
            limitations=[
                *data_quality.limitations,
                *(extra_limitations or []),
            ],
        )


class Phase1TransitionRequestBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reducer_owned: bool = True
    individual_gate_owned: bool = False
    transition_request_only: bool = True
    deterministic_writer_required: bool = True
    phase1_runtime_mutation_requested: bool = True
    runtime_safety_truth: bool = False
    phase1_runtime_safety_truth: bool = False
    phase1_l0_l4_state_mutated: bool = False
    safety_api_called: bool = False
    outbound_alert_sent: bool = False
    medical_diagnosis: bool = False
    raw_health_payload_shared: bool = False
    raw_track_shared: bool = False
    raw_gpx_shared: bool = False
    precise_timestamps_shared: bool = False
    home_work_trace_shared: bool = False

    @model_validator(mode="after")
    def enforce_request_boundary(self) -> "Phase1TransitionRequestBoundary":
        if not self.reducer_owned or self.individual_gate_owned:
            raise ValueError("Phase 1 transition requests must be reducer-owned")
        if not self.transition_request_only or not self.deterministic_writer_required:
            raise ValueError("Phase 1 transition request must require deterministic writer")
        if (
            self.runtime_safety_truth
            or self.phase1_runtime_safety_truth
            or self.phase1_l0_l4_state_mutated
        ):
            raise ValueError("Phase 1 transition request cannot claim mutation already happened")
        if self.safety_api_called:
            raise ValueError("Phase 1 transition request cannot call /safety/*")
        if self.outbound_alert_sent:
            raise ValueError("Phase 1 transition request cannot send outbound alerts")
        if self.medical_diagnosis:
            raise ValueError("Phase 1 transition request cannot be a medical diagnosis")
        _raise_if_private_payload_shared(self)
        return self


class Phase1MutationBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reducer_owned: bool = True
    deterministic_writer: bool = True
    phase1_runtime_safety_truth: bool = True
    phase1_l0_l4_state_mutated: bool = True
    safety_state_machine_applied: bool = True
    safety_api_called: bool = False
    outbound_alert_sent: bool = False
    outbound_policy_separate: bool = True
    medical_diagnosis: bool = False
    raw_health_payload_shared: bool = False
    raw_track_shared: bool = False
    raw_gpx_shared: bool = False
    precise_timestamps_shared: bool = False
    home_work_trace_shared: bool = False

    @model_validator(mode="after")
    def enforce_mutation_boundary(self) -> "Phase1MutationBoundary":
        if not (
            self.reducer_owned
            and self.deterministic_writer
            and self.phase1_runtime_safety_truth
            and self.phase1_l0_l4_state_mutated
            and self.safety_state_machine_applied
        ):
            raise ValueError("Phase 1 mutation result must be deterministic runtime truth")
        if self.safety_api_called:
            raise ValueError("Phase 1 mutation service cannot call /safety/*")
        if self.outbound_alert_sent:
            raise ValueError("Phase 1 mutation service cannot send outbound alerts")
        if not self.outbound_policy_separate:
            raise ValueError("outbound policy must stay separate from Phase 1 mutation")
        if self.medical_diagnosis:
            raise ValueError("Phase 1 mutation result cannot be a medical diagnosis")
        _raise_if_private_payload_shared(self)
        return self


class Phase1TransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_phase1_transition_request"
    artifact_version: str = "phase1_transition_request.v1"
    request_id: str = Field(min_length=1)
    source_provider: str = "scout_runtime_phase1_mutation"
    source_path: str = Field(min_length=1)
    sha256: str = Field(min_length=1)
    reducer_sha256: str = Field(min_length=1)
    reducer_source_path: str = Field(min_length=1)
    adapter_sha256: str = Field(min_length=1)
    adapter_source_path: str = Field(min_length=1)
    state_snapshot_id: str | None = None
    state_snapshot_sha256: str | None = None
    selected_gate_id: str = Field(min_length=1)
    selected_event_sha256: str | None = None
    contributing_gate_ids: list[str] = Field(default_factory=list)
    corroborating_gate_ids: list[str] = Field(default_factory=list)
    suppressed_gate_ids: list[str] = Field(default_factory=list)
    requested_ln_level_candidate: SafetyLnLevelCandidate
    requested_ln_transition_candidate: SafetyLnTransitionCandidate
    target_safety_level: SafetyLevel
    target_event_type: SafetyEventType
    reducer_recommendation: str
    event_time_offset_s: float = Field(default=0.0, ge=0.0)
    reason: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    route_id: str | None = None
    segment_id: str | None = None
    checkpoint_id: str | None = None
    map_target_ids: list[str] = Field(default_factory=list)
    eta_delay_minutes: int = Field(default=0, ge=0)
    route_pressure_review_required: bool = False
    evidence_refs: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    data_quality: Phase1TransitionDataQuality = Field(
        default_factory=Phase1TransitionDataQuality
    )
    privacy: Phase1TransitionPrivacy = Field(default_factory=Phase1TransitionPrivacy)
    boundary: Phase1TransitionRequestBoundary = Field(
        default_factory=Phase1TransitionRequestBoundary
    )

    @model_validator(mode="after")
    def enforce_request(self) -> "Phase1TransitionRequest":
        expected_level = _PHASE1_LEVEL_BY_CANDIDATE[self.requested_ln_level_candidate]
        if self.target_safety_level != expected_level:
            raise ValueError("target safety level must match requested L_n candidate")
        if self.target_event_type != _EVENT_TYPE_BY_GATE.get(
            self.selected_gate_id,
            SafetyEventType.UNSAFE_CONTINUATION,
        ):
            raise ValueError("target event type must match selected gate")
        if not self.contributing_gate_ids:
            raise ValueError("Phase 1 transition request requires contributing gates")
        if self.selected_gate_id not in self.contributing_gate_ids:
            raise ValueError("selected gate must be a contributing gate")
        forbidden_paths = _forbidden_key_paths(self.model_dump(mode="json"))
        if forbidden_paths:
            raise ValueError(
                "forbidden Phase 1 transition request fields present: "
                + ", ".join(forbidden_paths)
            )
        return self


class Phase1MutationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_phase1_safety_mutation_result"
    artifact_version: str = "phase1_safety_mutation_result.v1"
    mutation_id: str = Field(min_length=1)
    source_provider: str = "scout_runtime_phase1_mutation"
    source_path: str = Field(min_length=1)
    sha256: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    request_sha256: str = Field(min_length=1)
    status: Phase1MutationStatus
    previous_safety_level: SafetyLevel
    resulting_safety_level: SafetyLevel
    transition_performed: bool
    safety_event: SafetyEvent
    transition: SafetyTransition | None = None
    safety_state: SafetyState
    data_quality: Phase1TransitionDataQuality = Field(
        default_factory=Phase1TransitionDataQuality
    )
    privacy: Phase1TransitionPrivacy = Field(default_factory=Phase1TransitionPrivacy)
    boundary: Phase1MutationBoundary = Field(default_factory=Phase1MutationBoundary)

    @model_validator(mode="after")
    def enforce_result(self) -> "Phase1MutationResult":
        if self.transition_performed != (self.transition is not None):
            raise ValueError("transition_performed must match transition presence")
        if self.resulting_safety_level != self.safety_state.level:
            raise ValueError("resulting safety level must match safety state")
        if self.status == "applied_transition" and not self.transition_performed:
            raise ValueError("applied_transition requires a transition")
        if self.status == "accepted_no_transition" and self.transition_performed:
            raise ValueError("accepted_no_transition cannot include a transition")
        forbidden_paths = _forbidden_key_paths(self.model_dump(mode="json"))
        if forbidden_paths:
            raise ValueError(
                "forbidden Phase 1 mutation result fields present: "
                + ", ".join(forbidden_paths)
            )
        return self


class Phase1MutationAuditSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mutation_id: str = Field(min_length=1)
    mutation_path: str = Field(min_length=1)
    sha256: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    request_sha256: str = Field(min_length=1)
    status: Phase1MutationStatus
    previous_safety_level: SafetyLevel
    resulting_safety_level: SafetyLevel
    transition_performed: bool
    event_type: SafetyEventType


class Phase1MutationAuditIndex(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_phase1_safety_mutation_audit_index"
    artifact_version: str = "phase1_safety_mutation_audit_index.v1"
    source_provider: str = "scout_runtime_phase1_mutation"
    source_path: str = Field(min_length=1)
    sha256: str = Field(min_length=1)
    mutation_count: int = Field(ge=0)
    latest_mutation_id: str | None = None
    latest_safety_level: SafetyLevel | None = None
    mutations: list[Phase1MutationAuditSummary] = Field(default_factory=list)
    privacy: Phase1TransitionPrivacy = Field(default_factory=Phase1TransitionPrivacy)
    boundary: Phase1MutationBoundary | None = None

    @model_validator(mode="after")
    def enforce_index(self) -> "Phase1MutationAuditIndex":
        if self.mutation_count != len(self.mutations):
            raise ValueError("mutation_count must match mutations")
        if self.mutations:
            latest = self.mutations[-1]
            if self.latest_mutation_id != latest.mutation_id:
                raise ValueError("latest mutation id must match last audit summary")
            if self.latest_safety_level != latest.resulting_safety_level:
                raise ValueError("latest safety level must match last audit summary")
        elif self.latest_mutation_id is not None or self.latest_safety_level is not None:
            raise ValueError("empty mutation audit cannot declare latest fields")
        return self


class Phase1MutationProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_phase1_safety_mutation_projection"
    artifact_version: str = "phase1_safety_mutation_projection.v1"
    status: Literal["ready", "missing", "error"]
    project_id: str
    source_provider: str = "scout_runtime_phase1_mutation"
    source_path: str = ""
    sha256: str | None = None
    latest_mutation_id: str | None = None
    latest_safety_level: SafetyLevel | None = None
    mutation_count: int = Field(default=0, ge=0)
    surface_targets: list[str] = Field(default_factory=lambda: ["/admin/debug", "/admin"])
    timeline_events: list[dict[str, Any]] = Field(default_factory=list)
    privacy: Phase1TransitionPrivacy = Field(default_factory=Phase1TransitionPrivacy)
    boundary: Phase1MutationBoundary | None = None
    error_type: str | None = None
    error: str | None = None


class Phase1RuntimePromotionReadinessBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deterministic_readiness_gate_only: bool = True
    phase1_writer_invoked: bool = False
    runtime_safety_truth: bool = False
    phase1_runtime_safety_truth: bool = False
    phase1_l0_l4_state_mutated: bool = False
    safety_api_called: bool = False
    outbound_alert_sent: bool = False
    network_connection_attempted: bool = False
    external_send_performed: bool = False
    hardware_control_performed: bool = False
    private_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_readiness_boundary(
        self,
    ) -> "Phase1RuntimePromotionReadinessBoundary":
        if not self.deterministic_readiness_gate_only:
            raise ValueError("Phase 1 promotion readiness is a deterministic gate only")
        if (
            self.phase1_writer_invoked
            or self.runtime_safety_truth
            or self.phase1_runtime_safety_truth
            or self.phase1_l0_l4_state_mutated
            or self.safety_api_called
            or self.outbound_alert_sent
            or self.network_connection_attempted
            or self.external_send_performed
            or self.hardware_control_performed
            or self.private_payload_embedded
        ):
            raise ValueError("Phase 1 promotion readiness cannot perform effects")
        return self


class Phase1RuntimePromotionReadinessGate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_phase1_runtime_promotion_readiness_gate"
    artifact_version: str = "phase1_runtime_promotion_readiness_gate.v0"
    source_provider: str = "scout_runtime_phase1_mutation"
    source_path: str
    sha256: str = Field(min_length=1)
    status: Phase1RuntimePromotionReadinessStatus
    reducer_sha256: str = Field(min_length=1)
    adapter_sha256: str = Field(min_length=1)
    transition_request_sha256: str = Field(min_length=1)
    production_gate_residency_audit_sha256: str = Field(min_length=1)
    live_evidence_contract_audit_sha256: str = Field(min_length=1)
    runtime_authority_ref: str | None = None
    runtime_authority_sha256: str | None = None
    operator_review_ref: str | None = None
    operator_review_sha256: str | None = None
    lineage_match: bool = False
    adapter_prepared: bool = False
    production_gate_residency_ready: bool = False
    live_evidence_contract_ready: bool = False
    runtime_authority_present: bool = False
    operator_review_present: bool = False
    deterministic_writer_preconditions_met: bool = False
    phase1_writer_invocation_performed: bool = False
    runtime_safety_truth: bool = False
    phase1_runtime_safety_truth: bool = False
    phase1_l0_l4_state_mutated: bool = False
    safety_api_called: bool = False
    outbound_alert_sent: bool = False
    network_connection_attempted: bool = False
    external_send_performed: bool = False
    hardware_control_performed: bool = False
    reasons: list[str] = Field(default_factory=list)
    privacy: Phase1TransitionPrivacy = Field(default_factory=Phase1TransitionPrivacy)
    boundary: Phase1RuntimePromotionReadinessBoundary = Field(
        default_factory=Phase1RuntimePromotionReadinessBoundary
    )

    @model_validator(mode="after")
    def enforce_promotion_readiness(self) -> "Phase1RuntimePromotionReadinessGate":
        ready = self.status == "ready_for_deterministic_writer"
        if self.deterministic_writer_preconditions_met != ready:
            raise ValueError("promotion readiness flag must match status")
        if ready and not (
            self.lineage_match
            and self.adapter_prepared
            and self.production_gate_residency_ready
            and self.live_evidence_contract_ready
            and self.runtime_authority_present
            and self.operator_review_present
        ):
            raise ValueError("ready promotion gate requires every prerequisite")
        if (
            self.phase1_writer_invocation_performed
            or self.runtime_safety_truth
            or self.phase1_runtime_safety_truth
            or self.phase1_l0_l4_state_mutated
            or self.safety_api_called
            or self.outbound_alert_sent
            or self.network_connection_attempted
            or self.external_send_performed
            or self.hardware_control_performed
        ):
            raise ValueError("promotion readiness gate cannot perform effects")
        forbidden_paths = _forbidden_key_paths(self.model_dump(mode="json"))
        if forbidden_paths:
            raise ValueError(
                "forbidden Phase 1 promotion readiness fields present: "
                + ", ".join(forbidden_paths)
            )
        return self


class Phase1RuntimeWriterInvocationBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deterministic_invocation_guard: bool = True
    local_state_machine_only: bool = True
    production_runtime_write_performed: bool = False
    production_runtime_safety_truth_mutated: bool = False
    safety_api_called: bool = False
    outbound_alert_sent: bool = False
    network_connection_attempted: bool = False
    external_send_performed: bool = False
    hardware_control_performed: bool = False
    private_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_invocation_boundary(
        self,
    ) -> "Phase1RuntimeWriterInvocationBoundary":
        if not self.deterministic_invocation_guard or not self.local_state_machine_only:
            raise ValueError("Phase 1 writer invocation must stay locally guarded")
        if (
            self.production_runtime_write_performed
            or self.production_runtime_safety_truth_mutated
            or self.safety_api_called
            or self.outbound_alert_sent
            or self.network_connection_attempted
            or self.external_send_performed
            or self.hardware_control_performed
            or self.private_payload_embedded
        ):
            raise ValueError("Phase 1 writer invocation guard cannot perform external effects")
        return self


class Phase1RuntimeWriterInvocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_phase1_runtime_writer_invocation_request"
    artifact_version: str = "phase1_runtime_writer_invocation_request.v0"
    readiness_gate_sha256: str = Field(min_length=1)
    transition_request_sha256: str = Field(min_length=1)
    execution_mode: Phase1RuntimeWriterInvocationMode = "dry_run"
    idempotency_key: str = Field(min_length=1, max_length=128)
    explicit_confirmation: bool = False
    operator_identity_ref: str | None = None
    operator_authenticated: bool = False
    operator_approval_phrase: str | None = None

    @model_validator(mode="after")
    def enforce_writer_invocation_request(
        self,
    ) -> "Phase1RuntimeWriterInvocationRequest":
        if self.operator_authenticated and not self.operator_identity_ref:
            raise ValueError("authenticated writer invocation requires operator identity")
        forbidden_paths = _forbidden_key_paths(self.model_dump(mode="json"))
        if forbidden_paths:
            raise ValueError(
                "forbidden Phase 1 writer invocation request fields present: "
                + ", ".join(forbidden_paths)
            )
        return self


class Phase1RuntimeWriterInvocationReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_phase1_runtime_writer_invocation_receipt"
    artifact_version: str = "phase1_runtime_writer_invocation_receipt.v0"
    source_provider: str = "scout_runtime_phase1_mutation"
    source_path: str
    sha256: str = Field(min_length=1)
    request_sha256: str = Field(min_length=1)
    readiness_gate_sha256: str = Field(min_length=1)
    transition_request_sha256: str = Field(min_length=1)
    execution_mode: Phase1RuntimeWriterInvocationMode
    status: Phase1RuntimeWriterInvocationStatus
    readiness_gate_accepted: bool = False
    operator_approval_recorded: bool = False
    local_phase1_writer_invoked: bool = False
    local_phase1_l0_l4_state_mutated: bool = False
    production_runtime_write_performed: bool = False
    production_runtime_safety_truth_mutated: bool = False
    safety_api_called: bool = False
    outbound_alert_sent: bool = False
    network_connection_attempted: bool = False
    external_send_performed: bool = False
    hardware_control_performed: bool = False
    mutation_result_sha256: str | None = None
    mutation_id: str | None = None
    mutation_status: Phase1MutationStatus | None = None
    previous_safety_level: SafetyLevel | None = None
    resulting_safety_level: SafetyLevel | None = None
    reasons: list[str] = Field(default_factory=list)
    privacy: Phase1TransitionPrivacy = Field(default_factory=Phase1TransitionPrivacy)
    boundary: Phase1RuntimeWriterInvocationBoundary = Field(
        default_factory=Phase1RuntimeWriterInvocationBoundary
    )

    @model_validator(mode="after")
    def enforce_writer_invocation_receipt(
        self,
    ) -> "Phase1RuntimeWriterInvocationReceipt":
        invoked = self.status == "local_writer_invoked"
        if self.local_phase1_writer_invoked != invoked:
            raise ValueError("local writer invoked flag must match status")
        if invoked and not self.mutation_result_sha256:
            raise ValueError("local writer invocation requires mutation result hash")
        if not invoked and (
            self.local_phase1_l0_l4_state_mutated
            or self.mutation_result_sha256
            or self.mutation_id
            or self.mutation_status
            or self.previous_safety_level
            or self.resulting_safety_level
        ):
            raise ValueError("blocked or dry-run invocation cannot include mutation result")
        if (
            self.production_runtime_write_performed
            or self.production_runtime_safety_truth_mutated
            or self.safety_api_called
            or self.outbound_alert_sent
            or self.network_connection_attempted
            or self.external_send_performed
            or self.hardware_control_performed
        ):
            raise ValueError("writer invocation receipt cannot claim external effects")
        forbidden_paths = _forbidden_key_paths(self.model_dump(mode="json"))
        if forbidden_paths:
            raise ValueError(
                "forbidden Phase 1 writer invocation receipt fields present: "
                + ", ".join(forbidden_paths)
            )
        return self


class Phase1RuntimeWriterDeploymentBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deterministic_deployment_readiness_only: bool = True
    production_runtime_write_performed: bool = False
    production_runtime_safety_truth_mutated: bool = False
    safety_api_called: bool = False
    outbound_alert_sent: bool = False
    network_connection_attempted: bool = False
    external_send_performed: bool = False
    hardware_control_performed: bool = False
    private_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_deployment_boundary(
        self,
    ) -> "Phase1RuntimeWriterDeploymentBoundary":
        if not self.deterministic_deployment_readiness_only:
            raise ValueError("Phase 1 writer deployment readiness must be deterministic")
        if (
            self.production_runtime_write_performed
            or self.production_runtime_safety_truth_mutated
            or self.safety_api_called
            or self.outbound_alert_sent
            or self.network_connection_attempted
            or self.external_send_performed
            or self.hardware_control_performed
            or self.private_payload_embedded
        ):
            raise ValueError("Phase 1 writer deployment readiness cannot perform effects")
        return self


class Phase1RuntimeWriterDeploymentManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_phase1_runtime_writer_deployment_manifest"
    artifact_version: str = "phase1_runtime_writer_deployment_manifest.v0"
    readiness_gate_sha256: str = Field(min_length=1)
    writer_invocation_receipt_sha256: str = Field(min_length=1)
    transition_request_sha256: str = Field(min_length=1)
    runtime_environment_ref: str | None = None
    runtime_deployment_ref: str | None = None
    runtime_authority_ref: str | None = None
    runtime_authority_sha256: str | None = None
    writer_effect_boundary_ref: str | None = None
    writer_effect_boundary_sha256: str | None = None
    rollback_plan_ref: str | None = None
    rollback_plan_sha256: str | None = None
    operator_review_ref: str | None = None
    operator_review_sha256: str | None = None
    deployment_idempotency_key: str = Field(min_length=1, max_length=128)
    production_runtime_write_performed: bool = False
    production_runtime_safety_truth_mutated: bool = False
    safety_api_called: bool = False
    outbound_alert_sent: bool = False
    network_connection_attempted: bool = False
    external_send_performed: bool = False
    hardware_control_performed: bool = False
    private_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_deployment_manifest(
        self,
    ) -> "Phase1RuntimeWriterDeploymentManifest":
        if (
            self.production_runtime_write_performed
            or self.production_runtime_safety_truth_mutated
            or self.safety_api_called
            or self.outbound_alert_sent
            or self.network_connection_attempted
            or self.external_send_performed
            or self.hardware_control_performed
            or self.private_payload_embedded
        ):
            raise ValueError("Phase 1 writer deployment manifest cannot perform effects")
        forbidden_paths = _forbidden_key_paths(self.model_dump(mode="json"))
        if forbidden_paths:
            raise ValueError(
                "forbidden Phase 1 writer deployment fields present: "
                + ", ".join(forbidden_paths)
            )
        return self


class Phase1RuntimeWriterDeploymentReadinessAudit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_phase1_runtime_writer_deployment_readiness"
    artifact_version: str = "phase1_runtime_writer_deployment_readiness.v0"
    source_provider: str = "scout_runtime_phase1_mutation"
    source_path: str
    sha256: str = Field(min_length=1)
    status: Phase1RuntimeWriterDeploymentReadinessStatus
    readiness_gate_sha256: str = Field(min_length=1)
    writer_invocation_receipt_sha256: str = Field(min_length=1)
    transition_request_sha256: str = Field(min_length=1)
    deployment_manifest_sha256: str = Field(min_length=1)
    writer_invocation_ready: bool = False
    deployment_lineage_match: bool = False
    runtime_boundary_present: bool = False
    rollback_plan_present: bool = False
    operator_review_present: bool = False
    ready_for_reviewed_production_deployment: bool = False
    runtime_environment_ref: str | None = None
    runtime_deployment_ref: str | None = None
    runtime_authority_ref: str | None = None
    runtime_authority_sha256: str | None = None
    writer_effect_boundary_ref: str | None = None
    writer_effect_boundary_sha256: str | None = None
    rollback_plan_ref: str | None = None
    rollback_plan_sha256: str | None = None
    operator_review_ref: str | None = None
    operator_review_sha256: str | None = None
    production_runtime_write_performed: bool = False
    production_runtime_safety_truth_mutated: bool = False
    safety_api_called: bool = False
    outbound_alert_sent: bool = False
    network_connection_attempted: bool = False
    external_send_performed: bool = False
    hardware_control_performed: bool = False
    reasons: list[str] = Field(default_factory=list)
    privacy: Phase1TransitionPrivacy = Field(default_factory=Phase1TransitionPrivacy)
    boundary: Phase1RuntimeWriterDeploymentBoundary = Field(
        default_factory=Phase1RuntimeWriterDeploymentBoundary
    )

    @model_validator(mode="after")
    def enforce_deployment_readiness(
        self,
    ) -> "Phase1RuntimeWriterDeploymentReadinessAudit":
        ready = self.status == "ready_for_reviewed_production_deployment"
        if self.ready_for_reviewed_production_deployment != ready:
            raise ValueError("deployment readiness flag must match status")
        if ready and not (
            self.writer_invocation_ready
            and self.deployment_lineage_match
            and self.runtime_boundary_present
            and self.rollback_plan_present
            and self.operator_review_present
        ):
            raise ValueError("ready deployment audit requires every prerequisite")
        if (
            self.production_runtime_write_performed
            or self.production_runtime_safety_truth_mutated
            or self.safety_api_called
            or self.outbound_alert_sent
            or self.network_connection_attempted
            or self.external_send_performed
            or self.hardware_control_performed
        ):
            raise ValueError("Phase 1 writer deployment audit cannot perform effects")
        forbidden_paths = _forbidden_key_paths(self.model_dump(mode="json"))
        if forbidden_paths:
            raise ValueError(
                "forbidden Phase 1 writer deployment audit fields present: "
                + ", ".join(forbidden_paths)
            )
        return self


class Phase1SafetyMutationService:
    def __init__(self, initial_state: SafetyState | None = None) -> None:
        self.state_machine = SafetyStateMachine(initial_state)

    def apply_transition_request(
        self,
        request: Phase1TransitionRequest | dict[str, Any],
        *,
        source_path: str = "inline:phase1-safety-mutation-result",
    ) -> Phase1MutationResult:
        request_model = (
            request
            if isinstance(request, Phase1TransitionRequest)
            else Phase1TransitionRequest.model_validate(request)
        )
        event = safety_event_from_phase1_transition_request(request_model)
        previous_level = self.state_machine.state.level
        transition = self.state_machine.apply_event(event)
        resulting_level = self.state_machine.state.level
        status: Phase1MutationStatus = (
            "applied_transition" if transition is not None else "accepted_no_transition"
        )
        mutation_id = _mutation_id(request_model, previous_level, resulting_level)
        digest = aggregate_sha256(
            [
                {
                    "mutation_id": mutation_id,
                    "source_path": source_path,
                    "request_sha256": request_model.sha256,
                    "previous_level": previous_level.value,
                    "resulting_level": resulting_level.value,
                    "transition_performed": transition is not None,
                }
            ]
        )
        return Phase1MutationResult(
            mutation_id=mutation_id,
            source_path=source_path,
            sha256=digest,
            request_id=request_model.request_id,
            request_sha256=request_model.sha256,
            status=status,
            previous_safety_level=previous_level,
            resulting_safety_level=resulting_level,
            transition_performed=transition is not None,
            safety_event=event,
            transition=transition,
            safety_state=self.state_machine.state,
            data_quality=request_model.data_quality,
        )


class Phase1MutationAuditStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser()
        self.mutations_dir = self.root / "mutations"
        self.index_path = self.root / "phase1_safety_mutation_audit_index.json"
        self.mutations_dir.mkdir(parents=True, exist_ok=True)

    def save_result(
        self,
        result: Phase1MutationResult | dict[str, Any],
    ) -> Phase1MutationResult:
        result_model = (
            result
            if isinstance(result, Phase1MutationResult)
            else Phase1MutationResult.model_validate(result)
        )
        path = self.path_for(result_model.mutation_id)
        _atomic_write_json(path, result_model.model_dump(mode="json"))
        self.write_index()
        return self.load_result(result_model.mutation_id)

    def load_result(self, mutation_id: str) -> Phase1MutationResult:
        return load_phase1_mutation_result(self.path_for(mutation_id))

    def list_results(self) -> list[Phase1MutationResult]:
        return [
            load_phase1_mutation_result(path)
            for path in sorted(self.mutations_dir.glob("*.json"))
        ]

    def write_index(self) -> Phase1MutationAuditIndex:
        index = build_phase1_mutation_audit_index(
            self.list_results(),
            source_path=_relative_or_string(self.index_path, self.root),
        )
        _atomic_write_json(self.index_path, index.model_dump(mode="json"))
        return load_phase1_mutation_audit_index(self.index_path)

    def load_index(self) -> Phase1MutationAuditIndex:
        if not self.index_path.exists():
            return self.write_index()
        return load_phase1_mutation_audit_index(self.index_path)

    def path_for(self, mutation_id: str) -> Path:
        return self.mutations_dir / f"{mutation_id}.json"


def build_phase1_transition_request(
    reducer_decision: RuntimeSafetyReducerDecision | dict[str, Any],
    adapter_result: RuntimeSafetyPhase1AdapterResult | dict[str, Any],
    *,
    state_snapshot: RuntimeSafetyStateSnapshot | dict[str, Any] | None = None,
    source_path: str = "inline:phase1-transition-request",
    event_time_offset_s: float = 0.0,
) -> Phase1TransitionRequest:
    reducer = (
        reducer_decision
        if isinstance(reducer_decision, RuntimeSafetyReducerDecision)
        else RuntimeSafetyReducerDecision.model_validate(reducer_decision)
    )
    adapter = (
        adapter_result
        if isinstance(adapter_result, RuntimeSafetyPhase1AdapterResult)
        else RuntimeSafetyPhase1AdapterResult.model_validate(adapter_result)
    )
    snapshot = (
        None
        if state_snapshot is None
        else state_snapshot
        if isinstance(state_snapshot, RuntimeSafetyStateSnapshot)
        else RuntimeSafetyStateSnapshot.model_validate(state_snapshot)
    )
    if adapter.status != "transition_request_prepared":
        raise ValueError("Phase 1 transition request requires a prepared adapter")
    if adapter.selected_reducer_sha256 != reducer.sha256:
        raise ValueError("adapter result must reference reducer decision")
    if snapshot is not None and snapshot.reducer_sha256 != reducer.sha256:
        raise ValueError("state snapshot must reference reducer decision")
    if not reducer.selected_gate_id:
        raise ValueError("Phase 1 transition request requires selected gate")
    source_refs = _unique_string_list(
        [
            reducer.source_path,
            adapter.source_path,
            snapshot.source_path if snapshot else None,
        ]
    )
    map_target_ids = _unique_string_list(
        [
            target
            for summary in reducer.gate_summaries
            for target in summary.get("map_target_ids", [])
        ]
    )
    evidence_refs = _unique_string_list(
        [
            ref
            for summary in reducer.gate_summaries
            for ref in summary.get("evidence_refs", [])
        ]
    )
    reason = _mutation_reason(reducer)
    confidence = _CONFIDENCE_SCORE.get(reducer.data_quality.confidence, 0.45)
    target_level = _PHASE1_LEVEL_BY_CANDIDATE[reducer.ln_level_candidate]
    target_event_type = _EVENT_TYPE_BY_GATE.get(
        reducer.selected_gate_id,
        SafetyEventType.UNSAFE_CONTINUATION,
    )
    request_id = _request_id(reducer, adapter, snapshot)
    digest = aggregate_sha256(
        [
            {
                "request_id": request_id,
                "source_path": source_path,
                "reducer_sha256": reducer.sha256,
                "adapter_sha256": adapter.sha256,
                "snapshot_sha256": snapshot.sha256 if snapshot else None,
                "requested_ln_level": reducer.ln_level_candidate,
                "target_safety_level": target_level.value,
            }
        ]
    )
    return Phase1TransitionRequest(
        request_id=request_id,
        source_path=source_path,
        sha256=digest,
        reducer_sha256=reducer.sha256,
        reducer_source_path=reducer.source_path,
        adapter_sha256=adapter.sha256,
        adapter_source_path=adapter.source_path,
        state_snapshot_id=snapshot.snapshot_id if snapshot else None,
        state_snapshot_sha256=snapshot.sha256 if snapshot else None,
        selected_gate_id=reducer.selected_gate_id,
        selected_event_sha256=reducer.selected_event_sha256,
        contributing_gate_ids=reducer.contributing_gate_ids,
        corroborating_gate_ids=reducer.corroborating_gate_ids,
        suppressed_gate_ids=reducer.suppressed_gate_ids,
        requested_ln_level_candidate=reducer.ln_level_candidate,
        requested_ln_transition_candidate=reducer.ln_transition_candidate,
        target_safety_level=target_level,
        target_event_type=target_event_type,
        reducer_recommendation=reducer.recommendation,
        event_time_offset_s=event_time_offset_s,
        reason=reason,
        confidence=confidence,
        route_id=_first_summary_value(reducer, "route_id"),
        segment_id=_first_summary_value(reducer, "segment_id"),
        checkpoint_id=_first_summary_value(reducer, "checkpoint_id"),
        map_target_ids=map_target_ids,
        eta_delay_minutes=reducer.eta_delay_minutes,
        route_pressure_review_required=reducer.route_pressure_review_required,
        evidence_refs=evidence_refs,
        source_refs=source_refs,
        data_quality=Phase1TransitionDataQuality.from_reducer(
            reducer.data_quality,
            extra_limitations=[
                "Phase 1 transition request is local deterministic handoff",
                "outbound policy remains separate",
            ],
        ),
    )


def evaluate_phase1_runtime_promotion_readiness(
    transition_request: Phase1TransitionRequest | dict[str, Any],
    reducer_decision: RuntimeSafetyReducerDecision | dict[str, Any],
    adapter_result: RuntimeSafetyPhase1AdapterResult | dict[str, Any],
    gate_residency_audit: ProductionGateResidencyAudit | dict[str, Any],
    live_evidence_contract_audit: ProductionLiveEvidenceContractAudit | dict[str, Any],
    *,
    runtime_authority_ref: str | None = None,
    runtime_authority_sha256: str | None = None,
    operator_review_ref: str | None = None,
    operator_review_sha256: str | None = None,
    source_path: str = "inline:phase1-runtime-promotion-readiness-gate",
) -> Phase1RuntimePromotionReadinessGate:
    request = (
        transition_request
        if isinstance(transition_request, Phase1TransitionRequest)
        else Phase1TransitionRequest.model_validate(transition_request)
    )
    reducer = (
        reducer_decision
        if isinstance(reducer_decision, RuntimeSafetyReducerDecision)
        else RuntimeSafetyReducerDecision.model_validate(reducer_decision)
    )
    adapter = (
        adapter_result
        if isinstance(adapter_result, RuntimeSafetyPhase1AdapterResult)
        else RuntimeSafetyPhase1AdapterResult.model_validate(adapter_result)
    )
    residency = (
        gate_residency_audit
        if isinstance(gate_residency_audit, ProductionGateResidencyAudit)
        else ProductionGateResidencyAudit.model_validate(gate_residency_audit)
    )
    live_audit = (
        live_evidence_contract_audit
        if isinstance(live_evidence_contract_audit, ProductionLiveEvidenceContractAudit)
        else ProductionLiveEvidenceContractAudit.model_validate(
            live_evidence_contract_audit
        )
    )

    lineage_match = _phase1_promotion_lineage_matches(
        request=request,
        reducer=reducer,
        adapter=adapter,
        residency=residency,
        live_audit=live_audit,
    )
    adapter_prepared = (
        adapter.status == "transition_request_prepared"
        and adapter.transition_request_prepared
        and adapter.phase1_adapter_enabled
        and adapter.human_review_approved
    )
    production_gate_residency_ready = (
        residency.status == "all_resident"
        and residency.reducer_candidate_allowed
        and all(row.status == "resident_ready" for row in residency.rows)
    )
    live_evidence_contract_ready = (
        live_audit.status == "all_live_contracts_ready"
        and live_audit.production_weather_environment_ready
        and all(row.status == "live_contract_ready" for row in live_audit.rows)
    )
    runtime_authority_present = bool(runtime_authority_ref and runtime_authority_sha256)
    operator_review_present = bool(operator_review_ref and operator_review_sha256)
    reasons: list[str] = []
    if not lineage_match:
        status: Phase1RuntimePromotionReadinessStatus = "blocked_lineage_mismatch"
        reasons.append("transition request, reducer, adapter, or audit lineage mismatch")
    elif not adapter_prepared:
        status = "blocked_adapter_not_prepared"
        reasons.append("Phase 1 adapter is not enabled and human-reviewed")
    elif not production_gate_residency_ready:
        status = "blocked_production_gate_residency"
        reasons.append("all six primary gates are not production-resident")
    elif not live_evidence_contract_ready:
        status = "blocked_live_evidence_contract"
        reasons.append("weather/environment live evidence contract is not ready")
    elif not runtime_authority_present:
        status = "blocked_runtime_authority_missing"
        reasons.append("reviewed runtime authority ref and hash are required")
    elif not operator_review_present:
        status = "blocked_operator_review_missing"
        reasons.append("operator review ref and hash are required")
    else:
        status = "ready_for_deterministic_writer"
        reasons.append(
            "all local promotion preconditions are present; writer invocation remains separate"
        )
    ready = status == "ready_for_deterministic_writer"
    digest = aggregate_sha256(
        [
            {
                "source_path": source_path,
                "status": status,
                "transition_request_sha256": request.sha256,
                "reducer_sha256": reducer.sha256,
                "adapter_sha256": adapter.sha256,
                "gate_residency_audit_sha256": residency.sha256,
                "live_evidence_contract_audit_sha256": live_audit.sha256,
                "runtime_authority_sha256": runtime_authority_sha256,
                "operator_review_sha256": operator_review_sha256,
            }
        ]
    )
    return Phase1RuntimePromotionReadinessGate(
        source_path=source_path,
        sha256=digest,
        status=status,
        reducer_sha256=reducer.sha256,
        adapter_sha256=adapter.sha256,
        transition_request_sha256=request.sha256,
        production_gate_residency_audit_sha256=residency.sha256,
        live_evidence_contract_audit_sha256=live_audit.sha256,
        runtime_authority_ref=runtime_authority_ref,
        runtime_authority_sha256=runtime_authority_sha256,
        operator_review_ref=operator_review_ref,
        operator_review_sha256=operator_review_sha256,
        lineage_match=lineage_match,
        adapter_prepared=adapter_prepared,
        production_gate_residency_ready=production_gate_residency_ready,
        live_evidence_contract_ready=live_evidence_contract_ready,
        runtime_authority_present=runtime_authority_present,
        operator_review_present=operator_review_present,
        deterministic_writer_preconditions_met=ready,
        reasons=reasons,
    )


def invoke_phase1_runtime_promotion_writer(
    transition_request: Phase1TransitionRequest | dict[str, Any],
    readiness_gate: Phase1RuntimePromotionReadinessGate | dict[str, Any],
    invocation_request: Phase1RuntimeWriterInvocationRequest | dict[str, Any],
    *,
    mutation_service: Phase1SafetyMutationService | None = None,
    source_path: str = "inline:phase1-runtime-writer-invocation-receipt",
) -> Phase1RuntimeWriterInvocationReceipt:
    request = (
        transition_request
        if isinstance(transition_request, Phase1TransitionRequest)
        else Phase1TransitionRequest.model_validate(transition_request)
    )
    readiness = (
        readiness_gate
        if isinstance(readiness_gate, Phase1RuntimePromotionReadinessGate)
        else Phase1RuntimePromotionReadinessGate.model_validate(readiness_gate)
    )
    invocation = (
        invocation_request
        if isinstance(invocation_request, Phase1RuntimeWriterInvocationRequest)
        else Phase1RuntimeWriterInvocationRequest.model_validate(invocation_request)
    )
    request_sha = aggregate_sha256([invocation.model_dump(mode="json")])
    request_mismatch = (
        invocation.readiness_gate_sha256 != readiness.sha256
        or invocation.transition_request_sha256 != request.sha256
        or readiness.transition_request_sha256 != request.sha256
    )
    readiness_accepted = (
        readiness.status == "ready_for_deterministic_writer"
        and readiness.deterministic_writer_preconditions_met
    )
    operator_approval_recorded = (
        invocation.operator_authenticated
        and bool(invocation.operator_identity_ref)
        and invocation.explicit_confirmation
        and invocation.operator_approval_phrase
        == _PHASE1_RUNTIME_WRITER_CONFIRMATION_PHRASE
    )
    mutation_result: Phase1MutationResult | None = None
    reasons: list[str] = []
    if request_mismatch:
        status: Phase1RuntimeWriterInvocationStatus = "blocked_request_mismatch"
        reasons.append("writer invocation request does not match readiness lineage")
    elif not readiness_accepted:
        status = "blocked_readiness_not_ready"
        reasons.append("Phase 1 runtime promotion readiness gate is not ready")
    elif not (
        invocation.operator_authenticated and invocation.operator_identity_ref
    ):
        status = "blocked_requires_authenticated_operator"
        reasons.append("authenticated operator identity is required")
    elif not (
        invocation.explicit_confirmation
        and invocation.operator_approval_phrase
        == _PHASE1_RUNTIME_WRITER_CONFIRMATION_PHRASE
    ):
        status = "blocked_requires_explicit_confirmation"
        reasons.append("exact local writer confirmation phrase is required")
    elif invocation.execution_mode == "dry_run":
        status = "dry_run_ready"
        reasons.append("local deterministic writer invocation is ready but not executed")
    else:
        service = mutation_service or Phase1SafetyMutationService()
        mutation_result = service.apply_transition_request(
            request,
            source_path=f"{source_path}#local_phase1_mutation_result",
        )
        status = "local_writer_invoked"
        reasons.append("local deterministic writer invoked behind readiness gate")

    digest = aggregate_sha256(
        [
            {
                "source_path": source_path,
                "request_sha256": request_sha,
                "readiness_gate_sha256": readiness.sha256,
                "transition_request_sha256": request.sha256,
                "execution_mode": invocation.execution_mode,
                "status": status,
                "mutation_result_sha256": (
                    mutation_result.sha256 if mutation_result is not None else None
                ),
            }
        ]
    )
    return Phase1RuntimeWriterInvocationReceipt(
        source_path=source_path,
        sha256=digest,
        request_sha256=request_sha,
        readiness_gate_sha256=invocation.readiness_gate_sha256,
        transition_request_sha256=invocation.transition_request_sha256,
        execution_mode=invocation.execution_mode,
        status=status,
        readiness_gate_accepted=readiness_accepted,
        operator_approval_recorded=operator_approval_recorded,
        local_phase1_writer_invoked=mutation_result is not None,
        local_phase1_l0_l4_state_mutated=(
            mutation_result.transition_performed if mutation_result is not None else False
        ),
        mutation_result_sha256=(
            mutation_result.sha256 if mutation_result is not None else None
        ),
        mutation_id=mutation_result.mutation_id if mutation_result is not None else None,
        mutation_status=mutation_result.status if mutation_result is not None else None,
        previous_safety_level=(
            mutation_result.previous_safety_level
            if mutation_result is not None
            else None
        ),
        resulting_safety_level=(
            mutation_result.resulting_safety_level
            if mutation_result is not None
            else None
        ),
        reasons=reasons,
    )


def evaluate_phase1_writer_production_deployment_readiness(
    transition_request: Phase1TransitionRequest | dict[str, Any],
    readiness_gate: Phase1RuntimePromotionReadinessGate | dict[str, Any],
    writer_invocation_receipt: Phase1RuntimeWriterInvocationReceipt | dict[str, Any],
    deployment_manifest: Phase1RuntimeWriterDeploymentManifest | dict[str, Any],
    *,
    source_path: str = "inline:phase1-runtime-writer-deployment-readiness",
) -> Phase1RuntimeWriterDeploymentReadinessAudit:
    request = (
        transition_request
        if isinstance(transition_request, Phase1TransitionRequest)
        else Phase1TransitionRequest.model_validate(transition_request)
    )
    readiness = (
        readiness_gate
        if isinstance(readiness_gate, Phase1RuntimePromotionReadinessGate)
        else Phase1RuntimePromotionReadinessGate.model_validate(readiness_gate)
    )
    writer_receipt = (
        writer_invocation_receipt
        if isinstance(
            writer_invocation_receipt,
            Phase1RuntimeWriterInvocationReceipt,
        )
        else Phase1RuntimeWriterInvocationReceipt.model_validate(
            writer_invocation_receipt
        )
    )
    manifest = (
        deployment_manifest
        if isinstance(deployment_manifest, Phase1RuntimeWriterDeploymentManifest)
        else Phase1RuntimeWriterDeploymentManifest.model_validate(deployment_manifest)
    )
    manifest_sha = _phase1_writer_deployment_manifest_sha256(manifest)
    writer_invocation_ready = (
        readiness.status == "ready_for_deterministic_writer"
        and readiness.deterministic_writer_preconditions_met
        and writer_receipt.status == "local_writer_invoked"
        and writer_receipt.readiness_gate_accepted
        and writer_receipt.operator_approval_recorded
        and writer_receipt.local_phase1_writer_invoked
        and writer_receipt.local_phase1_l0_l4_state_mutated
        and not writer_receipt.production_runtime_write_performed
        and not writer_receipt.production_runtime_safety_truth_mutated
    )
    deployment_lineage_match = _phase1_writer_deployment_lineage_matches(
        request=request,
        readiness=readiness,
        writer_receipt=writer_receipt,
        manifest=manifest,
    )
    runtime_boundary_present = bool(
        manifest.runtime_environment_ref
        and manifest.runtime_deployment_ref
        and manifest.runtime_authority_ref
        and manifest.runtime_authority_sha256
        and manifest.writer_effect_boundary_ref
        and manifest.writer_effect_boundary_sha256
    )
    rollback_plan_present = bool(
        manifest.rollback_plan_ref and manifest.rollback_plan_sha256
    )
    operator_review_present = bool(
        manifest.operator_review_ref and manifest.operator_review_sha256
    )
    reasons: list[str] = []
    if not writer_invocation_ready:
        status: Phase1RuntimeWriterDeploymentReadinessStatus = (
            "blocked_writer_invocation_not_ready"
        )
        reasons.append("local guarded writer invocation proof is required")
    elif not deployment_lineage_match:
        status = "blocked_deployment_lineage_mismatch"
        reasons.append(
            "deployment manifest does not match transition, readiness, or writer receipt lineage"
        )
    elif not runtime_boundary_present:
        status = "blocked_runtime_boundary_missing"
        reasons.append(
            "runtime environment, deployment, authority, and writer effect boundary refs are required"
        )
    elif not rollback_plan_present:
        status = "blocked_rollback_plan_missing"
        reasons.append("rollback plan ref and hash are required")
    elif not operator_review_present:
        status = "blocked_operator_review_missing"
        reasons.append("operator deployment review ref and hash are required")
    else:
        status = "ready_for_reviewed_production_deployment"
        reasons.append(
            "production writer deployment readiness recorded; deployment remains a separate effect boundary"
        )
    ready = status == "ready_for_reviewed_production_deployment"
    digest = aggregate_sha256(
        [
            {
                "source_path": source_path,
                "status": status,
                "transition_request_sha256": request.sha256,
                "readiness_gate_sha256": readiness.sha256,
                "writer_invocation_receipt_sha256": writer_receipt.sha256,
                "deployment_manifest_sha256": manifest_sha,
            }
        ]
    )
    return Phase1RuntimeWriterDeploymentReadinessAudit(
        source_path=source_path,
        sha256=digest,
        status=status,
        readiness_gate_sha256=readiness.sha256,
        writer_invocation_receipt_sha256=writer_receipt.sha256,
        transition_request_sha256=request.sha256,
        deployment_manifest_sha256=manifest_sha,
        writer_invocation_ready=writer_invocation_ready,
        deployment_lineage_match=deployment_lineage_match,
        runtime_boundary_present=runtime_boundary_present,
        rollback_plan_present=rollback_plan_present,
        operator_review_present=operator_review_present,
        ready_for_reviewed_production_deployment=ready,
        runtime_environment_ref=manifest.runtime_environment_ref,
        runtime_deployment_ref=manifest.runtime_deployment_ref,
        runtime_authority_ref=manifest.runtime_authority_ref,
        runtime_authority_sha256=manifest.runtime_authority_sha256,
        writer_effect_boundary_ref=manifest.writer_effect_boundary_ref,
        writer_effect_boundary_sha256=manifest.writer_effect_boundary_sha256,
        rollback_plan_ref=manifest.rollback_plan_ref,
        rollback_plan_sha256=manifest.rollback_plan_sha256,
        operator_review_ref=manifest.operator_review_ref,
        operator_review_sha256=manifest.operator_review_sha256,
        reasons=reasons,
    )


def safety_event_from_phase1_transition_request(
    request: Phase1TransitionRequest | dict[str, Any],
) -> SafetyEvent:
    request_model = (
        request
        if isinstance(request, Phase1TransitionRequest)
        else Phase1TransitionRequest.model_validate(request)
    )
    details = {
        "phase1_transition_request_id": request_model.request_id,
        "phase1_transition_request_sha256": request_model.sha256,
        "reducer_sha256": request_model.reducer_sha256,
        "adapter_sha256": request_model.adapter_sha256,
        "selected_gate_id": request_model.selected_gate_id,
        "contributing_gate_ids": request_model.contributing_gate_ids,
        "corroborating_gate_ids": request_model.corroborating_gate_ids,
        "suppressed_gate_ids": request_model.suppressed_gate_ids,
        "route_id": request_model.route_id,
        "segment_id": request_model.segment_id,
        "checkpoint_id": request_model.checkpoint_id,
        "map_target_ids": request_model.map_target_ids,
        "eta_delay_minutes": request_model.eta_delay_minutes,
        "route_pressure_review_required": request_model.route_pressure_review_required,
        "source_refs": request_model.source_refs,
        "privacy": request_model.privacy.model_dump(mode="json"),
        "boundary": {
            "safety_api_called": False,
            "outbound_alert_sent": False,
            "medical_diagnosis": False,
            "raw_health_payload_shared": False,
            "precise_timestamps_shared": False,
        },
    }
    return SafetyEvent(
        event_type=request_model.target_event_type,
        level=request_model.target_safety_level,
        timestamp=request_model.event_time_offset_s,
        reason=request_model.reason,
        confidence=request_model.confidence,
        details=details,
    )


def write_phase1_transition_request(
    request: Phase1TransitionRequest,
    output_path: Path | str,
) -> Phase1TransitionRequest:
    path = Path(output_path).expanduser()
    _atomic_write_json(path, request.model_dump(mode="json"))
    return load_phase1_transition_request(path)


def load_phase1_transition_request(path: Path | str) -> Phase1TransitionRequest:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    payload["source_path"] = payload.get("source_path") or str(expanded)
    payload["sha256"] = payload.get("sha256") or sha256_file(expanded)
    return Phase1TransitionRequest.model_validate(payload)


def write_phase1_runtime_promotion_readiness_gate(
    gate: Phase1RuntimePromotionReadinessGate,
    output_path: Path | str,
) -> Phase1RuntimePromotionReadinessGate:
    path = Path(output_path).expanduser()
    _atomic_write_json(path, gate.model_dump(mode="json"))
    return load_phase1_runtime_promotion_readiness_gate(path)


def load_phase1_runtime_promotion_readiness_gate(
    path: Path | str,
) -> Phase1RuntimePromotionReadinessGate:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    payload["source_path"] = payload.get("source_path") or str(expanded)
    payload["sha256"] = payload.get("sha256") or sha256_file(expanded)
    return Phase1RuntimePromotionReadinessGate.model_validate(payload)


def write_phase1_runtime_writer_invocation_receipt(
    receipt: Phase1RuntimeWriterInvocationReceipt,
    output_path: Path | str,
) -> Phase1RuntimeWriterInvocationReceipt:
    path = Path(output_path).expanduser()
    _atomic_write_json(path, receipt.model_dump(mode="json"))
    return load_phase1_runtime_writer_invocation_receipt(path)


def load_phase1_runtime_writer_invocation_receipt(
    path: Path | str,
) -> Phase1RuntimeWriterInvocationReceipt:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    payload["source_path"] = payload.get("source_path") or str(expanded)
    payload["sha256"] = payload.get("sha256") or sha256_file(expanded)
    return Phase1RuntimeWriterInvocationReceipt.model_validate(payload)


def write_phase1_runtime_writer_deployment_readiness_audit(
    audit: Phase1RuntimeWriterDeploymentReadinessAudit,
    output_path: Path | str,
) -> Phase1RuntimeWriterDeploymentReadinessAudit:
    path = Path(output_path).expanduser()
    _atomic_write_json(path, audit.model_dump(mode="json"))
    return load_phase1_runtime_writer_deployment_readiness_audit(path)


def load_phase1_runtime_writer_deployment_readiness_audit(
    path: Path | str,
) -> Phase1RuntimeWriterDeploymentReadinessAudit:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    payload["source_path"] = payload.get("source_path") or str(expanded)
    payload["sha256"] = payload.get("sha256") or sha256_file(expanded)
    return Phase1RuntimeWriterDeploymentReadinessAudit.model_validate(payload)


def write_phase1_mutation_result(
    result: Phase1MutationResult,
    output_path: Path | str,
) -> Phase1MutationResult:
    path = Path(output_path).expanduser()
    _atomic_write_json(path, result.model_dump(mode="json"))
    return load_phase1_mutation_result(path)


def load_phase1_mutation_result(path: Path | str) -> Phase1MutationResult:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    payload["source_path"] = payload.get("source_path") or str(expanded)
    payload["sha256"] = payload.get("sha256") or sha256_file(expanded)
    return Phase1MutationResult.model_validate(payload)


def build_phase1_mutation_audit_index(
    results: list[Phase1MutationResult | dict[str, Any]],
    *,
    source_path: str = "inline:phase1-mutation-audit-index",
) -> Phase1MutationAuditIndex:
    result_models = [
        result
        if isinstance(result, Phase1MutationResult)
        else Phase1MutationResult.model_validate(result)
        for result in results
    ]
    summaries = [_audit_summary(result) for result in result_models]
    latest = summaries[-1] if summaries else None
    digest = aggregate_sha256(
        [
            {
                "source_path": source_path,
                "mutation_ids": [summary.mutation_id for summary in summaries],
                "mutation_hashes": [summary.sha256 for summary in summaries],
            }
        ]
    )
    return Phase1MutationAuditIndex(
        source_path=source_path,
        sha256=digest,
        mutation_count=len(summaries),
        latest_mutation_id=latest.mutation_id if latest else None,
        latest_safety_level=latest.resulting_safety_level if latest else None,
        mutations=summaries,
        boundary=Phase1MutationBoundary() if summaries else None,
    )


def write_phase1_mutation_audit_index(
    index: Phase1MutationAuditIndex,
    output_path: Path | str,
) -> Phase1MutationAuditIndex:
    path = Path(output_path).expanduser()
    _atomic_write_json(path, index.model_dump(mode="json"))
    return load_phase1_mutation_audit_index(path)


def load_phase1_mutation_audit_index(path: Path | str) -> Phase1MutationAuditIndex:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    payload["source_path"] = payload.get("source_path") or str(expanded)
    payload["sha256"] = payload.get("sha256") or sha256_file(expanded)
    return Phase1MutationAuditIndex.model_validate(payload)


def build_phase1_mutation_projection(
    project_id: str,
    *,
    project_root: Path | str,
    mutation_result_ref: str | None = None,
    mutation_audit_index_ref: str | None = None,
    shadow_replay_result_ref: str | None = None,
) -> Phase1MutationProjection:
    root = Path(project_root).expanduser()
    try:
        loaded = _load_projection_source(
            root,
            mutation_result_ref=mutation_result_ref,
            mutation_audit_index_ref=mutation_audit_index_ref,
            shadow_replay_result_ref=shadow_replay_result_ref,
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return Phase1MutationProjection(
            status="error",
            project_id=project_id,
            source_path=str(
                mutation_result_ref
                or mutation_audit_index_ref
                or shadow_replay_result_ref
                or ""
            ),
            error_type=type(exc).__name__,
            error=str(exc),
        )
    if loaded is None:
        return Phase1MutationProjection(
            status="missing",
            project_id=project_id,
            source_path=str(
                mutation_result_ref
                or mutation_audit_index_ref
                or shadow_replay_result_ref
                or ""
            ),
        )
    source_path, result, index = loaded
    event = phase1_mutation_projection_event(result, sequence=0)
    digest = aggregate_sha256(
        [
            {
                "project_id": project_id,
                "source_path": source_path,
                "mutation_sha256": result.sha256,
                "index_sha256": index.sha256 if index else None,
            }
        ]
    )
    return Phase1MutationProjection(
        status="ready",
        project_id=project_id,
        source_path=source_path,
        sha256=digest,
        latest_mutation_id=result.mutation_id,
        latest_safety_level=result.resulting_safety_level,
        mutation_count=index.mutation_count if index else 1,
        timeline_events=[event],
        boundary=result.boundary,
    )


def phase1_mutation_projection_event(
    result: Phase1MutationResult,
    *,
    sequence: int,
) -> dict[str, Any]:
    severity = {
        SafetyLevel.NORMAL: "info",
        SafetyLevel.WATCH: "watch",
        SafetyLevel.CONCERN: "warning",
        SafetyLevel.DISTRESS: "critical",
        SafetyLevel.EMERGENCY: "critical",
    }[result.resulting_safety_level]
    return {
        "event_id": f"phase1_mutation.{result.mutation_id}",
        "sequence": sequence,
        "timestamp": "offset:phase1-safety-mutation",
        "kind": "phase1_safety_mutation_result",
        "label": result.resulting_safety_level.value,
        "severity": severity,
        "summary": result.safety_event.reason,
        "source_refs": [result.source_path],
        "map_refs": result.safety_event.details.get("map_target_ids", []),
        "payload": {
            "mutation_id": result.mutation_id,
            "request_id": result.request_id,
            "status": result.status,
            "previous_safety_level": result.previous_safety_level.value,
            "resulting_safety_level": result.resulting_safety_level.value,
            "transition_performed": result.transition_performed,
            "event_type": result.safety_event.event_type.value,
            "selected_gate_id": result.safety_event.details.get("selected_gate_id"),
            "boundary": result.boundary.model_dump(mode="json"),
            "privacy": result.privacy.model_dump(mode="json"),
        },
    }


def _audit_summary(result: Phase1MutationResult) -> Phase1MutationAuditSummary:
    return Phase1MutationAuditSummary(
        mutation_id=result.mutation_id,
        mutation_path=result.source_path,
        sha256=result.sha256,
        request_id=result.request_id,
        request_sha256=result.request_sha256,
        status=result.status,
        previous_safety_level=result.previous_safety_level,
        resulting_safety_level=result.resulting_safety_level,
        transition_performed=result.transition_performed,
        event_type=result.safety_event.event_type,
    )


def _request_id(
    reducer: RuntimeSafetyReducerDecision,
    adapter: RuntimeSafetyPhase1AdapterResult,
    snapshot: RuntimeSafetyStateSnapshot | None,
) -> str:
    digest = aggregate_sha256(
        [
            {
                "reducer_sha256": reducer.sha256,
                "adapter_sha256": adapter.sha256,
                "snapshot_sha256": snapshot.sha256 if snapshot else None,
            }
        ]
    )
    return f"phase1_transition_request.{digest[:16]}"


def _mutation_id(
    request: Phase1TransitionRequest,
    previous_level: SafetyLevel,
    resulting_level: SafetyLevel,
) -> str:
    digest = aggregate_sha256(
        [
            {
                "request_sha256": request.sha256,
                "previous_level": previous_level.value,
                "resulting_level": resulting_level.value,
            }
        ]
    )
    return f"phase1_safety_mutation.{digest[:16]}"


def _mutation_reason(reducer: RuntimeSafetyReducerDecision) -> str:
    selected_gate = reducer.selected_gate_id or "runtime_safety_reducer"
    reasons = [
        summary.get("state_candidate")
        for summary in reducer.gate_summaries
        if summary.get("sha256") == reducer.selected_event_sha256
    ]
    reason = str(reasons[0]) if reasons else reducer.recommendation
    return (
        f"{selected_gate} requested {reducer.ln_level_candidate} via "
        f"{reducer.recommendation}: {reason}"
    )


def _first_summary_value(
    reducer: RuntimeSafetyReducerDecision,
    key: str,
) -> str | None:
    selected = [
        summary
        for summary in reducer.gate_summaries
        if summary.get("sha256") == reducer.selected_event_sha256
    ]
    candidates = selected or reducer.gate_summaries
    for summary in candidates:
        value = summary.get(key)
        if value:
            return str(value)
    return None


def _load_projection_source(
    root: Path,
    *,
    mutation_result_ref: str | None,
    mutation_audit_index_ref: str | None,
    shadow_replay_result_ref: str | None,
) -> tuple[str, Phase1MutationResult, Phase1MutationAuditIndex | None] | None:
    if mutation_result_ref:
        path = root / mutation_result_ref
        return mutation_result_ref, load_phase1_mutation_result(path), None
    if mutation_audit_index_ref:
        index_path = root / mutation_audit_index_ref
        index = load_phase1_mutation_audit_index(index_path)
        if not index.mutations:
            return None
        latest = index.mutations[-1]
        result_path = index_path.parent / latest.mutation_path
        if not result_path.exists():
            result_path = index_path.parent / "mutations" / f"{latest.mutation_id}.json"
        return (
            mutation_audit_index_ref,
            load_phase1_mutation_result(result_path),
            index,
        )
    if shadow_replay_result_ref:
        shadow_path = root / shadow_replay_result_ref
        payload = json.loads(shadow_path.read_text(encoding="utf-8"))
        result_payload = payload.get("phase1_mutation_result")
        if not result_payload:
            return None
        index_payload = payload.get("phase1_mutation_audit_index")
        index = (
            Phase1MutationAuditIndex.model_validate(index_payload)
            if index_payload
            else None
        )
        return (
            f"{shadow_replay_result_ref}#phase1_mutation_result",
            Phase1MutationResult.model_validate(result_payload),
            index,
        )
    return None


def _phase1_promotion_lineage_matches(
    *,
    request: Phase1TransitionRequest,
    reducer: RuntimeSafetyReducerDecision,
    adapter: RuntimeSafetyPhase1AdapterResult,
    residency: ProductionGateResidencyAudit,
    live_audit: ProductionLiveEvidenceContractAudit,
) -> bool:
    if request.reducer_sha256 != reducer.sha256:
        return False
    if request.adapter_sha256 != adapter.sha256:
        return False
    if adapter.selected_reducer_sha256 != reducer.sha256:
        return False
    if request.selected_gate_id != reducer.selected_gate_id:
        return False
    if request.selected_event_sha256 != reducer.selected_event_sha256:
        return False
    if request.requested_ln_level_candidate != reducer.ln_level_candidate:
        return False
    if request.requested_ln_transition_candidate != reducer.ln_transition_candidate:
        return False

    residency_by_gate = {row.gate_id: row for row in residency.rows}
    for gate_id in reducer.contributing_gate_ids:
        row = residency_by_gate.get(gate_id)
        if row is None or row.status != "resident_ready":
            return False
    if reducer.selected_gate_id:
        selected_row = residency_by_gate.get(reducer.selected_gate_id)
        if selected_row is None:
            return False
        if selected_row.event_sha256 != reducer.selected_event_sha256:
            return False

    for live_row in live_audit.rows:
        residency_row = residency_by_gate.get(live_row.gate_id)
        if residency_row is None:
            return False
        if live_row.event_sha256 != residency_row.event_sha256:
            return False
    return True


def _phase1_writer_deployment_manifest_sha256(
    manifest: Phase1RuntimeWriterDeploymentManifest,
) -> str:
    return aggregate_sha256(
        [
            {
                "artifact": manifest.artifact_kind,
                "payload": manifest.model_dump(mode="json"),
                "production_runtime_write_performed": False,
            }
        ]
    )


def _phase1_writer_deployment_lineage_matches(
    *,
    request: Phase1TransitionRequest,
    readiness: Phase1RuntimePromotionReadinessGate,
    writer_receipt: Phase1RuntimeWriterInvocationReceipt,
    manifest: Phase1RuntimeWriterDeploymentManifest,
) -> bool:
    core_matches = (
        readiness.transition_request_sha256 == request.sha256
        and writer_receipt.readiness_gate_sha256 == readiness.sha256
        and writer_receipt.transition_request_sha256 == request.sha256
        and manifest.readiness_gate_sha256 == readiness.sha256
        and manifest.writer_invocation_receipt_sha256 == writer_receipt.sha256
        and manifest.transition_request_sha256 == request.sha256
    )
    if not core_matches:
        return False
    if manifest.runtime_authority_ref and manifest.runtime_authority_sha256:
        if (
            manifest.runtime_authority_ref != readiness.runtime_authority_ref
            or manifest.runtime_authority_sha256 != readiness.runtime_authority_sha256
        ):
            return False
    if manifest.operator_review_ref and manifest.operator_review_sha256:
        if (
            manifest.operator_review_ref != readiness.operator_review_ref
            or manifest.operator_review_sha256 != readiness.operator_review_sha256
        ):
            return False
    return True


def _raise_if_private_payload_shared(value: Any) -> None:
    if (
        getattr(value, "raw_health_payload_shared", False)
        or getattr(value, "raw_track_shared", False)
        or getattr(value, "raw_gpx_shared", False)
        or getattr(value, "precise_timestamps_shared", False)
        or getattr(value, "home_work_trace_shared", False)
    ):
        raise ValueError("Phase 1 mutation artifacts cannot share raw private payloads")


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(path)


def _relative_or_string(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _forbidden_key_paths(value: Any, prefix: str = "") -> list[str]:
    if isinstance(value, dict):
        paths: list[str] = []
        for key, child in value.items():
            child_path = f"{prefix}.{key}" if prefix else str(key)
            lower_key = str(key).lower()
            if (
                lower_key in FORBIDDEN_RAW_KEYS
                and lower_key not in _PHASE1_STATE_MACHINE_ALLOWED_KEYS
            ):
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
