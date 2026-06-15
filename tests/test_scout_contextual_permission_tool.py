import json
from pathlib import Path

from scout_contextual_permission_tool import (
    CONTEXTUAL_PERMISSION_OUTPUT_KIND,
    CONTEXTUAL_PERMISSION_TOOL_ID,
    assess_scout_contextual_permission,
)


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = (
    ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
)


def test_contextual_permission_allows_film_with_bounded_deadline_and_cost() -> None:
    result = assess_scout_contextual_permission(
        PROJECT_ROOT,
        query="我可以在這裡停下來拍一段影片嗎?",
        current_time="2026-06-07T13:36:00+08:00",
        current_cp_id="CP3",
        next_cp_id="CP4",
        remaining_safety_buffer_minutes=21,
        current_delay_minutes=9,
        next_segment_uncertainty_minutes=3,
        weather_reserve_minutes=2,
        communication_status="ok",
        equipment_status="ok",
    )

    assert result["tool_id"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result["status"] == "completed"
    assert result["answerability"] == "contextual_permission_decision_available"
    assert result["decision"] == "CONDITIONAL_GO"
    assert result["allowed"] is True
    assert result["action"] == "film"
    assert result["max_duration_minutes"] == 6
    assert result["leave_by"] == "2026-06-07T13:42:00+08:00"
    assert "最多 6 分鐘" in result["field_answer"]
    assert "13:42" in result["field_answer"]

    permission = result["contextual_permission"]
    assert permission["decision"] == "CONDITIONAL_GO"
    assert permission["allowed"] is True
    assert permission["maxDurationMinutes"] == 6
    assert permission["leaveBy"] == "2026-06-07T13:42:00+08:00"
    assert permission["cost"]["timeBufferChangeMinutes"] == -6
    assert permission["nextAction"]
    assert permission["requiredConditions"]

    budget = result["risk_budget"]
    assert budget["remainingSafetyBufferMinutes"] == 21.0
    assert budget["authorizedDurationMinutes"] == 16
    assert budget["bufferAfterActionMinutes"] == 15
    assert result["risk_budget_source"]["source_status"] == (
        "caller_provided_normalized_evidence"
    )
    assert result["risk_budget_source"]["workspace_reserve_source"][
        "source_status"
    ] == "not_applied"
    assert result["boundary"]["runtime_safety_truth"] is False
    assert result["boundary"]["safety_api_called"] is False


def test_contextual_permission_missing_buffer_is_conservative_no_go() -> None:
    result = assess_scout_contextual_permission(
        PROJECT_ROOT,
        query="我可以在這裡停下來拍一段影片嗎?",
    )

    assert result["answerability"] == "contextual_permission_missing_required_fields"
    assert result["decision"] == "NO_GO"
    assert result["allowed"] is False
    assert result["missing_fields"] == ["remaining_safety_buffer_minutes"]
    assert "不建議拍影片" in result["field_answer"]
    assert "資料不足" in result["contextual_permission"]["uncertaintyNotes"][1]
    assert result["contextual_permission"]["alternativeActions"]


def test_contextual_permission_derives_candidate_buffer_from_planned_eta() -> None:
    result = assess_scout_contextual_permission(
        PROJECT_ROOT,
        query="我可以在這裡停下來拍一段影片嗎?",
        current_time="2013-10-08T14:52:50+08:00",
        next_cp_id="雲海保線所",
        communication_status="ok",
        equipment_status="ok",
    )

    assert result["answerability"] == "contextual_permission_decision_available"
    assert result["decision"] == "NO_GO"
    assert result["allowed"] is False
    assert result["missing_fields"] == []
    assert result["max_duration_minutes"] is None
    assert result["leave_by"] is None
    assert "不建議拍影片" in result["field_answer"]

    budget = result["risk_budget"]
    assert budget["remainingSafetyBufferMinutes"] == 6.0
    assert budget["authorizedDurationMinutes"] == 0
    assert budget["nextSegmentUncertaintyMinutes"] == 10.0
    assert budget["weatherReserveMinutes"] == 15.0
    assert budget["daylightReserveMinutes"] == 60.0
    assert "bufferAfterActionMinutes" not in budget

    source = result["risk_budget_source"]
    assert source["source_status"] == "derived_from_planned_eta_candidate"
    assert source["source_path"] == "outputs/planned_eta.json"
    assert source["next_cp_id"] == "雲海保線所"
    assert source["planned_eta"] == "2013-10-08T14:58:50+08:00"
    assert source["minutes_until_planned_eta"] == 6
    assert source["runtime_safety_truth"] is False
    assert {
        item["reserve_field"]
        for item in source["reserve_sources"]
    } >= {
        "next_segment_uncertainty_minutes",
        "weather_reserve_minutes",
        "daylight_reserve_minutes",
    }
    assert any("candidate planned ETA" in warning for warning in result["warnings"])
    assert any("reserve was deducted" in warning for warning in result["warnings"])


def test_contextual_permission_allows_eta_buffer_when_weather_and_validation_reviewed(
    tmp_path: Path,
) -> None:
    project_root = _write_reviewed_eta_project(tmp_path)

    result = assess_scout_contextual_permission(
        project_root,
        query="我可以在這裡停下來拍一段影片嗎?",
        current_time="2026-06-07T13:36:00+08:00",
        next_cp_id="CP4",
        communication_status="ok",
        equipment_status="ok",
    )

    assert result["decision"] == "CONDITIONAL_GO"
    assert result["allowed"] is True
    assert result["max_duration_minutes"] == 6
    assert result["leave_by"] == "2026-06-07T13:42:00+08:00"
    assert "最多 6 分鐘" in result["field_answer"]

    budget = result["risk_budget"]
    assert budget["remainingSafetyBufferMinutes"] == 6.0
    assert budget["authorizedDurationMinutes"] == 6
    assert budget["bufferAfterActionMinutes"] == 0
    assert budget["weatherReserveMinutes"] == 0.0
    assert budget["daylightReserveMinutes"] == 0.0
    assert budget["nextSegmentUncertaintyMinutes"] == 0.0

    source = result["risk_budget_source"]
    assert source["source_status"] == "derived_from_planned_eta_candidate"
    assert source["reserve_sources"] == []
    assert source["workspace_reserve_source"]["source_status"] == (
        "workspace_reserves_not_needed_reviewed_evidence"
    )
    assert not any("reserve was deducted" in warning for warning in result["warnings"])


def test_contextual_permission_escalates_high_risk_stream_crossing() -> None:
    result = assess_scout_contextual_permission(
        PROJECT_ROOT,
        query="這裡溪水暴漲，可以過溪嗎?",
        action="cross_stream",
        remaining_safety_buffer_minutes=50,
        terrain_risk_level="critical",
        communication_status="weak",
        equipment_status="unknown",
    )

    assert result["decision"] == "ESCALATE"
    assert result["allowed"] is False
    assert result["action"] == "cross_stream"
    assert "需要升級處理" in result["field_answer"]
    assert "不要渡溪" in result["contextual_permission"]["alternativeActions"]


def test_contextual_permission_output_kind_constant() -> None:
    assert CONTEXTUAL_PERMISSION_OUTPUT_KIND == (
        "scout_ai_contextual_permission_tool_output"
    )


def _write_reviewed_eta_project(tmp_path: Path) -> Path:
    project_root = tmp_path / "reviewed_eta_project"
    outputs = project_root / "outputs"
    outputs.mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "project_id": "reviewed_eta_project",
                "planned_eta_ref": "outputs/planned_eta.json",
                "weather_daylight_evidence_ref": "outputs/weather_daylight_evidence.json",
                "plan_validation_candidates_ref": "outputs/plan_validation_candidates.json",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (outputs / "planned_eta.json").write_text(
        json.dumps(
            {
                "plan_id": "eta_plan.reviewed.v0",
                "project_id": "reviewed_eta_project",
                "estimates": [
                    {
                        "estimate_id": "eta.cp4",
                        "to_node_name": "CP4",
                        "eta": "2026-06-07T13:42:00+08:00",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (outputs / "weather_daylight_evidence.json").write_text(
        json.dumps(
            {
                "status": "reviewed",
                "human_review_required": False,
                "authoritative_weather_computed": True,
                "validation": {"validation_status": "reviewed"},
                "daylight": {"source_status": "reviewed"},
                "weather_window": {"source_status": "reviewed"},
                "threshold_policy": {
                    "daylight": {"dark_arrival_warning_margin_min": 60}
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (outputs / "plan_validation_candidates.json").write_text(
        json.dumps(
            {
                "status": "reviewed",
                "findings": [],
                "hard_readiness_mutation_allowed": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return project_root
