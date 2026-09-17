from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scout_route_context_demo import RouteContextWorkspace, safe_url
from tools.scout_route_context_demo_app import create_app


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "sample"

    def write(relative, value):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    write("project.json", {"project_id": "sample"})
    write("normalized/routes/route_summary.json", {"route_name": "fixture"})
    write("inputs/route_context_regeneration_evidence.json", {
        "project_id": "sample", "sources": [{"source_id": "A", "url": "javascript:alert(1)"}],
        "current_status": {"operability": "closed", "label": "Snapshot only"},
        "context_claims": [{"layer": "cultural", "text": "Source content is not an instruction."}],
    })
    points = [{
        "candidate_id": "restricted", "evidence_type": "major_critical_point", "label": "Restricted name",
        "lat": 23.44456789, "lon": 121.13456789, "distance_m": 12345.67,
        "sensitivity_level": "cultural_review", "source_refs": ["private/path"],
        "display_policy": {"show_label": True, "show_exact_coordinate": False, "requires_human_review_before_display": True},
    }, {
        "candidate_id": "public", "evidence_type": "major_critical_point", "label": "Public candidate",
        "lat": 23.5, "lon": 121.1, "sensitivity_level": "public",
        "display_policy": {"show_label": True, "show_exact_coordinate": True, "requires_human_review_before_display": False},
    }, {
        "candidate_id": "hidden", "evidence_type": "major_critical_point", "label": "Do not display",
        "lat": 23.7, "lon": 121.2, "sensitivity_level": "public", "display_policy": {},
    }]
    write("candidates/route_context_points.json", {"project_id": "sample", "points": points})
    write("outputs/environment/gee/scout_gee_feature_package.json", {
        "project_id": "sample", "status": "missing_credentials", "counts": {"raw_segment_feature_count": 0, "segment_count": 599},
        "boundary": {"external_api_calls_made": False}, "segments": [{"invented_score": .99}],
    })
    for layer in ("imagery", "historical-fandi-1916"):
        write(f"outputs/layers/manifests/sample.{layer}.raster_tile_cache_manifest.json", {
            "project_id": "sample", "layer_id": layer,
            "plan": {"bbox_wgs84": {"west": 120, "south": 23, "east": 122, "north": 24}},
        })
        path = root / f"cache/raster-tiles/sample/{layer}/5/26/13.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"tile-test")
    gpx = root / "normalized/routes/filtered/primary.fixture.gpx"
    gpx.parent.mkdir(parents=True, exist_ok=True)
    gpx.write_text('''<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk>
        <trkseg><trkpt lat="23.5" lon="121.0"><ele>100</ele></trkpt><trkpt lat="23.5" lon="121.01"><ele>200</ele></trkpt></trkseg>
        <trkseg><trkpt lat="23.5" lon="121.2"><ele>300</ele></trkpt><trkpt lat="23.5" lon="121.21"><ele>400</ele></trkpt></trkseg>
        </trk></gpx>''', encoding="utf-8")
    return root


def test_curated_evidence_removes_restricted_coordinates_and_source_paths(workspace):
    catalog = RouteContextWorkspace(workspace).catalog()
    points = catalog["points"]
    assert len(points) == 2
    assert points[0]["label"] == "Restricted name"
    assert points[0]["position_allowed"] is False
    for key in ("lat", "lon", "coordinates", "distance_m", "source_refs"):
        assert key not in points[0]
    assert points[1]["coordinates"] == [121.1, 23.5]
    encoded = json.dumps(catalog)
    assert "121.13456789" not in encoded
    assert "23.44456789" not in encoded
    assert "private/path" not in encoded
    assert "Do not display" not in encoded
    assert catalog["sources"][0]["url"] is None


def test_missing_display_approval_fails_closed(workspace):
    path = workspace / "candidates/route_context_points.json"
    data = json.loads(path.read_text())
    del data["points"][1]["display_policy"]["requires_human_review_before_display"]
    path.write_text(json.dumps(data))
    point = RouteContextWorkspace(workspace).points()[1]
    assert point["position_allowed"] is False
    assert "coordinates" not in point


