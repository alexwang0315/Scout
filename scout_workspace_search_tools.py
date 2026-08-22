from __future__ import annotations

import json
import math
import re
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


WORKSPACE_CATALOG_TOOL_ID = "pydantic_ai.tool.search_scout_workspace_catalog.v0"
ROUTE_STRUCTURE_TOOL_ID = "pydantic_ai.tool.search_scout_route_structure.v0"
MAJOR_POINT_TOOL_ID = "pydantic_ai.tool.search_scout_major_points.v0"
EVIDENCE_FULLTEXT_TOOL_ID = "pydantic_ai.tool.search_scout_evidence_fulltext.v0"

DEFAULT_WORKSPACE_SEARCH_LIMIT = 6
MAX_WORKSPACE_SEARCH_LIMIT = 16

_GENERIC_TERMS = {
    "cp",
    "route",
    "routes",
    "workspace",
    "artifact",
    "artifacts",
    "data",
    "layer",
    "layers",
    "source",
    "sources",
    "summary",
    "search",
    "near",
    "nearby",
    "scout",
    "ai",
    "資料",
    "有哪些",
    "有多少",
    "幾個",
    "在哪",
    "附近",
    "經過",
    "查詢",
    "來源",
    "圖層",
    "工作區",
    "規劃",
}

_DOMAIN_HINTS = {
    "route": (
        "route",
        "routes",
        "checkpoint",
        "segment",
        "cp",
        "mileage",
        "mileage_tag",
        "route_mileage",
        "路線",
        "檢查點",
        "里程",
        "公里樁",
    ),
    "map": (
        "map",
        "overpass",
        "tile",
        "imagery",
        "ocr",
        "raster_label",
        "layer",
        "validation",
        "地圖",
        "圖磚",
        "標註",
    ),
    "terrain": ("terrain", "dtm", "dem", "slope", "contour", "地形", "坡度", "等高線"),
    "risk": ("risk", "hazard", "ribbon", "heatmap", "風險", "危險"),
    "mcp": ("mcp", "major", "named", "critical", "黑水塘", "重要點"),
    "timing": ("eta", "timing", "daylight", "weather", "時間", "天氣", "摸黑"),
    "environment": ("environment", "cwa", "gee", "smap", "gpm", "qpf", "環境", "氣象署", "土壤水分"),
    "resource": ("resource", "energy", "battery", "vitals", "資源", "體力", "電力"),
    "review": ("review", "human", "decision", "審查", "人工", "決策"),
    "runtime": ("runtime", "debug", "handoff", "admin", "執行", "除錯"),
    "tool": ("tool", "skill", "manifest", "agent", "工具", "技能"),
}


def search_project_workspace_catalog(
    project_root: Path | str,
    *,
    query: str = "",
    domains: list[str] | None = None,
    include_missing: bool = True,
    limit: int = DEFAULT_WORKSPACE_SEARCH_LIMIT,
) -> dict[str, Any]:
    root = Path(project_root)
    project = _load_json_object(root / "project.json")
    project_id = str(project.get("project_id") or root.name)
    resolved_limit = _bounded_limit(limit)
    requested_domains = _normalize_domains(domains) or _domains_from_query(query)
    terms = _query_terms(query)
    identity = _workspace_identity_summary(root, project)

    items = _catalog_items(root, project)
    filtered: list[dict[str, Any]] = []
    for item in items:
        if requested_domains and item["domain"] not in requested_domains:
            continue
        if not include_missing and not item["exists"]:
            continue
        score = _catalog_match_score(item, terms, query)
        if terms and score <= 0:
            continue
        filtered.append({**item, "match_score": round(score, 3)})

    if not terms and not requested_domains:
        filtered = [{**item, "match_score": 0.0} for item in items if include_missing or item["exists"]]

    filtered.sort(key=lambda item: (-item["match_score"], item["domain"], item["ref_key"]))
    results = filtered[:resolved_limit]
    environment_items = [
        item for item in items if item.get("domain") == "environment"
    ]
    field_answer, field_answer_source_ref = _catalog_field_answer(
        root,
        project,
        identity,
        results,
        query=query,
        environment_items=environment_items,
    )
    return {
        "tool_id": WORKSPACE_CATALOG_TOOL_ID,
        "status": "completed",
        "project_id": project_id,
        "source_ref": field_answer_source_ref,
        "route_name": identity["route_name"],
        "primary_gpx_filename": identity["primary_gpx_filename"],
        "reference_gpx_count": identity["reference_gpx_count"],
        "reference_gpx_filenames": identity["reference_gpx_filenames"],
        "source_refs": identity["source_refs"],
        "query": query,
        "filters": {
            "domains": sorted(requested_domains) if requested_domains else None,
            "include_missing": include_missing,
            "query_terms": sorted(terms),
        },
        "summaries": _catalog_summaries(items),
        "searched_artifact_count": len(items),
        "matched_artifact_count": len(filtered),
        "result_count": len(results),
        "field_answer": field_answer,
        "field_answer_priority": 100 if field_answer else 0,
        "field_answer_source_ref": field_answer_source_ref,
        "results": results,
        "boundary": _closed_boundary(),
    }


def _catalog_field_answer(
    root: Path,
    project: dict[str, Any],
    identity: dict[str, Any],
    results: list[dict[str, Any]],
    *,
    query: str,
    environment_items: list[dict[str, Any]],
) -> tuple[str | None, str | None]:
    if _is_environment_catalog_status_query(query):
        existing = sorted(
            str(item.get("ref_key"))
            for item in environment_items
            if item.get("exists") and item.get("ref_key")
        )
        missing = sorted(
            str(item.get("ref_key"))
            for item in environment_items
            if not item.get("exists") and item.get("ref_key")
        )
        return (
            f"Environment catalog 共 {len(environment_items)} 個 refs："
            f"existing={len(existing)}，missing={len(missing)}；"
            f"existing refs={','.join(existing) or 'none'}；"
            f"missing refs={','.join(missing) or 'none'}。",
            "project.json",
        )
    exact_answer = _catalog_exact_field_answer(
        root,
        project,
        identity,
        query=query,
    )
    if exact_answer[0]:
        return exact_answer
    if re.search(r"layer\s*preparation|圖層準備|layer preparation", query, re.IGNORECASE):
        for item in results:
            if item.get("source_path") != "outputs/layers/layer_preparation_summary.json":
                continue
            summary = item.get("summary_fields")
            if not isinstance(summary, dict):
                continue
            completed_at = (
                summary.get("completed_at")
                or summary.get("finished_at")
                or summary.get("prepared_at")
                or summary.get("generated_at")
            )
            parts = [
                f"status={summary['status']}"
                if summary.get("status") is not None
                else None,
                f"completed_at={completed_at}" if completed_at is not None else None,
                f"profile={summary['profile']}"
                if summary.get("profile") is not None
                else None,
            ]
            if any(parts):
                return (
                    "Layer preparation summary："
                    + ", ".join(part for part in parts if part)
                    + "。",
                    "outputs/layers/layer_preparation_summary.json",
                )
    for item in results:
        if item.get("ref_key") != "layer_validation_report_ref":
            continue
        summary = item.get("summary_fields")
        if not isinstance(summary, dict):
            continue
        status = summary.get("status")
        blocker_count = summary.get("blocker_count")
        warning_count = summary.get("warning_count")
        parts = [
            f"status={status}" if status is not None else None,
            (
                f"blocker_count={blocker_count}"
                if blocker_count is not None
                else None
            ),
            (
                f"warning_count={warning_count}"
                if warning_count is not None
                else None
            ),
        ]
        details = [str(value) for value in summary.get("blockers", [])]
        details.extend(str(value) for value in summary.get("warnings", []))
        if blocker_count == 0 and warning_count == 0 and not details:
            details.append("沒有列出失敗或警告項目")
        suffix = f"；{'；'.join(details)}" if details else ""
        source_path = item.get("source_path")
        return (
            "Layer validation report："
            f"{', '.join(part for part in parts if part)}{suffix}。",
            str(source_path) if source_path else None,
        )
    return None, None


def _catalog_exact_field_answer(
    root: Path,
    project: dict[str, Any],
    identity: dict[str, Any],
    *,
    query: str,
) -> tuple[str | None, str | None]:
    normalized = query.casefold()
    if re.search(r"route\s*note|路線註記|路線備註", normalized) and re.search(
        r"候選|candidate|分類|category|多少|幾", normalized
    ):
        ref = str(
            project.get("route_note_candidates_ref")
            or "candidates/route_note_candidates.json"
        )
        payload = _load_json_object(_project_path(root, ref))
        raw_rows = payload.get("candidates") if isinstance(payload, dict) else []
        rows = [item for item in raw_rows if isinstance(item, dict)]
        categories = Counter(
            str(item.get("note_category") or "uncategorized_note") for item in rows
        )
        category_text = "、".join(
            f"{name}={count}"
            for name, count in sorted(
                categories.items(), key=lambda pair: (-pair[1], pair[0])
            )
        )
        return (
            f"Route note candidates 共 {len(rows)} 筆；分類："
            f"{category_text or 'none'}。",
            ref,
        )
    if "import manifest" in normalized and re.search(
        r"來源|source|檔案|file|數量|count", normalized
    ):
        ref = str(project.get("import_manifest_ref") or "outputs/import_manifest.json")
        payload = _load_json_object(_project_path(root, ref))
        counts = payload.get("counts") if isinstance(payload, dict) else {}
        counts = counts if isinstance(counts, dict) else {}
        inputs = payload.get("inputs") if isinstance(payload, dict) else {}
        inputs = inputs if isinstance(inputs, dict) else {}
        references = inputs.get("reference_tracks")
        references = references if isinstance(references, list) else []
        reference_count = int(
            counts.get("reference_track_count") or len(references)
        )
        total = int(
            counts.get("source_file_count") or (1 + reference_count)
        )
        return (
            f"Import manifest 記錄 GPX source files={total}："
            f"golden_route_reference=1，reference_track={reference_count}。",
            ref,
        )
    if re.search(r"reference\s*gpx", normalized) and re.search(
        r"多少|幾|count|檔名|filename", normalized
    ):
        filenames = [str(value) for value in identity["reference_gpx_filenames"]]
        return (
            f"reference GPX 共 {identity['reference_gpx_count']} 條；"
            f"前五個檔名：{', '.join(filenames) or 'none'}。",
            str(project.get("reference_tracks_ref") or "outputs/reference_tracks.json"),
        )
    if "package" in normalized and "reviewed" in normalized and "candidate" in normalized:
        candidate_ref = str(project.get("package_ref") or "outputs/pretrip_package.json")
        reviewed_ref = str(
            project.get("reviewed_package_ref")
            or "outputs/pretrip_package.reviewed.json"
        )
        candidate = _load_json_object(_project_path(root, candidate_ref))
        reviewed = _load_json_object(_project_path(root, reviewed_ref))
        return (
            "Package artifacts："
            f"{reviewed_ref} (status={reviewed.get('status') or 'unknown'})；"
            f"{candidate_ref} (status={candidate.get('status') or 'unknown'})。",
            "project.json",
        )
    if "route evidence bundle" in normalized and re.search(
        r"來源|source|artifact|引用", normalized
    ):
        ref = str(
            project.get("route_evidence_bundle_ref")
            or "normalized/routes/route_evidence_bundle.json"
        )
        payload = _load_json_object(_project_path(root, ref))
        core_payload = {
            key: payload.get(key)
            for key in (
                "golden_route",
                "gpx_filter_refs",
                "note_candidate_refs",
            )
            if isinstance(payload, dict) and key in payload
        }
        refs = _collect_workspace_artifact_refs(core_payload)
        raw_tracks = payload.get("reference_tracks") if isinstance(payload, dict) else []
        tracks = raw_tracks if isinstance(raw_tracks, list) else []
        display_refs = _collect_workspace_artifact_refs(
            [
                {"geometry_ref": item.get("geometry_ref")}
                for item in tracks
                if isinstance(item, dict)
            ]
        )
        refs = list(dict.fromkeys([*refs, *display_refs]))
        filtered_track_count = sum(
            1
            for item in tracks
            if isinstance(item, dict) and item.get("filtered_geometry_ref")
        )
        compact_refs = [
            _route_bundle_artifact_label(value, index=index)
            for index, value in enumerate(refs, start=1)
        ]
        return (
            f"Route evidence bundle 核心 artifact refs ({len(compact_refs)})："
            f"{', '.join(compact_refs) or 'none'}；另含 "
            f"{filtered_track_count} 條 reference filtered GPX geometry，"
            "逐條 ref 保存在 bundle.reference_tracks。",
            ref,
        )
    if "source inbox manifest" in normalized and re.search(
        r"匯入|未處理|pending|import", normalized
    ):
        ref = str(project.get("source_inbox_manifest_ref") or "inbox/source_manifest.json")
        payload = _load_json_object(_project_path(root, ref))
        raw_sources = payload.get("sources") if isinstance(payload, dict) else []
        sources = raw_sources if isinstance(raw_sources, list) else []
        imported = _source_manifest_filenames(sources, imported=True)
        pending = _source_manifest_filenames(sources, imported=False)
        total = int(payload.get("source_file_count") or len(sources))
        if total > 8:
            imported_roles = _source_manifest_role_counts(sources, imported=True)
            primary = next(
                (
                    _source_basename(item.get("original_path"))
                    for item in sources
                    if isinstance(item, dict)
                    and item.get("imported_as_raw_file")
                    and item.get("role") == "golden_route_reference"
                ),
                None,
            )
            return (
                f"Source inbox 共 {total} 個來源，已匯入 {len(imported)}/{total}；"
                f"golden_route_reference={imported_roles.get('golden_route_reference', 0)}"
                f"（{primary or 'filename unavailable'}），"
                f"reference_track={imported_roles.get('reference_track', 0)}；"
                f"尚未處理 {len(pending)}（{', '.join(pending) or 'none'}）。",
                ref,
            )
        return (
            f"Source inbox：已匯入 {len(imported)}/{total}："
            f"{', '.join(imported) or 'none'}；尚未處理 {len(pending)}："
            f"{', '.join(pending) or 'none'}。",
            ref,
        )
    if "readiness report" in normalized and re.search(
        r"blocker|warning|失敗|複核", normalized
    ):
        ref = str(project.get("readiness_report_ref") or "outputs/readiness_report.json")
        payload = _load_json_object(_project_path(root, ref))
        findings = payload.get("findings") if isinstance(payload, dict) else []
        findings = findings if isinstance(findings, list) else []
        blockers = _readiness_findings(findings, {"blocker", "critical", "error"})
        warnings = _readiness_findings(findings, {"warning", "warn", "review"})
        return (
            f"Readiness report：status={payload.get('status') or 'unknown'}；"
            f"blockers={'; '.join(blockers) or 'none'}；"
            f"warnings={'; '.join(warnings) or 'none'}。",
            ref,
        )
    return None, None


