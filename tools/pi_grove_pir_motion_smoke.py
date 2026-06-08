from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

try:
    from tools.pi_grove_led_bar_smoke import DEFAULT_PORT as DEFAULT_LED_PORT
    from tools.pi_grove_led_bar_smoke import PORT_DEFAULTS, clear_led_bar, make_gpio_writer, write_led_bar_bits
    from tools.pi_oled_i2c_smoke import parse_address, write_display
except ImportError:  # pragma: no cover - used when executed directly from tools/ on a Pi.
    from pi_grove_led_bar_smoke import DEFAULT_PORT as DEFAULT_LED_PORT
    from pi_grove_led_bar_smoke import PORT_DEFAULTS, clear_led_bar, make_gpio_writer, write_led_bar_bits
    from pi_oled_i2c_smoke import parse_address, write_display


GROVE_DIGITAL_PORTS = {
    "D5": (5, 6),
    "D16": (16, 17),
    "D18": (18, 19),
    "D22": (22, 23),
    "D24": (24, 25),
    "D26": (26, 27),
}
DEFAULT_PORT = "D22"
DEFAULT_SIGNAL_INDEX = 0
DEFAULT_LED_MOTION_BIT = 2


class DigitalReader(Protocol):
    def read(self) -> int: ...

    def close(self) -> None: ...


class LgpioDigitalReader:
    def __init__(self, *, gpio: int, active_low: bool) -> None:
        import lgpio  # type: ignore

        self._lgpio = lgpio
        self._handle = lgpio.gpiochip_open(0)
        self._gpio = gpio
        pull_flag = lgpio.SET_PULL_UP if active_low else lgpio.SET_PULL_DOWN
        lgpio.gpio_claim_input(self._handle, gpio, pull_flag)

    def read(self) -> int:
        return int(self._lgpio.gpio_read(self._handle, self._gpio))

    def close(self) -> None:
        try:
            self._lgpio.gpio_free(self._handle, self._gpio)
        finally:
            self._lgpio.gpiochip_close(self._handle)


class RpiGpioDigitalReader:
    def __init__(self, *, gpio: int, active_low: bool) -> None:
        import RPi.GPIO as GPIO  # type: ignore

        self._gpio_module = GPIO
        self._gpio = gpio
        pull = GPIO.PUD_UP if active_low else GPIO.PUD_DOWN
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(gpio, GPIO.IN, pull_up_down=pull)

    def read(self) -> int:
        return int(self._gpio_module.input(self._gpio))

    def close(self) -> None:
        self._gpio_module.cleanup([self._gpio])


@dataclass(frozen=True)
class MotionObservation:
    event: str
    level: int
    motion_detected: bool


def make_digital_reader(*, gpio: int, active_low: bool) -> DigitalReader:
    try:
        return LgpioDigitalReader(gpio=gpio, active_low=active_low)
    except Exception:
        return RpiGpioDigitalReader(gpio=gpio, active_low=active_low)


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


def parse_signal_index(value: str) -> int:
    parsed = int(value)
    if parsed not in {0, 1}:
        raise argparse.ArgumentTypeError("signal index must be 0 or 1")
    return parsed


