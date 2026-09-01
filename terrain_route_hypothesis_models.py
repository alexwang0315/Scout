"""Typed models for candidate-only terrain route hypotheses."""

from __future__ import annotations

import math
from enum import Enum
from typing import Any, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


TERRAIN_ROUTE_HYPOTHESIS_SCHEMA_VERSION = "scout_terrain_route_hypothesis.v0_2"
TERRAIN_ROUTE_HYPOTHESIS_ALGORITHM_VERSION = "terrain_route_hypothesis.v0_2"
TERRAIN_ROUTE_PATH_MODEL = "anisotropic_walk"
TERRAIN_ROUTE_PATH_SEMANTICS = "minimum_anisotropic_model_cost_trace"
TERRAIN_ROUTE_BAND_MODEL = "symmetric_macro_terrain_cost"
TERRAIN_ROUTE_BAND_SEMANTICS = (
    "finite_symmetric_macro_terrain_relative_cost_cell_percentile"
)
TERRAIN_ROUTE_PATH_BAND_RELATIONSHIP = "separate_model_not_path_confidence_band"
DEFAULT_CORRIDOR_PERCENTILES = (5.0, 10.0, 20.0)
PROHIBITED_PROMOTION_LABELS = frozenset(
    {
        "existing_trail",
        "confirmed_trail",
        "safe_route",
        "passable",
        "legally_accessible",
        "recommended_route",
    }
)


class TerrainHypothesisAuthority(str, Enum):
    CANDIDATE_ONLY = "candidate_only"


class TerrainEvidenceSourceType(str, Enum):
    TERRAIN_HYPOTHESIS = "terrain_hypothesis"
    OBSERVED_TRAIL = "observed_trail"
    KNOWN_GPX = "known_gpx"
    OFFICIAL_TRAIL = "official_trail"
    HISTORICAL_ROUTE = "historical_route"
    HUMAN_VERIFIED = "human_verified"
    UNKNOWN = "unknown"


class TerrainRouteRunStatus(str, Enum):
    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class TerrainRouteFailureCode(str, Enum):
    MISSING_DEM = "missing_dem"
    DEM_RESOLUTION_TOO_LOW = "dem_resolution_too_low"
    NODATA_PRESENT = "nodata_present"
    CRS_MISMATCH = "crs_mismatch"
    ENDPOINTS_COINCIDENT = "endpoints_coincident"
    ENDPOINT_OUTSIDE_DEM = "endpoint_outside_dem"
    COST_SURFACE_INCOMPLETE = "cost_surface_incomplete"
    GRASS_UNAVAILABLE = "grass_unavailable"
    RWALK_FAILED = "rwalk_failed"
    RPATH_FAILED = "rpath_failed"
    NO_CONNECTED_SOLUTION = "no_connected_solution"
    BACKEND_FAILED = "backend_failed"


