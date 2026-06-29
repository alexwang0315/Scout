from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pretrip_models import RouteBBox
from pretrip_overpass_ingest import import_overpass_evidence_candidates


CONVERSION_RULE_VERSION = "osm-pbf-local-evidence.v1"
FEATURE_INDEX_VERSION = "osm-pbf-local-feature-index.v1"
OSM_PBF_FILTER_SPECS = (
    "w/highway=path,footway,track,steps,bridleway,pedestrian",
    "r/type=route",
    "r/route=hiking",
    "n/tourism=wilderness_hut,alpine_hut",
    "n/amenity=shelter,drinking_water,parking",
    "n/natural=spring,peak",
    "w/natural=cliff,scree,bare_rock",
    "w/geological=landslide",
)

OSM_PBF_FEATURE_CATEGORIES: dict[str, dict[str, str]] = {
    "trail_network": {
        "label": "OSM trail network（OSM 步道路網）",
        "timeline_group": "OSM Trails",
    },
    "milestone_route_marker": {
        "label": "OSM mileage / route markers（OSM 里程與路標）",
        "timeline_group": "OSM Milestones",
    },
    "mobile_signal": {
        "label": "OSM mobile signal points（OSM 通訊點）",
        "timeline_group": "OSM Mobile",
    },
    "peak_terrain": {
        "label": "OSM peaks / terrain POI（OSM 山峰地形點）",
        "timeline_group": "OSM Peaks",
    },
    "terrain_risk_context": {
        "label": "OSM terrain risk context（OSM 地形風險脈絡）",
        "timeline_group": "OSM Terrain",
    },
    "water_hydrology": {
        "label": "OSM water / hydrology（OSM 水源水系）",
        "timeline_group": "OSM Water",
    },
    "amenity_poi": {
        "label": "OSM amenities / POI（OSM 設施與興趣點）",
        "timeline_group": "OSM POI",
    },
    "infrastructure": {
        "label": "OSM infrastructure（OSM 基礎設施）",
        "timeline_group": "OSM Infrastructure",
    },
    "landcover_structure": {
        "label": "OSM landcover / structures（OSM 地表覆蓋與建物）",
        "timeline_group": "OSM Landcover",
    },
    "other_osm_feature": {
        "label": "Other OSM features（其他 OSM 圖徵）",
        "timeline_group": "OSM Other",
    },
}
_NODE_MATCH_KEYS = frozenset({"natural", "amenity", "tourism", "man_made"})
_WAY_MATCH_KEYS = frozenset({"highway", "natural", "geological", "hazard", "risk"})
_RELATION_MATCH_KEYS = frozenset({"route", "type"})
_OSM_PBF_NATIVE_FILTER_KEYS = tuple(
    sorted(_NODE_MATCH_KEYS | _WAY_MATCH_KEYS | _RELATION_MATCH_KEYS)
)


@dataclass(frozen=True)
class OsmiumExtractionPlan:
    pbf_path: Path
    bbox_wgs84: dict[str, float]
    bbox_arg: str
    extracted_pbf_path: Path
    raw_osm_json_path: Path
    commands: tuple[tuple[str, ...], ...]
    filter_specs: tuple[str, ...] = OSM_PBF_FILTER_SPECS

    def as_dict(self) -> dict[str, Any]:
        return {
            "pbf_path": self.pbf_path.as_posix(),
            "bbox_wgs84": self.bbox_wgs84,
            "bbox_arg": self.bbox_arg,
            "extracted_pbf_path": self.extracted_pbf_path.as_posix(),
            "raw_osm_json_path": self.raw_osm_json_path.as_posix(),
            "commands": [list(command) for command in self.commands],
            "filter_specs": list(self.filter_specs),
            "conversion_rule_version": CONVERSION_RULE_VERSION,
            "external_network_calls_made": False,
        }


def build_osmium_extraction_plan(
    *,
    pbf_path: Path,
    bbox_wgs84: dict[str, float],
    work_dir: Path,
    raw_osm_json_path: Path,
    osmium_bin: str = "osmium",
) -> OsmiumExtractionPlan:
    bbox = _normalize_bbox_for_osmium(bbox_wgs84)
    bbox_arg = f"{bbox['west']:.7f},{bbox['south']:.7f},{bbox['east']:.7f},{bbox['north']:.7f}"
    extracted_pbf_path = work_dir / "osm_pbf_route_bbox.osm.pbf"
    commands = (
        (
            osmium_bin,
            "extract",
            "--overwrite",
            "--bbox",
            bbox_arg,
            "--set-bounds",
            "--strategy",
            "smart",
            pbf_path.as_posix(),
            "-o",
            extracted_pbf_path.as_posix(),
        ),
    )
    return OsmiumExtractionPlan(
        pbf_path=pbf_path,
        bbox_wgs84=bbox,
        bbox_arg=bbox_arg,
        extracted_pbf_path=extracted_pbf_path,
        raw_osm_json_path=raw_osm_json_path,
        commands=commands,
    )


