from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from geo_utils import haversine_m  # noqa: E402
from ins_dr_input_adapter import InsDrInputState, dead_reckoning_delta_from_payload  # noqa: E402
from ins_dr_navigation import GnssFix, InsDrConfig, InsDrEstimate, ScoutInsDrNavigator, route_heading_deg  # noqa: E402
from route_matching import GpxRoute, RoutePoint  # noqa: E402


PDR_RESOLUTION_MODES = {"pedometer_updates", "distributed_sensorlog"}
PDR_HEADING_POLICIES = {"sensorlog_course", "reliable_course", "no_heading", "route_heading"}
PDR_REPLAY_PROFILES = {
    "manual": {
        "pdr_resolution_mode": "pedometer_updates",
        "pdr_heading_policy": "sensorlog_course",
        "notes": "Legacy/manual replay options; explicit flags control the actual mode.",
    },
    "wearable_route_constrained": {
        "pdr_resolution_mode": "distributed_sensorlog",
        "pdr_heading_policy": "no_heading",
        "notes": (
            "Recommended wearable-first client profile: pedometerDistance is the distance authority, "
            "deltas are distributed across SensorLog cadence, and uncalibrated watch heading is not used."
        ),
    },
    "wearable_course_gated": {
        "pdr_resolution_mode": "distributed_sensorlog",
        "pdr_heading_policy": "reliable_course",
        "notes": "Wearable diagnostic profile that only keeps course-over-ground when GPS accuracy and speed pass gates.",
    },
    "route_heading_oracle": {
        "pdr_resolution_mode": "distributed_sensorlog",
        "pdr_heading_policy": "route_heading",
        "notes": "Upper-bound replay profile; it uses planned-route heading and is not independent sensor evidence.",
    },
}
HEADING_KEYS = ("heading_deg", "motionHeading", "locationCourse", "locationTrueHeading", "locationMagneticHeading")


