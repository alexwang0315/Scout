from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


Confidence = Literal["high", "medium", "low"]


class RestDetectionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_version: str = "rest_detection.v1"
    rest_speed_threshold_kmh: float = Field(default=0.5, ge=0.0)
    rest_radius_m: float = Field(default=20.0, ge=0.0)
    min_rest_duration_s: int = Field(default=180, ge=0)
    max_sample_gap_s: int = Field(default=900, ge=0)
    max_segment_distance_deviation_ratio: float = Field(default=0.35, ge=0.0)


class SourceTrackRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    source_path: str
    sha256: str


class CapabilityNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    label: str
    lat: float
    lon: float
    source_refs: list[str]


class RestInterval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rest_id: str
    start_index: int
    end_index: int
    start_offset_s: int
    end_offset_s: int
    duration_s: int
    lat: float
    lon: float
    classification: str = "detected_rest"
    confidence: Confidence = "medium"
    source_refs: list[str]


class CapabilityEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edge_id: str
    segment_id: str
    from_node_id: str
    to_node_id: str
    direction: str = "outbound"
    elapsed_time_s: int
    moving_time_s: int
    rest_time_s: int
    distance_m: float
    ascent_m: float | None = None
    descent_m: float | None = None
    rest_intervals: list[str] = Field(default_factory=list)
    confidence: Confidence
    source_refs: list[str]
    limitations: list[str] = Field(default_factory=list)
    terrain_context: dict[str, Any] = Field(default_factory=dict)
    risk_context: dict[str, Any] = Field(default_factory=dict)
    guide_time_min: int | None = None


class CapabilitySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    elapsed_time_s: int
    moving_time_s: int
    rest_time_s: int
    moving_ratio: float
    distance_m: float
    ascent_m: float | None = None
    descent_m: float | None = None
    moving_pace_min_per_km: float | None = None
    ascent_m_per_hour_moving: float | None = None
    descent_m_per_hour_moving: float | None = None


class PostAnalysisBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    post_analysis_only: bool = True
    phase1_runtime_mutation_allowed: bool = False
    safety_api_calls_allowed: bool = False
    mission_graph_rewrite_allowed: bool = False
    incident_package_rewrite_allowed: bool = False
    raw_track_shared_by_default: bool = False
    runtime_safety_truth: bool = False


class CapabilityDataQuality(BaseModel):
    model_config = ConfigDict(extra="forbid")

    missing_timestamp_count: int = 0
    suspicious_timestamp_count: int = 0
    gps_gap_count: int = 0
    ambiguous_checkpoint_count: int = 0
    low_point_segment_count: int = 0
    route_deviation_count: int = 0
    low_confidence_edge_count: int = 0
    limitations: list[str] = Field(default_factory=list)


class CapabilityTimelineArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "post_analysis_capability_timeline"
    artifact_version: str = "capability_timeline.v1"
    case_id: str
    route_family: str
    source_track: SourceTrackRef
    rest_detection_policy: RestDetectionPolicy
    nodes: list[CapabilityNode]
    edges: list[CapabilityEdge]
    rest_intervals: list[RestInterval]
    summary: CapabilitySummary
    data_quality: CapabilityDataQuality = Field(default_factory=CapabilityDataQuality)
    analysis_context: dict[str, Any] = Field(default_factory=dict)
    boundary: PostAnalysisBoundary = Field(default_factory=PostAnalysisBoundary)


class CapabilityCapsuleArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "post_analysis_capability_capsule"
    artifact_version: str = "capability_capsule.v1"
    case_id: str
    route_family: str
    source_scope: str = "completed_run_summary_only"
    raw_track_shared: bool = False
    exact_timestamps_shared: bool = False
    incident_details_shared: bool = False
    moving_time_min: int
    elapsed_time_min: int
    rest_time_min: int
    distance_km: float
    ascent_m: float | None = None
    descent_m: float | None = None
    ascent_m_per_hour_moving: float | None = None
    descent_m_per_hour_moving: float | None = None
    moving_pace_min_per_km: float | None = None
    terrain_adjusted_level: str = "unclassified"
    confidence: Confidence
    limitations: list[str]
    boundary: PostAnalysisBoundary = Field(default_factory=PostAnalysisBoundary)


class RouteTimeComparisonSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comparison_id: str
    edge_id: str
    segment_id: str
    route_time_source: str
    comparison_basis: str = "moving_time"
    guide_time_min: int
    user_moving_time_min: int
    user_elapsed_time_min: int
    delta_vs_guide_moving_min: int
    confidence: Confidence
    source_refs: list[str]


class RouteTimeComparisonArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "post_analysis_route_time_comparison"
    artifact_version: str = "route_time_comparison.v1"
    case_id: str
    route_family: str
    route_time_source: str
    comparison_basis: str = "moving_time"
    segments: list[RouteTimeComparisonSegment]
    summary: dict[str, Any]
    boundary: PostAnalysisBoundary = Field(default_factory=PostAnalysisBoundary)


class CapabilitySharePreviewArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "post_analysis_capability_share_preview"
    artifact_version: str = "capability_share_preview.v1"
    case_id: str
    route_family: str
    export_requires_confirmation: bool = True
    included_fields: dict[str, Any]
    excluded_fields: dict[str, bool]
    limitations: list[str]
    boundary: PostAnalysisBoundary = Field(default_factory=PostAnalysisBoundary)


class CapabilityArtifactFiles(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timeline_path: str
    capsule_path: str
    comparison_path: str | None = None
    csv_summary_path: str | None = None
    share_preview_path: str | None = None
    exported_capsule_path: str | None = None
    timeline: dict[str, Any]
    capsule: dict[str, Any]
    comparison: dict[str, Any] | None = None
    share_preview: dict[str, Any] | None = None
