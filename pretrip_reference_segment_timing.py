from __future__ import annotations

import argparse
import heapq
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


DEFAULT_SOURCE_INDEX_REF = "sources/historical_gpx_source_index.json"
DEFAULT_ROUTE_GUIDE_TIMING_REF = "candidates/route_guide_timing.json"
DEFAULT_OUTPUT_REF = "outputs/reference_segment_timing.json"
CHECKPOINT_MATCH_RADIUS_M = 200.0
CHECKPOINT_CLUSTER_RADIUS_M = 350.0
MAX_VISIT_GAP_MINUTES = 45


@dataclass(frozen=True)
class ReferenceSegmentSpec:
    segment_id: str
    from_key: str
    to_key: str
    from_name: str
    to_name: str
    max_duration_minutes: float
    distance_filter_km: tuple[float, float]


CHILAI_NANHUA_REFERENCE_SEGMENTS = (
    ReferenceSegmentSpec(
        "ref_segment_timing.chilai_nanhua.trailhead_to_yunhai",
        "trailhead",
        "yunhai",
        "屯原登山口",
        "雲海保線所",
        360.0,
        (3.5, 6.2),
    ),
    ReferenceSegmentSpec(
        "ref_segment_timing.chilai_nanhua.yunhai_to_lodge",
        "yunhai",
        "lodge",
        "雲海保線所",
        "天池山莊",
        540.0,
        (7.0, 11.8),
    ),
    ReferenceSegmentSpec(
        "ref_segment_timing.chilai_nanhua.lodge_to_junction",
        "lodge",
        "junction",
        "天池山莊",
        "天池岔路",
        180.0,
        (0.5, 2.1),
    ),
    ReferenceSegmentSpec(
        "ref_segment_timing.chilai_nanhua.junction_to_qilai_south",
        "junction",
        "qilai_south",
        "天池岔路",
        "奇萊南峰",
        240.0,
        (1.2, 3.0),
    ),
    ReferenceSegmentSpec(
        "ref_segment_timing.chilai_nanhua.qilai_south_to_junction",
        "qilai_south",
        "junction",
        "奇萊南峰",
        "天池岔路",
        180.0,
        (1.2, 3.0),
    ),
    ReferenceSegmentSpec(
        "ref_segment_timing.chilai_nanhua.junction_to_nanhua",
        "junction",
        "nanhua",
        "天池岔路",
        "南華山",
        180.0,
        (1.0, 2.6),
    ),
    ReferenceSegmentSpec(
        "ref_segment_timing.chilai_nanhua.nanhua_to_lodge",
        "nanhua",
        "lodge",
        "南華山",
        "天池山莊",
        300.0,
        (1.8, 4.0),
    ),
    ReferenceSegmentSpec(
        "ref_segment_timing.chilai_nanhua.lodge_to_trailhead",
        "lodge",
        "trailhead",
        "天池山莊",
        "屯原登山口",
        600.0,
        (10.0, 17.0),
    ),
)


CHECKPOINT_LABELS = {
    "trailhead": "屯原登山口",
    "yunhai": "雲海保線所",
    "lodge": "天池山莊",
    "junction": "天池岔路",
    "qilai_south": "奇萊南峰",
    "nanhua": "南華山",
}


