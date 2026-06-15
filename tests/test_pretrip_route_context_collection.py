from __future__ import annotations

import json
import shutil
from pathlib import Path

from pretrip_route_context_collection import (
    ROUTE_CONTEXT_EVIDENCE_REF,
    ROUTE_CONTEXT_POINTS_REF,
    collect_pretrip_route_context,
)
from scout_agent_cli import run_scout_agent_cli
from scout_route_context_tool import assess_scout_route_context


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PROJECT = REPO_ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
MANIFEST_DIR = REPO_ROOT / "tools" / "scout_agent_tool_manifests"


def test_route_context_collection_dry_run_uses_sec6_sources_without_writes() -> None:
    result = collect_pretrip_route_context(
        FIXTURE_PROJECT,
        dry_run=True,
        limit_route_notes=12,
        collected_at="2026-06-15T00:00:00Z",
    )

    assert result["status"] == "completed"
    assert result["dry_run"] is True
    assert result["writes_performed"] is False
    assert result["route_context_point_count"] >= 15
    assert result["boundary"]["candidate_only"] is True
    assert result["boundary"]["runtime_safety_truth"] is False
    assert result["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert result["outputs"]["route_context_evidence_ref"] == ROUTE_CONTEXT_EVIDENCE_REF
    assert result["outputs"]["route_context_points_ref"] == ROUTE_CONTEXT_POINTS_REF

    source_status = {
        source["source_kind"]: source["status"] for source in result["source_report"]
    }
    assert source_status["mcp_candidates"] == "loaded"
    assert source_status["named_point_evidence"] == "loaded"
    assert source_status["route_note_candidates"] == "loaded"
    assert source_status["web_case_evidence"] == "missing"
    assert source_status["raster_label_evidence"] == "missing"


def test_route_context_collection_writes_workspace_layout_outputs(tmp_path: Path) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(FIXTURE_PROJECT, project_root)

    result = collect_pretrip_route_context(
        project_root,
        dry_run=False,
        limit_route_notes=16,
        collected_at="2026-06-15T00:00:00Z",
    )

    assert result["writes_performed"] is True
    evidence_path = project_root / ROUTE_CONTEXT_EVIDENCE_REF
    points_path = project_root / ROUTE_CONTEXT_POINTS_REF
    assert evidence_path.is_file()
    assert points_path.is_file()

    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    points = json.loads(points_path.read_text(encoding="utf-8"))
    labels = {point["display_label"] for point in points["points"]}
    assert evidence["artifact_kind"] == "pretrip_route_context_evidence"
    assert points["artifact_kind"] == "pretrip_route_context_points"
    assert evidence["route_context_points_ref"] == ROUTE_CONTEXT_POINTS_REF
    assert points["boundary"]["runtime_safety_truth"] is False
    assert "黑水塘" in labels
    assert "大崩壁" in labels
    assert "雲海保線所" in labels
    assert points["counts"]["by_evidence_type"]["major_critical_point"] == 6
    named_source = next(
        source
        for source in evidence["source_report"]
        if source["source_kind"] == "named_point_evidence"
    )
    assert named_source["loaded_count"] == 8
    heishuitang = next(point for point in points["points"] if point["display_label"] == "黑水塘")
    assert "named_point" in heishuitang["evidence_families"]
    assert "major_critical_point" in heishuitang["merged_evidence_types"]


def test_builtin_route_context_collect_tool_runs_with_authorization(tmp_path: Path) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(FIXTURE_PROJECT, project_root)
    request = tmp_path / "route-context-collect.request.json"
    request.write_text(
        json.dumps(
            {
                "project_root": str(project_root),
                "limit_route_notes": 10,
                "collected_at": "2026-06-15T00:00:00Z",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    blocked_exit, blocked_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.pretrip.route_context_collect",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--json",
        ]
    )
    assert blocked_exit == 2
    assert blocked_payload["status"] == "blocked"
    assert not (project_root / ROUTE_CONTEXT_POINTS_REF).exists()

    exit_code, payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.pretrip.route_context_collect",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--authorized-by",
            "operator.alex",
            "--json",
        ]
    )

    assert exit_code == 0
    assert payload["status"] == "completed"
    assert payload["effects"]["workspace_write_count"] == 1
    output = json.loads(payload["outputs"]["stdout"])
    assert output["artifact_kind"] == "scout_pretrip_route_context_collect_tool_output"
    assert output["result"]["writes_performed"] is True
    assert output["result"]["boundary"]["live_safety_api_calls_allowed"] is False
    assert (project_root / ROUTE_CONTEXT_EVIDENCE_REF).is_file()
    assert (project_root / ROUTE_CONTEXT_POINTS_REF).is_file()


def test_route_context_assessor_reads_collected_canonical_points(tmp_path: Path) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(FIXTURE_PROJECT, project_root)
    collect_pretrip_route_context(
        project_root,
        dry_run=False,
        limit_route_notes=8,
        collected_at="2026-06-15T00:00:00Z",
    )

    result = assess_scout_route_context(
        project_root,
        query="黑水塘附近有什麼路線脈絡",
        route_context_path=ROUTE_CONTEXT_POINTS_REF,
    )

    assert result["answerability"] == "route_context_available"
    assert result["route_context"]["candidate_only"] is True
    assert result["route_context"]["runtime_safety_truth"] is False
    assert result["source_report"][0]["source_kind"] == "route_context_points"
    assert "黑水塘" in {item["label"] for item in result["results"]}
