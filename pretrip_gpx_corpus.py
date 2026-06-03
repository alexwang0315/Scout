from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pretrip_models import PreTripCheckpointCandidate
from pretrip_models import PreTripSegmentCandidate
from pretrip_route_comparison import _bbox_comparison, _route_entry
from pretrip_source_ingest import sha256_file, summarize_gpx
from route_matching import RoutePoint, load_gpx_route


TW_MAP_GPX_PRIMARY_FILENAME = "能高安東軍縱走.gpx.gpx"
TW_MAP_GPX_GOLDEN_ROUTE_FILENAME = TW_MAP_GPX_PRIMARY_FILENAME


@dataclass(frozen=True)
class _IndexedDisplayPoint:
    source_index: int
    point: RoutePoint


def list_reference_gpx_paths(
    corpus_dir: Path | str,
    *,
    primary_filename: str = TW_MAP_GPX_PRIMARY_FILENAME,
) -> tuple[Path, list[Path]]:
    directory = Path(corpus_dir).expanduser()
    primary = directory / primary_filename
    if not primary.exists():
        raise FileNotFoundError(f"primary GPX not found: {primary}")
    references = sorted(path for path in directory.glob("*.gpx") if path.name != primary_filename)
    return primary, references


def build_reference_track_summary(
    *,
    project_id: str,
    primary_gpx_path: Path | str,
    reference_gpx_paths: list[Path] | tuple[Path, ...],
    primary_artifact_id: str = "artifact.gpx.chilai_nanhua_day1",
) -> dict[str, Any]:
    primary_path = Path(primary_gpx_path).expanduser()
    primary_summary = summarize_gpx(primary_path, primary_artifact_id)
    references: list[dict[str, Any]] = []

    for index, reference_path in enumerate(sorted(Path(path).expanduser() for path in reference_gpx_paths), start=1):
        artifact_id = f"{primary_artifact_id}.reference.{index:03d}"
        reference_summary = summarize_gpx(reference_path, artifact_id)
        references.append(
            {
                "reference_id": artifact_id,
                "role": "reference_track",
                "source_use_treatment": {
                    "reference_track_only": True,
                    "authoritative_for_mission": False,
                    "compiled_into_mission_graph": False,
                    "runtime_safety_truth": False,
                    "raw_source_versioned": False,
                    "derived_summary_only": True,
                },
                "route": _route_entry(reference_path, reference_summary),
                "bbox_comparison": _bbox_comparison(primary_summary.bbox_wgs84, reference_summary.bbox_wgs84),
                "distance_delta_m": round(reference_summary.distance_m - primary_summary.distance_m, 2),
                "point_count_delta": reference_summary.point_count - primary_summary.point_count,
            }
        )

    return {
        "artifact_kind": "pretrip_reference_track_summary",
        "schema_version": "0.1.0",
        "project_id": project_id,
        "route_role": "golden_route",
        "golden_route": {
            **_route_entry(primary_path, primary_summary),
            "role": "golden_route_reference",
            "pretrip_actual_user_track": False,
            "runtime_safety_truth": False,
        },
        "primary_route": _route_entry(primary_path, primary_summary),
        "reference_track_count": len(references),
        "reference_tracks": references,
        "boundary": {
            "candidate_evidence_only": True,
            "golden_route_is_reference_evidence": True,
            "pretrip_actual_user_track_available": False,
            "unwalked_route_sections_require_manual_waypoints": True,
            "unwalked_route_sections_require_danger_review": True,
            "raw_gpx_copied_to_repo": False,
            "reference_tracks_authoritative": False,
            "compiled_into_mission_graph": False,
            "runtime_safety_truth": False,
            "live_network_required": False,
        },
        "notes": [
            "reference tracks（參考軌跡）只作為 pre-trip evidence，不是 runtime safety truth（現場安全真相）。",
            "原始 GPX 保留在本機來源資料夾；repo fixture 只保存可重算的 metadata、hash、bbox、距離與點數。",
            "Golden route（出發前選定的主參考路線）不是使用者已走過的軌跡；平安返回後才由 post-analysis 匯入 actual track 取代。",
            "未曾發生的路徑或叉路必須由手動畫航點產生，並觸發 danger review（危險審查）而不是自動成為安全路線。",
        ],
    }