def run_sensorlog_replay(
    *,
    input_path: Path,
    max_horizontal_accuracy_m: float = 25.0,
    gnss_anchor_interval_s: float = 60.0,
    max_dead_reckoning_seconds: float = 300.0,
    max_dead_reckoning_distance_m: float = 250.0,
    pdr_profile: str = "manual",
    pdr_resolution_mode: str | None = None,
    pdr_heading_policy: str | None = None,
    reliable_course_min_speed_mps: float = 0.5,
    include_estimates: bool = False,
) -> dict[str, Any]:
    replay_options = resolve_pdr_replay_options(
        pdr_profile=pdr_profile,
        pdr_resolution_mode=pdr_resolution_mode,
        pdr_heading_policy=pdr_heading_policy,
    )
    pdr_profile = replay_options["pdr_profile"]
    pdr_resolution_mode = replay_options["pdr_resolution_mode"]
    pdr_heading_policy = replay_options["pdr_heading_policy"]
    records = _load_sensorlog_records(input_path)
    distributed_deltas = (
        _distributed_pdr_deltas(records, input_path=input_path)
        if pdr_resolution_mode == "distributed_sensorlog"
        else {}
    )
    route = _route_from_sensorlog(
        input_path=input_path,
        records=records,
        max_horizontal_accuracy_m=max_horizontal_accuracy_m,
    )
    navigator = ScoutInsDrNavigator(
        route,
        config=InsDrConfig(
            reliable_gnss_accuracy_threshold_m=max_horizontal_accuracy_m,
            max_dead_reckoning_seconds=max_dead_reckoning_seconds,
            max_dead_reckoning_distance_m=max_dead_reckoning_distance_m,
        ),
    )
    state = InsDrInputState()
    estimates: list[InsDrEstimate] = []
    last_anchor_timestamp_s: float | None = None
    anchor_seen = False
    dr_delta_count = 0
    dr_delta_distance_m = 0.0
    last_progress_for_heading_m: float | None = None

    for index, record in enumerate(records):
        timestamp_s = _replay_timestamp_s(
            record,
            fallback_timestamp_s=float(index),
            prefer_logging_time=pdr_resolution_mode == "distributed_sensorlog",
        )
        route_heading_for_delta = (
            route_heading_deg(route, last_progress_for_heading_m)
            if pdr_heading_policy == "route_heading" and last_progress_for_heading_m is not None
            else None
        )
        dr_delta = _dead_reckoning_delta_for_record(
            input_path=input_path,
            index=index,
            record=record,
            state=state,
            timestamp_s=timestamp_s,
            pdr_resolution_mode=pdr_resolution_mode,
            pdr_heading_policy=pdr_heading_policy,
            max_horizontal_accuracy_m=max_horizontal_accuracy_m,
            reliable_course_min_speed_mps=reliable_course_min_speed_mps,
            route_heading_for_delta=route_heading_for_delta,
            distributed_deltas=distributed_deltas,
        )

        gnss_fix = _gnss_fix_from_sensorlog_record(
            input_path=input_path,
            index=index,
            record=record,
            timestamp_s=timestamp_s,
            max_horizontal_accuracy_m=max_horizontal_accuracy_m,
        )
        should_anchor = (
            gnss_fix is not None
            and (
                last_anchor_timestamp_s is None
                or timestamp_s - last_anchor_timestamp_s >= gnss_anchor_interval_s
            )
        )
        if should_anchor:
            estimate = navigator.observe(gnss_fix=gnss_fix)
            estimates.append(estimate)
            anchor_seen = True
            last_anchor_timestamp_s = timestamp_s
            last_progress_for_heading_m = estimate.progress_m
            continue

        if not anchor_seen or dr_delta is None:
            continue

        dr_delta_count += 1
        dr_delta_distance_m += dr_delta.distance_delta_m
        estimate = navigator.observe(dr_delta=dr_delta)
        estimates.append(estimate)
        last_progress_for_heading_m = estimate.progress_m

    return _build_report(
        input_path=input_path,
        records=records,
        route=route,
        estimates=estimates,
        max_horizontal_accuracy_m=max_horizontal_accuracy_m,
        gnss_anchor_interval_s=gnss_anchor_interval_s,
        dr_delta_count=dr_delta_count,
        dr_delta_distance_m=dr_delta_distance_m,
        pdr_profile=pdr_profile,
        pdr_resolution_mode=pdr_resolution_mode,
        pdr_heading_policy=pdr_heading_policy,
        reliable_course_min_speed_mps=reliable_course_min_speed_mps,
        distributed_pdr_summary=_distributed_pdr_summary(distributed_deltas),
        include_estimates=include_estimates,
    )


def run_sensorlog_replays(
    *,
    input_paths: list[Path],
    max_horizontal_accuracy_m: float = 25.0,
    gnss_anchor_interval_s: float = 60.0,
    max_dead_reckoning_seconds: float = 300.0,
    max_dead_reckoning_distance_m: float = 250.0,
    pdr_profile: str = "manual",
    pdr_resolution_mode: str | None = None,
    pdr_heading_policy: str | None = None,
    reliable_course_min_speed_mps: float = 0.5,
    include_estimates: bool = False,
) -> dict[str, Any]:
    replay_options = resolve_pdr_replay_options(
        pdr_profile=pdr_profile,
        pdr_resolution_mode=pdr_resolution_mode,
        pdr_heading_policy=pdr_heading_policy,
    )
    reports = [
        run_sensorlog_replay(
            input_path=input_path,
            max_horizontal_accuracy_m=max_horizontal_accuracy_m,
            gnss_anchor_interval_s=gnss_anchor_interval_s,
            max_dead_reckoning_seconds=max_dead_reckoning_seconds,
            max_dead_reckoning_distance_m=max_dead_reckoning_distance_m,
            pdr_profile=replay_options["pdr_profile"],
            pdr_resolution_mode=replay_options["pdr_resolution_mode"],
            pdr_heading_policy=replay_options["pdr_heading_policy"],
            reliable_course_min_speed_mps=reliable_course_min_speed_mps,
            include_estimates=include_estimates,
        )
        for input_path in input_paths
    ]
    return {
        "artifact_kind": "scout_ins_dr_sensorlog_replay_bundle",
        "source_tool": "ins_dr_sensorlog_replay",
        "input_count": len(input_paths),
        "max_horizontal_accuracy_m": max_horizontal_accuracy_m,
        "gnss_anchor_interval_s": gnss_anchor_interval_s,
        "pdr_profile": replay_options["pdr_profile"],
        "pdr_profile_notes": replay_options["pdr_profile_notes"],
        "pdr_resolution_mode": replay_options["pdr_resolution_mode"],
        "pdr_heading_policy": replay_options["pdr_heading_policy"],
        "reliable_course_min_speed_mps": reliable_course_min_speed_mps,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_sensorlog_replay_only",
        "live_navigation_completion_proof": False,
        "reports": reports,
        "bundle_summary": _bundle_summary(reports),
    }


