from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ins_dr_navigation import DeadReckoningDelta, GnssFix, InsDrEstimate, VendorFusionEstimate
from pdr_fallback import PositionEstimate
from route_matching import RoutePoint


@dataclass
class InsDrInputState:
    last_cumulative_distance_m: float | None = None
    last_cumulative_steps: int | None = None
    last_heading_deg: float | None = None


def gnss_fix_from_payload(
    payload: dict[str, Any],
    *,
    fallback_timestamp_s: float,
    hdop_accuracy_scale_m: float = 5.0,
) -> GnssFix | None:
    source = str(payload.get("source") or "")
    primary_truth_scope = str(payload.get("primary_truth_scope") or "")
    sentence_type = str(payload.get("sentence_type") or "")
    if (
        "gnss" not in source.lower()
        and "gps" not in source.lower()
        and sentence_type[-3:] not in {"GGA", "RMC"}
        and primary_truth_scope != "raw_gnss_observation_only"
    ):
        return None

    position = payload.get("position") if isinstance(payload.get("position"), dict) else {}
    fix_quality = payload.get("fix_quality") if isinstance(payload.get("fix_quality"), dict) else {}
    lat = _float_or_none(position.get("lat"))
    lon = _float_or_none(position.get("lon"))
    if sentence_type and sentence_type[-3:] not in {"GGA", "RMC"}:
        return None
    if payload.get("checksum_valid") is False:
        return None

    timestamp_s = _timestamp_s(payload, fallback_timestamp_s=fallback_timestamp_s)
    horizontal_accuracy = _horizontal_accuracy_m(payload, fix_quality, hdop_accuracy_scale_m)
    quality = _int_or_none(fix_quality.get("quality"))
    status = fix_quality.get("status")
    satellites = _int_or_none(fix_quality.get("satellites"))
    return GnssFix(
        timestamp_s=timestamp_s,
        lat=lat,
        lon=lon,
        horizontal_accuracy_m=horizontal_accuracy,
        fix_quality=quality,
        status=str(status) if status not in (None, "") else None,
        satellite_count=satellites,
        max_cno_dbhz=_float_or_none(payload.get("max_cno_dbhz")),
        raw_evidence_ref=_raw_evidence_ref(payload, fallback=f"gnss:{sentence_type or 'unknown'}:{fallback_timestamp_s:g}"),
    )


def dead_reckoning_delta_from_payload(
    payload: dict[str, Any],
    state: InsDrInputState,
    *,
    fallback_timestamp_s: float,
    default_step_length_m: float = 0.75,
) -> DeadReckoningDelta | None:
    heading = _heading_deg(payload)
    if heading is not None:
        state.last_heading_deg = heading

    direct_delta = _float_or_none(payload.get("distance_delta_m"))
    if direct_delta is not None:
        return DeadReckoningDelta(
            timestamp_s=_timestamp_s(payload, fallback_timestamp_s=fallback_timestamp_s),
            distance_delta_m=max(0.0, direct_delta),
            heading_deg=_heading_deg(payload, default=state.last_heading_deg),
            raw_evidence_ref=_raw_evidence_ref(payload, fallback=f"dr_delta:{fallback_timestamp_s:g}"),
            source=str(payload.get("source") or "raw_odometry_delta"),
        )

    sensorlog = payload.get("sensorlog") if isinstance(payload.get("sensorlog"), dict) else payload
    cumulative_distance = _float_or_none(sensorlog.get("pedometerDistance") or sensorlog.get("distance_m"))
    if cumulative_distance is not None:
        previous = state.last_cumulative_distance_m
        state.last_cumulative_distance_m = cumulative_distance
        if previous is None:
            return None
        delta = cumulative_distance - previous
        if delta <= 0:
            return None
        return DeadReckoningDelta(
            timestamp_s=_timestamp_s(sensorlog, fallback_timestamp_s=fallback_timestamp_s),
            distance_delta_m=delta,
            heading_deg=_heading_deg(sensorlog, default=state.last_heading_deg),
            raw_evidence_ref=_raw_evidence_ref(payload, fallback=f"sensorlog:pedometerDistance:{fallback_timestamp_s:g}"),
            source="sensorlog_pedometer_distance",
        )

    cumulative_steps = _int_or_none(
        sensorlog.get("pedometerNumberOfSteps")
        or sensorlog.get("pedometerNumberofSteps")
        or sensorlog.get("steps")
    )
    if cumulative_steps is not None:
        previous = state.last_cumulative_steps
        state.last_cumulative_steps = cumulative_steps
        if previous is None:
            return None
        delta_steps = cumulative_steps - previous
        if delta_steps <= 0:
            return None
        return DeadReckoningDelta(
            timestamp_s=_timestamp_s(sensorlog, fallback_timestamp_s=fallback_timestamp_s),
            distance_delta_m=delta_steps * default_step_length_m,
            heading_deg=_heading_deg(sensorlog, default=state.last_heading_deg),
            raw_evidence_ref=_raw_evidence_ref(payload, fallback=f"sensorlog:pedometerSteps:{fallback_timestamp_s:g}"),
            source="sensorlog_pedometer_steps",
        )

    return None


