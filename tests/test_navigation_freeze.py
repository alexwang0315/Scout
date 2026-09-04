from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.verify_navigation_freeze import (
    BASELINE_PATH,
    ROOT,
    protected_inventory,
    verify_freeze,
)


def _write(root: Path, path: str, content: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _baseline(root: Path) -> dict:
    baseline = {
        "schema_version": "scout.navigation_freeze.v1",
        "status": "frozen",
        "baseline_source": "current_worktree_including_uncommitted_changes",
        "approval_required_before_edits": True,
        "files": protected_inventory(root),
    }
    _write(root, BASELINE_PATH, json.dumps(baseline))
    return baseline


@pytest.fixture
def frozen_repo(tmp_path: Path) -> Path:
    _write(tmp_path, "docs/admin/scout-dashboard-v0.1.html", "Navigation and Weather\n")
    _write(tmp_path, "terrain_route_hypothesis.py", "CANDIDATE_ONLY = True\n")
    _write(tmp_path, "workspace_terrain_dem.py", "NATIVE_RESOLUTION = True\n")
    _write(tmp_path, "tools/run_dashboard_workspace.sh", "start_dashboard\n")
    _baseline(tmp_path)
    return tmp_path


def test_current_navigation_freeze_is_temporarily_report_only() -> None:
    report = verify_freeze(ROOT)
    assert report["ok"], report
    assert report["status"] == "NAVIGATION_FREEZE_SUSPENDED"
    assert report["enforcement"] == "report_only"
    assert report["approval_granted"] is False
    assert report["runtime_safety_truth"] is False


def test_freeze_does_not_need_git_or_a_clean_worktree(frozen_repo: Path) -> None:
    assert not (frozen_repo / ".git").exists()
    report = verify_freeze(frozen_repo, enforce=True)
    assert report["ok"]
    assert report["status"] == "FROZEN_UNCHANGED"


def test_other_page_in_an_independent_file_is_allowed(frozen_repo: Path) -> None:
    _write(frozen_repo, "docs/admin/weather-details.html", "Weather only\n")
    assert verify_freeze(frozen_repo)["ok"]


@pytest.mark.parametrize(
    "path",
    [
        "docs/admin/scout-dashboard-v0.1.html",
        "terrain_route_hypothesis.py",
        "workspace_terrain_dem.py",
        "tools/run_dashboard_workspace.sh",
    ],
)
def test_changed_navigation_and_shared_entrypoints_require_approval(
    frozen_repo: Path,
    path: str,
) -> None:
    _write(frozen_repo, path, "changed for another page\n")
    report = verify_freeze(frozen_repo, enforce=True)
    assert not report["ok"]
    assert report["status"] == "NAVIGATION_APPROVAL_REQUIRED"
    assert report["changes"] == [{"path": path, "change": "modified"}]
    assert report["approval_granted"] is False


@pytest.mark.parametrize(
    "path",
    [
        "navigation_terrain_new_adapter.py",
        "terrain_route_new_strategy.py",
        "qgis_new_worker.py",
        "tests/test_navigation_new_contract.py",
    ],
)
def test_new_navigation_files_cannot_escape_the_inventory(
    frozen_repo: Path,
    path: str,
) -> None:
    _write(frozen_repo, path, "new code\n")
    assert verify_freeze(frozen_repo)["changes"] == [{"path": path, "change": "added"}]


def test_deleted_protected_file_is_rejected(frozen_repo: Path) -> None:
    (frozen_repo / "terrain_route_hypothesis.py").unlink()
    assert verify_freeze(frozen_repo)["changes"] == [
        {"path": "terrain_route_hypothesis.py", "change": "deleted"},
    ]


def test_new_or_changed_gate_cannot_silently_disable_checks(frozen_repo: Path) -> None:
    path = ".github/workflows/navigation-freeze.yml"
    _write(frozen_repo, path, "disabled\n")
    assert verify_freeze(frozen_repo)["changes"] == [{"path": path, "change": "added"}]


@pytest.mark.parametrize("content", ["{", "[]", "{}", '{"files": {}}'])
def test_malformed_or_empty_baseline_fails_closed(
    frozen_repo: Path, content: str
) -> None:
    _write(frozen_repo, BASELINE_PATH, content)
    report = verify_freeze(frozen_repo)
    assert not report["ok"]
    assert report["status"] == "INVALID_BASELINE"


def test_missing_baseline_fails_closed(frozen_repo: Path) -> None:
    (frozen_repo / BASELINE_PATH).unlink()
    assert verify_freeze(frozen_repo)["status"] == "INVALID_BASELINE"


@pytest.mark.parametrize("value", [False, "true", 1, None])
def test_approval_requirement_cannot_be_disabled(
    frozen_repo: Path, value: object
) -> None:
    baseline = json.loads((frozen_repo / BASELINE_PATH).read_text())
    baseline["approval_required_before_edits"] = value
    _write(frozen_repo, BASELINE_PATH, json.dumps(baseline))
    assert verify_freeze(frozen_repo)["status"] == "INVALID_BASELINE"


def test_unreadable_protected_file_fails_closed(frozen_repo: Path, monkeypatch) -> None:
    from tools import verify_navigation_freeze

    def unavailable(*args):
        raise OSError("cannot inspect protected file")

    monkeypatch.setattr(verify_navigation_freeze, "_file_hash", unavailable)
    report = verify_freeze(frozen_repo)
    assert report["status"] == "PROTECTED_FILE_UNAVAILABLE"
    assert report["approval_granted"] is False


@pytest.mark.parametrize(
    "path", ["../outside.py", "/etc/passwd", "a/../b.py", "a\\b.py"]
)
def test_baseline_cannot_reference_files_outside_repo(
    frozen_repo: Path, path: str
) -> None:
    baseline = json.loads((frozen_repo / BASELINE_PATH).read_text())
    baseline["files"][path] = hashlib.sha256(b"anything").hexdigest()
    _write(frozen_repo, BASELINE_PATH, json.dumps(baseline))
    assert verify_freeze(frozen_repo)["status"] == "INVALID_BASELINE"


def test_symlink_to_an_identical_file_is_not_accepted(frozen_repo: Path) -> None:
    path = frozen_repo / "terrain_route_hypothesis.py"
    copy = frozen_repo / "elsewhere.py"
    copy.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(copy)
    assert verify_freeze(frozen_repo)["status"] == "PROTECTED_FILE_UNAVAILABLE"


def test_inventory_and_cli_are_deterministic_and_read_only(frozen_repo: Path) -> None:
    _write(frozen_repo, "terrain_route_hypothesis.py", "changed\n")
    before = protected_inventory(frozen_repo)
    baseline_before = (frozen_repo / BASELINE_PATH).read_bytes()
    reports = []
    for _ in range(2):
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools/verify_navigation_freeze.py"),
                "--repo-root",
                str(frozen_repo),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        reports.append(json.loads(result.stdout))
    assert reports[0] == reports[1]
    assert reports[0]["status"] == "NAVIGATION_FREEZE_SUSPENDED"
    assert reports[0]["changes"] == verify_freeze(frozen_repo, enforce=True)["changes"]
    assert reports[0]["changes"] == [
        {"path": "terrain_route_hypothesis.py", "change": "modified"},
    ]
    assert before == protected_inventory(frozen_repo)
    assert baseline_before == (frozen_repo / BASELINE_PATH).read_bytes()


def test_strict_cli_returns_nonzero_for_source_drift(frozen_repo: Path) -> None:
    _write(frozen_repo, "terrain_route_hypothesis.py", "changed\n")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/verify_navigation_freeze.py"),
            "--repo-root",
            str(frozen_repo),
            "--enforce",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1
    assert json.loads(result.stdout)["status"] == "NAVIGATION_APPROVAL_REQUIRED"


def test_baseline_cannot_auto_approve_a_change(frozen_repo: Path) -> None:
    baseline = json.loads((frozen_repo / BASELINE_PATH).read_text())
    baseline["approval_granted"] = True
    _write(frozen_repo, BASELINE_PATH, json.dumps(baseline))
    _write(frozen_repo, "terrain_route_hypothesis.py", "changed\n")
    report = verify_freeze(frozen_repo, enforce=True)
    assert not report["ok"]
    assert report["approval_granted"] is False
