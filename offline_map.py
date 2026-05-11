from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from geo_utils import haversine_m
from offline_map_models import (
    CorridorEvidence,
    HazardEvidence,
    HazardZone,
    MapCoordinate,
    MapPoi,
    MapSourceMetadata,
    TrailCorridor,
)


DEFAULT_CORRIDOR_HALF_WIDTH_M = 3.0


@dataclass(frozen=True)
class OfflineMapContext:
    source: Path
    source_metadata: MapSourceMetadata
    corridors: list[TrailCorridor]
    hazards: list[HazardZone]
    pois: list[MapPoi]

    def corridor_evidence(
        self,
        lat: float,
        lon: float,
        *,
        position_uncertainty_m: float = 0.0,
    ) -> CorridorEvidence:
        best_corridor: TrailCorridor | None = None
        best_distance = float("inf")
        for corridor in self.corridors:
            distance = _distance_to_polyline_m(lat, lon, corridor.coordinates)
            if distance < best_distance:
                best_distance = distance
                best_corridor = corridor

        if best_corridor is None:
            return CorridorEvidence(
                inside=False,
                distance_m=float("inf"),
                allowed_distance_m=position_uncertainty_m,
            )

        allowed_distance = best_corridor.corridor_half_width_m + max(0.0, position_uncertainty_m)
        return CorridorEvidence(
            inside=best_distance <= allowed_distance,
            corridor_id=best_corridor.corridor_id,
            distance_m=best_distance,
            allowed_distance_m=allowed_distance,
            source_metadata=best_corridor.source_metadata,
        )

    def hazards_at(self, lat: float, lon: float) -> list[HazardEvidence]:
        evidence: list[HazardEvidence] = []
        for hazard in self.hazards:
            if _point_in_polygon(lat, lon, hazard.polygon):
                evidence.append(
                    HazardEvidence(
                        hazard_id=hazard.hazard_id,
                        hazard_type=hazard.hazard_type,
                        name=hazard.name,
                        l2_duration_s=hazard.l2_duration_s,
                        source_metadata=hazard.source_metadata,
                    )
                )
        return evidence


def load_offline_map_context(path: Path | str) -> OfflineMapContext:
    source = Path(path)
    payload = json.loads(source.read_text())
    if payload.get("type") != "FeatureCollection":
        raise ValueError(f"Offline map context must be a GeoJSON FeatureCollection: {source}")

    metadata = _source_metadata(payload.get("properties", {}))
    corridors: list[TrailCorridor] = []
    hazards: list[HazardZone] = []
    pois: list[MapPoi] = []

    for feature in payload.get("features", []):
        properties = feature.get("properties", {})
        geometry = feature.get("geometry", {})
        feature_type = properties.get("feature_type")
        feature_metadata = _source_metadata(properties, fallback=metadata)

        if feature_type == "approved_corridor":
            corridors.append(_corridor_from_feature(properties, geometry, feature_metadata))
        elif feature_type == "hazard_zone":
            hazards.append(_hazard_from_feature(properties, geometry, feature_metadata))
        elif feature_type == "poi":
            pois.append(_poi_from_feature(properties, geometry, feature_metadata))

    return OfflineMapContext(
        source=source,
        source_metadata=metadata,
        corridors=corridors,
        hazards=hazards,
        pois=pois,
    )


def _source_metadata(properties: dict[str, Any], fallback: MapSourceMetadata | None = None) -> MapSourceMetadata:
    if fallback is not None and "source" not in properties:
        return fallback
    return MapSourceMetadata(
        source=properties.get("source", "synthetic_fixture"),
        source_version=properties.get("source_version", "unknown"),
        confidence=float(properties.get("confidence", 0.5)),
        last_verified_at=properties.get("last_verified_at"),
        known_staleness_risk=properties.get("known_staleness_risk", "medium"),
    )


