"""Real app composition keeps assets unique, standalone defaults and guards."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import importlib
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from admin_api import create_admin_router
from debug_api import create_debug_app, create_debug_page_router
from hardware_readiness_api import create_hardware_readiness_app, create_hardware_readiness_router
from phase4_admin_runtime import create_phase4_admin_runtime_app
from fastapi_route_inventory import registered_route_methods, registered_routes

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = "/admin/scout-assistant-ui.js"
SCRIPT_SHA = hashlib.sha256((ROOT / "docs/admin/scout-assistant-ui.js").read_bytes()).hexdigest()


def _environment(tmp_path, enabled):
    return {"SCOUT_DEBUG_API_ENABLED": "true" if enabled else "false",
            "SCOUT_AI_ASSISTANT_ENABLED": "false", "SCOUT_AI_ASSISTANT_PROVIDER": "mock",
            "SCOUT_SAFETY_ENABLED": "false", "SCOUT_RUNTIME_STREAM_TRANSPORT_ENABLED": "false",
            "SCOUT_SAFETY_OBSERVATION_ADMISSION_ENABLED": "false",
            "SCOUT_INGRESS_OBSERVER_SUPERVISOR_ENABLED": "false",
            "SCOUT_DATA_ROOT": str(tmp_path), "SCOUT_PRETRIP_WORKSPACE_ROOT": str(tmp_path / "workspaces"),
            "SCOUT_SAFETY_INCIDENT_STORE": str(tmp_path / "incidents")}


@contextmanager
def _composed(entrypoint, tmp_path, enabled):
    environ = _environment(tmp_path, enabled)
    if entrypoint == "phase4":
        yield create_phase4_admin_runtime_app(environ=environ)
        return
    import server
    try:
        with patch.dict(os.environ, environ, clear=False):
            yield importlib.reload(server).app
    finally:
        importlib.reload(server)


@contextmanager
def _http(app):
    # Exercise ASGI routing without starting the field server's AI worker.
    client = TestClient(app)
    try:
        yield client
    finally:
        client.close()


def _script_receipt(client):
    response = client.get(SCRIPT_PATH)
    assert response.status_code == 200
    assert hashlib.sha256(response.content).hexdigest() == SCRIPT_SHA
    assert client.post(SCRIPT_PATH).status_code == 405
    return {"http_status": response.status_code, "sha256": SCRIPT_SHA}


@pytest.mark.parametrize("entrypoint", ["server", "phase4"])
@pytest.mark.parametrize("enabled", [False, True])
def test_composed_apps_have_one_script_and_a_consistent_debug_gate(tmp_path, entrypoint, enabled):
    with _composed(entrypoint, tmp_path, enabled) as app:
        inventory = registered_routes(app)
        assert sum(row.path == SCRIPT_PATH for row in inventory) == 1
        assert sum(row.path == "/admin/debug" for row in inventory) == int(enabled)
        with _http(app) as client:
            script = _script_receipt(client)
            page = client.get("/admin/debug")
            state = client.get("/debug/state")
            assert page.status_code == state.status_code == (200 if enabled else 404)
            if enabled:
                assert "Scout Phase 3.5 Runtime Debug" in page.text
                assert state.json()["debug_boundary"]["read_only"] is True
                assert client.post("/admin/debug").status_code == 405
            if entrypoint == "phase4":
                health = client.get("/health").json()
                assert health["routes"]["debug_admin"] == ("/admin/debug" if enabled else None)
                assert health["boundaries"]["debug_api_enabled"] is enabled
            receipt = {"entrypoint": entrypoint, "debug_enabled": enabled, "script": script,
                       "debug_page_status": page.status_code, "debug_state_status": state.status_code,
                       "routes": [{"path": r.path, "methods": sorted(r.methods), "kind": r.kind} for r in inventory]}
            (tmp_path / "composition-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


@pytest.mark.parametrize("kind", ["admin", "debug", "hardware"])
def test_standalone_defaults_keep_pages_and_exact_shared_script(kind):
    if kind == "admin":
        app = FastAPI(); app.include_router(create_admin_router())
        page = "/admin/debug"
    elif kind == "debug":
        app, page = create_debug_app(), "/admin/debug"
    else:
        app, page = create_hardware_readiness_app(), "/admin/hardware-readiness"
    assert sum(row.path == SCRIPT_PATH for row in registered_routes(app)) == 1
    with _http(app) as client:
        assert client.get(page).status_code == 200
        _script_receipt(client)


@pytest.mark.parametrize("kind", ["debug", "hardware"])
@pytest.mark.parametrize("include_script", [False, True])
def test_factory_script_opt_out_does_not_change_its_page(tmp_path, kind, include_script):
    path = tmp_path / "custom-ui.js"
    content = b"window.fixtureAsset = true;\n"
    if include_script:
        path.write_bytes(content)
    factory = create_debug_page_router if kind == "debug" else create_hardware_readiness_router
    app = FastAPI()
    app.include_router(factory(assistant_ui_script_path=path, include_assistant_ui_script=include_script))
    inventory = registered_route_methods(app, prefix="/admin")
    assert (SCRIPT_PATH in inventory) is include_script
    with _http(app) as client:
        page = "/admin/debug" if kind == "debug" else "/admin/hardware-readiness"
        assert client.get(page).status_code == 200
        script = client.get(SCRIPT_PATH)
        assert script.status_code == (200 if include_script else 404)
        if include_script:
            assert script.content == content


@pytest.mark.parametrize("enabled", [False, True])
def test_phase4_composition_keeps_admin_auth_for_script_and_debug_page(tmp_path, enabled):
    environ = {**_environment(tmp_path, enabled), "SCOUT_ADMIN_AUTH_REQUIRED": "true",
               "SCOUT_ADMIN_ACCESS_TOKEN": "fixture-admin-token"}
    app = create_phase4_admin_runtime_app(environ=environ)
    registered_routes(app)
    with _http(app) as client:
        assert client.get(SCRIPT_PATH).status_code == 401
        assert client.get("/admin/debug").status_code == 401
        headers = {"Authorization": "Bearer fixture-admin-token"}
        script = client.get(SCRIPT_PATH, headers=headers)
        assert script.status_code == 200 and hashlib.sha256(script.content).hexdigest() == SCRIPT_SHA
        assert client.get("/admin/debug", headers=headers).status_code == (200 if enabled else 404)
        assert client.get("/health").json()["auth"]["token_value_exposed"] is False
    environ.pop("SCOUT_ADMIN_ACCESS_TOKEN")
    app = create_phase4_admin_runtime_app(environ=environ)
    registered_routes(app)
    with _http(app) as client:
        assert client.get(SCRIPT_PATH).status_code == 503
        assert client.get("/admin/debug").status_code == 503


@pytest.mark.parametrize("entrypoint", ["dashboard_workspace", "admin_smoke"])
def test_tool_app_composition_preserves_smoke_debug_and_unique_assets(tmp_path, monkeypatch, entrypoint):
    import scout_env
    empty_env = scout_env.ScoutEnvLoadResult(loaded_files=(), loaded_keys=())
    with monkeypatch.context() as context:
        for key, value in _environment(tmp_path, True).items():
            context.setenv(key, value)
        if entrypoint == "dashboard_workspace":
            # Mock both bootstrap and refresh; never read an operator .env.
            original_loader = scout_env.load_scout_env_files
            with patch.object(scout_env, "load_scout_env_files", return_value=empty_env):
                module = importlib.import_module("tools.dashboard_workspace_app")
            try:
                module.load_scout_env_files = lambda **kwargs: empty_env
                app = module.create_dashboard_workspace_app(workspace_root=tmp_path / "workspaces")
            finally:
                module.load_scout_env_files = original_loader
        else:
            from tools.admin_ui_smoke_app import create_smoke_app
            app = create_smoke_app()
        try:
            inventory = registered_routes(app)
            assert sum(row.path == SCRIPT_PATH for row in inventory) == 1
            assert sum(row.path == "/admin/debug" for row in inventory) == 1
            if entrypoint == "dashboard_workspace":
                assert any(row.path.startswith("/admin/dashboard/scout-monitor") for row in inventory)
                assert app.state.connected_preparation_manager is not None
                assert app.state.qgis_runtime_controller is not None
            with _http(app) as client:
                script = _script_receipt(client)
                assert client.get("/admin/debug").status_code == 200
                assert client.get("/admin/hardware-readiness").status_code == 200
                assert client.get("/admin/dashboard").status_code == 200
                events = client.get("/debug/events").json()["events"]
                assert events and all(event["event_provenance"] == "smoke" for event in events)
                assert client.get("/debug/state").json()["debug_boundary"]["phase1_mutation_allowed"] is False
                receipt = {"entrypoint": entrypoint, "script": script, "event_provenance": "smoke",
                           "route_count": len(inventory), "script_route_count": 1, "debug_page_count": 1}
                (tmp_path / "tool-composition-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        finally:
            manager = getattr(app.state, "connected_preparation_manager", None)
            if manager is not None:
                manager.stop()