def build_checkpoint_event_candidates(
    *,
    project_id: str,
    route_gpx_path: Path | str,
    checkpoint_candidates: list[PreTripCheckpointCandidate],
    route_artifact_id: str = "artifact.gpx.chilai_nanhua_day1",
) -> dict[str, Any]:
    route_path = Path(route_gpx_path).expanduser()
    route = load_gpx_route(route_path)
    events: list[dict[str, Any]] = []

    for sequence, checkpoint in enumerate(checkpoint_candidates, start=1):
        if checkpoint.route_point_index is None:
            continue
        if checkpoint.route_point_index >= len(route.points):
            continue
        point = route.points[checkpoint.route_point_index]
        events.append(
            {
                "event_id": f"event.{project_id}.{checkpoint.candidate_id}",
                "event_type": "checkpoint_candidate_reached",
                "sequence": sequence,
                "checkpoint_candidate_id": checkpoint.candidate_id,
                "checkpoint_type": checkpoint.checkpoint_type,
                "label": checkpoint.label,
                "route_point_index": checkpoint.route_point_index,
                "progress_m": round(point.progress_m, 2),
                "observed_at": point.timestamp,
                "lat": point.lat,
                "lon": point.lon,
                "elevation_m": point.elevation_m,
                "source_refs": [route_artifact_id, "candidates/checkpoints.json"],
                "boundary": {
                    "candidate_only": True,
                    "runtime_mutation_allowed": False,
                    "phase1_runtime_mutation_allowed": False,
                    "phase2_writeback_allowed": False,
                },
            }
        )

    return {
        "artifact_kind": "pretrip_checkpoint_event_candidates",
        "schema_version": "0.1.0",
        "project_id": project_id,
        "route_artifact_id": route_artifact_id,
        "source_gpx": {
            "uri": route_path.resolve().as_posix(),
            "sha256": sha256_file(route_path),
            "point_count": len(route.points),
            "internal_points_preserved": True,
            "trimming_performed": False,
            "sampling_performed": False,
        },
        "event_count": len(events),
        "events": events,
        "boundary": {
            "candidate_events_only": True,
            "raw_track_points_embedded": False,
            "runtime_safety_truth": False,
            "live_network_required": False,
        },
        "notes": [
            "events（事件候選）由完整 golden route GPX 的 CP route_point_index 對應產生。",
            "不修剪、不抽樣 golden route GPX 內部點位；event 檔只保存 CP 對應點，不保存全量 trkpt。",
        ],
    }


def build_segment_display_geometry(
    *,
    project_id: str,
    route_gpx_path: Path | str,
    segment_candidates: list[PreTripSegmentCandidate],
    route_artifact_id: str = "artifact.gpx.chilai_nanhua_day1",
) -> dict[str, Any]:
    route_path = Path(route_gpx_path).expanduser()
    route = load_gpx_route(route_path)
    indexed_display_segments = _load_indexed_display_segments(route_path)
    segment_geometries: list[dict[str, Any]] = []

    for segment in segment_candidates:
        start_index = segment.route_point_start_index
        end_index = segment.route_point_end_index
        if start_index is None or end_index is None:
            continue
        if start_index < 0 or end_index >= len(route.points) or start_index >= end_index:
            continue
        points = route.points[start_index : end_index + 1]
        coordinate_segments = _coordinate_segments_for_range(
            indexed_display_segments,
            start_index=start_index,
            end_index=end_index,
        )
        if not coordinate_segments:
            fallback_coordinates = _display_coordinates(points)
            coordinate_segments = [fallback_coordinates] if fallback_coordinates else []
        coordinates = _flatten_coordinate_segments(coordinate_segments)
        segment_geometries.append(
            {
                "segment_candidate_id": segment.candidate_id,
                "from_candidate_id": segment.from_candidate_id,
                "to_candidate_id": segment.to_candidate_id,
                "route_point_start_index": start_index,
                "route_point_end_index": end_index,
                "source_point_count": len(points),
                "display_point_count": len(coordinates),
                "display_segment_count": len(coordinate_segments),
                "distance_m": round(segment.distance_m, 2),
                "coordinates": coordinates,
                "coordinate_segments": coordinate_segments,
                "segment_boundary_preserved": len(coordinate_segments) > 1,
            }
        )

    return {
        "artifact_kind": "pretrip_segment_display_geometry",
        "schema_version": "0.1.0",
        "project_id": project_id,
        "route_artifact_id": route_artifact_id,
        "source_gpx": {
            "uri": route_path.resolve().as_posix(),
            "sha256": sha256_file(route_path),
            "point_count": len(route.points),
            "timestamps_embedded": False,
            "elevation_embedded": False,
            "raw_gpx_copied_to_repo": False,
        },
        "segment_count": len(segment_geometries),
        "segments": segment_geometries,
        "boundary": {
            "display_geometry_only": True,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "raw_gpx_copied_to_repo": False,
            "live_network_required": False,
        },
        "notes": [
            "Segment display geometry（分段顯示幾何）只保留 lat/lon 曲線，供 admin map 畫出原始 GPX 走向。",
            "coordinate_segments preserves GPX track/segment boundaries（保留原始航跡分段邊界），避免畫出跨段長直線。",
            "不保存 timestamp/elevation/extension 欄位；不是 MissionGraph 或 runtime safety truth（現場安全真相）。",
        ],
    }


