"""Typed, candidate-only narrative guidance for terrain route hypotheses.

Scout AI may interpret historical route prose into this schema. Deterministic
GIS code resolves the resulting constraints against DEM-derived features, and
a human must review map anchors before any guided R4 calculation is allowed.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from enum import Enum
from typing import Any, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from terrain_route_hypothesis_models import (
    GeoPoint,
    TerrainAuthorityBoundary,
    TerrainEvidenceSourceType,
    TerrainHypothesisAuthority,
    reject_promotional_text,
)


TERRAIN_GUIDANCE_SCHEMA_VERSION = "scout_terrain_narrative_guidance.v0_1"
TERRAIN_GUIDANCE_PARSER_VERSION = "terrain_narrative_parser.v0_1"
TERRAIN_GUIDANCE_RESOLVER_VERSION = "terrain_guidance_resolver.v0_1"
TERRAIN_GUIDANCE_REVIEW_VERSION = "terrain_guidance_review.v0_2"
TERRAIN_GUIDANCE_EXECUTION_VERSION = "terrain_guidance_execution.v0_2"
TERRAIN_GUIDANCE_COST_MODEL_VERSION = "reviewed_local_cost_preferences.v0_1"


class TerrainGuidanceConstraintKind(str, Enum):
    FOLLOW_LANDFORM = "follow_landform"
    ELEVATION_BAND = "elevation_band"
    DIRECTIONAL_TRAVERSE = "directional_traverse"
    RELATIVE_TO_FEATURE = "relative_to_feature"
    EXPECTED_CROSSING = "expected_crossing"
    ORDERED_ANCHOR = "ordered_anchor"
    ASCEND_TO_LANDFORM = "ascend_to_landform"
    CONTEXT_OBSERVATION = "context_observation"


class TerrainGuidanceLandform(str, Enum):
    RIDGE = "ridge"
    BROAD_RIDGE = "broad_ridge"
    SADDLE = "saddle"
    DRAINAGE = "drainage"
    VALLEY = "valley"
    SLOPE = "slope"
    SLOPE_TRANSITION = "slope_transition"
    UNKNOWN = "unknown"


class TerrainGuidanceDirection(str, Enum):
    NORTH = "north"
    SOUTH = "south"
    EAST = "east"
    WEST = "west"
    NORTHEAST = "northeast"
    NORTHWEST = "northwest"
    SOUTHEAST = "southeast"
    SOUTHWEST = "southwest"


class TerrainGuidanceRelation(str, Enum):
    EAST_OF = "east_of"
    WEST_OF = "west_of"
    NORTH_OF = "north_of"
    SOUTH_OF = "south_of"
    ALONG = "along"
    CROSSES = "crosses"
    REACHES = "reaches"


class TerrainGuidanceRoutingEffect(str, Enum):
    PREFERENCE = "preference"
    PENALTY = "penalty"
    ORDERED_GATE = "ordered_gate"
    CONTEXT_ONLY = "context_only"


class TerrainGuidanceCostModifierKind(str, Enum):
    RIDGE_LOCAL_PREFERENCE = "ridge_local_preference"
    SADDLE_LOCAL_PREFERENCE = "saddle_local_preference"
    DRAINAGE_CROSSING_GATE = "drainage_crossing_gate"
    DIRECTIONAL_TRAVERSE_GATE = "directional_traverse_gate"
    RELATIVE_FEATURE_GATE = "relative_feature_gate"
    ELEVATION_GATE = "elevation_gate"
    GENERIC_REVIEWED_GATE = "generic_reviewed_gate"


class TerrainGuidanceMeasurementSemantics(str, Enum):
    DISTANCE_M = "distance_m"
    ELEVATION_M = "elevation_m"
    UNKNOWN = "unknown"


class TerrainGuidanceInterpretationStatus(str, Enum):
    COMPLETED = "completed"
    PARTIALLY_RESOLVED = "partially_resolved"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class TerrainGuidanceResolutionStatus(str, Enum):
    RESOLVED = "resolved"
    MULTIPLE_CANDIDATES = "multiple_candidates"
    CONFLICT = "conflict"
    UNRESOLVED = "unresolved"
    NOT_ROUTING_APPLICABLE = "not_routing_applicable"


class TerrainGuidanceReviewStatus(str, Enum):
    REVIEWED = "reviewed"
    PARTIALLY_REVIEWED = "partially_reviewed"


class TerrainGuidanceReviewDecisionKind(str, Enum):
    HUMAN_MAP_ANCHOR_CONFIRMED = "human_map_anchor_confirmed"
    HUMAN_SELECTED_CANDIDATE = "human_selected_candidate"
    HUMAN_DISABLED_CONSTRAINT = "human_disabled_constraint"
    LEFT_UNSELECTED = "left_unselected"


class TerrainGuidanceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NarrativeSourceSpan(TerrainGuidanceModel):
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def require_valid_range(self) -> "NarrativeSourceSpan":
        if self.end <= self.start:
            raise ValueError("source span end must follow start")
        return self


class TerrainGuidanceUnknown(TerrainGuidanceModel):
    code: str = Field(min_length=1)
    description: str = Field(min_length=1)
    related_constraint_ids: list[str] = Field(default_factory=list)
    source_type: TerrainEvidenceSourceType = TerrainEvidenceSourceType.UNKNOWN


class TerrainGuidanceConflict(TerrainGuidanceModel):
    code: str = Field(min_length=1)
    description: str = Field(min_length=1)
    constraint_ids: list[str] = Field(min_length=1)
    requires_human_resolution: Literal[True] = True


class TerrainGuidanceContextObservation(TerrainGuidanceModel):
    code: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    source_span: NarrativeSourceSpan
    source_type: TerrainEvidenceSourceType = TerrainEvidenceSourceType.HISTORICAL_ROUTE
    routing_applicable: Literal[False] = False
    routing_effect: Literal[TerrainGuidanceRoutingEffect.CONTEXT_ONLY] = (
        TerrainGuidanceRoutingEffect.CONTEXT_ONLY
    )
    boundary: TerrainAuthorityBoundary = Field(default_factory=TerrainAuthorityBoundary)

    @field_validator("summary")
    @classmethod
    def reject_promotional_summary(cls, value: str) -> str:
        reject_promotional_text(value)
        return value.strip()


class TerrainGuidanceCorridorOverlap(TerrainGuidanceModel):
    hypothesis_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,79}$")
    band_name: Literal[
        "top_5_percent_corridor",
        "top_10_percent_corridor",
        "top_20_percent_corridor",
    ]
    sample_count: int = Field(ge=1, le=100)
    inside_sample_count: int = Field(ge=0)
    outside_or_nodata_sample_count: int = Field(ge=0)
    overlap_fraction: float = Field(ge=0, le=1)
    semantics: Literal[
        "candidate_corridor_mask_overlap_for_review_ranking_only"
    ] = "candidate_corridor_mask_overlap_for_review_ranking_only"
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    operational: Literal[False] = False

    @model_validator(mode="after")
    def validate_overlap_counts(self) -> "TerrainGuidanceCorridorOverlap":
        if (
            self.inside_sample_count + self.outside_or_nodata_sample_count
            != self.sample_count
        ):
            raise ValueError("candidate corridor overlap sample counts do not add up")
        expected_fraction = self.inside_sample_count / self.sample_count
        if not math.isclose(self.overlap_fraction, expected_fraction, abs_tol=1e-9):
            raise ValueError("candidate corridor overlap fraction is inconsistent")
        return self


class TerrainGuidanceCorridorReference(TerrainGuidanceModel):
    hypothesis_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,79}$")
    hypothesis_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    cache_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    band_name: Literal[
        "top_5_percent_corridor",
        "top_10_percent_corridor",
        "top_20_percent_corridor",
    ]
    raster_ref: str = Field(min_length=1)
    raster_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    raster_crs: str = Field(min_length=1)
    sampling_backend: str = Field(min_length=1)
    sample_count: int = Field(ge=1)
    inside_sample_count: int = Field(ge=0)
    outside_or_nodata_sample_count: int = Field(ge=0)
    feature_count: int = Field(ge=1)
    features_with_overlap: int = Field(ge=0)
    inside_value: float = 1.0
    nodata_value: float = 255.0
    threshold_semantics: Literal[
        "finite_symmetric_macro_terrain_relative_cost_cell_percentile"
    ] = "finite_symmetric_macro_terrain_relative_cost_cell_percentile"
    ranking_semantics: Literal[
        "candidate_corridor_overlap_is_review_rank_evidence_not_route_confirmation"
    ] = "candidate_corridor_overlap_is_review_rank_evidence_not_route_confirmation"
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    operational: Literal[False] = False

    @field_validator("raster_ref")
    @classmethod
    def validate_bounded_raster_ref(cls, value: str) -> str:
        normalized = value.strip()
        if (
            not normalized
            or normalized.startswith(("/", "~"))
            or ".." in normalized.split("/")
        ):
            raise ValueError("candidate corridor raster ref must be workspace-relative")
        return normalized

    @model_validator(mode="after")
    def validate_sampling_counts(self) -> "TerrainGuidanceCorridorReference":
        if (
            self.inside_sample_count + self.outside_or_nodata_sample_count
            != self.sample_count
        ):
            raise ValueError("candidate corridor reference sample counts do not add up")
        if self.features_with_overlap > self.feature_count:
            raise ValueError("candidate corridor overlap feature count is invalid")
        return self


class TerrainNarrativeConstraint(TerrainGuidanceModel):
    constraint_id: str = Field(pattern=r"^G[1-9][0-9]*$")
    kind: TerrainGuidanceConstraintKind
    summary: str = Field(min_length=1, max_length=240)
    sequence_index: int = Field(ge=0)
    source_span: NarrativeSourceSpan
    source_type: TerrainEvidenceSourceType = TerrainEvidenceSourceType.HISTORICAL_ROUTE
    confidence: float = Field(ge=0, le=1)
    landform: TerrainGuidanceLandform | None = None
    direction: TerrainGuidanceDirection | None = None
    relation: TerrainGuidanceRelation | None = None
    reference_feature: TerrainGuidanceLandform | None = None
    approximate_value_m: float | None = Field(default=None, ge=0)
    measurement_semantics: TerrainGuidanceMeasurementSemantics | None = None
    routing_effect: TerrainGuidanceRoutingEffect
    routing_applicable: bool = True
    required_anchor: bool = False
    unknowns: list[str] = Field(default_factory=list)
    boundary: TerrainAuthorityBoundary = Field(default_factory=TerrainAuthorityBoundary)

    @field_validator("summary")
    @classmethod
    def reject_promotional_summary(cls, value: str) -> str:
        reject_promotional_text(value)
        return value.strip()

    @model_validator(mode="after")
    def validate_routing_semantics(self) -> "TerrainNarrativeConstraint":
        if not self.routing_applicable and self.routing_effect is not TerrainGuidanceRoutingEffect.CONTEXT_ONLY:
            raise ValueError("non-routing constraint must use context_only effect")
        if self.required_anchor and self.routing_effect is not TerrainGuidanceRoutingEffect.ORDERED_GATE:
            raise ValueError("required anchor must use ordered_gate effect")
        return self


class TerrainNarrativeGuidancePlan(TerrainGuidanceModel):
    artifact_kind: Literal["terrain_narrative_guidance_plan"] = (
        "terrain_narrative_guidance_plan"
    )
    schema_version: Literal["scout_terrain_narrative_guidance.v0_1"] = (
        TERRAIN_GUIDANCE_SCHEMA_VERSION
    )
    guidance_id: str = Field(min_length=1)
    status: TerrainGuidanceInterpretationStatus
    authority: TerrainHypothesisAuthority = TerrainHypothesisAuthority.CANDIDATE_ONLY
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    source_id: str = Field(min_length=1)
    source_type: TerrainEvidenceSourceType = TerrainEvidenceSourceType.HISTORICAL_ROUTE
    source_date: str | None = None
    narrative_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    parser_version: str = TERRAIN_GUIDANCE_PARSER_VERSION
    model_provider: str = "deterministic_local"
    model_name: str = "deterministic_phrase_parser"
    prompt_version: str = "terrain_guidance_prompt.v0_1"
    constraints: list[TerrainNarrativeConstraint] = Field(default_factory=list)
    context_observations: list[TerrainGuidanceContextObservation] = Field(
        default_factory=list
    )
    unknowns: list[TerrainGuidanceUnknown] = Field(default_factory=list)
    conflicts: list[TerrainGuidanceConflict] = Field(default_factory=list)
    review_required: Literal[True] = True
    warnings: list[str] = Field(default_factory=list)
    boundary: TerrainAuthorityBoundary = Field(default_factory=TerrainAuthorityBoundary)

    @model_validator(mode="after")
    def preserve_historical_candidate_boundary(self) -> "TerrainNarrativeGuidancePlan":
        if self.source_type not in {
            TerrainEvidenceSourceType.HISTORICAL_ROUTE,
            TerrainEvidenceSourceType.UNKNOWN,
        }:
            raise ValueError(
                "narrative guidance source_type cannot be promoted to observed, official, or verified truth"
            )
        expected_ids = [f"G{index}" for index in range(1, len(self.constraints) + 1)]
        if [item.constraint_id for item in self.constraints] != expected_ids:
            raise ValueError("constraint IDs must follow deterministic G1..Gn order")
        sequence = [item.sequence_index for item in self.constraints]
        if sequence != list(range(len(sequence))):
            raise ValueError("constraint sequence must be contiguous and deterministic")
        return self


class TerrainGuidanceFeatureCandidate(TerrainGuidanceModel):
    feature_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    landform: TerrainGuidanceLandform
    centroid: GeoPoint
    elevation_m: float | None = None
    direction: TerrainGuidanceDirection | None = None
    relations: tuple[str, ...] = ()
    supported_constraint_ids: tuple[str, ...] = ()
    reference_corridor_overlap: TerrainGuidanceCorridorOverlap | None = None
    geometry: dict[str, Any] | None = None
    selection_source: Literal["dem_derived", "human_map_annotation"] = (
        "dem_derived"
    )
    source_layer: str = Field(min_length=1)
    source_layer_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @field_validator("elevation_m")
    @classmethod
    def require_finite_elevation(cls, value: float | None) -> float | None:
        if value is None:
            return None
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("feature elevation must be finite")
        return number

    @field_validator("geometry")
    @classmethod
    def validate_geometry(
        cls, value: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if value is None:
            return None
        geometry_type = value.get("type")
        if geometry_type not in {
            "Point",
            "LineString",
            "MultiLineString",
            "Polygon",
            "MultiPolygon",
        }:
            raise ValueError("unsupported terrain guidance GeoJSON geometry")
        _validate_finite_coordinates(value.get("coordinates"))
        return value

    @model_validator(mode="after")
    def validate_selection_source(self) -> "TerrainGuidanceFeatureCandidate":
        if (
            self.selection_source == "human_map_annotation"
            and not self.supported_constraint_ids
        ):
            raise ValueError(
                "human map annotation must identify supported constraint IDs"
            )
        return self


class TerrainGuidanceSearchWindow(TerrainGuidanceModel):
    route_start: GeoPoint
    route_destination: GeoPoint
    margin_m: float = Field(ge=100, le=5000)
    west: float = Field(ge=-180, le=180)
    south: float = Field(ge=-90, le=90)
    east: float = Field(ge=-180, le=180)
    north: float = Field(ge=-90, le=90)

    @model_validator(mode="after")
    def validate_route_window(self) -> "TerrainGuidanceSearchWindow":
        if (
            self.route_start.crs != "EPSG:4326"
            or self.route_destination.crs != "EPSG:4326"
        ):
            raise ValueError("terrain guidance search window requires EPSG:4326")
        if (
            self.route_start.x == self.route_destination.x
            and self.route_start.y == self.route_destination.y
        ):
            raise ValueError("terrain guidance route endpoints must differ")
        if self.west >= self.east or self.south >= self.north:
            raise ValueError("terrain guidance search bounds are invalid")
        for point in (self.route_start, self.route_destination):
            if not (
                self.west <= point.x <= self.east
                and self.south <= point.y <= self.north
            ):
                raise ValueError("terrain guidance endpoint is outside search bounds")
        return self


class TerrainGuidanceFeatureIndex(TerrainGuidanceModel):
    artifact_kind: Literal["terrain_guidance_feature_index"] = (
        "terrain_guidance_feature_index"
    )
    dem_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    dem_resolution_m: float = Field(gt=0)
    crs: str = Field(min_length=1)
    algorithm_version: str = Field(min_length=1)
    elevation_sampling_status: Literal[
        "completed", "partial", "no_data", "unavailable"
    ] = "unavailable"
    elevation_sampling_backend: str | None = None
    elevation_sample_count: int = Field(default=0, ge=0)
    elevation_nodata_count: int = Field(default=0, ge=0)
    derived_saddle_count: int = Field(default=0, ge=0)
    reference_corridor: TerrainGuidanceCorridorReference | None = None
    search_window: TerrainGuidanceSearchWindow | None = None
    features: list[TerrainGuidanceFeatureCandidate]
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @field_validator("crs")
    @classmethod
    def normalize_crs(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("terrain guidance feature CRS is required")
        return normalized

    @model_validator(mode="after")
    def validate_feature_index(self) -> "TerrainGuidanceFeatureIndex":
        ids = [item.feature_id for item in self.features]
        if len(ids) != len(set(ids)):
            raise ValueError("terrain guidance feature IDs must be unique")
        expected_crs = self.crs.strip().upper()
        if any(item.centroid.crs != expected_crs for item in self.features):
            raise ValueError("terrain guidance feature CRS mismatch")
        dem_features = [
            item for item in self.features if item.selection_source == "dem_derived"
        ]
        overlaps = [
            item.reference_corridor_overlap
            for item in dem_features
            if item.reference_corridor_overlap is not None
        ]
        if self.reference_corridor is None and overlaps:
            raise ValueError("candidate corridor overlap is missing its bound reference")
        if self.reference_corridor is not None:
            if len(overlaps) != len(dem_features):
                raise ValueError(
                    "candidate corridor reference must cover every DEM-derived feature"
                )
            if any(
                item.hypothesis_id != self.reference_corridor.hypothesis_id
                or item.band_name != self.reference_corridor.band_name
                for item in overlaps
            ):
                raise ValueError("candidate corridor overlap reference mismatch")
            if self.reference_corridor.feature_count != len(dem_features):
                raise ValueError("candidate corridor feature count mismatch")
        if self.elevation_sampling_status == "unavailable":
            if (
                self.elevation_sampling_backend is not None
                or self.elevation_sample_count
                or self.elevation_nodata_count
                or self.derived_saddle_count
            ):
                raise ValueError(
                    "unavailable terrain elevation sampling cannot report derived evidence"
                )
            return self
        if not self.elevation_sampling_backend or self.elevation_sample_count < 1:
            raise ValueError("terrain elevation sampling requires a backend and samples")
        if self.elevation_nodata_count > self.elevation_sample_count:
            raise ValueError("terrain elevation NoData count exceeds sample count")
        if (
            self.elevation_sampling_status == "completed"
            and self.elevation_nodata_count != 0
        ):
            raise ValueError("completed terrain elevation sampling cannot contain NoData")
        if self.elevation_sampling_status == "partial" and not (
            0 < self.elevation_nodata_count < self.elevation_sample_count
        ):
            raise ValueError("partial terrain elevation sampling requires mixed data")
        if (
            self.elevation_sampling_status == "no_data"
            and self.elevation_nodata_count != self.elevation_sample_count
        ):
            raise ValueError(
                "no_data terrain elevation sampling requires every sample to be NoData"
            )
        if self.elevation_sampling_status == "no_data" and self.derived_saddle_count:
            raise ValueError("NoData terrain sampling cannot derive saddle evidence")
        return self


class ResolvedTerrainGuidanceConstraint(TerrainGuidanceModel):
    constraint_id: str = Field(pattern=r"^G[1-9][0-9]*$")
    sequence_index: int = Field(ge=0)
    required_anchor: bool
    status: TerrainGuidanceResolutionStatus
    candidate_feature_ids: list[str] = Field(default_factory=list)
    selected_feature_id: None = None
    explanation: str = Field(min_length=1)
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @model_validator(mode="after")
    def validate_status_candidates(self) -> "ResolvedTerrainGuidanceConstraint":
        count = len(self.candidate_feature_ids)
        if self.status is TerrainGuidanceResolutionStatus.RESOLVED and count != 1:
            raise ValueError("resolved constraint requires exactly one candidate")
        if self.status is TerrainGuidanceResolutionStatus.MULTIPLE_CANDIDATES and count < 2:
            raise ValueError("multiple_candidates requires at least two candidates")
        if self.status in {
            TerrainGuidanceResolutionStatus.UNRESOLVED,
            TerrainGuidanceResolutionStatus.NOT_ROUTING_APPLICABLE,
        } and count:
            raise ValueError("unresolved/context-only constraint cannot contain candidates")
        return self


class TerrainGuidanceResolution(TerrainGuidanceModel):
    artifact_kind: Literal["terrain_guidance_resolution"] = (
        "terrain_guidance_resolution"
    )
    schema_version: Literal["terrain_guidance_resolver.v0_1"] = (
        TERRAIN_GUIDANCE_RESOLVER_VERSION
    )
    resolution_id: str = Field(min_length=1)
    status: TerrainGuidanceInterpretationStatus
    plan_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    feature_index_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    dem_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    dem_resolution_m: float = Field(gt=0)
    candidate_rank_semantics: Literal[
        "typed_landform_elevation_then_narrative_sequence_proximity",
        "typed_landform_elevation_then_candidate_corridor_overlap_then_narrative_sequence_proximity",
    ] = "typed_landform_elevation_then_candidate_corridor_overlap_then_narrative_sequence_proximity"
    constraints: list[ResolvedTerrainGuidanceConstraint]
    unresolved_constraint_ids: list[str] = Field(default_factory=list)
    human_confirmation_required: Literal[True] = True
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    boundary: TerrainAuthorityBoundary = Field(default_factory=TerrainAuthorityBoundary)


class TerrainGuidanceAnchorSelection(TerrainGuidanceModel):
    constraint_id: str = Field(pattern=r"^G[1-9][0-9]*$")
    feature_id: str = Field(min_length=1)


class TerrainGuidanceReviewDecision(TerrainGuidanceModel):
    constraint_id: str = Field(pattern=r"^G[1-9][0-9]*$")
    sequence_index: int = Field(ge=0)
    resolver_status_before_review: TerrainGuidanceResolutionStatus
    resolver_candidate_feature_ids: list[str] = Field(default_factory=list)
    ai_selected_feature_id: None = None
    human_selected_feature_id: str | None = Field(default=None, min_length=1)
    selected_feature_source: Literal[
        "dem_derived",
        "human_map_annotation",
        "unknown",
    ] | None = None
    decision_kind: TerrainGuidanceReviewDecisionKind
    selection_authority: Literal["human_map_review"] = "human_map_review"
    ai_map_selection_performed: Literal[False] = False
    differs_from_ai_map_selection: bool
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    operational: Literal[False] = False

    @model_validator(mode="after")
    def validate_review_difference(self) -> "TerrainGuidanceReviewDecision":
        selected = self.human_selected_feature_id is not None
        if selected and self.decision_kind not in {
            TerrainGuidanceReviewDecisionKind.HUMAN_MAP_ANCHOR_CONFIRMED,
            TerrainGuidanceReviewDecisionKind.HUMAN_SELECTED_CANDIDATE,
        }:
            raise ValueError("selected review decision requires a selection decision kind")
        if selected and self.human_selected_feature_id not in (
            self.resolver_candidate_feature_ids
        ):
            raise ValueError("human review selection must remain in the resolver candidates")
        if not selected and self.selected_feature_source is not None:
            raise ValueError("unselected review decision cannot report a feature source")
        if (
            self.decision_kind
            is TerrainGuidanceReviewDecisionKind.HUMAN_MAP_ANCHOR_CONFIRMED
            and self.selected_feature_source != "human_map_annotation"
        ):
            raise ValueError("human map anchor decision requires a human map annotation")
        expected_difference = self.decision_kind is not (
            TerrainGuidanceReviewDecisionKind.LEFT_UNSELECTED
        )
        if self.differs_from_ai_map_selection is not expected_difference:
            raise ValueError("review difference flag does not match the human decision")
        return self


class TerrainNarrativeGuidanceReview(TerrainGuidanceModel):
    artifact_kind: Literal["terrain_narrative_guidance_review"] = (
        "terrain_narrative_guidance_review"
    )
    schema_version: Literal["terrain_guidance_review.v0_2"] = (
        TERRAIN_GUIDANCE_REVIEW_VERSION
    )
    review_id: str = Field(min_length=1)
    guidance_id: str = Field(min_length=1)
    guided_hypothesis_id: Literal["R4"] = "R4"
    plan_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    resolution_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    selected_anchors: list[TerrainGuidanceAnchorSelection]
    disabled_constraint_ids: list[str] = Field(default_factory=list)
    review_decisions: list[TerrainGuidanceReviewDecision] = Field(default_factory=list)
    reviewed_by: str = Field(min_length=1)
    reviewed_at: datetime
    review_status: TerrainGuidanceReviewStatus = TerrainGuidanceReviewStatus.REVIEWED
    reviewed: Literal[True] = True
    authority: TerrainHypothesisAuthority = TerrainHypothesisAuthority.CANDIDATE_ONLY
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    operational: Literal[False] = False
    boundary: TerrainAuthorityBoundary = Field(default_factory=TerrainAuthorityBoundary)

    @model_validator(mode="after")
    def bind_review_decisions(self) -> "TerrainNarrativeGuidanceReview":
        decision_ids = [item.constraint_id for item in self.review_decisions]
        if len(decision_ids) != len(set(decision_ids)):
            raise ValueError("terrain guidance review decisions must be unique")
        selected = {
            item.constraint_id: item.feature_id for item in self.selected_anchors
        }
        decision_selected = {
            item.constraint_id: item.human_selected_feature_id
            for item in self.review_decisions
            if item.human_selected_feature_id is not None
        }
        if selected != decision_selected:
            raise ValueError("review decisions must preserve every human anchor selection")
        disabled_from_decisions = sorted(
            item.constraint_id
            for item in self.review_decisions
            if item.decision_kind
            is TerrainGuidanceReviewDecisionKind.HUMAN_DISABLED_CONSTRAINT
        )
        if sorted(self.disabled_constraint_ids) != disabled_from_decisions:
            raise ValueError("review decisions must preserve disabled constraints")
        return self


class TerrainGuidanceExecutionAnchor(TerrainGuidanceModel):
    constraint_id: str = Field(pattern=r"^G[1-9][0-9]*$")
    sequence_index: int = Field(ge=0)
    kind: TerrainGuidanceConstraintKind
    landform: TerrainGuidanceLandform = TerrainGuidanceLandform.UNKNOWN
    routing_effect: TerrainGuidanceRoutingEffect
    required_anchor: bool
    feature_id: str = Field(min_length=1)
    point: GeoPoint
    selection_source: Literal["human_map_annotation"] = "human_map_annotation"
    source_layer: str = Field(min_length=1)
    source_layer_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    operational: Literal[False] = False

    @model_validator(mode="after")
    def require_reviewed_wgs84_point(self) -> "TerrainGuidanceExecutionAnchor":
        if self.point.crs != "EPSG:4326":
            raise ValueError("guided terrain route anchors must use EPSG:4326")
        return self


class TerrainGuidanceCostModifier(TerrainGuidanceModel):
    constraint_id: str = Field(pattern=r"^G[1-9][0-9]*$")
    sequence_index: int = Field(ge=0)
    modifier_kind: TerrainGuidanceCostModifierKind
    influence_radius_m: float = Field(ge=20, le=500)
    minimum_friction_multiplier: float = Field(ge=0.5, le=1)
    outside_friction_multiplier: Literal[1.0] = 1.0
    falloff: Literal["binary_local_preference"] = "binary_local_preference"
    semantics: Literal[
        "reviewed_constraint_local_cost_preference_not_route_truth"
    ] = "reviewed_constraint_local_cost_preference_not_route_truth"
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    operational: Literal[False] = False


class TerrainGuidanceExecutionPlan(TerrainGuidanceModel):
    artifact_kind: Literal["terrain_guidance_execution_plan"] = (
        "terrain_guidance_execution_plan"
    )
    schema_version: Literal["terrain_guidance_execution.v0_2"] = (
        TERRAIN_GUIDANCE_EXECUTION_VERSION
    )
    guidance_id: str = Field(min_length=1)
    guided_hypothesis_id: Literal["R4"] = "R4"
    review_id: str = Field(min_length=1)
    guidance_review_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    plan_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    resolution_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    feature_index_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    dem_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    dem_resolution_m: float = Field(gt=0)
    dem_crs: str = Field(min_length=1)
    reviewed_by: str = Field(min_length=1)
    reviewed_at: datetime
    review_decisions: list[TerrainGuidanceReviewDecision] = Field(
        min_length=1,
        max_length=64,
    )
    anchors: list[TerrainGuidanceExecutionAnchor] = Field(
        min_length=1,
        max_length=16,
    )
    cost_model_version: Literal["reviewed_local_cost_preferences.v0_1"] = (
        TERRAIN_GUIDANCE_COST_MODEL_VERSION
    )
    cost_modifiers: list[TerrainGuidanceCostModifier] = Field(
        min_length=1,
        max_length=16,
    )
    disabled_constraint_ids: list[str] = Field(default_factory=list)
    algorithm_version: Literal[
        "ordered_anchor_local_cost_anisotropic_walk.v0_2"
    ] = (
        "ordered_anchor_local_cost_anisotropic_walk.v0_2"
    )
    authority: TerrainHypothesisAuthority = TerrainHypothesisAuthority.CANDIDATE_ONLY
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    operational: Literal[False] = False
    safe_or_walkable: Literal["not_determined"] = "not_determined"
    review_required: Literal[True] = True
    human_reviewed: Literal[True] = True
    boundary: TerrainAuthorityBoundary = Field(default_factory=TerrainAuthorityBoundary)

    @field_validator("dem_crs")
    @classmethod
    def normalize_dem_crs(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def validate_ordered_candidate_anchors(self) -> "TerrainGuidanceExecutionPlan":
        sequence = [item.sequence_index for item in self.anchors]
        if sequence != sorted(sequence) or len(sequence) != len(set(sequence)):
            raise ValueError("guided terrain route anchors must follow unique source order")
        constraint_ids = [item.constraint_id for item in self.anchors]
        feature_ids = [item.feature_id for item in self.anchors]
        if len(constraint_ids) != len(set(constraint_ids)):
            raise ValueError("guided terrain route anchor constraints must be unique")
        if len(feature_ids) != len(set(feature_ids)):
            raise ValueError("guided terrain route anchor features must be unique")
        points = [(item.point.x, item.point.y) for item in self.anchors]
        if len(points) != len(set(points)):
            raise ValueError("guided terrain route anchor coordinates must be unique")
        modifier_ids = [item.constraint_id for item in self.cost_modifiers]
        modifier_sequence = [item.sequence_index for item in self.cost_modifiers]
        if modifier_ids != constraint_ids or modifier_sequence != sequence:
            raise ValueError(
                "guided terrain route cost modifiers must match reviewed anchors in source order"
            )
        selected_decisions = {
            item.constraint_id: item.human_selected_feature_id
            for item in self.review_decisions
            if item.human_selected_feature_id is not None
        }
        expected_selections = {
            item.constraint_id: item.feature_id for item in self.anchors
        }
        if selected_decisions != expected_selections:
            raise ValueError(
                "guided terrain route review decisions must match reviewed anchors"
            )
        disabled_decisions = sorted(
            item.constraint_id
            for item in self.review_decisions
            if item.decision_kind
            is TerrainGuidanceReviewDecisionKind.HUMAN_DISABLED_CONSTRAINT
        )
        if disabled_decisions != sorted(self.disabled_constraint_ids):
            raise ValueError(
                "guided terrain route review decisions must match disabled constraints"
            )
        return self


def interpret_terrain_route_narrative(
    narrative: str,
    *,
    source_id: str,
    source_date: str | None = None,
    source_type: TerrainEvidenceSourceType = TerrainEvidenceSourceType.HISTORICAL_ROUTE,
    model_provider: str = "deterministic_local",
    model_name: str = "deterministic_phrase_parser",
    prompt_version: str = "terrain_guidance_prompt.v0_1",
) -> TerrainNarrativeGuidancePlan:
    """Interpret a bounded set of route-language patterns without spatial guessing."""

    normalized = narrative.strip()
    if not normalized:
        raise ValueError("terrain route narrative is required")
    if not source_id.strip():
        raise ValueError("terrain route narrative source_id is required")
    narrative_sha = _sha256_text(normalized)
    raw_constraints = _extract_constraints(normalized)
    constraints = [
        TerrainNarrativeConstraint(
            constraint_id=f"G{index}",
            sequence_index=index - 1,
            **payload,
        )
        for index, payload in enumerate(raw_constraints, start=1)
    ]
    unknowns = _build_unknowns(constraints)
    observations = _extract_context_observations(normalized)
    status = (
        TerrainGuidanceInterpretationStatus.PARTIALLY_RESOLVED
        if unknowns
        else TerrainGuidanceInterpretationStatus.COMPLETED
    )
    plan = TerrainNarrativeGuidancePlan(
        guidance_id=f"terrain-guidance-{narrative_sha[:16]}",
        status=status,
        source_id=source_id.strip(),
        source_type=source_type,
        source_date=source_date,
        narrative_sha256=narrative_sha,
        model_provider=model_provider,
        model_name=model_name,
        prompt_version=prompt_version,
        constraints=constraints,
        context_observations=observations,
        unknowns=unknowns,
        warnings=[
            "Narrative constraints are candidate guidance only and require map review.",
            "Historical trail observations do not establish current trail existence, passability, safety, or legal access.",
        ],
    )
    validate_narrative_guidance_plan(plan, normalized)
    return plan


def validate_narrative_guidance_plan(
    plan: TerrainNarrativeGuidancePlan,
    narrative: str,
) -> None:
    """Verify hash and every quoted span against the exact source text."""

    normalized = narrative.strip()
    if _sha256_text(normalized) != plan.narrative_sha256:
        raise ValueError("narrative hash does not match guidance plan")
    for item in [*plan.constraints, *plan.context_observations]:
        span = item.source_span
        if span.end > len(normalized) or normalized[span.start : span.end] != span.text:
            item_id = (
                item.constraint_id
                if isinstance(item, TerrainNarrativeConstraint)
                else item.code
            )
            raise ValueError(
                f"source span does not match narrative for {item_id}"
            )


def resolve_terrain_route_guidance(
    plan: TerrainNarrativeGuidancePlan,
    feature_index: TerrainGuidanceFeatureIndex,
) -> TerrainGuidanceResolution:
    """Resolve constraints to DEM-derived candidates without selecting an anchor."""

    plan_sha = _model_sha256(plan)
    feature_sha = _model_sha256(feature_index)
    resolved: list[ResolvedTerrainGuidanceConstraint] = []
    unresolved_ids: list[str] = []
    constraint_count = len(plan.constraints)
    for constraint in plan.constraints:
        if not constraint.routing_applicable:
            result = ResolvedTerrainGuidanceConstraint(
                constraint_id=constraint.constraint_id,
                sequence_index=constraint.sequence_index,
                required_anchor=constraint.required_anchor,
                status=TerrainGuidanceResolutionStatus.NOT_ROUTING_APPLICABLE,
                explanation="Observation is retained as context and cannot affect routing.",
            )
        else:
            matched_features = sorted(
                (
                    feature
                    for feature in feature_index.features
                    if _feature_matches_constraint(feature, constraint)
                ),
                key=lambda feature: _feature_match_rank(
                    feature,
                    constraint,
                    feature_index=feature_index,
                    constraint_count=constraint_count,
                ),
            )
            matches = [feature.feature_id for feature in matched_features]
            if not matches:
                status = TerrainGuidanceResolutionStatus.UNRESOLVED
                explanation = "No DEM-derived feature satisfies the typed constraint."
                unresolved_ids.append(constraint.constraint_id)
            elif len(matches) == 1:
                status = TerrainGuidanceResolutionStatus.RESOLVED
                explanation = "One DEM-derived candidate zone was found; human confirmation remains required."
            else:
                status = TerrainGuidanceResolutionStatus.MULTIPLE_CANDIDATES
                explanation = "Multiple DEM-derived candidate zones were found; no automatic selection was made."
                unresolved_ids.append(constraint.constraint_id)
            result = ResolvedTerrainGuidanceConstraint(
                constraint_id=constraint.constraint_id,
                sequence_index=constraint.sequence_index,
                required_anchor=constraint.required_anchor,
                status=status,
                candidate_feature_ids=matches,
                explanation=explanation,
            )
        resolved.append(result)

    status = (
        TerrainGuidanceInterpretationStatus.PARTIALLY_RESOLVED
        if unresolved_ids
        else TerrainGuidanceInterpretationStatus.COMPLETED
    )
    resolution_id = _sha256_json(
        {
            "plan_sha256": plan_sha,
            "feature_index_sha256": feature_sha,
            "resolver_version": TERRAIN_GUIDANCE_RESOLVER_VERSION,
        }
    )[:20]
    return TerrainGuidanceResolution(
        resolution_id=f"terrain-guidance-resolution-{resolution_id}",
        status=status,
        plan_sha256=plan_sha,
        feature_index_sha256=feature_sha,
        dem_sha256=feature_index.dem_sha256,
        dem_resolution_m=feature_index.dem_resolution_m,
        constraints=resolved,
        unresolved_constraint_ids=unresolved_ids,
    )


def build_narrative_guidance_review(
    plan: TerrainNarrativeGuidancePlan,
    resolution: TerrainGuidanceResolution,
    *,
    selected_feature_ids: dict[str, str],
    reviewed_by: str,
    reviewed_at: datetime,
    disabled_constraint_ids: Sequence[str] = (),
    feature_selection_sources: Mapping[str, str] | None = None,
) -> TerrainNarrativeGuidanceReview:
    """Create an immutable human-review artifact after validating selections."""

    plan_sha = _model_sha256(plan)
    if resolution.plan_sha256 != plan_sha:
        raise ValueError("guidance resolution does not belong to this plan")
    by_id = {item.constraint_id: item for item in resolution.constraints}
    unknown_selected = set(selected_feature_ids) - set(by_id)
    unknown_disabled = set(disabled_constraint_ids) - set(by_id)
    if unknown_selected or unknown_disabled:
        raise ValueError("review references unknown constraint IDs")
    disabled = set(disabled_constraint_ids)
    selections: list[TerrainGuidanceAnchorSelection] = []
    for constraint_id, feature_id in sorted(
        selected_feature_ids.items(), key=lambda item: by_id[item[0]].sequence_index
    ):
        resolved = by_id[constraint_id]
        if feature_id not in resolved.candidate_feature_ids:
            raise ValueError(
                f"selected feature {feature_id!r} is not a candidate for {constraint_id}"
            )
        if constraint_id in disabled:
            raise ValueError(f"constraint {constraint_id} cannot be selected and disabled")
        selections.append(
            TerrainGuidanceAnchorSelection(
                constraint_id=constraint_id,
                feature_id=feature_id,
            )
        )
    selected_ids = set(selected_feature_ids)
    missing_required = [
        item.constraint_id
        for item in resolution.constraints
        if item.required_anchor
        and item.constraint_id not in selected_ids
        and item.constraint_id not in disabled
    ]
    if missing_required:
        raise ValueError(
            "required anchor constraints need a selected map feature or explicit disable: "
            + ", ".join(missing_required)
        )
    unresolved_not_handled = [
        constraint_id
        for constraint_id in resolution.unresolved_constraint_ids
        if constraint_id not in selected_ids and constraint_id not in disabled
    ]
    review_status = (
        TerrainGuidanceReviewStatus.PARTIALLY_REVIEWED
        if unresolved_not_handled
        else TerrainGuidanceReviewStatus.REVIEWED
    )
    selection_sources = feature_selection_sources or {}
    review_decisions: list[TerrainGuidanceReviewDecision] = []
    for resolved in sorted(
        resolution.constraints,
        key=lambda item: item.sequence_index,
    ):
        selected_feature_id = selected_feature_ids.get(resolved.constraint_id)
        selected_feature_source: str | None = None
        if selected_feature_id is not None:
            selected_feature_source = selection_sources.get(
                selected_feature_id,
                "unknown",
            )
            decision_kind = (
                TerrainGuidanceReviewDecisionKind.HUMAN_MAP_ANCHOR_CONFIRMED
                if selected_feature_source == "human_map_annotation"
                else TerrainGuidanceReviewDecisionKind.HUMAN_SELECTED_CANDIDATE
            )
        elif resolved.constraint_id in disabled:
            decision_kind = (
                TerrainGuidanceReviewDecisionKind.HUMAN_DISABLED_CONSTRAINT
            )
        else:
            decision_kind = TerrainGuidanceReviewDecisionKind.LEFT_UNSELECTED
        review_decisions.append(
            TerrainGuidanceReviewDecision(
                constraint_id=resolved.constraint_id,
                sequence_index=resolved.sequence_index,
                resolver_status_before_review=resolved.status,
                resolver_candidate_feature_ids=list(
                    resolved.candidate_feature_ids
                ),
                human_selected_feature_id=selected_feature_id,
                selected_feature_source=selected_feature_source,
                decision_kind=decision_kind,
                differs_from_ai_map_selection=(
                    decision_kind
                    is not TerrainGuidanceReviewDecisionKind.LEFT_UNSELECTED
                ),
            )
        )
    resolution_sha = _model_sha256(resolution)
    review_payload = {
        "guidance_id": plan.guidance_id,
        "resolution_sha256": resolution_sha,
        "selected_feature_ids": selected_feature_ids,
        "disabled_constraint_ids": sorted(disabled),
        "review_decisions": [
            item.model_dump(mode="json") for item in review_decisions
        ],
        "reviewed_by": reviewed_by,
        "reviewed_at": reviewed_at.isoformat(),
    }
    return TerrainNarrativeGuidanceReview(
        review_id=f"terrain-guidance-review-{_sha256_json(review_payload)[:20]}",
        guidance_id=plan.guidance_id,
        plan_sha256=plan_sha,
        resolution_sha256=resolution_sha,
        selected_anchors=selections,
        disabled_constraint_ids=sorted(disabled),
        review_decisions=review_decisions,
        reviewed_by=reviewed_by.strip(),
        reviewed_at=reviewed_at,
        review_status=review_status,
    )


def terrain_guidance_plan_sha256(plan: TerrainNarrativeGuidancePlan) -> str:
    return _model_sha256(plan)


def terrain_guidance_resolution_sha256(resolution: TerrainGuidanceResolution) -> str:
    return _model_sha256(resolution)


def terrain_guidance_review_sha256(review: TerrainNarrativeGuidanceReview) -> str:
    return _model_sha256(review)


def _extract_constraints(narrative: str) -> list[dict[str, Any]]:
    specs: list[tuple[str, dict[str, Any]]] = [
        (
            r"(?:於)?1148鞍",
            {
                "kind": TerrainGuidanceConstraintKind.ORDERED_ANCHOR,
                "summary": "Locate the historical record's 1148 saddle candidate.",
                "confidence": 0.78,
                "landform": TerrainGuidanceLandform.SADDLE,
                "approximate_value_m": 1148.0,
                "measurement_semantics": TerrainGuidanceMeasurementSemantics.UNKNOWN,
                "routing_effect": TerrainGuidanceRoutingEffect.ORDERED_GATE,
                "required_anchor": True,
                "unknowns": ["1148 may be a place label, elevation shorthand, or both"],
            },
        ),
        (
            r"沿著稜線走至其開始轉為上坡後",
            {
                "kind": TerrainGuidanceConstraintKind.FOLLOW_LANDFORM,
                "summary": "Prefer a ridge candidate until an upslope transition.",
                "confidence": 0.86,
                "landform": TerrainGuidanceLandform.RIDGE,
                "reference_feature": TerrainGuidanceLandform.SLOPE_TRANSITION,
                "routing_effect": TerrainGuidanceRoutingEffect.PREFERENCE,
            },
        ),
        (
            r"往西邊的坡切",
            {
                "kind": TerrainGuidanceConstraintKind.DIRECTIONAL_TRAVERSE,
                "summary": "Prefer a westward slope traverse candidate.",
                "confidence": 0.8,
                "landform": TerrainGuidanceLandform.SLOPE,
                "direction": TerrainGuidanceDirection.WEST,
                "routing_effect": TerrainGuidanceRoutingEffect.PREFERENCE,
            },
        ),
        (
            r"沿遇到的第一個溝東側的稜線續行",
            {
                "kind": TerrainGuidanceConstraintKind.RELATIVE_TO_FEATURE,
                "summary": "Prefer a ridge candidate east of the first drainage feature.",
                "confidence": 0.82,
                "landform": TerrainGuidanceLandform.RIDGE,
                "direction": TerrainGuidanceDirection.EAST,
                "relation": TerrainGuidanceRelation.EAST_OF,
                "reference_feature": TerrainGuidanceLandform.DRAINAGE,
                "routing_effect": TerrainGuidanceRoutingEffect.PREFERENCE,
            },
        ),
        (
            r"在寬闊的稜線上抓方向往北走",
            {
                "kind": TerrainGuidanceConstraintKind.FOLLOW_LANDFORM,
                "summary": "Prefer a northward broad-ridge candidate.",
                "confidence": 0.88,
                "landform": TerrainGuidanceLandform.BROAD_RIDGE,
                "direction": TerrainGuidanceDirection.NORTH,
                "routing_effect": TerrainGuidanceRoutingEffect.PREFERENCE,
            },
        ),
        (
            r"H820m?轉稜",
            {
                "kind": TerrainGuidanceConstraintKind.ORDERED_ANCHOR,
                "summary": "Locate a ridge-turn candidate near elevation 820 metres.",
                "confidence": 0.9,
                "landform": TerrainGuidanceLandform.RIDGE,
                "approximate_value_m": 820.0,
                "measurement_semantics": TerrainGuidanceMeasurementSemantics.ELEVATION_M,
                "routing_effect": TerrainGuidanceRoutingEffect.ORDERED_GATE,
                "required_anchor": True,
            },
        ),
        (
            r"下至溪底，過溪",
            {
                "kind": TerrainGuidanceConstraintKind.EXPECTED_CROSSING,
                "summary": "Locate a candidate drainage crossing after descent.",
                "confidence": 0.9,
                "landform": TerrainGuidanceLandform.DRAINAGE,
                "relation": TerrainGuidanceRelation.CROSSES,
                "routing_effect": TerrainGuidanceRoutingEffect.ORDERED_GATE,
                "required_anchor": True,
            },
        ),
        (
            r"沿著小溪溝上大概15m之後",
            {
                "kind": TerrainGuidanceConstraintKind.FOLLOW_LANDFORM,
                "summary": "Retain a short drainage-following segment as unresolved guidance.",
                "confidence": 0.68,
                "landform": TerrainGuidanceLandform.DRAINAGE,
                "relation": TerrainGuidanceRelation.ALONG,
                "approximate_value_m": 15.0,
                "measurement_semantics": TerrainGuidanceMeasurementSemantics.UNKNOWN,
                "routing_effect": TerrainGuidanceRoutingEffect.PREFERENCE,
                "unknowns": ["15m may describe horizontal distance or elevation gain"],
            },
        ),
        (
            r"往西腰繞",
            {
                "kind": TerrainGuidanceConstraintKind.DIRECTIONAL_TRAVERSE,
                "summary": "Prefer a westward contour-like traverse candidate.",
                "confidence": 0.86,
                "landform": TerrainGuidanceLandform.SLOPE,
                "direction": TerrainGuidanceDirection.WEST,
                "routing_effect": TerrainGuidanceRoutingEffect.PREFERENCE,
            },
        ),
        (
            r"(?:獵徑)?之字繞上稜",
            {
                "kind": TerrainGuidanceConstraintKind.ASCEND_TO_LANDFORM,
                "summary": "Prefer an ascent candidate that reaches a ridge.",
                "confidence": 0.8,
                "landform": TerrainGuidanceLandform.RIDGE,
                "relation": TerrainGuidanceRelation.REACHES,
                "routing_effect": TerrainGuidanceRoutingEffect.PREFERENCE,
            },
        ),
        (
            r"抵達異祿閣稜線",
            {
                "kind": TerrainGuidanceConstraintKind.ORDERED_ANCHOR,
                "summary": "Locate the terminal Iroko ridge candidate.",
                "confidence": 0.84,
                "landform": TerrainGuidanceLandform.BROAD_RIDGE,
                "routing_effect": TerrainGuidanceRoutingEffect.ORDERED_GATE,
                "required_anchor": True,
            },
        ),
    ]
    found: list[tuple[int, int, int, dict[str, Any]]] = []
    for priority, (pattern, values) in enumerate(specs):
        match = re.search(pattern, narrative)
        if match is None:
            continue
        span = NarrativeSourceSpan(
            start=match.start(),
            end=match.end(),
            text=match.group(0),
        )
        found.append((match.start(), match.end(), priority, {**values, "source_span": span}))
    found.sort(key=lambda item: (item[0], item[1], item[2]))
    return [item[3] for item in found]


def _extract_context_observations(
    narrative: str,
) -> list[TerrainGuidanceContextObservation]:
    specs = (
        ("marker_observation", r"(?:黃|粉色)布條", "Historical marker observation; current marker presence is unknown."),
        ("vegetation_observation", r"植被是及腰的草本植物", "Historical vegetation observation; current vegetation is unknown."),
        ("wet_surface_observation", r"(?:路徑)?濕滑", "Historical wet-surface observation; current moisture is unknown."),
        ("hunting_path_observation", r"獵徑", "Historical hunting-path observation; it is not DEM route truth."),
        ("boulder_observation", r"(?:大石頭|巨石)", "Historical boulder observation; DEM may not resolve it."),
    )
    observations: list[TerrainGuidanceContextObservation] = []
    for code, pattern, summary in specs:
        match = re.search(pattern, narrative)
        if match is None:
            continue
        observations.append(
            TerrainGuidanceContextObservation(
                code=code,
                summary=summary,
                source_span=NarrativeSourceSpan(
                    start=match.start(), end=match.end(), text=match.group(0)
                ),
            )
        )
    observations.sort(key=lambda item: item.source_span.start)
    return observations


def _build_unknowns(
    constraints: Sequence[TerrainNarrativeConstraint],
) -> list[TerrainGuidanceUnknown]:
    by_value = {
        item.approximate_value_m: item.constraint_id
        for item in constraints
        if item.approximate_value_m is not None
    }
    unknowns: list[TerrainGuidanceUnknown] = []
    if 1148.0 in by_value:
        unknowns.append(
            TerrainGuidanceUnknown(
                code="1148_semantics_unknown",
                description="1148 may be a saddle name, an elevation hint, or both; map confirmation is required.",
                related_constraint_ids=[by_value[1148.0]],
            )
        )
    if 15.0 in by_value:
        unknowns.append(
            TerrainGuidanceUnknown(
                code="15m_measurement_semantics_unknown",
                description="The narrative does not establish whether 15m is horizontal distance or elevation gain.",
                related_constraint_ids=[by_value[15.0]],
            )
        )
    unknowns.extend(
        [
            TerrainGuidanceUnknown(
                code="trail_observation_not_dem_authority",
                description="Markers and hunting-path observations do not establish a current trail in DEM evidence.",
            ),
            TerrainGuidanceUnknown(
                code="current_surface_unknown",
                description="Current vegetation, wetness, obstruction, and trail surface are unknown.",
            ),
            TerrainGuidanceUnknown(
                code="microterrain_unknown",
                description="Sub-cell gullies, ledges, boulders, bridges, ropes, and engineered trail structures may be unresolved.",
            ),
            TerrainGuidanceUnknown(
                code="legal_access_unknown",
                description="Narrative and DEM evidence do not establish legal access.",
            ),
        ]
    )
    return unknowns


def _feature_matches_constraint(
    feature: TerrainGuidanceFeatureCandidate,
    constraint: TerrainNarrativeConstraint,
) -> bool:
    if feature.supported_constraint_ids:
        return constraint.constraint_id in feature.supported_constraint_ids
    if constraint.landform is not None:
        compatible = {constraint.landform}
        if constraint.landform is TerrainGuidanceLandform.RIDGE:
            compatible.add(TerrainGuidanceLandform.BROAD_RIDGE)
        if constraint.landform is TerrainGuidanceLandform.BROAD_RIDGE:
            compatible.add(TerrainGuidanceLandform.RIDGE)
        if feature.landform not in compatible:
            return False
    if constraint.direction is not None and feature.direction not in {
        None,
        constraint.direction,
    }:
        return False
    if constraint.relation is not None and constraint.reference_feature is not None:
        relation_key = f"{constraint.relation.value}_{constraint.reference_feature.value}"
        if feature.relations and relation_key not in feature.relations:
            return False
    if (
        constraint.approximate_value_m is not None
        and constraint.kind is TerrainGuidanceConstraintKind.ORDERED_ANCHOR
    ):
        if feature.elevation_m is None:
            return False
        tolerance_m = 80.0
        if abs(feature.elevation_m - constraint.approximate_value_m) > tolerance_m:
            return False
    return True


def _feature_match_rank(
    feature: TerrainGuidanceFeatureCandidate,
    constraint: TerrainNarrativeConstraint,
    *,
    feature_index: TerrainGuidanceFeatureIndex,
    constraint_count: int,
) -> tuple[float, float, float, int, str]:
    """Order candidate evidence deterministically without selecting it."""

    elevation_delta = 0.0
    if constraint.approximate_value_m is not None:
        elevation_delta = (
            abs(feature.elevation_m - constraint.approximate_value_m)
            if feature.elevation_m is not None
            else math.inf
        )
    reference = feature_index.reference_corridor
    overlap = feature.reference_corridor_overlap
    corridor_penalty = 0.0
    if reference is not None:
        corridor_penalty = (
            1.0 - overlap.overlap_fraction
            if overlap is not None
            else math.inf
        )
    sequence_distance_m = 0.0
    search_window = feature_index.search_window
    if search_window is not None and constraint_count > 1:
        progress = constraint.sequence_index / float(constraint_count - 1)
        expected_point = (
            search_window.route_start.x
            + (search_window.route_destination.x - search_window.route_start.x)
            * progress,
            search_window.route_start.y
            + (search_window.route_destination.y - search_window.route_start.y)
            * progress,
        )
        candidate_points = _feature_geometry_points(feature)
        sequence_distance_m = min(
            _wgs84_approx_distance_m(expected_point, point)
            for point in candidate_points
        )
    landform_penalty = 0 if feature.landform is constraint.landform else 1
    return (
        elevation_delta,
        corridor_penalty,
        sequence_distance_m,
        landform_penalty,
        feature.feature_id,
    )


def _feature_geometry_points(
    feature: TerrainGuidanceFeatureCandidate,
) -> list[tuple[float, float]]:
    if feature.geometry is None:
        return [(feature.centroid.x, feature.centroid.y)]
    points: list[tuple[float, float]] = []

    def visit(value: Any) -> None:
        if (
            isinstance(value, (list, tuple))
            and len(value) >= 2
            and isinstance(value[0], (int, float))
            and isinstance(value[1], (int, float))
        ):
            points.append((float(value[0]), float(value[1])))
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                visit(item)

    visit(feature.geometry.get("coordinates"))
    return points or [(feature.centroid.x, feature.centroid.y)]


def _wgs84_approx_distance_m(
    start: tuple[float, float],
    destination: tuple[float, float],
) -> float:
    mean_latitude = math.radians((start[1] + destination[1]) / 2.0)
    x_m = (destination[0] - start[0]) * 111_320.0 * math.cos(mean_latitude)
    y_m = (destination[1] - start[1]) * 111_320.0
    return math.hypot(x_m, y_m)


def _model_sha256(model: BaseModel) -> str:
    return _sha256_json(model.model_dump(mode="json"))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return _sha256_text(payload)


def _validate_finite_coordinates(value: Any) -> None:
    if not isinstance(value, (list, tuple)):
        raise ValueError("GeoJSON coordinates must be nested arrays")
    if (
        len(value) >= 2
        and isinstance(value[0], (int, float))
        and isinstance(value[1], (int, float))
    ):
        if not math.isfinite(float(value[0])) or not math.isfinite(float(value[1])):
            raise ValueError("GeoJSON coordinates must be finite")
        return
    if not value:
        raise ValueError("GeoJSON coordinates cannot be empty")
    for item in value:
        _validate_finite_coordinates(item)


__all__ = [
    "NarrativeSourceSpan",
    "ResolvedTerrainGuidanceConstraint",
    "TERRAIN_GUIDANCE_PARSER_VERSION",
    "TERRAIN_GUIDANCE_COST_MODEL_VERSION",
    "TERRAIN_GUIDANCE_EXECUTION_VERSION",
    "TERRAIN_GUIDANCE_RESOLVER_VERSION",
    "TERRAIN_GUIDANCE_REVIEW_VERSION",
    "TERRAIN_GUIDANCE_SCHEMA_VERSION",
    "TerrainGuidanceAnchorSelection",
    "TerrainGuidanceConflict",
    "TerrainGuidanceCostModifier",
    "TerrainGuidanceCostModifierKind",
    "TerrainGuidanceConstraintKind",
    "TerrainGuidanceContextObservation",
    "TerrainGuidanceDirection",
    "TerrainGuidanceFeatureCandidate",
    "TerrainGuidanceFeatureIndex",
    "TerrainGuidanceExecutionAnchor",
    "TerrainGuidanceExecutionPlan",
    "TerrainGuidanceInterpretationStatus",
    "TerrainGuidanceLandform",
    "TerrainGuidanceMeasurementSemantics",
    "TerrainGuidanceRelation",
    "TerrainGuidanceResolution",
    "TerrainGuidanceResolutionStatus",
    "TerrainGuidanceReviewDecision",
    "TerrainGuidanceReviewDecisionKind",
    "TerrainGuidanceReviewStatus",
    "TerrainGuidanceRoutingEffect",
    "TerrainGuidanceSearchWindow",
    "TerrainGuidanceUnknown",
    "TerrainNarrativeConstraint",
    "TerrainNarrativeGuidancePlan",
    "TerrainNarrativeGuidanceReview",
    "build_narrative_guidance_review",
    "interpret_terrain_route_narrative",
    "resolve_terrain_route_guidance",
    "terrain_guidance_plan_sha256",
    "terrain_guidance_resolution_sha256",
    "terrain_guidance_review_sha256",
    "validate_narrative_guidance_plan",
]
