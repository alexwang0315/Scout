from __future__ import annotations

import json
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RuntimeIncidentBridgeOptInModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuntimeIncidentBridgeOptInStatus(StrEnum):
    OPT_IN_REQUIRED = "opt_in_required"
    BLOCKED = "blocked"
    READY_NOT_ENABLED = "ready_not_enabled"


class RuntimeIncidentBridgeOptInCounts(RuntimeIncidentBridgeOptInModel):
    incident_bridge_enable_count: Literal[0] = 0
    remote_notification_send_count: Literal[0] = 0
    phase2_writeback_count: Literal[0] = 0
    raw_payload_copy_count: Literal[0] = 0


class RuntimeIncidentBridgeOptInBoundary(RuntimeIncidentBridgeOptInModel):
    opt_in_guard_only: Literal[True] = True
    sends_remote_notification: Literal[False] = False
    enables_phase1_incident_bridge: Literal[False] = False
    writes_phase2_brain: Literal[False] = False
    mutates_runtime_export: Literal[False] = False
    mutates_activation_request: Literal[False] = False
    raw_payloads_embedded: Literal[False] = False
    notes: list[str] = Field(
        default_factory=lambda: [
            "Runtime Incident Bridge Opt-In / 遠端通知啟用守門 only evaluates whether bridge enablement may be allowed later.",
            "The guard does not send remote notifications or enable the Phase 1 incident bridge.",
            "Remote contact policy and noise-reduction policy are both required before bridge enablement can be considered.",
        ]
    )


class RuntimeIncidentBridgeOptInDecision(RuntimeIncidentBridgeOptInModel):
    artifact_kind: Literal["runtime_incident_bridge_opt_in_decision"] = (
        "runtime_incident_bridge_opt_in_decision"
    )
    status: RuntimeIncidentBridgeOptInStatus
    operator_id: str = Field(min_length=1)
    runtime_status: str = Field(min_length=1)
    operator_opt_in: bool
    remote_contact_policy_ref: str | None = None
    noise_reduction_policy_ref: str | None = None
    remote_notifications_enabled: Literal[False] = False
    enable_performed: Literal[False] = False
    bridge_enable_allowed_after_guard: bool
    blocker_reasons: list[str] = Field(default_factory=list)
    counts: RuntimeIncidentBridgeOptInCounts = Field(
        default_factory=RuntimeIncidentBridgeOptInCounts
    )
    boundary: RuntimeIncidentBridgeOptInBoundary = Field(
        default_factory=RuntimeIncidentBridgeOptInBoundary
    )

    @model_validator(mode="after")
    def enforce_opt_in_boundary(self) -> "RuntimeIncidentBridgeOptInDecision":
        if self.remote_notifications_enabled:
            raise ValueError("incident bridge opt-in guard must not enable notifications")
        if self.enable_performed:
            raise ValueError("incident bridge opt-in guard must not perform bridge enable")
        if self.boundary.sends_remote_notification:
            raise ValueError("incident bridge opt-in guard must not send notifications")
        if self.boundary.enables_phase1_incident_bridge:
            raise ValueError("incident bridge opt-in guard must not enable Phase 1 bridge")
        if self.boundary.writes_phase2_brain:
            raise ValueError("incident bridge opt-in guard must not write Phase 2")
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n"


def build_runtime_incident_bridge_opt_in_decision(
    *,
    operator_id: str,
    runtime_status: str,
    operator_opt_in: bool,
    remote_contact_policy_ref: str | None = None,
    noise_reduction_policy_ref: str | None = None,
) -> RuntimeIncidentBridgeOptInDecision:
    blockers: list[str] = []
    if runtime_status not in {"observing", "paused"}:
        blockers.append("runtime_status_not_observing_or_paused")
    if operator_opt_in and not remote_contact_policy_ref:
        blockers.append("missing_remote_contact_policy_ref")
    if operator_opt_in and not noise_reduction_policy_ref:
        blockers.append("missing_noise_reduction_policy_ref")

    if not operator_opt_in:
        status = RuntimeIncidentBridgeOptInStatus.OPT_IN_REQUIRED
    elif blockers:
        status = RuntimeIncidentBridgeOptInStatus.BLOCKED
    else:
        status = RuntimeIncidentBridgeOptInStatus.READY_NOT_ENABLED

    return RuntimeIncidentBridgeOptInDecision(
        status=status,
        operator_id=operator_id,
        runtime_status=runtime_status,
        operator_opt_in=operator_opt_in,
        remote_contact_policy_ref=remote_contact_policy_ref,
        noise_reduction_policy_ref=noise_reduction_policy_ref,
        bridge_enable_allowed_after_guard=(
            status == RuntimeIncidentBridgeOptInStatus.READY_NOT_ENABLED
        ),
        blocker_reasons=blockers,
    )
