from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.ins_dr_field_completion_gate import run_field_completion_gate  # noqa: E402
from tools.ins_dr_field_readiness_check import GNSS_SERIAL_AUTO_VALUE, resolve_requested_gnss_port  # noqa: E402
from tools.pi_dr_delta_smoke import build_dr_delta_payload  # noqa: E402
from tools.pi_gnss_nmea_smoke import parse_raw_nmea, read_serial_nmea  # noqa: E402


def run_manual_field_run(
    *,
    mission_graph_path: Path,
    output_dir: Path,
    gnss_port: str,
    gnss_baud: int,
    anchor_duration_seconds: float,
    reanchor_duration_seconds: float,
    distance_deltas_m: list[float],
    heading_degs: list[float | None],
    timestamp_s_values: list[float | None],
    raw_anchor_nmea: str | None = None,
    raw_reanchor_nmea: str | None = None,
    source: str = "manual_odometry_delta",
    provider: str = "operator_entered_distance_delta",
    require_reanchor: bool = True,
    min_dr_progress_m: float = 1.0,
    movement_window_seconds: float = 0.0,
    pretty: bool = False,
) -> dict[str, Any]:
    if movement_window_seconds < 0:
        raise ValueError("movement_window_seconds must be non-negative")
    output_dir.mkdir(parents=True, exist_ok=True)
    anchor_jsonl = output_dir / "anchor-gnss.jsonl"
    dr_jsonl = output_dir / "dr-delta.jsonl"
    reanchor_jsonl = output_dir / "reanchor-gnss.jsonl"
    runtime_updates_jsonl = output_dir / "runtime-updates.jsonl"
    field_report_json = output_dir / "field-report.json"
    proof_manifest_json = output_dir / "proof-manifest.json"
    verification_report_json = output_dir / "verification-report.json"

    anchor_payloads = _capture_gnss_payloads(
        raw_nmea=raw_anchor_nmea,
        port=gnss_port,
        baud=gnss_baud,
        duration_seconds=anchor_duration_seconds,
    )
    _write_jsonl(anchor_payloads, anchor_jsonl)

    dr_payloads = [
        build_dr_delta_payload(
            distance_delta_m=distance_delta_m,
            heading_deg=heading_deg,
            timestamp_s=timestamp_s,
            source=source,
            provider=provider,
        )
        for distance_delta_m, heading_deg, timestamp_s in zip(distance_deltas_m, heading_degs, timestamp_s_values)
    ]
    _write_jsonl(dr_payloads, dr_jsonl)

    if movement_window_seconds > 0:
        time.sleep(movement_window_seconds)

    reanchor_payloads = _capture_gnss_payloads(
        raw_nmea=raw_reanchor_nmea,
        port=gnss_port,
        baud=gnss_baud,
        duration_seconds=reanchor_duration_seconds,
    )
    _write_jsonl(reanchor_payloads, reanchor_jsonl)

    completion_report = run_field_completion_gate(
        mission_graph_path=mission_graph_path,
        payloads=anchor_payloads + dr_payloads + reanchor_payloads,
        input_jsonl_paths=[anchor_jsonl, dr_jsonl, reanchor_jsonl],
        raw_nmea=None,
        runtime_updates_path=runtime_updates_jsonl,
        field_report_path=field_report_json,
        proof_manifest_path=proof_manifest_json,
        verification_report_path=verification_report_json,
        require_reanchor=require_reanchor,
        min_dr_progress_m=min_dr_progress_m,
        device="scout_pi",
        source="manual_field_run_evidence",
        pretty=pretty,
    )

    return {
        "source": "ins_dr_manual_field_run",
        "artifact_kind": "ins_dr_manual_field_run_report",
        "scout_ins_dr_navigation_status": completion_report["scout_ins_dr_navigation_status"],
        "completion_ready": completion_report["completion_ready"],
        "anchor_payload_count": len(anchor_payloads),
        "dr_delta_count": len(dr_payloads),
        "reanchor_payload_count": len(reanchor_payloads),
        "movement_window_seconds": movement_window_seconds,
        "gnss_port": gnss_port,
        "gnss_baud": gnss_baud,
        "output_dir": str(output_dir),
        "anchor_jsonl": str(anchor_jsonl),
        "dr_jsonl": str(dr_jsonl),
        "reanchor_jsonl": str(reanchor_jsonl),
        "runtime_updates_jsonl": str(runtime_updates_jsonl),
        "field_report_json": str(field_report_json),
        "proof_manifest_json": str(proof_manifest_json),
        "verification_report_json": str(verification_report_json),
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_manual_field_run_only",
        "completion_report": completion_report,
    }


