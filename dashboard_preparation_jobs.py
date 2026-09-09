"""Durable, explicitly resumed Dashboard preparation jobs.

The ledger is separate from each workspace. GET derives interrupted state from
the target lease without writing; only submit, resume and workers mutate it.
Completed imports are reused only with their recorded GPX inputs intact.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import threading
from typing import Any, Callable, Iterator
import uuid
import xml.etree.ElementTree as ET


_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_JOB_ID = re.compile(r"^prep\.[a-f0-9]{32}$")
_ACTIVE = {"queued", "running"}
_RESUMABLE = {"failed", "interrupted", "completed_with_gaps"}
_SOURCE_BINDING_VERSION = 2
_BOUNDARY = {"candidate_only": True, "runtime_safety_truth": False,
             "departure_approval_granted": False, "runtime_mutated": False}


class DashboardPreparationJobConflict(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value.expanduser().resolve())
    if callable(getattr(value, "model_dump", None)):
        return _json_value(value.model_dump(mode="json"))
    if is_dataclass(value):
        return {field.name: _json_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


def _encoded(value: Any) -> bytes:
    return _encoded_json(_json_value(value))


def _encoded_json(value: Any) -> bytes:
    """Canonical bytes for values already decoded from JSON (no model walk)."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_encoded(value)).hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise DashboardPreparationJobConflict("invalid_job_record", "Expected an object in the job ledger.")
    return payload


