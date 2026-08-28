from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from terrain_route_hypothesis import (
    FakeTerrainBackend,
    GeoPoint,
    GrassTerrainBackend,
    PROHIBITED_PROMOTION_LABELS,
    TerrainDemRaster,
    TerrainEvidenceSourceType,
    TerrainHypothesisAuthority,
    TerrainRouteFailureCode,
    TerrainRouteHypothesis,
    TerrainRouteHypothesisRequest,
    TerrainRouteHypothesisService,
    TerrainRouteRunStatus,
    TerrainRoutingCostConfig,
    TerrainResolutionClass,
    slope_cost_for_degrees,
)


FIXED_TIME = "2026-08-28T00:00:00Z"
CRS = "EPSG:3826"


def _service(
    backend: FakeTerrainBackend | GrassTerrainBackend | None = None,
) -> TerrainRouteHypothesisService:
    return TerrainRouteHypothesisService(
        backend or FakeTerrainBackend(),
        now_factory=lambda: datetime(2026, 8, 28, tzinfo=timezone.utc),
    )


def _dem(cells: list[list[float | None]], resolution_m: float = 20.0) -> TerrainDemRaster:
    return TerrainDemRaster(
        dataset_id="synthetic-dem",
        cells=cells,
        resolution_m=resolution_m,
        crs=CRS,
    )


def _point(dem: TerrainDemRaster, row: int, col: int) -> GeoPoint:
    x, y = dem.xy_for_row_col(row, col)
    return GeoPoint(x=x, y=y, crs=dem.crs)


def _request(dem: TerrainDemRaster | None) -> TerrainRouteHypothesisRequest:
    if dem is None:
        return TerrainRouteHypothesisRequest(
            dem=None,
            start=GeoPoint(x=0, y=0, crs=CRS),
            destination=GeoPoint(x=20, y=0, crs=CRS),
            requested_at=FIXED_TIME,
        )
    return TerrainRouteHypothesisRequest(
        dem=dem,
        start=_point(dem, 0, 0),
        destination=_point(dem, dem.shape[0] - 1, dem.shape[1] - 1),
        requested_at=FIXED_TIME,
    )


def _path_cells(hypothesis: TerrainRouteHypothesis, dem: TerrainDemRaster) -> list[tuple[int, int]]:
    return [
        dem.row_col_for_point(GeoPoint(x=x, y=y, crs=dem.crs))
        for x, y in hypothesis.best_path.coordinates
    ]


def test_flat_plain_generates_candidate_only_hypothesis_with_provenance() -> None:
    dem = _dem([[100.0 for _ in range(5)] for _ in range(5)])

    run = _service().generate(_request(dem))

    assert run.status is TerrainRouteRunStatus.COMPLETED
    assert run.candidate_only is True
    assert run.runtime_safety_truth is False
    assert run.safe_or_walkable == "not_determined"
    hypothesis = run.hypotheses[0]
    assert hypothesis.authority is TerrainHypothesisAuthority.CANDIDATE_ONLY
    assert hypothesis.source_type is TerrainEvidenceSourceType.TERRAIN_HYPOTHESIS
    assert hypothesis.candidate_only is True
    assert hypothesis.runtime_safety_truth is False
    assert hypothesis.safe_or_walkable == "not_determined"
    assert hypothesis.resolution_class is TerrainResolutionClass.MACRO_TERRAIN_ONLY
    assert hypothesis.dem_resolution_m == 20.0
    assert any("one-metre" in item for item in hypothesis.confidence_limits)
    assert hypothesis.provenance.dem_dataset_id == "synthetic-dem"
    assert hypothesis.provenance.dem_resolution_m == 20.0
    assert hypothesis.provenance.dem_crs == CRS
    assert hypothesis.provenance.modules_executed == [
        "grass:r.slope.aspect",
        "grass:r.mapcalc",
        "grass:r.walk",
        "grass:r.path",
    ]
    assert hypothesis.provenance.processing_manifest["contour_policy"].startswith(
        "DEM primary"
    )
    assert {
        unknown.code for unknown in hypothesis.unknowns
    } >= {
        "vegetation_unknown",
        "trail_surface_unknown",
        "legal_access_unknown",
        "recent_landslide_unknown",
        "microterrain_unknown",
    }
    payload = hypothesis.model_dump(mode="json")
    assert payload["boundary"]["writes_to_official_trail_db"] is False
    assert payload["boundary"]["writes_to_safety_truth"] is False


