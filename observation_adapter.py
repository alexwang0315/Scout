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
    return [
        sensorlog_record_to_observation(
            record,
            device=device,
            source=source,
            received_at=received_at,
            server_signal_snapshot=server_signal_snapshot,
        )
        for record in _records_from_payload(payload)
    ]


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


def _records_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        imu_data = payload.get("imu_data")
        if isinstance(imu_data, list):
            return [item for item in imu_data if isinstance(item, dict)]
        return [payload]
    raise ValueError("SensorLog payload must be a dict, list, or dict with imu_data list")


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
