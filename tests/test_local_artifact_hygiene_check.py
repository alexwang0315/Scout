from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from local_artifact_hygiene_check import (
    GitStatusEntry,
    build_local_artifact_hygiene_check,
    parse_porcelain_status_z,
)


ROOT = Path(__file__).resolve().parents[1]


def test_unstaged_tracked_local_artifact_is_allowed_but_reported() -> None:
    result = build_local_artifact_hygiene_check(
        ROOT,
        status_entries=[GitStatusEntry(xy=" M", paths=("trajectory_map.png",))],
    )

    assert result["ok"] is True
    assert result["dirty_local_only_paths"] == ["trajectory_map.png"]
    assert result["unstaged_local_only_paths"] == ["trajectory_map.png"]
    assert result["staged_local_only_paths"] == []
    assert result["missing_required_artifacts"] == []
    assert result["boundary"]["mutates_worktree"] is False
    assert result["boundary"]["reverts_files"] is False


def test_staged_local_artifact_fails_hygiene_gate() -> None:
    result = build_local_artifact_hygiene_check(
        ROOT,
        status_entries=[GitStatusEntry(xy="M ", paths=("trajectory_map.png",))],
    )

    assert result["ok"] is False
    assert result["dirty_local_only_paths"] == ["trajectory_map.png"]
    assert result["staged_local_only_paths"] == ["trajectory_map.png"]
    assert result["missing_required_artifacts"] == [
        "local_only_staged:trajectory_map.png"
    ]


def test_forced_added_ignored_directory_file_fails_when_staged() -> None:
    result = build_local_artifact_hygiene_check(
        ROOT,
        status_entries=[
            GitStatusEntry(
                xy="A ",
                paths=("PdrSample/stream Apple Watch 260512 08_52_37.json",),
            ),
        ],
    )

    assert result["ok"] is False
    assert result["staged_local_only_paths"] == [
        "PdrSample/stream Apple Watch 260512 08_52_37.json"
    ]
    assert result["missing_required_artifacts"] == [
        "local_only_staged:PdrSample/stream Apple Watch 260512 08_52_37.json"
    ]


def test_untracked_local_operator_helper_is_reported_without_failing() -> None:
    result = build_local_artifact_hygiene_check(
        ROOT,
        status_entries=[GitStatusEntry(xy="??", paths=("install_skills.sh",))],
    )

    assert result["ok"] is True
    assert result["dirty_local_only_paths"] == ["install_skills.sh"]
    assert result["untracked_local_only_paths"] == ["install_skills.sh"]
    assert result["staged_local_only_paths"] == []


def test_non_local_artifact_status_is_ignored() -> None:
    result = build_local_artifact_hygiene_check(
        ROOT,
        status_entries=[
            GitStatusEntry(xy="M ", paths=("docs/specs/case-study-addition-skill.md",)),
            GitStatusEntry(xy="A ", paths=("tools/pi_ollama_stress.py",)),
        ],
    )

    assert result["ok"] is True
    assert result["dirty_local_only_paths"] == []
    assert result["staged_local_only_paths"] == []
    assert result["status_entries"] == []


def test_porcelain_z_parser_handles_spaces_and_renames() -> None:
    raw = (
        " M trajectory_map.png\0"
        "A  PdrSample/stream Apple Watch 260512 08_52_37.json\0"
        "R  docs/old.png\0trajectory_map.png\0"
    )

    entries = parse_porcelain_status_z(raw)

    assert entries == [
        GitStatusEntry(xy=" M", paths=("trajectory_map.png",)),
        GitStatusEntry(
            xy="A ",
            paths=("PdrSample/stream Apple Watch 260512 08_52_37.json",),
        ),
        GitStatusEntry(xy="R ", paths=("docs/old.png", "trajectory_map.png")),
    ]


def test_cli_reports_current_repo_without_mutating_local_artifacts() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "local_artifact_hygiene_check.py"),
            "--pretty",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    assert completed.returncode == 0, payload
    assert payload["artifact_kind"] == "local_artifact_hygiene_check"
    assert payload["boundary"]["stages_files"] is False
    assert payload["boundary"]["commits_files"] is False