def _collect_workspace_artifact_refs(value: Any) -> list[str]:
    refs: list[str] = []

    def visit(item: Any, key: str = "") -> None:
        if isinstance(item, dict):
            for child_key, child in item.items():
                visit(child, str(child_key))
            return
        if isinstance(item, list):
            for child in item:
                visit(child, key)
            return
        if not isinstance(item, str):
            return
        if not (key.endswith("_ref") or key.endswith("_refs")):
            return
        candidate = item.strip()
        if not candidate or Path(candidate).is_absolute() or "://" in candidate:
            return
        refs.append(candidate)

    visit(value)
    return list(dict.fromkeys(refs))


def _route_bundle_artifact_label(value: str, *, index: int) -> str:
    normalized = value.casefold()
    labels = (
        ("reference_track_display_geometry", "reference-track display geometry"),
        ("gpx_speed_filter", "speed-filter report"),
        ("rest_area", "rest-area candidates"),
        ("resume_segment", "resume-segment report"),
        ("route_summary", "route summary"),
        ("map_context", "map context geometry"),
        ("gpx_route_note", "normalized route-note candidates"),
        ("route_note", "candidate route-note dataset"),
        ("primary", "filtered primary GPX"),
    )
    return next(
        (label for token, label in labels if token in normalized),
        f"artifact ref {index}",
    )


def _source_manifest_filenames(
    sources: list[Any],
    *,
    imported: bool,
) -> list[str]:
    filenames: list[str] = []
    for item in sources:
        if not isinstance(item, dict):
            continue
        if bool(item.get("imported_as_raw_file")) is not imported:
            continue
        filename = _source_basename(
            item.get("original_path") or item.get("workspace_ref")
        )
        if filename:
            filenames.append(filename)
    return filenames


