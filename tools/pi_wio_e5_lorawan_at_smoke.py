from __future__ import annotations

import argparse
import json
import os
import re
import select
import sys
import termios
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from tools.pi_grove_led_bar_smoke import DEFAULT_PORT as DEFAULT_LED_PORT
    from tools.pi_grove_led_bar_smoke import PORT_DEFAULTS, clear_led_bar, make_gpio_writer, write_led_bar_bits
    from tools.pi_oled_i2c_smoke import parse_address, write_display
except ImportError:  # pragma: no cover - used when executed directly from tools/ on a Pi.
    from pi_grove_led_bar_smoke import DEFAULT_PORT as DEFAULT_LED_PORT
    from pi_grove_led_bar_smoke import PORT_DEFAULTS, clear_led_bar, make_gpio_writer, write_led_bar_bits
    from pi_oled_i2c_smoke import parse_address, write_display


SOURCE = "pi_wio_e5_lorawan_at_smoke"
HARDWARE_KIND = "wio_e5_lorawan_usb_serial_at"
DEFAULT_PORT = "/dev/ttyUSB0"
DEFAULT_BAUD = 9600
DEFAULT_COMMANDS = ("AT", "AT+VER", "AT+ID")
DEFAULT_LED_OK_BIT = 7
DEFAULT_LED_FAIL_BIT = 10

SAFE_COMMAND_RE = re.compile(r"^AT(?:\+[A-Z0-9_]+[?]?)?$")
BLOCKED_PREFIXES = (
    "AT+JOIN",
    "AT+MSG",
    "AT+MSGHEX",
    "AT+CMSG",
    "AT+CMSGHEX",
    "AT+PMSG",
    "AT+PMSGHEX",
    "AT+SEND",
    "AT+SENDB",
    "AT+DTRX",
    "AT+TEST",
)


@dataclass(frozen=True)
class AtCommandResult:
    command_index: int
    command: str
    response_lines: list[str]
    response_status: str
    elapsed_ms: int
    error: str | None = None


class PySerialAtSession:
    def __init__(self, *, port: str, baud: int) -> None:
        import serial  # type: ignore

        self._serial = serial.Serial(port=port, baudrate=baud, timeout=0.1, write_timeout=1.0)
        self._serial.reset_input_buffer()

    def transact(self, *, command: str, timeout_seconds: float, quiet_seconds: float) -> list[str]:
        self._serial.write(f"{command}\r\n".encode("ascii"))
        self._serial.flush()
        return _read_pyserial_response(
            self._serial,
            timeout_seconds=timeout_seconds,
            quiet_seconds=quiet_seconds,
        )

    def close(self) -> None:
        self._serial.close()


class StdlibAtSession:
    def __init__(self, *, port: str, baud: int) -> None:
        baud_constant = _termios_baud_constant(baud)
        self._fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        attrs = termios.tcgetattr(self._fd)
        attrs[0] = termios.IGNPAR
        attrs[1] = 0
        attrs[2] = baud_constant | termios.CS8 | termios.CLOCAL | termios.CREAD
        attrs[3] = 0
        attrs[4] = baud_constant
        attrs[5] = baud_constant
        attrs[6][termios.VMIN] = 0
        attrs[6][termios.VTIME] = 1
        termios.tcsetattr(self._fd, termios.TCSANOW, attrs)
        termios.tcflush(self._fd, termios.TCIOFLUSH)

    def transact(self, *, command: str, timeout_seconds: float, quiet_seconds: float) -> list[str]:
        os.write(self._fd, f"{command}\r\n".encode("ascii"))
        return _read_fd_response(
            self._fd,
            timeout_seconds=timeout_seconds,
            quiet_seconds=quiet_seconds,
        )

    def close(self) -> None:
        os.close(self._fd)


def parse_commands(value: str | None, repeated_commands: list[str] | None = None) -> list[str]:
    raw_commands = repeated_commands if repeated_commands else (value or ",".join(DEFAULT_COMMANDS)).split(",")
    commands = [normalize_command(command) for command in raw_commands if command.strip()]
    if not commands:
        raise argparse.ArgumentTypeError("at least one AT command is required")
    for command in commands:
        blocked_reason = blocked_reason_for_command(command)
        if blocked_reason is not None:
            raise argparse.ArgumentTypeError(f"blocked AT command {command!r}: {blocked_reason}")
        if not SAFE_COMMAND_RE.fullmatch(command):
            raise argparse.ArgumentTypeError("only read-only AT, AT+NAME, or AT+NAME? diagnostic commands are allowed")
    return commands


