from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from tools.pi_grove_led_bar_smoke import PORT_DEFAULTS, clear_led_bar, make_gpio_writer, write_led_bar_bits
    from tools.pi_oled_i2c_smoke import parse_address, write_display
except ImportError:  # pragma: no cover - used when executed directly from tools/ on a Pi.
    from pi_grove_led_bar_smoke import PORT_DEFAULTS, clear_led_bar, make_gpio_writer, write_led_bar_bits
    from pi_oled_i2c_smoke import parse_address, write_display


STATUS_BITS = {
    "run": 0x01F,
    "ok": 0x3FF,
    "fail": 0x155,
}


def _parse_non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return parsed


def visual_message(smoke_name: str, status: str) -> str:
    clipped_name = smoke_name.upper().replace("_", " ")[:16]
    return f"SCOUT\n{clipped_name}\n{status.upper()}"


def build_payload(
    *,
    smoke_name: str,
    command: list[str],
    child_returncode: int,
    visual_dry_run: bool,
    led_enabled: bool,
    oled_enabled: bool,
    led_port: str,
    data_gpio: int,
    clock_gpio: int,
    oled_bus: Path,
    oled_address: int,
    oled_driver: str,
    run_visual_statuses: list[dict[str, Any]],
    final_visual_statuses: list[dict[str, Any]],
    require_visual: bool,
) -> dict[str, Any]:
    status = "ok" if child_returncode == 0 else "fail"
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": "pi_smoke_visual_feedback",
        "hardware_kind": "grove_oled_led_bar_visual_smoke_feedback",
        "smoke_name": smoke_name,
        "command": command,
        "child_returncode": child_returncode,
        "status": status,
        "visual_dry_run": visual_dry_run,
        "led_enabled": led_enabled,
        "oled_enabled": oled_enabled,
        "led_port": led_port,
        "data_gpio": data_gpio,
        "clock_gpio": clock_gpio,
        "oled_bus": str(oled_bus),
        "oled_address": f"0x{oled_address:02x}",
        "oled_driver": oled_driver,
        "run_visual_statuses": run_visual_statuses,
        "final_visual_statuses": final_visual_statuses,
        "require_visual": require_visual,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_visual_feedback_only",
    }


def append_jsonl(payload: dict[str, Any], output_path: Path | None) -> None:
    if output_path is None:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def apply_visual_state(
    *,
    smoke_name: str,
    state: str,
    visual_dry_run: bool,
    led_enabled: bool,
    oled_enabled: bool,
    led_port: str,
    data_gpio: int,
    clock_gpio: int,
    oled_bus: Path,
    oled_address: int,
    oled_driver: str,
) -> list[dict[str, Any]]:
    statuses: list[dict[str, Any]] = []
    if led_enabled:
        statuses.append(
            _apply_led_state(
                state=state,
                visual_dry_run=visual_dry_run,
                led_port=led_port,
                data_gpio=data_gpio,
                clock_gpio=clock_gpio,
            )
        )
    if oled_enabled:
        statuses.append(
            _apply_oled_state(
                smoke_name=smoke_name,
                state=state,
                visual_dry_run=visual_dry_run,
                oled_bus=oled_bus,
                oled_address=oled_address,
                oled_driver=oled_driver,
            )
        )
    return statuses