def extract_osm_pbf_to_osm_json(
    *,
    pbf_path: Path,
    bbox_wgs84: dict[str, float],
    raw_osm_json_path: Path,
    osmium_bin: str = "osmium",
) -> tuple[bytes, dict[str, Any]]:
    if not pbf_path.exists():
        raise FileNotFoundError(f"OSM PBF not found: {pbf_path}")
    if shutil.which(osmium_bin) is None:
        return _extract_osm_pbf_with_optional_pyosmium(
            pbf_path=pbf_path,
            bbox_wgs84=bbox_wgs84,
            raw_osm_json_path=raw_osm_json_path,
        )
    raw_osm_json_path.parent.mkdir(parents=True, exist_ok=True)
    plan = build_osmium_extraction_plan(
        pbf_path=pbf_path,
        bbox_wgs84=bbox_wgs84,
        work_dir=raw_osm_json_path.parent,
        raw_osm_json_path=raw_osm_json_path,
        osmium_bin=osmium_bin,
    )
    for command in plan.commands:
        subprocess.run(command, check=True, cwd=raw_osm_json_path.parent)
    raw_bytes, conversion_plan = _extract_osm_pbf_with_optional_pyosmium(
        pbf_path=plan.extracted_pbf_path,
        bbox_wgs84=plan.bbox_wgs84,
        raw_osm_json_path=raw_osm_json_path,
    )
    planned = plan.as_dict()
    planned["extractor"] = "osmium_cli_extract_plus_python_osmium_filter"
    planned["conversion_plan"] = conversion_plan
    return raw_bytes, planned


def _extract_osm_pbf_with_optional_pyosmium(
    *,
    pbf_path: Path,
    bbox_wgs84: dict[str, float],
    raw_osm_json_path: Path,
) -> tuple[bytes, dict[str, Any]]:
    try:
        import osmium  # type: ignore[import-not-found]
    except ImportError as exc:
        raise FileNotFoundError(
            "OSM PBF extraction requires either the 'osmium' CLI or the "
            "optional Python 'osmium' package in the active environment"
        ) from exc

    bbox = _normalize_bbox_for_osmium(bbox_wgs84)
    handler = _PbfRouteEvidenceHandler(bbox=bbox, osmium_module=osmium)
    handler.apply_file(pbf_path.as_posix(), locations=True)
    payload = {
        "version": 0.6,
        "generator": "scout.pretrip_osm_pbf_ingest.pyosmium",
        "elements": handler.elements,
    }
    raw_osm_json_path.parent.mkdir(parents=True, exist_ok=True)
    raw_osm_json_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    plan = {
        "pbf_path": pbf_path.as_posix(),
        "bbox_wgs84": bbox,
        "raw_osm_json_path": raw_osm_json_path.as_posix(),
        "extractor": "python_osmium_streaming_fallback",
        "filter_specs": list(OSM_PBF_FILTER_SPECS),
        "conversion_rule_version": CONVERSION_RULE_VERSION,
        "external_network_calls_made": False,
    }
    return raw_osm_json_path.read_bytes(), plan


class _PbfRouteEvidenceHandler:
    def __init__(self, *, bbox: dict[str, float], osmium_module: Any) -> None:
        self.bbox = bbox
        self.elements: list[dict[str, Any]] = []
        self._way_geometries: dict[int, list[dict[str, float]]] = {}
        self.osmium_module = osmium_module
        self._handler = osmium_module.SimpleHandler

    def apply_file(self, path: str, *, locations: bool) -> None:
        outer = self

        class Handler(self._handler):  # type: ignore[misc, valid-type]
            def node(self, node: Any) -> None:
                outer._handle_node(node)

            def way(self, way: Any) -> None:
                outer._handle_way(way)

            def relation(self, relation: Any) -> None:
                outer._handle_relation(relation)

        filter_module = getattr(self.osmium_module, "filter", None)
        filters = []
        if filter_module is not None:
            filters.append(filter_module.KeyFilter(*_OSM_PBF_NATIVE_FILTER_KEYS))
        Handler().apply_file(path, locations=locations, filters=filters)

    def _handle_node(self, node: Any) -> None:
        tags = _osmium_tags_if_matches(
            node,
            relevant_keys=_NODE_MATCH_KEYS,
            matcher=_matches_node_tags,
        )
        if tags is None:
            return
        location = getattr(node, "location", None)
        if location is None or not _osmium_location_valid(location):
            return
        lat = float(location.lat)
        lon = float(location.lon)
        if not _point_in_bbox(lat=lat, lon=lon, bbox=self.bbox):
            return
        self.elements.append(
            {"type": "node", "id": int(node.id), "lat": lat, "lon": lon, "tags": tags}
        )

    def _handle_way(self, way: Any) -> None:
        tags = _osmium_tags_if_matches(
            way,
            relevant_keys=_WAY_MATCH_KEYS,
            matcher=_matches_way_tags,
        )
        if tags is None:
            return
        geometry = []
        for node_ref in way.nodes:
            location = getattr(node_ref, "location", None)
            if location is None or not _osmium_location_valid(location):
                return
            geometry.append({"lat": float(location.lat), "lon": float(location.lon)})
        if not any(
            _point_in_bbox(lat=point["lat"], lon=point["lon"], bbox=self.bbox)
            for point in geometry
        ):
            return
        way_id = int(way.id)
        self._way_geometries[way_id] = geometry
        self.elements.append(
            {"type": "way", "id": way_id, "tags": tags, "geometry": geometry}
        )

    def _handle_relation(self, relation: Any) -> None:
        tags = _osmium_tags_if_matches(
            relation,
            relevant_keys=_RELATION_MATCH_KEYS,
            matcher=_matches_relation_tags,
        )
        if tags is None:
            return
        members = []
        for member in relation.members:
            member_type = _osmium_member_type(member)
            member_ref = int(member.ref)
            if member_type != "way" or member_ref not in self._way_geometries:
                continue
            members.append(
                {
                    "type": "way",
                    "ref": member_ref,
                    "role": str(getattr(member, "role", "") or ""),
                    "geometry": self._way_geometries[member_ref],
                }
            )
        if not members:
            return
        self.elements.append(
            {"type": "relation", "id": int(relation.id), "tags": tags, "members": members}
        )


