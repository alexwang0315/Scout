from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.ins_dr_field_readiness_check import build_field_readiness_report  # noqa: E402
from tools.ins_dr_gnss_fix_watch import STOP_ON_VALUES, run_gnss_fix_watch  # noqa: E402
from tools.ins_dr_live_field_proof import run_live_field_proof  # noqa: E402
from tools.pi_gnss_diagnosis_report import build_diagnosis, render_markdown  # noqa: E402
from tools.pi_gnss_hardware_snapshot import build_auto_gnss_targets, collect_snapshot  # noqa: E402
from tools.pi_gnss_physical_checklist import (  # noqa: E402
    build_template as build_gnss_physical_template,
    evaluate_measurements,
    render_template_markdown as render_gnss_physical_template_markdown,
)
from tools.pi_grove_imu_9dof_smoke import (  # noqa: E402
    AK09918_DEFAULT_ADDRESS,
    ICM20600_DEFAULT_ADDRESS,
    error_payload as grove_imu_error_payload,
    read_live_imu_payload as read_live_grove_imu_payload,
)
from tools.pi_hiwonder_imu_usb_smoke import build_imu_payload, read_serial_frames  # noqa: E402
from tools.pi_wheel_encoder_gpio_smoke import (  # noqa: E402
    capture_wheel_encoder_records,
    summarize_wheel_encoder_records,
    write_jsonl as write_wheel_encoder_jsonl,
)
from tools.pi_wheel_odometry_delta_smoke import (  # noqa: E402
    build_template_records as build_wheel_odometry_template_records,
    render_template_markdown as render_wheel_odometry_template_markdown,
    write_template_jsonl as write_wheel_odometry_template_jsonl,
)


