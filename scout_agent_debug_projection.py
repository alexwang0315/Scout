from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from runtime_debug_models import RuntimeDebugEvent
from scout_agent_models import ScoutAgentToolResult
from scout_agent_trace import load_agent_trace


def load_agent_trace_debug_events(
    trace_log_path: str | Path | None,
    *,
    sequence_offset: int = 0,
    limit: int | None = None,
) -> list[RuntimeDebugEvent]:
    if trace_log_path is None:
        return []
    path = Path(trace_log_path)
    if not path.exists():
        return []
    results = load_agent_trace(path)
    if limit is not None and limit >= 0:
        results = results[-limit:]
    return agent_tool_results_to_debug_events(
        results,
        source_path=str(path),
        sequence_offset=sequence_offset,
    )


def agent_tool_results_to_debug_events(
    results: Iterable[ScoutAgentToolResult],
    *,
    source_path: str = "scout_agent_trace",
    sequence_offset: int = 0,
) -> list[RuntimeDebugEvent]:
    events: list[RuntimeDebugEvent] = []
    for index, result in enumerate(results, start=1):
        events.append(
            RuntimeDebugEvent(
                event_id=f"debug_event.agent_tool.{_safe_token(result.action_id)}",
                session_id=result.agent_run_id,
                mission_id=None,
                timestamp=result.ended_at,
                sequence=sequence_offset + index,
                kind="agent_tool_invocation",
                source="scout_agent_tools",
                phase="phase35",
                severity=_severity_for_result(result),
                subject_ref=result.tool_id,
                correlation_refs=[result.action_id],
                summary=(
                    f"Agent tool {result.tool_id} {result.status} "
                    f"in {result.mode} mode"
                ),
                payload=_payload_for_result(result, source_path=source_path),
            )
        )
    return events


def _payload_for_result(
    result: ScoutAgentToolResult,
    *,
    source_path: str,
) -> dict[str, object]:
    outputs = dict(result.outputs)
    return {
        "tool_id": result.tool_id,
        "tool_version": result.tool_version,
        "action_id": result.action_id,
        "agent_run_id": result.agent_run_id,
        "status": result.status,
        "mode": result.mode,
        "started_at": result.started_at,
        "ended_at": result.ended_at,
        "effects": result.effects.model_dump(mode="json"),
        "boundary": result.boundary.model_dump(mode="json"),
        "source_refs": [source.model_dump(mode="json") for source in result.source_refs],
        "receipt_refs": result.receipt_refs,
        "warnings": result.warnings,
        "input_refs": list(result.inputs.get("input_refs", [])),
        "artifact_refs": list(outputs.get("artifact_refs", [])),
        "requested_output_path": outputs.get("requested_output_path"),
        "returncode": outputs.get("returncode"),
        "blocked_reason": outputs.get("blocked_reason"),
        "stdout_preview": _preview(outputs.get("stdout")),
        "stderr_preview": _preview(outputs.get("stderr")),
        "source_path": source_path,
        "evidence_type": "scout_agent_tool_result",
        "runtime_safety_truth": False,
        "phase1_safety_mutation_allowed": False,
        "live_safety_api_calls_allowed": False,
    }


def _severity_for_result(result: ScoutAgentToolResult) -> str:
    status = str(result.status)
    if status.endswith("failed"):
        return "error"
    if status.endswith("blocked") or status.endswith("partial"):
        return "warning"
    return "info"


def _preview(value: object, *, limit: int = 500) -> str | None:
    if value is None:
        return None
    text = str(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _safe_token(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.:-]+", "_", value)
