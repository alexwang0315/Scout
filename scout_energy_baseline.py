from __future__ import annotations

import math
from datetime import date, timedelta

from scout_energy_models import (
    Confidence,
    EnergyWindowSummary,
    RouteFamilyBaselineProfile,
    ScoutEnergyDataQuality,
    ScoutEnergyReserveBaseline,
    ScoutEnergyReserveTrend,
    WearableActivitySummary,
    aggregate_sha256,
)


ZONE_WEIGHTS = {
    "z1": 1.0,
    "z2": 2.0,
    "z3": 3.0,
    "z4": 4.0,
    "z5": 5.0,
}

MIN_ROUTE_FAMILY_ACTIVITY_COUNT = 2


def build_energy_reserve_baseline(
    activities: list[WearableActivitySummary],
    *,
    reference_date: date | None = None,
    user_profile_ref: str = "local_user.private",
) -> ScoutEnergyReserveBaseline:
    if not activities:
        raise ValueError("at least one wearable activity summary is required")

    resolved_reference_date = reference_date or max(activity.activity_date for activity in activities)
    sorted_activities = sorted(activities, key=lambda activity: activity.activity_date)
    acute = _window_summary(sorted_activities, reference_date=resolved_reference_date, days=7)
    recent = _window_summary(sorted_activities, reference_date=resolved_reference_date, days=28)
    stable = _window_summary(sorted_activities, reference_date=resolved_reference_date, days=90)
    trend = _reserve_trend(sorted_activities, acute=acute, recent=recent, stable=stable)
    source_provider = _aggregate_provider(sorted_activities)
    source_path = _aggregate_source_path(sorted_activities)
    data_quality = _aggregate_data_quality(sorted_activities)

    return ScoutEnergyReserveBaseline(
        source_provider=source_provider,
        source_path=source_path,
        sha256=aggregate_sha256([activity.sha256 for activity in sorted_activities]),
        reference_date=resolved_reference_date,
        user_profile_ref=user_profile_ref,
        activity_count=len(sorted_activities),
        acute_7_day_load=acute,
        recent_28_day_baseline=recent,
        stable_90_day_baseline=stable,
        route_family_profiles=_route_family_profiles(sorted_activities),
        reserve_trend=trend,
        data_quality=data_quality,
    )


def internal_load_score(activity: WearableActivitySummary) -> float:
    zone_score = sum(activity.heart_rate.zone_minutes.get(zone, 0.0) * weight for zone, weight in ZONE_WEIGHTS.items())
    duration_score = activity.moving_time_s / 60.0
    rpe_score = (activity.session_rpe or 0.0) * (activity.duration_s / 60.0)
    if zone_score > 0:
        base = zone_score
    elif rpe_score > 0:
        base = rpe_score
    else:
        base = duration_score
    missing_penalty = min(activity.data_quality.missing_hr_seconds / 3600.0, 3.0) * 5.0
    return round(base + missing_penalty, 2)


def _window_summary(
    activities: list[WearableActivitySummary],
    *,
    reference_date: date,
    days: int,
) -> EnergyWindowSummary:
    start_date = reference_date - timedelta(days=days - 1)
    in_window = [activity for activity in activities if start_date <= activity.activity_date <= reference_date]
    load_sum = round(sum(internal_load_score(activity) for activity in in_window), 2)
    activity_count = len(in_window)
    return EnergyWindowSummary(
        window_days=days,
        activity_count=activity_count,
        load_sum=load_sum,
        mean_activity_load=round(load_sum / activity_count, 2) if activity_count else 0.0,
        daily_average_load=round(load_sum / days, 2),
        start_date=start_date,
        end_date=reference_date,
    )


