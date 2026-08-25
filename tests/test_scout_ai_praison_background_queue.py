from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from scout.nextgen import (
    CapabilityBroker,
    GeoScope,
    IntelligenceRequest,
    IntelligenceTaskType,
    StubIntelligenceGateway,
    WorkspaceBinding,
)
from scout.nextgen.praison_background_queue import (
    BackgroundIntelligenceJobCancelled,
    BackgroundIntelligenceJobFailed,
    BackgroundIntelligenceResultStale,
    BackgroundIntelligenceJobState,
    BackgroundIntelligenceResourceUnavailable,
    BackgroundIntelligenceQueueFull,
    PraisonBackgroundIntelligenceQueue,
)
from scout.nextgen.edge_resource_policy import (
    EdgeBackgroundResourcePolicy,
    EdgeResourceSnapshot,
)
from scout.nextgen.praison_service import (
    CapabilitySession,
    EvidenceCatalog,
    EvidenceCatalogItem,
    PraisonIntelligenceService,
    PraisonRunResult,
)


def _request() -> IntelligenceRequest:
    request_id = uuid4()
    evidence_refs = ("dem:background-route",)
    grant = CapabilityBroker().issue_grant(
        request_id=request_id,
        mission_id="mission-background",
        task_type=IntelligenceTaskType.TERRAIN_ANALYSIS,
        allowed_capabilities=("dem.read",),
        evidence_refs_allowed=evidence_refs,
        max_model_requests=10,
        max_tool_calls=10,
    )
    return IntelligenceRequest(
        request_id=request_id,
        mission_id="mission-background",
        task_type=IntelligenceTaskType.TERRAIN_ANALYSIS,
        question="Analyze candidate terrain evidence in the background.",
        workspace_binding=WorkspaceBinding(
            workspace_id="workspace-background",
            workspace_revision="revision-1",
            mission_id="mission-background",
            mission_version="mission-version-1",
            route_id="route-background",
            route_version="route-version-1",
            input_hash="background-input-hash",
            generated_at=datetime(2026, 8, 23, tzinfo=UTC),
        ),
        capability_grant=grant,
        geographic_scope=GeoScope(
            route_id="route-background",
            corridor_meters=250,
        ),
        evidence_refs=evidence_refs,
        max_runtime_seconds=10,
        max_model_requests=10,
    )


class _ControlledPraisonService:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def execute(
        self,
        request: IntelligenceRequest,
        *,
        cancellation_event: threading.Event | None = None,
        progress_callback: Callable[[str, int], None] | None = None,
    ) -> Any:
        self.calls += 1
        if progress_callback is not None:
            progress_callback("resolving_evidence", 15)
        self.started.set()
        while not self.release.wait(timeout=0.01):
            if cancellation_event is not None and cancellation_event.is_set():
                if progress_callback is not None:
                    progress_callback("cancelling", 80)
                return StubIntelligenceGateway().execute(request)
        if progress_callback is not None:
            progress_callback("validating_response", 90)
        return StubIntelligenceGateway().execute(request)


class _NeverRunRuntime:
    runtime_id = "praison.never-run"

    def __init__(self) -> None:
        self.calls = 0

    def run(
        self,
        *,
        request: IntelligenceRequest,
        evidence: tuple[EvidenceCatalogItem, ...],
        capabilities: CapabilitySession,
        cancellation_event: threading.Event | None = None,
        progress_callback: Callable[[str, int], None] | None = None,
    ) -> PraisonRunResult:
        del request, evidence, capabilities, cancellation_event, progress_callback
        self.calls += 1
        raise AssertionError("cancelled Praison request reached the runtime")


class _ReplayRuntime:
    runtime_id = "praison.background-replay"

    def run(
        self,
        *,
        request: IntelligenceRequest,
        evidence: tuple[EvidenceCatalogItem, ...],
        capabilities: CapabilitySession,
        cancellation_event: threading.Event | None = None,
        progress_callback: Callable[[str, int], None] | None = None,
    ) -> PraisonRunResult:
        del request, capabilities
        assert evidence
        assert cancellation_event is not None
        assert cancellation_event.is_set() is False
        if progress_callback is not None:
            progress_callback("specialist:terrain:running", 35)
        return PraisonRunResult(
            reports=(),
            agent_path=("praisonai.orchestrator", "background-replay"),
        )


