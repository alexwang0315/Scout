from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol


class WheelGpioReader(Protocol):
    def read_levels(self) -> tuple[int, int]: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class WheelEncoderConfig:
    left_gpio: int
    right_gpio: int
    meters_per_tick: float
    active_low: bool = False
    provider: str = "scout_gpio_wheel_encoder"


class LgpioWheelReader:
    def __init__(self, *, left_gpio: int, right_gpio: int, active_low: bool) -> None:
        import lgpio  # type: ignore

        self._lgpio = lgpio
        self._handle = lgpio.gpiochip_open(0)
        self._left_gpio = left_gpio
        self._right_gpio = right_gpio
        pull_flag = lgpio.SET_PULL_UP if active_low else lgpio.SET_PULL_DOWN
        lgpio.gpio_claim_input(self._handle, left_gpio, pull_flag)
        lgpio.gpio_claim_input(self._handle, right_gpio, pull_flag)

    def read_levels(self) -> tuple[int, int]:
        return (
            int(self._lgpio.gpio_read(self._handle, self._left_gpio)),
            int(self._lgpio.gpio_read(self._handle, self._right_gpio)),
        )

    def close(self) -> None:
        for gpio in (self._left_gpio, self._right_gpio):
            try:
                self._lgpio.gpio_free(self._handle, gpio)
            except Exception:
                pass
        self._lgpio.gpiochip_close(self._handle)


class RpiGpioWheelReader:
    def __init__(self, *, left_gpio: int, right_gpio: int, active_low: bool) -> None:
        import RPi.GPIO as GPIO  # type: ignore

        self._gpio = GPIO
        self._left_gpio = left_gpio
        self._right_gpio = right_gpio
        pull = GPIO.PUD_UP if active_low else GPIO.PUD_DOWN
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(left_gpio, GPIO.IN, pull_up_down=pull)
        GPIO.setup(right_gpio, GPIO.IN, pull_up_down=pull)

    def read_levels(self) -> tuple[int, int]:
        return (
            int(self._gpio.input(self._left_gpio)),
            int(self._gpio.input(self._right_gpio)),
        )

    def close(self) -> None:
        self._gpio.cleanup([self._left_gpio, self._right_gpio])


class GpiogetWheelReader:
    def __init__(self, *, left_gpio: int, right_gpio: int, active_low: bool, gpiochip: str) -> None:
        self._left_gpio = left_gpio
        self._right_gpio = right_gpio
        self._active_low = active_low
        self._gpiochip = gpiochip

    def read_levels(self) -> tuple[int, int]:
        command = [
            "gpioget",
            "-c",
            self._gpiochip,
            "--numeric",
        ]
        command.extend(["--bias", "pull-up" if self._active_low else "pull-down"])
        command.extend([str(self._left_gpio), str(self._right_gpio)])
        result = subprocess.run(command, text=True, capture_output=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "gpioget failed")
        values = [int(part) for part in result.stdout.strip().split()]
        if len(values) != 2:
            raise RuntimeError(f"gpioget returned {len(values)} values, expected 2: {result.stdout!r}")
        return values[0], values[1]

    def close(self) -> None:
        return None


def make_wheel_gpio_reader(
    *,
    left_gpio: int,
    right_gpio: int,
    active_low: bool,
    gpiochip: str = "gpiochip0",
) -> WheelGpioReader:
    try:
        return LgpioWheelReader(left_gpio=left_gpio, right_gpio=right_gpio, active_low=active_low)
    except Exception:
        try:
            return RpiGpioWheelReader(left_gpio=left_gpio, right_gpio=right_gpio, active_low=active_low)
        except Exception:
            return GpiogetWheelReader(
                left_gpio=left_gpio,
                right_gpio=right_gpio,
                active_low=active_low,
                gpiochip=gpiochip,
            )


