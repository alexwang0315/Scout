from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from scout_risk.cli import app
from scout_risk.geo import wgs84_to_twd97
from scout_risk.overpass.route_base import build_overpass_route_base


def test_overpass_route_base_uses_osm_geometry_with_gpx_as_alignment_only(
    tmp_path: Path,
):
    overpass_path, reference_gpx_path, _ = _write_overpass_fixture(tmp_path)

    route_base = build_overpass_route_base(
        overpass_geojson_path=overpass_path,
        reference_gpx_path=reference_gpx_path,
        corridor_m=20.0,
    )

    assert 24.0 <= route_base.points[0].lat <= 24.001
    assert 121.0 <= route_base.points[0].lon <= 121.001
    assert route_base.metadata["reference_gpx_not_used_as_route_centerline"] is True
    assert route_base.metadata["route_base"] == "overpass_vector_evidence"
    assert route_base.metadata["sampling_strategy"] == (
        "reference_progress_projected_to_nearest_overpass_segment.v1"
    )
    assert route_base.metadata["selected_feature_count"] == 1
    assert route_base.metadata["projected_reference_sample_count"] == (
        route_base.metadata["reference_sample_count"]
    )
    assert route_base.metadata["fallback_reference_sample_count"] == 0
    assert route_base.sample_metadata[0]["route_base_source"] == "overpass_projection"
    assert "reference_distance_m" in route_base.sample_metadata[0]


def test_overpass_route_base_projects_to_nearest_segment_not_all_corridor_vertices(
    tmp_path: Path,
):
    overpass_path = tmp_path / "overpass.geojson"
    overpass_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [
                                [121.0, 24.0],
                                [121.0005, 24.0],
                                [121.001, 24.0],
                            ],
                        },
                        "properties": {
                            "id": "overpass.trail_corridor_candidate.way.main",
                            "candidate_type": "trail_corridor_candidate",
                        },
                    },
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [
                                [121.0004, 24.00008],
                                [121.0004, 24.00045],
                            ],
                        },
                        "properties": {
                            "id": "overpass.trail_corridor_candidate.way.spur",
                            "candidate_type": "trail_corridor_candidate",
                        },
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    reference_gpx_path = tmp_path / "reference.gpx"
    reference_gpx_path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><trkseg>
    <trkpt lat="24.0" lon="121.0"/>
    <trkpt lat="24.0" lon="121.001"/>
  </trkseg></trk>
</gpx>
""",
        encoding="utf-8",
    )

    route_base = build_overpass_route_base(
        overpass_geojson_path=overpass_path,
        reference_gpx_path=reference_gpx_path,
        corridor_m=60.0,
    )

    assert route_base.metadata["selected_feature_ids"] == [
        "overpass.trail_corridor_candidate.way.main"
    ]
    assert route_base.metadata["selected_feature_count"] == 1
    assert all(abs(point.lat - 24.0) < 1e-8 for point in route_base.points)
    assert all(121.0 <= point.lon <= 121.001 for point in route_base.points)


def test_cli_overpass_route_profile_reads_twd97_dtm_tiles(tmp_path: Path):
    overpass_path, reference_gpx_path, route_coords = _write_overpass_fixture(tmp_path)
    coverage_path = _write_dtm_coverage_fixture(tmp_path, route_coords)
    out_path = tmp_path / "route_risk.geojson"
    csv_path = tmp_path / "route_risk.csv"
    metadata_path = tmp_path / "route_risk.metadata.json"
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "overpass-route-profile",
            "--dtm-coverage",
            str(coverage_path),
            "--overpass",
            str(overpass_path),
            "--reference-gpx",
            str(reference_gpx_path),
            "--out",
            str(out_path),
            "--csv-out",
            str(csv_path),
            "--metadata-out",
            str(metadata_path),
            "--sample-interval-m",
            "60",
            "--corridor-m",
            "25",
            "--dem-buffer-m",
            "80",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["type"] == "FeatureCollection"
    assert len(payload["features"]) >= 2
    assert payload["features"][0]["properties"]["route_base_source"] == (
        "overpass_projection"
    )
    assert csv_path.is_file()
    assert metadata["boundary"]["route_base_is_overpass_vector_evidence"] is True
    assert metadata["boundary"]["reference_gpx_not_used_as_route_centerline"] is True
    assert metadata["terrain_risk_config"]["source"].endswith(
        "terrain_risk_profile.default.toml"
    )
    assert metadata["terrain_risk_config"]["parameters"]["route_preparation"][
        "sample_interval_m"
    ] == 20.0
    assert metadata["route_preparation"]["sample_interval_m"] == 60.0
    assert metadata["route_preparation"]["overpass_corridor_m"] == 25.0
    assert metadata["route_preparation"]["dem_buffer_m"] == 80.0
    assert metadata["dtm_mosaic"]["used_tile_count"] == 1
    assert metadata["dtm_mosaic"]["raw_dtm_copied"] is False
    assert all(
        0 <= feature["properties"]["pretrip_risk"] <= 100
        for feature in payload["features"]
    )


def _write_overpass_fixture(tmp_path: Path) -> tuple[Path, Path, list[tuple[float, float]]]:
    route_coords = [(121.0, 24.0), (121.0005, 24.0005), (121.001, 24.001)]
    overpass_path = tmp_path / "overpass.geojson"
    overpass_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[lon, lat] for lon, lat in route_coords],
                        },
                        "properties": {
                            "id": "overpass.trail_corridor_candidate.way.1",
                            "candidate_type": "trail_corridor_candidate",
                            "osm_type": "way",
                            "osm_id": 1,
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    reference_gpx_path = tmp_path / "reference.gpx"
    reference_gpx_path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><trkseg>
    <trkpt lat="24.00005" lon="121.00005"/>
    <trkpt lat="24.00055" lon="121.00055"/>
    <trkpt lat="24.00105" lon="121.00105"/>
  </trkseg></trk>
</gpx>
""",
        encoding="utf-8",
    )
    return overpass_path, reference_gpx_path, route_coords


def _write_dtm_coverage_fixture(
    tmp_path: Path,
    route_coords: list[tuple[float, float]],
) -> Path:
    projected = [wgs84_to_twd97(lat, lon) for lon, lat in route_coords]
    xs = [point[0] for point in projected]
    ys = [point[1] for point in projected]
    min_x = int(min(xs) // 20 * 20 - 100)
    max_x = int(max(xs) // 20 * 20 + 120)
    min_y = int(min(ys) // 20 * 20 - 100)
    max_y = int(max(ys) // 20 * 20 + 120)
    grid_path = tmp_path / "syntheticdem.grd"
    with grid_path.open("w", encoding="utf-8") as handle:
        for y in range(max_y, min_y - 1, -20):
            for x in range(min_x, max_x + 1, 20):
                elevation = 1000.0 + (x - min_x) * 0.15 + (max_y - y) * 0.05
                handle.write(f"{x} {y} {elevation:.2f}\n")
    coverage_path = tmp_path / "dtm_coverage_summary.json"
    coverage_path.write_text(
        json.dumps(
            {
                "source_dirs": [str(tmp_path)],
                "candidate_tiles": [
                    {
                        "grid_uri": str(grid_path),
                        "bbox_twd97": {
                            "min_x": min_x,
                            "min_y": min_y,
                            "max_x": max_x,
                            "max_y": max_y,
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return coverage_path
