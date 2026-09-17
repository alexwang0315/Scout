"""P4/P5: real Planned compiler consumes complete map/TRH candidates.

Only public-map response bytes and terrain inputs are fixtures.  Source loading,
OSM graph search, route composition, clocks, review checks and Save replay use
the production implementation; no compiler seam or runtime environment is used.
"""
from __future__ import annotations

import hashlib
import json

import pytest

from scout_planned_route import compile_planned_route, load_planned_catalog
from scout_planned_route_artifacts import PlannedSaveRequest, save_planned_version
from scout_planned_route_models import PlannedRouteConflict, PlannedRouteRequest
from scout_planned_route_sources import fetch_trail_source_candidates
from test_scout_planned_route import planned_workspace
from test_scout_planned_route_sources import _attach_run, _hypothesis, _terrain_workspace, _way, _write


DEPARTURE = "2026-10-01T06:00:00+08:00"


def _file_hashes(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}


def _bind_map_fixture(root, ways):
    response = json.dumps({"elements": ways}).encode()
    bundle = fetch_trail_source_candidates(
        {"south": 24, "west": 120.999, "north": 24.003, "east": 121.003},
        fetcher=lambda _endpoint, _query: response,
        requested_at="2026-09-10T00:00:00Z",
    )
    for ref, contents in bundle["files"].items():
        _write(root, ref, contents)
    project = json.loads((root / "project.json").read_bytes())
    project["planned_overpass_source_refs"] = [bundle["project_binding"]]
    _write(root, "project.json", project)
    return bundle


def _node_anchor(catalog, node_id):
    return next(anchor["anchor_id"] for anchor in catalog["anchors"]
                if anchor.get("osm_node_id") == node_id)


def _request(catalog, **changes):
    return {"departure_at": DEPARTURE, "default_speed_kmh": 2,
            "source_snapshot_sha256": catalog["source_snapshot_sha256"], **changes}


def _source_request(catalog, source, *, branch=False):
    selection = {"source_id": source["source_id"], "part_index": 0,
                 "start_index": 0, "end_index": len(source["parts"][0]) - 1}
    if branch:
        return _request(catalog, operations=[{"kind": "branch", "at": "營地 A", "to": "山頭 B",
                                               "selection": selection}])
    return _request(catalog, route_selections=[selection])


def test_p4_trail_search_branch_roundtrip_compiles_full_geometry_time_and_sources(tmp_path):
    root = planned_workspace(tmp_path)
    bundle = _bind_map_fixture(root, [
        _way(10, [1, 2, 3], [(121, 24.001), (121.001, 24.001), (121.002, 24.001)]),
        _way(11, [2, 4], [(121.001, 24.001), (121.001, 24.002)]),
    ])
    catalog = load_planned_catalog(root)
    selection = {"trail_search": {"start_anchor_id": _node_anchor(catalog, 1),
                                  "end_anchor_id": _node_anchor(catalog, 3),
                                  "via_anchor_ids": [_node_anchor(catalog, 4)]}}
    before = _file_hashes(root)
    result = compile_planned_route(root, _request(catalog, operations=[
        {"kind": "branch", "at": "營地 A", "to": "山頭 B", "selection": selection}]))
    assert result["status"] == "needs_review", result["issues"]
    assert result["comparison"]["geometry_changed"] is True
    assert result["comparison"]["added_distance_m"] > 800
    added = [segment for segment in result["segments"] if segment["source_kind"] == "overpass"]
    assert len(added) == 2
    assert [segment["provenance"]["round_trip_leg"] for segment in added] == ["outbound", "return"]
    forward = result["route_axis"][added[0]["start_point_index"]:added[0]["end_point_index"] + 1]
    assert [(point["lon"], point["lat"]) for point in forward] == [
        (121, 24.001), (121.001, 24.001), (121.001, 24.002), (121.001, 24.001), (121.002, 24.001)]
    returning = result["route_axis"][added[1]["start_point_index"]:added[1]["end_point_index"] + 1]
    assert [(point["lon"], point["lat"]) for point in returning] == list(reversed(
        [(point["lon"], point["lat"]) for point in forward]))
    assert bundle["source_hashes"].items() <= result["source_hashes"].items()
    assert added[0]["provenance"]["source_hashes"] == bundle["source_hashes"]
    assert result["itinerary"]["days"][0]["moving_minutes"] > 50
    assert not result["itinerary"]["unknowns"]
    assert result["candidate_only"] is True and result["runtime_safety_truth"] is False
    assert 'role="planned"' in result["planned_gpx"] and "<time>" not in result["planned_gpx"]
    assert before == _file_hashes(root)