def write_estimates_jsonl(report: dict[str, Any], output_path: Path | None) -> None:
    if output_path is None:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for replay_report in report.get("reports", []):
            for estimate in replay_report.get("estimates", []):
                handle.write(json.dumps(estimate, ensure_ascii=False, sort_keys=True) + "\n")


def resolve_pdr_replay_options(
    *,
    pdr_profile: str = "manual",
    pdr_resolution_mode: str | None = None,
    pdr_heading_policy: str | None = None,
) -> dict[str, str]:
    if pdr_profile not in PDR_REPLAY_PROFILES:
        raise ValueError(f"Unsupported PDR replay profile: {pdr_profile}")
    profile = PDR_REPLAY_PROFILES[pdr_profile]
    resolved_resolution = pdr_resolution_mode or profile["pdr_resolution_mode"]
    resolved_heading = pdr_heading_policy or profile["pdr_heading_policy"]
    if resolved_resolution not in PDR_RESOLUTION_MODES:
        raise ValueError(f"Unsupported PDR resolution mode: {resolved_resolution}")
    if resolved_heading not in PDR_HEADING_POLICIES:
        raise ValueError(f"Unsupported PDR heading policy: {resolved_heading}")
    return {
        "pdr_profile": pdr_profile,
        "pdr_profile_notes": profile["notes"],
        "pdr_resolution_mode": resolved_resolution,
        "pdr_heading_policy": resolved_heading,
    }


