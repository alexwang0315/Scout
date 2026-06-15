import json
from pathlib import Path

from scout_agent_builtin_tools import run_builtin_tool
from scout_agent_tools import load_tool_manifest
from scout_ai_answer_synthesis import (
    ARTIFACT_KIND,
    ARTIFACT_VERSION,
    collect_and_synthesize_scout_ai_answer,
    synthesize_scout_ai_answer_from_evidence,
)
from scout_ai_evidence_collection import collect_scout_ai_evidence
from scout_ai_tool_planner import (
    ENERGY_VITALS_TOOL_ID,
    LIVE_NAVIGATION_STATE_TOOL_ID,
    NAVIGATION_TERRAIN_TOOL_ID,
    WEATHER_WINDOW_TOOL_ID,
)
from scout_contextual_permission_tool import CONTEXTUAL_PERMISSION_TOOL_ID
from scout_route_readiness_tool import ROUTE_READINESS_TOOL_ID
from scout_pace_guardian_tool import PACE_GUARDIAN_TOOL_ID
from scout_equipment_resource_tool import EQUIPMENT_RESOURCE_TOOL_ID
from scout_team_status_tool import TEAM_STATUS_TOOL_ID
from scout_post_trip_review_tool import POST_TRIP_REVIEW_TOOL_ID
from scout_route_architecture_tool import ROUTE_ARCHITECTURE_TOOL_ID
from scout_route_context_tool import ROUTE_CONTEXT_TOOL_ID
from scout_media_literacy_tool import MEDIA_LITERACY_TOOL_ID
from scout_survival_incident_playbook_tool import SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID
from scout_risk_score_tool import RISK_SCORE_TOOL_ID
from scout_terrain_score_tool import TERRAIN_SCORE_TOOL_ID
from scout_safety_boundary_tool import SAFETY_BOUNDARY_TOOL_ID
from scout_map_perception_tool import MAP_PERCEPTION_TOOL_ID
from scout_ins_dr_trace_tool import INS_DR_TRACE_TOOL_ID


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
POST_ANALYSIS_ROOT = (
    ROOT / "tests" / "fixtures" / "post_analysis" / "chilai_nanhua_day1_post_analysis"
)
MANIFEST_PATH = (
    ROOT
    / "tools"
    / "scout_agent_tool_manifests"
    / "scout.ai.answer_synthesis.synthesize.json"
)


def test_answer_synthesis_uses_completed_risk_and_terrain_evidence() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "危險地形在哪些位置?",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.artifact_kind == ARTIFACT_KIND
    assert result.artifact_version == ARTIFACT_VERSION
    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.evidence_collection_verified is True
    assert result.completed_source_count == 2
    assert result.missing_evidence_count == 1
    assert result.failed_source_count == 0
    assert result.synthesis_policy.evidence_collected_before_synthesis is True
    assert result.synthesis_policy.deterministic_fallback_formatter_used is True
    assert result.synthesis_policy.model_provider_used is False
    assert result.synthesis_policy.model_synthesis_performed is False
    assert result.boundary.runtime_safety_truth is False
    assert result.boundary.live_safety_api_calls_allowed is False

    source_ids = {source.tool_id for source in result.sources}
    assert RISK_SCORE_TOOL_ID in source_ids
    assert TERRAIN_SCORE_TOOL_ID in source_ids
    risk_source = next(source for source in result.sources if source.tool_id == RISK_SCORE_TOOL_ID)
    terrain_source = next(
        source for source in result.sources if source.tool_id == TERRAIN_SCORE_TOOL_ID
    )
    assert risk_source.top_result_summary["decision"] == "CHANGE_PLAN"
    assert risk_source.top_result_summary["decision_output"][
        "decisionObjectSchema"
    ] == "ContextualPermission"
    assert result.decision_output["answerSourceToolId"] == RISK_SCORE_TOOL_ID
    assert result.decision_output["decision"] == "CHANGE_PLAN"
    assert result.decision_output["firstLayer"]["decision"] == (
        "建議改變路線或通過策略。"
    )
    assert terrain_source.top_result_summary["decision"] == "DELAY"
    assert "terrain_score_results" in terrain_source.missing_fields
    assert "deterministic evidence was collected before synthesis" in result.answer
    assert RISK_SCORE_TOOL_ID in result.answer
    assert "result_count=3" in result.answer
    assert "runtime safety truth" in result.answer
    assert any("no model provider was called" in item for item in result.limitations)


def test_answer_synthesis_reports_weather_tool_missing_fresh_evidence_without_guessing() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "明天午後雷雨是否要紮營?",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.completed_source_count >= 1
    assert result.missing_evidence_count >= 1
    assert result.synthesis_policy.model_provider_used is False
    assert result.synthesis_policy.model_synthesis_performed is False

    assert result.sources[0].tool_id == WEATHER_WINDOW_TOOL_ID
    assert result.sources[0].collection_status == "completed"
    assert result.sources[0].top_result_summary["answerability"] == (
        "weather_placeholder_only"
    )
    assert "provider" in result.sources[0].missing_fields
    assert "ttl_s" in result.sources[0].missing_fields
    assert "route_weather_package" in result.sources[0].missing_fields
    assert result.missing_evidence[0]["tool_id"] == WEATHER_WINDOW_TOOL_ID
    assert "provider" in result.missing_evidence[0]["missing_fields"]
    assert "ttl_s" in result.missing_evidence[0]["missing_fields"]
    assert "weather_placeholder_only" in result.answer
    assert "provider" in result.answer
    assert "ttl_s" in result.answer
    assert "runtime safety truth" in result.answer


def test_answer_synthesis_uses_energy_vitals_decision_output() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "我現在心率偏高又很累，需要休息嗎?",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.sources[0].tool_id == ENERGY_VITALS_TOOL_ID
    assert result.sources[0].collection_status == "completed"
    assert result.sources[0].top_result_summary["decision"] == "DELAY"
    assert result.sources[0].top_result_summary["decision_output"][
        "decisionObjectSchema"
    ] == "ContextualPermission"
    assert result.decision_output["decisionObjectSchema"] == "ContextualPermission"
    assert result.decision_output["answerSourceToolId"] == ENERGY_VITALS_TOOL_ID
    assert result.decision_output["decision"] == "DELAY"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["firstLayer"]["decision"] == (
        "建議延後體能/穿戴判斷。"
    )
    assert result.decision_output["runtimeSafetyTruth"] is False


def test_answer_synthesis_uses_weather_to_decision_field_answer(tmp_path: Path) -> None:
    project_root = _write_route_weather_project(tmp_path)

    result = collect_and_synthesize_scout_ai_answer(
        "午後雷雨是否要改變計畫?",
        project_root=project_root,
        project_id="weather_decision_project",
        limit=3,
    )

    assert result.answerability == "evidence_available"
    assert result.completed_source_count >= 1
    assert result.missing_evidence_count == 0
    assert result.sources[0].tool_id == WEATHER_WINDOW_TOOL_ID
    assert result.sources[0].top_result_summary["decision"] == "CHANGE_PLAN"
    assert result.sources[0].top_result_summary["decision_output"][
        "decisionObjectSchema"
    ] == "ContextualPermission"
    assert result.sources[0].top_result_summary["weather_to_decision"]["role"] == (
        "Risk Sentinel / Weather-to-Decision"
    )
    assert result.decision_output["decisionObjectSchema"] == "ContextualPermission"
    assert result.decision_output["answerSourceToolId"] == WEATHER_WINDOW_TOOL_ID
    assert result.decision_output["decision"] == "CHANGE_PLAN"
    assert result.decision_output["firstLayer"]["decision"] == (
        "不建議照原計畫通過。"
    )
    assert result.decision_output["runtimeSafetyTruth"] is False
    assert "天氣決策" in result.answer
    assert "CHANGE_PLAN" in result.answer
    assert "runtime safety truth" in result.answer