def _reserve_trend(
    activities: list[WearableActivitySummary],
    *,
    acute: EnergyWindowSummary,
    recent: EnergyWindowSummary,
    stable: EnergyWindowSummary,
) -> ScoutEnergyReserveTrend:
    baseline_mean = stable.mean_activity_load or recent.mean_activity_load or 1.0
    acute_ratio = acute.mean_activity_load / baseline_mean if baseline_mean else 0.0
    recent_ratio = recent.mean_activity_load / baseline_mean if baseline_mean else 0.0
    acute_z = round(acute_ratio - 1.0, 3)
    recovery_debt_z = _provider_recovery_debt(activities)
    reserve_score = _clamp_score(round(50 - acute_z * 18 - recovery_debt_z * 10))
    band = _reserve_band(acute_ratio, recovery_debt_z)
    confidence = _trend_confidence(activities, stable)
    explanations = [
        "baseline-relative advisory trend only",
        f"7-day active-day load is {acute_ratio:.2f}x the 90-day active-day baseline",
        f"28-day active-day load is {recent_ratio:.2f}x the 90-day active-day baseline",
    ]
    if recovery_debt_z > 0:
        explanations.append("provider recovery values contributed as source values, not Scout truth")
    return ScoutEnergyReserveTrend(
        current_band=band,
        reserve_score=reserve_score,
        acute_load_ratio=round(acute_ratio, 3),
        acute_load_z=acute_z,
        recovery_debt_z=round(recovery_debt_z, 3),
        confidence=confidence,
        explanations=explanations,
    )


def _provider_recovery_debt(activities: list[WearableActivitySummary]) -> float:
    values: list[float] = []
    for activity in activities:
        provider = activity.body_energy_provider_values
        if provider.garmin_body_battery_end is not None:
            values.append(max(0.0, (50.0 - provider.garmin_body_battery_end) / 50.0))
        if provider.garmin_stress_avg is not None:
            values.append(max(0.0, (provider.garmin_stress_avg - 50.0) / 50.0))
    if not values:
        return 0.0
    return sum(values) / len(values)


def _reserve_band(acute_ratio: float, recovery_debt_z: float):
    combined = acute_ratio + recovery_debt_z * 0.5
    if combined >= 2.1:
        return "stop_and_check"
    if combined >= 1.6:
        return "rest_suggested"
    if combined >= 1.2:
        return "watch"
    return "normal"


def _trend_confidence(activities: list[WearableActivitySummary], stable: EnergyWindowSummary) -> Confidence:
    if stable.activity_count >= 10 and all(activity.data_quality.heart_rate_confidence != "low" for activity in activities):
        return "high"
    if stable.activity_count >= 3:
        return "medium"
    return "low"


def _aggregate_data_quality(activities: list[WearableActivitySummary]) -> ScoutEnergyDataQuality:
    missing_hr_seconds = sum(activity.data_quality.missing_hr_seconds for activity in activities)
    heart_rate_confidence = _min_confidence(activity.data_quality.heart_rate_confidence for activity in activities)
    gps_confidence = _min_confidence(activity.data_quality.gps_confidence for activity in activities)
    provider_confidence = _min_confidence(activity.data_quality.provider_value_confidence for activity in activities)
    limitations = sorted({limitation for activity in activities for limitation in activity.data_quality.limitations})
    if missing_hr_seconds:
        limitations.append("one or more activities contain missing heart-rate intervals")
    return ScoutEnergyDataQuality(
        heart_rate_confidence=heart_rate_confidence,
        gps_confidence=gps_confidence,
        missing_hr_seconds=missing_hr_seconds,
        missing_hr_intervals=[],
        provider_value_confidence=provider_confidence,
        limitations=limitations,
    )


def _route_family_profiles(
    activities: list[WearableActivitySummary],
) -> list[RouteFamilyBaselineProfile]:
    grouped: dict[str, list[WearableActivitySummary]] = {}
    for activity in activities:
        grouped.setdefault(_route_family(activity), []).append(activity)
    profiles = [
        _route_family_profile(route_family, family_activities)
        for route_family, family_activities in sorted(grouped.items())
        if len(family_activities) >= MIN_ROUTE_FAMILY_ACTIVITY_COUNT
    ]
    return profiles


