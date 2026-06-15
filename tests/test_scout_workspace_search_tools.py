from __future__ import annotations

from pathlib import Path

from scout_workspace_search_tools import (
    EVIDENCE_FULLTEXT_TOOL_ID,
    MAJOR_POINT_TOOL_ID,
    ROUTE_STRUCTURE_TOOL_ID,
    WORKSPACE_CATALOG_TOOL_ID,
    search_project_evidence_fulltext,
    search_project_major_points,
    search_project_route_structure,
    search_project_workspace_catalog,
)


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"


def test_workspace_catalog_search_lists_local_artifact_families() -> None:
    result = search_project_workspace_catalog(
        PROJECT_ROOT,
        query="workspace route terrain risk tools",
        limit=8,
    )

    assert result["tool_id"] == WORKSPACE_CATALOG_TOOL_ID
    assert result["status"] == "completed"
    assert result["project_id"] == "chilai_nanhua_day1"
    assert result["summaries"]["artifact_ref_count"] >= 60
    assert result["summaries"]["domains"]["route"]["existing"] >= 1
    assert result["summaries"]["domains"]["terrain"]["existing"] >= 1
    assert result["summaries"]["domains"]["risk"]["existing"] >= 1
    assert result["boundary"]["runtime_safety_truth"] is False


def test_route_structure_search_answers_cp_count_and_lookup() -> None:
    count_result = search_project_route_structure(
        PROJECT_ROOT,
        query="有多少個 CP?",
        limit=3,
    )
    cp_result = search_project_route_structure(
        PROJECT_ROOT,
        query="CP 002 在哪?",
        limit=5,
    )

    assert count_result["tool_id"] == ROUTE_STRUCTURE_TOOL_ID
    assert count_result["summaries"]["checkpoint_count"] == 124
    assert count_result["summaries"]["segment_count"] == 123
    assert count_result["route_summary"]["distance_km"] == 55.175
    assert any(item["candidate_id"] == "cp.002" for item in cp_result["results"])
    assert cp_result["boundary"]["phase1_safety_mutation_allowed"] is False


def test_major_point_search_finds_heishuitang_near_cp002() -> None:
    result = search_project_major_points(
        PROJECT_ROOT,
        query="黑水塘在第幾 CP 附近?",
        limit=5,
    )

    assert result["tool_id"] == MAJOR_POINT_TOOL_ID
    assert result["result_count"] >= 1
    first = result["results"][0]
    assert first["candidate_id"] == "mcp.heishuitang.002"
    assert first["label"] == "黑水塘"
    assert first["nearest_cp_candidate_id"] == "cp.002"
    assert first["support_status"] == "supported"
    assert first["candidate_only"] is True
    assert first["runtime_safety_truth"] is False


def test_major_point_search_treats_water_refill_as_water_source_lookup() -> None:
    result = search_project_major_points(
        PROJECT_ROOT,
        query="哪裡可以補水？",
        limit=5,
    )

    assert result["tool_id"] == MAJOR_POINT_TOOL_ID
    assert result["answerability"] == "major_points_available"
    assert result["result_count"] >= 1
    assert result["results"][0]["label"] == "黑水塘"
    assert "water_source" in result["results"][0]["point_classes"]
    assert result["field_answer"].startswith("候選補水/水源點：黑水塘")
    assert "不是現場取水" in result["field_answer"]
    assert result["boundary"]["runtime_safety_truth"] is False


def test_evidence_fulltext_wraps_local_evidence_index() -> None:
    result = search_project_evidence_fulltext(
        PROJECT_ROOT,
        query="黑水塘",
        limit=4,
    )

    assert result["tool_id"] == EVIDENCE_FULLTEXT_TOOL_ID
    assert result["status"] == "completed"
    assert result["result_count"] >= 1
    assert any(item["record_id"] == "mcp.heishuitang.002" for item in result["results"])
    assert result["boundary"]["local_evidence_only"] is True
    assert result["boundary"]["runtime_safety_truth"] is False
