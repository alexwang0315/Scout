from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from safety_models import SafetyEventType, SafetyLevel
from scout_energy_models import aggregate_sha256
from scout_runtime_phase1_mutation import (
    Phase1MutationResult,
    load_phase1_mutation_result,
)
from scout_wearable_validator import FORBIDDEN_RAW_KEYS


AlertTransportProfile = Literal["sms_text", "lora_compact", "mqtt_json"]
OutboundPolicyStatus = Literal[
    "blocked_dry_run",
    "requires_human_approval",
    "allowed_manual_copy",
]
EmergencyCallOutExecutorKind = Literal[
    "local_dry_run",
    "manual_handoff",
    "production_transport",
]
EmergencyCallOutAdmissionStatus = Literal[
    "blocked_packet_mismatch",
    "blocked_policy_not_allowed",
    "blocked_requires_explicit_confirmation",
    "blocked_requires_authenticated_approval",
    "blocked_production_executor_unavailable",
    "admitted_local_dry_run",
    "admitted_manual_handoff",
]
EmergencyCallOutReceiptOutcome = Literal[
    "dry_run_recorded",
    "manual_handoff_recorded",
]
ProductionEmergencyApprovalStatus = Literal[
    "blocked_packet_mismatch",
    "blocked_call_out_not_admitted",
    "blocked_requires_authenticated_operator",
    "blocked_requires_approval_phrase",
    "authenticated_approval_recorded_pending_transport",
]
ApprovedTransportExecutorSelectionStatus = Literal[
    "blocked_packet_mismatch",
    "blocked_no_matching_executor",
    "blocked_executor_not_approved",
    "blocked_production_approval_incomplete",
    "ready_for_verified_transport_executor",
]
ProductionTransportReleaseStatus = Literal[
    "blocked_packet_mismatch",
    "blocked_approval_preflight_not_recorded",
    "blocked_missing_residency_audit",
    "blocked_gate_residency_not_ready",
    "blocked_runtime_boundary_not_reviewed",
    "blocked_requires_final_confirmation",
    "released_for_approved_executor_selection",
]
ProductionDeliveryStatus = Literal[
    "delivered",
    "accepted_by_gateway",
    "failed",
    "unknown",
]
ProductionDeliveryVerificationStatus = Literal[
    "blocked_transport_selection_not_ready",
    "blocked_delivery_lineage_mismatch",
    "blocked_missing_delivery_proof",
    "blocked_delivery_not_verified",
    "verified_delivery_evidence_accepted",
]
ProductionEmergencyWorkflowCompletionStatus = Literal[
    "blocked_transport_release_missing",
    "blocked_transport_executor_not_ready",
    "blocked_verified_delivery_missing",
    "workflow_completed_verified_delivery",
]
ProductionTransportInvocationMode = Literal[
    "dry_run",
    "production_effect_boundary_request",
]
ProductionTransportInvocationStatus = Literal[
    "blocked_invocation_lineage_mismatch",
    "blocked_transport_selection_not_ready",
    "blocked_requires_authenticated_operator",
    "blocked_requires_explicit_confirmation",
    "blocked_transport_effect_boundary_missing",
    "dry_run_ready",
    "transport_invocation_authorized",
]
ProductionTransportExecutorEffectBoundaryReadinessStatus = Literal[
    "blocked_transport_invocation_not_authorized",
    "blocked_effect_boundary_lineage_mismatch",
    "blocked_executor_boundary_missing",
    "blocked_delivery_verifier_missing",
    "blocked_fallback_plan_missing",
    "ready_for_reviewed_transport_effect_boundary",
]
ProductionTransportExecutorExecutionStatus = Literal[
    "blocked_transport_executor_not_ready",
    "blocked_transport_invocation_not_authorized",
    "blocked_transport_execution_lineage_mismatch",
    "blocked_transport_client_result_invalid",
    "blocked_transport_client_effect_missing",
    "transport_effect_receipt_emitted",
]
ProductionTransportEffectReceiptIntakeStatus = Literal[
    "blocked_transport_invocation_not_authorized",
    "blocked_effect_receipt_lineage_mismatch",
    "blocked_missing_delivery_evidence",
    "blocked_effect_receipt_not_delivered",
    "delivery_report_prepared",
]

ALERT_APPROVAL_PHRASE = "SEND SCOUT ALERT"
TRANSPORT_INVOCATION_APPROVAL_PHRASE = "INVOKE SCOUT TRANSPORT"
DEFAULT_EMERGENCY_CONTACTS = ["119", "112"]


