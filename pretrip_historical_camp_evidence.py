from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from geo_utils import haversine_m
from pretrip_boss_point_synthesis import (
    _nearest_route_projection_from_edges,
    _route_projection_edges_from_segments,
)


DEFAULT_SOURCE_REF = "candidates/route_note_candidates.json"
MAX_CROSS_TRACK_M = 100.0
DEDUP_DISTANCE_M = 100.0

_CAMP_LABEL = re.compile(
    r"營地|营地|[紮扎][營营]|宿[營营]|露[營营]|\bcamp(?:site|ground|[ _-]site)?\b",
    re.IGNORECASE,
)
_NON_CAMP_LABEL = re.compile(
    r"休息|休憩|午餐|取水|補水|出水|岔路|叉路|路口|入口|路標|指標"
    r"|水源(?:點|處|口)?\s*\d*$"
    r"|(?:營地|营地).{0,12}(?:旁|附近|上方|下方|前方|後方|后方)"
    r"|(?:往|前往|通往|距離|距离).*(?:營地|营地|camp)"
    r"|(?:禁止|不可|不得|不宜|不適合|非|無).{0,8}(?:營|营|camp)"
    r"|\b(?:rest(?:ing)?\s+(?:area|stop|point)|near|towards?|junction|entrance)\b"
    r"|\bwater\s+(?:point|source|access)\b|\bno\s+camp(?:ing)?\b",
    re.IGNORECASE,
)


def build_historical_camp_anchors(
    *,
    project_root: str | Path,
    project: dict[str, Any],
    route_points: list[dict[str, Any]],
) -> dict[str, Any]:
    """Project explicit historical camp labels without assigning overnight stays."""
    source_ref = project.get("route_note_candidates_ref") or DEFAULT_SOURCE_REF
    if not isinstance(source_ref, str):
        return _result("unavailable", reason="invalid_source_ref")
    try:
        root = Path(project_root).resolve()
        path = (root / source_ref).resolve()
        if not path.is_relative_to(root):
            return _result("unavailable", reason="source_outside_project_root")
        source_ref = path.relative_to(root).as_posix()
        if not path.is_file():
            return _result(
                "unavailable" if path.exists() else "no_evidence",
                reason="source_not_file" if path.exists() else "source_missing",
            )
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RuntimeError) as error:
        return _result("unavailable", reason=type(error).__name__)
    notes = payload.get("candidates") if isinstance(payload, dict) else None
    if not isinstance(notes, list):
        return _result("unavailable", [source_ref], reason="invalid_note_candidates")
    edges = _route_edges(route_points)
    if not edges:
        return _result("unavailable", [source_ref], reason="invalid_route_axis")

    projected = []
    for note in notes:
        if not isinstance(note, dict):
            continue
        label = note.get("name") or note.get("label")
        if not isinstance(label, str) or not _CAMP_LABEL.search(label):
            continue
        if _NON_CAMP_LABEL.search(label):
            continue
        location = _location(note)
        if location is None:
            continue
        projection = _nearest_route_projection_from_edges(edges, **location)
        if projection is None or projection["distance_to_route_m"] > MAX_CROSS_TRACK_M:
            continue
        declared_refs = note.get("source_refs")
        refs = [source_ref, note.get("candidate_id")]
        if isinstance(declared_refs, list):
            refs = [*refs, *declared_refs]
        projected = [*projected, {
            "label": label.strip(),
            "route_distance_m": projection["route_distance_m"],
            "source_refs": sorted({ref for ref in refs if isinstance(ref, str) and ref}),
            **location,
        }]
    camps = _deduplicate(projected)
    return _result("ready" if camps else "no_evidence", [source_ref], camps=camps)


def _result(
    status: str,
    source_refs: list[str] | None = None,
    *,
    camps: list[dict[str, Any]] | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    return {
        "camps": camps or [],
        "source_refs": source_refs or [],
        "policy": {
            "anchor_basis": "explicit_historical_camp_label",
            "route_distance_axis": "parent_source_axis",
            "max_cross_track_m": MAX_CROSS_TRACK_M,
            "dedup_route_distance_m": DEDUP_DISTANCE_M,
            "dedup_location_distance_m": DEDUP_DISTANCE_M,
            "candidate_only": True,
            "overnight_assignment_verified": False,
            "runtime_safety_truth": False,
            **({"reason": reason} if reason else {}),
        },
        "status": status,
    }


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _location(point: dict[str, Any]) -> dict[str, float] | None:
    lat = _finite_number(point.get("lat"))
    lon = _finite_number(point.get("lon"))
    if lat is None or lon is None or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        return None
    return {"point_lat": lat, "point_lon": lon}


def _route_edges(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if any(not isinstance(point, dict) for point in points):
        return []
    locations = [_location(point) for point in points]
    distances = [_finite_number(point.get("route_distance_m")) for point in points]
    if any(location is None for location in locations):
        return []
    if any(distance is None or distance < 0 for distance in distances):
        return []
    if any(end < start for start, end in zip(distances, distances[1:])):
        return []
    samples = [
        {**location, "route_distance_m": distance}
        for location, distance in zip(locations, distances)
    ]
    # Keep each supplied distance interval; geometric lengths must not rebase the axis.
    segments = [
        {
            "start_distance_m": start["route_distance_m"],
            "end_distance_m": end["route_distance_m"],
            "coordinates": [
                {"lat": p["point_lat"], "lon": p["point_lon"]} for p in (start, end)
            ],
        }
        for start, end in zip(samples, samples[1:])
        if end["route_distance_m"] > start["route_distance_m"]
    ]
    return _route_projection_edges_from_segments(segments)


def _deduplicate(projected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(
        projected,
        key=lambda item: (
            item["route_distance_m"], item["label"], item["source_refs"],
            item["point_lat"], item["point_lon"],
        ),
    )
    groups: list[list[dict[str, Any]]] = []
    for camp in ordered:
        match = next((
            index for index, group in enumerate(groups)
            if all(
                abs(camp["route_distance_m"] - other["route_distance_m"]) <= DEDUP_DISTANCE_M
                and haversine_m(
                    camp["point_lat"], camp["point_lon"],
                    other["point_lat"], other["point_lon"],
                ) <= DEDUP_DISTANCE_M
                for other in group
            )
        ), None)
        groups = (
            [*groups, [camp]] if match is None else
            [[*group, camp] if index == match else group for index, group in enumerate(groups)]
        )
    return [_camp_record(group) for group in groups]


def _camp_record(group: list[dict[str, Any]]) -> dict[str, Any]:
    representative = group[0]
    source_refs = sorted({ref for camp in group for ref in camp["source_refs"]})
    distance = round(representative["route_distance_m"], 3)
    identity = json.dumps([
        source_refs, distance, representative["label"],
        representative["point_lat"], representative["point_lon"],
    ], ensure_ascii=True)
    return {
        "node_id": f"historical_camp.{hashlib.sha256(identity.encode()).hexdigest()[:16]}",
        "label": representative["label"],
        "route_distance_m": distance,
        "source_refs": source_refs,
        "candidate_only": True,
        "overnight_assignment_verified": False,
    }