def normalize_command(command: str) -> str:
    normalized = command.strip().upper()
    if "\r" in normalized or "\n" in normalized:
        raise argparse.ArgumentTypeError("AT commands must be single-line")
    if not normalized.startswith("AT"):
        raise argparse.ArgumentTypeError("AT commands must start with AT")
    return normalized


def blocked_reason_for_command(command: str) -> str | None:
    normalized = command.strip().upper().replace(" ", "")
    if "=" in normalized:
        return "commands with '=' can change radio/module state and are blocked in this diagnostic slice"
    for prefix in BLOCKED_PREFIXES:
        if normalized.startswith(prefix):
            return "join, uplink, send, test-TX, or RF action commands are blocked"
    return None


def canned_response_for_command(command: str) -> list[str]:
    if command == "AT":
        return ["+AT: OK"]
    if command == "AT+VER":
        return ["+VER: LoRa-E5 mock firmware", "+AT: OK"]
    if command in {"AT+ID", "AT+ID?"}:
        return [
            "+ID: DevAddr, 00:00:00:00",
            "+ID: DevEui, 00:00:00:00:00:00:00:00",
            "+ID: AppEui, 00:00:00:00:00:00:00:00",
            "+AT: OK",
        ]
    token = command.replace("+", "", 1).rstrip("?")
    return [f"+{token}: MOCK", "+AT: OK"]


def response_status_from_lines(lines: list[str]) -> str:
    if not lines:
        return "timeout"
    upper_lines = [line.upper() for line in lines]
    if any("ERROR" in line or line.startswith("+ERR") for line in upper_lines):
        return "error"
    return "ok"


def build_at_payload(
    *,
    result: AtCommandResult,
    device_port: str,
    baud: int,
    dry_run: bool,
) -> dict[str, Any]:
    payload = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": SOURCE,
        "hardware_kind": HARDWARE_KIND,
        "device_port": device_port,
        "baud": baud,
        "command_index": result.command_index,
        "command": result.command,
        "response_lines": result.response_lines,
        "response_status": result.response_status,
        "elapsed_ms": result.elapsed_ms,
        "dry_run": dry_run,
        "command_safe_for_diagnostic": True,
        "radio_tx_allowed": False,
        "join_allowed": False,
        "lorawan_uplink_allowed": False,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_serial_at_only",
    }
    if result.error is not None:
        payload["error"] = result.error
    return payload


def run_at_commands(
    *,
    port: str,
    baud: int,
    commands: list[str],
    command_timeout_seconds: float,
    quiet_seconds: float,
    inter_command_delay_ms: float,
    dry_run: bool,
) -> list[dict[str, Any]]:
    if dry_run:
        return [
            build_at_payload(
                result=AtCommandResult(
                    command_index=index,
                    command=command,
                    response_lines=canned_response_for_command(command),
                    response_status="ok",
                    elapsed_ms=0,
                ),
                device_port=port,
                baud=baud,
                dry_run=True,
            )
            for index, command in enumerate(commands)
        ]

    session = make_at_session(port=port, baud=baud)
    payloads: list[dict[str, Any]] = []
    try:
        for index, command in enumerate(commands):
            started_at = time.monotonic()
            try:
                response_lines = session.transact(
                    command=command,
                    timeout_seconds=command_timeout_seconds,
                    quiet_seconds=quiet_seconds,
                )
                elapsed_ms = int((time.monotonic() - started_at) * 1000)
                result = AtCommandResult(
                    command_index=index,
                    command=command,
                    response_lines=response_lines,
                    response_status=response_status_from_lines(response_lines),
                    elapsed_ms=elapsed_ms,
                )
            except Exception as exc:
                elapsed_ms = int((time.monotonic() - started_at) * 1000)
                result = AtCommandResult(
                    command_index=index,
                    command=command,
                    response_lines=[],
                    response_status="error",
                    elapsed_ms=elapsed_ms,
                    error=f"{type(exc).__name__}: {exc}",
                )
            payloads.append(build_at_payload(result=result, device_port=port, baud=baud, dry_run=False))
            if inter_command_delay_ms > 0:
                time.sleep(inter_command_delay_ms / 1000.0)
        return payloads
    finally:
        session.close()


