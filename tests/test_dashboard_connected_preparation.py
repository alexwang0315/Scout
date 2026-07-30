from __future__ import annotations

import json
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
        evidence_ref = "outputs/environment/cwa/cwa_weather_evidence.json"
        evidence_path = workspace_root / "fixture-route" / evidence_ref
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(
            json.dumps({"status": "ready"}),
            encoding="utf-8",
        )
        project_path = workspace_root / "fixture-route" / "project.json"
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
        }


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
        json={"reason": "dashboard-open", "force": False},
    )
    status_response = client.get(
        "/admin/pretrip/projects/fixture-route/connected-preparation"
    )

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert manager.calls == [("fixture-route", "dashboard-open", False)]
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "running"
