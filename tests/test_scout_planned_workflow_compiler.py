"""Compiler vertical slices for language, terrain scheduling and zero-Golden."""
from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET

import pytest
from pydantic import ValidationError

from scout_planned_intent import parse_planned_intent
from scout_planned_route import compile_planned_route, load_planned_catalog
from scout_planned_route_models import PlannedRouteConflict, PlannedRouteRequest
from scout_planned_route_artifacts import PlannedSaveRequest, export_planned_version, save_planned_version
from test_scout_planned_route import _gpx, _write, planned_workspace

START = "2026-10-01T06:00:00+08:00"
TERRAIN = {"assumed_flat_speed_kmh": 3, "assumed_ascent_m_per_hour": 350,
           "assumed_descent_m_per_hour": 450, "uncertainty_fraction": .25,
           "source_refs": ["human:declared-planning-profile"]}


def multiday_workspace(tmp_path):
    root = tmp_path / "multi_day"
    root.mkdir()
    parts = [[(24 + ((day - 1) * 3 + i) * .001, 121, 1000 + i * 20,
               f"2020-01-{day:02d}T06:{i*10:02d}:00+08:00")
              for i in range(4)] for day in range(1, 5)]
    branch = [[(24.006, 121 + i * .001, 1000 + i * 30,
                f"2021-01-01T07:{i*5:02d}:00+08:00") for i in range(3)]]
    golden_sha = _write(root, "normalized/golden.gpx", _gpx(parts))
    branch_sha = _write(root, "normalized/branch.gpx", _gpx(branch, [("山頭 B", 24.006, 121.002)]))
    _write(root, "project.json", {"project_id": root.name})
    _write(root, "outputs/gpx_speed_filter_report.json", {
        "primary": {"output_path": "normalized/golden.gpx", "output_sha256": golden_sha},
        "references": [{"output_path": "normalized/branch.gpx", "output_sha256": branch_sha}]})
    _write(root, "candidates/checkpoints.json", [
        {"candidate_id": "cp.a", "label": "營地 A", "route_point_index": 8},
        {"candidate_id": "cp.c", "label": "觀景點 C", "route_point_index": 9},
        {"candidate_id": "cp.night", "label": "中途營地", "route_point_index": 11},
        {"candidate_id": "cp.d", "label": "營地 D", "route_point_index": 15}])
    return root


def errors(result):
    return [row for row in result["issues"] if row.get("severity") == "error"]


def test_multiday_language_compiles_selected_days_branch_and_exact_camp_departures(tmp_path):
    root = multiday_workspace(tmp_path)
    text = ("沿 Golden 第三天路線；從營地 A 單攻山頭 B 後回 A；觀景點 C 多停40分鐘；"
            "第三天在中途營地紮營；隔天早上6點出發；第四天改到營地 D；隔天早上6點出發")
    result = compile_planned_route(root, {"human_text": text, "departure_at": START, "default_speed_kmh": 2})
    assert not errors(result), errors(result)
    assert result["intent_report"]["status"] == "resolved"
    assert {row["part_index"] for row in result["effective_route_selections"]} == {2, 3}
    assert {row["source_part_index"] for row in result["route_axis"] if row["source_id"] == "golden"} == {2, 3}
    assert [row["day_id"] for row in result["itinerary"]["days"]] == ["D3", "D4"]
    assert result["itinerary"]["days"][0]["departure_at"] == "2026-10-03T06:00:00+08:00"
    assert result["itinerary"]["days"][1]["departure_at"] == "2026-10-04T06:00:00+08:00"
    assert result["itinerary"]["days"][0]["fixed_rest_minutes"] == 40
    assert len([segment for segment in result["segments"] if segment["source_kind"] == "reference_gpx"]) == 2