def vendor_fusion_from_payload(
    payload: dict[str, Any],
    *,
    fallback_timestamp_s: float,
) -> VendorFusionEstimate | None:
    if not _looks_like_vendor_fusion(payload):
        return None
    position = payload.get("position") if isinstance(payload.get("position"), dict) else payload
    lat = _float_or_none(position.get("lat") or position.get("latitude"))
    lon = _float_or_none(position.get("lon") or position.get("longitude"))
    return VendorFusionEstimate(
        timestamp_s=_timestamp_s(payload, fallback_timestamp_s=fallback_timestamp_s),
        lat=lat,
        lon=lon,
        horizontal_accuracy_m=_float_or_none(
            position.get("horizontal_accuracy_m")
            or position.get("accuracy_m")
            or payload.get("horizontal_accuracy_m")
        ),
        raw_evidence_ref=_raw_evidence_ref(payload, fallback=f"vendor_fusion:{fallback_timestamp_s:g}"),
    )


def gnss_fix_from_route_point(
    *,
    timestamp_s: float,
    point: RoutePoint,
    raw_evidence_ref: str | None = None,
) -> GnssFix:
    return GnssFix(
        timestamp_s=timestamp_s,
        lat=point.lat,
        lon=point.lon,
        horizontal_accuracy_m=point.gps_horizontal_accuracy_m,
        fix_quality=1,
        status="A",
        raw_evidence_ref=raw_evidence_ref,
    )


def dead_reckoning_delta_from_route_point(
    *,
    timestamp_s: float,
    point: RoutePoint,
    state: InsDrInputState,
    default_step_length_m: float = 0.75,
    raw_evidence_ref: str | None = None,
) -> DeadReckoningDelta | None:
    payload: dict[str, Any] = {
        "timestamp_s": timestamp_s,
        "source": "route_point_pdr_evidence",
        "raw_evidence_ref": raw_evidence_ref,
    }
    if point.pedometer_distance_m is not None:
        payload["pedometerDistance"] = point.pedometer_distance_m
    elif point.pedometer_steps is not None:
        payload["pedometerNumberOfSteps"] = point.pedometer_steps
    else:
        return None
    return dead_reckoning_delta_from_payload(
        payload,
        state,
        fallback_timestamp_s=timestamp_s,
        default_step_length_m=default_step_length_m,
    )


def position_estimate_from_ins_dr(estimate: InsDrEstimate) -> PositionEstimate:
    if estimate.progress_m is None or estimate.route_index is None:
        return PositionEstimate(
            source=estimate.source,
            progress_m=0.0,
            route_index=0,
            route_distance_m=estimate.route_distance_m or 0.0,
            confidence=estimate.confidence,
            gps_horizontal_accuracy_m=estimate.gnss_horizontal_accuracy_m,
            pdr_delta_m=estimate.dr_distance_since_anchor_m,
            gps_reanchor_correction_m=estimate.gps_reanchor_correction_m,
        )
    return PositionEstimate(
        source=estimate.source,
        progress_m=estimate.progress_m,
        route_index=estimate.route_index,
        route_distance_m=estimate.route_distance_m or 0.0,
        confidence=estimate.confidence,
        gps_horizontal_accuracy_m=estimate.gnss_horizontal_accuracy_m,
        pdr_delta_m=estimate.dr_distance_since_anchor_m,
        gps_reanchor_correction_m=estimate.gps_reanchor_correction_m,
    )


