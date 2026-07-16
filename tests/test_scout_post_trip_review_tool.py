from __future__ import annotations

import json
from pathlib import Path

import pytest

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
    assert result["decision_output"]["decisionObjectSchema"] == "ContextualPermission"
    assert result["decision_output"]["decision"] == "DELAY"
    assert result["decision_output"]["firstLayer"]["decision"] == "暫緩學習寫回。"
    assert result["decision_output"]["runtimeSafetyTruth"] is False
    assert "subjective_difficulty" in result["missing_fields"]
    assert "near_miss_incident_review" in result["missing_fields"]
    assert result["post_trip_review"]["role"] == (
        "Post-Trip Review / Learning Governance"
    )
    assert result["post_trip_learning_package"]["role"] == "Post-Trip Learning Proposal"
    assert result["post_trip_learning_package"]["data_to_collect"][
        "actual_cp_pass_times"
    ]["observed_edge_count"] == 73
    assert result["post_trip_learning_package"]["writeback_policy"][
        "automatic_user_model_update_allowed"
    ] is False
    assert result["completed_trip_summary"]["edge_count"] == 73
    assert result["completed_trip_summary"]["rest_interval_count"] == 62
    assert result["privacy_share_policy"]["raw_track_shared"] is False
    assert result["privacy_share_policy"]["exact_timestamps_shared"] is False
    assert "行後回顧" in result["field_answer"]
    assert result["boundary"]["learning_write_performed"] is False
    assert result["boundary"]["runtime_safety_truth"] is False


def test_post_trip_review_does_not_infer_delay_without_actual_event_evidence() -> None:
    result = assess_scout_post_trip_review(
        POST_ANALYSIS_ROOT,
        query=(
            "post-trip review 可以從目前 GPX、CP events 與 risk artifacts "
            "找出哪些延誤或偏離？"
        ),
    )

    assert "不能可靠判定實際延誤或偏離" in result["field_answer"]
    assert "subjective_difficulty" in result["field_answer"]
    assert result["field_answer_priority"] == 100


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
    assert result["decision_output"]["decision"] == "ESCALATE"
    assert result["decision_output"]["firstLayer"]["decision"] == (
        "先升級人工事故回顧。"
    )
    assert "行後回顧包含 incident events，必須人工事故回顧。" in result[
        "review_governance"
    ]["critical_gaps"]
    assert result["post_trip_review"]["learning_write_performed"] is False
    assert result["review_governance"]["incident_package_rewrite_performed"] is False
    assert "不會寫回使用者模型" in result["field_answer"]


