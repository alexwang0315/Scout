from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SafetyLevel(StrEnum):
    NORMAL = "L0_NORMAL"
    WATCH = "L1_WATCH"
    CONCERN = "L2_CONCERN"
    DISTRESS = "L3_DISTRESS"
    EMERGENCY = "L4_EMERGENCY"


class SafetyEventType(StrEnum):
    ROUTE_DEVIATION = "route_deviation"
    BACKTRACKING_LOOP = "backtracking_loop"
    STEEP_SLOPE = "steep_slope"
    WEAK_GPS = "weak_gps"
    UNRECOGNIZED_ROUTE = "unrecognized_route"
    UNSAFE_CONTINUATION = "unsafe_continuation"
    MISSED_CHECKPOINT = "missed_checkpoint"
    RESOURCE_CONSTRAINT = "resource_constraint"
    SENSOR_ANOMALY = "sensor_anomaly"


class SafetyEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: SafetyEventType
    level: SafetyLevel
    timestamp: float
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)
    details: dict[str, Any] = Field(default_factory=dict)


class SafetyTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_level: SafetyLevel
    to_level: SafetyLevel
    timestamp: float
    reason: str
    event: SafetyEvent | None = None


class SafetyState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: SafetyLevel = SafetyLevel.NORMAL
    updated_at: float = 0.0
    active_events: list[SafetyEvent] = Field(default_factory=list)
    transitions: list[SafetyTransition] = Field(default_factory=list)


class Observation(BaseModel):
    model_config = ConfigDict(extra="allow")

    timestamp: float
    source: str
    lat: float | None = None
    lon: float | None = None
    elevation_m: float | None = None
    pdr_x_m: float | None = None
    pdr_y_m: float | None = None
    gps_horizontal_accuracy_m: float | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class IncidentPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: str
    trigger_level: SafetyLevel
    triggered_at: float
    trigger_event: SafetyEvent
    raw_window_start: float
    raw_window_end: float
    raw_samples: list[dict[str, Any]] = Field(default_factory=list)
    segment_capsule_ids: list[str] = Field(default_factory=list)
    safety_transitions: list[SafetyTransition] = Field(default_factory=list)
    ai_summary_input: dict[str, Any] = Field(default_factory=dict)
