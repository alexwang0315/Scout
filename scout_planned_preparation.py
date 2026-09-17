"""Prepare source-backed map/terrain evidence for an immutable Planned graph.

Only the supplied run directory is writable.  The saved Planned graph remains
the analysis subject; workspaces below this run are disposable producer inputs,
not replacements for its checkpoints, route order, gaps, or timetable.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Callable
import xml.etree.ElementTree as ET

from scout_planned_route_artifacts import STORE_REF, _load_version, canonical_bytes
from scout_planned_route_sources import fetch_trail_source_candidates, load_map_route_sources


BOUNDARY = {"candidate_only": True, "runtime_safety_truth": False, "operational": False,
            "departure_approval_granted": False, "recorded_track": False}
CANONICAL_FILES = {"route_axis": "route_axis.json", "checkpoints": "checkpoints.json",
                   "segments": "segments.json", "itinerary": "itinerary.json",
                   "route_geojson": "route.geojson", "planned_gpx": "planned.gpx"}
SCHEMA = "scout_planned_preparation.v1"
RECORDED_CANONICAL_FILES = {**{key: value for key, value in CANONICAL_FILES.items() if key != "planned_gpx"},
                            "recorded_gpx": "recorded.gpx"}


def _is_recorded(binding: dict) -> bool:
    return binding.get("kind") == "recorded_gpx" or binding.get("subject_kind") == "recorded_gpx"


def _subject_boundary(binding: dict) -> dict:
    return {**BOUNDARY, **({"recorded_track": True, "post_analysis_only": True,
                           "subject_kind": "recorded_gpx", "source_times_role": binding.get("source_times_role")}
                          if _is_recorded(binding) else {})}


def _canonical_files(binding: dict) -> dict:
    return RECORDED_CANONICAL_FILES if _is_recorded(binding) else CANONICAL_FILES

MAX_WORKER_POINTS = 20_000
# Keep the unchanged coarse geomorphon search radius (20 cells) usable even
# when a Planned part occupies only a few metres in the native 20 m DEM.
TERRAIN_ANALYSIS_MARGIN_M = 500.0


class PlannedPreparationError(ValueError):
    """An invalid identity or output root cannot become preparation evidence."""


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _path(root: Path, ref: str) -> Path:
    relative = Path(ref)
    target = root / relative
    for component in (target, *target.parents):
        if component == root:
            break
        if component.is_symlink():
            raise PlannedPreparationError("Preparation artifacts may not follow symlinks")
    path = target.resolve()
    if relative.is_absolute() or ".." in relative.parts or not path.is_relative_to(root):
        raise PlannedPreparationError("Preparation artifact escaped its run directory")
    return path


def _write(root: Path, ref: str, value: Any, *, immutable: bool = True) -> str:
    data = value if isinstance(value, bytes) else canonical_bytes(value)
    path = _path(root, ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and immutable:
        if path.read_bytes() != data:
            raise PlannedPreparationError(f"Preparation input changed: {ref}")
    else:
        temporary = _path(root, str(Path(ref).with_name(path.name + ".pending")))
        temporary.write_bytes(data)
        temporary.replace(path)
    return hashlib.sha256(data).hexdigest()


def _read(path: Path) -> dict:
    result = json.loads(path.read_bytes())
    if not isinstance(result, dict):
        raise PlannedPreparationError("Preparation metadata must be an object")
    return result


def _gap(code: str, message: str, **details: Any) -> dict:
    return {"code": code, "message": message, **details}


def _notify(progress: Callable | None, stage: str, status: str, **details: Any) -> None:
    if progress:
        progress({"stage": stage, "status": status, **details})


def _canonical_inputs(owner: Path, bundle: dict) -> tuple[dict, dict, dict[str, bytes]]:
    supplied = bundle.get("manifest") or {}
    if _is_recorded(supplied):
        from scout_recorded_analysis import get_recorded_version
        saved = get_recorded_version(owner, supplied.get("version_id", ""), supplied.get("manifest_sha256"))
        if saved["source_status"]["status"] != "current":
            raise PlannedPreparationError("Recorded source inputs changed before preparation")
        manifest, preview = saved["manifest"], saved["preview"]
        prefix = saved["bundle_ref"]
    else:
        manifest, preview = _load_version(owner, supplied.get("version_id", ""), supplied.get("manifest_sha256"))
        prefix = f"{STORE_REF}/versions/{manifest['version_id']}"
    provided_preview = bundle.get("preview") or {}
    if manifest != supplied or any(provided_preview.get(key) != value for key, value in preview.items()):
        raise PlannedPreparationError("Requested bundle is not the saved Planned version")
    contents = {key: _path(owner, f"{prefix}/{filename}").read_bytes()
                for key, filename in _canonical_files(manifest).items()}
    contents["manifest"] = _path(owner, f"{prefix}/manifest.json").read_bytes()
    return manifest, preview, contents


def build_planned_route_mapping(preview: dict) -> dict:
    """Map every point occurrence, including revisits and zero-distance joins."""
    axis = preview.get("route_axis")
    if not isinstance(axis, list) or len(axis) < 2:
        raise PlannedPreparationError("Planned preparation requires its complete route_axis list")
    parts: list[dict] = []
    for index, point in enumerate(axis):
        if not isinstance(point, dict) or point.get("point_index") != index:
            raise PlannedPreparationError("Planned point indices must match the complete ordered axis")
        lat, lon = point.get("lat"), point.get("lon")
        if (isinstance(lat, bool) or isinstance(lon, bool) or not isinstance(lat, (int, float))
                or not isinstance(lon, (int, float)) or not math.isfinite(lat) or not math.isfinite(lon)
                or not -90 <= lat <= 90 or not -180 <= lon <= 180):
            raise PlannedPreparationError("Planned axis contains an invalid WGS84 point")
        if not parts or point.get("break_before"):
            parts.append({"part_index": len(parts), "planned_point_indices": [],
                          "break_before_point_index": index, "gap_before": None})
            if index:
                from geo_utils import haversine_m
                previous = axis[index - 1]
                parts[-1]["gap_before"] = {"from_point_index": index - 1, "to_point_index": index,
                    "distance_m": haversine_m(previous["lat"], previous["lon"], lat, lon),
                    "interpolated": False, "time_inferred": False}
        parts[-1]["planned_point_indices"].append(index)
    membership = {point: (part["part_index"], local)
                  for part in parts for local, point in enumerate(part["planned_point_indices"])}
    checkpoints = []
    for item in preview.get("checkpoints", []):
        index = item.get("point_index")
        checkpoint_id = item.get("candidate_id") or item.get("checkpoint_id")
        if not isinstance(index, int) or index not in membership:
            raise PlannedPreparationError("Planned checkpoint has no canonical point occurrence")
        if not isinstance(checkpoint_id, str) or not checkpoint_id:
            raise PlannedPreparationError("Planned checkpoint has no canonical identity")
        part, local = membership[index]
        checkpoints.append({"candidate_id": checkpoint_id, "checkpoint_id": checkpoint_id, "planned_point_index": index,
                            "part_index": part, "local_point_index": local})
    segments = []
    for item in preview.get("segments", []):
        start, end = item.get("start_point_index"), item.get("end_point_index")
        if (not isinstance(start, int) or not isinstance(end, int) or start not in membership
                or end not in membership or start > end):
            raise PlannedPreparationError("Planned segment has no complete canonical point range")
        segments.append({"segment_id": item["segment_id"], "start_point_index": start,
                         "end_point_index": end, "part_indices": sorted({membership[p][0] for p in range(start, end + 1)})})
    return {"schema_version": "scout_planned_route_mapping.v1", "point_count": len(axis),
            "checkpoint_count": len(checkpoints), "segment_count": len(segments),
            "parts": parts, "checkpoints": checkpoints, "segments": segments,
            "coordinate_transform": "none", "deduplicated": False, "gap_policy": "preserve_break_before", **BOUNDARY}


def _mapped_source(path: str, path_map: dict[str, str]) -> Path:
    return Path(path_map.get(path, path)).expanduser().resolve()


def _raw_dem_inputs(owner: Path, path_map: dict[str, str]) -> dict:
    """Read declared raw inputs; remap paths without changing their hashes."""
    from dashboard_workspace_preparation import _reject_derived_workspace_source
    from pretrip_import import validate_dtm_raster_source

    owner_hashes, saved = {}, None
    for ref in ("inbox/source_manifest.json", "outputs/import_manifest.json"):
        path = _path(owner, ref)
        if not path.is_file():
            continue
        payload = _read(path)
        if payload.get("project_id") not in (None, owner.name):
            raise PlannedPreparationError("DEM source declarations belong to another workspace")
        owner_hashes[ref] = _sha(path)
        saved = payload.get("preparation_inputs") or payload.get("inputs", {}).get("preparation_inputs")
        if saved:
            break
    if not saved:
        project = _read(owner / "project.json")
        ref = project.get("dtm_coverage_summary_ref", "normalized/terrain/dtm_coverage_summary.json")
        path = _path(owner, ref)
        if path.is_file():
            coverage = _read(path)
            owner_hashes[ref] = _sha(path)
            saved = {"dtm_rasters": coverage.get("raster_sources", []), "dtm_dirs": coverage.get("source_dirs", [])}
    saved = saved or {}
    rasters, directories, external, directory_bindings = [], [], [], []
    for original in saved.get("dtm_rasters", []):
        item = dict(original)
        item["path"] = str(_mapped_source(item["path"], path_map))
        _reject_derived_workspace_source(Path(item["path"]), field="planned_raw_dem")
        if item.get("crs_evidence") and item["crs_evidence"] != "unavailable":
            item["crs_evidence"] = str(_mapped_source(item["crs_evidence"], path_map))
        validated = validate_dtm_raster_source(item).model_dump(mode="json")
        rasters.append(validated)
        external.append({"original_path": original["path"], "resolved_path": validated["path"],
                         "sha256": validated["sha256"], "role": "raw_dem"})
        if validated.get("crs_evidence_sha256"):
            external.append({"original_path": original["crs_evidence"], "resolved_path": validated["crs_evidence"],
                             "sha256": validated["crs_evidence_sha256"], "role": "raw_dem_crs_evidence"})
    for original in saved.get("dtm_dirs", []):
        path = _mapped_source(str(original), path_map)
        _reject_derived_workspace_source(path, field="planned_raw_dem_dir")
        if not path.is_dir():
            raise PlannedPreparationError("Declared raw DTM directory is unavailable")
        directories.append(str(path))
        directory_bindings.append({"original_path": str(original), "resolved_path": str(path)})
    return {"rasters": rasters, "directories": directories, "external_source_bindings": external,
            "directory_bindings": directory_bindings, "owner_source_hashes": owner_hashes, "derived_dem_reused": False}


def _bind_raw_tiles(raw: dict, coverage: dict) -> None:
    """Bind the selected raw grid and its CRS/header before worker execution."""
    if raw["rasters"]:
        return  # The existing worker explicitly uses the first declared raster.
    bound = {item["resolved_path"]: item for item in raw["external_source_bindings"]}
    for tile in coverage.get("candidate_tiles", []):
        if not tile.get("grid_uri"):
            continue
        if "TWD97" not in str(tile.get("horizontal_datum", "")).upper():
            raise PlannedPreparationError("Selected DTM tile has no supported TWD97 declaration")
        for field, role in (("header_uri", "raw_dem_tile_header"), ("grid_uri", "raw_dem_tile")):
            path = Path(tile[field]).resolve()
            directory = next((entry for entry in raw["directory_bindings"]
                              if path.is_relative_to(Path(entry["resolved_path"]))), None)
            if directory is None:
                raise PlannedPreparationError("Selected DTM tile escaped its declared raw source directory")
            original = Path(directory["original_path"]) / path.relative_to(directory["resolved_path"])
            sha = _sha(path)
            item = {"original_path": str(original), "resolved_path": str(path), "sha256": sha, "role": role}
            if str(path) in bound and bound[str(path)] != item:
                raise PlannedPreparationError("Selected raw DTM tile changed between route parts")
            if str(path) not in bound:
                raw["external_source_bindings"].append(item)
                bound[str(path)] = item
            tile["grid_sha256" if field == "grid_uri" else "header_sha256"] = sha


def _part_gpx(points: list[dict], *, binding: dict | None = None) -> bytes:
    if binding and _is_recorded(binding):
        from scout_recorded_analysis import _recorded_gpx
        return _recorded_gpx(points, binding["project_id"], binding["observation_kind"])
    from scout_planned_route import PLAN_NS
    tree = ET.Element("gpx", {"version": "1.1", "xmlns": "http://www.topografix.com/GPX/1/1", "creator": "Scout Planned Preparation"})
    metadata = ET.SubElement(tree, "metadata")
    ET.SubElement(metadata, "type").text = "planned_candidate"
    ET.SubElement(ET.SubElement(metadata, "extensions"), f"{{{PLAN_NS}}}provenance", role="planned", recorded_track="false")
    segment = ET.SubElement(ET.SubElement(tree, "trk"), "trkseg")
    for point in points:
        node = ET.SubElement(segment, "trkpt", lat=str(point["lat"]), lon=str(point["lon"]))
        if point.get("ele") is not None:
            ET.SubElement(node, "ele").text = str(point["ele"])
    return ET.tostring(tree, encoding="utf-8", xml_declaration=True)


def _bbox(points: list[dict], margin_m: float = 0) -> dict:
    latitudes, longitudes = [p["lat"] for p in points], [p["lon"] for p in points]
    latitude = sum(latitudes) / len(latitudes)
    delta_lat = max(margin_m / 111_320, 0.0000001)
    delta_lon = max(margin_m / (111_320 * max(0.01, math.cos(math.radians(latitude)))), 0.0000001)
    return {"south": max(-90, min(latitudes) - delta_lat), "north": min(90, max(latitudes) + delta_lat),
            "west": max(-180, min(longitudes) - delta_lon), "east": min(180, max(longitudes) + delta_lon)}


def _part_workspace(run_root: Path, points: list[dict], indices: list[int], raw: dict,
                    binding: dict, part_index: int, chunk_index: int) -> tuple[Path, dict]:
    from pretrip_models import RouteBBox
    from pretrip_source_ingest import summarize_gpx, scan_dtm_coverage
    identity = _digest({"subject": binding, "indices": indices,
                        "analysis_margin_m": TERRAIN_ANALYSIS_MARGIN_M})[:20]
    root = _path(run_root, f"terrain-parts/p{part_index:03d}.c{chunk_index:03d}.{identity}")
    root.mkdir(parents=True, exist_ok=True)
    gpx_ref, route_ref = "inputs/route.gpx", "inputs/route_evidence_bundle.json"
    gpx_sha = _write(root, gpx_ref, _part_gpx(points, binding=binding))
    _write(root, "inputs/route_mapping.json", {"subject_binding": binding, "planned_point_indices": indices,
                                              "part_index": part_index, "chunk_index": chunk_index, **_subject_boundary(binding)})
    summary = summarize_gpx(root / gpx_ref, f"{'recorded' if _is_recorded(binding) else 'planned'}.{identity}")
    bounds = _bbox(points, TERRAIN_ANALYSIS_MARGIN_M)
    coverage_summary = summary.model_copy(update={"bbox_wgs84": RouteBBox(min_lat=bounds["south"],
        max_lat=bounds["north"], min_lon=bounds["west"], max_lon=bounds["east"])})
    coverage = scan_dtm_coverage(route_summary=coverage_summary, source_dirs=[Path(p) for p in raw["directories"]],
                                 summary_id=f"planned-dem.{identity}").model_dump(mode="json")
    coverage["raster_sources"] = raw["rasters"]
    coverage["coverage_scope"] = "recorded_part_bbox_plus_500m" if _is_recorded(binding) else "planned_part_bbox_plus_500m"
    coverage["analysis_margin_m"] = TERRAIN_ANALYSIS_MARGIN_M
    if not raw["rasters"] and len(coverage.get("candidate_tiles", [])) > 32:
        raise PlannedPreparationError("Planned part needs more than 32 DTM tiles; prepare a bound raw-source mosaic first")
    _bind_raw_tiles(raw, coverage)
    _write(root, "normalized/terrain/dtm_coverage_summary.json", coverage)
    _write(root, "normalized/routes/route_summary.json", summary.model_dump(mode="json"))
    _write(root, route_ref, {"project_id": root.name, "subject_binding": binding,
        "golden_route": {"role": "recorded_gpx_observation" if _is_recorded(binding) else "planned_gpx_reference",
                         "gpx_provenance_role": "reference_observation" if _is_recorded(binding) else "planned",
                         "time_role": binding.get("source_times_role", "planned_estimate"),
                         "filtered_geometry_ref": gpx_ref, "filtered_geometry_sha256": gpx_sha},
        "boundary": _subject_boundary(binding)})
    project = {"project_id": root.name,
               "route_role": "recorded_gpx_observation" if _is_recorded(binding) else "planned_gpx_reference",
               "gpx_provenance_role": "reference_observation" if _is_recorded(binding) else "planned",
               "route_evidence_bundle_ref": route_ref, "route_summary_ref": "normalized/routes/route_summary.json",
               "dtm_coverage_summary_ref": "normalized/terrain/dtm_coverage_summary.json",
               "planned_preparation_subject": binding, **_subject_boundary(binding)}
    # Worker activation owns only this part workspace's project.json after its
    # first creation. Do not replace a completed/partially completed activation.
    if not (root / "project.json").exists():
        _write(root, "project.json", project)
    return root, coverage


def _qgis_backend():
    from qgis_spatial_backend import QgisSpatialBackend
    return QgisSpatialBackend.from_env()


def _run_terrain_part(root: Path, *, backend: Any, request_id: str) -> dict:
    from pretrip_layer_preparation import LayerPreparationRequest, _run_qgis_terrain_feature_stack_after_layer_preparation
    return _run_qgis_terrain_feature_stack_after_layer_preparation(
        project_root=root, manifest={"job_id": request_id, "normalized_layers": ["terrain"]},
        request=LayerPreparationRequest(project_id=root.name, project_root=root, layers=("terrain",),
            qgis_requested_by="planned_preparation", qgis_terrain_analysis_margin_m=TERRAIN_ANALYSIS_MARGIN_M,
            qgis_terrain_workflow_timeout_s=None, qgis_terrain_poll_interval_s=0.5), backend=backend)


def _sample_dem(path: Path, points: list[dict]) -> dict:
    """Read native cells at exact canonical points without an XYZ scratch file."""
    from pretrip_source_ingest import wgs84_to_twd97
    projected = [wgs84_to_twd97(point["lat"], point["lon"]) for point in points]
    try:
        import rasterio
    except ImportError:
        from osgeo import gdal, osr
        with gdal.ExceptionMgr(useExceptions=False), osr.ExceptionMgr(useExceptions=False):
            dataset = gdal.Open(str(path), gdal.GA_ReadOnly)
            if dataset is None:
                raise PlannedPreparationError("Prepared DEM is unreadable")
            crs = osr.SpatialReference(wkt=dataset.GetProjection())
            if crs.GetAuthorityCode(None) != "3826":
                raise PlannedPreparationError("Prepared DEM CRS is not verified EPSG:3826")
            transform = dataset.GetGeoTransform()
            if transform[2] or transform[4] or transform[1] <= 0 or transform[5] >= 0:
                raise PlannedPreparationError("Prepared DEM uses an unsupported native grid")
            band, values = dataset.GetRasterBand(1), []
            nodata = band.GetNoDataValue()
            for x, y in projected:
                column, row = math.floor((x-transform[0])/transform[1]), math.floor((y-transform[3])/transform[5])
                value = float(band.ReadAsArray(column, row, 1, 1)[0, 0]) if 0 <= column < dataset.RasterXSize and 0 <= row < dataset.RasterYSize else math.nan
                values.append(value if math.isfinite(value) and value != nodata else None)
            resolution = [abs(transform[1]), abs(transform[5])]
    else:
        import numpy as np
        with rasterio.open(path) as dataset:
            if dataset.crs is None or dataset.crs.to_epsg() != 3826:
                raise PlannedPreparationError("Prepared DEM CRS is not verified EPSG:3826")
            values = []
            for (x, y), sample in zip(projected, dataset.sample(projected, masked=True)):
                value = float(sample[0]) if not bool(np.ma.getmaskarray(sample)[0]) else math.nan
                inside = dataset.bounds.left <= x < dataset.bounds.right and dataset.bounds.bottom < y <= dataset.bounds.top
                values.append(value if inside and math.isfinite(value) and value != dataset.nodata else None)
            resolution = list(dataset.res)
    return {"values": values, "resolution_m": resolution, "crs": "EPSG:3826",
            "sampling_method": "native_dem_cell_at_exact_planned_point", "interpolated": False}


def _terrain_artifacts(run_root: Path, root: Path, result: dict, points: list[dict], indices: list[int]) -> dict:
    refs, hashes = {}, {}
    for key, ref in result.get("output_refs", {}).items():
        if not key.endswith("_ref") or not isinstance(ref, str):
            continue
        path = _path(root, ref)
        if not path.is_file():
            raise PlannedPreparationError(f"Terrain output is missing: {key}")
        relative = path.relative_to(run_root).as_posix()
        refs[key], hashes[relative] = relative, _sha(path)
    for key, ref in (("dtm_coverage_summary_ref", "normalized/terrain/dtm_coverage_summary.json"),
                     ("project_snapshot_ref", "project.json"), ("route_mapping_ref", "inputs/route_mapping.json"),
                     ("route_evidence_bundle_ref", "inputs/route_evidence_bundle.json"), ("planned_part_gpx_ref", "inputs/route.gpx")):
        path = _path(root, ref)
        relative = path.relative_to(run_root).as_posix()
        refs[key], hashes[relative] = relative, _sha(path)
    dem_ref = refs.get("terrain_dem_route_bbox_raster_ref")
    parent_ref = refs.get("terrain_feature_manifest_ref")
    if not dem_ref or not parent_ref:
        raise PlannedPreparationError("Terrain result has no independently bound DEM and parent")
    sampled = _sample_dem(run_root / dem_ref, points)
    samples = [{"planned_point_index": index, "lat": point["lat"], "lon": point["lon"], "elevation_m": value}
               for index, point, value in zip(indices, points, sampled["values"])]
    if len(samples) != len(points):
        raise PlannedPreparationError("Terrain sample count does not match the complete input part")
    sample_ref = (root / "outputs/planned_terrain_samples.json").relative_to(run_root).as_posix()
    part_mapping = _read(run_root / refs["route_mapping_ref"])
    if _is_recorded(part_mapping["subject_binding"]):
        sampled["sampling_method"] = "native_dem_cell_at_exact_recorded_point"
        for row in samples:
            row["recorded_point_index"] = row["planned_point_index"]
    hashes[sample_ref] = _write(run_root, sample_ref, {"points": samples, "dem_ref": dem_ref,
        "dem_sha256": hashes[dem_ref], "parent_ref": parent_ref, "parent_sha256": hashes[parent_ref],
        "subject_binding": part_mapping["subject_binding"], "mapping_ref": refs["route_mapping_ref"],
        "mapping_sha256": hashes[refs["route_mapping_ref"]],
        **{key: value for key, value in sampled.items() if key != "values"}, **_subject_boundary(part_mapping["subject_binding"])}, immutable=False)
    refs["terrain_samples_ref"] = sample_ref
    refs["terrain_route_samples_ref"] = sample_ref
    unsupported = [row["planned_point_index"] for row in samples if row["elevation_m"] is None]
    return {"output_refs": refs, "source_hashes": hashes, "point_count": len(samples),
            "subject_binding": part_mapping["subject_binding"],
            "unsupported_point_indices": unsupported, "coverage_status": "verified" if not unsupported else "partial",
            "resolution_m": sampled["resolution_m"], "analysis_margin_m": TERRAIN_ANALYSIS_MARGIN_M}


def _segment_distance_sq(a: tuple, b: tuple, c: tuple, d: tuple) -> float:
    def cross(u, v, w):
        return (v[0]-u[0]) * (w[1]-u[1]) - (v[1]-u[1]) * (w[0]-u[0])

    def point_distance(p, u, v):
        dx, dy = v[0]-u[0], v[1]-u[1]
        size = dx*dx + dy*dy
        factor = max(0.0, min(1.0, ((p[0]-u[0])*dx + (p[1]-u[1])*dy)/size)) if size else 0.0
        return (p[0]-u[0]-factor*dx)**2 + (p[1]-u[1]-factor*dy)**2

    if (max(min(a[0], b[0]), min(c[0], d[0])) <= min(max(a[0], b[0]), max(c[0], d[0]))
            and max(min(a[1], b[1]), min(c[1], d[1])) <= min(max(a[1], b[1]), max(c[1], d[1]))
            and cross(a, b, c)*cross(a, b, d) <= 0 and cross(c, d, a)*cross(c, d, b) <= 0):
        return 0.0
    return min(point_distance(a, c, d), point_distance(b, c, d), point_distance(c, a, b), point_distance(d, a, b))


def _corridor_sources(sources: list[dict], axis: list[dict], margin_m: float = 500) -> list[dict]:
    """Attach an exact point-index projection; never align or clip the axis."""
    from pretrip_source_ingest import wgs84_to_twd97

    def cells(a, b, expansion=0):
        for x in range(math.floor((min(a[0], b[0])-expansion)/margin_m), math.floor((max(a[0], b[0])+expansion)/margin_m)+1):
            for y in range(math.floor((min(a[1], b[1])-expansion)/margin_m), math.floor((max(a[1], b[1])+expansion)/margin_m)+1):
                yield x, y

    projected = [wgs84_to_twd97(point["lat"], point["lon"]) for point in axis]
    route_segments, index = [], {}
    for point_index, point in enumerate(axis):
        start_index = point_index if point_index == 0 or point.get("break_before") else point_index-1
        a, b = projected[start_index], projected[point_index]
        segment_index = len(route_segments)
        route_segments.append((a, b, start_index, point_index))
        for cell in cells(a, b, margin_m):
            index.setdefault(cell, []).append(segment_index)
    matched = []
    for source in sources:
        nearest = None
        for part in source["parts"]:
            line = [wgs84_to_twd97(point["lat"], point["lon"]) for point in part]
            for c, d in zip(line, line[1:]):
                candidates = {item for cell in cells(c, d) for item in index.get(cell, [])}
                for item in candidates:
                    a, b, start, end = route_segments[item]
                    distance_sq = _segment_distance_sq(a, b, c, d)
                    if distance_sq <= margin_m**2 and (nearest is None or distance_sq < nearest[0]):
                        nearest = distance_sq, start, end
        if nearest is not None:
            matched.append({**source, "planned_projection": {"crs": "EPSG:3826", "corridor_margin_m": margin_m,
                "distance_m": math.sqrt(nearest[0]), "start_point_index": nearest[1], "end_point_index": nearest[2],
                "projection_kind": "minimum_distance_to_preserved_part_segment", "geometry_changed": False,
                "walkability_inferred": False, "interpolated_across_gap": False}})
    return matched


def _prepare_map(run_root: Path, workspace: Path, axis: list[dict], binding: dict) -> dict:
    query_bbox = _bbox(axis, 500)
    bundle = fetch_trail_source_candidates(query_bbox)
    if bundle.get("candidate_only") is not True or bundle.get("runtime_safety_truth") is not False:
        raise PlannedPreparationError("Map source violated candidate authority")
    for ref, data in bundle["files"].items():
        if hashlib.sha256(data).hexdigest() != bundle["source_hashes"].get(ref):
            raise PlannedPreparationError("Fetched raw/vector source hash mismatch")
        _write(workspace, ref, data)
    project = _read(workspace / "project.json")
    project["planned_overpass_source_refs"] = [bundle["project_binding"]]
    _write(workspace, "project.json", project, immutable=False)
    catalog = load_map_route_sources(workspace, project)
    acquired_sources = [source for source in catalog["sources"] if source["kind"] == "overpass"]
    sources = _corridor_sources(acquired_sources, axis)
    prefix = workspace.relative_to(run_root).as_posix()
    hashes = {f"{prefix}/{ref}": sha for ref, sha in catalog["source_hashes"].items()}
    ref = f"{prefix}/outputs/planned_map_sources.json"
    hashes[ref] = _write(run_root, ref, {"subject_binding": binding, "bbox_wgs84": query_bbox,
        "sources": sources, "source_ref_base": prefix, "query": bundle["query"],
        "acquired_source_count": len(acquired_sources), "corridor_margin_m": 500,
        "interpretation": "Acquired map context; vector presence does not establish trail continuity or walkability.",
        "evidence_time_role": "current_map_context_not_historical_ground_truth" if _is_recorded(binding) else "current_map_context",
        **_subject_boundary(binding)}, immutable=False)
    return {"status": "completed" if sources else "no_trail_candidates", "catalog_ref": ref,
            "source_count": len(sources), "source_hashes": hashes, "bbox_wgs84": query_bbox,
            "coverage_scope": "planned_route_parts_corridor_500m", "acquisition_scope": "planned_route_bbox_plus_500m",
            "acquired_source_count": len(acquired_sources), "route_geometry_changed": False,
            "issues": [issue for issue in catalog["issues"] if issue.get("source_kind") == "overpass"]}


def prepare_planned_inputs(owner_root: Path, bundle: dict, run_root: Path, *,
                           progress: Callable | None = None, source_path_map: dict[str, str] | None = None) -> dict:
    """Executable, resumable preparation; caller owns job locking/publication.

    This function may fetch public Overpass data and invoke the configured QGIS
    worker. It never starts a service, writes owner artifacts, materializes a
    broad scratch DEM, changes a Planned review, or manufactures a reviewed graph.
    Raw DEM/CRS paths may be relocated for a Scout run only with matching hashes.
    """
    owner, run = Path(owner_root).resolve(), Path(run_root).resolve()
    recorded = _is_recorded(bundle.get("manifest") or {})
    allowed_nested_root = owner / ("outputs/recorded_analysis/runs" if recorded else "outputs/planned_analysis/runs")
    if (run == owner or owner.is_relative_to(run)
            or (run.is_relative_to(owner) and not run.is_relative_to(allowed_nested_root))):
        raise PlannedPreparationError("Preparation run must be isolated from owner inputs and saved Planned versions")
    manifest, preview, contents = _canonical_inputs(owner, bundle)
    mapping = build_planned_route_mapping(preview)
    axis = preview["route_axis"]
    if recorded:
        from scout_recorded_jobs import recorded_binding
        binding = recorded_binding(bundle)
        mapping.update(_subject_boundary(binding))
        mapping["schema_version"] = "scout_recorded_route_mapping.v1"
        for part in mapping["parts"]:
            part["recorded_point_indices"] = part["planned_point_indices"]
        for checkpoint in mapping["checkpoints"]:
            checkpoint["recorded_point_index"] = checkpoint["planned_point_index"]
    else:
        from scout_planned_analysis import planned_binding
        binding = planned_binding(bundle)
    if binding["manifest_file_sha256"] != hashlib.sha256(contents["manifest"]).hexdigest():
        raise PlannedPreparationError("Manifest byte identity does not match the requested analysis binding")
    identity = _digest({"schema": SCHEMA, "subject_binding": binding,
                        "analysis_margin_m": TERRAIN_ANALYSIS_MARGIN_M})
    run.mkdir(parents=True, exist_ok=True)
    _write(run, "inputs/subject_binding.json", binding)
    canonical_refs, source_hashes = {}, {}
    for key, filename in {**_canonical_files(manifest), "manifest": "manifest.json"}.items():
        ref = f"inputs/{filename}"
        canonical_refs[key] = ref
        source_hashes[ref] = _write(run, ref, contents[key])
    mapping_ref = "inputs/route_mapping.json"
    source_hashes[mapping_ref] = _write(run, mapping_ref, mapping)
    workspace = _path(run, f"workspaces/prep.{identity[:20]}")
    workspace.mkdir(parents=True, exist_ok=True)
    if not (workspace / "project.json").exists():
        _write(workspace, "project.json", {"project_id": workspace.name, "planned_preparation_subject": binding, **_subject_boundary(binding)})
    gaps, terrain_parts = [], []
    _notify(progress, "canonical_inputs", "completed", point_count=len(axis), part_count=len(mapping["parts"]))
    _notify(progress, "map", "running")
    try:
        maps = _prepare_map(run, workspace, axis, binding)
        source_hashes.update(maps["source_hashes"])
        if maps["status"] != "completed":
            gaps.append(_gap("planned_map_candidates_missing", "Map acquisition found no usable trail candidates."))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        maps = {"status": "unavailable", "source_hashes": {}, "error_type": type(exc).__name__}
        gaps.append(_gap("planned_map_unavailable", "Planned map acquisition is unavailable; retry this preparation.", error_type=type(exc).__name__))
    _notify(progress, "map", maps["status"])
    raw = {"rasters": [], "directories": [], "owner_source_hashes": {}, "external_source_bindings": []}
    try:
        raw = _raw_dem_inputs(owner, dict(source_path_map or {}))
        if not raw["rasters"] and not raw["directories"]:
            raise PlannedPreparationError("No declared raw DEM source is available for this Planned route")
        source_hashes["inputs/raw_dem_sources.json"] = _write(run, "inputs/raw_dem_sources.json", raw)
        backend = _qgis_backend()
        for part in mapping["parts"]:
            indices = part["planned_point_indices"]
            chunks = [indices[first:first + MAX_WORKER_POINTS] for first in range(0, len(indices)-1, MAX_WORKER_POINTS-1)]
            if not chunks:
                gaps.append(_gap("planned_terrain_point_only", "A one-point part has no continuous terrain route.", part_index=part["part_index"]))
            for chunk_index, chunk in enumerate(chunks):
                points = [axis[index] for index in chunk]
                _notify(progress, "terrain", "running", part_index=part["part_index"], chunk_index=chunk_index)
                record = {"part_index": part["part_index"], "chunk_index": chunk_index, "planned_point_indices": chunk}
                try:
                    part_root, coverage = _part_workspace(run, points, chunk, raw, binding, part["part_index"], chunk_index)
                    record["workspace_ref"] = part_root.relative_to(run).as_posix()
                    if not coverage["raster_sources"] and not coverage["candidate_tiles"]:
                        raise PlannedPreparationError("No raw DTM covers this Planned part")
                    terrain = _run_terrain_part(part_root, backend=backend, request_id=f"planned-preparation.{identity[:20]}.{part['part_index']}.{chunk_index}")
                    record.update(status=terrain.get("status", "unavailable"), workflow_run_id=terrain.get("workflow_run_id"), processor=terrain.get("actual_processor"))
                    if terrain.get("status") == "completed" and terrain.get("actual_processor") == "qgis_processing_grass":
                        record.update(_terrain_artifacts(run, part_root, terrain, points, chunk))
                        source_hashes.update(record["source_hashes"])
                        if record["coverage_status"] != "verified":
                            gaps.append(_gap("planned_dem_nodata", "Prepared DEM has unsupported canonical points.", part_index=part["part_index"], point_indices=record["unsupported_point_indices"]))
                    else:
                        gaps.append(_gap("planned_terrain_unavailable", "Planned terrain processing did not complete.", part_index=part["part_index"], status=record["status"], error=terrain.get("error")))
                except (OSError, ValueError, KeyError, TypeError, ImportError) as exc:
                    record.update(status="unavailable", error_type=type(exc).__name__)
                    gaps.append(_gap("planned_terrain_unavailable", str(exc), part_index=part["part_index"], error_type=type(exc).__name__))
                terrain_parts.append(record)
                _notify(progress, "terrain", record["status"], part_index=part["part_index"], chunk_index=chunk_index)
    except (OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        gaps.append(_gap("planned_raw_dem_unavailable", str(exc), error_type=type(exc).__name__))
    for source in raw["external_source_bindings"]:
        if not Path(source["resolved_path"]).is_file() or _sha(Path(source["resolved_path"])) != source["sha256"]:
            raise PlannedPreparationError("Raw DEM/CRS source changed during preparation")
    for ref, expected in raw["owner_source_hashes"].items():
        if _sha(_path(owner, ref)) != expected:
            raise PlannedPreparationError("Owner DEM declarations changed during preparation")
    latest, _, latest_contents = _canonical_inputs(owner, bundle)
    if latest != manifest or latest_contents != contents:
        raise PlannedPreparationError("Planned bundle changed during preparation")
    if raw["rasters"] or raw["directories"]:
        source_hashes["inputs/raw_dem_sources.json"] = _write(run, "inputs/raw_dem_sources.json", raw, immutable=False)
    covered_points = {index for part in terrain_parts if part.get("coverage_status") == "verified"
                      for index in part["planned_point_indices"]}
    terrain_ready = (covered_points == set(range(len(axis)))
                     and all(part.get("coverage_status") == "verified" for part in terrain_parts))
    result = {"schema_version": SCHEMA, "status": "completed_with_gaps" if gaps else "completed",
        "preparation_identity": identity, "subject_binding": binding,
        "workspace_ref": workspace.relative_to(run).as_posix(), "canonical_refs": canonical_refs,
        "mapping_ref": mapping_ref, "source_hashes": source_hashes,
        "owner_source_hashes": {**manifest["source_hashes"], **raw["owner_source_hashes"]},
        "external_source_bindings": raw["external_source_bindings"], "terrain_parts": terrain_parts, "map_sources": maps,
        "coverage": {"status": "prepared" if terrain_ready and maps["status"] == "completed" else "partial",
            "geometry_sha256": manifest["geometry_sha256"], "point_count": len(axis), "part_count": len(mapping["parts"]),
            "terrain_point_coverage": "verified" if terrain_ready else "unverified_or_partial",
            "gap_count": len(mapping["parts"])-1, "gaps_filled": False,
            "safe_or_walkable": "not_determined", "map_status": maps["status"]},
        "gaps": gaps, **_subject_boundary(binding)}
    if recorded:
        result["schema_version"] = "scout_recorded_preparation.v1"
        result["weather_evaluation_mode"] = "historical_at_observation_time"
        result["coverage"]["recorded_point_count"] = len(axis)
        for part in terrain_parts:
            part["recorded_point_indices"] = part["planned_point_indices"]
    _write(run, "preparation_result.json", result, immutable=False)
    return result
