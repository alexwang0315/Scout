from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ingress_evidence import IngressTransport


SENSOR_VITALS_RECORD_ARTIFACT_KIND = "scout_sensor_vitals_record"
SENSOR_VITALS_RECORD_ARTIFACT_VERSION = "scout_sensor_vitals_record.v0"
SENSOR_VITALS_RECORD_SET_ARTIFACT_KIND = "scout_sensor_vitals_record_set"
SENSOR_VITALS_RECORD_SET_ARTIFACT_VERSION = "scout_sensor_vitals_record_set.v0"


class SensorVitalsRecordModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScoutSensorVitalsBoundary(SensorVitalsRecordModel):
    evidence_only: Literal[True] = True
    runtime_admission_performed: Literal[False] = False
    phase1_l0_l4_state_mutated: Literal[False] = False
    safety_api_called: Literal[False] = False
    phase2_brain_writeback: Literal[False] = False
    outbound_send_performed: Literal[False] = False
    medical_diagnosis: Literal[False] = False
    raw_payload_embedded: Literal[False] = False
    credential_value_exposed: Literal[False] = False


class ScoutSensorVitalsRecord(SensorVitalsRecordModel):
    artifact_kind: Literal[SENSOR_VITALS_RECORD_ARTIFACT_KIND] = SENSOR_VITALS_RECORD_ARTIFACT_KIND
    artifact_version: Literal[SENSOR_VITALS_RECORD_ARTIFACT_VERSION] = SENSOR_VITALS_RECORD_ARTIFACT_VERSION
    record_id: str = Field(min_length=1)
    observation_ref: str = Field(min_length=1)
    session_id: str | None = None
    device_id: str | None = None
    source_adapter: str = Field(min_length=1)
    ingress_transport: IngressTransport
    observation_name: str = Field(min_length=1)
    observed_at: str | None = None
    timestamp_s: float | None = None
    received_at: str = Field(min_length=1)
    message_id: int | None = None
    values: dict[str, Any] = Field(default_factory=dict)
    unit_map: dict[str, str] = Field(default_factory=dict)
    capability_tags: tuple[str, ...] = Field(default_factory=tuple)
    privacy_class: str = Field(min_length=1)
    quality: dict[str, Any] = Field(default_factory=dict)
    raw_evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    payload_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    credential_value_exposed: Literal[False] = False
    boundary: ScoutSensorVitalsBoundary = Field(default_factory=ScoutSensorVitalsBoundary)

    @model_validator(mode="after")
    def enforce_record_boundary(self) -> "ScoutSensorVitalsRecord":
        if self.credential_value_exposed:
            raise ValueError("sensor/vitals record must not expose credential values")
        _assert_no_credentials(self.values, label="values")
        _assert_no_credentials(self.quality, label="quality")
        return self


class ScoutSensorVitalsRecordSet(SensorVitalsRecordModel):
    artifact_kind: Literal[SENSOR_VITALS_RECORD_SET_ARTIFACT_KIND] = SENSOR_VITALS_RECORD_SET_ARTIFACT_KIND
    artifact_version: Literal[SENSOR_VITALS_RECORD_SET_ARTIFACT_VERSION] = SENSOR_VITALS_RECORD_SET_ARTIFACT_VERSION
    session_id: str | None = None
    record_count: int = Field(ge=0)
    records: tuple[ScoutSensorVitalsRecord, ...] = Field(default_factory=tuple)
    summary: dict[str, Any] = Field(default_factory=dict)
    boundary: ScoutSensorVitalsBoundary = Field(default_factory=ScoutSensorVitalsBoundary)

    @model_validator(mode="after")
    def enforce_record_count(self) -> "ScoutSensorVitalsRecordSet":
        if self.record_count != len(self.records):
            raise ValueError("record_count must match records")
        return self