def _looks_like_vendor_fusion(payload: dict[str, Any]) -> bool:
    source = str(payload.get("source") or "")
    mode = str(payload.get("vendor_fusion_mode_observed") or "")
    return (
        "vendor_fusion" in source
        or mode in {"imu_and_vendor_fused", "imu_with_gps_fields", "vendor_fused_only"}
        or payload.get("vendor_fusion") is True
    )


def _heading_deg(payload: dict[str, Any], default: float | None = None) -> float | None:
    for key in ("heading_deg", "motionHeading", "locationCourse", "locationTrueHeading", "locationMagneticHeading"):
        value = _float_or_none(payload.get(key))
        if value is not None and value >= 0:
            return value % 360.0

    parsed = payload.get("parsed") if isinstance(payload.get("parsed"), dict) else {}
    angle = parsed.get("angle_deg")
    if isinstance(angle, (list, tuple)) and len(angle) >= 3:
        if _requires_raw_imu_checksum(payload) and _payload_checksum_valid(payload, parsed) is not True:
            return default
        yaw = _float_or_none(angle[2])
        if yaw is not None:
            return yaw % 360.0
    return default


def _requires_raw_imu_checksum(payload: dict[str, Any]) -> bool:
    source = str(payload.get("source") or "").lower()
    hardware_kind = str(payload.get("hardware_kind") or "").lower()
    frame_type = str(payload.get("frame_type") or "").lower()
    return (
        "hiwonder" in source
        or "wit" in source
        or "hiwonder" in hardware_kind
        or "wit" in hardware_kind
        or frame_type in {"acceleration", "gyro", "angle"}
        or payload.get("raw_imu_present") is True
    )


def _payload_checksum_valid(payload: dict[str, Any], parsed: dict[str, Any]) -> bool | None:
    if "checksum_valid" in payload:
        return payload.get("checksum_valid") is True
    if "checksum_valid" in parsed:
        return parsed.get("checksum_valid") is True
    return None


def _horizontal_accuracy_m(
    payload: dict[str, Any],
    fix_quality: dict[str, Any],
    hdop_accuracy_scale_m: float,
) -> float | None:
    for key in ("horizontal_accuracy_m", "gps_horizontal_accuracy_m", "locationHorizontalAccuracy"):
        value = _float_or_none(payload.get(key))
        if value is not None:
            return value
    hdop = _float_or_none(fix_quality.get("hdop"))
    if hdop is None:
        return None
    return hdop * hdop_accuracy_scale_m


def _timestamp_s(payload: dict[str, Any], *, fallback_timestamp_s: float) -> float:
    for key in ("timestamp_s", "timestamp", "motionTimestamp_sinceReboot", "loggingTimestamp_s"):
        value = _float_or_none(payload.get(key))
        if value is not None:
            return value

    logging_time = payload.get("loggingTime")
    if isinstance(logging_time, str):
        parsed = _parse_datetime_s(logging_time)
        if parsed is not None:
            return parsed

    captured_at = payload.get("captured_at")
    if isinstance(captured_at, str):
        parsed = _parse_datetime_s(captured_at)
        if parsed is not None:
            return parsed

    return fallback_timestamp_s


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


def _raw_evidence_ref(payload: dict[str, Any], *, fallback: str) -> str:
    for key in ("raw_evidence_ref", "evidence_ref", "raw_path", "raw_bytes_hex", "raw_sentence"):
        value = payload.get(key)
        if value not in (None, ""):
            return str(value)
    return fallback


def _float_or_none(value: Any) -> float | None:
    if value in (None, "", "null"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    parsed = _float_or_none(value)
    return int(parsed) if parsed is not None else None
