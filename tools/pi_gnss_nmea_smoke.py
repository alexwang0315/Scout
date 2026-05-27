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
    from tools.pi_grove_led_bar_smoke import PORT_DEFAULTS, clear_led_bar, make_gpio_writer, write_led_bar_bits
except ImportError:  # pragma: no cover - used when executed directly from tools/ on a Pi.
    from pi_grove_led_bar_smoke import PORT_DEFAULTS, clear_led_bar, make_gpio_writer, write_led_bar_bits


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
    return None


def build_gnss_payload(parsed: dict[str, Any], *, device_port: str, baud: int) -> dict[str, Any]:
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": "pi_gnss_nmea_smoke",
        "hardware_kind": "serial_gnss_nmea",
        "device_port": device_port,
        "baud": baud,
        "sentence_type": parsed["sentence_type"],
        "gnss_time_utc": parsed.get("gnss_time_utc"),
        "position": parsed.get("position"),
        "fix_quality": parsed.get("fix_quality"),
        "raw_sentence": parsed["raw_sentence"],
        "checksum_valid": parsed["checksum_valid"],
        "primary_truth_allowed": True,
        "primary_truth_scope": "raw_gnss_observation_only",
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_capture_only",
    }


def parse_raw_nmea(raw_nmea: str, *, device_port: str, baud: int) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for line in raw_nmea.splitlines():
        parsed = parse_nmea_sentence(line)
        if parsed is not None:
            payloads.append(build_gnss_payload(parsed, device_port=device_port, baud=baud))
    return payloads


def read_serial_nmea(
    *,
    port: str,
    baud: int,
    duration_seconds: float,
    on_line: Any | None = None,
) -> list[str]:
    try:
        import serial  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on Pi environment.
        raise RuntimeError(
            "pyserial is required for live GNSS serial smoke: python3 -m pip install pyserial"
        ) from exc

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


def append_jsonl(payloads: list[dict[str, Any]], output_path: Path | None) -> None:
    if output_path is None:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        for payload in payloads:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def gnss_oled_message(payload: dict[str, Any], *, sentence_count: int) -> str:
    fix_quality = payload.get("fix_quality") or {}
    position = payload.get("position") or {}
    sentence_type = str(payload.get("sentence_type") or "NMEA")[-3:]
    fix_label = "FIX OK" if fix_quality.get("valid") else "NO FIX"
    checksum_label = "CHK OK" if payload.get("checksum_valid") else "CHK BAD"
    satellites = fix_quality.get("satellites")
    quality = fix_quality.get("quality")
    lat = position.get("lat")
    lon = position.get("lon")
    lines = [
        "SCOUT GPS",
        fix_label,
        f"NMEA {sentence_type} {sentence_count}",
        f"SAT {_display_value(satellites)} Q{_display_value(quality)}",
        checksum_label,
    ]
    if lat is not None and lon is not None:
        lines.append(f"{float(lat):.4f}")
        lines.append(f"{float(lon):.4f}")
    else:
        lines.append("SEARCH SKY")
    return "\n".join(line[:16] for line in lines[:6])


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
    sentence_type = str(gnss_payload.get("sentence_type") or "NMEA")[-3:]
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
        "gnss_fix_state": "fix" if fix_quality.get("valid") else "no_fix",
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
    bits = gnss_led_bit(gnss_payload, fix_bit=fix_bit, nofix_bit=nofix_bit)
    payload = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": "pi_gnss_nmea_led_status",
        "hardware_kind": "grove_led_bar_v2_my9221",
        "port": port,
        "data_gpio": data_gpio,
        "clock_gpio": clock_gpio,
        "bits": f"0x{bits:03x}",
        "gnss_fix_state": "fix" if fix_quality.get("valid") else "no_fix",
        "nmea_sentence_type": str(gnss_payload.get("sentence_type") or "NMEA")[-3:],
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
    return {
        "sentence_type": fields[0],
        "gnss_time_utc": _parse_datetime(fields[1], fields[9] if len(fields) > 9 else ""),
        "position": {"lat": lat, "lon": lon, "altitude_m": None},
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


def _int_or_none(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: str) -> float | None:
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
    parser.add_argument("--led-port", choices=sorted(PORT_DEFAULTS), default="D16")
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
        gnss_payload = build_gnss_payload(parsed, device_port=args.port, baud=args.baud)
        oled_updates.append(
            write_gnss_oled_status(
                gnss_payload=gnss_payload,
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
        update_led_from_payload(build_gnss_payload(parsed, device_port=args.port, baud=args.baud), sentence_count)

    try:
        if args.raw_nmea is not None:
            payloads = parse_raw_nmea(args.raw_nmea, device_port=args.port, baud=args.baud)
            if args.oled_status or args.led_status:
                for sentence_count, payload in enumerate(payloads, start=1):
                    if args.oled_status:
                        oled_updates.append(
                            write_gnss_oled_status(
                                gnss_payload=payload,
                                sentence_count=sentence_count,
                                bus=args.oled_bus,
                                address=args.oled_address,
                                driver=args.oled_driver,
                                dry_run=args.oled_dry_run,
                            )
                        )
                    if args.led_status:
                        update_led_from_payload(payload, sentence_count)
        else:
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
            )
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    append_jsonl(payloads, args.output_jsonl)
    print(
        json.dumps(
            {
                "sentences": payloads,
                "sentence_count": len(payloads),
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
