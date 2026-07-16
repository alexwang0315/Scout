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
    assert "nearest_cp_label=CP 001" in result["field_answer"]
    assert "distance_to_cp_m=" in result["field_answer"]
    assert "gpx_cumulative_km=2.0" in result["field_answer"]
    assert "lat=24.002" in result["field_answer"]
    assert "lon=121.002" in result["field_answer"]


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


def test_search_project_risk_scores_joins_high_risk_points_to_route_segments(
    tmp_path: Path,
) -> None:
    workspace = _write_risk_score_workspace(tmp_path)

    result = search_project_risk_scores(
        workspace,
        query="哪些 route segments 含有 extreme 或 very_high risk 點？",
        limit=6,
    )

    assert result["filters"]["risk_bucket"] == "very_high"
    assert result["result_count"] == 3
    assert {item["risk_bucket"] for item in result["results"]} == {
        "very_high",
        "extreme",
    }
    assert {
        item["candidate_route_segment"]["candidate_id"]
        for item in result["results"]
    } == {"seg.002", "seg.003"}
    assert result["segment_risk_summary"]["matched_segment_count"] == 2
    assert {
        item["candidate_id"]
        for item in result["segment_risk_summary"]["segments"]
    } == {"seg.002", "seg.003"}
    assert "seg.002" in result["field_answer"]
    assert "seg.003" in result["field_answer"]
    assert all(
        item["segment_join_method"] == "cumulative_route_distance_candidate"
        for item in result["results"]
    )
    assert all(item["candidate_only"] is True for item in result["results"])
    assert all(item["runtime_safety_truth"] is False for item in result["results"])
    assert "candidates/segments.json" in result["source_refs"]


def test_risk_score_joins_route_notes_to_calibrated_high_risk_points(
    tmp_path: Path,
) -> None:
    workspace = _write_risk_score_workspace(tmp_path)

    result = search_project_risk_scores(
        workspace,
        query="哪些 route note 靠近 calibrated high risk 區域？",
        limit=6,
    )

    assert "危險轉折" in result["field_answer"]
    assert "距高風險點" in result["field_answer"]
    assert "score=95.0" in result["field_answer"]
    assert "candidates/route_note_candidates.json" in result["source_refs"]
    assert result["field_answer_priority"] == 100


def test_risk_score_answers_cross_surface_bucket_max_and_delta_questions(
    tmp_path: Path,
) -> None:
    workspace = _write_risk_score_workspace(tmp_path)

    buckets = search_project_risk_scores(
        workspace,
        query="risk score 各 bucket 分別有多少個點？",
    )
    maxima = search_project_risk_scores(
        workspace,
        query="baseline 與 calibrated risk 的最大分數各是多少？",
    )
    delta = search_project_risk_scores(
        workspace,
        query="risk delta 最大的路線位置與差值是多少？",
    )

    assert buckets["surface"] == "all"
    assert "baseline：low=1、high=1、extreme=1" in buckets["field_answer"]
    assert "calibration：very_high=1、extreme=1" in buckets["field_answer"]
    assert "baseline max=85.0" in maxima["field_answer"]
    assert "calibrated max=95.0" in maxima["field_answer"]
    assert "delta=10.0" in delta["field_answer"]
    assert "2.0 km" in delta["field_answer"]
    assert buckets["field_answer_priority"] == 100


def test_risk_score_answers_attribution_exclusion_and_surface_count_questions(
    tmp_path: Path,
) -> None:
    workspace = _write_risk_score_workspace(tmp_path)

    attribution = search_project_risk_scores(
        workspace,
        query="risk attribution diagnostic 將最高風險歸因到哪些來源？",
    )
    excluded = search_project_risk_scores(
        workspace,
        query="excluded extreme warning CP proposals 為何被排除？",
    )
    counts = search_project_risk_scores(
        workspace,
        query="risk ribbon 與 calibrated heatmap 的資料點數是否一致？",
    )

    assert "tri、lec、teii_20m" in attribution["field_answer"]
    assert "(tri + 0.8*lec + 0.7*teii_20m) / 2.5" in attribution["field_answer"]
    assert "sri 未納入正式公式" in excluded["field_answer"]
    assert "2 筆 proposal" in excluded["field_answer"]
    assert "risk ribbon=2" in counts["field_answer"]
    assert "calibrated heatmap=2" in counts["field_answer"]
    assert "一致" in counts["field_answer"]
    assert attribution["field_answer_source_ref"] == (
        "outputs/risk/risk_attribution_diagnostic.json"
    )
    assert excluded["field_answer_source_ref"] == (
        "outputs/risk/excluded_extreme_warning_cp_proposals.json"
    )


