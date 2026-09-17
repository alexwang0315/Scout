"""P7/P8 persistence and analysis admission with a deterministic compiler seam.

The route compiler's geometry/timing tests live separately. These cases execute
real filesystem publication, API validation, reload, review and selection.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path
import sys
import types
import zipfile

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from scout_analysis_subject import build_analysis_subject
import scout_planned_route_artifacts as artifacts
from scout_planned_route_api import create_planned_route_router
from scout_planned_route_models import PlannedRouteConflict, PlannedRouteRequest


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _files(root):
    return {p.relative_to(root).as_posix(): _sha(p.read_bytes())
            for p in root.rglob("*") if p.is_file()}


def _json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(artifacts.canonical_bytes(value))


@pytest.fixture
def planned(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    root = workspace / "planned_fixture"
    root.mkdir(parents=True)
    _json(root / "project.json", {"project_id": root.name, "reviewed_mission_baseline_ref": "reviews/golden.json"})
    _json(root / "reviews/golden.json", {"legacy": "original accepted Golden remains intact"})
    (root / "source.gpx").write_text("<gpx><trk><trkseg><trkpt lat='23' lon='121'/></trkseg></trk></gpx>")

    def compile_candidate(project_root, request):
        source_hashes = {ref: _sha((project_root / ref).read_bytes()) for ref in ("project.json", "source.gpx")}
        snapshot = _sha(artifacts.canonical_bytes(source_hashes))
        if request.source_snapshot_sha256 and request.source_snapshot_sha256 != snapshot:
            raise PlannedRouteConflict("planned_sources_stale", "Fixture source snapshot changed.")
        coordinates = [[121.0, 23.0, 1000], [121.001, 23.001, 1020],
                       [121.002, 23.002, 1200], [121.001, 23.001, 1020], [121.003, 23.004, 1040]]
        cp = [{"checkpoint_id": f"planned.cp.{i}", "point_index": i, "lon": point[0], "lat": point[1]}
              for i, point in enumerate(coordinates)]
        segments = [{"segment_id": f"planned.seg.{i}", "from_checkpoint_id": cp[i]["checkpoint_id"],
                     "to_checkpoint_id": cp[i + 1]["checkpoint_id"]} for i in range(len(cp) - 1)]
        timetable = {"days": [{"mission_day_id": "D1", "departure_at": request.model_dump(mode="json")["departure_at"],
                                "checkpoint_ids": [row["checkpoint_id"] for row in cp],
                                "segment_ids": [row["segment_id"] for row in segments]}],
                     "timeline": [{"kind": "stop", "duration_minutes": 40}],
                     "unknowns": [{"issue_id": "time.unknown", "reason": "Reverse branch pace is an estimate."}],
                     "conflicts": [], "timezone": "+08:00"}
        geometry_sha = _sha(artifacts.canonical_bytes(coordinates))
        result = {
            "project_id": project_root.name, "source_snapshot_sha256": snapshot,
            "request": request.model_dump(mode="json"), "source_hashes": source_hashes,
            "geometry_sha256": geometry_sha, "itinerary_sha256": _sha(artifacts.canonical_bytes(timetable)),
            "planned_gpx": '<gpx creator="Scout Planned"><metadata><type>planned_candidate</type></metadata></gpx>',
            "route_geojson": {"type": "FeatureCollection", "features": [{"type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coordinates}, "properties": {"role": "planned"}}]},
            "route_axis": {"points": coordinates, "geometry_sha256": geometry_sha}, "checkpoints": cp,
            "segments": segments, "itinerary": timetable, "comparison": {"branch_added": True},
            "coverage": {"status": "coverage_needed", "reason": "Branch leaves the prepared DEM footprint."},
            "issues": [], "status": "needs_review", "candidate_only": True, "runtime_safety_truth": False,
        }
        result["preview_sha256"] = _sha(artifacts.canonical_bytes(result))
        return result

    module = types.ModuleType("scout_planned_route")
    module.compile_planned_route = compile_candidate
    module.load_planned_catalog = lambda project_root: {"project_id": project_root.name, "candidate_only": True}
    monkeypatch.setitem(sys.modules, "scout_planned_route", module)
    app = FastAPI()

    def project_for(project_id):
        if project_id not in {root.name, "second_fixture"}:
            raise HTTPException(status_code=404, detail="Unknown project")
        path = workspace / project_id
        if not path.is_dir():
            raise HTTPException(status_code=404, detail="Unknown project")
        return path

    app.include_router(create_planned_route_router(project_root_for=project_for), prefix="/admin")
    client = TestClient(app)
    return root, compile_candidate, client


def _request(root, compiler, **updates):
    request = PlannedRouteRequest(human_text="沿 Golden 加支線往返，休息 40 分鐘", departure_at="2026-09-10T06:00:00+08:00", **updates)
    preview = compiler(root, request)
    request = request.model_copy(update={"source_snapshot_sha256": preview["source_snapshot_sha256"]})
    return request, compiler(root, request)


def _save(root, request, preview, key="save.1"):
    return artifacts.save_planned_version(root, artifacts.PlannedSaveRequest(
        request=request, expected_preview_sha256=preview["preview_sha256"], idempotency_key=key, explicit_confirmation=True))


def _review(root, saved, *, key="review.1", acknowledged=None):
    detail = artifacts.get_planned_version(root, saved["version_id"])
    return artifacts.review_planned_version(root, artifacts.PlannedReviewRequest(
        version_id=saved["version_id"], expected_manifest_sha256=saved["manifest_sha256"], reviewer_alias="fixture-human",
        accepted_dimensions=list(artifacts.REVIEW_DIMENSIONS),
        acknowledged_issue_ids=detail["manifest"]["required_issue_ids"] if acknowledged is None else acknowledged,
        idempotency_key=key, explicit_confirmation=True))


def _select(root, saved, **updates):
    return artifacts.select_analysis_subject(root, artifacts.PlannedAnalysisSelectionRequest(
        subject_kind="planned_gpx", version_id=saved["version_id"], expected_manifest_sha256=saved["manifest_sha256"],
        idempotency_key="selection.1", explicit_confirmation=True, **updates))


def test_preview_catalog_and_empty_selection_are_read_only(planned):
    root, compiler, client = planned
    request, preview = _request(root, compiler)
    before = _files(root)
    prefix = f"/admin/pretrip/projects/{root.name}/planned-route"
    assert client.get(prefix + "/catalog").status_code == 200
    response = client.post(prefix + "/preview", json=request.model_dump(mode="json"))
    assert response.status_code == 200, response.text
    assert response.json()["preview_sha256"] == preview["preview_sha256"]
    assert response.json()["review_requirements"]["required_issue_ids"] == ["time.unknown"]
    assert client.get(prefix + "/versions").json()["versions"] == []
    assert client.get(prefix + "/analysis-selection").json()["subject_kind"] == "golden_gpx"
    assert _files(root) == before


def test_save_reload_export_and_same_key_retry_keep_one_complete_version(planned):
    root, compiler, client = planned
    request, preview = _request(root, compiler)
    original = _files(root)
    prefix = f"/admin/pretrip/projects/{root.name}/planned-route"
    body = {"request": request.model_dump(mode="json"), "expected_preview_sha256": preview["preview_sha256"],
            "idempotency_key": "same-save", "explicit_confirmation": True}
    response = client.post(prefix + "/versions", json=body)
    assert response.status_code == 200, response.text
    saved = response.json()
    before_retry = _files(root)
    retry = client.post(prefix + "/versions", json=body).json()
    assert retry["version_id"] == saved["version_id"] and retry["writes_performed"] is False
    assert _files(root) == before_retry
    detail = client.get(prefix + "/versions/" + saved["version_id"]).json()
    assert detail["preview"]["itinerary"] == preview["itinerary"]
    assert detail["review"] is None
    assert len(client.get(prefix + "/versions").json()["versions"]) == 1
    exported = client.get(prefix + f"/export/{saved['version_id']}/bundle")
    assert exported.status_code == 200
    assert exported.headers["x-scout-track-role"] == "planned-candidate"
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["manifest_sha256"] == saved["manifest_sha256"]
        for filename, binding in manifest["files"].items():
            assert _sha(archive.read(filename)) == binding["sha256"]
        assert b"<time>" not in archive.read("planned.gpx")
        assert manifest["recorded_track"] is False
    for ref, sha in original.items():
        assert _sha((root / ref).read_bytes()) == sha


def test_revision_requires_current_parent_and_rejects_conflicting_retry(planned):
    root, compiler, _ = planned
    request, preview = _request(root, compiler)
    first = _save(root, request, preview)
    changed = request.model_copy(update={"human_text": "改成其他行程"})
    new_preview = compiler(root, changed)
    with pytest.raises(PlannedRouteConflict, match="different plan"):
        _save(root, changed, new_preview)
    with pytest.raises(PlannedRouteConflict) as error:
        _save(root, changed, new_preview, key="save.2")
    assert error.value.code == "planned_parent_version_conflict"
    changed = changed.model_copy(update={"parent_version_id": first["version_id"]})
    second = _save(root, changed, compiler(root, changed), key="save.2")
    assert second["parent_version_id"] == first["version_id"]
    assert artifacts.list_planned_versions(root)["head_version_id"] == second["version_id"]


def test_concurrent_saves_have_one_head_and_one_parent_conflict(planned):
    root, compiler, _ = planned
    request, preview = _request(root, compiler)

    def save(key):
        try:
            return _save(root, request, preview, key=key)["version_id"]
        except PlannedRouteConflict as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, ["concurrent.1", "concurrent.2"]))
    assert results.count("planned_parent_version_conflict") == 1
    assert len(artifacts.list_planned_versions(root)["versions"]) == 1


def test_stale_preview_source_and_staging_race_never_publish(planned, monkeypatch):
    root, compiler, _ = planned
    request, preview = _request(root, compiler)
    (root / "source.gpx").write_text("changed source")
    with pytest.raises(PlannedRouteConflict) as error:
        _save(root, request, preview)
    assert error.value.code == "planned_sources_stale"
    assert artifacts.list_planned_versions(root)["versions"] == []
    request, preview = _request(root, compiler)
    original_write = artifacts._write_new

    def source_race(path, data):
        original_write(path, data)
        if path.name == "manifest.json":
            (root / "source.gpx").write_text("source changed while staging")

    monkeypatch.setattr(artifacts, "_write_new", source_race)
    with pytest.raises(PlannedRouteConflict) as error:
        _save(root, request, preview)
    assert error.value.code == "planned_sources_stale"
    assert artifacts.list_planned_versions(root)["head_version_id"] is None
    assert list((root / artifacts.STORE_REF / "versions").glob(".*.pending"))


def test_interrupted_save_keeps_previous_version_and_retry_is_recoverable(planned, monkeypatch):
    root, compiler, _ = planned
    request, preview = _request(root, compiler)
    first = _save(root, request, preview)
    original_files = _files(root / artifacts.STORE_REF / "versions" / first["version_id"])
    revised = request.model_copy(update={"parent_version_id": first["version_id"], "human_text": "新增休息"})
    revised_preview = compiler(root, revised)
    original_write = artifacts._write_new

    def fail_write(path, data):
        if path.name == "route_axis.json":
            raise OSError("injected disk-full write")
        original_write(path, data)

    monkeypatch.setattr(artifacts, "_write_new", fail_write)
    with pytest.raises(OSError, match="disk-full"):
        _save(root, revised, revised_preview, key="save.retry")
    assert artifacts.list_planned_versions(root)["head_version_id"] == first["version_id"]
    assert _files(root / artifacts.STORE_REF / "versions" / first["version_id"]) == original_files
    monkeypatch.setattr(artifacts, "_write_new", original_write)
    final = _save(root, revised, revised_preview, key="save.retry")
    assert final["parent_version_id"] == first["version_id"]
    assert len(artifacts.list_planned_versions(root)["versions"]) == 2


def test_review_requires_all_dimensions_and_current_unknown_acknowledgments(planned):
    root, compiler, _ = planned
    request, preview = _request(root, compiler)
    saved = _save(root, request, preview)
    with pytest.raises(PlannedRouteConflict) as error:
        _select(root, saved)
    assert error.value.code == "planned_review_required"
    with pytest.raises(PlannedRouteConflict) as error:
        _review(root, saved, acknowledged=[])
    assert error.value.code == "planned_review_acknowledgments_incomplete"
    with pytest.raises(ValidationError):
        artifacts.PlannedReviewRequest(version_id=saved["version_id"], expected_manifest_sha256=saved["manifest_sha256"],
            reviewer_alias="test", accepted_dimensions=["geometry"], idempotency_key="bad", explicit_confirmation=True)
    accepted = _review(root, saved)
    files = _files(root)
    retry = _review(root, saved)
    assert retry["review_sha256"] == accepted["review_sha256"]
    assert _files(root) == files
    assert accepted["candidate_only"] is True and accepted["runtime_safety_truth"] is False


def test_planned_selection_exposes_own_branch_graph_timing_and_coverage_gaps(planned):
    root, compiler, _ = planned
    original = _files(root)
    golden = build_analysis_subject(root)
    request, preview = _request(root, compiler)
    saved = _save(root, request, preview)
    _review(root, saved)
    selected = _select(root, saved)
    subject = build_analysis_subject(root)
    assert subject.subject_kind == "planned_gpx"
    assert subject.selected_plan_version_id == saved["version_id"]
    assert subject.schedule_time_role == "planned_estimate"
    assert subject.checkpoints == preview["checkpoints"]
    assert subject.segments == preview["segments"]
    assert subject.itinerary == preview["itinerary"]
    assert subject.planned_route_geojson == preview["route_geojson"]
    assert subject.checkpoints[1]["lat"] == subject.checkpoints[3]["lat"]
    assert subject.checkpoints[1]["checkpoint_id"] != subject.checkpoints[3]["checkpoint_id"]
    assert subject.dependencies["permission"]["status"] == "current_planned_candidate"
    assert subject.dependencies["pace_fit"]["status"] == "current_planned_candidate"
    assert subject.dependencies["navigation"]["status"] == "coverage_needed"
    assert subject.dependencies["architecture"]["status"] == "needs_reanalysis"
    assert subject.dependencies["weather"]["historical_weather_status"] == "unknown"
    assert subject.departure_approval_granted is False
    artifacts.select_analysis_subject(root, artifacts.PlannedAnalysisSelectionRequest(
        subject_kind="golden_gpx", expected_selection_sha256=selected["selection_sha256"],
        idempotency_key="back-to-golden", explicit_confirmation=True))
    assert build_analysis_subject(root) == golden
    for ref, sha in original.items():
        assert _sha((root / ref).read_bytes()) == sha


def test_project_switch_never_reuses_another_projects_version(planned):
    root, compiler, client = planned
    request, preview = _request(root, compiler)
    saved = _save(root, request, preview)
    other = root.parent / "second_fixture"
    other.mkdir()
    _json(other / "project.json", {"project_id": other.name})
    assert artifacts.list_planned_versions(other)["versions"] == []
    response = client.get(f"/admin/pretrip/projects/{other.name}/planned-route/versions/{saved['version_id']}")
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "planned_artifact_missing"
    assert artifacts.get_planned_version(root, saved["version_id"])["manifest"]["project_id"] == root.name


def test_tampered_plan_or_review_cannot_claim_current_or_runtime_authority(planned):
    root, compiler, _ = planned
    request, preview = _request(root, compiler)
    saved = _save(root, request, preview)
    review = _review(root, saved)
    _select(root, saved)
    review_path = root / review["review_ref"]
    forged = json.loads(review_path.read_text())
    forged["runtime_safety_truth"] = True
    forged.pop("review_sha256")
    forged = artifacts._signed(forged, "review_sha256")
    _json(review_path, forged)
    subject = build_analysis_subject(root)
    assert subject.schedule_status == "blocked" and subject.subject_kind == "unresolved_selection"
    assert subject.issues == ["planned_authority_mismatch"]
    assert subject.runtime_safety_truth is False
    with pytest.raises(PlannedRouteConflict):
        artifacts.get_planned_version(root, saved["version_id"])


def test_changed_source_invalidates_selected_plan_without_reverting_to_golden(planned):
    root, compiler, _ = planned
    request, preview = _request(root, compiler)
    saved = _save(root, request, preview)
    _review(root, saved)
    _select(root, saved)
    (root / "source.gpx").write_text("new GPX revision")
    subject = build_analysis_subject(root)
    assert subject.subject_kind == "planned_gpx" and subject.schedule_status == "stale"
    assert subject.mission_day_estimates == []
    assert subject.dependencies["permission"]["status"] == "needs_reanalysis"
    assert artifacts.get_planned_version(root, saved["version_id"])["source_status"]["changed_refs"] == ["source.gpx"]


def test_selection_occ_and_partial_publication_recovery(planned, monkeypatch):
    root, compiler, _ = planned
    request, preview = _request(root, compiler)
    saved = _save(root, request, preview)
    _review(root, saved)
    original_atomic = artifacts._atomic_json

    def interrupt_pointer(root, ref, value):
        if ref.endswith("/analysis_selection.json"):
            raise OSError("injected pointer interruption")
        original_atomic(root, ref, value)

    monkeypatch.setattr(artifacts, "_atomic_json", interrupt_pointer)
    with pytest.raises(OSError, match="pointer interruption"):
        _select(root, saved)
    assert artifacts.get_analysis_selection(root)["subject_kind"] == "golden_gpx"
    monkeypatch.setattr(artifacts, "_atomic_json", original_atomic)
    selection = _select(root, saved)
    assert selection["replayed"] is True
    with pytest.raises(PlannedRouteConflict) as error:
        artifacts.select_analysis_subject(root, artifacts.PlannedAnalysisSelectionRequest(
            subject_kind="golden_gpx", idempotency_key="wrong-predecessor", explicit_confirmation=True))
    assert error.value.code == "planned_selection_conflict"
    before = _files(root)
    retry = _select(root, saved)
    assert retry["selection_sha256"] == selection["selection_sha256"]
    assert _files(root) == before


def test_file_tamper_path_traversal_and_authority_payload_are_rejected(planned):
    root, compiler, client = planned
    request, preview = _request(root, compiler)
    prefix = f"/admin/pretrip/projects/{root.name}/planned-route"
    body = {"request": request.model_dump(mode="json"), "expected_preview_sha256": preview["preview_sha256"],
            "idempotency_key": "bad-authority", "explicit_confirmation": True, "runtime_safety_truth": True}
    assert client.post(prefix + "/versions", json=body).status_code == 422
    with pytest.raises(PlannedRouteConflict):
        artifacts.get_planned_version(root, "../../elsewhere")
    saved = _save(root, request, preview)
    path = root / artifacts.STORE_REF / "versions" / saved["version_id"] / "itinerary.json"
    path.write_text('{"recorded_track":true}')
    with pytest.raises(PlannedRouteConflict) as error:
        artifacts.export_planned_version(root, saved["version_id"], "gpx")
    assert error.value.code == "planned_bundle_hash_mismatch"


def test_source_and_store_symlink_escape_are_rejected(planned, tmp_path):
    root, compiler, _ = planned
    outside = tmp_path / "outside"
    outside.mkdir()
    # The source verifier refuses a symlink even when it happens to resolve to
    # a readable file. No outside bytes are copied into a bundle.
    (outside / "source.gpx").write_text("external source")
    (root / "source-link.gpx").symlink_to(outside / "source.gpx")
    assert artifacts._source_status(root, {"source-link.gpx": _sha(b"external source")})["status"] == "stale"
    request, preview = _request(root, compiler)
    (root / "reviews/planned_routes").symlink_to(outside, target_is_directory=True)
    with pytest.raises(PlannedRouteConflict) as error:
        _save(root, request, preview)
    assert error.value.code == "invalid_planned_ref"
    assert list(outside.iterdir()) == [outside / "source.gpx"]


def _mock_map_fetch(monkeypatch):
    import scout_planned_route_sources
    calls = []
    prefix = "normalized/map/planned-overpass/" + "a" * 64
    raw_ref, ref = prefix + "/overpass_raw.json", prefix + "/overpass_vector_evidence.geojson"
    files = {raw_ref: b'{"elements":[]}', ref: b'{"type":"FeatureCollection","features":[]}'}
    hashes = {path: _sha(data) for path, data in files.items()}
    binding = {"ref": ref, "sha256": hashes[ref], "raw_ref": raw_ref, "raw_sha256": hashes[raw_ref]}

    def fetch(bbox):
        calls.append(bbox)
        return {"files": files, "source_hashes": hashes, "project_binding": binding, "query": "fixed endpoint bbox query",
                "candidate_only": True, "runtime_safety_truth": False}

    monkeypatch.setattr(scout_planned_route_sources, "fetch_trail_source_candidates", fetch)
    return calls, files, binding


def test_public_trail_source_query_is_idempotent_and_only_appends_its_binding(planned, monkeypatch):
    root, compiler, client = planned
    calls, files, binding = _mock_map_fetch(monkeypatch)
    request, preview = _request(root, compiler)
    original = json.loads((root / "project.json").read_text())
    prefix = f"/admin/pretrip/projects/{root.name}/planned-route"
    body = {"bbox": {"south": 23, "west": 121, "north": 23.1, "east": 121.1},
            "idempotency_key": "fetch.same", "explicit_confirmation": True}
    response = client.post(prefix + "/sources/overpass", json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "candidate_sources_saved"
    assert result["project_binding"] == binding
    after = _files(root)
    repeated = client.post(prefix + "/sources/overpass", json=body)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["writes_performed"] is False
    assert len(calls) == 1 and _files(root) == after
    project = json.loads((root / "project.json").read_text())
    assert project.pop("planned_overpass_source_refs") == [binding]
    assert project == original
    for ref, data in files.items():
        assert (root / ref).read_bytes() == data
    with pytest.raises(PlannedRouteConflict) as error:
        _save(root, request, preview)
    assert error.value.code == "planned_sources_stale"
    altered = {**body, "bbox": {**body["bbox"], "east": 122}}
    assert client.post(prefix + "/sources/overpass", json=altered).json()["detail"]["code"] == "planned_idempotency_conflict"
    assert len(calls) == 1
    assert client.post(prefix + "/sources/overpass", json={**body, "url": "https://untrusted.invalid"}).status_code == 422


def test_trail_source_partial_write_never_publishes_or_changes_project(planned, monkeypatch):
    root, _, _ = planned
    calls, files, _ = _mock_map_fetch(monkeypatch)
    original_project = (root / "project.json").read_bytes()
    write = artifacts._write_new

    def fail_vector(path, data):
        if path.name == "overpass_vector_evidence.geojson":
            raise OSError("injected source disk-full")
        write(path, data)

    monkeypatch.setattr(artifacts, "_write_new", fail_vector)
    request = artifacts.PlannedTrailSourceRequest(bbox={"south": 23, "west": 121, "north": 24, "east": 122},
                                                 idempotency_key="fetch.retry", explicit_confirmation=True)
    with pytest.raises(OSError, match="source disk-full"):
        artifacts.acquire_planned_trail_sources(root, request)
    assert (root / "project.json").read_bytes() == original_project
    assert all(not (root / ref).exists() for ref in files)
    assert artifacts.list_planned_versions(root)["versions"] == []


def test_trail_source_binding_publication_resumes_without_fetching_again(planned, monkeypatch):
    root, _, _ = planned
    calls, _, binding = _mock_map_fetch(monkeypatch)
    atomic = artifacts._atomic_json

    def fail_project(root, ref, value):
        if ref == "project.json":
            raise OSError("injected project pointer interruption")
        atomic(root, ref, value)

    monkeypatch.setattr(artifacts, "_atomic_json", fail_project)
    request = artifacts.PlannedTrailSourceRequest(bbox={"south": 23, "west": 121, "north": 24, "east": 122},
                                                 idempotency_key="fetch.resume", explicit_confirmation=True)
    with pytest.raises(OSError, match="pointer interruption"):
        artifacts.acquire_planned_trail_sources(root, request)
    assert "planned_overpass_source_refs" not in json.loads((root / "project.json").read_text())
    monkeypatch.setattr(artifacts, "_atomic_json", atomic)
    result = artifacts.acquire_planned_trail_sources(root, request)
    assert result["replayed"] is True and result["writes_performed"] is True
    assert len(calls) == 1
    assert json.loads((root / "project.json").read_text())["planned_overpass_source_refs"] == [binding]


def test_bundle_coherence_and_export_read_race_are_checked(planned, monkeypatch):
    root, compiler, _ = planned
    request, preview = _request(root, compiler)
    saved = _save(root, request, preview)
    prefix = root / artifacts.STORE_REF / "versions" / saved["version_id"]
    manifest = json.loads((prefix / "manifest.json").read_text())
    altered_itinerary = b'{"days":[],"time_role":"recorded"}'
    (prefix / "itinerary.json").write_bytes(altered_itinerary)
    manifest["files"]["itinerary.json"] = {"sha256": _sha(altered_itinerary), "bytes": len(altered_itinerary)}
    manifest.pop("manifest_sha256")
    _json(prefix / "manifest.json", artifacts._signed(manifest, "manifest_sha256"))
    with pytest.raises(PlannedRouteConflict) as error:
        artifacts.get_planned_version(root, saved["version_id"])
    assert error.value.code == "planned_bundle_binding_mismatch"
    # Restore this isolated fault fixture, then inject a mutation between the
    # bundle validation read and the export read.
    original_itinerary = artifacts.canonical_bytes(preview["itinerary"])
    (prefix / "itinerary.json").write_bytes(original_itinerary)
    manifest["files"]["itinerary.json"] = {"sha256": _sha(original_itinerary), "bytes": len(original_itinerary)}
    _json(prefix / "manifest.json", artifacts._signed(manifest, "manifest_sha256"))
    read_bytes = artifacts._read_bytes
    gpx_reads = 0

    def change_during_export(root, ref):
        nonlocal gpx_reads
        if ref.endswith("/planned.gpx"):
            gpx_reads += 1
            if gpx_reads == 2:
                return b"a different GPX revision"
        return read_bytes(root, ref)

    monkeypatch.setattr(artifacts, "_read_bytes", change_during_export)
    with pytest.raises(PlannedRouteConflict) as error:
        artifacts.export_planned_version(root, saved["version_id"], "gpx")
    assert error.value.code == "planned_export_changed"


def test_real_gpx_compiler_through_registered_api_save_review_select_and_export(tmp_path):
    from scout_contextual_permission_workbench_api import create_contextual_permission_workbench_router
    from test_scout_planned_route import planned_workspace

    root = planned_workspace(tmp_path)
    original = _files(root)
    app = FastAPI()
    app.include_router(create_contextual_permission_workbench_router(
        pretrip_workspace_root=root.parent, store_root=tmp_path / "permission_store"), prefix="/admin")
    client = TestClient(app)
    prefix = f"/admin/pretrip/projects/{root.name}/planned-route"
    catalog = client.get(prefix + "/catalog").json()
    request = {"human_text": "從營地 A 單攻山頭 B 後回營地 A；在山頭 B 停留 40 分鐘",
               "departure_at": "2026-10-01T06:00:00+08:00", "default_speed_kmh": 2,
               "source_snapshot_sha256": catalog["source_snapshot_sha256"]}
    response = client.post(prefix + "/preview", json=request)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["comparison"]["geometry_changed"] is True
    assert preview["itinerary"]["days"][0]["fixed_rest_minutes"] == 40
    save = client.post(prefix + "/versions", json={"request": request,
        "expected_preview_sha256": preview["preview_sha256"], "idempotency_key": "real-source-save", "explicit_confirmation": True})
    assert save.status_code == 200, save.text
    saved = save.json()
    review = client.post(prefix + "/review", json={"version_id": saved["version_id"],
        "expected_manifest_sha256": saved["manifest_sha256"], "reviewer_alias": "real-source-fixture-reviewer",
        "accepted_dimensions": list(artifacts.REVIEW_DIMENSIONS),
        "acknowledged_issue_ids": preview["review_requirements"]["required_issue_ids"],
        "idempotency_key": "real-source-review", "explicit_confirmation": True})
    assert review.status_code == 200, review.text
    selected = client.post(prefix + "/analysis-selection", json={"subject_kind": "planned_gpx", "version_id": saved["version_id"],
        "expected_manifest_sha256": saved["manifest_sha256"], "expected_selection_sha256": None,
        "idempotency_key": "real-source-selection", "explicit_confirmation": True})
    assert selected.status_code == 200, selected.text
    subject = client.get(f"/admin/pretrip/projects/{root.name}/analysis-subject").json()
    assert subject["subject_kind"] == "planned_gpx"
    assert subject["route_axis"] == preview["route_axis"]
    assert subject["itinerary"] == preview["itinerary"]
    assert subject["checkpoints"] == preview["checkpoints"]
    assert subject["day_segment_mapping"][0]["segment_ids"] == [row["segment_id"] for row in preview["segments"]]
    assert subject["dependencies"]["permission"]["status"] == "current_planned_candidate"
    assert subject["dependencies"]["navigation"]["status"] == "coverage_needed"
    candidate = json.loads((root / subject["selected_baseline_ref"]).read_text())
    assert candidate["days"][0]["segment_ids"] == subject["day_segment_mapping"][0]["segment_ids"]
    assert candidate["route_axis_validation"]["golden_graph_activation"] == "blocked"
    exported = client.get(prefix + f"/export/{saved['version_id']}/bundle")
    assert exported.status_code == 200, exported.text
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        assert archive.read("planned.gpx").decode() == preview["planned_gpx"]
        assert json.loads(archive.read("itinerary.json")) == preview["itinerary"]
        assert b'role="planned"' in archive.read("planned.gpx")
        assert b"<time>" not in archive.read("planned.gpx")
    for ref, sha in original.items():
        assert _sha((root / ref).read_bytes()) == sha
