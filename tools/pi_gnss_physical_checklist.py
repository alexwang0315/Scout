from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_TEMPLATE: dict[str, Any] = {
    "module_label": "grove",
    "measurement_context": "same location as Scout GNSS A/B test",
    "operator_notes": "",
    "vcc_voltage_v": None,
    "vcc_expected_min_v": 3.0,
    "vcc_expected_max_v": 5.5,
    "power_off_rf_center_to_gnd_ohm": None,
    "power_off_antenna_center_to_gnd_ohm": None,
    "power_off_antenna_center_to_rf_in_ohm": None,
    "power_off_antenna_shield_to_gnd_ohm": None,
    "has_external_active_antenna": None,
    "v_ant_no_antenna_v": None,
    "v_ant_with_antenna_v": None,
    "active_antenna_current_ma": None,
    "antenna_patch_faces_sky": None,
    "antenna_clear_of_pi_ssd_battery_display_metal": None,
    "known_good_gps_l1_antenna_tested": None,
    "known_good_gps_l1_antenna_cno_observed": None,
    "scout_tx_loopback_passed": None,
    "gps_rx_waveform_observed_while_sending_pubx": None,
}


def build_template() -> dict[str, Any]:
    return {
        "source": "pi_gnss_physical_checklist",
        "hardware_kind": "gnss_physical_measurement_template",
        "hardware_control_scope": "operator_measurement_entry_template_only",
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "template": dict(DEFAULT_TEMPLATE),
    }


