from __future__ import annotations

import json
import shutil
from pathlib import Path

from pretrip_p0_p1_source_collection import (
    DEFAULT_P0_P1_SOURCE_CATALOG,
    DEFAULT_WEB_CASE_EVIDENCE_REF,
    DEFAULT_WEB_CASE_QUERY_PLAN_REF,
    collect_pretrip_p0_p1_sources,
)
from pretrip_route_context_collection import (
    ROUTE_CONTEXT_BRIEFING_REF,
    ROUTE_CONTEXT_MEDIA_MANIFEST_REF,
    ROUTE_CONTEXT_POINTS_REF,
    collect_pretrip_route_context,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PROJECT = REPO_ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"


def test_p0_p1_source_collection_defaults_to_generic_catalog_without_route_urls(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(FIXTURE_PROJECT, project_root)

    result = collect_pretrip_p0_p1_sources(
        project_root,
        dry_run=True,
        generated_at="2026-06-15T00:00:00Z",
    )

    query_plan = result["planned_artifacts"]["query_plan"]
    evidence = result["planned_artifacts"]["evidence"]
    catalog = query_plan["source_catalog"]
    assert result["source_count"] == 0
    assert result["evidence_item_count"] == 0
    assert query_plan["status"] == "planned_requires_source_discovery"
    assert evidence["status"] == "planned_requires_source_discovery"
    assert query_plan["sources"] == []
    assert query_plan["source_policy"]["default_route_specific_sources"] is False
    assert query_plan["source_policy"]["catalog_role"] == "search_scope_only"
    assert query_plan["source_catalog_count"] == len(DEFAULT_P0_P1_SOURCE_CATALOG) == 27
    assert {source["source_tier"] for source in catalog} == {"P0", "P1"}
    assert {source["source_family"] for source in catalog} >= {
        "official_baseline",
        "official_status",
        "terrain_baseline",
        "weather_baseline",
        "hazard_baseline",
        "incident_baseline",
        "incident_local_baseline",
        "incident_open_data_baseline",
        "natural_baseline",
        "historical_map_baseline",
        "cultural_trail_baseline",
        "cultural_expansion",
        "historical_expansion",
        "cultural_spatial_expansion",
        "geology_expansion",
        "map_expansion",
        "community_route_seed",
        "community_article_evidence",
        "community_route_evidence",
        "rescue_training_reference",
        "field_rescue_expert_observation",
        "community_media_evidence",
    }
    assert all("url" not in source for source in catalog)
    assert any(
        source["source_tier"] == "P0"
        and source["source_family"] == "cultural_trail_baseline"
        and source["label"] == "尋路・循路－臺灣原住民族古道空間資訊網"
        for source in catalog
    )


def test_p0_p1_source_collection_writes_web_case_evidence_without_live_network(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(FIXTURE_PROJECT, project_root)
    sources = [
        {
            "source_id": "forest_tianchi_open_20260613",
            "source_tier": "P0",
            "source_family": "official_forest_notice",
            "label": "天池山莊開放公告",
            "url": "https://example.test/p0/tianchi",
        },
        {
            "source_id": "hiking_biji_chilai_nanhua",
            "source_tier": "P1",
            "source_family": "community_route_profile",
            "label": "健行筆記奇萊南華",
            "url": "https://example.test/p1/chilai-nanhua",
        },
    ]
    bodies = {
        "https://example.test/p0/tianchi": """
        <html><head><title>能高越嶺西段與天池山莊開放</title>
        <meta property="og:image" content="/photos/tianchi-cover.jpg">
        </head>
        <body><h1>天池山莊公告</h1>
        <img src="/photos/tianchi.jpg" alt="天池山莊">
        <p>奇萊-南華路線需要注意入園申請、住宿規定與夜間通行風險。</p>
        <p>能高越嶺路段仍有落石風險，僅作出發前候選 evidence。</p></body></html>
        """,
        "https://example.test/p1/chilai-nanhua": """
        <html><head><title>奇萊南華路線介紹</title>
        <link rel="image_src" href="https://example.test/assets/route-cover.jpg">
        </head>
        <body><h1>奇萊南華</h1>
        <picture><source srcset="https://example.test/assets/ridge-large.jpg 1200w, https://example.test/assets/ridge-small.jpg 600w"></picture>
        <img src="https://example.test/assets/guangbei.jpg" alt="光被八表">
        <p>奇萊南華常見經過雲海保線所、天池山莊、光被八表與南華山。</p>
        <p>健行紀錄可作 route context seed，不是 runtime safety truth。</p></body></html>
        """,
    }

    def fake_fetcher(url: str, timeout_seconds: float) -> dict[str, object]:
        assert timeout_seconds == 7.0
        return {
            "ok": True,
            "status_code": 200,
            "content_type": "text/html; charset=utf-8",
            "body": bodies[url],
        }

    result = collect_pretrip_p0_p1_sources(
        project_root,
        allow_network_fetch=True,
        source_records=sources,
        route_keywords=["奇萊-南華"],
        generated_at="2026-06-15T00:00:00Z",
        timeout_seconds=7.0,
        fetcher=fake_fetcher,
    )

    assert result["writes_performed"] is True
    assert result["evidence_item_count"] == 2
    assert result["network_calls_made"] is True
    assert result["boundary"]["candidate_only"] is True
    assert result["boundary"]["runtime_safety_truth"] is False

    query_plan = json.loads((project_root / DEFAULT_WEB_CASE_QUERY_PLAN_REF).read_text(encoding="utf-8"))
    evidence = json.loads((project_root / DEFAULT_WEB_CASE_EVIDENCE_REF).read_text(encoding="utf-8"))
    project = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    assert query_plan["artifact_kind"] == "pretrip_web_case_query_plan"
    assert query_plan["schema_version"] == "route_corridor_map_preparation.v1"
    assert query_plan["network_policy"]["explicit_fetch_required"] is True
    assert evidence["artifact_kind"] == "pretrip_web_case_evidence"
    assert evidence["schema_version"] == "route_corridor_map_preparation.v1"
    assert evidence["status"] == "ready_from_p0_p1_sources"
    assert evidence["counts"]["by_source_tier"] == {"P0": 1, "P1": 1}
    assert evidence["boundary"]["raw_html_embedded_in_json"] is False
    assert evidence["boundary"]["large_scraped_text_embedded"] is False
    assert evidence["points"][0]["candidate_only"] is True
    assert evidence["points"][0]["runtime_safety_truth"] is False
    p0_image_urls = {image["url"] for image in evidence["points"][0]["image_refs"]}
    p1_image_urls = {image["url"] for image in evidence["points"][1]["image_refs"]}
    assert "https://example.test/photos/tianchi-cover.jpg" in p0_image_urls
    assert "https://example.test/photos/tianchi.jpg" in p0_image_urls
    assert all(image["raw_image_embedded"] is False for image in evidence["points"][0]["image_refs"])
    assert "https://example.test/assets/route-cover.jpg" in p1_image_urls
    assert "https://example.test/assets/ridge-large.jpg" in p1_image_urls
    assert "https://example.test/assets/guangbei.jpg" in p1_image_urls
    assert project["web_case_evidence_ref"] == DEFAULT_WEB_CASE_EVIDENCE_REF
    assert project["web_case_evidence_count"] == 2

    route_context = collect_pretrip_route_context(
        project_root,
        dry_run=False,
        limit_route_notes=4,
        collected_at="2026-06-15T00:00:01Z",
    )
    web_source = next(
        source
        for source in route_context["source_report"]
        if source["source_kind"] == "web_case_evidence"
    )
    assert web_source["status"] == "loaded"
    assert web_source["loaded_count"] == 2
    assert web_source["source_tier"] == "mixed:P0/P1"
    assert web_source["source_tier_counts"] == {"P0": 1, "P1": 1}
    points = json.loads((project_root / ROUTE_CONTEXT_POINTS_REF).read_text(encoding="utf-8"))
    web_points = [
        point
        for point in points["points"]
        if point["evidence_type"] == "web_case_evidence"
    ]
    assert points["counts"]["by_evidence_type"]["web_case_evidence"] == 2
    assert {point["source_tier"] for point in web_points} == {"P0", "P1"}
    assert any(
        point["display_label"] == "奇萊南華路線介紹"
        and point["runtime_safety_truth"] is False
        for point in points["points"]
    )


def test_p0_p1_source_collection_requires_explicit_network_fetch(tmp_path: Path) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(FIXTURE_PROJECT, project_root)

    def blocked_fetcher(url: str, timeout_seconds: float) -> dict[str, object]:
        raise AssertionError(f"unexpected fetch: {url}")

    result = collect_pretrip_p0_p1_sources(
        project_root,
        allow_network_fetch=False,
        source_records=[{"url": "https://example.test/p0/tianchi"}],
        generated_at="2026-06-15T00:00:00Z",
        fetcher=blocked_fetcher,
    )

    evidence = json.loads((project_root / DEFAULT_WEB_CASE_EVIDENCE_REF).read_text(encoding="utf-8"))
    assert result["network_calls_made"] is False
    assert result["evidence_item_count"] == 0
    assert result["boundary"]["network_calls_allowed"] is False
    assert evidence["status"] == "planned_no_network"
    assert evidence["evidence_items"] == []
    assert evidence["source_statuses"][0]["status"] == "planned_no_network"


def test_p0_p1_source_collection_imports_operator_image_list_without_network(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(FIXTURE_PROJECT, project_root)
    image_list = tmp_path / "operator_images.json"
    image_records = [
        {
            "image_url": f"https://example.test/media/{layer}.jpg",
            "page_url": f"https://example.test/context/{layer}",
            "label": label,
            "caption": label,
            "summary": f"{label}，作為行前簡報的 {layer} 視覺脈絡。",
            "context_layer": layer,
            "source_tier": "P1",
            "source_family": family,
        }
        for layer, label, family in [
            ("historical", "能高越嶺道舊道影像", "historical_expansion"),
            ("cultural", "地方地名與路徑脈絡照片", "cultural_expansion"),
            ("natural", "高山植被與林相變化", "natural_baseline"),
            ("terrain", "稜線與崩壁地形示意照片", "geology_expansion"),
            ("seasonal", "雲海與低溫季節觀察", "community_article_evidence"),
            ("observation_point", "三分鐘觀察點示意", "community_route_evidence"),
            ("route_overview", "路線總覽導覽照片", "map_expansion"),
        ]
    ]
    image_list.write_text(
        json.dumps({"image_records": image_records}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    def blocked_fetcher(url: str, timeout_seconds: float) -> dict[str, object]:
        raise AssertionError(f"unexpected fetch: {url}")

    result = collect_pretrip_p0_p1_sources(
        project_root,
        allow_network_fetch=False,
        image_list_json=image_list,
        route_keywords=["奇萊-南華"],
        generated_at="2026-06-15T00:00:00Z",
        fetcher=blocked_fetcher,
    )

    assert result["network_calls_made"] is False
    assert result["image_source_count"] == 7
    assert result["evidence_item_count"] == 7
    assert result["boundary"]["network_calls_allowed"] is False
    evidence = json.loads((project_root / DEFAULT_WEB_CASE_EVIDENCE_REF).read_text(encoding="utf-8"))
    query_plan = json.loads((project_root / DEFAULT_WEB_CASE_QUERY_PLAN_REF).read_text(encoding="utf-8"))
    assert query_plan["status"] == "ready_from_operator_image_list"
    assert query_plan["image_source_count"] == 7
    assert query_plan["source_policy"]["operator_image_import_allowed"] is True
    assert evidence["status"] == "ready_from_p0_p1_sources"
    assert evidence["counts"]["operator_image_source_count"] == 7
    assert evidence["counts"]["by_source_tier"] == {"P1": 7}
    assert evidence["points"][0]["source_kind"] == "p0_p1_operator_image_source"
    assert evidence["points"][0]["image_refs"][0]["raw_image_embedded"] is False
    assert evidence["points"][0]["candidate_only"] is True
    assert evidence["points"][0]["runtime_safety_truth"] is False

    collect_pretrip_route_context(
        project_root,
        dry_run=False,
        limit_route_notes=4,
        collected_at="2026-06-15T00:00:01Z",
    )

    media_manifest = json.loads(
        (project_root / ROUTE_CONTEXT_MEDIA_MANIFEST_REF).read_text(encoding="utf-8")
    )
    briefing = (project_root / ROUTE_CONTEXT_BRIEFING_REF).read_text(encoding="utf-8")
    assert media_manifest["media_count"] == 7
    assert len(media_manifest["gallery_images"]) == 7
    curation = media_manifest["image_curation"]
    assert curation["coverage_status"] == "usable"
    assert curation["selected_media_count"] == 7
    assert curation["target_min_gallery_images"] == 12
    assert curation["target_max_gallery_images"] == 18
    assert curation["covered_context_layers"] == [
        "route_overview",
        "historical",
        "cultural",
        "natural",
        "terrain",
        "seasonal",
        "observation_point",
    ]
    assert curation["missing_context_layers"] == []
    assert curation["visual_readiness"]["status"] == "usable"
    assert curation["visual_readiness"]["label"] == "主要路段已可對照"
    assert curation["visual_readiness"]["quality_gate"] == "warn_top_up_images"
    assert curation["visual_readiness"]["missing_image_count_to_target"] == 5
    assert media_manifest["visual_readiness"] == curation["visual_readiness"]
    assert curation["recommendation"]
    by_layer = {
        image["context_layer"]: image
        for image in media_manifest["gallery_images"]
        if image.get("context_layer")
    }
    assert set(by_layer) >= {
        "historical",
        "cultural",
        "natural",
        "terrain",
        "seasonal",
        "observation_point",
        "route_overview",
    }
    assert by_layer["cultural"]["presentation_anchor"]["context_kind"] == "cultural_context"
    assert by_layer["terrain"]["presentation_anchor"]["context_kind"] == "terrain_context"
    assert by_layer["seasonal"]["presentation_anchor"]["context_kind"] == "seasonal_context"
    assert by_layer["cultural"]["presentation_anchor"]["match_reason"] == "operator_supplied_context_layer"
    assert "https://example.test/media/historical.jpg" in briefing
    assert "https://example.test/media/route_overview.jpg" in briefing
    assert "能高越嶺道舊道影像" in briefing
    assert "文化脈絡" in briefing
    assert "地形脈絡" in briefing
    assert "山友文章" in briefing
    assert "地質參考" in briefing
    assert "可信參考" in briefing
    assert "photo-essay" in briefing
    assert "先用一組畫面講完這趟路" in briefing
    assert "出發前補查路段" in briefing
    assert "已對照" in briefing
    assert "7 / 12" in briefing
    assert "四段路線" in briefing
    assert "visual-story-arc" in briefing
    assert media_manifest["visual_kit"]["slot_count"] == 6
    assert media_manifest["visual_kit_ready_count"] >= 5
    assert media_manifest["visual_kit_missing_count"] <= 1
    assert "路線照片與地圖" in briefing
    assert "visual-kit-board" in briefing
    assert "照片與地圖對應的行程段落" in briefing
    assert "入山與稜線遠景" in briefing
    assert "領隊可依入山、路線走向、宿點、中高山地形、短停觀察與天候季節逐段檢查" in briefing
    assert "不是增加裝飾圖，而是讓每張圖負責一個行前說明任務" not in briefing
    assert "避免簡報只剩資料欄位" not in briefing


def test_p0_p1_source_collection_imports_operator_image_html_without_network(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(FIXTURE_PROJECT, project_root)
    image_html = tmp_path / "operator_images.html"
    image_html.write_text(
        """
        <main>
          <figure data-context-layer="route_overview" data-source-tier="P1" data-source-family="map_expansion">
            <a href="https://example.test/source/route">
              <img src="https://example.test/media/route-overview.jpg" alt="路線總覽">
            </a>
            <figcaption>奇萊南華路線總覽與行程節奏</figcaption>
          </figure>
          <figure data-context-layer="historical" data-source-tier="P1" data-source-family="historical_expansion">
            <img data-page-url="https://example.test/source/history" src="https://example.test/media/history.jpg" alt="舊道">
            <figcaption>能高越嶺道與保線路歷史脈絡</figcaption>
          </figure>
          <figure data-context-layer="cultural" data-source-tier="P1" data-source-family="cultural_expansion">
            <img data-source-url="https://example.test/source/culture" src="https://example.test/media/culture.jpg" alt="地名">
            <figcaption>地名與土地使用變遷</figcaption>
          </figure>
          <figure data-context-layer="natural" data-source-tier="P0" data-source-family="natural_baseline">
            <img data-page-url="https://example.test/source/nature" src="https://example.test/media/nature.jpg" alt="林相">
            <figcaption>高山植被與林相變化</figcaption>
          </figure>
          <figure data-context-layer="terrain" data-source-tier="P1" data-source-family="geology_expansion">
            <img data-page-url="https://example.test/source/terrain" src="https://example.test/media/terrain.jpg" alt="稜線">
            <figcaption>稜線、鞍部與崩壁地形</figcaption>
          </figure>
          <figure data-context-layer="seasonal" data-source-tier="P1" data-source-family="community_article_evidence">
            <img data-page-url="https://example.test/source/season" src="https://example.test/media/season.jpg" alt="雲海">
            <figcaption>雲海、低溫與季節觀察</figcaption>
          </figure>
          <figure data-context-layer="observation_point" data-source-tier="P1" data-source-family="community_route_evidence">
            <img data-page-url="https://example.test/source/stop" src="https://example.test/media/stop.jpg" alt="停留點">
            <figcaption>值得停三分鐘觀察的展望點</figcaption>
          </figure>
        </main>
        """,
        encoding="utf-8",
    )

    def blocked_fetcher(url: str, timeout_seconds: float) -> dict[str, object]:
        raise AssertionError(f"unexpected fetch: {url}")

    result = collect_pretrip_p0_p1_sources(
        project_root,
        allow_network_fetch=False,
        image_list_html=image_html,
        route_keywords=["奇萊-南華"],
        generated_at="2026-06-15T00:00:00Z",
        fetcher=blocked_fetcher,
    )

    assert result["network_calls_made"] is False
    assert result["image_source_count"] == 7
    assert result["evidence_item_count"] == 7
    query_plan = json.loads((project_root / DEFAULT_WEB_CASE_QUERY_PLAN_REF).read_text(encoding="utf-8"))
    evidence = json.loads((project_root / DEFAULT_WEB_CASE_EVIDENCE_REF).read_text(encoding="utf-8"))
    assert query_plan["status"] == "ready_from_operator_image_list"
    assert "image_list_html" in query_plan["source_policy"]["concrete_url_inputs"]
    assert evidence["counts"]["operator_image_source_count"] == 7
    assert evidence["counts"]["by_source_tier"] == {"P0": 1, "P1": 6}
    by_layer = {item["context_layer"]: item for item in evidence["points"]}
    assert by_layer["route_overview"]["url"] == "https://example.test/source/route"
    assert by_layer["historical"]["summary"] == "能高越嶺道與保線路歷史脈絡"
    assert by_layer["natural"]["source_tier"] == "P0"

    collect_pretrip_route_context(
        project_root,
        dry_run=False,
        limit_route_notes=4,
        collected_at="2026-06-15T00:00:01Z",
    )

    media_manifest = json.loads(
        (project_root / ROUTE_CONTEXT_MEDIA_MANIFEST_REF).read_text(encoding="utf-8")
    )
    briefing = (project_root / ROUTE_CONTEXT_BRIEFING_REF).read_text(encoding="utf-8")
    curation = media_manifest["image_curation"]
    assert curation["coverage_status"] == "usable"
    assert curation["missing_context_layers"] == []
    assert curation["visual_readiness"]["status"] == "usable"
    assert curation["visual_readiness"]["missing_image_count_to_target"] == 5
    assert media_manifest["visual_readiness"] == curation["visual_readiness"]
    assert media_manifest["available_media_count"] == 7
    assert media_manifest["deduped_media_count"] == 7
    assert "出發前補查路段" in briefing
    assert "7 / 12" in briefing
    assert "奇萊南華路線總覽與行程節奏" in briefing
    assert "高山植被與林相變化" in briefing


def test_p0_p1_source_collection_can_read_allowlisted_links_from_briefing_html(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(FIXTURE_PROJECT, project_root)
    briefing = tmp_path / "briefing.html"
    briefing.write_text(
        """
        <a href="https://tconline.forest.gov.tw/news/index.php?id=521&mode=data">天池公告</a>
        <a href="https://hiking.biji.co/index.php?act=detail&id=430&q=trail">健行筆記</a>
        <a href="https://trail.tacp.gov.tw/zh-hant">尋路循路</a>
        <a href="https://www.ntfd.gov.tw/index.php?act=article&code=list&ids=70">南投消防局山域事故</a>
        <a href="https://data.gov.tw/datasets/search?qs=山域意外事故救援案件清冊">政府開放資料山域事故</a>
        <a href="https://www.ptt.cc/bbs/Hiking/M.1669177132.A.15F.html">PTT Hiking</a>
        <a href="https://www.mtrescue.org.tw/">山難救助協會</a>
        <a href="https://www.youtube.com/watch?v=1fjVWFle0A8">路線影片</a>
        """,
        encoding="utf-8",
    )

    result = collect_pretrip_p0_p1_sources(
        project_root,
        dry_run=True,
        source_records=[],
        source_list_html=briefing,
        generated_at="2026-06-15T00:00:00Z",
    )

    query_plan = result["planned_artifacts"]["query_plan"]
    assert result["writes_performed"] is False
    assert result["source_count"] == 8
    assert query_plan["sources"][0]["source_tier"] == "P0"
    assert query_plan["sources"][0]["source_family"] == "official_baseline"
    assert query_plan["sources"][1]["source_tier"] == "P1"
    assert query_plan["sources"][1]["source_family"] == "community_article_evidence"
    assert query_plan["sources"][2]["source_tier"] == "P0"
    assert query_plan["sources"][2]["source_family"] == "cultural_trail_baseline"
    assert query_plan["sources"][3]["source_tier"] == "P0"
    assert query_plan["sources"][3]["source_family"] == "incident_local_baseline"
    assert query_plan["sources"][4]["source_tier"] == "P0"
    assert query_plan["sources"][4]["source_family"] == "incident_open_data_baseline"
    assert query_plan["sources"][5]["source_tier"] == "P1"
    assert query_plan["sources"][5]["source_family"] == "community_article_evidence"
    assert query_plan["sources"][6]["source_tier"] == "P1"
    assert query_plan["sources"][6]["source_family"] == "rescue_training_reference"
    assert query_plan["sources"][7]["source_tier"] == "P1"
    assert query_plan["sources"][7]["source_family"] == "community_media_evidence"
