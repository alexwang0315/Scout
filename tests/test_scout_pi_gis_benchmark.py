from __future__ import annotations

from pathlib import Path

import pytest

from tools.scout_pi_gis_benchmark import (
    BenchmarkError,
    _bounded_window,
    _candidate_authority,
    _parse_gpx_points,
    _parse_route_dem_coverage,
    _route_points_in_window,
    _source_window,
    _validate_command,
)


def test_parse_gpx_points_and_deterministically_bound_count(tmp_path: Path) -> None:
    gpx = tmp_path / "route.gpx"
    gpx.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<gpx xmlns="http://www.topografix.com/GPX/1/1">
  <trk><trkseg>
    <trkpt lat="23.0" lon="121.0" />
    <trkpt lat="23.1" lon="121.1" />
    <trkpt lat="23.2" lon="121.2" />
    <trkpt lat="23.3" lon="121.3" />
    <trkpt lat="23.4" lon="121.4" />
  </trkseg></trk>
</gpx>
""",
        encoding="utf-8",
    )

    assert _parse_gpx_points(gpx, max_points=3) == [
        [121.0, 23.0],
        [121.2, 23.2],
        [121.4, 23.4],
    ]


def test_parse_gpx_points_fails_closed_for_missing_geometry(tmp_path: Path) -> None:
    gpx = tmp_path / "empty.gpx"
    gpx.write_text("<gpx />", encoding="utf-8")

    with pytest.raises(BenchmarkError, match="at least two"):
        _parse_gpx_points(gpx)


def test_bounded_window_intersects_dem_and_enforces_cell_limit() -> None:
    window = _bounded_window(
        projected_points=[(110.0, 120.0), (180.0, 190.0)],
        raster_bounds=(100.0, 100.0, 200.0, 200.0),
        corridor_m=10.0,
        pixel_size=(10.0, 10.0),
        max_cells=1_000,
    )

    assert window == {
        "min_x": 100.0,
        "min_y": 110.0,
        "max_x": 190.0,
        "max_y": 200.0,
        "cols": 9,
        "rows": 9,
        "cells": 81,
    }

    with pytest.raises(BenchmarkError, match="cell limit"):
        _bounded_window(
            projected_points=[(100.0, 100.0), (200.0, 200.0)],
            raster_bounds=(0.0, 0.0, 1_000.0, 1_000.0),
            corridor_m=500.0,
            pixel_size=(1.0, 1.0),
            max_cells=100,
        )


@pytest.mark.parametrize(
    ("geo_transform", "expected"),
    [
        ((100.0, 10.0, 0.0, 200.0, 0.0, -10.0), (1, 1, 3, 3)),
        ((100.0, 10.0, 0.0, 100.0, 0.0, 10.0), (1, 1, 3, 3)),
    ],
)
def test_source_window_supports_north_up_and_south_up_dem(
    geo_transform: tuple[float, ...],
    expected: tuple[int, int, int, int],
) -> None:
    spatial_window = {
        "min_x": 110.0,
        "min_y": 110.0 if geo_transform[5] > 0 else 160.0,
        "max_x": 140.0,
        "max_y": 140.0 if geo_transform[5] > 0 else 190.0,
    }

    assert _source_window(
        spatial_window=spatial_window,
        geo_transform=geo_transform,
        raster_size=(10, 10),
    ) == expected


def test_route_points_in_window_keeps_bounded_segment_and_edge_context() -> None:
    assert _route_points_in_window(
        wgs84_points=[
            [121.00, 23.00],
            [121.01, 23.01],
            [121.02, 23.02],
            [121.03, 23.03],
            [121.04, 23.04],
        ],
        projected_points=[
            (0.0, 0.0),
            (10.0, 10.0),
            (20.0, 20.0),
            (30.0, 30.0),
            (40.0, 40.0),
        ],
        spatial_window={"min_x": 15.0, "min_y": 15.0, "max_x": 35.0, "max_y": 35.0},
    ) == [
        [121.01, 23.01],
        [121.02, 23.02],
        [121.03, 23.03],
        [121.04, 23.04],
    ]


def test_route_points_in_window_does_not_join_disconnected_tile_visits() -> None:
    wgs84_points = [[121.0 + index / 100.0, 23.0] for index in range(9)]
    projected_points = [
        (20.0, 20.0),
        (21.0, 21.0),
        (100.0, 100.0),
        (100.0, 100.0),
        (20.0, 20.0),
        (21.0, 21.0),
        (22.0, 22.0),
        (23.0, 23.0),
        (100.0, 100.0),
    ]

    assert _route_points_in_window(
        wgs84_points=wgs84_points,
        projected_points=projected_points,
        spatial_window={"min_x": 10.0, "min_y": 10.0, "max_x": 30.0, "max_y": 30.0},
    ) == wgs84_points[3:9]


def test_external_command_allowlist_rejects_shell_and_unknown_tools() -> None:
    assert _validate_command(["gdaldem", "slope", "in.tif", "out.tif"])[0] == (
        "gdaldem"
    )
    assert _validate_command(["gdallocationinfo", "-valonly", "dem.tif"])[0] == (
        "gdallocationinfo"
    )

    for command in (["bash", "-c", "id"], ["python3", "-c", "print(1)"], []):
        with pytest.raises(BenchmarkError):
            _validate_command(command)


def test_route_dem_coverage_keeps_nodata_separate_from_processing_success() -> None:
    assert _parse_route_dem_coverage(
        "100.5\n-9999\n245.25\n",
        expected_count=3,
        nodata_value=-9999.0,
    ) == {
        "sampled_route_point_count": 3,
        "valid_route_point_count": 2,
        "nodata_route_point_count": 1,
        "valid_route_point_percent": 66.6667,
        "complete_route_point_coverage": False,
    }


def test_route_dem_coverage_fails_closed_on_incomplete_tool_output() -> None:
    with pytest.raises(BenchmarkError, match="incomplete"):
        _parse_route_dem_coverage(
            "100.5\n",
            expected_count=2,
            nodata_value=-9999.0,
        )


def test_candidate_authority_is_fail_closed() -> None:
    assert _candidate_authority() == {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "operational": False,
        "benchmark_only": True,
    }
