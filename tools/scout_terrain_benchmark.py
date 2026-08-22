from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import shutil
import statistics
import sys
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(os.environ.get("SCOUT_REPO_ROOT", Path(__file__).resolve().parents[1]))
SCOUT_RISK_SRC = REPO_ROOT / "scout-risk-engine" / "scout_codex_package" / "src"

SCHEMA_VERSION = "scout_terrain_benchmark.v0_1"
DEFAULT_SYNTHETIC_DEM_SIZES = (64, 128)
DEFAULT_ITERATIONS = 3
MAX_ITERATIONS = 10
EXTERNAL_TOOL_IDS = (
    "gdalinfo",
    "gdal_translate",
    "gdaldem",
    "grass",
    "qgis",
    "qgis_process",
)


class TerrainBenchmarkError(RuntimeError):
    pass


def run_benchmark(
    *,
    project_root: Path | None = None,
    project_id: str | None = None,
    iterations: int = DEFAULT_ITERATIONS,
    synthetic_dem_sizes: tuple[int, ...] = DEFAULT_SYNTHETIC_DEM_SIZES,
    include_synthetic: bool = True,
    probe_external_tools: bool = False,
) -> dict[str, Any]:
    if iterations < 1 or iterations > MAX_ITERATIONS:
        raise TerrainBenchmarkError("iterations must be between 1 and 10")
    if include_synthetic and not synthetic_dem_sizes:
        raise TerrainBenchmarkError("at least one synthetic DEM size is required")
    if any(size < 8 or size > 2048 for size in synthetic_dem_sizes):
        raise TerrainBenchmarkError("synthetic DEM sizes must be between 8 and 2048")

    host = _host_summary()
    workspace_report: dict[str, Any] | None = None
    synthetic_reports: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []

    if project_root is not None:
        workspace_report = _benchmark_workspace(
            project_root=project_root,
            project_id=project_id,
            iterations=iterations,
        )
        project_id = workspace_report["project_id"]

    if include_synthetic:
        for size in synthetic_dem_sizes:
            synthetic_reports.append(
                _benchmark_synthetic_dem_kernel(size=size, iterations=iterations)
            )

    if workspace_report is None and not synthetic_reports:
        raise TerrainBenchmarkError("nothing to benchmark")

    if not host["is_raspberry_pi"]:
        warnings.append(
            {
                "code": "HOST_NOT_RASPBERRY_PI",
                "message": (
                    "This run is host evidence only. Run the same command on the "
                    "Scout Raspberry Pi before classifying Pi compatibility."
                ),
            }
        )

    pi_compatibility = _pi_compatibility_summary(
        host=host,
        workspace_report=workspace_report,
        synthetic_reports=synthetic_reports,
    )
    decision_summary = _decision_summary(
        host=host,
        workspace_report=workspace_report,
        synthetic_reports=synthetic_reports,
        pi_compatibility=pi_compatibility,
        probe_external_tools=probe_external_tools,
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": "scout_terrain_benchmark_report",
        "status": "completed",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "project_id": project_id or "synthetic-only",
        "iterations": iterations,
        "host": host,
        "benchmark_scope": {
            "workspace_preparation_metadata": workspace_report is not None,
            "synthetic_python_terrain_kernel": bool(synthetic_reports),
            "external_tool_execution": False,
            "external_tool_probe": probe_external_tools,
            "qgis_processing_executed": False,
            "grass_processing_executed": False,
            "gdal_processing_executed": False,
        },
        "workspace_preparation": workspace_report,
        "synthetic_terrain_kernels": synthetic_reports,
        "external_tool_capabilities": (
            _probe_external_tools() if probe_external_tools else None
        ),
        "pi_compatibility": pi_compatibility,
        "decision_summary": decision_summary,
        "authority": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
            "benchmark_only": True,
        },
        "warnings": warnings,
        "limitations": [
            "This benchmark measures execution cost and input size only.",
            "It does not prove terrain correctness, route truth, hazard truth, or safety.",
            "Non-Pi host results must not be used as Raspberry Pi performance evidence.",
            "External GRASS/GDAL/QGIS tools are only detected unless a future explicit benchmark executes them.",
        ],
    }


