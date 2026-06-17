from __future__ import annotations

import argparse
import hashlib
import json
import re
import ssl
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


ARTIFACT_KIND = "pretrip_p0_p1_source_collection"
SCHEMA_VERSION = "pretrip_p0_p1_source_collection.v1"
MAP_PREPARATION_SCHEMA_VERSION = "route_corridor_map_preparation.v1"
DEFAULT_WEB_CASE_QUERY_PLAN_REF = "outputs/layers/plans/web_case_query_plan.json"
DEFAULT_WEB_CASE_EVIDENCE_REF = "outputs/layers/normalized/web_case_evidence.json"
DEFAULT_ROUTE_SCOPE_REF = "normalized/routes/route_evidence_bundle.json"


DEFAULT_P0_P1_SOURCE_CATALOG: tuple[dict[str, str], ...] = (
    {
        "catalog_id": "forest_nature_trail_data",
        "source_tier": "P0",
        "source_family": "official_baseline",
        "label": "林業及自然保育署自然步道資料",
        "coverage_scope": "national",
        "seed_role": "official trail baseline discovery",
    },
    {
        "catalog_id": "forest_recreation_open_data",
        "source_tier": "P0",
        "source_family": "official_baseline",
        "label": "台灣山林悠遊網開放資料",
        "coverage_scope": "national",
        "seed_role": "official recreation open-data baseline discovery",
    },
    {
        "catalog_id": "hike_taiwan_permit_portal",
        "source_tier": "P0",
        "source_family": "official_baseline",
        "label": "臺灣登山申請一站式服務網",
        "coverage_scope": "national",
        "seed_role": "permit, bed quota and controlled-area baseline discovery",
    },
    {
        "catalog_id": "national_park_route_status",
        "source_tier": "P0",
        "source_family": "official_status",
        "label": "國家公園路線開放狀態",
        "coverage_scope": "national_or_park_region",
        "seed_role": "park trail access and route status discovery",
    },
    {
        "catalog_id": "nlsc_dem_dtm_topographic_maps",
        "source_tier": "P0",
        "source_family": "terrain_baseline",
        "label": "內政部國土測繪中心 DEM / DTM / 地形圖",
        "coverage_scope": "national",
        "seed_role": "terrain, DEM, DTM and topographic-map baseline discovery",
    },
    {
        "catalog_id": "cwa_weather_open_data",
        "source_tier": "P0",
        "source_family": "weather_baseline",
        "label": "中央氣象署 CODiS / 開放資料",
        "coverage_scope": "national",
        "seed_role": "weather station, rainfall, temperature and warning evidence discovery",
    },
    {
        "catalog_id": "ncdr_disaster_potential",
        "source_tier": "P0",
        "source_family": "hazard_baseline",
        "label": "NCDR 災害潛勢資料",
        "coverage_scope": "national",
        "seed_role": "hazard and disaster-potential evidence discovery",
    },
    {
        "catalog_id": "nfa_mountain_rescue_cases",
        "source_tier": "P0",
        "source_family": "incident_baseline",
        "label": "消防署山域事故救援案件",
        "coverage_scope": "national",
        "seed_role": "incident and rescue case evidence discovery",
    },
    {
        "catalog_id": "regional_fire_department_incident_feeds",
        "source_tier": "P0",
        "source_family": "incident_local_baseline",
        "label": "地方消防局山域事故與即時災情",
        "coverage_scope": "regional",
        "seed_role": "regional official incident and rescue-dispatch evidence discovery",
    },
    {
        "catalog_id": "government_open_data_mountain_incidents",
        "source_tier": "P0",
        "source_family": "incident_open_data_baseline",
        "label": "政府資料開放平臺山域事故清冊 / 消防救援統計",
        "coverage_scope": "national",
        "seed_role": "structured mountain incident and rescue statistics discovery",
    },
    {
        "catalog_id": "tbn_biodiversity_network",
        "source_tier": "P0",
        "source_family": "natural_baseline",
        "label": "TBN 台灣生物多樣性網絡",
        "coverage_scope": "national",
        "seed_role": "natural and ecological context baseline discovery",
    },
    {
        "catalog_id": "as_taiwan_century_historical_maps",
        "source_tier": "P0",
        "source_family": "historical_map_baseline",
        "label": "中研院臺灣百年歷史地圖",
        "coverage_scope": "national",
        "seed_role": "historical map and old-place context baseline discovery",
    },
    {
        "catalog_id": "tacp_indigenous_historic_trails",
        "source_tier": "P0",
        "source_family": "cultural_trail_baseline",
        "label": "尋路・循路－臺灣原住民族古道空間資訊網",
        "coverage_scope": "national_or_regional",
        "seed_role": "official indigenous historic-trail baseline discovery",
    },
    {
        "catalog_id": "national_culture_memory",
        "source_tier": "P1",
        "source_family": "cultural_expansion",
        "label": "國家文化記憶庫",
        "coverage_scope": "national_or_regional",
        "seed_role": "cultural route-context expansion",
    },
    {
        "catalog_id": "taiwan_memory",
        "source_tier": "P1",
        "source_family": "historical_expansion",
        "label": "臺灣記憶",
        "coverage_scope": "national_or_regional",
        "seed_role": "historical route-context expansion",
    },
    {
        "catalog_id": "indigenous_historic_trail_spatial_info",
        "source_tier": "P1",
        "source_family": "cultural_spatial_expansion",
        "label": "原住民族古道空間資訊網",
        "coverage_scope": "national_or_regional",
        "seed_role": "cultural spatial route-context expansion",
    },
    {
        "catalog_id": "geology_cloud",
        "source_tier": "P1",
        "source_family": "geology_expansion",
        "label": "地質雲",
        "coverage_scope": "national",
        "seed_role": "geology evidence expansion",
    },
    {
        "catalog_id": "osm_overpass",
        "source_tier": "P1",
        "source_family": "map_expansion",
        "label": "OpenStreetMap / Overpass / OSM full-history",
        "coverage_scope": "global",
        "seed_role": "named places, trail topology and human-made feature discovery",
    },
    {
        "catalog_id": "rudymap",
        "source_tier": "P1",
        "source_family": "map_expansion",
        "label": "魯地圖",
        "coverage_scope": "taiwan_community",
        "seed_role": "community map and named-place expansion",
    },
    {
        "catalog_id": "map_generator_and_hiker_gpx",
        "source_tier": "P1",
        "source_family": "community_route_seed",
        "label": "地圖產生器 / 山友 GPX",
        "coverage_scope": "taiwan_community",
        "seed_role": "community GPX and route-seed discovery",
    },
    {
        "catalog_id": "hiking_biji",
        "source_tier": "P1",
        "source_family": "community_article_evidence",
        "label": "健行筆記",
        "coverage_scope": "taiwan_community",
        "seed_role": "community article and named-point evidence discovery",
    },
    {
        "catalog_id": "hikingbook",
        "source_tier": "P1",
        "source_family": "community_route_evidence",
        "label": "Hikingbook",
        "coverage_scope": "taiwan_community",
        "seed_role": "community route evidence discovery",
    },
    {
        "catalog_id": "ptt_hiking",
        "source_tier": "P1",
        "source_family": "community_article_evidence",
        "label": "PTT Hiking",
        "coverage_scope": "taiwan_community",
        "seed_role": "community trip report, pace log and pressure language discovery",
    },
    {
        "catalog_id": "mountain_notes",
        "source_tier": "P1",
        "source_family": "community_article_evidence",
        "label": "登山補給站",
        "coverage_scope": "taiwan_community",
        "seed_role": "community article, trip report and caution-note evidence discovery",
    },
    {
        "catalog_id": "mountain_rescue_association_knowledge",
        "source_tier": "P1",
        "source_family": "rescue_training_reference",
        "label": "中華民國山難救助協會 / 山域搜救訓練資料",
        "coverage_scope": "taiwan_rescue_community",
        "seed_role": "field rescue training and terrain-reading reference discovery",
    },
    {
        "catalog_id": "expert_field_rescue_media",
        "source_tier": "P1",
        "source_family": "field_rescue_expert_observation",
        "label": "跑山獸 / 山小白 / 公開搜救與登山專家影音",
        "coverage_scope": "taiwan_public_media",
        "seed_role": "reviewed public expert field observation and rescue-context discovery",
    },
    {
        "catalog_id": "public_community_media_posts",
        "source_tier": "P1",
        "source_family": "community_media_evidence",
        "label": "公開社群影音與路線貼文",
        "coverage_scope": "public_social_media",
        "seed_role": "public route media and visual pressure evidence discovery after review",
    },
)