def parse_led_bit(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 10:
        raise argparse.ArgumentTypeError("LED bit must be between 1 and 10")
    return parsed


def parse_simulated_levels(value: str) -> list[int]:
    aliases = {
        "0": 0,
        "LOW": 0,
        "IDLE": 0,
        "NO_MOTION": 0,
        "1": 1,
        "HIGH": 1,
        "MOTION": 1,
    }
    levels: list[int] = []
    invalid: list[str] = []
    for part in [candidate.strip().upper() for candidate in value.split(",") if candidate.strip()]:
        if part not in aliases:
            invalid.append(part)
        else:
            levels.append(aliases[part])
    if invalid:
        raise argparse.ArgumentTypeError(f"unsupported simulated level(s): {', '.join(invalid)}")
    if not levels:
        raise argparse.ArgumentTypeError("simulated levels cannot be empty")
    return levels


def gpio_from_port(*, port: str, signal_index: int) -> int:
    return GROVE_DIGITAL_PORTS[port][signal_index]


def motion_from_level(level: int, *, active_low: bool) -> bool:
    active_level = 0 if active_low else 1
    return level == active_level


def observation_for_level(
    *,
    level: int,
    previous_motion: bool | None,
    active_low: bool,
) -> MotionObservation | None:
    motion_detected = motion_from_level(level, active_low=active_low)
    if previous_motion is None:
        return MotionObservation(
            event="motion_present" if motion_detected else "motion_idle",
            level=level,
            motion_detected=motion_detected,
        )
    if motion_detected == previous_motion:
        return None
    return MotionObservation(
        event="motion_start" if motion_detected else "motion_end",
        level=level,
        motion_detected=motion_detected,
    )


def build_motion_payload(
    *,
    observation: MotionObservation,
    sequence: int,
    port: str,
    signal_index: int,
    gpio: int,
    active_low: bool,
    dry_run: bool,
    visual_updates: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": "pi_grove_pir_motion_smoke",
        "hardware_kind": "grove_mini_pir_motion_sensor",
        "event": observation.event,
        "sequence": sequence,
        "port": port,
        "signal_index": signal_index,
        "gpio": gpio,
        "level": observation.level,
        "motion_detected": observation.motion_detected,
        "active_mode": "active_low" if active_low else "active_high",
        "candidate_evidence_kind": "nearby_motion_candidate",
        "dry_run": dry_run,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_input_only",
        "visual_updates": visual_updates,
    }


def pir_oled_message(payload: dict[str, Any]) -> str:
    state = "MOTION" if payload["motion_detected"] else "IDLE"
    return "\n".join(
        [
            "SCOUT PIR",
            state,
            f"{payload['port']} GPIO{payload['gpio']}",
            payload["event"].upper()[:16],
            "DIAG ONLY",
        ]
    )


def write_oled_motion_status(
    *,
    payload: dict[str, Any],
    dry_run: bool,
    bus: Path,
    address: int,
    driver: str,
) -> dict[str, Any]:
    message = pir_oled_message(payload)
    status = {
        "target": "oled",
        "write_status": "dry_run" if dry_run else "ok",
        "bus": str(bus),
        "address": f"0x{address:02x}",
        "driver": driver,
        "message": message,
    }
    if dry_run:
        return status
    try:
        status["driver_attempted"] = write_display(bus=bus, address=address, driver=driver, message=message)
    except Exception as exc:
        status["write_status"] = "error"
        status["error"] = f"{type(exc).__name__}: {exc}"
    return status


def write_led_motion_status(
    *,
    motion_detected: bool,
    dry_run: bool,
    port: str,
    data_gpio: int,
    clock_gpio: int,
    motion_bit: int,
    blink_seconds: float,
) -> dict[str, Any]:
    bits = 1 << (motion_bit - 1) if motion_detected else 0
    status = {
        "target": "led_bar",
        "write_status": "dry_run" if dry_run else "ok",
        "port": port,
        "data_gpio": data_gpio,
        "clock_gpio": clock_gpio,
        "bits": f"0x{bits:03x}",
        "motion_led_bit": motion_bit,
        "blink_seconds": blink_seconds,
    }
    if dry_run:
        return status
    writer = None
    try:
        writer = make_gpio_writer()
        write_led_bar_bits(writer, data_gpio=data_gpio, clock_gpio=clock_gpio, bits=bits)
        if motion_detected and blink_seconds > 0:
            time.sleep(blink_seconds)
            clear_led_bar(writer, data_gpio=data_gpio, clock_gpio=clock_gpio)
    except Exception as exc:
        status["write_status"] = "error"
        status["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if writer is not None:
            writer.close()
    return status


def write_visual_feedback(
    *,
    payload: dict[str, Any],
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
    led_motion_bit: int,
    led_blink_seconds: float,
) -> list[dict[str, Any]]:
    updates: list[dict[str, Any]] = []
    if oled_status:
        updates.append(
            write_oled_motion_status(
                payload=payload,
                dry_run=oled_dry_run,
                bus=oled_bus,
                address=oled_address,
                driver=oled_driver,
            )
        )
    if led_status:
        updates.append(
            write_led_motion_status(
                motion_detected=payload["motion_detected"],
                dry_run=led_dry_run,
                port=led_port,
                data_gpio=led_data_gpio,
                clock_gpio=led_clock_gpio,
                motion_bit=led_motion_bit,
                blink_seconds=led_blink_seconds,
            )
        )
    return updates


def append_jsonl(payloads: list[dict[str, Any]], output_path: Path | None) -> None:
    if output_path is None:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        for payload in payloads:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def capture_motion_events(
    *,
    port: str,
    signal_index: int,
    gpio: int,
    active_low: bool,
    duration_seconds: float,
    poll_interval_ms: float,
    debounce_ms: float,
    dry_run: bool,
    simulated_levels: list[int],
    visual_options: dict[str, Any],
) -> list[dict[str, Any]]:
    previous_motion: bool | None = None
    last_event_at = 0.0
    events: list[dict[str, Any]] = []

    def append_level(level: int, *, now: float, is_dry_run: bool) -> None:
        nonlocal previous_motion, last_event_at
        observation = observation_for_level(level=level, previous_motion=previous_motion, active_low=active_low)
        previous_motion = motion_from_level(level, active_low=active_low)
        if observation is None:
            return
        if last_event_at and now - last_event_at < debounce_ms / 1000.0:
            return
        payload = build_motion_payload(
            observation=observation,
            sequence=len(events),
            port=port,
            signal_index=signal_index,
            gpio=gpio,
            active_low=active_low,
            dry_run=is_dry_run,
            visual_updates=[],
        )
        payload["visual_updates"] = write_visual_feedback(payload=payload, **visual_options)
        events.append(payload)
        last_event_at = now

    if dry_run:
        for offset, level in enumerate(simulated_levels):
            append_level(level, now=float(offset), is_dry_run=True)
        return events

    reader = make_digital_reader(gpio=gpio, active_low=active_low)
    try:
        deadline = time.monotonic() + duration_seconds
        while time.monotonic() < deadline:
            append_level(reader.read(), now=time.monotonic(), is_dry_run=False)
            time.sleep(poll_interval_ms / 1000.0)
        return events
    finally:
        reader.close()


def build_summary(
    *,
    port: str,
    signal_index: int,
    gpio: int,
    active_low: bool,
    duration_seconds: float,
    dry_run: bool,
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": "pi_grove_pir_motion_smoke",
        "hardware_kind": "grove_mini_pir_motion_sensor",
        "port": port,
        "signal_index": signal_index,
        "gpio": gpio,
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
    parser = argparse.ArgumentParser(description="Smoke-test a Grove mini PIR motion sensor as diagnostic input.")
    parser.add_argument("--port", choices=sorted(GROVE_DIGITAL_PORTS), default=DEFAULT_PORT)
    parser.add_argument("--signal-index", type=parse_signal_index, default=DEFAULT_SIGNAL_INDEX)
    parser.add_argument("--gpio", type=int)
    parser.add_argument("--duration-seconds", type=parse_non_negative_float, default=30.0)
    parser.add_argument("--poll-interval-ms", type=parse_positive_float, default=50.0)
    parser.add_argument("--debounce-ms", type=parse_non_negative_float, default=200.0)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--active-low", dest="active_low", action="store_true", default=False)
    mode.add_argument("--active-high", dest="active_low", action="store_false")
    parser.add_argument("--output-jsonl", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--simulate-levels", type=parse_simulated_levels, default=[0, 1, 1, 0])
    parser.add_argument("--oled-status", action="store_true")
    parser.add_argument("--oled-bus", type=Path, default=Path("/dev/i2c-1"))
    parser.add_argument("--oled-address", type=parse_address, default=parse_address("0x3c"))
    parser.add_argument("--oled-driver", choices=("sh1107g", "ssd1327", "auto"), default="sh1107g")
    parser.add_argument("--oled-dry-run", action="store_true")
    parser.add_argument("--led-status", action="store_true")
    parser.add_argument("--led-port", choices=sorted(PORT_DEFAULTS), default=DEFAULT_LED_PORT)
    parser.add_argument("--led-data-gpio", type=int)
    parser.add_argument("--led-clock-gpio", type=int)
    parser.add_argument("--led-motion-bit", type=parse_led_bit, default=DEFAULT_LED_MOTION_BIT)
    parser.add_argument("--led-blink-seconds", type=parse_non_negative_float, default=0.35)
    parser.add_argument("--led-dry-run", action="store_true")
    args = parser.parse_args(argv)

    gpio = args.gpio if args.gpio is not None else gpio_from_port(port=args.port, signal_index=args.signal_index)
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
        "led_motion_bit": args.led_motion_bit,
        "led_blink_seconds": args.led_blink_seconds,
    }
    events = capture_motion_events(
        port=args.port,
        signal_index=args.signal_index,
        gpio=gpio,
        active_low=args.active_low,
        duration_seconds=args.duration_seconds,
        poll_interval_ms=args.poll_interval_ms,
        debounce_ms=args.debounce_ms,
        dry_run=args.dry_run,
        simulated_levels=args.simulate_levels,
        visual_options=visual_options,
    )
    append_jsonl(events, args.output_jsonl)
    print(
        json.dumps(
            build_summary(
                port=args.port,
                signal_index=args.signal_index,
                gpio=gpio,
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
