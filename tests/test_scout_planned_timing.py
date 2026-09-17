"""Terrain/team planning proof: actual ordered geometry, constraints, and gaps."""
from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from scout_planned_timing import TerrainTimingOptions, estimate_segment_timing, plan_terrain_schedule


START = "2026-10-01T06:00:00+08:00"


def route(elevations, step=.005):
    return [{"point_index": i, "lat": 24 + i * step, "lon": 121., "ele": elevation,
             "source_id": "candidate.geometry", "source_point_index": i} for i, elevation in enumerate(elevations)]


def assumptions(**changes):
    return {"assumed_flat_speed_kmh": 3., "assumed_ascent_m_per_hour": 400.,
            "assumed_descent_m_per_hour": 800., "uncertainty_fraction": .2,
            "source_refs": ["review/operator-assumptions.json"], **changes}


def daylight(day, end="18:00"):
    return {"sunrise_at": f"2026-10-{day:02d}T05:30:00+08:00",
            "sunset_at": f"2026-10-{day:02d}T{end}:00+08:00", "source_ref": f"daylight/2026-10-{day:02d}.json"}


def codes(value):
    return {issue["code"] for issue in value["conflicts"]}


def test_high_gain_is_slower_than_same_flat_geometry_and_emits_explicit_bounds():
    flat = estimate_segment_timing(route([100, 100]), options=assumptions())
    gain = estimate_segment_timing(route([100, 1700]), options=assumptions())
    assert gain["duration_minutes"] == 240
    assert gain["duration_minutes"] > flat["duration_minutes"] * 10
    assert gain["lower_minutes"] == 192
    assert gain["upper_minutes"] == 288
    assert gain["ascent_m"] == 1600 and gain["descent_m"] == 0
    assert gain["member_inputs"][0]["assumed_fields"] == ["flat_speed_kmh", "ascent_m_per_hour", "descent_m_per_hour"]
    assert gain["assumptions"]["personal_capability_verified"] is False
    assert gain["assumptions"]["uncertainty_kind"].endswith("not_statistical_confidence")


def test_reverse_recomputes_descent_instead_of_reusing_forward_gpx_clock():
    outward = route([100, 1700])
    outward[0]["time"], outward[1]["time"] = "2020-01-01T06:00:00Z", "2020-01-01T07:00:00Z"
    reverse = [dict(p, point_index=i) for i, p in enumerate(reversed(outward))]
    a = estimate_segment_timing(outward, options=assumptions())
    b = estimate_segment_timing(reverse, options=assumptions())
    assert a["duration_minutes"] == 240 and b["duration_minutes"] == 120
    assert b["ascent_m"] == 0 and b["descent_m"] == 1600
    assert a["ordered_geometry_sha256"] != b["ordered_geometry_sha256"]
    assert b["assumptions"]["historical_timestamps_reused"] is False


def test_team_uses_each_edge_slowest_member_and_retains_source_provenance():
    members = [
        {"member_id": "flat_fast_climb_slow", "flat_speed_mps": 1.4, "ascent_speed_vertical_m_per_hour": 200,
         "descent_speed_mps": 1., "source_refs": ["pace/observed-a.json"]},
        {"member_id": "flat_slow_climb_fast", "scout_pace_coefficient": {"flat_speed_mps": .5, "downhill_speed_mps": .4},
         "ascent_m_per_hour": 800, "source_refs": ["pace/observed-b.json"]},
    ]
    climb = estimate_segment_timing(route([100, 900]), options=assumptions(team_members=members))
    flat = estimate_segment_timing(route([100, 100]), options=assumptions(team_members=members))
    assert climb["edges"][0]["slowest_member_id"] == "flat_fast_climb_slow"
    assert flat["edges"][0]["slowest_member_id"] == "flat_slow_climb_fast"
    assert climb["duration_minutes"] == 240
    assert set(climb["source_refs"]) >= {"pace/observed-a.json", "pace/observed-b.json"}
    assert all(not member["assumed_fields"] for member in climb["member_inputs"])


