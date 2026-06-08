from __future__ import annotations

import argparse
import glob
import json
import os
import re
import select
import sys
import termios
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CaptureTarget:
    label: str
    device_port: str
    baud: int


DEFAULT_SERIAL_DISCOVERY_PATTERNS: tuple[tuple[str, str, int], ...] = (
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


def nmea_checksum_valid(line: str) -> bool | None:
    stripped = line.strip()
    if not stripped.startswith("$") or "*" not in stripped:
        return None
    body, checksum = stripped[1:].split("*", 1)
    checksum = checksum[:2]
    value = 0
    for character in body:
        value ^= ord(character)
    try:
        return value == int(checksum, 16)
    except ValueError:
        return False


def parse_nmea_capture(
    raw_text: str,
    *,
    label: str,
    device_port: str | None = None,
    baud: int | None = None,
) -> dict[str, Any]:
    lines = [line.strip() for line in raw_text.replace("\r", "\n").splitlines() if line.strip().startswith("$")]
    valid_lines = [line for line in lines if nmea_checksum_valid(line) is True]
    invalid_lines = [line for line in lines if nmea_checksum_valid(line) is False]

    sentence_counts: Counter[str] = Counter()
    valid_sentence_counts: Counter[str] = Counter()
    last_by_type: dict[str, str] = {}
    valid_last_by_type: dict[str, str] = {}
    valid_gga: list[dict[str, Any]] = []
    valid_rmc: list[dict[str, Any]] = []
    txt_messages: list[str] = []
    gsv_by_talker: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "gsv_lines": 0,
            "visible_values": [],
            "cno_values": [],
            "examples": [],
        }
    )

    for line in lines:
        sentence_type = _sentence_type(line)
        if sentence_type is None:
            continue
        sentence_counts[sentence_type] += 1
        last_by_type[sentence_type] = line

    for line in valid_lines:
        sentence_type = _sentence_type(line)
        if sentence_type is None:
            continue
        valid_sentence_counts[sentence_type] += 1
        valid_last_by_type[sentence_type] = line
        fields = _nmea_fields(line)
        if not fields:
            continue
        if sentence_type == "GGA":
            gga = _parse_gga(fields, line)
            if gga is not None:
                valid_gga.append(gga)
        elif sentence_type == "RMC":
            rmc = _parse_rmc(fields, line)
            if rmc is not None:
                valid_rmc.append(rmc)
        elif sentence_type == "GSV":
            _collect_gsv(fields, line, gsv_by_talker)
        elif sentence_type == "TXT":
            message = ",".join(fields[4:]).strip() if len(fields) > 4 else ""
            if message:
                txt_messages.append(message)

    gsv_summary = {
        talker: _summarize_talker_gsv(data)
        for talker, data in sorted(gsv_by_talker.items())
    }
    any_nonzero_cno = any(
        talker["nonzero_cno_count"] > 0
        for talker in gsv_summary.values()
    )
    gp_summary = gsv_summary.get("GP", {})
    gps_nonzero_cno = int(gp_summary.get("nonzero_cno_count") or 0)

    return {
        "source": "pi_gnss_ab_compare",
        "hardware_kind": "multi_gnss_nmea_ab_compare",
        "hardware_control_scope": "diagnostic_read_only_nmea",
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "label": label,
        "device_port": device_port,
        "baud": baud,
        "nmea_lines": len(lines),
        "valid_checksum_lines": len(valid_lines),
        "invalid_checksum_lines": len(invalid_lines),
        "sentence_counts": dict(sentence_counts),
        "valid_sentence_counts": dict(valid_sentence_counts),
        "last_GGA": valid_last_by_type.get("GGA") or last_by_type.get("GGA"),
        "last_RMC": valid_last_by_type.get("RMC") or last_by_type.get("RMC"),
        "last_GSA": valid_last_by_type.get("GSA") or last_by_type.get("GSA"),
        "last_GSV": valid_last_by_type.get("GSV") or last_by_type.get("GSV"),
        "last_TXT": valid_last_by_type.get("TXT") or last_by_type.get("TXT"),
        "valid_GGA_count": len(valid_gga),
        "valid_RMC_count": len(valid_rmc),
        "first_valid_GGA": valid_gga[0] if valid_gga else None,
        "last_valid_GGA": valid_gga[-1] if valid_gga else None,
        "first_valid_RMC": valid_rmc[0] if valid_rmc else None,
        "last_valid_RMC": valid_rmc[-1] if valid_rmc else None,
        "txt_messages": txt_messages,
        "antenna_text_status": _antenna_text_status(txt_messages),
        "gsv_by_talker": gsv_summary,
        "summary": {
            "fix_observed": bool(valid_gga or valid_rmc),
            "any_rf_signal_observed": any_nonzero_cno,
            "gps_rf_signal_observed": gps_nonzero_cno > 0,
            "non_gps_rf_signal_observed": any_nonzero_cno and gps_nonzero_cno == 0,
            "max_cno_dbhz": _max_cno(gsv_summary),
            "gps_max_cno_dbhz": gp_summary.get("cno_max"),
            "likely_state": _likely_state(
                nmea_lines=len(lines),
                fix_observed=bool(valid_gga or valid_rmc),
                any_nonzero_cno=any_nonzero_cno,
                gps_nonzero_cno=gps_nonzero_cno,
            ),
        },
    }


