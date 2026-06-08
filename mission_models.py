from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class CheckpointType(StrEnum):
    START = "start"
    FINISH = "finish"
    TERRAIN_TRANSITION = "terrain_transition"
    RIDGE_ENTRY = "ridge_entry"
    WATER_SOURCE = "water_source"
    RETREAT_POINT = "retreat_point"
    CAMP = "camp"
    SIGNAL_SPOT = "signal_spot"
    HIGH_RISK_ENTRY = "high_risk_entry"
    SUMMIT = "summit"
    VIEWPOINT = "viewpoint"
    TRAILHEAD = "trailhead"
    WAYPOINT = "waypoint"


class ControlZoneType(StrEnum):
    URBAN_EDGE = "urban_edge"
    TRAILHEAD = "trailhead"
    FOREST = "forest"
    RIDGE_APPROACH = "ridge_approach"
    RIDGE_CROSSING = "ridge_crossing"
    STEEP_DESCENT = "steep_descent"
    WATER_OR_CAMP = "water_or_camp"
    RETREAT_CORRIDOR = "retreat_corridor"
    FINISH_APPROACH = "finish_approach"
    UNKNOWN = "unknown"


class RecordingProfile(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    RAW_LOCK = "raw_lock"


class GoNoGoAction(StrEnum):
    CONTINUE = "continue"
    HOLD = "hold"
    REST = "rest"
    TURN_BACK = "turn_back"
    DIVERT = "divert"
    CAMP = "camp"


class CommunicationChannel(StrEnum):
    WIFI = "wifi"
    CELLULAR = "cellular"
    SATELLITE = "satellite"
    BLUETOOTH = "bluetooth"
    LORA = "lora"
    RADIO_MODEM = "radio_modem"


class Checkpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checkpoint_id: str
    name: str
    checkpoint_type: CheckpointType = CheckpointType.WAYPOINT
    lat: float
    lon: float
    elevation_m: float | None = None
    arrival_radius_m: float = Field(default=30.0, gt=0)
    compression_boundary: bool = True
    must_emit_checkin: bool = False
    control_zone_after: str | None = None
    source: str = "gpx_wpt"


class ControlZone(BaseModel):
    model_config = ConfigDict(extra="forbid")

    zone_id: str
    zone_type: ControlZoneType = ControlZoneType.UNKNOWN
    name: str
    expected_gps_reliability: float = Field(default=0.8, ge=0.0, le=1.0)
    expected_communication_quality: float = Field(default=0.5, ge=0.0, le=1.0)
    slope_risk: float = Field(default=0.0, ge=0.0, le=1.0)
    notes: str = ""


class RecordingPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: str
    normal_profile: RecordingProfile = RecordingProfile.LOW
    watch_profile: RecordingProfile = RecordingProfile.MEDIUM
    concern_profile: RecordingProfile = RecordingProfile.RAW_LOCK
    raw_ring_seconds: int = Field(default=300, gt=0)
    checkpoint_seals_segment: bool = True


class SegmentRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_device_battery: float = Field(default=0.2, ge=0.0, le=1.0)
    min_estimated_human_energy: float = Field(default=0.35, ge=0.0, le=1.0)
    expected_duration_seconds: int = Field(default=0, ge=0)
    latest_safe_departure_time: str | None = None
    requires_daylight: bool = False
    water_available: bool = False
    camp_available: bool = False
    retreat_available: bool = False
    signal_expected: bool = True


class RouteSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str
    from_checkpoint_id: str
    to_checkpoint_id: str
    control_zone_id: str
    recording_policy_id: str
    requirement: SegmentRequirement = Field(default_factory=SegmentRequirement)
    distance_m: float = Field(default=0.0, ge=0.0)
    elevation_gain_m: float = Field(default=0.0, ge=0.0)
    elevation_loss_m: float = Field(default=0.0, ge=0.0)
    route_point_start_index: int | None = None
    route_point_end_index: int | None = None


class DiversionPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diversion_id: str
    name: str
    diversion_type: str
    lat: float
    lon: float
    distance_from_route_m: float = Field(default=0.0, ge=0.0)
    required_energy: float = Field(default=0.0, ge=0.0, le=1.0)
    required_daylight_seconds: int = Field(default=0, ge=0)
    communication_available: bool = False
    risk_level: float = Field(default=0.0, ge=0.0, le=1.0)


class ResourceState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_battery: float = Field(ge=0.0, le=1.0)
    estimated_human_energy: float = Field(ge=0.0, le=1.0)
    pace_trend: float = Field(default=1.0, ge=0.0)
    heart_rate_trend: str = "unknown"
    fatigue_score: float = Field(default=0.0, ge=0.0, le=1.0)


class EnvironmentState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weather_risk: float = Field(default=0.0, ge=0.0, le=1.0)
    temperature_c: float | None = None
    rain_probability: float = Field(default=0.0, ge=0.0, le=1.0)
    wind_speed_mps: float | None = None
    sunset_time: str | None = None
    daylight_remaining_seconds: int | None = Field(default=None, ge=0)
    visibility: str = "unknown"


class CommunicationCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: CommunicationChannel
    available: bool
    signal_strength: float | None = None
    supports_outbound: bool = False
    supports_inbound: bool = False
    supports_nearby_pull: bool = False
    estimated_delivery_confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class CommunicationState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capabilities: list[CommunicationCapability] = Field(default_factory=list)
    last_successful_uplink: str | None = None

    @property
    def best_delivery_confidence(self) -> float:
        available = [cap for cap in self.capabilities if cap.available]
        if not available:
            return 0.0
        return max(cap.estimated_delivery_confidence for cap in available)


class GoNoGoDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: GoNoGoAction
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)
    deadline: str | None = None
    next_safe_option: str | None = None


class SegmentCapsule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capsule_id: str
    segment_id: str
    started_at: float | None = None
    ended_at: float | None = None
    start_checkpoint_id: str
    end_checkpoint_id: str
    trajectory_summary: dict = Field(default_factory=dict)
    sensor_summary: dict = Field(default_factory=dict)
    signal_summary: dict = Field(default_factory=dict)
    resource_summary: dict = Field(default_factory=dict)
    safety_event_ids: list[str] = Field(default_factory=list)
    evidence_hash: str | None = None


class MissionGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mission_id: str
    name: str
    route_source: str
    checkpoints: list[Checkpoint]
    control_zones: list[ControlZone]
    recording_policies: list[RecordingPolicy]
    segments: list[RouteSegment]
    diversion_points: list[DiversionPoint] = Field(default_factory=list)

    def checkpoint_by_id(self, checkpoint_id: str) -> Checkpoint:
        for checkpoint in self.checkpoints:
            if checkpoint.checkpoint_id == checkpoint_id:
                return checkpoint
        raise KeyError(checkpoint_id)
