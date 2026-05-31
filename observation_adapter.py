from __future__ import annotations

import math
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from safety_models import Observation


class CapabilityStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNAVAILABLE_BY_PLATFORM = "unavailable_by_platform"
    UNKNOWN = "unknown"


class ObservationCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: CapabilityStatus
    reason: str
    value: Any = None


def sensorlog_payload_to_observations(
    payload: Any,
    *,
    device: str = "apple_watch",
    source: str = "live_sensorlog",
    received_at: float | None = None,
    server_signal_snapshot: dict[str, Any] | None = None,
) -> list[Observation]:
    observations = []
    for record in _records_from_payload(payload):
        if _looks_like_runtime_observation_record(record):
            observations.append(
                runtime_record_to_observation(
                    record,
                    device=device,
                    source=source,
                    received_at=received_at,
                    server_signal_snapshot=server_signal_snapshot,
                )
            )
        else:
            observations.append(
                sensorlog_record_to_observation(
                    record,
                    device=device,
                    source=source,
                    received_at=received_at,
                    server_signal_snapshot=server_signal_snapshot,
                )
            )
    return observations


def sensorlog_record_to_observation(
    record: dict[str, Any],
    *,
    device: str = "apple_watch",
    source: str = "live_sensorlog",
    received_at: float | None = None,
    server_signal_snapshot: dict[str, Any] | None = None,
) -> Observation:
    capabilities = _capabilities(record, device=device, server_signal_snapshot=server_signal_snapshot)
    timestamp = _timestamp_seconds(record, received_at=received_at)

    return Observation(
        timestamp=timestamp,
        source=source,
        lat=_to_float(record.get("locationLatitude")),
        lon=_to_float(record.get("locationLongitude")),
        elevation_m=_to_float(record.get("locationAltitude")),
        gps_horizontal_accuracy_m=_to_float(record.get("locationHorizontalAccuracy")),
        raw={
            "device": device,
            "capabilities": {name: capability.model_dump(mode="json") for name, capability in capabilities.items()},
            "sensorlog": _sensorlog_evidence(record),
            "server_signal_snapshot": server_signal_snapshot,
            "raw_payload": record,
        },
    )


def runtime_record_to_observation(
    record: dict[str, Any],
    *,
    device: str = "scout_pi",
    source: str = "runtime_provider_evidence",
    received_at: float | None = None,
    server_signal_snapshot: dict[str, Any] | None = None,
) -> Observation:
    record_raw = record.get("raw") if isinstance(record.get("raw"), dict) else {}
    raw_evidence = {**record, **record_raw}
    raw_evidence.update(
        {
            "device": device,
            "capabilities": {
                name: capability.model_dump(mode="json")
                for name, capability in _runtime_capabilities(record).items()
            },
            "server_signal_snapshot": server_signal_snapshot,
            "raw_payload": record,
        }
    )
    return Observation(
        timestamp=_runtime_timestamp_seconds(record, received_at=received_at),
        source=str(record.get("source") or source),
        lat=_runtime_lat(record),
        lon=_runtime_lon(record),
        elevation_m=_runtime_elevation_m(record),
        gps_horizontal_accuracy_m=_runtime_horizontal_accuracy_m(record),
        raw=raw_evidence,
    )


