"""Durable preparation receipts cannot promote another plan or old outputs."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import threading
import time

import pytest

from scout_planned_analysis import (
    PlannedAnalysisManager, PlannedAnalysisResumeRequest, PlannedAnalysisRunRequest,
    ROLES, file_sha, planned_binding,
)
from scout_planned_route_artifacts import canonical_bytes, get_planned_version
from scout_planned_route_models import PlannedRouteConflict
from scout_analysis_subject import build_analysis_subject
from test_scout_planned_route_artifacts import planned, _request, _save, _review, _select, _files


def _setup(planned, monkeypatch):
    monkeypatch.delenv("SCOUT_PLANNED_ANALYSIS_REMOTE_CONFIG", raising=False)
    root, compiler, client = planned
    request, preview = _request(root, compiler)
    saved = _save(root, request, preview)
    _review(root, saved)
    _select(root, saved)
    return root, client, saved


def _request_run(saved, key="analysis.one"):
    return PlannedAnalysisRunRequest(version_id=saved["version_id"],
                                    expected_manifest_sha256=saved["manifest_sha256"],
                                    idempotency_key=key, explicit_confirmation=True)


def _prepare(root, bundle, run_root, *, progress):
    payload = {"status": "completed", "subject_binding": planned_binding(bundle),
               "coverage": {"status": "verified", "planned_point_count": 5},
               "candidate_only": True, "runtime_safety_truth": False}
    (run_root / "map.json").write_bytes(canonical_bytes(payload))
    progress({"stage": "terrain", "status": "completed", "part_index": 0})
    return payload


def _analyse(root, bundle, run_root, prepared, *, progress):
    projections = {}
    for role in ROLES:
        result = {"role": role, "status": "partial" if role == "weather" else "ready",
                  "input_binding": planned_binding(bundle), "summary": f"{role} recomputed",
                  "missing_inputs": [{"code": "forecast_window"}] if role == "weather" else [],
                  "candidate_only": True, "runtime_safety_truth": False}
        path = run_root / f"{role}.json"
        path.write_bytes(canonical_bytes(result))
        projections[role] = {**result, "artifact_ref": path.name, "artifact_sha256": file_sha(path)}
    return {"projections": projections}


def _manager(root, **kwargs):
    return PlannedAnalysisManager(root, prepare=kwargs.get("prepare", _prepare),
                                  analyse=kwargs.get("analyse", _analyse), launch=lambda callback: callback())


def test_run_reload_same_key_and_subject_admit_only_matching_receipts(planned, monkeypatch):
    root, client, saved = _setup(planned, monkeypatch)
    before = _files(root)
    manager = _manager(root)
    run = manager.submit(_request_run(saved))
    assert run["status"] == "completed_with_gaps", run
    assert run["can_resume"] and len(run["projections"]) == 6
    assert run["preparation"]["coverage"]["planned_point_count"] == 5
    after = _files(root)
    assert all(after[ref] == value for ref, value in before.items())
    assert manager.submit(_request_run(saved))["run_id"] == run["run_id"]
    reloaded = _manager(root).get(run["run_id"])
    assert reloaded["artifact_sha256"] == run["artifact_sha256"]
    assert _files(root) == after  # every GET and same-key replay remained read-only
    subject = build_analysis_subject(root)
    assert subject.dependencies["architecture"]["status"] == "current_planned_analysis"
    assert subject.dependencies["weather"]["status"] == "partial_planned_analysis"
    assert subject.planned_analysis["binding"]["geometry_sha256"] == saved["geometry_sha256"]
    data, name = manager.artifact(run["run_id"], run["projections"]["architecture"]["artifact_ref"])
    assert name == "architecture.json" and json.loads(data)["summary"] == "architecture recomputed"
    with pytest.raises(PlannedRouteConflict):
        manager.artifact(run["run_id"], "project.json")


def test_tampered_preparation_output_is_not_presented_as_current(planned, monkeypatch):
    root, _, saved = _setup(planned, monkeypatch)
    manager = _manager(root)
    run = manager.submit(_request_run(saved))
    directory = root / run["report_ref"]
    report = json.loads(directory.read_text())
    map_ref = next(ref for ref in report["output_hashes"] if ref.endswith("/map.json"))
    (root / map_ref).write_text('{"other_route":true}')
    state = manager.get(run["run_id"])
    assert state["status"] == "stale" and not state["projections"]
    subject = build_analysis_subject(root)
    assert subject.planned_analysis["projections"] == {}
    assert subject.dependencies["navigation"]["status"] != "current_planned_analysis"


@pytest.mark.parametrize("change_before_publication", [False, True])
def test_compact_projection_retains_owner_inputs_from_full_artifact(planned, monkeypatch, change_before_publication):
    root, _, saved = _setup(planned, monkeypatch)
    source = root / "team-status.json"
    source.write_text('{"load_kg":8}')
    original_sha = file_sha(source)

    def compact(*args, **kwargs):
        result = _analyse(*args, **kwargs)
        projection = result["projections"]["pace_fit"]
        artifact = args[2] / projection["artifact_ref"]
        payload = json.loads(artifact.read_text())
        payload["source_report"] = [{"scope": "owner", "ref": source.name, "sha256": original_sha}]
        artifact.write_bytes(canonical_bytes(payload))
        projection["artifact_sha256"] = file_sha(artifact)
        assert "source_report" not in projection
        if change_before_publication:
            source.write_text('{"load_kg":12}')
        return result

    manager = _manager(root, analyse=compact)
    run = manager.submit(_request_run(saved))
    if change_before_publication:
        assert run["status"] == "failed"
        assert run["error"]["code"] == "planned_analysis_sources_changed"
        assert not list(root.rglob("reports/attempt-*.json"))
    else:
        assert run["status"] == "completed_with_gaps"
        report = json.loads((root / run["report_ref"]).read_text())
        assert report["owner_source_hashes"][source.name] == original_sha
        source.write_text('{"load_kg":12}')
        current = manager.get(run["run_id"])
        assert current["status"] == "stale" and not current["projections"]


def test_process_loss_is_observed_without_writes_and_resumed_explicitly(planned, monkeypatch):
    root, _, saved = _setup(planned, monkeypatch)
    manager = _manager(root)
    original = manager._start
    manager._start = lambda run_id, lease: manager._release(lease)
    run = manager.submit(_request_run(saved))
    assert run["status"] == "interrupted" and run["can_resume"]
    snapshot = _files(root)
    assert _manager(root).get(run["run_id"])["status"] == "interrupted"
    assert _files(root) == snapshot
    manager._start = original
    request = PlannedAnalysisResumeRequest(expected_manifest_sha256=saved["manifest_sha256"],
                                          idempotency_key="resume.one", explicit_confirmation=True)
    result = manager.resume(run["run_id"], request)
    assert result["status"] == "completed_with_gaps" and result["attempt"] == 2
    assert manager.resume(run["run_id"], request)["attempt"] == 2


def test_failed_stage_retries_in_a_new_attempt_preserving_previous_files(planned, monkeypatch):
    root, _, saved = _setup(planned, monkeypatch)
    def failure(root, bundle, run_root, *, progress):
        (run_root / "failure-evidence.json").write_text('{"partial":true}')
        raise OSError("fixture failure")
    manager = _manager(root, prepare=failure)
    result = manager.submit(_request_run(saved))
    assert result["status"] == "failed" and result["can_resume"]
    evidence = next(root.rglob("failure-evidence.json"))
    original = evidence.read_bytes()
    manager.prepare = _prepare
    resumed = manager.resume(result["run_id"], PlannedAnalysisResumeRequest(
        expected_manifest_sha256=saved["manifest_sha256"], idempotency_key="retry", explicit_confirmation=True))
    assert resumed["attempt"] == 2 and resumed["status"] == "completed_with_gaps"
    assert evidence.read_bytes() == original


def test_stale_plan_sources_block_submit_and_resume(planned, monkeypatch):
    root, _, saved = _setup(planned, monkeypatch)
    manager = _manager(root)
    run = manager.submit(_request_run(saved))
    (root / "source.gpx").write_text("changed source")
    assert manager.get(run["run_id"])["status"] == "stale"
    with pytest.raises(PlannedRouteConflict, match="sources changed"):
        manager.submit(_request_run(saved, "new"))
    with pytest.raises(PlannedRouteConflict):
        manager.resume(run["run_id"], PlannedAnalysisResumeRequest(
            expected_manifest_sha256=saved["manifest_sha256"], idempotency_key="retry", explicit_confirmation=True))


@pytest.mark.parametrize("fault", ["binding", "boundary", "missing_role"])
def test_invalid_producer_never_publishes_completed(fault, planned, monkeypatch):
    root, _, saved = _setup(planned, monkeypatch)
    def invalid(*args, **kwargs):
        result = _analyse(*args, **kwargs)
        if fault == "binding":
            result["projections"]["navigation"]["input_binding"]["geometry_sha256"] = "f" * 64
        elif fault == "boundary":
            result["projections"]["navigation"]["runtime_safety_truth"] = True
        else:
            del result["projections"]["navigation"]
        return result
    run = _manager(root, analyse=invalid).submit(_request_run(saved))
    assert run["status"] == "failed" and "projections" not in run
    assert not list(root.rglob("reports/attempt-*.json"))


def test_http_run_actions_keep_get_read_only_and_return_202(planned, monkeypatch):
    root, client, saved = _setup(planned, monkeypatch)
    import scout_planned_route_api
    monkeypatch.setattr(scout_planned_route_api, "manager_for", _manager)
    prefix = f"/admin/pretrip/projects/{root.name}/planned-route/analysis-runs"
    before = _files(root)
    assert client.get(prefix).json()["runs"] == [] and _files(root) == before
    response = client.post(prefix, json=_request_run(saved).model_dump(mode="json"))
    assert response.status_code == 202, response.text
    run = response.json()
    after = _files(root)
    assert client.get(prefix + "/" + run["run_id"]).json()["status"] == "completed_with_gaps"
    assert client.get(prefix, params={"version_id": saved["version_id"]}).json()["runs"][0]["run_id"] == run["run_id"]
    assert _files(root) == after
    assert client.post(prefix, json={**_request_run(saved).model_dump(mode="json"), "explicit_confirmation": False}).status_code == 422


def test_different_snapshots_share_one_configured_preparation_slot(planned, monkeypatch, tmp_path):
    root, _, saved = _setup(planned, monkeypatch)
    replicas = []
    for name in ("snapshot-a", "snapshot-b"):
        target = tmp_path / name / root.name
        shutil.copytree(root, target)
        replicas.append(target)
    monkeypatch.setenv("SCOUT_PLANNED_PREPARATION_LOCK_ROOT", str(tmp_path / "shared-worker"))
    guard, workers = threading.Lock(), []
    running, peak = 0, 0
    def prepare(*args, **kwargs):
        nonlocal running, peak
        with guard:
            running += 1
            peak = max(peak, running)
        time.sleep(.08)
        result = _prepare(*args, **kwargs)
        with guard:
            running -= 1
        return result
    def launch(callback):
        thread = threading.Thread(target=callback)
        workers.append(thread)
        thread.start()
    managers = [PlannedAnalysisManager(replica, prepare=prepare, analyse=_analyse, launch=launch) for replica in replicas]
    runs = [manager.submit(_request_run(saved)) for manager in managers]
    for worker in workers:
        worker.join(5)
        assert not worker.is_alive()
    assert peak == 1
    assert all(manager.get(run["run_id"])["status"] == "completed_with_gaps" for manager, run in zip(managers, runs))
