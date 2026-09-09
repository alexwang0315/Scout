"""Executable source provenance and trail topology cases for Planned GPX."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scout_planned_route_sources import (
    fetch_trail_source_candidates,
    find_trail_path,
    load_map_route_sources,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(root: Path, ref: str, payload) -> str:
    path = root / ref
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload if isinstance(payload, bytes) else json.dumps(payload).encode())
    return _sha(path)


def _way(way_id, node_ids, coordinates, **tags):
    return {"type": "way", "id": way_id, "nodes": node_ids,
            "tags": {"highway": "path", "name": f"步道 {way_id}", **tags},
            "geometry": [{"lon": x, "lat": y} for x, y in coordinates]}


def _fetched(root: Path, ways):
    raw = json.dumps({"elements": ways}).encode()
    bundle = fetch_trail_source_candidates({"south": 22, "west": 120, "north": 24, "east": 122},
                 fetcher=lambda _endpoint, query: raw,
                 requested_at="2026-09-10T00:00:00Z")
    assert not list(root.iterdir()) if root.exists() else True
    for ref, payload in bundle["files"].items():
        _write(root, ref, payload)
    return {"project_id": "planned-fixture", "planned_overpass_source_refs": [bundle["project_binding"]]}, bundle


def _sources(root: Path, ways):
    project, bundle = _fetched(root, ways)
    result = load_map_route_sources(root, project)
    return project, result, bundle


def test_overpass_search_follows_shared_nodes_and_ordered_branch_return(tmp_path):
    _, catalog, bundle = _sources(tmp_path, [
        _way(10, [1, 2, 3], [(121, 23), (121.001, 23), (121.002, 23)]),
        _way(11, [2, 4], [(121.001, 23), (121.001, 23.001)]),
    ])
    result = find_trail_path(catalog["sources"], {"lon": 121, "lat": 23}, {"lon": 121.002, "lat": 23},
                             [{"lon": 121.001, "lat": 23.001}])
    assert result["status"] == "ready"
    assert [p["osm_node_id"] for p in result["parts"][0]] == [1, 2, 4, 2, 3]
    assert [s["direction"] for s in result["selections"]] == ["forward", "forward", "reverse", "forward"]
    assert result["source_hashes"] == bundle["source_hashes"]
    assert result["candidate_only"] is True and result["operational"] is False
    assert all(p["time"] is None and p["ele"] is None for p in result["parts"][0])
    assert len(catalog["anchors"]) == 4


def test_crossing_and_coincident_vertices_with_distinct_osm_nodes_do_not_join(tmp_path):
    _, catalog, _ = _sources(tmp_path, [
        _way(10, [1, 2, 3], [(121, 23), (121.001, 23), (121.002, 23)], layer="0"),
        _way(11, [4, 5, 6], [(121.001, 22.999), (121.001, 23), (121.001, 23.001)], layer="1", bridge="yes"),
    ])
    result = find_trail_path(catalog["sources"], {"lon": 121, "lat": 23}, {"lon": 121.001, "lat": 23.001})
    assert result["status"] == "blocked"
    assert result["issues"][0]["code"] == "TRAIL_DISCONNECTED"
    ambiguous = find_trail_path(catalog["sources"], {"lon": 121.001, "lat": 23}, {"lon": 121.001, "lat": 23.001})
    assert ambiguous["issues"][0]["code"] == "TRAIL_ENDPOINT_AMBIGUOUS"
    selected = find_trail_path(catalog["sources"], {"lon": 121.001, "lat": 23, "osm_node_id": 5}, {"lon": 121.001, "lat": 23.001})
    assert selected["status"] == "ready"


def test_missing_osm_ids_preserves_geometry_and_blocks_graph_search(tmp_path):
    way = _way(10, [1, 2], [(121, 23), (121.001, 23)])
    way.pop("nodes")
    _, catalog, _ = _sources(tmp_path, [way])
    assert len(catalog["sources"]) == 1
    assert any(i["code"] == "OVERPASS_TOPOLOGY_UNAVAILABLE" for i in catalog["issues"])
    result = find_trail_path(catalog["sources"], {"lon": 121, "lat": 23}, {"lon": 121.001, "lat": 23})
    assert result["issues"][0]["code"] == "TRAIL_TOPOLOGY_UNAVAILABLE"


def test_raw_tampering_and_rebound_normalized_geometry_fail_closed(tmp_path):
    project, catalog, bundle = _sources(tmp_path, [_way(10, [1, 2], [(121, 23), (121.001, 23)])])
    assert len(catalog["sources"]) == 1
    descriptor = project["planned_overpass_source_refs"][0]
    vector_path = tmp_path / descriptor["ref"]
    vector = json.loads(vector_path.read_bytes())
    vector["features"][0]["geometry"]["coordinates"][-1][0] += 0.001
    descriptor["sha256"] = _write(tmp_path, descriptor["ref"], vector)
    assert not load_map_route_sources(tmp_path, project)["sources"]
    _write(tmp_path, descriptor["ref"], bundle["files"][descriptor["ref"]])
    descriptor["sha256"] = _sha(vector_path)
    with (tmp_path / descriptor["raw_ref"]).open("ab") as handle:
        handle.write(b" ")
    failed = load_map_route_sources(tmp_path, project)
    assert not failed["sources"]
    assert "source hash changed" in failed["issues"][0]["message"]


def test_restricted_access_and_foot_oneway_are_not_silently_reversed(tmp_path):
    _, catalog, _ = _sources(tmp_path, [
        _way(10, [1, 2], [(121, 23), (121.001, 23)], **{"oneway:foot": "yes"}),
        _way(11, [2, 3], [(121.001, 23), (121.002, 23)], access="private"),
    ])
    result = find_trail_path(catalog["sources"], {"lon": 121.001, "lat": 23}, {"lon": 121, "lat": 23})
    assert result["status"] == "blocked"


@pytest.mark.parametrize("restriction", [{"oneway:foot": "yes"}, {"access": "private"}, {"foot": "no"}])
def test_rebound_normalized_tags_cannot_remove_raw_osm_restrictions(tmp_path, restriction):
    project, _, _ = _sources(tmp_path, [
        _way(10, [1, 2], [(121, 23), (121.001, 23)], **restriction),
    ])
    descriptor = project["planned_overpass_source_refs"][0]
    vector = json.loads((tmp_path / descriptor["ref"]).read_bytes())
    vector["features"][0]["properties"]["osm_tags"] = {"highway": "path", "foot": "yes"}
    descriptor["sha256"] = _write(tmp_path, descriptor["ref"], vector)
    catalog = load_map_route_sources(tmp_path, project)
    assert len(catalog["sources"]) == 1
    assert restriction.items() <= catalog["sources"][0]["provenance"]["osm_tags"].items()
    result = find_trail_path(catalog["sources"], {"lon": 121.001, "lat": 23}, {"lon": 121, "lat": 23})
    assert result["status"] == "blocked"


def test_rudy_requires_hash_bound_map_drawing_and_human_review(tmp_path):
    image_ref = "evidence/rudy/13-6853-3534.png"
    image_sha = _write(tmp_path, image_ref, b"synthetic-image-fixture")
    ref = "candidates/rudy-trace.geojson"
    trace = {"type": "FeatureCollection", "properties": {
        "candidate_only": True, "runtime_safety_truth": False, "trace_method": "human_map_trace",
        "review_state": "human_reviewed", "reviewed_by": "fixture_human", "reviewed_at": "2026-09-10T00:00:00Z",
        "source_layer": "happyman_rudy_twmap", "source_artifacts": [{"ref": image_ref, "sha256": image_sha}]},
        "features": [{"id": "drawing-1", "type": "Feature", "properties": {"name": "圖上支線"},
            "geometry": {"type": "LineString", "coordinates": [[121, 23], [121.001, 23.001]]}}]}
    _write(tmp_path, ref, trace)
    project = {"planned_rudy_trace_refs": [ref]}
    result = load_map_route_sources(tmp_path, project)
    assert len(result["sources"]) == 1
    assert result["sources"][0]["kind"] == "rudy_trace"
    assert result["source_hashes"][image_ref] == image_sha
    (tmp_path / image_ref).write_bytes(b"changed map image")
    assert not load_map_route_sources(tmp_path, project)["sources"]


def test_source_path_cannot_escape_workspace(tmp_path):
    result = load_map_route_sources(tmp_path, {"planned_rudy_trace_refs": ["../secret.json"]})
    assert not result["sources"]
    assert any("workspace-relative" in i["message"] for i in result["issues"])


def _terrain_workspace(root: Path):
    dem_ref, manifest_ref = "terrain/dem_route_bbox.tif", "terrain/manifest.json"
    dem_sha = _write(root, dem_ref, b"test-dem-not-geospatial")
    manifest_sha = _write(root, manifest_ref, {"candidate_only": True, "runtime_safety_truth": False,
        "operational": False, "source_resolution": {"status": "reported", "x_m": 20, "y_m": 20,
        "crs": "EPSG:3826", "adds_source_resolution": False}, "artifacts": {"dem_route_bbox": "dem_route_bbox.tif"}})
    project = {"project_id": "planned-fixture", "terrain_feature_manifest_ref": manifest_ref,
               "terrain_dem_route_bbox_raster_ref": dem_ref, "terrain_route_hypothesis_candidate_only": True,
               "terrain_route_hypothesis_runtime_safety_truth": False}
    _write(root, "project.json", project)
    return project, {dem_ref: dem_sha, manifest_ref: manifest_sha}


def _hypothesis(index, parent_hashes):
    return {"id": f"test-r{index}", "alternative_index": index, "label": f"R{index} candidate",
        "strategy": "historical_narrative_guided" if index == 4 else "terrain_only_baseline",
        "start": {"x": 121, "y": 23, "crs": "EPSG:4326"},
        "destination": {"x": 121.002, "y": 23, "crs": "EPSG:4326"},
        "best_path": {"type": "LineString", "crs": "EPSG:4326", "coordinates": [[121, 23], [121.001, 23.0001], [121.002, 23]]},
        "path_semantics": "ordered_anchor_piecewise_anisotropic_model_cost_trace" if index == 4 else "minimum_anisotropic_model_cost_trace",
        "metrics": {"relative_cost": 5, "distance_m": 205, "elevation_gain_m": 4, "elevation_loss_m": 3,
                    "max_slope_degrees": 20, "median_slope_degrees": 5, "high_cost_fraction": 0.1},
        "dem_resolution_m": 20, "resolution_class": "terrain_corridor_candidate", "confidence_limits": [], "cost_model_version": "test",
        "provenance": {"dem_dataset_id": "test", "dem_sha256": parent_hashes["terrain/dem_route_bbox.tif"],
            "dem_resolution_m": 20, "dem_crs": "EPSG:3826", "dem_extent": {"xmin": 0, "xmax": 100},
            "input_endpoints": {"start": {"x": 121, "y": 23}, "destination": {"x": 121.002, "y": 23}},
            "cost_model_version": "test", "weights": {}, "weights_hash": "a" * 64, "grass_version": "test-fixture",
            "modules_executed": [], "timestamp": "2026-09-10T00:00:00Z", "algorithm_version": "test-fixture",
            "processing_manifest": {"parent_source_hashes": parent_hashes}, "cache_key": "b" * 64}}


def _attach_run(root, project, hypothesis):
    ref = "terrain/hypothesis.json"
    sha = _write(root, ref, {"status": "completed", "created_at": "2026-09-10T00:00:00Z", "hypotheses": [hypothesis]})
    project.update({"terrain_route_hypothesis_ref": ref, "terrain_route_hypothesis_sha256": sha,
                    "terrain_route_hypothesis_cache_key": "b" * 64})
    _write(root, "project.json", project)


@pytest.mark.parametrize("index", [1, 2, 3])
def test_trh_full_vertices_hashes_and_dem_staleness(tmp_path, index):
    project, hashes = _terrain_workspace(tmp_path)
    _attach_run(tmp_path, project, _hypothesis(index, hashes))
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    result = load_map_route_sources(tmp_path, project)
    assert len(result["sources"]) == 1, result["issues"]
    source = result["sources"][0]
    assert source["kind"] == f"trh_r{index}" and len(source["parts"][0]) == 3
    assert hashes.items() <= result["source_hashes"].items()
    assert source["provenance"]["timing_semantics"] == "model_cost_is_not_duration"
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    (tmp_path / "terrain/dem_route_bbox.tif").write_bytes(b"different DEM")
    assert not load_map_route_sources(tmp_path, project)["sources"]


def test_trh_geometry_cannot_claim_changed_ab(tmp_path):
    project, hashes = _terrain_workspace(tmp_path)
    hypothesis = _hypothesis(1, hashes)
    hypothesis["destination"]["x"] = 121.05
    _attach_run(tmp_path, project, hypothesis)
    result = load_map_route_sources(tmp_path, project)
    assert not result["sources"]
    assert any("endpoints" in i["message"] for i in result["issues"])


def test_r4_requires_existing_human_review_loader(tmp_path):
    project, hashes = _terrain_workspace(tmp_path)
    _attach_run(tmp_path, project, _hypothesis(4, hashes))
    result = load_map_route_sources(tmp_path, project)
    assert not result["sources"]
    assert any(i["code"] == "R4_REVIEW_UNAVAILABLE" for i in result["issues"])


@pytest.mark.parametrize("changed_source", ["narrative", "ab", "review"])
def test_r4_uses_real_narrative_manual_anchor_review_chain_and_invalidates_edits(tmp_path, changed_source):
    from terrain_route_guidance_workspace import (
        TerrainGuidanceInterpretRequest, TerrainGuidanceManualAnchorRequest,
        TerrainGuidanceResolveRequest, TerrainGuidanceReviewRequest,
        TerrainRouteGuidanceWorkspaceService, load_reviewed_guidance_execution_plan,
    )
    from terrain_route_hypothesis_models import GeoPoint
    project, hashes = _terrain_workspace(tmp_path)
    service = TerrainRouteGuidanceWorkspaceService()
    interpreted = service.interpret(tmp_path, project_id=project["project_id"],
                request=TerrainGuidanceInterpretRequest(narrative="於1148鞍沿著稜線走至其開始轉為上坡後，往西邊的坡切。", source_id="fixture_historical_narrative"))
    plan = interpreted["guidance_plan"]
    required = [item for item in plan["constraints"] if item["required_anchor"]]
    assert required
    anchors = [TerrainGuidanceManualAnchorRequest(constraint_id=item["constraint_id"],
                point=GeoPoint(x=121.0005 + index * 0.0002, y=23.0001, crs="EPSG:4326"))
                for index, item in enumerate(required)]
    resolved = service.resolve(tmp_path, project_id=project["project_id"], request=TerrainGuidanceResolveRequest(
                guidance_id=plan["guidance_id"], route_start=GeoPoint(x=121, y=23, crs="EPSG:4326"),
                route_destination=GeoPoint(x=121.002, y=23, crs="EPSG:4326"), manual_anchors=anchors))
    selections = {item["constraint_id"]: next(f["feature_id"] for f in resolved["feature_index"]["features"]
                  if f["selection_source"] == "human_map_annotation" and item["constraint_id"] in f["supported_constraint_ids"])
                  for item in required}
    disabled = [item["constraint_id"] for item in resolved["resolution"]["constraints"]
                if item["constraint_id"] not in selections and item["status"] in {"unresolved", "multiple_candidates"}]
    reviewed = service.review(tmp_path, project_id=project["project_id"], request=TerrainGuidanceReviewRequest(
                guidance_id=plan["guidance_id"], selected_feature_ids=selections,
                disabled_constraint_ids=disabled, reviewed_by="fixture_human"))
    assert reviewed["guided_execution_ready"] is True
    execution = load_reviewed_guidance_execution_plan(tmp_path, project_id=project["project_id"],
                guidance_id=plan["guidance_id"], review_sha256=reviewed["review_sha256"])
    project = json.loads((tmp_path / "project.json").read_bytes())
    hypothesis = _hypothesis(4, hashes)
    hypothesis["provenance"]["processing_manifest"]["guidance_execution"] = {
        **execution.model_dump(mode="json"), "raw_narrative_forwarded_to_worker": False}
    _attach_run(tmp_path, project, hypothesis)
    before = {str(p): _sha(p) for p in tmp_path.rglob("*") if p.is_file()}
    result = load_map_route_sources(tmp_path, project)
    assert len(result["sources"]) == 1, result["issues"]
    assert result["sources"][0]["kind"] == "trh_r4"
    assert result["sources"][0]["provenance"]["guidance_execution"]["human_reviewed"] is True
    for name in ("narrative", "plan", "feature_index", "resolution", "review", "manifest"):
        assert project[f"terrain_route_guidance_{name}_ref"] in result["source_hashes"]
    assert before == {str(p): _sha(p) for p in tmp_path.rglob("*") if p.is_file()}
    if changed_source == "narrative":
        (tmp_path / project["terrain_route_guidance_narrative_ref"]).write_text("Changed narrative")
    elif changed_source == "ab":
        service.resolve(tmp_path, project_id=project["project_id"], request=TerrainGuidanceResolveRequest(
            guidance_id=plan["guidance_id"], route_start=GeoPoint(x=121, y=23, crs="EPSG:4326"),
            route_destination=GeoPoint(x=121.003, y=23, crs="EPSG:4326"), manual_anchors=anchors))
    else:
        review_ref = project["terrain_route_guidance_review_ref"]
        review = json.loads((tmp_path / review_ref).read_bytes())
        review["reviewed_by"] = "Changed reviewer"
        _write(tmp_path, review_ref, review)
    assert not load_map_route_sources(tmp_path, project)["sources"]


def test_pbf_streaming_extractor_retains_genuine_node_refs_only():
    from pretrip_osm_pbf_ingest import _PbfRouteEvidenceHandler
    handler = _PbfRouteEvidenceHandler(bbox={"south": 22, "west": 120, "north": 24, "east": 122},
                                       osmium_module=SimpleNamespace(SimpleHandler=object))
    def location(lon):
        return SimpleNamespace(lat=23, lon=lon, valid=lambda: True)
    tags = [SimpleNamespace(k="highway", v="path")]
    way = SimpleNamespace(id=10, tags=tags, nodes=[SimpleNamespace(ref=101, location=location(121)), SimpleNamespace(ref=102, location=location(121.001))])
    handler._handle_way(way)
    assert handler.elements[0]["nodes"] == [101, 102]
    legacy = SimpleNamespace(id=11, tags=tags, nodes=[SimpleNamespace(location=location(121)), SimpleNamespace(location=location(121.001))])
    handler._handle_way(legacy)
    assert "nodes" not in handler.elements[1]
