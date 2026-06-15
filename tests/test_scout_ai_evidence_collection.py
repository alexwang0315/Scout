import json
from pathlib import Path

from scout_agent_builtin_tools import run_builtin_tool
from scout_agent_tools import load_tool_manifest
from scout_ai_evidence_collection import (
    ARTIFACT_KIND,
    ARTIFACT_VERSION,
    collect_scout_ai_evidence,
)
from scout_ai_tool_planner import (
    ENERGY_VITALS_TOOL_ID,
    LIVE_NAVIGATION_STATE_TOOL_ID,
    WEATHER_WINDOW_TOOL_ID,
)
from scout_route_readiness_tool import ROUTE_READINESS_TOOL_ID
from scout_pace_guardian_tool import PACE_GUARDIAN_TOOL_ID
from scout_equipment_resource_tool import EQUIPMENT_RESOURCE_TOOL_ID
from scout_team_status_tool import TEAM_STATUS_TOOL_ID
from scout_post_trip_review_tool import POST_TRIP_REVIEW_TOOL_ID
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


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
POST_ANALYSIS_ROOT = (
    ROOT / "tests" / "fixtures" / "post_analysis" / "chilai_nanhua_day1_post_analysis"
)
MANIFEST_PATH = (
    ROOT
    / "tools"
    / "scout_agent_tool_manifests"
    / "scout.ai.evidence_collection.collect.json"
)


