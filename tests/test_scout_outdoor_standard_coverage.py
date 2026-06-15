from __future__ import annotations

from pathlib import Path

import pytest

from scout_ai_tool_contracts import tool_registry_output
from scout_ai_tool_executor import execute_scout_ai_tool
from scout_contextual_permission_tool import CONTEXTUAL_PERMISSION_TOOL_ID
from scout_media_literacy_tool import MEDIA_LITERACY_TOOL_ID
from scout_navigation_terrain_tool import NAVIGATION_TERRAIN_TOOL_ID
from scout_pace_guardian_tool import PACE_GUARDIAN_TOOL_ID
from scout_post_trip_review_tool import POST_TRIP_REVIEW_TOOL_ID
from scout_route_architecture_tool import ROUTE_ARCHITECTURE_TOOL_ID
from scout_route_context_tool import ROUTE_CONTEXT_TOOL_ID
from scout_route_readiness_tool import ROUTE_READINESS_TOOL_ID
from scout_weather_window_tool import WEATHER_WINDOW_TOOL_ID


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = (
    ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
)
POST_ANALYSIS_ROOT = (
    ROOT / "tests" / "fixtures" / "post_analysis" / "chilai_nanhua_day1_post_analysis"
)

STANDARD_DECISIONS = {
    "GO",
    "CONDITIONAL_GO",
    "GUIDED_ONLY",
    "CHANGE_PLAN",
    "DELAY",
    "NO_GO",
    "ESCALATE",
}

DECISION_OUTPUT_REQUIRED_KEYS = {
    "decisionObjectSchema",
    "decision",
    "allowed",
    "firstLayer",
    "secondLayer",
    "cost",
    "confidence",
    "runtimeSafetyTruth",
    "mainReasons",
    "nextAction",
    "uncertaintyNotes",
    "residualRisk",
    "requiredConditions",
    "alternativeActions",
}

FORBIDDEN_SAFETY_PHRASES = ("請自行評估", "一定安全", "保證沒問題", "安全無虞")

SIX_FORCE_SCENARIOS = [
    pytest.param(
        "探索力",
        "Route Context Intelligence",
        ROUTE_CONTEXT_TOOL_ID,
        "scout.ai.experience_guide.assess",
        "這段路線有什麼歷史自然觀察點？",
        {},
        "section 6 Route Context Intelligence",
        id="route-context-exploration",
    ),
    pytest.param(
        "自信力",
        "Readiness & Pace Fit",
        PACE_GUARDIAN_TOOL_ID,
        "scout.ai.team_pace_fit.assess",
        "隊伍腳程是否能準時抵達下一個 CP？",
        {
            "team_members": [
                {
                    "member_id": "lead",
                    "display_label": "Lead",
                    "pace_mps": 1.0,
                    "reserve_minutes": 60,
                },
                {
                    "member_id": "slow",
                    "display_label": "Slow member",
                    "pace_mps": 0.72,
                    "reserve_minutes": 35,
                },
            ],
            "minutes_to_next_cp": 25,
            "leader_accepts_slowest_basis": True,
        },
        "section 7 Readiness & Pace Fit",
        id="pace-fit-confidence",
    ),
    pytest.param(
        "勇氣力",
        "Contextual Permissioning",
        CONTEXTUAL_PERMISSION_TOOL_ID,
        "scout.ai.micro_decision.assess",
        "我可以在這裡停下來拍一段影片嗎？",
        {
            "action": "film",
            "current_time": "2026-06-07T13:36:00+08:00",
            "current_cp_id": "CP3",
            "next_cp_id": "CP4",
            "remaining_safety_buffer_minutes": 21,
            "current_delay_minutes": 9,
            "next_segment_uncertainty_minutes": 3,
            "weather_reserve_minutes": 2,
            "communication_status": "ok",
            "equipment_status": "ok",
        },
        "section 8 Contextual Permissioning",
        id="contextual-permission-courage",
    ),
    pytest.param(
        "路線力",
        "Route Architecture Intelligence",
        ROUTE_ARCHITECTURE_TOOL_ID,
        "scout.ai.cp_graph.assess",
        "下一個撤退點在哪？這條路線難點在哪？",
        {},
        "section 9 Route Architecture Intelligence",
        id="route-architecture",
    ),
    pytest.param(
        "天氣力",
        "Weather-to-Decision Intelligence",
        WEATHER_WINDOW_TOOL_ID,
        "scout.ai.weather_window.assess",
        "明天午後雷雨要不要提早紮營",
        {},
        "section 10 Weather-to-Decision Intelligence",
        id="weather-to-decision",
    ),
    pytest.param(
        "地圖力",
        "Navigation & Terrain Intelligence",
        NAVIGATION_TERRAIN_TOOL_ID,
        "scout.ai.map_readiness.assess",
        "離線地圖和 GPX 是否足夠？",
        {
            "offline_map_downloaded": True,
            "gpx_loaded_on_device": True,
            "contour_skill_confirmed": False,
            "terrain_feature_skill_confirmed": False,
            "junction_points_known": True,
            "retreat_direction_understood": False,
            "backup_positioning_available": True,
            "terrain_risk_layers_understood": False,
            "team_map_user_count": 1,
        },
        "section 11 Navigation & Terrain Intelligence",
        id="navigation-terrain-map",
    ),
]


