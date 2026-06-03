from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from tools.pi_grove_led_bar_smoke import DEFAULT_PORT as DEFAULT_LED_PORT
    from tools.pi_grove_led_bar_smoke import PORT_DEFAULTS, make_gpio_writer, write_led_bar_bits
    from tools.pi_oled_i2c_smoke import parse_address, write_display
except ImportError:  # pragma: no cover - used when executed directly from tools/ on a Pi.
    from pi_grove_led_bar_smoke import DEFAULT_PORT as DEFAULT_LED_PORT
    from pi_grove_led_bar_smoke import PORT_DEFAULTS, make_gpio_writer, write_led_bar_bits
    from pi_oled_i2c_smoke import parse_address, write_display


I2C_SLAVE = 0x0703
SOURCE = "pi_ups_hat_e_smoke"
HARDWARE_KIND = "waveshare_ups_hat_e_i2c"
DEFAULT_BUS = Path("/dev/i2c-1")
DEFAULT_ADDRESS = 0x2D
DEFAULT_LOW_CELL_MV = 3150
DEFAULT_OK_LED_BIT = 7
DEFAULT_DISCHARGE_LED_BIT = 1
DEFAULT_CHARGE_LED_BIT = 2
DEFAULT_FAST_CHARGE_LED_BIT = 3
DEFAULT_LOW_LED_BIT = 10


class I2cRegisterDevice:
    def __init__(self, bus: Path, address: int) -> None:
        self._fd = os.open(bus, os.O_RDWR)
        fcntl.ioctl(self._fd, I2C_SLAVE, address)

    def read_block(self, register: int, length: int) -> bytes:
        os.write(self._fd, bytes([register]))
        return os.read(self._fd, length)

    def close(self) -> None:
        os.close(self._fd)


class SmbusRegisterDevice:
    def __init__(self, bus: Path, address: int) -> None:
        try:
            import smbus  # type: ignore
        except ImportError:
            import smbus2 as smbus  # type: ignore

        self._bus = smbus.SMBus(bus_number_from_path(bus))
        self._address = address

    def read_block(self, register: int, length: int) -> bytes:
        return bytes(self._bus.read_i2c_block_data(self._address, register, length))

    def close(self) -> None:
        close = getattr(self._bus, "close", None)
        if close is not None:
            close()


def bus_number_from_path(bus: Path) -> int:
    name = bus.name
    if not name.startswith("i2c-"):
        raise ValueError(f"unsupported I2C bus path: {bus}")
    return int(name.split("-", 1)[1])


def make_register_device(bus: Path, address: int) -> SmbusRegisterDevice | I2cRegisterDevice:
    try:
        return SmbusRegisterDevice(bus, address)
    except ImportError:
        return I2cRegisterDevice(bus, address)


def parse_positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def parse_non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return parsed


