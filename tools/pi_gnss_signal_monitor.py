from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.pi_gnss_ab_compare import discover_serial_candidates, parse_nmea_capture, read_serial_bytes  # noqa: E402


def run_signal_monitor(
    *,
    output_dir: Path,
    port: str = "auto",
    baud: int = 115200,
    window_seconds: float = 2.0,
    interval_seconds: float = 0.0,
    max_window_count: int = 30,
    allow_overwrite: bool = False,
    pretty: bool = False,
) -> dict[str, Any]:
    if window_seconds <= 0:
        raise ValueError("window_seconds must be positive")
    if interval_seconds < 0:
        raise ValueError("interval_seconds must be non-negative")
    if max_window_count < 1:
        raise ValueError("max_window_count must be at least 1")

    output_dir.mkdir(parents=True, exist_ok=True)
    windows_jsonl = output_dir / "gnss-signal-monitor-windows.jsonl"
    report_json = output_dir / "gnss-signal-monitor-report.json"
    conflicts = [path.name for path in (windows_jsonl, report_json) if path.exists()]
    if conflicts and not allow_overwrite:
        raise ValueError(f"output_dir already contains GNSS signal monitor artifacts: {', '.join(conflicts)}")

    resolved_port, serial_resolution = _resolve_port(port)
    windows: list[dict[str, Any]] = []
    for index in range(max_window_count):
        raw = read_serial_bytes(resolved_port, baud, duration_seconds=window_seconds)
        capture = parse_nmea_capture(
            raw.decode("ascii", "replace"),
            label=f"monitor_{index}",
            device_port=resolved_port,
            baud=baud,
        )
        window = _monitor_window(
            capture=capture,
            index=index,
            resolved_port=resolved_port,
            baud=baud,
            window_seconds=window_seconds,
            raw_bytes=len(raw),
        )
        windows.append(window)
        print(_operator_line(window), file=sys.stderr)
        if index + 1 < max_window_count and interval_seconds > 0:
            time.sleep(interval_seconds)

    _write_jsonl(windows_jsonl, windows)
    report = _monitor_report(
        output_dir=output_dir,
        port=port,
        resolved_port=resolved_port,
        baud=baud,
        window_seconds=window_seconds,
        interval_seconds=interval_seconds,
        max_window_count=max_window_count,
        serial_resolution=serial_resolution,
        windows=windows,
        windows_jsonl=windows_jsonl,
        report_json=report_json,
    )
    _write_json(report, report_json, pretty=pretty)
    return report


def _resolve_port(port: str) -> tuple[str, dict[str, Any]]:
    if port != "auto":
        return port, {
            "requested_port": port,
            "resolved_port": port,
            "resolution_status": "explicit_port",
        }
    candidates = discover_serial_candidates()
    if not candidates:
        raise ValueError("no serial candidates found for GNSS signal monitor")
    chosen = candidates[0]
    return str(chosen["path"]), {
        "requested_port": "auto",
        "resolved_port": str(chosen["path"]),
        "resolution_status": "selected_first_serial_candidate",
        "candidate_count": len(candidates),
        "candidate": chosen,
        "candidates": candidates,
    }


def _monitor_window(
    *,
    capture: dict[str, Any],
    index: int,
    resolved_port: str,
    baud: int,
    window_seconds: float,
    raw_bytes: int,
) -> dict[str, Any]:
    summary = capture.get("summary") if isinstance(capture.get("summary"), dict) else {}
    talker_signal_summary = _window_talker_signal_summary(capture.get("gsv_by_talker"))
    talkers_with_cno = _talkers_with_cno(talker_signal_summary)
    best_talker = talkers_with_cno[0] if talkers_with_cno else None
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": "pi_gnss_signal_monitor",
        "artifact_kind": "gnss_signal_monitor_window",
        "window_index": index,
        "device_port": resolved_port,
        "baud": baud,
        "window_seconds": window_seconds,
        "raw_bytes": raw_bytes,
        "nmea_lines": capture.get("nmea_lines"),
        "valid_checksum_lines": capture.get("valid_checksum_lines"),
        "likely_state": summary.get("likely_state"),
        "fix_observed": summary.get("fix_observed"),
        "gps_rf_signal_observed": summary.get("gps_rf_signal_observed"),
        "any_rf_signal_observed": summary.get("any_rf_signal_observed"),
        "non_gps_rf_signal_observed": summary.get("non_gps_rf_signal_observed"),
        "gps_max_cno_dbhz": summary.get("gps_max_cno_dbhz"),
        "max_cno_dbhz": summary.get("max_cno_dbhz"),
        "talker_signal_summary": talker_signal_summary,
        "talkers_with_cno": talkers_with_cno,
        "best_talker": best_talker["talker"] if best_talker else None,
        "best_talker_cno_dbhz": best_talker["max_cno_dbhz"] if best_talker else None,
        "antenna_text_status": capture.get("antenna_text_status"),
        "gsv_by_talker": capture.get("gsv_by_talker"),
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_gnss_signal_monitor_only",
    }