DEFAULT_CONCRETE_SOURCE_RECORDS: tuple[dict[str, str], ...] = ()


FetchResult = dict[str, Any]
Fetcher = Callable[[str, float], FetchResult]


def collect_pretrip_p0_p1_sources(
    project_root: Path | str,
    *,
    allow_network_fetch: bool = False,
    dry_run: bool = False,
    source_records: list[dict[str, Any]] | None = None,
    source_list_html: Path | str | None = None,
    image_records: list[dict[str, Any]] | None = None,
    image_list_json: Path | str | None = None,
    image_list_html: Path | str | None = None,
    route_keywords: list[str] | None = None,
    generated_at: str | None = None,
    timeout_seconds: float = 15.0,
    fetcher: Fetcher | None = None,
) -> dict[str, Any]:
    """Collect allowlisted P0/P1 route-context web evidence into the workspace.

    This is an operator-triggered pretrip evidence tool. It fetches only explicit
    source records, stores bounded snippets and hashes, and never creates runtime
    safety truth.
    """

    root = Path(project_root)
    project_path = root / "project.json"
    project = _load_json(project_path)
    project_id = str(project.get("project_id") or project.get("id") or root.name)
    generated_at = generated_at or _utc_now()
    query_plan_ref = str(project.get("web_case_query_plan_ref") or DEFAULT_WEB_CASE_QUERY_PLAN_REF)
    evidence_ref = str(project.get("web_case_evidence_ref") or DEFAULT_WEB_CASE_EVIDENCE_REF)
    route_scope_ref = _route_scope_ref(project)
    keywords = route_keywords or _route_keywords_from_workspace(root, project, project_id)
    base_sources = (
        [dict(source) for source in DEFAULT_CONCRETE_SOURCE_RECORDS]
        if source_records is None
        else source_records
    )
    sources = _merge_source_records(
        base_sources,
        _source_records_from_html(source_list_html) if source_list_html else [],
    )
    images = _merge_image_records(
        [] if image_records is None else image_records,
        [
            *(_image_records_from_json(image_list_json) if image_list_json else []),
            *(_image_records_from_html(image_list_html) if image_list_html else []),
        ],
    )

    network_calls_made = False
    source_statuses: list[dict[str, Any]] = []
    evidence_items: list[dict[str, Any]] = []
    for image_record in images:
        item = _image_evidence_item(
            project_id=project_id,
            image_record=image_record,
            keywords=keywords,
            generated_at=generated_at,
        )
        evidence_items.append(item)
        source_statuses.append(
            {
                "source_id": item["source_id"],
                "source_tier": item["source_tier"],
                "source_family": item["source_family"],
                "label": item["label"],
                "url": item["url"],
                "status": "operator_image_imported",
                "image_count": len(item["image_refs"]),
                "raw_image_embedded": False,
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )
    fetch = fetcher or _fetch_url
    for source in sources:
        record = _normalize_source_record(source)
        if not allow_network_fetch:
            source_statuses.append({**record, "status": "planned_no_network"})
            continue
        network_calls_made = True
        try:
            fetched = fetch(record["url"], timeout_seconds)
        except Exception as exc:  # pragma: no cover - defensive external path
            fetched = {
                "ok": False,
                "status_code": None,
                "content_type": None,
                "body": "",
                "error": str(exc),
            }
        if not fetched.get("ok"):
            source_statuses.append(
                {
                    **record,
                    "status": "fetch_failed",
                    "http_status": fetched.get("status_code"),
                    "error": fetched.get("error"),
                }
            )
            continue
        body = str(fetched.get("body") or "")
        extracted = _extract_html_summary(body, keywords, base_url=record.get("url"))
        content_sha256 = hashlib.sha256(body.encode("utf-8")).hexdigest()
        item = _evidence_item(
            project_id=project_id,
            source=record,
            extracted=extracted,
            keywords=keywords,
            generated_at=generated_at,
            http_status=fetched.get("status_code"),
            content_type=fetched.get("content_type"),
            content_sha256=content_sha256,
        )
        evidence_items.append(item)
        source_statuses.append(
            {
                **record,
                "status": "fetched",
                "http_status": fetched.get("status_code"),
                "content_type": fetched.get("content_type"),
                "content_sha256": content_sha256,
                "raw_html_embedded": False,
            }
        )

    boundary = _boundary(
        allow_network_fetch=allow_network_fetch,
        network_calls_made=network_calls_made,
    )
    query_plan = {
        "artifact_kind": "pretrip_web_case_query_plan",
        "schema_version": MAP_PREPARATION_SCHEMA_VERSION,
        "collector_schema_version": SCHEMA_VERSION,
        "project_id": project_id,
        "source_id": f"{project_id}.p0_p1_source_query_plan",
        "source_path": query_plan_ref,
        "status": _query_plan_status(allow_network_fetch, len(sources), len(images)),
        "route_scope_ref": route_scope_ref,
        "route_keywords": keywords,
        "source_catalog": [dict(source) for source in DEFAULT_P0_P1_SOURCE_CATALOG],
        "source_catalog_count": len(DEFAULT_P0_P1_SOURCE_CATALOG),
        "source_count": len(sources),
        "sources": sources,
        "image_source_count": len(images),
        "image_sources": images,
        "source_policy": {
            "default_route_specific_sources": False,
            "concrete_url_required_for_fetch": True,
            "concrete_url_inputs": [
                "source_list_html",
                "source_url",
                "image_list_json",
                "image_list_html",
                "operator_image_records",
                "future_search_adapter_output",
            ],
            "operator_image_import_allowed": True,
            "catalog_role": "search_scope_only",
        },
        "network_policy": {
            "allow_network_fetch": allow_network_fetch,
            "explicit_fetch_required": True,
            "network_calls_made": network_calls_made,
        },
        "output_ref": evidence_ref,
        "boundary": boundary,
    }
    evidence = {
        "artifact_kind": "pretrip_web_case_evidence",
        "schema_version": MAP_PREPARATION_SCHEMA_VERSION,
        "collector_schema_version": SCHEMA_VERSION,
        "project_id": project_id,
        "source_id": f"{project_id}.p0_p1_web_case_evidence",
        "source_path": evidence_ref,
        "status": _evidence_status(allow_network_fetch, evidence_items, source_statuses),
        "generated_at": generated_at,
        "route_scope_ref": route_scope_ref,
        "source_plan_ref": query_plan_ref,
        "route_keywords": keywords,
        "source_statuses": source_statuses,
        "evidence_items": evidence_items,
        "points": evidence_items,
        "counts": _counts(evidence_items, source_statuses),
        "boundary": boundary,
    }
    result = {
        "artifact_kind": ARTIFACT_KIND,
        "schema_version": SCHEMA_VERSION,
        "status": "completed",
        "dry_run": dry_run,
        "project_id": project_id,
        "source_count": len(sources),
        "image_source_count": len(images),
        "evidence_item_count": len(evidence_items),
        "network_calls_made": network_calls_made,
        "outputs": {
            "web_case_query_plan_ref": query_plan_ref,
            "web_case_evidence_ref": evidence_ref,
        },
        "boundary": boundary,
    }
    if not dry_run:
        _write_json(root / query_plan_ref, query_plan)
        _write_json(root / evidence_ref, evidence)
        _update_project(
            project_path,
            project,
            {
                "web_case_query_plan_ref": query_plan_ref,
                "web_case_evidence_ref": evidence_ref,
                "web_case_evidence_count": len(evidence_items),
                "web_case_source_count": len(sources),
                "web_case_image_source_count": len(images),
                "web_case_collection_updated_at": generated_at,
                "web_case_collection_schema_version": SCHEMA_VERSION,
            },
        )
        result["writes_performed"] = True
    else:
        result["writes_performed"] = False
        result["planned_artifacts"] = {
            "query_plan": query_plan,
            "evidence": evidence,
        }
    return result


def _normalize_source_record(source: dict[str, Any]) -> dict[str, Any]:
    url = str(source.get("url") or "").strip()
    if not url:
        raise ValueError("source record requires url")
    guessed = _classify_url(url)
    return {
        "source_id": str(source.get("source_id") or guessed["source_id"]),
        "source_tier": str(source.get("source_tier") or guessed["source_tier"]),
        "source_family": str(source.get("source_family") or guessed["source_family"]),
        "label": str(source.get("label") or guessed["label"]),
        "url": url,
    }


def _merge_source_records(
    primary: list[dict[str, Any]],
    extra: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in [*primary, *extra]:
        try:
            record = _normalize_source_record(source)
        except ValueError:
            continue
        if record["url"] in seen:
            continue
        seen.add(record["url"])
        merged.append(record)
    return merged


def _source_records_from_html(path: Path | str | None) -> list[dict[str, Any]]:
    if not path:
        return []
    html_path = Path(path)
    if not html_path.exists():
        return []
    parser = _AnchorExtractor()
    parser.feed(html_path.read_text(encoding="utf-8"))
    return [_classify_url(url, label=label) | {"url": url} for url, label in parser.links]


def _image_records_from_json(path: Path | str | None) -> list[dict[str, Any]]:
    if not path:
        return []
    json_path = Path(path)
    if not json_path.exists():
        return []
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict):
        records = (
            payload.get("image_records")
            or payload.get("images")
            or payload.get("results")
            or []
        )
    else:
        records = []
    return [record for record in records if isinstance(record, dict)]


def _image_records_from_html(path: Path | str | None) -> list[dict[str, Any]]:
    if not path:
        return []
    html_path = Path(path)
    if not html_path.exists():
        return []
    parser = _OperatorImageHTMLExtractor()
    try:
        parser.feed(html_path.read_text(encoding="utf-8"))
    except OSError:
        return []
    return parser.records


def _merge_image_records(
    primary: list[dict[str, Any]],
    extra: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for image in [*primary, *extra]:
        try:
            record = _normalize_image_record(image)
        except ValueError:
            continue
        if record["image_url"] in seen:
            continue
        seen.add(record["image_url"])
        merged.append(record)
    return merged


def _normalize_image_record(image: dict[str, Any]) -> dict[str, Any]:
    raw_image_url = str(
        image.get("image_url")
        or image.get("url")
        or image.get("src")
        or image.get("href")
        or ""
    ).strip()
    page_url = str(
        image.get("page_url")
        or image.get("source_url")
        or image.get("source_page_url")
        or ""
    ).strip()
    if not raw_image_url:
        raise ValueError("image record requires image_url")
    image_url = urljoin(page_url or "", raw_image_url)
    if not image_url.startswith(("http://", "https://")):
        raise ValueError("image record requires http(s) image_url")
    if image_url.startswith(("data:", "blob:", "javascript:")):
        raise ValueError("image record uses unsupported image_url scheme")
    classified = _classify_url(page_url or image_url)
    label = _collapse_ws(
        str(
            image.get("label")
            or image.get("caption")
            or image.get("alt")
            or image.get("title")
            or classified["label"]
        )
    )
    source_id = str(
        image.get("source_id")
        or f"operator_image.{hashlib.sha1(image_url.encode('utf-8')).hexdigest()[:12]}"
    )
    return {
        "source_id": source_id,
        "source_tier": str(image.get("source_tier") or classified["source_tier"]),
        "source_family": str(
            image.get("source_family")
            or image.get("source_kind")
            or classified["source_family"]
        ),
        "label": label[:160],
        "summary": _collapse_ws(str(image.get("summary") or ""))[:420],
        "image_url": image_url,
        "url": page_url or image_url,
        "page_url": page_url or image_url,
        "alt": _collapse_ws(str(image.get("alt") or label))[:120],
        "caption": _collapse_ws(str(image.get("caption") or label))[:160],
        "title": _collapse_ws(str(image.get("title") or ""))[:120],
        "context_layer": _collapse_ws(
            str(image.get("context_layer") or image.get("sec6_layer") or "")
        )[:80],
        "candidate_only": True,
        "requires_human_review": True,
        "runtime_safety_truth": False,
        "raw_image_embedded": False,
    }


def _classify_url(url: str, *, label: str | None = None) -> dict[str, str]:
    host = urlparse(url).netloc.lower()
    slug = re.sub(r"[^a-z0-9]+", "_", host).strip("_") or "source"
    tier = "P1"
    family = "community_or_reference_source"
    if host.endswith("forest.gov.tw") or host.endswith("hike.taiwan.gov.tw"):
        tier = "P0"
        family = "official_baseline"
    elif "nps.gov.tw" in host:
        tier = "P0"
        family = "official_status"
    elif "nlsc.gov.tw" in host:
        tier = "P0"
        family = "terrain_baseline"
    elif "cwa.gov.tw" in host or "codis" in host:
        tier = "P0"
        family = "weather_baseline"
    elif "ncdr" in host:
        tier = "P0"
        family = "hazard_baseline"
    elif "nfa.gov.tw" in host:
        tier = "P0"
        family = "incident_baseline"
    elif "data.gov.tw" in host:
        tier = "P0"
        family = "incident_open_data_baseline"
    elif _is_regional_fire_host(host):
        tier = "P0"
        family = "incident_local_baseline"
    elif "tbn.org.tw" in host:
        tier = "P0"
        family = "natural_baseline"
    elif "gis.rchss.sinica.edu.tw" in host:
        tier = "P0"
        family = "historical_map_baseline"
    elif host.endswith("trail.tacp.gov.tw"):
        tier = "P0"
        family = "cultural_trail_baseline"
    elif host.endswith("culture.tw"):
        tier = "P1"
        family = "cultural_expansion"
    elif host.endswith("hiking.biji.co"):
        tier = "P1"
        family = "community_article_evidence"
    elif "hikingbook" in host:
        tier = "P1"
        family = "community_route_evidence"
    elif "keepon" in host:
        tier = "P1"
        family = "community_article_evidence"
    elif "ptt.cc" in host:
        tier = "P1"
        family = "community_article_evidence"
    elif "mtrescue.org.tw" in host:
        tier = "P1"
        family = "rescue_training_reference"
    elif host.endswith(("youtube.com", "youtu.be")):
        tier = "P1"
        family = "community_media_evidence"
    elif host.endswith(("facebook.com", "instagram.com", "threads.com")):
        tier = "P1"
        family = "community_media_evidence"
    elif host.endswith(
        (
            "hikerzoe.com",
            "dokimitw.com",
            "lightliterlife.tw",
            "colorfulbutterfly.net",
            "pixnet.net",
        )
    ):
        tier = "P1"
        family = "community_article_evidence"
    elif "openstreetmap" in host or "overpass" in host:
        tier = "P1"
        family = "map_expansion"
    return {
        "source_id": f"source.{slug}.{hashlib.sha1(url.encode('utf-8')).hexdigest()[:10]}",
        "source_tier": tier,
        "source_family": family,
        "label": label or host or url,
    }


def _is_regional_fire_host(host: str) -> bool:
    if host != "119.gov.taipei" and not host.endswith(".gov.tw"):
        return False
    if host == "119.gov.taipei":
        return True
    fire_host_markers = (
        "fire",
        "fd",
        "119",
        "ntfd",
        "tyfd",
        "ptfd",
        "ttfd",
        "tnfd",
        "kmfd",
        "hlfd",
        "ilcfd",
        "hccfd",
        "cyfd",
    )
    return any(marker in host for marker in fire_host_markers)


def _image_evidence_item(
    *,
    project_id: str,
    image_record: dict[str, Any],
    keywords: list[str],
    generated_at: str,
) -> dict[str, Any]:
    source_id = str(image_record["source_id"])
    candidate_id = _candidate_id(project_id, source_id)
    content_sha256 = hashlib.sha256(
        f"{image_record['image_url']}|{image_record['page_url']}".encode("utf-8")
    ).hexdigest()
    image_ref = {
        "url": image_record["image_url"],
        "alt": image_record["alt"],
        "caption": image_record["caption"],
        "title": image_record["title"],
        "context_layer": image_record["context_layer"],
        "sec6_layer": image_record["context_layer"],
        "source_kind": "operator_approved_p0_p1_image",
        "source_id": source_id,
        "source_tier": image_record["source_tier"],
        "source_family": image_record["source_family"],
        "page_url": image_record["page_url"],
        "page_content_sha256": content_sha256,
        "candidate_only": True,
        "requires_human_review": True,
        "runtime_safety_truth": False,
        "raw_image_embedded": False,
    }
    return {
        "id": candidate_id,
        "candidate_id": candidate_id,
        "label": image_record["label"],
        "title": image_record["label"],
        "summary": image_record["summary"] or image_record["caption"],
        "snippets": [image_record["summary"]] if image_record["summary"] else [],
        "url": image_record["page_url"],
        "source_id": source_id,
        "source_kind": "p0_p1_operator_image_source",
        "source_tier": image_record["source_tier"],
        "source_family": image_record["source_family"],
        "source_families": [image_record["source_family"]],
        "context_layer": image_record["context_layer"],
        "http_status": None,
        "content_type": "operator/image-metadata",
        "content_sha256": content_sha256,
        "route_keywords": keywords,
        "retrieved_at": generated_at,
        "raw_html_embedded": False,
        "large_scraped_text_embedded": False,
        "candidate_only": True,
        "requires_human_review": True,
        "runtime_safety_truth": False,
        "source_refs": [
            {
                "source_kind": "operator_approved_p0_p1_image",
                "source_id": source_id,
                "source_tier": image_record["source_tier"],
                "source_family": image_record["source_family"],
                "url": image_record["page_url"],
                "content_sha256": content_sha256,
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        ],
        "image_refs": [image_ref],
    }


def _evidence_item(
    *,
    project_id: str,
    source: dict[str, Any],
    extracted: dict[str, Any],
    keywords: list[str],
    generated_at: str,
    http_status: Any,
    content_type: Any,
    content_sha256: str,
) -> dict[str, Any]:
    title = extracted.get("title") or source["label"]
    candidate_id = _candidate_id(project_id, source["source_id"])
    return {
        "id": candidate_id,
        "candidate_id": candidate_id,
        "label": title,
        "title": title,
        "summary": extracted.get("summary"),
        "snippets": extracted.get("snippets", []),
        "url": source["url"],
        "source_id": source["source_id"],
        "source_kind": "p0_p1_web_source",
        "source_tier": source["source_tier"],
        "source_family": source["source_family"],
        "source_families": [source["source_family"]],
        "http_status": http_status,
        "content_type": content_type,
        "content_sha256": content_sha256,
        "route_keywords": keywords,
        "retrieved_at": generated_at,
        "raw_html_embedded": False,
        "large_scraped_text_embedded": False,
        "candidate_only": True,
        "requires_human_review": True,
        "runtime_safety_truth": False,
        "source_refs": [
            {
                "source_kind": "p0_p1_web_source",
                "source_id": source["source_id"],
                "source_tier": source["source_tier"],
                "source_family": source["source_family"],
                "url": source["url"],
                "content_sha256": content_sha256,
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        ],
        "image_refs": _image_refs_for_source(
            extracted.get("image_refs"),
            source=source,
            content_sha256=content_sha256,
        ),
    }


def _extract_html_summary(
    body: str,
    keywords: list[str],
    *,
    base_url: str | None = None,
) -> dict[str, Any]:
    parser = _TextExtractor()
    parser.feed(body)
    title = parser.title or (parser.headings[0] if parser.headings else "")
    text = _collapse_ws(" ".join(parser.text_chunks))
    snippets = _snippets(text, keywords)
    summary = " / ".join(snippets)[:640] if snippets else text[:360]
    return {
        "title": _collapse_ws(title or "")[:120],
        "summary": summary,
        "snippets": snippets,
        "image_refs": _normalized_image_refs(parser.image_refs, base_url=base_url),
    }


def _normalized_image_refs(
    image_refs: list[dict[str, Any]],
    *,
    base_url: str | None,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for image in image_refs:
        src = str(image.get("src") or image.get("href") or image.get("content") or "").strip()
        if not src or src.startswith(("data:", "blob:", "javascript:")):
            continue
        url = urljoin(base_url or "", src)
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        normalized.append(
            {
                "url": url,
                "alt": _collapse_ws(str(image.get("alt") or ""))[:120],
                "title": _collapse_ws(str(image.get("title") or ""))[:120],
                "candidate_only": True,
                "runtime_safety_truth": False,
                "raw_image_embedded": False,
            }
        )
        if len(normalized) >= 18:
            break
    return normalized


def _image_refs_for_source(
    image_refs: Any,
    *,
    source: dict[str, Any],
    content_sha256: str,
) -> list[dict[str, Any]]:
    if not isinstance(image_refs, list):
        return []
    result = []
    for image in image_refs:
        if not isinstance(image, dict):
            continue
        result.append(
            {
                **image,
                "source_kind": "p0_p1_web_image",
                "source_id": source["source_id"],
                "source_tier": source["source_tier"],
                "source_family": source["source_family"],
                "page_url": source["url"],
                "page_content_sha256": content_sha256,
                "candidate_only": True,
                "requires_human_review": True,
                "runtime_safety_truth": False,
                "raw_image_embedded": False,
            }
        )
    return result[:18]


def _snippets(text: str, keywords: list[str]) -> list[str]:
    terms = [
        *keywords,
        "奇萊",
        "南華",
        "能高",
        "天池山莊",
        "雲天宮",
        "光被八表",
        "入園",
        "落石",
        "風險",
        "住宿",
    ]
    sentences = re.split(r"(?<=[。！？!?])\s+|\n+", text)
    matches: list[str] = []
    for sentence in sentences:
        value = _collapse_ws(sentence)
        if len(value) < 8:
            continue
        if any(term and term in value for term in terms):
            matches.append(value[:180])
        if len(matches) >= 4:
            break
    return matches


def _route_keywords_from_workspace(
    root: Path,
    project: dict[str, Any],
    project_id: str,
) -> list[str]:
    crawl_ref = project.get("route_context_crawl_seed_plan_ref")
    if isinstance(crawl_ref, str) and crawl_ref:
        payload = _load_json(root / crawl_ref)
        keywords = payload.get("route_keywords")
        if isinstance(keywords, list) and keywords:
            return [str(item) for item in keywords if str(item).strip()]
    if project_id == "chilai_nanhua_day1":
        return ["奇萊-南華", "chilai_nanhua_day1", "奇萊南華", "奇萊南峰 南華山"]
    return [project_id]


def _route_scope_ref(project: dict[str, Any]) -> str:
    value = project.get("route_evidence_bundle_ref")
    return str(value) if isinstance(value, str) and value else DEFAULT_ROUTE_SCOPE_REF


def _fetch_url(url: str, timeout_seconds: float) -> FetchResult:
    request = Request(
        url,
        headers={
            "User-Agent": "ScoutAlphaPretrip/0.1 (+https://local.scout.invalid)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds, context=_https_context()) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            raw = response.read(1_500_000)
            return {
                "ok": True,
                "status_code": getattr(response, "status", 200),
                "content_type": response.headers.get("content-type"),
                "body": raw.decode(charset, errors="replace"),
            }
    except HTTPError as exc:
        return {
            "ok": False,
            "status_code": exc.code,
            "content_type": exc.headers.get("content-type") if exc.headers else None,
            "body": "",
            "error": str(exc),
        }
    except URLError as exc:
        return {
            "ok": False,
            "status_code": None,
            "content_type": None,
            "body": "",
            "error": str(exc),
        }


def _https_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    strict_flag = getattr(ssl, "VERIFY_X509_STRICT", 0)
    if strict_flag and hasattr(context, "verify_flags"):
        context.verify_flags &= ~strict_flag
    return context


def _counts(
    evidence_items: list[dict[str, Any]],
    source_statuses: list[dict[str, Any]],
) -> dict[str, Any]:
    by_tier: dict[str, int] = {}
    by_family: dict[str, int] = {}
    for item in evidence_items:
        by_tier[item["source_tier"]] = by_tier.get(item["source_tier"], 0) + 1
        by_family[item["source_family"]] = by_family.get(item["source_family"], 0) + 1
    return {
        "evidence_item_count": len(evidence_items),
        "source_count": len(source_statuses),
        "fetched_source_count": sum(1 for item in source_statuses if item.get("status") == "fetched"),
        "operator_image_source_count": sum(
            1 for item in source_statuses if item.get("status") == "operator_image_imported"
        ),
        "failed_source_count": sum(1 for item in source_statuses if item.get("status") == "fetch_failed"),
        "by_source_tier": dict(sorted(by_tier.items())),
        "by_source_family": dict(sorted(by_family.items())),
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _evidence_status(
    allow_network_fetch: bool,
    evidence_items: list[dict[str, Any]],
    source_statuses: list[dict[str, Any]],
) -> str:
    if evidence_items:
        return "ready_from_p0_p1_sources"
    if not source_statuses:
        return "planned_requires_source_discovery"
    if not allow_network_fetch:
        return "planned_no_network"
    if any(item.get("status") == "fetch_failed" for item in source_statuses):
        return "empty_fetch_failed"
    return "empty_no_matching_sources"


def _query_plan_status(
    allow_network_fetch: bool,
    source_count: int,
    image_source_count: int = 0,
) -> str:
    if image_source_count:
        return "ready_from_operator_image_list"
    if source_count == 0:
        return "planned_requires_source_discovery"
    return "ready_for_explicit_fetch" if allow_network_fetch else "planned_no_network"


def _boundary(*, allow_network_fetch: bool, network_calls_made: bool) -> dict[str, Any]:
    return {
        "candidate_only": True,
        "review_gated": True,
        "observed_fact": False,
        "runtime_safety_truth": False,
        "phase1_runtime_mutation_allowed": False,
        "phase2_brain_writeback_allowed": False,
        "safety_api_called": False,
        "network_calls_allowed": allow_network_fetch,
        "network_calls_made": network_calls_made,
        "raw_gpx_embedded_in_json": False,
        "raw_dem_embedded_in_json": False,
        "raw_tile_embedded_in_json": False,
        "raw_html_embedded_in_json": False,
        "large_scraped_text_embedded": False,
    }


def _candidate_id(project_id: str, source_id: str) -> str:
    raw = f"web_case.{project_id}.{source_id}"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("_")[:180]


def _collapse_ws(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)


def _update_project(path: Path, project: dict[str, Any], updates: dict[str, Any]) -> None:
    if not path.exists():
        return
    _write_json(path, {**project, **updates})


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.headings: list[str] = []
        self.text_chunks: list[str] = []
        self.image_refs: list[dict[str, Any]] = []
        self._skip_depth = 0
        self._current_tag = ""
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
        self._current_tag = tag
        if tag in {"title", "h1", "h2"}:
            self._buffer = []
        if tag == "meta":
            self._handle_meta_image(attrs)
        if tag == "link":
            self._handle_link_image(attrs)
        if tag == "img":
            attrs_dict = dict(attrs)
            src = attrs_dict.get("src")
            if src:
                self.image_refs.append(
                    {
                        "src": src,
                        "alt": attrs_dict.get("alt") or "",
                        "title": attrs_dict.get("title") or "",
                    }
                )
        if tag == "source":
            attrs_dict = dict(attrs)
            srcset = attrs_dict.get("srcset")
            if srcset:
                src = _first_srcset_url(srcset)
                if src:
                    self.image_refs.append(
                        {
                            "src": src,
                            "alt": "",
                            "title": attrs_dict.get("title") or "",
                        }
                    )

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self.title = _collapse_ws(" ".join(self._buffer))
            self._buffer = []
        elif tag in {"h1", "h2"}:
            heading = _collapse_ws(" ".join(self._buffer))
            if heading:
                self.headings.append(heading)
            self._buffer = []
        self._current_tag = ""

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        value = _collapse_ws(data)
        if not value:
            return
        self.text_chunks.append(value)
        if self._current_tag in {"title", "h1", "h2"}:
            self._buffer.append(value)

    def _handle_meta_image(self, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key.lower(): value for key, value in attrs if key}
        key = str(
            attrs_dict.get("property")
            or attrs_dict.get("name")
            or attrs_dict.get("itemprop")
            or ""
        ).lower()
        if key not in {
            "og:image",
            "og:image:url",
            "twitter:image",
            "twitter:image:src",
            "image",
        }:
            return
        content = attrs_dict.get("content")
        if content:
            self.image_refs.append(
                {
                    "src": content,
                    "alt": "",
                    "title": "",
                    "source_hint": key,
                }
            )

    def _handle_link_image(self, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key.lower(): value for key, value in attrs if key}
        rel = str(attrs_dict.get("rel") or "").lower()
        as_type = str(attrs_dict.get("as") or "").lower()
        href = attrs_dict.get("href")
        if not href:
            return
        if "image_src" not in rel and not ("preload" in rel and as_type == "image"):
            return
        self.image_refs.append(
            {
                "src": href,
                "alt": "",
                "title": attrs_dict.get("title") or "",
                "source_hint": f"link:{rel or as_type}",
            }
        )


def _first_srcset_url(srcset: str) -> str:
    for candidate in srcset.split(","):
        url = candidate.strip().split(" ", 1)[0].strip()
        if url:
            return url
    return ""


class _OperatorImageHTMLExtractor(HTMLParser):
    _CONTEXT_TAGS = {"figure", "article", "section", "div", "li"}

    def __init__(self) -> None:
        super().__init__()
        self.records: list[dict[str, Any]] = []
        self._context_stack: list[dict[str, Any]] = []
        self._anchor_stack: list[str] = []
        self._caption_buffer: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = self._attrs(attrs)
        if tag in self._CONTEXT_TAGS:
            self._context_stack.append(
                {
                    "tag": tag,
                    "start_index": len(self.records),
                    "context_layer": self._first_attr(
                        attrs_dict,
                        "data-context-layer",
                        "data-sec6-layer",
                        "data-scout-context-layer",
                        "data-layer",
                    ),
                    "page_url": self._first_attr(
                        attrs_dict,
                        "data-page-url",
                        "data-source-url",
                        "data-source-page-url",
                        "data-url",
                    ),
                    "source_tier": self._first_attr(attrs_dict, "data-source-tier"),
                    "source_family": self._first_attr(
                        attrs_dict,
                        "data-source-family",
                        "data-source-kind",
                    ),
                    "caption": self._first_attr(
                        attrs_dict,
                        "data-caption",
                        "aria-label",
                        "title",
                    ),
                }
            )
        if tag == "figcaption":
            self._caption_buffer = []
        if tag == "a":
            href = self._first_attr(attrs_dict, "href")
            self._anchor_stack.append(href if href.startswith(("http://", "https://")) else "")
            if self._anchor_stack[-1]:
                self._set_current_context("page_url", self._anchor_stack[-1])
                self._backfill_current_context_records("page_url", self._anchor_stack[-1])
        if tag == "img":
            record = self._record_from_image_attrs(attrs_dict)
            if record:
                self.records.append(record)

    def handle_endtag(self, tag: str) -> None:
        if tag == "figcaption" and self._caption_buffer is not None:
            caption = _collapse_ws(" ".join(self._caption_buffer))
            if caption:
                self._set_current_context("caption", caption)
                self._backfill_current_context_records("caption", caption)
            self._caption_buffer = None
        if tag == "a" and self._anchor_stack:
            self._anchor_stack.pop()
        if tag in self._CONTEXT_TAGS and self._context_stack:
            self._context_stack.pop()

    def handle_data(self, data: str) -> None:
        if self._caption_buffer is not None:
            self._caption_buffer.append(data)

    def _record_from_image_attrs(self, attrs: dict[str, str]) -> dict[str, Any] | None:
        src = self._first_attr(
            attrs,
            "src",
            "data-src",
            "data-original",
            "data-lazy-src",
        )
        if not src:
            src = _first_srcset_url(self._first_attr(attrs, "srcset", "data-srcset"))
        if not src:
            return None
        caption = self._first_attr(
            attrs,
            "data-caption",
            "alt",
            "title",
            "aria-label",
        )
        caption_source = "data" if self._first_attr(attrs, "data-caption") else "alt"
        page_url = (
            self._first_attr(
                attrs,
                "data-page-url",
                "data-source-url",
                "data-source-page-url",
                "data-url",
            )
            or self._current_context_value("page_url")
            or self._current_anchor_href()
        )
        context_layer = (
            self._first_attr(
                attrs,
                "data-context-layer",
                "data-sec6-layer",
                "data-scout-context-layer",
                "data-layer",
            )
            or self._current_context_value("context_layer")
        )
        data_label = self._first_attr(attrs, "data-label")
        return {
            "image_url": src,
            "page_url": page_url,
            "label": data_label or caption,
            "label_source": "data" if data_label else caption_source,
            "caption": caption or self._current_context_value("caption"),
            "caption_source": caption_source,
            "summary": self._first_attr(attrs, "data-summary"),
            "alt": self._first_attr(attrs, "alt") or caption,
            "title": self._first_attr(attrs, "title"),
            "context_layer": context_layer,
            "source_tier": self._first_attr(attrs, "data-source-tier")
            or self._current_context_value("source_tier"),
            "source_family": self._first_attr(
                attrs,
                "data-source-family",
                "data-source-kind",
            )
            or self._current_context_value("source_family"),
        }

    def _backfill_current_context_records(self, key: str, value: str) -> None:
        if not value:
            return
        context = self._current_context()
        if context is None:
            return
        raw_start_index = context.get("start_index")
        start_index = (
            int(raw_start_index)
            if raw_start_index is not None
            else len(self.records)
        )
        for record in self.records[start_index:]:
            if key == "caption" and record.get("caption_source") == "data":
                continue
            if key == "caption":
                record["caption"] = value
                if record.get("label_source") != "data":
                    record["label"] = value
                record["summary"] = record.get("summary") or value
            elif key == "page_url" and (
                not record.get("page_url") or record.get("page_url") == record.get("image_url")
            ):
                record["page_url"] = value
            elif not record.get(key):
                record[key] = value

    def _set_current_context(self, key: str, value: str) -> None:
        context = self._current_context()
        if context is not None and value and not context.get(key):
            context[key] = value

    def _current_context(self) -> dict[str, Any] | None:
        return self._context_stack[-1] if self._context_stack else None

    def _current_context_value(self, key: str) -> str:
        for context in reversed(self._context_stack):
            value = str(context.get(key) or "").strip()
            if value:
                return value
        return ""

    def _current_anchor_href(self) -> str:
        for href in reversed(self._anchor_stack):
            if href:
                return href
        return ""

    @staticmethod
    def _attrs(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {
            key.lower(): str(value or "").strip()
            for key, value in attrs
            if key
        }

    @staticmethod
    def _first_attr(attrs: dict[str, str], *keys: str) -> str:
        for key in keys:
            value = str(attrs.get(key.lower()) or "").strip()
            if value:
                return value
        return ""


class _AnchorExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._label: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attrs_dict = dict(attrs)
        href = attrs_dict.get("href")
        if href and href.startswith(("http://", "https://")):
            self._href = href
            self._label = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href:
            self.links.append((self._href, _collapse_ws(" ".join(self._label))))
            self._href = None
            self._label = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._label.append(data)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect Scout P0/P1 route context web evidence.")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--allow-network-fetch", action="store_true")
    parser.add_argument("--source-list-html", type=Path, default=None)
    parser.add_argument("--image-list-json", type=Path, default=None)
    parser.add_argument("--image-list-html", type=Path, default=None)
    parser.add_argument("--source-url", action="append", default=[])
    parser.add_argument("--route-keyword", action="append", default=[])
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--generated-at", default=None)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    source_records = [{"url": url} for url in args.source_url]
    payload = collect_pretrip_p0_p1_sources(
        args.project_root,
        allow_network_fetch=args.allow_network_fetch,
        dry_run=args.dry_run,
        source_records=source_records,
        source_list_html=args.source_list_html,
        image_list_json=args.image_list_json,
        image_list_html=args.image_list_html,
        route_keywords=args.route_keyword or None,
        generated_at=args.generated_at,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
