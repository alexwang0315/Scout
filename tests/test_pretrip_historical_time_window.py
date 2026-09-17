from __future__ import annotations

from copy import deepcopy
import json
import math

import pytest

from pretrip_historical_time_window import build_historical_time_windows


def _node(node_id, distance):
    return {"node_id": node_id, "label": node_id.title(), "route_distance_m": distance}


def _bin(start, end, minutes, *, status="observed", reverse=900):
    return {
        "start_distance_m": start,
        "end_distance_m": end,
        "forward": {"average_minutes": minutes, "status": status},
        "reverse": {"average_minutes": reverse, "status": "observed"},
    }


def _day(index, start, end, departure=360, *, status="observed"):
    return {
        "day_id": f"d{index}",
        "day_index": index,
        "start_distance_m": start,
        "end_distance_m": end,
        "departure_minute_of_day": departure,
        "departure_status": status,
    }


def _build(
    *, bins=None, checkpoints=None, days=None, safe_points=(), distance=300, **kwargs
):
    return build_historical_time_windows(
        bins=[_bin(0, 300, 180)] if bins is None else bins,
        checkpoints=[_node("start", 0), _node("end", 300)]
        if checkpoints is None
        else checkpoints,
        days=[_day(1, 0, 300)] if days is None else days,
        safe_points=safe_points,
        route_distance_m=distance,
        **kwargs,
    )


def test_six_am_window_debits_forward_minutes_by_proportional_overlap():
    result = _build(
        bins=[_bin(0, 100, 40), _bin(100, 300, 100)],
        checkpoints=[_node("start", 0), _node("middle", 50), _node("later", 200)],
    )
    start, middle, later = result["checkpoints"]
    assert start["initial_window_minutes"] == 720
    assert [row["consumed_minutes"] for row in (start, middle, later)] == [0, 20, 90]
    assert [row["remaining_minutes"] for row in (start, middle, later)] == [
        720,
        700,
        630,
    ]
    assert later["remaining_ratio"] == pytest.approx(630 / 720)
    assert later["remaining_status"] == "observed"
    assert later["deadline_exceeded"] is False
    assert later["departure_minute_of_day"] == 360
    assert later["day_id"] == "d1"
    assert later["day_index"] == 1
    assert [row["day_reset"] for row in (start, middle, later)] == [True, False, False]
    assert result["status"] == "ready"
    assert result["schema_version"] == "historical_time_windows.v1"


def test_daily_reset_inserts_exact_departure_without_inserting_camps():
    result = _build(
        days=[_day(1, 0, 125), _day(2, 125, 300, 420)],
        checkpoints=[_node("start", 0), _node("before", 100), _node("after", 175)],
        safe_points=[_node("camp", 150)],
    )
    start, before, departure, after = result["checkpoints"]
    assert [row["route_distance_m"] for row in result["checkpoints"]] == [
        0,
        100,
        125,
        175,
    ]
    assert departure["node_kind"] == "day_start"
    assert departure["day_id"] == after["day_id"] == "d2"
    assert departure["day_reset"] is True
    assert departure["consumed_minutes"] == 0
    assert departure["remaining_minutes"] == 660
    assert after["consumed_minutes"] == 30
    assert after["remaining_minutes"] == 630
    assert before["remaining_minutes"] == 660
    assert before["day_reset"] is after["day_reset"] is False
    assert result["stats"]["inserted_day_start_count"] == 1
    assert result["stats"]["input_checkpoint_count"] == 3
    assert result["stats"]["checkpoint_count"] == 4
    assert result["stats"]["day_reset_count"] == 2


def test_shared_endpoint_belongs_to_new_day_without_duplicate_departure():
    result = _build(
        days=[_day(1, 0, 100), _day(2, 100, 300, 480)],
        checkpoints=[_node("old_end", 100), _node("new_start", 100), _node("end", 300)],
    )
    start, old_end, new_start, end = result["checkpoints"]
    assert start["node_kind"] == "day_start"
    for row in (old_end, new_start):
        assert row["node_kind"] == "checkpoint"
        assert row["day_id"] == "d2"
        assert row["remaining_minutes"] == 600
        assert row["day_reset"] is True
    assert end["day_id"] == "d2"
    assert end["consumed_minutes"] == 120
    assert end["remaining_minutes"] == 480
    assert result["stats"]["inserted_day_start_count"] == 1
    assert result["stats"]["day_reset_count"] == 2


