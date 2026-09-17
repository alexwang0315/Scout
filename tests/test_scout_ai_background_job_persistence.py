from __future__ import annotations

import sqlite3
from contextlib import closing
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from stat import S_IMODE
from typing import Any
from unittest.mock import Mock
from uuid import uuid4

import pytest

from scout.nextgen import (
    CapabilityBroker,
    IntelligenceRequest,
    IntelligenceResponse,
    IntelligenceTaskType,
    ModelExecutionRecord,
    StubIntelligenceGateway,
    WorkspaceBinding,
    degraded_intelligence_response,
)
from scout.nextgen.background_job_store import (
    BackgroundJobStoreCorrupt,
    SQLiteBackgroundIntelligenceJobStore,
)
from scout.nextgen.intelligence_gateway import GatewayValidationDisposition
from scout.nextgen.praison_background_queue import (
    BackgroundIntelligenceJobCancelled,
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


@pytest.mark.parametrize(
    ("expire_at_completion", "record_kind"),
    (
        pytest.param(False, "matching", id="valid-grant"),
        pytest.param(True, "matching", id="expired-grant"),
        pytest.param(True, "foreign", id="expired-grant-foreign-parent"),
        pytest.param(True, "mixed", id="expired-grant-mixed-parents"),
    ),
)
def test_running_cancellation_telemetry_survives_restart_without_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    expire_at_completion: bool,
    record_kind: str,
) -> None:
    request = _request()
    recorded_at = datetime.now(UTC)
    record = ModelExecutionRecord(
        parent_request_id=request.request_id,
        inference_id=uuid4(),
        runtime_id="local.cancel.probe",
        model_id="cancel-probe",
        locality="edge",
        started_at=recorded_at,
        completed_at=recorded_at,
        latency_ms=0,
        status="cancelled",
        model_request_count=1,
    )
    foreign_record = record.model_copy(
        update={
            "execution_id": uuid4(),
            "parent_request_id": uuid4(),
            "inference_id": uuid4(),
        }
    )
    response_records = {
        "matching": (record,),
        "foreign": (foreign_record,),
        "mixed": (record, foreign_record),
    }[record_kind]
    expected_records = () if record_kind == "foreign" else (record,)
    started = threading.Event()

    class _CancellingStubService:
        def execute(
            self,
            request: IntelligenceRequest,
            *,
            cancellation_event: threading.Event | None = None,
            progress_callback: Callable[[str, int], None] | None = None,
        ) -> IntelligenceResponse:
            del progress_callback
            assert cancellation_event is not None
            started.set()
            assert cancellation_event.wait(timeout=2)
            return degraded_intelligence_response(
                request=request,
                uncertainty_id="intelligence_cancelled",
                description="Background candidate intelligence was cancelled.",
                missing_evidence=("model_response",),
                impact="Candidate intelligence is unavailable.",
                service_name="cancellation-telemetry-test",
                service_version="test",
                agent_path=("cancellation-telemetry-test",),
                model_execution_records=response_records,
            )

    store_path = tmp_path / "running-cancelled-jobs.sqlite3"
    with SQLiteBackgroundIntelligenceJobStore(store_path) as store:
        with PraisonBackgroundIntelligenceQueue(
            service=_CancellingStubService(),
            job_store=store,
        ) as queue:
            submitted = queue.submit(request)
            assert started.wait(timeout=1)
            running = queue.get_progress(submitted.job_id)
            assert running.state is BackgroundIntelligenceJobState.RUNNING

            if expire_at_completion:
                # Only completion validation observes an expired grant.
                monkeypatch.setattr(
                    queue._contract_gateway,
                    "validate_response",
                    partial(
                        queue._contract_gateway.validate_response,
                        now=request.capability_grant.expires_at + timedelta(seconds=1),
                    ),
                )

            cancelling = queue.cancel(submitted.job_id)
            assert cancelling.state is BackgroundIntelligenceJobState.CANCELLING
            terminal = queue.wait(submitted.job_id, timeout_seconds=2)
            assert terminal.state is BackgroundIntelligenceJobState.CANCELLED
            assert terminal.cancellation_requested is True
            assert terminal.progress_percent == 100
            assert terminal.completed_at is not None
            assert terminal.response_available is False
            if expire_at_completion:
                assert (
                    terminal.validation_disposition
                    is GatewayValidationDisposition.CAPABILITY_VIOLATION
                )
                assert terminal.validation_reasons == ("capability grant expired",)
            assert all(
                item.parent_request_id == request.request_id
                for item in terminal.model_execution_records
            )
            with pytest.raises(BackgroundIntelligenceJobCancelled):
                queue.result(
                    submitted.job_id,
                    current_binding=request.workspace_binding,
                )

        (stored,) = store.load_jobs()
        assert stored.response is None
        assert (
            BackgroundIntelligenceJobProgress.model_validate_json(stored.progress_json)
            == terminal
        )
        events = store.list_events(submitted.job_id)
        assert tuple(event.event_type for event in events) == (
            "submitted",
            "started",
            "cancelling",
            "cancelled",
        )

    restored_service = Mock(wraps=_MustNotRunService())
    with SQLiteBackgroundIntelligenceJobStore(store_path) as restored_store:
        with PraisonBackgroundIntelligenceQueue(
            service=restored_service,
            job_store=restored_store,
        ) as restored_queue:
            restored = restored_queue.wait(submitted.job_id, timeout_seconds=0)
            assert restored == terminal
            with pytest.raises(BackgroundIntelligenceJobCancelled):
                restored_queue.result(
                    submitted.job_id,
                    current_binding=request.workspace_binding,
                )

        assert restored_store.load_jobs() == (stored,)
        assert restored_store.list_events(submitted.job_id) == events
    restored_service.execute.assert_not_called()
    assert terminal.model_execution_records == expected_records


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
    with closing(sqlite3.connect(store_path)) as connection, connection:
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
