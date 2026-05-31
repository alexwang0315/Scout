from __future__ import annotations

import argparse
import glob
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.pi_gnss_nmea_smoke import parse_raw_nmea, read_serial_nmea, summarize_gnss_fix, summarize_gnss_signal  # noqa: E402


STOP_ON_VALUES = ("valid_fix", "gps_cno", "any_cno")
GNSS_SERIAL_AUTO_VALUE = "auto"

DEFAULT_GNSS_SERIAL_GLOB_PATTERNS: tuple[tuple[str, str, int], ...] = (
    ("stable_by_id", "/dev/serial/by-id/*", 0),
    ("linux_usb_serial", "/dev/ttyUSB*", 10),
    ("linux_usb_acm", "/dev/ttyACM*", 11),
    ("linux_uart_alias", "/dev/serial0", 30),
    ("linux_uart", "/dev/ttyAMA*", 31),
    ("macos_usb_callout", "/dev/cu.usb*", 40),
    ("macos_silabs_callout", "/dev/cu.SLAB*", 41),
    ("macos_wch_callout", "/dev/cu.wch*", 42),
    ("macos_usb_tty", "/dev/tty.usb*", 50),
    ("macos_silabs_tty", "/dev/tty.SLAB*", 51),
    ("macos_wch_tty", "/dev/tty.wch*", 52),
)


def run_gnss_fix_watch(
    *,
    output_dir: Path,
    gnss_port: Path = Path(GNSS_SERIAL_AUTO_VALUE),
    gnss_baud: int = 115200,
    window_seconds: float = 10.0,
    max_wait_seconds: float = 300.0,
    poll_interval_seconds: float = 2.0,
    stop_on: str = "valid_fix",
    min_gps_cno_dbhz: float = 25.0,
    min_any_cno_dbhz: float = 20.0,
    include_uart: bool = False,
    max_window_count: int | None = None,
    allow_overwrite: bool = False,
    pretty: bool = False,
) -> dict[str, Any]:
    if stop_on not in STOP_ON_VALUES:
        raise ValueError(f"stop_on must be one of {', '.join(STOP_ON_VALUES)}")
    if window_seconds <= 0:
        raise ValueError("window_seconds must be positive")
    if max_wait_seconds <= 0 and max_window_count is None:
        raise ValueError("max_wait_seconds must be positive unless max_window_count is set")
    if poll_interval_seconds < 0:
        raise ValueError("poll_interval_seconds must be non-negative")
    if max_window_count is not None and max_window_count < 1:
        raise ValueError("max_window_count must be at least 1")

    output_dir.mkdir(parents=True, exist_ok=True)
    events_jsonl = output_dir / "gnss-fix-watch-events.jsonl"
    payloads_jsonl = output_dir / "gnss-fix-watch-payloads.jsonl"
    report_json = output_dir / "gnss-fix-watch-report.json"
    conflicts = _artifact_conflicts([events_jsonl, payloads_jsonl, report_json])
    if conflicts and not allow_overwrite:
        raise ValueError(f"output_dir already contains GNSS watch artifacts: {', '.join(conflicts)}")

    resolved_gnss_port, serial_evidence = resolve_requested_gnss_port(
        gnss_port,
        include_uart_serial_candidates=include_uart,
    )
    targets = _watch_targets(
        requested_gnss_port=gnss_port,
        resolved_gnss_port=resolved_gnss_port,
        serial_evidence=serial_evidence,
        baud=gnss_baud,
    )

    events: list[dict[str, Any]] = []
    all_payloads: list[dict[str, Any]] = []
    best_event: dict[str, Any] | None = None
    stop_reason: str | None = None

    start_monotonic = time.monotonic()
    window_index = 0
    while targets and _should_run_window(
        start_monotonic=start_monotonic,
        max_wait_seconds=max_wait_seconds,
        max_window_count=max_window_count,
        window_index=window_index,
    ):
        for target in targets:
            event, payloads = _capture_target_window(
                target=target,
                window_index=window_index,
                window_seconds=window_seconds,
                min_gps_cno_dbhz=min_gps_cno_dbhz,
                min_any_cno_dbhz=min_any_cno_dbhz,
            )
            events.append(event)
            all_payloads.extend(payloads)
            best_event = _better_event(best_event, event)
            if _stop_condition_met(event, stop_on=stop_on):
                stop_reason = stop_on
                break
        window_index += 1
        if stop_reason is not None:
            break
        if _should_run_window(
            start_monotonic=start_monotonic,
            max_wait_seconds=max_wait_seconds,
            max_window_count=max_window_count,
            window_index=window_index,
        ) and poll_interval_seconds > 0:
            time.sleep(poll_interval_seconds)

    _write_jsonl(events_jsonl, events)
    _write_jsonl(payloads_jsonl, all_payloads)

    report = _build_report(
        output_dir=output_dir,
        requested_gnss_port=gnss_port,
        resolved_gnss_port=resolved_gnss_port,
        serial_evidence=serial_evidence,
        targets=targets,
        events=events,
        payloads=all_payloads,
        best_event=best_event,
        stop_on=stop_on,
        stop_reason=stop_reason,
        min_gps_cno_dbhz=min_gps_cno_dbhz,
        min_any_cno_dbhz=min_any_cno_dbhz,
        window_seconds=window_seconds,
        max_wait_seconds=max_wait_seconds,
        poll_interval_seconds=poll_interval_seconds,
        max_window_count=max_window_count,
        events_jsonl=events_jsonl,
        payloads_jsonl=payloads_jsonl,
        report_json=report_json,
    )
    _write_json(report_json, report, pretty=pretty)
    return report


