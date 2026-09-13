"""Optional, source-bound Mapsforge vector extraction for Planned GPX.

The configured official reader supplies drawing geometry, not OSM connectivity.
No network, shell command string, human approval, or runtime route authority.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scout_planned_map_materialization import SCHEMA, _bbox, _existing_bbox, _project, _publish, _safe, _sha
from scout_planned_route_sources import BOUNDARY, _Reader, _json_bytes, _parts

READER_VERSION = "0.25.0"
READER_MODULES = ("mapsforge-core", "mapsforge-map", "mapsforge-map-reader")


def extract_mapsforge(source: Path, box: dict[str, float]) -> tuple[dict[str, Any], dict[str, str]]:
    """Use an operator-configured local JDK and pinned jars, never HTTP inputs."""
    java = os.environ.get("SCOUT_MAPSFORGE_JAVA") or shutil.which("java")
    directory = os.environ.get("SCOUT_MAPSFORGE_READER_DIR")
    if not java or not Path(java).is_file() or not directory:
        raise ValueError("Mapsforge needs the optional local Java reader configuration")
    jars = [Path(directory).resolve() / f"{name}-{READER_VERSION}.jar" for name in READER_MODULES]
    if any(not p.is_file() for p in jars):
        raise ValueError("Mapsforge reader jars are missing")
    adapter = Path(__file__).parent / "tools/mapsforge/ScoutMapsforgeExtract.java"
    hashes = {p.name: _sha(p.read_bytes()) for p in [*jars, adapter]}
    command = [str(java), "-cp", os.pathsep.join(map(str, jars)), str(adapter), str(source),
               *(str(box[key]) for key in ("south", "west", "north", "east"))]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        raise ValueError(f"Mapsforge reader failed ({result.returncode}): {result.stderr[-1500:]}")
    try:
        payload = json.loads(result.stdout)
    except ValueError as exc:
        raise ValueError("Mapsforge reader returned invalid JSON") from exc
    return payload, hashes


def materialize_mapsforge_sources(project_root: Path, request: dict[str, Any]) -> dict[str, Any]:
    root = Path(project_root).resolve()
    project = _project(root)
    ref = request.get("source_ref") or project.get("rudy_mapsforge_ref")
    if not ref:
        raise ValueError("No Mapsforge source is registered")
    path = _safe(root, ref)
    with path.open("rb") as stream:
        if stream.read(20) != b"mapsforge binary OSM":
            raise ValueError("Source is not a Mapsforge map")
    source_sha = _Reader(root).bind(ref, request.get("expected_source_sha256"))
    box = _bbox(request["bbox_wgs84"]) if request.get("bbox_wgs84") else _existing_bbox(root, project)
    payload, producer_hashes = extract_mapsforge(path, box)
    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection" or not isinstance(payload.get("features"), list):
        raise ValueError("Mapsforge reader returned no vector collection")
    props = payload.get("properties", {})
    if (props.get("extractor") != "mapsforge-map-reader" or props.get("reader_version") != READER_VERSION
            or props.get("source_file_size") != path.stat().st_size or props.get("projection") != "Mercator"
            or props.get("topology_available") is not False or props.get("query_bbox_wgs84") != box):
        raise ValueError("Mapsforge reader source/area contract mismatch")
    _Reader(root).bind(ref, source_sha)
    features = []
    for feature in payload["features"]:
        parts = _parts(feature["geometry"])
        properties = feature.get("properties", {})
        if properties.get("topology_available") is not False:
            raise ValueError("Mapsforge drawing geometry cannot assert OSM topology")
        tags = properties.get("tags")
        if not isinstance(tags, dict) or not (tags.get("highway") or tags.get("gpx") == "trk"):
            raise ValueError("Mapsforge route feature has no supported source tags")
        if any(point.get("ele") is not None for part in parts for point in part):
            raise ValueError("Mapsforge path geometry must not invent measured elevation")
        fid = _sha(_json_bytes({"geometry": feature["geometry"], "properties": properties}))
        features.append({**feature, "id": fid, "properties": {**properties, **BOUNDARY}})
    # Exact reader records only; never join endpoints or crossings by proximity.
    unique = {feature["id"]: feature for feature in features}
    vector = {**payload, "features": list(unique.values()), "properties": {
        **props, "source_kind": "mapsforge_vector", "source_ref": ref, "source_sha256": source_sha,
        "source_url": project.get("rudy_mapsforge_source_url"), "field_verified": False, **BOUNDARY}}
    at = request.get("requested_at") or datetime.now(timezone.utc).isoformat()
    if isinstance(at, datetime):
        at = at.isoformat()
    identity = {"schema_version": SCHEMA, "project_id": project["project_id"], "source_kind": "mapsforge_vector",
        "source_ref": ref, "source_sha256": source_sha, "bbox_wgs84": box, "producer_hashes": {
            **producer_hashes, Path(__file__).name: _sha(Path(__file__).read_bytes())},
        "vector_sha256": _sha(_json_bytes(vector)), "requested_by": request.get("requested_by", "explicit_operator"),
        "requested_at": at}
    bundle_id = _sha(_json_bytes(identity))
    vector_ref = f"outputs/planned_map_sources/bundles/{bundle_id}/mapsforge.geojson"
    raw = _json_bytes(vector)
    return _publish(root, project["project_id"], bundle_id, {vector_ref: raw}, {
        "kind": "mapsforge_vector", "request": identity, "input_source_hashes": {ref: source_sha},
        "source_state": "vectors_ready_topology_missing" if unique else "empty",
        "project_binding": {"ref": vector_ref, "sha256": _sha(raw), "input_source_hashes": {ref: source_sha},
                            "materialization_id": bundle_id},
        "source_counts": {"route_candidates": len(unique), "vertices": sum(sum(map(len, f["geometry"]["coordinates"]))
                          if f["geometry"]["type"] == "MultiLineString" else len(f["geometry"]["coordinates"])
                          for f in unique.values()), "ways_with_node_ids": 0}})
