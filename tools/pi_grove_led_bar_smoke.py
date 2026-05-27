from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol


PORT_DEFAULTS = {
    "D16": {"data_gpio": 16, "clock_gpio": 17},
    "D5": {"data_gpio": 5, "clock_gpio": 6},
}

PATTERN_BITS = {
    "all_on": 0x3FF,
    "all_off": 0x000,
    "odd": 0x155,
    "even": 0x2AA,
    "first_half": 0x01F,
    "last_half": 0x3E0,
    "walk": 0x001,
}


class GpioWriter(Protocol):
    def setup_output(self, gpio: int) -> None: ...

    def write(self, gpio: int, value: int) -> None: ...

    def close(self) -> None: ...


class LgpioWriter:
    def __init__(self) -> None:
        import lgpio  # type: ignore

        self._lgpio = lgpio
        self._handle = lgpio.gpiochip_open(0)

    def setup_output(self, gpio: int) -> None:
        self._lgpio.gpio_claim_output(self._handle, gpio, 0)

    def write(self, gpio: int, value: int) -> None:
        self._lgpio.gpio_write(self._handle, gpio, value)

    def close(self) -> None:
        self._lgpio.gpiochip_close(self._handle)


class GpiodWriter:
    def __init__(self) -> None:
        import gpiod  # type: ignore

        self._gpiod = gpiod
        self._chip = gpiod.Chip("/dev/gpiochip0")
        self._lines: dict[int, Any] = {}

    def setup_output(self, gpio: int) -> None:
        line = self._chip.get_line(gpio)
        line.request(consumer="scout-led-bar-smoke", type=self._gpiod.LINE_REQ_DIR_OUT, default_vals=[0])
        self._lines[gpio] = line

    def write(self, gpio: int, value: int) -> None:
        self._lines[gpio].set_value(value)

    def close(self) -> None:
        for line in self._lines.values():
            line.release()
        self._chip.close()


def make_gpio_writer() -> GpioWriter:
    try:
        return LgpioWriter()
    except Exception:
        return GpiodWriter()


def pattern_to_bits(pattern: str, bits: int | None = None) -> int:
    if pattern == "status_bits":
        if bits is None:
            raise ValueError("--bits is required for status_bits")
        return bits & 0x3FF
    if pattern not in PATTERN_BITS:
        raise ValueError(f"unsupported LED Bar pattern: {pattern}")
    return PATTERN_BITS[pattern]


def bit_values_from_10bit(bits: int) -> list[int]:
    values = [0x00FF if bits & (1 << index) else 0x0000 for index in range(10)]
    return values + [0x0000, 0x0000]


def write_led_bar_bits(writer: GpioWriter, *, data_gpio: int, clock_gpio: int, bits: int) -> None:
    writer.setup_output(data_gpio)
    writer.setup_output(clock_gpio)
    _send_16_bits(writer, data_gpio, clock_gpio, 0x0000)
    for value in bit_values_from_10bit(bits):
        _send_16_bits(writer, data_gpio, clock_gpio, value)
    _latch(writer, data_gpio, clock_gpio)


def clear_led_bar(writer: GpioWriter, *, data_gpio: int, clock_gpio: int) -> None:
    write_led_bar_bits(writer, data_gpio=data_gpio, clock_gpio=clock_gpio, bits=0x000)


def build_payload(
    *,
    port: str,
    data_gpio: int,
    clock_gpio: int,
    pattern: str,
    bits: int,
    write_status: str,
    dry_run: bool,
    error: str | None = None,
) -> dict[str, Any]:
    payload = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": "pi_grove_led_bar_smoke",
        "hardware_kind": "grove_led_bar_v2_my9221",
        "port": port,
        "data_gpio": data_gpio,
        "clock_gpio": clock_gpio,
        "pattern": pattern,
        "bits": f"0x{bits:03x}",
        "write_status": write_status,
        "dry_run": dry_run,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_indicator_only",
    }
    if error is not None:
        payload["error"] = error
    return payload


def append_jsonl(payload: dict[str, Any], output_path: Path | None) -> None:
    if output_path is None:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _send_16_bits(writer: GpioWriter, data_gpio: int, clock_gpio: int, value: int) -> None:
    clock_value = 0
    for bit_index in range(15, -1, -1):
        writer.write(data_gpio, 1 if value & (1 << bit_index) else 0)
        writer.write(clock_gpio, clock_value)
        clock_value = 1 - clock_value
        _short_delay()


def _latch(writer: GpioWriter, data_gpio: int, clock_gpio: int) -> None:
    writer.write(data_gpio, 0)
    writer.write(clock_gpio, 1)
    writer.write(clock_gpio, 0)
    writer.write(clock_gpio, 1)
    writer.write(clock_gpio, 0)
    time.sleep(0.00024)
    for _ in range(4):
        writer.write(data_gpio, 1)
        writer.write(data_gpio, 0)
    _short_delay()
    writer.write(clock_gpio, 1)
    writer.write(clock_gpio, 0)


def _short_delay() -> None:
    time.sleep(0.00001)


def _parse_int(value: str) -> int:
    return int(value, 0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke-test a Grove LED Bar v2.0 through MY9221 bit-bang.")
    parser.add_argument("--port", choices=sorted(PORT_DEFAULTS), default="D16")
    parser.add_argument("--data-gpio", type=int)
    parser.add_argument("--clock-gpio", type=int)
    parser.add_argument(
        "--pattern",
        choices=("all_on", "all_off", "odd", "even", "first_half", "last_half", "walk", "status_bits"),
        default="all_on",
    )
    parser.add_argument("--bits", type=_parse_int)
    parser.add_argument("--output-jsonl", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--keep-state", action="store_true")
    args = parser.parse_args(argv)

    defaults = PORT_DEFAULTS[args.port]
    data_gpio = args.data_gpio if args.data_gpio is not None else defaults["data_gpio"]
    clock_gpio = args.clock_gpio if args.clock_gpio is not None else defaults["clock_gpio"]

    try:
        bits = pattern_to_bits(args.pattern, args.bits)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    writer: GpioWriter | None = None
    try:
        if not args.dry_run:
            writer = make_gpio_writer()
            write_led_bar_bits(writer, data_gpio=data_gpio, clock_gpio=clock_gpio, bits=bits)
            if not args.keep_state:
                clear_led_bar(writer, data_gpio=data_gpio, clock_gpio=clock_gpio)
        payload = build_payload(
            port=args.port,
            data_gpio=data_gpio,
            clock_gpio=clock_gpio,
            pattern=args.pattern,
            bits=bits,
            write_status="dry_run" if args.dry_run else "ok",
            dry_run=args.dry_run,
        )
        append_jsonl(payload, args.output_jsonl)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        payload = build_payload(
            port=args.port,
            data_gpio=data_gpio,
            clock_gpio=clock_gpio,
            pattern=args.pattern,
            bits=bits,
            write_status="error",
            dry_run=args.dry_run,
            error=f"{type(exc).__name__}: {exc}",
        )
        append_jsonl(payload, args.output_jsonl)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1
    finally:
        if writer is not None:
            writer.close()


if __name__ == "__main__":
    raise SystemExit(main())
