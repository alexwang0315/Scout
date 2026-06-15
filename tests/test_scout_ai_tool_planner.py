from __future__ import annotations

from pathlib import Path

from assistant_models import AssistantSurface, ScoutAssistantQuery
from scout_ai_tool_planner import (
    CONTEXTUAL_PERMISSION_TOOL_ID,
    ENERGY_VITALS_TOOL_ID,
    INS_DR_TRACE_TOOL_ID,
    LIVE_NAVIGATION_STATE_TOOL_ID,
    ROUTE_CONTEXT_TOOL_ID,
    PACE_GUARDIAN_TOOL_ID,
    SAFETY_BOUNDARY_TOOL_ID,
    WEATHER_WINDOW_TOOL_ID,
    ScoutAiToolPlanItemStatus,
    plan_scout_ai_tools,
)
from scout_map_perception_tool import MAP_PERCEPTION_TOOL_ID
from scout_risk_score_tool import RISK_SCORE_TOOL_ID
from scout_terrain_score_tool import TERRAIN_SCORE_TOOL_ID
from scout_workspace_search_tools import MAJOR_POINT_TOOL_ID, ROUTE_STRUCTURE_TOOL_ID


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"


def test_planner_selects_route_structure_for_cp_count_question() -> None:
    plan = plan_scout_ai_tools(
        _query("有多少個 CP?"),
        project_root=PROJECT_ROOT,
    )

    item = _single_tool(plan, ROUTE_STRUCTURE_TOOL_ID)
    assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert item.implementation_status == "ready_current_tool"
    assert item.missing_fields == []
    assert item.required_fields
    assert item.request is not None
    assert item.request["tool_id"] == ROUTE_STRUCTURE_TOOL_ID
    assert plan.boundary.runtime_safety_truth is False


def test_planner_selects_major_points_for_named_place_cp_question() -> None:
    plan = plan_scout_ai_tools(
        _query("黑水塘在第幾 CP 附近?"),
        project_root=PROJECT_ROOT,
    )

    item = _single_tool(plan, MAJOR_POINT_TOOL_ID)
    assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert item.implementation_status == "ready_current_tool"
    assert "MCP" in item.reason or "named place" in item.reason
    assert ROUTE_STRUCTURE_TOOL_ID not in _tool_ids(plan)


def test_planner_prioritizes_map_perception_for_annotation_questions() -> None:
    plan = plan_scout_ai_tools(
        _query("CP001 附近有沒有標註?"),
        project_root=PROJECT_ROOT,
    )

    item = _single_tool(plan, MAP_PERCEPTION_TOOL_ID)
    assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert item.implementation_status == "ready_current_tool"
    assert MAJOR_POINT_TOOL_ID not in _tool_ids(plan)


def test_planner_selects_risk_and_terrain_for_dangerous_terrain_question() -> None:
    plan = plan_scout_ai_tools(
        _query("危險地形在哪些位置?"),
        project_root=PROJECT_ROOT,
    )

    tool_ids = _tool_ids(plan)
    assert RISK_SCORE_TOOL_ID in tool_ids
    assert TERRAIN_SCORE_TOOL_ID in tool_ids
    for tool_id in (RISK_SCORE_TOOL_ID, TERRAIN_SCORE_TOOL_ID):
        item = _single_tool(plan, tool_id)
        assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
        assert item.missing_fields == []
        assert item.request is not None
        assert item.request["query"] == "危險地形在哪些位置?"


def test_planner_selects_weather_ready_tool_for_weather_questions() -> None:
    plan = plan_scout_ai_tools(
        _query("明天午後雷雨是否要紮營?"),
        project_root=PROJECT_ROOT,
    )

    item = _single_tool(plan, WEATHER_WINDOW_TOOL_ID)
    assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert item.implementation_status == "ready_current_tool"
    assert item.request is not None
    assert item.request["tool_id"] == WEATHER_WINDOW_TOOL_ID
    assert item.required_fields == ["project_root"]
    assert item.missing_fields == []
    assert item.boundary.live_safety_api_calls_allowed is False


