from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from pretrip_artifact_manifest import build_pretrip_artifact_manifest
from pretrip_route_context_collection import (
    ROUTE_CONTEXT_BRIEFING_REF,
    ROUTE_CONTEXT_CRAWL_SEED_PLAN_REF,
    ROUTE_CONTEXT_EVIDENCE_REF,
    ROUTE_CONTEXT_MEDIA_MANIFEST_REF,
    ROUTE_CONTEXT_PACK_REF,
    ROUTE_CONTEXT_POINTS_REF,
    ROUTE_MILEAGE_K_ANCHORS_REF,
    SOURCE_TIER_CATALOG,
    ROUTE_CONTEXT_SOURCE_MANIFEST_REF,
    collect_pretrip_route_context,
    _briefing_profile_points,
    _briefing_schedule_phases,
    _briefing_source_brief_points,
    _briefing_source_health_panel,
    _briefing_source_summary,
    _briefing_source_tier_card,
    _stop_advisory_text,
)
from scout_agent_cli import run_scout_agent_cli
from scout_route_context_tool import assess_scout_route_context
from tools.verify_pretrip_workspace_spec_alignment import _check_route_context_refs


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PROJECT = (
    REPO_ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
)
MANIFEST_DIR = REPO_ROOT / "tools" / "scout_agent_tool_manifests"