def _benchmark_workspace(
    *,
    project_root: Path,
    project_id: str | None,
    iterations: int,
) -> dict[str, Any]:
    root = project_root.expanduser().resolve()
    project_path = root / "project.json"
    if not project_path.is_file():
        raise TerrainBenchmarkError(f"project.json not found: {project_path}")

    def load_workspace() -> dict[str, Any]:
        project = _read_json_object(project_path, "project.json")
        resolved_project_id = str(project_id or project.get("project_id") or root.name)
        refs = _workspace_refs(project)
        loaded_refs: dict[str, dict[str, Any]] = {}
        warnings: list[dict[str, str]] = []
        for name, ref in refs.items():
            if not ref:
                loaded_refs[name] = {"status": "missing_ref"}
                continue
            ref_path = _safe_project_ref(root, ref)
            if not ref_path.is_file():
                loaded_refs[name] = {"status": "missing_file", "ref": ref}
                warnings.append(
                    {
                        "code": "WORKSPACE_REF_MISSING_FILE",
                        "message": f"{name} points to missing file {ref}",
                    }
                )
                continue
            started = time.perf_counter_ns()
            payload = _read_json_payload(ref_path, name)
            loaded_refs[name] = {
                "status": "loaded",
                "ref": ref,
                "bytes": ref_path.stat().st_size,
                "load_ms": _elapsed_ms(started),
                "summary": _summarize_payload(payload),
            }
        return {
            "project_id": resolved_project_id,
            "project_key_count": len(project),
            "project_path": str(project_path),
            "refs": loaded_refs,
            "warnings": warnings,
            "authority": {
                "candidate_only": True,
                "runtime_safety_truth": False,
                "operational": False,
            },
        }

    operation = _measure_operation(
        "workspace_preparation_metadata_read",
        load_workspace,
        iterations=iterations,
    )
    summary = operation.pop("stable_output")
    return {
        **summary,
        "operation": operation,
        "scope": "project_json_and_prepared_terrain_metadata_refs",
        "qgis_processing_executed": False,
        "grass_processing_executed": False,
        "gdal_processing_executed": False,
    }


def _benchmark_synthetic_dem_kernel(*, size: int, iterations: int) -> dict[str, Any]:
    _ensure_scout_risk_importable()
    import numpy as np
    from scout_risk.dem.io import DEMGrid
    from scout_risk.dem.teii import compute_teii_from_dem

    def run_kernel() -> dict[str, Any]:
        elevation = np.fromfunction(
            lambda row, col: (
                800.0
                + row * 0.8
                + col * 0.55
                + np.sin(col / 7.0) * 18.0
                + np.cos(row / 11.0) * 14.0
            ),
            (size, size),
            dtype=float,
        )
        dem = DEMGrid.from_array(
            elevation,
            pixel_size=20.0,
            crs="synthetic-local-meter",
        )
        features, teii = compute_teii_from_dem(dem)
        return {
            "grid_size": size,
            "grid_cells": int(size * size),
            "pixel_size_m": dem.pixel_size,
            "source": "synthetic_dem",
            "fixture": True,
            "synthetic": True,
            "feature_names": sorted(features.as_dict().keys()),
            "teii_mean": round(float(np.nanmean(teii)), 6),
            "teii_max": round(float(np.nanmax(teii)), 6),
            "authority": {
                "candidate_only": True,
                "runtime_safety_truth": False,
                "operational": False,
            },
        }

    operation = _measure_operation(
        f"synthetic_dem_teii_{size}x{size}",
        run_kernel,
        iterations=iterations,
    )
    stable_output = operation.pop("stable_output")
    p50_ms = operation["summary"]["duration_ms_p50"]
    cells = stable_output["grid_cells"]
    return {
        **stable_output,
        "operation": operation,
        "cells_per_second_p50": (
            round(cells / (p50_ms / 1000.0), 3) if p50_ms > 0 else None
        ),
        "kernel": "scout_risk.compute_teii_from_dem",
        "scope": "pure_python_numpy_scout_risk_engine",
    }


