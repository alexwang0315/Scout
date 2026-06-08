import json
from pathlib import Path

from scout_risk_score_tool import RISK_SCORE_TOOL_ID, search_project_risk_scores


def test_search_project_risk_scores_returns_baseline_and_calibration_with_delta(
    tmp_path: Path,
) -> None:
    workspace = _write_risk_score_workspace(tmp_path)

    result = search_project_risk_scores(
        workspace,
        query="baseline and calibration highest risk score",
        limit=4,
    )

    assert result["tool_id"] == RISK_SCORE_TOOL_ID
    assert result["status"] == "completed"
    assert result["boundary"]["runtime_safety_truth"] is False
    assert result["summaries"]["baseline"]["available"] is True
    assert result["summaries"]["calibration"]["available"] is True
    assert result["results"][0]["surface"] == "calibration"
    assert result["results"][0]["score"] == 95.0
    assert result["results"][0]["paired_baseline_score"] == 85.0
    assert result["results"][0]["calibration_delta"] == 10.0


def test_search_project_risk_scores_filters_by_cp_anchor(tmp_path: Path) -> None:
    workspace = _write_risk_score_workspace(tmp_path)

    result = search_project_risk_scores(
        workspace,
        query="CP001 風險分數",
        limit=6,
    )

    assert result["filters"]["cp"] == "cp.001"
    assert result["matched_score_count"] >= 2
    assert all(item["anchor_distance_m"] <= 350 for item in result["results"])
    assert {item["surface"] for item in result["results"]} == {
        "baseline",
        "calibration",
    }


def test_search_project_risk_scores_filters_calibration_by_km(tmp_path: Path) -> None:
    workspace = _write_risk_score_workspace(tmp_path)

    result = search_project_risk_scores(
        workspace,
        query="1 km 校準 risk score",
        limit=3,
    )

    assert result["surface"] == "calibration"
    assert result["result_count"] == 1
    assert result["results"][0]["surface"] == "calibration"
    assert result["results"][0]["distance_km"] == 1.0
    assert result["results"][0]["score"] == 82.0


def _write_risk_score_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "risk-workspace"
    (workspace / "candidates").mkdir(parents=True)
    (workspace / "outputs" / "risk").mkdir(parents=True)
    (workspace / "project.json").write_text(
        json.dumps(
            {
                "project_id": "risk_fixture",
                "checkpoint_candidates_ref": "candidates/checkpoints.json",
                "risk_score_points_ref": "outputs/risk/risk_score_points.geojson",
                "calibrated_risk_heatmap_ref": (
                    "outputs/risk/calibrated_risk_heatmap.geojson"
                ),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (workspace / "candidates" / "checkpoints.json").write_text(
        json.dumps(
            [
                {
                    "candidate_id": "cp.001",
                    "label": "CP 001",
                    "lat": 24.001,
                    "lon": 121.001,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (workspace / "outputs" / "risk" / "risk_score_points.geojson").write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "metadata": {"artifact_kind": "scout_risk_score_point_map"},
                "features": [
                    _point("sample.000", 24.0, 121.0, 0.0, 35.0, "low"),
                    _point("sample.001", 24.001, 121.001, 1000.0, 75.0, "high"),
                    _point("sample.002", 24.002, 121.002, 2000.0, 85.0, "extreme"),
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (workspace / "outputs" / "risk" / "calibrated_risk_heatmap.geojson").write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "metadata": {"artifact_kind": "pretrip_calibrated_risk_heatmap"},
                "features": [
                    _segment(
                        "heat.001",
                        24.00095,
                        121.00095,
                        24.00105,
                        121.00105,
                        950.0,
                        1050.0,
                        82.0,
                        "very_high",
                    ),
                    _segment(
                        "heat.002",
                        24.00195,
                        121.00195,
                        24.00205,
                        121.00205,
                        1950.0,
                        2050.0,
                        95.0,
                        "extreme",
                    ),
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return workspace


def _point(
    sample_id: str,
    lat: float,
    lon: float,
    distance_m: float,
    score: float,
    bucket: str,
) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "sample_id": sample_id,
            "route_id": "fixture_route",
            "distance_m": distance_m,
            "rs": score,
            "score_field": "pretrip_risk",
            "risk_bucket": bucket,
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
    }


def _segment(
    segment_id: str,
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    start_distance_m: float,
    end_distance_m: float,
    score: float,
    bucket: str,
) -> dict:
    return {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": [[start_lon, start_lat], [end_lon, end_lat]],
        },
        "properties": {
            "segment_id": segment_id,
            "route_id": "fixture_route",
            "start_distance_m": start_distance_m,
            "end_distance_m": end_distance_m,
            "rs": score,
            "calibrated_risk_candidate": score,
            "score_field": "calibrated_risk_candidate",
            "risk_bucket": bucket,
            "relative_bucket": bucket,
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
    }
