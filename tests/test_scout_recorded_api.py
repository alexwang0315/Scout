"""Exercise the mounted Recorded HTTP boundary; GIS uses explicit test seams."""
from __future__ import annotations

import copy
import hashlib
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

import scout_recorded_api
import scout_recorded_jobs
from scout_contextual_permission_workbench_api import create_contextual_permission_workbench_router
from scout_planned_analysis import ROLES
from scout_planned_route_artifacts import STORE_REF as PLANNED_STORE
from test_scout_recorded_analysis import recorded, _files
from test_scout_recorded_jobs import _manager


@pytest.fixture
def http(recorded, monkeypatch, tmp_path):
    root, payload = recorded
    payload = copy.deepcopy(payload)
    # These HTTP fixtures were generated, not observations of a user's activity.
    for item in payload["recordings"]:
        item["observation_kind"] = "fixture_replay"
    monkeypatch.setenv("SCOUT_PLANNED_PREPARATION_LOCK_ROOT", str(tmp_path / "http-job-slots"))
    managers = {}

    def manager_for(project_root):
        if project_root not in managers:
            managers[project_root] = _manager(project_root)
        return managers[project_root]

    monkeypatch.setattr(scout_recorded_api, "RecordedAnalysisManager", manager_for)
    monkeypatch.setattr(scout_recorded_jobs, "RecordedAnalysisManager", manager_for)
    app = FastAPI()
    app.include_router(create_contextual_permission_workbench_router(
        pretrip_workspace_root=root.parent, store_root=tmp_path / "permission-store"), prefix="/admin")
    with TestClient(app, raise_server_exceptions=False) as client:
        yield SimpleNamespace(root=root, payload=payload, client=client, managers=managers,
            base=f"/admin/pretrip/projects/{root.name}/recorded-analysis",
            subject=f"/admin/pretrip/projects/{root.name}/analysis-subject",
            selection=f"/admin/pretrip/projects/{root.name}/planned-route/analysis-selection")


def _save(http, payload=None):
    response = http.client.post(http.base + "/versions", json=payload or http.payload)
    assert response.status_code == 200, response.text
    return response.json()


def _select(http, bundle, key="http.select"):
    selection = http.client.get(http.selection).json()
    manifest = bundle["manifest"]
    return http.client.post(http.base + "/selection", json={
        "subject_kind": "recorded_gpx", "version_id": manifest["version_id"],
        "expected_manifest_sha256": manifest["manifest_sha256"],
        "expected_selection_sha256": selection["selection_sha256"],
        "idempotency_key": key, "explicit_confirmation": True})


def _submit(http, bundle, key="http.run"):
    return http.client.post(http.base + "/analysis-runs", json={
        "version_id": bundle["manifest"]["version_id"],
        "expected_manifest_sha256": bundle["manifest"]["manifest_sha256"],
        "idempotency_key": key, "explicit_confirmation": True})


def test_http_upload_multiple_days_keeps_original_bytes_and_member_device_provenance(http):
    before = _files(http.root)
    payload = copy.deepcopy(http.payload)
    for item in payload["recordings"]:
        source = http.root / item["source_ref"]
        raw = source.read_bytes()
        request = {"file_name": source.name, "content": raw.decode("utf-8")}
        response = http.client.post(http.base + "/sources", json=request)
        assert response.status_code == 200, response.text
        uploaded = response.json()
        assert uploaded["sha256"] == hashlib.sha256(raw).hexdigest()
        assert (http.root / uploaded["source_ref"]).read_bytes() == raw
        assert uploaded["source_bytes_preserved"]
        after_first = _files(http.root)
        assert http.client.post(http.base + "/sources", json=request).json() == uploaded
        assert _files(http.root) == after_first
        item.update(source_ref=uploaded["source_ref"], expected_sha256=uploaded["sha256"])
    bundle = _save(http, payload)
    actual = bundle["preview"]["recordings"]
    assert [(r["member_id"], r["device_id"], r["role"]) for r in actual] == [
        ("alice", "phone", "primary"), ("alice", "phone", "primary"),
        ("alice", "watch", "backup"), ("bob", "watch", "member_context")]
    assert len(bundle["preview"]["itinerary"]["days"]) == 2
    assert len(bundle["preview"]["route_axis"]) == 97
    assert bundle["manifest"]["source_times_role"] == "fixture_replay_time"
    assert bundle["manifest"]["actual_user_recorded_activity"] is False
    assert all(_files(http.root)[ref] == sha for ref, sha in before.items())


