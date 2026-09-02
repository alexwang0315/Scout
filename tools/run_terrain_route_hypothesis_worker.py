"""Run one candidate-only terrain route hypothesis on a GIS worker host.

The command is intentionally host-agnostic. Its execution receipt records the
actual hostname so callers can prove whether GRASS ran on Scout or elsewhere.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import secrets
import sys
import time
from pathlib import Path
from typing import Any, Sequence

from pydantic import ValidationError


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qgis_spatial_contracts import SpatialWorkflowState
from qgis_worker import QgisWorkerConfig, QgisWorkerService
from qgis_worker_contracts import QgisWorkerRun, QgisWorkerWorkflowRequest
from terrain_route_hypothesis_artifacts import (
    build_live_terrain_route_cache_keys,
    build_terrain_route_resolution_identity,
    build_terrain_route_source_identity,
)
from terrain_route_guidance import TerrainGuidanceExecutionPlan
from terrain_route_hypothesis_models import TerrainRoutingCostConfig


_TERMINAL_STATES = {
    SpatialWorkflowState.COMPLETED,
    SpatialWorkflowState.FAILED,
    SpatialWorkflowState.CANCELLED,
}


class TerrainRouteWorkerError(RuntimeError):
    """Typed runner-boundary failure; no route candidate should be inferred."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_wgs84_point(value: str) -> tuple[float, float]:
    try:
        lon_text, lat_text = (part.strip() for part in value.split(",", 1))
        lon = float(lon_text)
        lat = float(lat_text)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("point must be formatted as lon,lat") from exc
    if not math.isfinite(lon) or not math.isfinite(lat):
        raise argparse.ArgumentTypeError("point coordinates must be finite")
    if not -180 <= lon <= 180 or not -90 <= lat <= 90:
        raise argparse.ArgumentTypeError("point is outside WGS84 bounds")
    return lon, lat


def load_guidance_execution_plan(path: Path) -> TerrainGuidanceExecutionPlan:
    """Load the reviewed worker-safe payload; raw narrative is schema-rejected."""

    resolved = path.expanduser().resolve(strict=True)
    if not resolved.is_file():
        raise TerrainRouteWorkerError(
            "terrain guidance execution plan is not a regular file"
        )
    return TerrainGuidanceExecutionPlan.model_validate_json(
        resolved.read_text(encoding="utf-8")
    )