def run_field_session(
    *,
    output_dir: Path,
    mission_graph_path: Path,
    gnss_baud: int = 115200,
    include_uart: bool = False,
    snapshot_ab_duration_seconds: float = 60.0,
    snapshot_probe_duration_seconds: float = 10.0,
    snapshot_poll_gap_seconds: float = 0.12,
    readiness_capture_duration_seconds: float = 60.0,
    readiness_auto_select_duration_seconds: float = 30.0,
    gnss_watch_before_readiness: bool = False,
    gnss_watch_window_seconds: float = 10.0,
    gnss_watch_max_wait_seconds: float = 300.0,
    gnss_watch_poll_interval_seconds: float = 2.0,
    gnss_watch_stop_on: str = "valid_fix",
    gnss_watch_min_gps_cno_dbhz: float = 25.0,
    gnss_watch_min_any_cno_dbhz: float = 20.0,
    gnss_watch_max_window_count: int | None = None,
    gnss_physical_measurements_json_path: Path | None = None,
    allow_overwrite: bool = False,
    run_live_proof: bool = False,
    live_mission_id: str | None = None,
    heading_evidence_jsonl_paths: list[Path] | None = None,
    imu_heading_capture_port: Path | None = None,
    imu_heading_baud: int = 9600,
    imu_heading_capture_duration_seconds: float | None = None,
    grove_imu_heading_capture: bool = False,
    grove_imu_bus: Path = Path("/dev/i2c-1"),
    grove_imu_address: int = ICM20600_DEFAULT_ADDRESS,
    grove_mag_address: int = AK09918_DEFAULT_ADDRESS,
    grove_imu_sample_count: int = 5,
    grove_imu_sample_interval_ms: float = 100.0,
    wheel_odometry_jsonl_paths: list[Path] | None = None,
    wheel_encoder_gpio_capture: bool = False,
    wheel_encoder_left_gpio: int = 20,
    wheel_encoder_right_gpio: int = 21,
    wheel_encoder_capture_duration_seconds: float = 5.0,
    wheel_encoder_sample_interval_seconds: float = 1.0,
    wheel_encoder_poll_interval_ms: float = 5.0,
    wheel_encoder_active_low: bool = False,
    wheel_encoder_gpiochip: str = "gpiochip0",
    live_wheel_encoder_gpio_capture: bool = False,
    wheel_source: str = "wheel_odometry",
    wheel_provider: str = "scout_wheel_encoder",
    wheel_meters_per_tick: float | None = None,
    wheel_max_delta_m: float = 25.0,
    movement_window_seconds: float = 0.0,
    anchor_duration_seconds: float = 10.0,
    anchor_wait_timeout_seconds: float | None = None,
    anchor_retry_interval_seconds: float = 0.0,
    reanchor_duration_seconds: float = 10.0,
    reanchor_wait_timeout_seconds: float | None = None,
    reanchor_retry_interval_seconds: float = 0.0,
    corridor_half_width_m: float = 6.0,
    pretty: bool = False,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    hardware_snapshot_json = output_dir / "gnss-hardware-snapshot.json"
    diagnosis_json = output_dir / "gnss-diagnosis-report.json"
    diagnosis_md = output_dir / "gnss-diagnosis-report.md"
    physical_report_json = output_dir / "gnss-physical-checklist-report.json"
    physical_template_json = output_dir / "gnss-physical-measurements-template.json"
    physical_template_md = output_dir / "gnss-physical-measurements-template.md"
    readiness_json = output_dir / "field-readiness-report.json"
    readiness_capture_jsonl = output_dir / "readiness-live-capture.jsonl"
    readiness_auto_select_dir = output_dir / "readiness-auto-select"
    gnss_watch_dir = output_dir / "gnss-fix-watch"
    imu_heading_capture_jsonl = output_dir / "imu-heading-capture.jsonl"
    imu_heading_capture_report_json = output_dir / "imu-heading-capture-report.json"
    grove_imu_heading_capture_jsonl = output_dir / "grove-imu-heading-capture.jsonl"
    wheel_encoder_capture_jsonl = output_dir / "wheel-encoder-gpio-capture.jsonl"
    wheel_odometry_template_jsonl = output_dir / "wheel-odometry-template.jsonl"
    wheel_odometry_template_md = output_dir / "wheel-odometry-template.md"
    live_output_dir = output_dir / "live-field-proof"
    next_action_json = output_dir / "field-session-next-action.json"
    next_action_md = output_dir / "field-session-next-action.md"
    field_session_report_json = output_dir / "field-session-report.json"
    conflicts = _session_artifact_conflicts(
        [
            hardware_snapshot_json,
            diagnosis_json,
            diagnosis_md,
            physical_report_json,
            physical_template_json,
            physical_template_md,
            imu_heading_capture_jsonl,
            imu_heading_capture_report_json,
            grove_imu_heading_capture_jsonl,
            wheel_encoder_capture_jsonl,
            wheel_odometry_template_jsonl,
            wheel_odometry_template_md,
            readiness_json,
            next_action_json,
            next_action_md,
            field_session_report_json,
        ]
    )
    if conflicts and not allow_overwrite:
        raise ValueError(f"output_dir already contains field session artifacts: {', '.join(conflicts)}")

    targets, auto_serial_candidates = build_auto_gnss_targets(
        bauds=[gnss_baud],
        include_uart=include_uart,
    )
    snapshot = collect_snapshot(
        targets=targets,
        ab_duration_seconds=snapshot_ab_duration_seconds,
        probe_duration_seconds=snapshot_probe_duration_seconds,
        poll_gap_seconds=snapshot_poll_gap_seconds,
    )
    snapshot["auto_serial_candidates"] = auto_serial_candidates
    snapshot["auto_serial_candidate_count"] = len(auto_serial_candidates)
    gnss_command_path_summary = _gnss_command_path_summary(snapshot)
    _write_json(snapshot, hardware_snapshot_json, pretty=pretty)

    physical_report = _load_physical_report(gnss_physical_measurements_json_path)
    if physical_report is not None:
        _write_json(physical_report, physical_report_json, pretty=pretty)

    diagnosis = build_diagnosis(snapshot=snapshot, physical=physical_report)
    _write_json(diagnosis, diagnosis_json, pretty=pretty)
    diagnosis_md.write_text(render_markdown(diagnosis), encoding="utf-8")

    gnss_watch_report: dict[str, Any] | None = None
    readiness_gnss_port = Path("auto")
    readiness_gnss_evidence_paths: list[Path] = []
    if gnss_watch_before_readiness:
        gnss_watch_report = run_gnss_fix_watch(
            output_dir=gnss_watch_dir,
            gnss_port=Path("auto"),
            gnss_baud=gnss_baud,
            window_seconds=gnss_watch_window_seconds,
            max_wait_seconds=gnss_watch_max_wait_seconds,
            poll_interval_seconds=gnss_watch_poll_interval_seconds,
            stop_on=gnss_watch_stop_on,
            min_gps_cno_dbhz=gnss_watch_min_gps_cno_dbhz,
            min_any_cno_dbhz=gnss_watch_min_any_cno_dbhz,
            include_uart=include_uart,
            max_window_count=gnss_watch_max_window_count,
            allow_overwrite=allow_overwrite,
            pretty=pretty,
        )
        watch_payloads_jsonl = gnss_watch_report.get("payloads_jsonl")
        if watch_payloads_jsonl:
            readiness_gnss_evidence_paths.append(Path(watch_payloads_jsonl))
        watch_selected_gnss_port = gnss_watch_report.get("selected_gnss_port")
        if watch_selected_gnss_port:
            readiness_gnss_port = Path(str(watch_selected_gnss_port))

    readiness = build_field_readiness_report(
        mission_graph_path=mission_graph_path,
        gnss_port=readiness_gnss_port,
        output_dir=output_dir / "readiness-field-run",
        allow_overwrite=allow_overwrite,
        gnss_evidence_jsonl_paths=readiness_gnss_evidence_paths,
        require_valid_gnss_fix=True,
        capture_gnss_duration_seconds=readiness_capture_duration_seconds,
        capture_gnss_evidence_jsonl_path=readiness_capture_jsonl,
        auto_select_gnss_by_fix_duration_seconds=readiness_auto_select_duration_seconds,
        auto_select_gnss_evidence_dir_path=readiness_auto_select_dir,
        gnss_hardware_snapshot_json_path=hardware_snapshot_json,
        gnss_baud=gnss_baud,
        include_uart_serial_candidates=include_uart,
    )
    _write_json(readiness, readiness_json, pretty=pretty)

    heading_evidence_paths = list(heading_evidence_jsonl_paths or [])
    imu_heading_capture_report: dict[str, Any] | None = None
    grove_imu_heading_capture_payload: dict[str, Any] | None = None
    if imu_heading_capture_duration_seconds is not None:
        imu_heading_capture_report = _capture_imu_heading_evidence(
            imu_heading_capture_port=imu_heading_capture_port or Path("auto"),
            auto_serial_candidates=auto_serial_candidates,
            baud=imu_heading_baud,
            duration_seconds=imu_heading_capture_duration_seconds,
            output_jsonl=imu_heading_capture_jsonl,
        )
        _write_json(imu_heading_capture_report, imu_heading_capture_report_json, pretty=pretty)
        heading_evidence_paths.append(imu_heading_capture_jsonl)
    if grove_imu_heading_capture:
        grove_imu_heading_capture_payload = _capture_grove_imu_heading_evidence(
            bus=grove_imu_bus,
            imu_address=grove_imu_address,
            mag_address=grove_mag_address,
            sample_count=grove_imu_sample_count,
            sample_interval_ms=grove_imu_sample_interval_ms,
            output_jsonl=grove_imu_heading_capture_jsonl,
        )
        heading_evidence_paths.append(grove_imu_heading_capture_jsonl)

    wheel_odometry_paths = list(wheel_odometry_jsonl_paths or [])
    wheel_encoder_gpio_capture_report: dict[str, Any] | None = None
    if wheel_encoder_gpio_capture:
        wheel_encoder_gpio_capture_report = _capture_wheel_encoder_gpio_evidence(
            left_gpio=wheel_encoder_left_gpio,
            right_gpio=wheel_encoder_right_gpio,
            meters_per_tick=wheel_meters_per_tick,
            duration_seconds=wheel_encoder_capture_duration_seconds,
            sample_interval_seconds=wheel_encoder_sample_interval_seconds,
            poll_interval_ms=wheel_encoder_poll_interval_ms,
            active_low=wheel_encoder_active_low,
            gpiochip=wheel_encoder_gpiochip,
            provider=wheel_provider,
            output_jsonl=wheel_encoder_capture_jsonl,
        )
        wheel_odometry_paths.append(wheel_encoder_capture_jsonl)

    heading_evidence_summary = _raw_imu_heading_evidence_summary(heading_evidence_paths)
    wheel_odometry_summary = _wheel_odometry_input_summary(wheel_odometry_paths)
    live_wheel_capture_config_ready = (
        live_wheel_encoder_gpio_capture
        and wheel_meters_per_tick is not None
        and wheel_meters_per_tick > 0
    )
    ins_dr_live_inputs_ready = (
        heading_evidence_summary["raw_imu_heading_ready"] is True
        and (wheel_odometry_summary["wheel_odometry_ready"] is True or live_wheel_capture_config_ready)
    )

    live_report: dict[str, Any] | None = None
    if run_live_proof and readiness.get("ready_for_live_field_proof") is True and ins_dr_live_inputs_ready:
        live_report = run_live_field_proof(
            output_dir=live_output_dir,
            mission_id=live_mission_id or "ins_dr_field_session_live",
            gnss_port="auto",
            gnss_baud=gnss_baud,
            anchor_duration_seconds=anchor_duration_seconds,
            reanchor_duration_seconds=reanchor_duration_seconds,
            readiness_report_json_path=readiness_json,
            heading_evidence_jsonl_paths=heading_evidence_paths,
            wheel_odometry_jsonl_paths=[] if live_wheel_encoder_gpio_capture else wheel_odometry_paths,
            wheel_encoder_gpio_capture=live_wheel_encoder_gpio_capture,
            wheel_encoder_left_gpio=wheel_encoder_left_gpio,
            wheel_encoder_right_gpio=wheel_encoder_right_gpio,
            wheel_encoder_capture_duration_seconds=wheel_encoder_capture_duration_seconds,
            wheel_encoder_sample_interval_seconds=wheel_encoder_sample_interval_seconds,
            wheel_encoder_poll_interval_ms=wheel_encoder_poll_interval_ms,
            wheel_encoder_active_low=wheel_encoder_active_low,
            wheel_encoder_gpiochip=wheel_encoder_gpiochip,
            wheel_source=wheel_source,
            wheel_provider=wheel_provider,
            wheel_meters_per_tick=wheel_meters_per_tick,
            wheel_max_delta_m=wheel_max_delta_m,
            movement_window_seconds=movement_window_seconds,
            anchor_wait_timeout_seconds=anchor_wait_timeout_seconds,
            anchor_retry_interval_seconds=anchor_retry_interval_seconds,
            reanchor_wait_timeout_seconds=reanchor_wait_timeout_seconds,
            reanchor_retry_interval_seconds=reanchor_retry_interval_seconds,
            corridor_half_width_m=corridor_half_width_m,
            allow_overwrite=allow_overwrite,
            pretty=pretty,
        )
        live_wheel_paths = [
            Path(path)
            for path in live_report.get("wheel_odometry_jsonl_paths", [])
            if isinstance(path, str) and path
        ]
        if live_wheel_paths:
            wheel_odometry_paths = [*wheel_odometry_paths, *live_wheel_paths]
            wheel_odometry_summary = _wheel_odometry_input_summary(wheel_odometry_paths)
            ins_dr_live_inputs_ready = (
                heading_evidence_summary["raw_imu_heading_ready"] is True
                and wheel_odometry_summary["wheel_odometry_ready"] is True
            )

    session_status = _session_status(
        readiness=readiness,
        live_report=live_report,
        run_live_proof=run_live_proof,
        gnss_watch_report=gnss_watch_report,
        ins_dr_live_inputs_ready=ins_dr_live_inputs_ready,
    )
    next_action = _build_next_action_summary(
        session_status=session_status,
        readiness=readiness,
        diagnosis=diagnosis,
        gnss_watch_report=gnss_watch_report,
        physical_report=physical_report,
        live_report=live_report,
        run_live_proof=run_live_proof,
        gnss_command_path_summary=gnss_command_path_summary,
        heading_evidence_summary=heading_evidence_summary,
        wheel_odometry_summary=wheel_odometry_summary,
        ins_dr_live_inputs_ready=ins_dr_live_inputs_ready,
    )
    physical_template_written = next_action["next_action_status"] == "collect_physical_measurements"
    if physical_template_written:
        template_payload = build_gnss_physical_template()
        _write_json(template_payload, physical_template_json, pretty=pretty)
        physical_template_md.write_text(render_gnss_physical_template_markdown(template_payload), encoding="utf-8")
        next_action["gnss_physical_measurements_template_json"] = str(physical_template_json)
        next_action["gnss_physical_measurements_template_md"] = str(physical_template_md)
    wheel_template_written = wheel_odometry_summary.get("wheel_odometry_ready") is not True
    if wheel_template_written:
        wheel_template_records = build_wheel_odometry_template_records()
        write_wheel_odometry_template_jsonl(wheel_odometry_template_jsonl, wheel_template_records)
        wheel_odometry_template_md.write_text(
            render_wheel_odometry_template_markdown(wheel_template_records),
            encoding="utf-8",
        )
        next_action["wheel_odometry_template_jsonl"] = str(wheel_odometry_template_jsonl)
        next_action["wheel_odometry_template_md"] = str(wheel_odometry_template_md)
    navigation_status = _scout_ins_dr_navigation_status(
        readiness=readiness,
        live_report=live_report,
        next_action=next_action,
        ins_dr_live_inputs_ready=ins_dr_live_inputs_ready,
        run_live_proof=run_live_proof,
    )
    completion_gate_summary = _ins_dr_completion_gate_summary(
        readiness=readiness,
        gnss_watch_report=gnss_watch_report,
        physical_report=physical_report,
        live_report=live_report,
        run_live_proof=run_live_proof,
        gnss_command_path_summary=gnss_command_path_summary,
        heading_evidence_summary=heading_evidence_summary,
        wheel_odometry_summary=wheel_odometry_summary,
        navigation_status=navigation_status,
        next_action=next_action,
    )
    next_action["scout_ins_dr_navigation_status"] = navigation_status["scout_ins_dr_navigation_status"]
    next_action["scout_ins_dr_navigation_status_reason"] = navigation_status[
        "scout_ins_dr_navigation_status_reason"
    ]
    next_action["ins_dr_completion_gate_summary"] = completion_gate_summary
    _write_json(next_action, next_action_json, pretty=pretty)
    next_action_md.write_text(_render_next_action_markdown(next_action), encoding="utf-8")
    report = {
        "source": "ins_dr_field_session",
        "artifact_kind": "ins_dr_field_session_report",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "field_session_status": session_status,
        "session_status": session_status,
        **navigation_status,
        "ins_dr_completion_gate_summary": completion_gate_summary,
        "ins_dr_completion_failed_gate_names": completion_gate_summary["failed_gate_names"],
        "completion_ready": bool(live_report and live_report.get("completion_ready") is True),
        "ready_for_live_field_proof": readiness.get("ready_for_live_field_proof") is True,
        "run_live_proof_requested": run_live_proof,
        "mission_graph": str(mission_graph_path),
        "output_dir": str(output_dir),
        "gnss_baud": gnss_baud,
        "include_uart": include_uart,
        "gnss_watch_before_readiness": gnss_watch_before_readiness,
        "gnss_watch_report_json": gnss_watch_report.get("report_json") if gnss_watch_report else None,
        "gnss_watch_status": gnss_watch_report.get("watch_status") if gnss_watch_report else None,
        "gnss_watch_goal_satisfied": gnss_watch_report.get("watch_goal_satisfied") if gnss_watch_report else None,
        "gnss_watch_ready_for_live_field_proof": (
            gnss_watch_report.get("ready_for_live_field_proof") if gnss_watch_report else None
        ),
        "gnss_watch_talker_signal_summary": (
            (gnss_watch_report.get("window_stability") or {}).get("talker_signal_summary")
            if gnss_watch_report
            else None
        ),
        "gnss_watch_best_talker": (
            (gnss_watch_report.get("window_stability") or {}).get("best_talker") if gnss_watch_report else None
        ),
        "gnss_watch_best_talker_cno_dbhz": (
            (gnss_watch_report.get("window_stability") or {}).get("best_talker_cno_dbhz")
            if gnss_watch_report
            else None
        ),
        "gnss_command_path_summary": gnss_command_path_summary,
        "gnss_physical_measurements_json": str(gnss_physical_measurements_json_path)
        if gnss_physical_measurements_json_path
        else None,
        "gnss_physical_checklist_report_json": str(physical_report_json) if physical_report is not None else None,
        "gnss_physical_overall_status": physical_report.get("overall_status") if physical_report else None,
        "gnss_physical_measurements_template_json": str(physical_template_json) if physical_template_written else None,
        "gnss_physical_measurements_template_md": str(physical_template_md) if physical_template_written else None,
        "heading_evidence_jsonl_paths": [str(path) for path in heading_evidence_paths],
        "imu_heading_capture_requested": imu_heading_capture_duration_seconds is not None,
        "imu_heading_capture_report_json": str(imu_heading_capture_report_json)
        if imu_heading_capture_report is not None
        else None,
        "imu_heading_capture_report": imu_heading_capture_report,
        "grove_imu_heading_capture_requested": grove_imu_heading_capture,
        "grove_imu_heading_capture_jsonl": str(grove_imu_heading_capture_jsonl)
        if grove_imu_heading_capture
        else None,
        "grove_imu_heading_capture_payload": grove_imu_heading_capture_payload,
        "wheel_odometry_jsonl_paths": [str(path) for path in wheel_odometry_paths],
        "wheel_encoder_gpio_capture_requested": wheel_encoder_gpio_capture,
        "live_wheel_encoder_gpio_capture_requested": live_wheel_encoder_gpio_capture,
        "wheel_encoder_gpio_capture_jsonl": str(wheel_encoder_capture_jsonl)
        if wheel_encoder_gpio_capture
        else None,
        "wheel_encoder_gpio_capture_report": wheel_encoder_gpio_capture_report,
        "wheel_odometry_template_jsonl": str(wheel_odometry_template_jsonl) if wheel_template_written else None,
        "wheel_odometry_template_md": str(wheel_odometry_template_md) if wheel_template_written else None,
        "raw_imu_heading_evidence_summary": heading_evidence_summary,
        "wheel_odometry_input_summary": wheel_odometry_summary,
        "ins_dr_live_inputs_ready": ins_dr_live_inputs_ready,
        "gnss_hardware_snapshot_json": str(hardware_snapshot_json),
        "hardware_snapshot_json": str(hardware_snapshot_json),
        "gnss_diagnosis_report_json": str(diagnosis_json),
        "diagnosis_json": str(diagnosis_json),
        "gnss_diagnosis_report_md": str(diagnosis_md),
        "diagnosis_md": str(diagnosis_md),
        "readiness_report_json": str(readiness_json),
        "readiness_gnss_talker_signal_summary": _readiness_talker_signal_summary(readiness),
        "readiness_gnss_best_talker": _readiness_best_talker(readiness),
        "readiness_gnss_best_talker_cno_dbhz": _readiness_best_talker_cno(readiness),
        "next_action_json": str(next_action_json),
        "next_action_md": str(next_action_md),
        "next_action_status": next_action["next_action_status"],
        "next_actions": next_action["actions"],
        "readiness_input_gnss_port": str(readiness_gnss_port),
        "readiness_input_gnss_evidence_jsonl_paths": [str(path) for path in readiness_gnss_evidence_paths],
        "readiness_status": readiness.get("field_run_readiness_status"),
        "readiness_selected_gnss_port": readiness.get("selected_gnss_port"),
        "readiness_auto_selection_status": (
            readiness.get("gnss_auto_selection_summary") or {}
        ).get("selection_status"),
        "live_field_proof_report_json": live_report.get("live_field_proof_report_json") if live_report else None,
        "auto_serial_candidate_count": len(auto_serial_candidates),
        "auto_serial_candidates": auto_serial_candidates,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_field_session_orchestration_only",
        "gnss_watch": gnss_watch_report,
        "gnss_physical": physical_report,
        "readiness": readiness,
        "diagnosis": diagnosis,
        "next_action": next_action,
        "live_report": live_report,
    }
    _write_json(report, field_session_report_json, pretty=pretty)
    return report


def _session_status(
    *,
    readiness: dict[str, Any],
    live_report: dict[str, Any] | None,
    run_live_proof: bool,
    gnss_watch_report: dict[str, Any] | None = None,
    ins_dr_live_inputs_ready: bool = True,
) -> str:
    if live_report is not None:
        return "live_proof_completed" if live_report.get("completion_ready") is True else "live_proof_failed"
    if readiness.get("ready_for_live_field_proof") is True and run_live_proof and not ins_dr_live_inputs_ready:
        return "dr_inputs_not_ready"
    if readiness.get("ready_for_live_field_proof") is True:
        return "ready_for_live_proof" if not run_live_proof else "live_proof_not_run"
    if gnss_watch_report is not None and gnss_watch_report.get("ready_for_live_field_proof") is not True:
        return "gnss_watch_not_ready"
    return "readiness_not_ready"


def _session_artifact_conflicts(paths: list[Path]) -> list[str]:
    return sorted(path.name for path in paths if path.exists())


def _load_physical_report(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"GNSS physical measurements JSON must be an object: {path}")
    if payload.get("source") == "pi_gnss_physical_checklist" and payload.get("overall_status"):
        return payload
    measurements = payload.get("template") if isinstance(payload.get("template"), dict) else payload
    if not isinstance(measurements, dict):
        raise ValueError(f"GNSS physical measurements payload must be an object: {path}")
    return evaluate_measurements(measurements)


def _capture_imu_heading_evidence(
    *,
    imu_heading_capture_port: Path,
    auto_serial_candidates: list[dict[str, Any]],
    baud: int,
    duration_seconds: float,
    output_jsonl: Path,
) -> dict[str, Any]:
    if duration_seconds <= 0:
        raise ValueError("imu_heading_capture_duration_seconds must be positive")
    targets = _imu_heading_capture_targets(
        imu_heading_capture_port=imu_heading_capture_port,
        auto_serial_candidates=auto_serial_candidates,
        baud=baud,
    )
    events: list[dict[str, Any]] = []
    payloads: list[dict[str, Any]] = []
    for target in targets:
        event_payloads: list[dict[str, Any]] = []
        capture_status = "captured"
        error = None
        path = Path(str(target["path"]))
        if not path.exists():
            capture_status = "skipped_missing_serial"
        else:
            try:
                frames = read_serial_frames(port=str(path), baud=baud, duration_seconds=duration_seconds)
                event_payloads = [build_imu_payload(frame, device_port=str(path), baud=baud) for frame in frames]
                for payload in event_payloads:
                    payload["imu_heading_capture_target_label"] = target["label"]
            except Exception as exc:
                capture_status = "error"
                error = f"{type(exc).__name__}: {exc}"
        payloads.extend(event_payloads)
        headings = [_heading_deg_from_payload(payload) for payload in event_payloads]
        heading_values = [heading for heading in headings if heading is not None]
        events.append(
            {
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "source": "ins_dr_field_session",
                "artifact_kind": "imu_heading_capture_window",
                "target_label": target["label"],
                "device_port": str(path),
                "baud": baud,
                "duration_seconds": duration_seconds,
                "capture_status": capture_status,
                "frame_count": len(event_payloads),
                "raw_imu_frame_count": sum(1 for payload in event_payloads if payload.get("raw_imu_present") is True),
                "heading_count": len(heading_values),
                "heading_deg_sample": heading_values[:5],
                "error": error,
                "phase1_safety_decision_change_allowed": False,
                "remote_outbound_allowed": False,
                "hardware_control_scope": "diagnostic_imu_heading_capture_only",
            }
        )
    _write_jsonl(output_jsonl, payloads)
    summary = _raw_imu_heading_evidence_summary([output_jsonl])
    return {
        "source": "ins_dr_field_session",
        "artifact_kind": "imu_heading_capture_report",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "requested_imu_heading_capture_port": str(imu_heading_capture_port),
        "baud": baud,
        "duration_seconds": duration_seconds,
        "target_count": len(targets),
        "targets": targets,
        "events": events,
        "output_jsonl": str(output_jsonl),
        "raw_imu_heading_evidence_summary": summary,
        "raw_imu_heading_ready": summary["raw_imu_heading_ready"],
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_imu_heading_capture_only",
    }


def _capture_grove_imu_heading_evidence(
    *,
    bus: Path,
    imu_address: int,
    mag_address: int,
    sample_count: int,
    sample_interval_ms: float,
    output_jsonl: Path,
) -> dict[str, Any]:
    if sample_count < 1:
        raise ValueError("grove_imu_sample_count must be at least 1")
    if sample_interval_ms < 0:
        raise ValueError("grove_imu_sample_interval_ms must be non-negative")
    try:
        payload = read_live_grove_imu_payload(
            bus=bus,
            imu_address=imu_address,
            mag_address=mag_address,
            sample_count=sample_count,
            sample_interval_ms=sample_interval_ms,
        )
    except Exception as exc:
        payload = grove_imu_error_payload(
            bus=bus,
            imu_address=imu_address,
            mag_address=mag_address,
            sample_count=sample_count,
            sample_interval_ms=sample_interval_ms,
            dry_run=False,
            error=exc,
        )
    _write_jsonl(output_jsonl, [payload])
    return payload


def _capture_wheel_encoder_gpio_evidence(
    *,
    left_gpio: int,
    right_gpio: int,
    meters_per_tick: float | None,
    duration_seconds: float,
    sample_interval_seconds: float,
    poll_interval_ms: float,
    active_low: bool,
    gpiochip: str,
    provider: str,
    output_jsonl: Path,
) -> dict[str, Any]:
    if meters_per_tick is None:
        payload = _wheel_encoder_error_payload(
            left_gpio=left_gpio,
            right_gpio=right_gpio,
            provider=provider,
            error="wheel_meters_per_tick is required for GPIO wheel encoder capture",
        )
        write_wheel_encoder_jsonl([payload], output_jsonl)
        return _wheel_encoder_capture_report(output_jsonl=output_jsonl, records=[payload], error=payload["error"])
    try:
        records = capture_wheel_encoder_records(
            left_gpio=left_gpio,
            right_gpio=right_gpio,
            meters_per_tick=meters_per_tick,
            duration_seconds=duration_seconds,
            sample_interval_seconds=sample_interval_seconds,
            poll_interval_ms=poll_interval_ms,
            active_low=active_low,
            gpiochip=gpiochip,
            provider=provider,
        )
        write_wheel_encoder_jsonl(records, output_jsonl)
        return _wheel_encoder_capture_report(output_jsonl=output_jsonl, records=records, error=None)
    except Exception as exc:
        payload = _wheel_encoder_error_payload(
            left_gpio=left_gpio,
            right_gpio=right_gpio,
            provider=provider,
            error=f"{type(exc).__name__}: {exc}",
        )
        write_wheel_encoder_jsonl([payload], output_jsonl)
        return _wheel_encoder_capture_report(output_jsonl=output_jsonl, records=[payload], error=payload["error"])


def _wheel_encoder_error_payload(*, left_gpio: int, right_gpio: int, provider: str, error: str) -> dict[str, Any]:
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": "pi_wheel_encoder_gpio_smoke",
        "provider": provider,
        "hardware_kind": "gpio_wheel_encoder_odometry",
        "read_status": "error",
        "error": error,
        "dry_run": False,
        "wheel": {"left_gpio": left_gpio, "right_gpio": right_gpio},
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "primary_truth_allowed": False,
        "raw_evidence_required": True,
        "replay_audit_supported": False,
        "hardware_control_scope": "diagnostic_gpio_wheel_encoder_capture_only",
    }


