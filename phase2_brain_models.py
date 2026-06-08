from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BrainNodeType(StrEnum):
    MISSION = "Mission"
    TEAM = "Team"
    PERSON = "Person"
    DEVICE = "Device"
    EQUIPMENT = "Equipment"
    ROUTE = "Route"
    SEGMENT = "Segment"
    CHECKPOINT = "Checkpoint"
    OBSERVED_FACT = "ObservedFact"
    DERIVED_MEASUREMENT = "DerivedMeasurement"
    MODEL_INTERPRETATION = "ModelInterpretation"
    HUMAN_REVIEW = "HumanReview"
    SKILL_DEFINITION = "SkillDefinition"
    SKILL_RUN_RECORD = "SkillRunRecord"
    ARTIFACT = "Artifact"
    REMOTE_STATUS_ARTIFACT = "RemoteStatusArtifact"
    DECISION_OPTION_SET = "DecisionOptionSet"
    BEACON_NODE = "BeaconNode"
    TEAM_SEPARATION_EVENT = "TeamSeparationEvent"
    SIGNAL_BEARING_MEASUREMENT = "SignalBearingMeasurement"


class BrainWritePolicy(StrEnum):
    AUTOMATIC = "automatic"
    APPEND_ONLY_REQUIRES_REVIEW = "append_only_requires_review"
    HUMAN_REVIEWED = "human_reviewed"
    MANUAL = "manual"


class ConfidenceLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class ArtifactKind(StrEnum):
    RAW_LOG = "raw_log"
    GPX = "gpx"
    GEOJSON = "geojson"
    PHOTO = "photo"
    INCIDENT_PACKAGE = "incident_package"
    SEGMENT_CAPSULE = "segment_capsule"
    REPLAY_OUTPUT = "replay_output"
    REMOTE_STATUS_JSON = "remote_status_json"
    BEACON_SCAN = "beacon_scan"
    OTHER = "other"


class BrainNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: BrainNodeType
    mission_id: str | None = None
    created_at: str | None = None
    artifact_refs: list[str] = Field(default_factory=list)


class Mission(BrainNode):
    type: Literal[BrainNodeType.MISSION] = BrainNodeType.MISSION

    name: str
    mission_owner: str
    team_id: str
    route_id: str
    started_at: str | None = None
    ended_at: str | None = None
    status: Literal["planned", "active", "completed", "cancelled"] = "planned"


class Team(BrainNode):
    type: Literal[BrainNodeType.TEAM] = BrainNodeType.TEAM

    name: str
    leader_id: str
    member_ids: list[str] = Field(default_factory=list)
    remote_contact_ids: list[str] = Field(default_factory=list)


class Person(BrainNode):
    type: Literal[BrainNodeType.PERSON] = BrainNodeType.PERSON

    display_name: str
    role: Literal["leader", "member", "remote_contact", "reviewer"] = "member"
    device_ids: list[str] = Field(default_factory=list)


class Device(BrainNode):
    type: Literal[BrainNodeType.DEVICE] = BrainNodeType.DEVICE

    owner_id: str | None = None
    device_type: str
    platform: str
    capabilities: list[str] = Field(default_factory=list)


class Equipment(BrainNode):
    type: Literal[BrainNodeType.EQUIPMENT] = BrainNodeType.EQUIPMENT

    owner_id: str | None = None
    equipment_type: str
    name: str
    status: Literal["available", "limited", "unavailable", "unknown"] = "unknown"


class Route(BrainNode):
    type: Literal[BrainNodeType.ROUTE] = BrainNodeType.ROUTE

    name: str
    route_type: Literal["loop", "out_and_back", "traverse", "expedition", "unknown"] = "unknown"
    checkpoint_ids: list[str] = Field(default_factory=list)
    segment_ids: list[str] = Field(default_factory=list)
    source_artifact_refs: list[str] = Field(default_factory=list)


class Segment(BrainNode):
    type: Literal[BrainNodeType.SEGMENT] = BrainNodeType.SEGMENT

    route_id: str
    from_checkpoint_id: str
    to_checkpoint_id: str
    planned_distance_m: float = Field(default=0.0, ge=0.0)
    planned_duration_seconds: int = Field(default=0, ge=0)


class Checkpoint(BrainNode):
    type: Literal[BrainNodeType.CHECKPOINT] = BrainNodeType.CHECKPOINT

    route_id: str
    name: str
    lat: float
    lon: float
    planned_arrival_at: str | None = None
    arrival_radius_m: float = Field(default=30.0, gt=0.0)


class Artifact(BrainNode):
    type: Literal[BrainNodeType.ARTIFACT] = BrainNodeType.ARTIFACT

    artifact_kind: ArtifactKind
    uri: str
    media_type: str | None = None
    sha256: str | None = None
    captured_at: str | None = None
    metadata: dict = Field(default_factory=dict)


class ObservedFact(BrainNode):
    type: Literal[BrainNodeType.OBSERVED_FACT] = BrainNodeType.OBSERVED_FACT

    subject: str
    predicate: str
    object: str | int | float | bool | None = None
    observed_at: str
    evidence: list[str] = Field(default_factory=list, min_length=1)
    confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN
    write_policy: Literal[BrainWritePolicy.AUTOMATIC] = BrainWritePolicy.AUTOMATIC


