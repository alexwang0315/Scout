from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

from scout_risk.cp.parser import CPNote, parse_cp_notes
from scout_risk.dem.io import DEMGrid
from scout_risk.dem.teii import compute_teii_from_dem
from scout_risk.gpx.parser import load_gpx_points
from scout_risk.gpx.sampling import XYRoutePoint, resample_route_points
from scout_risk.route.outputs import route_profile_to_geojson, write_route_csv
from scout_risk.route.risk_profile import build_route_risk_profile


def test_gpx_parser_and_resampler_reads_track_points(tmp_path: Path):
    gpx_path = tmp_path / "route.gpx"
    gpx_path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><name>synthetic</name><trkseg>
    <trkpt lat="24.0000" lon="121.0000"><ele>1000</ele></trkpt>
    <trkpt lat="24.0010" lon="121.0000"><ele>1010</ele></trkpt>
  </trkseg></trk>
</gpx>
""",
        encoding="utf-8",
    )

    points = load_gpx_points(gpx_path)
    resampled = resample_route_points(points, interval_m=50.0)

    assert len(points) == 2
    assert len(resampled) >= 3
    assert resampled[0].distance_m == 0.0
    assert resampled[-1].distance_m > 100.0


def test_route_risk_profile_outputs_geojson_and_csv(tmp_path: Path):
    y = np.arange(20, dtype=float)[:, None]
    elevation = 1000.0 + y * 30.0
    dem = DEMGrid.from_array(elevation + np.zeros((20, 20)), pixel_size=20.0)
    _, teii = compute_teii_from_dem(dem)
    route_points = [
        XYRoutePoint(
            x=col * 20.0,
            y=dem.y_max - 10 * 20.0,
            distance_m=col * 20.0,
            lat=24.0,
            lon=121.0 + col * 0.0001,
        )
        for col in range(5)
    ]
    cp_notes = parse_cp_notes(
        [
            CPNote(
                lat=24.0,
                lon=121.0002,
                text="大崩壁需高繞，請小心確認現場路跡",
            )
        ]
    )

    profile = build_route_risk_profile(
        route_id="synthetic_route",
        dem=dem,
        teii=teii,
        route_points=route_points,
        cp_notes=cp_notes,
        cp_radius_m=40.0,
    )
    geojson = route_profile_to_geojson(profile)
    csv_path = tmp_path / "route.csv"
    write_route_csv(profile, csv_path)

    assert len(profile.samples) == 5
    assert geojson["type"] == "FeatureCollection"
    assert len(geojson["features"]) == 5
    assert any(sample.scp > 0 for sample in profile.samples)
    assert all(0 <= sample.pretrip_risk <= 100 for sample in profile.samples)
    assert all("safe" not in " ".join(sample.explanation).lower() for sample in profile.samples)
    rows = list(csv.DictReader(csv_path.open("r", encoding="utf-8")))
    assert len(rows) == 5
    assert rows[0]["route_id"] == "synthetic_route"


def test_route_geojson_can_be_serialized(tmp_path: Path):
    dem = DEMGrid.from_array(np.full((4, 4), 1000.0), pixel_size=20.0)
    _, teii = compute_teii_from_dem(dem)
    profile = build_route_risk_profile(
        route_id="flat",
        dem=dem,
        teii=teii,
        route_points=[XYRoutePoint(x=0.0, y=dem.y_max, distance_m=0.0, lat=24.0, lon=121.0)],
    )

    payload = route_profile_to_geojson(profile)

    assert json.loads(json.dumps(payload))["features"][0]["properties"]["risk_level"] == 1