def _wheel_encoder_capture_report(
    *,
    output_jsonl: Path,
    records: list[dict[str, Any]],
    error: str | None,
) -> dict[str, Any]:
    usable = [record for record in records if record.get("dry_run") is not True and isinstance(record.get("odometry"), dict)]
    final = usable[-1] if usable else {}
    final_wheel = final.get("wheel") if isinstance(final.get("wheel"), dict) else {}
    movement_summary = summarize_wheel_encoder_records(records)
    return {
        "source": "ins_dr_field_session",
        "artifact_kind": "wheel_encoder_gpio_capture_report",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "output_jsonl": str(output_jsonl),
        "record_count": len(records),
        "usable_record_count": len(usable),
        "final_left_ticks": final_wheel.get("left_ticks"),
        "final_right_ticks": final_wheel.get("right_ticks"),
        "final_cumulative_distance_m": (final.get("odometry") or {}).get("cumulative_distance_m")
        if isinstance(final.get("odometry"), dict)
        else None,
        "movement_summary": movement_summary,
        "left_tick_delta": movement_summary["left_tick_delta"],
        "right_tick_delta": movement_summary["right_tick_delta"],
        "left_level_change_delta": movement_summary["left_level_change_delta"],
        "right_level_change_delta": movement_summary["right_level_change_delta"],
        "line_activity_observed": movement_summary["line_activity_observed"],
        "distance_delta_m": movement_summary["distance_delta_m"],
        "wheel_movement_observed": movement_summary["wheel_movement_observed"],
        "live_positive_wheel_movement_ready": movement_summary["live_positive_wheel_movement_ready"],
        "missing_reason": movement_summary["missing_reason"],
        "error": error,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "primary_truth_allowed": False,
        "hardware_control_scope": "diagnostic_gpio_wheel_encoder_capture_only",
    }