def test_observed_downhill_horizontal_rate_is_supported_without_fabricated_vertical_rate():
    result = estimate_segment_timing(route([900, 100]), options={
        "team_members": [{"member_id": "hiker", "flat_speed_mps": 1., "descent_speed_mps": .25}],
        "uncertainty_fraction": 0})
    assert result["status"] == "estimated"
    assert result["duration_minutes"] == pytest.approx(result["distance_m"] / 15.)
    assert result["member_inputs"][0]["descent_m_per_hour"] is None
    assert result["edges"][0]["member_estimates"][0]["horizontal_method"] == "slower_of_flat_and_downhill_speed"


def test_unknown_team_member_does_not_disappear_behind_average_or_generic_default():
    result = estimate_segment_timing(route([100, 300]), options=assumptions(team_members=[
        {"member_id": "known", "flat_speed_mps": 1, "ascent_m_per_hour": 400}, {"member_id": "unknown"}]))
    assert result["duration_minutes"] is None
    assert "member:unknown:flat_speed_kmh" in result["missing_inputs"]
    assert "member:unknown:ascent_m_per_hour" in result["missing_inputs"]
    explicit = estimate_segment_timing(route([100, 300]), options=assumptions(
        team_members=[{"member_id": "unknown"}], use_assumptions_for_missing_members=True))
    assert explicit["status"] == "estimated"
    assert "ascent_m_per_hour" in explicit["member_inputs"][0]["assumed_fields"]
    assert explicit["assumptions"]["personal_capability_verified"] is False


def test_technical_surface_and_load_weather_slowdowns_are_explainable_and_not_double_counted():
    points = route([100, 500]); points[1]["surface"] = "technical"
    member = {"member_id": "hiker", "flat_speed_mps": 1, "ascent_m_per_hour": 400,
              "technical_terrain_slowdown_ratio": .5, "load_impact_ratio": .2, "weather_impact_ratio": .25}
    result = estimate_segment_timing(points, options={"team_members": [member], "uncertainty_fraction": 0})
    assert result["duration_minutes"] == pytest.approx(200.)
    override = estimate_segment_timing(points, options={"team_members": [member], "surface_time_multipliers": {"technical": 1.5}})
    assert override["duration_minutes"] == pytest.approx(150.)
    assert "technical" not in override["edges"][0]["member_estimates"][0]["applied_slowdown_ratios"]


def test_unknown_surface_and_missing_elevation_are_visible_not_zero_gain():
    points = route([100, None]); points[1]["surface"] = "unmapped_scree"
    result = estimate_segment_timing(points, options=assumptions())
    assert result["ascent_m"] is None and result["descent_m"] is None
    assert result["duration_minutes"] is None
    assert "elevation_missing" in result["missing_inputs"]
    assert any("surface_time_multiplier:unmapped_scree" in value for value in result["missing_inputs"])


def test_geometry_gap_keeps_full_eta_unknown_even_after_an_explicit_later_departure():
    points = route([100, 500, 800, 1200]); points[2]["break_before"] = True
    result = plan_terrain_schedule(points, options=assumptions(), departure_at=START, events=[
        {"kind": "depart", "point_index": 2, "departure_at": "2026-10-01T13:00:00+08:00"}])
    assert result["finish_at"] is None and result["total_moving_minutes"] is None
    assert result["known_moving_minutes"] > 0
    assert result["conditional_finish_at"] is not None
    assert result["days"][0]["arrival_at"] is None
    assert result["complete_route_eta"] is False
    gap = next(e for e in result["timeline"] if e["point_index"] == 2)
    assert "route_geometry_gap" in gap["missing_inputs"]


def test_missing_rate_stays_unknown_even_if_points_have_trh_costs():
    points = route([100, 500]); points[1]["trh_cost"] = 12.; points[1]["cost_hours"] = 3
    result = estimate_segment_timing(points)
    assert result["duration_minutes"] is None
    assert result["assumptions"]["trh_cost_used_as_time"] is False


def test_fixed_stops_are_separate_and_shift_eta_without_changing_moving_time():
    points = route([100, 500, 900])
    base = plan_terrain_schedule(points, options=assumptions(), departure_at=START)
    paused = plan_terrain_schedule(points, options=assumptions(), departure_at=START, events=[
        {"kind": "stop", "point_index": 1, "duration_minutes": 40, "label": "人工停留"}])
    assert base["total_moving_minutes"] == paused["total_moving_minutes"] == 120
    assert paused["fixed_rest_minutes"] == 40 and paused["estimated_rest_minutes"] == 0
    assert datetime.fromisoformat(paused["finish_at"]) - datetime.fromisoformat(base["finish_at"]) == timedelta(minutes=40)
    assert paused["ordered_geometry_sha256"] == base["ordered_geometry_sha256"]


