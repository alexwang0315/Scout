from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from observation_adapter import sensorlog_payload_to_observations  # noqa: E402
from safety_runtime_session import SafetyRuntimeSession, SafetyRuntimeUpdate  # noqa: E402
from ins_dr_source_authority import classify_dr_distance_source  # noqa: E402
from tools.ins_dr_navigation_smoke import load_jsonl_payloads  # noqa: E402
from tools.pi_gnss_nmea_smoke import parse_raw_nmea  # noqa: E402

DR_ESTIMATE_SOURCES = {"dead_reckoning", "dead_reckoning_expired"}


def run_ins_dr_runtime_smoke(
    *,
    mission_graph_path: Path,
    payloads: list[dict[str, Any]],
    device: str = "scout_pi",
    source: str = "runtime_provider_evidence",
) -> dict[str, Any]:
    session = SafetyRuntimeSession(mission_graph_path)
    observations = sensorlog_payload_to_observations(
        {"payloads": payloads},
        device=device,
        source=source,
    )
    updates = [session.observe(observation) for observation in observations]
    snapshot = session.snapshot()
    update_payloads = [_update_payload(update) for update in updates]
    return {
        "source": "ins_dr_runtime_smoke",
        "hardware_kind": "host_side_ins_dr_runtime_ingest_replay",
        "mission_graph": str(mission_graph_path),
        "input_payload_count": len(payloads),
        "observations_accepted": len(observations),
        "safety_level": snapshot.safety_state.level,
        "latest_position_estimate": _latest_position_estimate(update_payloads),
        "latest_route_progress_sample": _latest_route_progress_sample(update_payloads),
        "phase1_live_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_runtime_ingest_replay_only",
        "updates": update_payloads,
    }


def append_updates_jsonl(result: dict[str, Any], output_path: Path | None) -> None:
    if output_path is None:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        for update in result["updates"]:
            handle.write(json.dumps(update, ensure_ascii=False, sort_keys=True) + "\n")


