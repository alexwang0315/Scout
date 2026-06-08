from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from replay_runner import ReplayResult, replay_route


def run_phase1_replay_demo(args: argparse.Namespace) -> dict[str, Any]:
    result = replay_route(
        mission_graph_path=args.mission,
        route_path=args.route,
        map_context_path=args.map_context,
        risk_rules_path=args.risk_rules,
        mission_context_path=args.mission_context,
        route_progress_config_path=args.route_progress_config,
        incident_store_path=args.incident_store,
    )
    return phase1_replay_summary(result)


def phase1_replay_summary(result: ReplayResult) -> dict[str, Any]:
    progressed_checkpoints = [
        update.checkpoint.checkpoint_id for update in result.progress_updates if update.checkpoint is not None
    ]
    return {
        "observations_processed": result.observations_processed,
        "safety_level": result.safety_state.level,
        "safety_events": [event.event_type for event in result.safety_events],
        "incident_ids": [package.incident_id for package in result.incident_packages],
        "stored_incident_paths": [str(path) for path in result.stored_incident_paths],
        "checkpoint_count": len(progressed_checkpoints),
        "checkpoint_hit_count": len(result.checkpoint_hits),
        "progressed_checkpoints": progressed_checkpoints,
        "segment_capsule_count": len(result.segment_capsules),
        "segment_capsules": [capsule.capsule_id for capsule in result.segment_capsules],
        "recording_profiles": sorted({decision.profile for decision in result.recording_decisions}),
        "latest_incident_summary": result.incident_packages[-1].ai_summary_input if result.incident_packages else None,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a Scout Fusion Phase 1 route replay demo.")
    parser.add_argument("--mission", required=True, type=Path, help="MissionGraph JSON path.")
    parser.add_argument("--route", required=True, type=Path, help="Observed route GPX path.")
    parser.add_argument("--map-context", type=Path, default=None, help="Optional offline map GeoJSON path.")
    parser.add_argument("--risk-rules", type=Path, default=None, help="Optional risk rules JSON path.")
    parser.add_argument("--mission-context", type=Path, default=None, help="Optional Go/No-Go mission context JSON path.")
    parser.add_argument("--route-progress-config", type=Path, default=None, help="Optional route progress config JSON path.")
    parser.add_argument("--incident-store", type=Path, default=None, help="Optional directory for incident package JSON.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    summary = run_phase1_replay_demo(args)
    indent = 2 if args.pretty else None
    print(json.dumps(summary, indent=indent, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