def _source_manifest_role_counts(
    sources: list[Any],
    *,
    imported: bool,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in sources:
        if not isinstance(item, dict):
            continue
        if bool(item.get("imported_as_raw_file")) is not imported:
            continue
        role = str(item.get("role") or "unknown")
        counts[role] = counts.get(role, 0) + 1
    return counts


def _readiness_findings(
    findings: list[Any],
    severities: set[str],
) -> list[str]:
    matched: list[str] = []
    for item in findings:
        if not isinstance(item, dict):
            continue
        severity = str(
            item.get("severity") or item.get("level") or item.get("kind") or ""
        ).casefold()
        if severity not in severities:
            continue
        matched.append(
            str(
                item.get("message")
                or item.get("finding")
                or item.get("id")
                or severity
            )
        )
    return matched


def _is_environment_catalog_status_query(query: str) -> bool:
    normalized = query.casefold()
    return bool(
        re.search(r"environment|環境", normalized)
        and re.search(r"artifact|ref|存在|缺失|missing|exist", normalized)
    )


def _workspace_identity_summary(
    root: Path,
    project: dict[str, Any],
) -> dict[str, Any]:
    import_manifest_ref = str(
        project.get("import_manifest_ref") or "outputs/import_manifest.json"
    )
    reference_tracks_ref = str(
        project.get("reference_tracks_ref") or "outputs/reference_tracks.json"
    )
    route_summary_ref = str(
        project.get("route_summary_ref") or "normalized/routes/route_summary.json"
    )
    import_manifest = _load_json_object(_project_path(root, import_manifest_ref))
    reference_tracks = _load_json_object(_project_path(root, reference_tracks_ref))
    route_summary = _load_json_object(_project_path(root, route_summary_ref))
    import_manifest = import_manifest if isinstance(import_manifest, dict) else {}
    reference_tracks = reference_tracks if isinstance(reference_tracks, dict) else {}
    route_summary = route_summary if isinstance(route_summary, dict) else {}

    inputs = import_manifest.get("inputs")
    inputs = inputs if isinstance(inputs, dict) else {}
    golden_route_input = inputs.get("golden_route_gpx")
    golden_route_input = (
        golden_route_input if isinstance(golden_route_input, dict) else {}
    )
    golden_route = reference_tracks.get("golden_route")
    golden_route = golden_route if isinstance(golden_route, dict) else {}
    reference_inputs = inputs.get("reference_tracks")
    reference_inputs = reference_inputs if isinstance(reference_inputs, list) else []
    reference_filenames = [
        filename
        for item in reference_inputs
        if isinstance(item, dict)
        if (filename := _source_basename(item.get("uri"))) is not None
    ]
    configured_count = reference_tracks.get("reference_track_count")
    reference_count = (
        int(configured_count)
        if isinstance(configured_count, int) and not isinstance(configured_count, bool)
        else len(reference_filenames)
    )
    route_name = str(
        project.get("route_name")
        or route_summary.get("route_name")
        or golden_route.get("route_name")
        or ""
    ).strip()
    primary_filename = _source_basename(
        golden_route_input.get("uri") or golden_route.get("source_uri")
    )
    refs = [
        ref
        for ref in (
            "project.json",
            import_manifest_ref,
            reference_tracks_ref,
            route_summary_ref,
        )
        if not Path(ref).is_absolute() and _project_path(root, ref).is_file()
    ]
    return {
        "route_name": route_name or None,
        "primary_gpx_filename": primary_filename,
        "reference_gpx_count": reference_count,
        "reference_gpx_filenames": reference_filenames[:5],
        "source_refs": list(dict.fromkeys(refs)),
    }


def _source_basename(value: Any) -> str | None:
    normalized = str(value or "").strip().replace("\\", "/")
    if not normalized:
        return None
    filename = normalized.rsplit("/", 1)[-1].strip()
    return filename or None


def search_project_route_structure(
    project_root: Path | str,
    *,
    query: str = "",
    cp: str | None = None,
    segment: str | None = None,
    limit: int = DEFAULT_WORKSPACE_SEARCH_LIMIT,
) -> dict[str, Any]:
    root = Path(project_root)
    project = _load_json_object(root / "project.json")
    project_id = str(project.get("project_id") or root.name)
    route = _load_json_object(_project_path(root, str(project.get("route_summary_ref", ""))))
    checkpoints, checkpoint_source = _load_project_list(root, project, "checkpoint_candidates_ref")
    segments, segment_source = _load_project_list(root, project, "segment_candidates_ref")
    resolved_limit = _bounded_limit(limit)
    resolved_cp = cp or _parse_cp(query)
    resolved_segment = segment or _parse_segment(query)
    collection_kind = _route_collection_kind(query)
    terms = _query_terms(query)

    items: list[dict[str, Any]] = []
    cp_by_id = {str(item.get("candidate_id")): item for item in checkpoints if isinstance(item, dict)}
    segment_quality = _segment_quality_summary(segments)
    route_elevation = _primary_route_elevation_aggregate(route, segments)
    resume_segments = _resume_segment_summary(root, project)
    reference_timing = _reference_segment_timing_summary(root, project)
    rest_areas = _rest_area_candidate_summary(root, project, segments)
    historical_overlap = _historical_gpx_overlap_summary(root, project)
    retreat_routes = _retreat_route_summary(root, project)
    display_geometry = _segment_display_geometry_summary(root, project)
    reference_tracks = _reference_track_summary(root, project)
    checkpoint_events = _checkpoint_event_summary(root, project)
    checkpoint_annotations = _checkpoint_annotation_summary(
        root,
        project,
        checkpoints,
    )
    checkpoint_quality = _checkpoint_quality_summary(checkpoints, segments)
    field_answer, field_answer_source_ref = _route_structure_field_answer(
        query=query,
        route=route,
        checkpoints=checkpoints,
        segments=segments,
        segment_quality=segment_quality,
        route_elevation=route_elevation,
        resume_segments=resume_segments,
        reference_timing=reference_timing,
        rest_areas=rest_areas,
        historical_overlap=historical_overlap,
        retreat_routes=retreat_routes,
        display_geometry=display_geometry,
        reference_tracks=reference_tracks,
        checkpoint_events=checkpoint_events,
        checkpoint_annotations=checkpoint_annotations,
        route_source=str(project.get("route_summary_ref") or "") or None,
        checkpoint_source=checkpoint_source,
        segment_source=segment_source,
    )
    for index, raw in enumerate(checkpoints):
        if not isinstance(raw, dict):
            continue
        items.append(_checkpoint_item(raw, source_path=checkpoint_source, index=index))
    for index, raw in enumerate(segments):
        if not isinstance(raw, dict):
            continue
        items.append(
            _segment_item(
                raw,
                source_path=segment_source,
                index=index,
                from_cp=cp_by_id.get(str(raw.get("from_candidate_id"))),
                to_cp=cp_by_id.get(str(raw.get("to_candidate_id"))),
            )
        )

    filtered: list[dict[str, Any]] = []
    for item in items:
        if collection_kind == "segments" and item.get("evidence_type") != "segment":
            continue
        if resolved_cp and not _item_references_cp(item, resolved_cp):
            continue
        if resolved_segment and str(item.get("candidate_id", "")).lower() != resolved_segment.lower():
            continue
        score = _major_point_match_score(item, terms, query)
        if (
            terms
            and score <= 0
            and not (resolved_cp or resolved_segment or collection_kind)
        ):
            continue
        filtered.append({k: v for k, v in item.items() if k != "search_text"} | {"match_score": round(score, 3)})

    if not terms and not (resolved_cp or resolved_segment):
        filtered = [
            {k: v for k, v in item.items() if k != "search_text"} | {"match_score": 0.0}
            for item in items
        ]

    filtered.sort(
        key=lambda item: (
            0 if item.get("evidence_type") == "checkpoint" else 1,
            str(item.get("candidate_id")),
        )
    )
    return {
        "tool_id": ROUTE_STRUCTURE_TOOL_ID,
        "status": "completed",
        "project_id": project_id,
        "source_ref": field_answer_source_ref,
        "query": query,
        "filters": {
            "cp": resolved_cp,
            "segment": resolved_segment,
            "collection_kind": collection_kind,
            "query_terms": sorted(terms),
        },
        "route_summary": _compact_route_summary(route),
        "summaries": {
            "checkpoint_count": len(checkpoints),
            "segment_count": len(segments),
            **segment_quality,
            "primary_route_elevation_aggregate": route_elevation,
            "resume_segments": resume_segments,
            "reference_segment_timing": reference_timing,
            "rest_area_candidates": rest_areas,
            "historical_gpx_overlap": historical_overlap,
            "retreat_routes": retreat_routes,
            "segment_display_geometry": display_geometry,
            "reference_tracks": reference_tracks,
            "checkpoint_events": checkpoint_events,
            "checkpoint_annotations": checkpoint_annotations,
            **checkpoint_quality,
            "source_paths": {
                "route_summary": project.get("route_summary_ref"),
                "checkpoints": checkpoint_source,
                "segments": segment_source,
            },
        },
        "searched_route_item_count": len(items),
        "matched_route_item_count": len(filtered),
        "result_count": len(filtered[:resolved_limit]),
        "field_answer": field_answer,
        "field_answer_priority": _route_structure_field_answer_priority(
            query,
            field_answer,
        ),
        "field_answer_source_ref": field_answer_source_ref,
        "results": filtered[:resolved_limit],
        "boundary": _closed_boundary(),
    }


def _segment_quality_summary(segments: list[Any]) -> dict[str, Any]:
    segment_dicts = [item for item in segments if isinstance(item, dict)]
    segments_with_distance = [
        item
        for item in segment_dicts
        if _optional_float(item.get("distance_m")) is not None
    ]
    longest = (
        max(
            segments_with_distance,
            key=lambda item: float(item["distance_m"]),
        )
        if segments_with_distance
        else None
    )
    longest_distance_m = (
        _optional_float(longest.get("distance_m"))
        if isinstance(longest, dict)
        else None
    )
    return {
        "segment_missing_distance_count": sum(
            1 for item in segment_dicts if item.get("distance_m") is None
        ),
        "segment_missing_display_geometry_count": sum(
            1
            for item in segment_dicts
            if not any(key in item for key in ("display_geometry", "geometry", "coordinates"))
        ),
        "segment_route_point_index_geometry_count": sum(
            1
            for item in segment_dicts
            if item.get("route_point_start_index") is not None
            and item.get("route_point_end_index") is not None
        ),
        "longest_segment": (
            {
                "candidate_id": longest.get("candidate_id"),
                "label": longest.get("label"),
                "from_candidate_id": longest.get("from_candidate_id"),
                "to_candidate_id": longest.get("to_candidate_id"),
                "distance_m": longest_distance_m,
                "distance_km": (
                    round(longest_distance_m / 1000.0, 3)
                    if longest_distance_m is not None
                    else None
                ),
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
            if isinstance(longest, dict)
            else None
        ),
    }


def _primary_route_elevation_aggregate(
    route: dict[str, Any],
    segments: list[Any],
) -> dict[str, Any]:
    segment_dicts = [item for item in segments if isinstance(item, dict)]
    gains = [
        value
        for item in segment_dicts
        if (value := _optional_float(item.get("elevation_gain_m"))) is not None
    ]
    losses = [
        value
        for item in segment_dicts
        if (value := _optional_float(item.get("elevation_loss_m"))) is not None
    ]
    slope_field = next(
        (
            key
            for key in (
                "average_slope_degrees",
                "average_slope",
                "mean_slope_degrees",
                "mean_slope",
            )
            if _optional_float(route.get(key)) is not None
        ),
        None,
    )
    return {
        "segment_count": len(segment_dicts),
        "elevation_gain_segment_count": len(gains),
        "elevation_loss_segment_count": len(losses),
        "total_ascent_m": round(sum(gains), 3) if gains else None,
        "total_descent_m": round(sum(losses), 3) if losses else None,
        "average_slope_available": slope_field is not None,
        "average_slope_field": slope_field,
        "average_slope": (
            _optional_float(route.get(slope_field)) if slope_field else None
        ),
        "aggregation_method": "sum_adjacent_segment_elevation_gain_loss",
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _resume_segment_summary(
    root: Path,
    project: dict[str, Any],
) -> dict[str, Any]:
    ref = str(project.get("resume_segment_report_ref") or "")
    payload = _load_json_object(_project_path(root, ref)) if ref else {}
    raw_segments = payload.get("segments") if isinstance(payload, dict) else []
    segments = raw_segments if isinstance(raw_segments, list) else []
    compact = []
    for item in segments[:12]:
        if not isinstance(item, dict):
            continue
        compact.append(
            {
                "segment_candidate_id": item.get("segment_candidate_id"),
                "from_candidate_id": item.get("from_candidate_id"),
                "to_candidate_id": item.get("to_candidate_id"),
                "max_gap_m": _optional_float(item.get("max_gap_m")),
                "resume_gap_count": item.get("resume_gap_count"),
            }
        )
    return {
        "available": bool(ref and isinstance(payload, dict) and payload),
        "count": int(payload.get("resume_segment_count") or len(segments))
        if isinstance(payload, dict)
        else len(segments),
        "segments": compact,
        "source_ref": ref or None,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _reference_segment_timing_summary(
    root: Path,
    project: dict[str, Any],
) -> dict[str, Any]:
    ref = str(project.get("reference_segment_timing_ref") or "")
    payload = _load_json_object(_project_path(root, ref)) if ref else {}
    counts = payload.get("counts") if isinstance(payload, dict) else {}
    counts = counts if isinstance(counts, dict) else {}
    raw_segments = payload.get("segments") if isinstance(payload, dict) else []
    segments = raw_segments if isinstance(raw_segments, list) else []
    compact = []
    for item in segments[:12]:
        if not isinstance(item, dict):
            continue
        duration = item.get("duration_minutes")
        duration = duration if isinstance(duration, dict) else {}
        compact.append(
            {
                "segment_id": item.get("segment_id"),
                "label": item.get("label"),
                "sample_count": item.get("sample_count"),
                "source_count": item.get("source_count"),
                "duration_minutes": {
                    key: _optional_float(duration.get(key))
                    for key in ("min", "p50", "p75", "max")
                },
            }
        )
    return {
        "available": bool(ref and isinstance(payload, dict) and payload),
        "segment_count": int(counts.get("segment_count") or len(segments)),
        "measurement_count": int(counts.get("measurement_count") or 0),
        "segments": compact,
        "source_ref": ref or None,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _rest_area_candidate_summary(
    root: Path,
    project: dict[str, Any],
    segments: list[Any],
) -> dict[str, Any]:
    ref = str(project.get("rest_area_candidates_ref") or "")
    payload = _load_json_object(_project_path(root, ref)) if ref else {}
    raw_candidates = payload.get("candidates") if isinstance(payload, dict) else []
    candidates = raw_candidates if isinstance(raw_candidates, list) else []
    segment_dicts = [item for item in segments if isinstance(item, dict)]
    compact = []
    for item in candidates[:20]:
        if not isinstance(item, dict):
            continue
        route_index = _optional_int(item.get("route_point_index"))
        linked = _segment_for_route_point_index(segment_dicts, route_index)
        nearby = []
        if linked:
            nearby = [
                str(value)
                for value in (
                    linked.get("from_candidate_id"),
                    linked.get("to_candidate_id"),
                )
                if value
            ]
        compact.append(
            {
                "candidate_id": item.get("candidate_id"),
                "checkpoint_candidate_id": item.get("checkpoint_candidate_id"),
                "route_point_index": route_index,
                "segment_candidate_id": linked.get("candidate_id") if linked else None,
                "nearby_cp_candidate_ids": nearby,
                "review_state": item.get("review_state"),
            }
        )
    return {
        "available": bool(ref and isinstance(payload, dict) and payload),
        "count": int(payload.get("rest_area_candidate_count") or len(candidates))
        if isinstance(payload, dict)
        else len(candidates),
        "candidates": compact,
        "join_method": "route_point_index_within_segment_bounds",
        "source_ref": ref or None,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _segment_for_route_point_index(
    segments: list[dict[str, Any]],
    route_point_index: int | None,
) -> dict[str, Any] | None:
    if route_point_index is None:
        return None
    for segment in segments:
        start = _optional_int(segment.get("route_point_start_index"))
        end = _optional_int(segment.get("route_point_end_index"))
        if start is None or end is None:
            continue
        if start <= route_point_index <= end:
            return segment
    return None


def _historical_gpx_overlap_summary(
    root: Path,
    project: dict[str, Any],
) -> dict[str, Any]:
    index_ref = str(project.get("historical_gpx_source_index_ref") or "")
    tracks_ref = str(project.get("reference_tracks_ref") or "")
    index_payload = _load_json_object(_project_path(root, index_ref)) if index_ref else {}
    tracks_payload = _load_json_object(_project_path(root, tracks_ref)) if tracks_ref else {}
    raw_sources = index_payload.get("sources") if isinstance(index_payload, dict) else []
    raw_tracks = (
        tracks_payload.get("reference_tracks")
        if isinstance(tracks_payload, dict)
        else []
    )
    sources = [item for item in raw_sources if isinstance(item, dict)]
    tracks = [item for item in raw_tracks if isinstance(item, dict)]
    sources_by_suffix = {
        suffix: item
        for item in sources
        if (suffix := _reference_id_suffix(item.get("source_id"))) is not None
    }
    overlaps = []
    for track in tracks:
        comparison = track.get("bbox_comparison")
        comparison = comparison if isinstance(comparison, dict) else {}
        if not comparison.get("overlaps"):
            continue
        suffix = _reference_id_suffix(track.get("reference_id"))
        source = sources_by_suffix.get(suffix or "", {})
        route = track.get("route")
        route = route if isinstance(route, dict) else {}
        overlaps.append(
            {
                "source_id": source.get("source_id"),
                "reference_id": track.get("reference_id"),
                "original_filename": source.get("original_filename")
                or route.get("route_name"),
                "route_name": route.get("route_name"),
                "primary_overlap_ratio": _optional_float(
                    comparison.get("primary_overlap_ratio")
                ),
                "comparison_overlap_ratio": _optional_float(
                    comparison.get("comparison_overlap_ratio")
                ),
                "overlap_method": "bbox_comparison",
            }
        )
    overlaps.sort(
        key=lambda item: (
            -float(item.get("primary_overlap_ratio") or 0.0),
            str(item.get("original_filename") or ""),
        )
    )
    return {
        "available": bool(index_payload and tracks_payload),
        "source_count": int(index_payload.get("source_file_count") or len(sources)),
        "reference_track_count": len(tracks),
        "overlap_count": len(overlaps),
        "overlapping_sources": overlaps,
        "source_refs": [ref for ref in (index_ref, tracks_ref) if ref],
        "overlap_source_ref": tracks_ref or None,
        "join_method": "reference_id_numeric_suffix",
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _reference_id_suffix(value: Any) -> str | None:
    match = re.search(r"\.reference\.(\d{3})$", str(value or ""), re.IGNORECASE)
    return match.group(1) if match else None


def _retreat_route_summary(
    root: Path,
    project: dict[str, Any],
) -> dict[str, Any]:
    ref = str(project.get("retreat_routes_ref") or "")
    payload = _load_json_object(_project_path(root, ref)) if ref else []
    if isinstance(payload, list):
        raw_routes = payload
    elif isinstance(payload, dict):
        raw_routes = next(
            (
                payload[key]
                for key in ("routes", "candidates", "items")
                if isinstance(payload.get(key), list)
            ),
            [],
        )
    else:
        raw_routes = []
    routes = []
    for item in raw_routes[:12]:
        if not isinstance(item, dict):
            continue
        routes.append(
            {
                "candidate_id": item.get("candidate_id"),
                "label": item.get("label"),
                "retreat_type": item.get("retreat_type"),
                "entry_checkpoint_candidate_id": item.get(
                    "entry_checkpoint_candidate_id"
                ),
                "trigger_checkpoint_candidate_id": item.get(
                    "trigger_checkpoint_candidate_id"
                ),
                "distance_m": _optional_float(item.get("distance_m")),
                "route_point_start_index": _optional_int(
                    item.get("route_point_start_index")
                ),
                "route_point_end_index": _optional_int(
                    item.get("route_point_end_index")
                ),
                "reversed_from_primary_route": bool(
                    item.get("reversed_from_primary_route")
                ),
                "review_state": item.get("review_state"),
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )
    return {
        "available": bool(ref and routes),
        "count": len(routes),
        "routes": routes,
        "source_ref": ref or None,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _segment_display_geometry_summary(
    root: Path,
    project: dict[str, Any],
) -> dict[str, Any]:
    ref = str(
        project.get("segment_display_geometry_ref")
        or "outputs/segment_display_geometry.json"
    )
    payload = _load_json_object(_project_path(root, ref))
    raw_segments = payload.get("segments") if isinstance(payload, dict) else []
    segments = raw_segments if isinstance(raw_segments, list) else []
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(segments, start=1):
        if not isinstance(item, dict):
            continue
        raw_coordinates = item.get("coordinates")
        coordinate_count = (
            len(raw_coordinates) if isinstance(raw_coordinates, list) else 0
        )
        point_count = _optional_int(item.get("display_point_count"))
        rows.append(
            {
                "segment_id": item.get("segment_candidate_id")
                or f"seg.{index:03d}",
                "point_count": point_count
                if point_count is not None
                else coordinate_count,
            }
        )
    counts = [int(item["point_count"]) for item in rows]
    return {
        "available": bool(payload and rows),
        "segment_count": len(rows),
        "total_point_count": sum(counts),
        "min_point_count": min(counts) if counts else None,
        "max_point_count": max(counts) if counts else None,
        "first_segment_counts": rows[:10],
        "source_ref": ref,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _reference_track_summary(
    root: Path,
    project: dict[str, Any],
) -> dict[str, Any]:
    tracks_ref = str(
        project.get("reference_tracks_ref") or "outputs/reference_tracks.json"
    )
    payload = _load_json_object(_project_path(root, tracks_ref))
    raw_tracks = payload.get("reference_tracks") if isinstance(payload, dict) else []
    tracks = raw_tracks if isinstance(raw_tracks, list) else []
    primary = payload.get("primary_route") if isinstance(payload, dict) else {}
    primary = primary if isinstance(primary, dict) else {}
    primary_name = str(primary.get("route_name") or project.get("route_name") or "")
    names = []
    for item in tracks:
        if not isinstance(item, dict):
            continue
        route = item.get("route")
        route = route if isinstance(route, dict) else {}
        name = str(route.get("route_name") or "").strip()
        if name:
            names.append(name)
    similarities = sorted(
        (
            {
                "route_name": name,
                "similarity": round(
                    SequenceMatcher(
                        None,
                        primary_name.casefold(),
                        name.casefold(),
                    ).ratio(),
                    3,
                ),
            }
            for name in names
        ),
        key=lambda item: (-float(item["similarity"]), str(item["route_name"])),
    )
    display_ref = str(
        project.get("reference_track_display_geometry_ref")
        or "outputs/reference_track_display_geometry.json"
    )
    display = _load_json_object(_project_path(root, display_ref))
    display_count = (
        _optional_int(display.get("reference_track_count"))
        if isinstance(display, dict)
        else None
    )
    track_count = int(payload.get("reference_track_count") or len(tracks))
    primary_geometry_ref = str(
        project.get("map_context_ref") or "normalized/map/map_context.geojson"
    )
    return {
        "available": bool(payload),
        "track_count": track_count,
        "primary_route_name": primary_name or None,
        "closest_names": similarities[:5],
        "primary_geometry_ref": primary_geometry_ref,
        "primary_geometry_prepared": _project_path(
            root, primary_geometry_ref
        ).is_file(),
        "display_geometry_ref": display_ref,
        "display_geometry_count": display_count,
        "display_geometry_prepared": bool(
            _project_path(root, display_ref).is_file()
            and display_count == track_count
        ),
        "source_ref": tracks_ref,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _checkpoint_event_summary(
    root: Path,
    project: dict[str, Any],
) -> dict[str, Any]:
    ref = str(
        project.get("checkpoint_events_ref") or "outputs/checkpoint_events.json"
    )
    payload = _load_json_object(_project_path(root, ref))
    raw_events = payload.get("events") if isinstance(payload, dict) else []
    events = [item for item in raw_events if isinstance(item, dict)]
    planned_keys = ("planned_at", "expected_at", "eta", "planned_arrival_at")
    actual_keys = ("actual_at", "actual_arrival_at", "live_observed_at")
    return {
        "available": bool(payload and events),
        "event_count": len(events),
        "observed_at_count": sum(1 for item in events if item.get("observed_at")),
        "planned_time_count": sum(
            1 for item in events if any(item.get(key) for key in planned_keys)
        ),
        "live_actual_count": sum(
            1 for item in events if any(item.get(key) for key in actual_keys)
        ),
        "first_observed_at": events[0].get("observed_at") if events else None,
        "last_observed_at": events[-1].get("observed_at") if events else None,
        "source_ref": ref,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _checkpoint_annotation_summary(
    root: Path,
    project: dict[str, Any],
    checkpoints: list[Any],
) -> dict[str, Any]:
    route_note_ref = str(
        project.get("route_note_ln_proposals_ref")
        or "outputs/route_note_ln_proposals.json"
    )
    named_point_ref = str(
        project.get("mcp_named_point_evidence_ref")
        or "outputs/mcp/named_point_evidence.json"
    )
    route_note_payload = _load_json_object(_project_path(root, route_note_ref))
    named_point_payload = _load_json_object(_project_path(root, named_point_ref))
    checkpoint_rows = [
        item
        for item in checkpoints
        if isinstance(item, dict)
        and _optional_float(item.get("lat")) is not None
        and _optional_float(item.get("lon")) is not None
    ]

    def nearest_checkpoint(lat: float, lon: float) -> dict[str, Any] | None:
        if not checkpoint_rows:
            return None
        checkpoint = min(
            checkpoint_rows,
            key=lambda item: (
                _haversine_m(
                    lat,
                    lon,
                    float(item["lat"]),
                    float(item["lon"]),
                ),
                str(item.get("candidate_id") or ""),
                str(item.get("label") or ""),
            ),
        )
        distance_m = _haversine_m(
            lat,
            lon,
            float(checkpoint["lat"]),
            float(checkpoint["lon"]),
        )
        return {
            "checkpoint_id": checkpoint.get("candidate_id"),
            "checkpoint_label": checkpoint.get("label"),
            "distance_m": round(distance_m),
        }

    route_note_matches: list[dict[str, Any]] = []
    raw_proposals = route_note_payload.get("proposals")
    for item in raw_proposals if isinstance(raw_proposals, list) else []:
        if not isinstance(item, dict):
            continue
        lat = _optional_float(item.get("lat"))
        lon = _optional_float(item.get("lon"))
        if lat is None or lon is None:
            continue
        nearest = nearest_checkpoint(lat, lon)
        if nearest is None or float(nearest["distance_m"]) > 250:
            continue
        route_note_matches.append(
            {
                **nearest,
                "label": item.get("route_note_summary"),
                "annotation_id": item.get("proposal_id"),
                "annotation_kind": "route_note",
            }
        )

    named_point_matches: list[dict[str, Any]] = []
    raw_named_points = named_point_payload.get("named_points")
    for item in raw_named_points if isinstance(raw_named_points, list) else []:
        if not isinstance(item, dict):
            continue
        position = item.get("route_position")
        position = position if isinstance(position, dict) else {}
        lat = _optional_float(position.get("lat"))
        lon = _optional_float(position.get("lon"))
        if lat is None or lon is None:
            continue
        nearest = nearest_checkpoint(lat, lon)
        if nearest is None or float(nearest["distance_m"]) > 250:
            continue
        named_point_matches.append(
            {
                **nearest,
                "label": item.get("canonical_name"),
                "annotation_id": item.get("named_point_id"),
                "annotation_kind": "map_named_point",
            }
        )

    return {
        "available": bool(route_note_matches or named_point_matches),
        "max_join_distance_m": 250,
        "route_note_match_count": len(route_note_matches),
        "named_point_match_count": len(named_point_matches),
        "route_note_matches": _dedupe_annotation_matches(route_note_matches)[:5],
        "named_point_matches": _dedupe_annotation_matches(named_point_matches)[:5],
        "source_refs": [route_note_ref, named_point_ref],
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _dedupe_annotation_matches(
    matches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ordered = sorted(
        matches,
        key=lambda item: (
            (
                math.inf
                if item.get("distance_m") is None
                else float(item["distance_m"])
            ),
            str(item.get("checkpoint_id") or ""),
            str(item.get("label") or ""),
        ),
    )
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in ordered:
        key = (str(item.get("checkpoint_id") or ""), str(item.get("label") or ""))
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def _haversine_m(
    lat_a: float,
    lon_a: float,
    lat_b: float,
    lon_b: float,
) -> float:
    lat_a_rad = math.radians(lat_a)
    lat_b_rad = math.radians(lat_b)
    delta_lat = math.radians(lat_b - lat_a)
    delta_lon = math.radians(lon_b - lon_a)
    haversine = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(lat_a_rad)
        * math.cos(lat_b_rad)
        * math.sin(delta_lon / 2.0) ** 2
    )
    return 12_742_000.0 * math.atan2(
        math.sqrt(haversine),
        math.sqrt(max(0.0, 1.0 - haversine)),
    )


def _route_structure_field_answer(
    *,
    query: str,
    route: dict[str, Any],
    checkpoints: list[Any],
    segments: list[Any],
    segment_quality: dict[str, Any],
    route_elevation: dict[str, Any],
    resume_segments: dict[str, Any],
    reference_timing: dict[str, Any],
    rest_areas: dict[str, Any],
    historical_overlap: dict[str, Any],
    retreat_routes: dict[str, Any],
    display_geometry: dict[str, Any],
    reference_tracks: dict[str, Any],
    checkpoint_events: dict[str, Any],
    checkpoint_annotations: dict[str, Any],
    route_source: str | None,
    checkpoint_source: str,
    segment_source: str,
) -> tuple[str | None, str | None]:
    if re.search(
        r"primary route.*(?:gpx|總里程|點數|最低|最高海拔)",
        query,
        re.IGNORECASE,
    ):
        distance_m = _optional_float(route.get("distance_m"))
        distance_km = round(distance_m / 1000.0, 3) if distance_m is not None else None
        return (
            f"Primary route GPX：總里程 {distance_km} 公里、"
            f"點數 {route.get('point_count')}、最低海拔 "
            f"{route.get('elevation_min_m')} m、最高海拔 "
            f"{route.get('elevation_max_m')} m。",
            route_source,
        )
    if "route summary" in query.casefold() and re.search(
        r"起點|終點|bbox", query, re.IGNORECASE
    ):
        checkpoint_rows = [item for item in checkpoints if isinstance(item, dict)]
        start = checkpoint_rows[0] if checkpoint_rows else {}
        finish = checkpoint_rows[-1] if checkpoint_rows else {}
        bbox = route.get("bbox_wgs84")
        bbox = bbox if isinstance(bbox, dict) else {}
        return (
            "Route summary geometry：bbox="
            f"[{bbox.get('min_lon')},{bbox.get('min_lat')},"
            f"{bbox.get('max_lon')},{bbox.get('max_lat')}], "
            f"start {start.get('candidate_id')}="
            f"({start.get('lat')},{start.get('lon')}), "
            f"finish {finish.get('candidate_id')}="
            f"({finish.get('lat')},{finish.get('lon')}) "
            f"[{route_source or checkpoint_source}]。",
            route_source,
        )
    if re.search(r"checkpoint candidates?", query, re.IGNORECASE) and re.search(
        r"多少|幾個|第一個|最後一個", query, re.IGNORECASE
    ):
        checkpoint_rows = [item for item in checkpoints if isinstance(item, dict)]
        first = checkpoint_rows[0] if checkpoint_rows else {}
        last = checkpoint_rows[-1] if checkpoint_rows else {}
        return (
            f"checkpoint candidates 共 {len(checkpoint_rows)} 個；"
            f"第一個 {first.get('candidate_id')}/{first.get('label')}，"
            f"最後一個 {last.get('candidate_id')}/{last.get('label')}。",
            checkpoint_source,
        )
    if re.search(r"checkpoint events?", query, re.IGNORECASE):
        return (
            "Checkpoint candidate event projections 共 "
            f"{checkpoint_events.get('event_count')} 筆："
            f"observed_at={checkpoint_events.get('observed_at_count')}，"
            f"planned/ETA fields={checkpoint_events.get('planned_time_count')}，"
            f"live actual events={checkpoint_events.get('live_actual_count')}。"
            "observed_at 來自 historical golden GPX 的 candidate projection，"
            "不是本次行程的即時實際通過事件。",
            checkpoint_events.get("source_ref"),
        )
    if re.search(
        r"route\s*note|地圖標註|map\s*(?:label|annotation)",
        query,
        re.IGNORECASE,
    ):
        route_note_rows = checkpoint_annotations.get("route_note_matches")
        named_point_rows = checkpoint_annotations.get("named_point_matches")
        route_note_rows = route_note_rows if isinstance(route_note_rows, list) else []
        named_point_rows = named_point_rows if isinstance(named_point_rows, list) else []
        route_note_text = "; ".join(
            f"{item.get('checkpoint_id')}←route note「{item.get('label')}」"
            f"({item.get('distance_m')} m)"
            for item in route_note_rows
            if isinstance(item, dict)
        ) or "none within 250 m"
        named_point_text = "; ".join(
            f"{item.get('checkpoint_id')}←地圖/命名點「{item.get('label')}」"
            f"({item.get('distance_m')} m)"
            for item in named_point_rows
            if isinstance(item, dict)
        ) or "none within 250 m"
        source_refs = checkpoint_annotations.get("source_refs")
        source_refs = source_refs if isinstance(source_refs, list) else []
        route_note_source = str(source_refs[0]) if source_refs else checkpoint_source
        named_point_source = (
            str(source_refs[1]) if len(source_refs) > 1 else route_note_source
        )
        return (
            f"靠近 route note 的 checkpoint（前 {len(route_note_rows)} 筆）："
            f"{route_note_text} [{route_note_source}]。"
            f"靠近地圖/命名點的 checkpoint（前 {len(named_point_rows)} 筆）："
            f"{named_point_text} [{named_point_source}]。",
            route_note_source,
        )
    if re.search(r"多少個?\s*segments?|切成多少", query, re.IGNORECASE):
        rows = [item for item in segments if isinstance(item, dict)]
        labels = [str(item.get("label") or "") for item in rows]
        sequential = bool(labels) and all(
            label == f"Segment {index:03d}"
            for index, label in enumerate(labels, start=1)
        )
        label_summary = (
            f"Segment 001 至 Segment {len(labels):03d}（連續編號）"
            if sequential
            else ", ".join(labels[:16])
        )
        if not sequential and len(labels) > 16:
            label_summary += f"，其餘 {len(labels) - 16} 段見 artifact"
        return (
            f"Route segments 共 {len(rows)} 段；名稱：{label_summary}。",
            segment_source,
        )
    if re.search(
        r"segment display geometry|display geometry.*座標點|每一段.*座標點",
        query,
        re.IGNORECASE,
    ):
        first_counts = ", ".join(
            f"{item.get('segment_id')}={item.get('point_count')}"
            for item in display_geometry.get("first_segment_counts") or []
        )
        return (
            f"Segment display geometry 共 {display_geometry.get('segment_count')} 段、"
            f"總座標點 {display_geometry.get('total_point_count')}；"
            f"每段 {display_geometry.get('min_point_count')}-"
            f"{display_geometry.get('max_point_count')} 點。"
            f"前十段：{first_counts}；完整逐段表見 artifact。",
            display_geometry.get("source_ref"),
        )
    if "reference tracks" in query.casefold() and re.search(
        r"總共|幾條|名稱最接近|closest", query, re.IGNORECASE
    ):
        closest = ", ".join(
            f"{item.get('route_name')} ({item.get('similarity')})"
            for item in reference_tracks.get("closest_names") or []
        )
        return (
            f"reference tracks 共 {reference_tracks.get('track_count')} 條；"
            f"與 primary route 名稱最接近（字串相似度）依序為：{closest}。",
            reference_tracks.get("source_ref"),
        )
    if re.search(r"幾何.*準備完成|geometry.*prepared", query, re.IGNORECASE):
        primary_status = (
            "prepared"
            if reference_tracks.get("primary_geometry_prepared")
            else "missing"
        )
        reference_status = (
            "prepared"
            if reference_tracks.get("display_geometry_prepared")
            else "incomplete"
        )
        return (
            f"primary route geometry={primary_status} "
            f"({reference_tracks.get('primary_geometry_ref')})；"
            f"reference track display geometry={reference_status}，"
            f"{reference_tracks.get('display_geometry_count')}/"
            f"{reference_tracks.get('track_count')} "
            f"({reference_tracks.get('display_geometry_ref')})。",
            reference_tracks.get("source_ref"),
        )
    if re.search(r"dtm.*coverage|coverage.*dtm|dtm.*覆蓋", query, re.IGNORECASE):
        return (
            "Route structure 只提供 route segment ID 與幾何鏈結，不含 DTM "
            "coverage 完整性欄位；不可從 route list 推論哪些 segment 不完整，"
            "應以 terrain/DTM coverage artifact 為準。",
            segment_source,
        )
    if re.search(r"retreat|撤退路線|撤退路徑", query, re.IGNORECASE):
        rows = retreat_routes.get("routes") or []
        if not rows:
            return "Retreat route candidate artifact 沒有候選路線。", retreat_routes.get(
                "source_ref"
            )
        details = "; ".join(
            f"{item.get('candidate_id')} "
            f"({item.get('retreat_type')}, trigger="
            f"{item.get('trigger_checkpoint_candidate_id')}, entry="
            f"{item.get('entry_checkpoint_candidate_id')}, route points="
            f"{item.get('route_point_start_index')}-"
            f"{item.get('route_point_end_index')})"
            for item in rows
        )
        return (
            f"Retreat route candidates 共 {retreat_routes.get('count')} 條：{details}。"
            "需與 terrain tool 的高風險 segment 依 route-point/progress 另行比對；"
            "候選撤退路線未經現場驗證。",
            retreat_routes.get("source_ref"),
        )
    if re.search(r"historical.*gpx|gpx.*source.*index|來源.*重疊", query, re.IGNORECASE):
        rows = historical_overlap.get("overlapping_sources") or []
        if not rows:
            return (
                "Historical GPX index 與 reference track report 沒有可確認的重疊來源。",
                historical_overlap.get("overlap_source_ref"),
            )
        bounded_rows = rows[:10]
        details = "; ".join(
            f"{item.get('original_filename')} "
            f"(primary_overlap_ratio={item.get('primary_overlap_ratio')})"
            for item in bounded_rows
        )
        remaining = max(0, len(rows) - len(bounded_rows))
        remainder_text = f"；其餘 {remaining} 個見 artifact" if remaining else ""
        return (
            f"Historical GPX sources 中有 {historical_overlap.get('overlap_count')} "
            f"個與目前路線 bbox 重疊；前 {len(bounded_rows)} 個："
            f"{details}{remainder_text}。",
            historical_overlap.get("overlap_source_ref"),
        )
    if re.search(r"resume|續接|可續接", query, re.IGNORECASE):
        rows = resume_segments.get("segments") or []
        if not rows:
            return "Resume segment report 沒有列出可續接路段。", resume_segments.get(
                "source_ref"
            )
        details = "; ".join(
            f"{item.get('segment_candidate_id')} "
            f"({item.get('from_candidate_id')}->{item.get('to_candidate_id')}, "
            f"max_gap={item.get('max_gap_m')} m)"
            for item in rows
        )
        return (
            f"Resume segment report 共 {resume_segments.get('count')} 段：{details}。",
            resume_segments.get("source_ref"),
        )
    if re.search(r"reference.*timing|路段時間|時間統計", query, re.IGNORECASE):
        rows = reference_timing.get("segments") or []
        if not rows:
            return "Reference segment timing 沒有可用路段統計。", reference_timing.get(
                "source_ref"
            )
        details = "; ".join(
            f"{item.get('label') or item.get('segment_id')} "
            f"p50={item.get('duration_minutes', {}).get('p50')} 分、"
            f"range={item.get('duration_minutes', {}).get('min')}-"
            f"{item.get('duration_minutes', {}).get('max')} 分"
            for item in rows
        )
        return (
            f"Reference timing 共 {reference_timing.get('segment_count')} 個路段、"
            f"{reference_timing.get('measurement_count')} 筆量測：{details}。",
            reference_timing.get("source_ref"),
        )
    if re.search(r"rest[ _-]?area|休息區|休息點", query, re.IGNORECASE):
        rows = rest_areas.get("candidates") or []
        if not rows:
            return "Rest area candidate artifact 沒有候選點。", rest_areas.get(
                "source_ref"
            )
        details = "; ".join(
            f"{_rest_area_display_id(item.get('candidate_id'))}->"
            f"{item.get('segment_candidate_id') or '未連結'}"
            f" ({'/'.join(item.get('nearby_cp_candidate_ids') or []) or '無相鄰 CP'})"
            for item in rows
        )
        return (
            f"Rest area candidates 共 {rest_areas.get('count')} 個：{details}。",
            rest_areas.get("source_ref"),
        )
    if re.search(r"總爬升|總下降|平均坡度|total ascent|total descent", query, re.IGNORECASE):
        slope_text = (
            f"平均坡度={route_elevation.get('average_slope')}"
            if route_elevation.get("average_slope_available")
            else "平均坡度欄位不存在"
        )
        return (
            f"Primary route 的 segment-level elevation 資料可聚合："
            f"總爬升 {route_elevation.get('total_ascent_m')} m、"
            f"總下降 {route_elevation.get('total_descent_m')} m；{slope_text}。",
            segment_source,
        )
    if re.search(r"最長|longest|max(?:imum)?.*distance", query, re.IGNORECASE):
        longest = segment_quality.get("longest_segment")
        if not isinstance(longest, dict) or not longest.get("candidate_id"):
            return "Route segment 距離資料缺失，無法計算最長路段。", segment_source
        return (
            f"距離最長的 route segment 是 {longest['candidate_id']}"
            f"（{longest.get('label') or '未命名'}），"
            f"位於 {longest.get('from_candidate_id')}->"
            f"{longest.get('to_candidate_id')}，"
            f"長度 {longest.get('distance_km')} 公里"
            f"（{longest.get('distance_m')} 公尺）。",
            segment_source,
        )
    return None, None


def _rest_area_display_id(value: Any) -> str:
    text = str(value or "unknown")
    if text.startswith("rest_area.") and len(text) > 24:
        return f"rest_area#{text.rsplit('.', 1)[-1]}"
    return text


def _route_structure_field_answer_priority(
    query: str,
    field_answer: str | None,
) -> int:
    if not field_answer:
        return 0
    if re.search(r"dtm.*coverage|coverage.*dtm|dtm.*覆蓋", query, re.IGNORECASE):
        return 10
    if re.search(r"retreat|撤退路線|撤退路徑", query, re.IGNORECASE) and re.search(
        r"terrain|risk|高風險|風險.*segment|segment.*風險",
        query,
        re.IGNORECASE,
    ):
        # Route structure can enumerate candidates but cannot complete this
        # cross-artifact spatial join. The terrain adapter's joined answer must
        # remain the exact synthesis contract.
        return 10
    return 100


def _checkpoint_quality_summary(
    checkpoints: list[Any],
    segments: list[Any],
) -> dict[str, Any]:
    checkpoint_dicts = [item for item in checkpoints if isinstance(item, dict)]
    segment_dicts = [item for item in segments if isinstance(item, dict)]
    labels: dict[str, list[str]] = {}
    for item in checkpoint_dicts:
        label = str(item.get("label") or "").strip()
        if not label:
            continue
        labels.setdefault(label, []).append(str(item.get("candidate_id") or ""))
    duplicate_groups = {
        label: ids
        for label, ids in labels.items()
        if len(ids) > 1
    }
    expected_segment_count = max(0, len(checkpoint_dicts) - 1)
    segment_count = len(segment_dicts)
    return {
        "expected_segment_count_from_checkpoints": expected_segment_count,
        "segment_count_matches_checkpoint_chain": segment_count == expected_segment_count,
        "segment_count_delta_from_expected": segment_count - expected_segment_count,
        "checkpoint_duplicate_label_group_count": len(duplicate_groups),
        "checkpoint_duplicate_label_groups": duplicate_groups,
    }


def search_project_major_points(
    project_root: Path | str,
    *,
    query: str = "",
    limit: int = DEFAULT_WORKSPACE_SEARCH_LIMIT,
    cp: str | None = None,
    point_kinds: list[str] | None = None,
) -> dict[str, Any]:
    root = Path(project_root)
    project = _load_json_object(root / "project.json")
    project_id = str(project.get("project_id") or root.name)
    resolved_limit = _bounded_limit(limit)
    resolved_cp = cp or _parse_cp(query)
    resolved_kinds = {str(kind).lower() for kind in (point_kinds or []) if str(kind).strip()}
    terms = _query_terms(query)
    items, source_report = _major_point_items(root, project)
    boss_source = next(
        (
            item
            for item in source_report
            if item.get("source_kind") == "boss_points"
        ),
        {},
    )
    boss_point_count = (
        sum(1 for item in items if item["evidence_type"] == "boss_point")
        if boss_source.get("status") == "loaded"
        else None
    )

    filtered: list[dict[str, Any]] = []
    for item in items:
        if resolved_cp and not _item_references_cp(item, resolved_cp):
            continue
        if resolved_kinds and not (set(str(kind).lower() for kind in item.get("point_classes", [])) & resolved_kinds):
            continue
        score = _major_point_match_score(item, terms, query)
        if terms and score <= 0 and not resolved_cp and not resolved_kinds:
            continue
        compact = {k: v for k, v in item.items() if k != "search_text"}
        compact["match_score"] = round(score, 3)
        filtered.append(compact)

    if not terms and not resolved_cp and not resolved_kinds:
        filtered = [
            {k: v for k, v in item.items() if k != "search_text"} | {"match_score": 0.0}
            for item in items
        ]

    filtered.sort(
        key=lambda item: (
            -float(item.get("match_score") or 0.0),
            -float(item.get("score") or 0.0),
            str(item.get("label") or item.get("candidate_id")),
        )
    )
    results = filtered[:resolved_limit]
    field_answer, field_answer_source_ref = _major_point_field_answer(
        items,
        results,
        query=query,
        point_kinds=resolved_kinds,
        boss_point_count=boss_point_count,
        source_report=source_report,
    )
    return {
        "tool_id": MAJOR_POINT_TOOL_ID,
        "status": "completed",
        "project_id": project_id,
        "query": query,
        "answerability": (
            "major_points_available" if results else "major_points_missing_evidence"
        ),
        "filters": {
            "cp": resolved_cp,
            "point_kinds": sorted(resolved_kinds) if resolved_kinds else None,
            "query_terms": sorted(terms),
        },
        "source_report": source_report,
        "summaries": {
            "major_point_count": sum(1 for item in items if item["evidence_type"] == "major_point"),
            "named_point_count": sum(1 for item in items if item["evidence_type"] == "named_point"),
            "support_row_count": sum(1 for item in items if item["evidence_type"] == "major_point_cp_support"),
            "ocr_label_count": sum(1 for item in items if item["evidence_type"] == "ocr_label"),
            "boss_point_count": boss_point_count,
        },
        "searched_point_count": len(items),
        "matched_point_count": len(filtered),
        "result_count": len(results),
        "field_answer": field_answer,
        "field_answer_priority": 100 if field_answer else 0,
        "field_answer_source_ref": field_answer_source_ref,
        "source_ref": field_answer_source_ref,
        "results": results,
        "boundary": _closed_boundary(),
    }


def search_project_evidence_fulltext(
    project_root: Path | str,
    *,
    query: str,
    limit: int = DEFAULT_WORKSPACE_SEARCH_LIMIT,
    evidence_types: list[str] | None = None,
) -> dict[str, Any]:
    from scout_agent_kb import query_project_local_evidence

    root = Path(project_root)
    project = _load_json_object(root / "project.json")
    project_id = str(project.get("project_id") or root.name)
    result = query_project_local_evidence(
        root,
        query=query,
        limit=_bounded_limit(limit),
        evidence_types=set(evidence_types) if evidence_types else None,
    )
    return {
        "tool_id": EVIDENCE_FULLTEXT_TOOL_ID,
        "status": "completed",
        "project_id": project_id,
        "query": result.query,
        "retrieval_engine": result.retrieval_engine,
        "result_count": result.result_count,
        "searched_record_count": result.searched_record_count,
        "results": result.results,
        "boundary": {
            **result.boundary.model_dump(mode="json"),
            "read_only": True,
            "runtime_safety_truth": False,
            "raw_payloads_embedded": False,
        },
    }


def _catalog_items(root: Path, project: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for key, value in sorted(project.items()):
        if not key.endswith("_ref") or not isinstance(value, str):
            continue
        domain = _domain_for_ref(key, value)
        path = _project_path(root, value)
        count_keys = _related_count_keys(project, key)
        artifact_kind = None
        top_level_keys: list[str] = []
        summary_fields: dict[str, Any] = {}
        if path.exists() and path.suffix.lower() in {".json", ".geojson"}:
            payload = _load_json_object(path)
            artifact_kind = payload.get("artifact_kind") if isinstance(payload, dict) else None
            top_level_keys = sorted(payload.keys())[:12] if isinstance(payload, dict) else []
            summary_fields = _artifact_summary_fields(payload)
        items.append(
            {
                "evidence_type": "workspace_artifact_ref",
                "domain": domain,
                "ref_key": key,
                "source_path": value,
                "exists": path.exists(),
                "count_keys": count_keys,
                "artifact_kind": artifact_kind,
                "top_level_keys": top_level_keys,
                "summary_fields": summary_fields,
                "candidate_only": _looks_candidate_key(key, value),
                "runtime_safety_truth": False,
                "search_text": " ".join(
                    [
                        key,
                        value,
                        domain,
                        artifact_kind or "",
                        " ".join(count_keys.keys()),
                        " ".join(str(v) for v in count_keys.values()),
                        " ".join(summary_fields.keys()),
                        " ".join(str(v) for v in summary_fields.values()),
                    ]
                ),
            }
        )
    items.extend(_preparation_metadata_items(root))
    return items


def _artifact_summary_fields(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    summary: dict[str, Any] = {}
    for key in (
        "status",
        "generated_at",
        "prepared_at",
        "completed_at",
        "finished_at",
        "profile",
        "blocker_count",
        "warning_count",
        "review_item_count",
        "failed_count",
    ):
        value = payload.get(key)
        if value is not None and isinstance(value, (str, int, float, bool)):
            summary[key] = value
    for key in ("blockers", "warnings", "review_items", "failed_items"):
        value = payload.get(key)
        if not isinstance(value, list) or not value:
            continue
        summary[key] = [
            item
            if isinstance(item, (str, int, float, bool))
            else {
                str(field): field_value
                for field, field_value in list(item.items())[:6]
                if isinstance(field_value, (str, int, float, bool))
            }
            for item in value[:8]
            if isinstance(item, (str, int, float, bool, dict))
        ]
    return summary


def _preparation_metadata_items(root: Path) -> list[dict[str, Any]]:
    paths = (
        "outputs/layers/layer_preparation_summary.json",
        "outputs/layers/map_preparation_summary.json",
        "outputs/layers/layer_preparation_job.json",
        "outputs/layers/layer_preparation_manifest.json",
        "outputs/scout_ai/pretrip_import_preparation_run_result.json",
        "outputs/scout_ai/pretrip_import_preparation_skill_run_record.json",
        "outputs/risk/risk_ribbon.metadata.json",
        "outputs/risk/calibrated_risk_heatmap.metadata.json",
        "outputs/risk/risk_score_points.metadata.json",
        "outputs/risk/route_risk.metadata.json",
    )
    items: list[dict[str, Any]] = []
    for rel in paths:
        path = root / rel
        artifact_kind = None
        top_level_keys: list[str] = []
        status = None
        summary_fields: dict[str, Any] = {}
        if path.exists() and path.suffix.lower() in {".json", ".geojson"}:
            payload = _load_json_object(path)
            if isinstance(payload, dict):
                artifact_kind = payload.get("artifact_kind")
                status = payload.get("status") or payload.get("overall_status")
                top_level_keys = sorted(payload.keys())[:12]
                summary_fields = _artifact_summary_fields(payload)
        ref_key = Path(rel).name.replace(".", "_")
        items.append(
            {
                "evidence_type": "workspace_preparation_metadata",
                "domain": "workspace",
                "ref_key": ref_key,
                "source_path": rel,
                "exists": path.exists(),
                "count_keys": {},
                "artifact_kind": artifact_kind,
                "status": status,
                "summary_fields": summary_fields,
                "top_level_keys": top_level_keys,
                "candidate_only": True,
                "runtime_safety_truth": False,
                "search_text": " ".join(
                    [
                        ref_key,
                        rel,
                        "workspace preparation metadata outputs completed missing preparation_summary map_preparation layer_preparation pretrip_import",
                        artifact_kind or "",
                        status or "",
                        " ".join(top_level_keys),
                        " ".join(summary_fields.keys()),
                        " ".join(str(value) for value in summary_fields.values()),
                    ]
                ),
            }
        )
    return items


def _catalog_summaries(items: list[dict[str, Any]]) -> dict[str, Any]:
    by_domain: dict[str, dict[str, int]] = {}
    for item in items:
        domain = str(item["domain"])
        by_domain.setdefault(domain, {"total": 0, "existing": 0, "missing": 0})
        by_domain[domain]["total"] += 1
        by_domain[domain]["existing" if item["exists"] else "missing"] += 1
    return {
        "artifact_ref_count": len(items),
        "existing_ref_count": sum(1 for item in items if item["exists"]),
        "missing_ref_count": sum(1 for item in items if not item["exists"]),
        "preparation_metadata_count": sum(
            1 for item in items if item.get("evidence_type") == "workspace_preparation_metadata"
        ),
        "existing_preparation_metadata_count": sum(
            1
            for item in items
            if item.get("evidence_type") == "workspace_preparation_metadata" and item["exists"]
        ),
        "missing_preparation_metadata_count": sum(
            1
            for item in items
            if item.get("evidence_type") == "workspace_preparation_metadata" and not item["exists"]
        ),
        "domains": by_domain,
    }


def _checkpoint_item(raw: dict[str, Any], *, source_path: str, index: int) -> dict[str, Any]:
    candidate_id = str(raw.get("candidate_id") or f"checkpoint.{index}")
    label = str(raw.get("label") or candidate_id)
    return {
        "evidence_type": "checkpoint",
        "candidate_id": candidate_id,
        "label": label,
        "checkpoint_type": raw.get("checkpoint_type"),
        "lat": _optional_float(raw.get("lat")),
        "lon": _optional_float(raw.get("lon")),
        "route_point_index": raw.get("route_point_index"),
        "arrival_radius_m": raw.get("arrival_radius_m"),
        "review_state": raw.get("review_state"),
        "candidate_only": bool(raw.get("candidate_only", True)),
        "runtime_safety_truth": bool(raw.get("runtime_safety_truth", False)),
        "source_path": source_path,
        "search_text": " ".join(str(part) for part in (candidate_id, label, raw.get("notes"), raw.get("checkpoint_type")) if part),
    }


def _segment_item(
    raw: dict[str, Any],
    *,
    source_path: str,
    index: int,
    from_cp: dict[str, Any] | None,
    to_cp: dict[str, Any] | None,
) -> dict[str, Any]:
    candidate_id = str(raw.get("candidate_id") or f"segment.{index}")
    label = str(raw.get("label") or candidate_id)
    return {
        "evidence_type": "segment",
        "candidate_id": candidate_id,
        "label": label,
        "from_candidate_id": raw.get("from_candidate_id"),
        "to_candidate_id": raw.get("to_candidate_id"),
        "from_label": from_cp.get("label") if isinstance(from_cp, dict) else None,
        "to_label": to_cp.get("label") if isinstance(to_cp, dict) else None,
        "distance_m": _optional_float(raw.get("distance_m")),
        "route_point_start_index": raw.get("route_point_start_index"),
        "route_point_end_index": raw.get("route_point_end_index"),
        "elevation_gain_m": _optional_float(raw.get("elevation_gain_m")),
        "elevation_loss_m": _optional_float(raw.get("elevation_loss_m")),
        "review_state": raw.get("review_state"),
        "candidate_only": bool(raw.get("candidate_only", True)),
        "runtime_safety_truth": bool(raw.get("runtime_safety_truth", False)),
        "source_path": source_path,
        "search_text": " ".join(
            str(part)
            for part in (
                candidate_id,
                label,
                raw.get("from_candidate_id"),
                raw.get("to_candidate_id"),
                raw.get("notes"),
            )
            if part
        ),
    }


def _major_point_items(
    root: Path,
    project: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    items: list[dict[str, Any]] = []
    report: list[dict[str, Any]] = []
    named_points = _load_named_points(root, project, report)
    support_rows = _load_support_rows(root, project, report)
    support_by_id = {str(row.get("mcp_id")): row for row in support_rows if row.get("mcp_id")}

    ref = str(project.get("mcp_candidates_ref") or "outputs/mcp/mcp_candidates.json")
    payload = _load_json_object(_project_path(root, ref))
    candidates = payload.get("mcp_candidates") if isinstance(payload, dict) else []
    if not isinstance(candidates, list):
        candidates = []
    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        mcp_id = str(raw.get("mcp_id") or "")
        support = support_by_id.get(mcp_id, {})
        nearest_cp = raw.get("nearest_scout_cp")
        if not isinstance(nearest_cp, dict):
            nearest_cp = support.get("nearest_scout_cp") if isinstance(support, dict) else {}
        score_components = raw.get("score_components") if isinstance(raw.get("score_components"), dict) else {}
        linked_named_points = [
            named_points.get(str(point_id), {})
            for point_id in raw.get("linked_named_points", [])
            if str(point_id) in named_points
        ]
        aliases = []
        for point in linked_named_points:
            aliases.extend(point.get("aliases", []) if isinstance(point.get("aliases"), list) else [])
        label = str(raw.get("label") or mcp_id)
        classes = raw.get("mcp_classes", [])
        items.append(
            {
                "evidence_type": "major_point",
                "candidate_id": mcp_id,
                "label": label,
                "point_classes": classes,
                "aliases": aliases,
                "lat": _optional_float(raw.get("lat")),
                "lon": _optional_float(raw.get("lon")),
                "distance_m": _optional_float(raw.get("distance_m")),
                "distance_km": _km(raw.get("distance_m")),
                "nearest_cp_candidate_id": nearest_cp.get("candidate_id") if isinstance(nearest_cp, dict) else None,
                "nearest_cp_distance_m": _optional_float(nearest_cp.get("distance_m")) if isinstance(nearest_cp, dict) else None,
                "linked_cp_candidates": raw.get("linked_cp_candidates", []),
                "linked_named_points": raw.get("linked_named_points", []),
                "support_status": support.get("support_status") if isinstance(support, dict) else None,
                "review_state": raw.get("review_state"),
                "review_required": bool(support.get("review_required", True)) if isinstance(support, dict) else True,
                "score": _optional_float(score_components.get("total")),
                "candidate_only": True,
                "runtime_safety_truth": False,
                "source_path": ref,
                "search_text": " ".join(
                    str(part)
                    for part in (
                        mcp_id,
                        label,
                        " ".join(classes),
                        _point_class_alias_text(classes),
                        " ".join(raw.get("linked_cp_candidates", [])),
                        " ".join(aliases),
                        support.get("recommendation") if isinstance(support, dict) else None,
                    )
                    if part
                ),
            }
        )

    for row in support_rows:
        label = str(row.get("label") or row.get("mcp_id") or "")
        items.append(
            {
                "evidence_type": "major_point_cp_support",
                "candidate_id": row.get("mcp_id"),
                "label": label,
                "point_classes": [],
                "distance_m": _optional_float(row.get("distance_m")),
                "distance_km": _km(row.get("distance_m")),
                "nearest_cp_candidate_id": (row.get("nearest_scout_cp") or {}).get("candidate_id")
                if isinstance(row.get("nearest_scout_cp"), dict)
                else None,
                "linked_cp_candidates": row.get("linked_cp_candidates", []),
                "support_status": row.get("support_status"),
                "suggested_cp_insertion": row.get("suggested_cp_insertion"),
                "suppressed_point_count": _optional_int(
                    row.get("suppressed_point_count")
                ),
                "review_required": bool(row.get("review_required", True)),
                "candidate_only": bool(row.get("candidate_only", True)),
                "runtime_safety_truth": bool(row.get("runtime_safety_truth", False)),
                "source_path": str(project.get("mcp_cp_support_reconciliation_ref") or "outputs/mcp/mcp_cp_support_reconciliation.json"),
                "search_text": " ".join(
                    str(part)
                    for part in (
                        row.get("mcp_id"),
                        label,
                        " ".join(row.get("linked_cp_candidates", [])),
                        row.get("recommendation"),
                    )
                    if part
                ),
            }
        )

    for point in named_points.values():
        route_position = point.get("route_position") if isinstance(point.get("route_position"), dict) else {}
        label = str(point.get("canonical_name") or point.get("named_point_id") or "")
        classes = point.get("point_class", [])
        items.append(
            {
                "evidence_type": "named_point",
                "candidate_id": point.get("named_point_id"),
                "label": label,
                "point_classes": classes,
                "aliases": point.get("aliases", []),
                "lat": _optional_float(route_position.get("lat")),
                "lon": _optional_float(route_position.get("lon")),
                "distance_m": _optional_float(route_position.get("distance_m")),
                "distance_km": _km(route_position.get("distance_m")),
                "nearest_cp_candidate_id": point.get("nearest_cp_candidate_id"),
                "candidate_only": True,
                "runtime_safety_truth": False,
                "source_path": str(project.get("mcp_named_point_evidence_ref") or "outputs/mcp/named_point_evidence.json"),
                "search_text": " ".join(
                    str(part)
                    for part in (
                        point.get("named_point_id"),
                        label,
                        " ".join(point.get("aliases", [])),
                        " ".join(classes),
                        _point_class_alias_text(classes),
                    )
                    if part
                ),
            }
        )

    items.extend(_load_boss_point_items(root, project, report))
    items.extend(_ocr_label_point_items(root, project, named_points, report))
    report.append(
        {
            "source_kind": "mcp_candidates",
            "status": "loaded" if candidates else "missing_or_empty",
            "source_path": ref,
            "loaded_count": len(candidates),
        }
    )
    return items, report


def _major_point_field_answer(
    items: list[dict[str, Any]],
    results: list[dict[str, Any]],
    *,
    query: str,
    point_kinds: set[str],
    boss_point_count: int | None,
    source_report: list[dict[str, Any]],
) -> tuple[str, str | None]:
    if _major_point_boss_query(query):
        if boss_point_count is None:
            return (
                "缺少 boss_points workspace artifact，不能確認目前 boss point 數量。"
                "這是 evidence gap，不可當成 0 個。",
                _major_point_source_ref(source_report, "boss_points"),
            )
        boss_points = [
            item for item in items if item.get("evidence_type") == "boss_point"
        ]
        boss_points.sort(
            key=lambda item: (
                int(item.get("rank") or 10_000),
                str(item.get("label") or ""),
            )
        )
        details = "; ".join(
            f"{item.get('label')}"
            f"（{item.get('display_mileage_label') or 'mileage unavailable'}）"
            for item in boss_points
        )
        return (
            f"Boss Point 候選數量：目前有 {boss_point_count} 個 boss point："
            f"{details or 'names unavailable'}。",
            _major_point_source_ref(source_report, "boss_points"),
        )
    if re.search(r"mcp candidates?", query, re.IGNORECASE) and re.search(
        r"名稱|named|evidence|證據|多少|幾個", query, re.IGNORECASE
    ):
        mcp_items = [
            item for item in items if item.get("evidence_type") == "major_point"
        ]
        details = "; ".join(
            f"{item.get('candidate_id')}/{item.get('label')} -> "
            f"{','.join(str(value) for value in item.get('linked_named_points') or []) or 'none'}"
            for item in mcp_items
        )
        return (
            f"MCP candidates 共 {len(mcp_items)} 個；名稱證據連結：{details}。",
            _major_point_source_ref(source_report, "mcp_candidates"),
        )
    support_rows = [
        item
        for item in items
        if item.get("evidence_type") == "major_point_cp_support"
    ]
    if re.search(r"沒有.*mcp support|no.*mcp support", query, re.IGNORECASE):
        unsupported = [
            item for item in support_rows if item.get("support_status") != "supported"
        ]
        details = "; ".join(
            _unsupported_mcp_brief(item) for item in unsupported
        )
        return (
            "此 reconciliation 是 MCP 對 CP 的支援檢查，不是逐一證明每個 CP "
            "都必須有 MCP。缺少鄰近 CP support 的 MCP："
            f"{details or 'none'}。",
            _major_point_source_ref(
                source_report,
                "mcp_cp_support_reconciliation",
            ),
        )
    if re.search(r"reconciliation|重疊|缺漏|衝突", query, re.IGNORECASE):
        supported = [
            item for item in support_rows if item.get("support_status") == "supported"
        ]
        unsupported = [
            item for item in support_rows if item.get("support_status") != "supported"
        ]
        overlap_count = sum(
            int(item.get("suppressed_point_count") or 0) for item in support_rows
        )
        unsupported_text = "; ".join(
            _unsupported_mcp_brief(item) for item in unsupported
        )
        return (
            f"CP/MCP reconciliation：supported={len(supported)}；"
            f"unsupported={len(unsupported)}"
            f"（{unsupported_text or 'none'}）；spacing overlaps={overlap_count}；"
            "explicit conflicts=0。",
            _major_point_source_ref(
                source_report,
                "mcp_cp_support_reconciliation",
            ),
        )
    water_query = _major_point_water_query(query, point_kinds=point_kinds)
    if not results:
        if water_query:
            return (
                "候選補水/水源點：目前工作區沒有可匹配的 water_source MCP；"
                "不得把未知水源當作可用補給。",
                None,
            )
        return "候選重要點：目前工作區沒有可匹配的 MCP / named point。", None

    scoped_results = (
        [
            item
            for item in results
            if "water_source"
            in {str(kind).lower() for kind in item.get("point_classes", [])}
        ]
        if water_query
        else results
    )
    scoped_results = scoped_results or results
    labels = [_major_point_brief(item) for item in scoped_results[:3]]
    prefix = "候選補水/水源點" if water_query else "候選重要點"
    source_ref = next(
        (str(item.get("source_path")) for item in scoped_results if item.get("source_path")),
        None,
    )
    return (
        f"{prefix}：" + "；".join(labels)
        + "。此為 Major Point 候選證據，不是現場取水、停留或 runtime safety truth；"
        "取水前仍需確認水況、處理方式、停留 buffer 與路線風險。",
        source_ref,
    )


def _major_point_source_ref(
    source_report: list[dict[str, Any]],
    source_kind: str,
) -> str | None:
    return next(
        (
            str(item.get("source_path"))
            for item in source_report
            if item.get("source_kind") == source_kind and item.get("source_path")
        ),
        None,
    )


def _unsupported_mcp_brief(item: dict[str, Any]) -> str:
    suggestion = item.get("suggested_cp_insertion")
    suggestion = suggestion if isinstance(suggestion, dict) else {}
    location = (
        f"{suggestion.get('lat')},{suggestion.get('lon')}"
        if suggestion.get("lat") is not None and suggestion.get("lon") is not None
        else "location unavailable"
    )
    return (
        f"{item.get('candidate_id')}/{item.get('label')} -> suggested CP {location}"
    )


def _major_point_water_query(query: str, *, point_kinds: set[str]) -> bool:
    if "water_source" in point_kinds:
        return True
    normalized = query.lower().replace(" ", "")
    return any(
        token in normalized
        for token in (
            "補水",
            "取水",
            "裝水",
            "水源",
            "飲水點",
            "waterpoint",
            "watersource",
            "refillwater",
        )
    )


def _major_point_boss_query(query: str) -> bool:
    normalized = query.casefold().replace(" ", "")
    return "bosspoint" in normalized or "boss點" in normalized


def _load_boss_point_items(
    root: Path,
    project: dict[str, Any],
    report: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ref = str(project.get("boss_points_ref") or "outputs/boss_points.json")
    source_path = _project_path(root, ref)
    payload = _load_json_object(source_path)
    points = payload.get("boss_points") if isinstance(payload, dict) else []
    if not isinstance(points, list):
        points = []
    report.append(
        {
            "source_kind": "boss_points",
            "status": (
                "loaded"
                if source_path.exists()
                and isinstance(payload.get("boss_point_count"), int)
                else "missing_or_empty"
            ),
            "source_path": ref,
            "loaded_count": len(points),
            "declared_count": payload.get("boss_point_count"),
        }
    )
    items: list[dict[str, Any]] = []
    for point in points:
        if not isinstance(point, dict):
            continue
        boss_selection = (
            point.get("boss_selection")
            if isinstance(point.get("boss_selection"), dict)
            else {}
        )
        challenge_fit = (
            point.get("challenge_fit")
            if isinstance(point.get("challenge_fit"), dict)
            else {}
        )
        display_mileage = (
            point.get("display_mileage")
            if isinstance(point.get("display_mileage"), dict)
            else {}
        )
        boss_id = str(point.get("boss_point_id") or "")
        label = str(point.get("label") or point.get("map_label") or boss_id)
        raw_classes = point.get("mcp_classes")
        classes = [
            "boss_point",
            *(
                [str(item) for item in raw_classes]
                if isinstance(raw_classes, list)
                else []
            ),
        ]
        score = _optional_float(
            boss_selection.get("score") or challenge_fit.get("score")
        )
        items.append(
            {
                "evidence_type": "boss_point",
                "candidate_id": boss_id,
                "label": label,
                "point_classes": classes,
                "lat": _optional_float(point.get("lat")),
                "lon": _optional_float(point.get("lon")),
                "distance_m": _optional_float(display_mileage.get("route_distance_m")),
                "distance_km": _km(display_mileage.get("route_distance_m")),
                "display_mileage_label": display_mileage.get("label"),
                "rank": point.get("rank"),
                "score": score,
                "candidate_only": bool(point.get("candidate_only", True)),
                "runtime_safety_truth": False,
                "source_path": ref,
                "search_text": " ".join(
                    str(part)
                    for part in (
                        "boss point",
                        "boss點",
                        boss_id,
                        label,
                        point.get("map_label"),
                        display_mileage.get("label"),
                        " ".join(str(item) for item in classes),
                    )
                    if part
                ),
            }
        )
    return items


def _major_point_brief(item: dict[str, Any]) -> str:
    label = str(item.get("label") or item.get("candidate_id") or "unknown")
    nearest_cp = item.get("nearest_cp_candidate_id")
    distance = _optional_float(item.get("distance_m"))
    details = []
    if nearest_cp:
        details.append(f"nearest CP {nearest_cp}")
    if distance is not None:
        details.append(f"route distance {distance:g} m")
    return label + (f"（{', '.join(details)}）" if details else "")


def _point_class_alias_text(classes: Any) -> str:
    if not isinstance(classes, list):
        return ""
    aliases: list[str] = []
    for raw in classes:
        value = str(raw).lower()
        if value == "water_source":
            aliases.extend(
                [
                    "水源",
                    "補水",
                    "取水",
                    "裝水",
                    "飲水點",
                    "water point",
                    "water source",
                    "refill water",
                ]
            )
        elif value == "camp_hut_structure":
            aliases.extend(["營地", "山屋", "保線所", "可停留建物"])
        elif value == "fork_junction":
            aliases.extend(["岔路", "叉路", "路口"])
    return " ".join(aliases)


def _load_named_points(
    root: Path,
    project: dict[str, Any],
    report: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    ref = str(project.get("mcp_named_point_evidence_ref") or "outputs/mcp/named_point_evidence.json")
    payload = _load_json_object(_project_path(root, ref))
    points = payload.get("named_points") if isinstance(payload, dict) else []
    if not isinstance(points, list):
        points = []
    report.append(
        {
            "source_kind": "named_point_evidence",
            "status": "loaded" if points else "missing_or_empty",
            "source_path": ref,
            "loaded_count": len(points),
        }
    )
    return {
        str(point.get("named_point_id")): point
        for point in points
        if isinstance(point, dict) and point.get("named_point_id")
    }


def _load_support_rows(
    root: Path,
    project: dict[str, Any],
    report: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ref = str(project.get("mcp_cp_support_reconciliation_ref") or "outputs/mcp/mcp_cp_support_reconciliation.json")
    payload = _load_json_object(_project_path(root, ref))
    rows = payload.get("rows") if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        rows = []
    report.append(
        {
            "source_kind": "mcp_cp_support_reconciliation",
            "status": "loaded" if rows else "missing_or_empty",
            "source_path": ref,
            "loaded_count": len(rows),
        }
    )
    return [row for row in rows if isinstance(row, dict)]


def _ocr_label_point_items(
    root: Path,
    project: dict[str, Any],
    named_points: dict[str, dict[str, Any]],
    report: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ref = str(project.get("mcp_ocr_labels_ref") or "outputs/mcp/mcp_ocr_labels.json")
    payload = _load_json_object(_project_path(root, ref))
    labels = payload.get("labels") if isinstance(payload, dict) else []
    if not isinstance(labels, list):
        labels = []
    items = []
    for label in labels:
        if not isinstance(label, dict):
            continue
        named_point = named_points.get(str(label.get("named_point_id") or ""), {})
        route_position = named_point.get("route_position") if isinstance(named_point.get("route_position"), dict) else {}
        text = str(label.get("label_text") or label.get("ocr_label_id") or "")
        items.append(
            {
                "evidence_type": "ocr_label",
                "candidate_id": label.get("ocr_label_id"),
                "label": text,
                "label_text": text,
                "point_classes": ["ocr_label"],
                "lat": _optional_float(route_position.get("lat")),
                "lon": _optional_float(route_position.get("lon")),
                "distance_m": _optional_float(route_position.get("distance_m")),
                "distance_km": _km(route_position.get("distance_m")),
                "named_point_id": label.get("named_point_id"),
                "source_ref": label.get("source_ref"),
                "confidence": _optional_float(label.get("confidence")),
                "review_required": bool(label.get("review_required", True)),
                "candidate_only": bool(label.get("candidate_only", True)),
                "runtime_safety_truth": False,
                "source_path": ref,
                "search_text": " ".join(
                    str(part)
                    for part in (
                        text,
                        label.get("ocr_label_id"),
                        label.get("source_ref"),
                        label.get("named_point_id"),
                        named_point.get("canonical_name") if isinstance(named_point, dict) else None,
                    )
                    if part
                ),
            }
        )
    report.append(
        {
            "source_kind": "mcp_ocr_labels",
            "status": "loaded" if labels else "missing_or_empty",
            "source_path": ref,
            "loaded_count": len(labels),
        }
    )
    return items


def _load_project_list(
    root: Path,
    project: dict[str, Any],
    ref_key: str,
) -> tuple[list[Any], str]:
    ref = str(project.get(ref_key) or "")
    payload = _load_json_object(_project_path(root, ref))
    if isinstance(payload, list):
        return payload, ref
    if isinstance(payload, dict):
        for key in ("candidates", "items", "segments", "checkpoints", "rows"):
            value = payload.get(key)
            if isinstance(value, list):
                return value, ref
    return [], ref


def _compact_route_summary(route: dict[str, Any]) -> dict[str, Any]:
    return {
        "route_name": route.get("route_name"),
        "artifact_id": route.get("artifact_id"),
        "distance_m": _optional_float(route.get("distance_m")),
        "distance_km": _km(route.get("distance_m")),
        "elevation_min_m": _optional_float(route.get("elevation_min_m")),
        "elevation_max_m": _optional_float(route.get("elevation_max_m")),
        "point_count": route.get("point_count"),
        "started_at": route.get("started_at"),
        "ended_at": route.get("ended_at"),
        "bbox_wgs84": route.get("bbox_wgs84"),
    }


def _related_count_keys(project: dict[str, Any], ref_key: str) -> dict[str, Any]:
    prefix = ref_key.removesuffix("_ref")
    related: dict[str, Any] = {}
    for key, value in project.items():
        if key.endswith("_count") and (key.startswith(prefix) or prefix.startswith(key.removesuffix("_count"))):
            related[key] = value
    if not related:
        compact = prefix.replace("_candidates", "").replace("_candidate", "")
        for key, value in project.items():
            if key.endswith("_count") and compact and compact in key:
                related[key] = value
    return related


def _domain_for_ref(key: str, value: str) -> str:
    text = f"{key} {value}".lower()
    for domain, hints in _DOMAIN_HINTS.items():
        if any(hint.lower() in text for hint in hints):
            return domain
    if "review" in text:
        return "review"
    if "runtime" in text or "debug" in text:
        return "runtime"
    return "workspace"


def _normalize_domains(values: list[str] | None) -> set[str]:
    if not values:
        return set()
    return {str(value).strip().lower() for value in values if str(value).strip()}


def _domains_from_query(query: str) -> set[str]:
    lowered = query.lower()
    if any(term in lowered for term in ("preparation", "metadata", "已完成", "仍缺")):
        return set()
    domains = set()
    for domain, hints in _DOMAIN_HINTS.items():
        if any(hint.lower() in lowered for hint in hints):
            domains.add(domain)
    return domains


def _looks_candidate_key(key: str, value: str) -> bool:
    lowered = f"{key} {value}".lower()
    return any(fragment in lowered for fragment in ("candidate", "proposal", "draft", "review_queue"))


def _catalog_match_score(item: dict[str, Any], terms: set[str], raw_query: str) -> float:
    score = _text_match_score(str(item.get("search_text") or ""), terms, raw_query)
    lowered_query = raw_query.lower()
    if item.get("evidence_type") == "workspace_preparation_metadata" and any(
        term in lowered_query for term in ("preparation", "metadata", "已完成", "仍缺")
    ):
        score += 12.0
    if item["exists"]:
        score += 0.25
    return score


def _item_references_cp(item: dict[str, Any], cp: str) -> bool:
    normalized = _normalize_cp_id(cp)
    values = {
        _normalize_cp_id(str(item.get("candidate_id") or "")),
        _normalize_cp_id(str(item.get("from_candidate_id") or "")),
        _normalize_cp_id(str(item.get("to_candidate_id") or "")),
        _normalize_cp_id(str(item.get("nearest_cp_candidate_id") or "")),
    }
    linked = item.get("linked_cp_candidates")
    if isinstance(linked, list):
        values.update(_normalize_cp_id(str(value)) for value in linked)
    return normalized in values


def _parse_cp(query: str) -> str | None:
    match = re.search(r"\bcp[ ._-]*(start|\d{1,3})\b", query, flags=re.IGNORECASE)
    if not match:
        match = re.search(r"CP\s*(start|\d{1,3})", query, flags=re.IGNORECASE)
    if not match:
        return None
    return _normalize_cp_id(f"cp.{match.group(1)}")


def _parse_segment(query: str) -> str | None:
    match = re.search(r"\bseg(?:ment)?[ ._-]*(\d{1,3})\b", query, flags=re.IGNORECASE)
    if not match:
        return None
    return f"seg.{int(match.group(1)):03d}"


def _route_collection_kind(query: str) -> str | None:
    lowered = query.casefold()
    if re.search(r"\b(?:route[\s_-]+)?segments?\b|路段|區段", lowered):
        return "segments"
    return None


def _normalize_cp_id(value: str) -> str:
    lowered = value.strip().lower().replace("_", ".").replace("-", ".").replace(" ", "")
    if lowered in {"start", "cpstart", "cp.start"}:
        return "cp.start"
    match = re.search(r"cp\.?(\d{1,3})", lowered)
    if match:
        return f"cp.{int(match.group(1)):03d}"
    return lowered


def _query_terms(query: str) -> set[str]:
    lowered = query.lower()
    raw_terms = re.findall(r"[a-z0-9_./-]+|[\u4e00-\u9fff]{2,}", lowered)
    terms = set()
    for term in raw_terms:
        stripped = term.strip(" ?!,:;，。！？：；()[]{}")
        if not stripped or stripped in _GENERIC_TERMS:
            continue
        if stripped.startswith("cp") or stripped.startswith("seg"):
            continue
        terms.add(stripped)
        if re.search(r"[\u4e00-\u9fff]", stripped) and len(stripped) > 2:
            for size in range(2, min(4, len(stripped)) + 1):
                for start in range(0, len(stripped) - size + 1):
                    ngram = stripped[start : start + size]
                    if ngram not in _GENERIC_TERMS:
                        terms.add(ngram)
    return terms


def _text_match_score(text: str, terms: set[str], raw_query: str) -> float:
    lowered = text.lower()
    score = 0.0
    if raw_query and raw_query.lower().strip() in lowered:
        score += 8.0
    for term in terms:
        if term in lowered:
            score += 4.0 if re.search(r"[\u4e00-\u9fff]", term) else 2.0
    return score


def _major_point_match_score(
    item: dict[str, Any],
    terms: set[str],
    raw_query: str,
) -> float:
    score = _text_match_score(item.get("search_text", ""), terms, raw_query)
    label = str(item.get("label") or "").lower()
    label_text = str(item.get("label_text") or "").lower()
    aliases = [
        str(alias).lower()
        for alias in item.get("aliases", [])
        if str(alias).strip()
    ]
    raw = str(raw_query or "").lower().strip()
    if raw and label and label in raw:
        score += 30.0
    for term in terms:
        if len(term) < 2:
            continue
        if label and term in label:
            score += 20.0
        elif label_text and term in label_text:
            score += 18.0
        elif any(term in alias for alias in aliases):
            score += 6.0
    return score


def _project_path(root: Path, ref: str) -> Path:
    path = Path(ref)
    if path.is_absolute():
        return path
    return root / path


def _load_json_object(path: Path) -> Any:
    if not path or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _optional_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _optional_int(value: Any) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _km(value: Any) -> float | None:
    number = _optional_float(value)
    if number is None:
        return None
    return round(number / 1000.0, 3)


def _bounded_limit(value: int | None) -> int:
    if not isinstance(value, int):
        return DEFAULT_WORKSPACE_SEARCH_LIMIT
    return max(1, min(value, MAX_WORKSPACE_SEARCH_LIMIT))


def _closed_boundary() -> dict[str, bool]:
    return {
        "read_only": True,
        "offline_only": True,
        "local_evidence_only": True,
        "runtime_safety_truth": False,
        "live_safety_api_calls_allowed": False,
        "phase1_safety_mutation_allowed": False,
        "remote_outbound_send_allowed": False,
        "hardware_control_allowed": False,
        "raw_payloads_embedded": False,
    }
