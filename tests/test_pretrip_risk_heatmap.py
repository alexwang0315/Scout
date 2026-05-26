import json
from pathlib import Path

from pretrip_risk_heatmap import (
    build_calibrated_risk_heatmap,
    heat_bucket,
    heat_thresholds,
)


def test_builds_calibrated_heatmap_from_workspace_diagnostic_shape(tmp_path: Path) -> None:
    route_risk = tmp_path / "route_risk.geojson"
    diagnostic = tmp_path / "risk_attribution_diagnostic.json"
    warnings = tmp_path / "excluded_extreme_warning_cp_proposals.json"
    route_risk.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    _route_risk_feature("sample.001", 24.0, 121.0, 0, 20, 10, 0, 30, 0),
                    _route_risk_feature("sample.002", 24.001, 121.001, 100, 90, 95, 20, 92, 0),
                    _route_risk_feature("sample.003", 24.002, 121.002, 200, 60, 50, 80, 65, 0),
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    diagnostic.write_text(
        json.dumps(
            {
                "schema_version": "0.2.0",
                "factor_analysis": {
                    "formula_candidate": {
                        "status": "candidate_only",
                        "expression": "(tri + 0.8*teii_20m + 0.5*lec) / 2.3",
                        "selected_dimensions": ["tri", "teii_20m", "lec"],
                        "terms": [
                            {"dimension": "tri", "normalized_weight": 0.4},
                            {"dimension": "teii_20m", "normalized_weight": 0.35},
                            {"dimension": "lec", "normalized_weight": 0.25},
                        ],
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    warnings.write_text(
        json.dumps(
            {
                "proposals": [
                    {
                        "proposal_id": "warning_cp.sri.sample.003",
                        "source_sample_id": "sample.003",
                        "excluded_dimension": "sri",
                        "excluded_dimension_value": 80,
                        "lat": 24.002,
                        "lon": 121.002,
                        "candidate_only": True,
                        "runtime_safety_truth": False,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    heatmap = build_calibrated_risk_heatmap(
        route_risk_path=route_risk,
        risk_attribution_diagnostic_path=diagnostic,
        warning_cp_proposals_path=warnings,
    )

    assert heatmap["metadata"]["artifact_kind"] == "pretrip_calibrated_risk_heatmap"
    assert heatmap["metadata"]["status"] == "candidate_only"
    assert heatmap["metadata"]["score_field"] == "calibrated_risk_candidate"
    assert heatmap["metadata"]["boundary"]["runtime_safety_truth"] is False
    assert heatmap["metadata"]["segment_count"] == 2
    assert heatmap["metadata"]["warning_cp_overlay_count"] == 1
    assert heatmap["metadata"]["score_stats"]["max"] > 0
    assert heatmap["metadata"]["style"]["high"]["stroke"] == "#d6a800"
    assert heatmap["features"][0]["properties"]["selected_dimensions"] == [
        "tri",
        "teii_20m",
        "lec",
    ]
    assert heatmap["features"][0]["properties"]["start_factor_values"]["tri"] == 10
    assert heatmap["features"][0]["properties"]["candidate_only"] is True
    assert heatmap["features"][0]["properties"]["relative_bucket"] in {
        "low",
        "moderate",
        "high",
        "very_high",
        "extreme",
    }
    assert heatmap["warning_cp_overlay"][0]["properties"]["overlay_kind"] == (
        "excluded_extreme_warning_cp"
    )


def test_heat_buckets_use_workspace_relative_thresholds() -> None:
    thresholds = heat_thresholds(
        [
            10,
            20,
            30,
            40,
            50,
            60,
            70,
            80,
            90,
            100,
            110,
            120,
            130,
            140,
            150,
            160,
            170,
            180,
            190,
            200,
            210,
        ]
    )

    assert heat_bucket(10, thresholds) == "low"
    assert heat_bucket(thresholds["p50"], thresholds) == "moderate"
    assert heat_bucket(thresholds["p75"], thresholds) == "high"
    assert heat_bucket(thresholds["p90"], thresholds) == "very_high"
    assert heat_bucket(thresholds["p95"], thresholds) == "extreme"


def _route_risk_feature(
    sample_id: str,
    lat: float,
    lon: float,
    distance_m: float,
    teii_20m: float,
    tri: float,
    sri: float,
    lec: float,
    scp: float,
) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "route_id": "fixture_route",
            "sample_id": sample_id,
            "distance_m": distance_m,
            "teii_20m": teii_20m,
            "tri": tri,
            "sri": sri,
            "lec": lec,
            "scp": scp,
            "pretrip_risk": 0,
        },
    }