def test_tool_registry_marks_all_six_force_tools_ready_current() -> None:
    registry = tool_registry_output(include_not_implemented=True)
    by_id = {tool.tool_id: tool for tool in registry.tools}

    assert registry.implementation_status_counts == {"ready_current_tool": 26}
    for scenario in SIX_FORCE_SCENARIOS:
        _, system_language, tool_id, alias, _, _, _ = scenario.values
        contract = by_id[tool_id]
        assert contract.implementation_status == "ready_current_tool", system_language
        assert contract.implementation_gap is None
        assert alias in contract.aliases


@pytest.mark.parametrize(
    (
        "six_force",
        "system_language",
        "canonical_tool_id",
        "tool_alias",
        "query",
        "arguments",
        "standard_section",
    ),
    SIX_FORCE_SCENARIOS,
)
def test_six_force_tools_emit_standard_contextual_permission_decisions(
    six_force: str,
    system_language: str,
    canonical_tool_id: str,
    tool_alias: str,
    query: str,
    arguments: dict[str, object],
    standard_section: str,
) -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": tool_alias,
            "project_root": str(PROJECT_ROOT),
            "query": query,
            "arguments": arguments,
        }
    )

    payload = result.payload
    decision_output = payload["decision_output"]
    missing_keys = DECISION_OUTPUT_REQUIRED_KEYS - set(decision_output)

    assert result.status == "completed", six_force
    assert result.tool_id == canonical_tool_id
    assert result.implementation_status == "ready_current_tool"
    assert not missing_keys, f"{six_force} missing decision_output keys: {missing_keys}"
    assert payload["decision"] in STANDARD_DECISIONS
    assert decision_output["decision"] == payload["decision"]
    assert decision_output["decisionObjectSchema"] == "ContextualPermission"
    assert isinstance(decision_output["allowed"], bool)
    assert decision_output["runtimeSafetyTruth"] is False
    assert decision_output["firstLayer"]["decision"]
    assert decision_output["firstLayer"]["limit"]
    assert decision_output["firstLayer"]["reason"]
    assert decision_output["firstLayer"]["nextStep"]
    assert decision_output["secondLayer"]["details"]
    assert decision_output["mainReasons"]
    assert decision_output["nextAction"]
    assert isinstance(decision_output["cost"], dict)
    assert isinstance(decision_output["residualRisk"], list)
    assert result.boundary.runtime_safety_truth is False
    assert result.boundary.live_safety_api_calls_allowed is False
    assert any(standard_section in item for item in payload["standard_alignment"]), (
        system_language
    )


def test_mvp_pretrip_go_no_go_outputs_required_package_and_conservative_gates() -> None:
    missing_result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.pretrip_go_no_go.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "出發前 Go/No-Go 可以出發嗎？",
        }
    )
    high_risk_result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.pretrip_go_no_go.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "雪地技術攀登，出發前 Go/No-Go 可以自主出發嗎？",
            "arguments": {
                "user_experience_level": "advanced",
                "user_goal": "雪地技術攀登",
                "transport_access_plan": "confirmed shuttle",
                "team_slowest_basis_confirmed": True,
                "departure_time_confirmed": True,
                "weather_reviewed": True,
                "daylight_reviewed": True,
                "equipment_confirmed": True,
                "remote_contact_confirmed": True,
            },
        }
    )

    assert missing_result.tool_id == ROUTE_READINESS_TOOL_ID
    assert missing_result.payload["decision"] == "DELAY"
    assert "user_experience_level" in missing_result.missing_fields
    assert "slowest_team_basis" in missing_result.missing_fields
    _assert_standard_output(missing_result.payload["decision_output"])
    missing_package = missing_result.payload["pretrip_decision_package"]
    required_outputs = missing_package["required_outputs"]
    assert required_outputs["pretrip_decision"] == "DELAY"
    assert required_outputs["cp_graph"]["checkpoint_count"] == 124
    assert required_outputs["cp_graph"]["segment_count"] == 123
    assert required_outputs["latest_turnaround"]["checkpoint_name"] == "雲海保線所"
    assert required_outputs["top_risk_sources"]
    assert required_outputs["required_conditions"]
    assert required_outputs["alternatives_or_short_routes"]
    assert required_outputs["pretrip_checklist"]
    assert required_outputs["residual_risk"]
    assert missing_package["decision_limits"]["allowed"] is False
    assert missing_package["acceptance_coverage"]["explicit_decision"] is True
    assert missing_result.boundary.runtime_safety_truth is False

    assert high_risk_result.tool_id == ROUTE_READINESS_TOOL_ID
    assert high_risk_result.payload["decision"] == "GUIDED_ONLY"
    assert high_risk_result.payload["guided_only_gate"]["required"] is True
    assert high_risk_result.payload["guided_only_gate"]["reason"] == (
        "high_risk_non_goal_domain"
    )
    assert high_risk_result.payload["decision_output"]["allowed"] is False
    assert high_risk_result.payload["decision_output"]["runtimeSafetyTruth"] is False
    assert "不得自主出發" in high_risk_result.payload["decision_output"]["firstLayer"][
        "limit"
    ]
    _assert_no_forbidden_safety_language(high_risk_result.payload)


