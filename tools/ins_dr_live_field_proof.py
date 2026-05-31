from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.ins_dr_diagnostic_route_scaffold import build_diagnostic_route_scaffold  # noqa: E402
from tools.ins_dr_field_completion_gate import run_field_completion_gate  # noqa: E402
from tools.ins_dr_field_readiness_check import (  # noqa: E402
    FIELD_RUN_ARTIFACT_NAMES,
    GNSS_SERIAL_AUTO_VALUE,
    resolve_requested_gnss_port,
)
from tools.ins_dr_navigation_smoke import load_jsonl_payloads  # noqa: E402
from tools.pi_dr_delta_smoke import build_dr_delta_payload  # noqa: E402
from tools.pi_gnss_nmea_smoke import parse_raw_nmea, read_serial_nmea, summarize_gnss_signal  # noqa: E402
from tools.pi_wheel_encoder_gpio_smoke import (  # noqa: E402
    capture_wheel_encoder_records,
    write_jsonl as write_wheel_encoder_jsonl,
)
from tools.pi_wheel_odometry_delta_smoke import (  # noqa: E402
    build_wheel_odometry_delta_payloads,
    load_wheel_odometry_jsonl,
)


LIVE_FIELD_PROOF_REPORT_NAME = "live-field-proof-report.json"
ROUTE_SCAFFOLD_REPORT_NAME = "route-scaffold-report.json"
OPERATOR_EVENTS_NAME = "operator-events.jsonl"


