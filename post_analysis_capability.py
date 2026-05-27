from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from post_analysis_capability_models import (
    CapabilityArtifactFiles,
    CapabilityCapsuleArtifact,
    CapabilityDataQuality,
    CapabilityEdge,
    CapabilityNode,
    CapabilitySharePreviewArtifact,
    CapabilitySummary,
    PostAnalysisBoundary,
    RestDetectionPolicy,
    RouteTimeComparisonArtifact,
    RouteTimeComparisonSegment,
    SourceTrackRef,
)
from post_analysis_rest_detection import detect_rest_intervals, timed_route_points
from post_analysis_route_slicing import (
    CapabilityCheckpoint,
    CapabilitySegmentDefinition,
    load_checkpoint_definitions,
    slice_route_by_checkpoints,
)
from route_matching import GpxRoute, load_gpx_route


ROOT = Path(__file__).resolve().parent


def build_capability_artifacts(
    *,
    case_id: str,
    completed_track_gpx: Path,
    checkpoint_definitions_path: Path | None = None,
    pretrip_project_root: Path | None = None,
    route_family: str | None = None,
    output_dir: Path | None = None,
    rest_policy: RestDetectionPolicy | None = None,
    route_time_entries_path: Path | None = None,
    analysis_context_path: Path | None = None,
    export_capsule_path: Path | None = None,
    confirm_share_export: bool = False,
    root: Path = ROOT,
) -> CapabilityArtifactFiles:
    route = load_gpx_route(completed_track_gpx)
    if checkpoint_definitions_path is None:
        if pretrip_project_root is None:
            raise ValueError("checkpoint_definitions_path or pretrip_project_root is required")
        definitions, checkpoint_source_path = load_checkpoint_definitions_from_pretrip_project(
            pretrip_project_root
        )
    else:
        definitions = _load_json(checkpoint_definitions_path)
        checkpoint_source_path = checkpoint_definitions_path
    if route_time_entries_path is None and pretrip_project_root is not None:
        route_time_entries_path = resolve_route_time_entries_from_pretrip_project(
            pretrip_project_root
        )
    analysis_context = _load_json(analysis_context_path) if analysis_context_path else {}
    checkpoints, segments = load_checkpoint_definitions(definitions)
    policy = rest_policy or RestDetectionPolicy()
    timeline = build_capability_timeline(
        case_id=case_id,
        route_family=route_family or definitions.get("route_family") or case_id,
        route=route,
        track_source_path=completed_track_gpx,
        checkpoints=checkpoints,
        segments=segments,
        checkpoint_source_path=checkpoint_source_path,
        rest_policy=policy,
        analysis_context=analysis_context,
        root=root,
    )
    capsule = build_capability_capsule(timeline.model_dump(mode="json"))
    comparison = None
    if route_time_entries_path is not None:
        comparison = build_route_time_comparison(
            timeline.model_dump(mode="json"),
            _load_json(route_time_entries_path),
            route_time_entries_path=route_time_entries_path,
            root=root,
        )
    share_preview = build_capability_share_preview(capsule.model_dump(mode="json"))

    resolved_output_dir = output_dir or completed_track_gpx.parent
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    timeline_path = resolved_output_dir / "capability_timeline.json"
    capsule_path = resolved_output_dir / "capability_capsule.json"
    comparison_path = resolved_output_dir / "capability_route_time_comparison.json"
    csv_summary_path = resolved_output_dir / "capability_segments.csv"
    share_preview_path = resolved_output_dir / "capability_share_preview.json"
    _write_json(timeline_path, timeline.model_dump(mode="json"))
    _write_json(capsule_path, capsule.model_dump(mode="json"))
    if comparison is not None:
        _write_json(comparison_path, comparison.model_dump(mode="json"))
    _write_capability_csv(csv_summary_path, timeline.model_dump(mode="json"))
    _write_json(share_preview_path, share_preview.model_dump(mode="json"))
    exported_capsule_path = None
    if export_capsule_path is not None:
        export_capability_capsule(
            capsule.model_dump(mode="json"),
            export_capsule_path,
            confirm_export=confirm_share_export,
        )
        exported_capsule_path = str(export_capsule_path)
    return CapabilityArtifactFiles(
        timeline_path=str(timeline_path),
        capsule_path=str(capsule_path),
        comparison_path=str(comparison_path) if comparison is not None else None,
        csv_summary_path=str(csv_summary_path),
        share_preview_path=str(share_preview_path),
        exported_capsule_path=exported_capsule_path,
        timeline=timeline.model_dump(mode="json"),
        capsule=capsule.model_dump(mode="json"),
        comparison=comparison.model_dump(mode="json") if comparison is not None else None,
        share_preview=share_preview.model_dump(mode="json"),
    )


