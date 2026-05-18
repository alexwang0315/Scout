from __future__ import annotations

import argparse
import json
from pathlib import Path

from runtime_debug_log import FileRuntimeDebugEventLog, MemoryRuntimeDebugEventLog
from runtime_simulator import run_runtime_debug_replay, runtime_debug_replay_summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a Scout Phase 3.5 runtime debug replay.")
    parser.add_argument("--mission", required=True, type=Path, help="MissionGraph JSON path.")
    parser.add_argument("--route", required=True, type=Path, help="Observed route GPX path.")
    parser.add_argument("--map-context", type=Path, default=None, help="Optional offline map GeoJSON path.")
    parser.add_argument("--risk-rules", type=Path, default=None, help="Optional risk rules JSON path.")
    parser.add_argument("--mission-context", type=Path, default=None, help="Optional Go/No-Go context JSON path.")
    parser.add_argument("--route-progress-config", type=Path, default=None, help="Optional route progress config JSON.")
    parser.add_argument("--incident-store", type=Path, default=None, help="Optional incident store directory.")
    parser.add_argument("--debug-log", type=Path, default=None, help="Optional JSONL debug event log path.")
    parser.add_argument("--session-id", default=None, help="Optional debug session id.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON summary.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    debug_log = FileRuntimeDebugEventLog(args.debug_log) if args.debug_log else MemoryRuntimeDebugEventLog()
    result = run_runtime_debug_replay(
        mission_graph_path=args.mission,
        route_path=args.route,
        map_context_path=args.map_context,
        risk_rules_path=args.risk_rules,
        mission_context_path=args.mission_context,
        route_progress_config_path=args.route_progress_config,
        incident_store_path=args.incident_store,
        debug_log=debug_log,
        session_id=args.session_id,
    )
    indent = 2 if args.pretty else None
    print(json.dumps(runtime_debug_replay_summary(result), indent=indent, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