def _update_payload(update: SafetyRuntimeUpdate) -> dict[str, Any]:
    observation = update.observation
    raw_payload = observation.raw.get("raw_payload")
    raw_payload = raw_payload if isinstance(raw_payload, dict) else {}
    dr_input = observation.raw.get("dead_reckoning_input")
    dr_input = dr_input if isinstance(dr_input, dict) else {}
    position_estimate = observation.raw.get("position_estimate")
    position_estimate = position_estimate if isinstance(position_estimate, dict) else None
    dr_source = _dr_source(observation.raw, raw_payload, dr_input, observation_source=observation.source)
    dr_provider = _dr_provider(observation.raw, raw_payload)
    dr_source_review = (
        classify_dr_distance_source(source=dr_source, provider=dr_provider)
        if _is_dead_reckoning_update(position_estimate)
        else None
    )
    return {
        "source_tool": "ins_dr_runtime_smoke",
        "hardware_kind": "host_side_ins_dr_runtime_update",
        "timestamp": observation.timestamp,
        "observation_source": observation.source,
        "observation_lat": observation.lat,
        "observation_lon": observation.lon,
        "observation_distance_delta_m": _dr_distance_delta_m(observation.raw, raw_payload, dr_input),
        "observation_heading_deg": _dr_heading_deg(observation.raw, raw_payload, dr_input),
        "observation_dr_distance_delta_m": dr_input.get("distance_delta_m"),
        "observation_dr_heading_deg": dr_input.get("heading_deg"),
        "observation_dr_raw_evidence_ref": dr_input.get("raw_evidence_ref"),
        "observation_provider_hardware_control_scope": (
            observation.raw.get("hardware_control_scope") or raw_payload.get("hardware_control_scope")
        ),
        "observation_odometry_delta_method": (
            observation.raw.get("odometry_delta_method") or raw_payload.get("odometry_delta_method")
        ),
        "observation_previous_raw_evidence_ref": (
            observation.raw.get("previous_raw_evidence_ref") or raw_payload.get("previous_raw_evidence_ref")
        ),
        "observation_current_raw_evidence_ref": (
            observation.raw.get("current_raw_evidence_ref") or raw_payload.get("current_raw_evidence_ref")
        ),
        "observation_previous_cumulative_distance_m": _float_or_none(
            observation.raw.get("previous_cumulative_distance_m")
            if observation.raw.get("previous_cumulative_distance_m") is not None
            else raw_payload.get("previous_cumulative_distance_m")
        ),
        "observation_current_cumulative_distance_m": _float_or_none(
            observation.raw.get("current_cumulative_distance_m")
            if observation.raw.get("current_cumulative_distance_m") is not None
            else raw_payload.get("current_cumulative_distance_m")
        ),
        "observation_dr_source": dr_source if _is_dead_reckoning_update(position_estimate) else None,
        "observation_dr_provider": dr_provider if _is_dead_reckoning_update(position_estimate) else None,
        "observation_dr_source_kind": dr_source_review["kind"] if dr_source_review is not None else None,
        "observation_dr_navigation_allowed": (
            dr_source_review["navigation_allowed"] if dr_source_review is not None else None
        ),
        "observation_dr_evidence_scope": dr_source_review["evidence_scope"] if dr_source_review is not None else None,
        "observation_capture_mode": observation.raw.get("capture_mode") or raw_payload.get("capture_mode"),
        "observation_device_port": observation.raw.get("device_port") or raw_payload.get("device_port"),
        "observation_baud": observation.raw.get("baud") or raw_payload.get("baud"),
        "observation_raw_sentence_present": bool(
            observation.raw.get("raw_sentence") or raw_payload.get("raw_sentence")
        ),
        "observation_primary_truth_allowed": (
            observation.raw.get("primary_truth_allowed")
            if "primary_truth_allowed" in observation.raw
            else raw_payload.get("primary_truth_allowed")
        ),
        "observation_primary_truth_scope": (
            observation.raw.get("primary_truth_scope") or raw_payload.get("primary_truth_scope")
        ),
        "observation_checksum_valid": (
            observation.raw.get("checksum_valid")
            if "checksum_valid" in observation.raw
            else raw_payload.get("checksum_valid")
        ),
        "observation_imu_checksum_valid": (
            observation.raw.get("checksum_valid")
            if _looks_like_imu_heading_observation(observation.raw, raw_payload)
            else None
        ),
        "observation_dry_run": (
            observation.raw.get("dry_run")
            if "dry_run" in observation.raw
            else raw_payload.get("dry_run")
        ),
        "observation_previous_dry_run": (
            observation.raw.get("previous_dry_run")
            if "previous_dry_run" in observation.raw
            else raw_payload.get("previous_dry_run")
        ),
        "observation_current_dry_run": (
            observation.raw.get("current_dry_run")
            if "current_dry_run" in observation.raw
            else raw_payload.get("current_dry_run")
        ),
        "observation_raw_evidence_ref": observation.raw.get("raw_evidence_ref") or raw_payload.get("raw_evidence_ref"),
        "position_estimate": position_estimate,
        "route_progress_sample": (
            asdict(update.route_progress_sample)
            if update.route_progress_sample is not None
            else None
        ),
        "recording_profile": update.recording_decision.profile,
        "safety_level": update.safety_state.level,
        "safety_events": [event.model_dump(mode="json") for event in update.safety_events],
        "checkpoint_arrival": (
            {
                "checkpoint_id": update.checkpoint_arrival.checkpoint.checkpoint_id,
                "distance_m": update.checkpoint_arrival.distance_m,
            }
            if update.checkpoint_arrival is not None
            else None
        ),
        "phase1_live_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_runtime_ingest_replay_only",
    }


def _is_dead_reckoning_update(position_estimate: dict[str, Any] | None) -> bool:
    return (
        isinstance(position_estimate, dict)
        and str(position_estimate.get("source") or "") in DR_ESTIMATE_SOURCES
    )


def _looks_like_imu_heading_observation(raw: dict[str, Any], raw_payload: dict[str, Any]) -> bool:
    source = str(raw.get("source") or raw_payload.get("source") or "").lower()
    hardware_kind = str(raw.get("hardware_kind") or raw_payload.get("hardware_kind") or "").lower()
    frame_type = str(raw.get("frame_type") or raw_payload.get("frame_type") or "").lower()
    return (
        "imu" in source
        or "hiwonder" in source
        or "wit" in source
        or "imu" in hardware_kind
        or "hiwonder" in hardware_kind
        or "wit" in hardware_kind
        or frame_type in {"acceleration", "gyro", "angle"}
    )


def _dr_source(
    raw: dict[str, Any],
    raw_payload: dict[str, Any],
    dr_input: dict[str, Any],
    *,
    observation_source: str,
) -> str | None:
    odometry = _section(raw, raw_payload, "odometry")
    dr = _section(raw, raw_payload, "dr")
    sensorlog = raw.get("sensorlog") if isinstance(raw.get("sensorlog"), dict) else {}

    if dr_input.get("source") not in (None, ""):
        return str(dr_input.get("source"))
    if _dr_distance_delta_m(raw, raw_payload, dr_input) is not None:
        return _first_text(dr, odometry, raw_payload, raw, keys=("source",)) or observation_source
    if _first_present(sensorlog, raw_payload, raw, keys=("pedometerDistance", "distance_m")) is not None:
        return "sensorlog_pedometer_distance"
    if _first_present(
        sensorlog,
        raw_payload,
        raw,
        keys=("pedometerNumberOfSteps", "pedometerNumberofSteps", "steps"),
    ) is not None:
        return "sensorlog_pedometer_steps"
    return observation_source