def test_http_save_restore_select_and_read_endpoints_do_not_mutate_versions(http):
    first = _save(http)
    first_bytes = _files(http.root / first["bundle_ref"])
    assert _save(http)["replayed"]
    revised = {**http.payload, "label": "Second immutable replay", "idempotency_key": "http.second"}
    second = _save(http, revised)
    assert first["manifest"]["version_id"] != second["manifest"]["version_id"]
    for index, bundle in enumerate((second, first)):
        restored = http.client.get(http.base + "/versions/" + bundle["manifest"]["version_id"])
        assert restored.status_code == 200 and restored.json()["manifest"] == bundle["manifest"]
        selected = _select(http, restored.json(), f"restore.{index}")
        assert selected.status_code == 200, selected.text
        assert selected.json()["subject_kind"] == "recorded_gpx"
        assert selected.json()["recorded_track"]
        assert http.client.get(http.selection).json()["selection_sha256"] == selected.json()["selection_sha256"]
        subject = http.client.get(http.subject)
        assert subject.status_code == 200, subject.text
        subject = subject.json()
        assert subject["recorded_version_id"] == bundle["manifest"]["version_id"]
        assert subject["schedule_time_role"] == "fixture_replay_time"
        assert len(subject["route_axis"]) == 97
        assert subject["actual_user_recorded_activity"] is False
        assert set(subject["comparison"]) >= {"golden", "planned"}
        assert all(v["status"] == "needs_reanalysis" for v in subject["dependencies"].values())
    before_reads = _files(http.root)
    for path in (http.base + "/sources", http.base + "/versions", http.base + "/analysis-runs",
                 http.base + "/versions/" + first["manifest"]["version_id"], http.subject, http.selection):
        response = http.client.get(path)
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
    for format, filename in (("gpx", "recorded.gpx"), ("manifest", "manifest.json"), ("comparison", "comparison.json")):
        response = http.client.get(http.base + "/export/" + first["manifest"]["version_id"] + "/" + format)
        assert response.status_code == 200, response.text
        assert response.content == (http.root / first["bundle_ref"] / filename).read_bytes()
        assert response.headers["x-scout-track-role"] == "recorded"
        assert response.headers["cache-control"] == "no-store"
    assert _files(http.root) == before_reads
    assert _files(http.root / first["bundle_ref"]) == first_bytes


def test_http_durable_run_six_bindings_download_resume_and_subject_admission(http):
    bundle = _save(http)
    assert _select(http, bundle).status_code == 200
    response = _submit(http, bundle)
    assert response.status_code == 202, response.text
    state = response.json()
    assert state["status"] == "completed_with_gaps", state
    assert set(state["projections"]) == set(ROLES)
    assert state["binding"]["kind"] == "recorded_gpx"
    assert "review_sha256" not in state["binding"]
    assert state["binding"]["source_times_role"] == "fixture_replay_time"
    original_attempt = _files(http.root / state["report_ref"].split("/reports/")[0] / "attempts/0001")
    before_reads = _files(http.root)
    same = _submit(http, bundle).json()
    assert same["run_id"] == state["run_id"]
    response = http.client.get(http.base + "/analysis-runs", params={"version_id": bundle["manifest"]["version_id"]})
    assert response.json()["runs"][0]["run_id"] == state["run_id"]
    read = http.client.get(http.base + "/analysis-runs/" + state["run_id"])
    assert read.json()["report_sha256"] == state["report_sha256"]
    artifact = state["projections"]["navigation"]
    downloaded = http.client.get(http.base + "/analysis-runs/" + state["run_id"] + "/artifact", params={"ref": artifact["artifact_ref"]})
    assert downloaded.status_code == 200
    assert hashlib.sha256(downloaded.content).hexdigest() == artifact["artifact_sha256"]
    subject = http.client.get(http.subject).json()
    assert subject["dependencies"]["weather"]["status"] == "partial_recorded_analysis"
    assert subject["dependencies"]["navigation"]["status"] == "current_recorded_analysis"
    assert subject["dependencies"]["weather"]["current_forecast_status"] == "not_evidence_of_recorded_weather"
    assert subject["recorded_analysis"]["run_id"] == state["run_id"]
    assert _files(http.root) == before_reads
    resumed = http.client.post(http.base + "/analysis-runs/" + state["run_id"] + "/resume", json={
        "expected_manifest_sha256": bundle["manifest"]["manifest_sha256"],
        "idempotency_key": "http.resume", "explicit_confirmation": True})
    assert resumed.status_code == 202, resumed.text
    assert resumed.json()["attempt"] == 2
    assert resumed.json()["run_id"] == state["run_id"]
    assert _files(http.root / state["report_ref"].split("/reports/")[0] / "attempts/0001") == original_attempt


