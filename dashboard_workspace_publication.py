from __future__ import annotations

import ctypes
import errno
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping


PROJECT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
GENERATION_ID_PATTERN = re.compile(
    r"^(?:[a-f0-9]{32}|legacy:[a-f0-9]{64})$"
)
PRETRIP_PROJECT_PATH_PATTERN = re.compile(
    r"^/admin/pretrip/projects/(?P<project_id>[A-Za-z0-9_.-]+)(?:/|$)"
)
JOURNAL_SCHEMA_VERSION = "dashboardWorkspacePublicationJournal.v1"
JOURNAL_STATES = frozenset({"staging", "prepared", "exchanged"})
GENERATION_MARKER_NAME = ".scout-workspace-generation.json"
GENERATION_MARKER_SCHEMA_VERSION = "dashboardWorkspaceGeneration.v1"

CloneTree = Callable[[Path, Path], str]
ExchangeDirectories = Callable[[Path, Path], str]


class WorkspacePreparationBusyError(RuntimeError):
    """Another process already owns preparation for this project."""


class WorkspaceRecoveryError(RuntimeError):
    """A crashed publication cannot be recovered without operator review."""


class _FileLockBusyError(RuntimeError):
    pass


@dataclass
class _FileLockHandle:
    descriptor: int
    path: Path
    released: bool = False

    def release(self) -> None:
        if self.released:
            return
        try:
            fcntl.flock(self.descriptor, fcntl.LOCK_UN)
        finally:
            os.close(self.descriptor)
            self.released = True


@dataclass
class _PreparationLease:
    project_id: str
    thread_lock: threading.Lock
    file_lock: _FileLockHandle
    released: bool = False

    def release(self) -> None:
        if self.released:
            return
        try:
            self.file_lock.release()
        finally:
            self.thread_lock.release()
            self.released = True


@dataclass
class _GenerationLockHandle:
    local_lock: "_ProjectReadWriteLock"
    file_lock: _FileLockHandle
    write: bool
    released: bool = False

    def release(self) -> None:
        if self.released:
            return
        try:
            self.file_lock.release()
        finally:
            if self.write:
                self.local_lock.release_write()
            else:
                self.local_lock.release_read()
            self.released = True


class _ProjectReadWriteLock:
    def __init__(self) -> None:
        self._condition = threading.Condition(threading.Lock())
        self._readers = 0
        self._writer = False
        self._waiting_writers = 0

    def acquire_read(self) -> None:
        with self._condition:
            self._condition.wait_for(
                lambda: not self._writer and self._waiting_writers == 0
            )
            self._readers += 1

    def release_read(self) -> None:
        with self._condition:
            if self._readers < 1:
                raise RuntimeError("workspace read lock is not held")
            self._readers -= 1
            if self._readers == 0:
                self._condition.notify_all()

    def acquire_write(self) -> None:
        with self._condition:
            self._waiting_writers += 1
            try:
                self._condition.wait_for(
                    lambda: not self._writer and self._readers == 0
                )
                self._writer = True
            finally:
                self._waiting_writers -= 1

    def release_write(self) -> None:
        with self._condition:
            if not self._writer:
                raise RuntimeError("workspace write lock is not held")
            self._writer = False
            self._condition.notify_all()


@dataclass(frozen=True)
class StagedDashboardWorkspace:
    project_id: str
    live_root: Path
    staged_root: Path
    session_root: Path
    clone_mode: str
    session_id: str
    journal_path: Path
    recovery_status: str
    preparation_lease: _PreparationLease = field(repr=False, compare=False)


