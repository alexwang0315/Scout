from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from pretrip_models import PaceMultiplierBasis, PreTripRouteGuideTimingCandidate


RouteGuideTimeKind = Literal["segment", "ascent", "descent", "return"]
MultiplierSource = Literal[
    "team_route_guide_multiplier",
    "personal_route_guide_multiplier",
    "default_identity_multiplier",
]
ElapsedTimePolicy = Literal[
    "total_elapsed_time",
    "moving_time_plus_fixed_rest",
    "total_elapsed_time_including_fixed_rest",
]


class PreTripTimingMeasurementCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    measurement_id: str
    source_candidate_id: str
    label: str
    route_branch: str | None = None
    segment_candidate_id: str | None = None
    from_node_name: str | None = None
    to_node_name: str | None = None
    movement_label: str | None = None
    route_guide_time_kind: RouteGuideTimeKind
    base_route_guide_duration_minutes: int = Field(ge=0)
    applied_multiplier: float = Field(gt=0.0)
    multiplier_source: MultiplierSource
    pace_multiplier_basis: PaceMultiplierBasis
    fixed_rest_minutes: int = Field(ge=0)
    conservative_long_day_adjustment: float = Field(ge=1.0)
    estimated_segment_duration_minutes: int = Field(ge=0)
    elapsed_time_policy: ElapsedTimePolicy
    eta_at_checkpoint: str | None = None
    eta_at_camp_or_overnight_point: str | None = None
    dark_arrival_margin_minutes: int | None = None
    source_refs: list[str] = Field(default_factory=list)
    planned_vs_actual_calibration_refs: list[str] = Field(default_factory=list)
    notes: str = ""


def generate_timing_measurement_candidates(
    timing_candidates: Iterable[PreTripRouteGuideTimingCandidate],
) -> list[PreTripTimingMeasurementCandidate]:
    measurements: list[PreTripTimingMeasurementCandidate] = []
    for candidate in timing_candidates:
        measurement = timing_measurement_candidate(candidate)
        if measurement is not None:
            measurements.append(measurement)
    return measurements


def timing_measurement_candidate(
    candidate: PreTripRouteGuideTimingCandidate,
) -> PreTripTimingMeasurementCandidate | None:
    base_time = _base_route_guide_time(candidate)
    if base_time is None:
        return None

    time_kind, base_minutes = base_time
    multiplier_source, multiplier = _multiplier(candidate)
    adjusted_minutes = (
        (base_minutes * multiplier) + candidate.fixed_rest_minutes
    ) * candidate.conservative_long_day_adjustment

    return PreTripTimingMeasurementCandidate(
        measurement_id=f"measurement.pretrip_timing.{candidate.candidate_id}.{time_kind}",
        source_candidate_id=candidate.candidate_id,
        label=f"Estimated timing: {candidate.label}",
        route_branch=candidate.route_branch,
        segment_candidate_id=candidate.segment_candidate_id,
        from_node_name=candidate.from_node_name,
        to_node_name=candidate.to_node_name,
        movement_label=candidate.movement_label,
        route_guide_time_kind=time_kind,
        base_route_guide_duration_minutes=base_minutes,
        applied_multiplier=multiplier,
        multiplier_source=multiplier_source,
        pace_multiplier_basis=candidate.pace_multiplier_basis,
        fixed_rest_minutes=candidate.fixed_rest_minutes,
        conservative_long_day_adjustment=candidate.conservative_long_day_adjustment,
        estimated_segment_duration_minutes=int(round(adjusted_minutes)),
        elapsed_time_policy=_elapsed_time_policy(candidate.pace_multiplier_basis),
        eta_at_checkpoint=candidate.eta_at_checkpoint,
        eta_at_camp_or_overnight_point=candidate.eta_at_camp_or_overnight_point,
        dark_arrival_margin_minutes=candidate.dark_arrival_margin_minutes,
        source_refs=list(candidate.source_refs),
        planned_vs_actual_calibration_refs=list(candidate.planned_vs_actual_calibration_refs),
        notes=(
            "Deterministic pre-trip timing measurement candidate; not an ObservedFact "
            "and not written to the Phase 2 Brain by this converter."
        ),
    )


def _base_route_guide_time(
    candidate: PreTripRouteGuideTimingCandidate,
) -> tuple[RouteGuideTimeKind, int] | None:
    if candidate.route_guide_segment_time_minutes is not None:
        return "segment", candidate.route_guide_segment_time_minutes
    if candidate.route_guide_ascent_time_minutes is not None:
        return "ascent", candidate.route_guide_ascent_time_minutes
    if candidate.route_guide_descent_time_minutes is not None:
        return "descent", candidate.route_guide_descent_time_minutes
    if candidate.route_guide_return_time_minutes is not None:
        return "return", candidate.route_guide_return_time_minutes
    return None


def _multiplier(candidate: PreTripRouteGuideTimingCandidate) -> tuple[MultiplierSource, float]:
    if candidate.team_route_guide_multiplier is not None:
        return "team_route_guide_multiplier", candidate.team_route_guide_multiplier
    if candidate.personal_route_guide_multiplier is not None:
        return "personal_route_guide_multiplier", candidate.personal_route_guide_multiplier
    return "default_identity_multiplier", 1.0


def _elapsed_time_policy(basis: PaceMultiplierBasis) -> ElapsedTimePolicy:
    if basis == PaceMultiplierBasis.MOVING_TIME_ONLY:
        return "moving_time_plus_fixed_rest"
    if basis == PaceMultiplierBasis.MIXED_UNKNOWN:
        return "total_elapsed_time_including_fixed_rest"
    return "total_elapsed_time"
