from __future__ import annotations

import json
from pathlib import Path

from scout_post_trip_review_tool import (
    POST_TRIP_REVIEW_OUTPUT_KIND,
    POST_TRIP_REVIEW_TOOL_ID,
    assess_scout_post_trip_review,
)


ROOT = Path(__file__).resolve().parents[1]
POST_ANALYSIS_ROOT = (
    ROOT / "tests" / "fixtures" / "post_analysis" / "chilai_nanhua_day1_post_analysis"
)


def test_post_trip_review_reports_fixture_learning_gaps_without_writeback() -> None:
    result = assess_scout_post_trip_review(
        POST_ANALYSIS_ROOT,
        query="行後回顧要更新哪些下一次規劃？",
    )

    assert result["artifact_kind"] == POST_TRIP_REVIEW_OUTPUT_KIND
    assert result["tool_id"] == POST_TRIP_REVIEW_TOOL_ID
    assert result["answerability"] == "post_trip_review_missing_required_fields"
    assert result["decision"] == "DELAY"
    assert "subjective_difficulty" in result["missing_fields"]
    assert "near_miss_incident_review" in result["missing_fields"]
    assert result["post_trip_review"]["role"] == (
        "Post-Trip Review / Learning Governance"
    )
    assert result["completed_trip_summary"]["edge_count"] == 73
    assert result["completed_trip_summary"]["rest_interval_count"] == 62
    assert result["privacy_share_policy"]["raw_track_shared"] is False
    assert result["privacy_share_policy"]["exact_timestamps_shared"] is False
    assert "行後回顧" in result["field_answer"]
    assert result["boundary"]["learning_write_performed"] is False
    assert result["boundary"]["runtime_safety_truth"] is False


def test_post_trip_review_escalates_incident_feedback_without_mutation() -> None:
    result = assess_scout_post_trip_review(
        POST_ANALYSIS_ROOT,
        query="行後有 near miss 和滑倒事件，下一次要怎麼改？",
        subjective_difficulty="比預期難",
        equipment_gaps=["手套不足"],
        near_miss_events=["摸黑前差點錯過岔路"],
        incident_events=["隊員滑倒擦傷"],
        weather_matched_expectation=False,
        route_condition_notes=["午後霧氣比預報早"],
        route_context_updates=["雲海保線所有可靠集合空間"],
        user_feedback_items=["午餐點應前移"],
    )

    assert result["answerability"] == "post_trip_review_available"
    assert result["decision"] == "ESCALATE"
    assert "行後回顧包含 incident events，必須人工事故回顧。" in result[
        "review_governance"
    ]["critical_gaps"]
    assert result["post_trip_review"]["learning_write_performed"] is False
    assert result["review_governance"]["incident_package_rewrite_performed"] is False
    assert "不會寫回使用者模型" in result["field_answer"]


def test_post_trip_review_go_when_required_feedback_is_complete(tmp_path: Path) -> None:
    project_root = tmp_path / "post_trip_ready"
    outputs = project_root / "outputs"
    outputs.mkdir(parents=True)
    (project_root / "project.json").write_text(
        '{"project_id":"post_trip_ready"}',
        encoding="utf-8",
    )
    (outputs / "capability_timeline.json").write_text(
        json.dumps(
            {
                "case_id": "post_trip_ready",
                "route_family": "demo_route",
                "summary": {
                    "completion_status": "complete",
                    "planned_segment_count": 2,
                    "traversed_segment_count": 2,
                    "partial_segment_count": 0,
                    "unreached_segment_count": 0,
                    "moving_time_s": 3600,
                    "elapsed_time_s": 4200,
                    "rest_time_s": 600,
                },
                "data_quality": {
                    "gps_gap_count": 0,
                    "ambiguous_checkpoint_count": 0,
                    "route_deviation_count": 0,
                    "limitations": [],
                },
                "edges": [
                    {"edge_id": "cp.start_to_cp.001", "traversal_status": "traversed"},
                    {"edge_id": "cp.001_to_cp.finish", "traversal_status": "traversed"},
                ],
                "rest_intervals": [{"rest_id": "rest.001"}],
                "boundary": {"runtime_safety_truth": False},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (outputs / "capability_capsule.json").write_text(
        json.dumps(
            {
                "case_id": "post_trip_ready",
                "route_family": "demo_route",
                "moving_time_min": 60,
                "elapsed_time_min": 70,
                "rest_time_min": 10,
                "distance_km": 4.0,
                "moving_pace_min_per_km": 15.0,
                "confidence": "high",
                "raw_track_shared": False,
                "exact_timestamps_shared": False,
                "incident_details_shared": False,
                "limitations": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = assess_scout_post_trip_review(
        project_root,
        query="行後回顧資料都齊了嗎？",
        subjective_difficulty="符合預期",
        equipment_gaps=["none"],
        near_miss_events=["none"],
        weather_matched_expectation=True,
        route_condition_notes=["路況符合預期"],
        route_context_updates=["補充展望點說明"],
        user_feedback_items=["節奏可沿用"],
    )

    assert result["answerability"] == "post_trip_review_available"
    assert result["decision"] == "GO"
    assert result["missing_fields"] == []
    assert result["review_governance"]["critical_gaps"] == []
    assert result["review_governance"]["warning_gaps"] == []
    assert "GO" in result["field_answer"]
    assert {
        item["update_kind"] for item in result["model_update_candidates"]
    } >= {"user_scout_pace_coefficient", "route_cp_elapsed_time"}


def test_post_trip_review_output_kind_constant() -> None:
    assert POST_TRIP_REVIEW_OUTPUT_KIND == "scout_ai_post_trip_review_tool_output"
