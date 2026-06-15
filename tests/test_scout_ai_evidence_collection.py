import json
from pathlib import Path

from scout_agent_builtin_tools import run_builtin_tool
from scout_agent_tools import load_tool_manifest
from scout_ai_evidence_collection import (
    ARTIFACT_KIND,
    ARTIFACT_VERSION,
    collect_scout_ai_evidence,
)
from scout_ai_tool_planner import WEATHER_WINDOW_TOOL_ID
from scout_pace_guardian_tool import PACE_GUARDIAN_TOOL_ID
from scout_route_architecture_tool import ROUTE_ARCHITECTURE_TOOL_ID
from scout_route_context_tool import ROUTE_CONTEXT_TOOL_ID
from scout_risk_score_tool import RISK_SCORE_TOOL_ID
from scout_terrain_score_tool import TERRAIN_SCORE_TOOL_ID


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
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
    assert terrain.result["payload"]["summaries"]


def test_evidence_collection_executes_weather_tool_without_model_synthesis() -> None:
    result = collect_scout_ai_evidence(
        "明天午後雷雨是否要紮營?",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
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

    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.contract_gap_count == 0
    assert result.execution_policy.ready_tools_executed is True
    assert result.execution_policy.model_synthesis_performed is False

    route_context = _record(result, ROUTE_CONTEXT_TOOL_ID)
    assert route_context.collection_status == "completed"
    assert route_context.result is not None
    payload = route_context.result["payload"]
    assert payload["answerability"] == "route_context_available"
    assert payload["source_status"] == "candidate_only"
    assert payload["route_context"]["role"] == "Experience Guide"
    assert payload["route_context"]["stop_permission_required"] is True
    assert payload["result_count"] >= 1
    assert payload["matched_context_count"] >= 1
    assert any(item["label"] == "稜線啞口觀景點" for item in payload["results"])
    assert route_context.boundary.runtime_safety_truth is False


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
    assert payload["route_architecture"]["role"] == "Route Architecture Intelligence"
    assert payload["route_decision"]["runtime_safety_truth"] is False
    assert payload["cp_graph"]["node_count"] == 124
    assert payload["cp_graph"]["edge_count"] == 123
    assert route_architecture.boundary.runtime_safety_truth is False


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
