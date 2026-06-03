from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from tools.pi_grove_led_bar_smoke import DEFAULT_PORT as DEFAULT_LED_PORT
    from tools.pi_grove_led_bar_smoke import PORT_DEFAULTS, make_gpio_writer, write_led_bar_bits
    from tools.pi_oled_i2c_smoke import parse_address, write_display
    from tools.pi_ups_hat_e_smoke import (
        DEFAULT_ADDRESS,
        DEFAULT_BUS,
        DEFAULT_LOW_CELL_MV,
        HARDWARE_KIND as UPS_HARDWARE_KIND,
        build_ups_payload,
        canned_ups_sample,
        parse_led_bit,
        parse_non_negative_float,
        parse_positive_int,
        read_ups_hat_e_sample,
    )
except ImportError:  # pragma: no cover - used when executed directly from tools/ on a Pi.
    from pi_grove_led_bar_smoke import DEFAULT_PORT as DEFAULT_LED_PORT
    from pi_grove_led_bar_smoke import PORT_DEFAULTS, make_gpio_writer, write_led_bar_bits
    from pi_oled_i2c_smoke import parse_address, write_display
    from pi_ups_hat_e_smoke import (
        DEFAULT_ADDRESS,
        DEFAULT_BUS,
        DEFAULT_LOW_CELL_MV,
        HARDWARE_KIND as UPS_HARDWARE_KIND,
        build_ups_payload,
        canned_ups_sample,
        parse_led_bit,
        parse_non_negative_float,
        parse_positive_int,
        read_ups_hat_e_sample,
    )


SOURCE = "pi_ups_hat_e_monitor"
HARDWARE_KIND = "waveshare_ups_hat_e_i2c_monitor"
DEFAULT_LOW_PERCENT = 10
DEFAULT_FULL_PERCENT = 100
DEFAULT_OK_LED_BIT = 7
DEFAULT_ON_BATTERY_LED_BIT = 1
DEFAULT_CHARGING_LED_BIT = 2
DEFAULT_FAST_CHARGING_LED_BIT = 3
DEFAULT_FULL_LED_BIT = 8
DEFAULT_LOW_LED_BIT = 10


def parse_percent(value: str) -> int:
    parsed = int(value)
    if not 0 <= parsed <= 100:
        raise argparse.ArgumentTypeError("percent must be between 0 and 100")
    return parsed


def parse_signed_int(value: str) -> int:
    return int(value)


def effective_power_state(sample: dict[str, Any]) -> str:
    battery = sample["battery"]
    vbus = sample["vbus"]
    if int(vbus.get("power_mw") or 0) <= 0 and int(battery.get("current_ma") or 0) < 0:
        return "on_battery"
    if sample.get("power_state") == "fast_charging":
        return "fast_charging"
    if sample.get("power_state") == "charging" or int(battery.get("current_ma") or 0) > 0:
        return "charging"
    if int(battery.get("current_ma") or 0) < 0:
        return "on_battery"
    return str(sample.get("power_state") or "idle")


def battery_load_w(sample: dict[str, Any]) -> float | None:
    current_ma = int(sample["battery"]["current_ma"])
    if current_ma >= 0:
        return None
    return sample["battery"]["voltage_mv"] * abs(current_ma) / 1_000_000


def battery_charge_w(sample: dict[str, Any]) -> float | None:
    current_ma = int(sample["battery"]["current_ma"])
    if current_ma <= 0:
        return None
    return sample["battery"]["voltage_mv"] * current_ma / 1_000_000


