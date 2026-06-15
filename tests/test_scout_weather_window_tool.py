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
    assert result["decision_output"]["decisionObjectSchema"] == "ContextualPermission"
    assert result["decision_output"]["decision"] == "DELAY"
    assert result["decision_output"]["firstLayer"]["decision"] == (
        "建議延後天氣判斷。"
    )
    assert result["decision_output"]["runtimeSafetyTruth"] is False
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


def test_weather_window_tool_delays_daylight_buffer_without_reviewed_sun_window() -> None:
    result = assess_scout_weather_window(
        PROJECT_ROOT,
        query="日照 buffer 是否下降？",
        limit=3,
    )

    assert result["answerability"] == "weather_placeholder_only"
    assert result["decision"] == "DELAY"
    status = result["daylight_buffer_status"]
    assert status["status"] == "daylight_buffer_missing_context"
    assert status["decision"] == "DELAY"
    assert status["missing_fields"] == ["reviewed_daylight_window", "current_time"]
    assert result["decision_output"]["firstLayer"]["decision"] == (
        "無法確認日照 buffer 是否下降。"
    )
    assert "仍有日照 buffer" in result["decision_output"]["firstLayer"]["limit"]
    assert "reviewed_daylight_window" in result["missing_fields"]
    assert "current_time" in result["missing_fields"]
    assert "日照 buffer 判斷" in result["field_answer"]
    assert result["decision_output"]["cost"]["daylightBufferStatus"]["status"] == (
        "daylight_buffer_missing_context"
    )
    assert result["decision_output"]["runtimeSafetyTruth"] is False


def test_weather_window_tool_computes_reviewed_daylight_buffer(
    tmp_path: Path,
) -> None:
    project_root = _write_daylight_buffer_project(tmp_path)

    result = assess_scout_weather_window(
        project_root,
        query="日照 buffer 是否下降？",
        current_time="2099-06-07T15:10:00+08:00",
        limit=3,
    )

    assert result["answerability"] == "route_weather_risk_available"
    assert result["decision"] == "CONDITIONAL_GO"
    status = result["daylight_buffer_status"]
    assert status["status"] == "daylight_buffer_available"
    assert status["minutes_until_sunset"] == 200.0
    assert status["route_daylight_buffer_minutes"] == 30.0
    assert result["decision_output"]["firstLayer"]["decision"] == (
        "日照 buffer 約 30 分鐘，偏低。"
    )
    assert "不得消耗停留或拍攝 buffer" in result["decision_output"][
        "firstLayer"
    ]["limit"]
    assert result["decision_output"]["cost"]["daylightBufferImpact"] == (
        "daylight buffer is low and must be reserved for CP re-check"
    )
    assert result["missing_fields"] == []
    assert "日照 buffer 判斷" in result["field_answer"]
    assert result["boundary"]["runtime_safety_truth"] is False


