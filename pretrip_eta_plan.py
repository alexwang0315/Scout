from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from pretrip_models import PaceMultiplierBasis, PreTripPackage, PreTripRouteGuideTimingCandidate


class PreTripHumanProvidedRouteStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stats_id: str
    record_date: str
    distance_m: float = Field(ge=0.0)
    total_elapsed_minutes: int = Field(ge=0)
    elevation_delta_m: float | None = None
    total_ascent_m: float = Field(ge=0.0)
    total_descent_m: float = Field(ge=0.0)
    pace_multiplier_basis: PaceMultiplierBasis = PaceMultiplierBasis.TOTAL_ELAPSED_TIME
    route_scope_note: str = ""


class PreTripEtaPlanningAssumption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assumption_id: str
    planned_start_time: str
    planned_start_source: str
    planned_start_offset_minutes: int
    day1_target_node_name: str
    turn_back_checkpoint_node_name: str
    target_eta: str | None = None
    turn_back_checkpoint_eta: str | None = None
    return_to_entry_eta_if_turn_back_at_checkpoint: str | None = None
    elapsed_time_policy: str
    daylight_policy_status: str = "not_evaluated_requires_sun_window"
    team_multiplier_status: str = "not_derived"
    human_provided_route_stats: PreTripHumanProvidedRouteStats | None = None
    notes: list[str] = Field(default_factory=list)


class PreTripEtaCheckpointEstimate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    estimate_id: str
    from_node_name: str
    to_node_name: str
    eta: str
    cumulative_duration_minutes: int = Field(ge=0)
    segment_duration_minutes: int = Field(ge=0)
    source_candidate_id: str
    route_guide_time_kind: str
    elapsed_time_policy: str


class PreTripEtaPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str
    project_id: str
    assumption: PreTripEtaPlanningAssumption
    estimates: list[PreTripEtaCheckpointEstimate] = Field(default_factory=list)


def build_chilai_day1_eta_plan(
    package: PreTripPackage | dict[str, Any],
    *,
    start_offset_minutes: int = 60,
    day1_target_node_name: str = "天池山莊",
    turn_back_checkpoint_node_name: str = "雲海保線所",
    local_timezone: str = "Asia/Taipei",
    human_stats: PreTripHumanProvidedRouteStats | dict[str, Any] | None = None,
) -> PreTripEtaPlan:
    pretrip_package = (
        package if isinstance(package, PreTripPackage) else PreTripPackage.model_validate(package)
    )
    if pretrip_package.route_summary.started_at is None:
        raise ValueError("route_summary.started_at is required to derive planned_start_time")

    start_time = _parse_gpx_time(pretrip_package.route_summary.started_at).astimezone(
        ZoneInfo(local_timezone)
    ) + timedelta(minutes=start_offset_minutes)
    estimates = _eta_estimates_to_target(
        pretrip_package.route_guide_timing_candidates,
        start_time=start_time,
        target_node_name=day1_target_node_name,
    )

    turn_back_eta = _estimate_eta_for_node(estimates, turn_back_checkpoint_node_name)
    target_eta = _estimate_eta_for_node(estimates, day1_target_node_name)
    return_eta = _return_eta_if_turn_back(
        pretrip_package.route_guide_timing_candidates,
        checkpoint_node_name=turn_back_checkpoint_node_name,
        checkpoint_eta=turn_back_eta,
    )

    stats = (
        None
        if human_stats is None
        else (
            human_stats
            if isinstance(human_stats, PreTripHumanProvidedRouteStats)
            else PreTripHumanProvidedRouteStats.model_validate(human_stats)
        )
    )
    team_multiplier_status = _team_multiplier_status(pretrip_package, stats)

    assumption = PreTripEtaPlanningAssumption(
        assumption_id=f"eta_assumption.{pretrip_package.project_id}.day1.v0",
        planned_start_time=start_time.isoformat(),
        planned_start_source="route_summary.started_at_plus_offset",
        planned_start_offset_minutes=start_offset_minutes,
        day1_target_node_name=day1_target_node_name,
        turn_back_checkpoint_node_name=turn_back_checkpoint_node_name,
        target_eta=target_eta,
        turn_back_checkpoint_eta=turn_back_eta,
        return_to_entry_eta_if_turn_back_at_checkpoint=return_eta,
        elapsed_time_policy="total_elapsed_time_including_normal_rest",
        team_multiplier_status=team_multiplier_status,
        human_provided_route_stats=stats,
        notes=[
            "ETA uses reviewed route-guide timing candidates only; no sun-window or dark-arrival calculation is performed in this slice.",
            "When multiplier basis is unknown, planning remains conservative and uses total elapsed time including normal rest.",
        ],
    )
    return PreTripEtaPlan(
        plan_id=f"eta_plan.{pretrip_package.project_id}.day1.v0",
        project_id=pretrip_package.project_id,
        assumption=assumption,
        estimates=estimates,
    )


