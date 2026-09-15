from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError

from navigation_terrain_raster_dem import encode_mapbox_terrain_rgb
from scout_gpx_3d import DisplayAuthority, Gpx3DWorkspace
from scout_gpx_3d_terrain import build_display_mesh, sample_prepared_elevation
from tools.scout_gpx_3d_app import create_app


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "explicit-project"
    root.mkdir()
    (root / "track.gpx").write_text('<gpx><trk><trkseg><trkpt lat="0.2" lon="0.2"/></trkseg></trk></gpx>')
    write_json(root / "project.json", {"project_id": root.name})
    return root


def prepared(project, alpha=255):
    # Synthetic one-tile schema fixture; never substituted for real GPX proof.
    body = io.BytesIO()
    Image.new("RGBA", (32, 32), (*encode_mapbox_terrain_rgb(123.4), alpha)).save(body, "PNG")
    (project / "tile.png").write_bytes(body.getvalue())
    manifest = {
        "schema_version": "scout_navigation_terrain_dem.v1", "artifact_kind": "navigation_terrain_raster_dem_tiles",
        "project_id": project.name, "status": "ready", "encoding": "mapbox", "resampling": "bilinear_elevation",
        "visual_interpolation": "bilinear", "adds_source_resolution": False, "nodata_policy": "exclude_incomplete_tiles",
        "tile_block": {"x_min": 1, "x_max": 1, "y_min": 0, "y_max": 0},
        "bounds_wgs84": {"west": 0, "east": 180, "south": 0, "north": 85.0511287798066},
        "minzoom": 1, "maxzoom": 1, "tile_size": 32, "tile_count": 1,
        "source_cell_resolution_m": 20, "source_dtm_tile_ids": ["fixture"],
        "tiles": [{"z": 1, "x": 1, "y": 0, "source_ref": "tile.png", "sha256": hashlib.sha256(body.getvalue()).hexdigest()}],
    }
    write_json(project / "terrain.json", manifest)
    write_json(project / "coverage.json", {"candidate_tiles": [{"tile_id": "fixture", "vertical_datum": "TWVD2001"}]})
    write_json(project / "project.json", {"project_id": project.name, "navigation_terrain_dem_manifest_ref": "terrain.json", "dtm_coverage_summary_ref": "coverage.json"})
    return manifest


def test_read_only_catalog_does_not_choose_other_trips(project):
    sibling = project.parent / "private-trip"
    sibling.mkdir()
    (sibling / "secret.gpx").write_text("not authorized")
    (project / "escape.gpx").symlink_to(sibling / "secret.gpx")
    w = Gpx3DWorkspace(project)
    catalog = w.catalog()
    assert len(catalog.sources) == 1
    assert catalog.sources[0].source_ref == "track.gpx"
    assert catalog.preferred_source_id is None
    assert catalog.sources[0].data_type == "unknown"
    with pytest.raises(FileNotFoundError):
        w.source("../private-trip/secret.gpx")
    for override in ({"runtime_safety_truth": True}, {"visualization_only": False}, {"candidate_only": False}):
        with pytest.raises(ValidationError):
            DisplayAuthority(**override)


def test_source_manifest_role_is_hash_bound_and_separate_from_data_type(project):
    sha = hashlib.sha256((project / "track.gpx").read_bytes()).hexdigest()
    write_json(project / "sources.json", {"sources": [{"workspace_ref": "track.gpx", "sha256": sha, "role": "golden_route_reference"}]})
    write_json(project / "project.json", {"project_id": project.name, "source_inbox_manifest_ref": "sources.json"})
    w = Gpx3DWorkspace(project)
    c = w.catalog()
    assert c.preferred_source_id == c.sources[0].id
    assert c.sources[0].data_type == "unknown"
    (project / "track.gpx").write_text("changed")
    assert w.catalog().preferred_source_id is None


def test_unavailable_empty_and_corrupt_terrain_are_explicit(project):
    assert Gpx3DWorkspace(project / "missing").catalog().status == "unavailable"
    assert Gpx3DWorkspace(project).terrain()["status"] == "unavailable"
    prepared(project)
    (project / "tile.png").write_bytes(b"corrupted")
    response = Gpx3DWorkspace(project).terrain()
    assert response["status"] == "unavailable"
    assert "hash mismatch" in response["summary"]
    assert response["tile_url_template"] is None


