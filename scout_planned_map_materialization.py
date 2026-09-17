"""Immutable map-source repair and reviewed Rudy tracing for Planned GPX.

Re-materialization derives new geometry from current source bytes. It never
repairs an old evidence hash in place or declares a model/map trace walkable.
The append-only catalog is discovery metadata; plans bind immutable bundles.
"""
from __future__ import annotations

import fcntl
import hashlib
import io
import json
import math
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from scout_planned_route_sources import BOUNDARY, _Reader, _json_bytes, _parts

CATALOG_REF = "outputs/planned_map_sources/catalog.json"
SCHEMA = "plannedMapSourceMaterialization.v1"


class PlannedMapMaterializationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_kind: Literal["osm_pbf", "overpass_raw", "mapsforge_vector"] = "osm_pbf"
    source_ref: str | None = None
    expected_source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    bbox_wgs84: dict[str, float] | None = None
    requested_by: str = Field(default="dashboard_operator", min_length=1, max_length=120)
    requested_at: datetime | None = None

    @field_validator("requested_at")
    @classmethod
    def aware_time(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("requested_at must include timezone")
        return value


class RudyMapEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    z: int = Field(ge=0, le=22)
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    source_layer: Literal["rudy-twmap", "happyman_rudy_twmap"] = "happyman_rudy_twmap"
    source_manifest_ref: str
    source_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PlannedRudyTraceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=240)
    geometry: dict[str, Any]
    map_evidence: list[RudyMapEvidence] = Field(min_length=1)
    reviewed_by: str = Field(min_length=1, max_length=120)
    reviewer_kind: Literal["human", "software"]
    trace_author_kind: Literal["human", "software"] | None = None
    review_note: str = Field(min_length=1, max_length=4000)
    reviewed_at: datetime | None = None
    candidate_review_confirmed: bool
    reviewed_draft_ref: str | None = None
    reviewed_draft_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("reviewed_at")
    @classmethod
    def aware_time(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("reviewed_at must include timezone")
        return value


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _producer_hashes() -> dict[str, str]:
    root = Path(__file__).parent
    return {name: _sha((root / name).read_bytes()) for name in (
        "scout_planned_map_materialization.py", "pretrip_osm_pbf_ingest.py", "pretrip_overpass_ingest.py")}


def _safe(root: Path, ref: str, *, exists: bool = True) -> Path:
    if not isinstance(ref, str) or not ref or Path(ref).is_absolute() or ".." in Path(ref).parts or ref.startswith("~"):
        raise ValueError("map materialization paths must be workspace relative")
    path = (root / ref).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError("map materialization path escapes workspace")
    if exists and not path.is_file():
        raise ValueError(f"map materialization source is unavailable: {ref}")
    return path


def _project(root: Path) -> dict[str, Any]:
    project = json.loads(_safe(root, "project.json").read_bytes())
    if not isinstance(project, dict):
        raise ValueError("map materialization requires a project object")
    project_id = project.get("project_id")
    if not isinstance(project_id, str) or not project_id or Path(project_id).parts != (project_id,):
        raise ValueError("map materialization requires a project identity")
    return project


def _bbox(value: dict[str, Any]) -> dict[str, float]:
    result = {key: float(value[key]) for key in ("south", "west", "north", "east")}
    if not all(math.isfinite(v) for v in result.values()) or not (-90 <= result["south"] < result["north"] <= 90 and -180 <= result["west"] < result["east"] <= 180):
        raise ValueError("map source bbox must be non-empty finite WGS84 coordinates")
    return result


def _existing_bbox(root: Path, project: dict[str, Any]) -> dict[str, float]:
    for key in ("overpass_evidence_ref", "overpass_map_context_ref"):
        ref = project.get(key)
        if not ref:
            continue
        payload = json.loads(_safe(root, ref).read_bytes())
        box = (payload.get("request") or payload.get("properties") or {}).get("bbox_wgs84", {})
        if set(("south", "west", "north", "east")) <= box.keys():
            return _bbox(box)
        if set(("min_lat", "min_lon", "max_lat", "max_lon")) <= box.keys():
            return _bbox(dict(south=box["min_lat"], west=box["min_lon"], north=box["max_lat"], east=box["max_lon"]))
    raise ValueError("explicit source bbox is required when no bound map extent exists")


def _legacy_sources(root: Path, project: dict[str, Any]) -> dict[str, Any]:
    hashes: dict[str, str] = {}
    declared_raw_hashes: set[str] = set()
    unreadable_declarations: list[str] = []
    for key in ("overpass_evidence_ref", "overpass_map_context_ref", "overpass_raw_payload_ref", "osm_pbf_raw_payload_ref"):
        ref = project.get(key)
        if not ref:
            continue
        raw = _safe(root, ref).read_bytes()
        hashes[ref] = _sha(raw)
        if key in ("overpass_evidence_ref", "overpass_map_context_ref"):
            try:
                payload = json.loads(raw)
                declaration = (payload.get("request") or payload.get("properties") or {})
                expected = declaration.get("raw_response_sha256")
            except (ValueError, TypeError, AttributeError):
                unreadable_declarations.append(ref)
                continue
            if isinstance(expected, str):
                declared_raw_hashes.add(expected)
    raw_ref = project.get("overpass_raw_payload_ref") or project.get("osm_pbf_raw_payload_ref")
    actual = hashes.get(raw_ref)
    mismatch = bool(actual and declared_raw_hashes and any(expected != actual for expected in declared_raw_hashes))
    return {"source_hashes": hashes, "raw_ref": raw_ref, "actual_raw_sha256": actual,
            "declared_raw_sha256": sorted(declared_raw_hashes),
            "state": "legacy_raw_hash_mismatch" if mismatch else "legacy_unreadable_declaration" if unreadable_declarations else "legacy_preserved",
            "unreadable_declarations": unreadable_declarations,
            "files_modified": False}


def _pbf_payload(path: Path, box: dict[str, float]) -> dict[str, Any]:
    try:
        import osmium
    except ImportError as exc:
        raise ValueError("Local PBF materialization requires the optional osmium runtime") from exc
    from pretrip_osm_pbf_ingest import _PbfRouteEvidenceHandler
    handler = _PbfRouteEvidenceHandler(bbox=box, osmium_module=osmium)
    handler.apply_file(path.as_posix(), locations=True)
    return {"version": 0.6, "generator": "scout.planned_map_materialization.pyosmium",
            "elements": handler.elements}


def _publish(root: Path, project_id: str, bundle_id: str, files: dict[str, bytes],
             manifest: dict[str, Any]) -> dict[str, Any]:
    prefix = f"outputs/planned_map_sources/bundles/{bundle_id}"
    manifest_ref = f"{prefix}/manifest.json"
    manifest = {"schema_version": SCHEMA, "project_id": project_id, "materialization_id": bundle_id,
                **manifest, "artifacts": {ref: _sha(raw) for ref, raw in files.items()}, **BOUNDARY}
    manifest_raw = _json_bytes(manifest)
    expected_manifest_sha = _sha(manifest_raw)
    files = {**files, manifest_ref: manifest_raw}
    # Validate every output and directory before performing any writes.
    paths = {ref: _safe(root, ref, exists=False) for ref in files}
    catalog_path = _safe(root, CATALOG_REF, exists=False)
    lock_path = _safe(root, "outputs/planned_map_sources/catalog.lock", exists=False)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        current = _project(root)
        if current["project_id"] != project_id:
            raise ValueError("project identity changed during map materialization")
        for ref, expected in manifest.get("input_source_hashes", {}).items():
            _Reader(root).bind(ref, expected)
        if catalog_path.exists():
            catalog = json.loads(catalog_path.read_bytes())
            if not isinstance(catalog, dict) or catalog.get("schema_version") != SCHEMA or catalog.get("project_id") != project_id or not isinstance(catalog.get("entries"), list) or any(not isinstance(row, dict) for row in catalog["entries"]):
                raise ValueError("map materialization catalog belongs to a different schema/project or is malformed")
        else:
            catalog = {"schema_version": SCHEMA, "project_id": project_id, "entries": [], **BOUNDARY}
        for ref, raw in files.items():
            path = paths[ref]
            if path.exists() and path.read_bytes() != raw:
                raise ValueError(f"immutable map materialization collision: {ref}")
        for ref, raw in files.items():
            path = paths[ref]
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                with path.open("xb") as output:
                    output.write(raw)
                    output.flush()
                    os.fsync(output.fileno())
        entry = {"materialization_id": bundle_id, "kind": manifest["kind"],
                 "manifest_ref": manifest_ref, "manifest_sha256": expected_manifest_sha,
                 "source_state": manifest["source_state"]}
        previous = next((row for row in catalog["entries"] if row["materialization_id"] == bundle_id), None)
        if previous is not None and previous != entry:
            raise ValueError("immutable map catalog entry collision")
        if previous is None:
            catalog["entries"].append(entry)
            temporary = catalog_path.with_name(f"catalog.{uuid.uuid4().hex}.tmp")
            with temporary.open("xb") as output:
                output.write(_json_bytes(catalog))
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, catalog_path)
    return {"status": "materialized", "materialization_id": bundle_id,
            "catalog_ref": CATALOG_REF, "manifest_ref": manifest_ref,
            "manifest_sha256": expected_manifest_sha, "source_state": manifest["source_state"],
            "project_binding": manifest["project_binding"], "source_counts": manifest.get("source_counts", {}),
            "legacy_sources": manifest.get("legacy_sources"), "artifacts": manifest["artifacts"],
            "project_modified": False, **BOUNDARY}