def _watch_targets(
    *,
    requested_gnss_port: Path,
    resolved_gnss_port: Path,
    serial_evidence: dict[str, Any],
    baud: int,
) -> list[dict[str, Any]]:
    if str(requested_gnss_port) != GNSS_SERIAL_AUTO_VALUE:
        return [
            {
                "label": _safe_label(0, "explicit_port", str(requested_gnss_port), baud),
                "path": str(requested_gnss_port),
                "kind": "explicit_port",
                "baud": baud,
            }
        ]
    candidates = serial_evidence.get("candidates") if isinstance(serial_evidence.get("candidates"), list) else []
    if candidates:
        return [
            {
                "label": _safe_label(index, str(candidate.get("kind") or "serial"), str(candidate.get("path")), baud),
                "path": str(candidate.get("path")),
                "kind": candidate.get("kind"),
                "baud": baud,
                "candidate": candidate,
            }
            for index, candidate in enumerate(candidates)
            if candidate.get("path")
        ]
    if resolved_gnss_port.exists():
        return [
            {
                "label": _safe_label(0, "auto_resolved", str(resolved_gnss_port), baud),
                "path": str(resolved_gnss_port),
                "kind": "auto_resolved",
                "baud": baud,
            }
        ]
    return []


def resolve_requested_gnss_port(
    gnss_port: Path,
    *,
    include_uart_serial_candidates: bool = False,
    serial_glob_patterns: Sequence[tuple[str, str, int]] | None = None,
) -> tuple[Path, dict[str, Any]]:
    requested = str(gnss_port)
    if requested != GNSS_SERIAL_AUTO_VALUE:
        return gnss_port, {
            "requested_gnss_port": requested,
            "resolved_gnss_port": str(gnss_port),
            "auto_detection_status": "explicit_port",
            "candidate_count": 0,
            "candidates": [],
        }

    candidates = _filter_gnss_serial_candidates(
        discover_gnss_serial_candidates(serial_glob_patterns=serial_glob_patterns),
        include_uart_serial_candidates=include_uart_serial_candidates,
    )
    if len(candidates) == 1:
        selected = Path(candidates[0]["path"])
        return selected, {
            "requested_gnss_port": requested,
            "resolved_gnss_port": str(selected),
            "auto_detection_status": "selected_unique_candidate",
            "candidate_count": 1,
            "candidates": candidates,
        }
    if not candidates:
        return gnss_port, {
            "requested_gnss_port": requested,
            "resolved_gnss_port": None,
            "auto_detection_status": "no_serial_candidates",
            "candidate_count": 0,
            "candidates": [],
        }
    return gnss_port, {
        "requested_gnss_port": requested,
        "resolved_gnss_port": None,
        "auto_detection_status": "ambiguous_serial_candidates",
        "candidate_count": len(candidates),
        "candidates": candidates,
    }