def load_checkpoint_definitions_from_pretrip_project(project_root: Path) -> tuple[dict[str, Any], Path]:
    project = _load_json(project_root / "project.json")
    for ref_key in ("compiled_mission_graph_reviewed_ref", "compiled_mission_graph_candidate_ref"):
        ref = project.get(ref_key)
        if ref and (project_root / ref).exists():
            path = project_root / ref
            return _load_json(path), path
    if project.get("checkpoint_candidates_ref") and project.get("segment_candidates_ref"):
        payload = {
            "case_id": project.get("project_id"),
            "route_family": project.get("project_id"),
            "checkpoints": _load_json(project_root / project["checkpoint_candidates_ref"]),
            "segments": _load_json(project_root / project["segment_candidates_ref"]),
        }
        return payload, project_root / "project.json"
    raise ValueError(f"pretrip project has no usable checkpoint/segment refs: {project_root}")


def resolve_route_time_entries_from_pretrip_project(project_root: Path) -> Path | None:
    project = _load_json(project_root / "project.json")
    ref = project.get("route_guide_timing_ref")
    if not ref:
        return None
    path = project_root / ref
    return path if path.exists() else None


def build_capability_timeline(
    *,
    case_id: str,
    route_family: str,
    route: GpxRoute,
    track_source_path: Path,
    checkpoints: list[CapabilityCheckpoint],
    segments: list[CapabilitySegmentDefinition],
    checkpoint_source_path: Path,
    rest_policy: RestDetectionPolicy,
    analysis_context: dict[str, Any] | None = None,
    root: Path = ROOT,
):
    from post_analysis_capability_models import CapabilityTimelineArtifact

    source_track = SourceTrackRef(
        source_id="completed_track",
        source_path=_relpath(track_source_path, root),
        sha256=_sha256(track_source_path),
    )
    checkpoint_source_ref = _relpath(checkpoint_source_path, root)
    rests = detect_rest_intervals(
        route.points,
        policy=rest_policy,
        source_ref=source_track.source_path,
    )
    route_slices = slice_route_by_checkpoints(route, checkpoints, segments)
    nodes = [
        CapabilityNode(
            node_id=checkpoint.checkpoint_id,
            label=checkpoint.name,
            lat=checkpoint.lat,
            lon=checkpoint.lon,
            source_refs=[checkpoint.source_ref, checkpoint_source_ref],
        )
        for checkpoint in checkpoints
    ]
    timed_points = timed_route_points(route.points)
    edges: list[CapabilityEdge] = []
    for route_slice in route_slices:
        start_offset = timed_points[route_slice.start_index].offset_s
        end_offset = timed_points[route_slice.end_index].offset_s
        elapsed_time_s = _duration_or_zero(start_offset, end_offset)
        rest_ids = [
            rest.rest_id
            for rest in rests
            if rest.start_index >= route_slice.start_index and rest.end_index <= route_slice.end_index
        ]
        rest_time_s = sum(rest.duration_s for rest in rests if rest.rest_id in rest_ids)
        moving_time_s = max(elapsed_time_s - rest_time_s, 0)
        edge_confidence, edge_limitations = _edge_confidence_and_limitations(
            route_slice=route_slice,
            timed_points=timed_points[route_slice.start_index : route_slice.end_index + 1],
            elapsed_time_s=elapsed_time_s,
            rest_policy=rest_policy,
        )
        edges.append(
            CapabilityEdge(
                edge_id=f"{route_slice.segment.from_checkpoint_id}_to_{route_slice.segment.to_checkpoint_id}",
                segment_id=route_slice.segment.segment_id,
                from_node_id=route_slice.segment.from_checkpoint_id,
                to_node_id=route_slice.segment.to_checkpoint_id,
                direction=route_slice.segment.direction,
                elapsed_time_s=elapsed_time_s,
                moving_time_s=moving_time_s,
                rest_time_s=rest_time_s,
                distance_m=route_slice.distance_m,
                ascent_m=route_slice.ascent_m,
                descent_m=route_slice.descent_m,
                rest_intervals=rest_ids,
                confidence=edge_confidence,
                source_refs=[
                    route_slice.segment.source_ref,
                    checkpoint_source_ref,
                    f"track_slice.{route_slice.start_index}-{route_slice.end_index}",
                    source_track.source_path,
                ],
                limitations=edge_limitations,
                terrain_context=route_slice.segment.terrain_context or {},
                risk_context=route_slice.segment.risk_context or {},
                guide_time_min=route_slice.segment.guide_time_min,
            )
        )
    summary = _timeline_summary(edges)
    data_quality = _timeline_data_quality(route.points, timed_points, route_slices, edges, rest_policy)
    return CapabilityTimelineArtifact(
        case_id=case_id,
        route_family=route_family,
        source_track=source_track,
        rest_detection_policy=rest_policy,
        nodes=nodes,
        edges=edges,
        rest_intervals=rests,
        summary=summary,
        data_quality=data_quality,
        analysis_context=analysis_context or {},
        boundary=PostAnalysisBoundary(),
    )