def _build_report(
    *,
    input_path: Path,
    records: list[dict[str, Any]],
    route: GpxRoute,
    estimates: list[InsDrEstimate],
    max_horizontal_accuracy_m: float,
    gnss_anchor_interval_s: float,
    dr_delta_count: int,
    dr_delta_distance_m: float,
    pdr_profile: str,
    pdr_resolution_mode: str,
    pdr_heading_policy: str,
    reliable_course_min_speed_mps: float,
    distributed_pdr_summary: dict[str, Any],
    include_estimates: bool,
) -> dict[str, Any]:
    estimate_payloads = [_estimate_payload(estimate) for estimate in estimates]
    source_counts = Counter(estimate.source for estimate in estimates)
    reanchor_corrections = [
        abs(estimate.gps_reanchor_correction_m)
        for estimate in estimates
        if estimate.gps_reanchor_correction_m is not None
    ]
    accuracy_values = [
        value
        for value in (_float_or_none(record.get("locationHorizontalAccuracy")) for record in records)
        if value is not None
    ]
    pedometer = _pedometer_summary(records)
    heading_summary = _heading_summary(records)
    status = _replay_status(
        estimates=estimates,
        route=route,
        dr_delta_count=dr_delta_count,
        heading_summary=heading_summary,
    )
    report = {
        "artifact_kind": "scout_ins_dr_sensorlog_replay_report",
        "source_tool": "ins_dr_sensorlog_replay",
        "input_path": str(input_path),
        "record_count": len(records),
        "route_point_count": len(route.points),
        "route_distance_m": route.points[-1].progress_m,
        "duration_s": _duration_s(records),
        "time_start": _first_text(records, "loggingTime"),
        "time_end": _last_text(records, "loggingTime"),
        "max_horizontal_accuracy_m": max_horizontal_accuracy_m,
        "gnss_anchor_interval_s": gnss_anchor_interval_s,
        "pdr_profile": pdr_profile,
        "pdr_profile_notes": PDR_REPLAY_PROFILES[pdr_profile]["notes"],
        "pdr_resolution_mode": pdr_resolution_mode,
        "pdr_heading_policy": pdr_heading_policy,
        "reliable_course_min_speed_mps": reliable_course_min_speed_mps,
        "distributed_pdr_summary": distributed_pdr_summary,
        "location_accuracy_summary": _numeric_summary(accuracy_values),
        "pedometer_summary": pedometer,
        "heading_summary": heading_summary,
        "estimate_count": len(estimates),
        "estimate_source_counts": dict(source_counts),
        "gnss_anchor_count": source_counts.get("gnss", 0) + source_counts.get("gnss_reanchor", 0),
        "dead_reckoning_estimate_count": source_counts.get("dead_reckoning", 0)
        + source_counts.get("dead_reckoning_expired", 0),
        "dr_delta_count": dr_delta_count,
        "dr_delta_distance_m": dr_delta_distance_m,
        "pedometer_vs_route_distance_ratio": (
            pedometer["distance_delta_m"] / route.points[-1].progress_m
            if pedometer["distance_delta_m"] is not None and route.points[-1].progress_m > 0
            else None
        ),
        "gps_reanchor_correction_abs_m": _numeric_summary(reanchor_corrections),
        "offline_replay_validation_status": status,
        "offline_replay_validation_possible": status != "failed",
        "live_navigation_completion_proof": False,
        "anchor_source_scope": "apple_watch_sensorlog_location_replay_not_raw_nmea",
        "validates": [
            "SensorLog location can provide replay anchors",
            "SensorLog cumulative pedometerDistance becomes DR distance deltas",
            "Scout INS/DR navigator can advance from anchor using DR and report GPS re-anchor correction",
        ],
        "does_not_validate": [
            "live raw GNSS NMEA reception on Scout",
            "live wheel encoder odometry",
            "live Hiwonder raw IMU heading baseline",
            "USB/UART timestamp alignment on Scout",
            "Phase 1 live safety decision mutation",
        ],
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_sensorlog_replay_only",
        "estimate_samples": {
            "first": estimate_payloads[0] if estimate_payloads else None,
            "last": estimate_payloads[-1] if estimate_payloads else None,
        },
    }
    if include_estimates:
        report["estimates"] = estimate_payloads
    return report


def _load_sensorlog_records(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.expanduser().read_text(encoding="utf-8"))
    if isinstance(payload, list):
        records = [item for item in payload if isinstance(item, dict)]
    elif isinstance(payload, dict):
        for key in ("imu_data", "payloads", "observations"):
            value = payload.get(key)
            if isinstance(value, list):
                records = [item for item in value if isinstance(item, dict)]
                break
        else:
            records = [payload]
    else:
        raise ValueError(f"SensorLog JSON must be a list or object: {path}")
    if not records:
        raise ValueError(f"No SensorLog records found: {path}")
    return records


def _dead_reckoning_delta_for_record(
    *,
    input_path: Path,
    index: int,
    record: dict[str, Any],
    state: InsDrInputState,
    timestamp_s: float,
    pdr_resolution_mode: str,
    pdr_heading_policy: str,
    max_horizontal_accuracy_m: float,
    reliable_course_min_speed_mps: float,
    route_heading_for_delta: float | None,
    distributed_deltas: dict[int, dict[str, Any]],
) -> Any:
    record_with_timestamp = _record_with_heading_policy(
        {**record, "timestamp_s": timestamp_s},
        pdr_heading_policy=pdr_heading_policy,
        max_horizontal_accuracy_m=max_horizontal_accuracy_m,
        reliable_course_min_speed_mps=reliable_course_min_speed_mps,
        route_heading_for_delta=route_heading_for_delta,
    )
    if pdr_resolution_mode == "distributed_sensorlog":
        distributed = distributed_deltas.get(index)
        if distributed is None:
            return None
        dr_payload = {
            **record_with_timestamp,
            "source": "apple_watch_sensorlog_pedometer_distributed",
            "distance_delta_m": distributed["distance_delta_m"],
            "raw_evidence_ref": (
                f"{_evidence_ref(input_path, index, 'sensorlog_pedometer_distributed')}:"
                f"{distributed['start_index'] + 1}-{distributed['end_index'] + 1}"
            ),
        }
    else:
        dr_payload = {
            "source": "apple_watch_sensorlog_pedometer",
            "sensorlog": record_with_timestamp,
            "raw_evidence_ref": _evidence_ref(input_path, index, "sensorlog_pedometer"),
        }
    return dead_reckoning_delta_from_payload(
        dr_payload,
        state,
        fallback_timestamp_s=timestamp_s,
    )