def discover_gnss_serial_candidates(
    *,
    serial_glob_patterns: Sequence[tuple[str, str, int]] | None = None,
) -> list[dict[str, Any]]:
    patterns = serial_glob_patterns or DEFAULT_GNSS_SERIAL_GLOB_PATTERNS
    candidates: list[dict[str, Any]] = []
    seen_real_paths: set[str] = set()
    for kind, pattern, priority in patterns:
        for raw_path in sorted(glob.glob(pattern)):
            path = Path(raw_path)
            if not path.exists():
                continue
            real_path = str(path.resolve())
            if real_path in seen_real_paths:
                continue
            seen_real_paths.add(real_path)
            candidates.append(
                {
                    "path": str(path),
                    "real_path": real_path,
                    "kind": kind,
                    "priority": priority,
                    "stable_path_preferred": kind == "stable_by_id",
                }
            )
    return sorted(candidates, key=lambda candidate: (candidate["priority"], candidate["path"]))


def _filter_gnss_serial_candidates(
    candidates: list[dict[str, Any]],
    *,
    include_uart_serial_candidates: bool,
) -> list[dict[str, Any]]:
    if include_uart_serial_candidates:
        return candidates
    return [
        candidate
        for candidate in candidates
        if not str(candidate.get("kind", "")).startswith("linux_uart")
    ]


def _capture_target_window(
    *,
    target: dict[str, Any],
    window_index: int,
    window_seconds: float,
    min_gps_cno_dbhz: float,
    min_any_cno_dbhz: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    path = Path(str(target["path"]))
    payloads: list[dict[str, Any]] = []
    capture_status = "captured"
    raw_line_count = 0
    error = None
    if not path.exists():
        capture_status = "skipped_missing_serial"
    else:
        try:
            lines = read_serial_nmea(port=str(path), baud=int(target["baud"]), duration_seconds=window_seconds)
            raw_line_count = len(lines)
            payloads = parse_raw_nmea(
                "\n".join(lines),
                device_port=str(path),
                baud=int(target["baud"]),
                capture_mode="serial_device",
            )
            for payload in payloads:
                payload["watch_window_index"] = window_index
                payload["watch_target_label"] = target["label"]
        except Exception as exc:
            capture_status = "error"
            error = f"{type(exc).__name__}: {exc}"

    fix = summarize_gnss_fix(payloads)
    signal = summarize_gnss_signal(payloads)
    classification = _classify_summary(
        payload_count=len(payloads),
        fix=fix,
        signal=signal,
        capture_status=capture_status,
        min_gps_cno_dbhz=min_gps_cno_dbhz,
        min_any_cno_dbhz=min_any_cno_dbhz,
    )
    event = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": "ins_dr_gnss_fix_watch",
        "artifact_kind": "ins_dr_gnss_fix_watch_window",
        "event_type": "gnss_fix_watch_window",
        "window_index": window_index,
        "target_label": target["label"],
        "gnss_port": str(path),
        "gnss_baud": int(target["baud"]),
        "window_seconds": window_seconds,
        "capture_status": capture_status,
        "raw_line_count": raw_line_count,
        "payload_count": len(payloads),
        "fix": fix,
        "signal": signal,
        "classification": classification,
        "error": error,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_gnss_fix_watch_only",
    }
    return event, payloads