class _MalformedService:
    def execute(
        self,
        request: IntelligenceRequest,
        *,
        cancellation_event: threading.Event | None = None,
        progress_callback: Callable[[str, int], None] | None = None,
    ) -> Any:
        del request, cancellation_event, progress_callback
        return {"candidate_only": False, "runtime_safety_truth": True}


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


def test_background_queue_reports_progress_and_completed_candidate_result() -> None:
    service = _ControlledPraisonService()
    with PraisonBackgroundIntelligenceQueue(
        service=service,
        max_queue_size=4,
    ) as queue:
        submitted = queue.submit(_request())
        assert submitted.state is BackgroundIntelligenceJobState.QUEUED
        assert service.started.wait(timeout=1)

        running = queue.get_progress(submitted.job_id)
        assert running.state is BackgroundIntelligenceJobState.RUNNING
        assert running.stage == "resolving_evidence"
        assert running.progress_percent == 15
        assert running.response_available is False

        service.release.set()
        completed = queue.wait(submitted.job_id, timeout_seconds=2)
        response = queue.result(
            submitted.job_id,
            current_binding=_request().workspace_binding,
        )

    assert completed.state is BackgroundIntelligenceJobState.COMPLETED
    assert completed.progress_percent == 100
    assert completed.response_available is True
    assert response.request_id == submitted.request_id
    assert response.candidate_only is True
    assert response.runtime_safety_truth is False


def test_background_queue_executes_real_praison_service_boundary() -> None:
    request = _request()
    service = PraisonIntelligenceService(
        runtime=_ReplayRuntime(),
        evidence_catalog=EvidenceCatalog(
            items=(
                EvidenceCatalogItem(
                    evidence_id="ev-background-dem",
                    source_ref="dem:background-route",
                    source_type="prepared_dem",
                    content_hash="background-dem-hash",
                    summary="Prepared candidate DEM for queue replay.",
                ),
            )
        ),
    )
    with PraisonBackgroundIntelligenceQueue(service=service) as queue:
        submitted = queue.submit(request)
        completed = queue.wait(submitted.job_id, timeout_seconds=2)
        response = queue.result(
            submitted.job_id,
            current_binding=request.workspace_binding,
        )

    assert completed.state is BackgroundIntelligenceJobState.COMPLETED
    assert response.provenance.agent_path == (
        "praisonai.orchestrator",
        "background-replay",
    )
    assert tuple(item.evidence_id for item in response.evidence) == (
        "ev-background-dem",
    )
    assert response.candidate_only is True
    assert response.runtime_safety_truth is False


def test_background_queue_cancels_running_and_queued_jobs() -> None:
    service = _ControlledPraisonService()
    with PraisonBackgroundIntelligenceQueue(
        service=service,
        max_queue_size=4,
    ) as queue:
        running_job = queue.submit(_request())
        assert service.started.wait(timeout=1)
        queued_job = queue.submit(_request())

        queued_cancelled = queue.cancel(queued_job.job_id)
        assert queued_cancelled.state is BackgroundIntelligenceJobState.CANCELLED
        assert queued_cancelled.progress_percent == 100

        running_cancel = queue.cancel(running_job.job_id)
        assert running_cancel.state in {
            BackgroundIntelligenceJobState.CANCELLING,
            BackgroundIntelligenceJobState.CANCELLED,
        }
        running_final = queue.wait(running_job.job_id, timeout_seconds=2)
        queued_final = queue.wait(queued_job.job_id, timeout_seconds=2)

        with pytest.raises(BackgroundIntelligenceJobCancelled):
            queue.result(
                running_job.job_id,
                current_binding=running_job.workspace_binding,
            )
        with pytest.raises(BackgroundIntelligenceJobCancelled):
            queue.result(
                queued_job.job_id,
                current_binding=queued_job.workspace_binding,
            )

    assert running_final.state is BackgroundIntelligenceJobState.CANCELLED
    assert queued_final.state is BackgroundIntelligenceJobState.CANCELLED
    assert service.calls == 1


def test_background_queue_rejects_malformed_or_authoritative_result() -> None:
    with PraisonBackgroundIntelligenceQueue(service=_MalformedService()) as queue:
        submitted = queue.submit(_request())
        failed = queue.wait(submitted.job_id, timeout_seconds=2)

        with pytest.raises(BackgroundIntelligenceJobFailed):
            queue.result(
                submitted.job_id,
                current_binding=submitted.workspace_binding,
            )

    assert failed.state is BackgroundIntelligenceJobState.FAILED
    assert failed.response_available is False
    assert failed.error_type == "ValidationError"
    assert failed.runtime_safety_truth is False


