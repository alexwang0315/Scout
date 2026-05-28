from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from scout_energy_models import (
    BodyEnergyProviderValues,
    HeartRateSummary,
    ScoutEnergyBoundary,
    ScoutEnergyDataQuality,
    ScoutEnergyPrivacy,
    WearableActivitySummary,
    aggregate_sha256,
    sha256_file,
)
from scout_wearable_validator import assert_valid_wearable_activity_summary_contract


WearableAdapterSourceFormat = Literal[
    "apple_health_export_summary",
    "apple_healthkit_workout_summary",
    "garmin_connect_activity_summary",
    "gpx_derived_summary",
    "fit_derived_summary",
    "tcx_derived_summary",
]

SOURCE_PROVIDER_BY_FORMAT: dict[WearableAdapterSourceFormat, str] = {
    "apple_health_export_summary": "apple_health_export",
    "apple_healthkit_workout_summary": "apple_healthkit_api_fixture",
    "garmin_connect_activity_summary": "garmin_connect_export",
    "gpx_derived_summary": "gpx_derived_summary",
    "fit_derived_summary": "fit_derived_summary",
    "tcx_derived_summary": "tcx_derived_summary",
}

FORBIDDEN_ADAPTER_KEYS = {
    "coordinates",
    "ended_at",
    "fit_records",
    "home_trace",
    "latitude",
    "longitude",
    "precise_timestamp",
    "raw_gpx",
    "raw_health_payload",
    "raw_payload",
    "raw_samples",
    "recorded_at",
    "source_uri",
    "started_at",
    "timestamp",
    "timestamps",
    "track",
    "trackpoints",
    "trkpt",
    "work_trace",
}


class WearableSanitizedImportEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_wearable_sanitized_import"
    artifact_version: str = "wearable_sanitized_import.v1"
    source_format: WearableAdapterSourceFormat
    activity_id: str
    activity_type: str
    activity_date: str
    duration_s: int = Field(ge=0)
    moving_time_s: int = Field(ge=0)
    distance_m: float = Field(default=0.0, ge=0)
    ascent_m: float = Field(default=0.0, ge=0)
    descent_m: float = Field(default=0.0, ge=0)
    rest_event_count: int = Field(default=0, ge=0)
    rest_duration_min: list[float] = Field(default_factory=list)
    late_activity_fatigue_decay: float | None = None
    session_rpe: float | None = Field(default=None, ge=0, le=10)
    heart_rate: HeartRateSummary = Field(default_factory=lambda: HeartRateSummary(sample_count=0))
    body_energy_provider_values: BodyEnergyProviderValues = Field(default_factory=BodyEnergyProviderValues)
    data_quality: ScoutEnergyDataQuality
    privacy: ScoutEnergyPrivacy = Field(default_factory=ScoutEnergyPrivacy)
    boundary: ScoutEnergyBoundary = Field(default_factory=ScoutEnergyBoundary)

    @model_validator(mode="after")
    def validate_adapter_boundary(self) -> "WearableSanitizedImportEnvelope":
        if self.privacy.raw_samples_embedded:
            raise ValueError("adapter input must not embed raw samples")
        if self.privacy.raw_health_payload_shared:
            raise ValueError("adapter input must not share raw health payload")
        if self.privacy.raw_track_shared:
            raise ValueError("adapter input must not share raw track")
        if self.privacy.exact_timestamps_shared:
            raise ValueError("adapter input must not share exact timestamps")
        if self.privacy.home_work_trace_shared:
            raise ValueError("adapter input must not share home/work traces")
        if self.boundary.medical_diagnosis:
            raise ValueError("adapter input cannot be medical diagnosis")
        if self.boundary.phase1_runtime_safety_truth:
            raise ValueError("adapter input cannot be Phase 1 runtime safety truth")
        if self.boundary.safety_api_calls_allowed:
            raise ValueError("adapter input cannot allow safety API calls")
        if not self.body_energy_provider_values.source_value_only:
            raise ValueError("provider values must remain source values")
        if self.body_energy_provider_values.scout_truth:
            raise ValueError("provider values must not be Scout truth")
        return self


def normalize_wearable_import_envelope(
    source_path: Path,
    *,
    root: Path | None = None,
) -> WearableActivitySummary:
    payload = _read_clean_adapter_payload(source_path)
    envelope = WearableSanitizedImportEnvelope.model_validate(payload)
    source_provider = SOURCE_PROVIDER_BY_FORMAT[envelope.source_format]
    normalized_payload = envelope.model_dump(mode="json")
    normalized_payload.pop("source_format", None)
    normalized_payload["artifact_kind"] = "scout_wearable_activity_summary"
    normalized_payload["artifact_version"] = "wearable_activity_summary.v1"
    normalized_payload["source_provider"] = source_provider
    normalized_payload["source_path"] = _relpath(source_path, root or Path.cwd())
    normalized_payload["sha256"] = sha256_file(source_path)
    normalized_payload["data_quality"]["limitations"] = sorted(
        {
            *normalized_payload["data_quality"].get("limitations", []),
            "normalized from sanitized source summary; raw provider payload not stored",
        }
    )
    return WearableActivitySummary.model_validate(normalized_payload)