def test_original_multiday_ambiguous_departure_cannot_be_marked_ready(tmp_path):
    root = multiday_workspace(tmp_path)
    text = "沿 Golden 第三天路線，從營地 A 單攻山頭 B 後回 A；觀景點 C 多停40分鐘，第四天改到營地 D，早上6點出發"
    result = compile_planned_route(root, {"human_text": text, "departure_at": START, "default_speed_kmh": 2})
    assert result["status"] == "blocked"
    assert "camp_departure_day_ambiguous" in {row["code"] for row in errors(result)}
    assert len(result["intent_report"]["clauses"]) == 5


def test_explicit_manual_operation_covers_exact_unparsed_clause_without_omission(tmp_path):
    root = planned_workspace(tmp_path)
    text = "在觀景點 C 看雲四十分鐘"
    request = {"human_text": text, "departure_at": START,
               "operations": [{"kind": "stop", "at": "觀景點 C", "duration_minutes": 40, "source_text": text}]}
    result = compile_planned_route(root, request)
    assert not errors(result)
    assert result["intent_report"]["clauses"][0]["status"] == "resolved_by_explicit_operation"
    assert len(result["intent_operations"]) == 1
    changed = compile_planned_route(root, {**request, "human_text": text + "；順便多走一個山頭"})
    assert changed["status"] == "blocked"
    assert changed["intent_report"]["unresolved_clause_ids"]


def test_source_bound_model_draft_replays_without_a_model_call(tmp_path):
    root = multiday_workspace(tmp_path)
    catalog = load_planned_catalog(root)
    text = "沿 Golden 第三天路線；我們想在觀景點 C 歇脚40分鐘"
    draft = {"clauses": [
        {"clause_id": "clause.001", "actions": [{"kind": "follow_golden", "day_index": 3}]},
        {"clause_id": "clause.002", "actions": [{"kind": "stop", "at": "觀景點 C", "duration_minutes": 40}]},
    ]}
    request = {"human_text": text, "departure_at": START, "intent_draft": draft,
               "intent_input_sha256": hashlib.sha256(text.encode()).hexdigest(),
               "source_snapshot_sha256": catalog["source_snapshot_sha256"]}
    first = compile_planned_route(root, request)
    second = compile_planned_route(root, request)
    assert not errors(first), errors(first)
    assert first["preview_sha256"] == second["preview_sha256"]
    assert first["intent_report"]["mode"] == "grounded_typed_planner"
    assert first["intent_report"]["validated_draft"]
    with pytest.raises(PlannedRouteConflict, match="Human itinerary changed"):
        compile_planned_route(root, {**request, "human_text": text + "多休息"})


def test_model_draft_requires_both_text_and_catalog_bindings():
    with pytest.raises(ValidationError, match="exact input and catalog"):
        PlannedRouteRequest(human_text="出發", intent_draft={"clauses": []})


def test_terrain_team_schedule_is_exposed_in_normal_preview_shape(tmp_path):
    root = planned_workspace(tmp_path)
    result = compile_planned_route(root, {"departure_at": START, "terrain_timing": TERRAIN,
                                         "human_text": "在觀景點 C 多停40分鐘"})
    assert not errors(result), errors(result)
    assert result["itinerary"]["timing_schema_version"] == "plannedTerrainTiming.v1"
    assert result["itinerary"]["complete_route_eta"] is True
    assert result["itinerary"]["assumptions"]["pace_mode"] == "terrain_team_model"
    assert result["itinerary"]["finish_at_lower"] < result["itinerary"]["finish_at_upper"]
    assert result["itinerary"]["days"][0]["fixed_rest_minutes"] == 40
    assert result["checkpoints"][-1]["arrival_at"] == result["itinerary"]["finish_at"]
    assert result["checkpoints"][-1]["arrival_at_lower"]
    assert result["geometry_sha256"] == compile_planned_route(root, {"departure_at": START})["geometry_sha256"]


def test_terrain_selected_third_day_keeps_correct_day_label(tmp_path):
    root = multiday_workspace(tmp_path)
    result = compile_planned_route(root, {"departure_at": START, "terrain_timing": TERRAIN,
                                         "human_text": "沿 Golden 第三天路線；觀景點 C 多停40分鐘"})
    assert not errors(result), errors(result)
    assert result["itinerary"]["days"][0]["day_id"] == "D3"
    assert result["itinerary"]["days"][0]["departure_at"] == "2026-10-03T06:00:00+08:00"


