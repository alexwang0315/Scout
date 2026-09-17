from __future__ import annotations

import importlib
import json
import shutil
import socket
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import admin_api
from phase4_pretrip_release_check import (
    DEFAULT_PROJECT_PATH,
    _check_admin_workspace_persistence_contract,
    _check_admin_workspace_project_creation_contract,
)


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ID = "chilai_nanhua_day1"
CHECKS = (
    _check_admin_workspace_persistence_contract,
    _check_admin_workspace_project_creation_contract,
)


@pytest.fixture
def workspace_contract_root(tmp_path: Path) -> Path:
    for relative in (
        "admin_api.py",
        "pretrip_review_decision_store.py",
        "pretrip_review_decision_apply_store.py",
        "pretrip_workspace_project.py",
    ):
        shutil.copyfile(ROOT / relative, tmp_path / relative)
    project = ROOT / DEFAULT_PROJECT_PATH
    target = tmp_path / DEFAULT_PROJECT_PATH
    target.parent.mkdir(parents=True)
    shutil.copyfile(project, target)
    review_ref = json.loads(project.read_text(encoding="utf-8"))["review_decision_log_ref"]
    review_target = target.parent / review_ref
    review_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(project.parent / review_ref, review_target)
    return tmp_path


@pytest.mark.parametrize("check", CHECKS, ids=("persistence", "creation"))
def test_source_contract_accepts_operation_records_and_url_parsing(
    workspace_contract_root: Path, check
) -> None:
    report = check(workspace_contract_root)
    assert report["ok"], report["missing"]
    assert report["forbidden_source_fragments"] == []
    assert report["phase1_runtime_mutation_allowed"] is False
    assert report["phase2_writeback_allowed"] is False
    assert report["external_api_calls_made"] is False


@pytest.mark.parametrize("check", CHECKS, ids=("persistence", "creation"))
@pytest.mark.parametrize(
    ("source", "fragment"),
    (
        ("import requests\n", "requests"),
        ("import requests as client\n", "requests"),
        ("from requests import get as fetch\n", "requests"),
        ("from requests.sessions import Session\n", "requests"),
        ("import httpx as client\n", "httpx"),
        ("from httpx import AsyncClient\n", "httpx"),
        ("client = __import__('requests')\n", "requests"),
        ("import importlib\nclient = importlib.import_module('httpx')\n", "httpx"),
        ("from importlib import import_module as load\nclient = load('requests')\n", "requests"),
        ("def forbidden_call():\n    return requests.get('https://example.invalid')\n", "requests"),
    ),
)
def test_source_contract_still_rejects_network_clients(
    workspace_contract_root: Path, check, source: str, fragment: str
) -> None:
    target = workspace_contract_root / "admin_api.py"
    with target.open("a", encoding="utf-8") as output:
        output.write("\n" + source)
    report = check(workspace_contract_root)
    assert report["ok"] is False
    assert {"path": "admin_api.py", "fragment": fragment} in report["forbidden_source_fragments"]
    assert any(fragment in item for item in report["missing"])


@pytest.mark.parametrize(
    ("source", "fragment"),
    (
        ("from urllib import request\n", "urllib"),
        ("from urllib.request import urlopen as fetch\n", "urllib"),
        ("import urllib.request as client\n", "urllib"),
        ("import urllib\n", "urllib"),
        ("client = __import__('urllib.request')\n", "urllib"),
        ("import importlib as loader\nclient = loader.import_module('urllib.request')\n", "urllib"),
        ("def forbidden_call():\n    return urllib.request.urlopen('https://example.invalid')\n", "urllib"),
        ("import aiohttp as client\n", "aiohttp"),
        ("from aiohttp import ClientSession\n", "aiohttp"),
    ),
)
def test_creation_contract_still_rejects_additional_network_clients(
    workspace_contract_root: Path, source: str, fragment: str
) -> None:
    target = workspace_contract_root / "admin_api.py"
    with target.open("a", encoding="utf-8") as output:
        output.write("\n" + source)
    report = _check_admin_workspace_project_creation_contract(workspace_contract_root)
    assert report["ok"] is False
    assert {"path": "admin_api.py", "fragment": fragment} in report["forbidden_source_fragments"]


@pytest.mark.parametrize("check", CHECKS, ids=("persistence", "creation"))
@pytest.mark.parametrize(
    "fragment",
    ("/safety", "Phase1IncidentBridge", "Phase2Brain", "phase2_writeback_policy", "write_observed_fact"),
)
def test_source_contract_retains_other_forbidden_boundaries(
    workspace_contract_root: Path, check, fragment: str
) -> None:
    target = workspace_contract_root / "admin_api.py"
    with target.open("a", encoding="utf-8") as output:
        output.write("\n# " + fragment + "\n")
    report = check(workspace_contract_root)
    assert report["ok"] is False
    assert {"path": "admin_api.py", "fragment": fragment} in report["forbidden_source_fragments"]