def build_capability_capsule(timeline: dict[str, Any]) -> CapabilityCapsuleArtifact:
    summary = timeline["summary"]
    confidence = _aggregate_confidence([edge["confidence"] for edge in timeline["edges"]])
    data_quality_limitations = timeline.get("data_quality", {}).get("limitations", [])
    return CapabilityCapsuleArtifact(
        case_id=timeline["case_id"],
        route_family=timeline["route_family"],
        moving_time_min=round(summary["moving_time_s"] / 60),
        elapsed_time_min=round(summary["elapsed_time_s"] / 60),
        rest_time_min=round(summary["rest_time_s"] / 60),
        distance_km=round(summary["distance_m"] / 1000, 2),
        ascent_m=summary.get("ascent_m"),
        descent_m=summary.get("descent_m"),
        ascent_m_per_hour_moving=summary.get("ascent_m_per_hour_moving"),
        descent_m_per_hour_moving=summary.get("descent_m_per_hour_moving"),
        moving_pace_min_per_km=summary.get("moving_pace_min_per_km"),
        confidence=confidence,
        limitations=[
            "rest detection is deterministic and rule-based",
            "weather, pack weight, and team waiting are not normalized",
            "capability capsule excludes raw GPX, exact timestamps, and incident details",
            *data_quality_limitations[:4],
        ],
    )