def test_terrain_unknown_gap_never_becomes_full_cp_eta_after_restart(tmp_path):
    root = planned_workspace(tmp_path)
    raw = _gpx([[(24, 121, 100, None), (24.001, 121, 120, None)],
                [(24.05, 121, 150, None), (24.051, 121, 160, None)]])
    sha = _write(root, "normalized/golden.gpx", raw)
    report = json.loads((root / "outputs/gpx_speed_filter_report.json").read_text())
    report["primary"]["output_sha256"] = sha
    _write(root, "outputs/gpx_speed_filter_report.json", report)
    result = compile_planned_route(root, {"departure_at": START, "terrain_timing": TERRAIN,
                "operations": [{"kind": "depart", "at": "golden.p1.i0",
                                "departure_at": "2026-10-01T09:00:00+08:00"}]})
    assert result["itinerary"]["complete_route_eta"] is False
    assert result["itinerary"]["finish_at"] is None
    assert result["itinerary"]["days"][-1]["arrival_at"] is None
    assert result["checkpoints"][-1]["arrival_at"] is None
    assert result["checkpoints"][-1]["conditional_arrival_at"]


def _exploration(tmp_path):
    from test_scout_exploration_workspace import _create, _map_fetcher
    from scout_exploration_workspace import prepare_exploration_workspace
    root, _ = _create(tmp_path)
    prepare_exploration_workspace(root, map_fetcher=_map_fetcher())
    return root


def test_zero_golden_cannot_silently_pick_the_first_available_source(tmp_path):
    root = _exploration(tmp_path)
    result = compile_planned_route(root, {"departure_at": START, "default_speed_kmh": 2})
    assert result["status"] == "blocked"
    assert "exploration_route_selection_required" in {row["code"] for row in errors(result)}
    assert result["route_axis"] == []
    assert result["golden_geojson"] is None
    assert result["comparison"]["status"] == "unavailable"
    for name in ("golden_length_m", "golden_geometry_sha256", "golden_source_sha256", "added_distance_m", "geometry_changed"):
        assert result["comparison"][name] is None


def test_zero_golden_explicit_candidate_compiles_saves_and_exports_real_gpx(tmp_path):
    root = _exploration(tmp_path)
    catalog = load_planned_catalog(root)
    source = catalog["sources"][0]
    request = {"departure_at": START, "default_speed_kmh": 2,
               "source_snapshot_sha256": catalog["source_snapshot_sha256"],
               "route_selections": [{"source_id": source["source_id"], "part_index": 0, "start_index": 0, "end_index": 1}]}
    preview = compile_planned_route(root, request)
    assert not errors(preview), errors(preview)
    assert preview["comparison"]["golden_available"] is False
    assert preview["comparison"]["planned_length_m"] > 0
    saved = save_planned_version(root, PlannedSaveRequest(request=request,
                expected_preview_sha256=preview["preview_sha256"], idempotency_key="zero-ref-vertical",
                explicit_confirmation=True))
    raw, media, filename = export_planned_version(root, saved["version_id"], "gpx")
    assert media == "application/gpx+xml" and filename.endswith(".planned.gpx")
    tree = ET.fromstring(raw)
    points = [node for node in tree.iter() if node.tag.rsplit("}", 1)[-1] == "trkpt"]
    assert len(points) == 2
    assert "role=\"planned\"" in raw.decode()
    assert not any(node.tag.rsplit("}", 1)[-1] == "time" for node in tree.iter())
    assert json.loads((root / "project.json").read_text())["primary_gpx"] is None


def test_zero_golden_disconnected_candidates_remain_separate_and_blocked(tmp_path):
    root = _exploration(tmp_path)
    catalog = load_planned_catalog(root)
    result = compile_planned_route(root, {"departure_at": START, "default_speed_kmh": 2,
          "route_selections": [{"source_id": source["source_id"]} for source in catalog["sources"]]})
    assert result["status"] == "blocked"
    assert "disconnected_geometry" in {row["code"] for row in errors(result)}
    assert len(result["route_geojson"]["features"]) == 2
    assert result["itinerary"]["unknowns"]



