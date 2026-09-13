"""W4: source-grounded multi-day language, uncertainty and provider boundary."""
from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

from scout_planned_intent import (
    bind_intent_to_route, build_intent_planning_prompt, golden_day_windows,
    parse_configured_planned_intent, parse_planned_intent,
)

START = "2026-10-01T06:00:00+08:00"
EXAMPLE = "沿 Golden 第三天路線，從營地 A 單攻山頭 B 後回 A；觀景點 C 多停 40 分鐘，第四天改到營地 D，早上 6 點出發"


@pytest.fixture
def catalog():
    sources = [
        {"source_id": "golden", "kind": "golden", "label": "Golden",
         "parts": [[{"lat": 24 + (d * 5 + i) / 1000, "lon": 121, "ele": 2000,
                     "time": f"2020-01-{d:02d}T06:{i*10:02d}:00+08:00"}
                    for i in range(5)] for d in range(1, 5)]},
        {"source_id": "ref.branch", "kind": "reference_gpx", "label": "支線 X",
         "parts": [[{"lat": 24.015, "lon": 121 + i / 1000} for i in range(3)]]},
    ]
    anchors = [
        {"anchor_id": "golden.p2.i0", "label": "營地 A", "source_id": "golden", "part_index": 2, "point_index": 0},
        {"anchor_id": "ref.branch.p0.i2", "label": "山頭 B", "source_id": "ref.branch", "part_index": 0, "point_index": 2},
        {"anchor_id": "golden.p2.i3", "label": "觀景點 C", "source_id": "golden", "part_index": 2, "point_index": 3},
        {"anchor_id": "golden.p3.i4", "label": "營地 D", "source_id": "golden", "part_index": 3, "point_index": 4},
    ]
    return {"schema_version": "plannedRouteCatalog.v1", "project_id": "intent-fixture",
            "golden_source_id": "golden", "sources": sources, "anchors": anchors,
            "source_snapshot_sha256": "a" * 64, "candidate_only": True, "runtime_safety_truth": False}


def parse(text, catalog, **kwargs):
    return parse_planned_intent(text, catalog, departure_at=START, **kwargs)


def codes(result):
    return {issue["code"] for issue in result["issues"]}


def test_realistic_multiday_example_accounts_for_every_clause_and_asks_actual_ambiguity(catalog):
    result = parse(EXAMPLE, catalog)
    assert result["status"] == "needs_clarification"
    assert result["mode"] == "deterministic_supported_grammar"
    assert [(op["kind"], op["day_index"]) for op in result["operations"]] == [("branch", 3), ("stop", 3), ("camp", 4)]
    assert result["operations"][0]["at"] == "golden.p2.i0"
    assert result["operations"][0]["to"] == "ref.branch.p0.i2"
    assert result["operations"][0]["round_trip"] is True
    assert result["operations"][1]["duration_minutes"] == 40
    assert codes(result) == {"camp_departure_day_ambiguous"}
    question = result["issues"][0]
    assert [choice["day_index"] for choice in question["choices"]] == [4, 5]
    assert result["route_intents"][0]["selections"] == [
        {"source_id": "golden", "part_index": 2, "start_index": 0, "end_index": 4}]
    assert len(result["clauses"]) == 5
    for clause in result["clauses"]:
        span = clause["source_span"]
        assert EXAMPLE[span["start"]:span["end"]] == clause["source_text"]
    assert result["unresolved_clause_ids"] == ["clause.005"]


def test_camp_next_day_departure_has_distinct_location_and_calendar_day(catalog):
    result = parse("第三天在營地 A 紮營，隔天早上6點出發", catalog)
    assert result["status"] == "resolved", result["issues"]
    camp, depart = result["operations"]
    assert camp["day_index"] == 3
    assert camp["departure_at"] == "2026-10-04T06:00:00+08:00"
    assert depart["day_index"] == 4
    assert depart["location_day_index"] == 3
    assert depart["at"] == camp["at"] == "golden.p2.i0"


@pytest.mark.parametrize("relative,day", [("次日", 4), ("翌日", 4), ("兩天後", 5), ("後天", 5)])
def test_relative_days_are_relative_to_last_stated_day(catalog, relative, day):
    result = parse(f"第三天在營地 A 紮營；{relative}06:15出發", catalog)
    assert result["status"] == "resolved", result["issues"]
    assert result["operations"][1]["day_index"] == day
    assert result["operations"][1]["departure_at"] == f"2026-10-{day:02d}T06:15:00+08:00"


