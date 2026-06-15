from __future__ import annotations

from pathlib import Path

from assistant_models import AssistantSurface, ScoutAssistantQuery
from scout_ai_tool_planner import (
    CONTEXTUAL_PERMISSION_TOOL_ID,
    ENERGY_VITALS_TOOL_ID,
    INS_DR_TRACE_TOOL_ID,
    LIVE_NAVIGATION_STATE_TOOL_ID,
    NAVIGATION_TERRAIN_TOOL_ID,
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


def test_planner_keeps_cold_exposure_risk_in_weather_not_survival() -> None:
    plan = plan_scout_ai_tools(
        _query("強風低溫會不會讓稜線失溫風險升高？"),
        project_root=PROJECT_ROOT,
    )

    tool_ids = _tool_ids(plan)
    assert WEATHER_WINDOW_TOOL_ID in tool_ids
    assert NAVIGATION_TERRAIN_TOOL_ID in tool_ids
    assert SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID not in tool_ids


def test_planner_keeps_active_hypothermia_in_survival_playbook() -> None:
    plan = plan_scout_ai_tools(
        _query("隊友失溫了現在怎麼做？"),
        project_root=PROJECT_ROOT,
    )

    tool_ids = _tool_ids(plan)
    assert WEATHER_WINDOW_TOOL_ID in tool_ids
    assert SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID in tool_ids


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
            "beginner 訓練 transportconfirmed slowestbasisconfirmed "
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
        "user_goal": "training",
        "transport_access_plan": "user_confirmed",
        "team_slowest_basis_confirmed": True,
        "departure_time_confirmed": True,
        "weather_reviewed": True,
        "daylight_reviewed": True,
        "equipment_confirmed": True,
        "remote_contact_confirmed": True,
    }
    assert _tool_ids(plan) == {ROUTE_READINESS_TOOL_ID}


def test_planner_passes_family_photo_goal_to_route_readiness() -> None:
    plan = plan_scout_ai_tools(
        _query("親子拍攝目標，出發前 Go/No-Go 可以出發嗎？我是中級。"),
        project_root=PROJECT_ROOT,
    )

    item = _single_tool(plan, ROUTE_READINESS_TOOL_ID)
    assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert item.request is not None
    assert item.request["tool_id"] == ROUTE_READINESS_TOOL_ID
    assert item.request["arguments"]["user_experience_level"] == "intermediate"
    assert item.request["arguments"]["user_goal"] == "photo,family"


def test_planner_passes_high_risk_domain_goal_to_route_readiness() -> None:
    plan = plan_scout_ai_tools(
        _query(
            "雪地技術攀登，出發前 Go/No-Go 可以自主出發嗎？"
            "advanced transportconfirmed slowestbasisconfirmed "
            "departuretimeconfirmed wxconfirmed sunok gearconfirmed rcconfirmed"
        ),
        project_root=PROJECT_ROOT,
    )

    item = _single_tool(plan, ROUTE_READINESS_TOOL_ID)
    assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert item.request is not None
    assert item.request["tool_id"] == ROUTE_READINESS_TOOL_ID
    assert item.request["arguments"] == {
        "user_experience_level": "advanced",
        "user_goal": "snow,technical_climb",
        "transport_access_plan": "user_confirmed",
        "team_slowest_basis_confirmed": True,
        "departure_time_confirmed": True,
        "weather_reviewed": True,
        "daylight_reviewed": True,
        "equipment_confirmed": True,
        "remote_contact_confirmed": True,
    }
    assert item.boundary.runtime_safety_truth is False


def test_planner_routes_latest_return_limit_to_route_readiness() -> None:
    plan = plan_scout_ai_tools(
        _query("最晚回程接駁是 16:30，這個行程可以嗎？"),
        project_root=PROJECT_ROOT,
    )

    item = _single_tool(plan, ROUTE_READINESS_TOOL_ID)
    assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert item.request is not None
    assert item.request["tool_id"] == ROUTE_READINESS_TOOL_ID
    assert item.request["arguments"] == {
        "latest_return_time": "16:30",
        "transport_access_plan": "latest_return_user_provided",
    }
    assert item.boundary.runtime_safety_truth is False