def test_recurring_rest_allowance_is_separate_and_requires_location_review():
    result = plan_terrain_schedule(route([100, 500, 900, 1300]), options=assumptions(
        rest_every_moving_minutes=50, rest_duration_minutes=10), departure_at=START)
    assert result["total_moving_minutes"] == 180
    assert result["estimated_rest_minutes"] == 20
    assert result["fixed_rest_minutes"] == 0
    allowances = [row for row in result["timeline"] if row["kind"] == "rest_allowance"]
    assert len(allowances) == 2 and all(row["location_review_required"] for row in allowances)


def test_auto_multiday_camps_respect_upper_bounds_and_keep_water_capacity_legal_unknown():
    points = route([100, 500, 900, 1300, 1700, 2100, 2500])
    options = assumptions(max_daily_moving_minutes=150, auto_schedule_camps=True,
        next_day_departure_time="06:00", minimum_overnight_minutes=600,
        require_daylight=True, daylight_windows=[daylight(1), daylight(2), daylight(3)],
        campsite_candidates=[{"candidate_id": "camp-a", "point_index": 2, "label": "候選 A", "slope_degrees": 3.},
                            {"candidate_id": "camp-b", "point_index": 4, "label": "候選 B", "slope_degrees": 2.}])
    result = plan_terrain_schedule(points, options=options, departure_at=START)
    assert result["status"] == "needs_review" and result["complete_route_eta"]
    assert [day["day_id"] for day in result["days"]] == ["D1", "D2", "D3"]
    assert [day["end_point_index"] for day in result["days"]] == [2, 4, 6]
    assert all(day["moving_minutes_upper"] <= 150 for day in result["days"])
    assert result["finish_at"] == "2026-10-03T08:00:00+08:00"
    assert [e["point_index"] for e in result["generated_camp_events"]] == [2, 4]
    assert all(review["water_available"] is None and review["legal_use"] is None for review in result["camp_reviews"])
    assert "camp-a:capacity_persons" in result["campsite_missing_inputs"]
    assert not any(codes(result))


def test_daylight_limit_can_drive_camp_selection_without_a_moving_limit():
    result = plan_terrain_schedule(route([100, 500, 900, 1300, 1700]), departure_at=START,
        options=assumptions(auto_schedule_camps=True, next_day_departure_time="06:00",
            daylight_windows=[daylight(1, "08:30"), daylight(2, "08:30")],
            campsite_candidates=[{"candidate_id": "camp", "point_index": 2}]))
    assert len(result["days"]) == 2
    assert result["generated_camp_events"][0]["point_index"] == 2
    assert result["finish_at"] == "2026-10-02T08:00:00+08:00"


def test_unreachable_or_explicitly_unusable_camp_does_not_become_feasible():
    result = plan_terrain_schedule(route([100, 500, 900, 1300, 1700]), departure_at=START,
        options=assumptions(auto_schedule_camps=True, next_day_departure_time="06:00", max_daily_moving_minutes=150,
            party_size=4, campsite_candidates=[{"candidate_id": "small", "point_index": 2, "capacity_persons": 2},
                                              {"candidate_id": "too-late", "point_index": 3}]))
    assert not result["generated_camp_events"]
    assert "no_reachable_campsite_before_limit" in codes(result)
    assert result["status"] == "conflict"
    assert result["known_moving_minutes"] == 240


def test_fixed_camp_departure_deadline_and_overnight_rest_constraints_do_not_accelerate_team():
    result = plan_terrain_schedule(route([100, 500, 900]), departure_at=START,
        options=assumptions(minimum_overnight_minutes=600), events=[
            {"kind": "deadline", "point_index": 1, "latest_arrival_at": "2026-10-01T06:30:00+08:00"},
            {"kind": "camp", "point_index": 1, "departure_at": "2026-10-01T08:00:00+08:00"}])
    assert result["total_moving_minutes"] == 120
    assert "arrival_constraint_unsatisfied" in codes(result)
    assert "minimum_overnight_rest_unsatisfied" in codes(result)
    assert result["finish_at"] == "2026-10-01T09:00:00+08:00"