def run_live_field_proof(
    *,
    output_dir: Path,
    mission_id: str,
    gnss_port: str,
    gnss_baud: int,
    anchor_duration_seconds: float,
    reanchor_duration_seconds: float,
    distance_deltas_m: list[float] | None = None,
    heading_degs: list[float | None] | None = None,
    timestamp_s_values: list[float | None] | None = None,
    route_heading_deg: float | None = None,
    route_distance_m: float | None = None,
    corridor_half_width_m: float = 6.0,
    point_count: int = 5,
    movement_window_seconds: float = 0.0,
    anchor_wait_timeout_seconds: float | None = None,
    anchor_retry_interval_seconds: float = 0.0,
    reanchor_wait_timeout_seconds: float | None = None,
    reanchor_retry_interval_seconds: float = 0.0,
    raw_anchor_nmea: str | None = None,
    raw_reanchor_nmea: str | None = None,
    readiness_report_json_path: Path | None = None,
    source: str = "manual_odometry_delta",
    provider: str = "operator_entered_distance_delta",
    heading_evidence_jsonl_paths: list[Path] | None = None,
    wheel_odometry_jsonl_paths: list[Path] | None = None,
    wheel_encoder_gpio_capture: bool = False,
    wheel_encoder_left_gpio: int = 20,
    wheel_encoder_right_gpio: int = 21,
    wheel_encoder_capture_duration_seconds: float = 10.0,
    wheel_encoder_sample_interval_seconds: float = 1.0,
    wheel_encoder_poll_interval_ms: float = 5.0,
    wheel_encoder_active_low: bool = False,
    wheel_encoder_gpiochip: str = "gpiochip0",
    wheel_source: str = "wheel_odometry",
    wheel_provider: str = "scout_wheel_encoder",
    wheel_meters_per_tick: float | None = None,
    wheel_max_delta_m: float = 25.0,
    require_reanchor: bool = True,
    min_dr_progress_m: float = 1.0,
    allow_overwrite: bool = False,
    pretty: bool = False,
) -> dict[str, Any]:
    distance_deltas_m = distance_deltas_m or []
    heading_degs = heading_degs or []
    timestamp_s_values = timestamp_s_values or []
    heading_evidence_jsonl_paths = heading_evidence_jsonl_paths or []
    wheel_odometry_jsonl_paths = wheel_odometry_jsonl_paths or []
    manual_delta_requested = bool(distance_deltas_m)
    wheel_delta_requested = bool(wheel_odometry_jsonl_paths)
    requested_dr_source_count = sum(
        1 for requested in (manual_delta_requested, wheel_delta_requested, wheel_encoder_gpio_capture) if requested
    )
    if requested_dr_source_count != 1:
        raise ValueError(
            "provide exactly one of distance_deltas_m, wheel_odometry_jsonl_paths, or wheel_encoder_gpio_capture"
        )
    if not manual_delta_requested:
        if heading_degs or timestamp_s_values:
            raise ValueError("heading_degs and timestamp_s_values are only valid with manual distance_deltas_m")
    elif len(heading_degs) != len(distance_deltas_m) or len(timestamp_s_values) != len(distance_deltas_m):
        raise ValueError("heading_degs and timestamp_s_values must match distance_deltas_m")
    for distance_delta_m in distance_deltas_m:
        if distance_delta_m < 0:
            raise ValueError("distance_delta_m must be non-negative")
    if anchor_wait_timeout_seconds is not None and anchor_wait_timeout_seconds < 0:
        raise ValueError("anchor_wait_timeout_seconds must be non-negative")
    if anchor_retry_interval_seconds < 0:
        raise ValueError("anchor_retry_interval_seconds must be non-negative")
    if reanchor_wait_timeout_seconds is not None and reanchor_wait_timeout_seconds < 0:
        raise ValueError("reanchor_wait_timeout_seconds must be non-negative")
    if reanchor_retry_interval_seconds < 0:
        raise ValueError("reanchor_retry_interval_seconds must be non-negative")
    if raw_anchor_nmea is None and anchor_duration_seconds <= 0:
        raise ValueError("anchor_duration_seconds must be positive for live serial capture")
    if raw_reanchor_nmea is None and reanchor_duration_seconds <= 0:
        raise ValueError("reanchor_duration_seconds must be positive for live serial capture")
    if wheel_encoder_gpio_capture:
        if wheel_meters_per_tick is None or wheel_meters_per_tick <= 0:
            raise ValueError("wheel_meters_per_tick must be positive when wheel_encoder_gpio_capture is enabled")
        if wheel_encoder_capture_duration_seconds <= 0:
            raise ValueError("wheel_encoder_capture_duration_seconds must be positive")
        if wheel_encoder_sample_interval_seconds <= 0:
            raise ValueError("wheel_encoder_sample_interval_seconds must be positive")
        if wheel_encoder_poll_interval_ms <= 0:
            raise ValueError("wheel_encoder_poll_interval_ms must be positive")

    field_run_dir = output_dir / "field-run"
    conflicts = _output_conflicts(output_dir=output_dir, field_run_dir=field_run_dir, mission_id=mission_id)
    if conflicts and not allow_overwrite:
        raise ValueError(f"output_dir already contains field proof artifacts: {', '.join(conflicts)}")

    anchor_jsonl = field_run_dir / "anchor-gnss.jsonl"
    dr_jsonl = field_run_dir / "dr-delta.jsonl"
    reanchor_jsonl = field_run_dir / "reanchor-gnss.jsonl"
    runtime_updates_jsonl = field_run_dir / "runtime-updates.jsonl"
    field_report_json = field_run_dir / "field-report.json"
    proof_manifest_json = field_run_dir / "proof-manifest.json"
    verification_report_json = field_run_dir / "verification-report.json"
    wheel_encoder_capture_jsonl = field_run_dir / "wheel-encoder-gpio-capture.jsonl"
    route_scaffold_report_json = output_dir / ROUTE_SCAFFOLD_REPORT_NAME
    live_report_json = output_dir / LIVE_FIELD_PROOF_REPORT_NAME
    operator_events_jsonl = output_dir / OPERATOR_EVENTS_NAME

    operator_events: list[dict[str, Any]] = []
    resolved_gnss_port, serial_evidence = _resolve_capture_port(
        gnss_port=gnss_port,
        readiness_report_json_path=readiness_report_json_path,
        raw_anchor_nmea=raw_anchor_nmea,
        raw_reanchor_nmea=raw_reanchor_nmea,
    )
    _record_operator_event(
        operator_events,
        event_type="anchor_capture_start",
        message=f"Capturing GNSS anchor for {anchor_duration_seconds:g}s.",
        details={
            "gnss_port": resolved_gnss_port,
            "duration_seconds": anchor_duration_seconds,
            "anchor_wait_timeout_seconds": anchor_wait_timeout_seconds,
            "anchor_retry_interval_seconds": anchor_retry_interval_seconds,
        },
    )
    anchor_payloads, anchor_capture_summary = _capture_anchor_payloads(
        raw_nmea=raw_anchor_nmea,
        port=resolved_gnss_port,
        baud=gnss_baud,
        duration_seconds=anchor_duration_seconds,
        wait_timeout_seconds=anchor_wait_timeout_seconds,
        retry_interval_seconds=anchor_retry_interval_seconds,
        operator_events=operator_events,
        capture_label="Anchor",
        attempt_event_type="anchor_capture_attempt",
    )
    try:
        start_lat, start_lon = _first_valid_gnss_position(anchor_payloads)
    except ValueError as exc:
        anchor_failure_diagnosis = _anchor_failure_diagnosis(anchor_payloads)
        _record_operator_event(
            operator_events,
            event_type="anchor_capture_failed",
            message=f"GNSS anchor capture did not produce a valid position: {exc}",
            details={
                "anchor_payload_count": len(anchor_payloads),
                "anchor_capture_summary": anchor_capture_summary,
                "gnss_signal_summary": summarize_gnss_signal(anchor_payloads),
                "anchor_failure_diagnosis": anchor_failure_diagnosis,
            },
        )
        return _write_anchor_failure_report(
            output_dir=output_dir,
            field_run_dir=field_run_dir,
            mission_id=mission_id,
            requested_gnss_port=gnss_port,
            resolved_gnss_port=resolved_gnss_port,
            gnss_baud=gnss_baud,
            serial_evidence=serial_evidence,
            anchor_payloads=anchor_payloads,
            anchor_capture_summary=anchor_capture_summary,
            operator_events=operator_events,
            anchor_jsonl=anchor_jsonl,
            live_report_json=live_report_json,
            operator_events_jsonl=operator_events_jsonl,
            route_scaffold_report_json=route_scaffold_report_json,
            dr_jsonl=dr_jsonl,
            reanchor_jsonl=reanchor_jsonl,
            runtime_updates_jsonl=runtime_updates_jsonl,
            field_report_json=field_report_json,
            proof_manifest_json=proof_manifest_json,
            verification_report_json=verification_report_json,
            failure_reason=str(exc),
            anchor_failure_diagnosis=anchor_failure_diagnosis,
            pretty=pretty,
        )
    _record_operator_event(
        operator_events,
        event_type="anchor_capture_complete",
        message="GNSS anchor captured. Route scaffold will be built from the first valid anchor position.",
        details={
            "anchor_payload_count": len(anchor_payloads),
            "anchor_capture_summary": anchor_capture_summary,
            "start_lat": start_lat,
            "start_lon": start_lon,
        },
    )
    heading_payloads = load_jsonl_payloads(heading_evidence_jsonl_paths)
    if heading_payloads:
        _record_operator_event(
            operator_events,
            event_type="heading_evidence_loaded",
            message="Raw heading evidence loaded for DR baseline.",
            details={
                "heading_evidence_payload_count": len(heading_payloads),
                "heading_evidence_jsonl_paths": [str(path) for path in heading_evidence_jsonl_paths],
                "heading_degs": [_heading_deg_from_payload(payload) for payload in heading_payloads],
            },
        )
    wheel_encoder_gpio_capture_report: dict[str, Any] | None = None
    if wheel_encoder_gpio_capture:
        _record_operator_event(
            operator_events,
            event_type="wheel_encoder_gpio_capture_start",
            message=(
                "Move Scout now. Capturing GPIO wheel encoder evidence for "
                f"{wheel_encoder_capture_duration_seconds:g}s before re-anchor."
            ),
            details={
                "left_gpio": wheel_encoder_left_gpio,
                "right_gpio": wheel_encoder_right_gpio,
                "gpiochip": wheel_encoder_gpiochip,
                "duration_seconds": wheel_encoder_capture_duration_seconds,
                "sample_interval_seconds": wheel_encoder_sample_interval_seconds,
                "poll_interval_ms": wheel_encoder_poll_interval_ms,
                "active_low": wheel_encoder_active_low,
                "meters_per_tick": wheel_meters_per_tick,
            },
        )
        wheel_records = capture_wheel_encoder_records(
            left_gpio=wheel_encoder_left_gpio,
            right_gpio=wheel_encoder_right_gpio,
            meters_per_tick=float(wheel_meters_per_tick),
            duration_seconds=wheel_encoder_capture_duration_seconds,
            sample_interval_seconds=wheel_encoder_sample_interval_seconds,
            poll_interval_ms=wheel_encoder_poll_interval_ms,
            active_low=wheel_encoder_active_low,
            gpiochip=wheel_encoder_gpiochip,
            provider=wheel_provider,
        )
        write_wheel_encoder_jsonl(wheel_records, wheel_encoder_capture_jsonl)
        wheel_odometry_jsonl_paths = [*wheel_odometry_jsonl_paths, wheel_encoder_capture_jsonl]
        wheel_encoder_gpio_capture_report = _wheel_encoder_gpio_capture_report(
            output_jsonl=wheel_encoder_capture_jsonl,
            records=wheel_records,
        )
        _record_operator_event(
            operator_events,
            event_type="wheel_encoder_gpio_capture_complete",
            message="GPIO wheel encoder capture complete. Building DR delta from captured wheel evidence.",
            details=wheel_encoder_gpio_capture_report,
        )
    dr_payloads, dr_evidence = _build_dr_payloads(
        distance_deltas_m=distance_deltas_m,
        heading_degs=heading_degs,
        timestamp_s_values=timestamp_s_values,
        source=source,
        provider=provider,
        wheel_odometry_jsonl_paths=wheel_odometry_jsonl_paths,
        wheel_source=wheel_source,
        wheel_provider=wheel_provider,
        wheel_meters_per_tick=wheel_meters_per_tick,
        wheel_max_delta_m=wheel_max_delta_m,
    )
    dr_distance_deltas_m = [
        float(payload["distance_delta_m"])
        for payload in dr_payloads
        if payload.get("distance_delta_m") is not None
    ]
    route_heading = _route_heading(
        route_heading_deg=route_heading_deg,
        heading_degs=[
            *(_heading_deg_from_payload(payload) for payload in heading_payloads),
            *(_heading_deg_from_payload(payload) for payload in dr_payloads),
        ],
    )
    total_route_distance_m = route_distance_m if route_distance_m is not None else sum(dr_distance_deltas_m)
    if total_route_distance_m <= 0:
        raise ValueError("route_distance_m must be positive")
    if movement_window_seconds < 0:
        raise ValueError("movement_window_seconds must be non-negative")

    route_report = build_diagnostic_route_scaffold(
        output_dir=output_dir,
        mission_id=mission_id,
        start_lat=start_lat,
        start_lon=start_lon,
        heading_deg=route_heading,
        distance_m=total_route_distance_m,
        point_count=point_count,
        corridor_half_width_m=corridor_half_width_m,
    )

    _write_json(route_report, route_scaffold_report_json, pretty=pretty)
    _write_jsonl(anchor_payloads, anchor_jsonl)
    _record_operator_event(
        operator_events,
        event_type="route_scaffold_created",
        message="Diagnostic route, mission graph, and corridor were created from the anchor position.",
        details={
            "route_gpx": route_report["route_gpx"],
            "mission_graph_json": route_report["mission_graph_json"],
            "map_context_geojson": route_report["map_context_geojson"],
            "distance_m": total_route_distance_m,
            "heading_deg": route_heading,
        },
    )

    _write_jsonl(dr_payloads, dr_jsonl)
    _record_operator_event(
        operator_events,
        event_type="dr_delta_recorded",
        message="DR distance delta evidence was recorded. Move the requested distance before re-anchor capture.",
        details={
            "dr_delta_count": len(dr_payloads),
            "distance_deltas_m": dr_distance_deltas_m,
            "dr_evidence_mode": dr_evidence["mode"],
            "wheel_odometry_jsonl_paths": dr_evidence["wheel_odometry_jsonl_paths"],
        },
    )

    if wheel_encoder_gpio_capture:
        _record_operator_event(
            operator_events,
            event_type="movement_window_consumed_by_wheel_encoder_capture",
            message="Movement was captured by the live GPIO wheel encoder window; re-anchor starts next.",
            details={
                "movement_window_seconds": movement_window_seconds,
                "wheel_encoder_capture_duration_seconds": wheel_encoder_capture_duration_seconds,
            },
        )
    elif movement_window_seconds > 0:
        _record_operator_event(
            operator_events,
            event_type="movement_window_start",
            message=(
                "Movement window started. Move now, then stop before re-anchor capture in "
                f"{movement_window_seconds:g}s."
            ),
            details={"movement_window_seconds": movement_window_seconds},
        )
        time.sleep(movement_window_seconds)
        _record_operator_event(
            operator_events,
            event_type="movement_window_complete",
            message="Movement window complete. Stop and hold position for GNSS re-anchor capture.",
            details={"movement_window_seconds": movement_window_seconds},
        )
    else:
        _record_operator_event(
            operator_events,
            event_type="movement_window_skipped",
            message="No movement window configured; re-anchor capture starts immediately.",
            details={"movement_window_seconds": movement_window_seconds},
        )

    _record_operator_event(
        operator_events,
        event_type="reanchor_capture_start",
        message=f"Capturing GNSS re-anchor for {reanchor_duration_seconds:g}s.",
        details={
            "gnss_port": resolved_gnss_port,
            "duration_seconds": reanchor_duration_seconds,
            "reanchor_wait_timeout_seconds": reanchor_wait_timeout_seconds,
            "reanchor_retry_interval_seconds": reanchor_retry_interval_seconds,
        },
    )
    reanchor_payloads, reanchor_capture_summary = _capture_anchor_payloads(
        raw_nmea=raw_reanchor_nmea,
        port=resolved_gnss_port,
        baud=gnss_baud,
        duration_seconds=reanchor_duration_seconds,
        wait_timeout_seconds=reanchor_wait_timeout_seconds,
        retry_interval_seconds=reanchor_retry_interval_seconds,
        operator_events=operator_events,
        capture_label="Re-anchor",
        attempt_event_type="reanchor_capture_attempt",
    )
    _write_jsonl(reanchor_payloads, reanchor_jsonl)
    _record_operator_event(
        operator_events,
        event_type="reanchor_capture_complete",
        message="GNSS re-anchor capture complete. Running INS/DR completion gate.",
        details={
            "reanchor_payload_count": len(reanchor_payloads),
            "reanchor_capture_summary": reanchor_capture_summary,
        },
    )

    completion_report = run_field_completion_gate(
        mission_graph_path=Path(route_report["mission_graph_json"]),
        payloads=anchor_payloads + heading_payloads + dr_payloads + reanchor_payloads,
        input_jsonl_paths=[
            anchor_jsonl,
            *heading_evidence_jsonl_paths,
            *wheel_odometry_jsonl_paths,
            dr_jsonl,
            reanchor_jsonl,
        ],
        raw_nmea=None,
        runtime_updates_path=runtime_updates_jsonl,
        field_report_path=field_report_json,
        proof_manifest_path=proof_manifest_json,
        verification_report_path=verification_report_json,
        require_reanchor=require_reanchor,
        min_dr_progress_m=min_dr_progress_m,
        device="scout_pi",
        source="live_field_proof_evidence",
        pretty=pretty,
    )
    _record_operator_event(
        operator_events,
        event_type="completion_gate_complete",
        message=f"Completion gate finished with status {completion_report['scout_ins_dr_navigation_status']}.",
        details={
            "completion_ready": completion_report["completion_ready"],
            "field_proof_status": completion_report["field_proof_status"],
            "proof_manifest_status": completion_report["proof_manifest_status"],
        },
    )
    _write_jsonl(operator_events, operator_events_jsonl)

    report = {
        "source": "ins_dr_live_field_proof",
        "artifact_kind": "ins_dr_live_field_proof_report",
        "scout_ins_dr_navigation_status": completion_report["scout_ins_dr_navigation_status"],
        "completion_ready": completion_report["completion_ready"],
        "field_proof_status": completion_report["field_proof_status"],
        "proof_manifest_status": completion_report["proof_manifest_status"],
        "mission_id": mission_id,
        "output_dir": str(output_dir),
        "field_run_dir": str(field_run_dir),
        "requested_gnss_port": gnss_port,
        "gnss_port": resolved_gnss_port,
        "gnss_baud": gnss_baud,
        "serial_resolution": serial_evidence,
        "anchor_payload_count": len(anchor_payloads),
        "anchor_capture_summary": anchor_capture_summary,
        "anchor_wait_timeout_seconds": anchor_wait_timeout_seconds,
        "anchor_retry_interval_seconds": anchor_retry_interval_seconds,
        "heading_evidence_payload_count": len(heading_payloads),
        "heading_evidence_jsonl_paths": [str(path) for path in heading_evidence_jsonl_paths],
        "dr_delta_count": len(dr_payloads),
        "reanchor_payload_count": len(reanchor_payloads),
        "reanchor_capture_summary": reanchor_capture_summary,
        "reanchor_wait_timeout_seconds": reanchor_wait_timeout_seconds,
        "reanchor_retry_interval_seconds": reanchor_retry_interval_seconds,
        "dr_evidence_mode": dr_evidence["mode"],
        "wheel_odometry_jsonl_paths": dr_evidence["wheel_odometry_jsonl_paths"],
        "wheel_odometry_record_count": dr_evidence["wheel_odometry_record_count"],
        "wheel_encoder_gpio_capture_requested": wheel_encoder_gpio_capture,
        "wheel_encoder_gpio_capture_report": wheel_encoder_gpio_capture_report,
        "movement_window_seconds": movement_window_seconds,
        "route_scaffold_report_json": str(route_scaffold_report_json),
        "live_field_proof_report_json": str(live_report_json),
        "operator_events_jsonl": str(operator_events_jsonl),
        "operator_event_count": len(operator_events),
        "operator_events": operator_events,
        "route_gpx": route_report["route_gpx"],
        "mission_graph_json": route_report["mission_graph_json"],
        "map_context_geojson": route_report["map_context_geojson"],
        "anchor_jsonl": str(anchor_jsonl),
        "dr_jsonl": str(dr_jsonl),
        "reanchor_jsonl": str(reanchor_jsonl),
        "runtime_updates_jsonl": str(runtime_updates_jsonl),
        "field_report_json": str(field_report_json),
        "proof_manifest_json": str(proof_manifest_json),
        "verification_report_json": str(verification_report_json),
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_live_field_proof_only",
        "route_scaffold": route_report,
        "completion_report": completion_report,
    }
    _write_json(report, live_report_json, pretty=pretty)
    return report


