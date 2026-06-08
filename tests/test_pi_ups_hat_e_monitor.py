import json
import subprocess
import sys
from pathlib import Path

from tools.pi_ups_hat_e_monitor import (
    HARDWARE_KIND,
    SOURCE,
    build_monitor_payload,
    classify_alerts,
    effective_power_state,
    led_bits_for_monitor,
    monitor_oled_message,
)
from tools.pi_ups_hat_e_smoke import DEFAULT_ADDRESS, DEFAULT_BUS, canned_ups_sample


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "pi_ups_hat_e_monitor.py"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_ups_monitor_dry_run_records_nominal_payload(tmp_path: Path) -> None:
    output = tmp_path / "monitor.jsonl"

    result = run_cli("--dry-run", "--samples", "1", "--output-jsonl", str(output))

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    persisted = [json.loads(line) for line in output.read_text().splitlines()]
    assert summary["source"] == SOURCE
    assert summary["hardware_kind"] == HARDWARE_KIND
    assert summary["sample_count"] == 1
    assert summary["notification_count"] == 0
    assert persisted == summary["samples"]
    payload = persisted[0]
    assert payload["effective_power_state"] == "on_battery"
    assert payload["alerts"] == []
    assert payload["active_alert_keys"] == []
    assert payload["notification_emitted"] is False
    assert payload["automatic_shutdown_allowed"] is False
    assert payload["power_control_write_allowed"] is False
    assert payload["phase1_safety_decision_change_allowed"] is False
    assert payload["remote_outbound_allowed"] is False
    assert payload["hardware_control_scope"] == "diagnostic_power_monitor_only"


def test_ups_monitor_low_battery_alert_is_deduped_with_state_file(tmp_path: Path) -> None:
    output = tmp_path / "monitor.jsonl"
    state = tmp_path / "state.json"

    result = run_cli(
        "--dry-run",
        "--samples",
        "2",
        "--interval-seconds",
        "0",
        "--dry-run-percent",
        "9",
        "--state-file",
        str(state),
        "--output-jsonl",
        str(output),
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    persisted = [json.loads(line) for line in output.read_text().splitlines()]
    assert summary["notification_count"] == 1
    assert [payload["notification_emitted"] for payload in persisted] == [True, False]
    assert persisted[0]["active_alert_keys"] == ["battery_percent_low"]
    assert persisted[0]["new_alert_keys"] == ["battery_percent_low"]
    assert persisted[1]["active_alert_keys"] == ["battery_percent_low"]
    assert persisted[1]["new_alert_keys"] == []
    assert json.loads(state.read_text())["active_alert_keys"] == ["battery_percent_low"]


def test_ups_monitor_full_battery_alert_and_visual_dry_run() -> None:
    result = run_cli(
        "--dry-run",
        "--samples",
        "1",
        "--dry-run-percent",
        "100",
        "--dry-run-battery-current-ma",
        "0",
        "--oled-status",
        "--oled-dry-run",
        "--led-status",
        "--led-dry-run",
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    payload = summary["samples"][0]
    assert payload["active_alert_keys"] == ["battery_percent_full"]
    assert payload["notification_emitted"] is True
    assert payload["visual_updates"] == [
        {
            "target": "oled",
            "write_status": "dry_run",
            "bus": "/dev/i2c-1",
            "address": "0x3c",
            "driver": "sh1107g",
            "message": "SCOUT UPS MON\nFULL 100%\nBAT 100%\nBV 15.28V\nBI 0.00A\nCHG 0.0W\nVBUS 0.0W\nDIAG ONLY",
        },
        {
            "target": "led_bar",
            "write_status": "dry_run",
            "port": "D5",
            "data_gpio": 5,
            "clock_gpio": 6,
            "bits": "0x080",
            "ok_led_bit": 7,
            "on_battery_led_bit": 1,
            "charging_led_bit": 2,
            "fast_charging_led_bit": 3,
            "full_led_bit": 8,
            "low_led_bit": 10,
        },
    ]


def test_ups_monitor_low_battery_visual_uses_low_led() -> None:
    result = run_cli(
        "--dry-run",
        "--samples",
        "1",
        "--dry-run-percent",
        "10",
        "--oled-status",
        "--oled-dry-run",
        "--led-status",
        "--led-dry-run",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)["samples"][0]
    assert payload["active_alert_keys"] == ["battery_percent_low"]
    assert "LOW BATTERY" in payload["visual_updates"][0]["message"]
    assert payload["visual_updates"][1]["bits"] == "0x200"


def test_ups_monitor_helper_classifies_low_cell_and_effective_power_state() -> None:
    sample = canned_ups_sample(low_cell_mv=3900)
    alerts = classify_alerts(sample, low_percent=10, full_percent=100)
    payload = build_monitor_payload(
        sample=sample,
        sequence=1,
        bus=DEFAULT_BUS,
        address=DEFAULT_ADDRESS,
        dry_run=True,
        low_percent=10,
        full_percent=100,
        previous_alert_keys=[],
        repeat_alerts=False,
        visual_updates=[],
    )

    assert effective_power_state(sample) == "on_battery"
    assert [alert["alert_key"] for alert in alerts] == ["cell_voltage_low"]
    assert "LOW CELL" in monitor_oled_message(payload)
    assert led_bits_for_monitor(
        payload,
        ok_bit=7,
        on_battery_bit=1,
        charging_bit=2,
        fast_charging_bit=3,
        full_bit=8,
        low_bit=10,
    ) == 0x200


def test_ups_monitor_repeat_alerts_emits_each_sample() -> None:
    result = run_cli(
        "--dry-run",
        "--samples",
        "2",
        "--interval-seconds",
        "0",
        "--dry-run-percent",
        "9",
        "--repeat-alerts",
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["notification_count"] == 2
    assert [sample["notification_emitted"] for sample in summary["samples"]] == [True, True]


def test_ups_monitor_invalid_percent_fails_cleanly() -> None:
    bad_low = run_cli("--dry-run", "--samples", "1", "--low-percent", "101")
    bad_order = run_cli("--dry-run", "--samples", "1", "--low-percent", "90", "--full-percent", "80")

    assert bad_low.returncode == 2
    assert "percent must be between 0 and 100" in bad_low.stderr
    assert bad_order.returncode == 2
    assert "--full-percent must be greater than or equal to --low-percent" in bad_order.stderr