def _monitor_report(
    *,
    output_dir: Path,
    port: str,
    resolved_port: str,
    baud: int,
    window_seconds: float,
    interval_seconds: float,
    max_window_count: int,
    serial_resolution: dict[str, Any],
    windows: list[dict[str, Any]],
    windows_jsonl: Path,
    report_json: Path,
) -> dict[str, Any]:
    state_counts: dict[str, int] = {}
    for window in windows:
        state = str(window.get("likely_state") or "unknown")
        state_counts[state] = state_counts.get(state, 0) + 1

    best = _best_window(windows)
    gps_cno_windows = [window for window in windows if window.get("gps_max_cno_dbhz") is not None]
    any_cno_windows = [window for window in windows if window.get("max_cno_dbhz") is not None]
    no_rf_windows = [window for window in windows if window.get("likely_state") == "no_rf_signal_observed"]
    fix_windows = [window for window in windows if window.get("fix_observed") is True]
    talker_signal_summary = _aggregate_talker_signal_summary(windows)
    return {
        "source": "pi_gnss_signal_monitor",
        "artifact_kind": "gnss_signal_monitor_report",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "output_dir": str(output_dir),
        "requested_port": port,
        "resolved_port": resolved_port,
        "baud": baud,
        "window_seconds": window_seconds,
        "interval_seconds": interval_seconds,
        "max_window_count": max_window_count,
        "window_count": len(windows),
        "state_counts": state_counts,
        "fix_window_count": len(fix_windows),
        "gps_cno_window_count": len(gps_cno_windows),
        "any_cno_window_count": len(any_cno_windows),
        "no_rf_window_count": len(no_rf_windows),
        "intermittent_rf_observed": bool(any_cno_windows and no_rf_windows),
        "best_window_index": best.get("window_index") if best else None,
        "best_likely_state": best.get("likely_state") if best else None,
        "best_gps_max_cno_dbhz": best.get("gps_max_cno_dbhz") if best else None,
        "best_max_cno_dbhz": best.get("max_cno_dbhz") if best else None,
        "best_talker": best.get("best_talker") if best else None,
        "best_talker_cno_dbhz": best.get("best_talker_cno_dbhz") if best else None,
        "talker_signal_summary": talker_signal_summary,
        "operator_recommendation": _operator_recommendation(
            fix_windows=fix_windows,
            gps_cno_windows=gps_cno_windows,
            any_cno_windows=any_cno_windows,
            no_rf_windows=no_rf_windows,
        ),
        "serial_resolution": serial_resolution,
        "windows_jsonl": str(windows_jsonl),
        "report_json": str(report_json),
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_gnss_signal_monitor_only",
        "windows": windows,
    }


