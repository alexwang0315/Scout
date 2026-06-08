from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


Confidence = Literal["high", "medium", "low"]
ReserveBand = Literal["normal", "watch", "rest_suggested", "stop_and_check"]


class ScoutEnergyBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    advisory_only: bool = True
    medical_diagnosis: bool = False
    phase1_runtime_safety_truth: bool = False
    safety_api_calls_allowed: bool = False
    phase1_safety_state_mutation_allowed: bool = False
    provider_values_are_scout_truth: bool = False


class ScoutEnergyPrivacy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_only: bool = True
    raw_samples_embedded: bool = False
    raw_health_payload_shared: bool = False
    raw_track_shared: bool = False
    exact_timestamps_shared: bool = False
    home_work_trace_shared: bool = False
    shareable_by_default: bool = False


class HeartRateSample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offset_s: int = Field(ge=0)
    bpm: int = Field(ge=1)
    quality: Confidence = "medium"


class HeartRateSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_count: int = Field(ge=0)
    avg_bpm: float | None = Field(default=None, ge=0)
    p90_bpm: float | None = Field(default=None, ge=0)
    zone_minutes: dict[str, float] = Field(default_factory=dict)
    samples: list[HeartRateSample] = Field(default_factory=list)

    @field_validator("zone_minutes")
    @classmethod
    def validate_zone_minutes(cls, value: dict[str, float]) -> dict[str, float]:
        allowed = {"z1", "z2", "z3", "z4", "z5"}
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"unknown heart-rate zones: {sorted(unknown)}")
        return {zone: float(minutes) for zone, minutes in value.items()}


class BodyEnergyProviderValues(BaseModel):
    model_config = ConfigDict(extra="forbid")

    garmin_body_battery_start: int | None = Field(default=None, ge=0, le=100)
    garmin_body_battery_end: int | None = Field(default=None, ge=0, le=100)
    garmin_stress_avg: int | None = Field(default=None, ge=0, le=100)
    source_value_only: bool = True
    scout_truth: bool = False


class ScoutEnergyDataQuality(BaseModel):
    model_config = ConfigDict(extra="forbid")

    heart_rate_confidence: Confidence = "low"
    gps_confidence: Confidence = "low"
    missing_hr_seconds: int = Field(default=0, ge=0)
    missing_hr_intervals: list[dict[str, int]] = Field(default_factory=list)
    sample_cadence_s: int | None = Field(default=None, ge=1)
    provider_value_confidence: Confidence = "low"
    limitations: list[str] = Field(default_factory=list)


class WearableActivitySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_wearable_activity_summary"
    artifact_version: str = "wearable_activity_summary.v1"
    activity_id: str
    source_provider: str
    source_path: str
    sha256: str
    activity_type: str
    route_family: str | None = None
    activity_date: date
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


class EnergyWindowSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_days: int
    activity_count: int
    load_sum: float
    mean_activity_load: float
    daily_average_load: float
    start_date: date
    end_date: date


class RouteFamilyBaselineProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route_family: str
    activity_count: int = Field(ge=0)
    route_effort_units_p50: float
    moving_time_per_effort_p50: float
    heart_rate_load_per_effort_p50: float
    late_activity_fatigue_decay_p50: float
    confidence: Confidence
    limitations: list[str] = Field(default_factory=list)


class ScoutEnergyReserveTrend(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_band: ReserveBand
    reserve_score: int = Field(ge=0, le=100)
    acute_load_ratio: float
    acute_load_z: float
    recovery_debt_z: float
    confidence: Confidence
    explanations: list[str]


class ScoutEnergyReserveExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_energy_reserve_explanation"
    artifact_version: str = "energy_reserve_explanation.v1"
    source_provider: str
    source_path: str
    sha256: str
    reserve_band: ReserveBand
    headline: str
    advisory_cues: list[str]
    forbidden_interpretations: list[str]
    data_quality: ScoutEnergyDataQuality
    privacy: ScoutEnergyPrivacy = Field(default_factory=ScoutEnergyPrivacy)
    boundary: ScoutEnergyBoundary = Field(default_factory=ScoutEnergyBoundary)


class ScoutEnergyReserveBaseline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_energy_reserve_baseline"
    artifact_version: str = "energy_reserve_baseline.v1"
    source_provider: str
    source_path: str
    sha256: str
    reference_date: date
    user_profile_ref: str = "local_user.private"
    activity_count: int
    acute_7_day_load: EnergyWindowSummary
    recent_28_day_baseline: EnergyWindowSummary
    stable_90_day_baseline: EnergyWindowSummary
    route_family_profiles: list[RouteFamilyBaselineProfile] = Field(default_factory=list)
    reserve_trend: ScoutEnergyReserveTrend
    data_quality: ScoutEnergyDataQuality
    privacy: ScoutEnergyPrivacy = Field(default_factory=ScoutEnergyPrivacy)
    boundary: ScoutEnergyBoundary = Field(default_factory=ScoutEnergyBoundary)


def load_wearable_activity_summary(path: Path, *, root: Path | None = None) -> WearableActivitySummary:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["source_path"] = _relpath(path, root or Path.cwd())
    payload["sha256"] = sha256_file(path)
    return WearableActivitySummary.model_validate(payload)


def load_wearable_activity_summaries(paths: list[Path], *, root: Path | None = None) -> list[WearableActivitySummary]:
    return [load_wearable_activity_summary(path, root=root) for path in paths]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def aggregate_sha256(values: list[str | dict[str, Any]]) -> str:
    encoded = json.dumps(values, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)