def build_reference_track_display_geometry(
    *,
    project_id: str,
    primary_gpx_path: Path | str,
    reference_gpx_paths: list[Path] | tuple[Path, ...],
    primary_artifact_id: str = "artifact.gpx.chilai_nanhua_day1",
    max_points_per_track: int = 1_000,
) -> dict[str, Any]:
    primary_path = Path(primary_gpx_path).expanduser()
    references: list[dict[str, Any]] = []

    for index, reference_path in enumerate(sorted(Path(path).expanduser() for path in reference_gpx_paths), start=1):
        route = load_gpx_route(reference_path)
        reference_id = f"{primary_artifact_id}.reference.{index:03d}"
        coordinate_segments = _display_coordinate_segments(
            _point_segments_from_indexed_segments(
                _load_indexed_display_segments(reference_path)
            ),
            max_points=max_points_per_track,
        )
        if not coordinate_segments:
            fallback_coordinates = _display_coordinates(
                route.points,
                max_points=max_points_per_track,
            )
            coordinate_segments = [fallback_coordinates] if fallback_coordinates else []
        coordinates = _flatten_coordinate_segments(coordinate_segments)
        references.append(
            {
                "reference_id": reference_id,
                "role": "reference_track",
                "route_name": summarize_gpx(reference_path, reference_id).route_name,
                "source_uri": reference_path.resolve().as_posix(),
                "source_sha256": sha256_file(reference_path),
                "source_point_count": len(route.points),
                "display_point_count": len(coordinates),
                "display_sampling_performed": len(coordinates) < len(route.points),
                "coordinates": coordinates,
                "coordinate_segments": coordinate_segments,
                "display_segment_count": len(coordinate_segments),
                "segment_boundary_preserved": len(coordinate_segments) > 1,
            }
        )

    return {
        "artifact_kind": "pretrip_reference_track_display_geometry",
        "schema_version": "0.1.0",
        "project_id": project_id,
        "golden_route_ref": primary_artifact_id,
        "golden_route_source_uri": Path(primary_gpx_path).expanduser().resolve().as_posix(),
        "primary_route_ref": primary_artifact_id,
        "primary_source_uri": Path(primary_gpx_path).expanduser().resolve().as_posix(),
        "reference_track_count": len(references),
        "max_points_per_track": max_points_per_track,
        "reference_tracks": references,
        "boundary": {
            "display_geometry_only": True,
            "golden_route_is_reference_evidence": True,
            "pretrip_actual_user_track_available": False,
            "reference_tracks_authoritative": False,
            "runtime_safety_truth": False,
            "raw_gpx_copied_to_repo": False,
            "live_network_required": False,
        },
        "notes": [
            "Reference tracks（專家/山友參考軌跡）是獨立 evidence layer，不是 OSM/Overpass 資料。",
            "畫面使用下採樣 display geometry；coordinate_segments preserves GPX track/segment boundaries（保留航跡分段邊界）以避免跨段長直線。",
            "完整 GPX 保留在本機來源資料夾，不進 runtime safety truth。",
        ],
    }