def test_weather_window_tool_uses_query_reported_recent_rain_conservatively() -> None:
    result = assess_scout_weather_window(
        PROJECT_ROOT,
        query="前 24 小時明顯降雨，溪水和崩塌風險是否升高？今天還能走嗎？",
        limit=3,
    )

    assert result["answerability"] == "weather_placeholder_only"
    assert result["decision"] == "CHANGE_PLAN"
    weather_decision = result["weather_to_decision"]
    assert weather_decision["decision"] == "CHANGE_PLAN"
    assert weather_decision["route_sensitive_weather_rule"]["rule"] == (
        "query_reported_previous_24h_rain_route_reassessment"
    )
    assert weather_decision["route_sensitive_weather_rule"]["query_reported"] is True
    assert "rain / wet terrain" in weather_decision["route_specific_conditions"]
    assert "terrain interaction" in weather_decision["route_specific_conditions"]
    assert "前 24 小時降雨" in weather_decision["main_reasons"][0]
    assert "不得把原路線視為已核准" in weather_decision["action_limit"]
    assert result["decision_output"]["firstLayer"]["decision"] == (
        "不建議照原計畫通過。"
    )
    assert "route_weather_package" in result["missing_fields"]
    assert "使用者回報條件下的候選保守決策" in result["field_answer"]
    assert result["boundary"]["runtime_safety_truth"] is False


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
    assert result["decision_output"]["decision"] == "CHANGE_PLAN"
    assert result["decision_output"]["firstLayer"]["decision"] == (
        "不建議照原計畫通過。"
    )
    assert result["decision_output"]["secondLayer"]["requiredConditions"]
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
    assert result["decision_output"]["decision"] == "NO_GO"
    assert result["decision_output"]["firstLayer"]["decision"] == (
        "不建議進入受天氣影響路段。"
    )
    assert result["weather_to_decision"]["decision"] == "NO_GO"
    assert result["weather_to_decision"]["weather_buffer_impact"] == (
        "weather buffer is not available for discretionary delay or exposure"
    )
    assert result["weather_to_decision"]["action_limit"] == (
        "此天氣窗口下不得進入已標記路段。"
    )
    assert "NO_GO" in result["field_answer"]


def test_weather_window_tool_delays_recent_rain_creek_crossing_without_experience(
    tmp_path: Path,
) -> None:
    project_root = _write_recent_rain_creek_project(tmp_path)

    result = assess_scout_weather_window(
        project_root,
        query="前 24 小時有降雨，這條路有兩處渡溪點且隊伍沒有渡溪經驗，可以照原計畫出發嗎？",
        limit=3,
    )

    assert result["answerability"] == "route_weather_risk_available"
    assert result["decision"] == "DELAY"
    assert result["weather_to_decision"]["decision"] == "DELAY"
    assert result["weather_to_decision"]["route_sensitive_weather_rule"] == {
        "rule": "previous_24h_rain_creek_crossing_no_experience",
        "creek_crossing_count": 2,
        "segment_ids": ["creek.crossing.1", "creek.crossing.2"],
    }
    assert "渡溪點" in result["weather_to_decision"]["main_reasons"][0]
    assert "缺少渡溪經驗" in result["weather_to_decision"][
        "main_reasons"
    ][1]
    assert "不得照原渡溪計畫出發" in result["weather_to_decision"]["action_limit"]
    assert "延期 48 小時" in result["weather_to_decision"]["next_action"]
    assert "低風險替代路線" in result["field_answer"]
    assert result["decision_output"]["decision"] == "DELAY"
    assert result["decision_output"]["runtimeSafetyTruth"] is False


def test_weather_window_tool_changes_plan_for_heat_exposure_water_margin(
    tmp_path: Path,
) -> None:
    project_root = _write_heat_exposure_project(tmp_path)

    result = assess_scout_weather_window(
        project_root,
        query="高溫曝曬，水量偏低，午後原路線還能走嗎？",
        limit=3,
    )

    assert result["answerability"] == "route_weather_risk_available"
    assert result["decision"] == "CHANGE_PLAN"
    weather_decision = result["weather_to_decision"]
    assert weather_decision["decision"] == "CHANGE_PLAN"
    assert weather_decision["route_sensitive_weather_rule"]["rule"] == (
        "high_heat_exposure_water_timing_review"
    )
    assert weather_decision["route_sensitive_weather_rule"]["segment_ids"] == [
        "heat.exposed.1"
    ]
    assert weather_decision["route_sensitive_weather_rule"][
        "max_temperature_or_heat_index_c"
    ] == 36.0
    assert weather_decision["route_sensitive_weather_rule"][
        "min_water_margin_liters"
    ] == 0.4
    assert "heat exposure / hydration demand" in weather_decision[
        "route_specific_conditions"
    ]
    assert "水量餘裕" in weather_decision["action_limit"]
    assert "較涼時段" in weather_decision["next_action"]
    assert "補足水量" in result["field_answer"]
    assert result["decision_output"]["decision"] == "CHANGE_PLAN"
    assert result["decision_output"]["runtimeSafetyTruth"] is False