def build_worker_request(
    *,
    project_id: str,
    request_id: str,
    requested_by: str,
    dem_path: Path,
    parent_manifest_path: Path,
    dem_resolution_m: float,
    start: Sequence[float],
    destination: Sequence[float],
    corridor_m: float,
    cost_config: TerrainRoutingCostConfig | None = None,
    guidance_execution_plan_path: Path | None = None,
) -> QgisWorkerWorkflowRequest:
    resolved_dem = dem_path.expanduser().resolve(strict=True)
    if not resolved_dem.is_file():
        raise TerrainRouteWorkerError("DEM input is not a regular file")
    resolved_manifest = parent_manifest_path.expanduser().resolve(strict=True)
    if (
        not resolved_manifest.is_file()
        or resolved_manifest.name != "terrain_feature_manifest.json"
    ):
        raise TerrainRouteWorkerError(
            "terrain_feature_manifest.json is required as the immutable DEM parent"
        )
    source_resolution = _validate_parent_manifest(
        path=resolved_manifest,
        dem_path=resolved_dem,
        expected_resolution_m=float(dem_resolution_m),
    )
    resolution = float(dem_resolution_m)
    if not math.isfinite(resolution) or resolution <= 0:
        raise TerrainRouteWorkerError("DEM resolution must be a positive finite value")
    start_pair = _coordinate_pair(start, label="start")
    destination_pair = _coordinate_pair(destination, label="destination")
    if start_pair == destination_pair:
        raise TerrainRouteWorkerError("start and destination must differ")
    resolved_cost_config = cost_config or TerrainRoutingCostConfig()
    source_ref = resolved_dem.as_posix()
    source_hash = sha256_file(resolved_dem)
    parent_manifest_ref = resolved_manifest.as_posix()
    parent_manifest_hash = sha256_file(resolved_manifest)
    source_hashes = {
        source_ref: source_hash,
        parent_manifest_ref: parent_manifest_hash,
    }
    terrain_source_hashes = build_terrain_route_source_identity(
        dem_sha256s=(source_hash,),
        parent_manifest_sha256=parent_manifest_hash,
    )
    source_refs = [source_ref, parent_manifest_ref]
    guidance_execution_plan = None
    guidance_execution_plan_hash = None
    route_coordinates = [list(start_pair), list(destination_pair)]
    if guidance_execution_plan_path is not None:
        guidance_path = guidance_execution_plan_path.expanduser().resolve(strict=True)
        guidance_execution_plan = load_guidance_execution_plan(guidance_path)
        if guidance_execution_plan.dem_sha256 != source_hash:
            raise TerrainRouteWorkerError(
                "reviewed terrain guidance is bound to a different DEM"
            )
        if not math.isclose(
            guidance_execution_plan.dem_resolution_m,
            resolution,
            rel_tol=1e-9,
            abs_tol=1e-9,
        ):
            raise TerrainRouteWorkerError(
                "reviewed terrain guidance DEM resolution does not match the request"
            )
        if guidance_execution_plan.dem_crs != "EPSG:3826":
            raise TerrainRouteWorkerError(
                "reviewed terrain guidance must be bound to EPSG:3826"
            )
        anchor_pairs = [
            _coordinate_pair(
                (anchor.point.x, anchor.point.y),
                label=f"guidance anchor {anchor.constraint_id}",
            )
            for anchor in guidance_execution_plan.anchors
        ]
        ordered_points = [start_pair, *anchor_pairs, destination_pair]
        if len(set(ordered_points)) != len(ordered_points):
            raise TerrainRouteWorkerError(
                "reviewed terrain guidance anchors must be distinct from A, B, and each other"
            )
        route_coordinates = [list(point) for point in ordered_points]
        guidance_ref = guidance_path.as_posix()
        guidance_execution_plan_hash = sha256_file(guidance_path)
        source_refs.append(guidance_ref)
        source_hashes[guidance_ref] = guidance_execution_plan_hash
    return QgisWorkerWorkflowRequest(
        workflow_id="terrain_route_hypothesis.v1",
        project_id=project_id,
        request_id=request_id,
        requested_by=requested_by,
        corridor_m=corridor_m,
        route_geojson={
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "authority": "candidate_only",
                        "source_type": "terrain_hypothesis",
                        "candidate_only": True,
                        "runtime_safety_truth": False,
                        "operational": False,
                    },
                    "geometry": {
                        "type": "LineString",
                        "coordinates": route_coordinates,
                    },
                }
            ],
        },
        dem_refs=[source_ref],
        source_refs=source_refs,
        source_hashes=source_hashes,
        source_resolution=source_resolution,
        terrain_routing_cost_config=resolved_cost_config,
        terrain_route_cache_keys=build_live_terrain_route_cache_keys(
            source_hashes=terrain_source_hashes,
            source_resolution=build_terrain_route_resolution_identity(
                source_resolution
            ),
            route_coordinates=route_coordinates,
            analysis_margin_m=corridor_m,
            cost_config=resolved_cost_config,
            optional_evidence_hashes=(
                {
                    "terrain_guidance_execution_plan": guidance_execution_plan_hash,
                    "terrain_guidance_review": (
                        guidance_execution_plan.guidance_review_sha256
                    ),
                }
                if guidance_execution_plan is not None
                and guidance_execution_plan_hash is not None
                else None
            ),
            guidance_review_sha256=(
                guidance_execution_plan.guidance_review_sha256
                if guidance_execution_plan is not None
                else None
            ),
        ),
        terrain_route_guidance_execution_plan=guidance_execution_plan,
        candidate_only=True,
        runtime_safety_truth=False,
        operational=False,
    )