def test_uncovered_schedule_does_not_extend_a_day_or_carry_budget_across_gap():
    result = _build(
        days=[_day(1, 25, 100), _day(2, 200, 275, 420)],
        checkpoints=[
            _node(str(distance), distance) for distance in (0, 100, 150, 225, 275, 300)
        ],
    )
    rows = {row["node_id"]: row for row in result["checkpoints"]}
    for node_id in ("0", "150", "300"):
        row = rows[node_id]
        assert row["day_id"] is row["initial_window_minutes"] is None
        assert row["consumed_minutes"] is row["remaining_minutes"] is None
        assert row["remaining_status"] == "unavailable"
        assert row["day_reset"] is False
    assert rows["100"]["day_id"] == "d1"
    assert rows["100"]["consumed_minutes"] == 45
    assert rows["100"]["remaining_minutes"] == 675
    assert rows["225"]["consumed_minutes"] == 15
    assert rows["225"]["remaining_minutes"] == 645
    assert rows["275"]["day_id"] == "d2"
    assert result["status"] == "partial"


def test_valid_day_after_missing_cost_resets_independently():
    result = _build(
        bins=[_bin(0, 100, None), _bin(100, 300, 60)],
        days=[_day(1, 0, 100), _day(2, 100, 300, 420)],
        checkpoints=[_node("lost", 50), _node("reset", 100), _node("later", 200)],
    )
    start, lost, reset, later = result["checkpoints"]
    assert lost["consumed_minutes"] is lost["remaining_minutes"] is None
    assert lost["deadline_exceeded"] is None
    assert reset["remaining_minutes"] == 660
    assert reset["day_reset"] is True
    assert later["remaining_minutes"] == 630
    assert later["remaining_status"] == "observed"


@pytest.mark.parametrize(
    "departure", [None, -1, 1440, math.nan, math.inf, True, "06:00"]
)
def test_missing_or_invalid_departure_keeps_cost_but_never_invents_window(departure):
    result = _build(
        days=[_day(1, 0, 100, departure), _day(2, 100, 300)],
        checkpoints=[_node("first", 50), _node("next_day", 100)],
    )
    start, first, next_day = result["checkpoints"]
    assert first["consumed_minutes"] == 30
    assert first["departure_minute_of_day"] is first["initial_window_minutes"] is None
    assert first["remaining_minutes"] is first["remaining_ratio"] is None
    assert first["remaining_status"] == "unavailable"
    assert first["deadline_exceeded"] is None
    assert start["day_reset"] is False
    assert next_day["remaining_minutes"] == 720
    assert next_day["day_reset"] is True
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("status", ["unavailable", "unknown", None])
def test_missing_departure_status_cannot_be_rescued_by_numeric_clock(status):
    result = _build(days=[_day(1, 0, 300, status=status)])
    assert all(row["remaining_minutes"] is None for row in result["checkpoints"])
    assert result["days"][0]["departure_status"] == "unavailable"
    assert result["status"] == "unavailable"


@pytest.mark.parametrize("minutes", [None, -1, math.nan, math.inf, True])
def test_missing_forward_never_uses_reverse_or_returns_partial_sum(minutes):
    result = _build(bins=[_bin(0, 100, 10), _bin(100, 300, minutes)])
    finish = result["checkpoints"][-1]
    assert finish["consumed_minutes"] is finish["remaining_minutes"] is None
    assert finish["remaining_status"] == "unavailable"
    assert finish["deadline_exceeded"] is None
    json.dumps(result, allow_nan=False)


def test_unavailable_forward_status_overrides_minutes_and_gaps_stay_unknown():
    for bins in (
        [_bin(0, 300, 15, status="unavailable")],
        [_bin(0, 100, 10), _bin(110, 300, 20)],
        [_bin(10, 300, 15)],
        [_bin(0, 290, 15)],
        [],
    ):
        result = _build(bins=bins)
        start, finish = result["checkpoints"]
        assert start["remaining_minutes"] == 720
        assert finish["consumed_minutes"] is finish["remaining_minutes"] is None


@pytest.mark.parametrize(
    "departure, consumed, window, remaining",
    [
        (360, 750, 720, -30),
        (1080, 0, 0, 0),
        (1080, 20, 0, -20),
        (1140, 20, -60, -80),
    ],
)
def test_deadline_values_are_not_clamped_or_wrapped(
    departure, consumed, window, remaining
):
    result = _build(days=[_day(1, 0, 300, departure)], bins=[_bin(0, 300, consumed)])
    row = result["checkpoints"][-1]
    assert row["initial_window_minutes"] == window
    assert row["remaining_minutes"] == remaining
    assert row["deadline_exceeded"] is (remaining < 0)
    assert row["remaining_ratio"] == (remaining / window if window > 0 else None)


