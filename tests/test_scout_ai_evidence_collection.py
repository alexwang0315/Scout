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


def test_evidence_collection_reports_weather_contract_gap_without_model_synthesis() -> None:
    result = collect_scout_ai_evidence(
        "明天午後雷雨是否要紮營?",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.selected_tool_count == 1
    assert result.executed_tool_count == 0
    assert result.completed_tool_count == 0
    assert result.contract_gap_count == 1
    assert result.execution_policy.ready_tools_executed is False
    assert result.execution_policy.model_synthesis_performed is False

    weather = _record(result, WEATHER_WINDOW_TOOL_ID)
    assert weather.collection_status == "contract_gap"
    assert weather.result is None
    assert "provider" in weather.missing_fields
    assert "ttl_s" in weather.missing_fields
    assert weather.implementation_gap is not None
    assert weather.boundary.runtime_safety_truth is False


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