def _gnss_command_path_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    verdict = snapshot.get("verdict") if isinstance(snapshot.get("verdict"), dict) else {}
    per_target = verdict.get("per_target") if isinstance(verdict.get("per_target"), dict) else {}
    probes = snapshot.get("ublox_probes") if isinstance(snapshot.get("ublox_probes"), dict) else {}
    targets: list[dict[str, Any]] = []
    for label, state in per_target.items():
        if not isinstance(state, dict):
            continue
        probe = probes.get(label) if isinstance(probes.get(label), dict) else {}
        probe_summary = probe.get("summary") if isinstance(probe.get("summary"), dict) else {}
        command_path_state = state.get("command_path") or probe_summary.get("command_path_state")
        targets.append(
            {
                "label": label,
                "nmea_rx_path": state.get("nmea_rx_path"),
                "command_path_state": command_path_state,
                "receiver_response_observed": command_path_state == "receiver_response_observed",
                "antenna_text_status": state.get("antenna_text_status") or probe_summary.get("antenna_text_status"),
                "antenna_supervisor_status": state.get("antenna_supervisor_status")
                or probe_summary.get("antenna_status_label"),
                "ubx_frame_count": probe.get("ubx_frame_count"),
                "ubx_ack_nak_count": probe_summary.get("ubx_ack_nak_count"),
                "ubx_ack_ack_count": probe_summary.get("ubx_ack_ack_count"),
                "ubx_mon_hw_seen": state.get("ubx_mon_hw_seen") or probe_summary.get("ubx_mon_hw_seen"),
                "ubx_nav_svinfo_seen": state.get("ubx_nav_svinfo_seen") or probe_summary.get("ubx_nav_svinfo_seen"),
                "max_cno_dbhz": state.get("max_cno_dbhz") or probe_summary.get("max_cno_dbhz"),
                "gps_max_cno_dbhz": state.get("gps_max_cno_dbhz"),
                "gps_rf_signal_observed": state.get("gps_rf_signal_observed"),
                "any_rf_signal_observed": state.get("any_rf_signal_observed"),
                "likely_state": state.get("likely_state") or probe_summary.get("likely_state"),
            }
        )
    receiver_response_count = sum(1 for target in targets if target["receiver_response_observed"])
    host_rx_valid_count = sum(1 for target in targets if target.get("nmea_rx_path") == "valid_nmea_received")
    return {
        "source": "ins_dr_field_session",
        "artifact_kind": "gnss_command_path_summary",
        "target_count": len(targets),
        "host_rx_valid_count": host_rx_valid_count,
        "receiver_response_observed_count": receiver_response_count,
        "command_path_proven": receiver_response_count > 0,
        "gps_rf_signal_observed_count": sum(1 for target in targets if target.get("gps_rf_signal_observed") is True),
        "any_rf_signal_observed_count": sum(1 for target in targets if target.get("any_rf_signal_observed") is True),
        "mon_hw_seen_count": sum(1 for target in targets if target.get("ubx_mon_hw_seen") is True),
        "nav_svinfo_seen_count": sum(1 for target in targets if target.get("ubx_nav_svinfo_seen") is True),
        "targets": targets,
        "next_required_evidence": list(verdict.get("next_required_evidence") or []),
    }


def _imu_heading_capture_targets(
    *,
    imu_heading_capture_port: Path,
    auto_serial_candidates: list[dict[str, Any]],
    baud: int,
) -> list[dict[str, Any]]:
    if str(imu_heading_capture_port) != "auto":
        return [
            {
                "label": f"imu_explicit_{imu_heading_capture_port.name}_{baud}",
                "path": str(imu_heading_capture_port),
                "kind": "explicit_port",
                "baud": baud,
            }
        ]
    return [
        {
            "label": f"imu_auto_{index}_{Path(str(candidate.get('path'))).name}_{baud}",
            "path": str(candidate.get("path")),
            "kind": candidate.get("kind"),
            "baud": baud,
            "candidate": candidate,
        }
        for index, candidate in enumerate(auto_serial_candidates)
        if candidate.get("path")
    ]


def _raw_imu_heading_evidence_summary(paths: list[Path]) -> dict[str, Any]:
    payloads, errors = _load_jsonl_payloads(paths)
    headings = [_heading_deg_from_payload(payload) for payload in payloads]
    heading_values = [heading for heading in headings if heading is not None]
    raw_imu_payloads = [
        payload
        for payload in payloads
        if _payload_is_raw_imu_evidence(payload)
    ]
    raw_imu_heading_count = sum(
        1 for payload in raw_imu_payloads if _heading_deg_from_payload(payload) is not None
    )
    ready = bool(paths) and not errors and raw_imu_heading_count > 0
    return {
        "source": "ins_dr_field_session",
        "artifact_kind": "raw_imu_heading_evidence_summary",
        "heading_evidence_jsonl_paths": [str(path) for path in paths],
        "path_count": len(paths),
        "payload_count": len(payloads),
        "raw_imu_payload_count": len(raw_imu_payloads),
        "heading_count": len(heading_values),
        "raw_imu_heading_count": raw_imu_heading_count,
        "heading_deg_sample": heading_values[:5],
        "errors": errors,
        "raw_imu_heading_ready": ready,
        "missing_reason": None if ready else _raw_imu_heading_missing_reason(paths, errors, payloads, raw_imu_heading_count),
    }


def _wheel_odometry_input_summary(paths: list[Path]) -> dict[str, Any]:
    payloads, errors = _load_jsonl_payloads(paths)
    dry_run_payload_count = sum(1 for payload in payloads if payload.get("dry_run") is True)
    usable_payloads = [payload for payload in payloads if payload.get("dry_run") is not True]
    positive_delta_count = 0
    cumulative_values: list[float] = []
    tick_totals: list[float] = []
    for payload in usable_payloads:
        for section in (payload, payload.get("odometry") if isinstance(payload.get("odometry"), dict) else {}):
            if _float_or_none(section.get("distance_delta_m")) is not None and _float_or_none(section.get("distance_delta_m")) > 0:
                positive_delta_count += 1
                break
        cumulative_value = _wheel_cumulative_distance_m(payload)
        if cumulative_value is not None:
            cumulative_values.append(cumulative_value)
        tick_total = _wheel_tick_total(payload)
        if tick_total is not None:
            tick_totals.append(tick_total)
    positive_cumulative_delta_count = _positive_increase_count(cumulative_values)
    positive_tick_delta_count = _positive_increase_count(tick_totals)
    ready = (
        bool(paths)
        and not errors
        and bool(usable_payloads)
        and (
            positive_delta_count > 0
            or positive_cumulative_delta_count > 0
            or positive_tick_delta_count > 0
        )
    )
    return {
        "source": "ins_dr_field_session",
        "artifact_kind": "wheel_odometry_input_summary",
        "wheel_odometry_jsonl_paths": [str(path) for path in paths],
        "path_count": len(paths),
        "payload_count": len(payloads),
        "usable_payload_count": len(usable_payloads),
        "dry_run_payload_count": dry_run_payload_count,
        "positive_distance_delta_count": positive_delta_count,
        "cumulative_distance_count": len(cumulative_values),
        "positive_cumulative_distance_delta_count": positive_cumulative_delta_count,
        "tick_count": len(tick_totals),
        "positive_tick_delta_count": positive_tick_delta_count,
        "errors": errors,
        "wheel_odometry_ready": ready,
        "missing_reason": None if ready else _wheel_odometry_missing_reason(paths, errors, payloads),
    }


def _wheel_cumulative_distance_m(payload: dict[str, Any]) -> float | None:
    for section in (
        payload,
        payload.get("odometry") if isinstance(payload.get("odometry"), dict) else {},
        payload.get("wheel") if isinstance(payload.get("wheel"), dict) else {},
    ):
        value = _float_or_none(section.get("cumulative_distance_m"))
        if value is not None:
            return value
    return None


def _wheel_tick_total(payload: dict[str, Any]) -> float | None:
    for section in (
        payload,
        payload.get("wheel") if isinstance(payload.get("wheel"), dict) else {},
    ):
        left_ticks = _float_or_none(section.get("left_ticks"))
        right_ticks = _float_or_none(section.get("right_ticks"))
        if left_ticks is not None or right_ticks is not None:
            return (left_ticks or 0.0) + (right_ticks or 0.0)
    return None


def _positive_increase_count(values: list[float]) -> int:
    return sum(1 for previous, current in zip(values, values[1:]) if current > previous)


