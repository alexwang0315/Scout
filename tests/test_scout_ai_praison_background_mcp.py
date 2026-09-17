from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
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
from scout.nextgen.intelligence_mcp import (
    IntelligenceMcpClientConfig,
    IntelligenceMcpProtocolError,
    IntelligenceMcpStdioClient,
)
from scout.nextgen.praison_background_mcp import (
    BackgroundIntelligenceJobAccessRejected,
    PraisonBackgroundMcpService,
)
from scout.nextgen.praison_background_queue import (
    BackgroundIntelligenceJobState,
)


def _request() -> IntelligenceRequest:
    request_id = uuid4()
    evidence_refs = ("dem:mcp-background-route",)
    grant = CapabilityBroker().issue_grant(
        request_id=request_id,
        mission_id="mission-mcp-background",
        task_type=IntelligenceTaskType.TERRAIN_ANALYSIS,
        allowed_capabilities=("dem.read",),
        evidence_refs_allowed=evidence_refs,
        max_runtime_seconds=30,
        max_model_requests=10,
        max_tool_calls=10,
    )
    return IntelligenceRequest(
        request_id=request_id,
        mission_id="mission-mcp-background",
        task_type=IntelligenceTaskType.TERRAIN_ANALYSIS,
        question="Analyze candidate terrain evidence as a background job.",
        workspace_binding=WorkspaceBinding(
            workspace_id="workspace-mcp-background",
            workspace_revision="revision-1",
            mission_id="mission-mcp-background",
            mission_version="mission-version-1",
            route_id="route-mcp-background",
            route_version="route-version-1",
            input_hash="mcp-background-input-hash",
            generated_at=datetime(2026, 9, 3, tzinfo=UTC),
        ),
        capability_grant=grant,
        geographic_scope=GeoScope(
            route_id="route-mcp-background",
            corridor_meters=250,
        ),
        evidence_refs=evidence_refs,
        max_runtime_seconds=30,
        max_model_requests=10,
    )


class _ControlledService:
    def __init__(self) -> None:
        self.started = threading.Event()

    def execute(
        self,
        request: IntelligenceRequest,
        *,
        cancellation_event: threading.Event | None = None,
        progress_callback: Callable[[str, int], None] | None = None,
    ) -> Any:
        if progress_callback is not None:
            progress_callback("model_running", 40)
        self.started.set()
        while cancellation_event is None or not cancellation_event.wait(0.01):
            pass
        return StubIntelligenceGateway().execute(request)


def test_background_mcp_adapter_binds_access_and_cancels_running_job() -> None:
    worker = _ControlledService()
    with PraisonBackgroundMcpService(service=worker) as service:
        submission = service.submit(_request())
        assert worker.started.wait(timeout=1)

        running = service.progress(submission.access)
        assert running.state is BackgroundIntelligenceJobState.RUNNING
        assert running.candidate_only is True
        assert running.runtime_safety_truth is False

        tampered = submission.access.model_copy(
            update={"mission_id": "different-mission"}
        )
        with pytest.raises(BackgroundIntelligenceJobAccessRejected):
            service.progress(tampered)

        cancelling = service.cancel(submission.access)
        assert cancelling.cancellation_requested is True
        terminal = service.wait(submission.access, timeout_seconds=2)

    assert terminal.state is BackgroundIntelligenceJobState.CANCELLED
    assert terminal.response_available is False


def test_stdio_mcp_background_lifecycle_survives_client_restart(tmp_path: Path) -> None:
    request = _request()
    store_path = tmp_path / "background-mcp.sqlite3"
    config = IntelligenceMcpClientConfig(
        command=(
            sys.executable,
            "-m",
            "scout.nextgen.intelligence_mcp_server",
            "--mode",
            "stub",
            "--background",
            "--background-job-store",
            str(store_path),
        ),
        pythonpath=str(Path("src").resolve()),
        timeout_seconds=5,
    )

    first_client = IntelligenceMcpStdioClient(config)
    try:
        submission = first_client.submit_background(request)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            progress = first_client.background_progress(submission.access)
            if progress.state in {
                BackgroundIntelligenceJobState.COMPLETED,
                BackgroundIntelligenceJobState.FAILED,
            }:
                break
            time.sleep(0.01)
        else:
            pytest.fail("background MCP job did not complete")
        assert progress.state is BackgroundIntelligenceJobState.COMPLETED, progress
    finally:
        first_client.close()

    with IntelligenceMcpStdioClient(config) as second_client:
        restored = second_client.background_progress(submission.access)
        response = second_client.background_result(
            submission.access,
            request=request,
            current_binding=request.workspace_binding,
        )

        stale_binding = request.workspace_binding.model_copy(
            update={
                "workspace_revision": "revision-2",
                "input_hash": "changed-input-hash",
            }
        )
        with pytest.raises(IntelligenceMcpProtocolError, match="stale"):
            second_client.background_result(
                submission.access,
                request=request,
                current_binding=stale_binding,
            )

    assert restored.state is BackgroundIntelligenceJobState.COMPLETED
    assert response.request_id == request.request_id
    assert response.candidate_only is True
    assert response.runtime_safety_truth is False
    assert store_path.stat().st_mode & 0o777 == 0o600


def test_stdio_mcp_rejects_tampered_background_job_binding(tmp_path: Path) -> None:
    request = _request()
    config = IntelligenceMcpClientConfig(
        command=(
            sys.executable,
            "-m",
            "scout.nextgen.intelligence_mcp_server",
            "--mode",
            "stub",
            "--background",
            "--background-job-store",
            str(tmp_path / "tampered-job.sqlite3"),
        ),
        pythonpath=str(Path("src").resolve()),
        timeout_seconds=5,
    )

    with IntelligenceMcpStdioClient(config) as client:
        submission = client.submit_background(request)
        tampered = submission.access.model_copy(
            update={"request_id": uuid4()}
        )
        with pytest.raises(IntelligenceMcpProtocolError, match="binding"):
            client.background_progress(tampered)