@pytest.mark.parametrize("text", ["2026-10-03早上6點出發", "10月3日早上6點出發", "第三天早上6點出發"])
def test_absolute_date_numbered_day_and_month_day_share_trip_calendar(catalog, text):
    result = parse(text, catalog)
    assert result["status"] == "resolved", result["issues"]
    assert result["operations"][0]["departure_at"] == "2026-10-03T06:00:00+08:00"


def test_invalid_and_conflicting_calendar_dates_are_not_normalized(catalog):
    invalid = parse("2026-02-30早上6點出發", catalog)
    conflict = parse("第三天2026-10-04早上6點出發", catalog)
    assert "invalid_calendar_date" in codes(invalid)
    assert "itinerary_day_date_conflict" in codes(conflict)
    assert not conflict["operations"]


def test_date_timezone_are_required_for_clocks_not_taken_from_historical_gpx(catalog):
    result = parse_planned_intent("第三天早上6點出發", catalog)
    assert "intent_calendar_and_timezone_required" in codes(result)
    assert not result["operations"]
    result = parse_planned_intent("早上6點出發", catalog, departure_at="2026-10-01T06:00")
    assert "departure_timezone_required" in codes(result)


def test_cross_midnight_requires_explicit_next_day_and_keeps_offset(catalog):
    result = parse("第三天晚上11點30分出發；次日凌晨1點前抵達營地 D", catalog)
    assert result["status"] == "resolved", result["issues"]
    assert result["operations"][0]["departure_at"] == "2026-10-03T23:30:00+08:00"
    assert result["operations"][1]["latest_arrival_at"] == "2026-10-04T01:00:00+08:00"
    assert result["operations"][1]["day_index"] == 4


def test_implicit_clock_wrap_is_not_silently_next_day(catalog):
    result = parse("第三天晚上11點出發；凌晨1點前抵達營地 A", catalog)
    assert "explicit_clock_order_conflict" in codes(result)
    assert len(result["operations"]) == 1


@pytest.mark.parametrize("clock", ["25:00", "06:70", "24點"])
def test_invalid_clock_is_explicit(catalog, clock):
    result = parse(f"第三天{clock}出發", catalog)
    assert "invalid_clock" in codes(result)
    assert not result["operations"]


def test_exact_arrival_and_deadline_are_distinct(catalog):
    exact = parse("第三天下午3點抵達營地 A", catalog)
    latest = parse("第三天最晚下午3點前抵達營地 A", catalog)
    assert exact["operations"][0]["kind"] == "arrival"
    assert exact["operations"][0]["arrival_at"] == "2026-10-03T15:00:00+08:00"
    assert latest["operations"][0]["kind"] == "deadline"
    assert latest["operations"][0]["latest_arrival_at"] == "2026-10-03T15:00:00+08:00"


def test_duration_combines_hours_minutes_and_preserves_additional_stop(catalog):
    result = parse("第三天在觀景點 C 多停一小時三十分鐘", catalog)
    assert result["status"] == "resolved", result["issues"]
    assert result["operations"][0]["duration_minutes"] == 90


def test_unknown_clause_and_unknown_place_remain_visible(catalog):
    result = parse("第三天營地 A 休息20分鐘；如果天氣不好就臨時換路；不明營地休息10分鐘", catalog)
    assert len(result["clauses"]) == 3
    assert "unsupported_itinerary_clause" in codes(result)
    assert "unlocated_place" in codes(result)
    assert len(result["unresolved_clause_ids"]) == 2


def test_same_name_same_day_requires_disambiguation(catalog):
    catalog["anchors"].append({**catalog["anchors"][0], "anchor_id": "golden.p2.i1", "point_index": 1})
    result = parse("第三天在營地 A 休息10分鐘", catalog)
    assert "ambiguous_place" in codes(result)
    assert len(result["issues"][0]["choices"]) == 2
    chosen = parse("第三天在營地 A 休息10分鐘", catalog, name_resolutions={"營地 A": "golden.p2.i1"})
    assert chosen["status"] == "resolved"
    assert chosen["operations"][0]["at"] == "golden.p2.i1"


def test_day_filters_duplicate_name_without_silently_selecting_a_different_day(catalog):
    catalog["anchors"].append({**catalog["anchors"][0], "anchor_id": "golden.p3.i0", "part_index": 3})
    result = parse("第四天在營地 A 休息10分鐘", catalog)
    assert result["status"] == "resolved"
    assert result["operations"][0]["at"] == "golden.p3.i0"


def test_branch_short_name_resolves_but_different_return_is_rejected(catalog):
    result = parse("第三天從營地 A 單攻山頭 B 後回營地 D", catalog)
    assert "branch_return_mismatch" in codes(result)
    assert not result["operations"]


