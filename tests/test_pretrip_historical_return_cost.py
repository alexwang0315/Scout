from __future__ import annotations

from copy import deepcopy
import json
import math

import pytest

from pretrip_historical_return_cost import build_historical_return_cost


def _node(node_id, distance):
    return {"node_id": node_id, "label": node_id.title(), "route_distance_m": distance}


def _bin(start, end, forward, reverse, *, reverse_status="observed"):
    return {
        "start_distance_m": start,
        "end_distance_m": end,
        "forward": {"average_minutes": forward, "status": "observed"},
        "reverse": {"average_minutes": reverse, "status": reverse_status},
    }


def _build(bins, checkpoints, camps=(), budget=60, distance=300):
    return build_historical_return_cost(
        bins=bins,
        checkpoints=checkpoints,
        camps=camps,
        daily_budget_minutes=budget,
        route_distance_m=distance,
    )


def test_asymmetric_directional_costs_are_integrated_by_overlap():
    result = _build(
        [_bin(0, 100, 10, 30), _bin(100, 200, 20, 40)],
        [_node("entry", 0), _node("middle", 50), _node("finish", 150)],
    )
    entry, middle, finish = result["checkpoints"]
    assert entry["next_cp_average_minutes"] == 5
    assert middle["next_cp_average_minutes"] == 15
    assert middle["return_to_entry_minutes"] == 15
    assert finish["return_to_entry_minutes"] == 50
    assert finish["return_cost_status"] == "observed"
    assert middle["next_cp_id"] == "finish"
    assert middle["next_cp_distance_m"] == 150
    assert finish["next_cp_id"] is None
    assert finish["next_cp_average_minutes"] is None
    assert finish["next_cp_timing_status"] == "unavailable"


def test_exact_budget_keeps_entry_then_switches_and_grows_from_camp():
    result = _build(
        [_bin(0, 300, 6, 180)],
        [
            _node("entry", 0),
            _node("equal", 100),
            _node("beyond", 150),
            _node("later", 200),
        ],
        camps=[_node("camp", 100)],
    )
    entry, equal, beyond, later = result["checkpoints"]
    assert equal["return_cost_minutes"] == 60
    assert equal["return_target_kind"] == "trailhead"
    assert equal["within_historical_day"] is True
    assert equal["budget_ratio"] == 1
    assert equal["decision_boundary"] is False
    assert equal["entry_day_exceeded"] is False
    assert equal["entry_decision_boundary"] is False
    assert beyond["return_to_entry_minutes"] == 90
    assert beyond["return_target_id"] == "camp"
    assert beyond["return_target_kind"] == "camp"
    assert beyond["return_target_distance_m"] == 100
    assert beyond["return_cost_minutes"] == 30
    assert beyond["budget_ratio"] == 0.5
    assert beyond["decision_boundary"] is True
    assert beyond["entry_day_exceeded"] is True
    assert beyond["entry_decision_boundary"] is True
    assert later["return_cost_minutes"] == 60
    assert later["decision_boundary"] is False
    assert later["entry_day_exceeded"] is True
    assert later["entry_decision_boundary"] is False
    assert entry["return_target_id"] == "entry"


def test_inserted_camps_reset_at_exact_location_and_use_latest_preceding_camp():
    result = _build(
        [_bin(0, 300, 30, 180)],
        [_node("entry", 0), _node("p1", 180), _node("p2", 280)],
        camps=[_node("camp2", 250), _node("camp1", 150)],
    )
    entry, camp1, p1, camp2, p2 = result["checkpoints"]
    assert [row["node_id"] for row in result["checkpoints"]] == [
        "entry",
        "camp1",
        "p1",
        "camp2",
        "p2",
    ]
    assert camp1["node_kind"] == camp2["node_kind"] == "camp"
    assert camp1["return_target_id"] == "camp1"
    assert camp2["return_target_id"] == "camp2"
    assert camp1["return_cost_minutes"] == camp2["return_cost_minutes"] == 0
    assert camp1["decision_boundary"] is camp2["decision_boundary"] is True
    assert p1["return_cost_minutes"] == pytest.approx(18)
    assert p2["return_cost_minutes"] == pytest.approx(18)
    assert entry["next_cp_id"] == "p1"
    assert entry["next_cp_average_minutes"] == 18
    assert p1["next_cp_id"] == "p2"
    assert p1["next_cp_average_minutes"] == 10
    assert camp1["next_cp_id"] == "p1"
    assert camp1["next_cp_average_minutes"] == 3
    assert camp2["next_cp_id"] == "p2"
    assert camp2["next_cp_average_minutes"] == 3
    assert camp1["entry_decision_boundary"] is True
    assert camp2["entry_decision_boundary"] is False
    assert result["stats"]["input_checkpoint_count"] == 3
    assert result["stats"]["inserted_camp_count"] == 2
    assert result["stats"]["checkpoint_count"] == 5


