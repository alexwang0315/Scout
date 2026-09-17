from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scout_energy_models import aggregate_sha256, sha256_file


ProductionSafetyQualificationArea = Literal[
    "live_provider_api",
    "connector_health_endpoint",
    "credential_access_path",
    "resident_freshness_attestor",
    "field_device_validator",
    "phase1_writer_deployment",
    "transport_client",
    "outbound_delivery",
    "pi_hardware",
]
ProductionSafetyQualificationReceiptStatus = Literal[
    "qualified",
    "failed",
    "blocked",
    "unknown",
]
ProductionSafetyCutoverReadinessStatus = Literal[
    "blocked_missing_required_qualification",
    "blocked_failed_required_qualification",
    "ready_for_production_cutover",
]
ProductionSafetyQualificationClaimId = Literal[
    "capability_observed",
    "production_environment_verified",
    "lineage_verified",
    "fail_closed_behavior_verified",
    "rollback_or_fallback_verified",
    "provider_api_execution_observed",
    "provider_response_sanitized",
    "provider_request_lineage_verified",
    "connector_health_endpoint_observed",
    "connector_degraded_fail_closed",
    "credential_ref_resolved_without_value",
    "credential_scope_and_rotation_verified",
    "freshness_attestor_resident_observed",
    "freshness_window_enforced",
    "stale_source_rejected",
    "field_device_observation_observed",
    "device_or_field_evidence_bound",
    "disputed_validation_rejected",
    "phase1_writer_runtime_deployed",
    "guarded_writer_invocation_verified",
    "production_write_boundary_reviewed",
    "transport_client_execution_observed",
    "transport_credential_ref_only",
    "transport_delivery_verifier_bound",
    "approved_outbound_send_observed",
    "delivery_confirmation_verified",
    "gateway_ack_rejected_as_insufficient",
    "pi_runtime_observed",
    "pi_device_identity_verified",
    "pi_hardware_fail_closed_verified",
]
ProductionSafetyQualificationReceiptAdmissionStatus = Literal[
    "qualification_receipt_accepted",
    "blocked_missing_required_claims",
    "blocked_rejected_required_claims",
    "blocked_stale_required_claims",
    "blocked_source_integrity_unverified",
]
ProductionSafetyQualificationSourceIntegrityRowStatus = Literal[
    "verified",
    "missing",
    "hash_mismatch",
    "unsafe_path",
    "sensitive_material",
]
ProductionSafetyQualificationSourceIntegrityStatus = Literal[
    "source_integrity_verified",
    "blocked_source_integrity_failed",
]
ProductionSafetyQualificationDossierRowStatus = Literal[
    "qualified",
    "missing_entry",
    "missing_paths",
    "load_failed",
    "source_integrity_failed",
    "admission_failed",
]
ProductionSafetyQualificationDossierStatus = Literal[
    "dossier_ready_for_production_cutover",
    "blocked_dossier_incomplete",
    "blocked_dossier_failed",
]
ProductionSafetyQualificationThreatId = Literal[
    "hallucination",
    "agent_runaway",
    "prompt_injection",
    "malicious_mcp_results",
    "stale_candidates",
    "authority_escalation",
    "accidental_action",
    "local_cloud_inconsistency",
]
ProductionSafetyQualificationModeId = Literal[
    "functional",
    "schema",
    "tool_use",
    "workspace",
    "authority_boundary",
    "latency",
    "memory",
    "failure_mode",
    "offline",
    "regression",
    "adversarial",
    "missing_evidence",
    "contradiction",
    "stale_state",
    "human_review",
]
ProductionSafetyQualificationCoverageItemType = Literal[
    "threat",
    "qualification_mode",
]
ProductionSafetyQualificationThreatCoverageRowStatus = Literal[
    "covered",
    "missing",
    "failed",
    "stale",
    "unverified_source",
]
ProductionSafetyQualificationThreatCoverageStatus = Literal[
    "qualification_threat_coverage_passed",
    "blocked_missing_qualification_coverage",
    "blocked_failed_qualification_coverage",
    "blocked_stale_qualification_coverage",
    "blocked_source_integrity_unverified",
]
ProductionSafetyQualificationDossierThreatCoverageStatus = (
    ProductionSafetyQualificationThreatCoverageStatus | Literal["missing", "load_failed"]
)
ProductionSafetyQualificationGapKind = Literal[
    "area_qualification",
    "threat_coverage",
    "qualification_mode_coverage",
    "threat_source_integrity",
    "dossier",
]
ProductionSafetyQualificationGapAction = Literal[
    "provide_area_bundle_and_source_package",
    "repair_area_source_integrity",
    "repair_area_claim_admission",
    "provide_threat_coverage_manifest_and_source_package",
    "repair_threat_coverage_source_integrity",
    "repair_threat_or_mode_coverage",
    "refresh_stale_coverage_evidence",
    "rerun_dossier_after_evidence_update",
]
ProductionSafetyQualificationGapStatus = Literal[
    "open",
    "resolved",
]
ProductionSafetyQualificationGapPlanStatus = Literal[
    "production_qualification_gaps_resolved",
    "blocked_production_qualification_gaps_open",
]
ProductionSafetyQualificationEvidenceRequestKind = Literal[
    "area_evidence_bundle",
    "area_source_package",
    "threat_coverage_manifest",
    "threat_coverage_source_package",
    "threat_coverage_case",
    "qualification_mode_case",
    "dossier_rerun",
]
ProductionSafetyQualificationEvidenceRequestPackStatus = Literal[
    "evidence_request_pack_ready",
    "no_evidence_requests_required",
]
ProductionSafetyQualificationEvidenceRequestFulfillmentRowStatus = Literal[
    "fulfilled",
    "missing",
    "mismatched",
    "rejected",
    "source_unverified",
]
ProductionSafetyQualificationEvidenceRequestFulfillmentStatus = Literal[
    "evidence_request_fulfillment_verified",
    "blocked_missing_requested_evidence",
    "blocked_mismatched_requested_evidence",
    "blocked_rejected_requested_evidence",
    "blocked_fulfillment_source_integrity_unverified",
]
ProductionSafetyQualificationEvidenceFulfillmentSourceIntegrityRowStatus = Literal[
    "verified",
    "missing",
    "hash_mismatch",
    "unsafe_path",
    "sensitive_material",
    "unrequested",
]
ProductionSafetyQualificationEvidenceFulfillmentSourceIntegrityStatus = Literal[
    "fulfillment_source_integrity_verified",
    "blocked_fulfillment_source_integrity_failed",
]
ProductionSafetyQualificationRemediationRowStatus = Literal[
    "ready_for_dossier_rerun",
    "blocked_request_pack_mismatch",
    "blocked_missing_requested_evidence",
    "blocked_mismatched_requested_evidence",
    "blocked_rejected_requested_evidence",
    "blocked_fulfillment_source_integrity_unverified",
]
ProductionSafetyQualificationRemediationStatus = Literal[
    "no_remediation_required",
    "ready_for_dossier_rerun",
    "blocked_remediation_incomplete",
]
ProductionSafetyQualificationExternalActionKind = Literal[
    "provider_api_qualification",
    "connector_health_qualification",
    "credential_access_review",
    "freshness_attestor_qualification",
    "field_device_validation",
    "phase1_writer_deployment_verification",
    "transport_client_qualification",
    "delivery_verification",
    "pi_hardware_validation",
    "threat_coverage_review",
    "threat_coverage_source_integrity_review",
    "qualification_mode_review",
    "dossier_rerun",
]
ProductionSafetyQualificationExternalActionRowStatus = Literal[
    "ready_for_operator_authorization",
    "blocked_remediation_incomplete",
]
ProductionSafetyQualificationExternalActionPacketStatus = Literal[
    "no_external_actions_required",
    "external_actions_ready_for_operator_authorization",
    "blocked_external_actions_incomplete",
]
ProductionSafetyQualificationExternalAuthorizationRowStatus = Literal[
    "authorization_recorded",
    "missing_authorization",
    "mismatched_authorization",
    "rejected_authorization",
    "expired_authorization",
    "blocked_packet_incomplete",
]
ProductionSafetyQualificationExternalAuthorizationReportStatus = Literal[
    "no_external_authorization_required",
    "external_authorization_recorded",
    "blocked_external_authorization_incomplete",
]
ProductionSafetyQualificationExternalInvocationRowStatus = Literal[
    "invocation_handoff_recorded",
    "missing_invocation_request",
    "mismatched_invocation_request",
    "missing_operator_confirmation",
    "rejected_invocation_request",
    "blocked_authorization_incomplete",
]
ProductionSafetyQualificationExternalInvocationReportStatus = Literal[
    "no_external_invocation_required",
    "external_invocation_handoff_recorded",
    "blocked_external_invocation_incomplete",
]
ProductionSafetyQualificationExternalResultRowStatus = Literal[
    "result_receipt_recorded",
    "missing_result_receipt",
    "mismatched_result_receipt",
    "rejected_result_receipt",
    "unverified_result_source",
    "blocked_invocation_incomplete",
]
ProductionSafetyQualificationExternalResultReportStatus = Literal[
    "no_external_result_required",
    "external_results_recorded",
    "blocked_external_results_incomplete",
]
ProductionSafetyQualificationExternalResultEvidenceBridgeRowStatus = Literal[
    "bridged_to_fulfillment_submission",
    "missing_result_for_request",
    "mismatched_result_artifact",
    "blocked_result_not_ready",
]
ProductionSafetyQualificationExternalResultEvidenceBridgeStatus = Literal[
    "no_external_result_bridge_required",
    "external_result_bridge_ready",
    "blocked_external_result_bridge_incomplete",
]
ProductionSafetyQualificationExternalResultRemediationClosureStatus = Literal[
    "no_external_result_remediation_required",
    "external_result_remediation_ready_for_dossier_rerun",
    "blocked_external_result_bridge_incomplete",
    "blocked_external_result_source_package_missing",
    "blocked_external_result_source_integrity_failed",
    "blocked_external_result_fulfillment_incomplete",
    "blocked_external_result_remediation_incomplete",
]
ProductionSafetyQualificationDossierRerunStatus = Literal[
    "no_dossier_rerun_required",
    "dossier_rerun_ready_for_cutover_review",
    "blocked_external_result_remediation_incomplete",
    "blocked_dossier_rerun_incomplete",
    "blocked_dossier_rerun_failed",
]
ProductionSafetyQualificationCutoverAuthorizationStatus = Literal[
    "cutover_authorization_recorded",
    "blocked_dossier_rerun_not_ready",
    "missing_cutover_authorization",
    "mismatched_cutover_authorization",
    "rejected_cutover_authorization",
    "expired_cutover_authorization",
]
ProductionSafetyQualificationCutoverReleaseHandoffStatus = Literal[
    "cutover_release_handoff_recorded",
    "blocked_cutover_authorization_incomplete",
    "missing_cutover_release_request",
    "mismatched_cutover_release_request",
    "rejected_cutover_release_request",
    "missing_operator_confirmation",
]
ProductionSafetyQualificationCutoverReleaseEffectStatus = Literal[
    "cutover_release_effect_receipt_recorded",
    "blocked_cutover_release_handoff_incomplete",
    "missing_cutover_release_effect_receipt",
    "mismatched_cutover_release_effect_receipt",
    "rejected_cutover_release_effect_receipt",
    "unverified_cutover_release_effect_source",
]
ProductionSafetyQualificationCutoverReleaseClosureStatus = Literal[
    "cutover_release_closure_recorded",
    "blocked_cutover_release_effect_incomplete",
    "missing_cutover_release_closure_review",
    "mismatched_cutover_release_closure_review",
    "rejected_cutover_release_closure_review",
    "unverified_cutover_release_closure_source",
    "expired_cutover_release_closure_review",
    "missing_release_closure_confirmation",
]

REQUIRED_PRODUCTION_SAFETY_QUALIFICATION_AREAS: tuple[
    ProductionSafetyQualificationArea,
    ...,
] = (
    "live_provider_api",
    "connector_health_endpoint",
    "credential_access_path",
    "resident_freshness_attestor",
    "field_device_validator",
    "phase1_writer_deployment",
    "transport_client",
    "outbound_delivery",
    "pi_hardware",
)
PRODUCTION_SAFETY_QUALIFICATION_AREA_EXTERNAL_ACTION_KINDS: dict[
    ProductionSafetyQualificationArea,
    ProductionSafetyQualificationExternalActionKind,
] = {
    "live_provider_api": "provider_api_qualification",
    "connector_health_endpoint": "connector_health_qualification",
    "credential_access_path": "credential_access_review",
    "resident_freshness_attestor": "freshness_attestor_qualification",
    "field_device_validator": "field_device_validation",
    "phase1_writer_deployment": "phase1_writer_deployment_verification",
    "transport_client": "transport_client_qualification",
    "outbound_delivery": "delivery_verification",
    "pi_hardware": "pi_hardware_validation",
}
COMMON_PRODUCTION_SAFETY_QUALIFICATION_CLAIMS: tuple[
    ProductionSafetyQualificationClaimId,
    ...,
] = (
    "capability_observed",
    "production_environment_verified",
    "lineage_verified",
    "fail_closed_behavior_verified",
    "rollback_or_fallback_verified",
)
PRODUCTION_SAFETY_QUALIFICATION_REQUIRED_CLAIMS: dict[
    ProductionSafetyQualificationArea,
    tuple[ProductionSafetyQualificationClaimId, ...],
] = {
    "live_provider_api": (
        *COMMON_PRODUCTION_SAFETY_QUALIFICATION_CLAIMS,
        "provider_api_execution_observed",
        "provider_response_sanitized",
        "provider_request_lineage_verified",
        "credential_ref_resolved_without_value",
    ),
    "connector_health_endpoint": (
        *COMMON_PRODUCTION_SAFETY_QUALIFICATION_CLAIMS,
        "connector_health_endpoint_observed",
        "connector_degraded_fail_closed",
        "credential_ref_resolved_without_value",
    ),
    "credential_access_path": (
        *COMMON_PRODUCTION_SAFETY_QUALIFICATION_CLAIMS,
        "credential_ref_resolved_without_value",
        "credential_scope_and_rotation_verified",
    ),
    "resident_freshness_attestor": (
        *COMMON_PRODUCTION_SAFETY_QUALIFICATION_CLAIMS,
        "freshness_attestor_resident_observed",
        "freshness_window_enforced",
        "stale_source_rejected",
    ),
    "field_device_validator": (
        *COMMON_PRODUCTION_SAFETY_QUALIFICATION_CLAIMS,
        "field_device_observation_observed",
        "device_or_field_evidence_bound",
        "disputed_validation_rejected",
    ),
    "phase1_writer_deployment": (
        *COMMON_PRODUCTION_SAFETY_QUALIFICATION_CLAIMS,
        "phase1_writer_runtime_deployed",
        "guarded_writer_invocation_verified",
        "production_write_boundary_reviewed",
    ),
    "transport_client": (
        *COMMON_PRODUCTION_SAFETY_QUALIFICATION_CLAIMS,
        "transport_client_execution_observed",
        "transport_credential_ref_only",
        "transport_delivery_verifier_bound",
    ),
    "outbound_delivery": (
        *COMMON_PRODUCTION_SAFETY_QUALIFICATION_CLAIMS,
        "approved_outbound_send_observed",
        "delivery_confirmation_verified",
        "gateway_ack_rejected_as_insufficient",
    ),
    "pi_hardware": (
        *COMMON_PRODUCTION_SAFETY_QUALIFICATION_CLAIMS,
        "pi_runtime_observed",
        "pi_device_identity_verified",
        "pi_hardware_fail_closed_verified",
    ),
}
REQUIRED_PRODUCTION_SAFETY_THREAT_COVERAGE: tuple[
    ProductionSafetyQualificationThreatId,
    ...,
] = (
    "hallucination",
    "agent_runaway",
    "prompt_injection",
    "malicious_mcp_results",
    "stale_candidates",
    "authority_escalation",
    "accidental_action",
    "local_cloud_inconsistency",
)
REQUIRED_PRODUCTION_SAFETY_QUALIFICATION_MODES: tuple[
    ProductionSafetyQualificationModeId,
    ...,
] = (
    "functional",
    "schema",
    "tool_use",
    "workspace",
    "authority_boundary",
    "latency",
    "memory",
    "failure_mode",
    "offline",
    "regression",
    "adversarial",
    "missing_evidence",
    "contradiction",
    "stale_state",
    "human_review",
)
_QUALIFICATION_REF_PREFIXES = (
    "prod://",
    "provider://",
    "cwa://",
    "attestation://",
    "field://",
    "device://",
    "operator://",
    "transport://",
    "pi://",
    "deployment://",
    "secret://",
    "vault://",
    "kms://",
    "keychain://",
    "envref://",
)
PRODUCTION_SAFETY_CUTOVER_REVIEW_CONFIRMATION = (
    "AUTHORIZE SCOUT PRODUCTION CUTOVER REVIEW"
)
PRODUCTION_SAFETY_CUTOVER_RELEASE_HANDOFF_CONFIRMATION = (
    "REQUEST SCOUT PRODUCTION CUTOVER HANDOFF"
)
PRODUCTION_SAFETY_CUTOVER_RELEASE_CLOSURE_CONFIRMATION = (
    "CLOSE SCOUT PRODUCTION CUTOVER RELEASE REVIEW"
)


class ProductionSafetyQualificationBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deterministic_audit_only: bool = True
    external_call_performed_by_audit: bool = False
    credential_material_loaded_by_audit: bool = False
    raw_payload_loaded_by_audit: bool = False
    production_database_mutated_by_audit: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    runtime_safety_truth_mutated: bool = False
    outbound_transport_invoked_by_audit: bool = False
    hardware_control_performed_by_audit: bool = False

    @model_validator(mode="after")
    def enforce_qualification_audit_boundary(
        self,
    ) -> "ProductionSafetyQualificationBoundary":
        if not self.deterministic_audit_only:
            raise ValueError("production qualification audit must be deterministic")
        if (
            self.external_call_performed_by_audit
            or self.credential_material_loaded_by_audit
            or self.raw_payload_loaded_by_audit
            or self.production_database_mutated_by_audit
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
            or self.runtime_safety_truth_mutated
            or self.outbound_transport_invoked_by_audit
            or self.hardware_control_performed_by_audit
        ):
            raise ValueError("production qualification audit cannot perform effects")
        return self


class ProductionSafetyQualificationReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_safety_qualification_receipt"
    artifact_version: str = "production_safety_qualification_receipt.v0"
    area: ProductionSafetyQualificationArea
    source_provider: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    sha256: str | None = None
    status: ProductionSafetyQualificationReceiptStatus = "unknown"
    qualification_ref: str | None = None
    qualification_sha256: str | None = None
    reviewed_effect_boundary_ref: str | None = None
    reviewed_effect_boundary_sha256: str | None = None
    operator_review_ref: str | None = None
    operator_review_sha256: str | None = None
    capability_observed: bool = False
    production_environment_verified: bool = False
    lineage_verified: bool = False
    fail_closed_behavior_verified: bool = False
    rollback_or_fallback_verified: bool = False
    credential_material_embedded: bool = False
    raw_payload_embedded: bool = False
    safety_api_called_by_qualifier: bool = False
    phase1_l0_l4_state_mutated_by_qualifier: bool = False
    runtime_safety_truth_mutated_by_qualifier: bool = False
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_qualification_receipt(
        self,
    ) -> "ProductionSafetyQualificationReceipt":
        for field_name, value in (
            ("source_path", self.source_path),
            ("qualification_ref", self.qualification_ref),
            ("reviewed_effect_boundary_ref", self.reviewed_effect_boundary_ref),
            ("operator_review_ref", self.operator_review_ref),
        ):
            if value is not None:
                _assert_qualification_ref(field_name, value)
        for ref_name, ref_value, sha_name, sha_value in (
            (
                "qualification_ref",
                self.qualification_ref,
                "qualification_sha256",
                self.qualification_sha256,
            ),
            (
                "reviewed_effect_boundary_ref",
                self.reviewed_effect_boundary_ref,
                "reviewed_effect_boundary_sha256",
                self.reviewed_effect_boundary_sha256,
            ),
            (
                "operator_review_ref",
                self.operator_review_ref,
                "operator_review_sha256",
                self.operator_review_sha256,
            ),
        ):
            if (ref_value is None) != (sha_value is None):
                raise ValueError(f"{ref_name} and {sha_name} must be paired")
        if self.credential_material_embedded or self.raw_payload_embedded:
            raise ValueError("qualification receipt cannot embed credentials or raw payloads")
        if (
            self.safety_api_called_by_qualifier
            or self.phase1_l0_l4_state_mutated_by_qualifier
            or self.runtime_safety_truth_mutated_by_qualifier
        ):
            raise ValueError("qualification receipt cannot mutate safety runtime")
        if self.status == "qualified" and not (
            self.qualification_ref
            and self.qualification_sha256
            and self.reviewed_effect_boundary_ref
            and self.reviewed_effect_boundary_sha256
            and self.operator_review_ref
            and self.operator_review_sha256
            and self.capability_observed
            and self.production_environment_verified
            and self.lineage_verified
            and self.fail_closed_behavior_verified
            and self.rollback_or_fallback_verified
        ):
            raise ValueError("qualified receipt requires complete reviewed evidence")
        return self


class ProductionSafetyQualificationEvidenceClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_safety_qualification_evidence_claim"
    artifact_version: str = "production_safety_qualification_evidence_claim.v0"
    claim_id: ProductionSafetyQualificationClaimId
    evidence_ref: str = Field(min_length=1)
    evidence_sha256: str = Field(min_length=1)
    evidence_observed_at: datetime
    reviewer_ref: str | None = None
    reviewer_sha256: str | None = None
    reviewer_observed_at: datetime
    max_age_seconds: int = Field(gt=0)
    accepted: bool = False
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_evidence_claim(
        self,
    ) -> "ProductionSafetyQualificationEvidenceClaim":
        _assert_qualification_ref("evidence_ref", self.evidence_ref)
        if (self.reviewer_ref is None) != (self.reviewer_sha256 is None):
            raise ValueError("reviewer_ref and reviewer_sha256 must be paired")
        if self.reviewer_ref is not None:
            _assert_qualification_ref("reviewer_ref", self.reviewer_ref)
        if _as_utc(self.reviewer_observed_at) < _as_utc(self.evidence_observed_at):
            raise ValueError("reviewer_observed_at cannot be before evidence_observed_at")
        return self


class ProductionSafetyQualificationEvidenceBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_safety_qualification_evidence_bundle"
    artifact_version: str = "production_safety_qualification_evidence_bundle.v0"
    area: ProductionSafetyQualificationArea
    source_provider: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    reference_time: datetime
    qualification_ref: str | None = None
    qualification_sha256: str | None = None
    reviewed_effect_boundary_ref: str | None = None
    reviewed_effect_boundary_sha256: str | None = None
    operator_review_ref: str | None = None
    operator_review_sha256: str | None = None
    claims: list[ProductionSafetyQualificationEvidenceClaim] = Field(default_factory=list)
    credential_material_embedded: bool = False
    raw_payload_embedded: bool = False
    external_call_performed_by_admission: bool = False
    credential_material_loaded_by_admission: bool = False
    raw_payload_loaded_by_admission: bool = False
    production_database_mutated_by_admission: bool = False
    safety_api_called_by_admission: bool = False
    phase1_l0_l4_state_mutated_by_admission: bool = False
    runtime_safety_truth_mutated_by_admission: bool = False
    outbound_transport_invoked_by_admission: bool = False
    hardware_control_performed_by_admission: bool = False
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_evidence_bundle(
        self,
    ) -> "ProductionSafetyQualificationEvidenceBundle":
        _assert_qualification_ref("source_path", self.source_path)
        for ref_name, ref_value, sha_name, sha_value in (
            (
                "qualification_ref",
                self.qualification_ref,
                "qualification_sha256",
                self.qualification_sha256,
            ),
            (
                "reviewed_effect_boundary_ref",
                self.reviewed_effect_boundary_ref,
                "reviewed_effect_boundary_sha256",
                self.reviewed_effect_boundary_sha256,
            ),
            (
                "operator_review_ref",
                self.operator_review_ref,
                "operator_review_sha256",
                self.operator_review_sha256,
            ),
        ):
            if (ref_value is None) != (sha_value is None):
                raise ValueError(f"{ref_name} and {sha_name} must be paired")
            if ref_value is not None:
                _assert_qualification_ref(ref_name, ref_value)
        claim_ids = [claim.claim_id for claim in self.claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("qualification evidence bundle claim ids must be unique")
        for claim in self.claims:
            if _as_utc(claim.evidence_observed_at) > _as_utc(self.reference_time):
                raise ValueError("claim evidence_observed_at cannot be after reference_time")
            if _as_utc(claim.reviewer_observed_at) > _as_utc(self.reference_time):
                raise ValueError("claim reviewer_observed_at cannot be after reference_time")
        if self.credential_material_embedded or self.raw_payload_embedded:
            raise ValueError("qualification bundle cannot embed credentials or raw payloads")
        if (
            self.external_call_performed_by_admission
            or self.credential_material_loaded_by_admission
            or self.raw_payload_loaded_by_admission
            or self.production_database_mutated_by_admission
            or self.safety_api_called_by_admission
            or self.phase1_l0_l4_state_mutated_by_admission
            or self.runtime_safety_truth_mutated_by_admission
            or self.outbound_transport_invoked_by_admission
            or self.hardware_control_performed_by_admission
        ):
            raise ValueError("qualification bundle admission cannot perform effects")
        return self


class ProductionSafetyQualificationReceiptAdmissionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_safety_qualification_receipt_admission"
    artifact_version: str = "production_safety_qualification_receipt_admission.v0"
    source_provider: str = "scout_runtime_safety_production_qualification"
    source_path: str
    sha256: str
    area: ProductionSafetyQualificationArea
    status: ProductionSafetyQualificationReceiptAdmissionStatus
    required_claims: list[ProductionSafetyQualificationClaimId]
    accepted_claims: list[ProductionSafetyQualificationClaimId]
    missing_claims: list[ProductionSafetyQualificationClaimId] = Field(
        default_factory=list
    )
    rejected_claims: list[ProductionSafetyQualificationClaimId] = Field(
        default_factory=list
    )
    stale_claims: list[ProductionSafetyQualificationClaimId] = Field(
        default_factory=list
    )
    unverified_source_claims: list[ProductionSafetyQualificationClaimId] = Field(
        default_factory=list
    )
    missing_required_refs: list[str] = Field(default_factory=list)
    source_integrity_report_ref: str | None = None
    source_integrity_report_sha256: str | None = None
    source_integrity_verified: bool = False
    receipt: ProductionSafetyQualificationReceipt
    ready_for_cutover_receipt: bool = False
    external_call_performed_by_admission: bool = False
    credential_material_loaded_by_admission: bool = False
    raw_payload_loaded_by_admission: bool = False
    production_database_mutated_by_admission: bool = False
    safety_api_called_by_admission: bool = False
    phase1_l0_l4_state_mutated_by_admission: bool = False
    runtime_safety_truth_mutated_by_admission: bool = False
    outbound_transport_invoked_by_admission: bool = False
    hardware_control_performed_by_admission: bool = False
    boundary: ProductionSafetyQualificationBoundary = Field(
        default_factory=ProductionSafetyQualificationBoundary
    )

    @model_validator(mode="after")
    def enforce_receipt_admission(
        self,
    ) -> "ProductionSafetyQualificationReceiptAdmissionDecision":
        ready = self.status == "qualification_receipt_accepted"
        if self.ready_for_cutover_receipt != ready:
            raise ValueError("ready_for_cutover_receipt must match status")
        if ready and (
            self.missing_claims
            or self.rejected_claims
            or self.stale_claims
            or self.unverified_source_claims
            or self.missing_required_refs
            or not self.source_integrity_verified
            or self.receipt.status != "qualified"
        ):
            raise ValueError("accepted receipt admission cannot contain blockers")
        if (self.source_integrity_report_ref is None) != (
            self.source_integrity_report_sha256 is None
        ):
            raise ValueError(
                "source_integrity_report_ref and source_integrity_report_sha256 must be paired"
            )
        if self.source_integrity_report_ref is not None:
            _assert_qualification_ref(
                "source_integrity_report_ref",
                self.source_integrity_report_ref,
            )
        if (
            self.external_call_performed_by_admission
            or self.credential_material_loaded_by_admission
            or self.raw_payload_loaded_by_admission
            or self.production_database_mutated_by_admission
            or self.safety_api_called_by_admission
            or self.phase1_l0_l4_state_mutated_by_admission
            or self.runtime_safety_truth_mutated_by_admission
            or self.outbound_transport_invoked_by_admission
            or self.hardware_control_performed_by_admission
        ):
            raise ValueError("qualification receipt admission cannot perform effects")
        return self


class ProductionSafetyQualificationEvidenceArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_safety_qualification_evidence_artifact"
    artifact_version: str = "production_safety_qualification_evidence_artifact.v0"
    evidence_ref: str = Field(min_length=1)
    evidence_sha256: str = Field(min_length=1)
    local_path: str = Field(min_length=1)
    media_type: str = "application/json"
    redacted_or_sanitized: bool = True
    credential_material_present: bool = False
    raw_payload_present: bool = False
    safety_api_path_present: bool = False
    runtime_safety_truth_present: bool = False
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_evidence_artifact(
        self,
    ) -> "ProductionSafetyQualificationEvidenceArtifact":
        _assert_qualification_ref("evidence_ref", self.evidence_ref)
        return self


class ProductionSafetyQualificationEvidencePackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_safety_qualification_evidence_package"
    artifact_version: str = "production_safety_qualification_evidence_package.v0"
    area: ProductionSafetyQualificationArea
    source_provider: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    artifacts: list[ProductionSafetyQualificationEvidenceArtifact] = Field(
        default_factory=list
    )
    credential_material_embedded: bool = False
    raw_payload_embedded: bool = False
    external_call_performed_by_verifier: bool = False
    credential_material_loaded_by_verifier: bool = False
    raw_payload_loaded_by_verifier: bool = False
    production_database_mutated_by_verifier: bool = False
    safety_api_called_by_verifier: bool = False
    phase1_l0_l4_state_mutated_by_verifier: bool = False
    runtime_safety_truth_mutated_by_verifier: bool = False
    outbound_transport_invoked_by_verifier: bool = False
    hardware_control_performed_by_verifier: bool = False
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_evidence_package(
        self,
    ) -> "ProductionSafetyQualificationEvidencePackage":
        _assert_qualification_ref("source_path", self.source_path)
        artifact_refs = [artifact.evidence_ref for artifact in self.artifacts]
        if len(artifact_refs) != len(set(artifact_refs)):
            raise ValueError("qualification evidence package refs must be unique")
        if self.credential_material_embedded or self.raw_payload_embedded:
            raise ValueError("qualification evidence package cannot embed sensitive data")
        if (
            self.external_call_performed_by_verifier
            or self.credential_material_loaded_by_verifier
            or self.raw_payload_loaded_by_verifier
            or self.production_database_mutated_by_verifier
            or self.safety_api_called_by_verifier
            or self.phase1_l0_l4_state_mutated_by_verifier
            or self.runtime_safety_truth_mutated_by_verifier
            or self.outbound_transport_invoked_by_verifier
            or self.hardware_control_performed_by_verifier
        ):
            raise ValueError("qualification evidence verifier cannot perform effects")
        return self


class ProductionSafetyQualificationSourceIntegrityRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: ProductionSafetyQualificationClaimId
    evidence_ref: str
    expected_sha256: str
    actual_sha256: str | None = None
    local_path: str | None = None
    status: ProductionSafetyQualificationSourceIntegrityRowStatus
    source_integrity_verified: bool = False
    blockers: list[str] = Field(default_factory=list)


class ProductionSafetyQualificationSourceIntegrityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_safety_qualification_source_integrity_report"
    artifact_version: str = "production_safety_qualification_source_integrity_report.v0"
    source_provider: str = "scout_runtime_safety_production_qualification"
    source_path: str
    sha256: str
    area: ProductionSafetyQualificationArea
    bundle_ref: str
    package_ref: str
    status: ProductionSafetyQualificationSourceIntegrityStatus
    rows: list[ProductionSafetyQualificationSourceIntegrityRow]
    verified_evidence_refs: list[str] = Field(default_factory=list)
    missing_evidence_refs: list[str] = Field(default_factory=list)
    mismatched_evidence_refs: list[str] = Field(default_factory=list)
    unsafe_evidence_refs: list[str] = Field(default_factory=list)
    sensitive_evidence_refs: list[str] = Field(default_factory=list)
    all_claim_sources_verified: bool = False
    external_call_performed_by_verifier: bool = False
    credential_material_loaded_by_verifier: bool = False
    raw_payload_loaded_by_verifier: bool = False
    production_database_mutated_by_verifier: bool = False
    safety_api_called_by_verifier: bool = False
    phase1_l0_l4_state_mutated_by_verifier: bool = False
    runtime_safety_truth_mutated_by_verifier: bool = False
    outbound_transport_invoked_by_verifier: bool = False
    hardware_control_performed_by_verifier: bool = False
    boundary: ProductionSafetyQualificationBoundary = Field(
        default_factory=ProductionSafetyQualificationBoundary
    )

    @model_validator(mode="after")
    def enforce_source_integrity_report(
        self,
    ) -> "ProductionSafetyQualificationSourceIntegrityReport":
        verified = self.status == "source_integrity_verified"
        if self.all_claim_sources_verified != verified:
            raise ValueError("all_claim_sources_verified must match status")
        if verified and any(not row.source_integrity_verified for row in self.rows):
            raise ValueError("verified source integrity requires every row verified")
        if (
            self.external_call_performed_by_verifier
            or self.credential_material_loaded_by_verifier
            or self.raw_payload_loaded_by_verifier
            or self.production_database_mutated_by_verifier
            or self.safety_api_called_by_verifier
            or self.phase1_l0_l4_state_mutated_by_verifier
            or self.runtime_safety_truth_mutated_by_verifier
            or self.outbound_transport_invoked_by_verifier
            or self.hardware_control_performed_by_verifier
        ):
            raise ValueError("qualification source integrity report cannot perform effects")
        return self


class ProductionSafetyQualificationThreatCoverageCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_safety_qualification_threat_case"
    artifact_version: str = "production_safety_qualification_threat_case.v0"
    threat_id: ProductionSafetyQualificationThreatId
    evidence_ref: str = Field(min_length=1)
    evidence_sha256: str = Field(min_length=1)
    evidence_observed_at: datetime
    reviewer_ref: str = Field(min_length=1)
    reviewer_sha256: str = Field(min_length=1)
    reviewer_observed_at: datetime
    max_age_seconds: int = Field(gt=0)
    mitigated: bool = False
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_threat_coverage_case(
        self,
    ) -> "ProductionSafetyQualificationThreatCoverageCase":
        _assert_qualification_ref("evidence_ref", self.evidence_ref)
        _assert_qualification_ref("reviewer_ref", self.reviewer_ref)
        if _as_utc(self.reviewer_observed_at) < _as_utc(self.evidence_observed_at):
            raise ValueError("reviewer_observed_at cannot be before evidence_observed_at")
        return self


class ProductionSafetyQualificationModeCoverageCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_safety_qualification_mode_case"
    artifact_version: str = "production_safety_qualification_mode_case.v0"
    mode_id: ProductionSafetyQualificationModeId
    evidence_ref: str = Field(min_length=1)
    evidence_sha256: str = Field(min_length=1)
    evidence_observed_at: datetime
    reviewer_ref: str = Field(min_length=1)
    reviewer_sha256: str = Field(min_length=1)
    reviewer_observed_at: datetime
    max_age_seconds: int = Field(gt=0)
    passed: bool = False
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_mode_coverage_case(
        self,
    ) -> "ProductionSafetyQualificationModeCoverageCase":
        _assert_qualification_ref("evidence_ref", self.evidence_ref)
        _assert_qualification_ref("reviewer_ref", self.reviewer_ref)
        if _as_utc(self.reviewer_observed_at) < _as_utc(self.evidence_observed_at):
            raise ValueError("reviewer_observed_at cannot be before evidence_observed_at")
        return self


class ProductionSafetyQualificationThreatCoverageManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_safety_qualification_threat_manifest"
    artifact_version: str = "production_safety_qualification_threat_manifest.v0"
    source_provider: str = "scout_runtime_safety_production_qualification"
    source_path: str
    reference_time: datetime
    threat_cases: list[ProductionSafetyQualificationThreatCoverageCase] = Field(
        default_factory=list
    )
    qualification_modes: list[ProductionSafetyQualificationModeCoverageCase] = Field(
        default_factory=list
    )
    external_call_performed_by_threat_audit: bool = False
    credential_material_loaded_by_threat_audit: bool = False
    raw_payload_loaded_by_threat_audit: bool = False
    production_database_mutated_by_threat_audit: bool = False
    safety_api_called_by_threat_audit: bool = False
    phase1_l0_l4_state_mutated_by_threat_audit: bool = False
    runtime_safety_truth_mutated_by_threat_audit: bool = False
    outbound_transport_invoked_by_threat_audit: bool = False
    hardware_control_performed_by_threat_audit: bool = False
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_threat_coverage_manifest(
        self,
    ) -> "ProductionSafetyQualificationThreatCoverageManifest":
        _assert_qualification_ref("source_path", self.source_path)
        threat_ids = [case.threat_id for case in self.threat_cases]
        if len(threat_ids) != len(set(threat_ids)):
            raise ValueError("threat coverage cases must be unique by threat_id")
        mode_ids = [case.mode_id for case in self.qualification_modes]
        if len(mode_ids) != len(set(mode_ids)):
            raise ValueError("qualification mode cases must be unique by mode_id")
        reference = _as_utc(self.reference_time)
        for case in [*self.threat_cases, *self.qualification_modes]:
            if _as_utc(case.evidence_observed_at) > reference:
                raise ValueError("coverage evidence_observed_at cannot be after reference_time")
            if _as_utc(case.reviewer_observed_at) > reference:
                raise ValueError("coverage reviewer_observed_at cannot be after reference_time")
        if (
            self.external_call_performed_by_threat_audit
            or self.credential_material_loaded_by_threat_audit
            or self.raw_payload_loaded_by_threat_audit
            or self.production_database_mutated_by_threat_audit
            or self.safety_api_called_by_threat_audit
            or self.phase1_l0_l4_state_mutated_by_threat_audit
            or self.runtime_safety_truth_mutated_by_threat_audit
            or self.outbound_transport_invoked_by_threat_audit
            or self.hardware_control_performed_by_threat_audit
        ):
            raise ValueError("qualification threat coverage audit cannot perform effects")
        return self


class ProductionSafetyQualificationThreatCoverageEvidencePackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = (
        "scout_production_safety_qualification_threat_evidence_package"
    )
    artifact_version: str = (
        "production_safety_qualification_threat_evidence_package.v0"
    )
    source_provider: str = "scout_runtime_safety_production_qualification"
    source_path: str
    artifacts: list[ProductionSafetyQualificationEvidenceArtifact] = Field(
        default_factory=list
    )
    credential_material_embedded: bool = False
    raw_payload_embedded: bool = False
    external_call_performed_by_verifier: bool = False
    credential_material_loaded_by_verifier: bool = False
    raw_payload_loaded_by_verifier: bool = False
    production_database_mutated_by_verifier: bool = False
    safety_api_called_by_verifier: bool = False
    phase1_l0_l4_state_mutated_by_verifier: bool = False
    runtime_safety_truth_mutated_by_verifier: bool = False
    outbound_transport_invoked_by_verifier: bool = False
    hardware_control_performed_by_verifier: bool = False
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_threat_evidence_package(
        self,
    ) -> "ProductionSafetyQualificationThreatCoverageEvidencePackage":
        _assert_qualification_ref("source_path", self.source_path)
        artifact_refs = [artifact.evidence_ref for artifact in self.artifacts]
        if len(artifact_refs) != len(set(artifact_refs)):
            raise ValueError("threat coverage evidence package refs must be unique")
        if self.credential_material_embedded or self.raw_payload_embedded:
            raise ValueError(
                "threat coverage evidence package cannot embed sensitive data"
            )
        if (
            self.external_call_performed_by_verifier
            or self.credential_material_loaded_by_verifier
            or self.raw_payload_loaded_by_verifier
            or self.production_database_mutated_by_verifier
            or self.safety_api_called_by_verifier
            or self.phase1_l0_l4_state_mutated_by_verifier
            or self.runtime_safety_truth_mutated_by_verifier
            or self.outbound_transport_invoked_by_verifier
            or self.hardware_control_performed_by_verifier
        ):
            raise ValueError("threat coverage evidence verifier cannot perform effects")
        return self


class ProductionSafetyQualificationThreatCoverageSourceIntegrityRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    coverage_type: ProductionSafetyQualificationCoverageItemType
    threat_id: ProductionSafetyQualificationThreatId | None = None
    mode_id: ProductionSafetyQualificationModeId | None = None
    evidence_ref: str
    expected_sha256: str
    actual_sha256: str | None = None
    local_path: str | None = None
    status: ProductionSafetyQualificationSourceIntegrityRowStatus
    source_integrity_verified: bool = False
    blockers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_threat_source_integrity_row(
        self,
    ) -> "ProductionSafetyQualificationThreatCoverageSourceIntegrityRow":
        if self.coverage_type == "threat" and self.threat_id is None:
            raise ValueError("threat source-integrity row requires threat_id")
        if self.coverage_type == "qualification_mode" and self.mode_id is None:
            raise ValueError("mode source-integrity row requires mode_id")
        return self


class ProductionSafetyQualificationThreatCoverageSourceIntegrityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = (
        "scout_production_safety_qualification_threat_source_integrity_report"
    )
    artifact_version: str = (
        "production_safety_qualification_threat_source_integrity_report.v0"
    )
    source_provider: str = "scout_runtime_safety_production_qualification"
    source_path: str
    sha256: str
    manifest_ref: str
    package_ref: str
    status: ProductionSafetyQualificationSourceIntegrityStatus
    rows: list[ProductionSafetyQualificationThreatCoverageSourceIntegrityRow]
    verified_evidence_refs: list[str] = Field(default_factory=list)
    missing_evidence_refs: list[str] = Field(default_factory=list)
    mismatched_evidence_refs: list[str] = Field(default_factory=list)
    unsafe_evidence_refs: list[str] = Field(default_factory=list)
    sensitive_evidence_refs: list[str] = Field(default_factory=list)
    all_coverage_sources_verified: bool = False
    external_call_performed_by_verifier: bool = False
    credential_material_loaded_by_verifier: bool = False
    raw_payload_loaded_by_verifier: bool = False
    production_database_mutated_by_verifier: bool = False
    safety_api_called_by_verifier: bool = False
    phase1_l0_l4_state_mutated_by_verifier: bool = False
    runtime_safety_truth_mutated_by_verifier: bool = False
    outbound_transport_invoked_by_verifier: bool = False
    hardware_control_performed_by_verifier: bool = False
    boundary: ProductionSafetyQualificationBoundary = Field(
        default_factory=ProductionSafetyQualificationBoundary
    )

    @model_validator(mode="after")
    def enforce_threat_source_integrity_report(
        self,
    ) -> "ProductionSafetyQualificationThreatCoverageSourceIntegrityReport":
        verified = self.status == "source_integrity_verified"
        if self.all_coverage_sources_verified != verified:
            raise ValueError("all_coverage_sources_verified must match status")
        if verified and any(not row.source_integrity_verified for row in self.rows):
            raise ValueError("verified threat source integrity requires every row")
        if (
            self.external_call_performed_by_verifier
            or self.credential_material_loaded_by_verifier
            or self.raw_payload_loaded_by_verifier
            or self.production_database_mutated_by_verifier
            or self.safety_api_called_by_verifier
            or self.phase1_l0_l4_state_mutated_by_verifier
            or self.runtime_safety_truth_mutated_by_verifier
            or self.outbound_transport_invoked_by_verifier
            or self.hardware_control_performed_by_verifier
        ):
            raise ValueError(
                "qualification threat source integrity report cannot perform effects"
            )
        return self


class ProductionSafetyQualificationThreatCoverageRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    coverage_type: ProductionSafetyQualificationCoverageItemType
    status: ProductionSafetyQualificationThreatCoverageRowStatus
    threat_id: ProductionSafetyQualificationThreatId | None = None
    mode_id: ProductionSafetyQualificationModeId | None = None
    evidence_ref: str | None = None
    evidence_sha256: str | None = None
    reviewer_ref: str | None = None
    reviewer_sha256: str | None = None
    ready_for_production_qualification: bool = False
    blockers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_threat_coverage_row(
        self,
    ) -> "ProductionSafetyQualificationThreatCoverageRow":
        if self.coverage_type == "threat" and self.threat_id is None:
            raise ValueError("threat coverage row requires threat_id")
        if self.coverage_type == "qualification_mode" and self.mode_id is None:
            raise ValueError("qualification mode row requires mode_id")
        ready = self.status == "covered"
        if self.ready_for_production_qualification != ready:
            raise ValueError("ready_for_production_qualification must match status")
        return self


class ProductionSafetyQualificationThreatCoverageAudit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_safety_qualification_threat_audit"
    artifact_version: str = "production_safety_qualification_threat_audit.v0"
    source_provider: str = "scout_runtime_safety_production_qualification"
    source_path: str
    sha256: str
    status: ProductionSafetyQualificationThreatCoverageStatus
    required_threats: list[ProductionSafetyQualificationThreatId]
    required_qualification_modes: list[ProductionSafetyQualificationModeId]
    rows: list[ProductionSafetyQualificationThreatCoverageRow]
    missing_threats: list[ProductionSafetyQualificationThreatId] = Field(
        default_factory=list
    )
    failed_threats: list[ProductionSafetyQualificationThreatId] = Field(
        default_factory=list
    )
    stale_threats: list[ProductionSafetyQualificationThreatId] = Field(
        default_factory=list
    )
    missing_qualification_modes: list[ProductionSafetyQualificationModeId] = Field(
        default_factory=list
    )
    failed_qualification_modes: list[ProductionSafetyQualificationModeId] = Field(
        default_factory=list
    )
    stale_qualification_modes: list[ProductionSafetyQualificationModeId] = Field(
        default_factory=list
    )
    unverified_source_threats: list[ProductionSafetyQualificationThreatId] = Field(
        default_factory=list
    )
    unverified_source_qualification_modes: list[
        ProductionSafetyQualificationModeId
    ] = Field(default_factory=list)
    source_integrity_report_ref: str | None = None
    source_integrity_report_sha256: str | None = None
    source_integrity_verified: bool = False
    threat_model_covered: bool = False
    qualification_modes_covered: bool = False
    ready_for_production_cutover_threat_coverage: bool = False
    external_call_performed_by_threat_audit: bool = False
    credential_material_loaded_by_threat_audit: bool = False
    raw_payload_loaded_by_threat_audit: bool = False
    production_database_mutated_by_threat_audit: bool = False
    safety_api_called_by_threat_audit: bool = False
    phase1_l0_l4_state_mutated_by_threat_audit: bool = False
    runtime_safety_truth_mutated_by_threat_audit: bool = False
    outbound_transport_invoked_by_threat_audit: bool = False
    hardware_control_performed_by_threat_audit: bool = False
    limitations: list[str] = Field(default_factory=list)
    boundary: ProductionSafetyQualificationBoundary = Field(
        default_factory=ProductionSafetyQualificationBoundary
    )

    @model_validator(mode="after")
    def enforce_threat_coverage_audit(
        self,
    ) -> "ProductionSafetyQualificationThreatCoverageAudit":
        ready = self.status == "qualification_threat_coverage_passed"
        if self.ready_for_production_cutover_threat_coverage != ready:
            raise ValueError("ready_for_production_cutover_threat_coverage must match status")
        if ready and (
            self.missing_threats
            or self.failed_threats
            or self.stale_threats
            or self.unverified_source_threats
            or self.missing_qualification_modes
            or self.failed_qualification_modes
            or self.stale_qualification_modes
            or self.unverified_source_qualification_modes
            or not self.threat_model_covered
            or not self.qualification_modes_covered
            or not self.source_integrity_verified
            or any(not row.ready_for_production_qualification for row in self.rows)
        ):
            raise ValueError("ready threat coverage audit cannot contain blockers")
        if (self.source_integrity_report_ref is None) != (
            self.source_integrity_report_sha256 is None
        ):
            raise ValueError(
                "source_integrity_report_ref and source_integrity_report_sha256 must be paired"
            )
        if self.source_integrity_report_ref is not None:
            _assert_qualification_ref(
                "source_integrity_report_ref",
                self.source_integrity_report_ref,
            )
        if (
            self.external_call_performed_by_threat_audit
            or self.credential_material_loaded_by_threat_audit
            or self.raw_payload_loaded_by_threat_audit
            or self.production_database_mutated_by_threat_audit
            or self.safety_api_called_by_threat_audit
            or self.phase1_l0_l4_state_mutated_by_threat_audit
            or self.runtime_safety_truth_mutated_by_threat_audit
            or self.outbound_transport_invoked_by_threat_audit
            or self.hardware_control_performed_by_threat_audit
        ):
            raise ValueError("qualification threat coverage audit cannot perform effects")
        return self


class ProductionSafetyQualificationDossierEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    area: ProductionSafetyQualificationArea
    bundle_path: str | None = None
    source_package_path: str | None = None


class ProductionSafetyQualificationDossierManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_safety_qualification_dossier_manifest"
    artifact_version: str = "production_safety_qualification_dossier_manifest.v0"
    source_provider: str = "scout_runtime_safety_production_qualification"
    source_path: str
    source_root_path: str | None = None
    threat_coverage_path: str | None = None
    threat_coverage_source_package_path: str | None = None
    entries: list[ProductionSafetyQualificationDossierEntry] = Field(
        default_factory=list
    )
    external_call_performed_by_dossier: bool = False
    credential_material_loaded_by_dossier: bool = False
    raw_payload_loaded_by_dossier: bool = False
    production_database_mutated_by_dossier: bool = False
    safety_api_called_by_dossier: bool = False
    phase1_l0_l4_state_mutated_by_dossier: bool = False
    runtime_safety_truth_mutated_by_dossier: bool = False
    outbound_transport_invoked_by_dossier: bool = False
    hardware_control_performed_by_dossier: bool = False

    @model_validator(mode="after")
    def enforce_dossier_manifest(
        self,
    ) -> "ProductionSafetyQualificationDossierManifest":
        _assert_qualification_ref("source_path", self.source_path)
        entry_areas = [entry.area for entry in self.entries]
        if len(entry_areas) != len(set(entry_areas)):
            raise ValueError("qualification dossier entries must be unique by area")
        if (
            self.external_call_performed_by_dossier
            or self.credential_material_loaded_by_dossier
            or self.raw_payload_loaded_by_dossier
            or self.production_database_mutated_by_dossier
            or self.safety_api_called_by_dossier
            or self.phase1_l0_l4_state_mutated_by_dossier
            or self.runtime_safety_truth_mutated_by_dossier
            or self.outbound_transport_invoked_by_dossier
            or self.hardware_control_performed_by_dossier
        ):
            raise ValueError("qualification dossier runner cannot perform effects")
        return self


class ProductionSafetyQualificationDossierRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    area: ProductionSafetyQualificationArea
    status: ProductionSafetyQualificationDossierRowStatus
    bundle_path: str | None = None
    source_package_path: str | None = None
    source_integrity_status: ProductionSafetyQualificationSourceIntegrityStatus | None = None
    admission_status: ProductionSafetyQualificationReceiptAdmissionStatus | None = None
    receipt_sha256: str | None = None
    qualified_for_cutover: bool = False
    blockers: list[str] = Field(default_factory=list)


class ProductionSafetyQualificationDossierReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_safety_qualification_dossier_report"
    artifact_version: str = "production_safety_qualification_dossier_report.v0"
    source_provider: str = "scout_runtime_safety_production_qualification"
    source_path: str
    sha256: str
    status: ProductionSafetyQualificationDossierStatus
    evaluation_time: datetime | None = None
    required_areas: list[ProductionSafetyQualificationArea]
    rows: list[ProductionSafetyQualificationDossierRow]
    cutover_audit: ProductionSafetyCutoverReadinessAudit
    threat_coverage_audit: ProductionSafetyQualificationThreatCoverageAudit | None = None
    threat_coverage_status: ProductionSafetyQualificationDossierThreatCoverageStatus = (
        "missing"
    )
    threat_coverage_ready: bool = False
    ready_for_production_cutover: bool = False
    missing_areas: list[ProductionSafetyQualificationArea] = Field(default_factory=list)
    failed_areas: list[ProductionSafetyQualificationArea] = Field(default_factory=list)
    dossier_blockers: list[str] = Field(default_factory=list)
    external_call_performed_by_dossier: bool = False
    credential_material_loaded_by_dossier: bool = False
    raw_payload_loaded_by_dossier: bool = False
    production_database_mutated_by_dossier: bool = False
    safety_api_called_by_dossier: bool = False
    phase1_l0_l4_state_mutated_by_dossier: bool = False
    runtime_safety_truth_mutated_by_dossier: bool = False
    outbound_transport_invoked_by_dossier: bool = False
    hardware_control_performed_by_dossier: bool = False
    boundary: ProductionSafetyQualificationBoundary = Field(
        default_factory=ProductionSafetyQualificationBoundary
    )

    @model_validator(mode="after")
    def enforce_dossier_report(
        self,
    ) -> "ProductionSafetyQualificationDossierReport":
        if self.evaluation_time is not None and self.evaluation_time.utcoffset() is None:
            raise ValueError("dossier evaluation_time must be timezone-aware")
        ready = self.status == "dossier_ready_for_production_cutover"
        if self.ready_for_production_cutover != ready:
            raise ValueError("ready_for_production_cutover must match dossier status")
        if ready and (
            self.missing_areas
            or self.failed_areas
            or self.dossier_blockers
            or not self.cutover_audit.ready_for_production_cutover
            or self.threat_coverage_audit is None
            or not self.threat_coverage_ready
            or any(not row.qualified_for_cutover for row in self.rows)
        ):
            raise ValueError("ready dossier report cannot contain blockers")
        if (
            self.external_call_performed_by_dossier
            or self.credential_material_loaded_by_dossier
            or self.raw_payload_loaded_by_dossier
            or self.production_database_mutated_by_dossier
            or self.safety_api_called_by_dossier
            or self.phase1_l0_l4_state_mutated_by_dossier
            or self.runtime_safety_truth_mutated_by_dossier
            or self.outbound_transport_invoked_by_dossier
            or self.hardware_control_performed_by_dossier
        ):
            raise ValueError("qualification dossier report cannot perform effects")
        return self


class ProductionSafetyQualificationGapRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gap_kind: ProductionSafetyQualificationGapKind
    action: ProductionSafetyQualificationGapAction
    status: ProductionSafetyQualificationGapStatus = "open"
    area: ProductionSafetyQualificationArea | None = None
    threat_id: ProductionSafetyQualificationThreatId | None = None
    mode_id: ProductionSafetyQualificationModeId | None = None
    source_status: str | None = None
    blockers: list[str] = Field(default_factory=list)
    required_artifacts: list[str] = Field(default_factory=list)
    unblock_condition: str = Field(min_length=1)

    @model_validator(mode="after")
    def enforce_gap_row(self) -> "ProductionSafetyQualificationGapRow":
        if self.gap_kind == "area_qualification" and self.area is None:
            raise ValueError("area qualification gap requires area")
        if self.gap_kind == "threat_coverage" and self.threat_id is None:
            raise ValueError("threat coverage gap requires threat_id")
        if self.gap_kind == "qualification_mode_coverage" and self.mode_id is None:
            raise ValueError("qualification mode coverage gap requires mode_id")
        if self.status == "open" and not self.blockers:
            raise ValueError("open qualification gap row requires blockers")
        return self


class ProductionSafetyQualificationGapPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_safety_qualification_gap_plan"
    artifact_version: str = "production_safety_qualification_gap_plan.v0"
    source_provider: str = "scout_runtime_safety_production_qualification"
    source_path: str
    sha256: str
    status: ProductionSafetyQualificationGapPlanStatus
    dossier_report_ref: str
    dossier_report_sha256: str
    ready_for_production_cutover: bool = False
    open_gap_count: int = 0
    rows: list[ProductionSafetyQualificationGapRow] = Field(default_factory=list)
    external_call_performed_by_gap_plan: bool = False
    credential_material_loaded_by_gap_plan: bool = False
    raw_payload_loaded_by_gap_plan: bool = False
    production_database_mutated_by_gap_plan: bool = False
    safety_api_called_by_gap_plan: bool = False
    phase1_l0_l4_state_mutated_by_gap_plan: bool = False
    runtime_safety_truth_mutated_by_gap_plan: bool = False
    outbound_transport_invoked_by_gap_plan: bool = False
    hardware_control_performed_by_gap_plan: bool = False
    limitations: list[str] = Field(default_factory=list)
    boundary: ProductionSafetyQualificationBoundary = Field(
        default_factory=ProductionSafetyQualificationBoundary
    )

    @model_validator(mode="after")
    def enforce_gap_plan(self) -> "ProductionSafetyQualificationGapPlan":
        ready = self.status == "production_qualification_gaps_resolved"
        if self.ready_for_production_cutover != ready:
            raise ValueError("ready_for_production_cutover must match gap plan status")
        if self.open_gap_count != len([row for row in self.rows if row.status == "open"]):
            raise ValueError("open_gap_count must match open rows")
        if ready and (self.rows or self.open_gap_count):
            raise ValueError("resolved gap plan cannot contain open rows")
        if (
            self.external_call_performed_by_gap_plan
            or self.credential_material_loaded_by_gap_plan
            or self.raw_payload_loaded_by_gap_plan
            or self.production_database_mutated_by_gap_plan
            or self.safety_api_called_by_gap_plan
            or self.phase1_l0_l4_state_mutated_by_gap_plan
            or self.runtime_safety_truth_mutated_by_gap_plan
            or self.outbound_transport_invoked_by_gap_plan
            or self.hardware_control_performed_by_gap_plan
        ):
            raise ValueError("production qualification gap plan cannot perform effects")
        return self


class ProductionSafetyQualificationEvidenceRequestRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_kind: ProductionSafetyQualificationEvidenceRequestKind
    source_gap_kind: ProductionSafetyQualificationGapKind | None = None
    action: ProductionSafetyQualificationGapAction | None = None
    area: ProductionSafetyQualificationArea | None = None
    threat_id: ProductionSafetyQualificationThreatId | None = None
    mode_id: ProductionSafetyQualificationModeId | None = None
    required_claims: list[ProductionSafetyQualificationClaimId] = Field(
        default_factory=list
    )
    required_threats: list[ProductionSafetyQualificationThreatId] = Field(
        default_factory=list
    )
    required_qualification_modes: list[ProductionSafetyQualificationModeId] = Field(
        default_factory=list
    )
    required_artifacts: list[str] = Field(default_factory=list)
    source_integrity_required: bool = True
    human_review_required: bool = True
    max_age_seconds_required: bool = True
    external_effects_prohibited: bool = True
    unblock_condition: str = Field(min_length=1)

    @model_validator(mode="after")
    def enforce_evidence_request_row(
        self,
    ) -> "ProductionSafetyQualificationEvidenceRequestRow":
        if self.request_kind in {
            "area_evidence_bundle",
            "area_source_package",
        } and self.area is None:
            raise ValueError("area evidence request requires area")
        if self.request_kind == "threat_coverage_case" and self.threat_id is None:
            raise ValueError("threat coverage request requires threat_id")
        if self.request_kind == "qualification_mode_case" and self.mode_id is None:
            raise ValueError("qualification mode request requires mode_id")
        if not self.external_effects_prohibited:
            raise ValueError("qualification evidence request cannot allow effects")
        return self


class ProductionSafetyQualificationEvidenceRequestPack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_safety_qualification_evidence_request_pack"
    artifact_version: str = "production_safety_qualification_evidence_request_pack.v0"
    source_provider: str = "scout_runtime_safety_production_qualification"
    source_path: str
    sha256: str
    status: ProductionSafetyQualificationEvidenceRequestPackStatus
    gap_plan_ref: str
    gap_plan_sha256: str
    request_count: int = 0
    rows: list[ProductionSafetyQualificationEvidenceRequestRow] = Field(
        default_factory=list
    )
    external_call_performed_by_request_pack: bool = False
    credential_material_loaded_by_request_pack: bool = False
    raw_payload_loaded_by_request_pack: bool = False
    production_database_mutated_by_request_pack: bool = False
    safety_api_called_by_request_pack: bool = False
    phase1_l0_l4_state_mutated_by_request_pack: bool = False
    runtime_safety_truth_mutated_by_request_pack: bool = False
    outbound_transport_invoked_by_request_pack: bool = False
    hardware_control_performed_by_request_pack: bool = False
    limitations: list[str] = Field(default_factory=list)
    boundary: ProductionSafetyQualificationBoundary = Field(
        default_factory=ProductionSafetyQualificationBoundary
    )

    @model_validator(mode="after")
    def enforce_evidence_request_pack(
        self,
    ) -> "ProductionSafetyQualificationEvidenceRequestPack":
        if self.request_count != len(self.rows):
            raise ValueError("request_count must match rows")
        if self.status == "no_evidence_requests_required" and self.rows:
            raise ValueError("no-request pack cannot contain rows")
        if self.status == "evidence_request_pack_ready" and not self.rows:
            raise ValueError("ready request pack requires request rows")
        if (
            self.external_call_performed_by_request_pack
            or self.credential_material_loaded_by_request_pack
            or self.raw_payload_loaded_by_request_pack
            or self.production_database_mutated_by_request_pack
            or self.safety_api_called_by_request_pack
            or self.phase1_l0_l4_state_mutated_by_request_pack
            or self.runtime_safety_truth_mutated_by_request_pack
            or self.outbound_transport_invoked_by_request_pack
            or self.hardware_control_performed_by_request_pack
        ):
            raise ValueError("qualification evidence request pack cannot perform effects")
        return self


class ProductionSafetyQualificationEvidenceSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_safety_qualification_evidence_submission"
    artifact_version: str = "production_safety_qualification_evidence_submission.v0"
    request_kind: ProductionSafetyQualificationEvidenceRequestKind
    area: ProductionSafetyQualificationArea | None = None
    threat_id: ProductionSafetyQualificationThreatId | None = None
    mode_id: ProductionSafetyQualificationModeId | None = None
    submitted_artifact_kind: str = Field(min_length=1)
    submitted_artifact_ref: str = Field(min_length=1)
    submitted_artifact_sha256: str = Field(min_length=1)
    reviewer_ref: str | None = None
    reviewer_sha256: str | None = None
    source_integrity_evidence_present: bool = False
    max_age_metadata_present: bool = False
    accepted: bool = False
    credential_material_embedded: bool = False
    raw_payload_embedded: bool = False
    safety_api_called_by_fulfillment: bool = False
    phase1_l0_l4_state_mutated_by_fulfillment: bool = False
    runtime_safety_truth_mutated_by_fulfillment: bool = False
    outbound_transport_invoked_by_fulfillment: bool = False
    hardware_control_performed_by_fulfillment: bool = False
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_evidence_submission(
        self,
    ) -> "ProductionSafetyQualificationEvidenceSubmission":
        _assert_qualification_ref("submitted_artifact_ref", self.submitted_artifact_ref)
        if (self.reviewer_ref is None) != (self.reviewer_sha256 is None):
            raise ValueError("reviewer_ref and reviewer_sha256 must be paired")
        if self.reviewer_ref is not None:
            _assert_qualification_ref("reviewer_ref", self.reviewer_ref)
        if self.credential_material_embedded or self.raw_payload_embedded:
            raise ValueError(
                "qualification evidence submission cannot embed sensitive data"
            )
        if (
            self.safety_api_called_by_fulfillment
            or self.phase1_l0_l4_state_mutated_by_fulfillment
            or self.runtime_safety_truth_mutated_by_fulfillment
            or self.outbound_transport_invoked_by_fulfillment
            or self.hardware_control_performed_by_fulfillment
        ):
            raise ValueError(
                "qualification evidence submission cannot perform runtime effects"
            )
        return self


class ProductionSafetyQualificationEvidenceFulfillmentManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = (
        "scout_production_safety_qualification_evidence_fulfillment_manifest"
    )
    artifact_version: str = (
        "production_safety_qualification_evidence_fulfillment_manifest.v0"
    )
    source_provider: str = "scout_runtime_safety_production_qualification"
    source_path: str
    request_pack_ref: str
    request_pack_sha256: str
    submissions: list[ProductionSafetyQualificationEvidenceSubmission] = Field(
        default_factory=list
    )
    external_call_performed_by_fulfillment: bool = False
    credential_material_loaded_by_fulfillment: bool = False
    raw_payload_loaded_by_fulfillment: bool = False
    production_database_mutated_by_fulfillment: bool = False
    safety_api_called_by_fulfillment: bool = False
    phase1_l0_l4_state_mutated_by_fulfillment: bool = False
    runtime_safety_truth_mutated_by_fulfillment: bool = False
    outbound_transport_invoked_by_fulfillment: bool = False
    hardware_control_performed_by_fulfillment: bool = False

    @model_validator(mode="after")
    def enforce_fulfillment_manifest(
        self,
    ) -> "ProductionSafetyQualificationEvidenceFulfillmentManifest":
        _assert_qualification_ref("source_path", self.source_path)
        _assert_qualification_ref("request_pack_ref", self.request_pack_ref)
        submission_keys = [
            _evidence_request_submission_key(submission)
            for submission in self.submissions
        ]
        if len(submission_keys) != len(set(submission_keys)):
            raise ValueError("evidence fulfillment submissions must be unique")
        if (
            self.external_call_performed_by_fulfillment
            or self.credential_material_loaded_by_fulfillment
            or self.raw_payload_loaded_by_fulfillment
            or self.production_database_mutated_by_fulfillment
            or self.safety_api_called_by_fulfillment
            or self.phase1_l0_l4_state_mutated_by_fulfillment
            or self.runtime_safety_truth_mutated_by_fulfillment
            or self.outbound_transport_invoked_by_fulfillment
            or self.hardware_control_performed_by_fulfillment
        ):
            raise ValueError("qualification evidence fulfillment cannot perform effects")
        return self


class ProductionSafetyQualificationEvidenceFulfillmentArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = (
        "scout_production_safety_qualification_evidence_fulfillment_artifact"
    )
    artifact_version: str = (
        "production_safety_qualification_evidence_fulfillment_artifact.v0"
    )
    submitted_artifact_ref: str = Field(min_length=1)
    submitted_artifact_sha256: str = Field(min_length=1)
    local_path: str = Field(min_length=1)
    redacted_or_sanitized: bool = True
    credential_material_present: bool = False
    raw_payload_present: bool = False
    safety_api_path_present: bool = False
    runtime_safety_truth_present: bool = False

    @model_validator(mode="after")
    def enforce_fulfillment_artifact(
        self,
    ) -> "ProductionSafetyQualificationEvidenceFulfillmentArtifact":
        _assert_qualification_ref("submitted_artifact_ref", self.submitted_artifact_ref)
        return self


class ProductionSafetyQualificationEvidenceFulfillmentSourcePackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = (
        "scout_production_safety_qualification_evidence_fulfillment_source_package"
    )
    artifact_version: str = (
        "production_safety_qualification_evidence_fulfillment_source_package.v0"
    )
    source_provider: str = "scout_runtime_safety_production_qualification"
    source_path: str
    fulfillment_manifest_ref: str
    fulfillment_manifest_sha256: str
    artifacts: list[ProductionSafetyQualificationEvidenceFulfillmentArtifact] = Field(
        default_factory=list
    )
    external_call_performed_by_source_package: bool = False
    credential_material_loaded_by_source_package: bool = False
    raw_payload_loaded_by_source_package: bool = False
    production_database_mutated_by_source_package: bool = False
    safety_api_called_by_source_package: bool = False
    phase1_l0_l4_state_mutated_by_source_package: bool = False
    runtime_safety_truth_mutated_by_source_package: bool = False
    outbound_transport_invoked_by_source_package: bool = False
    hardware_control_performed_by_source_package: bool = False

    @model_validator(mode="after")
    def enforce_fulfillment_source_package(
        self,
    ) -> "ProductionSafetyQualificationEvidenceFulfillmentSourcePackage":
        _assert_qualification_ref("source_path", self.source_path)
        _assert_qualification_ref(
            "fulfillment_manifest_ref",
            self.fulfillment_manifest_ref,
        )
        artifact_refs = [artifact.submitted_artifact_ref for artifact in self.artifacts]
        if len(artifact_refs) != len(set(artifact_refs)):
            raise ValueError("fulfillment source package artifacts must be unique")
        if (
            self.external_call_performed_by_source_package
            or self.credential_material_loaded_by_source_package
            or self.raw_payload_loaded_by_source_package
            or self.production_database_mutated_by_source_package
            or self.safety_api_called_by_source_package
            or self.phase1_l0_l4_state_mutated_by_source_package
            or self.runtime_safety_truth_mutated_by_source_package
            or self.outbound_transport_invoked_by_source_package
            or self.hardware_control_performed_by_source_package
        ):
            raise ValueError(
                "qualification fulfillment source package cannot perform effects"
            )
        return self


class ProductionSafetyQualificationEvidenceFulfillmentRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_kind: ProductionSafetyQualificationEvidenceRequestKind
    status: ProductionSafetyQualificationEvidenceRequestFulfillmentRowStatus
    area: ProductionSafetyQualificationArea | None = None
    threat_id: ProductionSafetyQualificationThreatId | None = None
    mode_id: ProductionSafetyQualificationModeId | None = None
    submitted_artifact_kind: str | None = None
    submitted_artifact_ref: str | None = None
    submitted_artifact_sha256: str | None = None
    fulfilled: bool = False
    blockers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_fulfillment_row(
        self,
    ) -> "ProductionSafetyQualificationEvidenceFulfillmentRow":
        if self.fulfilled != (self.status == "fulfilled"):
            raise ValueError("fulfilled must match row status")
        if self.status != "fulfilled" and not self.blockers:
            raise ValueError("blocked fulfillment row requires blockers")
        return self


class ProductionSafetyQualificationEvidenceFulfillmentSourceIntegrityRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    submitted_artifact_ref: str
    expected_sha256: str
    actual_sha256: str | None = None
    local_path: str | None = None
    status: ProductionSafetyQualificationEvidenceFulfillmentSourceIntegrityRowStatus
    source_integrity_verified: bool = False
    blockers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_fulfillment_source_integrity_row(
        self,
    ) -> "ProductionSafetyQualificationEvidenceFulfillmentSourceIntegrityRow":
        if self.source_integrity_verified != (self.status == "verified"):
            raise ValueError("source_integrity_verified must match row status")
        if self.status != "verified" and not self.blockers:
            raise ValueError("blocked fulfillment source-integrity row requires blockers")
        return self


class ProductionSafetyQualificationEvidenceFulfillmentSourceIntegrityReport(
    BaseModel
):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = (
        "scout_production_safety_qualification_evidence_fulfillment_source_integrity_report"
    )
    artifact_version: str = (
        "production_safety_qualification_evidence_fulfillment_source_integrity_report.v0"
    )
    source_provider: str = "scout_runtime_safety_production_qualification"
    source_path: str
    sha256: str
    fulfillment_manifest_ref: str
    fulfillment_manifest_sha256: str
    source_package_ref: str
    status: ProductionSafetyQualificationEvidenceFulfillmentSourceIntegrityStatus
    rows: list[ProductionSafetyQualificationEvidenceFulfillmentSourceIntegrityRow]
    verified_submitted_artifact_refs: list[str] = Field(default_factory=list)
    missing_submitted_artifact_refs: list[str] = Field(default_factory=list)
    mismatched_submitted_artifact_refs: list[str] = Field(default_factory=list)
    unsafe_submitted_artifact_refs: list[str] = Field(default_factory=list)
    sensitive_submitted_artifact_refs: list[str] = Field(default_factory=list)
    unrequested_submitted_artifact_refs: list[str] = Field(default_factory=list)
    all_fulfillment_sources_verified: bool = False
    external_call_performed_by_source_integrity: bool = False
    credential_material_loaded_by_source_integrity: bool = False
    raw_payload_loaded_by_source_integrity: bool = False
    production_database_mutated_by_source_integrity: bool = False
    safety_api_called_by_source_integrity: bool = False
    phase1_l0_l4_state_mutated_by_source_integrity: bool = False
    runtime_safety_truth_mutated_by_source_integrity: bool = False
    outbound_transport_invoked_by_source_integrity: bool = False
    hardware_control_performed_by_source_integrity: bool = False
    limitations: list[str] = Field(default_factory=list)
    boundary: ProductionSafetyQualificationBoundary = Field(
        default_factory=ProductionSafetyQualificationBoundary
    )

    @model_validator(mode="after")
    def enforce_fulfillment_source_integrity_report(
        self,
    ) -> "ProductionSafetyQualificationEvidenceFulfillmentSourceIntegrityReport":
        ready = self.status == "fulfillment_source_integrity_verified"
        if self.all_fulfillment_sources_verified != ready:
            raise ValueError("all_fulfillment_sources_verified must match status")
        if ready and any(row.status != "verified" for row in self.rows):
            raise ValueError("verified fulfillment source report cannot contain blockers")
        if (
            self.external_call_performed_by_source_integrity
            or self.credential_material_loaded_by_source_integrity
            or self.raw_payload_loaded_by_source_integrity
            or self.production_database_mutated_by_source_integrity
            or self.safety_api_called_by_source_integrity
            or self.phase1_l0_l4_state_mutated_by_source_integrity
            or self.runtime_safety_truth_mutated_by_source_integrity
            or self.outbound_transport_invoked_by_source_integrity
            or self.hardware_control_performed_by_source_integrity
        ):
            raise ValueError(
                "qualification fulfillment source-integrity report cannot perform effects"
            )
        return self


class ProductionSafetyQualificationEvidenceFulfillmentReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = (
        "scout_production_safety_qualification_evidence_fulfillment_report"
    )
    artifact_version: str = (
        "production_safety_qualification_evidence_fulfillment_report.v0"
    )
    source_provider: str = "scout_runtime_safety_production_qualification"
    source_path: str
    sha256: str
    status: ProductionSafetyQualificationEvidenceRequestFulfillmentStatus
    request_pack_ref: str
    request_pack_sha256: str
    fulfillment_manifest_ref: str
    fulfillment_manifest_sha256: str
    source_integrity_report_ref: str | None = None
    source_integrity_report_sha256: str | None = None
    source_integrity_verified: bool = False
    rows: list[ProductionSafetyQualificationEvidenceFulfillmentRow]
    fulfilled_request_count: int = 0
    missing_request_count: int = 0
    mismatched_request_count: int = 0
    rejected_request_count: int = 0
    source_unverified_request_count: int = 0
    unverified_source_refs: list[str] = Field(default_factory=list)
    all_requested_evidence_fulfilled: bool = False
    external_call_performed_by_fulfillment: bool = False
    credential_material_loaded_by_fulfillment: bool = False
    raw_payload_loaded_by_fulfillment: bool = False
    production_database_mutated_by_fulfillment: bool = False
    safety_api_called_by_fulfillment: bool = False
    phase1_l0_l4_state_mutated_by_fulfillment: bool = False
    runtime_safety_truth_mutated_by_fulfillment: bool = False
    outbound_transport_invoked_by_fulfillment: bool = False
    hardware_control_performed_by_fulfillment: bool = False
    limitations: list[str] = Field(default_factory=list)
    boundary: ProductionSafetyQualificationBoundary = Field(
        default_factory=ProductionSafetyQualificationBoundary
    )

    @model_validator(mode="after")
    def enforce_fulfillment_report(
        self,
    ) -> "ProductionSafetyQualificationEvidenceFulfillmentReport":
        ready = self.status == "evidence_request_fulfillment_verified"
        if self.all_requested_evidence_fulfilled != ready:
            raise ValueError("all_requested_evidence_fulfilled must match status")
        if self.fulfilled_request_count != len(
            [row for row in self.rows if row.status == "fulfilled"]
        ):
            raise ValueError("fulfilled_request_count must match rows")
        if self.missing_request_count != len(
            [row for row in self.rows if row.status == "missing"]
        ):
            raise ValueError("missing_request_count must match rows")
        if self.mismatched_request_count != len(
            [row for row in self.rows if row.status == "mismatched"]
        ):
            raise ValueError("mismatched_request_count must match rows")
        if self.rejected_request_count != len(
            [row for row in self.rows if row.status == "rejected"]
        ):
            raise ValueError("rejected_request_count must match rows")
        if self.source_unverified_request_count != len(
            [row for row in self.rows if row.status == "source_unverified"]
        ):
            raise ValueError("source_unverified_request_count must match rows")
        if ready and any(row.status != "fulfilled" for row in self.rows):
            raise ValueError("verified fulfillment cannot contain blocked rows")
        if ready and not self.source_integrity_verified:
            raise ValueError("verified fulfillment requires source integrity")
        if self.source_integrity_verified and (
            self.source_integrity_report_ref is None
            or self.source_integrity_report_sha256 is None
        ):
            raise ValueError("verified fulfillment requires source-integrity refs")
        if (self.source_integrity_report_ref is None) != (
            self.source_integrity_report_sha256 is None
        ):
            raise ValueError("source-integrity report refs must be paired")
        if (
            self.external_call_performed_by_fulfillment
            or self.credential_material_loaded_by_fulfillment
            or self.raw_payload_loaded_by_fulfillment
            or self.production_database_mutated_by_fulfillment
            or self.safety_api_called_by_fulfillment
            or self.phase1_l0_l4_state_mutated_by_fulfillment
            or self.runtime_safety_truth_mutated_by_fulfillment
            or self.outbound_transport_invoked_by_fulfillment
            or self.hardware_control_performed_by_fulfillment
        ):
            raise ValueError("qualification evidence fulfillment report cannot perform effects")
        return self


class ProductionSafetyQualificationRemediationRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gap_kind: ProductionSafetyQualificationGapKind
    action: ProductionSafetyQualificationGapAction
    status: ProductionSafetyQualificationRemediationRowStatus
    area: ProductionSafetyQualificationArea | None = None
    threat_id: ProductionSafetyQualificationThreatId | None = None
    mode_id: ProductionSafetyQualificationModeId | None = None
    expected_request_count: int = 0
    fulfilled_request_count: int = 0
    request_statuses: list[ProductionSafetyQualificationEvidenceRequestFulfillmentRowStatus] = (
        Field(default_factory=list)
    )
    ready_for_dossier_rerun: bool = False
    blockers: list[str] = Field(default_factory=list)
    unblock_condition: str = Field(min_length=1)

    @model_validator(mode="after")
    def enforce_remediation_row(
        self,
    ) -> "ProductionSafetyQualificationRemediationRow":
        ready = self.status == "ready_for_dossier_rerun"
        if self.ready_for_dossier_rerun != ready:
            raise ValueError("ready_for_dossier_rerun must match row status")
        if ready and self.blockers:
            raise ValueError("ready remediation row cannot contain blockers")
        if not ready and not self.blockers:
            raise ValueError("blocked remediation row requires blockers")
        if self.fulfilled_request_count > self.expected_request_count:
            raise ValueError("fulfilled_request_count cannot exceed expected requests")
        return self


class ProductionSafetyQualificationRemediationReadinessReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_safety_qualification_remediation_readiness"
    artifact_version: str = "production_safety_qualification_remediation_readiness.v0"
    source_provider: str = "scout_runtime_safety_production_qualification"
    source_path: str
    sha256: str
    status: ProductionSafetyQualificationRemediationStatus
    gap_plan_ref: str
    gap_plan_sha256: str
    request_pack_ref: str | None = None
    request_pack_sha256: str | None = None
    fulfillment_report_ref: str | None = None
    fulfillment_report_sha256: str | None = None
    rows: list[ProductionSafetyQualificationRemediationRow] = Field(
        default_factory=list
    )
    ready_gap_count: int = 0
    blocked_gap_count: int = 0
    all_open_gaps_remediated: bool = False
    ready_for_dossier_rerun: bool = False
    ready_for_production_cutover: bool = False
    external_call_performed_by_remediation: bool = False
    credential_material_loaded_by_remediation: bool = False
    raw_payload_loaded_by_remediation: bool = False
    production_database_mutated_by_remediation: bool = False
    safety_api_called_by_remediation: bool = False
    phase1_l0_l4_state_mutated_by_remediation: bool = False
    runtime_safety_truth_mutated_by_remediation: bool = False
    outbound_transport_invoked_by_remediation: bool = False
    hardware_control_performed_by_remediation: bool = False
    limitations: list[str] = Field(default_factory=list)
    boundary: ProductionSafetyQualificationBoundary = Field(
        default_factory=ProductionSafetyQualificationBoundary
    )

    @model_validator(mode="after")
    def enforce_remediation_report(
        self,
    ) -> "ProductionSafetyQualificationRemediationReadinessReport":
        ready_rows = [row for row in self.rows if row.ready_for_dossier_rerun]
        blocked_rows = [row for row in self.rows if not row.ready_for_dossier_rerun]
        if self.ready_gap_count != len(ready_rows):
            raise ValueError("ready_gap_count must match rows")
        if self.blocked_gap_count != len(blocked_rows):
            raise ValueError("blocked_gap_count must match rows")
        if self.status == "no_remediation_required" and self.rows:
            raise ValueError("no-remediation report cannot contain rows")
        if self.status == "ready_for_dossier_rerun" and (
            self.blocked_gap_count or not self.rows
        ):
            raise ValueError("ready remediation report requires only ready rows")
        if self.ready_for_dossier_rerun != (
            self.status == "ready_for_dossier_rerun"
        ):
            raise ValueError("ready_for_dossier_rerun must match report status")
        if self.ready_for_production_cutover:
            raise ValueError("remediation readiness cannot claim production cutover")
        if self.all_open_gaps_remediated != (
            self.status in {"no_remediation_required", "ready_for_dossier_rerun"}
        ):
            raise ValueError("all_open_gaps_remediated must match report status")
        if (
            self.external_call_performed_by_remediation
            or self.credential_material_loaded_by_remediation
            or self.raw_payload_loaded_by_remediation
            or self.production_database_mutated_by_remediation
            or self.safety_api_called_by_remediation
            or self.phase1_l0_l4_state_mutated_by_remediation
            or self.runtime_safety_truth_mutated_by_remediation
            or self.outbound_transport_invoked_by_remediation
            or self.hardware_control_performed_by_remediation
        ):
            raise ValueError("qualification remediation readiness cannot perform effects")
        return self


class ProductionSafetyQualificationExternalActionRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gap_kind: ProductionSafetyQualificationGapKind
    action: ProductionSafetyQualificationGapAction
    external_action_kind: ProductionSafetyQualificationExternalActionKind
    status: ProductionSafetyQualificationExternalActionRowStatus
    area: ProductionSafetyQualificationArea | None = None
    threat_id: ProductionSafetyQualificationThreatId | None = None
    mode_id: ProductionSafetyQualificationModeId | None = None
    expected_request_count: int = 0
    fulfilled_request_count: int = 0
    required_artifacts: list[str] = Field(default_factory=list)
    ready_for_operator_authorization: bool = False
    dossier_rerun_required: bool = False
    requires_explicit_operator_approval: Literal[True] = True
    reviewed_effect_boundary_required: Literal[True] = True
    execution_allowed: Literal[False] = False
    blockers: list[str] = Field(default_factory=list)
    next_action: str = Field(min_length=1)

    @model_validator(mode="after")
    def enforce_external_action_row(
        self,
    ) -> "ProductionSafetyQualificationExternalActionRow":
        ready = self.status == "ready_for_operator_authorization"
        if self.ready_for_operator_authorization != ready:
            raise ValueError("ready_for_operator_authorization must match row status")
        if ready and self.blockers:
            raise ValueError("ready external action row cannot contain blockers")
        if not ready and not self.blockers:
            raise ValueError("blocked external action row requires blockers")
        if self.fulfilled_request_count > self.expected_request_count:
            raise ValueError("fulfilled_request_count cannot exceed expected requests")
        if not self.required_artifacts:
            raise ValueError("external action row requires artifact list")
        if self.execution_allowed:
            raise ValueError("external qualification action row cannot allow execution")
        return self


class ProductionSafetyQualificationExternalActionPacket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_safety_qualification_external_action_packet"
    artifact_version: str = (
        "production_safety_qualification_external_action_packet.v0"
    )
    source_provider: str = "scout_runtime_safety_production_qualification"
    source_path: str
    sha256: str
    status: ProductionSafetyQualificationExternalActionPacketStatus
    remediation_report_ref: str
    remediation_report_sha256: str
    gap_plan_ref: str
    gap_plan_sha256: str
    request_pack_ref: str | None = None
    request_pack_sha256: str | None = None
    fulfillment_report_ref: str | None = None
    fulfillment_report_sha256: str | None = None
    rows: list[ProductionSafetyQualificationExternalActionRow] = Field(
        default_factory=list
    )
    ready_action_count: int = 0
    blocked_action_count: int = 0
    ready_for_operator_authorization: bool = False
    ready_for_production_cutover: bool = False
    execution_allowed: Literal[False] = False
    external_call_performed_by_packet: bool = False
    credential_material_loaded_by_packet: bool = False
    raw_payload_loaded_by_packet: bool = False
    production_database_mutated_by_packet: bool = False
    safety_api_called_by_packet: bool = False
    phase1_l0_l4_state_mutated_by_packet: bool = False
    runtime_safety_truth_mutated_by_packet: bool = False
    outbound_transport_invoked_by_packet: bool = False
    hardware_control_performed_by_packet: bool = False
    limitations: list[str] = Field(default_factory=list)
    boundary: ProductionSafetyQualificationBoundary = Field(
        default_factory=ProductionSafetyQualificationBoundary
    )

    @model_validator(mode="after")
    def enforce_external_action_packet(
        self,
    ) -> "ProductionSafetyQualificationExternalActionPacket":
        ready_rows = [
            row for row in self.rows if row.ready_for_operator_authorization
        ]
        blocked_rows = [
            row for row in self.rows if not row.ready_for_operator_authorization
        ]
        if self.ready_action_count != len(ready_rows):
            raise ValueError("ready_action_count must match rows")
        if self.blocked_action_count != len(blocked_rows):
            raise ValueError("blocked_action_count must match rows")
        if self.status == "no_external_actions_required" and self.rows:
            raise ValueError("no-action packet cannot contain rows")
        if self.status == "external_actions_ready_for_operator_authorization" and (
            not self.rows or blocked_rows
        ):
            raise ValueError("ready packet requires only ready external action rows")
        if self.status == "blocked_external_actions_incomplete" and not blocked_rows:
            raise ValueError("blocked packet requires blocked external action rows")
        if self.ready_for_operator_authorization != (
            self.status == "external_actions_ready_for_operator_authorization"
        ):
            raise ValueError("ready_for_operator_authorization must match status")
        if self.ready_for_production_cutover:
            raise ValueError("external action packet cannot claim production cutover")
        if self.execution_allowed:
            raise ValueError("external qualification action packet cannot allow execution")
        if (
            self.external_call_performed_by_packet
            or self.credential_material_loaded_by_packet
            or self.raw_payload_loaded_by_packet
            or self.production_database_mutated_by_packet
            or self.safety_api_called_by_packet
            or self.phase1_l0_l4_state_mutated_by_packet
            or self.runtime_safety_truth_mutated_by_packet
            or self.outbound_transport_invoked_by_packet
            or self.hardware_control_performed_by_packet
        ):
            raise ValueError("external qualification action packet cannot perform effects")
        return self


class ProductionSafetyQualificationExternalAuthorizationSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = (
        "scout_production_safety_qualification_external_authorization_submission"
    )
    artifact_version: str = (
        "production_safety_qualification_external_authorization_submission.v0"
    )
    gap_kind: ProductionSafetyQualificationGapKind
    action: ProductionSafetyQualificationGapAction
    external_action_kind: ProductionSafetyQualificationExternalActionKind
    area: ProductionSafetyQualificationArea | None = None
    threat_id: ProductionSafetyQualificationThreatId | None = None
    mode_id: ProductionSafetyQualificationModeId | None = None
    authorized: bool = False
    operator_identity_ref: str | None = None
    operator_identity_sha256: str | None = None
    authorization_ref: str | None = None
    authorization_sha256: str | None = None
    reviewed_effect_boundary_ref: str | None = None
    reviewed_effect_boundary_sha256: str | None = None
    idempotency_key: str | None = None
    authorization_observed_at: datetime | None = None
    expires_at: datetime | None = None
    execution_allowed: Literal[False] = False
    external_call_performed_by_authorization: bool = False
    credential_material_loaded_by_authorization: bool = False
    raw_payload_loaded_by_authorization: bool = False
    production_database_mutated_by_authorization: bool = False
    safety_api_called_by_authorization: bool = False
    phase1_l0_l4_state_mutated_by_authorization: bool = False
    runtime_safety_truth_mutated_by_authorization: bool = False
    outbound_transport_invoked_by_authorization: bool = False
    hardware_control_performed_by_authorization: bool = False

    @model_validator(mode="after")
    def enforce_external_authorization_submission(
        self,
    ) -> "ProductionSafetyQualificationExternalAuthorizationSubmission":
        for ref_name, ref_value, sha_name, sha_value in (
            (
                "operator_identity_ref",
                self.operator_identity_ref,
                "operator_identity_sha256",
                self.operator_identity_sha256,
            ),
            (
                "authorization_ref",
                self.authorization_ref,
                "authorization_sha256",
                self.authorization_sha256,
            ),
            (
                "reviewed_effect_boundary_ref",
                self.reviewed_effect_boundary_ref,
                "reviewed_effect_boundary_sha256",
                self.reviewed_effect_boundary_sha256,
            ),
        ):
            if (ref_value is None) != (sha_value is None):
                raise ValueError(f"{ref_name} and {sha_name} must be paired")
            if ref_value is not None:
                _assert_qualification_ref(ref_name, ref_value)
        if (
            self.authorization_observed_at is not None
            and self.expires_at is not None
            and _as_utc(self.expires_at) <= _as_utc(self.authorization_observed_at)
        ):
            raise ValueError("external authorization expires_at must be after observation")
        if self.execution_allowed:
            raise ValueError("external authorization submission cannot allow execution")
        if (
            self.external_call_performed_by_authorization
            or self.credential_material_loaded_by_authorization
            or self.raw_payload_loaded_by_authorization
            or self.production_database_mutated_by_authorization
            or self.safety_api_called_by_authorization
            or self.phase1_l0_l4_state_mutated_by_authorization
            or self.runtime_safety_truth_mutated_by_authorization
            or self.outbound_transport_invoked_by_authorization
            or self.hardware_control_performed_by_authorization
        ):
            raise ValueError("external authorization submission cannot perform effects")
        return self


class ProductionSafetyQualificationExternalAuthorizationManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = (
        "scout_production_safety_qualification_external_authorization_manifest"
    )
    artifact_version: str = (
        "production_safety_qualification_external_authorization_manifest.v0"
    )
    source_provider: str = "scout_runtime_safety_production_qualification"
    source_path: str
    external_action_packet_ref: str
    external_action_packet_sha256: str
    reference_time: datetime
    submissions: list[ProductionSafetyQualificationExternalAuthorizationSubmission] = (
        Field(default_factory=list)
    )
    external_call_performed_by_authorization_manifest: bool = False
    credential_material_loaded_by_authorization_manifest: bool = False
    raw_payload_loaded_by_authorization_manifest: bool = False
    production_database_mutated_by_authorization_manifest: bool = False
    safety_api_called_by_authorization_manifest: bool = False
    phase1_l0_l4_state_mutated_by_authorization_manifest: bool = False
    runtime_safety_truth_mutated_by_authorization_manifest: bool = False
    outbound_transport_invoked_by_authorization_manifest: bool = False
    hardware_control_performed_by_authorization_manifest: bool = False

    @model_validator(mode="after")
    def enforce_external_authorization_manifest(
        self,
    ) -> "ProductionSafetyQualificationExternalAuthorizationManifest":
        _assert_qualification_ref("source_path", self.source_path)
        _assert_qualification_ref(
            "external_action_packet_ref",
            self.external_action_packet_ref,
        )
        keys = [
            _external_authorization_key(submission)
            for submission in self.submissions
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("external authorization submissions must be unique")
        if (
            self.external_call_performed_by_authorization_manifest
            or self.credential_material_loaded_by_authorization_manifest
            or self.raw_payload_loaded_by_authorization_manifest
            or self.production_database_mutated_by_authorization_manifest
            or self.safety_api_called_by_authorization_manifest
            or self.phase1_l0_l4_state_mutated_by_authorization_manifest
            or self.runtime_safety_truth_mutated_by_authorization_manifest
            or self.outbound_transport_invoked_by_authorization_manifest
            or self.hardware_control_performed_by_authorization_manifest
        ):
            raise ValueError("external authorization manifest cannot perform effects")
        return self


class ProductionSafetyQualificationExternalAuthorizationRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gap_kind: ProductionSafetyQualificationGapKind
    action: ProductionSafetyQualificationGapAction
    external_action_kind: ProductionSafetyQualificationExternalActionKind
    status: ProductionSafetyQualificationExternalAuthorizationRowStatus
    area: ProductionSafetyQualificationArea | None = None
    threat_id: ProductionSafetyQualificationThreatId | None = None
    mode_id: ProductionSafetyQualificationModeId | None = None
    operator_authorization_recorded: bool = False
    ready_for_separate_executor_invocation: bool = False
    execution_allowed: Literal[False] = False
    operator_identity_ref: str | None = None
    operator_identity_sha256: str | None = None
    authorization_ref: str | None = None
    authorization_sha256: str | None = None
    reviewed_effect_boundary_ref: str | None = None
    reviewed_effect_boundary_sha256: str | None = None
    idempotency_key: str | None = None
    authorization_observed_at: datetime | None = None
    expires_at: datetime | None = None
    blockers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_external_authorization_row(
        self,
    ) -> "ProductionSafetyQualificationExternalAuthorizationRow":
        recorded = self.status == "authorization_recorded"
        if self.operator_authorization_recorded != recorded:
            raise ValueError("operator_authorization_recorded must match row status")
        if self.ready_for_separate_executor_invocation != recorded:
            raise ValueError(
                "ready_for_separate_executor_invocation must match row status"
            )
        if recorded and self.blockers:
            raise ValueError("recorded authorization row cannot contain blockers")
        if not recorded and not self.blockers:
            raise ValueError("blocked authorization row requires blockers")
        if self.execution_allowed:
            raise ValueError("external authorization row cannot allow execution")
        return self


class ProductionSafetyQualificationExternalAuthorizationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = (
        "scout_production_safety_qualification_external_authorization_report"
    )
    artifact_version: str = (
        "production_safety_qualification_external_authorization_report.v0"
    )
    source_provider: str = "scout_runtime_safety_production_qualification"
    source_path: str
    sha256: str
    status: ProductionSafetyQualificationExternalAuthorizationReportStatus
    external_action_packet_ref: str
    external_action_packet_sha256: str
    authorization_manifest_ref: str
    authorization_manifest_sha256: str
    remediation_report_ref: str
    remediation_report_sha256: str
    rows: list[ProductionSafetyQualificationExternalAuthorizationRow] = Field(
        default_factory=list
    )
    authorized_action_count: int = 0
    blocked_action_count: int = 0
    all_authorizations_recorded: bool = False
    ready_for_separate_executor_invocation: bool = False
    ready_for_production_cutover: bool = False
    execution_allowed: Literal[False] = False
    external_call_performed_by_authorization: bool = False
    credential_material_loaded_by_authorization: bool = False
    raw_payload_loaded_by_authorization: bool = False
    production_database_mutated_by_authorization: bool = False
    safety_api_called_by_authorization: bool = False
    phase1_l0_l4_state_mutated_by_authorization: bool = False
    runtime_safety_truth_mutated_by_authorization: bool = False
    outbound_transport_invoked_by_authorization: bool = False
    hardware_control_performed_by_authorization: bool = False
    limitations: list[str] = Field(default_factory=list)
    boundary: ProductionSafetyQualificationBoundary = Field(
        default_factory=ProductionSafetyQualificationBoundary
    )

    @model_validator(mode="after")
    def enforce_external_authorization_report(
        self,
    ) -> "ProductionSafetyQualificationExternalAuthorizationReport":
        authorized_rows = [
            row for row in self.rows if row.operator_authorization_recorded
        ]
        blocked_rows = [
            row for row in self.rows if not row.operator_authorization_recorded
        ]
        if self.authorized_action_count != len(authorized_rows):
            raise ValueError("authorized_action_count must match rows")
        if self.blocked_action_count != len(blocked_rows):
            raise ValueError("blocked_action_count must match rows")
        if self.status == "no_external_authorization_required" and self.rows:
            raise ValueError("no-authorization report cannot contain rows")
        if self.status == "external_authorization_recorded" and (
            not self.rows or blocked_rows
        ):
            raise ValueError("recorded authorization report requires only ready rows")
        if self.status == "blocked_external_authorization_incomplete" and not blocked_rows:
            raise ValueError("blocked authorization report requires blocked rows")
        recorded = self.status == "external_authorization_recorded"
        if self.all_authorizations_recorded != (
            self.status
            in {
                "no_external_authorization_required",
                "external_authorization_recorded",
            }
        ):
            raise ValueError("all_authorizations_recorded must match status")
        if self.ready_for_separate_executor_invocation != recorded:
            raise ValueError(
                "ready_for_separate_executor_invocation must match status"
            )
        if self.ready_for_production_cutover:
            raise ValueError("external authorization report cannot claim production cutover")
        if self.execution_allowed:
            raise ValueError("external authorization report cannot allow execution")
        if (
            self.external_call_performed_by_authorization
            or self.credential_material_loaded_by_authorization
            or self.raw_payload_loaded_by_authorization
            or self.production_database_mutated_by_authorization
            or self.safety_api_called_by_authorization
            or self.phase1_l0_l4_state_mutated_by_authorization
            or self.runtime_safety_truth_mutated_by_authorization
            or self.outbound_transport_invoked_by_authorization
            or self.hardware_control_performed_by_authorization
        ):
            raise ValueError("external authorization report cannot perform effects")
        return self


class ProductionSafetyQualificationExternalInvocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = (
        "scout_production_safety_qualification_external_invocation_request"
    )
    artifact_version: str = (
        "production_safety_qualification_external_invocation_request.v0"
    )
    gap_kind: ProductionSafetyQualificationGapKind
    action: ProductionSafetyQualificationGapAction
    external_action_kind: ProductionSafetyQualificationExternalActionKind
    area: ProductionSafetyQualificationArea | None = None
    threat_id: ProductionSafetyQualificationThreatId | None = None
    mode_id: ProductionSafetyQualificationModeId | None = None
    invocation_requested: bool = False
    operator_confirmation: bool = False
    operator_identity_ref: str | None = None
    operator_identity_sha256: str | None = None
    authorization_ref: str | None = None
    authorization_sha256: str | None = None
    reviewed_effect_boundary_ref: str | None = None
    reviewed_effect_boundary_sha256: str | None = None
    external_executor_ref: str | None = None
    external_executor_sha256: str | None = None
    executor_invocation_ref: str | None = None
    executor_invocation_sha256: str | None = None
    authorization_idempotency_key: str | None = None
    invocation_idempotency_key: str | None = None
    requested_at: datetime | None = None
    execution_allowed: Literal[False] = False
    external_call_performed_by_invocation_request: bool = False
    credential_material_loaded_by_invocation_request: bool = False
    raw_payload_loaded_by_invocation_request: bool = False
    production_database_mutated_by_invocation_request: bool = False
    safety_api_called_by_invocation_request: bool = False
    phase1_l0_l4_state_mutated_by_invocation_request: bool = False
    runtime_safety_truth_mutated_by_invocation_request: bool = False
    outbound_transport_invoked_by_invocation_request: bool = False
    hardware_control_performed_by_invocation_request: bool = False

    @model_validator(mode="after")
    def enforce_external_invocation_request(
        self,
    ) -> "ProductionSafetyQualificationExternalInvocationRequest":
        for ref_name, ref_value, sha_name, sha_value in (
            (
                "operator_identity_ref",
                self.operator_identity_ref,
                "operator_identity_sha256",
                self.operator_identity_sha256,
            ),
            (
                "authorization_ref",
                self.authorization_ref,
                "authorization_sha256",
                self.authorization_sha256,
            ),
            (
                "reviewed_effect_boundary_ref",
                self.reviewed_effect_boundary_ref,
                "reviewed_effect_boundary_sha256",
                self.reviewed_effect_boundary_sha256,
            ),
            (
                "external_executor_ref",
                self.external_executor_ref,
                "external_executor_sha256",
                self.external_executor_sha256,
            ),
            (
                "executor_invocation_ref",
                self.executor_invocation_ref,
                "executor_invocation_sha256",
                self.executor_invocation_sha256,
            ),
        ):
            if (ref_value is None) != (sha_value is None):
                raise ValueError(f"{ref_name} and {sha_name} must be paired")
            if ref_value is not None:
                _assert_qualification_ref(ref_name, ref_value)
        if self.execution_allowed:
            raise ValueError("external invocation request cannot allow execution")
        if (
            self.external_call_performed_by_invocation_request
            or self.credential_material_loaded_by_invocation_request
            or self.raw_payload_loaded_by_invocation_request
            or self.production_database_mutated_by_invocation_request
            or self.safety_api_called_by_invocation_request
            or self.phase1_l0_l4_state_mutated_by_invocation_request
            or self.runtime_safety_truth_mutated_by_invocation_request
            or self.outbound_transport_invoked_by_invocation_request
            or self.hardware_control_performed_by_invocation_request
        ):
            raise ValueError("external invocation request cannot perform effects")
        return self


class ProductionSafetyQualificationExternalInvocationManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = (
        "scout_production_safety_qualification_external_invocation_manifest"
    )
    artifact_version: str = (
        "production_safety_qualification_external_invocation_manifest.v0"
    )
    source_provider: str = "scout_runtime_safety_production_qualification"
    source_path: str
    external_authorization_report_ref: str
    external_authorization_report_sha256: str
    reference_time: datetime
    requests: list[ProductionSafetyQualificationExternalInvocationRequest] = (
        Field(default_factory=list)
    )
    external_call_performed_by_invocation_manifest: bool = False
    credential_material_loaded_by_invocation_manifest: bool = False
    raw_payload_loaded_by_invocation_manifest: bool = False
    production_database_mutated_by_invocation_manifest: bool = False
    safety_api_called_by_invocation_manifest: bool = False
    phase1_l0_l4_state_mutated_by_invocation_manifest: bool = False
    runtime_safety_truth_mutated_by_invocation_manifest: bool = False
    outbound_transport_invoked_by_invocation_manifest: bool = False
    hardware_control_performed_by_invocation_manifest: bool = False

    @model_validator(mode="after")
    def enforce_external_invocation_manifest(
        self,
    ) -> "ProductionSafetyQualificationExternalInvocationManifest":
        _assert_qualification_ref("source_path", self.source_path)
        _assert_qualification_ref(
            "external_authorization_report_ref",
            self.external_authorization_report_ref,
        )
        keys = [
            _external_invocation_key(request)
            for request in self.requests
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("external invocation requests must be unique")
        if (
            self.external_call_performed_by_invocation_manifest
            or self.credential_material_loaded_by_invocation_manifest
            or self.raw_payload_loaded_by_invocation_manifest
            or self.production_database_mutated_by_invocation_manifest
            or self.safety_api_called_by_invocation_manifest
            or self.phase1_l0_l4_state_mutated_by_invocation_manifest
            or self.runtime_safety_truth_mutated_by_invocation_manifest
            or self.outbound_transport_invoked_by_invocation_manifest
            or self.hardware_control_performed_by_invocation_manifest
        ):
            raise ValueError("external invocation manifest cannot perform effects")
        return self


class ProductionSafetyQualificationExternalInvocationRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gap_kind: ProductionSafetyQualificationGapKind
    action: ProductionSafetyQualificationGapAction
    external_action_kind: ProductionSafetyQualificationExternalActionKind
    status: ProductionSafetyQualificationExternalInvocationRowStatus
    area: ProductionSafetyQualificationArea | None = None
    threat_id: ProductionSafetyQualificationThreatId | None = None
    mode_id: ProductionSafetyQualificationModeId | None = None
    invocation_handoff_recorded: bool = False
    ready_for_separate_executor_handoff: bool = False
    execution_allowed: Literal[False] = False
    operator_identity_ref: str | None = None
    operator_identity_sha256: str | None = None
    authorization_ref: str | None = None
    authorization_sha256: str | None = None
    reviewed_effect_boundary_ref: str | None = None
    reviewed_effect_boundary_sha256: str | None = None
    external_executor_ref: str | None = None
    external_executor_sha256: str | None = None
    executor_invocation_ref: str | None = None
    executor_invocation_sha256: str | None = None
    authorization_idempotency_key: str | None = None
    invocation_idempotency_key: str | None = None
    requested_at: datetime | None = None
    blockers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_external_invocation_row(
        self,
    ) -> "ProductionSafetyQualificationExternalInvocationRow":
        recorded = self.status == "invocation_handoff_recorded"
        if self.invocation_handoff_recorded != recorded:
            raise ValueError("invocation_handoff_recorded must match row status")
        if self.ready_for_separate_executor_handoff != recorded:
            raise ValueError(
                "ready_for_separate_executor_handoff must match row status"
            )
        if recorded and self.blockers:
            raise ValueError("recorded invocation row cannot contain blockers")
        if not recorded and not self.blockers:
            raise ValueError("blocked invocation row requires blockers")
        if self.execution_allowed:
            raise ValueError("external invocation row cannot allow execution")
        return self


class ProductionSafetyQualificationExternalInvocationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = (
        "scout_production_safety_qualification_external_invocation_report"
    )
    artifact_version: str = (
        "production_safety_qualification_external_invocation_report.v0"
    )
    source_provider: str = "scout_runtime_safety_production_qualification"
    source_path: str
    sha256: str
    status: ProductionSafetyQualificationExternalInvocationReportStatus
    external_authorization_report_ref: str
    external_authorization_report_sha256: str
    invocation_manifest_ref: str
    invocation_manifest_sha256: str
    external_action_packet_ref: str
    external_action_packet_sha256: str
    remediation_report_ref: str
    remediation_report_sha256: str
    rows: list[ProductionSafetyQualificationExternalInvocationRow] = Field(
        default_factory=list
    )
    invocation_handoff_count: int = 0
    blocked_invocation_count: int = 0
    all_invocation_handoffs_recorded: bool = False
    ready_for_separate_executor_handoff: bool = False
    ready_for_production_cutover: bool = False
    execution_allowed: Literal[False] = False
    external_call_performed_by_invocation: bool = False
    credential_material_loaded_by_invocation: bool = False
    raw_payload_loaded_by_invocation: bool = False
    production_database_mutated_by_invocation: bool = False
    safety_api_called_by_invocation: bool = False
    phase1_l0_l4_state_mutated_by_invocation: bool = False
    runtime_safety_truth_mutated_by_invocation: bool = False
    outbound_transport_invoked_by_invocation: bool = False
    hardware_control_performed_by_invocation: bool = False
    limitations: list[str] = Field(default_factory=list)
    boundary: ProductionSafetyQualificationBoundary = Field(
        default_factory=ProductionSafetyQualificationBoundary
    )

    @model_validator(mode="after")
    def enforce_external_invocation_report(
        self,
    ) -> "ProductionSafetyQualificationExternalInvocationReport":
        handoff_rows = [
            row for row in self.rows if row.invocation_handoff_recorded
        ]
        blocked_rows = [
            row for row in self.rows if not row.invocation_handoff_recorded
        ]
        if self.invocation_handoff_count != len(handoff_rows):
            raise ValueError("invocation_handoff_count must match rows")
        if self.blocked_invocation_count != len(blocked_rows):
            raise ValueError("blocked_invocation_count must match rows")
        if self.status == "no_external_invocation_required" and self.rows:
            raise ValueError("no-invocation report cannot contain rows")
        if self.status == "external_invocation_handoff_recorded" and (
            not self.rows or blocked_rows
        ):
            raise ValueError("recorded invocation report requires only ready rows")
        if self.status == "blocked_external_invocation_incomplete" and not blocked_rows:
            raise ValueError("blocked invocation report requires blocked rows")
        recorded = self.status == "external_invocation_handoff_recorded"
        if self.all_invocation_handoffs_recorded != (
            self.status
            in {
                "no_external_invocation_required",
                "external_invocation_handoff_recorded",
            }
        ):
            raise ValueError("all_invocation_handoffs_recorded must match status")
        if self.ready_for_separate_executor_handoff != recorded:
            raise ValueError(
                "ready_for_separate_executor_handoff must match status"
            )
        if self.ready_for_production_cutover:
            raise ValueError("external invocation report cannot claim production cutover")
        if self.execution_allowed:
            raise ValueError("external invocation report cannot allow execution")
        if (
            self.external_call_performed_by_invocation
            or self.credential_material_loaded_by_invocation
            or self.raw_payload_loaded_by_invocation
            or self.production_database_mutated_by_invocation
            or self.safety_api_called_by_invocation
            or self.phase1_l0_l4_state_mutated_by_invocation
            or self.runtime_safety_truth_mutated_by_invocation
            or self.outbound_transport_invoked_by_invocation
            or self.hardware_control_performed_by_invocation
        ):
            raise ValueError("external invocation report cannot perform effects")
        return self


class ProductionSafetyQualificationExternalResultArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_safety_qualification_external_result_artifact"
    artifact_version: str = "production_safety_qualification_external_result_artifact.v0"
    submitted_artifact_kind: str = Field(min_length=1)
    submitted_artifact_ref: str = Field(min_length=1)
    submitted_artifact_sha256: str = Field(min_length=1)
    reviewer_ref: str | None = None
    reviewer_sha256: str | None = None
    source_integrity_evidence_present: bool = False
    max_age_metadata_present: bool = False
    accepted: bool = False
    credential_material_embedded: bool = False
    raw_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_external_result_artifact(
        self,
    ) -> "ProductionSafetyQualificationExternalResultArtifact":
        _assert_qualification_ref("submitted_artifact_ref", self.submitted_artifact_ref)
        if (self.reviewer_ref is None) != (self.reviewer_sha256 is None):
            raise ValueError("reviewer_ref and reviewer_sha256 must be paired")
        if self.reviewer_ref is not None:
            _assert_qualification_ref("reviewer_ref", self.reviewer_ref)
        if self.credential_material_embedded or self.raw_payload_embedded:
            raise ValueError("external result artifact cannot embed sensitive data")
        return self


class ProductionSafetyQualificationExternalResultReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = (
        "scout_production_safety_qualification_external_result_receipt"
    )
    artifact_version: str = (
        "production_safety_qualification_external_result_receipt.v0"
    )
    gap_kind: ProductionSafetyQualificationGapKind
    action: ProductionSafetyQualificationGapAction
    external_action_kind: ProductionSafetyQualificationExternalActionKind
    area: ProductionSafetyQualificationArea | None = None
    threat_id: ProductionSafetyQualificationThreatId | None = None
    mode_id: ProductionSafetyQualificationModeId | None = None
    accepted: bool = False
    external_executor_ref: str | None = None
    external_executor_sha256: str | None = None
    executor_invocation_ref: str | None = None
    executor_invocation_sha256: str | None = None
    result_artifact_kind: str | None = None
    result_ref: str | None = None
    result_sha256: str | None = None
    result_observed_at: datetime | None = None
    reviewer_ref: str | None = None
    reviewer_sha256: str | None = None
    provided_artifacts: list[ProductionSafetyQualificationExternalResultArtifact] = (
        Field(default_factory=list)
    )
    source_integrity_evidence_present: bool = False
    max_age_metadata_present: bool = False
    execution_allowed: Literal[False] = False
    credential_material_embedded: bool = False
    raw_payload_embedded: bool = False
    safety_api_called_by_result_receipt: bool = False
    phase1_l0_l4_state_mutated_by_result_receipt: bool = False
    runtime_safety_truth_mutated_by_result_receipt: bool = False
    outbound_transport_invoked_by_result_receipt: bool = False
    hardware_control_performed_by_result_receipt: bool = False

    @model_validator(mode="after")
    def enforce_external_result_receipt(
        self,
    ) -> "ProductionSafetyQualificationExternalResultReceipt":
        for ref_name, ref_value, sha_name, sha_value in (
            (
                "external_executor_ref",
                self.external_executor_ref,
                "external_executor_sha256",
                self.external_executor_sha256,
            ),
            (
                "executor_invocation_ref",
                self.executor_invocation_ref,
                "executor_invocation_sha256",
                self.executor_invocation_sha256,
            ),
            ("result_ref", self.result_ref, "result_sha256", self.result_sha256),
            ("reviewer_ref", self.reviewer_ref, "reviewer_sha256", self.reviewer_sha256),
        ):
            if (ref_value is None) != (sha_value is None):
                raise ValueError(f"{ref_name} and {sha_name} must be paired")
            if ref_value is not None:
                _assert_qualification_ref(ref_name, ref_value)
        if self.execution_allowed:
            raise ValueError("external result receipt cannot allow execution")
        if self.credential_material_embedded or self.raw_payload_embedded:
            raise ValueError("external result receipt cannot embed sensitive data")
        if (
            self.safety_api_called_by_result_receipt
            or self.phase1_l0_l4_state_mutated_by_result_receipt
            or self.runtime_safety_truth_mutated_by_result_receipt
            or self.outbound_transport_invoked_by_result_receipt
            or self.hardware_control_performed_by_result_receipt
        ):
            raise ValueError("external result receipt cannot perform runtime effects")
        return self


class ProductionSafetyQualificationExternalResultManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = (
        "scout_production_safety_qualification_external_result_manifest"
    )
    artifact_version: str = (
        "production_safety_qualification_external_result_manifest.v0"
    )
    source_provider: str = "scout_runtime_safety_production_qualification"
    source_path: str
    external_invocation_report_ref: str
    external_invocation_report_sha256: str
    receipts: list[ProductionSafetyQualificationExternalResultReceipt] = Field(
        default_factory=list
    )
    external_call_performed_by_result_manifest: bool = False
    credential_material_loaded_by_result_manifest: bool = False
    raw_payload_loaded_by_result_manifest: bool = False
    production_database_mutated_by_result_manifest: bool = False
    safety_api_called_by_result_manifest: bool = False
    phase1_l0_l4_state_mutated_by_result_manifest: bool = False
    runtime_safety_truth_mutated_by_result_manifest: bool = False
    outbound_transport_invoked_by_result_manifest: bool = False
    hardware_control_performed_by_result_manifest: bool = False

    @model_validator(mode="after")
    def enforce_external_result_manifest(
        self,
    ) -> "ProductionSafetyQualificationExternalResultManifest":
        _assert_qualification_ref("source_path", self.source_path)
        _assert_qualification_ref(
            "external_invocation_report_ref",
            self.external_invocation_report_ref,
        )
        keys = [_external_result_key(receipt) for receipt in self.receipts]
        if len(keys) != len(set(keys)):
            raise ValueError("external result receipts must be unique")
        if (
            self.external_call_performed_by_result_manifest
            or self.credential_material_loaded_by_result_manifest
            or self.raw_payload_loaded_by_result_manifest
            or self.production_database_mutated_by_result_manifest
            or self.safety_api_called_by_result_manifest
            or self.phase1_l0_l4_state_mutated_by_result_manifest
            or self.runtime_safety_truth_mutated_by_result_manifest
            or self.outbound_transport_invoked_by_result_manifest
            or self.hardware_control_performed_by_result_manifest
        ):
            raise ValueError("external result manifest cannot perform effects")
        return self


class ProductionSafetyQualificationExternalResultRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gap_kind: ProductionSafetyQualificationGapKind
    action: ProductionSafetyQualificationGapAction
    external_action_kind: ProductionSafetyQualificationExternalActionKind
    status: ProductionSafetyQualificationExternalResultRowStatus
    area: ProductionSafetyQualificationArea | None = None
    threat_id: ProductionSafetyQualificationThreatId | None = None
    mode_id: ProductionSafetyQualificationModeId | None = None
    result_receipt_recorded: bool = False
    ready_for_evidence_fulfillment: bool = False
    execution_allowed: Literal[False] = False
    external_executor_ref: str | None = None
    external_executor_sha256: str | None = None
    executor_invocation_ref: str | None = None
    executor_invocation_sha256: str | None = None
    result_artifact_kind: str | None = None
    result_ref: str | None = None
    result_sha256: str | None = None
    result_observed_at: datetime | None = None
    reviewer_ref: str | None = None
    reviewer_sha256: str | None = None
    provided_artifacts: list[ProductionSafetyQualificationExternalResultArtifact] = (
        Field(default_factory=list)
    )
    blockers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_external_result_row(
        self,
    ) -> "ProductionSafetyQualificationExternalResultRow":
        recorded = self.status == "result_receipt_recorded"
        if self.result_receipt_recorded != recorded:
            raise ValueError("result_receipt_recorded must match row status")
        if self.ready_for_evidence_fulfillment != recorded:
            raise ValueError("ready_for_evidence_fulfillment must match row status")
        if recorded and self.blockers:
            raise ValueError("recorded result row cannot contain blockers")
        if not recorded and not self.blockers:
            raise ValueError("blocked result row requires blockers")
        if self.execution_allowed:
            raise ValueError("external result row cannot allow execution")
        return self


class ProductionSafetyQualificationExternalResultReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = (
        "scout_production_safety_qualification_external_result_report"
    )
    artifact_version: str = "production_safety_qualification_external_result_report.v0"
    source_provider: str = "scout_runtime_safety_production_qualification"
    source_path: str
    sha256: str
    status: ProductionSafetyQualificationExternalResultReportStatus
    external_invocation_report_ref: str
    external_invocation_report_sha256: str
    result_manifest_ref: str
    result_manifest_sha256: str
    external_authorization_report_ref: str
    external_authorization_report_sha256: str
    external_action_packet_ref: str
    external_action_packet_sha256: str
    remediation_report_ref: str
    remediation_report_sha256: str
    rows: list[ProductionSafetyQualificationExternalResultRow] = Field(
        default_factory=list
    )
    result_receipt_count: int = 0
    blocked_result_count: int = 0
    all_result_receipts_recorded: bool = False
    ready_for_evidence_fulfillment: bool = False
    ready_for_production_cutover: bool = False
    execution_allowed: Literal[False] = False
    external_call_performed_by_result_intake: bool = False
    credential_material_loaded_by_result_intake: bool = False
    raw_payload_loaded_by_result_intake: bool = False
    production_database_mutated_by_result_intake: bool = False
    safety_api_called_by_result_intake: bool = False
    phase1_l0_l4_state_mutated_by_result_intake: bool = False
    runtime_safety_truth_mutated_by_result_intake: bool = False
    outbound_transport_invoked_by_result_intake: bool = False
    hardware_control_performed_by_result_intake: bool = False
    limitations: list[str] = Field(default_factory=list)
    boundary: ProductionSafetyQualificationBoundary = Field(
        default_factory=ProductionSafetyQualificationBoundary
    )

    @model_validator(mode="after")
    def enforce_external_result_report(
        self,
    ) -> "ProductionSafetyQualificationExternalResultReport":
        recorded_rows = [row for row in self.rows if row.result_receipt_recorded]
        blocked_rows = [row for row in self.rows if not row.result_receipt_recorded]
        if self.result_receipt_count != len(recorded_rows):
            raise ValueError("result_receipt_count must match rows")
        if self.blocked_result_count != len(blocked_rows):
            raise ValueError("blocked_result_count must match rows")
        if self.status == "no_external_result_required" and self.rows:
            raise ValueError("no-result report cannot contain rows")
        if self.status == "external_results_recorded" and (
            not self.rows or blocked_rows
        ):
            raise ValueError("recorded result report requires only ready rows")
        if self.status == "blocked_external_results_incomplete" and not blocked_rows:
            raise ValueError("blocked result report requires blocked rows")
        recorded = self.status == "external_results_recorded"
        if self.all_result_receipts_recorded != (
            self.status in {"no_external_result_required", "external_results_recorded"}
        ):
            raise ValueError("all_result_receipts_recorded must match status")
        if self.ready_for_evidence_fulfillment != recorded:
            raise ValueError("ready_for_evidence_fulfillment must match status")
        if self.ready_for_production_cutover:
            raise ValueError("external result report cannot claim production cutover")
        if self.execution_allowed:
            raise ValueError("external result report cannot allow execution")
        if (
            self.external_call_performed_by_result_intake
            or self.credential_material_loaded_by_result_intake
            or self.raw_payload_loaded_by_result_intake
            or self.production_database_mutated_by_result_intake
            or self.safety_api_called_by_result_intake
            or self.phase1_l0_l4_state_mutated_by_result_intake
            or self.runtime_safety_truth_mutated_by_result_intake
            or self.outbound_transport_invoked_by_result_intake
            or self.hardware_control_performed_by_result_intake
        ):
            raise ValueError("external result report cannot perform effects")
        return self


class ProductionSafetyQualificationExternalResultEvidenceBridgeRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_kind: ProductionSafetyQualificationEvidenceRequestKind
    source_gap_kind: ProductionSafetyQualificationGapKind | None = None
    action: ProductionSafetyQualificationGapAction | None = None
    area: ProductionSafetyQualificationArea | None = None
    threat_id: ProductionSafetyQualificationThreatId | None = None
    mode_id: ProductionSafetyQualificationModeId | None = None
    status: ProductionSafetyQualificationExternalResultEvidenceBridgeRowStatus
    submitted_artifact_kind: str | None = None
    submitted_artifact_ref: str | None = None
    submitted_artifact_sha256: str | None = None
    bridged_to_fulfillment_submission: bool = False
    blockers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_external_result_bridge_row(
        self,
    ) -> "ProductionSafetyQualificationExternalResultEvidenceBridgeRow":
        bridged = self.status == "bridged_to_fulfillment_submission"
        if self.bridged_to_fulfillment_submission != bridged:
            raise ValueError("bridged_to_fulfillment_submission must match row status")
        if bridged and self.blockers:
            raise ValueError("bridged external result row cannot contain blockers")
        if not bridged and not self.blockers:
            raise ValueError("blocked external result bridge row requires blockers")
        return self


class ProductionSafetyQualificationExternalResultEvidenceBridgeReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = (
        "scout_production_safety_qualification_external_result_evidence_bridge"
    )
    artifact_version: str = (
        "production_safety_qualification_external_result_evidence_bridge.v0"
    )
    source_provider: str = "scout_runtime_safety_production_qualification"
    source_path: str
    sha256: str
    status: ProductionSafetyQualificationExternalResultEvidenceBridgeStatus
    request_pack_ref: str
    request_pack_sha256: str
    external_result_report_ref: str
    external_result_report_sha256: str
    fulfillment_manifest: ProductionSafetyQualificationEvidenceFulfillmentManifest | None = (
        None
    )
    fulfillment_manifest_sha256: str | None = None
    rows: list[ProductionSafetyQualificationExternalResultEvidenceBridgeRow] = Field(
        default_factory=list
    )
    bridged_request_count: int = 0
    blocked_request_count: int = 0
    ready_for_fulfillment_intake: bool = False
    ready_for_production_cutover: bool = False
    execution_allowed: Literal[False] = False
    external_call_performed_by_bridge: bool = False
    credential_material_loaded_by_bridge: bool = False
    raw_payload_loaded_by_bridge: bool = False
    production_database_mutated_by_bridge: bool = False
    safety_api_called_by_bridge: bool = False
    phase1_l0_l4_state_mutated_by_bridge: bool = False
    runtime_safety_truth_mutated_by_bridge: bool = False
    outbound_transport_invoked_by_bridge: bool = False
    hardware_control_performed_by_bridge: bool = False
    limitations: list[str] = Field(default_factory=list)
    boundary: ProductionSafetyQualificationBoundary = Field(
        default_factory=ProductionSafetyQualificationBoundary
    )

    @model_validator(mode="after")
    def enforce_external_result_bridge_report(
        self,
    ) -> "ProductionSafetyQualificationExternalResultEvidenceBridgeReport":
        bridged_rows = [
            row for row in self.rows if row.bridged_to_fulfillment_submission
        ]
        blocked_rows = [
            row for row in self.rows if not row.bridged_to_fulfillment_submission
        ]
        if self.bridged_request_count != len(bridged_rows):
            raise ValueError("bridged_request_count must match rows")
        if self.blocked_request_count != len(blocked_rows):
            raise ValueError("blocked_request_count must match rows")
        if self.status == "no_external_result_bridge_required" and self.rows:
            raise ValueError("no-bridge report cannot contain rows")
        if self.status == "external_result_bridge_ready" and (
            not self.rows or blocked_rows or self.fulfillment_manifest is None
        ):
            raise ValueError("ready bridge report requires manifest and ready rows")
        if self.status == "blocked_external_result_bridge_incomplete" and not blocked_rows:
            raise ValueError("blocked bridge report requires blocked rows")
        if self.ready_for_fulfillment_intake != (
            self.status == "external_result_bridge_ready"
        ):
            raise ValueError("ready_for_fulfillment_intake must match status")
        if (self.fulfillment_manifest is None) != (
            self.fulfillment_manifest_sha256 is None
        ):
            raise ValueError("fulfillment manifest refs must be paired")
        if self.ready_for_production_cutover:
            raise ValueError("external result evidence bridge cannot claim cutover")
        if self.execution_allowed:
            raise ValueError("external result evidence bridge cannot allow execution")
        if (
            self.external_call_performed_by_bridge
            or self.credential_material_loaded_by_bridge
            or self.raw_payload_loaded_by_bridge
            or self.production_database_mutated_by_bridge
            or self.safety_api_called_by_bridge
            or self.phase1_l0_l4_state_mutated_by_bridge
            or self.runtime_safety_truth_mutated_by_bridge
            or self.outbound_transport_invoked_by_bridge
            or self.hardware_control_performed_by_bridge
        ):
            raise ValueError("external result evidence bridge cannot perform effects")
        return self


class ProductionSafetyQualificationExternalResultRemediationClosureReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = (
        "scout_production_safety_qualification_external_result_remediation_closure"
    )
    artifact_version: str = (
        "production_safety_qualification_external_result_remediation_closure.v0"
    )
    source_provider: str = "scout_runtime_safety_production_qualification"
    source_path: str
    sha256: str
    status: ProductionSafetyQualificationExternalResultRemediationClosureStatus
    gap_plan_ref: str
    gap_plan_sha256: str
    request_pack_ref: str
    request_pack_sha256: str
    external_result_bridge_ref: str
    external_result_bridge_sha256: str
    source_package_ref: str | None = None
    source_package_sha256: str | None = None
    bridge_report: ProductionSafetyQualificationExternalResultEvidenceBridgeReport
    source_integrity_report: (
        ProductionSafetyQualificationEvidenceFulfillmentSourceIntegrityReport | None
    ) = None
    fulfillment_report: ProductionSafetyQualificationEvidenceFulfillmentReport | None = (
        None
    )
    remediation_report: ProductionSafetyQualificationRemediationReadinessReport | None = (
        None
    )
    ready_for_dossier_rerun: bool = False
    ready_for_production_cutover: bool = False
    execution_allowed: Literal[False] = False
    external_call_performed_by_closure: bool = False
    credential_material_loaded_by_closure: bool = False
    raw_payload_loaded_by_closure: bool = False
    production_database_mutated_by_closure: bool = False
    safety_api_called_by_closure: bool = False
    phase1_l0_l4_state_mutated_by_closure: bool = False
    runtime_safety_truth_mutated_by_closure: bool = False
    outbound_transport_invoked_by_closure: bool = False
    hardware_control_performed_by_closure: bool = False
    limitations: list[str] = Field(default_factory=list)
    boundary: ProductionSafetyQualificationBoundary = Field(
        default_factory=ProductionSafetyQualificationBoundary
    )

    @model_validator(mode="after")
    def enforce_external_result_remediation_closure_report(
        self,
    ) -> "ProductionSafetyQualificationExternalResultRemediationClosureReport":
        ready = self.status == "external_result_remediation_ready_for_dossier_rerun"
        if self.ready_for_dossier_rerun != ready:
            raise ValueError("ready_for_dossier_rerun must match closure status")
        if (self.source_package_ref is None) != (self.source_package_sha256 is None):
            raise ValueError("source package refs must be paired")
        if self.status == "no_external_result_remediation_required" and (
            self.bridge_report.status != "no_external_result_bridge_required"
            or self.source_integrity_report is not None
            or self.fulfillment_report is not None
            or self.remediation_report is not None
        ):
            raise ValueError("no-remediation closure cannot contain downstream reports")
        if self.status == "blocked_external_result_bridge_incomplete" and (
            self.bridge_report.status
            not in {
                "blocked_external_result_bridge_incomplete",
                "no_external_result_bridge_required",
            }
        ):
            raise ValueError("bridge-incomplete closure requires blocked bridge report")
        if (
            self.status == "blocked_external_result_source_package_missing"
            and self.source_package_ref is not None
        ):
            raise ValueError("source-package-missing closure cannot contain package refs")
        if self.status == "blocked_external_result_source_integrity_failed" and (
            self.source_integrity_report is None
            or self.source_integrity_report.all_fulfillment_sources_verified
        ):
            raise ValueError(
                "source-integrity-failed closure requires failed source report"
            )
        if self.status == "blocked_external_result_fulfillment_incomplete" and (
            self.fulfillment_report is None
            or self.fulfillment_report.all_requested_evidence_fulfilled
        ):
            raise ValueError("fulfillment-incomplete closure requires failed fulfillment")
        if self.status == "blocked_external_result_remediation_incomplete" and (
            self.remediation_report is None
            or self.remediation_report.ready_for_dossier_rerun
        ):
            raise ValueError("remediation-incomplete closure requires blocked remediation")
        if ready and (
            self.bridge_report.status != "external_result_bridge_ready"
            or self.source_integrity_report is None
            or not self.source_integrity_report.all_fulfillment_sources_verified
            or self.fulfillment_report is None
            or not self.fulfillment_report.all_requested_evidence_fulfilled
            or self.remediation_report is None
            or not self.remediation_report.ready_for_dossier_rerun
        ):
            raise ValueError("ready closure requires all downstream gates ready")
        if self.ready_for_production_cutover:
            raise ValueError("external result remediation closure cannot claim cutover")
        if self.execution_allowed:
            raise ValueError("external result remediation closure cannot allow execution")
        if (
            self.external_call_performed_by_closure
            or self.credential_material_loaded_by_closure
            or self.raw_payload_loaded_by_closure
            or self.production_database_mutated_by_closure
            or self.safety_api_called_by_closure
            or self.phase1_l0_l4_state_mutated_by_closure
            or self.runtime_safety_truth_mutated_by_closure
            or self.outbound_transport_invoked_by_closure
            or self.hardware_control_performed_by_closure
        ):
            raise ValueError("external result remediation closure cannot perform effects")
        return self


class ProductionSafetyQualificationDossierRerunReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_safety_qualification_dossier_rerun"
    artifact_version: str = "production_safety_qualification_dossier_rerun.v0"
    source_provider: str = "scout_runtime_safety_production_qualification"
    source_path: str
    sha256: str
    status: ProductionSafetyQualificationDossierRerunStatus
    external_result_closure_ref: str
    external_result_closure_sha256: str
    dossier_manifest_ref: str
    dossier_manifest_sha256: str
    dossier_report_ref: str | None = None
    dossier_report_sha256: str | None = None
    closure_report: ProductionSafetyQualificationExternalResultRemediationClosureReport
    dossier_report: ProductionSafetyQualificationDossierReport | None = None
    dossier_status: ProductionSafetyQualificationDossierStatus | None = None
    cutover_audit_status: ProductionSafetyCutoverReadinessStatus | None = None
    threat_coverage_status: (
        ProductionSafetyQualificationDossierThreatCoverageStatus | None
    ) = None
    local_dossier_validator_executed: bool = False
    dossier_report_ready_for_cutover: bool = False
    ready_for_production_cutover: bool = False
    execution_allowed: Literal[False] = False
    external_call_performed_by_dossier_rerun: bool = False
    credential_material_loaded_by_dossier_rerun: bool = False
    raw_payload_loaded_by_dossier_rerun: bool = False
    production_database_mutated_by_dossier_rerun: bool = False
    safety_api_called_by_dossier_rerun: bool = False
    phase1_l0_l4_state_mutated_by_dossier_rerun: bool = False
    runtime_safety_truth_mutated_by_dossier_rerun: bool = False
    outbound_transport_invoked_by_dossier_rerun: bool = False
    hardware_control_performed_by_dossier_rerun: bool = False
    limitations: list[str] = Field(default_factory=list)
    boundary: ProductionSafetyQualificationBoundary = Field(
        default_factory=ProductionSafetyQualificationBoundary
    )

    @model_validator(mode="after")
    def enforce_dossier_rerun_report(
        self,
    ) -> "ProductionSafetyQualificationDossierRerunReport":
        if self.external_result_closure_ref != self.closure_report.source_path:
            raise ValueError("closure ref must match closure report source_path")
        if self.external_result_closure_sha256 != self.closure_report.sha256:
            raise ValueError("closure sha256 must match closure report")
        if (self.dossier_report_ref is None) != (
            self.dossier_report_sha256 is None
        ):
            raise ValueError("dossier report refs must be paired")
        if self.local_dossier_validator_executed != (
            self.dossier_report is not None
        ):
            raise ValueError(
                "local_dossier_validator_executed must match dossier report presence"
            )
        if self.dossier_report is None and (
            self.dossier_status is not None
            or self.cutover_audit_status is not None
            or self.threat_coverage_status is not None
            or self.dossier_report_ref is not None
            or self.dossier_report_sha256 is not None
            or self.dossier_report_ready_for_cutover
        ):
            raise ValueError("missing dossier report cannot expose dossier status")
        if self.dossier_report is not None:
            if self.dossier_report_ref != self.dossier_report.source_path:
                raise ValueError("dossier report ref must match report source_path")
            if self.dossier_report_sha256 != self.dossier_report.sha256:
                raise ValueError("dossier report sha256 must match report")
            if self.dossier_status != self.dossier_report.status:
                raise ValueError("dossier_status must match dossier report")
            if self.cutover_audit_status != self.dossier_report.cutover_audit.status:
                raise ValueError("cutover_audit_status must match dossier report")
            if (
                self.threat_coverage_status
                != self.dossier_report.threat_coverage_status
            ):
                raise ValueError("threat_coverage_status must match dossier report")
            if (
                self.dossier_report_ready_for_cutover
                != self.dossier_report.ready_for_production_cutover
            ):
                raise ValueError(
                    "dossier_report_ready_for_cutover must match dossier report"
                )
        if self.status == "no_dossier_rerun_required":
            if (
                self.closure_report.status
                != "no_external_result_remediation_required"
            ):
                raise ValueError("no rerun status requires no-remediation closure")
            if self.local_dossier_validator_executed:
                raise ValueError("no rerun status cannot execute dossier validator")
        elif self.status == "blocked_external_result_remediation_incomplete":
            if self.closure_report.ready_for_dossier_rerun:
                raise ValueError("blocked remediation status requires blocked closure")
            if self.local_dossier_validator_executed:
                raise ValueError("blocked remediation status cannot execute rerun")
        else:
            if not self.closure_report.ready_for_dossier_rerun:
                raise ValueError("dossier rerun statuses require ready closure")
            if self.dossier_report is None:
                raise ValueError("dossier rerun statuses require dossier report")
            if self.status == "dossier_rerun_ready_for_cutover_review" and (
                not self.dossier_report_ready_for_cutover
                or self.dossier_status != "dossier_ready_for_production_cutover"
            ):
                raise ValueError("ready rerun status requires ready dossier report")
            if self.status == "blocked_dossier_rerun_incomplete" and (
                self.dossier_status != "blocked_dossier_incomplete"
            ):
                raise ValueError("incomplete rerun status requires incomplete dossier")
            if self.status == "blocked_dossier_rerun_failed" and (
                self.dossier_status != "blocked_dossier_failed"
            ):
                raise ValueError("failed rerun status requires failed dossier")
        if self.ready_for_production_cutover:
            raise ValueError("dossier rerun report cannot claim production cutover")
        if self.execution_allowed:
            raise ValueError("dossier rerun report cannot allow execution")
        if (
            self.external_call_performed_by_dossier_rerun
            or self.credential_material_loaded_by_dossier_rerun
            or self.raw_payload_loaded_by_dossier_rerun
            or self.production_database_mutated_by_dossier_rerun
            or self.safety_api_called_by_dossier_rerun
            or self.phase1_l0_l4_state_mutated_by_dossier_rerun
            or self.runtime_safety_truth_mutated_by_dossier_rerun
            or self.outbound_transport_invoked_by_dossier_rerun
            or self.hardware_control_performed_by_dossier_rerun
        ):
            raise ValueError("dossier rerun report cannot perform effects")
        return self


class ProductionSafetyQualificationCutoverAuthorizationManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = (
        "scout_production_safety_qualification_cutover_authorization_manifest"
    )
    artifact_version: str = (
        "production_safety_qualification_cutover_authorization_manifest.v0"
    )
    source_provider: str = "scout_runtime_safety_production_qualification"
    source_path: str
    dossier_rerun_ref: str
    dossier_rerun_sha256: str
    reference_time: datetime
    authorized: bool = False
    operator_identity_ref: str | None = None
    operator_identity_sha256: str | None = None
    authorization_ref: str | None = None
    authorization_sha256: str | None = None
    reviewed_effect_boundary_ref: str | None = None
    reviewed_effect_boundary_sha256: str | None = None
    rollback_plan_ref: str | None = None
    rollback_plan_sha256: str | None = None
    production_change_request_ref: str | None = None
    production_change_request_sha256: str | None = None
    idempotency_key: str | None = None
    authorization_observed_at: datetime | None = None
    expires_at: datetime | None = None
    explicit_confirmation_phrase: str | None = None
    execution_allowed: Literal[False] = False
    external_call_performed_by_cutover_authorization: bool = False
    credential_material_loaded_by_cutover_authorization: bool = False
    raw_payload_loaded_by_cutover_authorization: bool = False
    production_database_mutated_by_cutover_authorization: bool = False
    safety_api_called_by_cutover_authorization: bool = False
    phase1_l0_l4_state_mutated_by_cutover_authorization: bool = False
    runtime_safety_truth_mutated_by_cutover_authorization: bool = False
    outbound_transport_invoked_by_cutover_authorization: bool = False
    hardware_control_performed_by_cutover_authorization: bool = False

    @model_validator(mode="after")
    def enforce_cutover_authorization_manifest(
        self,
    ) -> "ProductionSafetyQualificationCutoverAuthorizationManifest":
        _assert_qualification_ref("source_path", self.source_path)
        _assert_qualification_ref("dossier_rerun_ref", self.dossier_rerun_ref)
        for ref_name, ref_value, sha_name, sha_value in (
            (
                "operator_identity_ref",
                self.operator_identity_ref,
                "operator_identity_sha256",
                self.operator_identity_sha256,
            ),
            (
                "authorization_ref",
                self.authorization_ref,
                "authorization_sha256",
                self.authorization_sha256,
            ),
            (
                "reviewed_effect_boundary_ref",
                self.reviewed_effect_boundary_ref,
                "reviewed_effect_boundary_sha256",
                self.reviewed_effect_boundary_sha256,
            ),
            (
                "rollback_plan_ref",
                self.rollback_plan_ref,
                "rollback_plan_sha256",
                self.rollback_plan_sha256,
            ),
            (
                "production_change_request_ref",
                self.production_change_request_ref,
                "production_change_request_sha256",
                self.production_change_request_sha256,
            ),
        ):
            if (ref_value is None) != (sha_value is None):
                raise ValueError(f"{ref_name} and {sha_name} must be paired")
            if ref_value is not None:
                _assert_qualification_ref(ref_name, ref_value)
        if (
            self.authorization_observed_at is not None
            and self.expires_at is not None
            and _as_utc(self.expires_at) <= _as_utc(self.authorization_observed_at)
        ):
            raise ValueError(
                "cutover authorization expires_at must be after observation"
            )
        if self.execution_allowed:
            raise ValueError("cutover authorization manifest cannot allow execution")
        if (
            self.external_call_performed_by_cutover_authorization
            or self.credential_material_loaded_by_cutover_authorization
            or self.raw_payload_loaded_by_cutover_authorization
            or self.production_database_mutated_by_cutover_authorization
            or self.safety_api_called_by_cutover_authorization
            or self.phase1_l0_l4_state_mutated_by_cutover_authorization
            or self.runtime_safety_truth_mutated_by_cutover_authorization
            or self.outbound_transport_invoked_by_cutover_authorization
            or self.hardware_control_performed_by_cutover_authorization
        ):
            raise ValueError("cutover authorization manifest cannot perform effects")
        return self


class ProductionSafetyQualificationCutoverAuthorizationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = (
        "scout_production_safety_qualification_cutover_authorization_report"
    )
    artifact_version: str = (
        "production_safety_qualification_cutover_authorization_report.v0"
    )
    source_provider: str = "scout_runtime_safety_production_qualification"
    source_path: str
    sha256: str
    status: ProductionSafetyQualificationCutoverAuthorizationStatus
    dossier_rerun_ref: str
    dossier_rerun_sha256: str
    authorization_manifest_ref: str
    authorization_manifest_sha256: str
    dossier_report_ref: str | None = None
    dossier_report_sha256: str | None = None
    dossier_status: ProductionSafetyQualificationDossierStatus | None = None
    cutover_audit_status: ProductionSafetyCutoverReadinessStatus | None = None
    threat_coverage_status: (
        ProductionSafetyQualificationDossierThreatCoverageStatus | None
    ) = None
    operator_identity_ref: str | None = None
    operator_identity_sha256: str | None = None
    authorization_ref: str | None = None
    authorization_sha256: str | None = None
    reviewed_effect_boundary_ref: str | None = None
    reviewed_effect_boundary_sha256: str | None = None
    rollback_plan_ref: str | None = None
    rollback_plan_sha256: str | None = None
    production_change_request_ref: str | None = None
    production_change_request_sha256: str | None = None
    idempotency_key: str | None = None
    authorization_observed_at: datetime | None = None
    expires_at: datetime | None = None
    explicit_confirmation_phrase: str | None = None
    cutover_authorization_recorded: bool = False
    ready_for_human_cutover_review: bool = False
    ready_for_production_cutover: bool = False
    execution_allowed: Literal[False] = False
    blockers: list[str] = Field(default_factory=list)
    dossier_rerun_report: ProductionSafetyQualificationDossierRerunReport
    authorization_manifest: ProductionSafetyQualificationCutoverAuthorizationManifest
    external_call_performed_by_cutover_authorization: bool = False
    credential_material_loaded_by_cutover_authorization: bool = False
    raw_payload_loaded_by_cutover_authorization: bool = False
    production_database_mutated_by_cutover_authorization: bool = False
    safety_api_called_by_cutover_authorization: bool = False
    phase1_l0_l4_state_mutated_by_cutover_authorization: bool = False
    runtime_safety_truth_mutated_by_cutover_authorization: bool = False
    outbound_transport_invoked_by_cutover_authorization: bool = False
    hardware_control_performed_by_cutover_authorization: bool = False
    limitations: list[str] = Field(default_factory=list)
    boundary: ProductionSafetyQualificationBoundary = Field(
        default_factory=ProductionSafetyQualificationBoundary
    )

    @model_validator(mode="after")
    def enforce_cutover_authorization_report(
        self,
    ) -> "ProductionSafetyQualificationCutoverAuthorizationReport":
        recorded = self.status == "cutover_authorization_recorded"
        if self.cutover_authorization_recorded != recorded:
            raise ValueError("cutover_authorization_recorded must match status")
        if self.ready_for_human_cutover_review != recorded:
            raise ValueError("ready_for_human_cutover_review must match status")
        if self.dossier_rerun_ref != self.dossier_rerun_report.source_path:
            raise ValueError("dossier rerun ref must match rerun report")
        if self.dossier_rerun_sha256 != self.dossier_rerun_report.sha256:
            raise ValueError("dossier rerun sha256 must match rerun report")
        if self.authorization_manifest_ref != self.authorization_manifest.source_path:
            raise ValueError("authorization manifest ref must match manifest")
        if self.authorization_manifest_sha256 != _cutover_authorization_manifest_sha256(
            self.authorization_manifest
        ):
            raise ValueError("authorization manifest sha256 must match manifest")
        if self.authorization_manifest.dossier_rerun_ref != self.dossier_rerun_ref:
            raise ValueError("authorization manifest rerun ref must match report")
        if self.authorization_manifest.dossier_rerun_sha256 != self.dossier_rerun_sha256:
            raise ValueError("authorization manifest rerun sha256 must match report")
        if (self.dossier_report_ref is None) != (
            self.dossier_report_sha256 is None
        ):
            raise ValueError("dossier report refs must be paired")
        if self.dossier_rerun_report.dossier_report is None and (
            self.dossier_report_ref is not None
            or self.dossier_status is not None
            or self.cutover_audit_status is not None
            or self.threat_coverage_status is not None
        ):
            raise ValueError("missing rerun dossier cannot expose dossier status")
        if self.dossier_rerun_report.dossier_report is not None:
            dossier_report = self.dossier_rerun_report.dossier_report
            if self.dossier_report_ref != dossier_report.source_path:
                raise ValueError("dossier report ref must match nested dossier")
            if self.dossier_report_sha256 != dossier_report.sha256:
                raise ValueError("dossier report sha256 must match nested dossier")
            if self.dossier_status != dossier_report.status:
                raise ValueError("dossier status must match nested dossier")
            if self.cutover_audit_status != dossier_report.cutover_audit.status:
                raise ValueError("cutover audit status must match nested dossier")
            if self.threat_coverage_status != dossier_report.threat_coverage_status:
                raise ValueError("threat coverage status must match nested dossier")
        for field_name in (
            "operator_identity_ref",
            "operator_identity_sha256",
            "authorization_ref",
            "authorization_sha256",
            "reviewed_effect_boundary_ref",
            "reviewed_effect_boundary_sha256",
            "rollback_plan_ref",
            "rollback_plan_sha256",
            "production_change_request_ref",
            "production_change_request_sha256",
            "idempotency_key",
            "authorization_observed_at",
            "expires_at",
            "explicit_confirmation_phrase",
        ):
            if getattr(self, field_name) != getattr(
                self.authorization_manifest,
                field_name,
            ):
                raise ValueError(f"{field_name} must match authorization manifest")
        if recorded and self.blockers:
            raise ValueError("recorded cutover authorization cannot contain blockers")
        if not recorded and not self.blockers:
            raise ValueError("blocked cutover authorization requires blockers")
        if recorded and (
            self.dossier_rerun_report.status
            != "dossier_rerun_ready_for_cutover_review"
            or not self.dossier_rerun_report.dossier_report_ready_for_cutover
        ):
            raise ValueError("recorded cutover authorization requires ready rerun")
        if self.ready_for_production_cutover:
            raise ValueError(
                "cutover authorization report cannot claim production cutover"
            )
        if self.execution_allowed:
            raise ValueError("cutover authorization report cannot allow execution")
        if (
            self.external_call_performed_by_cutover_authorization
            or self.credential_material_loaded_by_cutover_authorization
            or self.raw_payload_loaded_by_cutover_authorization
            or self.production_database_mutated_by_cutover_authorization
            or self.safety_api_called_by_cutover_authorization
            or self.phase1_l0_l4_state_mutated_by_cutover_authorization
            or self.runtime_safety_truth_mutated_by_cutover_authorization
            or self.outbound_transport_invoked_by_cutover_authorization
            or self.hardware_control_performed_by_cutover_authorization
        ):
            raise ValueError("cutover authorization report cannot perform effects")
        return self


class ProductionSafetyQualificationCutoverReleaseHandoffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = (
        "scout_production_safety_qualification_cutover_release_handoff_request"
    )
    artifact_version: str = (
        "production_safety_qualification_cutover_release_handoff_request.v0"
    )
    release_handoff_requested: bool = False
    operator_confirmation: bool = False
    operator_identity_ref: str | None = None
    operator_identity_sha256: str | None = None
    authorization_ref: str | None = None
    authorization_sha256: str | None = None
    reviewed_effect_boundary_ref: str | None = None
    reviewed_effect_boundary_sha256: str | None = None
    rollback_plan_ref: str | None = None
    rollback_plan_sha256: str | None = None
    production_change_request_ref: str | None = None
    production_change_request_sha256: str | None = None
    release_executor_ref: str | None = None
    release_executor_sha256: str | None = None
    release_invocation_ref: str | None = None
    release_invocation_sha256: str | None = None
    cutover_authorization_idempotency_key: str | None = None
    handoff_idempotency_key: str | None = None
    requested_at: datetime | None = None
    explicit_confirmation_phrase: str | None = None
    execution_allowed: Literal[False] = False
    external_call_performed_by_release_handoff: bool = False
    credential_material_loaded_by_release_handoff: bool = False
    raw_payload_loaded_by_release_handoff: bool = False
    production_database_mutated_by_release_handoff: bool = False
    safety_api_called_by_release_handoff: bool = False
    phase1_l0_l4_state_mutated_by_release_handoff: bool = False
    runtime_safety_truth_mutated_by_release_handoff: bool = False
    outbound_transport_invoked_by_release_handoff: bool = False
    hardware_control_performed_by_release_handoff: bool = False

    @model_validator(mode="after")
    def enforce_cutover_release_handoff_request(
        self,
    ) -> "ProductionSafetyQualificationCutoverReleaseHandoffRequest":
        for ref_name, ref_value, sha_name, sha_value in (
            (
                "operator_identity_ref",
                self.operator_identity_ref,
                "operator_identity_sha256",
                self.operator_identity_sha256,
            ),
            (
                "authorization_ref",
                self.authorization_ref,
                "authorization_sha256",
                self.authorization_sha256,
            ),
            (
                "reviewed_effect_boundary_ref",
                self.reviewed_effect_boundary_ref,
                "reviewed_effect_boundary_sha256",
                self.reviewed_effect_boundary_sha256,
            ),
            (
                "rollback_plan_ref",
                self.rollback_plan_ref,
                "rollback_plan_sha256",
                self.rollback_plan_sha256,
            ),
            (
                "production_change_request_ref",
                self.production_change_request_ref,
                "production_change_request_sha256",
                self.production_change_request_sha256,
            ),
            (
                "release_executor_ref",
                self.release_executor_ref,
                "release_executor_sha256",
                self.release_executor_sha256,
            ),
            (
                "release_invocation_ref",
                self.release_invocation_ref,
                "release_invocation_sha256",
                self.release_invocation_sha256,
            ),
        ):
            if (ref_value is None) != (sha_value is None):
                raise ValueError(f"{ref_name} and {sha_name} must be paired")
            if ref_value is not None:
                _assert_qualification_ref(ref_name, ref_value)
        if self.execution_allowed:
            raise ValueError("cutover release handoff request cannot allow execution")
        if (
            self.external_call_performed_by_release_handoff
            or self.credential_material_loaded_by_release_handoff
            or self.raw_payload_loaded_by_release_handoff
            or self.production_database_mutated_by_release_handoff
            or self.safety_api_called_by_release_handoff
            or self.phase1_l0_l4_state_mutated_by_release_handoff
            or self.runtime_safety_truth_mutated_by_release_handoff
            or self.outbound_transport_invoked_by_release_handoff
            or self.hardware_control_performed_by_release_handoff
        ):
            raise ValueError("cutover release handoff request cannot perform effects")
        return self


class ProductionSafetyQualificationCutoverReleaseHandoffManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = (
        "scout_production_safety_qualification_cutover_release_handoff_manifest"
    )
    artifact_version: str = (
        "production_safety_qualification_cutover_release_handoff_manifest.v0"
    )
    source_provider: str = "scout_runtime_safety_production_qualification"
    source_path: str
    cutover_authorization_report_ref: str
    cutover_authorization_report_sha256: str
    reference_time: datetime
    request: ProductionSafetyQualificationCutoverReleaseHandoffRequest | None = None
    external_call_performed_by_release_handoff: bool = False
    credential_material_loaded_by_release_handoff: bool = False
    raw_payload_loaded_by_release_handoff: bool = False
    production_database_mutated_by_release_handoff: bool = False
    safety_api_called_by_release_handoff: bool = False
    phase1_l0_l4_state_mutated_by_release_handoff: bool = False
    runtime_safety_truth_mutated_by_release_handoff: bool = False
    outbound_transport_invoked_by_release_handoff: bool = False
    hardware_control_performed_by_release_handoff: bool = False

    @model_validator(mode="after")
    def enforce_cutover_release_handoff_manifest(
        self,
    ) -> "ProductionSafetyQualificationCutoverReleaseHandoffManifest":
        _assert_qualification_ref("source_path", self.source_path)
        _assert_qualification_ref(
            "cutover_authorization_report_ref",
            self.cutover_authorization_report_ref,
        )
        if (
            self.external_call_performed_by_release_handoff
            or self.credential_material_loaded_by_release_handoff
            or self.raw_payload_loaded_by_release_handoff
            or self.production_database_mutated_by_release_handoff
            or self.safety_api_called_by_release_handoff
            or self.phase1_l0_l4_state_mutated_by_release_handoff
            or self.runtime_safety_truth_mutated_by_release_handoff
            or self.outbound_transport_invoked_by_release_handoff
            or self.hardware_control_performed_by_release_handoff
        ):
            raise ValueError("cutover release handoff manifest cannot perform effects")
        return self


class ProductionSafetyQualificationCutoverReleaseHandoffReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = (
        "scout_production_safety_qualification_cutover_release_handoff_report"
    )
    artifact_version: str = (
        "production_safety_qualification_cutover_release_handoff_report.v0"
    )
    source_provider: str = "scout_runtime_safety_production_qualification"
    source_path: str
    sha256: str
    status: ProductionSafetyQualificationCutoverReleaseHandoffStatus
    cutover_authorization_report_ref: str
    cutover_authorization_report_sha256: str
    handoff_manifest_ref: str
    handoff_manifest_sha256: str
    dossier_rerun_ref: str
    dossier_rerun_sha256: str
    dossier_report_ref: str | None = None
    dossier_report_sha256: str | None = None
    release_executor_ref: str | None = None
    release_executor_sha256: str | None = None
    release_invocation_ref: str | None = None
    release_invocation_sha256: str | None = None
    operator_identity_ref: str | None = None
    operator_identity_sha256: str | None = None
    authorization_ref: str | None = None
    authorization_sha256: str | None = None
    reviewed_effect_boundary_ref: str | None = None
    reviewed_effect_boundary_sha256: str | None = None
    rollback_plan_ref: str | None = None
    rollback_plan_sha256: str | None = None
    production_change_request_ref: str | None = None
    production_change_request_sha256: str | None = None
    cutover_authorization_idempotency_key: str | None = None
    handoff_idempotency_key: str | None = None
    requested_at: datetime | None = None
    explicit_confirmation_phrase: str | None = None
    cutover_release_handoff_recorded: bool = False
    ready_for_release_executor_handoff: bool = False
    ready_for_production_cutover: bool = False
    execution_allowed: Literal[False] = False
    blockers: list[str] = Field(default_factory=list)
    cutover_authorization_report: (
        ProductionSafetyQualificationCutoverAuthorizationReport
    )
    handoff_manifest: ProductionSafetyQualificationCutoverReleaseHandoffManifest
    external_call_performed_by_release_handoff: bool = False
    credential_material_loaded_by_release_handoff: bool = False
    raw_payload_loaded_by_release_handoff: bool = False
    production_database_mutated_by_release_handoff: bool = False
    safety_api_called_by_release_handoff: bool = False
    phase1_l0_l4_state_mutated_by_release_handoff: bool = False
    runtime_safety_truth_mutated_by_release_handoff: bool = False
    outbound_transport_invoked_by_release_handoff: bool = False
    hardware_control_performed_by_release_handoff: bool = False
    limitations: list[str] = Field(default_factory=list)
    boundary: ProductionSafetyQualificationBoundary = Field(
        default_factory=ProductionSafetyQualificationBoundary
    )

    @model_validator(mode="after")
    def enforce_cutover_release_handoff_report(
        self,
    ) -> "ProductionSafetyQualificationCutoverReleaseHandoffReport":
        recorded = self.status == "cutover_release_handoff_recorded"
        if self.cutover_release_handoff_recorded != recorded:
            raise ValueError("cutover_release_handoff_recorded must match status")
        if self.ready_for_release_executor_handoff != recorded:
            raise ValueError("ready_for_release_executor_handoff must match status")
        if (
            self.cutover_authorization_report_ref
            != self.cutover_authorization_report.source_path
        ):
            raise ValueError("authorization report ref must match report")
        if (
            self.cutover_authorization_report_sha256
            != self.cutover_authorization_report.sha256
        ):
            raise ValueError("authorization report sha256 must match report")
        if self.handoff_manifest_ref != self.handoff_manifest.source_path:
            raise ValueError("handoff manifest ref must match manifest")
        if self.handoff_manifest_sha256 != _cutover_release_handoff_manifest_sha256(
            self.handoff_manifest
        ):
            raise ValueError("handoff manifest sha256 must match manifest")
        if (
            self.handoff_manifest.cutover_authorization_report_ref
            != self.cutover_authorization_report_ref
        ):
            raise ValueError("handoff manifest authorization ref must match report")
        if (
            self.handoff_manifest.cutover_authorization_report_sha256
            != self.cutover_authorization_report_sha256
        ):
            raise ValueError("handoff manifest authorization sha256 must match report")
        rerun = self.cutover_authorization_report.dossier_rerun_report
        if self.dossier_rerun_ref != rerun.source_path:
            raise ValueError("dossier rerun ref must match authorization report")
        if self.dossier_rerun_sha256 != rerun.sha256:
            raise ValueError("dossier rerun sha256 must match authorization report")
        if rerun.dossier_report is None:
            if self.dossier_report_ref is not None or self.dossier_report_sha256 is not None:
                raise ValueError("missing nested dossier cannot expose dossier refs")
        elif self.dossier_report_ref != rerun.dossier_report.source_path:
            raise ValueError("dossier report ref must match nested dossier")
        elif self.dossier_report_sha256 != rerun.dossier_report.sha256:
            raise ValueError("dossier report sha256 must match nested dossier")
        request = self.handoff_manifest.request
        if request is None:
            request_fields = (
                "release_executor_ref",
                "release_executor_sha256",
                "release_invocation_ref",
                "release_invocation_sha256",
                "operator_identity_ref",
                "operator_identity_sha256",
                "authorization_ref",
                "authorization_sha256",
                "reviewed_effect_boundary_ref",
                "reviewed_effect_boundary_sha256",
                "rollback_plan_ref",
                "rollback_plan_sha256",
                "production_change_request_ref",
                "production_change_request_sha256",
                "cutover_authorization_idempotency_key",
                "handoff_idempotency_key",
                "requested_at",
                "explicit_confirmation_phrase",
            )
            if any(getattr(self, field_name) is not None for field_name in request_fields):
                raise ValueError("missing handoff request cannot expose request fields")
        else:
            for field_name in (
                "release_executor_ref",
                "release_executor_sha256",
                "release_invocation_ref",
                "release_invocation_sha256",
                "operator_identity_ref",
                "operator_identity_sha256",
                "authorization_ref",
                "authorization_sha256",
                "reviewed_effect_boundary_ref",
                "reviewed_effect_boundary_sha256",
                "rollback_plan_ref",
                "rollback_plan_sha256",
                "production_change_request_ref",
                "production_change_request_sha256",
                "cutover_authorization_idempotency_key",
                "handoff_idempotency_key",
                "requested_at",
                "explicit_confirmation_phrase",
            ):
                if getattr(self, field_name) != getattr(request, field_name):
                    raise ValueError(f"{field_name} must match handoff request")
        if recorded and self.blockers:
            raise ValueError("recorded cutover release handoff cannot contain blockers")
        if not recorded and not self.blockers:
            raise ValueError("blocked cutover release handoff requires blockers")
        if recorded and (
            self.cutover_authorization_report.status
            != "cutover_authorization_recorded"
            or not self.cutover_authorization_report.ready_for_human_cutover_review
        ):
            raise ValueError("recorded release handoff requires authorization")
        if self.ready_for_production_cutover:
            raise ValueError(
                "cutover release handoff report cannot claim production cutover"
            )
        if self.execution_allowed:
            raise ValueError("cutover release handoff report cannot allow execution")
        if (
            self.external_call_performed_by_release_handoff
            or self.credential_material_loaded_by_release_handoff
            or self.raw_payload_loaded_by_release_handoff
            or self.production_database_mutated_by_release_handoff
            or self.safety_api_called_by_release_handoff
            or self.phase1_l0_l4_state_mutated_by_release_handoff
            or self.runtime_safety_truth_mutated_by_release_handoff
            or self.outbound_transport_invoked_by_release_handoff
            or self.hardware_control_performed_by_release_handoff
        ):
            raise ValueError("cutover release handoff report cannot perform effects")
        return self


class ProductionSafetyQualificationCutoverReleaseEffectReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = (
        "scout_production_safety_qualification_cutover_release_effect_receipt"
    )
    artifact_version: str = (
        "production_safety_qualification_cutover_release_effect_receipt.v0"
    )
    source_provider: str = "approved_cutover_release_executor"
    source_path: str = Field(min_length=1)
    sha256: str | None = None
    cutover_release_handoff_report_ref: str | None = None
    cutover_release_handoff_report_sha256: str | None = None
    release_executor_ref: str | None = None
    release_executor_sha256: str | None = None
    release_invocation_ref: str | None = None
    release_invocation_sha256: str | None = None
    handoff_idempotency_key: str | None = None
    release_execution_ref: str | None = None
    release_execution_sha256: str | None = None
    release_result_ref: str | None = None
    release_result_sha256: str | None = None
    reviewer_ref: str | None = None
    reviewer_sha256: str | None = None
    release_observed_at: datetime | None = None
    accepted: bool = False
    executor_reported_release_completed: bool = False
    source_integrity_evidence_present: bool = False
    max_age_metadata_present: bool = False
    execution_allowed: Literal[False] = False
    credential_material_embedded: bool = False
    raw_payload_embedded: bool = False
    production_database_payload_embedded: bool = False
    runtime_safety_truth_embedded: bool = False
    safety_api_called_by_release_effect_receipt: bool = False
    phase1_l0_l4_state_mutated_by_release_effect_receipt: bool = False
    runtime_safety_truth_mutated_by_release_effect_receipt: bool = False
    outbound_transport_invoked_by_release_effect_receipt: bool = False
    hardware_control_performed_by_release_effect_receipt: bool = False

    @model_validator(mode="after")
    def enforce_cutover_release_effect_receipt(
        self,
    ) -> "ProductionSafetyQualificationCutoverReleaseEffectReceipt":
        _assert_qualification_ref("source_path", self.source_path)
        for ref_name, ref_value, sha_name, sha_value in (
            (
                "cutover_release_handoff_report_ref",
                self.cutover_release_handoff_report_ref,
                "cutover_release_handoff_report_sha256",
                self.cutover_release_handoff_report_sha256,
            ),
            (
                "release_executor_ref",
                self.release_executor_ref,
                "release_executor_sha256",
                self.release_executor_sha256,
            ),
            (
                "release_invocation_ref",
                self.release_invocation_ref,
                "release_invocation_sha256",
                self.release_invocation_sha256,
            ),
            (
                "release_execution_ref",
                self.release_execution_ref,
                "release_execution_sha256",
                self.release_execution_sha256,
            ),
            (
                "release_result_ref",
                self.release_result_ref,
                "release_result_sha256",
                self.release_result_sha256,
            ),
            ("reviewer_ref", self.reviewer_ref, "reviewer_sha256", self.reviewer_sha256),
        ):
            if (ref_value is None) != (sha_value is None):
                raise ValueError(f"{ref_name} and {sha_name} must be paired")
            if ref_value is not None:
                _assert_qualification_ref(ref_name, ref_value)
        if self.execution_allowed:
            raise ValueError("cutover release effect receipt cannot allow execution")
        if (
            self.credential_material_embedded
            or self.raw_payload_embedded
            or self.production_database_payload_embedded
            or self.runtime_safety_truth_embedded
        ):
            raise ValueError(
                "cutover release effect receipt cannot embed sensitive runtime data"
            )
        if (
            self.safety_api_called_by_release_effect_receipt
            or self.phase1_l0_l4_state_mutated_by_release_effect_receipt
            or self.runtime_safety_truth_mutated_by_release_effect_receipt
            or self.outbound_transport_invoked_by_release_effect_receipt
            or self.hardware_control_performed_by_release_effect_receipt
        ):
            raise ValueError("cutover release effect receipt cannot perform effects")
        return self


class ProductionSafetyQualificationCutoverReleaseEffectManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = (
        "scout_production_safety_qualification_cutover_release_effect_manifest"
    )
    artifact_version: str = (
        "production_safety_qualification_cutover_release_effect_manifest.v0"
    )
    source_provider: str = "scout_runtime_safety_production_qualification"
    source_path: str
    cutover_release_handoff_report_ref: str
    cutover_release_handoff_report_sha256: str
    reference_time: datetime
    receipt: ProductionSafetyQualificationCutoverReleaseEffectReceipt | None = None
    external_call_performed_by_release_effect_intake: bool = False
    credential_material_loaded_by_release_effect_intake: bool = False
    raw_payload_loaded_by_release_effect_intake: bool = False
    production_database_mutated_by_release_effect_intake: bool = False
    safety_api_called_by_release_effect_intake: bool = False
    phase1_l0_l4_state_mutated_by_release_effect_intake: bool = False
    runtime_safety_truth_mutated_by_release_effect_intake: bool = False
    outbound_transport_invoked_by_release_effect_intake: bool = False
    hardware_control_performed_by_release_effect_intake: bool = False

    @model_validator(mode="after")
    def enforce_cutover_release_effect_manifest(
        self,
    ) -> "ProductionSafetyQualificationCutoverReleaseEffectManifest":
        _assert_qualification_ref("source_path", self.source_path)
        _assert_qualification_ref(
            "cutover_release_handoff_report_ref",
            self.cutover_release_handoff_report_ref,
        )
        if (
            self.external_call_performed_by_release_effect_intake
            or self.credential_material_loaded_by_release_effect_intake
            or self.raw_payload_loaded_by_release_effect_intake
            or self.production_database_mutated_by_release_effect_intake
            or self.safety_api_called_by_release_effect_intake
            or self.phase1_l0_l4_state_mutated_by_release_effect_intake
            or self.runtime_safety_truth_mutated_by_release_effect_intake
            or self.outbound_transport_invoked_by_release_effect_intake
            or self.hardware_control_performed_by_release_effect_intake
        ):
            raise ValueError("cutover release effect manifest cannot perform effects")
        return self


class ProductionSafetyQualificationCutoverReleaseEffectReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = (
        "scout_production_safety_qualification_cutover_release_effect_report"
    )
    artifact_version: str = (
        "production_safety_qualification_cutover_release_effect_report.v0"
    )
    source_provider: str = "scout_runtime_safety_production_qualification"
    source_path: str
    sha256: str
    status: ProductionSafetyQualificationCutoverReleaseEffectStatus
    cutover_release_handoff_report_ref: str
    cutover_release_handoff_report_sha256: str
    effect_manifest_ref: str
    effect_manifest_sha256: str
    effect_receipt_ref: str | None = None
    effect_receipt_sha256: str | None = None
    release_executor_ref: str | None = None
    release_executor_sha256: str | None = None
    release_invocation_ref: str | None = None
    release_invocation_sha256: str | None = None
    handoff_idempotency_key: str | None = None
    release_execution_ref: str | None = None
    release_execution_sha256: str | None = None
    release_result_ref: str | None = None
    release_result_sha256: str | None = None
    reviewer_ref: str | None = None
    reviewer_sha256: str | None = None
    release_observed_at: datetime | None = None
    receipt_accepted: bool = False
    executor_reported_release_completed: bool = False
    source_integrity_evidence_present: bool = False
    max_age_metadata_present: bool = False
    cutover_release_effect_receipt_recorded: bool = False
    ready_for_release_closure: bool = False
    ready_for_production_cutover: bool = False
    execution_allowed: Literal[False] = False
    blockers: list[str] = Field(default_factory=list)
    cutover_release_handoff_report: (
        ProductionSafetyQualificationCutoverReleaseHandoffReport
    )
    effect_manifest: ProductionSafetyQualificationCutoverReleaseEffectManifest
    effect_receipt: ProductionSafetyQualificationCutoverReleaseEffectReceipt | None = None
    external_call_performed_by_release_effect_intake: bool = False
    credential_material_loaded_by_release_effect_intake: bool = False
    raw_payload_loaded_by_release_effect_intake: bool = False
    production_database_mutated_by_release_effect_intake: bool = False
    safety_api_called_by_release_effect_intake: bool = False
    phase1_l0_l4_state_mutated_by_release_effect_intake: bool = False
    runtime_safety_truth_mutated_by_release_effect_intake: bool = False
    outbound_transport_invoked_by_release_effect_intake: bool = False
    hardware_control_performed_by_release_effect_intake: bool = False
    limitations: list[str] = Field(default_factory=list)
    boundary: ProductionSafetyQualificationBoundary = Field(
        default_factory=ProductionSafetyQualificationBoundary
    )

    @model_validator(mode="after")
    def enforce_cutover_release_effect_report(
        self,
    ) -> "ProductionSafetyQualificationCutoverReleaseEffectReport":
        recorded = self.status == "cutover_release_effect_receipt_recorded"
        if self.cutover_release_effect_receipt_recorded != recorded:
            raise ValueError("cutover_release_effect_receipt_recorded must match status")
        if self.ready_for_release_closure != recorded:
            raise ValueError("ready_for_release_closure must match status")
        if (
            self.cutover_release_handoff_report_ref
            != self.cutover_release_handoff_report.source_path
        ):
            raise ValueError("handoff report ref must match report")
        if (
            self.cutover_release_handoff_report_sha256
            != self.cutover_release_handoff_report.sha256
        ):
            raise ValueError("handoff report sha256 must match report")
        if self.effect_manifest_ref != self.effect_manifest.source_path:
            raise ValueError("effect manifest ref must match manifest")
        if self.effect_manifest_sha256 != _cutover_release_effect_manifest_sha256(
            self.effect_manifest
        ):
            raise ValueError("effect manifest sha256 must match manifest")
        if (
            self.effect_manifest.cutover_release_handoff_report_ref
            != self.cutover_release_handoff_report_ref
        ):
            raise ValueError("effect manifest handoff ref must match report")
        if (
            self.effect_manifest.cutover_release_handoff_report_sha256
            != self.cutover_release_handoff_report_sha256
        ):
            raise ValueError("effect manifest handoff sha256 must match report")
        receipt = self.effect_manifest.receipt
        if receipt is None:
            if self.effect_receipt is not None or self.effect_receipt_ref is not None:
                raise ValueError("missing release effect receipt cannot expose receipt")
            if self.effect_receipt_sha256 is not None:
                raise ValueError("missing release effect receipt cannot expose sha256")
        else:
            if self.effect_receipt != receipt:
                raise ValueError("effect receipt must match manifest receipt")
            if self.effect_receipt_ref != receipt.source_path:
                raise ValueError("effect receipt ref must match receipt")
            receipt_sha = receipt.sha256 or _cutover_release_effect_receipt_sha256(
                receipt
            )
            if self.effect_receipt_sha256 != receipt_sha:
                raise ValueError("effect receipt sha256 must match receipt")
            for field_name in (
                "release_executor_ref",
                "release_executor_sha256",
                "release_invocation_ref",
                "release_invocation_sha256",
                "handoff_idempotency_key",
                "release_execution_ref",
                "release_execution_sha256",
                "release_result_ref",
                "release_result_sha256",
                "reviewer_ref",
                "reviewer_sha256",
                "release_observed_at",
            ):
                if getattr(self, field_name) != getattr(receipt, field_name):
                    raise ValueError(f"{field_name} must match effect receipt")
        if recorded and self.blockers:
            raise ValueError("recorded cutover release effect cannot contain blockers")
        if not recorded and not self.blockers:
            raise ValueError("blocked cutover release effect requires blockers")
        if recorded and (
            self.cutover_release_handoff_report.status
            != "cutover_release_handoff_recorded"
            or not self.cutover_release_handoff_report.ready_for_release_executor_handoff
        ):
            raise ValueError("recorded release effect requires recorded handoff")
        if self.ready_for_production_cutover:
            raise ValueError("release effect report cannot claim production cutover")
        if self.execution_allowed:
            raise ValueError("release effect report cannot allow execution")
        if (
            self.external_call_performed_by_release_effect_intake
            or self.credential_material_loaded_by_release_effect_intake
            or self.raw_payload_loaded_by_release_effect_intake
            or self.production_database_mutated_by_release_effect_intake
            or self.safety_api_called_by_release_effect_intake
            or self.phase1_l0_l4_state_mutated_by_release_effect_intake
            or self.runtime_safety_truth_mutated_by_release_effect_intake
            or self.outbound_transport_invoked_by_release_effect_intake
            or self.hardware_control_performed_by_release_effect_intake
        ):
            raise ValueError("release effect report cannot perform effects")
        return self


class ProductionSafetyQualificationCutoverReleaseClosureReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = (
        "scout_production_safety_qualification_cutover_release_closure_review"
    )
    artifact_version: str = (
        "production_safety_qualification_cutover_release_closure_review.v0"
    )
    source_provider: str = "approved_cutover_release_reviewer"
    source_path: str = Field(min_length=1)
    sha256: str | None = None
    cutover_release_effect_report_ref: str | None = None
    cutover_release_effect_report_sha256: str | None = None
    release_executor_ref: str | None = None
    release_executor_sha256: str | None = None
    release_invocation_ref: str | None = None
    release_invocation_sha256: str | None = None
    handoff_idempotency_key: str | None = None
    release_execution_ref: str | None = None
    release_execution_sha256: str | None = None
    release_result_ref: str | None = None
    release_result_sha256: str | None = None
    release_effect_reviewer_ref: str | None = None
    release_effect_reviewer_sha256: str | None = None
    closure_reviewer_ref: str | None = None
    closure_reviewer_sha256: str | None = None
    rollback_plan_ref: str | None = None
    rollback_plan_sha256: str | None = None
    production_change_request_ref: str | None = None
    production_change_request_sha256: str | None = None
    closure_reviewed_at: datetime | None = None
    expires_at: datetime | None = None
    accepted: bool = False
    closure_reviewer_confirmation: bool = False
    source_integrity_evidence_present: bool = False
    max_age_metadata_present: bool = False
    explicit_confirmation_phrase: str | None = None
    execution_allowed: Literal[False] = False
    credential_material_embedded: bool = False
    raw_payload_embedded: bool = False
    production_database_payload_embedded: bool = False
    runtime_safety_truth_embedded: bool = False
    safety_api_called_by_release_closure_review: bool = False
    phase1_l0_l4_state_mutated_by_release_closure_review: bool = False
    runtime_safety_truth_mutated_by_release_closure_review: bool = False
    outbound_transport_invoked_by_release_closure_review: bool = False
    hardware_control_performed_by_release_closure_review: bool = False

    @model_validator(mode="after")
    def enforce_cutover_release_closure_review(
        self,
    ) -> "ProductionSafetyQualificationCutoverReleaseClosureReview":
        _assert_qualification_ref("source_path", self.source_path)
        for ref_name, ref_value, sha_name, sha_value in (
            (
                "cutover_release_effect_report_ref",
                self.cutover_release_effect_report_ref,
                "cutover_release_effect_report_sha256",
                self.cutover_release_effect_report_sha256,
            ),
            (
                "release_executor_ref",
                self.release_executor_ref,
                "release_executor_sha256",
                self.release_executor_sha256,
            ),
            (
                "release_invocation_ref",
                self.release_invocation_ref,
                "release_invocation_sha256",
                self.release_invocation_sha256,
            ),
            (
                "release_execution_ref",
                self.release_execution_ref,
                "release_execution_sha256",
                self.release_execution_sha256,
            ),
            (
                "release_result_ref",
                self.release_result_ref,
                "release_result_sha256",
                self.release_result_sha256,
            ),
            (
                "release_effect_reviewer_ref",
                self.release_effect_reviewer_ref,
                "release_effect_reviewer_sha256",
                self.release_effect_reviewer_sha256,
            ),
            (
                "closure_reviewer_ref",
                self.closure_reviewer_ref,
                "closure_reviewer_sha256",
                self.closure_reviewer_sha256,
            ),
            (
                "rollback_plan_ref",
                self.rollback_plan_ref,
                "rollback_plan_sha256",
                self.rollback_plan_sha256,
            ),
            (
                "production_change_request_ref",
                self.production_change_request_ref,
                "production_change_request_sha256",
                self.production_change_request_sha256,
            ),
        ):
            if (ref_value is None) != (sha_value is None):
                raise ValueError(f"{ref_name} and {sha_name} must be paired")
            if ref_value is not None:
                _assert_qualification_ref(ref_name, ref_value)
        if (
            self.closure_reviewed_at is not None
            and self.expires_at is not None
            and _as_utc(self.expires_at) <= _as_utc(self.closure_reviewed_at)
        ):
            raise ValueError("cutover release closure expires_at must be after review")
        if self.execution_allowed:
            raise ValueError("cutover release closure review cannot allow execution")
        if (
            self.credential_material_embedded
            or self.raw_payload_embedded
            or self.production_database_payload_embedded
            or self.runtime_safety_truth_embedded
        ):
            raise ValueError(
                "cutover release closure review cannot embed sensitive runtime data"
            )
        if (
            self.safety_api_called_by_release_closure_review
            or self.phase1_l0_l4_state_mutated_by_release_closure_review
            or self.runtime_safety_truth_mutated_by_release_closure_review
            or self.outbound_transport_invoked_by_release_closure_review
            or self.hardware_control_performed_by_release_closure_review
        ):
            raise ValueError("cutover release closure review cannot perform effects")
        return self


class ProductionSafetyQualificationCutoverReleaseClosureManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = (
        "scout_production_safety_qualification_cutover_release_closure_manifest"
    )
    artifact_version: str = (
        "production_safety_qualification_cutover_release_closure_manifest.v0"
    )
    source_provider: str = "scout_runtime_safety_production_qualification"
    source_path: str
    cutover_release_effect_report_ref: str
    cutover_release_effect_report_sha256: str
    reference_time: datetime
    closure_review: (
        ProductionSafetyQualificationCutoverReleaseClosureReview | None
    ) = None
    external_call_performed_by_release_closure: bool = False
    credential_material_loaded_by_release_closure: bool = False
    raw_payload_loaded_by_release_closure: bool = False
    production_database_mutated_by_release_closure: bool = False
    safety_api_called_by_release_closure: bool = False
    phase1_l0_l4_state_mutated_by_release_closure: bool = False
    runtime_safety_truth_mutated_by_release_closure: bool = False
    outbound_transport_invoked_by_release_closure: bool = False
    hardware_control_performed_by_release_closure: bool = False

    @model_validator(mode="after")
    def enforce_cutover_release_closure_manifest(
        self,
    ) -> "ProductionSafetyQualificationCutoverReleaseClosureManifest":
        _assert_qualification_ref("source_path", self.source_path)
        _assert_qualification_ref(
            "cutover_release_effect_report_ref",
            self.cutover_release_effect_report_ref,
        )
        if (
            self.external_call_performed_by_release_closure
            or self.credential_material_loaded_by_release_closure
            or self.raw_payload_loaded_by_release_closure
            or self.production_database_mutated_by_release_closure
            or self.safety_api_called_by_release_closure
            or self.phase1_l0_l4_state_mutated_by_release_closure
            or self.runtime_safety_truth_mutated_by_release_closure
            or self.outbound_transport_invoked_by_release_closure
            or self.hardware_control_performed_by_release_closure
        ):
            raise ValueError("cutover release closure manifest cannot perform effects")
        return self


class ProductionSafetyQualificationCutoverReleaseClosureReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = (
        "scout_production_safety_qualification_cutover_release_closure_report"
    )
    artifact_version: str = (
        "production_safety_qualification_cutover_release_closure_report.v0"
    )
    source_provider: str = "scout_runtime_safety_production_qualification"
    source_path: str
    sha256: str
    status: ProductionSafetyQualificationCutoverReleaseClosureStatus
    cutover_release_effect_report_ref: str
    cutover_release_effect_report_sha256: str
    closure_manifest_ref: str
    closure_manifest_sha256: str
    closure_review_ref: str | None = None
    closure_review_sha256: str | None = None
    release_executor_ref: str | None = None
    release_executor_sha256: str | None = None
    release_invocation_ref: str | None = None
    release_invocation_sha256: str | None = None
    handoff_idempotency_key: str | None = None
    release_execution_ref: str | None = None
    release_execution_sha256: str | None = None
    release_result_ref: str | None = None
    release_result_sha256: str | None = None
    release_effect_reviewer_ref: str | None = None
    release_effect_reviewer_sha256: str | None = None
    closure_reviewer_ref: str | None = None
    closure_reviewer_sha256: str | None = None
    rollback_plan_ref: str | None = None
    rollback_plan_sha256: str | None = None
    production_change_request_ref: str | None = None
    production_change_request_sha256: str | None = None
    closure_reviewed_at: datetime | None = None
    expires_at: datetime | None = None
    review_accepted: bool = False
    closure_reviewer_confirmation: bool = False
    source_integrity_evidence_present: bool = False
    max_age_metadata_present: bool = False
    explicit_confirmation_phrase: str | None = None
    cutover_release_closure_recorded: bool = False
    ready_for_production_cutover_review: bool = False
    ready_for_production_cutover: bool = False
    execution_allowed: Literal[False] = False
    blockers: list[str] = Field(default_factory=list)
    cutover_release_effect_report: (
        ProductionSafetyQualificationCutoverReleaseEffectReport
    )
    closure_manifest: ProductionSafetyQualificationCutoverReleaseClosureManifest
    closure_review: (
        ProductionSafetyQualificationCutoverReleaseClosureReview | None
    ) = None
    external_call_performed_by_release_closure: bool = False
    credential_material_loaded_by_release_closure: bool = False
    raw_payload_loaded_by_release_closure: bool = False
    production_database_mutated_by_release_closure: bool = False
    safety_api_called_by_release_closure: bool = False
    phase1_l0_l4_state_mutated_by_release_closure: bool = False
    runtime_safety_truth_mutated_by_release_closure: bool = False
    outbound_transport_invoked_by_release_closure: bool = False
    hardware_control_performed_by_release_closure: bool = False
    limitations: list[str] = Field(default_factory=list)
    boundary: ProductionSafetyQualificationBoundary = Field(
        default_factory=ProductionSafetyQualificationBoundary
    )

    @model_validator(mode="after")
    def enforce_cutover_release_closure_report(
        self,
    ) -> "ProductionSafetyQualificationCutoverReleaseClosureReport":
        recorded = self.status == "cutover_release_closure_recorded"
        if self.cutover_release_closure_recorded != recorded:
            raise ValueError("cutover_release_closure_recorded must match status")
        if self.ready_for_production_cutover_review != recorded:
            raise ValueError("ready_for_production_cutover_review must match status")
        if (
            self.cutover_release_effect_report_ref
            != self.cutover_release_effect_report.source_path
        ):
            raise ValueError("release effect report ref must match report")
        if (
            self.cutover_release_effect_report_sha256
            != self.cutover_release_effect_report.sha256
        ):
            raise ValueError("release effect report sha256 must match report")
        if self.closure_manifest_ref != self.closure_manifest.source_path:
            raise ValueError("closure manifest ref must match manifest")
        if self.closure_manifest_sha256 != _cutover_release_closure_manifest_sha256(
            self.closure_manifest
        ):
            raise ValueError("closure manifest sha256 must match manifest")
        if (
            self.closure_manifest.cutover_release_effect_report_ref
            != self.cutover_release_effect_report_ref
        ):
            raise ValueError("closure manifest effect ref must match report")
        if (
            self.closure_manifest.cutover_release_effect_report_sha256
            != self.cutover_release_effect_report_sha256
        ):
            raise ValueError("closure manifest effect sha256 must match report")
        review = self.closure_manifest.closure_review
        review_ref_fields = (
            "closure_review_ref",
            "closure_review_sha256",
            "release_executor_ref",
            "release_executor_sha256",
            "release_invocation_ref",
            "release_invocation_sha256",
            "handoff_idempotency_key",
            "release_execution_ref",
            "release_execution_sha256",
            "release_result_ref",
            "release_result_sha256",
            "release_effect_reviewer_ref",
            "release_effect_reviewer_sha256",
            "closure_reviewer_ref",
            "closure_reviewer_sha256",
            "rollback_plan_ref",
            "rollback_plan_sha256",
            "production_change_request_ref",
            "production_change_request_sha256",
            "closure_reviewed_at",
            "expires_at",
            "explicit_confirmation_phrase",
        )
        if review is None:
            if self.closure_review is not None:
                raise ValueError("missing closure review cannot expose review")
            if any(getattr(self, field_name) is not None for field_name in review_ref_fields):
                raise ValueError("missing closure review cannot expose review refs")
            if (
                self.review_accepted
                or self.closure_reviewer_confirmation
                or self.source_integrity_evidence_present
                or self.max_age_metadata_present
            ):
                raise ValueError("missing closure review cannot expose review flags")
        else:
            if self.closure_review != review:
                raise ValueError("closure review must match manifest review")
            if self.closure_review_ref != review.source_path:
                raise ValueError("closure review ref must match review")
            review_sha = review.sha256 or _cutover_release_closure_review_sha256(
                review
            )
            if self.closure_review_sha256 != review_sha:
                raise ValueError("closure review sha256 must match review")
            for field_name in (
                "release_executor_ref",
                "release_executor_sha256",
                "release_invocation_ref",
                "release_invocation_sha256",
                "handoff_idempotency_key",
                "release_execution_ref",
                "release_execution_sha256",
                "release_result_ref",
                "release_result_sha256",
                "release_effect_reviewer_ref",
                "release_effect_reviewer_sha256",
                "closure_reviewer_ref",
                "closure_reviewer_sha256",
                "rollback_plan_ref",
                "rollback_plan_sha256",
                "production_change_request_ref",
                "production_change_request_sha256",
                "closure_reviewed_at",
                "expires_at",
                "explicit_confirmation_phrase",
            ):
                if getattr(self, field_name) != getattr(review, field_name):
                    raise ValueError(f"{field_name} must match closure review")
            if self.review_accepted != review.accepted:
                raise ValueError("review_accepted must match closure review")
            if (
                self.closure_reviewer_confirmation
                != review.closure_reviewer_confirmation
            ):
                raise ValueError(
                    "closure_reviewer_confirmation must match closure review"
                )
            if (
                self.source_integrity_evidence_present
                != review.source_integrity_evidence_present
            ):
                raise ValueError(
                    "source_integrity_evidence_present must match closure review"
                )
            if self.max_age_metadata_present != review.max_age_metadata_present:
                raise ValueError("max_age_metadata_present must match closure review")
        if recorded and self.blockers:
            raise ValueError("recorded cutover release closure cannot contain blockers")
        if not recorded and not self.blockers:
            raise ValueError("blocked cutover release closure requires blockers")
        if recorded and (
            self.cutover_release_effect_report.status
            != "cutover_release_effect_receipt_recorded"
            or not self.cutover_release_effect_report.ready_for_release_closure
        ):
            raise ValueError("recorded release closure requires recorded effect")
        if self.ready_for_production_cutover:
            raise ValueError("release closure report cannot claim production cutover")
        if self.execution_allowed:
            raise ValueError("release closure report cannot allow execution")
        if (
            self.external_call_performed_by_release_closure
            or self.credential_material_loaded_by_release_closure
            or self.raw_payload_loaded_by_release_closure
            or self.production_database_mutated_by_release_closure
            or self.safety_api_called_by_release_closure
            or self.phase1_l0_l4_state_mutated_by_release_closure
            or self.runtime_safety_truth_mutated_by_release_closure
            or self.outbound_transport_invoked_by_release_closure
            or self.hardware_control_performed_by_release_closure
        ):
            raise ValueError("release closure report cannot perform effects")
        return self


class ProductionSafetyQualificationRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    area: ProductionSafetyQualificationArea
    status: ProductionSafetyQualificationReceiptStatus | Literal["missing"]
    receipt_sha256: str | None = None
    qualification_ref: str | None = None
    qualification_sha256: str | None = None
    reviewed_effect_boundary_ref: str | None = None
    operator_review_ref: str | None = None
    capability_observed: bool = False
    production_environment_verified: bool = False
    lineage_verified: bool = False
    fail_closed_behavior_verified: bool = False
    rollback_or_fallback_verified: bool = False
    qualified_for_cutover: bool = False
    blockers: list[str] = Field(default_factory=list)


class ProductionSafetyCutoverReadinessAudit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_safety_cutover_readiness_audit"
    artifact_version: str = "production_safety_cutover_readiness_audit.v0"
    source_provider: str = "scout_runtime_safety_production_qualification"
    source_path: str
    sha256: str
    status: ProductionSafetyCutoverReadinessStatus
    required_areas: list[ProductionSafetyQualificationArea]
    rows: list[ProductionSafetyQualificationRow]
    missing_areas: list[ProductionSafetyQualificationArea] = Field(default_factory=list)
    failed_areas: list[ProductionSafetyQualificationArea] = Field(default_factory=list)
    ready_for_production_cutover: bool = False
    external_call_performed_by_audit: bool = False
    credential_material_loaded_by_audit: bool = False
    raw_payload_loaded_by_audit: bool = False
    production_database_mutated_by_audit: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    runtime_safety_truth_mutated: bool = False
    outbound_transport_invoked_by_audit: bool = False
    hardware_control_performed_by_audit: bool = False
    limitations: list[str] = Field(default_factory=list)
    boundary: ProductionSafetyQualificationBoundary = Field(
        default_factory=ProductionSafetyQualificationBoundary
    )

    @model_validator(mode="after")
    def enforce_cutover_readiness_audit(
        self,
    ) -> "ProductionSafetyCutoverReadinessAudit":
        ready = self.status == "ready_for_production_cutover"
        if self.ready_for_production_cutover != ready:
            raise ValueError("ready_for_production_cutover must match status")
        if ready and (self.missing_areas or self.failed_areas):
            raise ValueError("ready cutover audit cannot contain missing or failed areas")
        if ready and not all(row.qualified_for_cutover for row in self.rows):
            raise ValueError("ready cutover audit requires all rows qualified")
        if (
            self.external_call_performed_by_audit
            or self.credential_material_loaded_by_audit
            or self.raw_payload_loaded_by_audit
            or self.production_database_mutated_by_audit
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
            or self.runtime_safety_truth_mutated
            or self.outbound_transport_invoked_by_audit
            or self.hardware_control_performed_by_audit
        ):
            raise ValueError("production qualification audit cannot perform effects")
        return self


def evaluate_production_safety_cutover_readiness(
    receipts: list[ProductionSafetyQualificationReceipt | dict[str, Any]],
    *,
    source_path: str = "inline:production-safety-cutover-readiness",
    required_areas: tuple[
        ProductionSafetyQualificationArea,
        ...,
    ] = REQUIRED_PRODUCTION_SAFETY_QUALIFICATION_AREAS,
) -> ProductionSafetyCutoverReadinessAudit:
    receipt_models = [
        receipt
        if isinstance(receipt, ProductionSafetyQualificationReceipt)
        else ProductionSafetyQualificationReceipt.model_validate(receipt)
        for receipt in receipts
    ]
    by_area: dict[ProductionSafetyQualificationArea, ProductionSafetyQualificationReceipt] = {}
    for receipt in receipt_models:
        by_area[receipt.area] = receipt

    rows = [_qualification_row(area, by_area.get(area)) for area in required_areas]
    missing = [row.area for row in rows if row.status == "missing"]
    failed = [
        row.area
        for row in rows
        if row.status != "missing" and not row.qualified_for_cutover
    ]
    if missing:
        status: ProductionSafetyCutoverReadinessStatus = (
            "blocked_missing_required_qualification"
        )
    elif failed:
        status = "blocked_failed_required_qualification"
    else:
        status = "ready_for_production_cutover"
    digest = aggregate_sha256(
        [
            {
                "source_path": source_path,
                "required_areas": list(required_areas),
                "row_statuses": [
                    {
                        "area": row.area,
                        "status": row.status,
                        "receipt_sha256": row.receipt_sha256,
                        "qualified_for_cutover": row.qualified_for_cutover,
                    }
                    for row in rows
                ],
                "status": status,
            }
        ]
    )
    return ProductionSafetyCutoverReadinessAudit(
        source_path=source_path,
        sha256=digest,
        status=status,
        required_areas=list(required_areas),
        rows=rows,
        missing_areas=missing,
        failed_areas=failed,
        ready_for_production_cutover=status == "ready_for_production_cutover",
        limitations=[
            "deterministic production cutover readiness audit only",
            "does not call providers, load credentials, deploy writers, send transport, verify delivery, mutate runtime safety truth, or control hardware",
        ],
    )


def evaluate_production_safety_qualification_bundle(
    bundle: ProductionSafetyQualificationEvidenceBundle | dict[str, Any],
    *,
    source_integrity_report: ProductionSafetyQualificationSourceIntegrityReport
    | dict[str, Any]
    | None = None,
) -> ProductionSafetyQualificationReceiptAdmissionDecision:
    bundle_model = (
        bundle
        if isinstance(bundle, ProductionSafetyQualificationEvidenceBundle)
        else ProductionSafetyQualificationEvidenceBundle.model_validate(bundle)
    )
    source_report = (
        None
        if source_integrity_report is None
        else source_integrity_report
        if isinstance(
            source_integrity_report,
            ProductionSafetyQualificationSourceIntegrityReport,
        )
        else ProductionSafetyQualificationSourceIntegrityReport.model_validate(
            source_integrity_report
        )
    )
    if source_report is not None and source_report.area != bundle_model.area:
        raise ValueError("source integrity report area must match evidence bundle area")
    if source_report is not None and source_report.bundle_ref != bundle_model.source_path:
        raise ValueError("source integrity report bundle_ref must match evidence bundle")
    required_claims = PRODUCTION_SAFETY_QUALIFICATION_REQUIRED_CLAIMS[
        bundle_model.area
    ]
    claims_by_id = {claim.claim_id: claim for claim in bundle_model.claims}
    source_verified_claims = _source_integrity_verified_claim_ids(source_report)
    stale_claims = [
        claim_id
        for claim_id in required_claims
        if claim_id in claims_by_id
        and claims_by_id[claim_id].accepted
        and _claim_is_stale(claims_by_id[claim_id], bundle_model.reference_time)
    ]
    accepted_claims = [
        claim_id
        for claim_id in required_claims
        if claim_id in claims_by_id and claims_by_id[claim_id].accepted
        and claim_id not in stale_claims
        and claim_id in source_verified_claims
    ]
    missing_claims = [
        claim_id for claim_id in required_claims if claim_id not in claims_by_id
    ]
    rejected_claims = [
        claim_id
        for claim_id in required_claims
        if claim_id in claims_by_id and not claims_by_id[claim_id].accepted
    ]
    unverified_source_claims = [
        claim_id
        for claim_id in required_claims
        if claim_id in claims_by_id
        and claims_by_id[claim_id].accepted
        and claim_id not in stale_claims
        and claim_id not in source_verified_claims
    ]
    missing_required_refs = _missing_required_receipt_refs(bundle_model)
    if missing_claims or missing_required_refs:
        status: ProductionSafetyQualificationReceiptAdmissionStatus = (
            "blocked_missing_required_claims"
        )
    elif stale_claims:
        status = "blocked_stale_required_claims"
    elif rejected_claims:
        status = "blocked_rejected_required_claims"
    elif unverified_source_claims:
        status = "blocked_source_integrity_unverified"
    else:
        status = "qualification_receipt_accepted"
    receipt = _qualification_receipt_from_bundle(
        bundle_model,
        status="qualified" if status == "qualification_receipt_accepted" else "blocked",
        accepted_claims=accepted_claims,
        missing_claims=missing_claims,
        rejected_claims=rejected_claims,
        stale_claims=stale_claims,
        unverified_source_claims=unverified_source_claims,
        missing_required_refs=missing_required_refs,
    )
    digest = aggregate_sha256(
        [
            {
                "source_path": bundle_model.source_path,
                "reference_time": _as_utc(bundle_model.reference_time).isoformat(),
                "area": bundle_model.area,
                "required_claims": list(required_claims),
                "accepted_claims": accepted_claims,
                "missing_claims": missing_claims,
                "rejected_claims": rejected_claims,
                "stale_claims": stale_claims,
                "unverified_source_claims": unverified_source_claims,
                "missing_required_refs": missing_required_refs,
                "source_integrity_report_sha256": (
                    source_report.sha256 if source_report else None
                ),
                "receipt_sha256": receipt.sha256,
                "status": status,
            }
        ]
    )
    return ProductionSafetyQualificationReceiptAdmissionDecision(
        source_path=bundle_model.source_path,
        sha256=digest,
        area=bundle_model.area,
        status=status,
        required_claims=list(required_claims),
        accepted_claims=accepted_claims,
        missing_claims=missing_claims,
        rejected_claims=rejected_claims,
        stale_claims=stale_claims,
        unverified_source_claims=unverified_source_claims,
        missing_required_refs=missing_required_refs,
        source_integrity_report_ref=source_report.source_path if source_report else None,
        source_integrity_report_sha256=source_report.sha256 if source_report else None,
        source_integrity_verified=bool(
            source_report and source_report.all_claim_sources_verified
        ),
        receipt=receipt,
        ready_for_cutover_receipt=status == "qualification_receipt_accepted",
    )


def verify_production_safety_qualification_source_integrity(
    bundle: ProductionSafetyQualificationEvidenceBundle | dict[str, Any],
    evidence_package: ProductionSafetyQualificationEvidencePackage | dict[str, Any],
    *,
    root_path: Path | str | None = None,
    source_path: str = "inline:production-safety-source-integrity",
) -> ProductionSafetyQualificationSourceIntegrityReport:
    bundle_model = (
        bundle
        if isinstance(bundle, ProductionSafetyQualificationEvidenceBundle)
        else ProductionSafetyQualificationEvidenceBundle.model_validate(bundle)
    )
    package_model = (
        evidence_package
        if isinstance(evidence_package, ProductionSafetyQualificationEvidencePackage)
        else ProductionSafetyQualificationEvidencePackage.model_validate(evidence_package)
    )
    if package_model.area != bundle_model.area:
        raise ValueError("source integrity package area must match evidence bundle area")
    artifacts_by_ref = {
        artifact.evidence_ref: artifact for artifact in package_model.artifacts
    }
    rows = [
        _source_integrity_row(claim, artifacts_by_ref.get(claim.evidence_ref), root_path)
        for claim in bundle_model.claims
    ]
    verified_refs = [
        row.evidence_ref for row in rows if row.status == "verified"
    ]
    missing_refs = [row.evidence_ref for row in rows if row.status == "missing"]
    mismatched_refs = [
        row.evidence_ref for row in rows if row.status == "hash_mismatch"
    ]
    unsafe_refs = [row.evidence_ref for row in rows if row.status == "unsafe_path"]
    sensitive_refs = [
        row.evidence_ref for row in rows if row.status == "sensitive_material"
    ]
    all_verified = all(row.source_integrity_verified for row in rows)
    status: ProductionSafetyQualificationSourceIntegrityStatus = (
        "source_integrity_verified"
        if all_verified
        else "blocked_source_integrity_failed"
    )
    digest = aggregate_sha256(
        [
            {
                "source_path": source_path,
                "area": bundle_model.area,
                "bundle_ref": bundle_model.source_path,
                "package_ref": package_model.source_path,
                "row_statuses": [
                    {
                        "claim_id": row.claim_id,
                        "evidence_ref": row.evidence_ref,
                        "expected_sha256": row.expected_sha256,
                        "actual_sha256": row.actual_sha256,
                        "status": row.status,
                    }
                    for row in rows
                ],
                "status": status,
            }
        ]
    )
    return ProductionSafetyQualificationSourceIntegrityReport(
        source_path=source_path,
        sha256=digest,
        area=bundle_model.area,
        bundle_ref=bundle_model.source_path,
        package_ref=package_model.source_path,
        status=status,
        rows=rows,
        verified_evidence_refs=verified_refs,
        missing_evidence_refs=missing_refs,
        mismatched_evidence_refs=mismatched_refs,
        unsafe_evidence_refs=unsafe_refs,
        sensitive_evidence_refs=sensitive_refs,
        all_claim_sources_verified=all_verified,
    )


def evaluate_production_safety_qualification_threat_coverage(
    manifest: ProductionSafetyQualificationThreatCoverageManifest
    | dict[str, Any]
    | Path
    | str,
    *,
    source_integrity_report: ProductionSafetyQualificationThreatCoverageSourceIntegrityReport
    | dict[str, Any]
    | None = None,
    source_path: str | None = None,
    required_threats: tuple[
        ProductionSafetyQualificationThreatId,
        ...,
    ] = REQUIRED_PRODUCTION_SAFETY_THREAT_COVERAGE,
    required_qualification_modes: tuple[
        ProductionSafetyQualificationModeId,
        ...,
    ] = REQUIRED_PRODUCTION_SAFETY_QUALIFICATION_MODES,
) -> ProductionSafetyQualificationThreatCoverageAudit:
    manifest_model = _load_or_validate_threat_coverage_manifest(manifest)
    source_report = (
        None
        if source_integrity_report is None
        else source_integrity_report
        if isinstance(
            source_integrity_report,
            ProductionSafetyQualificationThreatCoverageSourceIntegrityReport,
        )
        else ProductionSafetyQualificationThreatCoverageSourceIntegrityReport.model_validate(
            source_integrity_report
        )
    )
    if source_report is not None and source_report.manifest_ref != manifest_model.source_path:
        raise ValueError(
            "threat coverage source integrity report manifest_ref must match manifest"
        )
    audit_source_path = source_path or f"{manifest_model.source_path}/threat-audit"
    threats_by_id = {case.threat_id: case for case in manifest_model.threat_cases}
    modes_by_id = {
        case.mode_id: case for case in manifest_model.qualification_modes
    }
    verified_source_refs = _threat_coverage_source_integrity_verified_refs(
        source_report
    )
    rows = [
        *[
            _threat_coverage_row(
                threat_id,
                threats_by_id.get(threat_id),
                manifest_model.reference_time,
                verified_source_refs,
            )
            for threat_id in required_threats
        ],
        *[
            _qualification_mode_coverage_row(
                mode_id,
                modes_by_id.get(mode_id),
                manifest_model.reference_time,
                verified_source_refs,
            )
            for mode_id in required_qualification_modes
        ],
    ]
    missing_threats = [
        row.threat_id
        for row in rows
        if row.coverage_type == "threat"
        and row.status == "missing"
        and row.threat_id is not None
    ]
    failed_threats = [
        row.threat_id
        for row in rows
        if row.coverage_type == "threat"
        and row.status == "failed"
        and row.threat_id is not None
    ]
    stale_threats = [
        row.threat_id
        for row in rows
        if row.coverage_type == "threat"
        and row.status == "stale"
        and row.threat_id is not None
    ]
    unverified_threats = [
        row.threat_id
        for row in rows
        if row.coverage_type == "threat"
        and row.status == "unverified_source"
        and row.threat_id is not None
    ]
    missing_modes = [
        row.mode_id
        for row in rows
        if row.coverage_type == "qualification_mode"
        and row.status == "missing"
        and row.mode_id is not None
    ]
    failed_modes = [
        row.mode_id
        for row in rows
        if row.coverage_type == "qualification_mode"
        and row.status == "failed"
        and row.mode_id is not None
    ]
    stale_modes = [
        row.mode_id
        for row in rows
        if row.coverage_type == "qualification_mode"
        and row.status == "stale"
        and row.mode_id is not None
    ]
    unverified_modes = [
        row.mode_id
        for row in rows
        if row.coverage_type == "qualification_mode"
        and row.status == "unverified_source"
        and row.mode_id is not None
    ]
    if missing_threats or missing_modes:
        status: ProductionSafetyQualificationThreatCoverageStatus = (
            "blocked_missing_qualification_coverage"
        )
    elif stale_threats or stale_modes:
        status = "blocked_stale_qualification_coverage"
    elif failed_threats or failed_modes:
        status = "blocked_failed_qualification_coverage"
    elif unverified_threats or unverified_modes:
        status = "blocked_source_integrity_unverified"
    else:
        status = "qualification_threat_coverage_passed"
    digest = aggregate_sha256(
        [
            {
                "source_path": audit_source_path,
                "manifest_ref": manifest_model.source_path,
                "required_threats": list(required_threats),
                "required_qualification_modes": list(required_qualification_modes),
                "source_integrity_report_sha256": (
                    source_report.sha256 if source_report else None
                ),
                "row_statuses": [
                    {
                        "coverage_type": row.coverage_type,
                        "threat_id": row.threat_id,
                        "mode_id": row.mode_id,
                        "status": row.status,
                    }
                    for row in rows
                ],
                "status": status,
            }
        ]
    )
    return ProductionSafetyQualificationThreatCoverageAudit(
        source_path=audit_source_path,
        sha256=digest,
        status=status,
        required_threats=list(required_threats),
        required_qualification_modes=list(required_qualification_modes),
        rows=rows,
        missing_threats=missing_threats,
        failed_threats=failed_threats,
        stale_threats=stale_threats,
        unverified_source_threats=unverified_threats,
        missing_qualification_modes=missing_modes,
        failed_qualification_modes=failed_modes,
        stale_qualification_modes=stale_modes,
        unverified_source_qualification_modes=unverified_modes,
        source_integrity_report_ref=source_report.source_path if source_report else None,
        source_integrity_report_sha256=source_report.sha256 if source_report else None,
        source_integrity_verified=bool(
            source_report and source_report.all_coverage_sources_verified
        ),
        threat_model_covered=not (
            missing_threats
            or failed_threats
            or stale_threats
            or unverified_threats
        ),
        qualification_modes_covered=not (
            missing_modes or failed_modes or stale_modes or unverified_modes
        ),
        ready_for_production_cutover_threat_coverage=(
            status == "qualification_threat_coverage_passed"
        ),
        limitations=[
            "deterministic production qualification threat coverage audit only",
            "does not call providers, load credentials, mutate runtime safety truth, send transport, verify delivery, or control hardware",
        ],
    )


def verify_production_safety_qualification_threat_coverage_source_integrity(
    manifest: ProductionSafetyQualificationThreatCoverageManifest | dict[str, Any],
    evidence_package: ProductionSafetyQualificationThreatCoverageEvidencePackage
    | dict[str, Any],
    *,
    root_path: Path | str | None = None,
    source_path: str = "prod://qualification/threat-coverage/source-integrity",
) -> ProductionSafetyQualificationThreatCoverageSourceIntegrityReport:
    manifest_model = (
        manifest
        if isinstance(manifest, ProductionSafetyQualificationThreatCoverageManifest)
        else ProductionSafetyQualificationThreatCoverageManifest.model_validate(manifest)
    )
    package_model = (
        evidence_package
        if isinstance(
            evidence_package,
            ProductionSafetyQualificationThreatCoverageEvidencePackage,
        )
        else ProductionSafetyQualificationThreatCoverageEvidencePackage.model_validate(
            evidence_package
        )
    )
    artifacts_by_ref = {
        artifact.evidence_ref: artifact for artifact in package_model.artifacts
    }
    rows = [
        *[
            _threat_coverage_source_integrity_row(
                "threat",
                case.threat_id,
                None,
                case.evidence_ref,
                case.evidence_sha256,
                artifacts_by_ref.get(case.evidence_ref),
                root_path,
            )
            for case in manifest_model.threat_cases
        ],
        *[
            _threat_coverage_source_integrity_row(
                "qualification_mode",
                None,
                case.mode_id,
                case.evidence_ref,
                case.evidence_sha256,
                artifacts_by_ref.get(case.evidence_ref),
                root_path,
            )
            for case in manifest_model.qualification_modes
        ],
    ]
    verified_refs = [
        row.evidence_ref for row in rows if row.status == "verified"
    ]
    missing_refs = [row.evidence_ref for row in rows if row.status == "missing"]
    mismatched_refs = [
        row.evidence_ref for row in rows if row.status == "hash_mismatch"
    ]
    unsafe_refs = [row.evidence_ref for row in rows if row.status == "unsafe_path"]
    sensitive_refs = [
        row.evidence_ref for row in rows if row.status == "sensitive_material"
    ]
    all_verified = all(row.source_integrity_verified for row in rows)
    status: ProductionSafetyQualificationSourceIntegrityStatus = (
        "source_integrity_verified"
        if all_verified
        else "blocked_source_integrity_failed"
    )
    digest = aggregate_sha256(
        [
            {
                "source_path": source_path,
                "manifest_ref": manifest_model.source_path,
                "package_ref": package_model.source_path,
                "row_statuses": [
                    {
                        "coverage_type": row.coverage_type,
                        "threat_id": row.threat_id,
                        "mode_id": row.mode_id,
                        "evidence_ref": row.evidence_ref,
                        "expected_sha256": row.expected_sha256,
                        "actual_sha256": row.actual_sha256,
                        "status": row.status,
                    }
                    for row in rows
                ],
                "status": status,
            }
        ]
    )
    return ProductionSafetyQualificationThreatCoverageSourceIntegrityReport(
        source_path=source_path,
        sha256=digest,
        manifest_ref=manifest_model.source_path,
        package_ref=package_model.source_path,
        status=status,
        rows=rows,
        verified_evidence_refs=verified_refs,
        missing_evidence_refs=missing_refs,
        mismatched_evidence_refs=mismatched_refs,
        unsafe_evidence_refs=unsafe_refs,
        sensitive_evidence_refs=sensitive_refs,
        all_coverage_sources_verified=all_verified,
    )


def load_production_safety_qualification_receipt(
    path: Path | str,
) -> ProductionSafetyQualificationReceipt:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    payload["sha256"] = payload.get("sha256") or sha256_file(expanded)
    return ProductionSafetyQualificationReceipt.model_validate(payload)


def load_production_safety_qualification_receipts(
    paths: list[Path | str],
) -> list[ProductionSafetyQualificationReceipt]:
    return [load_production_safety_qualification_receipt(path) for path in paths]


def write_production_safety_qualification_receipt(
    receipt: ProductionSafetyQualificationReceipt,
    output_path: Path | str,
) -> ProductionSafetyQualificationReceipt:
    path = Path(output_path).expanduser()
    _write_json(path, receipt.model_dump(mode="json"))
    return load_production_safety_qualification_receipt(path)


def load_production_safety_qualification_evidence_bundle(
    path: Path | str,
) -> ProductionSafetyQualificationEvidenceBundle:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    return ProductionSafetyQualificationEvidenceBundle.model_validate(payload)


def load_production_safety_qualification_evidence_package(
    path: Path | str,
) -> ProductionSafetyQualificationEvidencePackage:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    return ProductionSafetyQualificationEvidencePackage.model_validate(payload)


def load_production_safety_qualification_threat_coverage_manifest(
    path: Path | str,
) -> ProductionSafetyQualificationThreatCoverageManifest:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    return ProductionSafetyQualificationThreatCoverageManifest.model_validate(payload)


def load_production_safety_qualification_threat_coverage_evidence_package(
    path: Path | str,
) -> ProductionSafetyQualificationThreatCoverageEvidencePackage:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    return ProductionSafetyQualificationThreatCoverageEvidencePackage.model_validate(
        payload
    )


def write_production_safety_qualification_threat_coverage_source_integrity_report(
    report: ProductionSafetyQualificationThreatCoverageSourceIntegrityReport,
    output_path: Path | str,
) -> ProductionSafetyQualificationThreatCoverageSourceIntegrityReport:
    path = Path(output_path).expanduser()
    _write_json(path, report.model_dump(mode="json"))
    return load_production_safety_qualification_threat_coverage_source_integrity_report(
        path
    )


def load_production_safety_qualification_threat_coverage_source_integrity_report(
    path: Path | str,
) -> ProductionSafetyQualificationThreatCoverageSourceIntegrityReport:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    payload["source_path"] = payload.get("source_path") or str(expanded)
    payload["sha256"] = payload.get("sha256") or sha256_file(expanded)
    return ProductionSafetyQualificationThreatCoverageSourceIntegrityReport.model_validate(
        payload
    )


def write_production_safety_qualification_threat_coverage_audit(
    audit: ProductionSafetyQualificationThreatCoverageAudit,
    output_path: Path | str,
) -> ProductionSafetyQualificationThreatCoverageAudit:
    path = Path(output_path).expanduser()
    _write_json(path, audit.model_dump(mode="json"))
    return load_production_safety_qualification_threat_coverage_audit(path)


def load_production_safety_qualification_threat_coverage_audit(
    path: Path | str,
) -> ProductionSafetyQualificationThreatCoverageAudit:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    payload["source_path"] = payload.get("source_path") or str(expanded)
    payload["sha256"] = payload.get("sha256") or sha256_file(expanded)
    return ProductionSafetyQualificationThreatCoverageAudit.model_validate(payload)


def write_production_safety_qualification_receipt_admission_decision(
    decision: ProductionSafetyQualificationReceiptAdmissionDecision,
    output_path: Path | str,
) -> ProductionSafetyQualificationReceiptAdmissionDecision:
    path = Path(output_path).expanduser()
    _write_json(path, decision.model_dump(mode="json"))
    return load_production_safety_qualification_receipt_admission_decision(path)


def load_production_safety_qualification_receipt_admission_decision(
    path: Path | str,
) -> ProductionSafetyQualificationReceiptAdmissionDecision:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    payload["source_path"] = payload.get("source_path") or str(expanded)
    payload["sha256"] = payload.get("sha256") or sha256_file(expanded)
    return ProductionSafetyQualificationReceiptAdmissionDecision.model_validate(payload)


def write_production_safety_qualification_source_integrity_report(
    report: ProductionSafetyQualificationSourceIntegrityReport,
    output_path: Path | str,
) -> ProductionSafetyQualificationSourceIntegrityReport:
    path = Path(output_path).expanduser()
    _write_json(path, report.model_dump(mode="json"))
    return load_production_safety_qualification_source_integrity_report(path)


def load_production_safety_qualification_source_integrity_report(
    path: Path | str,
) -> ProductionSafetyQualificationSourceIntegrityReport:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    payload["source_path"] = payload.get("source_path") or str(expanded)
    payload["sha256"] = payload.get("sha256") or sha256_file(expanded)
    return ProductionSafetyQualificationSourceIntegrityReport.model_validate(payload)


def run_production_safety_qualification_bundle_admission(
    bundle_paths: list[Path | str],
    *,
    source_package_paths: list[Path | str] | None = None,
    source_root_path: Path | str | None = None,
    source_integrity_output_dir: Path | str | None = None,
    admission_output_dir: Path | str | None = None,
    receipt_output_dir: Path | str | None = None,
) -> list[ProductionSafetyQualificationReceiptAdmissionDecision]:
    package_paths = source_package_paths or []
    if package_paths and len(package_paths) != len(bundle_paths):
        raise ValueError("source package count must match bundle count")
    source_integrity_dir = (
        Path(source_integrity_output_dir).expanduser()
        if source_integrity_output_dir
        else None
    )
    admission_dir = Path(admission_output_dir).expanduser() if admission_output_dir else None
    receipt_dir = Path(receipt_output_dir).expanduser() if receipt_output_dir else None
    decisions: list[ProductionSafetyQualificationReceiptAdmissionDecision] = []
    for index, bundle_path in enumerate(bundle_paths, start=1):
        bundle = load_production_safety_qualification_evidence_bundle(bundle_path)
        source_report = None
        if package_paths:
            package = load_production_safety_qualification_evidence_package(
                package_paths[index - 1]
            )
            source_report = verify_production_safety_qualification_source_integrity(
                bundle,
                package,
                root_path=source_root_path,
                source_path=f"{package.source_path}/source-integrity",
            )
            if source_integrity_dir is not None:
                source_report = (
                    write_production_safety_qualification_source_integrity_report(
                        source_report,
                        source_integrity_dir
                        / _qualification_artifact_filename(
                            index,
                            source_report.area,
                            "source-integrity",
                        ),
                    )
                )
        decision = evaluate_production_safety_qualification_bundle(
            bundle,
            source_integrity_report=source_report,
        )
        if admission_dir is not None:
            decision = write_production_safety_qualification_receipt_admission_decision(
                decision,
                admission_dir / _qualification_artifact_filename(
                    index,
                    decision.area,
                    "admission",
                ),
            )
        if receipt_dir is not None:
            write_production_safety_qualification_receipt(
                decision.receipt,
                receipt_dir
                / _qualification_artifact_filename(index, decision.area, "receipt"),
            )
        decisions.append(decision)
    return decisions


def write_production_safety_cutover_readiness_audit(
    audit: ProductionSafetyCutoverReadinessAudit,
    output_path: Path | str,
) -> ProductionSafetyCutoverReadinessAudit:
    path = Path(output_path).expanduser()
    _write_json(path, audit.model_dump(mode="json"))
    return load_production_safety_cutover_readiness_audit(path)


def load_production_safety_cutover_readiness_audit(
    path: Path | str,
) -> ProductionSafetyCutoverReadinessAudit:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    payload["source_path"] = payload.get("source_path") or str(expanded)
    payload["sha256"] = payload.get("sha256") or sha256_file(expanded)
    return ProductionSafetyCutoverReadinessAudit.model_validate(payload)


def run_production_safety_cutover_readiness_audit(
    receipt_paths: list[Path | str],
    *,
    output_path: Path | str | None = None,
    source_path: str = "inline:production-safety-cutover-readiness-cli",
) -> ProductionSafetyCutoverReadinessAudit:
    receipts = load_production_safety_qualification_receipts(receipt_paths)
    audit = evaluate_production_safety_cutover_readiness(
        receipts,
        source_path=source_path,
    )
    if output_path is None:
        return audit
    return write_production_safety_cutover_readiness_audit(audit, output_path)


def load_production_safety_qualification_dossier_manifest(
    path: Path | str,
) -> ProductionSafetyQualificationDossierManifest:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    return ProductionSafetyQualificationDossierManifest.model_validate(payload)


def write_production_safety_qualification_dossier_report(
    report: ProductionSafetyQualificationDossierReport,
    output_path: Path | str,
) -> ProductionSafetyQualificationDossierReport:
    path = Path(output_path).expanduser()
    _write_json(path, report.model_dump(mode="json"))
    return load_production_safety_qualification_dossier_report(path)


def load_production_safety_qualification_dossier_report(
    path: Path | str,
) -> ProductionSafetyQualificationDossierReport:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    payload["source_path"] = payload.get("source_path") or str(expanded)
    payload["sha256"] = payload.get("sha256") or sha256_file(expanded)
    return ProductionSafetyQualificationDossierReport.model_validate(payload)


def write_production_safety_qualification_gap_plan(
    plan: ProductionSafetyQualificationGapPlan,
    output_path: Path | str,
) -> ProductionSafetyQualificationGapPlan:
    path = Path(output_path).expanduser()
    _write_json(path, plan.model_dump(mode="json"))
    return load_production_safety_qualification_gap_plan(path)


def load_production_safety_qualification_gap_plan(
    path: Path | str,
) -> ProductionSafetyQualificationGapPlan:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    payload["source_path"] = payload.get("source_path") or str(expanded)
    payload["sha256"] = payload.get("sha256") or sha256_file(expanded)
    return ProductionSafetyQualificationGapPlan.model_validate(payload)


def write_production_safety_qualification_evidence_request_pack(
    pack: ProductionSafetyQualificationEvidenceRequestPack,
    output_path: Path | str,
) -> ProductionSafetyQualificationEvidenceRequestPack:
    path = Path(output_path).expanduser()
    _write_json(path, pack.model_dump(mode="json"))
    return load_production_safety_qualification_evidence_request_pack(path)


def load_production_safety_qualification_evidence_request_pack(
    path: Path | str,
) -> ProductionSafetyQualificationEvidenceRequestPack:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    payload["source_path"] = payload.get("source_path") or str(expanded)
    payload["sha256"] = payload.get("sha256") or sha256_file(expanded)
    return ProductionSafetyQualificationEvidenceRequestPack.model_validate(payload)


def load_production_safety_qualification_evidence_fulfillment_manifest(
    path: Path | str,
) -> ProductionSafetyQualificationEvidenceFulfillmentManifest:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    return ProductionSafetyQualificationEvidenceFulfillmentManifest.model_validate(payload)


def write_production_safety_qualification_evidence_fulfillment_manifest(
    manifest: ProductionSafetyQualificationEvidenceFulfillmentManifest,
    output_path: Path | str,
) -> ProductionSafetyQualificationEvidenceFulfillmentManifest:
    path = Path(output_path).expanduser()
    _write_json(path, manifest.model_dump(mode="json"))
    return load_production_safety_qualification_evidence_fulfillment_manifest(path)


def load_production_safety_qualification_evidence_fulfillment_source_package(
    path: Path | str,
) -> ProductionSafetyQualificationEvidenceFulfillmentSourcePackage:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    return ProductionSafetyQualificationEvidenceFulfillmentSourcePackage.model_validate(
        payload
    )


def write_production_safety_qualification_evidence_fulfillment_source_integrity_report(
    report: ProductionSafetyQualificationEvidenceFulfillmentSourceIntegrityReport,
    output_path: Path | str,
) -> ProductionSafetyQualificationEvidenceFulfillmentSourceIntegrityReport:
    path = Path(output_path).expanduser()
    _write_json(path, report.model_dump(mode="json"))
    return load_production_safety_qualification_evidence_fulfillment_source_integrity_report(
        path
    )


def load_production_safety_qualification_evidence_fulfillment_source_integrity_report(
    path: Path | str,
) -> ProductionSafetyQualificationEvidenceFulfillmentSourceIntegrityReport:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    payload["source_path"] = payload.get("source_path") or str(expanded)
    payload["sha256"] = payload.get("sha256") or sha256_file(expanded)
    return ProductionSafetyQualificationEvidenceFulfillmentSourceIntegrityReport.model_validate(
        payload
    )


def write_production_safety_qualification_evidence_fulfillment_report(
    report: ProductionSafetyQualificationEvidenceFulfillmentReport,
    output_path: Path | str,
) -> ProductionSafetyQualificationEvidenceFulfillmentReport:
    path = Path(output_path).expanduser()
    _write_json(path, report.model_dump(mode="json"))
    return load_production_safety_qualification_evidence_fulfillment_report(path)


def load_production_safety_qualification_evidence_fulfillment_report(
    path: Path | str,
) -> ProductionSafetyQualificationEvidenceFulfillmentReport:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    payload["source_path"] = payload.get("source_path") or str(expanded)
    payload["sha256"] = payload.get("sha256") or sha256_file(expanded)
    return ProductionSafetyQualificationEvidenceFulfillmentReport.model_validate(payload)


def write_production_safety_qualification_remediation_readiness_report(
    report: ProductionSafetyQualificationRemediationReadinessReport,
    output_path: Path | str,
) -> ProductionSafetyQualificationRemediationReadinessReport:
    path = Path(output_path).expanduser()
    _write_json(path, report.model_dump(mode="json"))
    return load_production_safety_qualification_remediation_readiness_report(path)


def load_production_safety_qualification_remediation_readiness_report(
    path: Path | str,
) -> ProductionSafetyQualificationRemediationReadinessReport:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    payload["source_path"] = payload.get("source_path") or str(expanded)
    payload["sha256"] = payload.get("sha256") or sha256_file(expanded)
    return ProductionSafetyQualificationRemediationReadinessReport.model_validate(
        payload
    )


def write_production_safety_qualification_external_action_packet(
    packet: ProductionSafetyQualificationExternalActionPacket,
    output_path: Path | str,
) -> ProductionSafetyQualificationExternalActionPacket:
    path = Path(output_path).expanduser()
    _write_json(path, packet.model_dump(mode="json"))
    return load_production_safety_qualification_external_action_packet(path)


def load_production_safety_qualification_external_action_packet(
    path: Path | str,
) -> ProductionSafetyQualificationExternalActionPacket:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    payload["source_path"] = payload.get("source_path") or str(expanded)
    payload["sha256"] = payload.get("sha256") or sha256_file(expanded)
    return ProductionSafetyQualificationExternalActionPacket.model_validate(payload)


def load_production_safety_qualification_external_authorization_manifest(
    path: Path | str,
) -> ProductionSafetyQualificationExternalAuthorizationManifest:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    return ProductionSafetyQualificationExternalAuthorizationManifest.model_validate(
        payload
    )


def write_production_safety_qualification_external_authorization_report(
    report: ProductionSafetyQualificationExternalAuthorizationReport,
    output_path: Path | str,
) -> ProductionSafetyQualificationExternalAuthorizationReport:
    path = Path(output_path).expanduser()
    _write_json(path, report.model_dump(mode="json"))
    return load_production_safety_qualification_external_authorization_report(path)


def load_production_safety_qualification_external_authorization_report(
    path: Path | str,
) -> ProductionSafetyQualificationExternalAuthorizationReport:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    payload["source_path"] = payload.get("source_path") or str(expanded)
    payload["sha256"] = payload.get("sha256") or sha256_file(expanded)
    return ProductionSafetyQualificationExternalAuthorizationReport.model_validate(
        payload
    )


def load_production_safety_qualification_external_invocation_manifest(
    path: Path | str,
) -> ProductionSafetyQualificationExternalInvocationManifest:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    return ProductionSafetyQualificationExternalInvocationManifest.model_validate(
        payload
    )


def write_production_safety_qualification_external_invocation_report(
    report: ProductionSafetyQualificationExternalInvocationReport,
    output_path: Path | str,
) -> ProductionSafetyQualificationExternalInvocationReport:
    path = Path(output_path).expanduser()
    _write_json(path, report.model_dump(mode="json"))
    return load_production_safety_qualification_external_invocation_report(path)


def load_production_safety_qualification_external_invocation_report(
    path: Path | str,
) -> ProductionSafetyQualificationExternalInvocationReport:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    payload["source_path"] = payload.get("source_path") or str(expanded)
    payload["sha256"] = payload.get("sha256") or sha256_file(expanded)
    return ProductionSafetyQualificationExternalInvocationReport.model_validate(
        payload
    )


def load_production_safety_qualification_external_result_manifest(
    path: Path | str,
) -> ProductionSafetyQualificationExternalResultManifest:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    return ProductionSafetyQualificationExternalResultManifest.model_validate(payload)


def write_production_safety_qualification_external_result_report(
    report: ProductionSafetyQualificationExternalResultReport,
    output_path: Path | str,
) -> ProductionSafetyQualificationExternalResultReport:
    path = Path(output_path).expanduser()
    _write_json(path, report.model_dump(mode="json"))
    return load_production_safety_qualification_external_result_report(path)


def load_production_safety_qualification_external_result_report(
    path: Path | str,
) -> ProductionSafetyQualificationExternalResultReport:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    payload["source_path"] = payload.get("source_path") or str(expanded)
    payload["sha256"] = payload.get("sha256") or sha256_file(expanded)
    return ProductionSafetyQualificationExternalResultReport.model_validate(payload)


def write_production_safety_qualification_external_result_evidence_bridge_report(
    report: ProductionSafetyQualificationExternalResultEvidenceBridgeReport,
    output_path: Path | str,
) -> ProductionSafetyQualificationExternalResultEvidenceBridgeReport:
    path = Path(output_path).expanduser()
    _write_json(path, report.model_dump(mode="json"))
    return load_production_safety_qualification_external_result_evidence_bridge_report(
        path
    )


def load_production_safety_qualification_external_result_evidence_bridge_report(
    path: Path | str,
) -> ProductionSafetyQualificationExternalResultEvidenceBridgeReport:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    payload["source_path"] = payload.get("source_path") or str(expanded)
    payload["sha256"] = payload.get("sha256") or sha256_file(expanded)
    return ProductionSafetyQualificationExternalResultEvidenceBridgeReport.model_validate(
        payload
    )


def write_production_safety_qualification_external_result_remediation_closure_report(
    report: ProductionSafetyQualificationExternalResultRemediationClosureReport,
    output_path: Path | str,
) -> ProductionSafetyQualificationExternalResultRemediationClosureReport:
    path = Path(output_path).expanduser()
    _write_json(path, report.model_dump(mode="json"))
    return load_production_safety_qualification_external_result_remediation_closure_report(
        path
    )


def load_production_safety_qualification_external_result_remediation_closure_report(
    path: Path | str,
) -> ProductionSafetyQualificationExternalResultRemediationClosureReport:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    payload["source_path"] = payload.get("source_path") or str(expanded)
    payload["sha256"] = payload.get("sha256") or sha256_file(expanded)
    return ProductionSafetyQualificationExternalResultRemediationClosureReport.model_validate(
        payload
    )


def write_production_safety_qualification_dossier_rerun_report(
    report: ProductionSafetyQualificationDossierRerunReport,
    output_path: Path | str,
) -> ProductionSafetyQualificationDossierRerunReport:
    path = Path(output_path).expanduser()
    _write_json(path, report.model_dump(mode="json"))
    return load_production_safety_qualification_dossier_rerun_report(path)


def load_production_safety_qualification_dossier_rerun_report(
    path: Path | str,
) -> ProductionSafetyQualificationDossierRerunReport:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    payload["source_path"] = payload.get("source_path") or str(expanded)
    payload["sha256"] = payload.get("sha256") or sha256_file(expanded)
    return ProductionSafetyQualificationDossierRerunReport.model_validate(payload)


def load_production_safety_qualification_cutover_authorization_manifest(
    path: Path | str,
) -> ProductionSafetyQualificationCutoverAuthorizationManifest:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    return ProductionSafetyQualificationCutoverAuthorizationManifest.model_validate(
        payload
    )


def write_production_safety_qualification_cutover_authorization_report(
    report: ProductionSafetyQualificationCutoverAuthorizationReport,
    output_path: Path | str,
) -> ProductionSafetyQualificationCutoverAuthorizationReport:
    path = Path(output_path).expanduser()
    _write_json(path, report.model_dump(mode="json"))
    return load_production_safety_qualification_cutover_authorization_report(path)


def load_production_safety_qualification_cutover_authorization_report(
    path: Path | str,
) -> ProductionSafetyQualificationCutoverAuthorizationReport:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    payload["source_path"] = payload.get("source_path") or str(expanded)
    payload["sha256"] = payload.get("sha256") or sha256_file(expanded)
    return ProductionSafetyQualificationCutoverAuthorizationReport.model_validate(
        payload
    )


def load_production_safety_qualification_cutover_release_handoff_manifest(
    path: Path | str,
) -> ProductionSafetyQualificationCutoverReleaseHandoffManifest:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    return ProductionSafetyQualificationCutoverReleaseHandoffManifest.model_validate(
        payload
    )


def write_production_safety_qualification_cutover_release_handoff_report(
    report: ProductionSafetyQualificationCutoverReleaseHandoffReport,
    output_path: Path | str,
) -> ProductionSafetyQualificationCutoverReleaseHandoffReport:
    path = Path(output_path).expanduser()
    _write_json(path, report.model_dump(mode="json"))
    return load_production_safety_qualification_cutover_release_handoff_report(path)


def load_production_safety_qualification_cutover_release_handoff_report(
    path: Path | str,
) -> ProductionSafetyQualificationCutoverReleaseHandoffReport:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    payload["source_path"] = payload.get("source_path") or str(expanded)
    payload["sha256"] = payload.get("sha256") or sha256_file(expanded)
    return ProductionSafetyQualificationCutoverReleaseHandoffReport.model_validate(
        payload
    )


def load_production_safety_qualification_cutover_release_effect_manifest(
    path: Path | str,
) -> ProductionSafetyQualificationCutoverReleaseEffectManifest:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    return ProductionSafetyQualificationCutoverReleaseEffectManifest.model_validate(
        payload
    )


def write_production_safety_qualification_cutover_release_effect_report(
    report: ProductionSafetyQualificationCutoverReleaseEffectReport,
    output_path: Path | str,
) -> ProductionSafetyQualificationCutoverReleaseEffectReport:
    path = Path(output_path).expanduser()
    _write_json(path, report.model_dump(mode="json"))
    return load_production_safety_qualification_cutover_release_effect_report(path)


def load_production_safety_qualification_cutover_release_effect_report(
    path: Path | str,
) -> ProductionSafetyQualificationCutoverReleaseEffectReport:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    payload["source_path"] = payload.get("source_path") or str(expanded)
    payload["sha256"] = payload.get("sha256") or sha256_file(expanded)
    return ProductionSafetyQualificationCutoverReleaseEffectReport.model_validate(
        payload
    )


def load_production_safety_qualification_cutover_release_closure_manifest(
    path: Path | str,
) -> ProductionSafetyQualificationCutoverReleaseClosureManifest:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    return ProductionSafetyQualificationCutoverReleaseClosureManifest.model_validate(
        payload
    )


def write_production_safety_qualification_cutover_release_closure_report(
    report: ProductionSafetyQualificationCutoverReleaseClosureReport,
    output_path: Path | str,
) -> ProductionSafetyQualificationCutoverReleaseClosureReport:
    path = Path(output_path).expanduser()
    _write_json(path, report.model_dump(mode="json"))
    return load_production_safety_qualification_cutover_release_closure_report(path)


def load_production_safety_qualification_cutover_release_closure_report(
    path: Path | str,
) -> ProductionSafetyQualificationCutoverReleaseClosureReport:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    payload["source_path"] = payload.get("source_path") or str(expanded)
    payload["sha256"] = payload.get("sha256") or sha256_file(expanded)
    return ProductionSafetyQualificationCutoverReleaseClosureReport.model_validate(
        payload
    )


def run_production_safety_qualification_dossier(
    manifest: ProductionSafetyQualificationDossierManifest | dict[str, Any] | Path | str,
    *,
    evaluation_time: datetime | None = None,
    output_path: Path | str | None = None,
    cutover_audit_output_path: Path | str | None = None,
    threat_coverage_output_path: Path | str | None = None,
    source_integrity_output_dir: Path | str | None = None,
    admission_output_dir: Path | str | None = None,
    receipt_output_dir: Path | str | None = None,
    source_path: str | None = None,
) -> ProductionSafetyQualificationDossierReport:
    # None preserves historical bundle-local replay; the CLI supplies current UTC.
    if evaluation_time is not None:
        if evaluation_time.utcoffset() is None:
            raise ValueError("dossier evaluation_time must be timezone-aware")
        evaluation_time = evaluation_time.astimezone(timezone.utc)
    manifest_model = _load_or_validate_dossier_manifest(manifest)
    entries_by_area = {entry.area: entry for entry in manifest_model.entries}
    source_root = manifest_model.source_root_path
    source_integrity_dir = (
        Path(source_integrity_output_dir).expanduser()
        if source_integrity_output_dir
        else None
    )
    admission_dir = Path(admission_output_dir).expanduser() if admission_output_dir else None
    receipt_dir = Path(receipt_output_dir).expanduser() if receipt_output_dir else None
    report_source_path = source_path or f"{manifest_model.source_path}/dossier-report"
    rows: list[ProductionSafetyQualificationDossierRow] = []
    receipts: list[ProductionSafetyQualificationReceipt] = []
    for index, area in enumerate(REQUIRED_PRODUCTION_SAFETY_QUALIFICATION_AREAS, start=1):
        row, receipt = _run_dossier_area(
            index,
            area,
            entries_by_area.get(area),
            evaluation_time=evaluation_time,
            source_root_path=source_root,
            source_integrity_output_dir=source_integrity_dir,
            admission_output_dir=admission_dir,
            receipt_output_dir=receipt_dir,
        )
        rows.append(row)
        if receipt is not None:
            receipts.append(receipt)
    threat_coverage_audit, threat_coverage_status, threat_blockers = (
        _run_dossier_threat_coverage(
            manifest_model.threat_coverage_path,
            evaluation_time=evaluation_time,
            source_package_path=manifest_model.threat_coverage_source_package_path,
            source_root_path=source_root,
            source_integrity_output_path=(
                None
                if source_integrity_dir is None
                else source_integrity_dir / "00-threat-coverage-source-integrity.json"
            ),
            output_path=threat_coverage_output_path,
            source_path=f"{report_source_path}/threat-coverage",
        )
    )
    threat_coverage_ready = bool(
        threat_coverage_audit
        and threat_coverage_audit.ready_for_production_cutover_threat_coverage
    )
    cutover_audit = evaluate_production_safety_cutover_readiness(
        receipts,
        source_path=f"{report_source_path}/cutover-audit",
    )
    if cutover_audit_output_path is not None:
        cutover_audit = write_production_safety_cutover_readiness_audit(
            cutover_audit,
            cutover_audit_output_path,
        )
    missing = _ordered_unique_areas(
        [
            *[
                row.area
                for row in rows
                if row.status in {"missing_entry", "missing_paths", "load_failed"}
            ],
            *cutover_audit.missing_areas,
        ]
    )
    dossier_blockers = list(threat_blockers)
    failed = _ordered_unique_areas(
        [
            *[
                row.area
                for row in rows
                if row.status
                in {"source_integrity_failed", "admission_failed"}
            ],
            *cutover_audit.failed_areas,
        ]
    )
    if (
        cutover_audit.ready_for_production_cutover
        and threat_coverage_ready
        and all(row.qualified_for_cutover for row in rows)
    ):
        status: ProductionSafetyQualificationDossierStatus = (
            "dossier_ready_for_production_cutover"
        )
    elif missing or threat_coverage_status == "missing":
        status = "blocked_dossier_incomplete"
    else:
        status = "blocked_dossier_failed"
    digest = aggregate_sha256(
        [
            {
                "source_path": report_source_path,
                "manifest_ref": manifest_model.source_path,
                "evaluation_time": (
                    evaluation_time.isoformat() if evaluation_time is not None else None
                ),
                "row_statuses": [
                    {
                        "area": row.area,
                        "status": row.status,
                        "receipt_sha256": row.receipt_sha256,
                    }
                    for row in rows
                ],
                "cutover_audit_sha256": cutover_audit.sha256,
                "threat_coverage_audit_sha256": (
                    threat_coverage_audit.sha256 if threat_coverage_audit else None
                ),
                "threat_coverage_status": threat_coverage_status,
                "status": status,
            }
        ]
    )
    report = ProductionSafetyQualificationDossierReport(
        source_path=report_source_path,
        sha256=digest,
        status=status,
        evaluation_time=evaluation_time,
        required_areas=list(REQUIRED_PRODUCTION_SAFETY_QUALIFICATION_AREAS),
        rows=rows,
        cutover_audit=cutover_audit,
        threat_coverage_audit=threat_coverage_audit,
        threat_coverage_status=threat_coverage_status,
        threat_coverage_ready=threat_coverage_ready,
        ready_for_production_cutover=status == "dossier_ready_for_production_cutover",
        missing_areas=missing,
        failed_areas=failed,
        dossier_blockers=dossier_blockers,
    )
    if output_path is None:
        return report
    return write_production_safety_qualification_dossier_report(report, output_path)


def evaluate_production_safety_qualification_gap_plan(
    dossier_report: ProductionSafetyQualificationDossierReport
    | dict[str, Any]
    | Path
    | str,
    *,
    source_path: str | None = None,
) -> ProductionSafetyQualificationGapPlan:
    report = _load_or_validate_dossier_report(dossier_report)
    rows = [
        *[
            _gap_row_from_dossier_area(row)
            for row in report.rows
            if not row.qualified_for_cutover
        ],
        *_gap_rows_from_threat_coverage(report),
    ]
    if not rows and not report.ready_for_production_cutover:
        rows.append(
            ProductionSafetyQualificationGapRow(
                gap_kind="dossier",
                action="rerun_dossier_after_evidence_update",
                source_status=report.status,
                blockers=[report.status],
                required_artifacts=["production_qualification_dossier_report"],
                unblock_condition=(
                    "rerun the production qualification dossier after repairing "
                    "the underlying required evidence"
                ),
            )
        )
    ready = report.ready_for_production_cutover and not rows
    status: ProductionSafetyQualificationGapPlanStatus = (
        "production_qualification_gaps_resolved"
        if ready
        else "blocked_production_qualification_gaps_open"
    )
    plan_source_path = source_path or f"{report.source_path}/gap-plan"
    digest = aggregate_sha256(
        [
            {
                "source_path": plan_source_path,
                "dossier_report_ref": report.source_path,
                "dossier_report_sha256": report.sha256,
                "row_statuses": [
                    {
                        "gap_kind": row.gap_kind,
                        "area": row.area,
                        "threat_id": row.threat_id,
                        "mode_id": row.mode_id,
                        "action": row.action,
                        "status": row.status,
                        "source_status": row.source_status,
                    }
                    for row in rows
                ],
                "status": status,
            }
        ]
    )
    return ProductionSafetyQualificationGapPlan(
        source_path=plan_source_path,
        sha256=digest,
        status=status,
        dossier_report_ref=report.source_path,
        dossier_report_sha256=report.sha256,
        ready_for_production_cutover=ready,
        open_gap_count=len(rows),
        rows=rows,
        limitations=[
            "internal production qualification gap plan only",
            "does not perform diagnostics, call providers, load credentials, mutate runtime safety truth, send transport, verify delivery, or control hardware",
        ],
    )


def build_production_safety_qualification_evidence_request_pack(
    gap_plan: ProductionSafetyQualificationGapPlan | dict[str, Any] | Path | str,
    *,
    source_path: str | None = None,
) -> ProductionSafetyQualificationEvidenceRequestPack:
    plan = _load_or_validate_gap_plan(gap_plan)
    rows = [
        request_row
        for gap_row in plan.rows
        for request_row in _evidence_request_rows_from_gap(gap_row)
    ]
    status: ProductionSafetyQualificationEvidenceRequestPackStatus = (
        "evidence_request_pack_ready"
        if rows
        else "no_evidence_requests_required"
    )
    request_source_path = source_path or f"{plan.source_path}/evidence-request-pack"
    digest = aggregate_sha256(
        [
            {
                "source_path": request_source_path,
                "gap_plan_ref": plan.source_path,
                "gap_plan_sha256": plan.sha256,
                "requests": [
                    {
                        "request_kind": row.request_kind,
                        "area": row.area,
                        "threat_id": row.threat_id,
                        "mode_id": row.mode_id,
                        "required_claims": row.required_claims,
                    }
                    for row in rows
                ],
                "status": status,
            }
        ]
    )
    return ProductionSafetyQualificationEvidenceRequestPack(
        source_path=request_source_path,
        sha256=digest,
        status=status,
        gap_plan_ref=plan.source_path,
        gap_plan_sha256=plan.sha256,
        request_count=len(rows),
        rows=rows,
        limitations=[
            "internal evidence request pack only",
            "does not collect evidence, call providers, load credentials, mutate runtime safety truth, send transport, verify delivery, or control hardware",
        ],
    )


def verify_production_safety_qualification_evidence_fulfillment_source_integrity(
    fulfillment_manifest: ProductionSafetyQualificationEvidenceFulfillmentManifest
    | dict[str, Any]
    | Path
    | str,
    source_package: ProductionSafetyQualificationEvidenceFulfillmentSourcePackage
    | dict[str, Any]
    | Path
    | str,
    *,
    root_path: Path | str | None = None,
    source_path: str | None = None,
) -> ProductionSafetyQualificationEvidenceFulfillmentSourceIntegrityReport:
    manifest = _load_or_validate_evidence_fulfillment_manifest(fulfillment_manifest)
    package = _load_or_validate_evidence_fulfillment_source_package(source_package)
    manifest_sha = _qualification_fulfillment_manifest_sha256(manifest)
    if package.fulfillment_manifest_ref != manifest.source_path:
        raise ValueError(
            "fulfillment source package manifest ref must match fulfillment manifest"
        )
    if package.fulfillment_manifest_sha256 != manifest_sha:
        raise ValueError(
            "fulfillment source package manifest sha must match fulfillment manifest"
        )
    artifacts_by_ref = {
        artifact.submitted_artifact_ref: artifact for artifact in package.artifacts
    }
    requested_refs = {
        submission.submitted_artifact_ref for submission in manifest.submissions
    }
    rows = [
        _fulfillment_source_integrity_row(
            submission,
            artifacts_by_ref.get(submission.submitted_artifact_ref),
            root_path,
        )
        for submission in manifest.submissions
    ]
    rows.extend(
        _unrequested_fulfillment_source_integrity_row(artifact)
        for artifact in package.artifacts
        if artifact.submitted_artifact_ref not in requested_refs
    )
    verified_refs = [
        row.submitted_artifact_ref for row in rows if row.status == "verified"
    ]
    missing_refs = [
        row.submitted_artifact_ref for row in rows if row.status == "missing"
    ]
    mismatched_refs = [
        row.submitted_artifact_ref for row in rows if row.status == "hash_mismatch"
    ]
    unsafe_refs = [
        row.submitted_artifact_ref for row in rows if row.status == "unsafe_path"
    ]
    sensitive_refs = [
        row.submitted_artifact_ref
        for row in rows
        if row.status == "sensitive_material"
    ]
    unrequested_refs = [
        row.submitted_artifact_ref for row in rows if row.status == "unrequested"
    ]
    all_verified = all(row.source_integrity_verified for row in rows)
    status: ProductionSafetyQualificationEvidenceFulfillmentSourceIntegrityStatus = (
        "fulfillment_source_integrity_verified"
        if all_verified
        else "blocked_fulfillment_source_integrity_failed"
    )
    report_source_path = (
        source_path or f"{package.source_path}/fulfillment-source-integrity"
    )
    digest = aggregate_sha256(
        [
            {
                "source_path": report_source_path,
                "fulfillment_manifest_ref": manifest.source_path,
                "fulfillment_manifest_sha256": manifest_sha,
                "source_package_ref": package.source_path,
                "row_statuses": [
                    {
                        "submitted_artifact_ref": row.submitted_artifact_ref,
                        "expected_sha256": row.expected_sha256,
                        "actual_sha256": row.actual_sha256,
                        "status": row.status,
                    }
                    for row in rows
                ],
                "status": status,
            }
        ]
    )
    return ProductionSafetyQualificationEvidenceFulfillmentSourceIntegrityReport(
        source_path=report_source_path,
        sha256=digest,
        fulfillment_manifest_ref=manifest.source_path,
        fulfillment_manifest_sha256=manifest_sha,
        source_package_ref=package.source_path,
        status=status,
        rows=rows,
        verified_submitted_artifact_refs=verified_refs,
        missing_submitted_artifact_refs=missing_refs,
        mismatched_submitted_artifact_refs=mismatched_refs,
        unsafe_submitted_artifact_refs=unsafe_refs,
        sensitive_submitted_artifact_refs=sensitive_refs,
        unrequested_submitted_artifact_refs=unrequested_refs,
        all_fulfillment_sources_verified=all_verified,
        limitations=[
            "internal evidence fulfillment source-integrity check only",
            "does not collect evidence, inspect credentials, call providers, mutate runtime safety truth, send transport, verify delivery, or control hardware",
        ],
    )


def evaluate_production_safety_qualification_evidence_fulfillment(
    request_pack: ProductionSafetyQualificationEvidenceRequestPack
    | dict[str, Any]
    | Path
    | str,
    fulfillment_manifest: ProductionSafetyQualificationEvidenceFulfillmentManifest
    | dict[str, Any]
    | Path
    | str,
    *,
    source_integrity_report: (
        ProductionSafetyQualificationEvidenceFulfillmentSourceIntegrityReport
        | dict[str, Any]
        | Path
        | str
        | None
    ) = None,
    source_path: str | None = None,
) -> ProductionSafetyQualificationEvidenceFulfillmentReport:
    pack = _load_or_validate_evidence_request_pack(request_pack)
    manifest = _load_or_validate_evidence_fulfillment_manifest(fulfillment_manifest)
    manifest_sha = _qualification_fulfillment_manifest_sha256(manifest)
    if manifest.request_pack_ref != pack.source_path:
        raise ValueError("fulfillment manifest request_pack_ref must match request pack")
    if manifest.request_pack_sha256 != pack.sha256:
        raise ValueError("fulfillment manifest request_pack_sha256 must match request pack")
    source_report = _load_or_validate_evidence_fulfillment_source_integrity_report(
        source_integrity_report
    )
    if source_report is not None:
        if source_report.fulfillment_manifest_ref != manifest.source_path:
            raise ValueError(
                "source-integrity report manifest ref must match fulfillment manifest"
            )
        if source_report.fulfillment_manifest_sha256 != manifest_sha:
            raise ValueError(
                "source-integrity report manifest sha must match fulfillment manifest"
            )
    verified_source_refs = _evidence_fulfillment_source_integrity_verified_refs(
        source_report
    )
    submissions_by_key = {
        _evidence_request_submission_key(submission): submission
        for submission in manifest.submissions
    }
    rows = [
        _evidence_fulfillment_row(
            request,
            submissions_by_key.get(_evidence_request_key(request)),
            verified_source_refs=verified_source_refs,
        )
        for request in pack.rows
    ]
    missing_count = len([row for row in rows if row.status == "missing"])
    mismatched_count = len([row for row in rows if row.status == "mismatched"])
    rejected_count = len([row for row in rows if row.status == "rejected"])
    source_unverified_count = len(
        [row for row in rows if row.status == "source_unverified"]
    )
    if missing_count:
        status: ProductionSafetyQualificationEvidenceRequestFulfillmentStatus = (
            "blocked_missing_requested_evidence"
        )
    elif mismatched_count:
        status = "blocked_mismatched_requested_evidence"
    elif rejected_count:
        status = "blocked_rejected_requested_evidence"
    elif source_unverified_count:
        status = "blocked_fulfillment_source_integrity_unverified"
    else:
        status = "evidence_request_fulfillment_verified"
    report_source_path = source_path or f"{manifest.source_path}/fulfillment-report"
    digest = aggregate_sha256(
        [
            {
                "source_path": report_source_path,
                "request_pack_ref": pack.source_path,
                "request_pack_sha256": pack.sha256,
                "fulfillment_manifest_ref": manifest.source_path,
                "fulfillment_manifest_sha256": manifest_sha,
                "source_integrity_report_ref": (
                    source_report.source_path if source_report else None
                ),
                "source_integrity_report_sha256": (
                    source_report.sha256 if source_report else None
                ),
                "row_statuses": [
                    {
                        "request_kind": row.request_kind,
                        "area": row.area,
                        "threat_id": row.threat_id,
                        "mode_id": row.mode_id,
                        "status": row.status,
                    }
                    for row in rows
                ],
                "status": status,
            }
        ]
    )
    return ProductionSafetyQualificationEvidenceFulfillmentReport(
        source_path=report_source_path,
        sha256=digest,
        status=status,
        request_pack_ref=pack.source_path,
        request_pack_sha256=pack.sha256,
        fulfillment_manifest_ref=manifest.source_path,
        fulfillment_manifest_sha256=manifest_sha,
        source_integrity_report_ref=source_report.source_path if source_report else None,
        source_integrity_report_sha256=source_report.sha256 if source_report else None,
        source_integrity_verified=bool(
            source_report and source_report.all_fulfillment_sources_verified
        ),
        rows=rows,
        fulfilled_request_count=len([row for row in rows if row.status == "fulfilled"]),
        missing_request_count=missing_count,
        mismatched_request_count=mismatched_count,
        rejected_request_count=rejected_count,
        source_unverified_request_count=source_unverified_count,
        unverified_source_refs=[
            row.submitted_artifact_ref
            for row in rows
            if row.status == "source_unverified" and row.submitted_artifact_ref
        ],
        all_requested_evidence_fulfilled=(
            status == "evidence_request_fulfillment_verified"
        ),
        limitations=[
            "internal evidence request fulfillment intake only",
            "requires source-integrity-verified fulfillment artifacts before reporting verified",
            "does not collect evidence, inspect credentials, call providers, mutate runtime safety truth, send transport, verify delivery, or control hardware",
        ],
    )


def evaluate_production_safety_qualification_remediation_readiness(
    gap_plan: ProductionSafetyQualificationGapPlan | dict[str, Any] | Path | str,
    request_pack: ProductionSafetyQualificationEvidenceRequestPack
    | dict[str, Any]
    | Path
    | str,
    fulfillment_report: ProductionSafetyQualificationEvidenceFulfillmentReport
    | dict[str, Any]
    | Path
    | str,
    *,
    source_path: str | None = None,
) -> ProductionSafetyQualificationRemediationReadinessReport:
    plan = _load_or_validate_gap_plan(gap_plan)
    pack = _load_or_validate_evidence_request_pack(request_pack)
    fulfillment = _load_or_validate_evidence_fulfillment_report(fulfillment_report)
    if pack.gap_plan_ref != plan.source_path:
        raise ValueError("request pack gap_plan_ref must match gap plan")
    if pack.gap_plan_sha256 != plan.sha256:
        raise ValueError("request pack gap_plan_sha256 must match gap plan")
    if fulfillment.request_pack_ref != pack.source_path:
        raise ValueError("fulfillment report request_pack_ref must match request pack")
    if fulfillment.request_pack_sha256 != pack.sha256:
        raise ValueError(
            "fulfillment report request_pack_sha256 must match request pack"
        )
    request_keys = {_evidence_request_key(row) for row in pack.rows}
    fulfillment_rows_by_key = {
        _evidence_fulfillment_report_row_key(row): row
        for row in fulfillment.rows
    }
    rows = [
        _remediation_row_from_gap(
            gap,
            request_keys=request_keys,
            fulfillment_rows_by_key=fulfillment_rows_by_key,
        )
        for gap in plan.rows
    ]
    if not rows and plan.ready_for_production_cutover:
        status: ProductionSafetyQualificationRemediationStatus = (
            "no_remediation_required"
        )
    elif rows and all(row.ready_for_dossier_rerun for row in rows):
        status = "ready_for_dossier_rerun"
    else:
        status = "blocked_remediation_incomplete"
    report_source_path = source_path or f"{fulfillment.source_path}/remediation"
    digest = aggregate_sha256(
        [
            {
                "source_path": report_source_path,
                "gap_plan_ref": plan.source_path,
                "gap_plan_sha256": plan.sha256,
                "request_pack_ref": pack.source_path,
                "request_pack_sha256": pack.sha256,
                "fulfillment_report_ref": fulfillment.source_path,
                "fulfillment_report_sha256": fulfillment.sha256,
                "row_statuses": [
                    {
                        "gap_kind": row.gap_kind,
                        "area": row.area,
                        "threat_id": row.threat_id,
                        "mode_id": row.mode_id,
                        "status": row.status,
                    }
                    for row in rows
                ],
                "status": status,
            }
        ]
    )
    return ProductionSafetyQualificationRemediationReadinessReport(
        source_path=report_source_path,
        sha256=digest,
        status=status,
        gap_plan_ref=plan.source_path,
        gap_plan_sha256=plan.sha256,
        request_pack_ref=pack.source_path,
        request_pack_sha256=pack.sha256,
        fulfillment_report_ref=fulfillment.source_path,
        fulfillment_report_sha256=fulfillment.sha256,
        rows=rows,
        ready_gap_count=len([row for row in rows if row.ready_for_dossier_rerun]),
        blocked_gap_count=len([row for row in rows if not row.ready_for_dossier_rerun]),
        all_open_gaps_remediated=status
        in {"no_remediation_required", "ready_for_dossier_rerun"},
        ready_for_dossier_rerun=status == "ready_for_dossier_rerun",
        limitations=[
            "internal remediation readiness gate only",
            "ready_for_dossier_rerun is not production cutover readiness",
            "does not apply evidence, rerun the dossier, call providers, mutate runtime safety truth, send transport, verify delivery, or control hardware",
        ],
    )


def build_production_safety_qualification_external_action_packet(
    remediation_report: ProductionSafetyQualificationRemediationReadinessReport
    | dict[str, Any]
    | Path
    | str,
    *,
    source_path: str | None = None,
) -> ProductionSafetyQualificationExternalActionPacket:
    remediation = _load_or_validate_remediation_readiness_report(remediation_report)
    rows = [
        _external_action_row_from_remediation_row(row)
        for row in remediation.rows
    ]
    if not rows and remediation.status == "no_remediation_required":
        status: ProductionSafetyQualificationExternalActionPacketStatus = (
            "no_external_actions_required"
        )
    elif rows and all(row.ready_for_operator_authorization for row in rows):
        status = "external_actions_ready_for_operator_authorization"
    else:
        status = "blocked_external_actions_incomplete"
    packet_source_path = source_path or f"{remediation.source_path}/external-actions"
    digest = aggregate_sha256(
        [
            {
                "source_path": packet_source_path,
                "remediation_report_ref": remediation.source_path,
                "remediation_report_sha256": remediation.sha256,
                "row_statuses": [
                    {
                        "gap_kind": row.gap_kind,
                        "area": row.area,
                        "threat_id": row.threat_id,
                        "mode_id": row.mode_id,
                        "external_action_kind": row.external_action_kind,
                        "status": row.status,
                    }
                    for row in rows
                ],
                "status": status,
            }
        ]
    )
    return ProductionSafetyQualificationExternalActionPacket(
        source_path=packet_source_path,
        sha256=digest,
        status=status,
        remediation_report_ref=remediation.source_path,
        remediation_report_sha256=remediation.sha256,
        gap_plan_ref=remediation.gap_plan_ref,
        gap_plan_sha256=remediation.gap_plan_sha256,
        request_pack_ref=remediation.request_pack_ref,
        request_pack_sha256=remediation.request_pack_sha256,
        fulfillment_report_ref=remediation.fulfillment_report_ref,
        fulfillment_report_sha256=remediation.fulfillment_report_sha256,
        rows=rows,
        ready_action_count=len(
            [row for row in rows if row.ready_for_operator_authorization]
        ),
        blocked_action_count=len(
            [row for row in rows if not row.ready_for_operator_authorization]
        ),
        ready_for_operator_authorization=(
            status == "external_actions_ready_for_operator_authorization"
        ),
        limitations=[
            "external qualification action packet only",
            "ready_for_operator_authorization is not execution approval",
            "does not call providers, resolve credentials, deploy writers, send transport, verify delivery, control Pi hardware, rerun dossiers, or mutate runtime safety truth",
        ],
    )


def _external_action_row_from_remediation_row(
    row: ProductionSafetyQualificationRemediationRow,
) -> ProductionSafetyQualificationExternalActionRow:
    ready = row.ready_for_dossier_rerun
    return ProductionSafetyQualificationExternalActionRow(
        gap_kind=row.gap_kind,
        action=row.action,
        external_action_kind=_external_action_kind_from_remediation_row(row),
        status=(
            "ready_for_operator_authorization"
            if ready
            else "blocked_remediation_incomplete"
        ),
        area=row.area,
        threat_id=row.threat_id,
        mode_id=row.mode_id,
        expected_request_count=row.expected_request_count,
        fulfilled_request_count=row.fulfilled_request_count,
        required_artifacts=_external_action_required_artifacts(row),
        ready_for_operator_authorization=ready,
        dossier_rerun_required=ready,
        blockers=[] if ready else row.blockers,
        next_action=(
            "request explicit operator authorization for the qualified external "
            "evidence path, then rerun the production qualification dossier"
            if ready
            else row.unblock_condition
        ),
    )


def _external_action_kind_from_remediation_row(
    row: ProductionSafetyQualificationRemediationRow,
) -> ProductionSafetyQualificationExternalActionKind:
    if row.area is not None:
        return PRODUCTION_SAFETY_QUALIFICATION_AREA_EXTERNAL_ACTION_KINDS[row.area]
    if row.gap_kind == "threat_source_integrity":
        return "threat_coverage_source_integrity_review"
    if row.gap_kind == "threat_coverage":
        return "threat_coverage_review"
    if row.gap_kind == "qualification_mode_coverage":
        return "qualification_mode_review"
    return "dossier_rerun"


def _external_action_required_artifacts(
    row: ProductionSafetyQualificationRemediationRow,
) -> list[str]:
    if row.area is not None:
        return [
            "production_qualification_evidence_bundle",
            "production_qualification_evidence_package",
            "production_qualification_receipt",
        ]
    if row.gap_kind == "threat_source_integrity":
        return [
            "production_qualification_threat_evidence_package",
            "production_qualification_threat_source_integrity_report",
        ]
    if row.gap_kind == "threat_coverage":
        return [
            "production_qualification_threat_case",
            "production_qualification_threat_evidence_package",
        ]
    if row.gap_kind == "qualification_mode_coverage":
        return [
            "production_qualification_mode_case",
            "production_qualification_threat_evidence_package",
        ]
    return [
        "production_qualification_dossier_manifest",
        "production_qualification_dossier_report",
    ]


def evaluate_production_safety_qualification_external_authorization(
    external_action_packet: ProductionSafetyQualificationExternalActionPacket
    | dict[str, Any]
    | Path
    | str,
    authorization_manifest: ProductionSafetyQualificationExternalAuthorizationManifest
    | dict[str, Any]
    | Path
    | str,
    *,
    source_path: str | None = None,
) -> ProductionSafetyQualificationExternalAuthorizationReport:
    packet = _load_or_validate_external_action_packet(external_action_packet)
    manifest = _load_or_validate_external_authorization_manifest(
        authorization_manifest
    )
    if manifest.external_action_packet_ref != packet.source_path:
        raise ValueError(
            "external authorization manifest packet ref must match packet"
        )
    if manifest.external_action_packet_sha256 != packet.sha256:
        raise ValueError(
            "external authorization manifest packet sha256 must match packet"
        )
    submissions_by_key = {
        _external_authorization_key(submission): submission
        for submission in manifest.submissions
    }
    rows = [
        _external_authorization_row_from_packet_row(
            row,
            submissions_by_key.get(_external_authorization_key(row)),
            manifest.reference_time,
        )
        for row in packet.rows
    ]
    if not rows and packet.status == "no_external_actions_required":
        status: ProductionSafetyQualificationExternalAuthorizationReportStatus = (
            "no_external_authorization_required"
        )
    elif rows and all(row.operator_authorization_recorded for row in rows):
        status = "external_authorization_recorded"
    else:
        status = "blocked_external_authorization_incomplete"
    report_source_path = source_path or f"{manifest.source_path}/report"
    manifest_sha = _external_authorization_manifest_sha256(manifest)
    digest = aggregate_sha256(
        [
            {
                "source_path": report_source_path,
                "external_action_packet_ref": packet.source_path,
                "external_action_packet_sha256": packet.sha256,
                "authorization_manifest_ref": manifest.source_path,
                "authorization_manifest_sha256": manifest_sha,
                "row_statuses": [
                    {
                        "gap_kind": row.gap_kind,
                        "area": row.area,
                        "threat_id": row.threat_id,
                        "mode_id": row.mode_id,
                        "external_action_kind": row.external_action_kind,
                        "status": row.status,
                    }
                    for row in rows
                ],
                "status": status,
            }
        ]
    )
    return ProductionSafetyQualificationExternalAuthorizationReport(
        source_path=report_source_path,
        sha256=digest,
        status=status,
        external_action_packet_ref=packet.source_path,
        external_action_packet_sha256=packet.sha256,
        authorization_manifest_ref=manifest.source_path,
        authorization_manifest_sha256=manifest_sha,
        remediation_report_ref=packet.remediation_report_ref,
        remediation_report_sha256=packet.remediation_report_sha256,
        rows=rows,
        authorized_action_count=len(
            [row for row in rows if row.operator_authorization_recorded]
        ),
        blocked_action_count=len(
            [row for row in rows if not row.operator_authorization_recorded]
        ),
        all_authorizations_recorded=(
            status
            in {
                "no_external_authorization_required",
                "external_authorization_recorded",
            }
        ),
        ready_for_separate_executor_invocation=(
            status == "external_authorization_recorded"
        ),
        limitations=[
            "external operator authorization intake only",
            "recorded authorization is not execution and does not prove delivery or cutover",
            "does not call providers, resolve credentials, deploy writers, send transport, verify delivery, control Pi hardware, rerun dossiers, or mutate runtime safety truth",
        ],
    )


def _external_authorization_row_from_packet_row(
    packet_row: ProductionSafetyQualificationExternalActionRow,
    submission: ProductionSafetyQualificationExternalAuthorizationSubmission | None,
    reference_time: datetime,
) -> ProductionSafetyQualificationExternalAuthorizationRow:
    row_base: dict[str, Any] = {
        "gap_kind": packet_row.gap_kind,
        "action": packet_row.action,
        "external_action_kind": packet_row.external_action_kind,
        "area": packet_row.area,
        "threat_id": packet_row.threat_id,
        "mode_id": packet_row.mode_id,
    }
    if not packet_row.ready_for_operator_authorization:
        return ProductionSafetyQualificationExternalAuthorizationRow(
            **row_base,
            status="blocked_packet_incomplete",
            blockers=packet_row.blockers or ["external_action_packet_row_blocked"],
        )
    if submission is None:
        return ProductionSafetyQualificationExternalAuthorizationRow(
            **row_base,
            status="missing_authorization",
            blockers=["external_authorization_submission_missing"],
        )
    blockers = _external_authorization_blockers(packet_row, submission)
    status: ProductionSafetyQualificationExternalAuthorizationRowStatus
    if not submission.authorized:
        status = "rejected_authorization"
        blockers.append("external_authorization_not_granted")
    elif blockers:
        status = "mismatched_authorization"
    elif (
        submission.expires_at is not None
        and _as_utc(submission.expires_at) <= _as_utc(reference_time)
    ):
        status = "expired_authorization"
        blockers.append("external_authorization_expired")
    else:
        status = "authorization_recorded"
    return ProductionSafetyQualificationExternalAuthorizationRow(
        **row_base,
        status=status,
        operator_authorization_recorded=status == "authorization_recorded",
        ready_for_separate_executor_invocation=status == "authorization_recorded",
        operator_identity_ref=submission.operator_identity_ref,
        operator_identity_sha256=submission.operator_identity_sha256,
        authorization_ref=submission.authorization_ref,
        authorization_sha256=submission.authorization_sha256,
        reviewed_effect_boundary_ref=submission.reviewed_effect_boundary_ref,
        reviewed_effect_boundary_sha256=submission.reviewed_effect_boundary_sha256,
        idempotency_key=submission.idempotency_key,
        authorization_observed_at=submission.authorization_observed_at,
        expires_at=submission.expires_at,
        blockers=blockers,
    )


def _external_authorization_blockers(
    packet_row: ProductionSafetyQualificationExternalActionRow,
    submission: ProductionSafetyQualificationExternalAuthorizationSubmission,
) -> list[str]:
    blockers: list[str] = []
    if submission.external_action_kind != packet_row.external_action_kind:
        blockers.append("external_action_kind_mismatch")
    if submission.area != packet_row.area:
        blockers.append("area_mismatch")
    if submission.threat_id != packet_row.threat_id:
        blockers.append("threat_id_mismatch")
    if submission.mode_id != packet_row.mode_id:
        blockers.append("mode_id_mismatch")
    for field_name in (
        "operator_identity_ref",
        "operator_identity_sha256",
        "authorization_ref",
        "authorization_sha256",
        "reviewed_effect_boundary_ref",
        "reviewed_effect_boundary_sha256",
        "idempotency_key",
        "authorization_observed_at",
        "expires_at",
    ):
        if getattr(submission, field_name) in {None, ""}:
            blockers.append(f"{field_name}_missing")
    return blockers


def _external_authorization_key(
    row: ProductionSafetyQualificationExternalActionRow
    | ProductionSafetyQualificationExternalAuthorizationSubmission,
) -> str:
    return "|".join(
        [
            row.gap_kind,
            row.action,
            row.area or "",
            row.threat_id or "",
            row.mode_id or "",
        ]
    )


def _external_authorization_manifest_sha256(
    manifest: ProductionSafetyQualificationExternalAuthorizationManifest,
) -> str:
    return aggregate_sha256([manifest.model_dump(mode="json")])


def evaluate_production_safety_qualification_external_invocation(
    external_authorization_report: ProductionSafetyQualificationExternalAuthorizationReport
    | dict[str, Any]
    | Path
    | str,
    invocation_manifest: ProductionSafetyQualificationExternalInvocationManifest
    | dict[str, Any]
    | Path
    | str,
    *,
    source_path: str | None = None,
) -> ProductionSafetyQualificationExternalInvocationReport:
    authorization = _load_or_validate_external_authorization_report(
        external_authorization_report
    )
    manifest = _load_or_validate_external_invocation_manifest(invocation_manifest)
    if manifest.external_authorization_report_ref != authorization.source_path:
        raise ValueError(
            "external invocation manifest authorization ref must match report"
        )
    if manifest.external_authorization_report_sha256 != authorization.sha256:
        raise ValueError(
            "external invocation manifest authorization sha256 must match report"
        )
    requests_by_key = {
        _external_invocation_key(request): request
        for request in manifest.requests
    }
    rows = [
        _external_invocation_row_from_authorization_row(
            row,
            requests_by_key.get(_external_invocation_key(row)),
        )
        for row in authorization.rows
    ]
    if not rows and authorization.status == "no_external_authorization_required":
        status: ProductionSafetyQualificationExternalInvocationReportStatus = (
            "no_external_invocation_required"
        )
    elif rows and all(row.invocation_handoff_recorded for row in rows):
        status = "external_invocation_handoff_recorded"
    else:
        status = "blocked_external_invocation_incomplete"
    report_source_path = source_path or f"{manifest.source_path}/report"
    manifest_sha = _external_invocation_manifest_sha256(manifest)
    digest = aggregate_sha256(
        [
            {
                "source_path": report_source_path,
                "external_authorization_report_ref": authorization.source_path,
                "external_authorization_report_sha256": authorization.sha256,
                "invocation_manifest_ref": manifest.source_path,
                "invocation_manifest_sha256": manifest_sha,
                "row_statuses": [
                    {
                        "gap_kind": row.gap_kind,
                        "area": row.area,
                        "threat_id": row.threat_id,
                        "mode_id": row.mode_id,
                        "external_action_kind": row.external_action_kind,
                        "status": row.status,
                    }
                    for row in rows
                ],
                "status": status,
            }
        ]
    )
    return ProductionSafetyQualificationExternalInvocationReport(
        source_path=report_source_path,
        sha256=digest,
        status=status,
        external_authorization_report_ref=authorization.source_path,
        external_authorization_report_sha256=authorization.sha256,
        invocation_manifest_ref=manifest.source_path,
        invocation_manifest_sha256=manifest_sha,
        external_action_packet_ref=authorization.external_action_packet_ref,
        external_action_packet_sha256=authorization.external_action_packet_sha256,
        remediation_report_ref=authorization.remediation_report_ref,
        remediation_report_sha256=authorization.remediation_report_sha256,
        rows=rows,
        invocation_handoff_count=len(
            [row for row in rows if row.invocation_handoff_recorded]
        ),
        blocked_invocation_count=len(
            [row for row in rows if not row.invocation_handoff_recorded]
        ),
        all_invocation_handoffs_recorded=(
            status
            in {
                "no_external_invocation_required",
                "external_invocation_handoff_recorded",
            }
        ),
        ready_for_separate_executor_handoff=(
            status == "external_invocation_handoff_recorded"
        ),
        limitations=[
            "external executor invocation guard only",
            "recorded handoff is not execution and does not prove provider response, delivery, deployment, Pi hardware validation, dossier rerun, or cutover",
            "does not call providers, resolve credentials, deploy writers, send transport, verify delivery, control Pi hardware, rerun dossiers, or mutate runtime safety truth",
        ],
    )


def _external_invocation_row_from_authorization_row(
    authorization_row: ProductionSafetyQualificationExternalAuthorizationRow,
    request: ProductionSafetyQualificationExternalInvocationRequest | None,
) -> ProductionSafetyQualificationExternalInvocationRow:
    row_base: dict[str, Any] = {
        "gap_kind": authorization_row.gap_kind,
        "action": authorization_row.action,
        "external_action_kind": authorization_row.external_action_kind,
        "area": authorization_row.area,
        "threat_id": authorization_row.threat_id,
        "mode_id": authorization_row.mode_id,
        "operator_identity_ref": authorization_row.operator_identity_ref,
        "operator_identity_sha256": authorization_row.operator_identity_sha256,
        "authorization_ref": authorization_row.authorization_ref,
        "authorization_sha256": authorization_row.authorization_sha256,
        "reviewed_effect_boundary_ref": (
            authorization_row.reviewed_effect_boundary_ref
        ),
        "reviewed_effect_boundary_sha256": (
            authorization_row.reviewed_effect_boundary_sha256
        ),
        "authorization_idempotency_key": authorization_row.idempotency_key,
    }
    if not authorization_row.ready_for_separate_executor_invocation:
        return ProductionSafetyQualificationExternalInvocationRow(
            **row_base,
            status="blocked_authorization_incomplete",
            blockers=authorization_row.blockers
            or ["external_authorization_row_blocked"],
        )
    if request is None:
        return ProductionSafetyQualificationExternalInvocationRow(
            **row_base,
            status="missing_invocation_request",
            blockers=["external_invocation_request_missing"],
        )
    blockers = _external_invocation_blockers(authorization_row, request)
    if not request.invocation_requested:
        status: ProductionSafetyQualificationExternalInvocationRowStatus = (
            "rejected_invocation_request"
        )
        blockers.append("external_invocation_not_requested")
    elif not request.operator_confirmation:
        status = "missing_operator_confirmation"
        blockers.append("external_invocation_operator_confirmation_missing")
    elif blockers:
        status = "mismatched_invocation_request"
    else:
        status = "invocation_handoff_recorded"
    return ProductionSafetyQualificationExternalInvocationRow(
        **row_base,
        status=status,
        invocation_handoff_recorded=status == "invocation_handoff_recorded",
        ready_for_separate_executor_handoff=(
            status == "invocation_handoff_recorded"
        ),
        external_executor_ref=request.external_executor_ref,
        external_executor_sha256=request.external_executor_sha256,
        executor_invocation_ref=request.executor_invocation_ref,
        executor_invocation_sha256=request.executor_invocation_sha256,
        invocation_idempotency_key=request.invocation_idempotency_key,
        requested_at=request.requested_at,
        blockers=blockers,
    )


def _external_invocation_blockers(
    authorization_row: ProductionSafetyQualificationExternalAuthorizationRow,
    request: ProductionSafetyQualificationExternalInvocationRequest,
) -> list[str]:
    blockers: list[str] = []
    if request.external_action_kind != authorization_row.external_action_kind:
        blockers.append("external_action_kind_mismatch")
    if request.area != authorization_row.area:
        blockers.append("area_mismatch")
    if request.threat_id != authorization_row.threat_id:
        blockers.append("threat_id_mismatch")
    if request.mode_id != authorization_row.mode_id:
        blockers.append("mode_id_mismatch")
    for field_name in (
        "operator_identity_ref",
        "operator_identity_sha256",
        "authorization_ref",
        "authorization_sha256",
        "reviewed_effect_boundary_ref",
        "reviewed_effect_boundary_sha256",
    ):
        if getattr(request, field_name) != getattr(authorization_row, field_name):
            blockers.append(f"{field_name}_mismatch")
    if request.authorization_idempotency_key != authorization_row.idempotency_key:
        blockers.append("authorization_idempotency_key_mismatch")
    for field_name in (
        "external_executor_ref",
        "external_executor_sha256",
        "executor_invocation_ref",
        "executor_invocation_sha256",
        "invocation_idempotency_key",
        "requested_at",
    ):
        if getattr(request, field_name) in {None, ""}:
            blockers.append(f"{field_name}_missing")
    return blockers


def _external_invocation_key(
    row: ProductionSafetyQualificationExternalAuthorizationRow
    | ProductionSafetyQualificationExternalInvocationRequest,
) -> str:
    return "|".join(
        [
            row.gap_kind,
            row.action,
            row.area or "",
            row.threat_id or "",
            row.mode_id or "",
        ]
    )


def _external_invocation_manifest_sha256(
    manifest: ProductionSafetyQualificationExternalInvocationManifest,
) -> str:
    return aggregate_sha256([manifest.model_dump(mode="json")])


def evaluate_production_safety_qualification_external_result_intake(
    external_invocation_report: ProductionSafetyQualificationExternalInvocationReport
    | dict[str, Any]
    | Path
    | str,
    result_manifest: ProductionSafetyQualificationExternalResultManifest
    | dict[str, Any]
    | Path
    | str,
    *,
    source_path: str | None = None,
) -> ProductionSafetyQualificationExternalResultReport:
    invocation = _load_or_validate_external_invocation_report(
        external_invocation_report
    )
    manifest = _load_or_validate_external_result_manifest(result_manifest)
    if manifest.external_invocation_report_ref != invocation.source_path:
        raise ValueError("external result manifest invocation ref must match report")
    if manifest.external_invocation_report_sha256 != invocation.sha256:
        raise ValueError("external result manifest invocation sha256 must match report")
    receipts_by_key = {
        _external_result_key(receipt): receipt
        for receipt in manifest.receipts
    }
    rows = [
        _external_result_row_from_invocation_row(
            row,
            receipts_by_key.get(_external_result_key(row)),
        )
        for row in invocation.rows
    ]
    if not rows and invocation.status == "no_external_invocation_required":
        status: ProductionSafetyQualificationExternalResultReportStatus = (
            "no_external_result_required"
        )
    elif rows and all(row.result_receipt_recorded for row in rows):
        status = "external_results_recorded"
    else:
        status = "blocked_external_results_incomplete"
    report_source_path = source_path or f"{manifest.source_path}/report"
    manifest_sha = _external_result_manifest_sha256(manifest)
    digest = aggregate_sha256(
        [
            {
                "source_path": report_source_path,
                "external_invocation_report_ref": invocation.source_path,
                "external_invocation_report_sha256": invocation.sha256,
                "result_manifest_ref": manifest.source_path,
                "result_manifest_sha256": manifest_sha,
                "row_statuses": [
                    {
                        "gap_kind": row.gap_kind,
                        "area": row.area,
                        "threat_id": row.threat_id,
                        "mode_id": row.mode_id,
                        "external_action_kind": row.external_action_kind,
                        "status": row.status,
                    }
                    for row in rows
                ],
                "status": status,
            }
        ]
    )
    return ProductionSafetyQualificationExternalResultReport(
        source_path=report_source_path,
        sha256=digest,
        status=status,
        external_invocation_report_ref=invocation.source_path,
        external_invocation_report_sha256=invocation.sha256,
        result_manifest_ref=manifest.source_path,
        result_manifest_sha256=manifest_sha,
        external_authorization_report_ref=invocation.external_authorization_report_ref,
        external_authorization_report_sha256=(
            invocation.external_authorization_report_sha256
        ),
        external_action_packet_ref=invocation.external_action_packet_ref,
        external_action_packet_sha256=invocation.external_action_packet_sha256,
        remediation_report_ref=invocation.remediation_report_ref,
        remediation_report_sha256=invocation.remediation_report_sha256,
        rows=rows,
        result_receipt_count=len(
            [row for row in rows if row.result_receipt_recorded]
        ),
        blocked_result_count=len(
            [row for row in rows if not row.result_receipt_recorded]
        ),
        all_result_receipts_recorded=(
            status in {"no_external_result_required", "external_results_recorded"}
        ),
        ready_for_evidence_fulfillment=status == "external_results_recorded",
        limitations=[
            "external result receipt intake only",
            "recorded result receipts are inputs for future evidence fulfillment, not cutover proof",
            "does not call providers, resolve credentials, deploy writers, send transport, verify delivery, control Pi hardware, rerun dossiers, or mutate runtime safety truth",
        ],
    )


def build_production_safety_qualification_evidence_fulfillment_manifest_from_external_results(
    request_pack: ProductionSafetyQualificationEvidenceRequestPack
    | dict[str, Any]
    | Path
    | str,
    external_result_report: ProductionSafetyQualificationExternalResultReport
    | dict[str, Any]
    | Path
    | str,
    *,
    source_path: str | None = None,
) -> ProductionSafetyQualificationExternalResultEvidenceBridgeReport:
    pack = _load_or_validate_evidence_request_pack(request_pack)
    result = _load_or_validate_external_result_report(external_result_report)
    result_rows_by_key = {
        _external_result_bridge_key_from_result_row(row): row
        for row in result.rows
    }
    rows: list[ProductionSafetyQualificationExternalResultEvidenceBridgeRow] = []
    submissions: list[ProductionSafetyQualificationEvidenceSubmission] = []
    for request in pack.rows:
        row, submission = _external_result_bridge_row_from_request(
            request,
            result_rows_by_key.get(_external_result_bridge_key_from_request(request)),
        )
        rows.append(row)
        if submission is not None:
            submissions.append(submission)
    if (
        not rows
        and pack.status == "no_evidence_requests_required"
        and result.status == "no_external_result_required"
    ):
        status: ProductionSafetyQualificationExternalResultEvidenceBridgeStatus = (
            "no_external_result_bridge_required"
        )
    elif rows and all(row.bridged_to_fulfillment_submission for row in rows):
        status = "external_result_bridge_ready"
    else:
        status = "blocked_external_result_bridge_incomplete"
    report_source_path = (
        source_path or f"{result.source_path}/evidence-fulfillment-bridge"
    )
    fulfillment_manifest: (
        ProductionSafetyQualificationEvidenceFulfillmentManifest | None
    ) = None
    fulfillment_manifest_sha256: str | None = None
    if status == "external_result_bridge_ready":
        fulfillment_manifest = ProductionSafetyQualificationEvidenceFulfillmentManifest(
            source_path=f"{report_source_path}/fulfillment-manifest",
            request_pack_ref=pack.source_path,
            request_pack_sha256=pack.sha256,
            submissions=submissions,
        )
        fulfillment_manifest_sha256 = _qualification_fulfillment_manifest_sha256(
            fulfillment_manifest
        )
    result_sha = result.sha256 or aggregate_sha256([result.model_dump(mode="json")])
    digest = aggregate_sha256(
        [
            {
                "source_path": report_source_path,
                "request_pack_ref": pack.source_path,
                "request_pack_sha256": pack.sha256,
                "external_result_report_ref": result.source_path,
                "external_result_report_sha256": result_sha,
                "fulfillment_manifest_sha256": fulfillment_manifest_sha256,
                "row_statuses": [
                    {
                        "request_kind": row.request_kind,
                        "source_gap_kind": row.source_gap_kind,
                        "action": row.action,
                        "area": row.area,
                        "threat_id": row.threat_id,
                        "mode_id": row.mode_id,
                        "status": row.status,
                    }
                    for row in rows
                ],
                "status": status,
            }
        ]
    )
    return ProductionSafetyQualificationExternalResultEvidenceBridgeReport(
        source_path=report_source_path,
        sha256=digest,
        status=status,
        request_pack_ref=pack.source_path,
        request_pack_sha256=pack.sha256,
        external_result_report_ref=result.source_path,
        external_result_report_sha256=result_sha,
        fulfillment_manifest=fulfillment_manifest,
        fulfillment_manifest_sha256=fulfillment_manifest_sha256,
        rows=rows,
        bridged_request_count=len(
            [row for row in rows if row.bridged_to_fulfillment_submission]
        ),
        blocked_request_count=len(
            [row for row in rows if not row.bridged_to_fulfillment_submission]
        ),
        ready_for_fulfillment_intake=status == "external_result_bridge_ready",
        limitations=[
            "external result evidence bridge only",
            "bridged artifacts are emitted as evidence fulfillment submissions and still require the fulfillment source-integrity gate",
            "does not call providers, resolve credentials, deploy writers, send transport, verify delivery, control hardware, rerun dossiers, or mutate runtime safety truth",
        ],
    )


def evaluate_production_safety_qualification_external_result_remediation_closure(
    gap_plan: ProductionSafetyQualificationGapPlan | dict[str, Any] | Path | str,
    request_pack: ProductionSafetyQualificationEvidenceRequestPack
    | dict[str, Any]
    | Path
    | str,
    external_result_bridge_report: (
        ProductionSafetyQualificationExternalResultEvidenceBridgeReport
        | dict[str, Any]
        | Path
        | str
    ),
    source_package: (
        ProductionSafetyQualificationEvidenceFulfillmentSourcePackage
        | dict[str, Any]
        | Path
        | str
        | None
    ) = None,
    *,
    root_path: Path | str | None = None,
    source_path: str | None = None,
) -> ProductionSafetyQualificationExternalResultRemediationClosureReport:
    plan = _load_or_validate_gap_plan(gap_plan)
    pack = _load_or_validate_evidence_request_pack(request_pack)
    bridge = _load_or_validate_external_result_evidence_bridge_report(
        external_result_bridge_report
    )
    if pack.gap_plan_ref != plan.source_path:
        raise ValueError("request pack gap_plan_ref must match gap plan")
    if pack.gap_plan_sha256 != plan.sha256:
        raise ValueError("request pack gap_plan_sha256 must match gap plan")
    if bridge.request_pack_ref != pack.source_path:
        raise ValueError("external result bridge request_pack_ref must match pack")
    if bridge.request_pack_sha256 != pack.sha256:
        raise ValueError("external result bridge request_pack_sha256 must match pack")
    report_source_path = (
        source_path or f"{bridge.source_path}/remediation-closure"
    )
    package = (
        _load_or_validate_evidence_fulfillment_source_package(source_package)
        if source_package is not None
        else None
    )
    source_package_sha = (
        _qualification_fulfillment_source_package_sha256(package)
        if package is not None
        else None
    )
    source_report: (
        ProductionSafetyQualificationEvidenceFulfillmentSourceIntegrityReport | None
    ) = None
    fulfillment_report: ProductionSafetyQualificationEvidenceFulfillmentReport | None = (
        None
    )
    remediation_report: ProductionSafetyQualificationRemediationReadinessReport | None = (
        None
    )
    if bridge.status == "no_external_result_bridge_required":
        status: ProductionSafetyQualificationExternalResultRemediationClosureStatus = (
            "no_external_result_remediation_required"
        )
    elif bridge.status != "external_result_bridge_ready":
        status = "blocked_external_result_bridge_incomplete"
    elif bridge.fulfillment_manifest is None:
        status = "blocked_external_result_bridge_incomplete"
    elif package is None:
        status = "blocked_external_result_source_package_missing"
    else:
        source_report = (
            verify_production_safety_qualification_evidence_fulfillment_source_integrity(
                bridge.fulfillment_manifest,
                package,
                root_path=root_path,
                source_path=f"{report_source_path}/source-integrity",
            )
        )
        fulfillment_report = evaluate_production_safety_qualification_evidence_fulfillment(
            pack,
            bridge.fulfillment_manifest,
            source_integrity_report=source_report,
            source_path=f"{report_source_path}/fulfillment",
        )
        remediation_report = (
            evaluate_production_safety_qualification_remediation_readiness(
                plan,
                pack,
                fulfillment_report,
                source_path=f"{report_source_path}/remediation",
            )
        )
        if not source_report.all_fulfillment_sources_verified:
            status = "blocked_external_result_source_integrity_failed"
        elif not fulfillment_report.all_requested_evidence_fulfilled:
            status = "blocked_external_result_fulfillment_incomplete"
        elif not remediation_report.ready_for_dossier_rerun:
            status = "blocked_external_result_remediation_incomplete"
        else:
            status = "external_result_remediation_ready_for_dossier_rerun"
    digest = aggregate_sha256(
        [
            {
                "source_path": report_source_path,
                "gap_plan_ref": plan.source_path,
                "gap_plan_sha256": plan.sha256,
                "request_pack_ref": pack.source_path,
                "request_pack_sha256": pack.sha256,
                "external_result_bridge_ref": bridge.source_path,
                "external_result_bridge_sha256": bridge.sha256,
                "source_package_ref": package.source_path if package else None,
                "source_package_sha256": source_package_sha,
                "source_integrity_status": (
                    source_report.status if source_report else None
                ),
                "fulfillment_status": (
                    fulfillment_report.status if fulfillment_report else None
                ),
                "remediation_status": (
                    remediation_report.status if remediation_report else None
                ),
                "status": status,
            }
        ]
    )
    return ProductionSafetyQualificationExternalResultRemediationClosureReport(
        source_path=report_source_path,
        sha256=digest,
        status=status,
        gap_plan_ref=plan.source_path,
        gap_plan_sha256=plan.sha256,
        request_pack_ref=pack.source_path,
        request_pack_sha256=pack.sha256,
        external_result_bridge_ref=bridge.source_path,
        external_result_bridge_sha256=bridge.sha256,
        source_package_ref=package.source_path if package else None,
        source_package_sha256=source_package_sha,
        bridge_report=bridge,
        source_integrity_report=source_report,
        fulfillment_report=fulfillment_report,
        remediation_report=remediation_report,
        ready_for_dossier_rerun=(
            status == "external_result_remediation_ready_for_dossier_rerun"
        ),
        limitations=[
            "external result remediation closure only",
            "ready_for_dossier_rerun is not production cutover readiness",
            "does not apply evidence, rerun the dossier, call providers, mutate runtime safety truth, send transport, verify delivery, or control hardware",
        ],
    )


def evaluate_production_safety_qualification_dossier_rerun_intake(
    external_result_closure_report: (
        ProductionSafetyQualificationExternalResultRemediationClosureReport
        | dict[str, Any]
        | Path
        | str
    ),
    dossier_manifest: (
        ProductionSafetyQualificationDossierManifest | dict[str, Any] | Path | str
    ),
    *,
    evaluation_time: datetime | None = None,
    cutover_audit_output_path: Path | str | None = None,
    threat_coverage_output_path: Path | str | None = None,
    source_integrity_output_dir: Path | str | None = None,
    admission_output_dir: Path | str | None = None,
    receipt_output_dir: Path | str | None = None,
    source_path: str | None = None,
) -> ProductionSafetyQualificationDossierRerunReport:
    closure = _load_or_validate_external_result_remediation_closure_report(
        external_result_closure_report
    )
    manifest = _load_or_validate_dossier_manifest(dossier_manifest)
    manifest_sha = _qualification_dossier_manifest_sha256(manifest)
    report_source_path = source_path or f"{closure.source_path}/dossier-rerun"
    dossier_report: ProductionSafetyQualificationDossierReport | None = None
    if closure.status == "no_external_result_remediation_required":
        status: ProductionSafetyQualificationDossierRerunStatus = (
            "no_dossier_rerun_required"
        )
    elif not closure.ready_for_dossier_rerun:
        status = "blocked_external_result_remediation_incomplete"
    else:
        dossier_report = run_production_safety_qualification_dossier(
            manifest,
            evaluation_time=evaluation_time,
            cutover_audit_output_path=cutover_audit_output_path,
            threat_coverage_output_path=threat_coverage_output_path,
            source_integrity_output_dir=source_integrity_output_dir,
            admission_output_dir=admission_output_dir,
            receipt_output_dir=receipt_output_dir,
            source_path=f"{report_source_path}/dossier-report",
        )
        if dossier_report.status == "dossier_ready_for_production_cutover":
            status = "dossier_rerun_ready_for_cutover_review"
        elif dossier_report.status == "blocked_dossier_incomplete":
            status = "blocked_dossier_rerun_incomplete"
        else:
            status = "blocked_dossier_rerun_failed"
    digest = aggregate_sha256(
        [
            {
                "source_path": report_source_path,
                "external_result_closure_ref": closure.source_path,
                "external_result_closure_sha256": closure.sha256,
                "dossier_manifest_ref": manifest.source_path,
                "dossier_manifest_sha256": manifest_sha,
                "dossier_report_ref": (
                    dossier_report.source_path if dossier_report else None
                ),
                "dossier_report_sha256": (
                    dossier_report.sha256 if dossier_report else None
                ),
                "dossier_status": dossier_report.status if dossier_report else None,
                "status": status,
            }
        ]
    )
    return ProductionSafetyQualificationDossierRerunReport(
        source_path=report_source_path,
        sha256=digest,
        status=status,
        external_result_closure_ref=closure.source_path,
        external_result_closure_sha256=closure.sha256,
        dossier_manifest_ref=manifest.source_path,
        dossier_manifest_sha256=manifest_sha,
        dossier_report_ref=dossier_report.source_path if dossier_report else None,
        dossier_report_sha256=dossier_report.sha256 if dossier_report else None,
        closure_report=closure,
        dossier_report=dossier_report,
        dossier_status=dossier_report.status if dossier_report else None,
        cutover_audit_status=(
            dossier_report.cutover_audit.status if dossier_report else None
        ),
        threat_coverage_status=(
            dossier_report.threat_coverage_status if dossier_report else None
        ),
        local_dossier_validator_executed=dossier_report is not None,
        dossier_report_ready_for_cutover=bool(
            dossier_report and dossier_report.ready_for_production_cutover
        ),
        limitations=[
            "dossier rerun intake is local qualification evidence only",
            "dossier_report_ready_for_cutover is not production cutover readiness",
            "does not call providers, resolve credentials, deploy writers, send transport, verify delivery, control hardware, invoke executors, or mutate runtime safety truth",
        ],
    )


def evaluate_production_safety_qualification_cutover_authorization(
    dossier_rerun_report: ProductionSafetyQualificationDossierRerunReport
    | dict[str, Any]
    | Path
    | str,
    authorization_manifest: (
        ProductionSafetyQualificationCutoverAuthorizationManifest
        | dict[str, Any]
        | Path
        | str
    ),
    *,
    source_path: str | None = None,
) -> ProductionSafetyQualificationCutoverAuthorizationReport:
    rerun = _load_or_validate_dossier_rerun_report(dossier_rerun_report)
    manifest = _load_or_validate_cutover_authorization_manifest(
        authorization_manifest
    )
    if manifest.dossier_rerun_ref != rerun.source_path:
        raise ValueError("cutover authorization manifest rerun ref must match report")
    if manifest.dossier_rerun_sha256 != rerun.sha256:
        raise ValueError("cutover authorization manifest rerun sha256 must match report")
    report_source_path = source_path or f"{manifest.source_path}/report"
    manifest_sha = _cutover_authorization_manifest_sha256(manifest)
    blockers = _cutover_authorization_blockers(rerun, manifest)
    if (
        rerun.status != "dossier_rerun_ready_for_cutover_review"
        or not rerun.dossier_report_ready_for_cutover
    ):
        status: ProductionSafetyQualificationCutoverAuthorizationStatus = (
            "blocked_dossier_rerun_not_ready"
        )
    elif not manifest.authorized:
        status = "rejected_cutover_authorization"
    elif any(blocker.endswith("_missing") for blocker in blockers):
        status = "missing_cutover_authorization"
    elif "explicit_confirmation_phrase_mismatch" in blockers:
        status = "mismatched_cutover_authorization"
    elif (
        manifest.expires_at is not None
        and _as_utc(manifest.expires_at) <= _as_utc(manifest.reference_time)
    ):
        blockers.append("cutover_authorization_expired")
        status = "expired_cutover_authorization"
    elif blockers:
        status = "mismatched_cutover_authorization"
    else:
        status = "cutover_authorization_recorded"
    dossier_report = rerun.dossier_report
    digest = aggregate_sha256(
        [
            {
                "source_path": report_source_path,
                "dossier_rerun_ref": rerun.source_path,
                "dossier_rerun_sha256": rerun.sha256,
                "authorization_manifest_ref": manifest.source_path,
                "authorization_manifest_sha256": manifest_sha,
                "dossier_report_ref": (
                    dossier_report.source_path if dossier_report else None
                ),
                "dossier_status": dossier_report.status if dossier_report else None,
                "authorization_ref": manifest.authorization_ref,
                "authorization_sha256": manifest.authorization_sha256,
                "operator_identity_ref": manifest.operator_identity_ref,
                "status": status,
                "blockers": blockers,
            }
        ]
    )
    return ProductionSafetyQualificationCutoverAuthorizationReport(
        source_path=report_source_path,
        sha256=digest,
        status=status,
        dossier_rerun_ref=rerun.source_path,
        dossier_rerun_sha256=rerun.sha256,
        authorization_manifest_ref=manifest.source_path,
        authorization_manifest_sha256=manifest_sha,
        dossier_report_ref=dossier_report.source_path if dossier_report else None,
        dossier_report_sha256=dossier_report.sha256 if dossier_report else None,
        dossier_status=dossier_report.status if dossier_report else None,
        cutover_audit_status=(
            dossier_report.cutover_audit.status if dossier_report else None
        ),
        threat_coverage_status=(
            dossier_report.threat_coverage_status if dossier_report else None
        ),
        operator_identity_ref=manifest.operator_identity_ref,
        operator_identity_sha256=manifest.operator_identity_sha256,
        authorization_ref=manifest.authorization_ref,
        authorization_sha256=manifest.authorization_sha256,
        reviewed_effect_boundary_ref=manifest.reviewed_effect_boundary_ref,
        reviewed_effect_boundary_sha256=manifest.reviewed_effect_boundary_sha256,
        rollback_plan_ref=manifest.rollback_plan_ref,
        rollback_plan_sha256=manifest.rollback_plan_sha256,
        production_change_request_ref=manifest.production_change_request_ref,
        production_change_request_sha256=manifest.production_change_request_sha256,
        idempotency_key=manifest.idempotency_key,
        authorization_observed_at=manifest.authorization_observed_at,
        expires_at=manifest.expires_at,
        explicit_confirmation_phrase=manifest.explicit_confirmation_phrase,
        cutover_authorization_recorded=(
            status == "cutover_authorization_recorded"
        ),
        ready_for_human_cutover_review=status == "cutover_authorization_recorded",
        blockers=blockers,
        dossier_rerun_report=rerun,
        authorization_manifest=manifest,
        limitations=[
            "cutover authorization intake records human review evidence only",
            "recorded authorization is not production cutover execution",
            "does not call providers, resolve credentials, deploy writers, send transport, verify delivery, control hardware, invoke executors, or mutate runtime safety truth",
        ],
    )


def _cutover_authorization_blockers(
    rerun: ProductionSafetyQualificationDossierRerunReport,
    manifest: ProductionSafetyQualificationCutoverAuthorizationManifest,
) -> list[str]:
    blockers: list[str] = []
    if (
        rerun.status != "dossier_rerun_ready_for_cutover_review"
        or not rerun.dossier_report_ready_for_cutover
    ):
        blockers.append("dossier_rerun_not_ready_for_cutover_review")
    if not manifest.authorized:
        blockers.append("cutover_authorization_not_granted")
    for field_name in (
        "operator_identity_ref",
        "operator_identity_sha256",
        "authorization_ref",
        "authorization_sha256",
        "reviewed_effect_boundary_ref",
        "reviewed_effect_boundary_sha256",
        "rollback_plan_ref",
        "rollback_plan_sha256",
        "production_change_request_ref",
        "production_change_request_sha256",
        "idempotency_key",
        "authorization_observed_at",
        "expires_at",
    ):
        if getattr(manifest, field_name) in {None, ""}:
            blockers.append(f"{field_name}_missing")
    if (
        manifest.explicit_confirmation_phrase
        != PRODUCTION_SAFETY_CUTOVER_REVIEW_CONFIRMATION
    ):
        blockers.append("explicit_confirmation_phrase_mismatch")
    return blockers


def evaluate_production_safety_qualification_cutover_release_handoff(
    cutover_authorization_report: (
        ProductionSafetyQualificationCutoverAuthorizationReport
        | dict[str, Any]
        | Path
        | str
    ),
    handoff_manifest: (
        ProductionSafetyQualificationCutoverReleaseHandoffManifest
        | dict[str, Any]
        | Path
        | str
    ),
    *,
    source_path: str | None = None,
) -> ProductionSafetyQualificationCutoverReleaseHandoffReport:
    authorization = _load_or_validate_cutover_authorization_report(
        cutover_authorization_report
    )
    manifest = _load_or_validate_cutover_release_handoff_manifest(
        handoff_manifest
    )
    if manifest.cutover_authorization_report_ref != authorization.source_path:
        raise ValueError("handoff manifest authorization ref must match report")
    if manifest.cutover_authorization_report_sha256 != authorization.sha256:
        raise ValueError("handoff manifest authorization sha256 must match report")
    report_source_path = source_path or f"{manifest.source_path}/report"
    manifest_sha = _cutover_release_handoff_manifest_sha256(manifest)
    request = manifest.request
    blockers = _cutover_release_handoff_blockers(
        authorization,
        request,
        manifest.reference_time,
    )
    if (
        authorization.status != "cutover_authorization_recorded"
        or not authorization.ready_for_human_cutover_review
    ):
        status: ProductionSafetyQualificationCutoverReleaseHandoffStatus = (
            "blocked_cutover_authorization_incomplete"
        )
    elif request is None:
        status = "missing_cutover_release_request"
    elif not request.release_handoff_requested:
        status = "rejected_cutover_release_request"
    elif not request.operator_confirmation:
        status = "missing_operator_confirmation"
    elif any(blocker.endswith("_missing") for blocker in blockers):
        status = "missing_cutover_release_request"
    elif blockers:
        status = "mismatched_cutover_release_request"
    else:
        status = "cutover_release_handoff_recorded"
    rerun = authorization.dossier_rerun_report
    digest = aggregate_sha256(
        [
            {
                "source_path": report_source_path,
                "cutover_authorization_report_ref": authorization.source_path,
                "cutover_authorization_report_sha256": authorization.sha256,
                "handoff_manifest_ref": manifest.source_path,
                "handoff_manifest_sha256": manifest_sha,
                "dossier_rerun_ref": rerun.source_path,
                "dossier_rerun_sha256": rerun.sha256,
                "dossier_report_ref": (
                    rerun.dossier_report.source_path if rerun.dossier_report else None
                ),
                "dossier_report_sha256": (
                    rerun.dossier_report.sha256 if rerun.dossier_report else None
                ),
                "release_executor_ref": (
                    request.release_executor_ref if request else None
                ),
                "release_invocation_ref": (
                    request.release_invocation_ref if request else None
                ),
                "status": status,
                "blockers": blockers,
            }
        ]
    )
    return ProductionSafetyQualificationCutoverReleaseHandoffReport(
        source_path=report_source_path,
        sha256=digest,
        status=status,
        cutover_authorization_report_ref=authorization.source_path,
        cutover_authorization_report_sha256=authorization.sha256,
        handoff_manifest_ref=manifest.source_path,
        handoff_manifest_sha256=manifest_sha,
        dossier_rerun_ref=rerun.source_path,
        dossier_rerun_sha256=rerun.sha256,
        dossier_report_ref=(
            rerun.dossier_report.source_path if rerun.dossier_report else None
        ),
        dossier_report_sha256=(
            rerun.dossier_report.sha256 if rerun.dossier_report else None
        ),
        release_executor_ref=request.release_executor_ref if request else None,
        release_executor_sha256=request.release_executor_sha256 if request else None,
        release_invocation_ref=request.release_invocation_ref if request else None,
        release_invocation_sha256=(
            request.release_invocation_sha256 if request else None
        ),
        operator_identity_ref=request.operator_identity_ref if request else None,
        operator_identity_sha256=(
            request.operator_identity_sha256 if request else None
        ),
        authorization_ref=request.authorization_ref if request else None,
        authorization_sha256=request.authorization_sha256 if request else None,
        reviewed_effect_boundary_ref=(
            request.reviewed_effect_boundary_ref if request else None
        ),
        reviewed_effect_boundary_sha256=(
            request.reviewed_effect_boundary_sha256 if request else None
        ),
        rollback_plan_ref=request.rollback_plan_ref if request else None,
        rollback_plan_sha256=request.rollback_plan_sha256 if request else None,
        production_change_request_ref=(
            request.production_change_request_ref if request else None
        ),
        production_change_request_sha256=(
            request.production_change_request_sha256 if request else None
        ),
        cutover_authorization_idempotency_key=(
            request.cutover_authorization_idempotency_key if request else None
        ),
        handoff_idempotency_key=request.handoff_idempotency_key if request else None,
        requested_at=request.requested_at if request else None,
        explicit_confirmation_phrase=(
            request.explicit_confirmation_phrase if request else None
        ),
        cutover_release_handoff_recorded=(
            status == "cutover_release_handoff_recorded"
        ),
        ready_for_release_executor_handoff=(
            status == "cutover_release_handoff_recorded"
        ),
        blockers=blockers,
        cutover_authorization_report=authorization,
        handoff_manifest=manifest,
        limitations=[
            "cutover release handoff records a future executor input only",
            "recorded handoff is not production cutover execution",
            "does not call providers, resolve credentials, deploy writers, send transport, verify delivery, control hardware, invoke executors, or mutate runtime safety truth",
        ],
    )


def _cutover_release_handoff_blockers(
    authorization: ProductionSafetyQualificationCutoverAuthorizationReport,
    request: ProductionSafetyQualificationCutoverReleaseHandoffRequest | None,
    reference_time: datetime,
) -> list[str]:
    blockers: list[str] = []
    if (
        authorization.status != "cutover_authorization_recorded"
        or not authorization.ready_for_human_cutover_review
    ):
        blockers.append("cutover_authorization_not_recorded")
    if request is None:
        blockers.append("cutover_release_request_missing")
        return blockers
    if not request.release_handoff_requested:
        blockers.append("cutover_release_handoff_not_requested")
    if not request.operator_confirmation:
        blockers.append("operator_confirmation_missing")
    for field_name in (
        "operator_identity_ref",
        "operator_identity_sha256",
        "authorization_ref",
        "authorization_sha256",
        "reviewed_effect_boundary_ref",
        "reviewed_effect_boundary_sha256",
        "rollback_plan_ref",
        "rollback_plan_sha256",
        "production_change_request_ref",
        "production_change_request_sha256",
        "release_executor_ref",
        "release_executor_sha256",
        "release_invocation_ref",
        "release_invocation_sha256",
        "cutover_authorization_idempotency_key",
        "handoff_idempotency_key",
        "requested_at",
    ):
        if getattr(request, field_name) in {None, ""}:
            blockers.append(f"{field_name}_missing")
    for field_name in (
        "operator_identity_ref",
        "operator_identity_sha256",
        "authorization_ref",
        "authorization_sha256",
        "reviewed_effect_boundary_ref",
        "reviewed_effect_boundary_sha256",
        "rollback_plan_ref",
        "rollback_plan_sha256",
        "production_change_request_ref",
        "production_change_request_sha256",
    ):
        if getattr(request, field_name) != getattr(authorization, field_name):
            blockers.append(f"{field_name}_mismatch")
    if request.cutover_authorization_idempotency_key != authorization.idempotency_key:
        blockers.append("cutover_authorization_idempotency_key_mismatch")
    if (
        request.explicit_confirmation_phrase
        != PRODUCTION_SAFETY_CUTOVER_RELEASE_HANDOFF_CONFIRMATION
    ):
        blockers.append("explicit_confirmation_phrase_mismatch")
    if (
        request.requested_at is not None
        and _as_utc(request.requested_at) > _as_utc(reference_time)
    ):
        blockers.append("requested_at_after_reference_time")
    return blockers


def evaluate_production_safety_qualification_cutover_release_effect_intake(
    cutover_release_handoff_report: (
        ProductionSafetyQualificationCutoverReleaseHandoffReport
        | dict[str, Any]
        | Path
        | str
    ),
    effect_manifest: (
        ProductionSafetyQualificationCutoverReleaseEffectManifest
        | dict[str, Any]
        | Path
        | str
    ),
    *,
    source_path: str | None = None,
) -> ProductionSafetyQualificationCutoverReleaseEffectReport:
    handoff = _load_or_validate_cutover_release_handoff_report(
        cutover_release_handoff_report
    )
    manifest = _load_or_validate_cutover_release_effect_manifest(effect_manifest)
    if manifest.cutover_release_handoff_report_ref != handoff.source_path:
        raise ValueError("release effect manifest handoff ref must match report")
    if manifest.cutover_release_handoff_report_sha256 != handoff.sha256:
        raise ValueError("release effect manifest handoff sha256 must match report")
    report_source_path = source_path or f"{manifest.source_path}/report"
    manifest_sha = _cutover_release_effect_manifest_sha256(manifest)
    receipt = manifest.receipt
    receipt_sha = (
        receipt.sha256 or _cutover_release_effect_receipt_sha256(receipt)
        if receipt is not None
        else None
    )
    blockers = _cutover_release_effect_blockers(
        handoff,
        receipt,
        manifest.reference_time,
    )
    if (
        handoff.status != "cutover_release_handoff_recorded"
        or not handoff.ready_for_release_executor_handoff
    ):
        status: ProductionSafetyQualificationCutoverReleaseEffectStatus = (
            "blocked_cutover_release_handoff_incomplete"
        )
    elif receipt is None:
        status = "missing_cutover_release_effect_receipt"
    elif not receipt.accepted:
        status = "rejected_cutover_release_effect_receipt"
    elif not (
        receipt.source_integrity_evidence_present
        and receipt.max_age_metadata_present
        and receipt.reviewer_ref
        and receipt.reviewer_sha256
    ):
        status = "unverified_cutover_release_effect_source"
    elif blockers:
        status = "mismatched_cutover_release_effect_receipt"
    else:
        status = "cutover_release_effect_receipt_recorded"
    digest = aggregate_sha256(
        [
            {
                "source_path": report_source_path,
                "cutover_release_handoff_report_ref": handoff.source_path,
                "cutover_release_handoff_report_sha256": handoff.sha256,
                "effect_manifest_ref": manifest.source_path,
                "effect_manifest_sha256": manifest_sha,
                "effect_receipt_ref": receipt.source_path if receipt else None,
                "effect_receipt_sha256": receipt_sha,
                "release_executor_ref": (
                    receipt.release_executor_ref if receipt else None
                ),
                "release_invocation_ref": (
                    receipt.release_invocation_ref if receipt else None
                ),
                "release_execution_ref": (
                    receipt.release_execution_ref if receipt else None
                ),
                "release_result_ref": receipt.release_result_ref if receipt else None,
                "status": status,
                "blockers": blockers,
            }
        ]
    )
    return ProductionSafetyQualificationCutoverReleaseEffectReport(
        source_path=report_source_path,
        sha256=digest,
        status=status,
        cutover_release_handoff_report_ref=handoff.source_path,
        cutover_release_handoff_report_sha256=handoff.sha256,
        effect_manifest_ref=manifest.source_path,
        effect_manifest_sha256=manifest_sha,
        effect_receipt_ref=receipt.source_path if receipt else None,
        effect_receipt_sha256=receipt_sha,
        release_executor_ref=receipt.release_executor_ref if receipt else None,
        release_executor_sha256=receipt.release_executor_sha256 if receipt else None,
        release_invocation_ref=receipt.release_invocation_ref if receipt else None,
        release_invocation_sha256=(
            receipt.release_invocation_sha256 if receipt else None
        ),
        handoff_idempotency_key=receipt.handoff_idempotency_key if receipt else None,
        release_execution_ref=receipt.release_execution_ref if receipt else None,
        release_execution_sha256=(
            receipt.release_execution_sha256 if receipt else None
        ),
        release_result_ref=receipt.release_result_ref if receipt else None,
        release_result_sha256=receipt.release_result_sha256 if receipt else None,
        reviewer_ref=receipt.reviewer_ref if receipt else None,
        reviewer_sha256=receipt.reviewer_sha256 if receipt else None,
        release_observed_at=receipt.release_observed_at if receipt else None,
        receipt_accepted=receipt.accepted if receipt else False,
        executor_reported_release_completed=(
            receipt.executor_reported_release_completed if receipt else False
        ),
        source_integrity_evidence_present=(
            receipt.source_integrity_evidence_present if receipt else False
        ),
        max_age_metadata_present=(
            receipt.max_age_metadata_present if receipt else False
        ),
        cutover_release_effect_receipt_recorded=(
            status == "cutover_release_effect_receipt_recorded"
        ),
        ready_for_release_closure=(
            status == "cutover_release_effect_receipt_recorded"
        ),
        blockers=blockers,
        cutover_release_handoff_report=handoff,
        effect_manifest=manifest,
        effect_receipt=receipt,
        limitations=[
            "cutover release effect intake records an external executor receipt only",
            "recorded release effect is not production cutover authority",
            "does not call providers, resolve credentials, deploy writers, send transport, verify delivery, control hardware, invoke executors, or mutate runtime safety truth",
        ],
    )


def _cutover_release_effect_blockers(
    handoff: ProductionSafetyQualificationCutoverReleaseHandoffReport,
    receipt: ProductionSafetyQualificationCutoverReleaseEffectReceipt | None,
    reference_time: datetime,
) -> list[str]:
    blockers: list[str] = []
    if (
        handoff.status != "cutover_release_handoff_recorded"
        or not handoff.ready_for_release_executor_handoff
    ):
        blockers.append("cutover_release_handoff_not_recorded")
    if receipt is None:
        blockers.append("cutover_release_effect_receipt_missing")
        return blockers
    if not receipt.accepted:
        blockers.append("cutover_release_effect_receipt_rejected")
    if not receipt.executor_reported_release_completed:
        blockers.append("release_effect_not_completed")
    for field_name in (
        "cutover_release_handoff_report_ref",
        "cutover_release_handoff_report_sha256",
        "release_executor_ref",
        "release_executor_sha256",
        "release_invocation_ref",
        "release_invocation_sha256",
        "handoff_idempotency_key",
        "release_execution_ref",
        "release_execution_sha256",
        "release_result_ref",
        "release_result_sha256",
        "reviewer_ref",
        "reviewer_sha256",
        "release_observed_at",
    ):
        if getattr(receipt, field_name) in {None, ""}:
            blockers.append(f"{field_name}_missing")
    if receipt.cutover_release_handoff_report_ref != handoff.source_path:
        blockers.append("cutover_release_handoff_report_ref_mismatch")
    if receipt.cutover_release_handoff_report_sha256 != handoff.sha256:
        blockers.append("cutover_release_handoff_report_sha256_mismatch")
    for field_name in (
        "release_executor_ref",
        "release_executor_sha256",
        "release_invocation_ref",
        "release_invocation_sha256",
        "handoff_idempotency_key",
    ):
        if getattr(receipt, field_name) != getattr(handoff, field_name):
            blockers.append(f"{field_name}_mismatch")
    if not receipt.source_integrity_evidence_present:
        blockers.append("source_integrity_evidence_missing")
    if not receipt.max_age_metadata_present:
        blockers.append("max_age_metadata_missing")
    if (
        receipt.release_observed_at is not None
        and _as_utc(receipt.release_observed_at) > _as_utc(reference_time)
    ):
        blockers.append("release_observed_at_after_reference_time")
    return blockers


def evaluate_production_safety_qualification_cutover_release_closure(
    cutover_release_effect_report: (
        ProductionSafetyQualificationCutoverReleaseEffectReport
        | dict[str, Any]
        | Path
        | str
    ),
    closure_manifest: (
        ProductionSafetyQualificationCutoverReleaseClosureManifest
        | dict[str, Any]
        | Path
        | str
    ),
    *,
    source_path: str | None = None,
) -> ProductionSafetyQualificationCutoverReleaseClosureReport:
    effect = _load_or_validate_cutover_release_effect_report(
        cutover_release_effect_report
    )
    manifest = _load_or_validate_cutover_release_closure_manifest(closure_manifest)
    if manifest.cutover_release_effect_report_ref != effect.source_path:
        raise ValueError("release closure manifest effect ref must match report")
    if manifest.cutover_release_effect_report_sha256 != effect.sha256:
        raise ValueError("release closure manifest effect sha256 must match report")
    report_source_path = source_path or f"{manifest.source_path}/report"
    manifest_sha = _cutover_release_closure_manifest_sha256(manifest)
    review = manifest.closure_review
    review_sha = (
        review.sha256 or _cutover_release_closure_review_sha256(review)
        if review is not None
        else None
    )
    blockers = _cutover_release_closure_blockers(
        effect,
        review,
        manifest.reference_time,
    )
    if (
        effect.status != "cutover_release_effect_receipt_recorded"
        or not effect.ready_for_release_closure
    ):
        status: ProductionSafetyQualificationCutoverReleaseClosureStatus = (
            "blocked_cutover_release_effect_incomplete"
        )
    elif review is None:
        status = "missing_cutover_release_closure_review"
    elif not review.accepted:
        status = "rejected_cutover_release_closure_review"
    elif not (
        review.source_integrity_evidence_present
        and review.max_age_metadata_present
        and review.closure_reviewer_ref
        and review.closure_reviewer_sha256
    ):
        status = "unverified_cutover_release_closure_source"
    elif "expires_at_at_or_before_reference_time" in blockers:
        status = "expired_cutover_release_closure_review"
    elif (
        "closure_reviewer_confirmation_missing" in blockers
        or "explicit_confirmation_phrase_missing" in blockers
        or "explicit_confirmation_phrase_mismatch" in blockers
    ):
        status = "missing_release_closure_confirmation"
    elif blockers:
        status = "mismatched_cutover_release_closure_review"
    else:
        status = "cutover_release_closure_recorded"
    digest = aggregate_sha256(
        [
            {
                "source_path": report_source_path,
                "cutover_release_effect_report_ref": effect.source_path,
                "cutover_release_effect_report_sha256": effect.sha256,
                "closure_manifest_ref": manifest.source_path,
                "closure_manifest_sha256": manifest_sha,
                "closure_review_ref": review.source_path if review else None,
                "closure_review_sha256": review_sha,
                "release_executor_ref": (
                    review.release_executor_ref if review else None
                ),
                "release_invocation_ref": (
                    review.release_invocation_ref if review else None
                ),
                "release_execution_ref": (
                    review.release_execution_ref if review else None
                ),
                "release_result_ref": review.release_result_ref if review else None,
                "status": status,
                "blockers": blockers,
            }
        ]
    )
    return ProductionSafetyQualificationCutoverReleaseClosureReport(
        source_path=report_source_path,
        sha256=digest,
        status=status,
        cutover_release_effect_report_ref=effect.source_path,
        cutover_release_effect_report_sha256=effect.sha256,
        closure_manifest_ref=manifest.source_path,
        closure_manifest_sha256=manifest_sha,
        closure_review_ref=review.source_path if review else None,
        closure_review_sha256=review_sha,
        release_executor_ref=review.release_executor_ref if review else None,
        release_executor_sha256=review.release_executor_sha256 if review else None,
        release_invocation_ref=review.release_invocation_ref if review else None,
        release_invocation_sha256=(
            review.release_invocation_sha256 if review else None
        ),
        handoff_idempotency_key=review.handoff_idempotency_key if review else None,
        release_execution_ref=review.release_execution_ref if review else None,
        release_execution_sha256=(
            review.release_execution_sha256 if review else None
        ),
        release_result_ref=review.release_result_ref if review else None,
        release_result_sha256=review.release_result_sha256 if review else None,
        release_effect_reviewer_ref=(
            review.release_effect_reviewer_ref if review else None
        ),
        release_effect_reviewer_sha256=(
            review.release_effect_reviewer_sha256 if review else None
        ),
        closure_reviewer_ref=review.closure_reviewer_ref if review else None,
        closure_reviewer_sha256=review.closure_reviewer_sha256 if review else None,
        rollback_plan_ref=review.rollback_plan_ref if review else None,
        rollback_plan_sha256=review.rollback_plan_sha256 if review else None,
        production_change_request_ref=(
            review.production_change_request_ref if review else None
        ),
        production_change_request_sha256=(
            review.production_change_request_sha256 if review else None
        ),
        closure_reviewed_at=review.closure_reviewed_at if review else None,
        expires_at=review.expires_at if review else None,
        review_accepted=review.accepted if review else False,
        closure_reviewer_confirmation=(
            review.closure_reviewer_confirmation if review else False
        ),
        source_integrity_evidence_present=(
            review.source_integrity_evidence_present if review else False
        ),
        max_age_metadata_present=(
            review.max_age_metadata_present if review else False
        ),
        explicit_confirmation_phrase=(
            review.explicit_confirmation_phrase if review else None
        ),
        cutover_release_closure_recorded=(
            status == "cutover_release_closure_recorded"
        ),
        ready_for_production_cutover_review=(
            status == "cutover_release_closure_recorded"
        ),
        blockers=blockers,
        cutover_release_effect_report=effect,
        closure_manifest=manifest,
        closure_review=review,
        limitations=[
            "cutover release closure records reviewer acceptance only",
            "recorded release closure is not production cutover authority",
            "does not call providers, resolve credentials, deploy writers, send transport, verify delivery, control hardware, invoke executors, or mutate runtime safety truth",
        ],
    )


def _cutover_release_closure_blockers(
    effect: ProductionSafetyQualificationCutoverReleaseEffectReport,
    review: ProductionSafetyQualificationCutoverReleaseClosureReview | None,
    reference_time: datetime,
) -> list[str]:
    blockers: list[str] = []
    if (
        effect.status != "cutover_release_effect_receipt_recorded"
        or not effect.ready_for_release_closure
    ):
        blockers.append("cutover_release_effect_not_recorded")
    if review is None:
        blockers.append("cutover_release_closure_review_missing")
        return blockers
    if not review.accepted:
        blockers.append("cutover_release_closure_review_rejected")
    for field_name in (
        "cutover_release_effect_report_ref",
        "cutover_release_effect_report_sha256",
        "release_executor_ref",
        "release_executor_sha256",
        "release_invocation_ref",
        "release_invocation_sha256",
        "handoff_idempotency_key",
        "release_execution_ref",
        "release_execution_sha256",
        "release_result_ref",
        "release_result_sha256",
        "release_effect_reviewer_ref",
        "release_effect_reviewer_sha256",
        "closure_reviewer_ref",
        "closure_reviewer_sha256",
        "rollback_plan_ref",
        "rollback_plan_sha256",
        "production_change_request_ref",
        "production_change_request_sha256",
        "closure_reviewed_at",
        "expires_at",
    ):
        if getattr(review, field_name) in {None, ""}:
            blockers.append(f"{field_name}_missing")
    if review.cutover_release_effect_report_ref != effect.source_path:
        blockers.append("cutover_release_effect_report_ref_mismatch")
    if review.cutover_release_effect_report_sha256 != effect.sha256:
        blockers.append("cutover_release_effect_report_sha256_mismatch")
    for field_name in (
        "release_executor_ref",
        "release_executor_sha256",
        "release_invocation_ref",
        "release_invocation_sha256",
        "handoff_idempotency_key",
        "release_execution_ref",
        "release_execution_sha256",
        "release_result_ref",
        "release_result_sha256",
    ):
        if getattr(review, field_name) != getattr(effect, field_name):
            blockers.append(f"{field_name}_mismatch")
    if review.release_effect_reviewer_ref != effect.reviewer_ref:
        blockers.append("release_effect_reviewer_ref_mismatch")
    if review.release_effect_reviewer_sha256 != effect.reviewer_sha256:
        blockers.append("release_effect_reviewer_sha256_mismatch")
    handoff = effect.cutover_release_handoff_report
    for field_name in (
        "rollback_plan_ref",
        "rollback_plan_sha256",
        "production_change_request_ref",
        "production_change_request_sha256",
    ):
        if getattr(review, field_name) != getattr(handoff, field_name):
            blockers.append(f"{field_name}_mismatch")
    if not review.source_integrity_evidence_present:
        blockers.append("source_integrity_evidence_missing")
    if not review.max_age_metadata_present:
        blockers.append("max_age_metadata_missing")
    if not review.closure_reviewer_confirmation:
        blockers.append("closure_reviewer_confirmation_missing")
    if review.explicit_confirmation_phrase in {None, ""}:
        blockers.append("explicit_confirmation_phrase_missing")
    elif (
        review.explicit_confirmation_phrase
        != PRODUCTION_SAFETY_CUTOVER_RELEASE_CLOSURE_CONFIRMATION
    ):
        blockers.append("explicit_confirmation_phrase_mismatch")
    if (
        review.closure_reviewed_at is not None
        and _as_utc(review.closure_reviewed_at) > _as_utc(reference_time)
    ):
        blockers.append("closure_reviewed_at_after_reference_time")
    if (
        review.expires_at is not None
        and _as_utc(review.expires_at) <= _as_utc(reference_time)
    ):
        blockers.append("expires_at_at_or_before_reference_time")
    return blockers


def _external_result_bridge_row_from_request(
    request: ProductionSafetyQualificationEvidenceRequestRow,
    result_row: ProductionSafetyQualificationExternalResultRow | None,
) -> tuple[
    ProductionSafetyQualificationExternalResultEvidenceBridgeRow,
    ProductionSafetyQualificationEvidenceSubmission | None,
]:
    row_base: dict[str, Any] = {
        "request_kind": request.request_kind,
        "source_gap_kind": request.source_gap_kind,
        "action": request.action,
        "area": request.area,
        "threat_id": request.threat_id,
        "mode_id": request.mode_id,
    }
    if result_row is None:
        return (
            ProductionSafetyQualificationExternalResultEvidenceBridgeRow(
                **row_base,
                status="missing_result_for_request",
                blockers=["external_result_row_missing_for_request"],
            ),
            None,
        )
    if not result_row.ready_for_evidence_fulfillment:
        return (
            ProductionSafetyQualificationExternalResultEvidenceBridgeRow(
                **row_base,
                status="blocked_result_not_ready",
                blockers=result_row.blockers or ["external_result_row_not_ready"],
            ),
            None,
        )
    artifact = _external_result_artifact_for_request(request, result_row)
    if artifact is None:
        return (
            ProductionSafetyQualificationExternalResultEvidenceBridgeRow(
                **row_base,
                status="mismatched_result_artifact",
                blockers=["external_result_artifact_kind_not_requested"],
            ),
            None,
        )
    artifact_blockers = _external_result_artifact_blockers(request, artifact)
    if artifact_blockers:
        return (
            ProductionSafetyQualificationExternalResultEvidenceBridgeRow(
                **row_base,
                status="mismatched_result_artifact",
                submitted_artifact_kind=artifact.submitted_artifact_kind,
                submitted_artifact_ref=artifact.submitted_artifact_ref,
                submitted_artifact_sha256=artifact.submitted_artifact_sha256,
                blockers=artifact_blockers,
            ),
            None,
        )
    submission = _external_result_artifact_submission(request, artifact)
    return (
        ProductionSafetyQualificationExternalResultEvidenceBridgeRow(
            **row_base,
            status="bridged_to_fulfillment_submission",
            submitted_artifact_kind=artifact.submitted_artifact_kind,
            submitted_artifact_ref=artifact.submitted_artifact_ref,
            submitted_artifact_sha256=artifact.submitted_artifact_sha256,
            bridged_to_fulfillment_submission=True,
        ),
        submission,
    )


def _external_result_artifact_for_request(
    request: ProductionSafetyQualificationEvidenceRequestRow,
    result_row: ProductionSafetyQualificationExternalResultRow,
) -> ProductionSafetyQualificationExternalResultArtifact | None:
    for artifact in result_row.provided_artifacts:
        if artifact.submitted_artifact_kind in request.required_artifacts:
            return artifact
    if result_row.result_artifact_kind not in request.required_artifacts:
        return None
    if result_row.result_ref is None or result_row.result_sha256 is None:
        return None
    return ProductionSafetyQualificationExternalResultArtifact(
        submitted_artifact_kind=result_row.result_artifact_kind,
        submitted_artifact_ref=result_row.result_ref,
        submitted_artifact_sha256=result_row.result_sha256,
        reviewer_ref=result_row.reviewer_ref,
        reviewer_sha256=result_row.reviewer_sha256,
        source_integrity_evidence_present=True,
        max_age_metadata_present=True,
        accepted=True,
    )


def _external_result_artifact_blockers(
    request: ProductionSafetyQualificationEvidenceRequestRow,
    artifact: ProductionSafetyQualificationExternalResultArtifact,
) -> list[str]:
    blockers: list[str] = []
    if not artifact.accepted:
        blockers.append("external_result_artifact_not_accepted")
    if request.human_review_required and not (
        artifact.reviewer_ref and artifact.reviewer_sha256
    ):
        blockers.append("external_result_artifact_human_review_missing")
    if request.source_integrity_required and not artifact.source_integrity_evidence_present:
        blockers.append("external_result_artifact_source_integrity_missing")
    if request.max_age_seconds_required and not artifact.max_age_metadata_present:
        blockers.append("external_result_artifact_max_age_metadata_missing")
    return blockers


def _external_result_artifact_submission(
    request: ProductionSafetyQualificationEvidenceRequestRow,
    artifact: ProductionSafetyQualificationExternalResultArtifact,
) -> ProductionSafetyQualificationEvidenceSubmission:
    return ProductionSafetyQualificationEvidenceSubmission(
        request_kind=request.request_kind,
        area=request.area,
        threat_id=request.threat_id,
        mode_id=request.mode_id,
        submitted_artifact_kind=artifact.submitted_artifact_kind,
        submitted_artifact_ref=artifact.submitted_artifact_ref,
        submitted_artifact_sha256=artifact.submitted_artifact_sha256,
        reviewer_ref=artifact.reviewer_ref,
        reviewer_sha256=artifact.reviewer_sha256,
        source_integrity_evidence_present=artifact.source_integrity_evidence_present,
        max_age_metadata_present=artifact.max_age_metadata_present,
        accepted=artifact.accepted,
        credential_material_embedded=artifact.credential_material_embedded,
        raw_payload_embedded=artifact.raw_payload_embedded,
        notes=[
            "bridged from external result receipt; must still pass fulfillment source-integrity verification"
        ],
    )


def _external_result_bridge_key_from_request(
    row: ProductionSafetyQualificationEvidenceRequestRow,
) -> str:
    return "|".join(
        [
            row.source_gap_kind or "",
            row.action or "",
            row.area or "",
            row.threat_id or "",
            row.mode_id or "",
        ]
    )


def _external_result_bridge_key_from_result_row(
    row: ProductionSafetyQualificationExternalResultRow,
) -> str:
    return "|".join(
        [
            row.gap_kind,
            row.action,
            row.area or "",
            row.threat_id or "",
            row.mode_id or "",
        ]
    )


def _external_result_row_from_invocation_row(
    invocation_row: ProductionSafetyQualificationExternalInvocationRow,
    receipt: ProductionSafetyQualificationExternalResultReceipt | None,
) -> ProductionSafetyQualificationExternalResultRow:
    row_base: dict[str, Any] = {
        "gap_kind": invocation_row.gap_kind,
        "action": invocation_row.action,
        "external_action_kind": invocation_row.external_action_kind,
        "area": invocation_row.area,
        "threat_id": invocation_row.threat_id,
        "mode_id": invocation_row.mode_id,
        "external_executor_ref": invocation_row.external_executor_ref,
        "external_executor_sha256": invocation_row.external_executor_sha256,
        "executor_invocation_ref": invocation_row.executor_invocation_ref,
        "executor_invocation_sha256": invocation_row.executor_invocation_sha256,
    }
    if not invocation_row.ready_for_separate_executor_handoff:
        return ProductionSafetyQualificationExternalResultRow(
            **row_base,
            status="blocked_invocation_incomplete",
            blockers=invocation_row.blockers or ["external_invocation_row_blocked"],
        )
    if receipt is None:
        return ProductionSafetyQualificationExternalResultRow(
            **row_base,
            status="missing_result_receipt",
            blockers=["external_result_receipt_missing"],
        )
    blockers = _external_result_blockers(invocation_row, receipt)
    if not receipt.accepted:
        status: ProductionSafetyQualificationExternalResultRowStatus = (
            "rejected_result_receipt"
        )
        blockers.append("external_result_receipt_not_accepted")
    elif not receipt.source_integrity_evidence_present:
        status = "unverified_result_source"
        blockers.append("external_result_source_integrity_missing")
    elif blockers:
        status = "mismatched_result_receipt"
    else:
        status = "result_receipt_recorded"
    return ProductionSafetyQualificationExternalResultRow(
        **row_base,
        status=status,
        result_receipt_recorded=status == "result_receipt_recorded",
        ready_for_evidence_fulfillment=status == "result_receipt_recorded",
        result_artifact_kind=receipt.result_artifact_kind,
        result_ref=receipt.result_ref,
        result_sha256=receipt.result_sha256,
        result_observed_at=receipt.result_observed_at,
        reviewer_ref=receipt.reviewer_ref,
        reviewer_sha256=receipt.reviewer_sha256,
        provided_artifacts=receipt.provided_artifacts,
        blockers=blockers,
    )


def _external_result_blockers(
    invocation_row: ProductionSafetyQualificationExternalInvocationRow,
    receipt: ProductionSafetyQualificationExternalResultReceipt,
) -> list[str]:
    blockers: list[str] = []
    if receipt.external_action_kind != invocation_row.external_action_kind:
        blockers.append("external_action_kind_mismatch")
    if receipt.area != invocation_row.area:
        blockers.append("area_mismatch")
    if receipt.threat_id != invocation_row.threat_id:
        blockers.append("threat_id_mismatch")
    if receipt.mode_id != invocation_row.mode_id:
        blockers.append("mode_id_mismatch")
    for field_name in (
        "external_executor_ref",
        "external_executor_sha256",
        "executor_invocation_ref",
        "executor_invocation_sha256",
    ):
        if getattr(receipt, field_name) != getattr(invocation_row, field_name):
            blockers.append(f"{field_name}_mismatch")
    for field_name in (
        "result_artifact_kind",
        "result_ref",
        "result_sha256",
        "result_observed_at",
        "reviewer_ref",
        "reviewer_sha256",
    ):
        if getattr(receipt, field_name) in {None, ""}:
            blockers.append(f"{field_name}_missing")
    if not receipt.max_age_metadata_present:
        blockers.append("external_result_max_age_metadata_missing")
    return blockers


def _external_result_key(
    row: ProductionSafetyQualificationExternalInvocationRow
    | ProductionSafetyQualificationExternalResultReceipt,
) -> str:
    return "|".join(
        [
            row.gap_kind,
            row.action,
            row.area or "",
            row.threat_id or "",
            row.mode_id or "",
        ]
    )


def _external_result_manifest_sha256(
    manifest: ProductionSafetyQualificationExternalResultManifest,
) -> str:
    return aggregate_sha256([manifest.model_dump(mode="json")])


def _qualification_row(
    area: ProductionSafetyQualificationArea,
    receipt: ProductionSafetyQualificationReceipt | None,
) -> ProductionSafetyQualificationRow:
    if receipt is None:
        return ProductionSafetyQualificationRow(
            area=area,
            status="missing",
            blockers=[f"{area}_qualification_missing"],
        )

    receipt_sha = receipt.sha256 or _qualification_receipt_sha256(receipt)
    qualified = (
        receipt.status == "qualified"
        and receipt.capability_observed
        and receipt.production_environment_verified
        and receipt.lineage_verified
        and receipt.fail_closed_behavior_verified
        and receipt.rollback_or_fallback_verified
        and bool(receipt.qualification_ref)
        and bool(receipt.qualification_sha256)
        and bool(receipt.reviewed_effect_boundary_ref)
        and bool(receipt.reviewed_effect_boundary_sha256)
        and bool(receipt.operator_review_ref)
        and bool(receipt.operator_review_sha256)
    )
    blockers = [] if qualified else [f"{area}_qualification_not_accepted"]
    return ProductionSafetyQualificationRow(
        area=area,
        status=receipt.status,
        receipt_sha256=receipt_sha,
        qualification_ref=receipt.qualification_ref,
        qualification_sha256=receipt.qualification_sha256,
        reviewed_effect_boundary_ref=receipt.reviewed_effect_boundary_ref,
        operator_review_ref=receipt.operator_review_ref,
        capability_observed=receipt.capability_observed,
        production_environment_verified=receipt.production_environment_verified,
        lineage_verified=receipt.lineage_verified,
        fail_closed_behavior_verified=receipt.fail_closed_behavior_verified,
        rollback_or_fallback_verified=receipt.rollback_or_fallback_verified,
        qualified_for_cutover=qualified,
        blockers=blockers,
    )


def _load_or_validate_dossier_manifest(
    manifest: ProductionSafetyQualificationDossierManifest | dict[str, Any] | Path | str,
) -> ProductionSafetyQualificationDossierManifest:
    if isinstance(manifest, ProductionSafetyQualificationDossierManifest):
        return manifest
    if isinstance(manifest, dict):
        return ProductionSafetyQualificationDossierManifest.model_validate(manifest)
    return load_production_safety_qualification_dossier_manifest(manifest)


def _load_or_validate_dossier_report(
    report: ProductionSafetyQualificationDossierReport | dict[str, Any] | Path | str,
) -> ProductionSafetyQualificationDossierReport:
    if isinstance(report, ProductionSafetyQualificationDossierReport):
        return report
    if isinstance(report, dict):
        return ProductionSafetyQualificationDossierReport.model_validate(report)
    return load_production_safety_qualification_dossier_report(report)


def _load_or_validate_gap_plan(
    plan: ProductionSafetyQualificationGapPlan | dict[str, Any] | Path | str,
) -> ProductionSafetyQualificationGapPlan:
    if isinstance(plan, ProductionSafetyQualificationGapPlan):
        return plan
    if isinstance(plan, dict):
        return ProductionSafetyQualificationGapPlan.model_validate(plan)
    return load_production_safety_qualification_gap_plan(plan)


def _load_or_validate_evidence_request_pack(
    pack: ProductionSafetyQualificationEvidenceRequestPack
    | dict[str, Any]
    | Path
    | str,
) -> ProductionSafetyQualificationEvidenceRequestPack:
    if isinstance(pack, ProductionSafetyQualificationEvidenceRequestPack):
        return pack
    if isinstance(pack, dict):
        return ProductionSafetyQualificationEvidenceRequestPack.model_validate(pack)
    return load_production_safety_qualification_evidence_request_pack(pack)


def _load_or_validate_evidence_fulfillment_manifest(
    manifest: ProductionSafetyQualificationEvidenceFulfillmentManifest
    | dict[str, Any]
    | Path
    | str,
) -> ProductionSafetyQualificationEvidenceFulfillmentManifest:
    if isinstance(manifest, ProductionSafetyQualificationEvidenceFulfillmentManifest):
        return manifest
    if isinstance(manifest, dict):
        return ProductionSafetyQualificationEvidenceFulfillmentManifest.model_validate(
            manifest
        )
    return load_production_safety_qualification_evidence_fulfillment_manifest(manifest)


def _load_or_validate_evidence_fulfillment_source_package(
    package: ProductionSafetyQualificationEvidenceFulfillmentSourcePackage
    | dict[str, Any]
    | Path
    | str,
) -> ProductionSafetyQualificationEvidenceFulfillmentSourcePackage:
    if isinstance(package, ProductionSafetyQualificationEvidenceFulfillmentSourcePackage):
        return package
    if isinstance(package, dict):
        return ProductionSafetyQualificationEvidenceFulfillmentSourcePackage.model_validate(
            package
        )
    return load_production_safety_qualification_evidence_fulfillment_source_package(
        package
    )


def _load_or_validate_evidence_fulfillment_source_integrity_report(
    report: ProductionSafetyQualificationEvidenceFulfillmentSourceIntegrityReport
    | dict[str, Any]
    | Path
    | str
    | None,
) -> ProductionSafetyQualificationEvidenceFulfillmentSourceIntegrityReport | None:
    if report is None:
        return None
    if isinstance(
        report,
        ProductionSafetyQualificationEvidenceFulfillmentSourceIntegrityReport,
    ):
        return report
    if isinstance(report, dict):
        return (
            ProductionSafetyQualificationEvidenceFulfillmentSourceIntegrityReport.model_validate(
                report
            )
        )
    return load_production_safety_qualification_evidence_fulfillment_source_integrity_report(
        report
    )


def _load_or_validate_evidence_fulfillment_report(
    report: ProductionSafetyQualificationEvidenceFulfillmentReport
    | dict[str, Any]
    | Path
    | str,
) -> ProductionSafetyQualificationEvidenceFulfillmentReport:
    if isinstance(report, ProductionSafetyQualificationEvidenceFulfillmentReport):
        return report
    if isinstance(report, dict):
        return ProductionSafetyQualificationEvidenceFulfillmentReport.model_validate(
            report
        )
    return load_production_safety_qualification_evidence_fulfillment_report(report)


def _load_or_validate_remediation_readiness_report(
    report: ProductionSafetyQualificationRemediationReadinessReport
    | dict[str, Any]
    | Path
    | str,
) -> ProductionSafetyQualificationRemediationReadinessReport:
    if isinstance(report, ProductionSafetyQualificationRemediationReadinessReport):
        return report
    if isinstance(report, dict):
        return ProductionSafetyQualificationRemediationReadinessReport.model_validate(
            report
        )
    return load_production_safety_qualification_remediation_readiness_report(report)


def _load_or_validate_external_action_packet(
    packet: ProductionSafetyQualificationExternalActionPacket
    | dict[str, Any]
    | Path
    | str,
) -> ProductionSafetyQualificationExternalActionPacket:
    if isinstance(packet, ProductionSafetyQualificationExternalActionPacket):
        return packet
    if isinstance(packet, dict):
        return ProductionSafetyQualificationExternalActionPacket.model_validate(packet)
    return load_production_safety_qualification_external_action_packet(packet)


def _load_or_validate_external_authorization_manifest(
    manifest: ProductionSafetyQualificationExternalAuthorizationManifest
    | dict[str, Any]
    | Path
    | str,
) -> ProductionSafetyQualificationExternalAuthorizationManifest:
    if isinstance(manifest, ProductionSafetyQualificationExternalAuthorizationManifest):
        return manifest
    if isinstance(manifest, dict):
        return ProductionSafetyQualificationExternalAuthorizationManifest.model_validate(
            manifest
        )
    return load_production_safety_qualification_external_authorization_manifest(
        manifest
    )


def _load_or_validate_external_authorization_report(
    report: ProductionSafetyQualificationExternalAuthorizationReport
    | dict[str, Any]
    | Path
    | str,
) -> ProductionSafetyQualificationExternalAuthorizationReport:
    if isinstance(report, ProductionSafetyQualificationExternalAuthorizationReport):
        return report
    if isinstance(report, dict):
        return (
            ProductionSafetyQualificationExternalAuthorizationReport.model_validate(
                report
            )
        )
    return load_production_safety_qualification_external_authorization_report(
        report
    )


def _load_or_validate_external_invocation_manifest(
    manifest: ProductionSafetyQualificationExternalInvocationManifest
    | dict[str, Any]
    | Path
    | str,
) -> ProductionSafetyQualificationExternalInvocationManifest:
    if isinstance(manifest, ProductionSafetyQualificationExternalInvocationManifest):
        return manifest
    if isinstance(manifest, dict):
        return ProductionSafetyQualificationExternalInvocationManifest.model_validate(
            manifest
        )
    return load_production_safety_qualification_external_invocation_manifest(
        manifest
    )


def _load_or_validate_external_invocation_report(
    report: ProductionSafetyQualificationExternalInvocationReport
    | dict[str, Any]
    | Path
    | str,
) -> ProductionSafetyQualificationExternalInvocationReport:
    if isinstance(report, ProductionSafetyQualificationExternalInvocationReport):
        return report
    if isinstance(report, dict):
        return ProductionSafetyQualificationExternalInvocationReport.model_validate(
            report
        )
    return load_production_safety_qualification_external_invocation_report(report)


def _load_or_validate_external_result_manifest(
    manifest: ProductionSafetyQualificationExternalResultManifest
    | dict[str, Any]
    | Path
    | str,
) -> ProductionSafetyQualificationExternalResultManifest:
    if isinstance(manifest, ProductionSafetyQualificationExternalResultManifest):
        return manifest
    if isinstance(manifest, dict):
        return ProductionSafetyQualificationExternalResultManifest.model_validate(
            manifest
        )
    return load_production_safety_qualification_external_result_manifest(manifest)


def _load_or_validate_external_result_report(
    report: ProductionSafetyQualificationExternalResultReport
    | dict[str, Any]
    | Path
    | str,
) -> ProductionSafetyQualificationExternalResultReport:
    if isinstance(report, ProductionSafetyQualificationExternalResultReport):
        return report
    if isinstance(report, dict):
        return ProductionSafetyQualificationExternalResultReport.model_validate(report)
    return load_production_safety_qualification_external_result_report(report)


def _load_or_validate_external_result_evidence_bridge_report(
    report: ProductionSafetyQualificationExternalResultEvidenceBridgeReport
    | dict[str, Any]
    | Path
    | str,
) -> ProductionSafetyQualificationExternalResultEvidenceBridgeReport:
    if isinstance(report, ProductionSafetyQualificationExternalResultEvidenceBridgeReport):
        return report
    if isinstance(report, dict):
        return (
            ProductionSafetyQualificationExternalResultEvidenceBridgeReport.model_validate(
                report
            )
        )
    return load_production_safety_qualification_external_result_evidence_bridge_report(
        report
    )


def _load_or_validate_external_result_remediation_closure_report(
    report: ProductionSafetyQualificationExternalResultRemediationClosureReport
    | dict[str, Any]
    | Path
    | str,
) -> ProductionSafetyQualificationExternalResultRemediationClosureReport:
    if isinstance(
        report,
        ProductionSafetyQualificationExternalResultRemediationClosureReport,
    ):
        return report
    if isinstance(report, dict):
        return (
            ProductionSafetyQualificationExternalResultRemediationClosureReport.model_validate(
                report
            )
        )
    return load_production_safety_qualification_external_result_remediation_closure_report(
        report
    )


def _load_or_validate_dossier_rerun_report(
    report: ProductionSafetyQualificationDossierRerunReport
    | dict[str, Any]
    | Path
    | str,
) -> ProductionSafetyQualificationDossierRerunReport:
    if isinstance(report, ProductionSafetyQualificationDossierRerunReport):
        return report
    if isinstance(report, dict):
        return ProductionSafetyQualificationDossierRerunReport.model_validate(report)
    return load_production_safety_qualification_dossier_rerun_report(report)


def _load_or_validate_cutover_authorization_manifest(
    manifest: ProductionSafetyQualificationCutoverAuthorizationManifest
    | dict[str, Any]
    | Path
    | str,
) -> ProductionSafetyQualificationCutoverAuthorizationManifest:
    if isinstance(manifest, ProductionSafetyQualificationCutoverAuthorizationManifest):
        return manifest
    if isinstance(manifest, dict):
        return ProductionSafetyQualificationCutoverAuthorizationManifest.model_validate(
            manifest
        )
    return load_production_safety_qualification_cutover_authorization_manifest(
        manifest
    )


def _load_or_validate_cutover_authorization_report(
    report: ProductionSafetyQualificationCutoverAuthorizationReport
    | dict[str, Any]
    | Path
    | str,
) -> ProductionSafetyQualificationCutoverAuthorizationReport:
    if isinstance(report, ProductionSafetyQualificationCutoverAuthorizationReport):
        return report
    if isinstance(report, dict):
        return ProductionSafetyQualificationCutoverAuthorizationReport.model_validate(
            report
        )
    return load_production_safety_qualification_cutover_authorization_report(report)


def _load_or_validate_cutover_release_handoff_manifest(
    manifest: ProductionSafetyQualificationCutoverReleaseHandoffManifest
    | dict[str, Any]
    | Path
    | str,
) -> ProductionSafetyQualificationCutoverReleaseHandoffManifest:
    if isinstance(manifest, ProductionSafetyQualificationCutoverReleaseHandoffManifest):
        return manifest
    if isinstance(manifest, dict):
        return (
            ProductionSafetyQualificationCutoverReleaseHandoffManifest.model_validate(
                manifest
            )
        )
    return load_production_safety_qualification_cutover_release_handoff_manifest(
        manifest
    )


def _load_or_validate_cutover_release_handoff_report(
    report: ProductionSafetyQualificationCutoverReleaseHandoffReport
    | dict[str, Any]
    | Path
    | str,
) -> ProductionSafetyQualificationCutoverReleaseHandoffReport:
    if isinstance(report, ProductionSafetyQualificationCutoverReleaseHandoffReport):
        return report
    if isinstance(report, dict):
        return ProductionSafetyQualificationCutoverReleaseHandoffReport.model_validate(
            report
        )
    return load_production_safety_qualification_cutover_release_handoff_report(report)


def _load_or_validate_cutover_release_effect_manifest(
    manifest: ProductionSafetyQualificationCutoverReleaseEffectManifest
    | dict[str, Any]
    | Path
    | str,
) -> ProductionSafetyQualificationCutoverReleaseEffectManifest:
    if isinstance(manifest, ProductionSafetyQualificationCutoverReleaseEffectManifest):
        return manifest
    if isinstance(manifest, dict):
        return (
            ProductionSafetyQualificationCutoverReleaseEffectManifest.model_validate(
                manifest
            )
        )
    return load_production_safety_qualification_cutover_release_effect_manifest(
        manifest
    )


def _load_or_validate_cutover_release_effect_report(
    report: ProductionSafetyQualificationCutoverReleaseEffectReport
    | dict[str, Any]
    | Path
    | str,
) -> ProductionSafetyQualificationCutoverReleaseEffectReport:
    if isinstance(report, ProductionSafetyQualificationCutoverReleaseEffectReport):
        return report
    if isinstance(report, dict):
        return ProductionSafetyQualificationCutoverReleaseEffectReport.model_validate(
            report
        )
    return load_production_safety_qualification_cutover_release_effect_report(report)


def _load_or_validate_cutover_release_closure_manifest(
    manifest: ProductionSafetyQualificationCutoverReleaseClosureManifest
    | dict[str, Any]
    | Path
    | str,
) -> ProductionSafetyQualificationCutoverReleaseClosureManifest:
    if isinstance(manifest, ProductionSafetyQualificationCutoverReleaseClosureManifest):
        return manifest
    if isinstance(manifest, dict):
        return (
            ProductionSafetyQualificationCutoverReleaseClosureManifest.model_validate(
                manifest
            )
        )
    return load_production_safety_qualification_cutover_release_closure_manifest(
        manifest
    )


def _load_or_validate_threat_coverage_manifest(
    manifest: ProductionSafetyQualificationThreatCoverageManifest
    | dict[str, Any]
    | Path
    | str,
) -> ProductionSafetyQualificationThreatCoverageManifest:
    if isinstance(manifest, ProductionSafetyQualificationThreatCoverageManifest):
        return manifest
    if isinstance(manifest, dict):
        return ProductionSafetyQualificationThreatCoverageManifest.model_validate(
            manifest
        )
    return load_production_safety_qualification_threat_coverage_manifest(manifest)


def _evidence_request_key(
    row: ProductionSafetyQualificationEvidenceRequestRow,
) -> str:
    return ":".join(
        [
            row.request_kind,
            row.area or "",
            row.threat_id or "",
            row.mode_id or "",
        ]
    )


def _evidence_request_submission_key(
    submission: ProductionSafetyQualificationEvidenceSubmission,
) -> str:
    return ":".join(
        [
            submission.request_kind,
            submission.area or "",
            submission.threat_id or "",
            submission.mode_id or "",
        ]
    )


def _evidence_fulfillment_report_row_key(
    row: ProductionSafetyQualificationEvidenceFulfillmentRow,
) -> str:
    return ":".join(
        [
            row.request_kind,
            row.area or "",
            row.threat_id or "",
            row.mode_id or "",
        ]
    )


def _remediation_row_from_gap(
    gap: ProductionSafetyQualificationGapRow,
    *,
    request_keys: set[str],
    fulfillment_rows_by_key: dict[
        str,
        ProductionSafetyQualificationEvidenceFulfillmentRow,
    ],
) -> ProductionSafetyQualificationRemediationRow:
    expected_requests = _evidence_request_rows_from_gap(gap)
    blockers: list[str] = []
    request_statuses: list[
        ProductionSafetyQualificationEvidenceRequestFulfillmentRowStatus
    ] = []
    fulfilled_count = 0
    row_status: ProductionSafetyQualificationRemediationRowStatus | None = None
    for expected in expected_requests:
        key = _evidence_request_key(expected)
        if key not in request_keys:
            blockers.append(f"request_pack_row_missing:{key}")
            row_status = row_status or "blocked_request_pack_mismatch"
            continue
        fulfillment_row = fulfillment_rows_by_key.get(key)
        if fulfillment_row is None:
            blockers.append(f"fulfillment_report_row_missing:{key}")
            row_status = row_status or "blocked_request_pack_mismatch"
            continue
        request_statuses.append(fulfillment_row.status)
        if fulfillment_row.status == "fulfilled":
            fulfilled_count += 1
            continue
        blockers.extend(
            f"{blocker}:{key}" for blocker in fulfillment_row.blockers
        )
        row_status = row_status or _remediation_status_from_fulfillment_status(
            fulfillment_row.status
        )
    if row_status is None:
        row_status = "ready_for_dossier_rerun"
    return ProductionSafetyQualificationRemediationRow(
        gap_kind=gap.gap_kind,
        action=gap.action,
        status=row_status,
        area=gap.area,
        threat_id=gap.threat_id,
        mode_id=gap.mode_id,
        expected_request_count=len(expected_requests),
        fulfilled_request_count=fulfilled_count,
        request_statuses=request_statuses,
        ready_for_dossier_rerun=row_status == "ready_for_dossier_rerun",
        blockers=blockers,
        unblock_condition=(
            "rerun the production qualification dossier with the fulfilled "
            "source-verified artifacts"
            if row_status == "ready_for_dossier_rerun"
            else gap.unblock_condition
        ),
    )


def _remediation_status_from_fulfillment_status(
    status: ProductionSafetyQualificationEvidenceRequestFulfillmentRowStatus,
) -> ProductionSafetyQualificationRemediationRowStatus:
    if status == "missing":
        return "blocked_missing_requested_evidence"
    if status == "mismatched":
        return "blocked_mismatched_requested_evidence"
    if status == "rejected":
        return "blocked_rejected_requested_evidence"
    if status == "source_unverified":
        return "blocked_fulfillment_source_integrity_unverified"
    return "ready_for_dossier_rerun"


def _evidence_fulfillment_row(
    request: ProductionSafetyQualificationEvidenceRequestRow,
    submission: ProductionSafetyQualificationEvidenceSubmission | None,
    *,
    verified_source_refs: set[str] | None = None,
) -> ProductionSafetyQualificationEvidenceFulfillmentRow:
    if submission is None:
        return _blocked_evidence_fulfillment_row(
            request,
            "missing",
            ["requested_evidence_submission_missing"],
        )
    blockers = _evidence_fulfillment_blockers(request, submission)
    if not submission.accepted:
        return _blocked_evidence_fulfillment_row(
            request,
            "rejected",
            ["requested_evidence_submission_rejected", *blockers],
            submission,
        )
    if blockers:
        return _blocked_evidence_fulfillment_row(
            request,
            "mismatched",
            blockers,
            submission,
        )
    if (
        request.source_integrity_required
        and submission.submitted_artifact_ref not in (verified_source_refs or set())
    ):
        return _blocked_evidence_fulfillment_row(
            request,
            "source_unverified",
            ["requested_evidence_source_integrity_unverified"],
            submission,
        )
    return ProductionSafetyQualificationEvidenceFulfillmentRow(
        request_kind=request.request_kind,
        status="fulfilled",
        area=request.area,
        threat_id=request.threat_id,
        mode_id=request.mode_id,
        submitted_artifact_kind=submission.submitted_artifact_kind,
        submitted_artifact_ref=submission.submitted_artifact_ref,
        submitted_artifact_sha256=submission.submitted_artifact_sha256,
        fulfilled=True,
    )


def _blocked_evidence_fulfillment_row(
    request: ProductionSafetyQualificationEvidenceRequestRow,
    status: Literal["missing", "mismatched", "rejected", "source_unverified"],
    blockers: list[str],
    submission: ProductionSafetyQualificationEvidenceSubmission | None = None,
) -> ProductionSafetyQualificationEvidenceFulfillmentRow:
    return ProductionSafetyQualificationEvidenceFulfillmentRow(
        request_kind=request.request_kind,
        status=status,
        area=request.area,
        threat_id=request.threat_id,
        mode_id=request.mode_id,
        submitted_artifact_kind=(
            submission.submitted_artifact_kind if submission else None
        ),
        submitted_artifact_ref=submission.submitted_artifact_ref if submission else None,
        submitted_artifact_sha256=(
            submission.submitted_artifact_sha256 if submission else None
        ),
        blockers=blockers,
    )


def _evidence_fulfillment_blockers(
    request: ProductionSafetyQualificationEvidenceRequestRow,
    submission: ProductionSafetyQualificationEvidenceSubmission,
) -> list[str]:
    blockers: list[str] = []
    if submission.submitted_artifact_kind not in request.required_artifacts:
        blockers.append("submitted_artifact_kind_not_requested")
    if request.human_review_required and not (
        submission.reviewer_ref and submission.reviewer_sha256
    ):
        blockers.append("requested_evidence_human_review_missing")
    if request.source_integrity_required and not submission.source_integrity_evidence_present:
        blockers.append("requested_evidence_source_integrity_missing")
    if request.max_age_seconds_required and not submission.max_age_metadata_present:
        blockers.append("requested_evidence_max_age_metadata_missing")
    return blockers


def _qualification_fulfillment_manifest_sha256(
    manifest: ProductionSafetyQualificationEvidenceFulfillmentManifest,
) -> str:
    return aggregate_sha256([manifest.model_dump(mode="json")])


def _qualification_dossier_manifest_sha256(
    manifest: ProductionSafetyQualificationDossierManifest,
) -> str:
    return aggregate_sha256([manifest.model_dump(mode="json")])


def _cutover_authorization_manifest_sha256(
    manifest: ProductionSafetyQualificationCutoverAuthorizationManifest,
) -> str:
    return aggregate_sha256([manifest.model_dump(mode="json")])


def _cutover_release_handoff_manifest_sha256(
    manifest: ProductionSafetyQualificationCutoverReleaseHandoffManifest,
) -> str:
    return aggregate_sha256([manifest.model_dump(mode="json")])


def _cutover_release_effect_receipt_sha256(
    receipt: ProductionSafetyQualificationCutoverReleaseEffectReceipt,
) -> str:
    return aggregate_sha256(
        [
            {
                key: value
                for key, value in receipt.model_dump(mode="json").items()
                if key != "sha256"
            }
        ]
    )


def _cutover_release_effect_manifest_sha256(
    manifest: ProductionSafetyQualificationCutoverReleaseEffectManifest,
) -> str:
    return aggregate_sha256([manifest.model_dump(mode="json")])


def _cutover_release_closure_review_sha256(
    review: ProductionSafetyQualificationCutoverReleaseClosureReview,
) -> str:
    return aggregate_sha256(
        [
            {
                key: value
                for key, value in review.model_dump(mode="json").items()
                if key != "sha256"
            }
        ]
    )


def _cutover_release_closure_manifest_sha256(
    manifest: ProductionSafetyQualificationCutoverReleaseClosureManifest,
) -> str:
    return aggregate_sha256([manifest.model_dump(mode="json")])


def _qualification_fulfillment_source_package_sha256(
    package: ProductionSafetyQualificationEvidenceFulfillmentSourcePackage,
) -> str:
    return aggregate_sha256([package.model_dump(mode="json")])


def _evidence_fulfillment_source_integrity_verified_refs(
    report: ProductionSafetyQualificationEvidenceFulfillmentSourceIntegrityReport | None,
) -> set[str] | None:
    if report is None:
        return None
    return set(report.verified_submitted_artifact_refs)


def _fulfillment_source_integrity_row(
    submission: ProductionSafetyQualificationEvidenceSubmission,
    artifact: ProductionSafetyQualificationEvidenceFulfillmentArtifact | None,
    root_path: Path | str | None,
) -> ProductionSafetyQualificationEvidenceFulfillmentSourceIntegrityRow:
    row_base = {
        "submitted_artifact_ref": submission.submitted_artifact_ref,
        "expected_sha256": submission.submitted_artifact_sha256,
    }
    if artifact is None:
        return ProductionSafetyQualificationEvidenceFulfillmentSourceIntegrityRow(
            **row_base,
            status="missing",
            blockers=["fulfillment_artifact_missing"],
        )
    if artifact.submitted_artifact_sha256 != submission.submitted_artifact_sha256:
        return ProductionSafetyQualificationEvidenceFulfillmentSourceIntegrityRow(
            **row_base,
            local_path=artifact.local_path,
            status="hash_mismatch",
            blockers=["artifact_hash_does_not_match_submission_hash"],
        )
    if (
        not artifact.redacted_or_sanitized
        or artifact.credential_material_present
        or artifact.raw_payload_present
        or artifact.safety_api_path_present
        or artifact.runtime_safety_truth_present
    ):
        return ProductionSafetyQualificationEvidenceFulfillmentSourceIntegrityRow(
            **row_base,
            local_path=artifact.local_path,
            status="sensitive_material",
            blockers=["fulfillment_artifact_contains_sensitive_or_runtime_material"],
        )
    try:
        resolved = _resolve_evidence_artifact_path(artifact.local_path, root_path)
        _assert_safe_local_evidence_path(resolved)
    except ValueError as exc:
        return ProductionSafetyQualificationEvidenceFulfillmentSourceIntegrityRow(
            **row_base,
            local_path=artifact.local_path,
            status="unsafe_path",
            blockers=[str(exc)],
        )
    if not resolved.is_file():
        return ProductionSafetyQualificationEvidenceFulfillmentSourceIntegrityRow(
            **row_base,
            local_path=str(resolved),
            status="missing",
            blockers=["fulfillment_artifact_file_missing"],
        )
    actual_sha = sha256_file(resolved)
    if actual_sha != submission.submitted_artifact_sha256:
        return ProductionSafetyQualificationEvidenceFulfillmentSourceIntegrityRow(
            **row_base,
            actual_sha256=actual_sha,
            local_path=str(resolved),
            status="hash_mismatch",
            blockers=["fulfillment_artifact_file_hash_mismatch"],
        )
    return ProductionSafetyQualificationEvidenceFulfillmentSourceIntegrityRow(
        **row_base,
        actual_sha256=actual_sha,
        local_path=str(resolved),
        status="verified",
        source_integrity_verified=True,
    )


def _unrequested_fulfillment_source_integrity_row(
    artifact: ProductionSafetyQualificationEvidenceFulfillmentArtifact,
) -> ProductionSafetyQualificationEvidenceFulfillmentSourceIntegrityRow:
    return ProductionSafetyQualificationEvidenceFulfillmentSourceIntegrityRow(
        submitted_artifact_ref=artifact.submitted_artifact_ref,
        expected_sha256=artifact.submitted_artifact_sha256,
        local_path=artifact.local_path,
        status="unrequested",
        blockers=["fulfillment_artifact_not_requested"],
    )


def _evidence_request_rows_from_gap(
    gap: ProductionSafetyQualificationGapRow,
) -> list[ProductionSafetyQualificationEvidenceRequestRow]:
    if gap.gap_kind == "area_qualification" and gap.area is not None:
        return [
            ProductionSafetyQualificationEvidenceRequestRow(
                request_kind="area_evidence_bundle",
                source_gap_kind=gap.gap_kind,
                action=gap.action,
                area=gap.area,
                required_claims=list(
                    PRODUCTION_SAFETY_QUALIFICATION_REQUIRED_CLAIMS[gap.area]
                ),
                required_artifacts=["production_qualification_evidence_bundle"],
                unblock_condition=gap.unblock_condition,
            ),
            ProductionSafetyQualificationEvidenceRequestRow(
                request_kind="area_source_package",
                source_gap_kind=gap.gap_kind,
                action=gap.action,
                area=gap.area,
                required_claims=list(
                    PRODUCTION_SAFETY_QUALIFICATION_REQUIRED_CLAIMS[gap.area]
                ),
                required_artifacts=["production_qualification_evidence_package"],
                unblock_condition=(
                    "provide sanitized local source files matching every "
                    "required area claim hash"
                ),
            ),
        ]
    if gap.gap_kind == "threat_source_integrity":
        return [
            ProductionSafetyQualificationEvidenceRequestRow(
                request_kind="threat_coverage_source_package",
                source_gap_kind=gap.gap_kind,
                action=gap.action,
                required_threats=list(REQUIRED_PRODUCTION_SAFETY_THREAT_COVERAGE),
                required_qualification_modes=list(
                    REQUIRED_PRODUCTION_SAFETY_QUALIFICATION_MODES
                ),
                required_artifacts=[
                    "production_qualification_threat_evidence_package"
                ],
                unblock_condition=gap.unblock_condition,
            )
        ]
    if gap.gap_kind == "threat_coverage" and gap.threat_id is not None:
        return [
            ProductionSafetyQualificationEvidenceRequestRow(
                request_kind="threat_coverage_case",
                source_gap_kind=gap.gap_kind,
                action=gap.action,
                threat_id=gap.threat_id,
                required_threats=[gap.threat_id],
                required_artifacts=[
                    "production_qualification_threat_case",
                    "production_qualification_threat_evidence_package",
                ],
                unblock_condition=gap.unblock_condition,
            )
        ]
    if gap.gap_kind == "qualification_mode_coverage" and gap.mode_id is not None:
        return [
            ProductionSafetyQualificationEvidenceRequestRow(
                request_kind="qualification_mode_case",
                source_gap_kind=gap.gap_kind,
                action=gap.action,
                mode_id=gap.mode_id,
                required_qualification_modes=[gap.mode_id],
                required_artifacts=[
                    "production_qualification_mode_case",
                    "production_qualification_threat_evidence_package",
                ],
                unblock_condition=gap.unblock_condition,
            )
        ]
    if gap.gap_kind == "dossier":
        return [
            ProductionSafetyQualificationEvidenceRequestRow(
                request_kind="dossier_rerun",
                source_gap_kind=gap.gap_kind,
                action=gap.action,
                required_artifacts=[
                    "production_qualification_dossier_manifest",
                    "production_qualification_dossier_report",
                ],
                unblock_condition=gap.unblock_condition,
            )
        ]
    return []


def _gap_row_from_dossier_area(
    row: ProductionSafetyQualificationDossierRow,
) -> ProductionSafetyQualificationGapRow:
    if row.status in {"missing_entry", "missing_paths", "load_failed"}:
        action: ProductionSafetyQualificationGapAction = (
            "provide_area_bundle_and_source_package"
        )
        required_artifacts = [
            "production_qualification_evidence_bundle",
            "production_qualification_evidence_package",
        ]
        unblock_condition = (
            "provide a loadable area evidence bundle and sanitized source package "
            "with every required claim"
        )
    elif row.status == "source_integrity_failed":
        action = "repair_area_source_integrity"
        required_artifacts = [
            "production_qualification_evidence_package",
            "production_qualification_source_integrity_report",
        ]
        unblock_condition = (
            "repair missing, unsafe, sensitive, or mismatched local evidence "
            "artifact hashes for this area"
        )
    else:
        action = "repair_area_claim_admission"
        required_artifacts = [
            "production_qualification_evidence_bundle",
            "production_qualification_receipt_admission",
            "production_qualification_receipt",
        ]
        unblock_condition = (
            "provide current accepted required claims and reviewed receipt refs "
            "so the area admission emits a qualified receipt"
        )
    return ProductionSafetyQualificationGapRow(
        gap_kind="area_qualification",
        action=action,
        area=row.area,
        source_status=row.status,
        blockers=row.blockers or [f"{row.area}_qualification_gap_open"],
        required_artifacts=required_artifacts,
        unblock_condition=unblock_condition,
    )


def _gap_rows_from_threat_coverage(
    report: ProductionSafetyQualificationDossierReport,
) -> list[ProductionSafetyQualificationGapRow]:
    if report.threat_coverage_audit is None:
        return [
            ProductionSafetyQualificationGapRow(
                gap_kind="dossier",
                action="provide_threat_coverage_manifest_and_source_package",
                source_status=report.threat_coverage_status,
                blockers=report.dossier_blockers
                or ["threat_coverage_manifest_missing"],
                required_artifacts=[
                    "production_qualification_threat_manifest",
                    "production_qualification_threat_evidence_package",
                ],
                unblock_condition=(
                    "provide a threat coverage manifest and sanitized source "
                    "package before rerunning the dossier"
                ),
            )
        ]
    audit = report.threat_coverage_audit
    rows: list[ProductionSafetyQualificationGapRow] = []
    if not audit.source_integrity_verified:
        rows.append(
            ProductionSafetyQualificationGapRow(
                gap_kind="threat_source_integrity",
                action="repair_threat_coverage_source_integrity",
                source_status=audit.status,
                blockers=["threat_coverage_source_integrity_unverified"],
                required_artifacts=[
                    "production_qualification_threat_evidence_package",
                    "production_qualification_threat_source_integrity_report",
                ],
                unblock_condition=(
                    "verify every threat and qualification-mode evidence ref "
                    "against sanitized local artifact hashes"
                ),
            )
        )
    for threat_id in audit.missing_threats:
        rows.append(
            _threat_gap_row(
                threat_id,
                "provide_threat_coverage_manifest_and_source_package",
                "missing",
            )
        )
    for threat_id in audit.failed_threats:
        rows.append(
            _threat_gap_row(
                threat_id,
                "repair_threat_or_mode_coverage",
                "failed",
            )
        )
    for threat_id in audit.stale_threats:
        rows.append(
            _threat_gap_row(
                threat_id,
                "refresh_stale_coverage_evidence",
                "stale",
            )
        )
    for threat_id in audit.unverified_source_threats:
        rows.append(
            _threat_gap_row(
                threat_id,
                "repair_threat_coverage_source_integrity",
                "unverified_source",
            )
        )
    for mode_id in audit.missing_qualification_modes:
        rows.append(
            _mode_gap_row(
                mode_id,
                "provide_threat_coverage_manifest_and_source_package",
                "missing",
            )
        )
    for mode_id in audit.failed_qualification_modes:
        rows.append(
            _mode_gap_row(
                mode_id,
                "repair_threat_or_mode_coverage",
                "failed",
            )
        )
    for mode_id in audit.stale_qualification_modes:
        rows.append(
            _mode_gap_row(
                mode_id,
                "refresh_stale_coverage_evidence",
                "stale",
            )
        )
    for mode_id in audit.unverified_source_qualification_modes:
        rows.append(
            _mode_gap_row(
                mode_id,
                "repair_threat_coverage_source_integrity",
                "unverified_source",
            )
        )
    return rows


def _threat_gap_row(
    threat_id: ProductionSafetyQualificationThreatId,
    action: ProductionSafetyQualificationGapAction,
    source_status: str,
) -> ProductionSafetyQualificationGapRow:
    return ProductionSafetyQualificationGapRow(
        gap_kind="threat_coverage",
        action=action,
        threat_id=threat_id,
        source_status=source_status,
        blockers=[f"{threat_id}_threat_coverage_{source_status}"],
        required_artifacts=[
            "production_qualification_threat_case",
            "production_qualification_threat_evidence_package",
        ],
        unblock_condition=(
            "provide fresh reviewed mitigation evidence and verified source "
            "integrity for this threat"
        ),
    )


def _mode_gap_row(
    mode_id: ProductionSafetyQualificationModeId,
    action: ProductionSafetyQualificationGapAction,
    source_status: str,
) -> ProductionSafetyQualificationGapRow:
    return ProductionSafetyQualificationGapRow(
        gap_kind="qualification_mode_coverage",
        action=action,
        mode_id=mode_id,
        source_status=source_status,
        blockers=[f"{mode_id}_qualification_mode_{source_status}"],
        required_artifacts=[
            "production_qualification_mode_case",
            "production_qualification_threat_evidence_package",
        ],
        unblock_condition=(
            "provide fresh reviewed passing evidence and verified source "
            "integrity for this qualification mode"
        ),
    )


def _run_dossier_threat_coverage(
    threat_coverage_path: str | None,
    *,
    evaluation_time: datetime | None,
    source_package_path: str | None,
    source_root_path: Path | str | None,
    source_integrity_output_path: Path | str | None,
    output_path: Path | str | None,
    source_path: str,
) -> tuple[
    ProductionSafetyQualificationThreatCoverageAudit | None,
    ProductionSafetyQualificationDossierThreatCoverageStatus,
    list[str],
]:
    if not threat_coverage_path:
        return None, "missing", ["threat_coverage_manifest_missing"]
    try:
        manifest = load_production_safety_qualification_threat_coverage_manifest(
            threat_coverage_path
        )
        if evaluation_time is not None:
            manifest = ProductionSafetyQualificationThreatCoverageManifest.model_validate(
                {**manifest.model_dump(), "reference_time": evaluation_time}
            )
        source_report = None
        if source_package_path:
            package = (
                load_production_safety_qualification_threat_coverage_evidence_package(
                    source_package_path
                )
            )
            source_report = (
                verify_production_safety_qualification_threat_coverage_source_integrity(
                    manifest,
                    package,
                    root_path=source_root_path,
                    source_path=f"{package.source_path}/source-integrity",
                )
            )
            if source_integrity_output_path is not None:
                source_report = (
                    write_production_safety_qualification_threat_coverage_source_integrity_report(
                        source_report,
                        source_integrity_output_path,
                    )
                )
        audit = evaluate_production_safety_qualification_threat_coverage(
            manifest,
            source_integrity_report=source_report,
            source_path=source_path,
        )
        if output_path is not None:
            audit = write_production_safety_qualification_threat_coverage_audit(
                audit,
                output_path,
            )
        if audit.ready_for_production_cutover_threat_coverage:
            return audit, audit.status, []
        return audit, audit.status, [audit.status]
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return None, "load_failed", [f"threat_coverage_load_failed:{exc}"]


def _run_dossier_area(
    index: int,
    area: ProductionSafetyQualificationArea,
    entry: ProductionSafetyQualificationDossierEntry | None,
    *,
    evaluation_time: datetime | None,
    source_root_path: Path | str | None,
    source_integrity_output_dir: Path | None,
    admission_output_dir: Path | None,
    receipt_output_dir: Path | None,
) -> tuple[ProductionSafetyQualificationDossierRow, ProductionSafetyQualificationReceipt | None]:
    if entry is None:
        return (
            ProductionSafetyQualificationDossierRow(
                area=area,
                status="missing_entry",
                blockers=[f"{area}_dossier_entry_missing"],
            ),
            None,
        )
    if not entry.bundle_path or not entry.source_package_path:
        return (
            ProductionSafetyQualificationDossierRow(
                area=area,
                status="missing_paths",
                bundle_path=entry.bundle_path,
                source_package_path=entry.source_package_path,
                blockers=[f"{area}_bundle_or_source_package_path_missing"],
            ),
            None,
        )
    try:
        bundle = load_production_safety_qualification_evidence_bundle(
            entry.bundle_path
        )
        if evaluation_time is not None:
            bundle = ProductionSafetyQualificationEvidenceBundle.model_validate(
                {**bundle.model_dump(), "reference_time": evaluation_time}
            )
        package = load_production_safety_qualification_evidence_package(
            entry.source_package_path
        )
        if bundle.area != area or package.area != area:
            raise ValueError("dossier entry area must match bundle and package area")
        source_report = verify_production_safety_qualification_source_integrity(
            bundle,
            package,
            root_path=source_root_path,
            source_path=f"{package.source_path}/source-integrity",
        )
        if source_integrity_output_dir is not None:
            source_report = write_production_safety_qualification_source_integrity_report(
                source_report,
                source_integrity_output_dir
                / _qualification_artifact_filename(
                    index,
                    area,
                    "source-integrity",
                ),
            )
        decision = evaluate_production_safety_qualification_bundle(
            bundle,
            source_integrity_report=source_report,
        )
        if admission_output_dir is not None:
            decision = write_production_safety_qualification_receipt_admission_decision(
                decision,
                admission_output_dir
                / _qualification_artifact_filename(index, area, "admission"),
            )
        receipt = decision.receipt
        if receipt_output_dir is not None:
            receipt = write_production_safety_qualification_receipt(
                receipt,
                receipt_output_dir
                / _qualification_artifact_filename(index, area, "receipt"),
            )
        if decision.ready_for_cutover_receipt:
            status: ProductionSafetyQualificationDossierRowStatus = "qualified"
            blockers: list[str] = []
        elif source_report.status != "source_integrity_verified":
            status = "source_integrity_failed"
            blockers = [source_report.status]
        else:
            status = "admission_failed"
            blockers = [decision.status]
        return (
            ProductionSafetyQualificationDossierRow(
                area=area,
                status=status,
                bundle_path=entry.bundle_path,
                source_package_path=entry.source_package_path,
                source_integrity_status=source_report.status,
                admission_status=decision.status,
                receipt_sha256=receipt.sha256,
                qualified_for_cutover=decision.ready_for_cutover_receipt,
                blockers=blockers,
            ),
            receipt,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return (
            ProductionSafetyQualificationDossierRow(
                area=area,
                status="load_failed",
                bundle_path=entry.bundle_path,
                source_package_path=entry.source_package_path,
                blockers=[str(exc)],
            ),
            None,
        )


def _threat_coverage_row(
    threat_id: ProductionSafetyQualificationThreatId,
    case: ProductionSafetyQualificationThreatCoverageCase | None,
    reference_time: datetime,
    verified_source_refs: set[str],
) -> ProductionSafetyQualificationThreatCoverageRow:
    if case is None:
        return ProductionSafetyQualificationThreatCoverageRow(
            coverage_type="threat",
            threat_id=threat_id,
            status="missing",
            blockers=[f"{threat_id}_threat_coverage_missing"],
        )
    if _qualification_coverage_case_is_stale(
        case.evidence_observed_at,
        case.max_age_seconds,
        reference_time,
    ):
        return ProductionSafetyQualificationThreatCoverageRow(
            coverage_type="threat",
            threat_id=threat_id,
            status="stale",
            evidence_ref=case.evidence_ref,
            evidence_sha256=case.evidence_sha256,
            reviewer_ref=case.reviewer_ref,
            reviewer_sha256=case.reviewer_sha256,
            blockers=[f"{threat_id}_threat_coverage_stale"],
        )
    if not case.mitigated:
        return ProductionSafetyQualificationThreatCoverageRow(
            coverage_type="threat",
            threat_id=threat_id,
            status="failed",
            evidence_ref=case.evidence_ref,
            evidence_sha256=case.evidence_sha256,
            reviewer_ref=case.reviewer_ref,
            reviewer_sha256=case.reviewer_sha256,
            blockers=[f"{threat_id}_threat_coverage_not_mitigated"],
        )
    if case.evidence_ref not in verified_source_refs:
        return ProductionSafetyQualificationThreatCoverageRow(
            coverage_type="threat",
            threat_id=threat_id,
            status="unverified_source",
            evidence_ref=case.evidence_ref,
            evidence_sha256=case.evidence_sha256,
            reviewer_ref=case.reviewer_ref,
            reviewer_sha256=case.reviewer_sha256,
            blockers=[f"{threat_id}_threat_coverage_source_unverified"],
        )
    return ProductionSafetyQualificationThreatCoverageRow(
        coverage_type="threat",
        threat_id=threat_id,
        status="covered",
        evidence_ref=case.evidence_ref,
        evidence_sha256=case.evidence_sha256,
        reviewer_ref=case.reviewer_ref,
        reviewer_sha256=case.reviewer_sha256,
        ready_for_production_qualification=True,
    )


def _qualification_mode_coverage_row(
    mode_id: ProductionSafetyQualificationModeId,
    case: ProductionSafetyQualificationModeCoverageCase | None,
    reference_time: datetime,
    verified_source_refs: set[str],
) -> ProductionSafetyQualificationThreatCoverageRow:
    if case is None:
        return ProductionSafetyQualificationThreatCoverageRow(
            coverage_type="qualification_mode",
            mode_id=mode_id,
            status="missing",
            blockers=[f"{mode_id}_qualification_mode_missing"],
        )
    if _qualification_coverage_case_is_stale(
        case.evidence_observed_at,
        case.max_age_seconds,
        reference_time,
    ):
        return ProductionSafetyQualificationThreatCoverageRow(
            coverage_type="qualification_mode",
            mode_id=mode_id,
            status="stale",
            evidence_ref=case.evidence_ref,
            evidence_sha256=case.evidence_sha256,
            reviewer_ref=case.reviewer_ref,
            reviewer_sha256=case.reviewer_sha256,
            blockers=[f"{mode_id}_qualification_mode_stale"],
        )
    if not case.passed:
        return ProductionSafetyQualificationThreatCoverageRow(
            coverage_type="qualification_mode",
            mode_id=mode_id,
            status="failed",
            evidence_ref=case.evidence_ref,
            evidence_sha256=case.evidence_sha256,
            reviewer_ref=case.reviewer_ref,
            reviewer_sha256=case.reviewer_sha256,
            blockers=[f"{mode_id}_qualification_mode_failed"],
        )
    if case.evidence_ref not in verified_source_refs:
        return ProductionSafetyQualificationThreatCoverageRow(
            coverage_type="qualification_mode",
            mode_id=mode_id,
            status="unverified_source",
            evidence_ref=case.evidence_ref,
            evidence_sha256=case.evidence_sha256,
            reviewer_ref=case.reviewer_ref,
            reviewer_sha256=case.reviewer_sha256,
            blockers=[f"{mode_id}_qualification_mode_source_unverified"],
        )
    return ProductionSafetyQualificationThreatCoverageRow(
        coverage_type="qualification_mode",
        mode_id=mode_id,
        status="covered",
        evidence_ref=case.evidence_ref,
        evidence_sha256=case.evidence_sha256,
        reviewer_ref=case.reviewer_ref,
        reviewer_sha256=case.reviewer_sha256,
        ready_for_production_qualification=True,
    )


def _qualification_coverage_case_is_stale(
    evidence_observed_at: datetime,
    max_age_seconds: int,
    reference_time: datetime,
) -> bool:
    reference = _as_utc(reference_time)
    observed = _as_utc(evidence_observed_at)
    age_seconds = (reference - observed).total_seconds()
    return age_seconds > max_age_seconds


def _threat_coverage_source_integrity_verified_refs(
    source_integrity_report: (
        ProductionSafetyQualificationThreatCoverageSourceIntegrityReport | None
    ),
) -> set[str]:
    if source_integrity_report is None:
        return set()
    return {
        row.evidence_ref
        for row in source_integrity_report.rows
        if row.source_integrity_verified
    }


def _threat_coverage_source_integrity_row(
    coverage_type: ProductionSafetyQualificationCoverageItemType,
    threat_id: ProductionSafetyQualificationThreatId | None,
    mode_id: ProductionSafetyQualificationModeId | None,
    evidence_ref: str,
    evidence_sha256: str,
    artifact: ProductionSafetyQualificationEvidenceArtifact | None,
    root_path: Path | str | None,
) -> ProductionSafetyQualificationThreatCoverageSourceIntegrityRow:
    row_base = {
        "coverage_type": coverage_type,
        "threat_id": threat_id,
        "mode_id": mode_id,
        "evidence_ref": evidence_ref,
        "expected_sha256": evidence_sha256,
    }
    if artifact is None:
        return ProductionSafetyQualificationThreatCoverageSourceIntegrityRow(
            **row_base,
            status="missing",
            blockers=["coverage_evidence_artifact_missing"],
        )
    if artifact.evidence_sha256 != evidence_sha256:
        return ProductionSafetyQualificationThreatCoverageSourceIntegrityRow(
            **row_base,
            local_path=artifact.local_path,
            status="hash_mismatch",
            blockers=["artifact_hash_does_not_match_coverage_hash"],
        )
    if (
        not artifact.redacted_or_sanitized
        or artifact.credential_material_present
        or artifact.raw_payload_present
        or artifact.safety_api_path_present
        or artifact.runtime_safety_truth_present
    ):
        return ProductionSafetyQualificationThreatCoverageSourceIntegrityRow(
            **row_base,
            local_path=artifact.local_path,
            status="sensitive_material",
            blockers=["coverage_artifact_contains_sensitive_or_runtime_material"],
        )
    try:
        resolved = _resolve_evidence_artifact_path(artifact.local_path, root_path)
        _assert_safe_local_evidence_path(resolved)
    except ValueError as exc:
        return ProductionSafetyQualificationThreatCoverageSourceIntegrityRow(
            **row_base,
            local_path=artifact.local_path,
            status="unsafe_path",
            blockers=[str(exc)],
        )
    if not resolved.is_file():
        return ProductionSafetyQualificationThreatCoverageSourceIntegrityRow(
            **row_base,
            local_path=str(resolved),
            status="missing",
            blockers=["coverage_evidence_artifact_file_missing"],
        )
    actual_sha = sha256_file(resolved)
    if actual_sha != evidence_sha256:
        return ProductionSafetyQualificationThreatCoverageSourceIntegrityRow(
            **row_base,
            actual_sha256=actual_sha,
            local_path=str(resolved),
            status="hash_mismatch",
            blockers=["coverage_evidence_artifact_file_hash_mismatch"],
        )
    return ProductionSafetyQualificationThreatCoverageSourceIntegrityRow(
        **row_base,
        actual_sha256=actual_sha,
        local_path=str(resolved),
        status="verified",
        source_integrity_verified=True,
    )


def _ordered_unique_areas(
    areas: list[ProductionSafetyQualificationArea],
) -> list[ProductionSafetyQualificationArea]:
    present = set(areas)
    return [area for area in REQUIRED_PRODUCTION_SAFETY_QUALIFICATION_AREAS if area in present]


def _missing_required_receipt_refs(
    bundle: ProductionSafetyQualificationEvidenceBundle,
) -> list[str]:
    missing = []
    for field_name, ref_value, sha_value in (
        ("qualification_ref", bundle.qualification_ref, bundle.qualification_sha256),
        (
            "reviewed_effect_boundary_ref",
            bundle.reviewed_effect_boundary_ref,
            bundle.reviewed_effect_boundary_sha256,
        ),
        ("operator_review_ref", bundle.operator_review_ref, bundle.operator_review_sha256),
    ):
        if ref_value is None or sha_value is None:
            missing.append(field_name)
    return missing


def _claim_is_stale(
    claim: ProductionSafetyQualificationEvidenceClaim,
    reference_time: datetime,
) -> bool:
    reference = _as_utc(reference_time)
    observed = _as_utc(claim.evidence_observed_at)
    age_seconds = (reference - observed).total_seconds()
    return age_seconds > claim.max_age_seconds


def _source_integrity_verified_claim_ids(
    source_integrity_report: ProductionSafetyQualificationSourceIntegrityReport | None,
) -> set[ProductionSafetyQualificationClaimId]:
    if source_integrity_report is None:
        return set()
    return {
        row.claim_id
        for row in source_integrity_report.rows
        if row.source_integrity_verified
    }


def _source_integrity_row(
    claim: ProductionSafetyQualificationEvidenceClaim,
    artifact: ProductionSafetyQualificationEvidenceArtifact | None,
    root_path: Path | str | None,
) -> ProductionSafetyQualificationSourceIntegrityRow:
    if artifact is None:
        return ProductionSafetyQualificationSourceIntegrityRow(
            claim_id=claim.claim_id,
            evidence_ref=claim.evidence_ref,
            expected_sha256=claim.evidence_sha256,
            status="missing",
            blockers=["evidence_artifact_missing"],
        )
    if artifact.evidence_sha256 != claim.evidence_sha256:
        return ProductionSafetyQualificationSourceIntegrityRow(
            claim_id=claim.claim_id,
            evidence_ref=claim.evidence_ref,
            expected_sha256=claim.evidence_sha256,
            local_path=artifact.local_path,
            status="hash_mismatch",
            blockers=["artifact_hash_does_not_match_claim_hash"],
        )
    if (
        not artifact.redacted_or_sanitized
        or artifact.credential_material_present
        or artifact.raw_payload_present
        or artifact.safety_api_path_present
        or artifact.runtime_safety_truth_present
    ):
        return ProductionSafetyQualificationSourceIntegrityRow(
            claim_id=claim.claim_id,
            evidence_ref=claim.evidence_ref,
            expected_sha256=claim.evidence_sha256,
            local_path=artifact.local_path,
            status="sensitive_material",
            blockers=["evidence_artifact_contains_sensitive_or_runtime_material"],
        )
    try:
        resolved = _resolve_evidence_artifact_path(artifact.local_path, root_path)
        _assert_safe_local_evidence_path(resolved)
    except ValueError as exc:
        return ProductionSafetyQualificationSourceIntegrityRow(
            claim_id=claim.claim_id,
            evidence_ref=claim.evidence_ref,
            expected_sha256=claim.evidence_sha256,
            local_path=artifact.local_path,
            status="unsafe_path",
            blockers=[str(exc)],
        )
    if not resolved.is_file():
        return ProductionSafetyQualificationSourceIntegrityRow(
            claim_id=claim.claim_id,
            evidence_ref=claim.evidence_ref,
            expected_sha256=claim.evidence_sha256,
            local_path=str(resolved),
            status="missing",
            blockers=["evidence_artifact_file_missing"],
        )
    actual_sha = sha256_file(resolved)
    if actual_sha != claim.evidence_sha256:
        return ProductionSafetyQualificationSourceIntegrityRow(
            claim_id=claim.claim_id,
            evidence_ref=claim.evidence_ref,
            expected_sha256=claim.evidence_sha256,
            actual_sha256=actual_sha,
            local_path=str(resolved),
            status="hash_mismatch",
            blockers=["evidence_artifact_file_hash_mismatch"],
        )
    return ProductionSafetyQualificationSourceIntegrityRow(
        claim_id=claim.claim_id,
        evidence_ref=claim.evidence_ref,
        expected_sha256=claim.evidence_sha256,
        actual_sha256=actual_sha,
        local_path=str(resolved),
        status="verified",
        source_integrity_verified=True,
    )


def _resolve_evidence_artifact_path(
    local_path: str,
    root_path: Path | str | None,
) -> Path:
    path = Path(local_path).expanduser()
    root = Path(root_path).expanduser().resolve() if root_path is not None else None
    resolved = path.resolve() if path.is_absolute() else (root or Path.cwd()).joinpath(path).resolve()
    if root is not None and not resolved.is_relative_to(root):
        raise ValueError("evidence artifact path must stay under root_path")
    return resolved


def _assert_safe_local_evidence_path(path: Path) -> None:
    lowered_parts = [part.lower() for part in path.parts]
    if path.name == ".env" or path.suffix.lower() in {".pem", ".key", ".p12", ".pfx"}:
        raise ValueError("evidence artifact path cannot target credential material")
    if any(
        part in {".ssh", "secret", "secrets", "credential", "credentials", "keychain"}
        for part in lowered_parts
    ):
        raise ValueError("evidence artifact path cannot target credential directories")


def _qualification_receipt_from_bundle(
    bundle: ProductionSafetyQualificationEvidenceBundle,
    *,
    status: ProductionSafetyQualificationReceiptStatus,
    accepted_claims: list[ProductionSafetyQualificationClaimId],
    missing_claims: list[ProductionSafetyQualificationClaimId],
    rejected_claims: list[ProductionSafetyQualificationClaimId],
    stale_claims: list[ProductionSafetyQualificationClaimId],
    unverified_source_claims: list[ProductionSafetyQualificationClaimId],
    missing_required_refs: list[str],
) -> ProductionSafetyQualificationReceipt:
    accepted = set(accepted_claims)
    notes = [
        *bundle.notes,
        *[f"missing_required_claim:{claim_id}" for claim_id in missing_claims],
        *[f"rejected_required_claim:{claim_id}" for claim_id in rejected_claims],
        *[f"stale_required_claim:{claim_id}" for claim_id in stale_claims],
        *[
            f"unverified_source_claim:{claim_id}"
            for claim_id in unverified_source_claims
        ],
        *[f"missing_required_ref:{ref_name}" for ref_name in missing_required_refs],
    ]
    receipt_payload = {
        "area": bundle.area,
        "source_provider": bundle.source_provider,
        "source_path": bundle.source_path,
        "status": status,
        "qualification_ref": bundle.qualification_ref,
        "qualification_sha256": bundle.qualification_sha256,
        "reviewed_effect_boundary_ref": bundle.reviewed_effect_boundary_ref,
        "reviewed_effect_boundary_sha256": bundle.reviewed_effect_boundary_sha256,
        "operator_review_ref": bundle.operator_review_ref,
        "operator_review_sha256": bundle.operator_review_sha256,
        "capability_observed": "capability_observed" in accepted,
        "production_environment_verified": "production_environment_verified"
        in accepted,
        "lineage_verified": "lineage_verified" in accepted,
        "fail_closed_behavior_verified": "fail_closed_behavior_verified" in accepted,
        "rollback_or_fallback_verified": "rollback_or_fallback_verified" in accepted,
        "credential_material_embedded": bundle.credential_material_embedded,
        "raw_payload_embedded": bundle.raw_payload_embedded,
        "safety_api_called_by_qualifier": bundle.safety_api_called_by_admission,
        "phase1_l0_l4_state_mutated_by_qualifier": (
            bundle.phase1_l0_l4_state_mutated_by_admission
        ),
        "runtime_safety_truth_mutated_by_qualifier": (
            bundle.runtime_safety_truth_mutated_by_admission
        ),
        "notes": notes,
    }
    receipt = ProductionSafetyQualificationReceipt(**receipt_payload)
    return ProductionSafetyQualificationReceipt(
        **{
            **receipt.model_dump(mode="json"),
            "sha256": _qualification_receipt_sha256(receipt),
        }
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _qualification_receipt_sha256(
    receipt: ProductionSafetyQualificationReceipt,
) -> str:
    return aggregate_sha256(
        [
            {
                key: value
                for key, value in receipt.model_dump(mode="json").items()
                if key != "sha256"
            }
        ]
    )


def _assert_qualification_ref(field_name: str, value: str) -> None:
    if "/safety/" in value:
        raise ValueError(f"{field_name} cannot reference a safety API path")
    if not value.startswith(_QUALIFICATION_REF_PREFIXES):
        raise ValueError(f"{field_name} must use a production qualification reference")
    if field_name == "source_path" and value.startswith("inline:"):
        raise ValueError("production qualification source_path cannot be inline")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)


def _qualification_artifact_filename(
    index: int,
    area: ProductionSafetyQualificationArea,
    suffix: str,
) -> str:
    return f"{index:02d}-{area}-{suffix}.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scout production safety cutover readiness audit"
    )
    parser.add_argument(
        "--receipt",
        action="append",
        default=[],
        help="Path to a production safety qualification receipt JSON file.",
    )
    parser.add_argument(
        "--dossier",
        help="Path to a production safety qualification dossier manifest JSON file.",
    )
    parser.add_argument(
        "--dossier-output",
        help="Optional path for the production safety qualification dossier report.",
    )
    parser.add_argument(
        "--evaluation-time",
        help=(
            "Timezone-aware ISO timestamp for dossier or dossier-rerun evaluation. "
            "Defaults to current UTC. Use an explicit timestamp for historical replay; "
            "evidence observation times are never changed."
        ),
    )
    parser.add_argument(
        "--gap-plan",
        help="Path to a production safety qualification dossier report JSON file.",
    )
    parser.add_argument(
        "--gap-plan-output",
        help="Optional path for the production safety qualification gap plan.",
    )
    parser.add_argument(
        "--evidence-request-pack",
        help="Path to a production safety qualification gap plan JSON file.",
    )
    parser.add_argument(
        "--evidence-request-output",
        help="Optional path for the production safety evidence request pack.",
    )
    parser.add_argument(
        "--evidence-fulfillment-request-pack",
        help="Path to a production safety evidence request pack JSON file.",
    )
    parser.add_argument(
        "--evidence-fulfillment-manifest",
        help="Path to a production safety evidence fulfillment manifest JSON file.",
    )
    parser.add_argument(
        "--evidence-fulfillment-source-package",
        help=(
            "Optional sanitized source package for submitted fulfillment "
            "artifacts."
        ),
    )
    parser.add_argument(
        "--evidence-fulfillment-source-integrity-output",
        help=(
            "Optional path for the evidence fulfillment source-integrity "
            "report."
        ),
    )
    parser.add_argument(
        "--evidence-fulfillment-output",
        help="Optional path for the production safety evidence fulfillment report.",
    )
    parser.add_argument(
        "--remediation-gap-plan",
        help="Path to a production safety qualification gap plan JSON file.",
    )
    parser.add_argument(
        "--remediation-request-pack",
        help="Path to a production safety evidence request pack JSON file.",
    )
    parser.add_argument(
        "--remediation-fulfillment-report",
        help="Path to a production safety evidence fulfillment report JSON file.",
    )
    parser.add_argument(
        "--remediation-output",
        help="Optional path for the production safety remediation readiness report.",
    )
    parser.add_argument(
        "--external-action-remediation",
        help=(
            "Path to a production safety remediation readiness report used to "
            "build an external qualification action packet."
        ),
    )
    parser.add_argument(
        "--external-action-output",
        help="Optional path for the external qualification action packet.",
    )
    parser.add_argument(
        "--external-authorization-packet",
        help=(
            "Path to an external qualification action packet awaiting "
            "operator authorization."
        ),
    )
    parser.add_argument(
        "--external-authorization-manifest",
        help="Path to an external qualification operator authorization manifest.",
    )
    parser.add_argument(
        "--external-authorization-output",
        help="Optional path for the external qualification authorization report.",
    )
    parser.add_argument(
        "--external-invocation-authorization-report",
        help=(
            "Path to an external qualification authorization report used before "
            "building a separate executor handoff."
        ),
    )
    parser.add_argument(
        "--external-invocation-manifest",
        help="Path to an external qualification executor invocation manifest.",
    )
    parser.add_argument(
        "--external-invocation-output",
        help="Optional path for the external qualification invocation guard report.",
    )
    parser.add_argument(
        "--external-result-invocation-report",
        help=(
            "Path to an external qualification invocation guard report used to "
            "intake separate executor result receipts."
        ),
    )
    parser.add_argument(
        "--external-result-manifest",
        help="Path to an external qualification result receipt manifest.",
    )
    parser.add_argument(
        "--external-result-output",
        help="Optional path for the external qualification result intake report.",
    )
    parser.add_argument(
        "--external-result-bridge-request-pack",
        help=(
            "Path to a production safety evidence request pack used to bridge "
            "external results back into fulfillment intake."
        ),
    )
    parser.add_argument(
        "--external-result-bridge-report",
        help="Path to an external qualification result intake report.",
    )
    parser.add_argument(
        "--external-result-bridge-output",
        help="Optional path for the external result evidence bridge report.",
    )
    parser.add_argument(
        "--external-result-bridge-fulfillment-output",
        help=(
            "Optional path for the bridged evidence fulfillment manifest when "
            "the bridge is ready."
        ),
    )
    parser.add_argument(
        "--external-result-closure-gap-plan",
        help="Path to the production safety qualification gap plan for closure.",
    )
    parser.add_argument(
        "--external-result-closure-request-pack",
        help="Path to the evidence request pack for external result closure.",
    )
    parser.add_argument(
        "--external-result-closure-bridge-report",
        help="Path to the external result evidence bridge report for closure.",
    )
    parser.add_argument(
        "--external-result-closure-source-package",
        help=(
            "Optional sanitized source package for the bridged fulfillment "
            "artifacts."
        ),
    )
    parser.add_argument(
        "--external-result-closure-output",
        help="Optional path for the external result remediation closure report.",
    )
    parser.add_argument(
        "--dossier-rerun-closure-report",
        help=(
            "Path to an external result remediation closure report used before "
            "a local dossier rerun."
        ),
    )
    parser.add_argument(
        "--dossier-rerun-manifest",
        help="Path to the production safety qualification dossier manifest to rerun.",
    )
    parser.add_argument(
        "--dossier-rerun-output",
        help="Optional path for the production safety dossier rerun report.",
    )
    parser.add_argument(
        "--cutover-authorization-dossier-rerun-report",
        help=(
            "Path to a production safety dossier rerun report used before "
            "cutover authorization intake."
        ),
    )
    parser.add_argument(
        "--cutover-authorization-manifest",
        help="Path to a production safety cutover authorization manifest.",
    )
    parser.add_argument(
        "--cutover-authorization-output",
        help="Optional path for the cutover authorization report.",
    )
    parser.add_argument(
        "--cutover-release-authorization-report",
        help=(
            "Path to a cutover authorization report used before release "
            "handoff intake."
        ),
    )
    parser.add_argument(
        "--cutover-release-handoff-manifest",
        help="Path to a production safety cutover release handoff manifest.",
    )
    parser.add_argument(
        "--cutover-release-handoff-output",
        help="Optional path for the cutover release handoff report.",
    )
    parser.add_argument(
        "--cutover-release-effect-handoff-report",
        help=(
            "Path to a cutover release handoff report used before release "
            "effect receipt intake."
        ),
    )
    parser.add_argument(
        "--cutover-release-effect-manifest",
        help="Path to a production safety cutover release effect manifest.",
    )
    parser.add_argument(
        "--cutover-release-effect-output",
        help="Optional path for the cutover release effect report.",
    )
    parser.add_argument(
        "--cutover-release-closure-effect-report",
        help=(
            "Path to a cutover release effect report used before release "
            "closure review."
        ),
    )
    parser.add_argument(
        "--cutover-release-closure-manifest",
        help="Path to a production safety cutover release closure manifest.",
    )
    parser.add_argument(
        "--cutover-release-closure-output",
        help="Optional path for the cutover release closure report.",
    )
    parser.add_argument(
        "--threat-coverage",
        help="Path to a production safety qualification threat coverage manifest.",
    )
    parser.add_argument(
        "--threat-coverage-source-package",
        help="Path to a sanitized threat coverage source-integrity package.",
    )
    parser.add_argument(
        "--threat-coverage-output",
        help="Optional path for the production safety threat coverage audit.",
    )
    parser.add_argument(
        "--bundle",
        action="append",
        default=[],
        help="Path to an area-specific qualification evidence bundle JSON file.",
    )
    parser.add_argument(
        "--source-package",
        action="append",
        default=[],
        help="Path to a sanitized local source-integrity evidence package JSON file.",
    )
    parser.add_argument(
        "--source-root",
        help="Optional root directory used to resolve relative evidence artifact paths.",
    )
    parser.add_argument(
        "--output",
        help="Optional path for the cutover readiness audit JSON artifact.",
    )
    parser.add_argument(
        "--source-integrity-output-dir",
        help="Optional directory for qualification source-integrity reports.",
    )
    parser.add_argument(
        "--admission-output-dir",
        help="Optional directory for qualification receipt admission decisions.",
    )
    parser.add_argument(
        "--receipt-output-dir",
        help="Optional directory for receipts emitted from admitted evidence bundles.",
    )
    parser.add_argument(
        "--source-path",
        default="inline:production-safety-cutover-readiness-cli",
        help="Source path recorded in the generated audit artifact.",
    )
    args = parser.parse_args(argv)
    evaluation_time = None
    if args.dossier or args.dossier_rerun_closure_report or args.dossier_rerun_manifest:
        try:
            evaluation_time = (
                datetime.fromisoformat(args.evaluation_time)
                if args.evaluation_time is not None
                else datetime.now(timezone.utc)
            )
            if evaluation_time.utcoffset() is None:
                raise ValueError("evaluation time must be timezone-aware")
        except ValueError:
            parser.error("--evaluation-time must be a timezone-aware ISO timestamp")
    elif args.evaluation_time is not None:
        parser.error("--evaluation-time requires --dossier or dossier-rerun inputs")
    if args.dossier:
        report = run_production_safety_qualification_dossier(
            args.dossier,
            evaluation_time=evaluation_time,
            output_path=args.dossier_output,
            cutover_audit_output_path=args.output,
            threat_coverage_output_path=args.threat_coverage_output,
            source_integrity_output_dir=args.source_integrity_output_dir,
            admission_output_dir=args.admission_output_dir,
            receipt_output_dir=args.receipt_output_dir,
            source_path=args.source_path,
        )
        if args.dossier_output is None:
            print(
                json.dumps(
                    report.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
        return 0
    if args.gap_plan:
        plan = evaluate_production_safety_qualification_gap_plan(
            args.gap_plan,
            source_path=args.source_path,
        )
        if args.gap_plan_output is not None:
            write_production_safety_qualification_gap_plan(
                plan,
                args.gap_plan_output,
            )
        else:
            print(
                json.dumps(
                    plan.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
        return 0
    if args.evidence_request_pack:
        pack = build_production_safety_qualification_evidence_request_pack(
            args.evidence_request_pack,
            source_path=args.source_path,
        )
        if args.evidence_request_output is not None:
            write_production_safety_qualification_evidence_request_pack(
                pack,
                args.evidence_request_output,
            )
        else:
            print(
                json.dumps(
                    pack.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
        return 0
    if args.evidence_fulfillment_manifest:
        if not args.evidence_fulfillment_request_pack:
            parser.error(
                "--evidence-fulfillment-manifest requires "
                "--evidence-fulfillment-request-pack"
            )
        source_report = None
        if args.evidence_fulfillment_source_package:
            source_report = (
                verify_production_safety_qualification_evidence_fulfillment_source_integrity(
                    args.evidence_fulfillment_manifest,
                    args.evidence_fulfillment_source_package,
                    root_path=args.source_root,
                )
            )
            if args.evidence_fulfillment_source_integrity_output is not None:
                source_report = (
                    write_production_safety_qualification_evidence_fulfillment_source_integrity_report(
                        source_report,
                        args.evidence_fulfillment_source_integrity_output,
                    )
                )
        report = evaluate_production_safety_qualification_evidence_fulfillment(
            args.evidence_fulfillment_request_pack,
            args.evidence_fulfillment_manifest,
            source_integrity_report=source_report,
            source_path=args.source_path,
        )
        if args.evidence_fulfillment_output is not None:
            write_production_safety_qualification_evidence_fulfillment_report(
                report,
                args.evidence_fulfillment_output,
            )
        else:
            print(
                json.dumps(
                    report.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
        return 0
    if args.remediation_gap_plan:
        if not args.remediation_request_pack or not args.remediation_fulfillment_report:
            parser.error(
                "--remediation-gap-plan requires --remediation-request-pack "
                "and --remediation-fulfillment-report"
            )
        remediation = evaluate_production_safety_qualification_remediation_readiness(
            args.remediation_gap_plan,
            args.remediation_request_pack,
            args.remediation_fulfillment_report,
            source_path=args.source_path,
        )
        if args.remediation_output is not None:
            write_production_safety_qualification_remediation_readiness_report(
                remediation,
                args.remediation_output,
            )
        else:
            print(
                json.dumps(
                    remediation.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
        return 0
    if args.external_action_remediation:
        packet = build_production_safety_qualification_external_action_packet(
            args.external_action_remediation,
            source_path=args.source_path,
        )
        if args.external_action_output is not None:
            write_production_safety_qualification_external_action_packet(
                packet,
                args.external_action_output,
            )
        else:
            print(
                json.dumps(
                    packet.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
        return 0
    if args.external_authorization_packet or args.external_authorization_manifest:
        if not args.external_authorization_packet or not args.external_authorization_manifest:
            parser.error(
                "--external-authorization-packet requires "
                "--external-authorization-manifest"
            )
        authorization_report = (
            evaluate_production_safety_qualification_external_authorization(
                args.external_authorization_packet,
                args.external_authorization_manifest,
                source_path=args.source_path,
            )
        )
        if args.external_authorization_output is not None:
            write_production_safety_qualification_external_authorization_report(
                authorization_report,
                args.external_authorization_output,
            )
        else:
            print(
                json.dumps(
                    authorization_report.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
        return 0
    if args.external_invocation_authorization_report or args.external_invocation_manifest:
        if (
            not args.external_invocation_authorization_report
            or not args.external_invocation_manifest
        ):
            parser.error(
                "--external-invocation-authorization-report requires "
                "--external-invocation-manifest"
            )
        invocation_report = (
            evaluate_production_safety_qualification_external_invocation(
                args.external_invocation_authorization_report,
                args.external_invocation_manifest,
                source_path=args.source_path,
            )
        )
        if args.external_invocation_output is not None:
            write_production_safety_qualification_external_invocation_report(
                invocation_report,
                args.external_invocation_output,
            )
        else:
            print(
                json.dumps(
                    invocation_report.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
        return 0
    if args.external_result_invocation_report or args.external_result_manifest:
        if not args.external_result_invocation_report or not args.external_result_manifest:
            parser.error(
                "--external-result-invocation-report requires "
                "--external-result-manifest"
            )
        result_report = evaluate_production_safety_qualification_external_result_intake(
            args.external_result_invocation_report,
            args.external_result_manifest,
            source_path=args.source_path,
        )
        if args.external_result_output is not None:
            write_production_safety_qualification_external_result_report(
                result_report,
                args.external_result_output,
            )
        else:
            print(
                json.dumps(
                    result_report.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
        )
        return 0
    if args.external_result_bridge_request_pack or args.external_result_bridge_report:
        if (
            not args.external_result_bridge_request_pack
            or not args.external_result_bridge_report
        ):
            parser.error(
                "--external-result-bridge-request-pack requires "
                "--external-result-bridge-report"
            )
        bridge_report = build_production_safety_qualification_evidence_fulfillment_manifest_from_external_results(
            args.external_result_bridge_request_pack,
            args.external_result_bridge_report,
            source_path=args.source_path,
        )
        if (
            args.external_result_bridge_fulfillment_output is not None
            and bridge_report.fulfillment_manifest is not None
        ):
            write_production_safety_qualification_evidence_fulfillment_manifest(
                bridge_report.fulfillment_manifest,
                args.external_result_bridge_fulfillment_output,
            )
        if args.external_result_bridge_output is not None:
            write_production_safety_qualification_external_result_evidence_bridge_report(
                bridge_report,
                args.external_result_bridge_output,
            )
        else:
            print(
                json.dumps(
                    bridge_report.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
        )
        return 0
    if (
        args.external_result_closure_gap_plan
        or args.external_result_closure_request_pack
        or args.external_result_closure_bridge_report
        or args.external_result_closure_source_package
    ):
        if (
            not args.external_result_closure_gap_plan
            or not args.external_result_closure_request_pack
            or not args.external_result_closure_bridge_report
        ):
            parser.error(
                "--external-result-closure-gap-plan requires "
                "--external-result-closure-request-pack and "
                "--external-result-closure-bridge-report"
            )
        closure_report = (
            evaluate_production_safety_qualification_external_result_remediation_closure(
                args.external_result_closure_gap_plan,
                args.external_result_closure_request_pack,
                args.external_result_closure_bridge_report,
                args.external_result_closure_source_package,
                root_path=args.source_root,
                source_path=args.source_path,
            )
        )
        if args.external_result_closure_output is not None:
            write_production_safety_qualification_external_result_remediation_closure_report(
                closure_report,
                args.external_result_closure_output,
            )
        else:
            print(
                json.dumps(
                    closure_report.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
        return 0
    if args.dossier_rerun_closure_report or args.dossier_rerun_manifest:
        if not args.dossier_rerun_closure_report or not args.dossier_rerun_manifest:
            parser.error(
                "--dossier-rerun-closure-report requires "
                "--dossier-rerun-manifest"
            )
        rerun_report = evaluate_production_safety_qualification_dossier_rerun_intake(
            args.dossier_rerun_closure_report,
            args.dossier_rerun_manifest,
            evaluation_time=evaluation_time,
            cutover_audit_output_path=args.output,
            threat_coverage_output_path=args.threat_coverage_output,
            source_integrity_output_dir=args.source_integrity_output_dir,
            admission_output_dir=args.admission_output_dir,
            receipt_output_dir=args.receipt_output_dir,
            source_path=args.source_path,
        )
        if args.dossier_rerun_output is not None:
            write_production_safety_qualification_dossier_rerun_report(
                rerun_report,
                args.dossier_rerun_output,
            )
        else:
            print(
                json.dumps(
                    rerun_report.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
        return 0
    if (
        args.cutover_authorization_dossier_rerun_report
        or args.cutover_authorization_manifest
    ):
        if (
            not args.cutover_authorization_dossier_rerun_report
            or not args.cutover_authorization_manifest
        ):
            parser.error(
                "--cutover-authorization-dossier-rerun-report requires "
                "--cutover-authorization-manifest"
            )
        authorization_report = (
            evaluate_production_safety_qualification_cutover_authorization(
                args.cutover_authorization_dossier_rerun_report,
                args.cutover_authorization_manifest,
                source_path=args.source_path,
            )
        )
        if args.cutover_authorization_output is not None:
            write_production_safety_qualification_cutover_authorization_report(
                authorization_report,
                args.cutover_authorization_output,
            )
        else:
            print(
                json.dumps(
                    authorization_report.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
        return 0
    if (
        args.cutover_release_authorization_report
        or args.cutover_release_handoff_manifest
    ):
        if (
            not args.cutover_release_authorization_report
            or not args.cutover_release_handoff_manifest
        ):
            parser.error(
                "--cutover-release-authorization-report requires "
                "--cutover-release-handoff-manifest"
            )
        handoff_report = (
            evaluate_production_safety_qualification_cutover_release_handoff(
                args.cutover_release_authorization_report,
                args.cutover_release_handoff_manifest,
                source_path=args.source_path,
            )
        )
        if args.cutover_release_handoff_output is not None:
            write_production_safety_qualification_cutover_release_handoff_report(
                handoff_report,
                args.cutover_release_handoff_output,
            )
        else:
            print(
                json.dumps(
                    handoff_report.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
        return 0
    if (
        args.cutover_release_effect_handoff_report
        or args.cutover_release_effect_manifest
    ):
        if (
            not args.cutover_release_effect_handoff_report
            or not args.cutover_release_effect_manifest
        ):
            parser.error(
                "--cutover-release-effect-handoff-report requires "
                "--cutover-release-effect-manifest"
            )
        effect_report = (
            evaluate_production_safety_qualification_cutover_release_effect_intake(
                args.cutover_release_effect_handoff_report,
                args.cutover_release_effect_manifest,
                source_path=args.source_path,
            )
        )
        if args.cutover_release_effect_output is not None:
            write_production_safety_qualification_cutover_release_effect_report(
                effect_report,
                args.cutover_release_effect_output,
            )
        else:
            print(
                json.dumps(
                    effect_report.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
        return 0
    if (
        args.cutover_release_closure_effect_report
        or args.cutover_release_closure_manifest
    ):
        if (
            not args.cutover_release_closure_effect_report
            or not args.cutover_release_closure_manifest
        ):
            parser.error(
                "--cutover-release-closure-effect-report requires "
                "--cutover-release-closure-manifest"
            )
        closure_report = (
            evaluate_production_safety_qualification_cutover_release_closure(
                args.cutover_release_closure_effect_report,
                args.cutover_release_closure_manifest,
                source_path=args.source_path,
            )
        )
        if args.cutover_release_closure_output is not None:
            write_production_safety_qualification_cutover_release_closure_report(
                closure_report,
                args.cutover_release_closure_output,
            )
        else:
            print(
                json.dumps(
                    closure_report.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
        return 0
    if args.threat_coverage:
        source_report = None
        manifest = load_production_safety_qualification_threat_coverage_manifest(
            args.threat_coverage
        )
        if args.threat_coverage_source_package:
            package = (
                load_production_safety_qualification_threat_coverage_evidence_package(
                    args.threat_coverage_source_package
                )
            )
            source_report = (
                verify_production_safety_qualification_threat_coverage_source_integrity(
                    manifest,
                    package,
                    root_path=args.source_root,
                    source_path=f"{package.source_path}/source-integrity",
                )
            )
            if args.source_integrity_output_dir:
                source_report = (
                    write_production_safety_qualification_threat_coverage_source_integrity_report(
                        source_report,
                        Path(args.source_integrity_output_dir)
                        / "00-threat-coverage-source-integrity.json",
                    )
                )
        audit = evaluate_production_safety_qualification_threat_coverage(
            manifest,
            source_integrity_report=source_report,
            source_path=args.source_path,
        )
        if args.threat_coverage_output is not None:
            write_production_safety_qualification_threat_coverage_audit(
                audit,
                args.threat_coverage_output,
            )
        else:
            print(
                json.dumps(
                    audit.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
        return 0
    decisions = run_production_safety_qualification_bundle_admission(
        args.bundle,
        source_package_paths=args.source_package,
        source_root_path=args.source_root,
        source_integrity_output_dir=args.source_integrity_output_dir,
        admission_output_dir=args.admission_output_dir,
        receipt_output_dir=args.receipt_output_dir,
    )
    if args.bundle and args.output is None:
        print(
            json.dumps(
                [decision.model_dump(mode="json") for decision in decisions],
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    receipts = [
        *load_production_safety_qualification_receipts(args.receipt),
        *[decision.receipt for decision in decisions],
    ]
    audit = evaluate_production_safety_cutover_readiness(
        receipts,
        source_path=args.source_path,
    )
    if args.output is not None:
        write_production_safety_cutover_readiness_audit(audit, args.output)
    else:
        print(
            json.dumps(
                audit.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