def parse_led_bit(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 10:
        raise argparse.ArgumentTypeError("LED bit must be between 1 and 10")
    return parsed


def u16le(data: bytes | list[int], offset: int) -> int:
    return int(data[offset]) | (int(data[offset + 1]) << 8)


def i16le(data: bytes | list[int], offset: int) -> int:
    value = u16le(data, offset)
    if value >= 0x8000:
        value -= 0x10000
    return value


def power_state_from_status(status: int) -> str:
    if status & 0x40:
        return "fast_charging"
    if status & 0x80:
        return "charging"
    if status & 0x20:
        return "discharging"
    return "idle"


def current_flow_from_ma(current_ma: int) -> str:
    if current_ma > 0:
        return "charging"
    if current_ma < 0:
        return "discharging"
    return "idle"


def parse_ups_registers(
    *,
    status_data: bytes | list[int],
    vbus_data: bytes | list[int],
    battery_data: bytes | list[int],
    cell_data: bytes | list[int],
    low_cell_mv: int,
) -> dict[str, Any]:
    status_register = int(status_data[0])
    battery_current_ma = i16le(battery_data, 2)
    cell_voltage_mv = [u16le(cell_data, offset) for offset in range(0, 8, 2)]
    low_cell_voltage_present = any(voltage < low_cell_mv for voltage in cell_voltage_mv)
    return {
        "status_register": f"0x{status_register:02x}",
        "power_state": power_state_from_status(status_register),
        "vbus": {
            "voltage_mv": u16le(vbus_data, 0),
            "current_ma": u16le(vbus_data, 2),
            "power_mw": u16le(vbus_data, 4),
        },
        "battery": {
            "voltage_mv": u16le(battery_data, 0),
            "current_ma": battery_current_ma,
            "current_flow": current_flow_from_ma(battery_current_ma),
            "percent": u16le(battery_data, 4),
            "remaining_capacity_mah": u16le(battery_data, 6),
            "run_time_to_empty_min": u16le(battery_data, 8),
            "average_time_to_full_min": u16le(battery_data, 10),
        },
        "cell_voltage_mv": cell_voltage_mv,
        "low_cell_threshold_mv": low_cell_mv,
        "low_cell_voltage_present": low_cell_voltage_present,
    }


def read_ups_hat_e_sample(*, bus: Path, address: int, low_cell_mv: int) -> dict[str, Any]:
    device = make_register_device(bus, address)
    try:
        return parse_ups_registers(
            status_data=device.read_block(0x02, 1),
            vbus_data=device.read_block(0x10, 6),
            battery_data=device.read_block(0x20, 12),
            cell_data=device.read_block(0x30, 8),
            low_cell_mv=low_cell_mv,
        )
    finally:
        device.close()


def canned_ups_sample(*, low_cell_mv: int) -> dict[str, Any]:
    return parse_ups_registers(
        status_data=[0x20],
        vbus_data=[0x88, 0x13, 0x00, 0x00, 0x00, 0x00],
        battery_data=[0xAC, 0x3B, 0xD0, 0xF8, 0x55, 0x00, 0xB8, 0x0B, 0xF0, 0x00, 0x00, 0x00],
        cell_data=[0xE1, 0x0E, 0xDF, 0x0E, 0xE0, 0x0E, 0xE2, 0x0E],
        low_cell_mv=low_cell_mv,
    )


def build_ups_payload(
    *,
    sample: dict[str, Any],
    sequence: int,
    bus: Path,
    address: int,
    dry_run: bool,
    visual_updates: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": SOURCE,
        "hardware_kind": HARDWARE_KIND,
        "sequence": sequence,
        "bus": str(bus),
        "address": f"0x{address:02x}",
        "dry_run": dry_run,
        "ups": sample,
        "automatic_shutdown_allowed": False,
        "power_control_write_allowed": False,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_power_telemetry_only",
        "visual_updates": visual_updates,
    }


def ups_oled_message(payload: dict[str, Any]) -> str:
    ups = payload["ups"]
    battery = ups["battery"]
    vbus = ups["vbus"]
    low_state = "LOW CELL" if ups["low_cell_voltage_present"] else "CELLS OK"
    return "\n".join(
        [
            "SCOUT UPS",
            ups["power_state"].upper()[:21],
            f"BAT {battery['percent']}%",
            f"BV {battery['voltage_mv'] / 1000:.2f}V",
            f"BI {battery['current_ma'] / 1000:.2f}A",
            f"VBUS {vbus['voltage_mv'] / 1000:.2f}V",
            f"VPWR {vbus['power_mw'] / 1000:.1f}W",
            low_state,
        ]
    )


def led_bits_for_ups(
    payload: dict[str, Any],
    *,
    ok_bit: int,
    discharge_bit: int,
    charge_bit: int,
    fast_charge_bit: int,
    low_bit: int,
) -> int:
    ups = payload["ups"]
    if ups["low_cell_voltage_present"]:
        return 1 << (low_bit - 1)
    power_state = ups["power_state"]
    if power_state == "fast_charging":
        return 1 << (fast_charge_bit - 1)
    if power_state == "charging":
        return 1 << (charge_bit - 1)
    if power_state == "discharging":
        return 1 << (discharge_bit - 1)
    return 1 << (ok_bit - 1)


def write_oled_ups_status(
    *,
    payload: dict[str, Any],
    dry_run: bool,
    bus: Path,
    address: int,
    driver: str,
) -> dict[str, Any]:
    message = ups_oled_message(payload)
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


def write_led_ups_status(
    *,
    payload: dict[str, Any],
    dry_run: bool,
    port: str,
    data_gpio: int,
    clock_gpio: int,
    ok_bit: int,
    discharge_bit: int,
    charge_bit: int,
    fast_charge_bit: int,
    low_bit: int,
    clear_after: bool,
) -> dict[str, Any]:
    bits = led_bits_for_ups(
        payload,
        ok_bit=ok_bit,
        discharge_bit=discharge_bit,
        charge_bit=charge_bit,
        fast_charge_bit=fast_charge_bit,
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
        "discharge_led_bit": discharge_bit,
        "charge_led_bit": charge_bit,
        "fast_charge_led_bit": fast_charge_bit,
        "low_led_bit": low_bit,
        "clear_after": clear_after,
    }
    if dry_run:
        return status
    writer = None
    try:
        writer = make_gpio_writer()
        write_led_bar_bits(writer, data_gpio=data_gpio, clock_gpio=clock_gpio, bits=bits)
        if clear_after:
            write_led_bar_bits(writer, data_gpio=data_gpio, clock_gpio=clock_gpio, bits=0)
    except Exception as exc:
        status["write_status"] = "error"
        status["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if writer is not None:
            writer.close()
    return status


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
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": SOURCE,
        "hardware_kind": HARDWARE_KIND,
        "bus": str(bus),
        "address": f"0x{address:02x}",
        "dry_run": dry_run,
        "sample_count": len(samples),
        "latest_sample": latest,
        "samples": samples,
        "automatic_shutdown_allowed": False,
        "power_control_write_allowed": False,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_power_telemetry_only",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke-test Waveshare UPS HAT (E) power telemetry over I2C.")
    parser.add_argument("--bus", type=Path, default=DEFAULT_BUS)
    parser.add_argument("--address", type=parse_address, default=DEFAULT_ADDRESS)
    parser.add_argument("--samples", type=parse_positive_int, default=1)
    parser.add_argument("--interval-seconds", type=parse_non_negative_float, default=1.0)
    parser.add_argument("--low-cell-mv", type=parse_positive_int, default=DEFAULT_LOW_CELL_MV)
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
    parser.add_argument("--led-ok-bit", type=parse_led_bit, default=DEFAULT_OK_LED_BIT)
    parser.add_argument("--led-discharge-bit", type=parse_led_bit, default=DEFAULT_DISCHARGE_LED_BIT)
    parser.add_argument("--led-charge-bit", type=parse_led_bit, default=DEFAULT_CHARGE_LED_BIT)
    parser.add_argument("--led-fast-charge-bit", type=parse_led_bit, default=DEFAULT_FAST_CHARGE_LED_BIT)
    parser.add_argument("--led-low-bit", type=parse_led_bit, default=DEFAULT_LOW_LED_BIT)
    parser.add_argument("--led-clear-after", action="store_true")
    parser.add_argument("--led-dry-run", action="store_true")
    args = parser.parse_args(argv)

    led_defaults = PORT_DEFAULTS[args.led_port]
    led_data_gpio = args.led_data_gpio if args.led_data_gpio is not None else led_defaults["data_gpio"]
    led_clock_gpio = args.led_clock_gpio if args.led_clock_gpio is not None else led_defaults["clock_gpio"]

    payloads: list[dict[str, Any]] = []
    try:
        for index in range(1, args.samples + 1):
            sample = canned_ups_sample(low_cell_mv=args.low_cell_mv) if args.dry_run else read_ups_hat_e_sample(
                bus=args.bus,
                address=args.address,
                low_cell_mv=args.low_cell_mv,
            )
            payload = build_ups_payload(
                sample=sample,
                sequence=index,
                bus=args.bus,
                address=args.address,
                dry_run=args.dry_run,
                visual_updates=[],
            )
            if args.oled_status:
                payload["visual_updates"].append(
                    write_oled_ups_status(
                        payload=payload,
                        dry_run=args.oled_dry_run,
                        bus=args.oled_bus,
                        address=args.oled_address,
                        driver=args.oled_driver,
                    )
                )
            if args.led_status:
                payload["visual_updates"].append(
                    write_led_ups_status(
                        payload=payload,
                        dry_run=args.led_dry_run,
                        port=args.led_port,
                        data_gpio=led_data_gpio,
                        clock_gpio=led_clock_gpio,
                        ok_bit=args.led_ok_bit,
                        discharge_bit=args.led_discharge_bit,
                        charge_bit=args.led_charge_bit,
                        fast_charge_bit=args.led_fast_charge_bit,
                        low_bit=args.led_low_bit,
                        clear_after=args.led_clear_after,
                    )
                )
            payloads.append(payload)
            if index < args.samples:
                time.sleep(args.interval_seconds)
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    append_jsonl(payloads, args.output_jsonl)
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