def sensor_vitals_records_from_observations(
    observations: Iterable[Any],
    *,
    session_id: str | None = None,
) -> ScoutSensorVitalsRecordSet:
    records = tuple(record_from_observation(observation) for observation in observations)
    effective_session_id = session_id or _first_session_id(records)
    return ScoutSensorVitalsRecordSet(
        session_id=effective_session_id,
        record_count=len(records),
        records=records,
        summary=summarize_sensor_vitals_records(records),
    )


def record_from_observation(observation: Any) -> ScoutSensorVitalsRecord:
    observation_name = str(getattr(observation, "observation_name"))
    values = dict(getattr(observation, "values", {}) or {})
    tags = tuple(sorted({str(tag) for tag in getattr(observation, "capability_tags", ())}))
    observation_ref = str(getattr(observation, "observation_id"))
    payload_sha256 = getattr(observation, "payload_sha256", None)
    raw_evidence_refs = tuple(str(ref) for ref in getattr(observation, "raw_evidence_refs", ()) or ())
    return ScoutSensorVitalsRecord(
        record_id=_stable_id(
            "sensor_vitals_record",
            observation_ref,
            str(payload_sha256 or ""),
            observation_name,
        ),
        observation_ref=observation_ref,
        session_id=getattr(observation, "session_id", None),
        device_id=getattr(observation, "device_id", None),
        source_adapter=str(getattr(observation, "source_adapter")),
        ingress_transport=IngressTransport(getattr(observation, "ingress_transport")),
        observation_name=observation_name,
        observed_at=getattr(observation, "observed_at", None),
        timestamp_s=getattr(observation, "timestamp_s", None),
        received_at=str(getattr(observation, "received_at")),
        message_id=getattr(observation, "message_id", None),
        values=values,
        unit_map=_unit_map_for_observation(observation_name, values),
        capability_tags=tags,
        privacy_class=_privacy_class_for_observation(observation_name, tags),
        quality=_quality_for_observation(observation_name, values),
        raw_evidence_refs=raw_evidence_refs,
        payload_sha256=payload_sha256,
    )


