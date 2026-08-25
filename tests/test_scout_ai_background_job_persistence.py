from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from stat import S_IMODE
from typing import Any
from uuid import uuid4

import pytest

from scout.nextgen import (
    CapabilityBroker,
    IntelligenceRequest,
    IntelligenceTaskType,
    StubIntelligenceGateway,
    WorkspaceBinding,
)
from scout.nextgen.background_job_store import (
    BackgroundJobStoreCorrupt,
    SQLiteBackgroundIntelligenceJobStore,
)
from scout.nextgen.praison_background_queue import (
    BackgroundIntelligenceJobProgress,
    BackgroundIntelligenceJobState,
    PraisonBackgroundIntelligenceQueue,
)


def _request() -> IntelligenceRequest:
    request_id = uuid4()
    grant = CapabilityBroker().issue_grant(
        request_id=request_id,
        mission_id="mission-persistent",
        task_type=IntelligenceTaskType.TERRAIN_ANALYSIS,
        allowed_capabilities=("dem.read",),
        evidence_refs_allowed=("dem:persistent",),
        max_model_requests=10,
        max_tool_calls=10,
    )
    return IntelligenceRequest(
        request_id=request_id,
        mission_id="mission-persistent",
        task_type=IntelligenceTaskType.TERRAIN_ANALYSIS,
        question="Persist this candidate terrain analysis.",
        workspace_binding=WorkspaceBinding(
            workspace_id="workspace-persistent",
            workspace_revision="revision-1",
            mission_id="mission-persistent",
            mission_version="mission-version-1",
            route_id="route-persistent",
            route_version="route-version-1",
            input_hash="persistent-input-hash",
            generated_at=datetime(2026, 8, 23, tzinfo=UTC),
        ),
        capability_grant=grant,
        evidence_refs=("dem:persistent",),
        max_runtime_seconds=10,
        max_model_requests=10,
    )


class _MustNotRunService:
    def execute(self, request: IntelligenceRequest, **kwargs: object) -> object:
        del request, kwargs
        raise AssertionError("restored terminal job was executed again")


class _ImmediateStubService:
    def execute(
        self,
        request: IntelligenceRequest,
        *,
        cancellation_event: threading.Event | None = None,
        progress_callback: Callable[[str, int], None] | None = None,
    ) -> Any:
        del cancellation_event, progress_callback
        return StubIntelligenceGateway().execute(request)


class _BlockingStubService:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def execute(
        self,
        request: IntelligenceRequest,
        *,
        cancellation_event: threading.Event | None = None,
        progress_callback: Callable[[str, int], None] | None = None,
    ) -> Any:
        del cancellation_event, progress_callback
        self.started.set()
        assert self.release.wait(timeout=2)
        return StubIntelligenceGateway().execute(request)


def test_completed_background_job_survives_queue_restart(tmp_path: Path) -> None:
    request = _request()
    store_path = tmp_path / "background-jobs.sqlite3"
    with SQLiteBackgroundIntelligenceJobStore(store_path) as store:
        with PraisonBackgroundIntelligenceQueue(
            service=_ImmediateStubService(),
            job_store=store,
        ) as queue:
            submitted = queue.submit(request)
            queue.wait(submitted.job_id, timeout_seconds=2)

    with SQLiteBackgroundIntelligenceJobStore(store_path) as restored_store:
        with PraisonBackgroundIntelligenceQueue(
            service=_MustNotRunService(),
            job_store=restored_store,
        ) as restored_queue:
            progress = restored_queue.get_progress(submitted.job_id)
            response = restored_queue.result(
                submitted.job_id,
                current_binding=request.workspace_binding,
            )
            events = restored_store.list_events(submitted.job_id)

    assert S_IMODE(store_path.stat().st_mode) == 0o600
    assert progress.state is BackgroundIntelligenceJobState.COMPLETED
    assert response.request_id == request.request_id
    assert response.candidate_only is True
    assert response.runtime_safety_truth is False
    assert tuple(event.event_type for event in events) == (
        "submitted",
        "started",
        "completed",
        "result_consumed",
    )