def _measure_operation(
    name: str,
    fn: Callable[[], dict[str, Any]],
    *,
    iterations: int,
) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    stable_output: dict[str, Any] | None = None
    for index in range(iterations):
        rss_before = _peak_rss_bytes()
        started = time.perf_counter_ns()
        output = fn()
        duration_ms = _elapsed_ms(started)
        rss_after = _peak_rss_bytes()
        comparable_output = _stable_json(_strip_measurement_fields(output))
        if stable_output is not None and comparable_output != _stable_json(
            _strip_measurement_fields(stable_output)
        ):
            raise TerrainBenchmarkError(f"{name} inputs changed during benchmark")
        stable_output = output
        samples.append(
            {
                "iteration": index + 1,
                "duration_ms": duration_ms,
                "peak_rss_bytes": rss_after,
                "peak_rss_delta_bytes": max(0, rss_after - rss_before),
            }
        )
    return {
        "name": name,
        "status": "completed",
        "samples": samples,
        "summary": {
            "duration_ms_p50": _median(samples, "duration_ms"),
            "duration_ms_min": _minimum(samples, "duration_ms"),
            "duration_ms_max": _maximum(samples, "duration_ms"),
            "peak_rss_bytes_max": max(int(sample["peak_rss_bytes"]) for sample in samples),
        },
        "stable_output": stable_output or {},
    }


def _workspace_refs(project: dict[str, Any]) -> dict[str, str | None]:
    return {
        "route_evidence_bundle": _string_or_none(project.get("route_evidence_bundle_ref")),
        "route_summary": _string_or_none(project.get("route_summary_ref")),
        "dtm_coverage_summary": _string_or_none(
            project.get("dtm_coverage_summary_ref")
            or project.get("terrain_dtm_coverage_summary_ref")
        ),
        "segment_dtm_coverage": _string_or_none(project.get("segment_dtm_coverage_ref")),
        "terrain_route_samples": _string_or_none(project.get("terrain_route_samples_ref")),
        "terrain_visualization": _string_or_none(project.get("terrain_visualization_ref")),
        "risk_route_profile": _string_or_none(project.get("risk_route_profile_ref")),
        "risk_score_points": _string_or_none(project.get("risk_score_points_ref")),
        "risk_ribbon": _string_or_none(project.get("risk_ribbon_ref")),
        "calibrated_risk_heatmap": _string_or_none(
            project.get("calibrated_risk_heatmap_ref")
        ),
    }


def _summarize_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, list):
        return {"kind": "list", "item_count": len(payload)}
    if not isinstance(payload, dict):
        return {"kind": type(payload).__name__}
    summary: dict[str, Any] = {
        "kind": "dict",
        "top_level_key_count": len(payload),
    }
    if isinstance(payload.get("features"), list):
        summary["feature_count"] = len(payload["features"])
    if isinstance(payload.get("candidate_tiles"), list):
        summary["candidate_tile_count"] = len(payload["candidate_tiles"])
    if isinstance(payload.get("segment_metadata"), list):
        summary["segment_count"] = len(payload["segment_metadata"])
    if isinstance(payload.get("samples"), list):
        summary["sample_count"] = len(payload["samples"])
    if isinstance(payload.get("raster_overlays"), list):
        summary["raster_overlay_count"] = len(payload["raster_overlays"])
    if isinstance(payload.get("boundary"), dict):
        boundary = payload["boundary"]
        summary["boundary"] = {
            "candidate_only": boundary.get("candidate_only"),
            "runtime_safety_truth": boundary.get("runtime_safety_truth"),
        }
    if isinstance(payload.get("artifact_kind"), str):
        summary["artifact_kind"] = payload["artifact_kind"]
    if isinstance(payload.get("summary_id"), str):
        summary["summary_id"] = payload["summary_id"]
    return summary


def _pi_compatibility_summary(
    *,
    host: dict[str, Any],
    workspace_report: dict[str, Any] | None,
    synthetic_reports: list[dict[str, Any]],
) -> dict[str, Any]:
    measured_on_pi = bool(host["is_raspberry_pi"])
    assessments: list[dict[str, Any]] = []
    if workspace_report is not None:
        assessments.append(
            _assess_operation_for_pi(
                operation_name="workspace_preparation_metadata_read",
                p50_ms=workspace_report["operation"]["summary"]["duration_ms_p50"],
                measured_on_pi=measured_on_pi,
            )
        )
    for report in synthetic_reports:
        assessments.append(
            _assess_operation_for_pi(
                operation_name=report["operation"]["name"],
                p50_ms=report["operation"]["summary"]["duration_ms_p50"],
                measured_on_pi=measured_on_pi,
            )
        )
    return {
        "measured_on_raspberry_pi": measured_on_pi,
        "status": "measured_on_pi" if measured_on_pi else "requires_pi_run",
        "assessments": assessments,
        "tier_definitions": {
            "pi_compatible": "p50 <= 2s on the actual Scout Pi for bounded inputs",
            "pi_bounded": "2s < p50 <= 20s on the actual Scout Pi for bounded inputs",
            "advanced_workstation": "p50 > 20s, timeout, memory pressure, or not measured on Pi",
        },
    }