def materialize_map_sources(project_root: Path, request: dict[str, Any] | PlannedMapMaterializationRequest) -> dict[str, Any]:
    """Build a new source version, preserving both legacy declarations and bytes."""
    request = PlannedMapMaterializationRequest.model_validate(request)
    if request.source_kind == "mapsforge_vector":
        from scout_mapsforge_source import materialize_mapsforge_sources
        return materialize_mapsforge_sources(project_root, request.model_dump(mode="json"))
    root = Path(project_root).resolve()
    project = _project(root)
    ref = request.source_ref or (project.get("osm_pbf_route_extract_ref") or project.get("osm_pbf_render_extract_ref")
                                if request.source_kind == "osm_pbf" else
                                project.get("overpass_raw_payload_ref") or project.get("osm_pbf_raw_payload_ref"))
    if not ref:
        raise ValueError("the selected map source family has no local source")
    source_path = _safe(root, ref)
    source_raw = source_path.read_bytes()
    source_sha = _sha(source_raw)
    if request.expected_source_sha256 and source_sha != request.expected_source_sha256:
        raise ValueError("map source changed since selection")
    box = _bbox(request.bbox_wgs84) if request.bbox_wgs84 else _existing_bbox(root, project)
    at = (request.requested_at or datetime.now(timezone.utc)).isoformat()
    payload = _pbf_payload(source_path, box) if request.source_kind == "osm_pbf" else json.loads(source_raw)
    if not isinstance(payload, dict) or not isinstance(payload.get("elements"), list):
        raise ValueError("map raw source has no OSM elements")
    raw = _json_bytes(payload) if request.source_kind == "osm_pbf" else source_raw
    raw_sha = _sha(raw)
    identity = {"schema_version": SCHEMA, "producer_hashes": _producer_hashes(), "project_id": project["project_id"], "source_kind": request.source_kind,
                "source_ref": ref, "source_sha256": source_sha, "raw_sha256": raw_sha,
                "bbox_wgs84": box, "requested_by": request.requested_by, "requested_at": at}
    bundle_id = _sha(_json_bytes(identity))
    prefix = f"outputs/planned_map_sources/bundles/{bundle_id}"
    raw_ref, vector_ref, evidence_ref = (f"{prefix}/{name}" for name in ("raw.osm.json", "vectors.geojson", "evidence.json"))
    from pretrip_models import RouteBBox
    from pretrip_osm_pbf_ingest import import_osm_pbf_evidence_candidates
    from pretrip_overpass_ingest import import_overpass_evidence_candidates
    bbox_model = RouteBBox(min_lat=box["south"], min_lon=box["west"], max_lat=box["north"], max_lon=box["east"])
    common = dict(query_body=json.dumps(identity, sort_keys=True), bbox_wgs84=bbox_model,
                  request_timestamp=at, endpoint=f"workspace-{request.source_kind}://{ref}",
                  raw_payload_uri=raw_ref, raw_response_sha256=raw_sha,
                  normalized_artifact_path=vector_ref, source_ref=raw_ref)
    if request.source_kind == "osm_pbf":
        evidence = import_osm_pbf_evidence_candidates(payload, route_corridor=None, pbf_source_uri=ref,
                    pbf_source_sha256=source_sha, extraction_plan={**identity, "extractor": "pyosmium_with_node_refs", "external_network_calls_made": False}, **common)
        vector = evidence["normalized_geojson"]
    else:
        imported = import_overpass_evidence_candidates(payload, http_status=200, **common)
        evidence = imported.model_dump(mode="json") if hasattr(imported, "model_dump") else {
            "request": imported.request.model_dump(mode="json"), "counts": imported.counts,
            "source_artifact": imported.source_artifact.model_dump(mode="json"), **BOUNDARY}
        vector = imported.normalized_geojson
    vector_raw, evidence_raw = _json_bytes(vector), _json_bytes(evidence)
    route_features = [f for f in vector.get("features", []) if f.get("properties", {}).get("candidate_type") in {"trail_corridor_candidate", "hiking_route_candidate"}]
    ways = [e for e in payload["elements"] if e.get("type") == "way" and e.get("tags", {}).get("highway")]
    node_ways = sum(isinstance(e.get("nodes"), list) and len(e["nodes"]) == len(e.get("geometry", [])) for e in ways)
    state = "topology_ready" if route_features and node_ways else "vectors_ready_topology_missing" if route_features else "empty"
    binding = {"ref": vector_ref, "sha256": _sha(vector_raw), "raw_ref": raw_ref, "raw_sha256": raw_sha,
               "evidence_ref": evidence_ref, "evidence_sha256": _sha(evidence_raw),
               "input_source_hashes": {ref: source_sha}, "materialization_id": bundle_id}
    return _publish(root, project["project_id"], bundle_id,
                    {raw_ref: raw, vector_ref: vector_raw, evidence_ref: evidence_raw},
                    {"kind": "overpass", "request": identity, "input_source_hashes": {ref: source_sha},
                     "source_state": state, "project_binding": binding,
                     "source_counts": {"osm_elements": len(payload["elements"]), "route_candidates": len(route_features),
                                       "ways": len(ways), "ways_with_node_ids": node_ways},
                     "legacy_sources": _legacy_sources(root, project)})