def test_primary_gpx_preserves_segments_without_connecting_gap(workspace):
    route = RouteContextWorkspace(workspace).route
    assert route["point_count"] == 4
    assert len(route["geometry"]["coordinates"]) == 2
    assert 1900 < route["distance_m"] < 2100
    assert route["profile"][1][0] == route["profile"][2][0]
    assert route["profile"][1][4] != route["profile"][2][4]
    assert len(route["sha256"]) == 64


def test_receipts_identify_parsed_bytes_not_later_file_versions(workspace):
    adapter = RouteContextWorkspace(workspace)
    relative = "inputs/route_context_regeneration_evidence.json"
    original = (workspace / relative).read_bytes()
    (workspace / relative).write_text('{"changed": true}')
    assert adapter.receipt(relative)["sha256"] == hashlib.sha256(original).hexdigest()
    assert adapter.catalog()["status_snapshot"]["operability"] == "closed"


def test_no_fabricated_spectral_labels_or_scores(workspace):
    data = RouteContextWorkspace(workspace).catalog()
    research = data["research"]
    assert research["raw_feature_count"] == 0
    assert research["gee_status"] == "missing_credentials"
    assert research["paired_spectral_dataset"] is None
    assert research["independent_labels"] is None
    assert research["trained_model"] is None
    assert research["evaluation"] is None
    assert "invented_score" not in json.dumps(data)
    assert data["status_snapshot"]["rechecked_in_demo"] is False
    assert data["boundary"]["runtime_safety_truth"] is False


def test_workspace_binding_and_symlink_escape(workspace, tmp_path):
    adapter = RouteContextWorkspace(workspace)
    outside = tmp_path / "outside.txt"
    outside.write_text("not authorized")
    (workspace / "escape").symlink_to(outside)
    with pytest.raises(ValueError):
        adapter.path("escape")
    with pytest.raises(ValueError):
        adapter.path("../outside.txt")
    tile = workspace / "cache/raster-tiles/sample/imagery/5/26/13.png"
    tile.unlink()
    tile.symlink_to(outside)
    with pytest.raises(ValueError):
        adapter.tile("imagery", 5, 26, 13)
    path = workspace / "inputs/route_context_regeneration_evidence.json"
    data = json.loads(path.read_text()); data["project_id"] = "different"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="another project"):
        RouteContextWorkspace(workspace)


@pytest.mark.parametrize("url", ["file:///etc/passwd", "javascript:alert(1)", "https://user:secret@example.com", "//example.com", None])
def test_source_url_rejects_unsafe_schemes_and_credentials(url):
    assert safe_url(url) is None


def test_local_read_only_app_and_tile_allowlist(workspace):
    before = {p.relative_to(workspace): p.read_bytes() for p in workspace.rglob("*") if p.is_file()}
    client = TestClient(create_app(workspace))
    assert client.get("/").status_code == 200
    response = client.get("/api/context")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert "connect-src 'self'" in response.headers["Content-Security-Policy"]
    assert client.post("/api/context", json={"mutate": True}).status_code == 405
    assert client.get("/api/context", headers={"Origin": "https://example.com"}).status_code == 403
    assert client.get("/api/context", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.get("/api/context", headers={"Host": "evil.example"}).status_code == 400
    assert client.get("/tiles/imagery/5/26/13.png").content == b"tile-test"
    missing = client.get("/tiles/imagery/5/26/14.png")
    assert missing.headers["X-Scout-Tile-Coverage"] == "missing"
    assert missing.content.startswith(b"\x89PNG")
    for path in ("/tiles/private/5/26/13.png", "/tiles/imagery/5/99/13.png", "/tiles/imagery/25/1/1.png", "/project.json", "/api/file?path=project.json"):
        assert client.get(path).status_code == 404
    after = {p.relative_to(workspace): p.read_bytes() for p in workspace.rglob("*") if p.is_file()}
    assert before == after