def build_route_time_comparison(
    timeline: dict[str, Any],
    route_time_entries: list[dict[str, Any]],
    *,
    route_time_entries_path: Path,
    root: Path = ROOT,
) -> RouteTimeComparisonArtifact:
    source_path = _relpath(route_time_entries_path, root)
    segments: list[RouteTimeComparisonSegment] = []
    for edge in timeline.get("edges", []):
        entry = _matching_route_time_entry(edge, route_time_entries)
        if entry is None:
            continue
        guide_time_min = _route_guide_time_min(edge, entry)
        if guide_time_min is None:
            continue
        user_moving_time_min = round(edge["moving_time_s"] / 60)
        user_elapsed_time_min = round(edge["elapsed_time_s"] / 60)
        source_refs = [source_path, *(entry.get("source_refs") or [])]
        segments.append(
            RouteTimeComparisonSegment(
                comparison_id=f"route_time.{edge['edge_id']}",
                edge_id=edge["edge_id"],
                segment_id=edge["segment_id"],
                route_time_source=str(entry.get("candidate_id") or entry.get("source_id") or source_path),
                guide_time_min=guide_time_min,
                user_moving_time_min=user_moving_time_min,
                user_elapsed_time_min=user_elapsed_time_min,
                delta_vs_guide_moving_min=user_moving_time_min - guide_time_min,
                confidence=_combine_confidence(edge["confidence"], entry.get("confidence", "medium")),
                source_refs=source_refs,
            )
        )
    deltas = [segment.delta_vs_guide_moving_min for segment in segments]
    summary = {
        "comparison_count": len(segments),
        "faster_than_guide_count": sum(1 for delta in deltas if delta < 0),
        "slower_than_guide_count": sum(1 for delta in deltas if delta > 0),
        "slowest_relative_delta_min": max(deltas) if deltas else None,
        "fastest_relative_delta_min": min(deltas) if deltas else None,
        "informational_only": True,
    }
    return RouteTimeComparisonArtifact(
        case_id=timeline["case_id"],
        route_family=timeline["route_family"],
        route_time_source=source_path,
        segments=segments,
        summary=summary,
    )


def build_capability_share_preview(capsule: dict[str, Any]) -> CapabilitySharePreviewArtifact:
    included_fields = {
        "route_family": capsule["route_family"],
        "source_scope": capsule["source_scope"],
        "moving_time_min": capsule["moving_time_min"],
        "elapsed_time_min": capsule["elapsed_time_min"],
        "rest_time_min": capsule["rest_time_min"],
        "distance_km": capsule["distance_km"],
        "ascent_m": capsule.get("ascent_m"),
        "descent_m": capsule.get("descent_m"),
        "moving_pace_min_per_km": capsule.get("moving_pace_min_per_km"),
        "confidence": capsule["confidence"],
        "limitations": capsule.get("limitations", []),
    }
    return CapabilitySharePreviewArtifact(
        case_id=capsule["case_id"],
        route_family=capsule["route_family"],
        included_fields=included_fields,
        excluded_fields={
            "raw_gpx": True,
            "exact_timestamps": True,
            "exact_coordinates": True,
            "incident_package_details": True,
            "private_notes": True,
            "home_work_traces": True,
        },
        limitations=[
            "export requires explicit confirmation",
            "shared capsule is advisory context, not a safety guarantee",
            *capsule.get("limitations", []),
        ],
    )


def export_capability_capsule(
    capsule: dict[str, Any],
    output_path: Path,
    *,
    confirm_export: bool,
) -> None:
    if not confirm_export:
        raise ValueError("capability capsule export requires --confirm-share-export")
    output = {
        **capsule,
        "export_confirmed": True,
        "export_boundary": {
            "raw_gpx_exported": False,
            "exact_timestamps_exported": False,
            "incident_details_exported": False,
            "runtime_safety_truth": False,
        },
    }
    _write_json(output_path, output)


