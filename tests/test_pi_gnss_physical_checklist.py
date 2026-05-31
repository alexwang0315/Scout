import json
import subprocess
import sys
from pathlib import Path

from tools.pi_gnss_physical_checklist import build_template, evaluate_measurements, render_template_markdown


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "pi_gnss_physical_checklist.py"


def test_template_contains_required_physical_measurement_fields() -> None:
    template = build_template()["template"]

    assert "vcc_voltage_v" in template
    assert "power_off_rf_center_to_gnd_ohm" in template
    assert "v_ant_no_antenna_v" in template
    assert "gps_rx_waveform_observed_while_sending_pubx" in template


def test_template_returns_isolated_copy() -> None:
    first = build_template()
    first["template"]["vcc_voltage_v"] = 3.3

    second = build_template()

    assert second["template"]["vcc_voltage_v"] is None


def test_template_markdown_names_required_measurements() -> None:
    text = render_template_markdown(build_template())

    assert "Scout GNSS Physical Measurement Worksheet" in text
    assert "`vcc_voltage_v`" in text
    assert "`power_off_antenna_center_to_rf_in_ohm`" in text
    assert "pi_gnss_physical_checklist.py" in text


def test_evaluate_measurements_flags_rf_short_and_low_vcc() -> None:
    result = evaluate_measurements(
        {
            "module_label": "grove",
            "vcc_voltage_v": 2.1,
            "power_off_rf_center_to_gnd_ohm": 1.4,
            "power_off_antenna_center_to_gnd_ohm": 2500,
            "power_off_antenna_center_to_rf_in_ohm": 1.2,
            "power_off_antenna_shield_to_gnd_ohm": 0.3,
            "has_external_active_antenna": False,
            "antenna_patch_faces_sky": True,
            "antenna_clear_of_pi_ssd_battery_display_metal": True,
        }
    )

    assert result["overall_status"] == "physical_fault_indicated"
    assert result["status_counts"]["fail"] == 2
    assert any("Power rail" in cause for cause in result["likely_causes"])
    assert any("shorted to GND" in cause for cause in result["likely_causes"])


def test_evaluate_measurements_flags_active_antenna_bias_collapse() -> None:
    result = evaluate_measurements(
        {
            "module_label": "grove",
            "vcc_voltage_v": 3.3,
            "power_off_rf_center_to_gnd_ohm": 1000,
            "power_off_antenna_center_to_gnd_ohm": 1000,
            "power_off_antenna_center_to_rf_in_ohm": 0.8,
            "power_off_antenna_shield_to_gnd_ohm": 0.2,
            "has_external_active_antenna": True,
            "v_ant_no_antenna_v": 3.3,
            "v_ant_with_antenna_v": 0.1,
            "active_antenna_current_ma": 0.2,
            "antenna_patch_faces_sky": True,
            "antenna_clear_of_pi_ssd_battery_display_metal": True,
            "scout_tx_loopback_passed": True,
            "gps_rx_waveform_observed_while_sending_pubx": True,
        }
    )

    assert result["overall_status"] == "physical_fault_indicated"
    assert any(check["name"] == "active antenna bias" and check["status"] == "fail" for check in result["checks"])
    assert any("bias supply" in cause for cause in result["likely_causes"])


def test_evaluate_measurements_keeps_unknown_items_actionable() -> None:
    result = evaluate_measurements({"module_label": "grove"})

    assert result["overall_status"] == "physical_checks_incomplete"
    assert result["status_counts"]["unknown"] > 0
    assert any("Measure VCC" in step for step in result["next_required_measurements"])


def test_cli_writes_template_and_evaluates_measurements(tmp_path: Path) -> None:
    template = tmp_path / "template.json"
    template_md = tmp_path / "template.md"
    measurements = tmp_path / "measurements.json"
    output = tmp_path / "physical.json"

    template_result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--write-template",
            str(template),
            "--write-template-md",
            str(template_md),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert template_result.returncode == 0, template_result.stderr
    assert "`vcc_voltage_v`" in template_md.read_text()
    payload = json.loads(template.read_text())
    payload["template"]["vcc_voltage_v"] = 3.3
    payload["template"]["power_off_rf_center_to_gnd_ohm"] = 1000
    payload["template"]["power_off_antenna_center_to_gnd_ohm"] = 1000
    payload["template"]["power_off_antenna_center_to_rf_in_ohm"] = 1.0
    payload["template"]["power_off_antenna_shield_to_gnd_ohm"] = 0.2
    payload["template"]["has_external_active_antenna"] = False
    payload["template"]["antenna_patch_faces_sky"] = True
    payload["template"]["antenna_clear_of_pi_ssd_battery_display_metal"] = True
    payload["template"]["known_good_gps_l1_antenna_tested"] = False
    payload["template"]["scout_tx_loopback_passed"] = True
    payload["template"]["gps_rx_waveform_observed_while_sending_pubx"] = True
    measurements.write_text(json.dumps(payload))

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--measurements-json",
            str(measurements),
            "--output-json",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    persisted = json.loads(output.read_text())
    assert persisted["module_label"] == "grove"
    assert persisted["status_counts"]["fail"] == 0
