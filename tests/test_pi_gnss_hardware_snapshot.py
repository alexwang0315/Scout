import json
import subprocess
import sys
from pathlib import Path

from tools.pi_gnss_ab_compare import build_ab_payload, parse_nmea_capture
from tools.pi_gnss_hardware_snapshot import (
    build_auto_gnss_targets,
    build_verdict,
    parse_target_spec,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "pi_gnss_hardware_snapshot.py"
GROVE_NO_GPS_RF = "\n".join(
    [
        "$GPGGA,003100.799,,,,,0,0,,,M,,M,,*4D",
        "$GPGSV,1,1,00*79",
        "$GPRMC,003100.799,V,,,,,0.00,0.00,060180,,,N*47",
    ]
)
USB_GLONASS_ONLY = "\n".join(
    [
        "$GNGGA,,,,,,0,00,25.5,,,,,,*64",
        "$GPGSV,1,1,00,0*65",
        "$GLGSV,1,1,01,70,,,30,0*7C",
        "$GPTXT,01,01,01,ANTENNA OK*35",
        "$GNRMC,,V,,,,,,,,,,M,V*34",
    ]
)
USB_GPS_RF = "\n".join(
    [
        "$GNGGA,,,,,,0,00,25.5,,,,,,*64",
        "$GPGSV,1,1,01,03,45,180,38,0*54",
        "$GPTXT,01,01,01,ANTENNA OK*35",
        "$GNRMC,,V,,,,,,,,,,M,V*34",
    ]
)


def test_parse_target_spec_extracts_label_port_and_baud() -> None:
    target = parse_target_spec("grove=/dev/ttyAMA0:9600")

    assert target.label == "grove"
    assert target.device_port == "/dev/ttyAMA0"
    assert target.baud == 9600


def test_verdict_keeps_rf_fault_unproven_without_gps_l1_comparator() -> None:
    snapshot = _snapshot(
        [
            parse_nmea_capture(GROVE_NO_GPS_RF, label="grove"),
            parse_nmea_capture(USB_GLONASS_ONLY, label="usb"),
        ],
        command_paths={"grove": "host_rx_only_observed", "usb": "receiver_response_observed"},
    )

    verdict = build_verdict(snapshot)

    assert verdict["environment_has_gps_l1_signal_for_comparison"] is False
    assert verdict["gps_rf_fault_strongly_supported_labels"] == []
    assert "Grove" not in " ".join(verdict["gps_rf_fault_strongly_supported_labels"])
    assert any("GPS GPGSV C/N0" in item for item in verdict["next_required_evidence"])
    assert "grove: command path to receiver RX is not proven" in verdict["unresolved_items"]


def test_verdict_marks_target_suspect_when_comparator_has_gps_cno() -> None:
    snapshot = _snapshot(
        [
            parse_nmea_capture(GROVE_NO_GPS_RF, label="grove"),
            parse_nmea_capture(USB_GPS_RF, label="usb"),
        ],
        command_paths={"grove": "host_rx_only_observed", "usb": "receiver_response_observed"},
    )

    verdict = build_verdict(snapshot)

    assert verdict["environment_has_gps_l1_signal_for_comparison"] is True
    assert verdict["gps_ab_discriminates_hardware"] is True
    assert verdict["gps_rf_fault_strongly_supported_labels"] == ["grove"]
    assert verdict["per_target"]["usb"]["gps_max_cno_dbhz"] == 38


def test_verdict_skips_tx_loopback_next_step_when_receiver_response_is_observed() -> None:
    snapshot = _snapshot(
        [parse_nmea_capture(GROVE_NO_GPS_RF, label="scout")],
        command_paths={"scout": "receiver_response_observed"},
    )

    verdict = build_verdict(snapshot)

    assert verdict["per_target"]["scout"]["command_path"] == "receiver_response_observed"
    assert not any("loopback" in item for item in verdict["next_required_evidence"])
    assert any("target GNSS VCC" in item for item in verdict["next_required_evidence"])


def test_build_auto_gnss_targets_uses_usb_stable_candidates_by_default(tmp_path: Path) -> None:
    usb = {
        "path": str(tmp_path / "usb-1a86_USB_Serial-if00-port0"),
        "real_path": str(tmp_path / "ttyUSB0"),
        "kind": "stable_by_id",
        "priority": 0,
        "stable_path_preferred": True,
    }
    uart = {
        "path": str(tmp_path / "serial0"),
        "real_path": str(tmp_path / "ttyAMA0"),
        "kind": "linux_uart_alias",
        "priority": 30,
        "stable_path_preferred": False,
    }

    targets, selected = build_auto_gnss_targets(
        bauds=[115200],
        include_uart=False,
        serial_candidates=[usb, uart],
    )

    assert selected == [usb]
    assert targets[0].label == "auto_0_stable_by_id_usb_1a86_USB_Serial_if00_port0_115200"
    assert targets[0].device_port == usb["path"]
    assert targets[0].baud == 115200


def test_build_auto_gnss_targets_can_include_uart_when_requested(tmp_path: Path) -> None:
    usb = {
        "path": str(tmp_path / "usb-1a86_USB_Serial-if00-port0"),
        "real_path": str(tmp_path / "ttyUSB0"),
        "kind": "stable_by_id",
        "priority": 0,
        "stable_path_preferred": True,
    }
    uart = {
        "path": str(tmp_path / "serial0"),
        "real_path": str(tmp_path / "ttyAMA0"),
        "kind": "linux_uart_alias",
        "priority": 30,
        "stable_path_preferred": False,
    }

    targets, selected = build_auto_gnss_targets(
        bauds=[115200],
        include_uart=True,
        serial_candidates=[usb, uart],
    )

    assert selected == [usb, uart]
    assert [target.device_port for target in targets] == [usb["path"], uart["path"]]


def test_cli_requires_target_argument() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "--target" in result.stdout
    assert "--auto-targets" in result.stdout
    assert "GNSS hardware/RF diagnostic snapshot" in result.stdout


def _snapshot(captures: list[dict], *, command_paths: dict[str, str]) -> dict:
    return {
        "ab_compare": build_ab_payload(captures),
        "ublox_probes": {
            label: {
                "summary": {
                    "command_path_state": command_path,
                    "ubx_mon_hw_seen": False,
                    "ubx_nav_svinfo_seen": False,
                }
            }
            for label, command_path in command_paths.items()
        },
    }