def test_missing_camp_departure_cannot_produce_full_eta_or_silent_next_day_clock():
    result = plan_terrain_schedule(route([100, 500, 900]), departure_at=START,
        options=assumptions(), events=[{"kind": "camp", "point_index": 1}])
    assert result["finish_at"] is None
    assert any(row["code"] == "camp_departure_missing" for row in result["unknowns"])
    assert result["days"][1]["departure_at"] is None


def test_repeated_coordinates_use_point_occurrences_for_stops_and_camps():
    points = route([100, 500, 100]); points[2]["lat"] = points[0]["lat"]
    result = plan_terrain_schedule(points, departure_at=START, options=assumptions(), events=[
        {"kind": "stop", "point_index": 2, "duration_minutes": 40}])
    stop = next(e for e in result["timeline"] if e["kind"] == "fixed_stop")
    assert stop["point_index"] == 2
    assert result["total_moving_minutes"] == 90
    assert result["fixed_rest_minutes"] == 40


@pytest.mark.parametrize("changes", [
    {"assumed_flat_speed_kmh": 0}, {"assumed_ascent_m_per_hour": float("nan")},
    {"surface_time_multipliers": {"mud": .5}}, {"uncertainty_fraction": 1},
    {"rest_every_moving_minutes": 60}, {"next_day_departure_time": "25:99"},
    {"daylight_windows": [{"sunrise_at": "2026-10-01T06:00:00", "sunset_at": "2026-10-01T18:00:00", "source_ref": "test"}]},
])
def test_invalid_or_ambiguous_assumptions_fail_validation(changes):
    with pytest.raises((ValueError, ValidationError)):
        TerrainTimingOptions.model_validate(changes)


def test_invalid_member_reduction_ratio_and_naive_departure_fail_closed():
    with pytest.raises(ValueError, match="slowdown"):
        estimate_segment_timing(route([100, 100]), options={"team_members": [{"member_id": "x", "flat_speed_mps": 1, "load_slowdown_ratio": 1.2}]})
    with pytest.raises(ValueError, match="timezone"):
        plan_terrain_schedule(route([100, 100]), options=assumptions(), departure_at="2026-10-01T06:00:00")


def test_missing_party_members_are_not_silently_dropped_from_slowest_member_basis():
    result = estimate_segment_timing(route([100, 100]), options=assumptions(
        team_members=[{"member_id": "known", "flat_speed_mps": 1}], party_size=3))
    assert result["duration_minutes"] is None
    assert "member:missing_party_member_2:flat_speed_kmh" in result["missing_inputs"]
    assert "member:missing_party_member_3:flat_speed_kmh" in result["missing_inputs"]


def test_relative_overnight_rest_remains_exact_despite_uncertain_arrival():
    result = plan_terrain_schedule(route([100, 500, 900]), departure_at=START,
        options=assumptions(minimum_overnight_minutes=600), events=[
            {"kind": "camp", "point_index": 1, "duration_minutes": 600}])
    assert "minimum_overnight_rest_unsatisfied" not in codes(result)
    assert result["finish_at"] == "2026-10-01T18:00:00+08:00"
    assert result["finish_at_lower"] == "2026-10-01T17:36:00+08:00"
    assert result["finish_at_upper"] == "2026-10-01T18:24:00+08:00"


def test_explicit_start_event_supplies_departure_without_an_unresolved_false_gap():
    result = plan_terrain_schedule(route([100, 500]), options=assumptions(), events=[
        {"kind": "depart", "point_index": 0, "departure_at": START}])
    assert result["complete_route_eta"] and result["finish_at"] == "2026-10-01T07:00:00+08:00"
    assert not result["unknowns"]


def test_geometry_gap_has_no_nested_fictional_duration_and_preserves_unknown():
    points = route([100, 500]); points[1]["break_before"] = True
    result = estimate_segment_timing(points, options=assumptions())
    assert result["duration_minutes"] is None and result["known_moving_minutes"] == 0
    assert all("duration_minutes" not in member for member in result["edges"][0]["member_estimates"])


