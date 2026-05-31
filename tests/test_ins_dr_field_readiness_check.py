import json
import subprocess
import sys
from pathlib import Path

from tools.ins_dr_diagnostic_route_scaffold import build_diagnostic_route_scaffold
from tools import ins_dr_field_readiness_check
from tools.ins_dr_field_readiness_check import (
    build_field_readiness_report,
    discover_gnss_serial_candidates,
    resolve_requested_gnss_port,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "ins_dr_field_readiness_check.py"


def test_field_readiness_check_passes_for_scaffolded_route_and_existing_serial_path(tmp_path: Path) -> None:
    scaffold = _build_scaffold(tmp_path / "scaffold")
    fake_port = tmp_path / "ttyUSB0"
    fake_port.write_text("", encoding="utf-8")

    report = build_field_readiness_report(
        mission_graph_path=Path(scaffold["mission_graph_json"]),
        gnss_port=fake_port,
        output_dir=tmp_path / "field-run",
    )

    assert report["source"] == "ins_dr_field_readiness_check"
    assert report["field_run_readiness_status"] == "ready"
    assert report["ready"] is True
    assert report["ready_for_live_field_proof"] is True
    assert report["hardware_control_scope"] == "diagnostic_field_readiness_check_only"
    assert _check_passed(report, "mission_graph_loads") is True
    assert _check_passed(report, "route_has_multiple_points") is True
    assert _check_passed(report, "map_corridor_available") is True
    assert _check_passed(report, "gnss_serial_port_exists") is True
    assert _check_passed(report, "output_dir_writable") is True


def test_field_readiness_check_fails_when_serial_path_is_missing(tmp_path: Path) -> None:
    scaffold = _build_scaffold(tmp_path / "scaffold")

    report = build_field_readiness_report(
        mission_graph_path=Path(scaffold["mission_graph_json"]),
        gnss_port=tmp_path / "missing-ttyUSB0",
        output_dir=tmp_path / "field-run",
    )

    assert report["field_run_readiness_status"] == "not_ready"
    assert report["ready"] is False
    assert _check_passed(report, "gnss_serial_port_exists") is False


def test_field_readiness_check_auto_selects_one_stable_serial_candidate(tmp_path: Path) -> None:
    scaffold = _build_scaffold(tmp_path / "scaffold")
    by_id_dir = tmp_path / "dev" / "serial" / "by-id"
    by_id_dir.mkdir(parents=True)
    stable_port = by_id_dir / "usb-u-blox_GNSS-if00-port0"
    stable_port.write_text("", encoding="utf-8")

    report = build_field_readiness_report(
        mission_graph_path=Path(scaffold["mission_graph_json"]),
        gnss_port=Path("auto"),
        output_dir=tmp_path / "field-run",
        serial_glob_patterns=[("stable_by_id", str(by_id_dir / "*"), 0)],
    )

    serial_check = _check(report, "gnss_serial_port_exists")
    assert report["ready"] is True
    assert report["requested_gnss_port"] == "auto"
    assert report["selected_gnss_port"] == str(stable_port)
    assert serial_check["passed"] is True
    assert serial_check["evidence"]["auto_detection_status"] == "selected_unique_candidate"
    assert serial_check["evidence"]["candidate_count"] == 1
    assert serial_check["evidence"]["candidates"][0]["stable_path_preferred"] is True


def test_field_readiness_check_auto_selects_valid_fix_candidate_from_ambiguous_serials(
    tmp_path: Path,
    monkeypatch,
) -> None:
    scaffold = _build_scaffold(tmp_path / "scaffold")
    dev_dir = tmp_path / "dev"
    dev_dir.mkdir()
    no_fix_port = dev_dir / "ttyUSB0"
    fix_port = dev_dir / "ttyUSB1"
    no_fix_port.write_text("", encoding="utf-8")
    fix_port.write_text("", encoding="utf-8")

    def serial_lines(*, port, baud, duration_seconds):
        if port == str(fix_port):
            return [
                _gga_sentence(lat=25.06370833, lon=121.654085, time_value="000010.000"),
                "$GPGSV,1,1,01,03,,,38,0*7D",
            ]
        return [
            "$GNGGA,,,,,,0,00,25.5,,,,,,*64",
            "$GPGSV,1,1,00,0*65",
            "$GNRMC,,V,,,,,,,,,,M,V*34",
        ]

    monkeypatch.setattr(ins_dr_field_readiness_check, "read_serial_nmea", serial_lines)

    report = build_field_readiness_report(
        mission_graph_path=Path(scaffold["mission_graph_json"]),
        gnss_port=Path("auto"),
        output_dir=tmp_path / "field-run",
        require_valid_gnss_fix=True,
        auto_select_gnss_by_fix_duration_seconds=0.1,
        auto_select_gnss_evidence_dir_path=tmp_path / "auto-select",
        serial_glob_patterns=[("linux_usb_serial", str(dev_dir / "ttyUSB*"), 10)],
    )

    assert report["ready"] is True
    assert report["selected_gnss_port"] == str(fix_port)
    assert _check_passed(report, "gnss_serial_port_exists") is True
    assert _check_passed(report, "gnss_auto_selection_has_valid_fix_candidate") is True
    assert report["gnss_auto_selection_summary"]["selection_status"] == "selected_valid_fix_candidate"
    assert report["gnss_auto_selection_summary"]["candidate_count"] == 2
    assert report["gnss_auto_selection_summary"]["selected_candidate"]["path"] == str(fix_port)
    assert report["gnss_evidence_summary"]["valid_fix_count"] == 1
    assert report["gnss_readiness_diagnosis"]["state"] == "valid_fix_ready"


def test_field_readiness_check_auto_selection_keeps_ambiguous_serials_blocked_without_valid_fix(
    tmp_path: Path,
    monkeypatch,
) -> None:
    scaffold = _build_scaffold(tmp_path / "scaffold")
    dev_dir = tmp_path / "dev"
    dev_dir.mkdir()
    first = dev_dir / "ttyUSB0"
    second = dev_dir / "ttyUSB1"
    first.write_text("", encoding="utf-8")
    second.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        ins_dr_field_readiness_check,
        "read_serial_nmea",
        lambda *, port, baud, duration_seconds: [
            "$GNGGA,,,,,,0,00,25.5,,,,,,*64",
            "$GLGSV,1,1,01,70,,,30,0*7C",
            "$GNRMC,,V,,,,,,,,,,M,V*34",
        ],
    )

    report = build_field_readiness_report(
        mission_graph_path=Path(scaffold["mission_graph_json"]),
        gnss_port=Path("auto"),
        output_dir=tmp_path / "field-run",
        require_valid_gnss_fix=True,
        auto_select_gnss_by_fix_duration_seconds=0.1,
        auto_select_gnss_evidence_dir_path=tmp_path / "auto-select",
        serial_glob_patterns=[("linux_usb_serial", str(dev_dir / "ttyUSB*"), 10)],
    )

    assert report["ready"] is False
    assert report["selected_gnss_port"] is None
    assert _check_passed(report, "gnss_serial_port_exists") is False
    assert _check_passed(report, "gnss_auto_selection_has_valid_fix_candidate") is False
    assert report["gnss_auto_selection_summary"]["selection_status"] == "no_valid_fix_candidate"
    assert report["gnss_auto_selection_summary"]["candidate_count"] == 2
    assert report["gnss_readiness_diagnosis"]["state"] == "non_gps_rf_signal_without_valid_fix"


