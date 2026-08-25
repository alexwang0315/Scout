from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient

from admin_api import create_admin_app
from dashboard_connected_preparation import (
    CONNECTED_DASHBOARD_LAYERS,
    DashboardConnectedPreparationManager,
)
from dashboard_workspace_publication import WorkspacePreparationBusyError
from scout_env import ScoutEnvLoadResult


def _write_project(workspace_root: Path, project_id: str = "fixture-route") -> Path:
    project_root = workspace_root / project_id
    project_root.mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps({"project_id": project_id}),
        encoding="utf-8",
    )
    return project_root


class _ImmediateThread:
    def __init__(self, *, target: Callable[[], None], **_: Any) -> None:
        self._target = target

    def start(self) -> None:
        self._target()


class _DeferredThread:
    def __init__(self, *, target: Callable[[], None], **_: Any) -> None:
        self._target = target

    def start(self) -> None:
        pass


class _RecordedTimer:
    created: list["_RecordedTimer"] = []

    def __init__(self, interval: float, function: Callable[[], None]) -> None:
        self.interval = interval
        self.function = function
        self.daemon = False
        self.started = False
        self.cancelled = False
        self.__class__.created.append(self)

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancelled = True


def test_connected_preparation_uses_mac_explicit_fetch_and_redacts_credentials(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    workspace_root = tmp_path / "workspaces"
    cache_root = (
        workspace_root / "fixture-route" / "cache" / "cwa-weather-imagery"
    )
    repo_root.mkdir()
    _write_project(workspace_root)
    (repo_root / ".env").write_text(
        "CWA_API_KEY=do-not-expose-this-value\n",
        encoding="utf-8",
    )
    environ: dict[str, str] = {}
    requests: list[Any] = []

    def fake_runner(request: Any) -> dict[str, Any]:
        requests.append(request)
        assert environ["CWA_API_KEY"] == "do-not-expose-this-value"
        assert environ["SCOUT_CWA_SERVER_IMAGERY_CAPABLE"] == "1"
        assert "SCOUT_CWA_IMAGERY_CACHE_ROOT" not in environ
        runner_root = (
            Path(request.project_root)
            if request.project_root is not None
            else Path(request.workspace_root) / request.project_id
        ).resolve()
        evidence_ref = "outputs/environment/cwa/cwa_weather_evidence.json"
        evidence_path = runner_root / evidence_ref
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(
            json.dumps({"status": "ready"}),
            encoding="utf-8",
        )
        project_path = runner_root / "project.json"
        project = json.loads(project_path.read_text(encoding="utf-8"))
        project["cwa_weather_evidence_ref"] = evidence_ref
        project_path.write_text(json.dumps(project), encoding="utf-8")
        return {
            "network_policy": {"network_calls_made": True},
            "boundary": {"external_api_calls_made": True},
        }

    manager = DashboardConnectedPreparationManager(
        repo_root=repo_root,
        workspace_root=workspace_root,
        environ=environ,
        runner=fake_runner,
        now_factory=lambda: datetime(2026, 7, 23, 3, 0, tzinfo=timezone.utc),
    )

    status = manager.run_once("fixture-route", reason="test")

    assert len(requests) == 1
    request = requests[0]
    assert request.profile == "mac-workstation"
    assert request.network_mode == "explicit-fetch"
    assert request.allow_network_fetch is True
    assert request.prepare_cwa_imagery is True
    assert request.run_post_layer_enrichments is False
    assert request.run_map_preparation_spec_artifacts is False
    assert request.publish_preparation_outputs is False
    assert request.layers == CONNECTED_DASHBOARD_LAYERS
    assert set(request.layers) == {
        "overpass",
        "cwa-qpf",
        "cwa-weather",
        "weather",
        "soil-moisture",
        "antecedent-rain",
    }
    assert status["status"] == "ready"
    assert status["statusReadSchedulesRefresh"] is False
    assert status["writerProvenance"] == {
        "processId": os.getpid(),
        "threadName": "MainThread",
        "reason": "test",
        "triggerKind": "internal",
        "startedAt": "2026-07-23T03:00:00+00:00",
        "completedAt": "2026-07-23T03:00:00+00:00",
    }
    assert status["cwaApiRequestAttempted"] is True
    assert status["externalApiCallsMade"] is True
    assert status["credentialNamesPresent"] == ["CWA_API_KEY"]
    assert status["credentialValuesExposed"] is False
    assert "do-not-expose-this-value" not in json.dumps(status)
    assert status["profile"] == "mac-workstation"
    assert status["networkMode"] == "explicit-fetch"
    assert status["allowNetworkFetch"] is True
    assert status["prepareCwaImagery"] is True
    assert status["serverImageryCapable"] is True
    assert status["cacheScope"] == "project_workspace"
    assert status["workspaceCacheRoot"] == str(cache_root)
    assert cache_root.is_dir()
    assert status["componentStatuses"]["cwaWeather"] == "ready"
    assert status["crossProcessLocking"] is True
    assert status["recoveryJournalStatus"] == "clear"


def test_connected_preparation_trigger_is_single_flight_and_schedules_refresh(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    workspace_root = tmp_path / "workspaces"
    _write_project(workspace_root)
    _RecordedTimer.created.clear()
    call_count = 0

    def fake_runner(_: Any) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        return {
            "network_policy": {"network_calls_made": True},
            "boundary": {"external_api_calls_made": True},
        }

    manager = DashboardConnectedPreparationManager(
        repo_root=repo_root,
        workspace_root=workspace_root,
        environ={"CWA_API_KEY": "present"},
        runner=fake_runner,
        refresh_interval_seconds=600,
        thread_factory=_ImmediateThread,
        timer_factory=_RecordedTimer,
        now_factory=lambda: datetime(2026, 7, 23, 3, 0, tzinfo=timezone.utc),
    )

    first = manager.trigger("fixture-route", reason="dashboard-open")
    second = manager.trigger("fixture-route", reason="dashboard-open")

    assert call_count == 1
    assert first["status"] == "ready"
    assert second["status"] == "ready"
    assert second["recurring"] is True
    assert second["refreshIntervalSeconds"] == 600
    assert len(_RecordedTimer.created) == 1
    assert _RecordedTimer.created[0].interval == 600
    assert _RecordedTimer.created[0].started is True


def test_connected_preparation_can_schedule_without_immediate_provider_fetch(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    workspace_root = tmp_path / "workspaces"
    _write_project(workspace_root)
    _RecordedTimer.created.clear()
    call_count = 0

    def fake_runner(_: Any) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        return {
            "network_policy": {"network_calls_made": True},
            "boundary": {"external_api_calls_made": True},
        }

    manager = DashboardConnectedPreparationManager(
        repo_root=repo_root,
        workspace_root=workspace_root,
        environ={"CWA_API_KEY": "present"},
        runner=fake_runner,
        refresh_interval_seconds=600,
        thread_factory=_ImmediateThread,
        timer_factory=_RecordedTimer,
        now_factory=lambda: datetime(2026, 7, 23, 3, 0, tzinfo=timezone.utc),
    )

    first = manager.ensure_scheduled("fixture-route")
    second = manager.ensure_scheduled("fixture-route")

    assert call_count == 0
    assert first["status"] == "idle"
    assert first["requestActivityState"] == "not-started"
    assert first["crossProcessLocking"] is True
    assert first["recoveryJournalStatus"] == "clear"
    assert first["nextRunAt"] == "2026-07-23T03:10:00+00:00"
    assert second == first
    assert len(_RecordedTimer.created) == 1
    assert _RecordedTimer.created[0].started is True

    _RecordedTimer.created[0].function()

    assert call_count == 1
    assert manager.snapshot("fixture-route")["status"] == "ready"
    assert len(_RecordedTimer.created) == 2
    assert _RecordedTimer.created[1].started is True


def test_connected_preparation_keeps_live_workspace_stable_until_runner_finishes(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    workspace_root = tmp_path / "workspaces"
    project_root = _write_project(workspace_root)
    project_path = project_root / "project.json"
    project_path.write_text(
        json.dumps({"project_id": "fixture-route", "generation": "old"}),
        encoding="utf-8",
    )
    runner_started = threading.Event()
    release_runner = threading.Event()
    observed_runner_roots: list[Path] = []
    results: list[dict[str, Any]] = []

    def fake_runner(request: Any) -> dict[str, Any]:
        runner_root = (
            Path(request.project_root)
            if request.project_root is not None
            else Path(request.workspace_root) / request.project_id
        ).resolve()
        observed_runner_roots.append(runner_root)
        staged_project = json.loads(
            (runner_root / "project.json").read_text(encoding="utf-8")
        )
        (runner_root / "project.json").write_text(
            json.dumps({**staged_project, "generation": "new"}),
            encoding="utf-8",
        )
        runner_started.set()
        assert release_runner.wait(timeout=5)
        return {
            "network_policy": {"network_calls_made": True},
            "boundary": {"external_api_calls_made": True},
        }

    manager = DashboardConnectedPreparationManager(
        repo_root=repo_root,
        workspace_root=workspace_root,
        environ={},
        runner=fake_runner,
    )
    worker = threading.Thread(
        target=lambda: results.append(
            manager.run_once("fixture-route", reason="test-atomic-publication")
        )
    )

    worker.start()
    assert runner_started.wait(timeout=5)
    try:
        live_project = json.loads(project_path.read_text(encoding="utf-8"))
        assert live_project["generation"] == "old"
        assert (
            project_root / "cache" / "cwa-weather-imagery"
        ).exists() is False
        assert observed_runner_roots
        assert observed_runner_roots[0] != project_root.resolve()
    finally:
        release_runner.set()
        worker.join(timeout=5)

    assert worker.is_alive() is False
    published_project = json.loads(project_path.read_text(encoding="utf-8"))
    assert published_project["generation"] == "new"
    assert results[0]["publicationMode"] == "staged-atomic-swap"


def test_connected_preparation_discards_invalid_generation_without_publishing(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    workspace_root = tmp_path / "workspaces"
    project_root = _write_project(workspace_root)
    project_path = project_root / "project.json"
    project_path.write_text(
        json.dumps({"project_id": "fixture-route", "generation": "old"}),
        encoding="utf-8",
    )

    def fake_runner(request: Any) -> dict[str, Any]:
        runner_root = Path(request.project_root).resolve()
        (runner_root / "project.json").write_text(
            json.dumps({"project_id": "wrong-route", "generation": "invalid"}),
            encoding="utf-8",
        )
        return {
            "network_policy": {"network_calls_made": True},
            "boundary": {"external_api_calls_made": True},
        }

    manager = DashboardConnectedPreparationManager(
        repo_root=repo_root,
        workspace_root=workspace_root,
        environ={},
        runner=fake_runner,
    )

    status = manager.run_once("fixture-route", reason="test-invalid-generation")

    live_project = json.loads(project_path.read_text(encoding="utf-8"))
    assert live_project == {
        "project_id": "fixture-route",
        "generation": "old",
    }
    assert status["status"] == "failed"
    assert status["publicationStatus"] == "not-published"
    staging_root = workspace_root / ".scout-connected-preparation" / "staging"
    assert not staging_root.exists() or not any(staging_root.iterdir())


def test_connected_preparation_rejects_invalid_runner_receipt_before_publish(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    workspace_root = tmp_path / "workspaces"
    project_root = _write_project(workspace_root)
    project_path = project_root / "project.json"
    project_path.write_text(
        json.dumps({"project_id": "fixture-route", "generation": "old"}),
        encoding="utf-8",
    )

    def fake_runner(request: Any) -> Any:
        runner_root = Path(request.project_root).resolve()
        (runner_root / "project.json").write_text(
            json.dumps({"project_id": "fixture-route", "generation": "new"}),
            encoding="utf-8",
        )
        return None

    manager = DashboardConnectedPreparationManager(
        repo_root=repo_root,
        workspace_root=workspace_root,
        environ={},
        runner=fake_runner,
    )

    status = manager.run_once("fixture-route", reason="test-invalid-receipt")

    assert json.loads(project_path.read_text(encoding="utf-8"))["generation"] == "old"
    assert status["status"] == "failed"
    assert status["publicationStatus"] == "not-published"


class _BusyWorkspacePublication:
    def stage(self, _: str) -> None:
        raise WorkspacePreparationBusyError(
            "connected preparation is active in another process"
        )

    def recovery_status(self, _: str) -> dict[str, str]:
        return {
            "status": "active-other-process",
            "journalStatus": "active-external",
        }


def test_connected_preparation_reports_external_process_as_busy(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    workspace_root = tmp_path / "workspaces"
    _write_project(workspace_root)
    manager = DashboardConnectedPreparationManager(
        repo_root=repo_root,
        workspace_root=workspace_root,
        environ={},
        runner=lambda _: pytest.fail("busy preparation must not run"),
        workspace_publication=_BusyWorkspacePublication(),  # type: ignore[arg-type]
    )

    status = manager.run_once("fixture-route", reason="test-cross-process-busy")

    assert status["status"] == "busy"
    assert status["requestActivityState"] == "waiting-external-preparation"
    assert status["externalPreparationActive"] is True
    assert status["publicationStatus"] == "not-published"
    assert status["startupRecovery"] == "active-other-process"
    assert status["recoveryJournalStatus"] == "active-external"


class _PreviouslyBusyWorkspacePublication:
    def recovery_status(self, _: str) -> dict[str, str]:
        return {
            "status": "active-other-process",
            "journalStatus": "clear",
        }


def test_connected_preparation_does_not_report_stale_external_activity(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    workspace_root = tmp_path / "workspaces"
    _write_project(workspace_root)
    manager = DashboardConnectedPreparationManager(
        repo_root=repo_root,
        workspace_root=workspace_root,
        environ={},
        runner=lambda _: pytest.fail("status read must not prepare"),
        workspace_publication=_PreviouslyBusyWorkspacePublication(),  # type: ignore[arg-type]
    )

    status = manager.snapshot("fixture-route")

    assert status["startupRecovery"] == "active-other-process"
    assert status["recoveryJournalStatus"] == "clear"
    assert status["externalPreparationActive"] is False


def test_connected_preparation_refresh_for_assistant_completes_before_return(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    workspace_root = tmp_path / "workspaces"
    _write_project(workspace_root)
    _RecordedTimer.created.clear()
    call_count = 0

    def fake_runner(_: Any) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        return {
            "network_policy": {"network_calls_made": True},
            "boundary": {"external_api_calls_made": True},
        }

    manager = DashboardConnectedPreparationManager(
        repo_root=repo_root,
        workspace_root=workspace_root,
        environ={"CWA_API_KEY": "present"},
        runner=fake_runner,
        timer_factory=_RecordedTimer,
        now_factory=lambda: datetime(2026, 7, 23, 3, 0, tzinfo=timezone.utc),
    )

    status = manager.refresh_for_assistant(
        "fixture-route",
        reason="scout-ai-weather-decision",
    )

    assert call_count == 1
    assert status["status"] == "ready"
    assert status["requestActivityState"] == "complete"
    assert status["reason"] == "scout-ai-weather-decision"
    assert status["runCount"] == 1
    assert status["nextRunAt"] == "2026-07-23T03:10:00+00:00"
    assert len(_RecordedTimer.created) == 1
    assert _RecordedTimer.created[0].started is True


def test_connected_preparation_reports_in_progress_without_false_call_results(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    workspace_root = tmp_path / "workspaces"
    _write_project(workspace_root)
    manager = DashboardConnectedPreparationManager(
        repo_root=repo_root,
        workspace_root=workspace_root,
        environ={"CWA_API_KEY": "present"},
        runner=lambda _: pytest.fail("deferred worker must not run"),
        thread_factory=_DeferredThread,
    )

    status = manager.trigger("fixture-route", reason="dashboard-open")

    assert status["status"] == "queued"
    assert status["requestActivityState"] == "in-progress"
    assert status["cwaApiRequestAttempted"] is None
    assert status["externalApiCallsMade"] is None
    assert status["networkCallsMade"] is None


def test_connected_preparation_keeps_startup_env_source_provenance(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    env_path = repo_root / ".env"
    env_path.write_text("CWA_API_KEY=already-loaded\n", encoding="utf-8")
    workspace_root = tmp_path / "workspaces"
    _write_project(workspace_root)
    manager = DashboardConnectedPreparationManager(
        repo_root=repo_root,
        workspace_root=workspace_root,
        environ={"CWA_API_KEY": "already-loaded"},
        initial_env_load_result=ScoutEnvLoadResult(
            loaded_files=(str(env_path),),
            loaded_keys=("CWA_API_KEY",),
        ),
        runner=lambda _: {
            "network_policy": {"network_calls_made": True},
            "boundary": {"external_api_calls_made": True},
        },
    )

    status = manager.run_once("fixture-route")

    assert status["envFilesLoaded"] == [str(env_path)]
    assert status["credentialNamesPresent"] == ["CWA_API_KEY"]
    assert status["credentialValuesExposed"] is False


def test_connected_preparation_keeps_each_project_cache_inside_its_workspace(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    workspace_root = tmp_path / "workspaces"
    _write_project(workspace_root)
    _write_project(workspace_root, "other-route")
    global_cache = tmp_path / "global-cache"
    environ = {"SCOUT_CWA_IMAGERY_CACHE_ROOT": str(global_cache)}
    manager = DashboardConnectedPreparationManager(
        repo_root=repo_root,
        workspace_root=workspace_root,
        environ=environ,
        runner=lambda _: {
            "network_policy": {"network_calls_made": False},
            "boundary": {"external_api_calls_made": False},
        },
    )

    first = manager.run_once("fixture-route")
    second = manager.run_once("other-route")

    first_cache = Path(first["workspaceCacheRoot"])
    second_cache = Path(second["workspaceCacheRoot"])
    assert first_cache == (
        workspace_root / "fixture-route" / "cache" / "cwa-weather-imagery"
    ).resolve()
    assert second_cache == (
        workspace_root / "other-route" / "cache" / "cwa-weather-imagery"
    ).resolve()
    assert first_cache != second_cache
    assert first_cache.is_dir()
    assert second_cache.is_dir()
    assert not global_cache.exists()
    assert environ["SCOUT_CWA_IMAGERY_CACHE_ROOT"] == str(global_cache)


def test_connected_preparation_does_not_read_artifacts_from_another_project(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    workspace_root = tmp_path / "workspaces"
    project_root = _write_project(workspace_root)
    other_root = _write_project(workspace_root, "other-route")
    (other_root / "weather.json").write_text(
        json.dumps({"status": "ready"}),
        encoding="utf-8",
    )
    project_path = project_root / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project["cwa_weather_evidence_ref"] = "../other-route/weather.json"
    project_path.write_text(json.dumps(project), encoding="utf-8")
    manager = DashboardConnectedPreparationManager(
        repo_root=repo_root,
        workspace_root=workspace_root,
        environ={},
        runner=lambda _: {
            "network_policy": {"network_calls_made": False},
            "boundary": {"external_api_calls_made": False},
        },
    )

    status = manager.run_once("fixture-route")

    assert status["componentStatuses"]["cwaWeather"] is None


class _FakeConnectedPreparationManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, bool]] = []
        self.schedule_calls: list[str] = []
        self.workspace_publication = _RecordingWorkspacePublication()

    def trigger(
        self,
        project_id: str,
        *,
        reason: str,
        force: bool = False,
    ) -> dict[str, Any]:
        self.calls.append((project_id, reason, force))
        return {
            "schemaVersion": "dashboardConnectedPreparation.v1",
            "projectId": project_id,
            "status": "queued",
            "profile": "mac-workstation",
            "networkMode": "explicit-fetch",
            "allowNetworkFetch": True,
            "prepareCwaImagery": True,
            "recurring": True,
        }

    def snapshot(self, project_id: str) -> dict[str, Any]:
        return {
            "schemaVersion": "dashboardConnectedPreparation.v1",
            "projectId": project_id,
            "status": "running",
            "profile": "mac-workstation",
            "networkMode": "explicit-fetch",
            "allowNetworkFetch": True,
            "prepareCwaImagery": True,
            "recurring": True,
            "nextRunAt": None,
        }

    def ensure_scheduled(self, project_id: str) -> dict[str, Any]:
        self.schedule_calls.append(project_id)
        return {
            **self.snapshot(project_id),
            "status": "idle",
            "nextRunAt": "2026-07-23T03:10:00+00:00",
        }


class _RecordingWorkspacePublication:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def acquire_read(self, project_id: str) -> None:
        self.events.append(("acquire", project_id))

    def release_read(self, project_id: str) -> None:
        self.events.append(("release", project_id))


def test_admin_connected_preparation_api_triggers_background_job(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspaces"
    _write_project(workspace_root)
    manager = _FakeConnectedPreparationManager()
    client = TestClient(
        create_admin_app(
            pretrip_workspace_root=workspace_root,
            connected_preparation_manager=manager,
        )
    )

    response = client.post(
        "/admin/pretrip/projects/fixture-route/connected-preparation",
        json={"force": False},
    )
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert manager.calls == [("fixture-route", "operator-refresh", False)]


def test_admin_connected_preparation_status_is_read_only_and_does_not_schedule(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspaces"
    _write_project(workspace_root)
    manager = _FakeConnectedPreparationManager()
    client = TestClient(
        create_admin_app(
            pretrip_workspace_root=workspace_root,
            connected_preparation_manager=manager,
        )
    )

    status_response = client.get(
        "/admin/pretrip/projects/fixture-route/connected-preparation"
    )

    assert status_response.status_code == 200
    assert status_response.json()["status"] == "running"
    assert status_response.json()["nextRunAt"] is None
    assert manager.schedule_calls == []
    assert manager.calls == []
    assert manager.workspace_publication.events == [
        ("acquire", "fixture-route"),
        ("release", "fixture-route"),
    ]
