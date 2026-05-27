from __future__ import annotations

import json
import sys
from pathlib import Path

from scout_agent_debug_projection import load_agent_trace_debug_events
from scout_agent_models import ScoutAgentToolManifest
from scout_agent_tools import run_registered_tool


def test_agent_tool_result_projects_to_runtime_debug_event(tmp_path: Path) -> None:
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"query": "agent trace"}), encoding="utf-8")
    trace_log = tmp_path / "agent-trace.jsonl"
    manifest = ScoutAgentToolManifest.model_validate(
        {
            "id": "scout.local_evidence.status",
            "version": "0.1.0",
            "description": "Return a deterministic local evidence status fixture.",
            "command": {
                "argv": [
                    sys.executable,
                    "-c",
                    "import json; print(json.dumps({'ok': True}))",
                ],
                "dry_run_argument": None,
            },
            "mode": "local_evidence_query",
            "allowed_reads": ["trip.local_evidence_index"],
            "forbidden_writes": ["phase1.runtime", "live.safety_api"],
        }
    )
    run_registered_tool(
        manifest,
        input_path=request,
        trace_log_path=trace_log,
        agent_run_id="agent_run.debug.001",
        action_id="agent_action.debug.001",
    )

    events = load_agent_trace_debug_events(trace_log, sequence_offset=10)

    assert len(events) == 1
    event = events[0]
    assert event.kind == "agent_tool_invocation"
    assert event.sequence == 11
    assert event.session_id == "agent_run.debug.001"
    assert event.subject_ref == "scout.local_evidence.status"
    assert event.payload["status"] == "completed"
    assert event.payload["boundary"]["live_safety_api_calls_allowed"] is False
    assert event.payload["phase1_safety_mutation_allowed"] is False
    assert event.payload["runtime_safety_truth"] is False
