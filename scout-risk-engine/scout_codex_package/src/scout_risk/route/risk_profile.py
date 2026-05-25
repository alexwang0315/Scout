from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from math import atan2, cos, radians, sin, sqrt

import numpy as np

from scout_risk.cp.parser import ParsedCPNote
from scout_risk.cp.scp import compute_scp
from scout_risk.dem.io import DEMGrid
from scout_risk.gpx.sampling import XYRoutePoint
from scout_risk.route.schemas import RiskConfidence, RouteRiskSample
from scout_risk.terrain_config import RouteRiskScoringConfig, SCPConfig


EARTH_RADIUS_M = 6_371_000.0


@dataclass(frozen=True)
class RouteRiskProfile:
    route_id: str
    samples: list[RouteRiskSample]


def build_route_risk_profile(
    *,
    route_id: str,
    dem: DEMGrid,
    teii: np.ndarray,
    route_points: list[XYRoutePoint],
    cp_notes: list[ParsedCPNote] | None = None,
    cp_radius_m: float | None = None,
    risk_config: RouteRiskScoringConfig | None = None,
    scp_config: SCPConfig | None = None,
) -> RouteRiskProfile:
    risk_config = risk_config or RouteRiskScoringConfig()
    cp_radius_m = cp_radius_m if cp_radius_m is not None else risk_config.cp_radius_m
    samples: list[RouteRiskSample] = []
    previous_teii: deque[float] = deque(maxlen=risk_config.sri_previous_sample_count)
    notes = cp_notes or []
    for index, point in enumerate(route_points):
        row_col = dem.row_col_for_xy(point.x, point.y)
        if row_col is None:
            teii_value = 100.0
            terrain_explanations = ["DEM 覆蓋外，地形風險不確定，請放慢、確認現場路跡"]
            elevation = point.elevation_m
            lec = 100.0
        else:
            row, col = row_col
            teii_value = clamp(float(teii[row, col]))
            elevation = dem.sample_xy(point.x, point.y)
            terrain_explanations = _terrain_explanations(teii_value, risk_config)
            lec = _lec_at(
                teii,
                dem,
                row,
                col,
                radius_m=risk_config.lec_radius_m,
                percentile=risk_config.lec_percentile,
            )
        sri = _sri(teii_value, list(previous_teii), risk_config)
        previous_teii.append(teii_value)
        tri = _tri(teii, dem, row_col, risk_config)
        matching_notes = _nearby_cp_notes(point, notes, cp_radius_m=cp_radius_m)
        scp_value = max(
            (compute_scp(note, config=scp_config) for note in matching_notes),
            default=0.0,
        )
        hazard_types = sorted(
            {
                hazard
                for note in matching_notes
                for hazard in note.hazard_types
            }
        )
        blended_terrain_risk = (
            risk_config.terrain_blend_teii_weight * teii_value
            + risk_config.terrain_blend_tri_weight * tri
            + risk_config.terrain_blend_sri_weight * sri
            + risk_config.terrain_blend_lec_weight * lec
        )
        terrain_risk = (
            max(teii_value, blended_terrain_risk)
            if risk_config.terrain_risk_floor_to_teii
            else blended_terrain_risk
        )
        pretrip_risk = clamp(
            risk_config.pretrip_terrain_weight * terrain_risk
            + risk_config.pretrip_scp_weight * scp_value
        )
        explanations = [
            *terrain_explanations,
            *_cp_explanations(matching_notes),
        ]
        samples.append(
            RouteRiskSample(
                route_id=route_id,
                sample_id=f"{route_id}.sample.{index:04d}",
                distance_m=round(point.distance_m, 2),
                lat=point.lat,
                lon=point.lon,
                x=point.x,
                y=point.y,
                elevation_m=elevation,
                teii_20m=round(teii_value, 2),
                tri=round(tri, 2),
                sri=round(sri, 2),
                lec=round(lec, 2),
                scp=round(scp_value, 2),
                pretrip_risk=round(pretrip_risk, 2),
                risk_level=risk_level(
                    pretrip_risk,
                    thresholds=risk_config.risk_level_thresholds,
                ),
                hazard_types=hazard_types,
                confidence=RiskConfidence(
                    scp_confidence="medium" if matching_notes else "low"
                ),
                explanation=explanations,
            )
        )
    return RouteRiskProfile(route_id=route_id, samples=samples)