def _record_with_heading_policy(
    record: dict[str, Any],
    *,
    pdr_heading_policy: str,
    max_horizontal_accuracy_m: float,
    reliable_course_min_speed_mps: float,
    route_heading_for_delta: float | None,
) -> dict[str, Any]:
    if pdr_heading_policy == "sensorlog_course":
        return record

    filtered = {key: value for key, value in record.items() if key not in HEADING_KEYS}
    if pdr_heading_policy == "no_heading":
        return filtered
    if pdr_heading_policy == "route_heading":
        if route_heading_for_delta is not None:
            filtered["heading_deg"] = route_heading_for_delta
        return filtered
    if pdr_heading_policy == "reliable_course":
        if _course_is_reliable(
            record,
            max_horizontal_accuracy_m=max_horizontal_accuracy_m,
            reliable_course_min_speed_mps=reliable_course_min_speed_mps,
        ):
            filtered["locationCourse"] = record.get("locationCourse")
        return filtered
    return record


def _course_is_reliable(
    record: dict[str, Any],
    *,
    max_horizontal_accuracy_m: float,
    reliable_course_min_speed_mps: float,
) -> bool:
    course = _non_negative_float(record.get("locationCourse"))
    if course is None:
        return False
    accuracy = _float_or_none(record.get("locationHorizontalAccuracy"))
    if accuracy is not None and accuracy > max_horizontal_accuracy_m:
        return False
    speed = _float_or_none(record.get("locationSpeed"))
    return speed is not None and speed >= reliable_course_min_speed_mps


def _distributed_pdr_deltas(records: list[dict[str, Any]], *, input_path: Path) -> dict[int, dict[str, Any]]:
    deltas: dict[int, dict[str, Any]] = {}
    previous_index: int | None = None
    previous_distance: float | None = None

    for index, record in enumerate(records):
        distance = _float_or_none(record.get("pedometerDistance"))
        if distance is None:
            continue
        if previous_index is None or previous_distance is None:
            previous_index = index
            previous_distance = distance
            continue
        delta = distance - previous_distance
        if delta > 0 and index > previous_index:
            span = list(range(previous_index + 1, index + 1))
            per_record_delta = delta / len(span)
            for span_index in span:
                deltas[span_index] = {
                    "distance_delta_m": per_record_delta,
                    "start_index": previous_index,
                    "end_index": index,
                    "source_distance_delta_m": delta,
                    "source_record_count": len(span),
                    "source_path": str(input_path),
                }
            previous_index = index
            previous_distance = distance
        elif delta < 0:
            previous_index = index
            previous_distance = distance
    return deltas


def _distributed_pdr_summary(distributed_deltas: dict[int, dict[str, Any]]) -> dict[str, Any]:
    if not distributed_deltas:
        return {
            "enabled": False,
            "distributed_delta_count": 0,
            "distributed_distance_m": 0.0,
            "distance_authority": "pedometerDistance",
            "distribution_method": None,
            "raw_imu_integrated": False,
        }
    values = [float(item["distance_delta_m"]) for item in distributed_deltas.values()]
    return {
        "enabled": True,
        "distributed_delta_count": len(values),
        "distributed_distance_m": sum(values),
        "median_delta_m": statistics.median(values),
        "mean_delta_m": statistics.fmean(values),
        "distance_authority": "pedometerDistance",
        "distribution_method": "spread each positive pedometerDistance interval over intermediate SensorLog records",
        "timestamp_source_preference": "loggingTime",
        "raw_imu_integrated": False,
    }