def _classify_summary(
    *,
    payload_count: int,
    fix: dict[str, Any],
    signal: dict[str, Any],
    capture_status: str,
    min_gps_cno_dbhz: float,
    min_any_cno_dbhz: float,
) -> dict[str, Any]:
    valid_fix = int(fix.get("valid_fix_count") or 0) > 0
    gps_max_cno = _float_or_none(signal.get("gps_max_cno_dbhz"))
    max_cno = _float_or_none(signal.get("max_cno_dbhz"))
    gps_cno_ready = gps_max_cno is not None and gps_max_cno >= min_gps_cno_dbhz
    any_cno_ready = max_cno is not None and max_cno >= min_any_cno_dbhz
    gsv_count = int(signal.get("gsv_sentence_count") or 0)

    if capture_status != "captured":
        state = capture_status
        action = "Check GNSS serial path, device permissions, USB hub power, and cabling."
    elif valid_fix:
        state = "valid_fix_observed"
        action = "GNSS has a valid fix; run field readiness or live proof with this selected serial path."
    elif gps_cno_ready:
        state = "gps_cno_observed_without_fix"
        action = "GPS L1 C/N0 is present but fix is not valid yet; keep antenna under open sky and continue waiting."
    elif any_cno_ready:
        state = "rf_signal_observed_without_fix"
        action = "Some satellite C/N0 is present but no valid GPS fix; keep collecting and compare GPS talker C/N0."
    elif payload_count == 0:
        state = "no_nmea_payloads"
        action = "Check baud rate, serial path, receiver power, and whether another process owns the port."
    elif gsv_count > 0:
        state = "no_rf_signal_observed"
        action = "NMEA is alive but C/N0 is absent; inspect antenna, RF path, shielding, placement, and bias."
    else:
        state = "nmea_without_gsv_or_fix"
        action = "NMEA is alive but lacks GSV and fix evidence; check receiver message configuration."

    return {
        "state": state,
        "valid_fix_observed": valid_fix,
        "gps_cno_ready": gps_cno_ready,
        "any_cno_ready": any_cno_ready,
        "min_gps_cno_dbhz": min_gps_cno_dbhz,
        "min_any_cno_dbhz": min_any_cno_dbhz,
        "next_operator_action": action,
    }


def _build_report(
    *,
    output_dir: Path,
    requested_gnss_port: Path,
    resolved_gnss_port: Path,
    serial_evidence: dict[str, Any],
    targets: list[dict[str, Any]],
    events: list[dict[str, Any]],
    payloads: list[dict[str, Any]],
    best_event: dict[str, Any] | None,
    stop_on: str,
    stop_reason: str | None,
    min_gps_cno_dbhz: float,
    min_any_cno_dbhz: float,
    window_seconds: float,
    max_wait_seconds: float,
    poll_interval_seconds: float,
    max_window_count: int | None,
    events_jsonl: Path,
    payloads_jsonl: Path,
    report_json: Path,
) -> dict[str, Any]:
    fix = summarize_gnss_fix(payloads)
    signal = summarize_gnss_signal(payloads)
    classification = _classify_summary(
        payload_count=len(payloads),
        fix=fix,
        signal=signal,
        capture_status="captured" if events else "no_targets",
        min_gps_cno_dbhz=min_gps_cno_dbhz,
        min_any_cno_dbhz=min_any_cno_dbhz,
    )
    watch_status = _watch_status(
        targets=targets,
        events=events,
        classification=classification,
    )
    selected_gnss_port = best_event.get("gnss_port") if best_event and _event_has_valid_fix(best_event) else None
    best_observed_gnss_port = best_event.get("gnss_port") if best_event else None
    watch_goal_satisfied = stop_reason is not None
    window_stability = _window_stability_summary(events)
    return {
        "source": "ins_dr_gnss_fix_watch",
        "artifact_kind": "ins_dr_gnss_fix_watch_report",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "watch_status": watch_status,
        "watch_goal_satisfied": watch_goal_satisfied,
        "stop_on": stop_on,
        "stop_reason": stop_reason or "timeout_or_no_targets",
        "ready_for_live_field_proof": selected_gnss_port is not None,
        "requested_gnss_port": str(requested_gnss_port),
        "resolved_gnss_port": str(resolved_gnss_port) if str(resolved_gnss_port) != GNSS_SERIAL_AUTO_VALUE else None,
        "selected_gnss_port": selected_gnss_port,
        "best_observed_gnss_port": best_observed_gnss_port,
        "best_observed_target_label": best_event.get("target_label") if best_event else None,
        "serial_evidence": serial_evidence,
        "target_count": len(targets),
        "targets": targets,
        "gnss_baud": targets[0]["baud"] if targets else None,
        "window_stability": window_stability,
        "intermittent_rf_observed": window_stability["intermittent_rf_observed"],
        "valid_fix_window_count": window_stability["valid_fix_window_count"],
        "gps_cno_window_count": window_stability["gps_cno_window_count"],
        "any_cno_window_count": window_stability["any_cno_window_count"],
        "no_rf_window_count": window_stability["no_rf_window_count"],
        "window_seconds": window_seconds,
        "max_wait_seconds": max_wait_seconds,
        "poll_interval_seconds": poll_interval_seconds,
        "max_window_count": max_window_count,
        "window_event_count": len(events),
        "payload_count": len(payloads),
        "valid_fix_count": fix.get("valid_fix_count"),
        "max_cno_dbhz": signal.get("max_cno_dbhz"),
        "gps_max_cno_dbhz": signal.get("gps_max_cno_dbhz"),
        "nonzero_cno_count": signal.get("nonzero_cno_count"),
        "gps_nonzero_cno_count": signal.get("gps_nonzero_cno_count"),
        "talker_signal_summary": signal.get("talker_signal_summary"),
        "talkers_with_cno": signal.get("talkers_with_cno"),
        "best_talker": signal.get("best_talker"),
        "best_talker_cno_dbhz": signal.get("best_talker_cno_dbhz"),
        "fix": fix,
        "signal": signal,
        "classification": classification,
        "events_jsonl": str(events_jsonl),
        "payloads_jsonl": str(payloads_jsonl),
        "report_json": str(report_json),
        "output_dir": str(output_dir),
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_gnss_fix_watch_only",
    }