def build_reference_segment_timing(
    project_root: Path,
    *,
    project_id: str | None = None,
    source_index_ref: str = DEFAULT_SOURCE_INDEX_REF,
    route_guide_timing_ref: str = DEFAULT_ROUTE_GUIDE_TIMING_REF,
    target_segments: tuple[ReferenceSegmentSpec, ...] = CHILAI_NANHUA_REFERENCE_SEGMENTS,
) -> dict[str, Any]:
    project_root = Path(project_root)
    source_index_path = project_root / source_index_ref
    guide_path = project_root / route_guide_timing_ref
    source_index = _load_json(source_index_path) if source_index_path.exists() else {}
    source_records = [
        item for item in source_index.get("sources", []) if isinstance(item, dict)
    ]
    project_id = project_id or str(source_index.get("project_id") or project_root.name)
    source_index_sha256 = _file_sha256(source_index_path) if source_index_path.exists() else None
    guide_candidates = _load_json(guide_path) if guide_path.exists() else []
    guide_graph = _guide_graph(guide_candidates if isinstance(guide_candidates, list) else [])

    existing_sources = [
        source for source in source_records if Path(str(source.get("original_path") or "")).exists()
    ]
    canonical_checkpoints, checkpoint_quality = _canonical_checkpoints(existing_sources)

    measurements: dict[str, list[dict[str, Any]]] = {
        spec.segment_id: [] for spec in target_segments
    }
    rejected_by_distance: dict[str, list[dict[str, Any]]] = {
        spec.segment_id: [] for spec in target_segments
    }
    boundary_crossed: dict[str, int] = {spec.segment_id: 0 for spec in target_segments}
    timed_source_count = 0

    if all(key in canonical_checkpoints for key in CHECKPOINT_LABELS):
        for source in existing_sources:
            source_path = Path(str(source.get("original_path") or ""))
            track_parts = _track_parts(source_path)
            timed_point_count = sum(len(part) for part in track_parts)
            if timed_point_count < 2:
                continue
            timed_source_count += 1
            flat_points = [
                {**point, "part_index": part_index}
                for part_index, part in enumerate(track_parts)
                for point in part
            ]
            visits = {
                key: _checkpoint_visits(flat_points, canonical_checkpoints[key])
                for key in CHECKPOINT_LABELS
            }
            for spec in target_segments:
                result = _measurement_for_source_segment(
                    source,
                    flat_points,
                    visits.get(spec.from_key, []),
                    visits.get(spec.to_key, []),
                    spec,
                    source_index_ref=source_index_ref,
                )
                if result is None:
                    continue
                if result["accepted"]:
                    measurements[spec.segment_id].append(result["measurement"])
                else:
                    rejected_by_distance[spec.segment_id].append(result["measurement"])
                if result["measurement"].get("track_segment_boundary_crossed"):
                    boundary_crossed[spec.segment_id] += 1

    segment_summaries = [
        _segment_summary(
            spec,
            measurements[spec.segment_id],
            rejected_by_distance[spec.segment_id],
            boundary_crossed[spec.segment_id],
            guide_graph,
        )
        for spec in target_segments
    ]
    usable_segment_count = sum(1 for item in segment_summaries if item["sample_count"] > 0)
    measurement_count = sum(item["sample_count"] for item in segment_summaries)

    return {
        "artifact_kind": "pretrip_reference_segment_timing",
        "schema_version": "pretrip_reference_segment_timing.v1",
        "project_id": project_id,
        "status": "ready" if usable_segment_count else "missing_source_or_unmatched_checkpoints",
        "source_provider": "historical_gpx_source_index",
        "source_path": source_index_ref,
        "sha256": source_index_sha256,
        "route_guide_timing_source_path": route_guide_timing_ref if guide_path.exists() else "",
        "route_guide_timing_sha256": _file_sha256(guide_path) if guide_path.exists() else None,
        "evidence_type": "pretrip_reference_segment_timing",
        "counts": {
            "source_file_count": len(source_records),
            "existing_source_file_count": len(existing_sources),
            "timed_source_file_count": timed_source_count,
            "checkpoint_count": len(canonical_checkpoints),
            "segment_count": len(segment_summaries),
            "usable_segment_count": usable_segment_count,
            "measurement_count": measurement_count,
            "distance_rejected_measurement_count": sum(
                len(items) for items in rejected_by_distance.values()
            ),
            "track_boundary_crossed_measurement_count": sum(boundary_crossed.values()),
        },
        "method": {
            "checkpoint_source": "gpx_waypoint_name_cluster",
            "checkpoint_cluster_radius_m": CHECKPOINT_CLUSTER_RADIUS_M,
            "checkpoint_match_radius_m": CHECKPOINT_MATCH_RADIUS_M,
            "visit_split_gap_minutes": MAX_VISIT_GAP_MINUTES,
            "duration_basis": "nearest_trackpoint_to_checkpoint_centroid",
            "distance_basis": "trackline_distance_between_checkpoint_passages",
            "distance_filter_applied": True,
            "track_segment_boundary_crossing_allowed": True,
            "track_segment_boundary_crossing_is_timing_only": True,
            "guide_time_basis": "route_guide_timing_shortest_path",
        },
        "checkpoint_match_quality": checkpoint_quality,
        "segments": segment_summaries,
        "data_quality": {
            "source_file_count": len(source_records),
            "existing_source_file_count": len(existing_sources),
            "timed_source_file_count": timed_source_count,
            "usable_segment_count": usable_segment_count,
            "measurement_count": measurement_count,
            "distance_filter_applied": True,
            "outlier_policy": "reject_measurements_outside_segment_distance_filter",
            "live_network_calls_made": False,
        },
        "privacy": {
            "aggregate_only": True,
            "raw_gpx_embedded_in_json": False,
            "raw_gpx_xml_embedded": False,
            "coordinates_embedded": False,
            "precise_timestamps_embedded": False,
            "source_original_paths_embedded": False,
            "source_filenames_embedded": True,
        },
        "boundary": {
            "candidate_only": True,
            "pretrip_candidate_evidence_only": True,
            "medical_diagnosis": False,
            "phase1_runtime_safety_truth": False,
            "runtime_safety_truth": False,
            "phase1_runtime_mutation_allowed": False,
            "phase2_brain_writeback_allowed": False,
            "safety_api_called": False,
            "historical_gpx_is_actual_user_track": False,
            "guide_time_is_authoritative_truth": False,
        },
        "notes": [
            "Reference segment timing is derived from historical GPX trackpoint times and route-guide candidates.",
            "Durations are aggregate pretrip evidence for comparison only; raw GPX, coordinates, and precise timestamps are not embedded.",
        ],
    }


