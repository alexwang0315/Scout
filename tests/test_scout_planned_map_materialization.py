"""Map repair preserves old evidence and enforces topology/review boundaries."""
from __future__ import annotations

import hashlib
import io
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from scout_planned_map_materialization import (
    CATALOG_REF, materialize_map_sources, materialize_rudy_trace, read_materialization_catalog, inspect_map_materialization,
)
from scout_planned_route_sources import find_trail_path, load_map_route_sources


def _write(root, ref, value):
    path = root / ref
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = value if isinstance(value, bytes) else json.dumps(value).encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _workspace(root):
    raw_ref = "map/current.osm.json"
    _write(root, "project.json", {"project_id": "map-source-test", "overpass_raw_payload_ref": raw_ref})
    _write(root, raw_ref, {"elements": [{"type": "way", "id": 41, "nodes": [4, 5, 6],
        "tags": {"highway": "path", "name": "Current raw trail"},
        "geometry": [{"lon": 121, "lat": 23}, {"lon": 121.001, "lat": 23}, {"lon": 121.002, "lat": 23}]}]})
    return {"source_kind": "overpass_raw", "source_ref": raw_ref,
            "bbox_wgs84": {"south": 22.9, "west": 120.9, "north": 23.1, "east": 121.1},
            "requested_at": "2026-09-10T08:00:00+08:00", "requested_by": "test_operator"}


def _project(root):
    return json.loads((root / "project.json").read_bytes())


def test_rebuild_uses_current_raw_geometry_and_preserves_legacy_hash_mismatch(tmp_path):
    request = _workspace(tmp_path)
    old_vector = {"type": "FeatureCollection", "properties": {"raw_response_sha256": "a" * 64}, "features": []}
    _write(tmp_path, "map/old.geojson", old_vector)
    project = _project(tmp_path)
    project["overpass_map_context_ref"] = "map/old.geojson"
    _write(tmp_path, "project.json", project)
    before = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    result = materialize_map_sources(tmp_path, request)
    assert result["source_state"] == "topology_ready"
    assert result["legacy_sources"]["state"] == "legacy_raw_hash_mismatch"
    assert result["project_modified"] is False
    assert result["runtime_safety_truth"] is False
    assert before == {ref: (tmp_path / ref).read_bytes() for ref in before}
    catalog = load_map_route_sources(tmp_path, project)
    assert len(catalog["sources"]) == 1
    source = catalog["sources"][0]
    assert [p["osm_node_id"] for p in source["parts"][0]] == [4, 5, 6]
    assert result["manifest_ref"] in source["provenance"]["source_hashes"]
    assert CATALOG_REF not in catalog["source_hashes"]
    route = find_trail_path(catalog["sources"], {"lon": 121, "lat": 23}, {"lon": 121.002, "lat": 23})
    assert route["status"] == "ready"
    assert [p["osm_node_id"] for p in route["parts"][0]] == [4, 5, 6]
    assert materialize_map_sources(tmp_path, request)["manifest_sha256"] == result["manifest_sha256"]
    assert len(json.loads((tmp_path / CATALOG_REF).read_bytes())["entries"]) == 1


def test_raw_without_node_id_does_not_fabricate_graph_topology(tmp_path):
    request = _workspace(tmp_path)
    payload = json.loads((tmp_path / request["source_ref"]).read_bytes())
    del payload["elements"][0]["nodes"]
    _write(tmp_path, request["source_ref"], payload)
    result = materialize_map_sources(tmp_path, request)
    assert result["source_state"] == "vectors_ready_topology_missing"
    sources = load_map_route_sources(tmp_path, _project(tmp_path))["sources"]
    assert len(sources) == 1
    assert find_trail_path(sources, {"lon": 121, "lat": 23}, {"lon": 121.002, "lat": 23})["status"] == "blocked"


def test_current_input_change_invalidates_a_materialized_source(tmp_path):
    request = _workspace(tmp_path)
    materialize_map_sources(tmp_path, request)
    with (tmp_path / request["source_ref"]).open("ab") as stream:
        stream.write(b" ")
    source = load_map_route_sources(tmp_path, _project(tmp_path))
    assert source["sources"] == []
    assert any(row["status"] == "stale_or_unavailable" for row in source["source_states"])