def capture_wheel_encoder_records(
    *,
    left_gpio: int,
    right_gpio: int,
    meters_per_tick: float,
    duration_seconds: float,
    sample_interval_seconds: float,
    poll_interval_ms: float,
    active_low: bool = False,
    gpiochip: str = "gpiochip0",
    provider: str = "scout_gpio_wheel_encoder",
    reader: WheelGpioReader | None = None,
) -> list[dict[str, Any]]:
    _validate_capture_args(
        left_gpio=left_gpio,
        right_gpio=right_gpio,
        meters_per_tick=meters_per_tick,
        duration_seconds=duration_seconds,
        sample_interval_seconds=sample_interval_seconds,
        poll_interval_ms=poll_interval_ms,
    )
    close_reader = reader is None
    live_reader = reader or make_wheel_gpio_reader(
        left_gpio=left_gpio,
        right_gpio=right_gpio,
        active_low=active_low,
        gpiochip=gpiochip,
    )
    try:
        active_level = 0 if active_low else 1
        left_ticks = 0
        right_ticks = 0
        previous_left, previous_right = live_reader.read_levels()
        left_level_change_count = 0
        right_level_change_count = 0
        poll_count = 0
        left_high_poll_count = 0
        right_high_poll_count = 0
        start_monotonic = time.monotonic()
        next_sample = start_monotonic
        deadline = start_monotonic + duration_seconds
        records: list[dict[str, Any]] = []

        while True:
            now = time.monotonic()
            left_level, right_level = live_reader.read_levels()
            poll_count += 1
            left_high_poll_count += int(left_level == 1)
            right_high_poll_count += int(right_level == 1)
            if previous_left != left_level:
                left_level_change_count += 1
            if previous_right != right_level:
                right_level_change_count += 1
            if previous_left != active_level and left_level == active_level:
                left_ticks += 1
            if previous_right != active_level and right_level == active_level:
                right_ticks += 1
            previous_left, previous_right = left_level, right_level

            if now >= next_sample or not records:
                records.append(
                    build_wheel_encoder_record(
                        config=WheelEncoderConfig(
                            left_gpio=left_gpio,
                            right_gpio=right_gpio,
                            meters_per_tick=meters_per_tick,
                            active_low=active_low,
                            provider=provider,
                        ),
                        timestamp_s=time.time(),
                        left_ticks=left_ticks,
                        right_ticks=right_ticks,
                        left_level=left_level,
                        right_level=right_level,
                        left_level_change_count=left_level_change_count,
                        right_level_change_count=right_level_change_count,
                        poll_count=poll_count,
                        left_high_poll_count=left_high_poll_count,
                        right_high_poll_count=right_high_poll_count,
                        dry_run=False,
                    )
                )
                next_sample += sample_interval_seconds

            if now >= deadline:
                break
            time.sleep(min(poll_interval_ms / 1000.0, max(0.0, deadline - now)))

        if len(records) < 2 or (
            records[-1]["wheel"]["left_ticks"] != left_ticks
            or records[-1]["wheel"]["right_ticks"] != right_ticks
        ):
            records.append(
                build_wheel_encoder_record(
                    config=WheelEncoderConfig(
                        left_gpio=left_gpio,
                        right_gpio=right_gpio,
                        meters_per_tick=meters_per_tick,
                        active_low=active_low,
                        provider=provider,
                    ),
                    timestamp_s=time.time(),
                    left_ticks=left_ticks,
                    right_ticks=right_ticks,
                    left_level=previous_left,
                    right_level=previous_right,
                    left_level_change_count=left_level_change_count,
                    right_level_change_count=right_level_change_count,
                    poll_count=poll_count,
                    left_high_poll_count=left_high_poll_count,
                    right_high_poll_count=right_high_poll_count,
                    dry_run=False,
                )
            )
        return records
    finally:
        if close_reader:
            live_reader.close()


