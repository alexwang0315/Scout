from __future__ import annotations

import json
import shutil
from pathlib import Path

from pretrip_artifact_manifest import build_pretrip_artifact_manifest
from pretrip_route_context_collection import (
    ROUTE_CONTEXT_BRIEFING_REF,
    ROUTE_CONTEXT_CRAWL_SEED_PLAN_REF,
    ROUTE_CONTEXT_EVIDENCE_REF,
    ROUTE_CONTEXT_PACK_REF,
    ROUTE_CONTEXT_POINTS_REF,
    ROUTE_CONTEXT_SOURCE_MANIFEST_REF,
    collect_pretrip_route_context,
)
from scout_agent_cli import run_scout_agent_cli
from scout_route_context_tool import assess_scout_route_context
from tools.verify_pretrip_workspace_spec_alignment import _check_route_context_refs


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
    assert result["route_context_point_count"] >= 6
    assert result["crawl_seed_count"] > result["route_context_point_count"]
    assert "route_note_candidate" not in result["counts"]["by_evidence_type"]
    assert result["boundary"]["candidate_only"] is True
    assert result["boundary"]["runtime_safety_truth"] is False
    assert result["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert result["outputs"]["route_context_evidence_ref"] == ROUTE_CONTEXT_EVIDENCE_REF
    assert result["outputs"]["route_context_source_manifest_ref"] == ROUTE_CONTEXT_SOURCE_MANIFEST_REF
    assert result["outputs"]["route_context_pack_ref"] == ROUTE_CONTEXT_PACK_REF
    assert result["outputs"]["route_context_crawl_seed_plan_ref"] == ROUTE_CONTEXT_CRAWL_SEED_PLAN_REF
    assert result["outputs"]["route_context_briefing_ref"] == ROUTE_CONTEXT_BRIEFING_REF
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
    source_manifest_path = project_root / ROUTE_CONTEXT_SOURCE_MANIFEST_REF
    pack_path = project_root / ROUTE_CONTEXT_PACK_REF
    crawl_seed_plan_path = project_root / ROUTE_CONTEXT_CRAWL_SEED_PLAN_REF
    briefing_path = project_root / ROUTE_CONTEXT_BRIEFING_REF
    points_path = project_root / ROUTE_CONTEXT_POINTS_REF
    assert evidence_path.is_file()
    assert source_manifest_path.is_file()
    assert pack_path.is_file()
    assert crawl_seed_plan_path.is_file()
    assert briefing_path.is_file()
    assert points_path.is_file()

    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    crawl_seed_plan = json.loads(crawl_seed_plan_path.read_text(encoding="utf-8"))
    briefing = briefing_path.read_text(encoding="utf-8")
    points = json.loads(points_path.read_text(encoding="utf-8"))
    project = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    labels = {point["display_label"] for point in points["points"]}
    assert evidence["artifact_kind"] == "pretrip_route_context_evidence"
    assert source_manifest["artifact_kind"] == "pretrip_route_context_source_manifest"
    assert pack["artifact_kind"] == "pretrip_route_context_pack"
    assert crawl_seed_plan["artifact_kind"] == "pretrip_route_context_crawl_seed_plan"
    assert points["artifact_kind"] == "pretrip_route_context_points"
    assert evidence["route_context_points_ref"] == ROUTE_CONTEXT_POINTS_REF
    assert evidence["source_manifest_ref"] == ROUTE_CONTEXT_SOURCE_MANIFEST_REF
    assert evidence["route_context_pack_ref"] == ROUTE_CONTEXT_PACK_REF
    assert evidence["crawl_seed_plan_ref"] == ROUTE_CONTEXT_CRAWL_SEED_PLAN_REF
    assert pack["source_manifest_ref"] == ROUTE_CONTEXT_SOURCE_MANIFEST_REF
    assert pack["route_context_points_ref"] == ROUTE_CONTEXT_POINTS_REF
    assert pack["crawl_seed_plan_ref"] == ROUTE_CONTEXT_CRAWL_SEED_PLAN_REF
    assert pack["route_summary"]["raw_route_points_embedded"] is False
    assert crawl_seed_plan["route_note_seed_policy"]["route_notes_are_conclusion"] is False
    assert crawl_seed_plan["route_note_seed_policy"]["route_notes_are_seed_material"] is True
    assert crawl_seed_plan["route_note_seed_count"] > 0
    assert "奇萊-南華" in crawl_seed_plan["route_keywords"]
    assert all("每日記錄" not in keyword for keyword in crawl_seed_plan["route_keywords"])
    assert "Scout Route Context Briefing" in briefing
    assert "Route notes are treated as seed material" in briefing
    assert source_manifest["cache_policy"]["live_fetch_performed"] is False
    assert project["route_context_evidence_ref"] == ROUTE_CONTEXT_EVIDENCE_REF
    assert project["route_context_source_manifest_ref"] == ROUTE_CONTEXT_SOURCE_MANIFEST_REF
    assert project["route_context_pack_ref"] == ROUTE_CONTEXT_PACK_REF
    assert project["route_context_crawl_seed_plan_ref"] == ROUTE_CONTEXT_CRAWL_SEED_PLAN_REF
    assert project["route_context_briefing_ref"] == ROUTE_CONTEXT_BRIEFING_REF
    assert project["route_context_points_ref"] == ROUTE_CONTEXT_POINTS_REF
    assert project["route_context_point_count"] == points["point_count"]
    assert project["route_context_crawl_seed_count"] == crawl_seed_plan["seed_count"]
    assert project["route_context_collection_schema_version"] == "route_context_collection.v1"
    assert points["boundary"]["runtime_safety_truth"] is False
    assert "route_note_candidate" not in points["counts"]["by_evidence_type"]
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
    assert heishuitang["observation_score"]["candidate_only"] is True
    assert heishuitang["source_freshness"]["requires_refresh_before_runtime_truth"] is True
    assert heishuitang["display_policy"]["show_label"] is True

    artifact_manifest = build_pretrip_artifact_manifest(project_root / "project.json").to_dict()
    by_kind = {
        artifact["artifact_kind"]: artifact
        for artifact in artifact_manifest["artifacts"]
        if artifact["source"] == "project"
    }
    assert by_kind["route_context_evidence"]["route_context_point_count"] == points["point_count"]
    assert by_kind["route_context_source_manifest"]["live_fetch_performed"] is False
    assert by_kind["route_context_pack"]["query_mode"] == "cache_first_tool_second"
    assert by_kind["route_context_crawl_seed_plan"]["route_notes_are_conclusion"] is False
    assert by_kind["route_context_briefing"]["content_type"] == "text/html"
    assert by_kind["route_context_points"]["point_count"] == points["point_count"]

    verifier_errors: list[str] = []
    route_context_summary = _check_route_context_refs(
        project_root,
        project,
        verifier_errors,
    )
    assert verifier_errors == []
    assert route_context_summary["available"] is True
    assert route_context_summary["point_count"] == points["point_count"]
    assert route_context_summary["crawl_seed_count"] == crawl_seed_plan["seed_count"]
    assert route_context_summary["route_note_seed_count"] == crawl_seed_plan["route_note_seed_count"]
    assert route_context_summary["briefing_available"] is True
    assert route_context_summary["live_fetch_performed"] is False
    assert route_context_summary["runtime_safety_truth"] is False


def test_builtin_route_context_collect_tool_runs_with_authorization(tmp_path: Path) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(FIXTURE_PROJECT, project_root)
    request = tmp_path / "route-context-collect.request.json"
    request.write_text(
        json.dumps(
            {
                "project_root": str(project_root),
                "limit_route_notes": 10,
                "route_keyword": "奇萊-南華",
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
    assert (project_root / ROUTE_CONTEXT_SOURCE_MANIFEST_REF).is_file()
    assert (project_root / ROUTE_CONTEXT_PACK_REF).is_file()
    assert (project_root / ROUTE_CONTEXT_CRAWL_SEED_PLAN_REF).is_file()
    assert (project_root / ROUTE_CONTEXT_BRIEFING_REF).is_file()
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


def test_route_context_collection_marks_sensitive_cultural_points(tmp_path: Path) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(FIXTURE_PROJECT, project_root)
    route_notes_path = project_root / "candidates" / "route_note_candidates.json"
    route_notes = json.loads(route_notes_path.read_text(encoding="utf-8"))
    route_notes["candidates"].append(
        {
            "candidate_id": "route_note.fixture.sensitive_old_tribe_path",
            "candidate_only": True,
            "confidence": "medium",
            "lat": 24.01,
            "lon": 121.24,
            "name": "舊社獵徑禁忌地",
            "normalized_note": "舊社獵徑禁忌地",
            "note_category": "hazard_hint",
            "review_state": "needs_review",
            "route_note_freshness": "unknown",
            "runtime_safety_truth": False,
        }
    )
    route_notes_path.write_text(
        json.dumps(route_notes, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    collect_pretrip_route_context(
        project_root,
        dry_run=False,
        limit_route_notes=120,
        route_note_point_policy="promote_representative",
        collected_at="2026-06-15T00:00:00Z",
    )

    points = json.loads((project_root / ROUTE_CONTEXT_POINTS_REF).read_text(encoding="utf-8"))
    sensitive = next(
        point for point in points["points"] if point["display_label"] == "舊社獵徑禁忌地"
    )
    assert sensitive["sensitivity_level"] == "restricted"
    assert sensitive["display_policy"]["show_exact_coordinate"] is False
    assert sensitive["display_policy"]["requires_human_review_before_display"] is True
    assert "cultural" in sensitive["sec6_layers"]
    assert points["counts"]["by_sensitivity_level"]["restricted"] >= 1