def execute_request(
    *,
    request: QgisWorkerWorkflowRequest,
    worker_root: Path,
    source_roots: Sequence[Path],
    timeout_s: float,
    poll_interval_s: float = 0.25,
    qgis_mcp_server_root: Path | None = None,
) -> tuple[QgisWorkerRun, dict[str, Any]]:
    timeout = float(timeout_s)
    if not math.isfinite(timeout) or not 1 <= timeout <= 1800:
        raise TerrainRouteWorkerError("timeout must be between 1 and 1800 seconds")
    roots = tuple(path.expanduser().resolve(strict=True) for path in source_roots)
    if not roots:
        raise TerrainRouteWorkerError("at least one bounded source root is required")
    server_root = resolve_qgis_mcp_server_root(qgis_mcp_server_root)
    service = QgisWorkerService(
        config=QgisWorkerConfig(
            enabled=True,
            auth_token=secrets.token_urlsafe(32),
            root=worker_root,
            source_roots=roots,
            timeout_s=timeout,
            poll_interval_s=poll_interval_s,
            request_max_bytes=2 * 1024 * 1024,
            mcp_command=(sys.executable, "-m", "qgis_mcp"),
            mcp_pythonpath=str(server_root),
        )
    )
    started = time.monotonic()
    try:
        status = service.status()
        if status.availability.value != "available":
            raise TerrainRouteWorkerError(
                "QGIS/GRASS worker is unavailable: "
                + status.model_dump_json(exclude_none=True)
            )
        current = service.start(request)
        deadline = time.monotonic() + timeout
        while current.state not in _TERMINAL_STATES:
            if time.monotonic() >= deadline:
                service.cancel(current.worker_run_id, requested_by="runner_timeout")
                raise TerrainRouteWorkerError("terrain route hypothesis worker timed out")
            time.sleep(poll_interval_s)
            current = service.get(current.worker_run_id)
        if current.state is not SpatialWorkflowState.COMPLETED or current.result is None:
            detail = current.error.model_dump(mode="json") if current.error else None
            raise TerrainRouteWorkerError(
                "terrain route hypothesis is unavailable: "
                + json.dumps(detail, ensure_ascii=False, sort_keys=True)
            )
        _assert_candidate_only(current)
        receipt = build_execution_receipt(
            run=current,
            duration_s=time.monotonic() - started,
            worker_root=worker_root,
            request=request,
        )
        return current, receipt
    finally:
        service.close()


def build_execution_receipt(
    *,
    run: QgisWorkerRun,
    duration_s: float,
    worker_root: Path,
    request: QgisWorkerWorkflowRequest | None = None,
) -> dict[str, Any]:
    _assert_candidate_only(run)
    if request is not None and (
        request.request_id != run.request_id or request.workflow_id != run.workflow_id
    ):
        raise TerrainRouteWorkerError(
            "execution receipt request does not match the completed worker run"
        )
    result = run.result
    assert result is not None
    receipt = {
        "schema_version": "scout_terrain_route_execution_receipt.v0_1",
        "status": "completed",
        "execution_host": platform.node() or "unknown",
        "execution_architecture": platform.machine() or "unknown",
        "workflow_id": run.workflow_id,
        "worker_run_id": run.worker_run_id,
        "worker_run_ref": (
            worker_root.expanduser().resolve()
            / "runs"
            / run.worker_run_id
            / "run.json"
        ).as_posix(),
        "duration_s": round(float(duration_s), 3),
        "qgis_version": result.qgis_version,
        "processing_algorithms": list(result.processing_algorithms),
        "artifact_count": len(result.artifacts),
        "authority": "candidate_only",
        "source_type": "terrain_hypothesis",
        "candidate_only": True,
        "runtime_safety_truth": False,
        "operational": False,
        "safe_or_walkable": "not_determined",
    }
    guidance = (
        request.terrain_route_guidance_execution_plan
        if request is not None
        else None
    )
    if guidance is not None:
        receipt.update(
            {
                "guided_hypothesis_id": guidance.guided_hypothesis_id,
                "guidance_id": guidance.guidance_id,
                "guidance_review_sha256": guidance.guidance_review_sha256,
                "guidance_plan_sha256": guidance.plan_sha256,
                "guidance_resolution_sha256": guidance.resolution_sha256,
                "guidance_feature_index_sha256": guidance.feature_index_sha256,
                "reviewed_by": guidance.reviewed_by,
                "reviewed_at": guidance.reviewed_at.isoformat(),
                "human_reviewed_interpretation_binding": True,
                "review_scope": "interpretation_to_map_binding_only",
            }
        )
    if request is not None:
        receipt.update(_input_contract_receipt_fields(request))
    return receipt