def append_sensor_vitals_records_jsonl(path: Path, record_set: ScoutSensorVitalsRecordSet) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for record in record_set.records:
            handle.write(json.dumps(record.model_dump(mode="json"), ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def load_sensor_vitals_records_jsonl(path: Path) -> list[ScoutSensorVitalsRecord]:
    if not path.exists():
        return []
    records: list[ScoutSensorVitalsRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(ScoutSensorVitalsRecord.model_validate_json(line))
    return records


def query_sensor_vitals_records(
    records: Iterable[ScoutSensorVitalsRecord],
    *,
    observation_names: set[str] | None = None,
    capability_tags: set[str] | None = None,
    device_id: str | None = None,
    session_id: str | None = None,
    start_timestamp_s: float | None = None,
    end_timestamp_s: float | None = None,
) -> list[ScoutSensorVitalsRecord]:
    filtered: list[ScoutSensorVitalsRecord] = []
    normalized_names = {name.lower() for name in observation_names or set()}
    normalized_tags = {tag.lower() for tag in capability_tags or set()}
    for record in records:
        if normalized_names and record.observation_name.lower() not in normalized_names:
            continue
        if normalized_tags and not normalized_tags.intersection(tag.lower() for tag in record.capability_tags):
            continue
        if device_id is not None and record.device_id != device_id:
            continue
        if session_id is not None and record.session_id != session_id:
            continue
        if start_timestamp_s is not None and (
            record.timestamp_s is None or record.timestamp_s < start_timestamp_s
        ):
            continue
        if end_timestamp_s is not None and (
            record.timestamp_s is None or record.timestamp_s > end_timestamp_s
        ):
            continue
        filtered.append(record)
    return filtered


def summarize_sensor_vitals_records(records: Iterable[ScoutSensorVitalsRecord]) -> dict[str, Any]:
    record_list = list(records)
    return {
        "artifact_kind": "scout_sensor_vitals_record_summary",
        "artifact_version": "sensor_vitals_record_summary.v0",
        "record_count": len(record_list),
        "observation_name_counts": _counts(record.observation_name for record in record_list),
        "device_counts": _counts(record.device_id or "unknown-device" for record in record_list),
        "session_counts": _counts(record.session_id or "unknown-session" for record in record_list),
        "source_adapter_counts": _counts(record.source_adapter for record in record_list),
        "ingress_transport_counts": _counts(record.ingress_transport.value for record in record_list),
        "capability_tag_counts": _counts(tag for record in record_list for tag in record.capability_tags),
        "privacy_class_counts": _counts(record.privacy_class for record in record_list),
        "boundary": ScoutSensorVitalsBoundary().model_dump(mode="json"),
    }


def _unit_map_for_observation(observation_name: str, values: dict[str, Any]) -> dict[str, str]:
    lower = observation_name.lower()
    unit_map: dict[str, str] = {}
    for key in values:
        normalized = key.lower()
        if normalized in {"latitude", "longitude", "lat", "lon", "locationlatitude", "locationlongitude"}:
            unit_map[key] = "deg"
        elif "accuracy" in normalized:
            unit_map[key] = "m"
        elif normalized in {"x", "y", "z", "acc_x", "acc_y", "acc_z"} and lower in {
            "accelerometer",
            "motion",
            "custommotionpacket",
        }:
            unit_map[key] = "m/s^2"
        elif normalized in {"x", "y", "z", "gyro_x", "gyro_y", "gyro_z"} and lower == "gyroscope":
            unit_map[key] = "rad/s"
        elif "distance" in normalized:
            unit_map[key] = "m"
        elif "steps" in normalized:
            unit_map[key] = "count"
        elif normalized in {"heartrate", "heart_rate", "hr"}:
            unit_map[key] = "bpm"
        elif "battery" in normalized:
            unit_map[key] = "%"
    return unit_map


def _privacy_class_for_observation(observation_name: str, tags: tuple[str, ...]) -> str:
    lower = observation_name.lower()
    tag_set = {tag.lower() for tag in tags}
    if {"health", "vitals", "resource"}.intersection(tag_set) or lower in {"heart_rate", "heartrate", "hrv", "spo2"}:
        return "private_vitals"
    if {"gps", "location", "pdr"}.intersection(tag_set) or lower in {"location", "pedometer"}:
        return "private_location"
    return "private_sensor"


def _quality_for_observation(observation_name: str, values: dict[str, Any]) -> dict[str, Any]:
    lower = observation_name.lower()
    quality: dict[str, Any] = {}
    for key in ("horizontalAccuracy", "locationHorizontalAccuracy", "accuracy", "accuracy_m"):
        if key in values:
            quality["horizontal_accuracy_m"] = values[key]
            break
    if lower == "location" or {"latitude", "longitude"}.intersection(values):
        quality["gps_like_location"] = True
    if lower == "pedometer" or any("step" in key.lower() or "distance" in key.lower() for key in values):
        quality["pdr_like_delta"] = True
    return quality


def _first_session_id(records: tuple[ScoutSensorVitalsRecord, ...]) -> str | None:
    for record in records:
        if record.session_id:
            return record.session_id
    return None


def _counts(values: Iterable[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _stable_id(*parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{parts[0]}:{digest}"


def _assert_no_credentials(value: Any, *, label: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if _credential_like_key(str(key)):
                raise ValueError(f"summary-forbidden:{label}.{key}")
            _assert_no_credentials(item, label=f"{label}.{key}")
    elif isinstance(value, list | tuple):
        for index, item in enumerate(value):
            _assert_no_credentials(item, label=f"{label}[{index}]")


def _credential_like_key(key: str) -> bool:
    forbidden = ("password", "secret", "token", "access_token", "hmac", "session_key")
    key_text = key.lower()
    return any(part in key_text for part in forbidden)
