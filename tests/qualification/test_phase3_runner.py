from __future__ import annotations

import json
from pathlib import Path

from tests.qualification.phase3_runner import _verify_prerequisite_files
from tools.verify_dashboard_internal_qualification import main


ROOT = Path(__file__).resolve().parents[2]


def test_phase3_prerequisite_packet_identities_are_exact() -> None:
    assert _verify_prerequisite_files(ROOT) == ()


def test_release_mode_requires_explicit_workspace_inventory(
    tmp_path: Path,
    capsys: object,
) -> None:
    exit_code = main(
        [
            "--release",
            "--execution-dir",
            str(tmp_path / "execution"),
            "--output-dir",
            str(tmp_path / "result"),
        ]
    )

    assert exit_code == 2
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "--release requires --workspace-inventory" in captured.err
    assert not (tmp_path / "execution").exists()
    assert not (tmp_path / "result").exists()


def test_phase3_cli_modes_are_mutually_exclusive(
    tmp_path: Path,
    capsys: object,
) -> None:
    exit_code = main(
        [
            "--all",
            "--domain",
            "dashboard-shell-control",
            "--execution-dir",
            str(tmp_path / "execution"),
            "--output-dir",
            str(tmp_path / "result"),
        ]
    )

    assert exit_code == 2
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "choose exactly one" in captured.err


def test_focused_dashboard_shell_cli_runs_real_replay_and_finalizes(
    tmp_path: Path,
    capsys: object,
) -> None:
    result_root = tmp_path / "result"
    exit_code = main(
        [
            "--domain",
            "dashboard-shell-control",
            "--execution-dir",
            str(tmp_path / "execution"),
            "--output-dir",
            str(result_root),
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert captured.out.startswith("PASS run=dashboard.phase3.focused.dashboard-shell-control")
    payload = json.loads(
        (result_root / "qualification-report.json").read_text(encoding="utf-8")
    )
    report = payload["report"]
    assert report["domain_id"] == "dashboard-shell-control"
    assert report["verdict"] == "pass"
    assert report["complete"] is True
    assert (result_root / "qualification-report.junit.xml").is_file()
    assert (result_root / "qualification-report.txt").is_file()