def test_planner_selects_contextual_permission_for_micro_decision() -> None:
    plan = plan_scout_ai_tools(
        _query("我可以在這裡停下來拍一段影片嗎?"),
        project_root=PROJECT_ROOT,
    )

    item = _single_tool(plan, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert item.implementation_status == "ready_current_tool"
    assert item.request is not None
    assert item.request["tool_id"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert item.required_fields == ["project_root"]
    assert item.missing_fields == []
    assert item.boundary.runtime_safety_truth is False
    assert WEATHER_WINDOW_TOOL_ID not in _tool_ids(plan)


def test_planner_selects_route_context_for_experience_guide_question() -> None:
    plan = plan_scout_ai_tools(
        _query("下一個觀察點在哪？哪裡適合拍攝大景？"),
        project_root=PROJECT_ROOT,
    )

    item = _single_tool(plan, ROUTE_CONTEXT_TOOL_ID)
    assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert item.implementation_status == "ready_current_tool"
    assert item.request is not None
    assert item.request["tool_id"] == ROUTE_CONTEXT_TOOL_ID
    assert item.missing_fields == []
    assert CONTEXTUAL_PERMISSION_TOOL_ID not in _tool_ids(plan)
    assert item.boundary.runtime_safety_truth is False


def test_planner_selects_pace_guardian_for_team_pace_fit_question() -> None:
    plan = plan_scout_ai_tools(
        _query("隊伍腳程是否能準時抵達下一個 CP？最慢者需要前移午餐點嗎？"),
        project_root=PROJECT_ROOT,
    )

    item = _single_tool(plan, PACE_GUARDIAN_TOOL_ID)
    assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert item.implementation_status == "ready_current_tool"
    assert item.request is not None
    assert item.request["tool_id"] == PACE_GUARDIAN_TOOL_ID
    assert item.missing_fields == []
    assert CONTEXTUAL_PERMISSION_TOOL_ID not in _tool_ids(plan)
    assert item.boundary.runtime_safety_truth is False


def test_planner_selects_energy_vitals_contract_only_for_health_question() -> None:
    plan = plan_scout_ai_tools(
        _query("我現在心率偏高又很累，需要休息嗎?"),
        project_root=PROJECT_ROOT,
    )

    item = _single_tool(plan, ENERGY_VITALS_TOOL_ID)
    assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert item.implementation_status == "partial_existing_surface"
    assert item.request is not None
    assert item.request["tool_id"] == ENERGY_VITALS_TOOL_ID
    assert "heart_rate_bpm" in item.required_fields
    assert item.missing_fields == []
    assert item.boundary.runtime_safety_truth is False
    assert item.boundary.live_safety_api_calls_allowed is False


def test_planner_selects_safety_boundary_and_live_state_for_candidate_ln_question() -> None:
    plan = plan_scout_ai_tools(
        _query("哪些風險目前只是候選，不能觸發 Ln？"),
        project_root=PROJECT_ROOT,
    )

    tool_ids = _tool_ids(plan)
    assert RISK_SCORE_TOOL_ID in tool_ids
    assert LIVE_NAVIGATION_STATE_TOOL_ID in tool_ids
    assert SAFETY_BOUNDARY_TOOL_ID in tool_ids
    assert WEATHER_WINDOW_TOOL_ID not in tool_ids

    live_item = _single_tool(plan, LIVE_NAVIGATION_STATE_TOOL_ID)
    safety_item = _single_tool(plan, SAFETY_BOUNDARY_TOOL_ID)
    assert live_item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert live_item.implementation_status == "partial_existing_surface"
    assert live_item.request is not None
    assert live_item.request["tool_id"] == LIVE_NAVIGATION_STATE_TOOL_ID
    assert safety_item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert safety_item.implementation_status == "boundary_explain_only"
    assert safety_item.request is not None
    assert safety_item.request["tool_id"] == SAFETY_BOUNDARY_TOOL_ID
    assert live_item.missing_fields == []
    assert safety_item.missing_fields == []
    assert safety_item.boundary.live_safety_api_calls_allowed is False


def test_planner_selects_ins_dr_trace_for_gps_dr_trajectory_question() -> None:
    plan = plan_scout_ai_tools(
        _query("GPS-only 軌跡和 INS/DR 軌跡差多少？"),
        project_root=PROJECT_ROOT,
    )

    item = _single_tool(plan, INS_DR_TRACE_TOOL_ID)
    assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert item.implementation_status == "ready_current_tool"
    assert item.missing_fields == []
    assert item.request is not None
    assert item.request["tool_id"] == INS_DR_TRACE_TOOL_ID
    assert item.boundary.runtime_safety_truth is False


def _query(question: str) -> ScoutAssistantQuery:
    return ScoutAssistantQuery(
        surface=AssistantSurface.PRETRIP,
        question=question,
        context_ref="chilai_nanhua_day1",
        project_id="chilai_nanhua_day1",
    )


def _tool_ids(plan) -> set[str]:
    return {item.tool_id for item in plan.selected_tools}


def _single_tool(plan, tool_id: str):
    matches = [item for item in plan.selected_tools if item.tool_id == tool_id]
    assert len(matches) == 1, plan.model_dump(mode="json")
    return matches[0]
