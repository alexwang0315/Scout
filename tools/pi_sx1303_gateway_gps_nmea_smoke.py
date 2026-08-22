from __future__ import annotations

import argparse
import json
import os
import re
import select
import sys
import termios
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from tools.pi_gnss_nmea_smoke import (
        parse_raw_nmea,
        summarize_gnss_fix,
        summarize_gnss_signal,
        _termios_baud_constant,
    )
    from tools.pi_grove_led_bar_smoke import DEFAULT_PORT as DEFAULT_LED_PORT
    from tools.pi_grove_led_bar_smoke import PORT_DEFAULTS, clear_led_bar, make_gpio_writer, write_led_bar_bits
    from tools.pi_oled_i2c_smoke import parse_address, write_display
except ImportError:  # pragma: no cover - used when executed directly from tools/ on a Pi.
    from pi_gnss_nmea_smoke import parse_raw_nmea, summarize_gnss_fix, summarize_gnss_signal, _termios_baud_constant
    from pi_grove_led_bar_smoke import DEFAULT_PORT as DEFAULT_LED_PORT
    from pi_grove_led_bar_smoke import PORT_DEFAULTS, clear_led_bar, make_gpio_writer, write_led_bar_bits
    from pi_oled_i2c_smoke import parse_address, write_display


SOURCE = "pi_sx1303_gateway_gps_nmea_smoke"
HARDWARE_KIND = "sx1303_gateway_hat_l76k_gnss_uart"
DEFAULT_PORTS = ("/dev/serial0", "/dev/ttyAMA0", "/dev/ttyAMA10", "/dev/ttyS0")
DEFAULT_BAUD_RATES = (9600, 38400, 57600, 115200)
DEFAULT_CONFIGURED_GPS_TTY_PATH = "/dev/ttyS0"
DEFAULT_LED_OK_BIT = 10
DEFAULT_LED_FAIL_BIT = 1
NMEA_RE = re.compile(r"\$(?:GP|GN|GB|BD|GA|GL|GQ)[A-Z]{3},[^\r\n$]*\*[0-9A-Fa-f]{2}")


def parse_csv_ports(value: str) -> list[str]:
    ports = [item.strip() for item in value.split(",") if item.strip()]
    if not ports:
        raise argparse.ArgumentTypeError("at least one UART port is required")
    return ports


def parse_csv_baud_rates(value: str) -> list[int]:
    baud_rates: list[int] = []
    for item in value.split(","):
        stripped = item.strip()
        if not stripped:
            continue
        try:
            baud = int(stripped)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"invalid baud rate: {stripped}") from exc
        if baud <= 0:
            raise argparse.ArgumentTypeError("baud rates must be positive")
        baud_rates.append(baud)
    if not baud_rates:
        raise argparse.ArgumentTypeError("at least one baud rate is required")
    return baud_rates