def write_normalized_wearable_import(
    source_path: Path,
    *,
    output_dir: Path,
    root: Path | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    activity = normalize_wearable_import_envelope(source_path, root=root)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{_activity_slug(activity.activity_id)}.json"
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"normalized wearable summary already exists: {output_path}")
    output_path.write_text(
        json.dumps(activity.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    validation = assert_valid_wearable_activity_summary_contract(output_path, root=root or Path.cwd())
    return {
        "artifact_kind": "scout_wearable_adapter_normalization_result",
        "source_provider": activity.source_provider,
        "source_path": activity.source_path,
        "sha256": activity.sha256,
        "activity_id": activity.activity_id,
        "normalized_path": str(output_path),
        "validation": validation.model_dump(mode="json"),
        "data_quality": activity.data_quality.model_dump(mode="json"),
        "privacy": activity.privacy.model_dump(mode="json"),
        "boundary": activity.boundary.model_dump(mode="json"),
        "mutation": {
            "normalized_summary_written": True,
            "source_file_mutated": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def write_normalized_wearable_imports(
    source_paths: list[Path],
    *,
    output_dir: Path,
    root: Path | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    if not source_paths:
        raise ValueError("at least one sanitized wearable import is required")
    results = [
        write_normalized_wearable_import(
            source_path,
            output_dir=output_dir,
            root=root,
            overwrite=overwrite,
        )
        for source_path in source_paths
    ]
    providers = sorted({result["source_provider"] for result in results})
    source_provider = providers[0] if len(providers) == 1 else "mixed_wearable_adapter_inputs"
    return {
        "artifact_kind": "scout_wearable_adapter_normalization_batch",
        "source_provider": source_provider,
        "source_path": _aggregate_source_path([result["source_path"] for result in results]),
        "sha256": aggregate_sha256([result["sha256"] for result in results]),
        "activity_count": len(results),
        "normalized_paths": [result["normalized_path"] for result in results],
        "results": results,
        "data_quality": _batch_data_quality(results),
        "privacy": ScoutEnergyPrivacy().model_dump(mode="json"),
        "boundary": ScoutEnergyBoundary().model_dump(mode="json"),
    }


def _read_clean_adapter_payload(source_path: Path) -> dict[str, Any]:
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    forbidden_paths = _forbidden_key_paths(payload)
    if forbidden_paths:
        raise ValueError(f"forbidden raw adapter fields present: {', '.join(forbidden_paths)}")
    try:
        return WearableSanitizedImportEnvelope.model_validate(payload).model_dump(mode="json")
    except ValidationError:
        raise


def _batch_data_quality(results: list[dict[str, Any]]) -> dict[str, Any]:
    order = {"low": 0, "medium": 1, "high": 2}
    data_quality = [result["data_quality"] for result in results]
    limitations = sorted(
        {
            limitation
            for quality in data_quality
            for limitation in quality.get("limitations", [])
        }
    )
    return ScoutEnergyDataQuality(
        heart_rate_confidence=min(
            (quality.get("heart_rate_confidence", "low") for quality in data_quality),
            key=order.get,
        ),
        gps_confidence=min(
            (quality.get("gps_confidence", "low") for quality in data_quality),
            key=order.get,
        ),
        missing_hr_seconds=sum(quality.get("missing_hr_seconds", 0) for quality in data_quality),
        provider_value_confidence=min(
            (quality.get("provider_value_confidence", "low") for quality in data_quality),
            key=order.get,
        ),
        limitations=limitations,
    ).model_dump(mode="json")


def _aggregate_source_path(paths: list[str]) -> str:
    if len(set(paths)) == 1:
        return paths[0]
    split_paths = [path.split("/")[:-1] for path in paths]
    prefix: list[str] = []
    for parts in zip(*split_paths):
        if len(set(parts)) != 1:
            break
        prefix.append(parts[0])
    return f"aggregate:{'/'.join(prefix) if prefix else 'wearable_adapter_inputs'}"


def _forbidden_key_paths(value: Any, prefix: str = "") -> list[str]:
    if isinstance(value, dict):
        paths: list[str] = []
        for key, child in value.items():
            child_path = f"{prefix}.{key}" if prefix else str(key)
            if str(key).lower() in FORBIDDEN_ADAPTER_KEYS:
                paths.append(child_path)
            paths.extend(_forbidden_key_paths(child, child_path))
        return paths
    if isinstance(value, list):
        paths: list[str] = []
        for index, child in enumerate(value):
            paths.extend(_forbidden_key_paths(child, f"{prefix}[{index}]"))
        return paths
    return []


def _activity_slug(activity_id: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", activity_id).strip("._")
    return slug or "activity"


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)