def test_p4_disconnected_trails_do_not_compile_a_straight_bridge(tmp_path):
    root = planned_workspace(tmp_path)
    _bind_map_fixture(root, [
        _way(10, [1, 2], [(121, 24.001), (121.001, 24.001)], layer="0"),
        _way(11, [3, 4], [(121.001, 24.001), (121.002, 24.001)], layer="1", bridge="yes"),
    ])
    catalog = load_planned_catalog(root)
    result = compile_planned_route(root, _request(catalog, route_selections=[{"trail_search": {
        "start_anchor_id": _node_anchor(catalog, 1), "end_anchor_id": _node_anchor(catalog, 4)}}]))
    assert result["status"] == "blocked"
    assert result["route_axis"] == [] and result["route_geojson"]["features"] == []
    assert "TRAIL_DISCONNECTED" in {item["code"] for item in result["issues"]}


def test_p4_trail_search_cannot_make_a_return_leg_against_foot_oneway(tmp_path):
    root = planned_workspace(tmp_path)
    _bind_map_fixture(root, [
        _way(10, [1, 2, 3], [(121, 24.001), (121.001, 24.001), (121.002, 24.001)],
             **{"oneway:foot": "yes"}),
    ])
    catalog = load_planned_catalog(root)
    result = compile_planned_route(root, _request(catalog, operations=[{
        "kind": "branch", "at": "營地 A", "to": "山頭 B", "selection": {"trail_search": {
            "start_anchor_id": _node_anchor(catalog, 1), "end_anchor_id": _node_anchor(catalog, 3)}}}]))
    assert result["status"] == "blocked"
    assert "trail_return_path_unavailable" in {item["code"] for item in result["issues"]}
    assert not any(segment["source_kind"] == "overpass" for segment in result["segments"])


def test_p4_trail_search_uses_a_distinct_legal_return_path_and_correct_branch_target(tmp_path):
    root = planned_workspace(tmp_path)
    _bind_map_fixture(root, [
        _way(10, [1, 2, 3], [(121, 24.001), (121.001, 24.001), (121.002, 24.001)],
             **{"oneway:foot": "yes"}),
        _way(11, [3, 4, 5, 1], [(121.002, 24.001), (121.002, 24.002), (121, 24.002), (121, 24.001)],
             **{"oneway:foot": "yes"}),
    ])
    catalog = load_planned_catalog(root)
    result = compile_planned_route(root, _request(catalog, operations=[{
        "kind": "branch", "at": "營地 A", "to": "山頭 B", "selection": {"trail_search": {
            "start_anchor_id": _node_anchor(catalog, 1), "end_anchor_id": _node_anchor(catalog, 3)}}}]))
    assert result["status"] == "needs_review", result["issues"]
    added = [segment for segment in result["segments"] if segment["source_kind"] == "overpass"]
    assert len(added) == 2
    assert [segment["provenance"]["round_trip_leg"] for segment in added] == ["outbound", "return"]
    paths = [result["route_axis"][segment["start_point_index"]:segment["end_point_index"] + 1] for segment in added]
    assert [[(point["lon"], point["lat"]) for point in path] for path in paths] == [
        [(121, 24.001), (121.001, 24.001), (121.002, 24.001)],
        [(121.002, 24.001), (121.002, 24.002), (121, 24.002), (121, 24.001)],
    ]
    assert "branch_target_mismatch" not in {item["code"] for item in result["issues"]}


@pytest.mark.parametrize("tags,first,last,round_trip,issue", [
    ({"oneway:foot": "yes"}, 2, 0, False, "trail_direction_restricted"),
    ({"oneway:foot": "-1"}, 0, 2, False, "trail_direction_restricted"),
    ({"oneway:foot": "yes"}, 0, 2, True, "trail_direction_restricted"),
    ({"access": "private"}, 0, 2, False, "trail_access_restricted"),
    ({"foot": "no"}, 2, 0, False, "trail_access_restricted"),
])
def test_p4_explicit_overpass_slice_cannot_bypass_foot_access_or_direction(tmp_path, tags, first, last, round_trip, issue):
    root = planned_workspace(tmp_path)
    _bind_map_fixture(root, [
        _way(10, [1, 2, 3], [(121, 24.001), (121.001, 24.001), (121.002, 24.001)], **tags),
    ])
    catalog = load_planned_catalog(root)
    source = next(source for source in catalog["sources"] if source["kind"] == "overpass")
    result = compile_planned_route(root, _request(catalog, route_selections=[{
        "source_id": source["source_id"], "start_index": first, "end_index": last, "round_trip": round_trip}]))
    assert result["status"] == "blocked"
    assert issue in {item["code"] for item in result["issues"]}
    assert result["route_axis"] == []