def test_no_camp_retains_exhausted_entry_cost_without_fake_boundary():
    result = _build([_bin(0, 300, 10, 180)], [_node("cp", 200)])
    cp = result["checkpoints"][0]
    assert cp["return_cost_minutes"] == 120
    assert cp["return_target_kind"] == "trailhead"
    assert cp["within_historical_day"] is False
    assert cp["budget_ratio"] == 2
    assert cp["decision_boundary"] is False
    assert cp["entry_day_exceeded"] is True
    assert cp["entry_decision_boundary"] is True


def test_no_camp_entry_threshold_marks_only_first_known_exceeded_checkpoint():
    result = _build(
        [_bin(0, 300, 10, 180)],
        [
            _node("entry", 0),
            _node("equal", 100),
            _node("crossing", 150),
            _node("coincident", 150),
            _node("later", 200),
        ],
    )
    rows = result["checkpoints"]
    assert [cp["entry_day_exceeded"] for cp in rows] == [False, False, True, True, True]
    assert [cp["entry_decision_boundary"] for cp in rows] == [
        False,
        False,
        True,
        False,
        False,
    ]
    assert not any(cp["decision_boundary"] for cp in rows)
    assert result["stats"]["entry_decision_boundary_count"] == 1


def test_midway_camp_does_not_shorten_original_checkpoint_duration():
    bins = [_bin(0, 100, 10, 30), _bin(100, 200, 30, 50)]
    checkpoints = [_node("entry", 0), _node("finish", 200)]
    without_camp = _build(bins, checkpoints)
    with_camp = _build(bins, checkpoints, camps=[_node("midway", 100)])
    entry, camp, finish = with_camp["checkpoints"]
    assert entry["next_cp_id"] == camp["next_cp_id"] == "finish"
    assert entry["next_cp_average_minutes"] == 40
    assert (
        entry["next_cp_average_minutes"]
        == without_camp["checkpoints"][0]["next_cp_average_minutes"]
    )
    assert camp["next_cp_average_minutes"] == 30
    assert finish["next_cp_id"] is None


def test_camp_must_not_hide_missing_forward_coverage_to_next_original_cp():
    result = _build(
        [_bin(0, 100, 10, 30), _bin(100, 200, None, 50)],
        [_node("entry", 0), _node("finish", 200)],
        camps=[_node("midway", 100)],
    )
    entry = result["checkpoints"][0]
    assert entry["next_cp_id"] == "finish"
    assert entry["next_cp_average_minutes"] is None
    assert entry["next_cp_timing_status"] == "unavailable"


def test_camps_after_last_original_cp_have_no_next_cp_without_reducing_readiness():
    result = _build(
        [_bin(0, 300, 30, 60)],
        [_node("entry", 0), _node("last", 100)],
        camps=[_node("camp1", 200), _node("camp2", 250)],
    )
    entry, last, camp1, camp2 = result["checkpoints"]
    assert entry["next_cp_id"] == "last"
    assert all(cp["next_cp_id"] is None for cp in (last, camp1, camp2))
    assert result["status"] == "ready"


