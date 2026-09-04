from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from qgis_local_runtime import LocalQgisRuntimeHost, _NoRedirect
from qgis_runtime_control import QgisRuntimeControlCode as Code
from qgis_runtime_control import QgisRuntimeUnavailable
from qgis_spatial_backend import QgisSpatialBackendConfig


@pytest.fixture
def host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalQgisRuntimeHost:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    profile = home / ".scout-fusion/qgis-desktop"
    token_file = profile / "runtime/worker-token"
    token_file.parent.mkdir(parents=True)
    token_file.write_text("fixture-token-not-a-credential-1234567890", encoding="utf-8")
    (profile / "profiles/scout/python/plugins/qgis_agent_mcp/_server").mkdir(parents=True)
    (repo / "tools").mkdir(parents=True)
    (repo / "tools/run_qgis_worker.sh").touch()
    python = repo / "venv/bin/python"
    python.parent.mkdir(parents=True)
    python.touch(mode=0o700)
    app = tmp_path / "QGIS.app"
    app.mkdir()
    instance = LocalQgisRuntimeHost(
        repo_root=repo, home=home, platform="darwin",
        environ={"SCOUT_QGIS_CONTENTS": str(app / "Contents")},
        config=QgisSpatialBackendConfig(
            enabled=True, worker_url="http://127.0.0.1:19876",
            worker_token=token_file.read_text(),
        ),
    )
    monkeypatch.setattr(instance, "worker_listening", lambda: False)
    monkeypatch.setattr(instance, "_bridge_present", lambda: False)
    return instance


@pytest.mark.parametrize("url,code", (
    ("http://scout.local:9876", Code.REMOTE_MANAGED),
    ("http://192.168.1.2:9876", Code.REMOTE_MANAGED),
    ("http://127.0.0.1:9876/remote", Code.CONFIGURATION_REQUIRED),
    ("http://user:secret@127.0.0.1:9876", Code.CONFIGURATION_REQUIRED),
    ("http://127.0.0.1:9876?command=restart", Code.CONFIGURATION_REQUIRED),
    ("https://127.0.0.1:9876", Code.CONFIGURATION_REQUIRED),
    ("http://127.0.0.1:bad", Code.CONFIGURATION_REQUIRED),
))
def test_configuration_never_manages_remote_or_arbitrary_worker_urls(host, url, code) -> None:
    host.config = replace(host.config, worker_url=url)
    assert host.configuration_issue() == code


def test_prepared_credentials_must_match_without_rewriting_them(host) -> None:
    assert host.configuration_issue() is None
    before = host.token_file.read_bytes()
    host.config = replace(host.config, worker_token="different-fixture-token-1234567890")
    assert host.configuration_issue() == Code.CONFIGURATION_REQUIRED
    assert host.token_file.read_bytes() == before


def test_mac_opens_only_prepared_profile_and_correct_profiles_path(host, monkeypatch) -> None:
    bridge_checks = iter([False, True])
    monkeypatch.setattr(host, "_bridge_present", lambda: next(bridge_checks))
    monkeypatch.setattr(host, "_qgis_running", lambda: False)
    run = Mock()
    monkeypatch.setattr("qgis_local_runtime.subprocess.run", run)
    assert host.ensure_qgis() == "qgis_started"
    argv = run.call_args.args[0]
    assert argv == [
        "/usr/bin/open", "-a", str(host.qgis_app), "--args", "--profiles-path",
        str(host.profile_root), "--profile", "scout", "--nologo", "--noversioncheck",
    ]
    assert run.call_args.kwargs.get("shell", False) is False


def test_existing_qgis_is_never_closed_or_replaced(host, monkeypatch) -> None:
    monkeypatch.setattr(host, "_qgis_running", lambda: True)
    run = Mock(side_effect=AssertionError("No launch, kill, or restart allowed"))
    monkeypatch.setattr("qgis_local_runtime.subprocess.run", run)
    with pytest.raises(QgisRuntimeUnavailable) as error:
        host.ensure_qgis()
    assert error.value.code == Code.QGIS_SESSION_REQUIRES_ATTENTION
    run.assert_not_called()


def test_existing_bridge_is_reused_on_linux_without_mac_commands(host, monkeypatch) -> None:
    host.platform = "linux"
    monkeypatch.setattr(host, "_bridge_present", lambda: True)
    monkeypatch.setattr("qgis_local_runtime.subprocess.run", Mock(side_effect=AssertionError("No GUI launch")))
    assert host.ensure_qgis() == "existing_qgis_preserved"
    monkeypatch.setattr(host, "_bridge_present", lambda: False)
    with pytest.raises(QgisRuntimeUnavailable) as error:
        host.ensure_qgis()
    assert error.value.code == Code.UNSUPPORTED_HOST


def test_worker_uses_fixed_launcher_and_server_owned_port_only_once(host, monkeypatch) -> None:
    process = SimpleNamespace(poll=lambda: None)
    launch = Mock(return_value=process)
    monkeypatch.setattr("qgis_local_runtime.subprocess.Popen", launch)
    host.start_worker()
    host.start_worker()
    launch.assert_called_once()
    assert launch.call_args.args == (["/bin/bash", str(host.launcher)],)
    assert launch.call_args.kwargs.get("shell", False) is False
    assert launch.call_args.kwargs["env"]["SCOUT_QGIS_WORKER_PORT"] == "19876"
    assert launch.call_args.kwargs["env"]["SCOUT_QGIS_WORKER_HOST"] == "127.0.0.1"
    assert launch.call_args.kwargs["start_new_session"] is True


def test_unrecognized_listener_is_preserved(host, monkeypatch) -> None:
    monkeypatch.setattr(host, "worker_listening", lambda: True)
    monkeypatch.setattr(host, "worker_authenticated", lambda: False)
    launch = Mock(side_effect=AssertionError("Occupied port must not launch"))
    monkeypatch.setattr("qgis_local_runtime.subprocess.Popen", launch)
    with pytest.raises(QgisRuntimeUnavailable) as error:
        host.start_worker()
    assert error.value.code == Code.PORT_IN_USE
    launch.assert_not_called()


def test_worker_identity_requires_authenticated_candidate_capability_contract(host, monkeypatch) -> None:
    payload = {
        "schema_version": "scout_qgis_worker_capabilities.v0_1",
        "workflows": ["terrain_route_hypothesis.v1"],
        "candidate_only": True, "runtime_safety_truth": False,
    }
    monkeypatch.setattr(host.backend.transport, "get_json", lambda *a, **kw: payload)
    assert host.worker_authenticated() is True
    payload["runtime_safety_truth"] = True
    assert host.worker_authenticated() is False


def test_local_status_never_redirects_auth_to_another_endpoint() -> None:
    request = Request("http://127.0.0.1:9876/status")
    with pytest.raises(HTTPError):
        _NoRedirect().redirect_request(request, None, 302, "Found", {}, "https://external.invalid/")


def test_connection_metadata_alone_does_not_prove_bridge_ready(host, monkeypatch) -> None:
    host.connection_file.parent.mkdir(parents=True)
    host.connection_file.write_text(json.dumps({"port": 12345, "pid": 54321}))
    monkeypatch.setattr(host, "_port_open", lambda port: False)
    assert LocalQgisRuntimeHost._bridge_present(host) is False