class RouteEvidencePolarity(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"


class TerrainResolutionClass(str, Enum):
    MACRO_TERRAIN_ONLY = "macro_terrain_only"
    TERRAIN_CORRIDOR_CANDIDATE = "terrain_corridor_candidate"
    FINE_TERRAIN_CANDIDATE = "fine_terrain_candidate"
    MICROTERRAIN_CANDIDATE = "microterrain_candidate"


class TerrainAuthorityBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authority: TerrainHypothesisAuthority = TerrainHypothesisAuthority.CANDIDATE_ONLY
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    operational: Literal[False] = False
    phase1_runtime_mutation_allowed: Literal[False] = False
    writes_to_official_trail_db: Literal[False] = False
    writes_to_safety_truth: Literal[False] = False
    promotion_allowed: Literal[False] = False
    safe_or_walkable: Literal["not_determined"] = "not_determined"


class GeoPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float
    y: float
    crs: str = Field(min_length=1)
    label: str | None = None

    @field_validator("x", "y")
    @classmethod
    def require_finite_coordinate(cls, value: float) -> float:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("GeoPoint coordinates must be finite")
        return number

    @field_validator("crs")
    @classmethod
    def normalize_crs(cls, value: str) -> str:
        crs = value.strip().upper()
        if not crs:
            raise ValueError("GeoPoint CRS is required")
        return crs


class GeoJsonLineString(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["LineString"] = "LineString"
    coordinates: tuple[tuple[float, float], ...]
    crs: str

    @field_validator("coordinates", mode="before")
    @classmethod
    def normalize_coordinates(cls, value: Any) -> tuple[tuple[float, float], ...]:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            raise ValueError("LineString coordinates must be a sequence")
        normalized: list[tuple[float, float]] = []
        for item in value:
            if not isinstance(item, Sequence) or len(item) < 2:
                raise ValueError("LineString coordinate must contain x and y")
            x = float(item[0])
            y = float(item[1])
            if not math.isfinite(x) or not math.isfinite(y):
                raise ValueError("LineString coordinates must be finite")
            normalized.append((x, y))
        if len(normalized) < 2:
            raise ValueError("LineString requires at least two coordinates")
        return tuple(normalized)


class TerrainDemRaster(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(min_length=1)
    cells: tuple[tuple[float | None, ...], ...]
    resolution_m: float = Field(gt=0)
    crs: str = Field(min_length=1)
    x_min: float = 0.0
    y_max: float | None = None
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    source_ref: str | None = None
    vertical_datum: str | None = None

    @field_validator("cells", mode="before")
    @classmethod
    def normalize_cells(cls, value: Any) -> tuple[tuple[float | None, ...], ...]:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            raise ValueError("DEM cells must be a rectangular 2D sequence")
        rows: list[tuple[float | None, ...]] = []
        width: int | None = None
        for raw_row in value:
            if not isinstance(raw_row, Sequence) or isinstance(raw_row, (str, bytes)):
                raise ValueError("DEM rows must be sequences")
            row: list[float | None] = []
            for raw_value in raw_row:
                if raw_value is None:
                    row.append(None)
                    continue
                number = float(raw_value)
                row.append(number if math.isfinite(number) else None)
            if width is None:
                width = len(row)
            if width == 0 or len(row) != width:
                raise ValueError("DEM cells must be non-empty and rectangular")
            rows.append(tuple(row))
        if not rows:
            raise ValueError("DEM cells must contain at least one row")
        return tuple(rows)

    @field_validator("crs")
    @classmethod
    def normalize_crs(cls, value: str) -> str:
        crs = value.strip().upper()
        if not crs:
            raise ValueError("DEM CRS is required")
        return crs

    @property
    def shape(self) -> tuple[int, int]:
        return len(self.cells), len(self.cells[0])

    @property
    def resolved_y_max(self) -> float:
        if self.y_max is not None:
            return float(self.y_max)
        return float((self.shape[0] - 1) * self.resolution_m)

    @property
    def x_max(self) -> float:
        return self.x_min + (self.shape[1] - 1) * self.resolution_m

    @property
    def y_min(self) -> float:
        return self.resolved_y_max - (self.shape[0] - 1) * self.resolution_m

    @property
    def extent(self) -> dict[str, float]:
        return {
            "x_min": float(self.x_min),
            "y_min": float(self.y_min),
            "x_max": float(self.x_max),
            "y_max": float(self.resolved_y_max),
        }

    def row_col_for_point(self, point: GeoPoint) -> tuple[int, int] | None:
        col = int(round((point.x - self.x_min) / self.resolution_m))
        row = int(round((self.resolved_y_max - point.y) / self.resolution_m))
        rows, cols = self.shape
        if row < 0 or col < 0 or row >= rows or col >= cols:
            return None
        return row, col

    def xy_for_row_col(self, row: int, col: int) -> tuple[float, float]:
        return (
            float(self.x_min + col * self.resolution_m),
            float(self.resolved_y_max - row * self.resolution_m),
        )


class SlopeCostBand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1)
    max_degrees: float | None = Field(default=None, gt=0)
    cost: float = Field(gt=0)


def default_slope_cost_bands() -> tuple[SlopeCostBand, ...]:
    return (
        SlopeCostBand(label="terrain_cost_low", max_degrees=10.0, cost=1.0),
        SlopeCostBand(label="terrain_cost_moderate", max_degrees=20.0, cost=2.4),
        SlopeCostBand(label="terrain_cost_increasing", max_degrees=30.0, cost=5.5),
        SlopeCostBand(label="terrain_cost_high", max_degrees=40.0, cost=13.0),
        SlopeCostBand(label="terrain_cost_extreme", max_degrees=None, cost=30.0),
    )


class TerrainRoutingCostConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_version: str = "terrain_routing_cost.v0_1"
    algorithm_version: str = TERRAIN_ROUTE_HYPOTHESIS_ALGORITHM_VERSION
    base_cost: float = Field(default=1.0, gt=0)
    slope_weight: float = Field(default=1.0, ge=0)
    roughness_weight: float = 0.0
    curvature_weight: float = 0.0
    drainage_weight: float = 0.0
    ridge_weight: float = 0.0
    teii_weight: float = 0.0
    max_dem_resolution_m: float = Field(default=50.0, gt=0)
    high_cost_threshold: float = Field(default=8.0, gt=0)
    candidate_exclusion_slope_degrees: float | None = Field(default=None, gt=0)
    corridor_percentiles: tuple[float, ...] = DEFAULT_CORRIDOR_PERCENTILES
    max_corridor_sample_cells: int = Field(default=500, ge=1, le=10_000)
    slope_cost_bands: tuple[SlopeCostBand, ...] = Field(
        default_factory=default_slope_cost_bands
    )

    @field_validator(
        "roughness_weight",
        "curvature_weight",
        "drainage_weight",
        "ridge_weight",
        "teii_weight",
    )
    @classmethod
    def require_finite_weight(cls, value: float) -> float:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("terrain cost weights must be finite")
        return number

    @field_validator("corridor_percentiles")
    @classmethod
    def validate_corridor_percentiles(
        cls, value: tuple[float, ...]
    ) -> tuple[float, ...]:
        if not value:
            raise ValueError("at least one corridor percentile is required")
        normalized = tuple(float(item) for item in value)
        if any(
            not math.isfinite(item) or item <= 0 or item > 100
            for item in normalized
        ):
            raise ValueError("corridor percentiles must be in (0, 100]")
        return tuple(sorted(normalized))

    @model_validator(mode="after")
    def validate_slope_bands(self) -> "TerrainRoutingCostConfig":
        if not self.slope_cost_bands:
            raise ValueError("slope_cost_bands must not be empty")
        finite_breaks = [
            band.max_degrees
            for band in self.slope_cost_bands
            if band.max_degrees is not None
        ]
        if finite_breaks != sorted(finite_breaks):
            raise ValueError("slope_cost_bands must be sorted by max_degrees")
        if self.slope_cost_bands[-1].max_degrees is not None:
            raise ValueError("final slope_cost_band must cover extreme slopes")
        return self


class RouteEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    polarity: RouteEvidencePolarity
    source_type: TerrainEvidenceSourceType = TerrainEvidenceSourceType.TERRAIN_HYPOTHESIS
    description: str = Field(min_length=1)


class RouteUnknown(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    source_type: TerrainEvidenceSourceType = TerrainEvidenceSourceType.UNKNOWN
    description: str = Field(min_length=1)


class TerrainRouteFailure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: TerrainRouteFailureCode
    message: str
    detail: str | None = None
    retryable: bool = False


class CorridorCell(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row: int = Field(ge=0)
    col: int = Field(ge=0)
    x: float
    y: float
    relative_corridor_cost: float = Field(ge=0)


class TerrainRasterReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_ref: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    media_type: Literal["image/tiff", "image/png"]
    crs: str = Field(min_length=1)
    bbox_wgs84: dict[str, float] | None = None
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    operational: Literal[False] = False

    @field_validator("artifact_ref")
    @classmethod
    def validate_bounded_artifact_ref(cls, value: str) -> str:
        if value.startswith(("/", "~")) or ".." in value.split("/"):
            raise ValueError("terrain raster artifact reference must be relative")
        return value


class CandidateCorridorBand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    percentile: float
    max_relative_corridor_cost: float = Field(ge=0)
    cell_count: int = Field(ge=0)
    sampled_cells: tuple[CorridorCell, ...] = Field(default_factory=tuple)
    contains_best_path: bool
    threshold_semantics: Literal[
        "finite_symmetric_macro_terrain_relative_cost_cell_percentile"
    ] = "finite_symmetric_macro_terrain_relative_cost_cell_percentile"
    threshold_comparison_operator: Literal["<="] = "<="
    tie_handling: Literal["include_all_cells_equal_to_threshold"] = (
        "include_all_cells_equal_to_threshold"
    )
    best_path_union_applied: Literal[False] = False
    path_relationship: Literal["separate_model_not_path_confidence_band"] = (
        "separate_model_not_path_confidence_band"
    )
    raster_ref: TerrainRasterReference | None = None
    overlay_ref: TerrainRasterReference | None = None
    authority: TerrainHypothesisAuthority = TerrainHypothesisAuthority.CANDIDATE_ONLY
    source_type: TerrainEvidenceSourceType = TerrainEvidenceSourceType.TERRAIN_HYPOTHESIS
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @field_validator("name")
    @classmethod
    def reject_promotional_corridor_name(cls, value: str) -> str:
        reject_promotional_text(value)
        return value


class TerrainRouteCandidateCorridor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: Literal["terrain_route_candidate_corridor"] = (
        "terrain_route_candidate_corridor"
    )
    relative_cost_formula: str = "C_A(x,y)+C_B(x,y)-C_AB"
    cost_surface_kind: Literal["symmetric_terrain_friction"] = (
        "symmetric_terrain_friction"
    )
    band_model: Literal["symmetric_macro_terrain_cost"] = (
        "symmetric_macro_terrain_cost"
    )
    threshold_semantics: Literal[
        "finite_symmetric_macro_terrain_relative_cost_cell_percentile"
    ] = "finite_symmetric_macro_terrain_relative_cost_cell_percentile"
    path_relationship: Literal["separate_model_not_path_confidence_band"] = (
        "separate_model_not_path_confidence_band"
    )
    bands: tuple[CandidateCorridorBand, ...]
    raster_ref: TerrainRasterReference | None = None
    authority: TerrainHypothesisAuthority = TerrainHypothesisAuthority.CANDIDATE_ONLY
    source_type: TerrainEvidenceSourceType = TerrainEvidenceSourceType.TERRAIN_HYPOTHESIS
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


class TerrainHypothesisMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relative_score: float | None = None
    relative_cost: float
    distance_m: float
    elevation_gain_m: float
    elevation_loss_m: float
    max_slope_degrees: float
    median_slope_degrees: float
    high_cost_fraction: float
    ridge_fraction: float | None = None
    valley_fraction: float | None = None
    teii_stats: dict[str, float] = Field(default_factory=dict)


class TerrainHypothesisProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dem_dataset_id: str
    dem_sha256: str
    dem_resolution_m: float
    dem_crs: str
    dem_extent: dict[str, float]
    input_endpoints: dict[str, dict[str, Any]]
    optional_evidence_refs: list[str] = Field(default_factory=list)
    optional_evidence_hashes: dict[str, str] = Field(default_factory=dict)
    cost_model_version: str
    weights: dict[str, float]
    weights_hash: str
    grass_version: str
    qgis_version: str = "unavailable"
    backend_id: str = "unknown"
    modules_executed: list[str]
    commands_executed: list[dict[str, Any]] = Field(default_factory=list)
    timestamp: str
    algorithm_version: str
    processing_manifest: dict[str, Any]
    cache_key: str
    cache_keys: dict[str, str] = Field(default_factory=dict)
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


class TerrainRouteHypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    label: str = Field(default="R1 terrain route hypothesis", min_length=1)
    authority: TerrainHypothesisAuthority = TerrainHypothesisAuthority.CANDIDATE_ONLY
    source_type: TerrainEvidenceSourceType = TerrainEvidenceSourceType.TERRAIN_HYPOTHESIS
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    safe_or_walkable: Literal["not_determined"] = "not_determined"
    start: GeoPoint
    destination: GeoPoint
    best_path: GeoJsonLineString
    path_model: Literal["anisotropic_walk"] = "anisotropic_walk"
    path_semantics: Literal["minimum_anisotropic_model_cost_trace"] = (
        "minimum_anisotropic_model_cost_trace"
    )
    corridor: TerrainRouteCandidateCorridor | None = None
    score: float | None = None
    metrics: TerrainHypothesisMetrics
    reasons: list[RouteEvidence] = Field(default_factory=list)
    unknowns: list[RouteUnknown] = Field(default_factory=list)
    dem_resolution_m: float
    resolution_class: TerrainResolutionClass
    confidence_limits: list[str]
    cost_model_version: str
    provenance: TerrainHypothesisProvenance
    boundary: TerrainAuthorityBoundary = Field(default_factory=TerrainAuthorityBoundary)

    @model_validator(mode="after")
    def enforce_candidate_authority(self) -> "TerrainRouteHypothesis":
        if self.authority is not TerrainHypothesisAuthority.CANDIDATE_ONLY:
            raise ValueError("terrain route hypotheses must be candidate_only")
        if self.source_type is not TerrainEvidenceSourceType.TERRAIN_HYPOTHESIS:
            raise ValueError("terrain route hypothesis source_type cannot be promoted")
        reject_promotional_text(self.id)
        reject_promotional_text(self.label)
        return self


class TerrainRouteHypothesisRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scout_terrain_route_hypothesis.v0_2"] = (
        TERRAIN_ROUTE_HYPOTHESIS_SCHEMA_VERSION
    )
    artifact_kind: Literal["terrain_route_hypothesis_run"] = "terrain_route_hypothesis_run"
    status: TerrainRouteRunStatus
    created_at: str
    hypotheses: list[TerrainRouteHypothesis] = Field(default_factory=list)
    failure: TerrainRouteFailure | None = None
    warnings: list[str] = Field(default_factory=list)
    unknowns: list[RouteUnknown] = Field(default_factory=list)
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    safe_or_walkable: Literal["not_determined"] = "not_determined"
    boundary: TerrainAuthorityBoundary = Field(default_factory=TerrainAuthorityBoundary)


class TerrainRouteHypothesisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dem: TerrainDemRaster | None
    start: GeoPoint
    destination: GeoPoint
    cost_config: TerrainRoutingCostConfig = Field(
        default_factory=TerrainRoutingCostConfig
    )
    optional_evidence_refs: list[str] = Field(default_factory=list)
    optional_evidence_hashes: dict[str, str] = Field(default_factory=dict)
    requested_at: str | None = None


class TerrainRouteHypothesisCatalogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,79}$")
    label: str = Field(min_length=1, max_length=120)
    scope: Literal["full_route", "local"]
    focus_mode: Literal["route_union", "hypothesis"]
    start_label: str = Field(min_length=1, max_length=80)
    destination_label: str = Field(min_length=1, max_length=80)
    hypothesis_ref: str = Field(min_length=1)
    hypothesis_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    visualization_ref: str = Field(min_length=1)
    visualization_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    cache_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    authority: TerrainHypothesisAuthority = TerrainHypothesisAuthority.CANDIDATE_ONLY
    source_type: Literal["terrain_hypothesis"] = "terrain_hypothesis"
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    operational: Literal[False] = False
    safe_or_walkable: Literal["not_determined"] = "not_determined"

    @field_validator("hypothesis_ref", "visualization_ref")
    @classmethod
    def validate_workspace_ref(cls, value: str) -> str:
        normalized = value.strip()
        if (
            not normalized
            or normalized.startswith(("/", "~"))
            or ".." in normalized.split("/")
        ):
            raise ValueError("terrain route catalog refs must be workspace-relative")
        return normalized

    @field_validator("label", "start_label", "destination_label")
    @classmethod
    def reject_promotional_labels(cls, value: str) -> str:
        normalized = value.strip()
        reject_promotional_text(normalized)
        return normalized


class TerrainRouteHypothesisCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scout_terrain_route_hypothesis_catalog.v0_1"] = (
        "scout_terrain_route_hypothesis_catalog.v0_1"
    )
    artifact_kind: Literal["terrain_route_hypothesis_catalog"] = (
        "terrain_route_hypothesis_catalog"
    )
    project_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    default_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,79}$")
    entries: tuple[TerrainRouteHypothesisCatalogEntry, ...] = Field(
        min_length=1,
        max_length=16,
    )
    created_at: str | None = None
    authority: TerrainHypothesisAuthority = TerrainHypothesisAuthority.CANDIDATE_ONLY
    source_type: Literal["terrain_hypothesis"] = "terrain_hypothesis"
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    operational: Literal[False] = False
    safe_or_walkable: Literal["not_determined"] = "not_determined"

    @model_validator(mode="after")
    def validate_selection(self) -> "TerrainRouteHypothesisCatalog":
        entry_ids = [entry.id for entry in self.entries]
        if len(entry_ids) != len(set(entry_ids)):
            raise ValueError("terrain route catalog entry IDs must be unique")
        if self.default_id not in entry_ids:
            raise ValueError("terrain route catalog default_id is not an entry")
        return self


def reject_promotional_text(value: str) -> None:
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in PROHIBITED_PROMOTION_LABELS:
        raise ValueError(f"terrain hypothesis cannot be labeled {value!r}")
