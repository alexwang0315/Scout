"""Real child ownership, process reaping, restart and launch-failure contracts."""
from __future__ import annotations

import gc
import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
import weakref
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

import scout_exploration_jobs as jobs
from scout_exploration_workspace import ExplorationWorkspaceError
from test_scout_exploration_workspace import _create as _create_workspace

ROOT = Path(__file__).resolve().parents[1]


def _create(tmp_path, **updates):
    root, _ = _create_workspace(tmp_path, **updates)
    return root, jobs.ExplorationJobManager(root).get()


def _command(receipt, key="first"):
    return {"expected_intake_sha256": receipt["intake_sha256"], "idempotency_key": key, "fetch_map": False}


def _hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def _finish(root, deadline):
    while time.monotonic() < deadline:
        state = jobs.ExplorationJobManager(root).get()["preparation"]
        if state["status"] not in {"queued", "running"}:
            return state
        time.sleep(.01)
    raise AssertionError("Original 20-second worker deadline expired")


@pytest.fixture
def observed(tmp_path, monkeypatch):
    real_popen, real_thread = subprocess.Popen, threading.Thread
    state = SimpleNamespace(launched=[], reaped={}, threads=[], gates=[], gated=True, exit_code=None)

    class ObservedPopen(real_popen):
        def __init__(self, args, **kwargs):
            original = list(args)
            gate = tmp_path / f"worker-gate-{len(state.launched)}"
            state.gates.append(gate)
            script = "from pathlib import Path\nimport os,runpy,signal,sys,time\n"
            if state.gated:
                script += (f"gate=Path({str(gate)!r})\nend=time.monotonic()+20\n"
                           "while not gate.exists():\n"
                           " if time.monotonic()>=end: raise SystemExit(90)\n"
                           " time.sleep(.01)\n")
            if state.exit_code is None:
                script += f"sys.argv={original[3:]!r}\nrunpy.run_module('scout_exploration_jobs',run_name='__main__')\n"
            elif state.exit_code < 0:
                script += f"os.kill(os.getpid(),{-state.exit_code})\n"
            else:
                script += f"raise SystemExit({state.exit_code})\n"
            super().__init__([original[0], "-B", "-c", script], **kwargs)
            # Weak references cannot keep Popen alive and conceal the original bug.
            state.launched.append({"pid": self.pid, "weak": weakref.ref(self), "gate": gate,
                                   "original": original, "start_new_session": kwargs["start_new_session"],
                                   "pass_fds": kwargs["pass_fds"]})

        def wait(self, *args, **kwargs):
            result = super().wait(*args, **kwargs)
            state.reaped[self.pid] = result
            return result

    def record_thread(*args, **kwargs):
        thread = real_thread(*args, **kwargs)
        state.threads.append(thread)
        return thread

    monkeypatch.setattr(jobs.subprocess, "Popen", ObservedPopen)
    monkeypatch.setattr(jobs, "Thread", record_thread)
    state.popen = ObservedPopen
    state.thread = record_thread
    yield state
    # Only release gates and join the reapers created by this test.
    for gate in state.gates:
        gate.touch()
    deadline = time.monotonic() + 20
    for thread in state.threads:
        if thread.ident is not None:
            thread.join(max(0, deadline - time.monotonic()))
    assert all(not thread.is_alive() for thread in state.threads)


def _assert_reaped(observed, pid, deadline, code=0):
    while pid not in observed.reaped and time.monotonic() < deadline:
        time.sleep(.01)
    assert observed.reaped.get(pid) == code
    with pytest.raises(ChildProcessError):
        os.waitpid(pid, os.WNOHANG)


