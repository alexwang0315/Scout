#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qgis_spatial_backend import QgisSpatialBackend, QgisSpatialBackendConfig  # noqa: E402


class QgisPreparationBenchmarkError(RuntimeError):
    pass


def run_benchmark(
    *,
    project_root: Path,
    project_id: str,
    iterations: int = 3,
) -> dict[str, Any]:
    if iterations < 1 or iterations > 10:
        raise QgisPreparationBenchmarkError("iterations must be between 1 and 10")
    root = project_root.expanduser().resolve()
    project_path = root / "project.json"
    if not project_path.is_file():
        raise QgisPreparationBenchmarkError("project.json is unavailable")

    backend = QgisSpatialBackend(config=QgisSpatialBackendConfig(enabled=False))
    samples: list[dict[str, float | int]] = []
    input_summary: dict[str, Any] | None = None
    total_dem_bytes = 0

    for _ in range(iterations):
        total_started = time.perf_counter_ns()

        phase_started = time.perf_counter_ns()
        try:
            project = json.loads(project_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise QgisPreparationBenchmarkError("project.json is invalid") from exc
        if not isinstance(project, dict):
            raise QgisPreparationBenchmarkError("project.json must contain an object")
        project_load_ms = _elapsed_ms(phase_started)

        phase_started = time.perf_counter_ns()
        route_points, route_refs, route_hashes, route_warning = backend._route_points(
            root,
            project,
            project_id=project_id,
        )
        route_resolution_ms = _elapsed_ms(phase_started)
        if len(route_points) < 2:
            raise QgisPreparationBenchmarkError("route geometry is unavailable")

        phase_started = time.perf_counter_ns()
        dem_paths, dem_refs, dem_hashes, source_resolution = backend._dem_sources(
            project_root=root,
            dem_ref=None,
        )
        dem_selection_and_hash_ms = _elapsed_ms(phase_started)
        if not dem_paths:
            raise QgisPreparationBenchmarkError("bounded DEM sources are unavailable")
        try:
            dem_bytes = sum(path.stat().st_size for path in dem_paths)
        except OSError as exc:
            raise QgisPreparationBenchmarkError("DEM source size inspection failed") from exc

        phase_started = time.perf_counter_ns()
        worker_payload = {
            "schema_version": "scout_qgis_worker_request.v0_1",
            "workflow_id": "terrain_context_preview.v1",
            "project_id": project_id,
            "corridor_m": 250.0,
            "route_geojson": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "candidate_only": True,
                            "runtime_safety_truth": False,
                            "operational": False,
                        },
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [
                                [point["lon"], point["lat"]] for point in route_points
                            ],
                        },
                    }
                ],
            },
            "dem_refs": [str(path) for path in dem_paths],
            "source_refs": [*route_refs, *dem_refs],
            "source_hashes": {**route_hashes, **dem_hashes},
            "source_resolution": source_resolution,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
        }
        payload_bytes = len(
            json.dumps(
                worker_payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        request_serialization_ms = _elapsed_ms(phase_started)
        total_ms = _elapsed_ms(total_started)
        samples.append(
            {
                "project_load_ms": project_load_ms,
                "route_resolution_ms": route_resolution_ms,
                "dem_selection_and_hash_ms": dem_selection_and_hash_ms,
                "request_serialization_ms": request_serialization_ms,
                "total_ms": total_ms,
                "request_payload_bytes": payload_bytes,
            }
        )
        total_dem_bytes = dem_bytes
        current_summary = {
            "route_point_count": len(route_points),
            "dem_source_count": len(dem_paths),
            "dem_source_bytes": dem_bytes,
            "source_ref_count": len(set([*route_refs, *dem_refs])),
            "source_hash_count": len({**route_hashes, **dem_hashes}),
            "source_resolution": source_resolution,
            "route_warning": route_warning,
        }
        if input_summary is not None and current_summary != input_summary:
            raise QgisPreparationBenchmarkError(
                "preparation inputs changed during the benchmark"
            )
        input_summary = current_summary

    dem_hash_seconds = sum(
        float(sample["dem_selection_and_hash_ms"]) for sample in samples
    ) / 1000.0
    return {
        "schema_version": "scout_qgis_preparation_benchmark.v0_1",
        "status": "completed",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "project_id": project_id,
        "benchmark_scope": "pre_qgis_input_preparation_only",
        "qgis_processing_executed": False,
        "mcp_invoked": False,
        "fixture": False,
        "synthetic": False,
        "iterations": iterations,
        "host": _host_summary(),
        "input_summary": input_summary,
        "samples": samples,
        "summary": {
            "total_ms_p50": _median(samples, "total_ms"),
            "total_ms_min": _minimum(samples, "total_ms"),
            "total_ms_max": _maximum(samples, "total_ms"),
            "dem_selection_and_hash_ms_p50": _median(
                samples,
                "dem_selection_and_hash_ms",
            ),
            "dem_hash_throughput_mib_s": round(
                (total_dem_bytes * iterations) / (1024 * 1024) / dem_hash_seconds,
                3,
            )
            if dem_hash_seconds > 0
            else None,
            "peak_rss_bytes": _peak_rss_bytes(),
        },
        "authority": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
        },
        "limitations": [
            "This benchmark does not execute QGIS Processing or MCP tools.",
            "Host results cannot be used as Raspberry Pi performance evidence unless host.is_raspberry_pi=true.",
        ],
    }


def _elapsed_ms(started_ns: int) -> float:
    return round((time.perf_counter_ns() - started_ns) / 1_000_000, 3)


def _median(samples: list[dict[str, float | int]], key: str) -> float:
    return round(statistics.median(float(sample[key]) for sample in samples), 3)


def _minimum(samples: list[dict[str, float | int]], key: str) -> float:
    return round(min(float(sample[key]) for sample in samples), 3)


def _maximum(samples: list[dict[str, float | int]], key: str) -> float:
    return round(max(float(sample[key]) for sample in samples), 3)


def _host_summary() -> dict[str, Any]:
    model_path = Path("/proc/device-tree/model")
    model = "unavailable"
    if model_path.is_file():
        try:
            model = model_path.read_text(encoding="utf-8").rstrip("\x00").strip()
        except OSError:
            model = "unavailable"
    return {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "model": model,
        "is_raspberry_pi": "raspberry pi" in model.casefold(),
    }


def _peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if platform.system() == "Darwin" else value * 1024


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark bounded Scout preparation before QGIS/MCP execution."
    )
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = run_benchmark(
            project_root=args.project_root,
            project_id=args.project_id,
            iterations=args.iterations,
        )
    except QgisPreparationBenchmarkError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}))
        return 2
    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