def build_wheel_encoder_records_from_ticks(
    *,
    left_ticks: list[int],
    right_ticks: list[int],
    meters_per_tick: float,
    sample_interval_seconds: float = 1.0,
    start_timestamp_s: float = 10.0,
    left_gpio: int = 20,
    right_gpio: int = 21,
    active_low: bool = False,
    provider: str = "scout_gpio_wheel_encoder",
    dry_run: bool = True,
) -> list[dict[str, Any]]:
    if len(left_ticks) != len(right_ticks):
        raise ValueError("left and right tick sequences must have the same length")
    if len(left_ticks) < 2:
        raise ValueError("at least two tick samples are required")
    if sample_interval_seconds <= 0:
        raise ValueError("sample_interval_seconds must be positive")
    _validate_tick_sequence(left_ticks, name="left_ticks")
    _validate_tick_sequence(right_ticks, name="right_ticks")
    if meters_per_tick <= 0:
        raise ValueError("meters_per_tick must be positive")
    config = WheelEncoderConfig(
        left_gpio=left_gpio,
        right_gpio=right_gpio,
        meters_per_tick=meters_per_tick,
        active_low=active_low,
        provider=provider,
    )
    return [
        build_wheel_encoder_record(
            config=config,
            timestamp_s=start_timestamp_s + index * sample_interval_seconds,
            left_ticks=left_tick,
            right_ticks=right_tick,
            dry_run=dry_run,
        )
        for index, (left_tick, right_tick) in enumerate(zip(left_ticks, right_ticks))
    ]


def build_wheel_encoder_record(
    *,
    config: WheelEncoderConfig,
    timestamp_s: float,
    left_ticks: int,
    right_ticks: int,
    dry_run: bool,
    left_level: int | None = None,
    right_level: int | None = None,
    left_level_change_count: int | None = None,
    right_level_change_count: int | None = None,
    poll_count: int | None = None,
    left_high_poll_count: int | None = None,
    right_high_poll_count: int | None = None,
) -> dict[str, Any]:
    left_distance_m = left_ticks * config.meters_per_tick
    right_distance_m = right_ticks * config.meters_per_tick
    cumulative_distance_m = (left_distance_m + right_distance_m) / 2.0
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": "pi_wheel_encoder_gpio_smoke",
        "provider": config.provider,
        "hardware_kind": "gpio_wheel_encoder_odometry",
        "timestamp_s": timestamp_s,
        "dry_run": dry_run,
        "wheel": {
            "left_gpio": config.left_gpio,
            "right_gpio": config.right_gpio,
            "active_low": config.active_low,
            "left_ticks": left_ticks,
            "right_ticks": right_ticks,
            "meters_per_tick": config.meters_per_tick,
            "left_distance_m": left_distance_m,
            "right_distance_m": right_distance_m,
            "cumulative_distance_m": cumulative_distance_m,
            "left_level": left_level,
            "right_level": right_level,
            "left_level_change_count": left_level_change_count,
            "right_level_change_count": right_level_change_count,
            "poll_count": poll_count,
            "left_high_poll_count": left_high_poll_count,
            "right_high_poll_count": right_high_poll_count,
        },
        "odometry": {
            "cumulative_distance_m": cumulative_distance_m,
        },
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "primary_truth_allowed": False,
        "raw_evidence_required": True,
        "replay_audit_supported": not dry_run,
        "hardware_control_scope": "diagnostic_gpio_wheel_encoder_capture_only",
    }


def write_jsonl(records: list[dict[str, Any]], output_path: Path | None) -> None:
    if output_path is None:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )


