from __future__ import annotations

import re
from pathlib import Path

import pytest

from scout_ai_full_workflow import run_scout_ai_full_workflow
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

SECTION_25_EXAMPLE_SCENARIOS = [
    pytest.param(
        "25.1 拍影片",
        "現在 13:36，前方 CP4 約 42 分鐘，安全 buffer 剩 21 分鐘，可以停 6 分鐘拍影片嗎？",
        CONTEXTUAL_PERMISSION_TOOL_ID,
        "film",
        "CONDITIONAL_GO",
        True,
        ("最多 6 分鐘", "13:42", "前往 CP4", "消耗 6 分鐘 buffer"),
        id="section-25-film",
    ),
    pytest.param(
        "25.2 午餐",
        "這裡是風口，前方 CP3 約 18 分鐘且較避風，安全 buffer 還有 45 分鐘，我們可以在這裡吃午餐嗎？",
        CONTEXTUAL_PERMISSION_TOOL_ID,
        "lunch",
        "NO_GO",
        False,
        ("不建議吃午餐", "約 18 分鐘到 CP3", "較避風", "不要消耗停留或改線 buffer"),
        id="section-25-lunch",
    ),
    pytest.param(
        "25.3 攻頂",
        "我們晚了 30 分鐘，還可以繼續攻頂嗎？",
        PACE_GUARDIAN_TOOL_ID,
        "pace_adjustment",
        "NO_GO",
        False,
        ("不建議繼續攻頂", "落後約 30 分鐘", "最慢者", "縮短行程或撤退"),
        id="section-25-summit",
    ),
    pytest.param(
        "25.4 等霧散拍照",
        "現在 14:00，安全 buffer 剩 18 分鐘，可以等霧散 5 分鐘再拍照嗎？",
        CONTEXTUAL_PERMISSION_TOOL_ID,
        "wait",
        "CONDITIONAL_GO",
        True,
        ("最多 5 分鐘", "14:05", "放棄拍攝", "消耗 5 分鐘 buffer"),
        id="section-25-fog-wait",
    ),
    pytest.param(
        "25.5 社群拍攝點",
        "大家都說旁邊那個點很好拍，可以繞去嗎？",
        MEDIA_LITERACY_TOOL_ID,
        "reroute",
        "NO_GO",
        False,
        ("不建議為媒體點位停留或改線", "beauty_photo_bias", "媒體內容", "不當作現場授權"),
        id="section-25-social-photo",
    ),
]


def test_standard_completion_audit_covers_all_sections_and_primary_surfaces() -> None:
    missing_sections = _missing_standard_section_numbers()
    assert missing_sections == []

    registry = tool_registry_output(include_not_implemented=True)
    assert registry.tool_count == 26
    assert registry.ready_current_tool_count == 26
    assert registry.contract_only_tool_count == 0
    assert registry.implementation_status_counts == {"ready_current_tool": 26}

    result = run_scout_ai_full_workflow(
        "請以 SCOUT_OUTDOOR_AI_AGENT_STANDARD 為基準，檢視目前 Scout 體系還缺哪些東西，六力是否都有實作？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=8,
    )
    decision_output = result.decision_output

    assert decision_output["answerSourceToolId"] == "scout.ai.standard_gap_overview.v0"
    assert decision_output["decision"] == "GUIDED_ONLY"
    assert decision_output["allowed"] is False
    assert decision_output["runtimeSafetyTruth"] is False
    assert result.boundary.runtime_safety_truth is False
    assert decision_output["cost"]["standardGroupCount"] == 10
    assert decision_output["cost"]["coveredStandardGroupCount"] == 10
    assert decision_output["cost"]["implementationGapToolCount"] == 0
    assert decision_output["cost"]["contextOrReviewEvidenceGapToolCount"] == 6
    assert decision_output["cost"]["uiUxValidationNeeded"] is True
    audit = decision_output["standardGapAudit"]
    assert audit["schema"] == "scout_standard_gap_audit.v0"
    assert audit["runtimeSafetyTruth"] is False
    assert audit["summary"]["standardGroupCount"] == 10
    assert audit["summary"]["coveredStandardGroupCount"] == 10
    assert audit["summary"]["implementationGapToolCount"] == 0
    assert audit["summary"]["contextOrReviewEvidenceGapToolCount"] == 6
    assert audit["summary"]["uiUxValidationNeeded"] is True
    statuses = {group["status"] for group in audit["groups"]}
    assert "implemented_requires_context_or_review_evidence" in statuses
    assert "implemented_synthesis_formatter" in statuses
    classifications = {item["classification"] for item in audit["inputOrEvidenceGaps"]}
    assert "live_navigation_state_required" not in classifications
    assert audit["implementationGaps"] == []
    assert any("UI/UX" in item for item in audit["nextSlices"])
    for label in ("探索力", "自信力", "勇氣力", "路線力", "天氣力", "地圖力"):
        assert label in result.answer
    for source_id in (
        "scout.ai.product_identity_standard.v0",
        "scout.ai.standard_glossary.v0",
        "scout.ai.contextual_permission.assess.v0",
        "scout.ai.route_readiness.assess.v0",
        "scout.ai.media_literacy.assess.v0",
    ):
        assert source_id in result.answer
    assert "缺口分類" in result.answer
    assert "情境輸入/審核 evidence gap=6" in result.answer
    assert "不是出發批准或 runtime safety truth" in result.answer


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
    assert missing_result.payload["decision"] == "CONDITIONAL_GO"
    assert missing_result.missing_fields == []
    _assert_standard_output(missing_result.payload["decision_output"])
    missing_package = missing_result.payload["pretrip_decision_package"]
    required_outputs = missing_package["required_outputs"]
    assert required_outputs["pretrip_decision"] == "CONDITIONAL_GO"
    assert required_outputs["cp_graph"]["checkpoint_count"] == 124
    assert required_outputs["cp_graph"]["segment_count"] == 123
    assert required_outputs["latest_turnaround"]["checkpoint_name"] == "雲海保線所"
    assert required_outputs["top_risk_sources"]
    assert required_outputs["required_conditions"]
    assert required_outputs["alternatives_or_short_routes"]
    assert required_outputs["pretrip_checklist"]
    assert required_outputs["residual_risk"]
    assert missing_package["decision_limits"]["allowed"] is True
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