class DashboardWorkspacePublication:
    """Stage provider refreshes and publish them as one Dashboard generation."""

    def __init__(
        self,
        workspace_root: Path,
        *,
        clone_tree: CloneTree | None = None,
        exchange_directories: ExchangeDirectories | None = None,
    ) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.private_root = self.workspace_root / ".scout-connected-preparation"
        self.staging_root = self.private_root / "staging"
        self.journal_root = self.private_root / "journals"
        self.lock_root = self.private_root / "locks"
        self.clone_tree = clone_tree or _clone_project_tree
        self.exchange_directories = (
            exchange_directories or _exchange_directories
        )
        self._locks_guard = threading.Lock()
        self._generation_locks: dict[str, _ProjectReadWriteLock] = {}
        self._preparation_thread_locks: dict[str, threading.Lock] = {}
        self._read_handles_guard = threading.Lock()
        self._read_handles: dict[str, list[_GenerationLockHandle]] = {}
        self._recovery_guard = threading.Lock()
        self._recovery_outcomes: dict[str, dict[str, Any]] = {}
        self._ensure_coordinator_directories(
            self.private_root,
            self.staging_root,
            self.journal_root,
            self.lock_root,
            self.lock_root / "preparation",
            self.lock_root / "generation",
        )
        self.startup_recovery = self.recover_pending()

    def stage(self, project_id: str) -> StagedDashboardWorkspace:
        self._validated_project_id(project_id)
        self._validate_coordinator_directories(
            self.private_root,
            self.staging_root,
            self.journal_root,
        )
        preparation_lease = self._acquire_preparation_lease(project_id)
        generation_lock: _GenerationLockHandle | None = None
        session_root: Path | None = None
        journal_path: Path | None = None
        session_id = uuid.uuid4().hex
        try:
            prior_recovery = self.recovery_status(project_id)
            recovery = self._recover_project_locked(project_id)
            if recovery["status"] != "none":
                self._record_recovery_outcome(project_id, recovery)
                if recovery["status"] == "published-cleanup-pending":
                    raise WorkspaceRecoveryError(
                        "published workspace cleanup is still pending"
                    )
            else:
                recovery = prior_recovery
            generation_lock = self._acquire_generation_lock(
                project_id,
                write=False,
            )
            live_root = self._validated_live_root(project_id)
            live_project_sha256 = _project_json_sha256(live_root)
            live_generation_id = _workspace_generation_identity(
                live_root,
                project_id,
            )
            session_root = self.staging_root / f"{project_id}.{session_id}"
            staged_root = session_root / project_id
            journal_path = self._journal_path(project_id)
            journal = {
                "schemaVersion": JOURNAL_SCHEMA_VERSION,
                "projectId": project_id,
                "sessionId": session_id,
                "sessionRef": session_root.relative_to(
                    self.workspace_root
                ).as_posix(),
                "state": "staging",
                "liveProjectSha256": live_project_sha256,
                "stagedProjectSha256": None,
                "liveGenerationId": live_generation_id,
                "stagedGenerationId": None,
                "cloneMode": None,
                "filesystemExchange": None,
                "ownerPid": os.getpid(),
                "createdAt": _utc_now(),
                "updatedAt": _utc_now(),
            }
            _atomic_write_json(journal_path, journal)
            session_root.mkdir(parents=True, exist_ok=False)
            clone_mode = self.clone_tree(live_root, staged_root)
            self._validate_project_identity(staged_root, project_id)
            staged_generation_id = uuid.uuid4().hex
            _write_generation_marker(
                staged_root,
                project_id=project_id,
                generation_id=staged_generation_id,
            )
            _atomic_write_json(
                journal_path,
                {
                    **journal,
                    "stagedGenerationId": staged_generation_id,
                    "cloneMode": clone_mode,
                    "updatedAt": _utc_now(),
                },
            )
        except Exception:
            session_removed = session_root is None
            if session_root is not None:
                try:
                    _remove_directory_tree_durably(session_root)
                    session_removed = True
                except OSError:
                    session_removed = False
            if journal_path is not None and session_removed:
                self._delete_journal_if_session(
                    journal_path,
                    session_id=session_id,
                )
            preparation_lease.release()
            raise
        finally:
            if generation_lock is not None:
                generation_lock.release()
        return StagedDashboardWorkspace(
            project_id=project_id,
            live_root=live_root,
            staged_root=staged_root,
            session_root=session_root,
            clone_mode=clone_mode,
            session_id=session_id,
            journal_path=journal_path,
            recovery_status=str(recovery["status"]),
            preparation_lease=preparation_lease,
        )

    def publish(self, staged: StagedDashboardWorkspace) -> dict[str, Any]:
        if staged.preparation_lease.released:
            raise RuntimeError("workspace preparation lease is no longer active")
        try:
            return self._publish_while_preparation_locked(staged)
        finally:
            staged.preparation_lease.release()

    def _publish_while_preparation_locked(
        self,
        staged: StagedDashboardWorkspace,
    ) -> dict[str, Any]:
        generation_lock: _GenerationLockHandle | None = None
        exchange_mode = "not-started"
        journal_status = "active"
        try:
            self._validate_project_identity(staged.staged_root, staged.project_id)
            staged_project_sha256 = _project_json_sha256(staged.staged_root)
            staged_generation_id = _workspace_generation_identity(
                staged.staged_root,
                staged.project_id,
            )
            generation_lock = self._acquire_generation_lock(
                staged.project_id,
                write=True,
            )
            live_root = self._validated_live_root(staged.project_id)
            if live_root != staged.live_root:
                raise RuntimeError("live workspace root changed during preparation")
            live_project_sha256 = _project_json_sha256(live_root)
            live_generation_id = _workspace_generation_identity(
                live_root,
                staged.project_id,
            )
            journal = self._load_journal_for_staged(staged)
            if (
                journal["liveGenerationId"] != live_generation_id
                or journal["liveProjectSha256"] != live_project_sha256
            ):
                raise WorkspaceRecoveryError(
                    "live workspace generation changed during preparation"
                )
            prepared_journal = {
                **journal,
                "state": "prepared",
                "liveProjectSha256": live_project_sha256,
                "stagedProjectSha256": staged_project_sha256,
                "liveGenerationId": live_generation_id,
                "stagedGenerationId": staged_generation_id,
                "updatedAt": _utc_now(),
            }
            _atomic_write_json(staged.journal_path, prepared_journal)
            exchange_mode = self.exchange_directories(
                live_root,
                staged.staged_root,
            )
            try:
                _atomic_write_json(
                    staged.journal_path,
                    {
                        **prepared_journal,
                        "state": "exchanged",
                        "filesystemExchange": exchange_mode,
                        "updatedAt": _utc_now(),
                    },
                )
                journal_status = "exchanged"
            except OSError:
                journal_status = "prepared-marker-retained"
        except Exception:
            recovery = self._recover_project_locked(
                staged.project_id,
                generation_locked=generation_lock is not None,
            )
            self._record_recovery_outcome(staged.project_id, recovery)
            if recovery["status"] in {
                "completed-publish-cleanup",
                "published-cleanup-pending",
            }:
                cleanup_pending = (
                    recovery["status"] == "published-cleanup-pending"
                )
                return {
                    "publicationMode": "staged-atomic-swap",
                    "cloneMode": staged.clone_mode,
                    "filesystemExchange": "recovered-after-exchange-error",
                    "retiredWorkspaceCleanup": (
                        "retained_for_cleanup"
                        if cleanup_pending
                        else "removed"
                    ),
                    "crossProcessLocking": True,
                    "recoveryJournalStatus": (
                        "active"
                        if cleanup_pending
                        else "clear"
                    ),
                    "startupRecovery": staged.recovery_status,
                }
            raise
        finally:
            if generation_lock is not None:
                generation_lock.release()
        cleanup_status = "removed"
        try:
            _remove_directory_tree_durably(staged.session_root)
        except OSError:
            cleanup_status = "retained_for_cleanup"
        if cleanup_status == "removed":
            _delete_file_durably(staged.journal_path)
            journal_status = "clear"
        else:
            journal_status = "active"
        return {
            "publicationMode": "staged-atomic-swap",
            "cloneMode": staged.clone_mode,
            "filesystemExchange": exchange_mode,
            "retiredWorkspaceCleanup": cleanup_status,
            "crossProcessLocking": True,
            "recoveryJournalStatus": journal_status,
            "startupRecovery": staged.recovery_status,
        }

    def discard(self, staged: StagedDashboardWorkspace) -> None:
        if staged.preparation_lease.released:
            return
        try:
            session_removed = False
            try:
                _remove_directory_tree_durably(staged.session_root)
                session_removed = True
            except OSError:
                pass
            if session_removed:
                self._delete_journal_if_session(
                    staged.journal_path,
                    session_id=staged.session_id,
                )
        finally:
            staged.preparation_lease.release()

    def acquire_read(self, project_id: str) -> None:
        self._validated_project_id(project_id)
        handle = self._acquire_generation_lock(project_id, write=False)
        with self._read_handles_guard:
            self._read_handles.setdefault(project_id, []).append(handle)

    def release_read(self, project_id: str) -> None:
        self._validated_project_id(project_id)
        with self._read_handles_guard:
            handles = self._read_handles.get(project_id) or []
            if not handles:
                raise RuntimeError("workspace read lock is not held")
            handle = handles.pop()
            if not handles:
                self._read_handles.pop(project_id, None)
        handle.release()

    @contextmanager
    def read_snapshot(self, project_id: str) -> Iterator[None]:
        self.acquire_read(project_id)
        try:
            yield
        finally:
            self.release_read(project_id)

    def recover_pending(self) -> dict[str, dict[str, Any]]:
        outcomes: dict[str, dict[str, Any]] = {}
        self._validate_coordinator_directories(
            self.private_root,
            self.staging_root,
            self.journal_root,
        )
        if not self.journal_root.exists():
            return outcomes
        for journal_path in sorted(self.journal_root.glob("*.json")):
            project_id = journal_path.stem
            try:
                self._validated_project_id(project_id)
            except ValueError as exc:
                outcomes[journal_path.name] = {
                    "status": "blocked",
                    "errorType": type(exc).__name__,
                }
                continue
            try:
                lease = self._acquire_preparation_lease(project_id)
            except WorkspacePreparationBusyError:
                outcomes[project_id] = {"status": "active-other-process"}
                continue
            try:
                outcome = self._recover_project_locked(project_id)
            except Exception as exc:
                outcome = {
                    "status": "blocked",
                    "errorType": type(exc).__name__,
                }
            finally:
                lease.release()
            outcomes[project_id] = outcome
        with self._recovery_guard:
            self._recovery_outcomes.update(outcomes)
        return {key: dict(value) for key, value in outcomes.items()}

    def recovery_status(self, project_id: str) -> dict[str, Any]:
        self._validated_project_id(project_id)
        with self._recovery_guard:
            outcome = dict(
                self._recovery_outcomes.get(project_id)
                or {"status": "none"}
            )
        journal_exists = self._journal_path(project_id).exists()
        if journal_exists and outcome.get("status") == "blocked":
            journal_status = "blocked"
        elif journal_exists and outcome.get("status") == "active-other-process":
            journal_status = "active-external"
        else:
            journal_status = "active" if journal_exists else "clear"
        return {
            **outcome,
            "journalStatus": journal_status,
        }

    def _record_recovery_outcome(
        self,
        project_id: str,
        outcome: Mapping[str, Any],
    ) -> None:
        with self._recovery_guard:
            self._recovery_outcomes[project_id] = dict(outcome)

    def _generation_lock_for(self, project_id: str) -> _ProjectReadWriteLock:
        with self._locks_guard:
            lock = self._generation_locks.get(project_id)
            if lock is None:
                lock = _ProjectReadWriteLock()
                self._generation_locks[project_id] = lock
            return lock

    def _preparation_thread_lock_for(self, project_id: str) -> threading.Lock:
        with self._locks_guard:
            lock = self._preparation_thread_locks.get(project_id)
            if lock is None:
                lock = threading.Lock()
                self._preparation_thread_locks[project_id] = lock
            return lock

    def _acquire_preparation_lease(
        self,
        project_id: str,
    ) -> _PreparationLease:
        self._validate_coordinator_directories(
            self.private_root,
            self.lock_root,
            self.lock_root / "preparation",
        )
        thread_lock = self._preparation_thread_lock_for(project_id)
        if not thread_lock.acquire(blocking=False):
            raise WorkspacePreparationBusyError(
                "connected preparation is active in this process"
            )
        try:
            file_lock = _acquire_file_lock(
                self.lock_root / "preparation" / f"{project_id}.lock",
                exclusive=True,
                blocking=False,
            )
        except _FileLockBusyError as exc:
            thread_lock.release()
            raise WorkspacePreparationBusyError(
                "connected preparation is active in another process"
            ) from exc
        except Exception:
            thread_lock.release()
            raise
        return _PreparationLease(
            project_id=project_id,
            thread_lock=thread_lock,
            file_lock=file_lock,
        )

    def _acquire_generation_lock(
        self,
        project_id: str,
        *,
        write: bool,
    ) -> _GenerationLockHandle:
        self._validate_coordinator_directories(
            self.private_root,
            self.lock_root,
            self.lock_root / "generation",
        )
        local_lock = self._generation_lock_for(project_id)
        if write:
            local_lock.acquire_write()
        else:
            local_lock.acquire_read()
        try:
            file_lock = _acquire_directory_lock(
                self.lock_root / "generation",
                exclusive=write,
                blocking=True,
            )
        except Exception:
            if write:
                local_lock.release_write()
            else:
                local_lock.release_read()
            raise
        return _GenerationLockHandle(
            local_lock=local_lock,
            file_lock=file_lock,
            write=write,
        )

    def _journal_path(self, project_id: str) -> Path:
        return self.journal_root / f"{project_id}.json"

    def _validate_coordinator_directories(self, *directories: Path) -> None:
        for directory in directories:
            try:
                relative = directory.relative_to(self.workspace_root)
            except ValueError as exc:
                raise WorkspaceRecoveryError(
                    "publication coordinator directory escapes workspace root"
                ) from exc
            current = self.workspace_root
            for part in relative.parts:
                current = current / part
                if current.is_symlink():
                    raise WorkspaceRecoveryError(
                        "publication coordinator directory must not be a "
                        "symbolic link"
                    )
                if current.exists() and not current.is_dir():
                    raise WorkspaceRecoveryError(
                        "publication coordinator path is not a directory"
                    )

    def _ensure_coordinator_directories(self, *directories: Path) -> None:
        self._validate_coordinator_directories(*directories)
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
        self._validate_coordinator_directories(*directories)

    def _load_journal_for_staged(
        self,
        staged: StagedDashboardWorkspace,
    ) -> dict[str, Any]:
        payload, session_root = self._load_validated_journal(
            staged.journal_path,
            staged.project_id,
        )
        if (
            payload.get("sessionId") != staged.session_id
            or session_root != staged.session_root
        ):
            raise WorkspaceRecoveryError(
                "publication journal does not match staged workspace"
            )
        return payload

    def _load_validated_journal(
        self,
        journal_path: Path,
        project_id: str,
    ) -> tuple[dict[str, Any], Path]:
        if journal_path.is_symlink():
            raise WorkspaceRecoveryError(
                "publication journal must not be a symbolic link"
            )
        payload = json.loads(journal_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise WorkspaceRecoveryError("publication journal must be an object")
        if (
            payload.get("schemaVersion") != JOURNAL_SCHEMA_VERSION
            or payload.get("projectId") != project_id
            or payload.get("state") not in JOURNAL_STATES
        ):
            raise WorkspaceRecoveryError("publication journal contract mismatch")
        session_ref = payload.get("sessionRef")
        if not isinstance(session_ref, str) or not session_ref:
            raise WorkspaceRecoveryError("publication journal session ref missing")
        session_id = payload.get("sessionId")
        if (
            not isinstance(session_id, str)
            or not re.fullmatch(r"[a-f0-9]{32}", session_id)
        ):
            raise WorkspaceRecoveryError("publication journal session id invalid")
        expected_session_path = (
            self.staging_root / f"{project_id}.{session_id}"
        )
        session_path = self.workspace_root / session_ref
        if session_path != expected_session_path:
            raise WorkspaceRecoveryError(
                "publication journal session identity mismatch"
            )
        if self.private_root.is_symlink() or self.staging_root.is_symlink():
            raise WorkspaceRecoveryError(
                "publication coordinator path must not be a symbolic link"
            )
        if session_path.is_symlink():
            raise WorkspaceRecoveryError(
                "publication journal session must not be a symbolic link"
            )
        session_root = session_path.resolve()
        try:
            session_root.relative_to(self.staging_root.resolve())
        except ValueError as exc:
            raise WorkspaceRecoveryError(
                "publication journal session escapes staging root"
            ) from exc
        if session_root == self.staging_root.resolve():
            raise WorkspaceRecoveryError("publication journal session is invalid")
        expected_session_root = expected_session_path.resolve()
        if session_root != expected_session_root:
            raise WorkspaceRecoveryError(
                "publication journal session identity mismatch"
            )
        live_sha = payload.get("liveProjectSha256")
        if not isinstance(live_sha, str) or not SHA256_PATTERN.fullmatch(live_sha):
            raise WorkspaceRecoveryError("publication journal live hash missing")
        staged_sha = payload.get("stagedProjectSha256")
        if payload.get("state") in {"prepared", "exchanged"} and (
            not isinstance(staged_sha, str)
            or not SHA256_PATTERN.fullmatch(staged_sha)
        ):
            raise WorkspaceRecoveryError("publication journal staged hash missing")
        live_generation_id = payload.get("liveGenerationId")
        if (
            not isinstance(live_generation_id, str)
            or not GENERATION_ID_PATTERN.fullmatch(live_generation_id)
        ):
            raise WorkspaceRecoveryError(
                "publication journal live generation id missing"
            )
        staged_generation_id = payload.get("stagedGenerationId")
        if payload.get("state") in {"prepared", "exchanged"} and (
            not isinstance(staged_generation_id, str)
            or not GENERATION_ID_PATTERN.fullmatch(staged_generation_id)
        ):
            raise WorkspaceRecoveryError(
                "publication journal staged generation id missing"
            )
        return payload, session_root

    def _recover_project_locked(
        self,
        project_id: str,
        *,
        generation_locked: bool = False,
    ) -> dict[str, Any]:
        generation_lock: _GenerationLockHandle | None = None
        if not generation_locked:
            generation_lock = self._acquire_generation_lock(
                project_id,
                write=True,
            )
        try:
            return self._recover_project_filesystem_locked(project_id)
        finally:
            if generation_lock is not None:
                generation_lock.release()

    def _recover_project_filesystem_locked(
        self,
        project_id: str,
    ) -> dict[str, Any]:
        journal_path = self._journal_path(project_id)
        if not journal_path.exists():
            return {"status": "none"}
        journal, session_root = self._load_validated_journal(
            journal_path,
            project_id,
        )
        state = str(journal["state"])
        live_root = self.workspace_root / project_id
        if live_root.is_symlink():
            raise WorkspaceRecoveryError(
                "published workspace must not be a symbolic link"
            )
        live_generation_id = _workspace_generation_identity_or_none(
            live_root,
            project_id,
        )
        live_project_sha256 = _project_json_sha256_or_none(live_root)
        old_generation_id = str(journal["liveGenerationId"])
        new_generation_id = journal.get("stagedGenerationId")
        old_generation_matches = (
            live_generation_id == old_generation_id
            and live_project_sha256 == journal["liveProjectSha256"]
        )
        new_generation_matches = (
            live_generation_id == new_generation_id
            and live_project_sha256 == journal.get("stagedProjectSha256")
        )
        if state == "staging":
            if not old_generation_matches:
                raise WorkspaceRecoveryError(
                    "live workspace changed during abandoned staging"
                )
            _remove_directory_tree_durably(session_root)
            _delete_file_durably(journal_path)
            return {
                "status": "discarded-staging",
                "journalState": state,
                "recoveredAt": _utc_now(),
            }
        if state == "exchanged" and not new_generation_matches:
            raise WorkspaceRecoveryError(
                "exchanged journal does not match live workspace"
            )
        if new_generation_matches:
            try:
                _remove_directory_tree_durably(session_root)
            except OSError:
                return {
                    "status": "published-cleanup-pending",
                    "journalState": state,
                    "recoveredAt": _utc_now(),
                }
            _delete_file_durably(journal_path)
            return {
                "status": "completed-publish-cleanup",
                "journalState": state,
                "recoveredAt": _utc_now(),
            }
        if state == "prepared" and old_generation_matches:
            _remove_directory_tree_durably(session_root)
            _delete_file_durably(journal_path)
            return {
                "status": "discarded-prepared-generation",
                "journalState": state,
                "recoveredAt": _utc_now(),
            }
        if (
            state == "prepared"
            and live_generation_id is None
            and not live_root.exists()
        ):
            retired = [
                candidate
                for candidate in session_root.glob(".retired-*")
                if not candidate.is_symlink()
                and candidate.is_dir()
                and _workspace_generation_identity_or_none(
                    candidate,
                    project_id,
                )
                == old_generation_id
                and _project_json_sha256_or_none(candidate)
                == journal["liveProjectSha256"]
            ]
            if len(retired) != 1:
                raise WorkspaceRecoveryError(
                    "retired workspace generation cannot be identified"
                )
            retired[0].rename(live_root)
            _fsync_directory(live_root.parent)
            _remove_directory_tree_durably(session_root)
            _delete_file_durably(journal_path)
            return {
                "status": "restored-old-generation",
                "journalState": state,
                "recoveredAt": _utc_now(),
            }
        raise WorkspaceRecoveryError(
            "publication journal does not match recoverable filesystem state"
        )

    def _delete_journal_if_session(
        self,
        journal_path: Path,
        *,
        session_id: str,
    ) -> None:
        if journal_path.is_symlink():
            return
        try:
            payload = json.loads(journal_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(payload, dict) and payload.get("sessionId") == session_id:
            _delete_file_durably(journal_path)

    def _validated_live_root(self, project_id: str) -> Path:
        self._validated_project_id(project_id)
        project_path = self.workspace_root / project_id
        if project_path.is_symlink():
            raise ValueError("pre-trip project root must not be a symbolic link")
        project_root = project_path.resolve()
        project_root.relative_to(self.workspace_root)
        self._validate_project_identity(project_root, project_id)
        return project_root

    @staticmethod
    def _validated_project_id(project_id: str) -> None:
        if not PROJECT_ID_PATTERN.fullmatch(str(project_id or "")):
            raise ValueError("invalid project id")

    @staticmethod
    def _validate_project_identity(project_root: Path, project_id: str) -> None:
        project_path = project_root / "project.json"
        payload = json.loads(project_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("project_id") != project_id:
            raise ValueError("pre-trip project identity mismatch")


def _acquire_file_lock(
    path: Path,
    *,
    exclusive: bool,
    blocking: bool,
) -> _FileLockHandle:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        path,
        os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    if not blocking:
        operation |= fcntl.LOCK_NB
    try:
        fcntl.flock(descriptor, operation)
    except BlockingIOError as exc:
        os.close(descriptor)
        raise _FileLockBusyError(str(path)) from exc
    except Exception:
        os.close(descriptor)
        raise
    return _FileLockHandle(descriptor=descriptor, path=path)


def _acquire_directory_lock(
    path: Path,
    *,
    exclusive: bool,
    blocking: bool,
) -> _FileLockHandle:
    """Lock an existing coordinator directory without creating GET artifacts."""

    if path.is_symlink() or not path.is_dir():
        raise WorkspaceRecoveryError("coordinator lock directory is invalid")
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_DIRECTORY", 0),
    )
    operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    if not blocking:
        operation |= fcntl.LOCK_NB
    try:
        fcntl.flock(descriptor, operation)
    except BlockingIOError as exc:
        os.close(descriptor)
        raise _FileLockBusyError(str(path)) from exc
    except Exception:
        os.close(descriptor)
        raise
    return _FileLockHandle(descriptor=descriptor, path=path)


def _project_json_sha256(project_root: Path) -> str:
    project_path = project_root / "project.json"
    return hashlib.sha256(project_path.read_bytes()).hexdigest()


def _project_json_sha256_or_none(project_root: Path) -> str | None:
    try:
        return _project_json_sha256(project_root)
    except OSError:
        return None


def _workspace_generation_identity(
    project_root: Path,
    project_id: str,
) -> str:
    marker_path = project_root / GENERATION_MARKER_NAME
    if marker_path.is_symlink():
        raise WorkspaceRecoveryError(
            "workspace generation marker must not be a symbolic link"
        )
    if not marker_path.exists():
        return f"legacy:{_project_json_sha256(project_root)}"
    payload = json.loads(marker_path.read_text(encoding="utf-8"))
    generation_id = payload.get("generationId") if isinstance(payload, dict) else None
    if (
        not isinstance(payload, dict)
        or payload.get("schemaVersion") != GENERATION_MARKER_SCHEMA_VERSION
        or payload.get("projectId") != project_id
        or not isinstance(generation_id, str)
        or not re.fullmatch(r"[a-f0-9]{32}", generation_id)
    ):
        raise WorkspaceRecoveryError("workspace generation marker is invalid")
    return generation_id


def _workspace_generation_identity_or_none(
    project_root: Path,
    project_id: str,
) -> str | None:
    try:
        return _workspace_generation_identity(project_root, project_id)
    except OSError:
        return None


def _write_generation_marker(
    project_root: Path,
    *,
    project_id: str,
    generation_id: str,
) -> None:
    if not re.fullmatch(r"[a-f0-9]{32}", generation_id):
        raise ValueError("workspace generation id is invalid")
    _atomic_write_json(
        project_root / GENERATION_MARKER_NAME,
        {
            "schemaVersion": GENERATION_MARKER_SCHEMA_VERSION,
            "projectId": project_id,
            "generationId": generation_id,
            "createdAt": _utc_now(),
        },
    )


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(
                dict(payload),
                handle,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _remove_directory_tree_durably(path: Path) -> None:
    if path.is_symlink():
        raise OSError(errno.ELOOP, "refusing to remove symbolic-link directory")
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        return
    if path.exists() or path.is_symlink():
        raise OSError(errno.EIO, "directory cleanup did not complete")
    _fsync_directory(path.parent)


def _delete_file_durably(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    _fsync_directory(path.parent)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def dashboard_project_id_from_read_path(method: str, path: str) -> str | None:
    if method.upper() not in {"GET", "HEAD"}:
        return None
    match = PRETRIP_PROJECT_PATH_PATTERN.match(path)
    return match.group("project_id") if match is not None else None


def _clone_project_tree(source: Path, destination: Path) -> str:
    if sys.platform == "darwin":
        command = ["/bin/cp", "-cRp", str(source), str(destination)]
        mode = "apfs-clone"
    elif sys.platform.startswith("linux") and shutil.which("cp"):
        command = [
            str(shutil.which("cp")),
            "-a",
            "--reflink=auto",
            str(source),
            str(destination),
        ]
        mode = "reflink-auto"
    else:
        shutil.copytree(source, destination, symlinks=True)
        return "full-copy"
    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        return mode
    except (OSError, subprocess.CalledProcessError):
        shutil.rmtree(destination, ignore_errors=True)
        shutil.copytree(source, destination, symlinks=True)
        return "full-copy-fallback"


def _exchange_directories(left: Path, right: Path) -> str:
    if sys.platform == "darwin" and _renamex_np_exchange(left, right):
        mode = "renamex_np"
    elif sys.platform.startswith("linux") and _renameat2_exchange(left, right):
        mode = "renameat2"
    else:
        mode = _locked_rename_exchange(left, right)
    _fsync_directory(left.parent)
    if right.parent != left.parent:
        _fsync_directory(right.parent)
    return mode


def _renamex_np_exchange(left: Path, right: Path) -> bool:
    libc = ctypes.CDLL(None, use_errno=True)
    renamex_np = getattr(libc, "renamex_np", None)
    if renamex_np is None:
        return False
    renamex_np.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    renamex_np.restype = ctypes.c_int
    result = renamex_np(os.fsencode(left), os.fsencode(right), 0x00000002)
    if result == 0:
        return True
    error_number = ctypes.get_errno()
    if error_number in {errno.ENOSYS, errno.ENOTSUP, errno.EINVAL}:
        return False
    raise OSError(error_number, os.strerror(error_number))


def _renameat2_exchange(left: Path, right: Path) -> bool:
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        return False
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    result = renameat2(
        -100,
        os.fsencode(left),
        -100,
        os.fsencode(right),
        0x00000002,
    )
    if result == 0:
        return True
    error_number = ctypes.get_errno()
    if error_number in {errno.ENOSYS, errno.ENOTSUP, errno.EINVAL}:
        return False
    raise OSError(error_number, os.strerror(error_number))


def _locked_rename_exchange(left: Path, right: Path) -> str:
    backup = right.parent / f".retired-{uuid.uuid4().hex}"
    left_moved = False
    right_moved = False
    left.rename(backup)
    left_moved = True
    try:
        right.rename(left)
        right_moved = True
        backup.rename(right)
        left_moved = False
    except Exception as exchange_error:
        try:
            if right_moved:
                if not left.exists() or right.exists():
                    raise RuntimeError(
                        "new workspace generation cannot be moved back to staging"
                    )
                left.rename(right)
                right_moved = False
            if left_moved:
                if not backup.exists() or left.exists():
                    raise RuntimeError(
                        "retired workspace generation cannot be restored"
                    )
                backup.rename(left)
                left_moved = False
        except Exception as rollback_error:
            failure = RuntimeError(
                "directory exchange failed and rollback was incomplete"
            )
            failure.add_note(
                f"rollback failure type: {type(rollback_error).__name__}"
            )
            raise failure from exchange_error
        raise
    return "locked-rename"
