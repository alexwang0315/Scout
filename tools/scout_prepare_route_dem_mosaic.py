from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


SCHEMA_VERSION = "scout_route_dem_mosaic.v0_1"
_TILE_ID = re.compile(r"^[0-9]{8}$")
_CRS = "EPSG:3826"
_RESOLUTION_M = 20.0


class MosaicPreparationError(RuntimeError):
    pass


@dataclass(frozen=True)
class MosaicPlan:
    coverage_summary: Path
    source_roots: tuple[Path, ...]
    tile_ids: tuple[str, ...]
    source_identities: tuple[str, ...]
    grid_paths: tuple[Path, ...]
    header_paths: tuple[Path, ...]
    min_x: float
    min_y: float
    max_x: float
    max_y: float
    resolution_m: float
    width: int
    height: int
    cell_count: int
    corridor_m: float

    @property
    def source_tile_count(self) -> int:
        return len(self.tile_ids)

    @property
    def unique_tile_id_count(self) -> int:
        return len(set(self.tile_ids))


def candidate_authority() -> dict[str, bool]:
    return {
        "benchmark_only": True,
        "candidate_only": True,
        "operational": False,
        "runtime_safety_truth": False,
    }


def load_mosaic_plan(
    *,
    coverage_summary: Path,
    source_root: Path | None = None,
    source_roots: Sequence[Path] | None = None,
    corridor_m: float,
    max_cells: int,
    max_sources: int,
) -> MosaicPlan:
    if not math.isfinite(corridor_m) or not 0 <= corridor_m <= 10_000:
        raise MosaicPreparationError("corridor must be between 0 and 10000 metres")
    if not 1 <= max_cells <= 100_000_000:
        raise MosaicPreparationError("max cell limit must be between 1 and 100000000")
    if not 1 <= max_sources <= 1024:
        raise MosaicPreparationError("max source limit must be between 1 and 1024")

    summary_path = coverage_summary.expanduser().resolve(strict=True)
    bounded_roots = _bounded_source_roots(
        source_root=source_root,
        source_roots=source_roots,
    )
    try:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise MosaicPreparationError("coverage summary is unreadable") from exc
    if not isinstance(payload, dict):
        raise MosaicPreparationError("coverage summary must contain an object")

    raw_tiles = payload.get("candidate_tiles")
    if not isinstance(raw_tiles, list) or not raw_tiles:
        raise MosaicPreparationError("coverage summary has no candidate tiles")
    if len(raw_tiles) > max_sources:
        raise MosaicPreparationError(
            f"source limit exceeded: {len(raw_tiles)} > {max_sources}"
        )

    tile_ids: list[str] = []
    source_identities: list[str] = []
    grid_paths: list[Path] = []
    header_paths: list[Path] = []
    seen: set[str] = set()
    for raw in raw_tiles:
        if not isinstance(raw, dict):
            raise MosaicPreparationError("candidate tile must be an object")
        tile_id = raw.get("tile_id")
        if not isinstance(tile_id, str) or not _TILE_ID.fullmatch(tile_id):
            raise MosaicPreparationError("candidate tile has an invalid tile ID")
        _require_resolution(raw, tile_id)
        county = raw.get("county") if isinstance(raw.get("county"), str) else None
        bounded_root = _select_source_root(
            tile_id=tile_id,
            county=county,
            source_roots=bounded_roots,
        )
        source_label = county or bounded_root.name
        source_identity = f"{source_label}:{tile_id}"
        if source_identity in seen:
            raise MosaicPreparationError(
                f"duplicate candidate source identity: {source_identity}"
            )
        seen.add(source_identity)
        grid = (bounded_root / f"{tile_id}dem.grd").resolve(strict=True)
        header = (bounded_root / f"{tile_id}dem.hdr").resolve(strict=True)
        if grid.parent != bounded_root or header.parent != bounded_root:
            raise MosaicPreparationError("candidate tile escaped the bounded source root")
        if not grid.is_file() or grid.stat().st_size == 0:
            raise MosaicPreparationError(f"source grid is unavailable: {grid.name}")
        if not header.is_file() or header.stat().st_size == 0:
            raise MosaicPreparationError(f"source header is unavailable: {header.name}")
        if header.stat().st_size > 64 * 1024:
            raise MosaicPreparationError(f"source header exceeds size limit: {header.name}")
        tile_ids.append(tile_id)
        source_identities.append(source_identity)
        grid_paths.append(grid)
        header_paths.append(header)

    bbox = payload.get("route_bbox_twd97")
    if not isinstance(bbox, dict) or "3826" not in str(bbox.get("crs", "")):
        raise MosaicPreparationError("route bbox CRS is unresolved")
    values = {
        name: _finite_number(bbox.get(name), name)
        for name in ("min_x", "min_y", "max_x", "max_y")
    }
    if values["min_x"] >= values["max_x"] or values["min_y"] >= values["max_y"]:
        raise MosaicPreparationError("route bbox is empty or reversed")

    min_x = _align_floor(values["min_x"] - corridor_m, _RESOLUTION_M)
    min_y = _align_floor(values["min_y"] - corridor_m, _RESOLUTION_M)
    max_x = _align_ceil(values["max_x"] + corridor_m, _RESOLUTION_M)
    max_y = _align_ceil(values["max_y"] + corridor_m, _RESOLUTION_M)
    width = int(round((max_x - min_x) / _RESOLUTION_M))
    height = int(round((max_y - min_y) / _RESOLUTION_M))
    cells = width * height
    if width < 1 or height < 1:
        raise MosaicPreparationError("aligned route bbox has no raster cells")
    if cells > max_cells:
        raise MosaicPreparationError(f"cell limit exceeded: {cells} > {max_cells}")

    return MosaicPlan(
        coverage_summary=summary_path,
        source_roots=bounded_roots,
        tile_ids=tuple(tile_ids),
        source_identities=tuple(source_identities),
        grid_paths=tuple(grid_paths),
        header_paths=tuple(header_paths),
        min_x=min_x,
        min_y=min_y,
        max_x=max_x,
        max_y=max_y,
        resolution_m=_RESOLUTION_M,
        width=width,
        height=height,
        cell_count=cells,
        corridor_m=corridor_m,
    )


