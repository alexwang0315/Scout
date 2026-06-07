import json
from pathlib import Path

from scout_agent_builtin_tools import run_builtin_tool
from scout_agent_tools import load_tool_manifest
from scout_ai_tool_planner import WEATHER_WINDOW_TOOL_ID
from scout_ai_workflow_discovery import (
    ARTIFACT_KIND,
    ARTIFACT_VERSION,
    build_scout_ai_workflow_discovery_plan,
)
from scout_risk_score_tool import RISK_SCORE_TOOL_ID
from scout_terrain_score_tool import TERRAIN_SCORE_TOOL_ID


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
MANIFEST_PATH = (
    ROOT
    / "tools"
    / "scout_agent_tool_manifests"
    / "scout.ai.workflow_discovery.plan.json"
)


def test_workflow_discovery_plans_weather_ready_tool_without_execution() -> None:
    result = build_scout_ai_workflow_discovery_plan(
        "明天午後雷雨是否要紮營?",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.artifact_kind == ARTIFACT_KIND
    assert result.artifact_version == ARTIFACT_VERSION
    assert result.project_id == "chilai_nanhua_day1"
    assert result.context_registry["artifact_kind"] == "scout_ai_context_registry"
    assert result.tool_registry_summary["artifact_kind"] == "scout_ai_tool_registry"
    assert WEATHER_WINDOW_TOOL_ID in result.selected_tool_ids
    assert result.ready_to_execute_tool_ids == [WEATHER_WINDOW_TOOL_ID]
    assert result.contract_gap_tool_ids == []
    assert result.execution_policy.ready_tools_executed is False
    assert result.execution_policy.model_synthesis_performed is False
    assert result.execution_policy.workspace_file_write_allowed is False
    assert result.boundary.runtime_safety_truth is False
    assert result.boundary.live_safety_api_calls_allowed is False

    selected_weather = _plan_item(result.tool_plan, WEATHER_WINDOW_TOOL_ID)
    assert selected_weather["status"] == "ready_to_execute"
    assert selected_weather["request"] is not None
    assert selected_weather["missing_fields"] == []
    assert "tool_result" not in selected_weather


def test_workflow_discovery_plans_ready_risk_and_terrain_without_running_tools() -> None:
    result = build_scout_ai_workflow_discovery_plan(
        "危險地形在哪些位置?",
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert RISK_SCORE_TOOL_ID in result.selected_tool_ids
    assert TERRAIN_SCORE_TOOL_ID in result.selected_tool_ids
    assert set(result.ready_to_execute_tool_ids) == {
        RISK_SCORE_TOOL_ID,
        TERRAIN_SCORE_TOOL_ID,
    }
    assert result.contract_gap_tool_ids == []
    assert result.execution_policy.ready_tools_executed is False
    assert result.execution_policy.model_synthesis_performed is False

    risk_item = _plan_item(result.tool_plan, RISK_SCORE_TOOL_ID)
    terrain_item = _plan_item(result.tool_plan, TERRAIN_SCORE_TOOL_ID)
    assert risk_item["status"] == "ready_to_execute"
    assert terrain_item["status"] == "ready_to_execute"
    assert risk_item["request"] is not None
    assert terrain_item["request"] is not None
    assert "tool_result" not in risk_item
    assert "tool_result" not in terrain_item


def test_workflow_discovery_builtin_manifest_and_payload_are_read_only(
    tmp_path: Path,
) -> None:
    manifest = load_tool_manifest(MANIFEST_PATH)
    request_path = tmp_path / "workflow-discovery-request.json"
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
        ["ai-workflow-discovery", "--input", str(request_path), "--json"]
    )

    assert manifest.id == "scout.ai.workflow_discovery.plan"
    assert manifest.mode == "local_evidence_query"
    assert manifest.allowed_writes == []
    assert "live.safety_api" in manifest.forbidden_writes
    assert "transport.egress" in manifest.forbidden_writes
    assert "hardware.device" in manifest.forbidden_writes
    assert manifest.metadata["read_only"] is True
    assert manifest.metadata["ready_tools_executed"] is False
    assert manifest.metadata["model_synthesis_performed"] is False
    assert manifest.metadata["runtime_safety_truth"] is False

    assert exit_code == 0
    assert payload["artifact_kind"] == ARTIFACT_KIND
    assert payload["artifact_version"] == ARTIFACT_VERSION
    assert payload["status"] == "completed"
    assert payload["selected_tool_count"] == 2
    assert set(payload["ready_to_execute_tool_ids"]) == {
        RISK_SCORE_TOOL_ID,
        TERRAIN_SCORE_TOOL_ID,
    }
    assert payload["execution_policy"]["ready_tools_executed"] is False
    assert payload["execution_policy"]["model_synthesis_performed"] is False
    assert payload["boundary"]["read_only"] is True
    assert payload["boundary"]["runtime_safety_truth"] is False
    assert payload["boundary"]["live_safety_api_calls_allowed"] is False
    assert payload["boundary"]["phase1_l0_l4_state_mutated"] is False
    assert payload["boundary"]["outbound_send_performed"] is False
    assert payload["boundary"]["hardware_control_performed"] is False
    assert payload["boundary"]["workspace_file_write_allowed"] is False
    assert payload["boundary"]["ready_tools_executed"] is False
    assert payload["boundary"]["model_synthesis_performed"] is False


def test_workflow_discovery_builtin_rejects_blank_question(tmp_path: Path) -> None:
    request_path = tmp_path / "workflow-discovery-request.json"
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
        ["ai-workflow-discovery", "--input", str(request_path), "--json"]
    )

    assert exit_code == 2
    assert payload["status"] == "failed"
    assert "non-empty question" in payload["error"]
    assert payload["boundary"]["runtime_safety_truth"] is False


def _plan_item(tool_plan: dict[str, object], tool_id: str) -> dict[str, object]:
    selected_tools = tool_plan["selected_tools"]
    assert isinstance(selected_tools, list)
    matches = [
        item
        for item in selected_tools
        if isinstance(item, dict) and item.get("tool_id") == tool_id
    ]
    assert len(matches) == 1, tool_plan
    return matches[0]
