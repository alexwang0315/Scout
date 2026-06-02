from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from tools.pi_oled_i2c_smoke import parse_address, write_display
except ImportError:  # pragma: no cover - used when executed directly from tools/ on a Pi.
    from pi_oled_i2c_smoke import parse_address, write_display

try:
    from tools.pi_grove_led_bar_smoke import DEFAULT_PORT, PORT_DEFAULTS, clear_led_bar, make_gpio_writer, write_led_bar_bits
except ImportError:  # pragma: no cover - used when executed directly from tools/ on a Pi.
    from pi_grove_led_bar_smoke import DEFAULT_PORT, PORT_DEFAULTS, clear_led_bar, make_gpio_writer, write_led_bar_bits


OLED_MAX_LINES_128 = 8
OLED_MAX_CHARS_128 = 21


def nmea_checksum_valid(sentence: str) -> bool:
    stripped = sentence.strip()
    if not stripped.startswith("$") or "*" not in stripped:
        return False
    body, expected = stripped[1:].split("*", 1)
    checksum = 0
    for char in body:
        checksum ^= ord(char)
    try:
        return checksum == int(expected[:2], 16)
    except ValueError:
        return False


def parse_nmea_sentence(sentence: str) -> dict[str, Any] | None:
    stripped = sentence.strip()
    if not stripped.startswith("$"):
        return None
    body = stripped[1:].split("*", 1)[0]
    fields = body.split(",")
    sentence_type = fields[0][-3:]
    if sentence_type == "RMC":
        return _parse_rmc(fields, stripped)
    if sentence_type == "GGA":
        return _parse_gga(fields, stripped)
    if sentence_type == "GSV":
        return _parse_gsv(fields, stripped)
    return None


def build_gnss_payload(
    parsed: dict[str, Any],
    *,
    device_port: str,
    baud: int,
    capture_mode: str = "serial_device",
) -> dict[str, Any]:
    replayed = capture_mode != "serial_device"
    checksum_valid = parsed["checksum_valid"] is True
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": "pi_gnss_nmea_smoke",
        "hardware_kind": "serial_gnss_nmea",
        "device_port": device_port,
        "baud": baud,
        "capture_mode": capture_mode,
        "sentence_type": parsed["sentence_type"],
        "gnss_time_utc": parsed.get("gnss_time_utc"),
        "position": parsed.get("position"),
        "fix_quality": parsed.get("fix_quality"),
        "motion": parsed.get("motion", _empty_motion()),
        "satellite_signal": parsed.get("satellite_signal"),
        "raw_sentence": parsed["raw_sentence"],
        "checksum_valid": parsed["checksum_valid"],
        "primary_truth_allowed": not replayed and checksum_valid,
        "primary_truth_scope": (
            "diagnostic_replayed_nmea_only"
            if replayed
            else "raw_gnss_observation_only"
            if checksum_valid
            else "invalid_gnss_checksum_diagnostic_only"
        ),
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_capture_only",
    }


def build_gnss_stream_status_payload(*, state: str, device_port: str, baud: int) -> dict[str, Any]:
    if state not in {"waiting", "no_stream"}:
        raise ValueError(f"unsupported GNSS stream status: {state}")
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": "pi_gnss_nmea_stream_status",
        "hardware_kind": "serial_gnss_nmea",
        "device_port": device_port,
        "baud": baud,
        "sentence_type": "NONE",
        "gnss_time_utc": None,
        "position": {"lat": None, "lon": None, "altitude_m": None},
        "motion": _empty_motion(),
        "fix_quality": {
            "status": None,
            "valid": False,
            "quality": None,
            "satellites": None,
            "hdop": None,
        },
        "raw_sentence": None,
        "checksum_valid": None,
        "nmea_stream_state": state,
        "primary_truth_allowed": False,
        "primary_truth_scope": "diagnostic_stream_status_only",
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_capture_only",
    }


