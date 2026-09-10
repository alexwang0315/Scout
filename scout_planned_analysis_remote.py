"""Configured SSH transport for Planned jobs whose data stays on Scout.

The Dashboard accepts version IDs only. Host, command, and destination roots
come from operator-owned configuration; no browser input becomes shell code.
Sparse, immutable input snapshots are streamed with rsync, never a Mac archive.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess

from scout_planned_analysis import (
    PlannedAnalysisManager, PlannedAnalysisResumeRequest, PlannedAnalysisRunRequest,
    RUN_PATTERN, TERMINAL, _admit, file_sha, planned_binding,
)
from scout_planned_route_artifacts import (
    AUTHORITY, _atomic_json, _digest, _project, _read_json, _safe_path,
    _signed, _verify_signed, canonical_bytes,
)
from scout_planned_route_models import PlannedRouteConflict


HANDLES_REF = "outputs/planned_analysis/remote_runs"
_PROJECT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SHA = re.compile(r"^[a-f0-9]{64}$")


def _config() -> dict:
    path = os.environ.get("SCOUT_PLANNED_ANALYSIS_REMOTE_CONFIG")
    if not path:
        raise PlannedRouteConflict("planned_remote_unconfigured", "Scout analysis storage has not been configured.")
    value = json.loads(Path(path).read_text())
    host, root, command = value.get("host"), value.get("workspace_root"), value.get("command")
    if (not isinstance(host, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+", host)
            or not isinstance(root, str) or not re.fullmatch(r"/[A-Za-z0-9_./-]+", root)
            or ".." in PurePosixPath(root).parts
            or not isinstance(command, list) or not command
            or not all(isinstance(v, str) and v and "\x00" not in v for v in command)):
        raise PlannedRouteConflict("invalid_planned_remote_config", "The operator-owned Scout execution configuration is invalid.")
    return {"host": host, "workspace_root": root.rstrip("/"), "command": command}


def _rpc(config: dict, envelope: dict) -> dict:
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=10",
         config["host"], shlex.join(config["command"])],
        input=canonical_bytes(envelope), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if result.returncode:
        raise PlannedRouteConflict("planned_remote_unavailable", "The Scout job endpoint is unavailable; retry the same action after reconnecting.")
    try:
        payload = json.loads(result.stdout)
    except (ValueError, UnicodeError) as exc:
        raise PlannedRouteConflict("invalid_planned_remote_response", "Scout did not return a valid job receipt.") from exc
    if not payload.get("ok"):
        error = payload.get("error") or {}
        raise PlannedRouteConflict(str(error.get("code", "planned_remote_failed")), str(error.get("message", "Scout could not complete this action.")))
    return payload["result"]


def _inputs(root: Path, bundle: dict) -> dict[str, dict]:
    from scout_planned_analysis_producers import OWNER_SOURCE_REFS
    from scout_planned_route_artifacts import STORE_REF

    # Copy only actual producer inputs plus this immutable bundle/review.
    # Analysis selection and other versions are UI state, not analysis inputs.
    project = _read_json(root, "project.json")
    refs = set(bundle["manifest"]["source_hashes"])
    prefix = f"{STORE_REF}/versions/{bundle['manifest']['version_id']}"
    refs.update(f"{prefix}/{name}" for name in [*bundle["manifest"]["files"], "manifest.json"])
    refs.add(bundle["review"]["review_ref"])
    candidates = ["inbox/source_manifest.json", "outputs/import_manifest.json",
                  project.get("dtm_coverage_summary_ref", "normalized/terrain/dtm_coverage_summary.json")]
    candidates.extend(project.get(key) or fallback for key, fallback in OWNER_SOURCE_REFS.items())
    for ref in candidates:
        if isinstance(ref, str) and _safe_path(root, ref).is_file():
            refs.add(ref)
    result = {}
    for ref in sorted(refs):
        path = _safe_path(root, ref)
        if not path.is_file():
            raise PlannedRouteConflict("planned_remote_input_missing", f"A snapshot input is unavailable: {ref}")
        result[ref] = {"sha256": file_sha(path, cached=True), "bytes": path.stat().st_size}
    return result


class RemotePlannedAnalysisManager:
    def __init__(self, root: Path):
        self.root, self.project_id = _project(root)
        self.config = _config()

    def _handle_ref(self, run_id: str):
        if not RUN_PATTERN.fullmatch(run_id):
            raise PlannedRouteConflict("invalid_planned_analysis_run", "Invalid Planned analysis run ID.")
        return f"{HANDLES_REF}/{run_id}.json"

    def _read_handle(self, run_id: str) -> dict:
        handle = _read_json(self.root, self._handle_ref(run_id))
        _verify_signed(handle, "handle_sha256")
        if (handle.get("run_id") != run_id or handle.get("project_id") != self.project_id
                or handle.get("config_sha256") != _digest(self.config)):
            raise PlannedRouteConflict("planned_remote_binding_changed", "This run belongs to a different configured Scout storage location.")
        return handle

    def _envelope(self, handle: dict, operation: str, **kwargs):
        return {"operation": operation, "snapshot_id": handle["snapshot_id"],
                "project_id": self.project_id, **kwargs}

    def _validate_owner(self, handle: dict) -> None:
        bundle = _admit(self.root, handle["version_id"], handle["manifest_sha256"])
        if planned_binding(bundle) != handle["binding"]:
            raise PlannedRouteConflict("planned_analysis_binding_changed", "The local Planned review or source identity changed after the Scout snapshot.")
        # Read-only local validation prevents a frozen remote replica from
        # hiding changes to the actual selected workspace.
        for ref, row in handle["input_files"].items():
            if file_sha(_safe_path(self.root, ref), cached=True) != row["sha256"]:
                raise PlannedRouteConflict("planned_analysis_sources_changed", "An input used by the Scout snapshot changed locally; prepare a new run.")

    def submit(self, request: PlannedAnalysisRunRequest) -> dict:
        # Serialize handle creation with key admission. Otherwise a concurrent
        # conflicting command could overwrite a successful remote run's handle
        # before the remote server rejects its idempotency key.
        with PlannedAnalysisManager(self.root)._registry():
            return self._submit_locked(request)

    def _submit_locked(self, request: PlannedAnalysisRunRequest) -> dict:
        bundle = _admit(self.root, request.version_id, request.expected_manifest_sha256)
        run_id = "analysis." + _digest({"project": self.project_id, "key": request.idempotency_key})[:32]
        ref = self._handle_ref(run_id)
        if _safe_path(self.root, ref).is_file():
            handle = self._read_handle(run_id)
            if handle["command_sha256"] != _digest(request.model_dump(mode="json")):
                raise PlannedRouteConflict("planned_idempotency_conflict", "This analysis key already identifies another request.")
            self._validate_owner(handle)
        else:
            inventory = _inputs(self.root, bundle)
            snapshot_id = _digest({"project_id": self.project_id, "inputs": inventory})
            handle = {"schema_version": "plannedRemoteHandle.v1", "run_id": run_id,
                      "project_id": self.project_id, "version_id": request.version_id,
                      "manifest_sha256": request.expected_manifest_sha256,
                      "binding": planned_binding(bundle), "input_files": inventory,
                      "snapshot_id": snapshot_id, "config_sha256": _digest(self.config),
                      "command_sha256": _digest(request.model_dump(mode="json")),
                      "execution_location": "scout", **AUTHORITY}
            _rpc(self.config, self._envelope(handle, "initialize"))
            target = f"{self.config['workspace_root']}/{snapshot_id}/{self.project_id}/"
            names = b"".join(ref.encode("utf-8") + b"\x00" for ref in inventory)
            result = subprocess.run(
                ["rsync", "-a", "--no-links", "--ignore-existing", "--from0", "--files-from=-",
                 "-e", "ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10",
                 str(self.root) + "/", f"{self.config['host']}:{target}"],
                input=names, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            if result.returncode:
                raise PlannedRouteConflict("planned_remote_transfer_failed", "The input stream to Scout was interrupted; retry the same action. Existing inputs are preserved.")
            self._validate_owner(handle)
            _rpc(self.config, self._envelope(handle, "verify_inputs", input_files=inventory))
            # Only this small handle stays on Mac. No GIS outputs, scratch
            # rasters, or compressed archive are written to the Mac workspace.
            _atomic_json(self.root, ref, _signed(handle, "handle_sha256"))
        result = _rpc(self.config, self._envelope(handle, "submit", request=request.model_dump(mode="json")))
        return self._decorate(result, handle)

    def _decorate(self, result, handle):
        if (result.get("run_id") != handle["run_id"] or result.get("binding") != handle["binding"]
                or result.get("project_id") != self.project_id):
            raise PlannedRouteConflict("planned_remote_binding_mismatch", "Scout returned a run for different Planned inputs.")
        return {**result, "execution_location": "scout",
                "storage_ref": f"{self.config['host']}:{self.config['workspace_root']}/{handle['snapshot_id']}/{self.project_id}"}

    def get(self, run_id: str):
        handle = self._read_handle(run_id)
        result = _rpc(self.config, self._envelope(handle, "get", run_id=run_id))
        result = self._decorate(result, handle)
        try:
            self._validate_owner(handle)
        except (PlannedRouteConflict, OSError) as exc:
            return {**result, "status": "stale", "can_resume": False, "projections": {}, "preparation": None,
                    "error": {"code": getattr(exc, "code", "planned_remote_input_missing"),
                              "message": str(exc) if isinstance(exc, PlannedRouteConflict) else "A bound local input is unavailable."}}
        return result

    def list(self, version_id: str | None = None):
        directory = _safe_path(self.root, HANDLES_REF)
        rows = []
        if directory.is_dir():
            for path in directory.glob("analysis.*.json"):
                handle = self._read_handle(path.stem)
                if version_id is not None and handle["version_id"] != version_id:
                    continue
                try:
                    row = self.get(handle["run_id"])
                except PlannedRouteConflict as exc:
                    row = {"run_id": handle["run_id"], "version_id": handle["version_id"],
                           "project_id": self.project_id, "manifest_sha256": handle["manifest_sha256"],
                           "status": "interrupted", "can_resume": False, "execution_location": "scout",
                           "error": {"code": exc.code, "message": exc.message}, **AUTHORITY}
                rows.append({k: v for k, v in row.items() if k not in {"projections", "preparation"}})
        return {"project_id": self.project_id, "runs": sorted(rows, key=lambda v: v.get("created_at", ""), reverse=True), **AUTHORITY}

    def resume(self, run_id: str, request: PlannedAnalysisResumeRequest):
        handle = self._read_handle(run_id)
        self._validate_owner(handle)
        result = _rpc(self.config, self._envelope(handle, "resume", run_id=run_id, request=request.model_dump(mode="json")))
        return self._decorate(result, handle)

    def artifact(self, run_id: str, ref: str):
        handle = self._read_handle(run_id)
        self._validate_owner(handle)
        result = _rpc(self.config, self._envelope(handle, "artifact", run_id=run_id, ref=ref))
        data = base64.b64decode(result["data"], validate=True)
        import hashlib
        if hashlib.sha256(data).hexdigest() != result["sha256"]:
            raise PlannedRouteConflict("planned_remote_artifact_changed", "The artifact transfer did not match its hash.")
        return data, result["filename"]


def serve_rpc(envelope: dict) -> dict:
    configured = os.environ.get("SCOUT_PLANNED_RPC_ROOT")
    if not configured:
        raise PlannedRouteConflict("planned_remote_unconfigured", "The Scout snapshot root is not configured.")
    project_id, snapshot = envelope.get("project_id"), envelope.get("snapshot_id")
    if not isinstance(project_id, str) or not _PROJECT.fullmatch(project_id) or not isinstance(snapshot, str) or not _SHA.fullmatch(snapshot):
        raise PlannedRouteConflict("invalid_planned_remote_target", "The snapshot and project identities are invalid.")
    base = Path(configured).resolve()
    root = _safe_path(base, f"{snapshot}/{project_id}")
    operation = envelope.get("operation")
    if operation == "initialize":
        root.mkdir(parents=True, exist_ok=True)
        return {"status": "ready", "project_id": project_id, "snapshot_id": snapshot, **AUTHORITY}
    if operation == "verify_inputs":
        files = envelope.get("input_files")
        if not isinstance(files, dict) or _digest({"project_id": project_id, "inputs": files}) != snapshot:
            raise PlannedRouteConflict("invalid_planned_remote_inventory", "The snapshot inventory does not match its identity.")
        for ref, row in files.items():
            path = _safe_path(root, ref)
            if path.stat().st_size != row["bytes"] or file_sha(path) != row["sha256"]:
                raise PlannedRouteConflict("planned_remote_input_changed", "A transferred input does not match the immutable snapshot.")
        return {"status": "verified", "file_count": len(files), "snapshot_id": snapshot, **AUTHORITY}
    # A remote worker must never recursively dispatch itself back over SSH.
    manager = PlannedAnalysisManager(root)
    if operation == "submit":
        return manager.submit(PlannedAnalysisRunRequest.model_validate(envelope["request"]))
    if operation == "get":
        return manager.get(envelope["run_id"])
    if operation == "resume":
        return manager.resume(envelope["run_id"], PlannedAnalysisResumeRequest.model_validate(envelope["request"]))
    if operation == "artifact":
        data, filename = manager.artifact(envelope["run_id"], envelope["ref"])
        import hashlib
        return {"data": base64.b64encode(data).decode("ascii"), "filename": filename,
                "sha256": hashlib.sha256(data).hexdigest()}
    raise PlannedRouteConflict("invalid_planned_remote_action", "This Scout job action is not supported.")
