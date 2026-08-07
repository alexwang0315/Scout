from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import threading
from pathlib import Path
from typing import Any

import pytest

import dashboard_workspace_publication as workspace_publication_module
from dashboard_workspace_publication import (
    DashboardWorkspacePublication,
    WorkspacePreparationBusyError,
    WorkspaceRecoveryError,
    _exchange_directories,
    _locked_rename_exchange,
    dashboard_project_id_from_read_path,
)

PROJECT_ID = "fixture-route"


def _write_project(
    workspace_root: Path,
    *,
    project_id: str = PROJECT_ID,
    generation: str = "old",
) -> Path:
    project_root = workspace_root / project_id
    project_root.mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "project_id": project_id,
                "generation": generation,
            }
        ),
        encoding="utf-8",
    )
    return project_root


def _read_generation(project_root: Path) -> str:
    payload = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    return str(payload["generation"])


def _hold_staged_preparation(
    workspace_root: str,
    ready: Any,
    release: Any,
) -> None:
    publication = DashboardWorkspacePublication(Path(workspace_root))
    staged = publication.stage(PROJECT_ID)
    ready.set()
    if not release.wait(timeout=10):
        os._exit(81)
    publication.discard(staged)


def _hold_dashboard_read(
    workspace_root: str,
    ready: Any,
    release: Any,
) -> None:
    publication = DashboardWorkspacePublication(Path(workspace_root))
    publication.acquire_read(PROJECT_ID)
    ready.set()
    if not release.wait(timeout=10):
        os._exit(82)
    publication.release_read(PROJECT_ID)


def _stage_then_hard_exit(workspace_root: str) -> None:
    publication = DashboardWorkspacePublication(Path(workspace_root))
    publication.stage(PROJECT_ID)
    os._exit(83)


def _exchange_then_hard_exit(left: Path, right: Path) -> str:
    _exchange_directories(left, right)
    os._exit(84)


def _publish_then_hard_exit(workspace_root: str) -> None:
    publication = DashboardWorkspacePublication(
        Path(workspace_root),
        exchange_directories=_exchange_then_hard_exit,
    )
    staged = publication.stage(PROJECT_ID)
    (staged.staged_root / "project.json").write_text(
        json.dumps({"project_id": PROJECT_ID, "generation": "new"}),
        encoding="utf-8",
    )
    publication.publish(staged)
    os._exit(85)


def _publish_evidence_only_then_hard_exit(workspace_root: str) -> None:
    publication = DashboardWorkspacePublication(
        Path(workspace_root),
        exchange_directories=_exchange_then_hard_exit,
    )
    staged = publication.stage(PROJECT_ID)
    (staged.staged_root / "evidence.json").write_text("new", encoding="utf-8")
    publication.publish(staged)
    os._exit(88)


def _move_live_then_hard_exit(left: Path, right: Path) -> str:
    left.rename(right.parent / ".retired-injected-crash")
    os._exit(86)


def _fallback_exchange_then_hard_exit(workspace_root: str) -> None:
    publication = DashboardWorkspacePublication(
        Path(workspace_root),
        exchange_directories=_move_live_then_hard_exit,
    )
    staged = publication.stage(PROJECT_ID)
    (staged.staged_root / "project.json").write_text(
        json.dumps({"project_id": PROJECT_ID, "generation": "new"}),
        encoding="utf-8",
    )
    publication.publish(staged)
    os._exit(87)


def _spawn_context() -> multiprocessing.context.BaseContext:
    return multiprocessing.get_context("spawn")


def _journal_path(workspace_root: Path) -> Path:
    return (
        workspace_root
        / ".scout-connected-preparation"
        / "journals"
        / f"{PROJECT_ID}.json"
    )


def _raise_before_exchange(_: Path, __: Path) -> str:
    raise OSError("simulated failure before directory exchange")


def _exchange_then_raise(left: Path, right: Path) -> str:
    _exchange_directories(left, right)
    raise OSError("simulated failure after directory exchange")