def materialize_rudy_trace(project_root: Path, request: dict[str, Any] | PlannedRudyTraceRequest) -> dict[str, Any]:
    """Bind reviewed vector vertices to actual georeferenced Rudy tile pixels.

    A software review remains pending human review; it never becomes a usable
    source, human approval or field verification. Source tiles are copied to the immutable bundle.
    """
    from PIL import Image
    request = PlannedRudyTraceRequest.model_validate(request)
    if not request.candidate_review_confirmed:
        raise ValueError("Rudy vector requires explicit candidate review")
    root = Path(project_root).resolve()
    project = _project(root)
    parts = _parts(request.geometry)
    reader = _Reader(root)
    if bool(request.reviewed_draft_ref) != bool(request.reviewed_draft_sha256):
        raise ValueError("Rudy draft review requires both the immutable ref and SHA")
    if request.reviewed_draft_ref:
        draft = reader.read(request.reviewed_draft_ref, request.reviewed_draft_sha256)
        previous = draft.get("request", {})
        if (request.reviewer_kind != "human" or draft.get("project_id") != project["project_id"]
                or draft.get("kind") != "rudy_trace" or draft.get("source_state") != "pending_human_review"
                or previous.get("geometry") != request.geometry
                or previous.get("map_evidence") != [item.model_dump() for item in request.map_evidence]
                or (previous.get("trace_author_kind") or previous.get("reviewer_kind")) != request.trace_author_kind):
            raise ValueError("Rudy human review must preserve the exact pending draft and source evidence")
        for ref, sha in {**draft.get("artifacts", {}), **draft.get("input_source_hashes", {})}.items():
            reader.bind(ref, sha)
    tiles: list[dict[str, Any]] = []
    original_bytes: list[bytes] = []
    source_manifests: dict[str, bytes] = {}
    for item in request.map_evidence:
        source_manifest = reader.read(item.source_manifest_ref, item.source_manifest_sha256)
        plan = source_manifest.get("plan", {})
        accepted_projects = {project["project_id"], project.get("source_workspace_id")}
        if (source_manifest.get("candidate_only") is not True or source_manifest.get("runtime_safety_truth") is not False
                or source_manifest.get("imagery_source_id") != "happyman_rudy_twmap"
                or source_manifest.get("layer_id") != "rudy-twmap"
                or plan.get("source_id") != "happyman_rudy_twmap"
                or source_manifest.get("project_id") not in accepted_projects
                or plan.get("project_id") not in accepted_projects
                or plan.get("source_metadata", {}).get("tile_matrix_crs") != "EPSG:3857"):
            raise ValueError("Rudy evidence lacks a matching prepared source manifest")
        source_manifests[item.source_manifest_sha256] = reader.path(item.source_manifest_ref).read_bytes()
        reader.bind(item.ref, item.sha256)
        raw = reader.path(item.ref).read_bytes()
        if _sha(raw) != item.sha256:
            raise ValueError("Rudy map evidence changed while reading")
        if item.x >= 2 ** item.z or item.y >= 2 ** item.z:
            raise ValueError("Rudy tile address is outside its zoom matrix")
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            if image.format != "PNG" or image.size != (256, 256):
                raise ValueError("Rudy evidence must contain actual 256px PNG tiles")
            extrema = image.convert("RGBA").getextrema()
            if extrema[3][1] == 0 or all(lo == hi for lo, hi in extrema):
                raise ValueError("Rudy map evidence is transparent or uniform")
        tiles.append(item.model_dump())
        original_bytes.append(raw)
    # The slippy-tile address is an explicit georeference, not a manually shifted
    # screenshot. Every supplied vertex must fall within a bound tile's extent.
    for part in parts:
        for point in part:
            if abs(point["lat"]) > 85.05112878:
                raise ValueError("Rudy vector is outside the Web Mercator domain")
            matched = False
            for tile in tiles:
                scale = 2 ** tile["z"]
                x = (point["lon"] + 180) / 360 * scale
                y = (1 - math.asinh(math.tan(math.radians(point["lat"]))) / math.pi) / 2 * scale
                if tile["x"] - 1e-8 <= x <= tile["x"] + 1 + 1e-8 and tile["y"] - 1e-8 <= y <= tile["y"] + 1 + 1e-8:
                    matched = True
                    break
            if not matched:
                raise ValueError("Rudy vector vertex lies outside all bound map evidence")
    at = (request.reviewed_at or datetime.now(timezone.utc)).isoformat()
    identity = {"schema_version": SCHEMA, "producer_hashes": _producer_hashes(), "project_id": project["project_id"],
                **request.model_dump(mode="json"), "reviewed_at": at}
    bundle_id = _sha(_json_bytes(identity))
    prefix = f"outputs/planned_map_sources/bundles/{bundle_id}"
    files: dict[str, bytes] = {}
    artifacts = []
    for sha, raw in source_manifests.items():
        ref = f"{prefix}/rudy-source-{sha}.json"
        files[ref] = raw
        artifacts.append({"ref": ref, "sha256": sha, "kind": "rudy_source_manifest"})
    for tile, raw in zip(tiles, original_bytes):
        ref = f"{prefix}/rudy-{tile['z']}-{tile['x']}-{tile['y']}.png"
        if ref in files and files[ref] != raw:
            raise ValueError("Rudy tile identity has conflicting bytes")
        files[ref] = raw
        artifacts.append({**tile, "ref": ref, "original_ref": tile["ref"]})
    author_kind = request.trace_author_kind or request.reviewer_kind
    properties = {"trace_method": "human_map_trace" if author_kind == "human" else "software_authored_map_trace",
                  "trace_author_kind": author_kind,
                  "review_state": "human_reviewed" if request.reviewer_kind == "human" else "pending_human_review",
                  "reviewer_kind": request.reviewer_kind, "human_reviewed": request.reviewer_kind == "human",
                  "reviewed_by": request.reviewed_by, "reviewed_at": at, "review_note": request.review_note,
                  "candidate_review_confirmed": True, "field_verified": False,
                  "source_layer": "happyman_rudy_twmap", "source_artifacts": artifacts,
                  "georeference": "EPSG:3857_slippy_tile_matrix", "geometry_crs": "EPSG:4326", **BOUNDARY}
    ref = f"{prefix}/rudy-trace.geojson"
    trace = {"type": "FeatureCollection", "properties": properties,
             "features": [{"type": "Feature", "id": "reviewed-map-trace", "properties": {"name": request.label},
                           "geometry": request.geometry}]}
    files[ref] = _json_bytes(trace)
    binding = {"ref": ref, "sha256": _sha(files[ref]), "materialization_id": bundle_id,
               "input_source_hashes": reader.source_hashes}
    return _publish(root, project["project_id"], bundle_id, files,
                    {"kind": "rudy_trace", "request": identity, "input_source_hashes": reader.source_hashes,
                     "source_state": "human_reviewed" if request.reviewer_kind == "human" else "pending_human_review", "project_binding": binding,
                     "source_counts": {"route_candidates": 1, "vertices": sum(map(len, parts)), "map_tiles": len(tiles)}})


