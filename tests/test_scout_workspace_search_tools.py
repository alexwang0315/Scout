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


def test_workspace_catalog_does_not_answer_unrelated_query_with_layer_summary() -> None:
    result = search_project_workspace_catalog(
        PROJECT_ROOT,
        query="workspace 是否有 team status、隊員位置或生命徵兆 evidence？",
        limit=8,
    )

    assert result["field_answer"] is None or not result["field_answer"].startswith(
        "Layer preparation summary"
    )


def test_workspace_catalog_summarizes_environment_ref_existence(tmp_path: Path) -> None:
    workspace = tmp_path / "trip"
    existing_path = workspace / "outputs" / "environment" / "cwa" / "qpf.json"
    existing_path.parent.mkdir(parents=True)
    existing_path.write_text("{}", encoding="utf-8")
    (workspace / "project.json").write_text(
        json.dumps(
            {
                "project_id": "trip",
                "cwa_qpf_grid_ref": "outputs/environment/cwa/qpf.json",
                "gee_raw_summary_ref": "outputs/environment/gee/missing.json",
            }
        ),
        encoding="utf-8",
    )

    result = search_project_workspace_catalog(
        workspace,
        query=(
            "workspace catalog 中哪些 environment artifact 已存在，"
            "哪些 ref 指向的檔案缺失？"
        ),
        limit=6,
    )

    assert result["field_answer_priority"] == 100
    assert "existing=1" in result["field_answer"]
    assert "missing=1" in result["field_answer"]
    assert "cwa_qpf_grid_ref" in result["field_answer"]
    assert "gee_raw_summary_ref" in result["field_answer"]
    assert result["field_answer_source_ref"] == "project.json"


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


def test_workspace_catalog_answers_import_manifest_source_counts() -> None:
    result = search_project_workspace_catalog(
        PROJECT_ROOT,
        query="請從 workspace catalog 查出 import manifest 記錄的來源類型與檔案數量。",
        limit=6,
    )

    assert "GPX source files=24" in result["field_answer"]
    assert "golden_route_reference=1" in result["field_answer"]
    assert "reference_track=23" in result["field_answer"]
    assert result["field_answer_priority"] == 100
    assert result["field_answer_source_ref"] == "outputs/import_manifest.json"


def test_workspace_catalog_answers_reference_gpx_count_and_filenames() -> None:
    result = search_project_workspace_catalog(
        PROJECT_ROOT,
        query="workspace 目前共有多少條 reference GPX，請列出前五個檔名。",
        limit=6,
    )

    assert "reference GPX 共 23 條" in result["field_answer"]
    assert "20161119_20奇萊連峰.gpx" in result["field_answer"]
    assert "990418能高安東軍GDB檔.gpx" in result["field_answer"]
    assert result["field_answer_priority"] == 100
    assert result["field_answer_source_ref"] == "outputs/reference_tracks.json"


def test_workspace_catalog_answers_candidate_and_reviewed_package_status() -> None:
    result = search_project_workspace_catalog(
        PROJECT_ROOT,
        query="目前 workspace 有哪些 reviewed package 與 candidate package？",
        limit=6,
    )

    assert "outputs/pretrip_package.reviewed.json (status=reviewed)" in result[
        "field_answer"
    ]
    assert "outputs/pretrip_package.json (status=candidate)" in result[
        "field_answer"
    ]
    assert result["field_answer_priority"] == 100
    assert result["field_answer_source_ref"] == "project.json"


