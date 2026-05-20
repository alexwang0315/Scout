from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from runtime_incident_bridge_enablement import (
    RuntimeIncidentBridgeEnablementRecord,
    RuntimeIncidentBridgeEnablementStatus,
)


class _MockOutboundTransport(Protocol):
    def get_message(self, message_id: str) -> Any:
        ...

    def mark_mock_delivered(self, message_id: str) -> Any:
        ...

    def cancel_message(self, message_id: str, *, reason: str) -> Any:
        ...


class RuntimeIncidentBridgeDeliveryAckModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuntimeIncidentBridgeDeliveryAction(StrEnum):
    CONFIRM_MOCK_DELIVERED = "confirm_mock_delivered"
    CANCEL_MOCK_DELIVERY = "cancel_mock_delivery"
    RERUN_DRY_RUN = "rerun_dry_run"


class RuntimeIncidentBridgeDeliveryAckStatus(StrEnum):
    ACK_RECORDED = "ack_recorded"
    CANCEL_RECORDED = "cancel_recorded"
    RERUN_RECORDED = "rerun_recorded"
    BLOCKED = "blocked"


class RuntimeIncidentBridgeDeliveryAckCounts(RuntimeIncidentBridgeDeliveryAckModel):
    mock_delivered_count: int = Field(default=0, ge=0)
    cancelled_count: int = Field(default=0, ge=0)
    rerun_message_count: int = Field(default=0, ge=0)
    remote_notification_send_count: Literal[0] = 0
    incident_bridge_enable_count: Literal[0] = 0
    phase2_writeback_count: Literal[0] = 0
    raw_payload_copy_count: Literal[0] = 0


class RuntimeIncidentBridgeDeliveryAckBoundary(RuntimeIncidentBridgeDeliveryAckModel):
    mock_ack_only: Literal[True] = True
    uses_mock_outbound_transport: Literal[True] = True
    sends_real_remote_notification: Literal[False] = False
    receives_real_provider_receipt: Literal[False] = False
    cancels_real_provider_delivery: Literal[False] = False
    enables_phase1_incident_bridge: Literal[False] = False
    writes_phase2_brain: Literal[False] = False
    raw_payloads_embedded: Literal[False] = False
    notes: list[str] = Field(
        default_factory=lambda: [
            "Mock Delivery Acknowledgment / 模擬送達確認 records mock-only operator delivery outcomes.",
            "Acknowledged means the mock transport was marked delivered, not that a real recipient received a notification.",
            "Cancelled means the mock queue intent was cancelled, not that a real provider message was withdrawn.",
        ]
    )


class RuntimeIncidentBridgeDeliveryAckRecord(RuntimeIncidentBridgeDeliveryAckModel):
    artifact_kind: Literal["runtime_incident_bridge_delivery_ack_record"] = (
        "runtime_incident_bridge_delivery_ack_record"
    )
    action: RuntimeIncidentBridgeDeliveryAction
    status: RuntimeIncidentBridgeDeliveryAckStatus
    operator_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    recorded_at: str = Field(min_length=1)
    enablement_status: str = Field(min_length=1)
    guard_status: str = Field(min_length=1)
    message_refs: list[str] = Field(default_factory=list)
    updated_message_refs: list[str] = Field(default_factory=list)
    rerun_message_refs: list[str] = Field(default_factory=list)
    blocker_reasons: list[str] = Field(default_factory=list)
    remote_notifications_enabled: Literal[False] = False
    enable_performed: Literal[False] = False
    counts: RuntimeIncidentBridgeDeliveryAckCounts = Field(
        default_factory=RuntimeIncidentBridgeDeliveryAckCounts
    )
    boundary: RuntimeIncidentBridgeDeliveryAckBoundary = Field(
        default_factory=RuntimeIncidentBridgeDeliveryAckBoundary
    )

    @model_validator(mode="after")
    def enforce_delivery_ack_boundary(self) -> "RuntimeIncidentBridgeDeliveryAckRecord":
        if self.remote_notifications_enabled:
            raise ValueError("mock delivery ack must not enable remote notifications")
        if self.enable_performed:
            raise ValueError("mock delivery ack must not perform bridge enablement")
        if self.boundary.sends_real_remote_notification:
            raise ValueError("mock delivery ack must not send real notifications")
        if self.boundary.receives_real_provider_receipt:
            raise ValueError("mock delivery ack must not receive provider receipts")
        if self.boundary.cancels_real_provider_delivery:
            raise ValueError("mock delivery ack must not cancel provider delivery")
        if self.boundary.enables_phase1_incident_bridge:
            raise ValueError("mock delivery ack must not enable Phase 1 bridge")
        if self.boundary.writes_phase2_brain:
            raise ValueError("mock delivery ack must not write Phase 2")
        if self.boundary.raw_payloads_embedded:
            raise ValueError("mock delivery ack must not embed raw payload")
        if self.counts.rerun_message_count != len(self.rerun_message_refs):
            raise ValueError("rerun_message_count must match rerun refs")
        return self


