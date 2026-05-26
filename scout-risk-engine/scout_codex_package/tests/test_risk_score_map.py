from __future__ import annotations

import csv
import json
from pathlib import Path

from typer.testing import CliRunner

from scout_risk.cli import app
from scout_risk.route.risk_score_map import (
    build_risk_ribbon_from_geojson,
    build_risk_score_point_map_from_geojson,
    write_risk_ribbon_geojson,
    write_risk_ribbon_metadata,
    write_risk_score_csv,
    write_risk_score_geojson,
    write_risk_score_metadata,
    write_risk_score_xyz,
)


def test_risk_score_point_map_snaps_to_grid_and_keeps_highest_score(tmp_path: Path):
    route_risk_path = _write_route_risk_fixture(tmp_path)

    point_map = build_risk_score_point_map_from_geojson(
        route_risk_path,
        snap_grid_m=1000.0,
    )

    assert len(point_map.points) == 2
    first = point_map.points[0]
    assert first.rs == 70.0
    assert first.sample_id == "sample.0001"
    assert first.source_sample_count == 2
    assert first.source_sample_ids == ("sample.0000", "sample.0001")
    assert point_map.metadata["aggregation"] == "max_score_per_twd97_grid_cell"
    assert point_map.metadata["boundary"]["candidate_only"] is True
    assert point_map.metadata["boundary"]["runtime_safety_truth"] is False


def test_risk_score_point_map_writes_csv_xyz_geojson_and_metadata(tmp_path: Path):
    route_risk_path = _write_route_risk_fixture(tmp_path)
    point_map = build_risk_score_point_map_from_geojson(route_risk_path, snap_grid_m=1000.0)
    csv_path = tmp_path / "risk_points.csv"
    xyz_path = tmp_path / "risk_points.xyz"
    geojson_path = tmp_path / "risk_points.geojson"
    metadata_path = tmp_path / "risk_points.metadata.json"

    write_risk_score_csv(point_map, csv_path)
    write_risk_score_xyz(point_map, xyz_path)
    write_risk_score_geojson(point_map, geojson_path)
    write_risk_score_metadata(point_map, metadata_path)

    rows = list(csv.DictReader(csv_path.open("r", encoding="utf-8")))
    assert rows[0]["rs"] == "70.0"
    assert rows[0]["score_field"] == "pretrip_risk"
    assert len(xyz_path.read_text(encoding="utf-8").splitlines()) == 2
    geojson = json.loads(geojson_path.read_text(encoding="utf-8"))
    assert geojson["type"] == "FeatureCollection"
    assert geojson["metadata"]["point_count"] == 2
    assert geojson["features"][0]["properties"]["rs"] == 70.0
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["source_feature_count"] == 3
    assert metadata["point_count"] == 2


def test_cli_risk_score_map_outputs_point_files(tmp_path: Path):
    route_risk_path = _write_route_risk_fixture(tmp_path)
    csv_path = tmp_path / "risk_points.csv"
    xyz_path = tmp_path / "risk_points.xyz"
    metadata_path = tmp_path / "risk_points.metadata.json"
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "risk-score-map",
            "--route-risk",
            str(route_risk_path),
            "--csv-out",
            str(csv_path),
            "--xyz-out",
            str(xyz_path),
            "--metadata-out",
            str(metadata_path),
            "--snap-grid-m",
            "1000",
        ],
    )

    assert result.exit_code == 0
    assert csv_path.is_file()
    assert xyz_path.is_file()
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["score_field"] == "pretrip_risk"
    assert metadata["snap_grid_m"] == 1000.0


def test_risk_ribbon_geojson_uses_adjacent_samples_and_risk_buckets(tmp_path: Path):
    route_risk_path = _write_route_risk_fixture(tmp_path)
    ribbon = build_risk_ribbon_from_geojson(route_risk_path)

    assert len(ribbon.features) == 2
    first = ribbon.features[0]
    assert first["geometry"]["type"] == "LineString"
    assert first["properties"]["from_sample_id"] == "sample.0000"
    assert first["properties"]["to_sample_id"] == "sample.0001"
    assert first["properties"]["rs"] == 70.0
    assert first["properties"]["risk_bucket"] == "high"
    assert first["properties"]["interpolated_surface"] is False
    assert ribbon.metadata["boundary"]["candidate_only"] is True
    assert ribbon.metadata["boundary"]["route_aligned_samples_only"] is True


def test_risk_ribbon_writes_geojson_and_metadata(tmp_path: Path):
    route_risk_path = _write_route_risk_fixture(tmp_path)
    ribbon = build_risk_ribbon_from_geojson(route_risk_path)
    geojson_path = tmp_path / "risk_ribbon.geojson"
    metadata_path = tmp_path / "risk_ribbon.metadata.json"

    write_risk_ribbon_geojson(ribbon, geojson_path)
    write_risk_ribbon_metadata(ribbon, metadata_path)

    payload = json.loads(geojson_path.read_text(encoding="utf-8"))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["type"] == "FeatureCollection"
    assert payload["metadata"]["segment_count"] == 2
    assert payload["features"][0]["properties"]["style_class"] == "risk-ribbon-high"
    assert metadata["score_surface_type"] == "route_aligned_risk_ribbon"


def test_cli_risk_ribbon_outputs_route_aligned_segments(tmp_path: Path):
    route_risk_path = _write_route_risk_fixture(tmp_path)
    out_path = tmp_path / "risk_ribbon.geojson"
    metadata_path = tmp_path / "risk_ribbon.metadata.json"
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "risk-ribbon",
            "--route-risk",
            str(route_risk_path),
            "--out",
            str(out_path),
            "--metadata-out",
            str(metadata_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert len(payload["features"]) == 2
    assert metadata["segment_count"] == 2


def _write_route_risk_fixture(tmp_path: Path) -> Path:
    route_risk_path = tmp_path / "route_risk.geojson"
    route_risk_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    _feature("sample.0000", 121.0, 24.0, 10.0, 40.0, 2),
                    _feature("sample.0001", 121.0, 24.0, 20.0, 70.0, 4),
                    _feature("sample.0002", 121.01, 24.01, 30.0, 55.0, 3),
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return route_risk_path


def _feature(
    sample_id: str,
    lon: float,
    lat: float,
    distance_m: float,
    risk: float,
    level: int,
) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "route_id": "route",
            "sample_id": sample_id,
            "distance_m": distance_m,
            "elevation_m": 1000.0,
            "teii_20m": risk,
            "tri": 0.0,
            "sri": 0.0,
            "lec": risk,
            "scp": 0.0,
            "pretrip_risk": risk,
            "risk_level": level,
        },
    }