def test_p4_bound_rudy_trace_compiles_candidate_geometry_without_claiming_recorded_time(tmp_path):
    root = planned_workspace(tmp_path)
    image_ref = "evidence/rudy/tile.png"
    image_sha = _write(root, image_ref, b"synthetic-rudy-image-fixture")
    trace_ref = "candidates/rudy_trace.geojson"
    _write(root, trace_ref, {"type": "FeatureCollection", "properties": {
        "trace_method": "human_map_trace", "review_state": "human_reviewed", "reviewed_by": "fixture_human",
        "reviewed_at": "2026-09-10T00:00:00Z", "source_layer": "happyman_rudy_twmap",
        "candidate_only": True, "runtime_safety_truth": False,
        "source_artifacts": [{"ref": image_ref, "sha256": image_sha}]}, "features": [{
            "id": "trace-1", "type": "Feature", "properties": {"name": "Rudy fixture branch"},
            "geometry": {"type": "LineString", "coordinates": [[121, 24.001], [121.001, 24.0015], [121.002, 24.001]]}}]})
    project = json.loads((root / "project.json").read_bytes())
    project["planned_rudy_trace_refs"] = [trace_ref]
    _write(root, "project.json", project)
    catalog = load_planned_catalog(root)
    source = next(source for source in catalog["sources"] if source["kind"] == "rudy_trace")
    result = compile_planned_route(root, _source_request(catalog, source, branch=True))
    assert result["status"] == "needs_review", result["issues"]
    assert result["source_hashes"][image_ref] == image_sha
    assert [segment["source_kind"] for segment in result["segments"]].count("rudy_trace") == 2
    assert all(row["method"] == "explicit_fixed_speed_assumption" for row in result["itinerary"]["timeline"]
               if row["kind"] == "move" and row.get("duration_minutes", 0) and row["point_index"] in {3, 4, 6, 7})


def _terrain_project(tmp_path, index):
    root = planned_workspace(tmp_path)
    project, hashes = _terrain_workspace(root)
    project["project_id"] = root.name
    _write(root, "project.json", project)
    hypothesis = _hypothesis(index, hashes)
    hypothesis["start"]["y"] = 24.001
    hypothesis["destination"]["y"] = 24.001
    hypothesis["best_path"]["coordinates"] = [[121, 24.001], [121.001, 24.0015], [121.002, 24.001]]
    hypothesis["provenance"]["input_endpoints"] = {
        "start": hypothesis["start"], "destination": hypothesis["destination"]}
    if index == 4:
        project, execution = _review_r4(root, project, hypothesis)
        hypothesis["provenance"]["processing_manifest"]["guidance_execution"] = {
            **execution.model_dump(mode="json"), "raw_narrative_forwarded_to_worker": False}
    _attach_run(root, project, hypothesis)
    return root, project, hypothesis


def _review_r4(root, project, hypothesis):
    from terrain_route_guidance_workspace import (
        TerrainGuidanceInterpretRequest, TerrainGuidanceManualAnchorRequest,
        TerrainGuidanceResolveRequest, TerrainGuidanceReviewRequest,
        TerrainRouteGuidanceWorkspaceService, load_reviewed_guidance_execution_plan,
    )
    from terrain_route_hypothesis_models import GeoPoint
    service = TerrainRouteGuidanceWorkspaceService()
    plan = service.interpret(root, project_id=root.name, request=TerrainGuidanceInterpretRequest(
        narrative="於1148鞍沿著稜線走至其開始轉為上坡後，往西邊的坡切。", source_id="fixture_historical_record"))["guidance_plan"]
    required = [constraint for constraint in plan["constraints"] if constraint["required_anchor"]]
    resolved = service.resolve(root, project_id=root.name, request=TerrainGuidanceResolveRequest(
        guidance_id=plan["guidance_id"], route_start=GeoPoint(**hypothesis["start"]),
        route_destination=GeoPoint(**hypothesis["destination"]), manual_anchors=[
            TerrainGuidanceManualAnchorRequest(constraint_id=constraint["constraint_id"],
                point=GeoPoint(x=121.001, y=24.0015, crs="EPSG:4326")) for constraint in required]))
    selected = {constraint["constraint_id"]: next(feature["feature_id"] for feature in resolved["feature_index"]["features"]
                if feature["selection_source"] == "human_map_annotation" and constraint["constraint_id"] in feature["supported_constraint_ids"])
                for constraint in required}
    disabled = [constraint["constraint_id"] for constraint in resolved["resolution"]["constraints"]
                if constraint["constraint_id"] not in selected and constraint["status"] in {"unresolved", "multiple_candidates"}]
    review = service.review(root, project_id=root.name, request=TerrainGuidanceReviewRequest(
        guidance_id=plan["guidance_id"], selected_feature_ids=selected,
        disabled_constraint_ids=disabled, reviewed_by="fixture_human"))
    assert review["guided_execution_ready"] is True
    execution = load_reviewed_guidance_execution_plan(root, project_id=root.name,
                 guidance_id=plan["guidance_id"], review_sha256=review["review_sha256"])
    return json.loads((root / "project.json").read_bytes()), execution