def build_gdalwarp_command(plan: MosaicPlan, output: Path) -> list[str]:
    target = output.expanduser().resolve(strict=False)
    if target.suffix.casefold() not in {".tif", ".tiff"}:
        raise MosaicPreparationError("mosaic output must be a GeoTIFF")
    return [
        "gdalwarp",
        "-overwrite",
        "-q",
        "-r",
        "near",
        "-s_srs",
        _CRS,
        "-t_srs",
        _CRS,
        "-te",
        _number(plan.min_x),
        _number(plan.min_y),
        _number(plan.max_x),
        _number(plan.max_y),
        "-tr",
        _number(plan.resolution_m),
        _number(plan.resolution_m),
        "-tap",
        "-ot",
        "Float32",
        "-dstnodata",
        "-9999",
        "-wm",
        "256",
        "-wo",
        "NUM_THREADS=1",
        "-co",
        "TILED=YES",
        "-co",
        "COMPRESS=DEFLATE",
        "-co",
        "BIGTIFF=IF_SAFER",
        *[str(path) for path in plan.grid_paths],
        str(target),
    ]


def prepare_mosaic(
    *,
    plan: MosaicPlan,
    output: Path,
    report_path: Path,
    timeout_s: float,
    initiated_by: str,
) -> dict[str, Any]:
    if not math.isfinite(timeout_s) or not 1 <= timeout_s <= 7200:
        raise MosaicPreparationError("timeout must be between 1 and 7200 seconds")
    target = output.expanduser().resolve(strict=False)
    report = report_path.expanduser().resolve(strict=False)
    if target.exists() or report.exists():
        raise MosaicPreparationError("mosaic output or report already exists")
    if target == report:
        raise MosaicPreparationError("mosaic output and report must differ")
    target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    report.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    temporary = target.with_name(f".{target.stem}.{os.getpid()}.tmp{target.suffix}")
    metrics = report.with_name(f".{report.stem}.{os.getpid()}.time.tsv")

    source_started = time.perf_counter_ns()
    source_hashes = {
        f"{identity}/{path.name}": _sha256(path)
        for identity, grid, header in zip(
            plan.source_identities,
            plan.grid_paths,
            plan.header_paths,
            strict=True,
        )
        for path in (grid, header)
    }
    hash_duration_ms = round((time.perf_counter_ns() - source_started) / 1_000_000, 3)
    command = build_gdalwarp_command(plan, temporary)
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": "scout_route_dem_mosaic_preparation",
        "status": "running",
        "created_at": _now_iso(),
        "initiated_by": initiated_by[:128],
        "authority": candidate_authority(),
        "input": {
            "coverage_summary": str(plan.coverage_summary),
            "coverage_summary_sha256": _sha256(plan.coverage_summary),
            "source_root": str(plan.source_roots[0]) if len(plan.source_roots) == 1 else None,
            "source_roots": [str(path) for path in plan.source_roots],
            "source_tile_count": plan.source_tile_count,
            "unique_tile_id_count": plan.unique_tile_id_count,
            "source_refs": [
                f"{identity}/{path.name}"
                for identity, path in zip(
                    plan.source_identities,
                    plan.grid_paths,
                    strict=True,
                )
            ],
            "source_hashes": source_hashes,
            "source_bytes": sum(
                path.stat().st_size for path in (*plan.grid_paths, *plan.header_paths)
            ),
            "provenance_hash_duration_ms": hash_duration_ms,
        },
        "output_contract": {
            "crs": _CRS,
            "resolution_m": plan.resolution_m,
            "width": plan.width,
            "height": plan.height,
            "cell_count": plan.cell_count,
            "bounds": [plan.min_x, plan.min_y, plan.max_x, plan.max_y],
            "corridor_m": plan.corridor_m,
            "adds_source_resolution": False,
        },
        "processing": {
            "algorithm": "gdalwarp",
            "parameters": {
                "resampling": "near",
                "working_memory_mb": 256,
                "threads": 1,
                "compression": "DEFLATE",
            },
            "command": command[:-1] + [str(target)],
            "timeout_s": timeout_s,
        },
        "resource_before": _resource_snapshot(),
        "review": {
            "processing_status": "running",
            "machine_review": "pending",
            "visual_review": "pending",
            "human_review": "pending",
        },
        "warnings": [
            "Mosaic preparation is execution evidence, not terrain or safety truth.",
            "Nearest-neighbour mosaicking adds no source resolution.",
            "EPSG:3826 is assigned from the bounded Scout coverage contract.",
        ],
    }
    _write_json(report, result)
    try:
        execution = _run_timed(command, timeout_s=timeout_s, metrics_path=metrics)
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise MosaicPreparationError("gdalwarp did not create a mosaic")
        inspection = _inspect_output(temporary, timeout_s=timeout_s)
        if inspection["size"] != [plan.width, plan.height]:
            raise MosaicPreparationError(
                f"mosaic size mismatch: {inspection['size']} != {[plan.width, plan.height]}"
            )
        temporary.replace(target)
        result["status"] = "completed"
        result["completed_at"] = _now_iso()
        result["processing"].update(execution)
        result["processing"]["inspection"] = inspection
        result["artifact"] = {
            "ref": str(target),
            "sha256": _sha256(target),
            "byte_count": target.stat().st_size,
            "artifact_type": "dem_route_bbox_mosaic",
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
            "adds_source_resolution": False,
        }
        result["review"]["processing_status"] = "completed"
        result["resource_after"] = _resource_snapshot()
        _write_json(report, result)
        return result
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        result["status"] = "failed"
        result["completed_at"] = _now_iso()
        result["review"]["processing_status"] = "failed"
        result["error"] = {
            "code": "DEM_MOSAIC_PREPARATION_FAILED",
            "type": type(exc).__name__,
            "message": str(exc),
        }
        result["resource_after"] = _resource_snapshot()
        _write_json(report, result)
        raise
    finally:
        metrics.unlink(missing_ok=True)