def _load_jsonl_payloads(paths: list[Path]) -> tuple[list[dict[str, Any]], list[str]]:
    payloads: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in paths:
        try:
            with path.open(encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if not line.strip():
                        continue
                    payload = json.loads(line)
                    if isinstance(payload, dict):
                        payloads.append(payload)
                    else:
                        errors.append(f"{path}:{line_number}: JSONL payload is not an object")
        except Exception as exc:
            errors.append(f"{path}: {type(exc).__name__}: {exc}")
    return payloads, errors


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
    samples = payload.get("samples") if isinstance(payload.get("samples"), list) else []
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        heading = _heading_deg_from_mag_raw(sample.get("mag_raw"))
        if heading is not None:
            return heading
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
        or payload.get("raw_imu_present") is True and "hiwonder" in source
    )


def _payload_checksum_valid(payload: dict[str, Any], parsed: dict[str, Any]) -> bool | None:
    if "checksum_valid" in payload:
        return payload.get("checksum_valid") is True
    if "checksum_valid" in parsed:
        return parsed.get("checksum_valid") is True
    return None


def _heading_deg_from_mag_raw(mag_raw: Any) -> float | None:
    if not isinstance(mag_raw, (list, tuple)) or len(mag_raw) < 2:
        return None
    mag_x = _float_or_none(mag_raw[0])
    mag_y = _float_or_none(mag_raw[1])
    if mag_x is None or mag_y is None or (mag_x == 0 and mag_y == 0):
        return None
    return math.degrees(math.atan2(mag_y, mag_x)) % 360.0


def _payload_is_raw_imu_evidence(payload: dict[str, Any]) -> bool:
    if payload.get("raw_imu_present") is True:
        return True
    if payload.get("source") != "pi_hiwonder_imu_usb_smoke":
        return False
    return payload.get("frame_type") in {"acceleration", "gyro", "angle"}


def _raw_imu_heading_missing_reason(
    paths: list[Path],
    errors: list[str],
    payloads: list[dict[str, Any]],
    raw_imu_heading_count: int,
) -> str:
    if not paths:
        return "no_heading_evidence_jsonl_paths"
    if errors:
        return "heading_evidence_jsonl_read_error"
    if not payloads:
        return "heading_evidence_jsonl_empty"
    if raw_imu_heading_count == 0:
        return "no_raw_imu_heading_payload"
    return "unknown"


def _wheel_odometry_missing_reason(paths: list[Path], errors: list[str], payloads: list[dict[str, Any]]) -> str:
    if not paths:
        return "no_wheel_odometry_jsonl_paths"
    if errors:
        return "wheel_odometry_jsonl_read_error"
    if not payloads:
        return "wheel_odometry_jsonl_empty"
    if all(payload.get("dry_run") is True for payload in payloads):
        return "wheel_odometry_dry_run_only"
    return "no_positive_wheel_motion_observed"


def _build_next_action_summary(
    *,
    session_status: str,
    readiness: dict[str, Any],
    diagnosis: dict[str, Any],
    gnss_watch_report: dict[str, Any] | None,
    physical_report: dict[str, Any] | None,
    live_report: dict[str, Any] | None,
    run_live_proof: bool,
    gnss_command_path_summary: dict[str, Any] | None = None,
    heading_evidence_summary: dict[str, Any] | None = None,
    wheel_odometry_summary: dict[str, Any] | None = None,
    ins_dr_live_inputs_ready: bool = True,
) -> dict[str, Any]:
    readiness_diagnosis = readiness.get("gnss_readiness_diagnosis")
    if not isinstance(readiness_diagnosis, dict):
        readiness_diagnosis = {}
    diagnosis_conclusion = diagnosis.get("conclusion") if isinstance(diagnosis.get("conclusion"), dict) else {}
    physical_status = physical_report.get("overall_status") if physical_report else None
    watch_status = gnss_watch_report.get("watch_status") if gnss_watch_report else None
    ready = readiness.get("ready_for_live_field_proof") is True
    completion_ready = bool(live_report and live_report.get("completion_ready") is True)
    heading_evidence_summary = heading_evidence_summary or {}
    wheel_odometry_summary = wheel_odometry_summary or {}
    gnss_command_path_summary = gnss_command_path_summary or {}

    actions: list[dict[str, Any]] = []
    blockers: list[str] = []

    if completion_ready:
        status = "field_navigation_evidence_completed"
        actions.append(
            _action(
                priority=1,
                action="Archive the live proof bundle and keep the raw GNSS/IMU/wheel evidence with the manifest.",
                rationale="Live proof reported completion_ready=true.",
                evidence_required=["proof-manifest.json", "verification-report.json", "field-report.json"],
            )
        )
    elif ready and not ins_dr_live_inputs_ready:
        status = "collect_dr_evidence_inputs"
        blockers.extend(_dr_input_blockers(heading_evidence_summary, wheel_odometry_summary))
        actions.append(
            _action(
                priority=1,
                action="Collect raw IMU heading evidence and wheel odometry evidence before live INS/DR proof.",
                rationale="GNSS readiness alone is not enough; Scout needs a raw IMU heading baseline plus a DR distance source.",
                evidence_required=_dr_input_evidence_required(heading_evidence_summary, wheel_odometry_summary),
            )
        )
    elif ready and not run_live_proof:
        status = "run_live_proof_next"
        actions.append(
            _action(
                priority=1,
                action="Run live field proof using the readiness report selected_gnss_port.",
                rationale="Readiness is ready, but live proof was not requested in this session.",
                evidence_required=["live-field-proof-report.json", "proof-manifest.json", "verification-report.json"],
            )
        )
    elif physical_status == "physical_fault_indicated":
        status = "repair_physical_fault"
        blockers.append("physical measurements indicate a GNSS hardware fault")
        actions.append(
            _action(
                priority=1,
                action="Repair the failed GNSS physical check before repeating GNSS watch/readiness.",
                rationale="Physical checklist overall_status=physical_fault_indicated.",
                evidence_required=_physical_failed_checks(physical_report),
            )
        )
    elif _gnss_signal_without_fix_state(watch_status=watch_status, readiness_diagnosis=readiness_diagnosis):
        status = "wait_for_valid_fix"
        blockers.append("GNSS signal is present but valid fix is missing")
        actions.append(
            _action(
                priority=1,
                action=_signal_without_fix_action(readiness_diagnosis),
                rationale=str(
                    readiness_diagnosis.get("next_operator_action")
                    or "C/N0 exists, but readiness still requires valid GNSS fix for live proof."
                ),
                evidence_required=[
                    "watch_status=valid_fix_observed",
                    "field_run_readiness_status=ready",
                    "gps_max_cno_dbhz or valid_fix_count > 0",
                ],
            )
        )
    elif physical_report is None and _gnss_no_rf_state(watch_status=watch_status, readiness_diagnosis=readiness_diagnosis):
        status = "collect_physical_measurements"
        blockers.append("GNSS NMEA is present but no C/N0 or valid fix is observed")
        actions.append(
            _action(
                priority=1,
                action="Fill the GNSS physical measurement checklist and rerun field session with --gnss-physical-measurements-json.",
                rationale="NMEA is alive but RF/C/N0 evidence is missing, and no physical checklist is attached.",
                evidence_required=[
                    "vcc_voltage_v",
                    "power_off_rf_center_to_gnd_ohm",
                    "power_off_antenna_center_to_gnd_ohm",
                    "power_off_antenna_center_to_rf_in_ohm",
                    "antenna_patch_faces_sky",
                    "known_good_gps_l1_antenna_tested when available",
                ],
            )
        )
    elif _gnss_no_rf_state(watch_status=watch_status, readiness_diagnosis=readiness_diagnosis):
        status = "fix_gnss_rf_or_antenna"
        blockers.append("GNSS has no RF/CN0 evidence")
        actions.append(
            _action(
                priority=1,
                action="Fix GNSS antenna/RF path, placement, or bias before attempting INS/DR field proof.",
                rationale="GNSS watch/readiness still reports no C/N0.",
                evidence_required=_diagnosis_next_evidence(diagnosis),
            )
        )
    elif not ready:
        status = "continue_readiness_debug"
        blockers.append("field readiness is not ready")
        actions.append(
            _action(
                priority=1,
                action="Resolve failed readiness checks before live proof.",
                rationale=str(readiness_diagnosis.get("next_operator_action") or diagnosis_conclusion.get("reason") or session_status),
                evidence_required=_failed_readiness_checks(readiness) or _diagnosis_next_evidence(diagnosis),
            )
        )
    else:
        status = "review_session"
        actions.append(
            _action(
                priority=1,
                action="Review field session artifacts and rerun with --run-live-proof if appropriate.",
                rationale=f"Unhandled session status: {session_status}.",
                evidence_required=["field-session-report.json"],
            )
        )

    if not completion_ready:
        actions.append(
            _action(
                priority=99,
                action="Do not run live INS/DR proof or declare Scout INS/DR usable until GNSS and DR inputs are ready.",
                rationale="Raw GNSS valid fix remains the anchor authority, and raw IMU heading plus wheel odometry are required for DR proof.",
                evidence_required=[
                    "ready_for_live_field_proof=true",
                    "selected_gnss_port",
                    "valid_fix_count > 0",
                    "raw_imu_heading_ready=true",
                    "wheel_odometry_ready=true",
                ],
            )
        )

    return {
        "source": "ins_dr_field_session",
        "artifact_kind": "ins_dr_field_session_next_action",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "next_action_status": status,
        "session_status": session_status,
        "ready_for_live_field_proof": ready,
        "completion_ready": completion_ready,
        "watch_status": watch_status,
        "readiness_status": readiness.get("field_run_readiness_status"),
        "readiness_diagnosis_state": readiness_diagnosis.get("state"),
        "readiness_gnss_talker_signal_summary": _readiness_talker_signal_summary(readiness),
        "readiness_gnss_best_talker": _readiness_best_talker(readiness),
        "readiness_gnss_best_talker_cno_dbhz": _readiness_best_talker_cno(readiness),
        "diagnosis_status": diagnosis_conclusion.get("status"),
        "physical_overall_status": physical_status,
        "gnss_watch_talker_signal_summary": (
            (gnss_watch_report.get("window_stability") or {}).get("talker_signal_summary")
            if gnss_watch_report
            else None
        ),
        "gnss_watch_best_talker": (
            (gnss_watch_report.get("window_stability") or {}).get("best_talker") if gnss_watch_report else None
        ),
        "gnss_watch_best_talker_cno_dbhz": (
            (gnss_watch_report.get("window_stability") or {}).get("best_talker_cno_dbhz")
            if gnss_watch_report
            else None
        ),
        "gnss_command_path_summary": gnss_command_path_summary,
        "raw_imu_heading_evidence_summary": heading_evidence_summary,
        "wheel_odometry_input_summary": wheel_odometry_summary,
        "ins_dr_live_inputs_ready": ins_dr_live_inputs_ready,
        "blockers": blockers,
        "actions": actions,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_field_session_operator_guidance_only",
    }