@pytest.mark.parametrize("index", [1, 2, 3, 4])
def test_p5_trh_candidate_runs_through_real_compiler_and_preserves_bindings(tmp_path, index):
    root, project, hypothesis = _terrain_project(tmp_path, index)
    catalog = load_planned_catalog(root)
    source = next(source for source in catalog["sources"] if source["kind"] == f"trh_r{index}")
    before = _file_hashes(root)
    result = compile_planned_route(root, _source_request(catalog, source, branch=True))
    assert result["status"] == "needs_review", result["issues"]
    added = [segment for segment in result["segments"] if segment["source_kind"] == f"trh_r{index}"]
    assert len(added) == 2 and added[0]["direction"] == "forward" and added[1]["direction"] == "reverse"
    actual = result["route_axis"][added[0]["start_point_index"]:added[0]["end_point_index"] + 1]
    assert [[point["lon"], point["lat"]] for point in actual] == hypothesis["best_path"]["coordinates"]
    assert result["source_hashes"][project["terrain_dem_route_bbox_raster_ref"]] == source["provenance"]["dem_sha256"]
    assert result["source_hashes"][project["terrain_feature_manifest_ref"]] == source["provenance"]["parent_manifest_sha256"]
    assert result["itinerary"]["unknowns"] == [] and result["itinerary"]["days"][0]["moving_minutes"] > 40
    assert added[0]["provenance"]["timing_semantics"] == "model_cost_is_not_duration"
    assert all(segment["candidate_only"] is True and segment["runtime_safety_truth"] is False for segment in added)
    if index == 4:
        execution = added[0]["provenance"]["guidance_execution"]
        assert execution["guidance_review_sha256"] == project["terrain_route_guidance_review_sha256"]
        assert execution["anchors"][0]["selection_source"] == "human_map_annotation"
        for name in ("narrative", "plan", "feature_index", "resolution", "review", "manifest"):
            assert project[f"terrain_route_guidance_{name}_ref"] in result["source_hashes"]
    assert before == _file_hashes(root)


@pytest.mark.parametrize("index,change", [(1, "ab"), (1, "dem"), (4, "ab"), (4, "dem"), (4, "narrative"), (4, "review")])
def test_p5_changed_trh_sources_reject_old_request_and_saved_preview(tmp_path, index, change):
    root, project, hypothesis = _terrain_project(tmp_path, index)
    catalog = load_planned_catalog(root)
    source = next(source for source in catalog["sources"] if source["kind"] == f"trh_r{index}")
    request = _source_request(catalog, source)
    preview = compile_planned_route(root, request)
    assert preview["status"] == "needs_review"
    if change == "ab":
        hypothesis["destination"]["x"] = 121.003
        hypothesis["best_path"]["coordinates"][-1][0] = 121.003
        hypothesis["provenance"]["input_endpoints"]["destination"] = hypothesis["destination"]
        _attach_run(root, project, hypothesis)
    elif change == "dem":
        (root / project["terrain_dem_route_bbox_raster_ref"]).write_bytes(b"new DEM fixture")
    elif change == "narrative":
        (root / project["terrain_route_guidance_narrative_ref"]).write_text("Changed historical narrative")
    else:
        (root / project["terrain_route_guidance_review_ref"]).write_text("{}")
    with pytest.raises(PlannedRouteConflict, match="Sources changed"):
        compile_planned_route(root, request)
    with pytest.raises(PlannedRouteConflict):
        save_planned_version(root, PlannedSaveRequest(request=PlannedRouteRequest.model_validate(request),
            expected_preview_sha256=preview["preview_sha256"], idempotency_key=f"stale.{index}.{change}", explicit_confirmation=True))
    assert not list((root / "reviews/planned_routes/versions").glob("*/manifest.json"))