def test_piecewise_slope_cost_is_nonlinear_and_never_labels_passability() -> None:
    config = TerrainRoutingCostConfig()

    low = slope_cost_for_degrees(8.0, config)
    moderate = slope_cost_for_degrees(18.0, config)
    high = slope_cost_for_degrees(35.0, config)
    extreme = slope_cost_for_degrees(45.0, config)

    assert low == pytest.approx(1.0)
    assert moderate > low
    assert high > moderate * 4
    assert extreme > high * 2
    assert not (PROHIBITED_PROMOTION_LABELS & {band.label for band in config.slope_cost_bands})


def test_route_prefers_saddle_gap_and_corridor_contains_best_path() -> None:
    cells = [[0.0 for _ in range(7)] for _ in range(7)]
    for row in range(7):
        cells[row][3] = 420.0
    cells[3][3] = 0.0
    dem = _dem(cells)
    request = TerrainRouteHypothesisRequest(
        dem=dem,
        start=_point(dem, 1, 0),
        destination=_point(dem, 5, 6),
        requested_at=FIXED_TIME,
    )

    run = _service().generate(request)

    assert run.status is TerrainRouteRunStatus.COMPLETED
    hypothesis = run.hypotheses[0]
    path_cells = _path_cells(hypothesis, dem)
    assert (3, 3) in path_cells
    assert all(col != 3 or row == 3 for row, col in path_cells)
    assert hypothesis.corridor is not None
    assert [band.name for band in hypothesis.corridor.bands] == [
        "top_5_percent_corridor",
        "top_10_percent_corridor",
        "top_20_percent_corridor",
    ]
    assert all(band.contains_best_path for band in hypothesis.corridor.bands)
    assert hypothesis.path_model == "anisotropic_walk"
    assert hypothesis.path_semantics == "minimum_anisotropic_model_cost_trace"
    assert hypothesis.corridor.band_model == "symmetric_macro_terrain_cost"
    assert hypothesis.corridor.path_relationship == (
        "separate_model_not_path_confidence_band"
    )
    assert all(
        band.best_path_union_applied is False
        for band in hypothesis.corridor.bands
    )
    assert all(band.source_type is TerrainEvidenceSourceType.TERRAIN_HYPOTHESIS for band in hypothesis.corridor.bands)


def test_authority_model_rejects_promotion_to_observed_official_or_safe_labels() -> None:
    dem = _dem([[10.0 for _ in range(3)] for _ in range(3)])
    hypothesis = _service().generate(_request(dem)).hypotheses[0]
    payload = hypothesis.model_dump(mode="json")

    assert TerrainEvidenceSourceType.TERRAIN_HYPOTHESIS != TerrainEvidenceSourceType.OBSERVED_TRAIL
    assert TerrainEvidenceSourceType.TERRAIN_HYPOTHESIS != TerrainEvidenceSourceType.OFFICIAL_TRAIL
    with pytest.raises(ValidationError, match="source_type cannot be promoted"):
        TerrainRouteHypothesis.model_validate(
            {**payload, "source_type": "official_trail"}
        )
    with pytest.raises(ValidationError, match="safe_route"):
        TerrainRouteHypothesis.model_validate({**payload, "label": "safe_route"})


