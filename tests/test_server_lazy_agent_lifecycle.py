from __future__ import annotations

import asyncio
import builtins
import importlib.util
import sys
from contextlib import suppress
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient


@pytest.fixture
def isolated_server(tmp_path, monkeypatch):
    """Exercise the real server while forbidding cloud or hardware startup."""
    import scout_env

    for name in (
        "SCOUT_SAFETY_ENABLED",
        "SCOUT_AI_ASSISTANT_ENABLED",
        "SCOUT_PHASE2_ADMIN_API_ENABLED",
        "SCOUT_DEBUG_API_ENABLED",
        "SCOUT_RUNTIME_STREAM_STATUS_ENABLED",
        "SCOUT_RUNTIME_STREAM_TRANSPORT_ENABLED",
        "SCOUT_SAFETY_OBSERVATION_ADMISSION_ENABLED",
    ):
        monkeypatch.setenv(name, "false")
    monkeypatch.setenv("SCOUT_DATA_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("SCOUT_SAFETY_INCIDENT_STORE", str(tmp_path / "incidents"))
    monkeypatch.setenv("SCOUT_PRETRIP_WORKSPACE_ROOT", str(tmp_path / "workspaces"))
    monkeypatch.setenv("SCOUT_PERSISTENT_ENV_FILE", str(tmp_path / "absent.env"))
    monkeypatch.setattr(scout_env, "load_scout_env_files", lambda **kwargs: None)

    source = Path(__file__).resolve().parents[1] / "server.py"
    spec = importlib.util.spec_from_file_location("_scout_lazy_agent_server", source)
    assert spec and spec.loader
    server = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, server)
    real_import = builtins.__import__

    def forbid_eager_agent(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "agent" and level == 0:
            raise AssertionError("Wi-Fi agent must not initialize during API import")
        return real_import(name, globals, locals, fromlist, level)

    try:
        with patch("builtins.__import__", side_effect=forbid_eager_agent):
            spec.loader.exec_module(server)
        server.world.scan_all = Mock(side_effect=AssertionError("no hardware in test"))
        server.pdr_event_queue = asyncio.Queue()
        yield server
    finally:
        if hasattr(server, "executor"):
            server.executor.shutdown(wait=True, cancel_futures=True)


def install_agent(monkeypatch, *, side_effect=None, output="fixture decision"):
    agent = ModuleType("agent")
    agent.sos_agent = SimpleNamespace(
        run=AsyncMock(side_effect=side_effect, return_value=SimpleNamespace(output=output))
    )
    monkeypatch.setitem(sys.modules, "agent", agent)
    return agent.sos_agent.run


def test_unrelated_api_boots_without_initializing_wifi_agent(isolated_server):
    with TestClient(isolated_server.app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "S.C.O.U.T. Fusion Online"
    isolated_server.world.scan_all.assert_not_called()


@pytest.mark.parametrize("preloaded", [False, True])
def test_navigation_initializes_agent_only_when_requested(
    isolated_server, monkeypatch, preloaded
):
    server = isolated_server
    run = install_agent(monkeypatch)
    server.world.get_full_snapshot = Mock(return_value={"fixture": -55.0})
    server.world.get_best_signal = Mock(return_value={"ssid": "fixture", "rssi": -55.0})
    if preloaded:
        server.world.trajectory = [{"x": 1, "y": 2, "signals": {"fixture": -55.0}}]
    result = asyncio.run(server.get_navigation())
    assert result == {
        "instruction": "fixture decision",
        "best_signal": {"ssid": "fixture", "rssi": -55.0},
    }
    run.assert_awaited_once()
    assert run.await_args.kwargs == {"deps": server.world, "model_settings": {"max_tokens": 256}}
    assert server.world.get_full_snapshot.call_count == (0 if preloaded else 1)
    assert server.last_instruction == "fixture decision"
    server.world.scan_all.assert_not_called()


def test_navigation_reports_agent_failure_without_replacing_instruction(
    isolated_server, monkeypatch
):
    server = isolated_server
    server.world.trajectory = [{"x": 1, "y": 2}]
    server.last_instruction = "previous decision"
    run = install_agent(monkeypatch, side_effect=RuntimeError("fixture model unavailable"))
    with pytest.raises(HTTPException) as caught:
        asyncio.run(server.get_navigation())
    assert caught.value.status_code == 500
    assert caught.value.detail == "fixture model unavailable"
    assert server.last_instruction == "previous decision"
    run.assert_awaited_once()
    server.world.scan_all.assert_not_called()


def test_navigation_reports_missing_agent_dependency_at_use_time(isolated_server):
    server = isolated_server
    server.world.trajectory = [{"x": 1, "y": 2}]
    previous = server.last_instruction
    real_import = builtins.__import__

    def missing_agent(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "agent" and level == 0:
            raise ModuleNotFoundError("fixture agent dependency unavailable")
        return real_import(name, globals, locals, fromlist, level)

    with patch("builtins.__import__", side_effect=missing_agent):
        with pytest.raises(HTTPException) as caught:
            asyncio.run(server.get_navigation())
    assert caught.value.status_code == 500
    assert caught.value.detail == "fixture agent dependency unavailable"
    assert server.last_instruction == previous
    server.world.scan_all.assert_not_called()


def test_idle_worker_does_not_initialize_agent(isolated_server):
    server = isolated_server
    real_import = builtins.__import__

    def forbid_agent(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "agent" and level == 0:
            raise AssertionError("idle worker must not initialize agent")
        return real_import(name, globals, locals, fromlist, level)

    async def exercise():
        server.pdr_event_queue = asyncio.Queue()
        task = asyncio.create_task(server.ai_decision_worker())
        await asyncio.sleep(0)
        assert not task.done()
        assert server.world.trajectory == []
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    with patch("builtins.__import__", side_effect=forbid_agent):
        asyncio.run(exercise())


def test_worker_recovers_after_agent_failure_and_acknowledges_each_event(
    isolated_server, monkeypatch
):
    server = isolated_server
    run = install_agent(
        monkeypatch,
        side_effect=[RuntimeError("fixture unavailable"), SimpleNamespace(output="recovered")],
    )

    async def exercise():
        server.pdr_event_queue = asyncio.Queue()
        for x in (1, 2):
            server.pdr_event_queue.put_nowait({"pose": {"x": x, "y": 0}, "signals": {}})
        task = asyncio.create_task(server.ai_decision_worker())
        try:
            await asyncio.wait_for(server.pdr_event_queue.join(), timeout=5)
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    asyncio.run(exercise())
    assert run.await_count == 2
    assert [point["decision"] for point in server.world.trajectory] == [None, "recovered"]
    assert server.last_instruction == "recovered"
    server.world.scan_all.assert_not_called()