def test_planner_routes_stop_policy_question_to_route_readiness() -> None:
    for question in (
        "哪裡是不建議停留點？",
        "有哪些建議停留點和不建議停留點？",
    ):
        plan = plan_scout_ai_tools(
            _query(question),
            project_root=PROJECT_ROOT,
        )

        item = _single_tool(plan, ROUTE_READINESS_TOOL_ID)
        assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
        assert item.implementation_status == "ready_current_tool"
        assert item.request is not None
        assert item.request["tool_id"] == ROUTE_READINESS_TOOL_ID
        assert item.boundary.runtime_safety_truth is False


def test_planner_routes_missing_offline_map_departure_to_navigation_and_equipment() -> None:
    plan = plan_scout_ai_tools(
        _query("我沒下載離線地圖，可以自主出發嗎？"),
        project_root=PROJECT_ROOT,
    )

    tool_ids = _tool_ids(plan)
    assert NAVIGATION_TERRAIN_TOOL_ID in tool_ids
    assert ROUTE_READINESS_TOOL_ID in tool_ids
    assert EQUIPMENT_RESOURCE_TOOL_ID in tool_ids
    assert MAP_PERCEPTION_TOOL_ID not in tool_ids

    navigation = _single_tool(plan, NAVIGATION_TERRAIN_TOOL_ID)
    assert navigation.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert navigation.request is not None
    assert navigation.request["arguments"] == {"offline_map_downloaded": False}
    assert navigation.boundary.runtime_safety_truth is False

    readiness = _single_tool(plan, ROUTE_READINESS_TOOL_ID)
    assert readiness.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert readiness.request is not None
    assert readiness.request["arguments"] == {"equipment_confirmed": False}

    equipment = _single_tool(plan, EQUIPMENT_RESOURCE_TOOL_ID)
    assert equipment.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert equipment.request is not None
    assert equipment.request["arguments"] == {"offline_map_ready": False}
    assert equipment.boundary.runtime_safety_truth is False


def test_planner_routes_offline_map_gpx_check_to_navigation_without_false_missing() -> None:
    plan = plan_scout_ai_tools(
        _query("我有沒有下載離線地圖和 GPX？"),
        project_root=PROJECT_ROOT,
    )

    tool_ids = _tool_ids(plan)
    assert NAVIGATION_TERRAIN_TOOL_ID in tool_ids
    assert EQUIPMENT_RESOURCE_TOOL_ID in tool_ids
    assert MAP_PERCEPTION_TOOL_ID not in tool_ids

    navigation = _single_tool(plan, NAVIGATION_TERRAIN_TOOL_ID)
    assert navigation.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert navigation.request is not None
    assert navigation.request.get("arguments", {}) == {}

    equipment = _single_tool(plan, EQUIPMENT_RESOURCE_TOOL_ID)
    assert equipment.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert equipment.request is not None
    assert equipment.request.get("arguments", {}) == {}


def test_planner_routes_no_signal_navigation_question_to_navigation_terrain() -> None:
    plan = plan_scout_ai_tools(
        _query("沒訊號時我還能導航嗎？"),
        project_root=PROJECT_ROOT,
    )

    navigation = _single_tool(plan, NAVIGATION_TERRAIN_TOOL_ID)
    assert navigation.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert navigation.request is not None
    assert navigation.request.get("arguments", {}) == {}
    assert navigation.boundary.runtime_safety_truth is False


def test_planner_routes_navigation_terrain_backup_positioning_question() -> None:
    plan = plan_scout_ai_tools(
        _query("這條路地圖力需求很高，但我們沒有第二套定位備援，可以自己去嗎？"),
        project_root=PROJECT_ROOT,
    )

    tool_ids = _tool_ids(plan)
    assert NAVIGATION_TERRAIN_TOOL_ID in tool_ids
    assert ROUTE_READINESS_TOOL_ID in tool_ids
    assert MAP_PERCEPTION_TOOL_ID not in tool_ids

    navigation = _single_tool(plan, NAVIGATION_TERRAIN_TOOL_ID)
    assert navigation.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert navigation.request is not None
    assert navigation.request["arguments"] == {"backup_positioning_available": False}
    assert navigation.boundary.runtime_safety_truth is False


def test_planner_routes_low_map_literacy_to_navigation_terrain() -> None:
    plan = plan_scout_ai_tools(
        _query("我不會看等高線，也不知道撤退方向，可以自主前往嗎？"),
        project_root=PROJECT_ROOT,
    )

    navigation = _single_tool(plan, NAVIGATION_TERRAIN_TOOL_ID)
    assert navigation.request is not None
    assert navigation.request["arguments"] == {
        "contour_skill_confirmed": False,
        "retreat_direction_understood": False,
    }


