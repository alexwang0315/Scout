from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def build_diagnosis(
    *,
    snapshot: dict[str, Any],
    physical: dict[str, Any] | None = None,
    loopback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    verdict = snapshot.get("verdict", {})
    host_checks = _host_checks(snapshot)
    target_checks = _target_checks(verdict, loopback=loopback)
    environment_check = _environment_check(verdict)
    physical_check = _physical_check(physical)
    conclusion = _conclusion(
        verdict=verdict,
        target_checks=target_checks,
        environment_check=environment_check,
        physical_check=physical_check,
    )
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": "pi_gnss_diagnosis_report",
        "hardware_kind": "gnss_antenna_rf_diagnosis_report",
        "hardware_control_scope": "diagnostic_report_only",
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "conclusion": conclusion,
        "host_checks": host_checks,
        "target_checks": target_checks,
        "environment_check": environment_check,
        "physical_check": physical_check,
        "integration_boundary": _integration_boundary(),
        "next_required_evidence": _next_required_evidence(verdict=verdict, physical_check=physical_check, loopback=loopback),
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Scout GNSS Hardware Diagnosis Report",
        "",
        f"- Conclusion: `{report['conclusion']['status']}`",
        f"- Confidence: `{report['conclusion']['confidence']}`",
        f"- Reason: {report['conclusion']['reason']}",
        "",
        "## Host Checks",
        "",
    ]
    for check in report["host_checks"]:
        lines.append(f"- `{check['status']}` {check['name']}: {check.get('detail', '')}")
    lines.extend(["", "## Target Checks", ""])
    for label, checks in report["target_checks"].items():
        lines.append(f"### {label}")
        for check in checks:
            lines.append(f"- `{check['status']}` {check['name']}: {check.get('detail', '')}")
        lines.append("")
    lines.extend(["## Environment", ""])
    lines.append(
        f"- `{report['environment_check']['status']}` {report['environment_check']['name']}: "
        f"{report['environment_check'].get('detail', '')}"
    )
    lines.extend(["", "## Physical Checks", ""])
    lines.append(
        f"- `{report['physical_check']['status']}` {report['physical_check']['name']}: "
        f"{report['physical_check'].get('detail', '')}"
    )
    if report["physical_check"].get("likely_causes"):
        lines.append("")
        lines.append("Likely physical causes:")
        for cause in report["physical_check"]["likely_causes"]:
            lines.append(f"- {cause}")
    lines.extend(["", "## Integration Boundary", ""])
    for item in report["integration_boundary"]:
        lines.append(f"- {item}")
    lines.extend(["", "## Next Required Evidence", ""])
    for item in report["next_required_evidence"]:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a conservative GNSS antenna/RF diagnosis report from collected evidence.")
    parser.add_argument("--snapshot-json", type=Path, required=True)
    parser.add_argument("--physical-json", type=Path)
    parser.add_argument("--loopback-json", type=Path)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-md", type=Path)
    args = parser.parse_args(argv)

    snapshot = json.loads(args.snapshot_json.read_text())
    physical = json.loads(args.physical_json.read_text()) if args.physical_json else None
    loopback = json.loads(args.loopback_json.read_text()) if args.loopback_json else None
    report = build_diagnosis(snapshot=snapshot, physical=physical, loopback=loopback)

    if args.output_json:
        _write_text(args.output_json, json.dumps(report, indent=2, sort_keys=True) + "\n")
    markdown = render_markdown(report)
    if args.output_md:
        _write_text(args.output_md, markdown)
    print(markdown)
    return 0