@pytest.mark.parametrize(
    "departure_status, bin_status, expected",
    [
        ("observed", "observed", "observed"),
        ("estimated", "observed", "estimated"),
        ("observed", "estimated", "estimated"),
        ("estimated", "estimated", "estimated"),
    ],
)
def test_estimation_propagates_only_from_inputs_used_in_each_row(
    departure_status, bin_status, expected
):
    result = _build(
        days=[_day(1, 0, 300, status=departure_status)],
        bins=[_bin(0, 300, 120, status=bin_status, reverse=None)],
    )
    start, finish = result["checkpoints"]
    assert start["remaining_status"] == departure_status
    assert finish["remaining_status"] == expected
    assert finish["remaining_minutes"] == 600


@pytest.mark.parametrize(
    "days",
    [
        [_day(1, 0, 200), _day(2, 100, 300)],
        [_day(2, 100, 300), _day(1, 0, 100)],
        [_day(1, 0, 100), _day(1, 100, 300)],
        [_day(1, 100, 0)],
        [_day(1, 100, 100)],
        [_day(1, None, 300)],
        [_day(1, 0, 301)],
        [_day(1, -1, 300)],
        [_day(1, 0, math.nan)],
        [
            {**_day(1, 0, 100), "day_id": "same"},
            {**_day(2, 100, 300), "day_id": "same"},
        ],
        [_day(2, 0, 100), _day(1, 100, 300)],
    ],
)
def test_invalid_or_ambiguous_schedule_is_not_sorted_or_invented(days):
    result = _build(days=days)
    assert result["stats"]["schedule_valid"] is False
    assert result["stats"]["inserted_day_start_count"] == 0
    assert result["stats"]["schedule_errors"]
    assert all(day["initial_window_minutes"] is None for day in result["days"])
    for row in result["checkpoints"]:
        assert (
            row["day_id"]
            is row["initial_window_minutes"]
            is row["remaining_minutes"]
            is None
        )
        assert row["day_reset"] is False
    json.dumps(result, allow_nan=False)


def test_empty_schedule_is_unavailable_without_implicit_day():
    result = _build(days=[])
    assert result["days"] == []
    assert result["status"] == "unavailable"
    assert result["stats"]["day_count"] == 0
    assert result["stats"]["inserted_day_start_count"] == 0
    assert all(row["remaining_minutes"] is None for row in result["checkpoints"])


def test_nearest_explicit_safe_point_is_strictly_ahead_and_does_not_reset_budget():
    result = _build(
        bins=[_bin(0, 100, 40), _bin(100, 300, 100)],
        checkpoints=[_node("before", 50), _node("camp_cp", 100), _node("end", 300)],
        safe_points=[_node("far", 200), _node("near", 100), _node("at_start", 0)],
    )
    start, before, camp, finish = result["checkpoints"]
    assert before["next_safe_point_id"] == "near"
    assert before["next_safe_point_label"] == "Near"
    assert before["next_safe_point_distance_m"] == 100
    assert before["forward_to_safe_minutes"] == 20
    assert before["forward_to_safe_status"] == "observed"
    assert before["arrival_margin_minutes"] == 680
    assert before["can_reach_safe_before_cutoff"] is True
    assert before["next_safe_point_kind"] == "historical_candidate"
    assert camp["next_safe_point_id"] == "far"
    assert camp["forward_to_safe_minutes"] == 50
    assert camp["remaining_minutes"] == 680
    assert camp["day_reset"] is False
    assert finish["next_safe_point_id"] is None
    assert finish["forward_to_safe_minutes"] is finish["arrival_margin_minutes"] is None
    assert finish["can_reach_safe_before_cutoff"] is None


def test_explicit_route_end_checkpoint_is_fallback_not_fabricated_from_route_length():
    result = _build(safe_points=[_node("camp", 50)])
    assert result["checkpoints"][0]["next_safe_point_id"] == "camp"
    with_finish = _build(checkpoints=[_node("middle", 100), _node("exit", 300)])
    middle = next(
        row for row in with_finish["checkpoints"] if row["node_id"] == "middle"
    )
    assert middle["next_safe_point_id"] == "exit"
    assert middle["next_safe_point_kind"] == "route_finish_candidate"
    assert middle["forward_to_safe_minutes"] == 120
    no_finish = _build(checkpoints=[_node("middle", 100)])
    assert all(row["next_safe_point_id"] is None for row in no_finish["checkpoints"])


