from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.ins_dr_field_session import run_field_session  # noqa: E402


def run_field_movement_drill(
    *,
    output_dir: Path,
    mission_graph_path: Path,
    wheel_meters_per_tick: float,
    gnss_baud: int = 115200,
    gnss_watch_window_seconds: float = 10.0,
    gnss_watch_max_wait_seconds: float = 300.0,
    gnss_watch_poll_interval_seconds: float = 2.0,
    gnss_watch_max_window_count: int | None = None,
    snapshot_ab_duration_seconds: float = 5.0,
    snapshot_probe_duration_seconds: float = 1.0,
    readiness_capture_duration_seconds: float = 10.0,
    readiness_auto_select_duration_seconds: float = 10.0,
    grove_imu_heading_capture: bool = True,
    grove_imu_sample_count: int = 5,
    grove_imu_sample_interval_ms: float = 100.0,
    wheel_encoder_left_gpio: int = 20,
    wheel_encoder_right_gpio: int = 21,
    wheel_encoder_capture_duration_seconds: float = 30.0,
    wheel_encoder_sample_interval_seconds: float = 1.0,
    wheel_encoder_poll_interval_ms: float = 5.0,
    wheel_encoder_active_low: bool = False,
    wheel_encoder_gpiochip: str = "gpiochip0",
    anchor_duration_seconds: float = 10.0,
    anchor_wait_timeout_seconds: float = 180.0,
    anchor_retry_interval_seconds: float = 2.0,
    reanchor_duration_seconds: float = 10.0,
    reanchor_wait_timeout_seconds: float = 180.0,
    reanchor_retry_interval_seconds: float = 2.0,
    corridor_half_width_m: float = 6.0,
    allow_overwrite: bool = False,
    dry_run_plan: bool = False,
    pretty: bool = False,
) -> dict[str, Any]:
    if wheel_meters_per_tick <= 0:
        raise ValueError("wheel_meters_per_tick must be positive")

    output_dir.mkdir(parents=True, exist_ok=True)
    drill_report_json = output_dir / "field-movement-drill-report.json"
    if drill_report_json.exists() and not allow_overwrite:
        raise ValueError(f"output_dir already contains {drill_report_json.name}")

    plan = _build_drill_plan(
        output_dir=output_dir,
        mission_graph_path=mission_graph_path,
        wheel_meters_per_tick=wheel_meters_per_tick,
        gnss_baud=gnss_baud,
        gnss_watch_window_seconds=gnss_watch_window_seconds,
        gnss_watch_max_wait_seconds=gnss_watch_max_wait_seconds,
        gnss_watch_poll_interval_seconds=gnss_watch_poll_interval_seconds,
        gnss_watch_max_window_count=gnss_watch_max_window_count,
        snapshot_ab_duration_seconds=snapshot_ab_duration_seconds,
        snapshot_probe_duration_seconds=snapshot_probe_duration_seconds,
        readiness_capture_duration_seconds=readiness_capture_duration_seconds,
        readiness_auto_select_duration_seconds=readiness_auto_select_duration_seconds,
        grove_imu_heading_capture=grove_imu_heading_capture,
        grove_imu_sample_count=grove_imu_sample_count,
        grove_imu_sample_interval_ms=grove_imu_sample_interval_ms,
        wheel_encoder_left_gpio=wheel_encoder_left_gpio,
        wheel_encoder_right_gpio=wheel_encoder_right_gpio,
        wheel_encoder_capture_duration_seconds=wheel_encoder_capture_duration_seconds,
        wheel_encoder_sample_interval_seconds=wheel_encoder_sample_interval_seconds,
        wheel_encoder_poll_interval_ms=wheel_encoder_poll_interval_ms,
        wheel_encoder_active_low=wheel_encoder_active_low,
        wheel_encoder_gpiochip=wheel_encoder_gpiochip,
        anchor_duration_seconds=anchor_duration_seconds,
        anchor_wait_timeout_seconds=anchor_wait_timeout_seconds,
        anchor_retry_interval_seconds=anchor_retry_interval_seconds,
        reanchor_duration_seconds=reanchor_duration_seconds,
        reanchor_wait_timeout_seconds=reanchor_wait_timeout_seconds,
        reanchor_retry_interval_seconds=reanchor_retry_interval_seconds,
        corridor_half_width_m=corridor_half_width_m,
    )

    if dry_run_plan:
        report = _build_drill_report(
            output_dir=output_dir,
            dry_run_plan=True,
            plan=plan,
            field_session_report=None,
        )
        _write_json(report, drill_report_json, pretty=pretty)
        return report

    field_session_report = run_field_session(
        output_dir=output_dir / "field-session",
        mission_graph_path=mission_graph_path,
        gnss_baud=gnss_baud,
        snapshot_ab_duration_seconds=snapshot_ab_duration_seconds,
        snapshot_probe_duration_seconds=snapshot_probe_duration_seconds,
        readiness_capture_duration_seconds=readiness_capture_duration_seconds,
        readiness_auto_select_duration_seconds=readiness_auto_select_duration_seconds,
        gnss_watch_before_readiness=True,
        gnss_watch_window_seconds=gnss_watch_window_seconds,
        gnss_watch_max_wait_seconds=gnss_watch_max_wait_seconds,
        gnss_watch_poll_interval_seconds=gnss_watch_poll_interval_seconds,
        gnss_watch_stop_on="valid_fix",
        gnss_watch_max_window_count=gnss_watch_max_window_count,
        allow_overwrite=allow_overwrite,
        run_live_proof=True,
        grove_imu_heading_capture=grove_imu_heading_capture,
        grove_imu_sample_count=grove_imu_sample_count,
        grove_imu_sample_interval_ms=grove_imu_sample_interval_ms,
        live_wheel_encoder_gpio_capture=True,
        wheel_encoder_left_gpio=wheel_encoder_left_gpio,
        wheel_encoder_right_gpio=wheel_encoder_right_gpio,
        wheel_encoder_capture_duration_seconds=wheel_encoder_capture_duration_seconds,
        wheel_encoder_sample_interval_seconds=wheel_encoder_sample_interval_seconds,
        wheel_encoder_poll_interval_ms=wheel_encoder_poll_interval_ms,
        wheel_encoder_active_low=wheel_encoder_active_low,
        wheel_encoder_gpiochip=wheel_encoder_gpiochip,
        wheel_meters_per_tick=wheel_meters_per_tick,
        movement_window_seconds=wheel_encoder_capture_duration_seconds,
        anchor_duration_seconds=anchor_duration_seconds,
        anchor_wait_timeout_seconds=anchor_wait_timeout_seconds,
        anchor_retry_interval_seconds=anchor_retry_interval_seconds,
        reanchor_duration_seconds=reanchor_duration_seconds,
        reanchor_wait_timeout_seconds=reanchor_wait_timeout_seconds,
        reanchor_retry_interval_seconds=reanchor_retry_interval_seconds,
        corridor_half_width_m=corridor_half_width_m,
        pretty=pretty,
    )
    report = _build_drill_report(
        output_dir=output_dir,
        dry_run_plan=False,
        plan=plan,
        field_session_report=field_session_report,
    )
    _write_json(report, drill_report_json, pretty=pretty)
    return report