def test_weather_window_tool_delays_forecast_source_disagreement(
    tmp_path: Path,
) -> None:
    project_root = _write_source_disagreement_project(tmp_path)

    result = assess_scout_weather_window(
        project_root,
        query="預報來源不一致，這個天氣窗可以照原計畫走嗎？",
        limit=3,
    )

    assert result["answerability"] == "route_weather_risk_available"
    assert result["decision"] == "DELAY"
    weather_decision = result["weather_to_decision"]
    assert weather_decision["decision"] == "DELAY"
    assert weather_decision["route_sensitive_weather_rule"]["rule"] == (
        "forecast_source_disagreement_conservative_review"
    )
    assert weather_decision["route_sensitive_weather_rule"]["segment_ids"] == [
        "forecast.conflict.1"
    ]
    assert weather_decision["route_sensitive_weather_rule"]["conflicting_sources"] == [
        "CWA",
        "mountain_forecast_partner",
    ]
    assert "forecast source disagreement / uncertainty" in weather_decision[
        "route_specific_conditions"
    ]
    assert "單一樂觀預報" in weather_decision["action_limit"]
    assert "來源仍不一致" in weather_decision["next_action"]
    assert result["decision_output"]["decision"] == "DELAY"
    assert result["decision_output"]["runtimeSafetyTruth"] is False


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


