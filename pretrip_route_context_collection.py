from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit


ROUTE_CONTEXT_COLLECTION_ARTIFACT_KIND = "pretrip_route_context_collection"
ROUTE_CONTEXT_EVIDENCE_ARTIFACT_KIND = "pretrip_route_context_evidence"
ROUTE_CONTEXT_POINTS_ARTIFACT_KIND = "pretrip_route_context_points"
ROUTE_CONTEXT_SOURCE_MANIFEST_ARTIFACT_KIND = "pretrip_route_context_source_manifest"
ROUTE_CONTEXT_PACK_ARTIFACT_KIND = "pretrip_route_context_pack"
ROUTE_CONTEXT_CRAWL_SEED_PLAN_ARTIFACT_KIND = "pretrip_route_context_crawl_seed_plan"
ROUTE_CONTEXT_BRIEFING_ARTIFACT_KIND = "pretrip_route_context_briefing"
ROUTE_CONTEXT_MEDIA_MANIFEST_ARTIFACT_KIND = "pretrip_route_context_media_manifest"
ROUTE_CONTEXT_EVIDENCE_REF = "normalized/context/route_context/route_context_evidence.json"
ROUTE_CONTEXT_SOURCE_MANIFEST_REF = "normalized/context/route_context/source_manifest.json"
ROUTE_CONTEXT_PACK_REF = "normalized/context/route_context/route_context_pack.json"
ROUTE_CONTEXT_CRAWL_SEED_PLAN_REF = "normalized/context/route_context/crawl_seed_plan.json"
ROUTE_CONTEXT_MEDIA_MANIFEST_REF = "normalized/context/route_context/media_manifest.json"
ROUTE_CONTEXT_BRIEFING_REF = "outputs/briefings/route_context_briefing.html"
ROUTE_CONTEXT_POINTS_REF = "candidates/route_context_points.json"
ROUTE_MILEAGE_K_ANCHORS_REF = "candidates/route_mileage_k_anchors.json"
ROUTE_CONTEXT_SCHEMA_VERSION = "route_context_collection.v1"
DEFAULT_ROUTE_NOTE_LIMIT = 80
DEFAULT_ROUTE_NOTE_SEED_LIMIT = 60
DEFAULT_ROUTE_NOTE_POINT_POLICY = "seed_only"
BRIEFING_MEDIA_GALLERY_LIMIT = 18
BRIEFING_VISUAL_ANCHOR_LIMIT = 10
BRIEFING_PHOTO_ESSAY_CARD_LIMIT = 17
BRIEFING_TARGET_MIN_GALLERY_IMAGES = 12
BRIEFING_CONTEXT_LAYER_ORDER = (
    "route_overview",
    "historical",
    "cultural",
    "natural",
    "terrain",
    "seasonal",
    "observation_point",
)
BRIEFING_VISUAL_KIT_SLOT_COUNT = 6
MILEAGE_K_LABEL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(\d{1,3}(?:\.\d{1,2})?)\s*(?:[Kk]|[Kk][Mm]|公里)(?![A-Za-z0-9])"
)
FULLWIDTH_MILEAGE_TRANSLATION = str.maketrans(
    "０１２３４５６７８９．ＫｋＭｍ",
    "0123456789.KkMm",
)
ROAD_MILEAGE_HINT_PATTERN = re.compile(
    r"(?:台\s*\d|台\d|投\s*\d|投\d|縣\s*\d|縣\d|鄉\s*\d|鄉\d|"
    r"市道|省道|公路|道路|投\d+線|台\d+線|台\d+甲|台\d+-|寶來|甲仙|清泉橋)"
)
CONTOUR_ELEVATION_PATTERN = re.compile(r"(?<!\d)([1-3]\d{2,3})(?:\s*m|公尺)?(?!\d)")
MAP_LABEL_ROLE_ALIASES = {
    "route_mileage_k_anchor": "trail_mileage_k_anchor",
    "trail_mileage_k_anchor": "trail_mileage_k_anchor",
    "road_mileage_stone": "road_mileage_stone",
    "cellular_communication_point": "cellular_communication_point",
    "communication_point": "cellular_communication_point",
    "contour_elevation_label": "contour_elevation_label",
    "trail_name_label": "trail_name_label",
    "named_place_label": "named_place_label",
    "trail_annotation_label": "trail_annotation_label",
    "hazard_annotation_label": "hazard_annotation_label",
}


SEC6_ALIGNMENT = {
    "standard": "SCOUT_OUTDOOR_AI_AGENT_STANDARD",
    "section": "Sec. 6 Route Context Intelligence",
    "workspace_layout_section": "Outdoor AI Agent Data Placement",
    "canonical_refs": [
        "normalized/context/route_context/*.json",
        ROUTE_CONTEXT_PACK_REF,
        ROUTE_CONTEXT_SOURCE_MANIFEST_REF,
        ROUTE_CONTEXT_CRAWL_SEED_PLAN_REF,
        ROUTE_CONTEXT_MEDIA_MANIFEST_REF,
        ROUTE_CONTEXT_BRIEFING_REF,
        ROUTE_CONTEXT_POINTS_REF,
        "outputs/mcp/named_point_evidence.json",
        "outputs/layers/normalized/web_case_evidence.json",
        "outputs/layers/normalized/raster_label_evidence.geojson",
    ],
}


SOURCE_TIER_CATALOG: tuple[dict[str, str], ...] = (
    {"tier": "P0", "source_id": "forest_trail_data", "label": "林業及自然保育署自然步道資料", "role": "official_baseline"},
    {"tier": "P0", "source_id": "taiwan_mountain_forest_open_data", "label": "台灣山林悠遊網開放資料", "role": "official_baseline"},
    {"tier": "P0", "source_id": "mountain_permit_service", "label": "臺灣登山申請一站式服務網", "role": "official_baseline"},
    {"tier": "P0", "source_id": "national_park_route_status", "label": "國家公園路線開放狀態", "role": "official_status"},
    {"tier": "P0", "source_id": "nlsc_dem_dtm_topomap", "label": "內政部國土測繪中心 DEM / DTM / 地形圖", "role": "terrain_baseline"},
    {"tier": "P0", "source_id": "cwa_codis_open_data", "label": "中央氣象署 CODiS / 開放資料", "role": "weather_baseline"},
    {"tier": "P0", "source_id": "ncdr_disaster_potential", "label": "NCDR 災害潛勢資料", "role": "hazard_baseline"},
    {"tier": "P0", "source_id": "nfa_mountain_rescue_cases", "label": "消防署山域事故救援案件", "role": "incident_baseline"},
    {"tier": "P0", "source_id": "regional_fire_department_incident_feeds", "label": "地方消防局山域事故與即時災情", "role": "incident_local_baseline"},
    {"tier": "P0", "source_id": "government_open_data_mountain_incidents", "label": "政府資料開放平臺山域事故清冊 / 消防救援統計", "role": "incident_open_data_baseline"},
    {"tier": "P0", "source_id": "tbn_biodiversity", "label": "TBN 台灣生物多樣性網絡", "role": "natural_baseline"},
    {"tier": "P0", "source_id": "as_taiwan_century_maps", "label": "中研院臺灣百年歷史地圖", "role": "historical_map_baseline"},
    {"tier": "P0", "source_id": "tacp_indigenous_historic_trails", "label": "尋路・循路－臺灣原住民族古道空間資訊網", "role": "cultural_trail_baseline"},
    {"tier": "P1", "source_id": "national_culture_memory_bank", "label": "國家文化記憶庫", "role": "cultural_expansion"},
    {"tier": "P1", "source_id": "taiwan_memory", "label": "臺灣記憶", "role": "historical_expansion"},
    {"tier": "P1", "source_id": "indigenous_trail_spatial_info", "label": "原住民族古道空間資訊網", "role": "cultural_spatial_expansion"},
    {"tier": "P1", "source_id": "geology_cloud", "label": "地質雲", "role": "geology_expansion"},
    {"tier": "P1", "source_id": "osm_overpass_history", "label": "OpenStreetMap / Overpass / OSM full-history", "role": "map_expansion"},
    {"tier": "P1", "source_id": "rudymap", "label": "魯地圖", "role": "map_expansion"},
    {"tier": "P1", "source_id": "map_generator_hiker_gpx", "label": "地圖產生器 / 山友 GPX", "role": "community_route_seed"},
    {"tier": "P1", "source_id": "hiking_biji", "label": "健行筆記", "role": "community_article_evidence"},
    {"tier": "P1", "source_id": "hikingbook", "label": "Hikingbook", "role": "community_route_evidence"},
    {"tier": "P1", "source_id": "ptt_hiking", "label": "PTT Hiking", "role": "community_article_evidence"},
    {"tier": "P1", "source_id": "mountain_news_bbs", "label": "登山補給站", "role": "community_article_evidence"},
    {"tier": "P1", "source_id": "mountain_rescue_association_knowledge", "label": "中華民國山難救助協會 / 山域搜救訓練資料", "role": "rescue_training_reference"},
    {"tier": "P1", "source_id": "expert_field_rescue_media", "label": "跑山獸 / 山小白 / 公開搜救與登山專家影音", "role": "field_rescue_expert_observation"},
    {"tier": "P1", "source_id": "public_community_media_posts", "label": "公開社群影音與路線貼文", "role": "community_media_evidence"},
    {"tier": "P2", "source_id": "user_completed_gpx", "label": "使用者實際 GPX", "role": "scout_owned_observation"},
    {"tier": "P2", "source_id": "off_route_records", "label": "偏航紀錄", "role": "scout_owned_observation"},
    {"tier": "P2", "source_id": "stay_points", "label": "停留點", "role": "scout_owned_observation"},
    {"tier": "P2", "source_id": "photo_points", "label": "拍照點", "role": "scout_owned_observation"},
    {"tier": "P2", "source_id": "voice_notes", "label": "語音註記", "role": "scout_owned_observation"},
    {"tier": "P2", "source_id": "imu_anomalies", "label": "IMU 異常", "role": "scout_owned_observation"},
    {"tier": "P2", "source_id": "barometric_altitude_changes", "label": "氣壓高度變化", "role": "scout_owned_observation"},
    {"tier": "P2", "source_id": "front_rear_distance", "label": "前鋒/後衛距離", "role": "scout_owned_team_context"},
    {"tier": "P2", "source_id": "team_stretch_records", "label": "隊伍拉長紀錄", "role": "scout_owned_team_context"},
    {"tier": "P2", "source_id": "user_worth_stop_feedback", "label": "使用者回報「值得停」或「不值得停」", "role": "scout_owned_review_feedback"},
)


SOURCE_DEFAULTS: dict[str, dict[str, Any]] = {
    "mcp_candidates": {
        "project_ref_key": "mcp_candidates_ref",
        "default_ref": "outputs/mcp/mcp_candidates.json",
        "required_by_standard_sec6": True,
        "source_tier": "P1",
        "conclusion_role": "representative_candidate",
    },
    "named_point_evidence": {
        "project_ref_key": "mcp_named_point_evidence_ref",
        "default_ref": "outputs/mcp/named_point_evidence.json",
        "required_by_standard_sec6": True,
        "source_tier": "P1",
        "conclusion_role": "representative_candidate",
    },
    "route_note_candidates": {
        "project_ref_key": "route_note_candidates_ref",
        "default_ref": "candidates/route_note_candidates.json",
        "required_by_standard_sec6": False,
        "source_tier": "P2",
        "conclusion_role": "seed_only",
    },
    "ocr_label_evidence": {
        "project_ref_key": "mcp_ocr_labels_ref",
        "default_ref": "outputs/mcp/mcp_ocr_labels.json",
        "required_by_standard_sec6": False,
        "source_tier": "P1",
        "conclusion_role": "representative_candidate_after_review",
    },
    "web_case_evidence": {
        "project_ref_key": "web_case_evidence_ref",
        "default_ref": "outputs/layers/normalized/web_case_evidence.json",
        "required_by_standard_sec6": False,
        "source_tier": "P1",
        "conclusion_role": "primary_briefing_evidence",
    },
    "raster_label_evidence": {
        "project_ref_key": "raster_label_evidence_ref",
        "default_ref": "outputs/layers/normalized/raster_label_evidence.geojson",
        "required_by_standard_sec6": False,
        "source_tier": "P1",
        "conclusion_role": "representative_candidate_after_review",
    },
    "import_manifest": {
        "project_ref_key": "import_manifest_ref",
        "default_ref": "outputs/import_manifest.json",
        "required_by_standard_sec6": False,
        "source_tier": "P2",
        "conclusion_role": "provenance_only",
    },
    "route_summary": {
        "project_ref_key": "route_summary_ref",
        "default_ref": "normalized/routes/route_summary.json",
        "required_by_standard_sec6": False,
        "source_tier": "P2",
        "conclusion_role": "route_scope",
    },
}


def collect_pretrip_route_context(
    project_root: Path | str,
    *,
    dry_run: bool = False,
    include_route_notes: bool = True,
    limit_route_notes: int = DEFAULT_ROUTE_NOTE_LIMIT,
    route_note_point_policy: str = DEFAULT_ROUTE_NOTE_POINT_POLICY,
    route_keyword: str | None = None,
    write_briefing: bool = True,
    collected_at: str | None = None,
) -> dict[str, Any]:
    """Collect Sec. 6 route-context evidence after GPX import.

    The collector materializes candidate-only evidence into the workspace layout.
    It does not fetch live network sources, call safety APIs, or promote evidence
    into runtime truth.
    """

    root = Path(project_root)
    project = _load_json_object(root / "project.json")
    project_id = str(project.get("project_id") or project.get("id") or root.name)
    collected_at = collected_at or _utc_now()
    route_note_point_policy = str(
        route_note_point_policy or DEFAULT_ROUTE_NOTE_POINT_POLICY
    ).strip()
    if route_note_point_policy not in {"seed_only", "promote_representative"}:
        route_note_point_policy = DEFAULT_ROUTE_NOTE_POINT_POLICY
    route_bbox = _route_bbox(root, project)

    source_report: list[dict[str, Any]] = []
    points: list[dict[str, Any]] = []

    mcp_payload, mcp_ref, _ = _load_source(root, project, "mcp_candidates", source_report)
    points.extend(_points_from_mcp_candidates(mcp_payload, mcp_ref))

    named_payload, named_ref, _ = _load_source(root, project, "named_point_evidence", source_report)
    points.extend(_points_from_named_point_evidence(named_payload, named_ref))

    ocr_payload, ocr_ref, _ = _load_source(root, project, "ocr_label_evidence", source_report)
    points.extend(_points_from_ocr_labels(ocr_payload, ocr_ref))

    web_payload, web_ref, _ = _load_source(root, project, "web_case_evidence", source_report)
    points.extend(_points_from_web_case_evidence(web_payload, web_ref))

    raster_payload, raster_ref, _ = _load_source(root, project, "raster_label_evidence", source_report)
    points.extend(_points_from_raster_label_evidence(raster_payload, raster_ref))

    route_distance_m = _route_summary_distance_m(root, project)
    route_note_payload, route_note_ref, _ = _load_source(
        root,
        project,
        "route_note_candidates",
        source_report,
    )
    mileage_anchor_points = _points_from_route_note_mileage_anchors(
        route_note_payload,
        route_note_ref,
        route_bbox=route_bbox,
        route_distance_m=route_distance_m,
    )
    mileage_scan_summary = _route_note_mileage_scan_summary(
        route_note_payload,
        route_bbox=route_bbox,
        route_distance_m=route_distance_m,
    )
    points.extend(mileage_anchor_points)
    if include_route_notes:
        if route_note_point_policy != "seed_only":
            points.extend(
                _points_from_route_notes(
                    route_note_payload,
                    route_note_ref,
                    route_bbox=route_bbox,
                    limit=max(0, int(limit_route_notes)),
                )
            )

    import_manifest_payload, import_manifest_ref, _ = _load_source(
        root,
        project,
        "import_manifest",
        source_report,
    )
    route_summary_payload, route_summary_ref, _ = _load_source(
        root,
        project,
        "route_summary",
        source_report,
    )

    points = _dedupe_points(points)
    counts = _counts(points)
    mileage_anchor_points = [
        point
        for point in points
        if point.get("evidence_type") == "trail_mileage_k_anchor"
    ]
    evidence_ref = str(project.get("route_context_evidence_ref") or ROUTE_CONTEXT_EVIDENCE_REF)
    source_manifest_ref = str(
        project.get("route_context_source_manifest_ref")
        or ROUTE_CONTEXT_SOURCE_MANIFEST_REF
    )
    context_pack_ref = str(
        project.get("route_context_pack_ref") or ROUTE_CONTEXT_PACK_REF
    )
    crawl_seed_plan_ref = str(
        project.get("route_context_crawl_seed_plan_ref")
        or ROUTE_CONTEXT_CRAWL_SEED_PLAN_REF
    )
    media_manifest_ref = str(
        project.get("route_context_media_manifest_ref")
        or ROUTE_CONTEXT_MEDIA_MANIFEST_REF
    )
    briefing_ref = str(
        project.get("route_context_briefing_ref") or ROUTE_CONTEXT_BRIEFING_REF
    )
    points_ref = str(project.get("route_context_points_ref") or ROUTE_CONTEXT_POINTS_REF)
    mileage_anchors_ref = str(
        project.get("route_mileage_k_anchors_ref") or ROUTE_MILEAGE_K_ANCHORS_REF
    )
    planned_writes = [
        evidence_ref,
        source_manifest_ref,
        context_pack_ref,
        crawl_seed_plan_ref,
        media_manifest_ref,
        points_ref,
        mileage_anchors_ref,
    ]
    if write_briefing:
        planned_writes.append(briefing_ref)

    boundary = _closed_boundary(
        candidate_only=True,
        workspace_file_mutation_allowed=not dry_run,
        raw_payloads_embedded=False,
        source_fulltext_embedded=False,
    )
    points_payload = {
        "artifact_kind": ROUTE_CONTEXT_POINTS_ARTIFACT_KIND,
        "schema_version": ROUTE_CONTEXT_SCHEMA_VERSION,
        "project_id": project_id,
        "generated_at": collected_at,
        "source_evidence_ref": evidence_ref,
        "point_count": len(points),
        "counts": counts,
        "points": points,
        "boundary": boundary,
    }
    mileage_anchor_payload = _build_mileage_k_anchor_payload(
        project_id=project_id,
        generated_at=collected_at,
        anchors=mileage_anchor_points,
        route_context_points_ref=points_ref,
        scan_summary=mileage_scan_summary,
        boundary=boundary,
    )
    route_keywords = _route_keywords(
        project_id=project_id,
        route_keyword=route_keyword,
        route_summary=route_summary_payload,
    )
    crawl_seed_plan_payload = _build_crawl_seed_plan(
        project_id=project_id,
        generated_at=collected_at,
        route_keywords=route_keywords,
        route_note_payload=route_note_payload,
        route_note_ref=route_note_ref,
        route_bbox=route_bbox,
        include_route_notes=include_route_notes,
        route_note_point_policy=route_note_point_policy,
        limit=DEFAULT_ROUTE_NOTE_SEED_LIMIT,
        boundary=boundary,
    )
    source_manifest_payload = {
        "artifact_kind": ROUTE_CONTEXT_SOURCE_MANIFEST_ARTIFACT_KIND,
        "schema_version": ROUTE_CONTEXT_SCHEMA_VERSION,
        "project_id": project_id,
        "generated_at": collected_at,
        "source_report": source_report,
        "source_tiers": _source_tier_catalog(),
        "source_strategy": _source_strategy(),
        "crawl_seed_plan_ref": crawl_seed_plan_ref,
        "route_context_media_manifest_ref": media_manifest_ref,
        "route_context_briefing_ref": briefing_ref if write_briefing else None,
        "required_missing_source_kinds": [
            source["source_kind"]
            for source in source_report
            if source["required_by_standard_sec6"] and source["status"] != "loaded"
        ],
        "optional_missing_source_kinds": [
            source["source_kind"]
            for source in source_report
            if not source["required_by_standard_sec6"] and source["status"] == "missing"
        ],
        "cache_policy": {
            "mode": "offline_first_cache_first",
            "live_fetch_performed": False,
            "refresh_required_before_runtime_truth": True,
            "answer_order": [
                "local_cache",
                "route_context_pack",
                "local_spatial_index",
                "remote_source_connector_if_explicitly_allowed",
                "fallback_with_uncertainty",
            ],
        },
        "boundary": boundary,
    }
    context_pack_payload = {
        "artifact_kind": ROUTE_CONTEXT_PACK_ARTIFACT_KIND,
        "schema_version": ROUTE_CONTEXT_SCHEMA_VERSION,
        "project_id": project_id,
        "generated_at": collected_at,
        "route_summary_ref": route_summary_ref,
        "route_summary": _route_summary_for_pack(route_summary_payload),
        "route_context_evidence_ref": evidence_ref,
        "source_manifest_ref": source_manifest_ref,
        "route_context_points_ref": points_ref,
        "route_mileage_k_anchors_ref": mileage_anchors_ref,
        "crawl_seed_plan_ref": crawl_seed_plan_ref,
        "route_context_media_manifest_ref": media_manifest_ref,
        "route_context_briefing_ref": briefing_ref if write_briefing else None,
        "point_count": len(points),
        "route_mileage_k_anchor_count": mileage_anchor_payload["anchor_count"],
        "counts": counts,
        "query_policy": {
            "mode": "cache_first_tool_second",
            "local_answer_sources": [
                "route_context_points",
                "source_manifest",
                "route_summary",
            ],
            "stop_or_delay_advice_requires_contextual_permission": True,
        },
        "sensitivity_policy": _sensitivity_policy(),
        "observation_scoring_policy": _observation_scoring_policy(),
        "source_strategy": _source_strategy(),
        "route_note_point_policy": route_note_point_policy,
        "boundary": boundary,
    }
    evidence_payload = {
        "artifact_kind": ROUTE_CONTEXT_EVIDENCE_ARTIFACT_KIND,
        "schema_version": ROUTE_CONTEXT_SCHEMA_VERSION,
        "project_id": project_id,
        "generated_at": collected_at,
        "source_status": "candidate_only",
        "standard_alignment": SEC6_ALIGNMENT,
        "source_report": source_report,
        "counts": counts,
        "route_context_points_ref": points_ref,
        "route_mileage_k_anchors_ref": mileage_anchors_ref,
        "source_manifest_ref": source_manifest_ref,
        "route_context_pack_ref": context_pack_ref,
        "crawl_seed_plan_ref": crawl_seed_plan_ref,
        "route_context_media_manifest_ref": media_manifest_ref,
        "route_context_briefing_ref": briefing_ref if write_briefing else None,
        "import_manifest_ref": import_manifest_ref,
        "import_manifest_summary": _import_manifest_summary(import_manifest_payload),
        "project_update_suggestions": {
            "route_context_evidence_ref": evidence_ref,
            "route_context_source_manifest_ref": source_manifest_ref,
            "route_context_pack_ref": context_pack_ref,
            "route_context_crawl_seed_plan_ref": crawl_seed_plan_ref,
            "route_context_media_manifest_ref": media_manifest_ref,
            "route_context_briefing_ref": briefing_ref if write_briefing else None,
            "route_context_points_ref": points_ref,
            "route_mileage_k_anchors_ref": mileage_anchors_ref,
            "route_context_point_count": len(points),
            "route_mileage_k_anchor_count": mileage_anchor_payload["anchor_count"],
        },
        "boundary": boundary,
    }
    media_manifest_payload = _build_media_manifest(
        project_id=project_id,
        generated_at=collected_at,
        route_keywords=route_keywords,
        web_payload=web_payload,
        web_ref=web_ref,
        route_summary=_route_summary_for_pack(route_summary_payload),
        points=points,
        boundary=boundary,
    )
    briefing_html = _build_briefing_html(
        project_id=project_id,
        generated_at=collected_at,
        route_keywords=route_keywords,
        route_summary=_route_summary_for_pack(route_summary_payload),
        points=points,
        counts=counts,
        source_manifest=source_manifest_payload,
        crawl_seed_plan=crawl_seed_plan_payload,
        media_manifest=media_manifest_payload,
        boundary=boundary,
    )
    collection_payload = {
        "artifact_kind": ROUTE_CONTEXT_COLLECTION_ARTIFACT_KIND,
        "status": "completed",
        "dry_run": dry_run,
        "project_id": project_id,
        "writes_performed": False,
        "planned_refs": planned_writes,
        "route_context_point_count": len(points),
        "crawl_seed_count": crawl_seed_plan_payload["seed_count"],
        "counts": counts,
        "source_report": source_report,
        "outputs": {
            "route_context_evidence_ref": evidence_ref,
            "route_context_source_manifest_ref": source_manifest_ref,
            "route_context_pack_ref": context_pack_ref,
            "route_context_crawl_seed_plan_ref": crawl_seed_plan_ref,
            "route_context_media_manifest_ref": media_manifest_ref,
            "route_context_briefing_ref": briefing_ref if write_briefing else None,
            "route_context_points_ref": points_ref,
            "route_mileage_k_anchors_ref": mileage_anchors_ref,
        },
        "standard_alignment": SEC6_ALIGNMENT,
        "boundary": boundary,
    }

    if not dry_run:
        _write_json(root / evidence_ref, evidence_payload)
        _write_json(root / source_manifest_ref, source_manifest_payload)
        _write_json(root / context_pack_ref, context_pack_payload)
        _write_json(root / crawl_seed_plan_ref, crawl_seed_plan_payload)
        _write_json(root / media_manifest_ref, media_manifest_payload)
        _write_json(root / points_ref, points_payload)
        _write_json(root / mileage_anchors_ref, mileage_anchor_payload)
        if write_briefing:
            _write_text(root / briefing_ref, briefing_html)
        _update_project_refs(
            root / "project.json",
            project,
            {
                "route_context_evidence_ref": evidence_ref,
                "route_context_source_manifest_ref": source_manifest_ref,
                "route_context_pack_ref": context_pack_ref,
                "route_context_crawl_seed_plan_ref": crawl_seed_plan_ref,
                "route_context_media_manifest_ref": media_manifest_ref,
                "route_context_briefing_ref": briefing_ref if write_briefing else None,
                "route_context_points_ref": points_ref,
                "route_mileage_k_anchors_ref": mileage_anchors_ref,
                "route_context_point_count": len(points),
                "route_mileage_k_anchor_count": mileage_anchor_payload["anchor_count"],
                "route_context_crawl_seed_count": crawl_seed_plan_payload["seed_count"],
                "route_context_collection_updated_at": collected_at,
                "route_context_collection_schema_version": ROUTE_CONTEXT_SCHEMA_VERSION,
            },
        )
        collection_payload["writes_performed"] = True
        collection_payload["written_refs"] = planned_writes

    return collection_payload


def _points_from_mcp_candidates(payload: dict[str, Any], source_ref: str) -> list[dict[str, Any]]:
    candidates = payload.get("mcp_candidates") if isinstance(payload, dict) else []
    if not isinstance(candidates, list):
        return []
    points = []
    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        label = _first_text(raw.get("label"), raw.get("mcp_id"))
        classes = _str_list(raw.get("mcp_classes"))
        nearest_cp = raw.get("nearest_scout_cp")
        nearest_cp = nearest_cp if isinstance(nearest_cp, dict) else {}
        text_fields = [label, raw.get("mcp_id"), *classes, *(_str_list(raw.get("promotion_reasons")))]
        point = _base_point(
            source_kind="mcp_candidates",
            source_ref=source_ref,
            source_candidate_id=_first_text(raw.get("mcp_id"), label),
            label=label,
            lat=_float_or_none(raw.get("lat")),
            lon=_float_or_none(raw.get("lon")),
            distance_m=_float_or_none(raw.get("distance_m")),
            text_fields=text_fields,
        )
        point.update(
            {
                "evidence_type": "major_critical_point",
                "mcp_classes": classes,
                "nearest_cp_candidate_id": nearest_cp.get("candidate_id"),
                "linked_cp_candidates": _str_list(raw.get("linked_cp_candidates")),
                "linked_named_points": _str_list(raw.get("linked_named_points")),
                "review_state": raw.get("review_state") or "needs_human_review",
                "confidence": raw.get("confidence"),
                "mention_ratio": _float_or_none(raw.get("mention_ratio")),
                "accepted_evidence_page_count": raw.get("accepted_evidence_page_count"),
                "reference_gaps": _str_list(raw.get("missing_source_gaps")),
                "source_refs": _source_refs_for(source_ref, "mcp_candidates", raw),
            }
        )
        points.append(point)
    return points


def _points_from_named_point_evidence(payload: dict[str, Any], source_ref: str) -> list[dict[str, Any]]:
    named_points = payload.get("named_points") if isinstance(payload, dict) else []
    if not isinstance(named_points, list):
        return []
    points = []
    for raw in named_points:
        if not isinstance(raw, dict):
            continue
        position = raw.get("route_position")
        position = position if isinstance(position, dict) else {}
        label = _first_text(raw.get("canonical_name"), raw.get("named_point_id"))
        aliases = _str_list(raw.get("aliases"))
        classes = _str_list(raw.get("point_class"))
        text_fields = [
            label,
            raw.get("named_point_id"),
            *aliases,
            *classes,
            *(_str_list(raw.get("source_families"))),
        ]
        point = _base_point(
            source_kind="named_point_evidence",
            source_ref=source_ref,
            source_candidate_id=_first_text(raw.get("named_point_id"), label),
            label=label,
            lat=_float_or_none(position.get("lat")),
            lon=_float_or_none(position.get("lon")),
            distance_m=_float_or_none(position.get("distance_m")),
            text_fields=text_fields,
            extra_evidence_families=["named_point", "article"],
        )
        point.update(
            {
                "evidence_type": "named_point",
                "aliases": aliases,
                "point_classes": classes,
                "confidence": position.get("coordinate_confidence"),
                "source_freshness": _source_freshness_from_raw_stale_risk(
                    raw.get("stale_risk"),
                    fallback=point["source_freshness"],
                ),
                "mention_ratio": _float_or_none(raw.get("mention_ratio")),
                "mention_page_count": raw.get("mention_page_count"),
                "source_families": _str_list(raw.get("source_families")),
                "reference_gaps": _str_list(raw.get("missing_source_families")),
                "source_refs": _source_refs_for(source_ref, "named_point_evidence", raw),
            }
        )
        points.append(point)
    return points


def _points_from_ocr_labels(payload: dict[str, Any], source_ref: str) -> list[dict[str, Any]]:
    labels = payload.get("labels") if isinstance(payload, dict) else []
    if not isinstance(labels, list):
        return []
    points = []
    for raw in labels:
        if not isinstance(raw, dict):
            continue
        label = _first_text(raw.get("label_text"), raw.get("ocr_label_id"))
        label_role = _map_label_role_from_raw(raw, label)
        mileage = _mileage_anchor_from_text(label, label_role=label_role)
        if mileage:
            label_role = mileage["label_role"]
        lat, lon = _lat_lon_from(raw)
        review_reasons = _mileage_review_reasons(
            mileage,
            lat=lat,
            lon=lon,
            route_distance_m=None,
            coordinate_spread_m=None,
            source_evidence_count=1,
        )
        point = _base_point(
            source_kind="ocr_label_evidence",
            source_ref=source_ref,
            source_candidate_id=_first_text(raw.get("ocr_label_id"), label),
            label=label,
            lat=lat,
            lon=lon,
            distance_m=_float_or_none(raw.get("distance_m")),
            text_fields=[
                label,
                raw.get("named_point_id"),
                raw.get("source_ref"),
                label_role,
            ],
            extra_evidence_families=_map_label_evidence_families(label_role, mileage),
        )
        point.update(
            {
                "evidence_type": _map_label_evidence_type(label_role, mileage, "ocr_map_label"),
                "label_role": label_role,
                "named_point_id": raw.get("named_point_id"),
                "confidence": raw.get("confidence"),
                "review_state": "needs_human_review"
                if raw.get("review_required", True) or review_reasons
                else "candidate",
                "source_refs": _source_refs_for(source_ref, "ocr_label_evidence", raw),
            }
        )
        if mileage:
            point.update(
                _mileage_anchor_point_fields(
                    mileage,
                    route_context_key=_first_text(raw.get("route_context_key"), "workspace_route"),
                    source_evidence_count=1,
                    coordinate_source=_first_text(
                        raw.get("coordinate_source"),
                        "ocr_label_geometry",
                    ),
                    review_reasons=review_reasons,
                    raw_label_examples=[label],
                    supporting_candidate_ids=[_first_text(raw.get("ocr_label_id"), label)],
                )
            )
        else:
            point.update(_map_label_role_fields(label_role, label))
        points.append(point)
    return points


def _points_from_web_case_evidence(payload: dict[str, Any], source_ref: str) -> list[dict[str, Any]]:
    records = _list_from_any(payload, ("points", "candidates", "evidence", "cases"))
    points = []
    for raw in records:
        if not isinstance(raw, dict):
            continue
        label = _first_text(raw.get("label"), raw.get("title"), raw.get("name"), raw.get("id"))
        lat, lon = _lat_lon_from(raw)
        point = _base_point(
            source_kind="web_case_evidence",
            source_ref=source_ref,
            source_candidate_id=_first_text(raw.get("candidate_id"), raw.get("id"), label),
            label=label,
            lat=lat,
            lon=lon,
            distance_m=_float_or_none(raw.get("distance_m")),
            text_fields=[label, raw.get("summary"), raw.get("source_family"), raw.get("url")],
            extra_evidence_families=["article"],
        )
        point.update(
            {
                "evidence_type": "web_case_evidence",
                "source_tier": str(raw.get("source_tier") or point["source_tier"]),
                "source_family": raw.get("source_family"),
                "source_families": _str_list(raw.get("source_families") or raw.get("source_family")),
                "source_refs": _source_refs_for(source_ref, "web_case_evidence", raw),
            }
        )
        points.append(point)
    return points


def _points_from_raster_label_evidence(payload: dict[str, Any], source_ref: str) -> list[dict[str, Any]]:
    records = _geojson_features(payload) or _list_from_any(payload, ("features", "labels", "points"))
    points = []
    for raw in records:
        if not isinstance(raw, dict):
            continue
        props = raw.get("properties") if isinstance(raw.get("properties"), dict) else raw
        label = _first_text(
            props.get("label"),
            props.get("label_text"),
            props.get("name"),
            props.get("id"),
        )
        lat, lon = _lat_lon_from(raw)
        if lat is None or lon is None:
            lat, lon = _lat_lon_from(props)
        label_role = _map_label_role_from_raw(props, label)
        mileage = _mileage_anchor_from_text(label, label_role=label_role)
        if mileage:
            label_role = mileage["label_role"]
        review_reasons = _mileage_review_reasons(
            mileage,
            lat=lat,
            lon=lon,
            route_distance_m=None,
            coordinate_spread_m=None,
            source_evidence_count=1,
        )
        point = _base_point(
            source_kind="raster_label_evidence",
            source_ref=source_ref,
            source_candidate_id=_first_text(props.get("candidate_id"), props.get("id"), label),
            label=label,
            lat=lat,
            lon=lon,
            distance_m=_float_or_none(props.get("distance_m")),
            text_fields=[label, props.get("class"), props.get("source_ref"), label_role],
            extra_evidence_families=_map_label_evidence_families(label_role, mileage),
        )
        point.update(
            {
                "evidence_type": _map_label_evidence_type(label_role, mileage, "raster_map_label"),
                "label_role": label_role,
                "confidence": props.get("confidence"),
                "review_state": "needs_human_review" if review_reasons else props.get("review_state", "candidate"),
                "source_refs": _source_refs_for(source_ref, "raster_label_evidence", props),
            }
        )
        if mileage:
            point.update(
                _mileage_anchor_point_fields(
                    mileage,
                    route_context_key=_first_text(props.get("route_context_key"), "workspace_route"),
                    source_evidence_count=1,
                    coordinate_source=_first_text(
                        props.get("coordinate_source"),
                        "raster_label_geometry",
                    ),
                    review_reasons=review_reasons,
                    raw_label_examples=[label],
                    supporting_candidate_ids=[
                        _first_text(props.get("candidate_id"), props.get("id"), label)
                    ],
                )
            )
        else:
            point.update(_map_label_role_fields(label_role, label))
        points.append(point)
    return points


def _points_from_route_note_mileage_anchors(
    payload: dict[str, Any],
    source_ref: str,
    *,
    route_bbox: dict[str, float] | None,
    route_distance_m: float | None,
) -> list[dict[str, Any]]:
    candidates = payload.get("candidates") if isinstance(payload, dict) else []
    if not isinstance(candidates, list):
        return []

    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        label = _first_text(raw.get("normalized_note"), raw.get("name"), raw.get("note"), raw.get("raw_note"))
        mileage = _mileage_anchor_from_text(
            label,
            route_distance_m=route_distance_m,
        )
        if not mileage:
            continue
        lat = _float_or_none(raw.get("lat"))
        lon = _float_or_none(raw.get("lon"))
        if (
            route_bbox
            and lat is not None
            and lon is not None
            and not _within_bbox(lat, lon, route_bbox, padding_degrees=0.03)
        ):
            continue
        route_context_key = _first_text(raw.get("route_context_key"), "workspace_route")
        key = (
            route_context_key,
            mileage["label_role"],
            mileage["normalized_mileage_k"],
        )
        item = grouped.setdefault(
            key,
            {
                "route_context_key": route_context_key,
                "mileage": mileage,
                "records": [],
                "labels": [],
                "candidate_ids": [],
                "source_refs": [],
                "coordinates": [],
                "golden_coordinates": [],
            },
        )
        item["records"].append(raw)
        item["labels"].append(label)
        item["candidate_ids"].append(_first_text(raw.get("candidate_id"), label))
        item["source_refs"].append(_source_refs_for(source_ref, "route_note_candidates", raw))
        if lat is not None and lon is not None:
            item["coordinates"].append((lat, lon))
            if "golden_route" in str(raw.get("candidate_id") or ""):
                item["golden_coordinates"].append((lat, lon))

    points = []
    for item in grouped.values():
        mileage = item["mileage"]
        coordinates = item["coordinates"]
        lat, lon, coordinate_source = _representative_mileage_coordinate(item)
        coordinate_spread_m = _coordinate_spread_m(coordinates)
        source_evidence_count = len(item["records"])
        review_reasons = _mileage_review_reasons(
            mileage,
            lat=lat,
            lon=lon,
            route_distance_m=route_distance_m,
            coordinate_spread_m=coordinate_spread_m,
            source_evidence_count=source_evidence_count,
        )
        label = mileage["normalized_mileage_k"]
        source_candidate_id = (
            f"{item['route_context_key']}.{mileage['normalized_mileage_k']}"
        )
        point = _base_point(
            source_kind="route_note_candidates",
            source_ref=source_ref,
            source_candidate_id=source_candidate_id,
            label=label,
            lat=lat,
            lon=lon,
            distance_m=mileage["mileage_m"],
        text_fields=[
                label,
                mileage["label_role"],
                "里程樁",
                *item["labels"][:8],
            ],
            extra_evidence_families=["route_note", "route_mileage", "map_label"],
        )
        point.update(
            {
                "evidence_type": mileage["evidence_type"],
                "label_role": mileage["label_role"],
                "confidence": _mileage_anchor_confidence(source_evidence_count, review_reasons),
                "review_state": "needs_human_review" if review_reasons else "candidate",
                "coordinate_spread_m": coordinate_spread_m,
                "source_refs": _merge_source_refs(*item["source_refs"]),
            }
        )
        point.update(
            _mileage_anchor_point_fields(
                mileage,
                route_context_key=item["route_context_key"],
                source_evidence_count=source_evidence_count,
                coordinate_source=coordinate_source,
                review_reasons=review_reasons,
                raw_label_examples=_unique_texts(item["labels"], limit=8),
                supporting_candidate_ids=_unique_texts(item["candidate_ids"], limit=24),
            )
        )
        points.append(point)
    return sorted(points, key=lambda point: (point.get("mileage_k") or 0.0, point.get("label") or ""))


def _route_note_mileage_scan_summary(
    payload: dict[str, Any],
    *,
    route_bbox: dict[str, float] | None,
    route_distance_m: float | None,
) -> dict[str, Any]:
    candidates = payload.get("candidates") if isinstance(payload, dict) else []
    if not isinstance(candidates, list):
        candidates = []

    raw_mileage_hit_count = 0
    kept_within_route_bbox_count = 0
    route_bbox_filtered_out_count = 0
    missing_coordinate_count = 0
    unique_values: dict[str, set[str]] = {
        "trail_mileage_k_anchor": set(),
        "road_mileage_stone": set(),
    }
    kept_values: dict[str, set[str]] = {
        "trail_mileage_k_anchor": set(),
        "road_mileage_stone": set(),
    }

    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        label = _first_text(
            raw.get("normalized_note"),
            raw.get("name"),
            raw.get("note"),
            raw.get("raw_note"),
        )
        mileage = _mileage_anchor_from_text(
            label,
            route_distance_m=route_distance_m,
        )
        if not mileage:
            continue
        raw_mileage_hit_count += 1
        evidence_type = str(mileage["evidence_type"])
        normalized = str(mileage["normalized_mileage_k"])
        unique_values.setdefault(evidence_type, set()).add(normalized)

        lat = _float_or_none(raw.get("lat"))
        lon = _float_or_none(raw.get("lon"))
        if lat is None or lon is None:
            missing_coordinate_count += 1
            continue
        if route_bbox and not _within_bbox(lat, lon, route_bbox, padding_degrees=0.03):
            route_bbox_filtered_out_count += 1
            continue
        kept_within_route_bbox_count += 1
        kept_values.setdefault(evidence_type, set()).add(normalized)

    return {
        "source_kind": "route_note_candidates",
        "source_candidate_count": len(candidates),
        "raw_mileage_label_hit_count": raw_mileage_hit_count,
        "unique_mileage_label_count": sum(len(values) for values in unique_values.values()),
        "unique_trail_mileage_k_count": len(unique_values["trail_mileage_k_anchor"]),
        "unique_road_mileage_stone_count": len(unique_values["road_mileage_stone"]),
        "kept_within_route_bbox_count": kept_within_route_bbox_count,
        "route_bbox_filtered_out_count": route_bbox_filtered_out_count,
        "missing_coordinate_count": missing_coordinate_count,
        "route_bbox_padding_degrees": 0.03,
        "complete_scan_before_route_bbox_filter": True,
        "trail_k_anchors_are_route_bbox_filtered": True,
        "road_mileage_stones_are_not_trail_k_anchors": True,
        "unique_trail_mileage_k_values_all": _sort_mileage_labels(
            unique_values["trail_mileage_k_anchor"]
        ),
        "unique_road_mileage_stone_values_all": _sort_mileage_labels(
            unique_values["road_mileage_stone"]
        ),
        "unique_trail_mileage_k_values_kept": _sort_mileage_labels(
            kept_values["trail_mileage_k_anchor"]
        ),
        "unique_road_mileage_stone_values_kept": _sort_mileage_labels(
            kept_values["road_mileage_stone"]
        ),
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _points_from_route_notes(
    payload: dict[str, Any],
    source_ref: str,
    *,
    route_bbox: dict[str, float] | None,
    limit: int,
) -> list[dict[str, Any]]:
    candidates = payload.get("candidates") if isinstance(payload, dict) else []
    if not isinstance(candidates, list) or limit <= 0:
        return []

    ranked: list[tuple[tuple[int, int, str], dict[str, Any]]] = []
    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        label = _first_text(raw.get("normalized_note"), raw.get("name"), raw.get("candidate_id"))
        category = str(raw.get("note_category") or "")
        lat = _float_or_none(raw.get("lat"))
        lon = _float_or_none(raw.get("lon"))
        if not _is_meaningful_route_note(label, category):
            continue
        if route_bbox and lat is not None and lon is not None and not _within_bbox(
            lat,
            lon,
            route_bbox,
            padding_degrees=0.03,
        ):
            continue
        rank = _route_note_rank(label, category)
        ranked.append((rank, raw))

    ranked.sort(key=lambda item: item[0])
    points = []
    for _, raw in ranked[:limit]:
        label = _first_text(raw.get("normalized_note"), raw.get("name"), raw.get("candidate_id"))
        category = str(raw.get("note_category") or "")
        text_fields = [
            label,
            category,
            raw.get("model_output_summary"),
            raw.get("desc"),
            raw.get("cmt"),
        ]
        point = _base_point(
            source_kind="route_note_candidates",
            source_ref=source_ref,
            source_candidate_id=_first_text(raw.get("candidate_id"), label),
            label=label,
            lat=_float_or_none(raw.get("lat")),
            lon=_float_or_none(raw.get("lon")),
            distance_m=_float_or_none(raw.get("distance_m")),
            text_fields=text_fields,
            extra_evidence_families=["route_note"],
        )
        point.update(
            {
                "evidence_type": "route_note_candidate",
                "route_note_category": category,
                "confidence": raw.get("confidence"),
                "review_state": raw.get("review_state") or "needs_review",
                "source_freshness": _source_freshness_from_route_note(raw),
                "route_note_freshness": raw.get("route_note_freshness"),
                "potential_ln_signal": bool(raw.get("potential_ln_signal", False)),
                "source_refs": _source_refs_for(source_ref, "route_note_candidates", raw),
            }
        )
        points.append(point)
    return points


def _base_point(
    *,
    source_kind: str,
    source_ref: str,
    source_candidate_id: str,
    label: str,
    lat: float | None,
    lon: float | None,
    distance_m: float | None,
    text_fields: list[Any],
    extra_evidence_families: list[str] | None = None,
) -> dict[str, Any]:
    sec6_layers = _sec6_layers(text_fields)
    evidence_families = sorted({source_kind, *(extra_evidence_families or [])})
    context_kind = _context_kind(sec6_layers, text_fields)
    sensitivity = _sensitivity_level(sec6_layers, text_fields)
    observation_score = _observation_score(
        context_kind,
        sec6_layers=sec6_layers,
        evidence_families=evidence_families,
        text_fields=text_fields,
    )
    return {
        "candidate_id": _candidate_id("route_context", source_kind, source_candidate_id),
        "source_candidate_id": source_candidate_id,
        "label": label,
        "display_label": _display_label(label, source_candidate_id),
        "context_kind": context_kind,
        "sec6_layers": sec6_layers,
        "evidence_families": evidence_families,
        "source_tier": _source_tier_for(source_kind),
        "promotion_basis": _promotion_basis_for(source_kind),
        "sensitivity_level": sensitivity,
        "display_policy": _display_policy(sensitivity),
        "source_freshness": _source_freshness(source_kind, text_fields),
        "observation_score": observation_score,
        "stop_advisory_candidate": _stop_advisory_candidate(context_kind, observation_score),
        "lat": lat,
        "lon": lon,
        "distance_m": distance_m,
        "candidate_only": True,
        "requires_human_review": True,
        "runtime_safety_truth": False,
        "phase1_runtime_mutation_allowed": False,
        "phase2_brain_writeback_allowed": False,
        "safety_api_called": False,
        "source_path": source_ref,
    }


def _sec6_layers(values: list[Any]) -> list[str]:
    text = _normalize(" ".join(str(value or "") for value in values))
    layers = []
    if _has_any(
        text,
        (
            "old",
            "historic",
            "history",
            "trail",
            "police",
            "station",
            "古道",
            "舊",
            "警備",
            "駐在",
            "保線",
            "產業道路",
        ),
    ):
        layers.append("historical")
    if _has_any(text, ("indigenous", "tribe", "culture", "地名", "舊社", "獵徑", "文化", "傳說")):
        layers.append("cultural")
    if _has_any(
        text,
        (
            "forest",
            "plant",
            "creek",
            "vegetation",
            "geology",
            "bird",
            "林",
            "溪",
            "植被",
            "自然",
            "地質",
            "鳥",
        ),
    ):
        layers.append("natural")
    if _has_any(
        text,
        (
            "ridge",
            "saddle",
            "valley",
            "collapse",
            "cliff",
            "slope",
            "rope",
            "fork",
            "junction",
            "pass",
            "peak",
            "崩",
            "稜",
            "谷",
            "啞口",
            "鞍",
            "峰",
            "坡",
            "崖",
            "叉路",
            "吊橋",
        ),
    ):
        layers.append("terrain")
    if _has_any(text, ("flower", "cloud", "maple", "rain", "season", "芒草", "花", "楓", "雲海", "雨季", "雪")):
        layers.append("seasonal")
    if _has_any(text, ("viewpoint", "view", "photo", "observation", "大景", "觀景", "展望", "拍", "看")):
        layers.append("observation_point")
    return layers or ["route_context"]


def _context_kind(sec6_layers: list[str], values: list[Any]) -> str:
    text = _normalize(" ".join(str(value or "") for value in values))
    if "observation_point" in sec6_layers:
        return "viewpoint"
    if _has_any(text, ("water", "camp", "hut", "保線所", "水塘", "營地", "山屋", "取水")):
        return "resource_context"
    if _has_any(text, ("fork", "junction", "turn", "叉路", "轉彎", "路口", "岔")):
        return "navigation_context"
    if _has_any(text, ("hazard", "risk", "warning", "collapse", "崩", "危險", "裸露", "斷崖")):
        return "risk_context"
    if "natural" in sec6_layers:
        return "natural_context"
    if "historical" in sec6_layers or "cultural" in sec6_layers:
        return "route_context"
    return "route_context"


def _sensitivity_level(sec6_layers: list[str], values: list[Any]) -> str:
    text = _normalize(" ".join(str(value or "") for value in values))
    if _has_any(
        text,
        (
            "祖靈",
            "墓",
            "墓地",
            "禁忌",
            "祭場",
            "傳統領域",
            "private",
            "restricted",
            "burial",
            "sacred",
        ),
    ):
        return "restricted"
    if _has_any(text, ("舊社", "獵徑", "部落", "原住民", "indigenous", "tribe")):
        return "sensitive"
    if "cultural" in sec6_layers:
        return "cultural_review"
    return "public"


def _display_policy(sensitivity_level: str) -> dict[str, Any]:
    if sensitivity_level == "restricted":
        return {
            "show_label": True,
            "show_exact_coordinate": False,
            "coordinate_precision": "hidden_or_area_only",
            "requires_human_review_before_display": True,
            "reason": "restricted cultural or private-location context",
        }
    if sensitivity_level in {"sensitive", "cultural_review"}:
        return {
            "show_label": True,
            "show_exact_coordinate": False,
            "coordinate_precision": "fuzzy_250m",
            "requires_human_review_before_display": True,
            "reason": "cultural context requires review before precise display",
        }
    return {
        "show_label": True,
        "show_exact_coordinate": True,
        "coordinate_precision": "exact_candidate_coordinate",
        "requires_human_review_before_display": False,
        "reason": "public candidate context",
    }


def _source_freshness(source_kind: str, values: list[Any]) -> dict[str, Any]:
    text = _normalize(" ".join(str(value or "") for value in values))
    if _has_any(text, ("stale", "過舊", "route_note_age_days")):
        status = "stale"
    elif source_kind in {"web_case_evidence", "raster_label_evidence"}:
        status = "unknown"
    elif source_kind == "route_note_candidates":
        status = "stale_or_unknown"
    else:
        status = "unknown"
    ttl_policy = {
        "mcp_candidates": "refresh_when_source_pack_changes",
        "named_point_evidence": "refresh_when_search_pack_changes",
        "ocr_label_evidence": "refresh_when_raster_tile_changes",
        "web_case_evidence": "refresh_before_public_answer_if_network_allowed",
        "raster_label_evidence": "refresh_when_map_layer_changes",
        "route_note_candidates": "review_age_before_promotion",
    }.get(source_kind, "unknown")
    return {
        "status": status,
        "ttl_policy": ttl_policy,
        "requires_refresh_before_runtime_truth": True,
    }


def _source_tier_for(source_kind: str) -> str:
    spec = SOURCE_DEFAULTS.get(source_kind, {})
    return str(spec.get("source_tier") or "unknown")


def _promotion_basis_for(source_kind: str) -> str:
    spec = SOURCE_DEFAULTS.get(source_kind, {})
    return str(spec.get("conclusion_role") or "candidate_evidence")


def _source_freshness_from_raw_stale_risk(
    stale_risk: Any,
    *,
    fallback: dict[str, Any],
) -> dict[str, Any]:
    if not stale_risk:
        return fallback
    status = {
        "low": "recent_enough_for_pretrip",
        "medium": "review_recommended",
        "high": "stale",
    }.get(str(stale_risk), "unknown")
    return {
        **fallback,
        "status": status,
        "stale_risk": str(stale_risk),
        "requires_refresh_before_runtime_truth": True,
    }


def _source_freshness_from_route_note(raw: dict[str, Any]) -> dict[str, Any]:
    freshness = str(raw.get("route_note_freshness") or "unknown")
    age_days = raw.get("route_note_age_days")
    status = "stale" if freshness == "stale" else freshness
    return {
        "status": status,
        "route_note_age_days": age_days,
        "ttl_policy": "review_age_before_promotion",
        "requires_refresh_before_runtime_truth": True,
    }


def _observation_score(
    context_kind: str,
    *,
    sec6_layers: list[str],
    evidence_families: list[str],
    text_fields: list[Any],
) -> dict[str, Any]:
    observation_value = 25.0
    reason_codes = ["candidate_context"]
    if context_kind == "viewpoint" or "observation_point" in sec6_layers:
        observation_value += 30.0
        reason_codes.append("observation_point")
    if "historical" in sec6_layers:
        observation_value += 14.0
        reason_codes.append("historical_context")
    if "cultural" in sec6_layers:
        observation_value += 12.0
        reason_codes.append("cultural_context")
    if "natural" in sec6_layers:
        observation_value += 10.0
        reason_codes.append("natural_context")
    if context_kind == "resource_context":
        observation_value += 10.0
        reason_codes.append("resource_context")
    if len(evidence_families) >= 3:
        observation_value += 8.0
        reason_codes.append("multi_source_support")

    text = _normalize(" ".join(str(value or "") for value in text_fields))
    risk_penalty = 0.0
    if context_kind == "risk_context" or _has_any(text, ("崩", "危險", "裸露", "斷崖", "hazard", "risk")):
        risk_penalty += 35.0
        reason_codes.append("risk_context_penalty")
    if _has_any(text, ("風口", "窄稜", "cliff", "exposure")):
        risk_penalty += 20.0
        reason_codes.append("exposure_penalty")

    value = max(0.0, min(100.0, observation_value - risk_penalty))
    return {
        "value": round(value, 1),
        "observation_value": round(min(100.0, observation_value), 1),
        "risk_penalty": round(risk_penalty, 1),
        "reason_codes": reason_codes,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _stop_advisory_candidate(
    context_kind: str,
    observation_score: dict[str, Any],
) -> str:
    value = _float_or_none(observation_score.get("value")) or 0.0
    risk_penalty = _float_or_none(observation_score.get("risk_penalty")) or 0.0
    if context_kind == "risk_context" or risk_penalty >= 35.0:
        return "pass_through_or_minimize_exposure"
    if value >= 60.0:
        return "short_stop_requires_contextual_permission"
    if value >= 35.0:
        return "context_reference_only"
    return "low_priority_context_reference"


def _load_source(
    root: Path,
    project: dict[str, Any],
    source_kind: str,
    source_report: list[dict[str, Any]],
) -> tuple[dict[str, Any], str, Path]:
    spec = SOURCE_DEFAULTS[source_kind]
    ref = str(project.get(spec["project_ref_key"]) or spec["default_ref"])
    path = _project_path(root, ref)
    payload = _load_json_object(path)
    count = _source_count(source_kind, payload)
    status = "loaded" if count > 0 else "empty"
    if not path.exists():
        status = "missing"
    source_tier, source_tier_counts = _source_tier_summary(source_kind, payload, spec)
    report = {
        "source_kind": source_kind,
        "status": status,
        "source_path": ref,
        "loaded_count": count,
        "required_by_standard_sec6": bool(spec["required_by_standard_sec6"]),
        "source_tier": source_tier,
        "conclusion_role": spec.get("conclusion_role"),
        "sha256": _sha256(path) if path.exists() and path.is_file() else None,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    if source_tier_counts:
        report["source_tier_counts"] = source_tier_counts
    source_report.append(report)
    return payload, ref, path


def _source_tier_summary(
    source_kind: str,
    payload: dict[str, Any],
    spec: dict[str, Any],
) -> tuple[str, dict[str, int]]:
    default_tier = str(spec.get("source_tier") or "unknown")
    if source_kind != "web_case_evidence" or not payload:
        return default_tier, {}
    counts: dict[str, int] = {}
    for raw in _list_from_any(payload, ("points", "candidates", "evidence", "cases")):
        if not isinstance(raw, dict):
            continue
        tier = str(raw.get("source_tier") or default_tier)
        counts[tier] = counts.get(tier, 0) + 1
    if not counts:
        return default_tier, {}
    if len(counts) == 1:
        return next(iter(counts)), dict(sorted(counts.items()))
    return "mixed:" + "/".join(sorted(counts)), dict(sorted(counts.items()))


def _source_count(source_kind: str, payload: dict[str, Any]) -> int:
    if not payload:
        return 0
    if source_kind == "mcp_candidates":
        return len(payload.get("mcp_candidates") or [])
    if source_kind == "named_point_evidence":
        return len(payload.get("named_points") or [])
    if source_kind == "route_note_candidates":
        return len(payload.get("candidates") or [])
    if source_kind == "ocr_label_evidence":
        return len(payload.get("labels") or [])
    if source_kind == "web_case_evidence":
        return len(_list_from_any(payload, ("points", "candidates", "evidence", "cases")))
    if source_kind == "raster_label_evidence":
        return len(_geojson_features(payload) or _list_from_any(payload, ("features", "labels", "points")))
    return 1


def _mileage_anchor_from_text(
    value: Any,
    *,
    label_role: str = "",
    route_distance_m: float | None = None,
) -> dict[str, Any] | None:
    text = _normalize_mileage_text(value)
    if not text:
        return None
    match = MILEAGE_K_LABEL_PATTERN.search(text)
    if not match:
        return None
    mileage_k = _float_or_none(match.group(1))
    if mileage_k is None:
        return None
    canonical_role = _canonical_map_label_role(label_role)
    if not canonical_role:
        canonical_role = (
            "road_mileage_stone"
            if _looks_like_road_mileage_label(text)
            or (
                route_distance_m is not None
                and round(mileage_k * 1000.0, 3) > route_distance_m + 1000.0
            )
            else "trail_mileage_k_anchor"
        )
    if canonical_role == "route_mileage_k_anchor":
        canonical_role = "trail_mileage_k_anchor"
    if canonical_role not in {"trail_mileage_k_anchor", "road_mileage_stone"}:
        canonical_role = "trail_mileage_k_anchor"
    evidence_type = (
        "road_mileage_stone"
        if canonical_role == "road_mileage_stone"
        else "trail_mileage_k_anchor"
    )
    return {
        "label_role": canonical_role,
        "evidence_type": evidence_type,
        "mileage_anchor_kind": canonical_role,
        "raw_mileage_text": match.group(0),
        "normalized_mileage_k": _format_mileage_k(mileage_k),
        "mileage_k": mileage_k,
        "mileage_m": round(mileage_k * 1000.0, 3),
    }


def _normalize_mileage_text(value: Any) -> str:
    return str(value or "").translate(FULLWIDTH_MILEAGE_TRANSLATION).strip()


def _format_mileage_k(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return f"{text}K"


def _sort_mileage_labels(values: set[str]) -> list[str]:
    return sorted(
        values,
        key=lambda value: (
            _float_or_none(str(value).replace("K", "")) is None,
            _float_or_none(str(value).replace("K", "")) or 0.0,
            str(value),
        ),
    )


def _looks_like_road_mileage_label(text: str) -> bool:
    return bool(ROAD_MILEAGE_HINT_PATTERN.search(text))


def _canonical_map_label_role(value: Any) -> str:
    key = str(value or "").strip()
    if not key:
        return ""
    return MAP_LABEL_ROLE_ALIASES.get(key, "")


def _map_label_role_from_raw(raw: dict[str, Any], label: str) -> str:
    for key in ("label_role", "role", "class", "label_class", "feature_role"):
        role = _canonical_map_label_role(raw.get(key))
        if role:
            return role
    text = _normalize_mileage_text(label)
    if "通訊點" in text or "通信點" in text:
        return "cellular_communication_point"
    if "等高線" in text or "contour" in text.lower():
        return "contour_elevation_label"
    if _looks_like_road_mileage_label(text) and MILEAGE_K_LABEL_PATTERN.search(text):
        return "road_mileage_stone"
    return ""


def _map_label_evidence_type(
    label_role: str,
    mileage: dict[str, Any] | None,
    fallback: str,
) -> str:
    if mileage:
        return str(mileage["evidence_type"])
    if label_role in {
        "cellular_communication_point",
        "contour_elevation_label",
        "trail_name_label",
        "named_place_label",
        "trail_annotation_label",
        "hazard_annotation_label",
    }:
        return label_role
    return fallback


def _map_label_evidence_families(
    label_role: str,
    mileage: dict[str, Any] | None,
) -> list[str]:
    families = ["map_label", "ocr"]
    if mileage:
        families.append("route_mileage")
        families.append("road_context" if mileage["label_role"] == "road_mileage_stone" else "trail_context")
    if label_role == "cellular_communication_point":
        families.extend(["communication", "readiness"])
    if label_role == "contour_elevation_label":
        families.extend(["terrain", "contour"])
    return sorted(set(families))


def _map_label_role_fields(label_role: str, label: str) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "map_label_kind": label_role or "map_label",
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    if label_role == "cellular_communication_point":
        fields["communication_networks"] = _communication_networks_from_text(label)
        fields["communication_emergency_hint"] = "112" in _normalize_mileage_text(label)
    elif label_role == "contour_elevation_label":
        fields["contour_elevation_m"] = _contour_elevation_from_text(label)
    return fields


def _communication_networks_from_text(label: str) -> list[str]:
    text = _normalize_mileage_text(label)
    networks = []
    for keyword in ("中華", "遠傳", "台哥大", "台灣大", "亞太", "台灣之星", "112"):
        if keyword in text:
            networks.append(keyword)
    return networks


def _contour_elevation_from_text(label: str) -> float | None:
    match = CONTOUR_ELEVATION_PATTERN.search(_normalize_mileage_text(label))
    return _float_or_none(match.group(1)) if match else None


def _mileage_anchor_point_fields(
    mileage: dict[str, Any],
    *,
    route_context_key: str,
    source_evidence_count: int,
    coordinate_source: str,
    review_reasons: list[str],
    raw_label_examples: list[str],
    supporting_candidate_ids: list[str],
) -> dict[str, Any]:
    return {
        "label_role": mileage["label_role"],
        "mileage_anchor_kind": mileage["mileage_anchor_kind"],
        "route_context_key": route_context_key,
        "raw_mileage_text": mileage["raw_mileage_text"],
        "normalized_mileage_k": mileage["normalized_mileage_k"],
        "mileage_k": mileage["mileage_k"],
        "mileage_m": mileage["mileage_m"],
        "route_mileage_m": mileage["mileage_m"],
        "source_evidence_count": source_evidence_count,
        "coordinate_source": coordinate_source,
        "review_required": bool(review_reasons),
        "review_reasons": review_reasons,
        "raw_label_examples": raw_label_examples,
        "supporting_candidate_ids": supporting_candidate_ids,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _representative_mileage_coordinate(
    item: dict[str, Any],
) -> tuple[float | None, float | None, str]:
    golden_coordinates = item.get("golden_coordinates") or []
    if golden_coordinates:
        lat, lon = golden_coordinates[0]
        return lat, lon, "golden_route_route_note_candidate"
    coordinates = item.get("coordinates") or []
    if not coordinates:
        return None, None, "missing_coordinate"
    lat_values = sorted(float(lat) for lat, _ in coordinates)
    lon_values = sorted(float(lon) for _, lon in coordinates)
    mid = len(coordinates) // 2
    if len(coordinates) % 2:
        return lat_values[mid], lon_values[mid], "route_note_candidate_median"
    return (
        (lat_values[mid - 1] + lat_values[mid]) / 2,
        (lon_values[mid - 1] + lon_values[mid]) / 2,
        "route_note_candidate_median",
    )


def _coordinate_spread_m(coordinates: list[tuple[float, float]]) -> float | None:
    if len(coordinates) < 2:
        return None
    max_distance = 0.0
    for index, first in enumerate(coordinates):
        for second in coordinates[index + 1 :]:
            max_distance = max(max_distance, _haversine_m(first, second))
    return round(max_distance, 2)


def _haversine_m(first: tuple[float, float], second: tuple[float, float]) -> float:
    lat1, lon1 = (math.radians(first[0]), math.radians(first[1]))
    lat2, lon2 = (math.radians(second[0]), math.radians(second[1]))
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1
    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return 6371000.0 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _mileage_review_reasons(
    mileage: dict[str, Any] | None,
    *,
    lat: float | None,
    lon: float | None,
    route_distance_m: float | None,
    coordinate_spread_m: float | None,
    source_evidence_count: int,
) -> list[str]:
    if not mileage:
        return []
    reasons = []
    if mileage.get("label_role") == "road_mileage_stone":
        reasons.append("road_mileage_stone_not_trail_k_anchor")
    if lat is None or lon is None:
        reasons.append("missing_coordinate")
    if source_evidence_count <= 1:
        reasons.append("single_source_evidence")
    if route_distance_m is not None and mileage["mileage_m"] > route_distance_m + 1000.0:
        reasons.append("exceeds_route_summary_distance")
    if coordinate_spread_m is not None and coordinate_spread_m > 300.0:
        reasons.append("coordinate_spread_over_300m")
    return reasons


def _mileage_anchor_confidence(source_evidence_count: int, review_reasons: list[str]) -> float:
    base = 0.55 + min(source_evidence_count, 8) * 0.04
    if "coordinate_spread_over_300m" in review_reasons:
        base -= 0.2
    if "missing_coordinate" in review_reasons:
        base -= 0.15
    if "exceeds_route_summary_distance" in review_reasons:
        base -= 0.1
    return round(max(0.2, min(0.9, base)), 2)


def _unique_texts(values: list[Any], *, limit: int) -> list[str]:
    results = []
    seen = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        results.append(text)
        if len(results) >= limit:
            break
    return results


def _route_summary_distance_m(root: Path, project: dict[str, Any]) -> float | None:
    ref = str(project.get("route_summary_ref") or SOURCE_DEFAULTS["route_summary"]["default_ref"])
    route_summary = _load_json_object(_project_path(root, ref))
    return _float_or_none(route_summary.get("distance_m"))


def _build_mileage_k_anchor_payload(
    *,
    project_id: str,
    generated_at: str,
    anchors: list[dict[str, Any]],
    route_context_points_ref: str,
    scan_summary: dict[str, Any],
    boundary: dict[str, Any],
) -> dict[str, Any]:
    sorted_anchors = sorted(
        anchors,
        key=lambda anchor: (
            _float_or_none(anchor.get("mileage_k")) or 0.0,
            str(anchor.get("route_context_key") or ""),
        ),
    )
    review_required_count = sum(1 for anchor in sorted_anchors if anchor.get("review_required"))
    raw_evidence_count = sum(
        int(anchor.get("source_evidence_count") or 0) for anchor in sorted_anchors
    )
    return {
        "artifact_kind": "pretrip_route_mileage_k_anchors",
        "schema_version": ROUTE_CONTEXT_SCHEMA_VERSION,
        "project_id": project_id,
        "generated_at": generated_at,
        "route_context_points_ref": route_context_points_ref,
        "anchor_count": len(sorted_anchors),
        "raw_evidence_count": raw_evidence_count,
        "review_required_count": review_required_count,
        "scan_summary": scan_summary,
        "normalized_mileage_k_values": [
            anchor.get("normalized_mileage_k") for anchor in sorted_anchors
        ],
        "anchors": [
            {
                "candidate_id": anchor.get("candidate_id"),
                "display_label": anchor.get("display_label"),
                "label_role": anchor.get("label_role"),
                "mileage_anchor_kind": anchor.get("mileage_anchor_kind"),
                "normalized_mileage_k": anchor.get("normalized_mileage_k"),
                "mileage_k": anchor.get("mileage_k"),
                "mileage_m": anchor.get("mileage_m"),
                "lat": anchor.get("lat"),
                "lon": anchor.get("lon"),
                "route_context_key": anchor.get("route_context_key"),
                "coordinate_source": anchor.get("coordinate_source"),
                "coordinate_spread_m": anchor.get("coordinate_spread_m"),
                "source_evidence_count": anchor.get("source_evidence_count"),
                "review_required": anchor.get("review_required"),
                "review_reasons": anchor.get("review_reasons") or [],
                "raw_label_examples": anchor.get("raw_label_examples") or [],
                "supporting_candidate_ids": anchor.get("supporting_candidate_ids") or [],
                "source_refs": anchor.get("source_refs") or [],
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
            for anchor in sorted_anchors
        ],
        "policy": {
            "included_evidence_type": "trail_mileage_k_anchor",
            "excluded_evidence_type": "road_mileage_stone",
            "duplicate_key": "route_context_key + normalized_mileage_k",
            "standalone_k_labels_are_review_candidates": True,
            "road_mileage_stones_are_not_trail_k_anchors": True,
            "out_of_route_distance_kept_with_review_reason": True,
            "raw_payloads_embedded": False,
        },
        "boundary": boundary,
    }


def _route_bbox(root: Path, project: dict[str, Any]) -> dict[str, float] | None:
    ref = str(project.get("route_summary_ref") or SOURCE_DEFAULTS["route_summary"]["default_ref"])
    route_summary = _load_json_object(_project_path(root, ref))
    bbox = route_summary.get("bbox_wgs84")
    if not isinstance(bbox, dict):
        return None
    try:
        return {
            "min_lat": float(bbox["min_lat"]),
            "min_lon": float(bbox["min_lon"]),
            "max_lat": float(bbox["max_lat"]),
            "max_lon": float(bbox["max_lon"]),
        }
    except (KeyError, TypeError, ValueError):
        return None


def _within_bbox(
    lat: float,
    lon: float,
    bbox: dict[str, float],
    *,
    padding_degrees: float,
) -> bool:
    return (
        bbox["min_lat"] - padding_degrees
        <= lat
        <= bbox["max_lat"] + padding_degrees
        and bbox["min_lon"] - padding_degrees
        <= lon
        <= bbox["max_lon"] + padding_degrees
    )


def _is_meaningful_route_note(label: str, category: str) -> bool:
    if not label:
        return False
    normalized = label.strip()
    if re.fullmatch(r"\d+(\.\d+)?\s*[Kk]", normalized):
        return False
    if re.fullmatch(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}.*", normalized):
        return False
    if normalized.lower().startswith("garmin_") or "birdseye demo" in normalized.lower():
        return False
    if category in {"landmark_hint", "camp_or_water_hint", "route_condition_hint", "hazard_hint"}:
        return True
    return _has_any(
        _normalize(normalized),
        (
            "山",
            "峰",
            "營地",
            "叉路",
            "溪",
            "橋",
            "崩",
            "保線",
            "水",
            "池",
            "啞口",
            "鞍",
            "林",
            "崖",
            "瀑",
            "吊橋",
        ),
    )


def _route_note_rank(label: str, category: str) -> tuple[int, int, str]:
    priority = {
        "hazard_hint": 0,
        "camp_or_water_hint": 1,
        "landmark_hint": 2,
        "route_condition_hint": 3,
    }.get(category, 4)
    return (priority, len(label), label)


def _route_keywords(
    *,
    project_id: str,
    route_keyword: str | None,
    route_summary: dict[str, Any],
) -> list[str]:
    candidates = [
        route_keyword,
        "chilai_nanhua_day1" if project_id == "chilai_nanhua_day1" else project_id,
        "奇萊-南華" if project_id == "chilai_nanhua_day1" else None,
        "奇萊南華" if project_id == "chilai_nanhua_day1" else None,
        "奇萊南峰 南華山" if project_id == "chilai_nanhua_day1" else None,
        "奇萊南峰南華山" if project_id == "chilai_nanhua_day1" else None,
        route_summary.get("route_name") if isinstance(route_summary, dict) else None,
    ]
    keywords: list[str] = []
    seen: set[str] = set()
    for value in candidates:
        text = str(value or "").strip()
        if not text or text in seen or not _is_thematic_route_keyword(text):
            continue
        seen.add(text)
        keywords.append(text)
    return keywords


def _is_thematic_route_keyword(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    if re.fullmatch(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}.*", text):
        return False
    if re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", text):
        return False
    if text in {"每日記錄", "daily record", "track", "route"}:
        return False
    if "每日記錄" in text and re.search(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", text):
        return False
    return True


def _build_crawl_seed_plan(
    *,
    project_id: str,
    generated_at: str,
    route_keywords: list[str],
    route_note_payload: dict[str, Any],
    route_note_ref: str,
    route_bbox: dict[str, float] | None,
    include_route_notes: bool,
    route_note_point_policy: str,
    limit: int,
    boundary: dict[str, Any],
) -> dict[str, Any]:
    seeds: list[dict[str, Any]] = []
    for index, keyword in enumerate(route_keywords, start=1):
        seeds.append(
            {
                "seed_id": f"route_keyword.{index:03d}",
                "seed_kind": "route_keyword",
                "query": keyword,
                "target_tiers": ["P0", "P1"],
                "expected_output": "web_case_evidence_or_official_source_record",
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )

    route_note_seeds = []
    if include_route_notes:
        route_note_seeds = _route_note_seed_records(
            route_note_payload,
            route_note_ref=route_note_ref,
            route_keywords=route_keywords,
            route_bbox=route_bbox,
            limit=limit,
        )
        seeds.extend(route_note_seeds)

    return {
        "artifact_kind": ROUTE_CONTEXT_CRAWL_SEED_PLAN_ARTIFACT_KIND,
        "schema_version": ROUTE_CONTEXT_SCHEMA_VERSION,
        "project_id": project_id,
        "generated_at": generated_at,
        "route_keywords": route_keywords,
        "source_tiers": _source_tier_catalog(),
        "route_note_seed_policy": {
            "route_notes_are_conclusion": False,
            "route_notes_are_seed_material": True,
            "route_note_point_policy": route_note_point_policy,
            "default_policy": DEFAULT_ROUTE_NOTE_POINT_POLICY,
            "required_before_briefing_conclusion": "P0/P1/P2 corroborating source evidence or human review",
        },
        "seed_count": len(seeds),
        "route_note_seed_count": len(route_note_seeds),
        "seeds": seeds,
        "boundary": boundary,
    }


def _route_note_seed_records(
    payload: dict[str, Any],
    *,
    route_note_ref: str,
    route_keywords: list[str],
    route_bbox: dict[str, float] | None,
    limit: int,
) -> list[dict[str, Any]]:
    candidates = payload.get("candidates") if isinstance(payload, dict) else []
    if not isinstance(candidates, list) or limit <= 0:
        return []
    primary_keyword = route_keywords[0] if route_keywords else ""
    ranked: list[tuple[tuple[int, int, str], dict[str, Any]]] = []
    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        label = _first_text(raw.get("normalized_note"), raw.get("name"), raw.get("candidate_id"))
        category = str(raw.get("note_category") or "")
        lat = _float_or_none(raw.get("lat"))
        lon = _float_or_none(raw.get("lon"))
        if not _is_meaningful_route_note(label, category):
            continue
        if route_bbox and lat is not None and lon is not None and not _within_bbox(
            lat,
            lon,
            route_bbox,
            padding_degrees=0.03,
        ):
            continue
        ranked.append((_route_note_rank(label, category), raw))
    ranked.sort(key=lambda item: item[0])

    seeds: list[dict[str, Any]] = []
    for index, (_, raw) in enumerate(ranked[:limit], start=1):
        label = _first_text(raw.get("normalized_note"), raw.get("name"), raw.get("candidate_id"))
        seeds.append(
            {
                "seed_id": f"route_note_seed.{index:03d}",
                "seed_kind": "route_note",
                "query": " ".join(part for part in (primary_keyword, label) if part),
                "label": label,
                "route_note_category": raw.get("note_category"),
                "source_candidate_id": raw.get("candidate_id"),
                "source_ref": route_note_ref,
                "target_tiers": ["P0", "P1"],
                "expected_output": "corroborating_article_or_official_record",
                "promote_to_route_context_point": False,
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )
    return seeds


def _dedupe_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[tuple[str, str, float | None, float | None], int] = {}
    deduped = []
    for point in points:
        key = _dedupe_key_for_point(point)
        if key in seen:
            existing = deduped[seen[key]]
            _merge_point_provenance(existing, point)
            continue
        seen[key] = len(deduped)
        deduped.append(point)
    return deduped


def _dedupe_key_for_point(
    point: dict[str, Any],
) -> tuple[str, str, float | None, float | None]:
    if point.get("evidence_type") in {"trail_mileage_k_anchor", "road_mileage_stone"}:
        return (
            str(point.get("evidence_type") or "mileage_label"),
            str(point.get("route_context_key") or "workspace_route"),
            _float_or_none(point.get("mileage_k")),
            None,
        )
    return (
        _normalize(point.get("label")),
        str(point.get("context_kind") or ""),
        _rounded_coord(point.get("lat")),
        _rounded_coord(point.get("lon")),
    )


def _merge_point_provenance(existing: dict[str, Any], incoming: dict[str, Any]) -> None:
    existing["sec6_layers"] = sorted(
        {*_str_list(existing.get("sec6_layers")), *_str_list(incoming.get("sec6_layers"))}
    )
    existing["evidence_families"] = sorted(
        {
            *_str_list(existing.get("evidence_families")),
            *_str_list(incoming.get("evidence_families")),
        }
    )
    evidence_types = {
        *_str_list(existing.get("merged_evidence_types")),
        str(existing.get("evidence_type") or ""),
        str(incoming.get("evidence_type") or ""),
    }
    existing["merged_evidence_types"] = sorted(item for item in evidence_types if item)
    existing["source_refs"] = _merge_source_refs(
        existing.get("source_refs"),
        incoming.get("source_refs"),
    )
    gaps = {
        *_str_list(existing.get("reference_gaps")),
        *_str_list(incoming.get("reference_gaps")),
    }
    if gaps:
        existing["reference_gaps"] = sorted(gaps)
    if existing.get("lat") is None and incoming.get("lat") is not None:
        existing["lat"] = incoming.get("lat")
    if existing.get("lon") is None and incoming.get("lon") is not None:
        existing["lon"] = incoming.get("lon")
    if existing.get("distance_m") is None and incoming.get("distance_m") is not None:
        existing["distance_m"] = incoming.get("distance_m")
    if existing.get("evidence_type") in {"trail_mileage_k_anchor", "road_mileage_stone"}:
        existing["source_evidence_count"] = int(existing.get("source_evidence_count") or 0) + int(
            incoming.get("source_evidence_count") or 0
        )
        existing["raw_label_examples"] = _unique_texts(
            [
                *_str_list(existing.get("raw_label_examples")),
                *_str_list(incoming.get("raw_label_examples")),
            ],
            limit=12,
        )
        existing["supporting_candidate_ids"] = _unique_texts(
            [
                *_str_list(existing.get("supporting_candidate_ids")),
                *_str_list(incoming.get("supporting_candidate_ids")),
            ],
            limit=36,
        )
        review_reasons = _unique_texts(
            [
                *_str_list(existing.get("review_reasons")),
                *_str_list(incoming.get("review_reasons")),
            ],
            limit=12,
        )
        if existing["source_evidence_count"] > 1:
            review_reasons = [
                reason for reason in review_reasons if reason != "single_source_evidence"
            ]
        existing["review_reasons"] = review_reasons
        existing["review_required"] = bool(review_reasons)
        existing["review_state"] = "needs_human_review" if review_reasons else "candidate"
    for key in (
        "mention_page_count",
        "mention_ratio",
        "source_families",
        "aliases",
    ):
        if key not in existing and incoming.get(key) is not None:
            existing[key] = incoming.get(key)


def _merge_source_refs(*values: Any) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, list):
            continue
        for ref in value:
            if not isinstance(ref, dict):
                continue
            key = json.dumps(ref, sort_keys=True, ensure_ascii=False)
            if key in seen:
                continue
            seen.add(key)
            refs.append(ref)
    return refs[:12]


def _counts(points: list[dict[str, Any]]) -> dict[str, Any]:
    by_layer: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    by_source: dict[str, int] = {}
    by_family: dict[str, int] = {}
    by_tier: dict[str, int] = {}
    by_sensitivity: dict[str, int] = {}
    by_stop_advisory: dict[str, int] = {}
    for point in points:
        for layer in point.get("sec6_layers", []):
            by_layer[str(layer)] = by_layer.get(str(layer), 0) + 1
        for family in point.get("evidence_families", []):
            by_family[str(family)] = by_family.get(str(family), 0) + 1
        by_kind[str(point.get("context_kind") or "unknown")] = by_kind.get(
            str(point.get("context_kind") or "unknown"),
            0,
        ) + 1
        by_source[str(point.get("evidence_type") or "unknown")] = by_source.get(
            str(point.get("evidence_type") or "unknown"),
            0,
        ) + 1
        by_tier[str(point.get("source_tier") or "unknown")] = by_tier.get(
            str(point.get("source_tier") or "unknown"),
            0,
        ) + 1
        by_sensitivity[str(point.get("sensitivity_level") or "unknown")] = (
            by_sensitivity.get(str(point.get("sensitivity_level") or "unknown"), 0)
            + 1
        )
        by_stop_advisory[str(point.get("stop_advisory_candidate") or "unknown")] = (
            by_stop_advisory.get(
                str(point.get("stop_advisory_candidate") or "unknown"),
                0,
            )
            + 1
        )
    return {
        "route_context_point_count": len(points),
        "by_sec6_layer": dict(sorted(by_layer.items())),
        "by_context_kind": dict(sorted(by_kind.items())),
        "by_evidence_type": dict(sorted(by_source.items())),
        "by_evidence_family": dict(sorted(by_family.items())),
        "by_source_tier": dict(sorted(by_tier.items())),
        "by_sensitivity_level": dict(sorted(by_sensitivity.items())),
        "by_stop_advisory_candidate": dict(sorted(by_stop_advisory.items())),
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _route_summary_for_pack(payload: dict[str, Any]) -> dict[str, Any]:
    bbox = payload.get("bbox_wgs84") if isinstance(payload.get("bbox_wgs84"), dict) else {}
    return {
        "route_name": payload.get("route_name"),
        "distance_m": _float_or_none(payload.get("distance_m")),
        "point_count": payload.get("point_count"),
        "started_at": payload.get("started_at"),
        "ended_at": payload.get("ended_at"),
        "elevation_min_m": _float_or_none(payload.get("elevation_min_m")),
        "elevation_max_m": _float_or_none(payload.get("elevation_max_m")),
        "bbox_wgs84": bbox,
        "raw_route_points_embedded": False,
    }


def _source_tier_catalog() -> list[dict[str, str]]:
    return [dict(source) for source in SOURCE_TIER_CATALOG]


def _source_strategy() -> dict[str, Any]:
    return {
        "P0": "Scout baseline sources. Use for official route, terrain, weather, hazard, rescue, biodiversity, and historical-map grounding.",
        "P1": "Expansion sources. Use for public named points, route stories, OSM/Overpass, community articles, and map labels.",
        "P2": "Scout-owned observations. Use as seeds and review feedback; do not promote to broad route context without corroboration.",
        "route_note_policy": "route notes are crawler seeds by default, not briefing conclusions",
        "briefing_conclusion_policy": "prefer P0/P1 crawler or official evidence; cite P2 only as Scout-owned observation or seed",
    }


def _build_briefing_html(
    *,
    project_id: str,
    generated_at: str,
    route_keywords: list[str],
    route_summary: dict[str, Any],
    points: list[dict[str, Any]],
    counts: dict[str, Any],
    source_manifest: dict[str, Any],
    crawl_seed_plan: dict[str, Any],
    media_manifest: dict[str, Any],
    boundary: dict[str, Any],
) -> str:
    route_label = _briefing_route_label(
        project_id=project_id,
        route_keywords=route_keywords,
        route_summary=route_summary,
    )
    title = f"Scout Route Context Briefing - {route_label}"
    route_distance_km = _route_distance_label(route_summary.get("distance_m"))
    point_count = counts.get("route_context_point_count") or len(points)
    source_summary = _briefing_source_summary(source_manifest)
    media_count = media_manifest.get("media_count") or 0
    representative_points = _representative_points(points)
    route_points = _route_ordered_points(points)
    stop_points = _observation_stop_points(points)
    risk_points = _risk_context_points(points)
    nav_points = _navigation_context_points(points)
    source_rows = _briefing_source_rows(source_manifest)
    source_trust_panel = _briefing_source_trust_panel(source_manifest, media_manifest)
    itinerary_options = _briefing_itinerary_options(route_distance_km, media_manifest)
    highlight_cards = _briefing_highlight_cards(representative_points[:8], media_manifest)
    layer_cards = _briefing_layer_cards(points, media_manifest)
    p2_cards = _briefing_p2_cards(source_manifest, media_manifest)
    route_steps = _briefing_route_steps(route_points[:10])
    stop_cards = _briefing_stop_cards(stop_points[:8], media_manifest)
    risk_cards = _briefing_risk_cards(risk_points[:6], nav_points[:6], media_manifest)
    schedule_cards = _briefing_schedule_cards(route_distance_km, media_manifest)
    seed_items = _briefing_seed_items(crawl_seed_plan)
    tier_items = _briefing_tier_items()
    source_health_panel = _briefing_source_health_panel(source_manifest, source_summary, boundary)
    source_tier_spine = _briefing_source_tier_spine(source_manifest)
    hero_image = _briefing_hero_image(media_manifest)
    hero_media = _briefing_hero_media(hero_image)
    visual_agenda = _briefing_visual_agenda(
        media_manifest=media_manifest,
        route_distance_km=route_distance_km,
        point_count=point_count,
    )
    media_band = _briefing_media_band(media_manifest)
    photo_essay = _briefing_photo_essay(media_manifest)
    visual_kit = _briefing_visual_kit(media_manifest)
    visual_readiness_panel = _briefing_visual_readiness_panel(media_manifest)
    visual_contact_sheet = _briefing_visual_contact_sheet(media_manifest)
    visual_story_arc = _briefing_visual_story_arc(media_manifest)
    visual_anchor_cards = _briefing_visual_anchor_cards(media_manifest)
    story_wall = _briefing_story_wall(points, media_manifest)
    map_atlas = _briefing_route_map_atlas(route_points[:12], route_summary, media_manifest, source_manifest)
    route_visual = _briefing_route_visual(route_points[:12], route_summary, media_manifest)
    chapter_see_route = _briefing_chapter_break(
        media_manifest=media_manifest,
        number="01",
        eyebrow="共同畫面",
        title="先看見這條路",
        body="用照片、距離與高度剖面先建立隊伍共同畫面；接著才討論路線細節與停留點。",
        bullets=[
            "照片不是裝飾，要能指向路線段落",
            "剖面圖只幫忙理解節奏，不取代導航",
            "先講整體，再拆檢查點",
        ],
        context_kinds=("route_overview", "viewpoint_context"),
        label_keywords=("能高越嶺道", "導覽圖", "高山景觀"),
    )
    chapter_context = _briefing_chapter_break(
        media_manifest=media_manifest,
        number="02",
        eyebrow="路線脈絡",
        title="再把路線讀成故事",
        body="歷史、文化、自然、地形、季節與 Scout 回顧，應該幫隊伍理解這條路，而不是堆成資料表。",
        bullets=[
            "每層脈絡都要能講給隊伍聽",
            "文化敏感點先標成待查證內容",
            "Scout 回顧先當線索，不直接變成結論",
        ],
        context_kinds=("resource_context", "natural_context"),
        label_keywords=("雲海保線所", "能高越嶺道", "雲海"),
    )
    chapter_field = _briefing_chapter_break(
        media_manifest=media_manifest,
        number="03",
        eyebrow="現地節奏",
        title="把停留變成有條件的決策",
        body="3 分鐘觀察點、風險提醒與行程版本要一起讀：能不能停，不是看景色，而是看當下條件。",
        bullets=[
            "每個短停都要有目的與離開條件",
            "風險點優先討論通過策略",
            "行程版本只交給領隊人工審查",
        ],
        context_kinds=("viewpoint_context", "resource_context"),
        label_keywords=("光被八表", "日出", "天池"),
    )
    chapter_sources = _briefing_chapter_break(
        media_manifest=media_manifest,
        number="04",
        eyebrow="查證邊界",
        title="最後才看資料能信到哪裡",
        body="來源追溯、缺口與資料新舊放在最後，但不可省略；Scout AI 必須揭露缺資料，不能把缺資料當安全。",
        bullets=[
            "簡報模式給隊伍看，資料模式給工作人員查",
            "行前資料不等於現地安全結論",
            "完整來源與收集線索保留可追溯",
        ],
        context_kinds=("route_overview", "visual_context"),
        label_keywords=("導覽圖", "能高越嶺道"),
    )
    generated_date = generated_at.split("T", 1)[0] if generated_at else ""
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_h(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #17202a;
      --muted: #64717f;
      --line: #d9e0e7;
      --panel: #ffffff;
      --page: #f4f6f5;
      --paper: #fffefa;
      --forest: #234f45;
      --forest-dark: #163d34;
      --moss: #6c7f42;
      --clay: #a35f3d;
      --sky: #4a7194;
      --gold: #b78a35;
      --ember: #e33d24;
      --ember-dark: #8f1f18;
      --signal: #ffb000;
      --night: #111820;
      --ice: #d7f3ff;
      --shadow: 0 18px 46px rgba(31, 42, 35, .12);
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{
      margin: 0;
      color: var(--ink);
      background:
        linear-gradient(90deg, rgba(35, 79, 69, .055) 1px, transparent 1px),
        linear-gradient(0deg, rgba(35, 79, 69, .045) 1px, transparent 1px),
        var(--page);
      background-size: 28px 28px;
      font-family: "Noto Sans TC", "PingFang TC", "Microsoft JhengHei", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.62;
    }}
    p {{ margin: 0; }}
    a {{ color: var(--sky); text-underline-offset: 3px; text-decoration-thickness: 2px; }}
    .wrap {{ width: min(1160px, calc(100% - 40px)); margin: 0 auto; }}
    .hero {{
      position: relative;
      min-height: min(620px, 72vh);
      display: flex;
      align-items: end;
      padding: 78px 0 64px;
      color: #fff;
      background:
        linear-gradient(110deg, rgba(26, 58, 50, .95), rgba(30, 55, 70, .76)),
        linear-gradient(180deg, #496b61, #263f3a);
      overflow: hidden;
    }}
    .hero::after {{
      content: "";
      position: absolute;
      inset: 0;
      background: linear-gradient(90deg, rgba(17, 43, 38, .92), rgba(17, 43, 38, .62), rgba(17, 43, 38, .2));
      pointer-events: none;
    }}
    .hero-photo {{
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      object-fit: cover;
      filter: saturate(1.05) contrast(1.02);
    }}
    .hero .wrap {{ position: relative; z-index: 1; }}
    .eyebrow, .kicker {{
      margin: 0 0 10px;
      color: var(--gold);
      font-size: 12px;
      font-weight: 800;
      letter-spacing: 0;
      text-transform: uppercase;
    }}
    .hero .eyebrow {{ color: #cbdcc5; }}
    h1 {{
      max-width: 920px;
      margin: 0 0 18px;
      font-family: "Noto Serif TC", "Songti TC", "PMingLiU", serif;
      font-size: 64px;
      line-height: 1.02;
      letter-spacing: 0;
    }}
    h2 {{
      margin: 0;
      font-family: "Noto Serif TC", "Songti TC", "PMingLiU", serif;
      font-size: 38px;
      line-height: 1.12;
      letter-spacing: 0;
    }}
    h3 {{ margin: 0 0 8px; font-size: 20px; line-height: 1.25; }}
    .hero-copy {{ max-width: 760px; margin: 0 0 24px; color: #f6ead8; font-size: 20px; }}
    .meta-row {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 18px; }}
    .pill {{
      display: inline-flex;
      align-items: center;
      min-height: 32px;
      padding: 6px 12px;
      border: 1px solid rgba(255, 255, 255, .28);
      border-radius: 999px;
      background: rgba(255, 255, 255, .12);
      font-size: 13px;
      font-weight: 700;
    }}
    nav {{
      position: sticky;
      top: 0;
      z-index: 10;
      border-bottom: 1px solid var(--line);
      background: rgba(255, 255, 255, .96);
      backdrop-filter: blur(12px);
    }}
    nav .wrap {{
      display: flex;
      gap: 8px;
      align-items: center;
      overflow-x: auto;
      padding-top: 10px;
      padding-bottom: 10px;
    }}
    nav a {{
      flex: 0 0 auto;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px 10px;
      color: var(--forest);
      background: var(--paper);
      font-size: 13px;
      font-weight: 800;
      text-decoration: none;
      white-space: nowrap;
    }}
    nav a[aria-current="true"] {{
      color: #fff;
      background: var(--forest);
      border-color: var(--forest);
      box-shadow: 0 7px 18px rgba(35, 79, 69, .16);
    }}
    .mode-briefing nav a.nav-detail {{
      display: none;
    }}
    .mode-data nav a.nav-detail {{
      display: inline-flex;
    }}
    .nav-progress {{
      flex: 0 0 auto;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      margin-left: auto;
      min-height: 40px;
      padding: 5px 10px;
      border: 1px solid #dbe6de;
      border-radius: 8px;
      color: #30463f;
      background: linear-gradient(180deg, #ffffff, #f4f8f5);
      box-shadow: 0 8px 18px rgba(31, 42, 35, .06);
      white-space: nowrap;
    }}
    .nav-progress span {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 900;
    }}
    .nav-progress b {{
      color: var(--forest-dark);
      font-size: 13px;
      line-height: 1;
    }}
    .nav-progress small {{
      color: var(--clay);
      font-size: 12px;
      font-weight: 900;
    }}
    .mode-data .nav-progress {{
      display: none;
    }}
    .presenter-controls {{
      flex: 0 0 auto;
      display: inline-flex;
      gap: 4px;
      align-items: center;
      padding: 3px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #f7f5ee;
    }}
    .mode-data .presenter-controls {{
      display: none;
    }}
    .presenter-button {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 34px;
      height: 34px;
      border: 0;
      border-radius: 6px;
      color: var(--forest);
      background: transparent;
      cursor: pointer;
    }}
    .presenter-icon {{
      display: block;
      width: 10px;
      height: 10px;
      border-top: 2px solid currentColor;
      border-right: 2px solid currentColor;
    }}
    .presenter-icon.prev {{
      transform: translateX(2px) rotate(-135deg);
    }}
    .presenter-icon.next {{
      transform: translateX(-2px) rotate(45deg);
    }}
    .presenter-button:hover,
    .presenter-button:focus-visible {{
      color: #fff;
      background: var(--forest);
      outline: none;
    }}
    .presenter-button:disabled {{
      color: #9fa9a4;
      background: transparent;
      cursor: default;
      opacity: .58;
    }}
    .mobile-presenter-dock {{
      display: none;
    }}
    .mode-switch {{
      flex: 0 0 auto;
      display: inline-flex;
      gap: 4px;
      margin-left: 0;
      padding: 3px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #f7f5ee;
    }}
    .mode-button {{
      min-height: 34px;
      border: 0;
      border-radius: 6px;
      padding: 6px 10px;
      color: var(--forest);
      background: transparent;
      font: inherit;
      font-size: 13px;
      font-weight: 900;
      cursor: pointer;
      white-space: nowrap;
    }}
    .mode-button[aria-pressed="true"] {{
      color: #fff;
      background: var(--forest);
    }}
    main {{ padding: 28px 0 56px; }}
    .visual-agenda {{
      display: grid;
      grid-template-columns: minmax(240px, .52fr) minmax(0, 1fr);
      gap: 16px;
      align-items: stretch;
      margin: 0 0 30px;
      padding: 18px;
      border: 1px solid #d8e5da;
      border-radius: 8px;
      background: linear-gradient(135deg, #f9fbf5, #fffefa);
      box-shadow: 0 16px 36px rgba(31, 42, 35, .09);
    }}
    .visual-agenda-copy {{
      display: grid;
      gap: 10px;
      align-content: center;
      padding: 8px;
    }}
    .visual-agenda-copy h2 {{
      font-size: 34px;
    }}
    .visual-agenda-copy p {{
      color: #344842;
      font-size: 16px;
      font-weight: 750;
      line-height: 1.52;
    }}
    .visual-agenda-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
    }}
    .visual-agenda-card {{
      position: relative;
      min-height: 252px;
      overflow: hidden;
      border-radius: 8px;
      color: #fff;
      background: #183a32;
      border: 1px solid #cedbd3;
      text-decoration: none;
      box-shadow: 0 14px 28px rgba(31, 42, 35, .1);
    }}
    .visual-agenda-card:hover,
    .visual-agenda-card:focus-visible {{
      outline: 3px solid rgba(74, 113, 148, .32);
      outline-offset: 2px;
    }}
    .visual-agenda-card img {{
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      object-fit: cover;
      filter: saturate(1.04) contrast(1.04);
      transition: transform .24s ease;
    }}
    .visual-agenda-card:hover img,
    .visual-agenda-card:focus-visible img {{
      transform: scale(1.035);
    }}
    .visual-agenda-card::after {{
      content: "";
      position: absolute;
      inset: 0;
      background:
        linear-gradient(180deg, rgba(16, 40, 35, .03), rgba(16, 40, 35, .86)),
        linear-gradient(90deg, rgba(16, 40, 35, .4), rgba(16, 40, 35, .08));
    }}
    .visual-agenda-body {{
      position: absolute;
      z-index: 1;
      left: 12px;
      right: 12px;
      bottom: 12px;
      display: grid;
      gap: 7px;
    }}
    .visual-agenda-step {{
      display: inline-flex;
      width: fit-content;
      min-height: 25px;
      align-items: center;
      padding: 4px 8px;
      border-radius: 999px;
      color: #223d35;
      background: #f5e6b2;
      font-size: 12px;
      font-weight: 950;
    }}
    .visual-agenda-card b {{
      color: #fff;
      font-size: 22px;
      line-height: 1.08;
    }}
    .visual-agenda-card span:not(.visual-agenda-step) {{
      color: #fff2dc;
      font-size: 13px;
      font-weight: 850;
      line-height: 1.38;
    }}
    .slide {{
      display: grid;
      align-content: center;
      min-width: 0;
      min-height: min(680px, calc(100vh - 120px));
      scroll-margin-top: 72px;
      margin: 0 0 30px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(255, 254, 250, .97);
      box-shadow: var(--shadow);
      overflow: hidden;
    }}
    .chapter-break {{
      position: relative;
      min-height: min(560px, calc(100vh - 120px));
      color: #fff;
      background: var(--forest-dark);
    }}
    .chapter-break::after {{
      content: "";
      position: absolute;
      inset: 0;
      background:
        linear-gradient(90deg, rgba(16, 40, 35, .94), rgba(16, 40, 35, .64), rgba(16, 40, 35, .22)),
        linear-gradient(180deg, rgba(16, 40, 35, .2), rgba(16, 40, 35, .72));
      pointer-events: none;
    }}
    .chapter-photo {{
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      object-fit: cover;
      filter: saturate(1.05) contrast(1.04);
    }}
    .chapter-inner {{
      position: relative;
      z-index: 1;
      display: grid;
      grid-template-columns: minmax(0, .75fr) minmax(320px, .55fr);
      gap: 28px;
      align-items: end;
      width: 100%;
      padding: 52px;
    }}
    .chapter-number {{
      display: inline-flex;
      width: fit-content;
      margin-bottom: 18px;
      padding: 7px 11px;
      border: 1px solid rgba(255, 255, 255, .32);
      border-radius: 999px;
      color: #f5e6b2;
      background: rgba(255, 255, 255, .12);
      font-size: 13px;
      font-weight: 900;
    }}
    .chapter-break h2 {{
      max-width: 720px;
      color: #fff;
      font-size: 52px;
    }}
    .chapter-break .kicker {{ color: #f5e6b2; }}
    .chapter-copy {{
      max-width: 760px;
      margin-top: 18px;
      color: #fff4dc;
      font-size: 20px;
    }}
    .chapter-rhythm {{
      display: grid;
      gap: 10px;
      padding: 18px;
      border-radius: 8px;
      background: rgba(255, 255, 255, .12);
      border: 1px solid rgba(255, 255, 255, .24);
      backdrop-filter: blur(10px);
    }}
    .chapter-rhythm b {{
      color: #f5e6b2;
      font-size: 15px;
    }}
    .chapter-rhythm span {{
      display: block;
      color: #fff;
      font-weight: 800;
    }}
    .chapter-stage {{
      display: grid;
      gap: 16px;
      align-content: end;
    }}
    .chapter-visual-card {{
      display: grid;
      gap: 12px;
      padding: 12px;
      border: 1px solid rgba(255, 255, 255, .28);
      border-radius: 8px;
      background: rgba(12, 34, 29, .5);
      box-shadow: 0 22px 44px rgba(7, 22, 18, .25);
      backdrop-filter: blur(12px);
    }}
    .chapter-visual-card.no-photo {{
      padding: 18px;
      background: rgba(255, 255, 255, .12);
    }}
    .chapter-visual-photo {{
      position: relative;
      min-height: 246px;
      margin: 0;
      overflow: hidden;
      border-radius: 8px;
      background: rgba(255, 255, 255, .08);
    }}
    .chapter-visual-photo img {{
      display: block;
      width: 100%;
      height: 100%;
      min-height: 246px;
      object-fit: cover;
      filter: saturate(1.06) contrast(1.03);
    }}
    .chapter-visual-photo::after {{
      content: "";
      position: absolute;
      inset: 0;
      background: linear-gradient(180deg, rgba(11, 31, 27, .02), rgba(11, 31, 27, .82));
    }}
    .chapter-visual-photo figcaption {{
      position: absolute;
      z-index: 1;
      left: 12px;
      right: 12px;
      bottom: 12px;
      display: grid;
      gap: 7px;
      color: #fff;
    }}
    .chapter-visual-label {{
      display: inline-flex;
      width: fit-content;
      min-height: 26px;
      align-items: center;
      padding: 4px 8px;
      border-radius: 999px;
      color: #223d35;
      background: #f5e6b2;
      font-size: 12px;
      font-weight: 950;
    }}
    .chapter-visual-title {{
      color: #fff;
      font-size: 22px;
      font-weight: 950;
      line-height: 1.12;
      text-wrap: balance;
    }}
    .chapter-cue-tags {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }}
    .chapter-cue-tags span {{
      display: inline-flex;
      min-height: 26px;
      align-items: center;
      padding: 4px 8px;
      border-radius: 999px;
      color: #fff8e8;
      background: rgba(255, 255, 255, .13);
      border: 1px solid rgba(255, 255, 255, .2);
      font-size: 12px;
      font-weight: 850;
    }}
    .slide-inner {{ min-width: 0; padding: 42px; }}
    .slide-head {{
      display: flex;
      align-items: start;
      justify-content: space-between;
      gap: 18px;
      margin-bottom: 24px;
    }}
    .stamp {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 88px;
      padding: 10px;
      border-radius: 8px;
      color: #fff;
      background: var(--forest);
      font-weight: 900;
      text-align: center;
    }}
    .lead {{ max-width: 860px; margin: 0 0 22px; color: #31433e; font-size: 18px; }}
    .grid, .decision-grid, .layers, .source-grid, .route-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
      gap: 14px;
    }}
    .briefing-deck {{
      display: flex;
      gap: 16px;
      width: 100%;
      max-width: 100%;
      min-width: 0;
      overflow-x: auto;
      overscroll-behavior-inline: contain;
      scroll-snap-type: x mandatory;
      padding: 6px 2px 16px;
      scrollbar-color: rgba(35, 79, 69, .55) transparent;
    }}
    .briefing-deck > article {{
      flex: 0 0 min(390px, calc(100vw - 80px));
      scroll-snap-align: start;
    }}
    .briefing-deck.layers {{
      display: flex;
      grid-template-columns: none;
    }}
    .deck-hint {{
      margin: -8px 0 14px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 800;
    }}
    .itinerary-board {{
      display: grid;
      grid-template-columns: minmax(320px, .9fr) minmax(0, 1.1fr);
      gap: 18px;
      margin: 20px 0;
      padding: 18px;
      align-items: start;
      border-radius: 8px;
      background: linear-gradient(135deg, #f7faef, #ffffff);
      border: 1px solid #dbe7c7;
      box-shadow: inset 0 0 0 1px rgba(255, 255, 255, .6);
    }}
    .itinerary-lead {{
      display: grid;
      gap: 0;
      overflow: hidden;
      min-height: 100%;
      border-radius: 8px;
      color: #fff;
      background: linear-gradient(150deg, #204b41, #5f7142);
    }}
    .itinerary-visual {{
      position: relative;
      margin: 0;
      overflow: hidden;
      aspect-ratio: 16 / 9;
      background: #183a32;
    }}
    .itinerary-visual img {{
      display: block;
      width: 100%;
      height: 100%;
      object-fit: cover;
    }}
    .itinerary-visual figcaption {{
      position: absolute;
      left: 10px;
      right: 10px;
      bottom: 10px;
      padding: 7px 9px;
      border-radius: 8px;
      color: #fff;
      background: rgba(18, 39, 34, .84);
      font-size: 12px;
      font-weight: 850;
      line-height: 1.35;
    }}
    .itinerary-lead-body {{
      display: grid;
      gap: 16px;
      padding: 18px;
    }}
    .itinerary-lead strong {{ display: block; font-size: 46px; line-height: .95; }}
    .itinerary-lead span {{ color: #f5e6b2; font-weight: 900; }}
    .itinerary-lens {{
      display: grid;
      gap: 8px;
    }}
    .itinerary-lens span {{
      display: block;
      padding: 10px 12px;
      border-radius: 8px;
      color: #fff;
      background: rgba(255, 255, 255, .12);
      border: 1px solid rgba(255, 255, 255, .18);
      font-size: 13px;
      line-height: 1.45;
    }}
    .itinerary-options {{
      display: grid;
      gap: 12px;
    }}
    .itinerary-option-card {{
      display: grid;
      grid-template-columns: 86px 1fr;
      gap: 12px;
      align-items: start;
      padding: 14px;
      border-radius: 8px;
      border: 1px solid #dfe7d8;
      background: rgba(255, 255, 255, .78);
    }}
    .itinerary-option-card.primary {{
      border-color: #b7c99a;
      background: #f6faef;
      box-shadow: inset 4px 0 0 #5f7142;
    }}
    .itinerary-option-card.compressed {{
      border-color: #ecd2ae;
      background: #fff8ea;
    }}
    .itinerary-option-card b {{ display: block; color: var(--forest); font-size: 21px; }}
    .itinerary-option-card p {{ margin: 5px 0 0; color: #344842; }}
    .itinerary-decision-cue {{
      color: var(--clay);
      font-size: 13px;
      font-weight: 900;
    }}
    .day-pill {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 44px;
      border-radius: 999px;
      background: #e8efdc;
      color: var(--forest);
      font-weight: 900;
      text-align: center;
    }}
    .card, .point, .decision, .layer, .day-card {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      padding: 16px;
    }}
    .layer-brief {{
      display: grid;
      gap: 12px;
      align-content: start;
    }}
    .layer-brief h3 {{
      margin-bottom: 0;
      font-size: 24px;
      line-height: 1.18;
    }}
    .layer-definition {{
      margin: 0;
      color: var(--muted);
      line-height: 1.55;
    }}
    .field-media {{
      margin: -2px -2px 2px;
      min-height: 150px;
      border-radius: 8px;
      overflow: hidden;
      background: #e7efe8;
      border: 1px solid #e4ebe7;
    }}
    .field-media img {{
      display: block;
      width: 100%;
      height: 180px;
      object-fit: cover;
    }}
    .field-media figcaption {{
      padding: 8px 10px;
      color: var(--muted);
      background: #fff;
      font-size: 12px;
      line-height: 1.35;
    }}
    .source-chips {{
      display: flex;
      flex-wrap: wrap;
      gap: 5px;
      margin-top: 8px;
    }}
    .source-badge {{
      display: inline-flex;
      align-items: center;
      min-height: 22px;
      padding: 3px 7px;
      border-radius: 999px;
      color: #344842;
      background: #eef3ef;
      border: 1px solid #dae5dc;
      font-size: 11px;
      font-weight: 900;
      line-height: 1;
      white-space: nowrap;
    }}
    .source-badge.tier-p0 {{ color: #fff; background: var(--forest); border-color: var(--forest); }}
    .source-badge.tier-p1 {{ color: #fff; background: var(--sky); border-color: var(--sky); }}
    .source-badge.tier-p2 {{ color: #fff; background: var(--gold); border-color: var(--gold); }}
    .source-badge.boundary {{ color: #5f4321; background: #fff4df; border-color: #ead4aa; }}
    .source-badge.review {{ color: #633c2a; background: #fff0e7; border-color: #e8c9b7; }}
    .mode-briefing .source-badge.boundary,
    .mode-briefing .source-badge.review {{
      display: none;
    }}
    .mode-briefing .source-chips {{
      display: none;
    }}
    .layer-count {{
      display: inline-flex;
      width: fit-content;
      padding: 4px 8px;
      border-radius: 999px;
      color: var(--forest-dark);
      background: #e8efdc;
      font-size: 12px;
      font-weight: 900;
    }}
    .decision.primary {{ border-color: #90a86a; background: #f6faef; }}
    .muted, small, .footnote, .boundary {{ color: var(--muted); }}
    .boundary-note {{
      margin-top: 16px;
      padding: 14px 16px;
      border-radius: 8px;
      background: #eef5ef;
      border: 1px solid #d5e3d7;
      color: #31433e;
      font-weight: 700;
    }}
    .audit-details {{
      margin-top: 10px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 600;
    }}
    .audit-details code {{ display: block; margin-top: 8px; white-space: normal; overflow-wrap: anywhere; }}
    body.mode-briefing .source-debug-slide,
    body.mode-briefing .audit-details,
    body.mode-briefing .source-details {{
      display: none;
    }}
    body.mode-data .source-debug-slide {{
      display: grid;
    }}
    .mode-note {{
      margin-top: 14px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 700;
    }}
    .alert {{
      margin-top: 16px;
      padding: 12px 14px;
      border-left: 4px solid var(--gold);
      background: #fff9eb;
      font-weight: 700;
    }}
    .stat-strip {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 10px;
      margin: 16px 0;
    }}
    .stat {{ border: 1px solid var(--line); border-radius: 8px; padding: 12px; }}
    .stat b {{ display: block; color: var(--forest); font-size: 24px; }}
    .source-health-board {{
      display: grid;
      grid-template-columns: minmax(300px, .85fr) minmax(0, 1.15fr);
      gap: 16px;
      margin-top: 18px;
    }}
    .source-health-summary {{
      display: grid;
      gap: 14px;
      align-content: start;
      padding: 18px;
      border-radius: 8px;
      color: #fff;
      background: linear-gradient(145deg, #214d43, #4a7194);
    }}
    .source-health-summary h3 {{
      margin: 0;
      color: #fff;
      font-size: 30px;
      line-height: 1.12;
    }}
    .source-health-summary p {{
      margin: 0;
      color: rgba(255, 255, 255, .88);
      line-height: 1.5;
    }}
    .source-health-score {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
    }}
    .source-health-score span {{
      min-height: 74px;
      padding: 10px;
      border-radius: 8px;
      background: rgba(255, 255, 255, .12);
      border: 1px solid rgba(255, 255, 255, .2);
      font-size: 12px;
      font-weight: 850;
      line-height: 1.35;
    }}
    .source-health-score b {{
      display: block;
      margin-bottom: 4px;
      color: #f5e6b2;
      font-size: 25px;
      line-height: 1;
    }}
    .source-health-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }}
    .source-health-card {{
      display: grid;
      gap: 8px;
      align-content: start;
      padding: 14px;
      border-radius: 8px;
      background: #fff;
      border: 1px solid #dfe7df;
    }}
    .source-health-card.warning {{
      border-color: #e6cfa7;
      background: #fff8ea;
    }}
    .source-health-card.locked {{
      border-color: #d5e3d7;
      background: #f3f8f3;
    }}
    .source-health-card h3 {{
      margin: 0;
      color: var(--forest-dark);
      font-size: 19px;
      line-height: 1.2;
    }}
    .source-health-card p {{
      margin: 0;
      color: #344842;
      line-height: 1.48;
    }}
    .source-health-card small {{
      color: var(--muted);
      font-weight: 800;
      line-height: 1.35;
    }}
    .health-pill-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }}
    .health-pill {{
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      padding: 4px 8px;
      border-radius: 999px;
      color: var(--forest-dark);
      background: #eef5ef;
      border: 1px solid #d8e5da;
      font-size: 12px;
      font-weight: 900;
      line-height: 1;
    }}
    .health-pill.warning {{
      color: #664823;
      background: #fff3dd;
      border-color: #e2c28d;
    }}
    .source-health-details {{
      color: var(--muted);
      font-size: 13px;
      font-weight: 700;
    }}
    .source-health-details code {{
      display: block;
      margin-top: 8px;
      white-space: normal;
      overflow-wrap: anywhere;
    }}
    .image-band {{
      display: grid;
      grid-template-columns: minmax(340px, .92fr) minmax(0, 1.08fr);
      gap: 18px;
      align-items: stretch;
    }}
    .status-photo-feature {{
      display: grid;
      align-self: start;
      grid-template-rows: auto auto;
      min-height: 0;
    }}
    .status-photo-feature img {{
      height: clamp(300px, 36vw, 520px);
      min-height: 0;
      max-height: none;
    }}
    .status-photo-strip {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-top: 14px;
    }}
    .status-photo-strip .photo {{
      min-height: 158px;
    }}
    .status-photo-strip .photo img {{
      min-height: 158px;
      max-height: 172px;
    }}
    .status-cues {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      margin-top: 14px;
    }}
    .status-cue {{
      padding: 12px;
      border-radius: 8px;
      color: #344842;
      background: #fff;
      border: 1px solid #e2e9e4;
      font-size: 13px;
      font-weight: 800;
      line-height: 1.45;
    }}
    .status-cue b {{
      display: block;
      margin-bottom: 5px;
      color: var(--forest-dark);
      font-size: 14px;
    }}
    .photo-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 10px;
    }}
    .highlight-wall {{
      display: grid;
      grid-template-columns: 1.2fr .8fr;
      gap: 16px;
      align-items: stretch;
    }}
    .highlight-card {{
      display: grid;
      grid-template-columns: minmax(160px, .85fr) minmax(0, 1fr);
      min-height: 190px;
      overflow: hidden;
      border-radius: 8px;
      background: #fff;
      border: 1px solid var(--line);
    }}
    .highlight-card:first-child {{ grid-row: span 2; grid-template-columns: 1fr; }}
    .highlight-card img {{
      width: 100%;
      height: 100%;
      min-height: 190px;
      object-fit: cover;
      background: #e7efe8;
    }}
    .highlight-body {{ padding: 16px; }}
    .highlight-body p {{ margin: 6px 0; }}
    .highlight-meta {{ color: var(--muted); font-size: 13px; }}
    .highlight-guide-cue {{
      color: #31433e;
      font-weight: 800;
      line-height: 1.48;
    }}
    .highlight-question {{
      margin-top: 10px;
      padding: 10px 12px;
      border-radius: 8px;
      color: var(--forest-dark);
      background: #eef5ef;
      border: 1px solid #d8e5da;
      font-size: 13px;
      font-weight: 900;
      line-height: 1.42;
    }}
    .highlight-data-details {{
      margin-top: 10px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 700;
    }}
    .highlight-data-details code {{
      display: block;
      margin-top: 8px;
      white-space: normal;
      overflow-wrap: anywhere;
    }}
    .mode-briefing .highlight-data-details {{
      display: none;
    }}
    .photo {{
      margin: 0;
      min-height: 180px;
      border-radius: 8px;
      overflow: hidden;
      background: #e9efeb;
      border: 1px solid var(--line);
    }}
    .photo img {{
      display: block;
      width: 100%;
      height: 100%;
      min-height: 180px;
      object-fit: cover;
    }}
    .photo figcaption {{
      padding: 8px 10px;
      color: var(--muted);
      background: #fff;
      font-size: 12px;
    }}
    .photo.status-photo-feature img {{
      height: clamp(300px, 36vw, 520px);
      min-height: 0;
      max-height: none;
    }}
    .media-panel {{
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      padding: 18px;
      border-radius: 8px;
      background: #f7f5ee;
      border: 1px solid #e6dcc7;
    }}
    .media-gap {{
      padding: 16px;
      border: 1px dashed #c9b98d;
      border-radius: 8px;
      background: #fff9eb;
    }}
    .visual-readiness {{
      display: grid;
      grid-template-columns: minmax(0, .72fr) minmax(260px, .48fr);
      gap: 16px;
      align-items: stretch;
      margin: 0 0 18px;
      padding: 16px;
      border-radius: 8px;
      background: #f8f6ef;
      border: 1px solid #e2d7bd;
    }}
    .visual-readiness.good {{
      background: #f2f7ef;
      border-color: #d5e4cf;
    }}
    .visual-readiness.warning {{
      background: #fff8ea;
      border-color: #ead7a8;
    }}
    .visual-readiness.blocked {{
      background: #fff4ef;
      border-color: #e7c5b7;
    }}
    .visual-readiness h3 {{
      margin: 4px 0 8px;
      color: var(--ink);
      font-size: 24px;
      line-height: 1.14;
    }}
    .visual-readiness p {{
      margin: 0;
      color: #41544f;
      font-weight: 700;
      line-height: 1.55;
    }}
    .visual-readiness-meter {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }}
    .visual-readiness-metric {{
      display: grid;
      gap: 4px;
      padding: 12px;
      border-radius: 8px;
      background: rgba(255, 255, 255, .72);
      border: 1px solid rgba(30, 74, 65, .12);
    }}
    .visual-readiness-metric span {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 900;
    }}
    .visual-readiness-metric b {{
      color: var(--forest);
      font-size: 23px;
      line-height: 1;
    }}
    .visual-readiness-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 12px;
    }}
    .visual-readiness-actions span {{
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      padding: 5px 9px;
      border-radius: 999px;
      background: #fff;
      border: 1px solid #e1d6bc;
      color: #4b5148;
      font-size: 12px;
      font-weight: 900;
    }}
    .photo-essay {{
      display: grid;
      grid-template-columns: minmax(360px, .98fr) minmax(0, 1.02fr);
      gap: 18px;
      align-items: stretch;
    }}
    .photo-essay-feature {{
      position: relative;
      height: 100%;
      min-height: 500px;
      margin: 0;
      overflow: hidden;
      border-radius: 8px;
      color: #fff;
      background: #173b35;
      border: 1px solid #cfd9d3;
    }}
    .photo-essay-feature img {{
      display: block;
      width: 100%;
      height: 100%;
      min-height: 500px;
      object-fit: cover;
    }}
    .photo-essay-feature::after {{
      content: "";
      position: absolute;
      inset: 0;
      background: linear-gradient(180deg, rgba(14, 33, 29, .08), rgba(14, 33, 29, .82));
    }}
    .photo-essay-feature figcaption {{
      position: absolute;
      z-index: 1;
      left: 18px;
      right: 18px;
      bottom: 18px;
      display: grid;
      gap: 8px;
    }}
    .photo-essay-feature b {{
      max-width: 660px;
      color: #fff;
      font-family: "Noto Serif TC", "Songti TC", "PMingLiU", serif;
      font-size: clamp(30px, 4vw, 54px);
      line-height: 1.02;
    }}
    .photo-essay-feature span {{
      max-width: 560px;
      color: #fff4dc;
      font-size: 16px;
      font-weight: 850;
      line-height: 1.45;
    }}
    .photo-essay-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      align-content: stretch;
    }}
    .photo-essay-card {{
      position: relative;
      height: 210px;
      min-height: 210px;
      overflow: hidden;
      border-radius: 8px;
      background: #eef3ef;
      border: 1px solid #dce6df;
    }}
    .photo-essay-card img {{
      display: block;
      width: 100%;
      height: 100%;
      min-height: 210px;
      object-fit: cover;
    }}
    .photo-essay-card::after {{
      content: "";
      position: absolute;
      inset: 0;
      background: linear-gradient(180deg, rgba(17, 43, 38, .02), rgba(17, 43, 38, .76));
    }}
    .photo-essay-card.map-card {{
      grid-column: 1 / -1;
      height: 170px;
      min-height: 170px;
    }}
    .photo-essay-card.map-card img {{
      min-height: 170px;
    }}
    .photo-essay-caption {{
      position: absolute;
      z-index: 1;
      left: 12px;
      right: 12px;
      bottom: 12px;
      display: grid;
      gap: 5px;
      color: #fff;
    }}
    .photo-essay-caption b {{
      color: #fff;
      font-size: 18px;
      line-height: 1.16;
    }}
    .photo-essay-caption span {{
      color: #f6ead8;
      font-size: 12px;
      font-weight: 850;
      line-height: 1.38;
    }}
    .visual-contact-sheet {{
      display: grid;
      grid-template-columns: minmax(230px, .34fr) minmax(0, 1fr);
      gap: 14px;
      align-items: stretch;
      margin-top: 18px;
      padding: 16px;
      border: 1px solid #d8e5da;
      border-radius: 8px;
      background: linear-gradient(180deg, #f7fbf8, #fffefa);
    }}
    .visual-contact-copy {{
      display: grid;
      gap: 10px;
      align-content: start;
      padding: 2px;
    }}
    .visual-contact-copy h3 {{
      margin: 0;
      color: var(--forest-dark);
      font-size: 24px;
      line-height: 1.16;
    }}
    .visual-contact-copy p {{
      color: #425650;
      font-weight: 750;
      line-height: 1.52;
    }}
    .visual-shot-list {{
      display: grid;
      gap: 8px;
      margin-top: 4px;
    }}
    .visual-shot-list span {{
      display: block;
      padding: 9px 10px;
      border-radius: 8px;
      color: #31433e;
      background: #fff;
      border: 1px solid #dfe8df;
      font-size: 13px;
      font-weight: 850;
      line-height: 1.38;
    }}
    .visual-contact-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 8px;
      align-content: start;
    }}
    .visual-contact-card {{
      position: relative;
      margin: 0;
      min-height: 132px;
      aspect-ratio: 4 / 3;
      overflow: hidden;
      border-radius: 8px;
      background: #e8efeb;
      border: 1px solid #d4dfd7;
    }}
    .visual-contact-card img {{
      display: block;
      width: 100%;
      height: 100%;
      object-fit: cover;
      filter: saturate(1.03) contrast(1.02);
    }}
    .visual-contact-card::after {{
      content: "";
      position: absolute;
      inset: 0;
      background: linear-gradient(180deg, rgba(14, 33, 29, .02), rgba(14, 33, 29, .7));
    }}
    .visual-contact-card figcaption {{
      position: absolute;
      z-index: 1;
      left: 9px;
      right: 9px;
      bottom: 9px;
      display: grid;
      gap: 4px;
      color: #fff;
      font-size: 12px;
      font-weight: 850;
      line-height: 1.25;
    }}
    .visual-contact-index {{
      display: inline-flex;
      width: fit-content;
      min-height: 22px;
      align-items: center;
      padding: 3px 7px;
      border-radius: 999px;
      color: #1d4038;
      background: #f5e6b2;
      font-size: 11px;
      font-weight: 950;
      line-height: 1;
    }}
    .visual-kit-board {{
      display: grid;
      gap: 16px;
    }}
    .visual-kit-summary {{
      display: grid;
      grid-template-columns: minmax(0, .84fr) minmax(220px, .36fr);
      gap: 16px;
      align-items: stretch;
      padding: 18px;
      border-radius: 8px;
      color: #fff;
      background: linear-gradient(135deg, #183d35, #4f6846);
    }}
    .visual-kit-summary h3 {{
      max-width: 780px;
      margin: 0;
      color: #fff;
      font-family: "Noto Serif TC", "Songti TC", "PMingLiU", serif;
      font-size: clamp(30px, 3.5vw, 50px);
      line-height: 1.05;
    }}
    .visual-kit-summary p {{
      margin-top: 10px;
      color: #fff2dc;
      font-size: 16px;
      font-weight: 800;
      line-height: 1.48;
    }}
    .visual-kit-score {{
      display: grid;
      place-items: center;
      padding: 14px;
      border-radius: 8px;
      background: rgba(255, 255, 255, .13);
      border: 1px solid rgba(255, 255, 255, .22);
      text-align: center;
    }}
    .visual-kit-score b {{
      color: #f5e6b2;
      font-size: 42px;
      line-height: 1;
    }}
    .visual-kit-score span {{
      color: #fff;
      font-size: 13px;
      font-weight: 900;
      line-height: 1.35;
    }}
    .visual-kit-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 14px;
    }}
    .visual-kit-card {{
      display: grid;
      grid-template-rows: 230px auto;
      min-height: 430px;
      overflow: hidden;
      border: 1px solid #d7e2da;
      border-radius: 8px;
      background: #fff;
      box-shadow: 0 14px 30px rgba(27, 45, 40, .08);
    }}
    .visual-kit-card.missing {{
      grid-template-rows: auto;
      border-style: dashed;
      border-color: #dcc18d;
      background: #fff8ea;
    }}
    .visual-kit-image {{
      position: relative;
      margin: 0;
      overflow: hidden;
      background: #e7efe8;
    }}
    .visual-kit-image img {{
      display: block;
      width: 100%;
      height: 230px;
      object-fit: cover;
      filter: saturate(1.04) contrast(1.02);
    }}
    .visual-kit-image::after {{
      content: "";
      position: absolute;
      inset: 0;
      background: linear-gradient(180deg, rgba(16, 40, 35, .04), rgba(16, 40, 35, .48));
    }}
    .visual-kit-image figcaption {{
      position: absolute;
      z-index: 1;
      left: 12px;
      right: 12px;
      bottom: 12px;
      color: #fff;
      font-size: 12px;
      font-weight: 850;
      line-height: 1.35;
    }}
    .visual-kit-body {{
      display: grid;
      gap: 9px;
      align-content: start;
      padding: 16px;
    }}
    .visual-kit-label {{
      display: inline-flex;
      width: fit-content;
      min-height: 26px;
      align-items: center;
      padding: 4px 8px;
      border-radius: 999px;
      color: #fff;
      background: var(--forest);
      font-size: 12px;
      font-weight: 950;
    }}
    .visual-kit-card.missing .visual-kit-label {{
      color: #61431d;
      background: #f5e6b2;
    }}
    .visual-kit-body h3 {{
      margin: 0;
      color: var(--forest-dark);
      font-size: 23px;
      line-height: 1.15;
    }}
    .visual-kit-role {{
      color: #354943;
      font-size: 15px;
      font-weight: 800;
      line-height: 1.48;
    }}
    .visual-kit-question {{
      padding-top: 10px;
      border-top: 1px solid #edf1ed;
      color: var(--forest-dark);
      font-size: 13px;
      font-weight: 950;
      line-height: 1.42;
    }}
    .visual-kit-missing-action {{
      padding: 10px 12px;
      border-radius: 8px;
      color: #654823;
      background: #fff;
      border: 1px solid #ead4aa;
      font-size: 13px;
      font-weight: 900;
      line-height: 1.42;
    }}
    .visual-kit-boundary {{
      display: flex;
      flex-wrap: wrap;
      gap: 7px;
      margin-top: 2px;
    }}
    .visual-kit-boundary span {{
      display: inline-flex;
      min-height: 24px;
      align-items: center;
      padding: 4px 8px;
      border-radius: 999px;
      color: #425650;
      background: #eef5ef;
      border: 1px solid #d8e5da;
      font-size: 12px;
      font-weight: 900;
      line-height: 1;
    }}
    .visual-story-arc {{
      display: grid;
      gap: 14px;
    }}
    .visual-story-lead {{
      display: grid;
      grid-template-columns: minmax(0, .86fr) minmax(260px, .48fr);
      gap: 16px;
      align-items: end;
      padding: 18px;
      border-radius: 8px;
      color: #fff;
      background: linear-gradient(135deg, #1c473e, #466644);
    }}
    .visual-story-lead h3 {{
      max-width: 760px;
      margin: 0;
      color: #fff;
      font-family: "Noto Serif TC", "Songti TC", "PMingLiU", serif;
      font-size: clamp(30px, 4vw, 52px);
      line-height: 1.04;
    }}
    .visual-story-lead p {{
      margin-top: 10px;
      color: #fff2dc;
      font-size: 17px;
      font-weight: 800;
      line-height: 1.45;
    }}
    .visual-story-stat {{
      display: grid;
      gap: 8px;
      padding: 14px;
      border-radius: 8px;
      background: rgba(255, 255, 255, .12);
      border: 1px solid rgba(255, 255, 255, .22);
    }}
    .visual-story-stat span {{
      color: #f5e6b2;
      font-size: 12px;
      font-weight: 900;
    }}
    .visual-story-stat b {{
      color: #fff;
      font-size: 34px;
      line-height: 1;
    }}
    .visual-story-grid {{
      display: grid;
      grid-template-columns: minmax(0, 1.35fr) repeat(2, minmax(0, 1fr));
      grid-auto-rows: minmax(258px, auto);
      gap: 12px;
    }}
    .visual-story-panel {{
      position: relative;
      min-height: 258px;
      overflow: hidden;
      border-radius: 8px;
      color: #fff;
      background: #173b35;
      border: 1px solid #d5dfd8;
      box-shadow: 0 14px 30px rgba(27, 45, 40, .1);
    }}
    .visual-story-panel:nth-child(1) {{
      grid-row: span 2;
      min-height: 532px;
    }}
    .visual-story-panel:nth-child(4) {{
      grid-column: span 2;
    }}
    .visual-story-panel img {{
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      object-fit: cover;
      filter: saturate(1.04) contrast(1.02);
    }}
    .visual-story-panel::after {{
      content: "";
      position: absolute;
      inset: 0;
      background:
        linear-gradient(180deg, rgba(17, 43, 38, .04), rgba(17, 43, 38, .84)),
        linear-gradient(90deg, rgba(17, 43, 38, .34), rgba(17, 43, 38, .04));
    }}
    .visual-story-body {{
      position: absolute;
      z-index: 1;
      left: 18px;
      right: 18px;
      bottom: 18px;
      display: grid;
      gap: 8px;
    }}
    .visual-story-step {{
      display: inline-flex;
      width: fit-content;
      min-height: 28px;
      align-items: center;
      padding: 4px 9px;
      border-radius: 999px;
      color: #223d35;
      background: #f5e6b2;
      font-size: 12px;
      font-weight: 900;
    }}
    .visual-story-panel h3 {{
      margin: 0;
      color: #fff;
      font-size: 27px;
      line-height: 1.08;
    }}
    .visual-story-panel p {{
      margin: 0;
      color: #fff3df;
      font-size: 14px;
      font-weight: 850;
      line-height: 1.42;
    }}
    .visual-anchor-board {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 14px;
    }}
    .visual-anchor {{
      display: grid;
      grid-template-rows: 180px auto;
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
    }}
    .visual-anchor img {{
      width: 100%;
      height: 100%;
      object-fit: cover;
      background: #e7efe8;
    }}
    .visual-anchor-body {{ padding: 16px; }}
    .visual-anchor-body p {{ margin: 6px 0; }}
    .anchor-kind {{
      display: inline-flex;
      margin-bottom: 10px;
      padding: 4px 8px;
      border-radius: 999px;
      color: #fff;
      background: var(--sky);
      font-size: 12px;
      font-weight: 900;
    }}
    .p2-review-board {{
      display: grid;
      grid-template-columns: minmax(320px, .92fr) minmax(0, 1.08fr);
      gap: 18px;
      align-items: stretch;
      margin-top: 18px;
    }}
    .p2-visual {{
      position: relative;
      min-height: 430px;
      overflow: hidden;
      border-radius: 8px;
      background: #203f37;
      border: 1px solid #cfd9d3;
    }}
    .p2-visual img {{
      display: block;
      width: 100%;
      height: 100%;
      min-height: 430px;
      object-fit: cover;
    }}
    .p2-visual figcaption {{
      position: absolute;
      left: 12px;
      right: 12px;
      bottom: 12px;
      padding: 10px 12px;
      border-radius: 8px;
      color: #fff;
      background: rgba(22, 43, 38, .86);
      font-size: 12px;
      font-weight: 850;
      line-height: 1.35;
    }}
    .p2-panel {{
      display: grid;
      gap: 14px;
      align-content: start;
      padding: 18px;
      border-radius: 8px;
      background: #f7f5ee;
      border: 1px solid #e6dcc7;
    }}
    .p2-lens {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }}
    .p2-lens span {{
      display: block;
      min-height: 84px;
      padding: 12px;
      border-radius: 8px;
      background: #fff;
      border: 1px solid #e2e6df;
      color: #344842;
      font-size: 13px;
      font-weight: 800;
      line-height: 1.45;
    }}
    .p2-lens b {{
      display: block;
      margin-bottom: 5px;
      color: var(--forest-dark);
      font-size: 14px;
    }}
    .p2-source-stack {{
      display: grid;
      gap: 10px;
    }}
    .p2-source-card {{
      display: grid;
      grid-template-columns: 76px 1fr;
      gap: 12px;
      align-items: start;
      padding: 14px;
      border-radius: 8px;
      background: #fff;
      border: 1px solid #e0e7df;
    }}
    .p2-source-card h3 {{
      margin: 0 0 4px;
      font-size: 18px;
      line-height: 1.2;
    }}
    .p2-source-card p {{
      margin: 5px 0 0;
      color: #344842;
      line-height: 1.45;
    }}
    .p2-source-count {{
      display: grid;
      place-items: center;
      min-height: 64px;
      border-radius: 8px;
      color: #fff;
      background: var(--gold);
      font-weight: 900;
      text-align: center;
    }}
    .p2-source-count b {{
      display: block;
      font-size: 26px;
      line-height: 1;
    }}
    .p2-source-count span {{
      display: block;
      margin-top: 3px;
      font-size: 11px;
    }}
    .p2-empty {{
      padding: 16px;
      border-radius: 8px;
      background: #fff9eb;
      border: 1px dashed #d8bf82;
      color: #5d4726;
      font-weight: 800;
    }}
    .story-wall {{
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      gap: 16px;
      align-items: start;
    }}
    .story-feature,
    .story-tile {{
      position: relative;
      overflow: hidden;
      border-radius: 8px;
      border: 1px solid var(--line);
      background: #fff;
      box-shadow: 0 14px 28px rgba(27, 45, 40, .08);
    }}
    .story-feature {{
      min-height: 470px;
      color: #fff;
      background: #173b35;
    }}
    .story-feature img {{
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      object-fit: cover;
    }}
    .story-feature::after {{
      content: "";
      position: absolute;
      inset: 0;
      background: linear-gradient(180deg, rgba(15, 35, 31, .1), rgba(15, 35, 31, .82));
    }}
    .story-feature-body {{
      position: absolute;
      z-index: 1;
      inset: auto 0 0;
      padding: 28px;
    }}
    .story-feature-body .source-chips {{ margin-top: 14px; }}
    .story-feature h3 {{
      max-width: 680px;
      margin: 12px 0;
      color: #fff;
      font-size: clamp(34px, 4vw, 58px);
      line-height: .98;
    }}
    .story-feature .story-cue {{
      max-width: 620px;
      margin: 0 0 14px;
      color: rgba(255, 255, 255, .9);
      font-size: clamp(19px, 2vw, 26px);
      font-weight: 850;
      line-height: 1.35;
    }}
    .story-feature .story-point,
    .story-feature .story-question {{
      max-width: 620px;
      color: rgba(255, 255, 255, .92);
    }}
    .story-mosaic {{
      display: flex;
      gap: 14px;
      width: 100%;
      max-width: 100%;
      min-width: 0;
      overflow-x: auto;
      overscroll-behavior-inline: contain;
      scroll-snap-type: x mandatory;
      padding: 2px 2px 14px;
      scrollbar-color: rgba(35, 79, 69, .55) transparent;
    }}
    .story-tile {{
      display: grid;
      grid-template-rows: 150px auto;
      flex: 0 0 min(330px, calc(100vw - 80px));
      min-height: 300px;
      scroll-snap-align: start;
    }}
    .story-tile img {{
      width: 100%;
      height: 150px;
      object-fit: cover;
      background: #e7efe8;
    }}
    .story-tile-body {{
      display: grid;
      gap: 8px;
      padding: 15px;
    }}
    .story-tile h3 {{
      margin: 0;
      font-size: 19px;
      line-height: 1.2;
    }}
    .story-cue {{
      margin: 0;
      color: #3f504b;
      font-size: 15px;
      font-weight: 850;
      line-height: 1.55;
    }}
    .story-point {{
      margin: 0;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
    }}
    .story-point b,
    .story-question b {{
      display: inline-block;
      margin-right: 6px;
      color: var(--forest-dark);
      font-size: 12px;
      letter-spacing: .03em;
      text-transform: uppercase;
    }}
    .story-question {{
      margin-top: 4px;
      padding-top: 10px;
      border-top: 1px solid #edf1ed;
      color: var(--forest-dark);
      font-size: 13px;
      font-weight: 900;
    }}
    .story-speaker-note {{
      margin-top: 4px;
      color: var(--muted);
      font-size: 13px;
    }}
    .story-speaker-note summary {{
      cursor: pointer;
      color: var(--forest-dark);
      font-weight: 900;
    }}
    .story-speaker-note p {{
      margin: 8px 0 0;
      line-height: 1.5;
    }}
    .mode-briefing .story-speaker-note {{
      display: none;
    }}
    .route-rail {{
      display: flex;
      gap: 10px;
      overflow-x: auto;
      margin: 18px 0;
      padding-bottom: 8px;
    }}
    .route-node {{
      flex: 0 0 132px;
      min-height: 92px;
      padding: 12px;
      border-radius: 8px;
      color: #fff;
      background: linear-gradient(160deg, #245347, #4d6b52);
    }}
    .route-node b {{ display: block; margin-bottom: 6px; color: #f5e6b2; }}
    .route-focus-strip {{
      display: grid;
      grid-template-columns: minmax(0, .82fr) repeat(3, minmax(160px, .32fr));
      gap: 10px;
      margin: 0 0 18px;
      padding: 14px;
      border-radius: 8px;
      color: #fff;
      background: linear-gradient(135deg, #1f4a40, #496743);
      border: 1px solid rgba(35, 79, 69, .18);
      box-shadow: 0 14px 30px rgba(31, 42, 35, .1);
    }}
    .route-focus-lead {{
      display: grid;
      gap: 8px;
      align-content: center;
      min-width: 0;
    }}
    .route-focus-lead .kicker {{ color: #f5e6b2; margin-bottom: 0; }}
    .route-focus-lead h3 {{
      margin: 0;
      color: #fff;
      font-size: 28px;
      line-height: 1.16;
    }}
    .route-focus-lead p {{
      max-width: 720px;
      color: #fff4dc;
      font-weight: 750;
      line-height: 1.5;
    }}
    .route-focus-item {{
      display: grid;
      gap: 5px;
      align-content: start;
      min-height: 112px;
      padding: 12px;
      border-radius: 8px;
      color: #fff;
      background: rgba(255, 255, 255, .12);
      border: 1px solid rgba(255, 255, 255, .18);
    }}
    .route-focus-item b {{
      color: #f5e6b2;
      font-size: 13px;
      line-height: 1.2;
    }}
    .route-focus-item span {{
      color: #fff;
      font-size: 13px;
      font-weight: 800;
      line-height: 1.42;
    }}
    .map-atlas {{
      display: grid;
      gap: 16px;
      margin: 20px 0;
    }}
    .map-atlas-hero {{
      display: grid;
      grid-template-columns: minmax(360px, 1.05fr) minmax(0, .95fr);
      gap: 18px;
      align-items: stretch;
      padding: 18px;
      border-radius: 8px;
      color: #fff;
      background:
        linear-gradient(135deg, rgba(17, 24, 32, .96), rgba(143, 31, 24, .92)),
        var(--night);
      border: 1px solid rgba(255, 176, 0, .42);
      box-shadow: 0 22px 46px rgba(17, 24, 32, .24);
    }}
    .map-atlas-figure {{
      position: relative;
      margin: 0;
      min-height: 360px;
      overflow: hidden;
      border-radius: 8px;
      background: #0f171f;
      border: 1px solid rgba(255, 176, 0, .38);
    }}
    .map-atlas-figure img {{
      display: block;
      width: 100%;
      height: 100%;
      min-height: 360px;
      object-fit: cover;
      filter: saturate(1.1) contrast(1.08);
    }}
    .map-atlas-figure::after {{
      content: "";
      position: absolute;
      inset: 0;
      background:
        linear-gradient(180deg, rgba(17, 24, 32, .02), rgba(17, 24, 32, .72)),
        linear-gradient(90deg, rgba(227, 61, 36, .16), rgba(255, 176, 0, .05));
    }}
    .map-atlas-figure figcaption {{
      position: absolute;
      z-index: 1;
      left: 14px;
      right: 14px;
      bottom: 14px;
      display: grid;
      gap: 7px;
      color: #fff;
      font-size: 12px;
      font-weight: 900;
      line-height: 1.35;
    }}
    .map-atlas-copy {{
      display: grid;
      align-content: center;
      gap: 16px;
      min-width: 0;
    }}
    .map-atlas-copy h3 {{
      margin: 0;
      color: #fff;
      font-family: "Noto Serif TC", "Songti TC", "PMingLiU", serif;
      font-size: clamp(34px, 4vw, 60px);
      line-height: 1.02;
    }}
    .map-atlas-copy p {{
      color: #ffe9c6;
      font-size: 17px;
      font-weight: 850;
      line-height: 1.48;
    }}
    .map-atlas-stats {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }}
    .map-atlas-stat {{
      min-height: 96px;
      padding: 12px;
      border-radius: 8px;
      color: #fff;
      background: rgba(255, 255, 255, .1);
      border: 1px solid rgba(255, 176, 0, .28);
    }}
    .map-atlas-stat span {{
      display: block;
      color: var(--signal);
      font-size: 12px;
      font-weight: 950;
    }}
    .map-atlas-stat b {{
      display: block;
      margin-top: 5px;
      color: #fff;
      font-size: 24px;
      line-height: 1.05;
    }}
    .map-atlas-layers {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }}
    .map-layer-card {{
      display: grid;
      gap: 8px;
      min-height: 170px;
      padding: 14px;
      border-radius: 8px;
      color: #fff;
      background: var(--night);
      border: 1px solid rgba(255, 176, 0, .3);
      box-shadow: inset 4px 0 0 var(--ember);
    }}
    .map-layer-card b {{
      color: var(--signal);
      font-size: 18px;
      line-height: 1.16;
    }}
    .map-layer-card p {{
      color: #f5f7f4;
      font-size: 14px;
      font-weight: 780;
      line-height: 1.45;
    }}
    .map-layer-card small {{
      color: var(--ice);
      font-size: 12px;
      font-weight: 900;
      line-height: 1.35;
    }}
    .route-overview {{
      display: grid;
      grid-template-columns: minmax(0, 1.1fr) minmax(260px, .9fr);
      gap: 16px;
      align-items: stretch;
      margin: 18px 0;
    }}
    .route-profile-card {{
      min-height: 270px;
      padding: 18px;
      border-radius: 8px;
      border: 1px solid #d7e1d9;
      background: linear-gradient(180deg, #f8fbf5, #fffefa);
    }}
    .route-profile-head {{
      display: flex;
      justify-content: space-between;
      gap: 14px;
      align-items: start;
      margin-bottom: 18px;
    }}
    .route-profile-head b {{ color: var(--forest-dark); font-size: 20px; }}
    .profile-stats {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
      margin-bottom: 22px;
    }}
    .profile-stat {{
      padding: 10px;
      border-radius: 8px;
      background: #eef5ef;
      color: #31433e;
      font-weight: 800;
    }}
    .profile-stat span {{ display: block; color: var(--muted); font-size: 12px; font-weight: 700; }}
    .profile-track {{
      position: relative;
      min-height: 110px;
      margin: 18px 4px 4px;
      border-bottom: 2px solid #c9d6cc;
    }}
    .profile-track::before {{
      content: "";
      position: absolute;
      left: 0;
      right: 0;
      bottom: 22px;
      height: 56px;
      border-radius: 999px 999px 18px 18px;
      background: linear-gradient(90deg, rgba(108,127,66,.28), rgba(183,138,53,.34), rgba(74,113,148,.26));
      clip-path: polygon(0 82%, 16% 70%, 28% 42%, 42% 54%, 58% 22%, 76% 36%, 100% 18%, 100% 100%, 0 100%);
    }}
    .profile-marker {{
      position: absolute;
      bottom: 14px;
      width: 2px;
      height: 72px;
      background: rgba(35, 79, 69, .56);
    }}
    .profile-marker::after {{
      content: "";
      position: absolute;
      left: -5px;
      top: -4px;
      width: 12px;
      height: 12px;
      border-radius: 999px;
      background: var(--forest-dark);
      box-shadow: 0 0 0 4px rgba(35, 79, 69, .14);
    }}
    .profile-legend {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 8px;
      margin-top: 12px;
    }}
    .profile-legend-item {{
      padding: 8px 10px;
      border-radius: 8px;
      background: #f1f6f2;
      color: #31433e;
      font-size: 13px;
      font-weight: 800;
    }}
    .profile-legend-item b {{
      color: var(--clay);
      margin-right: 6px;
    }}
    .route-media-note {{
      display: grid;
      gap: 12px;
      align-content: start;
      padding: 16px;
      border-radius: 8px;
      border: 1px solid #ead9b5;
      background: #fff8ea;
    }}
    .route-reader-cues {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }}
    .route-reader-cues span {{
      display: block;
      padding: 11px 12px;
      border-radius: 8px;
      color: #344842;
      background: #fff;
      border: 1px solid #eadfca;
      font-size: 13px;
      font-weight: 800;
      line-height: 1.42;
    }}
    .route-reader-cues b {{
      display: block;
      margin-bottom: 5px;
      color: var(--forest-dark);
      font-size: 14px;
    }}
    .route-photo-strip {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
    }}
    .route-photo-strip .photo {{
      min-height: 118px;
    }}
    .route-photo-strip .photo img {{
      min-height: 118px;
      max-height: 132px;
    }}
    .route-photo-strip .photo figcaption {{
      font-size: 11px;
      line-height: 1.3;
    }}
    .route-data-details {{
      margin-top: 8px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 700;
    }}
    .mode-briefing .route-data-details {{
      display: none;
    }}
    .risk-review-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 14px;
    }}
    .risk-review-card {{
      display: grid;
      gap: 12px;
      align-content: start;
      min-height: 260px;
      padding: 18px;
      border-radius: 8px;
      border: 1px solid #ead0bd;
      background: linear-gradient(180deg, #fff8f2, #ffffff);
      box-shadow: 0 12px 24px rgba(95, 61, 40, .06);
    }}
    .risk-review-card h3 {{
      margin: 0;
      font-size: 24px;
      line-height: 1.16;
    }}
    .risk-visual {{
      position: relative;
      margin: 0;
      overflow: hidden;
      aspect-ratio: 16 / 9;
      border-radius: 8px;
      background: #f1ebe3;
    }}
    .risk-visual img {{
      display: block;
      width: 100%;
      height: 100%;
      object-fit: cover;
    }}
    .risk-visual figcaption {{
      position: absolute;
      left: 8px;
      right: 8px;
      bottom: 8px;
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      align-items: center;
      padding: 7px 8px;
      border-radius: 8px;
      color: #fff;
      background: rgba(49, 42, 35, .84);
      font-size: 12px;
      font-weight: 850;
      line-height: 1.35;
    }}
    .risk-scene-label {{
      display: inline-flex;
      align-items: center;
      width: fit-content;
      min-height: 28px;
      padding: 4px 9px;
      border-radius: 999px;
      color: var(--clay);
      background: #fff2df;
      border: 1px solid #ecd2ae;
      font-size: 12px;
      font-weight: 900;
      line-height: 1;
    }}
    .risk-cue {{
      margin: 0;
      color: #3f504b;
      font-size: 16px;
      font-weight: 850;
      line-height: 1.45;
    }}
    .risk-action {{
      margin: 0;
      padding: 12px;
      border-radius: 8px;
      color: var(--forest-dark);
      background: #fff2df;
      border: 1px solid #ecd2ae;
      font-weight: 900;
      line-height: 1.45;
    }}
    .risk-operator-note {{
      margin: 0;
      color: #4f625c;
      font-size: 14px;
      font-weight: 800;
      line-height: 1.45;
    }}
    .risk-action b {{
      display: block;
      margin-bottom: 4px;
      color: var(--clay);
      font-size: 12px;
      letter-spacing: .03em;
      text-transform: uppercase;
    }}
    .risk-data-details {{
      color: var(--muted);
      font-size: 13px;
    }}
    .risk-data-details summary {{
      cursor: pointer;
      color: var(--forest-dark);
      font-weight: 900;
    }}
    .risk-data-details p {{
      margin: 8px 0 0;
      line-height: 1.5;
    }}
    .mode-briefing .risk-data-details {{
      display: none;
    }}
    .storyline-rail {{
      position: relative;
      display: flex;
      gap: 16px;
      width: 100%;
      max-width: 100%;
      min-width: 0;
      overflow-x: auto;
      overscroll-behavior-inline: contain;
      scroll-snap-type: x mandatory;
      padding: 10px 2px 18px;
      scrollbar-color: rgba(35, 79, 69, .55) transparent;
    }}
    .storyline-rail::before {{
      content: "";
      position: absolute;
      left: 24px;
      right: 24px;
      top: 38px;
      height: 2px;
      background: #d8e2db;
    }}
    .storyline-card {{
      position: relative;
      display: grid;
      gap: 12px;
      align-content: start;
      flex: 0 0 min(360px, calc(100vw - 86px));
      scroll-snap-align: start;
      min-height: 430px;
      padding: 14px;
      border-radius: 8px;
      border: 1px solid #dfe8e2;
      background: linear-gradient(180deg, #ffffff, #f7fbf8);
      box-shadow: 0 14px 28px rgba(32, 64, 55, .08);
    }}
    .storyline-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      min-width: 0;
    }}
    .storyline-index,
    .storyline-distance {{
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      padding: 4px 9px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 900;
      line-height: 1;
    }}
    .storyline-index {{
      color: #fff;
      background: var(--forest);
    }}
    .storyline-distance {{
      color: var(--forest-dark);
      background: #eef5ef;
      border: 1px solid #d7e5dc;
    }}
    .storyline-thumb {{
      position: relative;
      margin: 0;
      overflow: hidden;
      aspect-ratio: 16 / 9;
      border-radius: 8px;
      background: #edf3ef;
    }}
    .storyline-thumb img {{
      display: block;
      width: 100%;
      height: 100%;
      object-fit: cover;
    }}
    .storyline-thumb figcaption {{
      position: absolute;
      left: 8px;
      right: 8px;
      bottom: 8px;
      padding: 6px 8px;
      border-radius: 8px;
      color: #fff;
      background: rgba(23, 43, 38, .84);
      font-size: 12px;
      font-weight: 850;
      line-height: 1.35;
    }}
    .storyline-card h3 {{
      margin: 0;
      color: var(--forest-dark);
      font-size: 23px;
      line-height: 1.18;
    }}
    .storyline-cue {{
      margin: 0;
      color: #3a4e47;
      font-size: 15px;
      font-weight: 850;
      line-height: 1.45;
    }}
    .storyline-action {{
      margin: 0;
      padding: 12px;
      border-radius: 8px;
      color: var(--forest-dark);
      background: #fff8ea;
      border: 1px solid #ead9b5;
      font-weight: 850;
      line-height: 1.45;
    }}
    .storyline-action b {{
      display: block;
      margin-bottom: 4px;
      color: var(--clay);
      font-size: 12px;
      letter-spacing: .03em;
      text-transform: uppercase;
    }}
    .storyline-data-details {{
      color: var(--muted);
      font-size: 13px;
    }}
    .storyline-data-details summary {{
      cursor: pointer;
      color: var(--forest-dark);
      font-weight: 900;
    }}
    .storyline-data-details p {{
      margin: 8px 0 0;
      line-height: 1.5;
    }}
    .mode-briefing .storyline-data-details {{
      display: none;
    }}
    .steps {{ display: grid; gap: 10px; }}
    .step {{ display: grid; grid-template-columns: 88px 1fr; gap: 10px; }}
    .step strong {{ display: block; color: var(--forest-dark); }}
    .time {{ color: var(--clay); font-weight: 900; }}
    .briefing-script {{
      display: grid;
      gap: 10px;
      margin-top: 12px;
    }}
    .script-row {{
      padding: 10px 12px;
      border-radius: 8px;
      background: #f6f8f7;
      border: 1px solid #e3e9e5;
    }}
    .script-row.talk-row {{
      background: #f5faf4;
      border-color: #d9e8d5;
    }}
    .script-row.ask-row {{
      background: #fffaf0;
      border-color: #ead9b5;
    }}
    .script-row.boundary-row {{
      background: #fff6ee;
      border-color: #edcfbd;
    }}
    .script-row b {{
      display: block;
      margin-bottom: 4px;
      color: var(--forest-dark);
    }}
    .script-row span {{
      display: block;
      color: #344842;
      line-height: 1.5;
    }}
    .layer-data-details {{
      color: var(--muted);
      font-size: 13px;
    }}
    .layer-data-details summary {{
      cursor: pointer;
      color: var(--forest-dark);
      font-weight: 900;
    }}
    .layer-data-details p {{
      margin: 8px 0 0;
      line-height: 1.5;
    }}
    .mode-briefing .layer-definition,
    .mode-briefing .script-row.boundary-row,
    .mode-briefing .layer-data-details {{
      display: none;
    }}
    .schedule-board {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 16px;
    }}
    .schedule-focus-strip {{
      display: grid;
      grid-template-columns: minmax(0, .82fr) repeat(3, minmax(160px, .32fr));
      gap: 10px;
      margin: 0 0 18px;
      padding: 14px;
      border-radius: 8px;
      color: #fff;
      background: linear-gradient(135deg, #214f44, #476d79);
      border: 1px solid rgba(35, 79, 69, .16);
      box-shadow: 0 14px 30px rgba(31, 42, 35, .1);
    }}
    .schedule-focus-lead {{
      display: grid;
      gap: 8px;
      align-content: center;
      min-width: 0;
    }}
    .schedule-focus-lead .kicker {{ color: #f5e6b2; margin-bottom: 0; }}
    .schedule-focus-lead h3 {{
      margin: 0;
      color: #fff;
      font-size: 28px;
      line-height: 1.16;
    }}
    .schedule-focus-lead p {{
      max-width: 720px;
      color: #fff4dc;
      font-weight: 750;
      line-height: 1.5;
    }}
    .schedule-focus-item {{
      display: grid;
      gap: 5px;
      align-content: start;
      min-height: 112px;
      padding: 12px;
      border-radius: 8px;
      color: #fff;
      background: rgba(255, 255, 255, .12);
      border: 1px solid rgba(255, 255, 255, .18);
    }}
    .schedule-focus-item b {{
      color: #f5e6b2;
      font-size: 13px;
      line-height: 1.2;
    }}
    .schedule-focus-item span {{
      color: #fff;
      font-size: 13px;
      font-weight: 800;
      line-height: 1.42;
    }}
    .schedule-decision-board {{
      display: grid;
      grid-template-columns: minmax(320px, .85fr) minmax(0, 1.15fr);
      gap: 18px;
      align-items: stretch;
      margin-bottom: 18px;
    }}
    .schedule-gate-panel {{
      display: grid;
      gap: 14px;
      align-content: start;
      padding: 18px;
      border-radius: 8px;
      background: #f7f5ee;
      border: 1px solid #e6dcc7;
    }}
    .schedule-gate-panel h3 {{
      margin: 0;
      color: var(--forest-dark);
      font-size: 28px;
      line-height: 1.16;
    }}
    .schedule-gate-panel p {{
      margin: 0;
      color: #344842;
      line-height: 1.52;
    }}
    .schedule-gates {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }}
    .schedule-gates span {{
      display: block;
      min-height: 92px;
      padding: 12px;
      border-radius: 8px;
      color: #344842;
      background: #fff;
      border: 1px solid #e1e6dd;
      font-size: 13px;
      font-weight: 800;
      line-height: 1.45;
    }}
    .schedule-gates b {{
      display: block;
      margin-bottom: 5px;
      color: var(--forest-dark);
      font-size: 14px;
    }}
    .schedule-decision-tag {{
      display: inline-flex;
      width: fit-content;
      align-items: center;
      min-height: 26px;
      padding: 4px 9px;
      border-radius: 999px;
      color: #fff;
      background: var(--forest);
      font-size: 12px;
      font-weight: 900;
    }}
    .schedule-photo-strip {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      width: 100%;
      min-width: 0;
      margin: 0;
      overflow: hidden;
    }}
    .schedule-photo-strip > * {{
      min-width: 0;
    }}
    .schedule-photo-strip .field-media {{
      margin: 0;
    }}
    .schedule-version {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      overflow: hidden;
    }}
    .schedule-version.primary {{
      border-color: #bccd9d;
      box-shadow: inset 0 0 0 2px rgba(95, 113, 66, .16);
    }}
    .schedule-version.slow {{
      border-color: #cbd9df;
    }}
    .schedule-version-head {{
      padding: 18px;
      color: #fff;
      background: linear-gradient(145deg, #214d43, #697943);
    }}
    .schedule-version.slow .schedule-version-head {{
      background: linear-gradient(145deg, #214d43, #4a7194);
    }}
    .schedule-version-head strong {{
      display: block;
      margin-top: 4px;
      font-size: 30px;
      line-height: 1.1;
    }}
    .schedule-version-head p {{
      margin-bottom: 0;
      line-height: 1.5;
    }}
    .schedule-version-gate {{
      margin: 14px 18px 0;
      padding: 12px;
      border-radius: 8px;
      color: var(--forest-dark);
      background: #f3f7ef;
      border: 1px solid #dbe7cf;
      font-weight: 850;
      line-height: 1.45;
    }}
    .schedule-version-gate b {{
      display: block;
      margin-bottom: 4px;
      color: var(--clay);
      font-size: 12px;
      letter-spacing: .03em;
      text-transform: uppercase;
    }}
    .day-plan {{
      display: grid;
      grid-template-columns: 64px 1fr;
      gap: 12px;
      padding: 16px 18px;
      border-top: 1px solid #e5ece8;
    }}
    .day-plan b {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 48px;
      height: 48px;
      border-radius: 999px;
      color: var(--forest-dark);
      background: #e8efdc;
    }}
    .day-plan h3 {{ font-size: 18px; }}
    .schedule-caution {{
      margin-top: 16px;
      padding: 16px;
      border-radius: 8px;
      background: #fff7ea;
      border: 1px solid #ead9b5;
    }}
    .trust-board {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 14px;
      margin-bottom: 18px;
    }}
    .trust-card {{
      min-height: 150px;
      padding: 16px;
      border-radius: 8px;
      border: 1px solid var(--line);
      background: #fff;
    }}
    .source-brief-grid {{
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    }}
    .source-brief-card {{
      display: grid;
      gap: 10px;
      min-height: 210px;
      box-shadow: 0 12px 24px rgba(27, 45, 40, .06);
    }}
    .trust-card.good {{ background: #f2f8ef; border-color: #ccdfbd; }}
    .trust-card.warn {{ background: #fff8ea; border-color: #ead7ae; }}
    .trust-card.boundary {{ background: #eef5f7; border-color: #cfe1e7; }}
    .trust-card b {{
      display: block;
      margin-bottom: 6px;
      color: var(--forest-dark);
      font-size: 26px;
      line-height: 1.05;
    }}
    .source-trust-layout {{
      display: grid;
      grid-template-columns: minmax(300px, .82fr) minmax(0, 1.18fr);
      gap: 16px;
      align-items: stretch;
      margin-bottom: 18px;
    }}
    .source-tier-spine {{
      display: grid;
      gap: 16px;
      margin-bottom: 18px;
      padding: 18px;
      border-radius: 8px;
      color: #fff;
      background:
        linear-gradient(135deg, rgba(17, 24, 32, .98), rgba(35, 79, 69, .92)),
        var(--night);
      border: 1px solid rgba(255, 176, 0, .36);
      box-shadow: 0 18px 40px rgba(17, 24, 32, .18);
    }}
    .source-tier-spine h3 {{
      margin: 0;
      color: #fff;
      font-family: "Noto Serif TC", "Songti TC", "PMingLiU", serif;
      font-size: clamp(30px, 3.4vw, 50px);
      line-height: 1.06;
    }}
    .source-tier-spine p {{
      color: #fff1d0;
      font-weight: 850;
      line-height: 1.48;
    }}
    .source-tier-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }}
    .source-tier-card {{
      display: grid;
      gap: 10px;
      align-content: start;
      min-height: 230px;
      padding: 14px;
      border-radius: 8px;
      background: rgba(255, 255, 255, .1);
      border: 1px solid rgba(255, 255, 255, .18);
    }}
    .source-tier-card.p0 {{ box-shadow: inset 5px 0 0 var(--signal); }}
    .source-tier-card.p1 {{ box-shadow: inset 5px 0 0 var(--ice); }}
    .source-tier-card.p2 {{ box-shadow: inset 5px 0 0 var(--ember); }}
    .source-tier-card span {{
      display: inline-flex;
      width: fit-content;
      min-height: 28px;
      align-items: center;
      padding: 4px 9px;
      border-radius: 999px;
      color: var(--night);
      background: var(--signal);
      font-size: 12px;
      font-weight: 950;
      line-height: 1;
    }}
    .source-tier-card.p1 span {{ background: var(--ice); }}
    .source-tier-card.p2 span {{ color: #fff; background: var(--ember); }}
    .source-tier-card b {{
      color: #fff;
      font-size: 28px;
      line-height: 1.05;
    }}
    .source-tier-card ul {{
      display: grid;
      gap: 7px;
      margin: 0;
      padding-left: 18px;
      color: #fff;
      font-size: 13px;
      font-weight: 820;
      line-height: 1.38;
    }}
    .source-tier-card small {{
      color: #ffe9c6;
      font-size: 12px;
      font-weight: 880;
      line-height: 1.35;
    }}
    .source-trust-visual {{
      display: grid;
      grid-template-rows: minmax(260px, 1fr) auto;
      overflow: hidden;
      min-height: 100%;
      border-radius: 8px;
      border: 1px solid #d7e2dc;
      background: #f3f7f4;
    }}
    .source-trust-visual img {{
      display: block;
      width: 100%;
      height: 100%;
      min-height: 260px;
      object-fit: cover;
    }}
    .source-trust-caption {{
      display: grid;
      gap: 8px;
      padding: 14px;
      color: #344842;
      font-size: 13px;
      font-weight: 800;
      line-height: 1.45;
    }}
    .source-path {{
      counter-reset: source-step;
    }}
    .source-path .source-brief-card {{
      position: relative;
      grid-template-columns: 42px 1fr;
      gap: 12px;
      min-height: auto;
    }}
    .source-step-index {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 38px;
      height: 38px;
      border-radius: 999px;
      color: #fff;
      background: var(--forest);
      font-size: 13px;
      font-weight: 900;
    }}
    .source-card-body {{
      min-width: 0;
    }}
    .source-cue {{
      margin: 0;
      color: #31433e;
      font-size: 16px;
      font-weight: 850;
      line-height: 1.45;
    }}
    .source-action {{
      margin: 0;
      padding: 11px 12px;
      border-radius: 8px;
      color: var(--forest-dark);
      background: rgba(255, 255, 255, .68);
      border: 1px solid rgba(35, 79, 69, .12);
      font-weight: 850;
      line-height: 1.45;
    }}
    .source-action b {{
      display: block;
      margin-bottom: 4px;
      color: var(--clay);
      font-size: 12px;
      letter-spacing: .03em;
      text-transform: uppercase;
    }}
    .source-details {{
      margin-top: 18px;
      padding: 16px;
      border-radius: 8px;
      border: 1px solid var(--line);
      background: #fff;
    }}
    .source-details summary {{
      cursor: pointer;
      color: var(--forest-dark);
      font-weight: 900;
    }}
    .tag {{
      display: inline-flex;
      margin-bottom: 10px;
      padding: 4px 8px;
      border-radius: 999px;
      color: #fff;
      background: var(--forest);
      font-size: 12px;
      font-weight: 900;
    }}
    .tag.gold {{ background: var(--gold); }}
    .tag.sky {{ background: var(--sky); }}
    .tag.rust {{ background: var(--clay); }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; }}
    th, td {{ padding: 10px; border-bottom: 1px solid #e7ecef; text-align: left; vertical-align: top; font-size: 14px; }}
    th {{ color: #42524d; background: #f6f8f7; }}
    ul, ol {{ margin: 0; padding-left: 20px; }}
    li {{ margin: 7px 0; }}
    @media (max-width: 720px) {{
      .wrap {{ width: min(100% - 28px, 1160px); }}
      .hero {{ min-height: auto; padding: 52px 0 34px; }}
      h1 {{ font-size: 36px; }}
      h2 {{ font-size: 30px; }}
      .visual-agenda {{
        grid-template-columns: 1fr;
        padding: 14px;
      }}
      .visual-agenda-copy h2 {{ font-size: 28px; }}
      .visual-agenda-grid {{ grid-template-columns: 1fr; }}
      .visual-agenda-card {{ min-height: 218px; }}
      .slide {{ scroll-margin-top: 154px; }}
      .slide-inner {{ padding: 20px; }}
      .slide-head {{ display: block; }}
      .stamp {{ margin-top: 14px; }}
      .chapter-inner {{ grid-template-columns: 1fr; padding: 30px 20px; }}
      .chapter-break h2 {{ font-size: 34px; }}
      .chapter-copy {{ font-size: 17px; }}
      .chapter-visual-photo,
      .chapter-visual-photo img {{ min-height: 220px; }}
      .nav-progress {{ display: none; }}
      .mode-switch {{ margin-left: 0; }}
      .mobile-presenter-dock {{
        position: sticky;
        z-index: 9;
        top: 63px;
        width: min(100% - 28px, 362px);
        margin: 8px auto 10px;
        display: grid;
        grid-template-columns: 44px minmax(0, 1fr) 44px;
        gap: 8px;
        align-items: center;
        padding: 8px;
        border: 1px solid #b9cec5;
        border-radius: 8px;
        background: rgba(247, 245, 238, .98);
        box-shadow:
          0 16px 34px rgba(19, 40, 35, .24),
          0 0 0 1px rgba(255, 255, 255, .82);
        backdrop-filter: blur(12px);
      }}
      .mode-data .mobile-presenter-dock {{
        display: none;
      }}
      .mobile-presenter-dock .presenter-button {{
        width: 44px;
        height: 44px;
        color: #fff;
        background: var(--forest);
      }}
      .mobile-presenter-dock .presenter-button:disabled {{
        color: #74847e;
        background: #e5ece7;
        opacity: 1;
      }}
      .mobile-presenter-status {{
        min-width: 0;
        display: grid;
        gap: 0;
        justify-items: center;
        color: var(--forest-dark);
        font-weight: 900;
        line-height: 1.15;
      }}
      .mobile-presenter-status span,
      .mobile-presenter-status small {{
        color: var(--muted);
        font-size: 11px;
        font-weight: 850;
      }}
      .mobile-presenter-status b {{
        max-width: 100%;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        font-size: 15px;
      }}
      .briefing-deck > article {{ flex-basis: calc(100vw - 54px); }}
      .source-health-board {{ grid-template-columns: 1fr; }}
      .source-health-score {{ grid-template-columns: 1fr; }}
      .source-health-grid {{ grid-template-columns: 1fr; }}
      .storyline-card {{ flex-basis: calc(100vw - 54px); }}
      .storyline-rail::before {{ display: none; }}
      .step {{ grid-template-columns: 1fr; }}
      .image-band {{ grid-template-columns: 1fr; }}
      .route-focus-strip {{ grid-template-columns: 1fr; }}
      .route-focus-item {{ min-height: auto; }}
      .photo-essay {{ grid-template-columns: 1fr; }}
      .photo-essay-feature, .photo-essay-feature img {{ min-height: 420px; }}
      .photo-essay-grid {{ grid-template-columns: 1fr; }}
      .photo-essay-card {{ height: 280px; }}
      .photo-essay-card.map-card {{ grid-column: auto; height: 260px; }}
      .visual-contact-sheet {{ grid-template-columns: 1fr; }}
      .visual-contact-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .visual-contact-card {{ min-height: 150px; }}
      .visual-kit-summary {{ grid-template-columns: 1fr; }}
      .visual-kit-grid {{ grid-template-columns: 1fr; }}
      .visual-kit-card {{ grid-template-rows: 240px auto; min-height: auto; }}
      .visual-kit-card.missing {{ grid-template-rows: auto; }}
      .visual-kit-image img {{ height: 240px; }}
      .visual-story-lead {{ grid-template-columns: 1fr; }}
      .visual-story-grid {{ grid-template-columns: 1fr; }}
      .visual-story-panel,
      .visual-story-panel:nth-child(1),
      .visual-story-panel:nth-child(4) {{
        grid-column: auto;
        grid-row: auto;
        min-height: 320px;
      }}
      .map-atlas-hero {{ grid-template-columns: 1fr; padding: 14px; }}
      .map-atlas-figure,
      .map-atlas-figure img {{ min-height: 300px; }}
      .map-atlas-stats {{ grid-template-columns: 1fr; }}
      .map-atlas-layers {{ grid-template-columns: 1fr; }}
      .source-tier-grid {{ grid-template-columns: 1fr; }}
      .route-reader-cues {{ grid-template-columns: 1fr; }}
      .route-photo-strip {{ grid-template-columns: 1fr; }}
      .status-photo-strip {{ grid-template-columns: 1fr; }}
      .status-cues {{ grid-template-columns: 1fr; }}
      .visual-readiness {{ grid-template-columns: 1fr; }}
      .visual-readiness-meter {{ grid-template-columns: 1fr; }}
      .photo-grid {{ grid-template-columns: 1fr; }}
      .visual-anchor-board {{ grid-template-columns: 1fr; }}
      .p2-review-board {{ grid-template-columns: 1fr; }}
      .p2-lens {{ grid-template-columns: 1fr; }}
      .p2-source-card {{ grid-template-columns: 1fr; }}
      .story-wall {{ grid-template-columns: 1fr; }}
      .story-feature {{ min-height: 430px; }}
      .story-feature-body {{ padding: 22px; }}
      .story-mosaic {{ padding-bottom: 12px; }}
      .route-overview {{ grid-template-columns: 1fr; }}
      .profile-stats {{ grid-template-columns: 1fr; }}
      .schedule-focus-strip {{ grid-template-columns: 1fr; }}
      .schedule-focus-item {{ min-height: auto; }}
      .schedule-decision-board {{ grid-template-columns: 1fr; }}
      .schedule-gates {{ grid-template-columns: 1fr; }}
      .schedule-board {{ grid-template-columns: 1fr; }}
      .schedule-photo-strip {{ grid-template-columns: 1fr; }}
      .day-plan {{ grid-template-columns: 1fr; }}
      .source-trust-layout {{ grid-template-columns: 1fr; }}
      .source-path .source-brief-card {{ grid-template-columns: 1fr; }}
      .trust-board {{ grid-template-columns: 1fr; }}
      .itinerary-board {{ grid-template-columns: 1fr; padding: 14px; }}
      .itinerary-lead strong {{ font-size: 34px; }}
      .itinerary-option-card {{ grid-template-columns: 1fr; }}
      .highlight-wall {{ grid-template-columns: 1fr; }}
      .highlight-card, .highlight-card:first-child {{ grid-template-columns: 1fr; }}
    }}
    @page {{
      size: A4 landscape;
      margin: 10mm;
    }}
    @media print {{
      * {{
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
      }}
      html, body {{
        background: #fff;
        background-size: auto;
      }}
      body {{ font-size: 11pt; }}
      nav, .mode-switch, .mobile-presenter-dock {{ display: none !important; }}
      main {{ padding: 0; }}
      .wrap {{ width: 100%; }}
      .hero {{
        min-height: 170mm;
        padding: 18mm 0;
        break-after: page;
        page-break-after: always;
      }}
      h1 {{ font-size: 42pt; }}
      h2 {{ font-size: 26pt; }}
      .hero-copy, .lead, .chapter-copy {{ font-size: 14pt; }}
      .slide {{
        min-height: auto;
        margin: 0 0 8mm;
        border: 1px solid #cfd8d3;
        box-shadow: none;
        overflow: visible;
        break-after: page;
        page-break-after: always;
      }}
      .slide-inner {{ padding: 10mm; }}
      .chapter-break {{
        min-height: 160mm;
        break-before: page;
        page-break-before: always;
      }}
      .chapter-inner {{
        grid-template-columns: minmax(0, .9fr) minmax(260px, .55fr);
        padding: 16mm;
      }}
      .chapter-break h2 {{ font-size: 38pt; }}
      .card, .point, .decision, .layer, .day-card, .trust-card,
      .visual-anchor, .visual-kit-card, .story-feature, .story-tile, .highlight-card, .schedule-version,
      .storyline-card, .field-media, .photo, .script-row {{
        break-inside: avoid;
        page-break-inside: avoid;
      }}
      .briefing-deck,
      .briefing-deck.layers,
      .briefing-deck.stop-deck,
      .storyline-rail,
      .visual-kit-grid,
      .map-atlas-layers,
      .source-tier-grid,
      .visual-story-grid {{
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 6mm;
        overflow: visible;
        padding: 0;
        scroll-snap-type: none;
      }}
      .storyline-rail::before {{ display: none; }}
      .storyline-card {{ min-height: auto; flex: initial; }}
      .briefing-deck > article {{ flex: initial; }}
      .field-media img, .photo img, .visual-anchor img, .visual-kit-image img, .story-tile img,
      .map-atlas-figure img, .highlight-card img, .storyline-thumb img {{
        max-height: 48mm;
      }}
      .map-atlas-hero {{ grid-template-columns: 1fr; }}
      .story-wall {{ grid-template-columns: 1fr; }}
      .story-mosaic {{
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        overflow: visible;
        padding: 0;
        scroll-snap-type: none;
      }}
      .story-tile {{ flex: initial; }}
      .story-feature {{ min-height: 105mm; }}
      .visual-story-lead {{ grid-template-columns: 1fr; }}
      .visual-story-panel,
      .visual-story-panel:nth-child(1),
      .visual-story-panel:nth-child(4) {{
        grid-column: auto;
        grid-row: auto;
        min-height: 80mm;
      }}
      .source-details[open] {{ display: block; }}
      .source-details table {{ font-size: 9pt; }}
    }}
  </style>
</head>
<body class="mode-briefing">
  <header class="hero" id="top">
    {hero_media}
    <div class="wrap">
      <p class="eyebrow">Scout 行前路線簡報</p>
      <h1>{_h(route_label)}登山活動簡報</h1>
      <p class="hero-copy">先看山、再看路，最後才看資料來源。這份簡報把路線節奏、沿途亮點與 3 分鐘觀察點放在前面，讓隊伍先建立共同畫面。</p>
      <div class="meta-row" aria-label="route summary">
        <span class="pill">路線距離候選 {_h(route_distance_km)}</span>
        <span class="pill">脈絡點 {_h(point_count)}</span>
        <span class="pill">照片 {_h(media_count)} 張</span>
        <span class="pill">資料更新 {_h(generated_date)}</span>
        <span class="pill">可追溯版本</span>
      </div>
    </div>
  </header>

  <nav aria-label="簡報導覽">
    <div class="wrap">
      <a class="nav-primary" href="#days">天數結論</a>
      <a class="nav-detail" href="#status">現況</a>
      <a class="nav-primary" href="#photo-essay">圖像導覽</a>
      <a class="nav-primary" href="#visual-kit">素材板</a>
      <a class="nav-primary" href="#visual-story">四幕導覽</a>
      <a class="nav-detail" href="#visual-anchors">照片點</a>
      <a class="nav-detail" href="#story-wall">故事牆</a>
      <a class="nav-primary" href="#route">路線</a>
      <a class="nav-detail" href="#sights">景點</a>
      <a class="nav-detail" href="#layers">脈絡層</a>
      <a class="nav-detail" href="#p2">隊伍回顧</a>
      <a class="nav-detail" href="#storyline">路線敘事</a>
      <a class="nav-primary" href="#stops">觀察點</a>
      <a class="nav-detail" href="#risk">風險</a>
      <a class="nav-primary" href="#schedule">行程</a>
      <a class="nav-primary" href="#sources">來源</a>
      <span class="nav-progress" aria-live="polite" aria-label="目前章節">
        <span>目前</span>
        <b data-active-section-label>天數結論</b>
        <small data-active-section-count>1 / 6</small>
      </span>
      <span class="presenter-controls" aria-label="簡報章節控制">
        <button class="presenter-button" type="button" data-presenter-step="-1" aria-label="上一章"><span class="presenter-icon prev" aria-hidden="true"></span></button>
        <button class="presenter-button" type="button" data-presenter-step="1" aria-label="下一章"><span class="presenter-icon next" aria-hidden="true"></span></button>
      </span>
      <span class="mode-switch" aria-label="顯示模式">
        <button class="mode-button" type="button" data-briefing-mode="briefing" aria-pressed="true">簡報</button>
        <button class="mode-button" type="button" data-briefing-mode="data" aria-pressed="false">資料</button>
      </span>
    </div>
  </nav>

  <div class="mobile-presenter-dock" aria-label="行動簡報章節控制">
    <button class="presenter-button" type="button" data-presenter-step="-1" aria-label="上一章"><span class="presenter-icon prev" aria-hidden="true"></span></button>
    <span class="mobile-presenter-status" aria-live="polite">
      <span>目前章節</span>
      <b data-active-section-label>天數結論</b>
      <small data-active-section-count>1 / 6</small>
    </span>
    <button class="presenter-button" type="button" data-presenter-step="1" aria-label="下一章"><span class="presenter-icon next" aria-hidden="true"></span></button>
  </div>

  {visual_agenda}

  <main class="wrap">
    <section class="slide" id="days">
      <div class="slide-inner">
        <div class="slide-head">
          <div>
            <p class="kicker">行程天數</p>
            <h2>預計幾天可以完成？</h2>
          </div>
          <div class="stamp">行前<br>版本</div>
        </div>
        <p class="lead">先用兩個常見版本討論隊伍節奏：標準完成版，以及保留觀察、拍照與教學時間的慢走版。真正出發前仍要重查山屋、入園、天氣、路況與隊伍狀態。</p>
        {itinerary_options}
        <div class="alert">這裡是行前討論版本，不是自動出發建議；正式採用前仍需由領隊確認天氣、路況、山屋與隊伍狀態。</div>
      </div>
    </section>

    <section class="slide" id="status">
      <div class="slide-inner">
        {media_band}
      </div>
    </section>

    <section class="slide" id="photo-essay">
      <div class="slide-inner">
        <div class="slide-head">
          <div>
            <p class="kicker">圖像導覽</p>
            <h2>先用一組畫面講完這趟路</h2>
          </div>
          <div class="stamp">圖像<br>導覽</div>
        </div>
        <p class="lead">把照片從附件改成簡報主軸：先看路線氣質，再看山屋、展望、日出與導覽圖。這些畫面只協助行前理解，正式安全判斷仍回到天氣、路況與隊伍狀態。</p>
        {photo_essay}
        {visual_contact_sheet}
        {visual_readiness_panel}
      </div>
    </section>

    <section class="slide" id="visual-kit">
      <div class="slide-inner">
        <div class="slide-head">
          <div>
            <p class="kicker">簡報素材板</p>
            <h2>每張圖都要負責一個行前判斷</h2>
          </div>
          <div class="stamp">素材<br>編排</div>
        </div>
        <p class="lead">這一頁把圖片從「附件」改成「講者素材」：開場、路線圖、宿點、地形、短停與天候季節各自負責一個行前問題。缺圖就明確列為採圖缺口，不用文字假裝已經看見。</p>
        {visual_kit}
      </div>
    </section>

    <section class="slide" id="visual-story">
      <div class="slide-inner">
        <div class="slide-head">
          <div>
            <p class="kicker">四幕導覽</p>
            <h2>把活動講成可以被記住的四幕</h2>
          </div>
          <div class="stamp">四幕<br>導覽</div>
        </div>
        <p class="lead">這一頁把照片從素材清單拉回活動語境：入山、宿點、高山段與短停觀察。每一幕只回答一件事：隊伍現在要記住什麼。</p>
        {visual_story_arc}
      </div>
    </section>

    <section class="slide" id="visual-anchors">
      <div class="slide-inner">
        <div class="slide-head">
          <div>
            <p class="kicker">照片路標</p>
            <h2>把照片綁到路線點與簡報段落</h2>
          </div>
        </div>
        <p class="lead">同一張照片如果沒有位置脈絡，只是裝飾；這裡把圖片註記對到路線點、住宿節點、稜線展望或路線總覽，讓隊伍知道每張圖該支撐哪一段討論。</p>
        <div class="visual-anchor-board">{visual_anchor_cards}</div>
      </div>
    </section>

    <section class="slide" id="story-wall">
      <div class="slide-inner">
        <div class="slide-head">
          <div>
            <p class="kicker">路線故事牆</p>
            <h2>先讓隊伍記住畫面，再講資料</h2>
          </div>
          <div class="stamp">故事<br>導覽</div>
        </div>
        <p class="lead">把同一批行前資料翻成活動簡報語言：每一層只留一張主畫面、一句提醒，以及現地可以問隊伍的問題。</p>
        {story_wall}
      </div>
    </section>

    {chapter_see_route}

    <section class="slide source-debug-slide" id="status-data">
      <div class="slide-inner">
        <div class="slide-head">
          <div>
            <p class="kicker">資料現況</p>
            <h2>先看來源現況，再排行程</h2>
          </div>
        </div>
        <p class="lead">這份簡報由 workspace cache 與 operator-approved source collection 組成。Scout AI 回答時應優先揭露來源可用性、缺口與 stale risk，而不是把缺資料解讀成安全。</p>
        <p class="mode-note">這個區塊預設只在資料模式顯示。</p>
        {source_health_panel}
      </div>
    </section>

    <section class="slide" id="route">
      <div class="slide-inner">
        <div class="slide-head">
          <div>
            <p class="kicker">路線閱讀</p>
            <h2>先把路線讀成一張行走地圖</h2>
          </div>
        </div>
        <p class="lead">這一頁先讓隊伍抓住三件事：整趟路的節奏、哪些點會改變行程判斷、哪些地方只適合提問而不是直接下結論。</p>
        {map_atlas}
        {route_visual}
        <div class="route-grid">{route_steps}</div>
      </div>
    </section>

    <section class="slide" id="sights">
      <div class="slide-inner">
        <div class="slide-head">
          <div>
            <p class="kicker">沿途導覽</p>
            <h2>沿途停看聽導覽卡</h2>
          </div>
        </div>
        <p class="lead">這一頁不是景點清單，而是行前講解順序：每個點都要回答看什麼、問什麼，以及什麼條件下不能停留。</p>
        <section class="highlight-wall">{highlight_cards}</section>
      </div>
    </section>

    {chapter_context}

    <section class="slide" id="layers">
      <div class="slide-inner">
        <div class="slide-head">
          <div>
            <p class="kicker">脈絡層</p>
            <h2>把路線拆成六個脈絡層</h2>
          </div>
        </div>
        <p class="lead">這個章節對應你的提示詞：歷史層、文化層、自然層、地形層、季節層與觀察點。每張卡只引用已整理進行前包的資料。</p>
        <p class="deck-hint">簡報節奏：每次只講一層脈絡，避免把六層資料一次塞滿畫面。</p>
        <div class="briefing-deck layers" aria-label="六個路線脈絡層">{layer_cards}</div>
      </div>
    </section>

    <section class="slide" id="p2">
      <div class="slide-inner">
        <div class="slide-head">
          <div>
            <p class="kicker">Scout 自有脈絡</p>
            <h2>把完成旅程變成下一次的路線脈絡</h2>
          </div>
        </div>
        <p class="lead">公開來源回答外界如何描述這條路線；Scout 回顧回答實際走過後，這條路對這個隊伍代表什麼。未審核的回顧只作內部線索，公開前要再確認。</p>
        {p2_cards}
      </div>
    </section>

    <section class="slide" id="storyline">
      <div class="slide-inner">
        <div class="slide-head">
          <div>
            <p class="kicker">敘事線</p>
            <h2>把主要點串成行前敘事線</h2>
          </div>
        </div>
        <p class="lead">若路線距離可用，點位會依距離排序；否則依行前重要性與標籤排序。Scout 不能用這條敘事線取代導航或安全判斷。</p>
        <p class="deck-hint">路線敘事節奏：一次看一個節點，先抓距離與共同畫面，再講現地提醒。</p>
        <div class="storyline-rail" aria-label="路線敘事節點">{_briefing_story_steps(route_points[:12], media_manifest)}</div>
      </div>
    </section>

    {chapter_field}

    <section class="slide" id="stops">
      <div class="slide-inner">
        <div class="slide-head">
          <div>
            <p class="kicker">短停觀察</p>
            <h2>哪些點值得停 3 分鐘？</h2>
          </div>
          <div class="stamp">非停留<br>授權</div>
        </div>
        <p class="lead">3 分鐘觀察點必須再交給 contextual permission 檢查：當下天氣、能見度、地形暴露、隊伍間距、疲勞與撤退時間不通過時，Scout 應回答快速通過或不要停留。</p>
        <p class="deck-hint">短停節奏：一次只討論一個點，先看畫面，再看觀察重點、隊伍提問與離開條件。</p>
        <div class="briefing-deck stop-deck" aria-label="三分鐘觀察點">{stop_cards}</div>
      </div>
    </section>

    <section class="slide" id="risk">
      <div class="slide-inner">
        <div class="slide-head">
          <div>
            <p class="kicker">風險審查</p>
            <h2>風險、缺口與人工審查</h2>
          </div>
        </div>
        <p class="lead">這個區塊只做行前審查提醒。簡報模式先講行動策略；資料模式才展開候選點、邊界與資料缺口。</p>
        <div class="risk-review-grid">{risk_cards}</div>
      </div>
    </section>

    <section class="slide" id="schedule">
      <div class="slide-inner">
        <div class="slide-head">
          <div>
            <p class="kicker">行程決策</p>
            <h2>出發前行程審查板</h2>
          </div>
        </div>
        <p class="lead">這裡不是替領隊自動決定，而是把 2 天、3 天與壓縮行程放到同一張人工審查板：先看條件是否成立，再選版本。</p>
        {schedule_cards}
      </div>
    </section>

    {chapter_sources}

    <section class="slide" id="sources">
      <div class="slide-inner">
        <div class="slide-head">
          <div>
            <p class="kicker">來源追溯</p>
            <h2>這份簡報可以信任到什麼程度？</h2>
          </div>
        </div>
        <p class="lead">先看資料能支撐哪些結論，再看完整來源追溯。領隊要能看懂哪些內容已整理好、哪些地方還要回頭確認。</p>
        {source_tier_spine}
        {source_trust_panel}
        <p class="mode-note">完整來源表、收集線索與機器可讀邊界保留在資料模式。</p>
        <details class="source-details">
          <summary>展開完整來源表與 crawl seed</summary>
          <table>
            <thead><tr><th>來源</th><th>層級</th><th>狀態</th><th>數量</th><th>用途</th></tr></thead>
            <tbody>{source_rows}</tbody>
          </table>
          <h3>路線筆記 seed policy</h3>
          <p>路線筆記只作為收集線索；簡報結論應來自公開來源收集結果，或已審核的 Scout 自有回顧。</p>
          <ol>{seed_items}</ol>
          <h3>Source tier catalog</h3>
          <ul>{tier_items}</ul>
        </details>
      </div>
    </section>
  </main>
  <script>
    (() => {{
      const buttons = Array.from(document.querySelectorAll('[data-briefing-mode]'));
      const navLinks = Array.from(document.querySelectorAll('nav a[href^="#"]'));
      const presenterButtons = Array.from(document.querySelectorAll('[data-presenter-step]'));
      const activeLabels = Array.from(document.querySelectorAll('[data-active-section-label]'));
      const activeCounts = Array.from(document.querySelectorAll('[data-active-section-count]'));
      let presenterLockUntil = 0;
      const mobilePresenterDock = document.querySelector('.mobile-presenter-dock');
      const sectionFor = (link) => {{
        const id = (link.getAttribute('href') || '').slice(1);
        return id ? document.getElementById(id) : null;
      }};
      const isVisibleLink = (link) => {{
        const style = window.getComputedStyle(link);
        return style.display !== 'none' && style.visibility !== 'hidden';
      }};
      const visibleNavLinks = () => navLinks.filter(isVisibleLink);
      const activeNavThreshold = () => {{
        const nav = document.querySelector('nav');
        const navHeight = nav ? nav.getBoundingClientRect().height : 72;
        const dockHeight = (
          mobilePresenterDock && window.getComputedStyle(mobilePresenterDock).display !== 'none'
        )
          ? mobilePresenterDock.getBoundingClientRect().height
          : 0;
        return navHeight + dockHeight + 40;
      }};
      const setActiveLink = (link, visibleLinks) => {{
        navLinks.forEach((item) => item.removeAttribute('aria-current'));
        if (!link) {{
          return;
        }}
        link.setAttribute('aria-current', 'true');
        const visible = visibleLinks && visibleLinks.length ? visibleLinks : visibleNavLinks();
        const index = Math.max(0, visible.indexOf(link));
        activeLabels.forEach((label) => {{
          label.textContent = link.textContent.trim();
        }});
        activeCounts.forEach((count) => {{
          count.textContent = `${{index + 1}} / ${{Math.max(1, visible.length)}}`;
        }});
        presenterButtons.forEach((button) => {{
          const step = Number(button.dataset.presenterStep || 0);
          button.disabled = (step < 0 && index <= 0) || (step > 0 && index >= visible.length - 1);
        }});
      }};
      const goToRelativeSection = (delta) => {{
        const visible = visibleNavLinks();
        if (!visible.length) {{
          return;
        }}
        const current = document.querySelector('nav a[aria-current="true"]');
        const currentIndex = Math.max(0, visible.indexOf(current));
        const nextIndex = Math.min(visible.length - 1, Math.max(0, currentIndex + delta));
        const target = visible[nextIndex];
        const section = sectionFor(target);
        if (!section || nextIndex === currentIndex) {{
          setActiveLink(target, visible);
          return;
        }}
        presenterLockUntil = Date.now() + 900;
        section.scrollIntoView({{ block: 'start', behavior: 'smooth' }});
        setActiveLink(target, visible);
        window.setTimeout(() => {{
          presenterLockUntil = 0;
          updateActiveNav();
        }}, 920);
      }};
      const updateActiveNav = () => {{
        if (Date.now() < presenterLockUntil) {{
          return;
        }}
        const visible = visibleNavLinks();
        if (!visible.length) {{
          return;
        }}
        const nearBottom = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4;
        if (nearBottom) {{
          setActiveLink(visible[visible.length - 1], visible);
          return;
        }}
        let active = visible[0];
        const threshold = activeNavThreshold();
        for (const link of visible) {{
          const section = sectionFor(link);
          if (!section) {{
            continue;
          }}
          const top = section.getBoundingClientRect().top;
          if (top <= threshold) {{
            active = link;
          }}
        }}
        setActiveLink(active, visible);
      }};
      let activeNavFrame = 0;
      const scheduleActiveNav = () => {{
        if (activeNavFrame) {{
          return;
        }}
        activeNavFrame = window.requestAnimationFrame(() => {{
          activeNavFrame = 0;
          updateActiveNav();
        }});
      }};
      const applyMode = (mode) => {{
        const normalized = mode === 'data' ? 'data' : 'briefing';
        document.body.classList.toggle('mode-data', normalized === 'data');
        document.body.classList.toggle('mode-briefing', normalized !== 'data');
        buttons.forEach((button) => {{
          button.setAttribute('aria-pressed', String(button.dataset.briefingMode === normalized));
        }});
        scheduleActiveNav();
      }};
      buttons.forEach((button) => {{
        button.addEventListener('click', () => applyMode(button.dataset.briefingMode));
      }});
      presenterButtons.forEach((button) => {{
        button.addEventListener('click', () => {{
          goToRelativeSection(Number(button.dataset.presenterStep || 0));
        }});
      }});
      navLinks.forEach((link) => {{
        link.addEventListener('click', (event) => {{
          const visible = visibleNavLinks();
          if (!visible.includes(link)) {{
            return;
          }}
          const section = sectionFor(link);
          if (!section) {{
            return;
          }}
          event.preventDefault();
          presenterLockUntil = Date.now() + 350;
          const root = document.documentElement;
          const previousScrollBehavior = root.style.scrollBehavior;
          root.style.scrollBehavior = 'auto';
          const targetTop = Math.max(
            0,
            window.scrollY + section.getBoundingClientRect().top - activeNavThreshold() + 12
          );
          window.scrollTo(0, targetTop);
          root.style.scrollBehavior = previousScrollBehavior;
          if (window.location.hash !== link.hash) {{
            window.history.pushState(null, '', link.hash);
          }}
          setActiveLink(link, visible);
          window.setTimeout(() => {{
            presenterLockUntil = 0;
            updateActiveNav();
          }}, 360);
        }});
      }});
      window.addEventListener('scroll', scheduleActiveNav, {{ passive: true }});
      window.addEventListener('resize', scheduleActiveNav);
      applyMode('briefing');
      updateActiveNav();
    }})();
  </script>
</body>
</html>
"""


def _build_media_manifest(
    *,
    project_id: str,
    generated_at: str,
    route_keywords: list[str],
    web_payload: dict[str, Any],
    web_ref: str,
    route_summary: dict[str, Any],
    points: list[dict[str, Any]],
    boundary: dict[str, Any],
) -> dict[str, Any]:
    raw_images = _media_items_from_web_case_evidence(web_payload, web_ref)
    curation = _curate_media_items_for_briefing(raw_images)
    images = _anchor_media_items_to_route_points(curation["images"], points)
    image_curation = _media_curation_summary(images, curation)
    visual_kit = _media_visual_kit(images)
    hero_image = images[0] if images else None
    anchored_media_count = sum(
        1 for image in images if isinstance(image.get("presentation_anchor"), dict)
    )
    route_point_media_count = sum(
        1
        for image in images
        if isinstance(image.get("presentation_anchor"), dict)
        and image["presentation_anchor"].get("anchor_kind") == "route_point"
    )
    return {
        "artifact_kind": ROUTE_CONTEXT_MEDIA_MANIFEST_ARTIFACT_KIND,
        "schema_version": ROUTE_CONTEXT_SCHEMA_VERSION,
        "project_id": project_id,
        "generated_at": generated_at,
        "route_keywords": route_keywords,
        "route_summary": {
            "distance_m": route_summary.get("distance_m"),
            "point_count": route_summary.get("point_count"),
            "raw_route_points_embedded": False,
        },
        "source_evidence_ref": web_ref,
        "media_count": len(images),
        "available_media_count": curation["available_media_count"],
        "deduped_media_count": curation["deduped_media_count"],
        "duplicate_media_count": curation["duplicate_media_count"],
        "overflow_media_count": curation["overflow_media_count"],
        "anchored_media_count": anchored_media_count,
        "route_point_media_count": route_point_media_count,
        "hero_image": hero_image,
        "gallery_images": images[:BRIEFING_MEDIA_GALLERY_LIMIT],
        "gallery_image_limit": BRIEFING_MEDIA_GALLERY_LIMIT,
        "images": images,
        "image_curation": image_curation,
        "visual_readiness": image_curation["visual_readiness"],
        "visual_kit": visual_kit,
        "visual_kit_ready_count": visual_kit["ready_count"],
        "visual_kit_missing_count": visual_kit["missing_count"],
        "design_policy": {
            "presentation_variant": "photo_led_route_briefing",
            "prefer_real_source_assets": True,
            "raw_image_embedded": False,
            "show_media_gap_when_empty": True,
            "provenance_visible": True,
            "target_min_gallery_images": BRIEFING_TARGET_MIN_GALLERY_IMAGES,
            "target_max_gallery_images": BRIEFING_MEDIA_GALLERY_LIMIT,
        },
        "point_label_count": len({_point_label(point) for point in points}),
        "boundary": {
            **boundary,
            "raw_image_embedded": False,
            "remote_image_fetch_performed_by_collector": False,
        },
    }


def _media_items_from_web_case_evidence(
    payload: dict[str, Any],
    source_ref: str,
) -> list[dict[str, Any]]:
    records = _list_from_any(payload, ("points", "evidence_items", "candidates", "evidence", "cases"))
    images: list[dict[str, Any]] = []
    for raw in records:
        if not isinstance(raw, dict):
            continue
        image_refs = raw.get("image_refs")
        if not isinstance(image_refs, list):
            continue
        for index, image in enumerate(image_refs):
            if not isinstance(image, dict):
                continue
            url = str(image.get("url") or image.get("src") or "").strip()
            if not url or not url.startswith(("http://", "https://")):
                continue
            caption = _first_text(
                image.get("caption"),
                image.get("alt"),
                image.get("title"),
                raw.get("label"),
                raw.get("title"),
            )
            alt = _first_text(image.get("alt"), caption)
            if not _is_briefing_content_image(
                url=url,
                caption=caption,
                alt=alt,
                title=image.get("title"),
                page_url=_first_text(image.get("page_url"), raw.get("url")),
            ):
                continue
            source_tier = _first_text(image.get("source_tier"), raw.get("source_tier"), "P1")
            source_family = _first_text(
                image.get("source_family"),
                raw.get("source_family"),
                "web_case_evidence",
            )
            context_layer = _first_text(
                image.get("context_layer"),
                image.get("sec6_layer"),
                raw.get("context_layer"),
            )
            images.append(
                {
                    "media_id": _candidate_id(
                        "route_context_media",
                        "web_case_evidence",
                        f"{raw.get('candidate_id') or raw.get('id') or 'image'}.{index}",
                    ),
                    "url": url,
                    "caption": caption[:160],
                    "alt": alt[:120],
                    "source_tier": source_tier,
                    "source_family": source_family,
                    "context_layer": context_layer,
                    "page_url": _first_text(image.get("page_url"), raw.get("url")),
                    "source_ref": source_ref,
                    "candidate_only": True,
                    "requires_human_review": True,
                    "runtime_safety_truth": False,
                    "raw_image_embedded": False,
                }
            )
            if len(images) >= BRIEFING_MEDIA_GALLERY_LIMIT * 3:
                return images
    return images


def _is_briefing_content_image(
    *,
    url: str,
    caption: Any,
    alt: Any,
    title: Any,
    page_url: Any,
) -> bool:
    """Return true for route/content imagery and false for page chrome assets."""

    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    path = unquote(parsed.path or "").lower()
    netloc = parsed.netloc.lower()
    text = " ".join(
        str(value or "").strip().lower()
        for value in (caption, alt, title, page_url, path)
        if str(value or "").strip()
    )
    if netloc in {"www.facebook.com", "facebook.com", "sb.scorecardresearch.com"}:
        return False
    if any(token in netloc for token in ("doubleclick", "googlesyndication", "google-analytics")):
        return False
    if path.endswith((".svg", ".gif", ".ico")):
        return False
    if not path.endswith((".jpg", ".jpeg", ".png", ".webp")):
        return False
    if re.search(r"(^|/)(icon|icons|logo|logos|sprite|avatar|badge)(/|_|-|\.)", path):
        return False
    if any(
        marker in path
        for marker in (
            "/image/icon/",
            "/image/web-logo/",
            "/attachments/logo/",
            "/assets/images/logo",
            "/assets/images/file_exticon/",
            "/image/edu/",
            "/img/logo",
            "/default_avatar",
            "/web_structure/2503506/",
            "scorecardresearch",
            "facebook.com/tr",
        )
    ):
        return False
    if any(
        phrase in text
        for phrase in (
            "選單",
            "關閉",
            "搜尋",
            "登入",
            "登出",
            "語言切換",
            "facebook",
            "line",
            "森療",
            "野生物方程式",
            "我的e政府",
            "無障礙",
            "預設頭像",
            "標示",
            "logotype",
            "logo",
            "icon",
            "button",
            "tracking",
            "pixel",
        )
    ):
        return False
    return True


def _curate_media_items_for_briefing(
    raw_images: list[dict[str, Any]],
) -> dict[str, Any]:
    available = []
    for index, image in enumerate(raw_images):
        url = str(image.get("url") or "").strip()
        if not url:
            continue
        item = dict(image)
        item["source_index"] = index
        item["dedupe_key"] = _media_dedupe_key(url)
        available.append(item)

    deduped: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    duplicate_count = 0
    for image in available:
        key = str(image.get("dedupe_key") or image.get("url") or "")
        if key in seen_keys:
            duplicate_count += 1
            continue
        seen_keys.add(key)
        deduped.append(image)

    selected: list[dict[str, Any]] = []
    selected_keys: set[str] = set()
    for layer in BRIEFING_CONTEXT_LAYER_ORDER:
        layer_candidates = [
            image
            for image in deduped
            if str(image.get("context_layer") or "") == layer
            and str(image.get("dedupe_key") or "") not in selected_keys
        ]
        if not layer_candidates:
            continue
        best = min(layer_candidates, key=_media_priority_tuple)
        selected.append(best)
        selected_keys.add(str(best.get("dedupe_key") or best.get("url") or ""))

    remaining = [
        image
        for image in deduped
        if str(image.get("dedupe_key") or "") not in selected_keys
    ]
    for image in sorted(remaining, key=_media_priority_tuple):
        if len(selected) >= BRIEFING_MEDIA_GALLERY_LIMIT:
            break
        selected.append(image)
        selected_keys.add(str(image.get("dedupe_key") or image.get("url") or ""))

    for rank, image in enumerate(selected, start=1):
        image["briefing_media_rank"] = rank
        image["selected_for_briefing"] = True

    return {
        "images": selected,
        "available_media_count": len(available),
        "deduped_media_count": len(deduped),
        "duplicate_media_count": duplicate_count,
        "overflow_media_count": max(0, len(deduped) - len(selected)),
    }


def _media_priority_tuple(image: dict[str, Any]) -> tuple[int, int, int, int]:
    tier_order = {"P0": 0, "P1": 1, "P2": 2}
    tier = str(image.get("source_tier") or "").upper()
    layer = str(image.get("context_layer") or "")
    caption = str(image.get("caption") or image.get("alt") or "")
    return (
        tier_order.get(tier, 3),
        BRIEFING_CONTEXT_LAYER_ORDER.index(layer)
        if layer in BRIEFING_CONTEXT_LAYER_ORDER
        else len(BRIEFING_CONTEXT_LAYER_ORDER),
        0 if len(caption.strip()) >= 4 else 1,
        int(image.get("source_index") or 0),
    )


def _media_dedupe_key(url: str) -> str:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return url.strip()
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path,
            "",
            "",
        )
    )


def _media_curation_summary(
    images: list[dict[str, Any]],
    curation: dict[str, Any],
) -> dict[str, Any]:
    layer_counts = _media_layer_counts(images)
    covered_layers = [
        layer
        for layer in BRIEFING_CONTEXT_LAYER_ORDER
        if int(layer_counts.get(layer) or 0) > 0
    ]
    missing_layers = [
        layer
        for layer in BRIEFING_CONTEXT_LAYER_ORDER
        if int(layer_counts.get(layer) or 0) <= 0
    ]
    selected_count = len(images)
    if selected_count >= BRIEFING_TARGET_MIN_GALLERY_IMAGES and not missing_layers:
        status = "rich"
        recommendation = "公開簡報已有足夠圖像素材，可優先調整敘事與章節節奏。"
    elif selected_count >= len(BRIEFING_CONTEXT_LAYER_ORDER) and not missing_layers:
        status = "usable"
        recommendation = "圖像已覆蓋主要脈絡層；若要更像活動簡報，建議補到 12 張以上。"
    elif selected_count > 0:
        status = "thin"
        recommendation = "目前可出簡報，但缺少部分脈絡層圖片，畫面容易重複或偏資料化。"
    else:
        status = "missing"
        recommendation = "缺少可追溯圖片，請先匯入 operator-approved P0/P1 圖片或已審核的 P2 照片。"
    visual_readiness = _media_visual_readiness_summary(
        status=status,
        selected_count=selected_count,
        covered_layers=covered_layers,
        missing_layers=missing_layers,
        recommendation=recommendation,
    )
    return {
        "coverage_status": status,
        "selected_media_count": selected_count,
        "available_media_count": curation["available_media_count"],
        "deduped_media_count": curation["deduped_media_count"],
        "duplicate_media_count": curation["duplicate_media_count"],
        "overflow_media_count": curation["overflow_media_count"],
        "target_min_gallery_images": BRIEFING_TARGET_MIN_GALLERY_IMAGES,
        "target_max_gallery_images": BRIEFING_MEDIA_GALLERY_LIMIT,
        "target_context_layers": list(BRIEFING_CONTEXT_LAYER_ORDER),
        "covered_context_layers": covered_layers,
        "missing_context_layers": missing_layers,
        "by_context_layer": layer_counts,
        "recommendation": recommendation,
        "visual_readiness": visual_readiness,
        "missing_image_count_to_target": visual_readiness["missing_image_count_to_target"],
        "presentation_ready": visual_readiness["presentation_ready"],
    }


def _media_visual_readiness_summary(
    *,
    status: str,
    selected_count: int,
    covered_layers: list[str],
    missing_layers: list[str],
    recommendation: str,
) -> dict[str, Any]:
    target_layer_count = len(BRIEFING_CONTEXT_LAYER_ORDER)
    missing_image_count = max(0, BRIEFING_TARGET_MIN_GALLERY_IMAGES - selected_count)
    layer_coverage_ratio = (
        round(len(covered_layers) / target_layer_count, 3)
        if target_layer_count
        else 0
    )
    labels = {
        "rich": "畫面充足",
        "usable": "脈絡完整",
        "thin": "畫面偏薄",
        "missing": "缺少圖片",
    }
    gates = {
        "rich": "pass",
        "usable": "warn_top_up_images",
        "thin": "warn_missing_layers",
        "missing": "block_visual_briefing",
    }
    next_actions = []
    if missing_layers:
        missing_labels = "、".join(_context_layer_display_label(layer) for layer in missing_layers)
        next_actions.append(f"補齊 {missing_labels} 的可追溯照片")
    if missing_image_count:
        next_actions.append(f"再補 {missing_image_count} 張，讓公開簡報至少有 {BRIEFING_TARGET_MIN_GALLERY_IMAGES} 張圖")
    if not next_actions:
        next_actions.append("圖像素材已可支撐公開簡報，下一步可調整章節節奏與講者提示")
    return {
        "status": status,
        "label": labels.get(status, status),
        "quality_gate": gates.get(status, "warn_review_needed"),
        "presentation_ready": status in {"rich", "usable"},
        "selected_media_count": selected_count,
        "target_min_gallery_images": BRIEFING_TARGET_MIN_GALLERY_IMAGES,
        "missing_image_count_to_target": missing_image_count,
        "covered_context_layer_count": len(covered_layers),
        "target_context_layer_count": target_layer_count,
        "context_layer_coverage_ratio": layer_coverage_ratio,
        "covered_context_layers": covered_layers,
        "missing_context_layers": missing_layers,
        "recommendation": recommendation,
        "next_actions": next_actions,
    }


def _media_visual_kit(images: list[dict[str, Any]]) -> dict[str, Any]:
    used_keys: set[str] = set()
    slots = []
    for spec in _visual_kit_slot_specs():
        image = _media_visual_kit_match(images, spec, used_keys)
        image_summary = _media_manifest_image_summary(image) if image else None
        if image:
            used_keys.add(str(image.get("dedupe_key") or image.get("url") or ""))
        status = "ready" if image else "missing"
        slots.append(
            {
                "slot_id": spec["slot_id"],
                "label": spec["label"],
                "briefing_role": spec["briefing_role"],
                "speaker_question": spec["speaker_question"],
                "target_context_layers": list(spec["context_layers"]),
                "status": status,
                "image": image_summary,
                "missing_action": spec["missing_action"] if status == "missing" else None,
                "candidate_only": True,
                "requires_human_review": True,
                "runtime_safety_truth": False,
            }
        )
    ready_count = sum(1 for slot in slots if slot["status"] == "ready")
    return {
        "slot_count": len(slots),
        "ready_count": ready_count,
        "missing_count": len(slots) - ready_count,
        "slots": slots,
        "candidate_only": True,
        "requires_human_review": True,
        "runtime_safety_truth": False,
    }


def _visual_kit_slot_specs() -> list[dict[str, Any]]:
    return [
        {
            "slot_id": "route_cover",
            "label": "開場主視覺",
            "briefing_role": "先讓隊伍看見這趟路的氣質，建立共同方向感。",
            "speaker_question": "這趟路給隊伍的第一個印象是什麼？",
            "context_layers": ("route_overview",),
            "context_kinds": ("route_overview",),
            "keywords": ("能高越嶺", "高山景觀", "稜線", "遠景"),
            "missing_action": "補一張可公開的路線遠景或入口主視覺。",
        },
        {
            "slot_id": "route_map",
            "label": "路線總覽圖",
            "briefing_role": "確認路線形狀、方向與主要節點，不讓隊伍只記得照片。",
            "speaker_question": "隊伍能不能用這張圖說出今天的主線方向？",
            "context_layers": ("route_overview",),
            "context_kinds": ("route_overview",),
            "keywords": ("導覽圖", "地圖", "map", "路線總覽"),
            "missing_action": "補一張官方或可追溯的路線圖、入口導覽圖或 GPX 總覽圖。",
        },
        {
            "slot_id": "lodging_nodes",
            "label": "宿點與中繼節點",
            "briefing_role": "把山屋、保線所、補水或撤退節點先放進共同記憶。",
            "speaker_question": "晚到時，哪個節點會變成第一個重新決策點？",
            "context_layers": ("historical",),
            "context_kinds": ("resource_context",),
            "keywords": ("山莊", "保線所", "宿", "營地", "補給", "撤退"),
            "missing_action": "補山屋、保線所、營地或中繼休息點照片。",
        },
        {
            "slot_id": "terrain_passage",
            "label": "地形與通過策略",
            "briefing_role": "把稜線、風口、坡面與展望點轉成通過策略。",
            "speaker_question": "這裡是適合停留，還是應該快速通過？",
            "context_layers": ("terrain",),
            "context_kinds": ("terrain_context", "viewpoint_context"),
            "keywords": ("稜線", "風口", "坡", "崩", "碎石", "展望"),
            "missing_action": "補一張能看出坡面、稜線、風口或暴露感的照片。",
        },
        {
            "slot_id": "three_minute_stop",
            "label": "3 分鐘觀察點",
            "briefing_role": "讓漂亮畫面轉成短停目的、站位與離開條件。",
            "speaker_question": "停 3 分鐘後，隊伍要帶走哪個判斷？",
            "context_layers": ("observation_point",),
            "context_kinds": ("viewpoint_context",),
            "keywords": ("光被八表", "日出", "雲海", "觀察", "短停", "展望"),
            "missing_action": "補一張可說明站位、展望與離開方向的短停畫面。",
        },
        {
            "slot_id": "weather_season",
            "label": "天候與季節畫面",
            "briefing_role": "把雲霧、雨季、低溫、芒草或林相變化連回時間壓力。",
            "speaker_question": "如果天氣提早變差，這張圖提醒我們哪個條件要重查？",
            "context_layers": ("seasonal", "natural"),
            "context_kinds": ("seasonal_context", "natural_context", "viewpoint_context"),
            "keywords": ("雲海", "雨", "霧", "低溫", "芒草", "花", "林相", "溪流"),
            "missing_action": "補一張季節、雲霧、低溫、雨後或林相變化照片。",
        },
    ]


def _media_visual_kit_match(
    images: list[dict[str, Any]],
    spec: dict[str, Any],
    used_keys: set[str],
) -> dict[str, Any] | None:
    unused = [
        image
        for image in images
        if str(image.get("dedupe_key") or image.get("url") or "") not in used_keys
    ]
    exact = [image for image in unused if _media_matches_visual_kit_slot(image, spec)]
    if exact:
        return min(exact, key=_media_priority_tuple)
    return None


def _media_matches_visual_kit_slot(image: dict[str, Any], spec: dict[str, Any]) -> bool:
    context_layers = {str(layer) for layer in spec.get("context_layers", ())}
    if str(image.get("context_layer") or "") in context_layers:
        return True
    anchor = image.get("presentation_anchor")
    if isinstance(anchor, dict):
        context_kinds = {str(kind) for kind in spec.get("context_kinds", ())}
        if str(anchor.get("context_kind") or "") in context_kinds:
            return True
    text = _media_search_text(image)
    return any(str(keyword) and str(keyword) in text for keyword in spec.get("keywords", ()))


def _media_manifest_image_summary(image: dict[str, Any]) -> dict[str, Any]:
    anchor = image.get("presentation_anchor")
    return {
        "media_id": image.get("media_id"),
        "url": image.get("url"),
        "caption": image.get("caption"),
        "alt": image.get("alt"),
        "source_tier": image.get("source_tier"),
        "source_family": image.get("source_family"),
        "context_layer": image.get("context_layer"),
        "presentation_anchor": anchor if isinstance(anchor, dict) else None,
        "candidate_only": True,
        "requires_human_review": True,
        "runtime_safety_truth": False,
    }


def _context_layer_display_label(layer: str) -> str:
    labels = {
        "route_overview": "路線總覽",
        "historical": "歷史層",
        "cultural": "文化層",
        "natural": "自然層",
        "terrain": "地形層",
        "seasonal": "季節層",
        "observation_point": "觀察點",
    }
    return labels.get(layer, layer or "未分類")


def _media_layer_counts(images: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for image in images:
        layer = str(image.get("context_layer") or "unspecified")
        counts[layer] = counts.get(layer, 0) + 1
    return dict(sorted(counts.items()))


def _anchor_media_items_to_route_points(
    images: list[dict[str, Any]],
    points: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    route_points = _route_ordered_points(points)
    anchored: list[dict[str, Any]] = []
    for image in images:
        enriched = dict(image)
        enriched["presentation_anchor"] = _media_presentation_anchor(enriched, route_points)
        anchored.append(enriched)
    return anchored


def _media_presentation_anchor(
    image: dict[str, Any],
    route_points: list[dict[str, Any]],
) -> dict[str, Any]:
    text = _media_search_text(image)
    explicit_anchor = _explicit_media_layer_anchor(image)
    if explicit_anchor:
        return explicit_anchor
    for point in route_points:
        label = _point_label(point).strip()
        if len(label) >= 3 and label in text:
            return {
                "anchor_kind": "route_point",
                "label": label,
                "route_point_candidate_id": point.get("candidate_id"),
                "distance_m": point.get("distance_m"),
                "distance_label": _point_distance_label(point),
                "context_kind": point.get("context_kind"),
                "context_layer": image.get("context_layer") or None,
                "match_reason": "caption_or_alt_contains_route_point_label",
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
    return _inferred_media_section_anchor(text)


def _media_search_text(image: dict[str, Any]) -> str:
    return " ".join(
        str(image.get(key) or "")
        for key in ("caption", "alt", "context_layer", "url", "page_url", "source_family")
    )


def _explicit_media_layer_anchor(image: dict[str, Any]) -> dict[str, Any] | None:
    layer = str(image.get("context_layer") or "").strip()
    if not layer:
        return None
    anchors = {
        "historical": ("歷史層 / 舊路與人為設施", "historical_context"),
        "cultural": ("文化層 / 地名與路徑脈絡", "cultural_context"),
        "natural": ("自然層 / 林相與生態觀察", "natural_context"),
        "terrain": ("地形層 / 稜線與坡面判讀", "terrain_context"),
        "seasonal": ("季節層 / 天候與時間感", "seasonal_context"),
        "observation_point": ("觀察點 / 三分鐘短停", "viewpoint_context"),
        "route_overview": ("路線總覽 / 導覽圖", "route_overview"),
    }
    label, context_kind = anchors.get(layer, (f"{layer} / 視覺脈絡", "visual_context"))
    return {
        "anchor_kind": "route_section",
        "label": label,
        "context_kind": context_kind,
        "context_layer": layer,
        "match_reason": "operator_supplied_context_layer",
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _inferred_media_section_anchor(text: str) -> dict[str, Any]:
    lowered = text.lower()
    if "天池" in text or "山莊" in text:
        label = "天池山莊 / 住宿與行程節點"
        context_kind = "resource_context"
        reason = "caption_or_alt_indicates_lodge_or_camp"
    elif "光被八表" in text:
        label = "光被八表 / 稜線展望"
        context_kind = "viewpoint_context"
        reason = "caption_or_alt_indicates_ridge_viewpoint"
    elif "導覽圖" in text or "map" in lowered or "地圖" in text:
        label = "路線總覽 / 導覽圖"
        context_kind = "route_overview"
        reason = "caption_or_alt_indicates_route_map"
    elif "能高越嶺" in text:
        label = "能高越嶺道 / 路線總覽"
        context_kind = "route_overview"
        reason = "caption_or_alt_indicates_route_level_context"
    else:
        label = "路線視覺素材"
        context_kind = "visual_context"
        reason = "media_available_without_route_point_match"
    return {
        "anchor_kind": "route_section",
        "label": label,
        "context_kind": context_kind,
        "match_reason": reason,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _briefing_hero_image(media_manifest: dict[str, Any]) -> dict[str, Any] | None:
    hero_image = media_manifest.get("hero_image")
    if isinstance(hero_image, dict) and hero_image.get("url"):
        return hero_image
    images = media_manifest.get("gallery_images")
    if isinstance(images, list):
        for image in images:
            if isinstance(image, dict) and image.get("url"):
                return image
    return None


def _briefing_hero_media(hero_image: dict[str, Any] | None) -> str:
    if not hero_image:
        return ""
    return (
        f"<img class=\"hero-photo\" src=\"{_h(hero_image.get('url'))}\" "
        f"alt=\"{_h(hero_image.get('alt') or hero_image.get('caption'))}\">"
    )


def _briefing_visual_agenda(
    *,
    media_manifest: dict[str, Any],
    route_distance_km: str,
    point_count: int,
) -> str:
    if not _briefing_media_images(media_manifest):
        return ""
    agenda_items = [
        {
            "href": "#days",
            "step": "01 / 天數結論",
            "title": "先決定節奏",
            "body": f"{route_distance_km} 先用 2 天 1 夜主案討論，再看是否需要 3 天 2 夜緩衝。",
            "context_kinds": ("route_overview", "resource_context"),
            "label_keywords": ("天池山莊", "能高越嶺道", "導覽圖"),
        },
        {
            "href": "#photo-essay",
            "step": "02 / 圖像導覽",
            "title": "先看畫面",
            "body": "用照片建立共同記憶，再把住宿、展望、日出與導覽圖放回行程節奏。",
            "context_kinds": ("viewpoint_context", "natural_context", "route_overview"),
            "label_keywords": ("高山景觀", "雲海", "日出", "光被八表"),
        },
        {
            "href": "#route",
            "step": "03 / 路線閱讀",
            "title": "讀成行走地圖",
            "body": f"{point_count} 個脈絡點先分清哪些要停、哪些要快通過、哪些只適合提問。",
            "context_kinds": ("route_overview", "visual_context"),
            "label_keywords": ("導覽圖", "路線總覽", "能高越嶺道"),
        },
        {
            "href": "#schedule",
            "step": "04 / 行程審查",
            "title": "留緩衝再出發",
            "body": "把山屋、天氣、隊伍腳程與撤退時間放在同一張圖上，不用壓縮版本當預設。",
            "context_kinds": ("resource_context", "route_overview", "viewpoint_context"),
            "label_keywords": ("天池山莊", "雲海保線所", "光被八表"),
        },
    ]
    used_image_urls: set[str] = set()
    cards = "\n".join(
        _briefing_visual_agenda_card(
            media_manifest,
            item,
            index=index,
            used_image_urls=used_image_urls,
        )
        for index, item in enumerate(agenda_items)
    )
    return f"""
  <section class="wrap visual-agenda" aria-label="簡報視覺議程">
    <div class="visual-agenda-copy">
      <p class="kicker">視覺議程</p>
      <h2>先用四張圖抓住簡報順序</h2>
      <p>這裡不是資料索引，而是帶隊伍進入簡報的入口：先講節奏，再看畫面，接著讀路線，最後才做行程審查。</p>
    </div>
    <div class="visual-agenda-grid">
      {cards}
    </div>
  </section>
    """


def _briefing_visual_agenda_card(
    media_manifest: dict[str, Any],
    item: dict[str, Any],
    *,
    index: int,
    used_image_urls: set[str],
) -> str:
    image = _briefing_visual_agenda_image(
        media_manifest,
        context_kinds=tuple(item.get("context_kinds", ())),
        label_keywords=tuple(item.get("label_keywords", ())),
        fallback_index=index,
        used_image_urls=used_image_urls,
    )
    if not image:
        return ""
    image_url = str(image.get("url") or "")
    if image_url:
        used_image_urls.add(image_url)
    caption = _first_text(image.get("caption"), image.get("alt"), item.get("title"))
    return (
        f"<a class=\"visual-agenda-card\" href=\"{_h(item.get('href'))}\">"
        f"<img loading=\"lazy\" src=\"{_h(image.get('url'))}\" alt=\"{_h(image.get('alt') or caption)}\">"
        "<span class=\"visual-agenda-body\">"
        f"<span class=\"visual-agenda-step\">{_h(item.get('step'))}</span>"
        f"<b>{_h(item.get('title'))}</b>"
        f"<span>{_h(item.get('body'))}</span>"
        f"{_briefing_media_source_chips(image)}"
        "</span>"
        "</a>"
    )


def _briefing_visual_agenda_image(
    media_manifest: dict[str, Any],
    *,
    context_kinds: tuple[str, ...],
    label_keywords: tuple[str, ...],
    fallback_index: int,
    used_image_urls: set[str],
) -> dict[str, Any] | None:
    images = _briefing_media_images(media_manifest)
    if not images:
        return None
    preferred: list[dict[str, Any]] = []
    for image in images:
        anchor = image.get("presentation_anchor")
        if not isinstance(anchor, dict):
            anchor = {}
        context = str(anchor.get("context_kind") or "")
        label = _media_search_text(image) + " " + str(anchor.get("label") or "")
        if label_keywords and any(keyword in label for keyword in label_keywords):
            preferred.append(image)
            continue
        if context_kinds and context in context_kinds:
            preferred.append(image)
    start = fallback_index % len(images)
    rotated = images[start:] + images[:start]
    candidates = preferred + [image for image in rotated if image not in preferred]
    for image in candidates:
        url = str(image.get("url") or "")
        if url and url not in used_image_urls:
            return image
    return candidates[0] if candidates else None


def _briefing_media_band(media_manifest: dict[str, Any]) -> str:
    images = [
        image
        for image in media_manifest.get("gallery_images", [])
        if isinstance(image, dict) and image.get("url")
    ]
    if not images:
        return """
        <div class="media-gap">
          <p class="kicker">圖像缺口</p>
          <h2>目前缺少可呈現的路線照片</h2>
          <p>這不是版型限制，而是還缺可追溯照片。請先匯入已核准的官方或可信來源圖片，或已審核的 Scout 自有照片；簡報會自動把可追溯圖片放進版面。</p>
        </div>
        """
    primary = images[0]
    grid = "\n".join(_briefing_photo_figure(image) for image in images[1:5])
    if not grid:
        grid = _briefing_photo_figure(primary)
    return f"""
        <div class="image-band">
          <figure class="photo status-photo-feature">
            <img loading="eager" decoding="async" src="{_h(primary.get('url'))}" alt="{_h(primary.get('alt') or primary.get('caption'))}">
            <figcaption>{_h(primary.get('caption'))}{_briefing_media_source_chips(primary)}</figcaption>
          </figure>
          <div class="media-panel">
            <div>
              <p class="kicker">照片導覽</p>
              <h2>先用照片建立路線感</h2>
              <p>第一眼先讓隊伍知道這不是抽象路線：有稜線、山屋、展望、導覽圖與需要人工審查的現地條件。</p>
            </div>
            <div class="status-cues" aria-label="照片導讀重點">
              <div class="status-cue"><b>路線畫面</b>先看稜線與遠景，建立隊伍共同方向感。</div>
              <div class="status-cue"><b>節點畫面</b>再看山屋、保線所與展望點，連回天數與停留策略。</div>
              <div class="status-cue"><b>安全邊界</b>照片只輔助行前理解；不能取代現地天氣、導航與領隊判斷。</div>
            </div>
            <div class="status-photo-strip">{grid}</div>
          </div>
        </div>
        """


def _briefing_visual_readiness_panel(media_manifest: dict[str, Any]) -> str:
    readiness = media_manifest.get("visual_readiness")
    if not isinstance(readiness, dict):
        image_curation = media_manifest.get("image_curation")
        readiness = (
            image_curation.get("visual_readiness")
            if isinstance(image_curation, dict)
            else {}
        )
    if not isinstance(readiness, dict) or not readiness:
        return ""
    status = str(readiness.get("status") or "thin")
    state_class = {
        "rich": "good",
        "usable": "good",
        "thin": "warning",
        "missing": "blocked",
    }.get(status, "warning")
    selected = int(readiness.get("selected_media_count") or 0)
    target_images = int(
        readiness.get("target_min_gallery_images") or BRIEFING_TARGET_MIN_GALLERY_IMAGES
    )
    covered_layers = int(readiness.get("covered_context_layer_count") or 0)
    target_layers = int(
        readiness.get("target_context_layer_count") or len(BRIEFING_CONTEXT_LAYER_ORDER)
    )
    missing_layers = [
        _context_layer_display_label(str(layer))
        for layer in readiness.get("missing_context_layers", [])
        if str(layer).strip()
    ]
    missing_text = "、".join(missing_layers) if missing_layers else "脈絡完整"
    actions = readiness.get("next_actions")
    if not isinstance(actions, list) or not actions:
        actions = ["圖像素材已可支撐公開簡報"]
    action_chips = "".join(
        f"<span>{_h(str(action))}</span>"
        for action in actions[:3]
        if str(action).strip()
    )
    return f"""
        <aside class="visual-readiness {state_class}" aria-label="圖像準備度">
          <div>
            <p class="kicker">圖像準備度</p>
            <h3>{_h(str(readiness.get('label') or '畫面素材'))}</h3>
            <p>{_h(str(readiness.get('recommendation') or '請補齊可追溯照片，讓簡報更像活動導覽。'))}</p>
            <div class="visual-readiness-actions">{action_chips}</div>
          </div>
          <div class="visual-readiness-meter" aria-label="圖像素材檢查">
            <div class="visual-readiness-metric">
              <span>照片數</span>
              <b>{_h(selected)} / {_h(target_images)}</b>
            </div>
            <div class="visual-readiness-metric">
              <span>脈絡層</span>
              <b>{_h(covered_layers)} / {_h(target_layers)}</b>
            </div>
            <div class="visual-readiness-metric">
              <span>缺口</span>
              <b>{_h(missing_text)}</b>
            </div>
            <div class="visual-readiness-metric">
              <span>用途</span>
              <b>行前簡報</b>
            </div>
          </div>
        </aside>
        """


def _briefing_photo_essay(media_manifest: dict[str, Any]) -> str:
    images = _briefing_media_images(media_manifest)
    if not images:
        return """
        <div class="media-gap">
          <p class="kicker">圖像缺口</p>
          <h3>目前沒有可組成圖像導覽的照片</h3>
          <p>請先補官方或可信來源照片；若是 Scout 自有照片，必須保留來源、位置與人工審查狀態。</p>
        </div>
        """
    feature = images[0]
    cards = "\n".join(
        _briefing_photo_essay_card(image, index=index)
        for index, image in enumerate(images[1 : BRIEFING_PHOTO_ESSAY_CARD_LIMIT + 1], start=2)
    )
    if not cards:
        cards = _briefing_photo_essay_card(feature, index=2)
    feature_caption = _first_text(feature.get("caption"), feature.get("alt"), "路線主畫面")
    return f"""
        <div class="photo-essay">
          <figure class="photo-essay-feature">
            <img loading="eager" decoding="async" src="{_h(feature.get('url'))}" alt="{_h(feature.get('alt') or feature_caption)}">
            <figcaption>
              <span>{_h(_briefing_photo_essay_label(feature, 1))}</span>
              <b>{_h(feature_caption)}</b>
              <span>{_h(_briefing_photo_essay_cue(feature))}</span>
              {_briefing_media_source_chips(feature)}
            </figcaption>
          </figure>
          <div class="photo-essay-grid" aria-label="路線照片導覽">
            {cards}
          </div>
        </div>
        """


def _briefing_photo_essay_card(image: dict[str, Any], *, index: int) -> str:
    caption = _first_text(image.get("caption"), image.get("alt"), "路線畫面")
    card_class = "photo-essay-card map-card" if _briefing_photo_essay_is_map(image) else "photo-essay-card"
    return (
        f'<figure class="{card_class}">'
        f'<img loading="lazy" src="{_h(image.get("url"))}" alt="{_h(image.get("alt") or caption)}">'
        '<figcaption class="photo-essay-caption">'
        f"<span>{_h(_briefing_photo_essay_label(image, index))}</span>"
        f"<b>{_h(caption)}</b>"
        f"<span>{_h(_briefing_photo_essay_cue(image))}</span>"
        f"{_briefing_media_source_chips(image)}"
        "</figcaption>"
        "</figure>"
    )


def _briefing_visual_contact_sheet(media_manifest: dict[str, Any]) -> str:
    images = _briefing_media_images(media_manifest)[:BRIEFING_MEDIA_GALLERY_LIMIT]
    if not images:
        return ""
    cards = "\n".join(
        _briefing_visual_contact_card(image, index=index)
        for index, image in enumerate(images, start=1)
    )
    readiness = media_manifest.get("visual_readiness")
    missing_layers = (
        readiness.get("missing_context_layers", [])
        if isinstance(readiness, dict)
        else []
    )
    shot_list = "\n".join(
        f"<span>{_h(_visual_shot_prompt(str(layer)))}</span>"
        for layer in missing_layers[:4]
        if str(layer).strip()
    )
    if not shot_list:
        shot_list = (
            "<span>下一輪可補近景、隊伍尺度或通過視角，讓畫面不只像風景照。</span>"
            "<span>每張新增照片都要標註拍攝位置、來源頁與可公開狀態。</span>"
        )
    return f"""
        <section class="visual-contact-sheet" aria-label="路線畫面索引">
          <div class="visual-contact-copy">
            <p class="kicker">畫面索引</p>
            <h3>把可用圖片一次攤開，先看哪裡還薄。</h3>
            <p>這一格給工作人員和領隊快速檢查：是否只有漂亮遠景，還是已經有路線總覽、宿點、地形、季節與短停觀察的畫面。</p>
            <div class="visual-shot-list" aria-label="下一輪採圖清單">
              {shot_list}
            </div>
          </div>
          <div class="visual-contact-grid">
            {cards}
          </div>
        </section>
        """


def _briefing_visual_contact_card(image: dict[str, Any], *, index: int) -> str:
    caption = _first_text(image.get("caption"), image.get("alt"), "路線畫面")
    return (
        '<figure class="visual-contact-card">'
        f'<img loading="lazy" src="{_h(image.get("url"))}" alt="{_h(image.get("alt") or caption)}">'
        "<figcaption>"
        f'<span class="visual-contact-index">{index:02d}</span>'
        f"<span>{_h(_briefing_short_text(caption, 42))}</span>"
        "</figcaption>"
        "</figure>"
    )


def _briefing_short_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 3)].rstrip() + "..."


def _briefing_visual_kit(media_manifest: dict[str, Any]) -> str:
    visual_kit = media_manifest.get("visual_kit")
    if not isinstance(visual_kit, dict):
        return ""
    slots = [
        slot
        for slot in visual_kit.get("slots", [])
        if isinstance(slot, dict)
    ]
    if not slots:
        return ""
    ready_count = int(visual_kit.get("ready_count") or 0)
    slot_count = int(visual_kit.get("slot_count") or len(slots))
    missing_count = int(visual_kit.get("missing_count") or max(0, slot_count - ready_count))
    cards = "\n".join(_briefing_visual_kit_card(slot) for slot in slots)
    status = (
        "可以用畫面帶簡報，但仍要由領隊人工審查。"
        if missing_count == 0
        else "畫面還不完整，缺口會留在採圖清單，不升級成結論。"
    )
    return f"""
        <div class="visual-kit-board" aria-label="簡報素材板">
          <div class="visual-kit-summary">
            <div>
              <p class="kicker">簡報素材</p>
              <h3>不是增加裝飾圖，而是讓每張圖負責一個行前說明任務。</h3>
              <p>{_h(status)} 這個素材板固定檢查開場、路線圖、宿點、地形、短停與天候季節，避免簡報只剩資料欄位。</p>
            </div>
            <div class="visual-kit-score" aria-label="素材板準備度">
              <b>{_h(ready_count)} / {_h(slot_count)}</b>
              <span>已配對簡報素材</span>
            </div>
          </div>
          <div class="visual-kit-grid">
            {cards}
          </div>
        </div>
        """


def _briefing_visual_kit_card(slot: dict[str, Any]) -> str:
    label = _first_text(slot.get("label"), "簡報素材")
    role = _first_text(slot.get("briefing_role"), "行前簡報素材")
    question = _first_text(slot.get("speaker_question"), "這張圖要支撐哪個行前判斷？")
    image = slot.get("image")
    if isinstance(image, dict) and image.get("url"):
        caption = _first_text(image.get("caption"), image.get("alt"), label)
        image_html = (
            "<figure class=\"visual-kit-image\">"
            f"<img loading=\"lazy\" src=\"{_h(image.get('url'))}\" "
            f"alt=\"{_h(image.get('alt') or caption)}\">"
            f"<figcaption>{_h(caption)}{_briefing_media_source_chips(image)}</figcaption>"
            "</figure>"
        )
        status_label = "已配對"
        card_class = "ready"
        missing = ""
    else:
        image_html = ""
        status_label = "待補圖"
        card_class = "missing"
        missing_action = _first_text(slot.get("missing_action"), "補一張可追溯圖片。")
        missing = f"<p class=\"visual-kit-missing-action\">{_h(missing_action)}</p>"
    return (
        f"<article class=\"visual-kit-card {card_class}\">"
        f"{image_html}"
        "<div class=\"visual-kit-body\">"
        f"<span class=\"visual-kit-label\">{_h(status_label)}</span>"
        f"<h3>{_h(label)}</h3>"
        f"<p class=\"visual-kit-role\">{_h(role)}</p>"
        f"<p class=\"visual-kit-question\">{_h(question)}</p>"
        f"{missing}"
        "<div class=\"visual-kit-boundary\" aria-label=\"素材使用邊界\">"
        "<span>行前候選素材</span>"
        "<span>需人工審查</span>"
        "<span>非安全真值</span>"
        "</div>"
        "</div>"
        "</article>"
    )


def _visual_shot_prompt(layer: str) -> str:
    prompts = {
        "route_overview": "補一張路線總覽或入口畫面，讓隊伍先知道這趟路的形狀。",
        "historical": "補一張舊路、保線所、山屋或人為設施，讓歷史層有畫面可講。",
        "cultural": "補一張地名、路標或可公開的地方脈絡畫面，避免文化層只剩文字。",
        "natural": "補一張林相、植被、溪流或雲霧變化，讓自然層不只是背景介紹。",
        "terrain": "補一張稜線、風口、坡面或崩壁遠景，讓地形層能支撐通過策略。",
        "seasonal": "補一張季節條件照片，例如花期、雲海、雨霧、低溫或芒草狀態。",
        "observation_point": "補一張短停觀察點，最好能看出站位、停留空間與離開方向。",
    }
    return prompts.get(layer, f"補一張 {_context_layer_display_label(layer)} 的可追溯畫面。")


def _briefing_photo_essay_is_map(image: dict[str, Any]) -> bool:
    text = _media_search_text(image).lower()
    return "導覽圖" in text or "地圖" in text or "map" in text


def _briefing_photo_essay_label(image: dict[str, Any], index: int) -> str:
    anchor = image.get("presentation_anchor")
    if not isinstance(anchor, dict):
        anchor = _inferred_media_section_anchor(_media_search_text(image))
    context = _briefing_context_kind_label(anchor.get("context_kind"))
    return f"畫面 {index:02d} · {context}"


def _briefing_photo_essay_cue(image: dict[str, Any]) -> str:
    text = _media_search_text(image)
    if "山莊" in text or "保線所" in text:
        return "把住宿、休息與撤退節點先放進隊伍共同記憶。"
    if "光被八表" in text or "日出" in text or "雲海" in text:
        return "展望畫面要連到風、時間、停留條件與隊伍節奏。"
    if "導覽圖" in text or "地圖" in text or "map" in text.lower():
        return "用總覽圖確認路線方向，但不要取代離線地圖與導航。"
    if "能高越嶺" in text:
        return "先建立路線氣質，再回頭確認每個檢查點的通過策略。"
    return "作為行前視覺脈絡，正式結論仍需回到可追溯資料。"


def _briefing_visual_story_arc(media_manifest: dict[str, Any]) -> str:
    images = _briefing_media_images(media_manifest)
    if not images:
        return """
        <div class="media-gap">
          <p class="kicker">視覺故事缺口</p>
          <h3>目前還不能組成四幕式活動簡報</h3>
          <p>請先匯入已核准來源照片，或有來源紀錄的 Scout 自有照片。</p>
        </div>
        """
    story_steps = [
        {
            "layer_id": "route_overview",
            "step": "第一幕",
            "title": "先看見整條路",
            "cue": "用總覽、遠景或稜線照片讓隊伍知道今天走的是哪一種山路。",
            "fallback_index": 0,
        },
        {
            "layer_id": "historical",
            "step": "第二幕",
            "title": "把舊路與宿點串起來",
            "cue": "讓保線、山屋、補給與撤退節點先進入共同記憶。",
            "fallback_index": 1,
        },
        {
            "layer_id": "terrain",
            "step": "第三幕",
            "title": "高山段要講通過策略",
            "cue": "展望不是只看風景，也要提醒風口、坡面、隊形與停留條件。",
            "fallback_index": 2,
        },
        {
            "layer_id": "observation_point",
            "step": "第四幕",
            "title": "每次短停都換回一個判斷",
            "cue": "漂亮畫面要轉成時間、天氣、隊伍距離與離開條件。",
            "fallback_index": 3,
        },
    ]
    used_urls: set[str] = set()
    panels = []
    for step in story_steps:
        image = _briefing_unused_media_for_layer(
            str(step["layer_id"]),
            media_manifest,
            used_urls=used_urls,
            fallback_index=int(step["fallback_index"]),
        )
        if image:
            panels.append(_briefing_visual_story_panel(image, step))
    if not panels:
        return '<p class="muted">目前沒有可呈現四幕導覽的圖片 metadata。</p>'
    return f"""
        <div class="visual-story-arc">
          <div class="visual-story-lead">
            <div>
              <h3>不是把照片貼上去，而是讓照片負責開場。</h3>
              <p>公開簡報先用畫面建立活動感；來源與查核邊界留給資料頁確認。</p>
            </div>
            <div class="visual-story-stat">
              <span>可用路線圖像</span>
              <b>{_h(len(images))}</b>
              <p>最多保留 {_h(BRIEFING_MEDIA_GALLERY_LIMIT)} 張，讓章節依歷史、自然、地形與觀察點取用。</p>
            </div>
          </div>
          <div class="visual-story-grid" aria-label="四幕式活動簡報">
            {"".join(panels)}
          </div>
        </div>
        """


def _briefing_visual_story_panel(
    image: dict[str, Any],
    step: dict[str, Any],
) -> str:
    caption = _first_text(image.get("caption"), image.get("alt"), step.get("title"), "路線畫面")
    return (
        '<article class="visual-story-panel">'
        f'<img loading="lazy" src="{_h(image.get("url"))}" alt="{_h(image.get("alt") or caption)}">'
        '<div class="visual-story-body">'
        f'<span class="visual-story-step">{_h(step.get("step"))}</span>'
        f"<h3>{_h(step.get('title'))}</h3>"
        f"<p>{_h(step.get('cue'))}</p>"
        f"{_briefing_media_source_chips(image)}"
        "</div>"
        "</article>"
    )


def _briefing_visual_anchor_cards(media_manifest: dict[str, Any]) -> str:
    images = [
        image
        for image in media_manifest.get("gallery_images", [])
        if isinstance(image, dict) and image.get("url")
    ]
    if not images:
        return '<p class="muted">目前沒有可建立照片路標的 media metadata。</p>'
    cards = []
    for image in images[:BRIEFING_VISUAL_ANCHOR_LIMIT]:
        anchor = image.get("presentation_anchor")
        if not isinstance(anchor, dict):
            anchor = _inferred_media_section_anchor(_media_search_text(image))
        kind_label = _visual_anchor_kind_label(anchor.get("anchor_kind"))
        distance = _first_text(anchor.get("distance_label"), "路線段")
        context = _briefing_context_kind_label(anchor.get("context_kind"))
        caption = _first_text(image.get("caption"), image.get("alt"), anchor.get("label"))
        cards.append(
            "<article class=\"visual-anchor\">"
            f"<img loading=\"lazy\" src=\"{_h(image.get('url'))}\" "
            f"alt=\"{_h(image.get('alt') or caption)}\">"
            "<div class=\"visual-anchor-body\">"
            f"<span class=\"anchor-kind\">{_h(kind_label)}</span>"
            f"<h3>{_h(anchor.get('label') or caption)}</h3>"
            f"<p>{_h(distance)} · {_h(context)}</p>"
            f"<p class=\"muted\">{_h(caption)}</p>"
            f"{_briefing_media_source_chips(image)}"
            f"<details class=\"audit-details\"><summary>錨定依據</summary>"
            f"<code>{_h(anchor.get('match_reason'))}</code></details>"
            "</div>"
            "</article>"
        )
    return "\n".join(cards)


def _briefing_story_wall(
    points: list[dict[str, Any]],
    media_manifest: dict[str, Any],
) -> str:
    story_catalog = [
        (
            "historical",
            "歷史層",
            "從能高越嶺道開始讀路",
            "把舊路、保線所與山屋串成一條時間線。",
            "把古道、保線所、山屋與人為設施串成時間線，隊伍比較容易記住這條路為什麼存在。",
            "這裡是舊路痕跡、補給節點，還是單純經過點？",
        ),
        (
            "cultural",
            "文化層",
            "地名與路徑先保持尊重",
            "有脈絡就說脈絡，沒有來源就保留。",
            "原住民族地名、舊社與獵徑脈絡只作候選理解，不把未審核內容講成正式史實。",
            "這個名稱或路徑脈絡，我們有沒有可靠來源？",
        ),
        (
            "natural",
            "自然層",
            "讓林相、雲海與高山植被帶路",
            "自然變化是隊伍正在換環境的訊號。",
            "自然觀察不是背景介紹；它能提醒隊伍海拔、濕度、風向與季節感正在改變。",
            "這裡的植物、風、雲和溪流，跟剛才那段有什麼不同？",
        ),
        (
            "terrain",
            "地形層",
            "把展望點說成通過策略",
            "展望點不是只看風景，也要決定怎麼通過。",
            "稜線、鞍部、崩壁、風口與谷線要連到停留、通過、撤退和隊形，不只當景點。",
            "這裡適合停留，還是應該快速通過？",
        ),
        (
            "seasonal",
            "季節層",
            "季節不是美照，而是時間壓力",
            "季節條件會決定今天能不能慢慢走。",
            "花期、雨季、雲海、低溫、芒草與午後天氣，會改變拍照時間、摸黑風險與體能消耗。",
            "如果天氣提早變差，下一個安全點是哪裡？",
        ),
        (
            "observation_point",
            "觀察點",
            "3 分鐘短停要有目的",
            "每一次停留都要換回一個判斷。",
            "值得停不是因為漂亮，而是因為這裡能幫隊伍建立路線記憶、風險判斷或撤退共識。",
            "停 3 分鐘後，我們要帶走哪個判斷？",
        ),
    ]
    used_urls: set[str] = set()
    cards: list[str] = []
    for index, (layer_id, label, headline, cue, note, question) in enumerate(story_catalog):
        layer_points = [
            point for point in _route_ordered_points(points)
            if layer_id in _str_list(point.get("sec6_layers"))
        ]
        names = "、".join(_unique_point_labels(layer_points, limit=3)) or "待補現地觀察點"
        image = _briefing_unused_media_for_layer(
            layer_id,
            media_manifest,
            used_urls=used_urls,
            fallback_index=index,
        )
        image_html = ""
        chips = ""
        if image:
            image_html = (
                f"<img loading=\"eager\" decoding=\"async\" src=\"{_h(image.get('url'))}\" "
                f"alt=\"{_h(image.get('alt') or image.get('caption') or headline)}\">"
            )
            chips = _briefing_media_source_chips(image)
        if index == 0:
            cards.append(
                "<article class=\"story-feature\">"
                f"{image_html}"
                "<div class=\"story-feature-body\">"
                f"<span class=\"tag gold\">{_h(label)}</span>"
                f"<h3>{_h(headline)}</h3>"
                f"<p class=\"story-cue\">{_h(cue)}</p>"
                f"<p class=\"story-point\"><b>可帶到</b>{_h(names)}</p>"
                f"<p class=\"story-question\"><b>現場問</b>{_h(question)}</p>"
                f"<details class=\"story-speaker-note\"><summary>講者備註</summary>"
                f"<p>{_h(note)}</p></details>"
                f"{chips}"
                "</div>"
                "</article>"
            )
            continue
        cards.append(
            "<article class=\"story-tile\">"
            f"{image_html}"
            "<div class=\"story-tile-body\">"
            f"<span class=\"tag\">{_h(label)}</span>"
            f"<h3>{_h(headline)}</h3>"
            f"<p class=\"story-cue\">{_h(cue)}</p>"
            f"<p class=\"story-point\"><b>可帶到</b>{_h(names)}</p>"
            f"<p class=\"story-question\"><b>現場問</b>{_h(question)}</p>"
            f"<details class=\"story-speaker-note\"><summary>講者備註</summary>"
            f"<p>{_h(note)}</p></details>"
            f"{chips}"
            "</div>"
            "</article>"
        )
    feature = cards[0] if cards else ""
    mosaic = "\n".join(cards[1:])
    return f"""
        <div class="story-wall">
          {feature}
          <div class="story-mosaic">{mosaic}</div>
        </div>
        """


def _briefing_unused_media_for_layer(
    layer_id: str,
    media_manifest: dict[str, Any],
    *,
    used_urls: set[str],
    fallback_index: int,
) -> dict[str, Any] | None:
    preferred = _briefing_media_for_layer(
        layer_id,
        media_manifest,
        fallback_index=fallback_index,
    )
    images = _briefing_media_images(media_manifest)
    for image in [preferred, *images[fallback_index:], *images[:fallback_index]]:
        if not image:
            continue
        url = str(image.get("url") or "")
        if not url or url in used_urls:
            continue
        used_urls.add(url)
        return image
    if preferred:
        url = str(preferred.get("url") or "")
        if url:
            used_urls.add(url)
        return preferred
    return None


def _visual_anchor_kind_label(anchor_kind: Any) -> str:
    labels = {
        "route_point": "路線點照片",
        "route_section": "路線段照片",
    }
    return labels.get(str(anchor_kind or ""), "照片素材")


def _briefing_photo_figure(image: dict[str, Any]) -> str:
    caption = _first_text(image.get("caption"), image.get("alt"), "路線照片")
    return (
        "<figure class=\"photo\">"
        f"<img loading=\"lazy\" src=\"{_h(image.get('url'))}\" "
        f"alt=\"{_h(image.get('alt') or caption)}\">"
        f"<figcaption>{_h(caption)}{_briefing_media_source_chips(image)}</figcaption>"
        "</figure>"
    )


def _briefing_media_source_chips(image: dict[str, Any]) -> str:
    tier = str(image.get("source_tier") or "unknown").strip() or "unknown"
    family = str(image.get("source_family") or "").strip()
    chips = [
        (
            f"source-badge {_source_tier_badge_class(tier)}",
            _source_tier_display_label(tier),
        )
    ]
    if family:
        chips.append(("source-badge source-family", _source_family_display_label(family)))
    if image.get("candidate_only") is True:
        chips.append(("source-badge boundary", "候選證據"))
    if image.get("requires_human_review") is True:
        chips.append(("source-badge review", "需人工審查"))
    if image.get("runtime_safety_truth") is False:
        chips.append(("source-badge boundary", "非安全真值"))
    return (
        "<span class=\"source-chips\" aria-label=\"media provenance\">"
        + "".join(
            f"<span class=\"{_h(class_name)}\">{_h(label)}</span>"
            for class_name, label in chips
        )
        + "</span>"
    )


def _source_tier_display_label(tier: str) -> str:
    normalized = tier.strip().upper()
    labels = {
        "P0": "官方來源",
        "P1": "可信參考",
        "P2": "Scout 回顧",
    }
    return labels.get(normalized, normalized or "未知來源")


def _source_family_display_label(family: str) -> str:
    normalized = family.strip()
    labels = {
        "official_baseline": "官方照片",
        "official_status": "官方狀態",
        "official_forest_notice": "官方公告",
        "web_case_evidence": "網路參考",
        "scout_owned_observation": "Scout 自有資料",
        "route_context": "路線脈絡",
        "historical_expansion": "歷史參考",
        "historical_map_baseline": "歷史地圖",
        "cultural_expansion": "文化參考",
        "cultural_spatial_expansion": "文化空間",
        "natural_baseline": "自然資料",
        "geology_expansion": "地質參考",
        "map_expansion": "地圖參考",
        "community_article_evidence": "山友文章",
        "community_route_evidence": "路線參考",
        "community_route_profile": "路線介紹",
        "community_route_seed": "路線種子",
        "community_or_reference_source": "參考來源",
    }
    return labels.get(normalized, normalized.replace("_", " ")[:26])


def _source_tier_badge_class(tier: str) -> str:
    normalized = tier.lower()
    if normalized.startswith("p0"):
        return "tier-p0"
    if normalized.startswith("p1"):
        return "tier-p1"
    if normalized.startswith("p2"):
        return "tier-p2"
    return "tier-unknown"


def _briefing_chapter_break(
    *,
    media_manifest: dict[str, Any],
    number: str,
    eyebrow: str,
    title: str,
    body: str,
    bullets: list[str],
    context_kinds: tuple[str, ...],
    label_keywords: tuple[str, ...],
) -> str:
    image = _briefing_media_for_context(
        media_manifest,
        context_kinds=context_kinds,
        label_keywords=label_keywords,
    )
    photo = ""
    visual_card = ""
    if image:
        caption = _first_text(image.get("caption"), image.get("alt"), title)
        anchor = image.get("presentation_anchor")
        if not isinstance(anchor, dict):
            anchor = _inferred_media_section_anchor(_media_search_text(image))
        context_label = _briefing_context_kind_label(anchor.get("context_kind"))
        anchor_label = _first_text(anchor.get("label"), caption, "章節主畫面")
        photo = (
            f"<img class=\"chapter-photo\" loading=\"lazy\" src=\"{_h(image.get('url'))}\" "
            f"alt=\"{_h(image.get('alt') or caption)}\">"
        )
        visual_card = (
            "<aside class=\"chapter-visual-card\" aria-label=\"章節主畫面\">"
            "<figure class=\"chapter-visual-photo\">"
            f"<img loading=\"lazy\" src=\"{_h(image.get('url'))}\" alt=\"{_h(image.get('alt') or caption)}\">"
            "<figcaption>"
            f"<span class=\"chapter-visual-label\">{_h(context_label)}</span>"
            f"<b class=\"chapter-visual-title\">{_h(anchor_label)}</b>"
            f"{_briefing_media_source_chips(image)}"
            "</figcaption>"
            "</figure>"
            "<div class=\"chapter-cue-tags\" aria-label=\"章節使用邊界\">"
            "<span>行前候選畫面</span>"
            "<span>需人工審查</span>"
            "<span>不是現地安全結論</span>"
            "</div>"
        )
    rhythm = "\n".join(
        f"<span>{_h(item)}</span>"
        for item in bullets
    )
    if not visual_card:
        visual_card = (
            "<aside class=\"chapter-visual-card no-photo\" aria-label=\"章節主畫面\">"
            "<div class=\"chapter-cue-tags\" aria-label=\"章節使用邊界\">"
            "<span>缺少章節主畫面</span>"
            "<span>需補可追溯照片</span>"
            "<span>不是現地安全結論</span>"
            "</div>"
        )
    visual_card += (
        "<div class=\"chapter-rhythm\">"
        "<b>這章要帶隊伍抓住</b>"
        f"{rhythm}"
        "</div>"
        "</aside>"
    )
    chapter_id = f"chapter-{number.lower()}"
    return (
        f"<section class=\"slide chapter-break\" id=\"{_h(chapter_id)}\">"
        f"{photo}"
        "<div class=\"chapter-inner\">"
        "<div class=\"chapter-stage\">"
        f"<span class=\"chapter-number\">章節 {_h(number)}</span>"
        f"<p class=\"kicker\">{_h(eyebrow)}</p>"
        f"<h2>{_h(title)}</h2>"
        f"<p class=\"chapter-copy\">{_h(body)}</p>"
        "</div>"
        f"{visual_card}"
        "</div>"
        "</section>"
    )


def _briefing_media_images(media_manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        image
        for image in media_manifest.get("gallery_images", [])
        if isinstance(image, dict) and image.get("url")
    ]


def _briefing_media_for_context(
    media_manifest: dict[str, Any],
    *,
    context_kinds: tuple[str, ...] = (),
    label_keywords: tuple[str, ...] = (),
    fallback_index: int | None = 0,
) -> dict[str, Any] | None:
    images = _briefing_media_images(media_manifest)
    if not images:
        return None
    for image in images:
        anchor = image.get("presentation_anchor")
        if not isinstance(anchor, dict):
            anchor = {}
        context = str(anchor.get("context_kind") or "")
        label = _media_search_text(image) + " " + str(anchor.get("label") or "")
        if label_keywords and any(keyword in label for keyword in label_keywords):
            return image
        if context_kinds and context in context_kinds:
            return image
    if fallback_index is None:
        return None
    return images[fallback_index % len(images)]


def _briefing_visual_kit_slot_image(
    media_manifest: dict[str, Any],
    slot_id: str,
) -> dict[str, Any] | None:
    visual_kit = media_manifest.get("visual_kit")
    if not isinstance(visual_kit, dict):
        return None
    for slot in visual_kit.get("slots", []):
        if not isinstance(slot, dict) or slot.get("slot_id") != slot_id:
            continue
        image = slot.get("image")
        if isinstance(image, dict) and image.get("url"):
            return image
    return None


def _briefing_media_for_point(
    media_manifest: dict[str, Any],
    point: dict[str, Any],
    *,
    fallback_index: int = 0,
) -> dict[str, Any] | None:
    label = _point_label(point)
    context_kind = str(point.get("context_kind") or "")
    images = _briefing_media_images(media_manifest)
    for image in images:
        anchor = image.get("presentation_anchor")
        if not isinstance(anchor, dict):
            continue
        if str(anchor.get("label") or "") == label:
            return image
    return _briefing_media_for_context(
        media_manifest,
        context_kinds=(context_kind,) if context_kind else (),
        label_keywords=(label,),
        fallback_index=fallback_index,
    )


def _briefing_field_media(
    image: dict[str, Any] | None,
    *,
    caption_prefix: str = "",
) -> str:
    if not image:
        return ""
    anchor = image.get("presentation_anchor")
    if not isinstance(anchor, dict):
        anchor = {}
    caption = _first_text(
        image.get("caption"),
        image.get("alt"),
        anchor.get("label"),
        "route context media",
    )
    if caption_prefix:
        caption = f"{caption_prefix}: {caption}"
    return (
        "<figure class=\"field-media\">"
        f"<img loading=\"lazy\" src=\"{_h(image.get('url'))}\" "
        f"alt=\"{_h(image.get('alt') or caption)}\">"
        f"<figcaption>{_h(caption)}{_briefing_media_source_chips(image)}</figcaption>"
        "</figure>"
    )


def _briefing_route_map_atlas(
    points: list[dict[str, Any]],
    route_summary: dict[str, Any],
    media_manifest: dict[str, Any],
    source_manifest: dict[str, Any],
) -> str:
    route_map = _briefing_visual_kit_slot_image(
        media_manifest,
        "route_map",
    ) or _briefing_media_for_context(
        media_manifest,
        label_keywords=("導覽圖", "地圖", "map"),
        fallback_index=None,
    )
    distance_label = _route_distance_label(route_summary.get("distance_m"))
    elevation_range = _route_elevation_range_label(route_summary)
    bbox_span = _route_bbox_span_label(route_summary)
    p0_count = _source_tier_loaded_count(source_manifest, "P0")
    p1_count = _source_tier_loaded_count(source_manifest, "P1")
    p2_count = _source_tier_loaded_count(source_manifest, "P2")
    map_figure = _briefing_map_atlas_figure(route_map)
    point_names = "、".join(_unique_point_labels(points, limit=4)) or "待補路線點"
    return f"""
        <section class="map-atlas" aria-label="地圖深度與廣度">
          <div class="map-atlas-hero">
            {map_figure}
            <div class="map-atlas-copy">
              <p class="kicker">地圖深度</p>
              <h3>先用地圖建立廣度，再用節點建立深度。</h3>
              <p>這一頁把官方圖、候選路線點與 Scout 自有回顧放在同一個閱讀框架：隊伍先知道整條路有多長、跨多遠、爬升到哪裡，再決定哪些段落要慢看、哪些段落要快通過。</p>
              <div class="map-atlas-stats" aria-label="地圖尺度摘要">
                <div class="map-atlas-stat"><span>路線尺度</span><b>{_h(distance_label)}</b></div>
                <div class="map-atlas-stat"><span>高度感</span><b>{_h(elevation_range)}</b></div>
                <div class="map-atlas-stat"><span>空間跨度</span><b>{_h(bbox_span)}</b></div>
              </div>
            </div>
          </div>
          <div class="map-atlas-layers" aria-label="地圖證據三層">
            <article class="map-layer-card">
              <b>P0 官方底圖</b>
              <p>官方圖、路線狀態、地形與天候資料負責建立基本方向，不能被山友敘事取代。</p>
              <small>已載入 {_h(p0_count)} 類 P0 資料</small>
            </article>
            <article class="map-layer-card">
              <b>P1 擴展地圖</b>
              <p>OSM/Overpass、社群路線與命名點負責補足山屋、展望、地名與地形脈絡。</p>
              <small>已載入 {_h(p1_count)} 類 P1 資料；目前路線點：{_h(point_names)}</small>
            </article>
            <article class="map-layer-card">
              <b>P2 走過的痕跡</b>
              <p>Scout 自有 route notes 與完成旅程資料只當內部回顧，提醒下一次要補哪些停留與延誤線索。</p>
              <small>已載入 {_h(p2_count)} 類 P2 資料，仍維持 candidate-only。</small>
            </article>
          </div>
        </section>
        """


def _briefing_map_atlas_figure(image: dict[str, Any] | None) -> str:
    if not image:
        return (
            '<div class="media-gap map-atlas-figure" aria-label="缺官方路線圖">'
            "<p class=\"kicker\">地圖缺口</p>"
            "<h3>缺少可追溯的路線圖</h3>"
            "<p>請補官方導覽圖、GPX 總覽圖或 operator-approved map image。</p>"
            "</div>"
        )
    caption = _first_text(image.get("caption"), image.get("alt"), "路線地圖")
    return (
        '<figure class="map-atlas-figure">'
        f"<img loading=\"lazy\" src=\"{_h(image.get('url'))}\" "
        f"alt=\"{_h(image.get('alt') or caption)}\">"
        f"<figcaption>{_h(caption)}{_briefing_media_source_chips(image)}</figcaption>"
        "</figure>"
    )


def _route_elevation_range_label(route_summary: dict[str, Any]) -> str:
    low = _float_or_none(route_summary.get("elevation_min_m"))
    high = _float_or_none(route_summary.get("elevation_max_m"))
    if low is None or high is None:
        return "待補"
    return f"{low:.0f}m - {high:.0f}m"


def _route_bbox_span_label(route_summary: dict[str, Any]) -> str:
    bbox = route_summary.get("bbox_wgs84")
    if not isinstance(bbox, dict):
        return "待補"
    min_lat = _float_or_none(bbox.get("min_lat"))
    max_lat = _float_or_none(bbox.get("max_lat"))
    min_lon = _float_or_none(bbox.get("min_lon"))
    max_lon = _float_or_none(bbox.get("max_lon"))
    if None in (min_lat, max_lat, min_lon, max_lon):
        return "待補"
    north_south = abs(max_lat - min_lat) * 111.0
    east_west = abs(max_lon - min_lon) * 111.0
    return f"南北 {north_south:.1f}km / 東西 {east_west:.1f}km"


def _briefing_route_visual(
    points: list[dict[str, Any]],
    route_summary: dict[str, Any],
    media_manifest: dict[str, Any],
) -> str:
    if not points:
        return ""
    distance_m = _float_or_none(route_summary.get("distance_m"))
    route_distance_km = _route_distance_label(route_summary.get("distance_m"))
    elevation_min = _elevation_label(route_summary.get("elevation_min_m"))
    elevation_max = _elevation_label(route_summary.get("elevation_max_m"))
    profile_points = _briefing_profile_points(points, distance_m)
    profile_markers = _briefing_profile_markers(profile_points)
    profile_legend = _briefing_profile_legend(profile_points)
    route_media = _briefing_media_for_context(
        media_manifest,
        context_kinds=("route_overview",),
        label_keywords=("導覽圖", "路線總覽", "能高越嶺道"),
        fallback_index=0,
    )
    route_photo_strip = _briefing_route_photo_strip(
        media_manifest,
        exclude_url=str(route_media.get("url") or "") if route_media else "",
    )
    nodes = "\n".join(
        "<div class=\"route-node\">"
        f"<b>{_h(_point_distance_label(point))}</b>"
        f"<span>{_h(_point_label(point))}</span>"
        "</div>"
        for point in points[:8]
    )
    return f"""
        <section class="route-focus-strip" aria-label="路線頁主判斷">
          <div class="route-focus-lead">
            <p class="kicker">領隊先講這三件事</p>
            <h3>先建立路線節奏，再決定哪些點要停、哪些點要快通過。</h3>
            <p>這頁先給隊伍一個共同讀法：路線長度、節點密度、地形轉換與最後確認條件。</p>
          </div>
          <div class="route-focus-item">
            <b>主線節奏</b>
            <span>{_h(route_distance_km)} 不是只看距離，要同時看住宿、補水與回程時間。</span>
          </div>
          <div class="route-focus-item">
            <b>節點分類</b>
            <span>補水、轉折、風口、展望和山屋分開討論，不把所有點都當景點。</span>
          </div>
          <div class="route-focus-item">
            <b>最後確認</b>
            <span>缺定位訊號、天氣或隊伍狀態時，這頁只當行前理解，不當安全結論。</span>
          </div>
        </section>
        <div class="route-overview">
          <div class="route-profile-card">
            <div class="route-profile-head">
              <div>
                <p class="kicker">路線閱讀圖</p>
                <b>先看節奏，再看節點</b>
              </div>
              <small>行前閱讀</small>
            </div>
            <div class="profile-stats">
              <div class="profile-stat"><span>距離候選</span>{_h(route_distance_km)}</div>
              <div class="profile-stat"><span>最低高度</span>{_h(elevation_min)}</div>
              <div class="profile-stat"><span>最高高度</span>{_h(elevation_max)}</div>
            </div>
            <div class="profile-track" aria-label="route profile markers">
              {profile_markers}
            </div>
            <div class="profile-legend">{profile_legend}</div>
            <p class="footnote">這張圖幫隊伍看見節奏與檢核點；現地導航、天氣與安全判斷仍要另行確認。</p>
          </div>
          <div class="route-media-note">
            {_briefing_field_media(route_media, caption_prefix="路線圖像")}
            <div class="route-reader-cues" aria-label="路線閱讀提問">
              <span><b>先看節奏</b>哪一段只是推進，哪一段會開始消耗時間與體力。</span>
              <span><b>再看節點</b>補水、轉折、風口、展望與山屋要分開討論。</span>
              <span><b>最後看條件</b>缺少定位訊號、天氣或隊伍狀態時，不能把圖當安全結論。</span>
            </div>
            {route_photo_strip}
            <details class="route-data-details">
              <summary>資料邊界</summary>
              <p>路線總覽來自 bounded point metadata，距離候選 {_h(route_distance_km)}；HTML 不嵌入 raw GPX。</p>
            </details>
          </div>
        </div>
        <div class="route-rail" aria-label="route overview">{nodes}</div>
        """


def _briefing_route_photo_strip(media_manifest: dict[str, Any], *, exclude_url: str) -> str:
    images = [
        image
        for image in _briefing_media_images(media_manifest)
        if str(image.get("url") or "") and str(image.get("url") or "") != exclude_url
    ][:3]
    if not images:
        return ""
    return (
        '<div class="route-photo-strip" aria-label="路線畫面補充">'
        + "\n".join(_briefing_photo_figure(image) for image in images)
        + "</div>"
    )


def _briefing_profile_points(
    points: list[dict[str, Any]],
    distance_m: float | None,
) -> list[dict[str, Any]]:
    profile_points: list[dict[str, Any]] = []
    usable_distance = distance_m if distance_m and distance_m > 0 else None
    plotted = 0
    for point in points:
        point_distance = _float_or_none(point.get("distance_m"))
        if point_distance is None:
            continue
        if usable_distance:
            percent = max(0.0, min(100.0, point_distance / usable_distance * 100.0))
        else:
            percent = min(100.0, plotted * 11.0)
        if plotted >= 6:
            break
        profile_points.append(
            {
                "percent": percent,
                "distance_label": _point_distance_label(point),
                "label": _point_label(point),
            }
        )
        plotted += 1
    return profile_points


def _briefing_profile_markers(profile_points: list[dict[str, Any]]) -> str:
    markers = []
    for point in profile_points:
        markers.append(
            "<i class=\"profile-marker\" "
            f"style=\"left: {float(point['percent']):.1f}%\" "
            f"title=\"{_h(point['distance_label'])} {_h(point['label'])}\"></i>"
        )
    return "\n".join(markers)


def _briefing_profile_legend(profile_points: list[dict[str, Any]]) -> str:
    return "\n".join(
        "<span class=\"profile-legend-item\">"
        f"<b>{_h(point['distance_label'])}</b>{_h(point['label'])}"
        "</span>"
        for point in profile_points
    )


def _elevation_label(value: Any) -> str:
    elevation = _float_or_none(value)
    if elevation is None:
        return "unknown"
    return f"{elevation:.0f} m"


def _briefing_boundary_status(boundary: dict[str, Any]) -> str:
    raw = "; ".join(
        (
            f"candidate_only={str(boundary.get('candidate_only')).lower()}",
            f"runtime_safety_truth={str(boundary.get('runtime_safety_truth')).lower()}",
            f"live_safety_api_called={str(boundary.get('safety_api_called')).lower()}",
            f"source_fulltext_embedded={str(boundary.get('source_fulltext_embedded')).lower()}",
        )
    )
    return (
        "這份簡報只供行前討論與人工審查；它不會寫入 runtime safety，也不會取代現地判斷。"
        "<details class=\"audit-details\">"
        "<summary>顯示機器可讀邊界</summary>"
        f"<code>{_h(raw)}</code>"
        "</details>"
    )


def _briefing_route_label(
    *,
    project_id: str,
    route_keywords: list[str],
    route_summary: dict[str, Any],
) -> str:
    for keyword in route_keywords:
        text = str(keyword or "").strip()
        if text and text != project_id:
            return text
    route_name = str(route_summary.get("route_name") or "").strip()
    if route_name and _is_thematic_route_keyword(route_name):
        return route_name
    return project_id


def _route_distance_label(distance_m: Any) -> str:
    distance = _float_or_none(distance_m)
    if distance is None:
        return "unknown"
    return f"{distance / 1000.0:.1f} km"


def _representative_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        points,
        key=lambda point: (
            -_briefing_observation_score(point),
            _distance_sort_value(point),
            str(point.get("display_label") or point.get("label") or ""),
        ),
    )


def _route_ordered_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        points,
        key=lambda point: (
            _distance_sort_value(point),
            -_briefing_observation_score(point),
            str(point.get("display_label") or point.get("label") or ""),
        ),
    )


def _observation_stop_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = [
        point
        for point in points
        if "observation_point" in _str_list(point.get("sec6_layers"))
        or str(point.get("stop_advisory_candidate") or "")
        == "short_stop_requires_contextual_permission"
    ]
    return candidates or _representative_points(points)


def _risk_context_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        point
        for point in _representative_points(points)
        if str(point.get("context_kind") or "") == "risk_context"
        or "terrain" in _str_list(point.get("sec6_layers"))
        or str(point.get("stop_advisory_candidate") or "")
        == "pass_through_or_minimize_exposure"
    ]


def _navigation_context_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        point
        for point in _route_ordered_points(points)
        if str(point.get("context_kind") or "") == "navigation_context"
        or str(point.get("nearest_cp_candidate_id") or "")
    ]


def _briefing_observation_score(point: dict[str, Any]) -> float:
    score = point.get("observation_score")
    if isinstance(score, dict):
        value = _float_or_none(score.get("value"))
        if value is not None:
            return value
    return 0.0


def _distance_sort_value(point: dict[str, Any]) -> float:
    distance = _float_or_none(point.get("distance_m"))
    return distance if distance is not None else 10**12


def _point_label(point: dict[str, Any]) -> str:
    return str(point.get("display_label") or point.get("label") or "Unnamed point")


def _point_distance_label(point: dict[str, Any]) -> str:
    distance = _float_or_none(point.get("distance_m"))
    if distance is None:
        return "距離 unknown"
    return f"{distance / 1000.0:.1f}K"


def _point_source_label(point: dict[str, Any]) -> str:
    parts = [
        str(point.get("source_tier") or "unknown"),
        str(point.get("evidence_type") or "candidate"),
    ]
    families = _str_list(point.get("source_families"))
    if families:
        parts.append("/".join(families[:3]))
    return " · ".join(part for part in parts if part)


def _briefing_context_kind_label(context_kind: Any) -> str:
    labels = {
        "navigation_context": "導航脈絡",
        "resource_context": "資源節點",
        "risk_context": "風險脈絡",
        "viewpoint": "展望點",
        "viewpoint_context": "展望脈絡",
        "route_context": "路線脈絡",
        "historical_context": "歷史脈絡",
        "cultural_context": "文化脈絡",
        "natural_context": "自然脈絡",
        "terrain_context": "地形脈絡",
        "seasonal_context": "季節脈絡",
        "route_overview": "路線總覽",
        "visual_context": "視覺脈絡",
    }
    return labels.get(str(context_kind or ""), str(context_kind or "路線脈絡"))


def _stop_advisory_text(point: dict[str, Any]) -> str:
    advisory = str(point.get("stop_advisory_candidate") or "")
    mapping = {
        "short_stop_requires_contextual_permission": (
            "可列為 3 分鐘觀察候選；現地仍需通過天氣、地形、隊伍與撤退時間檢查。"
        ),
        "pass_through_or_minimize_exposure": (
            "只作為風險理解點；現地應快速通過，不建議停留拍照。"
        ),
        "context_reference_only": (
            "作為路線理解或補給脈絡，不自動代表停留建議。"
        ),
    }
    return mapping.get(
        advisory,
        "此點是 route-context candidate，需人工審查後才能放入正式行前包。",
    )


def _briefing_itinerary_options(
    route_distance_km: str,
    media_manifest: dict[str, Any],
) -> str:
    options = [
        (
            "2天",
            "2 天 1 夜",
            "標準完成版",
            "把主要路線與雙峰放在同一個活動節奏裡；適合已確認山屋、天氣與隊伍腳程的行程。",
            "建議先拿來討論",
            "primary",
        ),
        (
            "3天",
            "3 天 2 夜",
            "慢走觀察版",
            "把歷史、地形、照片與教學時間拆開，讓雲海保線所、天池、光被八表不只是打卡點。",
            "觀察與教學優先",
            "slow",
        ),
        (
            "壓縮",
            "1 日或壓縮",
            "高門檻版本",
            "只適合條件很完整的人工核准情境；若天氣、電力、隊伍或撤退條件不足，應排除。",
            "缺任一條件就排除",
            "compressed",
        ),
    ]
    rows = "\n".join(
        f"<article class=\"itinerary-option-card {_h(card_class)}\">"
        f"<span class=\"day-pill\">{_h(short)}</span>"
        "<div>"
        f"<b>{_h(name)}</b>"
        f"<p class=\"highlight-meta\">{_h(label)}</p>"
        f"<p>{_h(body)}</p>"
        f"<p class=\"itinerary-decision-cue\">{_h(cue)}</p>"
        "</div>"
        "</article>"
        for short, name, label, body, cue, card_class in options
    )
    visual = _briefing_itinerary_visual(media_manifest)
    return f"""
        <div class="itinerary-board">
          <div class="itinerary-lead">
            {visual}
            <div class="itinerary-lead-body">
            <div>
              <span>建議討論版本</span>
              <strong>2 天 1 夜</strong>
            </div>
            <p>路線摘要距離 {_h(route_distance_km)}。若活動重點包含觀察、攝影或教學，優先討論 3 天 2 夜。</p>
            <div class="itinerary-lens" aria-label="天數判斷">
              <span><b>時間窗</b> 出發前重查山屋、入園、天氣、路況與隊伍腳程。</span>
              <span><b>觀察密度</b> 想講歷史、地形與拍照，就不要把行程排成純趕路。</span>
              <span><b>排除條件</b> 天氣、電力、撤退或隊伍狀態不足時，壓縮版先排除。</span>
            </div>
            </div>
          </div>
          <div class="itinerary-options">{rows}</div>
        </div>
        """


def _briefing_itinerary_visual(media_manifest: dict[str, Any]) -> str:
    image = _briefing_media_for_context(
        media_manifest,
        context_kinds=("route_overview", "viewpoint_context"),
        label_keywords=("能高越嶺道", "高山景觀", "光被八表"),
    )
    if not image:
        return ""
    caption = _first_text(image.get("caption"), image.get("alt"), "路線畫面")
    return (
        "<figure class=\"itinerary-visual\">"
        f"<img loading=\"lazy\" src=\"{_h(image.get('url'))}\" "
        f"alt=\"{_h(image.get('alt') or caption)}\">"
        f"<figcaption>天數判斷畫面 · {_h(caption[:72])}</figcaption>"
        "</figure>"
    )


def _briefing_highlight_cards(
    points: list[dict[str, Any]],
    media_manifest: dict[str, Any],
) -> str:
    if not points:
        return '<p class="muted">No representative route context points yet.</p>'
    images = [
        image
        for image in media_manifest.get("gallery_images", [])
        if isinstance(image, dict) and image.get("url")
    ]
    cards = []
    for index, point in enumerate(points[:6]):
        image = images[index % len(images)] if images else None
        media = ""
        if image:
            media = (
                f"<img loading=\"lazy\" src=\"{_h(image.get('url'))}\" "
                f"alt=\"{_h(image.get('alt') or image.get('caption') or _point_label(point))}\">"
            )
        layers = ", ".join(_str_list(point.get("sec6_layers"))) or "route_context"
        source_detail = (
            f"脈絡層：{layers}; 來源：{_point_source_label(point)}; "
            f"觀察分數：{_briefing_observation_score(point)}"
        )
        cards.append(
            "<article class=\"highlight-card\">"
            f"{media}"
            "<div class=\"highlight-body\">"
            f"<span class=\"tag {_h(_storyline_tag_class(point))}\">{_h(_storyline_action_label(point))}</span>"
            f"<h3>{_h(_point_label(point))}</h3>"
            f"<p class=\"highlight-meta\">{_h(_point_distance_label(point))} · {_h(_briefing_context_kind_label(point.get('context_kind')))}</p>"
            f"<p class=\"highlight-guide-cue\"><b>看什麼</b>：{_h(_sight_look_cue_for_point(point))}</p>"
            f"<p class=\"highlight-question\"><b>隊伍提問</b>：{_h(_sight_question_for_point(point))}</p>"
            f"<p>{_h(_stop_advisory_text(point))}</p>"
            f"<details class=\"highlight-data-details\"><summary>現地審查資訊</summary><code>{_h(source_detail)}</code></details>"
            "</div>"
            "</article>"
        )
    return "\n".join(cards)


def _sight_look_cue_for_point(point: dict[str, Any]) -> str:
    context_kind = str(point.get("context_kind") or "")
    layers = set(_str_list(point.get("sec6_layers")))
    if context_kind == "navigation_context":
        return "路標、轉折、舊路痕、方向感與下一個共同確認點。"
    if context_kind == "resource_context":
        return "補水、休息、衣物調整、腳程落差與下一段時間壓力。"
    if context_kind == "risk_context" or "terrain" in layers:
        return "坡面、崩壁、碎石、風口與隊伍隊形，先決定通過方式。"
    if context_kind in {"viewpoint", "viewpoint_context"} or "observation_point" in layers:
        return "展望、雲霧、風勢與拍照位置是否會干擾通行。"
    if "historical" in layers or "cultural" in layers:
        return "保線、古道、地名與設施脈絡；敏感內容先保留。"
    if "natural" in layers:
        return "林相、草坡、溪溝、濕度與季節變化。"
    return "把這個點當作上一段與下一段路線的共同記憶。"


def _sight_question_for_point(point: dict[str, Any]) -> str:
    context_kind = str(point.get("context_kind") or "")
    layers = set(_str_list(point.get("sec6_layers")))
    if context_kind == "navigation_context":
        return "所有人都知道下一個檢查點與回頭點在哪裡嗎？"
    if context_kind == "resource_context":
        return "現在要補水、加衣、重分配裝備，還是直接往下一段？"
    if context_kind == "risk_context" or "terrain" in layers:
        return "這裡要快速通過、拉開距離，還是允許短暫觀察？"
    if context_kind in {"viewpoint", "viewpoint_context"} or "observation_point" in layers:
        return "停 3 分鐘後，我們要帶走哪個判斷？"
    if "historical" in layers or "cultural" in layers:
        return "這個故事是否有可靠來源，還是只當候選脈絡？"
    return "這個點會改變節奏、停留、撤退或隊伍溝通嗎？"


def _briefing_point_cards(points: list[dict[str, Any]]) -> str:
    if not points:
        return '<p class="muted">No representative route context points yet.</p>'
    cards = []
    for point in points:
        layers = ", ".join(_str_list(point.get("sec6_layers"))) or "route_context"
        cards.append(
            "<article class=\"point\">"
            f"<span class=\"tag\">{_h(point.get('source_tier') or 'unknown')}</span>"
            f"<h3>{_h(_point_label(point))}</h3>"
            f"<p>{_h(_point_distance_label(point))} · {_h(_briefing_context_kind_label(point.get('context_kind')))}</p>"
            f"<p>{_h(_point_source_label(point))}</p>"
            f"<p>脈絡層：{_h(layers)}</p>"
            f"<p class=\"muted\">觀察分數：{_h(_briefing_observation_score(point))}</p>"
            f"<p>{_h(_stop_advisory_text(point))}</p>"
            "</article>"
        )
    return "\n".join(cards)


def _briefing_layer_cards(
    points: list[dict[str, Any]],
    media_manifest: dict[str, Any],
) -> str:
    layer_catalog = [
        (
            "historical",
            "歷史層",
            "古道、警備道、駐在所、隘勇線、伐木路、產業道路、舊聚落、日治時期設施。",
            "",
        ),
        (
            "cultural",
            "文化層",
            "原住民族地名、舊社、獵徑、地方傳說、土地使用變遷。",
            "gold",
        ),
        (
            "natural",
            "自然層",
            "林相變化、植被帶、特殊植物、鳥類、溪流、地質、岩層。",
            "sky",
        ),
        (
            "terrain",
            "地形層",
            "稜線、鞍部、谷線、崩壁、溪谷、展望點、風口。",
            "rust",
        ),
        (
            "seasonal",
            "季節層",
            "花期、楓紅、雲海、溪水期、雨季、蚊蟲、芒草、低溫。",
            "",
        ),
        (
            "observation_point",
            "觀察點",
            "哪些地方值得停 3 分鐘，而不是只趕路通過。",
            "gold",
        ),
    ]
    cards = []
    used_urls: set[str] = set()
    for index, (layer_id, label, description, tag_class) in enumerate(layer_catalog):
        layer_points = [
            point for point in _route_ordered_points(points)
            if layer_id in _str_list(point.get("sec6_layers"))
        ]
        names = "、".join(_unique_point_labels(layer_points, limit=5))
        if not names:
            names = "目前沒有足夠候選點；保留為 source discovery/review gap。"
        class_attr = f"tag {tag_class}".strip()
        talk_track = _layer_talk_track(layer_id, names)
        image = _briefing_unused_media_for_layer(
            layer_id,
            media_manifest,
            used_urls=used_urls,
            fallback_index=index,
        )
        media = _briefing_field_media(image, caption_prefix=label)
        cards.append(
            "<article class=\"layer layer-brief\">"
            f"{media}"
            f"<span class=\"{_h(class_attr)}\">{_h(label)}</span>"
            f"<span class=\"layer-count\">{_h(len(layer_points))} 個候選點</span>"
            f"<h3>{_h(talk_track['headline'])}</h3>"
            f"<p class=\"layer-definition\">{_h(description)}</p>"
            "<div class=\"briefing-script\">"
            "<div class=\"script-row talk-row\">"
            f"<b>講給隊伍聽</b><span>{_h(talk_track['talk'])}</span>"
            "</div>"
            "<div class=\"script-row ask-row\">"
            f"<b>現場提問</b><span>{_h(talk_track['ask'])}</span>"
            "</div>"
            "<div class=\"script-row boundary-row\">"
            f"<b>邊界</b><span>{_h(talk_track['boundary'])}</span>"
            "</div>"
            "</div>"
            "<details class=\"layer-data-details\">"
            "<summary>候選點與邊界</summary>"
            f"<p><b>候選點</b>：{_h(names)}</p>"
            f"<p><b>邊界</b>：{_h(talk_track['boundary'])}</p>"
            "</details>"
            "</article>"
        )
    return "\n".join(cards)


def _briefing_media_for_layer(
    layer_id: str,
    media_manifest: dict[str, Any],
    *,
    fallback_index: int,
) -> dict[str, Any] | None:
    for image in _briefing_media_images(media_manifest):
        anchor = image.get("presentation_anchor")
        anchor_layer = ""
        if isinstance(anchor, dict):
            anchor_layer = str(anchor.get("context_layer") or "")
        if str(image.get("context_layer") or "") == layer_id or anchor_layer == layer_id:
            return image
    selectors = {
        "historical": {
            "context_kinds": ("historical_context", "resource_context", "route_overview"),
            "label_keywords": ("雲海保線所", "能高越嶺道", "保線"),
        },
        "cultural": {
            "context_kinds": ("cultural_context", "resource_context", "route_overview"),
            "label_keywords": ("能高越嶺道", "雲海保線所", "導覽"),
        },
        "natural": {
            "context_kinds": ("natural_context", "viewpoint_context", "route_overview"),
            "label_keywords": ("高山景觀", "雲海", "日出"),
        },
        "terrain": {
            "context_kinds": ("terrain_context", "viewpoint_context", "route_overview"),
            "label_keywords": ("稜線", "光被八表", "導覽圖"),
        },
        "seasonal": {
            "context_kinds": ("seasonal_context", "viewpoint_context"),
            "label_keywords": ("雲海", "日出", "季節"),
        },
        "observation_point": {
            "context_kinds": ("viewpoint_context", "resource_context"),
            "label_keywords": ("光被八表", "雲海保線所", "展望"),
        },
    }
    selector = selectors.get(layer_id, {})
    return _briefing_media_for_context(
        media_manifest,
        context_kinds=tuple(selector.get("context_kinds", ())),
        label_keywords=tuple(selector.get("label_keywords", ())),
        fallback_index=fallback_index,
    )


def _unique_point_labels(points: list[dict[str, Any]], *, limit: int) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for point in points:
        label = _point_label(point)
        if label in seen:
            continue
        seen.add(label)
        labels.append(label)
        if len(labels) >= limit:
            break
    return labels


def _layer_talk_track(layer_id: str, names: str) -> dict[str, str]:
    tracks = {
        "historical": {
            "headline": "把古道與設施說成時間線",
            "talk": f"用 {names} 串起保線、舊路、山屋與人為設施如何改變這條路。",
            "ask": "哪一段是歷史設施，哪一段只是現代路徑或補給點？",
            "boundary": "不要把未審核的地名、遺構或私人筆記當成正式史實。",
        },
        "cultural": {
            "headline": "讓地名與使用方式保持尊重",
            "talk": f"用 {names} 說明地名、舊路徑與土地使用變遷，但不放大敏感位置。",
            "ask": "這個點需要公開精確位置嗎？還是只需要理解脈絡？",
            "boundary": "文化敏感點只作 review candidate；未核准前不公開精確座標。",
        },
        "natural": {
            "headline": "把林相與季節變成觀察線索",
            "talk": f"用 {names} 讓隊伍看見林相、草坡、雲霧與自然環境的轉換。",
            "ask": "現在看到的植被、濕度、雲霧是否和行前預期一致？",
            "boundary": "自然觀察不是安全判定；天氣與地形條件仍要另行檢查。",
        },
        "terrain": {
            "headline": "把地形說成通過策略",
            "talk": f"用 {names} 指出稜線、崩壁、風口、溪谷或固定繩段的通過重點。",
            "ask": "這一段要拉開距離、快速通過，還是可以短停觀察？",
            "boundary": "地形層只能提示 review priority，不可直接宣稱可通行或不可通行。",
        },
        "seasonal": {
            "headline": "把季節變成時間與裝備檢查",
            "talk": f"用 {names} 討論雲海、低溫、雨季、濕滑與日照時間如何改變節奏。",
            "ask": "現在季節條件是否要求提早出發、加衣、補水或縮短停留？",
            "boundary": "季節線索需要搭配 CWA/weather evidence；缺資料時不能假設低風險。",
        },
        "observation_point": {
            "headline": "把值得停變成有條件的短停",
            "talk": f"用 {names} 做 3 分鐘觀察，但每次短停都要有目的與離開條件。",
            "ask": "這一停要看什麼？誰負責看隊伍距離與時間？",
            "boundary": "觀察點不是停留授權；現地條件不好時改為快速通過。",
        },
    }
    return tracks.get(
        layer_id,
        {
            "headline": "把候選脈絡轉成隊伍共同畫面",
            "talk": f"用 {names} 說明這層脈絡如何影響行程理解。",
            "ask": "這個脈絡是否需要在行前或現地重新確認？",
            "boundary": "所有脈絡層都是 candidate-only，需要人工審查。",
        },
    )


def _briefing_p2_cards(source_manifest: dict[str, Any], media_manifest: dict[str, Any]) -> str:
    p2_sources = [
        source
        for source in source_manifest.get("source_report", [])
        if str(source.get("source_tier") or "").startswith("P2")
    ]
    image = _briefing_media_for_context(
        media_manifest,
        context_kinds=("route_overview", "viewpoint_context", "resource_context"),
        label_keywords=("能高越嶺道", "雲海保線所", "光被八表", "天池"),
        fallback_index=2,
    )
    visual = ""
    if image:
        caption = _first_text(image.get("caption"), image.get("alt"), "Scout 回顧需要綁回真實路線畫面")
        visual = (
            "<figure class=\"p2-visual\">"
            f"<img loading=\"lazy\" src=\"{_h(image.get('url'))}\" "
            f"alt=\"{_h(image.get('alt') or caption)}\">"
            f"<figcaption>{_h(caption)}{_briefing_media_source_chips(image)}</figcaption>"
            "</figure>"
        )
    else:
        visual = (
            "<div class=\"p2-visual p2-empty\">"
            "目前缺少可和 Scout 回顧一起呈現的照片；請先匯入有來源紀錄的公開來源或 Scout 自有照片。"
            "</div>"
        )
    if not p2_sources:
        source_cards = '<div class="p2-empty">目前還沒有載入 Scout 自有回顧資料。</div>'
    else:
        cards = []
        for source in p2_sources:
            status = _briefing_source_status_label(source.get("status"))
            role = _briefing_source_role_label(source.get("conclusion_role"))
            count = _h(source.get("loaded_count"))
            cards.append(
                "<article class=\"p2-source-card\">"
                "<div class=\"p2-source-count\">"
                f"<b>{count}</b><span>回顧筆數</span>"
                "</div>"
                "<div>"
                f"<span class=\"tag gold\">Scout 回顧</span>"
                f"<h3>{_h(_briefing_source_name(source.get('source_kind')))}</h3>"
                f"<p><b>目前狀態</b>：{_h(status)}。</p>"
                f"<p><b>簡報用法</b>：{_h(role)}；先用來提醒下一次行前討論，不當作公開結論。</p>"
                f"<details class=\"audit-details\"><summary>來源路徑</summary><code>{_h(source.get('source_path'))}</code></details>"
                "</div>"
                "</article>"
            )
        source_cards = "\n".join(cards)
    return f"""
        <div class="p2-review-board">
          {visual}
          <div class="p2-panel">
            <div class="p2-lens" aria-label="Scout 回顧判讀方式">
              <span><b>先當回顧</b>把隊伍走過、延誤、停留與疑問整理成下一次 briefing 的線索。</span>
              <span><b>再找佐證</b>需要公開來源、地形、天氣或現地觀察交叉確認後，才進入結論層。</span>
              <span><b>保留邊界</b>Scout 回顧是自有線索；公開前需人工審查，不取代現地安全判斷。</span>
            </div>
            <div class="p2-source-stack" aria-label="Scout-owned review sources">
              {source_cards}
            </div>
          </div>
        </div>
    """


def _briefing_route_steps(points: list[dict[str, Any]]) -> str:
    if not points:
        return '<p class="muted">目前還沒有可排成路線節點的行前資料。</p>'
    midpoint = max(1, len(points) // 2)
    groups = [
        ("前段：進入路線與初始判斷", points[:midpoint]),
        ("後段：高山段、回程與複合風險", points[midpoint:]),
    ]
    cards = []
    for heading, group in groups:
        steps = "\n".join(
            "<div class=\"step\">"
            f"<span class=\"time\">{_h(_point_distance_label(point))}</span>"
            "<span>"
            f"<strong>{_h(_point_label(point))}</strong>"
            f"<small>{_h(_storyline_cue_for_point(point))}</small>"
            f"<details class=\"route-data-details\"><summary>來源</summary><code>{_h(_point_source_label(point))}</code></details>"
            "</span>"
            "</div>"
            for point in group[:6]
        )
        cards.append(
            "<article class=\"day-card\">"
            f"<h3>{_h(heading)}</h3>"
            f"<div class=\"steps\">{steps}</div>"
            "</article>"
        )
    return "\n".join(cards)


def _briefing_story_steps(
    points: list[dict[str, Any]],
    media_manifest: dict[str, Any],
) -> str:
    if not points:
        return '<p class="muted">目前還沒有路線敘事候選點。</p>'
    cards = []
    previous_image_url = ""
    for index, point in enumerate(points):
        image = _briefing_storyline_image_for_point(
            media_manifest,
            point,
            fallback_index=index,
            previous_image_url=previous_image_url,
        )
        previous_image_url = str((image or {}).get("url") or "")
        layers = ", ".join(_str_list(point.get("sec6_layers"))) or "route_context"
        cards.append(
            "<article class=\"storyline-card\">"
            f"{_briefing_storyline_thumb(image, point)}"
            "<div class=\"storyline-meta\">"
            f"<span class=\"storyline-index\">節點 {index + 1:02d}</span>"
            f"<span class=\"storyline-distance\">{_h(_point_distance_label(point))}</span>"
            f"<span class=\"tag {_h(_storyline_tag_class(point))}\">"
            f"{_h(_briefing_context_kind_label(point.get('context_kind')))}</span>"
            "</div>"
            f"<h3>{_h(_point_label(point))}</h3>"
            f"<p class=\"storyline-cue\">{_h(_storyline_cue_for_point(point))}</p>"
            "<p class=\"storyline-action\">"
            f"<b>{_h(_storyline_action_label(point))}</b>{_h(_stop_advisory_text(point))}"
            "</p>"
            "<details class=\"storyline-data-details\">"
            "<summary>資料與邊界</summary>"
            f"<p>來源：{_h(_point_source_label(point))}</p>"
            f"<p>脈絡層：{_h(layers)}</p>"
            "<p>candidate-only; runtime_safety_truth=false; human_review_required=true</p>"
            "</details>"
            "</article>"
        )
    return "\n".join(cards)


def _briefing_storyline_image_for_point(
    media_manifest: dict[str, Any],
    point: dict[str, Any],
    *,
    fallback_index: int,
    previous_image_url: str,
) -> dict[str, Any] | None:
    images = _briefing_media_images(media_manifest)
    if not images:
        return None
    label = _point_label(point)
    exact_matches = []
    for image in images:
        anchor = image.get("presentation_anchor")
        if not isinstance(anchor, dict):
            continue
        if str(anchor.get("label") or "") == label:
            exact_matches.append(image)
    start = fallback_index % len(images)
    rotated_images = images[start:] + images[:start]
    candidates = exact_matches + [
        image for image in rotated_images if image not in exact_matches
    ]
    for image in candidates:
        url = str(image.get("url") or "")
        if url and url != previous_image_url:
            return image
    return candidates[0] if candidates else None


def _briefing_storyline_thumb(
    image: dict[str, Any] | None,
    point: dict[str, Any],
) -> str:
    if not image or not image.get("url"):
        return ""
    anchor = image.get("presentation_anchor")
    if not isinstance(anchor, dict):
        anchor = {}
    caption = _first_text(
        image.get("caption"),
        image.get("alt"),
        anchor.get("label"),
        _point_label(point),
    )
    return (
        "<figure class=\"storyline-thumb\">"
        f"<img loading=\"lazy\" src=\"{_h(image.get('url'))}\" "
        f"alt=\"{_h(image.get('alt') or caption)}\">"
        f"<figcaption>{_h(caption[:96])}</figcaption>"
        "</figure>"
    )


def _storyline_tag_class(point: dict[str, Any]) -> str:
    context_kind = str(point.get("context_kind") or "")
    if context_kind == "risk_context":
        return "rust"
    if context_kind == "resource_context":
        return "gold"
    return "sky"


def _storyline_cue_for_point(point: dict[str, Any]) -> str:
    context_kind = str(point.get("context_kind") or "")
    layers = set(_str_list(point.get("sec6_layers")))
    if context_kind == "risk_context" or "terrain" in layers:
        return "先把這裡講成通過策略，不把它講成停留點。"
    if context_kind == "navigation_context":
        return "先確認方向、隊伍共同點與下一個檢查點，再讓隊伍離開。"
    if context_kind == "resource_context":
        return "把它當成補水、衣物、腳程與時間壓力的共同檢查點。"
    if "historical" in layers or "cultural" in layers:
        return "用故事建立路線記憶，但不要公開或放大敏感位置。"
    if context_kind == "viewpoint" or "observation_point" in layers:
        return "可以成為短停候選，但停留要有目的、邊界與離開條件。"
    return "用這個節點把上一段與下一段路線說清楚。"


def _storyline_action_label(point: dict[str, Any]) -> str:
    advisory = str(point.get("stop_advisory_candidate") or "")
    if advisory == "pass_through_or_minimize_exposure":
        return "通過策略"
    if advisory == "short_stop_requires_contextual_permission":
        return "短停條件"
    if advisory == "context_reference_only":
        return "講解節點"
    return "人工審查"


def _briefing_stop_cards(
    points: list[dict[str, Any]],
    media_manifest: dict[str, Any],
) -> str:
    if not points:
        return '<p class="muted">目前還沒有 3 分鐘觀察點候選。</p>'
    cards = []
    for index, point in enumerate(points):
        prompt = _observation_prompt_for_point(point)
        media = _briefing_field_media(
            _briefing_media_for_point(media_manifest, point, fallback_index=index),
            caption_prefix="短停畫面",
        )
        cards.append(
            "<article class=\"point\">"
            f"{media}"
            f"<span class=\"tag sky\">{_h(_point_distance_label(point))}</span>"
            f"<h3>{_h(_point_label(point))}</h3>"
            f"<p>{_h(prompt['setup'])}</p>"
            "<div class=\"briefing-script\">"
            "<div class=\"script-row\">"
            f"<b>觀察重點</b><span>{_h(prompt['observe'])}</span>"
            "</div>"
            "<div class=\"script-row\">"
            f"<b>隊伍提問</b><span>{_h(prompt['ask'])}</span>"
            "</div>"
            "<div class=\"script-row\">"
            f"<b>離開條件</b><span>{_h(prompt['leave'])}</span>"
            "</div>"
            "</div>"
            "<details class=\"audit-details\">"
            "<summary>現地審查資訊</summary>"
            f"<code>review_state={_h(point.get('review_state'))}; "
            f"sensitivity={_h(point.get('sensitivity_level'))}; "
            f"advisory={_h(point.get('stop_advisory_candidate'))}</code>"
            "</details>"
            "</article>"
        )
    return "\n".join(cards)


def _observation_prompt_for_point(point: dict[str, Any]) -> dict[str, str]:
    label = _point_label(point)
    context_kind = str(point.get("context_kind") or "")
    layers = set(_str_list(point.get("sec6_layers")))
    base = {
        "setup": "這是 3 分鐘觀察候選，不是停留授權；現地仍需先看天氣、地形暴露、隊伍間距與撤退時間。",
        "observe": "快速建立共同畫面：位置、路線方向、地形特徵與下一段節奏。",
        "ask": "全員是否跟上、是否需要補水或調整衣物、是否還能在預定時間內離開？",
        "leave": "3 分鐘到或任一條件變差就離開；若能見度、風勢、隊伍間距或時間壓力不佳，改為快速通過。",
    }
    if context_kind == "navigation_context":
        base.update(
            {
                "observe": f"用 {label} 確認岔路、舊路跡、轉向與預定路線方向，避免隊伍在相似路徑間分散。",
                "ask": "前後隊是否都知道接下來往哪裡走？最後一位是否已到齊並看見轉折？",
                "leave": "確認全隊到齊、方向一致、下一個檢核點明確後再離開；不確定時不要邊走邊猜。",
            }
        )
    elif context_kind == "viewpoint" or "observation_point" in layers:
        base.update(
            {
                "observe": f"在 {label} 只取必要畫面：稜線、鞍部、風口、雲霧移動與下一段暴露程度。",
                "ask": "現在風、霧、光線與隊伍保暖是否允許短停？有人拍照時是否太靠近邊緣？",
                "leave": "風變強、雲霧壓低、有人離邊緣太近或隊伍拉開時立即離開。",
            }
        )
    elif context_kind == "resource_context":
        base.update(
            {
                "observe": f"把 {label} 當成隊伍狀態檢查點：補水、衣物、時間、腳程與下一段爬升。",
                "ask": "有人需要吃東西、調整衣物或回報不舒服嗎？下一段是否仍符合原本節奏？",
                "leave": "完成補給與點名後離開；若時間落後或天氣轉差，改走撤退/保守版本。",
            }
        )
    elif "historical" in layers or "cultural" in layers:
        base.update(
            {
                "observe": f"用 {label} 說明歷史/文化脈絡，但不要踩踏、移動或放大敏感位置。",
                "ask": "這個點只需要理解，不需要深入探索；隊伍是否知道下一段路線與集合方式？",
                "leave": "拍照與講解收斂在 3 分鐘內；若涉及敏感文化資訊，只保留概念，不公開精確位置。",
            }
        )
    elif context_kind == "risk_context" or "terrain" in layers:
        base.update(
            {
                "setup": "這類點只作為風險理解，不建議停留拍照。",
                "observe": f"快速辨識 {label} 的坡面、落石、滑墜停止點、濕滑與繞行線索。",
                "ask": "是否需要拉開距離、收杖、戴手套或改成逐一通過？",
                "leave": "不要聚集；確認通過策略後立即前進或後撤。",
            }
        )
    return base


def _briefing_risk_cards(
    risk_points: list[dict[str, Any]],
    nav_points: list[dict[str, Any]],
    media_manifest: dict[str, Any],
) -> str:
    risk_names = _risk_review_names(risk_points, "目前沒有風險脈絡候選點")
    nav_names = _risk_review_names(nav_points, "目前沒有導航脈絡候選點")
    cards = [
        {
            "tag": "邊界提醒",
            "scene": "先看路線場景",
            "title": "先守住安全邊界",
            "cue": "這份簡報只能提示人工審查，不會自動判定可通行或不可通行。",
            "action_label": "通過前",
            "action": "把任何模型文字都當成討論提示；現地安全仍以實際天氣、導航與領隊判斷為準。",
            "operator_note": "簡報只建立共同語言，真正的出發或撤退決定要回到人工審查。",
            "detail": "不得寫入 /safety/*，不得改 Phase 1 runtime safety，也不得把模型文字升級成 safety truth。",
            "context_kinds": ("route_overview", "visual_context"),
            "label_keywords": ("導覽圖", "能高越嶺道"),
        },
        {
            "tag": "通過策略",
            "scene": "高暴露段",
            "title": "高風險段少停、分批過",
            "cue": "遇到崩壁、稜線、風口、固定繩或濕滑坡面，先討論隊形與通過節奏。",
            "action_label": "現場做",
            "action": "拉開距離、逐一通過、收斂拍照；條件不清楚時不要把它當觀察點。",
            "operator_note": "把畫面翻成隊形、距離與通過順序，不把風景翻成停留理由。",
            "detail": f"風險脈絡候選：{risk_names}",
            "context_kinds": ("viewpoint_context", "route_overview"),
            "label_keywords": ("稜線", "高山景觀", "光被八表"),
        },
        {
            "tag": "停留條件",
            "scene": "漂亮但不一定能停",
            "title": "能不能停，取決於當下條件",
            "cue": "景色漂亮不等於可以停。短停前要同時看天氣、能見度、隊伍距離與撤退時間。",
            "action_label": "停留前",
            "action": "只允許有目的的短停；任何一項條件不通過，就改成快速通過。",
            "operator_note": "先問現地條件，再決定是否停；不要先決定要拍照再找理由。",
            "detail": "這些停留條件只作 pretrip briefing；現地仍需 contextual permission 檢查。",
            "context_kinds": ("viewpoint_context", "resource_context"),
            "label_keywords": ("日出", "雲海", "展望"),
        },
        {
            "tag": "撤退提醒",
            "scene": "缺資料就保守",
            "title": "缺資料時，回答要更保守",
            "cue": "官方狀態、天氣、山屋、道路或地形資料缺失時，不要把缺資料解讀成安全。",
            "action_label": "回答方式",
            "action": "明確說資料缺口，請領隊補查；必要時把出發或撤退決定提升到人工審查。",
            "operator_note": "這張卡提醒 Scout AI：不知道不是安全，而是需要補證據。",
            "detail": "Scout AI 應回報資料缺口，而不是假裝安全。",
            "context_kinds": ("route_overview", "resource_context"),
            "label_keywords": ("導覽圖", "天池山莊", "山屋"),
        },
        {
            "tag": "導航檢查",
            "scene": "轉折前停一下腦袋",
            "title": "轉折和偏離要先查清楚",
            "cue": "導航脈絡候選代表隊伍可能需要提前確認轉折、方向和回頭點。",
            "action_label": "通過前",
            "action": "在轉折前確認路線方向、下一個檢查點、隊伍共同點與最近安全回頭點。",
            "operator_note": "轉折點要形成共同認知；不確定時不要讓前後隊各自猜。",
            "detail": f"導航脈絡候選：{nav_names}",
            "context_kinds": ("route_overview", "navigation_context"),
            "label_keywords": ("導覽圖", "路線", "能高越嶺道"),
        },
    ]
    rendered_cards = []
    previous_image_url = ""
    for index, card in enumerate(cards):
        image = _briefing_risk_image_for_card(
            media_manifest,
            context_kinds=tuple(card["context_kinds"]),
            label_keywords=tuple(card["label_keywords"]),
            fallback_index=index,
            previous_image_url=previous_image_url,
        )
        previous_image_url = str((image or {}).get("url") or "")
        rendered_cards.append(
            "<article class=\"risk-review-card\">"
            f"{_briefing_risk_visual(image, str(card['scene']))}"
            "<div class=\"storyline-meta\">"
            f"<span class=\"tag rust\">{_h(card['tag'])}</span>"
            f"<span class=\"risk-scene-label\">{_h(card['scene'])}</span>"
            "</div>"
            f"<h3>{_h(card['title'])}</h3>"
            f"<p class=\"risk-cue\">{_h(card['cue'])}</p>"
            f"<p class=\"risk-action\"><b>{_h(card['action_label'])}</b>{_h(card['action'])}</p>"
            f"<p class=\"risk-operator-note\">{_h(card['operator_note'])}</p>"
            "<details class=\"risk-data-details\">"
            "<summary>資料與邊界</summary>"
            f"<p>{_h(card['detail'])}</p>"
            "</details>"
            "</article>"
        )
    return "\n".join(rendered_cards)


def _briefing_risk_image_for_card(
    media_manifest: dict[str, Any],
    *,
    context_kinds: tuple[str, ...],
    label_keywords: tuple[str, ...],
    fallback_index: int,
    previous_image_url: str,
) -> dict[str, Any] | None:
    images = _briefing_media_images(media_manifest)
    if not images:
        return None
    preferred = []
    for image in images:
        anchor = image.get("presentation_anchor")
        if not isinstance(anchor, dict):
            anchor = {}
        context = str(anchor.get("context_kind") or "")
        label = _media_search_text(image) + " " + str(anchor.get("label") or "")
        if label_keywords and any(keyword in label for keyword in label_keywords):
            preferred.append(image)
            continue
        if context_kinds and context in context_kinds:
            preferred.append(image)
    start = fallback_index % len(images)
    rotated = images[start:] + images[:start]
    candidates = preferred + [image for image in rotated if image not in preferred]
    for image in candidates:
        url = str(image.get("url") or "")
        if url and url != previous_image_url:
            return image
    return candidates[0] if candidates else None


def _briefing_risk_visual(image: dict[str, Any] | None, scene: str) -> str:
    if not image or not image.get("url"):
        return ""
    caption = _first_text(image.get("caption"), image.get("alt"), scene)
    return (
        "<figure class=\"risk-visual\">"
        f"<img loading=\"lazy\" src=\"{_h(image.get('url'))}\" "
        f"alt=\"{_h(image.get('alt') or caption)}\">"
        f"<figcaption>{_h(scene)} · {_h(caption[:72])}</figcaption>"
        "</figure>"
    )


def _risk_review_names(points: list[dict[str, Any]], empty: str) -> str:
    names = "、".join(_point_label(point) for point in points[:5])
    return names or empty


def _briefing_schedule_cards(
    route_distance_km: str,
    media_manifest: dict[str, Any],
) -> str:
    versions = [
        {
            "name": "標準完成版",
            "duration": "2 天 1 夜",
            "decision": "建議主案",
            "class_name": "primary",
            "summary": (
                f"以 {_h(route_distance_km)} 路線摘要討論主線完成；適合已確認山屋、天氣、"
                "隊伍腳程與撤退時間的行程。"
            ),
            "gate": "山屋/入園、天氣窗口、隊伍腳程、撤退時間與離線地圖都已確認。",
            "days": [
                (
                    "D1",
                    "進入路線，抵達住宿節點",
                    "用雲海保線所、黑水塘等節點檢查腳程與補水；傍晚前確認住宿與隔日天氣。",
                ),
                (
                    "D2",
                    "清晨出發，完成雙峰與回程",
                    "把稜線啞口、光被八表與高山段當作時間壓力檢查點；延誤時優先保守撤退。",
                ),
            ],
        },
        {
            "name": "慢走觀察版",
            "duration": "3 天 2 夜",
            "decision": "觀察主案",
            "class_name": "slow",
            "summary": "把歷史、文化、自然、地形、季節與 Scout 回顧拆開，不把所有觀察壓在第二天。",
            "gate": "活動目標包含教學、攝影、隊伍節奏保守，或需要更多緩衝時間。",
            "days": [
                (
                    "D1",
                    "進入山區並建立路線共同畫面",
                    "第一天只做節奏校準、補給檢查與雲海保線所短講，不急著消耗隊伍餘裕。",
                ),
                (
                    "D2",
                    "雙峰、稜線與展望觀察日",
                    "把光被八表、稜線啞口、風口與天氣變化作為教學主題；每次停留都要有離開條件。",
                ),
                (
                    "D3",
                    "回程整理與 Scout 回顧",
                    "下山途中補足未看的歷史/自然點，並收集照片點、停留點、語音註記給下一次簡報。",
                ),
            ],
        },
    ]
    photo_strip = _briefing_schedule_photo_strip(media_manifest)
    focus_strip = """
        <section class="schedule-focus-strip" aria-label="行程頁主判斷">
          <div class="schedule-focus-lead">
            <p class="kicker">領隊先做版本選擇</p>
            <h3>主案是 2 天 1 夜；需要教學、攝影或保守節奏時，改用 3 天 2 夜。</h3>
            <p>壓縮行程不進預設建議，只在所有關鍵條件都充分時才交給人工討論。</p>
          </div>
          <div class="schedule-focus-item">
            <b>建議主案</b>
            <span>2 天 1 夜：山屋、天氣、隊伍腳程與撤退時間都確認後才採用。</span>
          </div>
          <div class="schedule-focus-item">
            <b>觀察版本</b>
            <span>3 天 2 夜：把教學、攝影、歷史與地形觀察拆開，不擠在同一天。</span>
          </div>
          <div class="schedule-focus-item">
            <b>排除條件</b>
            <span>缺任一關鍵資料，或隊伍狀態不明，就不要採壓縮版本。</span>
          </div>
        </section>
    """
    gate_panel = f"""
        <div class="schedule-decision-board">
          <div>{photo_strip}</div>
          <div class="schedule-gate-panel">
            <span class="schedule-decision-tag">人工行程審查</span>
            <h3>先確認能不能照原計畫走</h3>
            <p>行程版本只能進入人工討論；任何關鍵條件不完整，都要先補資料或改採保守版本。</p>
            <div class="schedule-gates" aria-label="行程版本 gate">
              <span><b>官方與天氣</b>入園、山屋、道路、官方天氣與警特報都要重查。</span>
              <span><b>隊伍狀態</b>腳程、疲勞、傷勢、隊距與撤退條件必須明確。</span>
              <span><b>裝置與導航</b>離線地圖、定位與感測、電力與通訊都要有備援。</span>
              <span><b>保守原則</b>缺資料不是安全；缺任一關鍵條件就升級人工審查。</span>
            </div>
          </div>
        </div>
    """
    boards = []
    for version in versions:
        days = "\n".join(
            "<div class=\"day-plan\">"
            f"<b>{_h(day)}</b>"
            "<div>"
            f"<h3>{_h(title)}</h3>"
            f"<p>{_h(body)}</p>"
            "</div>"
            "</div>"
            for day, title, body in version["days"]
        )
        boards.append(
            f"<article class=\"schedule-version {_h(version['class_name'])}\">"
            "<div class=\"schedule-version-head\">"
            f"<span class=\"schedule-decision-tag\">{_h(version['decision'])}</span>"
            f"<span>{_h(version['name'])}</span>"
            f"<strong>{_h(version['duration'])}</strong>"
            f"<p>{version['summary']}</p>"
            "</div>"
            "<div class=\"schedule-version-gate\">"
            f"<b>採用條件</b>{_h(version['gate'])}"
            "</div>"
            f"{days}"
            "</article>"
        )
    return (
        focus_strip
        +
        gate_panel
        +
        '<div class="schedule-board">'
        + "\n".join(boards)
        + "</div>"
        + '<div class="schedule-caution">'
        + "<strong>壓縮行程只保留為人工核准候選，不進入預設建議。</strong>"
        + "<p>只有官方狀態、天氣窗口、隊伍體能、電力、導航可信度與撤退條件都充分時，才應列入討論。</p>"
        + "</div>"
    )


def _briefing_schedule_photo_strip(media_manifest: dict[str, Any]) -> str:
    images = _briefing_media_images(media_manifest)[:4]
    if not images:
        return ""
    figures = "\n".join(
        _briefing_field_media(image, caption_prefix="行程節奏")
        for image in images
    )
    return f'<div class="schedule-photo-strip">{figures}</div>'


def _briefing_source_summary(source_manifest: dict[str, Any]) -> dict[str, int]:
    summary = {
        "loaded_source_count": 0,
        "p0_count": 0,
        "p1_count": 0,
        "p2_count": 0,
    }
    for source in source_manifest.get("source_report", []):
        if source.get("status") == "loaded":
            summary["loaded_source_count"] += 1
        tier_counts = source.get("source_tier_counts")
        if isinstance(tier_counts, dict):
            summary["p0_count"] += int(tier_counts.get("P0") or 0)
            summary["p1_count"] += int(tier_counts.get("P1") or 0)
            summary["p2_count"] += int(tier_counts.get("P2") or 0)
            continue
        tier = str(source.get("source_tier") or "")
        if tier.startswith("P0"):
            summary["p0_count"] += 1
        elif tier.startswith("P1"):
            summary["p1_count"] += 1
        elif tier.startswith("P2"):
            summary["p2_count"] += 1
    return summary


def _briefing_source_tier_spine(source_manifest: dict[str, Any]) -> str:
    cards = "\n".join(
        _briefing_source_tier_card(source_manifest, tier)
        for tier in ("P0", "P1", "P2")
    )
    return f"""
        <section class="source-tier-spine" aria-label="P0 P1 P2 來源脊柱">
          <div>
            <p class="kicker">P0 / P1 / P2 來源脊柱</p>
            <h3>官方、擴展、自有回顧要分開看，不能混成一團可信度。</h3>
            <p>這三欄是未來所有路線 briefing 的固定模板：P0 立底線，P1 補廣度，P2 補這支隊伍走過後的深度；全部都維持行前 candidate-only。</p>
          </div>
          <div class="source-tier-grid">
            {cards}
          </div>
        </section>
        """


def _briefing_source_tier_card(source_manifest: dict[str, Any], tier: str) -> str:
    loaded = _source_report_for_tier(source_manifest, tier)
    count = _source_tier_loaded_count(source_manifest, tier)
    items = "".join(
        f"<li>{_h(_briefing_source_name(source.get('source_kind')))}"
        f" · {_h(_briefing_source_status_label(source.get('status')))}"
        f" · {_h(source.get('loaded_count'))}</li>"
        for source in loaded[:4]
    )
    if not items:
        items = "<li>目前缺資料，不能假裝已查證。</li>"
    copy = {
        "P0": (
            "官方底線",
            "路線、狀態、地形、天候與救援等 baseline；簡報先用它建立基本可信度。",
        ),
        "P1": (
            "擴展脈絡",
            "社群路線、OSM/Overpass、地名、地質、文化與文章補足深度和廣度。",
        ),
        "P2": (
            "Scout 回顧",
            "完成旅程、route notes、停留、偏航與隊伍資料只作 Scout-local 回顧。",
        ),
    }
    title, body = copy.get(tier, (tier, "來源資料"))
    return (
        f"<article class=\"source-tier-card {tier.lower()}\">"
        f"<span>{_h(tier)}</span>"
        f"<b>{_h(title)}</b>"
        f"<p>{_h(body)}</p>"
        f"<small>已載入 {_h(count)} 類資料</small>"
        f"<ul>{items}</ul>"
        "</article>"
    )


def _source_report_for_tier(source_manifest: dict[str, Any], tier: str) -> list[dict[str, Any]]:
    target = tier.upper()
    return [
        source
        for source in source_manifest.get("source_report", [])
        if isinstance(source, dict)
        and str(source.get("source_tier") or "").upper().startswith(target)
        and source.get("status") == "loaded"
    ]


def _source_tier_loaded_count(source_manifest: dict[str, Any], tier: str) -> int:
    return len(_source_report_for_tier(source_manifest, tier))


def _briefing_source_health_panel(
    source_manifest: dict[str, Any],
    source_summary: dict[str, int],
    boundary: dict[str, Any],
) -> str:
    required = _str_list(source_manifest.get("required_missing_source_kinds"))
    optional = _str_list(source_manifest.get("optional_missing_source_kinds"))
    cache_policy = source_manifest.get("cache_policy")
    if not isinstance(cache_policy, dict):
        cache_policy = {}
    live_fetch = bool(cache_policy.get("live_fetch_performed"))
    refresh_required = bool(cache_policy.get("refresh_required_before_runtime_truth"))
    source_report = [
        source
        for source in source_manifest.get("source_report", [])
        if isinstance(source, dict)
    ]
    missing_label = (
        "無必要缺口"
        if not required
        else "必要缺口：" + "、".join(required)
    )
    optional_label = "可補強：" + "、".join(optional) if optional else "無可補強缺口"
    boundary_raw = "; ".join(
        (
            f"candidate_only={str(boundary.get('candidate_only')).lower()}",
            f"runtime_safety_truth={str(boundary.get('runtime_safety_truth')).lower()}",
            f"live_safety_api_called={str(boundary.get('safety_api_called')).lower()}",
            f"source_fulltext_embedded={str(boundary.get('source_fulltext_embedded')).lower()}",
        )
    )
    source_status = "、".join(
        f"{_briefing_source_name(source.get('source_kind'))}:{_briefing_source_status_label(source.get('status'))}"
        for source in source_report
    )
    return f"""
        <div class="source-health-board">
          <div class="source-health-summary">
            <span class="schedule-decision-tag">operator data mode</span>
            <h3>來源健康先讀，再給 Scout AI 回答</h3>
            <p>這個區塊用來快速判斷：哪些資料可以支撐簡報，哪些只是 seed，哪些缺口需要在回答時明講。</p>
            <div class="source-health-score" aria-label="來源摘要">
              <span><b>{_h(source_summary['loaded_source_count'])}</b>已載入來源</span>
              <span><b>{_h(source_summary['p0_count'])}</b>P0 官方訊號</span>
              <span><b>{_h(source_summary['p2_count'])}</b>P2 自有 seed</span>
            </div>
          </div>
          <div class="source-health-grid">
            <article class="source-health-card">
              <div class="health-pill-row">
                <span class="health-pill">P0 {_h(source_summary['p0_count'])}</span>
                <span class="health-pill">P1 {_h(source_summary['p1_count'])}</span>
                <span class="health-pill">P2 {_h(source_summary['p2_count'])}</span>
              </div>
              <h3>可回答範圍</h3>
              <p>已載入來源可支撐行前脈絡、照片導覽、路線故事與候選停留點；仍不得當作 runtime safety truth。</p>
              <details class="source-health-details"><summary>來源狀態列表</summary><code>{_h(source_status)}</code></details>
            </article>
            <article class="source-health-card warning">
              <div class="health-pill-row">
                <span class="health-pill warning">{_h(missing_label)}</span>
                <span class="health-pill warning">{_h(optional_label)}</span>
              </div>
              <h3>缺口處理</h3>
              <p>缺資料時回答要更保守；缺口不能被解讀成低風險或安全。</p>
              <small>出發前仍要重新整理官方狀態、天氣、路況、山屋與入園資訊。</small>
            </article>
            <article class="source-health-card">
              <div class="health-pill-row">
                <span class="health-pill">{_h(str(cache_policy.get('mode') or 'cache_first'))}</span>
                <span class="health-pill {'warning' if live_fetch else ''}">live fetch {_h('on' if live_fetch else 'off')}</span>
              </div>
              <h3>快取策略</h3>
              <p>這份簡報來自 workspace cache 與 operator-approved collection；不在 runtime 自動 live search。</p>
              <small>{_h('runtime truth 前需 refresh' if refresh_required else '未標示 refresh requirement')}</small>
            </article>
            <article class="source-health-card locked">
              <div class="health-pill-row">
                <span class="health-pill">candidate-only</span>
                <span class="health-pill">非安全真值</span>
              </div>
              <h3>安全邊界</h3>
              <p>這份簡報只供行前討論與人工審查；不寫入 /safety/*，也不取代現地判斷。</p>
              <details class="source-health-details"><summary>機器可讀邊界</summary><code>{_h(boundary_raw)}</code></details>
            </article>
          </div>
        </div>
    """


def _briefing_source_trust_panel(
    source_manifest: dict[str, Any],
    media_manifest: dict[str, Any],
) -> str:
    source_report = [
        source
        for source in source_manifest.get("source_report", [])
        if isinstance(source, dict)
    ]
    loaded = [source for source in source_report if source.get("status") == "loaded"]
    briefing_sources = [
        source
        for source in loaded
        if str(source.get("source_tier") or "").startswith(("P0", "P1"))
        and str(source.get("conclusion_role") or "")
        in {
            "primary_briefing_evidence",
            "representative_candidate",
            "representative_candidate_after_review",
            "route_scope",
        }
    ]
    seed_sources = [
        source
        for source in loaded
        if str(source.get("conclusion_role") or "") == "seed_only"
        or str(source.get("source_kind") or "") == "route_note_candidates"
    ]
    required_missing = _str_list(source_manifest.get("required_missing_source_kinds"))
    optional_missing = _str_list(source_manifest.get("optional_missing_source_kinds"))
    cache_policy = source_manifest.get("cache_policy")
    if not isinstance(cache_policy, dict):
        cache_policy = {}

    briefing_names = "、".join(
        _briefing_source_name(source.get("source_kind")) for source in briefing_sources[:3]
    )
    if len(briefing_sources) > 3:
        briefing_names += f" 等 {len(briefing_sources)} 類"
    if not briefing_names:
        briefing_names = "尚未載入可支撐簡報的 P0/P1 來源"

    seed_count = sum(int(source.get("loaded_count") or 0) for source in seed_sources)
    missing_text = (
        "沒有必要來源缺口；出發前仍需重新整理官方狀態、天氣與路況。"
        if not required_missing
        else "必要缺口：" + "、".join(_briefing_source_name(kind) for kind in required_missing)
    )
    if optional_missing:
        missing_text += " 可補強：" + "、".join(
            _briefing_source_name(kind) for kind in optional_missing
        )
    live_fetch = "沒有 live fetch" if cache_policy.get("live_fetch_performed") is False else "需確認 live fetch 狀態"
    refresh = (
        "出發前仍需 refresh"
        if cache_policy.get("refresh_required_before_runtime_truth")
        else "未標示 refresh requirement"
    )
    source_table_action = (
        "切到資料模式可看完整來源表、crawl seed 與 source tier catalog。"
    )

    cards = [
        {
            "style": "good",
            "label": "信任摘要",
            "metric": str(len(briefing_sources)),
            "cue": f"{briefing_names} 可支撐這份行前簡報。",
            "action_label": "簡報時",
            "action": "可以先引用這些來源建立共同畫面，但仍要在出發前 refresh 官方狀態。",
        },
        {
            "style": "warn" if required_missing or optional_missing else "good",
            "label": "缺口",
            "metric": str(len(required_missing) + len(optional_missing)),
            "cue": missing_text,
            "action_label": "缺資料時",
            "action": "明確說資料缺口，不把缺資料解讀成安全，也不直接給出發結論。",
        },
        {
            "style": "warn",
            "label": "可追溯資料",
            "metric": str(seed_count),
            "cue": "路線筆記與 Scout 自有回顧可提出線索，但不能單獨形成結論。",
            "action_label": "要查證",
            "action": source_table_action,
        },
        {
            "style": "boundary",
            "label": "安全邊界",
            "metric": "行前",
            "cue": f"{live_fetch}；{refresh}。",
            "action_label": "不可做",
            "action": "不得把這份簡報、模型文字或 P2 筆記升級為現地安全真值。",
        },
    ]
    return (
        '<div class="source-trust-layout">'
        f"{_briefing_source_trust_visual(media_manifest)}"
        '<div class="trust-board source-brief-grid source-path" aria-label="來源信任路徑">'
        + "\n".join(
            "<article class=\"trust-card "
            + _h(str(card["style"]))
            + " source-brief-card\">"
            + f"<span class=\"source-step-index\">{index:02d}</span>"
            + "<div class=\"source-card-body\">"
            + f"<span class=\"tag\">{_h(card['label'])}</span>"
            + f"<b>{_h(card['metric'])}</b>"
            + f"<p class=\"source-cue\">{_h(card['cue'])}</p>"
            + f"<p class=\"source-action\"><b>{_h(card['action_label'])}</b>{_h(card['action'])}</p>"
            + "</div>"
            + "</article>"
            for index, card in enumerate(cards, 1)
        )
        + "</div>"
        + "</div>"
    )


def _briefing_source_trust_visual(media_manifest: dict[str, Any]) -> str:
    image = _briefing_media_for_context(
        media_manifest,
        context_kinds=("route_overview", "visual_context"),
        label_keywords=("導覽圖", "能高越嶺道", "高山景觀"),
        fallback_index=0,
    )
    if not image:
        return (
            '<div class="source-trust-visual">'
            '<div class="source-trust-caption">目前沒有可用的來源代表圖；請切到資料模式查看來源表。</div>'
            "</div>"
        )
    caption = _first_text(image.get("caption"), image.get("alt"), "來源代表圖")
    return (
        '<figure class="source-trust-visual">'
        f"<img loading=\"lazy\" src=\"{_h(image.get('url'))}\" "
        f"alt=\"{_h(image.get('alt') or caption)}\">"
        '<figcaption class="source-trust-caption">'
        f"<span>來源代表圖 · {_h(caption[:88])}</span>"
        f"{_briefing_media_source_chips(image)}"
        "</figcaption>"
        "</figure>"
    )


def _briefing_source_name(source_kind: Any) -> str:
    names = {
        "mcp_candidates": "主要檢查點",
        "named_point_evidence": "命名點與地圖標註",
        "ocr_label_evidence": "地圖 OCR 標籤",
        "web_case_evidence": "官方/公開網頁案例",
        "raster_label_evidence": "Raster 標籤",
        "route_note_candidates": "路線筆記候選",
        "import_manifest": "匯入清單",
        "route_summary": "路線摘要",
    }
    return names.get(str(source_kind or ""), str(source_kind or "未知來源"))


def _briefing_source_status_label(status: Any) -> str:
    labels = {
        "loaded": "已載入",
        "missing": "尚缺",
        "ready": "可用",
        "ready_from_p0_p1_sources": "已由 P0/P1 來源建立",
        "metadata_only_fixture": "metadata fixture",
    }
    return labels.get(str(status or ""), str(status or "未知"))


def _briefing_source_role_label(role: Any) -> str:
    labels = {
        "candidate_input": "候選輸入",
        "source_discovery": "來源探索",
        "context_seed": "脈絡 seed",
        "provenance_only": "僅作 provenance",
        "summary_reference": "摘要參照",
        "workspace_baseline": "workspace 基礎資料",
        "representative_candidate": "代表性候選",
        "representative_candidate_after_review": "審查後代表性候選",
        "primary_briefing_evidence": "主要簡報證據",
        "seed_only": "僅作 seed",
        "route_scope": "路線範圍",
    }
    return labels.get(str(role or ""), str(role or "未標示"))


def _briefing_missing_items(source_manifest: dict[str, Any]) -> str:
    required = _str_list(source_manifest.get("required_missing_source_kinds"))
    optional = _str_list(source_manifest.get("optional_missing_source_kinds"))
    if not required and not optional:
        return '<p class="alert">目前沒有必要來源缺口；出發前仍需要重新整理官方狀態、天氣與路況。</p>'
    items = []
    if required:
        items.append(f"必要來源缺口：{_h(', '.join(required))}")
    if optional:
        items.append(f"可補強來源：{_h(', '.join(optional))}")
    return "<div class=\"alert\">" + "<br>".join(items) + "</div>"


def _briefing_source_rows(source_manifest: dict[str, Any]) -> str:
    rows = [
        "<tr>"
        f"<td>{_h(_briefing_source_name(source.get('source_kind')))}</td>"
        f"<td>{_h(source.get('source_tier'))}</td>"
        f"<td>{_h(_briefing_source_status_label(source.get('status')))}</td>"
        f"<td>{_h(source.get('loaded_count'))}</td>"
        f"<td>{_h(_briefing_source_role_label(source.get('conclusion_role')))}</td>"
        "</tr>"
        for source in source_manifest.get("source_report", [])
    ]
    return "\n".join(rows) or (
        '<tr><td colspan="5">目前沒有來源報告。</td></tr>'
    )


def _briefing_seed_items(crawl_seed_plan: dict[str, Any]) -> str:
    seeds = crawl_seed_plan.get("seeds", [])
    if not isinstance(seeds, list) or not seeds:
        return "<li>目前沒有可用的 crawl seed。</li>"
    return "\n".join(
        f"<li>{_h(seed.get('query'))} <span>{_h(seed.get('seed_kind'))}</span></li>"
        for seed in seeds[:24]
        if isinstance(seed, dict)
    )


def _briefing_tier_items() -> str:
    return "\n".join(
        f"<li><strong>{_h(source['tier'])}</strong> {_h(source['label'])} "
        f"<span>{_h(source['role'])}</span></li>"
        for source in SOURCE_TIER_CATALOG
    )


def _h(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def _sensitivity_policy() -> dict[str, Any]:
    return {
        "public": {
            "show_exact_coordinate": True,
            "requires_human_review_before_display": False,
        },
        "cultural_review": {
            "show_exact_coordinate": False,
            "coordinate_precision": "fuzzy_250m",
            "requires_human_review_before_display": True,
        },
        "sensitive": {
            "show_exact_coordinate": False,
            "coordinate_precision": "fuzzy_250m",
            "requires_human_review_before_display": True,
        },
        "restricted": {
            "show_exact_coordinate": False,
            "coordinate_precision": "hidden_or_area_only",
            "requires_human_review_before_display": True,
        },
    }


def _observation_scoring_policy() -> dict[str, Any]:
    return {
        "formula": "observation_value_minus_risk_penalty",
        "short_stop_requires": "scout.ai.contextual_permission.assess.v0",
        "runtime_safety_truth": False,
        "candidate_only": True,
    }


def _import_manifest_summary(payload: dict[str, Any]) -> dict[str, Any]:
    counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
    gpx_filter = payload.get("gpx_speed_filter") if isinstance(payload.get("gpx_speed_filter"), dict) else {}
    boundary = payload.get("boundary") if isinstance(payload.get("boundary"), dict) else {}
    return {
        "artifact_kind": payload.get("artifact_kind"),
        "import_stage": payload.get("import_stage"),
        "counts": {
            key: counts.get(key)
            for key in (
                "checkpoint_candidate_count",
                "segment_candidate_count",
                "route_point_count",
                "gis_perception_checkpoint_candidate_count",
            )
            if key in counts
        },
        "gpx_speed_filter_applied": boundary.get("gpx_speed_filter_applied")
        or gpx_filter.get("applied"),
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _source_refs_for(source_ref: str, source_kind: str, raw: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = [
        {
            "source_kind": source_kind,
            "source_path": source_ref,
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
    ]
    source_refs = raw.get("source_refs")
    if isinstance(source_refs, list):
        refs.extend(ref for ref in source_refs if isinstance(ref, dict))
    source_ref_value = raw.get("source_ref")
    if source_ref_value:
        refs.append(
            {
                "source_kind": "source_ref",
                "source_ref": str(source_ref_value),
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )
    return refs[:8]


def _list_from_any(payload: dict[str, Any], keys: tuple[str, ...]) -> list[Any]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def _geojson_features(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("type") == "FeatureCollection" and isinstance(payload.get("features"), list):
        return [feature for feature in payload["features"] if isinstance(feature, dict)]
    return []


def _lat_lon_from(raw: dict[str, Any]) -> tuple[float | None, float | None]:
    lat = _float_or_none(raw.get("lat"))
    lon = _float_or_none(raw.get("lon"))
    if lat is not None and lon is not None:
        return lat, lon
    geometry = raw.get("geometry")
    if isinstance(geometry, dict) and geometry.get("type") == "Point":
        coordinates = geometry.get("coordinates")
        if isinstance(coordinates, list) and len(coordinates) >= 2:
            return _float_or_none(coordinates[1]), _float_or_none(coordinates[0])
    return None, None


def _display_label(label: str, source_candidate_id: str) -> str:
    value = label.strip()
    if value and not value.startswith(("gis_cp_cluster.", "pretrip_gis_perception_")):
        return value[:48]
    return source_candidate_id.rsplit(".", 1)[-1][:48] or value[:48]


def _candidate_id(prefix: str, source_kind: str, source_candidate_id: str) -> str:
    raw = f"{prefix}.{source_kind}.{source_candidate_id}"
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("_")
    return slug[:180] or f"{prefix}.{source_kind}"


def _first_text(*values: Any) -> str:
    for value in values:
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _rounded_coord(value: Any) -> float | None:
    number = _float_or_none(value)
    return None if number is None else round(number, 6)


def _normalize(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").lower())


def _has_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(_normalize(needle) in text for needle in needles)


def _project_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _load_json_object(path: Path) -> dict[str, Any]:
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


def _write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    temp_path.write_text(payload, encoding="utf-8")
    temp_path.replace(path)


def _update_project_refs(
    project_path: Path,
    project: dict[str, Any],
    updates: dict[str, Any],
) -> None:
    if not project_path.exists():
        return
    current = _load_json_object(project_path)
    updated = {**project, **current, **updates}
    _write_json(project_path, updated)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _closed_boundary(**overrides: Any) -> dict[str, Any]:
    boundary = {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "phase1_runtime_mutation_allowed": False,
        "phase2_brain_writeback_allowed": False,
        "live_safety_api_calls_allowed": False,
        "safety_api_called": False,
        "compile_allowed": False,
    }
    boundary.update(overrides)
    return boundary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect Scout pretrip Route Context Intelligence evidence.")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--include-route-notes", action="store_true", default=True)
    parser.add_argument("--no-route-notes", dest="include_route_notes", action="store_false")
    parser.add_argument("--limit-route-notes", type=int, default=DEFAULT_ROUTE_NOTE_LIMIT)
    parser.add_argument(
        "--route-note-point-policy",
        choices=("seed_only", "promote_representative"),
        default=DEFAULT_ROUTE_NOTE_POINT_POLICY,
    )
    parser.add_argument("--route-keyword", default=None)
    parser.add_argument("--no-briefing", dest="write_briefing", action="store_false")
    parser.add_argument("--collected-at", default=None)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    payload = collect_pretrip_route_context(
        args.project_root,
        dry_run=args.dry_run,
        include_route_notes=args.include_route_notes,
        limit_route_notes=args.limit_route_notes,
        route_note_point_policy=args.route_note_point_policy,
        route_keyword=args.route_keyword,
        write_briefing=args.write_briefing,
        collected_at=args.collected_at,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
