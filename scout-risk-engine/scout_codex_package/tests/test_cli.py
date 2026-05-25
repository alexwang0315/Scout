from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from typer.testing import CliRunner

from scout_risk.cli import app


def test_cli_compute_teii_and_calibration_placeholder(tmp_path: Path):
    dem_path = tmp_path / "dem.npy"
    teii_path = tmp_path / "teii.npy"
    report_path = tmp_path / "calibration.json"
    np.save(dem_path, np.full((6, 6), 1000.0))
    runner = CliRunner()

    teii_result = runner.invoke(app, ["compute-teii", "--dem", str(dem_path), "--out", str(teii_path)])
    report_result = runner.invoke(app, ["calibration-report", "--out", str(report_path)])

    assert teii_result.exit_code == 0
    assert report_result.exit_code == 0
    assert teii_path.is_file()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["status"] == "placeholder_only"
    assert payload["boundary"]["ml_training_performed"] is False


def test_cli_route_profile_outputs_geojson_and_csv(tmp_path: Path):
    dem_path = tmp_path / "geo_dem.npz"
    gpx_path = tmp_path / "route.gpx"
    cp_path = tmp_path / "cp.csv"
    geojson_path = tmp_path / "route.geojson"
    csv_path = tmp_path / "route.csv"
    np.savez(
        dem_path,
        elevation=np.arange(16, dtype=float).reshape(4, 4) * 10.0,
        x_min=121.0,
        y_max=24.003,
        pixel_size=0.001,
        crs="EPSG:4326",
    )
    gpx_path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><trkseg>
    <trkpt lat="24.003" lon="121.000"><ele>1000</ele></trkpt>
    <trkpt lat="24.001" lon="121.002"><ele>1030</ele></trkpt>
  </trkseg></trk>
</gpx>
""",
        encoding="utf-8",
    )
    cp_path.write_text(
        "lat,lon,text\n24.002,121.001,大崩壁需高繞\n",
        encoding="utf-8",
    )
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "route-profile",
            "--dem",
            str(dem_path),
            "--gpx",
            str(gpx_path),
            "--cp",
            str(cp_path),
            "--out",
            str(geojson_path),
            "--csv-out",
            str(csv_path),
            "--sample-interval-m",
            "100",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(geojson_path.read_text(encoding="utf-8"))
    assert payload["type"] == "FeatureCollection"
    assert len(payload["features"]) >= 2
    assert csv_path.is_file()
    assert any(
        "collapse" in feature["properties"]["hazard_types"]
        for feature in payload["features"]
    )


def test_cli_route_profile_uses_config_sample_interval(tmp_path: Path):
    dem_path = tmp_path / "geo_dem.npz"
    gpx_path = tmp_path / "route.gpx"
    config_path = tmp_path / "terrain_config.toml"
    geojson_path = tmp_path / "route.geojson"
    np.savez(
        dem_path,
        elevation=np.full((4, 4), 1000.0),
        x_min=121.0,
        y_max=24.003,
        pixel_size=0.001,
        crs="EPSG:4326",
    )
    gpx_path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><trkseg>
    <trkpt lat="24.003" lon="121.000"/>
    <trkpt lat="24.001" lon="121.002"/>
  </trkseg></trk>
</gpx>
""",
        encoding="utf-8",
    )
    config_path.write_text(
        """
[route_preparation]
sample_interval_m = 500.0
""",
        encoding="utf-8",
    )
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "route-profile",
            "--dem",
            str(dem_path),
            "--gpx",
            str(gpx_path),
            "--out",
            str(geojson_path),
            "--config",
            str(config_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(geojson_path.read_text(encoding="utf-8"))
    assert len(payload["features"]) == 2
