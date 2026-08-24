#!/usr/bin/env python3
"""Compare Scout and QGIS terrain candidates without assigning terrain truth."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


SCOUT_GROUPS = {
    "main_ridge_candidate": "scout_ridge",
    "spur_ridge_candidate": "scout_ridge",
    "drainage_trunk": "scout_drainage",
    "tributary": "scout_drainage",
}
QGIS_GROUPS = {
    "qgis_candidate_ridge_line": "qgis_ridge",
    "qgis_candidate_valley_line": "qgis_valley",
    "qgis_candidate_stream_network": "qgis_stream",
}
COMPARISON_GROUPS = (
    ("ridge", "scout_ridge", "qgis_ridge"),
    ("valley_morphology", "scout_drainage", "qgis_valley"),
    ("flow_channel", "scout_drainage", "qgis_stream"),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _gpx_points(path: Path) -> list[tuple[float, float]]:
    root = ET.parse(path).getroot()
    points = [
        (float(element.attrib["lon"]), float(element.attrib["lat"]))
        for element in root.iter()
        if element.tag.rsplit("}", 1)[-1] in {"trkpt", "rtept"}
    ]
    if len(points) < 2:
        raise ValueError(f"Golden GPX has fewer than two route points: {path}")
    return points


def _line_parts(geometry: dict[str, Any]) -> list[list[tuple[float, float]]]:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    raw_parts = [coordinates] if geometry_type == "LineString" else coordinates
    if geometry_type not in {"LineString", "MultiLineString"} or not isinstance(
        raw_parts, list
    ):
        return []
    parts: list[list[tuple[float, float]]] = []
    for raw_part in raw_parts:
        if not isinstance(raw_part, list):
            continue
        part: list[tuple[float, float]] = []
        for coordinate in raw_part:
            if not isinstance(coordinate, (list, tuple)) or len(coordinate) < 2:
                continue
            try:
                lon, lat = float(coordinate[0]), float(coordinate[1])
            except (TypeError, ValueError):
                continue
            if math.isfinite(lon) and math.isfinite(lat):
                part.append((lon, lat))
        if len(part) >= 2:
            parts.append(part)
    return parts


def _scout_parts(edge: dict[str, Any]) -> list[list[tuple[float, float]]]:
    coordinates = edge.get("coordinates")
    if not isinstance(coordinates, list):
        return []
    part: list[tuple[float, float]] = []
    for coordinate in coordinates:
        if not isinstance(coordinate, dict):
            continue
        try:
            lon, lat = float(coordinate["lon"]), float(coordinate["lat"])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(lon) and math.isfinite(lat):
            part.append((lon, lat))
    return [part] if len(part) >= 2 else []


def _candidate_groups(
    navigation: dict[str, Any],
    workflow: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    groups = {group: [] for group in {*SCOUT_GROUPS.values(), *QGIS_GROUPS.values()}}
    hierarchy = navigation.get("terrain_hierarchy")
    edges = hierarchy.get("edges") if isinstance(hierarchy, dict) else []
    for ordinal, edge in enumerate(edges or []):
        if not isinstance(edge, dict):
            continue
        kind = str(edge.get("kind") or "")
        group = SCOUT_GROUPS.get(kind)
        parts = _scout_parts(edge)
        if group and parts:
            groups[group].append(
                {
                    "candidate_id": str(edge.get("id") or f"scout.{group}.{ordinal}"),
                    "kind": kind,
                    "parts": parts,
                }
            )
    collection = workflow.get("maplibre_geojson")
    features = collection.get("features") if isinstance(collection, dict) else []
    for ordinal, feature in enumerate(features or []):
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties")
        properties = properties if isinstance(properties, dict) else {}
        kind = str(properties.get("kind") or "")
        group = QGIS_GROUPS.get(kind)
        geometry = feature.get("geometry")
        parts = _line_parts(geometry) if isinstance(geometry, dict) else []
        if group and parts:
            groups[group].append(
                {
                    "candidate_id": str(
                        properties.get("id") or f"qgis.{group}.{ordinal}"
                    ),
                    "kind": kind,
                    "parts": parts,
                }
            )
    return groups


def _projection(route: list[tuple[float, float]]) -> tuple[float, float]:
    mean_lat = sum(point[1] for point in route) / len(route)
    return 111_320.0 * math.cos(math.radians(mean_lat)), 110_574.0


def _xy(point: tuple[float, float], scales: tuple[float, float]) -> tuple[float, float]:
    return point[0] * scales[0], point[1] * scales[1]


def _point_segment_distance(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    if dx == 0 and dy == 0:
        return math.hypot(point[0] - start[0], point[1] - start[1])
    ratio = max(
        0.0,
        min(
            1.0,
            ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy)
            / (dx * dx + dy * dy),
        ),
    )
    return math.hypot(
        point[0] - (start[0] + ratio * dx),
        point[1] - (start[1] + ratio * dy),
    )


def _orientation(
    start: tuple[float, float],
    end: tuple[float, float],
    point: tuple[float, float],
) -> float:
    return (end[0] - start[0]) * (point[1] - start[1]) - (
        end[1] - start[1]
    ) * (point[0] - start[0])


def _segments_intersect(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> bool:
    first = _orientation(a, b, c)
    second = _orientation(a, b, d)
    third = _orientation(c, d, a)
    fourth = _orientation(c, d, b)
    epsilon = 1e-9
    return (
        first * second < -epsilon and third * fourth < -epsilon
    ) or min(
        _point_segment_distance(a, c, d),
        _point_segment_distance(b, c, d),
        _point_segment_distance(c, a, b),
        _point_segment_distance(d, a, b),
    ) <= epsilon


def _segment_distance(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> float:
    if _segments_intersect(a, b, c, d):
        return 0.0
    return min(
        _point_segment_distance(a, c, d),
        _point_segment_distance(b, c, d),
        _point_segment_distance(c, a, b),
        _point_segment_distance(d, a, b),
    )


def _segments(parts: list[list[tuple[float, float]]]):
    for part in parts:
        yield from zip(part, part[1:])


def _candidate_length(candidate: dict[str, Any]) -> float:
    return sum(
        math.hypot(end[0] - start[0], end[1] - start[1])
        for start, end in _segments(candidate["metric_parts"])
    )


def _candidate_distance(left: dict[str, Any], right: dict[str, Any]) -> float:
    return min(
        _segment_distance(left_start, left_end, right_start, right_end)
        for left_start, left_end in _segments(left["metric_parts"])
        for right_start, right_end in _segments(right["metric_parts"])
    )


def _measure_groups(
    groups: dict[str, list[dict[str, Any]]],
    route: list[tuple[float, float]],
    *,
    start_corridor_m: float,
) -> None:
    scales = _projection(route)
    metric_route = [_xy(point, scales) for point in route]
    route_segments = list(zip(metric_route, metric_route[1:]))
    for candidates in groups.values():
        for candidate in candidates:
            metric_parts = [
                [_xy(point, scales) for point in part] for part in candidate["parts"]
            ]
            candidate["metric_parts"] = metric_parts
            start = metric_parts[0][0]
            route_start_distance = min(
                _point_segment_distance(start, route_start, route_end)
                for route_start, route_end in route_segments
            )
            candidate["route_start_distance_m"] = route_start_distance
            candidate["length_m"] = _candidate_length(candidate)
            candidate["displayed"] = route_start_distance <= start_corridor_m


def _percent(numerator: int, denominator: int) -> float:
    return round(100.0 * numerator / denominator, 1) if denominator else 0.0


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    return round(sorted(values)[max(0, math.ceil(percentile * len(values)) - 1)], 1)


def _group_summary(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    displayed = [candidate for candidate in candidates if candidate["displayed"]]
    distances = [candidate["route_start_distance_m"] for candidate in candidates]
    lengths = [candidate["length_m"] for candidate in candidates]
    return {
        "total": len(candidates),
        "displayed": len(displayed),
        "hidden_by_start_corridor": len(candidates) - len(displayed),
        "retained_percent": _percent(len(displayed), len(candidates)),
        "median_route_start_distance_m": (
            round(statistics.median(distances), 1) if distances else None
        ),
        "median_candidate_length_m": (
            round(statistics.median(lengths), 1) if lengths else None
        ),
    }


def _comparison_side(
    candidates: list[dict[str, Any]],
    other_candidates: list[dict[str, Any]],
    *,
    tolerance_m: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    distances: list[float] = []
    non_overlap: list[dict[str, Any]] = []
    for candidate in candidates:
        nearest = min(
            (_candidate_distance(candidate, other) for other in other_candidates),
            default=math.inf,
        )
        if math.isfinite(nearest):
            distances.append(nearest)
        if not math.isfinite(nearest) or nearest > tolerance_m:
            start = candidate["parts"][0][0]
            non_overlap.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "kind": candidate["kind"],
                    "start": {"lon": round(start[0], 7), "lat": round(start[1], 7)},
                    "route_start_distance_m": round(
                        candidate["route_start_distance_m"], 1
                    ),
                    "candidate_length_m": round(candidate["length_m"], 1),
                    "nearest_other_engine_m": (
                        round(nearest, 1) if math.isfinite(nearest) else None
                    ),
                }
            )
    within = sum(distance <= tolerance_m for distance in distances)
    outside = len(candidates) - within
    non_overlap.sort(
        key=lambda item: item["nearest_other_engine_m"]
        if item["nearest_other_engine_m"] is not None
        else math.inf,
        reverse=True,
    )
    return (
        {
            "displayed": len(candidates),
            "within_tolerance": within,
            "outside_tolerance": outside,
            "agreement_percent": _percent(within, len(candidates)),
            "median_nearest_distance_m": (
                round(statistics.median(distances), 1) if distances else None
            ),
            "p90_nearest_distance_m": _percentile(distances, 0.9),
        },
        non_overlap[:25],
    )


def _compare_groups(
    left_name: str,
    left: list[dict[str, Any]],
    right_name: str,
    right: list[dict[str, Any]],
    *,
    tolerance_m: float,
) -> dict[str, Any]:
    displayed_left = [candidate for candidate in left if candidate["displayed"]]
    displayed_right = [candidate for candidate in right if candidate["displayed"]]
    left_summary, left_non_overlap = _comparison_side(
        displayed_left,
        displayed_right,
        tolerance_m=tolerance_m,
    )
    right_summary, right_non_overlap = _comparison_side(
        displayed_right,
        displayed_left,
        tolerance_m=tolerance_m,
    )
    return {
        left_name: left_summary,
        right_name: right_summary,
        f"non_overlap_{left_name}": left_non_overlap,
        f"non_overlap_{right_name}": right_non_overlap,
    }


def build_comparison_report(
    *,
    navigation_path: Path,
    workflow_path: Path,
    golden_gpx_path: Path,
    start_corridor_m: float = 10.0,
    agreement_tolerance_m: float = 20.0,
) -> dict[str, Any]:
    if start_corridor_m <= 0 or agreement_tolerance_m <= 0:
        raise ValueError("distance thresholds must be positive")
    navigation_path = navigation_path.resolve()
    workflow_path = workflow_path.resolve()
    golden_gpx_path = golden_gpx_path.resolve()
    navigation = _json_object(navigation_path)
    workflow = _json_object(workflow_path)
    route = _gpx_points(golden_gpx_path)
    groups = _candidate_groups(navigation, workflow)
    _measure_groups(groups, route, start_corridor_m=start_corridor_m)
    comparisons = {
        label: _compare_groups(
            left_name,
            groups[left_name],
            right_name,
            groups[right_name],
            tolerance_m=agreement_tolerance_m,
        )
        for label, left_name, right_name in COMPARISON_GROUPS
    }
    return {
        "schema_version": "scout_qgis_terrain_candidate_comparison.v0_1",
        "workflow_run_id": workflow.get("workflow_run_id") or "UNKNOWN",
        "policy": {
            "display_filter": "candidate_start_to_golden_gpx",
            "start_corridor_m": start_corridor_m,
            "agreement_measure": "minimum_polyline_distance",
            "agreement_tolerance_m": agreement_tolerance_m,
            "source_resolution_m": 20,
            "start_vertex_direction_is_semantically_arbitrary": True,
            "raw_artifacts_deleted": False,
        },
        "sources": {
            "navigation": str(navigation_path),
            "workflow": str(workflow_path),
            "golden_gpx": str(golden_gpx_path),
            "source_hashes": {
                str(navigation_path): _sha256(navigation_path),
                str(workflow_path): _sha256(workflow_path),
                str(golden_gpx_path): _sha256(golden_gpx_path),
            },
            "golden_gpx_point_count": len(route),
        },
        "groups": {name: _group_summary(candidates) for name, candidates in groups.items()},
        "comparisons": comparisons,
        "interpretation": [
            "Agreement is not accuracy: two DEM-derived methods can agree and still be wrong.",
            "A non-overlap case identifies algorithm or scale disagreement, not a refuted terrain feature.",
            "Golden GPX proximity limits display clutter but does not validate ridge, valley, or stream truth.",
            "Independent contour review, field labels, or another reviewed reference is required to rank accuracy.",
        ],
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
            "accuracy_determined": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare Scout and QGIS terrain candidates near one Golden GPX."
    )
    parser.add_argument("--navigation", type=Path, required=True)
    parser.add_argument("--workflow", type=Path, required=True)
    parser.add_argument("--golden-gpx", type=Path, required=True)
    parser.add_argument("--start-corridor-m", type=float, default=10.0)
    parser.add_argument("--agreement-tolerance-m", type=float, default=20.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = build_comparison_report(
        navigation_path=args.navigation,
        workflow_path=args.workflow,
        golden_gpx_path=args.golden_gpx,
        start_corridor_m=args.start_corridor_m,
        agreement_tolerance_m=args.agreement_tolerance_m,
    )
    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