@pytest.mark.parametrize(
    "forward, expected_margin, expected_reach",
    [
        (120, 0, True),
        (150, -30, False),
        (None, None, None),
    ],
)
def test_arrival_margin_subtracts_entire_forward_cost_and_keeps_negative(
    forward, expected_margin, expected_reach
):
    result = _build(
        days=[_day(1, 0, 300, 900)],
        bins=[_bin(0, 100, 60), _bin(100, 300, forward)],
        checkpoints=[_node("cp", 100)],
        safe_points=[_node("next", 300)],
    )
    row = result["checkpoints"][-1]
    assert row["remaining_minutes"] == 120
    assert row["arrival_margin_minutes"] == expected_margin
    assert row["can_reach_safe_before_cutoff"] is expected_reach


def test_unknown_budget_does_not_hide_independent_forward_cost_to_safe_point():
    result = _build(days=[_day(1, 0, 300, None)], safe_points=[_node("camp", 100)])
    row = result["checkpoints"][0]
    assert row["forward_to_safe_minutes"] == 60
    assert row["forward_to_safe_status"] == "observed"
    assert row["arrival_margin_minutes"] is None
    assert row["arrival_margin_status"] == "unavailable"
    assert row["can_reach_safe_before_cutoff"] is None


def test_arrival_estimation_includes_forward_estimate_without_tainting_remaining():
    result = _build(
        bins=[_bin(0, 100, 60), _bin(100, 300, 120, status="estimated")],
        checkpoints=[_node("middle", 100)],
        safe_points=[_node("camp", 200)],
    )
    row = result["checkpoints"][-1]
    assert row["remaining_status"] == "observed"
    assert row["forward_to_safe_status"] == row["arrival_margin_status"] == "estimated"
    assert row["arrival_margin_minutes"] == 600


@pytest.mark.parametrize("cutoff", [None, -1, 1441, math.nan, math.inf, False])
def test_invalid_cutoff_never_defaults_to_six_pm(cutoff):
    result = _build(cutoff_minute_of_day=cutoff)
    assert result["cutoff_minute_of_day"] is None
    assert all(
        row["initial_window_minutes"] is row["remaining_minutes"] is None
        for row in result["checkpoints"]
    )
    json.dumps(result, allow_nan=False)


def test_custom_cutoff_is_respected_without_rounding_minutes():
    result = _build(
        cutoff_minute_of_day=1020.5,
        days=[_day(1, 0, 300, 360.25)],
        bins=[_bin(0, 300, 180.5)],
        checkpoints=[_node("half", 150)],
    )
    row = result["checkpoints"][-1]
    assert row["initial_window_minutes"] == 660.25
    assert row["consumed_minutes"] == 90.25
    assert row["remaining_minutes"] == 570


def test_invalid_checkpoint_and_safe_point_distances_are_not_projected():
    result = _build(
        checkpoints=[_node("valid", 50), _node("outside", 301), _node("bad", math.nan)],
        safe_points=[_node("invalid", -1), _node("far", 301), _node("valid_safe", 150)],
    )
    assert result["stats"]["invalid_checkpoint_count"] == 2
    assert result["stats"]["invalid_safe_point_count"] == 2
    valid = next(row for row in result["checkpoints"] if row["node_id"] == "valid")
    assert valid["next_safe_point_id"] == "valid_safe"
    for row in result["checkpoints"][-2:]:
        assert row["route_distance_m"] is row["remaining_minutes"] is None
        assert row["next_safe_point_id"] is None
    json.dumps(result, allow_nan=False)


def test_overlapping_bins_are_unavailable_but_do_not_erase_known_departure():
    result = _build(bins=[_bin(0, 200, 60), _bin(100, 300, 60)])
    start, finish = result["checkpoints"]
    assert start["remaining_minutes"] == 720
    assert finish["consumed_minutes"] is None
    assert result["stats"]["bin_geometry_valid"] is False


