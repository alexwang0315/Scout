from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RuntimeRemoteProviderPolicyModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuntimeRemoteProviderKind(StrEnum):
    WEBHOOK_TELEGRAM_LIKE = "webhook_telegram_like"


class RuntimeRemoteMessageClass(StrEnum):
    REMOTE_STATUS = "remote_status"
    CHECKIN = "checkin"
    INCIDENT_ALERT = "incident_alert"
    SOS = "sos"


class RuntimeRemoteProviderDecisionStatus(StrEnum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"


class RuntimeRemoteProviderEndpointPolicy(RuntimeRemoteProviderPolicyModel):
    endpoint_ref: str = "provider_endpoint.webhook_telegram_like.v0"
    raw_url_embedded: Literal[False] = False
    arbitrary_url_input_allowed: Literal[False] = False
    endpoint_secret_ref_required: Literal[True] = True


class RuntimeRemoteProviderAuthPolicy(RuntimeRemoteProviderPolicyModel):
    auth_method: Literal["secret_ref_bearer_token_or_hmac_signature"] = (
        "secret_ref_bearer_token_or_hmac_signature"
    )
    secret_ref_required: Literal[True] = True
    token_value_embedded: Literal[False] = False
    signature_supported: Literal[True] = True


class RuntimeRemoteRecipientPolicy(RuntimeRemoteProviderPolicyModel):
    allowed_recipient_refs: list[str] = Field(
        default_factory=lambda: ["remote_contact.primary", "remote_contact.backup"],
        min_length=1,
    )
    arbitrary_recipient_input_allowed: Literal[False] = False
    reviewed_contact_ref_required: Literal[True] = True


class RuntimeRemoteMessageClassPolicy(RuntimeRemoteProviderPolicyModel):
    allowed_message_classes: list[RuntimeRemoteMessageClass] = Field(
        default_factory=lambda: [
            RuntimeRemoteMessageClass.REMOTE_STATUS,
            RuntimeRemoteMessageClass.CHECKIN,
            RuntimeRemoteMessageClass.INCIDENT_ALERT,
        ],
        min_length=1,
    )
    blocked_message_classes: list[RuntimeRemoteMessageClass] = Field(
        default_factory=lambda: [RuntimeRemoteMessageClass.SOS],
        min_length=1,
    )
    incident_alert_allowed_levels: list[str] = Field(
        default_factory=lambda: ["L2_CONCERN", "L3_EMERGENCY"],
        min_length=1,
    )
    incident_alert_requires_noise_reduction_policy: Literal[True] = True
    sos_true_send_implemented: Literal[False] = False


class RuntimeRemoteCancellationPolicy(RuntimeRemoteProviderPolicyModel):
    provider_cancellation_supported: Literal[False] = False
    followup_correction_allowed: Literal[True] = True
    cancellation_semantics: Literal["cancel_request_or_correction_only"] = (
        "cancel_request_or_correction_only"
    )


class RuntimeRemoteFailurePolicy(RuntimeRemoteProviderPolicyModel):
    retry_candidate_allowed: Literal[True] = True
    manual_retry_required: Literal[True] = True
    auto_escalate_provider: Literal[False] = False
    auto_sos_escalation: Literal[False] = False


class RuntimeRemoteRateLimitPolicy(RuntimeRemoteProviderPolicyModel):
    incident_alert_window_seconds: Literal[600] = 600
    incident_alert_max_per_window: Literal[1] = 1
    remote_status_window_seconds: Literal[300] = 300
    remote_status_max_per_window: Literal[1] = 1
    checkin_window_seconds: Literal[300] = 300
    checkin_max_per_window: Literal[1] = 1


class RuntimeRemoteAuditPolicy(RuntimeRemoteProviderPolicyModel):
    summary_only: Literal[True] = True
    raw_payloads_embedded: Literal[False] = False
    required_fields: list[str] = Field(
        default_factory=lambda: [
            "provider_id",
            "recipient_ref",
            "message_class",
            "body_preview",
            "payload_hash",
            "send_status",
            "operator_id",
            "correlation_refs",
        ],
        min_length=1,
    )


class RuntimeRemoteProviderBoundary(RuntimeRemoteProviderPolicyModel):
    policy_only: Literal[True] = True
    creates_provider_adapter: Literal[False] = False
    sends_network_request: Literal[False] = False
    sends_real_remote_notification: Literal[False] = False
    enables_phase1_incident_bridge: Literal[False] = False
    writes_phase2_brain: Literal[False] = False
    raw_payloads_embedded: Literal[False] = False
    notes: list[str] = Field(
        default_factory=lambda: [
            "Webhook Remote Provider Policy / webhook 類真 provider 政策 only defines the first real-provider contract.",
            "The policy stores provider refs and secret refs, but never stores raw tokens or endpoint URLs.",
            "This slice sends no network request and enables no incident bridge.",
        ]
    )


class RuntimeRemoteProviderPolicyContract(RuntimeRemoteProviderPolicyModel):
    artifact_kind: Literal["runtime_remote_provider_policy_contract"] = (
        "runtime_remote_provider_policy_contract"
    )
    status: Literal["policy_ready_not_connected"] = "policy_ready_not_connected"
    provider_id: str = "remote_provider.webhook_telegram_like.v0"
    provider_kind: Literal[RuntimeRemoteProviderKind.WEBHOOK_TELEGRAM_LIKE] = (
        RuntimeRemoteProviderKind.WEBHOOK_TELEGRAM_LIKE
    )
    endpoint: RuntimeRemoteProviderEndpointPolicy = Field(
        default_factory=RuntimeRemoteProviderEndpointPolicy
    )
    auth: RuntimeRemoteProviderAuthPolicy = Field(
        default_factory=RuntimeRemoteProviderAuthPolicy
    )
    recipients: RuntimeRemoteRecipientPolicy = Field(
        default_factory=RuntimeRemoteRecipientPolicy
    )
    message_classes: RuntimeRemoteMessageClassPolicy = Field(
        default_factory=RuntimeRemoteMessageClassPolicy
    )
    cancellation: RuntimeRemoteCancellationPolicy = Field(
        default_factory=RuntimeRemoteCancellationPolicy
    )
    failure: RuntimeRemoteFailurePolicy = Field(
        default_factory=RuntimeRemoteFailurePolicy
    )
    rate_limits: RuntimeRemoteRateLimitPolicy = Field(
        default_factory=RuntimeRemoteRateLimitPolicy
    )
    audit: RuntimeRemoteAuditPolicy = Field(default_factory=RuntimeRemoteAuditPolicy)
    boundary: RuntimeRemoteProviderBoundary = Field(
        default_factory=RuntimeRemoteProviderBoundary
    )

    @model_validator(mode="after")
    def enforce_contract(self) -> "RuntimeRemoteProviderPolicyContract":
        if RuntimeRemoteMessageClass.SOS not in self.message_classes.blocked_message_classes:
            raise ValueError("sos must remain blocked in first provider policy")
        if self.endpoint.raw_url_embedded:
            raise ValueError("provider policy must not embed raw endpoint URL")
        if self.auth.token_value_embedded:
            raise ValueError("provider policy must not embed provider token")
        if self.boundary.sends_network_request:
            raise ValueError("provider policy must not send network requests")
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n"


class RuntimeRemoteProviderDecision(RuntimeRemoteProviderPolicyModel):
    artifact_kind: Literal["runtime_remote_provider_decision"] = (
        "runtime_remote_provider_decision"
    )
    status: RuntimeRemoteProviderDecisionStatus
    provider_id: str
    provider_kind: RuntimeRemoteProviderKind
    message_class: RuntimeRemoteMessageClass
    recipient_ref: str = Field(min_length=1)
    incident_level: str | None = None
    noise_reduction_policy_ref: str | None = None
    blocker_reasons: list[str] = Field(default_factory=list)
    send_performed: Literal[False] = False
    raw_payloads_embedded: Literal[False] = False
    phase2_writeback_count: Literal[0] = 0
    incident_bridge_enable_count: Literal[0] = 0
    remote_notification_send_count: Literal[0] = 0


def build_webhook_remote_provider_policy_contract() -> RuntimeRemoteProviderPolicyContract:
    return RuntimeRemoteProviderPolicyContract()


def evaluate_runtime_remote_message_request(
    policy: RuntimeRemoteProviderPolicyContract,
    *,
    message_class: RuntimeRemoteMessageClass,
    recipient_ref: str,
    incident_level: str | None = None,
    noise_reduction_policy_ref: str | None = None,
) -> RuntimeRemoteProviderDecision:
    blockers: list[str] = []
    if recipient_ref not in policy.recipients.allowed_recipient_refs:
        blockers.append("recipient_ref_not_allowed")
    if message_class in policy.message_classes.blocked_message_classes:
        blockers.append(f"{message_class.value}_provider_not_implemented")
    if message_class not in policy.message_classes.allowed_message_classes:
        blockers.append("message_class_not_allowed")
    if message_class == RuntimeRemoteMessageClass.INCIDENT_ALERT:
        if incident_level not in policy.message_classes.incident_alert_allowed_levels:
            blockers.append("incident_alert_level_not_allowed")
        if not noise_reduction_policy_ref:
            blockers.append("missing_noise_reduction_policy_ref")

    status = (
        RuntimeRemoteProviderDecisionStatus.BLOCKED
        if blockers
        else RuntimeRemoteProviderDecisionStatus.ALLOWED
    )
    return RuntimeRemoteProviderDecision(
        status=status,
        provider_id=policy.provider_id,
        provider_kind=policy.provider_kind,
        message_class=message_class,
        recipient_ref=recipient_ref,
        incident_level=incident_level,
        noise_reduction_policy_ref=noise_reduction_policy_ref,
        blocker_reasons=blockers,
    )


def load_runtime_remote_provider_policy_contract(
    path: Path | str,
) -> RuntimeRemoteProviderPolicyContract:
    return RuntimeRemoteProviderPolicyContract.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )
