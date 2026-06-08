import json
import subprocess
import sys
from pathlib import Path

from tools.pi_grove_imu_9dof_smoke import decode_imu_sample, signed16_be, signed16_le


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "pi_grove_imu_9dof_smoke.py"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_grove_imu_dry_run_writes_boundary_payload(tmp_path: Path) -> None:
    output = tmp_path / "imu.jsonl"

    result = run_cli(
        "--dry-run",
        "--sample-count",
        "2",
        "--sample-interval-ms",
        "0",
        "--output-jsonl",
        str(output),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    persisted = json.loads(output.read_text().splitlines()[0])
    assert payload == persisted
    assert payload["source"] == "pi_grove_imu_9dof_smoke"
    assert payload["hardware_kind"] == "grove_imu_9dof_icm20600_ak09918"
    assert payload["bus"] == "/dev/i2c-1"
    assert payload["imu_address"] == "0x69"
    assert payload["mag_address"] == "0x0c"
    assert payload["imu_whoami"] == "0x11"
    assert payload["mag_wia"] == "0x480c"
    assert payload["read_status"] == "dry_run"
    assert payload["sample_count"] == 2
    assert payload["samples"][0]["accel_raw"] == [1144, -14076, 7716]
    assert payload["samples"][0]["gyro_raw"] == [-144, -105, 30]
    assert payload["samples"][0]["mag_raw"] == [-78, 261, -113]
    assert payload["raw_imu_present"] is True
    assert payload["raw_magnetometer_present"] is True
    assert payload["primary_truth_allowed"] is False
    assert payload["raw_evidence_required"] is True
    assert payload["phase1_safety_decision_change_allowed"] is False
    assert payload["remote_outbound_allowed"] is False
    assert payload["hardware_control_scope"] == "diagnostic_capture_only"


def test_grove_imu_custom_addresses_are_reflected_in_payload() -> None:
    result = run_cli(
        "--dry-run",
        "--bus",
        "/tmp/fake-i2c",
        "--imu-address",
        "0x68",
        "--mag-address",
        "0x0c",
        "--sample-count",
        "1",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["bus"] == "/tmp/fake-i2c"
    assert payload["imu_address"] == "0x68"
    assert payload["mag_address"] == "0x0c"


def test_decode_imu_sample_scales_default_ranges() -> None:
    raw = bytes(
        [
            0x04,
            0x78,
            0xC9,
            0x04,
            0x1E,
            0x24,
            0x00,
            0x00,
            0xFF,
            0x70,
            0xFF,
            0x97,
            0x00,
            0x1E,
        ]
    )

    sample = decode_imu_sample(raw, sequence=3)

    assert sample["sequence"] == 3
    assert sample["accel_raw"] == [1144, -14076, 7716]
    assert sample["gyro_raw"] == [-144, -105, 30]
    assert sample["accel_g"] == [0.0698, -0.8591, 0.4709]
    assert sample["gyro_dps"] == [-1.0992, -0.8015, 0.229]


def test_signed16_helpers() -> None:
    assert signed16_be(0x00, 0x01) == 1
    assert signed16_be(0xFF, 0xFF) == -1
    assert signed16_le(0xFF, 0xFF) == -1
    assert signed16_le(0xB2, 0xFF) == -78


def test_grove_imu_invalid_address_fails_cleanly() -> None:
    result = run_cli("--dry-run", "--imu-address", "0x80")

    assert result.returncode == 2
    assert "I2C address must be between 0x03 and 0x77" in result.stderr


def test_grove_imu_invalid_sample_count_fails_cleanly() -> None:
    result = run_cli("--dry-run", "--sample-count", "0")

    assert result.returncode == 2
    assert "value must be at least 1" in result.stderr
