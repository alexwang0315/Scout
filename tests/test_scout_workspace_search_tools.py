from __future__ import annotations

import json
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


def test_evidence_fulltext_indexes_mileage_and_raster_ocr_artifacts(
    tmp_path: Path,
) -> None:
    workspace = _write_workspace_search_mileage_ocr_fixture(tmp_path)

    mileage = search_project_evidence_fulltext(workspace, query="15K在哪", limit=4)
    ocr = search_project_evidence_fulltext(workspace, query="924m OCR", limit=4)
    alignment = search_project_evidence_fulltext(
        workspace,
        query="mileage tag alignment usable anchor",
        limit=4,
    )

    assert any(
        item["evidence_type"] == "pretrip_route_mileage_k_anchor"
        and item["title"] == "15K"
        for item in mileage["results"]
    )
    assert any(
        item["evidence_type"] == "pretrip_raster_label_ocr"
        and item["title"] == "924m"
        for item in ocr["results"]
    )
    assert any(
        item["evidence_type"] == "pretrip_mileage_tag_alignment_summary"
        for item in alignment["results"]
    )
    assert mileage["boundary"]["runtime_safety_truth"] is False
    assert ocr["boundary"]["raw_payloads_embedded"] is False


def _write_workspace_search_mileage_ocr_fixture(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace-search-fixture"
    (workspace / "candidates").mkdir(parents=True)
    (workspace / "outputs" / "layers" / "normalized").mkdir(parents=True)
    (workspace / "outputs" / "layers").mkdir(parents=True, exist_ok=True)
    (workspace / "outputs").mkdir(parents=True, exist_ok=True)
    (workspace / "project.json").write_text(
        json.dumps(
            {
                "project_id": "workspace_search_fixture",
                "route_mileage_k_anchors_ref": "candidates/route_mileage_k_anchors.json",
                "mileage_tag_alignment_ref": "outputs/mileage_tag_alignment.json",
                "mileage_tag_alignment_geojson_ref": "outputs/mileage_tag_alignment.geojson",
                "raster_label_evidence_ref": (
                    "outputs/layers/normalized/raster_label_evidence.geojson"
                ),
                "raster_label_ocr_output_ref": "outputs/layers/raster_label_ocr_output.json",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (workspace / "candidates" / "route_mileage_k_anchors.json").write_text(
        json.dumps(
            {
                "artifact_kind": "pretrip_route_mileage_k_anchors",
                "anchors": [
                    {
                        "candidate_id": "route_context.route_note_candidates.workspace_route.15K",
                        "candidate_only": True,
                        "display_label": "15K",
                        "label_role": "trail_mileage_k_anchor",
                        "lat": 24.034234788,
                        "lon": 121.280180449,
                        "mileage_anchor_kind": "trail_mileage_k_anchor",
                        "mileage_k": 15.0,
                        "mileage_m": 15000.0,
                        "normalized_mileage_k": "15K",
                        "review_required": True,
                        "runtime_safety_truth": False,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (workspace / "outputs" / "mileage_tag_alignment.json").write_text(
        json.dumps(
            {
                "artifact_kind": "pretrip_workspace_mileage_tag_alignment",
                "status": "completed",
                "boundary": {"candidate_only": True, "runtime_safety_truth": False},
                "counts": {"tag_count": 1, "usable_anchor_count": 1},
                "mileage_tag_alignment_geojson_ref": "outputs/mileage_tag_alignment.geojson",
                "route_mileage_alignment": {
                    "usable_anchor_count": 1,
                    "projected_anchor_count": 1,
                    "rejected_anchor_count": 0,
                    "usable_anchors": [
                        {
                            "candidate_id": "route_context.route_note_candidates.workspace_route.15K",
                            "display_label": "15K",
                            "normalized_mileage_k": "15K",
                            "mileage_k": 15.0,
                            "mileage_m": 15000.0,
                            "lat": 24.034234788,
                            "lon": 121.280180449,
                            "candidate_only": True,
                            "runtime_safety_truth": False,
                        }
                    ],
                },
                "mileage_tags": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (
        workspace / "outputs" / "layers" / "normalized" / "raster_label_evidence.geojson"
    ).write_text(
        json.dumps(
            {
                "artifact_kind": "pretrip_raster_label_evidence",
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "id": "ocr_label.fixture.924m",
                        "geometry": {
                            "type": "Point",
                            "coordinates": [121.54724121, 23.5759308],
                        },
                        "properties": {
                            "candidate_id": "ocr_label.fixture.924m",
                            "candidate_only": True,
                            "confidence": 0.95,
                            "label_role": "named_place_label",
                            "label_text": "924m",
                            "review_required": True,
                            "runtime_safety_truth": False,
                            "source_payload_ref": (
                                "outputs/layers/raster_label_ocr_output.json"
                            ),
                            "source_ref": "local_raster_tile.z6.x53.y27",
                            "tile_id": "z6.x53.y27",
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (workspace / "outputs" / "layers" / "raster_label_ocr_output.json").write_text(
        json.dumps(
            {
                "artifact_kind": "pretrip_raster_label_ocr_output",
                "labels": [
                    {
                        "id": "ocr_label.fixture.924m",
                        "candidate_only": True,
                        "confidence": 0.95,
                        "label_role": "named_place_label",
                        "label_text": "924m",
                        "review_required": True,
                        "runtime_safety_truth": False,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return workspace
