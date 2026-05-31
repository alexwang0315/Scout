import json
import subprocess
import sys
from pathlib import Path

from tools.pi_gnss_diagnosis_report import build_diagnosis, render_markdown


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "pi_gnss_diagnosis_report.py"


def test_current_style_snapshot_remains_not_conclusive_without_gps_l1_comparator() -> None:
    report = build_diagnosis(snapshot=_snapshot(environment_has_gps=False, strong_labels=[]))

    assert report["conclusion"]["status"] == "not_yet_conclusive_gps_l1_environment_missing"
    assert report["environment_check"]["status"] == "unknown"
    assert "GPS GPGSV C/N0" in "\n".join(report["next_required_evidence"])
    assert report["target_checks"]["grove"][0]["status"] == "pass"


def test_report_strongly_supports_grove_rf_fault_when_comparator_has_gps_cno() -> None:
    report = build_diagnosis(snapshot=_snapshot(environment_has_gps=True, strong_labels=["grove"]))

    assert report["conclusion"]["status"] == "gnss_rf_path_fault_strongly_supported"
    assert report["conclusion"]["confidence"] == "high"


def test_report_handles_scout_labeled_target_without_gps_l1_comparator() -> None:
    report = build_diagnosis(
        snapshot=_snapshot(
            environment_has_gps=False,
            strong_labels=[],
            target_label="scout",
            comparator_label=None,
        )
    )

    assert report["conclusion"]["status"] == "not_yet_conclusive_gps_l1_environment_missing"
    assert "scout streams valid NMEA but no GPS C/N0" in report["conclusion"]["reason"]
    assert report["target_checks"]["scout"][0]["status"] == "pass"


def test_report_skips_loopback_next_step_when_all_command_paths_respond() -> None:
    report = build_diagnosis(
        snapshot=_snapshot(
            environment_has_gps=False,
            strong_labels=[],
            target_label="scout",
            comparator_label=None,
            target_command_path="receiver_response_observed",
        )
    )

    assert not any("loopback" in item for item in report["next_required_evidence"])


def test_physical_fault_overrides_incomplete_comparator_evidence() -> None:
    report = build_diagnosis(
        snapshot=_snapshot(environment_has_gps=False, strong_labels=[]),
        physical={
            "overall_status": "physical_fault_indicated",
            "likely_causes": ["RF input or antenna center conductor may be shorted to GND."],
        },
    )

    assert report["conclusion"]["status"] == "physical_fault_indicated"
    assert report["physical_check"]["status"] == "fail"
    assert "shorted to GND" in report["physical_check"]["likely_causes"][0]


def test_markdown_contains_conclusion_and_next_evidence() -> None:
    report = build_diagnosis(snapshot=_snapshot(environment_has_gps=False, strong_labels=[]))
    markdown = render_markdown(report)

    assert "# Scout GNSS Hardware Diagnosis Report" in markdown
    assert "not_yet_conclusive_gps_l1_environment_missing" in markdown
    assert "Next Required Evidence" in markdown
    assert "GPS-to-IMU D1" in markdown
    assert "not a GNSS RF/acquisition debug path" in markdown


def test_cli_writes_markdown_and_json(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot.json"
    output_json = tmp_path / "report.json"
    output_md = tmp_path / "report.md"
    snapshot.write_text(json.dumps(_snapshot(environment_has_gps=False, strong_labels=[])))

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--snapshot-json",
            str(snapshot),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(output_json.read_text())["source"] == "pi_gnss_diagnosis_report"
    assert "Scout GNSS Hardware Diagnosis Report" in output_md.read_text()
    assert "not_yet_conclusive" in result.stdout


def _snapshot(
    *,
    environment_has_gps: bool,
    strong_labels: list[str],
    target_label: str = "grove",
    comparator_label: str | None = "usb",
    target_command_path: str = "host_rx_only_observed",
) -> dict:
    usb_gps_rf = environment_has_gps
    per_target = {
        target_label: {
            "nmea_rx_path": "valid_nmea_received",
            "command_path": target_command_path,
            "fix_observed": False,
            "gps_rf_signal_observed": False,
            "any_rf_signal_observed": False,
            "gps_max_cno_dbhz": None,
            "max_cno_dbhz": None,
            "antenna_text_status": None,
            "ubx_mon_hw_seen": False,
            "ubx_nav_svinfo_seen": False,
            "likely_state": "no_rf_signal_observed",
        }
    }
    if comparator_label is not None:
        per_target[comparator_label] = {
            "nmea_rx_path": "valid_nmea_received",
            "command_path": "receiver_response_observed",
            "fix_observed": False,
            "gps_rf_signal_observed": usb_gps_rf,
            "any_rf_signal_observed": usb_gps_rf,
            "gps_max_cno_dbhz": 38 if usb_gps_rf else None,
            "max_cno_dbhz": 38 if usb_gps_rf else None,
            "antenna_text_status": "OK",
            "ubx_mon_hw_seen": False,
            "ubx_nav_svinfo_seen": False,
            "likely_state": "gps_rf_signal_observed_no_fix" if usb_gps_rf else "no_rf_signal_observed",
        }
    return {
        "hardware_snapshot": {
            "power": {
                "throttled": {"stdout": "throttled=0x0"},
                "temperature": {"stdout": "temp=46.6'C"},
            },
            "pinmux": {
                "gpio14": {"stdout": "14: a4 pn | hi // GPIO14 = TXD0"},
                "gpio15": {"stdout": "15: a4 pu | hi // GPIO15 = RXD0"},
            },
        },
        "verdict": {
            "environment_has_gps_l1_signal_for_comparison": environment_has_gps,
            "gps_rf_fault_strongly_supported_labels": strong_labels,
            "next_required_evidence": ["Move both receivers to a location where USB comparator shows GPS GPGSV C/N0 > 0"],
            "per_target": per_target,
        },
    }