def _dr_provider(raw: dict[str, Any], raw_payload: dict[str, Any]) -> str | None:
    odometry = _section(raw, raw_payload, "odometry")
    dr = _section(raw, raw_payload, "dr")
    return _first_text(dr, odometry, raw_payload, raw, keys=("provider", "device", "hardware_provider"))


def _dr_distance_delta_m(raw: dict[str, Any], raw_payload: dict[str, Any], dr_input: dict[str, Any]) -> float | None:
    direct = _float_or_none(dr_input.get("distance_delta_m"))
    if direct is not None:
        return direct
    odometry = _section(raw, raw_payload, "odometry")
    dr = _section(raw, raw_payload, "dr")
    return _first_float(raw, raw_payload, odometry, dr, keys=("distance_delta_m",))


def _dr_heading_deg(raw: dict[str, Any], raw_payload: dict[str, Any], dr_input: dict[str, Any]) -> float | None:
    direct = _float_or_none(dr_input.get("heading_deg"))
    if direct is not None:
        return direct
    odometry = _section(raw, raw_payload, "odometry")
    dr = _section(raw, raw_payload, "dr")
    heading = _first_float(raw, raw_payload, odometry, dr, keys=("heading_deg", "motionHeading", "locationCourse"))
    if heading is not None:
        return heading
    return _parsed_angle_heading(raw) or _parsed_angle_heading(raw_payload)


def _section(raw: dict[str, Any], raw_payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if isinstance(value, dict):
        return value
    raw_value = raw_payload.get(key)
    return raw_value if isinstance(raw_value, dict) else {}


def _parsed_angle_heading(mapping: dict[str, Any]) -> float | None:
    parsed = mapping.get("parsed") if isinstance(mapping.get("parsed"), dict) else {}
    angle = parsed.get("angle_deg")
    if isinstance(angle, (list, tuple)) and len(angle) >= 3:
        yaw = _float_or_none(angle[2])
        if yaw is not None and yaw >= 0:
            return yaw % 360.0
    return None


def _first_text(*mappings: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for mapping in mappings:
        for key in keys:
            value = mapping.get(key)
            if value not in (None, ""):
                return str(value)
    return None


def _first_present(*mappings: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for mapping in mappings:
        for key in keys:
            value = mapping.get(key)
            if value not in (None, "", "null"):
                return value
    return None


def _first_float(*mappings: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    value = _first_present(*mappings, keys=keys)
    return _float_or_none(value)


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _latest_position_estimate(updates: list[dict[str, Any]]) -> dict[str, Any] | None:
    for update in reversed(updates):
        position_estimate = update.get("position_estimate")
        if isinstance(position_estimate, dict):
            return position_estimate
    return None


def _latest_route_progress_sample(updates: list[dict[str, Any]]) -> dict[str, Any] | None:
    for update in reversed(updates):
        route_progress_sample = update.get("route_progress_sample")
        if isinstance(route_progress_sample, dict):
            return route_progress_sample
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Replay Scout GNSS/DR evidence JSONL through SafetyRuntimeSession."
    )
    parser.add_argument("--mission-graph", type=Path, required=True)
    parser.add_argument("--input-jsonl", type=Path, action="append", default=[], help="Evidence JSONL file. May repeat.")
    parser.add_argument("--raw-nmea", help="Parse fixture NMEA text and feed it before JSONL inputs.")
    parser.add_argument("--device", default="scout_pi")
    parser.add_argument("--source", default="runtime_provider_evidence")
    parser.add_argument("--output-jsonl", type=Path)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    try:
        payloads: list[dict[str, Any]] = []
        if args.raw_nmea is not None:
            payloads.extend(
                parse_raw_nmea(
                    args.raw_nmea,
                    device_port="raw-nmea",
                    baud=0,
                    capture_mode="raw_nmea_argument",
                )
            )
        payloads.extend(load_jsonl_payloads(args.input_jsonl))
        result = run_ins_dr_runtime_smoke(
            mission_graph_path=args.mission_graph,
            payloads=payloads,
            device=args.device,
            source=args.source,
        )
        append_updates_jsonl(result, args.output_jsonl)
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=not args.pretty))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
