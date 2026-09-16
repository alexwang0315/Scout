from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from scout.nextgen.dashboard_telemetry import SQLiteBackgroundIntelligenceTelemetryReader
from tests.test_scout_ai_dashboard_telemetry import _persist_completed_job
from tests.test_hardware_monitor_proxy import _status_payload
from tools.hardware_monitor_proxy import (
    HardwareMonitorUpstreamError,
    create_hardware_monitor_proxy_router,
)


def test_intelligence_corruption_then_restore_is_observed_without_reader_writes(
    tmp_path: Path,
) -> None:
    unconfigured = SQLiteBackgroundIntelligenceTelemetryReader(None).snapshot()
    assert (unconfigured.status, unconfigured.status_reason) == ("unavailable", "store_not_configured")
    path = tmp_path / "jobs.sqlite3"
    _request, _response, job_id = _persist_completed_job(path)
    reader = SQLiteBackgroundIntelligenceTelemetryReader(path)
    with closing(sqlite3.connect(path)) as connection:
        original = connection.execute("SELECT request_json FROM background_intelligence_jobs").fetchone()[0]
        corrupt = json.loads(original)
        corrupt["schema_version"] = "unsupported.future.v999"
        connection.execute("UPDATE background_intelligence_jobs SET request_json = ?", (json.dumps(corrupt),))
        connection.commit()
    corrupt_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    unavailable = reader.snapshot()
    assert unavailable.status == "degraded"
    assert unavailable.jobs == ()
    assert unavailable.runtime_safety_truth is False
    assert hashlib.sha256(path.read_bytes()).hexdigest() == corrupt_sha

    with closing(sqlite3.connect(path)) as connection:
        connection.execute("UPDATE background_intelligence_jobs SET request_json = ?", (original,))
        connection.commit()
    restored_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    ready = reader.snapshot()
    assert ready.status == "ready"
    assert len(ready.jobs) == 1 and str(ready.jobs[0].job_id) == job_id
    assert ready.read_only is True and ready.candidate_only is True
    assert ready.runtime_safety_truth is False
    assert hashlib.sha256(path.read_bytes()).hexdigest() == restored_sha


def test_monitor_disconnect_stale_then_fresh_recovery_keeps_get_only_boundary() -> None:
    calls = []
    stale = _status_payload(status="stale", data={"captured_at": "2026-09-11T01:59:00Z"})
    fresh = _status_payload(status="ok", data={"captured_at": "2026-09-11T02:05:00Z"})
    fresh["freshness"].update({"captured_at": fresh["data"]["captured_at"], "age_seconds": 0})

    def fetcher(endpoint, params):
        calls.append((endpoint, params))
        if len(calls) == 1:
            raise HardwareMonitorUpstreamError("synthetic disconnect")
        return (503, stale) if len(calls) == 2 else (200, fresh)

    app = FastAPI()
    app.include_router(create_hardware_monitor_proxy_router(fetcher=fetcher))
    prefix = "/admin/dashboard/scout-monitor/api/v1/hardware-monitor"
    with TestClient(app) as client:
        first, second, third = (client.get(prefix + "/status") for _ in range(3))
        assert first.status_code == 503 and first.json()["status"] == "unavailable"
        assert first.json()["data"] is None and first.json()["read_only"] is True
        assert second.status_code == 503 and second.json() == stale
        assert third.status_code == 200 and third.json() == fresh
        assert all(item.headers["cache-control"] == "no-store" for item in (first, second, third))
        assert client.post(prefix + "/status").status_code == 405
        assert client.get(prefix + "/history?limit=0").status_code == 422
        assert client.get(prefix + "/events?limit=201").status_code == 422
    assert calls == [("/api/v1/hardware-monitor/status", {})] * 3
