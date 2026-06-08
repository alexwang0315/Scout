from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

try:
    from tools.pi_grove_led_bar_smoke import DEFAULT_PORT, PORT_DEFAULTS, clear_led_bar, make_gpio_writer, write_led_bar_bits
    from tools.pi_oled_i2c_smoke import parse_address, write_display
except ImportError:  # pragma: no cover - used when executed directly from tools/ on a Pi.
    from pi_grove_led_bar_smoke import DEFAULT_PORT, PORT_DEFAULTS, clear_led_bar, make_gpio_writer, write_led_bar_bits
    from pi_oled_i2c_smoke import parse_address, write_display


GROVE_DIGITAL_PORTS = {
    "D5": (5, 6),
    "D16": (16, 17),
    "D18": (18, 19),
    "D22": (22, 23),
    "D24": (24, 25),
    "D26": (26, 27),
}
DEFAULT_GROVE_PORTS = ["D16", "D18", "D24", "D26"]
DEFAULT_ROWS = [16, 17, 18, 19]
DEFAULT_COLS = [24, 25, 26, 27]
KEYMAP = [
    ["1", "2", "3", "A"],
    ["4", "5", "6", "B"],
    ["7", "8", "9", "C"],
    ["*", "0", "#", "D"],
]
PHYSICAL_LABEL_LAYOUT = "row_major_left_to_right_top_to_bottom_s1_s16"
KEY_ROLES = {
    "A": "sos_arm_candidate",
    "B": "ack_i_am_ok_candidate",
    "C": "mark_event_candidate",
    "D": "mode_page_candidate",
    "*": "back_or_silence_candidate",
    "#": "confirm_candidate",
}


class KeypadScanner(Protocol):
    def scan_pressed(self) -> list["KeyPress"]: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class KeyPress:
    key: str
    row_index: int
    col_index: int
    row_gpio: int
    col_gpio: int


class LgpioKeypadScanner:
    def __init__(self, *, rows: list[int], cols: list[int], active_low: bool) -> None:
        import lgpio  # type: ignore

        self._lgpio = lgpio
        self._handle = lgpio.gpiochip_open(0)
        self._rows = rows
        self._cols = cols
        self._active_low = active_low
        self._active_level = 0 if active_low else 1
        self._inactive_level = 1 if active_low else 0
        pull_flag = lgpio.SET_PULL_UP if active_low else lgpio.SET_PULL_DOWN
        for row_gpio in rows:
            lgpio.gpio_claim_output(self._handle, row_gpio, self._inactive_level)
        for col_gpio in cols:
            lgpio.gpio_claim_input(self._handle, col_gpio, pull_flag)

    def scan_pressed(self) -> list[KeyPress]:
        pressed: list[KeyPress] = []
        for row_index, row_gpio in enumerate(self._rows):
            self._drive_all_rows(self._inactive_level)
            self._lgpio.gpio_write(self._handle, row_gpio, self._active_level)
            time.sleep(0.001)
            for col_index, col_gpio in enumerate(self._cols):
                if self._lgpio.gpio_read(self._handle, col_gpio) == self._active_level:
                    pressed.append(
                        KeyPress(
                            key=KEYMAP[row_index][col_index],
                            row_index=row_index,
                            col_index=col_index,
                            row_gpio=row_gpio,
                            col_gpio=col_gpio,
                        )
                    )
            self._lgpio.gpio_write(self._handle, row_gpio, self._inactive_level)
        return pressed

    def close(self) -> None:
        for gpio in [*self._rows, *self._cols]:
            try:
                self._lgpio.gpio_free(self._handle, gpio)
            except Exception:
                pass
        self._lgpio.gpiochip_close(self._handle)

    def _drive_all_rows(self, value: int) -> None:
        for row_gpio in self._rows:
            self._lgpio.gpio_write(self._handle, row_gpio, value)