def _eta_estimates_to_target(
    timing_candidates: list[PreTripRouteGuideTimingCandidate],
    *,
    start_time: datetime,
    target_node_name: str,
) -> list[PreTripEtaCheckpointEstimate]:
    estimates: list[PreTripEtaCheckpointEstimate] = []
    current_time = start_time
    current_node: str | None = None
    cumulative_minutes = 0

    for candidate in timing_candidates:
        if candidate.route_branch != "main":
            continue
        if candidate.route_guide_segment_time_minutes is None:
            continue
        if current_node is None:
            current_node = candidate.from_node_name
        if candidate.from_node_name != current_node:
            continue

        duration = _estimated_duration_minutes(candidate)
        current_time += timedelta(minutes=duration)
        cumulative_minutes += duration
        estimates.append(
            PreTripEtaCheckpointEstimate(
                estimate_id=f"eta.{candidate.candidate_id}",
                from_node_name=candidate.from_node_name or "",
                to_node_name=candidate.to_node_name or "",
                eta=current_time.isoformat(),
                cumulative_duration_minutes=cumulative_minutes,
                segment_duration_minutes=duration,
                source_candidate_id=candidate.candidate_id,
                route_guide_time_kind="segment",
                elapsed_time_policy="total_elapsed_time_including_normal_rest",
            )
        )
        current_node = candidate.to_node_name
        if current_node == target_node_name:
            break

    return estimates


def _estimated_duration_minutes(candidate: PreTripRouteGuideTimingCandidate) -> int:
    if candidate.route_guide_segment_time_minutes is None:
        return 0
    multiplier = candidate.team_route_guide_multiplier or candidate.personal_route_guide_multiplier or 1.0
    minutes = (candidate.route_guide_segment_time_minutes * multiplier) + candidate.fixed_rest_minutes
    return int(round(minutes * candidate.conservative_long_day_adjustment))


def _estimate_eta_for_node(
    estimates: list[PreTripEtaCheckpointEstimate],
    node_name: str,
) -> str | None:
    for estimate in estimates:
        if estimate.to_node_name == node_name:
            return estimate.eta
    return None


def _return_eta_if_turn_back(
    timing_candidates: list[PreTripRouteGuideTimingCandidate],
    *,
    checkpoint_node_name: str,
    checkpoint_eta: str | None,
) -> str | None:
    if checkpoint_eta is None:
        return None
    for candidate in timing_candidates:
        if (
            candidate.to_node_name == checkpoint_node_name
            and candidate.route_guide_return_time_minutes is not None
        ):
            checkpoint_time = datetime.fromisoformat(checkpoint_eta)
            return (checkpoint_time + timedelta(minutes=candidate.route_guide_return_time_minutes)).isoformat()
    return None


def _team_multiplier_status(
    package: PreTripPackage,
    stats: PreTripHumanProvidedRouteStats | None,
) -> str:
    if stats is None:
        return "not_derived_no_human_stats"
    fixture_distance = round(package.route_summary.distance_m)
    provided_distance = round(stats.distance_m)
    if abs(fixture_distance - provided_distance) > 500:
        return "not_derived_route_scope_mismatch"
    return "ready_for_manual_review"


def _parse_gpx_time(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=ZoneInfo("UTC"))
    return parsed