class DerivedMeasurement(BrainNode):
    type: Literal[BrainNodeType.DERIVED_MEASUREMENT] = BrainNodeType.DERIVED_MEASUREMENT

    subject: str
    metric: str
    value: str | int | float | bool
    unit: str | None = None
    derived_from: list[str] = Field(default_factory=list, min_length=1)
    method: str
    write_policy: Literal[BrainWritePolicy.AUTOMATIC] = BrainWritePolicy.AUTOMATIC


class ModelInterpretation(BrainNode):
    type: Literal[BrainNodeType.MODEL_INTERPRETATION] = BrainNodeType.MODEL_INTERPRETATION

    subject: str
    model: str
    model_version: str
    claim: str
    input_refs: list[str] = Field(default_factory=list, min_length=1)
    generated_at: str
    write_policy: Literal[BrainWritePolicy.APPEND_ONLY_REQUIRES_REVIEW] = (
        BrainWritePolicy.APPEND_ONLY_REQUIRES_REVIEW
    )


class HumanReview(BrainNode):
    type: Literal[BrainNodeType.HUMAN_REVIEW] = BrainNodeType.HUMAN_REVIEW

    reviewer_id: str
    reviewed_ref: str
    reviewed_at: str
    decision: Literal["accepted", "rejected", "corrected", "noted"]
    notes: str = ""
    correction_refs: list[str] = Field(default_factory=list)
    write_policy: Literal[BrainWritePolicy.HUMAN_REVIEWED] = BrainWritePolicy.HUMAN_REVIEWED


class SkillDefinition(BrainNode):
    type: Literal[BrainNodeType.SKILL_DEFINITION] = BrainNodeType.SKILL_DEFINITION

    skill_id: str
    version: str
    status: Literal["candidate", "experimental", "field_trial", "stable", "deprecated", "disabled"]
    manifest_ref: str


class SkillRunRecord(BrainNode):
    type: Literal[BrainNodeType.SKILL_RUN_RECORD] = BrainNodeType.SKILL_RUN_RECORD

    skill_id: str
    skill_version: str
    started_at: str
    ended_at: str | None = None
    activation_decision: Literal["allow", "disallow", "defer", "degrade"]
    input_refs: list[str] = Field(default_factory=list)
    output_refs: list[str] = Field(default_factory=list)
    preflight_results: dict = Field(default_factory=dict)
    failure_policy: dict = Field(default_factory=dict)


class RemoteStatusArtifact(BrainNode):
    type: Literal[BrainNodeType.REMOTE_STATUS_ARTIFACT] = BrainNodeType.REMOTE_STATUS_ARTIFACT

    generated_at: str
    freshness_seconds: int = Field(ge=0)
    status: str
    team_summary: dict = Field(default_factory=dict)
    latest_checkpoint: str | None = None
    next_checkpoint: str | None = None
    safety_level: str
    uncertainty: ConfidenceLevel = ConfidenceLevel.UNKNOWN
    message: str


class DecisionOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    action: str
    estimated_time_minutes: int | None = Field(default=None, ge=0)
    resource_cost: Literal["low", "medium", "high", "unknown"] = "unknown"
    daylight_risk: Literal["low", "medium", "high", "unknown"] = "unknown"
    communication_chance: Literal["low", "medium", "high", "unknown"] = "unknown"
    team_impact: str = ""
    reversibility: Literal["low", "medium", "high", "unknown"] = "unknown"
    failure_modes: list[str] = Field(default_factory=list)
    confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN


class DecisionOptionSet(BrainNode):
    type: Literal[BrainNodeType.DECISION_OPTION_SET] = BrainNodeType.DECISION_OPTION_SET

    generated_at: str
    current_safety_level: str
    pilot_in_command: str
    options: list[DecisionOption] = Field(default_factory=list, min_length=1)
    scout_preference: dict = Field(default_factory=dict)
    input_refs: list[str] = Field(default_factory=list)


class BeaconNode(BrainNode):
    type: Literal[BrainNodeType.BEACON_NODE] = BrainNodeType.BEACON_NODE

    source_device_id: str
    designated_at: str
    mode: Literal["mock", "wifi_softap", "ble", "lora", "uwb", "generic_radio"] = "mock"
    rendezvous_ref: str | None = None
    uncertainty: ConfidenceLevel = ConfidenceLevel.UNKNOWN
    active: bool = True


class TeamSeparationEvent(BrainNode):
    type: Literal[BrainNodeType.TEAM_SEPARATION_EVENT] = BrainNodeType.TEAM_SEPARATION_EVENT

    team_id: str
    detected_at: str
    member_ids: list[str] = Field(default_factory=list, min_length=1)
    evidence_refs: list[str] = Field(default_factory=list, min_length=1)
    severity: Literal["possible", "likely", "confirmed"] = "possible"
    reason: str


class SignalBearingMeasurement(BrainNode):
    type: Literal[BrainNodeType.SIGNAL_BEARING_MEASUREMENT] = BrainNodeType.SIGNAL_BEARING_MEASUREMENT

    beacon_id: str
    observer_device_id: str
    measured_at: str
    signal_type: Literal["mock", "wifi", "ble", "lora", "uwb", "generic_radio"] = "mock"
    trend: Literal["improving", "weakening", "stable", "lost", "unknown"]
    confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN
    evidence_refs: list[str] = Field(default_factory=list, min_length=1)
    direction_hint: str | None = None
    exact_position_claimed: bool = False

    @model_validator(mode="after")
    def reject_precise_position_claim(self) -> SignalBearingMeasurement:
        if self.exact_position_claimed:
            raise ValueError("SignalBearingMeasurement cannot claim exact position from signal trend")
        return self