def test_planned_camps_can_retime_one_recorded_golden_day_into_two_days(tmp_path):
    root = planned_workspace(tmp_path)
    text = "第一天在營地 A 紮營；隔天早上6點出發；第二天在觀景點 C 休息40分鐘"
    result = compile_planned_route(root, {"departure_at": START, "human_text": text})
    assert not errors(result), errors(result)
    assert [day["day_id"] for day in result["itinerary"]["days"]] == ["D1", "D2"]
    assert result["itinerary"]["days"][1]["departure_at"] == "2026-10-02T06:00:00+08:00"
    assert result["itinerary"]["days"][1]["fixed_rest_minutes"] == 40
    assert result["itinerary"]["days"][1]["arrival_at"].startswith("2026-10-02")
    assert result["route_axis"][-1]["source_day_index"] == 1
    assert result["route_axis"][-1]["planned_day_ids"] == ["D2"]


def test_dense_reference_replacement_resolves_nearest_unique_source_occurrences(tmp_path):
    root = planned_workspace(tmp_path)
    # Many nearby points are one passing, not distinct revisits.
    points = [(24.001 + i * .00002, 121, 120 + i, None) for i in range(51)]
    sha = _write(root, "normalized/replacement.gpx", _gpx([points]))
    report = json.loads((root / "outputs/gpx_speed_filter_report.json").read_text())
    report["references"].append({"output_path": "normalized/replacement.gpx", "output_sha256": sha})
    _write(root, "outputs/gpx_speed_filter_report.json", report)
    result = compile_planned_route(root, {"departure_at": START, "default_speed_kmh": 2,
                "human_text": "從營地 A 到觀景點 C 改走replacement.gpx"})
    assert not errors(result), errors(result)
    replacements = [segment for segment in result["segments"] if segment["source_ref"] == "normalized/replacement.gpx"]
    assert len(replacements) == 1
    assert replacements[0]["source_start_index"] == 0
    assert replacements[0]["source_end_index"] == 50


def test_explicit_operation_cannot_claim_a_false_original_source_span(tmp_path):
    root = planned_workspace(tmp_path)
    text = "在觀景點 C 看雲四十分鐘"
    result = compile_planned_route(root, {"departure_at": START, "human_text": text,
               "operations": [{"kind": "stop", "at": "觀景點 C", "duration_minutes": 40, "source_text": text,
                               "source_span": {"start": 1, "end": len(text)}}]})
    assert result["status"] == "blocked"
    assert "operation_source_span_mismatch" in {row["code"] for row in errors(result)}


def test_unperformed_precondition_is_preserved_but_candidate_save_is_allowed(tmp_path):
    root = planned_workspace(tmp_path)
    catalog = load_planned_catalog(root)
    text = "早上7點從營地 A 整裝後啟程"
    request = {"departure_at": START, "human_text": text,
        "source_snapshot_sha256": catalog["source_snapshot_sha256"],
        "intent_input_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "intent_draft": {"clauses": [{"clause_id": "clause.001", "actions": [
            {"kind": "depart", "at": "營地 A", "clock": "07:00", "preconditions": ["整裝後"]}]}]}}
    preview = compile_planned_route(root, request)
    assert preview["status"] == "needs_review" and not errors(preview)
    assert "itinerary_precondition_unverified" in {row["code"] for row in preview["issues"]}
    assert preview["intent_report"]["pending_conditions"][0]["precondition"] == "整裝後"
    saved = save_planned_version(root, PlannedSaveRequest(request=request,
                expected_preview_sha256=preview["preview_sha256"],
                idempotency_key="unperformed-precondition-is-a-plan", explicit_confirmation=True))
    raw, _, _ = export_planned_version(root, saved["version_id"], "gpx")
    assert raw and preview["departure_approval_granted"] is False