def test_field_readiness_check_passes_with_valid_gnss_fix_evidence(tmp_path: Path) -> None:
    scaffold = _build_scaffold(tmp_path / "scaffold")
    fake_port = tmp_path / "ttyUSB0"
    fake_port.write_text("", encoding="utf-8")
    gnss_jsonl = tmp_path / "gnss.jsonl"
    _write_jsonl(
        [
            {
                "source": "pi_gnss_nmea_smoke",
                "sentence_type": "GPGGA",
                "capture_mode": "serial_device",
                "checksum_valid": True,
                "position": {"lat": 25.06370833, "lon": 121.654085, "altitude_m": 80.0},
                "fix_quality": {"valid": True, "quality": 1, "satellites": 9, "hdop": 0.8},
            },
            {
                "source": "pi_gnss_nmea_smoke",
                "sentence_type": "GPGSV",
                "checksum_valid": True,
                "position": {"lat": None, "lon": None, "altitude_m": None},
                "fix_quality": {"valid": False, "quality": None, "satellites": 1, "hdop": None},
                "satellite_signal": {
                    "talker": "GP",
                    "reported_visible_satellites": 1,
                    "satellites": [{"talker": "GP", "svid": 3, "cno_dbhz": 38}],
                },
            },
        ],
        gnss_jsonl,
    )

    report = build_field_readiness_report(
        mission_graph_path=Path(scaffold["mission_graph_json"]),
        gnss_port=fake_port,
        output_dir=tmp_path / "field-run",
        gnss_evidence_jsonl_paths=[gnss_jsonl],
        require_valid_gnss_fix=True,
    )

    assert report["ready"] is True
    assert _check_passed(report, "gnss_evidence_has_rf_signal_or_fix") is True
    assert _check_passed(report, "gnss_evidence_has_valid_fix") is True
    assert report["gnss_evidence_summary"]["valid_fix_count"] == 1
    assert report["gnss_evidence_summary"]["signal"]["gps_max_cno_dbhz"] == 38
    assert report["gnss_readiness_diagnosis"]["state"] == "valid_fix_ready"
    assert report["gnss_readiness_diagnosis"]["can_start_field_proof_from_gnss"] is True


