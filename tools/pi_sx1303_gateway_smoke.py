#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

try:
    from tools.pi_grove_led_bar_smoke import DEFAULT_PORT as DEFAULT_LED_PORT
    from tools.pi_grove_led_bar_smoke import PORT_DEFAULTS, clear_led_bar, make_gpio_writer, write_led_bar_bits
    from tools.pi_oled_i2c_smoke import parse_address, write_display
except ImportError:  # pragma: no cover - used when copied beside smoke tools on Pi.
    from pi_grove_led_bar_smoke import DEFAULT_PORT as DEFAULT_LED_PORT
    from pi_grove_led_bar_smoke import PORT_DEFAULTS, clear_led_bar, make_gpio_writer, write_led_bar_bits
    from pi_oled_i2c_smoke import parse_address, write_display


SOURCE = "pi_sx1303_gateway_smoke"
HARDWARE_KIND = "sx1303_lorawan_gateway_hat"
DEFAULT_SPI_DEVICE = Path("/dev/spidev0.0")
DEFAULT_HAL_ROOT = Path("/home/alexwang0315/Documents/sx1302_hal_rpi5-master")
DEFAULT_OUTPUT_JSONL = Path("/data/scout/providers/lora/sx1303-gateway-smoke.jsonl")
DEFAULT_REGION_PROFILE = "AS923_2"
DEFAULT_LED_OK_BIT = 7
DEFAULT_LED_FAIL_BIT = 10


def parse_chip_id_output(text: str) -> dict[str, Any]:
    eui_match = re.search(r"concentrator\s+EUI:\s*(0x[0-9a-fA-F]+)", text, flags=re.IGNORECASE)
    chip_version_match = re.search(r"chip\s+version\s+is\s+(0x[0-9a-fA-F]+)", text, flags=re.IGNORECASE)
    return {
        "gateway_eui": eui_match.group(1).lower() if eui_match else None,
        "chip_version": chip_version_match.group(1).lower() if chip_version_match else None,
        "temperature_sensor_detected": "temperature sensor" in text.lower(),
        "legacy_timestamp": "legacy timestamp" in text.lower(),
        "dual_demodulation_disabled": "dual demodulation disabled" in text.lower(),
    }


def boundary_fields() -> dict[str, Any]:
    return {
        "read_only": True,
        "packet_forwarder_started": False,
        "gateway_config_changed": False,
        "rf_tx_allowed": False,
        "downlink_allowed": False,
        "join_allowed": False,
        "lorawan_uplink_allowed": False,
        "remote_outbound_allowed": False,
        "phase1_safety_decision_change_allowed": False,
        "phase1_l0_l4_state_mutated": False,
        "safety_api_called": False,
        "phase2_brain_writeback": False,
        "outbound_send_performed": False,
        "hardware_control_scope": "diagnostic_gateway_evidence_only",
    }


def build_chip_id_command(
    *,
    chip_id_command: str | None,
    hal_root: Path,
    spi_device: Path,
) -> list[str]:
    if chip_id_command:
        return shlex.split(chip_id_command)
    return [str(hal_root / "util_chip_id" / "chip_id"), "-d", str(spi_device), "-r", "1250", "-k", "0"]


def chip_id_working_directory(command: Sequence[str]) -> Path | None:
    if not command:
        return None
    executable = Path(command[0])
    if executable.is_absolute():
        return executable.parent
    return None