def _route_family_profile(
    route_family: str,
    activities: list[WearableActivitySummary],
) -> RouteFamilyBaselineProfile:
    effort_units = [_route_effort_units(activity) for activity in activities]
    moving_time_per_effort = [
        (activity.moving_time_s / 60.0) / effort
        for activity, effort in zip(activities, effort_units)
        if effort > 0
    ]
    hr_load_per_effort = [
        internal_load_score(activity) / effort
        for activity, effort in zip(activities, effort_units)
        if effort > 0
    ]
    fatigue_decay = [
        activity.late_activity_fatigue_decay
        for activity in activities
        if activity.late_activity_fatigue_decay is not None
    ]
    return RouteFamilyBaselineProfile(
        route_family=route_family,
        activity_count=len(activities),
        route_effort_units_p50=round(_median(effort_units), 3),
        moving_time_per_effort_p50=round(_median(moving_time_per_effort), 3),
        heart_rate_load_per_effort_p50=round(_median(hr_load_per_effort), 3),
        late_activity_fatigue_decay_p50=round(_median(fatigue_decay), 3),
        confidence=_route_family_confidence(activities),
        limitations=[
            "route-family profile is local baseline context, not a public capability label",
            "route-effort units in this slice normalize distance, ascent, and descent only; altitude, pack load, technical terrain, season, weather, daylight, traffic, cost, road condition, and equipment remain human-review context",
            f"minimum activity count for this alpha profile is {MIN_ROUTE_FAMILY_ACTIVITY_COUNT}",
        ],
    )


def _route_family_confidence(activities: list[WearableActivitySummary]) -> Confidence:
    if len(activities) >= 5 and all(activity.data_quality.gps_confidence != "low" for activity in activities):
        return "high"
    if len(activities) >= MIN_ROUTE_FAMILY_ACTIVITY_COUNT:
        return "medium"
    return "low"


def _route_family(activity: WearableActivitySummary) -> str:
    if activity.route_family:
        return activity.route_family
    effort = _route_effort_units(activity)
    if activity.activity_type in {"cross_training", "pilates", "strength", "strength_training"}:
        return "cross_training"
    if activity.activity_type in {"hike", "hiking"}:
        if activity.ascent_m >= 800 or effort >= 18:
            return "mountain_hike"
        return "local_day_hike"
    if activity.activity_type in {"walk", "walking"} and activity.ascent_m < 150 and effort < 8:
        return "local_walk"
    if activity.ascent_m >= 800 or effort >= 18:
        return "mountain_hike"
    if activity.ascent_m >= 250 or effort >= 8:
        return "local_day_hike"
    return "light_outdoor_activity"


def _route_effort_units(activity: WearableActivitySummary) -> float:
    return activity.distance_m / 1000.0 + activity.ascent_m / 100.0 + activity.descent_m / 200.0


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2.0


def _min_confidence(values) -> Confidence:
    order = {"low": 0, "medium": 1, "high": 2}
    return min(values, key=lambda value: order[value])


def _aggregate_provider(activities: list[WearableActivitySummary]) -> str:
    providers = sorted({activity.source_provider for activity in activities})
    return providers[0] if len(providers) == 1 else "mixed_wearable_activity_summaries"


def _aggregate_source_path(activities: list[WearableActivitySummary]) -> str:
    paths = sorted({activity.source_path for activity in activities})
    if len(paths) == 1:
        return paths[0]
    common_prefix = _common_directory(paths)
    return f"aggregate:{common_prefix}"


def _common_directory(paths: list[str]) -> str:
    split_paths = [path.split("/")[:-1] for path in paths]
    prefix: list[str] = []
    for parts in zip(*split_paths):
        if len(set(parts)) != 1:
            break
        prefix.append(parts[0])
    return "/".join(prefix) if prefix else "wearable_activity_summaries"


def _clamp_score(value: int) -> int:
    if math.isnan(value):
        return 50
    return max(0, min(100, value))