def _atomic_write(path: Path, payload: dict[str, Any], *, immutable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _encoded(payload) + b"\n"
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if immutable:
            os.link(temporary, path)
            temporary.unlink()
        else:
            os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()


def _default_import(request: Any) -> dict[str, Any]:
    from pretrip_import import run_pretrip_import
    return run_pretrip_import(request)


def _default_clone(request: Any, **runners: Any) -> dict[str, Any]:
    from dashboard_workspace_clone import clone_pretrip_workspace_from_inputs
    return clone_pretrip_workspace_from_inputs(request, **runners)


def _default_prepare(project_root: Path, **options: Any) -> dict[str, Any]:
    from dashboard_workspace_preparation import prepare_imported_workspace
    return prepare_imported_workspace(project_root, **options)


def _default_initialize(project_root: Path) -> dict[str, Any]:
    from scout_contextual_permission_initialization import ensure_contextual_permission_authoring
    return ensure_contextual_permission_authoring(project_root)


class DashboardPreparationJobManager:
    def __init__(
        self, workspace_root: Path, *,
        import_runner: Callable[..., dict[str, Any]] | None = None,
        clone_runner: Callable[..., dict[str, Any]] | None = None,
        preparation_runner: Callable[..., dict[str, Any]] | None = None,
        initializer: Callable[..., dict[str, Any]] | None = None,
        background_start: Callable[[Callable[[], None]], Any] | None = None,
    ) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.root = self.workspace_root / ".scout-preparation-jobs"
        self.import_runner = import_runner or _default_import
        self.clone_runner = clone_runner or _default_clone
        self.preparation_runner = preparation_runner or _default_prepare
        self.initializer = initializer or _default_initialize
        self.background_start = background_start or self._thread_start
        self._source_hash_cache: dict[str, tuple[tuple[int, ...], str]] = {}

    @staticmethod
    def _thread_start(callback: Callable[[], None]) -> None:
        threading.Thread(target=callback, name="dashboard-preparation", daemon=True).start()

    def submit_import(
        self, request: Any, idempotency_key: str, requested_by: str = "dashboard_operator",
        preparation_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        values = _json_value(request)
        if values.get("overwrite"):
            raise DashboardPreparationJobConflict("overwrite_forbidden", "Preparation jobs never overwrite an existing import.")
        if values.get("import_stage", "pretrip") != "pretrip":
            raise DashboardPreparationJobConflict("invalid_import_stage", "This job prepares pretrip workspaces only.")
        options = _json_value(preparation_options or {})
        if {"project_id", "project_root", "workspace_root"} & options.keys():
            raise DashboardPreparationJobConflict("preparation_target_override", "Preparation options cannot change the job target.")
        return self._submit("import", values, idempotency_key, requested_by, options)

    def submit_clone(self, request: Any, idempotency_key: str) -> dict[str, Any]:
        values = _json_value(request)
        options = {key: value for key, value in values.items() if key not in {
            "source_project_id", "target_project_id", "source_project_root", "workspace_root", "requested_by"}}
        return self._submit("clone", values, idempotency_key,
                            values.get("requested_by", "dashboard_operator"), options)

    def _submit(self, kind: str, values: dict[str, Any], key: str,
                requested_by: str, options: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(key, str) or not key.strip() or len(key) > 256:
            raise DashboardPreparationJobConflict("invalid_idempotency_key", "A non-empty idempotency key of at most 256 characters is required.")
        project_id = values["project_id" if kind == "import" else "target_project_id"]
        target = self._target(project_id)
        if Path(values["workspace_root"]).resolve() != self.workspace_root:
            raise DashboardPreparationJobConflict("workspace_root_mismatch", "The request must use the configured workspace root.")
        if kind == "clone":
            source_id = values["source_project_id"]
            if self._target(source_id) != Path(values["source_project_root"]).resolve() or source_id == project_id:
                raise DashboardPreparationJobConflict("invalid_clone_source", "Clone source must be a different workspace in this root.")
        request = {"kind": kind, "request": values, "requested_by": requested_by,
                   "preparation_options": options}
        request_sha = _digest(request)
        job_id = "prep." + hashlib.sha256(key.encode()).hexdigest()[:32]
        with self._registry_lock():
            state_path = self._directory(job_id) / "state.json"
            if state_path.is_file():
                existing = self._load(job_id)
                if existing["request_sha256"] != request_sha:
                    raise DashboardPreparationJobConflict("idempotency_conflict", "This idempotency key already binds another request.")
                return self.get(job_id)
            if target.exists() or any(item["project_id"] == project_id for item in self._states()):
                raise DashboardPreparationJobConflict("target_exists", "This target is already reserved or exists; use its existing job and explicit Resume.")
            lease = self._acquire_target(project_id, create=True)
            if lease is None:
                raise DashboardPreparationJobConflict("target_busy", "Another process is preparing this target.")
            try:
                binding_request = {**request, "source_binding_version": _SOURCE_BINDING_VERSION}
                bindings = self._source_bindings(binding_request)
                for binding in bindings:
                    if binding["role"] in {"golden_gpx", "reference_gpx"}:
                        self._validate_gpx(Path(binding["path"]))
                envelope = {**binding_request, "source_bindings": bindings, "source_sha256": _digest(bindings)}
                directory = self._directory(job_id)
                directory.mkdir()
                _atomic_write(directory / "request.json", envelope, immutable=True)
                state = {"schema_version": "dashboardPreparationJob.v1", "job_id": job_id,
                         "kind": kind, "project_id": project_id, "project_root": str(target),
                         "status": "queued", "stage": "import", "attempt": 1,
                         "created_at": _now(), "updated_at": _now(), "requested_by": requested_by,
                         "request_sha256": request_sha, "request_record_sha256": _digest(envelope),
                         "source_binding_version": _SOURCE_BINDING_VERSION,
                         "source_sha256": envelope["source_sha256"], "stages": {}, "error": None,
                         "refs": {"request": str(directory / "request.json")}, **_BOUNDARY}
                self._write_state(state)
            except BaseException:
                self._release(lease)
                raise
            self._start(job_id, lease)
        return self.get(job_id)

    def get(self, job_id: str) -> dict[str, Any]:
        state = self._read_state(job_id)
        if state["status"] in _ACTIVE:
            lease = self._acquire_target(state["project_id"], create=False)
            if lease is not None:
                try:
                    state = self._read_state(job_id)
                    if state["status"] in _ACTIVE:
                        state = {**state, "persisted_status": state["status"], "status": "interrupted",
                                 "error": {"code": "worker_interrupted", "message": "The worker lease ended before a terminal checkpoint; explicitly resume this job.", "retryable": True}}
                finally:
                    self._release(lease)
        # Validate the final observed snapshot once, including non-resumable
        # jobs. Resume still revalidates the request and raw sources under lease.
        envelope = self._envelope(state)
        state["can_resume"] = False
        state["workspace_available"] = (
            state["stages"].get("import", {}).get("status") == "completed"
            and (Path(state["project_root"]) / "project.json").is_file()
        )
        if state["status"] in _RESUMABLE:
            try:
                self._observe_resume_eligibility(state, envelope=envelope)
                state["can_resume"] = True
                state["resume_validation"] = "required_before_writes"
            except (DashboardPreparationJobConflict, OSError) as exc:
                state["resume_blocker"] = {"code": getattr(exc, "code", "source_unavailable"),
                                           "message": str(exc) if isinstance(exc, DashboardPreparationJobConflict) else "A bound input is unavailable."}
        return state

    def list(self, project_id: str | None = None) -> list[dict[str, Any]]:
        if project_id is not None:
            self._target(project_id)
        values = [self.get(path.parent.name) for path in sorted(self.root.glob("prep.*/state.json"))]
        if project_id is not None:
            values = [item for item in values if item["project_id"] == project_id]
        return sorted(values, key=lambda item: (item["created_at"], item["job_id"]), reverse=True)

    def resume(self, job_id: str) -> dict[str, Any]:
        with self._registry_lock():
            observed = self.get(job_id)
            if observed["status"] in _ACTIVE:
                return observed
            if observed["status"] not in _RESUMABLE:
                raise DashboardPreparationJobConflict("job_not_resumable", "This job has no unfinished stage to resume.")
            # Terminal state is published just before the worker releases its
            # target lease. The registry lock prevents a concurrent resumer;
            # wait for that worker's final fsync instead of rejecting a valid
            # immediate Resume in the terminal-publication window.
            lease = self._acquire_target(observed["project_id"], create=True, blocking=True)
            if lease is None:
                raise DashboardPreparationJobConflict("target_busy", "Another worker owns this target.")
            try:
                state = self._load(job_id)
                if state["status"] in _ACTIVE and (
                    observed["status"] != "interrupted" or state["attempt"] != observed["attempt"]
                ):
                    raise DashboardPreparationJobConflict(
                        "job_already_resumed", "The job advanced while its lease was acquired; refresh its current state.")
                self._validate_resume(state)
                state.update(status="queued", error=None, attempt=state["attempt"] + 1,
                             resumed_at=_now())
                self._write_state(state)
            except BaseException:
                self._release(lease)
                raise
            self._start(job_id, lease)
        return self.get(job_id)

    def _start(self, job_id: str, lease: int) -> None:
        try:
            self.background_start(lambda: self._run(job_id, lease))
        except Exception:
            state = self._load(job_id)
            state.update(status="interrupted", error={"code": "worker_start_failed", "message": "The background worker did not start.", "retryable": True})
            self._write_state(state)
            self._release(lease)
            raise

    def _run(self, job_id: str, lease: int) -> None:
        try:
            state = self._load(job_id)
            envelope = self._envelope(state)
            self._verify_sources(envelope)
            state.update(status="running", error=None)
            self._write_state(state)
            imported = state["stages"].get("import", {}).get("status") == "completed"
            if imported:
                self._verify_import(state)
            elif envelope["kind"] == "clone":
                def clone_import(request: Any) -> dict[str, Any]:
                    return self._run_import(state, request)

                def clone_prepare(request: Any) -> dict[str, Any]:
                    from dashboard_workspace_preparation import PREPARATION_OPTION_FIELDS
                    raw_options = _json_value(request)
                    options = {key: value for key, value in raw_options.items() if key in PREPARATION_OPTION_FIELDS}
                    # The effective options are an immutable checkpoint, reused
                    # on resume instead of deriving altered Clone defaults.
                    path = self._directory(job_id) / "effective-preparation.json"
                    _atomic_write(path, {"options": options}, immutable=True)
                    state["effective_preparation_sha256"] = _file_hash(path)
                    state["refs"]["effective_preparation"] = str(path)
                    self._write_state(state)
                    return self._run_prepare(state, options)

                clone_result = self.clone_runner(self._restore(envelope), import_runner=clone_import,
                                                 preparation_runner=clone_prepare)
                self._receipt(state, "clone", clone_result)
            else:
                self._run_import(state, self._restore(envelope))
            if state["stages"].get("prepare", {}).get("status") != "completed" or (imported and state.get("preparation_has_gaps")):
                options = self._preparation_options(state, envelope)
                self._run_prepare(state, options)
            self._verify_sources(envelope)
            self._stage(state, "permission_init")
            initialized = self.initializer(Path(state["project_root"]))
            self._receipt(state, "permission_init", initialized)
            initialization_status = str(initialized.get("status", "unknown"))
            init_ready = (
                initialization_status in {"ready", "initialized", "already_initialized", "already_ready", "reviewed_baseline_preserved", "preserved_reviewed_baseline"}
                and initialized.get("authoring_ready", True) is True
            )
            gaps = bool(state.get("preparation_has_gaps")) or not init_ready
            state.update(status="completed_with_gaps" if gaps else "completed", stage="complete",
                         completed_at=_now(), error=({"code": "preparation_incomplete", "message": "Preparation or Permission initialization retained explicit gaps; inspect the stage receipts.", "retryable": True} if gaps else None))
            self._write_state(state)
        except Exception as exc:
            state = self._load(job_id)
            from pretrip_import import PretripPreparationInputError
            source_error = exc
            while source_error is not None and not isinstance(source_error, PretripPreparationInputError):
                source_error = source_error.__cause__
            code = (exc.code if isinstance(exc, DashboardPreparationJobConflict)
                    else source_error.code if source_error is not None
                    else f"{state['stage']}_failed")
            message = str(exc) if isinstance(exc, DashboardPreparationJobConflict) else f"The {state['stage']} stage failed ({type(exc).__name__}); inspect its recorded artifacts."
            state.update(status="failed", error={"code": code, "message": message, "retryable": code not in {"source_changed", "import_changed"}})
            if source_error is not None:
                state["error"]["details"] = source_error.to_dict()
            from pydantic import ValidationError
            validation_error = exc
            while validation_error is not None and not isinstance(validation_error, ValidationError):
                validation_error = validation_error.__cause__
            if validation_error is not None:
                # Pydantic's input and validator context may contain an entire
                # source record (or arbitrary exception text). Retain field
                # locations/types; do not persist raw inputs, URLs or context.
                errors = validation_error.errors(include_input=False, include_url=False,
                                                  include_context=False)
                for item in errors:
                    if item["type"] in {"value_error", "assertion_error"}:
                        item["msg"] = "The field did not satisfy its declared validator."
                state["error"].setdefault("details", {})["validation_errors"] = errors
            self._receipt(state, state["stage"], {"status": "failed", "error": state["error"]}, completed=False)
            self._write_state(state)
        finally:
            self._release(lease)

    def _run_import(self, state: dict[str, Any], request: Any) -> dict[str, Any]:
        self._verify_sources(self._envelope(state))
        if Path(state["project_root"]).exists():
            raise DashboardPreparationJobConflict("unverified_existing_import", "An existing target has no completed import checkpoint; it will not be overwritten.")
        self._stage(state, "import")
        result = self.import_runner(request)
        root = Path(state["project_root"])
        source_manifest = root / "inbox/source_manifest.json"
        if not (root / "project.json").is_file() or not source_manifest.is_file():
            raise DashboardPreparationJobConflict("import_checkpoint_missing", "Import did not produce the workspace and source manifest required for safe resume.")
        imported = _read(source_manifest)
        bindings = []
        for row in imported.get("sources", []):
            path = self._workspace_file(root, row["workspace_ref"])
            if _file_hash(path) != row["sha256"]:
                raise DashboardPreparationJobConflict("import_changed", "An imported GPX does not match its source manifest.")
            bindings.append({"ref": row["workspace_ref"], "sha256": row["sha256"]})
        for path in sorted((root / "normalized/routes/filtered").glob("*.gpx")):
            bindings.append({"ref": str(path.relative_to(root)), "sha256": _file_hash(path)})
        if not bindings:
            raise DashboardPreparationJobConflict("import_checkpoint_missing", "Import produced no bound GPX sources.")
        state["import_checkpoint"] = {"source_contract_sha256": self._source_contract(imported),
                                       "bindings": bindings}
        self._receipt(state, "import", result)
        return result

    def _run_prepare(self, state: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
        envelope = self._envelope(state)
        self._verify_sources(envelope)
        self._verify_import(state)
        # All targets use one backend QGIS worker. Hold the target lease while
        # waiting, so observation can distinguish a queued resource from a dead
        # worker. A process exit releases both OS leases without a PID heuristic.
        state["stage"] = "waiting_for_preparation_slot"
        state["stages"]["prepare"] = {"status": "waiting_for_preparation_slot",
            "queued_at": _now(), "attempt": state["attempt"]}
        self._write_state(state)
        descriptor = os.open(self.root / ".preparation.lock",
                             os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            # The source may have changed while another project held the slot.
            self._verify_sources(envelope)
            self._verify_import(state)
            self._stage(state, "prepare")
            result = self.preparation_runner(Path(state["project_root"]),
                        source_project_id=envelope["request"].get("source_project_id"),
                        requested_by=envelope["requested_by"], preparation_options=options)
        finally:
            self._release(descriptor)
        validation = result.get("validation", {}).get("status", result.get("status", "unknown"))
        from pretrip_layer_preparation import DEFAULT_LAYERS
        qgis = result.get("qgis_terrain_feature_stack")
        terrain_requested = "terrain" in options.get("layers", DEFAULT_LAYERS)
        qgis_gap = terrain_requested and (not isinstance(qgis, dict) or qgis.get("status") != "completed")
        state["preparation_has_gaps"] = validation not in {"ready", "completed", "pass", "ok"} or qgis_gap
        self._receipt(state, "prepare", result)
        return result

    def _preparation_options(self, state: dict[str, Any], envelope: dict[str, Any]) -> dict[str, Any]:
        ref = state["refs"].get("effective_preparation")
        if ref:
            path = Path(ref)
            if path.parent != self._directory(state["job_id"]) or _file_hash(path) != state["effective_preparation_sha256"]:
                raise DashboardPreparationJobConflict("request_changed", "The saved preparation options changed.")
            return _read(path)["options"]
        return envelope["preparation_options"]

    def _stage(self, state: dict[str, Any], stage: str) -> None:
        state["stage"] = stage
        state["stages"][stage] = {"status": "running", "started_at": _now(), "attempt": state["attempt"]}
        self._write_state(state)

    def _receipt(self, state: dict[str, Any], stage: str, result: dict[str, Any], *, completed: bool = True) -> None:
        path = self._directory(state["job_id"]) / "receipts" / f"{stage}.{state['attempt']}.{uuid.uuid4().hex}.json"
        payload = {"job_id": state["job_id"], "stage": stage, "attempt": state["attempt"],
                   "request_sha256": state["request_sha256"], "source_sha256": state["source_sha256"],
                   "source_binding_version": state.get("source_binding_version", 1),
                   "recorded_at": _now(), "result": _json_value(result), **_BOUNDARY}
        _atomic_write(path, payload, immutable=True)
        state["stages"][stage] = {"status": "completed" if completed else "failed",
                                  "completed_at": payload["recorded_at"], "attempt": state["attempt"],
                                  "receipt_ref": str(path), "receipt_sha256": _file_hash(path)}
        state["refs"][stage] = str(path)
        self._write_state(state)

    def _validate_resume(self, state: dict[str, Any]) -> None:
        self._observe_resume_eligibility(state)
        envelope = self._envelope(state)
        self._verify_sources(envelope)
        if state["stages"].get("import", {}).get("status") == "completed":
            self._verify_import(state)
            options = self._preparation_options(state, envelope)
            if envelope.get("source_binding_version", 1) == 1:
                path = self._explicit_pbf_path({**envelope, "preparation_options": options})
                if path is not None:
                    self._require_legacy_file_binding(envelope, [path], "PBF")
        elif Path(state["project_root"]).exists():
            raise DashboardPreparationJobConflict("import_outcome_unverified", "The target exists without a completed import checkpoint; inspect it before starting another job. It will not be overwritten.")

    def _observe_resume_eligibility(self, state: dict[str, Any], *,
                                    envelope: dict[str, Any] | None = None) -> None:
        """Status GET is an eligibility observation, never content validation.

        A cold process must not rehash a country DEM/PBF, discover new sources,
        or invoke an input resolver to render a job list. Explicit Resume owns
        those checks under its leases before any persisted event or writer.
        """
        if envelope is None:
            envelope = self._envelope(state)
        self._validate_binding_version(envelope)
        if int(envelope.get("source_binding_version", 1)) == 1:
            options = self._preparation_options(state, envelope)
            explicit_pbf = self._explicit_pbf_path({**envelope, "preparation_options": options})
            if explicit_pbf is not None:
                self._require_legacy_file_binding(envelope, [explicit_pbf], "PBF")
            elif "osm_pbf_path" not in options and envelope["kind"] == "clone" and not any(
                item.get("role") == "material_manifest" for item in envelope["source_bindings"]
            ):
                # Legacy Clone can have raw PBF metadata in its source project,
                # without any material declaration in the submitted snapshot.
                # This small JSON read identifies an upgrade without opening
                # the PBF or asking the full DEM/source resolver to run.
                source = Path(envelope["request"]["source_project_root"])
                project = _read(source / "project.json")
                if project.get("osm_pbf_source_ref"):
                    path = Path(project["osm_pbf_source_ref"]).expanduser()
                    path = path if path.is_absolute() else source / path
                    self._require_legacy_file_binding(envelope, [path.resolve()], "PBF")
        root = Path(state["project_root"])
        if state["stages"].get("import", {}).get("status") == "completed":
            if not state.get("import_checkpoint", {}).get("bindings"):
                raise DashboardPreparationJobConflict("import_checkpoint_missing", "The completed import has no source checkpoint.")
            if not (root / "project.json").is_file() or not (root / "inbox/source_manifest.json").is_file():
                raise DashboardPreparationJobConflict("import_changed", "The imported workspace metadata is unavailable.")
        elif root.exists():
            raise DashboardPreparationJobConflict("import_outcome_unverified", "The target exists without a completed import checkpoint; inspect it before starting another job. It will not be overwritten.")

    def _verify_import(self, state: dict[str, Any]) -> None:
        root = Path(state["project_root"])
        checkpoint = state.get("import_checkpoint", {})
        if _read(root / "project.json").get("project_id") != state["project_id"]:
            raise DashboardPreparationJobConflict("import_changed", "The imported workspace identity changed.")
        if self._source_contract(_read(root / "inbox/source_manifest.json")) != checkpoint.get("source_contract_sha256"):
            raise DashboardPreparationJobConflict("import_changed", "The imported source manifest changed.")
        for row in checkpoint.get("bindings", []):
            if _file_hash(self._workspace_file(root, row["ref"])) != row["sha256"]:
                raise DashboardPreparationJobConflict("import_changed", "An imported GPX changed after its completed checkpoint.")

    @staticmethod
    def _source_contract(manifest: dict[str, Any]) -> str:
        return _digest({"project_id": manifest.get("project_id"), "sources": [
            {key: row.get(key) for key in ("role", "workspace_ref", "sha256", "original_path")}
            for row in manifest.get("sources", [])]})

    def _verify_sources(self, envelope: dict[str, Any]) -> None:
        self._validate_binding_version(envelope)
        pbf_paths: list[Path] = []
        crs_paths: list[Path] = []
        try:
            current = self._source_bindings(envelope, discovered_pbf_paths=pbf_paths,
                                           discovered_crs_paths=crs_paths)
        except (OSError, ValueError, KeyError) as exc:
            raise DashboardPreparationJobConflict("source_changed", "A bound preparation input is no longer available.") from exc
        if _digest(current) != envelope["source_sha256"]:
            raise DashboardPreparationJobConflict("source_changed", "A bound preparation input changed; this job cannot reinterpret its immutable request.")
        if envelope.get("source_binding_version", 1) == 1:
            self._require_legacy_file_binding(envelope, pbf_paths, "PBF")
            self._require_legacy_file_binding(envelope, crs_paths, "CRS metadata")

    @staticmethod
    def _validate_binding_version(envelope: dict[str, Any]) -> None:
        if envelope.get("source_binding_version", 1) not in {1, _SOURCE_BINDING_VERSION}:
            raise DashboardPreparationJobConflict("source_binding_version_unsupported", "This source binding version cannot be resumed by the current manager.")

    def _explicit_pbf_path(self, envelope: dict[str, Any]) -> Path | None:
        raw = envelope.get("preparation_options", {}).get("osm_pbf_path")
        if raw is None:
            return None
        path = Path(raw).expanduser()
        if not path.is_absolute():
            key = "project_id" if envelope["kind"] == "import" else "target_project_id"
            path = self._target(envelope["request"][key]) / path
        return path.resolve()

    @staticmethod
    def _require_legacy_file_binding(envelope: dict[str, Any], paths: list[Path], source_label: str) -> None:
        bound = {item["path"] for item in envelope.get("source_bindings", [])
                 if item.get("hash_basis") == "file_content"}
        if any(str(path.resolve()) not in bound for path in paths):
            raise DashboardPreparationJobConflict(
                "source_binding_upgrade_required",
                f"This legacy job did not bind the declared {source_label} content at submission. "
                "Keep this job for evidence and submit the complete sources as a new workspace "
                "with a new name; Resume cannot establish the missing historical checksum.")

    def _source_bindings(self, envelope: dict[str, Any], *,
                         discovered_pbf_paths: list[Path] | None = None,
                         discovered_crs_paths: list[Path] | None = None) -> list[dict[str, Any]]:
        self._validate_binding_version(envelope)
        binding_version = envelope.get("source_binding_version", 1)
        options = envelope.get("preparation_options", {})
        values = envelope["request"]
        paths: dict[str, str] = {}
        directories: dict[str, dict[str, Any]] = {}
        def bind(path: Path, role: str) -> None:
            resolved = path.expanduser().resolve()
            if not resolved.is_file():
                raise FileNotFoundError("A declared preparation source is missing.")
            paths[str(resolved)] = role
        def bind_directory(path: Path, role: str) -> None:
            resolved = path.expanduser().resolve()
            if not resolved.is_dir():
                raise FileNotFoundError("A declared preparation source directory is missing.")
            entries = []
            for item in sorted(resolved.rglob("*")):
                if item.is_file():
                    bind(item, role + "_file")
                    entries.append(str(item.relative_to(resolved)))
            directories[str(resolved)] = {"path": str(resolved), "role": role,
                "sha256": _digest(entries), "hash_basis": "directory_file_inventory"}
        def bind_material(sources: dict[str, Any]) -> None:
            for key in ("mcp_named_point_evidence", "local_osm_pbf"):
                if key == "local_osm_pbf" and binding_version >= 2:
                    continue  # Version 2 binds the effective explicit/default PBF below.
                value = sources.get(key)
                path = value.get("path") if isinstance(value, dict) else value
                if path:
                    bind(Path(path), key)
        def record_pbf(path: Path | None) -> None:
            if path is not None:
                path = path.expanduser().resolve()
                if discovered_pbf_paths is not None:
                    discovered_pbf_paths.append(path)
                if binding_version >= 2:
                    bind(path, "local_osm_pbf")
        def record_crs(raster: dict[str, Any]) -> None:
            if raster.get("crs_evidence_sha256"):
                path = Path(raster["crs_evidence"]).expanduser().resolve()
                if discovered_crs_paths is not None:
                    discovered_crs_paths.append(path)
                if binding_version >= 2:
                    bind(path, "dtm_crs_evidence")
        if envelope["kind"] == "import":
            bind(Path(values["primary_gpx"]), "golden_gpx")
            references = [Path(path) for path in values.get("reference_gpx_paths", [])]
            if values.get("reference_dir"):
                directory = Path(values["reference_dir"])
                if not directory.is_dir():
                    raise FileNotFoundError("The reference GPX directory is unavailable.")
                references.extend(sorted(directory.glob("*.gpx")))
            for path in references:
                if path.resolve() != Path(values["primary_gpx"]).resolve():
                    bind(path, "reference_gpx")
            from pretrip_import import _preparation_source_inputs, _resolve_mcp_named_point_evidence
            restored = self._restore(envelope)
            preparation_inputs = _preparation_source_inputs(restored)
            material_sources = {}
            if preparation_inputs.get("material_manifest_path"):
                manifest_path = Path(preparation_inputs["material_manifest_path"])
                bind(manifest_path, "material_manifest")
                material_sources = _read(manifest_path).get("sources", {})
                bind_material(material_sources)
            from dashboard_workspace_preparation import _resolve_original_osm_pbf
            material_root = preparation_inputs.get("material_root")
            raw_pbf = _resolve_original_osm_pbf(
                root=self._target(values["project_id"]), project={},
                material_root=Path(material_root) if material_root else None,
                material_sources=material_sources, options=options)
            record_pbf(Path(raw_pbf["path"]) if raw_pbf else None)
            for directory in preparation_inputs["dtm_dirs"]:
                bind_directory(Path(directory), "dtm_directory")
            for raster in preparation_inputs["dtm_rasters"]:
                bind(Path(raster["path"]), "dtm_raster")
                record_crs(raster)
            named = _resolve_mcp_named_point_evidence(restored)
            if named is not None:
                bind(named, "named_point_evidence")
            if values.get("template_project_root"):
                bind_directory(Path(values["template_project_root"]), "import_template")
        else:
            from dashboard_workspace_clone import (_source_gpx_inputs,
                                                    _discover_declared_material_reference_gpx)
            from dashboard_workspace_preparation import resolve_workspace_preparation_inputs
            source = Path(values["source_project_root"])
            manifest = _read(source / "inbox/source_manifest.json")
            primary, references, records = _source_gpx_inputs(source, manifest)
            inputs = resolve_workspace_preparation_inputs(source, preparation_options=options)
            material_root, material = inputs.material_root, inputs.material_manifest
            references, _, _ = _discover_declared_material_reference_gpx(
                material_sources=material.get("sources", {}), primary_gpx=primary,
                reference_gpx=references, source_records=records)
            bind(source / "inbox/source_manifest.json", "clone_source_manifest")
            bind(primary, "golden_gpx")
            for path in references:
                bind(path, "reference_gpx")
            if material_root and (material_root / "material_manifest.json").is_file():
                bind(material_root / "material_manifest.json", "material_manifest")
            bind_material(material.get("sources", {}))
            raw_pbf = inputs.local_osm_pbf
            record_pbf(Path(raw_pbf["path"]) if raw_pbf else None)
            for directory in inputs.dtm_dirs:
                bind_directory(directory, "dtm_directory")
            for raster in inputs.dtm_rasters:
                bind(Path(raster["path"]), "dtm_raster")
                record_crs(raster)
        return sorted([*directories.values(), *[
            {"path": path, "role": role, "sha256": self._source_file_hash(Path(path)),
             "hash_basis": "file_content"} for path, role in paths.items()]],
            key=lambda item: (item["path"], item["role"]))

    def _source_file_hash(self, path: Path) -> str:
        metadata = path.stat()
        identity = (metadata.st_dev, metadata.st_ino, metadata.st_size,
                    metadata.st_mtime_ns, metadata.st_ctime_ns)
        cached = self._source_hash_cache.get(str(path))
        if cached and cached[0] == identity:
            return cached[1]
        value = _file_hash(path)
        after = path.stat()
        if identity != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise DashboardPreparationJobConflict("source_changed", "A preparation input changed while its content hash was recorded.")
        self._source_hash_cache[str(path)] = (identity, value)
        return value

    def _restore(self, envelope: dict[str, Any]) -> Any:
        values = dict(envelope["request"])
        if envelope["kind"] == "import":
            from pretrip_import import PretripImportRequest
            from pretrip_models import DtmRasterSource
            for key in ("primary_gpx", "workspace_root", "reference_dir", "template_project_root", "material_root", "mcp_named_point_evidence"):
                if values.get(key) is not None:
                    values[key] = Path(values[key])
            for key in ("reference_gpx_paths", "dtm_dirs"):
                values[key] = tuple(Path(item) for item in values.get(key, []))
            values["dtm_raster_sources"] = tuple(
                DtmRasterSource.model_validate(item) for item in values.get("dtm_raster_sources", []))
            return PretripImportRequest(**values)
        from dashboard_workspace_clone import WorkspaceCloneRequest
        for key in ("source_project_root", "workspace_root"):
            values[key] = Path(values[key])
        values["layers"] = tuple(values.get("layers", []))
        return WorkspaceCloneRequest(**values)

    def _envelope(self, state: dict[str, Any]) -> dict[str, Any]:
        envelope = _read(self._directory(state["job_id"]) / "request.json")
        if hashlib.sha256(_encoded_json(envelope)).hexdigest() != state["request_record_sha256"]:
            raise DashboardPreparationJobConflict("request_changed", "The immutable preparation request changed.")
        return envelope

    def _target(self, project_id: str) -> Path:
        if not isinstance(project_id, str) or not _ID.fullmatch(project_id):
            raise DashboardPreparationJobConflict("invalid_project_id", "A safe project ID is required.")
        path = (self.workspace_root / project_id).resolve()
        if path.parent != self.workspace_root:
            raise DashboardPreparationJobConflict("invalid_project_id", "The target must remain a direct child of the workspace root.")
        return path

    def _directory(self, job_id: str) -> Path:
        if not _JOB_ID.fullmatch(job_id):
            raise DashboardPreparationJobConflict("invalid_job_id", "Invalid preparation job identity.")
        path = self.root / job_id
        if path.is_symlink() or self.root.is_symlink():
            raise DashboardPreparationJobConflict("invalid_job_path", "Job records cannot be redirected with symlinks.")
        return path

    def _read_state(self, job_id: str) -> dict[str, Any]:
        result = _read(self._directory(job_id) / "state.json")
        if result.get("job_id") != job_id or result.get("project_root") != str(self._target(result["project_id"])):
            raise DashboardPreparationJobConflict("invalid_job_record", "Job identity does not match its storage target.")
        return result

    def _load(self, job_id: str) -> dict[str, Any]:
        result = self._read_state(job_id)
        self._envelope(result)
        return result

    def _states(self) -> list[dict[str, Any]]:
        if not self.root.exists():
            return []
        return [self._load(path.parent.name) for path in sorted(self.root.glob("prep.*/state.json"))]

    def _write_state(self, state: dict[str, Any]) -> None:
        state["updated_at"] = _now()
        _atomic_write(self._directory(state["job_id"]) / "state.json", state)

    @contextmanager
    def _registry_lock(self) -> Iterator[None]:
        if self.root.is_symlink():
            raise DashboardPreparationJobConflict("invalid_job_path", "Job storage cannot be a symlink.")
        self.root.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.root / ".registry.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            self._release(descriptor)

    def _acquire_target(self, project_id: str, *, create: bool, blocking: bool = False) -> int | None:
        self._target(project_id)
        path = self.root / f".target-{project_id}.lock"
        flags = os.O_RDWR | os.O_NOFOLLOW | (os.O_CREAT if create else 0)
        try:
            descriptor = os.open(path, flags, 0o600)
        except FileNotFoundError:
            # Every durable active job has a lease file. Missing lease files
            # are corruption, not permission to start another writer.
            raise DashboardPreparationJobConflict("job_lease_missing", "The preparation lease file is unavailable.") from None
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            os.close(descriptor)
            return None
        return descriptor

    @staticmethod
    def _release(descriptor: int) -> None:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)

    @staticmethod
    def _validate_gpx(path: Path) -> None:
        try:
            document = ET.parse(path)
        except (OSError, ET.ParseError) as exc:
            raise DashboardPreparationJobConflict("invalid_gpx", "A selected GPX source is not readable XML.") from exc
        if document.getroot().tag.split("}")[-1] != "gpx":
            raise DashboardPreparationJobConflict("invalid_gpx", "A selected source is not a GPX document.")

    @staticmethod
    def _workspace_file(root: Path, reference: str) -> Path:
        path = (root / reference).resolve()
        if root not in path.parents or not path.is_file():
            raise DashboardPreparationJobConflict("import_changed", "An imported source ref is missing or outside its workspace.")
        return path