@pytest.mark.parametrize("target", ["manifest", "vector", "evidence"])
def test_bundle_tampering_fails_closed(tmp_path, target):
    request = _workspace(tmp_path)
    result = materialize_map_sources(tmp_path, request)
    ref = result["manifest_ref"] if target == "manifest" else result["project_binding"]["ref" if target == "vector" else "evidence_ref"]
    with (tmp_path / ref).open("ab") as stream:
        stream.write(b" ")
    assert not load_map_route_sources(tmp_path, _project(tmp_path))["sources"]


def test_concurrent_materializations_append_catalog_without_invalidating_old_bundle(tmp_path):
    request = _workspace(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda second: materialize_map_sources(tmp_path, {
            **request, "requested_at": f"2026-09-10T00:00:0{second}Z"}), (1, 2)))
    catalog = read_materialization_catalog(tmp_path, "map-source-test")
    assert len(catalog["overpass"]) == 2
    for result in results:
        assert hashlib.sha256((tmp_path / result["manifest_ref"]).read_bytes()).hexdigest() == result["manifest_sha256"]
    assert all(row["status"] == "topology_ready" for row in catalog["source_states"])


@pytest.mark.parametrize("source_ref", ["/etc/passwd", "../secret", "~/.ssh/key", "source-link.pbf"])
def test_source_cannot_escape_owned_workspace(tmp_path, source_ref):
    request = _workspace(tmp_path)
    (tmp_path / "source-link.pbf").symlink_to("/etc/passwd")
    with pytest.raises(ValueError, match="relative|escapes"):
        materialize_map_sources(tmp_path, {**request, "source_ref": source_ref})
    assert not (tmp_path / CATALOG_REF).exists()


def test_wrong_project_catalog_is_not_adopted(tmp_path):
    request = _workspace(tmp_path)
    materialize_map_sources(tmp_path, request)
    other = _project(tmp_path)
    other["project_id"] = "another-project"
    result = load_map_route_sources(tmp_path, other)
    assert not result["sources"]
    assert any(row["code"] == "MAP_MATERIALIZATION_CATALOG_UNAVAILABLE" for row in result["issues"])


def _rudy(root, reviewer_kind="software"):
    _write(root, "project.json", {"project_id": "rudy-review"})
    img = Image.new("RGB", (256, 256), "white")
    ImageDraw.Draw(img).line([(5, 40), (240, 220)], fill="red", width=3)
    output = io.BytesIO()
    img.save(output, format="PNG")
    sha = _write(root, "map/rudy.png", output.getvalue())
    source_sha = _write(root, "map/rudy-manifest.json", {"candidate_only": True, "runtime_safety_truth": False,
        "imagery_source_id": "happyman_rudy_twmap", "layer_id": "rudy-twmap", "project_id": "rudy-review",
        "plan": {"source_id": "happyman_rudy_twmap", "project_id": "rudy-review", "source_metadata": {"tile_matrix_crs": "EPSG:3857"}}})
    # Zoom0 is intentionally a fixture. Real-run acceptance uses observed z14+
    # tiles and is retained outside the repository.
    return {"label": "Fixture candidate drawing", "geometry": {"type": "LineString", "coordinates": [[121, 23], [121.001, 23.001]]},
            "map_evidence": [{"ref": "map/rudy.png", "sha256": sha, "z": 0, "x": 0, "y": 0, "source_manifest_ref": "map/rudy-manifest.json", "source_manifest_sha256": source_sha}],
            "reviewed_by": "test_operator", "reviewer_kind": reviewer_kind,
            "review_note": "Fixture checks candidate provenance only; no real human or field review.",
            "reviewed_at": "2026-09-10T00:00:00Z", "candidate_review_confirmed": True}


def test_software_rudy_trace_remains_pending_human_review(tmp_path):
    request = _rudy(tmp_path)
    result = materialize_rudy_trace(tmp_path, request)
    assert result["source_state"] == "pending_human_review"
    trace = json.loads((tmp_path / result["project_binding"]["ref"]).read_bytes())
    assert trace["properties"]["human_reviewed"] is False
    assert trace["properties"]["field_verified"] is False
    catalog = load_map_route_sources(tmp_path, _project(tmp_path))
    assert catalog["sources"] == []
    assert any(row["status"] == "pending_human_review" for row in catalog["source_states"])