def test_field_readiness_check_can_capture_live_gnss_evidence_for_gate(tmp_path: Path, monkeypatch) -> None:
    scaffold = _build_scaffold(tmp_path / "scaffold")
    fake_port = tmp_path / "ttyUSB0"
    fake_port.write_text("", encoding="utf-8")
    capture_jsonl = tmp_path / "captured-gnss.jsonl"

    monkeypatch.setattr(
        ins_dr_field_readiness_check,
        "read_serial_nmea",
        lambda *, port, baud, duration_seconds: [
            _gga_sentence(lat=25.06370833, lon=121.654085, time_value="000010.000"),
            "$GPGSV,1,1,01,03,,,38,0*7D",
        ],
    )

    report = build_field_readiness_report(
        mission_graph_path=Path(scaffold["mission_graph_json"]),
        gnss_port=fake_port,
        output_dir=tmp_path / "field-run",
        require_valid_gnss_fix=True,
        capture_gnss_duration_seconds=0.1,
        capture_gnss_evidence_jsonl_path=capture_jsonl,
        gnss_baud=115200,
    )

    assert report["ready"] is True
    assert _check_passed(report, "gnss_live_evidence_capture_completed") is True
    assert _check_passed(report, "gnss_evidence_has_rf_signal_or_fix") is True
    assert _check_passed(report, "gnss_evidence_has_valid_fix") is True
    assert report["gnss_live_capture_summary"]["capture_status"] == "captured"
    assert report["gnss_live_capture_summary"]["fix"]["valid_fix_count"] == 1
    assert report["gnss_evidence_summary"]["input_refs"] == [str(capture_jsonl)]
    assert report["gnss_evidence_summary"]["valid_fix_count"] == 1
    assert report["gnss_evidence_summary"]["fix"]["latest_valid_fix"]["position"]["lat"] == 25.06370833
    assert report["gnss_readiness_diagnosis"]["state"] == "valid_fix_ready"
    assert capture_jsonl.exists()