class RpiGpioKeypadScanner:
    def __init__(self, *, rows: list[int], cols: list[int], active_low: bool) -> None:
        import RPi.GPIO as GPIO  # type: ignore

        self._gpio = GPIO
        self._rows = rows
        self._cols = cols
        self._active_low = active_low
        self._active_level = GPIO.LOW if active_low else GPIO.HIGH
        self._inactive_level = GPIO.HIGH if active_low else GPIO.LOW
        pull = GPIO.PUD_UP if active_low else GPIO.PUD_DOWN
        GPIO.setmode(GPIO.BCM)
        for row_gpio in rows:
            GPIO.setup(row_gpio, GPIO.OUT, initial=self._inactive_level)
        for col_gpio in cols:
            GPIO.setup(col_gpio, GPIO.IN, pull_up_down=pull)

    def scan_pressed(self) -> list[KeyPress]:
        pressed: list[KeyPress] = []
        for row_index, row_gpio in enumerate(self._rows):
            for candidate in self._rows:
                self._gpio.output(candidate, self._inactive_level)
            self._gpio.output(row_gpio, self._active_level)
            time.sleep(0.001)
            for col_index, col_gpio in enumerate(self._cols):
                if self._gpio.input(col_gpio) == self._active_level:
                    pressed.append(
                        KeyPress(
                            key=KEYMAP[row_index][col_index],
                            row_index=row_index,
                            col_index=col_index,
                            row_gpio=row_gpio,
                            col_gpio=col_gpio,
                        )
                    )
            self._gpio.output(row_gpio, self._inactive_level)
        return pressed

    def close(self) -> None:
        self._gpio.cleanup([*self._rows, *self._cols])


def make_keypad_scanner(*, rows: list[int], cols: list[int], active_low: bool) -> KeypadScanner:
    try:
        return LgpioKeypadScanner(rows=rows, cols=cols, active_low=active_low)
    except Exception:
        return RpiGpioKeypadScanner(rows=rows, cols=cols, active_low=active_low)