def summarize_capability_artifacts(
    *,
    timeline_path: Path,
    capsule_path: Path,
    root: Path = ROOT,
) -> dict[str, Any]:
    timeline = _load_json(timeline_path)
    capsule = _load_json(capsule_path)
    share_preview_path = timeline_path.with_name("capability_share_preview.json")
    comparison_path = timeline_path.with_name("capability_route_time_comparison.json")
    share_preview = (
        _load_json(share_preview_path)
        if share_preview_path.exists()
        else build_capability_share_preview(capsule).model_dump(mode="json")
    )
    comparison = _load_json(comparison_path) if comparison_path.exists() else None
    return {
        "artifact_kind": "post_analysis_capability_summary",
        "case_id": timeline["case_id"],
        "route_family": timeline["route_family"],
        "source_id": "post_analysis_capability_timeline",
        "source_path": _relpath(timeline_path, root),
        "evidence_type": "post_analysis_capability",
        "timeline_source_path": _relpath(timeline_path, root),
        "capsule_source_path": _relpath(capsule_path, root),
        "edge_count": len(timeline.get("edges", [])),
        "rest_interval_count": len(timeline.get("rest_intervals", [])),
        "summary": timeline.get("summary", {}),
        "data_quality": timeline.get("data_quality", {}),
        "nodes": timeline.get("nodes", []),
        "share_preview": share_preview,
        "route_time_comparison": comparison,
        "capsule_preview": {
            "source_scope": capsule.get("source_scope"),
            "raw_track_shared": capsule.get("raw_track_shared"),
            "exact_timestamps_shared": capsule.get("exact_timestamps_shared"),
            "incident_details_shared": capsule.get("incident_details_shared"),
            "moving_time_min": capsule.get("moving_time_min"),
            "elapsed_time_min": capsule.get("elapsed_time_min"),
            "rest_time_min": capsule.get("rest_time_min"),
            "distance_km": capsule.get("distance_km"),
            "confidence": capsule.get("confidence"),
            "limitations": capsule.get("limitations", []),
        },
        "edges": [
            {
                "edge_id": edge["edge_id"],
                "segment_id": edge.get("segment_id"),
                "from_node_id": edge["from_node_id"],
                "to_node_id": edge["to_node_id"],
                "direction": edge.get("direction", "outbound"),
                "elapsed_time_s": edge["elapsed_time_s"],
                "moving_time_s": edge["moving_time_s"],
                "rest_time_s": edge["rest_time_s"],
                "distance_m": edge["distance_m"],
                "ascent_m": edge.get("ascent_m"),
                "descent_m": edge.get("descent_m"),
                "confidence": edge["confidence"],
                "source_refs": edge["source_refs"],
                "limitations": edge.get("limitations", []),
                "terrain_context": edge.get("terrain_context", {}),
                "risk_context": edge.get("risk_context", {}),
                "guide_time_min": edge.get("guide_time_min"),
                "evidence_type": "post_analysis_capability_segment",
                "source_id": edge["edge_id"],
                "source_path": _relpath(timeline_path, root),
            }
            for edge in timeline.get("edges", [])
        ],
        "boundary": timeline.get("boundary", {}),
    }


def _timeline_summary(edges: list[CapabilityEdge]) -> CapabilitySummary:
    elapsed_time_s = sum(edge.elapsed_time_s for edge in edges)
    moving_time_s = sum(edge.moving_time_s for edge in edges)
    rest_time_s = sum(edge.rest_time_s for edge in edges)
    distance_m = round(sum(edge.distance_m for edge in edges), 2)
    ascent_values = [edge.ascent_m for edge in edges if edge.ascent_m is not None]
    descent_values = [edge.descent_m for edge in edges if edge.descent_m is not None]
    ascent_m = round(sum(ascent_values), 2) if ascent_values else None
    descent_m = round(sum(descent_values), 2) if descent_values else None
    moving_hours = moving_time_s / 3600 if moving_time_s else 0.0
    distance_km = distance_m / 1000 if distance_m else 0.0
    return CapabilitySummary(
        elapsed_time_s=elapsed_time_s,
        moving_time_s=moving_time_s,
        rest_time_s=rest_time_s,
        moving_ratio=round(moving_time_s / elapsed_time_s, 3) if elapsed_time_s else 0.0,
        distance_m=distance_m,
        ascent_m=ascent_m,
        descent_m=descent_m,
        moving_pace_min_per_km=round((moving_time_s / 60) / distance_km, 2) if distance_km else None,
        ascent_m_per_hour_moving=round(ascent_m / moving_hours, 2) if ascent_m is not None and moving_hours else None,
        descent_m_per_hour_moving=round(descent_m / moving_hours, 2) if descent_m is not None and moving_hours else None,
    )


