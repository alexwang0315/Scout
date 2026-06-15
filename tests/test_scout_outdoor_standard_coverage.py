from __future__ import annotations

from pathlib import Path

import pytest

from scout_ai_tool_contracts import tool_registry_output
from scout_ai_tool_executor import execute_scout_ai_tool
from scout_contextual_permission_tool import CONTEXTUAL_PERMISSION_TOOL_ID
from scout_navigation_terrain_tool import NAVIGATION_TERRAIN_TOOL_ID
from scout_pace_guardian_tool import PACE_GUARDIAN_TOOL_ID
from scout_route_architecture_tool import ROUTE_ARCHITECTURE_TOOL_ID
from scout_route_context_tool import ROUTE_CONTEXT_TOOL_ID
from scout_weather_window_tool import WEATHER_WINDOW_TOOL_ID


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = (
    ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
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