def _visible_html_text(document: str) -> str:
    without_code = re.sub(
        r"<(script|style)\b[^>]*>.*?</\1>",
        " ",
        document,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", without_code)).strip()


def test_route_source_brief_points_drop_image_caption_noise() -> None:
    points = _briefing_source_brief_points(
        "A. 紀念碑原貌 B. 紀念碑現況 ▲ 1910年代人物 "
        "清朝八通關古道的修築始於清代開山政策。 / "
        "日人修築之越道路與清領時期古道路徑不同，東段分走溪流南北岸。"
    )

    assert points == [
        "清朝八通關古道的修築始於清代開山政策。",
        "日人修築之越道路與清領時期古道路徑不同，東段分走溪流南北岸。",
    ]
    assert all("紀念碑原貌" not in point for point in points)


def test_briefing_quality_gate_keeps_filtered_inputs_and_point_groups_honest() -> None:
    route_points = [
        {"display_label": f"節點 {index}", "distance_m": distance_m}
        for index, distance_m in enumerate(
            (3000, 4000, 38200, 40800, 43700, 47200, 70200),
            start=1,
        )
    ]
    source_manifest = {
        "source_report": [
            {
                "source_kind": "mcp_candidates",
                "source_tier": "P1",
                "status": "loaded",
                "loaded_count": 7,
                "materialized_point_count": 7,
                "filtered_out_point_count": 0,
            },
            {
                "source_kind": "named_point_evidence",
                "source_tier": "P1",
                "status": "loaded",
                "loaded_count": 7,
                "materialized_point_count": 7,
                "filtered_out_point_count": 0,
            },
            {
                "source_kind": "raster_label_evidence",
                "source_tier": "P1",
                "status": "loaded",
                "loaded_count": 17,
                "materialized_point_count": 0,
                "filtered_out_point_count": 17,
            },
        ],
        "cache_policy": {
            "live_source_refresh_status": "live_network_refreshed",
            "refresh_required_before_runtime_truth": False,
            "network_refresh_required": False,
        },
    }

    p1_card = _briefing_source_tier_card(source_manifest, "P1")
    assert "已載入 2 類可用資料" in p1_card
    assert "Raster 標籤 · 17 讀入 / 0 進入路線點" in p1_card
    assert "品質不足，不列為路線點" in p1_card
    assert "Raster 標籤 · 已載入 · 17" not in p1_card

    profile_points = _briefing_profile_points(route_points, 89827.14)
    assert [point["label"] for point in profile_points] == [
        f"節點 {index}" for index in range(1, 8)
    ]

    phases = _briefing_schedule_phases(route_points, 89827.14)
    assert [phase["name"] for phase in phases] == [
        "命名節點群組 1",
        "命名節點群組 2",
        "命名節點群組 3",
    ]
    assert phases[-1]["summary"] == "70.2K 節點 7；只是一個具名點，不代表路段。"
    assert phases[-1]["uncovered_ranges"] == ["70.2K–89.8K"]

    source_summary = _briefing_source_summary(source_manifest)
    health_panel = _briefing_source_health_panel(
        source_manifest,
        source_summary,
        {"candidate_only": True, "runtime_safety_truth": False},
    )
    assert "已知資訊缺口" in health_panel
    assert "本次列定來源抓取完成" in health_panel
    assert "現況與天氣仍未同步" in health_panel
    assert "無必要缺口" not in health_panel
    assert "無可補強缺口" not in health_panel
    assert "已完成來源更新" not in health_panel

    assert "優先查核是否需降低暴露或快速通過" in _stop_advisory_text(
        {"stop_advisory_candidate": "pass_through_or_minimize_exposure"}
    )
    assert "現地應快速通過" not in _stop_advisory_text(
        {"stop_advisory_candidate": "pass_through_or_minimize_exposure"}
    )


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
    assert any(
        source["tier"] == "P0"
        and source["source_id"] == "tacp_indigenous_historic_trails"
        and source["role"] == "cultural_trail_baseline"
        for source in SOURCE_TIER_CATALOG
    )
    assert any(
        source["tier"] == "P0"
        and source["source_id"] == "regional_fire_department_incident_feeds"
        and source["role"] == "incident_local_baseline"
        for source in SOURCE_TIER_CATALOG
    )
    assert any(
        source["tier"] == "P1"
        and source["source_id"] == "mountain_rescue_association_knowledge"
        and source["role"] == "rescue_training_reference"
        for source in SOURCE_TIER_CATALOG
    )
    assert "route_note_candidate" not in result["counts"]["by_evidence_type"]
    assert result["boundary"]["candidate_only"] is True
    assert result["boundary"]["runtime_safety_truth"] is False
    assert result["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert result["outputs"]["route_context_evidence_ref"] == ROUTE_CONTEXT_EVIDENCE_REF
    assert (
        result["outputs"]["route_context_source_manifest_ref"]
        == ROUTE_CONTEXT_SOURCE_MANIFEST_REF
    )
    assert result["outputs"]["route_context_pack_ref"] == ROUTE_CONTEXT_PACK_REF
    assert (
        result["outputs"]["route_context_crawl_seed_plan_ref"]
        == ROUTE_CONTEXT_CRAWL_SEED_PLAN_REF
    )
    assert (
        result["outputs"]["route_context_media_manifest_ref"]
        == ROUTE_CONTEXT_MEDIA_MANIFEST_REF
    )
    assert result["outputs"]["route_context_briefing_ref"] == ROUTE_CONTEXT_BRIEFING_REF
    assert result["outputs"]["route_context_points_ref"] == ROUTE_CONTEXT_POINTS_REF
    assert (
        result["outputs"]["route_mileage_k_anchors_ref"] == ROUTE_MILEAGE_K_ANCHORS_REF
    )

    source_status = {
        source["source_kind"]: source["status"] for source in result["source_report"]
    }
    assert source_status["mcp_candidates"] == "loaded"
    assert source_status["named_point_evidence"] == "loaded"
    assert source_status["route_note_candidates"] == "loaded"
    assert source_status["web_case_evidence"] == "loaded"
    assert source_status["raster_label_evidence"] == "missing"


def test_route_context_briefing_is_route_specific_and_rejects_map_label_noise(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "dongqing_batongguan_historic_trail_scoutAI"
    shutil.copytree(FIXTURE_PROJECT, project_root)

    project_path = project_root / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project["project_id"] = "dongqing_batongguan_historic_trail_scoutAI"
    project["route_name"] = "20210220清朝八通關全線"
    project["raster_label_evidence_ref"] = (
        "outputs/layers/normalized/raster_label_evidence.geojson"
    )
    project_path.write_text(
        json.dumps(project, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    route_summary_path = project_root / "normalized/routes/route_summary.json"
    route_summary = json.loads(route_summary_path.read_text(encoding="utf-8"))
    route_summary.update(
        {
            "route_name": "20210220清朝八通關全線",
            "distance_m": 89827.14,
            "elevation_min_m": 595.3,
            "elevation_max_m": 3248.96,
        }
    )
    route_summary_path.write_text(
        json.dumps(route_summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    mcp_path = project_root / "outputs/mcp/mcp_candidates.json"
    mcp = json.loads(mcp_path.read_text(encoding="utf-8"))
    mcp["project_id"] = project["project_id"]
    mcp["mcp_candidates"] = []
    mcp["mcp_candidate_count"] = 0
    mcp_path.write_text(
        json.dumps(mcp, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    named_path = project_root / "outputs/mcp/named_point_evidence.json"
    named = json.loads(named_path.read_text(encoding="utf-8"))
    named["project_id"] = project["project_id"]
    named_points = named["named_points"][:4]
    replacements = (
        ("244獵人營地", 3000.0, ["camp_hut_structure"]),
        ("大水窟山屋", 38200.0, ["camp_hut_structure"]),
        ("米亞桑溪", 43700.0, ["water_source"]),
        ("公山", 47200.0, ["viewpoint_trailhead_pass"]),
    )
    for point, (label, distance_m, point_class) in zip(
        named_points,
        replacements,
        strict=True,
    ):
        point["canonical_name"] = label
        point["aliases"] = [label]
        point["named_point_id"] = f"np.{label}"
        point["point_class"] = point_class
        point["route_position"]["distance_m"] = distance_m
    named["named_points"] = named_points
    named_path.write_text(
        json.dumps(named, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    route_notes_path = project_root / "candidates/route_note_candidates.json"
    route_notes = json.loads(route_notes_path.read_text(encoding="utf-8"))
    route_notes["project_id"] = project["project_id"]
    route_notes["candidates"] = []
    route_notes["counts"] = {key: 0 for key in route_notes.get("counts", {})}
    route_notes_path.write_text(
        json.dumps(route_notes, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    web_path = project_root / "outputs/layers/normalized/web_case_evidence.json"
    web = json.loads(web_path.read_text(encoding="utf-8"))
    web["project_id"] = project["project_id"]
    web["points"] = []
    web["source_statuses"] = []
    web["counts"] = {
        "by_source_tier": {},
        "image_ref_count": 0,
    }
    web_path.write_text(
        json.dumps(web, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    raster_path = project_root / project["raster_label_evidence_ref"]
    raster_path.parent.mkdir(parents=True, exist_ok=True)
    raster_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"id": "valid", "label": "大黑水塘"},
                        "geometry": {
                            "type": "Point",
                            "coordinates": [121.01, 23.45],
                        },
                    },
                    *[
                        {
                            "type": "Feature",
                            "properties": {"id": f"noise-{index}", "label": label},
                            "geometry": {
                                "type": "Point",
                                "coordinates": [121.01, 23.45],
                            },
                        }
                        for index, label in enumerate(
                            (
                                "il",
                                "ul",
                                "台",
                                "灣",
                                "魯",
                                "地",
                                "圖",
                                "v2026.07.23",
                                "GN",
                                "By,",
                                "馬",
                                "2",
                                "hae",
                                "care",
                                "oe",
                                "Vike",
                                "eS.",
                            ),
                            start=1,
                        )
                    ],
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    collect_pretrip_route_context(
        project_root,
        dry_run=False,
        include_route_notes=False,
        route_keyword="東清八通關古道 清朝八通關古道 大水窟 米亞桑溪",
        collected_at="2026-07-30T00:00:00Z",
    )

    briefing = (project_root / ROUTE_CONTEXT_BRIEFING_REF).read_text(encoding="utf-8")
    visible_briefing = _visible_html_text(briefing)
    points = json.loads(
        (project_root / ROUTE_CONTEXT_POINTS_REF).read_text(encoding="utf-8")
    )
    source_manifest = json.loads(
        (project_root / ROUTE_CONTEXT_SOURCE_MANIFEST_REF).read_text(encoding="utf-8")
    )
    labels = {point["display_label"] for point in points["points"]}
    ocr_source = next(
        source
        for source in source_manifest["source_report"]
        if source["source_kind"] == "ocr_label_evidence"
    )

    assert "東清八通關古道" in briefing
    assert "大水窟山屋" in briefing
    assert "米亞桑溪" in briefing
    assert "大黑水塘" in briefing
    for unrelated in (
        "奇萊",
        "南華",
        "能高越嶺",
        "雲海保線所",
        "天池山莊",
        "光被八表",
        "雙峰",
    ):
        assert unrelated not in briefing
    for unsourced_duration in ("1 日或壓縮", "2 天 1 夜", "3 天 2 夜"):
        assert unsourced_duration not in briefing
    assert "分日天數尚無可追溯行程來源" in briefing
    assert "89.8 km" in briefing
    assert "目前明確不能回答" in briefing
    assert "目前沒有可追溯的每日里程、宿點與接駁行程表" in briefing
    assert "缺口保留為缺口" in briefing
    hero = briefing[
        briefing.index('<header class="hero"') : briefing.index("</header>")
    ]
    assert "project: dongqing_batongguan_historic_trail_scoutAI" in hero
    assert "briefing 產製日期 2026-07-30" in hero
    assert "候選資料，需人工審查" in hero
    assert "現況與天氣未同步" in hero
    assert "非出發核准" in hero
    assert "資料更新 2026-07-30" not in hero
    assert "clip-path: polygon" not in briefing
    assert "里程節點軸（非高程剖面）" in briefing
    assert "來源圖片分類" in briefing
    assert "照片路標" not in briefing
    assert "現地應快速通過，不建議停留拍照" not in briefing
    assert "無必要缺口" not in briefing
    assert "無可補強缺口" not in briefing
    assert "已完成來源更新" not in briefing
    assert "body.mode-briefing .briefing-detail-slide" in briefing
    assert '<a class="nav-detail" href="#photo-essay">' in briefing
    assert '<section class="slide briefing-detail-slide" id="photo-essay">' in briefing
    assert ocr_source["status"] == "project_mismatch"
    assert ocr_source["binding_error"] == "source_artifact_project_id_mismatch"
    for noisy_label in (
        "il",
        "ul",
        "台",
        "灣",
        "魯",
        "地",
        "圖",
        "v2026.07.23",
        "GN",
        "By,",
        "馬",
        "2",
        "hae",
        "care",
        "oe",
        "Vike",
        "eS.",
    ):
        assert noisy_label not in labels
    for noisy_label in ("v2026.07.23", "eS."):
        assert noisy_label not in visible_briefing


def test_route_context_collection_writes_workspace_layout_outputs(
    tmp_path: Path,
) -> None:
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
    media_manifest_path = project_root / ROUTE_CONTEXT_MEDIA_MANIFEST_REF
    briefing_path = project_root / ROUTE_CONTEXT_BRIEFING_REF
    points_path = project_root / ROUTE_CONTEXT_POINTS_REF
    mileage_anchors_path = project_root / ROUTE_MILEAGE_K_ANCHORS_REF
    assert evidence_path.is_file()
    assert source_manifest_path.is_file()
    assert pack_path.is_file()
    assert crawl_seed_plan_path.is_file()
    assert media_manifest_path.is_file()
    assert briefing_path.is_file()
    assert points_path.is_file()
    assert mileage_anchors_path.is_file()

    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    crawl_seed_plan = json.loads(crawl_seed_plan_path.read_text(encoding="utf-8"))
    media_manifest = json.loads(media_manifest_path.read_text(encoding="utf-8"))
    briefing = briefing_path.read_text(encoding="utf-8")
    points = json.loads(points_path.read_text(encoding="utf-8"))
    mileage_anchors = json.loads(mileage_anchors_path.read_text(encoding="utf-8"))
    project = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    labels = {point["display_label"] for point in points["points"]}
    assert evidence["artifact_kind"] == "pretrip_route_context_evidence"
    assert source_manifest["artifact_kind"] == "pretrip_route_context_source_manifest"
    assert pack["artifact_kind"] == "pretrip_route_context_pack"
    assert crawl_seed_plan["artifact_kind"] == "pretrip_route_context_crawl_seed_plan"
    assert media_manifest["artifact_kind"] == "pretrip_route_context_media_manifest"
    assert points["artifact_kind"] == "pretrip_route_context_points"
    assert mileage_anchors["artifact_kind"] == "pretrip_route_mileage_k_anchors"
    assert mileage_anchors["scan_summary"]["source_candidate_count"] == 4406
    assert (
        mileage_anchors["scan_summary"]["complete_scan_before_route_bbox_filter"]
        is True
    )
    assert mileage_anchors["scan_summary"]["raw_mileage_label_hit_count"] > 500
    assert (
        mileage_anchors["scan_summary"]["unique_trail_mileage_k_count"]
        > (mileage_anchors["anchor_count"])
    )
    assert mileage_anchors["scan_summary"]["unique_road_mileage_stone_count"] >= 3
    assert mileage_anchors["scan_summary"]["route_bbox_filtered_out_count"] > 0
    assert set(
        mileage_anchors["scan_summary"]["unique_road_mileage_stone_values_kept"]
    ) == {
        "0K",
        "92.3K",
        "94K",
    }
    assert evidence["route_context_points_ref"] == ROUTE_CONTEXT_POINTS_REF
    assert evidence["route_mileage_k_anchors_ref"] == ROUTE_MILEAGE_K_ANCHORS_REF
    assert evidence["source_manifest_ref"] == ROUTE_CONTEXT_SOURCE_MANIFEST_REF
    assert evidence["route_context_pack_ref"] == ROUTE_CONTEXT_PACK_REF
    assert evidence["crawl_seed_plan_ref"] == ROUTE_CONTEXT_CRAWL_SEED_PLAN_REF
    assert pack["source_manifest_ref"] == ROUTE_CONTEXT_SOURCE_MANIFEST_REF
    assert pack["route_context_points_ref"] == ROUTE_CONTEXT_POINTS_REF
    assert pack["route_mileage_k_anchors_ref"] == ROUTE_MILEAGE_K_ANCHORS_REF
    assert pack["crawl_seed_plan_ref"] == ROUTE_CONTEXT_CRAWL_SEED_PLAN_REF
    assert pack["route_context_media_manifest_ref"] == ROUTE_CONTEXT_MEDIA_MANIFEST_REF
    assert pack["route_summary"]["raw_route_points_embedded"] is False
    assert mileage_anchors["anchor_count"] >= 20
    assert mileage_anchors["raw_evidence_count"] >= mileage_anchors["anchor_count"]
    assert {"0.5K", "5K", "10K", "14.5K"}.issubset(
        set(mileage_anchors["normalized_mileage_k_values"])
    )
    assert "94K" not in set(mileage_anchors["normalized_mileage_k_values"])
    assert any(
        point["evidence_type"] == "trail_mileage_k_anchor"
        and point["normalized_mileage_k"] == "5K"
        and point["source_evidence_count"] >= 1
        for point in points["points"]
    )
    assert any(
        point["evidence_type"] == "road_mileage_stone"
        and point["normalized_mileage_k"] == "94K"
        and "road_mileage_stone_not_trail_k_anchor" in point["review_reasons"]
        for point in points["points"]
    )
    assert (
        crawl_seed_plan["route_note_seed_policy"]["route_notes_are_conclusion"] is False
    )
    assert (
        crawl_seed_plan["route_note_seed_policy"]["route_notes_are_seed_material"]
        is True
    )
    assert crawl_seed_plan["route_note_seed_count"] > 0
    assert "奇萊-南華" in crawl_seed_plan["route_keywords"]
    assert all(
        "每日記錄" not in keyword for keyword in crawl_seed_plan["route_keywords"]
    )
    assert "Scout 行前路線說明" in briefing
    for section_id in (
        "intelligence",
        "days",
        "status",
        "photo-essay",
        "visual-kit",
        "visual-story",
        "visual-anchors",
        "story-wall",
        "route",
        "sights",
        "layers",
        "p2",
        "storyline",
        "stops",
        "risk",
        "schedule",
        "sources",
    ):
        assert f'id="{section_id}"' in briefing
    assert "目前有哪些可用事實與明確缺口" in briefing
    assert "先分清已證實內容與缺口" in briefing
    assert "命名節點" in briefing
    assert "官方脈絡" in briefing
    assert "證據層級" in briefing
    assert "缺口處理" in briefing
    assert "不能用舊軌跡日期、照片或點名反推出分日與現況" in briefing
    assert "這份資料能不能回答行程天數" in briefing
    assert "沿途停看聽導覽卡" in briefing
    assert "看什麼" in briefing
    assert "隊伍提問" in briefing
    assert "highlight-guide-cue" in briefing
    assert "highlight-question" in briefing
    assert "highlight-data-details" in briefing
    assert ".mode-briefing .highlight-data-details" in briefing
    assert "把路線拆成六個脈絡層" in briefing
    assert "六個行前面向" in briefing
    assert "講給隊伍聽" in briefing
    assert "現場提問" in briefing
    assert "把地形說成通過策略" in briefing
    assert "文化敏感點只作待審查線索" in briefing
    assert "哪些點值得停 3 分鐘" in briefing
    assert "觀察重點" in briefing
    assert "隊伍提問" in briefing
    assert "離開條件" in briefing
    assert "現地審查資訊" in briefing
    assert "itinerary-board" in briefing
    assert "itinerary-visual" in briefing
    assert "itinerary-option-card" in briefing
    assert "itinerary-lens" in briefing
    assert "天數判斷畫面" in briefing
    assert "補齊來源後再討論" in briefing
    assert "出發前行程審查板" in briefing
    assert "schedule-decision-board" in briefing
    assert "schedule-gate-panel" in briefing
    assert "schedule-gates" in briefing
    assert "領隊確認天氣、路況、山屋與隊伍狀態" in briefing
    assert "先確認能不能照原計畫走" in briefing
    assert "未覆蓋里程" in briefing
    assert "命名節點群組" in briefing
    assert "分日天數尚無可追溯行程來源" in briefing
    assert "schedule-board" in briefing
    assert "未覆蓋里程" in briefing
    assert "這份 briefing 不提供未有來源的分日建議" in briefing
    assert "highlight-wall" in briefing
    assert "trust-board" in briefing
    assert "source-trust-layout" in briefing
    assert "source-trust-visual" in briefing
    assert "source-step-index" in briefing
    assert "來源信任路徑" in briefing
    assert "來源代表圖" in briefing
    assert "source-brief-grid" in briefing
    assert "source-brief-card" in briefing
    assert "source-cue" in briefing
    assert "source-action" in briefing
    assert "source-tier-spine" in briefing
    assert "source-tier-grid" in briefing
    assert "來源可信度" in briefing
    assert "官方資料、延伸資料與隊伍回顧要分開看" in briefing
    assert "官方資料" in briefing
    assert "延伸資料" in briefing
    assert "隊伍回顧" in briefing
    assert "信任摘要" in briefing
    assert "可追溯資料" in briefing
    assert "缺口" in briefing
    assert "安全邊界" in briefing
    assert "展開來源查核表與待補資料" in briefing
    assert "visual-anchor-board" in briefing
    assert "來源圖片分類" in briefing
    assert "路線故事牆" in briefing
    assert "先讓隊伍記住畫面，再講資料" in briefing
    assert "story-feature" in briefing
    assert "story-mosaic" in briefing
    assert "story-cue" in briefing
    assert "story-speaker-note" in briefing
    assert "storyline-rail" in briefing
    assert "storyline-card" in briefing
    assert "storyline-thumb" in briefing
    assert "storyline-distance" in briefing
    assert "storyline-cue" in briefing
    assert "storyline-action" in briefing
    assert "storyline-data-details" in briefing
    assert ".mode-briefing .storyline-data-details" in briefing
    assert "路線敘事節奏" in briefing
    assert "領隊備註" in briefing
    assert "每一次停留都要換回一個判斷" in briefing
    assert ".mode-briefing .story-speaker-note" in briefing
    assert 'loading="eager" decoding="async"' in briefing
    assert "3 分鐘短停要有目的" in briefing
    assert "Visual evidence gap" not in briefing
    assert "先看照片中的行進方向" in briefing
    assert "status-photo-feature" in briefing
    assert "status-photo-strip" in briefing
    assert "status-cues" in briefing
    assert "source-health-board" in briefing
    assert "source-health-summary" in briefing
    assert "source-health-grid" in briefing
    assert "source-health-card" in briefing
    assert "行前資料查核" in briefing
    assert "先看哪些行程資訊已可支撐討論" in briefing
    assert "缺口處理" in briefing
    assert "更新提醒" in briefing
    assert "人工審查" in briefing
    assert "source-health-details" in briefing
    assert "照片導讀重點" in briefing
    assert "照片只輔助行前理解" in briefing
    assert "map-atlas" in briefing
    assert "map-atlas-hero" in briefing
    assert "map-atlas-layers" in briefing
    assert "地圖深度與廣度" in briefing
    assert "先確認路線尺度，再按距離讀命名節點" in briefing
    assert "官方來源" in briefing
    assert "路線命名點" in briefing
    assert "待查線索" in briefing
    assert "先用一組畫面講完這趟路" in briefing
    assert "四段路線" in briefing
    assert "visual-story-arc" in briefing
    assert "按行程順序看入山、宿點、稜線與短停" in briefing
    assert "photo-essay" in briefing
    assert "photo-essay-feature" in briefing
    assert "photo-essay-grid" in briefing
    assert "photo-essay-card" in briefing
    assert "路線照片與地圖" in briefing
    assert "visual-kit-board" in briefing
    assert "visual-kit-summary" in briefing
    assert "visual-kit-grid" in briefing
    assert "visual-kit-card" in briefing
    assert "visual-kit-score" in briefing
    assert "先看入山、宿點、稜線、短停與天候" in briefing
    assert "照片與地圖的行前主題檢查" in briefing
    assert "可用畫面主題" in briefing
    assert (
        "領隊可依入山、路線走向、宿點、中高山地形、短停觀察與天候季節分類檢查"
        in briefing
    )
    assert "不是增加裝飾圖，而是讓每張圖負責一個行前說明任務" not in briefing
    assert "避免簡報只剩資料欄位" not in briefing
    assert "開場主視覺" not in briefing
    assert "行前照片與地圖狀態" not in briefing
    assert (
        "已檢查開場、路線總覽、宿點、地形、短停與天候季節六類行程畫面" not in briefing
    )
    assert "入山與稜線遠景" in briefing
    assert "路線全段走向圖" in briefing
    assert "宿點與中繼點" in briefing
    assert "地形與通過策略" in briefing
    assert "短停觀察點" in briefing
    assert "雲霧低溫與季節條件" in briefing
    assert "行程參考照片" in briefing
    assert "visual-contact-sheet" in briefing
    assert "visual-contact-grid" in briefing
    assert "visual-contact-card" in briefing
    assert "行程照片清單" in briefing
    assert "待補照片清單" in briefing
    assert "按行程段落檢查哪些路段還缺照片" in briefing
    assert "畫面 01" in briefing
    assert "官方來源" in briefing
    assert "官方照片" in briefing
    assert "<img" in briefing
    assert "路線筆記只作為待查資料" in briefing
    assert "先把路線讀成一張行走地圖" in briefing
    assert "路線閱讀圖" in briefing
    assert "里程節點軸（非高程剖面）" in briefing
    assert "route-focus-strip" in briefing
    assert "路線頁主判斷" in briefing
    assert "目前可確認的路線骨架" in briefing
    assert "先讀距離與節點；不要從點名推測行程用途" in briefing
    assert "route-reader-cues" in briefing
    assert "route-photo-strip" in briefing
    assert "route-data-details" in briefing
    assert "路線畫面補充" in briefing
    assert "命名節點按路線距離整理" in briefing
    assert "現行公告" in briefing
    assert "定位與感測" in briefing
    assert "官方天氣" in briefing
    assert "預定路線方向" in briefing
    assert "工作人員和領隊" in briefing
    assert "CP/MCP" not in briefing
    assert "GNSS" not in briefing
    assert "GPS/IMU" not in briefing
    assert "P2 Scout-owned" not in briefing
    assert "GPX 趨勢" not in briefing
    forbidden_visible_copy = (
        "Route Context Intelligence implementation",
        "Scout AI 產生計畫",
        "compiler",
        "workspace cache",
        "route_context_pack.json",
        "route_context_points.json",
        "source_manifest.json",
        "route_context_briefing.html",
        "Scout Route Context Briefing",
        "Route Context",
        "prompt",
        "提示詞",
        "模型輸出",
        "deterministic",
        "candidate-only",
        "runtime_safety_truth",
        "非安全真值",
        "live_fetch",
        "media provenance",
        "機器可讀",
        "crawl seed",
        "把活動講成可以被記住的四幕",
        "這一頁把照片從素材清單拉回活動語境",
        "隊伍現在要記住什麼",
        "不是把照片貼上去，而是讓照片負責開場",
        "公開簡報先用畫面建立活動感",
        "簡報素材",
        "素材板",
        "講者備註",
        "版型",
        "行前素材狀態",
        "行前候選素材",
        "行前照片與地圖狀態",
        "已檢查開場、路線總覽、宿點、地形、短停與天候季節六類行程畫面",
        "開場主視覺",
        "共同方向感",
        "圖像準備度",
        "行程畫面覆蓋",
        "畫面偏薄",
        "照片與地圖準備度",
        "已配對行程畫面",
        "行前照片資料",
        "補齊 文化層、自然層、地形層 的可追溯照片",
        "再補 6 張路線照片，讓山屋、地形、短停與天候都有畫面",
        "圖像導覽",
        "照片導覽",
        "圖像缺口",
        "畫面索引",
        "把可用圖片一次攤開",
        "先用照片建立路線感",
        "Scout 行前路線簡報",
        "登山活動簡報",
        "簡報導覽",
        "行動簡報章節控制",
        "下一輪採圖清單",
        "採圖清單",
        "review candidate",
        "review priority",
        "CWA/weather evidence",
        "pretrip briefing",
        "contextual permission",
        "Scout AI",
        "review_state=",
        "sensitivity=",
        "advisory=",
    )
    for forbidden in forbidden_visible_copy:
        assert forbidden not in briefing
    assert "路線總覽使用提醒" in briefing
    assert "field-media" in briefing
    assert "layer-definition" in briefing
    assert "talk-row" in briefing
    assert "ask-row" in briefing
    assert "boundary-row" in briefing
    assert "layer-data-details" in briefing
    assert ".mode-briefing .layer-definition" in briefing
    assert ".mode-briefing .script-row.boundary-row" in briefing
    assert "p2-review-board" in briefing
    assert "p2-visual" in briefing
    assert "p2-lens" in briefing
    assert "p2-source-card" in briefing
    assert "隊伍回顧判讀方式" in briefing
    assert "先當回顧" in briefing
    assert "再找佐證" in briefing
    assert "保留邊界" in briefing
    assert "隊伍回顧" in briefing
    assert "隊伍回顧是自有線索" in briefing
    assert "候選點與邊界" in briefing

    assert "短停畫面" in briefing
    assert "risk-review-grid" in briefing
    assert "risk-review-card" in briefing
    assert "risk-visual" in briefing
    assert "risk-scene-label" in briefing
    assert "通過策略" in briefing
    assert "停留條件" in briefing
    assert "撤退提醒" in briefing
    assert "導航檢查" in briefing
    assert "risk-operator-note" in briefing
    assert "risk-data-details" in briefing
    assert ".mode-briefing .risk-data-details" in briefing
    assert "行前提醒" in briefing
    assert "schedule-photo-strip" in briefing
    assert "schedule-focus-strip" in briefing
    assert "行程頁主判斷" in briefing
    assert "領隊先確認證據是否足夠" in briefing
    assert "領隊先確認證據是否足夠" in briefing
    assert "目前只整理命名節點群組" in briefing
    assert '<body class="mode-briefing">' in briefing
    assert 'data-briefing-mode="briefing"' in briefing
    assert 'data-briefing-mode="data"' in briefing
    assert "source-debug-slide" in briefing
    assert "完整來源表與待補資料保留給領隊和工作人員查核" in briefing
    assert "chapter-break" in briefing
    assert "chapter-stage" in briefing
    assert "chapter-visual-card" in briefing
    assert "chapter-visual-photo" in briefing
    assert "chapter-visual-label" in briefing
    assert "chapter-cue-tags" in briefing
    assert "行前候選畫面" in briefing
    assert "不是現地安全結論" in briefing
    assert 'id="chapter-01"' in briefing
    assert "章節 01" in briefing
    assert "先看見這條路" in briefing
    assert "再把路線讀成故事" in briefing
    assert "把停留變成有條件的決策" in briefing
    assert "最後才看資料能信到哪裡" in briefing
    assert "這章要帶隊伍抓住" in briefing
    assert "briefing-deck layers" in briefing
    assert "stop-deck" in briefing
    assert "建議一次只看一層脈絡" in briefing
    assert "短停節奏" in briefing
    assert "source-chips" in briefing
    assert "source-badge" in briefing
    assert "照片來源" in briefing
    assert 'class="nav-primary"' in briefing
    assert 'class="nav-detail"' in briefing
    assert ".mode-briefing nav a.nav-detail" in briefing
    assert ".mode-data nav a.nav-detail" in briefing
    assert "nav-progress" in briefing
    assert "目前章節" in briefing
    assert "data-active-section-label" in briefing
    assert "data-active-section-count" in briefing
    assert "presenter-controls" in briefing
    assert "presenter-icon prev" in briefing
    assert "presenter-icon next" in briefing
    assert 'aria-hidden="true"' in briefing
    assert 'data-presenter-step="-1"' in briefing
    assert 'data-presenter-step="1"' in briefing
    assert "mobile-presenter-dock" in briefing
    assert "mobile-presenter-status" in briefing
    assert "行動行前章節控制" in briefing
    assert "activeLabels.forEach" in briefing
    assert "activeCounts.forEach" in briefing
    assert "mobilePresenterDock" in briefing
    assert "activeNavThreshold" in briefing
    assert "const threshold = activeNavThreshold()" in briefing
    assert "const nearBottom = window.innerHeight + window.scrollY" in briefing
    assert "setActiveLink(visible[visible.length - 1], visible)" in briefing
    assert "goToRelativeSection" in briefing
    assert "presenterLockUntil" in briefing
    assert "presenterButtons.forEach" in briefing
    assert "button.disabled" in briefing
    assert "visual-agenda" in briefing
    assert "visual-agenda-card" in briefing
    assert "visual-agenda-step" in briefing
    assert "行程導覽" in briefing
    assert "先用四張圖抓住行程順序" in briefing
    assert "先確認能回答多少" in briefing
    assert "先看畫面" in briefing
    assert "讀成行走地圖" in briefing
    assert "留緩衝再出發" in briefing
    assert 'href="#days"' in briefing
    assert 'href="#photo-essay"' in briefing
    assert 'href="#visual-kit"' in briefing
    assert 'href="#route"' in briefing
    assert 'href="#schedule"' in briefing
    assert "aria-current" in briefing
    assert "window.addEventListener('scroll', scheduleActiveNav" in briefing
    assert "window.addEventListener('resize', scheduleActiveNav)" in briefing
    assert "navLinks.forEach((link) =>" in briefing
    assert "link.addEventListener('click', (event) =>" in briefing
    assert "event.preventDefault()" in briefing
    assert "previousScrollBehavior" in briefing
    assert "window.scrollTo(0, targetTop)" in briefing
    assert "window.history.pushState" in briefing
    assert "setActiveLink(link, visible)" in briefing
    assert "setActiveLink(active, visible)" in briefing
    assert "count.textContent" in briefing
    assert "需人工審查" in briefing
    assert "現地再確認" in briefing
    assert ".mode-briefing .source-chips" in briefing
    assert ".mode-briefing .source-badge.boundary" in briefing
    assert "@page" in briefing
    assert "size: A4 landscape" in briefing
    assert "print-color-adjust: exact" in briefing
    assert "break-inside: avoid" in briefing
    assert "scroll-margin-top: 72px" in briefing
    assert "scroll-margin-top: 154px" in briefing
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in briefing
    assert "nav, .mode-switch, .mobile-presenter-dock" in briefing
    assert "live_fetch_performed" not in source_manifest["cache_policy"]
    assert source_manifest["cache_policy"]["network_refresh_required"] is True
    assert source_manifest["cache_policy"]["cache_only_answer_allowed"] is False
    assert source_manifest["cache_policy"]["live_source_refresh_status"] in {
        "live_network_refreshed",
        "cache_only_no_live_refresh",
        "legacy_cache_without_network_provenance",
    }
    assert "live_source_refresh_evidence" in source_manifest
    assert project["route_context_evidence_ref"] == ROUTE_CONTEXT_EVIDENCE_REF
    assert (
        project["route_context_source_manifest_ref"]
        == ROUTE_CONTEXT_SOURCE_MANIFEST_REF
    )
    assert project["route_context_pack_ref"] == ROUTE_CONTEXT_PACK_REF
    assert (
        project["route_context_crawl_seed_plan_ref"]
        == ROUTE_CONTEXT_CRAWL_SEED_PLAN_REF
    )
    assert (
        project["route_context_media_manifest_ref"] == ROUTE_CONTEXT_MEDIA_MANIFEST_REF
    )
    assert project["route_context_briefing_ref"] == ROUTE_CONTEXT_BRIEFING_REF
    assert project["route_context_points_ref"] == ROUTE_CONTEXT_POINTS_REF
    assert project["route_context_point_count"] == points["point_count"]
    assert project["route_context_crawl_seed_count"] == crawl_seed_plan["seed_count"]
    assert (
        project["route_context_collection_schema_version"]
        == "route_context_collection.v1"
    )
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
    heishuitang = next(
        point for point in points["points"] if point["display_label"] == "黑水塘"
    )
    assert "named_point" in heishuitang["evidence_families"]
    assert "major_critical_point" in heishuitang["merged_evidence_types"]
    assert heishuitang["observation_score"]["candidate_only"] is True
    assert (
        heishuitang["source_freshness"]["requires_refresh_before_runtime_truth"] is True
    )
    assert heishuitang["display_policy"]["show_label"] is True

    artifact_manifest = build_pretrip_artifact_manifest(
        project_root / "project.json"
    ).to_dict()
    by_kind = {
        artifact["artifact_kind"]: artifact
        for artifact in artifact_manifest["artifacts"]
        if artifact["source"] == "project"
    }
    assert (
        by_kind["route_context_evidence"]["route_context_point_count"]
        == points["point_count"]
    )
    assert by_kind["route_context_source_manifest"]["network_refresh_required"] is True
    assert (
        by_kind["route_context_source_manifest"]["cache_only_answer_allowed"] is False
    )
    assert (
        by_kind["route_context_source_manifest"]["live_source_refresh_status"]
        == source_manifest["cache_policy"]["live_source_refresh_status"]
    )
    assert by_kind["route_context_pack"]["query_mode"] == "cache_first_tool_second"
    assert (
        by_kind["route_context_crawl_seed_plan"]["route_notes_are_conclusion"] is False
    )
    assert (
        by_kind["route_context_media_manifest"]["media_count"]
        == media_manifest["media_count"]
    )
    assert by_kind["route_context_media_manifest"]["media_count"] >= 1
    assert (
        by_kind["route_context_media_manifest"]["anchored_media_count"]
        == media_manifest["media_count"]
    )
    assert by_kind["route_context_media_manifest"]["route_point_media_count"] >= 1
    assert by_kind["route_context_media_manifest"]["has_hero_image"] is True
    assert by_kind["route_context_media_manifest"]["raw_image_embedded"] is False
    assert (
        by_kind["route_context_media_manifest"]["visual_readiness_status"]
        == (media_manifest["visual_readiness"]["status"])
    )
    assert (
        by_kind["route_context_media_manifest"]["visual_quality_gate"]
        == (media_manifest["visual_readiness"]["quality_gate"])
    )
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
    assert (
        route_context_summary["route_note_seed_count"]
        == crawl_seed_plan["route_note_seed_count"]
    )
    assert route_context_summary["briefing_available"] is True
    assert (
        route_context_summary["anchored_media_count"] == media_manifest["media_count"]
    )
    assert route_context_summary["route_point_media_count"] >= 1
    assert route_context_summary["network_refresh_required"] is True
    assert route_context_summary["cache_only_answer_allowed"] is False
    assert (
        route_context_summary["live_source_refresh_status"]
        == source_manifest["cache_policy"]["live_source_refresh_status"]
    )
    assert route_context_summary["runtime_safety_truth"] is False


def test_route_context_collection_no_briefing_refresh_preserves_existing_ref(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(FIXTURE_PROJECT, project_root)

    collect_pretrip_route_context(
        project_root,
        dry_run=False,
        limit_route_notes=8,
        collected_at="2026-06-15T00:00:00Z",
    )
    collect_pretrip_route_context(
        project_root,
        dry_run=False,
        limit_route_notes=8,
        write_briefing=False,
        collected_at="2026-06-15T01:00:00Z",
    )
    project = json.loads((project_root / "project.json").read_text(encoding="utf-8"))

    assert project["route_context_briefing_ref"] == ROUTE_CONTEXT_BRIEFING_REF
    assert (project_root / ROUTE_CONTEXT_BRIEFING_REF).is_file()


def test_route_context_verifier_requires_live_refresh_when_network_allowed(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(FIXTURE_PROJECT, project_root)
    web_path = project_root / "outputs/layers/normalized/web_case_evidence.json"
    web_payload = json.loads(web_path.read_text(encoding="utf-8"))
    web_payload.setdefault("boundary", {})["network_calls_allowed"] = False
    web_payload["boundary"]["network_calls_made"] = False
    web_path.write_text(
        json.dumps(web_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    collect_pretrip_route_context(
        project_root,
        dry_run=False,
        limit_route_notes=8,
        collected_at="2026-06-15T00:00:00Z",
    )
    project = json.loads((project_root / "project.json").read_text(encoding="utf-8"))

    errors: list[str] = []
    summary = _check_route_context_refs(
        project_root,
        project,
        errors,
        allow_network_calls=True,
    )

    assert summary["live_source_refresh_status"] == "cache_only_no_live_refresh"
    assert (
        "route context source manifest missing live source refresh evidence" in errors
    )


def test_route_context_verifier_accepts_live_refresh_evidence_when_network_allowed(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(FIXTURE_PROJECT, project_root)
    web_path = project_root / "outputs/layers/normalized/web_case_evidence.json"
    web_payload = json.loads(web_path.read_text(encoding="utf-8"))
    web_payload["collector_schema_version"] = "pretrip_p0_p1_source_collection.v1"
    web_payload.setdefault("boundary", {})["network_calls_allowed"] = True
    web_payload["boundary"]["network_calls_made"] = True
    web_path.write_text(
        json.dumps(web_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    collect_pretrip_route_context(
        project_root,
        dry_run=False,
        limit_route_notes=8,
        collected_at="2026-06-15T00:00:00Z",
    )
    project = json.loads((project_root / "project.json").read_text(encoding="utf-8"))

    errors: list[str] = []
    summary = _check_route_context_refs(
        project_root,
        project,
        errors,
        allow_network_calls=True,
    )

    assert errors == []
    assert summary["live_source_refresh_status"] == "live_network_refreshed"


def test_route_context_verifier_rejects_deprecated_live_fetch_switch(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(FIXTURE_PROJECT, project_root)

    collect_pretrip_route_context(
        project_root,
        dry_run=False,
        limit_route_notes=8,
        collected_at="2026-06-15T00:00:00Z",
    )
    manifest_path = project_root / ROUTE_CONTEXT_SOURCE_MANIFEST_REF
    source_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_manifest["cache_policy"]["live_fetch_performed"] = False
    manifest_path.write_text(
        json.dumps(source_manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    project = json.loads((project_root / "project.json").read_text(encoding="utf-8"))

    errors: list[str] = []
    _check_route_context_refs(project_root, project, errors)

    assert (
        "route context source manifest uses deprecated live_fetch_performed switch"
        in errors
    )


def test_route_context_collection_normalizes_workspace_k_labels_from_ocr_and_raster(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(FIXTURE_PROJECT, project_root)

    ocr_path = project_root / "outputs" / "mcp" / "mcp_ocr_labels.json"
    ocr_payload = json.loads(ocr_path.read_text(encoding="utf-8"))
    ocr_payload["labels"].append(
        {
            "ocr_label_id": "ocr.k.5_5.fullwidth",
            "label_text": "５．５Ｋ",
            "label_role": "trail_mileage_k_anchor",
            "lat": 24.0492,
            "lon": 121.2401,
            "confidence": 0.82,
            "review_required": False,
            "source_ref": "local_rudy_tw_tile.z15.x26142.y13991",
        }
    )
    ocr_payload["labels"].append(
        {
            "ocr_label_id": "ocr.communication_point.001",
            "label_text": "通訊點（遠傳,台哥大,112）",
            "lat": 24.0501,
            "lon": 121.2399,
            "confidence": 0.81,
            "review_required": True,
            "source_ref": "local_rudy_tw_tile.z15.x26142.y13991",
        }
    )
    ocr_path.write_text(
        json.dumps(ocr_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    raster_path = (
        project_root
        / "outputs"
        / "layers"
        / "normalized"
        / "raster_label_evidence.geojson"
    )
    raster_path.parent.mkdir(parents=True, exist_ok=True)
    raster_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [121.245, 24.053]},
                        "properties": {
                            "id": "raster.k.6",
                            "label": "6km",
                            "label_role": "trail_mileage_k_anchor",
                            "confidence": 0.78,
                            "source_ref": "rudy_tw_runtime_tile",
                        },
                    },
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [121.246, 24.052]},
                        "properties": {
                            "id": "raster.road_k.94",
                            "label": "台14線94K",
                            "confidence": 0.76,
                            "source_ref": "rudy_tw_runtime_tile",
                        },
                    },
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [121.247, 24.051]},
                        "properties": {
                            "id": "raster.contour.1123",
                            "label": "1123",
                            "label_role": "contour_elevation_label",
                            "confidence": 0.73,
                            "source_ref": "rudy_tw_runtime_tile",
                        },
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    collect_pretrip_route_context(
        project_root,
        dry_run=False,
        write_briefing=False,
        collected_at="2026-06-15T00:00:00Z",
    )

    mileage_anchors = json.loads(
        (project_root / ROUTE_MILEAGE_K_ANCHORS_REF).read_text(encoding="utf-8")
    )
    anchors_by_k = {
        anchor["normalized_mileage_k"]: anchor for anchor in mileage_anchors["anchors"]
    }
    points = json.loads(
        (project_root / ROUTE_CONTEXT_POINTS_REF).read_text(encoding="utf-8")
    )

    assert "5.5K" in anchors_by_k
    assert "6K" in anchors_by_k
    assert "94K" not in anchors_by_k
    assert any(
        ref["source_kind"] == "ocr_label_evidence"
        for ref in anchors_by_k["5.5K"]["source_refs"]
    )
    assert any(
        ref["source_kind"] == "raster_label_evidence"
        for ref in anchors_by_k["6K"]["source_refs"]
    )
    assert anchors_by_k["5.5K"]["source_evidence_count"] >= 1
    assert anchors_by_k["6K"]["mileage_m"] == 6000.0
    assert any(
        point["evidence_type"] == "road_mileage_stone"
        and point["normalized_mileage_k"] == "94K"
        for point in points["points"]
    )
    assert any(
        point["evidence_type"] == "cellular_communication_point"
        and point["communication_networks"] == ["遠傳", "台哥大", "112"]
        for point in points["points"]
    )
    assert any(
        point["evidence_type"] == "contour_elevation_label"
        and point["contour_elevation_m"] == 1123.0
        for point in points["points"]
    )


def test_route_context_collection_uses_web_media_in_presentation_html(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(FIXTURE_PROJECT, project_root)
    web_ref = "outputs/layers/normalized/web_case_evidence.json"
    web_path = project_root / web_ref
    web_path.parent.mkdir(parents=True, exist_ok=True)
    bad_image_refs = [
        {
            "url": "https://recreation.forest.gov.tw/image/icon/web-logo/30uu-logotype-primary.svg",
            "alt": "山林悠遊網標示",
            "caption": "山林悠遊網標示",
            "source_tier": "P0",
            "source_family": "official_baseline",
            "page_url": "https://recreation.forest.gov.tw/Trail/RT?tr_id=064",
            "candidate_only": True,
            "runtime_safety_truth": False,
            "raw_image_embedded": False,
        },
        {
            "url": "https://recreation.forest.gov.tw/image/icon/interfaces/search@svg.svg",
            "alt": "搜尋",
            "caption": "搜尋",
            "source_tier": "P0",
            "source_family": "official_baseline",
            "page_url": "https://recreation.forest.gov.tw/Trail/RT?tr_id=064",
            "candidate_only": True,
            "runtime_safety_truth": False,
            "raw_image_embedded": False,
        },
        {
            "url": "https://www.facebook.com/tr?id=2086363621619508&ev=PageView&noscript=1",
            "alt": "",
            "caption": "",
            "source_tier": "P1",
            "source_family": "community_article_evidence",
            "page_url": "https://hiking.biji.co/index.php?act=gpx_detail&id=1133031&q=trail",
            "candidate_only": True,
            "runtime_safety_truth": False,
            "raw_image_embedded": False,
        },
        {
            "url": "https://recreation.forest.gov.tw/image/edu/ForestTherapy_circle.png",
            "alt": "森療 · 身療",
            "caption": "森療 · 身療",
            "source_tier": "P0",
            "source_family": "official_baseline",
            "page_url": "https://recreation.forest.gov.tw/Trail/RT?tr_id=064",
            "candidate_only": True,
            "runtime_safety_truth": False,
            "raw_image_embedded": False,
        },
        {
            "url": "https://example.test/ckfinder/userfiles/images/tltle.png",
            "alt": "路線標題圖",
            "caption": "路線標題圖",
            "source_tier": "P0",
            "source_family": "official_baseline",
            "page_url": "https://example.test/route",
            "candidate_only": True,
            "runtime_safety_truth": False,
            "raw_image_embedded": False,
        },
        {
            "url": "https://example.test/ckfinder/userfiles/images/background.png",
            "alt": "背景森林圖",
            "caption": "背景森林圖",
            "source_tier": "P0",
            "source_family": "official_baseline",
            "page_url": "https://example.test/route",
            "candidate_only": True,
            "runtime_safety_truth": False,
            "raw_image_embedded": False,
        },
    ]
    image_refs = bad_image_refs + [
        {
            "url": "https://example.test/photos/yunhai.jpg",
            "alt": "雲海保線所",
            "caption": "雲海保線所",
            "source_tier": "P0",
            "source_family": "official_baseline",
            "page_url": "https://recreation.forest.gov.tw/Trail/RT?tr_id=064",
            "candidate_only": True,
            "runtime_safety_truth": False,
            "raw_image_embedded": False,
        },
        {
            "url": "https://example.test/photos/guangbei.jpg",
            "alt": "光被八表雲海日出",
            "caption": "光被八表雲海日出",
            "source_tier": "P0",
            "source_family": "official_baseline",
            "page_url": "https://recreation.forest.gov.tw/Trail/RT?tr_id=064",
            "candidate_only": True,
            "runtime_safety_truth": False,
            "raw_image_embedded": False,
        },
        *[
            {
                "url": f"https://example.test/photos/context-{index}.jpg",
                "alt": f"奇萊南華路線補充畫面 {index}",
                "caption": f"奇萊南華路線補充畫面 {index}",
                "source_tier": "P1",
                "source_family": "community_article_evidence",
                "page_url": "https://example.test/p1/chilai-nanhua",
                "candidate_only": True,
                "runtime_safety_truth": False,
                "raw_image_embedded": False,
            }
            for index in range(3, 9)
        ],
    ]
    image_refs.append(
        {
            "url": "https://example.test/photos/context-8.jpg?utm_source=duplicate",
            "alt": "奇萊南華路線補充畫面 8 duplicate",
            "caption": "奇萊南華路線補充畫面 8 duplicate",
            "source_tier": "P1",
            "source_family": "community_article_evidence",
            "page_url": "https://example.test/p1/chilai-nanhua",
            "candidate_only": True,
            "runtime_safety_truth": False,
            "raw_image_embedded": False,
        }
    )
    image_refs[len(bad_image_refs) + 2]["alt"] = "能高越嶺道西段導覽圖"
    image_refs[len(bad_image_refs) + 2]["caption"] = "能高越嶺道西段導覽圖"
    web_path.write_text(
        json.dumps(
            {
                "artifact_kind": "pretrip_web_case_evidence",
                "schema_version": "route_corridor_map_preparation.v1",
                "project_id": "chilai_nanhua_day1",
                "status": "ready_from_p0_p1_sources",
                "points": [
                    {
                        "candidate_id": "web_case.official.forest_trail_064",
                        "label": "能高越嶺道官方照片",
                        "title": "能高越嶺道官方照片",
                        "summary": "奇萊南華沿途高山草坡、雲海保線所與光被八表。",
                        "url": "https://recreation.forest.gov.tw/Trail/RT?tr_id=064",
                        "source_tier": "P0",
                        "source_family": "official_baseline",
                        "source_families": ["official_baseline"],
                        "candidate_only": True,
                        "runtime_safety_truth": False,
                        "image_refs": image_refs,
                    }
                ],
                "counts": {"by_source_tier": {"P0": 1}},
                "boundary": {
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                    "raw_html_embedded_in_json": False,
                    "large_scraped_text_embedded": False,
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    project_path = project_root / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project["web_case_evidence_ref"] = web_ref
    project_path.write_text(
        json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    collect_pretrip_route_context(
        project_root,
        dry_run=False,
        limit_route_notes=8,
        collected_at="2026-06-15T00:00:00Z",
    )

    media_manifest = json.loads(
        (project_root / ROUTE_CONTEXT_MEDIA_MANIFEST_REF).read_text(encoding="utf-8")
    )
    briefing = (project_root / ROUTE_CONTEXT_BRIEFING_REF).read_text(encoding="utf-8")
    assert media_manifest["media_count"] == 8
    assert media_manifest["available_media_count"] == 9
    assert media_manifest["deduped_media_count"] == 8
    assert media_manifest["duplicate_media_count"] == 1
    assert media_manifest["overflow_media_count"] == 0
    assert media_manifest["anchored_media_count"] == 8
    assert media_manifest["gallery_image_limit"] == 18
    assert len(media_manifest["gallery_images"]) == 8
    assert media_manifest["image_curation"]["coverage_status"] == "thin"
    assert media_manifest["image_curation"]["target_min_gallery_images"] == 12
    assert media_manifest["image_curation"]["target_max_gallery_images"] == 18
    assert media_manifest["image_curation"]["duplicate_media_count"] == 1
    assert media_manifest["image_curation"]["missing_context_layers"]
    assert media_manifest["visual_readiness"]["status"] == "thin"
    assert media_manifest["visual_readiness"]["label"] == "部分路段待補查"
    assert media_manifest["visual_readiness"]["quality_gate"] == "warn_missing_layers"
    assert media_manifest["visual_readiness"]["missing_image_count_to_target"] == 4
    assert media_manifest["visual_kit"]["slot_count"] == 6
    assert media_manifest["visual_kit_ready_count"] >= 2
    assert media_manifest["visual_kit_missing_count"] <= 4
    assert media_manifest["visual_kit"]["candidate_only"] is True
    assert media_manifest["visual_kit"]["runtime_safety_truth"] is False
    missing_slots = [
        slot
        for slot in media_manifest["visual_kit"]["slots"]
        if slot["status"] == "missing"
    ]
    assert all(slot["missing_action"] for slot in missing_slots)
    assert {slot["slot_id"] for slot in media_manifest["visual_kit"]["slots"]} == {
        "route_cover",
        "route_map",
        "lodging_nodes",
        "terrain_passage",
        "three_minute_stop",
        "weather_season",
    }
    assert (
        media_manifest["hero_image"]["url"] == "https://example.test/photos/yunhai.jpg"
    )
    assert (
        media_manifest["hero_image"]["presentation_anchor"]["anchor_kind"]
        == "route_point"
    )
    assert media_manifest["hero_image"]["presentation_anchor"]["label"] == "雲海保線所"
    assert media_manifest["boundary"]["raw_image_embedded"] is False
    media_urls = {image["url"] for image in media_manifest["gallery_images"]}
    assert all(image["url"] not in media_urls for image in bad_image_refs)
    assert "Visual evidence gap" not in briefing
    assert "https://example.test/photos/yunhai.jpg" in briefing
    assert "https://example.test/photos/guangbei.jpg" in briefing
    assert "https://example.test/photos/context-8.jpg" in briefing
    assert "30uu-logotype-primary.svg" not in briefing
    assert "search@svg.svg" not in briefing
    assert "facebook.com/tr" not in briefing
    assert "ForestTherapy_circle.png" not in briefing
    map_atlas_fragment = briefing[
        briefing.index('class="map-atlas"') : briefing.index('class="map-layer-card"')
    ]
    assert "https://example.test/photos/context-3.jpg" in map_atlas_fragment
    assert "https://example.test/photos/yunhai.jpg" not in map_atlas_fragment
    assert "畫面 08" in briefing
    assert "出發前補查路段" in briefing
    assert "部分路段待補查" in briefing
    assert "待補查" in briefing
    assert "8 / 12" in briefing
    assert "visual-contact-sheet" in briefing
    assert "行程照片清單" in briefing
    assert briefing.count('<figure class="visual-contact-card">') == 8
    assert briefing.count('<article class="visual-anchor">') == 8
    assert "先看照片中的行進方向" in briefing
    assert "來源圖片分類" in briefing
    assert "按來源主題分類" in briefing
    assert "可用畫面主題" in briefing
    assert "整理成三組命名節點" in briefing
    assert "再把每張照片對回行程段落" not in briefing
    assert "已對應行程段落" not in briefing
    assert "整理成前段、中段與後段" not in briefing
    assert "<img" in briefing


def test_builtin_route_context_collect_tool_runs_with_authorization(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(FIXTURE_PROJECT, project_root)
    for ref in (
        ROUTE_CONTEXT_EVIDENCE_REF,
        ROUTE_CONTEXT_SOURCE_MANIFEST_REF,
        ROUTE_CONTEXT_PACK_REF,
        ROUTE_CONTEXT_CRAWL_SEED_PLAN_REF,
        ROUTE_CONTEXT_MEDIA_MANIFEST_REF,
        ROUTE_CONTEXT_BRIEFING_REF,
        ROUTE_CONTEXT_POINTS_REF,
    ):
        path = project_root / ref
        if path.exists():
            path.unlink()
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


def test_route_context_assessor_reads_collected_canonical_points(
    tmp_path: Path,
) -> None:
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
    source_kinds = {source["source_kind"] for source in result["source_report"]}
    assert "route_context_points" in source_kinds
    assert "黑水塘" in {item["label"] for item in result["results"]}


def test_route_context_collection_marks_sensitive_cultural_points(
    tmp_path: Path,
) -> None:
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

    points = json.loads(
        (project_root / ROUTE_CONTEXT_POINTS_REF).read_text(encoding="utf-8")
    )
    sensitive = next(
        point
        for point in points["points"]
        if point["display_label"] == "舊社獵徑禁忌地"
    )
    assert sensitive["sensitivity_level"] == "restricted"
    assert sensitive["display_policy"]["show_exact_coordinate"] is False
    assert sensitive["display_policy"]["requires_human_review_before_display"] is True
    assert "cultural" in sensitive["sec6_layers"]
    assert points["counts"]["by_sensitivity_level"]["restricted"] >= 1


def test_route_context_briefing_skill_pins_visual_map_source_template() -> None:
    skill = (
        REPO_ROOT / ".agents" / "skills" / "scout-route-context-briefing" / "SKILL.md"
    ).read_text(encoding="utf-8")
    template = (
        REPO_ROOT / "skills" / "scout" / "route-briefing-compose.yaml"
    ).read_text(encoding="utf-8")

    for expected in (
        "Visual / Map Briefing Template",
        "Product Copy Gate",
        "Scout AI/OpenRouter regeneration",
        "deterministic compiler",
        "Do not hardcode Chilai, Nengao, or any previous route's URLs",
        "visual kit",
        "map atlas",
        "source tier spine",
        "historical, cultural, natural, terrain, seasonal",
        "bold expedition palette",
        "出發前補查路段",
        "照片與地圖對應的行程段落",
        "入山與稜線遠景",
        "路線全段走向圖",
        "宿點與中繼點",
        "短停觀察點",
        "雲霧低溫與季節條件",
        "Scan visible HTML text",
        "script`, `style`, SVG, and JSON payloads removed",
    ):
        assert expected in skill
    for expected in (
        "visual_kit",
        "map_atlas",
        "source_tier_spine",
        "source_tiers_required",
        "bold_expedition",
        "candidate_only: true",
        "runtime_safety_truth: false",
    ):
        assert expected in template
