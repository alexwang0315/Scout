from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from pretrip_models import PreTripArtifactKind, PreTripProvenance, PreTripSourceArtifact, RouteBBox


CONVERSION_RULE_VERSION = "overpass-vector-evidence.v1"
TRAIL_HIGHWAYS = {"path", "footway", "track", "steps", "bridleway", "pedestrian"}
ROAD_ACCESS_HIGHWAYS = {"service", "tertiary", "unclassified"}
ROUTE_CORRIDOR_HIGHWAY_VALUES = (
    "path",
    "footway",
    "track",
    "steps",
    "bridleway",
    "pedestrian",
    "service",
    "tertiary",
    "unclassified",
)
ROUTE_CORRIDOR_HIGHWAYS = set(ROUTE_CORRIDOR_HIGHWAY_VALUES)
ROUTE_CORRIDOR_HIGHWAY_PATTERN = f"^({'|'.join(ROUTE_CORRIDOR_HIGHWAY_VALUES)})$"

OverpassOsmType = Literal["node", "way", "relation"]
OverpassCandidateType = Literal[
    "trail_corridor_candidate",
    "hiking_route_candidate",
    "shelter_candidate",
    "water_source_candidate",
    "parking_candidate",
    "peak_candidate",
    "terrain_risk_candidate",
]
ScoutMapFeatureType = Literal["approved_corridor", "hazard_zone", "poi"]
Confidence = Literal["low", "medium", "high", "unknown"]
StaleRisk = Literal["low", "medium", "high"]


class OverpassRequestEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_body: str
    bbox_wgs84: RouteBBox | None = None
    route_corridor: dict[str, Any] | None = None
    request_timestamp: str
    endpoint: str
    http_status: int = Field(ge=100, le=599)
    raw_payload_uri: str
    raw_response_sha256: str
    normalized_artifact_path: str
    conversion_rule_version: str = CONVERSION_RULE_VERSION


class OverpassObjectEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    osm_type: OverpassOsmType
    osm_id: int
    tags: dict[str, Any] = Field(default_factory=dict)
    candidate_type: OverpassCandidateType | None = None
    feature_type: ScoutMapFeatureType | None = None
    confidence: Confidence = "unknown"
    stale_risk: StaleRisk = "medium"
    geometry: dict[str, Any] | None = None
    skipped_reason: str | None = None
    linked_route_ref: str | None = None
    linked_segment_ref: str | None = None
    linked_checkpoint_ref: str | None = None


class OverpassPlanningCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    candidate_type: OverpassCandidateType
    label: str
    osm_type: OverpassOsmType
    osm_id: int
    tags: dict[str, Any] = Field(default_factory=dict)
    geometry: dict[str, Any]
    feature_type: ScoutMapFeatureType
    geojson_feature: dict[str, Any]
    source_refs: list[str] = Field(default_factory=list)
    source_attribution: list[dict[str, Any]] = Field(default_factory=list)
    provenance: list[PreTripProvenance] = Field(default_factory=list)
    extractor_version: str = CONVERSION_RULE_VERSION
    pydantic_ai_prompt_version: str = "not_applicable_deterministic_overpass_ingest"
    model_output_sha256: str = ""
    model_output_summary: str = ""
    conversion_rule_version: str = CONVERSION_RULE_VERSION
    confidence: Confidence = "unknown"
    stale_risk: StaleRisk = "medium"
    review_state: Literal["needs_review"] = "needs_review"
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    linked_route_ref: str | None = None
    linked_segment_ref: str | None = None
    linked_checkpoint_ref: str | None = None
    notes: str = "Overpass/OSM vector evidence is a pretrip planning candidate; it is not runtime safety truth."


class OverpassIngestResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_artifact: PreTripSourceArtifact
    request: OverpassRequestEvidence
    object_evidence: list[OverpassObjectEvidence] = Field(default_factory=list)
    skipped_objects: list[OverpassObjectEvidence] = Field(default_factory=list)
    candidates: list[OverpassPlanningCandidate] = Field(default_factory=list)
    normalized_geojson: dict[str, Any]

    @property
    def counts(self) -> dict[str, int]:
        by_type: dict[str, int] = {}
        for candidate in self.candidates:
            by_type[candidate.candidate_type] = by_type.get(candidate.candidate_type, 0) + 1
        return {
            "objects": len(self.object_evidence) + len(self.skipped_objects),
            "candidates": len(self.candidates),
            "skipped": len(self.skipped_objects),
            **by_type,
        }


def load_overpass_evidence_candidates(
    raw_payload_path: Path | str,
    *,
    query_body: str,
    bbox_wgs84: RouteBBox | None = None,
    route_corridor: dict[str, Any] | None = None,
    request_timestamp: str,
    endpoint: str,
    http_status: int,
    normalized_artifact_path: Path | str,
    source_ref: str | None = None,
) -> OverpassIngestResult:
    source = Path(raw_payload_path)
    raw_bytes = source.read_bytes()
    payload = json.loads(raw_bytes.decode("utf-8"))
    return import_overpass_evidence_candidates(
        payload,
        query_body=query_body,
        bbox_wgs84=bbox_wgs84,
        route_corridor=route_corridor,
        request_timestamp=request_timestamp,
        endpoint=endpoint,
        http_status=http_status,
        raw_payload_uri=source.as_posix(),
        raw_response_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        normalized_artifact_path=str(normalized_artifact_path),
        source_ref=source_ref or source.stem,
    )


def import_overpass_evidence_candidates(
    payload: dict[str, Any],
    *,
    query_body: str,
    bbox_wgs84: RouteBBox | None,
    route_corridor: dict[str, Any] | None = None,
    request_timestamp: str,
    endpoint: str,
    http_status: int,
    raw_payload_uri: str,
    raw_response_sha256: str | None = None,
    normalized_artifact_path: str,
    source_ref: str,
) -> OverpassIngestResult:
    if not isinstance(payload.get("elements"), list):
        raise ValueError("Overpass payload must include an elements array")

    raw_hash = raw_response_sha256 or _payload_sha256(payload)
    request = OverpassRequestEvidence(
        query_body=query_body,
        bbox_wgs84=bbox_wgs84,
        route_corridor=route_corridor,
        request_timestamp=request_timestamp,
        endpoint=endpoint,
        http_status=http_status,
        raw_payload_uri=raw_payload_uri,
        raw_response_sha256=raw_hash,
        normalized_artifact_path=normalized_artifact_path,
    )
    provenance = _provenance(source_ref=source_ref, request=request)
    source_artifact = _source_artifact(source_ref=source_ref, request=request, payload=payload, provenance=provenance)

    object_evidence: list[OverpassObjectEvidence] = []
    skipped_objects: list[OverpassObjectEvidence] = []
    candidates: list[OverpassPlanningCandidate] = []
    features: list[dict[str, Any]] = []

    for element in payload["elements"]:
        evidence, candidate = _candidate_from_element(
            element,
            request=request,
            source_ref=source_ref,
            provenance=provenance,
        )
        if evidence.skipped_reason:
            skipped_objects.append(evidence)
            continue
        object_evidence.append(evidence)
        if candidate is not None:
            candidates.append(candidate)
            features.append(candidate.geojson_feature)

    normalized_geojson = {
        "artifact_kind": "pretrip_overpass_vector_evidence",
        "schema_version": "route_corridor_map_preparation.v1",
        "route_scope_ref": (
            (route_corridor or {}).get("route_evidence_bundle_ref")
            or "normalized/routes/route_evidence_bundle.json"
        ),
        "status": "ready",
        "type": "FeatureCollection",
        "properties": {
            "source": "overpass_osm",
            "source_version": CONVERSION_RULE_VERSION,
            "confidence": 0.55,
            "last_verified_at": request_timestamp,
            "known_staleness_risk": "medium",
            "query_body": query_body,
            "bbox_wgs84": bbox_wgs84.model_dump(mode="json") if bbox_wgs84 else None,
            "route_corridor": route_corridor,
            "endpoint": endpoint,
            "http_status": http_status,
            "raw_payload_uri": raw_payload_uri,
            "raw_response_sha256": raw_hash,
            "normalized_artifact_path": normalized_artifact_path,
            "conversion_rule_version": CONVERSION_RULE_VERSION,
            "candidate_layer": "pretrip_overpass_vector_evidence",
            "runtime_truth": False,
        },
        "boundary": {
            "candidate_only": True,
            "runtime_truth": False,
            "runtime_safety_truth": False,
            "phase1_runtime_mutation_allowed": False,
            "phase2_brain_writeback_allowed": False,
            "raw_gpx_embedded_in_json": False,
        },
        "features": features,
    }

    return OverpassIngestResult(
        source_artifact=source_artifact,
        request=request,
        object_evidence=object_evidence,
        skipped_objects=skipped_objects,
        candidates=candidates,
        normalized_geojson=normalized_geojson,
    )


