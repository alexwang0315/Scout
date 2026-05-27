from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from scout_energy_models import (
    ScoutEnergyBoundary,
    ScoutEnergyDataQuality,
    ScoutEnergyPrivacy,
    load_wearable_activity_summary,
    sha256_file,
)


FORBIDDEN_RAW_KEYS = {
    "coordinates",
    "ended_at",
    "home_trace",
    "precise_timestamp",
    "raw_gpx",
    "raw_health_payload",
    "raw_payload",
    "raw_samples",
    "source_uri",
    "started_at",
    "timestamp",
    "timestamps",
    "work_trace",
}


class WearableActivityValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_wearable_activity_summary_validation"
    artifact_version: str = "wearable_activity_summary_validation.v1"
    valid: bool
    source_provider: str | None = None
    source_path: str
    sha256: str
    activity_id: str | None = None
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    data_quality: ScoutEnergyDataQuality = Field(default_factory=ScoutEnergyDataQuality)
    privacy: ScoutEnergyPrivacy = Field(default_factory=ScoutEnergyPrivacy)
    boundary: ScoutEnergyBoundary = Field(default_factory=ScoutEnergyBoundary)


def validate_wearable_activity_summary_contract(
    path: Path,
    *,
    root: Path | None = None,
) -> WearableActivityValidationReport:
    source_path = _relpath(path, root or Path.cwd())
    digest = sha256_file(path)
    errors: list[str] = []
    warnings: list[str] = []
    payload = json.loads(path.read_text(encoding="utf-8"))
    forbidden_paths = _forbidden_key_paths(payload)
    errors.extend(f"forbidden raw field present: {field_path}" for field_path in forbidden_paths)
    try:
        activity = load_wearable_activity_summary(path, root=root)
    except (ValidationError, ValueError, TypeError) as exc:
        errors.append(str(exc))
        return WearableActivityValidationReport(
            valid=False,
            source_path=source_path,
            sha256=digest,
            errors=errors,
            warnings=warnings,
        )
    if activity.privacy.raw_health_payload_shared:
        errors.append("privacy.raw_health_payload_shared must be false")
    if activity.privacy.raw_samples_embedded:
        errors.append("privacy.raw_samples_embedded must be false")
    if activity.privacy.raw_track_shared:
        errors.append("privacy.raw_track_shared must be false")
    if activity.privacy.exact_timestamps_shared:
        errors.append("privacy.exact_timestamps_shared must be false")
    if activity.privacy.home_work_trace_shared:
        errors.append("privacy.home_work_trace_shared must be false")
    if activity.boundary.medical_diagnosis:
        errors.append("boundary.medical_diagnosis must be false")
    if activity.boundary.phase1_runtime_safety_truth:
        errors.append("boundary.phase1_runtime_safety_truth must be false")
    if activity.boundary.safety_api_calls_allowed:
        errors.append("boundary.safety_api_calls_allowed must be false")
    if not activity.body_energy_provider_values.source_value_only:
        errors.append("body energy provider values must remain source values")
    if activity.body_energy_provider_values.scout_truth:
        errors.append("body energy provider values must not be Scout truth")
    if activity.heart_rate.samples and activity.privacy.raw_samples_embedded:
        errors.append("heart-rate samples cannot be marked as raw embedded payload")
    if activity.heart_rate.samples:
        warnings.append("heart-rate samples are represented as coarse offsets only")
    return WearableActivityValidationReport(
        valid=not errors,
        source_provider=activity.source_provider,
        source_path=activity.source_path,
        sha256=activity.sha256,
        activity_id=activity.activity_id,
        errors=errors,
        warnings=warnings,
        summary={
            "activity_type": activity.activity_type,
            "activity_date": activity.activity_date.isoformat(),
            "duration_s": activity.duration_s,
            "moving_time_s": activity.moving_time_s,
            "distance_m": activity.distance_m,
            "ascent_m": activity.ascent_m,
            "descent_m": activity.descent_m,
            "heart_rate_sample_count": activity.heart_rate.sample_count,
            "missing_hr_seconds": activity.data_quality.missing_hr_seconds,
            "provider_values_source_only": activity.body_energy_provider_values.source_value_only,
            "provider_values_scout_truth": activity.body_energy_provider_values.scout_truth,
        },
        data_quality=activity.data_quality,
        privacy=activity.privacy,
        boundary=activity.boundary,
    )


def assert_valid_wearable_activity_summary_contract(
    path: Path,
    *,
    root: Path | None = None,
) -> WearableActivityValidationReport:
    report = validate_wearable_activity_summary_contract(path, root=root)
    if not report.valid:
        raise ValueError("; ".join(report.errors))
    return report


def _forbidden_key_paths(value: Any, prefix: str = "") -> list[str]:
    if isinstance(value, dict):
        paths: list[str] = []
        for key, child in value.items():
            child_path = f"{prefix}.{key}" if prefix else str(key)
            if str(key).lower() in FORBIDDEN_RAW_KEYS:
                paths.append(child_path)
            paths.extend(_forbidden_key_paths(child, child_path))
        return paths
    if isinstance(value, list):
        paths = []
        for index, child in enumerate(value):
            paths.extend(_forbidden_key_paths(child, f"{prefix}[{index}]"))
        return paths
    return []


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)
