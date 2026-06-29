from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from geo_utils import haversine_m


DEFAULT_MAX_PROJECTION_DISTANCE_M = 50.0
MAX_SEGMENT_ALIGNMENT_DISTANCE_RATIO = 8.0
MIN_SEGMENT_ALIGNMENT_DISTANCE_RATIO = 0.30
MIN_SEGMENT_ALIGNMENT_LIMIT_M = 2_000.0
MAX_POINT_ROUTE_DISTANCE_DELTA_M = 2_000.0

ALIGNMENT_SUMMARY_REF = "outputs/overpass_route_alignment.json"
ALIGNED_CHECKPOINTS_REF = "outputs/overpass_aligned_checkpoints.json"
ALIGNED_SEGMENTS_REF = "outputs/overpass_aligned_segments.json"
ALIGNED_SEGMENT_DISPLAY_REF = "outputs/overpass_aligned_segment_display_geometry.json"
ALIGNED_MCP_REF = "outputs/overpass_aligned_mcp_candidates.json"


@dataclass(frozen=True)
class _RouteEdge:
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float
    start_distance_m: float
    end_distance_m: float
    length_m: float
    source_feature_id: str


def align_workspace_route_to_overpass(
    project_root: Path | str,
    *,
    max_projection_distance_m: float = DEFAULT_MAX_PROJECTION_DISTANCE_M,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Write Overpass-aligned pretrip display artifacts for a workspace.

    The original importer artifacts remain untouched. Aligned artifacts are
    candidate/evidence-only display geometry: GPX points within the configured
    tolerance snap to the Overpass/risk-ribbon centerline, and points outside the
    tolerance keep their original GPX position.
    """

    root = Path(project_root)
    project_path = root / "project.json"
    if not project_path.exists():
        return _status("skipped_missing_project")
    project = _load_json(project_path)
    risk_ref = project.get("risk_ribbon_ref")
    risk_path = root / risk_ref if isinstance(risk_ref, str) and risk_ref else None
    if risk_path is None or not risk_path.exists():
        return _status(
            "skipped_missing_overpass_centerline",
            required_ref="risk_ribbon_ref",
        )
    risk_ribbon = _load_json(risk_path)
    route_edges = _route_edges_from_risk_ribbon(risk_ribbon)
    if not route_edges:
        return _status("skipped_empty_overpass_centerline", required_ref="risk_ribbon_ref")

    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    outputs: dict[str, str] = {
        "overpass_route_alignment_ref": ALIGNMENT_SUMMARY_REF,
    }
    summaries: dict[str, Any] = {}
    checkpoint_route_distance_hints = _checkpoint_route_distance_hints(root, project)

    checkpoints_result = _align_candidate_file(
        root=root,
        project=project,
        ref_key="checkpoint_candidates_ref",
        output_ref=ALIGNED_CHECKPOINTS_REF,
        item_keys=("candidates",),
        id_keys=("candidate_id", "checkpoint_id"),
        route_edges=route_edges,
        max_projection_distance_m=max_projection_distance_m,
        route_distance_hints_m=checkpoint_route_distance_hints,
        generated_at=generated_at,
    )
    if checkpoints_result["status"] == "completed":
        outputs["overpass_aligned_checkpoint_candidates_ref"] = ALIGNED_CHECKPOINTS_REF
    summaries["checkpoints"] = checkpoints_result

    segments_result = _align_segments_from_checkpoints(
        root=root,
        project=project,
        checkpoint_output_ref=ALIGNED_CHECKPOINTS_REF,
        route_edges=route_edges,
        max_projection_distance_m=max_projection_distance_m,
        route_distance_hints_m=checkpoint_route_distance_hints,
        generated_at=generated_at,
    )
    if segments_result["status"] == "completed":
        outputs["overpass_aligned_segment_candidates_ref"] = ALIGNED_SEGMENTS_REF
    summaries["segments"] = segments_result

    display_result = _align_segment_display_geometry(
        root=root,
        project=project,
        route_edges=route_edges,
        max_projection_distance_m=max_projection_distance_m,
        generated_at=generated_at,
    )
    if display_result["status"] == "completed":
        outputs["overpass_aligned_segment_display_geometry_ref"] = (
            ALIGNED_SEGMENT_DISPLAY_REF
        )
    summaries["segment_display_geometry"] = display_result

    mcp_result = _align_candidate_file(
        root=root,
        project=project,
        ref_key="mcp_candidates_ref",
        output_ref=ALIGNED_MCP_REF,
        item_keys=("mcp_candidates", "candidates"),
        id_keys=("mcp_id", "candidate_id"),
        route_edges=route_edges,
        max_projection_distance_m=max_projection_distance_m,
        generated_at=generated_at,
    )
    if mcp_result["status"] == "completed":
        outputs["overpass_aligned_mcp_candidates_ref"] = ALIGNED_MCP_REF
    summaries["mcp_candidates"] = mcp_result

    summary = {
        "artifact_kind": "pretrip_overpass_route_alignment",
        "schema_version": "0.1.0",
        "project_id": project.get("project_id"),
        "source_path": ALIGNMENT_SUMMARY_REF,
        "generated_at": generated_at,
        "max_projection_distance_m": max_projection_distance_m,
        "route_basis": "overpass_risk_ribbon_centerline",
        "source_refs": {
            "risk_ribbon_ref": risk_ref,
            "checkpoint_candidates_ref": project.get("checkpoint_candidates_ref"),
            "segment_candidates_ref": project.get("segment_candidates_ref"),
            "segment_display_geometry_ref": project.get("segment_display_geometry_ref"),
            "mcp_candidates_ref": project.get("mcp_candidates_ref"),
        },
        "output_refs": outputs,
        "projection_policy": {
            "gpx_normal_corridor_m": max_projection_distance_m,
            "point_projection": "snap_to_nearest_overpass_centerline_within_corridor",
            "segment_projection": (
                "prefer checkpoint endpoint projections; when an endpoint is outside "
                "the corridor, inspect GPX segment display geometry and preserve the "
                "original GPX segment only when no usable Overpass centerline can be "
                "found within the GPX-normal corridor"
            ),
            "fallback": "preserve_original_gpx_segment_as_reference_evidence",
        },
        "counts": {
            "route_edge_count": len(route_edges),
            "snapped_point_count": sum(
                int(item.get("snapped_point_count", 0)) for item in summaries.values()
            ),
            "kept_gpx_point_count": sum(
                int(item.get("kept_gpx_point_count", 0)) for item in summaries.values()
            ),
            "missing_coordinate_count": sum(
                int(item.get("missing_coordinate_count", 0))
                for item in summaries.values()
            ),
            "rejected_segment_alignment_count": sum(
                int(item.get("rejected_segment_alignment_count", 0))
                for item in summaries.values()
            ),
        },
        "inputs": summaries,
        "boundary": _boundary(),
        "notes": [
            "Golden GPX remains reference evidence only; aligned display geometry uses Overpass/risk-ribbon centerline where a point or GPX segment corridor is within 50m.",
            "Points farther than the projection tolerance remain at the original GPX position so missing roads or temporary terrain changes stay reviewable.",
        ],
    }
    _write_json(root / ALIGNMENT_SUMMARY_REF, summary)
    _update_project_refs(project_path, outputs, generated_at, max_projection_distance_m)
    return {
        "status": "completed",
        "output_refs": outputs,
        "summary_ref": ALIGNMENT_SUMMARY_REF,
        "counts": summary["counts"],
        "boundary": _boundary(),
    }


def _checkpoint_route_distance_hints(root: Path, project: dict[str, Any]) -> dict[str, float]:
    ref = project.get("segment_candidates_ref")
    if not isinstance(ref, str) or not ref:
        return {}
    path = root / ref
    if not path.exists():
        return {}
    payload = _load_json(path)
    _, source_items = _candidate_list(payload, ("candidates",))
    if not isinstance(source_items, list):
        return {}
    indexed_segments = [
        item
        for item in source_items
        if isinstance(item, dict)
        and isinstance(_as_float(item.get("route_point_start_index")), float)
        and isinstance(_as_float(item.get("route_point_end_index")), float)
    ]
    if not indexed_segments:
        return {}

    hints: dict[str, float] = {}
    cumulative_m = 0.0
    for item in sorted(
        indexed_segments,
        key=lambda candidate: (
            _as_float(candidate.get("route_point_start_index")) or 0.0,
            _as_float(candidate.get("route_point_end_index")) or 0.0,
        ),
    ):
        from_id = _first_text(item, ("from_candidate_id", "from_checkpoint_id"))
        to_id = _first_text(item, ("to_candidate_id", "to_checkpoint_id"))
        distance_m = _as_float(item.get("distance_m"))
        if not isinstance(distance_m, float) or distance_m < 0:
            continue
        if from_id:
            cumulative_m = hints.setdefault(from_id, cumulative_m)
        cumulative_m += distance_m
        if to_id:
            hints[to_id] = cumulative_m
    return hints


def _align_candidate_file(
    *,
    root: Path,
    project: dict[str, Any],
    ref_key: str,
    output_ref: str,
    item_keys: tuple[str, ...],
    id_keys: tuple[str, ...],
    route_edges: list[_RouteEdge],
    max_projection_distance_m: float,
    generated_at: str,
    route_distance_hints_m: dict[str, float] | None = None,
) -> dict[str, Any]:
    ref = project.get(ref_key)
    if not isinstance(ref, str) or not ref:
        return _status("skipped_missing_ref", required_ref=ref_key)
    input_path = root / ref
    if not input_path.exists():
        return _status("skipped_missing_file", required_ref=ref_key, ref=ref)
    payload = _load_json(input_path)
    if isinstance(payload, list):
        item_key = None
        source_items = payload
    elif isinstance(payload, dict):
        item_key = next(
            (key for key in item_keys if isinstance(payload.get(key), list)),
            None,
        )
        source_items = payload.get(item_key, []) if item_key is not None else []
    else:
        item_key = None
        source_items = []
    if not isinstance(source_items, list):
        return _status("skipped_no_candidate_list", required_ref=ref_key, ref=ref)

    aligned_items: list[dict[str, Any]] = []
    stats = _Stats()
    for index, item in enumerate(source_items):
        if not isinstance(item, dict):
            continue
        item_id = _first_text(item, id_keys) or f"{ref_key}.{index + 1:06d}"
        expected_route_distance_m = (
            (route_distance_hints_m or {}).get(item_id)
            if route_distance_hints_m is not None
            else None
        )
        if expected_route_distance_m is None:
            expected_route_distance_m = _record_route_distance_hint(item)
        aligned_items.append(
            _align_point_record(
                item,
                item_id=item_id,
                route_edges=route_edges,
                max_projection_distance_m=max_projection_distance_m,
                expected_route_distance_m=expected_route_distance_m,
                stats=stats,
            )
        )

    if item_key is None:
        output: Any = aligned_items
    else:
        output = {
            **payload,
            item_key: aligned_items,
            "source_path": output_ref,
            "source_ref": ref,
            "overpass_alignment": {
                "generated_at": generated_at,
                "source_ref": ref,
                "max_projection_distance_m": max_projection_distance_m,
                **stats.to_dict(),
            },
            "boundary": {
                **(
                    payload.get("boundary")
                    if isinstance(payload.get("boundary"), dict)
                    else {}
                ),
                **_boundary(),
            },
        }
    _write_json(root / output_ref, output)
    return {"status": "completed", "output_ref": output_ref, **stats.to_dict()}


def _align_segments_from_checkpoints(
    *,
    root: Path,
    project: dict[str, Any],
    checkpoint_output_ref: str,
    route_edges: list[_RouteEdge],
    max_projection_distance_m: float,
    route_distance_hints_m: dict[str, float],
    generated_at: str,
) -> dict[str, Any]:
    ref = project.get("segment_candidates_ref")
    if not isinstance(ref, str) or not ref:
        return _status("skipped_missing_ref", required_ref="segment_candidates_ref")
    input_path = root / ref
    if not input_path.exists():
        return _status(
            "skipped_missing_file",
            required_ref="segment_candidates_ref",
            ref=ref,
        )
    checkpoint_path = root / checkpoint_output_ref
    if not checkpoint_path.exists():
        return _status(
            "skipped_missing_file",
            required_ref="overpass_aligned_checkpoint_candidates_ref",
            ref=checkpoint_output_ref,
        )

    payload = _load_json(input_path)
    checkpoint_payload = _load_json(checkpoint_path)
    item_key, source_items = _candidate_list(payload, ("candidates",))
    _, checkpoint_items = _candidate_list(checkpoint_payload, ("candidates",))
    if not isinstance(source_items, list):
        return _status("skipped_no_candidate_list", required_ref="segment_candidates_ref", ref=ref)

    checkpoints_by_id = {
        str(item.get("candidate_id") or item.get("checkpoint_id")): item
        for item in checkpoint_items
        if isinstance(item, dict) and (item.get("candidate_id") or item.get("checkpoint_id"))
    }
    display_segments_by_id = _segment_display_segments_by_id(root, project)
    aligned_items: list[dict[str, Any]] = []
    stats = _Stats()
    for index, item in enumerate(source_items):
        if not isinstance(item, dict):
            continue
        segment_id = _first_text(item, ("candidate_id", "segment_id")) or f"seg.{index + 1:03d}"
        from_id = _first_text(item, ("from_candidate_id", "from_checkpoint_id"))
        to_id = _first_text(item, ("to_candidate_id", "to_checkpoint_id"))
        from_checkpoint = checkpoints_by_id.get(str(from_id)) if from_id else None
        to_checkpoint = checkpoints_by_id.get(str(to_id)) if to_id else None
        aligned = dict(item)
        aligned["gpx_distance_m"] = item.get("distance_m")
        if not isinstance(from_checkpoint, dict) or not isinstance(to_checkpoint, dict):
            stats.missing_coordinate_count += 1
            aligned["overpass_projection"] = {
                "status": "missing_checkpoint_endpoint",
                "from_candidate_id": from_id,
                "to_candidate_id": to_id,
                "max_projection_distance_m": max_projection_distance_m,
            }
            aligned_items.append(aligned)
            continue

        start_projection = _usable_checkpoint_projection(from_checkpoint)
        end_projection = _usable_checkpoint_projection(to_checkpoint)
        if start_projection is None or end_projection is None:
            source_distance_m = _segment_source_distance_m(
                item,
                display_segments_by_id.get(segment_id),
            )
            display_alignment = _segment_alignment_from_display_geometry(
                display_segments_by_id.get(segment_id),
                expected_route_distances_by_segment=_segment_expected_route_distances_by_segment(
                    display_segments_by_id.get(segment_id),
                    from_id=from_id,
                    to_id=to_id,
                    route_distance_hints_m=route_distance_hints_m,
                ),
                route_edges=route_edges,
                max_projection_distance_m=max_projection_distance_m,
                stats=stats,
            )
            if display_alignment is not None:
                route_distance_delta = display_alignment["route_distance_delta_m"]
                rejection = _segment_alignment_rejection(
                    segment_id=segment_id,
                    source_distance_m=source_distance_m,
                    aligned_distance_m=route_distance_delta,
                    aligned_point_count=len(display_alignment["centerline"]),
                    projection_policy="gpx_normal_corridor_50m",
                )
                if rejection is not None:
                    stats.rejected_segment_alignment_count += 1
                    stats.kept_gpx_point_count += 1
                    aligned["overpass_projection"] = {
                        **rejection,
                        "from_candidate_id": from_id,
                        "to_candidate_id": to_id,
                        "from_projection_status": _projection_status(from_checkpoint),
                        "to_projection_status": _projection_status(to_checkpoint),
                        "max_projection_distance_m": max_projection_distance_m,
                    }
                    aligned_items.append(aligned)
                    continue
                midpoint = display_alignment["midpoint"]
                aligned.update(
                    {
                        "lat": midpoint["lat"],
                        "lon": midpoint["lon"],
                        "coordinates": [midpoint["lon"], midpoint["lat"]],
                        "distance_m": route_distance_delta,
                        "route_distance_start_m": min(
                            display_alignment["start_distance_m"],
                            display_alignment["end_distance_m"],
                        ),
                        "route_distance_end_m": max(
                            display_alignment["start_distance_m"],
                            display_alignment["end_distance_m"],
                        ),
                        "overpass_route_distance_m": route_distance_delta,
                        "overpass_display_coordinate_segments": [
                            display_alignment["centerline"]
                        ],
                        "overpass_display_point_count": len(
                            display_alignment["centerline"]
                        ),
                        "route_basis": "overpass_risk_ribbon_centerline",
                        "golden_gpx_role_after_alignment": "reference_track_evidence",
                        "overpass_projection": {
                            "status": "segment_gpx_normal_corridor_snapped_to_overpass",
                            "segment_id": segment_id,
                            "from_candidate_id": from_id,
                            "to_candidate_id": to_id,
                            "from_projection_status": _projection_status(from_checkpoint),
                            "to_projection_status": _projection_status(to_checkpoint),
                            "from_route_distance_m": round(
                                display_alignment["start_distance_m"], 3
                            ),
                            "to_route_distance_m": round(
                                display_alignment["end_distance_m"], 3
                            ),
                            "distance_m": round(route_distance_delta, 3),
                            "snapped_display_point_count": display_alignment[
                                "snapped_display_point_count"
                            ],
                            "max_projection_distance_m": max_projection_distance_m,
                            "projection_policy": "gpx_normal_corridor_50m",
                        },
                    }
                )
                aligned_items.append(aligned)
                continue
            stats.kept_gpx_point_count += 1
            aligned["overpass_projection"] = {
                "status": "kept_gpx_endpoint_outside_overpass_tolerance",
                "from_candidate_id": from_id,
                "to_candidate_id": to_id,
                "from_projection_status": _projection_status(from_checkpoint),
                "to_projection_status": _projection_status(to_checkpoint),
                "max_projection_distance_m": max_projection_distance_m,
                "projection_policy": "preserve_gpx_only_when_no_overpass_within_gpx_normal_corridor",
            }
            aligned_items.append(aligned)
            continue

        start_distance = start_projection["route_distance_m"]
        end_distance = end_projection["route_distance_m"]
        route_distance_delta = abs(end_distance - start_distance)
        source_distance_m = _segment_source_distance_m(
            item,
            display_segments_by_id.get(segment_id),
        )
        rejection = _segment_alignment_rejection(
            segment_id=segment_id,
            source_distance_m=source_distance_m,
            aligned_distance_m=route_distance_delta,
            aligned_point_count=None,
            projection_policy="checkpoint_endpoint_corridor",
        )
        if rejection is not None:
            stats.rejected_segment_alignment_count += 1
            stats.kept_gpx_point_count += 1
            aligned["overpass_projection"] = {
                **rejection,
                "from_candidate_id": from_id,
                "to_candidate_id": to_id,
                "from_route_distance_m": round(start_distance, 3),
                "to_route_distance_m": round(end_distance, 3),
                "max_projection_distance_m": max_projection_distance_m,
            }
            aligned_items.append(aligned)
            continue
        centerline = _slice_centerline(
            route_edges,
            start_distance_m=start_distance,
            end_distance_m=end_distance,
        )
        midpoint = _point_at_route_distance(
            route_edges,
            (start_distance + end_distance) / 2.0,
        )
        if not centerline or midpoint is None:
            stats.kept_gpx_point_count += 1
            aligned["overpass_projection"] = {
                "status": "kept_gpx_empty_overpass_slice",
                "from_candidate_id": from_id,
                "to_candidate_id": to_id,
                "max_projection_distance_m": max_projection_distance_m,
            }
            aligned_items.append(aligned)
            continue

        stats.snapped_point_count += 2
        aligned.update(
            {
                "lat": midpoint["lat"],
                "lon": midpoint["lon"],
                "coordinates": [midpoint["lon"], midpoint["lat"]],
                "distance_m": route_distance_delta,
                "route_distance_start_m": min(start_distance, end_distance),
                "route_distance_end_m": max(start_distance, end_distance),
                "overpass_route_distance_m": route_distance_delta,
                "overpass_display_coordinate_segments": [centerline],
                "overpass_display_point_count": len(centerline),
                "route_basis": "overpass_risk_ribbon_centerline",
                "golden_gpx_role_after_alignment": "reference_track_evidence",
                "overpass_projection": {
                    "status": "segment_endpoints_snapped_to_overpass",
                    "segment_id": segment_id,
                    "from_candidate_id": from_id,
                    "to_candidate_id": to_id,
                    "from_route_distance_m": round(start_distance, 3),
                    "to_route_distance_m": round(end_distance, 3),
                    "distance_m": round(route_distance_delta, 3),
                    "max_projection_distance_m": max_projection_distance_m,
                    "projection_policy": "checkpoint_endpoint_corridor",
                },
            }
        )
        aligned_items.append(aligned)

    if item_key is None:
        output: Any = aligned_items
    else:
        output = {
            **payload,
            item_key: aligned_items,
            "source_path": ALIGNED_SEGMENTS_REF,
            "source_ref": ref,
            "overpass_alignment": {
                "generated_at": generated_at,
                "source_ref": ref,
                "checkpoint_source_ref": checkpoint_output_ref,
                "max_projection_distance_m": max_projection_distance_m,
                "route_basis": "overpass_risk_ribbon_centerline",
                **stats.to_dict(),
            },
            "boundary": {
                **(
                    payload.get("boundary")
                    if isinstance(payload.get("boundary"), dict)
                    else {}
                ),
                **_boundary(),
            },
        }
    _write_json(root / ALIGNED_SEGMENTS_REF, output)
    return {"status": "completed", "output_ref": ALIGNED_SEGMENTS_REF, **stats.to_dict()}


def _align_segment_display_geometry(
    *,
    root: Path,
    project: dict[str, Any],
    route_edges: list[_RouteEdge],
    max_projection_distance_m: float,
    generated_at: str,
) -> dict[str, Any]:
    ref = project.get("segment_display_geometry_ref")
    if not isinstance(ref, str) or not ref:
        return _status("skipped_missing_ref", required_ref="segment_display_geometry_ref")
    input_path = root / ref
    if not input_path.exists():
        return _status(
            "skipped_missing_file",
            required_ref="segment_display_geometry_ref",
            ref=ref,
        )
    payload = _load_json(input_path)
    stats = _Stats()
    aligned_segments: list[dict[str, Any]] = []
    aligned_segment_map = _aligned_segments_by_id(root / ALIGNED_SEGMENTS_REF)
    route_distance_hints_m = _checkpoint_route_distance_hints(root, project)

    for segment in payload.get("segments", []):
        if not isinstance(segment, dict):
            continue
        segment_id = _first_text(segment, ("candidate_id", "segment_candidate_id", "segment_id"))
        aligned_segment = aligned_segment_map.get(str(segment_id)) if segment_id else None
        overpass_segments = (
            aligned_segment.get("overpass_display_coordinate_segments")
            if isinstance(aligned_segment, dict)
            else None
        )
        if isinstance(overpass_segments, list) and overpass_segments:
            coordinate_segments = [
                [
                    point
                    for point in coordinate_segment
                    if isinstance(point, dict)
                ]
                for coordinate_segment in overpass_segments
                if isinstance(coordinate_segment, list)
            ]
            coordinate_segments = [segment for segment in coordinate_segments if segment]
            if coordinate_segments:
                flattened = [
                    point
                    for coordinate_segment in coordinate_segments
                    for point in coordinate_segment
                ]
                rejection = _display_alignment_rejection(
                    segment_id=str(segment_id),
                    source_segment=segment,
                    aligned_points=flattened,
                    projection_policy="overpass_aligned_segment_candidate",
                )
                if rejection is not None:
                    stats.rejected_segment_alignment_count += 1
                    aligned_segments.append(
                        _fallback_display_segment(
                            segment,
                            source_ref=ref,
                            max_projection_distance_m=max_projection_distance_m,
                            rejection=rejection,
                        )
                    )
                    continue
                aligned_segments.append(
                    {
                        **segment,
                        "source_path": ALIGNED_SEGMENT_DISPLAY_REF,
                        "coordinates": flattened,
                        "coordinate_segments": coordinate_segments,
                        "display_point_count": len(flattened),
                        "display_segment_count": len(coordinate_segments),
                        "overpass_alignment": {
                            "source_ref": ref,
                            "candidate_ref": ALIGNED_SEGMENTS_REF,
                            "max_projection_distance_m": max_projection_distance_m,
                            "route_basis": "overpass_risk_ribbon_centerline",
                            "segment_candidate_id": segment_id,
                        },
                    }
                )
                continue
        coordinate_segments = segment.get("coordinate_segments")
        if not isinstance(coordinate_segments, list) or not coordinate_segments:
            coordinates = segment.get("coordinates")
            coordinate_segments = [coordinates] if isinstance(coordinates, list) else []
        aligned_coordinate_segments: list[list[dict[str, Any]]] = []
        for coordinate_segment in coordinate_segments:
            if not isinstance(coordinate_segment, list):
                continue
            expected_segments = _segment_expected_route_distances_by_segment(
                segment,
                from_id=_first_text(segment, ("from_candidate_id", "from_checkpoint_id")),
                to_id=_first_text(segment, ("to_candidate_id", "to_checkpoint_id")),
                route_distance_hints_m=route_distance_hints_m,
            )
            expected_index = len(aligned_coordinate_segments)
            aligned_coordinate_segments.append(
                _align_coordinate_segment(
                    coordinate_segment,
                    route_edges=route_edges,
                    max_projection_distance_m=max_projection_distance_m,
                    expected_route_distances_m=(
                        expected_segments[expected_index]
                        if expected_segments is not None
                        and expected_index < len(expected_segments)
                        else None
                    ),
                    stats=stats,
                )
            )
        flattened = [
            point
            for coordinate_segment in aligned_coordinate_segments
            for point in coordinate_segment
        ]
        if _snapped_overpass_point_count(flattened) == 0:
            aligned_segments.append(
                _fallback_display_segment(
                    segment,
                    source_ref=ref,
                    max_projection_distance_m=max_projection_distance_m,
                    rejection={
                        "status": "kept_gpx_no_display_points_snapped_to_overpass",
                        "segment_id": str(segment_id),
                        "projection_policy": "display_coordinate_corridor",
                    },
                )
            )
            continue
        rejection = _display_alignment_rejection(
            segment_id=str(segment_id),
            source_segment=segment,
            aligned_points=flattened,
            projection_policy="display_coordinate_corridor",
        )
        if rejection is not None:
            stats.rejected_segment_alignment_count += 1
            aligned_segments.append(
                _fallback_display_segment(
                    segment,
                    source_ref=ref,
                    max_projection_distance_m=max_projection_distance_m,
                    rejection=rejection,
                )
            )
            continue
        aligned_segments.append(
            {
                **segment,
                "source_path": ALIGNED_SEGMENT_DISPLAY_REF,
                "coordinates": flattened,
                "coordinate_segments": aligned_coordinate_segments,
                "display_point_count": len(flattened),
                "display_segment_count": len(aligned_coordinate_segments),
                "overpass_alignment": {
                    "source_ref": ref,
                    "max_projection_distance_m": max_projection_distance_m,
                    "route_basis": "overpass_risk_ribbon_centerline",
                },
            }
        )

    output = {
        **payload,
        "artifact_kind": "pretrip_overpass_aligned_segment_display_geometry",
        "source_path": ALIGNED_SEGMENT_DISPLAY_REF,
        "source_ref": ref,
        "generated_at": generated_at,
        "segments": aligned_segments,
        "segment_count": len(aligned_segments),
        "overpass_alignment": {
            "generated_at": generated_at,
            "source_ref": ref,
            "max_projection_distance_m": max_projection_distance_m,
            **stats.to_dict(),
        },
        "boundary": {
            **(payload.get("boundary") if isinstance(payload.get("boundary"), dict) else {}),
            **_boundary(),
        },
    }
    _write_json(root / ALIGNED_SEGMENT_DISPLAY_REF, output)
    return {"status": "completed", "output_ref": ALIGNED_SEGMENT_DISPLAY_REF, **stats.to_dict()}


def _candidate_list(
    payload: Any,
    item_keys: tuple[str, ...],
) -> tuple[str | None, list[Any]]:
    if isinstance(payload, list):
        return None, payload
    if isinstance(payload, dict):
        item_key = next(
            (key for key in item_keys if isinstance(payload.get(key), list)),
            None,
        )
        if item_key is not None:
            return item_key, payload.get(item_key, [])
    return None, []


def _aligned_segments_by_id(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    payload = _load_json(path)
    _, items = _candidate_list(payload, ("candidates",))
    return {
        str(item.get("candidate_id") or item.get("segment_candidate_id") or item.get("segment_id")): item
        for item in items
        if isinstance(item, dict)
        and (item.get("candidate_id") or item.get("segment_candidate_id") or item.get("segment_id"))
    }


def _segment_display_segments_by_id(
    root: Path,
    project: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    ref = project.get("segment_display_geometry_ref")
    if not isinstance(ref, str) or not ref:
        return {}
    path = root / ref
    if not path.exists():
        return {}
    payload = _load_json(path)
    if not isinstance(payload, dict):
        return {}
    segments = payload.get("segments")
    if not isinstance(segments, list):
        return {}
    return {
        str(item.get("candidate_id") or item.get("segment_candidate_id") or item.get("segment_id")): item
        for item in segments
        if isinstance(item, dict)
        and (item.get("candidate_id") or item.get("segment_candidate_id") or item.get("segment_id"))
    }


def _segment_alignment_from_display_geometry(
    segment: dict[str, Any] | None,
    *,
    expected_route_distances_by_segment: list[list[float | None]] | None = None,
    route_edges: list[_RouteEdge],
    max_projection_distance_m: float,
    stats: "_Stats",
) -> dict[str, Any] | None:
    if not isinstance(segment, dict):
        return None
    coordinate_segments = _segment_coordinate_segments(segment)
    if not coordinate_segments:
        return None
    snapped_distances: list[float] = []
    for segment_index, coordinate_segment in enumerate(coordinate_segments):
        expected_distances = (
            expected_route_distances_by_segment[segment_index]
            if expected_route_distances_by_segment is not None
            and segment_index < len(expected_route_distances_by_segment)
            else None
        )
        for index, point in enumerate(coordinate_segment):
            aligned_point = _align_coordinate(
                point,
                item_id=f"segment-corridor.pt{index + 1:04d}",
                route_edges=route_edges,
                max_projection_distance_m=max_projection_distance_m,
                expected_route_distance_m=(
                    expected_distances[index]
                    if expected_distances is not None
                    and index < len(expected_distances)
                    else None
                ),
                stats=stats,
            )
            projection = aligned_point.get("overpass_projection")
            if (
                isinstance(projection, dict)
                and projection.get("status") == "snapped_to_overpass"
            ):
                route_distance = _as_float(projection.get("route_distance_m"))
                if isinstance(route_distance, float):
                    snapped_distances.append(route_distance)
    if len(snapped_distances) < 2:
        return None
    start_distance = snapped_distances[0]
    end_distance = snapped_distances[-1]
    if abs(end_distance - start_distance) <= 0.001:
        return None
    centerline = _slice_centerline(
        route_edges,
        start_distance_m=start_distance,
        end_distance_m=end_distance,
    )
    midpoint = _point_at_route_distance(route_edges, (start_distance + end_distance) / 2.0)
    if not centerline or midpoint is None:
        return None
    return {
        "start_distance_m": start_distance,
        "end_distance_m": end_distance,
        "route_distance_delta_m": abs(end_distance - start_distance),
        "centerline": centerline,
        "midpoint": midpoint,
        "snapped_display_point_count": len(snapped_distances),
    }


def _segment_source_distance_m(
    segment: dict[str, Any],
    display_segment: dict[str, Any] | None = None,
) -> float | None:
    for value in (
        segment.get("gpx_distance_m"),
        segment.get("distance_m"),
        (display_segment or {}).get("gpx_distance_m"),
        (display_segment or {}).get("distance_m"),
    ):
        distance = _as_float(value)
        if isinstance(distance, float) and distance > 0:
            return distance
    for candidate in (display_segment, segment):
        if isinstance(candidate, dict):
            distance = _source_display_path_length_m(candidate)
            if isinstance(distance, float) and distance > 0:
                return distance
    return None


def _segment_alignment_rejection(
    *,
    segment_id: str,
    source_distance_m: float | None,
    aligned_distance_m: float | None,
    aligned_point_count: int | None,
    projection_policy: str,
) -> dict[str, Any] | None:
    if not isinstance(source_distance_m, float) or source_distance_m <= 0:
        return None
    if not isinstance(aligned_distance_m, float) or aligned_distance_m <= 0:
        return None
    min_distance_m = source_distance_m * MIN_SEGMENT_ALIGNMENT_DISTANCE_RATIO
    if aligned_distance_m < min_distance_m:
        return {
            "status": "rejected_overpass_segment_path_compression_kept_gpx",
            "segment_id": segment_id,
            "source_distance_m": round(source_distance_m, 3),
            "aligned_distance_m": round(aligned_distance_m, 3),
            "min_allowed_aligned_distance_m": round(min_distance_m, 3),
            "min_alignment_distance_ratio": MIN_SEGMENT_ALIGNMENT_DISTANCE_RATIO,
            "aligned_display_point_count": aligned_point_count,
            "projection_policy": projection_policy,
        }
    limit_m = max(
        MIN_SEGMENT_ALIGNMENT_LIMIT_M,
        source_distance_m * MAX_SEGMENT_ALIGNMENT_DISTANCE_RATIO,
    )
    if aligned_distance_m <= limit_m:
        return None
    return {
        "status": "rejected_overpass_segment_path_inflation_kept_gpx",
        "segment_id": segment_id,
        "source_distance_m": round(source_distance_m, 3),
        "aligned_distance_m": round(aligned_distance_m, 3),
        "max_allowed_aligned_distance_m": round(limit_m, 3),
        "max_alignment_distance_ratio": MAX_SEGMENT_ALIGNMENT_DISTANCE_RATIO,
        "min_alignment_limit_m": MIN_SEGMENT_ALIGNMENT_LIMIT_M,
        "aligned_display_point_count": aligned_point_count,
        "projection_policy": projection_policy,
    }


def _display_alignment_rejection(
    *,
    segment_id: str,
    source_segment: dict[str, Any],
    aligned_points: list[dict[str, Any]],
    projection_policy: str,
) -> dict[str, Any] | None:
    source_distance_m = _segment_source_distance_m(source_segment)
    aligned_distance_m = _coordinate_path_length_m(aligned_points)
    return _segment_alignment_rejection(
        segment_id=segment_id,
        source_distance_m=source_distance_m,
        aligned_distance_m=aligned_distance_m,
        aligned_point_count=len(aligned_points),
        projection_policy=projection_policy,
    )


def _source_display_path_length_m(segment: dict[str, Any]) -> float | None:
    coordinate_segments = _segment_coordinate_segments(segment)
    if not coordinate_segments:
        return None
    total = 0.0
    found = False
    for coordinate_segment in coordinate_segments:
        points = _display_points(coordinate_segment)
        distance = _coordinate_path_length_m(points)
        if distance is not None:
            total += distance
            found = True
    return total if found else None


def _coordinate_path_length_m(points: list[dict[str, Any]]) -> float | None:
    if len(points) < 2:
        return None
    total = 0.0
    previous = _lat_lon_from_point(points[0])
    if previous is None:
        return None
    for point in points[1:]:
        current = _lat_lon_from_point(point)
        if current is None:
            return None
        total += haversine_m(previous[0], previous[1], current[0], current[1])
        previous = current
    return total


def _display_points(points: list[Any]) -> list[dict[str, Any]]:
    display_points: list[dict[str, Any]] = []
    for point in points:
        if isinstance(point, dict):
            lat_lon = _lat_lon_from_point(point)
            if lat_lon is not None:
                display_points.append({"lat": lat_lon[0], "lon": lat_lon[1]})
        elif isinstance(point, (list, tuple)) and len(point) >= 2:
            lon = _as_float(point[0])
            lat = _as_float(point[1])
            if isinstance(lat, float) and isinstance(lon, float):
                display_points.append({"lat": lat, "lon": lon})
    return display_points


def _segment_expected_route_distances_by_segment(
    segment: dict[str, Any] | None,
    *,
    from_id: str | None,
    to_id: str | None,
    route_distance_hints_m: dict[str, float],
) -> list[list[float | None]] | None:
    if not isinstance(segment, dict) or not from_id or not to_id:
        return None
    start_distance_m = route_distance_hints_m.get(from_id)
    end_distance_m = route_distance_hints_m.get(to_id)
    if not isinstance(start_distance_m, float) or not isinstance(end_distance_m, float):
        return None
    coordinate_segments = _segment_coordinate_segments(segment)
    if not coordinate_segments:
        return None

    normalized_segments = [_display_points(points) for points in coordinate_segments]
    normalized_segments = [points for points in normalized_segments if points]
    if not normalized_segments:
        return None

    positions_by_segment: list[list[float]] = []
    total_distance_m = 0.0
    previous: tuple[float, float] | None = None
    for points in normalized_segments:
        segment_positions: list[float] = []
        previous = None
        for point in points:
            current = _lat_lon_from_point(point)
            if current is None:
                segment_positions.append(total_distance_m)
                continue
            if previous is not None:
                total_distance_m += haversine_m(
                    previous[0],
                    previous[1],
                    current[0],
                    current[1],
                )
            segment_positions.append(total_distance_m)
            previous = current
        positions_by_segment.append(segment_positions)

    if total_distance_m <= 0:
        return [
            [start_distance_m for _ in segment_positions]
            for segment_positions in positions_by_segment
        ]

    route_span_m = end_distance_m - start_distance_m
    return [
        [
            start_distance_m + (position_m / total_distance_m) * route_span_m
            for position_m in segment_positions
        ]
        for segment_positions in positions_by_segment
    ]


def _lat_lon_from_point(point: dict[str, Any]) -> tuple[float, float] | None:
    lat = _as_float(point.get("lat"))
    lon = _as_float(point.get("lon"))
    if isinstance(lat, float) and isinstance(lon, float):
        return lat, lon
    coordinates = point.get("coordinates")
    if isinstance(coordinates, (list, tuple)) and len(coordinates) >= 2:
        lon = _as_float(coordinates[0])
        lat = _as_float(coordinates[1])
        if isinstance(lat, float) and isinstance(lon, float):
            return lat, lon
    return None


def _fallback_display_segment(
    segment: dict[str, Any],
    *,
    source_ref: str,
    max_projection_distance_m: float,
    rejection: dict[str, Any],
) -> dict[str, Any]:
    coordinate_segments = _segment_coordinate_segments(segment)
    normalized_segments = [
        _display_points(coordinate_segment)
        for coordinate_segment in coordinate_segments
    ]
    normalized_segments = [items for items in normalized_segments if items]
    flattened = [point for items in normalized_segments for point in items]
    return {
        **segment,
        "source_path": ALIGNED_SEGMENT_DISPLAY_REF,
        "coordinates": flattened,
        "coordinate_segments": normalized_segments,
        "display_point_count": len(flattened),
        "display_segment_count": len(normalized_segments),
        "overpass_alignment": {
            **rejection,
            "source_ref": source_ref,
            "max_projection_distance_m": max_projection_distance_m,
            "route_basis": "original_gpx_display_geometry",
        },
    }


def _snapped_overpass_point_count(points: list[dict[str, Any]]) -> int:
    count = 0
    for point in points:
        projection = point.get("overpass_projection")
        if isinstance(projection, dict) and projection.get("status") == "snapped_to_overpass":
            count += 1
    return count


def _segment_coordinate_segments(segment: dict[str, Any]) -> list[list[Any]]:
    coordinate_segments = segment.get("coordinate_segments")
    if isinstance(coordinate_segments, list) and coordinate_segments:
        return [
            coordinate_segment
            for coordinate_segment in coordinate_segments
            if isinstance(coordinate_segment, list)
        ]
    coordinates = segment.get("coordinates")
    if isinstance(coordinates, list) and coordinates:
        return [coordinates]
    return []


def _usable_checkpoint_projection(item: dict[str, Any]) -> dict[str, float] | None:
    projection = item.get("overpass_projection")
    if not isinstance(projection, dict):
        return None
    if projection.get("status") != "snapped_to_overpass":
        return None
    route_distance = _as_float(projection.get("route_distance_m"))
    if not isinstance(route_distance, float):
        return None
    return {"route_distance_m": route_distance}


def _projection_status(item: dict[str, Any]) -> str:
    projection = item.get("overpass_projection")
    if isinstance(projection, dict):
        return str(projection.get("status") or "unknown")
    return "missing_projection"


def _align_coordinate_segment(
    coordinate_segment: list[Any],
    *,
    route_edges: list[_RouteEdge],
    max_projection_distance_m: float,
    expected_route_distances_m: list[float | None] | None = None,
    stats: "_Stats",
) -> list[dict[str, Any]]:
    aligned_points = [
        _align_coordinate(
            point,
            item_id=f"display.pt{index + 1:04d}",
            route_edges=route_edges,
            max_projection_distance_m=max_projection_distance_m,
            expected_route_distance_m=(
                expected_route_distances_m[index]
                if expected_route_distances_m is not None
                and index < len(expected_route_distances_m)
                else None
            ),
            stats=stats,
        )
        for index, point in enumerate(coordinate_segment)
    ]
    if len(aligned_points) < 2:
        return aligned_points

    densified: list[dict[str, Any]] = []
    for start, end in zip(aligned_points, aligned_points[1:]):
        start_projection = start.get("overpass_projection")
        end_projection = end.get("overpass_projection")
        if (
            isinstance(start_projection, dict)
            and isinstance(end_projection, dict)
            and start_projection.get("status") == "snapped_to_overpass"
            and end_projection.get("status") == "snapped_to_overpass"
        ):
            start_distance = _as_float(start_projection.get("route_distance_m"))
            end_distance = _as_float(end_projection.get("route_distance_m"))
            if isinstance(start_distance, float) and isinstance(end_distance, float):
                sliced = _slice_centerline(
                    route_edges,
                    start_distance_m=start_distance,
                    end_distance_m=end_distance,
                )
                if sliced:
                    _extend_without_duplicate(densified, sliced)
                    continue
        _extend_without_duplicate(densified, [start, end])
    return densified


def _align_point_record(
    item: dict[str, Any],
    *,
    item_id: str,
    route_edges: list[_RouteEdge],
    max_projection_distance_m: float,
    expected_route_distance_m: float | None = None,
    stats: "_Stats",
) -> dict[str, Any]:
    aligned = dict(item)
    point = _record_lat_lon(item)
    if point is None:
        stats.missing_coordinate_count += 1
        aligned["overpass_projection"] = {
            "status": "missing_coordinate",
            "max_projection_distance_m": max_projection_distance_m,
        }
        return aligned
    lat, lon = point
    projection = _nearest_projection(
        lat,
        lon,
        route_edges,
        max_projection_distance_m=max_projection_distance_m,
        expected_route_distance_m=expected_route_distance_m,
    )
    if projection is None:
        stats.kept_gpx_point_count += 1
        aligned["overpass_projection"] = {
            "status": "kept_gpx_no_overpass_centerline",
            "max_projection_distance_m": max_projection_distance_m,
        }
        return aligned
    if projection["offset_m"] <= max_projection_distance_m:
        route_distance_delta_m = _as_float(projection.get("route_distance_delta_m"))
        if _route_distance_hint_mismatch(route_distance_delta_m):
            stats.kept_gpx_point_count += 1
            aligned["overpass_projection"] = {
                "status": "kept_gpx_route_distance_hint_mismatch",
                "item_id": item_id,
                "offset_m": round(projection["offset_m"], 3),
                "route_distance_m": round(projection["route_distance_m"], 3),
                "route_distance_hint_m": round(expected_route_distance_m, 3)
                if isinstance(expected_route_distance_m, float)
                else None,
                "route_distance_delta_m": round(route_distance_delta_m, 3)
                if isinstance(route_distance_delta_m, float)
                else None,
                "max_route_distance_delta_m": MAX_POINT_ROUTE_DISTANCE_DELTA_M,
                "max_projection_distance_m": max_projection_distance_m,
                "source_feature_id": projection["source_feature_id"],
            }
            return aligned
        stats.snapped_point_count += 1
        aligned["gpx_lat"] = lat
        aligned["gpx_lon"] = lon
        aligned["lat"] = projection["lat"]
        aligned["lon"] = projection["lon"]
        aligned["coordinates"] = [projection["lon"], projection["lat"]]
        geometry = aligned.get("geometry")
        if isinstance(geometry, dict) and geometry.get("type") == "Point":
            aligned["geometry"] = {**geometry, "coordinates": aligned["coordinates"]}
        aligned["route_distance_m"] = projection["route_distance_m"]
        aligned["overpass_projection"] = {
            "status": "snapped_to_overpass",
            "item_id": item_id,
            "offset_m": round(projection["offset_m"], 3),
            "route_distance_m": round(projection["route_distance_m"], 3),
            "route_distance_hint_m": round(expected_route_distance_m, 3)
            if isinstance(expected_route_distance_m, float)
            else None,
            "route_distance_delta_m": round(route_distance_delta_m, 3)
            if isinstance(route_distance_delta_m, float)
            else None,
            "max_projection_distance_m": max_projection_distance_m,
            "source_feature_id": projection["source_feature_id"],
        }
        return aligned

    stats.kept_gpx_point_count += 1
    aligned["overpass_projection"] = {
        "status": "kept_gpx_outside_overpass_tolerance",
        "item_id": item_id,
        "offset_m": round(projection["offset_m"], 3),
        "route_distance_m": round(projection["route_distance_m"], 3),
        "route_distance_hint_m": round(expected_route_distance_m, 3)
        if isinstance(expected_route_distance_m, float)
        else None,
        "max_projection_distance_m": max_projection_distance_m,
        "source_feature_id": projection["source_feature_id"],
    }
    return aligned


def _record_route_distance_hint(item: dict[str, Any]) -> float | None:
    for key in (
        "route_distance_m",
        "overpass_route_distance_m",
        "mileage_m",
    ):
        value = _as_float(item.get(key))
        if isinstance(value, float) and value >= 0:
            return value
    return None


def _route_distance_hint_mismatch(route_distance_delta_m: float | None) -> bool:
    return (
        isinstance(route_distance_delta_m, float)
        and route_distance_delta_m > MAX_POINT_ROUTE_DISTANCE_DELTA_M
    )


def _align_coordinate(
    point: Any,
    *,
    item_id: str,
    route_edges: list[_RouteEdge],
    max_projection_distance_m: float,
    expected_route_distance_m: float | None = None,
    stats: "_Stats",
) -> dict[str, Any]:
    if isinstance(point, dict):
        base = dict(point)
    elif isinstance(point, (list, tuple)) and len(point) >= 2:
        base = {"lon": point[0], "lat": point[1]}
    else:
        stats.missing_coordinate_count += 1
        return {
            "overpass_projection": {
                "status": "missing_coordinate",
                "max_projection_distance_m": max_projection_distance_m,
            }
        }
    return _align_point_record(
        base,
        item_id=item_id,
        route_edges=route_edges,
        max_projection_distance_m=max_projection_distance_m,
        expected_route_distance_m=expected_route_distance_m,
        stats=stats,
    )


def _route_edges_from_risk_ribbon(payload: dict[str, Any]) -> list[_RouteEdge]:
    edges: list[_RouteEdge] = []
    cumulative_distance = 0.0
    for feature_index, feature in enumerate(payload.get("features", [])):
        if not isinstance(feature, dict):
            continue
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict) or geometry.get("type") != "LineString":
            continue
        coordinates = [
            coord
            for coord in geometry.get("coordinates", [])
            if isinstance(coord, (list, tuple)) and len(coord) >= 2
        ]
        if len(coordinates) < 2:
            continue
        properties = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        feature_id = str(
            properties.get("segment_id")
            or properties.get("candidate_id")
            or f"risk_ribbon.feature.{feature_index:04d}"
        )
        distances = _feature_coordinate_distances(
            coordinates,
            start_distance=_as_float(properties.get("start_distance_m")),
            end_distance=_as_float(properties.get("end_distance_m")),
            fallback_start=cumulative_distance,
        )
        for coord_a, coord_b, distance_a, distance_b in zip(
            coordinates,
            coordinates[1:],
            distances,
            distances[1:],
        ):
            lon_a, lat_a = float(coord_a[0]), float(coord_a[1])
            lon_b, lat_b = float(coord_b[0]), float(coord_b[1])
            length = haversine_m(lat_a, lon_a, lat_b, lon_b)
            if length <= 0:
                continue
            edges.append(
                _RouteEdge(
                    start_lat=lat_a,
                    start_lon=lon_a,
                    end_lat=lat_b,
                    end_lon=lon_b,
                    start_distance_m=distance_a,
                    end_distance_m=distance_b,
                    length_m=length,
                    source_feature_id=feature_id,
                )
            )
        cumulative_distance = max(cumulative_distance, distances[-1])
    return edges


def _feature_coordinate_distances(
    coordinates: list[Any],
    *,
    start_distance: float | None,
    end_distance: float | None,
    fallback_start: float,
) -> list[float]:
    cumulative = [0.0]
    for start, end in zip(coordinates, coordinates[1:]):
        cumulative.append(
            cumulative[-1]
            + haversine_m(float(start[1]), float(start[0]), float(end[1]), float(end[0]))
        )
    total = max(cumulative[-1], 0.0)
    if isinstance(start_distance, float) and isinstance(end_distance, float) and end_distance >= start_distance:
        span = max(end_distance - start_distance, 0.0)
        if total > 0:
            return [start_distance + (value / total) * span for value in cumulative]
        return [start_distance for _ in cumulative]
    return [fallback_start + value for value in cumulative]


def _nearest_projection(
    lat: float,
    lon: float,
    edges: list[_RouteEdge],
    *,
    max_projection_distance_m: float | None = None,
    expected_route_distance_m: float | None = None,
) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    best_by_offset: dict[str, Any] | None = None
    lat_scale = 111_320.0
    lon_scale = 111_320.0 * math.cos(math.radians(lat))
    for edge_index, edge in enumerate(edges):
        ax = (edge.start_lon - lon) * lon_scale
        ay = (edge.start_lat - lat) * lat_scale
        bx = (edge.end_lon - lon) * lon_scale
        by = (edge.end_lat - lat) * lat_scale
        vx = bx - ax
        vy = by - ay
        length_sq = vx * vx + vy * vy
        if length_sq <= 0:
            continue
        t = max(0.0, min(1.0, -((ax * vx + ay * vy) / length_sq)))
        px = ax + vx * t
        py = ay + vy * t
        offset_m = math.hypot(px, py)
        projected_lat = edge.start_lat + (edge.end_lat - edge.start_lat) * t
        projected_lon = edge.start_lon + (edge.end_lon - edge.start_lon) * t
        route_distance = edge.start_distance_m + (
            edge.end_distance_m - edge.start_distance_m
        ) * t
        route_distance_delta_m = (
            abs(route_distance - expected_route_distance_m)
            if isinstance(expected_route_distance_m, float)
            else 0.0
        )
        candidate = {
            "lat": projected_lat,
            "lon": projected_lon,
            "offset_m": offset_m,
            "route_distance_m": route_distance,
            "route_distance_delta_m": route_distance_delta_m,
            "edge_index": edge_index,
            "source_feature_id": edge.source_feature_id,
        }
        candidates.append(candidate)
        if best_by_offset is None or offset_m < best_by_offset["offset_m"]:
            best_by_offset = candidate
    if best_by_offset is None:
        return None
    if not isinstance(expected_route_distance_m, float):
        return best_by_offset

    tie_tolerance_m = 50.0
    if isinstance(max_projection_distance_m, float):
        tie_tolerance_m = max(50.0, min(100.0, max_projection_distance_m * 0.1))
    comparable_candidates = [
        candidate
        for candidate in candidates
        if (
            candidate["offset_m"] <= best_by_offset["offset_m"] + tie_tolerance_m
            and (
                not isinstance(max_projection_distance_m, float)
                or candidate["offset_m"] <= max_projection_distance_m
            )
        )
    ]
    if not comparable_candidates:
        return best_by_offset
    return min(
        comparable_candidates,
        key=lambda candidate: (
            candidate["route_distance_delta_m"],
            candidate["offset_m"],
        ),
    )


def _slice_centerline(
    edges: list[_RouteEdge],
    *,
    start_distance_m: float,
    end_distance_m: float,
) -> list[dict[str, Any]]:
    reverse = end_distance_m < start_distance_m
    low, high = sorted((start_distance_m, end_distance_m))
    sliced: list[dict[str, Any]] = []
    for edge in edges:
        edge_low = min(edge.start_distance_m, edge.end_distance_m)
        edge_high = max(edge.start_distance_m, edge.end_distance_m)
        if edge_high < low or edge_low > high:
            continue
        segment_low = max(low, edge_low)
        segment_high = min(high, edge_high)
        if segment_high < segment_low:
            continue
        start_point = _point_on_edge(edge, segment_low)
        end_point = _point_on_edge(edge, segment_high)
        _extend_without_duplicate(sliced, [start_point, end_point])
    if reverse:
        sliced.reverse()
    return sliced


def _point_at_route_distance(
    edges: list[_RouteEdge],
    distance_m: float,
) -> dict[str, Any] | None:
    if not edges:
        return None
    best_edge = min(
        edges,
        key=lambda edge: (
            0.0
            if min(edge.start_distance_m, edge.end_distance_m)
            <= distance_m
            <= max(edge.start_distance_m, edge.end_distance_m)
            else min(
                abs(distance_m - edge.start_distance_m),
                abs(distance_m - edge.end_distance_m),
            )
        ),
    )
    clamped_distance = max(
        min(best_edge.start_distance_m, best_edge.end_distance_m),
        min(distance_m, max(best_edge.start_distance_m, best_edge.end_distance_m)),
    )
    return _point_on_edge(best_edge, clamped_distance)


def _point_on_edge(edge: _RouteEdge, distance_m: float) -> dict[str, Any]:
    span = edge.end_distance_m - edge.start_distance_m
    ratio = 0.0 if span == 0 else (distance_m - edge.start_distance_m) / span
    ratio = max(0.0, min(1.0, ratio))
    return {
        "lat": edge.start_lat + (edge.end_lat - edge.start_lat) * ratio,
        "lon": edge.start_lon + (edge.end_lon - edge.start_lon) * ratio,
        "route_distance_m": distance_m,
        "overpass_projection": {
            "status": "centerline_interpolated",
            "route_distance_m": round(distance_m, 3),
            "source_feature_id": edge.source_feature_id,
        },
    }


def _extend_without_duplicate(target: list[dict[str, Any]], points: list[dict[str, Any]]) -> None:
    for point in points:
        if target and _same_coordinate(target[-1], point):
            continue
        target.append(point)


def _same_coordinate(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return (
        abs(float(a.get("lat", 0.0)) - float(b.get("lat", 0.0))) < 1e-9
        and abs(float(a.get("lon", 0.0)) - float(b.get("lon", 0.0))) < 1e-9
    )


def _record_lat_lon(item: dict[str, Any]) -> tuple[float, float] | None:
    lat = _as_float(item.get("lat"))
    lon = _as_float(item.get("lon"))
    if isinstance(lat, float) and isinstance(lon, float):
        return lat, lon
    coordinates = item.get("coordinates")
    if isinstance(coordinates, (list, tuple)) and len(coordinates) >= 2:
        lon = _as_float(coordinates[0])
        lat = _as_float(coordinates[1])
        if isinstance(lat, float) and isinstance(lon, float):
            return lat, lon
    geometry = item.get("geometry")
    if isinstance(geometry, dict) and geometry.get("type") == "Point":
        return _record_lat_lon({"coordinates": geometry.get("coordinates")})
    return None


def _first_text(item: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


@dataclass
class _Stats:
    snapped_point_count: int = 0
    kept_gpx_point_count: int = 0
    missing_coordinate_count: int = 0
    rejected_segment_alignment_count: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "snapped_point_count": self.snapped_point_count,
            "kept_gpx_point_count": self.kept_gpx_point_count,
            "missing_coordinate_count": self.missing_coordinate_count,
            "rejected_segment_alignment_count": self.rejected_segment_alignment_count,
        }


def _status(status: str, **kwargs: Any) -> dict[str, Any]:
    return {"status": status, "boundary": _boundary(), **kwargs}


def _boundary() -> dict[str, bool]:
    return {
        "candidate_only": True,
        "display_geometry_only": True,
        "runtime_safety_truth": False,
        "phase1_runtime_mutation_allowed": False,
        "safety_api_called": False,
        "raw_gpx_embedded": False,
        "raw_overpass_embedded": False,
    }


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _update_project_refs(
    project_path: Path,
    outputs: dict[str, str],
    generated_at: str,
    max_projection_distance_m: float,
) -> None:
    project = _load_json(project_path) if project_path.exists() else {}
    project.update(outputs)
    project["overpass_route_alignment_updated_at"] = generated_at
    project["overpass_route_alignment_basis"] = (
        "overpass_with_gpx_normal_corridor_fallback_50m"
    )
    project["overpass_route_alignment_max_projection_distance_m"] = (
        max_projection_distance_m
    )
    _write_json(project_path, project)