def test_replacement_source_is_grounded_and_geometry_is_still_required(catalog):
    result = parse("第三天從營地 A 到觀景點 C 改走支線 X", catalog)
    assert result["status"] == "resolved", result["issues"]
    assert result["operations"][0]["kind"] == "replace"
    route = result["route_intents"][0]
    assert route["source_id"] == "ref.branch"
    assert route["requires_geometry_resolution"] is True
    assert "coordinates" not in route


def test_route_replacement_via_point_does_not_create_geometry(catalog):
    result = parse("第三天從營地 A 到觀景點 C 改走經山頭 B", catalog)
    assert result["status"] == "resolved", result["issues"]
    assert result["route_intents"][0]["via_anchor_ids"] == ["ref.branch.p0.i2"]


def test_missing_golden_day_does_not_fall_back_to_entire_route(catalog):
    result = parse("沿 Golden 第五天路線", catalog)
    assert "golden_day_geometry_missing" in codes(result)
    assert not result["route_intents"]


def test_whole_golden_without_timestamps_still_has_explicit_source_selection(catalog):
    for part in catalog["sources"][0]["parts"]:
        for point in part:
            point.pop("time")
    result = parse("沿 Golden", catalog)
    assert result["status"] == "resolved"
    assert len(result["route_intents"][0]["selections"]) == 4
    assert golden_day_windows(catalog) == []


def test_revisited_exact_point_requires_visit_selection(catalog):
    result = parse("第三天在營地 A 休息10分鐘", catalog)
    nodes = [
        {"source_id": "golden", "part_index": 2, "source_point_index": 0},
        {"source_id": "golden", "part_index": 2, "source_point_index": 1},
        {"source_id": "golden", "part_index": 2, "source_point_index": 0},
    ]
    bound = bind_intent_to_route(result, nodes, catalog)
    assert "intent_route_visit_ambiguous" in codes(bound)
    selected = parse("第三天第2次到營地 A 休息10分鐘", catalog)
    bound = bind_intent_to_route(selected, nodes, catalog)
    assert bound["status"] == "resolved", bound["issues"]
    assert bound["operations"][0]["point_index"] == 2


def test_location_binding_does_not_invent_cross_source_correspondence(catalog):
    result = parse("第三天在營地 A 休息10分鐘", catalog)
    nodes = [{"source_id": "another", "part_index": 2, "source_point_index": 0}]
    bound = bind_intent_to_route(result, nodes, catalog)
    assert "intent_anchor_missing_in_day" in codes(bound)


class Runner:
    def __init__(self, payload):
        self.payload = payload
        self.prompts = []

    def run(self, prompt, *, timeout_seconds=None):
        self.prompts.append(json.loads(prompt))
        return json.dumps(self.payload, ensure_ascii=False)


def draft(*clauses):
    return {"schema_version": "plannedItineraryIntentDraft.v1", "clauses": list(clauses)}


def test_broader_language_uses_grounded_typed_planner_not_expanded_regex_claim(catalog):
    text = "第三天我們希望在觀景點 C 歇腳四十分鐘"
    fallback = parse(text, catalog)
    assert fallback["mode"] == "deterministic_supported_grammar"
    assert fallback["status"] == "needs_clarification"
    runner = Runner(draft({"clause_id": "clause.001", "actions": [
        {"kind": "stop", "at": "觀景點 C", "day_index": 3, "duration_minutes": 40}]}))
    result = parse(text, catalog, planner=runner)
    assert result["status"] == "resolved", result["issues"]
    assert result["mode"] == "grounded_typed_planner"
    assert result["operations"][0]["at"] == "golden.p2.i3"
    assert result["planner_response_sha256"]
    assert "coordinates" not in json.dumps(runner.prompts[0]["anchors"])
    assert "lat" not in runner.prompts[0]["anchors"][0]


@pytest.mark.parametrize("change,expected", [
    ({"at": "營地 D"}, "planner_place_not_in_source_clause"),
    ({"duration_minutes": 4}, "planner_duration_not_supported_by_clause"),
    ({"day_index": 4}, "planner_day_not_supported_by_clause"),
    ({"visit": 2}, "planner_visit_not_supported_by_clause"),
])
def test_model_invented_facts_are_rejected(catalog, change, expected):
    action = {"kind": "stop", "at": "觀景點 C", "day_index": 3, "duration_minutes": 40, **change}
    result = parse("第三天我們希望在觀景點 C 歇腳四十分鐘", catalog,
                   planner=Runner(draft({"clause_id": "clause.001", "actions": [action]})))
    assert expected in codes(result) or "planner_constraint_coverage_missing" in codes(result)
    assert not result["operations"]