def _route_from_sensorlog(
    *,
    input_path: Path,
    records: list[dict[str, Any]],
    max_horizontal_accuracy_m: float,
) -> GpxRoute:
    points: list[RoutePoint] = []
    previous: RoutePoint | None = None
    progress_m = 0.0
    for record in records:
        lat_lon = _valid_lat_lon(record)
        if lat_lon is None:
            continue
        accuracy = _float_or_none(record.get("locationHorizontalAccuracy"))
        if accuracy is not None and accuracy > max_horizontal_accuracy_m:
            continue
        lat, lon = lat_lon
        if previous is not None:
            progress_m += haversine_m(previous.lat, previous.lon, lat, lon)
        point = RoutePoint(
            lat=lat,
            lon=lon,
            elevation_m=_float_or_none(record.get("locationAltitude")),
            timestamp=_iso_time(record),
            progress_m=progress_m,
            gps_horizontal_accuracy_m=accuracy,
            course_deg=_non_negative_float(record.get("locationCourse")),
            pedometer_distance_m=_float_or_none(record.get("pedometerDistance")),
            pedometer_steps=_int_or_none(
                record.get("pedometerNumberOfSteps") or record.get("pedometerNumberofSteps")
            ),
        )
        points.append(point)
        previous = point
    if not points:
        raise ValueError(
            f"No valid SensorLog location points at or below {max_horizontal_accuracy_m:g} m accuracy: {input_path}"
        )
    return GpxRoute(source=input_path, points=points)


def _gnss_fix_from_sensorlog_record(
    *,
    input_path: Path,
    index: int,
    record: dict[str, Any],
    timestamp_s: float,
    max_horizontal_accuracy_m: float,
) -> GnssFix | None:
    lat_lon = _valid_lat_lon(record)
    if lat_lon is None:
        return None
    accuracy = _float_or_none(record.get("locationHorizontalAccuracy"))
    if accuracy is not None and accuracy > max_horizontal_accuracy_m:
        return None
    lat, lon = lat_lon
    return GnssFix(
        timestamp_s=timestamp_s,
        lat=lat,
        lon=lon,
        horizontal_accuracy_m=accuracy,
        fix_quality=1,
        status="A",
        raw_evidence_ref=_evidence_ref(input_path, index, "sensorlog_location"),
    )


def _estimate_payload(estimate: InsDrEstimate) -> dict[str, Any]:
    payload = estimate.to_dict()
    payload.update(
        {
            "source_tool": "ins_dr_sensorlog_replay",
            "hardware_kind": "host_side_sensorlog_ins_dr_replay",
            "anchor_source_scope": "apple_watch_sensorlog_location_replay_not_raw_nmea",
            "phase1_safety_decision_change_allowed": False,
            "remote_outbound_allowed": False,
            "hardware_control_scope": "diagnostic_sensorlog_replay_only",
        }
    )
    return payload


def _replay_status(
    *,
    estimates: list[InsDrEstimate],
    route: GpxRoute,
    dr_delta_count: int,
    heading_summary: dict[str, Any],
) -> str:
    source_counts = Counter(estimate.source for estimate in estimates)
    if not estimates or not route.points:
        return "failed"
    if source_counts.get("gnss", 0) <= 0:
        return "failed"
    if dr_delta_count <= 0 or source_counts.get("dead_reckoning", 0) <= 0:
        return "failed"
    if heading_summary["absolute_heading_sample_count"] <= 0:
        return "passed_with_heading_limitation"
    return "passed"


