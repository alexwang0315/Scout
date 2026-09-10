"""Faithful SSH/rsync seam: actual immutable snapshots and remote job files."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil
import threading
from types import SimpleNamespace

import pytest

import scout_planned_analysis_remote as remote
from scout_planned_analysis import PlannedAnalysisManager, PlannedAnalysisResumeRequest
from scout_planned_route_models import PlannedRouteConflict
from scout_planned_route_artifacts import PlannedAnalysisSelectionRequest, select_analysis_subject
from test_scout_planned_route_artifacts import planned
from test_scout_planned_route_artifacts import _request, _save, _review
from test_scout_planned_analysis import _setup, _request_run, _prepare, _analyse


@pytest.fixture
def transport(planned, monkeypatch, tmp_path):
    root, _, saved = _setup(planned, monkeypatch)
    server = tmp_path / "scout-storage"
    server.mkdir()
    config = tmp_path / "remote.json"
    config.write_text(json.dumps({"host": "operator@scout.local", "workspace_root": str(server),
                                  "command": ["/configured/planned-python", "-m", "scout_planned_analysis", "--rpc"]}))
    monkeypatch.setenv("SCOUT_PLANNED_RPC_ROOT", str(server))
    monkeypatch.setenv("SCOUT_PLANNED_ANALYSIS_REMOTE_CONFIG", str(config))
    monkeypatch.setenv("SCOUT_PLANNED_EXECUTION_LOCATION", "scout")
    class LocalExecution(PlannedAnalysisManager):
        def __init__(self, root):
            super().__init__(root, prepare=_prepare, analyse=_analyse, launch=lambda callback: callback())
    monkeypatch.setattr(remote, "PlannedAnalysisManager", LocalExecution)
    requests = []
    def rpc(config, envelope):
        requests.append(envelope)
        return remote.serve_rpc(envelope)
    monkeypatch.setattr(remote, "_rpc", rpc)
    streams = []
    def rsync(command, **kwargs):
        assert command[0] == "rsync" and "--ignore-existing" in command and "--no-links" in command
        source, target = Path(command[-2]), Path(command[-1].split(":", 1)[1])
        refs = kwargs["input"].decode().strip("\x00").split("\x00")
        for ref in refs:
            destination = target / ref
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists():
                shutil.copyfile(source / ref, destination)
        streams.append(refs)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(remote.subprocess, "run", rsync)
    return root, saved, server, requests, streams


def test_outputs_stay_on_scout_and_retry_does_not_resend_snapshot(transport):
    root, saved, server, requests, streams = transport
    manager = remote.RemotePlannedAnalysisManager(root)
    run = manager.submit(_request_run(saved))
    assert run["status"] == "completed_with_gaps" and run["execution_location"] == "scout"
    assert len(list(server.rglob("architecture.json"))) == 1
    assert not list(root.rglob("architecture.json"))
    assert len(list((root / remote.HANDLES_REF).glob("*.json"))) == 1
    assert len(streams) == 1
    assert manager.submit(_request_run(saved))["run_id"] == run["run_id"]
    assert len(streams) == 1
    state = manager.get(run["run_id"])
    assert state["binding"]["geometry_sha256"] == saved["geometry_sha256"]
    before = len(requests)
    assert manager.list(saved["version_id"])["runs"][0]["run_id"] == run["run_id"]
    assert all(request["operation"] == "get" for request in requests[before:])


def test_remote_replica_cannot_hide_local_source_changes(transport):
    root, saved, server, requests, streams = transport
    manager = remote.RemotePlannedAnalysisManager(root)
    run = manager.submit(_request_run(saved))
    (root / "source.gpx").write_text("new local source")
    state = manager.get(run["run_id"])
    assert state["status"] == "stale" and state["projections"] == {}
    with pytest.raises(PlannedRouteConflict):
        manager.resume(run["run_id"], PlannedAnalysisResumeRequest(expected_manifest_sha256=saved["manifest_sha256"],
                       idempotency_key="resume", explicit_confirmation=True))
    assert len(list(server.rglob("architecture.json"))) == 1


def test_switching_to_golden_and_back_does_not_invalidate_remote_analysis(transport):
    root, saved, server, requests, streams = transport
    manager = remote.RemotePlannedAnalysisManager(root)
    run = manager.submit(_request_run(saved))
    from scout_planned_route_artifacts import get_analysis_selection
    first = get_analysis_selection(root)
    golden = select_analysis_subject(root, PlannedAnalysisSelectionRequest(subject_kind="golden_gpx",
        expected_selection_sha256=first["selection_sha256"], idempotency_key="view-golden", explicit_confirmation=True))
    select_analysis_subject(root, PlannedAnalysisSelectionRequest(subject_kind="planned_gpx", version_id=saved["version_id"],
        expected_manifest_sha256=saved["manifest_sha256"], expected_selection_sha256=golden["selection_sha256"],
        idempotency_key="view-planned-again", explicit_confirmation=True))
    assert manager.get(run["run_id"])["status"] == "completed_with_gaps"
    assert not any("analysis_selection" in ref or "/selections/" in ref for ref in streams[0])


def test_rpc_rejects_path_escape_and_tampered_snapshot(transport):
    root, saved, server, requests, streams = transport
    with pytest.raises(PlannedRouteConflict):
        remote.serve_rpc({"operation": "initialize", "project_id": "../escape", "snapshot_id": "a" * 64})
    run = remote.RemotePlannedAnalysisManager(root).submit(_request_run(saved))
    verification = next(request for request in requests if request["operation"] == "verify_inputs")
    replica = server / verification["snapshot_id"] / root.name
    (replica / "source.gpx").write_text("different bytes")
    with pytest.raises(PlannedRouteConflict):
        remote.serve_rpc(verification)
    assert run["status"] == "completed_with_gaps"


def test_snapshot_does_not_stream_secrets_caches_or_links(transport):
    root, saved, server, requests, streams = transport
    (root / ".env").write_text("not a real credential")
    (root / "cache").mkdir()
    (root / "cache/large.json").write_text("{}")
    (root / "leaked.json").symlink_to(root / ".env")
    remote.RemotePlannedAnalysisManager(root).submit(_request_run(saved))
    assert not {".env", "cache/large.json", "leaked.json"} & set(streams[0])


def test_concurrent_conflicting_key_cannot_overwrite_successful_handle(transport, planned, monkeypatch):
    root, first, server, requests, streams = transport
    _, compiler, _ = planned
    request, preview = _request(root, compiler, parent_version_id=first["version_id"])
    second = _save(root, request, preview, key="save.second")
    _review(root, second, key="review.second")
    entered, release = threading.Event(), threading.Event()
    rpc = remote._rpc
    def slow_initialization(config, envelope):
        if envelope["operation"] == "initialize" and not entered.is_set():
            entered.set()
            assert release.wait(5)
        return rpc(config, envelope)
    monkeypatch.setattr(remote, "_rpc", slow_initialization)
    manager = remote.RemotePlannedAnalysisManager(root)
    with ThreadPoolExecutor(max_workers=2) as pool:
        winning = pool.submit(manager.submit, _request_run(first, "shared-key"))
        assert entered.wait(5)
        conflicting = pool.submit(manager.submit, _request_run(second, "shared-key"))
        release.set()
        result = winning.result()
        with pytest.raises(PlannedRouteConflict, match="key already identifies"):
            conflicting.result()
    assert manager.get(result["run_id"])["version_id"] == first["version_id"]
    assert len(streams) == 1