def _build_drill_plan(
    *,
    output_dir: Path,
    mission_graph_path: Path,
    wheel_meters_per_tick: float,
    gnss_baud: int,
    gnss_watch_window_seconds: float,
    gnss_watch_max_wait_seconds: float,
    gnss_watch_poll_interval_seconds: float,
    gnss_watch_max_window_count: int | None,
    snapshot_ab_duration_seconds: float,
    snapshot_probe_duration_seconds: float,
    readiness_capture_duration_seconds: float,
    readiness_auto_select_duration_seconds: float,
    grove_imu_heading_capture: bool,
    grove_imu_sample_count: int,
    grove_imu_sample_interval_ms: float,
    wheel_encoder_left_gpio: int,
    wheel_encoder_right_gpio: int,
    wheel_encoder_capture_duration_seconds: float,
    wheel_encoder_sample_interval_seconds: float,
    wheel_encoder_poll_interval_ms: float,
    wheel_encoder_active_low: bool,
    wheel_encoder_gpiochip: str,
    anchor_duration_seconds: float,
    anchor_wait_timeout_seconds: float,
    anchor_retry_interval_seconds: float,
    reanchor_duration_seconds: float,
    reanchor_wait_timeout_seconds: float,
    reanchor_retry_interval_seconds: float,
    corridor_half_width_m: float,
) -> dict[str, Any]:
    return {
        "source": "ins_dr_field_movement_drill",
        "artifact_kind": "ins_dr_field_movement_drill_plan",
        "drill_profile": "gnss_anchor_then_live_gpio_wheel_then_reanchor",
        "output_dir": str(output_dir),
        "field_session_output_dir": str(output_dir / "field-session"),
        "mission_graph_path": str(mission_graph_path),
        "operator_steps": [
            "Place Scout where the GNSS antenna has open sky and hold still for the anchor wait.",
            "Do not move Scout until the live proof has a valid GNSS anchor and starts GPIO wheel capture.",
            "When wheel_encoder_gpio_capture_start is logged, push Scout forward for the capture duration.",
            "Stop and hold position for re-anchor until the drill finishes.",
        ],
        "gnss": {
            "baud": gnss_baud,
            "watch_window_seconds": gnss_watch_window_seconds,
            "watch_max_wait_seconds": gnss_watch_max_wait_seconds,
            "watch_poll_interval_seconds": gnss_watch_poll_interval_seconds,
            "watch_max_window_count": gnss_watch_max_window_count,
            "snapshot_ab_duration_seconds": snapshot_ab_duration_seconds,
            "snapshot_probe_duration_seconds": snapshot_probe_duration_seconds,
            "readiness_capture_duration_seconds": readiness_capture_duration_seconds,
            "readiness_auto_select_duration_seconds": readiness_auto_select_duration_seconds,
            "anchor_duration_seconds": anchor_duration_seconds,
            "anchor_wait_timeout_seconds": anchor_wait_timeout_seconds,
            "anchor_retry_interval_seconds": anchor_retry_interval_seconds,
            "reanchor_duration_seconds": reanchor_duration_seconds,
            "reanchor_wait_timeout_seconds": reanchor_wait_timeout_seconds,
            "reanchor_retry_interval_seconds": reanchor_retry_interval_seconds,
        },
        "imu": {
            "grove_imu_heading_capture": grove_imu_heading_capture,
            "grove_imu_sample_count": grove_imu_sample_count,
            "grove_imu_sample_interval_ms": grove_imu_sample_interval_ms,
            "raw_imu_heading_required": True,
        },
        "wheel": {
            "live_wheel_encoder_gpio_capture": True,
            "left_gpio": wheel_encoder_left_gpio,
            "right_gpio": wheel_encoder_right_gpio,
            "meters_per_tick": wheel_meters_per_tick,
            "capture_duration_seconds": wheel_encoder_capture_duration_seconds,
            "sample_interval_seconds": wheel_encoder_sample_interval_seconds,
            "poll_interval_ms": wheel_encoder_poll_interval_ms,
            "active_low": wheel_encoder_active_low,
            "gpiochip": wheel_encoder_gpiochip,
        },
        "corridor_half_width_m": corridor_half_width_m,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_field_movement_drill_only",
    }


