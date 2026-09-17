"""Version-bound Planned preparation and analysis jobs.

The source project and saved Planned bundles are read-only inputs. Every run
owns a separate output directory; an OS lease makes process loss observable
without a timer, PID heuristic, or a write during GET. Resume is explicit.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Callable, Literal

from pydantic import Field

from scout_planned_route_artifacts import (
    AUTHORITY, SHA_PATTERN, VERSION_PATTERN, _atomic_json, _digest, _project,
    _read_json, _safe_path, _signed, _verify_signed, canonical_bytes,
    get_planned_version,
)
from scout_planned_route_models import PlannedModel, PlannedRouteConflict


RUNS_REF = "outputs/planned_analysis/runs"
RUN_PATTERN = re.compile(r"^analysis\.[a-f0-9]{32}$")
ROLES = ("permission", "pace_fit", "architecture", "navigation", "weather", "route_context")
ACTIVE = {"queued", "running"}
TERMINAL = {"completed", "completed_with_gaps"}
SUBJECT_BINDING_KEYS = ("project_id", "version_id", "manifest_sha256", "geometry_sha256",
                        "itinerary_sha256", "review_context_revision_id", "review_context_sha256")
RESUMABLE = {"interrupted", "failed", "completed_with_gaps"}
_FILE_HASHES: dict[str, tuple[tuple[int, ...], str]] = {}


class PlannedAnalysisRunRequest(PlannedModel):
    version_id: str = Field(pattern=VERSION_PATTERN.pattern)
    expected_manifest_sha256: str = Field(pattern=SHA_PATTERN)
    expected_review_context_sha256: str | None = Field(default=None, pattern=SHA_PATTERN)
    idempotency_key: str = Field(min_length=1, max_length=200)
    explicit_confirmation: Literal[True]


class PlannedAnalysisResumeRequest(PlannedModel):
    expected_manifest_sha256: str = Field(pattern=SHA_PATTERN)
    expected_review_context_sha256: str | None = Field(default=None, pattern=SHA_PATTERN)
    idempotency_key: str = Field(min_length=1, max_length=200)
    explicit_confirmation: Literal[True]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def file_sha(path: Path, *, cached: bool = False) -> str:
    stat = path.stat()
    signature = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    key = str(path)
    if cached and key in _FILE_HASHES and _FILE_HASHES[key][0] == signature:
        return _FILE_HASHES[key][1]
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    value = digest.hexdigest()
    _FILE_HASHES[key] = signature, value
    return value


def planned_binding(bundle: dict) -> dict:
    manifest = bundle["manifest"]
    context = bundle.get("analysis_review_context")
    context_binding = ({"review_context_revision_id": context["revision_id"],
                        "review_context_sha256": context["context_sha256"]} if context else {})
    return {
        "project_id": manifest["project_id"], "version_id": manifest["version_id"],
        "manifest_sha256": manifest["manifest_sha256"],
        "manifest_file_sha256": hashlib.sha256(canonical_bytes(manifest)).hexdigest(),
        "geometry_sha256": manifest["geometry_sha256"],
        "itinerary_sha256": manifest["itinerary_sha256"],
        "review_sha256": (bundle.get("review") or {}).get("review_sha256"),
        "source_hashes": manifest["source_hashes"],
        "canonical_files": {name: manifest["files"][name]["sha256"] for name in (
            "planned.gpx", "route_axis.json", "checkpoints.json", "segments.json", "itinerary.json")},
        **context_binding, **AUTHORITY,
    }


def _producer_sources() -> dict:
    root = Path(__file__).resolve().parent
    names = ("scout_planned_analysis.py", "scout_planned_preparation.py",
             "scout_planned_analysis_inputs.py", "scout_planned_analysis_producers.py",
             "scout_planned_analysis_evidence.py", "pretrip_reference_segment_timing.py",
             "scout_route_architecture_tool.py", "scout_pace_guardian_tool.py",
             "scout_contextual_permission_tool.py", "scout_weather_window_tool.py",
             "pretrip_navigation_terrain_collection.py", "pretrip_route_context_collection.py",
             "scout_weather_integration.py", "pretrip_gpx_corpus.py", "navigation_terrain_dem.py",
             "scout_planned_review_context.py", "scout_planned_pretrip_report.py",
             "scout_route_readiness_tool.py", "scout_recorded_analysis.py", "scout_recorded_jobs.py")
    return {name: file_sha(root / name, cached=True) for name in names if (root / name).is_file()}


def _admit(root: Path, version: str, expected: str) -> dict:
    bundle = get_planned_version(root, version)
    if bundle["manifest"]["manifest_sha256"] != expected:
        raise PlannedRouteConflict("planned_analysis_manifest_changed", "Reopen the saved Planned version before preparing it.")
    if bundle["source_status"]["status"] != "current":
        raise PlannedRouteConflict("planned_analysis_sources_changed", "Saved Planned sources changed; create and review a new version.")
    if not bundle.get("review"):
        raise PlannedRouteConflict("planned_review_required", "Review the saved Planned geometry, timing and uncertainty before preparing it.")
    from scout_planned_review_context import current_planned_review_context
    bundle["analysis_review_context"] = current_planned_review_context(root, version)
    return bundle


def _default_prepare(root, bundle, run_root, *, progress):
    from scout_planned_preparation import prepare_planned_inputs
    options = {}
    mapping_path = os.environ.get("SCOUT_PLANNED_SOURCE_PATH_MAP_FILE")
    if mapping_path:
        value = json.loads(Path(mapping_path).read_text())
        if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
            raise PlannedRouteConflict("invalid_planned_source_path_map", "The server source-path mapping is invalid.")
        options["source_path_map"] = value
    return prepare_planned_inputs(root, bundle, run_root, progress=progress, **options)


def _default_analyse(root, bundle, run_root, preparation, *, progress):
    from scout_planned_analysis_producers import run_planned_analyses
    return run_planned_analyses(root, bundle, run_root, preparation, progress=progress)


class PlannedAnalysisManager:
    authority = AUTHORITY
    runs_ref = RUNS_REF
    version_pattern = VERSION_PATTERN
    worker_module = "scout_planned_analysis"

    def _admit_bundle(self, version: str, expected: str) -> dict:
        return _admit(self.root, version, expected)

    def _binding(self, bundle: dict) -> dict:
        return planned_binding(bundle)

    def __init__(self, root: Path, *, prepare: Callable | None = None,
                 analyse: Callable | None = None, launch: Callable | None = None):
        self.root, self.project_id = _project(root)
        self.prepare = prepare or _default_prepare
        self.analyse = analyse or _default_analyse
        # Test seams can run synchronously or retain a callback to simulate exit.
        self.launch = launch

    def _ref(self, run_id: str, filename: str = "") -> str:
        if not RUN_PATTERN.fullmatch(run_id):
            raise PlannedRouteConflict("invalid_planned_analysis_run", "Invalid Planned analysis run ID.")
        return f"{self.runs_ref}/{run_id}" + (f"/{filename}" if filename else "")

    @contextmanager
    def _registry(self):
        path = _safe_path(self.root, f"{self.runs_ref}/.registry.lock")
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _lease(self, version_id: str, *, create: bool = False) -> int | None:
        if not self.version_pattern.fullmatch(version_id):
            raise PlannedRouteConflict("invalid_planned_version", "Invalid Planned version ID.")
        path = _safe_path(self.root, f"{self.runs_ref}/.{version_id}.lease")
        try:
            fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | (os.O_CREAT if create else 0), 0o600)
        except FileNotFoundError:
            return -1
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return None
        return fd

    @staticmethod
    def _release(fd):
        if fd is not None and fd >= 0:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _read(self, run_id: str) -> dict:
        state = _read_json(self.root, self._ref(run_id, "state.json"))
        _verify_signed(state, "state_sha256")
        if (state.get("run_id") != run_id or state.get("project_id") != self.project_id
                or state.get("candidate_only") is not True or state.get("runtime_safety_truth") is not False):
            raise PlannedRouteConflict("planned_analysis_binding_mismatch", "The analysis record does not belong to this project.")
        return state

    def _write(self, state: dict) -> None:
        state.pop("state_sha256", None)
        state["updated_at"] = _now()
        _atomic_json(self.root, self._ref(state["run_id"], "state.json"), _signed(state, "state_sha256"))

    def _bound_bundle(self, state: dict) -> dict:
        bundle = self._admit_bundle(state["version_id"], state["manifest_sha256"])
        if self._binding(bundle) != state["binding"]:
            raise PlannedRouteConflict("planned_analysis_binding_changed", "The Planned source or planning review changed after this run was created.")
        return bundle

    def submit(self, request: PlannedAnalysisRunRequest) -> dict:
        run_id = "analysis." + _digest({"project": self.project_id, "key": request.idempotency_key})[:32]
        command_sha = _digest(request.model_dump(mode="json"))
        with self._registry():
            if _safe_path(self.root, self._ref(run_id, "state.json")).is_file():
                existing = self._read(run_id)
                if existing["command_sha256"] != command_sha:
                    raise PlannedRouteConflict("planned_idempotency_conflict", "This analysis key already identifies another request.")
                return self.get(run_id)
            bundle = self._admit_bundle(request.version_id, request.expected_manifest_sha256)
            if getattr(request, "expected_review_context_sha256", None) != (bundle.get("analysis_review_context") or {}).get("context_sha256"):
                raise PlannedRouteConflict("planned_review_context_changed", "Refresh the supplement before starting analysis.")
            lease = self._lease(request.version_id, create=True)
            if lease is None:
                raise PlannedRouteConflict("planned_analysis_busy", "This Planned version already has a running analysis; inspect that job.")
            try:
                state = {
                    "schema_version": "plannedAnalysisRun.v1", "run_id": run_id,
                    "project_id": self.project_id, "version_id": request.version_id,
                    "manifest_sha256": request.expected_manifest_sha256,
                    "command_sha256": command_sha, "binding": self._binding(bundle),
                    "status": "queued", "stage": "prepare", "attempt": 1,
                    "created_at": _now(), "updated_at": _now(), "stages": {}, "progress": {},
                    "error": None, "resume_commands": {},
                    "execution_location": os.environ.get("SCOUT_PLANNED_EXECUTION_LOCATION", "local"),
                    "producer_sources": _producer_sources(), **self.authority,
                }
                _atomic_json(self.root, self._ref(run_id, "request.json"), request.model_dump(mode="json"))
                self._write(state)
                self._start(run_id, lease)
            except BaseException:
                self._release(lease)
                raise
        return self.get(run_id)

    def _start(self, run_id: str, lease: int) -> None:
        if self.launch is not None:
            self.launch(lambda: self._run(run_id, lease))
            return
        log = _safe_path(self.root, self._ref(run_id, "worker.log"))
        # A one-shot subprocess survives the HTTP request/server exit. No daemon
        # scheduler is installed; a crashed process requires explicit Resume.
        with log.open("ab") as stream:
            subprocess.Popen(
                [sys.executable, "-m", self.worker_module, "--worker", str(self.root), run_id, str(lease)],
                cwd=Path(__file__).resolve().parent, stdin=subprocess.DEVNULL,
                stdout=stream, stderr=subprocess.STDOUT, start_new_session=True, pass_fds=(lease,),
            )
        # The child owns the inherited open-file description. Do not LOCK_UN.
        os.close(lease)

    def get(self, run_id: str, *, verify_outputs: bool = True) -> dict:
        state = self._read(run_id)
        if state["status"] in ACTIVE:
            lease = self._lease(state["version_id"])
            if lease is not None:
                try:
                    state = self._read(run_id)
                    if state["status"] in ACTIVE:
                        state = {**state, "persisted_status": state["status"], "status": "interrupted",
                                 "error": {"code": "worker_interrupted", "message": "The worker lease ended; explicitly resume this run."}}
                finally:
                    self._release(lease)
        try:
            self._bound_bundle(state)
            if verify_outputs and state["status"] in TERMINAL:
                report = self._report(state)
                state.update(preparation=report["preparation"], projections=report["projections"],
                             artifact_ref=state["report_ref"], artifact_sha256=state["report_sha256"],
                             pretrip_report=report.get("pretrip_report"))
            state["can_resume"] = state["status"] in RESUMABLE
        except (PlannedRouteConflict, OSError, ValueError) as exc:
            state.update(status="stale", can_resume=False, preparation=None, projections={},
                         error={"code": getattr(exc, "code", "planned_analysis_output_changed"),
                                "message": str(exc) if isinstance(exc, PlannedRouteConflict) else "Bound analysis evidence is unavailable or changed."})
        return state

    def list(self, version_id: str | None = None) -> dict:
        directory = _safe_path(self.root, self.runs_ref)
        states = []
        if directory.is_dir():
            for path in directory.glob("analysis.*/state.json"):
                item = self.get(path.parent.name)
                if version_id is None or item["version_id"] == version_id:
                    # Lists carry status, not six complete assessment documents.
                    states.append({k: v for k, v in item.items() if k not in {"preparation", "projections"}})
        return {"project_id": self.project_id, "runs": sorted(states, key=lambda v: v["created_at"], reverse=True), **self.authority}

    def resume(self, run_id: str, request: PlannedAnalysisResumeRequest) -> dict:
        with self._registry():
            observed = self.get(run_id)
            if request.expected_manifest_sha256 != observed["manifest_sha256"]:
                raise PlannedRouteConflict("planned_analysis_manifest_changed", "Resume must identify the original Planned manifest.")
            if request.expected_review_context_sha256 != observed["binding"].get("review_context_sha256"):
                raise PlannedRouteConflict("planned_review_context_changed", "Resume must identify the original supplement revision.")
            command = _digest(request.model_dump(mode="json"))
            key = _digest(request.idempotency_key)
            earlier = observed.get("resume_commands", {}).get(key)
            if earlier:
                if earlier["command_sha256"] != command:
                    raise PlannedRouteConflict("planned_idempotency_conflict", "This Resume key already identifies another command.")
                return observed
            if observed["status"] in ACTIVE:
                return observed
            if not observed.get("can_resume"):
                raise PlannedRouteConflict("planned_analysis_not_resumable", "This run cannot be resumed; inspect its source and output bindings.")
            lease = self._lease(observed["version_id"], create=True)
            if lease is None:
                raise PlannedRouteConflict("planned_analysis_busy", "The worker still owns this version; refresh its status.")
            try:
                state = self._read(run_id)
                self._bound_bundle(state)
                if state["attempt"] != observed["attempt"]:
                    raise PlannedRouteConflict("planned_analysis_already_resumed", "Another Resume advanced this run.")
                state.update(status="queued", stage="prepare", error=None, progress={},
                             attempt=state["attempt"] + 1, producer_sources=_producer_sources(), stages={})
                state["resume_commands"][key] = {"command_sha256": command, "attempt": state["attempt"], "created_at": _now()}
                self._write(state)
                self._start(run_id, lease)
            except BaseException:
                self._release(lease)
                raise
        return self.get(run_id)

    def _report(self, state: dict) -> dict:
        path = _safe_path(self.root, state["report_ref"])
        if file_sha(path, cached=True) != state["report_sha256"]:
            raise PlannedRouteConflict("planned_analysis_output_changed", "The analysis report changed after publication.")
        report = _read_json(self.root, state["report_ref"])
        _verify_signed(report, "report_sha256")
        if (report.get("binding") != state["binding"] or report.get("run_id") != state["run_id"]
                or report.get("attempt") != state["attempt"] or report.get("producer_sources") != _producer_sources()):
            raise PlannedRouteConflict("planned_analysis_producer_changed", "The analysis binding or producer changed; rerun before using these results.")
        for ref, expected in report.get("output_hashes", {}).items():
            if file_sha(_safe_path(self.root, ref), cached=True) != expected:
                raise PlannedRouteConflict("planned_analysis_output_changed", "A bound preparation or analysis output changed.")
        for ref, expected in report.get("owner_source_hashes", {}).items():
            if file_sha(_safe_path(self.root, ref), cached=True) != expected:
                raise PlannedRouteConflict("planned_analysis_sources_changed", "A source used by the Planned assessment changed.")
        for source in report.get("external_source_bindings", []):
            if file_sha(Path(source["resolved_path"]), cached=True) != source["sha256"]:
                raise PlannedRouteConflict("planned_analysis_sources_changed", "The raw terrain input changed after preparation.")
        return report

    def _run(self, run_id: str, lease: int) -> None:
        state = self._read(run_id)
        try:
            bundle = self._bound_bundle(state)
            state.update(status="running", stage="prepare", error=None)
            self._write(state)
            attempt_ref = self._ref(run_id, f"attempts/{state['attempt']:04d}")
            run_root = _safe_path(self.root, attempt_ref)
            run_root.mkdir(parents=True, exist_ok=False)

            def progress(value: dict):
                state["progress"] = {k: value[k] for k in ("stage", "status", "part_index", "role", "message") if k in value}
                self._write(state)

            # Share the existing QGIS preparation slot on this workspace host.
            lock_root = Path(os.environ.get("SCOUT_PLANNED_PREPARATION_LOCK_ROOT")
                             or os.environ.get("SCOUT_PLANNED_RPC_ROOT") or self.root.parent)
            slot = lock_root / ".scout-preparation-jobs" / ".preparation.lock"
            slot.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(slot, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            try:
                progress({"stage": "waiting_for_preparation_slot", "status": "queued"})
                fcntl.flock(fd, fcntl.LOCK_EX)
                self._bound_bundle(state)
                prepared = self.prepare(self.root, bundle, run_root, progress=progress)
            finally:
                self._release(fd)
            _boundary(prepared)
            if any((prepared.get("subject_binding") or {}).get(key) != state["binding"].get(key)
                   for key in SUBJECT_BINDING_KEYS):
                raise PlannedRouteConflict("planned_analysis_binding_mismatch", "Preparation belongs to another Planned version.")
            for ref, expected in prepared.get("source_hashes", {}).items():
                if file_sha(_safe_path(run_root, ref)) != expected:
                    raise PlannedRouteConflict("planned_analysis_output_changed", "A preparation receipt does not match its input or output bytes.")
            _atomic_json(run_root, "preparation-receipt.json", prepared)
            state["stages"]["prepare"] = {"status": prepared.get("status", "blocked"), "completed_at": _now()}
            state["stage"] = "analysis"
            self._write(state)
            self._bound_bundle(state)
            analysed = self.analyse(self.root, bundle, run_root, prepared, progress=progress)
            projections = analysed.get("projections", analysed)
            if set(projections) != set(ROLES):
                raise PlannedRouteConflict("planned_analysis_roles_missing", "A result is required for each of the six analysis roles.")
            published, artifact_sources = {}, []
            for role, projection in projections.items():
                _boundary(projection)
                if projection.get("status") not in {"ready", "partial", "blocked"}:
                    raise PlannedRouteConflict("invalid_planned_projection", "A projection must explicitly report ready, partial, or blocked.")
                if any((projection.get("input_binding") or {}).get(key) != state["binding"].get(key)
                       for key in SUBJECT_BINDING_KEYS):
                    raise PlannedRouteConflict("planned_analysis_binding_mismatch", "A producer analysed a different Planned geometry or timetable.")
                ref = projection.get("artifact_ref")
                path = _safe_path(run_root, ref or "")
                if file_sha(path) != projection.get("artifact_sha256"):
                    raise PlannedRouteConflict("planned_analysis_output_changed", "A producer result does not match its artifact hash.")
                artifact = _read_json(run_root, ref)
                _boundary(artifact)
                if (artifact.get("role") != role or any((artifact.get("input_binding") or {}).get(key) != state["binding"].get(key)
                        for key in SUBJECT_BINDING_KEYS)):
                    raise PlannedRouteConflict("planned_analysis_binding_mismatch", "An assessment artifact belongs to another role or Planned subject.")
                artifact_sources.extend(artifact.get("source_report", []))
                # Store the complete assessor artifact separately; the response
                # is a bounded summary plus the producer's explicit result.
                published[role] = {**projection, "artifact_ref": f"{attempt_ref}/{ref}",
                                   "input_binding": {**projection["input_binding"], "run_id": run_id}}
            extra_report = analysed.get("pretrip_report")
            if extra_report:
                _boundary(extra_report)
                if any(extra_report.get("input_binding", {}).get(k) != state["binding"].get(k)
                       for k in SUBJECT_BINDING_KEYS):
                    raise PlannedRouteConflict("planned_analysis_binding_mismatch", "The pre-trip report belongs to a different plan or supplement.")
                if file_sha(_safe_path(run_root, extra_report["artifact_ref"])) != extra_report.get("artifact_sha256"):
                    raise PlannedRouteConflict("planned_analysis_output_changed", "The pre-trip report bytes changed before publication.")
                full_report = _read_json(run_root, extra_report["artifact_ref"])
                _boundary(full_report)
                if any(full_report.get("input_binding", {}).get(k) != state["binding"].get(k)
                       for k in SUBJECT_BINDING_KEYS):
                    raise PlannedRouteConflict("planned_analysis_binding_mismatch", "The full pre-trip report belongs to a different plan or supplement.")
                expected_hashes = {role: projection["artifact_sha256"] for role, projection in published.items()}
                provenance = full_report.get("provenance", {})
                if (provenance.get("projection_hashes") != expected_hashes
                        or any(provenance.get(k) != state["binding"].get(k)
                               for k in ("review_context_revision_id", "review_context_sha256"))):
                    raise PlannedRouteConflict("planned_analysis_binding_mismatch", "The pre-trip report does not reference the six results being published.")
                if (extra_report.get("report") != full_report
                        or any(extra_report.get(k) != full_report.get(k) for k in ("status", "decision"))):
                    raise PlannedRouteConflict("planned_analysis_binding_mismatch", "The pre-trip summary and downloadable report disagree.")
            self._bound_bundle(state)
            if state["producer_sources"] != _producer_sources():
                raise PlannedRouteConflict("planned_analysis_producer_changed", "Producer source changed during analysis; resume with one code version.")
            output_hashes = {}
            for path in run_root.rglob("*"):
                if path.is_symlink():
                    raise PlannedRouteConflict("invalid_planned_ref", "Analysis output must not reference files through symlinks.")
                if path.is_file() and not path.name.endswith((".lock", ".log")):
                    output_hashes[path.relative_to(self.root).as_posix()] = file_sha(path)
            owner_hashes = {**state["binding"]["source_hashes"], **prepared.get("owner_source_hashes", {})}
            for source in artifact_sources:
                if source.get("scope") == "owner":
                    if source["ref"] in owner_hashes and owner_hashes[source["ref"]] != source["sha256"]:
                        raise PlannedRouteConflict("planned_analysis_sources_changed", "Assessors observed different bytes for the same input.")
                    owner_hashes[source["ref"]] = source["sha256"]
            for ref, expected in owner_hashes.items():
                if file_sha(_safe_path(self.root, ref)) != expected:
                    raise PlannedRouteConflict("planned_analysis_sources_changed", "An analysis source changed before publication.")
            report = _signed({
                "schema_version": "plannedAnalysisReport.v1", "project_id": self.project_id,
                "run_id": run_id, "attempt": state["attempt"], "binding": state["binding"],
                "created_at": _now(), "producer_sources": state["producer_sources"],
                "preparation": {**prepared, "artifact_base_ref": attempt_ref},
                "projections": published, "output_hashes": output_hashes,
                "pretrip_report": ({**analysed["pretrip_report"],
                    "artifact_ref": f"{attempt_ref}/{analysed['pretrip_report']['artifact_ref']}"}
                    if analysed.get("pretrip_report") else None),
                "owner_source_hashes": owner_hashes,
                "external_source_bindings": prepared.get("external_source_bindings", []), **self.authority,
            }, "report_sha256")
            report_ref = self._ref(run_id, f"reports/attempt-{state['attempt']:04d}.json")
            _atomic_json(self.root, report_ref, report)
            gaps = prepared.get("status") != "completed" or any(row["status"] != "ready" for row in published.values())
            state["progress"] = {"stage": "complete", "status": "completed_with_gaps" if gaps else "completed"}
            state.update(status="completed_with_gaps" if gaps else "completed", stage="complete",
                         completed_at=_now(), report_ref=report_ref,
                         report_sha256=file_sha(_safe_path(self.root, report_ref)), error=None)
            state["stages"]["analysis"] = {"status": "completed_with_gaps" if gaps else "completed", "completed_at": _now()}
            self._write(state)
        except Exception as exc:
            state.update(status="failed", error={
                "code": getattr(exc, "code", "planned_analysis_stage_failed"),
                "message": str(exc) if isinstance(exc, PlannedRouteConflict)
                else f"The {state['stage']} stage failed ({type(exc).__name__}); inspect the run artifacts.",
                "exception_type": type(exc).__name__,
            })
            self._write(state)
        finally:
            self._release(lease)

    def artifact(self, run_id: str, ref: str) -> tuple[bytes, str]:
        state = self.get(run_id)
        if state["status"] not in TERMINAL:
            raise PlannedRouteConflict("planned_analysis_not_available", "Only verified completed run artifacts can be read.")
        report = self._report(state)
        if ref not in report["output_hashes"] and ref != state["report_ref"]:
            raise PlannedRouteConflict("invalid_planned_ref", "This file is not a published analysis artifact.")
        return _safe_path(self.root, ref).read_bytes(), Path(ref).name


def _boundary(value):
    if not isinstance(value, dict) or value.get("candidate_only") is not True or value.get("runtime_safety_truth") is not False:
        raise PlannedRouteConflict("planned_authority_mismatch", "Preparation and analysis outputs must remain planning candidates.")


def latest_planned_analysis(root: Path, bundle: dict) -> dict | None:
    """Read one matching run without substituting a different plan or Golden."""
    manager = manager_for(root)
    runs = manager.list(bundle["manifest"]["version_id"])["runs"]
    if not runs:
        return None
    return manager.get(runs[0]["run_id"])


def manager_for(root: Path):
    if os.environ.get("SCOUT_PLANNED_ANALYSIS_REMOTE_CONFIG"):
        from scout_planned_analysis_remote import RemotePlannedAnalysisManager
        return RemotePlannedAnalysisManager(root)
    return PlannedAnalysisManager(root)


def _main():
    if len(sys.argv) == 5 and sys.argv[1] == "--worker":
        PlannedAnalysisManager(Path(sys.argv[2]))._run(sys.argv[3], int(sys.argv[4]))
        return
    if len(sys.argv) == 2 and sys.argv[1] == "--rpc":
        # Used only through the configured SSH command. No client-supplied shell
        # command or environment is executed here.
        envelope = json.load(sys.stdin)
        from scout_planned_analysis_remote import serve_rpc
        try:
            value = serve_rpc(envelope)
            print(json.dumps({"ok": True, "result": value}, ensure_ascii=False))
        except PlannedRouteConflict as exc:
            print(json.dumps({"ok": False, "error": {"code": exc.code, "message": exc.message}}, ensure_ascii=False))
        return
    raise SystemExit("Use --worker or --rpc.")


if __name__ == "__main__":
    _main()