def _display_coordinates(
    points: list[RoutePoint],
    *,
    max_points: int | None = None,
) -> list[dict[str, float]]:
    selected_points = _downsample_points(points, max_points=max_points)
    return [
        {
            "lat": round(point.lat, 7),
            "lon": round(point.lon, 7),
        }
        for point in selected_points
    ]


def _load_indexed_display_segments(path: Path | str) -> list[list[_IndexedDisplayPoint]]:
    root = ET.parse(Path(path).expanduser()).getroot()
    ns = _namespace(root)
    source_index = 0
    segments: list[list[_IndexedDisplayPoint]] = []
    for track in root.findall("g:trk", ns):
        for segment in track.findall("g:trkseg", ns):
            points: list[_IndexedDisplayPoint] = []
            for trkpt in segment.findall("g:trkpt", ns):
                point = RoutePoint(
                    lat=float(trkpt.attrib["lat"]),
                    lon=float(trkpt.attrib["lon"]),
                )
                points.append(_IndexedDisplayPoint(source_index=source_index, point=point))
                source_index += 1
            if points:
                segments.append(points)
    return segments


def _namespace(root: ET.Element) -> dict[str, str]:
    if root.tag.startswith("{"):
        return {"g": root.tag[1:].split("}", 1)[0]}
    return {"g": "http://www.topografix.com/GPX/1/1"}


def _point_segments_from_indexed_segments(
    indexed_segments: list[list[_IndexedDisplayPoint]],
) -> list[list[RoutePoint]]:
    return [[item.point for item in segment] for segment in indexed_segments]


def _coordinate_segments_for_range(
    indexed_segments: list[list[_IndexedDisplayPoint]],
    *,
    start_index: int,
    end_index: int,
) -> list[list[dict[str, float]]]:
    point_segments: list[list[RoutePoint]] = []
    for segment in indexed_segments:
        points = [
            item.point
            for item in segment
            if start_index <= item.source_index <= end_index
        ]
        if points:
            point_segments.append(points)
    return _display_coordinate_segments(point_segments)


def _display_coordinate_segments(
    point_segments: list[list[RoutePoint]],
    *,
    max_points: int | None = None,
) -> list[list[dict[str, float]]]:
    selected_segments = _downsample_point_segments(
        point_segments,
        max_points=max_points,
    )
    return [
        _display_coordinates(points)
        for points in selected_segments
        if len(points) >= 2
    ]


def _flatten_coordinate_segments(
    coordinate_segments: list[list[dict[str, float]]],
) -> list[dict[str, float]]:
    return [
        point
        for segment in coordinate_segments
        for point in segment
    ]


def _downsample_points(
    points: list[RoutePoint],
    *,
    max_points: int | None,
) -> list[RoutePoint]:
    if max_points is None or max_points <= 0 or len(points) <= max_points:
        return points
    if max_points == 1:
        return [points[0]]
    step = (len(points) - 1) / (max_points - 1)
    indices = sorted({round(index * step) for index in range(max_points)})
    return [points[index] for index in indices]


def _downsample_point_segments(
    point_segments: list[list[RoutePoint]],
    *,
    max_points: int | None,
) -> list[list[RoutePoint]]:
    non_empty_segments = [segment for segment in point_segments if segment]
    total_points = sum(len(segment) for segment in non_empty_segments)
    if max_points is None or max_points <= 0 or total_points <= max_points:
        return non_empty_segments
    if max_points == 1:
        return [[non_empty_segments[0][0]]] if non_empty_segments else []
    step = (total_points - 1) / (max_points - 1)
    selected_indices = {round(index * step) for index in range(max_points)}
    selected_segments: list[list[RoutePoint]] = []
    offset = 0
    for segment in non_empty_segments:
        selected = [
            point
            for local_index, point in enumerate(segment)
            if offset + local_index in selected_indices
        ]
        if selected:
            selected_segments.append(selected)
        offset += len(segment)
    return selected_segments


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