def _bundle_summary(reports: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = Counter(report["offline_replay_validation_status"] for report in reports)
    return {
        "report_count": len(reports),
        "status_counts": dict(statuses),
        "total_records": sum(report["record_count"] for report in reports),
        "total_route_distance_m": sum(report["route_distance_m"] for report in reports),
        "total_pedometer_distance_delta_m": sum(
            report["pedometer_summary"]["distance_delta_m"] or 0.0 for report in reports
        ),
        "total_dr_delta_count": sum(report["dr_delta_count"] for report in reports),
        "total_gnss_anchor_count": sum(report["gnss_anchor_count"] for report in reports),
        "total_dead_reckoning_estimate_count": sum(report["dead_reckoning_estimate_count"] for report in reports),
        "live_navigation_completion_proof": False,
    }


def _pedometer_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    distances = [_float_or_none(record.get("pedometerDistance")) for record in records]
    distances = [value for value in distances if value is not None]
    steps = [
        _int_or_none(record.get("pedometerNumberOfSteps") or record.get("pedometerNumberofSteps"))
        for record in records
    ]
    steps = [value for value in steps if value is not None]
    return {
        "distance_sample_count": len(distances),
        "distance_start_m": distances[0] if distances else None,
        "distance_end_m": distances[-1] if distances else None,
        "distance_delta_m": (distances[-1] - distances[0]) if len(distances) >= 2 else None,
        "steps_sample_count": len(steps),
        "steps_start": steps[0] if steps else None,
        "steps_end": steps[-1] if steps else None,
        "steps_delta": (steps[-1] - steps[0]) if len(steps) >= 2 else None,
    }


def _heading_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    absolute_keys = ("motionHeading", "locationCourse", "locationTrueHeading", "locationMagneticHeading")
    absolute_count = 0
    by_key: dict[str, int] = {}
    for key in absolute_keys:
        count = sum(1 for record in records if _non_negative_float(record.get(key)) is not None)
        by_key[key] = count
        absolute_count += count
    motion_yaw_count = sum(1 for record in records if _float_or_none(record.get("motionYaw")) is not None)
    return {
        "absolute_heading_sample_count": absolute_count,
        "absolute_heading_sample_count_by_key": by_key,
        "motion_yaw_sample_count": motion_yaw_count,
        "motion_yaw_used_as_geo_heading": False,
        "limitation": (
            "No non-negative absolute heading field was present; replay validates DR distance and re-anchor behavior, "
            "but not a calibrated IMU heading baseline."
            if absolute_count == 0
            else None
        ),
    }


def _numeric_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None, "median": None}
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
    }


def _duration_s(records: list[dict[str, Any]]) -> float | None:
    timestamps = [_timestamp_s(record, fallback_timestamp_s=float(index)) for index, record in enumerate(records)]
    if len(timestamps) < 2:
        return None
    return max(timestamps) - min(timestamps)


def _valid_lat_lon(record: dict[str, Any]) -> tuple[float, float] | None:
    lat = _float_or_none(record.get("locationLatitude"))
    lon = _float_or_none(record.get("locationLongitude"))
    if lat is None or lon is None:
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    return lat, lon


def _timestamp_s(record: dict[str, Any], *, fallback_timestamp_s: float) -> float:
    for key in ("timestamp_s", "locationTimestamp_since1970", "loggingTimestamp_s", "motionTimestamp_sinceReboot"):
        value = _float_or_none(record.get(key))
        if value is not None:
            return value
    raw = record.get("loggingTime") or record.get("heartRateBPMTimestamp")
    if isinstance(raw, str) and raw and raw != "null":
        parsed = _parse_datetime_s(raw)
        if parsed is not None:
            return parsed
    return fallback_timestamp_s


def _replay_timestamp_s(
    record: dict[str, Any],
    *,
    fallback_timestamp_s: float,
    prefer_logging_time: bool,
) -> float:
    if prefer_logging_time:
        raw = record.get("loggingTime") or record.get("heartRateBPMTimestamp")
        if isinstance(raw, str) and raw and raw != "null":
            parsed = _parse_datetime_s(raw)
            if parsed is not None:
                return parsed
    return _timestamp_s(record, fallback_timestamp_s=fallback_timestamp_s)


