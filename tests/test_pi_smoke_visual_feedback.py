import json
import subprocess
import sys
from pathlib import Path

from tools import pi_smoke_visual_feedback as visual_feedback


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "pi_smoke_visual_feedback.py"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def payload_from_stdout(stdout: str) -> dict:
    return json.loads(stdout[stdout.find("{") :])


def test_visual_feedback_wraps_successful_smoke_and_writes_boundary_payload(tmp_path: Path) -> None:
    output = tmp_path / "visual.jsonl"

    result = run_cli(
        "--name",
        "oled",
        "--visual-dry-run",
        "--hold-seconds",
        "0",
        "--run-hold-seconds",
        "0",
        "--output-jsonl",
        str(output),
        "--",
        sys.executable,
        "-c",
        "print('child ok')",
    )

    assert result.returncode == 0, result.stderr
    assert "child ok" in result.stdout
    payload = payload_from_stdout(result.stdout)
    persisted = json.loads(output.read_text().splitlines()[0])
    assert payload == persisted
    assert payload["source"] == "pi_smoke_visual_feedback"
    assert payload["hardware_kind"] == "grove_oled_led_bar_visual_smoke_feedback"
    assert payload["smoke_name"] == "oled"
    assert payload["status"] == "ok"
    assert payload["child_returncode"] == 0
    assert payload["visual_dry_run"] is True
    assert payload["led_enabled"] is True
    assert payload["oled_enabled"] is True
    assert payload["led_port"] == "D5"
    assert payload["data_gpio"] == 5
    assert payload["clock_gpio"] == 6
    assert payload["oled_address"] == "0x3c"
    assert payload["run_visual_statuses"][0]["bits"] == "0x01f"
    assert payload["run_visual_statuses"][1]["message"] == "SCOUT\nOLED\nRUN"
    assert payload["final_visual_statuses"][0]["bits"] == "0x3ff"
    assert payload["final_visual_statuses"][1]["message"] == "SCOUT\nOLED\nOK"
    assert payload["phase1_safety_decision_change_allowed"] is False
    assert payload["remote_outbound_allowed"] is False
    assert payload["hardware_control_scope"] == "diagnostic_visual_feedback_only"


def test_visual_feedback_preserves_child_failure_status() -> None:
    result = run_cli(
        "--name",
        "gnss",
        "--visual-dry-run",
        "--hold-seconds",
        "0",
        "--run-hold-seconds",
        "0",
        "--",
        sys.executable,
        "-c",
        "raise SystemExit(7)",
    )

    assert result.returncode == 7
    payload = payload_from_stdout(result.stdout)
    assert payload["status"] == "fail"
    assert payload["child_returncode"] == 7
    assert payload["final_visual_statuses"][0]["bits"] == "0x155"
    assert payload["final_visual_statuses"][1]["message"] == "SCOUT\nGNSS\nFAIL"


def test_visual_feedback_supports_no_oled_and_d5_mapping() -> None:
    result = run_cli(
        "--name",
        "radio",
        "--visual-dry-run",
        "--hold-seconds",
        "0",
        "--run-hold-seconds",
        "0",
        "--no-oled",
        "--led-port",
        "D5",
        "--",
        sys.executable,
        "-c",
        "pass",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["oled_enabled"] is False
    assert payload["led_port"] == "D5"
    assert payload["data_gpio"] == 5
    assert payload["clock_gpio"] == 6
    assert [status["target"] for status in payload["run_visual_statuses"]] == ["led_bar"]


def test_visual_feedback_rejects_missing_command_cleanly() -> None:
    result = run_cli("--name", "missing", "--visual-dry-run")

    assert result.returncode == 2
    assert "smoke command is required after --" in result.stderr


def test_visual_feedback_invalid_oled_address_fails_cleanly() -> None:
    result = run_cli(
        "--name",
        "oled",
        "--visual-dry-run",
        "--oled-address",
        "0x80",
        "--",
        sys.executable,
        "-c",
        "pass",
    )

    assert result.returncode == 2
    assert "I2C address must be between 0x03 and 0x77" in result.stderr


def test_visual_feedback_records_led_error_without_masking_child_success(
    monkeypatch, capsys
) -> None:
    def fail_gpio_writer():
        raise RuntimeError("gpio unavailable")

    monkeypatch.setattr(visual_feedback, "make_gpio_writer", fail_gpio_writer)

    result = visual_feedback.main(
        [
            "--name",
            "imu",
            "--no-oled",
            "--hold-seconds",
            "0",
            "--run-hold-seconds",
            "0",
            "--",
            sys.executable,
            "-c",
            "pass",
        ]
    )

    assert result == 0
    payload = payload_from_stdout(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["run_visual_statuses"][0]["write_status"] == "error"
    assert payload["run_visual_statuses"][0]["error"] == "RuntimeError: gpio unavailable"
    assert payload["final_visual_statuses"][0]["write_status"] == "error"