def summarize_wheel_encoder_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    usable = [record for record in records if isinstance(record.get("wheel"), dict) and isinstance(record.get("odometry"), dict)]
    dry_run_count = sum(1 for record in records if record.get("dry_run") is True)
    first = usable[0] if usable else {}
    final = usable[-1] if usable else {}
    first_wheel = first.get("wheel") if isinstance(first.get("wheel"), dict) else {}
    final_wheel = final.get("wheel") if isinstance(final.get("wheel"), dict) else {}
    first_odometry = first.get("odometry") if isinstance(first.get("odometry"), dict) else {}
    final_odometry = final.get("odometry") if isinstance(final.get("odometry"), dict) else {}
    left_tick_delta = _delta(first_wheel.get("left_ticks"), final_wheel.get("left_ticks"))
    right_tick_delta = _delta(first_wheel.get("right_ticks"), final_wheel.get("right_ticks"))
    left_level_change_delta = _delta(
        first_wheel.get("left_level_change_count"),
        final_wheel.get("left_level_change_count"),
    )
    right_level_change_delta = _delta(
        first_wheel.get("right_level_change_count"),
        final_wheel.get("right_level_change_count"),
    )
    distance_delta_m = _delta(first_odometry.get("cumulative_distance_m"), final_odometry.get("cumulative_distance_m"))
    positive_tick_delta_observed = (left_tick_delta or 0) > 0 or (right_tick_delta or 0) > 0
    positive_distance_delta_observed = (distance_delta_m or 0) > 0
    line_activity_observed = (left_level_change_delta or 0) > 0 or (right_level_change_delta or 0) > 0
    live_positive_movement_ready = bool(
        usable
        and dry_run_count == 0
        and (positive_tick_delta_observed or positive_distance_delta_observed)
    )
    if not usable:
        missing_reason = "no_usable_wheel_records"
    elif dry_run_count > 0:
        missing_reason = "dry_run_not_navigation_evidence"
    elif not live_positive_movement_ready:
        missing_reason = "no_positive_wheel_motion_observed"
    else:
        missing_reason = None
    return {
        "source": "pi_wheel_encoder_gpio_smoke",
        "artifact_kind": "wheel_encoder_gpio_movement_summary",
        "record_count": len(records),
        "usable_record_count": len(usable),
        "dry_run_record_count": dry_run_count,
        "initial_left_ticks": first_wheel.get("left_ticks"),
        "initial_right_ticks": first_wheel.get("right_ticks"),
        "final_left_ticks": final_wheel.get("left_ticks"),
        "final_right_ticks": final_wheel.get("right_ticks"),
        "left_tick_delta": left_tick_delta,
        "right_tick_delta": right_tick_delta,
        "total_tick_delta": (left_tick_delta or 0) + (right_tick_delta or 0)
        if left_tick_delta is not None or right_tick_delta is not None
        else None,
        "initial_left_level": first_wheel.get("left_level"),
        "initial_right_level": first_wheel.get("right_level"),
        "final_left_level": final_wheel.get("left_level"),
        "final_right_level": final_wheel.get("right_level"),
        "left_level_change_delta": left_level_change_delta,
        "right_level_change_delta": right_level_change_delta,
        "line_activity_observed": line_activity_observed,
        "final_poll_count": final_wheel.get("poll_count"),
        "final_left_high_poll_count": final_wheel.get("left_high_poll_count"),
        "final_right_high_poll_count": final_wheel.get("right_high_poll_count"),
        "initial_cumulative_distance_m": first_odometry.get("cumulative_distance_m"),
        "final_cumulative_distance_m": final_odometry.get("cumulative_distance_m"),
        "distance_delta_m": distance_delta_m,
        "positive_tick_delta_observed": positive_tick_delta_observed,
        "positive_distance_delta_observed": positive_distance_delta_observed,
        "wheel_movement_observed": positive_tick_delta_observed or positive_distance_delta_observed,
        "live_positive_wheel_movement_ready": live_positive_movement_ready,
        "missing_reason": missing_reason,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "primary_truth_allowed": False,
        "hardware_control_scope": "diagnostic_gpio_wheel_encoder_capture_only",
    }


def _delta(initial: Any, final: Any) -> float | int | None:
    if initial is None or final is None:
        return None
    try:
        result = final - initial
    except TypeError:
        return None
    if isinstance(result, float):
        return round(result, 9)
    return result


