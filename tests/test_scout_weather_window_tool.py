from __future__ import annotations

import json
from pathlib import Path

from scout_weather_window_tool import (
    WEATHER_WINDOW_OUTPUT_KIND,
    WEATHER_WINDOW_TOOL_ID,
    assess_scout_weather_window,
)


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"


def test_weather_window_tool_reports_placeholder_missing_fresh_weather() -> None:
    result = assess_scout_weather_window(
        PROJECT_ROOT,
        query="明天午後雷雨是否要紮營?",
        limit=3,
    )

    assert result["tool_id"] == WEATHER_WINDOW_TOOL_ID
    assert result["status"] == "completed"
    assert result["answerability"] == "weather_placeholder_only"
    assert result["source_status"] == "candidate_only"
    assert result["decision"] == "DELAY"
    assert result["weather_to_decision"]["role"] == "Risk Sentinel / Weather-to-Decision"
    assert result["weather_to_decision"]["decision"] == "DELAY"
    assert result["weather_to_decision"]["candidate_only"] is True
    assert "天氣決策" in result["field_answer"]
    assert "DELAY" in result["field_answer"]
    assert result["result_count"] == 0
    assert result["risk_summary"]["segment_count"] == 0
    assert result["weather_window"]["source_status"] == "manual_placeholder"
    assert "provider" in result["missing_fields"]
    assert "ttl_s" in result["missing_fields"]
    assert "route_weather_package" in result["missing_fields"]
    assert any("manual placeholder" in warning for warning in result["warnings"])
    assert result["boundary"]["runtime_safety_truth"] is False
    assert result["boundary"]["client_cwa_api_key_allowed"] is False
    assert result["boundary"]["live_provider_fetch_performed"] is False


