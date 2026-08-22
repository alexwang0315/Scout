import route_imagery_sampler as sampler
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


def test_dense_route_sampling_avoids_all_pairs_segment_checks(monkeypatch) -> None:
    route_buffer = build_route_buffer(
        [(24.0, 121.0 + index * 0.0001) for index in range(500)],
        buffer_m=500,
    )
    segment_index = sampler._build_route_segment_index(route_buffer, bucket_km=0.5)
    assert len(segment_index.segments) < 50
    row = tuple(25.0 for _ in range(12))
    grid = RasterGrid(
        west=120.995,
        south=23.995,
        east=121.055,
        north=24.005,
        values=tuple(row for _ in range(12)),
    )
    original = sampler._point_segment_distance_km
    distance_checks = 0

    def counted_distance(*args: float) -> float:
        nonlocal distance_checks
        distance_checks += 1
        return original(*args)

    monkeypatch.setattr(sampler, "_point_segment_distance_km", counted_distance)

    sample_radar_grid(
        grid,
        route_buffer,
        source_timestamp="2026-07-23T02:40:00Z",
        fetched_at="2026-07-23T02:45:00Z",
    )

    assert distance_checks < 50_000


def test_route_segment_index_matches_brute_force_radius_filter() -> None:
    route_buffer = build_route_buffer(
        [(24.0, 121.0), (24.01, 121.01), (24.0, 121.02)],
        buffer_m=500,
    )
    grid = RasterGrid(
        west=120.98,
        south=23.98,
        east=121.04,
        north=24.03,
        values=tuple(tuple(1.0 for _ in range(8)) for _ in range(8)),
    )
    cells = sampler._grid_cells(grid)

    indexed = sampler._cells_within_route_radius(cells, route_buffer, 0.5)
    brute_force = [
        cell
        for cell in cells
        if sampler.distance_to_route_km(cell[0], cell[1], route_buffer) <= 0.5
    ]

    assert indexed == brute_force


def test_identical_frame_geometry_reuses_route_cell_membership(monkeypatch) -> None:
    route_buffer = build_route_buffer(
        [(24.0, 121.0), (24.01, 121.01), (24.0, 121.02)],
        buffer_m=500,
    )
    grid = RasterGrid(
        west=120.98,
        south=23.98,
        east=121.04,
        north=24.03,
        values=tuple(tuple(25.0 for _ in range(8)) for _ in range(8)),
    )
    original = sampler._build_route_segment_index
    build_calls = 0

    def counted_build(*args, **kwargs):
        nonlocal build_calls
        build_calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(sampler, "_build_route_segment_index", counted_build)
    sampler._route_cell_indices.cache_clear()

    for timestamp in ("2026-07-23T02:40:00Z", "2026-07-23T02:50:00Z"):
        sample_radar_grid(
            grid,
            route_buffer,
            source_timestamp=timestamp,
            fetched_at="2026-07-23T02:55:00Z",
        )
    sample_satellite_grid(
        grid,
        route_buffer,
        source_timestamp="2026-07-23T02:50:00Z",
        fetched_at="2026-07-23T02:55:00Z",
    )

    assert build_calls == 2
