import hashlib
import json
import shutil

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pretrip_gpx_source_resolution import resolve_gpx_sources
from scout_trip_notebook import NotebookAnalysisRequest, analyze_notebook_track, build_notebook_snapshot, safe_ref
from scout_trip_notebook_api import create_trip_notebook_router


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "route"
    def write(ref, value):
        path = root / ref
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value if isinstance(value, str) else json.dumps(value))
    gpx = '<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg><trkpt lat="23" lon="121"><ele>100</ele><time>2026-01-01T00:00:00Z</time></trkpt><trkpt lat="23.01" lon="121"><ele>110</ele><time>2026-01-01T01:00:00Z</time></trkpt></trkseg></trk></gpx>'
    write("inbox/gpx/a.gpx", gpx)
    sha = hashlib.sha256(gpx.encode()).hexdigest()
    write("project.json", {"project_id":"route", "checkpoint_candidates_ref":"candidates/checkpoints.json", "route_summary_ref":"normalized/routes/route_summary.json"})
    write("candidates/checkpoints.json", [{"candidate_id":"start", "label":"登山口", "lat":23,"lon":121,"route_distance_m":0}, {"candidate_id":"hut", "label":"山屋", "lat":23.01,"lon":121,"route_distance_m":1112}])
    write("outputs/mcp/mcp_candidates.json", {"mcp_candidates":[]})
    write("normalized/routes/route_summary.json", {"route_name":"本機測試路線", "distance_m":1112})
    write("normalized/routes/route_evidence_bundle.json", {"golden_route":{"filtered_geometry_ref":"inbox/gpx/a.gpx", "filtered_geometry_sha256":sha}})
    write("sources/historical_gpx_source_index.json", {"sources":[{"source_id":"a", "workspace_ref":"inbox/gpx/a.gpx", "original_path":"/unavailable/old-mac/a.gpx", "sha256":sha}, {"source_id":"same-content", "workspace_ref":"inbox/gpx/a.gpx", "sha256":sha}]})
    return root


def test_snapshot_survives_relocation_and_deduplicates_without_writes(workspace, tmp_path):
    before = {str(p.relative_to(workspace)):p.read_bytes() for p in workspace.rglob('*') if p.is_file()}
    original = build_notebook_snapshot(workspace)
    copied = tmp_path / "another-location"
    shutil.copytree(workspace, copied)
    relocated = build_notebook_snapshot(copied)
    assert original["version"] == relocated["version"]
    assert original["timing_counts"]["unique_content_source_count"] == 1
    assert original["timing_counts"]["duplicate_content_source_count"] == 1
    assert original["segments"][0]["sample_count"] == 1
    assert original["segments"][0]["duration_minutes"]["p50"] == 60
    assert original["boundary"]["runtime_safety_truth"] is False
    assert original["weather"]["fetched_at"] is None
    assert {str(p.relative_to(workspace)):p.read_bytes() for p in workspace.rglob('*') if p.is_file()} == before


def test_changed_source_is_rejected_and_version_changes(workspace):
    before = build_notebook_snapshot(workspace)
    (workspace / "inbox/gpx/a.gpx").write_text('<gpx/>')
    after = build_notebook_snapshot(workspace)
    assert after["version"] != before["version"]
    assert not after["geometry"]
    assert not after["segments"]
    assert any(i["code"] == "invalid_geometry" for i in after["issues"])


def test_resolver_fails_closed_for_external_symlink_and_wrong_hash(workspace, tmp_path):
    private = tmp_path / "private.gpx"
    private.write_text("private")
    (workspace / "escape.gpx").symlink_to(private)
    records = [{"source_id":"escape", "workspace_ref":"escape.gpx", "original_path":str(private)}, {"source_id":"bad-hash", "workspace_ref":"inbox/gpx/a.gpx", "sha256":"0" * 64}]
    sources, receipts = resolve_gpx_sources(workspace, records, allow_external_original_paths=False)
    assert not sources
    assert [r["status"] for r in receipts] == ["unsafe_workspace_ref", "hash_mismatch"]
    assert "private" not in json.dumps(receipts)


@pytest.mark.parametrize("ref", ["../private", "/etc/passwd", ""])
def test_unsafe_refs_rejected(workspace, ref):
    with pytest.raises(ValueError):
        safe_ref(workspace, ref)


def request(points):
    return NotebookAnalysisRequest(draft_id="isolated-demo", origin="simulation", points=points)


def test_stateless_analysis_separates_rest_missing_gaps_and_parts():
    points = [{"lat":23, "lon":121, "timestamp":f"2026-01-01T00:{i:02d}:00+00:00"} for i in range(6)]
    points += [{"lat":23, "lon":121, "timestamp":"2026-01-01T01:05:00Z", "part":1}, {"lat":23.001, "lon":121, "timestamp":"2026-01-01T01:06:00Z", "part":1}]
    result = analyze_notebook_track(request(points))
    assert result["elapsed_s"] == 3960
    assert result["rest_s"] == 300
    assert result["unclassified_gap_s"] == 3600
    assert result["moving_s"] == 60
    assert 110 < result["distance_m"] < 112
    assert result["receipt_id"] == analyze_notebook_track(request(points))["receipt_id"]
    assert result["saved_to_workspace"] is False
    assert result["sent"] is False


def test_analysis_rejects_non_monotonic_or_naive_times():
    p = {"lat":23, "lon":121, "timestamp":"2026-01-01T01:00:00Z"}
    with pytest.raises(ValueError, match="遞增"):
        analyze_notebook_track(request([p,p]))
    with pytest.raises(ValueError, match="timezone"):
        request([{**p,"timestamp":"2026-01-01T01:00:00"},p])


def test_analysis_excludes_impossible_speed_and_missing_altitude():
    result = analyze_notebook_track(request([{"lat":23,"lon":121,"timestamp":"2026-01-01T00:00:00Z"}, {"lat":24,"lon":121,"timestamp":"2026-01-01T00:00:01Z"}]))
    assert result["unclassified_gap_s"] == 1
    assert result["distance_m"] == 0
    assert result["moving_s"] == 0


def test_router_uses_selected_identity_and_only_serves_allowlisted_assets(workspace):
    app=FastAPI();app.include_router(create_trip_notebook_router(workspace), prefix="/admin")
    client=TestClient(app)
    response=client.get('/admin/trip-notebook/snapshot/route')
    assert response.status_code == 200
    assert response.headers['X-Scout-Notebook-Version'] == response.json()['version']
    assert response.json()['project_id'] == 'route'
    assert client.get('/admin/trip-notebook/snapshot/other').status_code == 404
    assert client.get('/admin/trip-notebook/AGENTS.md').status_code == 404
    assert client.post('/admin/trip-notebook/snapshot/route').status_code == 405
    assert client.get('/admin/trip-notebook/').status_code == 200
    assert "connect-src 'self'" in client.get('/admin/trip-notebook/').headers['Content-Security-Policy']
    assert client.get('/admin/trip-notebook/sw.js').status_code == 200
    assert '__SHELL_VERSION__' not in client.get('/admin/trip-notebook/sw.js').text


def test_route_identity_cannot_follow_workspace_symlink(workspace, tmp_path):
    catalog=tmp_path/'catalog';catalog.mkdir();(catalog/'route').symlink_to(workspace)
    app=FastAPI();app.include_router(create_trip_notebook_router(catalog))
    assert TestClient(app).get('/trip-notebook/snapshot/route').status_code == 404
