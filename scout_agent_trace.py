from __future__ import annotations

import json
from pathlib import Path

from scout_agent_models import ScoutAgentToolResult


def append_agent_trace(path: str | Path, result: ScoutAgentToolResult) -> None:
    trace_path = Path(path)
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    with trace_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(result.model_dump(mode="json"), ensure_ascii=False))
        handle.write("\n")


def load_agent_trace(path: str | Path) -> list[ScoutAgentToolResult]:
    trace_path = Path(path)
    if not trace_path.exists():
        return []
    results: list[ScoutAgentToolResult] = []
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            results.append(ScoutAgentToolResult.model_validate_json(line))
    return results


def tail_agent_trace(path: str | Path, *, limit: int = 20) -> list[ScoutAgentToolResult]:
    if limit <= 0:
        return []
    return load_agent_trace(path)[-limit:]
