"""Pure historical departure-to-cutoff accounting, not live daylight or safety."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from typing import Any

from pretrip_historical_return_cost import _Bin, _integrate, _prepare_bins


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def _nonnegative(value: Any) -> float | None:
    number = _finite(value)
    return number if number is not None and number >= 0 else None


def _position(value: Any, route_distance: float | None) -> float | None:
    distance = _nonnegative(value)
    if route_distance is None or distance is None or distance > route_distance:
        return None
    return distance


def _minute(value: Any, *, allow_day_end: bool = False) -> float | None:
    minute = _nonnegative(value)
    if minute is not None and (minute < 1440 or (allow_day_end and minute == 1440)):
        return minute
    return None


def _combined_status(*statuses: str) -> str:
    if any(status not in ("observed", "estimated") for status in statuses):
        return "unavailable"
    return "estimated" if "estimated" in statuses else "observed"


def _normalize_days(
    days: Sequence[Mapping[str, Any]],
    route_distance: float | None,
    cutoff: float | None,
) -> tuple[list[dict], list[str]]:
    normalized = []
    errors = []
    seen_ids = set()
    for ordinal, item in enumerate(days):
        day_id = item.get("day_id")
        if not isinstance(day_id, str) or not day_id.strip():
            day_id = None
            errors.append(f"day[{ordinal}]:invalid_day_id")
        elif day_id in seen_ids:
            errors.append(f"day[{ordinal}]:duplicate_day_id")
        seen_ids.add(day_id)
        index = _nonnegative(item.get("day_index"))
        index = int(index) if index is not None and index.is_integer() else None
        if index is None:
            errors.append(f"day[{ordinal}]:invalid_day_index")
        start = _position(item.get("start_distance_m"), route_distance)
        end = _position(item.get("end_distance_m"), route_distance)
        if start is None or end is None or end <= start:
            errors.append(f"day[{ordinal}]:invalid_bounds")
        if normalized:
            previous = normalized[-1]
            if (
                index is not None
                and previous["day_index"] is not None
                and index <= previous["day_index"]
            ):
                errors.append(f"day[{ordinal}]:unordered_day_index")
            if (
                start is not None
                and previous["end_distance_m"] is not None
                and start < previous["end_distance_m"]
            ):
                errors.append(f"day[{ordinal}]:overlapping_or_unordered_bounds")
        departure = _minute(item.get("departure_minute_of_day"))
        status = item.get("departure_status")
        if departure is None or status not in ("observed", "estimated"):
            departure, status = None, "unavailable"
        normalized.append(
            {
                "day_id": day_id,
                "day_index": index,
                "start_distance_m": start,
                "end_distance_m": end,
                "departure_minute_of_day": departure,
                "departure_status": status,
            }
        )
    return [
        {
            **day,
            "initial_window_minutes": cutoff - day["departure_minute_of_day"]
            if not errors
            and cutoff is not None
            and day["departure_minute_of_day"] is not None
            else None,
        }
        for day in normalized
    ], errors


def _normalize_nodes(
    nodes: Sequence[Mapping[str, Any]], route_distance: float | None, kind: str
) -> list[dict]:
    return [
        {
            "node_id": item.get("node_id"),
            "label": item.get("label"),
            "route_distance_m": _position(item.get("route_distance_m"), route_distance),
            "node_kind": kind,
        }
        for item in nodes
    ]


def _checkpoint_nodes(
    checkpoints: list[dict], days: list[dict]
) -> tuple[list[dict], int]:
    nodes = list(checkpoints)
    occupied = {cp["route_distance_m"] for cp in checkpoints}
    used_ids = {cp["node_id"] for cp in checkpoints if isinstance(cp["node_id"], str)}
    inserted = 0
    for day in days:
        distance = day["start_distance_m"]
        if distance in occupied:
            continue
        base_id = f"day_start.{day['day_id']}"
        node_id = base_id
        suffix = 1
        while node_id in used_ids:
            node_id = f"{base_id}.{suffix}"
            suffix += 1
        nodes.append(
            {
                "node_id": node_id,
                "label": f"Day {day['day_index']} departure",
                "route_distance_m": distance,
                "node_kind": "day_start",
            }
        )
        occupied.add(distance)
        used_ids.add(node_id)
        inserted += 1
    return sorted(
        nodes,
        key=lambda node: (
            node["route_distance_m"] is None,
            node["route_distance_m"] or 0,
        ),
    ), inserted


def _active_day(days: list[dict], distance: float | None) -> dict | None:
    if distance is None:
        return None
    # A departure owns a touching boundary; otherwise retain the prior day end.
    for day in reversed(days):
        start, end = day["start_distance_m"], day["end_distance_m"]
        if start <= distance <= end:
            return day
    return None


def _window_row(node: dict, day: dict | None, bins: tuple[_Bin, ...] | None) -> dict:
    source = day or {}
    window = source.get("initial_window_minutes")
    distance = node["route_distance_m"]
    consumed, consumed_status = _integrate(
        bins, source.get("start_distance_m"), distance, reverse=False
    )
    remaining = (
        _finite(window - consumed)
        if window is not None and consumed is not None
        else None
    )
    status = (
        _combined_status(source["departure_status"], consumed_status)
        if remaining is not None
        else "unavailable"
    )
    ratio = (
        _finite(remaining / window) if remaining is not None and window > 0 else None
    )
    return {
        **node,
        "day_id": source.get("day_id"),
        "day_index": source.get("day_index"),
        "departure_minute_of_day": source.get("departure_minute_of_day"),
        "departure_status": source.get("departure_status", "unavailable"),
        "initial_window_minutes": window,
        "consumed_minutes": consumed,
        "consumed_status": consumed_status,
        "remaining_minutes": remaining,
        "remaining_ratio": ratio,
        "remaining_status": status,
        "deadline_exceeded": remaining < 0 if remaining is not None else None,
        "day_reset": window is not None and distance == source.get("start_distance_m"),
    }


def _safe_point_row(
    row: dict,
    safe_points: list[dict],
    finish: dict | None,
    bins: tuple[_Bin, ...] | None,
) -> dict:
    distance = row["route_distance_m"]
    target = None
    if distance is not None:
        target = next(
            (point for point in safe_points if point["route_distance_m"] > distance),
            None,
        )
        if (
            target is None
            and finish is not None
            and finish["route_distance_m"] > distance
        ):
            target = finish
    cost, cost_status = _integrate(
        bins, distance, target["route_distance_m"] if target else None, reverse=False
    )
    remaining = row["remaining_minutes"]
    margin = (
        _finite(remaining - cost)
        if remaining is not None and cost is not None
        else None
    )
    return {
        **row,
        "next_safe_point_id": target["node_id"] if target else None,
        "next_safe_point_label": target["label"] if target else None,
        "next_safe_point_distance_m": target["route_distance_m"] if target else None,
        "next_safe_point_kind": target["node_kind"] if target else None,
        "forward_to_safe_minutes": cost,
        "forward_to_safe_status": cost_status,
        "arrival_margin_minutes": margin,
        "arrival_margin_status": _combined_status(row["remaining_status"], cost_status)
        if margin is not None
        else "unavailable",
        "can_reach_safe_before_cutoff": margin >= 0 if margin is not None else None,
    }


def build_historical_time_windows(
    *,
    bins: Sequence[Mapping[str, Any]],
    checkpoints: Sequence[Mapping[str, Any]],
    days: Sequence[Mapping[str, Any]],
    safe_points: Sequence[Mapping[str, Any]],
    route_distance_m: float | None,
    cutoff_minute_of_day: float = 1080,
) -> dict:
    """Debit forward-only minutes from each explicit departure-to-cutoff window.

    Days must have unique nonempty string IDs, increasing nonnegative integer
    indices and ordered, nonoverlapping positive-length bounds within the route.
    Invalid schedules make all budgets unavailable; missing departure clocks
    affect only their own days. Each day includes its exact start and end, except
    a touching endpoint belongs to the departing day. Even tiny gaps are unknown.

    Insert a day_start at every departure without a coincident CP. All coincident
    CPs share the new day's values. day_reset marks a known window at its exact
    departure, including the first day, never merely passing a historical camp.
    Departures are local minutes in [0, 1440); cutoff may also equal 1440. Negative
    windows and balances are preserved, without wrapping to another calendar day.
    remaining_ratio is A / T only for positive T, otherwise unavailable.

    Safe targets are nearest explicit points strictly ahead, with stable input
    order for ties. An original CP at route_distance_m is the only finish fallback;
    the numeric route length alone never supplies one. Arrival margin uses only
    the current balance, never a later day's allocation. These are historical
    candidate markers, not a determination of actual shelter, safety or sunset.
    """
    route_distance = _nonnegative(route_distance_m)
    cutoff = _minute(cutoff_minute_of_day, allow_day_end=True)
    prepared = _prepare_bins(bins)
    normalized_days, errors = _normalize_days(days, route_distance, cutoff)
    schedule_valid = bool(normalized_days) and not errors
    active_days = normalized_days if schedule_valid else []
    original_nodes = _normalize_nodes(checkpoints, route_distance, "checkpoint")
    nodes, inserted = _checkpoint_nodes(original_nodes, active_days)
    candidates = _normalize_nodes(safe_points, route_distance, "historical_candidate")
    valid_safe_points = sorted(
        (point for point in candidates if point["route_distance_m"] is not None),
        key=lambda point: point["route_distance_m"],
    )
    finish = next(
        (
            {**node, "node_kind": "route_finish_candidate"}
            for node in original_nodes
            if route_distance is not None and node["route_distance_m"] == route_distance
        ),
        None,
    )
    rows = [
        _safe_point_row(
            _window_row(
                node, _active_day(active_days, node["route_distance_m"]), prepared
            ),
            valid_safe_points,
            finish,
            prepared,
        )
        for node in nodes
    ]
    available = sum(row["remaining_minutes"] is not None for row in rows)
    target_count = sum(row["next_safe_point_distance_m"] is not None for row in rows)
    available_margins = sum(row["arrival_margin_minutes"] is not None for row in rows)
    status = "unavailable"
    if available:
        status = (
            "ready"
            if available == len(rows) and available_margins == target_count
            else "partial"
        )
    return {
        "schema_version": "historical_time_windows.v1",
        "route_distance_m": route_distance,
        "cutoff_minute_of_day": cutoff,
        "days": normalized_days,
        "checkpoints": rows,
        "safe_points": valid_safe_points,
        "status": status,
        "stats": {
            "bin_count": len(bins),
            "bin_geometry_valid": prepared is not None,
            "day_count": len(normalized_days),
            "schedule_valid": schedule_valid,
            "schedule_errors": errors,
            "available_departure_count": sum(
                day["departure_minute_of_day"] is not None for day in normalized_days
            ),
            "available_day_window_count": sum(
                day["initial_window_minutes"] is not None for day in normalized_days
            ),
            "input_checkpoint_count": len(checkpoints),
            "checkpoint_count": len(rows),
            "inserted_day_start_count": inserted,
            "invalid_checkpoint_count": sum(
                node["route_distance_m"] is None for node in original_nodes
            ),
            "safe_point_count": len(valid_safe_points),
            "invalid_safe_point_count": len(safe_points) - len(valid_safe_points),
            "available_remaining_count": available,
            "unavailable_remaining_count": len(rows) - available,
            "estimated_remaining_count": sum(
                row["remaining_status"] == "estimated" for row in rows
            ),
            "deadline_exceeded_count": sum(
                row["deadline_exceeded"] is True for row in rows
            ),
            "day_reset_count": len({row["day_id"] for row in rows if row["day_reset"]}),
            "next_safe_point_count": target_count,
            "available_forward_to_safe_count": sum(
                row["forward_to_safe_minutes"] is not None for row in rows
            ),
            "available_arrival_margin_count": available_margins,
        },
        "policy": {
            "initial_window": "cutoff_minus_explicit_departure_no_calendar_wrap",
            "remaining_minutes": "initial_window_minus_forward_cost_from_active_day_start",
            "remaining_ratio": "remaining_divided_by_positive_initial_window_else_null",
            "cost_basis": "forward_direction_only_proportional_bin_overlap",
            "partial_coverage": "unavailable_no_partial_sum",
            "day_bounds": "closed_bounds_touching_endpoint_owned_by_later_day",
            "invalid_schedule": "all_day_budgets_unavailable_no_sorting_or_inference",
            "day_reset": "known_window_at_explicit_departure_only_first_day_included",
            "camp_or_midnight_reset": False,
            "next_safe_point": "nearest_explicit_strictly_ahead_first_input_at_equal_distance",
            "finish_fallback": "explicit_original_checkpoint_at_route_end_only",
            "arrival_margin": "current_remaining_minus_forward_cost_to_target_no_future_day_credit",
            "negative_values": "preserved",
            "exact_cutoff_arrival": "within_window",
        },
        "candidate_only": True,
        "runtime_safety_truth": False,
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "live_remaining_day_budget": False,
            "actual_sunset_calculated": False,
            "safety_or_passability_determined": False,
            "safe_points_are_historical_candidates": True,
        },
    }
