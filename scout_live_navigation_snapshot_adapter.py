from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from scout_live_navigation_state_tool import LIVE_NAVIGATION_REQUIRED_FIELDS


LIVE_NAVIGATION_SNAPSHOT_ADAPTER_ID = (
    "scout.ai.live_navigation_snapshot_adapter.normalized_sensor_records.v0"
)

_ALLOWED_FIELDS = set(LIVE_NAVIGATION_REQUIRED_FIELDS)


def live_navigation_snapshot_from_sensor_records(
    records: Iterable[dict[str, Any]],
    *,
    default_source: str = "normalized_sensor_records",
) -> dict[str, Any]:
    """Project normalized sensor/MQTT-like records into the assistant snapshot contract."""

    snapshot: dict[str, Any] = {}
    saw_record = False
    saw_ins_dr_record = False

    for record in records:
        if not isinstance(record, dict):
            continue
        for sample in _iter_samples(record):
            saw_record = True
            sample_kind = _sample_kind(sample)
            if sample_kind in {"pdr", "imu", "ins_dr"}:
                saw_ins_dr_record = True
            _merge_sample(snapshot, sample, sample_kind=sample_kind)

    if saw_record and "source" not in snapshot:
        snapshot["source"] = default_source
    if saw_ins_dr_record and "ins_dr_source" not in snapshot:
        snapshot["ins_dr_source"] = default_source

    return _bounded_snapshot(snapshot)


def _iter_samples(record: dict[str, Any]) -> list[dict[str, Any]]:
    payload = record.get("payload")
    if isinstance(payload, dict) and isinstance(payload.get("payload"), list):
        return _sensorlogger_samples(payload, envelope=record)
    if isinstance(payload, list):
        return _sensorlogger_samples(record, envelope=record)

    if isinstance(payload, dict):
        return [_merged_payload_sample(record, payload)]

    data = record.get("data")
    if isinstance(data, dict):
        return [_merged_payload_sample(record, data)]

    values = record.get("values")
    if isinstance(values, dict):
        return [_merged_payload_sample(record, values)]

    return [dict(record)]


def _sensorlogger_samples(
    message: dict[str, Any],
    *,
    envelope: dict[str, Any],
) -> list[dict[str, Any]]:
    readings = message.get("payload")
    if not isinstance(readings, list):
        return []
    samples: list[dict[str, Any]] = []
    for index, reading in enumerate(readings):
        if not isinstance(reading, dict):
            continue
        values = reading.get("values") if isinstance(reading.get("values"), dict) else {}
        sample = {
            "topic": envelope.get("topic"),
            "source_adapter": envelope.get("source_adapter"),
            "ingress_transport": envelope.get("ingress_transport"),
            "device_id": message.get("deviceId") or envelope.get("device_id"),
            "session_id": message.get("sessionId") or envelope.get("session_id"),
            "message_id": message.get("messageId") or envelope.get("message_id"),
            "payload_index": index,
            "name": reading.get("name"),
            "time": reading.get("time"),
            "received_at": envelope.get("received_at") or message.get("received_at"),
            **values,
        }
        samples.append(sample)
    return samples