def _write_anchor_failure_report(
    *,
    output_dir: Path,
    field_run_dir: Path,
    mission_id: str,
    requested_gnss_port: str,
    resolved_gnss_port: str,
    gnss_baud: int,
    serial_evidence: dict[str, Any],
    anchor_payloads: list[dict[str, Any]],
    anchor_capture_summary: dict[str, Any],
    operator_events: list[dict[str, Any]],
    anchor_jsonl: Path,
    live_report_json: Path,
    operator_events_jsonl: Path,
    route_scaffold_report_json: Path,
    dr_jsonl: Path,
    reanchor_jsonl: Path,
    runtime_updates_jsonl: Path,
    field_report_json: Path,
    proof_manifest_json: Path,
    verification_report_json: Path,
    failure_reason: str,
    anchor_failure_diagnosis: dict[str, Any],
    pretty: bool,
) -> dict[str, Any]:
    _write_jsonl(anchor_payloads, anchor_jsonl)
    _write_jsonl(operator_events, operator_events_jsonl)
    report = {
        "source": "ins_dr_live_field_proof",
        "artifact_kind": "ins_dr_live_field_proof_report",
        "scout_ins_dr_navigation_status": "not_field_ready",
        "completion_ready": False,
        "field_proof_status": "failed",
        "proof_manifest_status": "not_created",
        "mission_id": mission_id,
        "output_dir": str(output_dir),
        "field_run_dir": str(field_run_dir),
        "requested_gnss_port": requested_gnss_port,
        "gnss_port": resolved_gnss_port,
        "gnss_baud": gnss_baud,
        "serial_resolution": serial_evidence,
        "failure_stage": "anchor_capture",
        "failure_reason": failure_reason,
        "anchor_failure_diagnosis": anchor_failure_diagnosis,
        "anchor_payload_count": len(anchor_payloads),
        "anchor_capture_summary": anchor_capture_summary,
        "dr_delta_count": 0,
        "reanchor_payload_count": 0,
        "anchor_gnss_signal_summary": summarize_gnss_signal(anchor_payloads),
        "route_scaffold_report_json": str(route_scaffold_report_json),
        "live_field_proof_report_json": str(live_report_json),
        "operator_events_jsonl": str(operator_events_jsonl),
        "operator_event_count": len(operator_events),
        "operator_events": operator_events,
        "route_gpx": None,
        "mission_graph_json": None,
        "map_context_geojson": None,
        "anchor_jsonl": str(anchor_jsonl),
        "dr_jsonl": str(dr_jsonl),
        "reanchor_jsonl": str(reanchor_jsonl),
        "runtime_updates_jsonl": str(runtime_updates_jsonl),
        "field_report_json": str(field_report_json),
        "proof_manifest_json": str(proof_manifest_json),
        "verification_report_json": str(verification_report_json),
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_live_field_proof_only",
        "completion_report": None,
    }
    _write_json(report, live_report_json, pretty=pretty)
    return report


