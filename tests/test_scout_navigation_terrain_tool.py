from __future__ import annotations

from pathlib import Path

from scout_navigation_terrain_tool import (
    NAVIGATION_TERRAIN_OUTPUT_KIND,
    NAVIGATION_TERRAIN_TOOL_ID,
    assess_scout_navigation_terrain,
)


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"


def test_navigation_terrain_guided_only_for_missing_backup_positioning() -> None:
    result = assess_scout_navigation_terrain(
        PROJECT_ROOT,
        query="這條路地圖力需求很高，但我們沒有第二套定位備援，可以自己去嗎？",
        backup_positioning_available=False,
    )

    assert result["artifact_kind"] == NAVIGATION_TERRAIN_OUTPUT_KIND
    assert result["tool_id"] == NAVIGATION_TERRAIN_TOOL_ID
    assert result["answerability"] == "navigation_terrain_missing_user_readiness"
    assert result["decision"] == "GUIDED_ONLY"
    assert result["decision_output"]["decisionObjectSchema"] == "ContextualPermission"
    assert result["decision_output"]["decision"] == "GUIDED_ONLY"
    assert result["decision_output"]["allowed"] is False
    assert result["decision_output"]["firstLayer"]["decision"] == "不建議自主前往。"
    assert "不得自主出發" in result["decision_output"]["firstLayer"]["limit"]
    assert result["navigation_terrain"]["role"] == (
        "Navigation & Terrain Intelligence / Map Readiness"
    )
    assert result["navigation_terrain"]["positioning_readiness"][
        "backup_positioning_available"
    ] is False
    assert result["navigation_terrain"]["navigation_demand"]["demand_level"] == "high"
    assert result["debug_collection"]["writes_performed"] is False
    assert result["boundary"]["runtime_safety_truth"] is False


def test_navigation_terrain_guided_only_when_only_one_map_user() -> None:
    result = assess_scout_navigation_terrain(
        PROJECT_ROOT,
        query="我們只有一個人熟悉離線地圖，可以自主出發嗎？",
        offline_map_downloaded=True,
        gpx_loaded_on_device=True,
        contour_skill_confirmed=True,
        terrain_feature_skill_confirmed=True,
        retreat_direction_understood=True,
        backup_positioning_available=True,
        team_map_user_count=1,
    )

    assert result["decision"] == "GUIDED_ONLY"
    assert result["missing_fields"] == []
    assert "Confirm at least two team members can use offline maps and GPX." in result[
        "required_actions"
    ]
    assert result["decision_output"]["runtimeSafetyTruth"] is False