def _corridor_from_feature(
    properties: dict[str, Any],
    geometry: dict[str, Any],
    source_metadata: MapSourceMetadata,
) -> TrailCorridor:
    if geometry.get("type") != "LineString":
        raise ValueError("Approved corridor features must use LineString geometry")
    return TrailCorridor(
        corridor_id=properties["id"],
        name=properties.get("name", properties["id"]),
        coordinates=_line_coordinates(geometry["coordinates"]),
        corridor_half_width_m=float(properties.get("corridor_half_width_m", DEFAULT_CORRIDOR_HALF_WIDTH_M)),
        route_level=properties.get("route_level"),
        source_metadata=source_metadata,
    )


def _hazard_from_feature(
    properties: dict[str, Any],
    geometry: dict[str, Any],
    source_metadata: MapSourceMetadata,
) -> HazardZone:
    if geometry.get("type") != "Polygon":
        raise ValueError("Hazard zone features must use Polygon geometry")
    rings = geometry.get("coordinates", [])
    if not rings:
        raise ValueError("Hazard zone polygon must include an outer ring")
    return HazardZone(
        hazard_id=properties["id"],
        hazard_type=properties.get("hazard_type", "unknown"),
        name=properties.get("name", properties["id"]),
        polygon=_line_coordinates(rings[0]),
        l2_duration_s=float(properties.get("l2_duration_s", 30.0)),
        source_metadata=source_metadata,
    )


def _poi_from_feature(
    properties: dict[str, Any],
    geometry: dict[str, Any],
    source_metadata: MapSourceMetadata,
) -> MapPoi:
    if geometry.get("type") != "Point":
        raise ValueError("POI features must use Point geometry")
    lon, lat = geometry["coordinates"]
    return MapPoi(
        poi_id=properties["id"],
        poi_type=properties.get("poi_type", "unknown"),
        name=properties.get("name", properties["id"]),
        coordinate=MapCoordinate(lat=float(lat), lon=float(lon)),
        source_metadata=source_metadata,
    )


def _line_coordinates(coordinates: list[list[float]]) -> list[MapCoordinate]:
    return [MapCoordinate(lat=float(lat), lon=float(lon)) for lon, lat in coordinates]


def _distance_to_polyline_m(lat: float, lon: float, coordinates: list[MapCoordinate]) -> float:
    if len(coordinates) == 1:
        point = coordinates[0]
        return haversine_m(lat, lon, point.lat, point.lon)

    best = float("inf")
    ref_lat = lat
    for start, end in zip(coordinates, coordinates[1:]):
        distance = _distance_to_segment_m(lat, lon, start, end, ref_lat)
        if distance < best:
            best = distance
    return best


def _distance_to_segment_m(
    lat: float,
    lon: float,
    start: MapCoordinate,
    end: MapCoordinate,
    ref_lat: float,
) -> float:
    px, py = _to_local_xy_m(lat, lon, ref_lat)
    ax, ay = _to_local_xy_m(start.lat, start.lon, ref_lat)
    bx, by = _to_local_xy_m(end.lat, end.lon, ref_lat)
    dx = bx - ax
    dy = by - ay
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    nearest_x = ax + t * dx
    nearest_y = ay + t * dy
    return ((px - nearest_x) ** 2 + (py - nearest_y) ** 2) ** 0.5


def _point_in_polygon(lat: float, lon: float, polygon: list[MapCoordinate]) -> bool:
    inside = False
    j = len(polygon) - 1
    for i, point in enumerate(polygon):
        previous = polygon[j]
        crosses = (point.lat > lat) != (previous.lat > lat)
        if crosses:
            slope_lon = (previous.lon - point.lon) * (lat - point.lat) / (previous.lat - point.lat) + point.lon
            if lon < slope_lon:
                inside = not inside
        j = i
    return inside


def _to_local_xy_m(lat: float, lon: float, ref_lat: float) -> tuple[float, float]:
    meters_per_deg_lat = 111_320.0
    meters_per_deg_lon = 111_320.0 * math.cos(math.radians(ref_lat))
    return lon * meters_per_deg_lon, lat * meters_per_deg_lat