def test_answer_synthesis_uses_map_perception_decision_output() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "CP001 附近有沒有標註?",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "evidence_available"
    assert result.completed_source_count == 1
    assert result.missing_evidence_count == 0
    source = _source(result, MAP_PERCEPTION_TOOL_ID)
    assert source.top_result_summary["decision"] == "CONDITIONAL_GO"
    assert source.top_result_summary["decision_output"]["decisionObjectSchema"] == (
        "ContextualPermission"
    )
    assert source.top_result_summary["map_perception"]["role"] == (
        "Navigation & Terrain Intelligence / Map Perception"
    )
    assert result.decision_output["answerSourceToolId"] == MAP_PERCEPTION_TOOL_ID
    assert result.decision_output["decision"] == "CONDITIONAL_GO"
    assert result.decision_output["allowed"] is True
    assert result.decision_output["firstLayer"]["decision"] == (
        "可作為候選地圖參考。"
    )
    assert "地圖判讀決策：CONDITIONAL_GO" in result.answer
    assert "不是 runtime safety truth" in result.answer


def test_answer_synthesis_uses_contextual_permission_field_answer_without_guessing() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "我可以在這裡停下來拍一段影片嗎?",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.completed_source_count == 1
    assert result.missing_evidence_count == 1
    assert result.sources[0].tool_id == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.sources[0].top_result_summary["decision"] == "NO_GO"
    assert result.sources[0].top_result_summary["allowed"] is False
    assert result.sources[0].top_result_summary["decision_object"] == (
        result.sources[0].top_result_summary["contextual_permission"]
    )
    assert result.sources[0].top_result_summary["decision_output"][
        "decisionObjectSchema"
    ] == "ContextualPermission"
    assert result.sources[0].top_result_summary["decision_output"]["firstLayer"][
        "decision"
    ] == "不建議拍影片。"
    assert result.decision_output["decisionObjectSchema"] == "ContextualPermission"
    assert result.decision_output["answerSourceToolId"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.decision_output["action"] == "film"
    assert result.decision_output["decision"] == "NO_GO"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["firstLayer"]["decision"] == "不建議拍影片。"
    assert result.decision_output["runtimeSafetyTruth"] is False
    assert "remaining_safety_buffer_minutes" in result.sources[0].missing_fields
    assert "[決策] 不建議拍影片。" in result.answer
    assert "不建議拍影片" in result.answer
    assert "remaining_safety_buffer_minutes" in result.answer
    assert "runtime safety truth" in result.answer


def test_answer_synthesis_prices_extra_stop_time_against_buffer() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "現在 2026-06-07T13:36:00+08:00，安全 buffer 還有 21 分鐘，"
        "如果多停 10 分鐘，代價是什麼？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "evidence_available"
    assert result.completed_source_count == 1
    source = result.sources[0]
    assert source.tool_id == CONTEXTUAL_PERMISSION_TOOL_ID
    assert source.top_result_summary["action"] == "stop"
    assert source.top_result_summary["decision"] == "CONDITIONAL_GO"
    assert source.top_result_summary["allowed"] is True
    assert source.top_result_summary["max_duration_minutes"] == 10
    assert source.top_result_summary["leave_by"] == "2026-06-07T13:46:00+08:00"
    assert result.decision_output["answerSourceToolId"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.decision_output["action"] == "stop"
    assert result.decision_output["decision"] == "CONDITIONAL_GO"
    assert result.decision_output["allowed"] is True
    assert result.decision_output["maxDurationMinutes"] == 10
    assert result.decision_output["leaveBy"] == "2026-06-07T13:46:00+08:00"
    assert result.decision_output["cost"]["timeBufferChangeMinutes"] == -10
    assert result.decision_output["firstLayer"]["decision"] == "可以，最多 10 分鐘。"
    assert "消耗 10 分鐘 buffer" in result.answer
    assert "2026-06-07T13:46:00+08:00 前離開" in result.answer
    assert result.decision_output["runtimeSafetyTruth"] is False


def test_answer_synthesis_treats_fog_photo_as_wait_permission() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "可以等霧散再拍照嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=6,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.completed_source_count == 2
    assert result.missing_evidence_count == 2
    weather = _source(result, WEATHER_WINDOW_TOOL_ID)
    contextual = _source(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert weather.top_result_summary["decision"] == "DELAY"
    assert contextual.top_result_summary["action"] == "wait"
    assert contextual.top_result_summary["decision"] == "NO_GO"
    assert contextual.missing_fields == ["remaining_safety_buffer_minutes"]
    assert result.decision_output["answerSourceToolId"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.decision_output["action"] == "wait"
    assert result.decision_output["decision"] == "NO_GO"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["firstLayer"]["decision"] == "不建議等待。"
    assert "不建議等待" in result.answer
    assert "remaining_safety_buffer_minutes" in result.answer
    assert "runtime safety truth" in result.answer


def test_answer_synthesis_blocks_wind_exposed_lunch() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "這裡是風口，我們可以在這裡吃午餐嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=6,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.completed_source_count == 2
    assert result.missing_evidence_count == 2
    weather = _source(result, WEATHER_WINDOW_TOOL_ID)
    contextual = _source(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert weather.top_result_summary["decision"] == "DELAY"
    assert contextual.top_result_summary["action"] == "lunch"
    assert contextual.top_result_summary["decision"] == "NO_GO"
    assert contextual.top_result_summary["allowed"] is False
    assert contextual.missing_fields == ["remaining_safety_buffer_minutes"]
    assert result.decision_output["answerSourceToolId"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.decision_output["action"] == "lunch"
    assert result.decision_output["decision"] == "NO_GO"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["firstLayer"]["decision"] == "不建議吃午餐。"
    assert "風口" in result.decision_output["firstLayer"]["reason"]
    assert "較避風 CP" in result.decision_output["firstLayer"]["nextStep"]
    assert "不建議吃午餐" in result.answer
    assert "runtime safety truth" in result.answer


def test_answer_synthesis_escalates_stream_surge_crossing() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "前方溪水暴漲，還能過溪嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=6,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.completed_source_count == 2
    assert result.missing_evidence_count == 2
    weather = _source(result, WEATHER_WINDOW_TOOL_ID)
    contextual = _source(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert weather.top_result_summary["decision"] == "DELAY"
    assert contextual.top_result_summary["action"] == "cross_stream"
    assert contextual.top_result_summary["decision"] == "ESCALATE"
    assert contextual.top_result_summary["allowed"] is False
    assert contextual.missing_fields == ["remaining_safety_buffer_minutes"]
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
    assert "runtime safety truth" in result.answer


def test_answer_synthesis_blocks_split_team_micro_decision() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "可以讓走得快的人先去山頂嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "evidence_available"
    assert result.completed_source_count == 1
    assert result.missing_evidence_count == 0
    assert result.sources[0].tool_id == CONTEXTUAL_PERMISSION_TOOL_ID
    summary = result.sources[0].top_result_summary
    assert summary["action"] == "split_team"
    assert summary["decision"] == "NO_GO"
    assert summary["allowed"] is False
    assert result.decision_output["answerSourceToolId"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.decision_output["action"] == "split_team"
    assert result.decision_output["decision"] == "NO_GO"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["firstLayer"]["decision"] == "不建議分隊。"
    assert "保持隊伍完整" in result.answer
    assert "runtime safety truth" in result.answer


def test_answer_synthesis_uses_rain_gear_micro_decision_before_missing_context() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "前面下雨了，要不要穿雨衣？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.completed_source_count == 3
    assert result.missing_evidence_count == 2
    source = _source(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    summary = source.top_result_summary
    assert summary["action"] == "wear_rain_gear"
    assert summary["decision"] == "GO"
    assert summary["allowed"] is True
    assert source.missing_fields == []
    assert result.decision_output["answerSourceToolId"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.decision_output["action"] == "wear_rain_gear"
    assert result.decision_output["decision"] == "GO"
    assert result.decision_output["allowed"] is True
    assert result.decision_output["firstLayer"]["decision"] == "可以穿雨具。"
    assert "不額外消耗停留 buffer" in result.answer
    assert "Missing evidence" in result.answer
    assert "runtime safety truth" in result.answer


def test_answer_synthesis_blocks_shortcut_reroute_micro_decision() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "這個岔路可以切嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=5,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.completed_source_count == 3
    assert result.missing_evidence_count == 2
    source = _source(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    summary = source.top_result_summary
    assert summary["action"] == "reroute"
    assert summary["decision"] == "NO_GO"
    assert summary["allowed"] is False
    assert source.missing_fields == ["remaining_safety_buffer_minutes"]
    nav_source = _source(result, LIVE_NAVIGATION_STATE_TOOL_ID)
    assert "lat" in nav_source.missing_fields
    assert result.decision_output["answerSourceToolId"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.decision_output["action"] == "reroute"
    assert result.decision_output["decision"] == "NO_GO"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["firstLayer"]["decision"] == "不建議改線。"
    assert "不要臨時改線" in result.answer
    assert "Missing evidence" in result.answer
    assert "runtime safety truth" in result.answer


def test_answer_synthesis_uses_direct_retreat_micro_decision() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "隊友很累，要不要直接撤退？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=5,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.completed_source_count == 3
    assert result.missing_evidence_count == 2
    source = _source(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    summary = source.top_result_summary
    assert summary["action"] == "retreat"
    assert summary["decision"] == "GO"
    assert summary["allowed"] is True
    assert source.missing_fields == []
    pace_source = _source(result, PACE_GUARDIAN_TOOL_ID)
    assert pace_source.missing_fields == ["member_pace_profile"]
    assert result.decision_output["answerSourceToolId"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.decision_output["action"] == "retreat"
    assert result.decision_output["decision"] == "GO"
    assert result.decision_output["allowed"] is True
    assert result.decision_output["firstLayer"]["decision"] == "可以撤退。"
    assert "開始撤退" in result.answer
    assert "Missing evidence" in result.answer
    assert "runtime safety truth" in result.answer


def test_answer_synthesis_uses_route_context_field_answer_without_guessing() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "下一個觀察點在哪？哪裡適合拍攝大景？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    assert result.answerability == "evidence_available"
    assert result.completed_source_count == 1
    assert result.missing_evidence_count == 0
    assert result.sources[0].tool_id == ROUTE_CONTEXT_TOOL_ID
    assert result.sources[0].top_result_summary["answerability"] == (
        "route_context_available"
    )
    assert result.sources[0].top_result_summary["decision"] == "CONDITIONAL_GO"
    assert result.sources[0].top_result_summary["decision_output"][
        "decisionObjectSchema"
    ] == "ContextualPermission"
    assert result.sources[0].top_result_summary["route_context"]["role"] == (
        "Experience Guide"
    )
    assert result.decision_output["answerSourceToolId"] == ROUTE_CONTEXT_TOOL_ID
    assert result.decision_output["decision"] == "CONDITIONAL_GO"
    assert result.decision_output["firstLayer"]["decision"] == "可作為候選觀察點。"
    assert "不是停留授權" in result.decision_output["firstLayer"]["limit"]
    assert "候選路線脈絡" in result.answer
    assert "Experience Guide 候選" in result.answer
    assert "contextual permission" in result.answer
    assert "runtime safety truth" in result.answer


def test_answer_synthesis_uses_route_briefing_compose_context(
    tmp_path: Path,
) -> None:
    project_root = _write_route_briefing_project(tmp_path)

    result = collect_and_synthesize_scout_ai_answer(
        "哪些點值得停 3 分鐘？",
        project_root=project_root,
        project_id="chilai_nanhua_briefing",
        limit=4,
    )

    assert result.answerability == "evidence_available"
    assert result.completed_source_count == 1
    assert result.missing_evidence_count == 0
    source = _source(result, ROUTE_CONTEXT_TOOL_ID)
    briefing = source.top_result_summary["route_briefing"]
    assert briefing["available"] is True
    assert briefing["candidate_only"] is True
    assert briefing["runtime_safety_truth"] is False
    assert source.top_result_summary["route_context"]["route_briefing"] == briefing
    assert result.decision_output["answerSourceToolId"] == ROUTE_CONTEXT_TOOL_ID
    assert "候選 3 分鐘觀察點" in result.answer
    assert "雲海保線所" in result.answer
    assert "松原駐在所、木炭窯" in result.answer
    assert "光被八表" in result.answer
    assert "不是現場停留授權" in result.answer
    assert "runtime safety truth" in result.answer


def test_answer_synthesis_uses_pace_guardian_field_answer_without_guessing(
    tmp_path: Path,
) -> None:
    project_root = _write_team_pace_project(tmp_path)

    result = collect_and_synthesize_scout_ai_answer(
        "隊伍腳程是否能準時抵達下一個 CP？最慢者需要前移午餐點嗎？",
        project_root=project_root,
        project_id="team_pace_project",
        limit=4,
    )

    assert result.answerability == "evidence_available"
    assert result.completed_source_count == 1
    assert result.missing_evidence_count == 0
    assert result.sources[0].tool_id == PACE_GUARDIAN_TOOL_ID
    assert result.sources[0].top_result_summary["answerability"] == (
        "pace_fit_decision_available"
    )
    assert result.sources[0].top_result_summary["pace_guardian"]["role"] == (
        "Pace Guardian"
    )
    assert result.sources[0].top_result_summary["decision_output"][
        "decisionObjectSchema"
    ] == "ContextualPermission"
    assert result.sources[0].top_result_summary["team_pace_fit"]["slowest_member"][
        "label"
    ] == "New teammate"
    assert result.decision_output["decisionObjectSchema"] == "ContextualPermission"
    assert result.decision_output["answerSourceToolId"] == PACE_GUARDIAN_TOOL_ID
    assert result.decision_output["decision"] == "CHANGE_PLAN"
    assert result.decision_output["firstLayer"]["decision"] == (
        "不建議照原計畫推進。"
    )
    assert "不要用平均腳程" in result.decision_output["firstLayer"]["limit"]
    assert "腳程守門員" in result.answer
    assert "不使用平均腳程" in result.answer
    assert "contextual permission" in result.answer
    assert "runtime safety truth" in result.answer


def test_answer_synthesis_routes_average_pace_bias_to_pace_guardian() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "我們平均腳程還可以，可以用平均速度估嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.completed_source_count == 1
    assert result.missing_evidence_count == 1
    assert result.sources[0].tool_id == PACE_GUARDIAN_TOOL_ID
    assert result.sources[0].top_result_summary["decision"] == "NO_GO"
    assert result.sources[0].top_result_summary["pace_guardian"][
        "average_pace_used"
    ] is False
    assert result.decision_output["answerSourceToolId"] == PACE_GUARDIAN_TOOL_ID
    assert result.decision_output["decision"] == "NO_GO"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["firstLayer"]["decision"] == (
        "不建議用目前腳程資料繼續判斷。"
    )
    assert "不要用平均腳程" in result.decision_output["firstLayer"]["limit"]
    assert "member_pace_profile" in result.sources[0].missing_fields
    assert "腳程守門員" in result.answer


def test_answer_synthesis_routes_slowest_member_original_plan_to_pace_guardian() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "隊伍最慢的人比預估慢很多，可以繼續原計畫嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.completed_source_count == 1
    assert result.sources[0].tool_id == PACE_GUARDIAN_TOOL_ID
    assert result.decision_output["answerSourceToolId"] == PACE_GUARDIAN_TOOL_ID
    assert result.decision_output["decision"] == "NO_GO"
    assert result.decision_output["allowed"] is False
    assert "member_pace_profile" in result.sources[0].missing_fields
    assert "腳程守門員" in result.answer


def test_answer_synthesis_prioritizes_pace_guardian_for_delayed_summit() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "我們晚了 30 分鐘，還可以繼續攻頂嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=6,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.completed_source_count == 2
    assert result.missing_evidence_count == 2
    pace = _source(result, PACE_GUARDIAN_TOOL_ID)
    contextual = _source(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert pace.top_result_summary["decision"] == "NO_GO"
    assert pace.top_result_summary["schedule_pressure"]["current_delay_minutes"] == 30.0
    assert contextual.top_result_summary["action"] == "summit"
    assert result.decision_output["answerSourceToolId"] == PACE_GUARDIAN_TOOL_ID
    assert result.decision_output["action"] == "pace_adjustment"
    assert result.decision_output["decision"] == "NO_GO"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["cost"]["scheduleDelayMinutes"] == 30.0
    assert result.decision_output["firstLayer"]["decision"] == "不建議繼續攻頂。"
    assert "目前已落後約 30 分鐘" in result.decision_output["firstLayer"]["reason"]
    assert "腳程守門員" in result.answer
    assert "runtime safety truth" in result.answer


def test_answer_synthesis_blocks_daylight_summit_pressure() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "我們快摸黑了，但山頂只差一點，可以趕一下攻頂嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=6,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.completed_source_count == 2
    weather = _source(result, WEATHER_WINDOW_TOOL_ID)
    contextual = _source(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert weather.top_result_summary["decision"] == "DELAY"
    assert "route_weather_package" in weather.missing_fields
    assert contextual.top_result_summary["action"] == "summit"
    assert contextual.top_result_summary["decision"] == "NO_GO"
    assert "remaining_safety_buffer_minutes" in contextual.missing_fields
    assert result.decision_output["answerSourceToolId"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.decision_output["action"] == "summit"
    assert result.decision_output["decision"] == "NO_GO"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["firstLayer"]["decision"] == "不建議攻頂。"
    assert "不要繼續攻頂" in result.decision_output["firstLayer"]["nextStep"]
    assert "天氣決策" in result.answer
    assert "runtime safety truth" in result.answer


def test_answer_synthesis_uses_route_architecture_field_answer_without_guessing() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "下一個撤退點在哪？這條路線難點在哪？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    assert result.answerability == "evidence_available"
    assert result.completed_source_count == 1
    assert result.missing_evidence_count == 0
    assert result.sources[0].tool_id == ROUTE_ARCHITECTURE_TOOL_ID
    assert result.sources[0].top_result_summary["answerability"] == (
        "route_architecture_available"
    )
    assert result.sources[0].top_result_summary["decision"] == "CONDITIONAL_GO"
    assert result.sources[0].top_result_summary["decision_output"][
        "decisionObjectSchema"
    ] == "ContextualPermission"
    assert result.sources[0].top_result_summary["route_architecture"]["role"] == (
        "Route Architecture Intelligence"
    )
    assert result.sources[0].top_result_summary["cp_graph"]["node_count"] == 124
    assert result.decision_output["answerSourceToolId"] == ROUTE_ARCHITECTURE_TOOL_ID
    assert result.decision_output["decision"] == "CONDITIONAL_GO"
    assert result.decision_output["firstLayer"]["decision"] == (
        "可依 CP Graph 推進，但必須保留折返窗口。"
    )
    assert "路線結構判斷" in result.answer
    assert "CP Graph" in result.answer
    assert "runtime safety truth" in result.answer


def test_answer_synthesis_uses_route_architecture_for_turnback_status() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "現在是不是折返點？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.completed_source_count == 1
    assert result.missing_evidence_count == 1
    assert result.sources[0].tool_id == ROUTE_ARCHITECTURE_TOOL_ID
    assert result.sources[0].missing_fields == ["current_cp_id", "current_time"]
    assert result.sources[0].top_result_summary["answerability"] == (
        "route_architecture_missing_current_context"
    )
    assert result.sources[0].top_result_summary["decision"] == "DELAY"
    assert result.decision_output["answerSourceToolId"] == ROUTE_ARCHITECTURE_TOOL_ID
    assert result.decision_output["decision"] == "DELAY"
    assert result.decision_output["firstLayer"]["decision"] == (
        "無法確認現在是否為折返點。"
    )
    assert "current_cp_id、current_time" in result.answer
    assert "雲海保線所" in result.decision_output["firstLayer"]["reason"]
    assert "runtime safety truth" in result.answer


def test_answer_synthesis_detects_natural_turnback_current_context() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "現在 2013-10-08T15:10:00+08:00 在雲海保線所，現在是不是折返點？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    assert result.answerability == "evidence_available"
    route = _source(result, ROUTE_ARCHITECTURE_TOOL_ID)
    assert route.missing_fields == []
    assert route.top_result_summary["answerability"] == "route_architecture_available"
    assert route.top_result_summary["decision"] == "CHANGE_PLAN"
    assert result.decision_output["answerSourceToolId"] == ROUTE_ARCHITECTURE_TOOL_ID
    assert result.decision_output["decision"] == "CHANGE_PLAN"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["firstLayer"]["decision"] == (
        "不建議照原路線往後段推進。"
    )
    assert "current_time is at or past" in result.decision_output["firstLayer"][
        "reason"
    ]
    assert "current CP matches" in result.decision_output["firstLayer"]["reason"]
    assert result.decision_output["runtimeSafetyTruth"] is False
    assert "runtime safety truth" in result.answer


def test_answer_synthesis_detects_local_clock_turnback_context() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "現在 15:10 在雲海保線所，現在是不是折返點？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    assert result.answerability == "evidence_available"
    route = _source(result, ROUTE_ARCHITECTURE_TOOL_ID)
    assert route.missing_fields == []
    assert route.top_result_summary["decision"] == "CHANGE_PLAN"
    assert result.decision_output["answerSourceToolId"] == ROUTE_ARCHITECTURE_TOOL_ID
    assert result.decision_output["decision"] == "CHANGE_PLAN"
    assert "current_time is at or past" in result.decision_output["firstLayer"][
        "reason"
    ]
    assert "current CP matches" in result.decision_output["firstLayer"]["reason"]
    assert result.decision_output["runtimeSafetyTruth"] is False
    assert "runtime safety truth" in result.answer


def test_answer_synthesis_uses_live_navigation_field_answer_without_guessing() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "我現在是不是偏離路線？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.completed_source_count == 1
    assert result.missing_evidence_count == 1
    assert result.sources[0].tool_id == LIVE_NAVIGATION_STATE_TOOL_ID
    assert result.sources[0].top_result_summary["decision"] == "DELAY"
    assert result.sources[0].top_result_summary["navigation_terrain"]["role"] == (
        "Navigation & Terrain Intelligence"
    )
    assert result.sources[0].top_result_summary["decision_output"][
        "decisionObjectSchema"
    ] == "ContextualPermission"
    assert result.decision_output["decisionObjectSchema"] == "ContextualPermission"
    assert result.decision_output["answerSourceToolId"] == LIVE_NAVIGATION_STATE_TOOL_ID
    assert result.decision_output["decision"] == "DELAY"
    assert result.decision_output["firstLayer"]["decision"] == (
        "暫緩判斷，先取得可靠位置。"
    )
    assert result.decision_output["secondLayer"]["uncertaintyNotes"]
    assert "lat" in result.sources[0].missing_fields
    assert "地形導航判斷" in result.answer
    assert "runtime safety truth" in result.answer


def test_answer_synthesis_uses_ins_dr_trace_decision_output() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "GPS-only 軌跡和 INS/DR 軌跡差多少？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.completed_source_count == 1
    assert result.missing_evidence_count == 1
    source = _source(result, INS_DR_TRACE_TOOL_ID)
    assert source.top_result_summary["decision"] == "DELAY"
    assert source.top_result_summary["decision_output"]["decisionObjectSchema"] == (
        "ContextualPermission"
    )
    assert source.top_result_summary["ins_dr_trace"]["role"] == (
        "Navigation Truth / INS-DR Trace Guard"
    )
    assert result.decision_output["answerSourceToolId"] == INS_DR_TRACE_TOOL_ID
    assert result.decision_output["decision"] == "DELAY"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["firstLayer"]["decision"] == (
        "暫緩 INS/DR trace 判斷。"
    )
    assert "ins_dr_estimates_jsonl" in source.missing_fields
    assert "INS/DR trace decision: DELAY" in result.answer
    assert "not runtime safety truth" in result.answer


def test_answer_synthesis_uses_equipment_resource_field_answer_without_guessing() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "手機電量和頭燈水量夠嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.completed_source_count == 1
    assert result.missing_evidence_count == 1
    assert result.sources[0].tool_id == EQUIPMENT_RESOURCE_TOOL_ID
    assert result.sources[0].top_result_summary["decision"] == "DELAY"
    assert result.sources[0].top_result_summary["decision_output"][
        "decisionObjectSchema"
    ] == "ContextualPermission"
    assert result.sources[0].top_result_summary["equipment_resource"]["role"] == (
        "Equipment / Resource Intelligence"
    )
    assert result.decision_output["answerSourceToolId"] == EQUIPMENT_RESOURCE_TOOL_ID
    assert result.decision_output["decision"] == "DELAY"
    assert result.decision_output["firstLayer"]["decision"] == (
        "建議延後裝備資源判斷。"
    )
    assert "water_liters" in result.sources[0].missing_fields
    assert "裝備資源判斷" in result.answer
    assert "runtime safety truth" in result.answer


def test_answer_synthesis_blocks_continuing_with_dead_phone_even_if_watch_has_battery() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "如果手機沒電但手錶還有電，可以繼續嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.completed_source_count == 1
    assert result.sources[0].tool_id == EQUIPMENT_RESOURCE_TOOL_ID
    assert result.sources[0].top_result_summary["decision"] == "NO_GO"
    assert result.sources[0].top_result_summary["resource_state"][
        "phone_battery_percent"
    ] == 0.0
    assert result.decision_output["answerSourceToolId"] == EQUIPMENT_RESOURCE_TOOL_ID
    assert result.decision_output["decision"] == "NO_GO"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["firstLayer"]["decision"] == (
        "不建議照原計畫出發或推進。"
    )
    assert "主要手機已無可用電量" in result.answer
    assert "手錶有電不能單獨取代" in result.answer
    assert "runtime safety truth" in result.answer


def test_answer_synthesis_blocks_autonomous_departure_without_offline_map() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "我沒下載離線地圖，可以自主出發嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    source_ids = {source.tool_id for source in result.sources}
    assert ROUTE_READINESS_TOOL_ID in source_ids
    assert EQUIPMENT_RESOURCE_TOOL_ID in source_ids
    assert MAP_PERCEPTION_TOOL_ID not in source_ids

    equipment = _source(result, EQUIPMENT_RESOURCE_TOOL_ID)
    assert equipment.top_result_summary["decision"] == "NO_GO"
    assert equipment.top_result_summary["resource_state"]["offline_map_ready"] is False
    assert "離線地圖未就緒。" in equipment.top_result_summary["critical_gaps"]

    assert result.decision_output["answerSourceToolId"] == EQUIPMENT_RESOURCE_TOOL_ID
    assert result.decision_output["decision"] == "NO_GO"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["firstLayer"]["decision"] == (
        "不建議照原計畫出發或推進。"
    )
    assert "不得照原計畫出發" in result.decision_output["firstLayer"]["limit"]
    assert "離線地圖未就緒" in result.answer
    assert "runtime safety truth" in result.answer


def test_answer_synthesis_blocks_autonomous_navigation_without_backup_positioning() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "這條路地圖力需求很高，但我們沒有第二套定位備援，可以自己去嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    source_ids = {source.tool_id for source in result.sources}
    assert NAVIGATION_TERRAIN_TOOL_ID in source_ids
    assert ROUTE_READINESS_TOOL_ID in source_ids
    assert MAP_PERCEPTION_TOOL_ID not in source_ids

    navigation = _source(result, NAVIGATION_TERRAIN_TOOL_ID)
    assert navigation.top_result_summary["decision"] == "GUIDED_ONLY"
    assert navigation.top_result_summary["positioning_readiness"][
        "backup_positioning_available"
    ] is False

    assert result.decision_output["answerSourceToolId"] == NAVIGATION_TERRAIN_TOOL_ID
    assert result.decision_output["decision"] == "GUIDED_ONLY"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["firstLayer"]["decision"] == "不建議自主前往。"
    assert "不得自主出發" in result.decision_output["firstLayer"]["limit"]
    assert "地圖力判斷" in result.answer
    assert "定位備援" in result.answer
    assert "runtime safety truth" in result.answer


def test_answer_synthesis_blocks_autonomous_navigation_with_low_map_literacy() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "我不會看等高線，也不知道撤退方向，可以自主前往嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    navigation = _source(result, NAVIGATION_TERRAIN_TOOL_ID)
    assert navigation.top_result_summary["decision"] == "GUIDED_ONLY"
    assert result.decision_output["answerSourceToolId"] == NAVIGATION_TERRAIN_TOOL_ID
    assert result.decision_output["firstLayer"]["decision"] == "不建議自主前往。"
    assert "等高線" in result.answer
    assert "撤退方向" in result.answer


def test_answer_synthesis_uses_route_readiness_field_answer_without_guessing() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "出發前 Go/No-Go 可以出發嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.completed_source_count == 1
    assert result.missing_evidence_count == 1
    assert result.sources[0].tool_id == ROUTE_READINESS_TOOL_ID
    assert result.sources[0].top_result_summary["decision"] == "DELAY"
    assert result.sources[0].top_result_summary["route_readiness"]["role"] == (
        "Pre-Trip Route Readiness / Departure Gate"
    )
    assert result.sources[0].top_result_summary["decision_output"][
        "decisionObjectSchema"
    ] == "ContextualPermission"
    assert result.sources[0].top_result_summary["decision_output"]["decision"] == (
        "DELAY"
    )
    package = result.sources[0].top_result_summary["pretrip_decision_package"]
    assert package["required_outputs"]["pretrip_decision"] == "DELAY"
    assert package["required_outputs"]["top_risk_sources"]
    assert result.decision_output["decisionObjectSchema"] == "ContextualPermission"
    assert result.decision_output["answerSourceToolId"] == ROUTE_READINESS_TOOL_ID
    assert result.decision_output["decision"] == "DELAY"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["firstLayer"]["decision"] == "建議延後。"
    assert "不得出發" in result.decision_output["firstLayer"]["limit"]
    assert result.decision_output["firstLayer"]["reason"]
    assert result.decision_output["firstLayer"]["nextStep"]
    assert result.decision_output["secondLayer"]["requiredConditions"]
    assert result.decision_output["runtimeSafetyTruth"] is False
    assert "user_experience_level" in result.sources[0].missing_fields
    assert "出發前判斷" in result.answer
    assert "標準出發前決策包" in result.answer
    assert "前三風險" in result.answer
    assert "必補條件" in result.answer
    assert "停留限制" in result.answer
    assert "runtime safety truth" in result.answer


def test_answer_synthesis_changes_plan_for_latest_return_limit() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "最晚回程接駁是 16:30，這個行程可以嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.completed_source_count == 1
    source = result.sources[0]
    assert source.tool_id == ROUTE_READINESS_TOOL_ID
    assert source.top_result_summary["decision"] == "CHANGE_PLAN"
    deadline = source.top_result_summary["readiness_governance"][
        "transport_deadline"
    ]
    assert deadline["resolved_deadline"] == "2013-10-08T16:30:00+08:00"
    assert deadline["target_eta"] == "2013-10-08T18:28:50+08:00"
    assert deadline["conflict"] is True
    assert result.decision_output["answerSourceToolId"] == ROUTE_READINESS_TOOL_ID
    assert result.decision_output["decision"] == "CHANGE_PLAN"
    assert result.decision_output["firstLayer"]["decision"] == "建議改變計畫。"
    assert "Target ETA 2013-10-08T18:28:50+08:00" in result.decision_output[
        "firstLayer"
    ]["reason"]
    assert result.decision_output["cost"]["latestReturnDeadline"] == (
        "2013-10-08T16:30:00+08:00"
    )
    assert result.decision_output["runtimeSafetyTruth"] is False


def test_answer_synthesis_surfaces_pretrip_stop_policy() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "哪裡是不建議停留點？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.completed_source_count == 1
    source = result.sources[0]
    assert source.tool_id == ROUTE_READINESS_TOOL_ID
    assert source.top_result_summary["decision"] == "DELAY"
    package = source.top_result_summary["pretrip_decision_package"]
    required = package["required_outputs"]
    assert required["suggested_stop_points"][0]["label"] == "雲海保線所"
    assert required["suggested_stop_points"][0]["policy"] == (
        "turnaround_or_reassess"
    )
    assert "Unplanned photo" in required["not_recommended_stop_points"][0]["label"]
    assert required["not_recommended_stop_points"][0]["policy"] == (
        "not_recommended_until_reviewed"
    )
    assert result.decision_output["answerSourceToolId"] == ROUTE_READINESS_TOOL_ID
    assert result.decision_output["decision"] == "DELAY"
    assert result.decision_output["runtimeSafetyTruth"] is False
    assert "標準出發前決策包" in result.answer
    assert "停留限制" in result.answer
    assert "runtime safety truth" in result.answer


def test_answer_synthesis_preserves_guided_only_route_readiness_decision() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "beginner transportconfirmed slowestbasisconfirmed "
        "departuretimeconfirmed wxconfirmed sunok gearconfirmed rcconfirmed "
        "pretrip Go/No-Go 可以自主出發嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "evidence_available"
    assert result.completed_source_count == 1
    assert result.missing_evidence_count == 0
    assert result.sources[0].tool_id == ROUTE_READINESS_TOOL_ID
    assert result.sources[0].top_result_summary["decision"] == "GUIDED_ONLY"
    assert result.sources[0].top_result_summary["guided_only_gate"]["required"] is True
    assert result.sources[0].top_result_summary["route_demand_profile"][
        "route_demand"
    ] == "high"
    package = result.sources[0].top_result_summary["pretrip_decision_package"]
    assert package["required_outputs"]["pretrip_decision"] == "GUIDED_ONLY"
    assert package["decision_limits"]["autonomous_departure_allowed"] is False
    assert result.decision_output["answerSourceToolId"] == ROUTE_READINESS_TOOL_ID
    assert result.decision_output["decision"] == "GUIDED_ONLY"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["firstLayer"]["decision"] == (
        "只建議在合格帶領下進入。"
    )
    assert "不得自主出發" in result.decision_output["firstLayer"]["limit"]
    assert "GUIDED_ONLY" in result.answer
    assert "不建議自主出發" in result.answer
    assert "runtime safety truth" in result.answer


def test_answer_synthesis_uses_media_literacy_field_answer_without_guessing() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "IG 大崩壁美照會不會誤導？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.completed_source_count >= 1
    assert result.missing_evidence_count == 2
    source = _source(result, MEDIA_LITERACY_TOOL_ID)
    terrain_source = _source(result, TERRAIN_SCORE_TOOL_ID)
    assert source.top_result_summary["decision"] == "NO_GO"
    assert terrain_source.top_result_summary["decision"] == "DELAY"
    assert "terrain_score_results" in terrain_source.missing_fields
    assert source.top_result_summary["media_literacy"]["role"] == (
        "Media Literacy / Bias Sentinel"
    )
    assert source.top_result_summary["decision_output"]["decisionObjectSchema"] == (
        "ContextualPermission"
    )
    assert result.decision_output["decisionObjectSchema"] == "ContextualPermission"
    assert result.decision_output["answerSourceToolId"] == MEDIA_LITERACY_TOOL_ID
    assert result.decision_output["decision"] == "NO_GO"
    assert result.decision_output["firstLayer"]["decision"] == (
        "不建議為媒體點位停留或改線。"
    )
    assert "不得為拍照" in result.decision_output["firstLayer"]["limit"]
    assert result.decision_output["secondLayer"]["alternativeActions"]
    assert "fresh_weather_or_route_condition_review" in source.missing_fields
    assert "媒體識讀判斷" in result.answer
    assert "runtime safety truth" in result.answer


def test_answer_synthesis_prioritizes_media_literacy_for_social_detour() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "大家都說旁邊那個點很好拍，可以繞去嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=5,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    media = _source(result, MEDIA_LITERACY_TOOL_ID)
    contextual = _source(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert media.top_result_summary["action"] == "reroute"
    assert media.top_result_summary["decision"] == "NO_GO"
    assert media.top_result_summary["decision_output"]["action"] == "reroute"
    assert contextual.top_result_summary["action"] == "reroute"
    assert contextual.top_result_summary["decision"] in {"NO_GO", "CHANGE_PLAN"}
    assert result.decision_output["answerSourceToolId"] == MEDIA_LITERACY_TOOL_ID
    assert result.decision_output["action"] == "reroute"
    assert result.decision_output["decision"] == "NO_GO"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["firstLayer"]["decision"] == (
        "不建議為媒體點位停留或改線。"
    )
    assert "媒體識讀判斷" in result.answer
    assert "beauty_photo_bias" in result.answer
    assert "runtime safety truth" in result.answer


def test_answer_synthesis_blocks_seasonal_photo_detour_with_buffer() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "看到乾季晴天美照，但今天濕滑又只剩 18 分鐘 buffer，可以繞去拍嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=5,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    media = _source(result, MEDIA_LITERACY_TOOL_ID)
    contextual = _source(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert media.top_result_summary["decision"] == "NO_GO"
    assert media.top_result_summary["media_bias_analysis"]["input_state"][
        "remaining_safety_buffer_minutes"
    ] == 18
    assert media.top_result_summary["media_bias_analysis"]["input_state"][
        "route_condition_reviewed"
    ] is True
    assert contextual.top_result_summary["action"] == "reroute"
    assert contextual.top_result_summary["decision"] == "NO_GO"
    assert contextual.top_result_summary["allowed"] is False
    assert result.decision_output["answerSourceToolId"] == MEDIA_LITERACY_TOOL_ID
    assert result.decision_output["decision"] == "NO_GO"
    assert result.decision_output["allowed"] is False
    assert "season_weather_bias" in result.answer
    assert "runtime safety truth" in result.answer


def test_answer_synthesis_blocks_exposed_photo_pressure() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "前方是高曝露陡坡，但照片很好看，可以去拍嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=5,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    media = _source(result, MEDIA_LITERACY_TOOL_ID)
    contextual = _source(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    terrain = _source(result, TERRAIN_SCORE_TOOL_ID)
    assert media.top_result_summary["action"] == "photo"
    assert media.top_result_summary["decision"] == "NO_GO"
    assert contextual.top_result_summary["action"] == "photo"
    assert contextual.top_result_summary["decision"] == "NO_GO"
    assert terrain.top_result_summary["decision"] == "DELAY"
    assert result.decision_output["answerSourceToolId"] == MEDIA_LITERACY_TOOL_ID
    assert result.decision_output["action"] == "photo"
    assert result.decision_output["decision"] == "NO_GO"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["firstLayer"]["decision"] == (
        "不建議為媒體點位停留或改線。"
    )
    assert "媒體識讀判斷" in result.answer
    assert "beauty_photo_bias" in result.answer
    assert "runtime safety truth" in result.answer


def test_answer_synthesis_uses_survival_playbook_field_answer_without_guessing() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "不確定自己在哪，可以下切溪谷找路嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.completed_source_count >= 1
    assert result.missing_evidence_count >= 1
    source = _source(result, SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID)
    assert source.top_result_summary["decision"] == "NO_GO"
    assert source.top_result_summary["decision_output"]["decisionObjectSchema"] == (
        "ContextualPermission"
    )
    assert source.top_result_summary["survival_incident_playbook"]["role"] == (
        "Risk Sentinel / Survival Incident Playbook"
    )
    assert source.top_result_summary["incident_triage"]["scenario"] == (
        "lost_or_position_uncertain"
    )
    assert "current_location_status" in source.missing_fields
    assert result.decision_output["answerSourceToolId"] == (
        SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID
    )
    assert result.decision_output["decision"] == "NO_GO"
    assert result.decision_output["firstLayer"]["decision"] == (
        "不建議繼續移動或下切找路。"
    )
    assert "求生事件 playbook" in result.answer
    assert "發送 SOS" in result.answer
    assert "runtime safety truth" in result.answer


def test_answer_synthesis_uses_team_status_field_answer_without_guessing() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "後隊在哪？最後一次有效位置多久前？留守回報準備好了嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.completed_source_count == 1
    assert result.missing_evidence_count == 1
    assert result.sources[0].tool_id == TEAM_STATUS_TOOL_ID
    assert result.sources[0].top_result_summary["decision"] == "DELAY"
    assert result.sources[0].top_result_summary["decision_output"][
        "decisionObjectSchema"
    ] == "ContextualPermission"
    assert result.sources[0].top_result_summary["team_status_guardian"]["role"] == (
        "Team Status / Remote Contact Governance"
    )
    assert result.decision_output["answerSourceToolId"] == TEAM_STATUS_TOOL_ID
    assert result.decision_output["decision"] == "DELAY"
    assert result.decision_output["firstLayer"]["decision"] == (
        "建議延後隊伍狀態判斷。"
    )
    assert "member_positions_or_last_heard" in result.sources[0].missing_fields
    assert "隊伍守門員" in result.answer
    assert "runtime safety truth" in result.answer


def test_answer_synthesis_escalates_unanswered_teammate_message_without_outbound() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "隊友已經 55 分鐘沒回訊息，要怎麼辦？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.completed_source_count == 1
    assert result.sources[0].tool_id == TEAM_STATUS_TOOL_ID
    assert result.sources[0].top_result_summary["decision"] == "ESCALATE"
    assert result.sources[0].top_result_summary["decision_output"]["cost"][
        "checkinOverdueMinutes"
    ] == 55.0
    assert result.sources[0].top_result_summary["team_status_guardian"][
        "outbound_send_performed"
    ] is False
    assert result.decision_output["answerSourceToolId"] == TEAM_STATUS_TOOL_ID
    assert result.decision_output["decision"] == "ESCALATE"
    assert result.decision_output["firstLayer"]["decision"] == (
        "停止推進並升級人工確認。"
    )
    assert "不得自動通知留守人" in result.decision_output["firstLayer"]["limit"]
    assert "runtime safety truth" in result.answer


def test_answer_synthesis_uses_post_trip_review_field_answer_without_guessing() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "行後回顧要更新哪些下一次規劃？實際耗時哪裡比預期慢？",
        project_root=POST_ANALYSIS_ROOT,
        project_id="chilai_nanhua_day1_post_analysis",
        limit=3,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.completed_source_count == 1
    assert result.missing_evidence_count == 1
    assert result.sources[0].tool_id == POST_TRIP_REVIEW_TOOL_ID
    assert result.sources[0].top_result_summary["decision"] == "DELAY"
    assert result.sources[0].top_result_summary["decision_output"][
        "decisionObjectSchema"
    ] == "ContextualPermission"
    assert result.sources[0].top_result_summary["post_trip_learning_package"][
        "role"
    ] == "Post-Trip Learning Proposal"
    assert result.sources[0].top_result_summary["post_trip_review"]["role"] == (
        "Post-Trip Review / Learning Governance"
    )
    assert result.decision_output["decisionObjectSchema"] == "ContextualPermission"
    assert result.decision_output["answerSourceToolId"] == POST_TRIP_REVIEW_TOOL_ID
    assert result.decision_output["decision"] == "DELAY"
    assert result.decision_output["firstLayer"]["decision"] == "暫緩學習寫回。"
    assert result.decision_output["runtimeSafetyTruth"] is False
    assert "subjective_difficulty" in result.sources[0].missing_fields
    assert "行後回顧" in result.answer
    assert "runtime safety truth" in result.answer


def test_answer_synthesis_routes_trip_end_debrief_to_post_trip_review() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "這次旅行結束後要怎麼檢討？哪些經驗要回寫到下次規劃？",
        project_root=POST_ANALYSIS_ROOT,
        project_id="chilai_nanhua_day1_post_analysis",
        limit=3,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.completed_source_count == 1
    assert result.sources[0].tool_id == POST_TRIP_REVIEW_TOOL_ID
    assert result.decision_output["answerSourceToolId"] == POST_TRIP_REVIEW_TOOL_ID
    assert result.decision_output["decision"] == "DELAY"
    assert result.decision_output["firstLayer"]["decision"] == "暫緩學習寫回。"
    assert result.decision_output["runtimeSafetyTruth"] is False
    assert "subjective_difficulty" in result.sources[0].missing_fields
    assert "行後回顧" in result.answer
    assert "runtime safety truth" in result.answer


def test_answer_synthesis_uses_safety_boundary_decision_output() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "哪些風險目前只是候選，不能觸發 Ln？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.completed_source_count == 3
    assert result.missing_evidence_count == 2
    safety = _source(result, SAFETY_BOUNDARY_TOOL_ID)
    assert safety.top_result_summary["decision"] == "DELAY"
    assert safety.top_result_summary["decision_output"]["decisionObjectSchema"] == (
        "ContextualPermission"
    )
    assert safety.top_result_summary["safety_boundary"]["role"] == (
        "Safety Boundary / Runtime Admission Guard"
    )
    assert result.decision_output["answerSourceToolId"] == SAFETY_BOUNDARY_TOOL_ID
    assert result.decision_output["decision"] == "DELAY"
    assert result.decision_output["allowed"] is False
    assert result.decision_output["runtimeSafetyTruth"] is False
    assert result.decision_output["firstLayer"]["decision"] == (
        "Hold safety-state changes until admission evidence is complete."
    )
    assert "admission_state" in safety.missing_fields
    assert "operator_review_status" in safety.missing_fields
    assert "Safety boundary decision: DELAY" in result.answer
    assert "cannot trigger Ln" in result.answer
    assert "runtime safety truth" in result.answer


def test_answer_synthesis_reports_no_registry_tool_selected_as_insufficient_evidence() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "請用一句話描述登山心情",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "no_registry_tool_selected"
    assert result.evidence_collection_verified is True
    assert result.completed_source_count == 0
    assert result.missing_evidence_count == 0
    assert result.failed_source_count == 0
    assert result.sources == []
    assert result.missing_evidence == []
    assert result.evidence_collection["selected_tool_count"] == 0
    assert result.evidence_collection["evidence_records"] == []
    assert result.synthesis_policy.model_provider_used is False
    assert result.synthesis_policy.model_synthesis_performed is False
    assert "No registry-backed Scout AI tool was selected" in result.answer
    assert "no deterministic evidence" in result.answer
    assert "runtime safety truth" in result.answer
    assert "answerability=no_registry_tool_selected" in result.limitations
    assert result.boundary.runtime_safety_truth is False
    assert result.boundary.live_safety_api_calls_allowed is False


def test_answer_synthesis_accepts_existing_evidence_collection_artifact() -> None:
    evidence_collection = collect_scout_ai_evidence(
        "危險地形在哪些位置?",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=2,
    )

    result = synthesize_scout_ai_answer_from_evidence(evidence_collection)

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.evidence_collection["artifact_kind"] == "scout_ai_evidence_collection"
    assert result.evidence_collection["executed_tool_count"] == 2
    assert result.completed_source_count == 2
    assert result.missing_evidence_count == 1
    terrain_source = _source(result, TERRAIN_SCORE_TOOL_ID)
    assert terrain_source.top_result_summary["decision"] == "DELAY"
    assert "terrain_score_results" in terrain_source.missing_fields


def test_answer_synthesis_builtin_manifest_and_payload_are_read_only(
    tmp_path: Path,
) -> None:
    manifest = load_tool_manifest(MANIFEST_PATH)
    evidence_collection = collect_scout_ai_evidence(
        "危險地形在哪些位置?",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=2,
    )
    request_path = tmp_path / "answer-synthesis-request.json"
    request_path.write_text(
        json.dumps(
            {
                "evidence_collection": evidence_collection.model_dump(mode="json"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    exit_code, payload = run_builtin_tool(
        ["ai-answer-synthesis", "--input", str(request_path), "--json"]
    )

    assert manifest.id == "scout.ai.answer_synthesis.synthesize"
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
    assert payload["evidence_collection_verified"] is True
    assert payload["completed_source_count"] == 2
    assert payload["missing_evidence_count"] == 1
    terrain_source = next(
        source
        for source in payload["sources"]
        if source["tool_id"] == TERRAIN_SCORE_TOOL_ID
    )
    assert terrain_source["top_result_summary"]["decision"] == "DELAY"
    assert "terrain_score_results" in terrain_source["missing_fields"]
    assert payload["synthesis_policy"]["model_provider_used"] is False
    assert payload["synthesis_policy"]["model_synthesis_performed"] is False
    assert payload["boundary"]["read_only"] is True
    assert payload["boundary"]["runtime_safety_truth"] is False
    assert payload["boundary"]["live_safety_api_calls_allowed"] is False
    assert payload["boundary"]["phase1_l0_l4_state_mutated"] is False
    assert payload["boundary"]["outbound_send_performed"] is False
    assert payload["boundary"]["hardware_control_performed"] is False
    assert payload["boundary"]["workspace_file_write_allowed"] is False
    assert payload["boundary"]["model_provider_used"] is False
    assert payload["boundary"]["model_synthesis_performed"] is False


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


def test_answer_synthesis_builtin_rejects_blank_question_without_evidence_collection(
    tmp_path: Path,
) -> None:
    request_path = tmp_path / "answer-synthesis-request.json"
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
        ["ai-answer-synthesis", "--input", str(request_path), "--json"]
    )

    assert exit_code == 2
    assert payload["status"] == "failed"
    assert "non-empty question" in payload["error"]
    assert payload["boundary"]["runtime_safety_truth"] is False


def _write_route_briefing_project(tmp_path: Path) -> Path:
    project_root = tmp_path / "route_briefing_project"
    project_root.mkdir()
    route_briefing_fixture = (
        ROOT
        / "tests"
        / "fixtures"
        / "pretrip"
        / "route_briefing"
        / "chilai_nanhua_research.json"
    )
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "project_id": "chilai_nanhua_briefing",
                "route_briefing_research_ref": str(route_briefing_fixture),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return project_root


def _source(result, tool_id: str):
    matches = [source for source in result.sources if source.tool_id == tool_id]
    assert len(matches) == 1, result.model_dump(mode="json")
    return matches[0]
