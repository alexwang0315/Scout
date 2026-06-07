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
from scout_ai_tool_planner import WEATHER_WINDOW_TOOL_ID
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


def test_answer_synthesis_reports_weather_missing_evidence_without_guessing() -> None:
    result = collect_and_synthesize_scout_ai_answer(
        "明天午後雷雨是否要紮營?",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.answerability == "missing_evidence"
    assert result.completed_source_count == 0
    assert result.missing_evidence_count == 1
    assert result.synthesis_policy.model_provider_used is False
    assert result.synthesis_policy.model_synthesis_performed is False

    assert result.sources[0].tool_id == WEATHER_WINDOW_TOOL_ID
    assert result.sources[0].collection_status == "contract_gap"
    assert "provider" in result.sources[0].missing_fields
    assert "ttl_s" in result.sources[0].missing_fields
    assert result.missing_evidence[0]["tool_id"] == WEATHER_WINDOW_TOOL_ID
    assert "provider" in result.missing_evidence[0]["missing_fields"]
    assert "ttl_s" in result.missing_evidence[0]["missing_fields"]
    assert "A field conclusion should not be inferred" in result.answer
    assert "provider" in result.answer
    assert "ttl_s" in result.answer
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
