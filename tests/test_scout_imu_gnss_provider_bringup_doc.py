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
    assert "D1 mode is not a GNSS RF/acquisition debug path" in text
    assert "direct GNSS debug path" in text
    assert "GPGSV=0" in text
    assert "C/N0 全 0" in text
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
    assert "pi_grove_imu_9dof_smoke.py" in text
    assert "pi_gnss_nmea_smoke.py" in text
    assert "pi_imu_gnss_vendor_fusion_smoke.py" in text
    assert "--imu-address 0x69" in text
    assert "--mag-address 0x0c" in text
    assert "WHOAMI=0x11" in text
    assert "WIA=0x480c" in text
    assert "lsusb" in text
    assert "ls /dev/ttyUSB* /dev/ttyACM*" in text
    assert "python3 -m serial.tools.list_ports" in text
    assert "vcgencmd get_throttled" in text
    assert "scout-imu-gnss-provider-bringup.md" in text
    assert "D1 接法是 vendor fusion / integrated-navigation review path" in text
    assert "不是 GPS" in text
    assert "RF debug path" in text


def test_imu_gnss_bringup_doc_documents_grove_imu_9dof_i2c_smoke() -> None:
    text = BRINGUP_DOC.read_text(encoding="utf-8")

    assert "Grove IMU 9DOF I2C Smoke" in text
    assert "ICM20600" in text
    assert "AK09918" in text
    assert "WHOAMI=0x11" in text
    assert "WIA=0x480c" in text
    assert "pi_grove_imu_9dof_smoke.py" in text
    assert "primary_truth_allowed=false" in text
    assert "phase1_safety_decision_change_allowed=false" in text
    assert "remote_outbound_allowed=false" in text


def test_imu_gnss_bringup_doc_documents_host_ins_dr_mvp() -> None:
    text = BRINGUP_DOC.read_text(encoding="utf-8")

    assert "Host INS/DR Navigation MVP" in text
    assert "ins_dr_navigation.py" in text
    assert "ScoutInsDrNavigator" in text
    assert "GnssFix" in text
    assert "DeadReckoningDelta" in text
    assert "VendorFusionEstimate" in text
    assert "InsDrEstimate" in text
    assert "ins_dr_input_adapter.py" in text
    assert "tools/ins_dr_navigation_smoke.py" in text
    assert "tools/ins_dr_runtime_smoke.py" in text
    assert "tools/ins_dr_field_evidence_check.py" in text
    assert "tools/ins_dr_field_proof_pipeline.py" in text
    assert "tools/ins_dr_proof_manifest_check.py" in text
    assert "tools/ins_dr_field_completion_gate.py" in text
    assert "tools/ins_dr_diagnostic_route_scaffold.py" in text
    assert "tools/ins_dr_field_readiness_check.py" in text
    assert "tools/ins_dr_manual_field_run.py" in text
    assert "tools/ins_dr_live_field_proof.py" in text
    assert "diagnostic_navigation_estimate_only" in text
    assert "diagnostic_runtime_ingest_replay_only" in text
    assert "diagnostic_field_evidence_review_only" in text
    assert "diagnostic_field_proof_pipeline_only" in text
    assert "ins_dr_field_proof_manifest" in text
    assert "diagnostic_field_proof_manifest_only" in text
    assert "diagnostic_field_proof_manifest_verification_only" in text
    assert "diagnostic_field_completion_gate_only" in text
    assert "diagnostic_route_scaffold_only" in text
    assert "diagnostic_field_readiness_check_only" in text
    assert "diagnostic_manual_field_run_only" in text
    assert "diagnostic_live_field_proof_only" in text
    assert "primary_truth_allowed=false" in text
    assert "gnss_field_capture_not_replayed_fixture" in text
    assert "raw_gnss_checksum_valid_for_navigation" in text
    assert "capture_mode=raw_nmea_argument" in text
    assert "invalid_gnss_checksum_diagnostic_only" in text
    assert "primary_truth_scope=diagnostic_replayed_nmea_only" in text
    assert "field_proof_status=passed" in text
    assert "route_corridor_inside_for_navigation" in text
    assert "proof_manifest_status=passed" in text
    assert "scout_ins_dr_navigation_status=field_ready" in text
    assert "completion_ready=true" in text
    assert "field_run_readiness_status=ready" in text
    assert "gnss_serial_port_exists" in text
    assert "--gnss-port auto" in text
    assert "selected_gnss_port" in text
    assert "ambiguous_serial_candidates" in text
    assert "live-field-proof-report.json" in text
    assert "operator-events.jsonl" in text
    assert "diagnostic_live_field_proof_operator_guidance_only" in text
    assert "raw_nmea_rehearsal_no_serial_required" in text
    assert "--movement-window-seconds" in text
    assert "movement_window_seconds" in text
    assert "--allow-overwrite" in text
    assert "proof-manifest.json" in text
    assert "--require-reanchor" in text
    assert "SafetyRuntimeSession" in text
    assert "Live no-fix" in text
    assert "unanchored_dead_reckoning" in text
    assert "gnss_reanchor" in text
    assert "dead_reckoning_expired" in text
    assert "vendor_fusion_used_as_primary_truth=false" in text
    assert "vendor_fusion_disagreement" in text
    assert "route_progress.py" in text
    assert "DR Distance Source Contract" in text
    assert "tools/pi_dr_delta_smoke.py" in text
    assert "diagnostic_odometry_delta_only" in text
    assert "primary_truth_allowed=false" in text
    assert "raw.odometry" in text or '"odometry"' in text
    assert "distance_delta_m" in text
    assert "/safety/observations" in text
    assert "latest_position_estimate" in text
    assert "raw_gnss+dead_reckoning" in text