def test_product_identity_answers_standard_north_star_and_must_not_become() -> None:
    result = run_scout_ai_full_workflow(
        "Scout 是什麼？它是不是路線資料庫或天氣工具？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=8,
    )

    decision_output = result.decision_output
    assert result.selected_tool_count == 0
    assert result.answerability == "standard_product_identity"
    assert decision_output["answerSourceToolId"] == (
        "scout.ai.product_identity_standard.v0"
    )
    assert decision_output["decision"] == "GUIDED_ONLY"
    assert decision_output["allowed"] is False
    assert decision_output["runtimeSafetyTruth"] is False
    _assert_standard_output(decision_output)
    assert "Scout 是戶外活動的 AI 決策層" in result.answer
    assert "不是路線資料庫" in result.answer
    assert "不是天氣工具" in result.answer
    assert "風險 dashboard" in result.answer
    assert "應該沒關係吧" in result.answer
    assert "不是出發批准或 runtime safety truth" in result.answer
    assert any(
        "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 26" in item
        for item in decision_output["standardAlignment"]
    )
    assert result.boundary.runtime_safety_truth is False


def test_standard_glossary_terms_are_explainable_without_operational_detour() -> None:
    result = run_scout_ai_full_workflow(
        "CP Graph、Risk Budget、Scout Pace Coefficient、Veto Power 和 Permission Power 是什麼？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=8,
    )

    decision_output = result.decision_output
    assert result.selected_tool_count == 0
    assert result.answerability == "standard_glossary"
    assert decision_output["answerSourceToolId"] == "scout.ai.standard_glossary.v0"
    assert decision_output["decision"] == "GUIDED_ONLY"
    assert decision_output["allowed"] is False
    assert decision_output["runtimeSafetyTruth"] is False
    _assert_standard_output(decision_output)
    assert "CP Graph" in result.answer
    assert "Risk Budget" in result.answer
    assert "Scout Pace Coefficient" in result.answer
    assert "Veto Power" in result.answer
    assert "Permission Power" in result.answer
    assert "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 29" in " ".join(
        decision_output["standardAlignment"]
    )
    assert "風險分數判斷" not in result.answer
    assert result.boundary.runtime_safety_truth is False


@pytest.mark.parametrize(
    (
        "scenario",
        "query",
        "answer_source_tool_id",
        "action",
        "decision",
        "allowed",
        "required_phrases",
    ),
    SECTION_25_EXAMPLE_SCENARIOS,
)
def test_section_25_example_scenarios_are_full_workflow_decisions(
    scenario: str,
    query: str,
    answer_source_tool_id: str,
    action: str,
    decision: str,
    allowed: bool,
    required_phrases: tuple[str, ...],
) -> None:
    result = run_scout_ai_full_workflow(
        query,
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=8,
    )

    decision_output = result.decision_output
    assert result.completed_tool_count >= 1, scenario
    assert result.failed_tool_count == 0, scenario
    assert decision_output["answerSourceToolId"] == answer_source_tool_id
    assert decision_output["action"] == action
    assert decision_output["decision"] == decision
    assert decision_output["allowed"] is allowed
    assert decision_output["runtimeSafetyTruth"] is False
    assert result.boundary.runtime_safety_truth is False
    _assert_standard_output(decision_output)
    _assert_no_forbidden_safety_language(decision_output)
    for phrase in required_phrases:
        assert phrase in result.answer, scenario


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


def _missing_standard_section_numbers() -> list[int]:
    spec_text = (ROOT / "docs/specs/SCOUT_OUTDOOR_AI_AGENT_STANDARD.md").read_text(
        encoding="utf-8"
    )
    section_numbers = [
        int(match.group(1))
        for match in re.finditer(r"^## (\d+)\.\s+", spec_text, re.MULTILINE)
    ]
    coverage_paths = [
        *ROOT.glob("scout_*_tool.py"),
        ROOT / "scout_ai_answer_synthesis.py",
        ROOT / "scout_ai_tool_planner.py",
        ROOT / "tests/test_scout_outdoor_standard_coverage.py",
    ]
    coverage_text = "\n".join(
        path.read_text(encoding="utf-8") for path in coverage_paths if path.exists()
    )
    missing = []
    for section_number in section_numbers:
        pattern = re.compile(
            rf"section {section_number}(?:\D|$)|section {section_number}\.|## {section_number}\.\s+",
            re.IGNORECASE,
        )
        if not pattern.search(coverage_text):
            missing.append(section_number)
    return missing