def test_publication_clones_and_exchanges_complete_workspace_generation(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspaces"
    live_root = _write_project(workspace_root)
    (live_root / "evidence.json").write_text("old", encoding="utf-8")
    publication = DashboardWorkspacePublication(workspace_root)

    staged = publication.stage("fixture-route")
    (staged.staged_root / "project.json").write_text(
        json.dumps({"project_id": "fixture-route", "generation": "new"}),
        encoding="utf-8",
    )
    (staged.staged_root / "evidence.json").write_text("new", encoding="utf-8")

    result = publication.publish(staged)

    assert _read_generation(live_root) == "new"
    assert (live_root / "evidence.json").read_text(encoding="utf-8") == "new"
    assert result["publicationMode"] == "staged-atomic-swap"
    assert result["filesystemExchange"] in {
        "renamex_np",
        "renameat2",
        "locked-rename",
    }
    assert result["retiredWorkspaceCleanup"] == "removed"
    assert staged.session_root.exists() is False
    generation_marker = json.loads(
        (live_root / ".scout-workspace-generation.json").read_text(
            encoding="utf-8"
        )
    )
    assert generation_marker["projectId"] == PROJECT_ID
    assert len(generation_marker["generationId"]) == 32


def test_exchange_failure_does_not_confuse_equal_project_json_generations(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspaces"
    live_root = _write_project(workspace_root)
    (live_root / "evidence.json").write_text("old", encoding="utf-8")
    publication = DashboardWorkspacePublication(
        workspace_root,
        exchange_directories=_raise_before_exchange,
    )
    staged = publication.stage(PROJECT_ID)
    (staged.staged_root / "evidence.json").write_text("new", encoding="utf-8")

    with pytest.raises(OSError, match="failure before directory exchange"):
        publication.publish(staged)

    assert (live_root / "evidence.json").read_text(encoding="utf-8") == "old"
    assert _journal_path(workspace_root).exists() is False


def test_cleanup_failure_retains_journal_for_next_startup_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspaces"
    live_root = _write_project(workspace_root)
    publication = DashboardWorkspacePublication(workspace_root)
    staged = publication.stage(PROJECT_ID)
    (staged.staged_root / "project.json").write_text(
        json.dumps({"project_id": PROJECT_ID, "generation": "new"}),
        encoding="utf-8",
    )
    real_cleanup = workspace_publication_module._remove_directory_tree_durably

    def fail_retired_cleanup(path: Path) -> None:
        if path == staged.session_root:
            raise OSError("simulated retired generation cleanup failure")
        real_cleanup(path)

    monkeypatch.setattr(
        workspace_publication_module,
        "_remove_directory_tree_durably",
        fail_retired_cleanup,
    )

    result = publication.publish(staged)

    assert _read_generation(live_root) == "new"
    assert result["retiredWorkspaceCleanup"] == "retained_for_cleanup"
    assert result["recoveryJournalStatus"] == "active"
    assert staged.session_root.is_dir()
    assert _journal_path(workspace_root).exists()

    pending = DashboardWorkspacePublication(workspace_root)

    assert (
        pending.startup_recovery[PROJECT_ID]["status"]
        == "published-cleanup-pending"
    )
    assert pending.recovery_status(PROJECT_ID)["journalStatus"] == "active"
    with pytest.raises(
        WorkspaceRecoveryError,
        match="published workspace cleanup is still pending",
    ):
        pending.stage(PROJECT_ID)
    assert _journal_path(workspace_root).exists()

    monkeypatch.setattr(
        workspace_publication_module,
        "_remove_directory_tree_durably",
        real_cleanup,
    )
    recovered = DashboardWorkspacePublication(workspace_root)

    assert _read_generation(live_root) == "new"
    assert staged.session_root.exists() is False
    assert _journal_path(workspace_root).exists() is False
    assert (
        recovered.startup_recovery[PROJECT_ID]["status"]
        == "completed-publish-cleanup"
    )


def test_committed_exchange_reports_success_when_recovery_cleanup_is_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspaces"
    live_root = _write_project(workspace_root)
    publication = DashboardWorkspacePublication(
        workspace_root,
        exchange_directories=_exchange_then_raise,
    )
    staged = publication.stage(PROJECT_ID)
    (staged.staged_root / "project.json").write_text(
        json.dumps({"project_id": PROJECT_ID, "generation": "new"}),
        encoding="utf-8",
    )
    real_cleanup = workspace_publication_module._remove_directory_tree_durably

    def fail_retired_cleanup(path: Path) -> None:
        if path == staged.session_root:
            raise OSError("simulated recovery cleanup failure")
        real_cleanup(path)

    monkeypatch.setattr(
        workspace_publication_module,
        "_remove_directory_tree_durably",
        fail_retired_cleanup,
    )

    result = publication.publish(staged)

    assert _read_generation(live_root) == "new"
    assert result["filesystemExchange"] == "recovered-after-exchange-error"
    assert result["retiredWorkspaceCleanup"] == "retained_for_cleanup"
    assert result["recoveryJournalStatus"] == "active"
    assert staged.session_root.is_dir()
    assert _journal_path(workspace_root).exists()

    monkeypatch.setattr(
        workspace_publication_module,
        "_remove_directory_tree_durably",
        real_cleanup,
    )
    recovered = DashboardWorkspacePublication(workspace_root)

    assert _read_generation(live_root) == "new"
    assert staged.session_root.exists() is False
    assert _journal_path(workspace_root).exists() is False
    assert (
        recovered.startup_recovery[PROJECT_ID]["status"]
        == "completed-publish-cleanup"
    )


def test_cross_process_preparation_mutex_rejects_second_writer(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspaces"
    _write_project(workspace_root)
    context = _spawn_context()
    ready = context.Event()
    release = context.Event()
    worker = context.Process(
        target=_hold_staged_preparation,
        args=(str(workspace_root), ready, release),
    )

    worker.start()
    assert ready.wait(timeout=10)
    try:
        publication = DashboardWorkspacePublication(workspace_root)
        with pytest.raises(WorkspacePreparationBusyError):
            publication.stage(PROJECT_ID)
    finally:
        release.set()
        worker.join(timeout=10)

    assert worker.exitcode == 0
    assert _read_generation(workspace_root / PROJECT_ID) == "old"


def test_publication_waits_for_active_dashboard_reader_before_exchange(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspaces"
    live_root = _write_project(workspace_root)
    publication = DashboardWorkspacePublication(workspace_root)
    staged = publication.stage("fixture-route")
    (staged.staged_root / "project.json").write_text(
        json.dumps({"project_id": "fixture-route", "generation": "new"}),
        encoding="utf-8",
    )
    publisher_started = threading.Event()
    publisher_done = threading.Event()

    def publish() -> None:
        publisher_started.set()
        publication.publish(staged)
        publisher_done.set()

    worker = threading.Thread(target=publish)
    with publication.read_snapshot("fixture-route"):
        worker.start()
        assert publisher_started.wait(timeout=5)
        assert publisher_done.wait(timeout=0.1) is False
        assert _read_generation(live_root) == "old"

    worker.join(timeout=5)
    assert worker.is_alive() is False
    assert publisher_done.is_set()
    assert _read_generation(live_root) == "new"


def test_dashboard_read_lock_does_not_persist_workspace_artifacts(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspaces"
    _write_project(workspace_root)
    publication = DashboardWorkspacePublication(workspace_root)
    before = {
        path.relative_to(workspace_root).as_posix(): path.read_bytes()
        for path in workspace_root.rglob("*")
        if path.is_file()
    }

    with publication.read_snapshot(PROJECT_ID):
        assert _read_generation(workspace_root / PROJECT_ID) == "old"

    after = {
        path.relative_to(workspace_root).as_posix(): path.read_bytes()
        for path in workspace_root.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_publication_waits_for_reader_in_another_process_before_exchange(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspaces"
    live_root = _write_project(workspace_root)
    publication = DashboardWorkspacePublication(workspace_root)
    staged = publication.stage(PROJECT_ID)
    (staged.staged_root / "project.json").write_text(
        json.dumps({"project_id": PROJECT_ID, "generation": "new"}),
        encoding="utf-8",
    )
    context = _spawn_context()
    reader_ready = context.Event()
    release_reader = context.Event()
    reader = context.Process(
        target=_hold_dashboard_read,
        args=(str(workspace_root), reader_ready, release_reader),
    )
    publisher_done = threading.Event()

    reader.start()
    assert reader_ready.wait(timeout=10)
    publisher = threading.Thread(
        target=lambda: (
            publication.publish(staged),
            publisher_done.set(),
        )
    )
    publisher.start()
    try:
        assert publisher_done.wait(timeout=0.2) is False
        assert _read_generation(live_root) == "old"
    finally:
        release_reader.set()
        reader.join(timeout=10)
        publisher.join(timeout=10)

    assert reader.exitcode == 0
    assert publisher.is_alive() is False
    assert publisher_done.is_set()
    assert _read_generation(live_root) == "new"


def test_startup_recovery_discards_staging_left_by_crashed_process(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspaces"
    live_root = _write_project(workspace_root)
    context = _spawn_context()
    worker = context.Process(
        target=_stage_then_hard_exit,
        args=(str(workspace_root),),
    )

    worker.start()
    worker.join(timeout=10)
    assert worker.exitcode == 83
    assert _journal_path(workspace_root).exists()

    publication = DashboardWorkspacePublication(workspace_root)

    assert _read_generation(live_root) == "old"
    assert _journal_path(workspace_root).exists() is False
    assert publication.startup_recovery[PROJECT_ID]["status"] == "discarded-staging"


def test_startup_recovery_keeps_new_generation_after_crash_during_publish(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspaces"
    live_root = _write_project(workspace_root)
    context = _spawn_context()
    worker = context.Process(
        target=_publish_then_hard_exit,
        args=(str(workspace_root),),
    )

    worker.start()
    worker.join(timeout=10)
    assert worker.exitcode == 84
    assert _read_generation(live_root) == "new"
    assert _journal_path(workspace_root).exists()

    publication = DashboardWorkspacePublication(workspace_root)

    assert _read_generation(live_root) == "new"
    assert _journal_path(workspace_root).exists() is False
    assert (
        publication.startup_recovery[PROJECT_ID]["status"]
        == "completed-publish-cleanup"
    )


def test_startup_recovery_distinguishes_evidence_only_generation_after_crash(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspaces"
    live_root = _write_project(workspace_root)
    (live_root / "evidence.json").write_text("old", encoding="utf-8")
    original_project_json = (live_root / "project.json").read_bytes()
    context = _spawn_context()
    worker = context.Process(
        target=_publish_evidence_only_then_hard_exit,
        args=(str(workspace_root),),
    )

    worker.start()
    worker.join(timeout=10)
    assert worker.exitcode == 84
    assert (live_root / "project.json").read_bytes() == original_project_json
    assert (live_root / "evidence.json").read_text(encoding="utf-8") == "new"
    assert _journal_path(workspace_root).exists()

    publication = DashboardWorkspacePublication(workspace_root)

    assert (live_root / "project.json").read_bytes() == original_project_json
    assert (live_root / "evidence.json").read_text(encoding="utf-8") == "new"
    assert _journal_path(workspace_root).exists() is False
    assert (
        publication.startup_recovery[PROJECT_ID]["status"]
        == "completed-publish-cleanup"
    )
    assert publication.recovery_status(PROJECT_ID)["journalStatus"] == "clear"


def test_startup_recovery_restores_old_generation_after_fallback_move_crash(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspaces"
    live_root = _write_project(workspace_root)
    context = _spawn_context()
    worker = context.Process(
        target=_fallback_exchange_then_hard_exit,
        args=(str(workspace_root),),
    )

    worker.start()
    worker.join(timeout=10)
    assert worker.exitcode == 86
    assert live_root.exists() is False
    assert _journal_path(workspace_root).exists()

    publication = DashboardWorkspacePublication(workspace_root)

    assert _read_generation(live_root) == "old"
    assert _journal_path(workspace_root).exists() is False
    assert (
        publication.startup_recovery[PROJECT_ID]["status"]
        == "restored-old-generation"
    )


def test_startup_recovery_fails_closed_on_mismatched_session_identity(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspaces"
    live_root = _write_project(workspace_root)
    session_id = "a" * 32
    victim = (
        workspace_root
        / ".scout-connected-preparation"
        / "staging"
        / f"other-route.{session_id}"
    )
    victim.mkdir(parents=True)
    (victim / "keep.txt").write_text("do not remove", encoding="utf-8")
    journal_path = _journal_path(workspace_root)
    journal_path.parent.mkdir(parents=True)
    live_project_sha256 = hashlib.sha256(
        (live_root / "project.json").read_bytes()
    ).hexdigest()
    journal_path.write_text(
        json.dumps(
            {
                "schemaVersion": "dashboardWorkspacePublicationJournal.v1",
                "projectId": PROJECT_ID,
                "sessionId": session_id,
                "sessionRef": victim.relative_to(workspace_root).as_posix(),
                "state": "staging",
                "liveProjectSha256": live_project_sha256,
                "stagedProjectSha256": None,
                "liveGenerationId": f"legacy:{live_project_sha256}",
                "stagedGenerationId": None,
            }
        ),
        encoding="utf-8",
    )

    publication = DashboardWorkspacePublication(workspace_root)

    assert victim.exists()
    assert journal_path.exists()
    assert publication.startup_recovery[PROJECT_ID]["status"] == "blocked"
    assert publication.recovery_status(PROJECT_ID)["journalStatus"] == "blocked"


def test_startup_recovery_does_not_follow_staging_session_symlink(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspaces"
    live_root = _write_project(workspace_root)
    session_id = "b" * 32
    staging_root = (
        workspace_root
        / ".scout-connected-preparation"
        / "staging"
    )
    victim = staging_root / "other-project.active-session"
    victim.mkdir(parents=True)
    (victim / "keep.txt").write_text("do not remove", encoding="utf-8")
    session_root = staging_root / f"{PROJECT_ID}.{session_id}"
    session_root.symlink_to(victim, target_is_directory=True)
    journal_path = _journal_path(workspace_root)
    journal_path.parent.mkdir(parents=True)
    live_project_sha256 = hashlib.sha256(
        (live_root / "project.json").read_bytes()
    ).hexdigest()
    journal_path.write_text(
        json.dumps(
            {
                "schemaVersion": "dashboardWorkspacePublicationJournal.v1",
                "projectId": PROJECT_ID,
                "sessionId": session_id,
                "sessionRef": session_root.relative_to(
                    workspace_root
                ).as_posix(),
                "state": "staging",
                "liveProjectSha256": live_project_sha256,
                "stagedProjectSha256": None,
                "liveGenerationId": f"legacy:{live_project_sha256}",
                "stagedGenerationId": None,
            }
        ),
        encoding="utf-8",
    )

    publication = DashboardWorkspacePublication(workspace_root)

    assert victim.is_dir()
    assert (victim / "keep.txt").read_text(encoding="utf-8") == "do not remove"
    assert session_root.is_symlink()
    assert journal_path.exists()
    assert publication.startup_recovery[PROJECT_ID]["status"] == "blocked"


def test_publication_rejects_symlinked_private_staging_root(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspaces"
    _write_project(workspace_root)
    external_root = tmp_path / "external-staging"
    external_root.mkdir()
    private_root = workspace_root / ".scout-connected-preparation"
    private_root.mkdir()
    (private_root / "staging").symlink_to(
        external_root,
        target_is_directory=True,
    )

    with pytest.raises(
        WorkspaceRecoveryError,
        match="coordinator directory must not be a symbolic link",
    ):
        DashboardWorkspacePublication(workspace_root)

    assert list(external_root.iterdir()) == []


def test_startup_recovery_does_not_restore_symlinked_retired_generation(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspaces"
    live_root = _write_project(workspace_root)
    live_project_sha256 = hashlib.sha256(
        (live_root / "project.json").read_bytes()
    ).hexdigest()
    victim = tmp_path / "external-old-generation"
    live_root.rename(victim)
    session_id = "c" * 32
    session_root = (
        workspace_root
        / ".scout-connected-preparation"
        / "staging"
        / f"{PROJECT_ID}.{session_id}"
    )
    session_root.mkdir(parents=True)
    (session_root / ".retired-forged").symlink_to(
        victim,
        target_is_directory=True,
    )
    journal_path = _journal_path(workspace_root)
    journal_path.parent.mkdir(parents=True)
    journal_path.write_text(
        json.dumps(
            {
                "schemaVersion": "dashboardWorkspacePublicationJournal.v1",
                "projectId": PROJECT_ID,
                "sessionId": session_id,
                "sessionRef": session_root.relative_to(
                    workspace_root
                ).as_posix(),
                "state": "prepared",
                "liveProjectSha256": live_project_sha256,
                "stagedProjectSha256": "d" * 64,
                "liveGenerationId": f"legacy:{live_project_sha256}",
                "stagedGenerationId": "e" * 32,
            }
        ),
        encoding="utf-8",
    )

    publication = DashboardWorkspacePublication(workspace_root)

    assert victim.is_dir()
    assert live_root.exists() is False
    assert journal_path.exists()
    assert publication.startup_recovery[PROJECT_ID]["status"] == "blocked"


def test_startup_recovery_rejects_symlinked_live_workspace(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspaces"
    live_root = _write_project(workspace_root)
    live_project_sha256 = hashlib.sha256(
        (live_root / "project.json").read_bytes()
    ).hexdigest()
    victim = tmp_path / "external-live-generation"
    live_root.rename(victim)
    live_root.symlink_to(victim, target_is_directory=True)
    session_id = "f" * 32
    session_root = (
        workspace_root
        / ".scout-connected-preparation"
        / "staging"
        / f"{PROJECT_ID}.{session_id}"
    )
    session_root.mkdir(parents=True)
    journal_path = _journal_path(workspace_root)
    journal_path.parent.mkdir(parents=True)
    journal_path.write_text(
        json.dumps(
            {
                "schemaVersion": "dashboardWorkspacePublicationJournal.v1",
                "projectId": PROJECT_ID,
                "sessionId": session_id,
                "sessionRef": session_root.relative_to(
                    workspace_root
                ).as_posix(),
                "state": "staging",
                "liveProjectSha256": live_project_sha256,
                "stagedProjectSha256": None,
                "liveGenerationId": f"legacy:{live_project_sha256}",
                "stagedGenerationId": None,
            }
        ),
        encoding="utf-8",
    )

    publication = DashboardWorkspacePublication(workspace_root)

    assert victim.is_dir()
    assert live_root.is_symlink()
    assert session_root.is_dir()
    assert journal_path.exists()
    assert publication.startup_recovery[PROJECT_ID]["status"] == "blocked"


def test_dashboard_project_id_parser_locks_only_project_reads() -> None:
    assert (
        dashboard_project_id_from_read_path(
            "GET",
            "/admin/pretrip/projects/fixture-route",
        )
        == "fixture-route"
    )
    assert (
        dashboard_project_id_from_read_path(
            "HEAD",
            "/admin/pretrip/projects/fixture-route/weather",
        )
        == "fixture-route"
    )
    assert (
        dashboard_project_id_from_read_path(
            "POST",
            "/admin/pretrip/projects/fixture-route/connected-preparation",
        )
        is None
    )
    assert dashboard_project_id_from_read_path("GET", "/admin/pretrip/projects") is None


def test_fallback_exchange_restores_old_generation_when_final_rename_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live_root = _write_project(tmp_path / "live")
    staged_root = _write_project(tmp_path / "staged", generation="new")
    original_rename = Path.rename
    rename_count = 0

    def fail_third_rename(source: Path, target: Path) -> Path:
        nonlocal rename_count
        rename_count += 1
        if rename_count == 3:
            raise OSError("simulated final rename failure")
        return original_rename(source, target)

    monkeypatch.setattr(Path, "rename", fail_third_rename)

    with pytest.raises(OSError, match="simulated final rename failure"):
        _locked_rename_exchange(live_root, staged_root)

    assert _read_generation(live_root) == "old"
    assert _read_generation(staged_root) == "new"
