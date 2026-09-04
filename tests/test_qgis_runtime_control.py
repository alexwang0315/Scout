from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from qgis_runtime_control import (
    QgisRuntimeControlCode,
    QgisRuntimeControlRequest,
    QgisRuntimeController,
    QgisRuntimeUnavailable,
)
from qgis_spatial_contracts import QgisBackendAvailability, QgisBackendStatus


def _status(ready: bool) -> QgisBackendStatus:
    return QgisBackendStatus(
        availability=QgisBackendAvailability.AVAILABLE if ready else QgisBackendAvailability.UNAVAILABLE,
        enabled=True, configured=True, reachable=ready,
        qgis_application_available=ready, plugin_bridge_available=ready,
        capabilities_discoverable=ready,
    )


class FakeHost:
    def __init__(self, *, ready: bool = False, listening: bool = False) -> None:
        self.ready = ready
        self.listening = listening
        self.events: list[str] = []
        self.issue: QgisRuntimeControlCode | None = None
        self.qgis_error: QgisRuntimeControlCode | None = None
        self.become_ready = True

    def configuration_issue(self) -> QgisRuntimeControlCode | None:
        return self.issue

    def probe(self, project_id: str) -> QgisBackendStatus:
        self.events.append("probe")
        return _status(self.ready)

    def worker_listening(self) -> bool:
        return self.listening

    def worker_authenticated(self) -> bool:
        return self.listening

    def ensure_qgis(self) -> str:
        self.events.append("ensure_qgis")
        if self.qgis_error:
            raise QgisRuntimeUnavailable(self.qgis_error)
        if self.listening:
            self.ready = self.become_ready
        return "existing_qgis_preserved"

    def start_worker(self) -> str:
        self.events.append("start_worker")
        self.listening = True
        self.ready = self.become_ready
        return "worker_started"


class Clock:
    now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _controller(tmp_path: Path, host: FakeHost) -> QgisRuntimeController:
    clock = Clock()
    return QgisRuntimeController(
        host=host, runtime_root=tmp_path / "runtime", startup_timeout_s=2,
        poll_interval_s=0.5, monotonic=clock.monotonic, sleep=clock.sleep,
    )


def test_runtime_get_is_read_only_and_never_launches_services(tmp_path: Path) -> None:
    host = FakeHost()
    result = _controller(tmp_path, host).snapshot(project_id="demo")
    assert result.status == "idle"
    assert result.can_start is True
    assert host.events == []
    assert not (tmp_path / "runtime").exists()


def test_runtime_start_waits_for_real_handshake_and_records_candidate_receipts(tmp_path: Path) -> None:
    host = FakeHost()
    result = _controller(tmp_path, host).ensure_ready(project_id="demo")
    assert result.status == "ready"
    assert result.code == QgisRuntimeControlCode.READY
    assert host.events == ["probe", "ensure_qgis", "start_worker", "probe"]
    assert result.actions == ["existing_qgis_preserved", "worker_started"]
    assert result.authority == "candidate_only"
    assert result.runtime_safety_truth is False
    assert result.operational is False
    receipts = [json.loads(line) for line in (tmp_path / "runtime" / "qgis-runtime-control.jsonl").read_text().splitlines()]
    assert [item["status"] for item in receipts] == ["starting", "ready"]
    assert receipts[0]["request_id"] == receipts[1]["request_id"]
    assert receipts[1]["project_id"] == "demo"


def test_ready_worker_is_reused_without_any_process_action(tmp_path: Path) -> None:
    host = FakeHost(ready=True, listening=True)
    result = _controller(tmp_path, host).ensure_ready(project_id="demo")
    assert result.status == "ready"
    assert host.events == ["probe"]
    assert result.actions == []


def test_existing_worker_is_not_restarted_to_restore_qgis(tmp_path: Path) -> None:
    host = FakeHost(listening=True)
    result = _controller(tmp_path, host).ensure_ready(project_id="demo")
    assert result.status == "ready"
    assert "start_worker" not in host.events
    assert "existing_qgis_preserved" in result.actions


@pytest.mark.parametrize("code", (
    QgisRuntimeControlCode.REMOTE_MANAGED,
    QgisRuntimeControlCode.CONFIGURATION_REQUIRED,
    QgisRuntimeControlCode.FIXTURE_MODE,
))
def test_unmanaged_configuration_never_starts_anything(tmp_path: Path, code: QgisRuntimeControlCode) -> None:
    host = FakeHost()
    host.issue = code
    result = _controller(tmp_path, host).ensure_ready(project_id="demo")
    assert result.status == "unavailable"
    assert result.code == code
    assert result.can_start is False
    assert host.events == []


def test_unresponsive_existing_qgis_session_is_not_closed_or_replaced(tmp_path: Path) -> None:
    host = FakeHost()
    host.qgis_error = QgisRuntimeControlCode.QGIS_SESSION_REQUIRES_ATTENTION
    result = _controller(tmp_path, host).ensure_ready(project_id="demo")
    assert result.status == "unavailable"
    assert result.code == QgisRuntimeControlCode.QGIS_SESSION_REQUIRES_ATTENTION
    assert host.events == ["probe", "ensure_qgis"]


def test_listening_port_does_not_prove_readiness(tmp_path: Path) -> None:
    host = FakeHost()
    host.become_ready = False
    result = _controller(tmp_path, host).ensure_ready(project_id="demo")
    assert result.status == "unavailable"
    assert result.code == QgisRuntimeControlCode.START_TIMEOUT
    assert host.events.count("start_worker") == 1


def test_repeat_start_is_bounded_and_does_not_duplicate_worker(tmp_path: Path) -> None:
    host = FakeHost()
    controller = _controller(tmp_path, host)
    first = controller.ensure_ready(project_id="demo")
    second = controller.ensure_ready(project_id="demo")
    assert second.request_id == first.request_id
    assert host.events.count("start_worker") == 1


def test_concurrent_start_returns_busy_without_starting_another_worker(tmp_path: Path) -> None:
    host = FakeHost()
    controller = _controller(tmp_path, host)
    assert controller._lock.acquire(blocking=False)
    try:
        result = controller.ensure_ready(project_id="demo")
    finally:
        controller._lock.release()
    assert result.code == QgisRuntimeControlCode.BUSY
    assert host.events == []


@pytest.mark.parametrize("payload", (
    {"worker_url": "http://other-host"}, {"command": "sh"}, {"env": {"PATH": "/tmp"}},
    {"candidate_only": False}, {"runtime_safety_truth": True}, {"action": "restart"},
))
def test_runtime_request_cannot_select_commands_hosts_or_authority(payload: dict) -> None:
    with pytest.raises(ValidationError):
        QgisRuntimeControlRequest.model_validate(payload)
