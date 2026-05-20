from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pretrip_models import RouteBBox


class WeatherDaylightStatus(StrEnum):
    CANDIDATE_ONLY = "candidate_only"


class WeatherDaylightValidationStatus(StrEnum):
    NEEDS_REVIEW = "needs_review"
    HUMAN_REVIEW_REQUIRED = "human_review_required"


class WeatherDaylightConfidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class WeatherDaylightStaleness(StrEnum):
    PLACEHOLDER = "placeholder"
    STALE = "stale"
    CURRENT_AS_OF_SOURCE = "current_as_of_source"
    UNKNOWN = "unknown"


class WeatherDaylightSourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_ref: str
    title: str
    uri: str | None = None
    collected_at: str | None = None
    notes: str = ""


class DaylightEvidenceWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: str
    timezone: str = "Asia/Taipei"
    sunrise: str | None = None
    sunset: str | None = None
    civil_twilight_begin: str | None = None
    civil_twilight_end: str | None = None
    source_status: Literal["manual_placeholder", "manually_provided"] = "manual_placeholder"
    notes: str = ""


class WeatherWindowSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_start: str
    window_end: str
    summary: str
    hazard_notes: list[str] = Field(default_factory=list)
    precipitation_label: str | None = None
    temperature_range_c: str | None = None
    wind_summary: str | None = None
    thunderstorm_risk: str | None = None
    source_status: Literal["manual_placeholder", "manually_provided"] = "manual_placeholder"
    notes: str = ""


class CwaStyleRainfallThresholdPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comparator: Literal[">="] = ">="
    heavy_rain_1h_mm: float = 40.0
    heavy_rain_24h_mm: float = 80.0
    extremely_heavy_rain_3h_mm: float = 100.0
    extremely_heavy_rain_24h_mm: float = 200.0
    source_refs: list[str] = Field(default_factory=list)
    notes: str = ""


class CwaStyleDenseFogThresholdPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visibility_comparator: Literal["<"] = "<"
    dense_fog_visibility_m: float = 200.0
    source_refs: list[str] = Field(default_factory=list)
    notes: str = ""


class CwaStyleStrongWindThresholdPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comparator: Literal[">="] = ">="
    yellow_avg_wind_mps: float = 10.8
    yellow_gust_mps: float = 17.2
    orange_avg_wind_mps: float = 20.8
    orange_gust_mps: float = 28.5
    source_refs: list[str] = Field(default_factory=list)
    notes: str = ""


class DaylightThresholdPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dark_arrival_warning_margin_min: int = 60
    civil_twilight_blocker_candidate_enabled: bool = True
    severe_weather_warning_candidate_enabled: bool = True
    configurable: bool = True
    source_refs: list[str] = Field(default_factory=list)
    notes: str = ""


class WeatherDaylightThresholdPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: str = "cwa_style_mountain_weather_daylight_reference.v0"
    policy_status: Literal["reference_only", "project_override"] = "reference_only"
    configurable: bool = True
    rainfall: CwaStyleRainfallThresholdPolicy = Field(
        default_factory=CwaStyleRainfallThresholdPolicy
    )
    dense_fog: CwaStyleDenseFogThresholdPolicy = Field(
        default_factory=CwaStyleDenseFogThresholdPolicy
    )
    strong_wind: CwaStyleStrongWindThresholdPolicy = Field(
        default_factory=CwaStyleStrongWindThresholdPolicy
    )
    daylight: DaylightThresholdPolicy = Field(default_factory=DaylightThresholdPolicy)
    notes: list[str] = Field(default_factory=list)


class WeatherDaylightValidation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    validation_status: WeatherDaylightValidationStatus = (
        WeatherDaylightValidationStatus.HUMAN_REVIEW_REQUIRED
    )
    confidence: WeatherDaylightConfidence = WeatherDaylightConfidence.UNKNOWN
    staleness: WeatherDaylightStaleness = WeatherDaylightStaleness.PLACEHOLDER
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    notes: list[str] = Field(default_factory=list)


class PreTripWeatherDaylightEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    project_id: str
    status: WeatherDaylightStatus = WeatherDaylightStatus.CANDIDATE_ONLY
    date: str
    timezone: str = "Asia/Taipei"
    location_name: str
    route_ref: str
    bbox_wgs84: RouteBBox | None = None
    daylight: DaylightEvidenceWindow
    weather_window: WeatherWindowSummary
    threshold_policy: WeatherDaylightThresholdPolicy | None = None
    source_refs: list[str] = Field(default_factory=list)
    source_details: list[WeatherDaylightSourceRef] = Field(default_factory=list)
    validation: WeatherDaylightValidation = Field(default_factory=WeatherDaylightValidation)
    human_review_required: bool = True
    authoritative_weather_computed: bool = False
    external_api_calls_made: bool = False
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_candidate_only_boundary(self) -> "PreTripWeatherDaylightEvidence":
        if self.status != WeatherDaylightStatus.CANDIDATE_ONLY:
            raise ValueError("weather/daylight evidence must remain candidate_only")
        if not self.human_review_required:
            raise ValueError("candidate weather/daylight evidence requires human review")
        if self.authoritative_weather_computed:
            raise ValueError("weather/daylight evidence must not claim authoritative computation")
        if self.external_api_calls_made:
            raise ValueError("weather/daylight evidence must not record external API calls")
        if self.daylight.date != self.date:
            raise ValueError("daylight date must match evidence date")
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


def load_weather_daylight_evidence(path: Path | str) -> PreTripWeatherDaylightEvidence:
    return PreTripWeatherDaylightEvidence.model_validate_json(Path(path).read_text())
