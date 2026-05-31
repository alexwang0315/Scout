from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.ins_dr_field_proof_pipeline import (  # noqa: E402
    build_proof_manifest,
    run_field_proof_pipeline,
    write_json,
    write_updates_jsonl,
)
from tools.ins_dr_navigation_smoke import load_jsonl_payloads  # noqa: E402
from tools.ins_dr_proof_manifest_check import verify_proof_manifest  # noqa: E402
from tools.pi_gnss_nmea_smoke import parse_raw_nmea  # noqa: E402


def run_field_completion_gate(
    *,
    mission_graph_path: Path,
    payloads: list[dict[str, Any]],
    input_jsonl_paths: list[Path],
    raw_nmea: str | None,
    runtime_updates_path: Path,
    field_report_path: Path,
    proof_manifest_path: Path,
    verification_report_path: Path | None = None,
    require_reanchor: bool = False,
    min_dr_progress_m: float = 1.0,
    device: str = "scout_pi",
    source: str = "runtime_provider_evidence",
    pretty: bool = False,
) -> dict[str, Any]:
    pipeline = run_field_proof_pipeline(
        mission_graph_path=mission_graph_path,
        payloads=payloads,
        require_reanchor=require_reanchor,
        min_dr_progress_m=min_dr_progress_m,
        device=device,
        source=source,
    )
    write_updates_jsonl(pipeline["runtime_updates"], runtime_updates_path)
    write_json(pipeline["field_report"], field_report_path, pretty=pretty)
    proof_manifest = build_proof_manifest(
        result=pipeline,
        mission_graph_path=mission_graph_path,
        input_jsonl_paths=input_jsonl_paths,
        raw_nmea=raw_nmea,
        runtime_updates_path=runtime_updates_path,
        field_report_path=field_report_path,
    )
    write_json(proof_manifest, proof_manifest_path, pretty=pretty)
    verification = verify_proof_manifest(
        proof_manifest_path=proof_manifest_path,
        require_reanchor=require_reanchor,
    )
    write_json(verification, verification_report_path, pretty=pretty)

    completion_ready = pipeline["usable_navigation_evidence"] is True and verification["completion_ready"] is True
    return {
        "source": "ins_dr_field_completion_gate",
        "artifact_kind": "ins_dr_field_completion_gate_report",
        "scout_ins_dr_navigation_status": "field_ready" if completion_ready else "not_field_ready",
        "completion_ready": completion_ready,
        "field_proof_status": pipeline["field_proof_status"],
        "proof_manifest_status": verification["proof_manifest_status"],
        "usable_navigation_evidence": pipeline["usable_navigation_evidence"],
        "require_reanchor": require_reanchor,
        "min_dr_progress_m": min_dr_progress_m,
        "runtime_updates_jsonl": str(runtime_updates_path),
        "field_report_json": str(field_report_path),
        "proof_manifest_json": str(proof_manifest_path),
        "verification_report_json": str(verification_report_path) if verification_report_path else None,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_field_completion_gate_only",
        "pipeline_summary": {
            "input_payload_count": pipeline["input_payload_count"],
            "runtime_update_count": pipeline["runtime_update_count"],
            "latest_position_estimate": pipeline["runtime_summary"]["latest_position_estimate"],
            "latest_route_progress_sample": pipeline["runtime_summary"]["latest_route_progress_sample"],
            "dr_distance_source_summary": pipeline["dr_distance_source_summary"],
            "dr_heading_summary": pipeline["dr_heading_summary"],
        },
        "verification_report": verification,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run Scout INS/DR field proof pipeline and manifest verification as one completion gate."
    )
    parser.add_argument("--mission-graph", type=Path, required=True)
    parser.add_argument("--input-jsonl", type=Path, action="append", default=[], help="Evidence JSONL file. May repeat.")
    parser.add_argument("--raw-nmea", help="Parse fixture NMEA text and feed it before JSONL inputs.")
    parser.add_argument("--runtime-updates-jsonl", type=Path, required=True)
    parser.add_argument("--field-report-json", type=Path, required=True)
    parser.add_argument("--proof-manifest-json", type=Path, required=True)
    parser.add_argument("--verification-report-json", type=Path)
    parser.add_argument("--require-reanchor", action="store_true")
    parser.add_argument("--min-dr-progress-m", type=float, default=1.0)
    parser.add_argument("--device", default="scout_pi")
    parser.add_argument("--source", default="runtime_provider_evidence")
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
        report = run_field_completion_gate(
            mission_graph_path=args.mission_graph,
            payloads=payloads,
            input_jsonl_paths=args.input_jsonl,
            raw_nmea=args.raw_nmea,
            runtime_updates_path=args.runtime_updates_jsonl,
            field_report_path=args.field_report_json,
            proof_manifest_path=args.proof_manifest_json,
            verification_report_path=args.verification_report_json,
            require_reanchor=args.require_reanchor,
            min_dr_progress_m=args.min_dr_progress_m,
            device=args.device,
            source=args.source,
            pretty=args.pretty,
        )
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=not args.pretty))
    return 0 if report["completion_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