def _edge_confidence_and_limitations(
    *,
    route_slice,
    timed_points,
    elapsed_time_s: int,
    rest_policy: RestDetectionPolicy,
) -> tuple[str, list[str]]:
    limitations = list(route_slice.limitations)
    values = [route_slice.confidence]
    if elapsed_time_s == 0:
        limitations.append("segment elapsed time could not be computed from timestamps")
        values.append("medium")
    if any(point.offset_s is None for point in timed_points):
        limitations.append("segment has one or more missing timestamp offsets")
        values.append("medium")
    if _has_suspicious_timestamps(timed_points):
        limitations.append("segment has non-increasing timestamps")
        values.append("medium")
    if _gps_gap_count(timed_points, rest_policy.max_sample_gap_s):
        limitations.append("segment has a large timestamp gap")
        values.append("medium")
    if (
        route_slice.distance_deviation_ratio is not None
        and route_slice.distance_deviation_ratio
        > rest_policy.max_segment_distance_deviation_ratio
    ):
        limitations.append("completed route distance deviates from planned/reference segment")
        values.append("low" if route_slice.distance_deviation_ratio > 0.75 else "medium")
    return _combine_confidence(*values), sorted(set(limitations))


def _timeline_data_quality(
    points,
    timed_points,
    route_slices,
    edges: list[CapabilityEdge],
    rest_policy: RestDetectionPolicy,
) -> CapabilityDataQuality:
    missing_timestamp_count = sum(1 for point in points if point.timestamp is None)
    suspicious_timestamp_count = _suspicious_timestamp_count(timed_points)
    gps_gap_count = _gps_gap_count(timed_points, rest_policy.max_sample_gap_s)
    ambiguous_checkpoint_count = sum(
        1
        for route_slice in route_slices
        for match in (route_slice.from_match, route_slice.to_match)
        if match.candidate_cluster_count > 1
    )
    low_point_segment_count = sum(1 for route_slice in route_slices if len(route_slice.points) < 2)
    route_deviation_count = sum(
        1
        for route_slice in route_slices
        if route_slice.distance_deviation_ratio is not None
        and route_slice.distance_deviation_ratio
        > rest_policy.max_segment_distance_deviation_ratio
    )
    low_confidence_edge_count = sum(1 for edge in edges if edge.confidence == "low")
    limitations: list[str] = []
    if missing_timestamp_count:
        limitations.append("one or more completed track points are missing timestamps")
    if suspicious_timestamp_count:
        limitations.append("one or more completed track timestamp steps are non-increasing")
    if gps_gap_count:
        limitations.append("one or more completed track timestamp gaps exceed policy")
    if ambiguous_checkpoint_count:
        limitations.append("one or more checkpoint matches have multiple plausible clusters")
    if low_point_segment_count:
        limitations.append("one or more segments have fewer than two track points")
    if route_deviation_count:
        limitations.append("one or more completed segments deviate from planned/reference distance")
    return CapabilityDataQuality(
        missing_timestamp_count=missing_timestamp_count,
        suspicious_timestamp_count=suspicious_timestamp_count,
        gps_gap_count=gps_gap_count,
        ambiguous_checkpoint_count=ambiguous_checkpoint_count,
        low_point_segment_count=low_point_segment_count,
        route_deviation_count=route_deviation_count,
        low_confidence_edge_count=low_confidence_edge_count,
        limitations=limitations,
    )


def _duration_or_zero(start_offset: int | None, end_offset: int | None) -> int:
    if start_offset is None or end_offset is None:
        return 0
    return max(end_offset - start_offset, 0)


def _has_suspicious_timestamps(timed_points) -> bool:
    return _suspicious_timestamp_count(timed_points) > 0


def _suspicious_timestamp_count(timed_points) -> int:
    count = 0
    for previous, current in zip(timed_points, timed_points[1:], strict=False):
        if previous.offset_s is None or current.offset_s is None:
            continue
        if current.offset_s <= previous.offset_s:
            count += 1
    return count