def _watch_status(*, targets: list[dict[str, Any]], events: list[dict[str, Any]], classification: dict[str, Any]) -> str:
    if not targets:
        return "no_serial_candidates"
    state = classification["state"]
    if state == "valid_fix_observed":
        return "valid_fix_observed"
    if state == "gps_cno_observed_without_fix":
        return "gps_cno_observed_without_fix"
    if state == "rf_signal_observed_without_fix":
        return "rf_signal_observed_without_fix"
    if not events:
        return "no_capture_windows"
    if state == "no_nmea_payloads":
        return "timed_out_no_nmea_payloads"
    if state == "no_rf_signal_observed":
        return "timed_out_no_rf_signal"
    return f"timed_out_{state}"


def _window_stability_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    state_counts: dict[str, int] = {}
    capture_status_counts: dict[str, int] = {}
    talker_counts: dict[str, int] = {}
    talker_signal_summary: dict[str, dict[str, Any]] = {}
    windows: list[dict[str, Any]] = []
    max_cno_values: list[int] = []
    gps_max_cno_values: list[int] = []

    for event in events:
        classification = event.get("classification") if isinstance(event.get("classification"), dict) else {}
        signal = event.get("signal") if isinstance(event.get("signal"), dict) else {}
        fix = event.get("fix") if isinstance(event.get("fix"), dict) else {}
        state = str(classification.get("state") or "unknown")
        capture_status = str(event.get("capture_status") or "unknown")
        state_counts[state] = state_counts.get(state, 0) + 1
        capture_status_counts[capture_status] = capture_status_counts.get(capture_status, 0) + 1

        for talker, count in (signal.get("talker_counts") or {}).items():
            talker_counts[str(talker)] = talker_counts.get(str(talker), 0) + int(count or 0)
        _merge_talker_signal_summary(talker_signal_summary, signal.get("talker_signal_summary"))

        max_cno = _int_or_none(signal.get("max_cno_dbhz"))
        gps_max_cno = _int_or_none(signal.get("gps_max_cno_dbhz"))
        if max_cno is not None:
            max_cno_values.append(max_cno)
        if gps_max_cno is not None:
            gps_max_cno_values.append(gps_max_cno)

        windows.append(
            {
                "window_index": event.get("window_index"),
                "target_label": event.get("target_label"),
                "gnss_port": event.get("gnss_port"),
                "capture_status": capture_status,
                "state": state,
                "payload_count": event.get("payload_count"),
                "valid_fix_count": fix.get("valid_fix_count"),
                "reported_visible_satellites": signal.get("reported_visible_satellites"),
                "nonzero_cno_count": signal.get("nonzero_cno_count"),
                "max_cno_dbhz": max_cno,
                "gps_nonzero_cno_count": signal.get("gps_nonzero_cno_count"),
                "gps_max_cno_dbhz": gps_max_cno,
                "talker_signal_summary": signal.get("talker_signal_summary"),
                "talkers_with_cno": signal.get("talkers_with_cno"),
                "best_talker": signal.get("best_talker"),
                "best_talker_cno_dbhz": signal.get("best_talker_cno_dbhz"),
            }
        )

    valid_fix_window_count = sum(1 for window in windows if int(window.get("valid_fix_count") or 0) > 0)
    gps_cno_window_count = sum(1 for window in windows if window.get("gps_max_cno_dbhz") is not None)
    any_cno_window_count = sum(1 for window in windows if window.get("max_cno_dbhz") is not None)
    no_rf_window_count = sum(1 for window in windows if window.get("state") == "no_rf_signal_observed")
    no_nmea_window_count = sum(1 for window in windows if window.get("state") == "no_nmea_payloads")
    error_window_count = sum(1 for window in windows if window.get("capture_status") == "error")
    talkers_with_cno = _talkers_with_cno(talker_signal_summary)
    best_talker = talkers_with_cno[0] if talkers_with_cno else None

    return {
        "source": "ins_dr_gnss_fix_watch",
        "artifact_kind": "ins_dr_gnss_window_stability_summary",
        "window_count": len(events),
        "state_counts": state_counts,
        "capture_status_counts": capture_status_counts,
        "talker_counts": talker_counts,
        "talker_signal_summary": talker_signal_summary,
        "talkers_with_cno": talkers_with_cno,
        "best_talker": best_talker["talker"] if best_talker else None,
        "best_talker_cno_dbhz": best_talker["max_cno_dbhz"] if best_talker else None,
        "valid_fix_window_count": valid_fix_window_count,
        "gps_cno_window_count": gps_cno_window_count,
        "any_cno_window_count": any_cno_window_count,
        "no_rf_window_count": no_rf_window_count,
        "no_nmea_window_count": no_nmea_window_count,
        "error_window_count": error_window_count,
        "intermittent_rf_observed": any_cno_window_count > 0 and no_rf_window_count > 0,
        "max_cno_dbhz": max(max_cno_values) if max_cno_values else None,
        "gps_max_cno_dbhz": max(gps_max_cno_values) if gps_max_cno_values else None,
        "windows": windows,
    }


