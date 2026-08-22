from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tools.pi_ai_hat_plus_2_smoke import (
    HARDWARE_KIND,
    SOURCE,
    collect_ai_hat_plus_2_status,
    parse_hailortcli_identify,
    parse_lspci_hailo,
    parse_throttled,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "pi_ai_hat_plus_2_smoke.py"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_parse_lspci_detects_hailo10h_ai_hat_plus_2() -> None:
    parsed = parse_lspci_hailo(
        "0001:01:00.0 Co-processor [0b40]: Hailo Technologies Ltd. "
        "Hailo-10H AI Processor [1e60:45c4] (rev 01)\n"
    )

    assert parsed["hailo_device_present"] is True
    assert parsed["hailo10h_detected"] is True
    assert parsed["hailo_pci_addresses"] == ["0001:01:00.0"]


def test_parse_hailortcli_identify_extracts_architecture_and_firmware() -> None:
    parsed = parse_hailortcli_identify(
        "Executing on device: 0001:01:00.0\n"
        "Control Protocol Version: 2\n"
        "Firmware Version: 5.1.1 (release,app)\n"
        "Device Architecture: HAILO10H\n"
    )

    assert parsed["executing_device"] == "0001:01:00.0"
    assert parsed["firmware_version"] == "5.1.1 (release,app)"
    assert parsed["device_architecture"] == "HAILO10H"
    assert parsed["hailo10h_runtime_identified"] is True


def test_parse_throttled_reports_ok_only_for_zero() -> None:
    assert parse_throttled("throttled=0x0\n") == {"throttled_raw": "0x0", "throttled_ok": True}
    assert parse_throttled("throttled=0x50000\n") == {"throttled_raw": "0x50000", "throttled_ok": False}


def test_ai_hat_smoke_dry_run_payload_is_ready_and_boundary_safe() -> None:
    payload = collect_ai_hat_plus_2_status(dry_run=True)

    assert payload["source"] == SOURCE
    assert payload["hardware_kind"] == HARDWARE_KIND
    assert payload["readiness_status"] == "ready"
    assert payload["ready_for_minimal_inference_smoke"] is True
    assert payload["pci"]["hailo10h_detected"] is True
    assert payload["device_nodes"]["device_nodes"] == ["/dev/hailo0"]
    assert payload["driver"]["kernel_modules"] == ["hailo1x_pci"]
    assert payload["packages"]["hailo-h10-all"] == "5.1.1"
    assert payload["hailortcli"]["version"] == "5.1.1"
    assert payload["command_results"]["hailortcli_path"]["cmd"] == ["sh", "-lc", "command -v hailortcli"]
    assert payload["hailortcli"]["identify"]["device_architecture"] == "HAILO10H"
    assert payload["model_inference_performed"] is False
    assert payload["package_install_performed"] is False
    assert payload["device_configuration_changed"] is False
    assert payload["phase1_safety_decision_change_allowed"] is False
    assert payload["runtime_safety_truth"] is False
    assert payload["safety_api_called"] is False
    assert payload["remote_outbound_allowed"] is False
    assert payload["outbound_send_performed"] is False
    assert payload["hardware_control_scope"] == "diagnostic_ai_accelerator_readiness_only"


def test_ai_hat_smoke_reports_driver_missing_from_fake_runner() -> None:
    def fake_runner(command: list[str], timeout_seconds: float) -> dict:
        del timeout_seconds
        stdout = ""
        if command[0] == "lspci":
            stdout = "0001:01:00.0 Co-processor [0b40]: Hailo-10H AI Processor [1e60:45c4]\n"
        elif command[0] == "vcgencmd":
            stdout = "throttled=0x0\n"
        elif command[0] == "uname":
            stdout = "Linux scout test\n"
        return {"cmd": command, "returncode": 0, "stdout": stdout, "stderr": "", "timed_out": False}

    payload = collect_ai_hat_plus_2_status(runner=fake_runner)

    assert payload["readiness_status"] == "driver_missing_or_not_loaded"
    assert payload["ready_for_minimal_inference_smoke"] is False
    assert "install_or_reinstall_dkms_and_hailo_h10_all" in payload["next_actions"]


def test_ai_hat_smoke_cli_writes_jsonl(tmp_path: Path) -> None:
    output = tmp_path / "ai-hat-smoke.jsonl"

    result = run_cli("--dry-run", "--output-jsonl", str(output))

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    persisted = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert persisted == [payload]
    assert payload["readiness_status"] == "ready"
    assert payload["model_inference_performed"] is False


def test_ai_hat_smoke_cli_no_write_and_invalid_timeout() -> None:
    ok = run_cli("--dry-run", "--no-write")
    bad = run_cli("--timeout-seconds", "0")

    assert ok.returncode == 0
    assert json.loads(ok.stdout)["readiness_status"] == "ready"
    assert bad.returncode == 2
    assert "--timeout-seconds must be positive" in bad.stderr