def _gps_gap_count(timed_points, max_sample_gap_s: int) -> int:
    if max_sample_gap_s <= 0:
        return 0
    count = 0
    for previous, current in zip(timed_points, timed_points[1:], strict=False):
        if previous.offset_s is None or current.offset_s is None:
            continue
        if current.offset_s - previous.offset_s > max_sample_gap_s:
            count += 1
    return count


def _matching_route_time_entry(
    edge: dict[str, Any],
    entries: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for entry in entries:
        if entry.get("segment_candidate_id") in {edge.get("segment_id"), edge.get("edge_id")}:
            return entry
        if entry.get("edge_id") == edge.get("edge_id"):
            return entry
        if (
            entry.get("from_node_id") == edge.get("from_node_id")
            and entry.get("to_node_id") == edge.get("to_node_id")
        ):
            return entry
    return None


def _route_guide_time_min(edge: dict[str, Any], entry: dict[str, Any]) -> int | None:
    if edge.get("direction") == "return" and entry.get("route_guide_return_time_minutes") is not None:
        return int(entry["route_guide_return_time_minutes"])
    for key in ("route_guide_segment_time_minutes", "guide_time_min"):
        if entry.get(key) is not None:
            return int(entry[key])
    return None


def _combine_confidence(*values: str) -> str:
    if "low" in values:
        return "low"
    if "medium" in values:
        return "medium"
    return "high"


def _aggregate_confidence(values: list[str]) -> str:
    if not values:
        return "low"
    return _combine_confidence(*values)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_capability_csv(path: Path, timeline: dict[str, Any]) -> None:
    headers = [
        "edge_id",
        "segment_id",
        "from_node_id",
        "to_node_id",
        "direction",
        "elapsed_time_s",
        "moving_time_s",
        "rest_time_s",
        "distance_m",
        "ascent_m",
        "descent_m",
        "confidence",
    ]
    rows = [",".join(headers)]
    for edge in timeline.get("edges", []):
        rows.append(",".join(_csv_cell(edge.get(header)) for header in headers))
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _csv_cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    if any(char in text for char in [",", '"', "\n"]):
        return '"' + text.replace('"', '""') + '"'
    return text


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build post-analysis capability timeline artifacts.")
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--completed-track-gpx", required=True, type=Path)
    parser.add_argument("--checkpoint-definitions", type=Path)
    parser.add_argument("--pretrip-project-root", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--route-family")
    parser.add_argument("--route-time-entries", type=Path)
    parser.add_argument("--analysis-context", type=Path)
    parser.add_argument("--export-capsule-path", type=Path)
    parser.add_argument("--confirm-share-export", action="store_true")
    parser.add_argument("--rest-speed-threshold-kmh", type=float, default=0.5)
    parser.add_argument("--rest-radius-m", type=float, default=20.0)
    parser.add_argument("--min-rest-duration-s", type=int, default=180)
    parser.add_argument("--max-sample-gap-s", type=int, default=900)
    parser.add_argument("--max-segment-distance-deviation-ratio", type=float, default=0.35)
    args = parser.parse_args(argv)
    if args.checkpoint_definitions is None and args.pretrip_project_root is None:
        parser.error("--checkpoint-definitions or --pretrip-project-root is required")

    files = build_capability_artifacts(
        case_id=args.case_id,
        completed_track_gpx=args.completed_track_gpx,
        checkpoint_definitions_path=args.checkpoint_definitions,
        pretrip_project_root=args.pretrip_project_root,
        output_dir=args.output_dir,
        route_family=args.route_family,
        route_time_entries_path=args.route_time_entries,
        analysis_context_path=args.analysis_context,
        export_capsule_path=args.export_capsule_path,
        confirm_share_export=args.confirm_share_export,
        rest_policy=RestDetectionPolicy(
            rest_speed_threshold_kmh=args.rest_speed_threshold_kmh,
            rest_radius_m=args.rest_radius_m,
            min_rest_duration_s=args.min_rest_duration_s,
            max_sample_gap_s=args.max_sample_gap_s,
            max_segment_distance_deviation_ratio=args.max_segment_distance_deviation_ratio,
        ),
    )
    print(json.dumps(files.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
