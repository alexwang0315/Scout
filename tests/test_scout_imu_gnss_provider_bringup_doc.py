from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRINGUP_DOC = ROOT / "docs" / "specs" / "scout-imu-gnss-provider-bringup.md"
SMOKE_DOC = ROOT / "docs" / "admin" / "scout-machine-deployment-smoke.md"


def test_imu_gnss_bringup_doc_preserves_primary_truth_boundary() -> None:
    text = BRINGUP_DOC.read_text(encoding="utf-8")

    assert "Raw GNSS NMEA/RMC/GGA" in text
    assert "GNSS timestamp authority" in text
    assert "Raw IMU frames" in text
    assert "Vendor GPS-IMU/INS fused output" in text
    assert "primary_truth_allowed=false for IMU and vendor fusion" in text
    assert "raw_gnss_observation_only" in text
    assert "vendor_fusion_algorithm=opaque" in text
    assert "不得直接改 L0-L4 safety level" in text
    assert "不可接 live" in text


def test_imu_gnss_bringup_doc_covers_d1_modes_and_ros_boundary() -> None:
    text = BRINGUP_DOC.read_text(encoding="utf-8")

    assert "GPS To IMU D1 Review Mode" in text
    assert "imu_with_gps_fields" in text
    assert "gps_raw_only" in text
    assert "imu_only" in text
    assert "vendor_fused_only" in text
    assert "imu_and_vendor_fused" in text
    assert "Why Not ROS First" in text
    assert "不應成為 Scout runtime" in text


def test_machine_smoke_runbook_links_imu_gnss_tools() -> None:
    text = SMOKE_DOC.read_text(encoding="utf-8")

    assert "pi_hiwonder_imu_usb_smoke.py" in text
    assert "pi_gnss_nmea_smoke.py" in text
    assert "pi_imu_gnss_vendor_fusion_smoke.py" in text
    assert "lsusb" in text
    assert "ls /dev/ttyUSB* /dev/ttyACM*" in text
    assert "python3 -m serial.tools.list_ports" in text
    assert "vcgencmd get_throttled" in text
    assert "scout-imu-gnss-provider-bringup.md" in text
