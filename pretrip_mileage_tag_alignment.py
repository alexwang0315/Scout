from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pretrip_boss_point_synthesis import (
    DEFAULT_CHECKPOINTS_REF,
    DEFAULT_MCP_CANDIDATES_REF,
    DEFAULT_RISK_RIBBON_REF,
    DEFAULT_ROUTE_MILEAGE_K_ANCHORS_REF,
    DEFAULT_ROUTE_NOTES_REF,
    DEFAULT_SEGMENT_DISPLAY_GEOMETRY_REF,
    DEFAULT_SEGMENTS_REF,
    _checkpoint_route_distances,
    _display_mileage_for_route_distance,
    _feature_coordinate_points,
    _float_or_none,
    _format_mileage_span_label,
    _gpx_segments_projected_to_route,
    _load_json_list,
    _load_json_object,
    _nearest_route_projection,
    _payload_list,
    _project_path,
    _projection_alignment_status,
    _round,
    _route_coordinate_at_distance,
    _route_distance_for_display_mileage,
    _route_display_geometry_from_risk_ribbon,
    _route_display_geometry_from_segment_display_geometry,
    _route_mileage_alignment_from_anchors,
    _segments_with_route_distance,
    _write_json,
)


MILEAGE_TAG_ALIGNMENT_ARTIFACT_KIND = "pretrip_workspace_mileage_tag_alignment"
MILEAGE_TAG_ALIGNMENT_SCHEMA_VERSION = "workspace_mileage_tag_alignment.v1"
MILEAGE_TAG_ALIGNMENT_REF = "outputs/mileage_tag_alignment.json"
MILEAGE_TAG_ALIGNMENT_GEOJSON_REF = "outputs/mileage_tag_alignment.geojson"

DEFAULT_ROUTE_CONTEXT_POINTS_REF = "candidates/route_context_points.json"
DEFAULT_GIS_CHECKPOINT_CANDIDATES_REF = (
    "outputs/layers/candidates/gis_checkpoint_candidates.json"
)
DEFAULT_TERRAIN_RISK_CANDIDATES_REF = (
    "outputs/layers/candidates/terrain_risk_candidates.json"
)
DEFAULT_RISK_SCORE_POINTS_REF = "outputs/risk/risk_score_points.geojson"
DEFAULT_CALIBRATED_RISK_HEATMAP_REF = "outputs/risk/calibrated_risk_heatmap.geojson"
DEFAULT_TERRAIN_ROUTE_SAMPLES_REF = (
    "outputs/layers/normalized/terrain_route_samples.geojson"
)
DEFAULT_ROUTE_PRESSURE_PROFILE_REF = "outputs/route_pressure_profile.json"
DEFAULT_BOSS_POINTS_REF = "outputs/boss_points.json"
REPRESENTATIVE_ROUTE_NOTE_LIMIT = 800
MILEAGE_LABEL_RE = re.compile(r"(?<![A-Za-z0-9])\d+(?:\.\d+)?\s*[Kk](?![A-Za-z])")
REPRESENTATIVE_ROUTE_NOTE_CATEGORIES = {
    "hazard_hint",
    "route_condition_hint",
}


