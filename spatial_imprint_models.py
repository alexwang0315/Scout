from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from voice_cue_models import VoiceCueCategory, VoiceCuePriority, VoiceCueSourceKind


class SpatialImprintBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SpatialImprintKind(StrEnum):
    ROUTE_WARNING = "route_warning"
    ROUTE_GUIDANCE = "route_guidance"
    REST_POINT = "rest_point"
    RISK_ZONE_WARNING = "risk_zone_warning"
    TEAM_NOTICE = "team_notice"
    ENVIRONMENT_CUE = "environment_cue"


class SpatialImprintSeverity(StrEnum):
    INFO = "info"
    CAUTION = "caution"
    WARNING = "warning"
    URGENT = "urgent"


class SpatialImprintPlantingSource(StrEnum):
    PRETRIP_REVIEWED = "pretrip_reviewed"
    AGENT_PROPOSED = "agent_proposed"
    OPERATOR_RUNTIME = "operator_runtime"
    USER_RUNTIME = "user_runtime"
    SYSTEM_CANDIDATE = "system_candidate"


class SpatialImprintLifecycleState(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    DELETED_TOMBSTONE = "deleted_tombstone"


class SpatialImprintLifecycleScope(StrEnum):
    TRIP_SCOPED = "trip_scoped"
    TTL_SCOPED = "ttl_scoped"
    ADMIN_PERSISTENT = "admin_persistent"


class SpatialImprintActor(SpatialImprintBaseModel):
    actor_type: Literal["operator", "user", "agent", "system"]
    actor_ref: str = Field(min_length=1)


class SpatialImprintCoordinate(SpatialImprintBaseModel):
    lat: float = Field(ge=-90.0, le=90.0)
    lon: float = Field(ge=-180.0, le=180.0)
    altitude_m: float | None = None
    horizontal_accuracy_m: float | None = Field(default=None, ge=0.0)
    vertical_accuracy_m: float | None = Field(default=None, ge=0.0)


class SpatialImprintAnchor(SpatialImprintBaseModel):
    anchor_type: Literal[
        "point_3d",
        "route_progress",
        "cp",
        "segment",
        "risk_zone",
        "sensor_state",
    ]
    route_id: str | None = Field(default=None, min_length=1)
    segment_ref: str | None = Field(default=None, min_length=1)
    cp_ref: str | None = Field(default=None, min_length=1)
    risk_zone_ref: str | None = Field(default=None, min_length=1)
    distance_m: float | None = Field(default=None, ge=0.0)
    trigger_before_m: float | None = Field(default=None, ge=0.0)
    coordinate: SpatialImprintCoordinate | None = None


class SpatialImprintPredicate(SpatialImprintBaseModel):
    type: Literal[
        "horizontal_radius",
        "altitude_range",
        "vertical_delta_from_anchor",
        "heading_sector",
        "route_progress_window",
        "before_cp",
        "inside_cp_radius",
        "inside_segment",
        "inside_risk_zone",
        "risk_score_min",
        "sensor_state",
        "time_window",
        "client_group_match",
        "all",
        "any",
    ]
    lat: float | None = Field(default=None, ge=-90.0, le=90.0)
    lon: float | None = Field(default=None, ge=-180.0, le=180.0)
    radius_m: float | None = Field(default=None, ge=0.0)
    min_m: float | None = None
    max_m: float | None = None
    center_degrees: float | None = Field(default=None, ge=0.0, lt=360.0)
    half_width_degrees: float | None = Field(default=None, ge=0.0, le=180.0)
    start_distance_m: float | None = Field(default=None, ge=0.0)
    end_distance_m: float | None = Field(default=None, ge=0.0)
    cp_ref: str | None = Field(default=None, min_length=1)
    segment_ref: str | None = Field(default=None, min_length=1)
    risk_zone_ref: str | None = Field(default=None, min_length=1)
    risk_score_min: float | None = Field(default=None, ge=0.0)
    client_group_ref: str | None = Field(default=None, min_length=1)
    requires_barometer: bool | None = None
    requires_magnetometer: bool | None = None
    requires_imu: bool | None = None
    requires_gnss_confidence_min: float | None = Field(default=None, ge=0.0, le=1.0)
    requires_pdr_confidence_min: float | None = Field(default=None, ge=0.0, le=1.0)
    starts_at: str | None = None
    ends_at: str | None = None
    predicates: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_shape(self) -> "SpatialImprintPredicate":
        if self.type == "horizontal_radius":
            _require(self.lat is not None, "horizontal_radius requires lat")
            _require(self.lon is not None, "horizontal_radius requires lon")
            _require(self.radius_m is not None, "horizontal_radius requires radius_m")
        elif self.type == "altitude_range":
            _require(self.min_m is not None, "altitude_range requires min_m")
            _require(self.max_m is not None, "altitude_range requires max_m")
            _require(self.min_m <= self.max_m, "altitude_range min_m must be <= max_m")
        elif self.type == "vertical_delta_from_anchor":
            _require(self.min_m is not None, "vertical_delta_from_anchor requires min_m")
            _require(self.max_m is not None, "vertical_delta_from_anchor requires max_m")
            _require(
                self.min_m <= self.max_m,
                "vertical_delta_from_anchor min_m must be <= max_m",
            )
        elif self.type == "heading_sector":
            _require(self.center_degrees is not None, "heading_sector requires center_degrees")
            _require(self.half_width_degrees is not None, "heading_sector requires half_width_degrees")
        elif self.type == "route_progress_window":
            _require(self.start_distance_m is not None, "route_progress_window requires start_distance_m")
            _require(self.end_distance_m is not None, "route_progress_window requires end_distance_m")
            _require(
                self.start_distance_m <= self.end_distance_m,
                "route_progress_window start_distance_m must be <= end_distance_m",
            )
        elif self.type == "before_cp":
            _require(self.cp_ref is not None, "before_cp requires cp_ref")
            _require(self.radius_m is not None, "before_cp requires radius_m")
        elif self.type == "inside_cp_radius":
            _require(self.cp_ref is not None, "inside_cp_radius requires cp_ref")
            _require(self.radius_m is not None, "inside_cp_radius requires radius_m")
        elif self.type == "inside_segment":
            _require(self.segment_ref is not None, "inside_segment requires segment_ref")
        elif self.type == "inside_risk_zone":
            _require(self.risk_zone_ref is not None, "inside_risk_zone requires risk_zone_ref")
        elif self.type == "risk_score_min":
            _require(self.risk_score_min is not None, "risk_score_min requires risk_score_min")
        elif self.type == "client_group_match":
            _require(self.client_group_ref is not None, "client_group_match requires client_group_ref")
        elif self.type in {"all", "any"}:
            _require(bool(self.predicates), f"{self.type} requires predicates")
        return self

    @field_validator("starts_at", "ends_at")
    @classmethod
    def validate_iso_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        _parse_datetime(value)
        return value


class SpatialImprintConfidencePolicy(SpatialImprintBaseModel):
    min_position_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    allow_sensor_degraded: bool = True
    reason_if_degraded: str | None = None


class SpatialImprintTrigger(SpatialImprintBaseModel):
    operator: Literal["all", "any"] = "all"
    predicates: list[SpatialImprintPredicate] = Field(default_factory=list)
    confidence_policy: SpatialImprintConfidencePolicy = Field(
        default_factory=SpatialImprintConfidencePolicy
    )

    @model_validator(mode="after")
    def require_predicates(self) -> "SpatialImprintTrigger":
        if not self.predicates:
            raise ValueError("spatial imprint trigger requires at least one predicate")
        return self


class SpatialImprintPayload(SpatialImprintBaseModel):
    payload_type: Literal[
        "voice_cue",
        "ui_cue",
        "haptic_cue",
        "note_append",
        "leader_message",
        "local_alarm",
    ]
    text_zh: str | None = Field(default=None, min_length=1)
    voice_priority: VoiceCuePriority = "info"
    voice_category: VoiceCueCategory = "route"
    source_kind: VoiceCueSourceKind = "deterministic_fact"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_payload(self) -> "SpatialImprintPayload":
        if self.payload_type in {"voice_cue", "ui_cue", "leader_message"} and not self.text_zh:
            raise ValueError(f"{self.payload_type} requires text_zh")
        return self


class SpatialImprintAudience(SpatialImprintBaseModel):
    scope: Literal[
        "registered_trip_clients",
        "leader_only",
        "specific_clients",
        "scout_centre_clients",
        "all_registered_clients",
    ] = "registered_trip_clients"
    client_group_refs: list[str] = Field(default_factory=list)
    client_refs: list[str] = Field(default_factory=list)
    exclude_actor_refs: list[str] = Field(default_factory=list)
    requires_active_trip_membership: bool = True


class SpatialImprintLifecycle(SpatialImprintBaseModel):
    state: SpatialImprintLifecycleState = SpatialImprintLifecycleState.ACTIVE
    scope: SpatialImprintLifecycleScope = SpatialImprintLifecycleScope.TRIP_SCOPED
    ttl_seconds: int | None = Field(default=None, ge=1)
    expires_at: str | None = None
    delete_requires_admin: bool = True

    @field_validator("expires_at")
    @classmethod
    def validate_expires_at(cls, value: str | None) -> str | None:
        if value is None:
            return None
        _parse_datetime(value)
        return value


class SpatialImprintTriggerPolicy(SpatialImprintBaseModel):
    once_per_client: bool = True
    retrigger_after_seconds: int | None = Field(default=None, ge=1)
    rearm_distance_m: float | None = Field(default=None, ge=0.0)
    dedupe_key: str | None = Field(default=None, min_length=1)
    suppress_if_acknowledged: bool = True


class SpatialImprintSourceRef(SpatialImprintBaseModel):
    source_id: str = Field(min_length=1)
    source_path: str | None = None
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    evidence_type: str | None = None


class SpatialImprintBoundary(SpatialImprintBaseModel):
    advisory_cue: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    phase1_safety_mutation_allowed: Literal[False] = False
    live_safety_api_calls_allowed: Literal[False] = False
    model_output_is_trigger_truth: Literal[False] = False
    remote_outbound_send_allowed: Literal[False] = False
    hardware_control_allowed: Literal[False] = False


class SpatialImprint(SpatialImprintBaseModel):
    imprint_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.:-]+$")
    schema_version: str = "0.1.0"
    label: str = Field(min_length=1)
    kind: SpatialImprintKind
    severity: SpatialImprintSeverity = SpatialImprintSeverity.INFO
    planting_source: SpatialImprintPlantingSource
    created_at: str
    created_by: SpatialImprintActor
    anchor: SpatialImprintAnchor
    trigger: SpatialImprintTrigger
    payload: SpatialImprintPayload
    audience: SpatialImprintAudience = Field(default_factory=SpatialImprintAudience)
    lifecycle: SpatialImprintLifecycle = Field(default_factory=SpatialImprintLifecycle)
    trigger_policy: SpatialImprintTriggerPolicy = Field(
        default_factory=SpatialImprintTriggerPolicy
    )
    source_refs: list[SpatialImprintSourceRef] = Field(default_factory=list)
    boundary: SpatialImprintBoundary = Field(default_factory=SpatialImprintBoundary)

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: str) -> str:
        _parse_datetime(value)
        return value

    @property
    def dedupe_key(self) -> str:
        return self.trigger_policy.dedupe_key or self.imprint_id


