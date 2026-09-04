"""Workspace-owned, source-aligned DEM preparation; no route or safety authority."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceDemError(ValueError):
    pass


class WorkspaceDemConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_analysis_margin_m: float = Field(
        default=5000, ge=0, le=5000, allow_inf_nan=False
    )
    grid_guard_cells: int = Field(default=2, ge=2, le=10)


class WorkspaceDemManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["scout_workspace_terrain_dem.v1"] = (
        "scout_workspace_terrain_dem.v1"
    )
    project_id: str
    authority: Literal["candidate_only"] = "candidate_only"
    runtime_safety_truth: Literal[False] = False
    adds_source_resolution: Literal[False] = False
    crs: Literal["EPSG:3826"] = "EPSG:3826"
    resolution_m: float = Field(gt=0, allow_inf_nan=False)
    max_analysis_margin_m: float = Field(ge=0, le=5000, allow_inf_nan=False)
    grid_guard_cells: int
    route_bounds: dict[str, float]
    bounds: dict[str, float]
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    finite_cell_count: int = Field(gt=0)
    nodata_cell_count: Literal[0] = 0
    dem_ref: str
    dem_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_ref: str
    parent_ref: str
    parent_dem_ref: str
    coverage_ref: str
    source_ref: str
    source_hashes: dict[str, str]
    crs_resolution: dict[str, str] = Field(default_factory=dict)
    created_at: str
    gdal_version: str
    commands: list[list[str]]


class WorkspaceDemAdapter(Protocol):
    def inspect(self, path: Path, *, statistics: bool = False) -> dict[str, Any]: ...
    def clip(
        self,
        source: Path,
        output: Path,
        *,
        window: tuple[float, ...],
        crs_override: str | None = None,
    ) -> list[str]: ...
    def version(self) -> str: ...


class GdalWorkspaceDemAdapter:
    """Fixed local GDAL operations, with no shell or source reprojection."""

    def __init__(self):
        self.commands: list[list[str]] = []

    def _run(self, tool: str, args: list[str]) -> str:
        if tool not in {"gdalinfo", "gdal_translate"}:
            raise WorkspaceDemError("Unsupported DEM preparation operation")
        candidates = [
            shutil.which(tool),
            f"/Applications/QGIS-LTR.app/Contents/MacOS/{tool}",
        ]
        executable = next((p for p in candidates if p and Path(p).is_file()), None)
        if executable is None:
            raise WorkspaceDemError(f"DEM preparation dependency unavailable: {tool}")
        environment = dict(os.environ)
        if executable.startswith("/Applications/QGIS-LTR.app/"):
            environment.setdefault(
                "PROJ_LIB", "/Applications/QGIS-LTR.app/Contents/Resources/qgis/proj"
            )
            environment.setdefault(
                "GDAL_DATA", "/Applications/QGIS-LTR.app/Contents/Resources/qgis/gdal"
            )
        try:
            result = subprocess.run(
                [executable, *args],
                capture_output=True,
                text=True,
                check=True,
                env=environment,
                shell=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise WorkspaceDemError(f"{tool} DEM preparation failed") from exc
        self.commands.append([executable, *args])
        return result.stdout

    def inspect(self, path: Path, *, statistics: bool = False) -> dict[str, Any]:
        metadata = json.loads(self._run("gdalinfo", ["-json", str(path)]))
        if not statistics:
            return metadata
        nodata = metadata["bands"][0].get("noDataValue")
        nodata = float(nodata) if nodata is not None else None
        finite = missing = 0
        # Count actual native cells. Rounded GDAL valid-percent statistics are insufficient.
        with tempfile.TemporaryDirectory(prefix="scout-dem-inventory-") as temporary:
            table = Path(temporary) / "cells.xyz"
            self._run(
                "gdal_translate",
                [
                    "-q",
                    "-of",
                    "XYZ",
                    "-co",
                    "COLUMN_SEPARATOR=,",
                    "-co",
                    "ADD_HEADER_LINE=YES",
                    str(path),
                    str(table),
                ],
            )
            with table.open(newline="") as stream:
                for row in csv.DictReader(stream):
                    value = float(row["Z"])
                    if math.isfinite(value) and (nodata is None or value != nodata):
                        finite += 1
                    else:
                        missing += 1
        return {
            **metadata,
            "inventory": {"finite_cell_count": finite, "nodata_cell_count": missing},
        }

    def clip(
        self,
        source: Path,
        output: Path,
        *,
        window: tuple[float, ...],
        crs_override: str | None = None,
    ) -> list[str]:
        if crs_override not in (None, "EPSG:3826"):
            raise WorkspaceDemError("Unsupported provider CRS normalization")
        args = [
            "-q",
            "-epo",
            "-of",
            "GTiff",
            "-projwin",
            *map(str, window),
            *(["-a_srs", crs_override] if crs_override else []),
            "-co",
            "TILED=YES",
            "-co",
            "COMPRESS=DEFLATE",
            str(source),
            str(output),
        ]
        self._run("gdal_translate", args)
        return ["gdal_translate", *args]

    def version(self) -> str:
        return self._run("gdalinfo", ["--version"]).strip()


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _path(root: Path, ref: str) -> Path:
    path = (root / ref).resolve()
    if Path(ref).is_absolute() or not path.is_relative_to(root.resolve()):
        raise WorkspaceDemError("DEM artifact must stay inside its workspace")
    return path


def _bounds(value: dict[str, Any]) -> dict[str, float]:
    result = {key: float(value[key]) for key in ("min_x", "min_y", "max_x", "max_y")}
    if (
        not all(math.isfinite(v) for v in result.values())
        or result["min_x"] >= result["max_x"]
        or result["min_y"] >= result["max_y"]
    ):
        raise WorkspaceDemError("Invalid DEM extent")
    return result


def _grid(
    metadata: dict[str, Any], resolution_m: float
) -> tuple[list[float], list[int], dict[str, float]]:
    transform = list(map(float, metadata["geoTransform"]))
    size = list(map(int, metadata["size"]))
    bands = metadata.get("bands", [])
    epsg = metadata.get("stac", {}).get("proj:epsg")
    if epsg != 3826:
        raise WorkspaceDemError("DEM CRS must be verified EPSG:3826")
    if (
        len(transform) != 6
        or len(size) != 2
        or min(size) <= 0
        or len(bands) != 1
        or not all(math.isfinite(v) for v in transform)
        or transform[2] != 0
        or transform[4] != 0
        or not math.isclose(transform[1], resolution_m)
        or not math.isclose(transform[5], -resolution_m)
        or bands[0].get("mask", {}).get("flags", [])
        not in ([], ["ALL_VALID"], ["NODATA"])
    ):
        raise WorkspaceDemError("DEM native grid, mask or resolution is unsupported")
    return (
        transform,
        size,
        _bounds(
            {
                "min_x": transform[0],
                "max_y": transform[3],
                "max_x": transform[0] + size[0] * resolution_m,
                "min_y": transform[3] - size[1] * resolution_m,
            }
        ),
    )


def _resolve_source_crs(
    metadata: dict[str, Any], evidence_path: Path | None
) -> dict[str, str]:
    stac = metadata.get("stac", {})
    if stac.get("proj:epsg") == 3826:
        return {"method": "raster_epsg", "crs": "EPSG:3826"}
    if stac.get("proj:epsg") is not None or evidence_path is None:
        raise WorkspaceDemError("DEM CRS must be verified EPSG:3826")
    if not evidence_path.is_file() or evidence_path.stat().st_size > 1024 * 1024:
        raise WorkspaceDemError("Provider CRS metadata is unavailable")
    metadata_bytes = evidence_path.read_bytes()
    try:
        xml = ET.fromstring(metadata_bytes)
    except ET.ParseError as exc:
        raise WorkspaceDemError("Provider CRS metadata is invalid") from exc
    codes = [
        e.text.strip().split("(")[0]
        for e in xml.findall(".//{*}referenceSystemInfo//{*}code/{*}CharacterString")
        if e.text
    ]
    projection = stac.get("proj:projjson", {})
    conversion = projection.get("conversion", {})
    parameters = {
        p.get("id", {}).get("code"): (p.get("value"), p.get("unit"))
        for p in conversion.get("parameters", [])
    }
    axes = projection.get("coordinate_system", {}).get("axis", [])
    # Some provider rasters have an unidentifiable WGS84/TM121 header. Resolve
    # only from registered ISO metadata AND identical projection parameters.
    if (
        codes != ["EPSG:3826"]
        or projection.get("type") != "ProjectedCRS"
        or conversion.get("method", {}).get("id", {}).get("code") != 9807
        or parameters
        != {
            8801: (0, "degree"),
            8802: (121, "degree"),
            8805: (0.9999, "unity"),
            8806: (250000, "metre"),
            8807: (0, "metre"),
        }
        or [(a.get("direction"), a.get("unit")) for a in axes]
        != [("east", "metre"), ("north", "metre")]
        or projection.get("base_crs", {}).get("id")
        != {"authority": "EPSG", "code": 4326}
    ):
        raise WorkspaceDemError("Raster CRS and provider metadata cannot be reconciled")
    return {
        "method": "registered_provider_metadata_tm121",
        "crs": "EPSG:3826",
        "metadata_path": str(evidence_path),
        "metadata_sha256": hashlib.sha256(metadata_bytes).hexdigest(),
        "original_wkt": stac.get("proj:wkt2", ""),
        "normalization": "derived_clip_tag_only_no_coordinate_or_pixel_resampling",
    }


def _contains(outer: dict[str, float], inner: dict[str, float]) -> bool:
    return all(outer[k] <= inner[k] for k in ("min_x", "min_y")) and all(
        outer[k] >= inner[k] for k in ("max_x", "max_y")
    )


def load_workspace_dem(
    project_root: Path,
    *,
    manifest_ref: str,
    expected_hashes: dict[str, str],
    project_id: str,
) -> WorkspaceDemManifest:
    result = WorkspaceDemManifest.model_validate_json(
        _path(project_root, manifest_ref).read_bytes()
    )
    if (
        result.project_id != project_id
        or result.manifest_ref != manifest_ref
        or result.source_hashes != expected_hashes
    ):
        raise WorkspaceDemError(
            "Workspace DEM source binding changed; prepare it again"
        )
    if _sha(_path(project_root, result.dem_ref)) != result.dem_sha256:
        raise WorkspaceDemError("Workspace DEM hash mismatch")
    for ref, expected in expected_hashes.items():
        if "#" not in ref and _sha(_path(project_root, ref)) != expected:
            raise WorkspaceDemError("Workspace DEM parent binding changed")
    crs_ref = result.crs_resolution.get("metadata_ref")
    if (
        result.crs_resolution.get("method") == "registered_provider_metadata_tm121"
        and not crs_ref
    ):
        raise WorkspaceDemError("Workspace DEM CRS evidence snapshot is unavailable")
    if crs_ref and _sha(_path(project_root, crs_ref)) != result.crs_resolution.get(
        "metadata_sha256"
    ):
        raise WorkspaceDemError("Workspace DEM CRS evidence hash mismatch")
    if result.finite_cell_count != result.width * result.height:
        raise WorkspaceDemError("Workspace DEM inventory is incomplete")
    _bounds(result.bounds)
    return result


def require_analysis_coverage(
    prepared: WorkspaceDemManifest,
    *,
    projected_points: list[tuple[float, float]],
    margin_m: float,
) -> None:
    if (
        not projected_points
        or not math.isfinite(margin_m)
        or margin_m < 0
        or margin_m > prepared.max_analysis_margin_m
        or not all(math.isfinite(v) for point in projected_points for v in point)
    ):
        raise WorkspaceDemError(
            "Requested analysis extent exceeds the prepared DEM policy"
        )
    resolution = prepared.resolution_m
    # Match the worker's projected, outward-aligned request; retain one cell for its source-grid clip.
    bounds = {
        "min_x": math.floor(
            (min(x for x, _ in projected_points) - margin_m) / resolution
        )
        * resolution
        - resolution,
        "min_y": math.floor(
            (min(y for _, y in projected_points) - margin_m) / resolution
        )
        * resolution
        - resolution,
        "max_x": math.ceil(
            (max(x for x, _ in projected_points) + margin_m) / resolution
        )
        * resolution
        + resolution,
        "max_y": math.ceil(
            (max(y for _, y in projected_points) + margin_m) / resolution
        )
        * resolution
        + resolution,
    }
    if not _contains(prepared.bounds, bounds):
        raise WorkspaceDemError(
            "A/B plus the analysis extent exceeds the workspace DEM; expand DEM preparation first"
        )


def prepare_workspace_dem(
    *,
    project_root: Path,
    project_id: str,
    source_path: Path,
    source_ref: str,
    source_hashes: dict[str, str],
    parent_ref: str,
    parent_dem_ref: str,
    coverage_ref: str,
    route_bounds: dict[str, float],
    resolution_m: float,
    crs_evidence_path: Path | None = None,
    config: WorkspaceDemConfig | None = None,
    adapter: WorkspaceDemAdapter | None = None,
) -> WorkspaceDemManifest:
    config = config or WorkspaceDemConfig()
    route = _bounds(route_bounds)
    if not math.isfinite(resolution_m) or not 0 < resolution_m <= 1000:
        raise WorkspaceDemError("DEM resolution is unavailable")
    identity = {
        "schema": "scout_workspace_terrain_dem.v1",
        "project_id": project_id,
        "source_hashes": source_hashes,
        "route_bounds": route,
        "resolution_m": resolution_m,
        "config": config.model_dump(),
        "parent_ref": parent_ref,
        "parent_dem_ref": parent_dem_ref,
        "crs_evidence_sha256": _sha(crs_evidence_path)
        if crs_evidence_path and crs_evidence_path.is_file()
        else None,
    }
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    base_ref = f"outputs/terrain/dem/{key}"
    manifest_ref = f"{base_ref}/manifest.json"
    if _path(project_root, manifest_ref).is_file():
        return load_workspace_dem(
            project_root,
            manifest_ref=manifest_ref,
            expected_hashes=source_hashes,
            project_id=project_id,
        )
    if _sha(source_path) != source_hashes.get(source_ref):
        raise WorkspaceDemError("Source DEM hash changed")
    for ref in (parent_ref, parent_dem_ref, coverage_ref):
        if _sha(_path(project_root, ref)) != source_hashes.get(ref):
            raise WorkspaceDemError("DEM preparation source binding is incomplete")
    adapter = adapter or GdalWorkspaceDemAdapter()
    metadata = adapter.inspect(source_path)
    crs_resolution = _resolve_source_crs(metadata, crs_evidence_path)
    normalized_metadata = {
        **metadata,
        "stac": {**metadata.get("stac", {}), "proj:epsg": 3826},
    }
    transform, _, source_bounds = _grid(normalized_metadata, resolution_m)
    buffer = config.max_analysis_margin_m + config.grid_guard_cells * resolution_m
    aligned = {}
    for key, origin in (
        ("min_x", transform[0]),
        ("max_x", transform[0]),
        ("min_y", transform[3]),
        ("max_y", transform[3]),
    ):
        rounding = math.floor if key.startswith("min") else math.ceil
        offset = -buffer if key.startswith("min") else buffer
        aligned[key] = (
            origin
            + rounding((route[key] + offset - origin) / resolution_m) * resolution_m
        )
    if not _contains(source_bounds, aligned):
        raise WorkspaceDemError("Source DEM does not cover the buffered route extent")
    window = tuple(aligned[k] for k in ("min_x", "max_y", "max_x", "min_y"))
    target_dir = _path(project_root, base_ref)
    target_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".prepare-", dir=target_dir) as temporary:
        output = Path(temporary) / "dem.tif"
        command = adapter.clip(
            source_path,
            output,
            window=window,
            crs_override="EPSG:3826"
            if crs_resolution["method"] != "raster_epsg"
            else None,
        )
        inspection = adapter.inspect(output, statistics=True)
        _, size, actual_bounds = _grid(inspection, resolution_m)
        inventory = inspection["inventory"]
        if (
            actual_bounds != aligned
            or inventory["nodata_cell_count"] != 0
            or inventory["finite_cell_count"] != size[0] * size[1]
        ):
            raise WorkspaceDemError(
                "Buffered workspace DEM contains NoData or an incomplete grid"
            )
        if _sha(source_path) != source_hashes[source_ref]:
            raise WorkspaceDemError("Source DEM changed during preparation")
        for ref in (parent_ref, parent_dem_ref, coverage_ref):
            if _sha(_path(project_root, ref)) != source_hashes[ref]:
                raise WorkspaceDemError("DEM source binding changed during preparation")
        dem_ref = f"{base_ref}/dem.tif"
        if crs_resolution.get("metadata_sha256"):
            evidence_bytes = crs_evidence_path.read_bytes()
            if (
                hashlib.sha256(evidence_bytes).hexdigest()
                != crs_resolution["metadata_sha256"]
            ):
                raise WorkspaceDemError(
                    "Provider CRS metadata changed during preparation"
                )
            evidence_ref = f"{base_ref}/crs_evidence.xml"
            _path(project_root, evidence_ref).write_bytes(evidence_bytes)
            crs_resolution = {**crs_resolution, "metadata_ref": evidence_ref}
        result = WorkspaceDemManifest(
            project_id=project_id,
            resolution_m=resolution_m,
            max_analysis_margin_m=config.max_analysis_margin_m,
            grid_guard_cells=config.grid_guard_cells,
            route_bounds=route,
            bounds=actual_bounds,
            width=size[0],
            height=size[1],
            finite_cell_count=inventory["finite_cell_count"],
            dem_ref=dem_ref,
            dem_sha256=_sha(output),
            manifest_ref=manifest_ref,
            parent_ref=parent_ref,
            parent_dem_ref=parent_dem_ref,
            coverage_ref=coverage_ref,
            source_ref=source_ref,
            source_hashes=source_hashes,
            crs_resolution=crs_resolution,
            created_at=datetime.now(timezone.utc).isoformat(),
            gdal_version=adapter.version(),
            commands=getattr(adapter, "commands", [command]),
        )
        output.replace(_path(project_root, dem_ref))
        receipt = Path(temporary) / "manifest.json"
        receipt.write_text(result.model_dump_json(indent=2) + "\n")
        receipt.replace(_path(project_root, manifest_ref))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare a buffered workspace-owned DEM without rebuilding routes or R4 review"
    )
    parser.add_argument("--project-root", type=Path, required=True)
    args = parser.parse_args()
    from qgis_spatial_backend import QgisSpatialBackend

    result = QgisSpatialBackend.from_env().prepare_workspace_terrain_dem(
        project_root=args.project_root
    )
    print(json.dumps(result, indent=2))
    if result["status"] != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