def _capabilities(
    record: dict[str, Any],
    *,
    device: str,
    server_signal_snapshot: dict[str, Any] | None,
) -> dict[str, ObservationCapability]:
    lat = _to_float(record.get("locationLatitude"))
    lon = _to_float(record.get("locationLongitude"))
    imu_fields = [
        "accelerometerAccelerationX",
        "accelerometerAccelerationY",
        "accelerometerAccelerationZ",
        "motionGravityX",
        "motionGravityY",
        "motionGravityZ",
        "motionYaw",
        "motionPitch",
        "motionRoll",
    ]
    pedometer_distance = _to_float(record.get("pedometerDistance"))
    pedometer_steps = _to_float(record.get("pedometerNumberOfSteps") or record.get("pedometerNumberofSteps"))
    heart_rate = _to_float(record.get("heartRateBPM"))

    capabilities = {
        "gps": _available_if(lat is not None and lon is not None, "locationLatitude/locationLongitude"),
        "gps_horizontal_accuracy": _available_if(
            _to_float(record.get("locationHorizontalAccuracy")) is not None,
            "locationHorizontalAccuracy",
        ),
        "imu": _available_if(any(record.get(field) not in (None, "", "null") for field in imu_fields), "IMU fields"),
        "heart_rate": _available_if(heart_rate is not None, "heartRateBPM"),
        "pedometer_distance": _available_if(pedometer_distance is not None, "pedometerDistance"),
        "pedometer_steps": _available_if(pedometer_steps is not None, "pedometerNumberOfSteps"),
        "battery": _available_if(_to_float(record.get("batteryLevel")) is not None, "batteryLevel"),
        "wifi_rssi": _platform_wifi_rssi_capability(device),
        "cellular_rssi": ObservationCapability(
            status=CapabilityStatus.UNKNOWN,
            reason="cellular RSSI is not present in the current SensorLog payload",
        ),
        "server_wifi_scan": _server_wifi_scan_capability(server_signal_snapshot),
    }
    return capabilities


def _sensorlog_evidence(record: dict[str, Any]) -> dict[str, Any]:
    fields = [
        "loggingTime",
        "locationTimestamp_since1970",
        "heartRateBPM",
        "pedometerDistance",
        "pedometerNumberOfSteps",
        "pedometerNumberofSteps",
        "pedometerCurrentPace",
        "pedometerCurrentCadence",
        "locationCourse",
        "locationTrueHeading",
        "locationMagneticHeading",
        "motionHeading",
        "batteryLevel",
        "batteryState",
        "accelerometerAccelerationX",
        "accelerometerAccelerationY",
        "accelerometerAccelerationZ",
        "motionGravityX",
        "motionGravityY",
        "motionGravityZ",
        "motionYaw",
        "motionPitch",
        "motionRoll",
    ]
    return {field: record[field] for field in fields if record.get(field) not in (None, "", "null")}


def _available_if(condition: bool, reason: str) -> ObservationCapability:
    if condition:
        return ObservationCapability(status=CapabilityStatus.AVAILABLE, reason=reason)
    return ObservationCapability(status=CapabilityStatus.UNAVAILABLE, reason=f"{reason} missing")


def _platform_wifi_rssi_capability(device: str) -> ObservationCapability:
    normalized = device.lower()
    if normalized in {"apple_watch", "watch", "iphone", "ios"}:
        return ObservationCapability(
            status=CapabilityStatus.UNAVAILABLE_BY_PLATFORM,
            reason="watchOS/iOS apps do not expose Wi-Fi RSSI for this observation path",
        )
    return ObservationCapability(
        status=CapabilityStatus.UNKNOWN,
        reason="Wi-Fi RSSI availability is unknown for this device",
    )


def _server_wifi_scan_capability(server_signal_snapshot: dict[str, Any] | None) -> ObservationCapability:
    if server_signal_snapshot:
        return ObservationCapability(
            status=CapabilityStatus.AVAILABLE,
            reason="server-side Wi-Fi scan snapshot attached",
            value=server_signal_snapshot,
        )
    return ObservationCapability(
        status=CapabilityStatus.UNKNOWN,
        reason="server-side Wi-Fi scan snapshot was not attached",
    )


def _runtime_capabilities(record: dict[str, Any]) -> dict[str, ObservationCapability]:
    return {
        "gps": _available_if(_runtime_lat(record) is not None and _runtime_lon(record) is not None, "runtime GNSS lat/lon"),
        "gps_horizontal_accuracy": _available_if(
            _runtime_horizontal_accuracy_m(record) is not None,
            "runtime GNSS horizontal accuracy",
        ),
        "dead_reckoning_delta": _available_if(
            _runtime_distance_delta_m(record) is not None,
            "runtime distance_delta_m",
        ),
        "heading": _available_if(
            _runtime_heading_deg(record) is not None,
            "runtime heading_deg",
        ),
    }


