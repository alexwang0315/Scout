"""Explicit, start-only local QGIS recovery; status reads have no launch effects."""

from __future__ import annotations

import fcntl
import json
import os
import threading
import time
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Callable, Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from qgis_spatial_contracts import QgisBackendAvailability, QgisBackendStatus


class QgisRuntimeControlCode(StrEnum):
    IDLE = "IDLE"
    STARTING = "STARTING"
    READY = "READY"
    BUSY = "BUSY"
    NOT_MANAGED = "NOT_MANAGED"
    REMOTE_MANAGED = "REMOTE_MANAGED"
    CONFIGURATION_REQUIRED = "CONFIGURATION_REQUIRED"
    FIXTURE_MODE = "FIXTURE_MODE"
    PORT_IN_USE = "PORT_IN_USE"
    QGIS_SESSION_REQUIRES_ATTENTION = "QGIS_SESSION_REQUIRES_ATTENTION"
    UNSUPPORTED_HOST = "UNSUPPORTED_HOST"
    START_TIMEOUT = "START_TIMEOUT"
    START_FAILED = "START_FAILED"
    AUDIT_UNAVAILABLE = "AUDIT_UNAVAILABLE"


class QgisRuntimeControlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action: Literal["ensure_ready"] = "ensure_ready"


class QgisRuntimeControlResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["qgis_runtime_control.v1"] = "qgis_runtime_control.v1"
    project_id: str
    request_id: str | None = None
    status: Literal["idle", "starting", "ready", "busy", "unavailable"]
    code: QgisRuntimeControlCode
    can_start: bool = False
    actions: list[str] = Field(default_factory=list)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    authority: Literal["candidate_only"] = "candidate_only"
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    operational: Literal[False] = False


class QgisRuntimeUnavailable(Exception):
    def __init__(self, code: QgisRuntimeControlCode) -> None:
        super().__init__(code.value)
        self.code = code


class QgisRuntimeHost(Protocol):
    def configuration_issue(self) -> QgisRuntimeControlCode | None: ...
    def probe(self, project_id: str) -> QgisBackendStatus: ...
    def worker_listening(self) -> bool: ...
    def worker_authenticated(self) -> bool: ...
    def ensure_qgis(self) -> str: ...
    def start_worker(self) -> str: ...


def _ready(status: QgisBackendStatus) -> bool:
    return (
        status.availability in {QgisBackendAvailability.AVAILABLE, QgisBackendAvailability.DEGRADED}
        and status.enabled and status.configured and status.reachable
        and status.qgis_application_available and status.plugin_bridge_available
        and status.capabilities_discoverable and not status.fixture_mode
    )


class QgisRuntimeController:
    def __init__(
        self, *, host: QgisRuntimeHost, runtime_root: Path,
        startup_timeout_s: float = 90, poll_interval_s: float = 2,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.host = host
        self.runtime_root = runtime_root
        self.startup_timeout_s = startup_timeout_s
        self.poll_interval_s = poll_interval_s
        self._monotonic = monotonic
        self._sleep = sleep
        self._lock = threading.Lock()
        self._last: QgisRuntimeControlResult | None = None
        self._last_finished = float("-inf")

    def snapshot(self, *, project_id: str) -> QgisRuntimeControlResult:
        issue = self.host.configuration_issue()
        if issue:
            return QgisRuntimeControlResult(project_id=project_id, status="unavailable", code=issue)
        if self._last is not None and self._last.project_id == project_id:
            try:
                status = self.host.probe(project_id)
            except (OSError, ValueError, RuntimeError):
                return self._last
            if _ready(status):
                return QgisRuntimeControlResult(
                    project_id=project_id,
                    request_id=self._last.request_id,
                    status="ready",
                    code=QgisRuntimeControlCode.READY,
                    can_start=True,
                    actions=self._last.actions,
                )
            return self._last
        return QgisRuntimeControlResult(
            project_id=project_id, status="idle", code=QgisRuntimeControlCode.IDLE, can_start=True,
        )

    def ensure_ready(self, *, project_id: str) -> QgisRuntimeControlResult:
        issue = self.host.configuration_issue()
        if issue:
            return QgisRuntimeControlResult(project_id=project_id, status="unavailable", code=issue)
        if not self._lock.acquire(blocking=False):
            return self._busy(project_id)
        lock_fd: int | None = None
        try:
            if (self._last is not None and self._last.project_id == project_id
                    and self._monotonic() - self._last_finished < 2):
                return self._last
            self.runtime_root.mkdir(mode=0o700, parents=True, exist_ok=True)
            lock_fd = os.open(
                self.runtime_root / "qgis-runtime-control.lock",
                os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600,
            )
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return self._busy(project_id)
            return self._start(project_id)
        except OSError:
            return QgisRuntimeControlResult(
                project_id=project_id, status="unavailable", code=QgisRuntimeControlCode.AUDIT_UNAVAILABLE,
            )
        finally:
            if lock_fd is not None:
                os.close(lock_fd)
            self._lock.release()

    def _busy(self, project_id: str) -> QgisRuntimeControlResult:
        return QgisRuntimeControlResult(
            project_id=project_id, status="busy", code=QgisRuntimeControlCode.BUSY, can_start=True,
        )

    def _record(self, result: QgisRuntimeControlResult) -> None:
        fd = os.open(
            self.runtime_root / "qgis-runtime-control.jsonl",
            os.O_CREAT | os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW, 0o600,
        )
        with os.fdopen(fd, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(result.model_dump(mode="json"), ensure_ascii=True) + "\n")
            stream.flush()
        self._last = result

    def _start(self, project_id: str) -> QgisRuntimeControlResult:
        request_id = str(uuid4())
        actions: list[str] = []
        starting = QgisRuntimeControlResult(
            project_id=project_id, request_id=request_id, status="starting",
            code=QgisRuntimeControlCode.STARTING, can_start=True,
        )
        # Audit must be writable before any host launch, and contains no credentials.
        self._record(starting)
        deadline = self._monotonic() + self.startup_timeout_s
        code = QgisRuntimeControlCode.START_TIMEOUT
        try:
            status = self.host.probe(project_id)
            if _ready(status):
                code = QgisRuntimeControlCode.READY
            else:
                listening = self.host.worker_listening()
                if listening and not self.host.worker_authenticated():
                    raise QgisRuntimeUnavailable(QgisRuntimeControlCode.PORT_IN_USE)
                actions.append(self.host.ensure_qgis())
                if not listening:
                    actions.append(self.host.start_worker())
                while self._monotonic() < deadline:
                    if _ready(self.host.probe(project_id)):
                        code = QgisRuntimeControlCode.READY
                        break
                    self._sleep(self.poll_interval_s)
        except QgisRuntimeUnavailable as exc:
            code = exc.code
        except (OSError, ValueError, RuntimeError):
            code = QgisRuntimeControlCode.START_FAILED
        result = QgisRuntimeControlResult(
            project_id=project_id, request_id=request_id, code=code, actions=actions,
            status="ready" if code == QgisRuntimeControlCode.READY else "unavailable",
            can_start=True,
        )
        self._record(result)
        self._last_finished = self._monotonic()
        return result
