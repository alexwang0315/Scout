from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


_ALLOWED_EXECUTABLES = frozenset(
    {
        "gdal_contour",
        "gdallocationinfo",
        "gdaldem",
        "gdalinfo",
        "gdalsrsinfo",
        "gdaltransform",
        "gdal_translate",
        "grass",
        "qgis_process",
    }
)
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_TERMINAL_STATES = {"completed", "failed", "cancelled"}
_QGIS_WORKFLOW_IDS = frozenset(
    {"terrain_context_preview.v1", "terrain_feature_stack.v1"}
)


class BenchmarkError(RuntimeError):
    pass


@dataclass(frozen=True)
class CommandExecution:
    label: str
    command: list[str]
    started_at: str
    duration_ms: float
    returncode: int
    max_rss_kb: int | None
    stdout: str
    stderr: str

    def report(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "command": self.command,
            "started_at": self.started_at,
            "duration_ms": self.duration_ms,
            "returncode": self.returncode,
            "max_rss_kb": self.max_rss_kb,
            "stdout_tail": self.stdout[-2000:],
            "stderr_tail": self.stderr[-2000:],
            "status": "completed" if self.returncode == 0 else "failed",
        }


def _candidate_authority() -> dict[str, bool]:
    return {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "operational": False,
        "benchmark_only": True,
    }


def _validate_command(command: list[str]) -> list[str]:
    if not command or not all(isinstance(item, str) and item for item in command):
        raise BenchmarkError("external command must be a non-empty argument list")
    if len(command) > 128 or any(len(item) > 16_384 for item in command):
        raise BenchmarkError("external command exceeds the bounded argument limit")
    if any("\x00" in item or "\n" in item or "\r" in item for item in command):
        raise BenchmarkError("external command contains forbidden control characters")
    executable = Path(command[0]).name
    if executable not in _ALLOWED_EXECUTABLES:
        raise BenchmarkError(f"external executable is not allowlisted: {executable}")
    return list(command)