def classify_alerts(
    sample: dict[str, Any],
    *,
    low_percent: int,
    full_percent: int,
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    percent = int(sample["battery"]["percent"])
    if percent <= low_percent:
        alerts.append(
            {
                "alert_key": "battery_percent_low",
                "severity": "critical",
                "message": f"UPS battery percent is at or below {low_percent}%",
                "threshold_percent": low_percent,
                "observed_percent": percent,
            }
        )
    if sample.get("low_cell_voltage_present") is True:
        alerts.append(
            {
                "alert_key": "cell_voltage_low",
                "severity": "critical",
                "message": "UPS reports at least one cell below low-cell threshold",
                "low_cell_threshold_mv": sample.get("low_cell_threshold_mv"),
                "cell_voltage_mv": sample.get("cell_voltage_mv"),
            }
        )
    if percent >= full_percent:
        alerts.append(
            {
                "alert_key": "battery_percent_full",
                "severity": "info",
                "message": f"UPS battery percent is at or above {full_percent}%",
                "threshold_percent": full_percent,
                "observed_percent": percent,
            }
        )
    return alerts


def alert_keys(alerts: list[dict[str, Any]]) -> list[str]:
    return sorted(str(alert["alert_key"]) for alert in alerts)


def load_state(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {"active_alert_keys": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path | None, state: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def monitor_oled_message(payload: dict[str, Any]) -> str:
    sample = payload["ups"]
    battery = sample["battery"]
    vbus = sample["vbus"]
    alerts = payload["alerts"]
    if any(alert["alert_key"] == "battery_percent_low" for alert in alerts):
        headline = "LOW BATTERY"
    elif any(alert["alert_key"] == "cell_voltage_low" for alert in alerts):
        headline = "LOW CELL"
    elif any(alert["alert_key"] == "battery_percent_full" for alert in alerts):
        headline = "FULL 100%"
    else:
        headline = effective_power_state(sample).upper()[:21]
    load_w = battery_load_w(sample)
    charge_w = battery_charge_w(sample)
    power_line = f"LOAD {load_w:.1f}W" if load_w is not None else f"CHG {charge_w or 0:.1f}W"
    return "\n".join(
        [
            "SCOUT UPS MON",
            headline,
            f"BAT {battery['percent']}%",
            f"BV {battery['voltage_mv'] / 1000:.2f}V",
            f"BI {battery['current_ma'] / 1000:.2f}A",
            power_line,
            f"VBUS {vbus['power_mw'] / 1000:.1f}W",
            "DIAG ONLY",
        ]
    )


def led_bits_for_monitor(
    payload: dict[str, Any],
    *,
    ok_bit: int,
    on_battery_bit: int,
    charging_bit: int,
    fast_charging_bit: int,
    full_bit: int,
    low_bit: int,
) -> int:
    keys = set(alert_keys(payload["alerts"]))
    if "battery_percent_low" in keys or "cell_voltage_low" in keys:
        return 1 << (low_bit - 1)
    if "battery_percent_full" in keys:
        return 1 << (full_bit - 1)
    state = effective_power_state(payload["ups"])
    if state == "on_battery":
        return 1 << (on_battery_bit - 1)
    if state == "fast_charging":
        return 1 << (fast_charging_bit - 1)
    if state == "charging":
        return 1 << (charging_bit - 1)
    return 1 << (ok_bit - 1)


def write_oled_monitor_status(
    *,
    payload: dict[str, Any],
    dry_run: bool,
    bus: Path,
    address: int,
    driver: str,
) -> dict[str, Any]:
    message = monitor_oled_message(payload)
    status: dict[str, Any] = {
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


def write_led_monitor_status(
    *,
    payload: dict[str, Any],
    dry_run: bool,
    port: str,
    data_gpio: int,
    clock_gpio: int,
    ok_bit: int,
    on_battery_bit: int,
    charging_bit: int,
    fast_charging_bit: int,
    full_bit: int,
    low_bit: int,
) -> dict[str, Any]:
    bits = led_bits_for_monitor(
        payload,
        ok_bit=ok_bit,
        on_battery_bit=on_battery_bit,
        charging_bit=charging_bit,
        fast_charging_bit=fast_charging_bit,
        full_bit=full_bit,
        low_bit=low_bit,
    )
    status: dict[str, Any] = {
        "target": "led_bar",
        "write_status": "dry_run" if dry_run else "ok",
        "port": port,
        "data_gpio": data_gpio,
        "clock_gpio": clock_gpio,
        "bits": f"0x{bits:03x}",
        "ok_led_bit": ok_bit,
        "on_battery_led_bit": on_battery_bit,
        "charging_led_bit": charging_bit,
        "fast_charging_led_bit": fast_charging_bit,
        "full_led_bit": full_bit,
        "low_led_bit": low_bit,
    }
    if dry_run:
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


def apply_dry_run_overrides(
    sample: dict[str, Any],
    *,
    percent: int | None,
    battery_current_ma: int | None,
    vbus_power_mw: int | None,
    low_cell: bool,
) -> dict[str, Any]:
    result = json.loads(json.dumps(sample))
    if percent is not None:
        result["battery"]["percent"] = percent
    if battery_current_ma is not None:
        result["battery"]["current_ma"] = battery_current_ma
        result["battery"]["current_flow"] = "charging" if battery_current_ma > 0 else "discharging" if battery_current_ma < 0 else "idle"
    if vbus_power_mw is not None:
        result["vbus"]["power_mw"] = vbus_power_mw
        if vbus_power_mw == 0:
            result["vbus"]["voltage_mv"] = 0
            result["vbus"]["current_ma"] = 0
    if low_cell:
        result["low_cell_voltage_present"] = True
    return result


def build_monitor_payload(
    *,
    sample: dict[str, Any],
    sequence: int,
    bus: Path,
    address: int,
    dry_run: bool,
    low_percent: int,
    full_percent: int,
    previous_alert_keys: list[str],
    repeat_alerts: bool,
    visual_updates: list[dict[str, Any]],
) -> dict[str, Any]:
    base_payload = build_ups_payload(
        sample=sample,
        sequence=sequence,
        bus=bus,
        address=address,
        dry_run=dry_run,
        visual_updates=visual_updates,
    )
    alerts = classify_alerts(sample, low_percent=low_percent, full_percent=full_percent)
    current_keys = alert_keys(alerts)
    new_keys = sorted(set(current_keys) - set(previous_alert_keys))
    notification_emitted = bool(alerts) and (repeat_alerts or bool(new_keys))
    base_payload.update(
        {
            "source": SOURCE,
            "hardware_kind": HARDWARE_KIND,
            "ups_hardware_kind": UPS_HARDWARE_KIND,
            "effective_power_state": effective_power_state(sample),
            "battery_load_w": battery_load_w(sample),
            "battery_charge_w": battery_charge_w(sample),
            "low_battery_threshold_percent": low_percent,
            "full_battery_threshold_percent": full_percent,
            "alerts": alerts,
            "active_alert_keys": current_keys,
            "new_alert_keys": new_keys,
            "notification_emitted": notification_emitted,
            "automatic_shutdown_allowed": False,
            "power_control_write_allowed": False,
            "phase1_safety_decision_change_allowed": False,
            "remote_outbound_allowed": False,
            "hardware_control_scope": "diagnostic_power_monitor_only",
        }
    )
    return base_payload


def append_jsonl(payloads: list[dict[str, Any]], output_path: Path | None) -> None:
    if output_path is None:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        for payload in payloads:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def build_summary(
    *,
    bus: Path,
    address: int,
    dry_run: bool,
    samples: list[dict[str, Any]],
) -> dict[str, Any]:
    latest = samples[-1] if samples else None
    emitted = [sample for sample in samples if sample.get("notification_emitted") is True]
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": SOURCE,
        "hardware_kind": HARDWARE_KIND,
        "bus": str(bus),
        "address": f"0x{address:02x}",
        "dry_run": dry_run,
        "sample_count": len(samples),
        "notification_count": len(emitted),
        "latest_sample": latest,
        "samples": samples,
        "automatic_shutdown_allowed": False,
        "power_control_write_allowed": False,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_power_monitor_only",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Monitor Waveshare UPS HAT (E) telemetry and emit diagnostic alerts.")
    parser.add_argument("--bus", type=Path, default=DEFAULT_BUS)
    parser.add_argument("--address", type=parse_address, default=DEFAULT_ADDRESS)
    parser.add_argument("--samples", type=int, default=0, help="0 means run continuously.")
    parser.add_argument("--interval-seconds", type=parse_non_negative_float, default=60.0)
    parser.add_argument("--low-cell-mv", type=parse_positive_int, default=DEFAULT_LOW_CELL_MV)
    parser.add_argument("--low-percent", type=parse_percent, default=DEFAULT_LOW_PERCENT)
    parser.add_argument("--full-percent", type=parse_percent, default=DEFAULT_FULL_PERCENT)
    parser.add_argument("--state-file", type=Path)
    parser.add_argument("--output-jsonl", type=Path)
    parser.add_argument("--repeat-alerts", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--dry-run-percent", type=parse_percent)
    parser.add_argument("--dry-run-battery-current-ma", type=parse_signed_int)
    parser.add_argument("--dry-run-vbus-power-mw", type=parse_signed_int)
    parser.add_argument("--dry-run-low-cell", action="store_true")
    parser.add_argument("--oled-status", action="store_true")
    parser.add_argument("--oled-bus", type=Path, default=Path("/dev/i2c-1"))
    parser.add_argument("--oled-address", type=parse_address, default=parse_address("0x3c"))
    parser.add_argument("--oled-driver", choices=("sh1107g", "ssd1327", "auto"), default="sh1107g")
    parser.add_argument("--oled-dry-run", action="store_true")
    parser.add_argument("--led-status", action="store_true")
    parser.add_argument("--led-port", choices=sorted(PORT_DEFAULTS), default=DEFAULT_LED_PORT)
    parser.add_argument("--led-data-gpio", type=int)
    parser.add_argument("--led-clock-gpio", type=int)
    parser.add_argument("--led-ok-bit", type=parse_led_bit, default=DEFAULT_OK_LED_BIT)
    parser.add_argument("--led-on-battery-bit", type=parse_led_bit, default=DEFAULT_ON_BATTERY_LED_BIT)
    parser.add_argument("--led-charging-bit", type=parse_led_bit, default=DEFAULT_CHARGING_LED_BIT)
    parser.add_argument("--led-fast-charging-bit", type=parse_led_bit, default=DEFAULT_FAST_CHARGING_LED_BIT)
    parser.add_argument("--led-full-bit", type=parse_led_bit, default=DEFAULT_FULL_LED_BIT)
    parser.add_argument("--led-low-bit", type=parse_led_bit, default=DEFAULT_LOW_LED_BIT)
    parser.add_argument("--led-dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.samples < 0:
        parser.error("--samples must be non-negative")
    if args.full_percent < args.low_percent:
        parser.error("--full-percent must be greater than or equal to --low-percent")

    led_defaults = PORT_DEFAULTS[args.led_port]
    led_data_gpio = args.led_data_gpio if args.led_data_gpio is not None else led_defaults["data_gpio"]
    led_clock_gpio = args.led_clock_gpio if args.led_clock_gpio is not None else led_defaults["clock_gpio"]
    state = load_state(args.state_file)
    previous_alert_keys = list(state.get("active_alert_keys") or [])
    payloads: list[dict[str, Any]] = []
    sequence = 0
    try:
        while args.samples == 0 or sequence < args.samples:
            sequence += 1
            sample = canned_ups_sample(low_cell_mv=args.low_cell_mv) if args.dry_run else read_ups_hat_e_sample(
                bus=args.bus,
                address=args.address,
                low_cell_mv=args.low_cell_mv,
            )
            if args.dry_run:
                sample = apply_dry_run_overrides(
                    sample,
                    percent=args.dry_run_percent,
                    battery_current_ma=args.dry_run_battery_current_ma,
                    vbus_power_mw=args.dry_run_vbus_power_mw,
                    low_cell=args.dry_run_low_cell,
                )
            payload = build_monitor_payload(
                sample=sample,
                sequence=sequence,
                bus=args.bus,
                address=args.address,
                dry_run=args.dry_run,
                low_percent=args.low_percent,
                full_percent=args.full_percent,
                previous_alert_keys=previous_alert_keys,
                repeat_alerts=args.repeat_alerts,
                visual_updates=[],
            )
            if args.oled_status:
                payload["visual_updates"].append(
                    write_oled_monitor_status(
                        payload=payload,
                        dry_run=args.oled_dry_run,
                        bus=args.oled_bus,
                        address=args.oled_address,
                        driver=args.oled_driver,
                    )
                )
            if args.led_status:
                payload["visual_updates"].append(
                    write_led_monitor_status(
                        payload=payload,
                        dry_run=args.led_dry_run,
                        port=args.led_port,
                        data_gpio=led_data_gpio,
                        clock_gpio=led_clock_gpio,
                        ok_bit=args.led_ok_bit,
                        on_battery_bit=args.led_on_battery_bit,
                        charging_bit=args.led_charging_bit,
                        fast_charging_bit=args.led_fast_charging_bit,
                        full_bit=args.led_full_bit,
                        low_bit=args.led_low_bit,
                    )
                )
            payloads.append(payload)
            append_jsonl([payload], args.output_jsonl)
            previous_alert_keys = list(payload["active_alert_keys"])
            state["active_alert_keys"] = previous_alert_keys
            state["updated_at"] = datetime.now(timezone.utc).isoformat()
            save_state(args.state_file, state)
            if args.samples != 0 and sequence >= args.samples:
                break
            time.sleep(args.interval_seconds)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            build_summary(bus=args.bus, address=args.address, dry_run=args.dry_run, samples=payloads),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
