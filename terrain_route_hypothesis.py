"""Candidate-only terrain route hypothesis engine.

This module owns the deterministic service layer for DEM-derived route
hypotheses. It does not assert trail existence, walkability, legal access, or
runtime safety truth.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any, Sequence

from terrain_route_hypothesis_backend import (
    CostGrid,
    FakeTerrainBackend,
    GrassCommandRunner,
    GrassTerrainBackend,
    GridCell,
    TerrainBackend,
    TerrainBackendFailure,
    TerrainBackendRequest,
    TerrainBackendResult,
)
from terrain_route_hypothesis_models import (
    DEFAULT_CORRIDOR_PERCENTILES,
    PROHIBITED_PROMOTION_LABELS,
    TERRAIN_ROUTE_BAND_MODEL,
    TERRAIN_ROUTE_BAND_SEMANTICS,
    TERRAIN_ROUTE_HYPOTHESIS_ALGORITHM_VERSION,
    TERRAIN_ROUTE_HYPOTHESIS_SCHEMA_VERSION,
    TERRAIN_ROUTE_PATH_BAND_RELATIONSHIP,
    TERRAIN_ROUTE_PATH_MODEL,
    TERRAIN_ROUTE_PATH_SEMANTICS,
    CandidateCorridorBand,
    CorridorCell,
    GeoJsonLineString,
    GeoPoint,
    RouteEvidence,
    RouteEvidencePolarity,
    RouteUnknown,
    SlopeCostBand,
    TerrainAuthorityBoundary,
    TerrainDemRaster,
    TerrainEvidenceSourceType,
    TerrainHypothesisAuthority,
    TerrainHypothesisMetrics,
    TerrainHypothesisProvenance,
    TerrainResolutionClass,
    TerrainRouteCandidateCorridor,
    TerrainRouteFailure,
    TerrainRouteFailureCode,
    TerrainRouteHypothesis,
    TerrainRouteHypothesisRequest,
    TerrainRouteHypothesisRun,
    TerrainRouteRunStatus,
    TerrainRoutingCostConfig,
    default_slope_cost_bands,
    reject_promotional_text,
)


class TerrainRouteHypothesisService:
    def __init__(
        self,
        backend: TerrainBackend,
        *,
        now_factory: Any | None = None,
    ) -> None:
        self.backend = backend
        self.now_factory = now_factory or (
            lambda: datetime.now(timezone.utc).replace(microsecond=0)
        )

    def generate(
        self,
        request: TerrainRouteHypothesisRequest | dict[str, Any],
    ) -> TerrainRouteHypothesisRun:
        created_at = _request_timestamp(request, self.now_factory)
        try:
            parsed = (
                request
                if isinstance(request, TerrainRouteHypothesisRequest)
                else TerrainRouteHypothesisRequest.model_validate(request)
            )
        except Exception as exc:
            return _unavailable_run(
                TerrainRouteFailureCode.BACKEND_FAILED,
                "Terrain route hypothesis request could not be parsed.",
                created_at=created_at,
                detail=str(exc),
            )

        failure = _preflight_failure(parsed)
        if failure is not None:
            return TerrainRouteHypothesisRun(
                status=TerrainRouteRunStatus.UNAVAILABLE,
                created_at=created_at,
                failure=failure,
                unknowns=default_route_unknowns(),
            )

        dem = parsed.dem
        assert dem is not None
        start_cell = dem.row_col_for_point(parsed.start)
        destination_cell = dem.row_col_for_point(parsed.destination)
        assert start_cell is not None
        assert destination_cell is not None

        try:
            slope = compute_slope_degrees(dem)
            friction = build_simple_friction_surface(slope, parsed.cost_config)
            if _has_nonfinite_cost(friction):
                return _unavailable_run(
                    TerrainRouteFailureCode.COST_SURFACE_INCOMPLETE,
                    "Terrain friction surface contains unavailable cells.",
                    created_at=created_at,
                )
            cache_key = build_terrain_route_hypothesis_cache_key(parsed)
            backend_result = self.backend.generate_best_path(
                TerrainBackendRequest(
                    dem=dem,
                    start_cell=start_cell,
                    destination_cell=destination_cell,
                    slope_degrees=slope,
                    friction=friction,
                    cost_config=parsed.cost_config,
                    cache_key=cache_key,
                )
            )
        except TerrainBackendFailure as exc:
            return _unavailable_run(
                exc.code,
                str(exc),
                created_at=created_at,
                detail=exc.detail,
                retryable=exc.retryable,
            )
        except Exception as exc:  # noqa: BLE001 - fail closed at service boundary.
            return _unavailable_run(
                TerrainRouteFailureCode.BACKEND_FAILED,
                "Terrain route hypothesis backend failed.",
                created_at=created_at,
                detail=str(exc),
            )

        if (
            not backend_result.path_cells
            or not math.isfinite(float(backend_result.accumulated_cost))
        ):
            return _unavailable_run(
                TerrainRouteFailureCode.NO_CONNECTED_SOLUTION,
                "No connected terrain route hypothesis could be produced.",
                created_at=created_at,
            )

        provenance = _build_provenance(
            parsed,
            dem=dem,
            backend_result=backend_result,
            timestamp=created_at,
            cache_key=cache_key,
        )
        metrics = _build_metrics(
            dem,
            backend_result.path_cells,
            slope,
            friction,
            backend_result.accumulated_cost,
            parsed.cost_config,
        )
        corridor = _build_candidate_corridor(
            dem,
            backend_result,
            parsed.cost_config,
        )
        resolution_class, confidence_limits = resolution_confidence_limits(
            dem.resolution_m
        )
        hypothesis = TerrainRouteHypothesis(
            id=f"terrain-route-hypothesis-r1-{cache_key[:12]}",
            start=parsed.start,
            destination=parsed.destination,
            best_path=GeoJsonLineString(
                coordinates=tuple(
                    dem.xy_for_row_col(row, col)
                    for row, col in backend_result.path_cells
                ),
                crs=dem.crs,
            ),
            corridor=corridor,
            score=metrics.relative_score,
            metrics=metrics,
            reasons=_route_evidence(metrics),
            unknowns=default_route_unknowns(dem_resolution_m=dem.resolution_m),
            dem_resolution_m=dem.resolution_m,
            resolution_class=resolution_class,
            confidence_limits=confidence_limits,
            cost_model_version=parsed.cost_config.model_version,
            provenance=provenance,
        )
        return TerrainRouteHypothesisRun(
            status=TerrainRouteRunStatus.COMPLETED,
            created_at=created_at,
            hypotheses=[hypothesis],
            warnings=[
                (
                    "Terrain route hypotheses are DEM/model candidates only; "
                    "they do not prove a trail exists, is passable, legally "
                    "accessible, recommended, or safe."
                )
            ],
            unknowns=hypothesis.unknowns,
        )


def compute_slope_degrees(dem: TerrainDemRaster) -> CostGrid:
    rows, cols = dem.shape
    result: list[tuple[float, ...]] = []
    for row in range(rows):
        values: list[float] = []
        for col in range(cols):
            center = _required_cell(dem, row, col)
            west = _required_cell(dem, row, max(0, col - 1))
            east = _required_cell(dem, row, min(cols - 1, col + 1))
            north = _required_cell(dem, max(0, row - 1), col)
            south = _required_cell(dem, min(rows - 1, row + 1), col)
            dx_cells = max(1, min(cols - 1, col + 1) - max(0, col - 1))
            dy_cells = max(1, min(rows - 1, row + 1) - max(0, row - 1))
            dzdx = (east - west) / (dx_cells * dem.resolution_m)
            dzdy = (south - north) / (dy_cells * dem.resolution_m)
            if not math.isfinite(center + dzdx + dzdy):
                raise TerrainBackendFailure(
                    TerrainRouteFailureCode.NODATA_PRESENT,
                    "DEM contains unavailable cells.",
                )
            values.append(math.degrees(math.atan(math.hypot(dzdx, dzdy))))
        result.append(tuple(values))
    return tuple(result)


def build_simple_friction_surface(
    slope_degrees: CostGrid,
    config: TerrainRoutingCostConfig,
) -> CostGrid:
    result: list[tuple[float, ...]] = []
    for row in slope_degrees:
        values: list[float] = []
        for slope in row:
            if (
                config.candidate_exclusion_slope_degrees is not None
                and slope >= config.candidate_exclusion_slope_degrees
            ):
                values.append(math.inf)
                continue
            slope_cost = slope_cost_for_degrees(slope, config)
            values.append(config.base_cost + config.slope_weight * slope_cost)
        result.append(tuple(values))
    return tuple(result)


def slope_cost_for_degrees(
    slope_degrees: float,
    config: TerrainRoutingCostConfig | None = None,
) -> float:
    config = config or TerrainRoutingCostConfig()
    slope = float(slope_degrees)
    if not math.isfinite(slope) or slope < 0:
        raise ValueError("slope_degrees must be a non-negative finite number")
    for band in config.slope_cost_bands:
        if band.max_degrees is None or slope <= band.max_degrees:
            return float(band.cost)
    return float(config.slope_cost_bands[-1].cost)


def resolution_confidence_limits(
    dem_resolution_m: float,
) -> tuple[TerrainResolutionClass, list[str]]:
    resolution = float(dem_resolution_m)
    if resolution >= 20.0:
        return (
            TerrainResolutionClass.MACRO_TERRAIN_ONLY,
            [
                "20m-or-coarser DEM supports macro terrain corridor reasoning only.",
                (
                    "It cannot resolve one-metre trail tread, small cliffs, "
                    "ladders, ropes, bridges, or short recent collapses."
                ),
                "Resolution class is not a safety confidence score.",
            ],
        )
    if resolution >= 5.0:
        return (
            TerrainResolutionClass.TERRAIN_CORRIDOR_CANDIDATE,
            [
                (
                    "DEM resolution can support terrain-corridor candidates, "
                    "not observed trail existence."
                ),
                (
                    "Vegetation, tread surface, engineered structures, water "
                    "level, and legal access remain unknown."
                ),
            ],
        )
    if resolution >= 1.0:
        return (
            TerrainResolutionClass.FINE_TERRAIN_CANDIDATE,
            [
                (
                    "Fine DEM supports smaller terrain-form candidates, but "
                    "still cannot verify current passage or legal access."
                ),
                (
                    "Recent landslide, vegetation, rope, ladder, bridge, and "
                    "surface conditions remain unknown."
                ),
            ],
        )
    return (
        TerrainResolutionClass.MICROTERRAIN_CANDIDATE,
        [
            (
                "Sub-metre DEM may expose microterrain candidates, but Scout "
                "still requires non-DEM evidence and human review before any "
                "promotion."
            ),
            "Current surface condition, legal access, and engineered aids remain unknown.",
        ],
    )


def default_route_unknowns(
    *,
    dem_resolution_m: float | None = None,
) -> list[RouteUnknown]:
    unknowns = [
        RouteUnknown(
            code="vegetation_unknown",
            description=(
                "DEM does not determine vegetation density or line-of-sight "
                "obstruction."
            ),
        ),
        RouteUnknown(
            code="trail_surface_unknown",
            description=(
                "DEM does not determine tread surface, erosion, mud, rock, or "
                "scrambling condition."
            ),
        ),
        RouteUnknown(
            code="legal_access_unknown",
            description="DEM does not determine permits, closures, ownership, or legal access.",
        ),
        RouteUnknown(
            code="bridge_presence_unknown",
            description="DEM does not determine whether a bridge or engineered crossing exists.",
        ),
        RouteUnknown(
            code="rope_presence_unknown",
            description="DEM does not determine whether ropes, ladders, or fixed aids exist.",
        ),
        RouteUnknown(
            code="recent_landslide_unknown",
            description="DEM may be older than recent collapse or storm damage.",
        ),
        RouteUnknown(
            code="water_level_unknown",
            description="DEM-derived drainage context does not determine current water level.",
        ),
    ]
    if dem_resolution_m is None or dem_resolution_m >= 20.0:
        unknowns.append(
            RouteUnknown(
                code="microterrain_unknown",
                description=(
                    "DEM resolution cannot resolve metre-scale mountain-trail "
                    "or cliff details."
                ),
            )
        )
    return unknowns


def build_terrain_route_hypothesis_cache_key(
    request: TerrainRouteHypothesisRequest,
) -> str:
    dem = request.dem
    dem_hash = "missing-dem" if dem is None else _dem_sha256(dem)
    payload = {
        "algorithm_version": request.cost_config.algorithm_version,
        "cost_model_version": request.cost_config.model_version,
        "dem_hash": dem_hash,
        "dem_extent": dem.extent if dem is not None else None,
        "dem_resolution_m": dem.resolution_m if dem is not None else None,
        "start": request.start.model_dump(mode="json"),
        "destination": request.destination.model_dump(mode="json"),
        "weights_hash": _weights_hash(request.cost_config),
        "optional_evidence_hashes": dict(
            sorted(request.optional_evidence_hashes.items())
        ),
    }
    return _stable_hash(payload)


def _preflight_failure(
    request: TerrainRouteHypothesisRequest,
) -> TerrainRouteFailure | None:
    dem = request.dem
    if dem is None:
        return TerrainRouteFailure(
            code=TerrainRouteFailureCode.MISSING_DEM,
            message="DEM is required for terrain route hypotheses.",
            retryable=True,
        )
    if dem.resolution_m > request.cost_config.max_dem_resolution_m:
        return TerrainRouteFailure(
            code=TerrainRouteFailureCode.DEM_RESOLUTION_TOO_LOW,
            message="DEM resolution is below the configured terrain-hypothesis floor.",
            detail=(
                f"DEM resolution {dem.resolution_m}m exceeds "
                f"max_dem_resolution_m={request.cost_config.max_dem_resolution_m}."
            ),
            retryable=True,
        )
    if dem.crs != request.start.crs or dem.crs != request.destination.crs:
        return TerrainRouteFailure(
            code=TerrainRouteFailureCode.CRS_MISMATCH,
            message="DEM and route endpoints must share one explicit CRS.",
            detail=(
                f"DEM={dem.crs}, start={request.start.crs}, "
                f"destination={request.destination.crs}"
            ),
        )
    if _dem_has_nodata(dem):
        return TerrainRouteFailure(
            code=TerrainRouteFailureCode.NODATA_PRESENT,
            message=(
                "DEM contains NoData/non-finite cells; no terrain hypothesis "
                "was generated."
            ),
            retryable=True,
        )
    if math.isclose(request.start.x, request.destination.x) and math.isclose(
        request.start.y,
        request.destination.y,
    ):
        return TerrainRouteFailure(
            code=TerrainRouteFailureCode.ENDPOINTS_COINCIDENT,
            message="Terrain route endpoints must identify two different locations.",
            retryable=True,
        )
    if dem.row_col_for_point(request.start) is None:
        return TerrainRouteFailure(
            code=TerrainRouteFailureCode.ENDPOINT_OUTSIDE_DEM,
            message="Start point is outside the DEM extent.",
        )
    if dem.row_col_for_point(request.destination) is None:
        return TerrainRouteFailure(
            code=TerrainRouteFailureCode.ENDPOINT_OUTSIDE_DEM,
            message="Destination point is outside the DEM extent.",
        )
    return None


def _build_candidate_corridor(
    dem: TerrainDemRaster,
    backend_result: TerrainBackendResult,
    config: TerrainRoutingCostConfig,
) -> TerrainRouteCandidateCorridor | None:
    if (
        backend_result.cost_from_start is None
        or backend_result.cost_from_destination is None
    ):
        return None
    c_ab = float(backend_result.accumulated_cost)
    if not math.isfinite(c_ab):
        return None
    path_cells = set(backend_result.path_cells)
    relative: list[tuple[float, int, int]] = []
    rows, cols = dem.shape
    for row in range(rows):
        for col in range(cols):
            start_cost = backend_result.cost_from_start[row][col]
            dest_cost = backend_result.cost_from_destination[row][col]
            if not math.isfinite(start_cost) or not math.isfinite(dest_cost):
                continue
            value = max(0.0, float(start_cost) + float(dest_cost) - c_ab)
            relative.append((value, row, col))
    if not relative:
        return None

    relative_sorted = sorted(relative)
    bands: list[CandidateCorridorBand] = []
    for percentile in config.corridor_percentiles:
        threshold_index = max(
            0,
            min(
                len(relative_sorted) - 1,
                math.ceil(len(relative_sorted) * percentile / 100.0) - 1,
            ),
        )
        threshold = relative_sorted[threshold_index][0]
        selected = [
            (value, row, col)
            for value, row, col in relative_sorted
            if value <= threshold
        ]
        selected_cells = {(row, col) for _, row, col in selected}
        sampled = tuple(
            CorridorCell(
                row=row,
                col=col,
                x=dem.xy_for_row_col(row, col)[0],
                y=dem.xy_for_row_col(row, col)[1],
                relative_corridor_cost=round(value, 6),
            )
            for value, row, col in selected[: config.max_corridor_sample_cells]
        )
        bands.append(
            CandidateCorridorBand(
                name=f"top_{_percentile_name(percentile)}_percent_corridor",
                percentile=percentile,
                max_relative_corridor_cost=round(float(threshold), 6),
                cell_count=len(selected),
                sampled_cells=sampled,
                contains_best_path=path_cells.issubset(selected_cells),
            )
        )
    return TerrainRouteCandidateCorridor(bands=tuple(bands))


def _build_metrics(
    dem: TerrainDemRaster,
    path_cells: tuple[GridCell, ...],
    slope: CostGrid,
    friction: CostGrid,
    accumulated_cost: float,
    config: TerrainRoutingCostConfig,
) -> TerrainHypothesisMetrics:
    elevations = [_required_cell(dem, row, col) for row, col in path_cells]
    slopes = [float(slope[row][col]) for row, col in path_cells]
    frictions = [float(friction[row][col]) for row, col in path_cells]
    distance = 0.0
    gain = 0.0
    loss = 0.0
    for index in range(1, len(path_cells)):
        row_a, col_a = path_cells[index - 1]
        row_b, col_b = path_cells[index]
        distance += dem.resolution_m * math.hypot(row_b - row_a, col_b - col_a)
        delta = elevations[index] - elevations[index - 1]
        if delta > 0:
            gain += delta
        else:
            loss += abs(delta)
    high_cost_count = sum(value >= config.high_cost_threshold for value in frictions)
    relative_score = 1.0 / (1.0 + accumulated_cost / max(distance, dem.resolution_m))
    return TerrainHypothesisMetrics(
        relative_score=round(relative_score, 6),
        relative_cost=round(float(accumulated_cost), 6),
        distance_m=round(distance, 3),
        elevation_gain_m=round(gain, 3),
        elevation_loss_m=round(loss, 3),
        max_slope_degrees=round(max(slopes, default=0.0), 6),
        median_slope_degrees=round(_median(slopes), 6),
        high_cost_fraction=round(high_cost_count / max(1, len(frictions)), 6),
    )


def _route_evidence(metrics: TerrainHypothesisMetrics) -> list[RouteEvidence]:
    evidence: list[RouteEvidence] = []
    if metrics.median_slope_degrees <= 20.0:
        evidence.append(
            RouteEvidence(
                code="moderate_slope",
                polarity=RouteEvidencePolarity.POSITIVE,
                description=(
                    "Median slope along the minimum anisotropic model-cost trace is in the "
                    "configured moderate terrain-cost range."
                ),
            )
        )
    else:
        evidence.append(
            RouteEvidence(
                code="steep_slope",
                polarity=RouteEvidencePolarity.NEGATIVE,
                description=(
                    "Median slope along the minimum anisotropic model-cost trace is high under "
                    "the terrain-cost model."
                ),
            )
        )
    if metrics.high_cost_fraction > 0:
        evidence.append(
            RouteEvidence(
                code="short_high_slope_section",
                polarity=RouteEvidencePolarity.NEGATIVE,
                description=(
                    "At least one minimum model-cost trace cell has high modeled "
                    "terrain cost."
                ),
            )
        )
    else:
        evidence.append(
            RouteEvidence(
                code="low_high_cost_fraction",
                polarity=RouteEvidencePolarity.POSITIVE,
                description=(
                    "No minimum model-cost trace cell exceeded the configured high-cost "
                    "threshold."
                ),
            )
        )
    return evidence


def _build_provenance(
    request: TerrainRouteHypothesisRequest,
    *,
    dem: TerrainDemRaster,
    backend_result: TerrainBackendResult,
    timestamp: str,
    cache_key: str,
) -> TerrainHypothesisProvenance:
    modules = [
        "grass:r.slope.aspect",
        "grass:r.mapcalc",
        *backend_result.modules_executed,
    ]
    weights = _cost_weights(request.cost_config)
    return TerrainHypothesisProvenance(
        dem_dataset_id=dem.dataset_id,
        dem_sha256=_dem_sha256(dem),
        dem_resolution_m=dem.resolution_m,
        dem_crs=dem.crs,
        dem_extent=dem.extent,
        input_endpoints={
            "start": request.start.model_dump(mode="json"),
            "destination": request.destination.model_dump(mode="json"),
        },
        optional_evidence_refs=list(request.optional_evidence_refs),
        optional_evidence_hashes=dict(sorted(request.optional_evidence_hashes.items())),
        cost_model_version=request.cost_config.model_version,
        weights=weights,
        weights_hash=_weights_hash(request.cost_config),
        grass_version=backend_result.grass_version,
        modules_executed=modules,
        timestamp=timestamp,
        algorithm_version=request.cost_config.algorithm_version,
        processing_manifest={
            "pipeline": [
                "dem",
                "slope",
                "simple_friction",
                "accumulated_cost_from_start",
                "accumulated_cost_from_destination",
                "rwalk_minimum_model_cost_trace",
                "rpath_minimum_model_cost_trace",
                "candidate_corridor",
            ],
            "path_model": {
                "id": TERRAIN_ROUTE_PATH_MODEL,
                "semantics": TERRAIN_ROUTE_PATH_SEMANTICS,
            },
            "band_model": {
                "id": TERRAIN_ROUTE_BAND_MODEL,
                "semantics": TERRAIN_ROUTE_BAND_SEMANTICS,
            },
            "path_band_relationship": TERRAIN_ROUTE_PATH_BAND_RELATIONSHIP,
            "best_path_union_applied": False,
            "backend": backend_result.backend_id,
            "backend_manifest": backend_result.processing_manifest,
            "contour_policy": "DEM primary; contour may be visualization or QA only.",
        },
        cache_key=cache_key,
    )


def _request_timestamp(request: Any, now_factory: Any) -> str:
    if isinstance(request, TerrainRouteHypothesisRequest) and request.requested_at:
        return request.requested_at
    if isinstance(request, dict) and request.get("requested_at"):
        return str(request["requested_at"])
    value = now_factory()
    if isinstance(value, str):
        return value
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _unavailable_run(
    code: TerrainRouteFailureCode,
    message: str,
    *,
    created_at: str,
    detail: str | None = None,
    retryable: bool = False,
) -> TerrainRouteHypothesisRun:
    return TerrainRouteHypothesisRun(
        status=TerrainRouteRunStatus.UNAVAILABLE,
        created_at=created_at,
        failure=TerrainRouteFailure(
            code=code,
            message=message,
            detail=detail,
            retryable=retryable,
        ),
        unknowns=default_route_unknowns(),
    )


def _required_cell(dem: TerrainDemRaster, row: int, col: int) -> float:
    value = dem.cells[row][col]
    if value is None or not math.isfinite(float(value)):
        raise TerrainBackendFailure(
            TerrainRouteFailureCode.NODATA_PRESENT,
            "DEM contains unavailable cells.",
        )
    return float(value)


def _dem_has_nodata(dem: TerrainDemRaster) -> bool:
    return any(value is None for row in dem.cells for value in row)


def _has_nonfinite_cost(grid: CostGrid) -> bool:
    return any(not math.isfinite(value) for row in grid for value in row)


def _dem_sha256(dem: TerrainDemRaster) -> str:
    return dem.sha256 or _stable_hash(
        {
            "dataset_id": dem.dataset_id,
            "cells": dem.cells,
            "resolution_m": dem.resolution_m,
            "crs": dem.crs,
            "x_min": dem.x_min,
            "y_max": dem.resolved_y_max,
            "source_ref": dem.source_ref,
            "vertical_datum": dem.vertical_datum,
        }
    )


def _weights_hash(config: TerrainRoutingCostConfig) -> str:
    return _stable_hash(
        {
            "weights": _cost_weights(config),
            "slope_cost_bands": [
                band.model_dump(mode="json") for band in config.slope_cost_bands
            ],
            "alternative_profiles": [
                profile.model_dump(mode="json")
                for profile in config.alternative_profiles
            ],
            "candidate_exclusion_slope_degrees": (
                config.candidate_exclusion_slope_degrees
            ),
        }
    )


def _cost_weights(config: TerrainRoutingCostConfig) -> dict[str, float]:
    return {
        "slope_weight": float(config.slope_weight),
        "roughness_weight": float(config.roughness_weight),
        "curvature_weight": float(config.curvature_weight),
        "drainage_weight": float(config.drainage_weight),
        "ridge_weight": float(config.ridge_weight),
        "teii_weight": float(config.teii_weight),
    }


def _stable_hash(payload: Any) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _percentile_name(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return str(value).replace(".", "_")