def build_runtime_incident_bridge_delivery_ack(
    *,
    enablement_record: RuntimeIncidentBridgeEnablementRecord,
    action: RuntimeIncidentBridgeDeliveryAction,
    operator_id: str,
    reason: str,
    outbound_transport: _MockOutboundTransport,
    rerun_message_refs: list[str] | None = None,
    timestamp_factory: Callable[[], str] | None = None,
) -> RuntimeIncidentBridgeDeliveryAckRecord:
    recorded_at = (timestamp_factory or _utc_now)()
    message_refs = list(enablement_record.mock_outbound_message_refs)
    blockers = _validate_ack_inputs(enablement_record, action, outbound_transport)
    updated_refs: list[str] = []
    rerun_refs = list(rerun_message_refs or [])
    mock_delivered_count = 0
    cancelled_count = 0

    if action == RuntimeIncidentBridgeDeliveryAction.RERUN_DRY_RUN and not rerun_refs:
        blockers.append("missing_rerun_message_refs")

    if not blockers:
        if action == RuntimeIncidentBridgeDeliveryAction.CONFIRM_MOCK_DELIVERED:
            for message_ref in message_refs:
                outbound_transport.mark_mock_delivered(message_ref)
                updated_refs.append(message_ref)
            mock_delivered_count = len(updated_refs)
            status = RuntimeIncidentBridgeDeliveryAckStatus.ACK_RECORDED
        elif action == RuntimeIncidentBridgeDeliveryAction.CANCEL_MOCK_DELIVERY:
            for message_ref in message_refs:
                outbound_transport.cancel_message(message_ref, reason=reason)
                updated_refs.append(message_ref)
            cancelled_count = len(updated_refs)
            status = RuntimeIncidentBridgeDeliveryAckStatus.CANCEL_RECORDED
        else:
            status = RuntimeIncidentBridgeDeliveryAckStatus.RERUN_RECORDED
    else:
        status = RuntimeIncidentBridgeDeliveryAckStatus.BLOCKED

    return RuntimeIncidentBridgeDeliveryAckRecord(
        action=action,
        status=status,
        operator_id=operator_id,
        reason=reason,
        recorded_at=recorded_at,
        enablement_status=enablement_record.status.value,
        guard_status=enablement_record.guard_status,
        message_refs=message_refs,
        updated_message_refs=updated_refs,
        rerun_message_refs=rerun_refs if status != RuntimeIncidentBridgeDeliveryAckStatus.BLOCKED else [],
        blocker_reasons=blockers,
        counts=RuntimeIncidentBridgeDeliveryAckCounts(
            mock_delivered_count=mock_delivered_count,
            cancelled_count=cancelled_count,
            rerun_message_count=(
                len(rerun_refs)
                if status == RuntimeIncidentBridgeDeliveryAckStatus.RERUN_RECORDED
                else 0
            ),
        ),
    )


def _validate_ack_inputs(
    enablement_record: RuntimeIncidentBridgeEnablementRecord,
    action: RuntimeIncidentBridgeDeliveryAction,
    outbound_transport: _MockOutboundTransport,
) -> list[str]:
    blockers: list[str] = []
    if enablement_record.status != RuntimeIncidentBridgeEnablementStatus.DRY_RUN_RECORDED:
        blockers.append("enablement_record_not_dry_run")
        return blockers
    if not enablement_record.mock_outbound_message_refs:
        blockers.append("missing_mock_outbound_message_refs")
        return blockers
    for message_ref in enablement_record.mock_outbound_message_refs:
        try:
            message = outbound_transport.get_message(message_ref)
        except KeyError:
            blockers.append(f"unknown_mock_outbound_message_ref:{message_ref}")
            continue
        if getattr(message, "transport", None) != "mock":
            blockers.append(f"non_mock_outbound_message_ref:{message_ref}")
        if action == RuntimeIncidentBridgeDeliveryAction.CANCEL_MOCK_DELIVERY:
            if getattr(message, "state", None) == "mock-delivered":
                blockers.append(f"cannot_cancel_mock_delivered_message:{message_ref}")
            if getattr(message, "state", None) == "cancelled":
                blockers.append(f"message_already_cancelled:{message_ref}")
    return blockers


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
