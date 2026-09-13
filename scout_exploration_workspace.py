"""AOI-first exploration workspaces, with no invented reference or Golden GPX.

Creation only persists typed human intent. Explicit preparation acquires public
map evidence and crops declared raw DEM at native resolution. That area evidence
is separate from route terrain assessment; an actual candidate must be selected
before Planned route analysis. All writes belong to the new workspace.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import math
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from scout_exploration_models import (
    ExplorationAOI, ExplorationLimits, ExplorationPoint, ExplorationWaypoint,
    ExplorationWorkspaceRequest,
)

BOUNDARY = {"authority": "candidate_only", "candidate_only": True,
            "runtime_safety_truth": False, "operational": False,
            "promotion_allowed": False, "recorded_track": False,
            "safe_or_walkable": "not_determined"}
INTAKE_REF = "inputs/exploration_intake.json"
SOURCE_REF = "inbox/source_manifest.json"
STORE_REF = "outputs/exploration"


class ExplorationWorkspaceError(ValueError):
    pass


def _bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def _sha(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _digest(value: Any) -> str:
    return hashlib.sha256(_bytes(value)).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path(root: Path, ref: str) -> Path:
    relative = Path(ref)
    if relative.is_absolute() or ".." in relative.parts or not ref:
        raise ExplorationWorkspaceError("Artifact must be a workspace-relative path")
    path = root / relative
    for item in (path, *path.parents):
        if item.is_symlink():
            raise ExplorationWorkspaceError("Workspace artifacts must not follow symlinks")
        if item == root:
            break
    if not path.resolve().is_relative_to(root):
        raise ExplorationWorkspaceError("Artifact escaped the exploration workspace")
    return path


def _write(root: Path, ref: str, value: Any, *, immutable: bool = True) -> str:
    path = _path(root, ref)
    data = value if isinstance(value, bytes) else _bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and immutable:
        if path.read_bytes() != data:
            raise ExplorationWorkspaceError(f"Immutable exploration artifact changed: {ref}")
    else:
        temporary = _path(root, ref + f".pending.{os.getpid()}")
        with temporary.open("wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    return hashlib.sha256(data).hexdigest()


def _read(root: Path, ref: str) -> dict:
    value = json.loads(_path(root, ref).read_bytes())
    if not isinstance(value, dict):
        raise ExplorationWorkspaceError("Expected an exploration metadata object")
    return value


@contextlib.contextmanager
def _lease(path: Path):
    if path.is_symlink():
        raise ExplorationWorkspaceError("Exploration lock must not be a symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ExplorationWorkspaceError("Exploration preparation is already running") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _unknowns(request: ExplorationWorkspaceRequest) -> list[dict]:
    rows = []
    for key, value in (("start", request.start), ("destination", request.destination)):
        if value is None:
            rows.append({"code": f"{key}_unknown", "message": "Area research is available; concrete TRH needs explicit A/B."})
    for waypoint in request.waypoints:
        if waypoint.point is None:
            rows.append({"code": "waypoint_unlocated", "label": waypoint.label,
                         "message": "The place name needs a source-bound location before route composition."})
        if waypoint.purpose == "camp_candidate":
            rows.append({"code": "camp_conditions_unreviewed", "label": waypoint.label,
                         "missing": ["water", "capacity", "legal_access", "overnight_conditions"]})
    if request.limits.fixed_speed_kmh is None and request.limits.speed_range_kmh is None:
        rows.append({"code": "pace_assumption_missing", "message": "Terrain model cost is not walking duration."})
    if request.limits.days is None:
        rows.append({"code": "trip_days_unknown", "message": "Trip duration has not been specified."})
    return rows


def create_exploration_workspace(workspace_root: Path, request: ExplorationWorkspaceRequest | dict) -> dict:
    """Create a new workspace plus a durable queued request, without network I/O."""
    request = ExplorationWorkspaceRequest.model_validate(request)
    base = Path(workspace_root).expanduser()
    if base.is_symlink():
        raise ExplorationWorkspaceError("Exploration workspace root must not be a symlink")
    base = base.resolve()
    base.mkdir(parents=True, exist_ok=True)
    root = _path(base, request.project_id)
    intake = request.model_dump(mode="json")
    intake_sha = _digest(intake)
    preparation_id = "explore." + intake_sha[:24]
    prefix = f"{STORE_REF}/preparation/{preparation_id}"
    with _lease(base / f".exploration-create.{request.project_id}.lock"):
        if root.exists():
            if not (root / INTAKE_REF).is_file() or _read(root, INTAKE_REF) != intake:
                raise ExplorationWorkspaceError("Project ID already belongs to a different workspace or intake")
            return read_exploration_workspace(root)
        root.mkdir()
        _write(root, INTAKE_REF, intake)
        aoi_ref = "inputs/exploration_aoi.geojson"
        _write(root, aoi_ref, {"type": "FeatureCollection", "features": [{"type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [request.aoi.ring("EPSG:4326")]},
            "properties": {"analysis_scope": "aoi", "source_crs": request.aoi.crs,
                           "intake_sha256": intake_sha, **BOUNDARY}}]})
        sources = {"schema_version": "scout_exploration_sources.v1", "project_id": request.project_id,
                   "intake_ref": INTAKE_REF, "intake_sha256": intake_sha,
                   "primary_gpx": None, "golden_gpx": None, "reference_gpxs": [],
                   "preparation_inputs": intake["preparation_inputs"], **BOUNDARY}
        source_sha = _write(root, SOURCE_REF, sources)
        job = {"schema_version": "scout_exploration_preparation_request.v1", "project_id": request.project_id,
               "preparation_id": preparation_id, "intake_ref": INTAKE_REF, "intake_sha256": intake_sha,
               "source_manifest_ref": SOURCE_REF, "source_manifest_sha256": source_sha,
               "aoi_ref": aoi_ref, "aoi_sha256": _sha(root / aoi_ref),
               "requested_at": _now(), "requested_by": request.requested_by,
               "stages": ["map_acquisition", "native_aoi_dem"],
               "route_terrain_feature_stack": "requires_selected_candidate_geometry",
               "route_input_required": False, "primary_gpx": None, "golden_gpx": None, "reference_gpxs": [], **BOUNDARY}
        request_ref = f"{prefix}/request.json"
        request_sha = _write(root, request_ref, job)
        state_ref = f"{prefix}/state.json"
        _write(root, state_ref, {"schema_version": "scout_exploration_preparation_state.v1",
            "project_id": request.project_id, "preparation_id": preparation_id, "status": "queued", "attempt": 0,
            "request_ref": request_ref, "request_sha256": request_sha, "updated_at": _now(), **BOUNDARY})
        _write(root, "project.json", {"schema_version": "pretrip_project.v1", "project_id": request.project_id,
            "route_name": request.intent, "workspace_kind": "exploration", "analysis_scope": "aoi",
            "golden_source_id": None, "primary_gpx": None, "golden_gpx": None, "reference_gpxs": [],
            "exploration_intake_ref": INTAKE_REF, "exploration_intake_sha256": intake_sha,
            "exploration_aoi_ref": aoi_ref, "exploration_preparation_request_ref": request_ref,
            "exploration_preparation_state_ref": state_ref, "exploration_preparation_id": preparation_id,
            "exploration_unknowns": _unknowns(request), "planned_overpass_source_refs": [], **BOUNDARY})
    return read_exploration_workspace(root)


def _identity(root: Path) -> tuple[dict, ExplorationWorkspaceRequest, dict]:
    project = _read(root, "project.json")
    if (project.get("workspace_kind") != "exploration" or project.get("project_id") != root.name
            or any(project.get(key) != value for key, value in BOUNDARY.items())):
        raise ExplorationWorkspaceError("Workspace is not the requested exploration project")
    request = ExplorationWorkspaceRequest.model_validate(_read(root, INTAKE_REF))
    job = _read(root, project["exploration_preparation_request_ref"])
    if (request.project_id != root.name or job.get("project_id") != root.name
            or _sha(root / INTAKE_REF) != job.get("intake_sha256")
            or _sha(root / SOURCE_REF) != job.get("source_manifest_sha256")
            or _sha(_path(root, job["aoi_ref"])) != job.get("aoi_sha256")):
        raise ExplorationWorkspaceError("Exploration input provenance changed")
    if any(project.get(key) is not None for key in ("primary_gpx", "golden_gpx", "golden_source_id")) or project.get("reference_gpxs") != []:
        raise ExplorationWorkspaceError("Exploration intake cannot acquire an implicit Golden or Ref GPX")
    return project, request, job


def read_exploration_workspace(project_root: Path) -> dict:
    root = Path(project_root).resolve()
    project, request, job = _identity(root)
    state = _read(root, project["exploration_preparation_state_ref"])
    if state.get("request_sha256") != _sha(_path(root, project["exploration_preparation_request_ref"])):
        raise ExplorationWorkspaceError("Exploration preparation request changed")
    return {"schema_version": "scout_exploration_workspace.v1", "project_id": root.name,
            "project_root": str(root), "intake": request.model_dump(mode="json"),
            "preparation_id": job["preparation_id"], "preparation": state,
            "unknowns": _unknowns(request), "golden_source_id": None, "reference_gpxs": [],
            "aoi_ref": job["aoi_ref"], "candidate_catalog_available": True, **BOUNDARY}


def _raw_dem_sources(request: ExplorationWorkspaceRequest) -> dict:
    """Select original DTM tiles intersecting the AOI using the existing parser."""
    from dashboard_workspace_preparation import _reject_derived_workspace_source
    from pretrip_import import validate_dtm_raster_source
    from pretrip_source_ingest import parse_dtm_header
    ring = request.aoi.ring("EPSG:3826")
    bounds = {"min_x": min(p[0] for p in ring), "max_x": max(p[0] for p in ring),
              "min_y": min(p[1] for p in ring), "max_y": max(p[1] for p in ring), "crs": "EPSG:3826"}
    bindings, tiles, rasters = [], [], []
    for source in request.preparation_inputs.dtm_rasters:
        _reject_derived_workspace_source(Path(source.path), field="exploration_raw_dem")
        validated = validate_dtm_raster_source(source).model_dump(mode="json")
        rasters.append(validated)
        bindings.append({"path": validated["path"], "sha256": validated["sha256"], "role": "raw_dem"})
        if validated.get("crs_evidence_sha256"):
            bindings.append({"path": validated["crs_evidence"], "sha256": validated["crs_evidence_sha256"], "role": "raw_dem_crs_evidence"})
    scanned = 0
    missing = []
    for value in request.preparation_inputs.dtm_dirs:
        directory = Path(value).expanduser().resolve()
        _reject_derived_workspace_source(directory, field="exploration_raw_dem_dir")
        if not directory.is_dir():
            raise ExplorationWorkspaceError(f"Declared raw DTM directory is unavailable: {directory}")
        for header in sorted(directory.glob("*dem.hdr")):
            scanned += 1
            if header.is_symlink():
                raise ExplorationWorkspaceError("Raw DEM header may not be a symlink")
            tile = parse_dtm_header(header).model_dump(mode="json")
            bbox = tile["bbox_twd97"]
            if bbox["min_x"] > bounds["max_x"] or bbox["max_x"] < bounds["min_x"] or bbox["min_y"] > bounds["max_y"] or bbox["max_y"] < bounds["min_y"]:
                continue
            tile.update(analysis_scope="aoi", coverage_note="Intersects exploration AOI; no route supplied")
            if "TWD97" not in tile["horizontal_datum"].upper():
                raise ExplorationWorkspaceError("Raw DTM tile has no TWD97 CRS evidence")
            if tile["grid_uri"] is None:
                missing.append(tile["tile_id"])
                continue
            for key, role in (("header_uri", "raw_dem_tile_header"), ("grid_uri", "raw_dem_tile")):
                path = Path(tile[key])
                if not path.is_relative_to(directory) or path.is_symlink():
                    raise ExplorationWorkspaceError("Raw DTM tile escaped its declared source directory")
                sha = _sha(path)
                tile["header_sha256" if key == "header_uri" else "grid_sha256"] = sha
                bindings.append({"path": str(path), "sha256": sha, "role": role})
            tiles.append(tile)
    return {"schema_version": "scout_exploration_dem_sources.v1", "analysis_scope": "aoi",
            "bbox_wgs84": request.aoi.bbox_wgs84(), "aoi_bbox_twd97": bounds,
            "aoi_polygon_twd97": ring, "raster_sources": rasters, "candidate_tiles": tiles,
            "scanned_header_count": scanned, "missing_tile_ids": missing,
            "source_dirs": request.preparation_inputs.dtm_dirs,
            "external_source_bindings": bindings, "derived_dem_reused": False, **BOUNDARY}


def prepare_native_aoi_dem(project_root: Path, request: ExplorationWorkspaceRequest,
                           output_ref: str, raw: dict) -> dict:
    """Run native GDAL on raw evidence; preserve resolution and AOI nodata.

    The parent is a DEM preparation manifest, never a claim that QGIS/GRASS
    terrain features or any candidate path have been computed.
    """
    from osgeo import gdal, ogr, osr
    import numpy as np

    root = Path(project_root).resolve()
    output = _path(root, output_ref)
    output.mkdir(parents=True, exist_ok=True)
    sources = [*[(row["path"], row["source_resolution_m"], row["crs"], False) for row in raw["raster_sources"]],
               *[(row["grid_uri"], row["resolution_x_m"], "EPSG:3826", True) for row in raw["candidate_tiles"]]]
    if not sources:
        raise ExplorationWorkspaceError("No declared raw DEM covers this AOI")
    if any(not math.isclose(row["resolution_x_m"], row["resolution_y_m"]) for row in raw["candidate_tiles"]):
        raise ExplorationWorkspaceError("AOI preparation requires a square native DEM grid")
    resolutions = {round(float(row[1]), 9) for row in sources}
    if len(resolutions) != 1:
        raise ExplorationWorkspaceError("AOI sources have mixed native resolutions; explicit source choice is required")
    resolution = resolutions.pop()
    datasets = []
    for path, _, declared_crs, header_bound in sources:
        if declared_crs.upper() not in {"3826", "EPSG:3826"}:
            raise ExplorationWorkspaceError("AOI DEM source CRS must be explicitly EPSG:3826")
        dataset = gdal.Open(path, gdal.GA_ReadOnly)
        if dataset is None:
            raise ExplorationWorkspaceError("Raw DEM is unreadable by GDAL")
        crs = dataset.GetSpatialRef()
        if crs is None and not header_bound:
            raise ExplorationWorkspaceError("Raw GeoTIFF has no native CRS metadata")
        if crs is not None and crs.GetAuthorityCode(None) != "3826":
            raise ExplorationWorkspaceError("Raw raster CRS disagrees with the declared TWD97 CRS")
        transform = dataset.GetGeoTransform()
        if transform[2] or transform[4] or not all(math.isclose(abs(transform[i]), resolution, rel_tol=1e-8) for i in (1, 5)):
            raise ExplorationWorkspaceError("Raw raster resolution disagrees with its source declaration")
        datasets.append(dataset)
    bounds = raw["aoi_bbox_twd97"]
    # Expand at most one native cell per edge, then retain an explicit AOI mask.
    extent = [math.floor(bounds["min_x"] / resolution) * resolution,
              math.floor(bounds["min_y"] / resolution) * resolution,
              math.ceil(bounds["max_x"] / resolution) * resolution,
              math.ceil(bounds["max_y"] / resolution) * resolution]
    path = output / "dem_route_bbox.tif"
    if path.exists():
        raise ExplorationWorkspaceError("An AOI DEM attempt cannot overwrite an earlier artifact")
    dataset = gdal.Warp(str(path), datasets, format="GTiff", srcSRS="EPSG:3826", dstSRS="EPSG:3826",
        outputBounds=extent, xRes=resolution, yRes=resolution, resampleAlg="near", dstNodata=-9999,
        creationOptions=["COMPRESS=DEFLATE", "TILED=YES"], multithread=False)
    if dataset is None:
        raise ExplorationWorkspaceError("Native GDAL AOI crop failed")
    mask = gdal.GetDriverByName("MEM").Create("", dataset.RasterXSize, dataset.RasterYSize, 1, gdal.GDT_Byte)
    mask.SetGeoTransform(dataset.GetGeoTransform())
    mask.SetProjection(dataset.GetProjection())
    vector = ogr.GetDriverByName("Memory").CreateDataSource("")
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(3826)
    layer = vector.CreateLayer("aoi", srs=srs, geom_type=ogr.wkbPolygon)
    geometry = ogr.CreateGeometryFromJson(json.dumps({"type": "Polygon", "coordinates": [raw["aoi_polygon_twd97"]]}))
    feature = ogr.Feature(layer.GetLayerDefn())
    feature.SetGeometry(geometry)
    layer.CreateFeature(feature)
    if gdal.RasterizeLayer(mask, [1], layer, burn_values=[1]) != 0:
        raise ExplorationWorkspaceError("AOI mask could not be rasterized")
    inside = mask.ReadAsArray().astype(bool)
    values = dataset.GetRasterBand(1).ReadAsArray()
    values[~inside] = -9999
    dataset.GetRasterBand(1).WriteArray(values)
    dataset.FlushCache()
    finite = np.isfinite(values) & (values != -9999) & inside
    finite_count, area_count = int(finite.sum()), int(inside.sum())
    rows, columns = dataset.RasterYSize, dataset.RasterXSize
    dataset = None
    datasets.clear()
    if not area_count:
        raise ExplorationWorkspaceError("AOI is smaller than a resolvable native DEM cell")
    dem_sha = _sha(path)
    source_hashes = {entry["path"]: entry["sha256"] for entry in raw["external_source_bindings"]}
    for ref, sha in source_hashes.items():
        if _sha(Path(ref)) != sha:
            raise ExplorationWorkspaceError("Raw DEM source changed during AOI preparation")
    manifest = {"schema_version": "scout_exploration_dem_parent.v1", "project_id": root.name,
        "actual_processor": "native_gdal_aoi_dem", "gdal_version": gdal.VersionInfo("RELEASE_NAME"),
        "analysis_scope": "aoi", "input_kind": "area_polygon", "route_input": None,
        "intake_sha256": _sha(root / INTAKE_REF), "fixture": False, "synthetic": False,
        "terrain_feature_stack_status": "not_run_no_selected_route", "geometry_generated": False,
        "parameters": {"analysis_extent": {"resolution_m": resolution, "bounds": extent,
            "aoi_polygon": raw["aoi_polygon_twd97"], "crs": "EPSG:3826", "mask_semantics": "native_cell_center_in_aoi"}},
        "source_resolution": {"status": "reported", "source_kind": "original_raw_aoi_dem",
            "x_m": resolution, "y_m": resolution, "crs": "EPSG:3826", "adds_source_resolution": False,
            "crs_evidence": "verified_native_raster_or_bound_TWD97_header"},
        "source_hashes": source_hashes, "artifacts": {"dem_route_bbox": path.name},
        "artifact_hashes": {path.name: dem_sha}, "rows": rows, "columns": columns,
        "aoi_cell_count": area_count, "finite_cell_count": finite_count,
        "nodata_cell_count": area_count - finite_count, "resampling": "nearest_native_resolution", **BOUNDARY}
    parent_ref = f"{output_ref}/terrain_feature_manifest.json"
    parent_sha = _write(root, parent_ref, manifest)
    return {"status": "completed" if finite_count == area_count else "partial", "actual_processor": "native_gdal_aoi_dem",
        "dem_ref": f"{output_ref}/{path.name}", "dem_sha256": dem_sha,
        "parent_manifest_ref": parent_ref, "parent_manifest_sha256": parent_sha,
        "resolution_m": resolution, "crs": "EPSG:3826", "finite_cell_count": finite_count,
        "nodata_cell_count": area_count - finite_count, "aoi_cell_count": area_count,
        "source_hashes": {**source_hashes, parent_ref: parent_sha, f"{output_ref}/{path.name}": dem_sha},
        "terrain_feature_stack_status": "not_run_no_selected_route", **BOUNDARY}


def _verify_hashes(root: Path, hashes: dict[str, str]) -> None:
    for ref, expected in hashes.items():
        path = Path(ref) if Path(ref).is_absolute() else _path(root, ref)
        if not path.is_file() or _sha(path) != expected:
            raise ExplorationWorkspaceError(f"Prepared exploration evidence changed: {ref}")


def prepare_exploration_workspace(project_root: Path, preparation_id: str | None = None, *,
        fetch_map: bool = True, map_fetcher: Callable[[dict], dict] | None = None,
        dem_preparer: Callable[[Path, ExplorationWorkspaceRequest, str, dict], dict] | None = None,
        progress: Callable[[dict], None] | None = None, force: bool = False) -> dict:
    """Run or explicitly resume an AOI job; GETs use read_exploration_workspace.

    A single filesystem lease owns writes. Completed immutable attempts remain
    available; a failed or interrupted attempt is retried in a fresh directory.
    No QGIS request is submitted here, and no runtime route is activated.
    """
    from scout_planned_route_sources import fetch_trail_source_candidates, load_map_route_sources

    root = Path(project_root).resolve()
    project, request, job = _identity(root)
    if preparation_id is not None and preparation_id != job["preparation_id"]:
        raise ExplorationWorkspaceError("Preparation belongs to another exploration intake")
    prefix = f"{STORE_REF}/preparation/{job['preparation_id']}"
    state_ref = project["exploration_preparation_state_ref"]
    with _lease(_path(root, f"{prefix}/preparation.lock")):
        state = _read(root, state_ref)
        if state.get("report_ref") and state.get("status") in {"completed", "completed_with_gaps"} and not force:
            report = _read(root, state["report_ref"])
            _verify_hashes(root, {**report["source_hashes"], state["report_ref"]: state["report_sha256"]})
            return report
        attempt = int(state.get("attempt", 0)) + 1
        attempt_ref = f"{prefix}/attempts/{attempt:04d}"
        state.update(attempt=attempt, status="running", stage="map", started_at=_now(), updated_at=_now())
        _write(root, state_ref, state, immutable=False)
        source_hashes = {INTAKE_REF: job["intake_sha256"], SOURCE_REF: job["source_manifest_sha256"],
                         job["aoi_ref"]: job["aoi_sha256"]}
        unknowns = _unknowns(request)

        def notify(stage, status, **details):
            state.update(stage=stage, stage_status=status, updated_at=_now(), **details)
            _write(root, state_ref, state, immutable=False)
            if progress:
                progress({"preparation_id": job["preparation_id"], "attempt": attempt,
                          "stage": stage, "status": status, **details})

        maps = {"status": "not_requested", "source_count": 0, "source_hashes": {}}
        if fetch_map:
            notify("map", "running")
            try:
                bundle = (map_fetcher or fetch_trail_source_candidates)(request.aoi.bbox_wgs84())
                if bundle.get("candidate_only") is not True or bundle.get("runtime_safety_truth") is not False:
                    raise ExplorationWorkspaceError("Map acquisition violated the candidate evidence boundary")
                for ref, raw in bundle["files"].items():
                    if hashlib.sha256(raw).hexdigest() != bundle["source_hashes"].get(ref):
                        raise ExplorationWorkspaceError("Map bundle bytes do not match their source hash")
                    _write(root, ref, raw)
                project = _read(root, "project.json")
                bindings = list(project.get("planned_overpass_source_refs") or [])
                if bundle["project_binding"] not in bindings:
                    bindings.append(bundle["project_binding"])
                project["planned_overpass_source_refs"] = bindings
                _write(root, "project.json", project, immutable=False)
                catalog = load_map_route_sources(root, project)
                refs = set(bundle["source_hashes"])
                acquired = [source for source in catalog["sources"] if source["ref"] in refs]
                maps = {"status": "completed" if acquired else "no_trail_candidates", "source_count": len(acquired),
                        "project_binding": bundle["project_binding"], "query": bundle.get("query"),
                        "bbox_wgs84": request.aoi.bbox_wgs84(), "evidence_scope": "area_acquisition",
                        "route_alignment": "not_applicable_without_selected_candidate",
                        "source_hashes": bundle["source_hashes"], "issues": catalog.get("issues", []), **BOUNDARY}
                source_hashes.update(bundle["source_hashes"])
                if not acquired:
                    unknowns.append({"code": "map_trail_candidates_missing", "message": "The acquired area evidence contains no usable trail geometry."})
            except (OSError, ValueError, KeyError, TypeError) as exc:
                maps = {"status": "unavailable", "source_count": 0, "error_type": type(exc).__name__, "message": str(exc), **BOUNDARY}
                unknowns.append({"code": "map_acquisition_unavailable", "message": str(exc)})
            notify("map", maps["status"])
        else:
            unknowns.append({"code": "map_acquisition_not_requested", "message": "No connected map acquisition was requested for this attempt."})
        map_ref = f"{attempt_ref}/map_evidence.json"
        source_hashes[map_ref] = _write(root, map_ref, maps)
        notify("dem", "running")
        try:
            raw = _raw_dem_sources(request)
            raw_ref = f"{attempt_ref}/raw_dem_sources.json"
            source_hashes[raw_ref] = _write(root, raw_ref, raw)
            source_hashes.update({entry["path"]: entry["sha256"] for entry in raw["external_source_bindings"]})
            terrain = (dem_preparer or prepare_native_aoi_dem)(root, request, f"{attempt_ref}/dem", raw)
            if (terrain.get("candidate_only") is not True or terrain.get("runtime_safety_truth") is not False
                    or terrain.get("actual_processor") != "native_gdal_aoi_dem"):
                raise ExplorationWorkspaceError("AOI DEM producer result has unsupported provenance")
            _verify_hashes(root, terrain["source_hashes"])
            source_hashes.update(terrain["source_hashes"])
            parent = _read(root, terrain["parent_manifest_ref"])
            if parent.get("intake_sha256") != job["intake_sha256"] or parent.get("project_id") != root.name:
                raise ExplorationWorkspaceError("AOI DEM parent belongs to another intake")
            project = _read(root, "project.json")
            project.update(terrain_feature_manifest_ref=terrain["parent_manifest_ref"],
                terrain_dem_route_bbox_raster_ref=terrain["dem_ref"],
                exploration_dem_status=terrain["status"], terrain_analysis_scope="aoi",
                terrain_feature_stack_status="not_run_no_selected_route",
                terrain_route_hypothesis_candidate_only=True, terrain_route_hypothesis_runtime_safety_truth=False)
            _write(root, "project.json", project, immutable=False)
            if terrain["status"] != "completed":
                unknowns.append({"code": "aoi_dem_partial_coverage", "nodata_cell_count": terrain.get("nodata_cell_count")})
        except (OSError, ValueError, KeyError, TypeError, ImportError, RuntimeError) as exc:
            terrain = {"status": "unavailable", "error_type": type(exc).__name__, "message": str(exc), **BOUNDARY}
            unknowns.append({"code": "aoi_dem_unavailable", "message": str(exc)})
        notify("dem", terrain["status"])
        _identity(root)
        _verify_hashes(root, source_hashes)
        report = {"schema_version": "scout_exploration_preparation_report.v1", "project_id": root.name,
            "preparation_id": job["preparation_id"], "attempt": attempt,
            "status": "completed_with_gaps" if unknowns else "completed", "completed_at": _now(),
            "intake_ref": INTAKE_REF, "intake_sha256": job["intake_sha256"],
            "map": maps, "terrain": terrain, "unknowns": unknowns, "source_hashes": source_hashes,
            "golden_source_id": None, "primary_gpx": None, "reference_gpxs": [],
            "route_terrain_feature_stack": "requires_selected_candidate_geometry",
            "trh_request_available": (request.start is not None and request.destination is not None
                and all(waypoint.point is not None for waypoint in request.waypoints) and terrain["status"] == "completed"),
            "area_research_preserved": True, **BOUNDARY}
        report_ref = f"{attempt_ref}/report.json"
        report_sha = _write(root, report_ref, report)
        state.update(status=report["status"], stage="completed", stage_status=report["status"],
                     completed_at=report["completed_at"], updated_at=_now(), report_ref=report_ref, report_sha256=report_sha)
        _write(root, state_ref, state, immutable=False)
        return report


def load_exploration_catalog(project_root: Path) -> dict:
    """Return map/TRH segments in the shared Planned catalog, with a null Golden."""
    from scout_planned_route import digest
    from scout_planned_route_sources import load_map_route_sources
    root = Path(project_root).resolve()
    project, request, job = _identity(root)
    sources = load_map_route_sources(root, project)
    hashes = {**sources["source_hashes"], INTAKE_REF: job["intake_sha256"],
              SOURCE_REF: job["source_manifest_sha256"], job["aoi_ref"]: job["aoi_sha256"]}
    anchors = list(sources["anchors"])
    targets = [((request.start.label or "A"), request.start)] if request.start else []
    if request.destination:
        targets.append((request.destination.label or "B", request.destination))
    targets.extend((waypoint.label, waypoint.point) for waypoint in request.waypoints if waypoint.point is not None)
    for label, point in targets:
        lon, lat = point.wgs84()
        from scout_planned_route_sources import _distance
        matches = []
        for source in sources["sources"]:
            for part_index, part in enumerate(source["parts"]):
                for index, point in enumerate(part):
                    offset = _distance(point, {"lat": lat, "lon": lon})
                    if offset <= 30:
                        matches.append((offset, source["source_id"], part_index, index, point))
        if matches:
            closest = min(row[0] for row in matches)
            # Repeated visits and distinct source identities remain separately resolvable.
            for offset, source_id, part_index, index, point in matches:
                if offset > closest + 0.05:
                    continue
                anchors.append({"anchor_id": f"{source_id}.p{part_index}.{index}", "source_id": source_id,
                    "part_index": part_index, "point_index": index, "label": label,
                    "lat": point["lat"], "lon": point["lon"], "aliases": [],
                    "location_source": "explicit_exploration_waypoint", "snap_distance_m": offset})
    merged = {}
    for anchor in anchors:
        previous = merged.get(anchor["anchor_id"])
        if previous:
            anchor["aliases"] = sorted(set(previous.get("aliases", []) + anchor.get("aliases", []) + [previous["label"]]))
        merged[anchor["anchor_id"]] = anchor
    return {"schema_version": "plannedRouteCatalog.v1", "project_id": root.name,
        "golden_source_id": None, "reference_gpxs": [], "workspace_kind": "exploration",
        "sources": sources["sources"], "anchors": list(merged.values()), "source_hashes": hashes,
        "source_snapshot_sha256": digest(hashes), "issues": sources["issues"],
        "source_states": sources.get("source_states", {}), "exploration_unknowns": _unknowns(request),
        "exploration_intake": request.model_dump(mode="json"), "analysis_scope": "aoi", **BOUNDARY}


# Explicitly named alias for callers building catalogs before a candidate exists.
build_exploration_catalog = load_exploration_catalog


def build_exploration_trh_requests(project_root: Path, *, corridor_m: float = 500,
                                   requested_by: str = "exploration_preparation") -> list:
    """Compile existing QGIS/GRASS requests for explicit A/via/B; never submit.

    An absent A/B or an unresolved intervening waypoint prevents concrete path
    generation while leaving the AOI evidence intact.
    """
    from tools.run_terrain_route_hypothesis_worker import build_worker_request
    root = Path(project_root).resolve()
    project, request, job = _identity(root)
    if request.start is None or request.destination is None:
        raise ExplorationWorkspaceError("Concrete terrain hypotheses require explicit A/B")
    if any(waypoint.point is None for waypoint in request.waypoints):
        raise ExplorationWorkspaceError("Locate or explicitly remove unresolved waypoints before path generation")
    if not math.isfinite(corridor_m) or corridor_m < 0:
        raise ExplorationWorkspaceError("TRH analysis margin must be finite and non-negative")
    state = _read(root, project["exploration_preparation_state_ref"])
    if not state.get("report_ref"):
        raise ExplorationWorkspaceError("Prepare actual AOI DEM evidence before terrain hypotheses")
    report = _read(root, state["report_ref"])
    _verify_hashes(root, {**report["source_hashes"], state["report_ref"]: state["report_sha256"]})
    terrain = report["terrain"]
    if terrain["status"] != "completed":
        raise ExplorationWorkspaceError("AOI DEM coverage is incomplete")
    points = [request.start, *(w.point for w in request.waypoints), request.destination]
    results = []
    for index, (start, destination) in enumerate(zip(points, points[1:])):
        if start.wgs84() == destination.wgs84():
            raise ExplorationWorkspaceError("Consecutive exploration targets must be distinct")
        results.append(build_worker_request(project_id=root.name,
            request_id=f"{job['preparation_id']}.a{state['attempt']}.leg{index}", requested_by=requested_by,
            dem_path=_path(root, terrain["dem_ref"]), parent_manifest_path=_path(root, terrain["parent_manifest_ref"]),
            dem_resolution_m=terrain["resolution_m"], start=start.wgs84(), destination=destination.wgs84(),
            corridor_m=corridor_m))
    return results


def export_exploration_candidates(project_root: Path, selections: list[dict], *,
        fixed_speed_kmh: float | None = None, assumptions: list[str] | None = None) -> dict:
    """Save explicitly selected source parts as separate candidate GPX segments.

    This preserves useful disconnected evidence before a complete Planned route
    can be assembled. The shared Planned compiler remains the full itinerary
    editor; no missing connection or terrain cost becomes elapsed time here.
    """
    from scout_planned_route import GPX_NS, PLAN_NS
    from scout_planned_route_sources import _distance
    root = Path(project_root).resolve()
    catalog = load_exploration_catalog(root)
    if not selections:
        raise ExplorationWorkspaceError("Select at least one actual source segment")
    if fixed_speed_kmh is not None and (not math.isfinite(fixed_speed_kmh) or not 0 < fixed_speed_kmh <= 20):
        raise ExplorationWorkspaceError("Explicit fixed speed must be between zero and 20 km/h")
    sources = {source["source_id"]: source for source in catalog["sources"]}
    parts, provenance, gaps = [], [], []
    for selection in selections:
        try:
            source = sources[selection["source_id"]]
            part_index = selection.get("part_index", 0)
            part = source["parts"][part_index]
            start, end = selection.get("start_index", 0), selection.get("end_index", len(part) - 1)
            if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in (part_index, start, end)) or start >= len(part) or end >= len(part) or start == end:
                raise ValueError("Invalid inclusive source range")
            indices = list(range(start, end + (1 if end > start else -1), 1 if end > start else -1))
            selected = [dict(part[index], time=None) for index in indices]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ExplorationWorkspaceError("Selection is not a complete bound source range") from exc
        if parts:
            offset = _distance(parts[-1][-1], selected[0])
            if offset > 0.05:
                gaps.append({"from_part": len(parts) - 1, "to_part": len(parts), "distance_m": offset,
                             "filled": False, "elapsed_minutes": None, "connection_status": "unresolved"})
        parts.append(selected)
        provenance.append({"source_id": source["source_id"], "source_ref": source["ref"],
            "source_sha256": source["sha256"], "part_index": part_index, "source_point_indices": indices,
            "direction": "forward" if end > start else "reverse", "provenance": source["provenance"]})
    distance_m = sum(_distance(a, b) for part in parts for a, b in zip(part, part[1:]))
    minutes = distance_m / (fixed_speed_kmh * 1000 / 60) if fixed_speed_kmh else None
    intent = {"selections": selections, "fixed_speed_kmh": fixed_speed_kmh, "assumptions": assumptions or []}
    version = "explore-export." + _digest({"catalog": catalog["source_snapshot_sha256"], "intent": intent,
        "semantics": "selected_source_parts_not_full_trip.v1"})[:24]
    prefix = f"{STORE_REF}/candidate_exports/{version}"
    tree = ET.Element("gpx", {"version": "1.1", "xmlns": GPX_NS, "creator": "Scout Exploration Candidate"})
    meta = ET.SubElement(tree, "metadata")
    ET.SubElement(meta, "type").text = "planned_candidate"
    ET.SubElement(ET.SubElement(meta, "extensions"), f"{{{PLAN_NS}}}provenance", role="planned", recorded_track="false", candidate_only="true")
    track = ET.SubElement(tree, "trk")
    for part in parts:
        segment = ET.SubElement(track, "trkseg")
        for point in part:
            node = ET.SubElement(segment, "trkpt", lat=str(point["lat"]), lon=str(point["lon"]))
            if point.get("ele") is not None:
                ET.SubElement(node, "ele").text = str(point["ele"])
    data = ET.tostring(tree, encoding="utf-8", xml_declaration=True)
    gpx_ref = f"{prefix}/candidates.gpx"
    gpx_sha = _write(root, gpx_ref, data)
    report = {"schema_version": "scout_exploration_candidate_export.v1", "project_id": root.name,
        "version_id": version, "golden_source_id": None, "reference_gpxs": [],
        "gpx_ref": gpx_ref, "gpx_sha256": gpx_sha, "segment_count": len(parts),
        "point_count": sum(len(part) for part in parts), "gaps": gaps, "source_provenance": provenance,
        "source_hashes": catalog["source_hashes"], "distance_m_of_known_segments": distance_m,
        "timing": {"semantics": "planned_estimate", "method": "explicit_fixed_speed" if fixed_speed_kmh else "unknown",
            "fixed_speed_kmh": fixed_speed_kmh, "known_segment_minutes": minutes,
            "connected_segment_moving_minutes": minutes if not gaps else None,
            "full_route_minutes": None, "assumptions": assumptions or [],
            "unknowns": (["unresolved_connection_duration"] if gaps else []) + ([] if fixed_speed_kmh else ["pace_not_specified"]),
            "model_cost_used_as_duration": False, "rest_and_camp_schedule": "not_defined"},
        "selected_geometry_connected": not gaps, "full_route_complete": False,
        "full_route_completion_status": "requires_explicit_planned_itinerary", **BOUNDARY}
    _write(root, f"{prefix}/manifest.json", report)
    _verify_hashes(root, catalog["source_hashes"])
    return report