def test_field_readiness_check_diagnoses_rf_signal_without_valid_fix(tmp_path: Path) -> None:
    scaffold = _build_scaffold(tmp_path / "scaffold")
    fake_port = tmp_path / "ttyUSB0"
    fake_port.write_text("", encoding="utf-8")
    gnss_jsonl = tmp_path / "gnss.jsonl"
    _write_jsonl(
        [
            {
                "source": "pi_gnss_nmea_smoke",
                "sentence_type": "GNGGA",
                "capture_mode": "serial_device",
                "checksum_valid": True,
                "position": {"lat": None, "lon": None, "altitude_m": None},
                "fix_quality": {"valid": False, "quality": 0, "satellites": 0, "hdop": 25.5},
            },
            {
                "source": "pi_gnss_nmea_smoke",
                "sentence_type": "GLGSV",
                "checksum_valid": True,
                "position": {"lat": None, "lon": None, "altitude_m": None},
                "fix_quality": {"valid": False, "quality": None, "satellites": 1, "hdop": None},
                "satellite_signal": {
                    "talker": "GP",
                    "reported_visible_satellites": 1,
                    "satellites": [{"talker": "GP", "svid": 3, "cno_dbhz": 30}],
                },
            },
        ],
        gnss_jsonl,
    )

    report = build_field_readiness_report(
        mission_graph_path=Path(scaffold["mission_graph_json"]),
        gnss_port=fake_port,
        output_dir=tmp_path / "field-run",
        gnss_evidence_jsonl_paths=[gnss_jsonl],
        require_valid_gnss_fix=True,
    )

    assert report["ready"] is False
    assert _check_passed(report, "gnss_evidence_has_rf_signal_or_fix") is True
    assert _check_passed(report, "gnss_evidence_has_valid_fix") is False
    assert report["gnss_readiness_diagnosis"]["state"] == "rf_signal_without_valid_fix"
    assert report["gnss_readiness_diagnosis"]["rf_signal_observed"] is True
    assert report["gnss_readiness_diagnosis"]["gps_rf_signal_observed"] is True
    assert report["gnss_readiness_diagnosis"]["can_start_field_proof_from_gnss"] is False
    assert report["gnss_readiness_diagnosis"]["max_cno_dbhz"] == 30


def test_field_readiness_check_distinguishes_non_gps_rf_signal_without_valid_fix(tmp_path: Path) -> None:
    scaffold = _build_scaffold(tmp_path / "scaffold")
    fake_port = tmp_path / "ttyUSB0"
    fake_port.write_text("", encoding="utf-8")
    gnss_jsonl = tmp_path / "gnss.jsonl"
    _write_jsonl(
        [
            {
                "source": "pi_gnss_nmea_smoke",
                "sentence_type": "GNGGA",
                "capture_mode": "serial_device",
                "checksum_valid": True,
                "position": {"lat": None, "lon": None, "altitude_m": None},
                "fix_quality": {"valid": False, "quality": 0, "satellites": 0, "hdop": 25.5},
            },
            {
                "source": "pi_gnss_nmea_smoke",
                "sentence_type": "GLGSV",
                "checksum_valid": True,
                "position": {"lat": None, "lon": None, "altitude_m": None},
                "fix_quality": {"valid": False, "quality": None, "satellites": 1, "hdop": None},
                "satellite_signal": {
                    "talker": "GL",
                    "reported_visible_satellites": 1,
                    "satellites": [{"talker": "GL", "svid": 70, "cno_dbhz": 30}],
                },
            },
        ],
        gnss_jsonl,
    )

    report = build_field_readiness_report(
        mission_graph_path=Path(scaffold["mission_graph_json"]),
        gnss_port=fake_port,
        output_dir=tmp_path / "field-run",
        gnss_evidence_jsonl_paths=[gnss_jsonl],
        require_valid_gnss_fix=True,
    )

    assert report["ready"] is False
    assert _check_passed(report, "gnss_evidence_has_rf_signal_or_fix") is True
    assert _check_passed(report, "gnss_evidence_has_valid_fix") is False
    assert report["gnss_readiness_diagnosis"]["state"] == "non_gps_rf_signal_without_valid_fix"
    assert report["gnss_readiness_diagnosis"]["rf_signal_observed"] is True
    assert report["gnss_readiness_diagnosis"]["gps_rf_signal_observed"] is False
    assert report["gnss_readiness_diagnosis"]["max_cno_dbhz"] == 30
    assert report["gnss_readiness_diagnosis"]["gps_max_cno_dbhz"] is None


