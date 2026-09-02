"""Typed, deterministic GPX-to-TRH terrain consistency assessment.

The result describes agreement with DEM/model evidence. It never determines
GPX validity, trail existence, passage, access, or safety.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections.abc import Callable
from enum import StrEnum
from typing import Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from terrain_route_hypothesis_models import (
    TerrainAuthorityBoundary,
    TerrainEvidenceSourceType,
    TerrainHypothesisAuthority,
)


class GpxTerrainConsistency(StrEnum):
    CONSISTENT = "consistent"
    PARTIALLY_CONSISTENT = "partially_consistent"
    TERRAIN_ANOMALY = "terrain_anomaly"
    UNKNOWN = "unknown"


class TerrainConsistencyStatus(StrEnum):
    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"


class TerrainConsistencySample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lon: float
    lat: float
    inside_candidate_corridor: bool | None = None
    deviation_from_hypothesis_m: float | None = Field(default=None, ge=0)
    slope_degrees: float | None = Field(default=None, ge=0, le=90)
    drainage_pressure: float | None = Field(default=None, ge=0)
    teii: float | None = None

    @model_validator(mode="after")
    def validate_wgs84(self) -> "TerrainConsistencySample":
        if not math.isfinite(self.lon) or not -180 <= self.lon <= 180:
            raise ValueError("consistency sample longitude must be finite WGS84")
        if not math.isfinite(self.lat) or not -90 <= self.lat <= 90:
            raise ValueError("consistency sample latitude must be finite WGS84")
        if self.teii is not None and not math.isfinite(self.teii):
            raise ValueError("consistency sample TEII must be finite when present")
        return self


class TerrainRouteConsistencyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_version: str = "gpx_terrain_consistency.v0_1"
    corridor_band_name: str = "top_10_percent_corridor"
    deviation_threshold_m: float = Field(default=100.0, gt=0)
    extreme_slope_degrees: float = Field(default=40.0, gt=0, le=90)
    high_teii_threshold: float = 0.7
    anomaly_fraction_threshold: float = Field(default=0.5, gt=0, le=1)

    @field_validator("high_teii_threshold")
    @classmethod
    def validate_teii_threshold(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("high TEII threshold must be finite")
        return float(value)


class TerrainRouteConsistencyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    known_gpx_id: str = Field(min_length=1, max_length=200)
    known_gpx_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    terrain_hypothesis_id: str = Field(min_length=1, max_length=200)
    terrain_hypothesis_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    dem_resolution_m: float = Field(gt=0)
    samples: tuple[TerrainConsistencySample, ...] = Field(default_factory=tuple)
    config: TerrainRouteConsistencyConfig = Field(
        default_factory=TerrainRouteConsistencyConfig
    )


class TerrainConsistencyObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1)
    description: str = Field(min_length=1)
    sample_count: int = Field(ge=1)
    sample_fraction: float = Field(ge=0, le=1)
    source_type: TerrainEvidenceSourceType = TerrainEvidenceSourceType.TERRAIN_HYPOTHESIS


class TerrainConsistencyUnknown(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1)
    description: str = Field(min_length=1)
    source_type: TerrainEvidenceSourceType = TerrainEvidenceSourceType.UNKNOWN


class TerrainConsistencyMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sample_count: int = Field(ge=0)
    corridor_evaluated_count: int = Field(ge=0)
    outside_corridor_fraction: float | None = Field(default=None, ge=0, le=1)
    slope_evaluated_count: int = Field(ge=0)
    extreme_slope_fraction: float | None = Field(default=None, ge=0, le=1)
    drainage_evaluated_count: int = Field(ge=0)
    drainage_pressure_fraction: float | None = Field(default=None, ge=0, le=1)
    teii_evaluated_count: int = Field(ge=0)
    high_teii_fraction: float | None = Field(default=None, ge=0, le=1)
    deviation_evaluated_count: int = Field(ge=0)
    median_deviation_from_hypothesis_m: float | None = Field(default=None, ge=0)
    max_deviation_from_hypothesis_m: float | None = Field(default=None, ge=0)


class TerrainRouteConsistencyResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: Literal["gpx_terrain_plausibility_check"] = (
        "gpx_terrain_plausibility_check"
    )
    schema_version: Literal["gpx_terrain_plausibility.v0_1"] = (
        "gpx_terrain_plausibility.v0_1"
    )
    analysis_id: str = Field(pattern=r"^gpx-terrain-[a-f0-9]{16}$")
    status: TerrainConsistencyStatus
    terrain_consistency: GpxTerrainConsistency
    assessment_semantics: Literal["terrain_consistency_not_gpx_validity"] = (
        "terrain_consistency_not_gpx_validity"
    )
    summary: str = Field(min_length=1)
    known_gpx_id: str
    known_gpx_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    terrain_hypothesis_id: str
    terrain_hypothesis_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    dem_resolution_m: float = Field(gt=0)
    metrics: TerrainConsistencyMetrics
    observations: tuple[TerrainConsistencyObservation, ...] = Field(
        default_factory=tuple
    )
    unknowns: tuple[TerrainConsistencyUnknown, ...] = Field(default_factory=tuple)
    possible_explanations: tuple[str, ...] = Field(default_factory=tuple)
    failure_code: str | None = None
    known_gpx_mutated: Literal[False] = False
    authority: TerrainHypothesisAuthority = TerrainHypothesisAuthority.CANDIDATE_ONLY
    source_type: TerrainEvidenceSourceType = TerrainEvidenceSourceType.KNOWN_GPX
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    operational: Literal[False] = False
    safe_or_walkable: Literal["not_determined"] = "not_determined"
    boundary: TerrainAuthorityBoundary = Field(default_factory=TerrainAuthorityBoundary)

    @model_validator(mode="after")
    def preserve_assessment_authority(self) -> "TerrainRouteConsistencyResult":
        if self.authority is not TerrainHypothesisAuthority.CANDIDATE_ONLY:
            raise ValueError("terrain consistency output must remain candidate_only")
        if self.source_type is not TerrainEvidenceSourceType.KNOWN_GPX:
            raise ValueError("terrain consistency source_type must remain known_gpx")
        return self


MISMATCH_EXPLANATIONS = (
    "gps_drift",
    "dem_error",
    "official_engineered_trail",
    "rope_route",
    "bridge",
    "tunnel",
    "old_route",
    "landslide",
    "historical_trail",
    "data_mismatch",
)


def evaluate_terrain_route_consistency(
    request: TerrainRouteConsistencyRequest | dict[str, object],
) -> TerrainRouteConsistencyResult:
    parsed = (
        request
        if isinstance(request, TerrainRouteConsistencyRequest)
        else TerrainRouteConsistencyRequest.model_validate(request)
    )
    metrics = _metrics(parsed)
    observations = _observations(parsed, metrics)
    evidence_count = sum(
        (
            metrics.corridor_evaluated_count,
            metrics.slope_evaluated_count,
            metrics.drainage_evaluated_count,
            metrics.teii_evaluated_count,
            metrics.deviation_evaluated_count,
        )
    )
    if evidence_count == 0:
        consistency = GpxTerrainConsistency.UNKNOWN
        status = TerrainConsistencyStatus.UNAVAILABLE
        summary = (
            "Terrain consistency is UNKNOWN because no aligned corridor, slope, "
            "drainage, TEII, or candidate-trace evidence was available."
        )
        failure_code = "terrain_evidence_unavailable"
    elif _is_anomaly(metrics, parsed.config):
        consistency = GpxTerrainConsistency.TERRAIN_ANOMALY
        status = TerrainConsistencyStatus.COMPLETED
        summary = (
            "The GPX has a terrain-model anomaly relative to the sampled DEM/TRH "
            "evidence; this does not determine that the GPX is wrong."
        )
        failure_code = None
    elif observations:
        consistency = GpxTerrainConsistency.PARTIALLY_CONSISTENT
        status = TerrainConsistencyStatus.COMPLETED
        summary = (
            "The GPX is partially consistent with the sampled DEM/TRH evidence; "
            "observed mismatches require source and field review."
        )
        failure_code = None
    else:
        consistency = GpxTerrainConsistency.CONSISTENT
        status = TerrainConsistencyStatus.COMPLETED
        summary = (
            "The sampled GPX points are consistent with the available DEM/TRH "
            "evidence; this does not verify a trail, passage, access, or safety."
        )
        failure_code = None

    unknowns = list(_default_unknowns())
    dimension_unknowns = (
        (
            metrics.corridor_evaluated_count,
            "candidate_corridor_unknown",
            "Candidate corridor membership was unavailable for the sampled GPX points.",
        ),
        (
            metrics.slope_evaluated_count,
            "slope_evidence_unknown",
            "DEM slope evidence was unavailable for the sampled GPX points.",
        ),
        (
            metrics.drainage_evaluated_count,
            "drainage_evidence_unknown",
            "DEM-derived drainage-pressure evidence was unavailable for the sampled GPX points.",
        ),
        (
            metrics.teii_evaluated_count,
            "teii_unknown",
            "TEII evidence was unavailable for the sampled GPX points.",
        ),
    )
    unknowns.extend(
        TerrainConsistencyUnknown(code=code, description=description)
        for count, code, description in dimension_unknowns
        if count == 0
    )
    if evidence_count == 0:
        unknowns.insert(
            0,
            TerrainConsistencyUnknown(
                code="terrain_evidence_unavailable",
                description="No aligned terrain evidence was available for comparison.",
            ),
        )
    analysis_hash = hashlib.sha256(
        json.dumps(parsed.model_dump(mode="json"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    return TerrainRouteConsistencyResult(
        analysis_id=f"gpx-terrain-{analysis_hash[:16]}",
        status=status,
        terrain_consistency=consistency,
        summary=summary,
        known_gpx_id=parsed.known_gpx_id,
        known_gpx_sha256=parsed.known_gpx_sha256,
        terrain_hypothesis_id=parsed.terrain_hypothesis_id,
        terrain_hypothesis_sha256=parsed.terrain_hypothesis_sha256,
        dem_resolution_m=parsed.dem_resolution_m,
        metrics=metrics,
        observations=tuple(observations),
        unknowns=tuple(unknowns),
        possible_explanations=(
            MISMATCH_EXPLANATIONS if observations else tuple()
        ),
        failure_code=failure_code,
    )


def _metrics(request: TerrainRouteConsistencyRequest) -> TerrainConsistencyMetrics:
    samples = request.samples
    corridor = [
        item.inside_candidate_corridor
        for item in samples
        if item.inside_candidate_corridor is not None
    ]
    slopes = [
        item.slope_degrees for item in samples if item.slope_degrees is not None
    ]
    drainage = [
        item.drainage_pressure
        for item in samples
        if item.drainage_pressure is not None
    ]
    teii = [item.teii for item in samples if item.teii is not None]
    deviation = [
        item.deviation_from_hypothesis_m
        for item in samples
        if item.deviation_from_hypothesis_m is not None
    ]
    return TerrainConsistencyMetrics(
        sample_count=len(samples),
        corridor_evaluated_count=len(corridor),
        outside_corridor_fraction=_fraction(corridor, lambda value: not value),
        slope_evaluated_count=len(slopes),
        extreme_slope_fraction=_fraction(
            slopes,
            lambda value: value >= request.config.extreme_slope_degrees,
        ),
        drainage_evaluated_count=len(drainage),
        drainage_pressure_fraction=_fraction(drainage, lambda value: value > 0),
        teii_evaluated_count=len(teii),
        high_teii_fraction=_fraction(
            teii,
            lambda value: value >= request.config.high_teii_threshold,
        ),
        deviation_evaluated_count=len(deviation),
        median_deviation_from_hypothesis_m=(
            statistics.median(deviation) if deviation else None
        ),
        max_deviation_from_hypothesis_m=max(deviation) if deviation else None,
    )


_SampleValue = TypeVar("_SampleValue")


def _fraction(
    values: list[_SampleValue],
    predicate: Callable[[_SampleValue], bool],
) -> float | None:
    if not values:
        return None
    return sum(1 for value in values if predicate(value)) / len(values)


def _observations(
    request: TerrainRouteConsistencyRequest,
    metrics: TerrainConsistencyMetrics,
) -> list[TerrainConsistencyObservation]:
    definitions = (
        (
            "gpx_exits_candidate_corridor",
            "Sampled GPX points leave the selected candidate corridor band.",
            metrics.corridor_evaluated_count,
            metrics.outside_corridor_fraction,
        ),
        (
            "gpx_crosses_extreme_slope_cell",
            "Sampled GPX points intersect the configured extreme terrain-cost slope band.",
            metrics.slope_evaluated_count,
            metrics.extreme_slope_fraction,
        ),
        (
            "gpx_enters_dem_drainage_pressure",
            "Sampled GPX points intersect DEM-derived drainage-pressure cells.",
            metrics.drainage_evaluated_count,
            metrics.drainage_pressure_fraction,
        ),
        (
            "gpx_intersects_high_teii",
            "Sampled GPX points intersect high TEII evidence cells.",
            metrics.teii_evaluated_count,
            metrics.high_teii_fraction,
        ),
    )
    observations = [
        TerrainConsistencyObservation(
            code=code,
            description=description,
            sample_count=max(1, round(evaluated * fraction)),
            sample_fraction=fraction,
        )
        for code, description, evaluated, fraction in definitions
        if fraction is not None and fraction > 0
    ]
    deviations = [
        sample
        for sample in request.samples
        if sample.deviation_from_hypothesis_m is not None
        and sample.deviation_from_hypothesis_m > request.config.deviation_threshold_m
    ]
    evaluated = metrics.deviation_evaluated_count
    if deviations and evaluated:
        observations.append(
            TerrainConsistencyObservation(
                code="gpx_deviates_from_terrain_hypothesis",
                description=(
                    "Sampled GPX points exceed the configured distance from the "
                    "minimum model-cost trace."
                ),
                sample_count=len(deviations),
                sample_fraction=len(deviations) / evaluated,
            )
        )
    return observations


def _is_anomaly(
    metrics: TerrainConsistencyMetrics,
    config: TerrainRouteConsistencyConfig,
) -> bool:
    return any(
        value is not None and value >= config.anomaly_fraction_threshold
        for value in (
            metrics.outside_corridor_fraction,
            metrics.extreme_slope_fraction,
            metrics.drainage_pressure_fraction,
            metrics.high_teii_fraction,
        )
    )


def _default_unknowns() -> tuple[TerrainConsistencyUnknown, ...]:
    return (
        TerrainConsistencyUnknown(
            code="current_ground_condition_unknown",
            description="Current vegetation, water, surface, and obstruction are unknown.",
        ),
        TerrainConsistencyUnknown(
            code="engineered_feature_unknown",
            description="Bridge, tunnel, rope, ladder, stairs, and engineered tread are unknown.",
        ),
        TerrainConsistencyUnknown(
            code="legal_access_unknown",
            description="Terrain consistency does not determine legal access.",
        ),
        TerrainConsistencyUnknown(
            code="recent_landslide_unknown",
            description="Recent slope failure may post-date the available DEM or GPX.",
        ),
    )


__all__ = [
    "GpxTerrainConsistency",
    "TerrainConsistencySample",
    "TerrainRouteConsistencyConfig",
    "TerrainRouteConsistencyRequest",
    "TerrainRouteConsistencyResult",
    "evaluate_terrain_route_consistency",
]