def write_reference_segment_timing(
    project_root: Path,
    *,
    output_ref: str = DEFAULT_OUTPUT_REF,
    **kwargs: Any,
) -> Path:
    project_root = Path(project_root)
    payload = build_reference_segment_timing(project_root, **kwargs)
    output_path = project_root / output_ref
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


def _measurement_for_source_segment(
    source: dict[str, Any],
    points: list[dict[str, Any]],
    from_visits: list[dict[str, Any]],
    to_visits: list[dict[str, Any]],
    spec: ReferenceSegmentSpec,
    *,
    source_index_ref: str,
) -> dict[str, Any] | None:
    rejected: list[dict[str, Any]] = []
    for start_visit in from_visits:
        for end_visit in to_visits:
            if end_visit["start_index"] <= start_visit["end_index"]:
                continue
            minutes = (
                end_visit["closest_time"] - start_visit["closest_time"]
            ).total_seconds() / 60.0
            if minutes < 2 or minutes > spec.max_duration_minutes:
                continue
            distance_km = _trackline_distance_km(
                points,
                start_visit["closest_index"],
                end_visit["closest_index"],
            )
            crosses_boundary = _trackline_crosses_part_boundary(
                points,
                start_visit["closest_index"],
                end_visit["closest_index"],
            )
            record = _measurement_record(
                source,
                spec,
                source_index_ref=source_index_ref,
                minutes=minutes,
                track_distance_km=distance_km,
                track_segment_boundary_crossed=crosses_boundary,
                reject_reason=None,
            )
            low, high = spec.distance_filter_km
            if distance_km is not None and low <= distance_km <= high:
                return {"accepted": True, "measurement": record}
            record["reject_reason"] = "outside_segment_distance_filter"
            rejected.append(record)
    if rejected:
        reason = str(rejected[0].get("reject_reason") or "outside_segment_distance_filter")
        return {"accepted": False, "reject_reason": reason, "measurement": rejected[0]}
    return None