def test_camp_at_route_finish_does_not_replace_route_arrival_with_next_day_departure():
    result = plan_terrain_schedule(route([100, 500]), options=assumptions(), departure_at=START, events=[
        {"kind": "camp", "point_index": 1, "departure_at": "2026-10-02T06:00:00+08:00"}])
    assert result["finish_at"] == "2026-10-01T07:00:00+08:00"
    assert len(result["days"]) == 1


def test_camp_without_water_keeps_water_plan_open_unless_water_was_a_declared_requirement():
    options = assumptions(campsite_candidates=[{"candidate_id": "dry-camp", "point_index": 1, "water_available": False}])
    event = {"kind": "camp", "point_index": 1, "departure_at": "2026-10-02T06:00:00+08:00"}
    result = plan_terrain_schedule(route([100, 500, 900]), options=options, departure_at=START, events=[event])
    assert "dry-camp:camp_water_plan" in result["campsite_missing_inputs"]
    assert "campsite_conditions_unsatisfied" not in codes(result)
    required = plan_terrain_schedule(route([100, 500, 900]), options={**options, "require_camp_water": True}, departure_at=START, events=[event])
    assert "campsite_conditions_unsatisfied" in codes(required)


def test_schedule_serializes_only_relevant_pace_inputs_not_unrelated_health_payload():
    result = plan_terrain_schedule(route([100, 100]), departure_at=START, options=assumptions(team_members=[
        {"member_id": "one", "flat_speed_mps": 1, "private_medical_note": "should not be carried into a timing report"}]))
    import json
    assert "private_medical_note" not in json.dumps(result)


def test_timing_edges_preserve_reverse_source_occurrences_and_evidence_refs():
    points = route([500, 100])
    points[0]["source_point_index"], points[1]["source_point_index"] = 20, 19
    points[0]["source_part_index"] = points[1]["source_part_index"] = 2
    result = plan_terrain_schedule(points, departure_at=START, options=assumptions())
    edge = result["timeline"][0]
    assert edge["source_start_point_index"] == 20 and edge["source_end_point_index"] == 19
    assert edge["source_direction"] == "reverse" and edge["source_part_index"] == 2
    assert "review/operator-assumptions.json" in edge["source_refs"]


def test_after_gap_new_camp_clock_is_conditional_and_last_day_eta_cannot_look_complete():
    points = route([100, 500, 800, 1200]); points[2]["break_before"] = True
    result = plan_terrain_schedule(points, options=assumptions(), departure_at=START, events=[
        {"kind": "camp", "point_index": 2, "departure_at": "2026-10-02T06:00:00+08:00"}])
    assert result["days"][-1]["arrival_at"] is None
    assert result["days"][-1]["conditional_arrival_at"] == "2026-10-02T07:00:00+08:00"
    assert result["finish_at"] is None and not result["complete_route_eta"]


def test_departure_and_deadline_constraints_are_retained_as_timeline_receipts():
    result = plan_terrain_schedule(route([100, 500, 900]), options=assumptions(), departure_at=START, events=[
        {"kind": "depart", "point_index": 1, "departure_at": "2026-10-01T08:00:00+08:00"},
        {"kind": "deadline", "point_index": 2, "latest_arrival_at": "2026-10-01T12:00:00+08:00"}])
    departed = next(e for e in result["timeline"] if e["kind"] == "depart")
    deadline = next(e for e in result["timeline"] if e["kind"] == "deadline")
    assert departed["departure_at"] == "2026-10-01T08:00:00+08:00"
    assert deadline["latest_arrival_at"] == "2026-10-01T12:00:00+08:00"
    assert result["finish_at"] == "2026-10-01T09:00:00+08:00"


def test_selected_day_three_and_following_camp_departure_keep_original_mission_days():
    result = plan_terrain_schedule(route([100, 500, 900]), options=assumptions(),
        departure_at="2026-10-03T06:00:00+08:00", start_day_index=3, events=[
            {"kind": "camp", "point_index": 1, "departure_at": "2026-10-04T06:00:00+08:00", "day_index": 3},
            {"kind": "depart", "point_index": 1, "departure_at": "2026-10-04T06:00:00+08:00", "day_index": 4}])
    assert [day["day_id"] for day in result["days"]] == ["D3", "D4"]
    assert [day["mission_day_id"] for day in result["days"]] == ["D3", "D4"]
    assert "event_day_constraint_mismatch" not in codes(result)
    assert result["finish_at"] == "2026-10-04T07:00:00+08:00"
