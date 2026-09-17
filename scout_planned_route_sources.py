"""Read-only, source-bound map candidates for Planned route composition.

This module consumes complete source geometry.  It neither changes a workspace
nor interprets a terrain hypothesis or a map drawing as a walkable route.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import math
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

BOUNDARY = {"candidate_only": True, "runtime_safety_truth": False,
            "operational": False, "safe_or_walkable": "not_determined"}


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def _point(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        lat, lon = float(value["lat"]), float(value["lon"])
        elevation = value.get("ele")
    else:
        lon, lat = float(value[0]), float(value[1])
        elevation = value[2] if len(value) > 2 else None
    if not math.isfinite(lat) or not math.isfinite(lon) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("source coordinates must be finite WGS84 coordinates")
    elevation = float(elevation) if elevation is not None else None
    if elevation is not None and not math.isfinite(elevation):
        raise ValueError("source elevation must be finite or unknown")
    return {"lat": lat, "lon": lon, "ele": elevation, "time": None}


def _parts(geometry: dict[str, Any]) -> list[list[dict[str, Any]]]:
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if kind == "LineString":
        coordinates = [coordinates]
    elif kind != "MultiLineString":
        raise ValueError("map route source requires LineString or MultiLineString")
    if not isinstance(coordinates, list) or not coordinates:
        raise ValueError("map route source has no line parts")
    parts = [[_point(point) for point in part] for part in coordinates]
    if any(len(part) < 2 for part in parts):
        raise ValueError("every source part needs at least two vertices")
    return parts


class _Reader:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.source_hashes: dict[str, str] = {}
        self._payloads: dict[str, Any] = {}

    def path(self, ref: str) -> Path:
        if not isinstance(ref, str) or not ref or Path(ref).is_absolute() or ".." in Path(ref).parts or ref.startswith("~"):
            raise ValueError("map source must be a workspace-relative path")
        path = (self.root / ref).resolve()
        if not path.is_relative_to(self.root) or not path.is_file():
            raise ValueError(f"map source is missing or outside the workspace: {ref}")
        return path

    def bind(self, ref: str, expected: str | None = None) -> str:
        if ref not in self.source_hashes:
            digest = hashlib.sha256()
            with self.path(ref).open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    digest.update(chunk)
            self.source_hashes[ref] = digest.hexdigest()
        actual = self.source_hashes[ref]
        if expected is not None and actual != expected:
            raise ValueError(f"source hash changed: {ref}")
        return actual

    def read(self, ref: str, expected: str | None = None) -> Any:
        self.bind(ref, expected)
        if ref not in self._payloads:
            raw = self.path(ref).read_bytes()
            if _hash(raw) != self.source_hashes[ref]:
                raise ValueError(f"source changed while reading: {ref}")
            self._payloads[ref] = json.loads(raw)
        return self._payloads[ref]


def _issue(code: str, message: str, *, kind: str = "map", blocking: bool = False) -> dict[str, Any]:
    return {"code": code, "message": message, "source_kind": kind, "blocking": blocking}


def _source(source_id: str, label: str, kind: str, ref: str, reader: _Reader,
            parts: list[list[dict[str, Any]]], provenance: dict[str, Any]) -> dict[str, Any]:
    return {"source_id": source_id, "label": label, "kind": kind,
            "ref": ref, "sha256": reader.bind(ref), "parts": parts,
            "provenance": {**provenance, **BOUNDARY}}


def load_map_route_sources(root: Path, project: dict[str, Any]) -> dict[str, Any]:
    """Return usable source segments, full vertices, and explicit unavailable causes.

    Additional immutable fetches are declared in ``planned_overpass_source_refs``
    as descriptors returned by :func:`fetch_trail_source_candidates`.  Rudy traces
    use ``planned_rudy_trace_refs`` and the documented human-trace provenance.
    Missing optional families never make an unrelated Ref-only plan unusable.
    """
    reader = _Reader(Path(root))
    sources: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    from scout_planned_map_materialization import read_materialization_catalog
    source_states = []
    registered = {"overpass": [], "rudy_trace": [], "mapsforge_vector": []}
    try:
        registered = read_materialization_catalog(reader.root, project.get("project_id", reader.root.name))
        issues.extend(registered.get("issues", []))
        source_states.extend(registered.get("source_states", []))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        issues.append(_issue("MAP_MATERIALIZATION_CATALOG_UNAVAILABLE", str(exc)))
    descriptors = [*(project.get("planned_overpass_source_refs") or []), *registered["overpass"]]
    if project.get("overpass_map_context_ref"):
        descriptors.insert(0, {"ref": project["overpass_map_context_ref"],
                              "raw_ref": project.get("overpass_raw_payload_ref") or project.get("osm_pbf_raw_payload_ref"),
                              "evidence_ref": project.get("overpass_evidence_ref")})
    for descriptor in descriptors:
        try:
            found, gaps = _overpass_sources(reader, descriptor)
            sources.extend(found)
            issues.extend(gaps)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            issues.append(_issue("OVERPASS_SOURCE_UNAVAILABLE", str(exc), kind="overpass"))
    if not descriptors:
        issues.append(_issue("OVERPASS_SOURCE_UNAVAILABLE", "No bound Overpass vectors are prepared.", kind="overpass"))
    for descriptor in registered.get("mapsforge_vector", []):
        try:
            sources.extend(_mapsforge_sources(reader, descriptor))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            issues.append(_issue("MAPSFORGE_SOURCE_UNAVAILABLE", str(exc), kind="mapsforge_vector"))
    trace_refs = [*(project.get("planned_rudy_trace_refs") or []), *registered["rudy_trace"]]
    for descriptor in trace_refs:
        try:
            sources.extend(_rudy_sources(reader, descriptor))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            issues.append(_issue("RUDY_TRACE_UNAVAILABLE", str(exc), kind="rudy_trace"))
    if not trace_refs and not any(s["kind"] == "mapsforge_vector" for s in sources):
        issues.append(_issue("RUDY_TRACE_PENDING", "Rudy+TWMap raster context has no bound human trace geometry.", kind="rudy_trace"))
    try:
        found, gaps = _trh_sources(reader, project)
        sources.extend(found)
        issues.extend(gaps)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        issues.append(_issue("TRH_SOURCE_UNAVAILABLE", str(exc), kind="trh"))
    unique: dict[str, dict[str, Any]] = {}
    for source in sources:
        previous = unique.get(source["source_id"])
        if previous is not None and previous != source:
            issues.append(_issue("SOURCE_ID_COLLISION", source["source_id"], blocking=True))
            continue
        unique[source["source_id"]] = source
    anchors = []
    for source in unique.values():
        for part_index, part in enumerate(source["parts"]):
            for point_index in (0, len(part) - 1):
                point = part[point_index]
                anchors.append({"anchor_id": f"{source['source_id']}.p{part_index}.{point_index}",
                                "label": f"{source['label']} · {'起點' if point_index == 0 else '終點'}",
                                "source_id": source["source_id"], "part_index": part_index,
                                "point_index": point_index, "lat": point["lat"], "lon": point["lon"],
                                **({"osm_node_id": point["osm_node_id"]} if "osm_node_id" in point else {})})
    for kind, families in (("overpass", {"overpass"}), ("mapsforge_vector", {"mapsforge_vector"}), ("rudy_trace", {"rudy_trace"}),
                           ("trh", {"trh_r1", "trh_r2", "trh_r3", "trh_r4"})):
        count = sum(source["kind"] in families for source in unique.values())
        source_states.append({"source_kind": kind, "status": "available" if count else "unavailable",
                              "usable_candidate_count": count,
                              "issues": [item["code"] for item in issues if item.get("source_kind") in families | {kind}]})
    return {"sources": list(unique.values()), "anchors": anchors,
            "source_hashes": reader.source_hashes, "issues": issues,
            "source_states": source_states, **BOUNDARY}


def _overpass_sources(reader: _Reader, descriptor: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ref = descriptor["ref"]
    payload = reader.read(ref, descriptor.get("sha256"))
    if payload.get("type") != "FeatureCollection":
        raise ValueError("Overpass source is not a FeatureCollection")
    dependencies = {ref: reader.bind(ref)}
    for dependency, expected in descriptor.get("input_source_hashes", {}).items():
        dependencies[dependency] = reader.bind(dependency, expected)
    if descriptor.get("manifest_ref"):
        dependencies[descriptor["manifest_ref"]] = reader.bind(descriptor["manifest_ref"], descriptor["manifest_sha256"])
    evidence = reader.read(descriptor["evidence_ref"], descriptor.get("evidence_sha256")) if descriptor.get("evidence_ref") else {}
    if descriptor.get("evidence_ref"):
        dependencies[descriptor["evidence_ref"]] = reader.bind(descriptor["evidence_ref"])
    request = evidence.get("request", {})
    sources, issues = [], []
    missing_nodes = 0
    for feature in payload.get("features", []):
        props = feature.get("properties", {})
        if props.get("candidate_type") not in {"trail_corridor_candidate", "hiking_route_candidate"}:
            continue
        if props.get("candidate_only") is not True or props.get("runtime_safety_truth") is not False:
            raise ValueError("Overpass source candidate authority is missing")
        raw_ref = descriptor.get("raw_ref") or props.get("raw_payload_uri") or request.get("raw_payload_uri")
        expected = descriptor.get("raw_sha256") or props.get("raw_response_sha256") or request.get("raw_response_sha256")
        if not raw_ref or not expected:
            raise ValueError("Overpass source raw payload/hash is missing")
        raw = reader.read(raw_ref, expected)
        parts = _parts(feature["geometry"])
        osm_type, osm_id = props.get("osm_type"), props.get("osm_id")
        if osm_type not in {"way", "relation"} or not isinstance(osm_id, int):
            raise ValueError("Overpass source OSM identity is missing")
        element = next((item for item in raw.get("elements", [])
                        if item.get("type") == osm_type and item.get("id") == osm_id), None)
        if element is None:
            raise ValueError("Overpass normalized feature is absent from bound raw payload")
        # Raw geometry must agree with the normalized geometry; raw node IDs are
        # never inferred from coordinate equality, proximity, or intersections.
        raw_lines = [element] if osm_type == "way" else [m for m in element.get("members", []) if m.get("geometry")]
        if len(raw_lines) != len(parts):
            raise ValueError("Overpass normalized part count differs from raw geometry")
        nodes_complete = True
        for part, raw_line in zip(parts, raw_lines):
            raw_points = raw_line.get("geometry")
            if raw_points is None:
                nodes_by_id = {n.get("id"): n for n in raw.get("elements", []) if n.get("type") == "node"}
                raw_points = [nodes_by_id.get(n) for n in raw_line.get("nodes", [])]
            if len(raw_points) != len(part) or any(p is None or _point(p) != q for p, q in zip(raw_points, part)):
                raise ValueError("Overpass normalized coordinates differ from raw geometry")
            node_ids = raw_line.get("nodes")
            valid_nodes = isinstance(node_ids, list) and len(node_ids) == len(part) and all(isinstance(n, int) and not isinstance(n, bool) for n in node_ids)
            nodes_complete &= valid_nodes
            if valid_nodes:
                for point, node_id in zip(part, node_ids):
                    point["osm_node_id"] = node_id
        if not nodes_complete:
            missing_nodes += 1
        # Routing restrictions come from the hash-bound raw OSM element. A
        # normalized vector can be rebound independently and is not authority
        # to remove access or pedestrian direction restrictions from that raw.
        tags = element.get("tags", {})
        if not isinstance(tags, dict):
            raise ValueError("Overpass raw OSM tags are malformed")
        source_id = f"overpass.{osm_type}.{osm_id}.{reader.bind(ref)[:12]}"
        sources.append(_source(source_id, str(props.get("name") or source_id), "overpass", ref, reader, parts,
                               {"osm_type": osm_type, "osm_id": osm_id, "osm_tags": tags,
                                "raw_ref": raw_ref, "raw_sha256": reader.bind(raw_ref),
                                "source_hashes": {**dependencies, raw_ref: reader.bind(raw_ref)},
                                "topology_status": "osm_node_ids" if nodes_complete else "missing_osm_node_ids",
                                "review_state": props.get("review_state", "needs_review"),
                                "observed_at": props.get("last_verified_at") or request.get("request_timestamp"),
                                "stale_risk": props.get("known_staleness_risk", "unknown"),
                                "endpoint": props.get("endpoint") or request.get("endpoint"),
                                "timing_semantics": "unknown_no_recorded_timestamps"}))
    if missing_nodes:
        issues.append(_issue("OVERPASS_TOPOLOGY_UNAVAILABLE", f"{missing_nodes} vector sources have no complete OSM node identities; graph search excludes them.", kind="overpass"))
    return sources, issues


def _mapsforge_sources(reader: _Reader, descriptor: dict[str, Any]) -> list[dict[str, Any]]:
    ref = descriptor["ref"]
    payload = reader.read(ref, descriptor["sha256"])
    props = payload.get("properties", {})
    if (payload.get("type") != "FeatureCollection" or props.get("source_kind") != "mapsforge_vector"
            or props.get("extractor") != "mapsforge-map-reader" or props.get("topology_available") is not False
            or any(props.get(key) != value for key, value in BOUNDARY.items())):
        raise ValueError("Mapsforge source authority/reader contract mismatch")
    hashes = {ref: reader.bind(ref), descriptor["manifest_ref"]: reader.bind(descriptor["manifest_ref"], descriptor["manifest_sha256"])}
    for dependency, expected in descriptor.get("input_source_hashes", {}).items():
        hashes[dependency] = reader.bind(dependency, expected)
    source_ref = props["source_ref"]
    if hashes.get(source_ref) != props["source_sha256"]:
        raise ValueError("Mapsforge source map is not bound")
    result = []
    for feature in payload.get("features", []):
        tags = feature.get("properties", {}).get("tags", {})
        if feature.get("properties", {}).get("topology_available") is not False:
            raise ValueError("Mapsforge feature cannot assert graph connectivity")
        result.append(_source(f"mapsforge.{reader.bind(ref)[:12]}.{feature['id'][:16]}",
            str(tags.get("name") or tags.get("ref") or tags.get("highway") or "Mapsforge path"),
            "mapsforge_vector", ref, reader, _parts(feature["geometry"]),
            {**props, **feature["properties"], "source_hashes": hashes, "timing_semantics": "unknown_no_recorded_timestamps"}))
    return result


def _rudy_sources(reader: _Reader, descriptor: dict[str, Any] | str) -> list[dict[str, Any]]:
    descriptor = {"ref": descriptor} if isinstance(descriptor, str) else descriptor
    ref = descriptor["ref"]
    payload = reader.read(ref, descriptor.get("sha256"))
    props = payload.get("properties", {})
    if payload.get("type") != "FeatureCollection" or props.get("candidate_only") is not True or props.get("runtime_safety_truth") is not False:
        raise ValueError("Rudy trace requires candidate-only FeatureCollection provenance")
    method = props.get("trace_method")
    allowed_method = method == "human_map_trace" or (
        method == "software_authored_map_trace" and props.get("trace_author_kind") == "software"
        and props.get("human_reviewed") is True and props.get("reviewer_kind") == "human")
    if not allowed_method or props.get("review_state") != "human_reviewed" or not props.get("reviewed_by") or not props.get("reviewed_at"):
        raise ValueError("Rudy trace needs explicit human drawing/review provenance")
    if props.get("source_layer") not in {"rudy-twmap", "happyman_rudy_twmap"}:
        raise ValueError("Rudy trace has no Rudy+TWMap source-layer binding")
    dependencies = props.get("source_artifacts")
    if not isinstance(dependencies, list) or not dependencies:
        raise ValueError("Rudy trace must bind its map evidence artifacts")
    hashes = {ref: reader.bind(ref)}
    for dependency, expected in descriptor.get("input_source_hashes", {}).items():
        hashes[dependency] = reader.bind(dependency, expected)
    if descriptor.get("manifest_ref"):
        hashes[descriptor["manifest_ref"]] = reader.bind(descriptor["manifest_ref"], descriptor["manifest_sha256"])
    for artifact in dependencies:
        hashes[artifact["ref"]] = reader.bind(artifact["ref"], artifact["sha256"])
    result = []
    for index, feature in enumerate(payload.get("features", [])):
        feature_id = str(feature.get("id") or index)
        result.append(_source(f"rudy.{reader.bind(ref)[:12]}.{feature_id}",
                              str(feature.get("properties", {}).get("name") or "Rudy 人工描繪"),
                              "rudy_trace", ref, reader, _parts(feature["geometry"]),
                              {**props, "source_hashes": hashes, "timing_semantics": "unknown_no_recorded_timestamps"}))
    return result


def _trh_sources(reader: _Reader, project: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    from terrain_route_guidance_workspace import _terrain_parent_binding, load_reviewed_guidance_execution_plan
    from terrain_route_hypothesis_models import TerrainRouteHypothesisCatalog, TerrainRouteHypothesisRun

    bindings = []
    catalog_ref = project.get("terrain_route_hypothesis_catalog_ref")
    if catalog_ref:
        catalog = TerrainRouteHypothesisCatalog.model_validate(reader.read(catalog_ref, project["terrain_route_hypothesis_catalog_sha256"]))
        if catalog.project_id != project.get("project_id"):
            raise ValueError("TRH catalog belongs to a different project")
        bindings.extend({"ref": e.hypothesis_ref, "sha256": e.hypothesis_sha256, "cache_key": e.cache_key, "selection_id": e.id} for e in catalog.entries)
    active_ref = project.get("terrain_route_hypothesis_ref")
    if active_ref and all(binding["ref"] != active_ref for binding in bindings):
        bindings.append({"ref": active_ref, "sha256": project["terrain_route_hypothesis_sha256"],
                         "cache_key": project["terrain_route_hypothesis_cache_key"], "selection_id": "active"})
    if not bindings:
        return [], [_issue("TRH_SOURCE_UNAVAILABLE", "No completed hash-bound terrain route has been prepared.", kind="trh")]
    if project.get("terrain_route_hypothesis_candidate_only") is not True or project.get("terrain_route_hypothesis_runtime_safety_truth") is not False:
        raise ValueError("TRH project candidate authority is missing")
    parent = _terrain_parent_binding(reader.root, project, required=True)
    if parent["dem_crs"] == "UNKNOWN":
        raise ValueError("TRH active DEM CRS is unavailable")
    parent_hashes = {parent["dem_ref"]: reader.bind(parent["dem_ref"], parent["dem_sha256"]),
                     parent["parent_manifest_ref"]: reader.bind(parent["parent_manifest_ref"], parent["parent_manifest_sha256"])}
    sources, issues = [], []
    for binding in bindings:
        try:
            run = TerrainRouteHypothesisRun.model_validate(reader.read(binding["ref"], binding["sha256"]))
            if run.status.value != "completed" or not run.hypotheses:
                raise ValueError("TRH run is not completed")
            for hypothesis in run.hypotheses:
                prov = hypothesis.provenance
                if prov.cache_key != binding["cache_key"] or hypothesis.best_path.crs != "EPSG:4326" or hypothesis.start.crs != "EPSG:4326" or hypothesis.destination.crs != "EPSG:4326":
                    raise ValueError("TRH geometry/cache binding is invalid")
                chain = prov.processing_manifest.get("parent_source_hashes", {})
                if any(chain.get(ref) != sha for ref, sha in parent_hashes.items()):
                    raise ValueError("TRH DEM or parent manifest is stale")
                if prov.dem_crs.upper() != parent["dem_crs"].upper() or prov.dem_resolution_m != parent["dem_resolution_m"]:
                    raise ValueError("TRH DEM resolution/CRS changed")
                geometry = hypothesis.best_path.model_dump(mode="json")
                parts = _parts(geometry)
                tolerance = max(30.0, parent["dem_resolution_m"] * 2)
                if _distance(parts[0][0], {"lon": hypothesis.start.x, "lat": hypothesis.start.y}) > tolerance or _distance(parts[0][-1], {"lon": hypothesis.destination.x, "lat": hypothesis.destination.y}) > tolerance:
                    raise ValueError("TRH path endpoints differ from declared A/B")
                hashes = {**parent_hashes, binding["ref"]: reader.bind(binding["ref"])}
                if catalog_ref:
                    hashes[catalog_ref] = reader.bind(catalog_ref)
                provenance = {"hypothesis_id": hypothesis.id, "selection_id": binding["selection_id"],
                              "alternative_index": hypothesis.alternative_index, "cache_key": binding["cache_key"],
                              "path_sha256": _hash(_json_bytes(geometry)), "input_endpoints": prov.input_endpoints,
                              "start": hypothesis.start.model_dump(mode="json"), "destination": hypothesis.destination.model_dump(mode="json"),
                              "dem_sha256": parent["dem_sha256"], "dem_resolution_m": parent["dem_resolution_m"],
                              "parent_manifest_sha256": parent["parent_manifest_sha256"], "dem_crs": parent["dem_crs"],
                              "unknowns": [x.model_dump(mode="json") for x in hypothesis.unknowns],
                              "timing_semantics": "model_cost_is_not_duration", "review_state": "candidate_review_required"}
                if hypothesis.alternative_index == 4:
                    try:
                        guidance = prov.processing_manifest.get("guidance_execution", {})
                        execution = load_reviewed_guidance_execution_plan(reader.root, project_id=project["project_id"],
                                    guidance_id=guidance["guidance_id"], review_sha256=guidance["guidance_review_sha256"])
                        if hypothesis.path_semantics != "ordered_anchor_piecewise_anisotropic_model_cost_trace":
                            raise ValueError("R4 does not preserve guided path semantics")
                        if guidance.get("raw_narrative_forwarded_to_worker") is not False or any(guidance.get(key) != value for key, value in BOUNDARY.items()):
                            raise ValueError("R4 execution provenance changed its candidate-only boundary")
                        execution_payload = execution.model_dump(mode="json")
                        for key in ("anchors", "review_decisions", "disabled_constraint_ids", "cost_modifiers"):
                            if guidance.get(key) != execution_payload[key]:
                                raise ValueError(f"R4 {key} differ from the bound human review")
                        for name in ("narrative", "plan", "feature_index", "resolution", "review", "manifest"):
                            dependency = project.get(f"terrain_route_guidance_{name}_ref")
                            if not dependency:
                                raise ValueError(f"R4 {name} artifact is unavailable")
                            hashes[dependency] = reader.bind(dependency)
                        feature_index = reader.read(project["terrain_route_guidance_feature_index_ref"])
                        window = feature_index.get("search_window") or {}
                        for key, endpoint in (("route_start", hypothesis.start), ("route_destination", hypothesis.destination)):
                            expected = window.get(key) or {}
                            if expected.get("x") != endpoint.x or expected.get("y") != endpoint.y:
                                raise ValueError("R4 reviewed A/B differs from this route")
                        for name in ("plan_sha256", "resolution_sha256", "feature_index_sha256"):
                            if guidance.get(name) != getattr(execution, name):
                                raise ValueError(f"R4 {name} execution binding changed")
                        provenance.update({"guidance_execution": execution_payload,
                                           "review_state": "human_reviewed_candidate_only"})
                    except (ValueError, KeyError, TypeError, OSError) as exc:
                        issues.append(_issue("R4_REVIEW_UNAVAILABLE", str(exc), kind="trh_r4"))
                        continue
                elif hypothesis.alternative_index not in (1, 2, 3) or hypothesis.path_semantics != "minimum_anisotropic_model_cost_trace":
                    continue
                provenance["source_hashes"] = hashes
                sources.append(_source(f"trh.{binding['cache_key'][:12]}.r{hypothesis.alternative_index}", hypothesis.label,
                                       f"trh_r{hypothesis.alternative_index}", binding["ref"], reader, parts, provenance))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            issues.append(_issue("TRH_SOURCE_STALE", f"{binding['selection_id']}: {exc}", kind="trh"))
    return sources, issues


def _distance(a: dict[str, Any], b: dict[str, Any]) -> float:
    lat1, lat2 = math.radians(float(a["lat"])), math.radians(float(b["lat"]))
    dlat = lat2 - lat1
    dlon = math.radians(float(b["lon"]) - float(a["lon"]))
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371008.8 * 2 * math.asin(min(1.0, math.sqrt(h)))


def find_trail_path(sources: list[dict[str, Any]], start: dict[str, Any], end: dict[str, Any],
                    via: list[dict[str, Any]] | None = None, *, endpoint_tolerance_m: float = 30.0) -> dict[str, Any]:
    """Search ordered A/via/B over actual OSM node edges, never spatial crossings.

    Success returns ``selections`` in compiler order, each with source_id,
    part_index, start_index, end_index, and direction.  Endpoint snapping is
    explicit; multiple distinct nodes at the same nearest location are ambiguous.
    Optional ``osm_node_id`` on an endpoint resolves that ambiguity.
    """
    if not math.isfinite(endpoint_tolerance_m) or not 0 <= endpoint_tolerance_m <= 100:
        raise ValueError("endpoint tolerance must be between 0 and 100 metres")
    graph: dict[int, list[tuple[int, float, dict[str, Any]]]] = {}
    nodes: dict[int, dict[str, Any]] = {}
    invalid_nodes: set[int] = set()
    for source in sources:
        if source.get("kind") != "overpass" or source.get("provenance", {}).get("topology_status") != "osm_node_ids":
            continue
        tags = source["provenance"].get("osm_tags", {})
        if tags.get("foot") in {"no", "private"} or (tags.get("access") in {"no", "private"} and tags.get("foot") not in {"yes", "designated", "permissive"}):
            continue
        for part_index, part in enumerate(source["parts"]):
            for point in part:
                node = point.get("osm_node_id")
                if not isinstance(node, int):
                    continue
                if node in nodes and _distance(nodes[node], point) > 0.05:
                    invalid_nodes.add(node)
                nodes[node] = point
            for index, (a, b) in enumerate(zip(part, part[1:])):
                if "osm_node_id" not in a or "osm_node_id" not in b:
                    continue
                for forward in (True, False):
                    foot_oneway = str(tags.get("oneway:foot", "no")).lower()
                    if (foot_oneway in {"yes", "1", "true"} and not forward) or (foot_oneway == "-1" and forward):
                        continue
                    i, j = (index, index + 1) if forward else (index + 1, index)
                    edge = {"source_id": source["source_id"], "part_index": part_index,
                            "start_index": i, "end_index": j, "direction": "forward" if forward else "reverse"}
                    graph.setdefault(part[i]["osm_node_id"], []).append((part[j]["osm_node_id"], _distance(a, b), edge))
    def unavailable(code: str, message: str, **extra: Any) -> dict[str, Any]:
        return {"status": "blocked", "selections": [], "parts": [], "source_ids": [],
                "provenance": {}, "issues": [_issue(code, message, blocking=True)], **extra, **BOUNDARY}
    if invalid_nodes:
        return unavailable("OSM_NODE_COORDINATE_CONFLICT", "The same OSM node ID has conflicting source coordinates.")
    if not graph:
        return unavailable("TRAIL_TOPOLOGY_UNAVAILABLE", "No connected trail data with genuine OSM node identities is available.")
    snaps = []
    for endpoint in [start, *(via or []), end]:
        point = _point(endpoint)
        eligible = [(node, _distance(point, coord)) for node, coord in nodes.items()]
        if endpoint.get("osm_node_id") is not None:
            eligible = [item for item in eligible if item[0] == endpoint["osm_node_id"]]
        eligible.sort(key=lambda item: (item[1], item[0]))
        if not eligible or eligible[0][1] > endpoint_tolerance_m:
            return unavailable("TRAIL_ENDPOINT_UNLOCATED", "An endpoint is outside the prepared trail-node tolerance.", endpoint=point)
        if len(eligible) > 1 and abs(eligible[0][1] - eligible[1][1]) < 0.05:
            return unavailable("TRAIL_ENDPOINT_AMBIGUOUS", "Distinct OSM nodes coincide near the endpoint; select the intended node.", candidates=[x[0] for x in eligible if x[1] - eligible[0][1] < 0.05])
        snaps.append({"osm_node_id": eligible[0][0], "distance_m": eligible[0][1], "requested": point, "matched": nodes[eligible[0][0]]})
    edges, total = [], 0.0
    for leg_index, (left, right) in enumerate(zip(snaps, snaps[1:])):
        a, b = left["osm_node_id"], right["osm_node_id"]
        queue = [(0.0, a)]
        best = {a: 0.0}
        previous = {}
        while queue:
            cost, node = heapq.heappop(queue)
            if cost != best[node]:
                continue
            if node == b:
                break
            for neighbor, weight, edge in graph.get(node, []):
                updated = cost + weight
                if updated < best.get(neighbor, math.inf):
                    best[neighbor] = updated
                    previous[neighbor] = (node, edge)
                    heapq.heappush(queue, (updated, neighbor))
        if b not in best:
            return unavailable("TRAIL_DISCONNECTED", "No OSM-node-connected trail joins this ordered itinerary leg.", leg_index=leg_index, snapped_endpoints=snaps)
        total += best[b]
        leg_edges, cursor = [], b
        while cursor != a:
            cursor, edge = previous[cursor]
            leg_edges.append(edge)
        edges.extend(reversed(leg_edges))
    selections = []
    for edge in edges:
        if selections and all(selections[-1][key] == edge[key] for key in ("source_id", "part_index", "direction")) and selections[-1]["end_index"] == edge["start_index"]:
            selections[-1]["end_index"] = edge["end_index"]
        else:
            selections.append(dict(edge))
    by_id = {source["source_id"]: source for source in sources}
    points = []
    hashes = {}
    for selection in selections:
        source = by_id[selection["source_id"]]
        part = source["parts"][selection["part_index"]]
        i, j = selection["start_index"], selection["end_index"]
        selected = [part[k] for k in range(i, j + (1 if j >= i else -1), 1 if j >= i else -1)]
        points.extend(selected[1:] if points else selected)
        hashes.update(source["provenance"].get("source_hashes", {}))
    if len(points) < 2:
        return unavailable("TRAIL_ENDPOINTS_COINCIDENT", "The requested trail path has no traversed edges.")
    return {"status": "ready", "selections": selections, "parts": [points], "distance_m": total,
            "source_ids": list(dict.fromkeys(selection["source_id"] for selection in selections)),
            "provenance": {"source_hashes": hashes, "selections": selections, "snapped_endpoints": snaps,
                           "routing_method": "ordered_via_dijkstra_osm_node_edges", **BOUNDARY},
            "snapped_endpoints": snaps, "source_hashes": hashes, "issues": [],
            "routing_method": "ordered_via_dijkstra_osm_node_edges", **BOUNDARY}


def fetch_trail_source_candidates(bbox: dict[str, float], *,
                                  fetcher: Callable[[str, str], bytes] | None = None,
                                  requested_at: str | None = None) -> dict[str, Any]:
    """Fetch a public bounded Overpass query; return immutable files, never write.

    The caller publishes ``files`` under a new candidate bundle and appends
    ``project_binding`` to planned_overpass_source_refs.  No existing source ref
    is replaced.  Tests supply a recorded-response fetcher.
    """
    from pretrip_models import RouteBBox
    from pretrip_overpass_ingest import import_overpass_evidence_candidates

    south, west, north, east = (float(bbox[k]) for k in ("south", "west", "north", "east"))
    if not all(math.isfinite(x) for x in (south, west, north, east)) or not (-90 <= south < north <= 90 and -180 <= west < east <= 180):
        raise ValueError("trail query requires a finite non-empty WGS84 bbox")
    endpoint = "https://overpass-api.de/api/interpreter"
    query = f'[out:json][timeout:40];way["highway"~"^(path|footway|track|steps|bridleway|pedestrian|service|tertiary|unclassified)$"]({south:.7f},{west:.7f},{north:.7f},{east:.7f});out body geom;'
    if fetcher is None:
        def fetcher(url: str, body: str) -> bytes:
            request = urllib.request.Request(url, data=urllib.parse.urlencode({"data": body}).encode(), method="POST",
                                             headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "Scout-Planned-GPX-Candidate/1"})
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.read()
    raw = fetcher(endpoint, query)
    raw_sha = _hash(raw)
    timestamp = requested_at or datetime.now(timezone.utc).isoformat()
    bundle_sha = _hash(_json_bytes({"raw_sha256": raw_sha, "query": query, "requested_at": timestamp}))
    prefix = f"normalized/map/planned-overpass/{bundle_sha}"
    raw_ref, vector_ref = f"{prefix}/overpass_raw.json", f"{prefix}/overpass_vector_evidence.geojson"
    result = import_overpass_evidence_candidates(json.loads(raw), query_body=query,
                 bbox_wgs84=RouteBBox(min_lat=south, min_lon=west, max_lat=north, max_lon=east),
                 request_timestamp=timestamp, endpoint=endpoint,
                 http_status=200, raw_payload_uri=raw_ref, raw_response_sha256=raw_sha,
                 normalized_artifact_path=vector_ref, source_ref=raw_ref)
    vector = _json_bytes(result.normalized_geojson)
    return {"status": "candidate_fetched", "files": {raw_ref: raw, vector_ref: vector},
            "project_binding": {"ref": vector_ref, "sha256": _hash(vector), "raw_ref": raw_ref, "raw_sha256": raw_sha},
            "source_hashes": {raw_ref: raw_sha, vector_ref: _hash(vector)},
            "query": query, "bbox_wgs84": bbox, "writes_performed": False, **BOUNDARY}
