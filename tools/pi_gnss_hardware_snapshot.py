from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from tools.pi_gnss_ab_compare import (
        CaptureTarget,
        build_ab_payload,
        build_auto_capture_targets,
        capture_serial_targets,
        discover_serial_candidates,
    )
    from tools.pi_ublox5_gnss_debug import build_debug_payload, read_serial_debug_bytes
except ModuleNotFoundError:  # pragma: no cover - used by /tmp deployment on Scout.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from pi_gnss_ab_compare import (
        CaptureTarget,
        build_ab_payload,
        build_auto_capture_targets,
        capture_serial_targets,
        discover_serial_candidates,
    )
    from pi_ublox5_gnss_debug import build_debug_payload, read_serial_debug_bytes


@dataclass(frozen=True)
class GnssTarget:
    label: str
    device_port: str
    baud: int

    def as_capture_target(self) -> CaptureTarget:
        return CaptureTarget(label=self.label, device_port=self.device_port, baud=self.baud)


def parse_target_spec(spec: str) -> GnssTarget:
    if "=" not in spec or ":" not in spec:
        raise ValueError("target must use LABEL=/dev/ttyX:BAUD")
    label, rest = spec.split("=", 1)
    port, baud_text = rest.rsplit(":", 1)
    if not label or not port:
        raise ValueError("target label and device port are required")
    return GnssTarget(label=label, device_port=port, baud=int(baud_text))


def build_auto_gnss_targets(
    *,
    bauds: list[int],
    include_uart: bool,
    serial_candidates: list[dict[str, Any]] | None = None,
) -> tuple[list[GnssTarget], list[dict[str, Any]]]:
    discovered = serial_candidates if serial_candidates is not None else discover_serial_candidates()
    selected = [
        candidate
        for candidate in discovered
        if include_uart or not str(candidate.get("kind", "")).startswith("linux_uart")
    ]
    targets: list[GnssTarget] = []
    for baud in bauds:
        targets.extend(
            GnssTarget(label=target.label, device_port=target.device_port, baud=target.baud)
            for target in build_auto_capture_targets(baud=baud, serial_candidates=selected)
        )
    return targets, selected


def collect_hardware_snapshot(targets: list[GnssTarget]) -> dict[str, Any]:
    device_paths = _serial_device_paths(targets)
    return {
        "source": "pi_gnss_hardware_snapshot",
        "hardware_control_scope": "diagnostic_read_only_host_state",
        "device_paths": device_paths,
        "serial_devices": [_path_status(path) for path in device_paths],
        "serial0_target": _readlink("/dev/serial0"),
        "pinmux": {
            "gpio14": _run(["pinctrl", "get", "14"]),
            "gpio15": _run(["pinctrl", "get", "15"]),
        },
        "power": {
            "throttled": _run(["vcgencmd", "get_throttled"]),
            "temperature": _run(["vcgencmd", "measure_temp"]),
        },
        "usb": {
            "lsusb": _run(["lsusb"]),
        },
        "uart_config": {
            "cmdline": _read_text("/boot/firmware/cmdline.txt", max_chars=4000),
            "enable_uart_lines": _matching_lines("/boot/firmware/config.txt", "enable_uart"),
        },
        "serial_owners": {
            target.label: _run(["fuser", "-v", target.device_port])
            for target in targets
        },
    }


def collect_snapshot(
    *,
    targets: list[GnssTarget],
    ab_duration_seconds: float,
    probe_duration_seconds: float,
    poll_gap_seconds: float,
) -> dict[str, Any]:
    ab_payload = build_ab_payload(
        capture_serial_targets(
            [target.as_capture_target() for target in targets],
            duration_seconds=ab_duration_seconds,
        ),
        duration_seconds=ab_duration_seconds,
    )
    probes = {
        target.label: _collect_probe(
            target=target,
            probe_duration_seconds=probe_duration_seconds,
            poll_gap_seconds=poll_gap_seconds,
        )
        for target in targets
    }
    payload = {
        "source": "pi_gnss_hardware_snapshot",
        "hardware_kind": "gnss_antenna_rf_hardware_snapshot",
        "hardware_control_scope": "diagnostic_read_only_plus_non_destructive_polls",
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "targets": [target.__dict__ for target in targets],
        "durations": {
            "ab_duration_seconds": ab_duration_seconds,
            "probe_duration_seconds": probe_duration_seconds,
            "poll_gap_seconds": poll_gap_seconds,
        },
        "hardware_snapshot": collect_hardware_snapshot(targets),
        "ab_compare": ab_payload,
        "ublox_probes": probes,
    }
    payload["verdict"] = build_verdict(payload)
    return payload