def _write_recent_rain_creek_project(tmp_path: Path) -> Path:
    project_root = tmp_path / "recent-rain-creek-project"
    (project_root / "outputs").mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "project_id": "recent_rain_creek_project",
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
                    "summary": "前 24 小時明顯降雨，溪流水位需重新確認",
                    "valid_from": "2099-06-07T08:00:00Z",
                    "valid_to": "2099-06-10T08:00:00Z",
                    "source_status": "server_side_fixture",
                },
                "segments": [
                    {
                        "segmentId": "creek.crossing.1",
                        "etaFrom": "2099-06-08T03:30:00Z",
                        "etaTo": "2099-06-08T03:50:00Z",
                        "terrainRisk": 0.48,
                        "weatherRisk": 0.44,
                        "finalRisk": 0.56,
                        "riskLevel": "MODERATE",
                        "factors": ["前 24 小時明顯降雨", "渡溪點", "隊伍沒有渡溪經驗"],
                        "message": "前 24 小時降雨後需重新確認溪流水位。",
                    },
                    {
                        "segmentId": "creek.crossing.2",
                        "etaFrom": "2099-06-08T05:20:00Z",
                        "etaTo": "2099-06-08T05:40:00Z",
                        "terrainRisk": 0.5,
                        "weatherRisk": 0.42,
                        "finalRisk": 0.55,
                        "riskLevel": "MODERATE",
                        "factors": ["前 24 小時明顯降雨", "渡溪點", "無渡溪經驗"],
                        "message": "第二處渡溪點受前 24 小時降雨影響。",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return project_root


def _write_heat_exposure_project(tmp_path: Path) -> Path:
    project_root = tmp_path / "heat-exposure-project"
    (project_root / "outputs").mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "project_id": "heat_exposure_project",
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
                    "summary": "午後高溫曝曬，水量與遮蔽需要重新規劃",
                    "valid_from": "2099-06-07T08:00:00Z",
                    "valid_to": "2099-06-10T08:00:00Z",
                    "source_status": "server_side_fixture",
                },
                "segments": [
                    {
                        "segmentId": "heat.exposed.1",
                        "etaFrom": "2099-06-08T04:30:00Z",
                        "etaTo": "2099-06-08T05:20:00Z",
                        "temperatureC": 33.5,
                        "heatIndexC": 36.0,
                        "shadeStatus": "limited",
                        "waterMarginLiters": 0.4,
                        "terrainRisk": 0.35,
                        "weatherRisk": 0.62,
                        "finalRisk": 0.62,
                        "riskLevel": "MODERATE",
                        "factors": ["高溫曝曬", "水量偏低", "無遮蔽", "午後炎熱時段"],
                        "message": "午後高溫與曝曬會放大中暑、補水與遮蔽需求。",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return project_root


def _write_source_disagreement_project(tmp_path: Path) -> Path:
    project_root = tmp_path / "source-disagreement-project"
    (project_root / "outputs").mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "project_id": "source_disagreement_project",
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
                "provider": "fixture_multi_source_weather",
                "authoritative_weather_computed": True,
                "external_api_calls_made": True,
                "human_review_required": False,
                "weather_window": {
                    "summary": "預報來源不一致：官方預報較保守，第三方模式較樂觀",
                    "valid_from": "2099-06-07T08:00:00Z",
                    "valid_to": "2099-06-10T08:00:00Z",
                    "source_status": "server_side_fixture",
                    "source_consistency": "forecast_source_disagreement",
                    "forecast_sources": [
                        {"provider": "CWA", "risk": "rain_after_noon"},
                        {"provider": "mountain_forecast_partner", "risk": "dry"},
                    ],
                },
                "segments": [
                    {
                        "segmentId": "forecast.conflict.1",
                        "etaFrom": "2099-06-08T04:30:00Z",
                        "etaTo": "2099-06-08T05:20:00Z",
                        "terrainRisk": 0.3,
                        "weatherRisk": 0.3,
                        "finalRisk": 0.36,
                        "riskLevel": "LOW",
                        "factors": ["預報來源不一致", "稜線通過時段", "人工審核前保守"],
                        "message": "同一時段來源不一致，不能採用較樂觀預報直接通過。",
                        "source": {
                            "provider": "CWA",
                            "source_consistency": "forecast_source_disagreement",
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return project_root


def _write_daylight_buffer_project(tmp_path: Path) -> Path:
    project_root = tmp_path / "daylight-buffer-project"
    (project_root / "outputs").mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "project_id": "daylight_buffer_project",
                "weather_daylight_evidence_ref": "outputs/weather_daylight_evidence.json",
                "planned_eta_ref": "outputs/planned_eta.json",
                "route_weather_package_ref": "outputs/route_weather_package.json",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (project_root / "outputs" / "weather_daylight_evidence.json").write_text(
        json.dumps(
            {
                "status": "candidate_only",
                "human_review_required": False,
                "daylight": {
                    "source_status": "reviewed",
                    "sunrise": "05:20",
                    "sunset": "18:30",
                    "timezone": "Asia/Taipei",
                },
                "validation": {"validation_status": "reviewed"},
                "weather_window": {
                    "summary": "reviewed daylight fixture",
                    "source_status": "server_side_fixture",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (project_root / "outputs" / "planned_eta.json").write_text(
        json.dumps(
            {
                "assumption": {
                    "target_eta": "2099-06-07T18:00:00+08:00",
                },
                "estimates": [
                    {
                        "eta": "2099-06-07T18:00:00+08:00",
                        "to_node_name": "target",
                    }
                ],
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
                "provider": "fixture_cwa_server_side_ingestor",
                "issued_at": "2099-06-07T08:00:00Z",
                "valid_from": "2099-06-07T08:00:00Z",
                "valid_to": "2099-06-08T08:00:00Z",
                "ttl_s": 86400,
                "human_review_required": False,
                "weather_window": {
                    "summary": "stable weather fixture",
                    "source_status": "server_side_fixture",
                },
                "segments": [
                    {
                        "segmentId": "low.weather.1",
                        "etaFrom": "2099-06-07T14:30:00+08:00",
                        "etaTo": "2099-06-07T15:00:00+08:00",
                        "terrainRisk": 0.1,
                        "weatherRisk": 0.1,
                        "finalRisk": 0.1,
                        "riskLevel": "LOW",
                        "factors": ["stable weather"],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return project_root