def _write_risk_score_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "risk-workspace"
    (workspace / "candidates").mkdir(parents=True)
    (workspace / "outputs" / "risk").mkdir(parents=True)
    (workspace / "project.json").write_text(
        json.dumps(
            {
                "project_id": "risk_fixture",
                "checkpoint_candidates_ref": "candidates/checkpoints.json",
                "segment_candidates_ref": "candidates/segments.json",
                "route_note_candidates_ref": "candidates/route_note_candidates.json",
                "risk_score_points_ref": "outputs/risk/risk_score_points.geojson",
                "calibrated_risk_heatmap_ref": (
                    "outputs/risk/calibrated_risk_heatmap.geojson"
                ),
                "calibrated_risk_heatmap_metadata_ref": (
                    "outputs/risk/calibrated_risk_heatmap.metadata.json"
                ),
                "risk_ribbon_metadata_ref": "outputs/risk/risk_ribbon.metadata.json",
                "risk_attribution_diagnostic_ref": (
                    "outputs/risk/risk_attribution_diagnostic.json"
                ),
                "excluded_extreme_warning_cp_proposals_ref": (
                    "outputs/risk/excluded_extreme_warning_cp_proposals.json"
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
    (workspace / "candidates" / "segments.json").write_text(
        json.dumps(
            [
                {
                    "candidate_id": "seg.001",
                    "label": "Segment 001",
                    "from_candidate_id": "cp.start",
                    "to_candidate_id": "cp.001",
                    "distance_m": 750.0,
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                },
                {
                    "candidate_id": "seg.002",
                    "label": "Segment 002",
                    "from_candidate_id": "cp.001",
                    "to_candidate_id": "cp.002",
                    "distance_m": 750.0,
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                },
                {
                    "candidate_id": "seg.003",
                    "label": "Segment 003",
                    "from_candidate_id": "cp.002",
                    "to_candidate_id": "cp.003",
                    "distance_m": 750.0,
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (workspace / "candidates" / "route_note_candidates.json").write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "candidate_id": "route_note.fixture.001",
                        "name": "危險轉折",
                        "note_category": "hazard_hint",
                        "lat": 24.002,
                        "lon": 121.002,
                    },
                    {
                        "candidate_id": "route_note.fixture.002",
                        "name": "遠方地標",
                        "note_category": "landmark_hint",
                        "lat": 24.02,
                        "lon": 121.02,
                    },
                ]
            },
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
    (workspace / "outputs" / "risk" / "risk_ribbon.metadata.json").write_text(
        json.dumps({"segment_count": 2}),
        encoding="utf-8",
    )
    (
        workspace / "outputs" / "risk" / "calibrated_risk_heatmap.metadata.json"
    ).write_text(
        json.dumps({"segment_count": 2}),
        encoding="utf-8",
    )
    (
        workspace / "outputs" / "risk" / "risk_attribution_diagnostic.json"
    ).write_text(
        json.dumps(
            {
                "factor_analysis": {
                    "formula_candidate": {
                        "expression": "(tri + 0.8*lec + 0.7*teii_20m) / 2.5",
                        "selected_dimensions": ["tri", "lec", "teii_20m"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (
        workspace
        / "outputs"
        / "risk"
        / "excluded_extreme_warning_cp_proposals.json"
    ).write_text(
        json.dumps(
            {
                "counts": {"proposal_count": 2},
                "excluded_dimensions": ["sri"],
                "proposals": [
                    {
                        "reason_zh": (
                            "sri 未納入正式公式，但超過極端門檻，保留供人工複核。"
                        )
                    }
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
