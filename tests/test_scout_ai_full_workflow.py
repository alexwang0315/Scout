import json
from pathlib import Path

from scout_agent_builtin_tools import run_builtin_tool
from scout_agent_tools import load_tool_manifest
from scout_ai_full_workflow import (
    ARTIFACT_KIND,
    ARTIFACT_VERSION,
    run_scout_ai_full_workflow,
)
from scout_ai_tool_planner import (
    ENERGY_VITALS_TOOL_ID,
    LIVE_NAVIGATION_STATE_TOOL_ID,
    NAVIGATION_TERRAIN_TOOL_ID,
    WEATHER_WINDOW_TOOL_ID,
)
from scout_pace_guardian_tool import PACE_GUARDIAN_TOOL_ID
from scout_equipment_resource_tool import EQUIPMENT_RESOURCE_TOOL_ID
from scout_team_status_tool import TEAM_STATUS_TOOL_ID
from scout_post_trip_review_tool import POST_TRIP_REVIEW_TOOL_ID
from scout_route_readiness_tool import ROUTE_READINESS_TOOL_ID
from scout_route_architecture_tool import ROUTE_ARCHITECTURE_TOOL_ID
from scout_route_context_tool import ROUTE_CONTEXT_TOOL_ID
from scout_contextual_permission_tool import CONTEXTUAL_PERMISSION_TOOL_ID
from scout_media_literacy_tool import MEDIA_LITERACY_TOOL_ID
from scout_survival_incident_playbook_tool import SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID
from scout_risk_score_tool import RISK_SCORE_TOOL_ID
from scout_terrain_score_tool import TERRAIN_SCORE_TOOL_ID
from scout_safety_boundary_tool import SAFETY_BOUNDARY_TOOL_ID
from scout_map_perception_tool import MAP_PERCEPTION_TOOL_ID
from scout_ins_dr_trace_tool import INS_DR_TRACE_TOOL_ID
from scout_workspace_search_tools import MAJOR_POINT_TOOL_ID


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
POST_ANALYSIS_ROOT = (
    ROOT / "tests" / "fixtures" / "post_analysis" / "chilai_nanhua_day1_post_analysis"
)
MANIFEST_PATH = (
    ROOT
    / "tools"
    / "scout_agent_tool_manifests"
    / "scout.ai.full_workflow.run.json"
)