def clear_led_state(
    *,
    visual_dry_run: bool,
    led_enabled: bool,
    data_gpio: int,
    clock_gpio: int,
) -> dict[str, Any] | None:
    if not led_enabled:
        return None
    if visual_dry_run:
        return {"target": "led_bar", "state": "clear", "write_status": "dry_run", "bits": "0x000"}

    writer = None
    status = {"target": "led_bar", "state": "clear", "write_status": "ok", "bits": "0x000"}
    try:
        writer = make_gpio_writer()
        clear_led_bar(writer, data_gpio=data_gpio, clock_gpio=clock_gpio)
    except Exception as exc:
        status["write_status"] = "error"
        status["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if writer is not None:
            writer.close()
    return status


def _apply_led_state(
    *,
    state: str,
    visual_dry_run: bool,
    led_port: str,
    data_gpio: int,
    clock_gpio: int,
) -> dict[str, Any]:
    bits = STATUS_BITS[state]
    status = {
        "target": "led_bar",
        "state": state,
        "port": led_port,
        "data_gpio": data_gpio,
        "clock_gpio": clock_gpio,
        "bits": f"0x{bits:03x}",
        "write_status": "dry_run" if visual_dry_run else "ok",
    }
    if visual_dry_run:
        return status

    writer = None
    try:
        writer = make_gpio_writer()
        write_led_bar_bits(writer, data_gpio=data_gpio, clock_gpio=clock_gpio, bits=bits)
    except Exception as exc:
        status["write_status"] = "error"
        status["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if writer is not None:
            writer.close()
    return status


def _apply_oled_state(
    *,
    smoke_name: str,
    state: str,
    visual_dry_run: bool,
    oled_bus: Path,
    oled_address: int,
    oled_driver: str,
) -> dict[str, Any]:
    message = visual_message(smoke_name, state)
    status = {
        "target": "oled",
        "state": state,
        "bus": str(oled_bus),
        "address": f"0x{oled_address:02x}",
        "driver": oled_driver,
        "message": message,
        "write_status": "dry_run" if visual_dry_run else "ok",
    }
    if visual_dry_run:
        return status

    try:
        driver_attempted = write_display(
            bus=oled_bus,
            address=oled_address,
            driver=oled_driver,
            message=message,
        )
        status["driver_attempted"] = driver_attempted
    except Exception as exc:
        status["write_status"] = "error"
        status["error"] = f"{type(exc).__name__}: {exc}"
    return status


def visual_status_has_error(statuses: list[dict[str, Any]]) -> bool:
    return any(status.get("write_status") == "error" for status in statuses)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a Pi hardware smoke command with OLED + LED Bar visual feedback."
    )
    parser.add_argument("--name", required=True, help="Short smoke name shown on the OLED.")
    parser.add_argument("--led-port", choices=sorted(PORT_DEFAULTS), default="D16")
    parser.add_argument("--led-data-gpio", type=int)
    parser.add_argument("--led-clock-gpio", type=int)
    parser.add_argument("--oled-bus", type=Path, default=Path("/dev/i2c-1"))
    parser.add_argument("--oled-address", type=parse_address, default=parse_address("0x3c"))
    parser.add_argument("--oled-driver", choices=("sh1107g", "ssd1327", "auto"), default="sh1107g")
    parser.add_argument("--no-led", action="store_true")
    parser.add_argument("--no-oled", action="store_true")
    parser.add_argument("--visual-dry-run", action="store_true")
    parser.add_argument("--require-visual", action="store_true")
    parser.add_argument("--run-hold-seconds", type=_parse_non_negative_float, default=0.75)
    parser.add_argument("--hold-seconds", type=_parse_non_negative_float, default=2.0)
    parser.add_argument("--clear-led-on-exit", action="store_true")
    parser.add_argument("--output-jsonl", type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)

    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("smoke command is required after --")

    defaults = PORT_DEFAULTS[args.led_port]
    data_gpio = args.led_data_gpio if args.led_data_gpio is not None else defaults["data_gpio"]
    clock_gpio = args.led_clock_gpio if args.led_clock_gpio is not None else defaults["clock_gpio"]

    led_enabled = not args.no_led
    oled_enabled = not args.no_oled

    run_statuses = apply_visual_state(
        smoke_name=args.name,
        state="run",
        visual_dry_run=args.visual_dry_run,
        led_enabled=led_enabled,
        oled_enabled=oled_enabled,
        led_port=args.led_port,
        data_gpio=data_gpio,
        clock_gpio=clock_gpio,
        oled_bus=args.oled_bus,
        oled_address=args.oled_address,
        oled_driver=args.oled_driver,
    )

    if args.run_hold_seconds > 0:
        time.sleep(args.run_hold_seconds)

    child = subprocess.run(command, check=False)
    final_state = "ok" if child.returncode == 0 else "fail"
    final_statuses = apply_visual_state(
        smoke_name=args.name,
        state=final_state,
        visual_dry_run=args.visual_dry_run,
        led_enabled=led_enabled,
        oled_enabled=oled_enabled,
        led_port=args.led_port,
        data_gpio=data_gpio,
        clock_gpio=clock_gpio,
        oled_bus=args.oled_bus,
        oled_address=args.oled_address,
        oled_driver=args.oled_driver,
    )

    if args.hold_seconds > 0:
        time.sleep(args.hold_seconds)

    clear_status = clear_led_state(
        visual_dry_run=args.visual_dry_run,
        led_enabled=led_enabled and args.clear_led_on_exit,
        data_gpio=data_gpio,
        clock_gpio=clock_gpio,
    )
    if clear_status is not None:
        final_statuses.append(clear_status)

    payload = build_payload(
        smoke_name=args.name,
        command=command,
        child_returncode=child.returncode,
        visual_dry_run=args.visual_dry_run,
        led_enabled=led_enabled,
        oled_enabled=oled_enabled,
        led_port=args.led_port,
        data_gpio=data_gpio,
        clock_gpio=clock_gpio,
        oled_bus=args.oled_bus,
        oled_address=args.oled_address,
        oled_driver=args.oled_driver,
        run_visual_statuses=run_statuses,
        final_visual_statuses=final_statuses,
        require_visual=args.require_visual,
    )
    append_jsonl(payload, args.output_jsonl)
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if args.require_visual and (visual_status_has_error(run_statuses) or visual_status_has_error(final_statuses)):
        return 1
    return child.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
