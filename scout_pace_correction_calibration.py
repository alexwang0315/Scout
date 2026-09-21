"""Candidate-only Pace Fit power calibration and route schedule helpers.

The dashboard correction is deliberately a route-scoped adaptive variable.  It
starts at a neutral ratio of one when no successful climb receipt exists, then
uses a transparent equal-weight update after each successful climb whose route
and Body Index power estimates are expressed in the same declared domain.

This module never treats HealthExport active-energy watts as mechanical power,
never infers a correction from activity counts, and never writes runtime safety
truth.  Pandolf's load-carriage equation is used only as a reproducible
metabolic-power estimate for the two sides of the ratio.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_PACE_CORRECTION_CALIBRATION_REF = "outputs/pace_correction_calibration.json"
PACE_CORRECTION_CALIBRATION_SCHEMA_VERSION = "scout_pace_correction_calibration.v1"
PANDOLF_POWER_DOMAIN = "pandolf_metabolic_power_w_estimate"
PANDOLF_PRIMARY_SOURCE = "https://pubmed.ncbi.nlm.nih.gov/908672/"
PANDOLF_VALIDATION_SOURCE = (
    "https://journals.physiology.org/doi/10.1152/japplphysiol.00504.2017"
)
DEFAULT_PRIOR_WEIGHT = 1.0


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _round(value: float | None, digits: int = 6) -> float | None:
    return round(value, digits) if value is not None and math.isfinite(value) else None


def _positive(value: Any) -> float | None:
    number = _finite(value)
    return number if number is not None and number > 0 else None


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_project_id(project_id: Any) -> str:
    value = str(project_id or "").strip()
    return value or "unknown_project"


def _safe_ref_list(value: Any, *, limit: int = 16) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        values = list(value)
    else:
        values = []
    return [str(item) for item in values if str(item).strip()][:limit]


def pandolf_metabolic_power_w(
    speed_mps: float,
    *,
    body_mass_kg: float = 70.0,
    load_kg: float = 0.0,
    grade_fraction: float = 0.0,
    terrain_factor: float = 1.0,
    psychological_stress_multiplier: float = 1.0,
) -> dict[str, Any]:
    """Return a Pandolf metabolic-power estimate in watts.

    Pandolf et al. express gradient as percent and velocity as m/s:

    ``M = 1.5W + 2(W+L)(L/W)^2 + eta(W+L)(1.5V^2 + 0.35VG)``.

    The psychological multiplier is intentionally an explicit scenario input;
    it is not a physiological measurement and is never inferred from a GPX.
    ``M`` is metabolic power, not external mechanical power and not a watch
    active-energy observation.
    """

    speed = _positive(speed_mps)
    mass = _positive(body_mass_kg)
    load = _finite(load_kg)
    grade = _finite(grade_fraction)
    terrain = _positive(terrain_factor)
    stress = _positive(psychological_stress_multiplier)
    if speed is None or mass is None:
        return {"status": "unavailable", "reason": "speed_or_body_mass_unavailable"}
    if load is None or load < 0:
        return {"status": "unavailable", "reason": "load_unavailable_or_negative"}
    if grade is None or terrain is None or stress is None:
        return {"status": "unavailable", "reason": "route_condition_parameter_unavailable"}

    grade_percent = grade * 100.0
    base_power = (
        1.5 * mass
        + 2.0 * (mass + load) * (load / mass) ** 2
        + terrain
        * (mass + load)
        * (1.5 * speed**2 + 0.35 * speed * grade_percent)
    )
    power = max(0.0, base_power * stress)
    return {
        "status": "available",
        "power_w": _round(power, 3),
        "power_domain": PANDOLF_POWER_DOMAIN,
        "speed_mps": _round(speed, 6),
        "body_mass_kg": _round(mass, 3),
        "body_mass_basis": "user_assumption",
        "load_kg": _round(load, 3),
        "grade_fraction": _round(grade, 6),
        "grade_percent": _round(grade_percent, 3),
        "terrain_factor": _round(terrain, 6),
        "psychological_stress_multiplier": _round(stress, 6),
        "formula": (
            "M=1.5W+2(W+L)(L/W)^2+eta(W+L)(1.5V^2+0.35VG); "
            "V=m/s, G=percent grade"
        ),
        "source": PANDOLF_PRIMARY_SOURCE,
        "validation_context": PANDOLF_VALIDATION_SOURCE,
        "not_mechanical_power": True,
        "not_provider_active_energy": True,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def architecture_route_bin_power_estimate_w(
    speed_mps: float,
    *,
    body_mass_kg: float = 70.0,
    load_kg: float = 0.0,
    grade_fraction: float = 0.0,
    terrain_factor: float = 1.0,
    psychological_stress_multiplier: float = 1.0,
) -> dict[str, Any]:
    """Estimate one Architecture route-bin metabolic power.

    The signed-grade Pandolf equation is useful for positive grade, but its
    linear grade term can become negative on steep descents.  Clamping that
    result to zero would incorrectly claim that a person moving downhill has
    no energy cost.  For a negative grade, this candidate model keeps the
    fixed reference schedule speed and applies the horizontal-motion ratio
    ``cos(atan(abs(grade)))`` to the same-speed level-ground estimate.

    This is deliberately exposed as a model assumption, not as a claim that
    downhill eccentric metabolic cost has been identified from GPX alone.
    ``power_w`` remains Pandolf metabolic power, not mechanical power.
    """

    speed = _positive(speed_mps)
    grade = _finite(grade_fraction)
    if speed is None or grade is None:
        return {
            "status": "unavailable",
            "reason": "speed_or_grade_unavailable",
            "power_domain": PANDOLF_POWER_DOMAIN,
            "candidate_only": True,
            "runtime_safety_truth": False,
        }

    grade_angle_rad = math.atan(abs(grade))
    horizontal_component_ratio = math.cos(grade_angle_rad)
    if grade < 0:
        level = pandolf_metabolic_power_w(
            speed,
            body_mass_kg=body_mass_kg,
            load_kg=load_kg,
            grade_fraction=0.0,
            terrain_factor=terrain_factor,
            psychological_stress_multiplier=psychological_stress_multiplier,
        )
        level_power = _positive(level.get("power_w"))
        if level_power is None:
            return {
                **level,
                "status": "unavailable",
                "reason": "level_ground_reference_unavailable",
                "grade_fraction": _round(grade, 6),
                "grade_percent": _round(grade * 100.0, 3),
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        result = dict(level)
        result.update(
            {
                "power_w": _round(level_power * horizontal_component_ratio, 3),
                "grade_fraction": _round(grade, 6),
                "grade_percent": _round(grade * 100.0, 3),
                "grade_angle_degrees": _round(math.degrees(grade_angle_rad), 3),
                "horizontal_component_ratio": _round(horizontal_component_ratio, 6),
                "horizontal_component_speed_mps": _round(
                    speed * horizontal_component_ratio, 6
                ),
                "grade_model": "downhill_horizontal_component_cosine_floor",
                "grade_model_basis": "user_requested_candidate_assumption",
                "reference_grade_fraction": 0.0,
                "formula_note": (
                    "downhill power = same-speed level-ground Pandolf power x "
                    "cos(atan(abs(signed grade ratio)))"
                ),
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )
        return result

    result = pandolf_metabolic_power_w(
        speed,
        body_mass_kg=body_mass_kg,
        load_kg=load_kg,
        grade_fraction=grade,
        terrain_factor=terrain_factor,
        psychological_stress_multiplier=psychological_stress_multiplier,
    )
    result.update(
        {
            "grade_angle_degrees": _round(math.degrees(grade_angle_rad), 3),
            "horizontal_component_ratio": _round(horizontal_component_ratio, 6),
            "horizontal_component_speed_mps": _round(
                speed * horizontal_component_ratio, 6
            ),
            "grade_model": "pandolf_signed_grade_uphill_or_level",
            "grade_model_basis": "pandolf_reference_equation",
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
    )
    return result


def build_body_flat_power_reference(
    flat_speed_by_mode: Mapping[str, Any] | None,
    *,
    body_mass_kg: float = 70.0,
) -> dict[str, Any]:
    """Build the Body Index flat reference in the same domain as route power."""

    walking = (flat_speed_by_mode or {}).get("walking")
    speed = _positive(walking.get("median_speed_mps") if isinstance(walking, Mapping) else None)
    if speed is None:
        return {
            "status": "unavailable",
            "reason": "walking_flat_speed_unavailable",
            "power_domain": PANDOLF_POWER_DOMAIN,
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
    result = pandolf_metabolic_power_w(
        speed,
        body_mass_kg=body_mass_kg,
        load_kg=0.0,
        grade_fraction=0.0,
        terrain_factor=1.0,
        psychological_stress_multiplier=1.0,
    )
    return {
        **result,
        "reference_role": "Body Index personal flat total power",
        "mode": "walking",
        "scenario": {
            "grade_degrees": 0,
            "grade_fraction": 0.0,
            "load_kg": 0.0,
            "terrain_factor": 1.0,
            "psychological_stress_multiplier": 1.0,
            "clothing": "light clothing assumption",
        },
        "source_ref": "body_index.flat_speed_by_mode.walking.median_speed_mps",
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _architecture_route_energy_bins(
    vectors: Sequence[Mapping[str, Any]],
    *,
    body_mass_kg: float,
    load_kg: float,
    terrain_factor: float,
    psychological_stress_multiplier: float,
    speed_key: str,
) -> tuple[list[dict[str, Any]], int, int]:
    """Return usable route-bin energy records and explicit skip counters."""

    bins: list[dict[str, Any]] = []
    skipped_bin_count = 0
    downhill_bin_count = 0
    for vector in vectors:
        if not isinstance(vector, Mapping):
            skipped_bin_count += 1
            continue
        start = _finite(vector.get("start_distance_m"))
        end = _finite(vector.get("end_distance_m"))
        distance = (end - start) if start is not None and end is not None else None
        speeds = vector.get("reference_speed_mps")
        if not isinstance(speeds, Mapping):
            speeds = {}
        speed = _positive(speeds.get(speed_key))
        if speed is None:
            kmh = vector.get("reference_speed_kmh")
            kmh = kmh.get(speed_key) if isinstance(kmh, Mapping) else None
            kmh_value = _positive(kmh)
            speed = kmh_value / 3.6 if kmh_value is not None else None
        if distance is None or distance <= 0 or speed is None:
            skipped_bin_count += 1
            continue
        grade = _finite(vector.get("signed_grade_ratio_p50"))
        if grade is None:
            skipped_bin_count += 1
            continue
        vector_terrain = _positive(vector.get("terrain_factor")) or terrain_factor
        vector_stress = (
            _positive(vector.get("psychological_stress_multiplier"))
            or psychological_stress_multiplier
        )
        estimate = architecture_route_bin_power_estimate_w(
            speed,
            body_mass_kg=body_mass_kg,
            load_kg=load_kg,
            grade_fraction=grade,
            terrain_factor=vector_terrain,
            psychological_stress_multiplier=vector_stress,
        )
        power = _positive(estimate.get("power_w"))
        if power is None:
            skipped_bin_count += 1
            continue
        duration_s = distance / speed
        if grade < 0:
            downhill_bin_count += 1
        bins.append(
            {
                "route_bin_id": vector.get("route_bin_id"),
                "start_distance_m": start,
                "end_distance_m": end,
                "distance_m": distance,
                "speed_mps": speed,
                "grade_fraction": grade,
                "power_w": power,
                "duration_s": duration_s,
                "energy_j": power * duration_s,
                "grade_model": estimate.get("grade_model"),
                "horizontal_component_ratio": estimate.get(
                    "horizontal_component_ratio"
                ),
            }
        )
    return bins, skipped_bin_count, downhill_bin_count


def architecture_route_power_summary(
    vectors: Sequence[Mapping[str, Any]],
    *,
    body_mass_kg: float = 70.0,
    load_kg: float = 0.0,
    terrain_factor: float = 1.0,
    psychological_stress_multiplier: float = 1.0,
    speed_key: str = "p50",
    source_ref: str = "route_architecture.segment_demand_vectors",
) -> dict[str, Any]:
    """Estimate time-weighted route metabolic power from Architecture vectors.

    Reference speed is the GPX-derived schedule speed.  The function does not
    alter that schedule; it only provides a route-condition power estimate that
    a successful-climb receipt may use for calibration.
    """

    bins, skipped_bin_count, downhill_bin_count = _architecture_route_energy_bins(
        vectors,
        body_mass_kg=body_mass_kg,
        load_kg=load_kg,
        terrain_factor=terrain_factor,
        psychological_stress_multiplier=psychological_stress_multiplier,
        speed_key=speed_key,
    )
    total_energy_j = sum(float(item["energy_j"]) for item in bins)
    total_duration_s = sum(float(item["duration_s"]) for item in bins)
    covered_distance_m = sum(float(item["distance_m"]) for item in bins)
    usable_bin_count = len(bins)

    average_power = total_energy_j / total_duration_s if total_duration_s > 0 else None
    return {
        "status": "available" if usable_bin_count else "unavailable",
        "power_domain": PANDOLF_POWER_DOMAIN,
        "route_total_power_w": _round(average_power, 3),
        "route_total_energy_kj": _round(total_energy_j / 1000.0, 3),
        "route_duration_s": _round(total_duration_s, 3),
        "covered_distance_m": _round(covered_distance_m, 3),
        "usable_bin_count": usable_bin_count,
        "skipped_bin_count": skipped_bin_count,
        "downhill_bin_count": downhill_bin_count,
        "downhill_model": "cosine_horizontal_component_floor",
        "downhill_model_basis": "user_requested_candidate_assumption",
        "speed_basis": f"Architecture reference/golden GPX schedule speed {speed_key}",
        "condition_inputs": {
            "body_mass_kg": body_mass_kg,
            "body_mass_basis": "user_assumption",
            "load_kg": load_kg,
            "terrain_factor": terrain_factor,
            "terrain_factor_basis": "explicit Architecture input or neutral prior 1.0",
            "psychological_stress_multiplier": psychological_stress_multiplier,
            "psychological_stress_basis": "explicit scenario input only; not inferred from GPX",
        },
        "source_ref": source_ref,
        "formula_source": PANDOLF_PRIMARY_SOURCE,
        "validation_context": PANDOLF_VALIDATION_SOURCE,
        "not_mechanical_power": True,
        "not_watch_active_energy": True,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _mission_day_bounds(day: Mapping[str, Any]) -> tuple[float | None, float | None, str]:
    replay = day.get("reference_replay")
    replay = replay if isinstance(replay, Mapping) else {}
    start_payload = replay.get("start")
    end_payload = replay.get("end")
    start_payload = start_payload if isinstance(start_payload, Mapping) else {}
    end_payload = end_payload if isinstance(end_payload, Mapping) else {}

    def first_finite(*values: Any) -> float | None:
        for value in values:
            number = _finite(value)
            if number is not None:
                return number
        return None

    start = first_finite(
        start_payload.get("route_order_m"),
        day.get("route_start_distance_m"),
        day.get("start_distance_m"),
    )
    end = first_finite(
        end_payload.get("route_order_m"),
        day.get("route_end_distance_m"),
        day.get("end_distance_m"),
    )
    boundary_source = (
        "mission_day_estimates.reference_replay.start/end.route_order_m"
        if start_payload.get("route_order_m") is not None
        and end_payload.get("route_order_m") is not None
        else "mission_day_estimates.route_start_distance_m/route_end_distance_m"
    )
    return start, end, boundary_source


def architecture_route_daily_energy_summary(
    vectors: Sequence[Mapping[str, Any]],
    eta: Mapping[str, Any] | None,
    *,
    body_mass_kg: float = 70.0,
    load_kg: float = 0.0,
    terrain_factor: float = 1.0,
    psychological_stress_multiplier: float = 1.0,
    speed_key: str = "p50",
    source_ref: str = "outputs/reference_pace_energy_analysis.json#route_bins",
    eta_source_ref: str = "outputs/planned_eta.json#mission_day_estimates",
) -> dict[str, Any]:
    """Allocate route-bin candidate energy to the adopted mission days.

    Allocation uses only interval overlap between route-bin distance and the
    explicit mission-day route boundaries.  Uncovered route gaps remain gaps;
    they are reported in coverage and are never interpolated as rest or energy.
    Aggregate mean/min/max are emitted only when every mission day has an
    energy row.  This prevents a missing day from silently becoming a complete
    nine-day average.
    """

    days = (eta or {}).get("mission_day_estimates") if isinstance(eta, Mapping) else None
    if not isinstance(days, Sequence) or isinstance(days, (str, bytes, bytearray)):
        return {
            "status": "unavailable",
            "reason": "mission_day_estimates_unavailable",
            "daily_values": [],
            "day_count": 0,
            "available_day_count": 0,
            "mean_daily_energy_kcal": None,
            "minimum_daily_energy_kcal": None,
            "maximum_daily_energy_kcal": None,
            "total_energy_kj": None,
            "source_ref": source_ref,
            "eta_source_ref": eta_source_ref,
            "candidate_only": True,
            "runtime_safety_truth": False,
        }

    bins, skipped_bin_count, downhill_bin_count = _architecture_route_energy_bins(
        vectors,
        body_mass_kg=body_mass_kg,
        load_kg=load_kg,
        terrain_factor=terrain_factor,
        psychological_stress_multiplier=psychological_stress_multiplier,
        speed_key=speed_key,
    )
    daily_values: list[dict[str, Any]] = []
    for index, raw_day in enumerate(days):
        day = raw_day if isinstance(raw_day, Mapping) else {}
        mission_day_id = str(
            day.get("mission_day_id") or day.get("day_id") or f"D{index + 1}"
        )
        start, end, boundary_source = _mission_day_bounds(day)
        elapsed_minutes = _finite(
            (day.get("eta") or {}).get("observed_elapsed_minutes")
            if isinstance(day.get("eta"), Mapping)
            else None
        )
        if start is None or end is None or end <= start:
            daily_values.append(
                {
                    "mission_day_id": mission_day_id,
                    "status": "unavailable",
                    "reason": "mission_day_route_boundaries_unavailable",
                    "energy_kj": None,
                    "energy_kcal": None,
                    "route_start_distance_m": _round(start, 3),
                    "route_end_distance_m": _round(end, 3),
                    "route_span_m": None,
                    "covered_distance_m": 0.0,
                    "coverage_ratio": None,
                    "reference_elapsed_minutes": _round(elapsed_minutes, 3),
                    "usable_bin_count": 0,
                    "source_ref": f"{eta_source_ref}[{mission_day_id}]",
                    "boundary_source": boundary_source,
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                }
            )
            continue

        span = end - start
        energy_j = 0.0
        covered_distance_m = 0.0
        usable_bin_count = 0
        for item in bins:
            overlap_start = max(start, float(item["start_distance_m"]))
            overlap_end = min(end, float(item["end_distance_m"]))
            overlap = overlap_end - overlap_start
            if overlap <= 0:
                continue
            fraction = overlap / float(item["distance_m"])
            energy_j += float(item["energy_j"]) * fraction
            covered_distance_m += overlap
            usable_bin_count += 1
        coverage_ratio = covered_distance_m / span if span > 0 else None
        row_status = "unavailable" if usable_bin_count == 0 else (
            "available" if coverage_ratio is not None and coverage_ratio >= 0.999 else "partial"
        )
        daily_values.append(
            {
                "mission_day_id": mission_day_id,
                "status": row_status,
                "reason": (
                    "no_route_bins_overlap_day"
                    if not usable_bin_count
                    else "uncovered_route_gap"
                    if row_status == "partial"
                    else None
                ),
                "energy_kj": _round(energy_j / 1000.0, 3),
                "energy_kcal": _round(energy_j / 4184.0, 3),
                "route_start_distance_m": _round(start, 3),
                "route_end_distance_m": _round(end, 3),
                "route_span_m": _round(span, 3),
                "covered_distance_m": _round(covered_distance_m, 3),
                "coverage_ratio": _round(coverage_ratio, 6),
                "reference_elapsed_minutes": _round(elapsed_minutes, 3),
                "usable_bin_count": usable_bin_count,
                "source_ref": f"{eta_source_ref}[{mission_day_id}]",
                "boundary_source": boundary_source,
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )

    energy_rows = [
        row for row in daily_values if _finite(row.get("energy_kcal")) is not None
    ]
    all_days_available = len(energy_rows) == len(daily_values) and bool(daily_values)
    statuses = {str(row.get("status")) for row in daily_values}
    if not energy_rows:
        aggregate_status = "unavailable"
    elif not all_days_available:
        aggregate_status = "partial"
    elif statuses == {"available"}:
        aggregate_status = "available"
    else:
        aggregate_status = "partial"
    values = [float(row["energy_kcal"]) for row in energy_rows]
    aggregate_reason = (
        "no_usable_mission_day_energy"
        if not energy_rows
        else "one_or_more_mission_days_missing_energy"
        if not all_days_available
        else "route_bin_coverage_incomplete"
        if aggregate_status == "partial"
        else None
    )
    requested_span = sum(
        float(row["route_span_m"])
        for row in daily_values
        if _finite(row.get("route_span_m")) is not None
    )
    covered_distance = sum(float(row.get("covered_distance_m") or 0.0) for row in daily_values)
    return {
        "status": aggregate_status,
        "reason": aggregate_reason,
        "day_count": len(daily_values),
        "available_day_count": len(energy_rows),
        "daily_values": daily_values,
        "mean_daily_energy_kcal": _round(sum(values) / len(values), 3) if all_days_available else None,
        "minimum_daily_energy_kcal": _round(min(values), 3) if all_days_available else None,
        "maximum_daily_energy_kcal": _round(max(values), 3) if all_days_available else None,
        "minimum_day_id": min(energy_rows, key=lambda row: float(row["energy_kcal"])).get(
            "mission_day_id"
        ) if all_days_available else None,
        "maximum_day_id": max(energy_rows, key=lambda row: float(row["energy_kcal"])).get(
            "mission_day_id"
        ) if all_days_available else None,
        "total_energy_kj": _round(sum(values) * 4.184, 3),
        "coverage": {
            "requested_route_span_m": _round(requested_span, 3),
            "covered_distance_m": _round(covered_distance, 3),
            "coverage_ratio": _round(
                covered_distance / requested_span if requested_span > 0 else None,
                6,
            ),
            "skipped_bin_count": skipped_bin_count,
            "downhill_bin_count": downhill_bin_count,
            "uncovered_route_gaps_excluded": True,
        },
        "mean_basis": (
            "arithmetic mean of mission-day route-bin energy rows; each row uses "
            "covered reference schedule bins only; no gap interpolation or duration extrapolation"
        ),
        "energy_basis": (
            "sum of Architecture candidate metabolic power x fixed reference/golden "
            "GPX schedule seconds; not HealthExport active energy, basal energy, or mechanical power"
        ),
        "day_boundary_basis": "adopted planned_eta mission_day_estimates reference_replay route boundaries",
        "calendar_date_range": {
            "status": "unavailable",
            "reason": "mission-day plan provides D labels rather than calendar dates",
        },
        "source_ref": source_ref,
        "eta_source_ref": eta_source_ref,
        "speed_basis": f"Architecture reference/golden GPX schedule speed {speed_key}",
        "downhill_model": "cosine_horizontal_component_floor",
        "downhill_model_basis": "user_requested_candidate_assumption",
        "condition_inputs": {
            "body_mass_kg": body_mass_kg,
            "body_mass_basis": "user_assumption",
            "load_kg": load_kg,
            "terrain_factor": terrain_factor,
            "psychological_stress_multiplier": psychological_stress_multiplier,
        },
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def default_pace_correction_calibration(
    project_id: str,
    *,
    schedule_source_ref: str | None = None,
    source_state: str = "not_present",
) -> dict[str, Any]:
    """Return the neutral, uncalibrated correction state."""

    refs = [DEFAULT_PACE_CORRECTION_CALIBRATION_REF]
    if schedule_source_ref:
        refs.append(schedule_source_ref)
    return {
        "artifact_kind": "scout_pace_correction_calibration",
        "schema_version": PACE_CORRECTION_CALIBRATION_SCHEMA_VERSION,
        "project_id": _safe_project_id(project_id),
        "route_scope_key": _safe_project_id(project_id),
        "status": "prior_uninformed",
        "source_state": source_state,
        "correction_ratio": 1.0,
        "correction_ratio_definition": (
            "Architecture route total metabolic power estimate / Body Index personal flat "
            "total metabolic power estimate"
        ),
        "power_domain": PANDOLF_POWER_DOMAIN,
        "calibrated_success_count": 0,
        "observations": [],
        "prior": {
            "ratio": 1.0,
            "weight": DEFAULT_PRIOR_WEIGHT,
            "basis": "no successful climb records; neutral prior only",
        },
        "update_policy": {
            "method": "neutral_prior_plus_equal_weight_successful_climbs",
            "formula": "new=(old*(prior_weight+accepted_count)+observed_ratio)/(prior_weight+accepted_count+1)",
            "observed_ratio": "route_total_power_w / body_flat_total_power_w",
            "failure_or_partial_climb_updates_ratio": False,
            "duplicate_climb_updates_ratio": False,
        },
        "last_update": {
            "status": "not_calibrated",
            "reason": "no successful climb receipt",
        },
        "source_refs": refs,
        "privacy": {
            "raw_health_payload_embedded": False,
            "raw_gpx_embedded": False,
            "precise_timestamps_embedded": False,
            "precise_location_embedded": False,
        },
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "phase1_runtime_mutation_allowed": False,
            "automatic_safety_decision_allowed": False,
        },
        "notes": [
            "Ratio 1 is an explicit uncalibrated prior, not evidence that the user can hold the route schedule.",
            "Reference/golden GPX schedule remains fixed; correction changes the candidate personal elapsed-time estimate only.",
        ],
    }


def load_pace_correction_calibration(
    project_root: Path | str,
    *,
    project_id: str,
) -> dict[str, Any]:
    """Load a route-scoped calibration artifact, or expose the neutral prior."""

    root = Path(project_root)
    project_path = root / "project.json"
    project: dict[str, Any] = {}
    if project_path.is_file():
        try:
            loaded = json.loads(project_path.read_text(encoding="utf-8"))
            if isinstance(loaded, Mapping):
                project = dict(loaded)
        except (OSError, json.JSONDecodeError):
            project = {}
    ref = str(
        project.get("pace_correction_calibration_ref")
        or DEFAULT_PACE_CORRECTION_CALIBRATION_REF
    )
    path = root / ref
    if not path.is_file():
        return default_pace_correction_calibration(project_id, source_state="not_present")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        result = default_pace_correction_calibration(project_id, source_state="invalid_json")
        result.update(
            {
                "status": "unavailable",
                "last_update": {
                    "status": "unavailable",
                    "reason": "calibration_artifact_invalid_json",
                },
            }
        )
        return result
    if not isinstance(payload, Mapping):
        result = default_pace_correction_calibration(project_id, source_state="invalid_shape")
        result.update(
            {
                "status": "unavailable",
                "last_update": {
                    "status": "unavailable",
                    "reason": "calibration_artifact_invalid_shape",
                },
            }
        )
        return result
    result = _normalize_calibration(dict(payload), project_id=project_id, source_ref=ref)
    expected_scope = _safe_project_id(project_id)
    if result.get("route_scope_key") not in {None, expected_scope}:
        result["status"] = "unavailable"
        result["last_update"] = {
            "status": "unavailable",
            "reason": "calibration_route_scope_mismatch",
        }
    return result


def apply_successful_climb_calibration(
    prior: Mapping[str, Any] | None,
    observation: Mapping[str, Any],
    *,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Apply exactly one sanitized successful-climb observation.

    A receipt is accepted only when it declares successful completion, the two
    powers are positive and in the same domain, and the climb id is new.  A
    rejected receipt returns the unchanged ratio with an explicit reason.
    """

    base = dict(prior or default_pace_correction_calibration(project_id or "unknown_project"))
    base = _normalize_calibration(base, project_id=project_id or base.get("project_id"))
    if base.get("status") == "unavailable":
        return _rejected_update(base, "calibration_prior_unavailable")
    climb_id = str(observation.get("climb_id") or observation.get("receipt_id") or "").strip()
    completion_status = str(
        observation.get("completion_status")
        or observation.get("status")
        or ""
    ).strip().lower()
    success = observation.get("success") is True or completion_status in {
        "success",
        "successful",
        "complete",
        "completed",
    }
    if not success:
        return _rejected_update(base, "climb_not_marked_successful")
    if not climb_id:
        return _rejected_update(base, "climb_id_required")

    observations = [
        item for item in base.get("observations", []) if isinstance(item, Mapping)
    ]
    if any(str(item.get("climb_id")) == climb_id for item in observations):
        return _rejected_update(base, "duplicate_climb_receipt", climb_id=climb_id)

    domain = str(observation.get("power_domain") or base.get("power_domain") or "")
    if domain != PANDOLF_POWER_DOMAIN or str(base.get("power_domain")) != domain:
        return _rejected_update(base, "power_domain_mismatch", climb_id=climb_id)
    route_power = _positive(observation.get("route_total_power_w"))
    body_power = _positive(observation.get("body_flat_total_power_w"))
    if route_power is None or body_power is None:
        return _rejected_update(base, "route_or_body_power_unavailable", climb_id=climb_id)
    scope = str(observation.get("route_scope_key") or base.get("route_scope_key") or "")
    if project_id and scope and scope != _safe_project_id(project_id):
        return _rejected_update(base, "route_scope_mismatch", climb_id=climb_id)

    old_ratio = _positive(base.get("correction_ratio")) or 1.0
    prior_weight = _positive((base.get("prior") or {}).get("weight")) or DEFAULT_PRIOR_WEIGHT
    accepted_count = len(observations)
    effective_weight = prior_weight + accepted_count
    observed_ratio = route_power / body_power
    learning_rate = 1.0 / (effective_weight + 1.0)
    new_ratio = old_ratio + (observed_ratio - old_ratio) * learning_rate
    observation_record = {
        "climb_id": climb_id,
        "completion_status": completion_status or "successful",
        "success": True,
        "route_scope_key": scope or base.get("route_scope_key"),
        "power_domain": domain,
        "route_total_power_w": _round(route_power, 3),
        "body_flat_total_power_w": _round(body_power, 3),
        "observed_ratio": _round(observed_ratio, 6),
        "source_refs": _safe_ref_list(observation.get("source_refs")),
        "schedule_adherence": str(observation.get("schedule_adherence") or "unreported"),
        "accepted_at": str(observation.get("observed_at") or _utc_now()),
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    observations.append(observation_record)
    result = dict(base)
    result.update(
        {
            "status": "calibrated",
            "source_state": "calibrated_success_receipts",
            "correction_ratio": _round(new_ratio, 6),
            "calibrated_success_count": len(observations),
            "observations": observations,
            "route_scope_key": scope or base.get("route_scope_key"),
            "last_update": {
                "status": "accepted",
                "climb_id": climb_id,
                "observed_ratio": _round(observed_ratio, 6),
                "learning_rate": _round(learning_rate, 6),
                "previous_ratio": _round(old_ratio, 6),
                "new_ratio": _round(new_ratio, 6),
            },
            "updated_at": _utc_now(),
        }
    )
    result["source_refs"] = list(
        dict.fromkeys(
            [*(_safe_ref_list(base.get("source_refs"))), *observation_record["source_refs"]]
        )
    )
    return result


def write_pace_correction_calibration(
    project_root: Path | str,
    calibration: Mapping[str, Any],
    *,
    output_ref: str | None = None,
) -> Path:
    """Explicitly write a candidate calibration artifact for later dashboard reads."""

    root = Path(project_root)
    project_path = root / "project.json"
    project: dict[str, Any] = {}
    if project_path.is_file():
        try:
            loaded = json.loads(project_path.read_text(encoding="utf-8"))
            if isinstance(loaded, Mapping):
                project = dict(loaded)
        except (OSError, json.JSONDecodeError):
            project = {}
    ref = output_ref or str(
        project.get("pace_correction_calibration_ref")
        or DEFAULT_PACE_CORRECTION_CALIBRATION_REF
    )
    path = root / ref
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = _normalize_calibration(
        dict(calibration),
        project_id=str(calibration.get("project_id") or project.get("project_id") or root.name),
        source_ref=ref,
    )
    path.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _normalize_calibration(
    payload: dict[str, Any],
    *,
    project_id: Any,
    source_ref: str | None = None,
) -> dict[str, Any]:
    result = dict(payload)
    result.setdefault("artifact_kind", "scout_pace_correction_calibration")
    result.setdefault("schema_version", PACE_CORRECTION_CALIBRATION_SCHEMA_VERSION)
    result.setdefault("project_id", _safe_project_id(project_id))
    result.setdefault("route_scope_key", _safe_project_id(project_id))
    result.setdefault("power_domain", PANDOLF_POWER_DOMAIN)
    result.setdefault("correction_ratio", 1.0)
    ratio = _positive(result.get("correction_ratio"))
    result["correction_ratio"] = _round(ratio or 1.0, 6)
    observations = result.get("observations")
    result["observations"] = [
        dict(item) for item in observations if isinstance(item, Mapping)
    ] if isinstance(observations, list) else []
    result["calibrated_success_count"] = len(result["observations"])
    result.setdefault("status", "calibrated" if result["observations"] else "prior_uninformed")
    result.setdefault("source_state", "loaded_artifact")
    source_refs = _safe_ref_list(result.get("source_refs"))
    if source_ref and source_ref not in source_refs:
        source_refs.append(source_ref)
    result["source_refs"] = source_refs
    result["candidate_only"] = True
    result["runtime_safety_truth"] = False
    result.setdefault(
        "boundary",
        {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "phase1_runtime_mutation_allowed": False,
            "automatic_safety_decision_allowed": False,
        },
    )
    return result


def _rejected_update(
    base: dict[str, Any],
    reason: str,
    *,
    climb_id: str | None = None,
) -> dict[str, Any]:
    result = dict(base)
    result["last_update"] = {
        "status": "rejected",
        "reason": reason,
        **({"climb_id": climb_id} if climb_id else {}),
    }
    result["candidate_only"] = True
    result["runtime_safety_truth"] = False
    return result


def calibration_digest(calibration: Mapping[str, Any]) -> str:
    """Stable digest for a sanitized calibration artifact."""

    payload = json.dumps(dict(calibration), ensure_ascii=False, sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "DEFAULT_PACE_CORRECTION_CALIBRATION_REF",
    "PANDOLF_POWER_DOMAIN",
    "apply_successful_climb_calibration",
    "architecture_route_bin_power_estimate_w",
    "architecture_route_daily_energy_summary",
    "architecture_route_power_summary",
    "build_body_flat_power_reference",
    "calibration_digest",
    "default_pace_correction_calibration",
    "load_pace_correction_calibration",
    "pandolf_metabolic_power_w",
    "write_pace_correction_calibration",
]