def _build_dr_payloads(
    *,
    distance_deltas_m: list[float],
    heading_degs: list[float | None],
    timestamp_s_values: list[float | None],
    source: str,
    provider: str,
    wheel_odometry_jsonl_paths: list[Path],
    wheel_source: str,
    wheel_provider: str,
    wheel_meters_per_tick: float | None,
    wheel_max_delta_m: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if wheel_odometry_jsonl_paths:
        records = load_wheel_odometry_jsonl(wheel_odometry_jsonl_paths)
        payloads = build_wheel_odometry_delta_payloads(
            records,
            source=wheel_source,
            provider=wheel_provider,
            meters_per_tick=wheel_meters_per_tick,
            max_delta_m=wheel_max_delta_m,
        )
        if not payloads:
            raise ValueError("wheel_odometry_jsonl_paths did not produce any positive DR delta")
        return payloads, {
            "mode": "wheel_odometry_jsonl",
            "wheel_odometry_jsonl_paths": [str(path) for path in wheel_odometry_jsonl_paths],
            "wheel_odometry_record_count": len(records),
        }

    payloads = [
        build_dr_delta_payload(
            distance_delta_m=distance_delta_m,
            heading_deg=heading_deg,
            timestamp_s=timestamp_s,
            source=source,
            provider=provider,
        )
        for distance_delta_m, heading_deg, timestamp_s in zip(distance_deltas_m, heading_degs, timestamp_s_values)
    ]
    return payloads, {
        "mode": "manual_distance_delta",
        "wheel_odometry_jsonl_paths": [],
        "wheel_odometry_record_count": 0,
    }


def _wheel_encoder_gpio_capture_report(*, output_jsonl: Path, records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "source": "ins_dr_live_field_proof",
        "artifact_kind": "wheel_encoder_gpio_capture_report",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "output_jsonl": str(output_jsonl),
        "record_count": len(records),
        "usable_record_count": sum(
            1 for record in records if record.get("dry_run") is not True and isinstance(record.get("odometry"), dict)
        ),
        "final_left_ticks": records[-1].get("wheel", {}).get("left_ticks") if records else None,
        "final_right_ticks": records[-1].get("wheel", {}).get("right_ticks") if records else None,
        "final_cumulative_distance_m": records[-1].get("odometry", {}).get("cumulative_distance_m")
        if records
        else None,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "primary_truth_allowed": False,
        "hardware_control_scope": "diagnostic_gpio_wheel_encoder_capture_only",
    }


def _resolve_capture_port(
    *,
    gnss_port: str,
    readiness_report_json_path: Path | None,
    raw_anchor_nmea: str | None,
    raw_reanchor_nmea: str | None,
) -> tuple[str, dict[str, Any]]:
    if readiness_report_json_path is not None and not (raw_anchor_nmea is not None and raw_reanchor_nmea is not None):
        return _resolve_capture_port_from_readiness(
            gnss_port=gnss_port,
            readiness_report_json_path=readiness_report_json_path,
        )
    if gnss_port != GNSS_SERIAL_AUTO_VALUE:
        return gnss_port, {
            "requested_gnss_port": gnss_port,
            "resolved_gnss_port": gnss_port,
            "auto_detection_status": "explicit_port",
            "raw_nmea_rehearsal": raw_anchor_nmea is not None or raw_reanchor_nmea is not None,
        }
    if raw_anchor_nmea is not None and raw_reanchor_nmea is not None:
        return GNSS_SERIAL_AUTO_VALUE, {
            "requested_gnss_port": gnss_port,
            "resolved_gnss_port": None,
            "auto_detection_status": "raw_nmea_rehearsal_no_serial_required",
            "raw_nmea_rehearsal": True,
        }
    resolved_port, evidence = resolve_requested_gnss_port(Path(gnss_port))
    if not resolved_port.exists() or evidence["auto_detection_status"] == "ambiguous_serial_candidates":
        raise ValueError(f"unable to resolve --gnss-port auto: {json.dumps(evidence, sort_keys=True)}")
    return str(resolved_port), evidence


def _resolve_capture_port_from_readiness(
    *,
    gnss_port: str,
    readiness_report_json_path: Path,
) -> tuple[str, dict[str, Any]]:
    report = json.loads(readiness_report_json_path.read_text(encoding="utf-8"))
    selected_port = report.get("selected_gnss_port")
    ready = report.get("ready_for_live_field_proof") is True or report.get("ready") is True
    if not ready:
        raise ValueError(f"readiness report is not ready: {readiness_report_json_path}")
    if not isinstance(selected_port, str) or not selected_port:
        raise ValueError(f"readiness report has no selected_gnss_port: {readiness_report_json_path}")
    if gnss_port != GNSS_SERIAL_AUTO_VALUE and gnss_port != selected_port:
        raise ValueError(
            f"--gnss-port {gnss_port} does not match readiness selected_gnss_port {selected_port}"
        )
    selected_path = Path(selected_port)
    if not selected_path.exists():
        raise ValueError(f"readiness selected_gnss_port does not exist: {selected_port}")
    return selected_port, {
        "requested_gnss_port": gnss_port,
        "resolved_gnss_port": selected_port,
        "auto_detection_status": "selected_from_readiness_report",
        "readiness_report_json": str(readiness_report_json_path),
        "readiness_status": report.get("field_run_readiness_status"),
        "readiness_selected_gnss_port": selected_port,
        "readiness_auto_selection_status": (
            report.get("gnss_auto_selection_summary") or {}
        ).get("selection_status"),
        "raw_nmea_rehearsal": False,
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


def _capture_anchor_payloads(
    *,
    raw_nmea: str | None,
    port: str,
    baud: int,
    duration_seconds: float,
    wait_timeout_seconds: float | None,
    retry_interval_seconds: float,
    operator_events: list[dict[str, Any]],
    capture_label: str,
    attempt_event_type: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if raw_nmea is not None or wait_timeout_seconds is None:
        payloads = _capture_gnss_payloads(
            raw_nmea=raw_nmea,
            port=port,
            baud=baud,
            duration_seconds=duration_seconds,
        )
        return payloads, {
            "mode": "single_capture",
            "attempt_count": 1,
            "wait_timeout_seconds": wait_timeout_seconds,
            "retry_interval_seconds": retry_interval_seconds,
            "valid_fix_observed": _valid_gnss_position_count(payloads) > 0,
            "payload_count": len(payloads),
            "signal": summarize_gnss_signal(payloads),
        }

    deadline = time.monotonic() + wait_timeout_seconds
    payloads: list[dict[str, Any]] = []
    attempt_count = 0
    while True:
        now = time.monotonic()
        if attempt_count > 0 and now >= deadline:
            break
        remaining = max(0.0, deadline - now)
        capture_duration = min(duration_seconds, remaining) if wait_timeout_seconds > 0 else duration_seconds
        if capture_duration <= 0 and attempt_count == 0:
            capture_duration = duration_seconds
        if capture_duration <= 0:
            break

        attempt_count += 1
        attempt_payloads = _capture_gnss_payloads(
            raw_nmea=None,
            port=port,
            baud=baud,
            duration_seconds=capture_duration,
        )
        payloads.extend(attempt_payloads)
        attempt_summary = summarize_gnss_signal(attempt_payloads)
        valid_fix_observed = _valid_gnss_position_count(payloads) > 0
        _record_operator_event(
            operator_events,
            event_type=attempt_event_type,
            message=(
                f"{capture_label} capture attempt {attempt_count} collected {len(attempt_payloads)} payloads; "
                f"valid_fix_observed={valid_fix_observed}."
            ),
            details={
                "attempt": attempt_count,
                "duration_seconds": capture_duration,
                "payload_count": len(attempt_payloads),
                "cumulative_payload_count": len(payloads),
                "valid_fix_observed": valid_fix_observed,
                "gnss_signal_summary": attempt_summary,
            },
        )
        if valid_fix_observed:
            break

        if time.monotonic() >= deadline:
            break
        if retry_interval_seconds > 0:
            time.sleep(min(retry_interval_seconds, max(0.0, deadline - time.monotonic())))

    return payloads, {
        "mode": "wait_until_valid_fix",
        "attempt_count": attempt_count,
        "wait_timeout_seconds": wait_timeout_seconds,
        "retry_interval_seconds": retry_interval_seconds,
        "valid_fix_observed": _valid_gnss_position_count(payloads) > 0,
        "payload_count": len(payloads),
        "signal": summarize_gnss_signal(payloads),
    }


def _first_valid_gnss_position(payloads: list[dict[str, Any]]) -> tuple[float, float]:
    for payload in payloads:
        position = payload.get("position") if isinstance(payload.get("position"), dict) else {}
        fix_quality = payload.get("fix_quality") if isinstance(payload.get("fix_quality"), dict) else {}
        if payload.get("checksum_valid") is False:
            continue
        lat = _float_or_none(position.get("lat"))
        lon = _float_or_none(position.get("lon"))
        if lat is not None and lon is not None and fix_quality.get("valid") is not False:
            return lat, lon
    raise ValueError("anchor capture did not include a valid GNSS position")


def _anchor_failure_diagnosis(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    signal = summarize_gnss_signal(payloads)
    valid_fix_count = _valid_gnss_position_count(payloads)
    any_rf_signal = int(signal.get("nonzero_cno_count") or 0) > 0
    gps_rf_signal = int(signal.get("gps_nonzero_cno_count") or 0) > 0
    if valid_fix_count > 0:
        state = "valid_fix_present"
        action = "Retry live proof; anchor parsing should have accepted at least one valid position."
    elif not payloads:
        state = "no_nmea_payloads"
        action = "Check serial path, baud rate, GPS power, and USB/UART cabling before field proof."
    elif any_rf_signal:
        state = "rf_signal_without_valid_fix"
        action = "Keep the antenna under open sky or improve placement until GGA/RMC reports a valid fix; do not start DR movement yet."
    elif int(signal.get("gsv_sentence_count") or 0) > 0:
        state = "no_rf_signal_observed"
        action = "NMEA is alive but C/N0 is still absent; inspect antenna, RF path, bias, shielding, and placement."
    else:
        state = "nmea_without_gsv_or_fix"
        action = "NMEA is alive but lacks fix and GSV signal evidence; check receiver message configuration and continue GNSS diagnostics."
    return {
        "state": state,
        "valid_fix_count": valid_fix_count,
        "any_rf_signal_observed": any_rf_signal,
        "gps_rf_signal_observed": gps_rf_signal,
        "max_cno_dbhz": signal.get("max_cno_dbhz"),
        "gps_max_cno_dbhz": signal.get("gps_max_cno_dbhz"),
        "next_operator_action": action,
    }


def _valid_gnss_position_count(payloads: list[dict[str, Any]]) -> int:
    count = 0
    for payload in payloads:
        position = payload.get("position") if isinstance(payload.get("position"), dict) else {}
        fix_quality = payload.get("fix_quality") if isinstance(payload.get("fix_quality"), dict) else {}
        if payload.get("checksum_valid") is False:
            continue
        if _float_or_none(position.get("lat")) is None or _float_or_none(position.get("lon")) is None:
            continue
        if fix_quality.get("valid") is False:
            continue
        count += 1
    return count


def _route_heading(*, route_heading_deg: float | None, heading_degs: list[float | None]) -> float:
    if route_heading_deg is not None:
        if not 0.0 <= route_heading_deg < 360.0:
            raise ValueError("route_heading_deg must be in [0, 360)")
        return route_heading_deg
    for heading_deg in heading_degs:
        if heading_deg is not None:
            if not 0.0 <= heading_deg < 360.0:
                raise ValueError("heading_deg must be in [0, 360)")
            return heading_deg
    raise ValueError("provide --route-heading-deg, --heading-evidence-jsonl, or at least one --heading-deg")


def _heading_deg_from_payload(payload: dict[str, Any]) -> float | None:
    for key in ("heading_deg", "motionHeading", "locationCourse", "locationTrueHeading", "locationMagneticHeading"):
        heading = _float_or_none(payload.get(key))
        if heading is not None and heading >= 0:
            return heading % 360.0

    for section_key in ("odometry", "dr", "raw", "raw_payload"):
        section = payload.get(section_key)
        if isinstance(section, dict):
            heading = _heading_deg_from_payload(section)
            if heading is not None:
                return heading

    parsed = payload.get("parsed") if isinstance(payload.get("parsed"), dict) else {}
    angle = parsed.get("angle_deg")
    if isinstance(angle, (list, tuple)) and len(angle) >= 3:
        if _requires_raw_imu_checksum(payload) and _payload_checksum_valid(payload, parsed) is not True:
            return None
        yaw = _float_or_none(angle[2])
        if yaw is not None:
            return yaw % 360.0
    return None


def _requires_raw_imu_checksum(payload: dict[str, Any]) -> bool:
    source = str(payload.get("source") or "").lower()
    hardware_kind = str(payload.get("hardware_kind") or "").lower()
    frame_type = str(payload.get("frame_type") or "").lower()
    return (
        "hiwonder" in source
        or "wit" in source
        or "hiwonder" in hardware_kind
        or "wit" in hardware_kind
        or frame_type in {"acceleration", "gyro", "angle"}
        or payload.get("raw_imu_present") is True
    )


def _payload_checksum_valid(payload: dict[str, Any], parsed: dict[str, Any]) -> bool | None:
    if "checksum_valid" in payload:
        return payload.get("checksum_valid") is True
    if "checksum_valid" in parsed:
        return parsed.get("checksum_valid") is True
    return None


def _output_conflicts(*, output_dir: Path, field_run_dir: Path, mission_id: str) -> list[str]:
    route_stem = f"{mission_id}_route"
    candidates = [
        output_dir / ROUTE_SCAFFOLD_REPORT_NAME,
        output_dir / LIVE_FIELD_PROOF_REPORT_NAME,
        output_dir / OPERATOR_EVENTS_NAME,
        field_run_dir / "wheel-encoder-gpio-capture.jsonl",
        output_dir / "routes" / f"{route_stem}.gpx",
        output_dir / "mission_graph" / f"{mission_id}_mission.json",
        output_dir / "maps" / f"{route_stem}_map_context.geojson",
    ]
    candidates.extend(field_run_dir / name for name in FIELD_RUN_ARTIFACT_NAMES)
    return sorted(str(path) for path in candidates if path.exists())


def _write_jsonl(payloads: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "".join(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n" for payload in payloads),
        encoding="utf-8",
    )


def _write_json(payload: dict[str, Any], output_path: Path, *, pretty: bool) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2 if pretty else None, sort_keys=not pretty) + "\n",
        encoding="utf-8",
    )


def _record_operator_event(
    events: list[dict[str, Any]],
    *,
    event_type: str,
    message: str,
    details: dict[str, Any],
) -> None:
    event = {
        "source": "ins_dr_live_field_proof",
        "artifact_kind": "ins_dr_live_field_proof_operator_event",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "message": message,
        "details": details,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_live_field_proof_operator_guidance_only",
    }
    events.append(event)
    print(f"[ins-dr-live] {message}", file=sys.stderr)


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
        description="Capture a one-command diagnostic Scout INS/DR field proof: live anchor, route scaffold, DR delta, re-anchor, completion gate."
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--mission-id", default=f"ins_dr_live_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}")
    parser.add_argument("--gnss-port", default=GNSS_SERIAL_AUTO_VALUE)
    parser.add_argument("--gnss-baud", type=int, default=9600)
    parser.add_argument("--anchor-duration-seconds", type=float, default=10.0)
    parser.add_argument("--reanchor-duration-seconds", type=float, default=10.0)
    parser.add_argument("--distance-delta-m", type=float, action="append")
    parser.add_argument("--heading-deg", type=float, action="append")
    parser.add_argument("--timestamp-s", type=float, action="append")
    parser.add_argument(
        "--wheel-odometry-jsonl",
        type=Path,
        action="append",
        help="Raw wheel/encoder odometry JSONL. Use instead of --distance-delta-m for field-ready DR evidence.",
    )
    parser.add_argument("--wheel-source", default="wheel_odometry")
    parser.add_argument("--wheel-provider", default="scout_wheel_encoder")
    parser.add_argument("--wheel-meters-per-tick", type=float)
    parser.add_argument("--wheel-max-delta-m", type=float, default=25.0)
    parser.add_argument(
        "--wheel-encoder-gpio-capture",
        action="store_true",
        help="After the anchor fix, capture two GPIO wheel encoder inputs as the DR movement source.",
    )
    parser.add_argument("--wheel-encoder-left-gpio", type=int, default=20)
    parser.add_argument("--wheel-encoder-right-gpio", type=int, default=21)
    parser.add_argument("--wheel-encoder-capture-duration-seconds", type=float, default=10.0)
    parser.add_argument("--wheel-encoder-sample-interval-seconds", type=float, default=1.0)
    parser.add_argument("--wheel-encoder-poll-interval-ms", type=float, default=5.0)
    parser.add_argument("--wheel-encoder-active-low", action="store_true")
    parser.add_argument("--wheel-encoder-gpiochip", default="gpiochip0")
    parser.add_argument("--route-heading-deg", type=float)
    parser.add_argument("--route-distance-m", type=float)
    parser.add_argument("--corridor-half-width-m", type=float, default=6.0)
    parser.add_argument("--point-count", type=int, default=5)
    parser.add_argument(
        "--movement-window-seconds",
        type=float,
        default=0.0,
        help="Seconds to wait after anchor capture and DR delta writing so the operator can move before re-anchor.",
    )
    parser.add_argument(
        "--anchor-wait-timeout-seconds",
        type=float,
        help="For live serial capture, keep retrying anchor capture until a valid GNSS fix appears or this timeout expires.",
    )
    parser.add_argument(
        "--anchor-retry-interval-seconds",
        type=float,
        default=0.0,
        help="Seconds to wait between live anchor capture attempts when --anchor-wait-timeout-seconds is set.",
    )
    parser.add_argument(
        "--reanchor-wait-timeout-seconds",
        type=float,
        help="For live serial capture, keep retrying re-anchor capture until a valid GNSS fix appears or this timeout expires.",
    )
    parser.add_argument(
        "--reanchor-retry-interval-seconds",
        type=float,
        default=0.0,
        help="Seconds to wait between live re-anchor capture attempts when --reanchor-wait-timeout-seconds is set.",
    )
    parser.add_argument("--source", default="manual_odometry_delta")
    parser.add_argument("--provider", default="operator_entered_distance_delta")
    parser.add_argument(
        "--heading-evidence-jsonl",
        type=Path,
        action="append",
        help="Raw IMU/heading JSONL, such as pi_hiwonder_imu_usb_smoke angle frames, to feed before DR deltas.",
    )
    parser.add_argument("--raw-anchor-nmea", help="Fixture/debug NMEA text for anchor capture rehearsal.")
    parser.add_argument("--raw-reanchor-nmea", help="Fixture/debug NMEA text for re-anchor capture rehearsal.")
    parser.add_argument(
        "--readiness-report-json",
        type=Path,
        help="Use selected_gnss_port from a ready ins_dr_field_readiness_check report.",
    )
    parser.add_argument("--no-require-reanchor", action="store_true")
    parser.add_argument("--min-dr-progress-m", type=float, default=1.0)
    parser.add_argument("--allow-overwrite", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    try:
        distance_deltas_m = args.distance_delta_m or []
        if distance_deltas_m:
            heading_degs = _expand_optional_values(args.heading_deg, len(distance_deltas_m), name="--heading-deg")
            timestamp_s_values = _expand_optional_values(args.timestamp_s, len(distance_deltas_m), name="--timestamp-s")
        else:
            if args.heading_deg:
                raise ValueError("--heading-deg is only valid with --distance-delta-m; use wheel heading or --route-heading-deg")
            if args.timestamp_s:
                raise ValueError("--timestamp-s is only valid with --distance-delta-m")
            heading_degs = []
            timestamp_s_values = []
        if distance_deltas_m and args.timestamp_s is None:
            now = time.time()
            timestamp_s_values = [now + index for index in range(len(distance_deltas_m))]
        report = run_live_field_proof(
            output_dir=args.output_dir,
            mission_id=args.mission_id,
            gnss_port=args.gnss_port,
            gnss_baud=args.gnss_baud,
            anchor_duration_seconds=args.anchor_duration_seconds,
            reanchor_duration_seconds=args.reanchor_duration_seconds,
            distance_deltas_m=distance_deltas_m,
            heading_degs=heading_degs,
            timestamp_s_values=timestamp_s_values,
            route_heading_deg=args.route_heading_deg,
            route_distance_m=args.route_distance_m,
            corridor_half_width_m=args.corridor_half_width_m,
            point_count=args.point_count,
            movement_window_seconds=args.movement_window_seconds,
            anchor_wait_timeout_seconds=args.anchor_wait_timeout_seconds,
            anchor_retry_interval_seconds=args.anchor_retry_interval_seconds,
            reanchor_wait_timeout_seconds=args.reanchor_wait_timeout_seconds,
            reanchor_retry_interval_seconds=args.reanchor_retry_interval_seconds,
            raw_anchor_nmea=args.raw_anchor_nmea,
            raw_reanchor_nmea=args.raw_reanchor_nmea,
            readiness_report_json_path=args.readiness_report_json,
            source=args.source,
            provider=args.provider,
            heading_evidence_jsonl_paths=args.heading_evidence_jsonl,
            wheel_odometry_jsonl_paths=args.wheel_odometry_jsonl,
            wheel_encoder_gpio_capture=args.wheel_encoder_gpio_capture,
            wheel_encoder_left_gpio=args.wheel_encoder_left_gpio,
            wheel_encoder_right_gpio=args.wheel_encoder_right_gpio,
            wheel_encoder_capture_duration_seconds=args.wheel_encoder_capture_duration_seconds,
            wheel_encoder_sample_interval_seconds=args.wheel_encoder_sample_interval_seconds,
            wheel_encoder_poll_interval_ms=args.wheel_encoder_poll_interval_ms,
            wheel_encoder_active_low=args.wheel_encoder_active_low,
            wheel_encoder_gpiochip=args.wheel_encoder_gpiochip,
            wheel_source=args.wheel_source,
            wheel_provider=args.wheel_provider,
            wheel_meters_per_tick=args.wheel_meters_per_tick,
            wheel_max_delta_m=args.wheel_max_delta_m,
            require_reanchor=not args.no_require_reanchor,
            min_dr_progress_m=args.min_dr_progress_m,
            allow_overwrite=args.allow_overwrite,
            pretty=args.pretty,
        )
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=not args.pretty))
    return 0 if report["completion_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