def test_reviewed_rudy_keeps_original_map_hash_and_geometry(tmp_path):
    request = _rudy(tmp_path, "human")
    result = materialize_rudy_trace(tmp_path, request)
    sources = load_map_route_sources(tmp_path, _project(tmp_path))["sources"]
    assert len(sources) == 1
    assert sources[0]["provenance"]["human_reviewed"] is True
    assert sources[0]["provenance"]["field_verified"] is False
    assert "map/rudy.png" in sources[0]["provenance"]["source_hashes"]
    assert result["manifest_ref"] in sources[0]["provenance"]["source_hashes"]
    assert [(p["lon"], p["lat"]) for p in sources[0]["parts"][0]] == [(121, 23), (121.001, 23.001)]


@pytest.mark.parametrize("change", ["unconfirmed", "blank", "matrix", "outside", "hash"])
def test_rudy_requires_real_bound_georeferenced_pixels_and_review(tmp_path, change):
    request = _rudy(tmp_path, "human")
    if change == "unconfirmed":
        request["candidate_review_confirmed"] = False
    elif change == "blank":
        img = Image.new("RGBA", (256, 256), (0, 0, 0, 0)); output = io.BytesIO(); img.save(output, format="PNG")
        request["map_evidence"][0]["sha256"] = _write(tmp_path, "map/rudy.png", output.getvalue())
    elif change == "matrix":
        request["map_evidence"][0]["x"] = 4
    elif change == "outside":
        request["map_evidence"][0].update(z=10, x=0, y=0)
    else:
        request["map_evidence"][0]["sha256"] = "f" * 64
    with pytest.raises(ValueError):
        materialize_rudy_trace(tmp_path, request)
    assert not (tmp_path / CATALOG_REF).exists()


def test_rudy_cannot_relabel_an_unrelated_raster_as_prepared_map_evidence(tmp_path):
    request = _rudy(tmp_path, "human")
    request["map_evidence"][0]["source_manifest_sha256"] = _write(tmp_path, "map/rudy-manifest.json", {
        "imagery_source_id": "unrelated_imagery", "candidate_only": True, "runtime_safety_truth": False})
    with pytest.raises(ValueError, match="prepared source manifest"):
        materialize_rudy_trace(tmp_path, request)
    assert not (tmp_path / CATALOG_REF).exists()


def test_human_can_review_software_draft_without_relabeling_its_author(tmp_path):
    request = _rudy(tmp_path)
    draft = materialize_rudy_trace(tmp_path, request)
    inspected = inspect_map_materialization(tmp_path, draft["materialization_id"])
    assert inspected["trace"]["properties"]["human_reviewed"] is False
    approved = materialize_rudy_trace(tmp_path, {**request, "reviewer_kind": "human", "trace_author_kind": "software", "reviewed_by": "fixture_human"})
    sources = load_map_route_sources(tmp_path, _project(tmp_path))["sources"]
    assert len(sources) == 1
    assert sources[0]["provenance"]["trace_author_kind"] == "software"
    assert sources[0]["provenance"]["human_reviewed"] is True
    assert sources[0]["provenance"]["field_verified"] is False
    assert hashlib.sha256((tmp_path / draft["manifest_ref"]).read_bytes()).hexdigest() == draft["manifest_sha256"]
    assert approved["materialization_id"] != draft["materialization_id"]


def test_broken_legacy_json_can_be_preserved_while_new_raw_is_rebuilt(tmp_path):
    request = _workspace(tmp_path)
    project = _project(tmp_path)
    project["overpass_map_context_ref"] = "map/broken.geojson"
    _write(tmp_path, "project.json", project)
    _write(tmp_path, "map/broken.geojson", b"broken old vector")
    result = materialize_map_sources(tmp_path, request)
    assert result["legacy_sources"]["state"] == "legacy_unreadable_declaration"
    assert result["legacy_sources"]["unreadable_declarations"] == ["map/broken.geojson"]
    assert len(load_map_route_sources(tmp_path, project)["sources"]) == 1
    assert (tmp_path / "map/broken.geojson").read_bytes() == b"broken old vector"


@pytest.mark.parametrize("content", [[], {"schema_version": "plannedMapSourceMaterialization.v1", "project_id": "map-source-test", "entries": "bad"}])
def test_malformed_discovery_metadata_is_explicitly_unavailable(tmp_path, content):
    _workspace(tmp_path)
    _write(tmp_path, CATALOG_REF, content)
    result = load_map_route_sources(tmp_path, _project(tmp_path))
    assert any(issue["code"] == "MAP_MATERIALIZATION_CATALOG_UNAVAILABLE" for issue in result["issues"])
    assert result["sources"] == []
