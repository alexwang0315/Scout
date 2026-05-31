import json
import os
import pty
import subprocess
import sys
import threading
import time
from pathlib import Path

from tools.pi_imu_gnss_vendor_fusion_smoke import _read_serial_bytes_stdlib, classify_vendor_fusion_stream


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "pi_imu_gnss_vendor_fusion_smoke.py"
RMC = b"$GPRMC,092751.000,A,5321.6802,N,00630.3372,W,0.06,31.66,280511,,,A*43\r\n"


def test_classifies_imu_only_stream() -> None:
    payload = classify_vendor_fusion_stream(_wit_frame(0x51, [2048, 0, 0, 0]))

    assert payload["vendor_fusion_mode_observed"] == "imu_only"
    assert payload["raw_imu_present"] is True
    assert payload["raw_gnss_present"] is False
    assert payload["fused_navigation_present"] is False
    assert payload["primary_truth_allowed"] is False
    assert payload["raw_evidence_required"] is True
    assert payload["vendor_fusion_algorithm"] == "opaque"


def test_classifies_gps_raw_only_stream() -> None:
    payload = classify_vendor_fusion_stream(RMC)

    assert payload["vendor_fusion_mode_observed"] == "gps_raw_only"
    assert payload["raw_imu_present"] is False
    assert payload["raw_gnss_present"] is True
    assert payload["fused_navigation_present"] is False


def test_classifies_imu_with_gps_fields_stream() -> None:
    payload = classify_vendor_fusion_stream(_wit_frame(0x51, [2048, 0, 0, 0]) + RMC)

    assert payload["vendor_fusion_mode_observed"] == "imu_with_gps_fields"
    assert payload["raw_imu_present"] is True
    assert payload["raw_gnss_present"] is True
    assert payload["fused_navigation_present"] is False
    assert payload["preferred_low_power_estimate"] is True


def test_classifies_vendor_fused_only_stream() -> None:
    payload = classify_vendor_fusion_stream(_wit_frame(0x58, [1, 2, 3, 4]))

    assert payload["vendor_fusion_mode_observed"] == "vendor_fused_only"
    assert payload["raw_imu_present"] is False
    assert payload["raw_gnss_present"] is False
    assert payload["fused_navigation_present"] is True


def test_classifies_imu_and_vendor_fused_stream() -> None:
    payload = classify_vendor_fusion_stream(
        _wit_frame(0x51, [2048, 0, 0, 0]) + _wit_frame(0x58, [1, 2, 3, 4])
    )

    assert payload["vendor_fusion_mode_observed"] == "imu_and_vendor_fused"
    assert payload["raw_imu_present"] is True
    assert payload["raw_gnss_present"] is False
    assert payload["fused_navigation_present"] is True


def test_vendor_fusion_cli_raw_text_writes_jsonl(tmp_path: Path) -> None:
    output = tmp_path / "fusion.jsonl"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--raw-text",
            RMC.decode(),
            "--output-jsonl",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    persisted = json.loads(output.read_text())
    assert payload == persisted
    assert payload["vendor_fusion_mode_observed"] == "gps_raw_only"
    assert payload["phase1_safety_decision_change_allowed"] is False
    assert payload["remote_outbound_allowed"] is False
    assert payload["hardware_control_scope"] == "diagnostic_capture_only"


def test_vendor_fusion_stdlib_serial_fallback_reads_bytes() -> None:
    master_fd, slave_fd = pty.openpty()
    slave_name = os.ttyname(slave_fd)

    def writer() -> None:
        time.sleep(0.05)
        os.write(master_fd, RMC)

    thread = threading.Thread(target=writer)
    thread.start()
    try:
        data = _read_serial_bytes_stdlib(port=slave_name, baud=115200, duration_seconds=0.25)
    finally:
        thread.join(timeout=1.0)
        os.close(master_fd)
        os.close(slave_fd)

    assert RMC.strip() in data


def _wit_frame(frame_type: int, values: list[int]) -> bytes:
    payload = b"".join(value.to_bytes(2, "little", signed=True) for value in values)
    frame = bytes([0x55, frame_type]) + payload
    return frame + bytes([sum(frame) & 0xFF])
