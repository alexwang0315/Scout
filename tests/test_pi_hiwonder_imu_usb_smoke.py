import json
import os
import pty
import subprocess
import sys
import threading
import time
from pathlib import Path

from tools.pi_hiwonder_imu_usb_smoke import _read_serial_bytes_stdlib, build_imu_payload, parse_raw_hex_frames


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "pi_hiwonder_imu_usb_smoke.py"


def test_imu_smoke_payload_keeps_safety_boundary_false() -> None:
    frame = parse_raw_hex_frames(_wit_frame_hex(0x51, [2048, 0, 0, 0]))[0]

    payload = build_imu_payload(frame, device_port="/dev/ttyUSB0", baud=9600)

    assert payload["source"] == "pi_hiwonder_imu_usb_smoke"
    assert payload["hardware_kind"] == "hiwonder_wit_imu_usb"
    assert payload["device_port"] == "/dev/ttyUSB0"
    assert payload["baud"] == 9600
    assert payload["frame_type"] == "acceleration"
    assert payload["raw_imu_present"] is True
    assert payload["raw_gnss_present"] is False
    assert payload["fused_navigation_present"] is False
    assert payload["preferred_low_power_estimate"] is False
    assert payload["primary_truth_allowed"] is False
    assert payload["raw_evidence_required"] is True
    assert payload["vendor_fusion_algorithm"] == "opaque"
    assert payload["phase1_safety_decision_change_allowed"] is False
    assert payload["remote_outbound_allowed"] is False
    assert payload["hardware_control_scope"] == "diagnostic_capture_only"


def test_imu_smoke_cli_raw_hex_writes_jsonl(tmp_path: Path) -> None:
    output = tmp_path / "imu.jsonl"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--raw-hex",
            _wit_frame_hex(0x51, [2048, 0, 0, 0]),
            "--output-jsonl",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    stdout_payload = json.loads(result.stdout)
    persisted = json.loads(output.read_text().splitlines()[0])
    assert stdout_payload["frame_count"] == 1
    assert persisted["frame_type"] == "acceleration"
    assert persisted["parsed"]["acceleration_g"] == [1.0, 0.0, 0.0]


def test_imu_smoke_cli_invalid_raw_hex_fails_cleanly() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--raw-hex", "not-hex"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "ValueError" in result.stderr


def test_stdlib_serial_fallback_reads_imu_bytes() -> None:
    master_fd, slave_fd = pty.openpty()
    slave_name = os.ttyname(slave_fd)
    frame = bytes.fromhex(_wit_frame_hex(0x53, [0, 0, 16384, 0]))

    def writer() -> None:
        time.sleep(0.05)
        os.write(master_fd, frame)

    thread = threading.Thread(target=writer)
    thread.start()
    try:
        data = _read_serial_bytes_stdlib(port=slave_name, baud=9600, duration_seconds=0.25)
    finally:
        thread.join(timeout=1.0)
        os.close(master_fd)
        os.close(slave_fd)

    assert frame in data


def _wit_frame_hex(frame_type: int, values: list[int]) -> str:
    payload = b"".join(value.to_bytes(2, "little", signed=True) for value in values)
    frame = bytes([0x55, frame_type]) + payload
    return (frame + bytes([sum(frame) & 0xFF])).hex()