def risk_level(
    score: float,
    *,
    thresholds: list[float] | None = None,
) -> int:
    thresholds = thresholds or RouteRiskScoringConfig().risk_level_thresholds
    if score < thresholds[0]:
        return 1
    if score < thresholds[1]:
        return 2
    if score < thresholds[2]:
        return 3
    if score < thresholds[3]:
        return 4
    return 5


def clamp(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def _tri(
    teii: np.ndarray,
    dem: DEMGrid,
    row_col: tuple[int, int] | None,
    config: RouteRiskScoringConfig,
) -> float:
    if row_col is None:
        return 100.0
    row, col = row_col
    radius = config.tri_radius_cells
    window = teii[
        max(0, row - radius) : min(teii.shape[0], row + radius + 1),
        max(0, col - radius) : min(teii.shape[1], col + radius + 1),
    ]
    high_ratio = float(np.mean(window >= config.tri_high_threshold)) * 100.0
    moving_avg = float(np.mean(window))
    return clamp(
        config.tri_high_ratio_weight * high_ratio
        + config.tri_mean_weight * moving_avg
    )


def _sri(
    current_teii: float,
    previous_values: list[float],
    config: RouteRiskScoringConfig,
) -> float:
    if not previous_values:
        return 0.0
    previous_avg = sum(previous_values) / len(previous_values)
    return clamp(max(0.0, current_teii - previous_avg) / config.sri_scale * 100.0)


def _lec_at(
    teii: np.ndarray,
    dem: DEMGrid,
    row: int,
    col: int,
    *,
    radius_m: float,
    percentile: float,
) -> float:
    radius_cells = max(1, int(round(radius_m / dem.pixel_size)))
    window = teii[
        max(0, row - radius_cells) : min(teii.shape[0], row + radius_cells + 1),
        max(0, col - radius_cells) : min(teii.shape[1], col + radius_cells + 1),
    ]
    return clamp(float(np.percentile(window, percentile)))


def _nearby_cp_notes(
    point: XYRoutePoint,
    notes: list[ParsedCPNote],
    *,
    cp_radius_m: float,
) -> list[ParsedCPNote]:
    matches: list[ParsedCPNote] = []
    for note in notes:
        if note.lat is None or note.lon is None or point.lat is None or point.lon is None:
            continue
        if _haversine_m(point.lat, point.lon, note.lat, note.lon) <= cp_radius_m:
            matches.append(note)
    return matches


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1 = radians(lat1)
    phi2 = radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    h = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return EARTH_RADIUS_M * 2 * atan2(sqrt(h), sqrt(1 - h))


def _terrain_explanations(
    teii_value: float,
    config: RouteRiskScoringConfig,
) -> list[str]:
    if teii_value >= config.teii_extreme_threshold:
        return ["TEII_20m 顯示極低容錯地形，請放慢、確認現場路跡"]
    if teii_value >= config.teii_low_tolerance_threshold:
        return ["TEII_20m 顯示低容錯地形，請放慢並保守通過"]
    if teii_value >= config.teii_caution_threshold:
        return ["TEII_20m 顯示需注意地形，維持現場確認"]
    return ["TEII_20m 顯示相對 lower risk，但仍需依現場路況確認"]


def _cp_explanations(notes: list[ParsedCPNote]) -> list[str]:
    explanations: list[str] = []
    for note in notes:
        if note.matched_keywords:
            keywords = "、".join(note.matched_keywords)
            explanations.append(f"CP note 標註 {keywords}，請放慢、確認現場路跡")
    return explanations