def test_planner_passes_junction_and_risk_layer_literacy_to_navigation_terrain() -> None:
    plan = plan_scout_ai_tools(
        _query("不知道岔路點，也看不懂地形風險圖層，可以自主前往嗎？"),
        project_root=PROJECT_ROOT,
    )

    navigation = _single_tool(plan, NAVIGATION_TERRAIN_TOOL_ID)
    assert navigation.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert navigation.request is not None
    assert navigation.request["arguments"] == {
        "junction_points_known": False,
        "terrain_risk_layers_understood": False,
    }
    assert navigation.boundary.runtime_safety_truth is False


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


def test_planner_passes_media_detour_buffer_to_media_and_contextual() -> None:
    plan = plan_scout_ai_tools(
        _query("看到乾季晴天美照，但今天濕滑又只剩 18 分鐘 buffer，可以繞去拍嗎？"),
        project_root=PROJECT_ROOT,
    )

    media = _single_tool(plan, MEDIA_LITERACY_TOOL_ID)
    assert media.request is not None
    assert media.request["arguments"] == {
        "remaining_safety_buffer_minutes": 18.0,
        "route_condition_reviewed": True,
    }

    contextual = _single_tool(plan, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert contextual.request is not None
    assert contextual.request["arguments"]["action"] == "reroute"
    assert contextual.request["arguments"]["remaining_safety_buffer_minutes"] == 18.0


def test_planner_selects_media_and_contextual_for_exposed_photo_pressure() -> None:
    plan = plan_scout_ai_tools(
        _query("前方是高曝露陡坡，但照片很好看，可以去拍嗎？"),
        project_root=PROJECT_ROOT,
    )

    tool_ids = _tool_ids(plan)
    assert TERRAIN_SCORE_TOOL_ID in tool_ids
    assert MEDIA_LITERACY_TOOL_ID in tool_ids
    assert CONTEXTUAL_PERMISSION_TOOL_ID in tool_ids
    assert ROUTE_CONTEXT_TOOL_ID not in tool_ids

    media = _single_tool(plan, MEDIA_LITERACY_TOOL_ID)
    assert media.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert media.request is not None
    assert media.request["tool_id"] == MEDIA_LITERACY_TOOL_ID
    assert media.boundary.runtime_safety_truth is False

    contextual = _single_tool(plan, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert contextual.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert contextual.request is not None
    assert contextual.request["tool_id"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert contextual.boundary.runtime_safety_truth is False


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


def test_planner_passes_stop_duration_and_buffer_to_contextual_permission() -> None:
    plan = plan_scout_ai_tools(
        _query(
            "現在 2026-06-07T13:36:00+08:00，安全 buffer 還有 21 分鐘，"
            "如果多停 10 分鐘，代價是什麼？"
        ),
        project_root=PROJECT_ROOT,
    )

    item = _single_tool(plan, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert item.request is not None
    assert item.request["tool_id"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert item.request["arguments"] == {
        "action": "stop",
        "requested_duration_minutes": 10.0,
        "remaining_safety_buffer_minutes": 21.0,
        "current_time": "2026-06-07T13:36:00+08:00",
    }
    assert item.boundary.runtime_safety_truth is False


def test_planner_passes_local_clock_to_contextual_permission() -> None:
    plan = plan_scout_ai_tools(
        _query("現在 13:36，安全 buffer 還有 21 分鐘，如果多停 10 分鐘，代價是什麼？"),
        project_root=PROJECT_ROOT,
    )

    item = _single_tool(plan, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert item.request is not None
    assert item.request["arguments"]["current_time"] == "13:36"
    assert item.request["arguments"]["requested_duration_minutes"] == 10.0
    assert item.request["arguments"]["remaining_safety_buffer_minutes"] == 21.0


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


def test_planner_routes_teammate_wait_to_contextual_action() -> None:
    plan = plan_scout_ai_tools(
        _query(
            "現在 2026-06-07T13:50:00+08:00，安全 buffer 還有 18 分鐘，可以等隊友 5 分鐘嗎？"
        ),
        project_root=PROJECT_ROOT,
    )

    contextual = _single_tool(plan, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert contextual.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert contextual.request is not None
    assert contextual.request["arguments"] == {
        "action": "wait_teammate",
        "requested_duration_minutes": 5.0,
        "remaining_safety_buffer_minutes": 18.0,
        "current_time": "2026-06-07T13:50:00+08:00",
    }
    assert contextual.boundary.runtime_safety_truth is False


def test_planner_routes_tripod_permission_to_contextual_action() -> None:
    plan = plan_scout_ai_tools(
        _query("現在 2026-06-07T13:36:00+08:00，安全 buffer 還有 21 分鐘，可以架腳架 4 分鐘嗎？"),
        project_root=PROJECT_ROOT,
    )

    contextual = _single_tool(plan, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert contextual.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert contextual.request is not None
    assert contextual.request["arguments"] == {
        "action": "tripod",
        "requested_duration_minutes": 4.0,
        "remaining_safety_buffer_minutes": 21.0,
        "current_time": "2026-06-07T13:36:00+08:00",
    }
    assert contextual.boundary.runtime_safety_truth is False


def test_planner_routes_photo_stop_budget_phrase_to_contextual_action() -> None:
    plan = plan_scout_ai_tools(
        _query("我們現在還有 21 分鐘安全 buffer，可以多停 10 分鐘拍照嗎？"),
        project_root=PROJECT_ROOT,
    )

    contextual = _single_tool(plan, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert contextual.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert contextual.request is not None
    assert contextual.request["arguments"] == {
        "action": "photo",
        "requested_duration_minutes": 10.0,
        "remaining_safety_buffer_minutes": 21.0,
    }
    assert contextual.boundary.runtime_safety_truth is False


def test_planner_routes_film_stop_with_cp_budget_to_contextual_action() -> None:
    plan = plan_scout_ai_tools(
        _query(
            "前方 CP4 約 42 分鐘，安全 buffer 剩 21 分鐘，可以停 6 分鐘拍影片嗎？"
        ),
        project_root=PROJECT_ROOT,
    )

    contextual = _single_tool(plan, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert contextual.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert contextual.request is not None
    assert contextual.request["arguments"] == {
        "action": "film",
        "requested_duration_minutes": 6.0,
        "remaining_safety_buffer_minutes": 21.0,
        "next_cp_id": "CP4",
        "minutes_to_next_cp": 42.0,
    }
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


def test_planner_passes_lunch_alternate_cp_and_minutes_to_contextual() -> None:
    plan = plan_scout_ai_tools(
        _query("這裡是風口，前方 CP3 約 18 分鐘且較避風，我們可以在這裡吃午餐嗎？"),
        project_root=PROJECT_ROOT,
    )

    contextual = _single_tool(plan, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert contextual.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert contextual.request is not None
    assert contextual.request["arguments"]["action"] == "lunch"
    assert contextual.request["arguments"]["next_cp_id"] == "CP3"
    assert contextual.request["arguments"]["minutes_to_next_cp"] == 18.0


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


def test_planner_routes_fast_passage_to_contextual_continue() -> None:
    plan = plan_scout_ai_tools(
        _query("這段要不要快速通過？"),
        project_root=PROJECT_ROOT,
    )

    item = _single_tool(plan, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert item.request is not None
    assert item.request["arguments"] == {"action": "continue"}
    assert item.boundary.runtime_safety_truth is False


def test_planner_routes_rockfall_fast_passage_to_exposed_section() -> None:
    plan = plan_scout_ai_tools(
        _query("前方是落石區，這段要不要快速通過？"),
        project_root=PROJECT_ROOT,
    )

    item = _single_tool(plan, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert item.request is not None
    assert item.request["arguments"] == {"action": "enter_exposed_section"}
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


def test_planner_selects_micro_decision_for_weather_fatigue_retreat_question() -> None:
    plan = plan_scout_ai_tools(
        _query("天氣變差且隊友疲勞，是否需要撤退？"),
        project_root=PROJECT_ROOT,
    )

    tool_ids = _tool_ids(plan)
    assert WEATHER_WINDOW_TOOL_ID in tool_ids
    assert ENERGY_VITALS_TOOL_ID in tool_ids
    assert PACE_GUARDIAN_TOOL_ID in tool_ids
    assert CONTEXTUAL_PERMISSION_TOOL_ID in tool_ids

    item = _single_tool(plan, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert item.implementation_status == "ready_current_tool"
    assert item.request is not None
    assert item.request["tool_id"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert item.request["arguments"] == {"action": "retreat"}
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


def test_planner_selects_route_context_for_standard_context_layers() -> None:
    questions = [
        "這段林相變化有什麼可以觀察？",
        "有哪些原住民族地名或舊社脈絡？",
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


def test_planner_selects_pace_guardian_for_scout_pace_coefficient_question() -> None:
    plan = plan_scout_ai_tools(
        _query("最慢者的 Scout Pace Coefficient 在碎石下坡和負重下還能照原計畫嗎？"),
        project_root=PROJECT_ROOT,
    )

    item = _single_tool(plan, PACE_GUARDIAN_TOOL_ID)
    assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert item.implementation_status == "ready_current_tool"
    assert item.request is not None
    assert item.request["tool_id"] == PACE_GUARDIAN_TOOL_ID
    assert item.boundary.runtime_safety_truth is False


def test_planner_selects_pace_guardian_for_average_pace_bias_question() -> None:
    plan = plan_scout_ai_tools(
        _query("我們平均腳程還可以，可以用平均速度估嗎？"),
        project_root=PROJECT_ROOT,
    )

    item = _single_tool(plan, PACE_GUARDIAN_TOOL_ID)
    assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert item.implementation_status == "ready_current_tool"
    assert item.request is not None
    assert item.request["tool_id"] == PACE_GUARDIAN_TOOL_ID
    assert item.request["arguments"] == {"leader_accepts_slowest_basis": False}
    assert item.boundary.runtime_safety_truth is False


def test_planner_selects_pace_guardian_for_slowest_member_original_plan_question() -> None:
    plan = plan_scout_ai_tools(
        _query("隊伍最慢的人比預估慢很多，可以繼續原計畫嗎？"),
        project_root=PROJECT_ROOT,
    )

    item = _single_tool(plan, PACE_GUARDIAN_TOOL_ID)
    assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert item.implementation_status == "ready_current_tool"
    assert item.request is not None
    assert item.request["tool_id"] == PACE_GUARDIAN_TOOL_ID
    assert item.boundary.runtime_safety_truth is False


def test_planner_selects_pace_guardian_for_too_fast_question() -> None:
    plan = plan_scout_ai_tools(
        _query("我們是不是走太快？要不要慢一點？"),
        project_root=PROJECT_ROOT,
    )

    item = _single_tool(plan, PACE_GUARDIAN_TOOL_ID)
    assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert item.implementation_status == "ready_current_tool"
    assert item.request is not None
    assert item.request["tool_id"] == PACE_GUARDIAN_TOOL_ID
    assert item.boundary.runtime_safety_truth is False


def test_planner_passes_ahead_of_plan_delta_to_pace_guardian() -> None:
    plan = plan_scout_ai_tools(
        _query("目前比計畫快 20 分鐘，可以繼續照原節奏嗎？"),
        project_root=PROJECT_ROOT,
    )

    item = _single_tool(plan, PACE_GUARDIAN_TOOL_ID)
    assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert item.request is not None
    assert item.request["arguments"] == {"current_delay_minutes": -20.0}
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


def test_planner_selects_weather_and_contextual_for_daylight_summit_pressure() -> None:
    for question in (
        "天快黑了但還差一點到山頂，可以衝一下嗎？",
        "我們快摸黑了，但山頂只差一點，可以趕一下攻頂嗎？",
        "現在日照 buffer 很低，還能繼續攻頂嗎？",
    ):
        plan = plan_scout_ai_tools(
            _query(question),
            project_root=PROJECT_ROOT,
        )

        tool_ids = _tool_ids(plan)
        assert WEATHER_WINDOW_TOOL_ID in tool_ids
        assert CONTEXTUAL_PERMISSION_TOOL_ID in tool_ids
        assert PACE_GUARDIAN_TOOL_ID not in tool_ids

        weather = _single_tool(plan, WEATHER_WINDOW_TOOL_ID)
        assert weather.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
        assert weather.request is not None
        assert weather.request["tool_id"] == WEATHER_WINDOW_TOOL_ID
        assert weather.boundary.runtime_safety_truth is False

        contextual = _single_tool(plan, CONTEXTUAL_PERMISSION_TOOL_ID)
        assert contextual.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
        assert contextual.request is not None
        assert contextual.request["tool_id"] == CONTEXTUAL_PERMISSION_TOOL_ID
        assert contextual.boundary.runtime_safety_truth is False


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


def test_planner_routes_dead_phone_watch_battery_to_equipment_resource() -> None:
    plan = plan_scout_ai_tools(
        _query("如果手機沒電但手錶還有電，可以繼續嗎？"),
        project_root=PROJECT_ROOT,
    )

    tool_ids = _tool_ids(plan)
    assert EQUIPMENT_RESOURCE_TOOL_ID in tool_ids
    assert PACE_GUARDIAN_TOOL_ID not in tool_ids

    equipment = _single_tool(plan, EQUIPMENT_RESOURCE_TOOL_ID)
    assert equipment.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert equipment.request is not None
    assert equipment.request["arguments"] == {"phone_battery_percent": 0}
    assert equipment.boundary.runtime_safety_truth is False


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


def test_planner_routes_unanswered_message_to_team_status_with_overdue_minutes() -> None:
    plan = plan_scout_ai_tools(
        _query("隊友已經 20 分鐘沒回訊息，要怎麼辦？"),
        project_root=PROJECT_ROOT,
    )

    item = _single_tool(plan, TEAM_STATUS_TOOL_ID)
    assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert item.implementation_status == "ready_current_tool"
    assert item.request is not None
    assert item.request["tool_id"] == TEAM_STATUS_TOOL_ID
    assert item.request["arguments"] == {
        "communication_status": "unknown",
        "checkin_overdue_minutes": 20.0,
        "last_heard_minutes": 20.0,
    }
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


def test_planner_selects_post_trip_review_for_trip_end_debrief_question() -> None:
    plan = plan_scout_ai_tools(
        _query("這次旅行結束後要怎麼檢討？哪些經驗要回寫到下次規劃？"),
        project_root=PROJECT_ROOT,
    )

    item = _single_tool(plan, POST_TRIP_REVIEW_TOOL_ID)
    assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert item.implementation_status == "ready_current_tool"
    assert item.request is not None
    assert item.request["tool_id"] == POST_TRIP_REVIEW_TOOL_ID
    assert item.missing_fields == []
    assert item.boundary.runtime_safety_truth is False


def test_planner_passes_post_trip_event_taxonomy_feedback() -> None:
    plan = plan_scout_ai_tools(
        _query(
            "行後比預期難，摸黑前差點錯過岔路，隊友滑倒、脫隊，"
            "頭燈電量不足，午後低溫濕冷比預報早，下次要怎麼更新？"
        ),
        project_root=PROJECT_ROOT,
    )

    item = _single_tool(plan, POST_TRIP_REVIEW_TOOL_ID)
    assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert item.request is not None
    args = item.request["arguments"]
    assert args["subjective_difficulty"] == "harder_than_expected"
    assert "摸黑" in args["near_miss_events"]
    assert "錯過岔路" in args["near_miss_events"]
    assert "滑倒" in args["incident_events"]
    assert "脫隊" in args["near_miss_events"]
    assert "頭燈電量不足" in args["equipment_gaps"]
    assert args["weather_matched_expectation"] is False
    assert args["user_feedback_items"] == ["review_for_next_pretrip"]
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


def test_planner_passes_turnback_current_context_to_route_architecture() -> None:
    plan = plan_scout_ai_tools(
        _query("現在 2013-10-08T15:10:00+08:00 在雲海保線所，現在是不是折返點？"),
        project_root=PROJECT_ROOT,
    )

    item = _single_tool(plan, ROUTE_ARCHITECTURE_TOOL_ID)
    assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert item.request is not None
    assert item.request["tool_id"] == ROUTE_ARCHITECTURE_TOOL_ID
    assert item.request["arguments"] == {
        "current_time": "2013-10-08T15:10:00+08:00",
        "current_cp_id": "雲海保線所",
    }
    assert item.boundary.runtime_safety_truth is False


def test_planner_passes_local_turnback_time_to_route_architecture() -> None:
    plan = plan_scout_ai_tools(
        _query("現在 15:10 在雲海保線所，現在是不是折返點？"),
        project_root=PROJECT_ROOT,
    )

    item = _single_tool(plan, ROUTE_ARCHITECTURE_TOOL_ID)
    assert item.request is not None
    assert item.request["arguments"] == {
        "current_time": "15:10",
        "current_cp_id": "雲海保線所",
    }


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
