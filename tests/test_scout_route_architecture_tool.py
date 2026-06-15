from __future__ import annotations

from pathlib import Path

from scout_route_architecture_tool import (
    ROUTE_ARCHITECTURE_OUTPUT_KIND,
    ROUTE_ARCHITECTURE_TOOL_ID,
    assess_scout_route_architecture,
)


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"


def test_route_architecture_builds_candidate_cp_graph_and_decision() -> None:
    result = assess_scout_route_architecture(
        PROJECT_ROOT,
        query="下一個撤退點在哪？這條路線難點在哪？",
        limit=4,
    )

    assert result["artifact_kind"] == ROUTE_ARCHITECTURE_OUTPUT_KIND
    assert result["tool_id"] == ROUTE_ARCHITECTURE_TOOL_ID
    assert result["status"] == "completed"
    assert result["answerability"] == "route_architecture_available"
    assert result["source_status"] == "candidate_only"
    assert result["decision"] == "CONDITIONAL_GO"
    assert result["decision_output"]["decisionObjectSchema"] == "ContextualPermission"
    assert result["decision_output"]["decision"] == "CONDITIONAL_GO"
    assert result["decision_output"]["firstLayer"]["decision"] == (
        "可依 CP Graph 推進，但必須保留折返窗口。"
    )
    assert "不得在難點群前消耗 buffer" in result["decision_output"]["firstLayer"]["limit"]
    assert result["decision_output"]["runtimeSafetyTruth"] is False
    assert result["missing_fields"] == []
    assert result["cp_graph"]["node_count"] == 124
    assert result["cp_graph"]["edge_count"] == 123
    assert result["route_architecture"]["role"] == "Route Architecture Intelligence"
    assert result["route_architecture"]["turn_back"]["turn_back_checkpoint_name"] == (
        "雲海保線所"
    )
    assert result["route_architecture"]["retreat_option_count"] == 1
    assert result["route_architecture"]["hard_points"]
    assert result["route_decision"]["runtime_safety_truth"] is False
    assert "路線結構判斷" in result["field_answer"]
    assert "CP Graph" in result["field_answer"]
    assert "雲海保線所" in result["field_answer"]
    assert "候選撤退路線" in result["field_answer"]
    assert "seg.050" in result["field_answer"]
    assert "中段難點" in result["field_answer"]
    assert "後段/回程難點" in result["field_answer"]
    assert result["boundary"]["runtime_safety_truth"] is False
    assert result["boundary"]["safety_api_called"] is False
    assert result["boundary"]["outbound_send_performed"] is False


def test_route_architecture_changes_plan_after_turn_back_eta() -> None:
    result = assess_scout_route_architecture(
        PROJECT_ROOT,
        query="現在是不是折返點？",
        current_time="2013-10-08T15:05:00+08:00",
        limit=2,
    )

    assert result["answerability"] == "route_architecture_available"
    assert result["decision"] == "CHANGE_PLAN"
    assert result["decision_output"]["firstLayer"]["decision"] == (
        "不建議照原路線往後段推進。"
    )
    assert result["route_decision"]["turn_back_checkpoint"][
        "turn_back_checkpoint_name"
    ] == "雲海保線所"
    assert "turn-back ETA" in result["route_decision"]["main_reasons"][0]
    assert "CHANGE_PLAN" in result["field_answer"]
    assert result["boundary"]["runtime_safety_truth"] is False


def test_route_architecture_changes_plan_after_missed_checkpoint_deadline() -> None:
    result = assess_scout_route_architecture(
        PROJECT_ROOT,
        query="11:30 未抵達 CP4 是否要折返？",
        current_time="11:30",
        target_cp_id="CP4",
        limit=2,
    )

    assert result["answerability"] == "route_architecture_available"
    assert result["decision"] == "CHANGE_PLAN"
    assert result["decision_output"]["firstLayer"]["decision"] == (
        "不建議錯過 checkpoint deadline 後繼續原計畫。"
    )
    assert result["route_decision"]["target_checkpoint"] == "CP4"
    assert result["route_decision"]["checkpoint_deadline"] == "11:30"
    assert "target checkpoint CP4" in result["route_decision"]["main_reasons"][0]
    assert result["boundary"]["runtime_safety_truth"] is False


def test_route_architecture_changes_plan_for_hut_checkin_pressure() -> None:
    result = assess_scout_route_architecture(
        PROJECT_ROOT,
        query="山屋報到時間快到了，是否需要改計畫？",
        limit=2,
    )

    assert result["answerability"] == "route_architecture_available"
    assert result["decision"] == "CHANGE_PLAN"
    assert result["decision_output"]["firstLayer"]["decision"] == (
        "建議改變計畫，先處理外部 deadline 壓力。"
    )
    assert result["route_decision"]["deadline_pressure"] == "hut_checkin"
    assert "hut check-in" in result["route_decision"]["main_reasons"][0]
    assert "external deadline pressure" in result["field_answer"]
    assert result["boundary"]["runtime_safety_truth"] is False


def test_route_architecture_changes_plan_for_transport_deadline_pressure() -> None:
    result = assess_scout_route_architecture(
        PROJECT_ROOT,
        query="交通末班車快趕不上了，還能照原計畫嗎？",
        limit=2,
    )

    assert result["answerability"] == "route_architecture_available"
    assert result["decision"] == "CHANGE_PLAN"
    assert result["route_decision"]["deadline_pressure"] == "transport_last_service"
    assert "transport last service" in result["route_decision"]["main_reasons"][0]
    assert result["boundary"]["runtime_safety_truth"] is False


def test_route_architecture_output_kind_constant() -> None:
    assert ROUTE_ARCHITECTURE_OUTPUT_KIND == "scout_ai_route_architecture_tool_output"