def make_at_session(*, port: str, baud: int) -> PySerialAtSession | StdlibAtSession:
    try:
        return PySerialAtSession(port=port, baud=baud)
    except ImportError:
        return StdlibAtSession(port=port, baud=baud)


def build_summary(
    *,
    port: str,
    baud: int,
    commands: list[str],
    dry_run: bool,
    payloads: list[dict[str, Any]],
    oled_status_updates: list[dict[str, Any]],
    led_status_updates: list[dict[str, Any]],
) -> dict[str, Any]:
    ok_count = sum(1 for payload in payloads if payload["response_status"] == "ok")
    failed_count = len(payloads) - ok_count
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": SOURCE,
        "hardware_kind": HARDWARE_KIND,
        "device_port": port,
        "baud": baud,
        "commands": commands,
        "command_count": len(commands),
        "ok_count": ok_count,
        "failed_count": failed_count,
        "dry_run": dry_run,
        "responses": payloads,
        "device_identity": extract_device_identity(payloads),
        "oled_status_updates": oled_status_updates,
        "led_status_updates": led_status_updates,
        "radio_tx_allowed": False,
        "join_allowed": False,
        "lorawan_uplink_allowed": False,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_serial_at_only",
    }


def extract_device_identity(payloads: list[dict[str, Any]]) -> dict[str, str]:
    identity: dict[str, str] = {}
    for payload in payloads:
        for line in payload.get("response_lines", []):
            match = re.match(r"^\+ID:\s*([^,]+),\s*(.+)$", line, flags=re.IGNORECASE)
            if match:
                key = match.group(1).strip().lower()
                identity[key] = match.group(2).strip()
    return identity