def _records_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        imu_data = payload.get("imu_data")
        if isinstance(imu_data, list):
            return [item for item in imu_data if isinstance(item, dict)]
        observations = payload.get("observations")
        if isinstance(observations, list):
            return [item for item in observations if isinstance(item, dict)]
        payloads = payload.get("payloads")
        if isinstance(payloads, list):
            return [item for item in payloads if isinstance(item, dict)]
        return [payload]
    raise ValueError("SensorLog payload must be a dict, list, or dict with imu_data list")


def _looks_like_runtime_observation_record(record: dict[str, Any]) -> bool:
    if isinstance(record.get("position"), dict):
        return True
    if isinstance(record.get("odometry"), dict) or isinstance(record.get("dr"), dict):
        return True
    if any(key in record for key in ("timestamp_s", "distance_delta_m", "heading_deg", "sentence_type")):
        return True
    if any(key in record for key in ("lat", "lon", "latitude", "longitude")):
        return True
    return False


def _timestamp_seconds(record: dict[str, Any], *, received_at: float | None) -> float:
    since_1970 = _to_float(record.get("locationTimestamp_since1970"))
    if since_1970 is not None and since_1970 > 0:
        return since_1970

    raw = record.get("loggingTime") or record.get("heartRateBPMTimestamp")
    if isinstance(raw, str) and raw and raw != "null":
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()
        except ValueError:
            pass

    return received_at if received_at is not None else 0.0


def _runtime_timestamp_seconds(record: dict[str, Any], *, received_at: float | None) -> float:
    for key in ("timestamp_s", "timestamp", "loggingTimestamp_s"):
        value = _to_float(record.get(key))
        if value is not None:
            return value

    for key in ("captured_at", "observed_at", "received_at"):
        raw = record.get(key)
        if isinstance(raw, str) and raw and raw != "null":
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()
            except ValueError:
                pass
    return received_at if received_at is not None else 0.0


def _runtime_lat(record: dict[str, Any]) -> float | None:
    position = record.get("position") if isinstance(record.get("position"), dict) else {}
    return _first_float(record, position, keys=("lat", "latitude"))


def _runtime_lon(record: dict[str, Any]) -> float | None:
    position = record.get("position") if isinstance(record.get("position"), dict) else {}
    return _first_float(record, position, keys=("lon", "longitude"))


def _runtime_elevation_m(record: dict[str, Any]) -> float | None:
    position = record.get("position") if isinstance(record.get("position"), dict) else {}
    return _first_float(record, position, keys=("elevation_m", "altitude_m", "altitude"))


def _runtime_horizontal_accuracy_m(record: dict[str, Any]) -> float | None:
    position = record.get("position") if isinstance(record.get("position"), dict) else {}
    value = _first_float(
        record,
        position,
        keys=("horizontal_accuracy_m", "gps_horizontal_accuracy_m", "accuracy_m"),
    )
    if value is not None:
        return value

    fix_quality = record.get("fix_quality") if isinstance(record.get("fix_quality"), dict) else {}
    hdop = _to_float(fix_quality.get("hdop"))
    return hdop * 5.0 if hdop is not None else None


def _runtime_distance_delta_m(record: dict[str, Any]) -> float | None:
    odometry = record.get("odometry") if isinstance(record.get("odometry"), dict) else {}
    dr = record.get("dr") if isinstance(record.get("dr"), dict) else {}
    return _first_float(record, odometry, dr, keys=("distance_delta_m",))


def _runtime_heading_deg(record: dict[str, Any]) -> float | None:
    odometry = record.get("odometry") if isinstance(record.get("odometry"), dict) else {}
    dr = record.get("dr") if isinstance(record.get("dr"), dict) else {}
    return _first_float(record, odometry, dr, keys=("heading_deg", "motionHeading", "locationCourse"))


def _first_float(*mappings: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for mapping in mappings:
        for key in keys:
            value = _to_float(mapping.get(key))
            if value is not None:
                return value
    return None


def _to_float(value: Any) -> float | None:
    if value in (None, "", "null"):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result