def _host_checks(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    hardware = snapshot.get("hardware_snapshot", {})
    power = hardware.get("power", {})
    pinmux = hardware.get("pinmux", {})
    throttled = (power.get("throttled") or {}).get("stdout", "")
    gpio14 = (pinmux.get("gpio14") or {}).get("stdout", "")
    gpio15 = (pinmux.get("gpio15") or {}).get("stdout", "")
    return [
        _check(
            "Pi power throttle state",
            "pass" if "throttled=0x0" in throttled else "warn",
            throttled or "missing throttled output",
        ),
        _check(
            "GPIO14 TXD0 pinmux",
            "pass" if "TXD0" in gpio14 else "warn",
            gpio14 or "missing GPIO14 pinmux output",
        ),
        _check(
            "GPIO15 RXD0 pinmux",
            "pass" if "RXD0" in gpio15 else "warn",
            gpio15 or "missing GPIO15 pinmux output",
        ),
    ]


def _target_checks(verdict: dict[str, Any], *, loopback: dict[str, Any] | None) -> dict[str, list[dict[str, str]]]:
    per_target = verdict.get("per_target", {})
    checks: dict[str, list[dict[str, str]]] = {}
    loopback_passed = bool((loopback or {}).get("loopback_passed"))
    for label, state in per_target.items():
        target_checks = [
            _check(
                "host RX path",
                "pass" if state.get("nmea_rx_path") == "valid_nmea_received" else "fail",
                str(state.get("nmea_rx_path")),
            ),
            _check(
                "GPS RF signal",
                "pass" if state.get("gps_rf_signal_observed") else "warn",
                f"gps_max_cno_dbhz={state.get('gps_max_cno_dbhz')}",
            ),
            _check(
                "any RF signal",
                "pass" if state.get("any_rf_signal_observed") else "warn",
                f"max_cno_dbhz={state.get('max_cno_dbhz')}",
            ),
        ]
        command_path = state.get("command_path")
        if command_path == "receiver_response_observed":
            target_checks.append(_check("receiver command response", "pass", str(command_path)))
        elif loopback_passed:
            target_checks.append(
                _check(
                    "receiver command response",
                    "warn",
                    "Scout UART loopback passed, but this GNSS receiver still has not replied; inspect receiver RX wiring, level, and input protocol.",
                )
            )
        else:
            target_checks.append(_check("receiver command response", "unknown", str(command_path)))
        antenna_text = state.get("antenna_text_status")
        if antenna_text:
            target_checks.append(_check("antenna TXT status", "pass" if antenna_text == "OK" else "fail", str(antenna_text)))
        else:
            target_checks.append(_check("antenna TXT status", "unknown", "no antenna TXT status"))
        checks[label] = target_checks
    return checks


def _environment_check(verdict: dict[str, Any]) -> dict[str, str]:
    if verdict.get("environment_has_gps_l1_signal_for_comparison"):
        labels = ", ".join(verdict.get("gps_rf_fault_strongly_supported_labels") or [])
        return _check("GPS L1 comparator environment", "pass", f"Comparator has GPS C/N0; suspect labels: {labels or 'none'}")
    return _check(
        "GPS L1 comparator environment",
        "unknown",
        "No comparator currently shows GPS GPGSV C/N0, so the target GNSS RF path cannot be conclusively discriminated at this location.",
    )


def _physical_check(physical: dict[str, Any] | None) -> dict[str, Any]:
    if physical is None:
        return {
            "name": "physical measurements",
            "status": "unknown",
            "detail": "No physical checklist result provided.",
            "likely_causes": [],
        }
    status = physical.get("overall_status")
    if status == "physical_fault_indicated":
        check_status = "fail"
    elif status == "physical_checks_passed":
        check_status = "pass"
    elif status == "physical_risk_or_borderline_measurement":
        check_status = "warn"
    else:
        check_status = "unknown"
    return {
        "name": "physical measurements",
        "status": check_status,
        "detail": str(status),
        "likely_causes": physical.get("likely_causes") or [],
        "next_required_measurements": physical.get("next_required_measurements") or [],
    }


def _conclusion(
    *,
    verdict: dict[str, Any],
    target_checks: dict[str, list[dict[str, str]]],
    environment_check: dict[str, str],
    physical_check: dict[str, Any],
) -> dict[str, str]:
    strong_labels = verdict.get("gps_rf_fault_strongly_supported_labels") or []
    if physical_check["status"] == "fail":
        return {
            "status": "physical_fault_indicated",
            "confidence": "high",
            "reason": "Physical measurements contain one or more failing checks.",
        }
    if strong_labels:
        return {
            "status": "gnss_rf_path_fault_strongly_supported",
            "confidence": "high",
            "reason": "A GPS L1 comparator shows C/N0 while target GNSS still has no GPS C/N0.",
        }
    no_gps_cno_labels = _labels_with_valid_rx_but_no_gps_cno(target_checks)
    if no_gps_cno_labels and environment_check["status"] == "unknown":
        return {
            "status": "not_yet_conclusive_gps_l1_environment_missing",
            "confidence": "medium",
            "reason": f"{', '.join(no_gps_cno_labels)} streams valid NMEA but no GPS C/N0; current comparator also lacks GPS C/N0.",
        }
    return {
        "status": "insufficient_evidence",
        "confidence": "low",
        "reason": "Required comparator or physical evidence is missing.",
    }


def _labels_with_valid_rx_but_no_gps_cno(target_checks: dict[str, list[dict[str, str]]]) -> list[str]:
    labels: list[str] = []
    for label, checks in target_checks.items():
        rx_pass = any(check["name"] == "host RX path" and check["status"] == "pass" for check in checks)
        gps_warn = any(check["name"] == "GPS RF signal" and check["status"] == "warn" for check in checks)
        if rx_pass and gps_warn:
            labels.append(label)
    return labels


def _next_required_evidence(
    *,
    verdict: dict[str, Any],
    physical_check: dict[str, Any],
    loopback: dict[str, Any] | None,
) -> list[str]:
    evidence = list(verdict.get("next_required_evidence") or [])
    evidence.extend(physical_check.get("next_required_measurements") or [])
    per_target = verdict.get("per_target") if isinstance(verdict.get("per_target"), dict) else {}
    command_path_unproven = any(
        state.get("command_path") != "receiver_response_observed"
        for state in per_target.values()
        if isinstance(state, dict)
    )
    if loopback is None and command_path_unproven:
        evidence.append("Run Scout UART loopback after disconnecting GNSS and shorting GPIO14/TXD0 to GPIO15/RXD0.")
    # Preserve order while dropping duplicates.
    deduped = []
    for item in evidence:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _integration_boundary() -> list[str]:
    return [
        "GPS-to-IMU D1 is a vendor fusion / integrated-navigation review path, not a GNSS RF/acquisition debug path.",
        "If direct GPS capture still reports GPGSV=0, C/N0 all zero, and GGA fix quality 0, routing NMEA into IMU D1 cannot create satellite signal.",
        "RF/antenna debug must keep the GPS receiver directly connected to Scout host serial/USB until GPS GPGSV C/N0 or valid fix is proven.",
    ]


def _check(name: str, status: str, detail: str) -> dict[str, str]:
    return {"name": name, "status": status, "detail": detail}


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


if __name__ == "__main__":
    raise SystemExit(main())