def build_verdict(snapshot: dict[str, Any]) -> dict[str, Any]:
    captures = snapshot.get("ab_compare", {}).get("captures", {})
    probes = snapshot.get("ublox_probes", {})
    per_target = {}
    for label, capture in captures.items():
        probe = probes.get(label, {})
        probe_summary = probe.get("summary", {})
        capture_summary = capture.get("summary", {})
        per_target[label] = {
            "nmea_rx_path": _nmea_rx_state(capture),
            "command_path": probe_summary.get("command_path_state"),
            "fix_observed": capture_summary.get("fix_observed"),
            "gps_rf_signal_observed": capture_summary.get("gps_rf_signal_observed"),
            "any_rf_signal_observed": capture_summary.get("any_rf_signal_observed"),
            "max_cno_dbhz": capture_summary.get("max_cno_dbhz"),
            "gps_max_cno_dbhz": capture_summary.get("gps_max_cno_dbhz"),
            "antenna_text_status": capture.get("antenna_text_status") or probe_summary.get("antenna_text_status"),
            "antenna_supervisor_status": probe_summary.get("antenna_status_label"),
            "ubx_mon_hw_seen": probe_summary.get("ubx_mon_hw_seen"),
            "ubx_nav_svinfo_seen": probe_summary.get("ubx_nav_svinfo_seen"),
            "likely_state": capture_summary.get("likely_state"),
        }

    comparison = snapshot.get("ab_compare", {}).get("comparison", {})
    labels_with_gps_rf = set(comparison.get("labels_with_gps_rf_signal") or [])
    labels_without_gps_rf = {
        label
        for label, target_state in per_target.items()
        if target_state.get("gps_rf_signal_observed") is False
    }
    strong_gps_rf_fault_labels = sorted(labels_without_gps_rf) if labels_with_gps_rf else []

    unresolved = []
    for label, target_state in per_target.items():
        if target_state.get("command_path") == "host_rx_only_observed":
            unresolved.append(f"{label}: command path to receiver RX is not proven")
        if target_state.get("nmea_rx_path") != "valid_nmea_received":
            unresolved.append(f"{label}: host RX path is not proven")
    if not labels_with_gps_rf:
        unresolved.append("No comparator currently shows GPS GPGSV C/N0, so GPS-only RF hardware cannot be conclusively discriminated at this location")

    return {
        "per_target": per_target,
        "gps_ab_discriminates_hardware": bool(labels_with_gps_rf),
        "gps_rf_fault_strongly_supported_labels": strong_gps_rf_fault_labels,
        "environment_has_gps_l1_signal_for_comparison": bool(labels_with_gps_rf),
        "unresolved_items": unresolved,
        "next_required_evidence": _next_required_evidence(
            labels_with_gps_rf=bool(labels_with_gps_rf),
            per_target=per_target,
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect one GNSS hardware/RF diagnostic snapshot on Scout.")
    parser.add_argument(
        "--target",
        action="append",
        default=[],
        help="GNSS target in LABEL=/dev/ttyX:BAUD form. May be repeated.",
    )
    parser.add_argument(
        "--auto-targets",
        action="store_true",
        help="Discover USB/stable serial candidates and include them as GNSS hardware snapshot targets.",
    )
    parser.add_argument(
        "--auto-baud",
        type=int,
        action="append",
        default=[],
        help="Baud rate for --auto-targets. May be repeated. Defaults to 115200.",
    )
    parser.add_argument(
        "--include-uart",
        action="store_true",
        help="Include non-USB UART candidates such as /dev/serial0 in --auto-targets.",
    )
    parser.add_argument("--ab-duration-seconds", type=float, default=180.0)
    parser.add_argument("--probe-duration-seconds", type=float, default=30.0)
    parser.add_argument("--poll-gap-seconds", type=float, default=0.12)
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args(argv)

    targets = [parse_target_spec(spec) for spec in args.target]
    auto_serial_candidates = None
    if args.auto_targets:
        auto_targets, auto_serial_candidates = build_auto_gnss_targets(
            bauds=args.auto_baud or [115200],
            include_uart=args.include_uart,
        )
        targets.extend(auto_targets)
    if not targets:
        parser.error("at least one --target or --auto-targets is required")
    payload = collect_snapshot(
        targets=targets,
        ab_duration_seconds=args.ab_duration_seconds,
        probe_duration_seconds=args.probe_duration_seconds,
        poll_gap_seconds=args.poll_gap_seconds,
    )
    if auto_serial_candidates is not None:
        payload["auto_serial_candidates"] = auto_serial_candidates
        payload["auto_serial_candidate_count"] = len(auto_serial_candidates)
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(text + "\n")
    print(text)
    return 0


def _collect_probe(
    *,
    target: GnssTarget,
    probe_duration_seconds: float,
    poll_gap_seconds: float,
) -> dict[str, Any]:
    try:
        data = read_serial_debug_bytes(
            port=target.device_port,
            baud=target.baud,
            duration_seconds=probe_duration_seconds,
            poll_gap_seconds=poll_gap_seconds,
        )
        return build_debug_payload(data=data, device_port=target.device_port, baud=target.baud)
    except Exception as exc:  # pragma: no cover - exercised on real hardware.
        return {
            "source": "pi_ublox5_gnss_debug",
            "device_port": target.device_port,
            "baud": target.baud,
            "error": repr(exc),
            "summary": {"command_path_state": "probe_error", "likely_state": "probe_error"},
        }


def _nmea_rx_state(capture: dict[str, Any]) -> str:
    if capture.get("valid_checksum_lines", 0) > 0:
        return "valid_nmea_received"
    if capture.get("nmea_lines", 0) > 0:
        return "nmea_received_without_valid_checksum"
    return "no_nmea_received"


def _next_required_evidence(*, labels_with_gps_rf: bool, per_target: dict[str, Any]) -> list[str]:
    evidence = [
        "Measure target GNSS VCC to GND under load while NMEA is streaming",
        "Inspect antenna orientation and keep the ceramic patch clear of Pi, SSD, battery, display, and metal",
        "With power off, measure antenna/RF center conductor to GND for shorts",
    ]
    if not labels_with_gps_rf:
        evidence.insert(0, "Move both receivers to a location where USB comparator shows GPS GPGSV C/N0 > 0")
    if any(state.get("command_path") != "receiver_response_observed" for state in per_target.values()):
        evidence.append(
            "Prove host TX reaches GNSS receiver RX with a logic analyzer, oscilloscope, or temporary UART loopback"
        )
    return evidence


def _serial_device_paths(targets: list[GnssTarget]) -> list[str]:
    paths = ["/dev/serial0", "/dev/ttyAMA0"]
    paths.extend(target.device_port for target in targets)
    return sorted(set(paths))


def _path_status(path_text: str) -> dict[str, Any]:
    path = Path(path_text)
    return {
        "path": path_text,
        "exists": path.exists(),
        "is_symlink": path.is_symlink(),
        "target": _readlink(path_text),
    }


def _readlink(path: str) -> str | None:
    try:
        return str(Path(path).resolve())
    except OSError:
        return None


def _read_text(path: str, *, max_chars: int) -> str | None:
    try:
        return Path(path).read_text(errors="replace")[:max_chars]
    except OSError:
        return None


def _matching_lines(path: str, needle: str) -> list[str]:
    text = _read_text(path, max_chars=20000)
    if text is None:
        return []
    return [line for line in text.splitlines() if needle in line]


def _run(command: list[str]) -> dict[str, Any]:
    try:
        result = subprocess.run(command, text=True, capture_output=True, timeout=5, check=False)
        return {
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "command": command,
            "error": repr(exc),
        }


if __name__ == "__main__":
    raise SystemExit(main())
