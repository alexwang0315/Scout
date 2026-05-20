from __future__ import annotations

from pathlib import Path

from scout_pi_docker_build_dry_run import build_docker_build_dry_run_report


ROOT = Path(__file__).resolve().parents[1]


def test_docker_build_dry_run_report_is_ready_without_running_docker() -> None:
    report = build_docker_build_dry_run_report(ROOT)

    assert report.status == "ready_for_manual_docker_build"
    assert report.blockers == []
    assert report.warnings == ["manual_operator_must_run_docker_build"]
    assert report.boundary.dry_run_only is True
    assert report.boundary.docker_build_executed is False
    assert report.boundary.container_started is False
    assert report.boundary.network_calls_performed is False
    assert report.boundary.local_model_start_allowed is False
    assert report.counts.checked_file_count == 4


def test_docker_build_dry_run_blocks_ai_and_future_ladder_terms(tmp_path: Path) -> None:
    for name in ("Dockerfile.pi", "docker-compose.pi.yml", ".dockerignore", "requirements.pi.txt"):
        (tmp_path / name).write_text((ROOT / name).read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "requirements.pi.txt").write_text("fastapi==0.136.1\ntorch==2.0.0\n", encoding="utf-8")
    (tmp_path / "docker-compose.pi.yml").write_text(
        (tmp_path / "docker-compose.pi.yml").read_text(encoding="utf-8") + "\n  ollama:\n",
        encoding="utf-8",
    )

    report = build_docker_build_dry_run_report(tmp_path)

    assert report.status == "blocked"
    assert "forbidden_requirement:torch" in report.blockers
    assert "forbidden_term:ollama" in report.blockers
    assert report.boundary.docker_build_executed is False
