import json
import subprocess
import sys
from pathlib import Path

from tools.pi_ups_hat_e_smoke import (
    DEFAULT_ADDRESS,
    DEFAULT_BUS,
    HARDWARE_KIND,
    SOURCE,
    build_summary,
    build_ups_payload,
    bus_number_from_path,
    canned_ups_sample,
    led_bits_for_ups,
    parse_ups_registers,
    power_state_from_status,
    ups_oled_message,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "pi_ups_hat_e_smoke.py"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_ups_register_parser_matches_waveshare_example_layout() -> None:
    sample = parse_ups_registers(
        status_data=[0x20],
        vbus_data=[0x88, 0x13, 0x34, 0x12, 0x78, 0x56],
        battery_data=[0xAC, 0x3B, 0xD0, 0xF8, 0x55, 0x00, 0xB8, 0x0B, 0xF0, 0x00, 0x00, 0x00],
        cell_data=[0xE1, 0x0E, 0xDF, 0x0E, 0xE0, 0x0E, 0xE2, 0x0E],
        low_cell_mv=3150,
    )

    assert sample["status_register"] == "0x20"
    assert sample["power_state"] == "discharging"
    assert sample["vbus"] == {
        "voltage_mv": 5000,
        "current_ma": 4660,
        "power_mw": 22136,
    }
    assert sample["battery"]["voltage_mv"] == 15276
    assert sample["battery"]["current_ma"] == -1840
    assert sample["battery"]["current_flow"] == "discharging"
    assert sample["battery"]["percent"] == 85
    assert sample["battery"]["remaining_capacity_mah"] == 3000
    assert sample["battery"]["run_time_to_empty_min"] == 240
    assert sample["cell_voltage_mv"] == [3809, 3807, 3808, 3810]
    assert sample["low_cell_voltage_present"] is False


def test_ups_bus_number_from_path_parses_linux_i2c_device() -> None:
    assert bus_number_from_path(Path("/dev/i2c-1")) == 1
    assert bus_number_from_path(Path("/dev/i2c-14")) == 14


def test_ups_power_state_priority_matches_official_demo() -> None:
    assert power_state_from_status(0x40 | 0x80 | 0x20) == "fast_charging"
    assert power_state_from_status(0x80 | 0x20) == "charging"
    assert power_state_from_status(0x20) == "discharging"
    assert power_state_from_status(0x00) == "idle"


def test_ups_dry_run_writes_boundary_payloads(tmp_path: Path) -> None:
    output = tmp_path / "ups.jsonl"

    result = run_cli("--dry-run", "--output-jsonl", str(output))

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    persisted = [json.loads(line) for line in output.read_text().splitlines()]
    assert summary["source"] == SOURCE
    assert summary["hardware_kind"] == HARDWARE_KIND
    assert summary["bus"] == str(DEFAULT_BUS)
    assert summary["address"] == f"0x{DEFAULT_ADDRESS:02x}"
    assert summary["sample_count"] == 1
    assert persisted == summary["samples"]
    payload = persisted[0]
    assert payload["ups"]["battery"]["percent"] == 85
    assert payload["automatic_shutdown_allowed"] is False
    assert payload["power_control_write_allowed"] is False
    assert payload["phase1_safety_decision_change_allowed"] is False
    assert payload["remote_outbound_allowed"] is False
    assert payload["hardware_control_scope"] == "diagnostic_power_telemetry_only"
    assert summary["automatic_shutdown_allowed"] is False
    assert summary["power_control_write_allowed"] is False


def test_ups_visual_dry_run_updates_oled_and_led() -> None:
    result = run_cli(
        "--dry-run",
        "--oled-status",
        "--oled-dry-run",
        "--led-status",
        "--led-dry-run",
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    payload = summary["samples"][0]
    assert payload["visual_updates"] == [
        {
            "target": "oled",
            "write_status": "dry_run",
            "bus": "/dev/i2c-1",
            "address": "0x3c",
            "driver": "sh1107g",
            "message": "SCOUT UPS\nDISCHARGING\nBAT 85%\nBV 15.28V\nBI -1.84A\nVBUS 5.00V\nVPWR 0.0W\nCELLS OK",
        },
        {
            "target": "led_bar",
            "write_status": "dry_run",
            "port": "D5",
            "data_gpio": 5,
            "clock_gpio": 6,
            "bits": "0x001",
            "ok_led_bit": 7,
            "discharge_led_bit": 1,
            "charge_led_bit": 2,
            "fast_charge_led_bit": 3,
            "low_led_bit": 10,
            "clear_after": False,
        },
    ]


def test_ups_oled_message_and_led_bits_surface_low_cell() -> None:
    low_sample = canned_ups_sample(low_cell_mv=3900)
    payload = build_ups_payload(
        sample=low_sample,
        sequence=1,
        bus=DEFAULT_BUS,
        address=DEFAULT_ADDRESS,
        dry_run=True,
        visual_updates=[],
    )

    assert "LOW CELL" in ups_oled_message(payload)
    assert led_bits_for_ups(
        payload,
        ok_bit=7,
        discharge_bit=1,
        charge_bit=2,
        fast_charge_bit=3,
        low_bit=10,
    ) == 0x200


def test_ups_summary_keeps_control_boundary() -> None:
    payload = build_ups_payload(
        sample=canned_ups_sample(low_cell_mv=3150),
        sequence=1,
        bus=DEFAULT_BUS,
        address=DEFAULT_ADDRESS,
        dry_run=True,
        visual_updates=[],
    )
    summary = build_summary(bus=DEFAULT_BUS, address=DEFAULT_ADDRESS, dry_run=True, samples=[payload])

    assert summary["latest_sample"] == payload
    assert summary["automatic_shutdown_allowed"] is False
    assert summary["power_control_write_allowed"] is False
    assert summary["phase1_safety_decision_change_allowed"] is False
    assert summary["remote_outbound_allowed"] is False


def test_ups_invalid_address_and_led_bit_fail_cleanly() -> None:
    bad_address = run_cli("--dry-run", "--address", "0x80")
    bad_led = run_cli("--dry-run", "--led-status", "--led-dry-run", "--led-low-bit", "11")

    assert bad_address.returncode == 2
    assert "I2C address must be between 0x03 and 0x77" in bad_address.stderr
    assert bad_led.returncode == 2
    assert "LED bit must be between 1 and 10" in bad_led.stderr
