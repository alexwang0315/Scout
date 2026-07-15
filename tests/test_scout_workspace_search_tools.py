from __future__ import annotations

import json
import shutil
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


def test_workspace_catalog_exposes_bounded_project_and_gpx_identity() -> None:
    result = search_project_workspace_catalog(
        PROJECT_ROOT,
        query="project_id route_name primary GPX reference GPX",
        limit=6,
    )

    assert result["project_id"] == "chilai_nanhua_day1"
    assert result["route_name"] == "2013-10-08 10:58:50 每日記錄"
    assert result["primary_gpx_filename"] == "能高安東軍縱走.gpx.gpx"
    assert result["reference_gpx_count"] == 23
    assert result["reference_gpx_filenames"][:3] == [
        "20161119_20奇萊連峰.gpx",
        "2024-09-14馬君山_萬里池(萬馬線)_ㄚ國_p.gpx",
        "990418能高安東軍GDB檔.gpx",
    ]
    assert result["source_refs"] == [
        "project.json",
        "outputs/import_manifest.json",
        "outputs/reference_tracks.json",
        "normalized/routes/route_summary.json",
    ]
    assert all("/" not in filename for filename in result["reference_gpx_filenames"])


def test_workspace_catalog_search_includes_preparation_metadata_files(tmp_path: Path) -> None:
    workspace = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(PROJECT_ROOT, workspace)
    for rel in (
        "outputs/layers/layer_preparation_summary.json",
        "outputs/layers/map_preparation_summary.json",
        "outputs/scout_ai/pretrip_import_preparation_run_result.json",
    ):
        path = workspace / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "artifact_kind": Path(rel).stem,
                    "status": "completed",
                    "generated_at": "2026-07-08T00:00:00Z",
                }
            ),
            encoding="utf-8",
        )

    result = search_project_workspace_catalog(
        workspace,
        query="已完成 outputs 與仍缺的 preparation metadata",
        limit=8,
    )

    assert result["tool_id"] == WORKSPACE_CATALOG_TOOL_ID
    assert result["summaries"]["preparation_metadata_count"] >= 10
    assert result["summaries"]["existing_preparation_metadata_count"] >= 3
    paths = {item["source_path"] for item in result["results"]}
    assert "outputs/layers/layer_preparation_summary.json" in paths
    assert "outputs/layers/map_preparation_summary.json" in paths
    assert any(item["evidence_type"] == "workspace_preparation_metadata" for item in result["results"])


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
    assert count_result["summaries"]["expected_segment_count_from_checkpoints"] == 123
    assert count_result["summaries"]["segment_count_matches_checkpoint_chain"] is True
    assert count_result["summaries"]["segment_count_delta_from_expected"] == 0
    assert count_result["summaries"]["segment_missing_distance_count"] == 0
    assert "segment_missing_display_geometry_count" in count_result["summaries"]
    assert "checkpoint_duplicate_label_group_count" in count_result["summaries"]
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


def test_major_point_search_reports_workspace_boss_point_count(tmp_path: Path) -> None:
    project_root = tmp_path / "boss-route"
    (project_root / "outputs").mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "project_id": "boss-route",
                "boss_points_ref": "outputs/boss_points.json",
            }
        ),
        encoding="utf-8",
    )
    (project_root / "outputs" / "boss_points.json").write_text(
        json.dumps(
            {
                "boss_point_count": 2,
                "boss_points": [
                    {
                        "boss_point_id": "boss.001",
                        "label": "高壓路段 1",
                        "lat": 24.0,
                        "lon": 121.0,
                        "rank": 1,
                        "candidate_only": True,
                        "runtime_safety_truth": False,
                    },
                    {
                        "boss_point_id": "boss.002",
                        "label": "高壓路段 2",
                        "lat": 24.1,
                        "lon": 121.1,
                        "rank": 2,
                        "candidate_only": True,
                        "runtime_safety_truth": False,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    result = search_project_major_points(
        project_root,
        query="目前有多少個 boss point？",
        limit=5,
    )

    assert result["summaries"]["boss_point_count"] == 2
    assert result["result_count"] == 2
    assert result["results"][0]["evidence_type"] == "boss_point"
    assert "2 個" in result["field_answer"]
    assert result["boundary"]["runtime_safety_truth"] is False


def test_major_point_search_does_not_treat_missing_boss_artifact_as_zero(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "boss-route-missing"
    project_root.mkdir()
    (project_root / "project.json").write_text(
        json.dumps({"project_id": "boss-route-missing"}),
        encoding="utf-8",
    )

    result = search_project_major_points(
        project_root,
        query="目前有多少個 boss point？",
        limit=5,
    )

    assert result["summaries"]["boss_point_count"] is None
    assert result["result_count"] == 0
    assert "缺少" in result["field_answer"]
    assert "0 個 boss point" not in result["field_answer"]


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


def test_major_point_search_prioritizes_exact_named_anchor_over_alias_match() -> None:
    result = search_project_major_points(
        PROJECT_ROOT,
        query="雲海保線所 route anchor",
        limit=5,
    )

    assert result["tool_id"] == MAJOR_POINT_TOOL_ID
    first = result["results"][0]
    assert first["candidate_id"] == "np.yunhai_station"
    assert first["label"] == "雲海保線所"
    assert result["results"][1]["candidate_id"] == "ocr.yunhai_station.001"
    assert result["results"][2]["candidate_id"] == "mcp.heishuitang.002"
    assert result["field_answer"].startswith("候選重要點：雲海保線所")


def test_major_point_kind_filter_supports_rescue_visibility_candidates() -> None:
    result = search_project_major_points(
        PROJECT_ROOT,
        query="哪裡比較容易被看見？",
        point_kinds=["viewpoint_trailhead_pass", "mobile_reception"],
        limit=5,
    )

    labels = {item["label"] for item in result["results"]}
    assert "稜線啞口觀景點" in labels
    assert "稜線通訊點" in labels


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