def test_background_queue_applies_bounded_backpressure() -> None:
    service = _ControlledPraisonService()
    with PraisonBackgroundIntelligenceQueue(
        service=service,
        max_queue_size=1,
    ) as queue:
        running = queue.submit(_request())
        assert service.started.wait(timeout=1)
        queued = queue.submit(_request())

        with pytest.raises(BackgroundIntelligenceQueueFull):
            queue.submit(_request())

        queue.cancel(queued.job_id)
        queue.cancel(running.job_id)
        queue.wait(running.job_id, timeout_seconds=2)


def test_praison_service_fails_closed_when_cancelled_before_execution() -> None:
    request = _request()
    runtime = _NeverRunRuntime()
    cancellation_event = threading.Event()
    cancellation_event.set()
    progress: list[tuple[str, int]] = []
    service = PraisonIntelligenceService(runtime=runtime)

    started = time.monotonic()
    response = service.execute(
        request,
        cancellation_event=cancellation_event,
        progress_callback=lambda stage, percent: progress.append((stage, percent)),
    )

    assert time.monotonic() - started < 0.5
    assert runtime.calls == 0
    assert response.findings == ()
    assert response.uncertainties[0].uncertainty_id == "intelligence_cancelled"
    assert progress[-1] == ("cancelled", 100)
    assert response.candidate_only is True
    assert response.runtime_safety_truth is False


def test_background_queue_rejects_stale_result_at_consumption() -> None:
    request = _request()
    with PraisonBackgroundIntelligenceQueue(
        service=_ImmediateStubService(),
    ) as queue:
        submitted = queue.submit(request)
        queue.wait(submitted.job_id, timeout_seconds=2)
        stale_binding = request.workspace_binding.model_copy(
            update={
                "workspace_revision": "revision-2",
                "input_hash": "background-input-hash-2",
            }
        )

        with pytest.raises(BackgroundIntelligenceResultStale):
            queue.result(
                submitted.job_id,
                current_binding=stale_binding,
            )


def test_background_queue_applies_resource_backpressure_before_submit() -> None:
    service = _ControlledPraisonService()
    snapshot = EdgeResourceSnapshot(
        observed_at=datetime.now(UTC),
        available_memory_mb=512,
        swap_used_mb=900,
        cpu_temperature_c=79.0,
        throttled=True,
        source="test-resource-monitor",
    )
    with PraisonBackgroundIntelligenceQueue(
        service=service,
        resource_snapshot_provider=lambda: snapshot,
        resource_policy=EdgeBackgroundResourcePolicy(
            min_available_memory_mb=2048,
            max_swap_used_mb=512,
            max_cpu_temperature_c=75.0,
        ),
    ) as queue:
        with pytest.raises(BackgroundIntelligenceResourceUnavailable) as exc_info:
            queue.submit(_request())

    assert "available memory" in str(exc_info.value)
    assert "swap" in str(exc_info.value)
    assert "temperature" in str(exc_info.value)
    assert "throttled" in str(exc_info.value)
    assert service.calls == 0


def test_background_queue_rechecks_resources_before_starting_next_job() -> None:
    service = _ControlledPraisonService()
    healthy = EdgeResourceSnapshot(
        observed_at=datetime.now(UTC),
        available_memory_mb=4096,
        swap_used_mb=0,
        cpu_temperature_c=55.0,
        throttled=False,
        source="test-resource-monitor",
    )
    constrained = healthy.model_copy(
        update={
            "observed_at": datetime.now(UTC),
            "available_memory_mb": 512,
        }
    )
    current_snapshot = {"value": healthy}
    with PraisonBackgroundIntelligenceQueue(
        service=service,
        max_queue_size=4,
        resource_snapshot_provider=lambda: current_snapshot["value"],
    ) as queue:
        running = queue.submit(_request())
        assert service.started.wait(timeout=1)
        queued = queue.submit(_request())
        current_snapshot["value"] = constrained
        service.release.set()

        running_final = queue.wait(running.job_id, timeout_seconds=2)
        queued_final = queue.wait(queued.job_id, timeout_seconds=2)

    assert running_final.state is BackgroundIntelligenceJobState.COMPLETED
    assert queued_final.state is BackgroundIntelligenceJobState.FAILED
    assert queued_final.error_type == "ResourceBackpressure"
    assert service.calls == 1