def _readiness_signal(readiness: dict[str, Any]) -> dict[str, Any]:
    evidence_summary = readiness.get("gnss_evidence_summary")
    if not isinstance(evidence_summary, dict):
        return {}
    signal = evidence_summary.get("signal")
    return signal if isinstance(signal, dict) else {}


def _readiness_talker_signal_summary(readiness: dict[str, Any]) -> dict[str, Any] | None:
    summary = _readiness_signal(readiness).get("talker_signal_summary")
    return summary if isinstance(summary, dict) else None


def _readiness_best_talker(readiness: dict[str, Any]) -> Any:
    return _readiness_signal(readiness).get("best_talker")


def _readiness_best_talker_cno(readiness: dict[str, Any]) -> Any:
    return _readiness_signal(readiness).get("best_talker_cno_dbhz")


def _render_next_action_markdown(next_action: dict[str, Any]) -> str:
    lines = [
        "# Scout INS/DR Field Session Next Action",
        "",
        f"- Status: `{next_action['next_action_status']}`",
        f"- Navigation status: `{next_action.get('scout_ins_dr_navigation_status')}`",
        f"- Navigation reason: `{next_action.get('scout_ins_dr_navigation_status_reason')}`",
        f"- Ready for live field proof: `{str(next_action['ready_for_live_field_proof']).lower()}`",
        f"- Completion ready: `{str(next_action['completion_ready']).lower()}`",
        f"- Watch status: `{next_action.get('watch_status')}`",
        f"- Watch best talker: `{next_action.get('gnss_watch_best_talker')}` "
        f"C/N0 `{next_action.get('gnss_watch_best_talker_cno_dbhz')}`",
        f"- Readiness best talker: `{next_action.get('readiness_gnss_best_talker')}` "
        f"C/N0 `{next_action.get('readiness_gnss_best_talker_cno_dbhz')}`",
        f"- Readiness diagnosis: `{next_action.get('readiness_diagnosis_state')}`",
        f"- Diagnosis status: `{next_action.get('diagnosis_status')}`",
        f"- Physical status: `{next_action.get('physical_overall_status')}`",
        "",
    ]
    gnss_command = next_action.get("gnss_command_path_summary") or {}
    if gnss_command:
        lines.extend(
            [
                "## GNSS Command/RF Debug",
                "",
                f"- Host RX valid targets: `{gnss_command.get('host_rx_valid_count')}`",
                f"- Receiver command responses: `{gnss_command.get('receiver_response_observed_count')}`",
                f"- MON-HW targets: `{gnss_command.get('mon_hw_seen_count')}`",
                f"- NAV-SVINFO targets: `{gnss_command.get('nav_svinfo_seen_count')}`",
                "",
            ]
        )
        for target in gnss_command.get("targets") or []:
            lines.append(
                f"- {target.get('label')}: command=`{target.get('command_path_state')}`, "
                f"antenna_txt=`{target.get('antenna_text_status')}`, "
                f"max_cno=`{target.get('max_cno_dbhz')}`"
            )
        lines.append("")
    completion_gates = (next_action.get("ins_dr_completion_gate_summary") or {}).get("gates") or []
    if completion_gates:
        lines.extend(["## Completion Gates", ""])
        for gate in completion_gates:
            passed = str(gate.get("passed") is True).lower()
            lines.append(f"- {gate.get('name')}: `{gate.get('status')}` passed=`{passed}`")
        lines.append("")
    if next_action.get("gnss_physical_measurements_template_json"):
        lines.extend(
            [
                "## Physical Measurement Template",
                "",
                f"- JSON: `{next_action.get('gnss_physical_measurements_template_json')}`",
                f"- Worksheet: `{next_action.get('gnss_physical_measurements_template_md')}`",
                "",
            ]
        )
    if next_action.get("wheel_odometry_template_jsonl"):
        lines.extend(
            [
                "## Wheel Odometry Template",
                "",
                f"- JSONL: `{next_action.get('wheel_odometry_template_jsonl')}`",
                f"- Worksheet: `{next_action.get('wheel_odometry_template_md')}`",
                "",
            ]
        )
    blockers = next_action.get("blockers") or []
    if blockers:
        lines.extend(["## Blockers", ""])
        for blocker in blockers:
            lines.append(f"- {blocker}")
        lines.append("")
    lines.extend(["## Actions", ""])
    for action in next_action.get("actions") or []:
        lines.append(f"- P{action['priority']}: {action['action']}")
        if action.get("rationale"):
            lines.append(f"  Rationale: {action['rationale']}")
        if action.get("evidence_required"):
            lines.append(f"  Evidence: {', '.join(str(item) for item in action['evidence_required'])}")
    lines.append("")
    return "\n".join(lines)


def _scout_ins_dr_navigation_status(
    *,
    readiness: dict[str, Any],
    live_report: dict[str, Any] | None,
    next_action: dict[str, Any],
    ins_dr_live_inputs_ready: bool,
    run_live_proof: bool,
) -> dict[str, Any]:
    completion_ready = bool(live_report and live_report.get("completion_ready") is True)
    next_action_status = str(next_action.get("next_action_status") or "")
    ready_for_live_field_proof = readiness.get("ready_for_live_field_proof") is True

    if completion_ready:
        status = "field_ready"
        reason = "Live proof completed with completion_ready=true."
    elif live_report is not None:
        status = "live_proof_failed"
        reason = "Live proof ran but did not produce completion_ready=true."
    elif next_action_status == "repair_physical_fault":
        status = "not_ready_gnss_physical_fault"
        reason = "GNSS physical measurements indicate a hardware fault."
    elif next_action_status == "collect_physical_measurements":
        status = "not_ready_gnss_physical_evidence"
        reason = "GNSS has no C/N0 or valid fix and still needs physical RF/antenna measurements."
    elif next_action_status == "fix_gnss_rf_or_antenna":
        status = "not_ready_gnss_rf_or_antenna"
        reason = "GNSS RF/antenna path still lacks usable C/N0 evidence."
    elif next_action_status == "wait_for_valid_fix":
        status = "not_ready_gnss_valid_fix"
        reason = "GNSS signal exists, but no valid fix is available for anchor authority."
    elif ready_for_live_field_proof and not ins_dr_live_inputs_ready:
        status = "not_ready_dr_inputs"
        reason = "GNSS readiness is satisfied, but raw IMU heading or wheel odometry evidence is missing."
    elif ready_for_live_field_proof and ins_dr_live_inputs_ready and not run_live_proof:
        status = "ready_for_live_proof"
        reason = "GNSS and DR inputs are ready; run live proof to verify navigation."
    elif ready_for_live_field_proof and ins_dr_live_inputs_ready and run_live_proof:
        status = "live_proof_not_completed"
        reason = "Live proof was requested but no completion report was produced."
    else:
        status = "not_ready_readiness"
        reason = "Field readiness is not ready."

    return {
        "scout_ins_dr_navigation_status": status,
        "scout_ins_dr_navigation_status_reason": reason,
        "scout_ins_dr_navigation_completion_ready": completion_ready,
        "scout_ins_dr_navigation_required_evidence": _navigation_required_evidence(status),
    }


def _navigation_required_evidence(status: str) -> list[str]:
    if status == "field_ready":
        return ["proof-manifest.json", "verification-report.json", "field-report.json"]
    if status.startswith("not_ready_gnss"):
        return ["valid GNSS fix", "selected_gnss_port", "raw GNSS NMEA evidence"]
    if status == "not_ready_dr_inputs":
        return ["raw IMU heading JSONL", "wheel odometry JSONL"]
    if status == "ready_for_live_proof":
        return ["live-field-proof-report.json", "proof-manifest.json", "verification-report.json"]
    if status in {"live_proof_failed", "live_proof_not_completed"}:
        return ["live-field-proof-report.json", "operator-events.jsonl", "field-report.json"]
    return ["field-session-report.json"]