@pytest.mark.parametrize(
    ("hypothesis_request", "expected_code"),
    [
        (_request(None), TerrainRouteFailureCode.MISSING_DEM),
        (
            TerrainRouteHypothesisRequest(
                dem=_dem([[1.0, None], [1.0, 1.0]]),
                start=GeoPoint(x=0, y=20, crs=CRS),
                destination=GeoPoint(x=20, y=0, crs=CRS),
                requested_at=FIXED_TIME,
            ),
            TerrainRouteFailureCode.NODATA_PRESENT,
        ),
        (
            TerrainRouteHypothesisRequest(
                dem=_dem([[1.0, 1.0], [1.0, 1.0]], resolution_m=120.0),
                start=GeoPoint(x=0, y=120, crs=CRS),
                destination=GeoPoint(x=120, y=0, crs=CRS),
                requested_at=FIXED_TIME,
            ),
            TerrainRouteFailureCode.DEM_RESOLUTION_TOO_LOW,
        ),
        (
            TerrainRouteHypothesisRequest(
                dem=_dem([[1.0, 1.0], [1.0, 1.0]]),
                start=GeoPoint(x=0, y=20, crs="EPSG:4326"),
                destination=GeoPoint(x=20, y=0, crs=CRS),
                requested_at=FIXED_TIME,
            ),
            TerrainRouteFailureCode.CRS_MISMATCH,
        ),
        (
            TerrainRouteHypothesisRequest(
                dem=_dem([[1.0, 1.0], [1.0, 1.0]]),
                start=GeoPoint(x=-100, y=20, crs=CRS),
                destination=GeoPoint(x=20, y=0, crs=CRS),
                requested_at=FIXED_TIME,
            ),
            TerrainRouteFailureCode.ENDPOINT_OUTSIDE_DEM,
        ),
    ],
)
def test_fail_closed_preflight_errors(
    hypothesis_request: TerrainRouteHypothesisRequest,
    expected_code: TerrainRouteFailureCode,
) -> None:
    run = _service().generate(hypothesis_request)

    assert run.status is TerrainRouteRunStatus.UNAVAILABLE
    assert run.failure is not None
    assert run.failure.code is expected_code
    assert run.candidate_only is True
    assert run.runtime_safety_truth is False


def test_grass_unavailable_and_rwalk_failure_are_typed_failures() -> None:
    dem = _dem([[1.0 for _ in range(3)] for _ in range(3)])

    unavailable = _service(GrassTerrainBackend()).generate(_request(dem))
    rwalk_failed = _service(
        FakeTerrainBackend(failure_code=TerrainRouteFailureCode.RWALK_FAILED)
    ).generate(_request(dem))

    assert unavailable.status is TerrainRouteRunStatus.UNAVAILABLE
    assert unavailable.failure is not None
    assert unavailable.failure.code is TerrainRouteFailureCode.GRASS_UNAVAILABLE
    assert rwalk_failed.status is TerrainRouteRunStatus.UNAVAILABLE
    assert rwalk_failed.failure is not None
    assert rwalk_failed.failure.code is TerrainRouteFailureCode.RWALK_FAILED


def test_no_connected_solution_is_typed_unknown_not_a_guess() -> None:
    dem = _dem([[1.0 for _ in range(5)] for _ in range(5)])
    blocked = {(row, 2) for row in range(5)}

    run = _service(FakeTerrainBackend(blocked_cells=blocked)).generate(_request(dem))

    assert run.status is TerrainRouteRunStatus.UNAVAILABLE
    assert run.failure is not None
    assert run.failure.code is TerrainRouteFailureCode.NO_CONNECTED_SOLUTION
    assert run.hypotheses == []


def test_reproducible_for_same_dem_endpoints_and_config() -> None:
    dem = _dem(
        [
            [100.0, 100.0, 110.0, 120.0],
            [100.0, 105.0, 110.0, 120.0],
            [100.0, 110.0, 112.0, 120.0],
            [100.0, 115.0, 116.0, 120.0],
        ]
    )
    request = _request(dem)

    first = _service().generate(request)
    second = _service().generate(request)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