class SpatialImprintSet(SpatialImprintBaseModel):
    artifact_kind: Literal["spatial_imprint_set"] = "spatial_imprint_set"
    schema_version: str = "0.1.0"
    trip_id: str = Field(min_length=1)
    imprints: list[SpatialImprint] = Field(default_factory=list)
    boundary: SpatialImprintBoundary = Field(default_factory=SpatialImprintBoundary)


class SpatialImprintPosition(SpatialImprintBaseModel):
    lat: float = Field(ge=-90.0, le=90.0)
    lon: float = Field(ge=-180.0, le=180.0)
    altitude_m: float | None = None
    horizontal_accuracy_m: float | None = Field(default=None, ge=0.0)
    vertical_accuracy_m: float | None = Field(default=None, ge=0.0)
    source: str | None = None


class SpatialImprintMotion(SpatialImprintBaseModel):
    heading_degrees: float | None = Field(default=None, ge=0.0, lt=360.0)
    heading_source: str | None = None
    speed_mps: float | None = Field(default=None, ge=0.0)
    stationary: bool | None = None


class SpatialImprintRouteProgress(SpatialImprintBaseModel):
    route_id: str | None = None
    segment_ref: str | None = None
    progress_m: float | None = Field(default=None, ge=0.0)
    nearest_cp_ref: str | None = None
    distance_to_nearest_cp_m: float | None = Field(default=None, ge=0.0)


