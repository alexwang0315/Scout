"""Durable, one-shot AOI preparation dispatch; reads never restart a worker."""
from __future__ import annotations

import fcntl
import hashlib
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

from pydantic import Field

from scout_exploration_models import ExplorationModel
from scout_exploration_workspace import (
    BOUNDARY, STORE_REF, ExplorationWorkspaceError, _identity, _lease, _now,
    _path, _read, _sha, _verify_hashes, _write, prepare_exploration_workspace,
    read_exploration_workspace,
)


class ExplorationPrepareCommand(ExplorationModel):
    expected_intake_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    idempotency_key: str = Field(min_length=1, max_length=200)
    fetch_map: bool = True


def _worker_lease(path: Path, *, create: bool = False) -> int | None:
    if path.is_symlink():
        raise ExplorationWorkspaceError("Worker lock cannot follow a symlink")
    if not create and not path.exists():
        return -1
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | (os.O_CREAT if create else 0), 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except BlockingIOError:
        os.close(fd)
        return None


def _release(fd: int | None) -> None:
    if fd is not None and fd >= 0:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


class ExplorationJobManager:
    def __init__(self, project_root: Path, *, launch: Callable | None = None,
                 preparer: Callable = prepare_exploration_workspace):
        self.root = Path(project_root).resolve()
        project, _, job = _identity(self.root)
        self.prefix = f"{STORE_REF}/preparation/{job['preparation_id']}"
        self.state_ref = project["exploration_preparation_state_ref"]
        self.dispatch_ref = f"{self.prefix}/dispatch.json"
        self.worker_lock = _path(self.root, f"{self.prefix}/worker.lock")
        self.launch = launch
        self.preparer = preparer

    def _dispatch(self) -> dict:
        if _path(self.root, self.dispatch_ref).is_file():
            value = _read(self.root, self.dispatch_ref)
            if value.get("project_id") != self.root.name or any(value.get(key) != expected for key, expected in BOUNDARY.items()):
                raise ExplorationWorkspaceError("Exploration dispatch identity is invalid")
            return value
        return {"project_id": self.root.name, "commands": {}, "worker_status": "not_started", **BOUNDARY}

    def get(self, *, include_report: bool = True) -> dict:
        receipt = read_exploration_workspace(self.root)
        state = dict(receipt["preparation"])
        dispatch = self._dispatch()
        fd = _worker_lease(self.worker_lock)
        active = fd is None
        _release(fd)
        state.update(worker_live=active, dispatch_status=dispatch["worker_status"])
        if active and dispatch["worker_status"] in {"queued", "running"}:
            state["status"] = "running" if state.get("status") == "running" else "queued"
        elif not active and dispatch["worker_status"] in {"queued", "running"}:
            state.update(persisted_status=state["status"], status="interrupted",
                         error={"code": "worker_interrupted", "message": "Worker lease ended. Explicitly resume this same preparation."})
        elif dispatch["worker_status"] == "failed":
            state.update(status="failed", error=dispatch.get("error"))
        state["can_prepare"] = dispatch["worker_status"] == "not_started" and state.get("attempt", 0) == 0
        state["can_resume"] = not active and state["status"] in {"interrupted", "failed", "completed", "completed_with_gaps"}
        if state.get("report_ref") and not active and state["status"] in {"completed", "completed_with_gaps"}:
            try:
                report = _read(self.root, state["report_ref"])
                _verify_hashes(self.root, {**report["source_hashes"], state["report_ref"]: state["report_sha256"]})
                state["evidence_current"] = True
                if include_report:
                    state["report"] = report
            except (OSError, ValueError) as exc:
                state.update(status="stale", can_resume=False, evidence_current=False,
                             error={"code": "evidence_changed", "message": str(exc)})
        return {**receipt, "preparation": state, "intake_sha256": _sha(self.root / "inputs/exploration_intake.json")}

    def submit(self, command: ExplorationPrepareCommand | dict, *, resume: bool = False) -> dict:
        command = ExplorationPrepareCommand.model_validate(command)
        payload = {**command.model_dump(mode="json"), "resume": resume}
        from scout_exploration_workspace import _digest
        command_sha = _digest(payload)
        key = hashlib.sha256(command.idempotency_key.encode()).hexdigest()
        with _lease(_path(self.root, f"{self.prefix}/dispatch.lock")):
            _, _, job = _identity(self.root)
            if command.expected_intake_sha256 != job["intake_sha256"]:
                raise ExplorationWorkspaceError("Refresh the exploration intake before submitting this preparation")
            dispatch = self._dispatch()
            earlier = dispatch["commands"].get(key)
            if earlier:
                if earlier["command_sha256"] != command_sha:
                    raise ExplorationWorkspaceError("This idempotency key already identifies another command")
                return self.get()
            observed = self.get()
            if observed["preparation"]["worker_live"]:
                return observed
            if observed["preparation"]["status"] == "stale":
                raise ExplorationWorkspaceError("Bound exploration sources changed; create a new intake")
            if not resume and not observed["preparation"]["can_prepare"]:
                return observed
            if resume and not observed["preparation"]["can_resume"]:
                raise ExplorationWorkspaceError("This preparation has no resumable attempt")
            fd = _worker_lease(self.worker_lock, create=True)
            if fd is None:
                return self.get()
            request_ref = f"{self.prefix}/commands/{key}.json"
            _write(self.root, request_ref, payload)
            dispatch["commands"][key] = {"command_sha256": command_sha, "command_ref": request_ref,
                                         "submitted_at": _now()}
            dispatch.update(worker_status="queued", active_command=key, updated_at=_now(), error=None)
            _write(self.root, self.dispatch_ref, dispatch, immutable=False)
            try:
                if self.launch is not None:
                    self.launch(lambda: self._run(key, fd))
                else:
                    with _path(self.root, f"{self.prefix}/worker.log").open("ab") as log:
                        subprocess.Popen([sys.executable, "-B", "-m", "scout_exploration_jobs", "--worker", str(self.root), key, str(fd)],
                            cwd=Path(__file__).resolve().parent, stdin=subprocess.DEVNULL,
                            stdout=log, stderr=subprocess.STDOUT, pass_fds=(fd,), start_new_session=True)
                    os.close(fd)  # The child keeps the same locked open-file description.
            except BaseException:
                _release(fd)
                dispatch.update(worker_status="failed", error={"code": "worker_launch_failed", "message": "Preparation worker could not start."})
                _write(self.root, self.dispatch_ref, dispatch, immutable=False)
                raise
        return self.get()

    def _run(self, key: str, fd: int) -> None:
        dispatch = self._dispatch()
        try:
            record = dispatch["commands"][key]
            payload = _read(self.root, record["command_ref"])
            from scout_exploration_workspace import _digest
            if _digest(payload) != record["command_sha256"]:
                raise ExplorationWorkspaceError("Durable exploration command changed")
            _, _, job = _identity(self.root)
            if payload["expected_intake_sha256"] != job["intake_sha256"]:
                raise ExplorationWorkspaceError("Exploration intake changed before execution")
            dispatch.update(worker_status="running", updated_at=_now())
            _write(self.root, self.dispatch_ref, dispatch, immutable=False)
            self.preparer(self.root, job["preparation_id"], fetch_map=payload["fetch_map"], force=payload["resume"])
            dispatch.update(worker_status="completed", completed_at=_now(), error=None)
        except Exception as exc:
            dispatch.update(worker_status="failed", completed_at=_now(), error={"code": "exploration_preparation_failed",
                "message": str(exc), "exception_type": type(exc).__name__})
        finally:
            _write(self.root, self.dispatch_ref, dispatch, immutable=False)
            _release(fd)


def main() -> None:
    if len(sys.argv) != 5 or sys.argv[1] != "--worker":
        raise SystemExit("usage: python -m scout_exploration_jobs --worker PROJECT_ROOT COMMAND_KEY LEASE_FD")
    ExplorationJobManager(Path(sys.argv[2]))._run(sys.argv[3], int(sys.argv[4]))


if __name__ == "__main__":
    main()