def render_template_markdown(template_payload: dict[str, Any] | None = None) -> str:
    payload = template_payload or build_template()
    template = payload.get("template") if isinstance(payload.get("template"), dict) else {}
    lines = [
        "# Scout GNSS Physical Measurement Worksheet",
        "",
        "Fill the JSON template values, then rerun `pi_gnss_physical_checklist.py --measurements-json`.",
        "Leave unknown values as `null`; the interpreter will list the missing measurements.",
        "",
        "## Required no-RF triage values",
        "",
        "| Field | Current value | What to measure |",
        "| --- | --- | --- |",
    ]
    for field in _required_no_rf_fields():
        lines.append(f"| `{field}` | `{template.get(field)}` | {_measurement_hint(field)} |")
    lines.extend(
        [
            "",
            "## Optional but useful values",
            "",
            "| Field | Current value | What it proves |",
            "| --- | --- | --- |",
        ]
    )
    for field in _optional_fields():
        lines.append(f"| `{field}` | `{template.get(field)}` | {_measurement_hint(field)} |")
    lines.extend(
        [
            "",
            "## Rerun",
            "",
            "```bash",
            "python3 tools/pi_gnss_physical_checklist.py \\",
            "  --measurements-json /path/to/physical-measurements-filled.json \\",
            "  --output-json /path/to/gnss-physical-checklist-report.json",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def evaluate_measurements(measurements: dict[str, Any]) -> dict[str, Any]:
    checks = [
        _check_vcc(measurements),
        _check_resistance(
            measurements,
            field="power_off_rf_center_to_gnd_ohm",
            label="RF_IN to GND short check",
            pass_min_ohm=100.0,
            fail_max_ohm=10.0,
        ),
        _check_resistance(
            measurements,
            field="power_off_antenna_center_to_gnd_ohm",
            label="antenna center to GND short check",
            pass_min_ohm=100.0,
            fail_max_ohm=10.0,
        ),
        _check_continuity(
            measurements,
            field="power_off_antenna_center_to_rf_in_ohm",
            label="antenna center to RF_IN continuity",
            pass_max_ohm=5.0,
        ),
        _check_continuity(
            measurements,
            field="power_off_antenna_shield_to_gnd_ohm",
            label="antenna shield to GND continuity",
            pass_max_ohm=2.0,
        ),
        _check_active_antenna_bias(measurements),
        _check_active_antenna_current(measurements),
        _check_boolean(
            measurements,
            field="antenna_patch_faces_sky",
            label="ceramic patch faces sky",
            fail_when_false=True,
        ),
        _check_boolean(
            measurements,
            field="antenna_clear_of_pi_ssd_battery_display_metal",
            label="antenna clear of nearby blockers",
            fail_when_false=True,
        ),
        _check_known_good_antenna(measurements),
        _check_tx_path(measurements),
    ]
    checks = [check for check in checks if check is not None]
    counts = _status_counts(checks)
    likely_causes = _likely_causes(checks, measurements)
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": "pi_gnss_physical_checklist",
        "hardware_kind": "gnss_physical_measurement_interpretation",
        "hardware_control_scope": "operator_entered_measurement_interpretation_only",
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "module_label": measurements.get("module_label"),
        "measurement_context": measurements.get("measurement_context"),
        "operator_notes": measurements.get("operator_notes"),
        "checks": checks,
        "status_counts": counts,
        "likely_causes": likely_causes,
        "overall_status": _overall_status(counts),
        "next_required_measurements": _next_required_measurements(checks),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Interpret operator-entered GNSS antenna/RF physical measurements.")
    parser.add_argument("--write-template", type=Path, help="Write a JSON measurement template and exit.")
    parser.add_argument("--write-template-md", type=Path, help="Write a Markdown measurement worksheet and exit.")
    parser.add_argument("--measurements-json", type=Path, help="JSON file containing operator-entered measurements.")
    parser.add_argument("--output-json", type=Path, help="Optional path to persist interpreted checklist JSON.")
    args = parser.parse_args(argv)

    if args.write_template or args.write_template_md:
        payload = build_template()
        if args.write_template:
            _write_json(args.write_template, payload)
        if args.write_template_md:
            args.write_template_md.parent.mkdir(parents=True, exist_ok=True)
            args.write_template_md.write_text(render_template_markdown(payload), encoding="utf-8")
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    if args.measurements_json is None:
        parser.error("--measurements-json is required unless --write-template is used")

    measurements = json.loads(args.measurements_json.read_text())
    if "template" in measurements and isinstance(measurements["template"], dict):
        measurements = measurements["template"]
    payload = evaluate_measurements(measurements)
    if args.output_json:
        _write_json(args.output_json, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _check_vcc(measurements: dict[str, Any]) -> dict[str, Any]:
    value = _number(measurements.get("vcc_voltage_v"))
    min_v = _number(measurements.get("vcc_expected_min_v"), default=3.0)
    max_v = _number(measurements.get("vcc_expected_max_v"), default=5.5)
    if value is None:
        return _unknown("VCC under-load voltage", "Measure VCC to GND while NMEA is streaming.")
    if min_v <= value <= max_v:
        return _check("VCC under-load voltage", "pass", value=value, unit="V")
    return _check(
        "VCC under-load voltage",
        "fail",
        value=value,
        unit="V",
        detail=f"Expected {min_v:g}-{max_v:g} V under load.",
    )


def _check_resistance(
    measurements: dict[str, Any],
    *,
    field: str,
    label: str,
    pass_min_ohm: float,
    fail_max_ohm: float,
) -> dict[str, Any]:
    value = _number(measurements.get(field))
    if value is None:
        return _unknown(label, f"Measure {field} with power off.")
    if value <= fail_max_ohm:
        return _check(label, "fail", value=value, unit="ohm", detail="Low resistance suggests a short.")
    if value >= pass_min_ohm:
        return _check(label, "pass", value=value, unit="ohm")
    return _check(label, "warn", value=value, unit="ohm", detail="Borderline resistance; compare with module schematic or known-good board.")


def _check_continuity(
    measurements: dict[str, Any],
    *,
    field: str,
    label: str,
    pass_max_ohm: float,
) -> dict[str, Any]:
    value = _number(measurements.get(field))
    if value is None:
        return _unknown(label, f"Measure {field} with power off.")
    if value <= pass_max_ohm:
        return _check(label, "pass", value=value, unit="ohm")
    return _check(label, "fail", value=value, unit="ohm", detail="High resistance suggests an open path or bad solder/contact.")


def _check_active_antenna_bias(measurements: dict[str, Any]) -> dict[str, Any]:
    has_active = measurements.get("has_external_active_antenna")
    no_ant = _number(measurements.get("v_ant_no_antenna_v"))
    with_ant = _number(measurements.get("v_ant_with_antenna_v"))
    if has_active is False:
        return _check("active antenna bias", "pass", detail="Marked not applicable for passive/integrated antenna.")
    if has_active is None and no_ant is None and with_ant is None:
        return _unknown("active antenna bias", "If using active antenna, measure V_ANT with and without antenna attached.")
    if no_ant is None or with_ant is None:
        return _unknown("active antenna bias", "Need both v_ant_no_antenna_v and v_ant_with_antenna_v.")
    if no_ant < 2.5:
        return _check("active antenna bias", "fail", value=no_ant, unit="V", detail="No unloaded antenna bias voltage.")
    if with_ant < 0.5:
        return _check("active antenna bias", "fail", value=with_ant, unit="V", detail="Antenna bias collapses when antenna is attached.")
    if with_ant < 2.5:
        return _check("active antenna bias", "warn", value=with_ant, unit="V", detail="Loaded antenna bias is low.")
    return _check("active antenna bias", "pass", value=with_ant, unit="V")


def _check_active_antenna_current(measurements: dict[str, Any]) -> dict[str, Any]:
    has_active = measurements.get("has_external_active_antenna")
    current = _number(measurements.get("active_antenna_current_ma"))
    if has_active is False:
        return _check("active antenna current", "pass", detail="Marked not applicable for passive/integrated antenna.")
    if current is None:
        return _unknown("active antenna current", "If using active antenna, measure current draw.")
    if 1.0 <= current <= 30.0:
        return _check("active antenna current", "pass", value=current, unit="mA")
    return _check("active antenna current", "warn", value=current, unit="mA", detail="Compare with active antenna datasheet.")


def _check_boolean(
    measurements: dict[str, Any],
    *,
    field: str,
    label: str,
    fail_when_false: bool,
) -> dict[str, Any]:
    value = measurements.get(field)
    if value is None:
        return _unknown(label, f"Set {field} to true or false.")
    if bool(value):
        return _check(label, "pass")
    status = "fail" if fail_when_false else "warn"
    return _check(label, status)


def _check_known_good_antenna(measurements: dict[str, Any]) -> dict[str, Any]:
    tested = measurements.get("known_good_gps_l1_antenna_tested")
    observed = measurements.get("known_good_gps_l1_antenna_cno_observed")
    if tested is None:
        return _unknown("known-good GPS L1 antenna test", "If possible, compare with known-good GPS L1 antenna.")
    if not tested:
        return _unknown("known-good GPS L1 antenna test", "Known-good antenna was not tested.")
    if observed is True:
        return _check("known-good GPS L1 antenna test", "pass", detail="Known-good antenna produced GPS L1 C/N0.")
    if observed is False:
        return _check("known-good GPS L1 antenna test", "fail", detail="Known-good antenna still produced no GPS L1 C/N0.")
    return _unknown("known-good GPS L1 antenna test", "Set known_good_gps_l1_antenna_cno_observed.")


def _check_tx_path(measurements: dict[str, Any]) -> dict[str, Any]:
    loopback = measurements.get("scout_tx_loopback_passed")
    waveform = measurements.get("gps_rx_waveform_observed_while_sending_pubx")
    if loopback is True and waveform is True:
        return _check("Scout TX to GPS RX command path", "pass")
    if loopback is False:
        return _check("Scout TX to GPS RX command path", "fail", detail="Scout UART TX loopback failed.")
    if waveform is False:
        return _check("Scout TX to GPS RX command path", "fail", detail="No waveform observed at GPS RX while sending PUBX.")
    return _unknown("Scout TX to GPS RX command path", "Use loopback or logic analyzer/scope while sending PUBX.")


def _required_no_rf_fields() -> list[str]:
    return [
        "vcc_voltage_v",
        "power_off_rf_center_to_gnd_ohm",
        "power_off_antenna_center_to_gnd_ohm",
        "power_off_antenna_center_to_rf_in_ohm",
        "power_off_antenna_shield_to_gnd_ohm",
        "antenna_patch_faces_sky",
        "antenna_clear_of_pi_ssd_battery_display_metal",
    ]


def _optional_fields() -> list[str]:
    return [
        "has_external_active_antenna",
        "v_ant_no_antenna_v",
        "v_ant_with_antenna_v",
        "active_antenna_current_ma",
        "known_good_gps_l1_antenna_tested",
        "known_good_gps_l1_antenna_cno_observed",
        "scout_tx_loopback_passed",
        "gps_rx_waveform_observed_while_sending_pubx",
        "operator_notes",
    ]


def _measurement_hint(field: str) -> str:
    hints = {
        "vcc_voltage_v": "VCC to GND while NMEA is streaming.",
        "power_off_rf_center_to_gnd_ohm": "Power off, RF_IN center to GND resistance.",
        "power_off_antenna_center_to_gnd_ohm": "Power off, antenna connector center to GND resistance.",
        "power_off_antenna_center_to_rf_in_ohm": "Power off, antenna connector center to receiver RF_IN continuity.",
        "power_off_antenna_shield_to_gnd_ohm": "Power off, antenna shield to board GND continuity.",
        "antenna_patch_faces_sky": "`true` only when the ceramic patch/front face points at open sky.",
        "antenna_clear_of_pi_ssd_battery_display_metal": "`true` only when clear of Pi, SSD, battery, display, and metal.",
        "has_external_active_antenna": "`true` when an active GPS L1 antenna is attached.",
        "v_ant_no_antenna_v": "Active antenna bias voltage with antenna disconnected.",
        "v_ant_with_antenna_v": "Active antenna bias voltage with antenna connected.",
        "active_antenna_current_ma": "Active antenna current draw in mA.",
        "known_good_gps_l1_antenna_tested": "`true` after trying a known-good GPS L1 antenna.",
        "known_good_gps_l1_antenna_cno_observed": "`true` if known-good antenna produces GPS C/N0.",
        "scout_tx_loopback_passed": "`true` if Scout UART TX loopback passes.",
        "gps_rx_waveform_observed_while_sending_pubx": "`true` if GPS RX pin sees waveform while sending PUBX.",
        "operator_notes": "Short notes about antenna, cable, placement, or meter setup.",
    }
    return hints.get(field, "Operator-entered measurement.")


def _likely_causes(checks: list[dict[str, Any]], measurements: dict[str, Any]) -> list[str]:
    causes: list[str] = []
    failed = {check["name"]: check for check in checks if check["status"] == "fail"}
    if "VCC under-load voltage" in failed:
        causes.append("Power rail is outside expected range under load.")
    if "RF_IN to GND short check" in failed or "antenna center to GND short check" in failed:
        causes.append("RF input or antenna center conductor may be shorted to GND.")
    if "antenna center to RF_IN continuity" in failed:
        causes.append("RF path from antenna center to receiver input may be open.")
    if "antenna shield to GND continuity" in failed:
        causes.append("Antenna shield/ground path may be open.")
    if "active antenna bias" in failed:
        causes.append("Active antenna bias supply is missing or collapses under load.")
    if failed.get("ceramic patch faces sky") or failed.get("antenna clear of nearby blockers"):
        causes.append("Antenna placement/orientation is likely blocking or detuning the receiver.")
    if "known-good GPS L1 antenna test" in failed:
        causes.append("Receiver RF front-end or board RF path remains suspect even with a known-good GPS L1 antenna.")
    if "Scout TX to GPS RX command path" in failed:
        causes.append("Scout-to-GPS command path is broken; this blocks MON-HW/PUBX but not autonomous satellite acquisition.")
    return causes


def _next_required_measurements(checks: list[dict[str, Any]]) -> list[str]:
    return [check["next_step"] for check in checks if check["status"] == "unknown" and check.get("next_step")]


def _overall_status(counts: dict[str, int]) -> str:
    if counts.get("fail", 0):
        return "physical_fault_indicated"
    if counts.get("warn", 0):
        return "physical_risk_or_borderline_measurement"
    if counts.get("unknown", 0):
        return "physical_checks_incomplete"
    return "physical_checks_passed"


def _status_counts(checks: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"pass": 0, "warn": 0, "fail": 0, "unknown": 0}
    for check in checks:
        counts[check["status"]] = counts.get(check["status"], 0) + 1
    return counts


def _unknown(name: str, next_step: str) -> dict[str, Any]:
    return _check(name, "unknown", next_step=next_step)


def _check(
    name: str,
    status: str,
    *,
    value: float | None = None,
    unit: str | None = None,
    detail: str | None = None,
    next_step: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {"name": name, "status": status}
    if value is not None:
        result["value"] = value
    if unit is not None:
        result["unit"] = unit
    if detail:
        result["detail"] = detail
    if next_step:
        result["next_step"] = next_step
    return result


def _number(value: Any, *, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