def test_submission_retains_child_after_manager_gc_and_reaps_exactly_once(tmp_path, observed):
    root, receipt = _create(tmp_path)
    manager = jobs.ExplorationJobManager(root)
    deadline = time.monotonic() + 20
    result = manager.submit(_command(receipt))
    assert result["preparation"]["worker_live"] is True
    assert len(observed.launched) == len(observed.threads) == 1
    child = observed.launched[0]
    assert child["start_new_session"] is True and len(child["pass_fds"]) == 1
    assert observed.threads[0].daemon is True
    del manager
    gc.collect()
    assert child["weak"]() is not None and child["pid"] not in observed.reaped
    before = _hashes(root)
    assert jobs.ExplorationJobManager(root).get()["preparation"]["worker_live"] is True
    assert _hashes(root) == before
    child["gate"].touch()
    state = _finish(root, deadline)
    assert state["status"] == "completed_with_gaps" and state["attempt"] == 1
    _assert_reaped(observed, child["pid"], deadline)
    assert len(observed.reaped) == 1


def test_thread_start_failure_never_launches_child_and_releases_lease(tmp_path, observed, monkeypatch):
    root, receipt = _create(tmp_path)

    class CannotStart:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            raise RuntimeError("fixture thread-start failure")

    monkeypatch.setattr(jobs, "Thread", CannotStart)
    manager = jobs.ExplorationJobManager(root)
    with pytest.raises(RuntimeError, match="thread-start failure"):
        manager.submit(_command(receipt))
    assert observed.launched == observed.threads == []
    state = jobs.ExplorationJobManager(root).get()["preparation"]
    assert state["status"] == "failed" and state["worker_live"] is False
    assert state["error"]["code"] == "worker_launch_failed" and state["can_resume"] is True


def test_popen_failure_unblocks_waiter_releases_lease_and_can_resume(tmp_path, observed, monkeypatch):
    root, receipt = _create(tmp_path)

    def failed_popen(*args, **kwargs):
        raise OSError("fixture spawn failure")

    monkeypatch.setattr(jobs.subprocess, "Popen", failed_popen)
    manager = jobs.ExplorationJobManager(root)
    with pytest.raises(OSError, match="spawn failure"):
        manager.submit(_command(receipt))
    observed.threads[0].join(1)
    assert not observed.threads[0].is_alive() and not observed.launched
    state = manager.get()["preparation"]
    assert state["status"] == "failed" and state["worker_live"] is False
    monkeypatch.setattr(jobs.subprocess, "Popen", observed.popen)
    observed.gated = False
    deadline = time.monotonic() + 20
    manager.submit(_command(receipt, "retry"), resume=True)
    assert _finish(root, deadline)["status"] == "completed_with_gaps"
    _assert_reaped(observed, observed.launched[0]["pid"], deadline)


def test_worker_log_open_failure_unblocks_waiter_without_child(tmp_path, observed, monkeypatch):
    root, receipt = _create(tmp_path)
    original_open = Path.open

    def fail_worker_log(path, *args, **kwargs):
        if path.name == "worker.log":
            raise OSError("fixture worker log failure")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_worker_log)
    manager = jobs.ExplorationJobManager(root)
    with pytest.raises(OSError, match="worker log failure"):
        manager.submit(_command(receipt))
    observed.threads[0].join(1)
    assert not observed.threads[0].is_alive() and not observed.launched
    state = manager.get()["preparation"]
    assert state["status"] == "failed" and state["worker_live"] is False


@pytest.mark.parametrize("exit_code", [7, -signal.SIGTERM])
def test_abrupt_child_exit_is_reaped_and_requires_explicit_resume(tmp_path, observed, exit_code):
    root, receipt = _create(tmp_path)
    observed.exit_code = exit_code
    manager = jobs.ExplorationJobManager(root)
    deadline = time.monotonic() + 20
    manager.submit(_command(receipt))
    child = observed.launched[0]
    child["gate"].touch()
    _assert_reaped(observed, child["pid"], deadline, code=exit_code)
    before = _hashes(root)
    for _ in range(2):
        state = jobs.ExplorationJobManager(root).get()["preparation"]
        assert state["status"] == "interrupted" and state["can_resume"] is True
    assert _hashes(root) == before and len(observed.launched) == 1
    observed.exit_code, observed.gated = None, False
    manager.submit(_command(receipt, "resume-after-exit"), resume=True)
    assert _finish(root, deadline)["status"] == "completed_with_gaps"
    _assert_reaped(observed, observed.launched[-1]["pid"], deadline)
    assert len(observed.launched) == len(observed.reaped) == 2


