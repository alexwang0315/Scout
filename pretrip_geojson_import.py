from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from offline_map_models import HazardZone, MapCoordinate, MapPoi, MapSourceMetadata, TrailCorridor
from pretrip_models import (
    CandidateReviewState,
    PreTripArtifactKind,
    PreTripProvenance,
    PreTripSourceArtifact,
)


DEFAULT_CORRIDOR_HALF_WIDTH_M = 3.0
DEFAULT_HAZARD_L2_DURATION_S = 30.0


class PreTripMapCandidateBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    label: str
    source_refs: list[str] = Field(default_factory=list)
    provenance: list[PreTripProvenance] = Field(default_factory=list)
    review_state: CandidateReviewState = CandidateReviewState.NEEDS_REVIEW
    review_required: bool = True
    source_metadata: MapSourceMetadata
    notes: str = "Imported as candidate map data; human review required before compilation."


class PreTripCorridorCandidate(PreTripMapCandidateBase):
    corridor: TrailCorridor


class PreTripPoiCandidate(PreTripMapCandidateBase):
    poi: MapPoi


class PreTripHazardCandidate(PreTripMapCandidateBase):
    hazard: HazardZone


class PreTripGeoJsonImportResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_artifact: PreTripSourceArtifact
    source_metadata: MapSourceMetadata
    corridor_candidates: list[PreTripCorridorCandidate] = Field(default_factory=list)
    poi_candidates: list[PreTripPoiCandidate] = Field(default_factory=list)
    hazard_candidates: list[PreTripHazardCandidate] = Field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        return {
            "corridors": len(self.corridor_candidates),
            "pois": len(self.poi_candidates),
            "hazards": len(self.hazard_candidates),
        }

    def all_candidates(
        self,
    ) -> list[PreTripCorridorCandidate | PreTripPoiCandidate | PreTripHazardCandidate]:
        return [*self.corridor_candidates, *self.poi_candidates, *self.hazard_candidates]


def load_pretrip_geojson_candidates(
    path: Path | str,
    *,
    source_ref: str | None = None,
) -> PreTripGeoJsonImportResult:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    return import_pretrip_geojson_candidates(payload, uri=str(source), source_ref=source_ref or source.stem)


def import_pretrip_geojson_candidates(
    payload: dict[str, Any],
    *,
    uri: str,
    source_ref: str,
) -> PreTripGeoJsonImportResult:
    if payload.get("type") != "FeatureCollection":
        raise ValueError("GeoJSON import must be a FeatureCollection")

    collection_properties = _properties(payload)
    collection_metadata = _source_metadata(collection_properties)
    source_artifact = _source_artifact(
        source_ref=source_ref,
        uri=uri,
        properties=collection_properties,
        payload=payload,
    )
    artifact_provenance = source_artifact.provenance

    corridor_candidates: list[PreTripCorridorCandidate] = []
    poi_candidates: list[PreTripPoiCandidate] = []
    hazard_candidates: list[PreTripHazardCandidate] = []

    for index, feature in enumerate(payload.get("features", []), start=1):
        if feature.get("type") != "Feature":
            raise ValueError(f"GeoJSON features must use Feature type at index {index}")

        properties = _properties(feature)
        geometry = feature.get("geometry") or {}
        geometry_type = geometry.get("type")
        feature_id = _feature_id(feature, properties, index)
        feature_metadata = _source_metadata(properties, fallback=collection_metadata)

        if geometry_type == "LineString":
            corridor = _corridor_from_feature(feature_id, properties, geometry, feature_metadata)
            corridor_candidates.append(
                PreTripCorridorCandidate(
                    candidate_id=f"map.corridor.{feature_id}",
                    label=corridor.name,
                    source_refs=[source_ref],
                    provenance=[artifact_provenance],
                    source_metadata=feature_metadata,
                    corridor=corridor,
                )
            )
        elif geometry_type == "Point":
            poi = _poi_from_feature(feature_id, properties, geometry, feature_metadata)
            poi_candidates.append(
                PreTripPoiCandidate(
                    candidate_id=f"map.poi.{feature_id}",
                    label=poi.name,
                    source_refs=[source_ref],
                    provenance=[artifact_provenance],
                    source_metadata=feature_metadata,
                    poi=poi,
                )
            )
        elif geometry_type == "Polygon":
            hazard = _hazard_from_feature(feature_id, properties, geometry, feature_metadata)
            hazard_candidates.append(
                PreTripHazardCandidate(
                    candidate_id=f"map.hazard.{feature_id}",
                    label=hazard.name,
                    source_refs=[source_ref],
                    provenance=[artifact_provenance],
                    source_metadata=feature_metadata,
                    hazard=hazard,
                )
            )
        else:
            raise ValueError(f"Unsupported GeoJSON geometry type for feature {feature_id}: {geometry_type}")

    return PreTripGeoJsonImportResult(
        source_artifact=source_artifact,
        source_metadata=collection_metadata,
        corridor_candidates=corridor_candidates,
        poi_candidates=poi_candidates,
        hazard_candidates=hazard_candidates,
    )


