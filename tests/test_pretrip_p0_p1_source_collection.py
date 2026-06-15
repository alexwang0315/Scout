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
    assert query_plan["source_catalog_count"] == len(DEFAULT_P0_P1_SOURCE_CATALOG) == 20
    assert {source["source_tier"] for source in catalog} == {"P0", "P1"}
    assert {source["source_family"] for source in catalog} >= {
        "official_baseline",
        "official_status",
        "terrain_baseline",
        "weather_baseline",
        "hazard_baseline",
        "incident_baseline",
        "natural_baseline",
        "historical_map_baseline",
        "cultural_expansion",
        "historical_expansion",
        "cultural_spatial_expansion",
        "geology_expansion",
        "map_expansion",
        "community_route_seed",
        "community_article_evidence",
        "community_route_evidence",
    }
    assert all("url" not in source for source in catalog)


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
        <html><head><title>能高越嶺西段與天池山莊開放</title></head>
        <body><h1>天池山莊公告</h1>
        <p>奇萊-南華路線需要注意入園申請、住宿規定與夜間通行風險。</p>
        <p>能高越嶺路段仍有落石風險，僅作出發前候選 evidence。</p></body></html>
        """,
        "https://example.test/p1/chilai-nanhua": """
        <html><head><title>奇萊南華路線介紹</title></head>
        <body><h1>奇萊南華</h1>
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
    assert result["source_count"] == 2
    assert query_plan["sources"][0]["source_tier"] == "P0"
    assert query_plan["sources"][0]["source_family"] == "official_baseline"
    assert query_plan["sources"][1]["source_tier"] == "P1"
    assert query_plan["sources"][1]["source_family"] == "community_article_evidence"