def test_concurrent_duplicate_commands_launch_only_one_worker(tmp_path, observed):
    root, receipt = _create(tmp_path)
    barrier = threading.Barrier(2)
    deadline = time.monotonic() + 20

    def submit():
        barrier.wait(timeout=5)
        try:
            return jobs.ExplorationJobManager(root).submit(_command(receipt))["preparation"]["worker_live"]
        except ExplorationWorkspaceError as exc:
            assert "already running" in str(exc)
            return "locked"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: submit(), range(2)))
    assert all(result in {True, "locked"} for result in outcomes)
    assert len(observed.launched) == 1
    assert jobs.ExplorationJobManager(root).submit(_command(receipt))["preparation"]["worker_live"] is True
    assert len(observed.launched) == 1
    observed.launched[0]["gate"].touch()
    assert _finish(root, deadline)["status"] == "completed_with_gaps"
    _assert_reaped(observed, observed.launched[0]["pid"], deadline)


def test_different_workspaces_have_independent_live_workers_and_reapers(tmp_path, observed):
    first, first_receipt = _create(tmp_path, project_id="first")
    second, second_receipt = _create(tmp_path, project_id="second")
    deadline = time.monotonic() + 20
    jobs.ExplorationJobManager(first).submit(_command(first_receipt))
    jobs.ExplorationJobManager(second).submit(_command(second_receipt))
    assert len(observed.launched) == 2
    a, b = observed.launched
    a["gate"].touch()
    assert _finish(first, deadline)["status"] == "completed_with_gaps"
    _assert_reaped(observed, a["pid"], deadline)
    assert jobs.ExplorationJobManager(second).get()["preparation"]["worker_live"] is True
    assert b["weak"]() is not None and b["pid"] not in observed.reaped
    b["gate"].touch()
    assert _finish(second, deadline)["status"] == "completed_with_gaps"
    _assert_reaped(observed, b["pid"], deadline)


def test_daemon_reaper_does_not_block_parent_exit_or_cancel_durable_child(tmp_path):
    root, receipt = _create(tmp_path)
    gate = tmp_path / "parent-exit-gate"
    # This parent exits while its one-shot child is deliberately gated before
    # executing the real worker module. Its daemon reaper must not join on exit.
    program = f"""
import json,subprocess,sys
import scout_exploration_jobs as jobs
from pathlib import Path
original = subprocess.Popen
pids = []
def launch(args, **kwargs):
    code = "from pathlib import Path\\nimport runpy,sys,time\\n"
    code += "gate=Path({str(gate)!r})\\nend=time.monotonic()+20\\n"
    code += "while not gate.exists():\\n if time.monotonic()>=end: raise SystemExit(90)\\n time.sleep(.01)\\n"
    code += "sys.argv=" + repr(args[3:]) + "\\nrunpy.run_module('scout_exploration_jobs',run_name='__main__')\\n"
    child = original([args[0], '-B', '-c', code], **kwargs)
    pids.append(child.pid)
    return child
jobs.subprocess.Popen = launch
state = jobs.ExplorationJobManager(Path({str(root)!r})).submit({repr(_command(receipt))})
print(json.dumps({{'pids':pids, 'worker_live':state['preparation']['worker_live']}}),flush=True)
"""
    deadline = time.monotonic() + 20
    try:
        parent = subprocess.run([sys.executable, "-B", "-W", "error", "-c", program], cwd=ROOT,
                                capture_output=True, text=True, timeout=20)
        assert parent.returncode == 0, parent.stderr
        result = json.loads(parent.stdout)
        assert result["worker_live"] is True and len(result["pids"]) == 1
        assert parent.stderr == ""
        assert jobs.ExplorationJobManager(root).get()["preparation"]["worker_live"] is True
    finally:
        gate.touch()
    state = _finish(root, deadline)
    assert state["status"] == "completed_with_gaps" and state["attempt"] == 1
    assert state["report"]["primary_gpx"] is None and state["report"]["reference_gpxs"] == []
