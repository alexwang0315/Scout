from __future__ import annotations

import json
import sys
from pathlib import Path

from scout_agent_cli import run_scout_agent_cli
from scout_agent_trace import load_agent_trace


def test_tools_list_and_describe(tmp_path: Path) -> None:
    manifest_dir = tmp_path / "manifests"
    _write_manifest(manifest_dir)

    list_exit, list_payload = run_scout_agent_cli(
        ["tools", "list", "--manifest-dir", str(manifest_dir), "--json"]
    )
    describe_exit, describe_payload = run_scout_agent_cli(
        [
            "tools",
            "describe",
            "scout.local_evidence.status",
            "--manifest-dir",
            str(manifest_dir),
            "--json",
        ]
    )

    assert list_exit == 0
    assert list_payload["tools"][0]["id"] == "scout.local_evidence.status"
    assert describe_exit == 0
    assert describe_payload["manifest"]["mode"] == "local_evidence_query"
    assert describe_payload["boundary"]["live_safety_api_calls_allowed"] is False


def test_tools_run_writes_trace(tmp_path: Path) -> None:
    manifest_dir = tmp_path / "manifests"
    _write_manifest(manifest_dir)
    input_path = tmp_path / "request.json"
    input_path.write_text(json.dumps({"query": "風險摘要"}), encoding="utf-8")
    trace_log = tmp_path / "agent-trace.jsonl"

    exit_code, payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.local_evidence.status",
            "--manifest-dir",
            str(manifest_dir),
            "--input",
            str(input_path),
            "--trace-log",
            str(trace_log),
            "--agent-run-id",
            "agent_run.test.cli",
            "--action-id",
            "agent_action.test.cli",
            "--json",
        ]
    )

    assert exit_code == 0
    assert payload["status"] == "completed"
    assert json.loads(payload["outputs"]["stdout"])["ok"] is True
    assert load_agent_trace(trace_log)[0].agent_run_id == "agent_run.test.cli"


def test_tools_run_blocks_workspace_write_without_authorization(tmp_path: Path) -> None:
    manifest_dir = tmp_path / "manifests"
    _write_manifest(
        manifest_dir,
        mode="workspace_write",
        allowed_writes=["pretrip.workspace.proposals"],
        requires_authorization={"kind": "user_or_operator"},
    )

    exit_code, payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.local_evidence.status",
            "--manifest-dir",
            str(manifest_dir),
            "--json",
        ]
    )

    assert exit_code == 2
    assert payload["status"] == "blocked"
    assert payload["boundary"]["phase1_safety_mutation_allowed"] is False
    assert payload["effects"]["workspace_write_count"] == 0


def test_agent_run_plan_executes_structured_tool_plan(tmp_path: Path) -> None:
    manifest_dir = tmp_path / "manifests"
    _write_manifest(manifest_dir)
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"query": "status"}), encoding="utf-8")
    plan = tmp_path / "plan.json"
    plan.write_text(
        json.dumps(
            {
                "artifact_kind": "scout_agent_tool_plan",
                "plan_id": "agent_plan.cli.001",
                "agent_run_id": "agent_run.cli.001",
                "user_intent": "read local evidence status",
                "tool_calls": [
                    {
                        "tool_id": "scout.local_evidence.status",
                        "action_id": "agent_action.cli.001",
                        "input_path": str(request),
                        "dry_run": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    trace_log = tmp_path / "agent-trace.jsonl"

    exit_code, payload = run_scout_agent_cli(
        [
            "agent",
            "run-plan",
            "--manifest-dir",
            str(manifest_dir),
            "--plan",
            str(plan),
            "--trace-log",
            str(trace_log),
            "--json",
        ]
    )

    assert exit_code == 0
    assert payload["status"] == "completed"
    assert payload["result_count"] == 1
    assert payload["boundary"]["live_safety_api_calls_allowed"] is False
    assert load_agent_trace(trace_log)[0].action_id == "agent_action.cli.001"


def _write_manifest(tmp_path: Path, **overrides) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
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
    path = tmp_path / "scout.local_evidence.status.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path