def test_inputs_remain_unchanged_and_result_has_candidate_boundary():
    inputs = {
        "bins": [_bin(0, 300, 120)],
        "checkpoints": [_node("end", 300), _node("start", 0)],
        "days": [_day(1, 0, 100), _day(2, 100, 300, 420)],
        "safe_points": [_node("far", 250), _node("near", 50)],
        "route_distance_m": 300,
    }
    original = deepcopy(inputs)
    result = build_historical_time_windows(**inputs)
    assert inputs == original
    assert result["candidate_only"] is True
    assert result["runtime_safety_truth"] is False
    assert result["boundary"]["candidate_only"] is True
    assert result["boundary"]["runtime_safety_truth"] is False
    assert result["boundary"]["safety_or_passability_determined"] is False
    assert result["boundary"]["actual_sunset_calculated"] is False
    result["days"][0]["departure_minute_of_day"] = 1
    result["checkpoints"][0]["label"] = "changed"
    result["safe_points"][0]["label"] = "changed"
    assert inputs == original
    json.dumps(result, allow_nan=False)


def test_passing_midnight_does_not_reset_without_a_new_explicit_day():
    result = _build(bins=[_bin(0, 300, 2160)])
    row = result["checkpoints"][-1]
    assert row["day_id"] == "d1"
    assert row["remaining_minutes"] == -1440
    assert row["remaining_ratio"] == -2
    assert row["day_reset"] is False
    assert row["deadline_exceeded"] is True


def test_forward_arrival_margin_never_borrows_next_days_budget():
    result = _build(
        days=[_day(1, 0, 100, 1050), _day(2, 100, 300, 360)],
        checkpoints=[_node("before", 50), _node("after", 150)],
        safe_points=[_node("next", 200)],
    )
    before = next(row for row in result["checkpoints"] if row["node_id"] == "before")
    assert before["remaining_minutes"] == 0
    assert before["forward_to_safe_minutes"] == 90
    assert before["arrival_margin_minutes"] == -90
    assert before["can_reach_safe_before_cutoff"] is False
    after = result["checkpoints"][-1]
    assert after["remaining_minutes"] == 690
    assert after["arrival_margin_minutes"] == 660


@pytest.mark.parametrize("factor", [0.01, 1.006512, 1000])
def test_rescaled_route_axis_preserves_proportional_time_minutes(factor):
    inputs = {
        "bins": [_bin(0, 100, 13.5), _bin(100, 300, 27.5)],
        "days": [_day(1, 0, 125), _day(2, 125, 300, 480)],
        "checkpoints": [_node("a", 50), _node("b", 175), _node("end", 300)],
        "safe_points": [_node("s", 225)],
        "route_distance_m": 300,
    }
    baseline = build_historical_time_windows(**inputs)
    scaled = {
        **inputs,
        "bins": [
            {
                **item,
                "start_distance_m": item["start_distance_m"] * factor,
                "end_distance_m": item["end_distance_m"] * factor,
            }
            for item in inputs["bins"]
        ],
        "days": [
            {
                **item,
                "start_distance_m": item["start_distance_m"] * factor,
                "end_distance_m": item["end_distance_m"] * factor,
            }
            for item in inputs["days"]
        ],
        "checkpoints": [
            {**item, "route_distance_m": item["route_distance_m"] * factor}
            for item in inputs["checkpoints"]
        ],
        "safe_points": [
            {**item, "route_distance_m": item["route_distance_m"] * factor}
            for item in inputs["safe_points"]
        ],
        "route_distance_m": 300 * factor,
    }
    transformed = build_historical_time_windows(**scaled)
    for original, changed in zip(
        baseline["checkpoints"], transformed["checkpoints"], strict=True
    ):
        for field in (
            "initial_window_minutes",
            "consumed_minutes",
            "remaining_minutes",
            "remaining_ratio",
            "forward_to_safe_minutes",
            "arrival_margin_minutes",
        ):
            assert (
                changed[field] == pytest.approx(original[field])
                if original[field] is not None
                else changed[field] is None
            )
        assert changed["day_id"] == original["day_id"]
        assert changed["day_reset"] == original["day_reset"]


@pytest.mark.parametrize(
    "key, value",
    [
        ("day_id", None),
        ("day_id", " "),
        ("day_id", []),
        ("day_index", None),
        ("day_index", -1),
        ("day_index", 1.5),
        ("day_index", True),
        ("day_index", math.inf),
    ],
)
def test_invalid_day_identity_does_not_receive_budget(key, value):
    result = _build(days=[{**_day(1, 0, 300), key: value}])
    assert result["stats"]["schedule_valid"] is False
    assert result["days"][0][key] is None
    assert all(row["remaining_minutes"] is None for row in result["checkpoints"])