def _measurement_record(
    source: dict[str, Any],
    spec: ReferenceSegmentSpec,
    *,
    source_index_ref: str,
    minutes: float | None,
    track_distance_km: float | None,
    track_segment_boundary_crossed: bool,
    reject_reason: str | None,
) -> dict[str, Any]:
    source_id = str(source.get("source_id") or "unknown_source")
    measurement_id = f"{spec.segment_id}.{_safe_id(source_id)}"
    source_path = f"{source_index_ref}#{source_id}"
    identity = {
        "measurement_id": measurement_id,
        "source_path": source_path,
        "sha256": source.get("sha256"),
        "segment_id": spec.segment_id,
        "duration_minutes": _round1(minutes) if minutes is not None else None,
        "track_distance_km": _round2(track_distance_km) if track_distance_km is not None else None,
    }
    return {
        "measurement_id": measurement_id,
        "source_provider": source.get("provider") or "operator_supplied_local_file",
        "source_id": source_id,
        "source_path": source_path,
        "sha256": source.get("sha256"),
        "source_role": source.get("role") or source.get("route_role"),
        "source_filename": source.get("original_filename"),
        "source_refs": [source_path, source_id, str(source.get("sha256") or "")],
        "source_attribution": [
            {
                "source_kind": "historical_gpx_reference_segment_timing",
                "source_ref": source_path,
                "source_candidate_id": source_id,
                "source_sha256": source.get("sha256"),
                "source_role": source.get("role") or source.get("route_role"),
                "confidence": "medium",
                "stale_risk": "medium",
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        ],
        "confidence": "medium",
        "stale_risk": "medium",
        "review_state": "projection_only",
        "candidate_only": True,
        "runtime_safety_truth": False,
        "extractor_version": "pretrip_reference_segment_timing.v1",
        "pydantic_ai_prompt_version": "not_applicable_deterministic_reference_segment_timing.v1",
        "model_output_sha256": _stable_hash(identity),
        "model_output_summary": (
            "Aggregate historical GPX segment timing sample; source path/hash "
            "metadata only, not runtime safety truth."
        ),
        "duration_minutes": _round1(minutes) if minutes is not None else None,
        "track_distance_km": _round2(track_distance_km) if track_distance_km is not None else None,
        "track_segment_boundary_crossed": track_segment_boundary_crossed,
        "reject_reason": reject_reason,
        "privacy": {
            "raw_gpx_embedded_in_json": False,
            "coordinates_embedded": False,
            "precise_timestamps_embedded": False,
            "source_original_path_embedded": False,
        },
    }


def _segment_summary(
    spec: ReferenceSegmentSpec,
    measurements: list[dict[str, Any]],
    distance_rejects: list[dict[str, Any]],
    boundary_crossed_count: int,
    guide_graph: dict[str, list[tuple[str, int, str]]],
) -> dict[str, Any]:
    durations = [
        float(item["duration_minutes"])
        for item in measurements
        if item.get("duration_minutes") is not None
    ]
    distances = [
        float(item["track_distance_km"])
        for item in measurements
        if item.get("track_distance_km") is not None
    ]
    guide = _guide_time_comparison(
        spec,
        durations,
        guide_graph,
    )
    return {
        "segment_id": spec.segment_id,
        "label": f"{spec.from_name} -> {spec.to_name}",
        "from_node_name": spec.from_name,
        "to_node_name": spec.to_name,
        "sample_count": len(measurements),
        "source_count": len({item.get("source_id") for item in measurements}),
        "duration_minutes": {
            "min": _round1(min(durations)) if durations else None,
            "max": _round1(max(durations)) if durations else None,
            "p50": _round1(_percentile(durations, 0.50)) if durations else None,
            "p75": _round1(_percentile(durations, 0.75)) if durations else None,
        },
        "track_distance_km": {
            "min": _round2(min(distances)) if distances else None,
            "max": _round2(max(distances)) if distances else None,
        },
        "distance_filter_km": {
            "min": spec.distance_filter_km[0],
            "max": spec.distance_filter_km[1],
        },
        "max_duration_filter_minutes": spec.max_duration_minutes,
        "route_guide_comparison": guide,
        "measurements": sorted(
            measurements,
            key=lambda item: (
                float(item["duration_minutes"])
                if item.get("duration_minutes") is not None
                else math.inf
            ),
        ),
        "rejected_summary": {
            "distance_rejected_count": len(distance_rejects),
            "track_boundary_crossed_count": boundary_crossed_count,
            "distance_rejected_samples": sorted(
                distance_rejects,
                key=lambda item: (
                    float(item["duration_minutes"])
                    if item.get("duration_minutes") is not None
                    else math.inf
                ),
            )[:5],
        },
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "phase1_runtime_mutation_allowed": False,
            "historical_gpx_is_actual_user_track": False,
        },
    }


