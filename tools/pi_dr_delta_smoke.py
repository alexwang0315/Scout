from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def build_dr_delta_payload(
    *,
    distance_delta_m: float,
    heading_deg: float | None = None,
    timestamp_s: float | None = None,
    source: str = "manual_odometry_delta",
    provider: str = "operator_entered_distance_delta",
) -> dict[str, Any]:
    if distance_delta_m < 0:
        raise ValueError("distance_delta_m must be non-negative")
    if heading_deg is not None and not 0.0 <= heading_deg < 360.0:
        raise ValueError("heading_deg must be in [0, 360)")

    captured_at = datetime.now(timezone.utc).isoformat()
    effective_timestamp_s = timestamp_s if timestamp_s is not None else datetime.now(timezone.utc).timestamp()
    payload: dict[str, Any] = {
        "source": source,
        "provider": provider,
        "hardware_kind": "dead_reckoning_delta_evidence",
        "timestamp_s": effective_timestamp_s,
        "distance_delta_m": distance_delta_m,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "primary_truth_allowed": False,
        "hardware_control_scope": "diagnostic_odometry_delta_only",
        "raw_evidence_ref": f"pi_dr_delta_smoke:{effective_timestamp_s:g}",
        "captured_at": captured_at,
    }
    if heading_deg is not None:
        payload["heading_deg"] = heading_deg
    return payload


def append_jsonl(payload: dict[str, Any], output_path: Path | None) -> None:
    if output_path is None:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create one Scout diagnostic dead-reckoning distance delta JSONL payload."
    )
    parser.add_argument("--distance-delta-m", type=float, required=True)
    parser.add_argument("--heading-deg", type=float)
    parser.add_argument("--timestamp-s", type=float)
    parser.add_argument("--source", default="manual_odometry_delta")
    parser.add_argument("--provider", default="operator_entered_distance_delta")
    parser.add_argument("--output-jsonl", type=Path)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    try:
        payload = build_dr_delta_payload(
            distance_delta_m=args.distance_delta_m,
            heading_deg=args.heading_deg,
            timestamp_s=args.timestamp_s,
            source=args.source,
            provider=args.provider,
        )
        append_jsonl(payload, args.output_jsonl)
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    output = {
        "source": "pi_dr_delta_smoke",
        "hardware_kind": "dead_reckoning_delta_evidence",
        "payload_count": 1,
        "output_jsonl": str(args.output_jsonl) if args.output_jsonl else None,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_odometry_delta_only",
        "payloads": [payload],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=not args.pretty))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
