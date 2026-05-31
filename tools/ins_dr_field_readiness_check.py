from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from safety_runtime_session import SafetyRuntimeSession  # noqa: E402
from tools.pi_gnss_nmea_smoke import parse_raw_nmea, read_serial_nmea, summarize_gnss_fix, summarize_gnss_signal  # noqa: E402


FIELD_RUN_ARTIFACT_NAMES = {
    "anchor-gnss.jsonl",
    "dr-delta.jsonl",
    "reanchor-gnss.jsonl",
    "runtime-updates.jsonl",
    "field-report.json",
    "proof-manifest.json",
    "verification-report.json",
}

GNSS_SERIAL_AUTO_VALUE = "auto"

DEFAULT_GNSS_SERIAL_GLOB_PATTERNS: tuple[tuple[str, str, int], ...] = (
    ("stable_by_id", "/dev/serial/by-id/*", 0),
    ("linux_usb_serial", "/dev/ttyUSB*", 10),
    ("linux_usb_acm", "/dev/ttyACM*", 11),
    ("linux_uart_alias", "/dev/serial0", 30),
    ("linux_uart", "/dev/ttyAMA*", 31),
    ("macos_usb_callout", "/dev/cu.usb*", 40),
    ("macos_silabs_callout", "/dev/cu.SLAB*", 41),
    ("macos_wch_callout", "/dev/cu.wch*", 42),
    ("macos_usb_tty", "/dev/tty.usb*", 50),
    ("macos_silabs_tty", "/dev/tty.SLAB*", 51),
    ("macos_wch_tty", "/dev/tty.wch*", 52),
)


