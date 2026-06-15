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
from scout_ai_tool_planner import LIVE_NAVIGATION_STATE_TOOL_ID, WEATHER_WINDOW_TOOL_ID
from scout_contextual_permission_tool import CONTEXTUAL_PERMISSION_TOOL_ID
from scout_pace_guardian_tool import PACE_GUARDIAN_TOOL_ID
from scout_equipment_resource_tool import EQUIPMENT_RESOURCE_TOOL_ID
from scout_team_status_tool import TEAM_STATUS_TOOL_ID
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
    assert result.answerability == "evidence_available"
    assert result.evidence_collection_verified is True
    assert result.completed_source_count == 2
    assert result.missing_evidence_count == 0
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
    assert result.completed_source_count == 1
    assert result.missing_evidence_count == 1
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


def test_answer_synthesis_uses_weather_to_decision_field_answer(tmp_path: Path) -> None:
    project_root = _write_route_weather_project(tmp_path)

    result = collect_and_synthesize_scout_ai_answer(
        "午後雷雨是否要改變計畫?",
        project_root=project_root,
        project_id="weather_decision_project",
        limit=3,
    )

    assert result.answerability == "evidence_available"
    assert result.completed_source_count == 1
    assert result.missing_evidence_count == 0
    assert result.sources[0].tool_id == WEATHER_WINDOW_TOOL_ID
    assert result.sources[0].top_result_summary["decision"] == "CHANGE_PLAN"
    assert result.sources[0].top_result_summary["weather_to_decision"]["role"] == (
        "Risk Sentinel / Weather-to-Decision"
    )
    assert "天氣決策" in result.answer
    assert "CHANGE_PLAN" in result.answer
    assert "runtime safety truth" in result.answer


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
    assert "remaining_safety_buffer_minutes" in result.sources[0].missing_fields
    assert "不建議拍影片" in result.answer
    assert "remaining_safety_buffer_minutes" in result.answer
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
    assert result.sources[0].top_result_summary["route_context"]["role"] == (
        "Experience Guide"
    )
    assert "候選路線脈絡" in result.answer
    assert "Experience Guide 候選" in result.answer
    assert "contextual permission" in result.answer
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
    assert result.sources[0].top_result_summary["team_pace_fit"]["slowest_member"][
        "label"
    ] == "New teammate"
    assert "腳程守門員" in result.answer
    assert "不使用平均腳程" in result.answer
    assert "contextual permission" in result.answer
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
    assert result.sources[0].top_result_summary["route_architecture"]["role"] == (
        "Route Architecture Intelligence"
    )
    assert result.sources[0].top_result_summary["cp_graph"]["node_count"] == 124
    assert "路線結構判斷" in result.answer
    assert "CP Graph" in result.answer
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
    assert "lat" in result.sources[0].missing_fields
    assert "地形導航判斷" in result.answer
    assert "runtime safety truth" in result.answer


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
    assert result.sources[0].top_result_summary["equipment_resource"]["role"] == (
        "Equipment / Resource Intelligence"
    )
    assert "water_liters" in result.sources[0].missing_fields
    assert "裝備資源判斷" in result.answer
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
    assert result.sources[0].top_result_summary["team_status_guardian"]["role"] == (
        "Team Status / Remote Contact Governance"
    )
    assert "member_positions_or_last_heard" in result.sources[0].missing_fields
    assert "隊伍守門員" in result.answer
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

    assert result.answerability == "evidence_available"
    assert result.evidence_collection["artifact_kind"] == "scout_ai_evidence_collection"
    assert result.evidence_collection["executed_tool_count"] == 2
    assert result.completed_source_count == 2


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
    assert payload["answerability"] == "evidence_available"
    assert payload["evidence_collection_verified"] is True
    assert payload["completed_source_count"] == 2
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
