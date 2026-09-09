from __future__ import annotations

import builtins
from dataclasses import dataclass, replace
import hashlib
import io
import json
import multiprocessing
import os
from pathlib import Path
import socket
import threading
import time

import pytest

from dashboard_preparation_jobs import (
    DashboardPreparationJobConflict, DashboardPreparationJobManager,
)


@pytest.fixture(autouse=True)
def isolated_inputs_only(monkeypatch, tmp_path):
    """Factories must never discover the operator's env files or network."""
    import dotenv
    import dotenv.main
    import scout_env
    monkeypatch.setattr(dotenv, "dotenv_values", lambda *a, **k: {})
    monkeypatch.setattr(dotenv.main, "dotenv_values", lambda *a, **k: {})
    monkeypatch.setattr(dotenv.main.DotEnv, "dict", lambda *a, **k: {})
    monkeypatch.setattr(scout_env, "load_scout_env_files", lambda **k: scout_env.ScoutEnvLoadResult((), ()))
    monkeypatch.setenv("SCOUT_AI_ASSISTANT_ENABLED", "0")
    monkeypatch.setenv("SCOUT_PRETRIP_WORKSPACE_ROOT", str(tmp_path / "workspaces"))
    monkeypatch.setenv("SCOUT_RUNTIME_AUDIT_ROOT", str(tmp_path / "runtime-audit"))
    monkeypatch.delenv("SCOUT_PRETRIP_MATERIAL_ROOT", raising=False)
    monkeypatch.delenv("SCOUT_PRETRIP_DURABLE_EVIDENCE_SOURCE_ROOT", raising=False)

    def no_network(*args, **kwargs):
        raise AssertionError("Network calls are forbidden in preparation job fixtures")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "getaddrinfo", no_network)
    for module in (builtins, io):
        original = module.open
        def safe_open(file, *args, _original=original, **kwargs):
            if isinstance(file, (str, bytes, os.PathLike)) and Path(os.fsdecode(file)).name.startswith(".env"):
                raise AssertionError("Real env-file reads are forbidden")
            return _original(file, *args, **kwargs)
        monkeypatch.setattr(module, "open", safe_open)


def _request(tmp_path, project_id="fixture-route"):
    from pretrip_import import PretripImportRequest
    primary = tmp_path / "golden.gpx"
    if not primary.exists():
        primary.write_text(
            '<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
            '<trkpt lat="23" lon="121"><ele>1000</ele><time>2026-09-01T00:00:00Z</time></trkpt>'
            '<trkpt lat="23.001" lon="121.001"><ele>1010</ele><time>2026-09-01T00:10:00Z</time></trkpt>'
            '</trkseg></trk></gpx>')
    return PretripImportRequest(project_id=project_id, primary_gpx=primary,
                                workspace_root=tmp_path / "workspaces")


