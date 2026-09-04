"""Typed, read-only DEM marker projection for narrative map review."""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from terrain_route_hypothesis_models import GeoPoint


Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
SelectionId = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,79}$")]
CorridorBandName = Literal[
    "top_5_percent_corridor",
    "top_10_percent_corridor",
    "top_20_percent_corridor",
]


class _MapReviewModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class TerrainGuidanceMapReviewRequest(_MapReviewModel):
    reference_hypothesis_id: SelectionId
    corridor_band_name: CorridorBandName
    expected_feature_index_sha256: Sha256 | None = None
    expected_resolution_sha256: Sha256 | None = None


class TerrainGuidanceMapReviewCentroid(_MapReviewModel):
    x: float = Field(ge=-180, le=180)
    y: float = Field(ge=-90, le=90)
    crs: Literal["EPSG:4326"] = "EPSG:4326"


class TerrainGuidanceMapReviewCandidate(_MapReviewModel):
    feature_id: str = Field(min_length=1)
    rank: int = Field(ge=1)
    centroid: TerrainGuidanceMapReviewCentroid
    minimum_path_distance_m: float = Field(ge=0)
    inside_corridor: Literal[True] = True


class TerrainGuidanceMapReviewConstraint(_MapReviewModel):
    constraint_id: str = Field(pattern=r"^G[1-9][0-9]*$")
    total_candidate_count: int = Field(ge=0)
    visible_candidate_count: int = Field(ge=0)
    excluded_candidate_count: int = Field(ge=0)
    status: Literal["candidates", "unknown", "not_routing_applicable"]
    candidates: tuple[TerrainGuidanceMapReviewCandidate, ...] = ()

    @model_validator(mode="after")
    def validate_counts_and_ranks(self) -> "TerrainGuidanceMapReviewConstraint":
        if (
            self.visible_candidate_count != len(self.candidates)
            or self.total_candidate_count
            != self.visible_candidate_count + self.excluded_candidate_count
            or (self.status == "candidates") != bool(self.candidates)
        ):
            raise ValueError("map review constraint counts or status are inconsistent")
        ranks = [item.rank for item in self.candidates]
        ids = [item.feature_id for item in self.candidates]
        if (
            ranks != sorted(set(ranks))
            or any(rank > self.total_candidate_count for rank in ranks)
            or len(ids) != len(set(ids))
        ):
            raise ValueError("map review candidates must preserve unique source ranks")
        return self


class TerrainGuidanceMapReviewCorridorReference(_MapReviewModel):
    hypothesis_id: SelectionId
    hypothesis_sha256: Sha256
    cache_key: Sha256
    band_name: CorridorBandName
    raster_ref: str = Field(min_length=1)
    raster_sha256: Sha256
    raster_crs: str = Field(min_length=1)
    bbox_wgs84: dict[str, float]
    parent_manifest_ref: str = Field(min_length=1)
    parent_manifest_sha256: Sha256
    dem_ref: str = Field(min_length=1)
    dem_sha256: Sha256
    inside_value: Literal[1.0] = 1.0
    outside_value: Literal[0.0] = 0.0
    nodata_value: Literal[255.0] = 255.0
    sampling_backend: str = Field(min_length=1)
    sampled_marker_count: int = Field(ge=0)
    sampling_semantics: Literal["marker_centroid_only"] = "marker_centroid_only"
    threshold_semantics: Literal[
        "finite_symmetric_macro_terrain_relative_cost_cell_percentile"
    ] = "finite_symmetric_macro_terrain_relative_cost_cell_percentile"


class TerrainGuidanceMapReviewPathReference(_MapReviewModel):
    selection_id: SelectionId
    hypothesis_id: str = Field(min_length=1)
    display_id: Literal["R1", "R2", "R3"]
    label: str = Field(min_length=1)
    alternative_index: int = Field(ge=1, le=3)
    hypothesis_run_sha256: Sha256
    cache_key: Sha256
    path_sha256: Sha256
    crs: Literal["EPSG:4326"] = "EPSG:4326"
    path_point_count: int = Field(ge=2)
    distance_semantics: Literal[
        "minimum_marker_centroid_to_full_path_segments_m"
    ] = "minimum_marker_centroid_to_full_path_segments_m"


class TerrainGuidanceMapReviewScope(_MapReviewModel):
    artifact_kind: Literal["terrain_guidance_map_review_scope"] = (
        "terrain_guidance_map_review_scope"
    )
    status: Literal["ready"] = "ready"
    project_id: str = Field(min_length=1)
    guidance_id: str = Field(min_length=1)
    scope_id: Sha256
    reference_hypothesis_id: SelectionId
    band_name: CorridorBandName
    dem_resolution_m: float = Field(gt=0)
    saddle_path_tolerance_m: float = Field(gt=0)
    source_feature_index_sha256: Sha256
    source_resolution_sha256: Sha256
    endpoint_alignment: Literal["same_ab", "different_review_context"]
    source_route_start: GeoPoint
    source_route_destination: GeoPoint
    scope_route_start: GeoPoint
    scope_route_destination: GeoPoint
    start_difference_m: float = Field(ge=0)
    destination_difference_m: float = Field(ge=0)
    corridor_reference: TerrainGuidanceMapReviewCorridorReference
    reference_paths: tuple[TerrainGuidanceMapReviewPathReference, ...] = Field(
        min_length=1, max_length=3
    )
    constraints: tuple[TerrainGuidanceMapReviewConstraint, ...]
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    operational: Literal[False] = False
    execution_eligible: Literal[False] = False
    routing_effect: Literal["none"] = "none"

    @model_validator(mode="after")
    def validate_scope_binding(self) -> "TerrainGuidanceMapReviewScope":
        corridor = self.corridor_reference
        endpoint_tolerance_m = max(30.0, self.dem_resolution_m * 2.0)
        same_ab = (
            self.start_difference_m <= endpoint_tolerance_m
            and self.destination_difference_m <= endpoint_tolerance_m
        )
        if (
            (self.endpoint_alignment == "same_ab") != same_ab
            or any(point.crs != "EPSG:4326" for point in (
                self.source_route_start, self.source_route_destination,
                self.scope_route_start, self.scope_route_destination,
            ))
        ):
            raise ValueError("map review endpoint context is inconsistent")
        if (
            self.saddle_path_tolerance_m != self.dem_resolution_m * math.sqrt(2)
            or corridor.hypothesis_id != self.reference_hypothesis_id
            or corridor.band_name != self.band_name
            or any(
                path.selection_id != self.reference_hypothesis_id
                or path.hypothesis_run_sha256 != corridor.hypothesis_sha256
                or path.cache_key != corridor.cache_key
                for path in self.reference_paths
            )
        ):
            raise ValueError("map review provenance or saddle tolerance mismatch")
        ids = [item.constraint_id for item in self.constraints]
        if len(ids) != len(set(ids)):
            raise ValueError("map review constraint IDs must be unique")
        return self
