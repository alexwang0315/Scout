from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROUTE_CONTEXT_COLLECTION_ARTIFACT_KIND = "pretrip_route_context_collection"
ROUTE_CONTEXT_EVIDENCE_ARTIFACT_KIND = "pretrip_route_context_evidence"
ROUTE_CONTEXT_POINTS_ARTIFACT_KIND = "pretrip_route_context_points"
ROUTE_CONTEXT_SOURCE_MANIFEST_ARTIFACT_KIND = "pretrip_route_context_source_manifest"
ROUTE_CONTEXT_PACK_ARTIFACT_KIND = "pretrip_route_context_pack"
ROUTE_CONTEXT_CRAWL_SEED_PLAN_ARTIFACT_KIND = "pretrip_route_context_crawl_seed_plan"
ROUTE_CONTEXT_BRIEFING_ARTIFACT_KIND = "pretrip_route_context_briefing"
ROUTE_CONTEXT_EVIDENCE_REF = "normalized/context/route_context/route_context_evidence.json"
ROUTE_CONTEXT_SOURCE_MANIFEST_REF = "normalized/context/route_context/source_manifest.json"
ROUTE_CONTEXT_PACK_REF = "normalized/context/route_context/route_context_pack.json"
ROUTE_CONTEXT_CRAWL_SEED_PLAN_REF = "normalized/context/route_context/crawl_seed_plan.json"
ROUTE_CONTEXT_BRIEFING_REF = "outputs/briefings/route_context_briefing.html"
ROUTE_CONTEXT_POINTS_REF = "candidates/route_context_points.json"
ROUTE_CONTEXT_SCHEMA_VERSION = "route_context_collection.v1"
DEFAULT_ROUTE_NOTE_LIMIT = 80
DEFAULT_ROUTE_NOTE_SEED_LIMIT = 60
DEFAULT_ROUTE_NOTE_POINT_POLICY = "seed_only"


