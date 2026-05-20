from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from runtime_incident_bridge_opt_in import (
    RuntimeIncidentBridgeOptInDecision,
    RuntimeIncidentBridgeOptInStatus,
)


class _MockOutboundTransport(Protocol):
    def queue_message(
        self,
        *,
        category: str,
        recipient_ref: str,
        body_preview: str,
        subject_ref: str | None = None,
        payload: dict[str, Any] | None = None,
        correlation_refs: list[str] | None = None,
    ) -> Any:
        ...


class RuntimeIncidentBridgeEnablementModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuntimeIncidentBridgeEnablementStatus(StrEnum):
    BLOCKED = "blocked"
    DRY_RUN_RECORDED = "dry_run_recorded"


class RuntimeIncidentBridgeEnablementCounts(RuntimeIncidentBridgeEnablementModel):
    incident_bridge_enable_count: Literal[0] = 0
    remote_notification_send_count: Literal[0] = 0
    mock_outbound_message_count: int = Field(default=0, ge=0)
    phase2_writeback_count: Literal[0] = 0
    raw_payload_copy_count: Literal[0] = 0


class RuntimeIncidentBridgeEnablementBoundary(RuntimeIncidentBridgeEnablementModel):
    dry_run_only: Literal[True] = True
    uses_mock_outbound_transport: Literal[True] = True
    sends_real_remote_notification: Literal[False] = False
    enables_phase1_incident_bridge: Literal[False] = False
    writes_phase2_brain: Literal[False] = False
    mutates_runtime_export: Literal[False] = False
    mutates_activation_request: Literal[False] = False
    raw_payloads_embedded: Literal[False] = False
    notes: list[str] = Field(
        default_factory=lambda: [
            "Runtime Incident Bridge Enablement Dry Run / 遠端通知啟用演練 records enablement intent only.",
            "Dry run queues mock outbound messages, but sends no real remote notification.",
            "Dry run does not enable the Phase 1 incident bridge and does not write Phase 2 Brain state.",
        ]
    )


class RuntimeIncidentBridgeEnablementRecord(RuntimeIncidentBridgeEnablementModel):
    artifact_kind: Literal["runtime_incident_bridge_enablement_record"] = (
        "runtime_incident_bridge_enablement_record"
    )
    status: RuntimeIncidentBridgeEnablementStatus
    guard_status: str = Field(min_length=1)
    operator_id: str = Field(min_length=1)
    runtime_status: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    recorded_at: str = Field(min_length=1)
    remote_contact_policy_ref: str | None = None
    noise_reduction_policy_ref: str | None = None
    recipient_refs: list[str] = Field(default_factory=list)
    mock_outbound_message_refs: list[str] = Field(default_factory=list)
    blocker_reasons: list[str] = Field(default_factory=list)
    remote_notifications_enabled: Literal[False] = False
    enable_performed: Literal[False] = False
    counts: RuntimeIncidentBridgeEnablementCounts = Field(
        default_factory=RuntimeIncidentBridgeEnablementCounts
    )
    boundary: RuntimeIncidentBridgeEnablementBoundary = Field(
        default_factory=RuntimeIncidentBridgeEnablementBoundary
    )

    @model_validator(mode="after")
    def enforce_enablement_boundary(self) -> "RuntimeIncidentBridgeEnablementRecord":
        if self.remote_notifications_enabled:
            raise ValueError("dry run must not enable remote notifications")
        if self.enable_performed:
            raise ValueError("dry run must not perform bridge enablement")
        if self.boundary.sends_real_remote_notification:
            raise ValueError("dry run must not send real remote notifications")
        if self.boundary.enables_phase1_incident_bridge:
            raise ValueError("dry run must not enable Phase 1 incident bridge")
        if self.boundary.writes_phase2_brain:
            raise ValueError("dry run must not write Phase 2 Brain")
        if self.boundary.raw_payloads_embedded:
            raise ValueError("dry run must not embed raw payloads")
        if self.counts.mock_outbound_message_count != len(self.mock_outbound_message_refs):
            raise ValueError("mock_outbound_message_count must match message refs")
        return self


def build_runtime_incident_bridge_enablement_dry_run(
    *,
    opt_in_decision: RuntimeIncidentBridgeOptInDecision,
    operator_id: str,
    recipient_refs: list[str],
    reason: str,
    outbound_transport: _MockOutboundTransport | None,
    timestamp_factory: Callable[[], str] | None = None,
) -> RuntimeIncidentBridgeEnablementRecord:
    recorded_at = (timestamp_factory or _utc_now)()
    blockers: list[str] = []
    if (
        opt_in_decision.status != RuntimeIncidentBridgeOptInStatus.READY_NOT_ENABLED
        or not opt_in_decision.bridge_enable_allowed_after_guard
    ):
        blockers.append("opt_in_guard_not_ready")
    if not recipient_refs:
        blockers.append("missing_recipient_refs")
    if recipient_refs and outbound_transport is None:
        blockers.append("missing_mock_outbound_transport")

    mock_message_refs: list[str] = []
    if not blockers and outbound_transport is not None:
        subject_ref = f"runtime_incident_bridge_enablement.{recorded_at}"
        for recipient_ref in recipient_refs:
            message = outbound_transport.queue_message(
                category="remote_status",
                recipient_ref=recipient_ref,
                subject_ref=subject_ref,
                body_preview=(
                    "Scout would enable remote incident notifications after "
                    f"operator opt-in for runtime status {opt_in_decision.runtime_status}."
                ),
                payload={
                    "dry_run_only": True,
                    "runtime_status": opt_in_decision.runtime_status,
                    "remote_contact_policy_ref": opt_in_decision.remote_contact_policy_ref,
                    "noise_reduction_policy_ref": opt_in_decision.noise_reduction_policy_ref,
                    "remote_notifications_enabled": False,
                    "enable_performed": False,
                },
                correlation_refs=[
                    opt_in_decision.remote_contact_policy_ref or "remote_contact_policy.missing",
                    opt_in_decision.noise_reduction_policy_ref
                    or "noise_reduction_policy.missing",
                ],
            )
            mock_message_refs.append(str(message.message_id))

    status = (
        RuntimeIncidentBridgeEnablementStatus.BLOCKED
        if blockers
        else RuntimeIncidentBridgeEnablementStatus.DRY_RUN_RECORDED
    )
    return RuntimeIncidentBridgeEnablementRecord(
        status=status,
        guard_status=opt_in_decision.status.value,
        operator_id=operator_id,
        runtime_status=opt_in_decision.runtime_status,
        reason=reason,
        recorded_at=recorded_at,
        remote_contact_policy_ref=opt_in_decision.remote_contact_policy_ref,
        noise_reduction_policy_ref=opt_in_decision.noise_reduction_policy_ref,
        recipient_refs=list(recipient_refs),
        mock_outbound_message_refs=mock_message_refs,
        blocker_reasons=blockers,
        counts=RuntimeIncidentBridgeEnablementCounts(
            mock_outbound_message_count=len(mock_message_refs),
        ),
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