def test_post_trip_review_classifies_standard_event_taxonomy() -> None:
    result = assess_scout_post_trip_review(
        POST_ANALYSIS_ROOT,
        query="行後有摸黑、差點迷路、滑倒、脫隊、失溫和裝備失效，下一次要怎麼改？",
        subjective_difficulty="比預期難",
        equipment_gaps=["頭燈電量不足"],
        near_miss_events=["摸黑前差點錯過岔路", "後隊脫隊十分鐘"],
        incident_events=["隊員滑倒擦傷", "濕冷後疑似失溫", "頭燈失效"],
        weather_matched_expectation=False,
        route_condition_notes=["午後低溫濕冷"],
        route_context_updates=["危險岔路需要標記"],
        user_feedback_items=["下次應提早折返"],
    )

    assert result["answerability"] == "post_trip_review_available"
    assert result["decision"] == "ESCALATE"
    taxonomy = result["post_trip_feedback"]["event_taxonomy"]
    assert taxonomy["candidate_only"] is True
    assert taxonomy["runtime_safety_truth"] is False
    assert set(taxonomy["matched_event_types"]) >= {
        "lost_or_navigation_uncertainty",
        "slip_or_fall",
        "cold_or_hypothermia",
        "team_separation",
        "darkness_or_daylight_overrun",
        "equipment_failure",
    }
    data = result["post_trip_learning_package"]["data_to_collect"]
    assert data["event_taxonomy"]["event_count"] >= 5
    coverage = result["post_trip_learning_package"]["model_update_target_coverage"]
    assert coverage["navigation_terrain_readiness_model"] is True
    assert coverage["terrain_risk_layer"] is True
    assert coverage["weather_cold_exposure_policy"] is True
    assert coverage["team_status_governance"] is True
    assert coverage["daylight_turnaround_policy"] is True
    assert coverage["equipment_resource_readiness"] is True
    update_kinds = {item["update_kind"] for item in result["model_update_candidates"]}
    assert {
        "navigation_terrain_readiness_model",
        "terrain_risk_layer",
        "weather_cold_exposure_policy",
        "team_status_governance",
        "daylight_turnaround_policy",
        "equipment_resource_readiness",
    } <= update_kinds
    assert any(
        "摸黑" in gap or "日照" in gap
        for gap in result["review_governance"]["warning_gaps"]
    )
    assert result["post_trip_review"]["learning_write_performed"] is False
    assert result["boundary"]["runtime_safety_truth"] is False


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
    assert result["decision_output"]["firstLayer"]["decision"] == "可送人工學習審核。"
    assert result["post_trip_learning_package"]["model_update_target_coverage"][
        "team_pace_fit_model"
    ] is True
    assert result["post_trip_learning_package"]["model_update_target_coverage"][
        "route_condition_risk_layer"
    ] is True
    assert "GO" in result["field_answer"]
    assert {
        item["update_kind"] for item in result["model_update_candidates"]
    } >= {"user_scout_pace_coefficient", "route_cp_elapsed_time"}


def test_post_trip_review_output_kind_constant() -> None:
    assert POST_TRIP_REVIEW_OUTPUT_KIND == "scout_ai_post_trip_review_tool_output"


@pytest.mark.parametrize(
    ("question", "subject"),
    (
        ("這次最早的風險訊號是什麼？", "最早風險訊號回顧"),
        ("Scout 哪個 warning 應該更早出現？", "warning 提前時點回顧"),
        ("哪個 CP 設錯或漏設了？", "CP 設定缺漏回顧"),
        ("哪段路的 GPX corridor 太寬或太窄？", "GPX corridor 寬度回顧"),
        ("是否有景觀點/拍照停留風險被忽略？", "景觀停留風險遺漏回顧"),
        ("這次是迷途、滑墜、資源不足還是隊伍治理問題？", "事件主因分類回顧"),
        ("哪些資料應該進 incident package？", "incident package 資料契約"),
        ("這個案例應該變成 field case 嗎？", "field case 升格審查"),
        ("哪些 spec 需要被更新？", "spec 更新候選審查"),
        ("下次行前規劃要改哪三件事？", "下次行前規劃三項回顧"),
    ),
)
def test_post_trip_review_provides_structured_query_guidance(
    question: str,
    subject: str,
) -> None:
    result = assess_scout_post_trip_review(POST_ANALYSIS_ROOT, query=question)

    guidance = result["query_guidance"]
    assert guidance["subject"] == subject
    assert guidance["facts"]
    assert guidance["required_fact_groups"]
    assert guidance["boundary"]
    assert guidance["forbidden_claims"]


def test_incident_package_guidance_names_scout_evidence_groups() -> None:
    result = assess_scout_post_trip_review(
        POST_ANALYSIS_ROOT,
        query="哪些資料應該進 incident package？",
    )

    facts = result["query_guidance"]["facts"]
    assert any("位置" in fact and "時間" in fact for fact in facts)
    assert any("軌跡" in fact and "CP" in fact for fact in facts)
    assert any("傷勢" in fact and "隊伍" in fact for fact in facts)
    assert any("天氣" in fact and "資源" in fact for fact in facts)
    assert result["decision"] == "DELAY"
    assert result["post_trip_feedback"]["incident_events"] == []
