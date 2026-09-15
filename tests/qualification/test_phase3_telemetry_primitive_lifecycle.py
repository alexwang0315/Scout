from __future__ import annotations

import builtins
import json
import os
import socket
import subprocess
import sys
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path

import admin_api  # Load dependencies before an outer audit restricts filesystem access.
import pytest

from scout_agent_cli import run_scout_agent_cli
from scout_agent_trace import load_agent_trace
from tests.qualification import phase3_telemetry
from tests.qualification.effects import EffectAudit

ROOT = Path(__file__).resolve().parents[2]
PRIMITIVES = (
    ("subprocess.run", subprocess, "run"),
    ("subprocess.Popen", subprocess, "Popen"),
    ("socket.socket", socket, "socket"),
    ("builtins.open", builtins, "open"),
    ("Path.open", Path, "open"),
    ("os.open", os, "open"),
)


def _identities():
    return {label: getattr(owner, name) for label, owner, name in PRIMITIVES}


def _restore(original):
    for label, owner, name in PRIMITIVES:
        setattr(owner, name, original[label])


def _identity_description(values):
    return {
        label: {"id": id(value), "module": getattr(value, "__module__", ""),
                "qualname": getattr(value, "__qualname__", type(value).__qualname__)}
        for label, value in values.items()
    }


def _preserve_receipt(name, payload):
    target = os.environ.get("SCOUT_TELEMETRY_LIFECYCLE_RECEIPTS")
    if target:
        destination = Path(target)
        destination.mkdir(parents=True, exist_ok=True)
        (destination / f"{name}.json").write_text(json.dumps(payload, indent=2) + "\n")


def _install_replay(monkeypatch, *, raises, only_subprocess=False):
    def fixture_replay(tmp_path, monkeypatch):
        def inert_primitive(*args, **kwargs):
            raise AssertionError("fixture primitive must not execute")

        for label, owner, name in PRIMITIVES:
            if not only_subprocess or label.startswith("subprocess."):
                monkeypatch.setattr(owner, name, inert_primitive)
        if raises:
            raise RuntimeError("intentional telemetry reader failure")

    monkeypatch.setattr(sys.modules[__name__], "lifecycle_fixture_replay", fixture_replay, raising=False)
    contract = replace(
        phase3_telemetry.READ_TELEMETRY_CONTRACTS[0],
        domain_id="primitive-lifecycle-fixture", route="primitive-lifecycle",
        replay_nodes=(f"{__name__}::lifecycle_fixture_replay",),
    )
    monkeypatch.setattr(phase3_telemetry, "READ_TELEMETRY_CONTRACTS", (contract,))


def _local_status_cli(tmp_path):
    request = tmp_path / "status-request.json"
    request.write_text(json.dumps({"trip_id": "lifecycle-fixture"}))
    trace = tmp_path / "agent-trace.jsonl"
    exit_code, payload = run_scout_agent_cli([
        "tools", "run", "scout.local_evidence.status", "--manifest-dir",
        str(ROOT / "tools/scout_agent_tool_manifests"), "--input", str(request),
        "--trace-log", str(trace), "--json",
    ])
    return exit_code, payload, trace


@pytest.mark.parametrize("raises", [False, True], ids=["normal", "reader-error"])
@pytest.mark.parametrize("nested", [False, True], ids=["single-audit", "nested-audit"])
def test_telemetry_replay_restores_exact_primitive_identity(tmp_path, monkeypatch, raises, nested):
    _install_replay(monkeypatch, raises=raises)
    original = _identities()
    outer = EffectAudit(
        transition_id="lifecycle.outer",
        roots=(("execution", tmp_path), ("repository", ROOT)),
    ) if nested else nullcontext()
    try:
        with outer:
            before = _identities()
            replays = phase3_telemetry.replay_read_telemetry(
                "primitive-lifecycle-fixture", execution_root=tmp_path / "replays",
                repository_root=ROOT,
            )
            after = _identities()
            inner_restored = {label: after[label] is value for label, value in before.items()}
        final = _identities()
        outer_restored = {label: final[label] is value for label, value in original.items()}
    finally:
        # Preserve failures while keeping the isolated negative replay process usable.
        _restore(original)
    receipt = {
        "nested": nested, "reader_raises": raises,
        "before": _identity_description(before), "after": _identity_description(after),
        "inner_restored": inner_restored, "outer_restored": outer_restored,
        "replay_status": [item.status for item in replays],
        "replay_detail": [item.detail for item in replays],
    }
    _preserve_receipt(f"identity-{nested}-{raises}", receipt)
    assert len(replays) == 1
    assert replays[0].status == ("failed" if raises else "passed")
    if raises:
        assert replays[0].detail == "RuntimeError: intentional telemetry reader failure"
    assert all(inner_restored.values()), receipt
    assert all(outer_restored.values()), receipt


@pytest.mark.parametrize("raises", [False, True], ids=["normal", "reader-error"])
def test_telemetry_cleanup_preserves_following_local_cli(tmp_path, monkeypatch, raises):
    _install_replay(monkeypatch, raises=raises, only_subprocess=True)
    original = _identities()
    try:
        replays = phase3_telemetry.replay_read_telemetry(
            "primitive-lifecycle-fixture", execution_root=tmp_path / "replays",
            repository_root=ROOT,
        )
        after = _identities()
        restored = {label: after[label] is value for label, value in original.items()}
        exit_code, payload, trace = _local_status_cli(tmp_path)
    finally:
        _restore(original)
    receipt = {"reader_raises": raises, "restored": restored, "cli_exit_code": exit_code,
               "cli_result": payload, "replay_status": [item.status for item in replays]}
    _preserve_receipt(f"following-cli-{raises}", receipt)
    assert exit_code == 0, receipt
    assert all(restored.values()), receipt
    assert payload["status"] == "completed"
    output = json.loads(payload["outputs"]["stdout"])
    assert output["offline_only"] is True
    assert output["boundary"]["live_safety_api_calls_allowed"] is False
    assert load_agent_trace(trace)[0].tool_id == "scout.local_evidence.status"


def test_registered_monitor_replays_restore_primitives_before_following_cli(tmp_path):
    original = _identities()
    try:
        replays = phase3_telemetry.replay_read_telemetry(
            "observer-hardware-boundary", execution_root=tmp_path / "monitor-replays",
            repository_root=ROOT,
        )
        after = _identities()
        restored = {label: after[label] is value for label, value in original.items()}
        exit_code, payload, trace = _local_status_cli(tmp_path)
    finally:
        _restore(original)
    receipt = {"restored": restored, "cli_exit_code": exit_code, "cli_result": payload,
               "replays": [{"node_id": item.node_id, "status": item.status,
                            "detail": item.detail} for item in replays]}
    _preserve_receipt("registered-monitor-and-cli", receipt)
    assert len(replays) == 9
    assert all(item.status == "passed" for item in replays), receipt
    assert all(restored.values()), receipt
    assert exit_code == 0, receipt
    assert payload["status"] == "completed"
    assert load_agent_trace(trace)[0].tool_id == "scout.local_evidence.status"