def _ins_dr_completion_gate_summary(
    *,
    readiness: dict[str, Any],
    gnss_watch_report: dict[str, Any] | None,
    physical_report: dict[str, Any] | None,
    live_report: dict[str, Any] | None,
    run_live_proof: bool,
    gnss_command_path_summary: dict[str, Any],
    heading_evidence_summary: dict[str, Any],
    wheel_odometry_summary: dict[str, Any],
    navigation_status: dict[str, Any],
    next_action: dict[str, Any],
) -> dict[str, Any]:
    readiness_diagnosis = readiness.get("gnss_readiness_diagnosis")
    if not isinstance(readiness_diagnosis, dict):
        readiness_diagnosis = {}
    ready_for_live_field_proof = readiness.get("ready_for_live_field_proof") is True
    raw_imu_heading_ready = heading_evidence_summary.get("raw_imu_heading_ready") is True
    wheel_odometry_ready = wheel_odometry_summary.get("wheel_odometry_ready") is True
    live_proof_passed = bool(live_report and live_report.get("completion_ready") is True)
    completion_ready = navigation_status.get("scout_ins_dr_navigation_completion_ready") is True

    gates = [
        _completion_gate(
            name="gnss_anchor",
            label="GNSS anchor authority",
            passed=ready_for_live_field_proof,
            status=_gnss_anchor_gate_status(
                ready_for_live_field_proof=ready_for_live_field_proof,
                gnss_watch_report=gnss_watch_report,
                physical_report=physical_report,
                readiness_diagnosis=readiness_diagnosis,
            ),
            required_evidence=[
                "raw GNSS NMEA evidence",
                "valid GNSS fix",
                "selected_gnss_port",
            ],
            evidence={
                "ready_for_live_field_proof": ready_for_live_field_proof,
                "field_run_readiness_status": readiness.get("field_run_readiness_status"),
                "selected_gnss_port": readiness.get("selected_gnss_port"),
                "gnss_watch_status": gnss_watch_report.get("watch_status") if gnss_watch_report else None,
                "gnss_watch_valid_fix_count": gnss_watch_report.get("valid_fix_count")
                if gnss_watch_report
                else None,
                "gnss_watch_gps_max_cno_dbhz": gnss_watch_report.get("gps_max_cno_dbhz")
                if gnss_watch_report
                else None,
                "gnss_watch_max_cno_dbhz": gnss_watch_report.get("max_cno_dbhz") if gnss_watch_report else None,
                "gnss_watch_intermittent_rf_observed": gnss_watch_report.get("intermittent_rf_observed")
                if gnss_watch_report
                else None,
                "gnss_watch_valid_fix_window_count": gnss_watch_report.get("valid_fix_window_count")
                if gnss_watch_report
                else None,
                "gnss_watch_gps_cno_window_count": gnss_watch_report.get("gps_cno_window_count")
                if gnss_watch_report
                else None,
                "gnss_watch_any_cno_window_count": gnss_watch_report.get("any_cno_window_count")
                if gnss_watch_report
                else None,
                "gnss_watch_no_rf_window_count": gnss_watch_report.get("no_rf_window_count")
                if gnss_watch_report
                else None,
                "gnss_physical_overall_status": physical_report.get("overall_status") if physical_report else None,
                "readiness_diagnosis_state": readiness_diagnosis.get("state"),
                "command_path_proven": gnss_command_path_summary.get("command_path_proven"),
                "receiver_response_observed_count": gnss_command_path_summary.get(
                    "receiver_response_observed_count"
                ),
                "antenna_text_statuses": [
                    target.get("antenna_text_status")
                    for target in gnss_command_path_summary.get("targets", [])
                    if target.get("antenna_text_status")
                ],
                "mon_hw_seen_count": gnss_command_path_summary.get("mon_hw_seen_count"),
                "nav_svinfo_seen_count": gnss_command_path_summary.get("nav_svinfo_seen_count"),
            },
            blocker=None
            if ready_for_live_field_proof
            else _gnss_anchor_gate_blocker(
                gnss_watch_report=gnss_watch_report,
                physical_report=physical_report,
                readiness_diagnosis=readiness_diagnosis,
                next_action=next_action,
            ),
        ),
        _completion_gate(
            name="raw_imu_heading",
            label="Raw IMU heading baseline",
            passed=raw_imu_heading_ready,
            status="passed" if raw_imu_heading_ready else "missing_raw_imu_heading",
            required_evidence=[
                "raw IMU JSONL with raw_imu_present=true",
                "parsed.angle_deg yaw or heading_deg",
            ],
            evidence={
                "raw_imu_heading_ready": raw_imu_heading_ready,
                "heading_evidence_jsonl_paths": heading_evidence_summary.get("heading_evidence_jsonl_paths") or [],
                "raw_imu_heading_count": heading_evidence_summary.get("raw_imu_heading_count"),
                "heading_count": heading_evidence_summary.get("heading_count"),
                "missing_reason": heading_evidence_summary.get("missing_reason"),
            },
            blocker=None
            if raw_imu_heading_ready
            else f"raw IMU heading baseline missing: {heading_evidence_summary.get('missing_reason')}",
        ),
        _completion_gate(
            name="wheel_odometry",
            label="Wheel odometry DR distance source",
            passed=wheel_odometry_ready,
            status="passed" if wheel_odometry_ready else "missing_wheel_odometry",
            required_evidence=[
                "wheel odometry JSONL with positive distance_delta_m",
                "or positive cumulative_distance_m / encoder tick increase",
            ],
            evidence={
                "wheel_odometry_ready": wheel_odometry_ready,
                "wheel_odometry_jsonl_paths": wheel_odometry_summary.get("wheel_odometry_jsonl_paths") or [],
                "positive_distance_delta_count": wheel_odometry_summary.get("positive_distance_delta_count"),
                "cumulative_distance_count": wheel_odometry_summary.get("cumulative_distance_count"),
                "positive_cumulative_distance_delta_count": wheel_odometry_summary.get(
                    "positive_cumulative_distance_delta_count"
                ),
                "tick_count": wheel_odometry_summary.get("tick_count"),
                "positive_tick_delta_count": wheel_odometry_summary.get("positive_tick_delta_count"),
                "missing_reason": wheel_odometry_summary.get("missing_reason"),
            },
            blocker=None
            if wheel_odometry_ready
            else f"wheel odometry DR distance source missing: {wheel_odometry_summary.get('missing_reason')}",
        ),
        _completion_gate(
            name="live_field_proof",
            label="Live field proof",
            passed=live_proof_passed,
            status=_live_field_proof_gate_status(
                live_report=live_report,
                run_live_proof=run_live_proof,
                ready_for_live_field_proof=ready_for_live_field_proof,
                raw_imu_heading_ready=raw_imu_heading_ready,
                wheel_odometry_ready=wheel_odometry_ready,
            ),
            required_evidence=[
                "live-field-proof-report.json",
                "proof-manifest.json",
                "verification-report.json",
            ],
            evidence={
                "run_live_proof_requested": run_live_proof,
                "live_report_present": live_report is not None,
                "live_field_proof_report_json": live_report.get("live_field_proof_report_json")
                if live_report
                else None,
                "completion_ready": live_proof_passed,
            },
            blocker=_live_field_proof_gate_blocker(
                live_report=live_report,
                run_live_proof=run_live_proof,
                ready_for_live_field_proof=ready_for_live_field_proof,
                raw_imu_heading_ready=raw_imu_heading_ready,
                wheel_odometry_ready=wheel_odometry_ready,
            ),
        ),
    ]
    failed_gate_names = [str(gate["name"]) for gate in gates if gate.get("passed") is not True]
    passed_gate_names = [str(gate["name"]) for gate in gates if gate.get("passed") is True]
    return {
        "source": "ins_dr_field_session",
        "artifact_kind": "ins_dr_completion_gate_summary",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "overall_status": navigation_status.get("scout_ins_dr_navigation_status"),
        "overall_reason": navigation_status.get("scout_ins_dr_navigation_status_reason"),
        "completion_ready": completion_ready,
        "gate_count": len(gates),
        "passed_gate_names": passed_gate_names,
        "failed_gate_names": failed_gate_names,
        "gates": gates,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_field_session_completion_gate_summary_only",
    }


def _completion_gate(
    *,
    name: str,
    label: str,
    passed: bool,
    status: str,
    required_evidence: list[str],
    evidence: dict[str, Any],
    blocker: str | None,
) -> dict[str, Any]:
    return {
        "name": name,
        "label": label,
        "passed": passed,
        "status": status,
        "required_evidence": required_evidence,
        "evidence": evidence,
        "blockers": [] if passed or blocker is None else [blocker],
    }


def _gnss_anchor_gate_status(
    *,
    ready_for_live_field_proof: bool,
    gnss_watch_report: dict[str, Any] | None,
    physical_report: dict[str, Any] | None,
    readiness_diagnosis: dict[str, Any],
) -> str:
    if ready_for_live_field_proof:
        return "passed"
    physical_status = physical_report.get("overall_status") if physical_report else None
    if physical_status == "physical_fault_indicated":
        return "physical_fault_indicated"
    watch_status = gnss_watch_report.get("watch_status") if gnss_watch_report else None
    if _gnss_signal_without_fix_state(watch_status=watch_status, readiness_diagnosis=readiness_diagnosis):
        return "rf_signal_without_valid_fix"
    if _gnss_no_rf_state(watch_status=watch_status, readiness_diagnosis=readiness_diagnosis):
        return "no_rf_signal_or_cno"
    return "not_ready"


def _gnss_anchor_gate_blocker(
    *,
    gnss_watch_report: dict[str, Any] | None,
    physical_report: dict[str, Any] | None,
    readiness_diagnosis: dict[str, Any],
    next_action: dict[str, Any],
) -> str:
    physical_status = physical_report.get("overall_status") if physical_report else None
    if physical_status == "physical_fault_indicated":
        return "GNSS physical measurements indicate a hardware fault."
    watch_status = gnss_watch_report.get("watch_status") if gnss_watch_report else None
    if _gnss_signal_without_fix_state(watch_status=watch_status, readiness_diagnosis=readiness_diagnosis):
        return "GNSS RF/C/N0 exists, but valid fix is missing."
    if _gnss_no_rf_state(watch_status=watch_status, readiness_diagnosis=readiness_diagnosis):
        return "GNSS NMEA is present but no C/N0 or valid fix is observed."
    blockers = next_action.get("blockers") if isinstance(next_action.get("blockers"), list) else []
    return str(blockers[0]) if blockers else "GNSS anchor readiness is not ready."


def _live_field_proof_gate_status(
    *,
    live_report: dict[str, Any] | None,
    run_live_proof: bool,
    ready_for_live_field_proof: bool,
    raw_imu_heading_ready: bool,
    wheel_odometry_ready: bool,
) -> str:
    if live_report is not None:
        return "passed" if live_report.get("completion_ready") is True else "failed"
    if not (ready_for_live_field_proof and raw_imu_heading_ready and wheel_odometry_ready):
        return "waiting_for_required_inputs"
    if run_live_proof:
        return "not_completed"
    return "not_run"


def _live_field_proof_gate_blocker(
    *,
    live_report: dict[str, Any] | None,
    run_live_proof: bool,
    ready_for_live_field_proof: bool,
    raw_imu_heading_ready: bool,
    wheel_odometry_ready: bool,
) -> str | None:
    if live_report is not None:
        if live_report.get("completion_ready") is True:
            return None
        return "Live field proof ran but completion_ready is not true."
    missing: list[str] = []
    if not ready_for_live_field_proof:
        missing.append("GNSS anchor")
    if not raw_imu_heading_ready:
        missing.append("raw IMU heading")
    if not wheel_odometry_ready:
        missing.append("wheel odometry")
    if missing:
        return f"Live proof is waiting for required gates: {', '.join(missing)}."
    if run_live_proof:
        return "Live proof was requested but no completion report was produced."
    return "Live proof has not been run."


def _action(*, priority: int, action: str, rationale: str, evidence_required: list[str]) -> dict[str, Any]:
    return {
        "priority": priority,
        "action": action,
        "rationale": rationale,
        "evidence_required": evidence_required,
    }


def _gnss_no_rf_state(*, watch_status: Any, readiness_diagnosis: dict[str, Any]) -> bool:
    return watch_status == "timed_out_no_rf_signal" or readiness_diagnosis.get("state") == "no_rf_signal_observed"


def _gnss_signal_without_fix_state(*, watch_status: Any, readiness_diagnosis: dict[str, Any]) -> bool:
    return watch_status in {"gps_cno_observed_without_fix", "rf_signal_observed_without_fix"} or readiness_diagnosis.get(
        "state"
    ) in {"rf_signal_without_valid_fix", "non_gps_rf_signal_without_valid_fix"}


def _signal_without_fix_action(readiness_diagnosis: dict[str, Any]) -> str:
    if readiness_diagnosis.get("state") == "non_gps_rf_signal_without_valid_fix":
        return (
            "Keep the GNSS antenna under open sky, compare against a USB GPS L1 receiver, "
            "and continue watch until GPS C/N0 or valid_fix_observed."
        )
    return "Keep the GNSS antenna under open sky and continue watch until valid_fix_observed."


def _diagnosis_next_evidence(diagnosis: dict[str, Any]) -> list[str]:
    evidence = diagnosis.get("next_required_evidence")
    return list(evidence) if isinstance(evidence, list) and evidence else ["gnss-diagnosis-report.md"]


