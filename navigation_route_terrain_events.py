"""Join an observed route with candidate terrain hierarchy events."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from navigation_terrain_dem import (
    WorkspaceTerrainEvidenceError,
    _read_project_json,
    _required_project_ref,
    _route_sample_points,
)

RIDGE_EDGE_KINDS = {
    "main_ridge_candidate",
    "spur_ridge_candidate",
    "watershed_boundary",
}
DRAINAGE_EDGE_KINDS = {"drainage_trunk", "tributary"}
NODE_EVENT_TYPES = {
    "saddle_node": "saddle_passage",
    "ridge_divide_node": "ridge_divide_passage",
    "headwater_node": "headwater_crossing",
    "drainage_confluence_node": "drainage_branch",
}


def build_route_terrain_events(
    route_points: Sequence[Mapping[str, Any]],
    terrain_hierarchy: Mapping[str, Any],
    *,
    proximity_tolerance_m: float = 40.0,
    crossing_angle_degrees: float = 35.0,
    dedupe_distance_m: float = 30.0,
    max_events: int = 120,
) -> dict[str, Any]:
    """Return ordered, candidate-only terrain-relative navigation events."""

    boundary = terrain_hierarchy.get("boundary", {})
    if (
        not isinstance(boundary, Mapping)
        or boundary.get("candidate_only") is not True
        or boundary.get("runtime_safety_truth") is not False
    ):
        return _empty_result(
            "rejected_boundary",
            "Terrain hierarchy did not preserve the candidate-only boundary.",
        )
    route = _normalize_route(route_points)
    if len(route) < 2:
        return _empty_result(
            "not_prepared",
            "At least two projected route points are required.",
        )
    tolerance = _positive(proximity_tolerance_m, "proximity_tolerance_m")
    crossing_angle = _bounded_angle(crossing_angle_degrees)
    dedupe_distance = _positive(dedupe_distance_m, "dedupe_distance_m")
    if max_events < 1 or max_events > 500:
        raise WorkspaceTerrainEvidenceError("max_events must be between 1 and 500")

    route_index = _route_segment_index(
        route,
        proximity_tolerance_m=tolerance,
    )
    hierarchy_source_refs = _refs(terrain_hierarchy.get("source_refs"))
    candidates: list[dict[str, Any]] = []
    raw_edges = terrain_hierarchy.get("edges", [])
    if isinstance(raw_edges, list):
        for edge in raw_edges:
            event = _edge_event(
                route_index,
                edge,
                proximity_tolerance_m=tolerance,
                crossing_angle_degrees=crossing_angle,
                fallback_source_refs=hierarchy_source_refs,
            )
            if event is not None:
                candidates.append(event)
    raw_nodes = terrain_hierarchy.get("nodes", [])
    if isinstance(raw_nodes, list):
        for node in raw_nodes:
            event = _node_event(
                route,
                node,
                proximity_tolerance_m=tolerance,
                fallback_source_refs=hierarchy_source_refs,
            )
            if event is not None:
                candidates.append(event)

    ordered = sorted(
        candidates,
        key=lambda item: (
            float(item["route_distance_m"]),
            float(item["off_route_distance_m"]),
            str(item["event_type"]),
            str(item["terrain_feature_id"]),
        ),
    )
    deduped: list[dict[str, Any]] = []
    for event in ordered:
        duplicate_index = next(
            (
                index
                for index, existing in enumerate(deduped)
                if existing["event_type"] == event["event_type"]
                and abs(
                    float(existing["route_distance_m"])
                    - float(event["route_distance_m"])
                )
                <= dedupe_distance
            ),
            None,
        )
        if duplicate_index is None:
            deduped.append(event)
        elif float(event["off_route_distance_m"]) < float(
            deduped[duplicate_index]["off_route_distance_m"]
        ):
            deduped[duplicate_index] = event
    bounded = sorted(
        deduped,
        key=lambda item: (
            float(item["route_distance_m"]),
            str(item["event_type"]),
        ),
    )[:max_events]
    events = [
        {
            "id": f"route-terrain-event.{index:03d}",
            "sequence": index,
            **event,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "requires_human_review": True,
        }
        for index, event in enumerate(bounded, start=1)
    ]
    return {
        "schema_version": "scout_navigation_route_terrain_events.v0",
        "artifact_kind": "route_terrain_event_sequence",
        "status": "candidate_events" if events else "no_nearby_events",
        "route_point_count": len(route),
        "candidate_event_count": len(deduped),
        "event_count": len(events),
        "truncated": len(deduped) > len(events),
        "events": events,
        "method": {
            "join": "projected_polyline_nearest_segment_and_crossing.v0",
            "proximity_tolerance_m": tolerance,
            "crossing_angle_degrees": crossing_angle,
            "dedupe_distance_m": dedupe_distance,
            "ordering": "route_distance_m_ascending",
        },
        "limitations": [
            (
                "Events express route-to-terrain geometry, not trail "
                "existence, current passability, or a go/no-go decision."
            ),
            (
                "Wrong-way cues are terrain-relative review prompts and must "
                "be calibrated against map, visibility, and field evidence."
            ),
        ],
        "boundary": _candidate_boundary(),
    }


def build_workspace_route_terrain_events(
    project_root: Path,
    project: dict[str, Any],
    terrain_hierarchy: Mapping[str, Any],
    *,
    projected_route_points: Sequence[Mapping[str, Any]] | None = None,
    **options: Any,
) -> dict[str, Any]:
    """Join prepared workspace route samples to a terrain hierarchy."""

    route_ref = _required_project_ref(project, "terrain_route_samples_ref")
    if projected_route_points is None:
        route_samples = _route_sample_points(
            _read_project_json(project_root.resolve(), route_ref)
        )
        from navigation_terrain_dem import project_route_sample_points_twd97

        projected = project_route_sample_points_twd97(route_samples)
    else:
        projected = [dict(point) for point in projected_route_points]
    projected = [
        {
            **point,
            "source_refs": [route_ref],
        }
        for point in projected
    ]
    result = build_route_terrain_events(projected, terrain_hierarchy, **options)
    return {
        **result,
        "source_refs": list(
            dict.fromkeys(
                [
                    route_ref,
                    *[
                        ref
                        for ref in terrain_hierarchy.get("source_refs", [])
                        if isinstance(ref, str) and ref.strip()
                    ],
                ]
            )
        ),
    }


def _edge_event(
    route_index: Mapping[str, Any],
    value: Any,
    *,
    proximity_tolerance_m: float,
    crossing_angle_degrees: float,
    fallback_source_refs: list[str],
) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    kind = str(value.get("kind") or "")
    if kind not in RIDGE_EDGE_KINDS | DRAINAGE_EDGE_KINDS:
        return None
    coordinates = _normalize_line(value.get("coordinates_twd97"))
    if len(coordinates) < 2:
        return None
    relation = _nearest_line_relation(route_index, coordinates)
    if relation is None or relation["distance_m"] > proximity_tolerance_m:
        return None
    angle = relation["angle_degrees"]
    is_crossing = bool(relation["intersects"] or angle >= crossing_angle_degrees)
    if kind in RIDGE_EDGE_KINDS:
        if is_crossing:
            event_type = "watershed_crossing"
            terrain_relation = (
                "crosses_main_ridge_or_watershed"
                if kind in {"main_ridge_candidate", "watershed_boundary"}
                else "crosses_spur_ridge"
            )
        else:
            event_type = "route_terrain_transition"
            terrain_relation = (
                "aligned_with_main_ridge"
                if kind in {"main_ridge_candidate", "watershed_boundary"}
                else "aligned_with_spur_ridge"
            )
    elif is_crossing:
        event_type = "drainage_crossing"
        terrain_relation = (
            "crosses_drainage_trunk"
            if kind == "drainage_trunk"
            else "crosses_tributary"
        )
    else:
        event_type = "route_terrain_transition"
        terrain_relation = (
            "aligned_with_drainage_trunk"
            if kind == "drainage_trunk"
            else "aligned_with_tributary"
        )
    return _event_record(
        event_type=event_type,
        terrain_relation=terrain_relation,
        feature_id=str(value.get("id") or kind),
        feature_kind=kind,
        relation=relation,
        source_refs=_refs(value.get("source_refs")) or fallback_source_refs,
    )


def _node_event(
    route: Sequence[dict[str, float]],
    value: Any,
    *,
    proximity_tolerance_m: float,
    fallback_source_refs: list[str],
) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    kind = str(value.get("kind") or "")
    event_type = NODE_EVENT_TYPES.get(kind)
    if event_type is None:
        return None
    x = _finite(value.get("x_twd97"))
    y = _finite(value.get("y_twd97"))
    if x is None or y is None:
        return None
    relation = _project_point_to_route(route, (x, y))
    if relation["distance_m"] > proximity_tolerance_m:
        return None
    terrain_relation = {
        "saddle_node": "passes_saddle_candidate",
        "ridge_divide_node": "passes_ridge_divide_candidate",
        "headwater_node": "passes_headwater_candidate",
        "drainage_confluence_node": "passes_drainage_branch_candidate",
    }[kind]
    return _event_record(
        event_type=event_type,
        terrain_relation=terrain_relation,
        feature_id=str(value.get("id") or kind),
        feature_kind=kind,
        relation={
            **relation,
            "angle_degrees": None,
            "intersects": relation["distance_m"] <= 0.001,
        },
        source_refs=_refs(value.get("source_refs")) or fallback_source_refs,
    )


def _event_record(
    *,
    event_type: str,
    terrain_relation: str,
    feature_id: str,
    feature_kind: str,
    relation: Mapping[str, Any],
    source_refs: list[str],
) -> dict[str, Any]:
    language = _event_language(event_type, terrain_relation)
    return {
        "event_type": event_type,
        "terrain_relation": terrain_relation,
        "terrain_feature_id": feature_id,
        "terrain_feature_kind": feature_kind,
        "route_distance_m": round(float(relation["route_distance_m"]), 1),
        "off_route_distance_m": round(float(relation["distance_m"]), 1),
        "crossing_angle_degrees": (
            round(float(relation["angle_degrees"]), 1)
            if relation.get("angle_degrees") is not None
            else None
        ),
        "x_twd97": round(float(relation["route_point"][0]), 3),
        "y_twd97": round(float(relation["route_point"][1]), 3),
        "observation_prompt": language["observation_prompt"],
        "wrong_way_cue": language["wrong_way_cue"],
        "recovery_prompt": language["recovery_prompt"],
        "source_refs": source_refs,
    }


def _event_language(event_type: str, terrain_relation: str) -> dict[str, str]:
    if event_type == "watershed_crossing":
        return {
            "observation_prompt": "前方應出現稜脊或分水界的地形轉折。",
            "wrong_way_cue": "若持續沿同一側坡腰繞、完全未出現轉折，應重新核對位置。",
            "recovery_prompt": "停下比對等高線、來向與兩側落水方向，再決定是否續行。",
        }
    if event_type == "drainage_crossing":
        return {
            "observation_prompt": "前方應接近凹谷、支流或集水線。",
            "wrong_way_cue": "若開始沿谷線持續下降，可能已把穿越誤走成順谷下切。",
            "recovery_prompt": "回到最後可確認的穿越點，核對對岸續行方向與等高線。",
        }
    if event_type == "saddle_passage":
        return {
            "observation_prompt": "此處應呈現兩高兩低的鞍部地形。",
            "wrong_way_cue": "若仍在單向長坡或明顯峰頂，可能尚未到鞍部。",
            "recovery_prompt": "用前後高點與兩側落水方向重新確認鞍部位置。",
        }
    if event_type in {"ridge_divide_passage", "drainage_branch"}:
        return {
            "observation_prompt": "此處是候選地形分支，路徑岔口仍需另行觀察。",
            "wrong_way_cue": "不要把地形分支自動當成步道岔口。",
            "recovery_prompt": "先確認踏跡、方位與下一個地形控制點，再選擇方向。",
        }
    if event_type == "headwater_crossing":
        return {
            "observation_prompt": "此處接近候選源頭凹地，水跡可能不連續。",
            "wrong_way_cue": "若進入持續加深的溪溝，可能已偏離源頭穿越位置。",
            "recovery_prompt": "退回坡形尚清楚處，重新確認凹地上緣與續行方向。",
        }
    return {
        "observation_prompt": f"路線在此與候選地形骨架呈現 {terrain_relation}。",
        "wrong_way_cue": "若地形關係與預期長時間不符，應停止慣性前進。",
        "recovery_prompt": "回看上一個可確認地形點並重新比對等高線與方位。",
    }


def _normalize_route(
    values: Sequence[Mapping[str, Any]],
) -> list[dict[str, float]]:
    if not isinstance(values, Sequence):
        return []
    points = []
    for item in values:
        if not isinstance(item, Mapping):
            continue
        x = _finite(item.get("x_twd97"))
        y = _finite(item.get("y_twd97"))
        if x is None or y is None:
            continue
        if points and math.hypot(points[-1]["x"] - x, points[-1]["y"] - y) < 0.001:
            continue
        points.append(
            {
                "x": x,
                "y": y,
                "provided_distance_m": _finite(item.get("distance_m")),
            }
        )
    if not points:
        return []
    for index, point in enumerate(points):
        geometry_distance = 0.0
        if index:
            geometry_distance = points[index - 1]["distance_m"] + math.hypot(
                point["x"] - points[index - 1]["x"],
                point["y"] - points[index - 1]["y"],
            )
        provided = point["provided_distance_m"]
        if provided is not None and (
            index == 0 or provided >= points[index - 1]["distance_m"]
        ):
            point["distance_m"] = provided
        else:
            point["distance_m"] = geometry_distance
    return points


def _normalize_line(value: Any) -> list[tuple[float, float]]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        x = _finite(item[0])
        y = _finite(item[1])
        if x is None or y is None:
            continue
        point = (x, y)
        if not result or _distance(result[-1], point) > 0.001:
            result.append(point)
    return result


def _nearest_line_relation(
    route_index: Mapping[str, Any],
    terrain: Sequence[tuple[float, float]],
) -> dict[str, Any] | None:
    nearest = None
    route_segments = route_index["segments"]
    for terrain_a, terrain_b in zip(terrain, terrain[1:]):
        for segment_id in _nearby_route_segment_ids(
            route_index,
            terrain_a,
            terrain_b,
        ):
            route_a = route_segments[segment_id]["a"]
            route_b = route_segments[segment_id]["b"]
            a = (route_a["x"], route_a["y"])
            b = (route_b["x"], route_b["y"])
            relation = _segment_relation(a, b, terrain_a, terrain_b)
            route_length = _distance(a, b)
            route_distance = route_a["distance_m"] + (
                relation["route_fraction"]
                * (route_b["distance_m"] - route_a["distance_m"])
                if route_length > 0
                else 0.0
            )
            candidate = {
                **relation,
                "route_distance_m": route_distance,
            }
            if nearest is None or (
                candidate["distance_m"],
                candidate["route_distance_m"],
            ) < (
                nearest["distance_m"],
                nearest["route_distance_m"],
            ):
                nearest = candidate
    return nearest


def _route_segment_index(
    route: Sequence[dict[str, float]],
    *,
    proximity_tolerance_m: float,
) -> dict[str, Any]:
    bucket_size_m = max(100.0, proximity_tolerance_m * 2.0)
    segments = []
    buckets: dict[tuple[int, int], list[int]] = {}
    for route_a, route_b in zip(route, route[1:]):
        min_x = min(route_a["x"], route_b["x"]) - proximity_tolerance_m
        max_x = max(route_a["x"], route_b["x"]) + proximity_tolerance_m
        min_y = min(route_a["y"], route_b["y"]) - proximity_tolerance_m
        max_y = max(route_a["y"], route_b["y"]) + proximity_tolerance_m
        segment_id = len(segments)
        segments.append(
            {
                "a": route_a,
                "b": route_b,
                "min_x": min_x,
                "min_y": min_y,
                "max_x": max_x,
                "max_y": max_y,
            }
        )
        for bucket_x in range(
            math.floor(min_x / bucket_size_m),
            math.floor(max_x / bucket_size_m) + 1,
        ):
            for bucket_y in range(
                math.floor(min_y / bucket_size_m),
                math.floor(max_y / bucket_size_m) + 1,
            ):
                buckets.setdefault((bucket_x, bucket_y), []).append(segment_id)
    return {
        "segments": segments,
        "buckets": buckets,
        "bucket_size_m": bucket_size_m,
        "proximity_tolerance_m": proximity_tolerance_m,
    }


def _nearby_route_segment_ids(
    route_index: Mapping[str, Any],
    terrain_a: tuple[float, float],
    terrain_b: tuple[float, float],
) -> list[int]:
    bucket_size_m = float(route_index["bucket_size_m"])
    tolerance = float(route_index["proximity_tolerance_m"])
    min_x = min(terrain_a[0], terrain_b[0]) - tolerance
    max_x = max(terrain_a[0], terrain_b[0]) + tolerance
    min_y = min(terrain_a[1], terrain_b[1]) - tolerance
    max_y = max(terrain_a[1], terrain_b[1]) + tolerance
    candidate_ids = {
        segment_id
        for bucket_x in range(
            math.floor(min_x / bucket_size_m),
            math.floor(max_x / bucket_size_m) + 1,
        )
        for bucket_y in range(
            math.floor(min_y / bucket_size_m),
            math.floor(max_y / bucket_size_m) + 1,
        )
        for segment_id in route_index["buckets"].get(
            (bucket_x, bucket_y),
            [],
        )
    }
    return sorted(
        segment_id
        for segment_id in candidate_ids
        if not (
            route_index["segments"][segment_id]["max_x"] < min_x
            or route_index["segments"][segment_id]["min_x"] > max_x
            or route_index["segments"][segment_id]["max_y"] < min_y
            or route_index["segments"][segment_id]["min_y"] > max_y
        )
    )


def _segment_relation(
    route_a: tuple[float, float],
    route_b: tuple[float, float],
    terrain_a: tuple[float, float],
    terrain_b: tuple[float, float],
) -> dict[str, Any]:
    intersection = _segment_intersection(route_a, route_b, terrain_a, terrain_b)
    angle = _acute_angle_degrees(route_a, route_b, terrain_a, terrain_b)
    if intersection is not None:
        point, route_fraction = intersection
        return {
            "distance_m": 0.0,
            "route_fraction": route_fraction,
            "route_point": point,
            "angle_degrees": angle,
            "intersects": True,
        }
    projections = [
        _project_point_to_segment(terrain_a, route_a, route_b),
        _project_point_to_segment(terrain_b, route_a, route_b),
    ]
    for route_endpoint, fraction in ((route_a, 0.0), (route_b, 1.0)):
        distance, _terrain_fraction, _terrain_point = _project_point_to_segment(
            route_endpoint,
            terrain_a,
            terrain_b,
        )
        projections.append((distance, fraction, route_endpoint))
    distance, route_fraction, route_point = min(
        projections,
        key=lambda item: (item[0], item[1]),
    )
    return {
        "distance_m": distance,
        "route_fraction": route_fraction,
        "route_point": route_point,
        "angle_degrees": angle,
        "intersects": False,
    }


def _project_point_to_route(
    route: Sequence[dict[str, float]],
    point: tuple[float, float],
) -> dict[str, Any]:
    nearest = None
    for route_a, route_b in zip(route, route[1:]):
        a = (route_a["x"], route_a["y"])
        b = (route_b["x"], route_b["y"])
        distance, fraction, route_point = _project_point_to_segment(point, a, b)
        route_distance = route_a["distance_m"] + fraction * (
            route_b["distance_m"] - route_a["distance_m"]
        )
        candidate = {
            "distance_m": distance,
            "route_distance_m": route_distance,
            "route_point": route_point,
        }
        if nearest is None or (
            candidate["distance_m"],
            candidate["route_distance_m"],
        ) < (
            nearest["distance_m"],
            nearest["route_distance_m"],
        ):
            nearest = candidate
    assert nearest is not None
    return nearest


def _project_point_to_segment(
    point: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
) -> tuple[float, float, tuple[float, float]]:
    vx, vy = b[0] - a[0], b[1] - a[1]
    denominator = vx * vx + vy * vy
    if denominator <= 0:
        return _distance(point, a), 0.0, a
    fraction = max(
        0.0,
        min(
            1.0,
            ((point[0] - a[0]) * vx + (point[1] - a[1]) * vy) / denominator,
        ),
    )
    projected = (a[0] + fraction * vx, a[1] + fraction * vy)
    return _distance(point, projected), fraction, projected


def _segment_intersection(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> tuple[tuple[float, float], float] | None:
    rx, ry = b[0] - a[0], b[1] - a[1]
    sx, sy = d[0] - c[0], d[1] - c[1]
    denominator = rx * sy - ry * sx
    if abs(denominator) < 1e-9:
        return None
    qpx, qpy = c[0] - a[0], c[1] - a[1]
    t = (qpx * sy - qpy * sx) / denominator
    u = (qpx * ry - qpy * rx) / denominator
    if -1e-9 <= t <= 1.0 + 1e-9 and -1e-9 <= u <= 1.0 + 1e-9:
        return (a[0] + t * rx, a[1] + t * ry), max(0.0, min(1.0, t))
    return None


def _acute_angle_degrees(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> float:
    route_vector = (b[0] - a[0], b[1] - a[1])
    terrain_vector = (d[0] - c[0], d[1] - c[1])
    denominator = math.hypot(*route_vector) * math.hypot(*terrain_vector)
    if denominator <= 0:
        return 0.0
    cosine = abs(
        (route_vector[0] * terrain_vector[0] + route_vector[1] * terrain_vector[1])
        / denominator
    )
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def _empty_result(status: str, limitation: str) -> dict[str, Any]:
    return {
        "schema_version": "scout_navigation_route_terrain_events.v0",
        "artifact_kind": "route_terrain_event_sequence",
        "status": status,
        "route_point_count": 0,
        "candidate_event_count": 0,
        "event_count": 0,
        "truncated": False,
        "events": [],
        "limitations": [limitation],
        "boundary": _candidate_boundary(),
    }


def _candidate_boundary() -> dict[str, Any]:
    return {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "safe_or_walkable": "not_determined",
        "human_review_required": True,
        "phase1_runtime_mutation_allowed": False,
        "safety_api_called": False,
    }


def _refs(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(
        dict.fromkeys(
            item.strip()[:500]
            for item in value
            if isinstance(item, str) and item.strip()
        )
    )[:32]


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _positive(value: Any, field_name: str) -> float:
    number = _finite(value)
    if number is None or number <= 0:
        raise WorkspaceTerrainEvidenceError(f"{field_name} must be positive")
    return number


def _bounded_angle(value: Any) -> float:
    number = _finite(value)
    if number is None or not 0 < number < 90:
        raise WorkspaceTerrainEvidenceError(
            "crossing_angle_degrees must be between 0 and 90"
        )
    return number


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])