def test_mvp_on_route_micro_decision_is_bounded_and_conservative_when_missing() -> None:
    missing_result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.micro_decision.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "我可以在這裡停留 10 分鐘嗎？",
        }
    )
    film_result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.micro_decision.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "我可以在這裡停下來拍一段影片嗎？",
            "arguments": {
                "action": "film",
                "current_time": "2026-06-07T13:36:00+08:00",
                "current_cp_id": "CP3",
                "next_cp_id": "CP4",
                "remaining_safety_buffer_minutes": 21,
                "current_delay_minutes": 9,
                "next_segment_uncertainty_minutes": 3,
                "weather_reserve_minutes": 2,
                "communication_status": "ok",
                "equipment_status": "ok",
            },
        }
    )

    assert missing_result.tool_id == CONTEXTUAL_PERMISSION_TOOL_ID
    assert missing_result.payload["decision"] == "NO_GO"
    assert "remaining_safety_buffer_minutes" in missing_result.missing_fields
    assert missing_result.payload["decision_output"]["allowed"] is False
    assert missing_result.payload["decision_output"]["cost"][
        "timeBufferChangeMinutes"
    ] == -10
    _assert_standard_output(missing_result.payload["decision_output"])

    assert film_result.tool_id == CONTEXTUAL_PERMISSION_TOOL_ID
    assert film_result.payload["decision"] == "CONDITIONAL_GO"
    assert film_result.payload["allowed"] is True
    assert film_result.payload["max_duration_minutes"] == 6
    assert film_result.payload["leave_by"] == "2026-06-07T13:42:00+08:00"
    assert film_result.payload["contextual_permission"]["cost"][
        "timeBufferChangeMinutes"
    ] == -6
    assert "最多 6 分鐘" in film_result.payload["field_answer"]
    assert "13:42" in film_result.payload["field_answer"]
    assert film_result.payload["decision_output"]["nextAction"]
    assert film_result.payload["decision_output"]["runtimeSafetyTruth"] is False
    _assert_no_forbidden_safety_language(film_result.payload)