def _decision_summary(
    *,
    host: dict[str, Any],
    workspace_report: dict[str, Any] | None,
    synthetic_reports: list[dict[str, Any]],
    pi_compatibility: dict[str, Any],
    probe_external_tools: bool,
) -> dict[str, Any]:
    missing_refs: list[str] = []
    loaded_refs: list[str] = []
    if workspace_report is not None:
        for name, item in workspace_report["refs"].items():
            status = item.get("status")
            if status == "loaded":
                loaded_refs.append(name)
            elif status in {"missing_ref", "missing_file"}:
                missing_refs.append(name)

    operation_rows: list[dict[str, Any]] = []
    assessments_by_operation = {
        item["operation"]: item for item in pi_compatibility["assessments"]
    }
    if workspace_report is not None:
        operation_rows.append(
            _decision_operation_row(
                label="workspace_preparation_metadata_read",
                assessment=assessments_by_operation.get(
                    "workspace_preparation_metadata_read",
                    {},
                ),
                measured_on_pi=bool(host["is_raspberry_pi"]),
            )
        )
    for report in synthetic_reports:
        operation_rows.append(
            _decision_operation_row(
                label=report["operation"]["name"],
                assessment=assessments_by_operation.get(report["operation"]["name"], {}),
                measured_on_pi=bool(host["is_raspberry_pi"]),
            )
        )

    next_actions: list[str] = []
    if not host["is_raspberry_pi"]:
        next_actions.append(
            "Run this same benchmark on the Scout Raspberry Pi before classifying Pi feasibility."
        )
    if missing_refs:
        next_actions.append(
            "Inspect missing workspace refs before using this workspace as a complete preparation benchmark."
        )
    if not probe_external_tools:
        next_actions.append(
            "Use --probe-external-tools when deciding whether GRASS/GDAL/QGIS backends are locally available."
        )
    if not next_actions:
        next_actions.append(
            "Use the operation tiers to decide Pi-compatible, Pi-bounded, or advanced workstation placement."
        )

    return {
        "classification_status": (
            "requires_pi_run"
            if not host["is_raspberry_pi"]
            else "pi_measured"
        ),
        "workspace_refs": {
            "loaded": loaded_refs,
            "missing": missing_refs,
        },
        "operations": operation_rows,
        "external_processing_executed": False,
        "next_actions": next_actions,
        "authority": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
        },
    }


def _decision_operation_row(
    *,
    label: str,
    assessment: dict[str, Any],
    measured_on_pi: bool,
) -> dict[str, Any]:
    return {
        "operation": label,
        "tier": assessment.get(
            "tier",
            "unclassified_requires_pi_run"
            if not measured_on_pi
            else "unclassified_missing_assessment",
        ),
        "p50_ms": assessment.get("p50_ms"),
        "measured_on_pi": measured_on_pi,
    }


def _assess_operation_for_pi(
    *,
    operation_name: str,
    p50_ms: float,
    measured_on_pi: bool,
) -> dict[str, Any]:
    if not measured_on_pi:
        return {
            "operation": operation_name,
            "tier": "unclassified_requires_pi_run",
            "reason": "This benchmark was not measured on a Raspberry Pi.",
            "p50_ms": p50_ms,
        }
    if p50_ms <= 2000:
        tier = "pi_compatible"
    elif p50_ms <= 20000:
        tier = "pi_bounded"
    else:
        tier = "advanced_workstation"
    return {
        "operation": operation_name,
        "tier": tier,
        "p50_ms": p50_ms,
    }