def _execute_command(
    *,
    label: str,
    command: list[str],
    metrics_root: Path,
    timeout_s: float,
    stdin_text: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> CommandExecution:
    bounded = _validate_command(command)
    resolved = shutil.which(bounded[0])
    if not resolved:
        raise BenchmarkError(f"external executable is unavailable: {bounded[0]}")
    bounded = [resolved, *bounded[1:]]
    metrics_root.mkdir(parents=True, exist_ok=True)
    metrics_path = metrics_root / f"{_safe_label(label)}.time.tsv"
    timed_command = bounded
    time_binary = Path("/usr/bin/time")
    if time_binary.is_file():
        timed_command = [
            str(time_binary),
            "-f",
            "%e\t%M\t%x",
            "-o",
            str(metrics_path),
            *bounded,
        ]
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    started_at = _now_iso()
    started = time.perf_counter_ns()
    try:
        completed = subprocess.run(
            timed_command,
            input=stdin_text,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=timeout_s,
            check=False,
            shell=False,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise BenchmarkError(f"external command timed out: {label}") from exc
    duration_ms = round((time.perf_counter_ns() - started) / 1_000_000, 3)
    max_rss_kb = _time_max_rss(metrics_path)
    execution = CommandExecution(
        label=label,
        command=[Path(bounded[0]).name, *bounded[1:]],
        started_at=started_at,
        duration_ms=duration_ms,
        returncode=completed.returncode,
        max_rss_kb=max_rss_kb,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
    if completed.returncode != 0:
        detail = " ".join(completed.stderr.strip().split())[-1000:]
        raise BenchmarkError(
            f"external command failed: {label} (exit={completed.returncode}): {detail}"
        )
    return execution


def _parse_gpx_points(path: Path, *, max_points: int = 20_000) -> list[list[float]]:
    if max_points < 2 or max_points > 20_000:
        raise BenchmarkError("GPX point limit must be between 2 and 20000")
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        raise BenchmarkError(f"GPX input is unreadable: {path}") from exc
    points: list[list[float]] = []
    for element in root.iter():
        local_name = element.tag.rsplit("}", 1)[-1]
        if local_name not in {"trkpt", "rtept"}:
            continue
        try:
            lon = float(element.attrib["lon"])
            lat = float(element.attrib["lat"])
        except (KeyError, TypeError, ValueError) as exc:
            raise BenchmarkError("GPX contains an invalid route coordinate") from exc
        if not -180 <= lon <= 180 or not -90 <= lat <= 90:
            raise BenchmarkError("GPX contains a coordinate outside WGS84 bounds")
        points.append([lon, lat])
    if len(points) < 2:
        raise BenchmarkError("GPX must contain at least two track or route points")
    return _sample_points(points, max_points=max_points)


def _sample_points(points: list[list[float]], *, max_points: int) -> list[list[float]]:
    if len(points) <= max_points:
        return points
    indexes = {
        round(index * (len(points) - 1) / (max_points - 1))
        for index in range(max_points)
    }
    return [points[index] for index in sorted(indexes)]


def _bounded_window(
    *,
    projected_points: list[tuple[float, float]],
    raster_bounds: tuple[float, float, float, float],
    corridor_m: float,
    pixel_size: tuple[float, float],
    max_cells: int,
) -> dict[str, float | int]:
    if not projected_points:
        raise BenchmarkError("route projection produced no points")
    if corridor_m < 0 or corridor_m > 5_000:
        raise BenchmarkError("corridor distance must be between 0 and 5000 metres")
    if max_cells < 1:
        raise BenchmarkError("maximum raster cell count must be positive")
    raster_min_x, raster_min_y, raster_max_x, raster_max_y = raster_bounds
    pixel_x, pixel_y = map(abs, pixel_size)
    if pixel_x <= 0 or pixel_y <= 0:
        raise BenchmarkError("DEM pixel resolution is invalid")
    route_min_x = min(point[0] for point in projected_points) - corridor_m
    route_min_y = min(point[1] for point in projected_points) - corridor_m
    route_max_x = max(point[0] for point in projected_points) + corridor_m
    route_max_y = max(point[1] for point in projected_points) + corridor_m
    min_x = max(raster_min_x, route_min_x)
    min_y = max(raster_min_y, route_min_y)
    max_x = min(raster_max_x, route_max_x)
    max_y = min(raster_max_y, route_max_y)
    if min_x >= max_x or min_y >= max_y:
        raise BenchmarkError("route corridor does not intersect the DEM")
    min_x = max(
        raster_min_x,
        raster_min_x + math.floor((min_x - raster_min_x) / pixel_x) * pixel_x,
    )
    min_y = max(
        raster_min_y,
        raster_min_y + math.floor((min_y - raster_min_y) / pixel_y) * pixel_y,
    )
    max_x = min(
        raster_max_x,
        raster_min_x + math.ceil((max_x - raster_min_x) / pixel_x) * pixel_x,
    )
    max_y = min(
        raster_max_y,
        raster_min_y + math.ceil((max_y - raster_min_y) / pixel_y) * pixel_y,
    )
    cols = max(1, math.ceil((max_x - min_x) / pixel_x))
    rows = max(1, math.ceil((max_y - min_y) / pixel_y))
    cells = cols * rows
    if cells > max_cells:
        raise BenchmarkError(
            f"route corridor exceeds the bounded raster cell limit: {cells} > {max_cells}"
        )
    return {
        "min_x": round(min_x, 6),
        "min_y": round(min_y, 6),
        "max_x": round(max_x, 6),
        "max_y": round(max_y, 6),
        "cols": cols,
        "rows": rows,
        "cells": cells,
    }


def _source_window(
    *,
    spatial_window: dict[str, float | int],
    geo_transform: tuple[float, ...],
    raster_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    if len(geo_transform) != 6 or geo_transform[2] != 0 or geo_transform[4] != 0:
        raise BenchmarkError("rotated DEM geotransforms are not supported")
    origin_x, pixel_x, _, origin_y, _, pixel_y = geo_transform
    if pixel_x == 0 or pixel_y == 0:
        raise BenchmarkError("DEM geotransform has an invalid pixel size")
    x_pixels = [
        (float(spatial_window[key]) - origin_x) / pixel_x
        for key in ("min_x", "max_x")
    ]
    y_pixels = [
        (float(spatial_window[key]) - origin_y) / pixel_y
        for key in ("min_y", "max_y")
    ]
    xoff = max(0, math.floor(min(x_pixels)))
    yoff = max(0, math.floor(min(y_pixels)))
    xend = min(raster_size[0], math.ceil(max(x_pixels)))
    yend = min(raster_size[1], math.ceil(max(y_pixels)))
    if xoff >= xend or yoff >= yend:
        raise BenchmarkError("route corridor produced an empty DEM source window")
    return xoff, yoff, xend - xoff, yend - yoff


def _route_points_in_window(
    *,
    wgs84_points: list[list[float]],
    projected_points: list[tuple[float, float]],
    spatial_window: dict[str, float | int],
) -> list[list[float]]:
    if len(wgs84_points) != len(projected_points):
        raise BenchmarkError("route coordinate projections are inconsistent")
    matching = [
        index
        for index, (x, y) in enumerate(projected_points)
        if float(spatial_window["min_x"]) <= x <= float(spatial_window["max_x"])
        and float(spatial_window["min_y"]) <= y <= float(spatial_window["max_y"])
    ]
    if not matching:
        raise BenchmarkError("no route points intersect the bounded DEM window")
    runs: list[tuple[int, int]] = []
    run_start = matching[0]
    run_end = matching[0]
    for index in matching[1:]:
        if index == run_end + 1:
            run_end = index
            continue
        runs.append((run_start, run_end))
        run_start = index
        run_end = index
    runs.append((run_start, run_end))
    matched_start, matched_end = max(
        runs,
        key=lambda item: (item[1] - item[0], -item[0]),
    )
    start = max(0, matched_start - 1)
    end = min(len(wgs84_points), matched_end + 2)
    bounded = wgs84_points[start:end]
    if len(bounded) < 2:
        raise BenchmarkError("bounded route context requires at least two points")
    return bounded


def run_benchmark(
    *,
    project_id: str,
    route_gpx: Path,
    dem_path: Path,
    output_root: Path,
    source_root: Path,
    run_id: str,
    corridor_m: float = 500.0,
    max_cells: int = 4_000_000,
    timeout_s: float = 600.0,
    qgis_workflow_id: str = "terrain_context_preview.v1",
) -> tuple[dict[str, Any], Path]:
    if not _SAFE_RUN_ID.fullmatch(run_id):
        raise BenchmarkError("run ID contains unsupported characters")
    if qgis_workflow_id not in _QGIS_WORKFLOW_IDS:
        raise BenchmarkError("QGIS workflow is not allowlisted for the Pi GIS benchmark")
    route_gpx = route_gpx.expanduser().resolve(strict=True)
    dem_path = dem_path.expanduser().resolve(strict=True)
    source_root = source_root.expanduser().resolve(strict=True)
    if not _path_under(route_gpx, source_root) or not _path_under(dem_path, source_root):
        raise BenchmarkError("route and DEM inputs must stay inside the bounded source root")
    output_dir = output_root.expanduser().resolve(strict=False) / run_id
    if output_dir.exists():
        raise BenchmarkError(f"benchmark output already exists: {output_dir}")
    output_dir.mkdir(parents=True, mode=0o700)
    commands_root = output_dir / "command-metrics"
    command_reports: list[dict[str, Any]] = []
    report_path = output_dir / "benchmark-report.json"
    report: dict[str, Any] = {
        "schema_version": "scout_pi_gis_benchmark.v0_1",
        "artifact_kind": "scout_pi_gis_benchmark_report",
        "run_id": run_id,
        "project_id": project_id,
        "recorded_at": _now_iso(),
        "status": "running",
        "host": _host_summary(),
        "authority": _candidate_authority(),
        "review": {
            "processing_success": False,
            "render_success": False,
            "machine_review": "pending",
            "visual_review": "pending",
            "human_review": "pending",
        },
        "inputs": {
            "route_gpx": str(route_gpx),
            "route_sha256": _sha256(route_gpx),
            "dem": str(dem_path),
            "dem_sha256": _sha256(dem_path),
            "corridor_m": corridor_m,
            "max_cells": max_cells,
            "qgis_workflow_id": qgis_workflow_id,
        },
        "resource_before": _resource_snapshot(),
        "commands": command_reports,
        "warnings": [
            "GIS processing success is evidence of execution, not terrain or safety truth.",
            "The crop is a route-corridor bounding envelope, not a navigability conclusion.",
        ],
    }
    _write_report(report_path, report)
    try:
        points = _parse_gpx_points(route_gpx)
        metadata, target_srs = _inspect_dem(
            dem_path=dem_path,
            metrics_root=commands_root,
            command_reports=command_reports,
            timeout_s=timeout_s,
        )
        projected = _project_route(
            points=points,
            target_srs=target_srs,
            metrics_root=commands_root,
            command_reports=command_reports,
            timeout_s=timeout_s,
        )
        route_dem_coverage = _sample_route_dem(
            dem_path=dem_path,
            projected_points=projected,
            nodata_value=metadata["nodata_value"],
            metrics_root=commands_root,
            command_reports=command_reports,
            timeout_s=timeout_s,
        )
        window = _bounded_window(
            projected_points=projected,
            raster_bounds=metadata["bounds"],
            corridor_m=corridor_m,
            pixel_size=metadata["pixel_size"],
            max_cells=max_cells,
        )
        srcwin = _source_window(
            spatial_window=window,
            geo_transform=metadata["geo_transform"],
            raster_size=metadata["size"],
        )
        window["source_window"] = list(srcwin)
        bounded_route_points = _route_points_in_window(
            wgs84_points=points,
            projected_points=projected,
            spatial_window=window,
        )
        report["inputs"].update(
            {
                "route_point_count": len(points),
                "bounded_route_point_count": len(bounded_route_points),
                "dem_crs": target_srs,
                "dem_pixel_size": list(metadata["pixel_size"]),
                "dem_raster_size": list(metadata["size"]),
                "dem_nodata_value": metadata["nodata_value"],
                "route_dem_coverage": route_dem_coverage,
                "bounded_window": window,
                "adds_source_resolution": False,
            }
        )
        gdal_result = _run_gdal(
            dem_path=dem_path,
            output_dir=output_dir,
            target_srs=target_srs,
            window=window,
            metrics_root=commands_root,
            command_reports=command_reports,
            timeout_s=timeout_s,
        )
        report["gdal"] = gdal_result
        _write_report(report_path, report)
        grass_result = _run_grass(
            dem_path=Path(gdal_result["crop_ref"]),
            output_dir=output_dir,
            metrics_root=commands_root,
            command_reports=command_reports,
            timeout_s=timeout_s,
        )
        report["grass"] = grass_result
        _write_report(report_path, report)
        qgis_result = _run_qgis_mcp(
            project_id=project_id,
            run_id=run_id,
            points=bounded_route_points,
            dem_path=Path(gdal_result["crop_ref"]),
            route_gpx=route_gpx,
            source_root=source_root,
            output_dir=output_dir,
            corridor_m=corridor_m,
            metadata=metadata,
            timeout_s=timeout_s,
            workflow_id=qgis_workflow_id,
        )
        report["qgis_mcp"] = qgis_result
        report["status"] = "completed"
        report["completed_at"] = _now_iso()
        report["review"]["processing_success"] = True
        report["review"]["render_success"] = bool(qgis_result.get("render_completed"))
        report["artifacts"] = _artifact_inventory(output_dir, report_path)
        report["resource_after"] = _resource_snapshot()
        _write_report(report_path, report)
        return report, report_path
    except Exception as exc:
        report["status"] = "failed"
        report["completed_at"] = _now_iso()
        report["error"] = {
            "code": _error_code(exc),
            "message": str(exc),
            "type": type(exc).__name__,
        }
        report["resource_after"] = _resource_snapshot()
        _write_report(report_path, report)
        raise


def _inspect_dem(
    *,
    dem_path: Path,
    metrics_root: Path,
    command_reports: list[dict[str, Any]],
    timeout_s: float,
) -> tuple[dict[str, Any], str]:
    info = _record(
        command_reports,
        _execute_command(
            label="gdalinfo_json",
            command=["gdalinfo", "-json", str(dem_path)],
            metrics_root=metrics_root,
            timeout_s=timeout_s,
        ),
    )
    try:
        payload = json.loads(info.stdout)
        size = tuple(int(value) for value in payload["size"][:2])
        transform = tuple(float(value) for value in payload["geoTransform"])
        corners = payload["cornerCoordinates"]
        corner_values = [
            corners[name]
            for name in ("upperLeft", "lowerLeft", "lowerRight", "upperRight")
        ]
        bands = payload["bands"]
        if not isinstance(bands, list) or not bands:
            raise KeyError("bands")
        raw_nodata = bands[0].get("noDataValue")
        nodata_value = float(raw_nodata) if raw_nodata is not None else None
        xs = [float(value[0]) for value in corner_values]
        ys = [float(value[1]) for value in corner_values]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise BenchmarkError("GDAL did not return usable DEM metadata") from exc
    srs = _record(
        command_reports,
        _execute_command(
            label="gdalsrsinfo_epsg",
            command=["gdalsrsinfo", "-o", "epsg", str(dem_path)],
            metrics_root=metrics_root,
            timeout_s=timeout_s,
        ),
    )
    match = re.search(r"EPSG:\d+", srs.stdout)
    if not match:
        raise BenchmarkError("DEM CRS could not be resolved to an EPSG identifier")
    return (
        {
            "size": size,
            "pixel_size": (abs(transform[1]), abs(transform[5])),
            "bounds": (min(xs), min(ys), max(xs), max(ys)),
            "geo_transform": transform,
            "nodata_value": nodata_value,
        },
        match.group(0),
    )


def _project_route(
    *,
    points: list[list[float]],
    target_srs: str,
    metrics_root: Path,
    command_reports: list[dict[str, Any]],
    timeout_s: float,
) -> list[tuple[float, float]]:
    input_text = "".join(f"{lon:.10f} {lat:.10f}\n" for lon, lat in points)
    execution = _record(
        command_reports,
        _execute_command(
            label="gdaltransform_route",
            command=["gdaltransform", "-s_srs", "EPSG:4326", "-t_srs", target_srs],
            metrics_root=metrics_root,
            timeout_s=timeout_s,
            stdin_text=input_text,
        ),
    )
    projected: list[tuple[float, float]] = []
    for line in execution.stdout.splitlines():
        values = line.split()
        if len(values) < 2:
            continue
        try:
            projected.append((float(values[0]), float(values[1])))
        except ValueError as exc:
            raise BenchmarkError("GDAL route projection returned an invalid coordinate") from exc
    if len(projected) != len(points):
        raise BenchmarkError("GDAL route projection returned an incomplete result")
    return projected


def _sample_route_dem(
    *,
    dem_path: Path,
    projected_points: list[tuple[float, float]],
    nodata_value: float | None,
    metrics_root: Path,
    command_reports: list[dict[str, Any]],
    timeout_s: float,
) -> dict[str, Any]:
    input_text = "".join(f"{x:.6f} {y:.6f}\n" for x, y in projected_points)
    execution = _record(
        command_reports,
        _execute_command(
            label="gdallocationinfo_route_coverage",
            command=["gdallocationinfo", "-valonly", "-geoloc", str(dem_path)],
            metrics_root=metrics_root,
            timeout_s=timeout_s,
            stdin_text=input_text,
        ),
    )
    return _parse_route_dem_coverage(
        execution.stdout,
        expected_count=len(projected_points),
        nodata_value=nodata_value,
    )


def _parse_route_dem_coverage(
    output: str,
    *,
    expected_count: int,
    nodata_value: float | None,
) -> dict[str, Any]:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if len(lines) != expected_count:
        raise BenchmarkError(
            "GDAL route DEM coverage returned an incomplete result: "
            f"{len(lines)} != {expected_count}"
        )
    try:
        values = [float(line) for line in lines]
    except ValueError as exc:
        raise BenchmarkError("GDAL route DEM coverage returned an invalid value") from exc
    valid_count = sum(
        1
        for value in values
        if math.isfinite(value)
        and (
            nodata_value is None
            or not math.isclose(value, nodata_value, rel_tol=0.0, abs_tol=1e-6)
        )
    )
    nodata_count = expected_count - valid_count
    return {
        "sampled_route_point_count": expected_count,
        "valid_route_point_count": valid_count,
        "nodata_route_point_count": nodata_count,
        "valid_route_point_percent": round(valid_count * 100 / expected_count, 4),
        "complete_route_point_coverage": nodata_count == 0,
    }


def _run_gdal(
    *,
    dem_path: Path,
    output_dir: Path,
    target_srs: str,
    window: dict[str, float | int],
    metrics_root: Path,
    command_reports: list[dict[str, Any]],
    timeout_s: float,
) -> dict[str, Any]:
    crop = output_dir / "gdal_route_corridor_dem.tif"
    slope = output_dir / "gdal_slope.tif"
    hillshade = output_dir / "gdal_hillshade.tif"
    contours = output_dir / "gdal_contours.geojson"
    commands = [
        (
            "gdal_translate_crop",
            [
                "gdal_translate",
                "-srcwin",
                *[str(value) for value in window["source_window"]],
                "-of",
                "GTiff",
                "-co",
                "TILED=YES",
                "-co",
                "COMPRESS=DEFLATE",
                str(dem_path),
                str(crop),
            ],
        ),
        (
            "gdaldem_slope",
            ["gdaldem", "slope", str(crop), str(slope), "-compute_edges"],
        ),
        (
            "gdaldem_hillshade",
            ["gdaldem", "hillshade", str(crop), str(hillshade), "-compute_edges"],
        ),
        (
            "gdal_contour_20m",
            ["gdal_contour", "-a", "elevation_m", "-i", "20", str(crop), str(contours)],
        ),
    ]
    executions = []
    for label, command in commands:
        execution = _record(
            command_reports,
            _execute_command(
                label=label,
                command=command,
                metrics_root=metrics_root,
                timeout_s=timeout_s,
            ),
        )
        executions.append(execution.report())
    _require_files((crop, slope, hillshade, contours), backend="GDAL")
    return {
        "status": "completed",
        "processing_executed": True,
        "algorithms": ["gdal_translate", "gdaldem:slope", "gdaldem:hillshade", "gdal_contour"],
        "crop_ref": str(crop),
        "artifacts": [_file_summary(path) for path in (crop, slope, hillshade, contours)],
        "commands": executions,
        "authority": _candidate_authority(),
    }


def _run_grass(
    *,
    dem_path: Path,
    output_dir: Path,
    metrics_root: Path,
    command_reports: list[dict[str, Any]],
    timeout_s: float,
) -> dict[str, Any]:
    location = output_dir / "grassdb" / "scout_benchmark"
    mapset = location / "PERMANENT"
    slope = output_dir / "grass_slope.tif"
    aspect = output_dir / "grass_aspect.tif"
    landforms = output_dir / "grass_geomorphon_landforms.tif"
    accumulation = output_dir / "grass_flow_accumulation.tif"
    commands = [
        ("grass_create_project", ["grass", "-c", str(dem_path), "-e", str(location)]),
        (
            "grass_import_dem",
            [
                "grass",
                str(mapset),
                "--exec",
                "r.in.gdal",
                f"input={dem_path}",
                "output=dem",
                "--overwrite",
            ],
        ),
        (
            "grass_region",
            ["grass", str(mapset), "--exec", "g.region", "raster=dem"],
        ),
        (
            "grass_slope_aspect",
            [
                "grass",
                str(mapset),
                "--exec",
                "r.slope.aspect",
                "elevation=dem",
                "slope=slope",
                "aspect=aspect",
                "format=degrees",
                "precision=FCELL",
                "--overwrite",
            ],
        ),
        (
            "grass_geomorphon",
            [
                "grass",
                str(mapset),
                "--exec",
                "r.geomorphon",
                "elevation=dem",
                "forms=landforms",
                "search=10",
                "skip=0",
                "flat=1",
                "--overwrite",
            ],
        ),
        (
            "grass_watershed",
            [
                "grass",
                str(mapset),
                "--exec",
                "r.watershed",
                "elevation=dem",
                "accumulation=accumulation",
                "drainage=drainage",
                "threshold=50",
                "--overwrite",
            ],
        ),
        (
            "grass_export_slope",
            [
                "grass",
                str(mapset),
                "--exec",
                "r.out.gdal",
                "input=slope",
                f"output={slope}",
                "format=GTiff",
                "createopt=COMPRESS=DEFLATE",
                "--overwrite",
            ],
        ),
        (
            "grass_export_aspect",
            [
                "grass",
                str(mapset),
                "--exec",
                "r.out.gdal",
                "input=aspect",
                f"output={aspect}",
                "format=GTiff",
                "createopt=COMPRESS=DEFLATE",
                "--overwrite",
            ],
        ),
        (
            "grass_export_geomorphon",
            [
                "grass",
                str(mapset),
                "--exec",
                "r.out.gdal",
                "input=landforms",
                f"output={landforms}",
                "format=GTiff",
                "createopt=COMPRESS=DEFLATE",
                "--overwrite",
            ],
        ),
        (
            "grass_export_accumulation",
            [
                "grass",
                str(mapset),
                "--exec",
                "r.out.gdal",
                "input=accumulation",
                f"output={accumulation}",
                "format=GTiff",
                "createopt=COMPRESS=DEFLATE",
                "--overwrite",
            ],
        ),
    ]
    executions = []
    for label, command in commands:
        execution = _record(
            command_reports,
            _execute_command(
                label=label,
                command=command,
                metrics_root=metrics_root,
                timeout_s=timeout_s,
            ),
        )
        executions.append(execution.report())
    _require_files((slope, aspect, landforms, accumulation), backend="GRASS")
    return {
        "status": "completed",
        "processing_executed": True,
        "algorithms": ["r.slope.aspect", "r.geomorphon", "r.watershed"],
        "artifacts": [_file_summary(path) for path in (slope, aspect, landforms, accumulation)],
        "commands": executions,
        "authority": _candidate_authority(),
    }


def _run_qgis_mcp(
    *,
    project_id: str,
    run_id: str,
    points: list[list[float]],
    dem_path: Path,
    route_gpx: Path,
    source_root: Path,
    output_dir: Path,
    corridor_m: float,
    metadata: dict[str, Any],
    timeout_s: float,
    workflow_id: str,
) -> dict[str, Any]:
    try:
        from qgis_spatial_contracts import QgisBackendAvailability
        from qgis_worker import QgisWorkerConfig, QgisWorkerService
        from qgis_worker_contracts import QgisWorkerWorkflowRequest
    except ImportError as exc:
        raise BenchmarkError("Scout QGIS worker modules are unavailable") from exc
    server_root = Path("/opt/qgis-plugins/qgis_agent_mcp/_server")
    if not server_root.is_dir():
        raise BenchmarkError("QGIS Agent MCP bundled server is unavailable")
    worker_root = output_dir / "qgis-worker"
    service = QgisWorkerService(
        config=QgisWorkerConfig(
            enabled=True,
            auth_token=secrets.token_urlsafe(32),
            root=worker_root,
            source_roots=(source_root, output_dir),
            timeout_s=timeout_s,
            poll_interval_s=0.25,
            request_max_bytes=2 * 1024 * 1024,
            mcp_command=("python3", "-m", "qgis_mcp"),
            mcp_pythonpath=str(server_root),
        )
    )
    try:
        backend_status = service.status()
        if backend_status.availability is not QgisBackendAvailability.AVAILABLE:
            raise BenchmarkError(
                "QGIS MCP backend is unavailable: "
                + backend_status.model_dump_json(exclude_none=True)
            )
        route_geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": _candidate_authority(),
                    "geometry": {"type": "LineString", "coordinates": points},
                }
            ],
        }
        request = QgisWorkerWorkflowRequest(
            workflow_id=workflow_id,
            project_id=project_id,
            request_id=f"benchmark:{run_id}",
            requested_by="scout_pi_gis_benchmark",
            corridor_m=corridor_m,
            route_geojson=route_geojson,
            dem_refs=[str(dem_path)],
            source_refs=[str(route_gpx), str(dem_path)],
            source_hashes={
                str(route_gpx): _sha256(route_gpx),
                str(dem_path): _sha256(dem_path),
            },
            source_resolution={
                "x_m": metadata["pixel_size"][0],
                "y_m": metadata["pixel_size"][1],
                "adds_source_resolution": False,
            },
        )
        queued = service.start(request)
        deadline = time.monotonic() + timeout_s
        current = queued
        while _enum_value(current.state) not in _TERMINAL_STATES:
            if time.monotonic() >= deadline:
                service.cancel(current.worker_run_id, requested_by="benchmark_timeout")
                raise BenchmarkError("QGIS MCP workflow timed out")
            time.sleep(0.25)
            current = service.get(current.worker_run_id)
        payload = current.model_dump(mode="json")
        if _enum_value(current.state) != "completed" or current.result is None:
            raise BenchmarkError(
                "QGIS MCP workflow failed: "
                + json.dumps(payload.get("error"), ensure_ascii=False, sort_keys=True)
            )
        return {
            "status": "completed",
            "workflow_id": workflow_id,
            "mcp_invoked": True,
            "qgis_processing_executed": True,
            "render_completed": current.render_status == "completed",
            "worker_run_id": current.worker_run_id,
            "worker_run_ref": str(worker_root / "runs" / current.worker_run_id / "run.json"),
            "qgis_version": current.result.qgis_version,
            "qgis_mcp_plugin_version": current.result.qgis_mcp_plugin_version,
            "processing_algorithms": current.result.processing_algorithms,
            "artifacts": [artifact.model_dump(mode="json") for artifact in current.result.artifacts],
            "review": {
                "processing_status": current.processing_status,
                "render_status": current.render_status,
                "visual_review_status": current.visual_review_status,
                "human_review_status": current.human_review_status,
            },
            "authority": _candidate_authority(),
        }
    finally:
        service.close()


def _record(
    reports: list[dict[str, Any]], execution: CommandExecution
) -> CommandExecution:
    reports.append(execution.report())
    return execution


def _require_files(paths: tuple[Path, ...], *, backend: str) -> None:
    missing = [str(path) for path in paths if not path.is_file() or path.stat().st_size == 0]
    if missing:
        raise BenchmarkError(f"{backend} did not create required artifacts: {missing}")


def _file_summary(path: Path) -> dict[str, Any]:
    return {
        "ref": str(path),
        "sha256": _sha256(path),
        "byte_count": path.stat().st_size,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "operational": False,
        "adds_source_resolution": False,
    }


def _artifact_inventory(output_dir: Path, report_path: Path) -> list[dict[str, Any]]:
    names = {
        "gdal_route_corridor_dem.tif",
        "gdal_slope.tif",
        "gdal_hillshade.tif",
        "gdal_contours.geojson",
        "grass_slope.tif",
        "grass_aspect.tif",
        "grass_geomorphon_landforms.tif",
        "grass_flow_accumulation.tif",
        "slope.tif",
        "qgis_render_preview.png",
    }
    paths = sorted(
        path
        for path in output_dir.rglob("*")
        if path.is_file() and path.name in names and path != report_path
    )
    return [_file_summary(path) for path in paths]


def _host_summary() -> dict[str, Any]:
    model_path = Path("/proc/device-tree/model")
    model = "unavailable"
    if model_path.is_file():
        try:
            model = model_path.read_text(encoding="utf-8").rstrip("\x00").strip()
        except OSError:
            pass
    return {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "model": model,
        "is_raspberry_pi": "raspberry pi" in model.casefold(),
    }


def _resource_snapshot() -> dict[str, Any]:
    result: dict[str, Any] = {"recorded_at": _now_iso()}
    temperature = Path("/sys/class/thermal/thermal_zone0/temp")
    try:
        result["cpu_temperature_c"] = round(float(temperature.read_text().strip()) / 1000, 1)
    except (OSError, ValueError):
        result["cpu_temperature_c"] = None
    try:
        values = {}
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, value = line.split(":", 1)
            if key in {"MemAvailable", "SwapTotal", "SwapFree"}:
                values[key] = int(value.strip().split()[0]) * 1024
        result.update(
            {
                "memory_available_bytes": values.get("MemAvailable"),
                "swap_total_bytes": values.get("SwapTotal"),
                "swap_used_bytes": (
                    values["SwapTotal"] - values["SwapFree"]
                    if "SwapTotal" in values and "SwapFree" in values
                    else None
                ),
            }
        )
    except (OSError, ValueError):
        result.update(
            {
                "memory_available_bytes": None,
                "swap_total_bytes": None,
                "swap_used_bytes": None,
            }
        )
    return result


def _time_max_rss(path: Path) -> int | None:
    try:
        values = path.read_text(encoding="utf-8").strip().split("\t")
        return int(values[1]) if len(values) >= 2 else None
    except (OSError, ValueError):
        return None


def _safe_label(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value)[:120]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_report(path: Path, report: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def _error_code(exc: Exception) -> str:
    message = str(exc).casefold()
    if "timed out" in message:
        return "WORKFLOW_INTERRUPTED"
    if "crs" in message or "epsg" in message:
        return "CRS_UNRESOLVED"
    if "qgis mcp" in message:
        return "MCP_UNAVAILABLE"
    if "grass" in message or "gdal" in message or "processing" in message:
        return "PROCESSING_FAILED"
    if "route" in message or "gpx" in message or "cell limit" in message:
        return "INVALID_INPUT"
    return "UNKNOWN"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run bounded real GDAL, GRASS, and QGIS MCP terrain processing on Scout inputs."
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--route-gpx", required=True, type=Path)
    parser.add_argument("--dem", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--corridor-m", type=float, default=500.0)
    parser.add_argument("--max-cells", type=int, default=4_000_000)
    parser.add_argument("--timeout-s", type=float, default=600.0)
    parser.add_argument(
        "--qgis-workflow",
        choices=sorted(_QGIS_WORKFLOW_IDS),
        default="terrain_context_preview.v1",
    )
    args = parser.parse_args()
    try:
        report, report_path = run_benchmark(
            project_id=args.project_id,
            route_gpx=args.route_gpx,
            dem_path=args.dem,
            output_root=args.output_root,
            source_root=args.source_root,
            run_id=args.run_id,
            corridor_m=args.corridor_m,
            max_cells=args.max_cells,
            timeout_s=args.timeout_s,
            qgis_workflow_id=args.qgis_workflow,
        )
    except (BenchmarkError, OSError, ValueError) as exc:
        print(
            json.dumps(
                {"status": "failed", "error": str(exc), "type": type(exc).__name__},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "status": report["status"],
                "run_id": report["run_id"],
                "report": str(report_path),
                "qgis_worker_run_id": report.get("qgis_mcp", {}).get("worker_run_id"),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