def _build_drill_report(
    *,
    output_dir: Path,
    dry_run_plan: bool,
    plan: dict[str, Any],
    field_session_report: dict[str, Any] | None,
) -> dict[str, Any]:
    completion_ready = (
        field_session_report is not None
        and field_session_report.get("scout_ins_dr_navigation_completion_ready") is True
    )
    return {
        "source": "ins_dr_field_movement_drill",
        "artifact_kind": "ins_dr_field_movement_drill_report",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "dry_run_plan": dry_run_plan,
        "drill_profile": plan["drill_profile"],
        "output_dir": str(output_dir),
        "field_session_report_json": (
            str(output_dir / "field-session" / "field-session-report.json") if field_session_report else None
        ),
        "field_session_status": field_session_report.get("field_session_status") if field_session_report else None,
        "scout_ins_dr_navigation_status": (
            field_session_report.get("scout_ins_dr_navigation_status") if field_session_report else "not_run"
        ),
        "scout_ins_dr_navigation_completion_ready": completion_ready,
        "failed_gate_names": (
            field_session_report.get("ins_dr_completion_failed_gate_names") if field_session_report else []
        ),
        "next_action_status": field_session_report.get("next_action_status") if field_session_report else "dry_run_plan",
        "plan": plan,
        "field_session_report": field_session_report,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_field_movement_drill_only",
    }


