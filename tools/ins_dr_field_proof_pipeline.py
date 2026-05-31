from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.ins_dr_field_evidence_check import build_field_evidence_report  # noqa: E402
from tools.ins_dr_navigation_smoke import load_jsonl_payloads  # noqa: E402
from tools.ins_dr_runtime_smoke import run_ins_dr_runtime_smoke  # noqa: E402
from tools.pi_gnss_nmea_smoke import parse_raw_nmea  # noqa: E402


def run_field_proof_pipeline(
    *,
    mission_graph_path: Path,
    payloads: list[dict[str, Any]],
    require_reanchor: bool = False,
    min_dr_progress_m: float = 1.0,
    device: str = "scout_pi",
    source: str = "runtime_provider_evidence",
) -> dict[str, Any]:
    runtime_result = run_ins_dr_runtime_smoke(
        mission_graph_path=mission_graph_path,
        payloads=payloads,
        device=device,
        source=source,
    )
    field_report = build_field_evidence_report(
        runtime_result["updates"],
        require_reanchor=require_reanchor,
        min_dr_progress_m=min_dr_progress_m,
    )
    return {
        "source": "ins_dr_field_proof_pipeline",
        "hardware_kind": "ins_dr_field_proof_pipeline",
        "mission_graph": str(mission_graph_path),
        "input_payload_count": len(payloads),
        "runtime_update_count": len(runtime_result["updates"]),
        "field_proof_status": field_report["field_proof_status"],
        "usable_navigation_evidence": field_report["usable_navigation_evidence"],
        "require_reanchor": require_reanchor,
        "min_dr_progress_m": min_dr_progress_m,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_field_proof_pipeline_only",
        "runtime_summary": {
            "source": runtime_result["source"],
            "latest_position_estimate": runtime_result["latest_position_estimate"],
            "latest_route_progress_sample": runtime_result["latest_route_progress_sample"],
            "safety_level": runtime_result["safety_level"],
        },
        "dr_distance_source_summary": field_report["dr_distance_source_summary"],
        "dr_heading_summary": field_report["dr_heading_summary"],
        "field_report": field_report,
        "runtime_updates": runtime_result["updates"],
    }


def write_json(payload: dict[str, Any], output_path: Path | None, *, pretty: bool) -> None:
    if output_path is None:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2 if pretty else None, sort_keys=not pretty) + "\n",
        encoding="utf-8",
    )


def write_updates_jsonl(updates: list[dict[str, Any]], output_path: Path | None) -> None:
    if output_path is None:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "".join(json.dumps(update, ensure_ascii=False, sort_keys=True) + "\n" for update in updates),
        encoding="utf-8",
    )


def build_proof_manifest(
    *,
    result: dict[str, Any],
    mission_graph_path: Path,
    input_jsonl_paths: list[Path],
    raw_nmea: str | None,
    runtime_updates_path: Path | None,
    field_report_path: Path | None,
) -> dict[str, Any]:
    return {
        "source": "ins_dr_field_proof_pipeline",
        "artifact_kind": "ins_dr_field_proof_manifest",
        "manifest_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "field_proof_status": result["field_proof_status"],
        "usable_navigation_evidence": result["usable_navigation_evidence"],
        "mission_graph_ref": _file_ref(mission_graph_path),
        "input_refs": [_file_ref(path) for path in input_jsonl_paths],
        "raw_nmea_ref": _text_ref(raw_nmea) if raw_nmea is not None else None,
        "output_refs": {
            "runtime_updates_jsonl": _file_ref(runtime_updates_path) if runtime_updates_path else None,
            "field_report_json": _file_ref(field_report_path) if field_report_path else None,
        },
        "completion_evidence": {
            "require_reanchor": result["require_reanchor"],
            "min_dr_progress_m": result["min_dr_progress_m"],
            "runtime_update_count": result["runtime_update_count"],
            "dr_distance_source_summary": result["field_report"].get("dr_distance_source_summary"),
            "dr_heading_summary": result["field_report"].get("dr_heading_summary"),
            "field_report_checks": result["field_report"]["checks"],
        },
        "boundary": {
            "phase1_safety_decision_change_allowed": False,
            "remote_outbound_allowed": False,
            "hardware_control_scope": "diagnostic_field_proof_manifest_only",
            "live_safety_api_called": False,
            "hardware_control_performed": False,
        },
    }


def _file_ref(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    return {
        "path": str(path),
        "exists": path.exists(),
        "sha256": _sha256_file(path) if path.exists() else None,
    }


def _text_ref(text: str) -> dict[str, Any]:
    return {
        "source": "raw_nmea_argument",
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run Scout INS/DR runtime replay and field evidence check in one diagnostic pipeline."
    )
    parser.add_argument("--mission-graph", type=Path, required=True)
    parser.add_argument("--input-jsonl", type=Path, action="append", default=[], help="Evidence JSONL file. May repeat.")
    parser.add_argument("--raw-nmea", help="Parse fixture NMEA text and feed it before JSONL inputs.")
    parser.add_argument("--runtime-updates-jsonl", type=Path)
    parser.add_argument("--field-report-json", type=Path)
    parser.add_argument("--proof-manifest-json", type=Path)
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
        result = run_field_proof_pipeline(
            mission_graph_path=args.mission_graph,
            payloads=payloads,
            require_reanchor=args.require_reanchor,
            min_dr_progress_m=args.min_dr_progress_m,
            device=args.device,
            source=args.source,
        )
        write_updates_jsonl(result["runtime_updates"], args.runtime_updates_jsonl)
        write_json(result["field_report"], args.field_report_json, pretty=args.pretty)
        proof_manifest = build_proof_manifest(
            result=result,
            mission_graph_path=args.mission_graph,
            input_jsonl_paths=args.input_jsonl,
            raw_nmea=args.raw_nmea,
            runtime_updates_path=args.runtime_updates_jsonl,
            field_report_path=args.field_report_json,
        )
        write_json(proof_manifest, args.proof_manifest_json, pretty=args.pretty)
        result["proof_manifest"] = proof_manifest
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=not args.pretty))
    return 0 if result["usable_navigation_evidence"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