def _import(request):
    root = request.workspace_root / request.project_id
    (root / "inbox/gpx").mkdir(parents=True)
    (root / "project.json").write_text(json.dumps({"project_id": request.project_id}))
    source = root / "inbox/gpx/primary.gpx"
    source.write_bytes(request.primary_gpx.read_bytes())
    manifest = {"project_id": request.project_id, "sources": [{
        "role": "golden_route_reference", "workspace_ref": "inbox/gpx/primary.gpx",
        "original_path": str(request.primary_gpx), "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }]}
    (root / "inbox/source_manifest.json").write_text(json.dumps(manifest))
    return {"project_id": request.project_id, "outputs": {"source_inbox_manifest_ref": "inbox/source_manifest.json"}}


def _ready(*args, **kwargs):
    return {"validation": {"status": "ready"}, "qgis_terrain_feature_stack": {"status": "completed"}}


def _initialized(*args, **kwargs):
    return {"status": "ready", "candidate_only": True, "runtime_safety_truth": False}


def _manager(root, **overrides):
    options = dict(import_runner=_import, preparation_runner=_ready, initializer=_initialized)
    options.update(overrides)
    return DashboardPreparationJobManager(root, **options)


def _terminal(manager, job_id, *, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = manager.get(job_id)
        if state["status"] not in {"queued", "running"}:
            return state
        time.sleep(0.01)
    pytest.fail("Fixture preparation did not reach a terminal state")


def _snapshot(root):
    return {str(path.relative_to(root)): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


def test_constructor_and_empty_observation_do_not_create_storage(tmp_path):
    root = tmp_path / "absent-workspaces"
    manager = _manager(root)
    assert manager.list() == []
    with pytest.raises(FileNotFoundError):
        manager.get("prep." + "0" * 32)
    assert not root.exists()


def test_async_job_exposes_stage_and_get_list_are_read_only(tmp_path):
    request = _request(tmp_path)
    preparing = threading.Event()
    release = threading.Event()
    options_seen = []
    def prepare(root, **options):
        options_seen.append(options)
        preparing.set()
        assert release.wait(10)
        return _ready()
    manager = _manager(request.workspace_root, preparation_runner=prepare)
    options = {"allow_network_fetch": False, "seed_imagery_cache": False, "network_mode": "no-network"}
    job = manager.submit_import(request, "same-request", preparation_options=options)
    try:
        assert preparing.wait(10)
        other = _manager(request.workspace_root)
        before = _snapshot(request.workspace_root)
        state = other.get(job["job_id"])
        assert state["status"] == "running" and state["stage"] == "prepare"
        assert state["workspace_available"] is True and state["can_resume"] is False
        assert other.list(request.project_id)[0]["job_id"] == job["job_id"]
        assert _snapshot(request.workspace_root) == before
        replay = other.submit_import(request, "same-request", preparation_options=options)
        assert replay["job_id"] == job["job_id"]
        assert len(other.list()) == 1
        assert options_seen[0]["preparation_options"] == options
    finally:
        release.set()
    completed = _terminal(manager, job["job_id"])
    assert completed["status"] == "completed"
    assert completed["runtime_safety_truth"] is False
    assert set(completed["stages"]) == {"import", "prepare", "permission_init"}
    for value in completed["stages"].values():
        assert hashlib.sha256(Path(value["receipt_ref"]).read_bytes()).hexdigest() == value["receipt_sha256"]


def test_request_key_and_target_collisions_do_not_create_new_jobs(tmp_path):
    request = _request(tmp_path)
    manager = _manager(request.workspace_root)
    job = manager.submit_import(request, "key")
    _terminal(manager, job["job_id"])
    before = _snapshot(request.workspace_root)
    with pytest.raises(DashboardPreparationJobConflict, match="another request") as conflict:
        manager.submit_import(_request(tmp_path, "other-route"), "key")
    assert conflict.value.code == "idempotency_conflict"
    with pytest.raises(DashboardPreparationJobConflict) as collision:
        manager.submit_import(request, "new-key")
    assert collision.value.code == "target_exists"
    assert _snapshot(request.workspace_root) == before


def test_failed_prepare_resumes_without_import_and_preserves_false_options(tmp_path):
    request = _request(tmp_path)
    calls = []
    seen = []
    def importer(value):
        calls.append("import")
        return _import(value)
    def prepare(root, **kwargs):
        calls.append("prepare")
        seen.append(kwargs["preparation_options"])
        if len(seen) == 1:
            raise RuntimeError("fixture failure payload must not be exposed")
        return _ready()
    manager = _manager(request.workspace_root, import_runner=importer, preparation_runner=prepare)
    options = {"allow_network_fetch": False, "network_mode": "no-network"}
    job = manager.submit_import(request, "resume", preparation_options=options)
    failed = _terminal(manager, job["job_id"])
    assert failed["status"] == "failed" and failed["stage"] == "prepare"
    assert failed["can_resume"] is True and failed["workspace_available"] is True
    assert "failure payload" not in json.dumps(failed)
    original_import_ref = failed["refs"]["import"]
    manager.resume(job["job_id"])
    completed = _terminal(manager, job["job_id"])
    assert completed["status"] == "completed" and completed["attempt"] == 2
    assert calls == ["import", "prepare", "prepare"]
    assert seen == [options, options]
    assert completed["refs"]["import"] == original_import_ref
    assert Path(failed["refs"]["prepare"]).is_file()


@pytest.mark.parametrize("which", ["source", "imported"])
def test_source_or_completed_import_change_blocks_resume_without_writes(tmp_path, which):
    request = _request(tmp_path)
    def fail(*args, **kwargs):
        raise RuntimeError("synthetic preparation failure")
    manager = _manager(request.workspace_root, preparation_runner=fail)
    job = manager.submit_import(request, "changed-source")
    assert _terminal(manager, job["job_id"])["status"] == "failed"
    path = request.primary_gpx if which == "source" else request.workspace_root / request.project_id / "inbox/gpx/primary.gpx"
    path.write_bytes(path.read_bytes() + b"\n")
    before = _snapshot(tmp_path)
    state = manager.get(job["job_id"])
    assert state["can_resume"] is True
    assert state["resume_validation"] == "required_before_writes"
    with pytest.raises(DashboardPreparationJobConflict) as conflict:
        manager.resume(job["job_id"])
    assert conflict.value.code == ("source_changed" if which == "source" else "import_changed")
    assert _snapshot(tmp_path) == before


def test_permission_failure_resumes_after_completed_preparation(tmp_path):
    request = _request(tmp_path)
    calls = []
    def prepare(*args, **kwargs):
        calls.append("prepare")
        return _ready()
    def initialize(root):
        calls.append("init")
        if calls.count("init") == 1:
            raise RuntimeError("fixture init unavailable")
        return _initialized()
    manager = _manager(request.workspace_root, preparation_runner=prepare, initializer=initialize)
    job = manager.submit_import(request, "init-retry")
    assert _terminal(manager, job["job_id"])["stage"] == "permission_init"
    manager.resume(job["job_id"])
    assert _terminal(manager, job["job_id"])["status"] == "completed"
    assert calls == ["prepare", "init", "init"]


def test_concurrent_resume_calls_start_only_one_worker(tmp_path):
    request = _request(tmp_path)
    running, release = threading.Event(), threading.Event()
    calls = []
    def prepare(*args, **kwargs):
        calls.append("prepare")
        if len(calls) == 1:
            raise RuntimeError("first preparation is interrupted")
        running.set()
        assert release.wait(10)
        return _ready()
    manager = _manager(request.workspace_root, preparation_runner=prepare)
    job = manager.submit_import(request, "concurrent-resume")
    assert _terminal(manager, job["job_id"])["status"] == "failed"
    barrier = threading.Barrier(3)
    resumed, errors = [], []
    def resume():
        barrier.wait()
        try:
            resumed.append(manager.resume(job["job_id"]))
        except Exception as exc:
            errors.append(exc)
    workers = [threading.Thread(target=resume) for _ in range(2)]
    for worker in workers:
        worker.start()
    barrier.wait()
    try:
        assert running.wait(10)
        for worker in workers:
            worker.join(10)
        assert not errors
        assert len(resumed) == 2 and {item["attempt"] for item in resumed} == {2}
    finally:
        release.set()
    assert _terminal(manager, job["job_id"])["status"] == "completed"
    assert calls == ["prepare", "prepare"]


def test_degraded_preparation_is_terminal_without_automatic_retry(tmp_path):
    request = _request(tmp_path)
    calls = []
    def prepare(*args, **kwargs):
        calls.append("prepare")
        return {"validation": {"status": "blocked"}, "qgis_terrain_feature_stack": {"status": "unavailable"}}
    manager = _manager(request.workspace_root, preparation_runner=prepare)
    job = manager.submit_import(request, "degraded")
    state = _terminal(manager, job["job_id"])
    assert state["status"] == "completed_with_gaps" and state["can_resume"] is True
    assert state["stages"]["permission_init"]["status"] == "completed"
    assert calls == ["prepare"]


def test_missing_qgis_stage_cannot_be_reported_as_completed(tmp_path):
    request = _request(tmp_path)
    manager = _manager(request.workspace_root, preparation_runner=lambda *a, **k: {
        "validation": {"status": "ready"},
    })
    job = manager.submit_import(request, "missing-qgis-receipt")
    assert _terminal(manager, job["job_id"])["status"] == "completed_with_gaps"


def test_invalid_xml_is_rejected_before_job_or_workspace_creation(tmp_path):
    request = _request(tmp_path)
    request.primary_gpx.write_text("<gpx>broken")
    manager = _manager(request.workspace_root)
    with pytest.raises(DashboardPreparationJobConflict) as conflict:
        manager.submit_import(request, "bad-gpx")
    assert conflict.value.code == "invalid_gpx"
    assert manager.list() == []
    assert not (request.workspace_root / request.project_id).exists()


def test_partial_import_without_checkpoint_cannot_be_overwritten_on_resume(tmp_path):
    request = _request(tmp_path)
    calls = []
    def importer(value):
        calls.append("import")
        (value.workspace_root / value.project_id).mkdir()
        raise RuntimeError("interrupted while writing import")
    manager = _manager(request.workspace_root, import_runner=importer)
    job = manager.submit_import(request, "partial-import")
    state = _terminal(manager, job["job_id"])
    assert state["status"] == "failed" and state["can_resume"] is False
    assert state["resume_blocker"]["code"] == "import_outcome_unverified"
    with pytest.raises(DashboardPreparationJobConflict):
        manager.resume(job["job_id"])
    assert calls == ["import"]


def _crash_worker(request):
    def crash(*args, **kwargs):
        os._exit(17)
    manager = _manager(request.workspace_root, preparation_runner=crash)
    manager.submit_import(request, "process-crash")
    threading.Event().wait(15)


def test_process_restart_derives_interrupted_read_only_then_resumes_import_checkpoint(tmp_path):
    request = _request(tmp_path)
    context = multiprocessing.get_context("fork")
    process = context.Process(target=_crash_worker, args=(request,))
    process.start()
    process.join(15)
    assert process.exitcode == 17
    manager = _manager(request.workspace_root, import_runner=lambda _: pytest.fail("Must reuse completed import"))
    before = _snapshot(request.workspace_root)
    job = manager.list()[0]
    assert job["status"] == "interrupted" and job["persisted_status"] == "running"
    assert job["stage"] == "prepare" and job["can_resume"] is True
    assert _snapshot(request.workspace_root) == before
    manager.resume(job["job_id"])
    assert _terminal(manager, job["job_id"])["status"] == "completed"


def _holding_worker(request, preparing, release):
    def hold(*args, **kwargs):
        preparing.set()
        assert release.wait(15)
        return _ready()
    manager = _manager(request.workspace_root, preparation_runner=hold)
    job = manager.submit_import(request, "cross-process")
    _terminal(manager, job["job_id"])


def test_target_lease_and_idempotency_apply_across_processes(tmp_path):
    request = _request(tmp_path)
    context = multiprocessing.get_context("fork")
    preparing, release = context.Event(), context.Event()
    process = context.Process(target=_holding_worker, args=(request, preparing, release))
    process.start()
    try:
        assert preparing.wait(15)
        manager = _manager(request.workspace_root, import_runner=lambda _: pytest.fail("Duplicate import"))
        replay = manager.submit_import(request, "cross-process")
        assert replay["status"] == "running" and replay["can_resume"] is False
        assert len(manager.list()) == 1
        with pytest.raises(DashboardPreparationJobConflict) as conflict:
            manager.submit_import(request, "other-key")
        assert conflict.value.code == "target_exists"
    finally:
        release.set()
        process.join(15)
    assert process.exitcode == 0


def test_different_targets_wait_for_shared_preparation_lease_across_processes(tmp_path):
    first = _request(tmp_path, "first-route")
    second = replace(first, project_id="second-route")
    context = multiprocessing.get_context("fork")
    preparing, release = context.Event(), context.Event()
    process = context.Process(target=_holding_worker, args=(first, preparing, release))
    process.start()
    second_started = threading.Event()
    def prepare(*args, **kwargs):
        second_started.set()
        return _ready()
    manager = _manager(second.workspace_root, preparation_runner=prepare)
    try:
        assert preparing.wait(15)
        job = manager.submit_import(second, "second-target")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            waiting = manager.get(job["job_id"])
            if waiting["stage"] == "waiting_for_preparation_slot":
                break
            time.sleep(0.01)
        assert waiting["stage"] == "waiting_for_preparation_slot"
        assert waiting["status"] == "running" and waiting["workspace_available"] is True
        assert waiting["can_resume"] is False and not second_started.is_set()
        before = _snapshot(second.workspace_root)
        assert len(manager.list()) == 2
        assert _snapshot(second.workspace_root) == before
    finally:
        release.set()
        process.join(15)
    assert process.exitcode == 0
    assert _terminal(manager, job["job_id"])["status"] == "completed"
    assert second_started.is_set()


@pytest.mark.parametrize("source_kind", ["raw_directory", "raster_model"])
def test_raw_dtm_bindings_survive_manager_restart_and_block_changed_sources(tmp_path, source_kind):
    from pretrip_models import DtmRasterSource
    request = _request(tmp_path)
    raw = tmp_path / "raw-dtm"
    raw.mkdir()
    raster = raw / "source.tif"
    raster.write_bytes(b"synthetic raw terrain, never passed to a GIS processor")
    if source_kind == "raw_directory":
        request = replace(request, dtm_dirs=(raw,))
    else:
        request = replace(request, dtm_raster_sources=(DtmRasterSource(
            path=str(raster), role="terrain_dtm", sha256=hashlib.sha256(raster.read_bytes()).hexdigest(),
            crs="EPSG:3826", source_resolution_m=20.0),))
    captured = []
    def importer(value):
        captured.append(value)
        return _import(value)
    def unavailable(*args, **kwargs):
        raise RuntimeError("isolated prep unavailable")
    manager = _manager(request.workspace_root, import_runner=importer, preparation_runner=unavailable)
    job = manager.submit_import(request, "dtm-bound")
    assert _terminal(manager, job["job_id"])["can_resume"] is True
    if source_kind == "raster_model":
        assert isinstance(captured[0].dtm_raster_sources[0], DtmRasterSource)
    manager = _manager(request.workspace_root)
    assert manager.get(job["job_id"])["can_resume"] is True
    raster.write_bytes(b"changed raw terrain")
    before = _snapshot(tmp_path)
    observed = manager.get(job["job_id"])
    assert observed["can_resume"] is True
    assert observed["resume_validation"] == "required_before_writes"
    with pytest.raises(DashboardPreparationJobConflict) as conflict:
        manager.resume(job["job_id"])
    assert conflict.value.code == "source_changed"
    assert _snapshot(tmp_path) == before


def test_typed_missing_source_failure_retains_field_and_path(tmp_path):
    from pretrip_import import PretripPreparationInputError
    request = _request(tmp_path)
    missing = tmp_path / "declared-source.tif"
    def unavailable(*args, **kwargs):
        raise PretripPreparationInputError(field="dtm_rasters", path=missing)
    manager = _manager(request.workspace_root, preparation_runner=unavailable)
    job = manager.submit_import(request, "typed-source-failure")
    failed = _terminal(manager, job["job_id"])
    assert failed["error"]["code"] == "PREPARATION_SOURCE_MISSING"
    assert failed["error"]["details"] == {
        "code": "PREPARATION_SOURCE_MISSING", "field": "dtm_rasters", "path": str(missing)}


def test_cold_get_and_list_do_not_resolve_or_read_large_source_contents(tmp_path, monkeypatch, record_property):
    import dashboard_preparation_jobs as jobs
    import dashboard_workspace_preparation as preparation
    import pretrip_import
    from pretrip_models import DtmRasterSource
    request = _request(tmp_path)
    raster = tmp_path / "large-source.tif"
    raster.write_bytes(b"synthetic raster source used only for binding")
    request = replace(request, dtm_raster_sources=(DtmRasterSource(
        path=str(raster), role="terrain_dtm", sha256=hashlib.sha256(raster.read_bytes()).hexdigest(),
        crs="EPSG:3826", source_resolution_m=20.0),))
    def unavailable(*args, **kwargs):
        raise RuntimeError("fixture preparation failure")
    original = _manager(request.workspace_root, preparation_runner=unavailable)
    job = original.submit_import(request, "cold-status")
    assert _terminal(original, job["job_id"])["status"] == "failed"
    cold = _manager(request.workspace_root)
    before = _snapshot(tmp_path)
    forbidden_calls = []
    def forbidden(*args, **kwargs):
        forbidden_calls.append(True)
        raise AssertionError("Status observation must not hash inputs, resolve them, or start workers")
    with monkeypatch.context() as guarded:
        guarded.setattr(jobs, "_file_hash", forbidden)
        guarded.setattr(pretrip_import, "_preparation_source_inputs", forbidden)
        guarded.setattr(preparation, "resolve_workspace_preparation_inputs", forbidden)
        guarded.setattr(cold, "background_start", forbidden)
        started = time.monotonic()
        for _ in range(10):
            assert cold.get(job["job_id"])["resume_validation"] == "required_before_writes"
            assert cold.list()[0]["can_resume"] is True
        elapsed = time.monotonic() - started
    record_property("twenty_cold_status_reads_seconds", elapsed)
    assert elapsed < 2.0
    assert not forbidden_calls and _snapshot(tmp_path) == before


@pytest.mark.parametrize("prepare_failed", [False, True])
def test_status_validates_each_json_request_once_without_model_conversion(tmp_path, monkeypatch, prepare_failed):
    import dashboard_preparation_jobs as jobs

    def prepare(*args, **kwargs):
        if prepare_failed:
            raise RuntimeError("fixture preparation failure")
        return _ready()

    request = _request(tmp_path)
    manager = _manager(request.workspace_root, preparation_runner=prepare,
                       background_start=lambda callback: callback())
    first = manager.submit_import(request, "first")
    second = manager.submit_import(_request(tmp_path, "second-route"), "second")
    before = _snapshot(tmp_path)
    verified = []
    original = manager._envelope

    def observe_envelope(state):
        verified.append(state["job_id"])
        return original(state)

    def no_model_conversion(*args, **kwargs):
        raise AssertionError("JSON status records need no recursive model conversion")

    monkeypatch.setattr(manager, "_envelope", observe_envelope)
    monkeypatch.setattr(jobs, "_json_value", no_model_conversion)
    assert manager.get(first["job_id"])["can_resume"] is prepare_failed
    assert verified == [first["job_id"]]
    verified.clear()
    assert len(manager.list()) == 2
    assert sorted(verified) == sorted([first["job_id"], second["job_id"]])
    assert manager.list(request.project_id)[0]["job_id"] == first["job_id"]
    assert _snapshot(tmp_path) == before

    # Both completed and failed jobs must still detect modified JSON content.
    record = Path(first["refs"]["request"])
    payload = json.loads(record.read_text())
    payload["requested_by"] = "changed request"
    record.write_text(json.dumps(payload))
    for read in (lambda: manager.get(first["job_id"]), manager.list):
        with pytest.raises(DashboardPreparationJobConflict) as conflict:
            read()
        assert conflict.value.code == "request_changed"


def test_validation_error_receipt_has_field_errors_without_secret_inputs(tmp_path):
    from pydantic import BaseModel, field_validator
    class FixtureInput(BaseModel):
        count: int
        label: str

        @field_validator("label")
        @classmethod
        def reject_label(cls, value):
            raise ValueError("the rejected raw value was " + value)
    request = _request(tmp_path)
    secret = "fixture-private-value-never-echo"
    def invalid(*args, **kwargs):
        try:
            FixtureInput.model_validate({"count": secret, "label": secret})
        except Exception as exc:
            raise RuntimeError("wrapper must not hide structured validation") from exc
    manager = _manager(request.workspace_root, import_runner=invalid)
    job = manager.submit_import(request, "validation-details")
    failed = _terminal(manager, job["job_id"])
    errors = failed["error"]["details"]["validation_errors"]
    assert {tuple(item["loc"]) for item in errors} == {("count",), ("label",)}
    assert {item["type"] for item in errors} == {"int_parsing", "value_error"}
    assert not any({"input", "url", "ctx"} & item.keys() for item in errors)
    receipt = Path(failed["refs"]["import"]).read_text()
    assert secret not in json.dumps(failed) and secret not in receipt


@pytest.mark.parametrize("explicit_path", [True, False])
def test_v2_pbf_options_bind_effective_source_and_preserve_explicit_none(tmp_path, explicit_path):
    request = _request(tmp_path)
    material = tmp_path / "material"
    material.mkdir()
    (material / "material_manifest.json").write_text(json.dumps({"sources": {
        "local_osm_pbf": {"path": str(material / "missing-old-source.osm.pbf")},
    }}))
    pbf = tmp_path / "chosen-source.osm.pbf"
    pbf.write_bytes(b"synthetic PBF source; no osmium invocation")
    request = replace(request, material_root=material)
    def unavailable(*args, **kwargs):
        raise RuntimeError("fixture preparation failure")
    manager = _manager(request.workspace_root, preparation_runner=unavailable)
    job = manager.submit_import(request, "explicit-pbf", preparation_options={
        "osm_pbf_path": str(pbf) if explicit_path else None,
    })
    failed = _terminal(manager, job["job_id"])
    assert failed["stage"] == "prepare"
    envelope = json.loads(Path(failed["refs"]["request"]).read_text())
    assert envelope["source_binding_version"] == 2
    pbf_bindings = [item for item in envelope["source_bindings"] if item["role"] == "local_osm_pbf"]
    assert [item["path"] for item in pbf_bindings] == ([str(pbf)] if explicit_path else [])
    if explicit_path:
        pbf.write_bytes(b"changed declared PBF")
        before = _snapshot(tmp_path)
        with pytest.raises(DashboardPreparationJobConflict) as conflict:
            manager.resume(job["job_id"])
        assert conflict.value.code == "source_changed"
        assert _snapshot(tmp_path) == before


def _legacy_job(tmp_path, monkeypatch, *, material_pbf):
    """Replay the pre-v2 binding verifier, retaining an immutable v1 ledger."""
    import dashboard_preparation_jobs as jobs
    request = _request(tmp_path)
    pbf = tmp_path / "historical-source.osm.pbf"
    pbf.write_bytes(b"historical PBF fixture")
    options = {"osm_pbf_path": str(pbf)}
    if material_pbf:
        material = tmp_path / "material"
        material.mkdir()
        (material / "material_manifest.json").write_text(json.dumps({"sources": {
            "local_osm_pbf": {"path": str(pbf), "sha256": hashlib.sha256(pbf.read_bytes()).hexdigest()},
        }}))
        request = replace(request, material_root=material)
        options = {}
    class LegacyFixtureManager(DashboardPreparationJobManager):
        def _verify_sources(self, envelope):
            current = self._source_bindings(envelope)
            if jobs._digest(current) != envelope["source_sha256"]:
                raise DashboardPreparationJobConflict("source_changed", "Legacy input changed")
    def unavailable(*args, **kwargs):
        raise RuntimeError("preserved legacy preparation failure")
    with monkeypatch.context() as legacy:
        legacy.setattr(jobs, "_SOURCE_BINDING_VERSION", 1)
        manager = LegacyFixtureManager(request.workspace_root, import_runner=_import,
            preparation_runner=unavailable, initializer=_initialized, background_start=lambda callback: callback())
        job = manager.submit_import(request, "historical-v1", preparation_options=options)
    assert job["status"] == "failed" and job["workspace_available"] is True
    return request, pbf, job


def test_v1_unbound_explicit_pbf_requires_new_workspace_without_mutating_history(tmp_path, monkeypatch):
    request, pbf, job = _legacy_job(tmp_path, monkeypatch, material_pbf=False)
    manager = _manager(request.workspace_root)
    before = _snapshot(tmp_path)
    observed = manager.get(job["job_id"])
    assert observed["can_resume"] is False
    assert observed["resume_blocker"]["code"] == "source_binding_upgrade_required"
    assert "new workspace" in observed["resume_blocker"]["message"]
    with pytest.raises(DashboardPreparationJobConflict) as conflict:
        manager.resume(job["job_id"])
    assert conflict.value.code == "source_binding_upgrade_required"
    assert _snapshot(tmp_path) == before


def test_v1_material_pbf_binding_remains_resumable_and_keeps_original_request(tmp_path, monkeypatch):
    request, pbf, job = _legacy_job(tmp_path, monkeypatch, material_pbf=True)
    original_request = Path(job["refs"]["request"]).read_bytes()
    manager = _manager(request.workspace_root, import_runner=lambda _: pytest.fail("Do not reimport v1"))
    assert manager.get(job["job_id"])["can_resume"] is True
    manager.resume(job["job_id"])
    assert _terminal(manager, job["job_id"])["status"] == "completed"
    assert Path(job["refs"]["request"]).read_bytes() == original_request


@pytest.mark.parametrize("project_pbf", [False, True])
def test_v1_clone_without_crs_or_project_pbf_bindings_cannot_reinterpret_current_metadata(tmp_path, monkeypatch, project_pbf):
    import dashboard_preparation_jobs as jobs
    from dashboard_workspace_clone import WorkspaceCloneRequest
    request = _request(tmp_path, "source-route")
    _import(request)
    source = request.workspace_root / request.project_id
    reference = source / "inbox/gpx/reference.gpx"
    reference.write_bytes(request.primary_gpx.read_bytes())
    manifest_path = source / "inbox/source_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["sources"].append({"role": "reference_track", "workspace_ref": "inbox/gpx/reference.gpx",
        "sha256": hashlib.sha256(reference.read_bytes()).hexdigest()})
    manifest_path.write_text(json.dumps(manifest))
    raster = tmp_path / "original.tif"
    metadata = tmp_path / "Metadata.xml"
    raster.write_bytes(b"unchanged original raster")
    metadata.write_text("<metadata><crs>EPSG:3826</crs></metadata>")
    coverage = source / "normalized/terrain/dtm_coverage_summary.json"
    coverage.parent.mkdir(parents=True)
    coverage.write_text(json.dumps({"raster_sources": [{
        "path": str(raster), "role": "raw_dem", "sha256": hashlib.sha256(raster.read_bytes()).hexdigest(),
        "crs": "EPSG:3826", "source_resolution_m": 20.0, "crs_evidence": str(metadata),
        "crs_evidence_sha256": hashlib.sha256(metadata.read_bytes()).hexdigest(),
    }]}))
    if project_pbf:
        pbf = tmp_path / "original.osm.pbf"
        pbf.write_bytes(b"unchanged original PBF")
        project = json.loads((source / "project.json").read_text())
        project.update({"osm_pbf_source_ref": str(pbf),
            "osm_pbf_source_sha256": hashlib.sha256(pbf.read_bytes()).hexdigest()})
        (source / "project.json").write_text(json.dumps(project))
    calls = []
    class LegacyFixtureManager(DashboardPreparationJobManager):
        def _verify_sources(self, envelope):
            if jobs._digest(self._source_bindings(envelope)) != envelope["source_sha256"]:
                raise DashboardPreparationJobConflict("source_changed", "Legacy input changed")
    def legacy_failure(*args, **kwargs):
        calls.append("clone")
        raise RuntimeError("legacy import schema failure before creating the target")
    clone_request = WorkspaceCloneRequest(source_project_id=request.project_id, target_project_id="legacy-clone",
        source_project_root=source, workspace_root=request.workspace_root,
        allow_network_fetch=False, network_mode="no-network")
    with monkeypatch.context() as legacy:
        legacy.setattr(jobs, "_SOURCE_BINDING_VERSION", 1)
        manager = LegacyFixtureManager(request.workspace_root, clone_runner=legacy_failure,
            background_start=lambda callback: callback())
        job = manager.submit_clone(clone_request, "legacy-clone-provenance")
    envelope = json.loads(Path(job["refs"]["request"]).read_text())
    bound = {row["path"] for row in envelope["source_bindings"]}
    assert str(raster) in bound and str(metadata) not in bound and str(coverage) not in bound
    cold = _manager(request.workspace_root, clone_runner=legacy_failure)
    before = _snapshot(tmp_path)
    observed = cold.get(job["job_id"])
    if project_pbf:
        assert observed["can_resume"] is False
        assert observed["resume_blocker"]["code"] == "source_binding_upgrade_required"
    else:
        assert observed["resume_validation"] == "required_before_writes"
    with pytest.raises(DashboardPreparationJobConflict) as conflict:
        cold.resume(job["job_id"])
    assert conflict.value.code == "source_binding_upgrade_required"
    assert ("PBF" if project_pbf else "CRS metadata") in str(conflict.value)
    assert calls == ["clone"]
    assert _snapshot(tmp_path) == before


def test_v2_clone_binds_original_project_pbf_through_real_clone_entrypoint(tmp_path, monkeypatch):
    from dashboard_workspace_clone import WorkspaceCloneRequest
    request = _request(tmp_path, "source-route")
    _import(request)
    source = request.workspace_root / request.project_id
    reference = source / "inbox/gpx/reference.gpx"
    reference.write_bytes(request.primary_gpx.read_bytes())
    source_manifest_path = source / "inbox/source_manifest.json"
    manifest = json.loads(source_manifest_path.read_text())
    manifest["sources"].append({"role": "reference_track", "workspace_ref": "inbox/gpx/reference.gpx",
        "sha256": hashlib.sha256(reference.read_bytes()).hexdigest()})
    source_manifest_path.write_text(json.dumps(manifest))
    pbf = tmp_path / "original-source.osm.pbf"
    pbf.write_bytes(b"synthetic raw PBF; the extractor is never invoked")
    project = json.loads((source / "project.json").read_text())
    project.update({"osm_pbf_source_ref": str(pbf),
        "osm_pbf_source_sha256": hashlib.sha256(pbf.read_bytes()).hexdigest()})
    (source / "project.json").write_text(json.dumps(project))
    monkeypatch.setattr("dashboard_workspace_clone._osm_pbf_parser_available", lambda _: True)
    seen = []
    def unavailable(root, **kwargs):
        seen.append(kwargs["preparation_options"])
        raise RuntimeError("stop before actual map processing")
    manager = _manager(request.workspace_root, preparation_runner=unavailable)
    clone_request = WorkspaceCloneRequest(source_project_id=request.project_id, target_project_id="clone-route",
        source_project_root=source, workspace_root=request.workspace_root,
        allow_network_fetch=False, network_mode="no-network", seed_imagery_cache=False)
    job = manager.submit_clone(clone_request, "raw-project-pbf")
    failed = _terminal(manager, job["job_id"])
    assert failed["stage"] == "prepare" and failed["workspace_available"] is True
    assert seen[0]["osm_pbf_path"] == str(pbf)
    envelope = json.loads(Path(failed["refs"]["request"]).read_text())
    pbf_bindings = [row for row in envelope["source_bindings"] if row["role"] == "local_osm_pbf"]
    assert pbf_bindings == [{"path": str(pbf), "role": "local_osm_pbf",
        "sha256": hashlib.sha256(pbf.read_bytes()).hexdigest(), "hash_basis": "file_content"}]
    pbf.write_bytes(b"changed original source")
    before = _snapshot(tmp_path)
    with pytest.raises(DashboardPreparationJobConflict) as conflict:
        manager.resume(job["job_id"])
    assert conflict.value.code == "source_changed"
    assert _snapshot(tmp_path) == before


def test_v2_crs_metadata_is_bound_and_changed_evidence_blocks_resume(tmp_path):
    from pretrip_models import DtmRasterSource
    request = _request(tmp_path)
    raster = tmp_path / "source.tif"
    metadata = tmp_path / "Metadata.xml"
    raster.write_bytes(b"synthetic raw raster")
    metadata.write_text("<metadata><crs>EPSG:3826</crs></metadata>")
    request = replace(request, dtm_raster_sources=(DtmRasterSource(
        path=str(raster), role="terrain_dtm", sha256=hashlib.sha256(raster.read_bytes()).hexdigest(),
        crs="EPSG:3826", source_resolution_m=20.0, crs_evidence=str(metadata),
        crs_evidence_sha256=hashlib.sha256(metadata.read_bytes()).hexdigest()),))
    def unavailable(*args, **kwargs):
        raise RuntimeError("fixture prep failure")
    manager = _manager(request.workspace_root, preparation_runner=unavailable)
    job = manager.submit_import(request, "crs-evidence")
    failed = _terminal(manager, job["job_id"])
    envelope = json.loads(Path(failed["refs"]["request"]).read_text())
    evidence = [row for row in envelope["source_bindings"] if row["role"] == "dtm_crs_evidence"]
    assert evidence == [{"path": str(metadata), "role": "dtm_crs_evidence",
        "sha256": hashlib.sha256(metadata.read_bytes()).hexdigest(), "hash_basis": "file_content"}]
    metadata.write_text("<metadata><crs>EPSG:4326</crs></metadata>")
    before = _snapshot(tmp_path)
    with pytest.raises(DashboardPreparationJobConflict) as conflict:
        manager.resume(job["job_id"])
    assert conflict.value.code == "source_changed"
    assert _snapshot(tmp_path) == before


def test_v2_import_resolves_material_relative_pbf_using_shared_resolver(tmp_path):
    request = _request(tmp_path)
    material = tmp_path / "material"
    material.mkdir()
    pbf = material / "original.osm.pbf"
    pbf.write_bytes(b"synthetic material PBF")
    (material / "material_manifest.json").write_text(json.dumps({"sources": {
        "local_osm_pbf": {"path": pbf.name, "sha256": hashlib.sha256(pbf.read_bytes()).hexdigest()},
    }}))
    request = replace(request, material_root=material)
    manager = _manager(request.workspace_root)
    job = manager.submit_import(request, "material-relative-pbf")
    completed = _terminal(manager, job["job_id"])
    assert completed["status"] == "completed"
    envelope = json.loads(Path(completed["refs"]["request"]).read_text())
    assert [row["path"] for row in envelope["source_bindings"] if row["role"] == "local_osm_pbf"] == [str(pbf)]


def test_real_import_and_common_preparation_helper_use_the_durable_job_entrypoint(tmp_path, monkeypatch):
    import dashboard_workspace_preparation as preparation
    request = _request(tmp_path)
    prepared = []
    def fixture_layers(value):
        prepared.append(value)
        return _ready()
    monkeypatch.setattr(preparation, "run_layer_preparation", fixture_layers)
    manager = DashboardPreparationJobManager(request.workspace_root, initializer=_initialized)
    job = manager.submit_import(request, "real-import-fixture-layers", preparation_options={
        "allow_network_fetch": False, "network_mode": "no-network", "seed_imagery_cache": False,
        "prepare_cwa_imagery": False,
    })
    completed = _terminal(manager, job["job_id"], timeout=120)
    assert completed["status"] == "completed", completed.get("error")
    root = request.workspace_root / request.project_id
    import_manifest = json.loads((root / "outputs/import_manifest.json").read_text())
    assert import_manifest["project_id"] == request.project_id
    assert len(prepared) == 1 and prepared[0].project_root == root
    assert prepared[0].allow_network_fetch is False and prepared[0].seed_imagery_cache is False
    assert prepared[0].run_qgis_terrain_workflow is True
    assert prepared[0].run_post_layer_enrichments is True
    assert prepared[0].run_map_preparation_spec_artifacts is True
    assert prepared[0].publish_preparation_outputs is True


@dataclass
class _ClonePreparation:
    project_id: str
    project_root: Path
    allow_network_fetch: bool = False
    network_mode: str = "no-network"
    seed_imagery_cache: bool = False


def test_clone_resume_uses_effective_options_and_never_calls_clone_again(tmp_path):
    from dashboard_workspace_clone import WorkspaceCloneRequest
    from pretrip_import import PretripImportRequest
    request = _request(tmp_path, "source-route")
    _import(request)
    source = request.workspace_root / request.project_id
    reference = source / "inbox/gpx/ref.gpx"
    reference.write_text('<gpx><trk><trkseg><trkpt lat="24" lon="121"/></trkseg></trk></gpx>')
    manifest = json.loads((source / "inbox/source_manifest.json").read_text())
    manifest["sources"].append({"role": "reference_track", "workspace_ref": "inbox/gpx/ref.gpx",
                                "sha256": hashlib.sha256(reference.read_bytes()).hexdigest()})
    (source / "inbox/source_manifest.json").write_text(json.dumps(manifest))
    calls, seen = [], []
    def clone(value, *, import_runner, preparation_runner):
        calls.append("clone")
        import_runner(PretripImportRequest(project_id=value.target_project_id,
            primary_gpx=source / "inbox/gpx/primary.gpx", workspace_root=value.workspace_root))
        return preparation_runner(_ClonePreparation(value.target_project_id, value.workspace_root / value.target_project_id))
    def prepare(root, **kwargs):
        calls.append("prepare")
        seen.append(kwargs["preparation_options"])
        if len(seen) == 1:
            raise RuntimeError("synthetic clone preparation failure")
        return _ready()
    manager = _manager(request.workspace_root, clone_runner=clone, preparation_runner=prepare)
    clone_request = WorkspaceCloneRequest(source_project_id=request.project_id, target_project_id="clone-route",
        source_project_root=source, workspace_root=request.workspace_root, allow_network_fetch=False, network_mode="no-network")
    job = manager.submit_clone(clone_request, "clone-resume")
    assert _terminal(manager, job["job_id"])["can_resume"] is True
    manager.resume(job["job_id"])
    assert _terminal(manager, job["job_id"])["status"] == "completed"
    assert calls == ["clone", "prepare", "prepare"]
    assert seen[0] == seen[1]
    assert seen[1]["allow_network_fetch"] is False and seen[1]["seed_imagery_cache"] is False
