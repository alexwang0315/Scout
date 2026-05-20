from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class HardwareControlEventType(StrEnum):
    MANUAL_SOS_BUTTON_OBSERVED = "manual_sos_button_observed"
    ALERT_ACK_BUTTON_OBSERVED = "alert_ack_button_observed"
    LOCAL_ALERT_SILENCE_OBSERVED = "local_alert_silence_observed"
    DEVICE_MODE_SWITCH_OBSERVED = "device_mode_switch_observed"
    MANUAL_DISTRESS_CONFIRMED = "manual_sos_button_observed"
    ALERT_ACKNOWLEDGED = "alert_ack_button_observed"
    LOCAL_ALERT_SILENCED = "local_alert_silence_observed"
    DEVICE_MODE_CHANGED = "device_mode_switch_observed"


class HardwareControlDeviceMode(StrEnum):
    SAFE = "SAFE"
    ARMED = "ARMED"
    MAINTENANCE = "MAINTENANCE"
    UNKNOWN = "UNKNOWN"


class HardwareControlEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: HardwareControlEventType
    source: str = Field(min_length=1)
    observed_at: float
    device_mode: HardwareControlDeviceMode = HardwareControlDeviceMode.UNKNOWN
    pattern: str | None = None
    authority: Literal["operator_observed", "user_asserted"] = "operator_observed"
    debounce_ms: int | None = Field(default=None, ge=0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    details: dict[str, Any] = Field(default_factory=dict)


class HardwareControlBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_contract_only: bool = True
    read_only_projection: bool = True
    safety_mutation_allowed: bool = False
    phase1_safety_decision_mutation_allowed: bool = False
    incident_package_write_allowed: bool = False
    observed_fact_write_allowed: bool = False
    brain_write_allowed: bool = False
    outbound_send_allowed: bool = False
    hardware_provider_control_allowed: bool = False
    network_calls_allowed: bool = False


class HardwareControlEventProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: Literal["hardware_control_event_projection"]
    event_type: HardwareControlEventType
    source: str
    observed_at: float
    device_mode: HardwareControlDeviceMode
    annotation_only: bool
    requires_operator_review: bool
    boundary: HardwareControlBoundary


def project_hardware_control_event(event: HardwareControlEvent) -> HardwareControlEventProjection:
    return HardwareControlEventProjection(
        artifact_kind="hardware_control_event_projection",
        event_type=event.event_type,
        source=event.source,
        observed_at=event.observed_at,
        device_mode=event.device_mode,
        annotation_only=True,
        requires_operator_review=True,
        boundary=HardwareControlBoundary(),
    )


def hardware_control_annotation(event: HardwareControlEvent) -> dict[str, Any]:
    return {
        "annotation_type": event.event_type.value,
        "source": event.source,
        "observed_at": event.observed_at,
        "device_mode": event.device_mode.value,
        "pattern": event.pattern,
        "authority": event.authority,
        "debounce_ms": event.debounce_ms,
        "confidence": event.confidence,
        "details": event.details,
        "projection_only": True,
    }


def hardware_control_event_to_safety_event(*_: Any, **__: Any) -> Any:
    raise RuntimeError(
        "GPIO control events are projection-only in this slice and cannot be converted "
        "into safety events without an explicit Phase 1 runtime decision."
    )