def _guide_time_comparison(
    spec: ReferenceSegmentSpec,
    durations: list[float],
    guide_graph: dict[str, list[tuple[str, int, str]]],
) -> dict[str, Any]:
    guide_path = _shortest_guide_path(
        _normalize_node_name(spec.from_name),
        _normalize_node_name(spec.to_name),
        guide_graph,
    )
    if guide_path is None:
        return {
            "status": "missing_guide_time",
            "guide_duration_minutes": None,
            "guide_path_candidate_ids": [],
        }
    guide_minutes, candidate_ids = guide_path
    comparison = {
        "status": "available",
        "guide_duration_minutes": guide_minutes,
        "guide_path_candidate_ids": candidate_ids,
    }
    if durations:
        comparison["delta_minutes"] = {
            "min_minus_guide": _round1(min(durations) - guide_minutes),
            "max_minus_guide": _round1(max(durations) - guide_minutes),
            "p50_minus_guide": _round1(_percentile(durations, 0.50) - guide_minutes),
            "p75_minus_guide": _round1(_percentile(durations, 0.75) - guide_minutes),
        }
    return comparison


def _guide_graph(candidates: list[dict[str, Any]]) -> dict[str, list[tuple[str, int, str]]]:
    graph: dict[str, list[tuple[str, int, str]]] = {}
    for candidate in candidates:
        from_name = _normalize_node_name(candidate.get("from_node_name"))
        to_name = _normalize_node_name(candidate.get("to_node_name"))
        candidate_id = str(candidate.get("candidate_id") or "")
        if not from_name or not to_name or not candidate_id:
            continue
        forward = _first_int(
            candidate.get("route_guide_segment_time_minutes"),
            candidate.get("route_guide_ascent_time_minutes"),
            candidate.get("route_guide_descent_time_minutes"),
        )
        reverse = _first_int(
            candidate.get("route_guide_return_time_minutes"),
            candidate.get("route_guide_descent_time_minutes"),
            candidate.get("route_guide_ascent_time_minutes"),
        )
        if forward is not None:
            graph.setdefault(from_name, []).append((to_name, forward, candidate_id))
        if reverse is not None:
            graph.setdefault(to_name, []).append((from_name, reverse, candidate_id))
    return graph


def _shortest_guide_path(
    start: str,
    end: str,
    graph: dict[str, list[tuple[str, int, str]]],
) -> tuple[int, list[str]] | None:
    if not start or not end:
        return None
    queue: list[tuple[int, str, list[str]]] = [(0, start, [])]
    best: dict[str, int] = {}
    while queue:
        minutes, node, path = heapq.heappop(queue)
        if node == end:
            return minutes, path
        if minutes >= best.get(node, math.inf):
            continue
        best[node] = minutes
        if len(path) >= 5:
            continue
        for next_node, edge_minutes, candidate_id in graph.get(node, []):
            heapq.heappush(queue, (minutes + edge_minutes, next_node, [*path, candidate_id]))
    return None