def test_post_trip_learning_package_covers_reviewable_model_updates_without_writeback() -> None:
    missing_result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.after_action.assess",
            "project_root": str(POST_ANALYSIS_ROOT),
            "query": "行後回顧要更新哪些下一次規劃？",
        }
    )
    incident_result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.after_action.assess",
            "project_root": str(POST_ANALYSIS_ROOT),
            "query": "行後有 near miss 和滑倒事件，下一次要怎麼改？",
            "arguments": {
                "subjective_difficulty": "比預期難",
                "equipment_gaps": ["手套不足"],
                "near_miss_events": ["摸黑前差點錯過岔路"],
                "incident_events": ["隊員滑倒擦傷"],
                "weather_matched_expectation": False,
                "route_condition_notes": ["午後霧氣比預報早"],
                "route_context_updates": ["雲海保線所有可靠集合空間"],
                "user_feedback_items": ["午餐點應前移"],
            },
        }
    )

    assert missing_result.tool_id == POST_TRIP_REVIEW_TOOL_ID
    assert missing_result.payload["decision"] == "DELAY"
    assert "subjective_difficulty" in missing_result.missing_fields
    learning_package = missing_result.payload["post_trip_learning_package"]
    assert learning_package["data_to_collect"]["actual_cp_pass_times"][
        "observed_edge_count"
    ] == 73
    assert learning_package["data_to_collect"]["actual_stop_duration"][
        "rest_interval_count"
    ] == 62
    assert learning_package["model_update_target_coverage"][
        "user_scout_pace_coefficient"
    ] is True
    assert learning_package["model_update_target_coverage"][
        "route_cp_elapsed_time"
    ] is True
    assert learning_package["writeback_policy"][
        "automatic_user_model_update_allowed"
    ] is False
    assert learning_package["writeback_policy"][
        "automatic_route_model_update_allowed"
    ] is False
    assert learning_package["acceptance_coverage"]["section_20_1_data_to_collect"] is True
    assert learning_package["acceptance_coverage"]["section_20_2_model_update_targets"] is True
    assert missing_result.payload["boundary"]["learning_write_performed"] is False

    assert incident_result.payload["decision"] == "ESCALATE"
    assert incident_result.payload["post_trip_feedback"]["event_taxonomy"][
        "review_required"
    ] is True
    assert {
        "lost_or_navigation_uncertainty",
        "slip_or_fall",
        "darkness_or_daylight_overrun",
        "equipment_failure",
    } <= set(
        incident_result.payload["post_trip_feedback"]["event_taxonomy"][
            "matched_event_types"
        ]
    )
    assert incident_result.payload["post_trip_review"]["learning_write_performed"] is False
    assert incident_result.payload["decision_output"]["runtimeSafetyTruth"] is False
    _assert_no_forbidden_safety_language(incident_result.payload)


def test_media_literacy_product_function_counters_bias_without_permission_leak() -> None:
    social_photo_result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.media_bias.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "IG 大崩壁美照會不會誤導？想去打卡。",
        }
    )
    summit_pressure_result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.media_bias.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "已經快到山頂了，不攻頂會不會很可惜？",
        }
    )

    assert social_photo_result.tool_id == MEDIA_LITERACY_TOOL_ID
    assert social_photo_result.payload["decision"] == "NO_GO"
    assert social_photo_result.payload["allowed"] is False
    assert {
        bias["bias_id"]
        for bias in social_photo_result.payload["media_literacy"]["detected_biases"]
    } >= {"beauty_photo_bias", "check_in_pressure"}
    assert social_photo_result.payload["media_bias_analysis"][
        "target_context_points"
    ][0]["risk_context"] is True
    assert "fresh_weather_or_route_condition_review" in social_photo_result.missing_fields
    assert social_photo_result.payload["decision_output"]["action"] in {
        "photo",
        "stop",
    }
    assert social_photo_result.payload["decision_output"]["allowed"] is False
    assert social_photo_result.payload["decision_output"]["runtimeSafetyTruth"] is False
    assert any(
        "section 21 Media Literacy" in item
        for item in social_photo_result.payload["standard_alignment"]
    )
    _assert_standard_output(social_photo_result.payload["decision_output"])
    _assert_no_forbidden_safety_language(social_photo_result.payload)

    assert summit_pressure_result.payload["decision"] == "NO_GO"
    assert summit_pressure_result.payload["decision_output"]["action"] == "summit"
    assert any(
        bias["bias_id"] == "sunk_cost_bias"
        for bias in summit_pressure_result.payload["media_literacy"]["detected_biases"]
    )
    assert any(
        "最近安全 CP" in action
        for action in summit_pressure_result.payload["decision_output"][
            "alternativeActions"
        ]
    )
    assert summit_pressure_result.payload["decision_output"]["runtimeSafetyTruth"] is False
    assert summit_pressure_result.boundary.live_safety_api_calls_allowed is False


def _assert_standard_output(decision_output: dict[str, object]) -> None:
    missing_keys = DECISION_OUTPUT_REQUIRED_KEYS - set(decision_output)
    assert not missing_keys
    assert decision_output["decision"] in STANDARD_DECISIONS
    assert decision_output["decisionObjectSchema"] == "ContextualPermission"
    assert isinstance(decision_output["allowed"], bool)
    assert decision_output["runtimeSafetyTruth"] is False
    assert decision_output["firstLayer"]["decision"]
    assert decision_output["firstLayer"]["limit"]
    assert decision_output["firstLayer"]["reason"]
    assert decision_output["firstLayer"]["nextStep"]
    assert decision_output["mainReasons"]
    assert decision_output["nextAction"]
    assert isinstance(decision_output["cost"], dict)


def _assert_no_forbidden_safety_language(payload: dict[str, object]) -> None:
    text = str(payload)
    for phrase in FORBIDDEN_SAFETY_PHRASES:
        assert phrase not in text