def _parse_datetime_s(value: str) -> float | None:
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _iso_time(record: dict[str, Any]) -> str | None:
    raw = record.get("loggingTime") or record.get("heartRateBPMTimestamp")
    if isinstance(raw, str) and raw and raw != "null":
        parsed = _parse_datetime_s(raw)
        if parsed is None:
            return raw
        return datetime.fromtimestamp(parsed, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    return None


def _evidence_ref(path: Path, index: int, kind: str) -> str:
    return f"{path}:{index + 1}:{kind}"


def _first_text(records: list[dict[str, Any]], key: str) -> str | None:
    for record in records:
        value = record.get(key)
        if value not in (None, "", "null"):
            return str(value)
    return None


def _last_text(records: list[dict[str, Any]], key: str) -> str | None:
    for record in reversed(records):
        value = record.get(key)
        if value not in (None, "", "null"):
            return str(value)
    return None


def _non_negative_float(value: Any) -> float | None:
    parsed = _float_or_none(value)
    if parsed is None or parsed < 0:
        return None
    return parsed


def _float_or_none(value: Any) -> float | None:
    if value in (None, "", "null"):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(parsed) or math.isinf(parsed):
        return None
    return parsed


def _int_or_none(value: Any) -> int | None:
    parsed = _float_or_none(value)
    return int(parsed) if parsed is not None else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Replay Apple Watch/SensorLog GPS + pedometer samples through Scout INS/DR diagnostics."
    )
    parser.add_argument("--input", type=Path, action="append", required=True, help="SensorLog JSON input. May repeat.")
    parser.add_argument("--output-report", type=Path, help="Write replay report JSON.")
    parser.add_argument("--output-jsonl", type=Path, help="Write replay estimates JSONL.")
    parser.add_argument("--include-estimates", action="store_true", help="Embed every estimate in stdout/report JSON.")
    parser.add_argument("--max-horizontal-accuracy-m", type=float, default=25.0)
    parser.add_argument("--gnss-anchor-interval-s", type=float, default=60.0)
    parser.add_argument("--max-dead-reckoning-seconds", type=float, default=300.0)
    parser.add_argument("--max-dead-reckoning-distance-m", type=float, default=250.0)
    parser.add_argument(
        "--pdr-profile",
        choices=sorted(PDR_REPLAY_PROFILES),
        default="manual",
        help=(
            "Named replay profile. wearable_route_constrained is the wearable-first client default; "
            "route_heading_oracle is only an upper-bound diagnostic."
        ),
    )
    parser.add_argument(
        "--pdr-resolution-mode",
        choices=sorted(PDR_RESOLUTION_MODES),
        default=None,
        help=(
            "pedometer_updates emits DR only when cumulative pedometerDistance changes; "
            "distributed_sensorlog spreads each pedometer interval over intermediate SensorLog records. "
            "Overrides the selected --pdr-profile resolution."
        ),
    )
    parser.add_argument(
        "--pdr-heading-policy",
        choices=sorted(PDR_HEADING_POLICIES),
        default=None,
        help=(
            "sensorlog_course uses SensorLog heading/course directly; reliable_course only keeps locationCourse "
            "when GPS accuracy and speed are acceptable; no_heading forces forward route progress; "
            "route_heading uses planned-route heading as an upper-bound replay. "
            "Overrides the selected --pdr-profile heading policy."
        ),
    )
    parser.add_argument("--reliable-course-min-speed-mps", type=float, default=0.5)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = run_sensorlog_replays(
            input_paths=[path.expanduser().resolve() for path in args.input],
            max_horizontal_accuracy_m=args.max_horizontal_accuracy_m,
            gnss_anchor_interval_s=args.gnss_anchor_interval_s,
            max_dead_reckoning_seconds=args.max_dead_reckoning_seconds,
            max_dead_reckoning_distance_m=args.max_dead_reckoning_distance_m,
            pdr_profile=args.pdr_profile,
            pdr_resolution_mode=args.pdr_resolution_mode,
            pdr_heading_policy=args.pdr_heading_policy,
            reliable_course_min_speed_mps=args.reliable_course_min_speed_mps,
            include_estimates=bool(args.output_jsonl or args.include_estimates),
        )
        write_estimates_jsonl(report, args.output_jsonl.expanduser().resolve() if args.output_jsonl else None)
        if args.output_jsonl is not None and not args.include_estimates:
            report = _without_embedded_estimates(report)
        if args.output_report is not None:
            output_report = args.output_report.expanduser().resolve()
            output_report.parent.mkdir(parents=True, exist_ok=True)
            output_report.write_text(
                json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=not args.pretty))
    return 0


def _without_embedded_estimates(report: dict[str, Any]) -> dict[str, Any]:
    stripped = {**report}
    stripped["reports"] = []
    for item in report.get("reports", []):
        copied = {**item}
        copied.pop("estimates", None)
        stripped["reports"].append(copied)
    return stripped


if __name__ == "__main__":
    raise SystemExit(main())
