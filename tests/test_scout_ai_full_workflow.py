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
    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.missing_evidence_count == 1
    assert result.sources[0]["tool_id"] == CONTEXTUAL_PERMISSION_TOOL_ID
    summary = result.sources[0]["top_result_summary"]
    assert summary["decision"] == "NO_GO"
    assert summary["decision_object"] == summary["contextual_permission"]
    assert summary["decision_output"]["decisionObjectSchema"] == "ContextualPermission"
    assert summary["decision_output"]["firstLayer"]["decision"] == "不建議拍影片。"
    assert result.decision_output["decisionObjectSchema"] == "ContextualPermission"
    assert result.decision_output["answerSourceToolId"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.decision_output["firstLayer"]["decision"] == "不建議拍影片。"
    answer_step = result.workflow_steps[-1]
    assert answer_step.summary["decision_output_schema"] == "ContextualPermission"
    assert answer_step.summary["decision_output_source_tool"] == (
        CONTEXTUAL_PERMISSION_TOOL_ID
    )
    assert "[決策] 不建議拍影片。" in result.answer
    assert "runtime safety truth" in result.answer
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


def test_full_workflow_runs_route_readiness_question() -> None:
    result = run_scout_ai_full_workflow(
        "出發前 Go/No-Go 可以出發嗎？",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.contract_gap_count == 0
    assert result.failed_tool_count == 0
    assert result.missing_evidence_count == 1
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
    assert "出發前判斷" in result.answer
    assert "標準出發前決策包" in result.answer
    assert "停留限制" in result.answer
    assert "runtime safety truth" in result.answer
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