def test_mesh_and_sample_preserve_source_and_do_not_fill_nodata(project):
    prepared(project)
    before = {p: p.read_bytes() for p in project.iterdir() if p.is_file()}
    workspace = Gpx3DWorkspace(project)
    mesh = build_display_mesh(workspace)
    assert mesh["status"] == "ready"
    assert mesh["width"] == mesh["height"] == 2
    assert mesh["elevations"] == [123.4] * 4
    assert mesh["vertical_datum"] == "TWVD2001"
    assert mesh["sampling"]["adds_source_resolution"] is False
    assert sample_prepared_elevation(workspace, 45, 45)["elevation_m"] == 123.4
    assert sample_prepared_elevation(workspace, -45, 45)["elevation_m"] is None
    assert all(path.read_bytes() == body for path, body in before.items())
    prepared(project, alpha=0)
    with pytest.raises(ValueError, match="unsupported pixels"):
        build_display_mesh(workspace)


def test_cp_requires_provenance_join_and_preserves_missing_height(project):
    source_sha = hashlib.sha256((project / "track.gpx").read_bytes()).hexdigest()
    write_json(project / "cp.json", [
        {"label": "Existing CP", "candidate_id": "one", "lat": .2, "lon": .2,
         "provenance": [{"uri": "/legacy/filtered.gpx"}], "review_state": "proposed"},
        {"label": "Unrelated CP", "lat": .2, "lon": .2, "route_point_index": 0},
    ])
    write_json(project / "filter.json", {"primary": {"output_path": "/legacy/filtered.gpx", "output_sha256": source_sha}, "references": []})
    write_json(project / "project.json", {"project_id": project.name, "checkpoint_candidates_ref": "cp.json", "gpx_speed_filter_report_ref": "filter.json"})
    workspace = Gpx3DWorkspace(project)
    result = workspace.checkpoints(workspace.catalog().sources[0].id)
    assert result["unmatched_count"] == 1
    assert result["nodes"][0]["name"] == "Existing CP"
    assert result["nodes"][0]["gpx_elevation_m"] is None
    assert result["nodes"][0]["cp_elevation_m"] is None
    assert result["nodes"][0]["time"] is None


def test_api_only_serves_allowlisted_reads_and_leaves_bytes_unchanged(project):
    before = {p.name: p.read_bytes() for p in project.iterdir()}
    with TestClient(create_app(project)) as client:
        catalog = client.get("/api/catalog").json()
        source = catalog["sources"][0]
        response = client.get(f"/api/gpx/{source['id']}")
        assert response.content == before["track.gpx"]
        assert response.headers["x-source-sha256"] == source["sha256"]
        assert response.headers["cache-control"] == "no-store"
        assert "connect-src 'self'" in response.headers["content-security-policy"]
        assert client.post("/api/gpx/anything", content="GPX").status_code == 405
        assert client.get("/api/catalog", headers={"origin": "https://public.example"}).status_code == 403
        assert client.get("/api/catalog", headers={"sec-fetch-site": "cross-site"}).status_code == 403
        assert client.get("/api/catalog", headers={"host": "attacker.example"}).status_code == 400
        for path in ("/.env", "/project.json", "/admin", "/api/gpx/not-in-catalog", "/assets/../../project.json"):
            assert client.get(path).status_code == 404
    assert {p.name: p.read_bytes() for p in project.iterdir()} == before


def test_benchmark_uses_isolated_vendor_and_retains_read_only_boundary(project):
    from tools.scout_gpx_3d_benchmark_app import create_benchmark_app

    before = {p.name: p.read_bytes() for p in project.iterdir()}
    with TestClient(create_benchmark_app(project)) as client:
        assert client.get("/benchmark").status_code == 200
        assert client.get("/benchmark-maplibre/maplibre-gl.mjs").status_code == 200
        assert client.post("/benchmark", json={"result": "fake"}).status_code == 405
        assert client.get("/benchmark", headers={"origin": "https://public.example"}).status_code == 403
        assert client.get("/benchmark-maplibre/../../project.json").status_code == 404
        assert client.get("/admin").status_code == 404
    assert {p.name: p.read_bytes() for p in project.iterdir()} == before