def _physical_failed_checks(physical_report: dict[str, Any] | None) -> list[str]:
    if not physical_report:
        return []
    checks = physical_report.get("checks") if isinstance(physical_report.get("checks"), list) else []
    failed = [str(check.get("name")) for check in checks if isinstance(check, dict) and check.get("status") == "fail"]
    return failed or list(physical_report.get("likely_causes") or [])


def _dr_input_blockers(
    heading_evidence_summary: dict[str, Any],
    wheel_odometry_summary: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if heading_evidence_summary.get("raw_imu_heading_ready") is not True:
        blockers.append(f"raw IMU heading baseline missing: {heading_evidence_summary.get('missing_reason')}")
    if wheel_odometry_summary.get("wheel_odometry_ready") is not True:
        blockers.append(f"wheel odometry DR distance source missing: {wheel_odometry_summary.get('missing_reason')}")
    return blockers


def _dr_input_evidence_required(
    heading_evidence_summary: dict[str, Any],
    wheel_odometry_summary: dict[str, Any],
) -> list[str]:
    evidence: list[str] = []
    if heading_evidence_summary.get("raw_imu_heading_ready") is not True:
        evidence.extend(
            [
                "pi_hiwonder_imu_usb_smoke JSONL with raw_imu_present=true",
                "parsed.angle_deg yaw or equivalent heading_deg",
            ]
        )
    if wheel_odometry_summary.get("wheel_odometry_ready") is not True:
        evidence.extend(
            [
                "wheel odometry JSONL with positive distance_delta_m",
                "or at least two cumulative_distance_m / encoder tick samples",
            ]
        )
    return evidence


def _failed_readiness_checks(readiness: dict[str, Any]) -> list[str]:
    checks = readiness.get("checks") if isinstance(readiness.get("checks"), list) else []
    return [str(check.get("name")) for check in checks if isinstance(check, dict) and check.get("passed") is False]


def _cli_success(report: dict[str, Any], *, run_live_proof: bool) -> bool:
    if run_live_proof:
        return report.get("field_session_status") == "live_proof_completed"
    return report.get("ready_for_live_field_proof") is True


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _write_json(payload: dict[str, Any], path: Path, *, pretty: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2 if pretty else None, sort_keys=not pretty) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, payloads: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n" for payload in payloads),
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a bounded Scout INS/DR field session preflight and optional live proof.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--mission-graph", type=Path, required=True)
    parser.add_argument("--gnss-baud", type=int, default=115200)
    parser.add_argument("--include-uart", action="store_true")
    parser.add_argument("--snapshot-ab-duration-seconds", type=float, default=60.0)
    parser.add_argument("--snapshot-probe-duration-seconds", type=float, default=10.0)
    parser.add_argument("--snapshot-poll-gap-seconds", type=float, default=0.12)
    parser.add_argument("--readiness-capture-duration-seconds", type=float, default=60.0)
    parser.add_argument("--readiness-auto-select-duration-seconds", type=float, default=30.0)
    parser.add_argument("--gnss-watch-before-readiness", action="store_true")
    parser.add_argument("--gnss-watch-window-seconds", type=float, default=10.0)
    parser.add_argument("--gnss-watch-max-wait-seconds", type=float, default=300.0)
    parser.add_argument("--gnss-watch-poll-interval-seconds", type=float, default=2.0)
    parser.add_argument("--gnss-watch-stop-on", choices=STOP_ON_VALUES, default="valid_fix")
    parser.add_argument("--gnss-watch-min-gps-cno-dbhz", type=float, default=25.0)
    parser.add_argument("--gnss-watch-min-any-cno-dbhz", type=float, default=20.0)
    parser.add_argument("--gnss-watch-max-window-count", type=int)
    parser.add_argument("--gnss-physical-measurements-json", type=Path)
    parser.add_argument("--run-live-proof", action="store_true")
    parser.add_argument("--mission-id", "--live-mission-id", dest="live_mission_id")
    parser.add_argument("--heading-evidence-jsonl", type=Path, action="append")
    parser.add_argument("--imu-heading-capture-port", type=Path)
    parser.add_argument("--imu-heading-baud", type=int, default=9600)
    parser.add_argument("--imu-heading-capture-duration-seconds", type=float)
    parser.add_argument("--grove-imu-heading-capture", action="store_true")
    parser.add_argument("--grove-imu-bus", type=Path, default=Path("/dev/i2c-1"))
    parser.add_argument("--grove-imu-address", type=lambda value: int(value, 0), default=ICM20600_DEFAULT_ADDRESS)
    parser.add_argument("--grove-mag-address", type=lambda value: int(value, 0), default=AK09918_DEFAULT_ADDRESS)
    parser.add_argument("--grove-imu-sample-count", type=int, default=5)
    parser.add_argument("--grove-imu-sample-interval-ms", type=float, default=100.0)
    parser.add_argument("--wheel-odometry-jsonl", type=Path, action="append")
    parser.add_argument("--wheel-encoder-gpio-capture", action="store_true")
    parser.add_argument("--wheel-encoder-left-gpio", type=int, default=20)
    parser.add_argument("--wheel-encoder-right-gpio", type=int, default=21)
    parser.add_argument("--wheel-encoder-capture-duration-seconds", type=float, default=5.0)
    parser.add_argument("--wheel-encoder-sample-interval-seconds", type=float, default=1.0)
    parser.add_argument("--wheel-encoder-poll-interval-ms", type=float, default=5.0)
    parser.add_argument("--wheel-encoder-active-low", action="store_true")
    parser.add_argument("--wheel-encoder-gpiochip", default="gpiochip0")
    parser.add_argument(
        "--live-wheel-encoder-gpio-capture",
        action="store_true",
        help="When --run-live-proof is ready, capture GPIO wheel encoder evidence after anchor and before re-anchor.",
    )
    parser.add_argument("--wheel-source", default="wheel_odometry")
    parser.add_argument("--wheel-provider", default="scout_wheel_encoder")
    parser.add_argument("--wheel-meters-per-tick", type=float)
    parser.add_argument("--wheel-max-delta-m", type=float, default=25.0)
    parser.add_argument("--movement-window-seconds", type=float, default=0.0)
    parser.add_argument("--anchor-duration-seconds", type=float, default=10.0)
    parser.add_argument("--anchor-wait-timeout-seconds", type=float)
    parser.add_argument("--anchor-retry-interval-seconds", type=float, default=0.0)
    parser.add_argument("--reanchor-duration-seconds", type=float, default=10.0)
    parser.add_argument("--reanchor-wait-timeout-seconds", type=float)
    parser.add_argument("--reanchor-retry-interval-seconds", type=float, default=0.0)
    parser.add_argument("--corridor-half-width-m", type=float, default=6.0)
    parser.add_argument("--allow-overwrite", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = run_field_session(
            output_dir=args.output_dir,
            mission_graph_path=args.mission_graph,
            gnss_baud=args.gnss_baud,
            include_uart=args.include_uart,
            snapshot_ab_duration_seconds=args.snapshot_ab_duration_seconds,
            snapshot_probe_duration_seconds=args.snapshot_probe_duration_seconds,
            snapshot_poll_gap_seconds=args.snapshot_poll_gap_seconds,
            readiness_capture_duration_seconds=args.readiness_capture_duration_seconds,
            readiness_auto_select_duration_seconds=args.readiness_auto_select_duration_seconds,
            gnss_watch_before_readiness=args.gnss_watch_before_readiness,
            gnss_watch_window_seconds=args.gnss_watch_window_seconds,
            gnss_watch_max_wait_seconds=args.gnss_watch_max_wait_seconds,
            gnss_watch_poll_interval_seconds=args.gnss_watch_poll_interval_seconds,
            gnss_watch_stop_on=args.gnss_watch_stop_on,
            gnss_watch_min_gps_cno_dbhz=args.gnss_watch_min_gps_cno_dbhz,
            gnss_watch_min_any_cno_dbhz=args.gnss_watch_min_any_cno_dbhz,
            gnss_watch_max_window_count=args.gnss_watch_max_window_count,
            gnss_physical_measurements_json_path=args.gnss_physical_measurements_json,
            allow_overwrite=args.allow_overwrite,
            run_live_proof=args.run_live_proof,
            live_mission_id=args.live_mission_id,
            heading_evidence_jsonl_paths=args.heading_evidence_jsonl,
            imu_heading_capture_port=args.imu_heading_capture_port,
            imu_heading_baud=args.imu_heading_baud,
            imu_heading_capture_duration_seconds=args.imu_heading_capture_duration_seconds,
            grove_imu_heading_capture=args.grove_imu_heading_capture,
            grove_imu_bus=args.grove_imu_bus,
            grove_imu_address=args.grove_imu_address,
            grove_mag_address=args.grove_mag_address,
            grove_imu_sample_count=args.grove_imu_sample_count,
            grove_imu_sample_interval_ms=args.grove_imu_sample_interval_ms,
            wheel_odometry_jsonl_paths=args.wheel_odometry_jsonl,
            wheel_encoder_gpio_capture=args.wheel_encoder_gpio_capture,
            wheel_encoder_left_gpio=args.wheel_encoder_left_gpio,
            wheel_encoder_right_gpio=args.wheel_encoder_right_gpio,
            wheel_encoder_capture_duration_seconds=args.wheel_encoder_capture_duration_seconds,
            wheel_encoder_sample_interval_seconds=args.wheel_encoder_sample_interval_seconds,
            wheel_encoder_poll_interval_ms=args.wheel_encoder_poll_interval_ms,
            wheel_encoder_active_low=args.wheel_encoder_active_low,
            wheel_encoder_gpiochip=args.wheel_encoder_gpiochip,
            live_wheel_encoder_gpio_capture=args.live_wheel_encoder_gpio_capture,
            wheel_source=args.wheel_source,
            wheel_provider=args.wheel_provider,
            wheel_meters_per_tick=args.wheel_meters_per_tick,
            wheel_max_delta_m=args.wheel_max_delta_m,
            movement_window_seconds=args.movement_window_seconds,
            anchor_duration_seconds=args.anchor_duration_seconds,
            anchor_wait_timeout_seconds=args.anchor_wait_timeout_seconds,
            anchor_retry_interval_seconds=args.anchor_retry_interval_seconds,
            reanchor_duration_seconds=args.reanchor_duration_seconds,
            reanchor_wait_timeout_seconds=args.reanchor_wait_timeout_seconds,
            reanchor_retry_interval_seconds=args.reanchor_retry_interval_seconds,
            corridor_half_width_m=args.corridor_half_width_m,
            pretty=args.pretty,
        )
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=not args.pretty))
    return 0 if _cli_success(report, run_live_proof=args.run_live_proof) else 1


if __name__ == "__main__":
    raise SystemExit(main())