def _merged_payload_sample(record: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    sample: dict[str, Any] = {}
    for key, value in record.items():
        if key in {"payload", "data", "values", "raw_payload", "raw_nmea"}:
            continue
        sample[key] = value
    sample.update(payload)
    return sample


def _merge_sample(
    snapshot: dict[str, Any],
    sample: dict[str, Any],
    *,
    sample_kind: str,
) -> None:
    nested_gnss = _dict_or_empty(sample.get("gnss_fix"))
    nested_ins_dr = _dict_or_empty(sample.get("ins_dr")) or _dict_or_empty(
        sample.get("ins_dr_snapshot")
    )
    nested_route_match = _dict_or_empty(sample.get("route_match"))
    nested_position = _dict_or_empty(sample.get("position"))
    application_output = _dict_or_empty(sample.get("output_summary"))

    _copy_first(
        snapshot,
        "observed_at",
        sample,
        nested_gnss,
        nested_ins_dr,
        keys=("observed_at", "timestamp", "captured_at", "gnss_time_utc", "time"),
        transform=_timestamp_or_text,
    )
    _copy_first(
        snapshot,
        "lat",
        sample,
        nested_gnss,
        nested_position,
        keys=("lat", "latitude", "locationLatitude"),
    )
    _copy_first(
        snapshot,
        "lon",
        sample,
        nested_gnss,
        nested_position,
        keys=("lon", "lng", "longitude", "locationLongitude"),
    )
    _copy_first(
        snapshot,
        "elevation_m",
        sample,
        nested_gnss,
        keys=("elevation_m", "altitude_m", "altitude", "locationAltitude"),
    )
    _copy_first(
        snapshot,
        "hdop",
        sample,
        nested_gnss,
        keys=("hdop",),
    )
    _copy_first(
        snapshot,
        "horizontal_accuracy_m",
        sample,
        nested_gnss,
        application_output,
        keys=(
            "horizontal_accuracy_m",
            "accuracy_m",
            "h_acc_m",
            "accuracy",
            "horizontalAccuracy",
            "locationHorizontalAccuracy",
            "gnss_horizontal_accuracy_m",
        ),
    )
    fix_sources = (
        (sample, nested_gnss) if sample_kind in {"gnss", "generic"} else (nested_gnss,)
    )
    _copy_first(
        snapshot,
        "fix_quality",
        *fix_sources,
        keys=("fix_quality", "quality", "fix", "fix_status", "status"),
        transform=_fix_quality_text,
    )
    if "fix_quality" not in snapshot:
        valid = _first_present(sample, nested_gnss, keys=("valid",))
        if valid is not None:
            snapshot["fix_quality"] = "valid" if bool(valid) else "invalid"
    _copy_first(
        snapshot,
        "satellite_count",
        sample,
        nested_gnss,
        keys=("satellite_count", "satellites", "num_sats", "numSat", "num_sv"),
    )
    _copy_first(
        snapshot,
        "max_cno_dbhz",
        sample,
        nested_gnss,
        keys=("max_cno_dbhz", "max_cno", "cno"),
        transform=_cno_value,
    )
    _copy_first(
        snapshot,
        "heading_deg",
        sample,
        nested_gnss,
        nested_ins_dr,
        keys=("heading_deg", "heading", "yaw_deg", "yaw"),
    )
    _copy_first(
        snapshot,
        "course_deg",
        sample,
        nested_gnss,
        keys=("course_deg", "course", "locationCourse"),
    )
    _copy_first(
        snapshot,
        "speed_mps",
        sample,
        nested_gnss,
        keys=("speed_mps", "speed"),
    )
    _copy_first(
        snapshot,
        "speed_mps",
        sample,
        nested_gnss,
        keys=("speed_kmh",),
        transform=_kmh_to_mps,
    )
    _copy_first(
        snapshot,
        "nearest_route_distance_m",
        sample,
        nested_route_match,
        keys=(
            "nearest_route_distance_m",
            "distance_to_route_m",
            "cross_track_error_m",
            "route_offset_m",
        ),
    )
    _copy_first(
        snapshot,
        "route_progress_m",
        sample,
        nested_route_match,
        nested_ins_dr,
        application_output,
        keys=("route_progress_m", "progress_m"),
    )
    _copy_first(
        snapshot,
        "nearest_cp_id",
        sample,
        nested_route_match,
        keys=("nearest_cp_id", "nearest_cp_candidate_id", "cp_id", "checkpoint_id"),
    )
    _copy_first(
        snapshot,
        "confidence",
        sample,
        nested_ins_dr,
        application_output,
        keys=("confidence",),
    )
    _copy_first(
        snapshot,
        "uncertainty_m",
        sample,
        nested_gnss,
        nested_ins_dr,
        application_output,
        keys=("uncertainty_m", "estimated_error_m", "position_uncertainty_m"),
    )
    _copy_first(
        snapshot,
        "last_anchor_at",
        sample,
        nested_ins_dr,
        application_output,
        keys=("last_anchor_at", "last_gps_anchor_at", "last_gnss_anchor_at"),
        transform=_timestamp_or_text,
    )
    _copy_first(
        snapshot,
        "ins_dr_source",
        nested_ins_dr,
        application_output,
        keys=("ins_dr_source", "source", "estimate_source", "primary_truth_source"),
    )

    source_value = (
        _ins_dr_source_value(sample)
        if sample_kind in {"pdr", "imu", "ins_dr"}
        else _source_value(sample)
    )
    if source_value is not None:
        if sample_kind in {"pdr", "imu", "ins_dr"}:
            snapshot["ins_dr_source"] = source_value
        elif "source" not in snapshot:
            snapshot["source"] = source_value


def _sample_kind(sample: dict[str, Any]) -> str:
    text_parts = [
        sample.get("topic"),
        sample.get("name"),
        sample.get("observation_name"),
        sample.get("source"),
        sample.get("source_adapter"),
        sample.get("output_kind"),
        sample.get("route_target"),
        sample.get("route_id"),
    ]
    tags = sample.get("capability_tags")
    if isinstance(tags, (list, tuple, set)):
        text_parts.extend(str(tag) for tag in tags)
    text = " ".join(str(part).lower() for part in text_parts if part is not None)
    keys = {str(key).lower() for key in sample}
    if "ins_dr" in text or "navigation_estimate" in text:
        return "ins_dr"
    if "pdr" in text or "pedometer" in text or keys.intersection(
        {"pedometerdistance", "pedometernumberofsteps", "distance_m", "steps"}
    ):
        return "pdr"
    if "imu" in text or keys.intersection({"acc_x", "acc_y", "acc_z", "gyro_x"}):
        return "imu"
    if "gnss" in text or "gps" in text or "location" in text or keys.intersection(
        {"lat", "latitude", "locationlatitude"}
    ):
        return "gnss"
    if "route_match" in text or keys.intersection({"nearest_cp_id", "route_progress_m"}):
        return "route_match"
    return "generic"


def _copy_first(
    target: dict[str, Any],
    target_key: str,
    *sources: dict[str, Any],
    keys: tuple[str, ...],
    transform: Any | None = None,
) -> None:
    for source in sources:
        for key in keys:
            value = source.get(key)
            if _missing(value):
                continue
            parsed = transform(value) if transform is not None else value
            if _missing(parsed):
                continue
            target[target_key] = parsed
            return


def _first_present(*sources: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for source in sources:
        for key in keys:
            value = source.get(key)
            if not _missing(value):
                return value
    return None


def _source_value(sample: dict[str, Any]) -> str | None:
    for key in ("ins_dr_source", "source", "source_adapter", "topic", "observation_name", "name"):
        value = sample.get(key)
        if _missing(value):
            continue
        return str(value)
    return None


def _ins_dr_source_value(sample: dict[str, Any]) -> str | None:
    for key in ("ins_dr_source", "source", "name", "observation_name", "source_adapter", "topic"):
        value = sample.get(key)
        if _missing(value):
            continue
        return str(value)
    return None


def _bounded_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    bounded: dict[str, Any] = {}
    for key in LIVE_NAVIGATION_REQUIRED_FIELDS:
        value = snapshot.get(key)
        if _missing(value) or not _is_scalar(value):
            continue
        bounded[key] = value
    return {key: value for key, value in bounded.items() if key in _ALLOWED_FIELDS}


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return not value
    return False


def _is_scalar(value: Any) -> bool:
    return isinstance(value, (str, int, float, bool))


def _timestamp_or_text(value: Any) -> str | None:
    if _missing(value):
        return None
    if isinstance(value, (int, float)):
        timestamp_s = float(value)
        if timestamp_s > 1_000_000_000_000_000:
            timestamp_s = timestamp_s / 1_000_000_000.0
        elif timestamp_s > 1_000_000_000_000:
            timestamp_s = timestamp_s / 1000.0
        try:
            return datetime.fromtimestamp(timestamp_s, tz=timezone.utc).isoformat().replace(
                "+00:00",
                "Z",
            )
        except (OSError, OverflowError, ValueError):
            return str(value)
    return str(value)


def _fix_quality_text(value: Any) -> str | None:
    if _missing(value):
        return None
    if isinstance(value, bool):
        return "valid" if value else "invalid"
    return str(value)


def _cno_value(value: Any) -> Any:
    if isinstance(value, list):
        numeric = [_float_or_none(item) for item in value]
        numeric = [item for item in numeric if item is not None]
        return max(numeric) if numeric else None
    return value


def _kmh_to_mps(value: Any) -> float | None:
    numeric = _float_or_none(value)
    if numeric is None:
        return None
    return numeric / 3.6


def _float_or_none(value: Any) -> float | None:
    if _missing(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
