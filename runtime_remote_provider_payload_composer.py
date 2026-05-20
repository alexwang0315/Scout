from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from runtime_remote_provider_config_preflight import (
    RuntimeRemoteProviderConfig,
    RuntimeRemoteProviderConfigPreflightReport,
    RuntimeRemoteProviderConfigPreflightStatus,
)
from runtime_remote_provider_policy import (
    RuntimeRemoteMessageClass,
    RuntimeRemoteProviderKind,
    RuntimeRemoteProviderPolicyContract,
    evaluate_runtime_remote_message_request,
)


class RuntimeRemoteProviderPayloadModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuntimeRemoteProviderPayloadCompositionStatus(StrEnum):
    READY_NOT_SENT = "payload_ready_not_sent"
    BLOCKED = "payload_blocked"


class RuntimeRemoteProviderPayloadRequest(RuntimeRemoteProviderPayloadModel):
    artifact_kind: Literal["runtime_remote_provider_payload_request"] = (
        "runtime_remote_provider_payload_request"
    )
    message_class: RuntimeRemoteMessageClass
    recipient_ref: str = Field(min_length=1)
    body_summary: str = Field(min_length=1)
    operator_id: str = Field(min_length=1)
    incident_level: str | None = None
    noise_reduction_policy_ref: str | None = None
    correlation_refs: list[str] = Field(min_length=1)
    raw_payloads_embedded: Literal[False] = False
    secret_values_loaded: Literal[False] = False


class RuntimeRemoteProviderPayloadComposition(RuntimeRemoteProviderPayloadModel):
    artifact_kind: Literal["runtime_remote_provider_payload_preview"] = (
        "runtime_remote_provider_payload_preview"
    )
    status: RuntimeRemoteProviderPayloadCompositionStatus
    payload_ready: bool
    provider_id: str
    provider_kind: RuntimeRemoteProviderKind
    endpoint_ref: str
    recipient_ref: str
    delivery_target_secret_ref: str | None = None
    message_class: RuntimeRemoteMessageClass
    body_preview: str
    payload_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    operator_id: str
    incident_level: str | None = None
    noise_reduction_policy_ref: str | None = None
    correlation_refs: list[str] = Field(default_factory=list)
    blocker_count: int = 0
    blocker_reasons: list[str] = Field(default_factory=list)
    summary_only: Literal[True] = True
    raw_payloads_embedded: Literal[False] = False
    secret_values_loaded: Literal[False] = False
    endpoint_url_embedded: Literal[False] = False
    token_value_embedded: Literal[False] = False
    send_performed: Literal[False] = False
    remote_notification_send_count: Literal[0] = 0
    incident_bridge_enable_count: Literal[0] = 0
    phase2_writeback_count: Literal[0] = 0


def compose_runtime_remote_provider_payload(
    policy: RuntimeRemoteProviderPolicyContract,
    config: RuntimeRemoteProviderConfig,
    preflight: RuntimeRemoteProviderConfigPreflightReport,
    request: RuntimeRemoteProviderPayloadRequest,
) -> RuntimeRemoteProviderPayloadComposition:
    body_preview = _normalize_body_preview(request.body_summary)
    delivery_target_secret_ref = _delivery_target_secret_ref(config, request.recipient_ref)
    blockers: list[str] = []

    if preflight.status != RuntimeRemoteProviderConfigPreflightStatus.READY:
        blockers.append("provider_config_preflight_not_ready")
        blockers.extend(preflight.blocker_reasons)
    if preflight.provider_config_ready is not True:
        blockers.append("provider_config_ready_flag_false")
    if request.message_class not in config.enabled_message_classes:
        blockers.append(f"message_class_not_enabled_in_config:{request.message_class.value}")
    if delivery_target_secret_ref is None:
        blockers.append("recipient_config_missing")

    decision = evaluate_runtime_remote_message_request(
        policy,
        message_class=request.message_class,
        recipient_ref=request.recipient_ref,
        incident_level=request.incident_level,
        noise_reduction_policy_ref=request.noise_reduction_policy_ref,
    )
    blockers.extend(decision.blocker_reasons)

    unique_blockers = list(dict.fromkeys(blockers))
    payload_hash = _payload_hash(
        {
            "provider_id": config.provider_id,
            "provider_kind": config.provider_kind.value,
            "endpoint_ref": config.endpoint.endpoint_ref,
            "recipient_ref": request.recipient_ref,
            "delivery_target_secret_ref": delivery_target_secret_ref,
            "message_class": request.message_class.value,
            "body_preview": body_preview,
            "operator_id": request.operator_id,
            "incident_level": request.incident_level,
            "noise_reduction_policy_ref": request.noise_reduction_policy_ref,
            "correlation_refs": request.correlation_refs,
        }
    )
    ready = not unique_blockers
    return RuntimeRemoteProviderPayloadComposition(
        status=(
            RuntimeRemoteProviderPayloadCompositionStatus.READY_NOT_SENT
            if ready
            else RuntimeRemoteProviderPayloadCompositionStatus.BLOCKED
        ),
        payload_ready=ready,
        provider_id=config.provider_id,
        provider_kind=config.provider_kind,
        endpoint_ref=config.endpoint.endpoint_ref,
        recipient_ref=request.recipient_ref,
        delivery_target_secret_ref=delivery_target_secret_ref,
        message_class=request.message_class,
        body_preview=body_preview,
        payload_hash=payload_hash,
        operator_id=request.operator_id,
        incident_level=request.incident_level,
        noise_reduction_policy_ref=request.noise_reduction_policy_ref,
        correlation_refs=request.correlation_refs,
        blocker_count=len(unique_blockers),
        blocker_reasons=unique_blockers,
    )


def _normalize_body_preview(summary: str, *, max_length: int = 240) -> str:
    normalized = " ".join(summary.split())
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 3].rstrip() + "..."


def _delivery_target_secret_ref(
    config: RuntimeRemoteProviderConfig,
    recipient_ref: str,
) -> str | None:
    for recipient in config.recipients:
        if recipient.recipient_ref == recipient_ref:
            return recipient.delivery_target_secret_ref
    return None


def _payload_hash(payload_preview: dict[str, object]) -> str:
    canonical = json.dumps(
        payload_preview,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