def parse_raw_nmea(
    raw_nmea: str,
    *,
    device_port: str,
    baud: int,
    capture_mode: str = "serial_device",
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for line in raw_nmea.splitlines():
        parsed = parse_nmea_sentence(line)
        if parsed is not None:
            payloads.append(
                build_gnss_payload(
                    parsed,
                    device_port=device_port,
                    baud=baud,
                    capture_mode=capture_mode,
                )
            )
    return payloads


def summarize_gnss_signal(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    gsv_payloads = [
        payload
        for payload in payloads
        if isinstance(payload.get("satellite_signal"), dict)
    ]
    satellites: list[dict[str, Any]] = []
    reported_visible_values: list[int] = []
    talker_counts: dict[str, int] = {}
    talker_signal_summary: dict[str, dict[str, Any]] = {}
    for payload in gsv_payloads:
        signal = payload["satellite_signal"]
        talker = str(signal.get("talker") or "")
        if talker:
            talker_counts[talker] = talker_counts.get(talker, 0) + 1
            bucket = talker_signal_summary.setdefault(
                talker,
                {
                    "gsv_sentence_count": 0,
                    "reported_visible_satellites": None,
                    "parsed_satellites": 0,
                    "nonzero_cno_count": 0,
                    "max_cno_dbhz": None,
                },
            )
            bucket["gsv_sentence_count"] += 1
            bucket["parsed_satellites"] += int(signal.get("parsed_satellites") or 0)
            bucket["nonzero_cno_count"] += int(signal.get("nonzero_cno_count") or 0)
            if (visible := _int_or_none(signal.get("reported_visible_satellites"))) is not None:
                bucket["reported_visible_satellites"] = max(int(bucket["reported_visible_satellites"] or 0), visible)
            if (max_cno := _int_or_none(signal.get("max_cno_dbhz"))) is not None:
                bucket["max_cno_dbhz"] = max(int(bucket["max_cno_dbhz"] or 0), max_cno)
        reported_visible = _int_or_none(signal.get("reported_visible_satellites"))
        if reported_visible is not None:
            reported_visible_values.append(reported_visible)
        for satellite in signal.get("satellites") or []:
            if isinstance(satellite, dict):
                satellites.append(satellite)
    for summary in talker_signal_summary.values():
        summary["rf_signal_observed"] = int(summary.get("nonzero_cno_count") or 0) > 0

    cno_values = [
        value
        for satellite in satellites
        if (value := _int_or_none(satellite.get("cno_dbhz"))) is not None
    ]
    gps_cno_values = [
        value
        for satellite in satellites
        if str(satellite.get("talker") or "") == "GP"
        if (value := _int_or_none(satellite.get("cno_dbhz"))) is not None
    ]
    talkers_with_cno = _talkers_with_cno(talker_signal_summary)
    best_talker = talkers_with_cno[0] if talkers_with_cno else None
    return {
        "gsv_sentence_count": len(gsv_payloads),
        "reported_visible_satellites": max(reported_visible_values) if reported_visible_values else None,
        "parsed_satellites": len(satellites),
        "nonzero_cno_count": sum(1 for value in cno_values if value > 0),
        "max_cno_dbhz": max(cno_values) if cno_values else None,
        "gps_nonzero_cno_count": sum(1 for value in gps_cno_values if value > 0),
        "gps_max_cno_dbhz": max(gps_cno_values) if gps_cno_values else None,
        "talker_counts": talker_counts,
        "talker_signal_summary": talker_signal_summary,
        "talkers_with_cno": talkers_with_cno,
        "best_talker": best_talker["talker"] if best_talker else None,
        "best_talker_cno_dbhz": best_talker["max_cno_dbhz"] if best_talker else None,
        "satellites_sample": satellites[:12],
    }


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


def summarize_gnss_fix(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    sentence_type_counts: dict[str, int] = {}
    quality_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    valid_fix_count = 0
    checksum_valid_count = 0
    checksum_invalid_count = 0
    latest_valid_payload: dict[str, Any] | None = None

    for payload in payloads:
        sentence_type = str(payload.get("sentence_type") or "UNKNOWN")
        sentence_type_counts[sentence_type] = sentence_type_counts.get(sentence_type, 0) + 1
        if payload.get("checksum_valid") is True:
            checksum_valid_count += 1
        elif payload.get("checksum_valid") is False:
            checksum_invalid_count += 1

        fix_quality = payload.get("fix_quality") if isinstance(payload.get("fix_quality"), dict) else {}
        quality_key = _summary_key(fix_quality.get("quality"))
        status_key = _summary_key(fix_quality.get("status"))
        quality_counts[quality_key] = quality_counts.get(quality_key, 0) + 1
        status_counts[status_key] = status_counts.get(status_key, 0) + 1

        if _payload_has_valid_fix(payload):
            valid_fix_count += 1
            latest_valid_payload = payload

    return {
        "payload_count": len(payloads),
        "valid_fix_count": valid_fix_count,
        "has_valid_fix": valid_fix_count > 0,
        "checksum_valid_count": checksum_valid_count,
        "checksum_invalid_count": checksum_invalid_count,
        "sentence_type_counts": sentence_type_counts,
        "quality_counts": quality_counts,
        "status_counts": status_counts,
        "latest_valid_fix": _latest_valid_fix_summary(latest_valid_payload),
    }


def _payload_has_valid_fix(payload: dict[str, Any]) -> bool:
    if payload.get("checksum_valid") is False:
        return False
    fix_quality = payload.get("fix_quality") if isinstance(payload.get("fix_quality"), dict) else {}
    if fix_quality.get("valid") is not True:
        return False
    position = payload.get("position") if isinstance(payload.get("position"), dict) else {}
    return _float_or_none(position.get("lat")) is not None and _float_or_none(position.get("lon")) is not None


def _latest_valid_fix_summary(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if payload is None:
        return None
    fix_quality = payload.get("fix_quality") if isinstance(payload.get("fix_quality"), dict) else {}
    position = payload.get("position") if isinstance(payload.get("position"), dict) else {}
    return {
        "sentence_type": payload.get("sentence_type"),
        "gnss_time_utc": payload.get("gnss_time_utc"),
        "position": position,
        "motion": payload.get("motion") if isinstance(payload.get("motion"), dict) else _empty_motion(),
        "quality": fix_quality.get("quality"),
        "status": fix_quality.get("status"),
        "satellites": fix_quality.get("satellites"),
        "hdop": fix_quality.get("hdop"),
    }


def _summary_key(value: Any) -> str:
    return "null" if value in (None, "") else str(value)


def read_serial_nmea(
    *,
    port: str,
    baud: int,
    duration_seconds: float,
    on_line: Any | None = None,
) -> list[str]:
    try:
        import serial  # type: ignore
    except ImportError:
        return _read_serial_nmea_stdlib(
            port=port,
            baud=baud,
            duration_seconds=duration_seconds,
            on_line=on_line,
        )

    lines: list[str] = []
    deadline = time.monotonic() + duration_seconds
    with serial.Serial(port=port, baudrate=baud, timeout=0.2) as serial_port:
        while time.monotonic() < deadline:
            raw = serial_port.readline()
            if raw:
                line = raw.decode("ascii", errors="replace").strip()
                lines.append(line)
                if on_line is not None:
                    on_line(line, len(lines))
    return lines


def _read_serial_nmea_stdlib(
    *,
    port: str,
    baud: int,
    duration_seconds: float,
    on_line: Any | None = None,
) -> list[str]:
    import os
    import select
    import termios

    baud_constant = _termios_baud_constant(baud)
    lines: list[str] = []
    buffer = b""
    deadline = time.monotonic() + duration_seconds
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
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
        termios.tcflush(fd, termios.TCIOFLUSH)

        while time.monotonic() < deadline:
            timeout = max(0.0, min(0.2, deadline - time.monotonic()))
            readable, _, _ = select.select([fd], [], [], timeout)
            if not readable:
                continue
            chunk = os.read(fd, 256)
            if not chunk:
                continue
            buffer += chunk
            while b"\n" in buffer:
                raw_line, buffer = buffer.split(b"\n", 1)
                line = raw_line.decode("ascii", errors="replace").strip()
                if line:
                    lines.append(line)
                    if on_line is not None:
                        on_line(line, len(lines))

        remaining = buffer.decode("ascii", errors="replace").strip()
        if remaining:
            lines.append(remaining)
            if on_line is not None:
                on_line(remaining, len(lines))
        return lines
    finally:
        os.close(fd)


def _termios_baud_constant(baud: int) -> int:
    import termios

    constant_name = f"B{baud}"
    if not hasattr(termios, constant_name):
        raise RuntimeError(f"unsupported serial baud rate for stdlib fallback: {baud}")
    return getattr(termios, constant_name)


def append_jsonl(payloads: list[dict[str, Any]], output_path: Path | None) -> None:
    if output_path is None:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        for payload in payloads:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def gnss_oled_message(payload: dict[str, Any], *, sentence_count: int) -> str:
    stream_state = payload.get("nmea_stream_state")
    if stream_state in {"waiting", "no_stream"}:
        port = Path(str(payload.get("device_port") or "")).name.upper()[:10]
        baud = payload.get("baud") or "--"
        state_label = "WAIT UART" if stream_state == "waiting" else "NO STREAM"
        hint = "LISTENING" if stream_state == "waiting" else "CHECK UART"
        lines = [
            "SCOUT GPS",
            state_label,
            f"NMEA {sentence_count}",
            f"PORT {port}",
            f"{baud} BAUD",
            hint,
        ]
        return _format_oled_lines(lines)

    fix_quality = payload.get("fix_quality") or {}
    position = payload.get("position") or {}
    motion = payload.get("motion") or {}
    sentence_type = str(payload.get("sentence_type") or "NMEA")[-3:]
    has_valid_fix = fix_quality.get("valid") is True
    fix_label = "FIX OK" if has_valid_fix else "NO FIX"
    checksum_label = "CHK OK" if payload.get("checksum_valid") else "CHK BAD"
    satellites = fix_quality.get("satellites")
    quality = fix_quality.get("quality")
    hdop = fix_quality.get("hdop")
    lat = position.get("lat")
    lon = position.get("lon")
    altitude = position.get("altitude_m")
    speed_kmh = motion.get("speed_kmh")
    lines = [
        "SCOUT GPS",
        f"{fix_label} {checksum_label}",
        f"NMEA {sentence_type} {sentence_count}",
        f"SAT {_display_value(satellites)} Q{_display_value(quality)}",
    ]
    if has_valid_fix and lat is not None and lon is not None:
        lines.append(f"LAT {float(lat):.5f}")
        lines.append(f"LON {float(lon):.5f}")
        if altitude is not None:
            lines.append(f"ALT {float(altitude):.1f}M")
        elif hdop is not None:
            lines.append(f"HDOP {hdop}")
        if speed_kmh is not None:
            lines.append(f"SPD {float(speed_kmh):.1f}KMH")
    else:
        lines.append("SEARCH SKY")
    return _format_oled_lines(lines)


def _format_oled_lines(lines: list[str]) -> str:
    return "\n".join(line[:OLED_MAX_CHARS_128] for line in lines[:OLED_MAX_LINES_128])


def apply_gnss_oled_telemetry_state(
    state: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    stream_state = payload.get("nmea_stream_state")
    if stream_state in {"waiting", "no_stream"} or payload.get("checksum_valid") is False:
        return payload

    sentence_type = str(payload.get("sentence_type") or "")
    position = dict(state.get("position") or {"lat": None, "lon": None, "altitude_m": None})
    incoming_position = payload.get("position") if isinstance(payload.get("position"), dict) else {}
    if sentence_type.endswith(("RMC", "GGA")):
        for key in ("lat", "lon", "altitude_m"):
            if incoming_position.get(key) is not None:
                position[key] = incoming_position[key]

    fix_quality = dict(
        state.get("fix_quality")
        or {
            "status": None,
            "valid": False,
            "quality": None,
            "satellites": None,
            "hdop": None,
        }
    )
    incoming_fix_quality = payload.get("fix_quality") if isinstance(payload.get("fix_quality"), dict) else {}
    if sentence_type.endswith(("RMC", "GGA")) and incoming_fix_quality.get("valid") is not None:
        fix_quality["valid"] = incoming_fix_quality.get("valid") is True
    for key in ("status", "quality", "satellites", "hdop"):
        if incoming_fix_quality.get(key) is not None:
            fix_quality[key] = incoming_fix_quality[key]

    motion = dict(state.get("motion") or _empty_motion())
    incoming_motion = payload.get("motion") if isinstance(payload.get("motion"), dict) else {}
    for key in ("speed_knots", "speed_kmh", "speed_mps", "course_deg"):
        if incoming_motion.get(key) is not None:
            motion[key] = incoming_motion[key]

    gnss_time_utc = payload.get("gnss_time_utc") or state.get("gnss_time_utc")
    state["position"] = position
    state["fix_quality"] = fix_quality
    state["motion"] = motion
    state["gnss_time_utc"] = gnss_time_utc

    merged = dict(payload)
    merged["position"] = position
    merged["fix_quality"] = fix_quality
    merged["motion"] = motion
    merged["gnss_time_utc"] = gnss_time_utc
    return merged


def build_oled_status_payload(
    *,
    gnss_payload: dict[str, Any],
    sentence_count: int,
    bus: Path,
    address: int,
    driver: str,
    write_status: str,
    dry_run: bool,
    driver_attempted: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    fix_quality = gnss_payload.get("fix_quality") or {}
    stream_state = gnss_payload.get("nmea_stream_state")
    sentence_type = "NONE" if stream_state else str(gnss_payload.get("sentence_type") or "NMEA")[-3:]
    fix_state = stream_state if stream_state in {"waiting", "no_stream"} else (
        "fix" if fix_quality.get("valid") else "no_fix"
    )
    payload = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": "pi_gnss_nmea_oled_status",
        "hardware_kind": "grove_oled_96x96_i2c",
        "bus": str(bus),
        "address": f"0x{address:02x}",
        "driver": driver,
        "driver_attempted": driver_attempted,
        "write_status": write_status,
        "dry_run": dry_run,
        "message": gnss_oled_message(gnss_payload, sentence_count=sentence_count),
        "gnss_fix_state": fix_state,
        "nmea_stream_state": stream_state,
        "nmea_sentence_type": sentence_type,
        "nmea_sentence_count": sentence_count,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_display_only",
    }
    if error is not None:
        payload["error"] = error
    return payload


def gnss_led_bit(payload: dict[str, Any], *, fix_bit: int, nofix_bit: int) -> int:
    stream_state = payload.get("nmea_stream_state")
    if stream_state == "waiting":
        return 0x003
    if stream_state == "no_stream":
        return 1 << (nofix_bit - 1)
    fix_quality = payload.get("fix_quality") or {}
    bit_number = fix_bit if fix_quality.get("valid") else nofix_bit
    if not 1 <= bit_number <= 10:
        raise ValueError("LED bit number must be between 1 and 10")
    return 1 << (bit_number - 1)


def build_led_status_payload(
    *,
    gnss_payload: dict[str, Any],
    sentence_count: int,
    port: str,
    data_gpio: int,
    clock_gpio: int,
    fix_bit: int,
    nofix_bit: int,
    blink_count: int,
    blink_seconds: float,
    write_status: str,
    dry_run: bool,
    error: str | None = None,
) -> dict[str, Any]:
    fix_quality = gnss_payload.get("fix_quality") or {}
    stream_state = gnss_payload.get("nmea_stream_state")
    fix_state = stream_state if stream_state in {"waiting", "no_stream"} else (
        "fix" if fix_quality.get("valid") else "no_fix"
    )
    bits = gnss_led_bit(gnss_payload, fix_bit=fix_bit, nofix_bit=nofix_bit)
    payload = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": "pi_gnss_nmea_led_status",
        "hardware_kind": "grove_led_bar_v2_my9221",
        "port": port,
        "data_gpio": data_gpio,
        "clock_gpio": clock_gpio,
        "bits": f"0x{bits:03x}",
        "gnss_fix_state": fix_state,
        "nmea_stream_state": stream_state,
        "nmea_sentence_type": "NONE" if stream_state else str(gnss_payload.get("sentence_type") or "NMEA")[-3:],
        "nmea_sentence_count": sentence_count,
        "fix_led_bit": fix_bit,
        "nofix_led_bit": nofix_bit,
        "blink_count": blink_count,
        "blink_seconds": blink_seconds,
        "write_status": write_status,
        "dry_run": dry_run,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_indicator_only",
    }
    if error is not None:
        payload["error"] = error
    return payload


def blink_gnss_led_status(
    *,
    gnss_payload: dict[str, Any],
    sentence_count: int,
    port: str,
    data_gpio: int,
    clock_gpio: int,
    fix_bit: int,
    nofix_bit: int,
    blink_count: int,
    blink_seconds: float,
    dry_run: bool,
) -> dict[str, Any]:
    if blink_count < 1:
        raise ValueError("blink_count must be at least 1")
    if blink_seconds < 0:
        raise ValueError("blink_seconds must be non-negative")
    bits = gnss_led_bit(gnss_payload, fix_bit=fix_bit, nofix_bit=nofix_bit)
    if dry_run:
        return build_led_status_payload(
            gnss_payload=gnss_payload,
            sentence_count=sentence_count,
            port=port,
            data_gpio=data_gpio,
            clock_gpio=clock_gpio,
            fix_bit=fix_bit,
            nofix_bit=nofix_bit,
            blink_count=blink_count,
            blink_seconds=blink_seconds,
            write_status="dry_run",
            dry_run=True,
        )

    writer = None
    try:
        writer = make_gpio_writer()
        for _ in range(blink_count):
            write_led_bar_bits(writer, data_gpio=data_gpio, clock_gpio=clock_gpio, bits=bits)
            time.sleep(blink_seconds)
            clear_led_bar(writer, data_gpio=data_gpio, clock_gpio=clock_gpio)
            time.sleep(blink_seconds)
        return build_led_status_payload(
            gnss_payload=gnss_payload,
            sentence_count=sentence_count,
            port=port,
            data_gpio=data_gpio,
            clock_gpio=clock_gpio,
            fix_bit=fix_bit,
            nofix_bit=nofix_bit,
            blink_count=blink_count,
            blink_seconds=blink_seconds,
            write_status="ok",
            dry_run=False,
        )
    except Exception as exc:
        return build_led_status_payload(
            gnss_payload=gnss_payload,
            sentence_count=sentence_count,
            port=port,
            data_gpio=data_gpio,
            clock_gpio=clock_gpio,
            fix_bit=fix_bit,
            nofix_bit=nofix_bit,
            blink_count=blink_count,
            blink_seconds=blink_seconds,
            write_status="error",
            dry_run=False,
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        if writer is not None:
            writer.close()


def write_gnss_oled_status(
    *,
    gnss_payload: dict[str, Any],
    sentence_count: int,
    bus: Path,
    address: int,
    driver: str,
    dry_run: bool,
) -> dict[str, Any]:
    if dry_run:
        return build_oled_status_payload(
            gnss_payload=gnss_payload,
            sentence_count=sentence_count,
            bus=bus,
            address=address,
            driver=driver,
            driver_attempted=driver,
            write_status="dry_run",
            dry_run=True,
        )
    try:
        driver_attempted = write_display(
            bus=bus,
            address=address,
            driver=driver,
            message=gnss_oled_message(gnss_payload, sentence_count=sentence_count),
        )
        return build_oled_status_payload(
            gnss_payload=gnss_payload,
            sentence_count=sentence_count,
            bus=bus,
            address=address,
            driver=driver,
            driver_attempted=driver_attempted,
            write_status="ok",
            dry_run=False,
        )
    except Exception as exc:
        return build_oled_status_payload(
            gnss_payload=gnss_payload,
            sentence_count=sentence_count,
            bus=bus,
            address=address,
            driver=driver,
            write_status="error",
            dry_run=False,
            error=f"{type(exc).__name__}: {exc}",
        )


def _display_value(value: Any) -> str:
    if value is None:
        return "--"
    return str(value)


def _parse_rmc(fields: list[str], raw_sentence: str) -> dict[str, Any]:
    status = fields[2] if len(fields) > 2 else ""
    lat = _parse_lat_lon(fields[3], fields[4]) if len(fields) > 4 else None
    lon = _parse_lat_lon(fields[5], fields[6]) if len(fields) > 6 else None
    speed_knots = _float_or_none(fields[7]) if len(fields) > 7 else None
    course_deg = _float_or_none(fields[8]) if len(fields) > 8 else None
    return {
        "sentence_type": fields[0],
        "gnss_time_utc": _parse_datetime(fields[1], fields[9] if len(fields) > 9 else ""),
        "position": {"lat": lat, "lon": lon, "altitude_m": None},
        "motion": _motion_from_rmc(speed_knots=speed_knots, course_deg=course_deg),
        "fix_quality": {
            "status": status,
            "valid": status == "A",
            "quality": None,
            "satellites": None,
            "hdop": None,
        },
        "raw_sentence": raw_sentence,
        "checksum_valid": nmea_checksum_valid(raw_sentence),
    }


def _parse_gga(fields: list[str], raw_sentence: str) -> dict[str, Any]:
    lat = _parse_lat_lon(fields[2], fields[3]) if len(fields) > 3 else None
    lon = _parse_lat_lon(fields[4], fields[5]) if len(fields) > 5 else None
    quality = _int_or_none(fields[6]) if len(fields) > 6 else None
    satellites = _int_or_none(fields[7]) if len(fields) > 7 else None
    hdop = _float_or_none(fields[8]) if len(fields) > 8 else None
    altitude = _float_or_none(fields[9]) if len(fields) > 9 else None
    return {
        "sentence_type": fields[0],
        "gnss_time_utc": _parse_time_only(fields[1] if len(fields) > 1 else ""),
        "position": {"lat": lat, "lon": lon, "altitude_m": altitude},
        "fix_quality": {
            "status": None,
            "valid": bool(quality and quality > 0),
            "quality": quality,
            "satellites": satellites,
            "hdop": hdop,
        },
        "raw_sentence": raw_sentence,
        "checksum_valid": nmea_checksum_valid(raw_sentence),
    }


def _parse_gsv(fields: list[str], raw_sentence: str) -> dict[str, Any]:
    talker = fields[0][:-3]
    reported_visible = _int_or_none(fields[3]) if len(fields) > 3 else None
    satellites = []
    for offset in range(4, len(fields), 4):
        if len(fields) < offset + 4:
            break
        svid = _int_or_none(fields[offset])
        if svid is None:
            continue
        satellites.append(
            {
                "talker": talker,
                "svid": svid,
                "elevation_deg": _int_or_none(fields[offset + 1]),
                "azimuth_deg": _int_or_none(fields[offset + 2]),
                "cno_dbhz": _int_or_none(fields[offset + 3]),
            }
        )
    cno_values = [
        value
        for satellite in satellites
        if (value := _int_or_none(satellite.get("cno_dbhz"))) is not None
    ]
    return {
        "sentence_type": fields[0],
        "gnss_time_utc": None,
        "position": {"lat": None, "lon": None, "altitude_m": None},
        "fix_quality": {
            "status": None,
            "valid": False,
            "quality": None,
            "satellites": reported_visible,
            "hdop": None,
        },
        "satellite_signal": {
            "talker": talker,
            "total_messages": _int_or_none(fields[1]) if len(fields) > 1 else None,
            "message_number": _int_or_none(fields[2]) if len(fields) > 2 else None,
            "reported_visible_satellites": reported_visible,
            "parsed_satellites": len(satellites),
            "nonzero_cno_count": sum(1 for value in cno_values if value > 0),
            "max_cno_dbhz": max(cno_values) if cno_values else None,
            "satellites": satellites,
        },
        "raw_sentence": raw_sentence,
        "checksum_valid": nmea_checksum_valid(raw_sentence),
    }


def _parse_lat_lon(value: str, hemisphere: str) -> float | None:
    if not value or not hemisphere:
        return None
    split_at = 2 if hemisphere in {"N", "S"} else 3
    degrees = float(value[:split_at])
    minutes = float(value[split_at:])
    result = degrees + minutes / 60.0
    if hemisphere in {"S", "W"}:
        result = -result
    return round(result, 8)


def _motion_from_rmc(*, speed_knots: float | None, course_deg: float | None) -> dict[str, float | None]:
    if speed_knots is None:
        return {
            "speed_knots": None,
            "speed_kmh": None,
            "speed_mps": None,
            "course_deg": course_deg,
        }
    return {
        "speed_knots": speed_knots,
        "speed_kmh": round(speed_knots * 1.852, 3),
        "speed_mps": round(speed_knots * 0.514444, 3),
        "course_deg": course_deg,
    }


def _empty_motion() -> dict[str, None]:
    return {
        "speed_knots": None,
        "speed_kmh": None,
        "speed_mps": None,
        "course_deg": None,
    }


def _parse_datetime(time_value: str, date_value: str) -> str | None:
    if len(time_value) < 6 or len(date_value) != 6:
        return _parse_time_only(time_value)
    day = int(date_value[0:2])
    month = int(date_value[2:4])
    year = 2000 + int(date_value[4:6])
    return f"{year:04d}-{month:02d}-{day:02d}T{_format_time(time_value)}Z"


def _parse_time_only(time_value: str) -> str | None:
    if len(time_value) < 6:
        return None
    return f"{_format_time(time_value)}Z"


def _format_time(time_value: str) -> str:
    hours = time_value[0:2]
    minutes = time_value[2:4]
    seconds = time_value[4:]
    return f"{hours}:{minutes}:{seconds}"


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read raw GNSS NMEA sentences as Scout diagnostic evidence.")
    parser.add_argument("--port", default="/dev/ttyUSB0")
    parser.add_argument("--baud", type=int, default=9600)
    parser.add_argument("--duration-seconds", type=float, default=5.0)
    parser.add_argument("--output-jsonl", type=Path)
    parser.add_argument("--raw-nmea", help="Parse fixture NMEA text instead of opening serial.")
    parser.add_argument("--oled-status", action="store_true")
    parser.add_argument("--oled-bus", type=Path, default=Path("/dev/i2c-1"))
    parser.add_argument("--oled-address", type=parse_address, default=parse_address("0x3c"))
    parser.add_argument("--oled-driver", choices=("sh1107g", "ssd1327", "auto"), default="sh1107g")
    parser.add_argument("--oled-update-seconds", type=float, default=2.0)
    parser.add_argument("--oled-dry-run", action="store_true")
    parser.add_argument("--led-status", action="store_true")
    parser.add_argument("--led-port", choices=sorted(PORT_DEFAULTS), default=DEFAULT_PORT)
    parser.add_argument("--led-data-gpio", type=int)
    parser.add_argument("--led-clock-gpio", type=int)
    parser.add_argument("--led-fix-bit", type=int, default=10)
    parser.add_argument("--led-nofix-bit", type=int, default=1)
    parser.add_argument("--led-update-seconds", type=float, default=2.0)
    parser.add_argument("--led-blink-count", type=int, default=2)
    parser.add_argument("--led-blink-seconds", type=float, default=0.25)
    parser.add_argument("--led-dry-run", action="store_true")
    args = parser.parse_args(argv)

    oled_updates: list[dict[str, Any]] = []
    led_updates: list[dict[str, Any]] = []
    oled_telemetry_state: dict[str, Any] = {}
    last_oled_update = 0.0
    last_led_update = 0.0
    led_defaults = PORT_DEFAULTS[args.led_port]
    led_data_gpio = args.led_data_gpio if args.led_data_gpio is not None else led_defaults["data_gpio"]
    led_clock_gpio = args.led_clock_gpio if args.led_clock_gpio is not None else led_defaults["clock_gpio"]

    if not 1 <= args.led_fix_bit <= 10:
        parser.error("--led-fix-bit must be between 1 and 10")
    if not 1 <= args.led_nofix_bit <= 10:
        parser.error("--led-nofix-bit must be between 1 and 10")
    if args.led_blink_count < 1:
        parser.error("--led-blink-count must be at least 1")
    if args.led_blink_seconds < 0:
        parser.error("--led-blink-seconds must be non-negative")

    def update_oled_from_line(line: str, sentence_count: int) -> None:
        nonlocal last_oled_update
        if not args.oled_status:
            return
        parsed = parse_nmea_sentence(line)
        if parsed is None:
            return
        now = time.monotonic()
        if now - last_oled_update < args.oled_update_seconds:
            return
        last_oled_update = now
        gnss_payload = build_gnss_payload(
            parsed,
            device_port=args.port,
            baud=args.baud,
            capture_mode="serial_device",
        )
        oled_payload = apply_gnss_oled_telemetry_state(oled_telemetry_state, gnss_payload)
        oled_updates.append(
            write_gnss_oled_status(
                gnss_payload=oled_payload,
                sentence_count=sentence_count,
                bus=args.oled_bus,
                address=args.oled_address,
                driver=args.oled_driver,
                dry_run=args.oled_dry_run,
            )
        )

    def update_led_from_payload(gnss_payload: dict[str, Any], sentence_count: int) -> None:
        led_updates.append(
            blink_gnss_led_status(
                gnss_payload=gnss_payload,
                sentence_count=sentence_count,
                port=args.led_port,
                data_gpio=led_data_gpio,
                clock_gpio=led_clock_gpio,
                fix_bit=args.led_fix_bit,
                nofix_bit=args.led_nofix_bit,
                blink_count=args.led_blink_count,
                blink_seconds=args.led_blink_seconds,
                dry_run=args.led_dry_run,
            )
        )

    def update_led_from_line(line: str, sentence_count: int) -> None:
        nonlocal last_led_update
        if not args.led_status:
            return
        parsed = parse_nmea_sentence(line)
        if parsed is None:
            return
        now = time.monotonic()
        if now - last_led_update < args.led_update_seconds:
            return
        last_led_update = now
        update_led_from_payload(
            build_gnss_payload(
                parsed,
                device_port=args.port,
                baud=args.baud,
                capture_mode="serial_device",
            ),
            sentence_count,
        )

    def append_visual_status(gnss_payload: dict[str, Any], sentence_count: int) -> None:
        if args.oled_status:
            oled_payload = apply_gnss_oled_telemetry_state(oled_telemetry_state, gnss_payload)
            oled_updates.append(
                write_gnss_oled_status(
                    gnss_payload=oled_payload,
                    sentence_count=sentence_count,
                    bus=args.oled_bus,
                    address=args.oled_address,
                    driver=args.oled_driver,
                    dry_run=args.oled_dry_run,
                )
            )
        if args.led_status:
            update_led_from_payload(gnss_payload, sentence_count)

    try:
        if args.raw_nmea is not None:
            payloads = parse_raw_nmea(
                args.raw_nmea,
                device_port=args.port,
                baud=args.baud,
                capture_mode="raw_nmea_argument",
            )
            if args.oled_status or args.led_status:
                for sentence_count, payload in enumerate(payloads, start=1):
                    append_visual_status(payload, sentence_count)
                if not payloads:
                    append_visual_status(
                        build_gnss_stream_status_payload(
                            state="no_stream",
                            device_port=args.port,
                            baud=args.baud,
                        ),
                        0,
                    )
        else:
            if args.oled_status or args.led_status:
                append_visual_status(
                    build_gnss_stream_status_payload(
                        state="waiting",
                        device_port=args.port,
                        baud=args.baud,
                    ),
                    0,
                )
            payloads = parse_raw_nmea(
                "\n".join(
                    read_serial_nmea(
                        port=args.port,
                        baud=args.baud,
                        duration_seconds=args.duration_seconds,
                        on_line=lambda line, sentence_count: (
                            update_oled_from_line(line, sentence_count),
                            update_led_from_line(line, sentence_count),
                        ),
                    )
                ),
                device_port=args.port,
                baud=args.baud,
                capture_mode="serial_device",
            )
            if (args.oled_status or args.led_status) and not payloads:
                append_visual_status(
                    build_gnss_stream_status_payload(
                        state="no_stream",
                        device_port=args.port,
                        baud=args.baud,
                    ),
                    0,
                )
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    append_jsonl(payloads, args.output_jsonl)
    gnss_fix_summary = summarize_gnss_fix(payloads)
    gnss_signal_summary = summarize_gnss_signal(payloads)
    print(
        json.dumps(
            {
                "sentences": payloads,
                "sentence_count": len(payloads),
                "gnss_fix_summary": gnss_fix_summary,
                "gnss_signal_summary": gnss_signal_summary,
                "oled_status_updates": oled_updates,
                "led_status_updates": led_updates,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