def build_field_readiness_report(
    *,
    mission_graph_path: Path,
    gnss_port: Path,
    output_dir: Path,
    allow_overwrite: bool = False,
    gnss_evidence_jsonl_paths: Sequence[Path] | None = None,
    require_valid_gnss_fix: bool = False,
    min_gnss_cno_dbhz: float = 1.0,
    capture_gnss_duration_seconds: float | None = None,
    capture_gnss_evidence_jsonl_path: Path | None = None,
    auto_select_gnss_by_fix_duration_seconds: float | None = None,
    auto_select_gnss_evidence_dir_path: Path | None = None,
    gnss_hardware_snapshot_json_path: Path | None = None,
    gnss_baud: int = 115200,
    include_uart_serial_candidates: bool = False,
    serial_glob_patterns: Sequence[tuple[str, str, int]] | None = None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    requested_gnss_port = str(gnss_port)
    resolved_gnss_port, serial_evidence = resolve_requested_gnss_port(
        gnss_port,
        include_uart_serial_candidates=include_uart_serial_candidates,
        serial_glob_patterns=serial_glob_patterns,
    )
    gnss_auto_selection_summary: dict[str, Any] | None = None
    gnss_evidence_paths = list(gnss_evidence_jsonl_paths or [])
    if auto_select_gnss_by_fix_duration_seconds is not None:
        selection_dir = auto_select_gnss_evidence_dir_path or output_dir / "gnss-auto-selection"
        gnss_auto_selection_summary = _auto_select_gnss_port_by_fix(
            requested_gnss_port=requested_gnss_port,
            resolved_gnss_port=resolved_gnss_port,
            serial_evidence=serial_evidence,
            baud=gnss_baud,
            duration_seconds=auto_select_gnss_by_fix_duration_seconds,
            output_dir=selection_dir,
        )
        gnss_evidence_paths.extend(Path(path) for path in gnss_auto_selection_summary.get("evidence_jsonl_paths", []))
        selected_path = gnss_auto_selection_summary.get("selected_gnss_port")
        if selected_path:
            resolved_gnss_port = Path(selected_path)
            serial_evidence = dict(serial_evidence)
            serial_evidence.update(
                {
                    "resolved_gnss_port": selected_path,
                    "auto_detection_status": "selected_valid_fix_candidate",
                    "auto_selection_status": gnss_auto_selection_summary.get("selection_status"),
                    "auto_selected_candidate_label": gnss_auto_selection_summary.get("selected_candidate_label"),
                }
            )
    session: SafetyRuntimeSession | None = None
    try:
        session = SafetyRuntimeSession(mission_graph_path)
        checks.append(
            _check(
                "mission_graph_loads",
                True,
                "Mission graph and route source must load before a field run.",
                {
                    "mission_graph": str(mission_graph_path),
                    "route_source": str(session.planned_route_path),
                    "route_point_count": len(session.planned_route.points),
                },
            )
        )
    except Exception as exc:
        checks.append(
            _check(
                "mission_graph_loads",
                False,
                "Mission graph and route source must load before a field run.",
                {"mission_graph": str(mission_graph_path), "error": f"{type(exc).__name__}: {exc}"},
            )
        )

    checks.append(
        _check(
            "route_has_multiple_points",
            session is not None and len(session.planned_route.points) >= 2,
            "Field proof route must contain at least two GPX points.",
            {
                "route_source": str(session.planned_route_path) if session is not None else None,
                "route_point_count": len(session.planned_route.points) if session is not None else None,
            },
        )
    )
    checks.append(
        _check(
            "map_corridor_available",
            session is not None and session.offline_map_context is not None and bool(session.offline_map_context.corridors),
            "Completion gate requires an offline map corridor for route-corridor evidence.",
            {
                "map_context": str(session.offline_map_context.source)
                if session is not None and session.offline_map_context is not None
                else None,
                "corridor_count": len(session.offline_map_context.corridors)
                if session is not None and session.offline_map_context is not None
                else 0,
            },
        )
    )
    checks.append(
        _check(
            "gnss_serial_port_exists",
            resolved_gnss_port.exists() and serial_evidence["auto_detection_status"] != "ambiguous_serial_candidates",
            "GNSS serial device path must exist before running a live field proof.",
            serial_evidence,
        )
    )
    if auto_select_gnss_by_fix_duration_seconds is not None:
        checks.append(
            _check(
                "gnss_auto_selection_has_valid_fix_candidate",
                gnss_auto_selection_summary is not None
                and gnss_auto_selection_summary.get("selection_status") == "selected_valid_fix_candidate",
                "Auto GNSS selection must find a serial candidate with a valid fix before field proof can use it.",
                gnss_auto_selection_summary,
            )
        )
    gnss_capture_summary: dict[str, Any] | None = None
    if capture_gnss_duration_seconds is not None:
        capture_path = capture_gnss_evidence_jsonl_path or output_dir / "gnss-readiness-capture.jsonl"
        gnss_capture_summary = _capture_live_gnss_evidence(
            port=resolved_gnss_port,
            baud=gnss_baud,
            duration_seconds=capture_gnss_duration_seconds,
            output_jsonl=capture_path,
            serial_ready=resolved_gnss_port.exists()
            and serial_evidence["auto_detection_status"] != "ambiguous_serial_candidates",
        )
        if gnss_capture_summary["capture_status"] == "captured":
            gnss_evidence_paths.append(capture_path)
        checks.append(
            _check(
                "gnss_live_evidence_capture_completed",
                gnss_capture_summary["capture_status"] == "captured",
                "Optional live GNSS evidence capture must complete before it can be used for readiness.",
                gnss_capture_summary,
            )
        )
    gnss_evidence_summary = _gnss_evidence_summary(gnss_evidence_paths)
    if gnss_evidence_jsonl_paths or require_valid_gnss_fix:
        checks.append(
            _check(
                "gnss_evidence_has_rf_signal_or_fix",
                gnss_evidence_summary["valid_fix_count"] > 0
                or _summary_cno_at_least(gnss_evidence_summary, min_gnss_cno_dbhz),
                "GNSS evidence should show either a valid fix or at least one non-zero GSV C/N0 before field proof.",
                gnss_evidence_summary,
            )
        )
    if require_valid_gnss_fix:
        checks.append(
            _check(
                "gnss_evidence_has_valid_fix",
                gnss_evidence_summary["valid_fix_count"] > 0,
                "Live field proof requires at least one valid GNSS fix for the anchor.",
                gnss_evidence_summary,
            )
        )
    gnss_readiness_diagnosis = _gnss_readiness_diagnosis(
        gnss_evidence_summary,
        require_valid_gnss_fix=require_valid_gnss_fix,
        min_gnss_cno_dbhz=min_gnss_cno_dbhz,
    )
    gnss_hardware_snapshot_summary = _gnss_hardware_snapshot_summary(gnss_hardware_snapshot_json_path)
    if gnss_hardware_snapshot_json_path is not None:
        checks.append(
            _check(
                "gnss_hardware_snapshot_loaded",
                bool(
                    gnss_hardware_snapshot_summary
                    and gnss_hardware_snapshot_summary.get("loaded") is True
                    and gnss_hardware_snapshot_summary.get("verdict_present") is True
                ),
                "Optional GNSS hardware snapshot must be readable and include a verdict when provided.",
                gnss_hardware_snapshot_summary,
            )
        )

    output_dir_ready, output_dir_error = _ensure_output_dir(output_dir)
    checks.append(
        _check(
            "output_dir_writable",
            output_dir_ready,
            "Manual field run output directory must be creatable and writable.",
            {"output_dir": str(output_dir), "error": output_dir_error},
        )
    )
    existing_artifacts = _existing_field_run_artifacts(output_dir)
    checks.append(
        _check(
            "output_dir_not_reusing_existing_proof_artifacts",
            allow_overwrite or not existing_artifacts,
            "Existing proof artifacts should not be overwritten unless the operator explicitly allows it.",
            {"output_dir": str(output_dir), "existing_artifacts": existing_artifacts, "allow_overwrite": allow_overwrite},
        )
    )

    ready = all(check["passed"] for check in checks)
    return {
        "source": "ins_dr_field_readiness_check",
        "artifact_kind": "ins_dr_field_readiness_report",
        "field_run_readiness_status": "ready" if ready else "not_ready",
        "ready": ready,
        "ready_for_live_field_proof": ready,
        "mission_graph": str(mission_graph_path),
        "requested_gnss_port": requested_gnss_port,
        "gnss_port": str(resolved_gnss_port),
        "selected_gnss_port": str(resolved_gnss_port) if resolved_gnss_port.exists() else None,
        "serial_candidate_count": serial_evidence["candidate_count"],
        "serial_candidates": serial_evidence["candidates"],
        "gnss_auto_selection_summary": gnss_auto_selection_summary,
        "gnss_live_capture_summary": gnss_capture_summary,
        "gnss_evidence_summary": gnss_evidence_summary,
        "gnss_readiness_diagnosis": gnss_readiness_diagnosis,
        "gnss_hardware_snapshot_summary": gnss_hardware_snapshot_summary,
        "output_dir": str(output_dir),
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_field_readiness_check_only",
        "checks": checks,
    }


def resolve_requested_gnss_port(
    gnss_port: Path,
    *,
    include_uart_serial_candidates: bool = False,
    serial_glob_patterns: Sequence[tuple[str, str, int]] | None = None,
) -> tuple[Path, dict[str, Any]]:
    requested = str(gnss_port)
    if requested != GNSS_SERIAL_AUTO_VALUE:
        return gnss_port, {
            "requested_gnss_port": requested,
            "resolved_gnss_port": str(gnss_port),
            "auto_detection_status": "explicit_port",
            "candidate_count": 0,
            "candidates": [],
        }

    candidates = _filter_gnss_serial_candidates(
        discover_gnss_serial_candidates(serial_glob_patterns=serial_glob_patterns),
        include_uart_serial_candidates=include_uart_serial_candidates,
    )
    if len(candidates) == 1:
        selected = Path(candidates[0]["path"])
        return selected, {
            "requested_gnss_port": requested,
            "resolved_gnss_port": str(selected),
            "auto_detection_status": "selected_unique_candidate",
            "candidate_count": 1,
            "candidates": candidates,
        }
    if not candidates:
        return gnss_port, {
            "requested_gnss_port": requested,
            "resolved_gnss_port": None,
            "auto_detection_status": "no_serial_candidates",
            "candidate_count": 0,
            "candidates": [],
        }
    return gnss_port, {
        "requested_gnss_port": requested,
        "resolved_gnss_port": None,
        "auto_detection_status": "ambiguous_serial_candidates",
        "candidate_count": len(candidates),
        "candidates": candidates,
    }


def discover_gnss_serial_candidates(
    *,
    serial_glob_patterns: Sequence[tuple[str, str, int]] | None = None,
) -> list[dict[str, Any]]:
    patterns = serial_glob_patterns or DEFAULT_GNSS_SERIAL_GLOB_PATTERNS
    candidates: list[dict[str, Any]] = []
    seen_real_paths: set[str] = set()
    for kind, pattern, priority in patterns:
        for raw_path in sorted(glob.glob(pattern)):
            path = Path(raw_path)
            if not path.exists():
                continue
            real_path = str(path.resolve())
            if real_path in seen_real_paths:
                continue
            seen_real_paths.add(real_path)
            candidates.append(
                {
                    "path": str(path),
                    "real_path": real_path,
                    "kind": kind,
                    "priority": priority,
                    "stable_path_preferred": kind == "stable_by_id",
                }
            )
    return sorted(candidates, key=lambda candidate: (candidate["priority"], candidate["path"]))


def _filter_gnss_serial_candidates(
    candidates: list[dict[str, Any]],
    *,
    include_uart_serial_candidates: bool,
) -> list[dict[str, Any]]:
    if include_uart_serial_candidates:
        return candidates
    return [
        candidate
        for candidate in candidates
        if not str(candidate.get("kind", "")).startswith("linux_uart")
    ]


def _ensure_output_dir(output_dir: Path) -> tuple[bool, str | None]:
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        probe = output_dir / ".ins_dr_readiness_write_probe"
        probe.write_text("ok\n", encoding="utf-8")
        probe.unlink()
        return True, None
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _existing_field_run_artifacts(output_dir: Path) -> list[str]:
    if not output_dir.is_dir():
        return []
    return sorted(path.name for path in output_dir.iterdir() if path.name in FIELD_RUN_ARTIFACT_NAMES)


def _gnss_evidence_summary(paths: Sequence[Path]) -> dict[str, Any]:
    payloads = _load_jsonl_payloads(paths)
    valid_fix_payloads = [
        payload
        for payload in payloads
        if isinstance(payload.get("fix_quality"), dict)
        and payload["fix_quality"].get("valid") is True
        and isinstance(payload.get("position"), dict)
        and payload["position"].get("lat") is not None
        and payload["position"].get("lon") is not None
    ]
    checksum_failures = [
        payload
        for payload in payloads
        if payload.get("checksum_valid") is False
    ]
    return {
        "input_refs": [str(path) for path in paths],
        "payload_count": len(payloads),
        "valid_fix_count": len(valid_fix_payloads),
        "checksum_failure_count": len(checksum_failures),
        "fix": summarize_gnss_fix(payloads),
        "signal": summarize_gnss_signal(payloads),
    }


def _capture_live_gnss_evidence(
    *,
    port: Path,
    baud: int,
    duration_seconds: float,
    output_jsonl: Path,
    serial_ready: bool,
) -> dict[str, Any]:
    if duration_seconds <= 0:
        raise ValueError("capture_gnss_duration_seconds must be positive")
    if not serial_ready:
        return {
            "capture_status": "skipped_serial_not_ready",
            "output_jsonl": str(output_jsonl),
            "port": str(port),
            "baud": baud,
            "duration_seconds": duration_seconds,
            "payload_count": 0,
            "fix": summarize_gnss_fix([]),
            "signal": summarize_gnss_signal([]),
        }
    try:
        lines = read_serial_nmea(port=str(port), baud=baud, duration_seconds=duration_seconds)
        payloads = parse_raw_nmea(
            "\n".join(lines),
            device_port=str(port),
            baud=baud,
            capture_mode="serial_device",
        )
        output_jsonl.parent.mkdir(parents=True, exist_ok=True)
        output_jsonl.write_text(
            "".join(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n" for payload in payloads),
            encoding="utf-8",
        )
        return {
            "capture_status": "captured",
            "output_jsonl": str(output_jsonl),
            "port": str(port),
            "baud": baud,
            "duration_seconds": duration_seconds,
            "raw_line_count": len(lines),
            "payload_count": len(payloads),
            "fix": summarize_gnss_fix(payloads),
            "signal": summarize_gnss_signal(payloads),
        }
    except Exception as exc:
        return {
            "capture_status": "error",
            "output_jsonl": str(output_jsonl),
            "port": str(port),
            "baud": baud,
            "duration_seconds": duration_seconds,
            "payload_count": 0,
            "error": f"{type(exc).__name__}: {exc}",
            "fix": summarize_gnss_fix([]),
            "signal": summarize_gnss_signal([]),
        }


def _auto_select_gnss_port_by_fix(
    *,
    requested_gnss_port: str,
    resolved_gnss_port: Path,
    serial_evidence: dict[str, Any],
    baud: int,
    duration_seconds: float,
    output_dir: Path,
) -> dict[str, Any]:
    if duration_seconds <= 0:
        raise ValueError("auto_select_gnss_by_fix_duration_seconds must be positive")
    if requested_gnss_port == GNSS_SERIAL_AUTO_VALUE:
        candidates = list(serial_evidence.get("candidates") or [])
    elif resolved_gnss_port.exists():
        candidates = [
            {
                "path": str(resolved_gnss_port),
                "real_path": str(resolved_gnss_port.resolve()),
                "kind": "explicit_port",
                "priority": 0,
                "stable_path_preferred": False,
            }
        ]
    else:
        candidates = []

    capture_summaries: list[dict[str, Any]] = []
    best: dict[str, Any] | None = None
    for index, candidate in enumerate(candidates):
        candidate_path = Path(candidate["path"])
        output_jsonl = _auto_selection_capture_path(
            output_dir=output_dir,
            index=index,
            candidate=candidate,
            baud=baud,
        )
        capture = _capture_live_gnss_evidence(
            port=candidate_path,
            baud=baud,
            duration_seconds=duration_seconds,
            output_jsonl=output_jsonl,
            serial_ready=candidate_path.exists(),
        )
        summary = {
            "candidate": candidate,
            "candidate_label": _safe_auto_selection_label(index=index, candidate=candidate, baud=baud),
            "capture": capture,
            "score": _auto_selection_score(capture),
        }
        capture_summaries.append(summary)
        if _capture_has_valid_fix(capture) and (best is None or summary["score"] > best["score"]):
            best = summary

    evidence_paths = [
        summary["capture"]["output_jsonl"]
        for summary in capture_summaries
        if summary["capture"].get("capture_status") == "captured"
    ]
    if best is not None:
        return {
            "selection_status": "selected_valid_fix_candidate",
            "requested_gnss_port": requested_gnss_port,
            "selected_gnss_port": best["candidate"]["path"],
            "selected_candidate_label": best["candidate_label"],
            "selected_candidate": best["candidate"],
            "baud": baud,
            "duration_seconds": duration_seconds,
            "candidate_count": len(candidates),
            "evidence_jsonl_paths": evidence_paths,
            "candidate_summaries": capture_summaries,
        }
    return {
        "selection_status": "no_valid_fix_candidate",
        "requested_gnss_port": requested_gnss_port,
        "selected_gnss_port": None,
        "selected_candidate_label": None,
        "selected_candidate": None,
        "baud": baud,
        "duration_seconds": duration_seconds,
        "candidate_count": len(candidates),
        "evidence_jsonl_paths": evidence_paths,
        "candidate_summaries": capture_summaries,
    }


def _capture_has_valid_fix(capture: dict[str, Any]) -> bool:
    fix = capture.get("fix") if isinstance(capture.get("fix"), dict) else {}
    return int(fix.get("valid_fix_count") or 0) > 0


def _auto_selection_score(capture: dict[str, Any]) -> tuple[int, float, float, int]:
    fix = capture.get("fix") if isinstance(capture.get("fix"), dict) else {}
    signal = capture.get("signal") if isinstance(capture.get("signal"), dict) else {}
    return (
        int(fix.get("valid_fix_count") or 0),
        float(signal.get("gps_max_cno_dbhz") or 0),
        float(signal.get("max_cno_dbhz") or 0),
        int(capture.get("payload_count") or 0),
    )


def _auto_selection_capture_path(*, output_dir: Path, index: int, candidate: dict[str, Any], baud: int) -> Path:
    return output_dir / f"{_safe_auto_selection_label(index=index, candidate=candidate, baud=baud)}.jsonl"


def _safe_auto_selection_label(*, index: int, candidate: dict[str, Any], baud: int) -> str:
    raw = f"candidate_{index}_{candidate.get('kind', 'serial')}_{Path(str(candidate.get('path', 'unknown'))).name}_{baud}"
    label = re.sub(r"[^A-Za-z0-9_]+", "_", raw).strip("_")
    return label[:96] or f"candidate_{index}"


def _gnss_readiness_diagnosis(
    summary: dict[str, Any],
    *,
    require_valid_gnss_fix: bool,
    min_gnss_cno_dbhz: float,
) -> dict[str, Any]:
    payload_count = int(summary.get("payload_count") or 0)
    valid_fix_count = int(summary.get("valid_fix_count") or 0)
    signal = summary.get("signal") if isinstance(summary.get("signal"), dict) else {}
    max_cno = _numeric_or_none(signal.get("max_cno_dbhz"))
    gps_max_cno = _numeric_or_none(signal.get("gps_max_cno_dbhz"))
    nonzero_cno_count = int(signal.get("nonzero_cno_count") or 0)
    gps_nonzero_cno_count = int(signal.get("gps_nonzero_cno_count") or 0)
    gsv_sentence_count = int(signal.get("gsv_sentence_count") or 0)
    rf_signal_observed = (
        max_cno is not None
        and max_cno >= min_gnss_cno_dbhz
    ) or nonzero_cno_count > 0
    gps_rf_signal_observed = (
        gps_max_cno is not None
        and gps_max_cno >= min_gnss_cno_dbhz
    ) or gps_nonzero_cno_count > 0

    if valid_fix_count > 0:
        state = "valid_fix_ready"
        can_start = True
        action = "GNSS evidence has a valid fix; field proof may proceed if all other readiness checks pass."
    elif rf_signal_observed and not gps_rf_signal_observed:
        state = "non_gps_rf_signal_without_valid_fix"
        can_start = False
        action = "GNSS sees non-GPS C/N0 but no GPS C/N0 or valid fix; keep collecting under open sky and compare against a USB GPS L1 receiver before field proof."
    elif payload_count == 0:
        state = "no_nmea_payloads"
        can_start = False
        action = "Check GNSS serial path, baud rate, GPS power, and cabling before field proof."
    elif rf_signal_observed:
        state = "rf_signal_without_valid_fix"
        can_start = not require_valid_gnss_fix
        action = "Keep antenna under open sky or improve placement until GGA/RMC reports a valid fix; do not start a required-fix field proof yet."
    elif gsv_sentence_count > 0:
        state = "no_rf_signal_observed"
        can_start = False
        action = "NMEA is alive but C/N0 is absent; inspect antenna, RF path, bias, shielding, and placement."
    else:
        state = "nmea_without_gsv_or_fix"
        can_start = False
        action = "NMEA is alive but lacks fix and GSV signal evidence; check receiver message configuration and continue diagnostics."

    return {
        "state": state,
        "can_start_field_proof_from_gnss": can_start,
        "require_valid_gnss_fix": require_valid_gnss_fix,
        "valid_fix_count": valid_fix_count,
        "payload_count": payload_count,
        "rf_signal_observed": rf_signal_observed,
        "gps_rf_signal_observed": gps_rf_signal_observed,
        "max_cno_dbhz": max_cno,
        "gps_max_cno_dbhz": gps_max_cno,
        "min_gnss_cno_dbhz": min_gnss_cno_dbhz,
        "next_operator_action": action,
    }


def _gnss_hardware_snapshot_summary(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None

    summary: dict[str, Any] = {
        "input_ref": str(path),
        "loaded": False,
        "verdict_present": False,
    }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        summary["error"] = f"{type(exc).__name__}: {exc}"
        return summary
    if not isinstance(payload, dict):
        summary["error"] = "snapshot JSON must be an object"
        return summary

    verdict = payload.get("verdict")
    summary.update(
        {
            "loaded": True,
            "source": payload.get("source"),
            "hardware_kind": payload.get("hardware_kind"),
            "hardware_control_scope": payload.get("hardware_control_scope"),
            "targets": payload.get("targets") if isinstance(payload.get("targets"), list) else [],
            "verdict_present": isinstance(verdict, dict),
            "verdict": _compact_gnss_hardware_verdict(verdict if isinstance(verdict, dict) else {}),
        }
    )
    return summary


def _compact_gnss_hardware_verdict(verdict: dict[str, Any]) -> dict[str, Any]:
    return {
        "per_target": verdict.get("per_target") if isinstance(verdict.get("per_target"), dict) else {},
        "gps_ab_discriminates_hardware": bool(verdict.get("gps_ab_discriminates_hardware")),
        "gps_rf_fault_strongly_supported_labels": verdict.get("gps_rf_fault_strongly_supported_labels")
        if isinstance(verdict.get("gps_rf_fault_strongly_supported_labels"), list)
        else [],
        "environment_has_gps_l1_signal_for_comparison": bool(
            verdict.get("environment_has_gps_l1_signal_for_comparison")
        ),
        "unresolved_items": verdict.get("unresolved_items") if isinstance(verdict.get("unresolved_items"), list) else [],
        "next_required_evidence": verdict.get("next_required_evidence")
        if isinstance(verdict.get("next_required_evidence"), list)
        else [],
    }


def _numeric_or_none(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _load_jsonl_payloads(paths: Sequence[Path]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                payload = json.loads(stripped)
                if not isinstance(payload, dict):
                    raise ValueError(f"{path}:{line_number} is not a JSON object")
                payloads.append(payload)
    return payloads


def _summary_cno_at_least(summary: dict[str, Any], threshold: float) -> bool:
    signal = summary.get("signal") if isinstance(summary.get("signal"), dict) else {}
    for key in ("gps_max_cno_dbhz", "max_cno_dbhz"):
        value = signal.get(key)
        if isinstance(value, (int, float)) and value >= threshold:
            return True
    return False


def _check(name: str, passed: bool, reason: str, evidence: Any) -> dict[str, Any]:
    return {
        "name": name,
        "passed": bool(passed),
        "reason": reason,
        "evidence": evidence,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check whether Scout INS/DR manual field proof inputs are ready.")
    parser.add_argument("--mission-graph", type=Path, required=True)
    parser.add_argument("--gnss-port", type=Path, required=True, help="GNSS serial path, or 'auto' for preflight discovery.")
    parser.add_argument("--gnss-evidence-jsonl", type=Path, action="append", default=[])
    parser.add_argument("--require-valid-gnss-fix", action="store_true")
    parser.add_argument("--min-gnss-cno-dbhz", type=float, default=1.0)
    parser.add_argument(
        "--capture-gnss-duration-seconds",
        type=float,
        help="Optionally capture live GNSS NMEA evidence during readiness and include it in the GNSS checks.",
    )
    parser.add_argument("--capture-gnss-evidence-jsonl", type=Path)
    parser.add_argument(
        "--auto-select-gnss-by-fix-duration-seconds",
        type=float,
        help="Capture every discovered GNSS serial candidate and select the one with a valid fix.",
    )
    parser.add_argument("--auto-select-gnss-evidence-dir", type=Path)
    parser.add_argument(
        "--gnss-hardware-snapshot-json",
        type=Path,
        help="Optional JSON from pi_gnss_hardware_snapshot.py to include hardware/RF next-evidence guidance.",
    )
    parser.add_argument(
        "--include-uart",
        action="store_true",
        help="Include non-USB UART candidates such as /dev/serial0 when --gnss-port auto is used.",
    )
    parser.add_argument("--gnss-baud", type=int, default=115200)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--allow-overwrite", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = build_field_readiness_report(
            mission_graph_path=args.mission_graph,
            gnss_port=args.gnss_port,
            output_dir=args.output_dir,
            allow_overwrite=args.allow_overwrite,
            gnss_evidence_jsonl_paths=args.gnss_evidence_jsonl,
            require_valid_gnss_fix=args.require_valid_gnss_fix,
            min_gnss_cno_dbhz=args.min_gnss_cno_dbhz,
            capture_gnss_duration_seconds=args.capture_gnss_duration_seconds,
            capture_gnss_evidence_jsonl_path=args.capture_gnss_evidence_jsonl,
            auto_select_gnss_by_fix_duration_seconds=args.auto_select_gnss_by_fix_duration_seconds,
            auto_select_gnss_evidence_dir_path=args.auto_select_gnss_evidence_dir,
            gnss_hardware_snapshot_json_path=args.gnss_hardware_snapshot_json,
            gnss_baud=args.gnss_baud,
            include_uart_serial_candidates=args.include_uart,
        )
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=not args.pretty))
    return 0 if report["ready_for_live_field_proof"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