def test_field_readiness_check_blocks_no_fix_and_zero_cno_gnss_evidence(tmp_path: Path) -> None:
    scaffold = _build_scaffold(tmp_path / "scaffold")
    fake_port = tmp_path / "ttyUSB0"
    fake_port.write_text("", encoding="utf-8")
    gnss_jsonl = tmp_path / "gnss.jsonl"
    _write_jsonl(
        [
            {
                "source": "pi_gnss_nmea_smoke",
                "sentence_type": "GNGGA",
                "capture_mode": "serial_device",
                "checksum_valid": True,
                "position": {"lat": None, "lon": None, "altitude_m": None},
                "fix_quality": {"valid": False, "quality": 0, "satellites": 0, "hdop": 25.5},
            },
            {
                "source": "pi_gnss_nmea_smoke",
                "sentence_type": "GPGSV",
                "checksum_valid": True,
                "position": {"lat": None, "lon": None, "altitude_m": None},
                "fix_quality": {"valid": False, "quality": None, "satellites": 0, "hdop": None},
                "satellite_signal": {
                    "talker": "GP",
                    "reported_visible_satellites": 0,
                    "satellites": [],
                },
            },
        ],
        gnss_jsonl,
    )

    report = build_field_readiness_report(
        mission_graph_path=Path(scaffold["mission_graph_json"]),
        gnss_port=fake_port,
        output_dir=tmp_path / "field-run",
        gnss_evidence_jsonl_paths=[gnss_jsonl],
        require_valid_gnss_fix=True,
    )

    assert report["ready"] is False
    assert _check_passed(report, "gnss_evidence_has_rf_signal_or_fix") is False
    assert _check_passed(report, "gnss_evidence_has_valid_fix") is False
    assert report["gnss_evidence_summary"]["valid_fix_count"] == 0
    assert report["gnss_evidence_summary"]["signal"]["reported_visible_satellites"] == 0
    assert report["gnss_evidence_summary"]["signal"]["max_cno_dbhz"] is None
    assert report["gnss_readiness_diagnosis"]["state"] == "no_rf_signal_observed"
    assert report["gnss_readiness_diagnosis"]["can_start_field_proof_from_gnss"] is False


