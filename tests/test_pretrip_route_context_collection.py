from __future__ import annotations

import json
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
    assert result["outputs"]["route_context_media_manifest_ref"] == ROUTE_CONTEXT_MEDIA_MANIFEST_REF
    assert result["outputs"]["route_context_briefing_ref"] == ROUTE_CONTEXT_BRIEFING_REF
    assert result["outputs"]["route_context_points_ref"] == ROUTE_CONTEXT_POINTS_REF

    source_status = {
        source["source_kind"]: source["status"] for source in result["source_report"]
    }
    assert source_status["mcp_candidates"] == "loaded"
    assert source_status["named_point_evidence"] == "loaded"
    assert source_status["route_note_candidates"] == "loaded"
    assert source_status["web_case_evidence"] == "loaded"
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
    media_manifest_path = project_root / ROUTE_CONTEXT_MEDIA_MANIFEST_REF
    briefing_path = project_root / ROUTE_CONTEXT_BRIEFING_REF
    points_path = project_root / ROUTE_CONTEXT_POINTS_REF
    assert evidence_path.is_file()
    assert source_manifest_path.is_file()
    assert pack_path.is_file()
    assert crawl_seed_plan_path.is_file()
    assert media_manifest_path.is_file()
    assert briefing_path.is_file()
    assert points_path.is_file()

    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    crawl_seed_plan = json.loads(crawl_seed_plan_path.read_text(encoding="utf-8"))
    media_manifest = json.loads(media_manifest_path.read_text(encoding="utf-8"))
    briefing = briefing_path.read_text(encoding="utf-8")
    points = json.loads(points_path.read_text(encoding="utf-8"))
    project = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    labels = {point["display_label"] for point in points["points"]}
    assert evidence["artifact_kind"] == "pretrip_route_context_evidence"
    assert source_manifest["artifact_kind"] == "pretrip_route_context_source_manifest"
    assert pack["artifact_kind"] == "pretrip_route_context_pack"
    assert crawl_seed_plan["artifact_kind"] == "pretrip_route_context_crawl_seed_plan"
    assert media_manifest["artifact_kind"] == "pretrip_route_context_media_manifest"
    assert points["artifact_kind"] == "pretrip_route_context_points"
    assert evidence["route_context_points_ref"] == ROUTE_CONTEXT_POINTS_REF
    assert evidence["source_manifest_ref"] == ROUTE_CONTEXT_SOURCE_MANIFEST_REF
    assert evidence["route_context_pack_ref"] == ROUTE_CONTEXT_PACK_REF
    assert evidence["crawl_seed_plan_ref"] == ROUTE_CONTEXT_CRAWL_SEED_PLAN_REF
    assert pack["source_manifest_ref"] == ROUTE_CONTEXT_SOURCE_MANIFEST_REF
    assert pack["route_context_points_ref"] == ROUTE_CONTEXT_POINTS_REF
    assert pack["crawl_seed_plan_ref"] == ROUTE_CONTEXT_CRAWL_SEED_PLAN_REF
    assert pack["route_context_media_manifest_ref"] == ROUTE_CONTEXT_MEDIA_MANIFEST_REF
    assert pack["route_summary"]["raw_route_points_embedded"] is False
    assert crawl_seed_plan["route_note_seed_policy"]["route_notes_are_conclusion"] is False
    assert crawl_seed_plan["route_note_seed_policy"]["route_notes_are_seed_material"] is True
    assert crawl_seed_plan["route_note_seed_count"] > 0
    assert "奇萊-南華" in crawl_seed_plan["route_keywords"]
    assert all("每日記錄" not in keyword for keyword in crawl_seed_plan["route_keywords"])
    assert "Scout Route Context Briefing" in briefing
    for section_id in (
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
    assert "預計幾天可以完成" in briefing
    assert "沿途停看聽導覽卡" in briefing
    assert "看什麼" in briefing
    assert "隊伍提問" in briefing
    assert "highlight-guide-cue" in briefing
    assert "highlight-question" in briefing
    assert "highlight-data-details" in briefing
    assert ".mode-briefing .highlight-data-details" in briefing
    assert "把路線拆成六個脈絡層" in briefing
    assert "講給隊伍聽" in briefing
    assert "現場提問" in briefing
    assert "把地形說成通過策略" in briefing
    assert "文化敏感點只作 review candidate" in briefing
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
    assert "缺任一條件就排除" in briefing
    assert "出發前行程審查板" in briefing
    assert "schedule-decision-board" in briefing
    assert "schedule-gate-panel" in briefing
    assert "schedule-gates" in briefing
    assert "領隊確認天氣、路況、山屋與隊伍狀態" in briefing
    assert "先確認能不能照原計畫走" in briefing
    assert "採用條件" in briefing
    assert "建議主案" in briefing
    assert "觀察主案" in briefing
    assert "schedule-board" in briefing
    assert "標準完成版" in briefing
    assert "慢走觀察版" in briefing
    assert "D1" in briefing
    assert "D2" in briefing
    assert "D3" in briefing
    assert "壓縮行程只保留為人工核准候選" in briefing
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
    assert "P0 / P1 / P2 來源脊柱" in briefing
    assert "官方、擴展、自有回顧要分開看" in briefing
    assert "官方底線" in briefing
    assert "擴展脈絡" in briefing
    assert "Scout 回顧" in briefing
    assert "信任摘要" in briefing
    assert "可追溯資料" in briefing
    assert "缺口" in briefing
    assert "安全邊界" in briefing
    assert "切到資料模式可看完整來源表" in briefing
    assert "展開完整來源表與 crawl seed" in briefing
    assert "visual-anchor-board" in briefing
    assert "照片路標" in briefing
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
    assert "講者備註" in briefing
    assert "每一次停留都要換回一個判斷" in briefing
    assert ".mode-briefing .story-speaker-note" in briefing
    assert 'loading="eager" decoding="async"' in briefing
    assert "3 分鐘短停要有目的" in briefing
    assert "Visual evidence gap" not in briefing
    assert "先用照片建立路線感" in briefing
    assert "status-photo-feature" in briefing
    assert "status-photo-strip" in briefing
    assert "status-cues" in briefing
    assert "source-health-board" in briefing
    assert "source-health-summary" in briefing
    assert "source-health-grid" in briefing
    assert "source-health-card" in briefing
    assert "operator data mode" in briefing
    assert "來源健康先讀，再給 Scout AI 回答" in briefing
    assert "缺口處理" in briefing
    assert "快取策略" in briefing
    assert "安全邊界" in briefing
    assert "source-health-details" in briefing
    assert "照片導讀重點" in briefing
    assert "照片只輔助行前理解" in briefing
    assert "map-atlas" in briefing
    assert "map-atlas-hero" in briefing
    assert "map-atlas-layers" in briefing
    assert "地圖深度與廣度" in briefing
    assert "先用地圖建立廣度，再用節點建立深度" in briefing
    assert "P0 官方底圖" in briefing
    assert "P1 擴展地圖" in briefing
    assert "P2 走過的痕跡" in briefing
    assert "先用一組畫面講完這趟路" in briefing
    assert "四幕導覽" in briefing
    assert "visual-story-arc" in briefing
    assert "把活動講成可以被記住的四幕" in briefing
    assert "photo-essay" in briefing
    assert "photo-essay-feature" in briefing
    assert "photo-essay-grid" in briefing
    assert "photo-essay-card" in briefing
    assert "簡報素材板" in briefing
    assert "visual-kit-board" in briefing
    assert "visual-kit-summary" in briefing
    assert "visual-kit-grid" in briefing
    assert "visual-kit-card" in briefing
    assert "visual-kit-score" in briefing
    assert "每張圖都要負責一個行前判斷" in briefing
    assert "不是增加裝飾圖，而是讓每張圖負責一個行前說明任務" in briefing
    assert "開場主視覺" in briefing
    assert "路線總覽圖" in briefing
    assert "宿點與中繼節點" in briefing
    assert "地形與通過策略" in briefing
    assert "3 分鐘觀察點" in briefing
    assert "天候與季節畫面" in briefing
    assert "行前候選素材" in briefing
    assert "visual-contact-sheet" in briefing
    assert "visual-contact-grid" in briefing
    assert "visual-contact-card" in briefing
    assert "畫面索引" in briefing
    assert "下一輪採圖清單" in briefing
    assert "把可用圖片一次攤開" in briefing
    assert "畫面 01" in briefing
    assert "官方來源" in briefing
    assert "官方照片" in briefing
    assert "<img" in briefing
    assert "runtime_safety_truth=false" in briefing
    assert "路線筆記只作為收集線索" in briefing
    assert "先把路線讀成一張行走地圖" in briefing
    assert "路線閱讀圖" in briefing
    assert "先看節奏，再看節點" in briefing
    assert "route-focus-strip" in briefing
    assert "路線頁主判斷" in briefing
    assert "領隊先講這三件事" in briefing
    assert "先建立路線節奏，再決定哪些點要停、哪些點要快通過" in briefing
    assert "route-reader-cues" in briefing
    assert "route-photo-strip" in briefing
    assert "route-data-details" in briefing
    assert "路線畫面補充" in briefing
    assert "每個檢查點" in briefing
    assert "定位訊號" in briefing
    assert "定位與感測" in briefing
    assert "官方天氣" in briefing
    assert "預定路線方向" in briefing
    assert "工作人員和領隊" in briefing
    assert "CP/MCP" not in briefing
    assert "GNSS" not in briefing
    assert "GPS/IMU" not in briefing
    assert "P2 Scout-owned" not in briefing
    assert "GPX 趨勢" not in briefing
    assert "資料邊界" in briefing
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
    assert "Scout 回顧判讀方式" in briefing
    assert "先當回顧" in briefing
    assert "再找佐證" in briefing
    assert "保留邊界" in briefing
    assert "Scout 回顧" in briefing
    assert "Scout 回顧是自有線索" in briefing
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
    assert "資料與邊界" in briefing
    assert "schedule-photo-strip" in briefing
    assert "schedule-focus-strip" in briefing
    assert "行程頁主判斷" in briefing
    assert "領隊先做版本選擇" in briefing
    assert "主案是 2 天 1 夜" in briefing
    assert "壓縮行程不進預設建議" in briefing
    assert '<body class="mode-briefing">' in briefing
    assert 'data-briefing-mode="briefing"' in briefing
    assert 'data-briefing-mode="data"' in briefing
    assert "source-debug-slide" in briefing
    assert "完整來源表、收集線索與機器可讀邊界保留在資料模式" in briefing
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
    assert "簡報節奏" in briefing
    assert "短停節奏" in briefing
    assert "source-chips" in briefing
    assert "source-badge" in briefing
    assert "media provenance" in briefing
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
    assert "行動簡報章節控制" in briefing
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
    assert "簡報視覺議程" in briefing
    assert "先用四張圖抓住簡報順序" in briefing
    assert "先決定節奏" in briefing
    assert "先看畫面" in briefing
    assert "讀成行走地圖" in briefing
    assert "留緩衝再出發" in briefing
    assert 'href="#days"' in briefing
    assert 'href="#photo-essay"' in briefing
    assert 'href="#visual-kit"' in briefing
    assert 'href="#route"' in briefing
    assert 'href="#schedule"' in briefing
    assert 'aria-current' in briefing
    assert 'window.addEventListener(\'scroll\', scheduleActiveNav' in briefing
    assert 'window.addEventListener(\'resize\', scheduleActiveNav)' in briefing
    assert "navLinks.forEach((link) =>" in briefing
    assert "link.addEventListener('click', (event) =>" in briefing
    assert "event.preventDefault()" in briefing
    assert "previousScrollBehavior" in briefing
    assert "window.scrollTo(0, targetTop)" in briefing
    assert "window.history.pushState" in briefing
    assert "setActiveLink(link, visible)" in briefing
    assert "setActiveLink(active, visible)" in briefing
    assert "count.textContent" in briefing
    assert "candidate-only" in briefing
    assert "需人工審查" in briefing
    assert "非安全真值" in briefing
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
    assert source_manifest["cache_policy"]["live_fetch_performed"] is False
    assert project["route_context_evidence_ref"] == ROUTE_CONTEXT_EVIDENCE_REF
    assert project["route_context_source_manifest_ref"] == ROUTE_CONTEXT_SOURCE_MANIFEST_REF
    assert project["route_context_pack_ref"] == ROUTE_CONTEXT_PACK_REF
    assert project["route_context_crawl_seed_plan_ref"] == ROUTE_CONTEXT_CRAWL_SEED_PLAN_REF
    assert project["route_context_media_manifest_ref"] == ROUTE_CONTEXT_MEDIA_MANIFEST_REF
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
    assert by_kind["route_context_media_manifest"]["media_count"] == media_manifest["media_count"]
    assert by_kind["route_context_media_manifest"]["media_count"] >= 1
    assert by_kind["route_context_media_manifest"]["anchored_media_count"] == media_manifest["media_count"]
    assert by_kind["route_context_media_manifest"]["route_point_media_count"] >= 1
    assert by_kind["route_context_media_manifest"]["has_hero_image"] is True
    assert by_kind["route_context_media_manifest"]["raw_image_embedded"] is False
    assert by_kind["route_context_media_manifest"]["visual_readiness_status"] == (
        media_manifest["visual_readiness"]["status"]
    )
    assert by_kind["route_context_media_manifest"]["visual_quality_gate"] == (
        media_manifest["visual_readiness"]["quality_gate"]
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
    assert route_context_summary["route_note_seed_count"] == crawl_seed_plan["route_note_seed_count"]
    assert route_context_summary["briefing_available"] is True
    assert route_context_summary["anchored_media_count"] == media_manifest["media_count"]
    assert route_context_summary["route_point_media_count"] >= 1
    assert route_context_summary["live_fetch_performed"] is False
    assert route_context_summary["runtime_safety_truth"] is False


def test_route_context_collection_uses_web_media_in_presentation_html(tmp_path: Path) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(FIXTURE_PROJECT, project_root)
    web_ref = "outputs/layers/normalized/web_case_evidence.json"
    web_path = project_root / web_ref
    web_path.parent.mkdir(parents=True, exist_ok=True)
    image_refs = [
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
    image_refs[2]["alt"] = "能高越嶺道西段導覽圖"
    image_refs[2]["caption"] = "能高越嶺道西段導覽圖"
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
    project_path.write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")

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
    assert media_manifest["visual_readiness"]["label"] == "畫面偏薄"
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
    assert {
        slot["slot_id"] for slot in media_manifest["visual_kit"]["slots"]
    } == {
        "route_cover",
        "route_map",
        "lodging_nodes",
        "terrain_passage",
        "three_minute_stop",
        "weather_season",
    }
    assert media_manifest["hero_image"]["url"] == "https://example.test/photos/yunhai.jpg"
    assert media_manifest["hero_image"]["presentation_anchor"]["anchor_kind"] == "route_point"
    assert media_manifest["hero_image"]["presentation_anchor"]["label"] == "雲海保線所"
    assert media_manifest["boundary"]["raw_image_embedded"] is False
    assert "Visual evidence gap" not in briefing
    assert "https://example.test/photos/yunhai.jpg" in briefing
    assert "https://example.test/photos/guangbei.jpg" in briefing
    assert "https://example.test/photos/context-8.jpg" in briefing
    map_atlas_fragment = briefing[
        briefing.index('class="map-atlas"') : briefing.index(
            'class="map-layer-card"'
        )
    ]
    assert "https://example.test/photos/context-3.jpg" in map_atlas_fragment
    assert "https://example.test/photos/yunhai.jpg" not in map_atlas_fragment
    assert "畫面 08" in briefing
    assert "圖像準備度" in briefing
    assert "畫面偏薄" in briefing
    assert "8 / 12" in briefing
    assert "visual-contact-sheet" in briefing
    assert "畫面索引" in briefing
    assert briefing.count('<figure class="visual-contact-card">') == 8
    assert briefing.count('<article class="visual-anchor">') == 8
    assert "先用照片建立路線感" in briefing
    assert "照片路標" in briefing
    assert "<img" in briefing


def test_builtin_route_context_collect_tool_runs_with_authorization(tmp_path: Path) -> None:
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
    source_kinds = {source["source_kind"] for source in result["source_report"]}
    assert "route_context_points" in source_kinds
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


def test_route_context_briefing_skill_pins_visual_map_source_template() -> None:
    skill = (REPO_ROOT / ".agents" / "skills" / "scout-route-context-briefing" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    template = (REPO_ROOT / "skills" / "scout" / "route-briefing-compose.yaml").read_text(
        encoding="utf-8"
    )

    for expected in (
        "Visual / Map Briefing Template",
        "visual kit",
        "map atlas",
        "source tier spine",
        "historical, cultural, natural, terrain, seasonal",
        "bold expedition palette",
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
