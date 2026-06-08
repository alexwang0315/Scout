from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scout_agent_kb import (
    build_local_evidence_index,
    load_local_evidence_index,
    query_local_evidence_index,
    query_local_evidence_sqlite_index,
    query_project_local_evidence,
    write_local_evidence_index,
    write_local_evidence_sqlite_index,
)


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"


def test_local_evidence_index_builds_from_pretrip_project_without_raw_payloads() -> None:
    index = build_local_evidence_index(PROJECT_ROOT)

    assert index.artifact_kind == "scout_local_evidence_index"
    assert index.project_id == "chilai_nanhua_day1"
    assert index.record_count > 100
    assert {record.evidence_type for record in index.records} >= {
        "pretrip_route_summary",
        "pretrip_checkpoint_candidate",
        "pretrip_segment_candidate",
        "pretrip_route_note_candidate",
        "pretrip_review_queue_item",
        "pretrip_reviewed_spatial_imprint",
        "pretrip_spatial_imprint_candidate",
        "pretrip_mcp_named_point",
        "pretrip_major_critical_point_candidate",
        "pretrip_mcp_cp_support_reconciliation",
    }
    payload = index.model_dump_json()
    assert "<trkpt" not in payload.lower()
    assert "raw_gpx" not in payload
    assert "/safety/" not in payload
    assert index.boundary.local_evidence_only is True
    assert index.boundary.phase1_safety_mutation_allowed is False


def test_local_evidence_query_finds_hazard_route_note_with_source_refs() -> None:
    result = query_project_local_evidence(
        PROJECT_ROOT,
        query="大崩塌",
        limit=3,
        evidence_types={"pretrip_route_note_candidate"},
    )

    assert result.artifact_kind == "scout_local_evidence_query_result"
    assert result.result_count >= 1
    first = result.results[0]
    assert first["record_id"] == "route_note.golden_route.wpt_051"
    assert "大崩塌" in first["snippet"]
    assert first["source_path"] == "candidates/route_note_candidates.json"
    assert first["metadata"]["note_category"] == "hazard_hint"
    assert first["boundary"]["live_safety_api_calls_allowed"] is False


def test_local_evidence_query_finds_mcp_candidate_and_cp_support() -> None:
    candidate_result = query_project_local_evidence(
        PROJECT_ROOT,
        query="黑水塘",
        limit=3,
        evidence_types={"pretrip_major_critical_point_candidate"},
    )
    support_result = query_project_local_evidence(
        PROJECT_ROOT,
        query="黑水塘 cp",
        limit=3,
        evidence_types={"pretrip_mcp_cp_support_reconciliation"},
    )
    named_point_result = query_project_local_evidence(
        PROJECT_ROOT,
        query="黑水塘營地",
        limit=3,
        evidence_types={"pretrip_mcp_named_point"},
    )

    assert candidate_result.result_count >= 1
    candidate = candidate_result.results[0]
    assert candidate["record_id"] == "mcp.heishuitang.002"
    assert candidate["metadata"]["nearest_cp_candidate_id"] == "cp.002"
    assert candidate["metadata"]["runtime_safety_truth"] is False

    assert support_result.result_count >= 1
    support = support_result.results[0]
    assert support["record_id"] == "mcp.heishuitang.002"
    assert support["metadata"]["support_status"] == "supported"
    assert support["metadata"]["nearest_cp_candidate_id"] == "cp.002"
    assert support["metadata"]["runtime_safety_truth"] is False

    assert named_point_result.result_count >= 1
    named_point = named_point_result.results[0]
    assert named_point["record_id"] == "np.heishuitang"
    assert named_point["metadata"]["canonical_name"] == "黑水塘"
    assert named_point["metadata"]["runtime_safety_truth"] is False


def test_local_evidence_query_handles_cjk_natural_language_question() -> None:
    result = query_project_local_evidence(
        PROJECT_ROOT,
        query="大崩塌有什麼風險？",
        limit=3,
    )

    assert result.result_count >= 1
    assert any("大崩塌" in item["snippet"] for item in result.results)
    assert result.boundary.local_evidence_only is True
    assert result.boundary.live_safety_api_calls_allowed is False