def _write_json(payload: dict[str, Any], output_path: Path, *, pretty: bool) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2 if pretty else None, sort_keys=not pretty) + "\n",
        encoding="utf-8",
    )


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run Scout's one-command diagnostic INS/DR movement drill with GNSS anchor, raw IMU heading, live GPIO wheel capture, and GNSS re-anchor."
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--mission-graph", type=Path, required=True)
    parser.add_argument("--wheel-meters-per-tick", type=_positive_float, required=True)
    parser.add_argument("--gnss-baud", type=int, default=115200)
    parser.add_argument("--gnss-watch-window-seconds", type=_positive_float, default=10.0)
    parser.add_argument("--gnss-watch-max-wait-seconds", type=_positive_float, default=300.0)
    parser.add_argument("--gnss-watch-poll-interval-seconds", type=float, default=2.0)
    parser.add_argument("--gnss-watch-max-window-count", type=int)
    parser.add_argument("--snapshot-ab-duration-seconds", type=_positive_float, default=5.0)
    parser.add_argument("--snapshot-probe-duration-seconds", type=_positive_float, default=1.0)
    parser.add_argument("--readiness-capture-duration-seconds", type=_positive_float, default=10.0)
    parser.add_argument("--readiness-auto-select-duration-seconds", type=_positive_float, default=10.0)
    parser.add_argument("--no-grove-imu-heading-capture", action="store_true")
    parser.add_argument("--grove-imu-sample-count", type=int, default=5)
    parser.add_argument("--grove-imu-sample-interval-ms", type=_positive_float, default=100.0)
    parser.add_argument("--wheel-encoder-left-gpio", type=int, default=20)
    parser.add_argument("--wheel-encoder-right-gpio", type=int, default=21)
    parser.add_argument("--wheel-encoder-capture-duration-seconds", type=_positive_float, default=30.0)
    parser.add_argument("--wheel-encoder-sample-interval-seconds", type=_positive_float, default=1.0)
    parser.add_argument("--wheel-encoder-poll-interval-ms", type=_positive_float, default=5.0)
    parser.add_argument("--wheel-encoder-active-low", action="store_true")
    parser.add_argument("--wheel-encoder-gpiochip", default="gpiochip0")
    parser.add_argument("--anchor-duration-seconds", type=_positive_float, default=10.0)
    parser.add_argument("--anchor-wait-timeout-seconds", type=_positive_float, default=180.0)
    parser.add_argument("--anchor-retry-interval-seconds", type=float, default=2.0)
    parser.add_argument("--reanchor-duration-seconds", type=_positive_float, default=10.0)
    parser.add_argument("--reanchor-wait-timeout-seconds", type=_positive_float, default=180.0)
    parser.add_argument("--reanchor-retry-interval-seconds", type=float, default=2.0)
    parser.add_argument("--corridor-half-width-m", type=_positive_float, default=6.0)
    parser.add_argument("--dry-run-plan", action="store_true")
    parser.add_argument("--allow-overwrite", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = run_field_movement_drill(
            output_dir=args.output_dir,
            mission_graph_path=args.mission_graph,
            wheel_meters_per_tick=args.wheel_meters_per_tick,
            gnss_baud=args.gnss_baud,
            gnss_watch_window_seconds=args.gnss_watch_window_seconds,
            gnss_watch_max_wait_seconds=args.gnss_watch_max_wait_seconds,
            gnss_watch_poll_interval_seconds=args.gnss_watch_poll_interval_seconds,
            gnss_watch_max_window_count=args.gnss_watch_max_window_count,
            snapshot_ab_duration_seconds=args.snapshot_ab_duration_seconds,
            snapshot_probe_duration_seconds=args.snapshot_probe_duration_seconds,
            readiness_capture_duration_seconds=args.readiness_capture_duration_seconds,
            readiness_auto_select_duration_seconds=args.readiness_auto_select_duration_seconds,
            grove_imu_heading_capture=not args.no_grove_imu_heading_capture,
            grove_imu_sample_count=args.grove_imu_sample_count,
            grove_imu_sample_interval_ms=args.grove_imu_sample_interval_ms,
            wheel_encoder_left_gpio=args.wheel_encoder_left_gpio,
            wheel_encoder_right_gpio=args.wheel_encoder_right_gpio,
            wheel_encoder_capture_duration_seconds=args.wheel_encoder_capture_duration_seconds,
            wheel_encoder_sample_interval_seconds=args.wheel_encoder_sample_interval_seconds,
            wheel_encoder_poll_interval_ms=args.wheel_encoder_poll_interval_ms,
            wheel_encoder_active_low=args.wheel_encoder_active_low,
            wheel_encoder_gpiochip=args.wheel_encoder_gpiochip,
            anchor_duration_seconds=args.anchor_duration_seconds,
            anchor_wait_timeout_seconds=args.anchor_wait_timeout_seconds,
            anchor_retry_interval_seconds=args.anchor_retry_interval_seconds,
            reanchor_duration_seconds=args.reanchor_duration_seconds,
            reanchor_wait_timeout_seconds=args.reanchor_wait_timeout_seconds,
            reanchor_retry_interval_seconds=args.reanchor_retry_interval_seconds,
            corridor_half_width_m=args.corridor_half_width_m,
            allow_overwrite=args.allow_overwrite,
            dry_run_plan=args.dry_run_plan,
            pretty=args.pretty,
        )
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=not args.pretty))
    return 0 if report["dry_run_plan"] or report["scout_ins_dr_navigation_completion_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
