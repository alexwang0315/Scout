from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
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
    SegmentTerrainProfile,
    SourceTrackRef,
    TerrainProfileSample,
    TerrainProfileSummary,
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
    resolved_output_dir = output_dir or completed_track_gpx.parent
    profile_output_dir = resolved_output_dir / "terrain_profiles"
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
        terrain_profile_output_dir=profile_output_dir,
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
    terrain_profile_output_dir: Path | None = None,
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
        if route_slice.traversal_status == "unreached":
            elapsed_time_s = 0
            rest_ids = []
            rest_time_s = 0
            moving_time_s = 0
            edge_confidence = "low"
            edge_limitations = sorted(set(route_slice.limitations))
            distance_m = 0.0
            ascent_m = None
            descent_m = None
            terrain_profile = None
        else:
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
            distance_m = route_slice.distance_m
            ascent_m = route_slice.ascent_m
            descent_m = route_slice.descent_m
            terrain_profile = _build_segment_terrain_profile(
                route_slice=route_slice,
                edge_id=f"{route_slice.segment.from_checkpoint_id}_to_{route_slice.segment.to_checkpoint_id}",
                output_dir=terrain_profile_output_dir,
            )
        edges.append(
            CapabilityEdge(
                edge_id=f"{route_slice.segment.from_checkpoint_id}_to_{route_slice.segment.to_checkpoint_id}",
                segment_id=route_slice.segment.segment_id,
                from_node_id=route_slice.segment.from_checkpoint_id,
                to_node_id=route_slice.segment.to_checkpoint_id,
                direction=route_slice.segment.direction,
                traversal_status=route_slice.traversal_status,
                elapsed_time_s=elapsed_time_s,
                moving_time_s=moving_time_s,
                rest_time_s=rest_time_s,
                distance_m=distance_m,
                ascent_m=ascent_m,
                descent_m=descent_m,
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
                terrain_profile=terrain_profile,
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
        if edge.get("traversal_status") == "unreached":
            continue
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
    edges = [
        {
            "edge_id": edge["edge_id"],
            "segment_id": edge.get("segment_id"),
            "from_node_id": edge["from_node_id"],
            "to_node_id": edge["to_node_id"],
            "direction": edge.get("direction", "outbound"),
            "traversal_status": edge.get("traversal_status", "traversed"),
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
            "terrain_profile": edge.get("terrain_profile"),
            "guide_time_min": edge.get("guide_time_min"),
            "evidence_type": "post_analysis_capability_segment",
            "source_id": edge["edge_id"],
            "source_path": _relpath(timeline_path, root),
        }
        for edge in timeline.get("edges", [])
    ]
    observed_edges = [
        edge for edge in edges if edge.get("traversal_status") != "unreached"
    ]
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
        "observed_edge_count": len(observed_edges),
        "planned_segment_count": timeline.get("summary", {}).get("planned_segment_count"),
        "traversed_segment_count": timeline.get("summary", {}).get("traversed_segment_count"),
        "partial_segment_count": timeline.get("summary", {}).get("partial_segment_count"),
        "unreached_segment_count": timeline.get("summary", {}).get("unreached_segment_count"),
        "completion_status": timeline.get("summary", {}).get("completion_status"),
        "turnaround_edge_id": timeline.get("summary", {}).get("turnaround_edge_id"),
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
        "edges": edges,
        "observed_edges": observed_edges,
        "boundary": timeline.get("boundary", {}),
    }


def _timeline_summary(edges: list[CapabilityEdge]) -> CapabilitySummary:
    accounted_edges = [
        edge for edge in edges if edge.traversal_status in {"traversed", "partial"}
    ]
    elapsed_time_s = sum(edge.elapsed_time_s for edge in accounted_edges)
    moving_time_s = sum(edge.moving_time_s for edge in accounted_edges)
    rest_time_s = sum(edge.rest_time_s for edge in accounted_edges)
    distance_m = round(sum(edge.distance_m for edge in accounted_edges), 2)
    ascent_values = [edge.ascent_m for edge in accounted_edges if edge.ascent_m is not None]
    descent_values = [edge.descent_m for edge in accounted_edges if edge.descent_m is not None]
    ascent_m = round(sum(ascent_values), 2) if ascent_values else None
    descent_m = round(sum(descent_values), 2) if descent_values else None
    moving_hours = moving_time_s / 3600 if moving_time_s else 0.0
    distance_km = distance_m / 1000 if distance_m else 0.0
    partial_segment_count = sum(1 for edge in edges if edge.traversal_status == "partial")
    unreached_segment_count = sum(1 for edge in edges if edge.traversal_status == "unreached")
    traversed_segment_count = sum(1 for edge in edges if edge.traversal_status == "traversed")
    turnaround_edge_id = next(
        (edge.edge_id for edge in edges if edge.traversal_status == "partial"),
        None,
    )
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
        planned_segment_count=len(edges),
        traversed_segment_count=traversed_segment_count,
        partial_segment_count=partial_segment_count,
        unreached_segment_count=unreached_segment_count,
        completion_status="partial" if unreached_segment_count or partial_segment_count else "complete",
        turnaround_edge_id=turnaround_edge_id,
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
    partial_segment_count = sum(1 for edge in edges if edge.traversal_status == "partial")
    unreached_segment_count = sum(1 for edge in edges if edge.traversal_status == "unreached")
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
    if partial_segment_count:
        limitations.append("completed track appears to turn around before one planned segment")
    if unreached_segment_count:
        limitations.append("one or more planned segments were not reached by the completed track")
    return CapabilityDataQuality(
        missing_timestamp_count=missing_timestamp_count,
        suspicious_timestamp_count=suspicious_timestamp_count,
        gps_gap_count=gps_gap_count,
        ambiguous_checkpoint_count=ambiguous_checkpoint_count,
        low_point_segment_count=low_point_segment_count,
        route_deviation_count=route_deviation_count,
        low_confidence_edge_count=low_confidence_edge_count,
        partial_segment_count=partial_segment_count,
        unreached_segment_count=unreached_segment_count,
        limitations=limitations,
    )


def _build_segment_terrain_profile(
    *,
    route_slice,
    edge_id: str,
    output_dir: Path | None,
    sample_distance_m: float = 20.0,
) -> SegmentTerrainProfile | None:
    samples = _terrain_profile_samples(
        route_slice.points,
        risk_score=_extract_risk_score(route_slice.segment.risk_context or {}),
        sample_distance_m=sample_distance_m,
    )
    if len(samples) < 2:
        return None

    summary = _terrain_profile_summary(samples)
    if output_dir is None:
        profile_svg_ref = f"terrain_profiles/{_safe_artifact_name(edge_id)}.svg"
    else:
        output_dir.mkdir(parents=True, exist_ok=True)
        profile_name = f"{_safe_artifact_name(edge_id)}.svg"
        _write_terrain_profile_svg(
            output_dir / profile_name,
            edge_id=edge_id,
            samples=samples,
            summary=summary,
        )
        profile_svg_ref = f"terrain_profiles/{profile_name}"

    return SegmentTerrainProfile(
        source="completed_track_elevation",
        sample_distance_m=sample_distance_m,
        profile_svg_ref=profile_svg_ref,
        samples=samples,
        summary=summary,
    )


def _terrain_profile_samples(
    points,
    *,
    risk_score: float | None,
    sample_distance_m: float,
) -> list[TerrainProfileSample]:
    elevated = [point for point in points if point.elevation_m is not None]
    if len(elevated) < 2:
        return []

    samples = []
    previous_sample_offset: float | None = None
    segment_start_progress = elevated[0].progress_m
    for index, point in enumerate(elevated):
        offset_m = max(point.progress_m - segment_start_progress, 0.0)
        is_first = index == 0
        is_last = index == len(elevated) - 1
        due_by_distance = (
            previous_sample_offset is None
            or offset_m - previous_sample_offset >= sample_distance_m
        )
        if not (is_first or is_last or due_by_distance):
            continue
        slope_deg = _local_slope_deg(elevated, index)
        samples.append(
            TerrainProfileSample(
                offset_m=round(offset_m, 2),
                elevation_m=round(float(point.elevation_m), 2),
                slope_deg=round(slope_deg, 2) if slope_deg is not None else None,
                risk_score=risk_score,
            )
        )
        previous_sample_offset = offset_m

    return samples


def _local_slope_deg(points, index: int) -> float | None:
    if len(points) < 2:
        return None
    previous_index = max(index - 1, 0)
    next_index = min(index + 1, len(points) - 1)
    if previous_index == next_index:
        return None
    previous = points[previous_index]
    current = points[index]
    next_point = points[next_index]
    left_distance = max(current.progress_m - previous.progress_m, 0.0)
    right_distance = max(next_point.progress_m - current.progress_m, 0.0)
    if right_distance > 0:
        horizontal_m = right_distance
        vertical_m = abs(float(next_point.elevation_m) - float(current.elevation_m))
    elif left_distance > 0:
        horizontal_m = left_distance
        vertical_m = abs(float(current.elevation_m) - float(previous.elevation_m))
    else:
        return None
    return math.degrees(math.atan(vertical_m / horizontal_m))


def _terrain_profile_summary(samples: list[TerrainProfileSample]) -> TerrainProfileSummary:
    elevations = [sample.elevation_m for sample in samples]
    ascent = 0.0
    descent = 0.0
    for previous, current in zip(samples, samples[1:], strict=False):
        delta = current.elevation_m - previous.elevation_m
        if delta >= 0:
            ascent += delta
        else:
            descent += abs(delta)
    slopes = [sample.slope_deg for sample in samples if sample.slope_deg is not None]
    slope_band_counts = {key: 0 for key in ("0_10", "10_20", "20_30", "30_40", "40_50", "50_plus")}
    for slope in slopes:
        slope_band_counts[_slope_band_key(slope)] += 1
    max_slope = max(slopes) if slopes else None
    mean_slope = sum(slopes) / len(slopes) if slopes else None
    return TerrainProfileSummary(
        min_elevation_m=round(min(elevations), 2),
        max_elevation_m=round(max(elevations), 2),
        ascent_m=round(ascent, 2),
        descent_m=round(descent, 2),
        max_slope_deg=round(max_slope, 2) if max_slope is not None else None,
        mean_slope_deg=round(mean_slope, 2) if mean_slope is not None else None,
        slope_band_counts=slope_band_counts,
        terrain_difficulty_band=_terrain_difficulty_band(
            max_slope_deg=max_slope,
            ascent_m=ascent,
            descent_m=descent,
            distance_m=max(sample.offset_m for sample in samples),
        ),
    )


def _slope_band_key(slope_deg: float) -> str:
    if slope_deg < 10:
        return "0_10"
    if slope_deg < 20:
        return "10_20"
    if slope_deg < 30:
        return "20_30"
    if slope_deg < 40:
        return "30_40"
    if slope_deg < 50:
        return "40_50"
    return "50_plus"


def _terrain_difficulty_band(
    *,
    max_slope_deg: float | None,
    ascent_m: float,
    descent_m: float,
    distance_m: float,
) -> str:
    if max_slope_deg is None or distance_m <= 0:
        return "unknown"
    ascent_per_100m = ascent_m / distance_m * 100.0
    descent_per_100m = descent_m / distance_m * 100.0
    if max_slope_deg >= 50 or ascent_per_100m >= 30 or descent_per_100m >= 45:
        return "severe"
    if max_slope_deg >= 35 or ascent_per_100m >= 20 or descent_per_100m >= 30:
        return "strained"
    if max_slope_deg >= 20 or ascent_per_100m >= 10 or descent_per_100m >= 18:
        return "watch"
    return "normal"


def _write_terrain_profile_svg(
    path: Path,
    *,
    edge_id: str,
    samples: list[TerrainProfileSample],
    summary: TerrainProfileSummary,
) -> None:
    width = 220
    height = 56
    pad_x = 10
    pad_top = 8
    pad_bottom = 14
    plot_w = width - pad_x * 2
    plot_h = height - pad_top - pad_bottom
    max_offset = max(sample.offset_m for sample in samples) or 1.0
    min_ele = summary.min_elevation_m
    max_ele = summary.max_elevation_m
    ele_range = max(max_ele - min_ele, 1.0)

    coords: list[tuple[float, float]] = []
    for sample in samples:
        x = pad_x + (sample.offset_m / max_offset) * plot_w
        y = pad_top + (1.0 - ((sample.elevation_m - min_ele) / ele_range)) * plot_h
        coords.append((x, y))

    bands = []
    for index, sample in enumerate(samples[1:], start=1):
        previous_x = coords[index - 1][0]
        current_x = coords[index][0]
        band = _slope_band_key(sample.slope_deg or 0.0)
        bands.append(
            f'<rect x="{previous_x:.1f}" y="{pad_top}" width="{max(current_x - previous_x, 1):.1f}" '
            f'height="{plot_h}" fill="{_slope_band_color(band)}" opacity="0.28"/>'
        )

    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    label = _svg_text(edge_id[:34])
    difficulty = _svg_text(summary.terrain_difficulty_band)
    path.write_text(
        "\n".join(
            [
                '<svg xmlns="http://www.w3.org/2000/svg" width="220" height="56" viewBox="0 0 220 56" role="img">',
                f"<title>{label} terrain profile</title>",
                '<rect x="0" y="0" width="220" height="56" fill="#171b20"/>',
                *bands,
                f'<polyline points="{polyline}" fill="none" stroke="#f4f7fb" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>',
                f'<text x="10" y="52" fill="#9aa4b2" font-size="9">{difficulty}</text>',
                f'<text x="210" y="52" text-anchor="end" fill="#9aa4b2" font-size="9">{min_ele:.0f}-{max_ele:.0f}m</text>',
                "</svg>",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _slope_band_color(band: str) -> str:
    return {
        "0_10": "#9ee6a0",
        "10_20": "#c6e86b",
        "20_30": "#f2d84b",
        "30_40": "#f6a044",
        "40_50": "#e46e3f",
        "50_plus": "#d84b4b",
    }.get(band, "#6f7a85")


def _extract_risk_score(risk_context: dict[str, Any]) -> float | None:
    for key in ("risk_score", "risk_score_mean", "pretrip_risk_score", "risk"):
        value = risk_context.get(key)
        if isinstance(value, (int, float)):
            return round(float(value), 4)
    return None


def _safe_artifact_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return cleaned.strip("._") or "terrain_profile"


def _svg_text(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
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
        "traversal_status",
        "elapsed_time_s",
        "moving_time_s",
        "rest_time_s",
        "distance_m",
        "ascent_m",
        "descent_m",
        "terrain_difficulty_band",
        "confidence",
    ]
    rows = [",".join(headers)]
    for edge in timeline.get("edges", []):
        rows.append(
            ",".join(
                _csv_cell(_capability_csv_value(edge, header))
                for header in headers
            )
        )
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _capability_csv_value(edge: dict[str, Any], header: str) -> Any:
    if header == "terrain_difficulty_band":
        return (edge.get("terrain_profile") or {}).get("summary", {}).get(
            "terrain_difficulty_band"
        )
    return edge.get(header)


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