def run_chip_id(command: Sequence[str], *, timeout_seconds: float) -> dict[str, Any]:
    started = time.monotonic()
    cwd = chip_id_working_directory(command)
    try:
        result = subprocess.run(
            list(command),
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
            cwd=str(cwd) if cwd is not None else None,
        )
    except FileNotFoundError as exc:
        return {
            "status": "command_missing",
            "returncode": None,
            "stdout": "",
            "stderr": f"{type(exc).__name__}: {exc}",
            "cwd": str(cwd) if cwd is not None else None,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return {
            "status": "timeout",
            "returncode": None,
            "stdout": stdout,
            "stderr": stderr,
            "cwd": str(cwd) if cwd is not None else None,
            "timeout_seconds": timeout_seconds,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
    elapsed_ms = int((time.monotonic() - started) * 1000)
    return {
        "status": "ok" if result.returncode == 0 else "nonzero",
        "returncode": result.returncode,
        "stdout": result.stdout or "",
        "stderr": result.stderr or "",
        "cwd": str(cwd) if cwd is not None else None,
        "elapsed_ms": elapsed_ms,
    }


def spidev_candidates() -> list[dict[str, Any]]:
    candidates = [Path("/dev/spidev0.0"), Path("/dev/spidev0.1"), Path("/dev/spidev10.0")]
    return [{"path": str(path), "exists": path.exists()} for path in candidates]


def build_payload(
    *,
    spi_device: Path,
    hal_root: Path,
    chip_id_command: list[str],
    chip_id_result: dict[str, Any],
    dry_run: bool,
    region_profile: str,
) -> dict[str, Any]:
    combined_output = "\n".join(
        part for part in (chip_id_result.get("stdout", ""), chip_id_result.get("stderr", "")) if part
    )
    parsed = parse_chip_id_output(combined_output)
    status = "dry_run" if dry_run else "ok"
    if not dry_run and (chip_id_result["status"] != "ok" or not parsed["gateway_eui"]):
        status = "error"
    payload = {
        "captured_at": _now_iso(),
        "source": SOURCE,
        "hardware_kind": HARDWARE_KIND,
        "status": status,
        "region_profile": region_profile,
        "spi_device": str(spi_device),
        "spidev_candidates": spidev_candidates(),
        "hal_root": str(hal_root),
        "chip_id_tool": str(chip_id_command[0]) if chip_id_command else None,
        "chip_id_command": list(chip_id_command),
        "chip_id_result": {
            "status": chip_id_result["status"],
            "returncode": chip_id_result["returncode"],
            "cwd": chip_id_result.get("cwd"),
            "elapsed_ms": chip_id_result.get("elapsed_ms"),
        },
        "gateway_eui": parsed["gateway_eui"],
        "chip_version": parsed["chip_version"],
        "temperature_sensor_detected": parsed["temperature_sensor_detected"],
        "legacy_timestamp": parsed["legacy_timestamp"],
        "dual_demodulation_disabled": parsed["dual_demodulation_disabled"],
        "frequency_plan_checked": False,
        "rf_receive_path_checked": not dry_run and status == "ok",
        "rf_read_scope": "spi_chip_id_only",
        "uplink_count": 0,
        **boundary_fields(),
    }
    if chip_id_result.get("stderr") and chip_id_result["status"] != "ok":
        payload["error"] = chip_id_result["stderr"].strip()[:1000]
    return payload


def gateway_oled_message(payload: dict[str, Any]) -> str:
    status = "RF OK" if payload["status"] == "ok" else ("DRY RUN" if payload["status"] == "dry_run" else "RF FAIL")
    eui = str(payload.get("gateway_eui") or "--").replace("0x", "").upper()
    eui_tail = eui[-8:] if eui != "--" else "--"
    lines = [
        "SCOUT LORA GW",
        status,
        f"REG {payload['region_profile']}"[:16],
        f"EUI {eui_tail}"[:16],
        "NO RF TX",
    ]
    return "\n".join(line[:16] for line in lines)


def write_oled_status(
    *,
    payload: dict[str, Any],
    bus: Path,
    address: int,
    driver: str,
    dry_run: bool,
) -> dict[str, Any]:
    message = gateway_oled_message(payload)
    status_payload = {
        "captured_at": _now_iso(),
        "source": "pi_sx1303_gateway_smoke_oled_status",
        "hardware_kind": "grove_oled_96x96_i2c",
        "bus": str(bus),
        "address": f"0x{address:02x}",
        "driver": driver,
        "message": message,
        "dry_run": dry_run,
        "gateway_eui": payload.get("gateway_eui"),
        "rf_tx_allowed": False,
        "downlink_allowed": False,
        "lorawan_uplink_allowed": False,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_display_only",
    }
    if dry_run:
        return {**status_payload, "write_status": "dry_run", "driver_attempted": driver}
    try:
        driver_attempted = write_display(bus=bus, address=address, driver=driver, message=message)
        return {**status_payload, "write_status": "ok", "driver_attempted": driver_attempted}
    except Exception as exc:
        return {
            **status_payload,
            "write_status": "error",
            "driver_attempted": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


def write_led_status(
    *,
    payload: dict[str, Any],
    port: str,
    data_gpio: int,
    clock_gpio: int,
    ok_bit: int,
    fail_bit: int,
    blink_seconds: float,
    dry_run: bool,
) -> dict[str, Any]:
    selected_bit = ok_bit if payload["status"] in {"ok", "dry_run"} else fail_bit
    bits = 1 << (selected_bit - 1)
    status_payload = {
        "captured_at": _now_iso(),
        "source": "pi_sx1303_gateway_smoke_led_status",
        "hardware_kind": "grove_led_bar_v2_my9221",
        "port": port,
        "data_gpio": data_gpio,
        "clock_gpio": clock_gpio,
        "bits": f"0x{bits:03x}",
        "status": payload["status"],
        "ok_led_bit": ok_bit,
        "fail_led_bit": fail_bit,
        "blink_seconds": blink_seconds,
        "write_status": "dry_run" if dry_run else "ok",
        "dry_run": dry_run,
        "rf_tx_allowed": False,
        "downlink_allowed": False,
        "lorawan_uplink_allowed": False,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_indicator_only",
    }
    if dry_run:
        return status_payload
    writer = None
    try:
        writer = make_gpio_writer()
        write_led_bar_bits(writer, data_gpio=data_gpio, clock_gpio=clock_gpio, bits=bits)
        time.sleep(blink_seconds)
        clear_led_bar(writer, data_gpio=data_gpio, clock_gpio=clock_gpio)
        return status_payload
    except Exception as exc:
        return {
            **status_payload,
            "write_status": "error",
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        if writer is not None:
            writer.close()


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _led_bit(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 10:
        raise argparse.ArgumentTypeError("LED bit must be between 1 and 10")
    return parsed


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture SX1303 gateway SPI/chip-id diagnostic evidence without RF TX or LoRaWAN joins."
    )
    parser.add_argument("--spi-device", type=Path, default=DEFAULT_SPI_DEVICE)
    parser.add_argument("--hal-root", type=Path, default=DEFAULT_HAL_ROOT)
    parser.add_argument("--chip-id-command")
    parser.add_argument("--chip-id-output", help="Parse this chip_id output instead of touching hardware.")
    parser.add_argument("--timeout-seconds", type=_positive_float, default=20.0)
    parser.add_argument("--region-profile", default=DEFAULT_REGION_PROFILE)
    parser.add_argument("--output-jsonl", type=Path, default=DEFAULT_OUTPUT_JSONL)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-output-jsonl", action="store_true")
    parser.add_argument("--oled-status", action="store_true")
    parser.add_argument("--oled-bus", type=Path, default=Path("/dev/i2c-1"))
    parser.add_argument("--oled-address", type=parse_address, default=0x3C)
    parser.add_argument("--oled-driver", choices=("sh1107g", "ssd1327", "auto"), default="sh1107g")
    parser.add_argument("--oled-dry-run", action="store_true")
    parser.add_argument("--led-status", action="store_true")
    parser.add_argument("--led-port", choices=sorted(PORT_DEFAULTS), default=DEFAULT_LED_PORT)
    parser.add_argument("--led-data-gpio", type=int)
    parser.add_argument("--led-clock-gpio", type=int)
    parser.add_argument("--led-ok-bit", type=_led_bit, default=DEFAULT_LED_OK_BIT)
    parser.add_argument("--led-fail-bit", type=_led_bit, default=DEFAULT_LED_FAIL_BIT)
    parser.add_argument("--led-blink-seconds", type=float, default=0.35)
    parser.add_argument("--led-dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.led_blink_seconds < 0:
        parser.error("--led-blink-seconds must be non-negative")

    chip_id_command = build_chip_id_command(
        chip_id_command=args.chip_id_command,
        hal_root=args.hal_root.expanduser(),
        spi_device=args.spi_device.expanduser(),
    )
    if args.dry_run:
        chip_id_result = {"status": "dry_run", "returncode": None, "stdout": "", "stderr": "", "elapsed_ms": 0}
    elif args.chip_id_output is not None:
        chip_id_result = {
            "status": "ok",
            "returncode": 0,
            "stdout": args.chip_id_output,
            "stderr": "",
            "elapsed_ms": 0,
        }
    else:
        chip_id_result = run_chip_id(chip_id_command, timeout_seconds=args.timeout_seconds)

    payload = build_payload(
        spi_device=args.spi_device.expanduser(),
        hal_root=args.hal_root.expanduser(),
        chip_id_command=chip_id_command,
        chip_id_result=chip_id_result,
        dry_run=bool(args.dry_run),
        region_profile=str(args.region_profile),
    )

    if args.oled_status:
        payload["oled_status_updates"] = [
            write_oled_status(
                payload=payload,
                bus=args.oled_bus.expanduser(),
                address=int(args.oled_address),
                driver=str(args.oled_driver),
                dry_run=bool(args.oled_dry_run),
            )
        ]
    if args.led_status:
        defaults = PORT_DEFAULTS[args.led_port]
        payload["led_status_updates"] = [
            write_led_status(
                payload=payload,
                port=str(args.led_port),
                data_gpio=args.led_data_gpio if args.led_data_gpio is not None else int(defaults["data_gpio"]),
                clock_gpio=args.led_clock_gpio if args.led_clock_gpio is not None else int(defaults["clock_gpio"]),
                ok_bit=int(args.led_ok_bit),
                fail_bit=int(args.led_fail_bit),
                blink_seconds=float(args.led_blink_seconds),
                dry_run=bool(args.led_dry_run),
            )
        ]

    if not args.no_output_jsonl:
        append_jsonl(args.output_jsonl.expanduser(), payload)

    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload["status"] in {"ok", "dry_run"} else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
