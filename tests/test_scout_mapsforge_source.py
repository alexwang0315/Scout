"""Source integrity and no fabricated topology, plus actual HTTP composition."""
import copy
import hashlib
import json

import pytest

from scout_planned_map_materialization import materialize_map_sources, inspect_map_materialization
from scout_planned_route_sources import load_map_route_sources, find_trail_path
from scout_planned_route import compile_planned_route, load_planned_catalog
from test_scout_planned_map_api import _client


def setup_source(root, monkeypatch):
    from scout_exploration_workspace import create_exploration_workspace
    create_exploration_workspace(root.parent, {"project_id": root.name, "intent": "Fixture map selection",
        "aoi": {"crs": "EPSG:4326", "bbox": [121, 23, 121.01, 23.01]}})
    raw = b"mapsforge binary OSM" + b"fixture-reader-test"
    (root / "source.map").write_bytes(raw)
    project = json.loads((root / "project.json").read_bytes())
    project["rudy_mapsforge_ref"] = "source.map"
    (root / "project.json").write_text(json.dumps(project))
    box = {"south": 23.0, "west": 121.0, "north": 23.01, "east": 121.01}
    payload = {"type": "FeatureCollection", "properties": {"extractor": "mapsforge-map-reader", "reader_version": "0.25.0",
        "source_file_size": len(raw), "projection": "Mercator", "topology_available": False, "query_bbox_wgs84": box},
        "features": [{"type": "Feature", "properties": {"tags": {"highway": "path", "name": "Fixture trail"}, "layer": 1,
        "topology_available": False}, "geometry": {"type": "MultiLineString", "coordinates": [
            [[121, 23], [121.001, 23.001]], [[121.005, 23.005], [121.006, 23.006]]]}}]}
    monkeypatch.setattr("scout_mapsforge_source.extract_mapsforge", lambda *args: (copy.deepcopy(payload), {"test_reader": "a" * 64}))
    request = {"source_kind": "mapsforge_vector", "source_ref": "source.map", "expected_source_sha256": hashlib.sha256(raw).hexdigest(),
               "bbox_wgs84": box, "requested_by": "fixture", "requested_at": "2026-09-10T00:00:00Z"}
    return project, request, payload


def test_mapsforge_http_to_real_compiler_preserves_parts_and_cannot_graph_route(tmp_path, monkeypatch):
    tmp_path = tmp_path / "mapsforge-test"
    project, request, _ = setup_source(tmp_path, monkeypatch)
    client = _client(tmp_path);base = "/admin/pretrip/projects/mapsforge-test/planned-map"
    assert client.get(base+"/catalog").json()["mapsforge_sources"][0]["sha256"] == request["expected_source_sha256"]
    command = {key: value for key, value in request.items() if key != "requested_at"}
    response = client.post(base+"/rebuild", json={**command, "explicit_rebuild_confirmed": True})
    assert response.status_code == 201, response.text
    receipt = response.json()
    assert receipt["source_state"] == "vectors_ready_topology_missing"
    source = load_map_route_sources(tmp_path, project)["sources"][0]
    assert source["kind"] == "mapsforge_vector" and len(source["parts"]) == 2
    assert all(point["time"] is None and "osm_node_id" not in point for part in source["parts"] for point in part)
    assert find_trail_path([source], {"lon":121,"lat":23}, {"lon":121.001,"lat":23.001})["status"] == "blocked"
    preview = compile_planned_route(tmp_path, {"departure_at": "2026-10-01T06:00:00+08:00", "default_speed_kmh": 2,
        "route_selections": [{"source_id": source["source_id"], "part_index": 0, "start_index": 1, "end_index": 0},
                             {"source_id": source["source_id"], "part_index": 1, "start_index": 0, "end_index": 1}]})
    assert preview["status"] == "blocked"
    assert "disconnected_geometry" in {issue["code"] for issue in preview["issues"]}
    single = compile_planned_route(tmp_path, {"departure_at": "2026-10-01T06:00:00+08:00", "default_speed_kmh": 2,
        "route_selections": [{"source_id": source["source_id"], "part_index": 0, "start_index": 1, "end_index": 0}]})
    assert not [issue for issue in single["issues"] if issue["severity"] == "error"]
    assert preview["route_axis"][0]["lon"] == 121.001
    assert preview["comparison"]["golden_available"] is False
    assert client.get(base+"/versions/"+receipt["materialization_id"]).json()["vector"]["properties"]["topology_available"] is False
    assert client.post(base+"/rebuild", json={**command, "source_ref": "project.json", "explicit_rebuild_confirmed": True}).status_code == 409


@pytest.mark.parametrize("target", ["source", "vector", "manifest"])
def test_changed_map_or_bundle_is_never_a_current_source(tmp_path, monkeypatch, target):
    tmp_path = tmp_path / "mapsforge-test"
    project, request, _ = setup_source(tmp_path, monkeypatch)
    receipt = materialize_map_sources(tmp_path, request)
    ref = "source.map" if target == "source" else receipt["project_binding"]["ref"] if target == "vector" else receipt["manifest_ref"]
    with (tmp_path / ref).open("ab") as f:
        f.write(b"changed")
    assert load_map_route_sources(tmp_path, project)["sources"] == []
    with pytest.raises(ValueError):
        inspect_map_materialization(tmp_path, receipt["materialization_id"])


@pytest.mark.parametrize("bad", ["sha", "topology", "bbox", "coordinates", "magic"])
def test_mapsforge_invalid_contract_rejected_without_publishing(tmp_path, monkeypatch, bad):
    tmp_path = tmp_path / "mapsforge-test"
    _, request, payload = setup_source(tmp_path, monkeypatch)
    if bad == "sha": request["expected_source_sha256"] = "0" * 64
    if bad == "topology": payload["features"][0]["properties"]["topology_available"] = True
    if bad == "bbox": payload["properties"]["query_bbox_wgs84"] = {}
    if bad == "coordinates": payload["features"][0]["geometry"]["coordinates"][0][0][0] = float("nan")
    if bad == "magic": (tmp_path / "source.map").write_bytes(b"not a map")
    with pytest.raises(ValueError): materialize_map_sources(tmp_path, request)
    assert not (tmp_path / "outputs/planned_map_sources/catalog.json").exists()