def cost_replay_fixture(project):
    """Schema-only fixture for the local HTTP boundary, not performance evidence."""
    manifest = prepared(project)
    manifest["source_fingerprint"] = "synthetic-http-fixture"
    write_json(project / "terrain.json", manifest)
    config = json.loads((project / "project.json").read_text())
    config["navigation_terrain_projection_ref"] = "projection.json"
    write_json(project / "project.json", config)
    write_json(project / "projection.json", {
        "boundary": {"candidate_only": True, "runtime_safety_truth": False},
        "projection_compilation": {"input_fingerprint": "explicitly-stale-test-fixture"},
    })
    write_json(project / f"outputs/layers/manifests/{project.name}.rudy-twmap.raster_tile_cache_manifest.json", {
        "imagery_source_id": "happyman_rudy_twmap", "plan": {"max_zoom": 1},
    })
    tile = project / f"cache/raster-tiles/{project.name}/rudy-twmap/1/1/0.png"
    tile.parent.mkdir(parents=True)
    tile.write_bytes((project / "tile.png").read_bytes())


def test_dashboard_cost_replays_stale_evidence_without_bootstrap_or_writes(project):
    from tools.dashboard_3d_cost_app import create_cost_app

    cost_replay_fixture(project)
    before = {p.relative_to(project): p.read_bytes() for p in project.rglob("*") if p.is_file()}
    with TestClient(create_cost_app(project, project.parent / "evidence")) as client:
        response = client.get("/cost-data")
        assert hashlib.sha256(response.content).hexdigest() == response.headers["x-source-sha256"]
        payload = response.json()
        assert payload["provenance"]["current_read_interface_status"] == "not_prepared"
        assert payload["provenance"]["authority"] == {"candidate_only": True, "visualization_only": True, "runtime_safety_truth": False}
        assert client.get("/cost-dem/1/1/0.png").content == before[Path("tile.png")]
        assert client.get(f"/admin/tiles/imagery/{project.name}/imagery/1/1/0.png").content == before[Path("tile.png")]
        assert client.get("/cost-dem/1/0/0.png").status_code == 404
        assert client.get(f"/admin/tiles/imagery/{project.name}/imagery/2/1/0.png").status_code == 404
        assert client.get("/admin/tiles/imagery/unselected/imagery/1/1/0.png").status_code == 404
        html = client.get("/dashboard-cost").text
        assert '<script src="/cost-dashboard-source.js"></script>' in html
        script = client.get("/cost-dashboard-source.js").text
        original = Path("docs/admin/scout-dashboard-v0.1.html").read_text()
        assert 'document.addEventListener("DOMContentLoaded", () => {' in original
        assert 'document.addEventListener("DOMContentLoaded", () => {' not in script
        assert 'document.addEventListener("cost-replay-no-bootstrap", () => {' in script
        for method in (client.post, client.put, client.delete):
            assert method("/cost-data").status_code == 405
        assert client.get("/cost-data", headers={"origin": "https://public.example"}).status_code == 403
        assert client.get("/cost-data", headers={"host": "attacker.example"}).status_code == 400
        assert "connect-src 'self'" in response.headers["content-security-policy"]
        assert client.get("/api/projects").status_code == 404
    assert {p.relative_to(project): p.read_bytes() for p in project.rglob("*") if p.is_file()} == before


def test_dashboard_cost_rejects_runtime_authority_and_corrupt_dem(project):
    from tools.dashboard_3d_cost_app import create_cost_app

    cost_replay_fixture(project)
    write_json(project / "projection.json", {"boundary": {"candidate_only": False, "runtime_safety_truth": True}})
    with pytest.raises(ValueError, match="candidate-only"):
        create_cost_app(project, project.parent / "evidence")
    write_json(project / "projection.json", {"boundary": {"candidate_only": True, "runtime_safety_truth": False}})
    (project / "tile.png").write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="Complete prepared terrain"):
        create_cost_app(project, project.parent / "evidence")