def _source_artifact(
    *,
    source_ref: str,
    uri: str,
    properties: dict[str, Any],
    payload: dict[str, Any],
) -> PreTripSourceArtifact:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return PreTripSourceArtifact(
        artifact_id=f"geojson.{_slug(source_ref)}",
        kind=PreTripArtifactKind.OTHER,
        uri=uri,
        media_type="application/geo+json",
        sha256=hashlib.sha256(encoded).hexdigest(),
        size_bytes=len(encoded),
        provenance=PreTripProvenance(
            source_ref=source_ref,
            source_kind=PreTripArtifactKind.OTHER,
            uri=uri,
            captured_at=properties.get("captured_at"),
            collected_at=properties.get("collected_at"),
            license_note=properties.get("license_note"),
            method="geojson_feature_collection_import",
            notes=properties.get("notes", "GeoJSON map import candidate layer."),
        ),
        metadata={
            "candidate_layer": "pretrip_map",
            "review_required": True,
            "source": properties.get("source"),
            "source_version": properties.get("source_version"),
        },
    )


def _corridor_from_feature(
    feature_id: str,
    properties: dict[str, Any],
    geometry: dict[str, Any],
    source_metadata: MapSourceMetadata,
) -> TrailCorridor:
    coordinates = _line_coordinates(geometry.get("coordinates", []), feature_id=feature_id)
    if len(coordinates) < 2:
        raise ValueError(f"LineString corridor {feature_id} must include at least two coordinates")

    return TrailCorridor(
        corridor_id=feature_id,
        name=properties.get("name", feature_id),
        coordinates=coordinates,
        corridor_half_width_m=float(properties.get("corridor_half_width_m", DEFAULT_CORRIDOR_HALF_WIDTH_M)),
        route_level=properties.get("route_level"),
        source_metadata=source_metadata,
    )


def _poi_from_feature(
    feature_id: str,
    properties: dict[str, Any],
    geometry: dict[str, Any],
    source_metadata: MapSourceMetadata,
) -> MapPoi:
    coordinate = geometry.get("coordinates", [])
    if len(coordinate) < 2:
        raise ValueError(f"Point POI {feature_id} must include lon/lat coordinates")
    lon, lat = coordinate[:2]

    return MapPoi(
        poi_id=feature_id,
        poi_type=properties.get("poi_type", properties.get("feature_type", "unknown")),
        name=properties.get("name", feature_id),
        coordinate=MapCoordinate(lat=float(lat), lon=float(lon)),
        source_metadata=source_metadata,
    )


def _hazard_from_feature(
    feature_id: str,
    properties: dict[str, Any],
    geometry: dict[str, Any],
    source_metadata: MapSourceMetadata,
) -> HazardZone:
    rings = geometry.get("coordinates", [])
    if not rings:
        raise ValueError(f"Polygon hazard {feature_id} must include an outer ring")
    polygon = _line_coordinates(rings[0], feature_id=feature_id)
    if len(polygon) < 4:
        raise ValueError(f"Polygon hazard {feature_id} must include a closed outer ring")
    if polygon[0] != polygon[-1]:
        raise ValueError(f"Polygon hazard {feature_id} outer ring must be closed")

    return HazardZone(
        hazard_id=feature_id,
        hazard_type=properties.get("hazard_type", properties.get("feature_type", "unknown")),
        name=properties.get("name", feature_id),
        polygon=polygon,
        l2_duration_s=float(properties.get("l2_duration_s", DEFAULT_HAZARD_L2_DURATION_S)),
        source_metadata=source_metadata,
    )


def _line_coordinates(coordinates: list[list[float]], *, feature_id: str) -> list[MapCoordinate]:
    converted: list[MapCoordinate] = []
    for coordinate in coordinates:
        if len(coordinate) < 2:
            raise ValueError(f"Feature {feature_id} contains an invalid lon/lat coordinate")
        lon, lat = coordinate[:2]
        converted.append(MapCoordinate(lat=float(lat), lon=float(lon)))
    return converted


def _source_metadata(
    properties: dict[str, Any],
    *,
    fallback: MapSourceMetadata | None = None,
) -> MapSourceMetadata:
    if fallback is not None and "source" not in properties:
        return fallback

    return MapSourceMetadata(
        source=properties.get("source", "geojson_import"),
        source_version=properties.get("source_version", "unknown"),
        confidence=float(properties.get("confidence", 0.5)),
        last_verified_at=properties.get("last_verified_at"),
        known_staleness_risk=properties.get("known_staleness_risk", "medium"),
    )


def _properties(item: dict[str, Any]) -> dict[str, Any]:
    properties = item.get("properties") or {}
    if not isinstance(properties, dict):
        raise ValueError("GeoJSON properties must be an object when present")
    return properties


def _feature_id(feature: dict[str, Any], properties: dict[str, Any], index: int) -> str:
    raw_id = properties.get("id") or feature.get("id") or f"feature-{index:03d}"
    return _slug(str(raw_id))


def _slug(value: str) -> str:
    normalized = []
    for character in value.strip().lower():
        if character.isalnum():
            normalized.append(character)
        elif character in {"-", "_", ".", ":"}:
            normalized.append(character)
        elif character.isspace():
            normalized.append("-")
    slug = "".join(normalized).strip("-._:")
    return slug or "unknown"
