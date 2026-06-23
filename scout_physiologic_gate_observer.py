from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from scout_runtime_physiologic_integration import (
    PHYSIOLOGIC_GATE_STATUS_FILENAME,
    run_physio_integration_replay,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scout physiologic gate resident observer")
    parser.add_argument("--sensorlogger-vitals-jsonl", required=True)
    parser.add_argument("--evidence-dir", required=True)
    parser.add_argument("--baseline-json")
    parser.add_argument("--route-context-json")
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    parser.add_argument("--window-minutes", type=int, default=15)
    parser.add_argument("--max-records", type=int, default=1000)
    parser.add_argument("--activity-type", choices=["walking", "hiking", "running", "other"], default="hiking")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--print-ready", action="store_true")
    args = parser.parse_args(argv)

    evidence_dir = Path(args.evidence_dir).expanduser()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    if args.print_ready:
        print(
            json.dumps(
                {
                    "observer": "physiologic-gate",
                    "ready": True,
                    "evidence_dir": str(evidence_dir),
                    "safety_api_called": False,
                    "phase1_l0_l4_state_mutated": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            flush=True,
        )

    while True:
        _run_once(
            sensorlogger_vitals_jsonl=Path(args.sensorlogger_vitals_jsonl).expanduser(),
            evidence_dir=evidence_dir,
            baseline_json=Path(args.baseline_json).expanduser() if args.baseline_json else None,
            route_context_json=Path(args.route_context_json).expanduser() if args.route_context_json else None,
            window_minutes=args.window_minutes,
            activity_type=args.activity_type,
            max_records=args.max_records,
        )
        if args.once:
            return 0
        time.sleep(max(1.0, args.poll_seconds))


def _run_once(
    *,
    sensorlogger_vitals_jsonl: Path,
    evidence_dir: Path,
    baseline_json: Path | None,
    route_context_json: Path | None,
    window_minutes: int,
    activity_type: str,
    max_records: int,
) -> None:
    status_path = evidence_dir / PHYSIOLOGIC_GATE_STATUS_FILENAME
    try:
        route_context = _load_optional_json(route_context_json)
        result = run_physio_integration_replay(
            sensorlogger_vitals_jsonl,
            output_dir=evidence_dir,
            route_context=route_context,
            baseline_path=baseline_json,
            window_minutes=window_minutes,
            activity_type=activity_type,  # type: ignore[arg-type]
            max_records=max_records,
        )
        status_payload: dict[str, Any] = {
            **result.model_dump(mode="json"),
            "observer": "physiologic-gate",
            "last_error": None,
            "phase1_l0_l4_state_mutated": False,
            "safety_api_called": False,
            "outbound_alert_sent": False,
        }
    except Exception as exc:
        status_payload = {
            "artifact_kind": "scout_physiologic_gate_observer_status",
            "artifact_version": "physiologic_gate_observer_status.v1",
            "observer": "physiologic-gate",
            "source_provider": "scout_physiologic_gate_observer",
            "source_path": str(sensorlogger_vitals_jsonl),
            "last_error": f"{type(exc).__name__}:{exc}",
            "phase1_l0_l4_state_mutated": False,
            "safety_api_called": False,
            "outbound_alert_sent": False,
            "boundary": {
                "medical_diagnosis": False,
                "phase1_runtime_safety_truth": False,
                "safety_api_calls_allowed": False,
                "phase1_safety_state_mutation_allowed": False,
                "provider_values_are_scout_truth": False,
            },
        }
    status_path.write_text(json.dumps(status_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_optional_json(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
