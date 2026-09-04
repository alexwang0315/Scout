"""Pure historical GPX moving-time analysis; never a live return deadline."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
from typing import Any


Timing = tuple[float | None, str]
_UNAVAILABLE: Timing = (None, "unavailable")


@dataclass(frozen=True)
class _Bin:
    start: float
    end: float
    forward: Timing
    reverse: Timing


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _timing(value: Any) -> Timing:
    if not isinstance(value, Mapping):
        return _UNAVAILABLE
    minutes = _number(value.get("average_minutes"))
    status = value.get("status")
    if minutes is None or status not in ("observed", "estimated"):
        return _UNAVAILABLE
    return minutes, status


def _prepare_bins(bins: Sequence[Mapping[str, Any]]) -> tuple[_Bin, ...] | None:
    normalized = []
    previous_end = 0.0
    for item in bins:
        start = _number(item.get("start_distance_m"))
        end = _number(item.get("end_distance_m"))
        if start is None or end is None or end < start:
            return None
        if end == start:
            continue
        if start < previous_end:
            return None
        normalized.append(
            _Bin(start, end, _timing(item.get("forward")), _timing(item.get("reverse")))
        )
        previous_end = end
    return tuple(normalized)


def _integrate(
    bins: tuple[_Bin, ...] | None,
    start: float | None,
    end: float | None,
    *,
    reverse: bool,
) -> Timing:
    if start is None or end is None or end < start:
        return _UNAVAILABLE
    if start == end:
        return 0.0, "observed"
    if bins is None:
        return _UNAVAILABLE

    cursor = start
    parts = []
    status = "observed"
    for interval in bins:
        if interval.end <= cursor:
            continue
        if interval.start > cursor:
            return _UNAVAILABLE
        minutes, interval_status = interval.reverse if reverse else interval.forward
        if minutes is None:
            return _UNAVAILABLE
        overlap_end = min(end, interval.end)
        parts.append(
            ((overlap_end - cursor) / (interval.end - interval.start)) * minutes
        )
        if interval_status == "estimated":
            status = "estimated"
        cursor = overlap_end
        if cursor == end:
            try:
                total = _number(math.fsum(parts))
            except OverflowError:
                return _UNAVAILABLE
            return (total, status) if total is not None else _UNAVAILABLE
    return _UNAVAILABLE


def _node(item: Mapping[str, Any], route_distance: float | None, kind: str) -> dict:
    distance = _number(item.get("route_distance_m"))
    if route_distance is None or (distance is not None and distance > route_distance):
        distance = None
    return {
        "node_id": item.get("node_id"),
        "label": item.get("label"),
        "route_distance_m": distance,
        "node_kind": kind,
    }


def _target_key(target: Mapping[str, Any]) -> tuple:
    return target["node_id"], target["route_distance_m"], target["node_kind"]


def build_historical_return_cost(
    *,
    bins: Sequence[Mapping[str, Any]],
    checkpoints: Sequence[Mapping[str, Any]],
    camps: Sequence[Mapping[str, Any]],
    daily_budget_minutes: float | None,
    route_distance_m: float | None,
) -> dict:
    """Integrate independent forward and reverse average times over route intervals.

    The budget is full historical-day moving capacity, without subtracting the
    outbound cost. Unknown entry costs retain the previous target, initially the
    trailhead, without inferring a new switch. An absent budget keeps trailhead.

    Output checkpoints preserve every input CP, sorted by distance. One extra
    node_kind='camp' is inserted per valid camp-only distance. Coincident CPs are
    retained; coincident camps add no nodes. Next-CP targets always use the next
    original checkpoint, so inserted camps never split CP-to-CP durations.
    entry_day_exceeded compares the entry cost with the budget; the first known
    exceeded row has entry_decision_boundary=True, independently of target changes.
    Invalid CP distances become null and sort last; invalid camps are excluded.
    The first explicit camp wins ties in distance. Invalid or overlapping bin
    geometry makes nonzero integrations unavailable. Zero-length bins are ignored.
    """
    route_distance = _number(route_distance_m)
    budget = _number(daily_budget_minutes)
    prepared_bins = _prepare_bins(bins)
    nodes = [_node(cp, route_distance, "checkpoint") for cp in checkpoints]
    normalized_camps = [_node(camp, route_distance, "camp") for camp in camps]
    valid_camps = sorted(
        (camp for camp in normalized_camps if camp["route_distance_m"] is not None),
        key=lambda camp: camp["route_distance_m"],
    )
    occupied = {cp["route_distance_m"] for cp in nodes}
    inserted_count = 0
    for camp in valid_camps:
        if camp["route_distance_m"] not in occupied:
            nodes.append(dict(camp))
            occupied.add(camp["route_distance_m"])
            inserted_count += 1
    nodes.sort(
        key=lambda cp: (cp["route_distance_m"] is None, cp["route_distance_m"] or 0)
    )
    next_originals: list[dict | None] = [None] * len(nodes)
    upcoming_original = None
    for index in reversed(range(len(nodes))):
        next_originals[index] = upcoming_original
        if nodes[index]["node_kind"] == "checkpoint":
            upcoming_original = nodes[index]

    entry_cp = next(
        (
            cp
            for cp in nodes
            if cp["route_distance_m"] == 0 and cp["node_kind"] == "checkpoint"
        ),
        None,
    )
    entry = {
        "node_id": entry_cp["node_id"] if entry_cp else "trailhead",
        "label": entry_cp["label"] if entry_cp else "Trailhead",
        "route_distance_m": 0.0,
        "node_kind": "trailhead",
    }
    target = entry
    previous_target_key = None
    entry_crossing_seen = False
    rows = []
    for index, cp in enumerate(nodes):
        distance = cp["route_distance_m"]
        entry_cost, entry_status = _integrate(
            prepared_bins, 0.0, distance, reverse=True
        )
        entry_day_exceeded = (
            entry_cost > budget
            if entry_cost is not None and budget is not None
            else None
        )
        entry_decision_boundary = entry_day_exceeded is True and not entry_crossing_seen
        entry_crossing_seen = entry_crossing_seen or entry_decision_boundary
        if budget is None:
            target = entry
        elif entry_cost is not None:
            target = entry
            if entry_cost > budget:
                preceding = [
                    camp for camp in valid_camps if camp["route_distance_m"] <= distance
                ]
                if preceding:
                    latest_distance = preceding[-1]["route_distance_m"]
                    target = next(
                        camp
                        for camp in preceding
                        if camp["route_distance_m"] == latest_distance
                    )

        return_cost, return_status = _integrate(
            prepared_bins,
            target["route_distance_m"],
            distance,
            reverse=True,
        )
        next_cp = next_originals[index]
        next_cost, next_status = _integrate(
            prepared_bins,
            distance,
            next_cp["route_distance_m"] if next_cp else None,
            reverse=False,
        )
        target_key = _target_key(target)
        ratio = (
            _number(return_cost / budget)
            if return_cost is not None and budget
            else None
        )
        rows.append(
            {
                **cp,
                "next_cp_id": next_cp["node_id"] if next_cp else None,
                "next_cp_label": next_cp["label"] if next_cp else None,
                "next_cp_distance_m": next_cp["route_distance_m"] if next_cp else None,
                "next_cp_average_minutes": next_cost,
                "next_cp_timing_status": next_status,
                "return_to_entry_minutes": entry_cost,
                "return_to_entry_status": entry_status,
                "entry_day_exceeded": entry_day_exceeded,
                "entry_decision_boundary": entry_decision_boundary,
                "return_target_id": target["node_id"],
                "return_target_label": target["label"],
                "return_target_distance_m": target["route_distance_m"],
                "return_target_kind": target["node_kind"],
                "return_cost_minutes": return_cost,
                "return_cost_status": return_status,
                "budget_ratio": ratio,
                "within_historical_day": (
                    return_cost <= budget
                    if return_cost is not None and budget is not None
                    else None
                ),
                "decision_boundary": previous_target_key is not None
                and target_key != previous_target_key,
            }
        )
        previous_target_key = target_key

    available_returns = sum(row["return_cost_minutes"] is not None for row in rows)
    available_next = sum(row["next_cp_average_minutes"] is not None for row in rows)
    expected_next = sum(cp is not None for cp in next_originals)
    status = "unavailable"
    if available_returns or available_next:
        status = "partial"
        if (
            available_returns == len(rows)
            and available_next == expected_next
            and budget is not None
            and route_distance is not None
        ):
            status = "ready"
    return {
        "schema_version": "historical_return_cost.v1",
        "route_distance_m": route_distance,
        "daily_budget_minutes": budget,
        "camps": valid_camps,
        "checkpoints": rows,
        "status": status,
        "stats": {
            "bin_count": len(bins),
            "bin_geometry_valid": prepared_bins is not None,
            "input_checkpoint_count": len(checkpoints),
            "checkpoint_count": len(rows),
            "inserted_camp_count": inserted_count,
            "camp_count": len(valid_camps),
            "invalid_camp_count": len(camps) - len(valid_camps),
            "invalid_checkpoint_count": sum(
                cp["route_distance_m"] is None for cp in nodes
            ),
            "available_return_count": available_returns,
            "unavailable_return_count": len(rows) - available_returns,
            "estimated_return_count": sum(
                row["return_cost_status"] == "estimated" for row in rows
            ),
            "available_next_cp_count": available_next,
            "next_cp_pair_count": expected_next,
            "decision_boundary_count": sum(row["decision_boundary"] for row in rows),
            "entry_decision_boundary_count": sum(
                row["entry_decision_boundary"] for row in rows
            ),
        },
        "policy": {
            "budget_basis": "historical_gpx_full_day_moving_minutes",
            "outbound_time_subtracted": False,
            "return_cost_basis": "reverse_direction_only_proportional_bin_overlap",
            "next_cp_cost_basis": "forward_direction_proportional_bin_overlap",
            "next_cp_target": "next_original_checkpoint_in_distance_order_skip_inserted_camps",
            "partial_coverage": "unavailable_no_partial_sum",
            "target_selection": "entry_cost_le_budget_else_latest_explicit_preceding_camp",
            "camp_selection": "explicit_only_at_or_before_cp_first_input_at_equal_distance",
            "unknown_entry_cost": "retain_previous_target_without_new_switch",
            "unknown_budget": "trailhead_cost_with_unknown_threshold",
            "budget_ratio": "target_return_cost_divided_by_positive_budget_else_null",
            "within_historical_day": "target_return_cost_le_full_historical_day_budget",
            "entry_day_exceeded": "entry_return_cost_gt_budget_else_unknown_if_cost_or_budget_missing",
            "entry_decision_boundary": "first_known_entry_day_exceeded_row_independent_of_target_changes",
            "decision_boundary": "target_change_between_ordered_output_nodes_first_node_false",
            "checkpoint_order": "distance_sorted_cps_plus_one_node_per_camp_only_distance",
        },
        "candidate_only": True,
        "runtime_safety_truth": False,
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "live_remaining_day_budget": False,
            "safety_or_passability_determined": False,
        },
    }