def _network_effect_recorder(monkeypatch):
    attempts: list[str] = []
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def deny(kind: str):
        def blocked(*_args, **_kwargs):
            attempts.append(kind)
            raise OSError("qualification network effect denied before outbound I/O")
        return blocked

    def guarded_connect(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            return deny("tcp_connect")(sock, address)
        return original_connect(sock, address)

    def guarded_connect_ex(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            return deny("tcp_connect_ex")(sock, address)
        return original_connect_ex(sock, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", deny("dns_lookup"))
    monkeypatch.setattr(socket, "create_connection", deny("create_connection"))
    monkeypatch.setattr(subprocess, "Popen", deny("child_process"))
    return attempts


def _network_attempts(transport: str) -> None:
    if transport == "helper":
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
            connection.connect(("198.51.100.13", 443))
    elif transport == "dynamic":
        importlib.import_module("urllib.request").urlopen("https://example.invalid/")
    else:
        subprocess.run(["curl", "https://example.invalid/"], check=True)


def _perform_workspace_operation(tmp_path: Path, operation: str):
    workspace_root = tmp_path / "workspaces"
    if operation == "persistence":
        shutil.copytree(ROOT / Path(DEFAULT_PROJECT_PATH).parent, workspace_root / PROJECT_ID)
    with TestClient(admin_api.create_admin_app(pretrip_workspace_root=workspace_root)) as client:
        if operation == "creation":
            return client.post(f"/admin/pretrip/projects/{PROJECT_ID}/workspace")
        return client.post(
            f"/admin/pretrip/projects/{PROJECT_ID}/review-decisions",
            json={
                "candidate_ref": "contour.g11.seg_006_008",
                "decision": "accepted",
                "reviewer_alias": "network-contract-test",
                "summary": "Candidate-only fixture review.",
                "persist_to_workspace": True,
            },
        )


def _network_effect_result(response, attempts: list[str]) -> dict[str, object]:
    return {
        "ok": response.status_code == 200 and not attempts,
        "http_status": response.status_code,
        "network_effect_count": len(attempts),
        "network_effects": list(attempts),
    }


@pytest.mark.parametrize("operation", ("creation", "persistence"))
def test_real_workspace_operation_has_no_network_effects(tmp_path, monkeypatch, operation):
    attempts = _network_effect_recorder(monkeypatch)
    response = _perform_workspace_operation(tmp_path, operation)
    result = _network_effect_result(response, attempts)
    (tmp_path / "network-effect-receipt.json").write_text(json.dumps(result, indent=2) + "\n")
    assert result["ok"], result
    assert response.json()["boundary"]["external_api_calls_made"] is False
    assert response.json()["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert response.json()["boundary"]["phase2_writeback_allowed"] is False
    assert response.json()["persisted"] is True


@pytest.mark.parametrize("operation", ("creation", "persistence"))
@pytest.mark.parametrize("transport", ("helper", "dynamic", "child"))
def test_effect_gate_rejects_swallowed_indirect_network_attempts(
    tmp_path, monkeypatch, operation, transport
):
    attempts = _network_effect_recorder(monkeypatch)
    helper = "copy_pretrip_project_workspace" if operation == "creation" else "append_review_decision"
    original = getattr(admin_api, helper)

    def network_using_helper(*args, **kwargs):
        try:
            _network_attempts(transport)
        except OSError:
            pass
        return original(*args, **kwargs)

    monkeypatch.setattr(admin_api, helper, network_using_helper)
    response = _perform_workspace_operation(tmp_path, operation)
    result = _network_effect_result(response, attempts)
    # A swallowed helper error can leave a successful HTTP response and a stale
    # boundary flag. Acceptance must still fail from observed effects.
    assert response.status_code == 200
    assert response.json()["boundary"]["external_api_calls_made"] is False
    assert result["ok"] is False
    assert result["network_effect_count"] >= 1
    expected = {"helper": {"tcp_connect"}, "dynamic": {"dns_lookup", "create_connection", "tcp_connect"}, "child": {"child_process"}}
    (tmp_path / "network-effect-receipt.json").write_text(json.dumps({**result, "transport": transport, "operation": operation}, indent=2) + "\n")
    assert expected[transport].intersection(result["network_effects"])