@pytest.mark.parametrize("distance", [None, -1, math.nan, math.inf, True, 10**400])
def test_invalid_route_distance_does_not_create_departures_or_safe_targets(distance):
    result = _build(distance=distance, safe_points=[_node("camp", 100)])
    assert result["route_distance_m"] is None
    assert result["stats"]["inserted_day_start_count"] == 0
    for row in result["checkpoints"]:
        assert row["route_distance_m"] is row["remaining_minutes"] is None
        assert row["next_safe_point_id"] is None
    json.dumps(result, allow_nan=False)


def test_tied_safe_targets_use_input_order_and_inserted_ids_do_not_collide():
    result = _build(
        checkpoints=[_node("day_start.d1", 50), _node("day_start.d1.1", 75)],
        safe_points=[_node("first", 100), _node("second", 100)],
    )
    departure = result["checkpoints"][0]
    assert departure["node_id"] == "day_start.d1.2"
    assert departure["next_safe_point_id"] == "first"
    assert len({row["node_id"] for row in result["checkpoints"]}) == 3


def test_cutoff_may_equal_end_of_day_without_calendar_wrap():
    result = _build(cutoff_minute_of_day=1440, days=[_day(1, 0, 300, 1140)])
    start, finish = result["checkpoints"]
    assert start["initial_window_minutes"] == 300
    assert finish["remaining_minutes"] == 120


def test_overflowed_derived_values_stay_json_safe_and_unavailable():
    result = _build(
        bins=[_bin(0, 100, 1e308), _bin(100, 300, 1e308)],
        checkpoints=[_node("middle", 100), _node("end", 300)],
    )
    middle = next(row for row in result["checkpoints"] if row["node_id"] == "middle")
    assert middle["remaining_minutes"] == -1e308
    assert middle["arrival_margin_minutes"] is None
    assert middle["arrival_margin_status"] == "unavailable"
    assert result["checkpoints"][-1]["consumed_minutes"] is None
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("gap", [5, 17.5, 45])
def test_overnight_end_anchor_is_available_while_tiny_schedule_hole_is_unknown(gap):
    day_end = 100
    next_start = day_end + gap
    checkpoints = [
        _node("before_overnight", 75),
        _node("d1_overnight", day_end),
        _node("just_after", math.nextafter(day_end, math.inf)),
        _node("mid_gap", day_end + gap / 2),
        _node("just_before", math.nextafter(next_start, -math.inf)),
        _node("later", 200),
        _node("d2_overnight", 300),
    ]
    result = _build(
        checkpoints=checkpoints,
        days=[
            _day(1, 0, day_end, status="estimated"),
            _day(2, next_start, 300, 420, status="estimated"),
        ],
        safe_points=[_node("d1_overnight", day_end), _node("d2_overnight", 300)],
    )
    rows = {row["node_id"]: row for row in result["checkpoints"]}
    before = rows["before_overnight"]
    assert before["next_safe_point_id"] == "d1_overnight"
    assert before["forward_to_safe_minutes"] == 15
    assert before["arrival_margin_minutes"] == 660
    assert before["arrival_margin_status"] == "estimated"
    overnight = rows["d1_overnight"]
    assert overnight["day_id"] == "d1"
    assert overnight["remaining_minutes"] == 660
    assert overnight["remaining_status"] == "estimated"
    assert overnight["day_reset"] is False
    assert overnight["node_kind"] == "checkpoint"
    for node_id in ("just_after", "mid_gap", "just_before"):
        row = rows[node_id]
        assert row["day_id"] is row["initial_window_minutes"] is None
        assert row["remaining_minutes"] is row["arrival_margin_minutes"] is None
        assert row["remaining_status"] == "unavailable"
        assert row["day_reset"] is False
    reset = next(
        row for row in result["checkpoints"] if row["route_distance_m"] == next_start
    )
    assert reset["node_kind"] == "day_start"
    assert reset["day_id"] == "d2"
    assert reset["day_reset"] is True
    assert reset["remaining_minutes"] == 660
    assert reset["remaining_status"] == "estimated"
    assert rows["later"]["consumed_minutes"] == pytest.approx((200 - next_start) * 0.6)
    assert rows["later"]["remaining_status"] == "estimated"
    assert rows["d2_overnight"]["remaining_status"] == "estimated"
    assert result["stats"]["inserted_day_start_count"] == 2
    assert result["stats"]["unavailable_remaining_count"] == 3