def test_evidence_collection_executes_ready_risk_and_terrain_tools() -> None:
    result = collect_scout_ai_evidence(
        "危險地形在哪些位置?",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.artifact_kind == ARTIFACT_KIND
    assert result.artifact_version == ARTIFACT_VERSION
    assert result.project_id == "chilai_nanhua_day1"
    assert result.discovery_plan["artifact_kind"] == "scout_ai_workflow_discovery_plan"
    assert result.selected_tool_count == 2
    assert result.executed_tool_count == 2
    assert result.completed_tool_count == 2
    assert result.contract_gap_count == 0
    assert result.failed_tool_count == 0
    assert result.execution_policy.ready_tools_executed is True
    assert result.execution_policy.model_synthesis_performed is False
    assert result.execution_policy.workspace_file_write_allowed is False
    assert result.boundary.runtime_safety_truth is False
    assert result.boundary.live_safety_api_calls_allowed is False

    risk = _record(result, RISK_SCORE_TOOL_ID)
    terrain = _record(result, TERRAIN_SCORE_TOOL_ID)
    for record in (risk, terrain):
        assert record.collection_status == "completed"
        assert record.result is not None
        assert record.result["status"] == "completed"
        assert "result_count" in record.result["payload"]
        assert record.result["payload"]["results_truncated"] is False
        assert record.result["boundary"]["runtime_safety_truth"] is False
    assert risk.result["payload"]["result_count"] >= 1
    assert risk.result["payload"]["results"]
    assert risk.result["payload"]["decision"] == "CHANGE_PLAN"
    assert risk.result["payload"]["decision_output"]["decisionObjectSchema"] == (
        "ContextualPermission"
    )
    assert risk.result["payload"]["decision_output"]["firstLayer"]["decision"] == (
        "建議改變路線或通過策略。"
    )
    assert risk.result["payload"]["risk_decision"]["highest_risk_result"][
        "risk_bucket"
    ] == "high"
    assert terrain.result["payload"]["answerability"] == "terrain_score_missing_evidence"
    assert terrain.result["payload"]["decision"] == "DELAY"
    assert terrain.result["payload"]["decision_output"]["decisionObjectSchema"] == (
        "ContextualPermission"
    )
    assert terrain.result["payload"]["decision_output"]["firstLayer"]["decision"] == (
        "暫緩地形分數判斷。"
    )
    assert "terrain_score_results" in terrain.missing_fields
    assert terrain.result["payload"]["summaries"]


def test_evidence_collection_executes_weather_tool_without_model_synthesis() -> None:
    result = collect_scout_ai_evidence(
        "明天午後雷雨是否要紮營?",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.selected_tool_count >= 1
    assert result.executed_tool_count >= 1
    assert result.completed_tool_count >= 1
    assert result.contract_gap_count == 0
    assert result.execution_policy.ready_tools_executed is True
    assert result.execution_policy.model_synthesis_performed is False

    weather = _record(result, WEATHER_WINDOW_TOOL_ID)
    assert weather.collection_status == "completed"
    assert weather.result is not None
    assert weather.result["status"] == "completed"
    assert weather.result["payload"]["answerability"] == "weather_placeholder_only"
    assert weather.result["payload"]["source_status"] == "candidate_only"
    assert weather.result["payload"]["result_count"] == 0
    assert "provider" in weather.missing_fields
    assert "ttl_s" in weather.missing_fields
    assert "route_weather_package" in weather.missing_fields
    assert weather.implementation_gap is None
    assert weather.boundary.runtime_safety_truth is False


def test_evidence_collection_keeps_map_perception_decision_output() -> None:
    result = collect_scout_ai_evidence(
        "CP001 附近有沒有標註?",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    map_perception = _record(result, MAP_PERCEPTION_TOOL_ID)
    payload = map_perception.result["payload"]
    assert payload["answerability"] == "map_perception_evidence_available"
    assert payload["decision"] == "CONDITIONAL_GO"
    assert payload["decision_output"]["decisionObjectSchema"] == "ContextualPermission"
    assert payload["decision_output"]["decision"] == "CONDITIONAL_GO"
    assert payload["decision_output"]["firstLayer"]["decision"] == (
        "可作為候選地圖參考。"
    )
    assert payload["map_perception"]["role"] == (
        "Navigation & Terrain Intelligence / Map Perception"
    )
    assert payload["map_perception"]["top_material"]["evidence_type"] == "ocr_label"
    assert map_perception.missing_fields == []
    assert map_perception.boundary.runtime_safety_truth is False


def test_evidence_collection_keeps_energy_vitals_decision_output() -> None:
    result = collect_scout_ai_evidence(
        "我現在心率偏高又很累，需要休息嗎?",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    energy = _record(result, ENERGY_VITALS_TOOL_ID)
    assert energy.collection_status == "completed"
    assert energy.result is not None
    payload = energy.result["payload"]
    assert payload["answerability"] == "energy_vitals_missing_required_fields"
    assert payload["decision"] == "DELAY"
    assert payload["decision_output"]["decisionObjectSchema"] == "ContextualPermission"
    assert payload["decision_output"]["decision"] == "DELAY"
    assert payload["decision_output"]["allowed"] is False
    assert payload["decision_output"]["runtimeSafetyTruth"] is False
    assert payload["decision_output"]["firstLayer"]["decision"] == (
        "建議延後體能/穿戴判斷。"
    )
    assert "heart_rate_bpm" in energy.missing_fields
    assert energy.boundary.runtime_safety_truth is False


def test_evidence_collection_keeps_weather_to_decision_payload(tmp_path: Path) -> None:
    project_root = _write_route_weather_project(tmp_path)

    result = collect_scout_ai_evidence(
        "午後雷雨是否要改變計畫?",
        project_root=project_root,
        project_id="weather_decision_project",
        limit=3,
    )

    weather = _record(result, WEATHER_WINDOW_TOOL_ID)
    assert weather.collection_status == "completed"
    assert weather.result is not None
    payload = weather.result["payload"]
    assert payload["answerability"] == "route_weather_risk_available"
    assert payload["decision"] == "CHANGE_PLAN"
    assert payload["decision_output"]["decisionObjectSchema"] == "ContextualPermission"
    assert payload["decision_output"]["decision"] == "CHANGE_PLAN"
    assert payload["decision_output"]["firstLayer"]["decision"] == (
        "不建議照原計畫通過。"
    )
    assert payload["field_answer"].startswith("天氣決策")
    assert payload["weather_to_decision"]["role"] == (
        "Risk Sentinel / Weather-to-Decision"
    )
    assert payload["weather_to_decision"]["decision"] == "CHANGE_PLAN"
    assert payload["weather_to_decision"]["highest_risk_segment"]["segment_id"] == (
        "ridge.exposure"
    )
    assert weather.missing_fields == []
    assert weather.boundary.runtime_safety_truth is False


def test_evidence_collection_executes_route_context_tool_without_model_synthesis() -> None:
    result = collect_scout_ai_evidence(
        "下一個觀察點在哪？哪裡適合拍攝大景？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    assert result.selected_tool_count >= 1
    assert result.executed_tool_count >= 1
    assert result.completed_tool_count >= 1
    assert result.contract_gap_count == 0
    assert result.execution_policy.ready_tools_executed is True
    assert result.execution_policy.model_synthesis_performed is False

    route_context = _record(result, ROUTE_CONTEXT_TOOL_ID)
    assert route_context.collection_status == "completed"
    assert route_context.result is not None
    payload = route_context.result["payload"]
    assert payload["answerability"] == "route_context_available"
    assert payload["source_status"] == "candidate_only"
    assert payload["decision"] == "CONDITIONAL_GO"
    assert payload["decision_output"]["decisionObjectSchema"] == "ContextualPermission"
    assert payload["decision_output"]["firstLayer"]["decision"] == "可作為候選觀察點。"
    assert "不是停留授權" in payload["decision_output"]["firstLayer"]["limit"]
    assert payload["route_context"]["role"] == "Experience Guide"
    assert payload["route_context"]["stop_permission_required"] is True
    assert payload["result_count"] >= 1
    assert payload["matched_context_count"] >= 1
    assert any(item["label"] == "稜線啞口觀景點" for item in payload["results"])
    assert route_context.boundary.runtime_safety_truth is False


def test_evidence_collection_keeps_contextual_permission_decision_object() -> None:
    result = collect_scout_ai_evidence(
        "我可以在這裡停下來拍一段影片嗎?",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.missing_input_count == 0

    contextual = _record(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert contextual.collection_status == "completed"
    assert contextual.result is not None
    payload = contextual.result["payload"]
    assert payload["decision"] == "NO_GO"
    assert payload["decision_object"] == payload["contextual_permission"]
    assert payload["decision_output"]["decisionObjectSchema"] == (
        "ContextualPermission"
    )
    assert payload["decision_output"]["firstLayer"]["decision"] == "不建議拍影片。"
    assert payload["field_answer"].startswith("[決策] 不建議拍影片。")
    assert contextual.boundary.runtime_safety_truth is False


def test_evidence_collection_keeps_split_team_micro_decision() -> None:
    result = collect_scout_ai_evidence(
        "可以讓走得快的人先去山頂嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.missing_input_count == 0

    contextual = _record(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert contextual.collection_status == "completed"
    assert contextual.missing_fields == []
    assert contextual.result is not None
    payload = contextual.result["payload"]
    assert payload["answerability"] == "contextual_permission_decision_available"
    assert payload["action"] == "split_team"
    assert payload["decision"] == "NO_GO"
    assert payload["allowed"] is False
    assert payload["decision_output"]["firstLayer"]["decision"] == "不建議分隊。"
    assert contextual.boundary.runtime_safety_truth is False


def test_evidence_collection_keeps_rain_gear_micro_decision() -> None:
    result = collect_scout_ai_evidence(
        "前面下雨了，要不要穿雨衣？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    assert result.selected_tool_count == 3
    assert result.executed_tool_count == 3
    assert result.completed_tool_count == 3
    assert result.missing_input_count == 0

    contextual = _record(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert contextual.collection_status == "completed"
    assert contextual.missing_fields == []
    assert contextual.result is not None
    payload = contextual.result["payload"]
    assert payload["answerability"] == "contextual_permission_decision_available"
    assert payload["action"] == "wear_rain_gear"
    assert payload["decision"] == "GO"
    assert payload["allowed"] is True
    assert payload["decision_output"]["firstLayer"]["decision"] == "可以穿雨具。"
    assert contextual.boundary.runtime_safety_truth is False


def test_evidence_collection_blocks_shortcut_reroute_micro_decision() -> None:
    result = collect_scout_ai_evidence(
        "這個岔路可以切嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=5,
    )

    assert result.selected_tool_count == 3
    assert result.executed_tool_count == 3
    assert result.completed_tool_count == 3
    assert result.missing_input_count == 0

    route = _record(result, ROUTE_ARCHITECTURE_TOOL_ID)
    nav = _record(result, LIVE_NAVIGATION_STATE_TOOL_ID)
    contextual = _record(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert route.collection_status == "completed"
    assert nav.collection_status == "completed"
    assert "lat" in nav.missing_fields
    assert contextual.collection_status == "completed"
    assert contextual.missing_fields == ["remaining_safety_buffer_minutes"]
    assert contextual.result is not None
    payload = contextual.result["payload"]
    assert payload["answerability"] == "contextual_permission_missing_required_fields"
    assert payload["action"] == "reroute"
    assert payload["decision"] == "NO_GO"
    assert payload["allowed"] is False
    assert payload["decision_output"]["firstLayer"]["decision"] == "不建議改線。"
    assert contextual.boundary.runtime_safety_truth is False


def test_evidence_collection_keeps_direct_retreat_micro_decision() -> None:
    result = collect_scout_ai_evidence(
        "隊友很累，要不要直接撤退？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=5,
    )

    assert result.selected_tool_count == 3
    assert result.executed_tool_count == 3
    assert result.completed_tool_count == 3
    assert result.missing_input_count == 0

    energy = _record(result, ENERGY_VITALS_TOOL_ID)
    pace = _record(result, PACE_GUARDIAN_TOOL_ID)
    contextual = _record(result, CONTEXTUAL_PERMISSION_TOOL_ID)
    assert "subject_id" in energy.missing_fields
    assert pace.missing_fields == ["member_pace_profile"]
    assert contextual.collection_status == "completed"
    assert contextual.missing_fields == []
    assert contextual.result is not None
    payload = contextual.result["payload"]
    assert payload["answerability"] == "contextual_permission_decision_available"
    assert payload["action"] == "retreat"
    assert payload["decision"] == "GO"
    assert payload["allowed"] is True
    assert payload["decision_output"]["firstLayer"]["decision"] == "可以撤退。"
    assert contextual.boundary.runtime_safety_truth is False


def test_evidence_collection_executes_pace_guardian_tool_without_model_synthesis(
    tmp_path: Path,
) -> None:
    project_root = _write_team_pace_project(tmp_path)

    result = collect_scout_ai_evidence(
        "隊伍腳程是否能準時抵達下一個 CP？最慢者需要前移午餐點嗎？",
        project_root=project_root,
        project_id="team_pace_project",
        limit=4,
    )

    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.contract_gap_count == 0
    assert result.execution_policy.ready_tools_executed is True
    assert result.execution_policy.model_synthesis_performed is False

    pace = _record(result, PACE_GUARDIAN_TOOL_ID)
    assert pace.collection_status == "completed"
    assert pace.result is not None
    payload = pace.result["payload"]
    assert payload["answerability"] == "pace_fit_decision_available"
    assert payload["source_status"] == "candidate_only"
    assert payload["decision"] == "CHANGE_PLAN"
    assert payload["decision_output"]["decisionObjectSchema"] == "ContextualPermission"
    assert payload["decision_output"]["decision"] == "CHANGE_PLAN"
    assert payload["decision_output"]["firstLayer"]["decision"] == (
        "不建議照原計畫推進。"
    )
    assert payload["pace_guardian"]["role"] == "Pace Guardian"
    assert payload["pace_guardian"]["average_pace_used"] is False
    assert payload["team_pace_fit"]["slowest_member"]["label"] == "New teammate"
    assert payload["team_pace_fit"]["pace_gap_ratio"] == 1.92
    assert pace.boundary.runtime_safety_truth is False


def test_evidence_collection_keeps_route_architecture_cp_graph_payload() -> None:
    result = collect_scout_ai_evidence(
        "下一個撤退點在哪？這條路線難點在哪？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=4,
    )

    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.contract_gap_count == 0
    assert result.execution_policy.ready_tools_executed is True
    assert result.execution_policy.model_synthesis_performed is False

    route_architecture = _record(result, ROUTE_ARCHITECTURE_TOOL_ID)
    assert route_architecture.collection_status == "completed"
    assert route_architecture.result is not None
    payload = route_architecture.result["payload"]
    assert payload["answerability"] == "route_architecture_available"
    assert payload["source_status"] == "candidate_only"
    assert payload["decision"] == "CONDITIONAL_GO"
    assert payload["decision_output"]["decisionObjectSchema"] == "ContextualPermission"
    assert payload["decision_output"]["firstLayer"]["decision"] == (
        "可依 CP Graph 推進，但必須保留折返窗口。"
    )
    assert payload["route_architecture"]["role"] == "Route Architecture Intelligence"
    assert payload["route_decision"]["runtime_safety_truth"] is False
    assert payload["cp_graph"]["node_count"] == 124
    assert payload["cp_graph"]["edge_count"] == 123
    assert route_architecture.boundary.runtime_safety_truth is False


def test_evidence_collection_keeps_live_navigation_decision_payload() -> None:
    result = collect_scout_ai_evidence(
        "我現在是不是偏離路線？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.missing_input_count == 0

    navigation = _record(result, LIVE_NAVIGATION_STATE_TOOL_ID)
    assert navigation.collection_status == "completed"
    assert navigation.result is not None
    payload = navigation.result["payload"]
    assert payload["answerability"] == "snapshot_missing_required_fields"
    assert payload["decision"] == "DELAY"
    assert payload["navigation_terrain"]["role"] == "Navigation & Terrain Intelligence"
    assert payload["navigation_decision"]["route_fit_status"] == "route_fit_unknown"
    assert payload["decision_output"]["decisionObjectSchema"] == "ContextualPermission"
    assert payload["decision_output"]["decision"] == "DELAY"
    assert payload["decision_output"]["firstLayer"]["decision"] == (
        "暫緩判斷，先取得可靠位置。"
    )
    assert payload["decision_output"]["secondLayer"]["uncertaintyNotes"]
    assert "lat" in navigation.missing_fields
    assert "lon" in navigation.missing_fields
    assert navigation.boundary.runtime_safety_truth is False


def test_evidence_collection_keeps_ins_dr_trace_decision_output() -> None:
    result = collect_scout_ai_evidence(
        "GPS-only 軌跡和 INS/DR 軌跡差多少？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    trace = _record(result, INS_DR_TRACE_TOOL_ID)
    payload = trace.result["payload"]
    assert payload["answerability"] == "missing_trace_evidence"
    assert payload["decision"] == "DELAY"
    assert payload["decision_output"]["decisionObjectSchema"] == "ContextualPermission"
    assert payload["decision_output"]["decision"] == "DELAY"
    assert payload["decision_output"]["firstLayer"]["decision"] == (
        "暫緩 INS/DR trace 判斷。"
    )
    assert payload["ins_dr_trace"]["role"] == "Navigation Truth / INS-DR Trace Guard"
    assert payload["ins_dr_trace"]["runtime_safety_truth"] is False
    assert "ins_dr_estimates_jsonl" in trace.missing_fields
    assert "gps_only_trajectory" in trace.missing_fields
    assert trace.boundary.runtime_safety_truth is False


def test_evidence_collection_keeps_equipment_resource_payload() -> None:
    result = collect_scout_ai_evidence(
        "手機電量和頭燈水量夠嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.missing_input_count == 0

    equipment = _record(result, EQUIPMENT_RESOURCE_TOOL_ID)
    assert equipment.collection_status == "completed"
    assert equipment.result is not None
    payload = equipment.result["payload"]
    assert payload["answerability"] == "equipment_resource_missing_required_fields"
    assert payload["decision"] == "DELAY"
    assert payload["decision_output"]["decisionObjectSchema"] == "ContextualPermission"
    assert payload["decision_output"]["firstLayer"]["decision"] == (
        "建議延後裝備資源判斷。"
    )
    assert payload["equipment_resource"]["role"] == "Equipment / Resource Intelligence"
    assert payload["resource_state"]["offline_map_ready"] is True
    assert "water_liters" in equipment.missing_fields
    assert equipment.boundary.runtime_safety_truth is False


def test_evidence_collection_keeps_route_readiness_payload() -> None:
    result = collect_scout_ai_evidence(
        "出發前 Go/No-Go 可以出發嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.missing_input_count == 0

    readiness = _record(result, ROUTE_READINESS_TOOL_ID)
    assert readiness.collection_status == "completed"
    assert readiness.result is not None
    payload = readiness.result["payload"]
    assert payload["answerability"] == "route_readiness_missing_required_fields"
    assert payload["decision"] == "DELAY"
    assert payload["decision_output"]["decisionObjectSchema"] == "ContextualPermission"
    assert payload["decision_output"]["decision"] == "DELAY"
    assert payload["decision_output"]["allowed"] is False
    assert payload["decision_output"]["firstLayer"]["decision"] == "建議延後。"
    assert "不得出發" in payload["decision_output"]["firstLayer"]["limit"]
    assert payload["decision_output"]["departureApprovalGranted"] is False
    assert payload["decision_output"]["runtimeSafetyTruth"] is False
    assert payload["route_readiness"]["role"] == (
        "Pre-Trip Route Readiness / Departure Gate"
    )
    assert payload["route_readiness"]["decision_output"]["decision"] == "DELAY"
    package = payload["pretrip_decision_package"]
    assert package["required_outputs"]["pretrip_decision"] == "DELAY"
    assert package["required_outputs"]["top_risk_sources"]
    assert package["required_outputs"]["latest_turnaround"]["checkpoint_name"] == (
        "雲海保線所"
    )
    assert package["traceability"]["raw_payloads_embedded"] is False
    assert payload["departure_gate"]["approval_granted"] is False
    assert "user_experience_level" in readiness.missing_fields
    assert readiness.boundary.runtime_safety_truth is False


def test_evidence_collection_keeps_guided_only_route_readiness_payload() -> None:
    result = collect_scout_ai_evidence(
        "beginner transportconfirmed slowestbasisconfirmed "
        "departuretimeconfirmed wxconfirmed sunok gearconfirmed rcconfirmed "
        "pretrip Go/No-Go 可以自主出發嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.failed_tool_count == 0
    readiness = _record(result, ROUTE_READINESS_TOOL_ID)
    assert readiness.collection_status == "completed"
    assert readiness.missing_fields == []
    assert readiness.result is not None
    payload = readiness.result["payload"]
    assert payload["answerability"] == "route_readiness_decision_available"
    assert payload["decision"] == "GUIDED_ONLY"
    assert payload["decision_output"]["decision"] == "GUIDED_ONLY"
    assert payload["decision_output"]["allowed"] is False
    assert payload["guided_only_gate"]["required"] is True
    assert payload["route_demand_profile"]["route_demand"] == "high"
    assert payload["pretrip_decision_package"]["required_outputs"][
        "pretrip_decision"
    ] == "GUIDED_ONLY"
    assert payload["pretrip_decision_package"]["decision_limits"][
        "autonomous_departure_allowed"
    ] is False
    assert readiness.boundary.runtime_safety_truth is False


def test_evidence_collection_keeps_media_literacy_payload() -> None:
    result = collect_scout_ai_evidence(
        "IG 大崩壁美照會不會誤導？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.selected_tool_count >= 1
    assert result.executed_tool_count >= 1
    assert result.completed_tool_count >= 1
    assert result.missing_input_count == 0

    media = _record(result, MEDIA_LITERACY_TOOL_ID)
    assert media.collection_status == "completed"
    assert media.result is not None
    payload = media.result["payload"]
    assert payload["answerability"] == "media_literacy_missing_context"
    assert payload["decision"] == "NO_GO"
    assert payload["media_literacy"]["role"] == "Media Literacy / Bias Sentinel"
    assert payload["media_bias_analysis"]["target_context_points"][0]["label"] == (
        "大崩壁"
    )
    assert payload["decision_output"]["decisionObjectSchema"] == "ContextualPermission"
    assert payload["decision_output"]["decision"] == "NO_GO"
    assert payload["decision_output"]["firstLayer"]["decision"] == (
        "不建議為媒體點位停留或改線。"
    )
    assert payload["decision_output"]["secondLayer"]["alternativeActions"]
    assert "fresh_weather_or_route_condition_review" in media.missing_fields
    assert media.boundary.runtime_safety_truth is False


def test_evidence_collection_keeps_survival_playbook_payload() -> None:
    result = collect_scout_ai_evidence(
        "不確定自己在哪，可以下切溪谷找路嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.selected_tool_count >= 1
    assert result.executed_tool_count >= 1
    assert result.completed_tool_count >= 1
    assert result.missing_input_count == 0

    survival = _record(result, SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID)
    assert survival.collection_status == "completed"
    assert survival.result is not None
    payload = survival.result["payload"]
    assert payload["answerability"] == "survival_playbook_missing_personalized_context"
    assert payload["decision"] == "NO_GO"
    assert payload["decision_output"]["decisionObjectSchema"] == "ContextualPermission"
    assert payload["decision_output"]["firstLayer"]["decision"] == (
        "不建議繼續移動或下切找路。"
    )
    assert payload["survival_incident_playbook"]["role"] == (
        "Risk Sentinel / Survival Incident Playbook"
    )
    assert payload["incident_triage"]["scenario"] == "lost_or_position_uncertain"
    assert payload["survival_incident_playbook"]["share_policy"][
        "can_send_or_notify"
    ] is False
    assert "current_location_status" in survival.missing_fields
    assert survival.boundary.runtime_safety_truth is False


def test_evidence_collection_keeps_team_status_payload() -> None:
    result = collect_scout_ai_evidence(
        "後隊在哪？最後一次有效位置多久前？留守回報準備好了嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.missing_input_count == 0

    team_status = _record(result, TEAM_STATUS_TOOL_ID)
    assert team_status.collection_status == "completed"
    assert team_status.result is not None
    payload = team_status.result["payload"]
    assert payload["answerability"] == "team_status_missing_required_fields"
    assert payload["decision"] == "DELAY"
    assert payload["decision_output"]["decisionObjectSchema"] == "ContextualPermission"
    assert payload["decision_output"]["firstLayer"]["decision"] == (
        "建議延後隊伍狀態判斷。"
    )
    assert payload["team_status_guardian"]["role"] == (
        "Team Status / Remote Contact Governance"
    )
    assert payload["team_status"]["remote_contact"]["available"] is True
    assert "member_positions_or_last_heard" in team_status.missing_fields
    assert team_status.boundary.runtime_safety_truth is False


def test_evidence_collection_keeps_post_trip_review_payload() -> None:
    result = collect_scout_ai_evidence(
        "行後回顧要更新哪些下一次規劃？實際耗時哪裡比預期慢？",
        project_root=POST_ANALYSIS_ROOT,
        project_id="chilai_nanhua_day1_post_analysis",
        limit=3,
    )

    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.missing_input_count == 0

    post_trip = _record(result, POST_TRIP_REVIEW_TOOL_ID)
    assert post_trip.collection_status == "completed"
    assert post_trip.result is not None
    payload = post_trip.result["payload"]
    assert payload["answerability"] == "post_trip_review_missing_required_fields"
    assert payload["decision"] == "DELAY"
    assert payload["decision_output"]["decisionObjectSchema"] == "ContextualPermission"
    assert payload["decision_output"]["decision"] == "DELAY"
    assert payload["decision_output"]["runtimeSafetyTruth"] is False
    assert payload["post_trip_review"]["role"] == (
        "Post-Trip Review / Learning Governance"
    )
    assert payload["post_trip_learning_package"]["role"] == (
        "Post-Trip Learning Proposal"
    )
    assert payload["post_trip_learning_package"]["writeback_policy"][
        "automatic_route_model_update_allowed"
    ] is False
    assert payload["completed_trip_summary"]["edge_count"] == 73
    assert "subjective_difficulty" in post_trip.missing_fields
    assert post_trip.boundary.runtime_safety_truth is False


def test_evidence_collection_keeps_safety_boundary_decision_output() -> None:
    result = collect_scout_ai_evidence(
        "哪些風險目前只是候選，不能觸發 Ln？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.selected_tool_count == 3
    assert result.executed_tool_count == 3
    assert result.completed_tool_count == 3
    safety = _record(result, SAFETY_BOUNDARY_TOOL_ID)
    payload = safety.result["payload"]
    assert payload["answerability"] == "safety_boundary_missing_required_fields"
    assert payload["decision"] == "DELAY"
    assert payload["decision_output"]["decisionObjectSchema"] == "ContextualPermission"
    assert payload["decision_output"]["decision"] == "DELAY"
    assert payload["decision_output"]["allowed"] is False
    assert payload["decision_output"]["runtimeSafetyTruth"] is False
    assert payload["safety_boundary"]["role"] == (
        "Safety Boundary / Runtime Admission Guard"
    )
    assert "admission_state" in safety.missing_fields
    assert "operator_review_status" in safety.missing_fields
    assert safety.boundary.runtime_safety_truth is False
    assert safety.boundary.live_safety_api_calls_allowed is False


def test_evidence_collection_reports_empty_collection_when_no_tool_matches() -> None:
    result = collect_scout_ai_evidence(
        "請用一句話描述登山心情",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.selected_tool_count == 0
    assert result.executed_tool_count == 0
    assert result.completed_tool_count == 0
    assert result.contract_gap_count == 0
    assert result.missing_input_count == 0
    assert result.failed_tool_count == 0
    assert result.evidence_records == []
    assert result.execution_policy.ready_tools_executed is False
    assert result.execution_policy.model_synthesis_performed is False
    assert result.boundary.runtime_safety_truth is False
    assert result.discovery_plan["selected_tool_count"] == 0
    assert result.discovery_plan["tool_plan"]["selected_tools"] == []
    assert result.discovery_plan["tool_plan"]["planner_notes"]


def test_evidence_collection_builtin_manifest_and_payload_are_read_only(
    tmp_path: Path,
) -> None:
    manifest = load_tool_manifest(MANIFEST_PATH)
    request_path = tmp_path / "evidence-collection-request.json"
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
        ["ai-evidence-collection", "--input", str(request_path), "--json"]
    )

    assert manifest.id == "scout.ai.evidence_collection.collect"
    assert manifest.mode == "local_evidence_query"
    assert manifest.allowed_writes == []
    assert "live.safety_api" in manifest.forbidden_writes
    assert "transport.egress" in manifest.forbidden_writes
    assert "hardware.device" in manifest.forbidden_writes
    assert manifest.metadata["read_only"] is True
    assert manifest.metadata["model_synthesis_performed"] is False
    assert manifest.metadata["runtime_safety_truth"] is False

    assert exit_code == 0
    assert payload["artifact_kind"] == ARTIFACT_KIND
    assert payload["artifact_version"] == ARTIFACT_VERSION
    assert payload["status"] == "completed"
    assert payload["executed_tool_count"] == 2
    assert payload["completed_tool_count"] == 2
    assert payload["execution_policy"]["ready_tools_executed"] is True
    assert payload["execution_policy"]["model_synthesis_performed"] is False
    assert payload["boundary"]["read_only"] is True
    assert payload["boundary"]["runtime_safety_truth"] is False
    assert payload["boundary"]["live_safety_api_calls_allowed"] is False
    assert payload["boundary"]["phase1_l0_l4_state_mutated"] is False
    assert payload["boundary"]["outbound_send_performed"] is False
    assert payload["boundary"]["hardware_control_performed"] is False
    assert payload["boundary"]["workspace_file_write_allowed"] is False
    assert payload["boundary"]["model_synthesis_performed"] is False


def test_evidence_collection_builtin_rejects_blank_question(tmp_path: Path) -> None:
    request_path = tmp_path / "evidence-collection-request.json"
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
        ["ai-evidence-collection", "--input", str(request_path), "--json"]
    )

    assert exit_code == 2
    assert payload["status"] == "failed"
    assert "non-empty question" in payload["error"]
    assert payload["boundary"]["runtime_safety_truth"] is False


def _record(result, tool_id: str):
    matches = [record for record in result.evidence_records if record.tool_id == tool_id]
    assert len(matches) == 1, result.model_dump(mode="json")
    return matches[0]


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