def test_local_evidence_index_round_trips_as_json(tmp_path: Path) -> None:
    index_path = tmp_path / "local-evidence-index.json"
    index = build_local_evidence_index(PROJECT_ROOT)
    index_path.write_text(index.model_dump_json(), encoding="utf-8")

    loaded = load_local_evidence_index(index_path)
    result = query_local_evidence_index(loaded, query="獸俓", limit=1)

    assert loaded.record_count == index.record_count
    assert result.result_count == 1
    assert "獸俓" in result.results[0]["snippet"]


def test_local_evidence_index_writer_persists_offline_index(tmp_path: Path) -> None:
    index_path = tmp_path / "outputs" / "kb" / "local-evidence-index.json"

    index = write_local_evidence_index(PROJECT_ROOT, index_path)
    loaded = load_local_evidence_index(index_path)

    assert index_path.is_file()
    assert loaded.record_count == index.record_count
    assert loaded.boundary.local_evidence_only is True
    assert loaded.boundary.live_safety_api_calls_allowed is False
    assert "<trkpt" not in index_path.read_text(encoding="utf-8").lower()


def test_local_evidence_sqlite_index_uses_fts_bm25(tmp_path: Path) -> None:
    index_path = tmp_path / "outputs" / "kb" / "local-evidence-index.sqlite3"

    index = write_local_evidence_sqlite_index(PROJECT_ROOT, index_path)
    result = query_local_evidence_sqlite_index(
        index_path,
        query="大崩塌",
        limit=2,
        evidence_types={"pretrip_route_note_candidate"},
    )

    assert index_path.is_file()
    assert result.retrieval_engine == "sqlite_fts5_bm25"
    assert result.searched_record_count == index.record_count
    assert result.results[0]["record_id"] == "route_note.golden_route.wpt_051"
    assert "retrieval_rank" in result.results[0]
    assert result.results[0]["boundary"]["live_safety_api_calls_allowed"] is False


def test_local_evidence_sqlite_index_diversifies_general_place_results(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "outputs" / "kb" / "local-evidence-index.sqlite3"
    write_local_evidence_sqlite_index(PROJECT_ROOT, index_path)

    result = query_local_evidence_sqlite_index(
        index_path,
        query="黑水塘有什麼資料？",
        limit=5,
    )

    evidence_types = {item["evidence_type"] for item in result.results}
    assert result.retrieval_engine == "sqlite_fts5_bm25"
    assert "pretrip_major_critical_point_candidate" in evidence_types
    assert "pretrip_mcp_cp_support_reconciliation" in evidence_types
    assert "pretrip_mcp_named_point" in evidence_types
    assert sum(
        1
        for item in result.results
        if item["evidence_type"] == "pretrip_route_note_candidate"
    ) <= 2


def test_project_local_evidence_prefers_prebuilt_sqlite_index(tmp_path: Path) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(PROJECT_ROOT, project_root)
    sqlite_path = project_root / "outputs" / "kb" / "local-evidence-index.sqlite3"
    write_local_evidence_sqlite_index(project_root, sqlite_path)

    result = query_project_local_evidence(
        project_root,
        query="黑水塘 cp",
        limit=3,
        evidence_types={"pretrip_mcp_cp_support_reconciliation"},
    )

    assert result.retrieval_engine == "sqlite_fts5_bm25"
    assert result.results[0]["record_id"] == "mcp.heishuitang.002"
    assert result.results[0]["metadata"]["support_status"] == "supported"
    assert result.results[0]["metadata"]["runtime_safety_truth"] is False


def test_local_evidence_query_finds_reviewed_spatial_imprint() -> None:
    result = query_project_local_evidence(
        PROJECT_ROOT,
        query="大崩壁",
        limit=3,
        evidence_types={"pretrip_reviewed_spatial_imprint"},
    )

    assert result.result_count == 1
    first = result.results[0]
    assert first["record_id"] == "spatial_imprint.chilai.collapse_wall.017"
    assert first["source_path"] == "outputs/spatial_imprint_set.json"
    assert "大崩壁" in first["snippet"]
    assert first["metadata"]["severity"] == "warning"
    assert first["boundary"]["runtime_safety_truth"] is False


def test_local_evidence_query_rejects_blank_query() -> None:
    with pytest.raises(ValueError, match="must not be blank"):
        query_local_evidence_index(
            build_local_evidence_index(PROJECT_ROOT),
            query=" ",
        )