def align_pretrip_workspace_mileage_tags(
    project_root: Path | str,
    *,
    generated_at: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    root = Path(project_root)
    project_path = root / "project.json"
    project = _load_json_object(project_path)
    project_id = str(project.get("project_id") or project.get("id") or root.name)
    aligned_at = generated_at or _utc_now()

    checkpoints_path = _project_path(
        root, project, "checkpoint_candidates_ref", DEFAULT_CHECKPOINTS_REF
    )
    segments_path = _project_path(root, project, "segment_candidates_ref", DEFAULT_SEGMENTS_REF)
    route_notes_path = _project_path(
        root, project, "route_note_candidates_ref", DEFAULT_ROUTE_NOTES_REF
    )
    mcp_path = _project_path(root, project, "mcp_candidates_ref", DEFAULT_MCP_CANDIDATES_REF)
    route_context_path = _project_path(
        root,
        project,
        "route_context_points_ref",
        DEFAULT_ROUTE_CONTEXT_POINTS_REF,
    )
    route_mileage_anchors_path = _project_path(
        root,
        project,
        "route_mileage_k_anchors_ref",
        DEFAULT_ROUTE_MILEAGE_K_ANCHORS_REF,
    )
    risk_ribbon_path = _project_path(root, project, "risk_ribbon_ref", DEFAULT_RISK_RIBBON_REF)
    segment_display_geometry_path = _project_path(
        root,
        project,
        "segment_display_geometry_ref",
        DEFAULT_SEGMENT_DISPLAY_GEOMETRY_REF,
    )

    checkpoints = _load_json_list(checkpoints_path)
    segments = _load_json_list(segments_path)
    route_notes = _payload_list(_load_json_object(route_notes_path), "candidates")
    mcp_payload = _load_json_object(mcp_path)
    route_context_payload = _load_json_object(route_context_path)
    route_mileage_anchors = _load_json_object(route_mileage_anchors_path)
    risk_ribbon = _load_json_object(risk_ribbon_path)
    segment_display_geometry = _load_json_object(segment_display_geometry_path)

    cp_distances = _checkpoint_route_distances(checkpoints, segments)
    segments_with_distance = _segments_with_route_distance(segments, cp_distances)
    risk_features = _payload_list(risk_ribbon, "features")
    gpx_route_geometry = _route_display_geometry_from_segment_display_geometry(
        project_id=project_id,
        segment_display_geometry=segment_display_geometry,
        segments=segments_with_distance,
        source_path=_source_ref(root, segment_display_geometry_path),
    )
    route_display_geometry = _route_display_geometry_from_risk_ribbon(
        project_id=project_id,
        risk_features=risk_features,
        source_path=_source_ref(root, risk_ribbon_path),
    )
    if not route_display_geometry.get("coordinates"):
        route_display_geometry = gpx_route_geometry

    route_mileage_alignment = _route_mileage_alignment_from_anchors(
        route_mileage_anchors,
        route_display_geometry=route_display_geometry,
        source_ref=_source_ref(root, route_mileage_anchors_path),
    )

    source_refs = _source_refs(root, project)
    checkpoint_tags = _point_tags(
        project_id=project_id,
        source_kind="checkpoint",
        source_ref=_source_ref(root, checkpoints_path),
        items=checkpoints,
        id_keys=("candidate_id",),
        route_display_geometry=route_display_geometry,
        route_mileage_alignment=route_mileage_alignment,
        source_route_distances=cp_distances,
    )
    segment_tags = _segment_tags(
        project_id=project_id,
        source_ref=_source_ref(root, segments_path),
        segments=_gpx_segments_projected_to_route(
            segments_with_distance,
            gpx_route_geometry,
            route_display_geometry,
        ),
        route_display_geometry=route_display_geometry,
        route_mileage_alignment=route_mileage_alignment,
    )
    mcp_tags = _point_tags(
        project_id=project_id,
        source_kind="mcp_candidate",
        source_ref=_source_ref(root, mcp_path),
        items=_payload_list(mcp_payload, "mcp_candidates"),
        id_keys=("mcp_id", "candidate_id"),
        route_display_geometry=route_display_geometry,
        route_mileage_alignment=route_mileage_alignment,
    )
    route_context_tags = _point_tags(
        project_id=project_id,
        source_kind="route_context_point",
        source_ref=_source_ref(root, route_context_path),
        items=_payload_list(route_context_payload, "points"),
        id_keys=("candidate_id", "source_id"),
        route_display_geometry=route_display_geometry,
        route_mileage_alignment=route_mileage_alignment,
    )
    representative_route_notes = _representative_route_notes(route_notes)
    route_note_tags = _point_tags(
        project_id=project_id,
        source_kind="route_note_candidate",
        source_ref=_source_ref(root, route_notes_path),
        items=representative_route_notes,
        id_keys=("candidate_id", "source_id"),
        route_display_geometry=route_display_geometry,
        route_mileage_alignment=route_mileage_alignment,
        compact_text=True,
    )
    known_route_distances = _route_distance_lookup(
        checkpoint_tags,
        segment_tags,
        mcp_tags,
        route_context_tags,
        route_note_tags,
    )

    optional_tags = []
    optional_tags.extend(
        _geojson_feature_tags(
            project_id=project_id,
            source_kind="risk_ribbon_segment",
            source_ref=source_refs.get("risk_ribbon", DEFAULT_RISK_RIBBON_REF),
            payload=risk_ribbon,
            route_display_geometry=route_display_geometry,
            route_mileage_alignment=route_mileage_alignment,
            id_keys=("segment_id", "candidate_id"),
            feature_limit=None,
        )
    )
    optional_tags.extend(
        _optional_geojson_tags(
            root=root,
            project=project,
            project_id=project_id,
            ref_key="risk_score_points_ref",
            default_ref=DEFAULT_RISK_SCORE_POINTS_REF,
            source_kind="risk_score_point",
            route_display_geometry=route_display_geometry,
            route_mileage_alignment=route_mileage_alignment,
            id_keys=("sample_id", "candidate_id", "point_id"),
        )
    )
    optional_tags.extend(
        _optional_geojson_tags(
            root=root,
            project=project,
            project_id=project_id,
            ref_key="calibrated_risk_heatmap_ref",
            default_ref=DEFAULT_CALIBRATED_RISK_HEATMAP_REF,
            source_kind="calibrated_risk_heatmap_segment",
            route_display_geometry=route_display_geometry,
            route_mileage_alignment=route_mileage_alignment,
            id_keys=("segment_id", "candidate_id"),
        )
    )
    optional_tags.extend(
        _optional_geojson_tags(
            root=root,
            project=project,
            project_id=project_id,
            ref_key="terrain_route_samples_ref",
            default_ref=DEFAULT_TERRAIN_ROUTE_SAMPLES_REF,
            source_kind="terrain_route_sample",
            route_display_geometry=route_display_geometry,
            route_mileage_alignment=route_mileage_alignment,
            id_keys=("sample_id", "candidate_id"),
        )
    )
    optional_tags.extend(
        _optional_point_payload_tags(
            root=root,
            project=project,
            project_id=project_id,
            ref_key="gis_checkpoint_candidates_ref",
            default_ref=DEFAULT_GIS_CHECKPOINT_CANDIDATES_REF,
            source_kind="gis_checkpoint_candidate",
            payload_key="candidates",
            id_keys=("candidate_id",),
            route_display_geometry=route_display_geometry,
            route_mileage_alignment=route_mileage_alignment,
            source_route_distances=known_route_distances,
            project_coordinates=False,
        )
    )
    optional_tags.extend(
        _optional_point_payload_tags(
            root=root,
            project=project,
            project_id=project_id,
            ref_key="terrain_risk_candidates_ref",
            default_ref=DEFAULT_TERRAIN_RISK_CANDIDATES_REF,
            source_kind="terrain_risk_candidate",
            payload_key="candidates",
            id_keys=("candidate_id",),
            route_display_geometry=route_display_geometry,
            route_mileage_alignment=route_mileage_alignment,
            source_route_distances=known_route_distances,
            project_coordinates=True,
        )
    )
    optional_tags.extend(
        _optional_route_pressure_tags(
            root=root,
            project=project,
            project_id=project_id,
            route_display_geometry=route_display_geometry,
            route_mileage_alignment=route_mileage_alignment,
        )
    )
    optional_tags.extend(
        _optional_boss_point_tags(
            root=root,
            project=project,
            project_id=project_id,
            route_display_geometry=route_display_geometry,
            route_mileage_alignment=route_mileage_alignment,
        )
    )

    mileage_tags = [
        *checkpoint_tags,
        *segment_tags,
        *mcp_tags,
        *route_context_tags,
        *route_note_tags,
        *optional_tags,
    ]
    mileage_tags = [
        tag
        for tag in mileage_tags
        if tag.get("display_mileage", {}).get("label")
        or tag.get("display_mileage_span", {}).get("label")
    ]

    counts = _counts(mileage_tags, route_mileage_alignment)
    payload = {
        "artifact_kind": MILEAGE_TAG_ALIGNMENT_ARTIFACT_KIND,
        "schema_version": MILEAGE_TAG_ALIGNMENT_SCHEMA_VERSION,
        "project_id": project_id,
        "generated_at": aligned_at,
        "status": "completed" if counts["aligned_tag_count"] else "missing_alignment",
        "mileage_tag_alignment_ref": MILEAGE_TAG_ALIGNMENT_REF,
        "mileage_tag_alignment_geojson_ref": MILEAGE_TAG_ALIGNMENT_GEOJSON_REF,
        "counts": counts,
        "raw_source_summary": {
            "route_note_candidate_count": len(route_notes),
            "route_note_mileage_tag_candidate_count": len(representative_route_notes),
            "route_note_not_expanded_count": max(
                0,
                len(route_notes) - len(representative_route_notes),
            ),
        },
        "route_mileage_alignment": route_mileage_alignment,
        "source_refs": {
            "project": "project.json",
            "route_mileage_k_anchors": _source_ref(root, route_mileage_anchors_path),
            "route_centerline": _source_ref(root, risk_ribbon_path)
            if route_display_geometry.get("evidence_type")
            == "pretrip_overpass_risk_ribbon_centerline"
            else _source_ref(root, segment_display_geometry_path),
            **source_refs,
        },
        "policy": {
            "route_axis": "overpass_risk_ribbon_distance_when_available",
            "fallback_route_axis": "segment_display_geometry_distance",
            "display_axis": "trail_mileage_k_anchor",
            "standalone_k_anchor_allowed": False,
            "road_mileage_stones_used_for_interpolation": False,
            "source_files_mutated": False,
            "raw_route_note_text_embedded": False,
            "raw_route_notes_not_expanded_reason": (
                "Only K anchors, hazard/condition/camp-water notes, and "
                "potential LN signals are projected into mileage tags."
            ),
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
        "mileage_tags": mileage_tags,
        "boundary": _boundary(),
    }

    geojson = _mileage_tags_geojson(payload, route_display_geometry)
    if not dry_run:
        _write_json(root / MILEAGE_TAG_ALIGNMENT_REF, payload)
        _write_json(root / MILEAGE_TAG_ALIGNMENT_GEOJSON_REF, geojson)
        _update_project_refs(root / "project.json", project, payload)
    return payload


def _point_tags(
    *,
    project_id: str,
    source_kind: str,
    source_ref: str,
    items: list[dict[str, Any]],
    id_keys: tuple[str, ...],
    route_display_geometry: dict[str, Any],
    route_mileage_alignment: dict[str, Any],
    source_route_distances: dict[str, float] | None = None,
    compact_text: bool = False,
    project_coordinates: bool = True,
) -> list[dict[str, Any]]:
    tags = []
    source_route_distances = source_route_distances or {}
    for item in items:
        source_id = _source_id(item, id_keys)
        if not source_id:
            continue
        route_distance = _float_or_none(item.get("route_distance_m"))
        if route_distance is None:
            route_distance = _float_or_none(item.get("distance_m"))
        if route_distance is None:
            route_distance = source_route_distances.get(source_id)
        route_distance_from_mileage_label = False
        if route_distance is None:
            mileage_m = _mileage_m_from_item(item)
            mileage_route_distance = (
                _route_distance_for_display_mileage(route_mileage_alignment, mileage_m)
                if mileage_m is not None
                else {}
            )
            route_distance = _float_or_none(mileage_route_distance.get("route_distance_m"))
            route_distance_from_mileage_label = route_distance is not None
        projection = (
            _nearest_route_projection(route_display_geometry, item)
            if project_coordinates and not route_distance_from_mileage_label
            else None
        )
        projection_distance = None
        coordinate = None
        if projection is not None:
            route_distance = _float_or_none(projection.get("route_distance_m"))
            projection_distance = _float_or_none(projection.get("distance_to_route_m"))
            coordinate = {"lat": projection.get("lat"), "lon": projection.get("lon")}
        if route_distance is None:
            continue
        display = _display(route_mileage_alignment, route_distance)
        tags.append(
            _base_tag(
                project_id=project_id,
                source_kind=source_kind,
                source_ref=source_ref,
                source_id=source_id,
                item=item,
                route_distance_m=route_distance,
                route_display_geometry=route_display_geometry,
                route_mileage_alignment=route_mileage_alignment,
                display_mileage=display,
                coordinate=coordinate,
                source_coordinate=_source_coordinate(item),
                route_projection_distance_m=projection_distance,
                route_projection_status=(
                    "mileage_label_anchor_axis"
                    if route_distance_from_mileage_label
                    else _projection_alignment_status(projection_distance)
                ),
                compact_text=compact_text,
            )
        )
    return tags


def _representative_route_notes(
    route_notes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    selected = []
    for note in route_notes:
        text = " ".join(
            str(note.get(key) or "")
            for key in ("name", "normalized_note", "desc", "cmt", "model_output_summary")
        )
        if (
            MILEAGE_LABEL_RE.search(text)
            or bool(note.get("potential_ln_signal"))
            or str(note.get("note_category") or "") in REPRESENTATIVE_ROUTE_NOTE_CATEGORIES
        ):
            selected.append(note)
    selected.sort(
        key=lambda item: (
            0 if MILEAGE_LABEL_RE.search(str(item.get("name") or "")) else 1,
            str(item.get("candidate_id") or ""),
        )
    )
    return selected[:REPRESENTATIVE_ROUTE_NOTE_LIMIT]


def _segment_tags(
    *,
    project_id: str,
    source_ref: str,
    segments: list[dict[str, Any]],
    route_display_geometry: dict[str, Any],
    route_mileage_alignment: dict[str, Any],
) -> list[dict[str, Any]]:
    tags = []
    for segment in segments:
        source_id = str(segment.get("candidate_id") or segment.get("segment_candidate_id") or "")
        if not source_id:
            continue
        start = _float_or_none(segment.get("start_distance_m"))
        end = _float_or_none(segment.get("end_distance_m"))
        mid = _float_or_none(segment.get("route_distance_m"))
        if mid is None and start is not None and end is not None:
            mid = (start + end) / 2.0
        if mid is None:
            continue
        display = _display(route_mileage_alignment, mid)
        span = _display_span(route_mileage_alignment, start, end)
        coordinate = _route_coordinate_at_distance(route_display_geometry, mid)
        tags.append(
            _base_tag(
                project_id=project_id,
                source_kind="segment",
                source_ref=source_ref,
                source_id=source_id,
                item=segment,
                route_distance_m=mid,
                route_display_geometry=route_display_geometry,
                route_mileage_alignment=route_mileage_alignment,
                display_mileage=display,
                display_mileage_span=span,
                coordinate=coordinate,
                source_coordinate=None,
                route_projection_distance_m=_float_or_none(
                    segment.get("route_projection_distance_m")
                ),
                route_projection_status=str(
                    segment.get("route_projection_status")
                    or _projection_alignment_status(
                        _float_or_none(segment.get("route_projection_distance_m"))
                    )
                ),
                compact_text=False,
            )
        )
    return tags


def _geojson_feature_tags(
    *,
    project_id: str,
    source_kind: str,
    source_ref: str,
    payload: dict[str, Any],
    route_display_geometry: dict[str, Any],
    route_mileage_alignment: dict[str, Any],
    id_keys: tuple[str, ...],
    feature_limit: int | None,
) -> list[dict[str, Any]]:
    features = _payload_list(payload, "features")
    if feature_limit is not None:
        features = features[:feature_limit]
    tags = []
    for index, feature in enumerate(features):
        properties = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        source_id = _source_id(properties, id_keys) or f"{source_kind}.{index:04d}"
        start = _first_float(
            properties,
            "projected_start_distance_m",
            "start_distance_m",
            "route_start_distance_m",
        )
        end = _first_float(
            properties,
            "projected_end_distance_m",
            "end_distance_m",
            "route_end_distance_m",
        )
        route_distance = _first_float(
            properties,
            "route_distance_m",
            "distance_m",
            "sample_distance_m",
        )
        if route_distance is None and start is not None and end is not None:
            route_distance = (start + end) / 2.0
        coordinate = None
        projection_distance = None
        points = _feature_coordinate_points(feature)
        if points:
            coordinate = points[len(points) // 2]
        if route_distance is None and points:
            projection = _nearest_route_projection(route_display_geometry, points[0])
            if projection is not None:
                route_distance = _float_or_none(projection.get("route_distance_m"))
                projection_distance = _float_or_none(projection.get("distance_to_route_m"))
                coordinate = {"lat": projection.get("lat"), "lon": projection.get("lon")}
        if route_distance is None:
            continue
        coordinate = coordinate or _route_coordinate_at_distance(
            route_display_geometry,
            route_distance,
        )
        tags.append(
            _base_tag(
                project_id=project_id,
                source_kind=source_kind,
                source_ref=source_ref,
                source_id=source_id,
                item=properties,
                route_distance_m=route_distance,
                route_display_geometry=route_display_geometry,
                route_mileage_alignment=route_mileage_alignment,
                display_mileage=_display(route_mileage_alignment, route_distance),
                display_mileage_span=_display_span(route_mileage_alignment, start, end),
                coordinate=coordinate,
                source_coordinate=points[0] if points else None,
                route_projection_distance_m=projection_distance,
                route_projection_status=_projection_alignment_status(projection_distance),
                compact_text=False,
            )
        )
    return tags


def _optional_geojson_tags(
    *,
    root: Path,
    project: dict[str, Any],
    project_id: str,
    ref_key: str,
    default_ref: str,
    source_kind: str,
    route_display_geometry: dict[str, Any],
    route_mileage_alignment: dict[str, Any],
    id_keys: tuple[str, ...],
) -> list[dict[str, Any]]:
    path = _project_path(root, project, ref_key, default_ref)
    if not path.exists():
        return []
    return _geojson_feature_tags(
        project_id=project_id,
        source_kind=source_kind,
        source_ref=_source_ref(root, path),
        payload=_load_json_object(path),
        route_display_geometry=route_display_geometry,
        route_mileage_alignment=route_mileage_alignment,
        id_keys=id_keys,
        feature_limit=None,
    )


def _optional_point_payload_tags(
    *,
    root: Path,
    project: dict[str, Any],
    project_id: str,
    ref_key: str,
    default_ref: str,
    source_kind: str,
    payload_key: str,
    id_keys: tuple[str, ...],
    route_display_geometry: dict[str, Any],
    route_mileage_alignment: dict[str, Any],
    source_route_distances: dict[str, float] | None = None,
    project_coordinates: bool = True,
) -> list[dict[str, Any]]:
    path = _project_path(root, project, ref_key, default_ref)
    if not path.exists():
        return []
    items = _payload_list(_load_json_object(path), payload_key)
    return _point_tags(
        project_id=project_id,
        source_kind=source_kind,
        source_ref=_source_ref(root, path),
        items=items,
        id_keys=id_keys,
        route_display_geometry=route_display_geometry,
        route_mileage_alignment=route_mileage_alignment,
        source_route_distances=source_route_distances,
        project_coordinates=project_coordinates,
    )


def _optional_route_pressure_tags(
    *,
    root: Path,
    project: dict[str, Any],
    project_id: str,
    route_display_geometry: dict[str, Any],
    route_mileage_alignment: dict[str, Any],
) -> list[dict[str, Any]]:
    path = _project_path(
        root,
        project,
        "route_pressure_profile_ref",
        DEFAULT_ROUTE_PRESSURE_PROFILE_REF,
    )
    if not path.exists():
        return []
    payload = _load_json_object(path)
    tags = []
    for item in _payload_list(payload, "samples"):
        source_id = str(item.get("sample_id") or item.get("candidate_id") or "")
        if not source_id:
            continue
        route_distance = _float_or_none(item.get("distance_m"))
        if route_distance is None:
            start = _float_or_none(item.get("start_distance_m"))
            end = _float_or_none(item.get("end_distance_m"))
            if start is not None and end is not None:
                route_distance = (start + end) / 2.0
        if route_distance is None:
            continue
        tags.append(
            _base_tag(
                project_id=project_id,
                source_kind="route_pressure_sample",
                source_ref=_source_ref(root, path),
                source_id=source_id,
                item=item,
                route_distance_m=route_distance,
                route_display_geometry=route_display_geometry,
                route_mileage_alignment=route_mileage_alignment,
                display_mileage=_display(route_mileage_alignment, route_distance),
                display_mileage_span=_display_span(
                    route_mileage_alignment,
                    item.get("start_distance_m"),
                    item.get("end_distance_m"),
                ),
                coordinate=_route_coordinate_at_distance(route_display_geometry, route_distance),
                source_coordinate=_source_coordinate(item),
                route_projection_distance_m=None,
                route_projection_status="route_distance_axis",
                compact_text=False,
            )
        )
    return tags


def _optional_boss_point_tags(
    *,
    root: Path,
    project: dict[str, Any],
    project_id: str,
    route_display_geometry: dict[str, Any],
    route_mileage_alignment: dict[str, Any],
) -> list[dict[str, Any]]:
    path = _project_path(root, project, "boss_points_ref", DEFAULT_BOSS_POINTS_REF)
    if not path.exists():
        return []
    tags = []
    for item in _payload_list(_load_json_object(path), "boss_points"):
        source_id = str(item.get("boss_point_id") or "")
        if not source_id:
            continue
        existing_display = item.get("display_mileage")
        existing_display = existing_display if isinstance(existing_display, dict) else {}
        route_position = item.get("route_position")
        route_position = route_position if isinstance(route_position, dict) else {}
        route_distance = _float_or_none(
            existing_display.get("route_distance_m")
        ) or _float_or_none(route_position.get("distance_m"))
        if route_distance is None:
            continue
        display = dict(existing_display) if existing_display else _display(
            route_mileage_alignment,
            route_distance,
        )
        display.setdefault("candidate_only", True)
        display.setdefault("runtime_safety_truth", False)
        tags.append(
            _base_tag(
                project_id=project_id,
                source_kind="boss_point",
                source_ref=_source_ref(root, path),
                source_id=source_id,
                item=item,
                route_distance_m=route_distance,
                route_display_geometry=route_display_geometry,
                route_mileage_alignment=route_mileage_alignment,
                display_mileage=display,
                display_mileage_span=_display_span(
                    route_mileage_alignment,
                    existing_display.get("start_m"),
                    existing_display.get("end_m"),
                ),
                coordinate=_route_coordinate_at_distance(route_display_geometry, route_distance),
                source_coordinate=_source_coordinate(item),
                route_projection_distance_m=None,
                route_projection_status="route_distance_axis",
                compact_text=False,
            )
        )
    return tags


def _base_tag(
    *,
    project_id: str,
    source_kind: str,
    source_ref: str,
    source_id: str,
    item: dict[str, Any],
    route_distance_m: float,
    route_display_geometry: dict[str, Any],
    route_mileage_alignment: dict[str, Any],
    display_mileage: dict[str, Any],
    coordinate: dict[str, Any] | None,
    source_coordinate: dict[str, Any] | None,
    route_projection_distance_m: float | None,
    route_projection_status: str,
    display_mileage_span: dict[str, Any] | None = None,
    compact_text: bool = False,
) -> dict[str, Any]:
    coordinate = coordinate or _route_coordinate_at_distance(route_display_geometry, route_distance_m)
    display_mileage = {
        **display_mileage,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    display_label = str(display_mileage.get("label") or "").strip()
    span_label = (
        str((display_mileage_span or {}).get("label") or "").strip()
        if display_mileage_span
        else ""
    )
    label = _item_label(item, compact_text=compact_text)
    mileage_tag_label = (
        f"{span_label} {label}".strip()
        if span_label and span_label != "K待校正"
        else f"{display_label} {label}".strip()
    )
    tag = {
        "mileage_tag_id": _mileage_tag_id(project_id, source_kind, source_id),
        "source_kind": source_kind,
        "source_ref": source_ref,
        "source_id": source_id,
        "source_label": label,
        "display_label": mileage_tag_label,
        "display_mileage": display_mileage,
        "display_mileage_label": display_label,
        "route_distance_m": _round(route_distance_m),
        "route_axis": (
            "overpass_risk_ribbon_distance"
            if route_display_geometry.get("evidence_type")
            == "pretrip_overpass_risk_ribbon_centerline"
            else "segment_display_geometry_distance"
        ),
        "route_projection_status": route_projection_status,
        "route_projection_distance_m": _round(route_projection_distance_m),
        "route_projection_source_ref": route_display_geometry.get("source_path"),
        "lat": _round(_float_or_none((coordinate or {}).get("lat"))),
        "lon": _round(_float_or_none((coordinate or {}).get("lon"))),
        "source_lat": _round(_float_or_none((source_coordinate or {}).get("lat"))),
        "source_lon": _round(_float_or_none((source_coordinate or {}).get("lon"))),
        "alignment_source_ref": route_mileage_alignment.get("source_ref"),
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    if display_mileage_span is not None:
        tag["display_mileage_span"] = {
            **display_mileage_span,
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
    for key in (
        "review_state",
        "confidence",
        "evidence_type",
        "checkpoint_type",
        "mcp_classes",
        "risk_level",
        "risk_bucket",
    ):
        if item.get(key) not in (None, "", []):
            tag[key] = item.get(key)
    return tag


def _display(
    route_mileage_alignment: dict[str, Any],
    route_distance_m: Any,
) -> dict[str, Any]:
    return _display_mileage_for_route_distance(route_mileage_alignment, route_distance_m)


def _display_span(
    route_mileage_alignment: dict[str, Any],
    start_m: Any,
    end_m: Any,
) -> dict[str, Any] | None:
    start = _float_or_none(start_m)
    end = _float_or_none(end_m)
    if start is None and end is None:
        return None
    start_display = _display(route_mileage_alignment, start) if start is not None else {}
    end_display = _display(route_mileage_alignment, end) if end is not None else {}
    return {
        "label": _format_mileage_span_label(
            start_display.get("mileage_m"),
            end_display.get("mileage_m"),
        ),
        "start": start_display,
        "end": end_display,
        "start_route_distance_m": _round(start),
        "end_route_distance_m": _round(end),
        "alignment_status": _span_status(start_display, end_display),
        "source_ref": route_mileage_alignment.get("source_ref"),
    }


def _span_status(start_display: dict[str, Any], end_display: dict[str, Any]) -> str:
    statuses = [
        str(display.get("alignment_status") or "")
        for display in (start_display, end_display)
        if display
    ]
    if not statuses:
        return "missing_alignment"
    if all(status == "matched_mileage_anchor" for status in statuses):
        return "matched_mileage_anchor_span"
    if any(status.startswith("interpolated") for status in statuses):
        return "interpolated_mileage_anchor_span"
    if any(status.startswith("extrapolated") for status in statuses):
        return "extrapolated_mileage_anchor_span"
    return statuses[0]


def _mileage_tags_geojson(
    payload: dict[str, Any],
    route_display_geometry: dict[str, Any],
) -> dict[str, Any]:
    features = []
    for tag in payload.get("mileage_tags") or []:
        lat = _float_or_none(tag.get("lat"))
        lon = _float_or_none(tag.get("lon"))
        if lat is None or lon is None:
            coordinate = _route_coordinate_at_distance(
                route_display_geometry,
                tag.get("route_distance_m"),
            )
            lat = _float_or_none((coordinate or {}).get("lat"))
            lon = _float_or_none((coordinate or {}).get("lon"))
        if lat is None or lon is None:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [lon, lat],
                },
                "properties": {
                    "mileage_tag_id": tag.get("mileage_tag_id"),
                    "source_kind": tag.get("source_kind"),
                    "source_id": tag.get("source_id"),
                    "source_ref": tag.get("source_ref"),
                    "source_label": tag.get("source_label"),
                    "display_label": tag.get("display_label"),
                    "display_mileage_label": tag.get("display_mileage_label"),
                    "display_mileage_span_label": (
                        tag.get("display_mileage_span") or {}
                    ).get("label"),
                    "route_distance_m": tag.get("route_distance_m"),
                    "route_projection_status": tag.get("route_projection_status"),
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "artifact_kind": "pretrip_workspace_mileage_tag_alignment_geojson",
            "source_artifact_kind": payload.get("artifact_kind"),
            "project_id": payload.get("project_id"),
            "feature_count": len(features),
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
    }


def _counts(
    tags: list[dict[str, Any]],
    route_mileage_alignment: dict[str, Any],
) -> dict[str, Any]:
    source_kind_counts = Counter(str(tag.get("source_kind") or "unknown") for tag in tags)
    projection_counts = Counter(
        str(tag.get("route_projection_status") or "unknown") for tag in tags
    )
    display_status_counts = Counter(
        str((tag.get("display_mileage") or {}).get("alignment_status") or "unknown")
        for tag in tags
    )
    return {
        "tag_count": len(tags),
        "aligned_tag_count": sum(
            1
            for tag in tags
            if (tag.get("display_mileage") or {}).get("label") != "K待校正"
            or (tag.get("display_mileage_span") or {}).get("label") != "K待校正"
        ),
        "source_kind_counts": dict(sorted(source_kind_counts.items())),
        "route_projection_status_counts": dict(sorted(projection_counts.items())),
        "display_mileage_status_counts": dict(sorted(display_status_counts.items())),
        "usable_anchor_count": route_mileage_alignment.get("usable_anchor_count", 0),
        "projected_anchor_count": route_mileage_alignment.get("projected_anchor_count", 0),
        "rejected_anchor_count": route_mileage_alignment.get("rejected_anchor_count", 0),
        "candidate_only_count": len(tags),
        "runtime_safety_truth_count": 0,
    }


def _source_refs(root: Path, project: dict[str, Any]) -> dict[str, str]:
    refs = {}
    for key, value in project.items():
        if key.endswith("_ref") and isinstance(value, str) and value:
            path = root / value
            if path.exists():
                refs[key[:-4]] = value
    return refs


def _route_distance_lookup(*tag_groups: list[dict[str, Any]]) -> dict[str, float]:
    lookup: dict[str, float] = {}
    for group in tag_groups:
        for tag in group:
            source_id = str(tag.get("source_id") or "")
            route_distance = _float_or_none(tag.get("route_distance_m"))
            if source_id and route_distance is not None:
                lookup[source_id] = route_distance
    return lookup


def _source_ref(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _source_id(item: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _item_label(item: dict[str, Any], *, compact_text: bool) -> str:
    for key in ("display_label", "label", "name", "title", "normalized_note"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return _compact(value.strip(), limit=42 if compact_text else 80)
    return ""


def _source_coordinate(item: dict[str, Any]) -> dict[str, float] | None:
    lat = _float_or_none(item.get("lat"))
    lon = _float_or_none(item.get("lon"))
    if lat is None or lon is None:
        return None
    return {"lat": lat, "lon": lon}


def _first_float(item: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _float_or_none(item.get(key))
        if value is not None:
            return value
    return None


def _mileage_m_from_item(item: dict[str, Any]) -> float | None:
    for key in ("display_label", "label", "name", "normalized_note"):
        value = item.get(key)
        if not isinstance(value, str):
            continue
        match = MILEAGE_LABEL_RE.search(value)
        if match:
            return float(match.group(0).lower().replace("k", "").strip()) * 1000.0
    return None


def _mileage_tag_id(project_id: str, source_kind: str, source_id: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in ".-" else "_" for ch in source_id)
    return f"mileage_tag.{project_id}.{source_kind}.{safe}"


def _compact(value: str, *, limit: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 1)].rstrip() + "..."


def _boundary() -> dict[str, Any]:
    return {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "pretrip_candidate_evidence_only": True,
        "phase1_runtime_mutation_allowed": False,
        "phase2_brain_writeback_allowed": False,
        "safety_api_calls_allowed": False,
        "workspace_file_mutation_allowed": True,
    }


def _update_project_refs(
    project_path: Path,
    project: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    updated = {
        **project,
        "mileage_tag_alignment_ref": MILEAGE_TAG_ALIGNMENT_REF,
        "mileage_tag_alignment_geojson_ref": MILEAGE_TAG_ALIGNMENT_GEOJSON_REF,
        "mileage_tag_alignment_count": payload.get("counts", {}).get("tag_count", 0),
        "mileage_tag_alignment_updated_at": payload.get("generated_at"),
        "mileage_tag_alignment_schema_version": MILEAGE_TAG_ALIGNMENT_SCHEMA_VERSION,
    }
    _write_json(project_path, updated)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Align workspace evidence with trail mileage K tags."
    )
    parser.add_argument("project_root", type=Path)
    parser.add_argument("--generated-at")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    payload = align_pretrip_workspace_mileage_tags(
        args.project_root,
        generated_at=args.generated_at,
        dry_run=args.dry_run,
    )
    print(json.dumps(payload["counts"], ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