SEC6_ALIGNMENT = {
    "standard": "SCOUT_OUTDOOR_AI_AGENT_STANDARD",
    "section": "Sec. 6 Route Context Intelligence",
    "workspace_layout_section": "Outdoor AI Agent Data Placement",
    "canonical_refs": [
        "normalized/context/route_context/*.json",
        ROUTE_CONTEXT_PACK_REF,
        ROUTE_CONTEXT_SOURCE_MANIFEST_REF,
        ROUTE_CONTEXT_CRAWL_SEED_PLAN_REF,
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
    {"tier": "P0", "source_id": "tbn_biodiversity", "label": "TBN 台灣生物多樣性網絡", "role": "natural_baseline"},
    {"tier": "P0", "source_id": "as_taiwan_century_maps", "label": "中研院臺灣百年歷史地圖", "role": "historical_map_baseline"},
    {"tier": "P1", "source_id": "national_culture_memory_bank", "label": "國家文化記憶庫", "role": "cultural_expansion"},
    {"tier": "P1", "source_id": "taiwan_memory", "label": "臺灣記憶", "role": "historical_expansion"},
    {"tier": "P1", "source_id": "indigenous_trail_spatial_info", "label": "原住民族古道空間資訊網", "role": "cultural_spatial_expansion"},
    {"tier": "P1", "source_id": "geology_cloud", "label": "地質雲", "role": "geology_expansion"},
    {"tier": "P1", "source_id": "osm_overpass_history", "label": "OpenStreetMap / Overpass / OSM full-history", "role": "map_expansion"},
    {"tier": "P1", "source_id": "rudymap", "label": "魯地圖", "role": "map_expansion"},
    {"tier": "P1", "source_id": "map_generator_hiker_gpx", "label": "地圖產生器 / 山友 GPX", "role": "community_route_seed"},
    {"tier": "P1", "source_id": "hiking_biji", "label": "健行筆記", "role": "community_article_evidence"},
    {"tier": "P1", "source_id": "hikingbook", "label": "Hikingbook", "role": "community_route_evidence"},
    {"tier": "P1", "source_id": "mountain_news_bbs", "label": "登山補給站", "role": "community_article_evidence"},
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

    route_note_payload, route_note_ref, _ = _load_source(
        root,
        project,
        "route_note_candidates",
        source_report,
    )
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
    briefing_ref = str(
        project.get("route_context_briefing_ref") or ROUTE_CONTEXT_BRIEFING_REF
    )
    points_ref = str(project.get("route_context_points_ref") or ROUTE_CONTEXT_POINTS_REF)
    planned_writes = [
        evidence_ref,
        source_manifest_ref,
        context_pack_ref,
        crawl_seed_plan_ref,
        points_ref,
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
        "crawl_seed_plan_ref": crawl_seed_plan_ref,
        "route_context_briefing_ref": briefing_ref if write_briefing else None,
        "point_count": len(points),
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
        "source_manifest_ref": source_manifest_ref,
        "route_context_pack_ref": context_pack_ref,
        "crawl_seed_plan_ref": crawl_seed_plan_ref,
        "route_context_briefing_ref": briefing_ref if write_briefing else None,
        "import_manifest_ref": import_manifest_ref,
        "import_manifest_summary": _import_manifest_summary(import_manifest_payload),
        "project_update_suggestions": {
            "route_context_evidence_ref": evidence_ref,
            "route_context_source_manifest_ref": source_manifest_ref,
            "route_context_pack_ref": context_pack_ref,
            "route_context_crawl_seed_plan_ref": crawl_seed_plan_ref,
            "route_context_briefing_ref": briefing_ref if write_briefing else None,
            "route_context_points_ref": points_ref,
            "route_context_point_count": len(points),
        },
        "boundary": boundary,
    }
    briefing_html = _build_briefing_html(
        project_id=project_id,
        generated_at=collected_at,
        route_keywords=route_keywords,
        route_summary=_route_summary_for_pack(route_summary_payload),
        points=points,
        counts=counts,
        source_manifest=source_manifest_payload,
        crawl_seed_plan=crawl_seed_plan_payload,
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
            "route_context_briefing_ref": briefing_ref if write_briefing else None,
            "route_context_points_ref": points_ref,
        },
        "standard_alignment": SEC6_ALIGNMENT,
        "boundary": boundary,
    }

    if not dry_run:
        _write_json(root / evidence_ref, evidence_payload)
        _write_json(root / source_manifest_ref, source_manifest_payload)
        _write_json(root / context_pack_ref, context_pack_payload)
        _write_json(root / crawl_seed_plan_ref, crawl_seed_plan_payload)
        _write_json(root / points_ref, points_payload)
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
                "route_context_briefing_ref": briefing_ref if write_briefing else None,
                "route_context_points_ref": points_ref,
                "route_context_point_count": len(points),
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
        point = _base_point(
            source_kind="ocr_label_evidence",
            source_ref=source_ref,
            source_candidate_id=_first_text(raw.get("ocr_label_id"), label),
            label=label,
            lat=None,
            lon=None,
            distance_m=None,
            text_fields=[label, raw.get("named_point_id"), raw.get("source_ref")],
            extra_evidence_families=["ocr", "map_label"],
        )
        point.update(
            {
                "evidence_type": "ocr_map_label",
                "named_point_id": raw.get("named_point_id"),
                "confidence": raw.get("confidence"),
                "review_state": "needs_human_review" if raw.get("review_required", True) else "candidate",
                "source_refs": _source_refs_for(source_ref, "ocr_label_evidence", raw),
            }
        )
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
        point = _base_point(
            source_kind="raster_label_evidence",
            source_ref=source_ref,
            source_candidate_id=_first_text(props.get("candidate_id"), props.get("id"), label),
            label=label,
            lat=lat,
            lon=lon,
            distance_m=_float_or_none(props.get("distance_m")),
            text_fields=[label, props.get("class"), props.get("source_ref")],
            extra_evidence_families=["map_label", "ocr"],
        )
        point.update(
            {
                "evidence_type": "raster_map_label",
                "confidence": props.get("confidence"),
                "source_refs": _source_refs_for(source_ref, "raster_label_evidence", props),
            }
        )
        points.append(point)
    return points


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
        key = (
            _normalize(point.get("label")),
            str(point.get("context_kind") or ""),
            _rounded_coord(point.get("lat")),
            _rounded_coord(point.get("lon")),
        )
        if key in seen:
            existing = deduped[seen[key]]
            _merge_point_provenance(existing, point)
            continue
        seen[key] = len(deduped)
        deduped.append(point)
    return deduped


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
    boundary: dict[str, Any],
) -> str:
    title = f"Scout Route Context Briefing - {route_keywords[0] if route_keywords else project_id}"
    representative_points = sorted(
        points,
        key=lambda point: (
            -float((point.get("observation_score") or {}).get("value") or 0),
            str(point.get("display_label") or ""),
        ),
    )
    source_rows = "\n".join(
        "<tr>"
        f"<td>{_h(source.get('source_kind'))}</td>"
        f"<td>{_h(source.get('source_tier'))}</td>"
        f"<td>{_h(source.get('status'))}</td>"
        f"<td>{_h(source.get('loaded_count'))}</td>"
        f"<td>{_h(source.get('conclusion_role'))}</td>"
        "</tr>"
        for source in source_manifest.get("source_report", [])
    )
    point_cards = "\n".join(
        "<article class=\"point\">"
        f"<h3>{_h(point.get('display_label'))}</h3>"
        f"<p>{_h(point.get('context_kind'))} · {_h(point.get('evidence_type'))} · {_h(point.get('source_tier'))}</p>"
        f"<p>Layers: {_h(', '.join(_str_list(point.get('sec6_layers'))))}</p>"
        f"<p>Observation score: {_h((point.get('observation_score') or {}).get('value'))}</p>"
        "</article>"
        for point in representative_points[:12]
    )
    seed_items = "\n".join(
        f"<li>{_h(seed.get('query'))} <span>{_h(seed.get('seed_kind'))}</span></li>"
        for seed in crawl_seed_plan.get("seeds", [])[:24]
    )
    tier_items = "\n".join(
        f"<li><strong>{_h(source['tier'])}</strong> {_h(source['label'])} <span>{_h(source['role'])}</span></li>"
        for source in SOURCE_TIER_CATALOG
    )
    route_distance = _float_or_none(route_summary.get("distance_m"))
    route_distance_km = round(route_distance / 1000.0, 1) if route_distance else "unknown"
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_h(title)}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; color: #17202a; background: #f7f8fa; }}
    header, main {{ max-width: 1080px; margin: 0 auto; padding: 28px; }}
    header {{ background: #ffffff; border-bottom: 1px solid #d8dee6; }}
    h1 {{ margin: 0 0 8px; font-size: 28px; }}
    h2 {{ margin-top: 28px; font-size: 20px; }}
    .meta, .boundary {{ color: #526070; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }}
    .card, .point {{ background: #fff; border: 1px solid #d8dee6; border-radius: 8px; padding: 14px; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #d8dee6; }}
    th, td {{ text-align: left; padding: 9px; border-bottom: 1px solid #e6ebf0; font-size: 14px; }}
    li {{ margin: 7px 0; }}
    span {{ color: #687586; }}
  </style>
</head>
<body>
  <header>
    <h1>{_h(title)}</h1>
    <p class="meta">Generated at {_h(generated_at)} · project {_h(project_id)} · route distance {_h(route_distance_km)} km</p>
    <p class="boundary">Candidate-only pretrip evidence. Runtime safety truth: {_h(boundary.get('runtime_safety_truth'))}. Live safety API called: {_h(boundary.get('safety_api_called'))}.</p>
  </header>
  <main>
    <section class="grid">
      <div class="card"><strong>Route context points</strong><br>{_h(counts.get('route_context_point_count'))}</div>
      <div class="card"><strong>Crawl seeds</strong><br>{_h(crawl_seed_plan.get('seed_count'))}</div>
      <div class="card"><strong>Route-note seeds</strong><br>{_h(crawl_seed_plan.get('route_note_seed_count'))}</div>
      <div class="card"><strong>Source tiers</strong><br>P0 / P1 / P2</div>
    </section>
    <h2>Representative Context Candidates</h2>
    <section class="grid">{point_cards or '<p>No representative route context points yet.</p>'}</section>
    <h2>Source Readiness</h2>
    <table>
      <thead><tr><th>Source</th><th>Tier</th><th>Status</th><th>Count</th><th>Role</th></tr></thead>
      <tbody>{source_rows}</tbody>
    </table>
    <h2>Crawl Seed Plan</h2>
    <p>Route notes are treated as seed material. Briefing conclusions should come from P0/P1 crawler outputs or reviewed Scout-owned P2 evidence.</p>
    <ol>{seed_items}</ol>
    <h2>Source Tier Catalog</h2>
    <ul>{tier_items}</ul>
  </main>
</body>
</html>
"""


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
    updated = {**project, **updates}
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