def _run_timed(
    command: list[str], *, timeout_s: float, metrics_path: Path
) -> dict[str, Any]:
    executable = shutil.which(command[0])
    if not executable:
        raise MosaicPreparationError(f"required executable is unavailable: {command[0]}")
    bounded = [executable, *command[1:]]
    timed = bounded
    if Path("/usr/bin/time").is_file():
        timed = [
            "/usr/bin/time",
            "-f",
            "%e\t%M\t%x",
            "-o",
            str(metrics_path),
            *bounded,
        ]
    started_at = _now_iso()
    started = time.perf_counter_ns()
    try:
        completed = subprocess.run(
            timed,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=timeout_s,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise MosaicPreparationError("gdalwarp timed out") from exc
    duration_ms = round((time.perf_counter_ns() - started) / 1_000_000, 3)
    if completed.returncode != 0:
        detail = " ".join(completed.stderr.strip().split())[-1500:]
        raise MosaicPreparationError(
            f"gdalwarp failed with exit {completed.returncode}: {detail}"
        )
    return {
        "started_at": started_at,
        "duration_ms": duration_ms,
        "max_rss_kb": _time_max_rss(metrics_path),
        "returncode": completed.returncode,
        "stdout_tail": completed.stdout[-2000:],
        "stderr_tail": completed.stderr[-2000:],
    }


def _inspect_output(path: Path, *, timeout_s: float) -> dict[str, Any]:
    executable = shutil.which("gdalinfo")
    if not executable:
        raise MosaicPreparationError("required executable is unavailable: gdalinfo")
    try:
        completed = subprocess.run(
            [executable, "-json", str(path)],
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=min(timeout_s, 120),
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise MosaicPreparationError("gdalinfo timed out") from exc
    if completed.returncode != 0:
        raise MosaicPreparationError("gdalinfo could not inspect the mosaic")
    try:
        payload = json.loads(completed.stdout)
        size = payload["size"]
        transform = payload["geoTransform"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise MosaicPreparationError("gdalinfo returned malformed metadata") from exc
    return {
        "size": [int(size[0]), int(size[1])],
        "geo_transform": [float(value) for value in transform],
        "band_count": len(payload.get("bands", [])),
        "driver": payload.get("driverShortName", "unavailable"),
    }


def _require_resolution(raw: dict[str, Any], tile_id: str) -> None:
    x = _finite_number(raw.get("resolution_x_m"), "resolution_x_m")
    y = _finite_number(raw.get("resolution_y_m"), "resolution_y_m")
    if not math.isclose(x, _RESOLUTION_M) or not math.isclose(y, _RESOLUTION_M):
        raise MosaicPreparationError(f"unsupported source resolution for tile {tile_id}")


def _bounded_source_roots(
    *,
    source_root: Path | None,
    source_roots: Sequence[Path] | None,
) -> tuple[Path, ...]:
    requested = [*(source_roots or ())]
    if source_root is not None:
        requested.insert(0, source_root)
    if not requested:
        raise MosaicPreparationError("at least one bounded source root is required")
    if len(requested) > 32:
        raise MosaicPreparationError("bounded source root limit exceeded")

    bounded: list[Path] = []
    seen: set[Path] = set()
    for requested_root in requested:
        resolved = requested_root.expanduser().resolve(strict=True)
        if not resolved.is_dir():
            raise MosaicPreparationError(f"source root is not a directory: {resolved}")
        if resolved in seen:
            continue
        seen.add(resolved)
        bounded.append(resolved)
    return tuple(bounded)


def _select_source_root(
    *,
    tile_id: str,
    county: str | None,
    source_roots: tuple[Path, ...],
) -> Path:
    available = [
        root
        for root in source_roots
        if (root / f"{tile_id}dem.grd").is_file()
        and (root / f"{tile_id}dem.hdr").is_file()
    ]
    if county:
        county_matches = [root for root in available if _county_from_root(root) == county]
        if len(county_matches) == 1:
            return county_matches[0]
        if len(county_matches) > 1:
            raise MosaicPreparationError(
                f"candidate source is ambiguous for county {county}: {tile_id}"
            )
    if len(available) == 1:
        return available[0]
    if not available:
        raise MosaicPreparationError(f"source grid is unavailable: {tile_id}dem.grd")
    raise MosaicPreparationError(
        f"candidate source root is ambiguous without a county match: {tile_id}"
    )


def _county_from_root(path: Path) -> str | None:
    match = re.search(r"分幅_(.+?)20MDEM", path.name)
    return match.group(1) if match else None


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise MosaicPreparationError(f"{name} must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise MosaicPreparationError(f"{name} must be numeric") from exc
    if not math.isfinite(parsed):
        raise MosaicPreparationError(f"{name} must be finite")
    return parsed


def _align_floor(value: float, resolution: float) -> float:
    return math.floor(value / resolution) * resolution


def _align_ceil(value: float, resolution: float) -> float:
    return math.ceil(value / resolution) * resolution


def _number(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resource_snapshot() -> dict[str, Any]:
    result: dict[str, Any] = {"recorded_at": _now_iso()}
    temperature = Path("/sys/class/thermal/thermal_zone0/temp")
    try:
        result["cpu_temperature_c"] = round(
            float(temperature.read_text(encoding="ascii").strip()) / 1000, 1
        )
    except (OSError, ValueError):
        result["cpu_temperature_c"] = None
    try:
        values: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            key, value = line.split(":", 1)
            if key in {"MemAvailable", "SwapTotal", "SwapFree"}:
                values[key] = int(value.strip().split()[0]) * 1024
        result["memory_available_bytes"] = values.get("MemAvailable")
        result["swap_total_bytes"] = values.get("SwapTotal")
        result["swap_used_bytes"] = (
            values["SwapTotal"] - values["SwapFree"]
            if "SwapTotal" in values and "SwapFree" in values
            else None
        )
    except (OSError, ValueError):
        result.update(
            memory_available_bytes=None,
            swap_total_bytes=None,
            swap_used_bytes=None,
        )
    return result


def _time_max_rss(path: Path) -> int | None:
    try:
        values = path.read_text(encoding="ascii").strip().split("\t")
        return int(values[1]) if len(values) >= 2 else None
    except (OSError, ValueError):
        return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare a bounded 20 m route-bbox DEM mosaic for Scout benchmarking."
    )
    parser.add_argument("--coverage-summary", required=True, type=Path)
    parser.add_argument(
        "--source-root",
        required=True,
        action="append",
        type=Path,
        help="Bounded DEM directory; repeat for county-crossing routes.",
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--corridor-m", type=float, default=500.0)
    parser.add_argument("--max-cells", type=int, default=4_000_000)
    parser.add_argument("--max-sources", type=int, default=256)
    parser.add_argument("--timeout-s", type=float, default=1800.0)
    parser.add_argument("--initiated-by", default="scout_operator_benchmark")
    args = parser.parse_args()
    try:
        plan = load_mosaic_plan(
            coverage_summary=args.coverage_summary,
            source_roots=args.source_root,
            corridor_m=args.corridor_m,
            max_cells=args.max_cells,
            max_sources=args.max_sources,
        )
        result = prepare_mosaic(
            plan=plan,
            output=args.output,
            report_path=args.report,
            timeout_s=args.timeout_s,
            initiated_by=args.initiated_by,
        )
    except (MosaicPreparationError, OSError, ValueError) as exc:
        print(
            json.dumps(
                {"status": "failed", "type": type(exc).__name__, "error": str(exc)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "status": result["status"],
                "artifact": result["artifact"]["ref"],
                "report": str(args.report.expanduser().resolve(strict=False)),
                "cell_count": result["output_contract"]["cell_count"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
