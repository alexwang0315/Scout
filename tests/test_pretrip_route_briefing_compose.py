from __future__ import annotations

import json
from pathlib import Path

from pretrip_route_briefing_compose import compose_pretrip_route_briefing
from scout_agent_cli import run_scout_agent_cli


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = REPO_ROOT / "tools" / "scout_agent_tool_manifests"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "pretrip" / "route_briefing" / "chilai_nanhua_research.json"


def test_compose_route_briefing_dry_run_keeps_candidate_boundary(tmp_path: Path) -> None:
    output = tmp_path / "briefing.html"

    result = compose_pretrip_route_briefing(FIXTURE, output_path=output, dry_run=True)

    assert result["status"] == "completed"
    assert result["dry_run"] is True
    assert result["writes_performed"] is False
    assert result["source_count"] == 4
    assert result["context_layer_count"] == 5
    assert result["boundary"]["candidate_only"] is True
    assert result["boundary"]["runtime_safety_truth"] is False
    assert result["boundary"]["network_calls_made"] is False
    assert "奇萊南華登山活動簡報" in result["html_preview"]
    assert not output.exists()


def test_route_briefing_tool_blocks_without_authorization(tmp_path: Path) -> None:
    output = tmp_path / "briefing.html"

    exit_code, payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.pretrip.route_briefing_compose",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(FIXTURE),
            "--output",
            str(output),
            "--json",
        ]
    )

    assert exit_code == 2
    assert payload["status"] == "blocked"
    assert "requires explicit authorization" in payload["warnings"][0]
    assert not output.exists()


def test_route_briefing_tool_dry_run_and_authorized_write(tmp_path: Path) -> None:
    output = tmp_path / "briefing.html"

    dry_exit, dry_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.pretrip.route_briefing_compose",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(FIXTURE),
            "--output",
            str(output),
            "--dry-run",
            "--json",
        ]
    )
    dry_stdout = json.loads(dry_payload["outputs"]["stdout"])

    assert dry_exit == 0
    assert dry_stdout["writes_performed"] is False
    assert dry_stdout["boundary"]["network_calls_made"] is False
    assert not output.exists()

    write_exit, write_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.pretrip.route_briefing_compose",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(FIXTURE),
            "--output",
            str(output),
            "--authorized-by",
            "operator.local",
            "--json",
        ]
    )
    write_stdout = json.loads(write_payload["outputs"]["stdout"])

    assert write_exit == 0
    assert write_payload["effects"]["workspace_write_count"] == 1
    assert write_stdout["writes_performed"] is True
    assert write_stdout["boundary"]["runtime_safety_truth"] is False
    assert output.exists()
    html = output.read_text(encoding="utf-8")
    assert "奇萊南華登山活動簡報" in html
    assert "Scout pretrip route briefing" in html
