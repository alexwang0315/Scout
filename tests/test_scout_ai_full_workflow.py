import json
from pathlib import Path

from scout_agent_builtin_tools import run_builtin_tool
from scout_agent_tools import load_tool_manifest
from scout_ai_full_workflow import (
    ARTIFACT_KIND,
    ARTIFACT_VERSION,
    run_scout_ai_full_workflow,
)
from scout_ai_tool_planner import WEATHER_WINDOW_TOOL_ID
from scout_pace_guardian_tool import PACE_GUARDIAN_TOOL_ID
from scout_route_context_tool import ROUTE_CONTEXT_TOOL_ID
from scout_risk_score_tool import RISK_SCORE_TOOL_ID
from scout_terrain_score_tool import TERRAIN_SCORE_TOOL_ID


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
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
    assert result.answerability == "evidence_available"
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
    assert result.missing_evidence_count == 0
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
    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.contract_gap_count == 0
    assert result.failed_tool_count == 0
    assert result.missing_evidence_count == 1
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


def test_full_workflow_runs_weather_to_decision_question(tmp_path: Path) -> None:
    project_root = _write_route_weather_project(tmp_path)

    result = run_scout_ai_full_workflow(
        "午後雷雨是否要改變計畫?",
        project_root=project_root,
        project_id="weather_decision_project",
        limit=3,
    )

    assert result.answerability == "evidence_available"
    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 1
    assert result.completed_tool_count == 1
    assert result.missing_evidence_count == 0
    assert result.sources[0]["tool_id"] == WEATHER_WINDOW_TOOL_ID
    assert result.sources[0]["top_result_summary"]["decision"] == "CHANGE_PLAN"
    assert result.sources[0]["top_result_summary"]["weather_to_decision"]["role"] == (
        "Risk Sentinel / Weather-to-Decision"
    )
    assert "天氣決策" in result.answer
    assert "CHANGE_PLAN" in result.answer
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
    assert result.sources[0]["top_result_summary"]["route_context"]["role"] == (
        "Experience Guide"
    )
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
    assert result.sources[0]["top_result_summary"]["team_pace_fit"]["slowest_member"][
        "label"
    ] == "New teammate"
    assert "腳程守門員" in result.answer
    assert "不使用平均腳程" in result.answer
    assert "runtime safety truth" in result.answer
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
    assert payload["answerability"] == "evidence_available"
    assert payload["selected_tool_count"] == 2
    assert payload["executed_tool_count"] == 2
    assert payload["completed_tool_count"] == 2
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