def _best_window(windows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not windows:
        return None
    return max(
        windows,
        key=lambda window: (
            int(bool(window.get("fix_observed"))),
            int(bool(window.get("gps_rf_signal_observed"))),
            int(window.get("gps_max_cno_dbhz") or 0),
            int(window.get("max_cno_dbhz") or 0),
            int(window.get("best_talker_cno_dbhz") or 0),
            int(window.get("valid_checksum_lines") or 0),
        ),
    )


def _operator_recommendation(
    *,
    fix_windows: list[dict[str, Any]],
    gps_cno_windows: list[dict[str, Any]],
    any_cno_windows: list[dict[str, Any]],
    no_rf_windows: list[dict[str, Any]],
) -> str:
    if fix_windows:
        return "valid_fix_observed_hold_position_and_run_movement_drill"
    if gps_cno_windows:
        return "gps_cno_observed_hold_open_sky_until_valid_fix"
    if any_cno_windows and no_rf_windows:
        return "rf_is_intermittent_adjust_mounting_and_reduce_shielding"
    if any_cno_windows:
        return "non_gps_rf_observed_continue_open_sky_wait_for_gps_cno"
    return "no_rf_observed_try_open_sky_or_check_antenna_rf_path"


def _operator_line(window: dict[str, Any]) -> str:
    return (
        "[gnss-monitor] "
        f"window={window['window_index']} "
        f"state={window.get('likely_state')} "
        f"gps_cno={window.get('gps_max_cno_dbhz')} "
        f"any_cno={window.get('max_cno_dbhz')} "
        f"talkers={_operator_talkers(window)} "
        f"fix={str(window.get('fix_observed')).lower()}"
    )


def _window_talker_signal_summary(gsv_by_talker: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(gsv_by_talker, dict):
        return {}

    summary: dict[str, dict[str, Any]] = {}
    for talker, data in sorted(gsv_by_talker.items()):
        if not isinstance(data, dict):
            continue
        nonzero_cno_count = int(data.get("nonzero_cno_count") or 0)
        max_cno = data.get("cno_max")
        summary[str(talker)] = {
            "gsv_lines": int(data.get("gsv_lines") or 0),
            "visible_max": data.get("visible_max"),
            "nonzero_cno_count": nonzero_cno_count,
            "max_cno_dbhz": max_cno,
            "rf_signal_observed": nonzero_cno_count > 0,
        }
    return summary


def _talkers_with_cno(talker_signal_summary: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    talkers: list[dict[str, Any]] = []
    for talker, summary in talker_signal_summary.items():
        if int(summary.get("nonzero_cno_count") or 0) <= 0:
            continue
        talkers.append(
            {
                "talker": talker,
                "max_cno_dbhz": summary.get("max_cno_dbhz"),
                "nonzero_cno_count": summary.get("nonzero_cno_count"),
            }
        )
    return sorted(talkers, key=lambda item: (int(item.get("max_cno_dbhz") or 0), item["talker"]), reverse=True)


def _aggregate_talker_signal_summary(windows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    aggregate: dict[str, dict[str, Any]] = {}
    for window in windows:
        talker_summary = window.get("talker_signal_summary")
        if not isinstance(talker_summary, dict):
            continue
        for talker, summary in sorted(talker_summary.items()):
            if not isinstance(summary, dict):
                continue
            bucket = aggregate.setdefault(
                str(talker),
                {
                    "window_count": 0,
                    "nonzero_cno_window_count": 0,
                    "max_cno_dbhz": None,
                    "visible_max": None,
                    "gsv_line_count": 0,
                },
            )
            bucket["window_count"] += 1
            bucket["gsv_line_count"] += int(summary.get("gsv_lines") or 0)
            if summary.get("visible_max") is not None:
                bucket["visible_max"] = max(
                    int(bucket["visible_max"] or 0),
                    int(summary["visible_max"]),
                )
            if int(summary.get("nonzero_cno_count") or 0) > 0:
                bucket["nonzero_cno_window_count"] += 1
            if summary.get("max_cno_dbhz") is not None:
                bucket["max_cno_dbhz"] = max(
                    int(bucket["max_cno_dbhz"] or 0),
                    int(summary["max_cno_dbhz"]),
                )
    return aggregate


def _operator_talkers(window: dict[str, Any]) -> str:
    talkers = window.get("talkers_with_cno")
    if not isinstance(talkers, list) or not talkers:
        return "none"
    return ",".join(
        f"{item['talker']}:{item.get('max_cno_dbhz')}"
        for item in talkers
        if isinstance(item, dict) and item.get("talker")
    ) or "none"


def _write_jsonl(path: Path, payloads: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n" for payload in payloads),
        encoding="utf-8",
    )


def _write_json(payload: dict[str, Any], path: Path, *, pretty: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
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
        description="Monitor GNSS C/N0 windows while the operator adjusts Scout antenna placement."
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--port", default="auto")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--window-seconds", type=_positive_float, default=2.0)
    parser.add_argument("--interval-seconds", type=float, default=0.0)
    parser.add_argument("--max-window-count", type=int, default=30)
    parser.add_argument("--allow-overwrite", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = run_signal_monitor(
            output_dir=args.output_dir,
            port=args.port,
            baud=args.baud,
            window_seconds=args.window_seconds,
            interval_seconds=args.interval_seconds,
            max_window_count=args.max_window_count,
            allow_overwrite=args.allow_overwrite,
            pretty=args.pretty,
        )
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=not args.pretty))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