def test_http_interrupted_get_does_not_resume_and_wrong_version_resume_is_rejected(http):
    bundle = _save(http)
    manager = scout_recorded_api.RecordedAnalysisManager(http.root)
    start = manager._start
    manager._start = lambda run_id, lease: manager._release(lease)
    response = _submit(http, bundle)
    assert response.status_code == 202, response.text
    state = response.json()
    assert state["status"] == "interrupted" and state["can_resume"]
    before_reads = _files(http.root)
    assert http.client.get(http.base + "/analysis-runs/" + state["run_id"]).json()["status"] == "interrupted"
    assert _files(http.root) == before_reads
    manager._start = start
    request = {"expected_manifest_sha256": "0" * 64, "idempotency_key": "http.recover", "explicit_confirmation": True}
    rejected = http.client.post(http.base + "/analysis-runs/" + state["run_id"] + "/resume", json=request)
    assert rejected.status_code == 409
    request["expected_manifest_sha256"] = bundle["manifest"]["manifest_sha256"]
    resumed = http.client.post(http.base + "/analysis-runs/" + state["run_id"] + "/resume", json=request)
    assert resumed.status_code == 202, resumed.text
    assert resumed.json()["attempt"] == 2 and resumed.json()["status"] == "completed_with_gaps"


def test_http_source_drift_and_projection_tampering_never_admit_old_six_forces(http):
    bundle = _save(http)
    assert _select(http, bundle).status_code == 200
    state = _submit(http, bundle).json()
    projection = http.root / state["projections"]["navigation"]["artifact_ref"]
    projection.write_text('{"tampered":true}')
    before_reads = _files(http.root)
    observed = http.client.get(http.base + "/analysis-runs/" + state["run_id"]).json()
    assert observed["status"] == "stale" and observed["projections"] == {}
    subject = http.client.get(http.subject).json()
    assert all(v["status"] == "needs_reanalysis" for v in subject["dependencies"].values())
    blocked = http.client.get(http.base + "/analysis-runs/" + state["run_id"] + "/artifact", params={"ref": projection.relative_to(http.root).as_posix()})
    assert blocked.status_code == 409
    assert _files(http.root) == before_reads
    source = http.root / http.payload["recordings"][0]["source_ref"]
    source.write_text(source.read_text().replace("121.002", "121.0021"))
    assert _select(http, bundle, "stale.select").status_code == 409
    assert _submit(http, bundle, "stale.run").status_code == 409
    subject = http.client.get(http.subject).json()
    assert subject["schedule_status"] == "stale"
    assert all(v["status"] == "needs_reanalysis" for v in subject["dependencies"].values())


@pytest.mark.parametrize("part", ["manifest", "canonical_file"])
def test_http_immutable_tamper_returns_conflict_and_blocks_selected_subject(http, part):
    bundle = _save(http)
    assert _select(http, bundle).status_code == 200
    path = http.root / bundle["bundle_ref"] / ("manifest.json" if part == "manifest" else "recorded.gpx")
    if part == "manifest":
        value = json.loads(path.read_bytes())
        value["runtime_safety_truth"] = True
        path.write_text(json.dumps(value))
    else:
        path.write_bytes(path.read_bytes() + b"\n")
    before_reads = _files(http.root)
    assert http.client.get(http.base + "/versions/" + bundle["manifest"]["version_id"]).status_code == 409
    assert http.client.get(http.base + "/export/" + bundle["manifest"]["version_id"] + "/gpx").status_code == 409
    subject = http.client.get(http.subject)
    assert subject.status_code == 200, subject.text
    assert subject.json()["subject_kind"] == "unresolved_selection"
    assert all(v["status"] == "needs_reanalysis" for v in subject.json()["dependencies"].values())
    assert _files(http.root) == before_reads