def _candidate_from_element(
    element: dict[str, Any],
    *,
    request: OverpassRequestEvidence,
    source_ref: str,
    provenance: PreTripProvenance,
) -> tuple[OverpassObjectEvidence, OverpassPlanningCandidate | None]:
    osm_type = element.get("type")
    osm_id = element.get("id")
    if osm_type not in {"node", "way", "relation"} or not isinstance(osm_id, int):
        return _skipped(element, "Overpass element must include supported type and integer id"), None

    tags = element.get("tags") or {}
    if not isinstance(tags, dict):
        return _skipped(element, "Overpass element tags must be an object when present"), None

    rule = _classification(osm_type, tags)
    if rule is None:
        return (
            OverpassObjectEvidence(
                osm_type=osm_type,
                osm_id=osm_id,
                tags=tags,
                skipped_reason="OSM tags do not map to a Scout Phase A planning candidate",
            ),
            None,
        )

    geometry, skipped_reason = _geometry_for_rule(element, rule)
    if skipped_reason is not None:
        return (
            OverpassObjectEvidence(
                osm_type=osm_type,
                osm_id=osm_id,
                tags=tags,
                candidate_type=rule["candidate_type"],
                feature_type=rule["feature_type"],
                confidence=rule["confidence"],
                stale_risk=rule["stale_risk"],
                skipped_reason=skipped_reason,
            ),
            None,
        )

    evidence = OverpassObjectEvidence(
        osm_type=osm_type,
        osm_id=osm_id,
        tags=tags,
        candidate_type=rule["candidate_type"],
        feature_type=rule["feature_type"],
        confidence=rule["confidence"],
        stale_risk=rule["stale_risk"],
        geometry=geometry,
    )
    feature = _geojson_feature(
        evidence=evidence,
        label=_label(tags, osm_type, osm_id),
        request=request,
        source_ref=source_ref,
    )
    candidate_id = feature["properties"]["id"]
    source_attribution = [
        {
            "source_kind": "overpass_osm_vector",
            "source_ref": source_ref,
            "source_candidate_id": candidate_id,
            "source_artifact_id": source_ref,
            "source_label": feature["properties"]["name"],
            "evidence_type": "pretrip_overpass_vector_candidate",
            "confidence": rule["confidence"],
            "stale_risk": rule["stale_risk"],
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
    ]
    provenance_hash = _payload_sha256(
        {
            "candidate_id": candidate_id,
            "osm_type": osm_type,
            "osm_id": osm_id,
            "source_ref": source_ref,
            "raw_response_sha256": request.raw_response_sha256,
            "conversion_rule_version": request.conversion_rule_version,
        }
    )
    feature["properties"].update(
        {
            "source_refs": [source_ref],
            "source_attribution": source_attribution,
            "extractor_version": CONVERSION_RULE_VERSION,
            "pydantic_ai_prompt_version": (
                "not_applicable_deterministic_overpass_ingest"
            ),
            "model_output_sha256": provenance_hash,
            "model_output_summary": (
                "Deterministic Overpass/OSM vector normalization produced a "
                "pretrip planning candidate; not runtime safety truth."
            ),
            "review_state": "needs_review",
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
    )
    candidate = OverpassPlanningCandidate(
        candidate_id=candidate_id,
        candidate_type=rule["candidate_type"],
        label=feature["properties"]["name"],
        osm_type=osm_type,
        osm_id=osm_id,
        tags=tags,
        geometry=geometry,
        feature_type=rule["feature_type"],
        geojson_feature=feature,
        source_refs=[source_ref],
        source_attribution=source_attribution,
        provenance=[provenance],
        model_output_sha256=provenance_hash,
        model_output_summary=(
            "Deterministic Overpass/OSM vector normalization produced a "
            "pretrip planning candidate; not runtime safety truth."
        ),
        confidence=rule["confidence"],
        stale_risk=rule["stale_risk"],
    )
    return evidence, candidate


def _classification(osm_type: str, tags: dict[str, Any]) -> dict[str, Any] | None:
    if osm_type == "node":
        if tags.get("natural") == "peak":
            return _rule("peak_candidate", "poi", "medium", "medium")
        if tags.get("amenity") == "parking" or "parking" in tags:
            return _rule("parking_candidate", "poi", "medium", "medium")
        if (
            tags.get("natural") == "spring"
            or tags.get("amenity") == "drinking_water"
            or tags.get("man_made") == "water_tap"
        ):
            return _rule("water_source_candidate", "poi", "low", "high")
        if tags.get("amenity") == "shelter" or tags.get("tourism") in {"wilderness_hut", "alpine_hut"}:
            return _rule("shelter_candidate", "poi", "medium", "high")

    if _is_terrain_risk(tags):
        return _rule("terrain_risk_candidate", "hazard_zone", "low", "high")

    if tags.get("route") == "hiking" or (tags.get("type") == "route" and tags.get("route") == "hiking"):
        return _rule("hiking_route_candidate", "approved_corridor", "medium", "medium")

    if str(tags.get("highway", "")).strip().lower() in ROUTE_CORRIDOR_HIGHWAYS:
        return _rule("trail_corridor_candidate", "approved_corridor", "medium", "medium")

    return None


def _rule(
    candidate_type: OverpassCandidateType,
    feature_type: ScoutMapFeatureType,
    confidence: Confidence,
    stale_risk: StaleRisk,
) -> dict[str, Any]:
    return {
        "candidate_type": candidate_type,
        "feature_type": feature_type,
        "confidence": confidence,
        "stale_risk": stale_risk,
    }


def _is_terrain_risk(tags: dict[str, Any]) -> bool:
    if "hazard" in tags or "risk" in tags:
        return True
    return tags.get("natural") in {"cliff", "scree", "bare_rock"} or tags.get("geological") in {"landslide"}


def _geometry_for_rule(element: dict[str, Any], rule: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    feature_type = rule["feature_type"]
    if feature_type == "poi":
        return _point_geometry(element)
    if feature_type == "approved_corridor":
        return _line_geometry(element)
    if feature_type == "hazard_zone":
        return _polygon_geometry(element)
    return None, f"Unsupported Scout map feature type: {feature_type}"


def _point_geometry(element: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    if element.get("type") != "node" or "lat" not in element or "lon" not in element:
        return None, "POI candidate requires node lat/lon geometry"
    return {"type": "Point", "coordinates": [float(element["lon"]), float(element["lat"])]}, None


def _line_geometry(element: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    if element.get("type") == "relation":
        return _relation_line_geometry(element)
    coordinates = _element_line_coordinates(element)
    if coordinates is None:
        return None, "Line candidate requires complete Overpass geometry coordinates"
    if len(coordinates) < 2:
        return None, "Line candidate requires at least two complete geometry points"
    return {"type": "LineString", "coordinates": coordinates}, None


def _polygon_geometry(element: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    coordinates = _element_line_coordinates(element)
    if coordinates is None:
        return None, "Terrain risk candidate requires complete Overpass geometry coordinates"
    if len(coordinates) < 4:
        return None, "Terrain risk candidate requires at least four polygon coordinates"
    if coordinates[0] != coordinates[-1]:
        return None, "Terrain risk candidate requires closed polygon geometry"
    return {"type": "Polygon", "coordinates": [coordinates]}, None


def _element_line_coordinates(element: dict[str, Any]) -> list[list[float]] | None:
    if element.get("type") == "relation":
        return _relation_line_coordinates(element)
    geometry = element.get("geometry")
    if not isinstance(geometry, list):
        return None
    return _geometry_points(geometry)


def _relation_line_coordinates(element: dict[str, Any]) -> list[list[float]] | None:
    members = element.get("members")
    if not isinstance(members, list):
        return None
    coordinates: list[list[float]] = []
    for member in members:
        geometry = member.get("geometry") if isinstance(member, dict) else None
        if not isinstance(geometry, list):
            continue
        member_coordinates = _geometry_points(geometry)
        if member_coordinates is None:
            return None
        for coordinate in member_coordinates:
            if not coordinates or coordinates[-1] != coordinate:
                coordinates.append(coordinate)
    return coordinates


def _relation_line_geometry(element: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    members = element.get("members")
    if not isinstance(members, list):
        return None, "Line candidate requires complete Overpass geometry coordinates"
    lines: list[list[list[float]]] = []
    for member in members:
        geometry = member.get("geometry") if isinstance(member, dict) else None
        if not isinstance(geometry, list):
            continue
        member_coordinates = _geometry_points(geometry)
        if member_coordinates is None:
            return None, "Line candidate requires complete Overpass geometry coordinates"
        if len(member_coordinates) >= 2:
            lines.append(member_coordinates)
    if not lines:
        return None, "Line candidate requires complete Overpass geometry coordinates"
    if len(lines) == 1:
        return {"type": "LineString", "coordinates": lines[0]}, None
    return {"type": "MultiLineString", "coordinates": lines}, None


def _geometry_points(points: list[Any]) -> list[list[float]] | None:
    coordinates: list[list[float]] = []
    for point in points:
        if not isinstance(point, dict) or "lat" not in point or "lon" not in point:
            return None
        coordinates.append([float(point["lon"]), float(point["lat"])])
    return coordinates


def _geojson_feature(
    *,
    evidence: OverpassObjectEvidence,
    label: str,
    request: OverpassRequestEvidence,
    source_ref: str,
) -> dict[str, Any]:
    candidate_id = f"overpass.{evidence.candidate_type}.{evidence.osm_type}.{evidence.osm_id}"
    confidence_score = {"unknown": 0.5, "low": 0.35, "medium": 0.55, "high": 0.75}[evidence.confidence]
    properties = {
        "id": candidate_id,
        "name": label,
        "feature_type": evidence.feature_type,
        "candidate_type": evidence.candidate_type,
        "osm_type": evidence.osm_type,
        "osm_id": evidence.osm_id,
        "osm_tags": evidence.tags,
        "source": "overpass_osm",
        "source_ref": source_ref,
        "source_version": CONVERSION_RULE_VERSION,
        "confidence": confidence_score,
        "candidate_confidence": evidence.confidence,
        "known_staleness_risk": evidence.stale_risk,
        "last_verified_at": request.request_timestamp,
        "query_body": request.query_body,
        "bbox_wgs84": request.bbox_wgs84.model_dump(mode="json") if request.bbox_wgs84 else None,
        "route_corridor": request.route_corridor,
        "endpoint": request.endpoint,
        "http_status": request.http_status,
        "raw_payload_uri": request.raw_payload_uri,
        "raw_response_sha256": request.raw_response_sha256,
        "normalized_artifact_path": request.normalized_artifact_path,
        "conversion_rule_version": request.conversion_rule_version,
        "runtime_truth": False,
        "linked_route_ref": evidence.linked_route_ref,
        "linked_segment_ref": evidence.linked_segment_ref,
        "linked_checkpoint_ref": evidence.linked_checkpoint_ref,
    }
    if evidence.candidate_type in {"trail_corridor_candidate", "hiking_route_candidate"}:
        properties["route_level"] = evidence.candidate_type
    elif evidence.candidate_type in {
        "shelter_candidate",
        "water_source_candidate",
        "parking_candidate",
        "peak_candidate",
    }:
        properties["poi_type"] = _poi_type(evidence.candidate_type)
    elif evidence.candidate_type == "terrain_risk_candidate":
        properties["hazard_type"] = _hazard_type(evidence.tags)

    return {
        "type": "Feature",
        "properties": properties,
        "geometry": evidence.geometry,
    }


def _source_artifact(
    *,
    source_ref: str,
    request: OverpassRequestEvidence,
    payload: dict[str, Any],
    provenance: PreTripProvenance,
) -> PreTripSourceArtifact:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return PreTripSourceArtifact(
        artifact_id=f"overpass.raw.{_slug(source_ref)}",
        kind=PreTripArtifactKind.OVERPASS_RAW_PAYLOAD,
        uri=request.raw_payload_uri,
        media_type="application/json",
        sha256=request.raw_response_sha256,
        size_bytes=len(encoded),
        provenance=provenance,
        metadata={
            "candidate_layer": "pretrip_overpass_vector_evidence",
            "query_body": request.query_body,
            "bbox_wgs84": request.bbox_wgs84.model_dump(mode="json") if request.bbox_wgs84 else None,
            "route_corridor": request.route_corridor,
            "request_timestamp": request.request_timestamp,
            "endpoint": request.endpoint,
            "http_status": request.http_status,
            "raw_response_sha256": request.raw_response_sha256,
            "normalized_artifact_path": request.normalized_artifact_path,
            "conversion_rule_version": request.conversion_rule_version,
            "runtime_truth": False,
        },
    )


def _provenance(*, source_ref: str, request: OverpassRequestEvidence) -> PreTripProvenance:
    return PreTripProvenance(
        source_ref=source_ref,
        source_kind=PreTripArtifactKind.OVERPASS_RAW_PAYLOAD,
        uri=request.raw_payload_uri,
        captured_at=request.request_timestamp,
        collected_at=request.request_timestamp,
        license_note="OSM data via Overpass; verify ODbL attribution and freshness before review.",
        method="pretrip_overpass_ingest.import_overpass_evidence_candidates",
        notes="Fixture-backed Overpass vector evidence normalized into Phase 4 pretrip candidates only.",
    )


def _payload_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _skipped(element: dict[str, Any], reason: str) -> OverpassObjectEvidence:
    return OverpassObjectEvidence(
        osm_type=element.get("type", "node") if element.get("type") in {"node", "way", "relation"} else "node",
        osm_id=element.get("id") if isinstance(element.get("id"), int) else -1,
        tags=element.get("tags") if isinstance(element.get("tags"), dict) else {},
        skipped_reason=reason,
    )


def _label(tags: dict[str, Any], osm_type: str, osm_id: int) -> str:
    return str(tags.get("name") or tags.get("name:zh") or f"{osm_type}/{osm_id}")


def _poi_type(candidate_type: str) -> str:
    return {
        "shelter_candidate": "shelter",
        "water_source_candidate": "water_source",
        "parking_candidate": "parking",
        "peak_candidate": "peak",
    }.get(candidate_type, "unknown")


def _hazard_type(tags: dict[str, Any]) -> str:
    return str(
        tags.get("hazard")
        or tags.get("risk")
        or tags.get("natural")
        or tags.get("geological")
        or "terrain_risk"
    )


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
