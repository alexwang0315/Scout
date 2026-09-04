from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from scout.nextgen import (
    CapabilityBroker,
    IntelligenceRequest,
    IntelligenceTaskType,
    WorkspaceBinding,
)
from scout.nextgen.intelligence_mcp_http import (
    IntelligenceMcpHttpClient,
    IntelligenceMcpHttpClientConfig,
)
from scout.nextgen.praison_background_queue import BackgroundIntelligenceJobState


def test_socket_is_private_before_group_access_is_enabled(monkeypatch) -> None:
    from scout.nextgen.intelligence_mcp_http_server import _bind_private_socket

    socket_path = Path("/tmp") / f"scout-private-{uuid4().hex}.sock"
    observed_modes = []
    original_chmod = os.chmod

    def check_private_before_chmod(path, mode):
        observed_modes.append(path.stat().st_mode & 0o777)
        original_chmod(path, mode)

    monkeypatch.setattr(os, "chmod", check_private_before_chmod)
    previous_umask = os.umask(0o022)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            _bind_private_socket(listener, socket_path)
            assert observed_modes == [0o600]
            assert socket_path.stat().st_mode & 0o777 == 0o660
            assert os.umask(0o022) == 0o022
    finally:
        os.umask(previous_umask)
        socket_path.unlink(missing_ok=True)


def test_socket_bind_failure_restores_umask() -> None:
    from scout.nextgen.intelligence_mcp_http_server import _bind_private_socket

    socket_path = Path("/tmp") / f"scout-bound-{uuid4().hex}.sock"
    previous_umask = os.umask(0o022)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as owner:
            owner.bind(str(socket_path))
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
                with pytest.raises(OSError):
                    _bind_private_socket(listener, socket_path)
            assert os.umask(0o022) == 0o022
    finally:
        os.umask(previous_umask)
        socket_path.unlink(missing_ok=True)


def _request() -> IntelligenceRequest:
    request_id = uuid4()
    evidence_refs = ("dem:http-background-route",)
    grant = CapabilityBroker().issue_grant(
        request_id=request_id,
        mission_id="mission-http-background",
        task_type=IntelligenceTaskType.TERRAIN_ANALYSIS,
        allowed_capabilities=("dem.read",),
        evidence_refs_allowed=evidence_refs,
        max_runtime_seconds=30,
        max_model_requests=10,
        max_tool_calls=10,
    )
    return IntelligenceRequest(
        request_id=request_id,
        mission_id="mission-http-background",
        task_type=IntelligenceTaskType.TERRAIN_ANALYSIS,
        question="Analyze candidate terrain evidence through MCP HTTP.",
        workspace_binding=WorkspaceBinding(
            workspace_id="workspace-http-background",
            workspace_revision="revision-1",
            mission_id="mission-http-background",
            mission_version="mission-version-1",
            route_id="route-http-background",
            route_version="route-version-1",
            input_hash="http-background-input-hash",
            generated_at=datetime(2026, 9, 3, tzinfo=UTC),
        ),
        capability_grant=grant,
        evidence_refs=evidence_refs,
        max_runtime_seconds=30,
        max_model_requests=10,
    )


def test_streamable_http_unix_socket_background_round_trip(tmp_path: Path) -> None:
    socket_path = Path("/tmp") / f"scout-intelligence-{uuid4().hex}.sock"
    store_path = tmp_path / "background-http.sqlite3"
    env = {
        **os.environ,
        "PYTHONPATH": str(Path("src").resolve()),
        "PRAISONAI_TELEMETRY_DISABLED": "true",
    }
    process = subprocess.Popen(
        (
            sys.executable,
            "-m",
            "scout.nextgen.intelligence_mcp_http_server",
            "--mode",
            "stub",
            "--unix-socket",
            str(socket_path),
            "--background-job-store",
            str(store_path),
        ),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        # Cold MCP imports on a busy development host are not an inference SLO.
        deadline = time.monotonic() + 30
        ready = False
        with httpx.Client(
            transport=httpx.HTTPTransport(uds=str(socket_path)),
            timeout=1,
            trust_env=False,
        ) as health_client:
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    stderr = process.stderr.read() if process.stderr is not None else ""
                    raise AssertionError(f"MCP HTTP server exited early: {stderr}")
                try:
                    response = health_client.get("http://localhost/health")
                    ready = response.status_code == 200 and response.json()["status"] == "ok"
                except httpx.TransportError:
                    ready = False
                if ready:
                    break
                time.sleep(0.02)
        assert ready, "MCP HTTP server did not become healthy"
        assert socket_path.stat().st_mode & 0o777 == 0o660

        request = _request()
        client = IntelligenceMcpHttpClient(
            IntelligenceMcpHttpClientConfig(unix_socket=socket_path)
        )
        submission = client.submit_background(request)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            progress = client.background_progress(submission.access)
            if progress.state is BackgroundIntelligenceJobState.COMPLETED:
                break
            time.sleep(0.02)
        assert progress.state is BackgroundIntelligenceJobState.COMPLETED

        response = client.background_result(
            submission.access,
            request=request,
            current_binding=request.workspace_binding,
        )
    finally:
        process.terminate()
        process.wait(timeout=5)
        socket_path.unlink(missing_ok=True)

    assert response.request_id == request.request_id
    assert response.candidate_only is True
    assert response.runtime_safety_truth is False
    assert store_path.stat().st_mode & 0o777 == 0o600