def _merge_talker_signal_summary(aggregate: dict[str, dict[str, Any]], source: Any) -> None:
    if not isinstance(source, dict):
        return
    for talker, summary in sorted(source.items()):
        if not isinstance(summary, dict):
            continue
        bucket = aggregate.setdefault(
            str(talker),
            {
                "window_count": 0,
                "gsv_sentence_count": 0,
                "reported_visible_satellites": None,
                "parsed_satellites": 0,
                "nonzero_cno_count": 0,
                "nonzero_cno_window_count": 0,
                "max_cno_dbhz": None,
                "rf_signal_observed": False,
            },
        )
        bucket["window_count"] += 1
        bucket["gsv_sentence_count"] += int(summary.get("gsv_sentence_count") or 0)
        bucket["parsed_satellites"] += int(summary.get("parsed_satellites") or 0)
        nonzero_cno_count = int(summary.get("nonzero_cno_count") or 0)
        bucket["nonzero_cno_count"] += nonzero_cno_count
        if nonzero_cno_count > 0:
            bucket["nonzero_cno_window_count"] += 1
            bucket["rf_signal_observed"] = True
        if (visible := _int_or_none(summary.get("reported_visible_satellites"))) is not None:
            bucket["reported_visible_satellites"] = max(int(bucket["reported_visible_satellites"] or 0), visible)
        if (max_cno := _int_or_none(summary.get("max_cno_dbhz"))) is not None:
            bucket["max_cno_dbhz"] = max(int(bucket["max_cno_dbhz"] or 0), max_cno)


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
                "nonzero_cno_window_count": summary.get("nonzero_cno_window_count"),
            }
        )
    return sorted(talkers, key=lambda item: (int(item.get("max_cno_dbhz") or 0), item["talker"]), reverse=True)