class SpatialImprintRiskContext(SpatialImprintBaseModel):
    risk_score: float | None = Field(default=None, ge=0.0)
    risk_zone_refs: list[str] = Field(default_factory=list)


class SpatialImprintSensorState(SpatialImprintBaseModel):
    barometer_available: bool = False
    magnetometer_available: bool = False
    imu_available: bool = False
    gnss_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    pdr_confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class SpatialImprintTriggerContext(SpatialImprintBaseModel):
    client_id: str = Field(min_length=1)
    scout_machine_id: str = Field(min_length=1)
    trip_id: str = Field(min_length=1)
    observed_at: str
    client_group_refs: list[str] = Field(default_factory=list)
    position: SpatialImprintPosition | None = None
    motion: SpatialImprintMotion = Field(default_factory=SpatialImprintMotion)
    route_progress: SpatialImprintRouteProgress = Field(
        default_factory=SpatialImprintRouteProgress
    )
    risk_context: SpatialImprintRiskContext = Field(default_factory=SpatialImprintRiskContext)
    sensor_state: SpatialImprintSensorState = Field(default_factory=SpatialImprintSensorState)

    @field_validator("observed_at")
    @classmethod
    def validate_observed_at(cls, value: str) -> str:
        _parse_datetime(value)
        return value