def _input_contract_receipt_fields(
    request: QgisWorkerWorkflowRequest,
) -> dict[str, Any]:
    dem_hashes: list[str] = []
    for dem_ref in request.dem_refs:
        value = request.source_hashes.get(dem_ref)
        if value is None:
            raise TerrainRouteWorkerError(
                "execution receipt cannot bind the source DEM hash"
            )
        dem_hashes.append(value)
    parent_refs = [
        ref
        for ref in request.source_refs
        if Path(ref).name == "terrain_feature_manifest.json"
    ]
    if len(parent_refs) != 1:
        raise TerrainRouteWorkerError(
            "execution receipt requires one terrain-feature parent manifest"
        )
    parent_hash = request.source_hashes.get(parent_refs[0])
    if parent_hash is None:
        raise TerrainRouteWorkerError(
            "execution receipt cannot bind the terrain-feature parent hash"
        )
    coordinates = request.route_geojson["features"][0]["geometry"]["coordinates"]
    contract = {
        "source_dem_sha256s": sorted(dem_hashes),
        "terrain_parent_manifest_sha256": parent_hash,
        "source_resolution": build_terrain_route_resolution_identity(
            request.source_resolution
        ),
        "start": coordinates[0],
        "destination": coordinates[-1],
        "corridor_m": request.corridor_m,
        "cost_config": request.terrain_routing_cost_config.model_dump(mode="json"),
        "guidance_review_sha256": (
            request.terrain_route_guidance_execution_plan.guidance_review_sha256
            if request.terrain_route_guidance_execution_plan is not None
            else None
        ),
    }
    contract_sha = hashlib.sha256(
        json.dumps(
            contract,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "source_dem_sha256s": contract["source_dem_sha256s"],
        "terrain_parent_manifest_sha256": parent_hash,
        "input_contract_sha256": contract_sha,
    }


def _coordinate_pair(value: Sequence[float], *, label: str) -> tuple[float, float]:
    if len(value) != 2:
        raise TerrainRouteWorkerError(f"{label} must contain lon and lat")
    lon = float(value[0])
    lat = float(value[1])
    if not math.isfinite(lon) or not math.isfinite(lat):
        raise TerrainRouteWorkerError(f"{label} coordinates must be finite")
    if not -180 <= lon <= 180 or not -90 <= lat <= 90:
        raise TerrainRouteWorkerError(f"{label} is outside WGS84 bounds")
    return lon, lat


def resolve_qgis_mcp_server_root(explicit: Path | None = None) -> Path:
    """Resolve the same bounded QGIS MCP package on macOS and Scout/Linux."""

    if explicit is not None:
        candidates = (explicit,)
    else:
        configured = os.getenv("SCOUT_QGIS_MCP_PYTHONPATH", "").strip()
        candidates = (
            (Path(configured),)
            if configured
            else (
                Path.home()
                / ".scout-fusion"
                / "qgis-desktop"
                / "profiles"
                / "scout"
                / "python"
                / "plugins"
                / "qgis_agent_mcp"
                / "_server",
                Path("/opt/qgis-plugins/qgis_agent_mcp/_server"),
            )
        )
    for candidate in candidates:
        resolved = candidate.expanduser().resolve(strict=False)
        if resolved.is_dir() and (resolved / "qgis_mcp").is_dir():
            return resolved
    raise TerrainRouteWorkerError(
        "QGIS Agent MCP server package is unavailable on this host"
    )


def _validate_parent_manifest(
    *,
    path: Path,
    dem_path: Path,
    expected_resolution_m: float,
) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        source_resolution = payload["source_resolution"]
        artifacts = payload["artifacts"]
        analysis_extent = payload["parameters"]["analysis_extent"]
        x_m = float(source_resolution["x_m"])
        y_m = float(source_resolution["y_m"])
        analysis_resolution_m = float(analysis_extent["resolution_m"])
        crs = str(source_resolution["crs"]).upper()
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TerrainRouteWorkerError(
            "terrain-feature parent manifest is incomplete or malformed"
        ) from exc
    if (
        not isinstance(payload, dict)
        or payload.get("candidate_only") is not True
        or payload.get("runtime_safety_truth") is not False
        or payload.get("operational") is not False
        or payload.get("fixture") is True
        or payload.get("synthetic") is True
        or path.parent != dem_path.parent
        or not isinstance(artifacts, dict)
        or artifacts.get("dem_route_bbox") != dem_path.name
        or not isinstance(source_resolution, dict)
        or source_resolution.get("status") != "reported"
        or source_resolution.get("adds_source_resolution") is not False
        or crs not in {"3826", "EPSG:3826"}
        or not all(
            math.isfinite(value)
            for value in (x_m, y_m, analysis_resolution_m, expected_resolution_m)
        )
        or expected_resolution_m <= 0
        or not math.isclose(x_m, y_m, rel_tol=1e-9, abs_tol=1e-9)
        or not math.isclose(x_m, analysis_resolution_m, rel_tol=1e-9, abs_tol=1e-9)
        or not math.isclose(
            x_m,
            expected_resolution_m,
            rel_tol=1e-9,
            abs_tol=1e-9,
        )
    ):
        raise TerrainRouteWorkerError(
            "terrain-feature parent manifest does not bind the submitted DEM grid"
        )
    return {
        "status": "reported",
        "source_kind": "active_terrain_feature_dem",
        "x_m": x_m,
        "y_m": y_m,
        "crs": "EPSG:3826",
        "crs_evidence": source_resolution.get("crs_evidence") or "unavailable",
        "adds_source_resolution": False,
        "parent_terrain_feature_manifest_ref": path.as_posix(),
    }


def _assert_candidate_only(run: QgisWorkerRun) -> None:
    result = run.result
    if (
        run.candidate_only is not True
        or run.runtime_safety_truth is not False
        or run.operational is not False
        or result is None
        or result.candidate_only is not True
        or result.runtime_safety_truth is not False
        or result.operational is not False
    ):
        raise TerrainRouteWorkerError("worker result violated candidate-only authority")


def _load_cost_config(path: Path | None) -> TerrainRoutingCostConfig:
    if path is None:
        return TerrainRoutingCostConfig()
    return TerrainRoutingCostConfig.model_validate_json(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a candidate-only A/B terrain route hypothesis on this GIS host."
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--dem", required=True, type=Path)
    parser.add_argument("--terrain-parent-manifest", required=True, type=Path)
    parser.add_argument("--dem-resolution-m", required=True, type=float)
    parser.add_argument("--start", required=True, type=parse_wgs84_point)
    parser.add_argument("--destination", required=True, type=parse_wgs84_point)
    parser.add_argument("--corridor-m", type=float, default=500.0)
    parser.add_argument("--source-root", required=True, action="append", type=Path)
    parser.add_argument("--worker-root", required=True, type=Path)
    parser.add_argument("--timeout-s", type=float, default=600.0)
    parser.add_argument("--qgis-mcp-server-root", type=Path)
    parser.add_argument("--cost-config-json", type=Path)
    parser.add_argument(
        "--guidance-execution-plan",
        type=Path,
        help=(
            "Optional reviewed, hash-bound R4 execution plan. Raw narrative is not accepted."
        ),
    )
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()
    try:
        request = build_worker_request(
            project_id=args.project_id,
            request_id=args.request_id,
            requested_by="scout_terrain_route_worker_cli",
            dem_path=args.dem,
            parent_manifest_path=args.terrain_parent_manifest,
            dem_resolution_m=args.dem_resolution_m,
            start=args.start,
            destination=args.destination,
            corridor_m=args.corridor_m,
            cost_config=_load_cost_config(args.cost_config_json),
            guidance_execution_plan_path=args.guidance_execution_plan,
        )
        _, receipt = execute_request(
            request=request,
            worker_root=args.worker_root,
            source_roots=args.source_root,
            timeout_s=args.timeout_s,
            qgis_mcp_server_root=args.qgis_mcp_server_root,
        )
        receipt_path = args.receipt.expanduser().resolve()
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (
        OSError,
        ValueError,
        ValidationError,
        TerrainRouteWorkerError,
    ) as exc:
        print(
            json.dumps(
                {
                    "status": "unavailable",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "authority": "candidate_only",
                    "runtime_safety_truth": False,
                    "operational": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