def test_field_readiness_check_includes_gnss_hardware_snapshot_verdict(tmp_path: Path) -> None:
    scaffold = _build_scaffold(tmp_path / "scaffold")
    fake_port = tmp_path / "ttyUSB0"
    fake_port.write_text("", encoding="utf-8")
    snapshot_json = tmp_path / "gnss-hardware-snapshot.json"
    snapshot_json.write_text(
        json.dumps(
            {
                "source": "pi_gnss_hardware_snapshot",
                "hardware_kind": "gnss_antenna_rf_hardware_snapshot",
                "hardware_control_scope": "diagnostic_read_only_plus_non_destructive_polls",
                "targets": [{"label": "scout", "device_port": "/dev/ttyUSB0", "baud": 115200}],
                "verdict": {
                    "per_target": {
                        "scout": {
                            "nmea_rx_path": "valid_nmea_received",
                            "gps_rf_signal_observed": False,
                        }
                    },
                    "gps_ab_discriminates_hardware": False,
                    "gps_rf_fault_strongly_supported_labels": [],
                    "environment_has_gps_l1_signal_for_comparison": False,
                    "unresolved_items": [
                        "No comparator currently shows GPS GPGSV C/N0, so GPS-only RF hardware cannot be conclusively discriminated at this location"
                    ],
                    "next_required_evidence": [
                        "Move both receivers to a location where USB comparator shows GPS GPGSV C/N0 > 0",
                        "Measure Grove VCC to GND under load while NMEA is streaming",
                    ],
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    report = build_field_readiness_report(
        mission_graph_path=Path(scaffold["mission_graph_json"]),
        gnss_port=fake_port,
        output_dir=tmp_path / "field-run",
        gnss_hardware_snapshot_json_path=snapshot_json,
    )

    assert report["ready"] is True
    assert _check_passed(report, "gnss_hardware_snapshot_loaded") is True
    assert report["gnss_hardware_snapshot_summary"]["source"] == "pi_gnss_hardware_snapshot"
    assert report["gnss_hardware_snapshot_summary"]["verdict"]["per_target"]["scout"]["nmea_rx_path"] == "valid_nmea_received"
    assert report["gnss_hardware_snapshot_summary"]["verdict"]["next_required_evidence"] == [
        "Move both receivers to a location where USB comparator shows GPS GPGSV C/N0 > 0",
        "Measure Grove VCC to GND under load while NMEA is streaming",
    ]


def test_field_readiness_check_fails_when_requested_gnss_hardware_snapshot_is_missing(tmp_path: Path) -> None:
    scaffold = _build_scaffold(tmp_path / "scaffold")
    fake_port = tmp_path / "ttyUSB0"
    fake_port.write_text("", encoding="utf-8")
    missing_snapshot = tmp_path / "missing-gnss-hardware-snapshot.json"

    report = build_field_readiness_report(
        mission_graph_path=Path(scaffold["mission_graph_json"]),
        gnss_port=fake_port,
        output_dir=tmp_path / "field-run",
        gnss_hardware_snapshot_json_path=missing_snapshot,
    )

    assert report["ready"] is False
    assert _check_passed(report, "gnss_hardware_snapshot_loaded") is False
    assert report["gnss_hardware_snapshot_summary"]["loaded"] is False
    assert "FileNotFoundError" in report["gnss_hardware_snapshot_summary"]["error"]


def test_field_readiness_check_auto_fails_when_serial_candidates_are_ambiguous(tmp_path: Path) -> None:
    scaffold = _build_scaffold(tmp_path / "scaffold")
    dev_dir = tmp_path / "dev"
    dev_dir.mkdir()
    first = dev_dir / "ttyUSB0"
    second = dev_dir / "ttyUSB1"
    first.write_text("", encoding="utf-8")
    second.write_text("", encoding="utf-8")

    report = build_field_readiness_report(
        mission_graph_path=Path(scaffold["mission_graph_json"]),
        gnss_port=Path("auto"),
        output_dir=tmp_path / "field-run",
        serial_glob_patterns=[("linux_usb_serial", str(dev_dir / "ttyUSB*"), 10)],
    )

    serial_check = _check(report, "gnss_serial_port_exists")
    assert report["ready"] is False
    assert report["selected_gnss_port"] is None
    assert serial_check["passed"] is False
    assert serial_check["evidence"]["auto_detection_status"] == "ambiguous_serial_candidates"
    assert serial_check["evidence"]["candidate_count"] == 2
    assert [candidate["path"] for candidate in serial_check["evidence"]["candidates"]] == [str(first), str(second)]


def test_discover_gnss_serial_candidates_prefers_stable_path_and_deduplicates_real_device(tmp_path: Path) -> None:
    dev_dir = tmp_path / "dev"
    by_id_dir = dev_dir / "serial" / "by-id"
    by_id_dir.mkdir(parents=True)
    real_port = dev_dir / "ttyUSB0"
    real_port.write_text("", encoding="utf-8")
    stable_link = by_id_dir / "usb-u-blox_GNSS-if00-port0"
    stable_link.symlink_to(real_port)

    candidates = discover_gnss_serial_candidates(
        serial_glob_patterns=[
            ("stable_by_id", str(by_id_dir / "*"), 0),
            ("linux_usb_serial", str(dev_dir / "ttyUSB*"), 10),
        ]
    )
    resolved, evidence = resolve_requested_gnss_port(
        Path("auto"),
        serial_glob_patterns=[
            ("stable_by_id", str(by_id_dir / "*"), 0),
            ("linux_usb_serial", str(dev_dir / "ttyUSB*"), 10),
        ],
    )

    assert len(candidates) == 1
    assert candidates[0]["path"] == str(stable_link)
    assert candidates[0]["real_path"] == str(real_port)
    assert candidates[0]["stable_path_preferred"] is True
    assert resolved == stable_link
    assert evidence["auto_detection_status"] == "selected_unique_candidate"


def test_resolve_auto_gnss_port_skips_uart_candidates_by_default(tmp_path: Path) -> None:
    dev_dir = tmp_path / "dev"
    by_id_dir = dev_dir / "serial" / "by-id"
    by_id_dir.mkdir(parents=True)
    real_port = dev_dir / "ttyUSB0"
    real_port.write_text("", encoding="utf-8")
    stable_link = by_id_dir / "usb-u-blox_GNSS-if00-port0"
    stable_link.symlink_to(real_port)
    serial0 = dev_dir / "serial0"
    serial0.write_text("", encoding="utf-8")

    resolved, evidence = resolve_requested_gnss_port(
        Path("auto"),
        serial_glob_patterns=[
            ("stable_by_id", str(by_id_dir / "*"), 0),
            ("linux_uart_alias", str(serial0), 30),
        ],
    )
    resolved_with_uart, evidence_with_uart = resolve_requested_gnss_port(
        Path("auto"),
        include_uart_serial_candidates=True,
        serial_glob_patterns=[
            ("stable_by_id", str(by_id_dir / "*"), 0),
            ("linux_uart_alias", str(serial0), 30),
        ],
    )

    assert resolved == stable_link
    assert evidence["auto_detection_status"] == "selected_unique_candidate"
    assert evidence["candidate_count"] == 1
    assert resolved_with_uart == Path("auto")
    assert evidence_with_uart["auto_detection_status"] == "ambiguous_serial_candidates"
    assert evidence_with_uart["candidate_count"] == 2


def test_field_readiness_check_rejects_existing_artifacts_without_overwrite_flag(tmp_path: Path) -> None:
    scaffold = _build_scaffold(tmp_path / "scaffold")
    fake_port = tmp_path / "ttyUSB0"
    fake_port.write_text("", encoding="utf-8")
    output_dir = tmp_path / "field-run"
    output_dir.mkdir()
    (output_dir / "anchor-gnss.jsonl").write_text("{}\n", encoding="utf-8")

    blocked = build_field_readiness_report(
        mission_graph_path=Path(scaffold["mission_graph_json"]),
        gnss_port=fake_port,
        output_dir=output_dir,
    )
    allowed = build_field_readiness_report(
        mission_graph_path=Path(scaffold["mission_graph_json"]),
        gnss_port=fake_port,
        output_dir=output_dir,
        allow_overwrite=True,
    )

    assert blocked["ready"] is False
    blocked_check = _check(blocked, "output_dir_not_reusing_existing_proof_artifacts")
    assert blocked_check["passed"] is False
    assert blocked_check["evidence"]["existing_artifacts"] == ["anchor-gnss.jsonl"]
    assert allowed["ready"] is True
    allowed_check = _check(allowed, "output_dir_not_reusing_existing_proof_artifacts")
    assert allowed_check["passed"] is True
    assert allowed_check["evidence"]["allow_overwrite"] is True


def test_field_readiness_check_cli_returns_nonzero_when_not_ready(tmp_path: Path) -> None:
    scaffold = _build_scaffold(tmp_path / "scaffold")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--mission-graph",
            scaffold["mission_graph_json"],
            "--gnss-port",
            str(tmp_path / "missing-ttyUSB0"),
            "--output-dir",
            str(tmp_path / "field-run"),
            "--pretty",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["field_run_readiness_status"] == "not_ready"
    assert _check_passed(report, "gnss_serial_port_exists") is False


def _build_scaffold(output_dir: Path) -> dict:
    return build_diagnostic_route_scaffold(
        output_dir=output_dir,
        mission_id="ins_dr_readiness_test",
        start_lat=25.06370833,
        start_lon=121.654085,
        heading_deg=87.5,
        distance_m=3.0,
        point_count=4,
        corridor_half_width_m=6.0,
    )


def _check(report: dict, name: str) -> dict:
    return next(check for check in report["checks"] if check["name"] == name)


def _check_passed(report: dict, name: str) -> bool:
    return bool(_check(report, name)["passed"])


def _write_jsonl(payloads: list[dict], path: Path) -> None:
    path.write_text(
        "".join(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n" for payload in payloads),
        encoding="utf-8",
    )


def _gga_sentence(*, lat: float, lon: float, time_value: str) -> str:
    lat_value, lat_hemi = _nmea_lat(lat)
    lon_value, lon_hemi = _nmea_lon(lon)
    body = f"GPGGA,{time_value},{lat_value},{lat_hemi},{lon_value},{lon_hemi},1,09,0.8,80.0,M,20.1,M,,"
    checksum = 0
    for char in body:
        checksum ^= ord(char)
    return f"${body}*{checksum:02X}"


def _nmea_lat(value: float) -> tuple[str, str]:
    hemi = "N" if value >= 0 else "S"
    absolute = abs(value)
    degrees = int(absolute)
    minutes = (absolute - degrees) * 60.0
    return f"{degrees:02d}{minutes:07.4f}", hemi


def _nmea_lon(value: float) -> tuple[str, str]:
    hemi = "E" if value >= 0 else "W"
    absolute = abs(value)
    degrees = int(absolute)
    minutes = (absolute - degrees) * 60.0
    return f"{degrees:03d}{minutes:07.4f}", hemi