@pytest.mark.parametrize("reverse", [None, math.nan, math.inf, -math.inf, -1, True])
def test_bad_reverse_never_uses_forward_or_returns_partial_sum(reverse):
    result = _build(
        [_bin(0, 100, 20, 30), _bin(100, 200, 25, reverse)],
        [_node("start", 0), _node("finish", 200)],
        camps=[_node("camp", 150)],
    )
    cp = result["checkpoints"][-1]
    assert cp["return_to_entry_minutes"] is None
    assert cp["return_cost_minutes"] is None
    assert cp["return_cost_status"] == "unavailable"
    assert cp["within_historical_day"] is None
    assert cp["return_target_kind"] == "trailhead"
    assert cp["decision_boundary"] is False
    assert cp["entry_day_exceeded"] is None
    assert cp["entry_decision_boundary"] is False
    assert result["checkpoints"][0]["next_cp_timing_status"] == "observed"
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("gap", [(0, 10), (50, 60), (190, 200)])
def test_any_gap_makes_whole_interval_unavailable(gap):
    start, end = gap
    bins = []
    if start:
        bins.append(_bin(0, start, 10, 20))
    if end < 200:
        bins.append(_bin(end, 200, 15, 25))
    result = _build(bins, [_node("entry", 0), _node("finish", 200)])
    entry, finish = result["checkpoints"]
    assert entry["next_cp_average_minutes"] is None
    assert entry["next_cp_timing_status"] == "unavailable"
    assert finish["return_cost_minutes"] is None
    assert finish["return_cost_status"] == "unavailable"


def test_unavailable_status_overrides_numeric_duration():
    result = _build(
        [_bin(0, 300, 20, 30, reverse_status="unavailable")],
        [_node("cp", 200)],
    )
    assert result["checkpoints"][0]["return_cost_minutes"] is None
    assert result["status"] == "unavailable"


def test_missing_reverse_record_stays_unavailable_with_available_forward():
    interval = _bin(0, 300, 20, 30)
    del interval["reverse"]
    result = _build([interval], [_node("entry", 0), _node("cp", 300)])
    entry, cp = result["checkpoints"]
    assert entry["next_cp_average_minutes"] == 20
    assert cp["return_cost_minutes"] is None
    assert cp["return_cost_status"] == "unavailable"


@pytest.mark.parametrize("forward", [None, math.nan, math.inf, -1])
def test_bad_forward_does_not_poison_independent_reverse_cost(forward):
    result = _build(
        [_bin(0, 300, forward, 30)],
        [_node("entry", 0), _node("cp", 300)],
    )
    entry, cp = result["checkpoints"]
    assert entry["next_cp_average_minutes"] is None
    assert entry["next_cp_timing_status"] == "unavailable"
    assert cp["return_cost_minutes"] == 30
    assert cp["return_cost_status"] == "observed"


def test_zero_length_bins_and_bad_data_outside_requested_span_do_not_taint_cost():
    result = _build(
        [_bin(0, 100, 10, 20), _bin(50, 50, None, None), _bin(100, 200, None, None)],
        [_node("entry", 0), _node("cp", 100)],
    )
    entry, cp = result["checkpoints"]
    assert entry["next_cp_average_minutes"] == 10
    assert cp["return_cost_minutes"] == 20
    assert cp["return_cost_status"] == "observed"


def test_estimated_status_propagates_only_for_the_integrated_direction():
    bins = [_bin(0, 100, 10, 20), _bin(100, 200, 15, 30, reverse_status="estimated")]
    result = _build(bins, [_node("entry", 0), _node("cp", 150)])
    entry, cp = result["checkpoints"]
    assert entry["next_cp_timing_status"] == "observed"
    assert cp["return_cost_status"] == "estimated"
    assert cp["return_cost_minutes"] == 35
    bins[1]["forward"]["status"] = "estimated"
    result = _build(bins, [_node("entry", 0), _node("cp", 150)])
    assert result["checkpoints"][0]["next_cp_timing_status"] == "estimated"


@pytest.mark.parametrize("budget", [None, math.nan, math.inf, -1, True])
def test_unknown_budget_keeps_entry_costs_and_unknown_threshold(budget):
    result = _build(
        [_bin(0, 300, 20, 180)],
        [_node("cp", 200)],
        camps=[_node("camp", 100)],
        budget=budget,
    )
    cp = result["checkpoints"][-1]
    assert result["daily_budget_minutes"] is None
    assert cp["return_cost_minutes"] == 120
    assert cp["return_target_kind"] == "trailhead"
    assert cp["within_historical_day"] is None
    assert cp["budget_ratio"] is None
    assert cp["decision_boundary"] is False
    assert cp["entry_day_exceeded"] is None
    assert cp["entry_decision_boundary"] is False


