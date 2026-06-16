from __future__ import annotations

from pathlib import Path

from scout_equipment_resource_tool import (
    EQUIPMENT_RESOURCE_OUTPUT_KIND,
    EQUIPMENT_RESOURCE_TOOL_ID,
    assess_scout_equipment_resource,
)


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"


def test_equipment_resource_uses_reviewed_fixture_resource_fields_with_warnings() -> None:
    result = assess_scout_equipment_resource(
        PROJECT_ROOT,
        query="手機電量和頭燈水量夠嗎？",
    )

    assert result["artifact_kind"] == EQUIPMENT_RESOURCE_OUTPUT_KIND
    assert result["tool_id"] == EQUIPMENT_RESOURCE_TOOL_ID
    assert result["answerability"] == "equipment_resource_decision_available"
    assert result["decision"] == "CONDITIONAL_GO"
    assert result["decision_output"]["decisionObjectSchema"] == "ContextualPermission"
    assert result["decision_output"]["decision"] == "CONDITIONAL_GO"
    assert result["decision_output"]["firstLayer"]["decision"] == (
        "可有條件進入下一步規劃。"
    )
    assert result["decision_output"]["runtimeSafetyTruth"] is False
    assert result["missing_fields"] == []
    assert result["equipment_resource"]["role"] == "Equipment / Resource Intelligence"
    assert result["resource_state"]["phone_battery_percent"] == 95.0
    assert result["resource_state"]["offline_map_ready"] is True
    assert result["resource_state"]["gpx_loaded"] is True
    assert result["resource_state"]["headlamp_ready"] is True
    assert result["resource_state"]["water_liters"] == 2.0
    assert result["resource_state"]["food_hours"] == 8.0
    assert result["debug_sources"]["equipment_status_source"] == (
        "outputs/equipment_status.json"
    )
    assert result["resource_readiness"]["warning_gaps"]
    assert "裝備資源判斷" in result["field_answer"]
    assert result["boundary"]["runtime_safety_truth"] is False
    assert result["boundary"]["outbound_send_performed"] is False


def test_equipment_resource_no_go_for_low_battery_and_missing_offline_map() -> None:
    result = assess_scout_equipment_resource(
        PROJECT_ROOT,
        query="手機只剩 5%，沒有離線地圖可以出發嗎？",
        phone_battery_percent=5,
        power_bank_percent=0,
        offline_map_ready=False,
        gpx_loaded=False,
        headlamp_ready=True,
        water_liters=1.0,
        food_hours=3.0,
    )

    assert result["answerability"] == "equipment_resource_decision_available"
    assert result["decision"] == "NO_GO"
    assert result["decision_output"]["decision"] == "NO_GO"
    assert result["decision_output"]["firstLayer"]["decision"] == (
        "不建議照原計畫出發或推進。"
    )
    assert "不得照原計畫" in result["decision_output"]["firstLayer"]["limit"]
    assert "手機電量過低且沒有可靠行動電源。" in result["resource_readiness"][
        "critical_gaps"
    ]
    assert "離線地圖未就緒。" in result["resource_readiness"]["critical_gaps"]
    assert "GPX/路線檔未載入。" in result["resource_readiness"]["critical_gaps"]
    assert "NO_GO" in result["field_answer"]
    assert result["equipment_resource"]["runtime_safety_truth"] is False


def test_equipment_resource_no_go_for_missing_offline_map_even_with_fixture_resources() -> None:
    result = assess_scout_equipment_resource(
        PROJECT_ROOT,
        query="我沒下載離線地圖，可以自主出發嗎？",
        offline_map_ready=False,
    )

    assert result["answerability"] == "equipment_resource_decision_available"
    assert result["decision"] == "NO_GO"
    assert result["decision_output"]["decision"] == "NO_GO"
    assert result["decision_output"]["allowed"] is False
    assert result["decision_output"]["firstLayer"]["decision"] == (
        "不建議照原計畫出發或推進。"
    )
    assert "離線地圖未就緒。" in result["resource_readiness"]["critical_gaps"]
    assert result["missing_fields"] == []
    assert result["decision_output"]["runtimeSafetyTruth"] is False


def test_equipment_resource_no_go_when_phone_dead_even_if_watch_has_battery() -> None:
    result = assess_scout_equipment_resource(
        PROJECT_ROOT,
        query="如果手機沒電但手錶還有電，可以繼續嗎？",
        phone_battery_percent=0,
        watch_battery_percent=80,
        power_bank_percent=100,
        offline_map_ready=True,
        gpx_loaded=True,
        headlamp_ready=True,
        water_liters=1.5,
        food_hours=4.0,
    )

    assert result["answerability"] == "equipment_resource_decision_available"
    assert result["decision"] == "NO_GO"
    assert result["decision_output"]["decision"] == "NO_GO"
    assert result["decision_output"]["allowed"] is False
    assert result["resource_state"]["phone_battery_percent"] == 0.0
    assert result["resource_state"]["watch_battery_percent"] == 80.0
    assert any(
        "手錶有電不能單獨取代" in gap
        for gap in result["resource_readiness"]["critical_gaps"]
    )
    assert "主要手機已無可用電量" in result["field_answer"]
    assert result["equipment_resource"]["runtime_safety_truth"] is False


def test_equipment_resource_go_when_direct_required_resources_are_ready(tmp_path: Path) -> None:
    project_root = tmp_path / "equipment_ready_project"
    project_root.mkdir()
    (project_root / "project.json").write_text(
        '{"project_id":"equipment_ready_project"}',
        encoding="utf-8",
    )

    result = assess_scout_equipment_resource(
        project_root,
        query="裝備都齊了嗎？",
        phone_battery_percent=80,
        offline_map_ready=True,
        gpx_loaded=True,
        headlamp_ready=True,
        water_liters=2.0,
        food_hours=6.0,
    )

    assert result["answerability"] == "equipment_resource_decision_available"
    assert result["decision"] == "GO"
    assert result["decision_output"]["firstLayer"]["decision"] == (
        "裝備資源可進入下一步。"
    )
    assert result["missing_fields"] == []
    assert result["resource_readiness"]["critical_gaps"] == []
    assert result["resource_readiness"]["warning_gaps"] == []
    assert "GO" in result["field_answer"]
    assert result["debug_sources"]["resource_plan_source"] is None


def test_equipment_resource_output_kind_constant() -> None:
    assert EQUIPMENT_RESOURCE_OUTPUT_KIND == "scout_ai_equipment_resource_tool_output"
