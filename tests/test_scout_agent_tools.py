from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from scout_agent_models import ScoutAgentToolManifest
from scout_agent_tools import load_tool_manifest, run_registered_tool
from scout_agent_trace import load_agent_trace


def test_manifest_rejects_runtime_safety_mutation_mode() -> None:
    payload = _manifest_payload(mode="runtime_safety_mutation")

    with pytest.raises(ValidationError):
        ScoutAgentToolManifest.model_validate(payload)


def test_manifest_rejects_live_safety_allowed_write() -> None:
    payload = _manifest_payload(mode="workspace_write")
    payload["allowed_writes"] = ["live.safety_api"]

    with pytest.raises(ValidationError):
        ScoutAgentToolManifest.model_validate(payload)


def test_registered_tool_run_emits_result_and_trace(tmp_path: Path) -> None:
    input_path = tmp_path / "request.json"
    input_path.write_text(json.dumps({"query": "附近風險摘要"}), encoding="utf-8")
    trace_log = tmp_path / "agent-trace.jsonl"
    manifest = ScoutAgentToolManifest.model_validate(_manifest_payload())

    result = run_registered_tool(
        manifest,
        input_path=input_path,
        trace_log_path=trace_log,
        agent_run_id="agent_run.test.001",
        action_id="agent_action.test.001",
    )

    assert result.status == "completed"
    assert result.boundary.live_safety_api_calls_allowed is False
    assert result.effects.workspace_write_count == 0
    assert result.source_refs[0].sha256
    assert json.loads(result.outputs["stdout"])["ok"] is True
    assert load_agent_trace(trace_log)[0].action_id == "agent_action.test.001"


def test_write_tool_blocks_without_authorization_and_records_trace(tmp_path: Path) -> None:
    trace_log = tmp_path / "blocked-trace.jsonl"
    manifest = ScoutAgentToolManifest.model_validate(
        _manifest_payload(
            mode="workspace_write",
            allowed_writes=["pretrip.workspace.proposals"],
            requires_authorization={"kind": "user_or_operator"},
        )
    )

    result = run_registered_tool(
        manifest,
        trace_log_path=trace_log,
        agent_run_id="agent_run.test.002",
        action_id="agent_action.test.002",
    )

    assert result.status == "blocked"
    assert "requires explicit authorization" in result.warnings[0]
    assert result.effects.workspace_write_count == 0
    assert load_agent_trace(trace_log)[0].status == "blocked"


def test_workspace_tool_dry_run_has_no_write_effects() -> None:
    manifest = ScoutAgentToolManifest.model_validate(
        _manifest_payload(
            mode="workspace_write",
            allowed_writes=["pretrip.workspace.proposals"],
            requires_authorization={"kind": "user_or_operator"},
        )
    )

    result = run_registered_tool(manifest, dry_run=True)

    assert result.status == "completed"
    assert result.effects.workspace_write_count == 0


def test_json_manifest_loader(tmp_path: Path) -> None:
    manifest_path = tmp_path / "scout.local_evidence.status.json"
    manifest_path.write_text(json.dumps(_manifest_payload()), encoding="utf-8")

    manifest = load_tool_manifest(manifest_path)

    assert manifest.id == "scout.local_evidence.status"
    assert manifest.mode == "local_evidence_query"


def _manifest_payload(**overrides):
    payload = {
        "id": "scout.local_evidence.status",
        "version": "0.1.0",
        "description": "Return a deterministic local evidence status fixture.",
        "command": {
            "argv": [
                sys.executable,
                "-c",
                "import json; print(json.dumps({'ok': True, 'tool': 'local_evidence'}))",
            ],
            "dry_run_argument": None,
        },
        "mode": "local_evidence_query",
        "allowed_reads": ["trip.local_evidence_index"],
        "forbidden_writes": ["phase1.runtime", "live.safety_api"],
    }
    payload.update(overrides)
    return payload