def _should_run_window(
    *,
    start_monotonic: float,
    max_wait_seconds: float,
    max_window_count: int | None,
    window_index: int,
) -> bool:
    if max_window_count is not None:
        return window_index < max_window_count
    return time.monotonic() - start_monotonic < max_wait_seconds


def _better_event(current: dict[str, Any] | None, candidate: dict[str, Any]) -> dict[str, Any]:
    if current is None:
        return candidate
    return candidate if _event_score(candidate) > _event_score(current) else current


def _event_score(event: dict[str, Any]) -> tuple[int, float, float, int]:
    fix = event.get("fix") if isinstance(event.get("fix"), dict) else {}
    signal = event.get("signal") if isinstance(event.get("signal"), dict) else {}
    return (
        int(fix.get("valid_fix_count") or 0),
        float(signal.get("gps_max_cno_dbhz") or 0),
        float(signal.get("max_cno_dbhz") or 0),
        int(event.get("payload_count") or 0),
    )


def _stop_condition_met(event: dict[str, Any], *, stop_on: str) -> bool:
    classification = event.get("classification") if isinstance(event.get("classification"), dict) else {}
    if stop_on == "valid_fix":
        return bool(classification.get("valid_fix_observed"))
    if stop_on == "gps_cno":
        return bool(classification.get("valid_fix_observed") or classification.get("gps_cno_ready"))
    if stop_on == "any_cno":
        return bool(
            classification.get("valid_fix_observed")
            or classification.get("gps_cno_ready")
            or classification.get("any_cno_ready")
        )
    return False


def _event_has_valid_fix(event: dict[str, Any]) -> bool:
    classification = event.get("classification") if isinstance(event.get("classification"), dict) else {}
    return bool(classification.get("valid_fix_observed"))


def _artifact_conflicts(paths: list[Path]) -> list[str]:
    return sorted(path.name for path in paths if path.exists())


def _safe_label(index: int, kind: str, path: str, baud: int) -> str:
    raw = f"watch_{index}_{kind}_{Path(path).name}_{baud}"
    return re.sub(r"[^A-Za-z0-9_]+", "_", raw).strip("_")[:96] or f"watch_{index}"


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _write_jsonl(path: Path, payloads: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n" for payload in payloads),
        encoding="utf-8",
    )


def _write_json(path: Path, payload: dict[str, Any], *, pretty: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2 if pretty else None, sort_keys=not pretty) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Watch raw GNSS NMEA until Scout has a valid fix or usable C/N0 evidence.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--gnss-port", type=Path, default=Path(GNSS_SERIAL_AUTO_VALUE))
    parser.add_argument("--gnss-baud", type=int, default=115200)
    parser.add_argument("--window-seconds", type=float, default=10.0)
    parser.add_argument("--max-wait-seconds", type=float, default=300.0)
    parser.add_argument("--poll-interval-seconds", type=float, default=2.0)
    parser.add_argument("--stop-on", choices=STOP_ON_VALUES, default="valid_fix")
    parser.add_argument("--min-gps-cno-dbhz", type=float, default=25.0)
    parser.add_argument("--min-any-cno-dbhz", type=float, default=20.0)
    parser.add_argument("--include-uart", action="store_true")
    parser.add_argument("--max-window-count", type=int)
    parser.add_argument("--allow-overwrite", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = run_gnss_fix_watch(
            output_dir=args.output_dir,
            gnss_port=args.gnss_port,
            gnss_baud=args.gnss_baud,
            window_seconds=args.window_seconds,
            max_wait_seconds=args.max_wait_seconds,
            poll_interval_seconds=args.poll_interval_seconds,
            stop_on=args.stop_on,
            min_gps_cno_dbhz=args.min_gps_cno_dbhz,
            min_any_cno_dbhz=args.min_any_cno_dbhz,
            include_uart=args.include_uart,
            max_window_count=args.max_window_count,
            allow_overwrite=args.allow_overwrite,
            pretty=args.pretty,
        )
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=not args.pretty))
    return 0 if report["watch_goal_satisfied"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