def _canonical_checkpoints(
    sources: list[dict[str, Any]],
) -> tuple[dict[str, tuple[float, float]], dict[str, Any]]:
    classified: dict[str, list[tuple[float, float, str, str]]] = {
        key: [] for key in CHECKPOINT_LABELS
    }
    for source in sources:
        path = Path(str(source.get("original_path") or ""))
        if not path.exists():
            continue
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError:
            continue
        for waypoint in root.findall(".//{*}wpt"):
            name = (waypoint.findtext("{*}name") or "").strip()
            key = _classify_waypoint_name(name)
            if not key:
                continue
            try:
                lat = float(waypoint.attrib["lat"])
                lon = float(waypoint.attrib["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            classified[key].append((lat, lon, name, str(source.get("source_id") or "")))

    canonical: dict[str, tuple[float, float]] = {}
    quality: dict[str, Any] = {}
    for key, rows in classified.items():
        clusters = _clusters(rows)
        main_cluster = clusters[0] if clusters else []
        if main_cluster:
            canonical[key] = (
                _median([item[0] for item in main_cluster]),
                _median([item[1] for item in main_cluster]),
            )
        quality[key] = {
            "label": CHECKPOINT_LABELS[key],
            "classified_waypoint_count": len(rows),
            "cluster_count": len(clusters),
            "main_cluster_waypoint_count": len(main_cluster),
            "main_cluster_source_count": len({item[3] for item in main_cluster}),
            "coordinates_embedded": False,
        }
    return canonical, quality


def _clusters(rows: list[tuple[float, float, str, str]]) -> list[list[tuple[float, float, str, str]]]:
    clusters: list[list[tuple[float, float, str, str]]] = []
    for row in rows:
        for cluster in clusters:
            center_lat = sum(item[0] for item in cluster) / len(cluster)
            center_lon = sum(item[1] for item in cluster) / len(cluster)
            if _haversine_m(row[0], row[1], center_lat, center_lon) <= CHECKPOINT_CLUSTER_RADIUS_M:
                cluster.append(row)
                break
        else:
            clusters.append([row])
    clusters.sort(key=len, reverse=True)
    return clusters


def _checkpoint_visits(
    points: list[dict[str, Any]],
    checkpoint: tuple[float, float],
) -> list[dict[str, Any]]:
    visits: list[dict[str, Any]] = []
    active: dict[str, Any] | None = None
    previous_inside_time: datetime | None = None
    max_gap = timedelta(minutes=MAX_VISIT_GAP_MINUTES)
    for index, point in enumerate(points):
        distance_m = _haversine_m(
            float(point["lat"]),
            float(point["lon"]),
            checkpoint[0],
            checkpoint[1],
        )
        inside = distance_m <= CHECKPOINT_MATCH_RADIUS_M
        point_time = point["time"]
        if inside:
            if (
                active is None
                or (
                    previous_inside_time is not None
                    and point_time - previous_inside_time > max_gap
                )
            ):
                if active is not None:
                    visits.append(active)
                active = {
                    "start_index": index,
                    "end_index": index,
                    "part_index": point["part_index"],
                    "closest_index": index,
                    "closest_time": point_time,
                    "closest_distance_m": distance_m,
                }
            else:
                active["end_index"] = index
                if distance_m < active["closest_distance_m"]:
                    active["closest_distance_m"] = distance_m
                    active["closest_index"] = index
                    active["closest_time"] = point_time
            previous_inside_time = point_time
        else:
            if active is not None:
                visits.append(active)
            active = None
            previous_inside_time = None
    if active is not None:
        visits.append(active)
    return visits


def _track_parts(path: Path) -> list[list[dict[str, Any]]]:
    root = ET.parse(path).getroot()
    parts: list[list[dict[str, Any]]] = []
    for segment in root.findall(".//{*}trkseg"):
        points: list[dict[str, Any]] = []
        for trkpt in segment.findall("{*}trkpt"):
            point_time = _parse_time(trkpt.findtext("{*}time"))
            if point_time is None:
                continue
            try:
                lat = float(trkpt.attrib["lat"])
                lon = float(trkpt.attrib["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            points.append({"lat": lat, "lon": lon, "time": point_time})
        if points:
            parts.append(points)
    return parts


def _trackline_distance_km(
    points: list[dict[str, Any]],
    start_index: int,
    end_index: int,
) -> float | None:
    if end_index < start_index:
        return None
    distance_m = 0.0
    for index in range(start_index + 1, end_index + 1):
        previous = points[index - 1]
        current = points[index]
        distance_m += _haversine_m(
            float(previous["lat"]),
            float(previous["lon"]),
            float(current["lat"]),
            float(current["lon"]),
        )
    return distance_m / 1000.0


def _trackline_crosses_part_boundary(
    points: list[dict[str, Any]],
    start_index: int,
    end_index: int,
) -> bool:
    if end_index < start_index:
        return False
    for index in range(start_index + 1, end_index + 1):
        if points[index - 1]["part_index"] != points[index]["part_index"]:
            return True
    return False


def _classify_waypoint_name(name: str) -> str | None:
    normalized = _compact_text(name)
    if not normalized:
        return None
    if (
        "屯原登山口" in normalized
        or "屯原登口" in normalized
        or "屯原入口" in normalized
    ):
        return "trailhead"
    if "雲海保線所" in normalized or "雲海保線" in normalized:
        return "yunhai"
    if "天池山莊" in normalized:
        return "lodge"
    if (
        "天池叉路口" in normalized
        or "天池岔路口" in normalized
        or "天池三叉路" in normalized
        or "天池三岔" in normalized
    ):
        return "junction"
    if (
        "奇萊南峰" in normalized
        or "奇來南峰" in normalized
        or "奇萊主山南峰" in normalized
    ) and not any(token in normalized for token in ("下營", "營地", "登山口", "溪谷", "1.1K")):
        return "qilai_south"
    if (
        "南華山" in normalized
        or re.search(r"\d+-?南華$", normalized)
        or "021-南華" in normalized
    ) and not any(token in normalized for token in ("叉路", "岔", "步道")):
        return "nanhua"
    return None


def _normalize_node_name(name: Any) -> str:
    normalized = _compact_text(str(name or ""))
    replacements = {
        "天池岔路口": "天池岔路",
        "天池叉路口": "天池岔路",
        "天池三叉路": "天池岔路",
        "天池三岔": "天池岔路",
        "奇來南峰": "奇萊南峰",
        "奇萊主山南峰": "奇萊南峰",
        "南華山(能高北峰)": "南華山",
        "屯原登口": "屯原登山口",
        "屯原入口": "屯原登山口",
    }
    return replacements.get(normalized, normalized)


def _compact_text(value: str) -> str:
    return re.sub(r"\s+", "", value.strip())


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_m = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * radius_m * math.asin(math.sqrt(a))


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _percentile(values: list[float], q: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[int(position)]
    lower_value = sorted_values[lower]
    upper_value = sorted_values[upper]
    return lower_value + (upper_value - lower_value) * (position - lower)


def _first_int(*values: Any) -> int | None:
    for value in values:
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _median(values: list[float]) -> float:
    return _percentile(values, 0.50)


def _round1(value: float | None) -> float | None:
    return round(value, 1) if value is not None else None


def _round2(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _file_sha256(path: Path) -> str:
    return hashlib_sha256(path.read_bytes())


def _stable_hash(value: Any) -> str:
    return hashlib_sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    )


def hashlib_sha256(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def _main() -> None:
    parser = argparse.ArgumentParser(
        description="Build aggregate reference segment timing evidence from historical GPX sources.",
    )
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--project-id")
    parser.add_argument("--source-index-ref", default=DEFAULT_SOURCE_INDEX_REF)
    parser.add_argument("--route-guide-timing-ref", default=DEFAULT_ROUTE_GUIDE_TIMING_REF)
    parser.add_argument("--output-ref", default=DEFAULT_OUTPUT_REF)
    args = parser.parse_args()
    output_path = write_reference_segment_timing(
        Path(args.project_root),
        output_ref=args.output_ref,
        project_id=args.project_id,
        source_index_ref=args.source_index_ref,
        route_guide_timing_ref=args.route_guide_timing_ref,
    )
    print(str(output_path))


if __name__ == "__main__":
    _main()
