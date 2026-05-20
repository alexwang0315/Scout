from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PreTripArtifactKind(StrEnum):
    GPX = "gpx"
    PHOTO = "photo"
    DTM_TILE = "dtm_tile"
    DTM_COVERAGE_SUMMARY = "dtm_coverage_summary"
    PRETRIP_PACKAGE = "pretrip_package"
    CHECKPOINT_CANDIDATES = "checkpoint_candidates"
    SEGMENT_CANDIDATES = "segment_candidates"
    RETREAT_ROUTE_CANDIDATES = "retreat_route_candidates"
    PLANNING_REFERENCES = "planning_references"
    ROUTE_GUIDE_TIMING_CANDIDATES = "route_guide_timing_candidates"
    SEGMENT_TERRAIN_SUMMARY = "segment_terrain_summary"
    READINESS_REPORT = "readiness_report"
    SKILL_CONFIG_MANIFEST = "skill_config_manifest"
    OTHER = "other"


class CandidateReviewState(StrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    NEEDS_REVIEW = "needs_review"


class PaceMultiplierBasis(StrEnum):
    TOTAL_ELAPSED_TIME = "total_elapsed_time"
    MOVING_TIME_ONLY = "moving_time_only"
    MIXED_UNKNOWN = "mixed_unknown"


class RouteBBox(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float


class ProjectedBBox(BaseModel):
    model_config = ConfigDict(extra="forbid")

    crs: str
    min_x: float
    min_y: float
    max_x: float
    max_y: float


class PreTripProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_ref: str
    source_kind: PreTripArtifactKind
    uri: str
    captured_at: str | None = None
    collected_at: str | None = None
    license_note: str | None = None
    method: str
    notes: str = ""


class PreTripSourceArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    kind: PreTripArtifactKind
    uri: str
    media_type: str | None = None
    sha256: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    provenance: PreTripProvenance
    metadata: dict = Field(default_factory=dict)


class PreTripPlanningReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference_id: str
    title: str
    uri: str
    reference_type: Literal["reference_product", "community_timing_evidence", "route_planning_method"]
    scout_meaning: str
    artifact_treatment: list[
        Literal["Artifact", "ModelInterpretation", "HumanReview", "DerivedMeasurement"]
    ] = Field(default_factory=list)
    not_observed_fact: bool = True
    supported_primitives: list[str] = Field(default_factory=list)
    notes: str = ""


class PreTripRouteSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    route_name: str
    point_count: int = Field(gt=0)
    distance_m: float = Field(ge=0.0)
    bbox_wgs84: RouteBBox
    elevation_min_m: float | None = None
    elevation_max_m: float | None = None
    started_at: str | None = None
    ended_at: str | None = None


class DtmTileCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tile_id: str
    county: str
    header_uri: str
    grid_uri: str | None = None
    horizontal_datum: str
    vertical_datum: str
    resolution_x_m: float = Field(gt=0.0)
    resolution_y_m: float = Field(gt=0.0)
    rows: int = Field(gt=0)
    cols: int = Field(gt=0)
    origin_x: float
    origin_y: float
    bbox_twd97: ProjectedBBox
    intersects_route_bbox: bool = True
    coverage_note: str = ""


class DtmCoverageSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary_id: str
    route_artifact_id: str
    source_dirs: list[str] = Field(default_factory=list)
    route_bbox_wgs84: RouteBBox
    route_bbox_twd97: ProjectedBBox
    candidate_tiles: list[DtmTileCandidate] = Field(default_factory=list)
    scanned_header_count: int = Field(ge=0)
    missing_grid_count: int = Field(ge=0)
    notes: str = ""


class PreTripCandidateBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    label: str
    source_refs: list[str] = Field(default_factory=list)
    provenance: list[PreTripProvenance] = Field(default_factory=list)
    review_state: CandidateReviewState = CandidateReviewState.PROPOSED
    confidence: Literal["low", "medium", "high", "unknown"] = "unknown"
    notes: str = ""


class PreTripCheckpointCandidate(PreTripCandidateBase):
    lat: float
    lon: float
    route_point_index: int | None = Field(default=None, ge=0)
    checkpoint_type: str = "waypoint"
    arrival_radius_m: float = Field(default=30.0, gt=0.0)
    compression_boundary: bool = True


class PreTripSegmentCandidate(PreTripCandidateBase):
    from_candidate_id: str
    to_candidate_id: str
    route_point_start_index: int | None = Field(default=None, ge=0)
    route_point_end_index: int | None = Field(default=None, ge=0)
    distance_m: float = Field(default=0.0, ge=0.0)
    elevation_gain_m: float = Field(default=0.0, ge=0.0)
    elevation_loss_m: float = Field(default=0.0, ge=0.0)


class PreTripRetreatRouteCandidate(PreTripCandidateBase):
    retreat_type: Literal["return_to_entry", "alternate_route", "evacuation_exit"] = "return_to_entry"
    entry_checkpoint_candidate_id: str
    trigger_checkpoint_candidate_id: str | None = None
    route_point_start_index: int | None = Field(default=None, ge=0)
    route_point_end_index: int | None = Field(default=None, ge=0)
    reversed_from_primary_route: bool = True
    distance_m: float = Field(default=0.0, ge=0.0)
    expected_use: Literal["retreat", "alternate", "both"] = "both"
    human_review_required: bool = True


class PreTripRouteGuideTimingCandidate(PreTripCandidateBase):
    segment_candidate_id: str | None = None
    route_branch: str | None = None
    from_node_name: str | None = None
    to_node_name: str | None = None
    movement_label: str | None = None
    route_guide_segment_time_minutes: int | None = Field(default=None, ge=0)
    route_guide_return_time_minutes: int | None = Field(default=None, ge=0)
    route_guide_ascent_time_minutes: int | None = Field(default=None, ge=0)
    route_guide_descent_time_minutes: int | None = Field(default=None, ge=0)
    personal_route_guide_multiplier: float | None = Field(default=None, gt=0.0)
    team_route_guide_multiplier: float | None = Field(default=None, gt=0.0)
    pace_multiplier_basis: PaceMultiplierBasis = PaceMultiplierBasis.MIXED_UNKNOWN
    fixed_rest_minutes: int = Field(default=0, ge=0)
    conservative_long_day_adjustment: float = Field(default=1.0, ge=1.0)
    eta_at_checkpoint: str | None = None
    eta_at_camp_or_overnight_point: str | None = None
    dark_arrival_margin_minutes: int | None = None
    planned_vs_actual_calibration_refs: list[str] = Field(default_factory=list)
    vehicle_or_shuttle_likely: bool = False
    vehicle_access_note: str | None = None
    readiness_eta_policy: Literal[
        "total_elapsed_time_including_normal_rest",
        "moving_time_only",
        "human_review_required",
    ] = "total_elapsed_time_including_normal_rest"


class PreTripPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    package_id: str
    project_id: str
    version: str
    status: Literal["candidate", "reviewed", "compiled"] = "candidate"
    route_summary: PreTripRouteSummary
    source_artifacts: list[PreTripSourceArtifact] = Field(default_factory=list)
    planning_references: list[PreTripPlanningReference] = Field(default_factory=list)
    dtm_coverage_summary: DtmCoverageSummary | None = None
    checkpoint_candidates: list[PreTripCheckpointCandidate] = Field(default_factory=list)
    segment_candidates: list[PreTripSegmentCandidate] = Field(default_factory=list)
    retreat_route_candidates: list[PreTripRetreatRouteCandidate] = Field(default_factory=list)
    route_guide_timing_candidates: list[PreTripRouteGuideTimingCandidate] = Field(default_factory=list)
    readiness_notes: list[str] = Field(default_factory=list)