class AlertApplicationDataQuality(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confidence: Literal["low", "medium", "high"] = "medium"
    source_artifact_count: int = Field(default=1, ge=0)
    rendered_profile_count: int = Field(default=0, ge=0)
    truncated_profile_count: int = Field(default=0, ge=0)
    live_network_calls_made: bool = False
    hardware_transport_invoked: bool = False
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_local_only_quality(self) -> "AlertApplicationDataQuality":
        if self.live_network_calls_made:
            raise ValueError("alert application layer dry-run cannot make network calls")
        if self.hardware_transport_invoked:
            raise ValueError("alert application layer dry-run cannot invoke hardware transport")
        return self


class AlertApplicationPrivacy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_only: bool = True
    aggregate_only: bool = True
    raw_health_payload_shared: bool = False
    raw_track_shared: bool = False
    raw_gpx_shared: bool = False
    precise_coordinates_shared: bool = False
    precise_timestamps_shared: bool = False
    home_work_trace_shared: bool = False
    shareable_by_default: bool = False

    @model_validator(mode="after")
    def enforce_privacy(self) -> "AlertApplicationPrivacy":
        if (
            self.raw_health_payload_shared
            or self.raw_track_shared
            or self.raw_gpx_shared
            or self.precise_coordinates_shared
            or self.precise_timestamps_shared
            or self.home_work_trace_shared
            or self.shareable_by_default
        ):
            raise ValueError("alert application artifacts cannot share raw private payloads")
        return self


class AlertApplicationBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    application_layer_only: bool = True
    transport_neutral: bool = True
    dry_run_only: bool = True
    phase1_runtime_safety_truth_source: bool = True
    phase1_runtime_safety_truth_mutated: bool = False
    outbound_policy_separate: bool = True
    outbound_send_performed: bool = False
    hardware_transport_invoked: bool = False
    safety_api_called: bool = False
    medical_diagnosis: bool = False
    operator_approval_required: bool = True
    raw_health_payload_shared: bool = False
    raw_track_shared: bool = False
    raw_gpx_shared: bool = False
    precise_coordinates_shared: bool = False
    precise_timestamps_shared: bool = False
    home_work_trace_shared: bool = False

    @model_validator(mode="after")
    def enforce_boundary(self) -> "AlertApplicationBoundary":
        if not self.application_layer_only or not self.transport_neutral:
            raise ValueError("alert application artifacts must stay transport-neutral")
        if not self.dry_run_only:
            raise ValueError("alert application artifacts are dry-run only in this slice")
        if self.phase1_runtime_safety_truth_mutated:
            raise ValueError("alert application layer cannot mutate Phase 1 safety truth")
        if not self.outbound_policy_separate:
            raise ValueError("outbound policy must stay separate from alert rendering")
        if self.outbound_send_performed:
            raise ValueError("alert application layer cannot send outbound alerts")
        if self.hardware_transport_invoked:
            raise ValueError("alert application layer cannot invoke hardware transport")
        if self.safety_api_called:
            raise ValueError("alert application layer cannot call safety APIs")
        if self.medical_diagnosis:
            raise ValueError("alert application layer cannot be a medical diagnosis")
        if (
            self.raw_health_payload_shared
            or self.raw_track_shared
            or self.raw_gpx_shared
            or self.precise_coordinates_shared
            or self.precise_timestamps_shared
            or self.home_work_trace_shared
        ):
            raise ValueError("alert application artifacts cannot share raw private payloads")
        return self


class ProductionEmergencyWorkflowBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deterministic_verification_only: bool = True
    production_transport_executor_invoked_by_verifier: bool = False
    network_connection_attempted_by_verifier: bool = False
    external_send_performed_by_verifier: bool = False
    hardware_transport_invoked_by_verifier: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    runtime_safety_truth_mutated: bool = False
    credential_material_embedded: bool = False
    raw_transport_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_workflow_boundary(self) -> "ProductionEmergencyWorkflowBoundary":
        if not self.deterministic_verification_only:
            raise ValueError("production emergency workflow artifacts are verification-only")
        if (
            self.production_transport_executor_invoked_by_verifier
            or self.network_connection_attempted_by_verifier
            or self.external_send_performed_by_verifier
            or self.hardware_transport_invoked_by_verifier
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
            or self.runtime_safety_truth_mutated
            or self.credential_material_embedded
            or self.raw_transport_payload_embedded
        ):
            raise ValueError("production emergency workflow verifier cannot perform effects")
        return self


class EmergencyPacket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_emergency_packet"
    artifact_version: str = "emergency_packet.v1"
    route_id: str | None = None
    route_name: str | None = None
    segment_id: str | None = None
    checkpoint_id: str | None = None
    map_target_ids: list[str] = Field(default_factory=list)
    location_ref: str = Field(min_length=1)
    party_count: int = Field(default=1, ge=1)
    condition_summary: str = Field(min_length=1)
    injuries_or_status: str = "unknown"
    gear_shelter: str = "unknown"
    battery_status: str = "unknown"
    signal_status: str = "unknown"
    communication_method: str = "unknown"
    requested_action: str = Field(min_length=1)
    emergency_contacts: list[str] = Field(default_factory=lambda: list(DEFAULT_EMERGENCY_CONTACTS))
    source_refs: list[str] = Field(default_factory=list)
    data_quality: AlertApplicationDataQuality = Field(default_factory=AlertApplicationDataQuality)
    privacy: AlertApplicationPrivacy = Field(default_factory=AlertApplicationPrivacy)
    boundary: AlertApplicationBoundary = Field(default_factory=AlertApplicationBoundary)

    @model_validator(mode="after")
    def enforce_packet(self) -> "EmergencyPacket":
        if not self.map_target_ids:
            self.map_target_ids = _unique([self.segment_id, self.checkpoint_id])
        _raise_forbidden_fields(self.model_dump(mode="json"))
        return self


class ScoutAlertPacket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_alert_application_packet"
    artifact_version: str = "alert_application_packet.v1"
    packet_id: str = Field(min_length=1)
    source_provider: str = "scout_alert_application_layer"
    source_path: str = Field(min_length=1)
    sha256: str = Field(min_length=1)
    phase1_mutation_id: str = Field(min_length=1)
    phase1_mutation_sha256: str = Field(min_length=1)
    phase1_mutation_source_path: str = Field(min_length=1)
    safety_level: SafetyLevel
    event_type: SafetyEventType
    selected_gate_id: str | None = None
    summary: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    severity_label: Literal["info", "watch", "warning", "critical"]
    emergency_packet: EmergencyPacket
    source_refs: list[str] = Field(default_factory=list)
    data_quality: AlertApplicationDataQuality = Field(default_factory=AlertApplicationDataQuality)
    privacy: AlertApplicationPrivacy = Field(default_factory=AlertApplicationPrivacy)
    boundary: AlertApplicationBoundary = Field(default_factory=AlertApplicationBoundary)

    @model_validator(mode="after")
    def enforce_alert_packet(self) -> "ScoutAlertPacket":
        if self.phase1_mutation_source_path not in self.source_refs:
            self.source_refs.append(self.phase1_mutation_source_path)
        if self.emergency_packet.privacy != self.privacy:
            raise ValueError("nested emergency packet privacy must match alert packet privacy")
        if self.emergency_packet.boundary != self.boundary:
            raise ValueError("nested emergency packet boundary must match alert packet boundary")
        _raise_forbidden_fields(self.model_dump(mode="json"))
        return self


class RenderedAlertMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_alert_rendered_message"
    artifact_version: str = "alert_rendered_message.v1"
    transport_profile: AlertTransportProfile
    source_provider: str = "scout_alert_application_layer"
    source_path: str = Field(min_length=1)
    sha256: str = Field(min_length=1)
    source_packet_id: str = Field(min_length=1)
    source_packet_sha256: str = Field(min_length=1)
    body_text: str | None = None
    payload_json: dict[str, Any] | None = None
    payload_hex: str | None = None
    payload_base64: str | None = None
    mqtt_topic: str | None = None
    mqtt_qos: int | None = Field(default=None, ge=0, le=2)
    mqtt_retain: bool | None = None
    max_chars: int | None = Field(default=None, ge=1)
    max_bytes: int | None = Field(default=None, ge=1)
    char_count: int = Field(default=0, ge=0)
    byte_count: int = Field(default=0, ge=0)
    truncated: bool = False
    sent: bool = False
    data_quality: AlertApplicationDataQuality = Field(default_factory=AlertApplicationDataQuality)
    privacy: AlertApplicationPrivacy = Field(default_factory=AlertApplicationPrivacy)
    boundary: AlertApplicationBoundary = Field(default_factory=AlertApplicationBoundary)

    @model_validator(mode="after")
    def enforce_rendered_message(self) -> "RenderedAlertMessage":
        if self.sent:
            raise ValueError("rendered alert message cannot mark outbound send as performed")
        if self.transport_profile == "sms_text" and not self.body_text:
            raise ValueError("sms_text rendering requires body_text")
        if self.transport_profile in {"lora_compact", "mqtt_json"} and not self.payload_json:
            raise ValueError("packet renderings require payload_json")
        if self.transport_profile == "lora_compact" and (
            not self.payload_hex or not self.payload_base64
        ):
            raise ValueError("lora_compact rendering requires encoded payloads")
        if self.transport_profile == "mqtt_json" and not self.mqtt_topic:
            raise ValueError("mqtt_json rendering requires mqtt_topic")
        _raise_forbidden_fields(
            {
                "payload_json": self.payload_json,
                "body_text": self.body_text,
                "mqtt_topic": self.mqtt_topic,
            }
        )
        return self


class OutboundPolicyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_outbound_policy_decision"
    artifact_version: str = "outbound_policy_decision.v1"
    source_provider: str = "scout_alert_application_layer"
    source_path: str = Field(min_length=1)
    sha256: str = Field(min_length=1)
    source_packet_id: str = Field(min_length=1)
    source_packet_sha256: str = Field(min_length=1)
    status: OutboundPolicyStatus
    phase1_safety_level: SafetyLevel
    external_send_allowed: bool = False
    manual_copy_allowed: bool = False
    operator_approval_present: bool = False
    required_approval_phrase: str = ALERT_APPROVAL_PHRASE
    reasons: list[str] = Field(default_factory=list)
    rendered_profile_ids: list[str] = Field(default_factory=list)
    data_quality: AlertApplicationDataQuality = Field(default_factory=AlertApplicationDataQuality)
    privacy: AlertApplicationPrivacy = Field(default_factory=AlertApplicationPrivacy)
    boundary: AlertApplicationBoundary = Field(default_factory=AlertApplicationBoundary)

    @model_validator(mode="after")
    def enforce_policy(self) -> "OutboundPolicyDecision":
        if self.external_send_allowed:
            raise ValueError("this slice cannot allow external send")
        if self.status == "allowed_manual_copy" and not self.manual_copy_allowed:
            raise ValueError("allowed_manual_copy requires manual_copy_allowed")
        if self.status != "allowed_manual_copy" and self.manual_copy_allowed:
            raise ValueError("manual copy is allowed only after explicit approval phrase")
        _raise_forbidden_fields(self.model_dump(mode="json"))
        return self


class OutboundMessageEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_outbound_message_evidence"
    artifact_version: str = "outbound_message_evidence.v1"
    evidence_id: str = Field(min_length=1)
    source_provider: str = "scout_alert_application_layer"
    source_path: str = Field(min_length=1)
    sha256: str = Field(min_length=1)
    packet_id: str = Field(min_length=1)
    packet_sha256: str = Field(min_length=1)
    rendered_message_sha256s: list[str] = Field(default_factory=list)
    policy_decision_sha256: str = Field(min_length=1)
    output_refs: list[str] = Field(default_factory=list)
    sent: bool = False
    data_quality: AlertApplicationDataQuality = Field(default_factory=AlertApplicationDataQuality)
    privacy: AlertApplicationPrivacy = Field(default_factory=AlertApplicationPrivacy)
    boundary: AlertApplicationBoundary = Field(default_factory=AlertApplicationBoundary)

    @model_validator(mode="after")
    def enforce_evidence(self) -> "OutboundMessageEvidence":
        if self.sent:
            raise ValueError("outbound evidence cannot mark a send as performed")
        _raise_forbidden_fields(self.model_dump(mode="json"))
        return self


class AlertApplicationDryRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_alert_application_dry_run_result"
    artifact_version: str = "alert_application_dry_run_result.v1"
    source_provider: str = "scout_alert_application_layer"
    source_path: str = Field(min_length=1)
    sha256: str = Field(min_length=1)
    output_dir: str = Field(min_length=1)
    packet: ScoutAlertPacket
    rendered_messages: list[RenderedAlertMessage]
    policy_decision: OutboundPolicyDecision
    evidence: OutboundMessageEvidence
    artifact_refs: list[str] = Field(default_factory=list)
    timeline_events: list[dict[str, Any]] = Field(default_factory=list)
    data_quality: AlertApplicationDataQuality = Field(default_factory=AlertApplicationDataQuality)
    privacy: AlertApplicationPrivacy = Field(default_factory=AlertApplicationPrivacy)
    boundary: AlertApplicationBoundary = Field(default_factory=AlertApplicationBoundary)

    @model_validator(mode="after")
    def enforce_dry_run(self) -> "AlertApplicationDryRunResult":
        if not self.rendered_messages:
            raise ValueError("dry-run result requires rendered messages")
        _raise_forbidden_fields(self.model_dump(mode="json"))
        return self


class EmergencyCallOutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_packet_id: str = Field(min_length=1)
    source_packet_sha256: str = Field(min_length=1)
    source_policy_sha256: str = Field(min_length=1)
    rendered_message_sha256: str = Field(min_length=1)
    transport_profile: AlertTransportProfile
    executor_kind: EmergencyCallOutExecutorKind = "local_dry_run"
    idempotency_key: str = Field(min_length=1, max_length=128)
    explicit_confirmation: bool = False
    operator_identity_ref: str | None = None
    operator_authenticated: bool = False
    operator_approval_phrase: str | None = None

    @model_validator(mode="after")
    def enforce_request_shape(self) -> "EmergencyCallOutRequest":
        if self.operator_authenticated and not self.operator_identity_ref:
            raise ValueError("authenticated call-out request requires operator identity")
        _raise_forbidden_fields(self.model_dump(mode="json"))
        return self


class EmergencyCallOutAdmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_emergency_call_out_admission"
    artifact_version: str = "emergency_call_out_admission.v0"
    source_provider: str = "scout_alert_application_layer"
    sha256: str = Field(min_length=1)
    request_sha256: str = Field(min_length=1)
    source_packet_id: str = Field(min_length=1)
    source_packet_sha256: str = Field(min_length=1)
    source_policy_sha256: str = Field(min_length=1)
    rendered_message_sha256: str = Field(min_length=1)
    transport_profile: AlertTransportProfile
    executor_kind: EmergencyCallOutExecutorKind
    status: EmergencyCallOutAdmissionStatus
    admitted: bool
    operator_identity_ref: str | None = None
    operator_authenticated: bool = False
    authenticated_operator_required: bool = True
    production_executor_available: bool = False
    verified_delivery_possible: bool = False
    reasons: list[str] = Field(default_factory=list)
    data_quality: AlertApplicationDataQuality = Field(
        default_factory=AlertApplicationDataQuality
    )
    privacy: AlertApplicationPrivacy = Field(default_factory=AlertApplicationPrivacy)
    boundary: AlertApplicationBoundary = Field(default_factory=AlertApplicationBoundary)

    @model_validator(mode="after")
    def enforce_admission(self) -> "EmergencyCallOutAdmission":
        if self.admitted != self.status.startswith("admitted_"):
            raise ValueError("call-out admission status and admitted flag disagree")
        if self.executor_kind == "production_transport" and self.admitted:
            raise ValueError("production transport executor is not available in v0")
        if self.verified_delivery_possible:
            raise ValueError("verified delivery is not possible in v0")
        _raise_forbidden_fields(self.model_dump(mode="json"))
        return self


class EmergencyCallOutAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_emergency_call_out_attempt"
    artifact_version: str = "emergency_call_out_attempt.v0"
    source_provider: str = "scout_alert_application_layer"
    attempt_id: str = Field(min_length=1)
    sha256: str = Field(min_length=1)
    request_sha256: str = Field(min_length=1)
    admission_sha256: str = Field(min_length=1)
    source_packet_id: str = Field(min_length=1)
    source_packet_sha256: str = Field(min_length=1)
    source_policy_sha256: str = Field(min_length=1)
    rendered_message_sha256: str = Field(min_length=1)
    transport_profile: AlertTransportProfile
    executor_kind: EmergencyCallOutExecutorKind
    idempotency_key: str = Field(min_length=1, max_length=128)
    attempted: bool = True
    dry_run: bool = True
    manual_handoff_recorded: bool = False
    network_connection_attempted: bool = False
    production_transport_invoked: bool = False
    hardware_transport_invoked: bool = False
    external_send_performed: bool = False
    sent: bool = False
    data_quality: AlertApplicationDataQuality = Field(
        default_factory=AlertApplicationDataQuality
    )
    privacy: AlertApplicationPrivacy = Field(default_factory=AlertApplicationPrivacy)
    boundary: AlertApplicationBoundary = Field(default_factory=AlertApplicationBoundary)

    @model_validator(mode="after")
    def enforce_attempt_boundary(self) -> "EmergencyCallOutAttempt":
        if not self.dry_run:
            raise ValueError("call-out v0 attempt must remain dry-run")
        if self.executor_kind == "manual_handoff" and not self.manual_handoff_recorded:
            raise ValueError("manual handoff attempt must record manual handoff state")
        if self.executor_kind != "manual_handoff" and self.manual_handoff_recorded:
            raise ValueError("manual handoff state is only valid for manual_handoff")
        if (
            self.network_connection_attempted
            or self.production_transport_invoked
            or self.hardware_transport_invoked
            or self.external_send_performed
            or self.sent
        ):
            raise ValueError("call-out v0 attempt cannot claim a production effect")
        _raise_forbidden_fields(self.model_dump(mode="json"))
        return self


class EmergencyCallOutDeliveryReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_emergency_call_out_delivery_receipt"
    artifact_version: str = "emergency_call_out_delivery_receipt.v0"
    source_provider: str = "scout_alert_application_layer"
    receipt_id: str = Field(min_length=1)
    sha256: str = Field(min_length=1)
    request_sha256: str = Field(min_length=1)
    source_attempt_id: str = Field(min_length=1)
    source_attempt_sha256: str = Field(min_length=1)
    source_packet_id: str = Field(min_length=1)
    source_packet_sha256: str = Field(min_length=1)
    rendered_message_sha256: str = Field(min_length=1)
    outcome: EmergencyCallOutReceiptOutcome
    idempotency_key: str = Field(min_length=1, max_length=128)
    delivery_claim: Literal["not_delivered", "manual_handoff_unverified"] = (
        "not_delivered"
    )
    production_delivery_verified: bool = False
    verified_delivery_evidence_ref: str | None = None
    production_send_performed: bool = False
    external_send_performed: bool = False
    hardware_transport_invoked: bool = False
    sent: bool = False
    data_quality: AlertApplicationDataQuality = Field(
        default_factory=AlertApplicationDataQuality
    )
    privacy: AlertApplicationPrivacy = Field(default_factory=AlertApplicationPrivacy)
    boundary: AlertApplicationBoundary = Field(default_factory=AlertApplicationBoundary)

    @model_validator(mode="after")
    def enforce_receipt_boundary(self) -> "EmergencyCallOutDeliveryReceipt":
        if self.outcome == "manual_handoff_recorded" and (
            self.delivery_claim != "manual_handoff_unverified"
        ):
            raise ValueError("manual handoff receipt must remain unverified")
        if self.outcome == "dry_run_recorded" and self.delivery_claim != "not_delivered":
            raise ValueError("dry-run receipt cannot claim delivery")
        if (
            self.production_delivery_verified
            or self.verified_delivery_evidence_ref is not None
            or self.production_send_performed
            or self.external_send_performed
            or self.hardware_transport_invoked
            or self.sent
        ):
            raise ValueError("call-out v0 receipt cannot claim production delivery")
        _raise_forbidden_fields(self.model_dump(mode="json"))
        return self


class EmergencyCallOutExecutorResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_emergency_call_out_executor_result"
    artifact_version: str = "emergency_call_out_executor_result.v0"
    source_provider: str = "scout_alert_application_layer"
    sha256: str = Field(min_length=1)
    request_sha256: str = Field(min_length=1)
    admission: EmergencyCallOutAdmission
    attempt: EmergencyCallOutAttempt | None = None
    delivery_receipt: EmergencyCallOutDeliveryReceipt | None = None
    timeline_events: list[dict[str, Any]] = Field(default_factory=list)
    data_quality: AlertApplicationDataQuality = Field(
        default_factory=AlertApplicationDataQuality
    )
    privacy: AlertApplicationPrivacy = Field(default_factory=AlertApplicationPrivacy)
    boundary: AlertApplicationBoundary = Field(default_factory=AlertApplicationBoundary)

    @model_validator(mode="after")
    def enforce_result_boundary(self) -> "EmergencyCallOutExecutorResult":
        if self.admission.admitted and self.attempt is None:
            raise ValueError("admitted call-out result requires an attempt")
        if not self.admission.admitted and (
            self.attempt is not None or self.delivery_receipt is not None
        ):
            raise ValueError("blocked call-out result cannot include attempt or receipt")
        _raise_forbidden_fields(self.model_dump(mode="json"))
        return self


class ProductionEmergencyApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_packet_id: str = Field(min_length=1)
    source_packet_sha256: str = Field(min_length=1)
    source_policy_sha256: str = Field(min_length=1)
    rendered_message_sha256: str = Field(min_length=1)
    call_out_admission_sha256: str = Field(min_length=1)
    transport_profile: AlertTransportProfile
    idempotency_key: str = Field(min_length=1, max_length=128)
    operator_identity_ref: str | None = None
    operator_authentication_ref: str | None = None
    operator_authentication_sha256: str | None = None
    operator_authenticated: bool = False
    operator_approval_phrase: str | None = None
    explicit_confirmation: bool = False

    @model_validator(mode="after")
    def enforce_approval_request(self) -> "ProductionEmergencyApprovalRequest":
        if self.operator_authenticated and (
            not self.operator_identity_ref
            or not self.operator_authentication_ref
            or not self.operator_authentication_sha256
        ):
            raise ValueError("authenticated approval requires operator proof refs")
        _raise_forbidden_fields(self.model_dump(mode="json"))
        return self


class ProductionEmergencyApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_emergency_approval_decision"
    artifact_version: str = "production_emergency_approval_decision.v0"
    source_provider: str = "scout_alert_application_layer"
    sha256: str = Field(min_length=1)
    request_sha256: str = Field(min_length=1)
    source_packet_id: str = Field(min_length=1)
    source_packet_sha256: str = Field(min_length=1)
    source_policy_sha256: str = Field(min_length=1)
    rendered_message_sha256: str = Field(min_length=1)
    call_out_admission_sha256: str = Field(min_length=1)
    transport_profile: AlertTransportProfile
    status: ProductionEmergencyApprovalStatus
    operator_identity_ref: str | None = None
    operator_authentication_ref: str | None = None
    operator_authenticated: bool = False
    authenticated_operator_required: bool = True
    operator_approval_recorded: bool = False
    production_approval_granted: bool = False
    transport_release_authorized: bool = False
    verified_delivery_required: bool = True
    verified_delivery_present: bool = False
    workflow_complete: bool = False
    reasons: list[str] = Field(default_factory=list)
    data_quality: AlertApplicationDataQuality = Field(
        default_factory=AlertApplicationDataQuality
    )
    privacy: AlertApplicationPrivacy = Field(default_factory=AlertApplicationPrivacy)
    boundary: AlertApplicationBoundary = Field(default_factory=AlertApplicationBoundary)

    @model_validator(mode="after")
    def enforce_approval_decision(self) -> "ProductionEmergencyApprovalDecision":
        if self.workflow_complete:
            raise ValueError("production approval v0 cannot complete without verified delivery")
        if (
            self.production_approval_granted
            or self.transport_release_authorized
            or self.verified_delivery_present
        ):
            raise ValueError("production approval v0 cannot grant production authority")
        if self.operator_approval_recorded and self.status != (
            "authenticated_approval_recorded_pending_transport"
        ):
            raise ValueError("operator approval can only be recorded in pending status")
        _raise_forbidden_fields(self.model_dump(mode="json"))
        return self


class ProductionTransportReleaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    production_approval_sha256: str = Field(min_length=1)
    source_packet_sha256: str = Field(min_length=1)
    source_policy_sha256: str = Field(min_length=1)
    rendered_message_sha256: str = Field(min_length=1)
    call_out_admission_sha256: str = Field(min_length=1)
    transport_profile: AlertTransportProfile
    production_gate_residency_audit_sha256: str | None = None
    production_gate_residency_status: Literal[
        "all_resident",
        "partial_resident",
        "shadow_only",
        "not_resident",
        "missing",
    ] = "missing"
    runtime_authorization_ref: str | None = None
    runtime_authorization_sha256: str | None = None
    effect_boundary_ref: str | None = None
    effect_boundary_sha256: str | None = None
    effect_boundary_reviewed: bool = False
    idempotency_key: str = Field(min_length=1, max_length=128)
    explicit_confirmation: bool = False
    operator_approval_phrase: str | None = None

    @model_validator(mode="after")
    def enforce_transport_release_request(
        self,
    ) -> "ProductionTransportReleaseRequest":
        if self.effect_boundary_reviewed and (
            not self.runtime_authorization_ref
            or not self.runtime_authorization_sha256
            or not self.effect_boundary_ref
            or not self.effect_boundary_sha256
        ):
            raise ValueError("reviewed effect boundary requires runtime and boundary refs")
        _raise_forbidden_fields(self.model_dump(mode="json"))
        return self


class ProductionTransportReleaseDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_transport_release_decision"
    artifact_version: str = "production_transport_release_decision.v0"
    source_provider: str = "scout_alert_application_layer"
    sha256: str = Field(min_length=1)
    request_sha256: str = Field(min_length=1)
    source_approval_sha256: str = Field(min_length=1)
    source_packet_sha256: str = Field(min_length=1)
    source_policy_sha256: str = Field(min_length=1)
    rendered_message_sha256: str = Field(min_length=1)
    call_out_admission_sha256: str = Field(min_length=1)
    transport_profile: AlertTransportProfile
    status: ProductionTransportReleaseStatus
    production_gate_residency_audit_sha256: str | None = None
    production_gate_residency_status: str = "missing"
    runtime_authorization_ref: str | None = None
    runtime_authorization_sha256: str | None = None
    effect_boundary_ref: str | None = None
    effect_boundary_sha256: str | None = None
    effect_boundary_reviewed: bool = False
    operator_approval_recorded: bool = False
    production_approval_complete: bool = False
    transport_release_authorized: bool = False
    verified_delivery_required: bool = True
    verified_delivery_present: bool = False
    workflow_complete: bool = False
    production_transport_invoked_by_release: bool = False
    external_send_performed_by_release: bool = False
    hardware_transport_invoked_by_release: bool = False
    reasons: list[str] = Field(default_factory=list)
    data_quality: AlertApplicationDataQuality = Field(
        default_factory=AlertApplicationDataQuality
    )
    privacy: AlertApplicationPrivacy = Field(default_factory=AlertApplicationPrivacy)
    boundary: ProductionEmergencyWorkflowBoundary = Field(
        default_factory=ProductionEmergencyWorkflowBoundary
    )

    @model_validator(mode="after")
    def enforce_transport_release_decision(
        self,
    ) -> "ProductionTransportReleaseDecision":
        released = self.status == "released_for_approved_executor_selection"
        if self.production_approval_complete != released:
            raise ValueError("production approval completion must match release status")
        if self.transport_release_authorized != released:
            raise ValueError("transport release authorization must match release status")
        if self.workflow_complete or self.verified_delivery_present:
            raise ValueError("transport release is not final workflow completion")
        if (
            self.production_transport_invoked_by_release
            or self.external_send_performed_by_release
            or self.hardware_transport_invoked_by_release
        ):
            raise ValueError("transport release cannot perform transport effects")
        _raise_forbidden_fields(self.model_dump(mode="json"))
        return self


class ApprovedTransportExecutor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executor_id: str = Field(min_length=1)
    transport_profile: AlertTransportProfile
    executor_ref: str = Field(min_length=1)
    executor_sha256: str | None = None
    approved_for_production: bool = False
    delivery_verification_supported: bool = False
    hardware_backed: bool = False
    network_transport_enabled: bool = False
    credential_ref: str | None = None
    credential_material_embedded: bool = False
    candidate_only: bool = True
    runtime_safety_truth: bool = False

    @model_validator(mode="after")
    def enforce_executor_registry_entry(self) -> "ApprovedTransportExecutor":
        if self.credential_material_embedded:
            raise ValueError("transport executor registry cannot embed credential material")
        if self.approved_for_production and not self.delivery_verification_supported:
            raise ValueError("approved transport executor requires delivery verification")
        _raise_forbidden_fields(self.model_dump(mode="json"))
        return self


class ApprovedTransportExecutorSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    production_approval_sha256: str = Field(min_length=1)
    transport_release_sha256: str | None = None
    source_packet_sha256: str = Field(min_length=1)
    rendered_message_sha256: str = Field(min_length=1)
    transport_profile: AlertTransportProfile
    executor_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def enforce_executor_selection_request(
        self,
    ) -> "ApprovedTransportExecutorSelectionRequest":
        _raise_forbidden_fields(self.model_dump(mode="json"))
        return self


class ApprovedTransportExecutorSelectionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_approved_transport_executor_selection"
    artifact_version: str = "approved_transport_executor_selection.v0"
    source_provider: str = "scout_alert_application_layer"
    sha256: str = Field(min_length=1)
    request_sha256: str = Field(min_length=1)
    production_approval_sha256: str = Field(min_length=1)
    transport_release_sha256: str | None = None
    source_packet_sha256: str = Field(min_length=1)
    rendered_message_sha256: str = Field(min_length=1)
    transport_profile: AlertTransportProfile
    executor_id: str
    status: ApprovedTransportExecutorSelectionStatus
    executor_selected: bool = False
    executor_approved_for_production: bool = False
    delivery_verification_supported: bool = False
    operator_approval_recorded: bool = False
    production_approval_complete: bool = False
    transport_invocation_permitted: bool = False
    network_connection_attempted: bool = False
    production_transport_invoked: bool = False
    hardware_transport_invoked: bool = False
    external_send_performed: bool = False
    sent: bool = False
    production_delivery_verified: bool = False
    reasons: list[str] = Field(default_factory=list)
    executor_ref: str | None = None
    executor_sha256: str | None = None
    data_quality: AlertApplicationDataQuality = Field(
        default_factory=AlertApplicationDataQuality
    )
    privacy: AlertApplicationPrivacy = Field(default_factory=AlertApplicationPrivacy)
    boundary: AlertApplicationBoundary = Field(default_factory=AlertApplicationBoundary)

    @model_validator(mode="after")
    def enforce_executor_selection_boundary(
        self,
    ) -> "ApprovedTransportExecutorSelectionDecision":
        ready = self.status == "ready_for_verified_transport_executor"
        if self.transport_invocation_permitted != ready:
            raise ValueError("transport invocation permission must match ready status")
        if ready and not (
            self.executor_selected
            and self.executor_approved_for_production
            and self.delivery_verification_supported
            and self.production_approval_complete
        ):
            raise ValueError("ready transport executor selection requires all gates")
        if (
            self.network_connection_attempted
            or self.production_transport_invoked
            or self.hardware_transport_invoked
            or self.external_send_performed
            or self.sent
            or self.production_delivery_verified
        ):
            raise ValueError("transport executor selection cannot perform transport effects")
        _raise_forbidden_fields(self.model_dump(mode="json"))
        return self


class ProductionTransportInvocationBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deterministic_guard_only: bool = True
    production_transport_executor_invoked_by_guard: bool = False
    network_connection_attempted_by_guard: bool = False
    external_send_performed_by_guard: bool = False
    hardware_transport_invoked_by_guard: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    runtime_safety_truth_mutated: bool = False
    credential_material_embedded: bool = False
    transport_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_transport_invocation_boundary(
        self,
    ) -> "ProductionTransportInvocationBoundary":
        if not self.deterministic_guard_only:
            raise ValueError("production transport invocation must be guarded")
        if (
            self.production_transport_executor_invoked_by_guard
            or self.network_connection_attempted_by_guard
            or self.external_send_performed_by_guard
            or self.hardware_transport_invoked_by_guard
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
            or self.runtime_safety_truth_mutated
            or self.credential_material_embedded
            or self.transport_payload_embedded
        ):
            raise ValueError("production transport invocation guard cannot perform effects")
        return self


class ProductionTransportEffectReceiptIntakeBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deterministic_intake_only: bool = True
    production_transport_executor_invoked_by_intake: bool = False
    network_connection_attempted_by_intake: bool = False
    external_send_performed_by_intake: bool = False
    hardware_transport_invoked_by_intake: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    runtime_safety_truth_mutated: bool = False
    credential_material_embedded: bool = False
    raw_transport_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_transport_effect_intake_boundary(
        self,
    ) -> "ProductionTransportEffectReceiptIntakeBoundary":
        if not self.deterministic_intake_only:
            raise ValueError("transport effect receipt intake must be deterministic")
        if (
            self.production_transport_executor_invoked_by_intake
            or self.network_connection_attempted_by_intake
            or self.external_send_performed_by_intake
            or self.hardware_transport_invoked_by_intake
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
            or self.runtime_safety_truth_mutated
            or self.credential_material_embedded
            or self.raw_transport_payload_embedded
        ):
            raise ValueError("transport effect receipt intake cannot perform effects")
        return self


class ProductionTransportExecutorEffectBoundaryReadinessBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deterministic_readiness_only: bool = True
    production_transport_executor_invoked_by_readiness: bool = False
    network_connection_attempted_by_readiness: bool = False
    external_send_performed_by_readiness: bool = False
    hardware_transport_invoked_by_readiness: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    runtime_safety_truth_mutated: bool = False
    credential_material_embedded: bool = False
    raw_transport_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_transport_executor_effect_boundary_readiness(
        self,
    ) -> "ProductionTransportExecutorEffectBoundaryReadinessBoundary":
        if not self.deterministic_readiness_only:
            raise ValueError("transport executor readiness must be deterministic")
        if (
            self.production_transport_executor_invoked_by_readiness
            or self.network_connection_attempted_by_readiness
            or self.external_send_performed_by_readiness
            or self.hardware_transport_invoked_by_readiness
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
            or self.runtime_safety_truth_mutated
            or self.credential_material_embedded
            or self.raw_transport_payload_embedded
        ):
            raise ValueError("transport executor readiness cannot perform effects")
        return self


class ProductionTransportInvocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    production_approval_sha256: str = Field(min_length=1)
    transport_release_sha256: str = Field(min_length=1)
    executor_selection_sha256: str = Field(min_length=1)
    source_packet_sha256: str = Field(min_length=1)
    rendered_message_sha256: str = Field(min_length=1)
    transport_profile: AlertTransportProfile
    executor_id: str = Field(min_length=1)
    executor_sha256: str = Field(min_length=1)
    execution_mode: ProductionTransportInvocationMode = "dry_run"
    idempotency_key: str = Field(min_length=1, max_length=128)
    explicit_confirmation: bool = False
    operator_identity_ref: str | None = None
    operator_authenticated: bool = False
    operator_approval_phrase: str | None = None
    reviewed_transport_effect_boundary_ref: str | None = None
    reviewed_transport_effect_boundary_sha256: str | None = None

    @model_validator(mode="after")
    def enforce_transport_invocation_request(
        self,
    ) -> "ProductionTransportInvocationRequest":
        if self.operator_authenticated and not self.operator_identity_ref:
            raise ValueError("authenticated transport invocation requires operator identity")
        _raise_forbidden_fields(self.model_dump(mode="json"))
        return self


class ProductionTransportInvocationReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_transport_invocation_receipt"
    artifact_version: str = "production_transport_invocation_receipt.v0"
    source_provider: str = "scout_alert_application_layer"
    source_path: str
    sha256: str = Field(min_length=1)
    request_sha256: str = Field(min_length=1)
    production_approval_sha256: str = Field(min_length=1)
    transport_release_sha256: str = Field(min_length=1)
    executor_selection_sha256: str = Field(min_length=1)
    source_packet_sha256: str = Field(min_length=1)
    rendered_message_sha256: str = Field(min_length=1)
    transport_profile: AlertTransportProfile
    executor_id: str = Field(min_length=1)
    executor_sha256: str = Field(min_length=1)
    execution_mode: ProductionTransportInvocationMode
    status: ProductionTransportInvocationStatus
    transport_selection_ready: bool = False
    operator_approval_recorded: bool = False
    transport_effect_boundary_reviewed: bool = False
    transport_invocation_authorized: bool = False
    transport_execution_ref: str | None = None
    transport_execution_sha256: str | None = None
    production_transport_invoked: bool = False
    network_connection_attempted: bool = False
    external_send_performed: bool = False
    hardware_transport_invoked: bool = False
    sent: bool = False
    production_delivery_verified: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    runtime_safety_truth_mutated: bool = False
    reasons: list[str] = Field(default_factory=list)
    data_quality: AlertApplicationDataQuality = Field(
        default_factory=AlertApplicationDataQuality
    )
    privacy: AlertApplicationPrivacy = Field(default_factory=AlertApplicationPrivacy)
    boundary: ProductionTransportInvocationBoundary = Field(
        default_factory=ProductionTransportInvocationBoundary
    )

    @model_validator(mode="after")
    def enforce_transport_invocation_receipt(
        self,
    ) -> "ProductionTransportInvocationReceipt":
        authorized = self.status == "transport_invocation_authorized"
        if self.transport_invocation_authorized != authorized:
            raise ValueError("transport invocation authorization must match status")
        if authorized and not (
            self.transport_selection_ready
            and self.operator_approval_recorded
            and self.transport_effect_boundary_reviewed
            and self.transport_execution_ref
            and self.transport_execution_sha256
            and self.executor_sha256
        ):
            raise ValueError("authorized transport invocation requires complete guards")
        if not authorized and (
            self.transport_execution_ref or self.transport_execution_sha256
        ):
            raise ValueError("blocked or dry-run transport invocation cannot include execution refs")
        if (
            self.production_transport_invoked
            or self.network_connection_attempted
            or self.external_send_performed
            or self.hardware_transport_invoked
            or self.sent
            or self.production_delivery_verified
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
            or self.runtime_safety_truth_mutated
        ):
            raise ValueError("transport invocation guard cannot claim effects")
        _raise_forbidden_fields(self.model_dump(mode="json"))
        return self


class ProductionTransportExecutorEffectBoundaryManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = (
        "scout_production_transport_executor_effect_boundary_manifest"
    )
    artifact_version: str = "production_transport_executor_effect_boundary_manifest.v0"
    source_provider: str = "approved_transport_executor"
    source_path: str = Field(min_length=1)
    executor_selection_sha256: str = Field(min_length=1)
    transport_invocation_sha256: str = Field(min_length=1)
    request_sha256: str = Field(min_length=1)
    production_approval_sha256: str = Field(min_length=1)
    transport_release_sha256: str = Field(min_length=1)
    source_packet_sha256: str = Field(min_length=1)
    rendered_message_sha256: str = Field(min_length=1)
    transport_profile: AlertTransportProfile
    executor_id: str = Field(min_length=1)
    executor_sha256: str = Field(min_length=1)
    transport_execution_ref: str = Field(min_length=1)
    transport_execution_sha256: str = Field(min_length=1)
    executor_effect_boundary_ref: str | None = None
    executor_effect_boundary_sha256: str | None = None
    credential_ref: str | None = None
    delivery_verifier_ref: str | None = None
    delivery_verifier_sha256: str | None = None
    fallback_plan_ref: str | None = None
    fallback_plan_sha256: str | None = None
    idempotency_key: str = Field(min_length=1, max_length=128)
    production_transport_invoked_by_readiness: bool = False
    network_connection_attempted_by_readiness: bool = False
    external_send_performed_by_readiness: bool = False
    hardware_transport_invoked_by_readiness: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    runtime_safety_truth_mutated: bool = False
    credential_material_embedded: bool = False
    raw_transport_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_transport_executor_manifest(
        self,
    ) -> "ProductionTransportExecutorEffectBoundaryManifest":
        if (
            self.production_transport_invoked_by_readiness
            or self.network_connection_attempted_by_readiness
            or self.external_send_performed_by_readiness
            or self.hardware_transport_invoked_by_readiness
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
            or self.runtime_safety_truth_mutated
            or self.credential_material_embedded
            or self.raw_transport_payload_embedded
        ):
            raise ValueError("transport executor manifest cannot perform effects")
        _raise_forbidden_fields(self.model_dump(mode="json"))
        return self


class ProductionTransportExecutorEffectBoundaryReadinessDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = (
        "scout_production_transport_executor_effect_boundary_readiness"
    )
    artifact_version: str = "production_transport_executor_effect_boundary_readiness.v0"
    source_provider: str = "scout_alert_application_layer"
    source_path: str
    sha256: str = Field(min_length=1)
    status: ProductionTransportExecutorEffectBoundaryReadinessStatus
    executor_selection_sha256: str = Field(min_length=1)
    transport_invocation_sha256: str = Field(min_length=1)
    manifest_sha256: str = Field(min_length=1)
    request_sha256: str = Field(min_length=1)
    production_approval_sha256: str = Field(min_length=1)
    transport_release_sha256: str = Field(min_length=1)
    source_packet_sha256: str = Field(min_length=1)
    rendered_message_sha256: str = Field(min_length=1)
    transport_profile: AlertTransportProfile
    executor_id: str = Field(min_length=1)
    executor_sha256: str = Field(min_length=1)
    transport_execution_ref: str | None = None
    transport_execution_sha256: str | None = None
    executor_effect_boundary_ref: str | None = None
    executor_effect_boundary_sha256: str | None = None
    credential_ref_present: bool = False
    delivery_verifier_ref: str | None = None
    delivery_verifier_sha256: str | None = None
    fallback_plan_ref: str | None = None
    fallback_plan_sha256: str | None = None
    transport_invocation_authorized: bool = False
    lineage_match: bool = False
    executor_boundary_present: bool = False
    delivery_verifier_present: bool = False
    fallback_plan_present: bool = False
    ready_for_reviewed_transport_effect_boundary: bool = False
    production_transport_executor_invoked: bool = False
    network_connection_attempted: bool = False
    external_send_performed: bool = False
    hardware_transport_invoked: bool = False
    sent: bool = False
    production_delivery_verified: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    runtime_safety_truth_mutated: bool = False
    reasons: list[str] = Field(default_factory=list)
    data_quality: AlertApplicationDataQuality = Field(
        default_factory=AlertApplicationDataQuality
    )
    privacy: AlertApplicationPrivacy = Field(default_factory=AlertApplicationPrivacy)
    boundary: ProductionTransportExecutorEffectBoundaryReadinessBoundary = Field(
        default_factory=ProductionTransportExecutorEffectBoundaryReadinessBoundary
    )

    @model_validator(mode="after")
    def enforce_transport_executor_readiness(
        self,
    ) -> "ProductionTransportExecutorEffectBoundaryReadinessDecision":
        ready = self.status == "ready_for_reviewed_transport_effect_boundary"
        if self.ready_for_reviewed_transport_effect_boundary != ready:
            raise ValueError("transport executor readiness must match status")
        if ready and not (
            self.transport_invocation_authorized
            and self.lineage_match
            and self.executor_boundary_present
            and self.delivery_verifier_present
            and self.fallback_plan_present
        ):
            raise ValueError("ready transport executor boundary requires all gates")
        if (
            self.production_transport_executor_invoked
            or self.network_connection_attempted
            or self.external_send_performed
            or self.hardware_transport_invoked
            or self.sent
            or self.production_delivery_verified
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
            or self.runtime_safety_truth_mutated
        ):
            raise ValueError("transport executor readiness cannot claim effects")
        _raise_forbidden_fields(self.model_dump(mode="json"))
        return self


class ProductionTransportEffectReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_transport_effect_receipt"
    artifact_version: str = "production_transport_effect_receipt.v0"
    source_provider: str = "approved_transport_executor"
    source_path: str = Field(min_length=1)
    sha256: str | None = None
    transport_invocation_sha256: str = Field(min_length=1)
    request_sha256: str = Field(min_length=1)
    production_approval_sha256: str = Field(min_length=1)
    transport_release_sha256: str = Field(min_length=1)
    executor_selection_sha256: str = Field(min_length=1)
    source_packet_sha256: str = Field(min_length=1)
    rendered_message_sha256: str = Field(min_length=1)
    transport_profile: AlertTransportProfile
    executor_id: str = Field(min_length=1)
    executor_sha256: str = Field(min_length=1)
    transport_execution_ref: str = Field(min_length=1)
    transport_execution_sha256: str = Field(min_length=1)
    provider_delivery_evidence_ref: str | None = None
    provider_delivery_evidence_sha256: str | None = None
    provider_delivery_id_hash: str | None = None
    verification_method_ref: str | None = None
    verification_method_sha256: str | None = None
    delivery_status: ProductionDeliveryStatus = "unknown"
    delivery_confirmation_observed: bool = False
    executor_reported_transport_invoked: bool = False
    executor_reported_network_connection_attempted: bool = False
    executor_reported_external_send_performed: bool = False
    executor_reported_hardware_transport_invoked: bool = False
    credential_material_embedded: bool = False
    raw_transport_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_transport_effect_receipt(self) -> "ProductionTransportEffectReceipt":
        if self.credential_material_embedded or self.raw_transport_payload_embedded:
            raise ValueError("transport effect receipt cannot embed credentials or raw payloads")
        _raise_forbidden_fields(self.model_dump(mode="json"))
        return self


class ProductionTransportExecutorExecutionBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewed_transport_effect_boundary_required: bool = True
    injected_transport_client_required: bool = True
    production_transport_effect_allowed: bool = True
    runtime_safety_truth_mutated: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    credential_material_embedded: bool = False
    raw_transport_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_transport_executor_execution_boundary(
        self,
    ) -> "ProductionTransportExecutorExecutionBoundary":
        if not self.reviewed_transport_effect_boundary_required:
            raise ValueError("transport executor requires a reviewed boundary")
        if not self.injected_transport_client_required:
            raise ValueError("transport executor requires an injected client")
        if not self.production_transport_effect_allowed:
            raise ValueError("transport executor boundary must allow transport effects")
        if (
            self.runtime_safety_truth_mutated
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
        ):
            raise ValueError("transport executor boundary cannot mutate safety runtime")
        if self.credential_material_embedded or self.raw_transport_payload_embedded:
            raise ValueError("transport executor boundary cannot embed credentials or raw payloads")
        _raise_forbidden_fields(self.model_dump(mode="json"))
        return self


class ProductionTransportExecutorExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_transport_executor_execution_request"
    artifact_version: str = "production_transport_executor_execution_request.v0"
    transport_executor_readiness_sha256: str = Field(min_length=1)
    transport_invocation_sha256: str = Field(min_length=1)
    manifest_sha256: str = Field(min_length=1)
    request_sha256: str = Field(min_length=1)
    production_approval_sha256: str = Field(min_length=1)
    transport_release_sha256: str = Field(min_length=1)
    executor_selection_sha256: str = Field(min_length=1)
    source_packet_sha256: str = Field(min_length=1)
    rendered_message_sha256: str = Field(min_length=1)
    transport_profile: AlertTransportProfile
    executor_id: str = Field(min_length=1)
    executor_sha256: str = Field(min_length=1)
    transport_execution_ref: str = Field(min_length=1)
    transport_execution_sha256: str = Field(min_length=1)
    executor_effect_boundary_ref: str = Field(min_length=1)
    executor_effect_boundary_sha256: str = Field(min_length=1)
    credential_ref_present: bool = False
    delivery_verifier_ref: str = Field(min_length=1)
    delivery_verifier_sha256: str = Field(min_length=1)
    fallback_plan_ref: str = Field(min_length=1)
    fallback_plan_sha256: str = Field(min_length=1)
    runtime_safety_truth_mutated: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    credential_material_embedded: bool = False
    raw_transport_payload_embedded: bool = False
    boundary: ProductionTransportExecutorExecutionBoundary = Field(
        default_factory=ProductionTransportExecutorExecutionBoundary
    )

    @model_validator(mode="after")
    def enforce_transport_executor_execution_request(
        self,
    ) -> "ProductionTransportExecutorExecutionRequest":
        if not self.credential_ref_present:
            raise ValueError("transport executor request requires credential ref presence")
        if (
            self.runtime_safety_truth_mutated
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
        ):
            raise ValueError("transport executor request cannot mutate safety runtime")
        if self.credential_material_embedded or self.raw_transport_payload_embedded:
            raise ValueError("transport executor request cannot embed credentials or raw payloads")
        _raise_forbidden_fields(self.model_dump(mode="json"))
        return self


class ProductionTransportExecutorExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_transport_executor_execution_result"
    artifact_version: str = "production_transport_executor_execution_result.v0"
    source_provider: str = "approved_transport_executor"
    source_path: str = Field(min_length=1)
    transport_invocation_sha256: str = Field(min_length=1)
    request_sha256: str = Field(min_length=1)
    production_approval_sha256: str = Field(min_length=1)
    transport_release_sha256: str = Field(min_length=1)
    executor_selection_sha256: str = Field(min_length=1)
    source_packet_sha256: str = Field(min_length=1)
    rendered_message_sha256: str = Field(min_length=1)
    transport_profile: AlertTransportProfile
    executor_id: str = Field(min_length=1)
    executor_sha256: str = Field(min_length=1)
    transport_execution_ref: str = Field(min_length=1)
    transport_execution_sha256: str = Field(min_length=1)
    provider_delivery_evidence_ref: str | None = None
    provider_delivery_evidence_sha256: str | None = None
    provider_delivery_id_hash: str | None = None
    verification_method_ref: str | None = None
    verification_method_sha256: str | None = None
    delivery_status: ProductionDeliveryStatus = "unknown"
    delivery_confirmation_observed: bool = False
    executor_reported_transport_invoked: bool = False
    executor_reported_network_connection_attempted: bool = False
    executor_reported_external_send_performed: bool = False
    executor_reported_hardware_transport_invoked: bool = False
    executor_reported_safety_api_called: bool = False
    executor_reported_phase1_l0_l4_state_mutated: bool = False
    executor_reported_runtime_safety_truth_mutated: bool = False
    credential_material_embedded: bool = False
    raw_transport_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_transport_executor_execution_result(
        self,
    ) -> "ProductionTransportExecutorExecutionResult":
        if (
            self.executor_reported_safety_api_called
            or self.executor_reported_phase1_l0_l4_state_mutated
            or self.executor_reported_runtime_safety_truth_mutated
        ):
            raise ValueError("transport execution result cannot mutate safety runtime")
        if self.credential_material_embedded or self.raw_transport_payload_embedded:
            raise ValueError("transport execution result cannot embed credentials or raw payloads")
        _raise_forbidden_fields(self.model_dump(mode="json"))
        return self


class ProductionTransportExecutorExecutionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_transport_executor_execution_decision"
    artifact_version: str = "production_transport_executor_execution_decision.v0"
    source_provider: str = "scout_alert_application_layer"
    source_path: str
    sha256: str = Field(min_length=1)
    status: ProductionTransportExecutorExecutionStatus
    transport_executor_readiness_sha256: str = Field(min_length=1)
    transport_invocation_sha256: str = Field(min_length=1)
    execution_request_sha256: str | None = None
    effect_receipt_sha256: str | None = None
    effect_receipt: ProductionTransportEffectReceipt | None = None
    transport_executor_ready: bool = False
    transport_invocation_authorized: bool = False
    transport_execution_lineage_match: bool = False
    transport_client_called: bool = False
    transport_client_result_valid: bool = False
    transport_client_effect_present: bool = False
    production_transport_executor_invoked: bool = False
    network_connection_attempted: bool = False
    external_send_performed: bool = False
    hardware_transport_invoked: bool = False
    sent: bool = False
    production_delivery_verified: bool = False
    runtime_safety_truth_mutated: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    reasons: list[str] = Field(default_factory=list)
    data_quality: AlertApplicationDataQuality = Field(
        default_factory=AlertApplicationDataQuality
    )
    privacy: AlertApplicationPrivacy = Field(default_factory=AlertApplicationPrivacy)
    boundary: ProductionTransportExecutorExecutionBoundary = Field(
        default_factory=ProductionTransportExecutorExecutionBoundary
    )

    @model_validator(mode="after")
    def enforce_transport_executor_execution_decision(
        self,
    ) -> "ProductionTransportExecutorExecutionDecision":
        emitted = self.status == "transport_effect_receipt_emitted"
        if emitted and not (
            self.effect_receipt
            and self.effect_receipt_sha256
            and self.execution_request_sha256
            and self.transport_executor_ready
            and self.transport_invocation_authorized
            and self.transport_execution_lineage_match
            and self.transport_client_called
            and self.transport_client_result_valid
            and self.transport_client_effect_present
        ):
            raise ValueError("emitted transport effect receipt requires all gates")
        if not emitted and (self.effect_receipt or self.effect_receipt_sha256):
            raise ValueError("blocked transport execution cannot include receipt")
        if (
            self.production_delivery_verified
            or self.runtime_safety_truth_mutated
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
        ):
            raise ValueError("transport executor decision cannot mutate or verify safety runtime")
        _raise_forbidden_fields(self.model_dump(mode="json"))
        return self


class ProductionDeliveryEvidenceReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_delivery_evidence_report"
    artifact_version: str = "production_delivery_evidence_report.v0"
    source_provider: str = "approved_transport_executor"
    source_path: str = Field(min_length=1)
    sha256: str | None = None
    executor_selection_sha256: str = Field(min_length=1)
    production_approval_sha256: str = Field(min_length=1)
    transport_release_sha256: str | None = None
    source_packet_sha256: str = Field(min_length=1)
    rendered_message_sha256: str = Field(min_length=1)
    transport_profile: AlertTransportProfile
    executor_id: str = Field(min_length=1)
    executor_sha256: str = Field(min_length=1)
    transport_execution_ref: str | None = None
    transport_execution_sha256: str | None = None
    provider_delivery_evidence_ref: str | None = None
    provider_delivery_evidence_sha256: str | None = None
    provider_delivery_id_hash: str | None = None
    verification_method_ref: str | None = None
    verification_method_sha256: str | None = None
    delivery_status: ProductionDeliveryStatus = "unknown"
    delivery_confirmation_observed: bool = False
    credential_material_embedded: bool = False
    raw_transport_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_delivery_report(self) -> "ProductionDeliveryEvidenceReport":
        if self.credential_material_embedded or self.raw_transport_payload_embedded:
            raise ValueError("delivery evidence cannot embed credentials or raw payloads")
        _raise_forbidden_fields(self.model_dump(mode="json"))
        return self


class ProductionTransportEffectReceiptIntakeDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_transport_effect_receipt_intake"
    artifact_version: str = "production_transport_effect_receipt_intake.v0"
    source_provider: str = "scout_alert_application_layer"
    source_path: str
    sha256: str = Field(min_length=1)
    status: ProductionTransportEffectReceiptIntakeStatus
    transport_invocation_sha256: str = Field(min_length=1)
    effect_receipt_sha256: str = Field(min_length=1)
    delivery_report_sha256: str | None = None
    source_packet_sha256: str = Field(min_length=1)
    rendered_message_sha256: str = Field(min_length=1)
    transport_profile: AlertTransportProfile
    executor_id: str = Field(min_length=1)
    executor_sha256: str = Field(min_length=1)
    transport_execution_ref: str | None = None
    transport_execution_sha256: str | None = None
    provider_delivery_evidence_ref: str | None = None
    provider_delivery_evidence_sha256: str | None = None
    delivery_report: ProductionDeliveryEvidenceReport | None = None
    delivery_report_prepared: bool = False
    executor_reported_delivery: bool = False
    intake_verified_delivery_claim: bool = False
    reasons: list[str] = Field(default_factory=list)
    data_quality: AlertApplicationDataQuality = Field(
        default_factory=AlertApplicationDataQuality
    )
    privacy: AlertApplicationPrivacy = Field(default_factory=AlertApplicationPrivacy)
    boundary: ProductionTransportEffectReceiptIntakeBoundary = Field(
        default_factory=ProductionTransportEffectReceiptIntakeBoundary
    )

    @model_validator(mode="after")
    def enforce_transport_effect_intake(
        self,
    ) -> "ProductionTransportEffectReceiptIntakeDecision":
        prepared = self.status == "delivery_report_prepared"
        if self.delivery_report_prepared != prepared:
            raise ValueError("delivery_report_prepared must match status")
        if self.intake_verified_delivery_claim:
            raise ValueError("intake cannot claim verified delivery")
        if prepared and not (self.delivery_report and self.delivery_report_sha256):
            raise ValueError("prepared intake requires a delivery report")
        if not prepared and (self.delivery_report or self.delivery_report_sha256):
            raise ValueError("blocked intake cannot include a delivery report")
        _raise_forbidden_fields(self.model_dump(mode="json"))
        return self


class ProductionDeliveryVerificationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_delivery_verification_decision"
    artifact_version: str = "production_delivery_verification_decision.v0"
    source_provider: str = "scout_alert_application_layer"
    sha256: str = Field(min_length=1)
    report_sha256: str = Field(min_length=1)
    executor_selection_sha256: str = Field(min_length=1)
    transport_invocation_sha256: str | None = None
    production_approval_sha256: str = Field(min_length=1)
    transport_release_sha256: str | None = None
    source_packet_sha256: str = Field(min_length=1)
    rendered_message_sha256: str = Field(min_length=1)
    transport_profile: AlertTransportProfile
    executor_id: str = Field(min_length=1)
    executor_sha256: str | None = None
    status: ProductionDeliveryVerificationStatus
    delivery_evidence_present: bool = False
    executor_reported_delivery: bool = False
    production_delivery_verified: bool = False
    provider_delivery_evidence_ref: str | None = None
    provider_delivery_evidence_sha256: str | None = None
    provider_delivery_id_hash: str | None = None
    transport_execution_ref: str | None = None
    transport_execution_sha256: str | None = None
    reasons: list[str] = Field(default_factory=list)
    data_quality: AlertApplicationDataQuality = Field(
        default_factory=AlertApplicationDataQuality
    )
    privacy: AlertApplicationPrivacy = Field(default_factory=AlertApplicationPrivacy)
    boundary: ProductionEmergencyWorkflowBoundary = Field(
        default_factory=ProductionEmergencyWorkflowBoundary
    )

    @model_validator(mode="after")
    def enforce_delivery_verification(
        self,
    ) -> "ProductionDeliveryVerificationDecision":
        verified = self.status == "verified_delivery_evidence_accepted"
        if self.production_delivery_verified != verified:
            raise ValueError("production delivery verification must match status")
        if verified and not (
            self.delivery_evidence_present
            and self.executor_reported_delivery
            and self.provider_delivery_evidence_ref
            and self.provider_delivery_evidence_sha256
        ):
            raise ValueError("verified delivery requires complete delivery evidence")
        _raise_forbidden_fields(self.model_dump(mode="json"))
        return self


class ProductionEmergencyWorkflowCompletionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_emergency_workflow_completion"
    artifact_version: str = "production_emergency_workflow_completion.v0"
    source_provider: str = "scout_alert_application_layer"
    sha256: str = Field(min_length=1)
    transport_release_sha256: str = Field(min_length=1)
    executor_selection_sha256: str = Field(min_length=1)
    delivery_verification_sha256: str = Field(min_length=1)
    production_approval_sha256: str = Field(min_length=1)
    source_packet_sha256: str = Field(min_length=1)
    rendered_message_sha256: str = Field(min_length=1)
    transport_profile: AlertTransportProfile
    executor_id: str = Field(min_length=1)
    status: ProductionEmergencyWorkflowCompletionStatus
    production_approval_complete: bool = False
    transport_release_authorized: bool = False
    executor_ready_for_verified_transport: bool = False
    verified_delivery_present: bool = False
    workflow_complete: bool = False
    runtime_safety_truth_mutated: bool = False
    safety_api_called: bool = False
    external_send_performed_by_verifier: bool = False
    hardware_transport_invoked_by_verifier: bool = False
    reasons: list[str] = Field(default_factory=list)
    data_quality: AlertApplicationDataQuality = Field(
        default_factory=AlertApplicationDataQuality
    )
    privacy: AlertApplicationPrivacy = Field(default_factory=AlertApplicationPrivacy)
    boundary: ProductionEmergencyWorkflowBoundary = Field(
        default_factory=ProductionEmergencyWorkflowBoundary
    )

    @model_validator(mode="after")
    def enforce_workflow_completion(
        self,
    ) -> "ProductionEmergencyWorkflowCompletionDecision":
        complete = self.status == "workflow_completed_verified_delivery"
        if self.workflow_complete != complete:
            raise ValueError("workflow completion flag must match status")
        if complete and not (
            self.production_approval_complete
            and self.transport_release_authorized
            and self.executor_ready_for_verified_transport
            and self.verified_delivery_present
        ):
            raise ValueError("workflow completion requires all production gates")
        if (
            self.runtime_safety_truth_mutated
            or self.safety_api_called
            or self.external_send_performed_by_verifier
            or self.hardware_transport_invoked_by_verifier
        ):
            raise ValueError("workflow completion verifier cannot perform effects")
        _raise_forbidden_fields(self.model_dump(mode="json"))
        return self


def build_alert_packet_from_phase1_mutation(
    mutation_result: Phase1MutationResult | dict[str, Any],
    *,
    source_path: str = "inline:alert-application-packet",
    route_name: str | None = None,
    party_count: int = 1,
    location_ref: str | None = None,
    condition_summary: str | None = None,
    injuries_or_status: str = "unknown",
    gear_shelter: str = "unknown",
    battery_status: str = "unknown",
    signal_status: str = "unknown",
    communication_method: str = "unknown",
    requested_action: str | None = None,
) -> ScoutAlertPacket:
    result = (
        mutation_result
        if isinstance(mutation_result, Phase1MutationResult)
        else Phase1MutationResult.model_validate(mutation_result)
    )
    details = result.safety_event.details
    route_id = _optional_str(details.get("route_id"))
    segment_id = _optional_str(details.get("segment_id"))
    checkpoint_id = _optional_str(details.get("checkpoint_id"))
    map_target_ids = _unique(details.get("map_target_ids", []))
    selected_gate_id = _optional_str(details.get("selected_gate_id"))
    level = result.resulting_safety_level
    packet_id = _packet_id(result)
    safe_location_ref = location_ref or segment_id or checkpoint_id or route_id or "field-location-ref"
    summary = condition_summary or _condition_summary(result)
    action = requested_action or _default_requested_action(level)
    privacy = AlertApplicationPrivacy()
    boundary = AlertApplicationBoundary()
    quality = AlertApplicationDataQuality(
        confidence=result.data_quality.confidence,
        source_artifact_count=1,
        limitations=[
            *result.data_quality.limitations,
            "Application-layer packet is generated for dry-run review only",
            "No raw health payload, raw GPX, precise coordinate, or exact timestamp is embedded",
        ],
    )
    emergency = EmergencyPacket(
        route_id=route_id,
        route_name=route_name,
        segment_id=segment_id,
        checkpoint_id=checkpoint_id,
        map_target_ids=map_target_ids,
        location_ref=safe_location_ref,
        party_count=party_count,
        condition_summary=summary,
        injuries_or_status=injuries_or_status,
        gear_shelter=gear_shelter,
        battery_status=battery_status,
        signal_status=signal_status,
        communication_method=communication_method,
        requested_action=action,
        source_refs=[result.source_path],
        data_quality=quality,
        privacy=privacy,
        boundary=boundary,
    )
    digest = aggregate_sha256(
        [
            {
                "packet_id": packet_id,
                "source_path": source_path,
                "mutation_id": result.mutation_id,
                "mutation_sha256": result.sha256,
                "level": level.value,
                "event_type": result.safety_event.event_type.value,
                "location_ref": safe_location_ref,
            }
        ]
    )
    return ScoutAlertPacket(
        packet_id=packet_id,
        source_path=source_path,
        sha256=digest,
        phase1_mutation_id=result.mutation_id,
        phase1_mutation_sha256=result.sha256,
        phase1_mutation_source_path=result.source_path,
        safety_level=level,
        event_type=result.safety_event.event_type,
        selected_gate_id=selected_gate_id,
        summary=summary,
        reason=result.safety_event.reason,
        severity_label=_severity_label(level),
        emergency_packet=emergency,
        source_refs=[result.source_path],
        data_quality=quality,
        privacy=privacy,
        boundary=boundary,
    )


def render_sms_text(
    packet: ScoutAlertPacket | dict[str, Any],
    *,
    max_chars: int = 320,
    source_path: str = "inline:sms-alert-message",
) -> RenderedAlertMessage:
    packet_model = _packet_model(packet)
    emergency = packet_model.emergency_packet
    parts = [
        "SCOUT ALERT DRAFT - NOT SENT",
        f"ID {packet_model.packet_id[-12:]}",
        f"LEVEL {packet_model.safety_level.value}",
        _label("ROUTE", emergency.route_name or emergency.route_id),
        _label("SEG", emergency.segment_id),
        _label("CP", emergency.checkpoint_id),
        f"LOCREF {emergency.location_ref}",
        f"PARTY {emergency.party_count}",
        f"STATUS {emergency.condition_summary}",
        f"ACTION {emergency.requested_action}",
        f"CONTACT {'/'.join(emergency.emergency_contacts)}",
    ]
    body = " | ".join(part for part in parts if part)
    truncated = len(body) > max_chars
    if truncated:
        body = body[: max(0, max_chars - 3)] + "..."
    digest = _render_sha(
        packet_model,
        source_path,
        "sms_text",
        {"body_text": body, "max_chars": max_chars, "truncated": truncated},
    )
    return RenderedAlertMessage(
        transport_profile="sms_text",
        source_path=source_path,
        sha256=digest,
        source_packet_id=packet_model.packet_id,
        source_packet_sha256=packet_model.sha256,
        body_text=body,
        max_chars=max_chars,
        char_count=len(body),
        byte_count=len(body.encode("utf-8")),
        truncated=truncated,
        data_quality=AlertApplicationDataQuality(
            confidence=packet_model.data_quality.confidence,
            rendered_profile_count=1,
            truncated_profile_count=1 if truncated else 0,
            limitations=["SMS body is a dry-run manual-copy draft, not a sent message"],
        ),
        privacy=packet_model.privacy,
        boundary=packet_model.boundary,
    )


def render_lora_compact(
    packet: ScoutAlertPacket | dict[str, Any],
    *,
    max_bytes: int = 160,
    source_path: str = "inline:lora-compact-alert-payload",
) -> RenderedAlertMessage:
    packet_model = _packet_model(packet)
    emergency = packet_model.emergency_packet
    payload: dict[str, Any] = {
        "v": 1,
        "id": packet_model.packet_id[-12:],
        "lvl": packet_model.safety_level.value,
        "evt": packet_model.event_type.value,
        "gate": packet_model.selected_gate_id,
        "r": emergency.route_id,
        "s": emergency.segment_id,
        "c": emergency.checkpoint_id,
        "ref": emergency.location_ref,
        "p": emergency.party_count,
        "act": _short_action(emergency.requested_action),
        "sent": False,
    }
    payload = {key: value for key, value in payload.items() if value not in (None, "", [])}
    payload_bytes = _compact_json_bytes(payload)
    truncated = False
    for key in ("evt", "gate", "ref", "c", "s", "r"):
        if len(payload_bytes) <= max_bytes:
            break
        payload.pop(key, None)
        payload["tr"] = True
        truncated = True
        payload_bytes = _compact_json_bytes(payload)
    if len(payload_bytes) > max_bytes:
        payload = {
            "v": 1,
            "id": packet_model.packet_id[-8:],
            "lvl": _short_level(packet_model.safety_level),
            "act": "review",
            "sent": False,
            "tr": True,
        }
        truncated = True
        payload_bytes = _compact_json_bytes(payload)
    digest = _render_sha(
        packet_model,
        source_path,
        "lora_compact",
        {"payload_json": payload, "max_bytes": max_bytes, "truncated": truncated},
    )
    return RenderedAlertMessage(
        transport_profile="lora_compact",
        source_path=source_path,
        sha256=digest,
        source_packet_id=packet_model.packet_id,
        source_packet_sha256=packet_model.sha256,
        body_text=payload_bytes.decode("utf-8"),
        payload_json=payload,
        payload_hex=payload_bytes.hex(),
        payload_base64=base64.b64encode(payload_bytes).decode("ascii"),
        max_bytes=max_bytes,
        char_count=len(payload_bytes.decode("utf-8")),
        byte_count=len(payload_bytes),
        truncated=truncated,
        data_quality=AlertApplicationDataQuality(
            confidence=packet_model.data_quality.confidence,
            rendered_profile_count=1,
            truncated_profile_count=1 if truncated else 0,
            limitations=[
                "LoRa payload is compact application data only; no radio uplink is invoked"
            ],
        ),
        privacy=packet_model.privacy,
        boundary=packet_model.boundary,
    )


def render_mqtt_json(
    packet: ScoutAlertPacket | dict[str, Any],
    *,
    topic_prefix: str = "scout/alerts/application",
    qos: int = 1,
    retain: bool = False,
    source_path: str = "inline:mqtt-alert-payload",
) -> RenderedAlertMessage:
    packet_model = _packet_model(packet)
    emergency = packet_model.emergency_packet
    topic = f"{topic_prefix.rstrip('/')}/{_topic_token(packet_model.packet_id)}"
    payload = {
        "artifact_kind": "scout_alert_mqtt_payload",
        "version": 1,
        "packet_id": packet_model.packet_id,
        "phase1_mutation_id": packet_model.phase1_mutation_id,
        "level": packet_model.safety_level.value,
        "event_type": packet_model.event_type.value,
        "selected_gate_id": packet_model.selected_gate_id,
        "route": {
            "route_id": emergency.route_id,
            "route_name": emergency.route_name,
            "segment_id": emergency.segment_id,
            "checkpoint_id": emergency.checkpoint_id,
            "map_target_ids": emergency.map_target_ids,
            "location_ref": emergency.location_ref,
        },
        "party_count": emergency.party_count,
        "condition_summary": emergency.condition_summary,
        "requested_action": emergency.requested_action,
        "emergency_contacts": emergency.emergency_contacts,
        "sent": False,
        "dry_run": True,
        "privacy": packet_model.privacy.model_dump(mode="json"),
        "boundary": packet_model.boundary.model_dump(mode="json"),
    }
    payload = _strip_none(payload)
    payload_bytes = _pretty_json_bytes(payload)
    digest = _render_sha(
        packet_model,
        source_path,
        "mqtt_json",
        {"topic": topic, "payload_json": payload, "qos": qos, "retain": retain},
    )
    return RenderedAlertMessage(
        transport_profile="mqtt_json",
        source_path=source_path,
        sha256=digest,
        source_packet_id=packet_model.packet_id,
        source_packet_sha256=packet_model.sha256,
        payload_json=payload,
        mqtt_topic=topic,
        mqtt_qos=qos,
        mqtt_retain=retain,
        char_count=len(payload_bytes.decode("utf-8")),
        byte_count=len(payload_bytes),
        data_quality=AlertApplicationDataQuality(
            confidence=packet_model.data_quality.confidence,
            rendered_profile_count=1,
            limitations=["MQTT payload is written as dry-run JSON; no publish is performed"],
        ),
        privacy=packet_model.privacy,
        boundary=packet_model.boundary,
    )


def decide_outbound_policy(
    packet: ScoutAlertPacket | dict[str, Any],
    rendered_messages: list[RenderedAlertMessage | dict[str, Any]],
    *,
    operator_approval_phrase: str | None = None,
    source_path: str = "inline:outbound-policy-decision",
) -> OutboundPolicyDecision:
    packet_model = _packet_model(packet)
    message_models = [
        message
        if isinstance(message, RenderedAlertMessage)
        else RenderedAlertMessage.model_validate(message)
        for message in rendered_messages
    ]
    approval_present = operator_approval_phrase == ALERT_APPROVAL_PHRASE
    if approval_present:
        status: OutboundPolicyStatus = "allowed_manual_copy"
        manual_copy_allowed = True
        reasons = [
            "explicit operator approval phrase was provided",
            "manual copy is allowed, but this module still performs no external send",
        ]
    elif packet_model.safety_level in {SafetyLevel.DISTRESS, SafetyLevel.EMERGENCY}:
        status = "requires_human_approval"
        manual_copy_allowed = False
        reasons = [
            "Phase 1 safety level requires alert review",
            "external send requires a separate approved transport executor",
        ]
    else:
        status = "blocked_dry_run"
        manual_copy_allowed = False
        reasons = [
            "dry-run packet is not high enough for manual-copy alert workflow",
            "external send remains disabled in this slice",
        ]
    digest = aggregate_sha256(
        [
            {
                "source_path": source_path,
                "packet_sha256": packet_model.sha256,
                "rendered_sha256s": [message.sha256 for message in message_models],
                "approval_present": approval_present,
                "status": status,
            }
        ]
    )
    return OutboundPolicyDecision(
        source_path=source_path,
        sha256=digest,
        source_packet_id=packet_model.packet_id,
        source_packet_sha256=packet_model.sha256,
        status=status,
        phase1_safety_level=packet_model.safety_level,
        manual_copy_allowed=manual_copy_allowed,
        operator_approval_present=approval_present,
        reasons=reasons,
        rendered_profile_ids=[message.sha256 for message in message_models],
        data_quality=AlertApplicationDataQuality(
            confidence=packet_model.data_quality.confidence,
            rendered_profile_count=len(message_models),
            truncated_profile_count=sum(1 for message in message_models if message.truncated),
            limitations=["Policy decision is local evidence; no transport executor is invoked"],
        ),
        privacy=packet_model.privacy,
        boundary=packet_model.boundary,
    )


def build_outbound_message_evidence(
    packet: ScoutAlertPacket,
    rendered_messages: list[RenderedAlertMessage],
    policy_decision: OutboundPolicyDecision,
    *,
    source_path: str = "inline:outbound-message-evidence",
    output_refs: list[str] | None = None,
) -> OutboundMessageEvidence:
    evidence_id = _evidence_id(packet, rendered_messages, policy_decision)
    refs = output_refs or []
    digest = aggregate_sha256(
        [
            {
                "evidence_id": evidence_id,
                "source_path": source_path,
                "packet_sha256": packet.sha256,
                "rendered_sha256s": [message.sha256 for message in rendered_messages],
                "policy_sha256": policy_decision.sha256,
                "output_refs": refs,
            }
        ]
    )
    return OutboundMessageEvidence(
        evidence_id=evidence_id,
        source_path=source_path,
        sha256=digest,
        packet_id=packet.packet_id,
        packet_sha256=packet.sha256,
        rendered_message_sha256s=[message.sha256 for message in rendered_messages],
        policy_decision_sha256=policy_decision.sha256,
        output_refs=refs,
        data_quality=AlertApplicationDataQuality(
            confidence=packet.data_quality.confidence,
            source_artifact_count=1,
            rendered_profile_count=len(rendered_messages),
            truncated_profile_count=sum(1 for message in rendered_messages if message.truncated),
            limitations=["Outbound message evidence records drafts only; sent=false"],
        ),
        privacy=packet.privacy,
        boundary=packet.boundary,
    )


def execute_emergency_call_out(
    packet: ScoutAlertPacket | dict[str, Any],
    rendered_message: RenderedAlertMessage | dict[str, Any],
    policy_decision: OutboundPolicyDecision | dict[str, Any],
    request: EmergencyCallOutRequest | dict[str, Any],
) -> EmergencyCallOutExecutorResult:
    packet_model = _packet_model(packet)
    message_model = _message_model(rendered_message)
    policy_model = _policy_model(policy_decision)
    request_model = (
        request
        if isinstance(request, EmergencyCallOutRequest)
        else EmergencyCallOutRequest.model_validate(request)
    )
    request_sha = aggregate_sha256([request_model.model_dump(mode="json")])
    status, reasons = _call_out_admission_status(
        packet_model,
        message_model,
        policy_model,
        request_model,
    )
    admitted = status.startswith("admitted_")
    admission_sha = aggregate_sha256(
        [
            {
                "request_sha256": request_sha,
                "source_packet_sha256": request_model.source_packet_sha256,
                "source_policy_sha256": request_model.source_policy_sha256,
                "rendered_message_sha256": request_model.rendered_message_sha256,
                "transport_profile": request_model.transport_profile,
                "executor_kind": request_model.executor_kind,
                "status": status,
                "operator_authenticated": request_model.operator_authenticated,
            }
        ]
    )
    admission = EmergencyCallOutAdmission(
        sha256=admission_sha,
        request_sha256=request_sha,
        source_packet_id=request_model.source_packet_id,
        source_packet_sha256=request_model.source_packet_sha256,
        source_policy_sha256=request_model.source_policy_sha256,
        rendered_message_sha256=request_model.rendered_message_sha256,
        transport_profile=request_model.transport_profile,
        executor_kind=request_model.executor_kind,
        status=status,
        admitted=admitted,
        operator_identity_ref=request_model.operator_identity_ref,
        operator_authenticated=request_model.operator_authenticated,
        reasons=reasons,
        data_quality=AlertApplicationDataQuality(
            confidence=packet_model.data_quality.confidence,
            rendered_profile_count=1,
            truncated_profile_count=1 if message_model.truncated else 0,
            limitations=[
                "Emergency Call Out v0 is an admission and dry-run executor only",
                "Production transport and verified delivery remain unavailable",
            ],
        ),
        privacy=packet_model.privacy,
        boundary=packet_model.boundary,
    )
    attempt: EmergencyCallOutAttempt | None = None
    receipt: EmergencyCallOutDeliveryReceipt | None = None
    if admitted:
        attempt_id = _call_out_attempt_id(request_sha, admission.sha256)
        attempt_sha = aggregate_sha256(
            [
                {
                    "attempt_id": attempt_id,
                    "request_sha256": request_sha,
                    "admission_sha256": admission.sha256,
                    "packet_sha256": packet_model.sha256,
                    "message_sha256": message_model.sha256,
                    "executor_kind": request_model.executor_kind,
                }
            ]
        )
        attempt = EmergencyCallOutAttempt(
            attempt_id=attempt_id,
            sha256=attempt_sha,
            request_sha256=request_sha,
            admission_sha256=admission.sha256,
            source_packet_id=packet_model.packet_id,
            source_packet_sha256=packet_model.sha256,
            source_policy_sha256=policy_model.sha256,
            rendered_message_sha256=message_model.sha256,
            transport_profile=message_model.transport_profile,
            executor_kind=request_model.executor_kind,
            idempotency_key=request_model.idempotency_key,
            manual_handoff_recorded=request_model.executor_kind == "manual_handoff",
            data_quality=admission.data_quality,
            privacy=packet_model.privacy,
            boundary=packet_model.boundary,
        )
        receipt_id = _call_out_receipt_id(attempt.sha256)
        outcome: EmergencyCallOutReceiptOutcome = (
            "manual_handoff_recorded"
            if request_model.executor_kind == "manual_handoff"
            else "dry_run_recorded"
        )
        receipt_sha = aggregate_sha256(
            [
                {
                    "receipt_id": receipt_id,
                    "request_sha256": request_sha,
                    "attempt_sha256": attempt.sha256,
                    "packet_sha256": packet_model.sha256,
                    "message_sha256": message_model.sha256,
                    "outcome": outcome,
                }
            ]
        )
        receipt = EmergencyCallOutDeliveryReceipt(
            receipt_id=receipt_id,
            sha256=receipt_sha,
            request_sha256=request_sha,
            source_attempt_id=attempt.attempt_id,
            source_attempt_sha256=attempt.sha256,
            source_packet_id=packet_model.packet_id,
            source_packet_sha256=packet_model.sha256,
            rendered_message_sha256=message_model.sha256,
            outcome=outcome,
            idempotency_key=request_model.idempotency_key,
            delivery_claim=(
                "manual_handoff_unverified"
                if outcome == "manual_handoff_recorded"
                else "not_delivered"
            ),
            data_quality=admission.data_quality,
            privacy=packet_model.privacy,
            boundary=packet_model.boundary,
        )
    timeline_events = emergency_call_out_projection_events(
        admission,
        attempt=attempt,
        receipt=receipt,
    )
    result_sha = aggregate_sha256(
        [
            {
                "request_sha256": request_sha,
                "admission_sha256": admission.sha256,
                "attempt_sha256": attempt.sha256 if attempt is not None else None,
                "receipt_sha256": receipt.sha256 if receipt is not None else None,
            }
        ]
    )
    return EmergencyCallOutExecutorResult(
        sha256=result_sha,
        request_sha256=request_sha,
        admission=admission,
        attempt=attempt,
        delivery_receipt=receipt,
        timeline_events=timeline_events,
        data_quality=admission.data_quality,
        privacy=packet_model.privacy,
        boundary=packet_model.boundary,
    )


def run_emergency_call_out_dry_run(
    alert_result: AlertApplicationDryRunResult | dict[str, Any],
    *,
    output_dir: Path | str,
    transport_profile: AlertTransportProfile = "sms_text",
    executor_kind: EmergencyCallOutExecutorKind = "local_dry_run",
    idempotency_key: str = "emergency-call-out-dry-run",
    explicit_confirmation: bool = True,
    operator_identity_ref: str | None = None,
    operator_authenticated: bool = False,
    operator_approval_phrase: str | None = None,
) -> EmergencyCallOutExecutorResult:
    alert_model = (
        alert_result
        if isinstance(alert_result, AlertApplicationDryRunResult)
        else AlertApplicationDryRunResult.model_validate(alert_result)
    )
    message = next(
        (
            item
            for item in alert_model.rendered_messages
            if item.transport_profile == transport_profile
        ),
        None,
    )
    if message is None:
        raise ValueError(f"missing rendered transport profile: {transport_profile}")
    request = EmergencyCallOutRequest(
        source_packet_id=alert_model.packet.packet_id,
        source_packet_sha256=alert_model.packet.sha256,
        source_policy_sha256=alert_model.policy_decision.sha256,
        rendered_message_sha256=message.sha256,
        transport_profile=transport_profile,
        executor_kind=executor_kind,
        idempotency_key=idempotency_key,
        explicit_confirmation=explicit_confirmation,
        operator_identity_ref=operator_identity_ref,
        operator_authenticated=operator_authenticated,
        operator_approval_phrase=operator_approval_phrase,
    )
    result = execute_emergency_call_out(
        alert_model.packet,
        message,
        alert_model.policy_decision,
        request,
    )
    output_root = Path(output_dir).expanduser()
    output_root.mkdir(parents=True, exist_ok=True)
    _write_json(
        output_root / "emergency_call_out_admission.json",
        result.admission.model_dump(mode="json"),
    )
    if result.attempt is not None:
        _write_json(
            output_root / "emergency_call_out_attempt.json",
            result.attempt.model_dump(mode="json"),
        )
    if result.delivery_receipt is not None:
        _write_json(
            output_root / "emergency_call_out_delivery_receipt.json",
            result.delivery_receipt.model_dump(mode="json"),
        )
    _write_json(
        output_root / "emergency_call_out_executor_result.json",
        result.model_dump(mode="json"),
    )
    return result


def evaluate_production_emergency_approval(
    packet: ScoutAlertPacket | dict[str, Any],
    rendered_message: RenderedAlertMessage | dict[str, Any],
    policy_decision: OutboundPolicyDecision | dict[str, Any],
    call_out_result: EmergencyCallOutExecutorResult | dict[str, Any],
    request: ProductionEmergencyApprovalRequest | dict[str, Any],
) -> ProductionEmergencyApprovalDecision:
    packet_model = _packet_model(packet)
    message_model = _message_model(rendered_message)
    policy_model = _policy_model(policy_decision)
    call_out_model = _call_out_result_model(call_out_result)
    request_model = (
        request
        if isinstance(request, ProductionEmergencyApprovalRequest)
        else ProductionEmergencyApprovalRequest.model_validate(request)
    )
    request_sha = aggregate_sha256([request_model.model_dump(mode="json")])
    status, reasons = _production_emergency_approval_status(
        packet_model,
        message_model,
        policy_model,
        call_out_model,
        request_model,
    )
    approval_recorded = status == "authenticated_approval_recorded_pending_transport"
    digest = aggregate_sha256(
        [
            {
                "request_sha256": request_sha,
                "packet_sha256": request_model.source_packet_sha256,
                "policy_sha256": request_model.source_policy_sha256,
                "message_sha256": request_model.rendered_message_sha256,
                "call_out_admission_sha256": request_model.call_out_admission_sha256,
                "status": status,
                "operator_authenticated": request_model.operator_authenticated,
                "operator_approval_recorded": approval_recorded,
            }
        ]
    )
    return ProductionEmergencyApprovalDecision(
        sha256=digest,
        request_sha256=request_sha,
        source_packet_id=request_model.source_packet_id,
        source_packet_sha256=request_model.source_packet_sha256,
        source_policy_sha256=request_model.source_policy_sha256,
        rendered_message_sha256=request_model.rendered_message_sha256,
        call_out_admission_sha256=request_model.call_out_admission_sha256,
        transport_profile=request_model.transport_profile,
        status=status,
        operator_identity_ref=request_model.operator_identity_ref,
        operator_authentication_ref=request_model.operator_authentication_ref,
        operator_authenticated=request_model.operator_authenticated,
        operator_approval_recorded=approval_recorded,
        reasons=reasons,
        data_quality=AlertApplicationDataQuality(
            confidence=packet_model.data_quality.confidence,
            rendered_profile_count=1,
            truncated_profile_count=1 if message_model.truncated else 0,
            limitations=[
                "Production approval v0 records authenticated approval preflight only",
                "Transport release and verified delivery remain unavailable",
            ],
        ),
        privacy=packet_model.privacy,
        boundary=packet_model.boundary,
    )


def evaluate_production_transport_release(
    production_approval: ProductionEmergencyApprovalDecision | dict[str, Any],
    request: ProductionTransportReleaseRequest | dict[str, Any],
) -> ProductionTransportReleaseDecision:
    approval_model = (
        production_approval
        if isinstance(production_approval, ProductionEmergencyApprovalDecision)
        else ProductionEmergencyApprovalDecision.model_validate(production_approval)
    )
    request_model = (
        request
        if isinstance(request, ProductionTransportReleaseRequest)
        else ProductionTransportReleaseRequest.model_validate(request)
    )
    request_sha = aggregate_sha256([request_model.model_dump(mode="json")])
    status, reasons = _production_transport_release_status(
        approval_model,
        request_model,
    )
    released = status == "released_for_approved_executor_selection"
    digest = aggregate_sha256(
        [
            {
                "request_sha256": request_sha,
                "approval_sha256": approval_model.sha256,
                "packet_sha256": request_model.source_packet_sha256,
                "transport_profile": request_model.transport_profile,
                "residency_status": request_model.production_gate_residency_status,
                "effect_boundary_reviewed": request_model.effect_boundary_reviewed,
                "status": status,
            }
        ]
    )
    return ProductionTransportReleaseDecision(
        sha256=digest,
        request_sha256=request_sha,
        source_approval_sha256=approval_model.sha256,
        source_packet_sha256=request_model.source_packet_sha256,
        source_policy_sha256=request_model.source_policy_sha256,
        rendered_message_sha256=request_model.rendered_message_sha256,
        call_out_admission_sha256=request_model.call_out_admission_sha256,
        transport_profile=request_model.transport_profile,
        status=status,
        production_gate_residency_audit_sha256=(
            request_model.production_gate_residency_audit_sha256
        ),
        production_gate_residency_status=(
            request_model.production_gate_residency_status
        ),
        runtime_authorization_ref=request_model.runtime_authorization_ref,
        runtime_authorization_sha256=request_model.runtime_authorization_sha256,
        effect_boundary_ref=request_model.effect_boundary_ref,
        effect_boundary_sha256=request_model.effect_boundary_sha256,
        effect_boundary_reviewed=request_model.effect_boundary_reviewed,
        operator_approval_recorded=approval_model.operator_approval_recorded,
        production_approval_complete=released,
        transport_release_authorized=released,
        reasons=reasons,
        data_quality=AlertApplicationDataQuality(
            confidence=approval_model.data_quality.confidence,
            source_artifact_count=2,
            rendered_profile_count=1,
            limitations=[
                "Transport release is a deterministic approval completion artifact",
                "The release does not invoke network, hardware, or external send",
            ],
        ),
        privacy=approval_model.privacy,
    )


def evaluate_approved_transport_executor_selection(
    production_approval: (
        ProductionEmergencyApprovalDecision
        | ProductionTransportReleaseDecision
        | dict[str, Any]
    ),
    executors: list[ApprovedTransportExecutor | dict[str, Any]],
    request: ApprovedTransportExecutorSelectionRequest | dict[str, Any],
) -> ApprovedTransportExecutorSelectionDecision:
    approval_model, release_model = _transport_selection_authority_models(
        production_approval
    )
    executor_models = [
        executor
        if isinstance(executor, ApprovedTransportExecutor)
        else ApprovedTransportExecutor.model_validate(executor)
        for executor in executors
    ]
    request_model = (
        request
        if isinstance(request, ApprovedTransportExecutorSelectionRequest)
        else ApprovedTransportExecutorSelectionRequest.model_validate(request)
    )
    request_sha = aggregate_sha256([request_model.model_dump(mode="json")])
    matching = next(
        (
            executor
            for executor in executor_models
            if executor.executor_id == request_model.executor_id
            and executor.transport_profile == request_model.transport_profile
        ),
        None,
    )
    expected_transport_release_sha = (
        release_model.sha256 if release_model is not None else None
    )
    expected_approval_sha = (
        release_model.source_approval_sha256
        if release_model is not None
        else approval_model.sha256
    )
    expected_packet_sha = (
        release_model.source_packet_sha256
        if release_model is not None
        else approval_model.source_packet_sha256
    )
    expected_message_sha = (
        release_model.rendered_message_sha256
        if release_model is not None
        else approval_model.rendered_message_sha256
    )
    expected_transport_profile = (
        release_model.transport_profile
        if release_model is not None
        else approval_model.transport_profile
    )
    production_approval_complete = (
        release_model.production_approval_complete
        and release_model.transport_release_authorized
        if release_model is not None
        else approval_model.production_approval_granted
    )
    operator_approval_recorded = (
        release_model.operator_approval_recorded
        if release_model is not None
        else approval_model.operator_approval_recorded
    )
    mismatch = (
        request_model.production_approval_sha256 != expected_approval_sha
        or request_model.transport_release_sha256 != expected_transport_release_sha
        or request_model.source_packet_sha256 != expected_packet_sha
        or request_model.rendered_message_sha256 != expected_message_sha
        or request_model.transport_profile != expected_transport_profile
    )
    reasons: list[str] = []
    if mismatch:
        status: ApprovedTransportExecutorSelectionStatus = "blocked_packet_mismatch"
        reasons.append(
            "transport executor selection request does not match approval lineage"
        )
    elif matching is None:
        status = "blocked_no_matching_executor"
        reasons.append("no approved transport executor matches the requested profile")
    elif not (
        matching.approved_for_production
        and matching.delivery_verification_supported
        and matching.credential_ref
    ):
        status = "blocked_executor_not_approved"
        reasons.append(
            "matching transport executor is not approved with delivery verification"
        )
    elif not (
        production_approval_complete
        and operator_approval_recorded
    ):
        status = "blocked_production_approval_incomplete"
        reasons.append(
            "production transport release is missing or operator approval is incomplete"
        )
    else:
        status = "ready_for_verified_transport_executor"
        reasons.append(
            "approved executor selected; caller must invoke transport in a separate reviewed effect boundary"
        )
    ready = status == "ready_for_verified_transport_executor"
    digest = aggregate_sha256(
        [
            {
                "request_sha256": request_sha,
                "approval_sha256": expected_approval_sha,
                "transport_release_sha256": expected_transport_release_sha,
                "executor_id": request_model.executor_id,
                "status": status,
                "executor_sha256": matching.executor_sha256 if matching else None,
            }
        ]
    )
    return ApprovedTransportExecutorSelectionDecision(
        sha256=digest,
        request_sha256=request_sha,
        production_approval_sha256=request_model.production_approval_sha256,
        transport_release_sha256=request_model.transport_release_sha256,
        source_packet_sha256=request_model.source_packet_sha256,
        rendered_message_sha256=request_model.rendered_message_sha256,
        transport_profile=request_model.transport_profile,
        executor_id=request_model.executor_id,
        status=status,
        executor_selected=matching is not None,
        executor_approved_for_production=(
            bool(matching.approved_for_production) if matching else False
        ),
        delivery_verification_supported=(
            bool(matching.delivery_verification_supported) if matching else False
        ),
        operator_approval_recorded=operator_approval_recorded,
        production_approval_complete=production_approval_complete,
        transport_invocation_permitted=ready,
        reasons=reasons,
        executor_ref=matching.executor_ref if matching else None,
        executor_sha256=matching.executor_sha256 if matching else None,
        data_quality=AlertApplicationDataQuality(
            confidence=(
                release_model.data_quality.confidence
                if release_model is not None
                else approval_model.data_quality.confidence
            ),
            source_artifact_count=1 + len(executor_models),
            rendered_profile_count=1,
            limitations=[
                "Transport executor selection is local preflight only",
                "No network, hardware, external send, or delivery verification is performed",
            ],
        ),
        privacy=(
            release_model.privacy if release_model is not None else approval_model.privacy
        ),
    )


def evaluate_production_transport_invocation_guard(
    transport_release: ProductionTransportReleaseDecision | dict[str, Any],
    executor_selection: ApprovedTransportExecutorSelectionDecision | dict[str, Any],
    request: ProductionTransportInvocationRequest | dict[str, Any],
    *,
    source_path: str = "inline:production-transport-invocation-receipt",
) -> ProductionTransportInvocationReceipt:
    release_model = (
        transport_release
        if isinstance(transport_release, ProductionTransportReleaseDecision)
        else ProductionTransportReleaseDecision.model_validate(transport_release)
    )
    selection_model = (
        executor_selection
        if isinstance(executor_selection, ApprovedTransportExecutorSelectionDecision)
        else ApprovedTransportExecutorSelectionDecision.model_validate(
            executor_selection
        )
    )
    request_model = (
        request
        if isinstance(request, ProductionTransportInvocationRequest)
        else ProductionTransportInvocationRequest.model_validate(request)
    )
    request_sha = aggregate_sha256([request_model.model_dump(mode="json")])
    mismatch = _transport_invocation_request_mismatch(
        release_model,
        selection_model,
        request_model,
    )
    selection_ready = (
        release_model.status == "released_for_approved_executor_selection"
        and release_model.transport_release_authorized
        and selection_model.status == "ready_for_verified_transport_executor"
        and selection_model.transport_invocation_permitted
    )
    operator_approval_recorded = (
        request_model.operator_authenticated
        and bool(request_model.operator_identity_ref)
        and request_model.explicit_confirmation
        and request_model.operator_approval_phrase
        == TRANSPORT_INVOCATION_APPROVAL_PHRASE
    )
    boundary_reviewed = bool(
        request_model.reviewed_transport_effect_boundary_ref
        and request_model.reviewed_transport_effect_boundary_sha256
    )
    reasons: list[str] = []
    transport_execution_ref: str | None = None
    transport_execution_sha: str | None = None
    if mismatch:
        status: ProductionTransportInvocationStatus = (
            "blocked_invocation_lineage_mismatch"
        )
        reasons.append("transport invocation request does not match release or selection")
    elif not selection_ready:
        status = "blocked_transport_selection_not_ready"
        reasons.append("transport release or executor selection is not ready")
    elif not (
        request_model.operator_authenticated and request_model.operator_identity_ref
    ):
        status = "blocked_requires_authenticated_operator"
        reasons.append("authenticated operator identity is required")
    elif not (
        request_model.explicit_confirmation
        and request_model.operator_approval_phrase
        == TRANSPORT_INVOCATION_APPROVAL_PHRASE
    ):
        status = "blocked_requires_explicit_confirmation"
        reasons.append("exact transport invocation confirmation phrase is required")
    elif request_model.execution_mode == "dry_run":
        status = "dry_run_ready"
        reasons.append("transport invocation guard is ready but no executor is invoked")
    elif not boundary_reviewed:
        status = "blocked_transport_effect_boundary_missing"
        reasons.append("reviewed transport effect boundary ref and hash are required")
    else:
        status = "transport_invocation_authorized"
        transport_execution_sha = aggregate_sha256(
            [
                {
                    "request_sha256": request_sha,
                    "transport_release_sha256": release_model.sha256,
                    "executor_selection_sha256": selection_model.sha256,
                    "executor_sha256": selection_model.executor_sha256,
                    "effect_boundary_sha256": (
                        request_model.reviewed_transport_effect_boundary_sha256
                    ),
                    "transport_effects_performed": False,
                }
            ]
        )
        transport_execution_ref = (
            f"transport-invocation://{selection_model.executor_id}/"
            f"{transport_execution_sha[:16]}"
        )
        reasons.append(
            "transport invocation authorized for separate executor boundary; guard performed no send"
        )
    authorized = status == "transport_invocation_authorized"
    digest = aggregate_sha256(
        [
            {
                "source_path": source_path,
                "request_sha256": request_sha,
                "transport_release_sha256": release_model.sha256,
                "executor_selection_sha256": selection_model.sha256,
                "status": status,
                "transport_execution_sha256": transport_execution_sha,
            }
        ]
    )
    return ProductionTransportInvocationReceipt(
        source_path=source_path,
        sha256=digest,
        request_sha256=request_sha,
        production_approval_sha256=release_model.source_approval_sha256,
        transport_release_sha256=release_model.sha256,
        executor_selection_sha256=selection_model.sha256,
        source_packet_sha256=release_model.source_packet_sha256,
        rendered_message_sha256=release_model.rendered_message_sha256,
        transport_profile=release_model.transport_profile,
        executor_id=selection_model.executor_id,
        executor_sha256=selection_model.executor_sha256,
        execution_mode=request_model.execution_mode,
        status=status,
        transport_selection_ready=selection_ready,
        operator_approval_recorded=operator_approval_recorded,
        transport_effect_boundary_reviewed=boundary_reviewed,
        transport_invocation_authorized=authorized,
        transport_execution_ref=transport_execution_ref,
        transport_execution_sha256=transport_execution_sha,
        reasons=reasons,
        data_quality=AlertApplicationDataQuality(
            confidence="high" if authorized else "low",
            source_artifact_count=3,
            rendered_profile_count=1,
            limitations=[
                "Transport invocation guard is deterministic local evidence",
                "The guard does not invoke network, hardware, or external send",
            ],
        ),
        privacy=release_model.privacy,
    )


def evaluate_production_transport_executor_effect_boundary_readiness(
    executor_selection: ApprovedTransportExecutorSelectionDecision | dict[str, Any],
    transport_invocation: ProductionTransportInvocationReceipt | dict[str, Any],
    manifest: ProductionTransportExecutorEffectBoundaryManifest | dict[str, Any],
    *,
    source_path: str = "inline:production-transport-executor-effect-boundary-readiness",
) -> ProductionTransportExecutorEffectBoundaryReadinessDecision:
    selection_model = (
        executor_selection
        if isinstance(executor_selection, ApprovedTransportExecutorSelectionDecision)
        else ApprovedTransportExecutorSelectionDecision.model_validate(
            executor_selection
        )
    )
    invocation_model = (
        transport_invocation
        if isinstance(transport_invocation, ProductionTransportInvocationReceipt)
        else ProductionTransportInvocationReceipt.model_validate(transport_invocation)
    )
    manifest_model = (
        manifest
        if isinstance(manifest, ProductionTransportExecutorEffectBoundaryManifest)
        else ProductionTransportExecutorEffectBoundaryManifest.model_validate(
            manifest
        )
    )
    manifest_sha = _transport_executor_effect_boundary_manifest_sha256(
        manifest_model
    )
    invocation_authorized = (
        invocation_model.status == "transport_invocation_authorized"
        and invocation_model.transport_invocation_authorized
    )
    lineage_match = _transport_executor_effect_boundary_lineage_matches(
        selection_model,
        invocation_model,
        manifest_model,
    )
    executor_boundary_present = bool(
        manifest_model.executor_effect_boundary_ref
        and manifest_model.executor_effect_boundary_sha256
        and manifest_model.credential_ref
    )
    delivery_verifier_present = bool(
        manifest_model.delivery_verifier_ref
        and manifest_model.delivery_verifier_sha256
    )
    fallback_plan_present = bool(
        manifest_model.fallback_plan_ref and manifest_model.fallback_plan_sha256
    )
    status: ProductionTransportExecutorEffectBoundaryReadinessStatus
    reasons: list[str]
    if not invocation_authorized:
        status = "blocked_transport_invocation_not_authorized"
        reasons = ["transport invocation receipt is not authorized"]
    elif not lineage_match:
        status = "blocked_effect_boundary_lineage_mismatch"
        reasons = [
            "transport executor boundary manifest does not match invocation lineage"
        ]
    elif not executor_boundary_present:
        status = "blocked_executor_boundary_missing"
        reasons = [
            "transport executor boundary ref/hash or credential ref is missing"
        ]
    elif not delivery_verifier_present:
        status = "blocked_delivery_verifier_missing"
        reasons = ["transport executor delivery verifier ref/hash is missing"]
    elif not fallback_plan_present:
        status = "blocked_fallback_plan_missing"
        reasons = ["transport executor fallback or rollback plan ref/hash is missing"]
    else:
        status = "ready_for_reviewed_transport_effect_boundary"
        reasons = [
            "transport executor effect boundary is ready for a separate reviewed executor"
        ]

    ready = status == "ready_for_reviewed_transport_effect_boundary"
    digest = aggregate_sha256(
        [
            {
                "source_path": source_path,
                "executor_selection_sha256": selection_model.sha256,
                "transport_invocation_sha256": invocation_model.sha256,
                "manifest_sha256": manifest_sha,
                "status": status,
            }
        ]
    )
    return ProductionTransportExecutorEffectBoundaryReadinessDecision(
        source_path=source_path,
        sha256=digest,
        status=status,
        executor_selection_sha256=selection_model.sha256,
        transport_invocation_sha256=invocation_model.sha256,
        manifest_sha256=manifest_sha,
        request_sha256=invocation_model.request_sha256,
        production_approval_sha256=invocation_model.production_approval_sha256,
        transport_release_sha256=invocation_model.transport_release_sha256,
        source_packet_sha256=invocation_model.source_packet_sha256,
        rendered_message_sha256=invocation_model.rendered_message_sha256,
        transport_profile=invocation_model.transport_profile,
        executor_id=invocation_model.executor_id,
        executor_sha256=invocation_model.executor_sha256,
        transport_execution_ref=manifest_model.transport_execution_ref,
        transport_execution_sha256=manifest_model.transport_execution_sha256,
        executor_effect_boundary_ref=manifest_model.executor_effect_boundary_ref,
        executor_effect_boundary_sha256=(
            manifest_model.executor_effect_boundary_sha256
        ),
        credential_ref_present=bool(manifest_model.credential_ref),
        delivery_verifier_ref=manifest_model.delivery_verifier_ref,
        delivery_verifier_sha256=manifest_model.delivery_verifier_sha256,
        fallback_plan_ref=manifest_model.fallback_plan_ref,
        fallback_plan_sha256=manifest_model.fallback_plan_sha256,
        transport_invocation_authorized=invocation_authorized,
        lineage_match=lineage_match,
        executor_boundary_present=executor_boundary_present,
        delivery_verifier_present=delivery_verifier_present,
        fallback_plan_present=fallback_plan_present,
        ready_for_reviewed_transport_effect_boundary=ready,
        reasons=reasons,
        data_quality=AlertApplicationDataQuality(
            confidence="high" if ready else "low",
            source_artifact_count=3,
            rendered_profile_count=1,
            limitations=[
                "Transport executor readiness validates refs and lineage only",
                "The readiness gate does not invoke network, hardware, or external send",
            ],
        ),
        privacy=invocation_model.privacy,
    )


def execute_production_transport_with_client(
    transport_executor_readiness: (
        ProductionTransportExecutorEffectBoundaryReadinessDecision | dict[str, Any]
    ),
    transport_invocation: ProductionTransportInvocationReceipt | dict[str, Any],
    transport_client: Callable[
        [ProductionTransportExecutorExecutionRequest],
        ProductionTransportExecutorExecutionResult | dict[str, Any],
    ],
    *,
    source_path: str = "inline:production-transport-executor-execution",
) -> ProductionTransportExecutorExecutionDecision:
    readiness_model = (
        transport_executor_readiness
        if isinstance(
            transport_executor_readiness,
            ProductionTransportExecutorEffectBoundaryReadinessDecision,
        )
        else ProductionTransportExecutorEffectBoundaryReadinessDecision.model_validate(
            transport_executor_readiness
        )
    )
    invocation_model = (
        transport_invocation
        if isinstance(transport_invocation, ProductionTransportInvocationReceipt)
        else ProductionTransportInvocationReceipt.model_validate(transport_invocation)
    )
    executor_ready = (
        readiness_model.status == "ready_for_reviewed_transport_effect_boundary"
        and readiness_model.ready_for_reviewed_transport_effect_boundary
    )
    invocation_authorized = (
        invocation_model.status == "transport_invocation_authorized"
        and invocation_model.transport_invocation_authorized
    )
    lineage_match = _transport_executor_execution_matches_invocation(
        readiness_model,
        invocation_model,
    )
    status: ProductionTransportExecutorExecutionStatus
    reasons: list[str]
    execution_request_sha: str | None = None
    effect_receipt_sha: str | None = None
    effect_receipt: ProductionTransportEffectReceipt | None = None
    client_called = False
    client_result_valid = False
    client_effect_present = False
    result_transport_invoked = False
    result_network_attempted = False
    result_external_send = False
    result_hardware_invoked = False

    if not executor_ready:
        status = "blocked_transport_executor_not_ready"
        reasons = ["transport executor effect boundary readiness is not ready"]
    elif not invocation_authorized:
        status = "blocked_transport_invocation_not_authorized"
        reasons = ["transport invocation receipt is not authorized"]
    elif not lineage_match:
        status = "blocked_transport_execution_lineage_mismatch"
        reasons = ["transport executor readiness does not match invocation lineage"]
    else:
        execution_request = ProductionTransportExecutorExecutionRequest(
            transport_executor_readiness_sha256=readiness_model.sha256,
            transport_invocation_sha256=invocation_model.sha256,
            manifest_sha256=readiness_model.manifest_sha256,
            request_sha256=invocation_model.request_sha256,
            production_approval_sha256=invocation_model.production_approval_sha256,
            transport_release_sha256=invocation_model.transport_release_sha256,
            executor_selection_sha256=invocation_model.executor_selection_sha256,
            source_packet_sha256=invocation_model.source_packet_sha256,
            rendered_message_sha256=invocation_model.rendered_message_sha256,
            transport_profile=invocation_model.transport_profile,
            executor_id=invocation_model.executor_id,
            executor_sha256=invocation_model.executor_sha256,
            transport_execution_ref=invocation_model.transport_execution_ref or "",
            transport_execution_sha256=(
                invocation_model.transport_execution_sha256 or ""
            ),
            executor_effect_boundary_ref=(
                readiness_model.executor_effect_boundary_ref or ""
            ),
            executor_effect_boundary_sha256=(
                readiness_model.executor_effect_boundary_sha256 or ""
            ),
            credential_ref_present=readiness_model.credential_ref_present,
            delivery_verifier_ref=readiness_model.delivery_verifier_ref or "",
            delivery_verifier_sha256=readiness_model.delivery_verifier_sha256
            or "",
            fallback_plan_ref=readiness_model.fallback_plan_ref or "",
            fallback_plan_sha256=readiness_model.fallback_plan_sha256 or "",
        )
        execution_request_sha = _transport_executor_execution_request_sha256(
            execution_request
        )
        client_called = True
        try:
            client_result = transport_client(execution_request)
            result_model = (
                client_result
                if isinstance(client_result, ProductionTransportExecutorExecutionResult)
                else ProductionTransportExecutorExecutionResult.model_validate(
                    client_result
                )
            )
        except Exception:  # noqa: BLE001
            status = "blocked_transport_client_result_invalid"
            reasons = ["transport client result failed schema validation"]
        else:
            client_result_valid = True
            result_transport_invoked = result_model.executor_reported_transport_invoked
            result_network_attempted = (
                result_model.executor_reported_network_connection_attempted
            )
            result_external_send = result_model.executor_reported_external_send_performed
            result_hardware_invoked = (
                result_model.executor_reported_hardware_transport_invoked
            )
            client_effect_present = bool(
                result_transport_invoked
                and result_external_send
                and (result_network_attempted or result_hardware_invoked)
            )
            result_lineage_match = _transport_executor_result_matches_request(
                execution_request,
                result_model,
            )
            if not result_lineage_match:
                status = "blocked_transport_client_result_invalid"
                reasons = ["transport client result does not match execution request"]
            elif not client_effect_present:
                status = "blocked_transport_client_effect_missing"
                reasons = ["transport client did not report outbound transport effects"]
            else:
                try:
                    draft_receipt = ProductionTransportEffectReceipt(
                        source_provider=result_model.source_provider,
                        source_path=result_model.source_path,
                        transport_invocation_sha256=invocation_model.sha256,
                        request_sha256=invocation_model.request_sha256,
                        production_approval_sha256=(
                            invocation_model.production_approval_sha256
                        ),
                        transport_release_sha256=(
                            invocation_model.transport_release_sha256
                        ),
                        executor_selection_sha256=(
                            invocation_model.executor_selection_sha256
                        ),
                        source_packet_sha256=invocation_model.source_packet_sha256,
                        rendered_message_sha256=(
                            invocation_model.rendered_message_sha256
                        ),
                        transport_profile=invocation_model.transport_profile,
                        executor_id=invocation_model.executor_id,
                        executor_sha256=invocation_model.executor_sha256,
                        transport_execution_ref=(
                            invocation_model.transport_execution_ref or ""
                        ),
                        transport_execution_sha256=(
                            invocation_model.transport_execution_sha256 or ""
                        ),
                        provider_delivery_evidence_ref=(
                            result_model.provider_delivery_evidence_ref
                        ),
                        provider_delivery_evidence_sha256=(
                            result_model.provider_delivery_evidence_sha256
                        ),
                        provider_delivery_id_hash=(
                            result_model.provider_delivery_id_hash
                        ),
                        verification_method_ref=result_model.verification_method_ref,
                        verification_method_sha256=(
                            result_model.verification_method_sha256
                        ),
                        delivery_status=result_model.delivery_status,
                        delivery_confirmation_observed=(
                            result_model.delivery_confirmation_observed
                        ),
                        executor_reported_transport_invoked=(
                            result_model.executor_reported_transport_invoked
                        ),
                        executor_reported_network_connection_attempted=(
                            result_model.executor_reported_network_connection_attempted
                        ),
                        executor_reported_external_send_performed=(
                            result_model.executor_reported_external_send_performed
                        ),
                        executor_reported_hardware_transport_invoked=(
                            result_model.executor_reported_hardware_transport_invoked
                        ),
                    )
                except Exception:  # noqa: BLE001
                    effect_receipt = None
                    status = "blocked_transport_client_result_invalid"
                    reasons = ["transport client result could not become receipt"]
                else:
                    effect_receipt_sha = _transport_effect_receipt_sha256(
                        draft_receipt
                    )
                    effect_receipt = draft_receipt.model_copy(
                        update={"sha256": effect_receipt_sha}
                    )
                    status = "transport_effect_receipt_emitted"
                    reasons = [
                        "sanitized transport effect receipt emitted from injected client result"
                    ]

    digest = aggregate_sha256(
        [
            {
                "source_path": source_path,
                "transport_executor_readiness_sha256": readiness_model.sha256,
                "transport_invocation_sha256": invocation_model.sha256,
                "execution_request_sha256": execution_request_sha,
                "effect_receipt_sha256": effect_receipt_sha,
                "status": status,
            }
        ]
    )
    return ProductionTransportExecutorExecutionDecision(
        source_path=source_path,
        sha256=digest,
        status=status,
        transport_executor_readiness_sha256=readiness_model.sha256,
        transport_invocation_sha256=invocation_model.sha256,
        execution_request_sha256=execution_request_sha,
        effect_receipt_sha256=effect_receipt_sha,
        effect_receipt=effect_receipt,
        transport_executor_ready=executor_ready,
        transport_invocation_authorized=invocation_authorized,
        transport_execution_lineage_match=lineage_match,
        transport_client_called=client_called,
        transport_client_result_valid=client_result_valid,
        transport_client_effect_present=client_effect_present,
        production_transport_executor_invoked=result_transport_invoked,
        network_connection_attempted=result_network_attempted,
        external_send_performed=result_external_send,
        hardware_transport_invoked=result_hardware_invoked,
        sent=result_external_send,
        reasons=reasons,
        data_quality=AlertApplicationDataQuality(
            confidence="high" if status == "transport_effect_receipt_emitted" else "low",
            source_artifact_count=3,
            rendered_profile_count=1,
            limitations=[
                "Transport executor harness calls only the injected client supplied by the caller",
                "This function does not verify delivery; effect receipt intake and delivery verifier remain separate",
            ],
        ),
        privacy=invocation_model.privacy,
    )


def build_delivery_evidence_from_transport_effect_receipt(
    transport_invocation: ProductionTransportInvocationReceipt | dict[str, Any],
    effect_receipt: ProductionTransportEffectReceipt | dict[str, Any],
    *,
    source_path: str = "inline:production-transport-effect-receipt-intake",
) -> ProductionTransportEffectReceiptIntakeDecision:
    invocation_model = (
        transport_invocation
        if isinstance(transport_invocation, ProductionTransportInvocationReceipt)
        else ProductionTransportInvocationReceipt.model_validate(transport_invocation)
    )
    effect_model = (
        effect_receipt
        if isinstance(effect_receipt, ProductionTransportEffectReceipt)
        else ProductionTransportEffectReceipt.model_validate(effect_receipt)
    )
    effect_sha = effect_model.sha256 or _transport_effect_receipt_sha256(effect_model)
    status: ProductionTransportEffectReceiptIntakeStatus
    reasons: list[str]
    delivery_report: ProductionDeliveryEvidenceReport | None = None
    delivery_report_sha: str | None = None

    if not (
        invocation_model.status == "transport_invocation_authorized"
        and invocation_model.transport_invocation_authorized
    ):
        status = "blocked_transport_invocation_not_authorized"
        reasons = ["transport invocation receipt is not authorized"]
    elif not _transport_effect_receipt_matches_invocation(
        invocation_model,
        effect_model,
    ):
        status = "blocked_effect_receipt_lineage_mismatch"
        reasons = ["transport effect receipt does not match invocation lineage"]
    elif not _transport_effect_delivery_evidence_present(effect_model):
        status = "blocked_missing_delivery_evidence"
        reasons = ["transport effect receipt is missing delivery proof refs"]
    elif not (
        effect_model.delivery_status == "delivered"
        and effect_model.delivery_confirmation_observed
        and effect_model.executor_reported_transport_invoked
        and effect_model.executor_reported_external_send_performed
    ):
        status = "blocked_effect_receipt_not_delivered"
        reasons = ["executor receipt does not prove delivered outbound transport"]
    else:
        status = "delivery_report_prepared"
        reasons = [
            "sanitized delivery evidence report prepared from transport effect receipt"
        ]
        prepared = ProductionDeliveryEvidenceReport(
            source_provider=effect_model.source_provider,
            source_path=effect_model.source_path,
            executor_selection_sha256=effect_model.executor_selection_sha256,
            production_approval_sha256=effect_model.production_approval_sha256,
            transport_release_sha256=effect_model.transport_release_sha256,
            source_packet_sha256=effect_model.source_packet_sha256,
            rendered_message_sha256=effect_model.rendered_message_sha256,
            transport_profile=effect_model.transport_profile,
            executor_id=effect_model.executor_id,
            executor_sha256=effect_model.executor_sha256,
            transport_execution_ref=effect_model.transport_execution_ref,
            transport_execution_sha256=effect_model.transport_execution_sha256,
            provider_delivery_evidence_ref=(
                effect_model.provider_delivery_evidence_ref
            ),
            provider_delivery_evidence_sha256=(
                effect_model.provider_delivery_evidence_sha256
            ),
            provider_delivery_id_hash=effect_model.provider_delivery_id_hash,
            verification_method_ref=effect_model.verification_method_ref,
            verification_method_sha256=effect_model.verification_method_sha256,
            delivery_status=effect_model.delivery_status,
            delivery_confirmation_observed=(
                effect_model.delivery_confirmation_observed
            ),
        )
        delivery_report_sha = _delivery_report_sha256(prepared)
        delivery_report = prepared.model_copy(update={"sha256": delivery_report_sha})

    digest = aggregate_sha256(
        [
            {
                "source_path": source_path,
                "transport_invocation_sha256": invocation_model.sha256,
                "effect_receipt_sha256": effect_sha,
                "delivery_report_sha256": delivery_report_sha,
                "status": status,
            }
        ]
    )
    return ProductionTransportEffectReceiptIntakeDecision(
        source_path=source_path,
        sha256=digest,
        status=status,
        transport_invocation_sha256=invocation_model.sha256,
        effect_receipt_sha256=effect_sha,
        delivery_report_sha256=delivery_report_sha,
        source_packet_sha256=invocation_model.source_packet_sha256,
        rendered_message_sha256=invocation_model.rendered_message_sha256,
        transport_profile=invocation_model.transport_profile,
        executor_id=invocation_model.executor_id,
        executor_sha256=invocation_model.executor_sha256,
        transport_execution_ref=effect_model.transport_execution_ref,
        transport_execution_sha256=effect_model.transport_execution_sha256,
        provider_delivery_evidence_ref=effect_model.provider_delivery_evidence_ref,
        provider_delivery_evidence_sha256=(
            effect_model.provider_delivery_evidence_sha256
        ),
        delivery_report=delivery_report,
        delivery_report_prepared=status == "delivery_report_prepared",
        executor_reported_delivery=effect_model.delivery_status == "delivered",
        reasons=reasons,
        data_quality=AlertApplicationDataQuality(
            confidence="high" if status == "delivery_report_prepared" else "low",
            source_artifact_count=2,
            rendered_profile_count=1,
            limitations=[
                "Transport effect intake validates external executor evidence only",
                "The intake does not invoke network, hardware, or external send",
            ],
        ),
        privacy=invocation_model.privacy,
    )


def verify_production_delivery_evidence(
    executor_selection: ApprovedTransportExecutorSelectionDecision | dict[str, Any],
    delivery_report: ProductionDeliveryEvidenceReport | dict[str, Any],
    transport_invocation: ProductionTransportInvocationReceipt | dict[str, Any] | None = None,
) -> ProductionDeliveryVerificationDecision:
    selection_model = (
        executor_selection
        if isinstance(executor_selection, ApprovedTransportExecutorSelectionDecision)
        else ApprovedTransportExecutorSelectionDecision.model_validate(
            executor_selection
        )
    )
    report_model = (
        delivery_report
        if isinstance(delivery_report, ProductionDeliveryEvidenceReport)
        else ProductionDeliveryEvidenceReport.model_validate(delivery_report)
    )
    invocation_model = (
        None
        if transport_invocation is None
        else transport_invocation
        if isinstance(transport_invocation, ProductionTransportInvocationReceipt)
        else ProductionTransportInvocationReceipt.model_validate(transport_invocation)
    )
    report_sha = report_model.sha256 or aggregate_sha256(
        [
            {
                key: value
                for key, value in report_model.model_dump(mode="json").items()
                if key != "sha256"
            }
        ]
    )
    status, reasons, evidence_present = _production_delivery_verification_status(
        selection_model,
        report_model,
        invocation_model,
    )
    verified = status == "verified_delivery_evidence_accepted"
    digest = aggregate_sha256(
        [
            {
                "report_sha256": report_sha,
                "selection_sha256": selection_model.sha256,
                "transport_invocation_sha256": (
                    invocation_model.sha256 if invocation_model is not None else None
                ),
                "transport_release_sha256": selection_model.transport_release_sha256,
                "packet_sha256": selection_model.source_packet_sha256,
                "message_sha256": selection_model.rendered_message_sha256,
                "status": status,
            }
        ]
    )
    return ProductionDeliveryVerificationDecision(
        sha256=digest,
        report_sha256=report_sha,
        executor_selection_sha256=selection_model.sha256,
        transport_invocation_sha256=(
            invocation_model.sha256 if invocation_model is not None else None
        ),
        production_approval_sha256=selection_model.production_approval_sha256,
        transport_release_sha256=selection_model.transport_release_sha256,
        source_packet_sha256=selection_model.source_packet_sha256,
        rendered_message_sha256=selection_model.rendered_message_sha256,
        transport_profile=selection_model.transport_profile,
        executor_id=selection_model.executor_id,
        executor_sha256=selection_model.executor_sha256,
        status=status,
        delivery_evidence_present=evidence_present,
        executor_reported_delivery=report_model.delivery_status == "delivered",
        production_delivery_verified=verified,
        provider_delivery_evidence_ref=report_model.provider_delivery_evidence_ref,
        provider_delivery_evidence_sha256=(
            report_model.provider_delivery_evidence_sha256
        ),
        provider_delivery_id_hash=report_model.provider_delivery_id_hash,
        transport_execution_ref=report_model.transport_execution_ref,
        transport_execution_sha256=report_model.transport_execution_sha256,
        reasons=reasons,
        data_quality=AlertApplicationDataQuality(
            confidence="high" if verified else "low",
            source_artifact_count=2,
            rendered_profile_count=1,
            limitations=[
                "Delivery verification inspects executor evidence only",
                "The verifier does not invoke network, hardware, or external send",
            ],
        ),
        privacy=selection_model.privacy,
    )


def evaluate_production_emergency_workflow_completion(
    transport_release: ProductionTransportReleaseDecision | dict[str, Any],
    executor_selection: ApprovedTransportExecutorSelectionDecision | dict[str, Any],
    delivery_verification: ProductionDeliveryVerificationDecision | dict[str, Any],
) -> ProductionEmergencyWorkflowCompletionDecision:
    release_model = (
        transport_release
        if isinstance(transport_release, ProductionTransportReleaseDecision)
        else ProductionTransportReleaseDecision.model_validate(transport_release)
    )
    selection_model = (
        executor_selection
        if isinstance(executor_selection, ApprovedTransportExecutorSelectionDecision)
        else ApprovedTransportExecutorSelectionDecision.model_validate(
            executor_selection
        )
    )
    verification_model = (
        delivery_verification
        if isinstance(delivery_verification, ProductionDeliveryVerificationDecision)
        else ProductionDeliveryVerificationDecision.model_validate(
            delivery_verification
        )
    )
    status, reasons = _production_emergency_workflow_completion_status(
        release_model,
        selection_model,
        verification_model,
    )
    complete = status == "workflow_completed_verified_delivery"
    digest = aggregate_sha256(
        [
            {
                "transport_release_sha256": release_model.sha256,
                "executor_selection_sha256": selection_model.sha256,
                "delivery_verification_sha256": verification_model.sha256,
                "status": status,
            }
        ]
    )
    return ProductionEmergencyWorkflowCompletionDecision(
        sha256=digest,
        transport_release_sha256=release_model.sha256,
        executor_selection_sha256=selection_model.sha256,
        delivery_verification_sha256=verification_model.sha256,
        production_approval_sha256=release_model.source_approval_sha256,
        source_packet_sha256=release_model.source_packet_sha256,
        rendered_message_sha256=release_model.rendered_message_sha256,
        transport_profile=release_model.transport_profile,
        executor_id=selection_model.executor_id,
        status=status,
        production_approval_complete=release_model.production_approval_complete,
        transport_release_authorized=release_model.transport_release_authorized,
        executor_ready_for_verified_transport=(
            selection_model.status == "ready_for_verified_transport_executor"
        ),
        verified_delivery_present=verification_model.production_delivery_verified,
        workflow_complete=complete,
        reasons=reasons,
        data_quality=AlertApplicationDataQuality(
            confidence="high" if complete else "low",
            source_artifact_count=3,
            rendered_profile_count=1,
            limitations=[
                "Workflow completion is a deterministic verification artifact",
                "It does not mutate runtime safety truth or perform external send",
            ],
        ),
        privacy=release_model.privacy,
    )


def emergency_call_out_projection_events(
    admission: EmergencyCallOutAdmission,
    *,
    attempt: EmergencyCallOutAttempt | None = None,
    receipt: EmergencyCallOutDeliveryReceipt | None = None,
    sequence: int = 0,
) -> list[dict[str, Any]]:
    events = [
        {
            "event_id": f"emergency_call_out.admission.{admission.sha256[:16]}",
            "sequence": sequence,
            "timestamp": "offset:emergency-call-out-admission",
            "kind": (
                "emergency_call_out_admitted"
                if admission.admitted
                else "emergency_call_out_blocked"
            ),
            "label": "Emergency Call Out admission",
            "severity": "critical",
            "summary": "; ".join(admission.reasons),
            "source_refs": [admission.source_packet_id],
            "payload": {
                "status": admission.status,
                "executor_kind": admission.executor_kind,
                "transport_profile": admission.transport_profile,
                "operator_authenticated": admission.operator_authenticated,
                "production_executor_available": False,
                "verified_delivery_possible": False,
                "sent": False,
                "production_delivery_verified": False,
            },
        }
    ]
    if attempt is not None:
        events.append(
            {
                "event_id": f"emergency_call_out.attempt.{attempt.sha256[:16]}",
                "sequence": sequence + len(events),
                "timestamp": "offset:emergency-call-out-attempt",
                "kind": "emergency_call_out_attempt_recorded",
                "label": "Emergency Call Out attempt",
                "severity": "critical",
                "summary": (
                    "Local call-out attempt recorded; no network, hardware, "
                    "external send, or delivery claim."
                ),
                "source_refs": [attempt.source_packet_id],
                "payload": {
                    "attempt_id": attempt.attempt_id,
                    "executor_kind": attempt.executor_kind,
                    "transport_profile": attempt.transport_profile,
                    "network_connection_attempted": False,
                    "production_transport_invoked": False,
                    "hardware_transport_invoked": False,
                    "external_send_performed": False,
                    "sent": False,
                },
            }
        )
    if receipt is not None:
        events.append(
            {
                "event_id": f"emergency_call_out.receipt.{receipt.sha256[:16]}",
                "sequence": sequence + len(events),
                "timestamp": "offset:emergency-call-out-receipt",
                "kind": "emergency_call_out_delivery_receipt_recorded",
                "label": "Emergency Call Out delivery receipt",
                "severity": "critical",
                "summary": (
                    "Receipt is local and unverified; production delivery remains false."
                ),
                "source_refs": [receipt.source_packet_id, receipt.source_attempt_id],
                "payload": {
                    "receipt_id": receipt.receipt_id,
                    "outcome": receipt.outcome,
                    "delivery_claim": receipt.delivery_claim,
                    "production_delivery_verified": False,
                    "verified_delivery_evidence_ref": None,
                    "sent": False,
                },
            }
        )
    return events


def alert_application_projection_events(
    packet: ScoutAlertPacket,
    rendered_messages: list[RenderedAlertMessage],
    policy_decision: OutboundPolicyDecision,
    *,
    sequence: int = 0,
) -> list[dict[str, Any]]:
    map_refs = packet.emergency_packet.map_target_ids
    return [
        {
            "event_id": f"alert_application.{packet.packet_id}",
            "sequence": sequence,
            "timestamp": "offset:alert-application-packet",
            "kind": "alert_application_packet_prepared",
            "label": "Alert packet prepared",
            "severity": packet.severity_label,
            "summary": packet.summary,
            "source_refs": [packet.source_path, *packet.source_refs],
            "map_refs": map_refs,
            "payload": {
                "packet_id": packet.packet_id,
                "phase1_mutation_id": packet.phase1_mutation_id,
                "safety_level": packet.safety_level.value,
                "event_type": packet.event_type.value,
                "selected_gate_id": packet.selected_gate_id,
                "transport_profiles": [
                    message.transport_profile for message in rendered_messages
                ],
                "policy_status": policy_decision.status,
                "sent": False,
                "boundary": packet.boundary.model_dump(mode="json"),
                "privacy": packet.privacy.model_dump(mode="json"),
                "data_quality": packet.data_quality.model_dump(mode="json"),
            },
        }
    ]


def run_alert_application_dry_run(
    mutation_result: Phase1MutationResult | dict[str, Any],
    *,
    output_dir: Path | str,
    route_name: str | None = None,
    party_count: int = 1,
    location_ref: str | None = None,
    operator_approval_phrase: str | None = None,
) -> AlertApplicationDryRunResult:
    output_root = Path(output_dir).expanduser()
    packet_ref = "alert_application_packet.json"
    sms_ref = "sms_message.txt"
    lora_ref = "lora_payload.json"
    mqtt_ref = "mqtt_payload.json"
    policy_ref = "outbound_policy_decision.json"
    evidence_ref = "outbound_message_evidence.json"
    result_ref = "alert_application_dry_run_result.json"
    packet = build_alert_packet_from_phase1_mutation(
        mutation_result,
        source_path=packet_ref,
        route_name=route_name,
        party_count=party_count,
        location_ref=location_ref,
    )
    sms = render_sms_text(packet, source_path=sms_ref)
    lora = render_lora_compact(packet, source_path=lora_ref)
    mqtt = render_mqtt_json(packet, source_path=mqtt_ref)
    rendered_messages = [sms, lora, mqtt]
    policy = decide_outbound_policy(
        packet,
        rendered_messages,
        operator_approval_phrase=operator_approval_phrase,
        source_path=policy_ref,
    )
    output_refs = [packet_ref, sms_ref, lora_ref, mqtt_ref, policy_ref, evidence_ref]
    evidence = build_outbound_message_evidence(
        packet,
        rendered_messages,
        policy,
        source_path=evidence_ref,
        output_refs=output_refs,
    )
    timeline_events = alert_application_projection_events(
        packet,
        rendered_messages,
        policy,
        sequence=0,
    )
    artifact_refs = [*output_refs, result_ref]
    digest = aggregate_sha256(
        [
            {
                "source_path": result_ref,
                "packet_sha256": packet.sha256,
                "rendered_sha256s": [message.sha256 for message in rendered_messages],
                "policy_sha256": policy.sha256,
                "evidence_sha256": evidence.sha256,
                "artifact_refs": artifact_refs,
            }
        ]
    )
    result = AlertApplicationDryRunResult(
        source_path=result_ref,
        sha256=digest,
        output_dir=str(output_root),
        packet=packet,
        rendered_messages=rendered_messages,
        policy_decision=policy,
        evidence=evidence,
        artifact_refs=artifact_refs,
        timeline_events=timeline_events,
        data_quality=AlertApplicationDataQuality(
            confidence=packet.data_quality.confidence,
            source_artifact_count=1,
            rendered_profile_count=len(rendered_messages),
            truncated_profile_count=sum(1 for message in rendered_messages if message.truncated),
            limitations=["macOS dry-run writes local evidence files only"],
        ),
        privacy=packet.privacy,
        boundary=packet.boundary,
    )
    output_root.mkdir(parents=True, exist_ok=True)
    _write_json(output_root / packet_ref, packet.model_dump(mode="json"))
    (output_root / sms_ref).write_text(sms.body_text or "", encoding="utf-8")
    _write_json(output_root / lora_ref, lora.model_dump(mode="json"))
    _write_json(output_root / mqtt_ref, mqtt.model_dump(mode="json"))
    _write_json(output_root / policy_ref, policy.model_dump(mode="json"))
    _write_json(output_root / evidence_ref, evidence.model_dump(mode="json"))
    _write_json(output_root / result_ref, result.model_dump(mode="json"))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scout alert application layer dry-run")
    subparsers = parser.add_subparsers(dest="command", required=True)
    dry_run = subparsers.add_parser("dry-run")
    dry_run.add_argument("--mutation-result", required=True)
    dry_run.add_argument("--output-dir", required=True)
    dry_run.add_argument("--route-name")
    dry_run.add_argument("--party-count", type=int, default=1)
    dry_run.add_argument("--location-ref")
    dry_run.add_argument("--operator-approval-phrase")
    call_out = subparsers.add_parser("call-out-dry-run")
    call_out.add_argument("--alert-dry-run-result", required=True)
    call_out.add_argument("--output-dir", required=True)
    call_out.add_argument(
        "--transport-profile",
        choices=["sms_text", "lora_compact", "mqtt_json"],
        default="sms_text",
    )
    call_out.add_argument(
        "--executor-kind",
        choices=["local_dry_run", "manual_handoff", "production_transport"],
        default="local_dry_run",
    )
    call_out.add_argument("--idempotency-key", default="emergency-call-out-dry-run")
    call_out.add_argument("--explicit-confirmation", action="store_true")
    call_out.add_argument("--operator-identity-ref")
    call_out.add_argument("--operator-authenticated", action="store_true")
    call_out.add_argument("--operator-approval-phrase")
    args = parser.parse_args(argv)
    if args.command == "dry-run":
        mutation = load_phase1_mutation_result(args.mutation_result)
        result = run_alert_application_dry_run(
            mutation,
            output_dir=args.output_dir,
            route_name=args.route_name,
            party_count=args.party_count,
            location_ref=args.location_ref,
            operator_approval_phrase=args.operator_approval_phrase,
        )
        print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "call-out-dry-run":
        alert_result = AlertApplicationDryRunResult.model_validate_json(
            Path(args.alert_dry_run_result).read_text(encoding="utf-8")
        )
        result = run_emergency_call_out_dry_run(
            alert_result,
            output_dir=args.output_dir,
            transport_profile=args.transport_profile,
            executor_kind=args.executor_kind,
            idempotency_key=args.idempotency_key,
            explicit_confirmation=args.explicit_confirmation,
            operator_identity_ref=args.operator_identity_ref,
            operator_authenticated=args.operator_authenticated,
            operator_approval_phrase=args.operator_approval_phrase,
        )
        print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    return 2


def _packet_model(packet: ScoutAlertPacket | dict[str, Any]) -> ScoutAlertPacket:
    return packet if isinstance(packet, ScoutAlertPacket) else ScoutAlertPacket.model_validate(packet)


def _message_model(
    message: RenderedAlertMessage | dict[str, Any],
) -> RenderedAlertMessage:
    return (
        message
        if isinstance(message, RenderedAlertMessage)
        else RenderedAlertMessage.model_validate(message)
    )


def _policy_model(
    policy_decision: OutboundPolicyDecision | dict[str, Any],
) -> OutboundPolicyDecision:
    return (
        policy_decision
        if isinstance(policy_decision, OutboundPolicyDecision)
        else OutboundPolicyDecision.model_validate(policy_decision)
    )


def _call_out_result_model(
    call_out_result: EmergencyCallOutExecutorResult | dict[str, Any],
) -> EmergencyCallOutExecutorResult:
    return (
        call_out_result
        if isinstance(call_out_result, EmergencyCallOutExecutorResult)
        else EmergencyCallOutExecutorResult.model_validate(call_out_result)
    )


def _call_out_admission_status(
    packet: ScoutAlertPacket,
    message: RenderedAlertMessage,
    policy: OutboundPolicyDecision,
    request: EmergencyCallOutRequest,
) -> tuple[EmergencyCallOutAdmissionStatus, list[str]]:
    packet_mismatch = (
        request.source_packet_id != packet.packet_id
        or request.source_packet_sha256 != packet.sha256
        or request.source_policy_sha256 != policy.sha256
        or request.rendered_message_sha256 != message.sha256
        or request.transport_profile != message.transport_profile
        or message.source_packet_id != packet.packet_id
        or message.source_packet_sha256 != packet.sha256
        or policy.source_packet_id != packet.packet_id
        or policy.source_packet_sha256 != packet.sha256
    )
    if packet_mismatch:
        return (
            "blocked_packet_mismatch",
            ["request, packet, policy, and rendered message hashes do not match"],
        )
    if not request.explicit_confirmation:
        return (
            "blocked_requires_explicit_confirmation",
            ["Emergency Call Out requires a consequence-labelled confirmation"],
        )
    if request.executor_kind == "production_transport":
        return (
            "blocked_production_executor_unavailable",
            [
                "no approved production transport executor is available",
                "verified delivery evidence cannot be produced by v0",
            ],
        )
    if request.executor_kind == "manual_handoff":
        if policy.status != "allowed_manual_copy" or not policy.manual_copy_allowed:
            return (
                "blocked_policy_not_allowed",
                ["manual handoff requires the outbound policy to allow manual copy"],
            )
        if (
            not request.operator_authenticated
            or not request.operator_identity_ref
            or request.operator_approval_phrase != ALERT_APPROVAL_PHRASE
        ):
            return (
                "blocked_requires_authenticated_approval",
                [
                    "manual handoff requires authenticated operator identity",
                    "the exact approval phrase must be bound at call-out time",
                ],
            )
        return (
            "admitted_manual_handoff",
            [
                "authenticated operator approved manual handoff",
                "Scout records an unverified handoff receipt only",
            ],
        )
    return (
        "admitted_local_dry_run",
        [
            "local Emergency Call Out dry-run admitted",
            "no network, hardware, external send, or verified delivery occurs",
        ],
    )


def _production_emergency_approval_status(
    packet: ScoutAlertPacket,
    message: RenderedAlertMessage,
    policy: OutboundPolicyDecision,
    call_out: EmergencyCallOutExecutorResult,
    request: ProductionEmergencyApprovalRequest,
) -> tuple[ProductionEmergencyApprovalStatus, list[str]]:
    mismatch = (
        request.source_packet_id != packet.packet_id
        or request.source_packet_sha256 != packet.sha256
        or request.source_policy_sha256 != policy.sha256
        or request.rendered_message_sha256 != message.sha256
        or request.call_out_admission_sha256 != call_out.admission.sha256
        or request.transport_profile != message.transport_profile
        or message.source_packet_id != packet.packet_id
        or message.source_packet_sha256 != packet.sha256
        or policy.source_packet_id != packet.packet_id
        or policy.source_packet_sha256 != packet.sha256
        or call_out.admission.source_packet_id != packet.packet_id
        or call_out.admission.source_packet_sha256 != packet.sha256
        or call_out.admission.source_policy_sha256 != policy.sha256
        or call_out.admission.rendered_message_sha256 != message.sha256
    )
    if mismatch:
        return (
            "blocked_packet_mismatch",
            ["approval request, packet, policy, rendered message, or call-out hashes do not match"],
        )
    if not call_out.admission.admitted:
        return (
            "blocked_call_out_not_admitted",
            ["Emergency Call Out admission is blocked and cannot enter production approval"],
        )
    if (
        not request.operator_authenticated
        or not request.operator_identity_ref
        or not request.operator_authentication_ref
        or not request.operator_authentication_sha256
    ):
        return (
            "blocked_requires_authenticated_operator",
            ["production approval requires authenticated operator identity evidence"],
        )
    if (
        not request.explicit_confirmation
        or request.operator_approval_phrase != ALERT_APPROVAL_PHRASE
    ):
        return (
            "blocked_requires_approval_phrase",
            ["production approval requires the exact consequence-labelled approval phrase"],
        )
    return (
        "authenticated_approval_recorded_pending_transport",
        [
            "authenticated operator approval preflight recorded",
            "production transport release and verified delivery remain unavailable",
        ],
    )


def _production_transport_release_status(
    approval: ProductionEmergencyApprovalDecision,
    request: ProductionTransportReleaseRequest,
) -> tuple[ProductionTransportReleaseStatus, list[str]]:
    mismatch = (
        request.production_approval_sha256 != approval.sha256
        or request.source_packet_sha256 != approval.source_packet_sha256
        or request.source_policy_sha256 != approval.source_policy_sha256
        or request.rendered_message_sha256 != approval.rendered_message_sha256
        or request.call_out_admission_sha256 != approval.call_out_admission_sha256
        or request.transport_profile != approval.transport_profile
    )
    if mismatch:
        return (
            "blocked_packet_mismatch",
            ["transport release request does not match approval lineage"],
        )
    if not (
        approval.operator_approval_recorded
        and approval.status == "authenticated_approval_recorded_pending_transport"
    ):
        return (
            "blocked_approval_preflight_not_recorded",
            ["authenticated approval preflight has not been recorded"],
        )
    if not request.production_gate_residency_audit_sha256:
        return (
            "blocked_missing_residency_audit",
            ["production gate residency audit evidence is missing"],
        )
    if request.production_gate_residency_status != "all_resident":
        return (
            "blocked_gate_residency_not_ready",
            [
                "all six runtime safety gates must be production-resident before release"
            ],
        )
    if not (
        request.effect_boundary_reviewed
        and request.runtime_authorization_ref
        and request.runtime_authorization_sha256
        and request.effect_boundary_ref
        and request.effect_boundary_sha256
    ):
        return (
            "blocked_runtime_boundary_not_reviewed",
            ["reviewed runtime authorization and effect boundary evidence is missing"],
        )
    if (
        not request.explicit_confirmation
        or request.operator_approval_phrase != ALERT_APPROVAL_PHRASE
    ):
        return (
            "blocked_requires_final_confirmation",
            ["transport release requires the exact consequence-labelled phrase"],
        )
    return (
        "released_for_approved_executor_selection",
        [
            "production approval completion recorded",
            "transport release is limited to approved executor selection",
        ],
    )


def _transport_selection_authority_models(
    production_approval: (
        ProductionEmergencyApprovalDecision
        | ProductionTransportReleaseDecision
        | dict[str, Any]
    ),
) -> tuple[ProductionEmergencyApprovalDecision | None, ProductionTransportReleaseDecision | None]:
    if isinstance(production_approval, ProductionTransportReleaseDecision):
        return None, production_approval
    if isinstance(production_approval, ProductionEmergencyApprovalDecision):
        return production_approval, None
    artifact_kind = str(production_approval.get("artifact_kind") or "")
    if artifact_kind == "scout_production_transport_release_decision":
        return None, ProductionTransportReleaseDecision.model_validate(
            production_approval
        )
    return ProductionEmergencyApprovalDecision.model_validate(production_approval), None


def _delivery_proof_present(report: ProductionDeliveryEvidenceReport) -> bool:
    return bool(
        report.transport_execution_ref
        and report.transport_execution_sha256
        and report.provider_delivery_evidence_ref
        and report.provider_delivery_evidence_sha256
        and report.provider_delivery_id_hash
        and report.verification_method_ref
        and report.verification_method_sha256
    )


def _transport_invocation_request_mismatch(
    release: ProductionTransportReleaseDecision,
    selection: ApprovedTransportExecutorSelectionDecision,
    request: ProductionTransportInvocationRequest,
) -> bool:
    return (
        selection.transport_release_sha256 != release.sha256
        or selection.production_approval_sha256 != release.source_approval_sha256
        or selection.source_packet_sha256 != release.source_packet_sha256
        or selection.rendered_message_sha256 != release.rendered_message_sha256
        or selection.transport_profile != release.transport_profile
        or request.production_approval_sha256 != release.source_approval_sha256
        or request.transport_release_sha256 != release.sha256
        or request.executor_selection_sha256 != selection.sha256
        or request.source_packet_sha256 != release.source_packet_sha256
        or request.rendered_message_sha256 != release.rendered_message_sha256
        or request.transport_profile != release.transport_profile
        or request.executor_id != selection.executor_id
        or request.executor_sha256 != selection.executor_sha256
    )


def _transport_invocation_matches_delivery_report(
    invocation: ProductionTransportInvocationReceipt,
    selection: ApprovedTransportExecutorSelectionDecision,
    report: ProductionDeliveryEvidenceReport,
) -> bool:
    return (
        invocation.status == "transport_invocation_authorized"
        and invocation.transport_invocation_authorized
        and invocation.executor_selection_sha256 == selection.sha256
        and invocation.transport_release_sha256 == selection.transport_release_sha256
        and invocation.production_approval_sha256 == selection.production_approval_sha256
        and invocation.source_packet_sha256 == selection.source_packet_sha256
        and invocation.rendered_message_sha256 == selection.rendered_message_sha256
        and invocation.transport_profile == selection.transport_profile
        and invocation.executor_id == selection.executor_id
        and invocation.executor_sha256 == selection.executor_sha256
        and report.transport_execution_ref == invocation.transport_execution_ref
        and report.transport_execution_sha256 == invocation.transport_execution_sha256
    )


def _transport_executor_effect_boundary_manifest_sha256(
    manifest: ProductionTransportExecutorEffectBoundaryManifest,
) -> str:
    return aggregate_sha256(
        [
            {
                key: value
                for key, value in manifest.model_dump(mode="json").items()
            }
        ]
    )


def _transport_executor_effect_boundary_lineage_matches(
    selection: ApprovedTransportExecutorSelectionDecision,
    invocation: ProductionTransportInvocationReceipt,
    manifest: ProductionTransportExecutorEffectBoundaryManifest,
) -> bool:
    return (
        selection.status == "ready_for_verified_transport_executor"
        and selection.transport_invocation_permitted
        and invocation.status == "transport_invocation_authorized"
        and invocation.transport_invocation_authorized
        and invocation.executor_selection_sha256 == selection.sha256
        and manifest.executor_selection_sha256 == selection.sha256
        and manifest.transport_invocation_sha256 == invocation.sha256
        and manifest.request_sha256 == invocation.request_sha256
        and manifest.production_approval_sha256 == invocation.production_approval_sha256
        and manifest.transport_release_sha256 == invocation.transport_release_sha256
        and manifest.source_packet_sha256 == invocation.source_packet_sha256
        and manifest.rendered_message_sha256 == invocation.rendered_message_sha256
        and manifest.transport_profile == invocation.transport_profile
        and manifest.executor_id == invocation.executor_id
        and manifest.executor_sha256 == invocation.executor_sha256
        and manifest.executor_id == selection.executor_id
        and manifest.executor_sha256 == selection.executor_sha256
        and manifest.transport_execution_ref == invocation.transport_execution_ref
        and manifest.transport_execution_sha256 == invocation.transport_execution_sha256
    )


def _transport_executor_execution_matches_invocation(
    readiness: ProductionTransportExecutorEffectBoundaryReadinessDecision,
    invocation: ProductionTransportInvocationReceipt,
) -> bool:
    return (
        readiness.transport_invocation_sha256 == invocation.sha256
        and readiness.request_sha256 == invocation.request_sha256
        and readiness.production_approval_sha256 == invocation.production_approval_sha256
        and readiness.transport_release_sha256 == invocation.transport_release_sha256
        and readiness.source_packet_sha256 == invocation.source_packet_sha256
        and readiness.rendered_message_sha256 == invocation.rendered_message_sha256
        and readiness.transport_profile == invocation.transport_profile
        and readiness.executor_id == invocation.executor_id
        and readiness.executor_sha256 == invocation.executor_sha256
        and readiness.transport_execution_ref == invocation.transport_execution_ref
        and readiness.transport_execution_sha256 == invocation.transport_execution_sha256
    )


def _transport_executor_execution_request_sha256(
    request: ProductionTransportExecutorExecutionRequest,
) -> str:
    return aggregate_sha256(
        [
            {
                "artifact": request.artifact_kind,
                "payload": request.model_dump(mode="json"),
                "safety_api_called": False,
                "phase1_l0_l4_state_mutated": False,
                "runtime_safety_truth_mutated": False,
            }
        ]
    )


def _transport_executor_result_matches_request(
    request: ProductionTransportExecutorExecutionRequest,
    result: ProductionTransportExecutorExecutionResult,
) -> bool:
    return (
        result.transport_invocation_sha256 == request.transport_invocation_sha256
        and result.request_sha256 == request.request_sha256
        and result.production_approval_sha256 == request.production_approval_sha256
        and result.transport_release_sha256 == request.transport_release_sha256
        and result.executor_selection_sha256 == request.executor_selection_sha256
        and result.source_packet_sha256 == request.source_packet_sha256
        and result.rendered_message_sha256 == request.rendered_message_sha256
        and result.transport_profile == request.transport_profile
        and result.executor_id == request.executor_id
        and result.executor_sha256 == request.executor_sha256
        and result.transport_execution_ref == request.transport_execution_ref
        and result.transport_execution_sha256 == request.transport_execution_sha256
    )


def _transport_effect_receipt_sha256(receipt: ProductionTransportEffectReceipt) -> str:
    return aggregate_sha256(
        [
            {
                key: value
                for key, value in receipt.model_dump(mode="json").items()
                if key != "sha256"
            }
        ]
    )


def _delivery_report_sha256(report: ProductionDeliveryEvidenceReport) -> str:
    return aggregate_sha256(
        [
            {
                key: value
                for key, value in report.model_dump(mode="json").items()
                if key != "sha256"
            }
        ]
    )


def _transport_effect_receipt_matches_invocation(
    invocation: ProductionTransportInvocationReceipt,
    receipt: ProductionTransportEffectReceipt,
) -> bool:
    return (
        receipt.transport_invocation_sha256 == invocation.sha256
        and receipt.request_sha256 == invocation.request_sha256
        and receipt.production_approval_sha256 == invocation.production_approval_sha256
        and receipt.transport_release_sha256 == invocation.transport_release_sha256
        and receipt.executor_selection_sha256 == invocation.executor_selection_sha256
        and receipt.source_packet_sha256 == invocation.source_packet_sha256
        and receipt.rendered_message_sha256 == invocation.rendered_message_sha256
        and receipt.transport_profile == invocation.transport_profile
        and receipt.executor_id == invocation.executor_id
        and receipt.executor_sha256 == invocation.executor_sha256
        and receipt.transport_execution_ref == invocation.transport_execution_ref
        and receipt.transport_execution_sha256 == invocation.transport_execution_sha256
    )


def _transport_effect_delivery_evidence_present(
    receipt: ProductionTransportEffectReceipt,
) -> bool:
    return bool(
        receipt.provider_delivery_evidence_ref
        and receipt.provider_delivery_evidence_sha256
        and receipt.provider_delivery_id_hash
        and receipt.verification_method_ref
        and receipt.verification_method_sha256
    )


def _production_delivery_verification_status(
    selection: ApprovedTransportExecutorSelectionDecision,
    report: ProductionDeliveryEvidenceReport,
    invocation: ProductionTransportInvocationReceipt | None = None,
) -> tuple[ProductionDeliveryVerificationStatus, list[str], bool]:
    evidence_present = _delivery_proof_present(report)
    if not (
        selection.status == "ready_for_verified_transport_executor"
        and selection.transport_invocation_permitted
        and selection.transport_release_sha256
    ):
        return (
            "blocked_transport_selection_not_ready",
            ["approved transport executor selection is not ready"],
            evidence_present,
        )
    mismatch = (
        report.executor_selection_sha256 != selection.sha256
        or report.production_approval_sha256 != selection.production_approval_sha256
        or report.transport_release_sha256 != selection.transport_release_sha256
        or report.source_packet_sha256 != selection.source_packet_sha256
        or report.rendered_message_sha256 != selection.rendered_message_sha256
        or report.transport_profile != selection.transport_profile
        or report.executor_id != selection.executor_id
        or report.executor_sha256 != selection.executor_sha256
    )
    if mismatch:
        return (
            "blocked_delivery_lineage_mismatch",
            ["delivery report does not match transport selection lineage"],
            evidence_present,
        )
    if invocation is not None and not _transport_invocation_matches_delivery_report(
        invocation,
        selection,
        report,
    ):
        return (
            "blocked_delivery_lineage_mismatch",
            ["delivery report does not match transport invocation receipt"],
            evidence_present,
        )
    if not evidence_present:
        return (
            "blocked_missing_delivery_proof",
            ["delivery report is missing execution, provider, or verification refs"],
            evidence_present,
        )
    if not (
        report.delivery_status == "delivered"
        and report.delivery_confirmation_observed
    ):
        return (
            "blocked_delivery_not_verified",
            ["provider evidence did not prove delivered status"],
            evidence_present,
        )
    return (
        "verified_delivery_evidence_accepted",
        ["verified delivery evidence accepted from approved executor lineage"],
        evidence_present,
    )


def _production_emergency_workflow_completion_status(
    release: ProductionTransportReleaseDecision,
    selection: ApprovedTransportExecutorSelectionDecision,
    verification: ProductionDeliveryVerificationDecision,
) -> tuple[ProductionEmergencyWorkflowCompletionStatus, list[str]]:
    mismatch = (
        selection.production_approval_sha256 != release.source_approval_sha256
        or selection.transport_release_sha256 != release.sha256
        or selection.source_packet_sha256 != release.source_packet_sha256
        or selection.rendered_message_sha256 != release.rendered_message_sha256
        or verification.executor_selection_sha256 != selection.sha256
        or verification.transport_release_sha256 != release.sha256
        or verification.source_packet_sha256 != release.source_packet_sha256
        or verification.rendered_message_sha256 != release.rendered_message_sha256
    )
    if mismatch or not (
        release.production_approval_complete
        and release.transport_release_authorized
    ):
        return (
            "blocked_transport_release_missing",
            ["transport release lineage is missing, blocked, or mismatched"],
        )
    if not (
        selection.status == "ready_for_verified_transport_executor"
        and selection.transport_invocation_permitted
    ):
        return (
            "blocked_transport_executor_not_ready",
            ["approved transport executor selection is not ready"],
        )
    if not verification.production_delivery_verified:
        return (
            "blocked_verified_delivery_missing",
            ["verified delivery evidence has not been accepted"],
        )
    return (
        "workflow_completed_verified_delivery",
        ["production emergency workflow closure verified from delivery evidence"],
    )


def _call_out_attempt_id(request_sha256: str, admission_sha256: str) -> str:
    digest = aggregate_sha256(
        [{"request_sha256": request_sha256, "admission_sha256": admission_sha256}]
    )
    return f"emergency_call_out_attempt.{digest[:16]}"


def _call_out_receipt_id(attempt_sha256: str) -> str:
    digest = aggregate_sha256([{"attempt_sha256": attempt_sha256}])
    return f"emergency_call_out_receipt.{digest[:16]}"


def _packet_id(result: Phase1MutationResult) -> str:
    digest = aggregate_sha256(
        [
            {
                "mutation_id": result.mutation_id,
                "mutation_sha256": result.sha256,
                "safety_level": result.resulting_safety_level.value,
            }
        ]
    )
    return f"scout_alert_packet.{digest[:16]}"


def _evidence_id(
    packet: ScoutAlertPacket,
    rendered_messages: list[RenderedAlertMessage],
    policy_decision: OutboundPolicyDecision,
) -> str:
    digest = aggregate_sha256(
        [
            {
                "packet_sha256": packet.sha256,
                "rendered_sha256s": [message.sha256 for message in rendered_messages],
                "policy_sha256": policy_decision.sha256,
            }
        ]
    )
    return f"outbound_message_evidence.{digest[:16]}"


def _condition_summary(result: Phase1MutationResult) -> str:
    gate = result.safety_event.details.get("selected_gate_id") or "runtime_safety_gate"
    return f"{gate} raised {result.resulting_safety_level.value}: {result.safety_event.reason}"


def _default_requested_action(level: SafetyLevel) -> str:
    if level == SafetyLevel.EMERGENCY:
        return "prepare emergency alert review and contact local emergency services if operator confirms"
    if level == SafetyLevel.DISTRESS:
        return "stop, review retreat or emergency camp, and prepare alert draft"
    if level == SafetyLevel.CONCERN:
        return "stop and rest before continuing"
    if level == SafetyLevel.WATCH:
        return "slow down and monitor"
    return "continue monitoring"


def _severity_label(level: SafetyLevel) -> Literal["info", "watch", "warning", "critical"]:
    if level == SafetyLevel.NORMAL:
        return "info"
    if level == SafetyLevel.WATCH:
        return "watch"
    if level == SafetyLevel.CONCERN:
        return "warning"
    return "critical"


def _render_sha(
    packet: ScoutAlertPacket,
    source_path: str,
    profile: AlertTransportProfile,
    payload: dict[str, Any],
) -> str:
    return aggregate_sha256(
        [
            {
                "packet_sha256": packet.sha256,
                "source_path": source_path,
                "transport_profile": profile,
                "payload": payload,
            }
        ]
    )


def _label(name: str, value: str | None) -> str | None:
    return f"{name} {value}" if value else None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _unique(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    output: list[str] = []
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text and text not in output:
            output.append(text)
    return output


def _short_action(action: str) -> str:
    text = action.lower()
    if "emergency" in text:
        return "emergency_review"
    if "retreat" in text:
        return "retreat_review"
    if "rest" in text:
        return "rest"
    if "monitor" in text:
        return "monitor"
    return "review"


def _short_level(level: SafetyLevel) -> str:
    return {
        SafetyLevel.NORMAL: "L0",
        SafetyLevel.WATCH: "L1",
        SafetyLevel.CONCERN: "L2",
        SafetyLevel.DISTRESS: "L3",
        SafetyLevel.EMERGENCY: "L4",
    }[level]


def _topic_token(value: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in value)


def _compact_json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        _strip_none(payload),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _pretty_json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _strip_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_none(child)
            for key, child in value.items()
            if child not in (None, "", [])
        }
    if isinstance(value, list):
        return [_strip_none(child) for child in value if child not in (None, "", [])]
    return value


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(path)


def _raise_forbidden_fields(value: Any, prefix: str = "") -> None:
    paths = _forbidden_key_paths(value, prefix)
    if paths:
        raise ValueError("forbidden alert application fields present: " + ", ".join(paths))


def _forbidden_key_paths(value: Any, prefix: str = "") -> list[str]:
    if isinstance(value, dict):
        paths: list[str] = []
        for key, child in value.items():
            child_path = f"{prefix}.{key}" if prefix else str(key)
            lower_key = str(key).lower()
            if lower_key == "timestamp" and isinstance(child, str) and child.startswith("offset:"):
                pass
            elif lower_key in FORBIDDEN_RAW_KEYS:
                paths.append(child_path)
            paths.extend(_forbidden_key_paths(child, child_path))
        return paths
    if isinstance(value, list):
        paths: list[str] = []
        for index, child in enumerate(value):
            paths.extend(_forbidden_key_paths(child, f"{prefix}[{index}]"))
        return paths
    return []


if __name__ == "__main__":
    raise SystemExit(main())
