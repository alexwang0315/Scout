import json
from pathlib import Path

from pretrip_risk_heatmap import (
    build_calibrated_risk_heatmap,
    heat_bucket,
    heat_thresholds,
    update_workspace_project_refs,
)


def test_builds_calibrated_heatmap_from_workspace_diagnostic_shape(tmp_path: Path) -> None:
    route_risk = tmp_path / "route_risk.geojson"
    diagnostic = tmp_path / "risk_attribution_diagnostic.json"
    warnings = tmp_path / "excluded_extreme_warning_cp_proposals.json"
    route_risk.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "metadata": {
                    "route_base": {
                        "route_base": "overpass_vector_evidence",
                        "sampling_strategy": (
                            "reference_progress_projected_to_nearest_overpass_segment.v1"
                        ),
                        "corridor_m": 500.0,
                        "projected_reference_sample_count": 4,
                        "fallback_reference_sample_count": 1,
                        "route_point_count": 5,
                    }
                },
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


def test_calibrated_heatmap_skips_fallback_and_large_route_base_jumps(
    tmp_path: Path,
) -> None:
    route_risk = tmp_path / "route_risk.geojson"
    diagnostic = tmp_path / "risk_attribution_diagnostic.json"
    warnings = tmp_path / "excluded_extreme_warning_cp_proposals.json"
    route_risk.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "metadata": {
                    "route_base": {
                        "route_base": "overpass_vector_evidence",
                        "sampling_strategy": (
                            "reference_progress_projected_to_nearest_overpass_segment.v1"
                        ),
                        "corridor_m": 500.0,
                        "projected_reference_sample_count": 4,
                        "fallback_reference_sample_count": 1,
                        "route_point_count": 5,
                    }
                },
                "features": [
                    _route_risk_feature(
                        "sample.001",
                        24.0,
                        121.0,
                        0,
                        20,
                        10,
                        0,
                        30,
                        0,
                        route_base_source="overpass_projection",
                    ),
                    _route_risk_feature(
                        "sample.002",
                        24.0001,
                        121.0001,
                        20,
                        90,
                        95,
                        20,
                        92,
                        0,
                        route_base_source="overpass_projection",
                    ),
                    _route_risk_feature(
                        "sample.003",
                        24.0002,
                        121.0002,
                        40,
                        60,
                        50,
                        80,
                        65,
                        0,
                        route_base_source="reference_gpx_gap_fallback",
                    ),
                    _route_risk_feature(
                        "sample.004",
                        24.01,
                        121.01,
                        60,
                        60,
                        50,
                        80,
                        65,
                        0,
                        route_base_source="overpass_projection",
                    ),
                    _route_risk_feature(
                        "sample.005",
                        24.02,
                        121.02,
                        80,
                        60,
                        50,
                        80,
                        65,
                        0,
                        route_base_source="overpass_projection",
                    ),
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
                        "expression": "tri",
                        "selected_dimensions": ["tri"],
                        "terms": [{"dimension": "tri", "normalized_weight": 1.0}],
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    warnings.write_text(json.dumps({"proposals": []}), encoding="utf-8")

    heatmap = build_calibrated_risk_heatmap(
        route_risk_path=route_risk,
        risk_attribution_diagnostic_path=diagnostic,
        warning_cp_proposals_path=warnings,
    )

    assert heatmap["metadata"]["segment_count"] == 1
    assert heatmap["metadata"]["skipped_pair_count"] == 3
    assert heatmap["metadata"]["route_base"]["sampling_strategy"] == (
        "reference_progress_projected_to_nearest_overpass_segment.v1"
    )
    assert heatmap["metadata"]["route_base"]["fallback_reference_sample_count"] == 1
    assert heatmap["features"][0]["properties"]["from_sample_id"] == "sample.001"
    assert heatmap["features"][0]["properties"]["to_sample_id"] == "sample.002"


def test_workspace_refs_do_not_require_preview_png(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "project.json").write_text(
        json.dumps(
            {
                "project_id": "fixture",
                "calibrated_risk_heatmap_preview_ref": "outputs/risk/stale.png",
            }
        ),
        encoding="utf-8",
    )
    heatmap_path = workspace / "outputs/risk/calibrated_risk_heatmap.geojson"
    metadata_path = workspace / "outputs/risk/calibrated_risk_heatmap.metadata.json"
    heatmap_path.parent.mkdir(parents=True)
    heatmap_path.write_text("{}", encoding="utf-8")
    metadata_path.write_text("{}", encoding="utf-8")

    update_workspace_project_refs(
        workspace=workspace,
        heatmap_path=heatmap_path,
        metadata_path=metadata_path,
        preview_path=None,
        heatmap={
            "metadata": {
                "segment_count": 2,
                "warning_cp_overlay_count": 1,
            }
        },
    )

    project = json.loads((workspace / "project.json").read_text(encoding="utf-8"))
    assert project["calibrated_risk_heatmap_ref"] == (
        "outputs/risk/calibrated_risk_heatmap.geojson"
    )
    assert project["calibrated_risk_heatmap_metadata_ref"] == (
        "outputs/risk/calibrated_risk_heatmap.metadata.json"
    )
    assert "calibrated_risk_heatmap_preview_ref" not in project
    assert project["calibrated_risk_heatmap_segment_count"] == 2
    assert project["calibrated_risk_heatmap_warning_cp_overlay_count"] == 1


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
    route_base_source: str | None = None,
) -> dict:
    route_base_properties = {}
    if route_base_source is not None:
        route_base_properties["route_base_source"] = route_base_source
        route_base_properties["route_base_feature_id"] = "osm.way.fixture"
        route_base_properties["route_base_projection_distance_m"] = 0.0
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
            **route_base_properties,
        },
    }