def parse_led_bit(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 10:
        raise argparse.ArgumentTypeError("LED bit must be between 1 and 10")
    return parsed


def read_serial_bytes(*, port: str, baud: int, duration_seconds: float, max_bytes: int) -> bytes:
    if duration_seconds < 0:
        raise ValueError("duration_seconds must be non-negative")
    if max_bytes < 1:
        raise ValueError("max_bytes must be at least 1")

    baud_constant = _termios_baud_constant(baud)
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

        chunks: list[bytes] = []
        remaining = max_bytes
        deadline = time.monotonic() + duration_seconds
        while remaining > 0 and time.monotonic() < deadline:
            timeout = max(0.0, min(0.2, deadline - time.monotonic()))
            readable, _, _ = select.select([fd], [], [], timeout)
            if not readable:
                continue
            chunk = os.read(fd, min(256, remaining))
            if not chunk:
                continue
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def analyze_raw_sample(
    *,
    raw: bytes,
    port: str,
    baud: int,
    read_status: str = "ok",
    error: str | None = None,
    capture_mode: str = "serial_device",
) -> dict[str, Any]:
    decoded = raw.decode("ascii", errors="replace")
    nmea_lines = extract_nmea_lines(decoded)
    payloads = parse_nmea_lines_safely(nmea_lines, port=port, baud=baud, capture_mode=capture_mode)
    checksum_valid_count = sum(1 for payload in payloads if payload.get("checksum_valid") is True)
    status = candidate_status(
        read_status=read_status,
        bytes_read=len(raw),
        nmea_sentence_count=len(payloads),
        checksum_valid_count=checksum_valid_count,
    )
    fix_summary = summarize_gnss_fix(payloads)
    signal_summary = summarize_gnss_signal(payloads)
    candidate = {
        "port": port,
        "baud": baud,
        "status": status,
        "read_status": read_status,
        "bytes_read": len(raw),
        "line_count": count_nonempty_lines(decoded),
        "nmea_sentence_count": len(payloads),
        "checksum_valid_count": checksum_valid_count,
        "nmea_sentence_types": [payload["sentence_type"] for payload in payloads],
        "capture_mode": capture_mode,
        "ascii_printable_ratio": ascii_printable_ratio(raw),
        "raw_sample_hex": raw[:96].hex(),
        "raw_sample_text": sanitize_sample_text(decoded, limit=160),
        "gnss_fix_summary": fix_summary,
        "gnss_signal_summary": signal_summary,
    }
    if error is not None:
        candidate["error"] = error
    if payloads:
        candidate["first_nmea_payload"] = payloads[0]
    return candidate


def extract_nmea_lines(decoded: str) -> list[str]:
    return [match.group(0) for match in NMEA_RE.finditer(decoded)]


def parse_nmea_lines_safely(lines: list[str], *, port: str, baud: int, capture_mode: str) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for line in lines:
        try:
            payloads.extend(parse_raw_nmea(line, device_port=port, baud=baud, capture_mode=capture_mode))
        except Exception:
            continue
    return payloads


def candidate_status(*, read_status: str, bytes_read: int, nmea_sentence_count: int, checksum_valid_count: int) -> str:
    if read_status == "missing_device":
        return "missing_device"
    if read_status == "dry_run":
        return "not_scanned_dry_run"
    if read_status == "error":
        return "read_error"
    if nmea_sentence_count > 0 and checksum_valid_count > 0:
        return "nmea_ok"
    if nmea_sentence_count > 0:
        return "nmea_without_valid_checksum"
    if bytes_read > 0:
        return "bad_stream"
    return "no_stream"


def count_nonempty_lines(decoded: str) -> int:
    return sum(1 for line in decoded.splitlines() if line.strip())


def ascii_printable_ratio(raw: bytes) -> float | None:
    if not raw:
        return None
    printable = sum(1 for byte in raw if byte in (9, 10, 13) or 32 <= byte <= 126)
    return round(printable / len(raw), 3)


def sanitize_sample_text(decoded: str, *, limit: int) -> str:
    sanitized = []
    for char in decoded[:limit]:
        if char in "\r\n\t" or 32 <= ord(char) <= 126:
            sanitized.append(char)
        else:
            sanitized.append(".")
    return "".join(sanitized)


def scan_candidates(
    *,
    ports: list[str],
    baud_rates: list[int],
    duration_seconds: float,
    max_bytes: int,
    dry_run: bool,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for port in ports:
        port_exists = Path(port).exists()
        for baud in baud_rates:
            if dry_run:
                candidates.append(analyze_raw_sample(raw=b"", port=port, baud=baud, read_status="dry_run"))
                continue
            if not port_exists:
                candidates.append(analyze_raw_sample(raw=b"", port=port, baud=baud, read_status="missing_device"))
                continue
            try:
                raw = read_serial_bytes(
                    port=port,
                    baud=baud,
                    duration_seconds=duration_seconds,
                    max_bytes=max_bytes,
                )
                candidates.append(analyze_raw_sample(raw=raw, port=port, baud=baud))
            except Exception as exc:
                candidates.append(
                    analyze_raw_sample(
                        raw=b"",
                        port=port,
                        baud=baud,
                        read_status="error",
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
    return candidates


def choose_best_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not candidates:
        return None
    status_rank = {
        "nmea_ok": 5,
        "nmea_without_valid_checksum": 4,
        "bad_stream": 3,
        "read_error": 2,
        "no_stream": 1,
        "missing_device": 0,
        "not_scanned_dry_run": 0,
    }
    return max(
        candidates,
        key=lambda item: (
            status_rank.get(str(item.get("status")), -1),
            int(item.get("checksum_valid_count") or 0),
            int(item.get("nmea_sentence_count") or 0),
            int(item.get("bytes_read") or 0),
            -len(str(item.get("port") or "")),
        ),
    )


def build_summary(
    *,
    ports: list[str],
    baud_rates: list[int],
    candidates: list[dict[str, Any]],
    duration_seconds: float,
    max_bytes: int,
    configured_gps_tty_path: str,
    dry_run: bool,
    raw_sample_mode: bool,
    oled_status_updates: list[dict[str, Any]],
    led_status_updates: list[dict[str, Any]],
) -> dict[str, Any]:
    best = choose_best_candidate(candidates)
    status = str(best.get("status")) if best else "no_candidates"
    nmea_ok = status == "nmea_ok"
    selected_port = str(best.get("port")) if best and nmea_ok else None
    selected_baud = int(best.get("baud")) if best and nmea_ok else None
    summary = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": SOURCE,
        "hardware_kind": HARDWARE_KIND,
        "region_profile": "AS923_TW_920_925",
        "gateway_location_source": "sx1303_hat_l76k_gnss_uart_candidate",
        "ports_scanned": ports,
        "baud_rates_scanned": baud_rates,
        "duration_seconds_per_candidate": duration_seconds,
        "max_bytes_per_candidate": max_bytes,
        "configured_gps_tty_path": configured_gps_tty_path,
        "configured_gps_tty_path_exists": Path(configured_gps_tty_path).exists(),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "best_candidate": best,
        "status": status,
        "nmea_available": nmea_ok,
        "selected_port": selected_port,
        "selected_baud": selected_baud,
        "suggested_gateway_conf_update": {"gps_tty_path": selected_port} if selected_port else None,
        "dry_run": dry_run,
        "raw_sample_mode": raw_sample_mode,
        "oled_status_updates": oled_status_updates,
        "led_status_updates": led_status_updates,
        "packet_forwarder_started": False,
        "rf_tx_allowed": False,
        "join_allowed": False,
        "lorawan_uplink_allowed": False,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_gateway_gnss_uart_only",
    }
    return summary


def gateway_gps_oled_message(summary: dict[str, Any]) -> str:
    status = summary.get("status")
    best = summary.get("best_candidate") or {}
    if status == "nmea_ok":
        status_label = "NMEA OK"
        hint = "GPS UART OK"
    elif status == "nmea_without_valid_checksum":
        status_label = "NMEA BADCHK"
        hint = "CHECK CHK"
    elif status == "bad_stream":
        status_label = "BAD STREAM"
        hint = "CHECK BAUD"
    elif status == "not_scanned_dry_run":
        status_label = "DRY RUN"
        hint = "NO UART OPEN"
    else:
        status_label = "NO NMEA"
        hint = "CHECK UART"

    port = Path(str(best.get("port") or summary.get("configured_gps_tty_path") or "")).name.upper()[:16] or "--"
    baud = best.get("baud") or "--"
    sentence_count = int(best.get("nmea_sentence_count") or 0)
    checksum_count = int(best.get("checksum_valid_count") or 0)
    lines = [
        "SCOUT GW GPS",
        status_label,
        f"NMEA {sentence_count}",
        f"CHK {checksum_count}",
        f"PORT {port}",
        f"{baud} BAUD",
        hint,
    ]
    return "\n".join(line[:16] for line in lines)


def build_oled_status_payload(
    *,
    summary: dict[str, Any],
    bus: Path,
    address: int,
    driver: str,
    driver_attempted: str | None,
    write_status: str,
    dry_run: bool,
    error: str | None = None,
) -> dict[str, Any]:
    payload = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": "pi_sx1303_gateway_gps_nmea_oled_status",
        "hardware_kind": "grove_oled_96x96_i2c",
        "bus": str(bus),
        "address": f"0x{address:02x}",
        "driver": driver,
        "driver_attempted": driver_attempted,
        "write_status": write_status,
        "dry_run": dry_run,
        "message": gateway_gps_oled_message(summary),
        "gateway_gps_status": summary["status"],
        "nmea_available": summary["nmea_available"],
        "selected_port": summary["selected_port"],
        "selected_baud": summary["selected_baud"],
        "packet_forwarder_started": False,
        "rf_tx_allowed": False,
        "join_allowed": False,
        "lorawan_uplink_allowed": False,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_display_only",
    }
    if error is not None:
        payload["error"] = error
    return payload


def write_oled_status(
    *,
    summary: dict[str, Any],
    dry_run: bool,
    bus: Path,
    address: int,
    driver: str,
) -> dict[str, Any]:
    if dry_run:
        return build_oled_status_payload(
            summary=summary,
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
            message=gateway_gps_oled_message(summary),
        )
        return build_oled_status_payload(
            summary=summary,
            bus=bus,
            address=address,
            driver=driver,
            driver_attempted=driver_attempted,
            write_status="ok",
            dry_run=False,
        )
    except Exception as exc:
        return build_oled_status_payload(
            summary=summary,
            bus=bus,
            address=address,
            driver=driver,
            driver_attempted=None,
            write_status="error",
            dry_run=False,
            error=f"{type(exc).__name__}: {exc}",
        )


def led_bits_for_summary(summary: dict[str, Any], *, ok_bit: int, fail_bit: int) -> int:
    bit = ok_bit if summary["nmea_available"] else fail_bit
    return 1 << (bit - 1)


def build_led_status_payload(
    *,
    summary: dict[str, Any],
    port: str,
    data_gpio: int,
    clock_gpio: int,
    ok_bit: int,
    fail_bit: int,
    blink_count: int,
    blink_seconds: float,
    write_status: str,
    dry_run: bool,
    error: str | None = None,
) -> dict[str, Any]:
    bits = led_bits_for_summary(summary, ok_bit=ok_bit, fail_bit=fail_bit)
    payload = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": "pi_sx1303_gateway_gps_nmea_led_status",
        "hardware_kind": "grove_led_bar_v2_my9221",
        "port": port,
        "data_gpio": data_gpio,
        "clock_gpio": clock_gpio,
        "bits": f"0x{bits:03x}",
        "gateway_gps_status": summary["status"],
        "nmea_available": summary["nmea_available"],
        "selected_port": summary["selected_port"],
        "selected_baud": summary["selected_baud"],
        "ok_led_bit": ok_bit,
        "fail_led_bit": fail_bit,
        "blink_count": blink_count,
        "blink_seconds": blink_seconds,
        "write_status": write_status,
        "dry_run": dry_run,
        "packet_forwarder_started": False,
        "rf_tx_allowed": False,
        "join_allowed": False,
        "lorawan_uplink_allowed": False,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_indicator_only",
    }
    if error is not None:
        payload["error"] = error
    return payload


def blink_led_status(
    *,
    summary: dict[str, Any],
    port: str,
    data_gpio: int,
    clock_gpio: int,
    ok_bit: int,
    fail_bit: int,
    blink_count: int,
    blink_seconds: float,
    dry_run: bool,
) -> dict[str, Any]:
    if blink_count < 1:
        raise ValueError("blink_count must be at least 1")
    if blink_seconds < 0:
        raise ValueError("blink_seconds must be non-negative")
    if dry_run:
        return build_led_status_payload(
            summary=summary,
            port=port,
            data_gpio=data_gpio,
            clock_gpio=clock_gpio,
            ok_bit=ok_bit,
            fail_bit=fail_bit,
            blink_count=blink_count,
            blink_seconds=blink_seconds,
            write_status="dry_run",
            dry_run=True,
        )
    writer = None
    try:
        writer = make_gpio_writer()
        bits = led_bits_for_summary(summary, ok_bit=ok_bit, fail_bit=fail_bit)
        for _ in range(blink_count):
            write_led_bar_bits(writer, data_gpio=data_gpio, clock_gpio=clock_gpio, bits=bits)
            time.sleep(blink_seconds)
            clear_led_bar(writer, data_gpio=data_gpio, clock_gpio=clock_gpio)
            time.sleep(blink_seconds)
        return build_led_status_payload(
            summary=summary,
            port=port,
            data_gpio=data_gpio,
            clock_gpio=clock_gpio,
            ok_bit=ok_bit,
            fail_bit=fail_bit,
            blink_count=blink_count,
            blink_seconds=blink_seconds,
            write_status="ok",
            dry_run=False,
        )
    except Exception as exc:
        return build_led_status_payload(
            summary=summary,
            port=port,
            data_gpio=data_gpio,
            clock_gpio=clock_gpio,
            ok_bit=ok_bit,
            fail_bit=fail_bit,
            blink_count=blink_count,
            blink_seconds=blink_seconds,
            write_status="error",
            dry_run=False,
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        if writer is not None:
            writer.close()


def append_jsonl(payload: dict[str, Any], output_path: Path | None) -> None:
    if output_path is None:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan SX1303 HAT L76K GNSS UART candidates for valid NMEA.")
    parser.add_argument("--ports", type=parse_csv_ports, default=list(DEFAULT_PORTS))
    parser.add_argument("--baud-rates", type=parse_csv_baud_rates, default=list(DEFAULT_BAUD_RATES))
    parser.add_argument("--duration-seconds", type=float, default=4.0)
    parser.add_argument("--max-bytes", type=int, default=2048)
    parser.add_argument("--configured-gps-tty-path", default=DEFAULT_CONFIGURED_GPS_TTY_PATH)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--raw-sample-hex", help="Analyze a hex-encoded UART sample instead of opening devices.")
    parser.add_argument("--raw-sample-text", help="Analyze a text UART sample instead of opening devices.")
    parser.add_argument("--sample-port", default="raw-sample")
    parser.add_argument("--sample-baud", type=int, default=9600)
    parser.add_argument("--output-jsonl", type=Path)
    parser.add_argument("--oled-status", action="store_true")
    parser.add_argument("--oled-bus", type=Path, default=Path("/dev/i2c-1"))
    parser.add_argument("--oled-address", type=parse_address, default=parse_address("0x3c"))
    parser.add_argument("--oled-driver", choices=("sh1107g", "ssd1327", "auto"), default="sh1107g")
    parser.add_argument("--oled-dry-run", action="store_true")
    parser.add_argument("--led-status", action="store_true")
    parser.add_argument("--led-port", choices=sorted(PORT_DEFAULTS), default=DEFAULT_LED_PORT)
    parser.add_argument("--led-data-gpio", type=int)
    parser.add_argument("--led-clock-gpio", type=int)
    parser.add_argument("--led-ok-bit", type=parse_led_bit, default=DEFAULT_LED_OK_BIT)
    parser.add_argument("--led-fail-bit", type=parse_led_bit, default=DEFAULT_LED_FAIL_BIT)
    parser.add_argument("--led-blink-count", type=int, default=2)
    parser.add_argument("--led-blink-seconds", type=float, default=0.25)
    parser.add_argument("--led-dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.duration_seconds < 0:
        parser.error("--duration-seconds must be non-negative")
    if args.max_bytes < 1:
        parser.error("--max-bytes must be at least 1")
    if args.sample_baud <= 0:
        parser.error("--sample-baud must be positive")
    if args.led_blink_count < 1:
        parser.error("--led-blink-count must be at least 1")
    if args.led_blink_seconds < 0:
        parser.error("--led-blink-seconds must be non-negative")
    if args.raw_sample_hex is not None and args.raw_sample_text is not None:
        parser.error("--raw-sample-hex and --raw-sample-text are mutually exclusive")

    raw_sample_mode = args.raw_sample_hex is not None or args.raw_sample_text is not None
    try:
        if args.raw_sample_hex is not None:
            raw = bytes.fromhex(args.raw_sample_hex)
            candidates = [
                analyze_raw_sample(
                    raw=raw,
                    port=args.sample_port,
                    baud=args.sample_baud,
                    capture_mode="raw_nmea_argument",
                )
            ]
            ports = [args.sample_port]
            baud_rates = [args.sample_baud]
        elif args.raw_sample_text is not None:
            raw = args.raw_sample_text.encode("ascii", errors="replace")
            candidates = [
                analyze_raw_sample(
                    raw=raw,
                    port=args.sample_port,
                    baud=args.sample_baud,
                    capture_mode="raw_nmea_argument",
                )
            ]
            ports = [args.sample_port]
            baud_rates = [args.sample_baud]
        else:
            ports = args.ports
            baud_rates = args.baud_rates
            candidates = scan_candidates(
                ports=ports,
                baud_rates=baud_rates,
                duration_seconds=args.duration_seconds,
                max_bytes=args.max_bytes,
                dry_run=args.dry_run,
            )
    except ValueError as exc:
        print(f"ValueError: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    summary = build_summary(
        ports=ports,
        baud_rates=baud_rates,
        candidates=candidates,
        duration_seconds=args.duration_seconds,
        max_bytes=args.max_bytes,
        configured_gps_tty_path=args.configured_gps_tty_path,
        dry_run=args.dry_run,
        raw_sample_mode=raw_sample_mode,
        oled_status_updates=[],
        led_status_updates=[],
    )

    if args.oled_status:
        summary["oled_status_updates"].append(
            write_oled_status(
                summary=summary,
                dry_run=args.oled_dry_run,
                bus=args.oled_bus,
                address=args.oled_address,
                driver=args.oled_driver,
            )
        )
    if args.led_status:
        led_defaults = PORT_DEFAULTS[args.led_port]
        data_gpio = args.led_data_gpio if args.led_data_gpio is not None else led_defaults["data_gpio"]
        clock_gpio = args.led_clock_gpio if args.led_clock_gpio is not None else led_defaults["clock_gpio"]
        summary["led_status_updates"].append(
            blink_led_status(
                summary=summary,
                port=args.led_port,
                data_gpio=data_gpio,
                clock_gpio=clock_gpio,
                ok_bit=args.led_ok_bit,
                fail_bit=args.led_fail_bit,
                blink_count=args.led_blink_count,
                blink_seconds=args.led_blink_seconds,
                dry_run=args.led_dry_run,
            )
        )

    append_jsonl(summary, args.output_jsonl)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
