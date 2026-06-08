"""Boundary-tagged hardware and mobile evidence artifacts for Scout AI OS."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping
from uuid import uuid4

from pydantic import Field

from scout.schemas.base import NonEmptyStr, SchemaModel


HardwareEvidenceSourceKind = Literal[
    "mobile_sensor",
    "wearable_sensor",
    "gnss",
    "imu",
    "wheel",
    "host_probe",
    "manual_probe",
    "other",
]

SAFE_HARDWARE_EVIDENCE_BOUNDARY: dict[str, bool] = {
    "advisory_only": True,
    "not_safety_truth": True,
    "hardware_control_allowed": False,
    "hardware_control_performed": False,
    "provider_control_allowed": False,
    "outbound_send_allowed": False,
    "outbound_sent": False,
    "phase1_l0_l4_state_mutation_allowed": False,
    "phase1_l0_l4_state_mutated": False,
    "phase1_runtime_safety_truth": False,
    "phase1_runtime_mutated": False,
    "safety_api_mutation_allowed": False,
    "safety_api_called": False,
    "runtime_ingest_performed": False,
    "provider_values_are_scout_truth": False,
    "generated_runtime_code_install_allowed": False,
}

_FORBIDDEN_TRUE_KEYS = {
    key
    for key, value in SAFE_HARDWARE_EVIDENCE_BOUNDARY.items()
    if value is False and key not in {"advisory_only", "not_safety_truth"}
}


class HardwareEvidenceSample(SchemaModel):
    """One source sample captured before Scout runtime promotion."""

    sample_id: NonEmptyStr = Field(default_factory=lambda: f"sample-{uuid4()}")
    source_kind: HardwareEvidenceSourceKind
    captured_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    values: dict[str, Any] = Field(default_factory=dict)
    units: dict[str, str] = Field(default_factory=dict)
    quality: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)


class HardwareEvidenceArtifact(SchemaModel):
    """Smoke-attachable evidence that cannot promote values into runtime truth."""

    artifact_kind: Literal["scout_hardware_evidence.v0"] = "scout_hardware_evidence.v0"
    artifact_id: NonEmptyStr = Field(default_factory=lambda: f"hardware-evidence-{uuid4()}")
    produced_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    source: NonEmptyStr
    source_device_id: str | None = None
    samples: list[HardwareEvidenceSample]
    boundary: dict[str, bool] = Field(
        default_factory=lambda: dict(SAFE_HARDWARE_EVIDENCE_BOUNDARY)
    )
    notes: list[str] = Field(default_factory=list)

    def assert_safe_boundary(self) -> None:
        assert_safe_hardware_evidence_boundary(self.boundary)


class HardwareEvidenceDirectoryEntry(SchemaModel):
    """Index entry for one advisory hardware evidence artifact."""

    artifact_id: NonEmptyStr
    source: NonEmptyStr
    artifact_path: NonEmptyStr
    source_device_id: str | None = None
    produced_at: str
    sample_count: int


class HardwareEvidenceDirectoryArtifact(SchemaModel):
    """Directory index for mobile, GNSS, wearable, and host-probe artifacts."""

    artifact_kind: Literal[
        "scout_hardware_evidence_directory.v0"
    ] = "scout_hardware_evidence_directory.v0"
    directory_id: NonEmptyStr = Field(default_factory=lambda: f"hardware-evidence-dir-{uuid4()}")
    produced_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    root: NonEmptyStr
    entries: list[HardwareEvidenceDirectoryEntry]
    boundary: dict[str, bool] = Field(
        default_factory=lambda: dict(SAFE_HARDWARE_EVIDENCE_BOUNDARY)
    )
    notes: list[str] = Field(default_factory=list)

    def assert_safe_boundary(self) -> None:
        assert_safe_hardware_evidence_boundary(self.boundary)


def build_hardware_evidence(
    *,
    source: str,
    samples: list[HardwareEvidenceSample | dict[str, Any]],
    source_device_id: str | None = None,
    boundary_overrides: dict[str, bool] | None = None,
    notes: list[str] | None = None,
) -> HardwareEvidenceArtifact:
    """Build a Scout hardware evidence artifact with safe boundary metadata."""

    boundary = _safe_boundary(boundary_overrides)
    artifact = HardwareEvidenceArtifact(
        source=source,
        source_device_id=source_device_id,
        samples=[
            sample
            if isinstance(sample, HardwareEvidenceSample)
            else HardwareEvidenceSample.model_validate(sample)
            for sample in samples
        ],
        boundary=boundary,
        notes=list(notes or []),
    )
    artifact.assert_safe_boundary()
    return artifact


def sensor_logger_rows_to_samples(
    rows: Iterable[Mapping[str, Any]],
    *,
    source_kind: HardwareEvidenceSourceKind = "mobile_sensor",
) -> list[HardwareEvidenceSample]:
    """Convert Sensor Logger style rows into Scout advisory evidence samples."""

    samples: list[HardwareEvidenceSample] = []
    for index, row in enumerate(rows):
        values = _compact(
            {
                "lat": _float_from_keys(row, "latitude", "locationLatitude", "lat"),
                "lon": _float_from_keys(row, "longitude", "locationLongitude", "lon"),
                "altitude_m": _float_from_keys(row, "altitude", "locationAltitude"),
                "accuracy_m": _float_from_keys(
                    row, "horizontalAccuracy", "locationHorizontalAccuracy", "accuracy_m"
                ),
                "speed_mps": _float_from_keys(row, "speed", "locationSpeed"),
                "course_deg": _float_from_keys(row, "course", "locationCourse"),
                "accel_x": _float_from_keys(
                    row, "accelerometerAccelerationX", "accelerationX", "accel_x"
                ),
                "accel_y": _float_from_keys(
                    row, "accelerometerAccelerationY", "accelerationY", "accel_y"
                ),
                "accel_z": _float_from_keys(
                    row, "accelerometerAccelerationZ", "accelerationZ", "accel_z"
                ),
                "gyro_x": _float_from_keys(row, "gyroRotationX", "rotationRateX", "gyro_x"),
                "gyro_y": _float_from_keys(row, "gyroRotationY", "rotationRateY", "gyro_y"),
                "gyro_z": _float_from_keys(row, "gyroRotationZ", "rotationRateZ", "gyro_z"),
                "heart_rate_bpm": _float_from_keys(row, "heartRate", "heart_rate_bpm"),
            }
        )
        quality = _compact(
            {
                "fix": row.get("fix") or row.get("locationFix"),
                "horizontal_accuracy_m": values.get("accuracy_m"),
                "row_index": index,
            }
        )
        provenance = _compact(
            {
                "producer": "sensor_logger",
                "raw_timestamp": row.get("time") or row.get("timestamp"),
                "source_format": "sensor_logger_row",
            }
        )
        samples.append(
            HardwareEvidenceSample(
                source_kind=source_kind,
                captured_at=str(
                    row.get("timestamp")
                    or row.get("time")
                    or row.get("date")
                    or datetime.now(UTC).isoformat()
                ),
                values=values,
                units={
                    "altitude_m": "m",
                    "accuracy_m": "m",
                    "speed_mps": "m/s",
                    "course_deg": "deg",
                    "accel_x": "m/s^2",
                    "accel_y": "m/s^2",
                    "accel_z": "m/s^2",
                    "gyro_x": "rad/s",
                    "gyro_y": "rad/s",
                    "gyro_z": "rad/s",
                    "heart_rate_bpm": "bpm",
                },
                quality=quality,
                provenance=provenance,
            )
        )
    return samples


def sensor_logger_json_to_samples(
    payload: Any,
    *,
    source_kind: HardwareEvidenceSourceKind = "mobile_sensor",
) -> list[HardwareEvidenceSample]:
    """Load Sensor Logger rows from a JSON list or wrapper object."""

    rows: Any
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = (
            payload.get("samples")
            or payload.get("rows")
            or payload.get("data")
            or payload.get("measurements")
        )
    else:
        rows = None
    if not isinstance(rows, list):
        raise ValueError("Sensor Logger JSON must contain a row list")
    return sensor_logger_rows_to_samples(rows, source_kind=source_kind)


def nmea_lines_to_samples(lines: Iterable[str]) -> list[HardwareEvidenceSample]:
    """Convert GGA/RMC NMEA sentences into advisory GNSS evidence samples."""

    samples: list[HardwareEvidenceSample] = []
    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line or not line.startswith("$"):
            continue
        sentence = line.split("*", 1)[0]
        parts = sentence.split(",")
        sentence_type = parts[0][-3:]
        if sentence_type == "GGA" and len(parts) >= 10:
            lat = _nmea_coordinate(parts[2], parts[3])
            lon = _nmea_coordinate(parts[4], parts[5])
            values = _compact(
                {
                    "lat": lat,
                    "lon": lon,
                    "fix_quality": _int_or_none(parts[6]),
                    "satellite_count": _int_or_none(parts[7]),
                    "hdop": _float_or_none(parts[8]),
                    "altitude_m": _float_or_none(parts[9]),
                }
            )
            quality = _compact(
                {
                    "sentence_type": parts[0].removeprefix("$"),
                    "fix_quality": values.get("fix_quality"),
                    "satellite_count": values.get("satellite_count"),
                    "hdop": values.get("hdop"),
                    "row_index": index,
                }
            )
        elif sentence_type == "RMC" and len(parts) >= 9:
            lat = _nmea_coordinate(parts[3], parts[4])
            lon = _nmea_coordinate(parts[5], parts[6])
            values = _compact(
                {
                    "lat": lat,
                    "lon": lon,
                    "speed_knots": _float_or_none(parts[7]),
                    "course_deg": _float_or_none(parts[8]),
                }
            )
            quality = _compact(
                {
                    "sentence_type": parts[0].removeprefix("$"),
                    "status": parts[2] or None,
                    "row_index": index,
                }
            )
        else:
            continue

        samples.append(
            HardwareEvidenceSample(
                source_kind="gnss",
                values=values,
                units={
                    "altitude_m": "m",
                    "course_deg": "deg",
                    "speed_knots": "kn",
                },
                quality=quality,
                provenance={
                    "producer": "nmea",
                    "source_format": "nmea_sentence",
                    "raw_sentence_type": parts[0].removeprefix("$"),
                    "nmea_time": parts[1] if len(parts) > 1 else None,
                },
            )
        )
    if not samples:
        raise ValueError("NMEA input did not contain supported GGA or RMC sentences")
    return samples


def host_probe_to_samples(payload: Mapping[str, Any]) -> list[HardwareEvidenceSample]:
    """Convert a Scout host probe JSON object into advisory evidence."""

    values = _compact(
        {
            "hostname": payload.get("hostname"),
            "uptime_seconds": _float_from_keys(payload, "uptime_seconds", "uptime"),
            "load_1m": _float_from_keys(payload, "load_1m"),
            "service_count": len(payload.get("services") or [])
            if isinstance(payload.get("services"), list)
            else None,
        }
    )
    quality = _compact(
        {
            "service_statuses": payload.get("services"),
            "probe_status": payload.get("status") or "candidate",
        }
    )
    return [
        HardwareEvidenceSample(
            source_kind="host_probe",
            captured_at=str(payload.get("captured_at") or datetime.now(UTC).isoformat()),
            values=values,
            units={"uptime_seconds": "s"},
            quality=quality,
            provenance={
                "producer": "host_probe",
                "source_format": "host_probe_json",
            },
        )
    ]


def build_hardware_evidence_directory(
    *,
    root: Path,
    artifacts: list[tuple[HardwareEvidenceArtifact, Path]],
    notes: list[str] | None = None,
) -> HardwareEvidenceDirectoryArtifact:
    """Build a safe index over advisory hardware evidence artifacts."""

    entries = [
        HardwareEvidenceDirectoryEntry(
            artifact_id=artifact.artifact_id,
            source=artifact.source,
            source_device_id=artifact.source_device_id,
            produced_at=artifact.produced_at,
            artifact_path=_relative_or_absolute(path, root),
            sample_count=len(artifact.samples),
        )
        for artifact, path in artifacts
    ]
    directory = HardwareEvidenceDirectoryArtifact(
        root=str(root),
        entries=entries,
        notes=list(notes or []),
    )
    directory.assert_safe_boundary()
    return directory


def load_hardware_evidence_samples(path: Path) -> list[HardwareEvidenceSample]:
    """Load one sample object or a sample list from JSON."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_samples: list[Any]
    if isinstance(payload, list):
        raw_samples = payload
    elif isinstance(payload, dict) and isinstance(payload.get("samples"), list):
        raw_samples = payload["samples"]
    elif isinstance(payload, dict):
        raw_samples = [payload]
    else:
        raise ValueError("sample JSON must be an object, a list, or contain samples")
    return [HardwareEvidenceSample.model_validate(sample) for sample in raw_samples]