def test_http_synthetic_planned_xml_cannot_be_uploaded_as_actual(http):
    planned = http.root / PLANNED_STORE / "versions" / http.payload["planned_version_id"] / "planned.gpx"
    before = _files(http.root)
    response = http.client.post(http.base + "/sources", json={"file_name": "pretend-actual.gpx", "content": planned.read_text()})
    assert response.status_code == 409, response.text
    assert "planned" in response.json()["detail"]["code"]
    assert _files(http.root) == before


@pytest.mark.parametrize("name,content", [
    ("../escape.gpx", "<gpx/>"), ("folder\\escape.gpx", "<gpx/>"),
    ("recorded.xml", "<gpx/>"), (".recorded.gpx", "<gpx/>"),
    ("broken.gpx", "<gpx"),
    ("entity.gpx", '<!DOCTYPE gpx [<!ENTITY x SYSTEM "file:///unavailable">]><gpx>&x;</gpx>'),
])
def test_http_upload_rejects_invalid_filenames_and_untrusted_xml_without_writes(http, name, content):
    before = _files(http.root)
    response = http.client.post(http.base + "/sources", json={"file_name": name, "content": content})
    assert response.status_code in {409, 422}, response.text
    assert _files(http.root) == before


def test_http_project_mismatch_selection_cas_and_artifact_paths_fail_closed(http):
    before = _files(http.root)
    payload = {**http.payload, "project_id": "different-project"}
    assert http.client.post(http.base + "/versions", json=payload).status_code == 409
    assert http.client.get(http.base.replace(http.root.name, "missing-project") + "/versions").status_code == 404
    assert _files(http.root) == before
    bundle = _save(http)
    selection = _select(http, bundle)
    assert selection.status_code == 200
    stale_cas = {"subject_kind": "golden_gpx", "version_id": None,
                 "expected_manifest_sha256": None, "expected_selection_sha256": None,
                 "idempotency_key": "old.selection", "explicit_confirmation": True}
    assert http.client.post(http.base + "/selection", json=stale_cas).status_code == 409
    state = _submit(http, bundle).json()
    for ref in ("project.json", "../../project.json", "/etc/passwd", "reviews/planned_routes/analysis_selection.json"):
        response = http.client.get(http.base + "/analysis-runs/" + state["run_id"] + "/artifact", params={"ref": ref})
        assert response.status_code == 422, response.text
    bad_run = {"version_id": bundle["manifest"]["version_id"], "expected_manifest_sha256": bundle["manifest"]["manifest_sha256"], "idempotency_key": "unconfirmed", "explicit_confirmation": False}
    assert http.client.post(http.base + "/analysis-runs", json=bad_run).status_code == 422


def test_http_missing_recorded_version_is_a_structured_error(http):
    before = _files(http.root)
    response = http.client.get(http.base + "/versions/recorded." + "e" * 24)
    assert response.status_code in {404, 409}, response.text
    assert response.json()["detail"]["code"]
    assert _files(http.root) == before


@pytest.mark.parametrize("damage", ["missing", "invalid_json", "missing_canonical"])
def test_http_damaged_selected_bundle_is_blocked_without_falling_back_to_golden(http, damage):
    bundle = _save(http)
    assert _select(http, bundle).status_code == 200
    path = http.root / bundle["bundle_ref"] / "manifest.json"
    if damage == "missing_canonical":
        path = path.parent / "recorded.gpx"
        path.rename(path.with_suffix(".unavailable"))
    elif damage == "missing":
        path.rename(path.with_suffix(".unavailable"))
    else:
        path.write_text("{broken")
    response = http.client.get(http.subject)
    assert response.status_code == 200, response.text
    assert response.json()["subject_kind"] == "unresolved_selection"
    assert all(v["status"] == "needs_reanalysis" for v in response.json()["dependencies"].values())