def parse_int_sequence(value: str) -> list[int]:
    try:
        values = [int(part.strip()) for part in value.split(",") if part.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("tick sequence must contain comma-separated integers") from exc
    try:
        _validate_tick_sequence(values, name="tick sequence")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return values


def parse_positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def parse_non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return parsed


def _validate_capture_args(
    *,
    left_gpio: int,
    right_gpio: int,
    meters_per_tick: float,
    duration_seconds: float,
    sample_interval_seconds: float,
    poll_interval_ms: float,
) -> None:
    if left_gpio == right_gpio:
        raise ValueError("left_gpio and right_gpio must be different")
    if meters_per_tick <= 0:
        raise ValueError("meters_per_tick must be positive")
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")
    if sample_interval_seconds <= 0:
        raise ValueError("sample_interval_seconds must be positive")
    if poll_interval_ms <= 0:
        raise ValueError("poll_interval_ms must be positive")


def _validate_tick_sequence(values: list[int], *, name: str) -> None:
    if not values:
        raise ValueError(f"{name} must not be empty")
    previous = values[0]
    if previous < 0:
        raise ValueError(f"{name} cannot contain negative ticks")
    for value in values[1:]:
        if value < previous:
            raise ValueError(f"{name} must be monotonic")
        previous = value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture Scout wheel encoder ticks from two GPIO inputs.")
    parser.add_argument("--left-gpio", type=int, default=20)
    parser.add_argument("--right-gpio", type=int, default=21)
    parser.add_argument("--meters-per-tick", type=parse_positive_float, required=True)
    parser.add_argument("--duration-seconds", type=parse_positive_float, default=5.0)
    parser.add_argument("--sample-interval-seconds", type=parse_positive_float, default=1.0)
    parser.add_argument("--poll-interval-ms", type=parse_positive_float, default=5.0)
    parser.add_argument("--active-low", action="store_true")
    parser.add_argument("--gpiochip", default="gpiochip0")
    parser.add_argument("--provider", default="scout_gpio_wheel_encoder")
    parser.add_argument("--output-jsonl", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--simulate-left-ticks", type=parse_int_sequence, default=[0, 10])
    parser.add_argument("--simulate-right-ticks", type=parse_int_sequence, default=[0, 10])
    parser.add_argument(
        "--require-live-positive-movement",
        action="store_true",
        help="Exit 1 unless non-dry-run GPIO evidence shows positive wheel tick or distance movement.",
    )
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    try:
        records = (
            build_wheel_encoder_records_from_ticks(
                left_ticks=args.simulate_left_ticks,
                right_ticks=args.simulate_right_ticks,
                meters_per_tick=args.meters_per_tick,
                sample_interval_seconds=args.sample_interval_seconds,
                left_gpio=args.left_gpio,
                right_gpio=args.right_gpio,
                active_low=args.active_low,
                provider=args.provider,
                dry_run=True,
            )
            if args.dry_run
            else capture_wheel_encoder_records(
                left_gpio=args.left_gpio,
                right_gpio=args.right_gpio,
                meters_per_tick=args.meters_per_tick,
                duration_seconds=args.duration_seconds,
                sample_interval_seconds=args.sample_interval_seconds,
                poll_interval_ms=args.poll_interval_ms,
                active_low=args.active_low,
                gpiochip=args.gpiochip,
                provider=args.provider,
            )
        )
        write_jsonl(records, args.output_jsonl)
        movement_summary = summarize_wheel_encoder_records(records)
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    report = {
        "source": "pi_wheel_encoder_gpio_smoke",
        "hardware_kind": "gpio_wheel_encoder_odometry_report",
        "record_count": len(records),
        "output_jsonl": str(args.output_jsonl) if args.output_jsonl else None,
        "dry_run": args.dry_run,
        "provider": args.provider,
        "left_gpio": args.left_gpio,
        "right_gpio": args.right_gpio,
        "meters_per_tick": args.meters_per_tick,
        "final_left_ticks": records[-1]["wheel"]["left_ticks"] if records else None,
        "final_right_ticks": records[-1]["wheel"]["right_ticks"] if records else None,
        "final_cumulative_distance_m": records[-1]["odometry"]["cumulative_distance_m"] if records else None,
        "movement_summary": movement_summary,
        "left_tick_delta": movement_summary["left_tick_delta"],
        "right_tick_delta": movement_summary["right_tick_delta"],
        "left_level_change_delta": movement_summary["left_level_change_delta"],
        "right_level_change_delta": movement_summary["right_level_change_delta"],
        "line_activity_observed": movement_summary["line_activity_observed"],
        "distance_delta_m": movement_summary["distance_delta_m"],
        "wheel_movement_observed": movement_summary["wheel_movement_observed"],
        "live_positive_wheel_movement_ready": movement_summary["live_positive_wheel_movement_ready"],
        "missing_reason": movement_summary["missing_reason"],
        "require_live_positive_movement": args.require_live_positive_movement,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "primary_truth_allowed": False,
        "hardware_control_scope": "diagnostic_gpio_wheel_encoder_capture_only",
        "records": records,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=not args.pretty))
    if args.require_live_positive_movement and movement_summary["live_positive_wheel_movement_ready"] is not True:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