def load_sensor_logger_json_samples(path: Path) -> list[HardwareEvidenceSample]:
    return sensor_logger_json_to_samples(json.loads(path.read_text(encoding="utf-8")))


def load_sensor_logger_csv_samples(path: Path) -> list[HardwareEvidenceSample]:
    import csv

    with path.open("r", encoding="utf-8", newline="") as file:
        return sensor_logger_rows_to_samples(csv.DictReader(file))


def load_nmea_samples(path: Path) -> list[HardwareEvidenceSample]:
    return nmea_lines_to_samples(path.read_text(encoding="utf-8").splitlines())


def load_host_probe_samples(path: Path) -> list[HardwareEvidenceSample]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("host probe JSON must be an object")
    return host_probe_to_samples(payload)


def write_hardware_evidence(artifact: HardwareEvidenceArtifact, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(artifact.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def write_hardware_evidence_directory(
    artifact: HardwareEvidenceDirectoryArtifact, path: Path
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(artifact.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def assert_safe_hardware_evidence_boundary(boundary: dict[str, Any]) -> None:
    forbidden_true = {
        key: value
        for key, value in boundary.items()
        if key in _FORBIDDEN_TRUE_KEYS and value is True
    }
    if forbidden_true:
        raise ValueError(
            "hardware evidence boundary cannot enable runtime effects: "
            f"{sorted(forbidden_true)}"
        )
    if boundary.get("advisory_only") is not True:
        raise ValueError("hardware evidence must keep advisory_only=true")
    if boundary.get("not_safety_truth") is not True:
        raise ValueError("hardware evidence must keep not_safety_truth=true")


def _safe_boundary(overrides: dict[str, bool] | None) -> dict[str, bool]:
    boundary = dict(SAFE_HARDWARE_EVIDENCE_BOUNDARY)
    boundary.update(overrides or {})
    assert_safe_hardware_evidence_boundary(boundary)
    return boundary


def _compact(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def _float_from_keys(row: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return _float_or_none(value)
    return None


def _float_or_none(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _nmea_coordinate(value: str, hemisphere: str) -> float | None:
    if not value:
        return None
    try:
        dot_index = value.index(".")
        degree_digits = dot_index - 2
        degrees = int(value[:degree_digits])
        minutes = float(value[degree_digits:])
        coordinate = degrees + minutes / 60.0
        if hemisphere in {"S", "W"}:
            coordinate *= -1
        return coordinate
    except (ValueError, IndexError):
        return None


def _relative_or_absolute(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


__all__ = [
    "HardwareEvidenceArtifact",
    "HardwareEvidenceDirectoryArtifact",
    "HardwareEvidenceDirectoryEntry",
    "HardwareEvidenceSample",
    "HardwareEvidenceSourceKind",
    "SAFE_HARDWARE_EVIDENCE_BOUNDARY",
    "assert_safe_hardware_evidence_boundary",
    "build_hardware_evidence",
    "build_hardware_evidence_directory",
    "host_probe_to_samples",
    "load_hardware_evidence_samples",
    "load_host_probe_samples",
    "load_nmea_samples",
    "load_sensor_logger_csv_samples",
    "load_sensor_logger_json_samples",
    "nmea_lines_to_samples",
    "sensor_logger_json_to_samples",
    "sensor_logger_rows_to_samples",
    "write_hardware_evidence",
    "write_hardware_evidence_directory",
]
