from __future__ import annotations

from pathlib import Path

from assistant_models import AssistantSurface, ScoutAssistantQuery
from scout_ai_tool_planner import (
    CONTEXTUAL_PERMISSION_TOOL_ID,
    ENERGY_VITALS_TOOL_ID,
    INS_DR_TRACE_TOOL_ID,
    LIVE_NAVIGATION_STATE_TOOL_ID,
    ROUTE_READINESS_TOOL_ID,
    ROUTE_CONTEXT_TOOL_ID,
    ROUTE_ARCHITECTURE_TOOL_ID,
    MEDIA_LITERACY_TOOL_ID,
    SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID,
    PACE_GUARDIAN_TOOL_ID,
    EQUIPMENT_RESOURCE_TOOL_ID,
    TEAM_STATUS_TOOL_ID,
    POST_TRIP_REVIEW_TOOL_ID,
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


def test_planner_selects_route_readiness_for_pretrip_go_no_go_question() -> None:
    plan = plan_scout_ai_tools(
        _query("出發前 Go/No-Go 可以出發嗎？"),
        project_root=PROJECT_ROOT,
    )

    item = _single_tool(plan, ROUTE_READINESS_TOOL_ID)
    assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert item.implementation_status == "ready_current_tool"
    assert item.request is not None
    assert item.request["tool_id"] == ROUTE_READINESS_TOOL_ID
    assert item.missing_fields == []
    assert item.boundary.runtime_safety_truth is False


def test_planner_passes_explicit_route_readiness_inputs_as_arguments() -> None:
    plan = plan_scout_ai_tools(
        _query(
            "beginner transportconfirmed slowestbasisconfirmed "
            "departuretimeconfirmed wxconfirmed sunok gearconfirmed rcconfirmed "
            "pretrip Go/No-Go 可以自主出發嗎？"
        ),
        project_root=PROJECT_ROOT,
    )

    item = _single_tool(plan, ROUTE_READINESS_TOOL_ID)
    assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert item.request is not None
    assert item.request["tool_id"] == ROUTE_READINESS_TOOL_ID
    assert item.request["arguments"] == {
        "user_experience_level": "beginner",
        "transport_access_plan": "user_confirmed",
        "team_slowest_basis_confirmed": True,
        "departure_time_confirmed": True,
        "weather_reviewed": True,
        "daylight_reviewed": True,
        "equipment_confirmed": True,
        "remote_contact_confirmed": True,
    }
    assert _tool_ids(plan) == {ROUTE_READINESS_TOOL_ID}


def test_planner_selects_media_literacy_for_social_photo_bias_question() -> None:
    plan = plan_scout_ai_tools(
        _query("IG 大崩壁美照會不會誤導？"),
        project_root=PROJECT_ROOT,
    )

    item = _single_tool(plan, MEDIA_LITERACY_TOOL_ID)
    assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert item.implementation_status == "ready_current_tool"
    assert item.request is not None
    assert item.request["tool_id"] == MEDIA_LITERACY_TOOL_ID
    assert item.missing_fields == []
    assert item.boundary.runtime_safety_truth is False
    assert ROUTE_CONTEXT_TOOL_ID not in _tool_ids(plan)


def test_planner_selects_media_and_contextual_for_social_detour_question() -> None:
    plan = plan_scout_ai_tools(
        _query("大家都說旁邊那個點很好拍，可以繞去嗎？"),
        project_root=PROJECT_ROOT,
    )

    tool_ids = _tool_ids(plan)
    assert MEDIA_LITERACY_TOOL_ID in tool_ids
    assert CONTEXTUAL_PERMISSION_TOOL_ID in tool_ids

    media = _single_tool(plan, MEDIA_LITERACY_TOOL_ID)
    assert media.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert media.implementation_status == "ready_current_tool"
    assert media.request is not None
    assert media.request["tool_id"] == MEDIA_LITERACY_TOOL_ID
    assert media.boundary.runtime_safety_truth is False

    contextual = _single_tool(plan, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert contextual.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert contextual.request is not None
    assert contextual.request["tool_id"] == CONTEXTUAL_PERMISSION_TOOL_ID


def test_planner_selects_survival_playbook_for_lost_position_question() -> None:
    plan = plan_scout_ai_tools(
        _query("不確定自己在哪，可以下切溪谷找路嗎？"),
        project_root=PROJECT_ROOT,
    )

    item = _single_tool(plan, SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID)
    assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert item.implementation_status == "ready_current_tool"
    assert item.request is not None
    assert item.request["tool_id"] == SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID
    assert item.missing_fields == []
    assert item.boundary.runtime_safety_truth is False


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


def test_planner_selects_weather_and_contextual_for_fog_wait_photo() -> None:
    plan = plan_scout_ai_tools(
        _query("可以等霧散再拍照嗎？"),
        project_root=PROJECT_ROOT,
    )

    tool_ids = _tool_ids(plan)
    assert WEATHER_WINDOW_TOOL_ID in tool_ids
    assert CONTEXTUAL_PERMISSION_TOOL_ID in tool_ids

    contextual = _single_tool(plan, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert contextual.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert contextual.implementation_status == "ready_current_tool"
    assert contextual.request is not None
    assert contextual.request["tool_id"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert contextual.boundary.runtime_safety_truth is False


def test_planner_selects_weather_and_contextual_for_wind_lunch() -> None:
    plan = plan_scout_ai_tools(
        _query("這裡是風口，我們可以在這裡吃午餐嗎？"),
        project_root=PROJECT_ROOT,
    )

    tool_ids = _tool_ids(plan)
    assert WEATHER_WINDOW_TOOL_ID in tool_ids
    assert CONTEXTUAL_PERMISSION_TOOL_ID in tool_ids

    contextual = _single_tool(plan, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert contextual.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert contextual.implementation_status == "ready_current_tool"
    assert contextual.request is not None
    assert contextual.request["tool_id"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert contextual.boundary.runtime_safety_truth is False


def test_planner_selects_weather_and_contextual_for_stream_surge_crossing() -> None:
    plan = plan_scout_ai_tools(
        _query("前方溪水暴漲，還能過溪嗎？"),
        project_root=PROJECT_ROOT,
    )

    tool_ids = _tool_ids(plan)
    assert WEATHER_WINDOW_TOOL_ID in tool_ids
    assert CONTEXTUAL_PERMISSION_TOOL_ID in tool_ids

    contextual = _single_tool(plan, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert contextual.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert contextual.implementation_status == "ready_current_tool"
    assert contextual.request is not None
    assert contextual.request["tool_id"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert contextual.boundary.runtime_safety_truth is False


def test_planner_selects_contextual_permission_for_split_team_summit_question() -> None:
    plan = plan_scout_ai_tools(
        _query("可以讓走得快的人先去山頂嗎？"),
        project_root=PROJECT_ROOT,
    )

    item = _single_tool(plan, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert item.implementation_status == "ready_current_tool"
    assert item.request is not None
    assert item.request["tool_id"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert item.missing_fields == []
    assert item.boundary.runtime_safety_truth is False


def test_planner_selects_contextual_permission_for_rain_gear_question() -> None:
    plan = plan_scout_ai_tools(
        _query("前面下雨了，要不要穿雨衣？"),
        project_root=PROJECT_ROOT,
    )

    item = _single_tool(plan, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert item.implementation_status == "ready_current_tool"
    assert item.request is not None
    assert item.request["tool_id"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert item.missing_fields == []
    assert item.boundary.runtime_safety_truth is False


def test_planner_selects_contextual_permission_for_shortcut_reroute_question() -> None:
    plan = plan_scout_ai_tools(
        _query("這個岔路可以切嗎？"),
        project_root=PROJECT_ROOT,
    )

    tool_ids = _tool_ids(plan)
    assert CONTEXTUAL_PERMISSION_TOOL_ID in tool_ids
    assert ROUTE_ARCHITECTURE_TOOL_ID in tool_ids
    assert LIVE_NAVIGATION_STATE_TOOL_ID in tool_ids

    item = _single_tool(plan, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert item.implementation_status == "ready_current_tool"
    assert item.request is not None
    assert item.request["tool_id"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert item.missing_fields == []
    assert item.boundary.runtime_safety_truth is False


def test_planner_selects_contextual_permission_for_direct_retreat_question() -> None:
    plan = plan_scout_ai_tools(
        _query("隊友很累，要不要直接撤退？"),
        project_root=PROJECT_ROOT,
    )

    tool_ids = _tool_ids(plan)
    assert CONTEXTUAL_PERMISSION_TOOL_ID in tool_ids
    assert ENERGY_VITALS_TOOL_ID in tool_ids
    assert PACE_GUARDIAN_TOOL_ID in tool_ids

    item = _single_tool(plan, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert item.implementation_status == "ready_current_tool"
    assert item.request is not None
    assert item.request["tool_id"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert item.missing_fields == []
    assert item.boundary.runtime_safety_truth is False


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


def test_planner_selects_route_context_for_route_briefing_questions() -> None:
    questions = [
        "奇萊南華建議幾天？",
        "沿途有哪些歷史、文化、自然、地形、季節觀察？",
        "哪些點值得停 3 分鐘？",
    ]

    for question in questions:
        plan = plan_scout_ai_tools(_query(question), project_root=PROJECT_ROOT)
        item = _single_tool(plan, ROUTE_CONTEXT_TOOL_ID)
        assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
        assert item.implementation_status == "ready_current_tool"
        assert item.request is not None
        assert item.request["tool_id"] == ROUTE_CONTEXT_TOOL_ID
        assert item.missing_fields == []
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


def test_planner_selects_pace_and_contextual_for_delayed_summit_question() -> None:
    plan = plan_scout_ai_tools(
        _query("我們晚了 30 分鐘，還可以繼續攻頂嗎？"),
        project_root=PROJECT_ROOT,
    )

    tool_ids = _tool_ids(plan)
    assert PACE_GUARDIAN_TOOL_ID in tool_ids
    assert CONTEXTUAL_PERMISSION_TOOL_ID in tool_ids

    pace = _single_tool(plan, PACE_GUARDIAN_TOOL_ID)
    assert pace.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert pace.implementation_status == "ready_current_tool"
    assert pace.request is not None
    assert pace.request["tool_id"] == PACE_GUARDIAN_TOOL_ID
    assert pace.boundary.runtime_safety_truth is False


def test_planner_selects_equipment_resource_for_device_and_water_question() -> None:
    plan = plan_scout_ai_tools(
        _query("手機電量和頭燈水量夠嗎？"),
        project_root=PROJECT_ROOT,
    )

    item = _single_tool(plan, EQUIPMENT_RESOURCE_TOOL_ID)
    assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert item.implementation_status == "ready_current_tool"
    assert item.request is not None
    assert item.request["tool_id"] == EQUIPMENT_RESOURCE_TOOL_ID
    assert item.missing_fields == []
    assert item.boundary.runtime_safety_truth is False


def test_planner_selects_team_status_for_rear_group_and_checkin_question() -> None:
    plan = plan_scout_ai_tools(
        _query("後隊在哪？最後一次有效位置多久前？留守回報準備好了嗎？"),
        project_root=PROJECT_ROOT,
    )

    item = _single_tool(plan, TEAM_STATUS_TOOL_ID)
    assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert item.implementation_status == "ready_current_tool"
    assert item.request is not None
    assert item.request["tool_id"] == TEAM_STATUS_TOOL_ID
    assert item.missing_fields == []
    assert item.boundary.runtime_safety_truth is False


def test_planner_selects_post_trip_review_for_after_action_question() -> None:
    plan = plan_scout_ai_tools(
        _query("行後回顧要更新哪些下一次規劃？實際耗時哪裡比預期慢？"),
        project_root=PROJECT_ROOT,
    )

    item = _single_tool(plan, POST_TRIP_REVIEW_TOOL_ID)
    assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert item.implementation_status == "ready_current_tool"
    assert item.request is not None
    assert item.request["tool_id"] == POST_TRIP_REVIEW_TOOL_ID
    assert item.missing_fields == []
    assert item.boundary.runtime_safety_truth is False


def test_planner_selects_route_architecture_for_cp_graph_question() -> None:
    plan = plan_scout_ai_tools(
        _query("下一個撤退點在哪？這條路線的難點在哪裡？"),
        project_root=PROJECT_ROOT,
    )

    item = _single_tool(plan, ROUTE_ARCHITECTURE_TOOL_ID)
    assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert item.implementation_status == "ready_current_tool"
    assert item.request is not None
    assert item.request["tool_id"] == ROUTE_ARCHITECTURE_TOOL_ID
    assert item.missing_fields == []
    assert item.boundary.runtime_safety_truth is False


def test_planner_uses_route_architecture_not_contextual_for_turnback_status() -> None:
    plan = plan_scout_ai_tools(
        _query("現在是不是折返點？"),
        project_root=PROJECT_ROOT,
    )

    tool_ids = _tool_ids(plan)
    assert ROUTE_ARCHITECTURE_TOOL_ID in tool_ids
    assert CONTEXTUAL_PERMISSION_TOOL_ID not in tool_ids

    item = _single_tool(plan, ROUTE_ARCHITECTURE_TOOL_ID)
    assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert item.implementation_status == "ready_current_tool"
    assert item.request is not None
    assert item.request["tool_id"] == ROUTE_ARCHITECTURE_TOOL_ID
    assert item.missing_fields == []
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
    assert live_item.implementation_status == "ready_current_tool"
    assert live_item.request is not None
    assert live_item.request["tool_id"] == LIVE_NAVIGATION_STATE_TOOL_ID
    assert safety_item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert safety_item.implementation_status == "boundary_explain_only"
    assert safety_item.request is not None
    assert safety_item.request["tool_id"] == SAFETY_BOUNDARY_TOOL_ID
    assert live_item.missing_fields == []
    assert safety_item.missing_fields == []
    assert safety_item.boundary.live_safety_api_calls_allowed is False


def test_planner_selects_live_navigation_for_branch_uncertainty_question() -> None:
    plan = plan_scout_ai_tools(
        _query("剛剛岔路我有走對嗎？現在要不要回主線？"),
        project_root=PROJECT_ROOT,
    )

    item = _single_tool(plan, LIVE_NAVIGATION_STATE_TOOL_ID)
    assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert item.implementation_status == "ready_current_tool"
    assert item.request is not None
    assert item.request["tool_id"] == LIVE_NAVIGATION_STATE_TOOL_ID
    assert item.boundary.runtime_safety_truth is False


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