def test_weather_window_tool_reads_route_weather_package_and_emits_wx_alerts(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "weather-project"
    (project_root / "outputs").mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "project_id": "weather_project",
                "route_weather_package_ref": "outputs/route_weather_package.json",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (project_root / "outputs" / "route_weather_package.json").write_text(
        json.dumps(
            {
                "artifact_kind": "route_weather_package",
                "status": "candidate_only",
                "routeId": "fixture-route",
                "generatedAt": "2099-06-07T08:00:00Z",
                "issued_at": "2099-06-07T08:00:00Z",
                "valid_from": "2099-06-07T08:00:00Z",
                "valid_to": "2099-06-10T08:00:00Z",
                "validUntil": "2099-06-10T08:00:00Z",
                "ttl_s": 259200,
                "provider": "fixture_cwa_server_side_ingestor",
                "authoritative_weather_computed": True,
                "external_api_calls_made": True,
                "human_review_required": False,
                "weather_window": {
                    "summary": "午後雷雨風險偏高",
                    "valid_from": "2099-06-07T08:00:00Z",
                    "valid_to": "2099-06-10T08:00:00Z",
                    "source_status": "server_side_fixture",
                },
                "segments": [
                    {
                        "segmentId": 42,
                        "fromM": 3200,
                        "toM": 3450,
                        "etaFrom": "2099-06-08T04:30:00Z",
                        "etaTo": "2099-06-08T05:10:00Z",
                        "township": "仁愛鄉",
                        "terrainRisk": 0.72,
                        "weatherRisk": 0.66,
                        "finalRisk": 0.78,
                        "riskLevel": "HIGH",
                        "factors": ["稜線暴露", "降雨機率偏高", "低能見度可能"],
                        "message": "此路段有降雨與稜線暴露疊加。",
                    },
                    {
                        "segmentId": 41,
                        "fromM": 3000,
                        "toM": 3200,
                        "etaFrom": "2099-06-08T03:50:00Z",
                        "etaTo": "2099-06-08T04:30:00Z",
                        "terrainRisk": 0.2,
                        "weatherRisk": 0.1,
                        "riskLevel": "LOW",
                        "factors": ["林道路段"],
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = assess_scout_weather_window(
        project_root,
        query="哪些路段下雨後風險變高?",
        limit=2,
    )

    assert result["tool_id"] == WEATHER_WINDOW_TOOL_ID
    assert result["assessment_kind"] == "read_only_route_weather_window"
    assert result["answerability"] == "route_weather_risk_available"
    assert result["decision"] == "CHANGE_PLAN"
    assert result["weather_to_decision"]["decision"] == "CHANGE_PLAN"
    assert result["weather_to_decision"]["highest_risk_segment"]["segment_id"] == "42"
    assert "rain / wet terrain" in result["weather_to_decision"]["route_specific_conditions"]
    assert "天氣決策" in result["field_answer"]
    assert "CHANGE_PLAN" in result["field_answer"]
    assert result["missing_fields"] == []
    assert result["risk_summary"]["segment_count"] == 2
    assert result["risk_summary"]["max_weather_risk"] == 0.66
    assert result["risk_summary"]["risk_level_counts"]["HIGH"] == 1
    assert result["result_count"] == 2
    assert result["results"][0]["segment_id"] == "42"
    assert result["results"][0]["risk_level"] == "HIGH"
    assert result["wx_alerts"][0]["type"] == "WX_ALERT"
    assert result["wx_alerts"][0]["seg"] == "42"
    assert result["wx_alerts"][0]["risk"] == 3
    assert "RAIN" in result["wx_alerts"][0]["code"]
    assert result["source_report"][0]["status"] == "loaded"
    assert result["route_weather_package_schema"]["artifact_kind"] == (
        "route_weather_package"
    )
    assert result["boundary"]["runtime_safety_truth"] is False


def test_weather_window_tool_no_go_for_critical_weather_route_interaction(
    tmp_path: Path,
) -> None:
    project_root = _write_route_weather_project(
        tmp_path,
        risk_level="CRITICAL",
        final_risk=0.91,
        weather_risk=0.82,
    )

    result = assess_scout_weather_window(
        project_root,
        query="前方午後雷雨還能照原路線走嗎?",
        limit=2,
    )

    assert result["answerability"] == "route_weather_risk_available"
    assert result["decision"] == "NO_GO"
    assert result["weather_to_decision"]["decision"] == "NO_GO"
    assert result["weather_to_decision"]["weather_buffer_impact"] == (
        "weather buffer is not available for discretionary delay or exposure"
    )
    assert result["weather_to_decision"]["action_limit"] == (
        "Do not enter the flagged segment under this weather window."
    )
    assert "NO_GO" in result["field_answer"]


def test_weather_window_output_kind_is_registered_constant() -> None:
    assert WEATHER_WINDOW_OUTPUT_KIND == "scout_ai_weather_window_tool_output"


def _write_route_weather_project(
    tmp_path: Path,
    *,
    risk_level: str,
    final_risk: float,
    weather_risk: float,
) -> Path:
    project_root = tmp_path / "weather-critical-project"
    (project_root / "outputs").mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "project_id": "weather_critical_project",
                "route_weather_package_ref": "outputs/route_weather_package.json",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (project_root / "outputs" / "route_weather_package.json").write_text(
        json.dumps(
            {
                "artifact_kind": "route_weather_package",
                "status": "candidate_only",
                "routeId": "fixture-route",
                "generatedAt": "2099-06-07T08:00:00Z",
                "issued_at": "2099-06-07T08:00:00Z",
                "valid_from": "2099-06-07T08:00:00Z",
                "valid_to": "2099-06-10T08:00:00Z",
                "validUntil": "2099-06-10T08:00:00Z",
                "ttl_s": 259200,
                "provider": "fixture_cwa_server_side_ingestor",
                "authoritative_weather_computed": True,
                "external_api_calls_made": True,
                "human_review_required": False,
                "weather_window": {
                    "summary": "午後雷雨與強風疊加",
                    "valid_from": "2099-06-07T08:00:00Z",
                    "valid_to": "2099-06-10T08:00:00Z",
                    "source_status": "server_side_fixture",
                },
                "segments": [
                    {
                        "segmentId": "ridge.exposure",
                        "etaFrom": "2099-06-08T04:30:00Z",
                        "etaTo": "2099-06-08T05:10:00Z",
                        "terrainRisk": 0.88,
                        "weatherRisk": weather_risk,
                        "finalRisk": final_risk,
                        "riskLevel": risk_level,
                        "factors": ["午後雷雨", "稜線暴露", "強風", "低能見度可能"],
                        "message": "此路段有雷雨、強風與稜線暴露疊加。",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return project_root
