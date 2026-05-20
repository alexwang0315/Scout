from __future__ import annotations

import json
import math
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from pretrip_models import PreTripPackage


class PoiReadinessCategory(StrEnum):
    ROUTE_CORRIDOR_POI_COVERAGE = "route_corridor_poi_coverage"
    WATER = "water"
    CAMP_OR_HUT = "camp_or_hut"
    SHELTER = "shelter"
    TRAILHEAD = "trailhead"
    SIGNAL = "signal"
    EVACUATION = "evacuation"
    RETREAT_ROUTE = "retreat_route"


class PoiReadinessSeverity(StrEnum):
    WARNING = "warning"
    BLOCKER = "blocker"


class PoiReadinessPolicyCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: PoiReadinessCategory
    severity: PoiReadinessSeverity
    corridor_distance_m: float = Field(default=1000.0, ge=0.0)
    minimum_poi_count: int = Field(default=1, ge=0)
    message: str
    candidate_only: bool = True
    notes: str = (
        "Candidate-only Phase 4 policy signal; does not mutate hard pre-trip readiness."
    )


class PoiReadinessFindingCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    category: PoiReadinessCategory
    severity: PoiReadinessSeverity
    message: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    candidate_only: bool = True


class PoiReadinessCandidateReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    artifact_kind: Literal["poi_readiness_candidates"] = "poi_readiness_candidates"
    project_id: str
    status: Literal["candidate_only"] = "candidate_only"
    policy_version: str = "0.1.0"
    policy_candidates: list[PoiReadinessPolicyCandidate]
    findings: list[PoiReadinessFindingCandidate]
    counts: dict[str, int]
    notes: list[str] = Field(default_factory=list)


DEFAULT_POI_READINESS_POLICY: tuple[PoiReadinessPolicyCandidate, ...] = (
    PoiReadinessPolicyCandidate(
        category=PoiReadinessCategory.ROUTE_CORRIDOR_POI_COVERAGE,
        severity=PoiReadinessSeverity.WARNING,
        corridor_distance_m=1000.0,
        minimum_poi_count=1,
        message="No POI candidates are within 1000m of the route corridor.",
    ),
)


def load_and_evaluate_poi_readiness_candidates(
    package_path: Path | str,
    map_candidates_path: Path | str,
    *,
    policy_candidates: tuple[PoiReadinessPolicyCandidate, ...] = DEFAULT_POI_READINESS_POLICY,
) -> PoiReadinessCandidateReport:
    package = PreTripPackage.model_validate(_load_json(Path(package_path)))
    map_candidates = _load_json(Path(map_candidates_path))
    return evaluate_poi_readiness_candidates(
        package,
        map_candidates,
        policy_candidates=policy_candidates,
    )


def evaluate_poi_readiness_candidates(
    package: PreTripPackage | dict[str, Any],
    map_candidates: dict[str, Any],
    *,
    policy_candidates: tuple[PoiReadinessPolicyCandidate, ...] = DEFAULT_POI_READINESS_POLICY,
) -> PoiReadinessCandidateReport:
    if isinstance(package, dict):
        package = PreTripPackage.model_validate(package)

    poi_coverage = _route_corridor_poi_coverage(map_candidates, policy_candidates)
    findings = [
        PoiReadinessFindingCandidate(
            candidate_id=f"poi_readiness.{package.project_id}.{policy.category}",
            category=policy.category,
            severity=policy.severity,
            message=_policy_message(policy),
            evidence={
                "corridor_distance_m": policy.corridor_distance_m,
                "minimum_poi_count": policy.minimum_poi_count,
                "matched_poi_count": len(matches),
                "matched_poi_refs": [
                    match["candidate_ref"]
                    for match in sorted(
                        matches,
                        key=lambda match: (
                            match["distance_to_corridor_m"],
                            match["candidate_ref"],
                        ),
                    )
                ],
                "nearest_poi_distance_to_corridor_m": _nearest_distance(matches),
            },
        )
        for policy, matches in poi_coverage
        if len(matches) < policy.minimum_poi_count
    ]

    warning_count = sum(1 for finding in findings if finding.severity == PoiReadinessSeverity.WARNING)
    blocker_count = sum(1 for finding in findings if finding.severity == PoiReadinessSeverity.BLOCKER)
    return PoiReadinessCandidateReport(
        artifact_id=f"poi_readiness_candidates.{package.project_id}.v0",
        project_id=package.project_id,
        policy_candidates=list(policy_candidates),
        findings=findings,
        counts={
            "policy_candidate_count": len(policy_candidates),
            "finding_candidate_count": len(findings),
            "warning_candidate_count": warning_count,
            "blocker_candidate_count": blocker_count,
            "route_corridor_poi_count": _max_matched_poi_count(poi_coverage),
        },
        notes=[
            "Candidate-only POI route-corridor coverage policy output.",
            "This artifact is separate from readiness_report_ref and must not create hard readiness blockers.",
        ],
    )


