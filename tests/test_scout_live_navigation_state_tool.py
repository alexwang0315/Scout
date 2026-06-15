from __future__ import annotations

from pathlib import Path

from scout_live_navigation_state_tool import (
    LIVE_NAVIGATION_STATE_OUTPUT_KIND,
    LIVE_NAVIGATION_STATE_TOOL_ID,
    assess_scout_live_navigation_state,
)


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"


def test_live_navigation_state_outputs_guidance_for_branch_check() -> None:
    result = assess_scout_live_navigation_state(
        PROJECT_ROOT,
        query="剛剛岔路我有走對嗎？現在要不要回主線？",
        **_complete_snapshot(nearest_route_distance_m=8),
    )

    assert result["artifact_kind"] == LIVE_NAVIGATION_STATE_OUTPUT_KIND
    assert result["tool_id"] == LIVE_NAVIGATION_STATE_TOOL_ID
    assert result["answerability"] == "snapshot_evidence_available"
    assert result["decision"] == "CONDITIONAL_GO"
    assert result["missing_fields"] == []
    assert result["navigation_terrain"]["role"] == "Navigation & Terrain Intelligence"
    assert result["navigation_terrain"]["location_fit"]["route_fit_status"] == (
        "on_route_corridor"
    )
    assert result["navigation_terrain"]["location_fit"]["position_quality_status"] == (
        "usable_quality"
    )
    assert "branch_or_mainline_check" in result["navigation_terrain"][
        "terrain_caution_flags"
    ]
    assert "地形導航判斷" in result["field_answer"]
    assert "runtime safety truth" in result["field_answer"]
    assert result["boundary"]["runtime_safety_truth"] is False
    assert result["boundary"]["live_hardware_read_performed"] is False


def test_live_navigation_state_blocks_downcut_from_candidate_snapshot() -> None:
    result = assess_scout_live_navigation_state(
        PROJECT_ROOT,
        query="我可以下切溪谷找路嗎？",
        **_complete_snapshot(nearest_route_distance_m=140),
    )

    assert result["answerability"] == "snapshot_evidence_available"
    assert result["decision"] == "NO_GO"
    assert result["navigation_decision"]["route_fit_status"] == "off_route_candidate"
    assert "downcut_or_stream_channel" in result["navigation_decision"][
        "terrain_caution_flags"
    ]
    assert "不要下切溪谷" in result["navigation_decision"]["next_action"]
    assert "NO_GO" in result["field_answer"]
    assert result["boundary"]["safety_api_called"] is False


def test_live_navigation_state_delays_without_position() -> None:
    result = assess_scout_live_navigation_state(
        PROJECT_ROOT,
        query="我現在是不是偏離路線？",
    )

    assert result["answerability"] == "snapshot_missing_required_fields"
    assert result["decision"] == "DELAY"
    assert "lat" in result["missing_fields"]
    assert "lon" in result["missing_fields"]
    assert result["navigation_decision"]["route_fit_status"] == "route_fit_unknown"
    assert result["route_query_plan"]["status"] == "insufficient_position"
    assert "地形導航判斷" in result["field_answer"]


def test_live_navigation_state_output_kind_constant() -> None:
    assert LIVE_NAVIGATION_STATE_OUTPUT_KIND == "scout_ai_live_navigation_state_tool_output"


def _complete_snapshot(**overrides):
    payload = {
        "observed_at": "2026-06-15T08:00:00+08:00",
        "lat": 24.0509,
        "lon": 121.216,
        "elevation_m": 2220,
        "source": "caller_fixture",
        "hdop": 0.9,
        "horizontal_accuracy_m": 5,
        "fix_quality": "3d",
        "satellite_count": 12,
        "max_cno_dbhz": 38,
        "heading_deg": 94,
        "course_deg": 96,
        "speed_mps": 0.82,
        "nearest_route_distance_m": 8,
        "route_progress_m": 1200,
        "nearest_cp_id": "cp.004",
        "ins_dr_source": "pdr_anchor",
        "confidence": 0.82,
        "uncertainty_m": 8,
        "last_anchor_at": "2026-06-15T07:58:00+08:00",
    }
    payload.update(overrides)
    return payload