@pytest.mark.parametrize("payload", [
    draft(),
    draft({"clause_id": "clause.099", "actions": []}),
    draft({"clause_id": "clause.001", "actions": [{"kind": "stop", "at": "營地 A", "duration_minutes": 10, "coordinates": [121, 24]}]}),
])
def test_model_cannot_omit_clauses_or_add_geometry(catalog, payload):
    result = parse("第三天營地 A 休息10分鐘", catalog, planner=Runner(payload))
    assert "planner_failed" in codes(result)
    assert not result["operations"]


def test_model_cannot_hide_unknown_clause_as_day_context(catalog):
    result = parse("第三天如果天氣不好就換路", catalog, planner=Runner(draft(
        {"clause_id": "clause.001", "actions": [{"kind": "set_day", "day_index": 3}]})))
    assert "planner_context_hides_unresolved_text" in codes(result)


def test_provider_failure_never_serializes_exception_secret(catalog):
    class Failed:
        def run(self, prompt, *, timeout_seconds=None):
            raise RuntimeError("private-token-value-must-not-appear")
    result = parse("第三天在營地 A 休息10分鐘", catalog, planner=Failed())
    assert result["status"] == "needs_clarification"
    assert result["provider_error"] == "RuntimeError"
    assert "private-token-value" not in json.dumps(result)


def test_configured_entrypoint_uses_existing_runner_only_when_authorized(catalog, monkeypatch):
    import scout_agent_runtime
    runner = Runner(draft({"clause_id": "clause.001", "actions": [
        {"kind": "stop", "at": "觀景點 C", "day_index": 3, "duration_minutes": 40}]}))
    calls = []
    def factory(config, *, environ=None):
        calls.append(config)
        return runner
    monkeypatch.setattr(scout_agent_runtime, "create_configured_scout_agent_planner_runner", factory)
    config = SimpleNamespace(active_profile="cloud", cloud_model=SimpleNamespace(model_name="configured-capable-model"))
    text = "第三天我們希望在觀景點 C 歇腳四十分鐘"
    denied = parse_configured_planned_intent(text, catalog, planner_config=config, departure_at=START)
    assert denied["configured_planner_status"] == "not_authorized"
    assert calls == []
    approved = parse_configured_planned_intent(text, catalog, planner_config=config,
                                                model_calls_authorized=True, departure_at=START)
    assert len(calls) == 1
    assert approved["status"] == "resolved"
    assert approved["configured_model"] == "configured-capable-model"
    assert approved["candidate_only"] is True and approved["runtime_safety_truth"] is False


def test_input_and_catalog_are_unchanged_by_all_entrypoints(catalog):
    before = copy.deepcopy(catalog)
    first = parse(EXAMPLE, catalog)
    second = parse(EXAMPLE, catalog)
    assert first == second
    assert catalog == before
    prompt = json.loads(build_intent_planning_prompt(EXAMPLE, catalog, departure_at=START))
    assert prompt["runtime_safety_truth"] is False
    assert all("lat" not in anchor and "lon" not in anchor for anchor in prompt["anchors"])


def test_partly_missing_source_times_never_silently_drop_points_for_golden_day(catalog):
    catalog["sources"][0]["parts"][2][2].pop("time")
    result = parse("沿 Golden 第三天路線", catalog)
    assert "golden_day_geometry_missing" in codes(result)
    assert result["route_intents"] == []
    whole = parse("沿 Golden", catalog)
    assert whole["status"] == "resolved"
    assert whole["route_intents"][0]["selections"][2]["end_index"] == 4


def test_absolute_day_then_relative_day_retains_calendar_without_assumed_timezone(catalog):
    result = parse_planned_intent("2026-10-03在營地 A 紮營；隔天在營地 D 紮營", catalog)
    assert [op["calendar_date"] for op in result["operations"]] == ["2026-10-03", "2026-10-04"]
    assert result["trip_start_at"] is None