def test_zero_distance_has_zero_cost_without_bins_including_zero_budget():
    result = _build([], [_node("entry", 0)], budget=0, distance=0)
    cp = result["checkpoints"][0]
    assert cp["return_cost_minutes"] == 0
    assert cp["return_cost_status"] == "observed"
    assert cp["within_historical_day"] is True
    assert cp["budget_ratio"] is None
    assert cp["decision_boundary"] is False
    assert cp["entry_day_exceeded"] is False
    assert cp["entry_decision_boundary"] is False


def test_coincident_checkpoint_and_camp_nodes_preserve_ids_without_extra_nodes():
    result = _build(
        [_bin(0, 300, 30, 180)],
        [_node("entry", 0), _node("cp", 200), _node("other", 200)],
        camps=[_node("camp", 200), _node("cp", 200)],
    )
    entry, cp, other = result["checkpoints"]
    assert [row["node_id"] for row in result["checkpoints"]] == ["entry", "cp", "other"]
    assert cp["next_cp_id"] == "other"
    assert cp["next_cp_average_minutes"] == 0
    assert cp["next_cp_timing_status"] == "observed"
    assert cp["return_cost_minutes"] == other["return_cost_minutes"] == 0
    assert cp["return_target_id"] == other["return_target_id"]
    assert cp["decision_boundary"] is True
    assert other["decision_boundary"] is False
    assert result["stats"]["inserted_camp_count"] == 0


def test_unknown_entry_after_switch_does_not_manufacture_a_new_target():
    result = _build(
        [_bin(0, 150, 10, 90), _bin(150, 300, 10, None)],
        [_node("entry", 0), _node("cp", 280)],
        camps=[_node("camp1", 150), _node("camp2", 250)],
    )
    entry, camp1, camp2, cp = result["checkpoints"]
    assert camp1["return_target_id"] == "camp1"
    assert camp2["return_target_id"] == cp["return_target_id"] == "camp1"
    assert camp2["decision_boundary"] is cp["decision_boundary"] is False
    assert cp["return_cost_minutes"] is None
    assert cp["within_historical_day"] is None


@pytest.mark.parametrize("bad", [math.nan, math.inf, -1])
def test_invalid_checkpoint_distance_is_preserved_as_unavailable(bad):
    result = _build([_bin(0, 300, 10, 20)], [_node("bad", bad)])
    cp = result["checkpoints"][0]
    assert cp["node_id"] == "bad"
    assert cp["route_distance_m"] is None
    assert cp["return_cost_minutes"] is None
    assert result["stats"]["invalid_checkpoint_count"] == 1
    json.dumps(result, allow_nan=False)


def test_invalid_bin_geometry_and_overflow_fail_closed():
    for bins in (
        [_bin(math.nan, 100, 10, 20)],
        [_bin(-1, 100, 10, 20)],
        [_bin(100, 0, 10, 20)],
        [_bin(0, 150, 10, 20), _bin(100, 200, 10, 20)],
        [_bin(0, 100, 10, 1e308), _bin(100, 200, 10, 1e308)],
    ):
        result = _build(bins, [_node("cp", 200)])
        assert result["checkpoints"][0]["return_cost_minutes"] is None
        json.dumps(result, allow_nan=False)


def test_build_is_pure_and_has_explicit_candidate_and_budget_policy():
    inputs = {
        "bins": [_bin(0, 300, 10, 20)],
        "checkpoints": [_node("finish", 300), _node("entry", 0)],
        "camps": [_node("camp", 100)],
        "daily_budget_minutes": 60,
        "route_distance_m": 300,
    }
    before = deepcopy(inputs)
    result = build_historical_return_cost(**inputs)
    assert inputs == before
    assert result == build_historical_return_cost(**inputs)
    assert result["schema_version"] == "historical_return_cost.v1"
    assert result["candidate_only"] is True
    assert result["runtime_safety_truth"] is False
    assert result["boundary"]["live_remaining_day_budget"] is False
    assert result["policy"]["budget_basis"] == "historical_gpx_full_day_moving_minutes"
    assert result["status"] == "ready"
    assert result["stats"]["checkpoint_count"] == 3
    json.dumps(result, allow_nan=False)