def wio_e5_oled_message(summary: dict[str, Any]) -> str:
    status = "AT OK" if summary["failed_count"] == 0 and summary["ok_count"] else "AT FAIL"
    port = Path(str(summary["device_port"])).name.upper()[:16]
    identity = summary.get("device_identity") or {}
    deveui = identity.get("deveui")
    id_line = f"EUI {deveui.replace(':', '')[-8:]}" if deveui else "ID --"
    lines = [
        "SCOUT LORA",
        status,
        f"AT {summary['ok_count']}/{summary['command_count']}",
        id_line,
        port,
        "NO RF TX",
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
        "source": "pi_wio_e5_lorawan_oled_status",
        "hardware_kind": "grove_oled_96x96_i2c",
        "bus": str(bus),
        "address": f"0x{address:02x}",
        "driver": driver,
        "driver_attempted": driver_attempted,
        "write_status": write_status,
        "dry_run": dry_run,
        "message": wio_e5_oled_message(summary),
        "radio_tx_allowed": False,
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
            message=wio_e5_oled_message(summary),
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


def parse_led_bit(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 10:
        raise argparse.ArgumentTypeError("LED bit must be between 1 and 10")
    return parsed


def led_bits_for_summary(summary: dict[str, Any], *, ok_bit: int, fail_bit: int) -> int:
    bit = ok_bit if summary["failed_count"] == 0 and summary["ok_count"] else fail_bit
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
        "source": "pi_wio_e5_lorawan_led_status",
        "hardware_kind": "grove_led_bar_v2_my9221",
        "port": port,
        "data_gpio": data_gpio,
        "clock_gpio": clock_gpio,
        "bits": f"0x{bits:03x}",
        "at_ok_count": summary["ok_count"],
        "at_failed_count": summary["failed_count"],
        "ok_led_bit": ok_bit,
        "fail_led_bit": fail_bit,
        "blink_count": blink_count,
        "blink_seconds": blink_seconds,
        "write_status": write_status,
        "dry_run": dry_run,
        "radio_tx_allowed": False,
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


def append_jsonl(payloads: list[dict[str, Any]], output_path: Path | None) -> None:
    if output_path is None:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        for payload in payloads:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _read_pyserial_response(serial_port: Any, *, timeout_seconds: float, quiet_seconds: float) -> list[str]:
    lines: list[str] = []
    deadline = time.monotonic() + timeout_seconds
    last_rx_at: float | None = None
    while time.monotonic() < deadline:
        raw = serial_port.readline()
        if raw:
            for line in _decode_response_chunk(raw):
                lines.append(line)
                last_rx_at = time.monotonic()
            if _has_terminal_status(lines):
                break
            continue
        if lines and last_rx_at is not None and time.monotonic() - last_rx_at >= quiet_seconds:
            break
    return lines


def _read_fd_response(fd: int, *, timeout_seconds: float, quiet_seconds: float) -> list[str]:
    lines: list[str] = []
    buffer = b""
    deadline = time.monotonic() + timeout_seconds
    last_rx_at: float | None = None
    while time.monotonic() < deadline:
        timeout = max(0.0, min(0.1, deadline - time.monotonic()))
        readable, _, _ = select.select([fd], [], [], timeout)
        if not readable:
            if lines and last_rx_at is not None and time.monotonic() - last_rx_at >= quiet_seconds:
                break
            continue
        chunk = os.read(fd, 512)
        if not chunk:
            continue
        buffer += chunk
        while b"\n" in buffer:
            raw_line, buffer = buffer.split(b"\n", 1)
            for line in _decode_response_chunk(raw_line):
                lines.append(line)
                last_rx_at = time.monotonic()
        if _has_terminal_status(lines):
            break
    for line in _decode_response_chunk(buffer):
        if line not in lines:
            lines.append(line)
    return lines


def _decode_response_chunk(chunk: bytes) -> list[str]:
    text = chunk.decode("ascii", errors="replace")
    return [line.strip() for line in re.split(r"[\r\n]+", text) if line.strip()]


def _has_terminal_status(lines: list[str]) -> bool:
    upper_lines = [line.upper() for line in lines]
    return any(line == "OK" or line.endswith(": OK") or "ERROR" in line for line in upper_lines)


def _termios_baud_constant(baud: int) -> int:
    constant_name = f"B{baud}"
    if not hasattr(termios, constant_name):
        raise RuntimeError(f"unsupported serial baud rate for stdlib fallback: {baud}")
    return getattr(termios, constant_name)


def parse_non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return parsed


def parse_positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def parse_positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke-test Wio-E5 / LoRa-E5 local USB serial AT diagnostics.")
    parser.add_argument("--port", default=DEFAULT_PORT)
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD)
    parser.add_argument("--commands", default=",".join(DEFAULT_COMMANDS))
    parser.add_argument("--command", action="append", help="Repeatable AT diagnostic command; overrides --commands.")
    parser.add_argument("--command-timeout-seconds", type=parse_positive_float, default=2.0)
    parser.add_argument("--quiet-seconds", type=parse_positive_float, default=0.25)
    parser.add_argument("--inter-command-delay-ms", type=parse_non_negative_float, default=100.0)
    parser.add_argument("--output-jsonl", type=Path)
    parser.add_argument("--dry-run", action="store_true")
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
    parser.add_argument("--led-blink-count", type=parse_positive_int, default=2)
    parser.add_argument("--led-blink-seconds", type=parse_non_negative_float, default=0.25)
    parser.add_argument("--led-dry-run", action="store_true")
    args = parser.parse_args(argv)

    try:
        commands = parse_commands(args.commands, args.command)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))

    led_defaults = PORT_DEFAULTS[args.led_port]
    led_data_gpio = args.led_data_gpio if args.led_data_gpio is not None else led_defaults["data_gpio"]
    led_clock_gpio = args.led_clock_gpio if args.led_clock_gpio is not None else led_defaults["clock_gpio"]

    try:
        payloads = run_at_commands(
            port=args.port,
            baud=args.baud,
            commands=commands,
            command_timeout_seconds=args.command_timeout_seconds,
            quiet_seconds=args.quiet_seconds,
            inter_command_delay_ms=args.inter_command_delay_ms,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    append_jsonl(payloads, args.output_jsonl)
    summary = build_summary(
        port=args.port,
        baud=args.baud,
        commands=commands,
        dry_run=args.dry_run,
        payloads=payloads,
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
        summary["led_status_updates"].append(
            blink_led_status(
                summary=summary,
                port=args.led_port,
                data_gpio=led_data_gpio,
                clock_gpio=led_clock_gpio,
                ok_bit=args.led_ok_bit,
                fail_bit=args.led_fail_bit,
                blink_count=args.led_blink_count,
                blink_seconds=args.led_blink_seconds,
                dry_run=args.led_dry_run,
            )
        )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["failed_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