def import_osm_pbf_evidence_candidates(
    payload: dict[str, Any],
    *,
    query_body: str,
    bbox_wgs84: RouteBBox | None,
    route_corridor: dict[str, Any] | None,
    request_timestamp: str,
    endpoint: str,
    raw_payload_uri: str,
    raw_response_sha256: str | None,
    normalized_artifact_path: str,
    source_ref: str,
    pbf_source_uri: str | None = None,
    pbf_download_url: str | None = None,
    pbf_source_sha256: str | None = None,
    pbf_cache_metadata: dict[str, Any] | None = None,
    extraction_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    hydrated_payload = osm_json_to_overpass_payload(payload)
    raw_hash = raw_response_sha256 or _payload_sha256(payload)
    result = import_overpass_evidence_candidates(
        hydrated_payload,
        query_body=query_body,
        bbox_wgs84=bbox_wgs84,
        route_corridor=route_corridor,
        request_timestamp=request_timestamp,
        endpoint=endpoint,
        http_status=200,
        raw_payload_uri=raw_payload_uri,
        raw_response_sha256=raw_hash,
        normalized_artifact_path=normalized_artifact_path,
        source_ref=source_ref,
    )
    normalized_geojson = _localize_geojson(
        result.normalized_geojson,
        pbf_source_uri=pbf_source_uri,
        pbf_download_url=pbf_download_url,
        pbf_source_sha256=pbf_source_sha256,
        pbf_cache_metadata=pbf_cache_metadata,
        extraction_plan=extraction_plan,
    )
    candidates = [
        _localize_candidate(candidate.model_dump(mode="json"))
        for candidate in result.candidates
    ]
    evidence = {
        "artifact_kind": "pretrip_osm_pbf_evidence",
        "schema_version": "route_corridor_map_preparation.v1",
        "status": "ready_from_local_osm_pbf",
        "source_artifact": _localize_source_artifact(
            result.source_artifact.model_dump(mode="json"),
            pbf_source_uri=pbf_source_uri,
            pbf_download_url=pbf_download_url,
            pbf_source_sha256=pbf_source_sha256,
            pbf_cache_metadata=pbf_cache_metadata,
            extraction_plan=extraction_plan,
        ),
        "request": _localize_request(result.request.model_dump(mode="json")),
        "object_evidence": [
            item.model_dump(mode="json") for item in result.object_evidence
        ],
        "skipped_objects": [
            item.model_dump(mode="json") for item in result.skipped_objects
        ],
        "candidates": candidates,
        "counts": {
            **result.counts,
            "hydrated_osm_element_count": len(hydrated_payload.get("elements", [])),
            "network_calls_made": 0,
        },
        "normalized_geojson_ref": normalized_artifact_path,
        "normalized_geojson": normalized_geojson,
        "pbf_cache": pbf_cache_metadata,
        "source_refs": [
            {
                "ref": raw_payload_uri,
                "source_kind": "local_osm_pbf_osmjson_extract",
                "external_network_required": False,
                "network_calls_made": False,
            }
        ],
        "boundary": {
            "candidate_only": True,
            "runtime_truth": False,
            "runtime_safety_truth": False,
            "live_network_required": False,
            "network_mode": "local_file",
            "phase1_runtime_mutation_allowed": False,
            "phase2_brain_writeback_allowed": False,
        },
    }
    return evidence


def build_osm_pbf_feature_index(
    payload: dict[str, Any],
    *,
    source_ref: str,
    render_source_ref: str,
    request_timestamp: str,
    route_corridor: dict[str, Any] | None = None,
    pbf_cache_metadata: dict[str, Any] | None = None,
    pbf_source_uri: str | None = None,
    pbf_download_url: str | None = None,
    pbf_source_sha256: str | None = None,
) -> dict[str, Any]:
    """Build compact UI evidence from a route-bbox OSM extract.

    The input may be an osmium-exported GeoJSON FeatureCollection or an OSM JSON
    payload. The index is intentionally smaller than a renderer source: it keeps
    source object ids, tags, representative coordinates, and category counts for
    admin Map/Risk review without embedding full Taiwan PBF data.
    """

    source_kind = (
        "local_osm_pbf_geojson_extract"
        if payload.get("type") == "FeatureCollection"
        else "local_osm_pbf_osmjson_extract"
    )
    items = (
        _feature_index_items_from_geojson(payload, source_ref=source_ref)
        if payload.get("type") == "FeatureCollection"
        else _feature_index_items_from_osm_json(payload, source_ref=source_ref)
    )
    category_counts = Counter(item["category_id"] for item in items)
    geometry_counts = Counter(item["geometry_type"] for item in items)
    category_items = [
        {
            "category_id": category_id,
            "category_label": OSM_PBF_FEATURE_CATEGORIES[category_id]["label"],
            "timeline_group": OSM_PBF_FEATURE_CATEGORIES[category_id][
                "timeline_group"
            ],
            "count": int(category_counts.get(category_id, 0)),
            "sample_labels": [
                item["label"]
                for item in items
                if item["category_id"] == category_id
            ][:8],
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
        for category_id in OSM_PBF_FEATURE_CATEGORIES
        if category_counts.get(category_id, 0)
    ]
    index_hash = _payload_sha256(
        {
            "source_ref": source_ref,
            "render_source_ref": render_source_ref,
            "item_ids": [item["candidate_id"] for item in items],
            "category_counts": dict(category_counts),
        }
    )
    return {
        "artifact_kind": "pretrip_local_osm_pbf_feature_index",
        "schema_version": "0.1.0",
        "source_id": "local_osm_pbf.feature_index",
        "source_path": source_ref,
        "source_kind": source_kind,
        "render_source_ref": render_source_ref,
        "status": "candidate_only" if items else "empty",
        "generated_at": request_timestamp,
        "conversion_rule_version": FEATURE_INDEX_VERSION,
        "model_output_sha256": index_hash,
        "model_output_summary": (
            "Local OSM PBF route-bbox feature index for Scout Map/Risk timeline "
            "review; candidate-only evidence and not runtime safety truth."
        ),
        "counts": {
            "item_count": len(items),
            "category_counts": dict(sorted(category_counts.items())),
            "geometry_counts": dict(sorted(geometry_counts.items())),
            "point_item_count": int(geometry_counts.get("Point", 0)),
            "line_item_count": int(geometry_counts.get("LineString", 0))
            + int(geometry_counts.get("MultiLineString", 0)),
            "area_item_count": int(geometry_counts.get("Polygon", 0))
            + int(geometry_counts.get("MultiPolygon", 0)),
        },
        "categories": category_items,
        "items": items,
        "source_refs": [
            {
                "ref": source_ref,
                "source_kind": source_kind,
                "external_network_required": False,
                "network_calls_made": False,
            },
            {
                "ref": render_source_ref,
                "source_kind": "local_osm_pbf_render_extract",
                "external_network_required": False,
                "network_calls_made": False,
            },
        ],
        "route_corridor": route_corridor,
        "pbf_cache": pbf_cache_metadata,
        "pbf_source_uri": pbf_source_uri,
        "pbf_download_url": pbf_download_url,
        "pbf_source_sha256": pbf_source_sha256,
        "boundary": {
            "candidate_only": True,
            "runtime_truth": False,
            "runtime_safety_truth": False,
            "live_network_required": False,
            "network_mode": "local_file",
            "phase1_runtime_mutation_allowed": False,
            "phase2_brain_writeback_allowed": False,
        },
    }


def osm_json_to_geojson_feature_collection(payload: dict[str, Any]) -> dict[str, Any]:
    """Convert the local OSM JSON extract into a renderable GeoJSON layer."""

    overpass_payload = osm_json_to_overpass_payload(payload)
    features: list[dict[str, Any]] = []
    for element in overpass_payload.get("elements", []):
        if not isinstance(element, dict):
            continue
        geometry = _feature_index_geometry_from_overpass_element(element)
        if geometry is None:
            continue
        tags = dict(element.get("tags") or {})
        osm_type = str(element.get("type") or "feature")
        osm_id = element.get("id")
        properties = {
            "@type": osm_type,
            "@id": osm_id,
            "type": osm_type,
            "id": osm_id,
            "source": "local_osm_pbf",
            "source_kind": "local_osm_pbf_osmjson_extract",
            **tags,
        }
        features.append(
            {
                "type": "Feature",
                "id": f"{osm_type}/{osm_id}",
                "properties": properties,
                "geometry": geometry,
            }
        )
    return {
        "type": "FeatureCollection",
        "name": "scout_local_osm_pbf_route_bbox",
        "features": features,
        "properties": {
            "source": "local_osm_pbf",
            "source_kind": "local_osm_pbf_osmjson_extract",
            "generator": "scout.pretrip_osm_pbf_ingest.osm_json_to_geojson_feature_collection",
            "conversion_rule_version": CONVERSION_RULE_VERSION,
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
    }


def osm_json_to_overpass_payload(payload: dict[str, Any]) -> dict[str, Any]:
    elements = payload.get("elements")
    if not isinstance(elements, list):
        raise ValueError("OSM JSON payload must include an elements array")

    node_coordinates: dict[int, dict[str, float]] = {}
    ways_by_id: dict[int, dict[str, Any]] = {}
    hydrated: list[dict[str, Any]] = []

    for element in elements:
        if not isinstance(element, dict):
            continue
        osm_type = element.get("type")
        osm_id = element.get("id")
        if not isinstance(osm_id, int):
            continue
        if osm_type == "node" and "lat" in element and "lon" in element:
            node_coordinates[osm_id] = {
                "lat": float(element["lat"]),
                "lon": float(element["lon"]),
            }
        elif osm_type == "way":
            ways_by_id[osm_id] = element

    for element in elements:
        if not isinstance(element, dict):
            continue
        osm_type = element.get("type")
        osm_id = element.get("id")
        if osm_type not in {"node", "way", "relation"} or not isinstance(osm_id, int):
            continue
        converted = {
            "type": osm_type,
            "id": osm_id,
            "tags": dict(element.get("tags") or {}),
        }
        if osm_type == "node":
            if "lat" in element and "lon" in element:
                converted["lat"] = float(element["lat"])
                converted["lon"] = float(element["lon"])
        elif osm_type == "way":
            converted["nodes"] = list(element.get("nodes") or [])
            geometry = _way_geometry(element, node_coordinates)
            if geometry is not None:
                converted["geometry"] = geometry
        elif osm_type == "relation":
            converted["members"] = _relation_members_with_geometry(
                element,
                node_coordinates=node_coordinates,
                ways_by_id=ways_by_id,
            )
        hydrated.append(converted)

    return {
        "version": payload.get("version", 0.6),
        "generator": "scout.pretrip_osm_pbf_ingest",
        "elements": hydrated,
    }


def _feature_index_items_from_geojson(
    payload: dict[str, Any],
    *,
    source_ref: str,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    features = payload.get("features")
    if not isinstance(features, list):
        return items
    for index, feature in enumerate(features):
        if not isinstance(feature, dict):
            continue
        geometry = feature.get("geometry")
        properties = dict(feature.get("properties") or {})
        osm_type = str(properties.get("@type") or properties.get("type") or "feature")
        osm_id = properties.get("@id") or properties.get("id") or index
        item = _feature_index_item(
            osm_type=osm_type,
            osm_id=osm_id,
            tags={k: v for k, v in properties.items() if not str(k).startswith("@")},
            geometry=geometry,
            source_ref=source_ref,
            source_kind="local_osm_pbf_geojson_extract",
        )
        if item is not None:
            items.append(item)
    return items


def _feature_index_items_from_osm_json(
    payload: dict[str, Any],
    *,
    source_ref: str,
) -> list[dict[str, Any]]:
    overpass_payload = osm_json_to_overpass_payload(payload)
    items: list[dict[str, Any]] = []
    for element in overpass_payload.get("elements", []):
        if not isinstance(element, dict):
            continue
        osm_type = element.get("type")
        osm_id = element.get("id")
        tags = dict(element.get("tags") or {})
        geometry = _feature_index_geometry_from_overpass_element(element)
        item = _feature_index_item(
            osm_type=osm_type,
            osm_id=osm_id,
            tags=tags,
            geometry=geometry,
            source_ref=source_ref,
            source_kind="local_osm_pbf_osmjson_extract",
        )
        if item is not None:
            items.append(item)
    return items


def _feature_index_geometry_from_overpass_element(
    element: dict[str, Any],
) -> dict[str, Any] | None:
    if element.get("type") == "node" and "lat" in element and "lon" in element:
        return {
            "type": "Point",
            "coordinates": [float(element["lon"]), float(element["lat"])],
        }
    if element.get("type") == "way" and isinstance(element.get("geometry"), list):
        coordinates = [
            [float(point["lon"]), float(point["lat"])]
            for point in element["geometry"]
            if isinstance(point, dict) and "lat" in point and "lon" in point
        ]
        if len(coordinates) >= 2:
            return {"type": "LineString", "coordinates": coordinates}
    if element.get("type") == "relation":
        lines = []
        for member in element.get("members", []):
            if not isinstance(member, dict) or not isinstance(member.get("geometry"), list):
                continue
            line = [
                [float(point["lon"]), float(point["lat"])]
                for point in member["geometry"]
                if isinstance(point, dict) and "lat" in point and "lon" in point
            ]
            if len(line) >= 2:
                lines.append(line)
        if lines:
            return {"type": "MultiLineString", "coordinates": lines}
    return None


def _feature_index_item(
    *,
    osm_type: Any,
    osm_id: Any,
    tags: dict[str, Any],
    geometry: dict[str, Any] | None,
    source_ref: str,
    source_kind: str,
) -> dict[str, Any] | None:
    if not tags:
        return None
    if not isinstance(geometry, dict):
        return None
    geometry_type = str(geometry.get("type") or "unknown")
    coordinates = _flatten_geojson_coordinates(geometry)
    if not coordinates:
        return None
    bbox = _coordinate_bbox(coordinates)
    representative = _representative_coordinate(coordinates)
    category_id = _feature_category(tags, geometry_type)
    feature_type = _feature_type(tags, geometry_type)
    label = _feature_label(tags, osm_type=osm_type, osm_id=osm_id, feature_type=feature_type)
    safe_osm_type = str(osm_type or "feature")
    safe_osm_id = str(osm_id)
    candidate_id = f"osm_pbf.{safe_osm_type}.{safe_osm_id}"
    source_refs = [
        source_ref,
        f"{safe_osm_type}/{safe_osm_id}",
        *[
            str(value)
            for value in (
                tags.get("name"),
                tags.get("name:zh"),
                tags.get("ref"),
                tags.get("distance"),
                tags.get("network"),
            )
            if value
        ],
    ]
    model_hash = _payload_sha256(
        {
            "candidate_id": candidate_id,
            "tags": tags,
            "bbox": bbox,
            "geometry_type": geometry_type,
        }
    )
    stale_risk = "medium"
    return {
        "candidate_id": candidate_id,
        "source_id": candidate_id,
        "source_path": source_ref,
        "evidence_type": "pretrip_local_osm_pbf_feature",
        "timeline_element_type": "map_feature_evidence",
        "layer_id": "osm",
        "review_category": "map_risk_osm_pbf",
        "category_id": category_id,
        "category_label": OSM_PBF_FEATURE_CATEGORIES[category_id]["label"],
        "timeline_group": OSM_PBF_FEATURE_CATEGORIES[category_id]["timeline_group"],
        "label": label,
        "feature_type": feature_type,
        "geometry_type": geometry_type,
        "osm_type": safe_osm_type,
        "osm_id": safe_osm_id,
        "tags": tags,
        "tag_summary": _tag_summary(tags),
        "lat": representative["lat"],
        "lon": representative["lon"],
        "bbox_wgs84": bbox,
        "geometry_summary": {
            "point_count": len(coordinates),
            "representative_coordinate_policy": "centroid_of_available_geometry",
        },
        "map_target_ids": [candidate_id],
        "source_refs": list(dict.fromkeys(source_refs)),
        "source_attribution": [
            {
                "source_kind": source_kind,
                "source_ref": source_ref,
                "source_candidate_id": f"{safe_osm_type}/{safe_osm_id}",
                "source_label": label,
                "evidence_type": "pretrip_local_osm_pbf_feature",
                "confidence": "medium",
                "stale_risk": stale_risk,
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        ],
        "confidence": "medium",
        "stale_risk": stale_risk,
        "review_state": "needs_review",
        "candidate_only": True,
        "runtime_truth": False,
        "runtime_safety_truth": False,
        "extractor_version": FEATURE_INDEX_VERSION,
        "pydantic_ai_prompt_version": "not_applicable_deterministic_osm_pbf_feature_index.v1",
        "model_output_sha256": model_hash,
        "model_output_summary": (
            "Local OSM PBF map feature indexed for Scout admin Map/Risk review; "
            "candidate-only evidence and not runtime safety truth."
        ),
    }


def _flatten_geojson_coordinates(geometry: dict[str, Any]) -> list[dict[str, float]]:
    coordinates = geometry.get("coordinates")
    flattened: list[dict[str, float]] = []

    def visit(value: Any) -> None:
        if (
            isinstance(value, list)
            and len(value) >= 2
            and isinstance(value[0], (int, float))
            and isinstance(value[1], (int, float))
        ):
            flattened.append({"lon": float(value[0]), "lat": float(value[1])})
            return
        if isinstance(value, list):
            for child in value:
                visit(child)

    visit(coordinates)
    return flattened


def _coordinate_bbox(coordinates: list[dict[str, float]]) -> dict[str, float]:
    lats = [point["lat"] for point in coordinates]
    lons = [point["lon"] for point in coordinates]
    return {
        "west": min(lons),
        "south": min(lats),
        "east": max(lons),
        "north": max(lats),
    }


def _representative_coordinate(coordinates: list[dict[str, float]]) -> dict[str, float]:
    return {
        "lat": sum(point["lat"] for point in coordinates) / len(coordinates),
        "lon": sum(point["lon"] for point in coordinates) / len(coordinates),
    }


def _feature_category(tags: dict[str, Any], geometry_type: str) -> str:
    highway = str(tags.get("highway") or "")
    information = str(tags.get("information") or "")
    natural = str(tags.get("natural") or "")
    amenity = str(tags.get("amenity") or "")
    tourism = str(tags.get("tourism") or "")
    landuse = str(tags.get("landuse") or "")
    if highway == "milestone" or information == "route_marker":
        return "milestone_route_marker"
    if information == "mobile":
        return "mobile_signal"
    if highway in {"path", "footway", "track", "steps", "bridleway", "pedestrian"}:
        return "trail_network"
    if str(tags.get("route") or "") == "hiking":
        return "trail_network"
    if natural == "peak":
        return "peak_terrain"
    if natural in {"cliff", "scree", "bare_rock", "shingle"} or tags.get("geological"):
        return "terrain_risk_context"
    if tags.get("waterway") or natural in {"spring", "water"} or amenity == "drinking_water":
        return "water_hydrology"
    if amenity or tourism in {"wilderness_hut", "alpine_hut", "information", "viewpoint"}:
        return "amenity_poi"
    if tags.get("power") or tags.get("man_made"):
        return "infrastructure"
    if tags.get("building") or landuse or natural in {"wood", "forest", "grassland"}:
        return "landcover_structure"
    if geometry_type in {"Polygon", "MultiPolygon"}:
        return "landcover_structure"
    return "other_osm_feature"


def _feature_type(tags: dict[str, Any], geometry_type: str) -> str:
    for key in (
        "highway",
        "information",
        "natural",
        "amenity",
        "tourism",
        "waterway",
        "landuse",
        "building",
        "power",
        "man_made",
        "route",
    ):
        value = tags.get(key)
        if value:
            return f"{key}:{value}"
    return geometry_type.lower()


def _feature_label(
    tags: dict[str, Any],
    *,
    osm_type: Any,
    osm_id: Any,
    feature_type: str,
) -> str:
    for key in ("name:zh", "name", "official_name", "alt_name"):
        value = tags.get(key)
        if value:
            return str(value)
    if tags.get("distance"):
        network = tags.get("network")
        return f"{tags['distance']}{f' {network}' if network else ''}"
    if tags.get("ref"):
        return str(tags["ref"])
    if tags.get("information") == "mobile":
        return "通訊點"
    return f"{feature_type} {osm_type}/{osm_id}"


def _tag_summary(tags: dict[str, Any]) -> dict[str, Any]:
    return {
        key: tags[key]
        for key in (
            "name:zh",
            "name",
            "distance",
            "ref",
            "network",
            "highway",
            "information",
            "natural",
            "amenity",
            "tourism",
            "waterway",
            "landuse",
            "building",
            "power",
            "man_made",
        )
        if key in tags
    }


def _way_geometry(
    element: dict[str, Any],
    node_coordinates: dict[int, dict[str, float]],
) -> list[dict[str, float]] | None:
    if isinstance(element.get("geometry"), list):
        geometry = []
        for point in element["geometry"]:
            if not isinstance(point, dict) or "lat" not in point or "lon" not in point:
                return None
            geometry.append({"lat": float(point["lat"]), "lon": float(point["lon"])})
        return geometry
    node_refs = element.get("nodes")
    if not isinstance(node_refs, list):
        return None
    geometry = []
    for node_ref in node_refs:
        if not isinstance(node_ref, int) or node_ref not in node_coordinates:
            return None
        geometry.append(node_coordinates[node_ref])
    return geometry


def _relation_members_with_geometry(
    element: dict[str, Any],
    *,
    node_coordinates: dict[int, dict[str, float]],
    ways_by_id: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    members = element.get("members")
    if not isinstance(members, list):
        return []
    hydrated = []
    for member in members:
        if not isinstance(member, dict):
            continue
        hydrated_member = dict(member)
        if hydrated_member.get("type") == "way":
            way_ref = hydrated_member.get("ref")
            way = ways_by_id.get(way_ref) if isinstance(way_ref, int) else None
            if way is not None:
                geometry = _way_geometry(way, node_coordinates)
                if geometry is not None:
                    hydrated_member["geometry"] = geometry
        hydrated.append(hydrated_member)
    return hydrated


def _localize_source_artifact(
    source_artifact: dict[str, Any],
    *,
    pbf_source_uri: str | None,
    pbf_download_url: str | None,
    pbf_source_sha256: str | None,
    pbf_cache_metadata: dict[str, Any] | None,
    extraction_plan: dict[str, Any] | None,
) -> dict[str, Any]:
    metadata = dict(source_artifact.get("metadata") or {})
    metadata.update(
        {
            "source": "local_osm_pbf",
            "pbf_source_uri": pbf_source_uri,
            "pbf_download_url": pbf_download_url,
            "pbf_source_sha256": pbf_source_sha256,
            "pbf_cache": pbf_cache_metadata,
            "extraction_plan": extraction_plan,
            "conversion_rule_version": CONVERSION_RULE_VERSION,
            "runtime_truth": False,
        }
    )
    provenance = dict(source_artifact.get("provenance") or {})
    provenance.update(
        {
            "source_kind": "osm_pbf_raw_payload",
            "method": "pretrip_osm_pbf_ingest.import_osm_pbf_evidence_candidates",
            "notes": (
                "Local OSM PBF extract normalized into pretrip planning "
                "candidates only; not runtime safety truth."
            ),
        }
    )
    return {
        **source_artifact,
        "artifact_kind": "pretrip_osm_pbf_evidence",
        "kind": "osm_pbf_raw_payload",
        "metadata": metadata,
        "provenance": provenance,
    }


def _localize_request(request: dict[str, Any]) -> dict[str, Any]:
    return {
        **request,
        "source": "local_osm_pbf",
        "conversion_rule_version": CONVERSION_RULE_VERSION,
        "external_network_calls_made": False,
        "runtime_safety_truth": False,
    }


def _localize_geojson(
    geojson: dict[str, Any],
    *,
    pbf_source_uri: str | None,
    pbf_download_url: str | None,
    pbf_source_sha256: str | None,
    pbf_cache_metadata: dict[str, Any] | None,
    extraction_plan: dict[str, Any] | None,
) -> dict[str, Any]:
    localized = json.loads(json.dumps(geojson))
    properties = dict(localized.get("properties") or {})
    properties.update(
        {
            "source": "local_osm_pbf",
            "source_version": CONVERSION_RULE_VERSION,
            "pbf_source_uri": pbf_source_uri,
            "pbf_download_url": pbf_download_url,
            "pbf_source_sha256": pbf_source_sha256,
            "pbf_cache": pbf_cache_metadata,
            "extraction_plan": extraction_plan,
            "candidate_layer": "pretrip_local_osm_pbf_vector_evidence",
            "runtime_truth": False,
        }
    )
    localized["properties"] = properties
    localized["features"] = [
        _localize_geojson_feature(feature)
        for feature in localized.get("features", [])
        if isinstance(feature, dict)
    ]
    return localized


def _localize_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    candidate["extractor_version"] = CONVERSION_RULE_VERSION
    candidate["geojson_feature"] = _localize_geojson_feature(
        candidate.get("geojson_feature") or {}
    )
    candidate["source_attribution"] = [
        _localize_source_attribution(item)
        for item in candidate.get("source_attribution", [])
        if isinstance(item, dict)
    ]
    candidate["notes"] = (
        "Local OSM PBF vector evidence is a pretrip planning candidate; "
        "it is not runtime safety truth."
    )
    return candidate


def _localize_geojson_feature(feature: dict[str, Any]) -> dict[str, Any]:
    localized = dict(feature)
    properties = dict(localized.get("properties") or {})
    properties.update(
        {
            "source": "local_osm_pbf",
            "source_kind": "local_osm_pbf_vector",
            "source_version": CONVERSION_RULE_VERSION,
            "extractor_version": CONVERSION_RULE_VERSION,
            "evidence_type": "pretrip_local_osm_pbf_vector_candidate",
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
    )
    if isinstance(properties.get("source_attribution"), list):
        properties["source_attribution"] = [
            _localize_source_attribution(item)
            for item in properties["source_attribution"]
            if isinstance(item, dict)
        ]
    localized["properties"] = properties
    return localized


def _localize_source_attribution(item: dict[str, Any]) -> dict[str, Any]:
    return {
        **item,
        "source_kind": "local_osm_pbf_vector",
        "evidence_type": "pretrip_local_osm_pbf_vector_candidate",
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _matches_node_tags(tags: dict[str, Any]) -> bool:
    return (
        tags.get("natural") == "peak"
        or tags.get("natural") == "spring"
        or tags.get("amenity") in {"shelter", "drinking_water", "parking"}
        or tags.get("tourism") in {"wilderness_hut", "alpine_hut"}
        or tags.get("man_made") == "water_tap"
    )


def _matches_way_tags(tags: dict[str, Any]) -> bool:
    highway = str(tags.get("highway", "")).strip().lower()
    return (
        highway in {"path", "footway", "track", "steps", "bridleway", "pedestrian"}
        or tags.get("natural") in {"cliff", "scree", "bare_rock"}
        or tags.get("geological") == "landslide"
        or "hazard" in tags
        or "risk" in tags
    )


def _matches_relation_tags(tags: dict[str, Any]) -> bool:
    return tags.get("route") == "hiking" or (
        tags.get("type") == "route" and tags.get("route") == "hiking"
    )


def _osmium_tags(entity: Any) -> dict[str, Any]:
    return {str(tag.k): str(tag.v) for tag in entity.tags}


def _osmium_tags_if_matches(
    entity: Any,
    *,
    relevant_keys: frozenset[str],
    matcher: Any,
) -> dict[str, Any] | None:
    relevant: dict[str, Any] | None = None
    for tag in entity.tags:
        key = str(tag.k)
        if key not in relevant_keys:
            continue
        if relevant is None:
            relevant = {}
        relevant[key] = str(tag.v)
    if relevant is None or not matcher(relevant):
        return None
    return _osmium_tags(entity)


def _osmium_location_valid(location: Any) -> bool:
    valid = getattr(location, "valid", None)
    if callable(valid):
        return bool(valid())
    return bool(valid)


def _osmium_member_type(member: Any) -> str:
    value = getattr(member, "type", "")
    normalized = str(value).lower()
    if normalized in {"w", "way", "w way"} or normalized.endswith(".way"):
        return "way"
    if normalized in {"n", "node"} or normalized.endswith(".node"):
        return "node"
    if normalized in {"r", "relation"} or normalized.endswith(".relation"):
        return "relation"
    return normalized


def _point_in_bbox(*, lat: float, lon: float, bbox: dict[str, float]) -> bool:
    return (
        bbox["south"] <= lat <= bbox["north"]
        and bbox["west"] <= lon <= bbox["east"]
    )


def _normalize_bbox_for_osmium(bbox: dict[str, float]) -> dict[str, float]:
    if {"south", "west", "north", "east"} <= set(bbox):
        south = float(bbox["south"])
        west = float(bbox["west"])
        north = float(bbox["north"])
        east = float(bbox["east"])
    else:
        south = float(bbox["min_lat"])
        west = float(bbox["min_lon"])
        north = float(bbox["max_lat"])
        east = float(bbox["max_lon"])
    if south >= north or west >= east:
        raise ValueError("bbox must satisfy south < north and west < east")
    return {"south": south, "west": west, "north": north, "east": east}


def _payload_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