def _probe_external_tools() -> dict[str, Any]:
    tools: dict[str, Any] = {}
    for tool_id in EXTERNAL_TOOL_IDS:
        path = shutil.which(tool_id)
        tools[tool_id] = {
            "available_on_path": path is not None,
            "path": path,
            "executed": False,
        }
    return {
        "status": "completed",
        "execution_policy": "path_probe_only_no_processing",
        "tools": tools,
        "roles": {
            "gdal": "optional_pi_bounded_or_advanced_worker_after_benchmark",
            "grass": "optional_pi_bounded_or_advanced_worker_after_benchmark",
            "qgis": "advanced_visual_review_or_workstation_processing",
        },
    }


def _host_summary() -> dict[str, Any]:
    model = _device_model()
    return {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "model": model,
        "is_raspberry_pi": "raspberry pi" in model.casefold(),
    }


def _device_model() -> str:
    model_path = Path("/proc/device-tree/model")
    if model_path.is_file():
        try:
            return model_path.read_text(encoding="utf-8").rstrip("\x00").strip()
        except OSError:
            return "unavailable"
    return platform.platform()


def _ensure_scout_risk_importable() -> None:
    path_text = SCOUT_RISK_SRC.as_posix()
    if path_text not in sys.path:
        sys.path.insert(0, path_text)


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    payload = _read_json_payload(path, label)
    if not isinstance(payload, dict):
        raise TerrainBenchmarkError(f"{label} must contain a JSON object")
    return payload


def _read_json_payload(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise TerrainBenchmarkError(f"failed to read {label}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise TerrainBenchmarkError(f"failed to parse {label}: {path}") from exc


def _safe_project_ref(project_root: Path, ref: str) -> Path:
    path = (project_root / ref).resolve()
    try:
        path.relative_to(project_root)
    except ValueError as exc:
        raise TerrainBenchmarkError(f"workspace ref escapes project root: {ref}") from exc
    return path


def _string_or_none(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _strip_measurement_fields(payload: Any) -> Any:
    if isinstance(payload, list):
        return [_strip_measurement_fields(item) for item in payload]
    if isinstance(payload, dict):
        return {
            key: _strip_measurement_fields(value)
            for key, value in payload.items()
            if key not in {"load_ms"}
        }
    return payload


def _elapsed_ms(started_ns: int) -> float:
    return round((time.perf_counter_ns() - started_ns) / 1_000_000, 3)


def _median(samples: list[dict[str, Any]], key: str) -> float:
    return round(statistics.median(float(sample[key]) for sample in samples), 3)


def _minimum(samples: list[dict[str, Any]], key: str) -> float:
    return round(min(float(sample[key]) for sample in samples), 3)


def _maximum(samples: list[dict[str, Any]], key: str) -> float:
    return round(max(float(sample[key]) for sample in samples), 3)


def _peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if platform.system() == "Darwin" else value * 1024


def _parse_sizes(raw: str) -> tuple[int, ...]:
    sizes: list[int] = []
    for item in raw.split(","):
        stripped = item.strip()
        if not stripped:
            continue
        try:
            sizes.append(int(stripped))
        except ValueError as exc:
            raise TerrainBenchmarkError(f"invalid synthetic DEM size: {stripped}") from exc
    return tuple(sizes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark Scout Pi-first terrain preparation and pure Python terrain kernels."
    )
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--project-id")
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument(
        "--synthetic-dem-sizes",
        default=",".join(str(size) for size in DEFAULT_SYNTHETIC_DEM_SIZES),
        help="Comma-separated square DEM sizes, e.g. 64,128,256.",
    )
    parser.add_argument("--skip-synthetic", action="store_true")
    parser.add_argument("--probe-external-tools", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        report = run_benchmark(
            project_root=args.project_root,
            project_id=args.project_id,
            iterations=args.iterations,
            synthetic_dem_sizes=_parse_sizes(args.synthetic_dem_sizes),
            include_synthetic=not args.skip_synthetic,
            probe_external_tools=args.probe_external_tools,
        )
    except TerrainBenchmarkError as exc:
        print(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "status": "failed",
                    "error": str(exc),
                    "authority": {
                        "candidate_only": True,
                        "runtime_safety_truth": False,
                        "operational": False,
                    },
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2

    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