def build_ab_payload(captures: list[dict[str, Any]], *, duration_seconds: float | None = None) -> dict[str, Any]:
    by_label = {capture["label"]: capture for capture in captures}
    return {
        "source": "pi_gnss_ab_compare",
        "hardware_kind": "multi_gnss_nmea_ab_compare",
        "hardware_control_scope": "diagnostic_read_only_nmea",
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": duration_seconds,
        "capture_count": len(captures),
        "captures": by_label,
        "comparison": _compare_captures(by_label),
    }


def capture_serial_targets(targets: list[CaptureTarget], *, duration_seconds: float) -> list[dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    threads = [
        threading.Thread(
            target=_capture_one_target,
            args=(target, duration_seconds, results),
            daemon=True,
        )
        for target in targets
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return [results[target.label] for target in targets]


def discover_serial_candidates(
    *,
    serial_glob_patterns: list[tuple[str, str, int]] | tuple[tuple[str, str, int], ...] | None = None,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen_real_paths: set[str] = set()
    for kind, pattern, priority in serial_glob_patterns or DEFAULT_SERIAL_DISCOVERY_PATTERNS:
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


def build_auto_capture_targets(
    *,
    baud: int,
    serial_candidates: list[dict[str, Any]],
) -> list[CaptureTarget]:
    targets: list[CaptureTarget] = []
    for index, candidate in enumerate(serial_candidates):
        raw_name = f"auto_{index}_{candidate['kind']}_{Path(candidate['path']).name}_{baud}"
        label = _safe_label(raw_name)
        targets.append(CaptureTarget(label=label, device_port=candidate["path"], baud=baud))
    return targets


def capture_auto_serial_candidates(
    *,
    bauds: list[int],
    duration_seconds: float,
    include_uart: bool = False,
    serial_glob_patterns: list[tuple[str, str, int]] | tuple[tuple[str, str, int], ...] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates = _auto_capture_candidates(
        discover_serial_candidates(serial_glob_patterns=serial_glob_patterns),
        include_uart=include_uart,
    )
    captures: list[dict[str, Any]] = []
    for baud in bauds:
        targets = build_auto_capture_targets(baud=baud, serial_candidates=candidates)
        captures.extend(capture_serial_targets(targets, duration_seconds=duration_seconds))
    return captures, candidates


def capture_placement_sweep(
    *,
    placements: list[str],
    port: str,
    baud: int,
    duration_seconds: float,
    settle_seconds: float = 0.0,
    serial_candidates: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not placements:
        raise ValueError("at least one placement label is required")
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")
    if settle_seconds < 0:
        raise ValueError("settle_seconds must be non-negative")
    resolved_port, resolution = _resolve_placement_port(port, serial_candidates=serial_candidates)
    captures: list[dict[str, Any]] = []
    for index, placement in enumerate(placements):
        label = _safe_label(f"placement_{index}_{placement}")
        if settle_seconds > 0:
            print(
                f"[gnss-placement] Move antenna/receiver to {placement!r}; capturing in {settle_seconds:g}s.",
                file=sys.stderr,
            )
            time.sleep(settle_seconds)
        raw = read_serial_bytes(resolved_port, baud, duration_seconds=duration_seconds)
        capture = parse_nmea_capture(
            raw.decode("ascii", "replace"),
            label=label,
            device_port=resolved_port,
            baud=baud,
        )
        capture["placement_label"] = placement
        capture["placement_index"] = index
        capture["settle_seconds"] = settle_seconds
        capture["raw_bytes"] = len(raw)
        captures.append(capture)
    return captures, resolution


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare multiple GNSS NMEA streams as read-only A/B evidence.")
    parser.add_argument(
        "--capture",
        action="append",
        default=[],
        help="Serial capture target in LABEL=/dev/ttyX:BAUD form. May be repeated.",
    )
    parser.add_argument(
        "--raw-file",
        action="append",
        default=[],
        help="Parse existing raw NMEA in LABEL=/path/to/file form. May be repeated.",
    )
    parser.add_argument(
        "--auto-capture",
        action="store_true",
        help="Capture every discovered local serial candidate as read-only GNSS A/B evidence.",
    )
    parser.add_argument(
        "--auto-baud",
        type=int,
        action="append",
        default=[],
        help="Baud rate for --auto-capture. May be repeated. Defaults to 115200.",
    )
    parser.add_argument(
        "--include-uart",
        action="store_true",
        help="Include non-USB UART candidates such as /dev/serial0 in --auto-capture.",
    )
    parser.add_argument(
        "--placement",
        action="append",
        default=[],
        help="Sequential same-receiver placement label to capture. Repeat for current/window/outdoor comparisons.",
    )
    parser.add_argument(
        "--placement-port",
        default="auto",
        help="Serial port for --placement sweep. Defaults to first stable auto candidate.",
    )
    parser.add_argument("--placement-baud", type=int, default=115200)
    parser.add_argument(
        "--placement-settle-seconds",
        type=float,
        default=0.0,
        help="Seconds to wait before each placement capture so the operator can move antenna/receiver.",
    )
    parser.add_argument("--duration-seconds", type=float, default=180.0)
    parser.add_argument("--output-json", help="Optional path to persist the comparison JSON.")
    args = parser.parse_args()

    captures: list[dict[str, Any]] = []
    auto_serial_candidates: list[dict[str, Any]] | None = None
    if args.auto_capture:
        auto_captures, auto_serial_candidates = capture_auto_serial_candidates(
            bauds=args.auto_baud or [115200],
            duration_seconds=args.duration_seconds,
            include_uart=args.include_uart,
        )
        captures.extend(auto_captures)
    placement_resolution: dict[str, Any] | None = None
    if args.placement:
        placement_captures, placement_resolution = capture_placement_sweep(
            placements=args.placement,
            port=args.placement_port,
            baud=args.placement_baud,
            duration_seconds=args.duration_seconds,
            settle_seconds=args.placement_settle_seconds,
        )
        captures.extend(placement_captures)
    if args.capture:
        targets = [_parse_capture_target(spec) for spec in args.capture]
        for capture in capture_serial_targets(targets, duration_seconds=args.duration_seconds):
            captures.append(capture)
    for spec in args.raw_file:
        label, path = _parse_raw_file_spec(spec)
        raw = path.read_bytes().decode("ascii", "replace")
        capture = parse_nmea_capture(raw, label=label)
        capture["raw_file"] = str(path)
        capture["raw_bytes"] = path.stat().st_size
        captures.append(capture)

    payload = build_ab_payload(
        captures,
        duration_seconds=args.duration_seconds if args.capture or args.auto_capture else None,
    )
    if auto_serial_candidates is not None:
        payload["auto_serial_candidates"] = auto_serial_candidates
        payload["auto_serial_candidate_count"] = len(auto_serial_candidates)
    if placement_resolution is not None:
        payload["placement_resolution"] = placement_resolution
        payload["placement_sweep"] = _placement_sweep_summary(captures)
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text + "\n")
    print(text)
    return 0


def _capture_one_target(
    target: CaptureTarget,
    duration_seconds: float,
    results: dict[str, dict[str, Any]],
) -> None:
    try:
        raw = read_serial_bytes(target.device_port, target.baud, duration_seconds=duration_seconds)
        capture = parse_nmea_capture(
            raw.decode("ascii", "replace"),
            label=target.label,
            device_port=target.device_port,
            baud=target.baud,
        )
        capture["raw_bytes"] = len(raw)
        results[target.label] = capture
    except Exception as exc:  # pragma: no cover - exercised on real hardware.
        results[target.label] = {
            "source": "pi_gnss_ab_compare",
            "label": target.label,
            "device_port": target.device_port,
            "baud": target.baud,
            "error": repr(exc),
            "summary": {"likely_state": "capture_error"},
        }


def _resolve_placement_port(
    port: str,
    *,
    serial_candidates: list[dict[str, Any]] | None = None,
) -> tuple[str, dict[str, Any]]:
    if port != "auto":
        return port, {
            "requested_port": port,
            "resolved_port": port,
            "resolution_status": "explicit_port",
        }
    candidates = serial_candidates if serial_candidates is not None else discover_serial_candidates()
    if not candidates:
        raise ValueError("no serial candidates found for placement sweep")
    chosen = candidates[0]
    return str(chosen["path"]), {
        "requested_port": "auto",
        "resolved_port": str(chosen["path"]),
        "resolution_status": "selected_first_serial_candidate",
        "candidate_count": len(candidates),
        "candidate": chosen,
        "candidates": candidates,
    }


def _placement_sweep_summary(captures: list[dict[str, Any]]) -> dict[str, Any]:
    placement_captures = [capture for capture in captures if capture.get("placement_label") is not None]
    ranked = sorted(
        placement_captures,
        key=lambda capture: (
            int(bool(capture.get("summary", {}).get("fix_observed"))),
            int(bool(capture.get("summary", {}).get("gps_rf_signal_observed"))),
            int(capture.get("summary", {}).get("gps_max_cno_dbhz") or 0),
            int(capture.get("summary", {}).get("max_cno_dbhz") or 0),
            int(capture.get("valid_checksum_lines") or 0),
        ),
        reverse=True,
    )
    best = ranked[0] if ranked else None
    return {
        "source": "pi_gnss_ab_compare",
        "artifact_kind": "gnss_placement_sweep_summary",
        "placement_count": len(placement_captures),
        "best_placement_label": best.get("placement_label") if best else None,
        "best_placement_capture_label": best.get("label") if best else None,
        "best_likely_state": best.get("summary", {}).get("likely_state") if best else None,
        "best_gps_max_cno_dbhz": best.get("summary", {}).get("gps_max_cno_dbhz") if best else None,
        "best_max_cno_dbhz": best.get("summary", {}).get("max_cno_dbhz") if best else None,
        "placements_with_fix": [
            capture["placement_label"]
            for capture in placement_captures
            if capture.get("summary", {}).get("fix_observed") is True
        ],
        "placements_with_gps_rf_signal": [
            capture["placement_label"]
            for capture in placement_captures
            if capture.get("summary", {}).get("gps_rf_signal_observed") is True
        ],
        "placements_with_any_rf_signal": [
            capture["placement_label"]
            for capture in placement_captures
            if capture.get("summary", {}).get("any_rf_signal_observed") is True
        ],
        "ranked_placements": [
            {
                "placement_label": capture.get("placement_label"),
                "capture_label": capture.get("label"),
                "likely_state": capture.get("summary", {}).get("likely_state"),
                "fix_observed": capture.get("summary", {}).get("fix_observed"),
                "gps_rf_signal_observed": capture.get("summary", {}).get("gps_rf_signal_observed"),
                "any_rf_signal_observed": capture.get("summary", {}).get("any_rf_signal_observed"),
                "gps_max_cno_dbhz": capture.get("summary", {}).get("gps_max_cno_dbhz"),
                "max_cno_dbhz": capture.get("summary", {}).get("max_cno_dbhz"),
            }
            for capture in ranked
        ],
    }


def read_serial_bytes(port: str, baud: int, *, duration_seconds: float) -> bytes:
    baud_constant = _termios_baud_constant(baud)
    fd = os.open(port, os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        attrs = termios.tcgetattr(fd)
        attrs[0] = termios.IGNPAR
        attrs[1] = 0
        attrs[2] = baud_constant | termios.CS8 | termios.CLOCAL | termios.CREAD
        attrs[3] = 0
        attrs[4] = baud_constant
        attrs[5] = baud_constant
        attrs[6][termios.VMIN] = 0
        attrs[6][termios.VTIME] = 2
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        termios.tcflush(fd, termios.TCIFLUSH)

        chunks: list[bytes] = []
        deadline = time.monotonic() + duration_seconds
        while time.monotonic() < deadline:
            timeout = max(0.0, min(0.2, deadline - time.monotonic()))
            readable, _, _ = select.select([fd], [], [], timeout)
            if not readable:
                continue
            try:
                chunk = os.read(fd, 4096)
            except BlockingIOError:
                continue
            if chunk:
                chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _sentence_type(line: str) -> str | None:
    fields = _nmea_fields(line)
    if not fields or len(fields[0]) < 5:
        return None
    return fields[0][-3:]


def _nmea_fields(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("$"):
        return []
    body = stripped[1:].split("*", 1)[0]
    return body.split(",")


def _parse_gga(fields: list[str], line: str) -> dict[str, Any] | None:
    if len(fields) <= 7 or fields[6] in ("", "0"):
        return None
    return {
        "line": line,
        "time_utc": fields[1] if len(fields) > 1 else "",
        "fix_quality": _safe_int(fields[6]),
        "satellites_used": _safe_int(fields[7]),
        "hdop": _safe_float(fields[8]) if len(fields) > 8 else None,
        "altitude_m": _safe_float(fields[9]) if len(fields) > 9 else None,
    }


def _parse_rmc(fields: list[str], line: str) -> dict[str, Any] | None:
    if len(fields) <= 2 or fields[2] != "A":
        return None
    return {
        "line": line,
        "time_utc": fields[1] if len(fields) > 1 else "",
        "status": fields[2],
        "lat": fields[3] if len(fields) > 3 else "",
        "ns": fields[4] if len(fields) > 4 else "",
        "lon": fields[5] if len(fields) > 5 else "",
        "ew": fields[6] if len(fields) > 6 else "",
    }


def _collect_gsv(fields: list[str], line: str, by_talker: dict[str, dict[str, Any]]) -> None:
    if not fields or fields[0][-3:] != "GSV":
        return
    talker = fields[0][:-3]
    data = by_talker[talker]
    data["gsv_lines"] += 1
    visible = _safe_int(fields[3]) if len(fields) > 3 else None
    if visible is not None:
        data["visible_values"].append(visible)

    line_has_nonzero_cno = False
    for offset in range(4, len(fields) - 3, 4):
        svid = fields[offset]
        if not svid:
            continue
        cno = _safe_int(fields[offset + 3])
        if cno is None:
            continue
        data["cno_values"].append(cno)
        if cno > 0:
            line_has_nonzero_cno = True
    if line_has_nonzero_cno and len(data["examples"]) < 10:
        data["examples"].append(line)


def _summarize_talker_gsv(data: dict[str, Any]) -> dict[str, Any]:
    visible_values = data["visible_values"]
    cno_values = data["cno_values"]
    return {
        "gsv_lines": data["gsv_lines"],
        "visible_max": max(visible_values) if visible_values else None,
        "visible_values_sample": visible_values[:10],
        "nonzero_cno_count": sum(1 for value in cno_values if value > 0),
        "cno_max": max(cno_values) if cno_values else None,
        "examples": data["examples"],
    }


def _compare_captures(captures: dict[str, dict[str, Any]]) -> dict[str, Any]:
    labels_with_fix = [
        label
        for label, capture in captures.items()
        if capture.get("summary", {}).get("fix_observed") is True
    ]
    labels_with_gps_rf = [
        label
        for label, capture in captures.items()
        if capture.get("summary", {}).get("gps_rf_signal_observed") is True
    ]
    labels_with_any_rf = [
        label
        for label, capture in captures.items()
        if capture.get("summary", {}).get("any_rf_signal_observed") is True
    ]
    return {
        "labels_with_fix": labels_with_fix,
        "labels_with_gps_rf_signal": labels_with_gps_rf,
        "labels_with_any_rf_signal": labels_with_any_rf,
        "gps_ab_discriminates_hardware": len(labels_with_gps_rf) > 0,
        "interpretation": _comparison_interpretation(
            labels_with_fix=labels_with_fix,
            labels_with_gps_rf=labels_with_gps_rf,
            labels_with_any_rf=labels_with_any_rf,
        ),
    }


def _comparison_interpretation(
    *,
    labels_with_fix: list[str],
    labels_with_gps_rf: list[str],
    labels_with_any_rf: list[str],
) -> str:
    if labels_with_fix:
        return "fix_observed_on_at_least_one_receiver"
    if labels_with_gps_rf:
        return "gps_rf_available_for_ab_hardware_comparison"
    if labels_with_any_rf:
        return "non_gps_rf_observed_but_gps_l1_not_available_for_gps_only_ab"
    return "no_rf_signal_observed_on_any_receiver"


def _likely_state(
    *,
    nmea_lines: int,
    fix_observed: bool,
    any_nonzero_cno: bool,
    gps_nonzero_cno: int,
) -> str:
    if nmea_lines == 0:
        return "no_nmea_stream"
    if fix_observed:
        return "fix_observed"
    if gps_nonzero_cno > 0:
        return "gps_rf_signal_observed_no_fix"
    if any_nonzero_cno:
        return "non_gps_rf_signal_observed_no_fix"
    return "no_rf_signal_observed"


def _max_cno(gsv_summary: dict[str, dict[str, Any]]) -> int | None:
    values = [summary["cno_max"] for summary in gsv_summary.values() if summary.get("cno_max") is not None]
    return max(values) if values else None


def _antenna_text_status(messages: list[str]) -> str | None:
    joined = " ".join(messages).upper()
    if "ANTENNA OK" in joined:
        return "OK"
    if "ANTENNA SHORT" in joined:
        return "SHORT"
    if "ANTENNA OPEN" in joined:
        return "OPEN"
    if "ANTENNA" in joined:
        return "UNKNOWN"
    return None


def _parse_capture_target(spec: str) -> CaptureTarget:
    if "=" not in spec or ":" not in spec:
        raise ValueError("--capture must use LABEL=/dev/ttyX:BAUD")
    label, rest = spec.split("=", 1)
    port, baud_text = rest.rsplit(":", 1)
    return CaptureTarget(label=label, device_port=port, baud=int(baud_text))


def _parse_raw_file_spec(spec: str) -> tuple[str, Path]:
    if "=" not in spec:
        raise ValueError("--raw-file must use LABEL=/path/to/file")
    label, path = spec.split("=", 1)
    return label, Path(path)


def _auto_capture_candidates(candidates: list[dict[str, Any]], *, include_uart: bool) -> list[dict[str, Any]]:
    if include_uart:
        return candidates
    return [
        candidate
        for candidate in candidates
        if not str(candidate.get("kind", "")).startswith("linux_uart")
    ]


def _safe_label(value: str) -> str:
    label = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_")
    return label[:96] or "auto_serial"


def _safe_int(value: str) -> int | None:
    if value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _safe_float(value: str) -> float | None:
    if value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _termios_baud_constant(baud: int) -> int:
    name = f"B{baud}"
    if not hasattr(termios, name):
        raise ValueError(f"unsupported baud rate: {baud}")
    return getattr(termios, name)


if __name__ == "__main__":
    raise SystemExit(main())
