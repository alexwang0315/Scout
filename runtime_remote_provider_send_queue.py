from __future__ import annotations

import json
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from runtime_remote_provider_payload_composer import (
    RuntimeRemoteProviderPayloadComposition,
    RuntimeRemoteProviderPayloadCompositionStatus,
)
from runtime_remote_provider_policy import (
    RuntimeRemoteMessageClass,
    RuntimeRemoteProviderKind,
)


class RuntimeRemoteProviderSendQueueModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuntimeRemoteProviderSendIntentStatus(StrEnum):
    QUEUED_NOT_SENT = "queued_not_sent"
    BLOCKED = "send_intent_blocked"


class RuntimeRemoteProviderSendIntent(RuntimeRemoteProviderSendQueueModel):
    artifact_kind: Literal["runtime_remote_provider_send_intent"] = (
        "runtime_remote_provider_send_intent"
    )
    status: RuntimeRemoteProviderSendIntentStatus
    send_intent_queued: bool
    intent_id: str = Field(min_length=1)
    provider_id: str = Field(min_length=1)
    provider_kind: RuntimeRemoteProviderKind
    endpoint_ref: str = Field(min_length=1)
    recipient_ref: str = Field(min_length=1)
    delivery_target_secret_ref: str | None = None
    message_class: RuntimeRemoteMessageClass
    body_preview: str = Field(min_length=1)
    payload_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    queued_by_operator_id: str = Field(min_length=1)
    queued_at_iso: str = Field(min_length=1)
    correlation_refs: list[str] = Field(default_factory=list)
    blocker_count: int = 0
    blocker_reasons: list[str] = Field(default_factory=list)
    provider_adapter_required_before_send: Literal[True] = True
    manual_send_authorization_required: Literal[True] = True
    summary_only: Literal[True] = True
    raw_payloads_embedded: Literal[False] = False
    secret_values_loaded: Literal[False] = False
    endpoint_url_embedded: Literal[False] = False
    token_value_embedded: Literal[False] = False
    creates_provider_adapter: Literal[False] = False
    sends_network_request: Literal[False] = False
    send_performed: Literal[False] = False
    remote_notification_send_count: Literal[0] = 0
    incident_bridge_enable_count: Literal[0] = 0
    phase2_writeback_count: Literal[0] = 0

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n"


def queue_runtime_remote_provider_send_intent(
    payload_preview: RuntimeRemoteProviderPayloadComposition,
    *,
    intent_id: str,
    queued_by_operator_id: str,
    queued_at_iso: str,
) -> RuntimeRemoteProviderSendIntent:
    blockers: list[str] = []
    if payload_preview.status != RuntimeRemoteProviderPayloadCompositionStatus.READY_NOT_SENT:
        blockers.append("payload_not_ready")
    if not payload_preview.payload_ready:
        blockers.append("payload_ready_flag_false")
    blockers.extend(payload_preview.blocker_reasons)
    unique_blockers = list(dict.fromkeys(blockers))
    queued = not unique_blockers

    return RuntimeRemoteProviderSendIntent(
        status=(
            RuntimeRemoteProviderSendIntentStatus.QUEUED_NOT_SENT
            if queued
            else RuntimeRemoteProviderSendIntentStatus.BLOCKED
        ),
        send_intent_queued=queued,
        intent_id=intent_id,
        provider_id=payload_preview.provider_id,
        provider_kind=payload_preview.provider_kind,
        endpoint_ref=payload_preview.endpoint_ref,
        recipient_ref=payload_preview.recipient_ref,
        delivery_target_secret_ref=payload_preview.delivery_target_secret_ref,
        message_class=payload_preview.message_class,
        body_preview=payload_preview.body_preview,
        payload_hash=payload_preview.payload_hash,
        queued_by_operator_id=queued_by_operator_id,
        queued_at_iso=queued_at_iso,
        correlation_refs=payload_preview.correlation_refs,
        blocker_count=len(unique_blockers),
        blocker_reasons=unique_blockers,
    )