def _route_corridor_poi_coverage(
    map_candidates: dict[str, Any],
    policy_candidates: tuple[PoiReadinessPolicyCandidate, ...],
) -> list[tuple[PoiReadinessPolicyCandidate, list[dict[str, Any]]]]:
    poi_refs = _poi_refs(map_candidates)
    corridor_coordinates = _corridor_coordinates(map_candidates)
    coverage: list[tuple[PoiReadinessPolicyCandidate, list[dict[str, Any]]]] = [
        (policy, []) for policy in policy_candidates
    ]
    if not corridor_coordinates:
        return coverage

    for poi in poi_refs:
        distance = _distance_to_polyline_m(
            poi["coordinate"]["lat"],
            poi["coordinate"]["lon"],
            corridor_coordinates,
        )
        for policy, matches in coverage:
            if distance <= policy.corridor_distance_m:
                matches.append(
                    {
                        "candidate_ref": poi["candidate_ref"],
                        "poi_type": poi["poi_type"],
                        "distance_to_corridor_m": round(distance, 1),
                    }
                )

    return coverage


def _poi_refs(map_candidates: dict[str, Any]) -> list[dict[str, Any]]:
    poi_refs: list[dict[str, Any]] = []

    for candidate in map_candidates.get("poi_candidates", []):
        if not isinstance(candidate, dict):
            continue
        poi = candidate.get("poi", {})
        if not isinstance(poi, dict):
            continue
        coordinate = poi.get("coordinate", {})
        if not isinstance(coordinate, dict):
            continue
        try:
            lat = float(coordinate["lat"])
            lon = float(coordinate["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        poi_type = str(poi.get("poi_type", "")).strip().lower()
        ref = str(candidate.get("candidate_id") or poi.get("poi_id") or poi_type)
        poi_refs.append(
            {
                "candidate_ref": ref,
                "poi_type": poi_type,
                "coordinate": {"lat": lat, "lon": lon},
            }
        )

    return poi_refs


def _corridor_coordinates(map_candidates: dict[str, Any]) -> list[dict[str, float]]:
    coordinates: list[dict[str, float]] = []
    for candidate in map_candidates.get("corridor_candidates", []):
        if not isinstance(candidate, dict):
            continue
        corridor = candidate.get("corridor", {})
        if not isinstance(corridor, dict):
            continue
        for coordinate in corridor.get("coordinates", []):
            if not isinstance(coordinate, dict):
                continue
            try:
                coordinates.append(
                    {"lat": float(coordinate["lat"]), "lon": float(coordinate["lon"])}
                )
            except (KeyError, TypeError, ValueError):
                continue
    return coordinates


def _distance_to_polyline_m(
    lat: float,
    lon: float,
    coordinates: list[dict[str, float]],
) -> float:
    if len(coordinates) == 1:
        point = coordinates[0]
        return _haversine_m(lat, lon, point["lat"], point["lon"])

    best = float("inf")
    for start, end in zip(coordinates, coordinates[1:]):
        distance = _distance_to_segment_m(lat, lon, start, end, lat)
        if distance < best:
            best = distance
    return best


def _distance_to_segment_m(
    lat: float,
    lon: float,
    start: dict[str, float],
    end: dict[str, float],
    ref_lat: float,
) -> float:
    px, py = _to_local_xy_m(lat, lon, ref_lat)
    ax, ay = _to_local_xy_m(start["lat"], start["lon"], ref_lat)
    bx, by = _to_local_xy_m(end["lat"], end["lon"], ref_lat)
    dx = bx - ax
    dy = by - ay
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    nearest_x = ax + t * dx
    nearest_y = ay + t * dy
    return ((px - nearest_x) ** 2 + (py - nearest_y) ** 2) ** 0.5


def _to_local_xy_m(lat: float, lon: float, ref_lat: float) -> tuple[float, float]:
    meters_per_deg_lat = 111_320.0
    meters_per_deg_lon = 111_320.0 * math.cos(math.radians(ref_lat))
    return lon * meters_per_deg_lon, lat * meters_per_deg_lat


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def _policy_message(policy: PoiReadinessPolicyCandidate) -> str:
    if policy.message:
        return policy.message
    return (
        f"Fewer than {policy.minimum_poi_count} POI candidates are within "
        f"{policy.corridor_distance_m:g}m of the route corridor."
    )


def _nearest_distance(matches: list[dict[str, Any]]) -> float | None:
    if not matches:
        return None
    return min(match["distance_to_corridor_m"] for match in matches)


def _max_matched_poi_count(
    coverage: list[tuple[PoiReadinessPolicyCandidate, list[dict[str, Any]]]],
) -> int:
    if not coverage:
        return 0
    return max(len(matches) for _, matches in coverage)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
