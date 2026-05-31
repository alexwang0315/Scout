from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ins_dr_input_adapter import (  # noqa: E402
    InsDrInputState,
    dead_reckoning_delta_from_payload,
    gnss_fix_from_payload,
    vendor_fusion_from_payload,
)
from ins_dr_navigation import InsDrConfig, InsDrEstimate, ScoutInsDrNavigator  # noqa: E402
from route_matching import load_gpx_route  # noqa: E402
from tools.pi_gnss_nmea_smoke import parse_raw_nmea  # noqa: E402


def build_ins_dr_estimates(
    *,
    route_path: Path,
    payloads: list[dict[str, Any]],
    config: InsDrConfig | None = None,
) -> list[InsDrEstimate]:
    route = load_gpx_route(route_path)
    navigator = ScoutInsDrNavigator(route, config=config)
    state = InsDrInputState()
    estimates: list[InsDrEstimate] = []

    for index, payload in enumerate(payloads):
        fallback_timestamp_s = float(index)
        gnss_fix = gnss_fix_from_payload(payload, fallback_timestamp_s=fallback_timestamp_s)
        dr_delta = dead_reckoning_delta_from_payload(
            payload,
            state,
            fallback_timestamp_s=fallback_timestamp_s,
        )
        vendor_fusion = vendor_fusion_from_payload(payload, fallback_timestamp_s=fallback_timestamp_s)

        if gnss_fix is None and dr_delta is None and vendor_fusion is None:
            continue
        if gnss_fix is not None and not gnss_fix.has_position and dr_delta is None and vendor_fusion is None:
            continue

        estimates.append(
            navigator.observe(
                gnss_fix=gnss_fix,
                dr_delta=dr_delta,
                vendor_fusion=vendor_fusion,
            )
        )

    return estimates


def load_jsonl_payloads(paths: list[Path]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                payload = json.loads(stripped)
                if not isinstance(payload, dict):
                    raise ValueError(f"{path}:{line_number} is not a JSON object")
                payload.setdefault("raw_evidence_ref", f"{path}:{line_number}")
                payloads.append(payload)
    return payloads


def append_estimates_jsonl(estimates: list[InsDrEstimate], output_path: Path | None) -> None:
    if output_path is None:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        for estimate in estimates:
            handle.write(json.dumps(_estimate_payload(estimate), ensure_ascii=False, sort_keys=True) + "\n")


def _estimate_payload(estimate: InsDrEstimate) -> dict[str, Any]:
    payload = estimate.to_dict()
    payload.update(
        {
            "source_tool": "ins_dr_navigation_smoke",
            "hardware_kind": "host_side_ins_dr_navigation_estimate",
            "phase1_safety_decision_change_allowed": False,
            "remote_outbound_allowed": False,
            "hardware_control_scope": "diagnostic_navigation_estimate_only",
        }
    )
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Scout host-side INS/DR estimates from raw evidence JSONL.")
    parser.add_argument("--route", type=Path, required=True, help="Planned GPX route used for route-aligned estimates.")
    parser.add_argument("--input-jsonl", type=Path, action="append", default=[], help="Evidence JSONL file. May repeat.")
    parser.add_argument("--raw-nmea", help="Parse fixture NMEA text and feed it before JSONL inputs.")
    parser.add_argument("--output-jsonl", type=Path)
    parser.add_argument("--vendor-disagreement-threshold-m", type=float, default=35.0)
    parser.add_argument("--max-dead-reckoning-seconds", type=float, default=300.0)
    parser.add_argument("--max-dead-reckoning-distance-m", type=float, default=250.0)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    try:
        payloads: list[dict[str, Any]] = []
        if args.raw_nmea is not None:
            payloads.extend(
                parse_raw_nmea(
                    args.raw_nmea,
                    device_port="raw-nmea",
                    baud=0,
                    capture_mode="raw_nmea_argument",
                )
            )
        payloads.extend(load_jsonl_payloads(args.input_jsonl))
        estimates = build_ins_dr_estimates(
            route_path=args.route,
            payloads=payloads,
            config=InsDrConfig(
                vendor_disagreement_threshold_m=args.vendor_disagreement_threshold_m,
                max_dead_reckoning_seconds=args.max_dead_reckoning_seconds,
                max_dead_reckoning_distance_m=args.max_dead_reckoning_distance_m,
            ),
        )
        append_estimates_jsonl(estimates, args.output_jsonl)
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    output = {
        "source": "ins_dr_navigation_smoke",
        "hardware_kind": "host_side_ins_dr_navigation_estimate",
        "route": str(args.route),
        "input_payload_count": len(payloads),
        "estimate_count": len(estimates),
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_navigation_estimate_only",
        "estimates": [_estimate_payload(estimate) for estimate in estimates],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=not args.pretty))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
