from __future__ import annotations

import json
from pathlib import Path

from tools.compare_scout_qgis_terrain_candidates import build_comparison_report


def _write_gpx(path: Path) -> None:
    path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><trkseg>
    <trkpt lat="24.000000" lon="121.000000"/>
    <trkpt lat="24.000000" lon="121.010000"/>
  </trkseg></trk>
</gpx>
""",
        encoding="utf-8",
    )


def _line_feature(
    candidate_id: str,
    kind: str,
    coordinates: list[list[float]],
) -> dict[str, object]:
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coordinates},
        "properties": {
            "id": candidate_id,
            "kind": kind,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
        },
    }


def test_comparison_report_filters_by_start_and_separates_agreement_from_accuracy(
    tmp_path: Path,
) -> None:
    navigation_path = tmp_path / "navigation.json"
    navigation_path.write_text(
        json.dumps(
            {
                "terrain_hierarchy": {
                    "edges": [
                        {
                            "id": "scout-ridge-near",
                            "kind": "main_ridge_candidate",
                            "coordinates": [
                                {"lon": 121.001, "lat": 24.000045},
                                {"lon": 121.0012, "lat": 24.000045},
                            ],
                        },
                        {
                            "id": "scout-ridge-far-start",
                            "kind": "spur_ridge_candidate",
                            "coordinates": [
                                {"lon": 121.002, "lat": 24.000180},
                                {"lon": 121.0022, "lat": 24.000000},
                            ],
                        },
                        {
                            "id": "scout-drainage-near",
                            "kind": "drainage_trunk",
                            "coordinates": [
                                {"lon": 121.004, "lat": 24.000000},
                                {"lon": 121.0042, "lat": 24.000000},
                            ],
                        },
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    workflow_path = tmp_path / "workflow.json"
    workflow_path.write_text(
        json.dumps(
            {
                "workflow_run_id": "qgis-run-test",
                "maplibre_geojson": {
                    "type": "FeatureCollection",
                    "features": [
                        _line_feature(
                            "qgis-ridge-supported",
                            "qgis_candidate_ridge_line",
                            [[121.001, 24.000055], [121.0012, 24.000055]],
                        ),
                        _line_feature(
                            "qgis-ridge-unmatched",
                            "qgis_candidate_ridge_line",
                            [[121.008, 24.000045], [121.0082, 24.000045]],
                        ),
                        _line_feature(
                            "qgis-valley-supported",
                            "qgis_candidate_valley_line",
                            [[121.004, 24.000010], [121.0042, 24.000010]],
                        ),
                        _line_feature(
                            "qgis-stream-unmatched",
                            "qgis_candidate_stream_network",
                            [[121.007, 24.000010], [121.0072, 24.000010]],
                        ),
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    gpx_path = tmp_path / "golden.gpx"
    _write_gpx(gpx_path)

    report = build_comparison_report(
        navigation_path=navigation_path,
        workflow_path=workflow_path,
        golden_gpx_path=gpx_path,
        start_corridor_m=10.0,
        agreement_tolerance_m=20.0,
    )

    assert report["boundary"] == {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "operational": False,
        "accuracy_determined": False,
    }
    assert report["groups"]["scout_ridge"]["total"] == 2
    assert report["groups"]["scout_ridge"]["displayed"] == 1
    assert report["groups"]["scout_ridge"]["hidden_by_start_corridor"] == 1
    ridge = report["comparisons"]["ridge"]
    assert ridge["scout_ridge"]["within_tolerance"] == 1
    assert ridge["qgis_ridge"]["within_tolerance"] == 1
    assert ridge["qgis_ridge"]["outside_tolerance"] == 1
    assert ridge["non_overlap_qgis_ridge"][0]["candidate_id"] == (
        "qgis-ridge-unmatched"
    )
    assert report["comparisons"]["valley_morphology"]["qgis_valley"][
        "within_tolerance"
    ] == 1
    assert report["comparisons"]["flow_channel"]["qgis_stream"][
        "outside_tolerance"
    ] == 1
    assert "agreement is not accuracy" in report["interpretation"][0].lower()