def test_full_workflow_runs_risk_and_terrain_question_end_to_end() -> None:
    result = run_scout_ai_full_workflow(
        "危險地形在哪些位置?",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.artifact_kind == ARTIFACT_KIND
    assert result.artifact_version == ARTIFACT_VERSION
    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.discovery_plan["artifact_kind"] == "scout_ai_workflow_discovery_plan"
    assert result.evidence_collection["artifact_kind"] == "scout_ai_evidence_collection"
    assert result.answer_synthesis["artifact_kind"] == "scout_ai_answer_synthesis"
    assert [step.step_id for step in result.workflow_steps] == [
        "context_registry_and_tool_plan",
        "evidence_collection",
        "answer_synthesis",
    ]
    assert result.selected_tool_count == 2
    assert result.executed_tool_count == 2
    assert result.completed_tool_count == 2
    assert result.contract_gap_count == 0
    assert result.failed_tool_count == 0
    assert result.missing_evidence_count == 1
    assert result.workflow_policy.deterministic_tools_executed is True
    assert result.workflow_policy.context_registry_discovered is True
    assert result.workflow_policy.tool_plan_created is True
    assert result.workflow_policy.evidence_collection_performed is True
    assert result.workflow_policy.answer_synthesis_performed is True
    assert result.workflow_policy.model_provider_used is False
    assert result.workflow_policy.model_synthesis_performed is False
    assert result.boundary.runtime_safety_truth is False
    assert result.boundary.live_safety_api_calls_allowed is False

    source_ids = {source["tool_id"] for source in result.sources}
    assert RISK_SCORE_TOOL_ID in source_ids
    assert TERRAIN_SCORE_TOOL_ID in source_ids
    risk_source = next(
        source for source in result.sources if source["tool_id"] == RISK_SCORE_TOOL_ID
    )
    terrain_source = next(
        source for source in result.sources if source["tool_id"] == TERRAIN_SCORE_TOOL_ID
    )
    assert risk_source["top_result_summary"]["decision"] == "CHANGE_PLAN"
    assert risk_source["top_result_summary"]["decision_output"][
        "decisionObjectSchema"
    ] == "ContextualPermission"
    assert result.decision_output["answerSourceToolId"] == RISK_SCORE_TOOL_ID
    assert result.decision_output["decision"] == "CHANGE_PLAN"
    assert result.decision_output["firstLayer"]["decision"] == (
        "建議改變路線或通過策略。"
    )
    assert terrain_source["top_result_summary"]["decision"] == "DELAY"
    assert "terrain_score_results" in terrain_source["missing_fields"]
    assert "deterministic evidence was collected before synthesis" in result.answer
    assert "runtime safety truth" in result.answer
    assert any("no model provider was called" in item for item in result.limitations)


def test_full_workflow_uses_risk_sentinel_for_forward_high_risk_segment() -> None:
    result = run_scout_ai_full_workflow(
        "前方是否有高風險路段？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=6,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 2
    assert result.executed_tool_count == 2
    assert result.completed_tool_count == 2
    assert result.missing_evidence_count == 1
    source_ids = {source["tool_id"] for source in result.sources}
    assert RISK_SCORE_TOOL_ID in source_ids
    assert LIVE_NAVIGATION_STATE_TOOL_ID in source_ids
    assert CONTEXTUAL_PERMISSION_TOOL_ID not in source_ids
    nav_source = _workflow_source(result, LIVE_NAVIGATION_STATE_TOOL_ID)
    assert "lat" in nav_source["missing_fields"]
    assert result.decision_output["answerSourceToolId"] == RISK_SCORE_TOOL_ID
    assert result.decision_output["decision"] == "CHANGE_PLAN"
    assert result.decision_output["firstLayer"]["decision"] == (
        "建議改變路線或通過策略。"
    )
    assert "最高候選風險" in result.decision_output["firstLayer"]["reason"]
    assert "不建議進入曝露地形。" not in result.answer
    assert "runtime safety truth" in result.answer


def test_full_workflow_runs_weather_tool_and_reports_missing_fresh_evidence() -> None:
    result = run_scout_ai_full_workflow(
        "明天午後雷雨是否要紮營?",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count >= 1
    assert result.executed_tool_count >= 1
    assert result.completed_tool_count >= 1
    assert result.contract_gap_count == 0
    assert result.failed_tool_count == 0
    assert result.missing_evidence_count >= 1
    assert result.workflow_policy.deterministic_tools_executed is True
    assert result.workflow_policy.model_provider_used is False
    assert result.workflow_policy.model_synthesis_performed is False

    assert result.sources[0]["tool_id"] == WEATHER_WINDOW_TOOL_ID
    assert result.sources[0]["collection_status"] == "completed"
    assert result.sources[0]["top_result_summary"]["answerability"] == (
        "weather_placeholder_only"
    )
    assert "provider" in result.sources[0]["missing_fields"]
    assert "ttl_s" in result.sources[0]["missing_fields"]
    assert "route_weather_package" in result.sources[0]["missing_fields"]
    assert result.missing_evidence[0]["tool_id"] == WEATHER_WINDOW_TOOL_ID
    assert "provider" in result.missing_evidence[0]["missing_fields"]
    assert "ttl_s" in result.missing_evidence[0]["missing_fields"]
    assert "weather_placeholder_only" in result.answer
    assert "runtime safety truth" in result.answer


def test_full_workflow_surfaces_standard_six_power_coverage_overview() -> None:
    result = run_scout_ai_full_workflow(
        "請檢視 Scout 對六力的實作狀態：探索力、自信力、勇氣力、路線力、天氣力、地圖力。",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=8,
    )

    source_ids = {source["tool_id"] for source in result.sources}
    assert {
        ROUTE_CONTEXT_TOOL_ID,
        PACE_GUARDIAN_TOOL_ID,
        ROUTE_READINESS_TOOL_ID,
        CONTEXTUAL_PERMISSION_TOOL_ID,
        ROUTE_ARCHITECTURE_TOOL_ID,
        WEATHER_WINDOW_TOOL_ID,
        NAVIGATION_TERRAIN_TOOL_ID,
    }.issubset(source_ids)
    assert result.selected_tool_count == 7
    assert result.completed_tool_count == 7
    assert result.decision_output["answerSourceToolId"] == (
        "scout.ai.standard_six_power_overview.v0"
    )
    assert result.decision_output["decision"] == "GUIDED_ONLY"
    assert result.decision_output["dataConfidence"]["level"] == "medium"
    assert result.decision_output["dataConfidence"]["missingEvidenceCount"] == (
        result.missing_evidence_count
    )
    assert result.decision_output["runtimeSafetyTruth"] is False
    assert result.answer.startswith("六力覆蓋檢視：")
    for label in ("探索力", "自信力", "勇氣力", "路線力", "天氣力", "地圖力"):
        assert label in result.answer
    assert PACE_GUARDIAN_TOOL_ID in result.answer
    assert ROUTE_READINESS_TOOL_ID in result.answer
    assert "不輸出單一靜態分數" in result.answer
    assert "信心：中等" in result.answer
    assert "可以繼續前進" not in result.answer
    assert "地圖力判斷：建議" not in result.answer
    assert result.workflow_policy.model_provider_used is False
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_routes_scout_ai_meta_power_to_six_capability_tools() -> None:
    result = run_scout_ai_full_workflow(
        "Scout AI 力如何把六力轉成動態決策，而不是靜態分數表？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=8,
    )

    assert result.selected_tool_count == 7
    assert result.completed_tool_count == 7
    assert result.decision_output["answerSourceToolId"] == (
        "scout.ai.standard_six_power_overview.v0"
    )
    assert result.decision_output["decision"] == "GUIDED_ONLY"
    assert "tool planning -> evidence collection" in result.answer
    assert "deterministic answer synthesis" in result.answer
    assert "不輸出單一靜態分數" in result.answer
    assert "可以繼續前進" not in result.answer


def test_full_workflow_uses_daylight_buffer_weather_decision() -> None:
    result = run_scout_ai_full_workflow(
        "日照 buffer 是否下降？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 1
    assert result.completed_tool_count == 1
    weather = _workflow_source(result, WEATHER_WINDOW_TOOL_ID)
    assert weather["top_result_summary"]["decision"] == "DELAY"
    status = weather["top_result_summary"]["daylight_buffer_status"]
    assert status["status"] == "daylight_buffer_missing_context"
    assert status["missing_fields"] == ["reviewed_daylight_window", "current_time"]
    assert result.decision_output["answerSourceToolId"] == WEATHER_WINDOW_TOOL_ID
    assert result.decision_output["firstLayer"]["decision"] == (
        "無法確認日照 buffer 是否下降。"
    )
    assert "reviewed_daylight_window" in weather["missing_fields"]
    assert "current_time" in weather["missing_fields"]
    assert "日照 buffer 判斷" in result.answer
    assert result.decision_output["runtimeSafetyTruth"] is False
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_uses_query_reported_recent_rain_weather_decision() -> None:
    result = run_scout_ai_full_workflow(
        "前 24 小時明顯降雨，溪水和崩塌風險是否升高？今天還能走嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=5,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.failed_tool_count == 0
    weather = _workflow_source(result, WEATHER_WINDOW_TOOL_ID)
    assert weather["top_result_summary"]["decision"] == "CHANGE_PLAN"
    assert weather["top_result_summary"]["weather_to_decision"][
        "route_sensitive_weather_rule"
    ]["rule"] == "query_reported_previous_24h_rain_route_reassessment"
    assert "route_weather_package" in weather["missing_fields"]
    assert result.decision_output["answerSourceToolId"] == WEATHER_WINDOW_TOOL_ID
    assert result.decision_output["decision"] == "CHANGE_PLAN"
    assert result.decision_output["firstLayer"]["decision"] == (
        "不建議照原計畫通過。"
    )
    assert "前 24 小時降雨" in result.decision_output["firstLayer"]["reason"]
    assert "不得把原路線視為已核准" in result.decision_output["firstLayer"]["limit"]
    assert result.decision_output["runtimeSafetyTruth"] is False
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_preserves_energy_vitals_decision_output() -> None:
    result = run_scout_ai_full_workflow(
        "我現在心率偏高又很累，需要休息嗎?",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.sources[0]["tool_id"] == ENERGY_VITALS_TOOL_ID
    assert result.sources[0]["collection_status"] == "completed"
    summary = result.sources[0]["top_result_summary"]
    assert summary["decision"] == "DELAY"
    assert summary["decision_output"]["decisionObjectSchema"] == "ContextualPermission"
    assert result.decision_output["decisionObjectSchema"] == "ContextualPermission"
    assert result.decision_output["answerSourceToolId"] == ENERGY_VITALS_TOOL_ID
    assert result.decision_output["decision"] == "DELAY"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["firstLayer"]["decision"] == (
        "建議延後體能/穿戴判斷。"
    )
    assert result.decision_output["runtimeSafetyTruth"] is False
    answer_step = result.workflow_steps[-1]
    assert answer_step.summary["decision_output_schema"] == "ContextualPermission"
    assert answer_step.summary["decision_output_source_tool"] == ENERGY_VITALS_TOOL_ID


def test_full_workflow_runs_weather_to_decision_question(tmp_path: Path) -> None:
    project_root = _write_route_weather_project(tmp_path)

    result = run_scout_ai_full_workflow(
        "午後雷雨是否要改變計畫?",
        project_root=project_root,
        project_id="weather_decision_project",
        limit=3,
    )

    assert result.answerability == "evidence_available"
    assert result.selected_tool_count >= 1
    assert result.executed_tool_count >= 1
    assert result.completed_tool_count >= 1
    assert result.missing_evidence_count == 0
    assert result.sources[0]["tool_id"] == WEATHER_WINDOW_TOOL_ID
    assert result.sources[0]["top_result_summary"]["decision"] == "CHANGE_PLAN"
    assert result.sources[0]["top_result_summary"]["decision_output"][
        "decisionObjectSchema"
    ] == "ContextualPermission"
    assert result.sources[0]["top_result_summary"]["weather_to_decision"]["role"] == (
        "Risk Sentinel / Weather-to-Decision"
    )
    assert result.decision_output["answerSourceToolId"] == WEATHER_WINDOW_TOOL_ID
    assert result.decision_output["decision"] == "CHANGE_PLAN"
    assert result.decision_output["firstLayer"]["decision"] == (
        "不建議照原計畫通過。"
    )
    assert "天氣決策" in result.answer
    assert "CHANGE_PLAN" in result.answer
    assert "runtime safety truth" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_keeps_cold_exposure_risk_as_weather_decision() -> None:
    result = run_scout_ai_full_workflow(
        "強風低溫會不會讓稜線失溫風險升高？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=5,
    )

    source_ids = {source["tool_id"] for source in result.sources}
    assert WEATHER_WINDOW_TOOL_ID in source_ids
    assert NAVIGATION_TERRAIN_TOOL_ID in source_ids
    assert SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID not in source_ids
    weather = _workflow_source(result, WEATHER_WINDOW_TOOL_ID)
    assert weather["top_result_summary"]["decision"] == "DELAY"
    assert result.decision_output["answerSourceToolId"] == WEATHER_WINDOW_TOOL_ID
    assert result.decision_output["decision"] == "DELAY"
    assert "天氣決策" in result.answer
    assert "失溫" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_delays_recent_rain_creek_crossing_without_experience(
    tmp_path: Path,
) -> None:
    project_root = _write_recent_rain_creek_project(tmp_path)

    result = run_scout_ai_full_workflow(
        "前 24 小時有降雨，這條路有兩處渡溪點且隊伍沒有渡溪經驗，天氣決策怎麼看？",
        project_root=project_root,
        project_id="recent_rain_creek_project",
        limit=3,
    )

    weather = _workflow_source(result, WEATHER_WINDOW_TOOL_ID)
    assert weather["top_result_summary"]["decision"] == "DELAY"
    rule = weather["top_result_summary"]["weather_to_decision"][
        "route_sensitive_weather_rule"
    ]
    assert rule["creek_crossing_count"] == 2
    assert result.decision_output["answerSourceToolId"] == WEATHER_WINDOW_TOOL_ID
    assert result.decision_output["decision"] == "DELAY"
    assert "延期 48 小時" in result.answer
    assert "低風險替代路線" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_changes_plan_for_heat_exposure_weather(
    tmp_path: Path,
) -> None:
    project_root = _write_heat_exposure_project(tmp_path)

    result = run_scout_ai_full_workflow(
        "高溫曝曬，天氣決策怎麼看？",
        project_root=project_root,
        project_id="heat_exposure_project",
        limit=3,
    )

    assert result.answerability == "evidence_available"
    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.missing_evidence_count == 0
    weather = _workflow_source(result, WEATHER_WINDOW_TOOL_ID)
    assert weather["top_result_summary"]["decision"] == "CHANGE_PLAN"
    rule = weather["top_result_summary"]["weather_to_decision"][
        "route_sensitive_weather_rule"
    ]
    assert rule["rule"] == "high_heat_exposure_water_timing_review"
    assert rule["segment_ids"] == ["heat.exposed.1"]
    assert result.decision_output["answerSourceToolId"] == WEATHER_WINDOW_TOOL_ID
    assert result.decision_output["decision"] == "CHANGE_PLAN"
    assert "水量餘裕" in result.decision_output["firstLayer"]["limit"]
    assert "補足水量" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_delays_forecast_source_disagreement_weather(
    tmp_path: Path,
) -> None:
    project_root = _write_source_disagreement_project(tmp_path)

    result = run_scout_ai_full_workflow(
        "預報來源不一致，天氣決策怎麼看？",
        project_root=project_root,
        project_id="source_disagreement_project",
        limit=3,
    )

    assert result.answerability == "evidence_available"
    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.missing_evidence_count == 0
    weather = _workflow_source(result, WEATHER_WINDOW_TOOL_ID)
    assert weather["top_result_summary"]["decision"] == "DELAY"
    rule = weather["top_result_summary"]["weather_to_decision"][
        "route_sensitive_weather_rule"
    ]
    assert rule["rule"] == "forecast_source_disagreement_conservative_review"
    assert rule["segment_ids"] == ["forecast.conflict.1"]
    assert result.decision_output["answerSourceToolId"] == WEATHER_WINDOW_TOOL_ID
    assert result.decision_output["decision"] == "DELAY"
    assert "單一樂觀預報" in result.decision_output["firstLayer"]["limit"]
    assert "來源仍不一致" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_runs_map_perception_question() -> None:
    result = run_scout_ai_full_workflow(
        "CP001 附近有沒有標註?",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "evidence_available"
    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.missing_evidence_count == 0
    assert result.sources[0]["tool_id"] == MAP_PERCEPTION_TOOL_ID
    summary = result.sources[0]["top_result_summary"]
    assert summary["decision"] == "CONDITIONAL_GO"
    assert summary["decision_output"]["decisionObjectSchema"] == "ContextualPermission"
    assert summary["map_perception"]["role"] == (
        "Navigation & Terrain Intelligence / Map Perception"
    )
    assert result.decision_output["answerSourceToolId"] == MAP_PERCEPTION_TOOL_ID
    assert result.decision_output["decision"] == "CONDITIONAL_GO"
    assert result.decision_output["firstLayer"]["decision"] == "可作為候選地圖參考。"
    answer_step = result.workflow_steps[-1]
    assert answer_step.summary["decision_output_schema"] == "ContextualPermission"
    assert answer_step.summary["decision_output_source_tool"] == MAP_PERCEPTION_TOOL_ID
    assert "地圖判讀決策：CONDITIONAL_GO" in result.answer
    assert "不是 runtime safety truth" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_preserves_contextual_permission_decision_object() -> None:
    result = run_scout_ai_full_workflow(
        "我可以在這裡停下來拍一段影片嗎?",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 6
    assert result.executed_tool_count == 6
    assert result.completed_tool_count == 6
    assert result.missing_evidence_count == 4
    _assert_on_route_micro_decision_support_sources(result)
    contextual = _workflow_source(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    summary = contextual["top_result_summary"]
    assert summary["decision"] == "NO_GO"
    assert summary["decision_object"] == summary["contextual_permission"]
    assert summary["decision_output"]["decisionObjectSchema"] == "ContextualPermission"
    assert summary["decision_output"]["firstLayer"]["decision"] == "不建議拍影片。"
    assert result.decision_output["decisionObjectSchema"] == "ContextualPermission"
    assert result.decision_output["answerSourceToolId"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.decision_output["action"] == "film"
    assert result.decision_output["decision"] == "NO_GO"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["firstLayer"]["decision"] == "不建議拍影片。"
    answer_step = result.workflow_steps[-1]
    assert answer_step.summary["decision_output_schema"] == "ContextualPermission"
    assert answer_step.summary["decision_output_source_tool"] == (
        CONTEXTUAL_PERMISSION_TOOL_ID
    )
    assert result.answer.startswith("[決策] 不建議拍影片。")
    assert not result.answer.startswith("Scout AI read-only answer draft")
    assert "[決策] 不建議拍影片。" in result.answer
    assert "runtime safety truth" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_allows_bounded_tripod_permission() -> None:
    result = run_scout_ai_full_workflow(
        "現在 2026-06-07T13:36:00+08:00，安全 buffer 還有 21 分鐘，可以架腳架 4 分鐘嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 6
    assert result.executed_tool_count == 6
    assert result.completed_tool_count == 6
    assert result.missing_evidence_count == 3
    _assert_on_route_micro_decision_support_sources(result)
    contextual = _workflow_source(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    summary = contextual["top_result_summary"]
    assert summary["action"] == "tripod"
    assert summary["decision"] == "CONDITIONAL_GO"
    assert summary["allowed"] is True
    assert summary["max_duration_minutes"] == 4
    assert result.decision_output["answerSourceToolId"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.decision_output["action"] == "tripod"
    assert result.decision_output["firstLayer"]["decision"] == "可以，最多 4 分鐘。"
    assert "收起腳架" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_prices_extra_stop_time_against_buffer() -> None:
    result = run_scout_ai_full_workflow(
        "現在 2026-06-07T13:36:00+08:00，安全 buffer 還有 21 分鐘，"
        "如果多停 10 分鐘，代價是什麼？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 6
    assert result.executed_tool_count == 6
    assert result.completed_tool_count == 6
    assert result.missing_evidence_count == 3
    _assert_on_route_micro_decision_support_sources(result)
    assert result.failed_tool_count == 0
    source = _workflow_source(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert source["top_result_summary"]["action"] == "stop"
    assert source["top_result_summary"]["decision"] == "CONDITIONAL_GO"
    assert source["top_result_summary"]["allowed"] is True
    assert source["top_result_summary"]["max_duration_minutes"] == 10
    assert source["top_result_summary"]["leave_by"] == (
        "2026-06-07T13:46:00+08:00"
    )
    assert result.decision_output["answerSourceToolId"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.decision_output["action"] == "stop"
    assert result.decision_output["decision"] == "CONDITIONAL_GO"
    assert result.decision_output["allowed"] is True
    assert result.decision_output["maxDurationMinutes"] == 10
    assert result.decision_output["leaveBy"] == "2026-06-07T13:46:00+08:00"
    assert result.decision_output["cost"]["timeBufferChangeMinutes"] == -10
    assert result.decision_output["firstLayer"]["decision"] == "可以，最多 10 分鐘。"
    answer_step = result.workflow_steps[-1]
    assert answer_step.summary["decision_output_schema"] == "ContextualPermission"
    assert answer_step.summary["decision_output_source_tool"] == (
        CONTEXTUAL_PERMISSION_TOOL_ID
    )
    assert "消耗 10 分鐘 buffer" in result.answer
    assert "2026-06-07T13:46:00+08:00 前離開" in result.answer
    assert result.decision_output["runtimeSafetyTruth"] is False
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_routes_generic_leave_by_to_contextual_stop() -> None:
    result = run_scout_ai_full_workflow(
        "現在可以做嗎？什麼時間前必須離開？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 6
    assert result.executed_tool_count == 6
    assert result.completed_tool_count == 6
    assert result.missing_evidence_count == 4
    _assert_on_route_micro_decision_support_sources(result)
    assert result.failed_tool_count == 0
    source = _workflow_source(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert source["top_result_summary"]["action"] == "stop"
    assert source["top_result_summary"]["decision"] == "NO_GO"
    assert source["missing_fields"] == ["remaining_safety_buffer_minutes"]
    assert result.decision_output["answerSourceToolId"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.decision_output["action"] == "stop"
    assert result.decision_output["decision"] == "NO_GO"
    assert result.decision_output["firstLayer"]["decision"] == "不建議停留。"
    assert result.decision_output["runtimeSafetyTruth"] is False
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_reports_requested_stop_cost_when_buffer_missing() -> None:
    result = run_scout_ai_full_workflow(
        "如果多停 10 分鐘，代價是什麼？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 6
    assert result.executed_tool_count == 6
    assert result.completed_tool_count == 6
    assert result.missing_evidence_count == 4
    _assert_on_route_micro_decision_support_sources(result)
    assert result.failed_tool_count == 0
    source = _workflow_source(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert source["top_result_summary"]["action"] == "stop"
    assert source["top_result_summary"]["decision"] == "NO_GO"
    assert source["missing_fields"] == ["remaining_safety_buffer_minutes"]
    assert result.decision_output["answerSourceToolId"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.decision_output["action"] == "stop"
    assert result.decision_output["decision"] == "NO_GO"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["cost"]["timeBufferChangeMinutes"] == -10
    assert result.decision_output["firstLayer"]["decision"] == "不建議停留。"
    assert "使用者要求約 10 分鐘" in result.decision_output["firstLayer"]["reason"]
    assert "不能計算代價或授權" in result.decision_output["firstLayer"]["reason"]
    assert any(
        "使用者要求時間約 10 分鐘" in detail
        for detail in result.decision_output["secondLayer"]["details"]
    )
    assert "消耗約 10 分鐘時間 buffer" in result.answer
    assert result.decision_output["runtimeSafetyTruth"] is False
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_prices_film_stop_budget_phrase_with_next_cp() -> None:
    result = run_scout_ai_full_workflow(
        "前方 CP4 約 42 分鐘，安全 buffer 剩 21 分鐘，可以停 6 分鐘拍影片嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 6
    assert result.executed_tool_count == 6
    assert result.completed_tool_count == 6
    assert result.missing_evidence_count == 3
    _assert_on_route_micro_decision_support_sources(result)
    source = _workflow_source(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert source["top_result_summary"]["action"] == "film"
    assert source["top_result_summary"]["decision"] == "CONDITIONAL_GO"
    assert source["top_result_summary"]["allowed"] is True
    assert source["top_result_summary"]["max_duration_minutes"] == 6
    assert result.decision_output["answerSourceToolId"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.decision_output["action"] == "film"
    assert result.decision_output["decision"] == "CONDITIONAL_GO"
    assert result.decision_output["allowed"] is True
    assert result.decision_output["maxDurationMinutes"] == 6
    assert result.decision_output["cost"]["timeBufferChangeMinutes"] == -6
    assert result.decision_output["firstLayer"]["decision"] == "可以，最多 6 分鐘。"
    assert "消耗 6 分鐘 buffer" in result.answer
    assert "前往 CP4" in result.answer
    assert result.decision_output["runtimeSafetyTruth"] is False
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_uses_local_clock_for_stop_deadline() -> None:
    result = run_scout_ai_full_workflow(
        "現在 13:36，安全 buffer 還有 21 分鐘，如果多停 10 分鐘，代價是什麼？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 6
    assert result.executed_tool_count == 6
    assert result.completed_tool_count == 6
    assert result.missing_evidence_count == 3
    _assert_on_route_micro_decision_support_sources(result)
    assert result.decision_output["answerSourceToolId"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.decision_output["action"] == "stop"
    assert result.decision_output["decision"] == "CONDITIONAL_GO"
    assert result.decision_output["maxDurationMinutes"] == 10
    assert result.decision_output["leaveBy"] == "13:46"
    assert result.decision_output["cost"]["timeBufferChangeMinutes"] == -10
    assert "最多 10 分鐘，13:46 前離開" in (
        result.decision_output["firstLayer"]["limit"]
    )
    assert "路線走廊" in result.decision_output["firstLayer"]["limit"]
    assert "13:46 前離開" in result.answer
    assert result.decision_output["runtimeSafetyTruth"] is False
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_routes_abstract_buffer_cost_to_contextual_permission() -> None:
    result = run_scout_ai_full_workflow(
        "這個選擇會消耗什麼 buffer？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 6
    assert result.executed_tool_count == 6
    assert result.completed_tool_count == 6
    assert result.missing_evidence_count == 4
    _assert_on_route_micro_decision_support_sources(result)
    contextual = _workflow_source(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert contextual["top_result_summary"]["action"] == "stop"
    assert contextual["top_result_summary"]["decision"] == "NO_GO"
    assert contextual["missing_fields"] == ["remaining_safety_buffer_minutes"]
    assert result.decision_output["answerSourceToolId"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.decision_output["action"] == "stop"
    assert result.decision_output["decision"] == "NO_GO"
    assert "remaining_safety_buffer_minutes" in result.answer
    assert "不要消耗停留或改線 buffer" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_treats_fog_photo_as_wait_permission() -> None:
    result = run_scout_ai_full_workflow(
        "可以等霧散再拍照嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=6,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 6
    assert result.executed_tool_count == 6
    assert result.completed_tool_count == 6
    assert result.missing_evidence_count == 4
    _assert_on_route_micro_decision_support_sources(result)
    weather = _workflow_source(result, WEATHER_WINDOW_TOOL_ID)
    contextual = _workflow_source(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert weather["top_result_summary"]["decision"] == "DELAY"
    assert contextual["top_result_summary"]["action"] == "wait"
    assert contextual["top_result_summary"]["decision"] == "NO_GO"
    assert contextual["missing_fields"] == ["remaining_safety_buffer_minutes"]
    assert result.decision_output["answerSourceToolId"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.decision_output["action"] == "wait"
    assert result.decision_output["decision"] == "NO_GO"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["firstLayer"]["decision"] == "不建議等待。"
    assert "不建議等待" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_prioritizes_weather_delay_over_generic_continue() -> None:
    result = run_scout_ai_full_workflow(
        "日落快到了，還能繼續推進嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 6
    assert result.executed_tool_count == 6
    assert result.completed_tool_count == 6
    assert result.missing_evidence_count == 3
    _assert_on_route_micro_decision_support_sources(result)
    assert result.failed_tool_count == 0
    weather = _workflow_source(result, WEATHER_WINDOW_TOOL_ID)
    contextual = _workflow_source(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert weather["top_result_summary"]["decision"] == "DELAY"
    assert contextual["top_result_summary"]["action"] == "continue"
    assert contextual["top_result_summary"]["decision"] == "GO"
    assert result.decision_output["answerSourceToolId"] == WEATHER_WINDOW_TOOL_ID
    assert result.decision_output["decision"] == "DELAY"
    assert result.decision_output["firstLayer"]["decision"] == (
        "無法確認日照 buffer 是否下降。"
    )
    assert "reviewed daylight window" in result.decision_output["firstLayer"]["reason"]
    assert result.decision_output["runtimeSafetyTruth"] is False
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_allows_bounded_teammate_wait() -> None:
    result = run_scout_ai_full_workflow(
        "現在 2026-06-07T13:50:00+08:00，安全 buffer 還有 18 分鐘，可以等隊友 5 分鐘嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 6
    assert result.executed_tool_count == 6
    assert result.completed_tool_count == 6
    assert result.missing_evidence_count == 3
    _assert_on_route_micro_decision_support_sources(result)
    contextual = _workflow_source(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    summary = contextual["top_result_summary"]
    assert summary["action"] == "wait_teammate"
    assert summary["decision"] == "CONDITIONAL_GO"
    assert summary["allowed"] is True
    assert summary["max_duration_minutes"] == 5
    assert result.decision_output["answerSourceToolId"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.decision_output["action"] == "wait_teammate"
    assert result.decision_output["firstLayer"]["decision"] == "可以，最多 5 分鐘。"
    assert "未會合" in result.answer
    assert "隊伍狀態檢查" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_blocks_wind_exposed_lunch() -> None:
    result = run_scout_ai_full_workflow(
        "這裡是風口，我們可以在這裡吃午餐嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=6,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 6
    assert result.executed_tool_count == 6
    assert result.completed_tool_count == 6
    assert result.missing_evidence_count == 4
    _assert_on_route_micro_decision_support_sources(result)
    weather = _workflow_source(result, WEATHER_WINDOW_TOOL_ID)
    contextual = _workflow_source(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert weather["top_result_summary"]["decision"] == "DELAY"
    assert contextual["top_result_summary"]["action"] == "lunch"
    assert contextual["top_result_summary"]["decision"] == "NO_GO"
    assert contextual["top_result_summary"]["allowed"] is False
    assert contextual["missing_fields"] == ["remaining_safety_buffer_minutes"]
    assert result.decision_output["answerSourceToolId"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.decision_output["action"] == "lunch"
    assert result.decision_output["decision"] == "NO_GO"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["firstLayer"]["decision"] == "不建議吃午餐。"
    assert "風口" in result.decision_output["firstLayer"]["reason"]
    assert "較避風 CP" in result.decision_output["firstLayer"]["nextStep"]
    assert "不建議吃午餐" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_surfaces_lunch_alternate_cp_and_minutes() -> None:
    result = run_scout_ai_full_workflow(
        "這裡是風口，前方 CP3 約 18 分鐘且較避風，安全 buffer 還有 45 分鐘，"
        "我們可以在這裡吃午餐嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=6,
    )

    contextual = _workflow_source(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert contextual["top_result_summary"]["action"] == "lunch"
    assert contextual["top_result_summary"]["decision"] == "NO_GO"
    assert contextual["top_result_summary"]["allowed"] is False
    assert contextual["top_result_summary"]["minutes_to_next_cp"] == 18.0
    assert contextual["missing_fields"] == []
    assert "約 18 分鐘到 CP3" in result.decision_output["firstLayer"]["nextStep"]
    assert "約 18 分鐘到 CP3" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_escalates_stream_surge_crossing() -> None:
    result = run_scout_ai_full_workflow(
        "前方溪水暴漲，還能過溪嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=6,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 6
    assert result.executed_tool_count == 6
    assert result.completed_tool_count == 6
    assert result.missing_evidence_count == 4
    _assert_on_route_micro_decision_support_sources(result)
    weather = _workflow_source(result, WEATHER_WINDOW_TOOL_ID)
    contextual = _workflow_source(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert weather["top_result_summary"]["decision"] == "DELAY"
    assert contextual["top_result_summary"]["action"] == "cross_stream"
    assert contextual["top_result_summary"]["decision"] == "ESCALATE"
    assert contextual["top_result_summary"]["allowed"] is False
    assert contextual["missing_fields"] == ["remaining_safety_buffer_minutes"]
    assert result.decision_output["answerSourceToolId"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.decision_output["action"] == "cross_stream"
    assert result.decision_output["decision"] == "ESCALATE"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["firstLayer"]["decision"] == (
        "需要升級處理，不建議渡溪。"
    )
    assert "高後果情境" in result.decision_output["firstLayer"]["reason"]
    assert "停止進入溪谷" in result.decision_output["firstLayer"]["nextStep"]
    assert "需要升級處理，不建議渡溪" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_escalates_unknown_creek_level_without_experience() -> None:
    result = run_scout_ai_full_workflow(
        "目前無法確認溪流水位，且我們沒有渡溪經驗，可以進入溪谷嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=6,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.failed_tool_count == 0
    contextual = _workflow_source(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert contextual["top_result_summary"]["action"] == "cross_stream"
    assert contextual["top_result_summary"]["decision"] == "ESCALATE"
    assert contextual["top_result_summary"]["allowed"] is False
    assert contextual["missing_fields"] == ["remaining_safety_buffer_minutes"]
    assert result.decision_output["answerSourceToolId"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.decision_output["action"] == "cross_stream"
    assert result.decision_output["decision"] == "ESCALATE"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["firstLayer"]["decision"] == (
        "需要升級處理，不建議渡溪。"
    )
    assert "高後果情境" in result.decision_output["firstLayer"]["reason"]
    assert "停止進入溪谷" in result.decision_output["firstLayer"]["nextStep"]
    assert "需要升級處理，不建議渡溪" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_blocks_split_team_summit_question() -> None:
    result = run_scout_ai_full_workflow(
        "可以讓走得快的人先去山頂嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 6
    assert result.executed_tool_count == 6
    assert result.completed_tool_count == 6
    assert result.missing_evidence_count == 3
    _assert_on_route_micro_decision_support_sources(result)
    contextual = _workflow_source(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    summary = contextual["top_result_summary"]
    assert summary["action"] == "split_team"
    assert summary["decision"] == "NO_GO"
    assert summary["allowed"] is False
    assert result.decision_output["answerSourceToolId"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.decision_output["action"] == "split_team"
    assert result.decision_output["decision"] == "NO_GO"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["firstLayer"]["decision"] == "不建議分隊。"
    assert "保持隊伍完整" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_uses_rain_gear_micro_decision() -> None:
    result = run_scout_ai_full_workflow(
        "前面下雨了，要不要穿雨衣？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 7
    assert result.executed_tool_count == 7
    assert result.completed_tool_count == 7
    assert result.missing_evidence_count == 4
    _assert_on_route_micro_decision_support_sources(result)
    contextual = _workflow_source(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    summary = contextual["top_result_summary"]
    assert summary["action"] == "wear_rain_gear"
    assert summary["decision"] == "GO"
    assert summary["allowed"] is True
    assert summary["max_duration_minutes"] == 2
    assert summary["location_constraint"] == (
        "就地安全位置；不離開步道內側或既有路線走廊"
    )
    assert result.decision_output["answerSourceToolId"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.decision_output["action"] == "wear_rain_gear"
    assert result.decision_output["decision"] == "GO"
    assert result.decision_output["allowed"] is True
    assert result.decision_output["maxDurationMinutes"] == 2
    assert result.decision_output["locationConstraint"] == (
        "就地安全位置；不離開步道內側或既有路線走廊"
    )
    assert result.decision_output["firstLayer"]["decision"] == (
        "可以穿雨具，最多 2 分鐘。"
    )
    assert "最多 2 分鐘" in result.decision_output["firstLayer"]["limit"]
    assert "就地安全位置" in result.decision_output["firstLayer"]["limit"]
    assert "就地穿上雨具" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_blocks_shortcut_reroute_question() -> None:
    result = run_scout_ai_full_workflow(
        "這個岔路可以切嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=5,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 6
    assert result.executed_tool_count == 6
    assert result.completed_tool_count == 6
    assert result.missing_evidence_count == 4
    _assert_on_route_micro_decision_support_sources(result)
    contextual = _workflow_source(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    summary = contextual["top_result_summary"]
    assert summary["action"] == "reroute"
    assert summary["decision"] == "NO_GO"
    assert summary["allowed"] is False
    nav_source = _workflow_source(result, LIVE_NAVIGATION_STATE_TOOL_ID)
    assert "lat" in nav_source["missing_fields"]
    assert result.decision_output["answerSourceToolId"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.decision_output["action"] == "reroute"
    assert result.decision_output["decision"] == "NO_GO"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["firstLayer"]["decision"] == "不建議改線。"
    assert "臨時切岔路或改線" in result.decision_output["firstLayer"]["reason"]
    assert "已審核替代路線" in result.decision_output["firstLayer"]["reason"]
    assert "不要臨時改線" in result.answer
    assert "只走已審核替代路線" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_blocks_unreviewed_retreat_window_continue() -> None:
    result = run_scout_ai_full_workflow(
        "撤退窗口快失去了，現在能不能繼續？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 6
    assert result.executed_tool_count == 6
    assert result.completed_tool_count == 6
    assert result.missing_evidence_count == 3
    _assert_on_route_micro_decision_support_sources(result)
    contextual = _workflow_source(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    summary = contextual["top_result_summary"]
    assert summary["action"] == "continue"
    assert summary["decision"] == "NO_GO"
    assert summary["allowed"] is False
    assert result.decision_output["answerSourceToolId"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.decision_output["action"] == "continue"
    assert result.decision_output["decision"] == "NO_GO"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["firstLayer"]["decision"] == "不建議繼續前進。"
    assert "不能授權快速通過" in result.decision_output["firstLayer"]["reason"]
    assert "最近安全 CP" in result.decision_output["firstLayer"]["nextStep"]
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_blocks_unreviewed_continue_forward() -> None:
    result = run_scout_ai_full_workflow(
        "我們現在可以繼續前進嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 6
    assert result.executed_tool_count == 6
    assert result.completed_tool_count == 6
    assert result.missing_evidence_count == 3
    _assert_on_route_micro_decision_support_sources(result)
    contextual = _workflow_source(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    summary = contextual["top_result_summary"]
    assert summary["action"] == "continue"
    assert summary["decision"] == "NO_GO"
    assert summary["allowed"] is False
    assert result.decision_output["answerSourceToolId"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.decision_output["action"] == "continue"
    assert result.decision_output["decision"] == "NO_GO"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["firstLayer"]["decision"] == "不建議繼續前進。"
    assert "繼續推進" in result.decision_output["firstLayer"]["reason"]
    assert "最近安全 CP" in result.decision_output["firstLayer"]["nextStep"]
    assert "退回最近安全 CP" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_uses_direct_retreat_micro_decision() -> None:
    result = run_scout_ai_full_workflow(
        "隊友很累，要不要直接撤退？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=5,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 7
    assert result.executed_tool_count == 7
    assert result.completed_tool_count == 7
    assert result.missing_evidence_count == 4
    _assert_on_route_micro_decision_support_sources(result)
    contextual = _workflow_source(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    summary = contextual["top_result_summary"]
    assert summary["action"] == "retreat"
    assert summary["decision"] == "GO"
    assert summary["allowed"] is True
    assert summary["max_duration_minutes"] == 0
    assert "最近安全點" in summary["location_constraint"]
    pace_source = _workflow_source(result, PACE_GUARDIAN_TOOL_ID)
    assert pace_source["missing_fields"] == ["member_pace_profile"]
    assert result.decision_output["answerSourceToolId"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.decision_output["action"] == "retreat"
    assert result.decision_output["decision"] == "GO"
    assert result.decision_output["allowed"] is True
    assert result.decision_output["maxDurationMinutes"] == 0
    assert "最近安全點" in result.decision_output["locationConstraint"]
    assert result.decision_output["firstLayer"]["decision"] == "建議撤退。"
    assert "立即開始撤退" in result.decision_output["firstLayer"]["limit"]
    assert "不授權停留" in result.decision_output["firstLayer"]["limit"]
    assert "保持隊伍完整" in result.decision_output["firstLayer"]["limit"]
    assert "建議撤退" in result.answer
    assert "保持隊伍完整" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_uses_micro_decision_for_weather_fatigue_retreat() -> None:
    result = run_scout_ai_full_workflow(
        "天氣變差且隊友疲勞，是否需要撤退？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=5,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 7
    assert result.executed_tool_count == 7
    assert result.completed_tool_count == 7
    assert result.missing_evidence_count == 4
    _assert_on_route_micro_decision_support_sources(result)
    contextual = _workflow_source(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    summary = contextual["top_result_summary"]
    assert summary["action"] == "retreat"
    assert summary["decision"] == "GO"
    assert summary["allowed"] is True
    assert summary["max_duration_minutes"] == 0
    assert "最近安全點" in summary["location_constraint"]
    assert _workflow_source(result, WEATHER_WINDOW_TOOL_ID)["missing_fields"]
    assert _workflow_source(result, ENERGY_VITALS_TOOL_ID)["missing_fields"]
    assert _workflow_source(result, PACE_GUARDIAN_TOOL_ID)["missing_fields"] == [
        "member_pace_profile"
    ]
    assert result.decision_output["answerSourceToolId"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.decision_output["action"] == "retreat"
    assert result.decision_output["decision"] == "GO"
    assert result.decision_output["allowed"] is True
    assert result.decision_output["maxDurationMinutes"] == 0
    assert "最近安全點" in result.decision_output["locationConstraint"]
    assert result.decision_output["firstLayer"]["decision"] == "建議撤退。"
    assert "立即開始撤退" in result.decision_output["firstLayer"]["limit"]
    assert "保持隊伍完整" in result.decision_output["firstLayer"]["limit"]
    assert "建議撤退" in result.answer
    assert "開始撤退" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_runs_route_context_experience_guide_question() -> None:
    result = run_scout_ai_full_workflow(
        "下一個觀察點在哪？哪裡適合拍攝大景？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    assert result.answerability == "evidence_available"
    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.contract_gap_count == 0
    assert result.failed_tool_count == 0
    assert result.missing_evidence_count == 0
    assert result.sources[0]["tool_id"] == ROUTE_CONTEXT_TOOL_ID
    assert result.sources[0]["top_result_summary"]["decision"] == "CONDITIONAL_GO"
    assert result.sources[0]["top_result_summary"]["decision_output"][
        "decisionObjectSchema"
    ] == "ContextualPermission"
    assert result.sources[0]["top_result_summary"]["route_context"]["role"] == (
        "Experience Guide"
    )
    assert result.decision_output["answerSourceToolId"] == ROUTE_CONTEXT_TOOL_ID
    assert result.decision_output["decision"] == "CONDITIONAL_GO"
    assert result.decision_output["firstLayer"]["decision"] == "可作為候選觀察點。"
    assert "不是停留授權" in result.decision_output["firstLayer"]["limit"]
    assert "候選路線脈絡" in result.answer
    assert "contextual permission" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_routes_standard_natural_context_layer() -> None:
    questions = [
        "這段林相變化有什麼可以觀察？",
        "這條路線有哪些自然、人文或地形脈絡？",
        "哪裡適合停下來看風景，不要只衝山頂？",
    ]

    for question in questions:
        result = run_scout_ai_full_workflow(
            question,
            project_root=PROJECT_ROOT,
            project_id="chilai_nanhua_day1",
            limit=4,
        )

        assert result.answerability == "evidence_available"
        assert result.selected_tool_count == 1
        assert result.executed_tool_count == 1
        assert result.completed_tool_count == 1
        assert result.contract_gap_count == 0
        assert result.failed_tool_count == 0
        assert result.missing_evidence_count == 0
        assert result.sources[0]["tool_id"] == ROUTE_CONTEXT_TOOL_ID
        assert result.sources[0]["top_result_summary"]["decision"] == "CONDITIONAL_GO"
        assert result.sources[0]["top_result_summary"]["route_context"]["role"] == (
            "Experience Guide"
        )
        assert result.decision_output["answerSourceToolId"] == ROUTE_CONTEXT_TOOL_ID
        assert result.decision_output["decision"] == "CONDITIONAL_GO"
        assert "候選路線脈絡" in result.answer
        assert "Experience Guide 候選" in result.answer
        assert result.boundary.runtime_safety_truth is False


def test_full_workflow_runs_pace_guardian_team_pace_question(tmp_path: Path) -> None:
    project_root = _write_team_pace_project(tmp_path)

    result = run_scout_ai_full_workflow(
        "隊伍腳程是否能準時抵達下一個 CP？最慢者需要前移午餐點嗎？",
        project_root=project_root,
        project_id="team_pace_project",
        limit=4,
    )

    assert result.answerability == "evidence_available"
    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.contract_gap_count == 0
    assert result.failed_tool_count == 0
    assert result.missing_evidence_count == 0
    assert result.sources[0]["tool_id"] == PACE_GUARDIAN_TOOL_ID
    assert result.sources[0]["top_result_summary"]["pace_guardian"]["role"] == (
        "Pace Guardian"
    )
    assert result.sources[0]["top_result_summary"]["decision_output"][
        "decisionObjectSchema"
    ] == "ContextualPermission"
    assert result.sources[0]["top_result_summary"]["team_pace_fit"]["slowest_member"][
        "label"
    ] == "New teammate"
    assert result.decision_output["answerSourceToolId"] == PACE_GUARDIAN_TOOL_ID
    assert result.decision_output["decision"] == "CHANGE_PLAN"
    assert result.decision_output["firstLayer"]["decision"] == (
        "不建議照原計畫推進。"
    )
    assert "不要用平均腳程" in result.decision_output["firstLayer"]["limit"]
    assert "腳程守門員" in result.answer
    assert "不使用平均腳程" in result.answer
    assert "runtime safety truth" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_surfaces_scout_pace_coefficient(tmp_path: Path) -> None:
    project_root = _write_pace_coefficient_project(tmp_path)

    result = run_scout_ai_full_workflow(
        "最慢者的 Scout Pace Coefficient 在碎石下坡和負重下還能照原計畫嗎？",
        project_root=project_root,
        project_id="pace_coefficient_project",
        limit=4,
    )

    source = _workflow_source(result, PACE_GUARDIAN_TOOL_ID)
    assert source["top_result_summary"]["decision"] == "CONDITIONAL_GO"
    coefficients = source["top_result_summary"]["team_pace_fit"][
        "scout_pace_coefficients"
    ]
    assert coefficients[0]["label"] == "Slowest member"
    assert coefficients[0]["technical_terrain_slowdown_ratio"] == 0.35
    assert "Scout Pace Coefficient" in result.answer
    assert "技術地形降速率" in result.answer
    assert "負重" in result.answer
    assert result.decision_output["answerSourceToolId"] == PACE_GUARDIAN_TOOL_ID
    assert result.decision_output["cost"]["paceCoefficientImpact"].startswith(
        "Scout Pace Coefficient considered"
    )
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_routes_average_pace_bias_to_pace_guardian() -> None:
    result = run_scout_ai_full_workflow(
        "我們平均腳程還可以，可以用平均速度估嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.missing_evidence_count == 1
    assert result.sources[0]["tool_id"] == PACE_GUARDIAN_TOOL_ID
    assert result.sources[0]["top_result_summary"]["decision"] == "NO_GO"
    assert result.sources[0]["top_result_summary"]["pace_guardian"][
        "average_pace_used"
    ] is False
    assert result.decision_output["answerSourceToolId"] == PACE_GUARDIAN_TOOL_ID
    assert result.decision_output["decision"] == "NO_GO"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["firstLayer"]["decision"] == (
        "不建議用目前腳程資料繼續判斷。"
    )
    assert "不要用平均腳程" in result.decision_output["firstLayer"]["limit"]
    assert "member_pace_profile" in result.sources[0]["missing_fields"]
    answer_step = result.workflow_steps[-1]
    assert answer_step.summary["decision_output_source_tool"] == PACE_GUARDIAN_TOOL_ID
    assert "腳程守門員" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_uses_query_reported_vulnerable_member_conditions() -> None:
    result = run_scout_ai_full_workflow(
        "有人膝蓋痛又睡眠不足，還能照原計畫嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.failed_tool_count == 0
    pace = _workflow_source(result, PACE_GUARDIAN_TOOL_ID)
    assert pace["top_result_summary"]["decision"] == "NO_GO"
    assert pace["top_result_summary"]["team_pace_fit"][
        "query_reported_vulnerabilities"
    ] == ["knee_pain", "sleep_debt"]
    assert pace["missing_fields"] == ["member_pace_profile"]
    assert result.decision_output["answerSourceToolId"] == PACE_GUARDIAN_TOOL_ID
    assert result.decision_output["decision"] == "NO_GO"
    assert result.decision_output["firstLayer"]["decision"] == (
        "不建議照原計畫推進。"
    )
    assert "膝蓋痛" in result.decision_output["firstLayer"]["reason"]
    assert "睡眠不足" in result.answer
    assert result.decision_output["runtimeSafetyTruth"] is False
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_uses_query_reported_rest_rhythm_mismatch() -> None:
    result = run_scout_ai_full_workflow(
        "隊伍休息節奏不一致，是否需要縮短行程？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.failed_tool_count == 0
    pace = _workflow_source(result, PACE_GUARDIAN_TOOL_ID)
    assert pace["top_result_summary"]["team_pace_fit"][
        "query_reported_vulnerabilities"
    ] == ["rest_rhythm_mismatch"]
    assert result.decision_output["answerSourceToolId"] == PACE_GUARDIAN_TOOL_ID
    assert result.decision_output["decision"] == "NO_GO"
    assert result.decision_output["firstLayer"]["decision"] == (
        "不建議照原計畫推進。"
    )
    assert "休息節奏不一致" in result.decision_output["firstLayer"]["reason"]
    assert result.decision_output["runtimeSafetyTruth"] is False
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_routes_ahead_of_plan_pace_to_pace_guardian() -> None:
    result = run_scout_ai_full_workflow(
        "目前比計畫快 20 分鐘，可以繼續照原節奏嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.missing_evidence_count == 1
    pace = _workflow_source(result, PACE_GUARDIAN_TOOL_ID)
    assert pace["top_result_summary"]["decision"] == "NO_GO"
    assert pace["top_result_summary"]["schedule_pressure"]["current_delay_minutes"] == -20.0
    assert result.decision_output["answerSourceToolId"] == PACE_GUARDIAN_TOOL_ID
    assert result.decision_output["decision"] == "NO_GO"
    assert result.decision_output["cost"]["scheduleDelayMinutes"] == -20.0
    assert result.decision_output["cost"]["scheduleAheadMinutes"] == 20.0
    assert "比計畫快約 20 分鐘" in result.decision_output["firstLayer"]["reason"]
    assert "不是免費 buffer" in result.decision_output["firstLayer"]["reason"]
    answer_step = result.workflow_steps[-1]
    assert answer_step.summary["decision_output_source_tool"] == PACE_GUARDIAN_TOOL_ID
    assert "腳程守門員" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_prioritizes_pace_guardian_for_delayed_summit() -> None:
    result = run_scout_ai_full_workflow(
        "我們晚了 30 分鐘，還可以繼續攻頂嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=6,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 6
    assert result.executed_tool_count == 6
    assert result.completed_tool_count == 6
    assert result.missing_evidence_count == 4
    _assert_on_route_micro_decision_support_sources(result)
    pace = _workflow_source(result, PACE_GUARDIAN_TOOL_ID)
    contextual = _workflow_source(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert pace["top_result_summary"]["decision"] == "NO_GO"
    assert pace["top_result_summary"]["schedule_pressure"]["current_delay_minutes"] == 30.0
    assert contextual["top_result_summary"]["action"] == "summit"
    assert result.decision_output["answerSourceToolId"] == PACE_GUARDIAN_TOOL_ID
    assert result.decision_output["action"] == "pace_adjustment"
    assert result.decision_output["decision"] == "NO_GO"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["cost"]["scheduleDelayMinutes"] == 30.0
    assert result.decision_output["firstLayer"]["decision"] == "不建議繼續攻頂。"
    assert "目前已落後約 30 分鐘" in result.decision_output["firstLayer"]["reason"]
    first_answer_block = result.answer.split(" Collected evidence: ")[0]
    assert first_answer_block.count("[決策]") == 1
    assert "[決策] 不建議攻頂。" not in first_answer_block
    assert "腳程守門員" in result.answer
    assert "contextual permission" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_prioritizes_pace_for_slowed_continue_question() -> None:
    result = run_scout_ai_full_workflow(
        "走到這裡比預計慢 25 分鐘，還能繼續嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=6,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 6
    assert result.executed_tool_count == 6
    assert result.completed_tool_count == 6
    assert result.missing_evidence_count == 3
    _assert_on_route_micro_decision_support_sources(result)
    pace = _workflow_source(result, PACE_GUARDIAN_TOOL_ID)
    contextual = _workflow_source(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert pace["top_result_summary"]["decision"] == "NO_GO"
    assert pace["top_result_summary"]["schedule_pressure"]["current_delay_minutes"] == 25.0
    assert contextual["top_result_summary"]["action"] == "continue"
    assert contextual["top_result_summary"]["decision"] == "GO"
    assert result.decision_output["answerSourceToolId"] == PACE_GUARDIAN_TOOL_ID
    assert result.decision_output["action"] == "pace_adjustment"
    assert result.decision_output["decision"] == "NO_GO"
    assert result.decision_output["cost"]["scheduleDelayMinutes"] == 25.0
    assert result.answer.startswith("[決策] 不建議用目前腳程資料繼續判斷。")
    assert not result.answer.startswith("Scout AI read-only answer draft")
    first_answer_block = result.answer.split(" Collected evidence: ")[0]
    assert "腳程守門員" in first_answer_block
    assert "[決策] 可以繼續前進。" not in first_answer_block
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_routes_time_to_summit_to_micro_decision() -> None:
    result = run_scout_ai_full_workflow(
        "現在是否還有時間攻頂？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=6,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 6
    assert result.executed_tool_count == 6
    assert result.completed_tool_count == 6
    assert result.missing_evidence_count == 4
    _assert_on_route_micro_decision_support_sources(result)
    pace = _workflow_source(result, PACE_GUARDIAN_TOOL_ID)
    contextual = _workflow_source(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert pace["top_result_summary"]["decision"] == "NO_GO"
    assert contextual["top_result_summary"]["action"] == "summit"
    assert contextual["top_result_summary"]["decision"] == "NO_GO"
    assert result.decision_output["answerSourceToolId"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.decision_output["action"] == "summit"
    assert result.decision_output["decision"] == "NO_GO"
    assert result.decision_output["firstLayer"]["decision"] == "不建議攻頂。"
    assert "不要繼續攻頂" in result.decision_output["firstLayer"]["nextStep"]
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_blocks_daylight_summit_pressure() -> None:
    result = run_scout_ai_full_workflow(
        "我們快摸黑了，但山頂只差一點，可以趕一下攻頂嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=6,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 7
    assert result.executed_tool_count == 7
    assert result.completed_tool_count == 7
    assert result.missing_evidence_count == 5
    _assert_on_route_micro_decision_support_sources(result)
    assert result.failed_tool_count == 0
    weather = _workflow_source(result, WEATHER_WINDOW_TOOL_ID)
    media = _workflow_source(result, MEDIA_LITERACY_TOOL_ID)
    contextual = _workflow_source(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert weather["top_result_summary"]["decision"] == "DELAY"
    assert "route_weather_package" in weather["missing_fields"]
    bias_ids = {
        item["bias_id"]
        for item in media["top_result_summary"]["media_bias_analysis"][
            "detected_biases"
        ]
    }
    assert "sunk_cost_bias" in bias_ids
    assert media["top_result_summary"]["action"] == "summit"
    assert media["top_result_summary"]["decision"] == "NO_GO"
    assert contextual["top_result_summary"]["action"] == "summit"
    assert contextual["top_result_summary"]["decision"] == "NO_GO"
    assert "remaining_safety_buffer_minutes" in contextual["missing_fields"]
    assert result.decision_output["answerSourceToolId"] == MEDIA_LITERACY_TOOL_ID
    assert result.decision_output["action"] == "summit"
    assert result.decision_output["decision"] == "NO_GO"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["firstLayer"]["decision"] == (
        "不建議因為已經投入時間而繼續前進或攻頂。"
    )
    assert "已投入時間" in result.decision_output["firstLayer"]["limit"]
    assert "日照 buffer 判斷" in result.answer
    assert "sunk_cost_bias" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_runs_route_architecture_cp_graph_question() -> None:
    result = run_scout_ai_full_workflow(
        "下一個撤退點在哪？這條路線難點在哪？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    assert result.answerability == "evidence_available"
    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.contract_gap_count == 0
    assert result.failed_tool_count == 0
    assert result.missing_evidence_count == 0
    assert result.sources[0]["tool_id"] == ROUTE_ARCHITECTURE_TOOL_ID
    assert result.sources[0]["top_result_summary"]["decision"] == "CONDITIONAL_GO"
    assert result.sources[0]["top_result_summary"]["decision_output"][
        "decisionObjectSchema"
    ] == "ContextualPermission"
    assert result.sources[0]["top_result_summary"]["route_architecture"]["role"] == (
        "Route Architecture Intelligence"
    )
    assert result.sources[0]["top_result_summary"]["cp_graph"]["node_count"] == 124
    assert result.decision_output["answerSourceToolId"] == ROUTE_ARCHITECTURE_TOOL_ID
    assert result.decision_output["decision"] == "CONDITIONAL_GO"
    assert result.decision_output["firstLayer"]["decision"] == (
        "可依 CP Graph 推進，但必須保留折返窗口。"
    )
    assert "路線結構判斷" in result.answer
    assert "CP Graph" in result.answer
    assert "通過折返點前，先使用已審核或候選撤退路線返回入口" in result.answer
    assert "Return to entry" not in result.answer
    assert "return to entry using" not in result.answer
    assert "turn back at" not in result.answer
    assert "shorten route or split" not in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_explains_route_forgiveness_and_retreat_options() -> None:
    result = run_scout_ai_full_workflow(
        "走錯或變天時還有退路嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    assert result.answerability == "evidence_available"
    assert result.selected_tool_count == 1
    assert result.sources[0]["tool_id"] == ROUTE_ARCHITECTURE_TOOL_ID
    assert result.decision_output["answerSourceToolId"] == ROUTE_ARCHITECTURE_TOOL_ID
    assert result.decision_output["decision"] == "CONDITIONAL_GO"
    assert "seg.050" in result.decision_output["firstLayer"]["reason"]
    assert "候選撤退路線" in result.answer
    assert "雲海保線所" in result.answer
    assert "路段內無撤退點" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_explains_where_to_retreat_after_wrong_turn() -> None:
    result = run_scout_ai_full_workflow(
        "如果走錯要往哪裡退？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    assert result.answerability == "evidence_available"
    assert result.selected_tool_count == 1
    assert result.sources[0]["tool_id"] == ROUTE_ARCHITECTURE_TOOL_ID
    assert result.decision_output["answerSourceToolId"] == ROUTE_ARCHITECTURE_TOOL_ID
    assert result.decision_output["decision"] == "CONDITIONAL_GO"
    assert "候選撤退路線" in result.answer
    assert "雲海保線所" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_uses_route_architecture_for_turnback_status() -> None:
    result = run_scout_ai_full_workflow(
        "現在是不是折返點？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.contract_gap_count == 0
    assert result.failed_tool_count == 0
    assert result.missing_evidence_count == 1
    assert result.sources[0]["tool_id"] == ROUTE_ARCHITECTURE_TOOL_ID
    assert result.sources[0]["missing_fields"] == ["current_cp_id", "current_time"]
    assert result.sources[0]["top_result_summary"]["answerability"] == (
        "route_architecture_missing_current_context"
    )
    assert result.sources[0]["top_result_summary"]["decision"] == "DELAY"
    assert result.decision_output["answerSourceToolId"] == ROUTE_ARCHITECTURE_TOOL_ID
    assert result.decision_output["decision"] == "DELAY"
    assert result.decision_output["firstLayer"]["decision"] == (
        "無法確認現在是否為折返點。"
    )
    assert "current_cp_id、current_time" in result.answer
    assert "雲海保線所" in result.decision_output["firstLayer"]["reason"]
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_delays_retreat_point_status_without_current_context() -> None:
    result = run_scout_ai_full_workflow(
        "現在是不是撤退點？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.contract_gap_count == 0
    assert result.failed_tool_count == 0
    assert result.missing_evidence_count == 1
    assert result.sources[0]["tool_id"] == ROUTE_ARCHITECTURE_TOOL_ID
    assert result.sources[0]["missing_fields"] == ["current_cp_id", "current_time"]
    assert result.sources[0]["top_result_summary"]["answerability"] == (
        "route_architecture_missing_current_context"
    )
    assert result.sources[0]["top_result_summary"]["decision"] == "DELAY"
    assert result.decision_output["answerSourceToolId"] == ROUTE_ARCHITECTURE_TOOL_ID
    assert result.decision_output["decision"] == "DELAY"
    assert result.decision_output["firstLayer"]["decision"] == (
        "無法確認現在是否為撤退點。"
    )
    assert "current_cp_id、current_time" in result.answer
    assert "雲海保線所" in result.decision_output["firstLayer"]["reason"]
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_delays_retreat_window_status_without_current_context() -> None:
    result = run_scout_ai_full_workflow(
        "撤退點是否即將失去？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.contract_gap_count == 0
    assert result.failed_tool_count == 0
    assert result.missing_evidence_count == 1
    assert result.sources[0]["tool_id"] == ROUTE_ARCHITECTURE_TOOL_ID
    assert result.sources[0]["missing_fields"] == ["current_cp_id", "current_time"]
    assert result.sources[0]["top_result_summary"]["answerability"] == (
        "route_architecture_missing_current_context"
    )
    assert result.sources[0]["top_result_summary"]["decision"] == "DELAY"
    assert result.decision_output["answerSourceToolId"] == ROUTE_ARCHITECTURE_TOOL_ID
    assert result.decision_output["decision"] == "DELAY"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["firstLayer"]["decision"] == (
        "無法確認撤退點是否即將失去。"
    )
    assert "current_cp_id、current_time" in result.answer
    assert "撤退窗口仍可用" in result.decision_output["firstLayer"]["limit"]
    assert "不能確認撤退點是否即將失去" in result.answer
    assert "可依 CP Graph 推進" not in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_delays_cp_schedule_delta_without_current_context() -> None:
    result = run_scout_ai_full_workflow(
        "我們現在比計畫晚多少？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.contract_gap_count == 0
    assert result.failed_tool_count == 0
    assert result.missing_evidence_count == 1
    route = _workflow_source(result, ROUTE_ARCHITECTURE_TOOL_ID)
    assert route["missing_fields"] == ["current_cp_id", "current_time"]
    assert route["top_result_summary"]["decision"] == "DELAY"
    assert route["top_result_summary"]["route_decision"]["first_layer_decision"] == (
        "無法確認與計畫 CP 通過時間的差距。"
    )
    assert result.decision_output["answerSourceToolId"] == ROUTE_ARCHITECTURE_TOOL_ID
    assert result.decision_output["decision"] == "DELAY"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["firstLayer"]["decision"] == (
        "無法確認與計畫 CP 通過時間的差距。"
    )
    assert "current_cp_id、current_time" in result.answer
    assert "不能確認與計畫 CP 通過時間差距" in result.answer
    assert "No registry-backed Scout AI tool" not in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_prioritizes_route_architecture_for_position_schedule_delta() -> (
    None
):
    result = run_scout_ai_full_workflow(
        "目前位置和計畫 CP 通過時間差多少？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=6,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    source_by_tool = {source["tool_id"]: source for source in result.sources}
    assert ROUTE_ARCHITECTURE_TOOL_ID in source_by_tool
    route = source_by_tool[ROUTE_ARCHITECTURE_TOOL_ID]
    assert route["missing_fields"] == ["current_cp_id", "current_time"]
    assert result.decision_output["answerSourceToolId"] == ROUTE_ARCHITECTURE_TOOL_ID
    assert result.decision_output["decision"] == "DELAY"
    assert result.decision_output["firstLayer"]["decision"] == (
        "無法確認與計畫 CP 通過時間的差距。"
    )
    assert "不能確認與計畫 CP 通過時間差距" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_detects_natural_turnback_current_context() -> None:
    result = run_scout_ai_full_workflow(
        "現在 2013-10-08T15:10:00+08:00 在雲海保線所，現在是不是折返點？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    assert result.answerability == "evidence_available"
    assert result.failed_tool_count == 0
    source_by_tool = {source["tool_id"]: source for source in result.sources}
    route = source_by_tool[ROUTE_ARCHITECTURE_TOOL_ID]
    assert route["missing_fields"] == []
    assert route["top_result_summary"]["answerability"] == (
        "route_architecture_available"
    )
    assert route["top_result_summary"]["decision"] == "CHANGE_PLAN"
    assert result.decision_output["answerSourceToolId"] == ROUTE_ARCHITECTURE_TOOL_ID
    assert result.decision_output["decision"] == "CHANGE_PLAN"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["firstLayer"]["decision"] == (
        "不建議照原路線往後段推進。"
    )
    assert "目前時間已到或超過折返 ETA" in result.decision_output["firstLayer"][
        "reason"
    ]
    assert "目前 CP 符合計畫折返 checkpoint" in result.decision_output["firstLayer"][
        "reason"
    ]
    assert result.decision_output["runtimeSafetyTruth"] is False
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_detects_local_clock_turnback_context() -> None:
    result = run_scout_ai_full_workflow(
        "現在 15:10 在雲海保線所，現在是不是折返點？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    assert result.answerability == "evidence_available"
    assert result.failed_tool_count == 0
    source_by_tool = {source["tool_id"]: source for source in result.sources}
    route = source_by_tool[ROUTE_ARCHITECTURE_TOOL_ID]
    assert route["missing_fields"] == []
    assert route["top_result_summary"]["decision"] == "CHANGE_PLAN"
    assert result.decision_output["answerSourceToolId"] == ROUTE_ARCHITECTURE_TOOL_ID
    assert result.decision_output["decision"] == "CHANGE_PLAN"
    assert "目前時間已到或超過折返 ETA" in result.decision_output["firstLayer"][
        "reason"
    ]
    assert "目前 CP 符合計畫折返 checkpoint" in result.decision_output["firstLayer"][
        "reason"
    ]
    assert result.decision_output["runtimeSafetyTruth"] is False
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_uses_route_architecture_for_missed_checkpoint_deadline() -> None:
    result = run_scout_ai_full_workflow(
        "11:30 未抵達 CP4 是否要折返？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    assert result.answerability == "evidence_available"
    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.contract_gap_count == 0
    assert result.failed_tool_count == 0
    assert result.missing_evidence_count == 0
    source_by_tool = {source["tool_id"]: source for source in result.sources}
    route = source_by_tool[ROUTE_ARCHITECTURE_TOOL_ID]
    assert route["missing_fields"] == []
    assert route["top_result_summary"]["answerability"] == (
        "route_architecture_available"
    )
    assert route["top_result_summary"]["decision"] == "CHANGE_PLAN"
    assert route["top_result_summary"]["route_decision"]["target_checkpoint"] == "CP4"
    assert route["top_result_summary"]["route_decision"]["checkpoint_deadline"] == "11:30"
    assert result.decision_output["answerSourceToolId"] == ROUTE_ARCHITECTURE_TOOL_ID
    assert result.decision_output["decision"] == "CHANGE_PLAN"
    assert result.decision_output["firstLayer"]["decision"] == (
        "不建議錯過 checkpoint deadline 後繼續原計畫。"
    )
    assert "目標 checkpoint CP4" in result.decision_output["firstLayer"]["reason"]
    assert result.decision_output["runtimeSafetyTruth"] is False
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_uses_route_architecture_for_hut_checkin_pressure() -> None:
    result = run_scout_ai_full_workflow(
        "山屋報到時間快到了，是否需要改計畫？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    assert result.answerability == "evidence_available"
    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.contract_gap_count == 0
    assert result.failed_tool_count == 0
    assert result.missing_evidence_count == 0
    source_by_tool = {source["tool_id"]: source for source in result.sources}
    route = source_by_tool[ROUTE_ARCHITECTURE_TOOL_ID]
    assert route["missing_fields"] == []
    assert route["top_result_summary"]["answerability"] == (
        "route_architecture_available"
    )
    assert route["top_result_summary"]["decision"] == "CHANGE_PLAN"
    assert route["top_result_summary"]["route_decision"]["deadline_pressure"] == (
        "hut_checkin"
    )
    assert result.decision_output["answerSourceToolId"] == ROUTE_ARCHITECTURE_TOOL_ID
    assert result.decision_output["decision"] == "CHANGE_PLAN"
    assert result.decision_output["firstLayer"]["decision"] == (
        "建議改變計畫，先處理外部 deadline 壓力。"
    )
    assert "山屋報到" in result.decision_output["firstLayer"]["reason"]
    assert result.decision_output["runtimeSafetyTruth"] is False
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_prioritizes_transport_deadline_pressure() -> None:
    result = run_scout_ai_full_workflow(
        "交通末班車快趕不上了，還能照原計畫嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count >= 2
    assert result.failed_tool_count == 0
    assert result.missing_evidence_count >= 1
    source_by_tool = {source["tool_id"]: source for source in result.sources}
    route = source_by_tool[ROUTE_ARCHITECTURE_TOOL_ID]
    assert route["top_result_summary"]["decision"] == "CHANGE_PLAN"
    assert route["top_result_summary"]["route_decision"]["deadline_pressure"] == (
        "transport_last_service"
    )
    assert result.decision_output["answerSourceToolId"] == ROUTE_ARCHITECTURE_TOOL_ID
    assert result.decision_output["decision"] == "CHANGE_PLAN"
    assert result.decision_output["firstLayer"]["decision"] == (
        "建議改變計畫，先處理外部 deadline 壓力。"
    )
    assert "交通末班/接駁 deadline" in result.decision_output["firstLayer"][
        "reason"
    ]
    assert result.decision_output["runtimeSafetyTruth"] is False
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_runs_live_navigation_uncertainty_question() -> None:
    result = run_scout_ai_full_workflow(
        "我現在是不是偏離路線？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.missing_evidence_count == 1
    assert result.sources[0]["tool_id"] == LIVE_NAVIGATION_STATE_TOOL_ID
    assert result.sources[0]["top_result_summary"]["decision"] == "DELAY"
    assert result.sources[0]["top_result_summary"]["navigation_terrain"]["role"] == (
        "Navigation & Terrain Intelligence"
    )
    assert result.sources[0]["top_result_summary"]["decision_output"][
        "decisionObjectSchema"
    ] == "ContextualPermission"
    assert result.decision_output["decisionObjectSchema"] == "ContextualPermission"
    assert result.decision_output["answerSourceToolId"] == LIVE_NAVIGATION_STATE_TOOL_ID
    assert result.decision_output["decision"] == "DELAY"
    assert result.decision_output["firstLayer"]["decision"] == (
        "暫緩判斷，先取得可靠位置。"
    )
    assert result.decision_output["secondLayer"]["uncertaintyNotes"]
    assert "地形導航判斷" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_runs_ins_dr_trace_question() -> None:
    result = run_scout_ai_full_workflow(
        "GPS-only 軌跡和 INS/DR 軌跡差多少？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.missing_evidence_count == 1
    assert result.sources[0]["tool_id"] == INS_DR_TRACE_TOOL_ID
    summary = result.sources[0]["top_result_summary"]
    assert summary["decision"] == "DELAY"
    assert summary["decision_output"]["decisionObjectSchema"] == "ContextualPermission"
    assert summary["ins_dr_trace"]["role"] == "Navigation Truth / INS-DR Trace Guard"
    assert result.decision_output["answerSourceToolId"] == INS_DR_TRACE_TOOL_ID
    assert result.decision_output["decision"] == "DELAY"
    assert result.decision_output["firstLayer"]["decision"] == (
        "暫緩 INS/DR trace 判斷。"
    )
    answer_step = result.workflow_steps[-1]
    assert answer_step.summary["decision_output_schema"] == "ContextualPermission"
    assert answer_step.summary["decision_output_source_tool"] == INS_DR_TRACE_TOOL_ID
    assert "ins_dr_estimates_jsonl" in result.sources[0]["missing_fields"]
    assert "INS/DR trace decision: DELAY" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_runs_equipment_resource_question() -> None:
    result = run_scout_ai_full_workflow(
        "手機電量和頭燈水量夠嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.missing_evidence_count == 1
    assert result.sources[0]["tool_id"] == EQUIPMENT_RESOURCE_TOOL_ID
    assert result.sources[0]["top_result_summary"]["decision"] == "DELAY"
    assert result.sources[0]["top_result_summary"]["decision_output"][
        "decisionObjectSchema"
    ] == "ContextualPermission"
    assert result.sources[0]["top_result_summary"]["equipment_resource"]["role"] == (
        "Equipment / Resource Intelligence"
    )
    assert result.decision_output["answerSourceToolId"] == EQUIPMENT_RESOURCE_TOOL_ID
    assert result.decision_output["decision"] == "DELAY"
    assert result.decision_output["firstLayer"]["decision"] == (
        "建議延後裝備資源判斷。"
    )
    assert "裝備資源判斷" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_routes_water_refill_to_major_point_and_resource_answer() -> None:
    result = run_scout_ai_full_workflow(
        "哪裡可以補水？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=6,
    )

    source_ids = {source["tool_id"] for source in result.sources}
    assert MAJOR_POINT_TOOL_ID in source_ids
    assert EQUIPMENT_RESOURCE_TOOL_ID in source_ids
    assert ENERGY_VITALS_TOOL_ID in source_ids

    major_point = _workflow_source(result, MAJOR_POINT_TOOL_ID)
    assert major_point["top_result_summary"]["label"] == "黑水塘"
    assert major_point["top_result_summary"]["answerability"] == (
        "major_points_available"
    )
    assert major_point["top_result_summary"]["field_answer"].startswith(
        "候選補水/水源點：黑水塘"
    )
    assert result.decision_output["answerSourceToolId"] == EQUIPMENT_RESOURCE_TOOL_ID
    assert result.decision_output["decision"] == "DELAY"
    assert "候選補水/水源點：黑水塘" in result.answer
    assert "裝備資源判斷" in result.answer
    assert "不是現場取水" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_blocks_continuing_with_dead_phone_even_if_watch_has_battery() -> None:
    result = run_scout_ai_full_workflow(
        "如果手機沒電但手錶還有電，可以繼續嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 1
    assert result.sources[0]["tool_id"] == EQUIPMENT_RESOURCE_TOOL_ID
    assert result.sources[0]["top_result_summary"]["decision"] == "NO_GO"
    assert result.sources[0]["top_result_summary"]["resource_state"][
        "phone_battery_percent"
    ] == 0.0
    assert result.decision_output["answerSourceToolId"] == EQUIPMENT_RESOURCE_TOOL_ID
    assert result.decision_output["decision"] == "NO_GO"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["firstLayer"]["decision"] == (
        "不建議照原計畫出發或推進。"
    )
    assert "手錶有電不能單獨取代" in result.answer
    answer_step = result.workflow_steps[-1]
    assert answer_step.summary["decision_output_source_tool"] == (
        EQUIPMENT_RESOURCE_TOOL_ID
    )
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_blocks_autonomous_departure_without_offline_map() -> None:
    result = run_scout_ai_full_workflow(
        "我沒下載離線地圖，可以自主出發嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    source_ids = {source["tool_id"] for source in result.sources}
    assert NAVIGATION_TERRAIN_TOOL_ID in source_ids
    assert ROUTE_READINESS_TOOL_ID in source_ids
    assert EQUIPMENT_RESOURCE_TOOL_ID in source_ids
    assert MAP_PERCEPTION_TOOL_ID not in source_ids

    navigation = _workflow_source(result, NAVIGATION_TERRAIN_TOOL_ID)
    assert navigation["top_result_summary"]["decision"] == "GUIDED_ONLY"
    assert navigation["top_result_summary"]["map_readiness"][
        "offline_map_downloaded"
    ] is False

    equipment = next(
        source
        for source in result.sources
        if source["tool_id"] == EQUIPMENT_RESOURCE_TOOL_ID
    )
    assert equipment["top_result_summary"]["decision"] == "NO_GO"
    assert equipment["top_result_summary"]["resource_state"]["offline_map_ready"] is False

    assert result.decision_output["answerSourceToolId"] == EQUIPMENT_RESOURCE_TOOL_ID
    assert result.decision_output["decision"] == "NO_GO"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["firstLayer"]["decision"] == (
        "不建議照原計畫出發或推進。"
    )
    assert "離線地圖未就緒" in result.answer
    answer_step = result.workflow_steps[-1]
    assert answer_step.summary["decision_output_source_tool"] == (
        EQUIPMENT_RESOURCE_TOOL_ID
    )
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_routes_offline_map_gpx_check_to_navigation_readiness() -> None:
    result = run_scout_ai_full_workflow(
        "我有沒有下載離線地圖和 GPX？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    source_ids = {source["tool_id"] for source in result.sources}
    assert NAVIGATION_TERRAIN_TOOL_ID in source_ids
    assert EQUIPMENT_RESOURCE_TOOL_ID in source_ids
    navigation = _workflow_source(result, NAVIGATION_TERRAIN_TOOL_ID)
    map_readiness = navigation["top_result_summary"]["map_readiness"]
    assert navigation["top_result_summary"]["decision"] == "CONDITIONAL_GO"
    assert map_readiness["offline_map_downloaded"] is None
    assert map_readiness["gpx_loaded_on_device"] is None
    equipment = _workflow_source(result, EQUIPMENT_RESOURCE_TOOL_ID)
    assert (
        equipment["top_result_summary"]["resource_state"]["offline_map_ready"] is True
    )
    assert equipment["top_result_summary"]["resource_state"]["gpx_loaded"] is None
    assert "地圖力判斷" in result.answer
    assert "裝備資源判斷" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_routes_no_signal_navigation_to_map_readiness() -> None:
    result = run_scout_ai_full_workflow(
        "沒訊號時我還能導航嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    assert result.answerability == "evidence_available"
    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.missing_evidence_count == 0
    navigation = _workflow_source(result, NAVIGATION_TERRAIN_TOOL_ID)
    assert navigation["top_result_summary"]["decision"] == "CONDITIONAL_GO"
    assert navigation["top_result_summary"]["map_readiness"][
        "offline_tile_manifest_available"
    ] is False
    assert result.decision_output["answerSourceToolId"] == NAVIGATION_TERRAIN_TOOL_ID
    assert result.decision_output["decision"] == "CONDITIONAL_GO"
    assert "地圖力判斷" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_blocks_autonomous_navigation_without_backup_positioning() -> None:
    result = run_scout_ai_full_workflow(
        "這條路地圖力需求很高，但我們沒有第二套定位備援，可以自己去嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    source_ids = {source["tool_id"] for source in result.sources}
    assert NAVIGATION_TERRAIN_TOOL_ID in source_ids
    assert ROUTE_READINESS_TOOL_ID in source_ids
    assert MAP_PERCEPTION_TOOL_ID not in source_ids

    navigation = next(
        source
        for source in result.sources
        if source["tool_id"] == NAVIGATION_TERRAIN_TOOL_ID
    )
    assert navigation["top_result_summary"]["decision"] == "GUIDED_ONLY"
    assert navigation["top_result_summary"]["positioning_readiness"][
        "backup_positioning_available"
    ] is False

    assert result.decision_output["answerSourceToolId"] == NAVIGATION_TERRAIN_TOOL_ID
    assert result.decision_output["decision"] == "GUIDED_ONLY"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["firstLayer"]["decision"] == "不建議自主前往。"
    assert "地圖力判斷" in result.answer
    answer_step = result.workflow_steps[-1]
    assert answer_step.summary["decision_output_source_tool"] == (
        NAVIGATION_TERRAIN_TOOL_ID
    )
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_blocks_autonomous_navigation_without_terrain_feature_literacy() -> None:
    result = run_scout_ai_full_workflow(
        "我不會看稜線谷線鞍部，可以自主前往嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=6,
    )

    navigation = _workflow_source(result, NAVIGATION_TERRAIN_TOOL_ID)
    assert navigation["top_result_summary"]["decision"] == "GUIDED_ONLY"
    assert navigation["top_result_summary"]["map_skill_readiness"][
        "terrain_feature_skill_confirmed"
    ] is False
    assert result.decision_output["answerSourceToolId"] == NAVIGATION_TERRAIN_TOOL_ID
    assert result.decision_output["decision"] == "GUIDED_ONLY"
    assert result.decision_output["firstLayer"]["decision"] == "不建議自主前往。"
    assert "地形判讀" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_blocks_unknown_junctions_and_risk_layers() -> None:
    result = run_scout_ai_full_workflow(
        "不知道岔路點，也看不懂地形風險圖層，可以自主前往嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    navigation = _workflow_source(result, NAVIGATION_TERRAIN_TOOL_ID)
    assert navigation["top_result_summary"]["decision"] == "GUIDED_ONLY"
    assert navigation["top_result_summary"]["map_readiness"][
        "junction_points_known"
    ] is False
    assert navigation["top_result_summary"]["map_readiness"][
        "terrain_risk_layers_understood"
    ] is False

    assert result.decision_output["answerSourceToolId"] == NAVIGATION_TERRAIN_TOOL_ID
    assert result.decision_output["decision"] == "GUIDED_ONLY"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["firstLayer"]["decision"] == "不建議自主前往。"
    assert "岔路" in result.answer
    assert "地形風險圖層" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_blocks_natural_risk_layer_literacy_gap() -> None:
    result = run_scout_ai_full_workflow(
        "看不懂崩壁溪谷陡坡曝露地形風險圖層，可以自主前往嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=6,
    )

    navigation = _workflow_source(result, NAVIGATION_TERRAIN_TOOL_ID)
    assert navigation["top_result_summary"]["decision"] == "GUIDED_ONLY"
    assert navigation["top_result_summary"]["map_readiness"][
        "terrain_risk_layers_understood"
    ] is False
    assert result.decision_output["answerSourceToolId"] == NAVIGATION_TERRAIN_TOOL_ID
    assert result.decision_output["decision"] == "GUIDED_ONLY"
    assert result.decision_output["firstLayer"]["decision"] == "不建議自主前往。"
    assert "地形風險圖層" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_runs_route_readiness_question() -> None:
    result = run_scout_ai_full_workflow(
        "出發前 Go/No-Go 可以出發嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 6
    assert result.executed_tool_count == 6
    assert result.completed_tool_count == 6
    assert result.contract_gap_count == 0
    assert result.failed_tool_count == 0
    assert result.missing_evidence_count == 4
    source_ids = {source["tool_id"] for source in result.sources}
    assert {
        ROUTE_READINESS_TOOL_ID,
        ROUTE_ARCHITECTURE_TOOL_ID,
        NAVIGATION_TERRAIN_TOOL_ID,
        WEATHER_WINDOW_TOOL_ID,
        PACE_GUARDIAN_TOOL_ID,
        EQUIPMENT_RESOURCE_TOOL_ID,
    }.issubset(source_ids)
    assert result.sources[0]["tool_id"] == ROUTE_READINESS_TOOL_ID
    assert result.sources[0]["top_result_summary"]["decision"] == "DELAY"
    assert result.sources[0]["top_result_summary"]["route_readiness"]["role"] == (
        "Pre-Trip Route Readiness / Departure Gate"
    )
    assert result.sources[0]["top_result_summary"]["decision_output"][
        "decisionObjectSchema"
    ] == "ContextualPermission"
    assert result.sources[0]["top_result_summary"]["decision_output"]["decision"] == (
        "DELAY"
    )
    package = result.sources[0]["top_result_summary"]["pretrip_decision_package"]
    assert package["required_outputs"]["pretrip_decision"] == "DELAY"
    assert package["required_outputs"]["top_risk_sources"]
    assert result.decision_output["decisionObjectSchema"] == "ContextualPermission"
    assert result.decision_output["answerSourceToolId"] == ROUTE_READINESS_TOOL_ID
    assert result.decision_output["decision"] == "DELAY"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["firstLayer"]["decision"] == "建議延後。"
    assert "不得出發" in result.decision_output["firstLayer"]["limit"]
    assert result.decision_output["secondLayer"]["requiredConditions"]
    answer_step = result.workflow_steps[-1]
    assert answer_step.summary["decision_output_schema"] == "ContextualPermission"
    assert answer_step.summary["decision_output_source_tool"] == ROUTE_READINESS_TOOL_ID
    assert "user_experience_level" in result.sources[0]["missing_fields"]
    assert "user_goal" in result.sources[0]["missing_fields"]
    assert "出發前判斷" in result.answer
    assert "標準出發前決策包" in result.answer
    assert "停留限制" in result.answer
    assert "runtime safety truth" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_routes_top_risk_sources_to_route_readiness() -> None:
    result = run_scout_ai_full_workflow(
        "主要風險來源前三項是什麼？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    source = _workflow_source(result, ROUTE_READINESS_TOOL_ID)
    package = source["top_result_summary"]["pretrip_decision_package"]
    top_risks = package["required_outputs"]["top_risk_sources"]
    assert top_risks
    assert len(top_risks) >= 3
    assert result.decision_output["answerSourceToolId"] == ROUTE_READINESS_TOOL_ID
    assert result.decision_output["decision"] == "DELAY"
    assert "標準出發前決策包" in result.answer
    assert "前三風險" in result.answer
    assert "缺少必要行前輸入" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_expands_generic_pretrip_departure_to_mvp_evidence() -> None:
    result = run_scout_ai_full_workflow(
        "這個隊伍明天可以出發嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=6,
    )

    source_ids = {source["tool_id"] for source in result.sources}
    assert {
        ROUTE_READINESS_TOOL_ID,
        ROUTE_ARCHITECTURE_TOOL_ID,
        NAVIGATION_TERRAIN_TOOL_ID,
        WEATHER_WINDOW_TOOL_ID,
        PACE_GUARDIAN_TOOL_ID,
        EQUIPMENT_RESOURCE_TOOL_ID,
    }.issubset(source_ids)
    assert result.decision_output["answerSourceToolId"] == ROUTE_READINESS_TOOL_ID
    assert result.decision_output["decision"] == "DELAY"
    assert "出發前判斷" in result.answer
    assert "路線結構判斷" in result.answer
    assert "地圖力判斷" in result.answer
    assert "天氣決策" in result.answer
    assert "腳程守門員" in result.answer
    assert "裝備資源判斷" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_changes_plan_for_latest_return_limit() -> None:
    result = run_scout_ai_full_workflow(
        "最晚回程接駁是 16:30，這個行程可以嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.failed_tool_count == 0
    source = result.sources[0]
    assert source["tool_id"] == ROUTE_READINESS_TOOL_ID
    assert source["top_result_summary"]["decision"] == "CHANGE_PLAN"
    deadline = source["top_result_summary"]["readiness_governance"][
        "transport_deadline"
    ]
    assert deadline["resolved_deadline"] == "2013-10-08T16:30:00+08:00"
    assert deadline["target_eta"] == "2013-10-08T18:28:50+08:00"
    assert deadline["conflict"] is True
    assert result.decision_output["answerSourceToolId"] == ROUTE_READINESS_TOOL_ID
    assert result.decision_output["decision"] == "CHANGE_PLAN"
    assert result.decision_output["firstLayer"]["decision"] == "建議改變計畫。"
    assert result.decision_output["cost"]["latestReturnDeadline"] == (
        "2013-10-08T16:30:00+08:00"
    )
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_surfaces_pretrip_stop_policy() -> None:
    result = run_scout_ai_full_workflow(
        "哪裡是不建議停留點？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.failed_tool_count == 0
    source = result.sources[0]
    assert source["tool_id"] == ROUTE_READINESS_TOOL_ID
    assert source["top_result_summary"]["decision"] == "DELAY"
    package = source["top_result_summary"]["pretrip_decision_package"]
    required = package["required_outputs"]
    assert required["suggested_stop_points"][0]["label"] == "雲海保線所"
    assert required["suggested_stop_points"][0]["policy"] == (
        "turnaround_or_reassess"
    )
    assert "未審核拍攝" in required["not_recommended_stop_points"][0]["label"]
    assert required["not_recommended_stop_points"][0]["policy"] == (
        "not_recommended_until_reviewed"
    )
    assert result.decision_output["answerSourceToolId"] == ROUTE_READINESS_TOOL_ID
    assert result.decision_output["decision"] == "DELAY"
    assert result.decision_output["runtimeSafetyTruth"] is False
    answer_step = result.workflow_steps[-1]
    assert answer_step.summary["decision_output_source_tool"] == ROUTE_READINESS_TOOL_ID
    assert "標準出發前決策包" in result.answer
    assert "停留限制" in result.answer
    assert "建議停留/重評點" in result.answer
    assert "雲海保線所" in result.answer
    assert "runtime safety truth" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_surfaces_pretrip_checklist_gaps() -> None:
    result = run_scout_ai_full_workflow(
        "行前 checklist 還缺什麼？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    source = _workflow_source(result, ROUTE_READINESS_TOOL_ID)
    checklist = source["top_result_summary"]["pretrip_decision_package"][
        "required_outputs"
    ]["pretrip_checklist"]
    assert any(item["status"] != "complete" for item in checklist)
    assert result.decision_output["answerSourceToolId"] == ROUTE_READINESS_TOOL_ID
    assert "行前 checklist 缺口" in result.answer
    assert "成員經驗已審核=missing_or_needs_review" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_routes_residual_risk_to_route_readiness_package() -> None:
    result = run_scout_ai_full_workflow(
        "殘餘風險有哪些？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    source = _workflow_source(result, ROUTE_READINESS_TOOL_ID)
    residual_risk = source["top_result_summary"]["pretrip_decision_package"][
        "required_outputs"
    ]["residual_risk"]
    assert residual_risk
    assert result.decision_output["answerSourceToolId"] == ROUTE_READINESS_TOOL_ID
    assert "殘餘風險" in result.answer
    assert any("已審核行前證據不等於出發核准" in item for item in residual_risk)
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_runs_guided_only_route_readiness_question() -> None:
    result = run_scout_ai_full_workflow(
        "beginner 訓練 transportconfirmed slowestbasisconfirmed "
        "departuretimeconfirmed wxconfirmed sunok gearconfirmed rcconfirmed "
        "pretrip Go/No-Go 可以自主出發嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "evidence_available"
    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.failed_tool_count == 0
    assert result.missing_evidence_count == 0
    assert result.sources[0]["tool_id"] == ROUTE_READINESS_TOOL_ID
    summary = result.sources[0]["top_result_summary"]
    assert summary["decision"] == "GUIDED_ONLY"
    assert summary["guided_only_gate"]["required"] is True
    assert summary["route_demand_profile"]["route_demand"] == "high"
    package = summary["pretrip_decision_package"]
    assert package["required_outputs"]["pretrip_decision"] == "GUIDED_ONLY"
    assert package["decision_limits"]["autonomous_departure_allowed"] is False
    assert result.decision_output["answerSourceToolId"] == ROUTE_READINESS_TOOL_ID
    assert result.decision_output["decision"] == "GUIDED_ONLY"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["firstLayer"]["decision"] == (
        "只建議在合格帶領下進入。"
    )
    assert "不得自主出發" in result.decision_output["firstLayer"]["limit"]
    answer_step = result.workflow_steps[-1]
    assert answer_step.summary["decision_output_schema"] == "ContextualPermission"
    assert answer_step.summary["decision_output_source_tool"] == ROUTE_READINESS_TOOL_ID
    assert "GUIDED_ONLY" in result.answer
    assert "不建議自主出發" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_guided_only_for_high_risk_non_goal_route_readiness() -> None:
    result = run_scout_ai_full_workflow(
        "雪地技術攀登，出發前 Go/No-Go 可以自主出發嗎？"
        "advanced transportconfirmed slowestbasisconfirmed departuretimeconfirmed "
        "wxconfirmed sunok gearconfirmed rcconfirmed",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "evidence_available"
    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.failed_tool_count == 0
    assert result.missing_evidence_count == 0
    source = result.sources[0]
    assert source["tool_id"] == ROUTE_READINESS_TOOL_ID
    summary = source["top_result_summary"]
    assert summary["decision"] == "GUIDED_ONLY"
    assert summary["user_goal_profile"]["high_risk_non_goal"] is True
    assert summary["user_goal_profile"]["high_risk_non_goal_domains"] == [
        "snow",
        "technical_climb",
    ]
    gate = summary["readiness_governance"]["high_risk_domain_gate"]
    assert gate["required"] is True
    assert gate["domain_labels"] == ["雪地", "技術攀登"]
    package = summary["pretrip_decision_package"]
    assert package["required_outputs"]["pretrip_decision"] == "GUIDED_ONLY"
    assert package["decision_limits"]["autonomous_departure_allowed"] is False
    assert result.decision_output["answerSourceToolId"] == ROUTE_READINESS_TOOL_ID
    assert result.decision_output["decision"] == "GUIDED_ONLY"
    assert result.decision_output["allowed"] is False
    assert "不得自主出發" in result.decision_output["firstLayer"]["limit"]
    answer_step = result.workflow_steps[-1]
    assert answer_step.summary["decision_output_source_tool"] == ROUTE_READINESS_TOOL_ID
    assert "GUIDED_ONLY" in result.answer
    assert "雪地" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_surfaces_route_readiness_user_goal_controls() -> None:
    result = run_scout_ai_full_workflow(
        "親子拍攝目標，出發前 Go/No-Go 可以出發嗎？我是中級，"
        "transportconfirmed slowestbasisconfirmed departuretimeconfirmed "
        "wxconfirmed sunok gearconfirmed rcconfirmed",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "evidence_available"
    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.missing_evidence_count == 0
    source = result.sources[0]
    assert source["tool_id"] == ROUTE_READINESS_TOOL_ID
    summary = source["top_result_summary"]
    assert summary["decision"] == "CONDITIONAL_GO"
    profile = summary["user_goal_profile"]
    assert set(profile["goals"]) == {"photo", "family"}
    required = summary["pretrip_decision_package"]["required_outputs"]
    assert required["user_goal_profile"]["goal_labels"] == ["拍攝", "親子/家庭"]
    assert any(
        "拍攝" in gap
        for gap in summary["readiness_governance"]["warning_gaps"]
    )
    assert any(
        item["policy"] == "not_recommended_until_goal_limits_reviewed"
        for item in required["not_recommended_stop_points"]
    )
    assert result.decision_output["answerSourceToolId"] == ROUTE_READINESS_TOOL_ID
    assert result.decision_output["decision"] == "CONDITIONAL_GO"
    assert result.decision_output["runtimeSafetyTruth"] is False
    answer_step = result.workflow_steps[-1]
    assert answer_step.summary["decision_output_source_tool"] == ROUTE_READINESS_TOOL_ID
    assert "CONDITIONAL_GO" in result.answer
    assert "拍攝" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_runs_media_literacy_question() -> None:
    result = run_scout_ai_full_workflow(
        "IG 大崩壁美照會不會誤導？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count >= 1
    assert result.executed_tool_count >= 1
    assert result.completed_tool_count >= 1
    assert result.contract_gap_count == 0
    assert result.failed_tool_count == 0
    assert result.missing_evidence_count == 2
    sources = [source for source in result.sources if source["tool_id"] == MEDIA_LITERACY_TOOL_ID]
    assert len(sources) == 1
    source = sources[0]
    terrain_sources = [
        source for source in result.sources if source["tool_id"] == TERRAIN_SCORE_TOOL_ID
    ]
    assert len(terrain_sources) == 1
    terrain_source = terrain_sources[0]
    assert source["top_result_summary"]["decision"] == "NO_GO"
    assert terrain_source["top_result_summary"]["decision"] == "DELAY"
    assert "terrain_score_results" in terrain_source["missing_fields"]
    assert source["top_result_summary"]["media_literacy"]["role"] == (
        "Media Literacy / Bias Sentinel"
    )
    assert source["top_result_summary"]["decision_output"]["decisionObjectSchema"] == (
        "ContextualPermission"
    )
    assert result.decision_output["decisionObjectSchema"] == "ContextualPermission"
    assert result.decision_output["answerSourceToolId"] == MEDIA_LITERACY_TOOL_ID
    assert result.decision_output["decision"] == "NO_GO"
    assert result.decision_output["firstLayer"]["decision"] == (
        "不建議為媒體點位停留或改線。"
    )
    assert "不得為拍照" in result.decision_output["firstLayer"]["limit"]
    assert "媒體識讀判斷" in result.answer
    assert "runtime safety truth" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_prioritizes_media_literacy_for_social_detour() -> None:
    result = run_scout_ai_full_workflow(
        "大家都說旁邊那個點很好拍，可以繞去嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=5,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 7
    assert result.executed_tool_count == 7
    assert result.completed_tool_count == 7
    assert result.missing_evidence_count == 5
    _assert_on_route_micro_decision_support_sources(result)
    assert result.failed_tool_count == 0
    media = _workflow_source(result, MEDIA_LITERACY_TOOL_ID)
    contextual = _workflow_source(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert media["top_result_summary"]["action"] == "reroute"
    assert media["top_result_summary"]["decision"] == "NO_GO"
    assert media["top_result_summary"]["decision_output"]["action"] == "reroute"
    assert contextual["top_result_summary"]["action"] == "reroute"
    assert result.decision_output["answerSourceToolId"] == MEDIA_LITERACY_TOOL_ID
    assert result.decision_output["action"] == "reroute"
    assert result.decision_output["decision"] == "NO_GO"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["firstLayer"]["decision"] == (
        "不建議為媒體點位停留或改線。"
    )
    assert "媒體識讀判斷" in result.answer
    assert "beauty_photo_bias" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_routes_media_speed_bias_to_pace_adjustment() -> None:
    result = run_scout_ai_full_workflow(
        "這個網紅影片說兩小時可到，我們可以照這個速度嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=6,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 2
    assert result.completed_tool_count == 2
    media = _workflow_source(result, MEDIA_LITERACY_TOOL_ID)
    pace = _workflow_source(result, PACE_GUARDIAN_TOOL_ID)
    bias_ids = {
        item["bias_id"]
        for item in media["top_result_summary"]["media_bias_analysis"][
            "detected_biases"
        ]
    }
    assert "speed_bias" in bias_ids
    assert media["top_result_summary"]["action"] == "pace_adjustment"
    assert media["top_result_summary"]["decision"] == "NO_GO"
    assert pace["top_result_summary"]["decision"] == "NO_GO"
    assert result.decision_output["answerSourceToolId"] == MEDIA_LITERACY_TOOL_ID
    assert result.decision_output["action"] == "pace_adjustment"
    assert result.decision_output["decision"] == "NO_GO"
    assert "媒體識讀判斷" in result.answer
    assert "腳程守門員" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_blocks_sunk_cost_summit_pressure() -> None:
    result = run_scout_ai_full_workflow(
        "已經快到山頂了，不攻頂會不會很可惜？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=6,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 7
    assert result.executed_tool_count == 7
    assert result.completed_tool_count == 7
    assert result.missing_evidence_count == 5
    _assert_on_route_micro_decision_support_sources(result)
    media = _workflow_source(result, MEDIA_LITERACY_TOOL_ID)
    pace = _workflow_source(result, PACE_GUARDIAN_TOOL_ID)
    contextual = _workflow_source(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    bias_ids = {
        item["bias_id"]
        for item in media["top_result_summary"]["media_bias_analysis"][
            "detected_biases"
        ]
    }
    assert "sunk_cost_bias" in bias_ids
    assert media["top_result_summary"]["action"] == "summit"
    assert media["top_result_summary"]["decision"] == "NO_GO"
    assert pace["top_result_summary"]["decision"] == "NO_GO"
    assert contextual["top_result_summary"]["action"] == "summit"
    assert result.decision_output["answerSourceToolId"] == MEDIA_LITERACY_TOOL_ID
    assert result.decision_output["action"] == "summit"
    assert result.decision_output["decision"] == "NO_GO"
    assert result.decision_output["firstLayer"]["decision"] == (
        "不建議因為已經投入時間而繼續前進或攻頂。"
    )
    assert "sunk_cost_bias" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_blocks_seasonal_photo_detour_with_buffer() -> None:
    result = run_scout_ai_full_workflow(
        "看到乾季晴天美照，但今天濕滑又只剩 18 分鐘 buffer，可以繞去拍嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=5,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.failed_tool_count == 0
    media = _workflow_source(result, MEDIA_LITERACY_TOOL_ID)
    contextual = _workflow_source(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert media["top_result_summary"]["decision"] == "NO_GO"
    assert media["top_result_summary"]["media_bias_analysis"]["input_state"][
        "remaining_safety_buffer_minutes"
    ] == 18
    assert media["top_result_summary"]["media_bias_analysis"]["input_state"][
        "route_condition_reviewed"
    ] is True
    assert contextual["top_result_summary"]["action"] == "reroute"
    assert contextual["top_result_summary"]["decision"] == "NO_GO"
    assert contextual["top_result_summary"]["allowed"] is False
    assert result.decision_output["answerSourceToolId"] == MEDIA_LITERACY_TOOL_ID
    assert result.decision_output["decision"] == "NO_GO"
    assert result.decision_output["allowed"] is False
    assert "season_weather_bias" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_blocks_exposed_photo_pressure() -> None:
    result = run_scout_ai_full_workflow(
        "前方是高曝露陡坡，但照片很好看，可以去拍嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=5,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 8
    assert result.executed_tool_count == 8
    assert result.completed_tool_count == 8
    assert result.missing_evidence_count == 6
    _assert_on_route_micro_decision_support_sources(result)
    assert result.failed_tool_count == 0
    media = _workflow_source(result, MEDIA_LITERACY_TOOL_ID)
    contextual = _workflow_source(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    terrain = _workflow_source(result, TERRAIN_SCORE_TOOL_ID)
    assert media["top_result_summary"]["action"] == "photo"
    assert media["top_result_summary"]["decision"] == "NO_GO"
    assert contextual["top_result_summary"]["action"] == "photo"
    assert contextual["top_result_summary"]["decision"] == "NO_GO"
    assert terrain["top_result_summary"]["decision"] == "DELAY"
    assert result.decision_output["answerSourceToolId"] == MEDIA_LITERACY_TOOL_ID
    assert result.decision_output["action"] == "photo"
    assert result.decision_output["decision"] == "NO_GO"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["firstLayer"]["decision"] == (
        "不建議為媒體點位停留或改線。"
    )
    assert "媒體識讀判斷" in result.answer
    assert "beauty_photo_bias" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_runs_survival_playbook_question() -> None:
    result = run_scout_ai_full_workflow(
        "不確定自己在哪，可以下切溪谷找路嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count >= 1
    assert result.executed_tool_count >= 1
    assert result.completed_tool_count >= 1
    assert result.contract_gap_count == 0
    assert result.failed_tool_count == 0
    assert result.missing_evidence_count >= 1
    source = [
        source
        for source in result.sources
        if source["tool_id"] == SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID
    ]
    assert len(source) == 1
    summary = source[0]["top_result_summary"]
    assert summary["decision"] == "NO_GO"
    assert summary["decision_output"]["decisionObjectSchema"] == "ContextualPermission"
    assert summary["incident_triage"]["scenario"] == "lost_or_position_uncertain"
    assert summary["survival_incident_playbook"]["share_policy"][
        "can_send_or_notify"
    ] is False
    assert result.decision_output["answerSourceToolId"] == (
        SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID
    )
    assert result.decision_output["decision"] == "NO_GO"
    assert result.decision_output["firstLayer"]["decision"] == (
        "不建議繼續移動或下切找路。"
    )
    assert "求生事件 playbook" in result.answer
    assert "發送 SOS" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_escalates_active_altitude_sickness() -> None:
    result = run_scout_ai_full_workflow(
        "隊友頭痛想吐疑似高山症，還能繼續前進嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=5,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.failed_tool_count == 0
    source = _workflow_source(result, SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID)
    assert source["top_result_summary"]["decision"] == "ESCALATE"
    assert source["top_result_summary"]["incident_triage"]["scenario"] == (
        "injury_or_medical_uncertainty"
    )
    assert result.decision_output["answerSourceToolId"] == (
        SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID
    )
    assert result.decision_output["decision"] == "ESCALATE"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["firstLayer"]["decision"] == (
        "停止推進並交由人工救援/領隊判斷。"
    )
    assert "疑似高山症" in result.decision_output["firstLayer"]["reason"]
    assert "求生事件 playbook" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_runs_team_status_question() -> None:
    result = run_scout_ai_full_workflow(
        "後隊在哪？最後一次有效位置多久前？留守回報準備好了嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.missing_evidence_count == 1
    assert result.sources[0]["tool_id"] == TEAM_STATUS_TOOL_ID
    assert result.sources[0]["top_result_summary"]["decision"] == "DELAY"
    assert result.sources[0]["top_result_summary"]["decision_output"][
        "decisionObjectSchema"
    ] == "ContextualPermission"
    assert result.sources[0]["top_result_summary"]["team_status_guardian"]["role"] == (
        "Team Status / Remote Contact Governance"
    )
    assert result.decision_output["answerSourceToolId"] == TEAM_STATUS_TOOL_ID
    assert result.decision_output["decision"] == "DELAY"
    assert result.decision_output["firstLayer"]["decision"] == (
        "建議延後隊伍狀態判斷。"
    )
    assert "隊伍守門員" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_escalates_unanswered_teammate_message_without_outbound() -> None:
    result = run_scout_ai_full_workflow(
        "隊友已經 55 分鐘沒回訊息，要怎麼辦？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.failed_tool_count == 0
    source = result.sources[0]
    assert source["tool_id"] == TEAM_STATUS_TOOL_ID
    assert source["top_result_summary"]["decision"] == "ESCALATE"
    assert source["top_result_summary"]["decision_output"]["cost"][
        "checkinOverdueMinutes"
    ] == 55.0
    assert source["top_result_summary"]["team_status_guardian"][
        "outbound_send_performed"
    ] is False
    assert result.decision_output["answerSourceToolId"] == TEAM_STATUS_TOOL_ID
    assert result.decision_output["decision"] == "ESCALATE"
    assert result.decision_output["firstLayer"]["decision"] == (
        "停止推進並升級人工確認。"
    )
    assert "不得自動通知留守人" in result.decision_output["firstLayer"]["limit"]
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_escalates_rear_group_lost_contact_without_outbound() -> None:
    result = run_scout_ai_full_workflow(
        "後隊失聯 50 分鐘，是否需要升級處理？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.failed_tool_count == 0
    source = result.sources[0]
    assert source["tool_id"] == TEAM_STATUS_TOOL_ID
    assert source["top_result_summary"]["decision"] == "ESCALATE"
    assert source["top_result_summary"]["decision_output"]["cost"][
        "checkinOverdueMinutes"
    ] == 50.0
    assert source["top_result_summary"]["team_status_guardian"][
        "outbound_send_performed"
    ] is False
    assert result.decision_output["answerSourceToolId"] == TEAM_STATUS_TOOL_ID
    assert result.decision_output["decision"] == "ESCALATE"
    assert result.decision_output["firstLayer"]["decision"] == (
        "停止推進並升級人工確認。"
    )
    assert "回報逾時約 50 分鐘" in result.decision_output["firstLayer"]["reason"]
    assert "不得自動通知留守人" in result.decision_output["firstLayer"]["limit"]
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_runs_post_trip_review_question() -> None:
    result = run_scout_ai_full_workflow(
        "行後回顧要更新哪些下一次規劃？實際耗時哪裡比預期慢？",
        project_root=POST_ANALYSIS_ROOT,
        project_id="chilai_nanhua_day1_post_analysis",
        limit=3,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.missing_evidence_count == 1
    assert result.sources[0]["tool_id"] == POST_TRIP_REVIEW_TOOL_ID
    assert result.sources[0]["top_result_summary"]["decision"] == "DELAY"
    assert result.sources[0]["top_result_summary"]["decision_output"][
        "decisionObjectSchema"
    ] == "ContextualPermission"
    assert result.sources[0]["top_result_summary"]["post_trip_learning_package"][
        "role"
    ] == "Post-Trip Learning Proposal"
    assert result.sources[0]["top_result_summary"]["post_trip_review"]["role"] == (
        "Post-Trip Review / Learning Governance"
    )
    assert result.decision_output["answerSourceToolId"] == POST_TRIP_REVIEW_TOOL_ID
    assert result.decision_output["decision"] == "DELAY"
    assert result.decision_output["firstLayer"]["decision"] == "暫緩學習寫回。"
    assert "行後回顧" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_routes_trip_end_debrief_to_post_trip_review() -> None:
    result = run_scout_ai_full_workflow(
        "這次旅行結束後要怎麼檢討？哪些經驗要回寫到下次規劃？",
        project_root=POST_ANALYSIS_ROOT,
        project_id="chilai_nanhua_day1_post_analysis",
        limit=3,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.sources[0]["tool_id"] == POST_TRIP_REVIEW_TOOL_ID
    assert result.decision_output["answerSourceToolId"] == POST_TRIP_REVIEW_TOOL_ID
    assert result.decision_output["decision"] == "DELAY"
    assert result.decision_output["firstLayer"]["decision"] == "暫緩學習寫回。"
    assert "行後回顧" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_routes_actual_cp_writeback_to_post_trip_review() -> None:
    result = run_scout_ai_full_workflow(
        "實際 CP 通過時間要怎麼回寫？",
        project_root=POST_ANALYSIS_ROOT,
        project_id="chilai_nanhua_day1_post_analysis",
        limit=4,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.sources[0]["tool_id"] == POST_TRIP_REVIEW_TOOL_ID
    assert result.decision_output["answerSourceToolId"] == POST_TRIP_REVIEW_TOOL_ID
    assert result.decision_output["firstLayer"]["decision"] == "暫緩學習寫回。"
    assert "行後回顧" in result.answer
    assert "current_cp_id" not in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_routes_route_context_updates_to_post_trip_review() -> None:
    question = "哪些歷史、自然、文化點值得補充到路線脈絡？"
    result = run_scout_ai_full_workflow(
        question,
        project_root=POST_ANALYSIS_ROOT,
        project_id="chilai_nanhua_day1_post_analysis",
        limit=4,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.sources[0]["tool_id"] == POST_TRIP_REVIEW_TOOL_ID
    source = result.sources[0]["top_result_summary"]
    package = source["post_trip_learning_package"]
    assert package["data_to_collect"]["route_context_updates"] == [question]
    assert package["model_update_target_coverage"][
        "route_context_intelligence"
    ] is True
    assert result.decision_output["answerSourceToolId"] == POST_TRIP_REVIEW_TOOL_ID
    assert result.decision_output["firstLayer"]["decision"] == "暫緩學習寫回。"
    assert "行後回顧" in result.answer
    assert "候選路線脈絡" not in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_routes_post_trip_lost_near_miss_to_review() -> None:
    result = run_scout_ai_full_workflow(
        "這次摸黑差點迷路，要怎麼檢討？",
        project_root=POST_ANALYSIS_ROOT,
        project_id="chilai_nanhua_day1_post_analysis",
        limit=6,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 1
    assert result.missing_evidence_count == 1
    source = result.sources[0]
    assert source["tool_id"] == POST_TRIP_REVIEW_TOOL_ID
    assert source["missing_fields"] == [
        "subjective_difficulty",
        "equipment_gap_review",
        "weather_and_route_condition_feedback",
    ]
    assert result.decision_output["answerSourceToolId"] == POST_TRIP_REVIEW_TOOL_ID
    assert result.decision_output["decision"] == "ESCALATE"
    taxonomy = source["top_result_summary"]["post_trip_feedback"]["event_taxonomy"]
    assert "lost_or_navigation_uncertainty" in taxonomy["matched_event_types"]
    assert "darkness_or_daylight_overrun" in taxonomy["matched_event_types"]
    assert "行後回顧" in result.answer
    assert "求生事件 playbook" not in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_surfaces_post_trip_event_taxonomy() -> None:
    result = run_scout_ai_full_workflow(
        (
            "行後比預期難，摸黑前差點錯過岔路，隊友滑倒、脫隊，"
            "頭燈電量不足，午後低溫濕冷比預報早，下次要怎麼更新？"
        ),
        project_root=POST_ANALYSIS_ROOT,
        project_id="chilai_nanhua_day1_post_analysis",
        limit=6,
    )

    assert result.answerability == "evidence_available"
    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.missing_evidence_count == 0
    source = result.sources[0]
    assert source["tool_id"] == POST_TRIP_REVIEW_TOOL_ID
    assert source["collection_status"] == "completed"
    assert source["top_result_summary"]["decision"] == "ESCALATE"
    taxonomy = source["top_result_summary"]["post_trip_feedback"]["event_taxonomy"]
    assert taxonomy["candidate_only"] is True
    assert taxonomy["runtime_safety_truth"] is False
    assert set(taxonomy["matched_event_types"]) >= {
        "lost_or_navigation_uncertainty",
        "slip_or_fall",
        "cold_or_hypothermia",
        "team_separation",
        "darkness_or_daylight_overrun",
        "equipment_failure",
    }
    coverage = source["top_result_summary"]["post_trip_learning_package"][
        "model_update_target_coverage"
    ]
    assert coverage["navigation_terrain_readiness_model"] is True
    assert coverage["terrain_risk_layer"] is True
    assert coverage["weather_cold_exposure_policy"] is True
    assert coverage["team_status_governance"] is True
    assert coverage["daylight_turnaround_policy"] is True
    assert coverage["equipment_resource_readiness"] is True
    assert result.decision_output["answerSourceToolId"] == POST_TRIP_REVIEW_TOOL_ID
    assert result.decision_output["decision"] == "ESCALATE"
    assert result.decision_output["runtimeSafetyTruth"] is False
    assert "行後回顧" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_runs_safety_boundary_question() -> None:
    result = run_scout_ai_full_workflow(
        "哪些風險目前只是候選，不能觸發 Ln？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 3
    assert result.executed_tool_count == 3
    assert result.completed_tool_count == 3
    assert result.missing_evidence_count == 2
    source_ids = {source["tool_id"] for source in result.sources}
    assert SAFETY_BOUNDARY_TOOL_ID in source_ids
    safety = next(
        source
        for source in result.sources
        if source["tool_id"] == SAFETY_BOUNDARY_TOOL_ID
    )
    assert safety["top_result_summary"]["decision"] == "DELAY"
    assert safety["top_result_summary"]["decision_output"][
        "decisionObjectSchema"
    ] == "ContextualPermission"
    assert safety["top_result_summary"]["safety_boundary"]["role"] == (
        "Safety Boundary / Runtime Admission Guard"
    )
    assert result.decision_output["answerSourceToolId"] == SAFETY_BOUNDARY_TOOL_ID
    assert result.decision_output["decision"] == "DELAY"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["firstLayer"]["decision"] == (
        "Hold safety-state changes until admission evidence is complete."
    )
    answer_step = result.workflow_steps[-1]
    assert answer_step.summary["decision_output_schema"] == "ContextualPermission"
    assert answer_step.summary["decision_output_source_tool"] == SAFETY_BOUNDARY_TOOL_ID
    assert "admission_state" in safety["missing_fields"]
    assert "Safety boundary decision: DELAY" in result.answer
    assert "cannot trigger Ln" in result.answer
    assert result.boundary.runtime_safety_truth is False


def test_full_workflow_reports_no_registry_tool_selected_without_guessing() -> None:
    result = run_scout_ai_full_workflow(
        "請用一句話描述登山心情",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "no_registry_tool_selected"
    assert [step.step_id for step in result.workflow_steps] == [
        "context_registry_and_tool_plan",
        "evidence_collection",
        "answer_synthesis",
    ]
    assert result.selected_tool_count == 0
    assert result.executed_tool_count == 0
    assert result.completed_tool_count == 0
    assert result.contract_gap_count == 0
    assert result.missing_input_count == 0
    assert result.failed_tool_count == 0
    assert result.missing_evidence_count == 0
    assert result.sources == []
    assert result.missing_evidence == []
    assert result.workflow_policy.deterministic_tools_executed is False
    assert result.workflow_policy.model_provider_used is False
    assert result.workflow_policy.model_synthesis_performed is False
    assert result.discovery_plan["selected_tool_count"] == 0
    assert result.evidence_collection["selected_tool_count"] == 0
    assert result.answer_synthesis["answerability"] == "no_registry_tool_selected"
    assert result.workflow_steps[0].summary["selected_tool_count"] == 0
    assert result.workflow_steps[1].summary["selected_tool_count"] == 0
    assert result.workflow_steps[2].summary["answerability"] == (
        "no_registry_tool_selected"
    )
    assert "No registry-backed Scout AI tool was selected" in result.answer
    assert "no deterministic evidence" in result.answer
    assert "runtime safety truth" in result.answer
    assert result.boundary.runtime_safety_truth is False
    assert result.boundary.live_safety_api_calls_allowed is False


def test_full_workflow_builtin_manifest_and_payload_are_read_only(
    tmp_path: Path,
) -> None:
    manifest = load_tool_manifest(MANIFEST_PATH)
    request_path = tmp_path / "full-workflow-request.json"
    request_path.write_text(
        json.dumps(
            {
                "project_root": str(PROJECT_ROOT),
                "project_id": "chilai_nanhua_day1",
                "question": "危險地形在哪些位置?",
                "limit": 3,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    exit_code, payload = run_builtin_tool(
        ["ai-full-workflow", "--input", str(request_path), "--json"]
    )

    assert manifest.id == "scout.ai.full_workflow.run"
    assert manifest.mode == "local_evidence_query"
    assert manifest.allowed_writes == []
    assert "live.safety_api" in manifest.forbidden_writes
    assert "transport.egress" in manifest.forbidden_writes
    assert "hardware.device" in manifest.forbidden_writes
    assert manifest.metadata["read_only"] is True
    assert manifest.metadata["model_provider_used"] is False
    assert manifest.metadata["model_synthesis_performed"] is False
    assert manifest.metadata["runtime_safety_truth"] is False

    assert exit_code == 0
    assert payload["artifact_kind"] == ARTIFACT_KIND
    assert payload["artifact_version"] == ARTIFACT_VERSION
    assert payload["status"] == "completed"
    assert payload["answerability"] == "partial_evidence_with_missing_context"
    assert payload["selected_tool_count"] == 2
    assert payload["executed_tool_count"] == 2
    assert payload["completed_tool_count"] == 2
    assert payload["missing_evidence_count"] == 1
    terrain_source = next(
        source
        for source in payload["sources"]
        if source["tool_id"] == TERRAIN_SCORE_TOOL_ID
    )
    assert terrain_source["top_result_summary"]["decision"] == "DELAY"
    assert "terrain_score_results" in terrain_source["missing_fields"]
    assert payload["workflow_policy"]["model_provider_used"] is False
    assert payload["workflow_policy"]["model_synthesis_performed"] is False
    assert payload["workflow_steps"][0]["step_id"] == "context_registry_and_tool_plan"
    assert payload["workflow_steps"][1]["step_id"] == "evidence_collection"
    assert payload["workflow_steps"][2]["step_id"] == "answer_synthesis"
    assert payload["boundary"]["read_only"] is True
    assert payload["boundary"]["runtime_safety_truth"] is False
    assert payload["boundary"]["live_safety_api_calls_allowed"] is False
    assert payload["boundary"]["phase1_l0_l4_state_mutated"] is False
    assert payload["boundary"]["outbound_send_performed"] is False
    assert payload["boundary"]["hardware_control_performed"] is False
    assert payload["boundary"]["workspace_file_write_allowed"] is False
    assert payload["boundary"]["model_provider_used"] is False
    assert payload["boundary"]["model_synthesis_performed"] is False


def test_full_workflow_builtin_rejects_blank_question(tmp_path: Path) -> None:
    request_path = tmp_path / "full-workflow-request.json"
    request_path.write_text(
        json.dumps(
            {
                "project_root": str(PROJECT_ROOT),
                "question": "",
            }
        ),
        encoding="utf-8",
    )

    exit_code, payload = run_builtin_tool(
        ["ai-full-workflow", "--input", str(request_path), "--json"]
    )

    assert exit_code == 2
    assert payload["status"] == "failed"
    assert "non-empty question" in payload["error"]
    assert payload["boundary"]["runtime_safety_truth"] is False


def _write_team_pace_project(tmp_path: Path) -> Path:
    project_root = tmp_path / "team_pace_project"
    outputs = project_root / "outputs"
    outputs.mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "project_id": "team_pace_project",
                "team_status_ref": "outputs/team_status.json",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (outputs / "team_status.json").write_text(
        json.dumps(
            {
                "artifact_kind": "scout_team_status",
                "source_status": "candidate_only",
                "leader_accepts_slowest_basis": False,
                "team_rest_sync": "mismatched",
                "schedule": {"current_delay_minutes": 22},
                "members": [
                    {
                        "member_id": "leader",
                        "display_label": "Leader",
                        "pace_mps": 1.15,
                        "reserve_minutes": 55,
                        "fatigue_band": "normal",
                    },
                    {
                        "member_id": "teammate",
                        "display_label": "New teammate",
                        "pace_mps": 0.60,
                        "reserve_minutes": 8,
                        "fatigue_band": "tired",
                        "rest_need_minutes": 12,
                        "first_time_similar_route": True,
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return project_root


def _write_pace_coefficient_project(tmp_path: Path) -> Path:
    project_root = tmp_path / "pace_coefficient_project"
    outputs = project_root / "outputs"
    outputs.mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "project_id": "pace_coefficient_project",
                "team_status_ref": "outputs/team_status.json",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (outputs / "team_status.json").write_text(
        json.dumps(
            {
                "artifact_kind": "scout_team_status",
                "source_status": "candidate_only",
                "leader_accepts_slowest_basis": True,
                "team_rest_sync": "synced",
                "members": [
                    {
                        "member_id": "leader",
                        "display_label": "Leader",
                        "pace_mps": 1.05,
                        "reserve_minutes": 70,
                    },
                    {
                        "member_id": "slowest",
                        "display_label": "Slowest member",
                        "pace_mps": 0.72,
                        "reserve_minutes": 45,
                        "flat_speed_mps": 1.0,
                        "uphill_speed_mps": 0.55,
                        "downhill_speed_mps": 0.48,
                        "technical_terrain_slowdown_ratio": 0.35,
                        "rest_frequency_minutes": 50,
                        "late_trip_speed_decay_ratio": 0.28,
                        "pack_weight_kg": 11,
                        "load_slowdown_ratio": 0.2,
                        "weather_slowdown_ratio": 0.18,
                        "experience_credibility": "low",
                        "self_report_gap_ratio": 0.24,
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return project_root


def _assert_on_route_micro_decision_support_sources(result) -> None:
    live_navigation = _workflow_source(result, LIVE_NAVIGATION_STATE_TOOL_ID)
    route_architecture = _workflow_source(result, ROUTE_ARCHITECTURE_TOOL_ID)
    weather = _workflow_source(result, WEATHER_WINDOW_TOOL_ID)
    pace = _workflow_source(result, PACE_GUARDIAN_TOOL_ID)
    risk = _workflow_source(result, RISK_SCORE_TOOL_ID)

    assert live_navigation["collection_status"] == "completed"
    assert "lat" in live_navigation["missing_fields"]
    assert route_architecture["collection_status"] == "completed"
    assert weather["collection_status"] == "completed"
    assert "route_weather_package" in weather["missing_fields"]
    assert pace["collection_status"] == "completed"
    assert pace["missing_fields"] == ["member_pace_profile"]
    assert risk["collection_status"] == "completed"


def _workflow_source(result, tool_id: str):
    matches = [
        source for source in result.sources if source["tool_id"] == tool_id
    ]
    assert len(matches) == 1, result.sources
    return matches[0]


def _write_route_weather_project(tmp_path: Path) -> Path:
    project_root = tmp_path / "weather_decision_project"
    outputs = project_root / "outputs"
    outputs.mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "project_id": "weather_decision_project",
                "route_weather_package_ref": "outputs/route_weather_package.json",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (outputs / "route_weather_package.json").write_text(
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
                        "segmentId": "ridge.exposure",
                        "etaFrom": "2099-06-08T04:30:00Z",
                        "etaTo": "2099-06-08T05:10:00Z",
                        "terrainRisk": 0.74,
                        "weatherRisk": 0.68,
                        "finalRisk": 0.79,
                        "riskLevel": "HIGH",
                        "factors": ["午後雷雨", "稜線暴露", "低能見度可能"],
                        "message": "此路段有雷雨、低能見度與稜線暴露疊加。",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return project_root


def _write_recent_rain_creek_project(tmp_path: Path) -> Path:
    project_root = tmp_path / "recent_rain_creek_project"
    outputs = project_root / "outputs"
    outputs.mkdir(parents=True)
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
    (outputs / "route_weather_package.json").write_text(
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
    project_root = tmp_path / "heat_exposure_project"
    outputs = project_root / "outputs"
    outputs.mkdir(parents=True)
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
    (outputs / "route_weather_package.json").write_text(
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
    project_root = tmp_path / "source_disagreement_project"
    outputs = project_root / "outputs"
    outputs.mkdir(parents=True)
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
    (outputs / "route_weather_package.json").write_text(
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