def read_materialization_catalog(project_root: Path, project_id: str) -> dict[str, Any]:
    """Read validated immutable entries; mutable discovery metadata is unbound."""
    root = Path(project_root).resolve()
    path = _safe(root, CATALOG_REF, exists=False)
    result: dict[str, Any] = {"overpass": [], "rudy_trace": [], "mapsforge_vector": [], "source_states": [], "issues": []}
    if not path.exists():
        return result
    catalog = json.loads(path.read_bytes())
    if not isinstance(catalog, dict) or catalog.get("schema_version") != SCHEMA or catalog.get("project_id") != project_id or not isinstance(catalog.get("entries"), list):
        raise ValueError("map source catalog schema/project identity is invalid")
    if any(catalog.get(key) != value for key, value in BOUNDARY.items()):
        raise ValueError("map source catalog changed candidate authority")
    for entry in catalog["entries"]:
        if not isinstance(entry, dict):
            result["issues"].append({"code": "MATERIALIZED_SOURCE_UNAVAILABLE", "message": "map source catalog entry is not an object", "source_kind": "map", "blocking": False})
            continue
        kind = entry.get("kind")
        try:
            if kind not in {"overpass", "rudy_trace", "mapsforge_vector"}:
                raise ValueError("unknown materialized map source kind")
            reader = _Reader(root)
            manifest = reader.read(entry["manifest_ref"], entry["manifest_sha256"])
            if manifest.get("project_id") != project_id or manifest.get("materialization_id") != entry["materialization_id"] or manifest.get("kind") != kind:
                raise ValueError("materialized map source identity changed")
            if any(manifest.get(key) != value for key, value in BOUNDARY.items()):
                raise ValueError("materialized map source changed candidate authority")
            for ref, sha in {**manifest["artifacts"], **manifest.get("input_source_hashes", {})}.items():
                reader.bind(ref, sha)
            descriptor = {**manifest["project_binding"], "manifest_ref": entry["manifest_ref"],
                          "manifest_sha256": entry["manifest_sha256"], "input_source_hashes": reader.source_hashes}
            result[kind].append(descriptor)
            result["source_states"].append({"source_kind": kind, "materialization_id": entry["materialization_id"],
                "status": manifest["source_state"], "manifest_ref": entry["manifest_ref"], "manifest_sha256": entry["manifest_sha256"]})
        except (OSError, ValueError, KeyError, TypeError) as exc:
            result["issues"].append({"code": "MATERIALIZED_SOURCE_UNAVAILABLE", "message": str(exc), "source_kind": kind or "map", "blocking": False})
            result["source_states"].append({"source_kind": kind or "map", "materialization_id": entry.get("materialization_id"), "status": "stale_or_unavailable", "reason": str(exc)})
    return result


def inspect_map_materialization(project_root: Path, materialization_id: str) -> dict[str, Any]:
    """Return an exact, still-current immutable bundle for a review UI."""
    root = Path(project_root).resolve()
    project = _project(root)
    catalog = read_materialization_catalog(root, project["project_id"])
    descriptor = next((item for kind in ("overpass", "rudy_trace", "mapsforge_vector") for item in catalog[kind]
                       if item.get("materialization_id") == materialization_id), None)
    if descriptor is None:
        raise ValueError("the requested materialization is missing or no longer current")
    reader = _Reader(root)
    manifest = reader.read(descriptor["manifest_ref"], descriptor["manifest_sha256"])
    result = {"manifest_ref": descriptor["manifest_ref"], "manifest_sha256": descriptor["manifest_sha256"],
              "manifest": manifest, "project_id": project["project_id"], **BOUNDARY}
    if manifest["kind"] == "rudy_trace":
        result["trace"] = reader.read(descriptor["ref"], descriptor["sha256"])
    if manifest["kind"] == "mapsforge_vector":
        result["vector"] = reader.read(descriptor["ref"], descriptor["sha256"])
    return result
