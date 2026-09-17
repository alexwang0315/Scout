from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import admin_api
from qgis_runtime_control import QgisRuntimeControlCode as Code, QgisRuntimeControlResult


class FakeController:
    def __init__(self) -> None:
        self.starts: list[str] = []

    def snapshot(self, *, project_id):
        return QgisRuntimeControlResult(project_id=project_id, status="idle", code=Code.IDLE, can_start=True)

    def ensure_ready(self, *, project_id):
        self.starts.append(project_id)
        return QgisRuntimeControlResult(project_id=project_id, status="ready", code=Code.READY, can_start=True)


@pytest.fixture
def runtime_api(tmp_path, monkeypatch):
    monkeypatch.setattr(admin_api, "load_scout_env_files", lambda **kw: None)
    monkeypatch.setenv("SCOUT_QGIS_ENABLED", "false")
    monkeypatch.setenv("SCOUT_QGIS_FIXTURE_MODE", "false")
    monkeypatch.setenv("SCOUT_ALPHA_SANDBOX_ENABLED", "false")
    root = tmp_path / "workspaces"
    project = root / "demo"
    project.mkdir(parents=True)
    (project / "project.json").write_text(json.dumps({"project_id": "demo"}))
    controller = FakeController()

    def app_factory(managed=True):
        app = FastAPI()
        app.include_router(admin_api.create_admin_router(
            pretrip_workspace_root=root,
            qgis_runtime_controller=controller if managed else None,
            terrain_guidance_elevation_sampler=None,
        ))
        return app

    return controller, app_factory, project


BASE = "/admin/pretrip/projects/demo/spatial/qgis/runtime"
ORIGIN = {"Origin": "http://127.0.0.1"}


def _client(app, *, host="127.0.0.1", base_url="http://127.0.0.1"):
    return TestClient(app, base_url=base_url, client=(host, 50100))


def test_get_is_read_only_and_start_is_explicit_candidate_only(runtime_api) -> None:
    controller, factory, project = runtime_api
    before = (project / "project.json").read_bytes()
    with _client(factory()) as client:
        response = client.get(BASE)
        assert response.status_code == 200
        assert response.json()["can_start"] is True
        assert controller.starts == []
        response = client.post(BASE + "/ensure-ready", json={"action": "ensure_ready"}, headers=ORIGIN)
    assert response.status_code == 200
    assert controller.starts == ["demo"]
    assert response.json()["authority"] == "candidate_only"
    assert response.json()["runtime_safety_truth"] is False
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-scout-candidate-only"] == "true"
    assert (project / "project.json").read_bytes() == before
    assert list(project.iterdir()) == [project / "project.json"]


@pytest.mark.parametrize("peer,base_url,headers", (
    ("192.168.1.20", "http://127.0.0.1", ORIGIN),
    ("127.0.0.1", "http://127.0.0.1", {}),
    ("127.0.0.1", "http://127.0.0.1", {"Origin": "null"}),
    ("127.0.0.1", "http://127.0.0.1", {"Origin": "https://external.invalid"}),
    ("127.0.0.1", "http://rebind.invalid", {"Origin": "http://rebind.invalid"}),
    ("127.0.0.1", "http://127.0.0.1", {**ORIGIN, "Sec-Fetch-Site": "cross-site"}),
))
def test_start_rejects_remote_cross_origin_and_dns_rebinding(runtime_api, peer, base_url, headers) -> None:
    controller, factory, _ = runtime_api
    with _client(factory(), host=peer, base_url=base_url) as client:
        response = client.post(BASE + "/ensure-ready", json={}, headers=headers)
    assert response.status_code == 403
    assert controller.starts == []


@pytest.mark.parametrize("payload", ({"command": "restart"}, {"worker_url": "http://host"}, {"action": "restart"}, {"runtime_safety_truth": True}))
def test_start_body_cannot_escape_typed_allowlist(runtime_api, payload) -> None:
    controller, factory, _ = runtime_api
    with _client(factory()) as client:
        response = client.post(BASE + "/ensure-ready", json=payload, headers=ORIGIN)
    assert response.status_code == 422
    assert controller.starts == []


def test_regular_admin_app_does_not_gain_host_launch_authority(runtime_api) -> None:
    controller, factory, _ = runtime_api
    with _client(factory(managed=False)) as client:
        assert client.get(BASE).json()["can_start"] is False
        response = client.post(BASE + "/ensure-ready", json={}, headers=ORIGIN)
    assert response.json()["code"] == "NOT_MANAGED"
    assert controller.starts == []


def test_start_requires_real_existing_workspace(runtime_api) -> None:
    controller, factory, _ = runtime_api
    with _client(factory()) as client:
        response = client.post(BASE.replace("/demo/", "/missing/") + "/ensure-ready", json={}, headers=ORIGIN)
    assert response.status_code == 404
    assert controller.starts == []