def test_workspace_catalog_answers_route_evidence_bundle_sources(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "trip"
    shutil.copytree(PROJECT_ROOT, workspace)
    project_path = workspace / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project["route_evidence_bundle_ref"] = (
        "normalized/routes/route_evidence_bundle.json"
    )
    project_path.write_text(json.dumps(project), encoding="utf-8")
    bundle_path = workspace / project["route_evidence_bundle_ref"]
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(
        json.dumps(
            {
                "golden_route": {
                    "route_summary_ref": "normalized/routes/route_summary.json",
                    "geometry_ref": "normalized/map/map_context.geojson",
                    "filtered_geometry_ref": "normalized/routes/filtered/primary.gpx",
                },
                "gpx_filter_refs": {
                    "speed_filter_report_ref": "outputs/gpx_speed_filter_report.json",
                    "rest_area_candidates_ref": "outputs/rest_area_candidates.json",
                },
                "note_candidate_refs": ["candidates/route_note_candidates.json"],
                "reference_tracks": [
                    {"geometry_ref": "outputs/reference_track_display_geometry.json"}
                ],
            }
        ),
        encoding="utf-8",
    )

    result = search_project_workspace_catalog(
        workspace,
        query="route evidence bundle 引用了哪些主要來源 artifact？",
        limit=6,
    )

    assert "route summary" in result["field_answer"]
    assert "speed-filter report" in result["field_answer"]
    assert "reference-track display geometry" in result["field_answer"]
    assert result["field_answer_priority"] == 100
    assert result["field_answer_source_ref"] == project["route_evidence_bundle_ref"]


def test_workspace_catalog_answers_source_inbox_import_status(tmp_path: Path) -> None:
    workspace = tmp_path / "trip"
    shutil.copytree(PROJECT_ROOT, workspace)
    project_path = workspace / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project["source_inbox_manifest_ref"] = "inbox/source_manifest.json"
    project_path.write_text(json.dumps(project), encoding="utf-8")
    manifest_path = workspace / project["source_inbox_manifest_ref"]
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "source_file_count": 2,
                "sources": [
                    {
                        "original_path": "/input/imported.gpx",
                        "imported_as_raw_file": True,
                    },
                    {
                        "original_path": "/input/pending.gpx",
                        "imported_as_raw_file": False,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    result = search_project_workspace_catalog(
        workspace,
        query="source inbox manifest 中哪些原始資料已匯入，哪些尚未處理？",
        limit=6,
    )

    assert "已匯入 1/2" in result["field_answer"]
    assert "imported.gpx" in result["field_answer"]
    assert "尚未處理 1" in result["field_answer"]
    assert "pending.gpx" in result["field_answer"]
    assert result["field_answer_priority"] == 100
    assert result["field_answer_source_ref"] == "inbox/source_manifest.json"


def test_workspace_catalog_answers_readiness_findings() -> None:
    result = search_project_workspace_catalog(
        PROJECT_ROOT,
        query="readiness report 目前列出的 blocker 與 warning 各有哪些？",
        limit=6,
    )

    assert "status=ready" in result["field_answer"]
    assert "blockers=none" in result["field_answer"]
    assert "warnings=none" in result["field_answer"]
    assert result["field_answer_priority"] == 100
    assert result["field_answer_source_ref"] == "outputs/readiness_report.json"


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


def test_workspace_catalog_answers_latest_layer_preparation_status(tmp_path: Path) -> None:
    workspace = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(PROJECT_ROOT, workspace)
    summary_path = workspace / "outputs/layers/layer_preparation_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(
            {
                "artifact_kind": "layer_preparation_summary",
                "status": "ready",
                "prepared_at": "2026-07-13T03:29:50Z",
                "profile": "mac-workstation",
            }
        ),
        encoding="utf-8",
    )

    result = search_project_workspace_catalog(
        workspace,
        query=(
            "請從 workspace catalog 查 layer preparation summary 的最新狀態、"
            "完成時間與 profile。"
        ),
        limit=8,
    )

    assert "status=ready" in result["field_answer"]
    assert "completed_at=2026-07-13T03:29:50Z" in result["field_answer"]
    assert "profile=mac-workstation" in result["field_answer"]
    assert result["field_answer_source_ref"] == (
        "outputs/layers/layer_preparation_summary.json"
    )


def test_workspace_catalog_reads_layer_validation_scalar_summary(tmp_path: Path) -> None:
    workspace = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(PROJECT_ROOT, workspace)
    project_path = workspace / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project["layer_validation_report_ref"] = (
        "outputs/layers/layer_validation_report.json"
    )
    project_path.write_text(
        json.dumps(project, ensure_ascii=False),
        encoding="utf-8",
    )
    report_path = workspace / "outputs" / "layers" / "layer_validation_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {
                "artifact_kind": "pretrip_layer_validation_report",
                "status": "ready",
                "completed_at": "2026-07-15T01:00:00Z",
                "profile": "full",
                "blocker_count": 0,
                "warning_count": 0,
                "blockers": [],
                "warnings": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = search_project_workspace_catalog(
        workspace,
        query="layer validation report 有哪些失敗或需要人工複核？",
        limit=6,
    )

    validation = next(
        item
        for item in result["results"]
        if item["ref_key"] == "layer_validation_report_ref"
    )
    assert "map" in result["filters"]["domains"]
    assert validation["domain"] == "map"
    assert validation["summary_fields"] == {
        "status": "ready",
        "completed_at": "2026-07-15T01:00:00Z",
        "profile": "full",
        "blocker_count": 0,
        "warning_count": 0,
    }
    assert "status=ready" in result["field_answer"]
    assert "blocker_count=0" in result["field_answer"]
    assert "warning_count=0" in result["field_answer"]
    assert "沒有列出失敗或警告項目" in result["field_answer"]
    assert result["field_answer_source_ref"] == (
        "outputs/layers/layer_validation_report.json"
    )
    assert result["source_ref"] == "outputs/layers/layer_validation_report.json"


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


def test_route_structure_answers_primary_route_gpx_summary() -> None:
    result = search_project_route_structure(
        PROJECT_ROOT,
        query="primary route 的 GPX 總里程、點數、最低與最高海拔是多少？",
    )

    assert "55.175 公里" in result["field_answer"]
    assert "2612" in result["field_answer"]
    assert "1216.69" in result["field_answer"]
    assert "3350.81" in result["field_answer"]
    assert result["field_answer_priority"] == 100
    assert result["field_answer_source_ref"] == "normalized/routes/route_summary.json"


def test_route_structure_answers_route_endpoints_and_bbox() -> None:
    result = search_project_route_structure(
        PROJECT_ROOT,
        query="路線結構資料中的 route summary 起點、終點與 bbox 座標是多少？",
    )

    assert "start cp.start=(24.05065393075347,121.21523100882769)" in result[
        "field_answer"
    ]
    assert "finish cp.finish=(23.953395187854767,121.17726685479283)" in result[
        "field_answer"
    ]
    assert (
        "bbox=[121.17726685479283,23.872665725648403,"
        "121.28102609887719,24.053969560191035]"
    ) in result["field_answer"]
    assert result["field_answer_priority"] == 100


def test_route_structure_answers_segment_count_and_names_compactly() -> None:
    result = search_project_route_structure(
        PROJECT_ROOT,
        query="目前路線被切成多少個 segments，各段名稱是什麼？",
    )

    assert "segments 共 123 段" in result["field_answer"]
    assert "Segment 001 至 Segment 123" in result["field_answer"]
    assert result["field_answer_priority"] == 100
    assert result["field_answer_source_ref"] == "candidates/segments.json"


def test_route_structure_answers_segment_display_point_counts() -> None:
    result = search_project_route_structure(
        PROJECT_ROOT,
        query="segment display geometry 每一段各有多少個座標點？",
    )

    assert "123 段" in result["field_answer"]
    assert "總座標點 2731" in result["field_answer"]
    assert "每段 2-64 點" in result["field_answer"]
    assert "seg.001=22" in result["field_answer"]
    assert result["field_answer_priority"] == 100
    assert result["field_answer_source_ref"] == (
        "outputs/segment_display_geometry.json"
    )


def test_route_structure_elevation_aggregate_has_exact_answer_priority() -> None:
    result = search_project_route_structure(
        PROJECT_ROOT,
        query="primary route 的總爬升、總下降與平均坡度資料是否存在？",
    )

    assert "總爬升" in result["field_answer"]
    assert "總下降" in result["field_answer"]
    assert "平均坡度欄位不存在" in result["field_answer"]
    assert result["field_answer_priority"] == 100


def test_route_structure_answers_reference_track_name_similarity() -> None:
    result = search_project_route_structure(
        PROJECT_ROOT,
        query=(
            "路線結構資料中的 reference tracks 總共有幾條，"
            "哪些與 primary route 名稱最接近？"
        ),
    )

    assert "reference tracks 共 23 條" in result["field_answer"]
    assert "2014-10-(09-10)" in result["field_answer"]
    assert "字串相似度" in result["field_answer"]
    assert result["field_answer_priority"] == 100
    assert result["field_answer_source_ref"] == "outputs/reference_tracks.json"


def test_route_structure_answers_geometry_preparation_completeness() -> None:
    result = search_project_route_structure(
        PROJECT_ROOT,
        query=(
            "路線結構資料顯示 primary route 與 reference tracks "
            "的幾何是否都已準備完成？"
        ),
    )

    assert "primary route geometry=prepared" in result["field_answer"]
    assert "reference track display geometry=prepared" in result["field_answer"]
    assert "23/23" in result["field_answer"]
    assert result["field_answer_priority"] == 100


def test_route_structure_answers_checkpoint_count_and_endpoints() -> None:
    result = search_project_route_structure(
        PROJECT_ROOT,
        query="checkpoint candidates 共有多少個，第一個與最後一個 CP 是什麼？",
    )

    assert "checkpoint candidates 共 124 個" in result["field_answer"]
    assert "第一個 cp.start/Start" in result["field_answer"]
    assert "最後一個 cp.finish/Finish" in result["field_answer"]
    assert result["field_answer_priority"] == 100
    assert result["field_answer_source_ref"] == "candidates/checkpoints.json"


def test_route_structure_answers_checkpoint_event_time_semantics() -> None:
    result = search_project_route_structure(
        PROJECT_ROOT,
        query="checkpoint events 中有哪些預計通過時間或實際事件資料？",
    )

    assert "candidate event projections 共 124 筆" in result["field_answer"]
    assert "observed_at=124" in result["field_answer"]
    assert "planned/ETA fields=0" in result["field_answer"]
    assert "live actual events=0" in result["field_answer"]
    assert "historical golden GPX" in result["field_answer"]
    assert result["field_answer_priority"] == 100
    assert result["field_answer_source_ref"] == "outputs/checkpoint_events.json"


def test_route_structure_joins_route_notes_and_named_points_to_checkpoints() -> None:
    result = search_project_route_structure(
        PROJECT_ROOT,
        query="哪些 checkpoint 靠近 route note 或地圖標註？",
    )

    assert "cp.077" in result["field_answer"]
    assert "083 崩塌區" in result["field_answer"]
    assert "cp.start" in result["field_answer"]
    assert "舊林道叉路" in result["field_answer"]
    assert "cp.003" in result["field_answer"]
    assert "雲海保線所" in result["field_answer"]
    assert result["field_answer_priority"] == 100
    assert result["field_answer_source_ref"] == (
        "outputs/route_note_ln_proposals.json"
    )
    annotation_summary = result["summaries"]["checkpoint_annotations"]
    assert annotation_summary["route_note_match_count"] > 0
    assert annotation_summary["named_point_match_count"] > 0
    assert annotation_summary["source_refs"] == [
        "outputs/route_note_ln_proposals.json",
        "outputs/mcp/named_point_evidence.json",
    ]


def test_route_structure_search_exposes_segments_for_cross_tool_risk_join() -> None:
    result = search_project_route_structure(
        PROJECT_ROOT,
        query="哪些 route segments 含有 extreme 或 very_high risk 點？",
        limit=5,
    )

    assert result["filters"]["collection_kind"] == "segments"
    assert result["result_count"] == 5
    assert all(item["evidence_type"] == "segment" for item in result["results"])
    assert result["results"][0]["candidate_id"] == "seg.001"
    assert all(item["candidate_only"] is True for item in result["results"])
    assert all(item["runtime_safety_truth"] is False for item in result["results"])


def test_route_structure_defers_dtm_coverage_verdict_to_terrain_evidence() -> None:
    result = search_project_route_structure(
        PROJECT_ROOT,
        query="哪些 route segments 的 DTM coverage 不完整？",
        limit=5,
    )

    assert "不含 DTM coverage 完整性欄位" in result["field_answer"]
    assert "不可從 route list 推論" in result["field_answer"]
    assert result["field_answer_source_ref"] == "candidates/segments.json"
    assert result["field_answer_priority"] == 10


def test_route_structure_search_reports_longest_segment_aggregate() -> None:
    segments = json.loads(
        (PROJECT_ROOT / "candidates" / "segments.json").read_text(encoding="utf-8")
    )
    expected = max(segments, key=lambda item: float(item["distance_m"]))

    result = search_project_route_structure(
        PROJECT_ROOT,
        query="哪一個 route segment 的距離最長，長度是多少公里？",
        limit=5,
    )

    longest = result["summaries"]["longest_segment"]
    assert longest["candidate_id"] == expected["candidate_id"]
    assert longest["distance_m"] == expected["distance_m"]
    assert longest["distance_km"] == round(float(expected["distance_m"]) / 1000, 3)
    assert expected["candidate_id"] in result["field_answer"]
    assert str(longest["distance_km"]) in result["field_answer"]


def test_route_structure_search_reports_primary_route_elevation_aggregates() -> None:
    segments = json.loads(
        (PROJECT_ROOT / "candidates" / "segments.json").read_text(encoding="utf-8")
    )
    expected_gain = round(
        sum(float(item.get("elevation_gain_m") or 0.0) for item in segments),
        3,
    )
    expected_loss = round(
        sum(float(item.get("elevation_loss_m") or 0.0) for item in segments),
        3,
    )

    result = search_project_route_structure(
        PROJECT_ROOT,
        query="primary route 的總爬升、總下降與平均坡度資料是否存在？",
        limit=5,
    )

    aggregate = result["summaries"]["primary_route_elevation_aggregate"]
    assert aggregate["segment_count"] == len(segments)
    assert aggregate["total_ascent_m"] == expected_gain
    assert aggregate["total_descent_m"] == expected_loss
    assert aggregate["average_slope_available"] is False
    assert "平均坡度欄位不存在" in result["field_answer"]
    assert result["field_answer_source_ref"] == "candidates/segments.json"


def test_route_structure_search_reads_resume_segment_report(tmp_path: Path) -> None:
    workspace = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(PROJECT_ROOT, workspace)
    project_path = workspace / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project["resume_segment_report_ref"] = "outputs/resume_segments.json"
    project_path.write_text(json.dumps(project), encoding="utf-8")
    report_path = workspace / "outputs" / "resume_segments.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {
                "resume_segment_count": 2,
                "segments": [
                    {
                        "segment_candidate_id": "seg.132",
                        "from_candidate_id": "cp.129",
                        "to_candidate_id": "cp.130",
                        "max_gap_m": 1802.176,
                    },
                    {
                        "segment_candidate_id": "seg.133",
                        "from_candidate_id": "cp.130",
                        "to_candidate_id": "cp.131",
                        "max_gap_m": 1807.29,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    result = search_project_route_structure(
        workspace,
        query="resume segment report 找到哪些可續接的路段？",
        limit=5,
    )

    assert result["summaries"]["resume_segments"]["count"] == 2
    assert "seg.132" in result["field_answer"]
    assert "seg.133" in result["field_answer"]
    assert result["field_answer_source_ref"] == "outputs/resume_segments.json"


def test_route_structure_search_reads_reference_segment_timing(tmp_path: Path) -> None:
    workspace = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(PROJECT_ROOT, workspace)
    project_path = workspace / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project["reference_segment_timing_ref"] = "outputs/reference_segment_timing.json"
    project_path.write_text(json.dumps(project), encoding="utf-8")
    report_path = workspace / "outputs" / "reference_segment_timing.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {
                "counts": {"segment_count": 2, "measurement_count": 11},
                "segments": [
                    {
                        "segment_id": "ref.001",
                        "label": "登山口 -> 山屋",
                        "sample_count": 6,
                        "duration_minutes": {"min": 90.0, "p50": 110.0, "p75": 125.0, "max": 150.0},
                    },
                    {
                        "segment_id": "ref.002",
                        "label": "山屋 -> 稜線",
                        "sample_count": 5,
                        "duration_minutes": {"min": 40.0, "p50": 55.0, "p75": 64.0, "max": 80.0},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    result = search_project_route_structure(
        workspace,
        query="reference segment timing 提供了哪些路段時間統計？",
        limit=5,
    )

    timing = result["summaries"]["reference_segment_timing"]
    assert timing["segment_count"] == 2
    assert timing["measurement_count"] == 11
    assert timing["segments"][0]["duration_minutes"]["p50"] == 110.0
    assert "登山口 -> 山屋" in result["field_answer"]
    assert "p50=110.0 分" in result["field_answer"]
    assert result["field_answer_source_ref"] == "outputs/reference_segment_timing.json"


def test_route_structure_search_joins_rest_areas_to_route_segments(tmp_path: Path) -> None:
    workspace = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(PROJECT_ROOT, workspace)
    project_path = workspace / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project["rest_area_candidates_ref"] = "outputs/rest_area_candidates.json"
    project_path.write_text(json.dumps(project), encoding="utf-8")
    report_path = workspace / "outputs" / "rest_area_candidates.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {
                "rest_area_candidate_count": 3,
                "candidates": [
                    {
                        "candidate_id": "rest.001",
                        "checkpoint_candidate_id": "cp.rest.001",
                        "route_point_index": 3,
                        "review_state": "needs_review",
                    },
                        {
                            "candidate_id": "rest.002",
                            "checkpoint_candidate_id": "cp.rest.002",
                            "route_point_index": 30,
                            "review_state": "needs_review",
                        },
                    {
                        "candidate_id": "rest_area.chilai_nanhua_day1_scoutAI.014",
                        "checkpoint_candidate_id": "cp.rest.014",
                        "route_point_index": 3,
                        "review_state": "needs_review",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    result = search_project_route_structure(
        workspace,
        query="rest area candidates 共有幾個，分別靠近哪些 CP 或 segment？",
        limit=5,
    )

    rest = result["summaries"]["rest_area_candidates"]
    assert rest["count"] == 3
    assert rest["candidates"][0]["segment_candidate_id"] == "seg.001"
    assert rest["candidates"][0]["nearby_cp_candidate_ids"] == [
        "cp.start",
        "cp.001",
    ]
    assert rest["candidates"][1]["segment_candidate_id"] == "seg.002"
    assert "rest.001" in result["field_answer"]
    assert "rest_area#014" in result["field_answer"]
    assert "rest_area.chilai_nanhua_day1_scoutAI.014" not in result["field_answer"]
    assert "seg.001" in result["field_answer"]
    assert result["field_answer_source_ref"] == "outputs/rest_area_candidates.json"
    assert result["field_answer_priority"] == 100


def test_route_structure_search_joins_historical_gpx_sources_to_overlap_report() -> None:
    source_index = json.loads(
        (PROJECT_ROOT / "sources" / "historical_gpx_source_index.json").read_text(
            encoding="utf-8"
        )
    )
    reference_tracks = json.loads(
        (PROJECT_ROOT / "outputs" / "reference_tracks.json").read_text(
            encoding="utf-8"
        )
    )
    expected_overlap_count = sum(
        bool(item.get("bbox_comparison", {}).get("overlaps"))
        for item in reference_tracks["reference_tracks"]
    )

    result = search_project_route_structure(
        PROJECT_ROOT,
        query="historical GPX source index 中哪些來源與目前路線重疊？",
        limit=5,
    )

    overlap = result["summaries"]["historical_gpx_overlap"]
    assert overlap["source_count"] == source_index["source_file_count"]
    assert overlap["reference_track_count"] == len(
        reference_tracks["reference_tracks"]
    )
    assert overlap["overlap_count"] == expected_overlap_count
    assert overlap["overlapping_sources"]
    assert overlap["overlapping_sources"][0]["original_filename"]
    assert "historical gpx sources" in result["field_answer"].lower()
    assert str(expected_overlap_count) in result["field_answer"]
    assert result["field_answer_source_ref"] == "outputs/reference_tracks.json"
    assert len(result["field_answer"]) < 2400


def test_workspace_catalog_counts_route_note_candidate_categories() -> None:
    result = search_project_workspace_catalog(
        PROJECT_ROOT,
        query="route note candidates 有多少筆，分類有哪些？",
        limit=5,
    )

    payload = json.loads(
        (PROJECT_ROOT / "candidates" / "route_note_candidates.json").read_text(
            encoding="utf-8"
        )
    )
    expected_count = len(payload["candidates"])
    assert f"共 {expected_count} 筆" in result["field_answer"]
    assert "uncategorized_note=" in result["field_answer"]
    assert "hazard_hint=" in result["field_answer"]
    assert result["field_answer_source_ref"] == "candidates/route_note_candidates.json"
    assert result["field_answer_priority"] == 100


def test_route_structure_search_exposes_retreat_route_candidates() -> None:
    result = search_project_route_structure(
        PROJECT_ROOT,
        query="哪些 retreat route 最靠近高 terrain risk segment？",
        limit=5,
    )

    retreat = result["summaries"]["retreat_routes"]
    assert retreat["available"] is True
    assert retreat["count"] >= 1
    assert retreat["routes"][0]["candidate_id"]
    assert retreat["routes"][0]["candidate_only"] is True
    assert retreat["routes"][0]["runtime_safety_truth"] is False
    assert "retreat route candidates" in result["field_answer"].lower()
    assert result["field_answer_source_ref"] == "candidates/retreat_routes.json"
    assert result["field_answer_priority"] == 10


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
    assert "高壓路段 1" in result["field_answer"]
    assert "高壓路段 2" in result["field_answer"]
    assert result["field_answer_priority"] == 100
    assert result["field_answer_source_ref"] == "outputs/boss_points.json"
    assert result["boundary"]["runtime_safety_truth"] is False


def test_major_point_search_answers_named_mcp_inventory() -> None:
    result = search_project_major_points(
        PROJECT_ROOT,
        query="MCP candidates 共有多少個，哪些 MCP 已有名稱證據？",
        limit=6,
    )

    assert "MCP candidates 共 6 個" in result["field_answer"]
    assert "mcp.heishuitang.002/黑水塘" in result["field_answer"]
    assert "np.heishuitang" in result["field_answer"]
    assert result["field_answer_priority"] == 100
    assert result["field_answer_source_ref"] == "outputs/mcp/mcp_candidates.json"


def test_major_point_search_answers_cp_mcp_reconciliation() -> None:
    result = search_project_major_points(
        PROJECT_ROOT,
        query="CP 與 MCP reconciliation 報告中有哪些重疊、缺漏或衝突？",
        limit=6,
    )

    assert "supported=5" in result["field_answer"]
    assert "unsupported=1" in result["field_answer"]
    assert "mcp.mobile_reception_ridge.006" in result["field_answer"]
    assert "spacing overlaps=" in result["field_answer"]
    assert result["field_answer_priority"] == 100
    assert result["field_answer_source_ref"] == (
        "outputs/mcp/mcp_cp_support_reconciliation.json"
    )


def test_major_point_search_explains_unsupported_mcp_directionality() -> None:
    result = search_project_major_points(
        PROJECT_ROOT,
        query="哪些 CP 目前沒有對應的 MCP support？",
        limit=6,
    )

    assert "reconciliation 是 MCP 對 CP 的支援檢查" in result["field_answer"]
    assert "mcp.mobile_reception_ridge.006" in result["field_answer"]
    assert "suggested CP" in result["field_answer"]
    assert result["field_answer_priority"] == 100


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
