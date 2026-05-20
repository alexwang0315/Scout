from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from mission_models import DiversionPoint
from offline_map_models import HazardZone, TrailCorridor
from pretrip_geojson_import import (
    PreTripCorridorCandidate,
    PreTripGeoJsonImportResult,
    PreTripHazardCandidate,
    PreTripPoiCandidate,
)
from pretrip_models import CandidateReviewState


REVIEWED_STATES = {CandidateReviewState.ACCEPTED}
UNREVIEWED_STATES = {CandidateReviewState.PROPOSED, CandidateReviewState.NEEDS_REVIEW}
DIVERSION_POI_TYPES = {
    "camp",
    "evacuation_exit",
    "exit",
    "hut",
    "retreat",
    "retreat_point",
    "shelter",
    "signal",
    "signal_spot",
    "trailhead",
    "water",
    "water_source",
}


class MapCandidateCompileRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    candidate_type: Literal["corridor", "poi", "hazard"]
    label: str
    review_state: CandidateReviewState
    compiled_as: list[str] = Field(default_factory=list)
    skipped_reason: str | None = None


class PreTripMapCompileResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diversion_points: list[DiversionPoint] = Field(default_factory=list)
    trail_corridors: list[TrailCorridor] = Field(default_factory=list)
    hazard_zones: list[HazardZone] = Field(default_factory=list)
    compiled_candidates: list[MapCandidateCompileRecord] = Field(default_factory=list)
    skipped_candidates: list[MapCandidateCompileRecord] = Field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        return {
            "diversion_points": len(self.diversion_points),
            "trail_corridors": len(self.trail_corridors),
            "hazard_zones": len(self.hazard_zones),
            "compiled_candidates": len(self.compiled_candidates),
            "skipped_candidates": len(self.skipped_candidates),
        }


def load_and_compile_pretrip_map_candidates(
    path: Path | str,
    *,
    allow_unreviewed: bool = False,
) -> PreTripMapCompileResult:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return compile_pretrip_map_candidates(payload, allow_unreviewed=allow_unreviewed)


def compile_pretrip_map_candidates(
    candidates: PreTripGeoJsonImportResult | dict[str, Any],
    *,
    allow_unreviewed: bool = False,
) -> PreTripMapCompileResult:
    map_candidates = (
        candidates
        if isinstance(candidates, PreTripGeoJsonImportResult)
        else PreTripGeoJsonImportResult.model_validate(candidates)
    )

    diversion_points: list[DiversionPoint] = []
    trail_corridors: list[TrailCorridor] = []
    hazard_zones: list[HazardZone] = []
    compiled: list[MapCandidateCompileRecord] = []
    skipped: list[MapCandidateCompileRecord] = []

    for candidate in map_candidates.corridor_candidates:
        if _skip_rejected(candidate, "corridor", skipped):
            continue
        _ensure_reviewed(candidate, allow_unreviewed=allow_unreviewed)
        trail_corridors.append(candidate.corridor)
        compiled.append(_record(candidate, "corridor", compiled_as=["trail_corridor"]))

    for candidate in map_candidates.hazard_candidates:
        if _skip_rejected(candidate, "hazard", skipped):
            continue
        _ensure_reviewed(candidate, allow_unreviewed=allow_unreviewed)
        hazard_zones.append(candidate.hazard)
        compiled.append(_record(candidate, "hazard", compiled_as=["hazard_zone"]))

    for candidate in map_candidates.poi_candidates:
        if _skip_rejected(candidate, "poi", skipped):
            continue
        _ensure_reviewed(candidate, allow_unreviewed=allow_unreviewed)
        if not _poi_can_compile_to_diversion(candidate):
            skipped.append(
                _record(
                    candidate,
                    "poi",
                    skipped_reason=f"poi_type is not diversion-compatible: {candidate.poi.poi_type}",
                )
            )
            continue
        diversion_points.append(_diversion_from_poi(candidate))
        compiled.append(_record(candidate, "poi", compiled_as=["diversion_point"]))

    return PreTripMapCompileResult(
        diversion_points=diversion_points,
        trail_corridors=trail_corridors,
        hazard_zones=hazard_zones,
        compiled_candidates=compiled,
        skipped_candidates=skipped,
    )


def _ensure_reviewed(candidate: Any, *, allow_unreviewed: bool) -> None:
    if candidate.review_state == CandidateReviewState.REJECTED:
        return
    if candidate.review_state in REVIEWED_STATES:
        return
    if allow_unreviewed and candidate.review_state in UNREVIEWED_STATES:
        return
    raise ValueError(
        "unreviewed PreTrip map candidate cannot be compiled without allow_unreviewed=True: "
        f"{candidate.candidate_id} ({candidate.review_state})"
    )


def _skip_rejected(
    candidate: PreTripCorridorCandidate | PreTripHazardCandidate | PreTripPoiCandidate,
    candidate_type: Literal["corridor", "poi", "hazard"],
    skipped: list[MapCandidateCompileRecord],
) -> bool:
    if candidate.review_state != CandidateReviewState.REJECTED:
        return False
    skipped.append(_record(candidate, candidate_type, skipped_reason="candidate rejected by review"))
    return True


def _record(
    candidate: PreTripCorridorCandidate | PreTripHazardCandidate | PreTripPoiCandidate,
    candidate_type: Literal["corridor", "poi", "hazard"],
    *,
    compiled_as: list[str] | None = None,
    skipped_reason: str | None = None,
) -> MapCandidateCompileRecord:
    return MapCandidateCompileRecord(
        candidate_id=candidate.candidate_id,
        candidate_type=candidate_type,
        label=candidate.label,
        review_state=candidate.review_state,
        compiled_as=compiled_as or [],
        skipped_reason=skipped_reason,
    )


def _poi_can_compile_to_diversion(candidate: PreTripPoiCandidate) -> bool:
    return _normalized_type(candidate.poi.poi_type) in DIVERSION_POI_TYPES


def _diversion_from_poi(candidate: PreTripPoiCandidate) -> DiversionPoint:
    poi_type = _normalized_type(candidate.poi.poi_type)
    coordinate = candidate.poi.coordinate
    return DiversionPoint(
        diversion_id=candidate.candidate_id,
        name=candidate.poi.name,
        diversion_type=poi_type,
        lat=coordinate.lat,
        lon=coordinate.lon,
        distance_from_route_m=0.0,
        required_energy=_required_energy(poi_type),
        required_daylight_seconds=_required_daylight_seconds(poi_type),
        communication_available=poi_type in {"signal", "signal_spot"},
        risk_level=_risk_level(poi_type),
    )


def _normalized_type(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_") or "unknown"


def _required_energy(poi_type: str) -> float:
    if poi_type in {"camp", "hut", "shelter"}:
        return 0.15
    if poi_type in {"trailhead", "retreat", "retreat_point", "evacuation_exit", "exit"}:
        return 0.25
    return 0.05


def _required_daylight_seconds(poi_type: str) -> int:
    if poi_type in {"trailhead", "retreat", "retreat_point", "evacuation_exit", "exit"}:
        return 1800
    return 0


def _risk_level(poi_type: str) -> float:
    if poi_type in {"trailhead", "retreat", "retreat_point", "evacuation_exit", "exit"}:
        return 0.35
    if poi_type in {"camp", "hut", "shelter"}:
        return 0.2
    return 0.1