def test_nonterminal_persisted_job_fails_closed_after_restart(tmp_path: Path) -> None:
    request = _request()
    submitted_at = datetime.now(UTC)
    progress = BackgroundIntelligenceJobProgress(
        request_id=request.request_id,
        mission_id=request.mission_id,
        workspace_binding=request.workspace_binding,
        state=BackgroundIntelligenceJobState.RUNNING,
        stage="specialist:terrain:running",
        progress_percent=40,
        submitted_at=submitted_at,
        started_at=submitted_at,
    )
    store_path = tmp_path / "interrupted-jobs.sqlite3"
    with SQLiteBackgroundIntelligenceJobStore(store_path) as store:
        store.save_job(
            request=request,
            progress=progress,
            response=None,
            event_type="started",
        )

    with SQLiteBackgroundIntelligenceJobStore(store_path) as restored_store:
        with PraisonBackgroundIntelligenceQueue(
            service=_MustNotRunService(),
            job_store=restored_store,
        ) as queue:
            restored = queue.get_progress(progress.job_id)
            events = restored_store.list_events(progress.job_id)

    assert restored.state is BackgroundIntelligenceJobState.FAILED
    assert restored.error_type == "ProcessRestartInterrupted"
    assert restored.response_available is False
    assert events[-1].event_type == "restart_interrupted"


def test_queued_cancellation_is_persisted_and_not_replayed(tmp_path: Path) -> None:
    service = _BlockingStubService()
    store_path = tmp_path / "cancelled-jobs.sqlite3"
    with SQLiteBackgroundIntelligenceJobStore(store_path) as store:
        with PraisonBackgroundIntelligenceQueue(
            service=service,
            job_store=store,
        ) as queue:
            running = queue.submit(_request())
            assert service.started.wait(timeout=1)
            queued = queue.submit(_request())
            cancelled = queue.cancel(queued.job_id)
            service.release.set()
            queue.wait(running.job_id, timeout_seconds=2)
            queue.wait(queued.job_id, timeout_seconds=2)

        events = store.list_events(queued.job_id)

    with SQLiteBackgroundIntelligenceJobStore(store_path) as restored_store:
        with PraisonBackgroundIntelligenceQueue(
            service=_MustNotRunService(),
            job_store=restored_store,
        ) as restored_queue:
            restored = restored_queue.get_progress(queued.job_id)

    assert cancelled.state is BackgroundIntelligenceJobState.CANCELLED
    assert restored.state is BackgroundIntelligenceJobState.CANCELLED
    assert tuple(event.event_type for event in events) == (
        "submitted",
        "cancelled",
    )


def test_corrupt_persisted_progress_fails_closed_before_worker_start(
    tmp_path: Path,
) -> None:
    request = _request()
    progress = BackgroundIntelligenceJobProgress(
        request_id=request.request_id,
        mission_id=request.mission_id,
        workspace_binding=request.workspace_binding,
        state=BackgroundIntelligenceJobState.QUEUED,
        stage="queued",
        progress_percent=0,
        submitted_at=datetime.now(UTC),
    )
    store_path = tmp_path / "corrupt-jobs.sqlite3"
    with SQLiteBackgroundIntelligenceJobStore(store_path) as store:
        store.save_job(
            request=request,
            progress=progress,
            response=None,
            event_type="submitted",
        )
    with sqlite3.connect(store_path) as connection:
        connection.execute(
            "UPDATE background_intelligence_jobs SET progress_json = ?",
            ('{"state":"completed","runtime_safety_truth":true}',),
        )

    with SQLiteBackgroundIntelligenceJobStore(store_path) as corrupt_store:
        with pytest.raises(BackgroundJobStoreCorrupt):
            PraisonBackgroundIntelligenceQueue(
                service=_MustNotRunService(),
                job_store=corrupt_store,
            )
