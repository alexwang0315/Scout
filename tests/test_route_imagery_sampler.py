from route_imagery_sampler import (
    RasterGrid,
    build_route_buffer,
    sample_radar_grid,
    sample_satellite_grid,
)


def test_route_buffer_sampling_detects_overlap_and_nearby_strong_echo() -> None:
    route_buffer = build_route_buffer(
        [(24.0, 121.0), (24.0, 121.02)],
        buffer_m=2_000,
    )
    grid = RasterGrid(
        west=120.98,
        south=23.98,
        east=121.04,
        north=24.02,
        values=(
            (0.0, 0.0, 0.0, 0.0),
            (0.0, 25.0, 48.0, 0.0),
            (0.0, 30.0, 52.0, 0.0),
            (0.0, 0.0, 0.0, 0.0),
        ),
    )

    sample = sample_radar_grid(
        grid,
        route_buffer,
        source_timestamp="2026-07-11T03:20:00Z",
        fetched_at="2026-07-11T03:27:00Z",
    )

    assert sample["currentRainOnRoute"] is True
    assert sample["nearbyStrongEcho"] is True
    assert sample["maxReflectivityDbz"] == 52.0
    assert sample["strongEchoCentroid"] is not None
    assert "values" not in sample
    assert route_buffer.to_geojson()["geometry"]["type"] == "MultiPolygon"


def test_satellite_sampler_outputs_compact_convective_score() -> None:
    route_buffer = build_route_buffer([(24.0, 121.0), (24.0, 121.02)], buffer_m=2_000)
    grid = RasterGrid(
        west=120.98,
        south=23.98,
        east=121.04,
        north=24.02,
        values=((0.1, 0.2), (0.85, 0.95)),
    )

    sample = sample_satellite_grid(
        grid,
        route_buffer,
        source_timestamp="2026-07-11T03:20:00Z",
        fetched_at="2026-07-11T03:27:00Z",
    )

    assert 0.0 <= sample["satelliteConvectiveCloudScore"] <= 1.0
    assert sample["convectiveCloudCentroid"] is not None
    assert "values" not in sample


def test_route_sampling_is_unknown_when_grid_cells_are_coarser_than_buffer() -> None:
    route_buffer = build_route_buffer([(24.0, 121.0), (24.0, 121.02)], buffer_m=500)
    row = tuple(50.0 for _ in range(160))
    grid = RasterGrid(
        west=118,
        south=20.5,
        east=124,
        north=26.5,
        values=tuple(row for _ in range(160)),
    )

    sample = sample_radar_grid(
        grid,
        route_buffer,
        source_timestamp="2026-07-11T03:20:00Z",
        fetched_at="2026-07-11T03:27:00Z",
    )

    assert sample["currentRainOnRoute"] is None
    assert sample["coverageConfidence"] == 0
    assert sample["spatialResolutionKm"] > 0.5