def parse_gpio_list(value: str) -> list[int]:
    try:
        gpios = [int(part.strip()) for part in value.split(",") if part.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("GPIO list must contain comma-separated integers") from exc
    if len(gpios) != 4:
        raise argparse.ArgumentTypeError("GPIO list must contain exactly 4 pins")
    if len(set(gpios)) != 4:
        raise argparse.ArgumentTypeError("GPIO list cannot contain duplicate pins")
    return gpios


def parse_grove_ports(value: str) -> list[str]:
    ports = [part.strip().upper() for part in value.split(",") if part.strip()]
    invalid = [port for port in ports if port not in GROVE_DIGITAL_PORTS]
    if invalid:
        choices = ", ".join(sorted(GROVE_DIGITAL_PORTS))
        raise argparse.ArgumentTypeError(
            f"unsupported Grove digital port(s): {', '.join(invalid)}; choose from {choices}"
        )
    if len(ports) != 4:
        raise argparse.ArgumentTypeError("Grove port list must contain exactly 4 ports")
    if len(set(ports)) != 4:
        raise argparse.ArgumentTypeError("Grove port list cannot contain duplicate ports")
    return ports


def rows_cols_from_grove_ports(ports: list[str]) -> tuple[list[int], list[int]]:
    flattened = [gpio for port in ports for gpio in GROVE_DIGITAL_PORTS[port]]
    return flattened[:4], flattened[4:]


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


def parse_simulated_keys(value: str) -> list[str]:
    keys = [part.strip().upper() for part in value.split(",") if part.strip()]
    valid = {key for row in KEYMAP for key in row}
    valid.update(f"S{index}" for index in range(1, 17))
    invalid = [key for key in keys if key not in valid]
    if invalid:
        raise argparse.ArgumentTypeError(f"unsupported keypad key(s): {', '.join(invalid)}")
    return keys


def physical_label_for_position(row_index: int, col_index: int) -> str:
    return f"S{row_index * 4 + col_index + 1}"


def key_position_for_physical_label(label: str) -> tuple[int, int] | None:
    normalized = label.upper()
    if not normalized.startswith("S"):
        return None
    try:
        index = int(normalized[1:])
    except ValueError:
        return None
    if not 1 <= index <= 16:
        return None
    zero_based = index - 1
    return zero_based // 4, zero_based % 4


def key_press_for_key(key: str, *, rows: list[int], cols: list[int]) -> KeyPress:
    normalized = key.upper()
    position = key_position_for_physical_label(normalized)
    if position is not None:
        row_index, col_index = position
        return KeyPress(
            key=KEYMAP[row_index][col_index],
            row_index=row_index,
            col_index=col_index,
            row_gpio=rows[row_index],
            col_gpio=cols[col_index],
        )
    for row_index, row in enumerate(KEYMAP):
        if normalized in row:
            col_index = row.index(normalized)
            return KeyPress(
                key=normalized,
                row_index=row_index,
                col_index=col_index,
                row_gpio=rows[row_index],
                col_gpio=cols[col_index],
            )
    raise ValueError(f"unsupported keypad key: {key}")


def build_key_payload(
    *,
    key_press: KeyPress,
    rows: list[int],
    cols: list[int],
    grove_ports: list[str] | None,
    active_low: bool,
    dry_run: bool,
    sequence: int,
    visual_updates: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": "pi_keypad_4x4_smoke",
        "hardware_kind": "matrix_keypad_4x4",
        "event": "press",
        "key": key_press.key,
        "physical_label": physical_label_for_position(key_press.row_index, key_press.col_index),
        "physical_label_layout": PHYSICAL_LABEL_LAYOUT,
        "sequence": sequence,
        "row_index": key_press.row_index,
        "col_index": key_press.col_index,
        "row_gpio": key_press.row_gpio,
        "col_gpio": key_press.col_gpio,
        "rows": rows,
        "cols": cols,
        "grove_ports": grove_ports,
        "active_mode": "active_low" if active_low else "active_high",
        "dry_run": dry_run,
        "suggested_control_role": KEY_ROLES.get(key_press.key, "numeric_code_candidate"),
        "sos_gesture_detected": False,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_input_only",
        "visual_updates": visual_updates,
    }


def keypad_oled_message(key_press: KeyPress) -> str:
    physical_label = physical_label_for_position(key_press.row_index, key_press.col_index)
    return "\n".join(
        [
            "SCOUT KEY",
            f"{physical_label} KEY {key_press.key}",
            f"R{key_press.row_index + 1} C{key_press.col_index + 1}",
            "DIAG ONLY",
        ]
    )


def led_bits_for_key(key_press: KeyPress) -> int:
    key_index = key_press.row_index * 4 + key_press.col_index
    bit_index = key_index % 10
    return 1 << bit_index


def write_visual_feedback(
    *,
    key_press: KeyPress,
    oled_status: bool,
    oled_dry_run: bool,
    oled_bus: Path,
    oled_address: int,
    oled_driver: str,
    led_status: bool,
    led_dry_run: bool,
    led_port: str,
    led_data_gpio: int,
    led_clock_gpio: int,
    led_blink_seconds: float,
) -> list[dict[str, Any]]:
    updates: list[dict[str, Any]] = []
    if oled_status:
        updates.append(
            write_oled_key_status(
                key_press=key_press,
                dry_run=oled_dry_run,
                bus=oled_bus,
                address=oled_address,
                driver=oled_driver,
            )
        )
    if led_status:
        updates.append(
            blink_led_key_status(
                key_press=key_press,
                dry_run=led_dry_run,
                port=led_port,
                data_gpio=led_data_gpio,
                clock_gpio=led_clock_gpio,
                blink_seconds=led_blink_seconds,
            )
        )
    return updates


def write_oled_key_status(
    *,
    key_press: KeyPress,
    dry_run: bool,
    bus: Path,
    address: int,
    driver: str,
) -> dict[str, Any]:
    message = keypad_oled_message(key_press)
    payload = {
        "target": "oled",
        "write_status": "dry_run" if dry_run else "ok",
        "bus": str(bus),
        "address": f"0x{address:02x}",
        "driver": driver,
        "message": message,
    }
    if dry_run:
        return payload
    try:
        payload["driver_attempted"] = write_display(bus=bus, address=address, driver=driver, message=message)
    except Exception as exc:
        payload["write_status"] = "error"
        payload["error"] = f"{type(exc).__name__}: {exc}"
    return payload


def blink_led_key_status(
    *,
    key_press: KeyPress,
    dry_run: bool,
    port: str,
    data_gpio: int,
    clock_gpio: int,
    blink_seconds: float,
) -> dict[str, Any]:
    bits = led_bits_for_key(key_press)
    payload = {
        "target": "led_bar",
        "write_status": "dry_run" if dry_run else "ok",
        "port": port,
        "data_gpio": data_gpio,
        "clock_gpio": clock_gpio,
        "bits": f"0x{bits:03x}",
        "blink_seconds": blink_seconds,
    }
    if dry_run:
        return payload
    writer = None
    try:
        writer = make_gpio_writer()
        write_led_bar_bits(writer, data_gpio=data_gpio, clock_gpio=clock_gpio, bits=bits)
        time.sleep(blink_seconds)
        clear_led_bar(writer, data_gpio=data_gpio, clock_gpio=clock_gpio)
    except Exception as exc:
        payload["write_status"] = "error"
        payload["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if writer is not None:
            writer.close()
    return payload


def append_jsonl(payloads: list[dict[str, Any]], output_path: Path | None) -> None:
    if output_path is None:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        for payload in payloads:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def scan_keypad_events(
    *,
    rows: list[int],
    cols: list[int],
    grove_ports: list[str] | None,
    active_low: bool,
    duration_seconds: float,
    poll_interval_ms: float,
    debounce_ms: float,
    dry_run: bool,
    simulated_keys: list[str],
    visual_options: dict[str, Any],
    event_callback: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    if dry_run:
        events: list[dict[str, Any]] = []
        for sequence, key in enumerate(simulated_keys):
            key_press = key_press_for_key(key, rows=rows, cols=cols)
            visual_updates = write_visual_feedback(key_press=key_press, **visual_options)
            event = build_key_payload(
                key_press=key_press,
                rows=rows,
                cols=cols,
                grove_ports=grove_ports,
                active_low=active_low,
                dry_run=True,
                sequence=sequence,
                visual_updates=visual_updates,
            )
            events.append(event)
            if event_callback is not None:
                event_callback(event)
        return events

    scanner = make_keypad_scanner(rows=rows, cols=cols, active_low=active_low)
    try:
        events = []
        pressed_previous: set[tuple[int, int]] = set()
        last_event_at: dict[tuple[int, int], float] = {}
        deadline = time.monotonic() + duration_seconds
        sequence = 0
        while time.monotonic() < deadline:
            pressed = scanner.scan_pressed()
            pressed_now = {(item.row_index, item.col_index) for item in pressed}
            now = time.monotonic()
            for key_press in pressed:
                key_id = (key_press.row_index, key_press.col_index)
                if key_id in pressed_previous:
                    continue
                if now - last_event_at.get(key_id, 0.0) < debounce_ms / 1000.0:
                    continue
                visual_updates = write_visual_feedback(key_press=key_press, **visual_options)
                event = build_key_payload(
                    key_press=key_press,
                    rows=rows,
                    cols=cols,
                    grove_ports=grove_ports,
                    active_low=active_low,
                    dry_run=False,
                    sequence=sequence,
                    visual_updates=visual_updates,
                )
                events.append(event)
                if event_callback is not None:
                    event_callback(event)
                sequence += 1
                last_event_at[key_id] = now
            pressed_previous = pressed_now
            time.sleep(poll_interval_ms / 1000.0)
        return events
    finally:
        scanner.close()


def build_summary(
    *,
    rows: list[int],
    cols: list[int],
    grove_ports: list[str] | None,
    active_low: bool,
    duration_seconds: float,
    dry_run: bool,
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": "pi_keypad_4x4_smoke",
        "hardware_kind": "matrix_keypad_4x4",
        "rows": rows,
        "cols": cols,
        "grove_ports": grove_ports,
        "physical_label_layout": PHYSICAL_LABEL_LAYOUT,
        "active_mode": "active_low" if active_low else "active_high",
        "duration_seconds": duration_seconds,
        "dry_run": dry_run,
        "event_count": len(events),
        "events": events,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_input_only",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke-test a 4x4 matrix keypad with Scout diagnostic boundaries.")
    parser.add_argument("--grove-ports", type=parse_grove_ports, default=DEFAULT_GROVE_PORTS)
    parser.add_argument("--rows", type=parse_gpio_list)
    parser.add_argument("--cols", type=parse_gpio_list)
    parser.add_argument("--duration-seconds", type=parse_non_negative_float, default=30.0)
    parser.add_argument("--poll-interval-ms", type=parse_positive_float, default=25.0)
    parser.add_argument("--debounce-ms", type=parse_non_negative_float, default=120.0)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--active-low", dest="active_low", action="store_true", default=False)
    mode.add_argument("--active-high", dest="active_low", action="store_false")
    parser.add_argument("--output-jsonl", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--simulate-keys", type=parse_simulated_keys, default=[])
    parser.add_argument("--oled-status", action="store_true")
    parser.add_argument("--oled-bus", type=Path, default=Path("/dev/i2c-1"))
    parser.add_argument("--oled-address", type=parse_address, default=parse_address("0x3c"))
    parser.add_argument("--oled-driver", choices=("sh1107g", "ssd1327", "auto"), default="sh1107g")
    parser.add_argument("--oled-dry-run", action="store_true")
    parser.add_argument("--led-status", action="store_true")
    parser.add_argument("--led-port", choices=sorted(PORT_DEFAULTS), default=DEFAULT_PORT)
    parser.add_argument("--led-data-gpio", type=int)
    parser.add_argument("--led-clock-gpio", type=int)
    parser.add_argument("--led-blink-seconds", type=parse_non_negative_float, default=0.25)
    parser.add_argument("--led-dry-run", action="store_true")
    args = parser.parse_args(argv)

    if (args.rows is None) != (args.cols is None):
        parser.error("--rows and --cols must be provided together")
    if args.rows is None:
        rows, cols = rows_cols_from_grove_ports(args.grove_ports)
        grove_ports = args.grove_ports
    else:
        rows = args.rows
        cols = args.cols
        grove_ports = None

    led_defaults = PORT_DEFAULTS[args.led_port]
    led_data_gpio = args.led_data_gpio if args.led_data_gpio is not None else led_defaults["data_gpio"]
    led_clock_gpio = args.led_clock_gpio if args.led_clock_gpio is not None else led_defaults["clock_gpio"]
    visual_options = {
        "oled_status": args.oled_status,
        "oled_dry_run": args.oled_dry_run,
        "oled_bus": args.oled_bus,
        "oled_address": args.oled_address,
        "oled_driver": args.oled_driver,
        "led_status": args.led_status,
        "led_dry_run": args.led_dry_run,
        "led_port": args.led_port,
        "led_data_gpio": led_data_gpio,
        "led_clock_gpio": led_clock_gpio,
        "led_blink_seconds": args.led_blink_seconds,
    }

    events = scan_keypad_events(
        rows=rows,
        cols=cols,
        grove_ports=grove_ports,
        active_low=args.active_low,
        duration_seconds=args.duration_seconds,
        poll_interval_ms=args.poll_interval_ms,
        debounce_ms=args.debounce_ms,
        dry_run=args.dry_run,
        simulated_keys=args.simulate_keys,
        visual_options=visual_options,
    )
    append_jsonl(events, args.output_jsonl)
    print(
        json.dumps(
            build_summary(
                rows=rows,
                cols=cols,
                grove_ports=grove_ports,
                active_low=args.active_low,
                duration_seconds=args.duration_seconds,
                dry_run=args.dry_run,
                events=events,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