def test_actual_gpx_catalog_grounding_and_full_original_sentence_provenance(tmp_path):
    import hashlib
    import xml.etree.ElementTree as ET
    from scout_planned_route import load_planned_catalog

    root = tmp_path / "intent_real_catalog"
    def write(ref, value):
        path = root / ref
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value if isinstance(value, str) else json.dumps(value))
        return hashlib.sha256(path.read_bytes()).hexdigest()
    def gpx(parts, waypoint=None):
        tree = ET.Element("gpx", version="1.1")
        if waypoint:
            label, lat, lon = waypoint
            node = ET.SubElement(tree, "wpt", lat=str(lat), lon=str(lon))
            ET.SubElement(node, "name").text = label
        track = ET.SubElement(tree, "trk")
        for points in parts:
            part = ET.SubElement(track, "trkseg")
            for lat, lon, stamp in points:
                point = ET.SubElement(part, "trkpt", lat=str(lat), lon=str(lon))
                ET.SubElement(point, "time").text = stamp
        return ET.tostring(tree, encoding="unicode")
    parts = [[(24 + (day * 5 + i) / 1000, 121,
               f"2020-01-{day:02d}T06:{i*10:02d}:00+08:00")
              for i in range(5)] for day in range(1, 5)]
    golden_sha = write("normalized/golden.gpx", gpx(parts))
    branch = [[(24.015, 121 + i / 1000, f"2021-01-01T06:{i*10:02d}:00+08:00") for i in range(3)]]
    branch_sha = write("normalized/branch.gpx", gpx(branch, ("山頭 B", 24.015, 121.002)))
    write("project.json", {"project_id": root.name})
    write("outputs/gpx_speed_filter_report.json", {
        "primary": {"output_path": "normalized/golden.gpx", "output_sha256": golden_sha},
        "references": [{"output_path": "normalized/branch.gpx", "output_sha256": branch_sha}]})
    write("candidates/checkpoints.json", [
        {"candidate_id": "cp.a", "label": "營地 A", "route_point_index": 10},
        {"candidate_id": "cp.c", "label": "觀景點 C", "route_point_index": 13},
        {"candidate_id": "cp.d", "label": "營地 D", "route_point_index": 19}])
    catalog = load_planned_catalog(root)
    original = parse(EXAMPLE, catalog)
    assert codes(original) == {"camp_departure_day_ambiguous"}
    assert len(original["operations"]) == 3
    assert original["source_snapshot_sha256"] == catalog["source_snapshot_sha256"]
    clarified = parse("第三天在營地 A 紮營；隔天早上6點出發", catalog)
    assert clarified["status"] == "resolved"
    source = clarified["derived_constraints"][0]
    assert source["source_text"] == "隔天早上6點出發"
    assert source["source_clause_id"] == "clause.002"
    assert clarified["operations"][source["operation_index"]][source["field"]] == source["value"]

def test_explicit_camp_name_in_relative_departure_binds_prior_camp_departure(catalog):
    result = parse("第三天在營地 A 紮營；隔天從營地 A 早上6點出發", catalog)
    assert result["status"] == "resolved", result["issues"]
    assert result["operations"][0]["departure_at"] == "2026-10-04T06:00:00+08:00"
    assert result["operations"][1]["location_day_index"] == 3


def test_model_context_can_ground_a_following_pronoun_but_cannot_drop_duration(catalog):
    text = "第三天我們先到觀景點 C；這一站想多留四十分鐘"
    runner = Runner(draft(
        {"clause_id": "clause.001", "actions": [{"kind": "set_location", "day_index": 3, "at": "觀景點 C"}]},
        {"clause_id": "clause.002", "actions": [{"kind": "stop", "at": "這一站", "duration_minutes": 40}]}))
    result = parse(text, catalog, planner=runner)
    assert result["status"] == "resolved", result["issues"]
    assert result["operations"][0]["at"] == "golden.p2.i3"
    assert result["clauses"][0]["status"] == "resolved_context"
    omitted = Runner(draft({"clause_id": "clause.001", "actions": [{"kind": "set_location", "day_index": 3, "at": "觀景點 C"}]}))
    result = parse("第三天在觀景點 C 休息四十分鐘", catalog, planner=omitted)
    assert "planner_constraint_coverage_missing" in codes(result)

def test_provider_sees_existing_place_choice_and_preserves_unverified_precondition(catalog):
    text = "第三天早上6點從營地 A 整裝後啟程"
    selected = {"營地 A": "golden.p2.i0"}
    runner = Runner(draft({"clause_id": "clause.001", "actions": [
        {"kind": "depart", "day_index": 3, "at": "營地 A", "clock": "06:00", "preconditions": ["整裝後"]}]}))
    result = parse(text, catalog, planner=runner, name_resolutions=selected)
    assert result["status"] == "resolved", result["issues"]
    assert runner.prompts[0]["name_resolutions"] == selected
    assert result["operations"][0]["preconditions"] == ["整裝後"]
    assert result["pending_conditions"][0]["status"] == "awaiting_human_confirmation"
    assert not result["runtime_safety_truth"]