def _capture_gnss_payloads(
    *,
    raw_nmea: str | None,
    port: str,
    baud: int,
    duration_seconds: float,
) -> list[dict[str, Any]]:
    if raw_nmea is not None:
        return parse_raw_nmea(
            raw_nmea,
            device_port=port,
            baud=baud,
            capture_mode="raw_nmea_argument",
        )
    lines = read_serial_nmea(port=port, baud=baud, duration_seconds=duration_seconds)
    return parse_raw_nmea(
        "\n".join(lines),
        device_port=port,
        baud=baud,
        capture_mode="serial_device",
    )


def _write_jsonl(payloads: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "".join(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n" for payload in payloads),
        encoding="utf-8",
    )


def _expand_optional_values(values: list[float] | None, count: int, *, name: str) -> list[float | None]:
    if not values:
        return [None] * count
    if len(values) == 1:
        return [values[0]] * count
    if len(values) != count:
        raise ValueError(f"{name} must be omitted, provided once, or repeated once per --distance-delta-m")
    return list(values)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Capture a manual Scout INS/DR field run: GNSS anchor, DR delta, GNSS re-anchor, completion gate."
    )
    parser.add_argument("--mission-graph", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--gnss-port", default="/dev/ttyUSB0")
    parser.add_argument("--gnss-baud", type=int, default=9600)
    parser.add_argument("--anchor-duration-seconds", type=float, default=10.0)
    parser.add_argument("--reanchor-duration-seconds", type=float, default=10.0)
    parser.add_argument("--distance-delta-m", type=float, action="append", required=True)
    parser.add_argument("--heading-deg", type=float, action="append")
    parser.add_argument("--timestamp-s", type=float, action="append")
    parser.add_argument("--source", default="manual_odometry_delta")
    parser.add_argument("--provider", default="operator_entered_distance_delta")
    parser.add_argument("--raw-anchor-nmea", help="Fixture/debug NMEA text for the anchor capture.")
    parser.add_argument("--raw-reanchor-nmea", help="Fixture/debug NMEA text for the re-anchor capture.")
    parser.add_argument("--no-require-reanchor", action="store_true")
    parser.add_argument("--min-dr-progress-m", type=float, default=1.0)
    parser.add_argument(
        "--movement-window-seconds",
        type=float,
        default=0.0,
        help="Seconds to wait after anchor capture and DR delta writing so the operator can move before re-anchor.",
    )
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    try:
        for distance_delta_m in args.distance_delta_m:
            if distance_delta_m < 0:
                raise ValueError("distance_delta_m must be non-negative")
        heading_degs = _expand_optional_values(args.heading_deg, len(args.distance_delta_m), name="--heading-deg")
        timestamp_s_values = _expand_optional_values(args.timestamp_s, len(args.distance_delta_m), name="--timestamp-s")
        if args.timestamp_s is None:
            now = time.time()
            timestamp_s_values = [now + index for index in range(len(args.distance_delta_m))]
        gnss_port = args.gnss_port
        if gnss_port == GNSS_SERIAL_AUTO_VALUE:
            resolved_port, serial_evidence = resolve_requested_gnss_port(Path(gnss_port))
            if not resolved_port.exists() or serial_evidence["auto_detection_status"] == "ambiguous_serial_candidates":
                raise ValueError(f"unable to resolve --gnss-port auto: {json.dumps(serial_evidence, sort_keys=True)}")
            gnss_port = str(resolved_port)
        report = run_manual_field_run(
            mission_graph_path=args.mission_graph,
            output_dir=args.output_dir,
            gnss_port=gnss_port,
            gnss_baud=args.gnss_baud,
            anchor_duration_seconds=args.anchor_duration_seconds,
            reanchor_duration_seconds=args.reanchor_duration_seconds,
            distance_deltas_m=args.distance_delta_m,
            heading_degs=heading_degs,
            timestamp_s_values=timestamp_s_values,
            raw_anchor_nmea=args.raw_anchor_nmea,
            raw_reanchor_nmea=args.raw_reanchor_nmea,
            source=args.source,
            provider=args.provider,
            require_reanchor=not args.no_require_reanchor,
            min_dr_progress_m=args.min_dr_progress_m,
            movement_window_seconds=args.movement_window_seconds,
            pretty=args.pretty,
        )
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=not args.pretty))
    return 0 if report["completion_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