class SpatialPredicateEvaluation(SpatialImprintBaseModel):
    predicate_type: str = Field(min_length=1)
    matched: bool
    reason: str
    details: dict[str, Any] = Field(default_factory=dict)


class SpatialImprintQueuedPayload(SpatialImprintBaseModel):
    payload_type: str = Field(min_length=1)
    cue_id: str | None = None
    text_zh: str | None = None


class SpatialImprintTriggerEvent(SpatialImprintBaseModel):
    event_id: str = Field(min_length=1)
    imprint_id: str = Field(min_length=1)
    client_id: str = Field(min_length=1)
    triggered_at: str
    status: Literal["triggered", "not_triggered", "suppressed", "expired", "inactive"]
    matched_predicates: list[str] = Field(default_factory=list)
    failed_predicates: list[SpatialPredicateEvaluation] = Field(default_factory=list)
    suppressed: bool = False
    suppression_reason: str | None = None
    queued_payload: SpatialImprintQueuedPayload | None = None
    boundary: SpatialImprintBoundary = Field(default_factory=SpatialImprintBoundary)

    @field_validator("triggered_at")
    @classmethod
    def validate_triggered_at(cls, value: str) -> str:
        _parse_datetime(value)
        return value


class SpatialImprintTriggerDryRunReport(SpatialImprintBaseModel):
    artifact_kind: Literal["spatial_imprint_trigger_dry_run"] = (
        "spatial_imprint_trigger_dry_run"
    )
    schema_version: str = "0.1.0"
    trip_id: str
    client_id: str
    observed_at: str
    events: list[SpatialImprintTriggerEvent]
    counts: dict[str, int]
    boundary: SpatialImprintBoundary = Field(default_factory=SpatialImprintBoundary)


def parse_spatial_datetime(value: str) -> datetime:
    return _parse_datetime(value)


def spatial_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)
