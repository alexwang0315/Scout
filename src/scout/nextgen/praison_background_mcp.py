"""Transport-neutral MCP lifecycle adapter for candidate-only Praison jobs."""

from __future__ import annotations

import contextlib
import inspect
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import model_validator

from scout.nextgen.background_job_store import (
    SQLiteBackgroundIntelligenceJobStore,
)
from scout.nextgen.edge_resource_policy import (
    EdgeBackgroundResourcePolicy,
    EdgeResourceSnapshot,
)
from scout.nextgen.intelligence_gateway import (
    IntelligenceRequest,
    IntelligenceResponse,
    WorkspaceBinding,
)
from scout.nextgen.praison_background_queue import (
    BackgroundIntelligenceJobProgress,
    PraisonBackgroundIntelligenceQueue,
)
from scout.schemas.base import NonEmptyStr, SchemaModel


class _BackgroundExecutor(Protocol):
    def execute(
        self,
        request: IntelligenceRequest,
        *,
        cancellation_event: threading.Event | None = None,
        progress_callback: Callable[[str, int], None] | None = None,
    ) -> IntelligenceResponse: ...


class BackgroundIntelligenceJobAccessRejected(RuntimeError):
    pass


class BackgroundIntelligenceJobAccess(SchemaModel):
    """Opaque job handle bound to the request and immutable Workspace inputs."""

    schema_version: Literal["scout.background_intelligence_access.v0"] = (
        "scout.background_intelligence_access.v0"
    )
    job_id: UUID
    request_id: UUID
    mission_id: NonEmptyStr
    workspace_binding: WorkspaceBinding
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @model_validator(mode="after")
    def validate_mission_binding(self) -> "BackgroundIntelligenceJobAccess":
        if self.workspace_binding.mission_id != self.mission_id:
            raise ValueError("background job access mission binding does not match")
        return self

    @classmethod
    def from_progress(
        cls,
        progress: BackgroundIntelligenceJobProgress,
    ) -> "BackgroundIntelligenceJobAccess":
        return cls(
            job_id=progress.job_id,
            request_id=progress.request_id,
            mission_id=progress.mission_id,
            workspace_binding=progress.workspace_binding,
        )


class BackgroundIntelligenceJobSubmission(SchemaModel):
    schema_version: Literal["scout.background_intelligence_submission.v0"] = (
        "scout.background_intelligence_submission.v0"
    )
    access: BackgroundIntelligenceJobAccess
    progress: BackgroundIntelligenceJobProgress
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @model_validator(mode="after")
    def validate_access_matches_progress(self) -> "BackgroundIntelligenceJobSubmission":
        expected = BackgroundIntelligenceJobAccess.from_progress(self.progress)
        if self.access != expected:
            raise ValueError("background job submission access does not match progress")
        return self


class _CompatibleExecutor:
    def __init__(
        self,
        service: _BackgroundExecutor,
        *,
        redirect_stdout: bool,
    ) -> None:
        self._service = service
        self._redirect_stdout = redirect_stdout

    def execute(
        self,
        request: IntelligenceRequest,
        *,
        cancellation_event: threading.Event | None = None,
        progress_callback: Callable[[str, int], None] | None = None,
    ) -> IntelligenceResponse:
        parameters = inspect.signature(self._service.execute).parameters
        controls: dict[str, Any] = {}
        if "cancellation_event" in parameters:
            controls["cancellation_event"] = cancellation_event
        if "progress_callback" in parameters:
            controls["progress_callback"] = progress_callback
        output_context = (
            contextlib.redirect_stdout(sys.stderr)
            if self._redirect_stdout
            else contextlib.nullcontext()
        )
        with output_context:
            return self._service.execute(
                request,
                **controls,
            )


class PraisonBackgroundMcpService:
    """Expose a bounded queue without granting it Scout runtime authority."""

    def __init__(
        self,
        *,
        service: _BackgroundExecutor,
        job_store_path: Path | None = None,
        max_queue_size: int = 16,
        resource_snapshot_provider: Callable[[], EdgeResourceSnapshot] | None = None,
        resource_policy: EdgeBackgroundResourcePolicy | None = None,
        redirect_worker_stdout: bool = False,
    ) -> None:
        self._service = service
        self._store = (
            SQLiteBackgroundIntelligenceJobStore(job_store_path)
            if job_store_path is not None
            else None
        )
        executor: _BackgroundExecutor = _CompatibleExecutor(
            service,
            redirect_stdout=redirect_worker_stdout,
        )
        self._queue = PraisonBackgroundIntelligenceQueue(
            service=executor,
            max_queue_size=max_queue_size,
            job_store=self._store,
            resource_snapshot_provider=resource_snapshot_provider,
            resource_policy=resource_policy,
        )
        self._closed = False

    def __enter__(self) -> "PraisonBackgroundMcpService":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    @property
    def supports_live_web(self) -> bool:
        return bool(getattr(self._service, "supports_live_web", False))

    def execute(self, request: IntelligenceRequest) -> IntelligenceResponse:
        return self._service.execute(request)

    def submit(
        self,
        request: IntelligenceRequest,
    ) -> BackgroundIntelligenceJobSubmission:
        progress = self._queue.submit(request)
        return BackgroundIntelligenceJobSubmission(
            access=BackgroundIntelligenceJobAccess.from_progress(progress),
            progress=progress,
        )

    def progress(
        self,
        access: BackgroundIntelligenceJobAccess,
    ) -> BackgroundIntelligenceJobProgress:
        progress = self._queue.get_progress(access.job_id)
        self._validate_access(access, progress)
        return progress

    def cancel(
        self,
        access: BackgroundIntelligenceJobAccess,
    ) -> BackgroundIntelligenceJobProgress:
        progress = self._queue.get_progress(access.job_id)
        self._validate_access(access, progress)
        return self._queue.cancel(access.job_id)

    def wait(
        self,
        access: BackgroundIntelligenceJobAccess,
        *,
        timeout_seconds: float | None = None,
    ) -> BackgroundIntelligenceJobProgress:
        progress = self._queue.get_progress(access.job_id)
        self._validate_access(access, progress)
        return self._queue.wait(
            access.job_id,
            timeout_seconds=timeout_seconds,
        )

    def result(
        self,
        access: BackgroundIntelligenceJobAccess,
        *,
        current_binding: WorkspaceBinding,
    ) -> IntelligenceResponse:
        progress = self._queue.get_progress(access.job_id)
        self._validate_access(access, progress)
        return self._queue.result(
            access.job_id,
            current_binding=current_binding,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._queue.close()
        finally:
            close_service = getattr(self._service, "close", None)
            if callable(close_service):
                close_service()
            if self._store is not None:
                self._store.close()

    @staticmethod
    def _validate_access(
        access: BackgroundIntelligenceJobAccess,
        progress: BackgroundIntelligenceJobProgress,
    ) -> None:
        expected = BackgroundIntelligenceJobAccess.from_progress(progress)
        if access != expected:
            raise BackgroundIntelligenceJobAccessRejected(
                "background job access binding was rejected"
            )


__all__ = [
    "BackgroundIntelligenceJobAccess",
    "BackgroundIntelligenceJobAccessRejected",
    "BackgroundIntelligenceJobSubmission",
    "PraisonBackgroundMcpService",
]
