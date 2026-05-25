from __future__ import annotations

import argparse
import hashlib
import json
import math
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from admin_basemap_tiles import build_osm_basemap_contract, normalize_bbox_wgs84
from pretrip_models import RouteBBox
from pretrip_overpass_ingest import import_overpass_evidence_candidates


LAYER_PREPARATION_VERSION = "0.1.0"
LayerProfile = Literal["mac-workstation", "pi-offline", "pi-online-explicit"]
NetworkMode = Literal["no-network", "explicit-fetch"]

DEFAULT_LAYERS = (
    "osm",
    "overpass",
    "terrain",
    "imagery",
    "weather",
    "reference-tracks",
    "route",
    "segments",
    "checkpoints",
)
OUTPUT_REFS = {
    "layer_preparation_manifest_ref": "outputs/layers/layer_preparation_manifest.json",
    "layer_preparation_job_ref": "outputs/layers/layer_preparation_job.json",
    "layer_preparation_summary_ref": "outputs/layers/layer_preparation_summary.json",
    "layer_adapter_manifest_ref": "outputs/layers/layer_adapter_manifest.json",
    "layer_validation_report_ref": "outputs/layers/layer_validation_report.json",
    "layer_map_projection_ref": "outputs/layers/projections/pretrip_map_layers.json",
    "layer_debug_projection_events_ref": "outputs/layers/projections/admin_debug_events.jsonl",
}
ALLOWED_LAYERS = {
    "osm",
    "overpass",
    "terrain",
    "imagery",
    "weather",
    "reference-tracks",
    "route",
    "segments",
    "checkpoints",
    "pois",
    "hazards",
    "corridors",
    "retreat",
    "route-notes",
}
LAYER_ALIASES = {
    "dem": "terrain",
    "dtm": "terrain",
    "weather-api": "weather",
    "reference_tracks": "reference-tracks",
    "references": "reference-tracks",
    "ref-gpx": "reference-tracks",
    "reference-gpx": "reference-tracks",
}
READY_STATUSES = {
    "ready",
    "ready_from_project_ref",
    "ready_with_fallback",
    "projection_ready",
}
HEAVY_LOCAL_LAYER_IDS = {"terrain", "imagery"}


@dataclass(frozen=True)
class LayerPreparationRequest:
    project_id: str
    workspace_root: Path | None = None
    project_root: Path | None = None
    layers: tuple[str, ...] = DEFAULT_LAYERS
    profile: LayerProfile = "pi-offline"
    network_mode: NetworkMode = "no-network"
    allow_network_fetch: bool = False
    bbox: dict[str, Any] | None = None
    route_corridor_m: float = 500.0
    prepared_at: str | None = None


def run_layer_preparation(request: LayerPreparationRequest) -> dict[str, Any]:
    _maybe_fetch_overpass_evidence(request)
    manifest, project_root, project = _build_layer_preparation_manifest(
        request,
        workspace_file_mutation_allowed=True,
    )
    summary = _summary_from_manifest(manifest)
    adapter_manifest = _adapter_manifest_from_manifest(manifest)
    map_projection = _map_projection_from_manifest(manifest)
    debug_events = _debug_events_from_manifest(manifest)
    job_payload = _job_payload_from_manifest(manifest)
    outputs = manifest["outputs"]

    _write_json(project_root / outputs["layer_preparation_manifest_ref"], manifest)
    _write_json(project_root / outputs["layer_preparation_job_ref"], job_payload)
    _write_json(project_root / outputs["layer_preparation_summary_ref"], summary)
    _write_json(project_root / outputs["layer_adapter_manifest_ref"], adapter_manifest)
    _write_json(project_root / outputs["layer_validation_report_ref"], manifest["validation"])
    _write_json(project_root / outputs["layer_map_projection_ref"], map_projection)
    _write_jsonl(project_root / outputs["layer_debug_projection_events_ref"], debug_events)
    _write_layer_plan_files(project_root, manifest)
    _update_project_refs(project_root / "project.json", project, outputs, manifest["finished_at"])
    return manifest


def build_layer_preparation_preview(request: LayerPreparationRequest) -> dict[str, Any]:
    manifest, _, _ = _build_layer_preparation_manifest(
        request,
        workspace_file_mutation_allowed=False,
    )
    return {
        **manifest,
        "artifact_kind": "pretrip_layer_preparation_preview",
        "preview": True,
        "persisted": False,
    }


def _maybe_fetch_overpass_evidence(request: LayerPreparationRequest) -> None:
    normalized_layers = _normalize_layer_ids(request.layers)
    if "overpass" not in normalized_layers:
        return
    if request.network_mode != "explicit-fetch" or not request.allow_network_fetch:
        return
    project_root = _resolve_project_root(request)
    _reject_fixture_fetch(project_root)
    project_path = project_root / "project.json"
    project = _load_json(project_path)
    if project.get("overpass_evidence_ref"):
        return
    route_summary = _load_project_ref(
        project_root,
        project,
        "route_summary_ref",
        required=True,
    )
    route_bbox = normalize_bbox_wgs84(request.bbox or route_summary["bbox_wgs84"])
    query_bbox = _expand_bbox_by_meters(route_bbox, request.route_corridor_m)
    route_corridor = _route_corridor_record(
        project=project,
        route_summary=route_summary,
        route_bbox=route_bbox,
        query_bbox=query_bbox,
        request=request,
    )
    planned_request = _planned_overpass_request(
        bbox=query_bbox,
        request=request,
        route_corridor=route_corridor,
    )
    raw_bytes, http_status = _fetch_overpass_raw_payload(planned_request)
    raw_payload = json.loads(raw_bytes.decode("utf-8"))
    raw_ref = planned_request["raw_payload_target_ref"]
    normalized_ref = planned_request["normalized_artifact_target_ref"]
    evidence_ref = "candidates/overpass_evidence.json"
    _write_bytes(project_root / raw_ref, raw_bytes)
    result = import_overpass_evidence_candidates(
        raw_payload,
        query_body=planned_request["query_body"],
        bbox_wgs84=RouteBBox(
            min_lat=query_bbox["south"],
            min_lon=query_bbox["west"],
            max_lat=query_bbox["north"],
            max_lon=query_bbox["east"],
        ),
        route_corridor=route_corridor,
        request_timestamp=request.prepared_at or _utc_now(),
        endpoint=planned_request["endpoint"],
        http_status=http_status,
        raw_payload_uri=raw_ref,
        raw_response_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        normalized_artifact_path=normalized_ref,
        source_ref=raw_ref,
    )
    _write_json(project_root / normalized_ref, result.normalized_geojson)
    overpass_evidence = {
        "source_artifact": result.source_artifact.model_dump(mode="json"),
        "request": result.request.model_dump(mode="json"),
        "object_evidence": [
            item.model_dump(mode="json") for item in result.object_evidence
        ],
        "skipped_objects": [
            item.model_dump(mode="json") for item in result.skipped_objects
        ],
        "candidates": [item.model_dump(mode="json") for item in result.candidates],
        "counts": result.counts,
        "normalized_geojson_ref": normalized_ref,
        "boundary": {
            "candidate_only": True,
            "runtime_truth": False,
            "runtime_safety_truth": False,
            "live_network_required": True,
            "network_mode": request.network_mode,
            "phase1_runtime_mutation_allowed": False,
            "phase2_brain_writeback_allowed": False,
        },
    }
    _write_json(project_root / evidence_ref, overpass_evidence)
    updated = {
        **project,
        "overpass_evidence_ref": evidence_ref,
        "overpass_map_context_ref": normalized_ref,
        "overpass_raw_payload_ref": raw_ref,
        "overpass_query_ref": planned_request["query_body_ref"],
        "overpass_candidate_count": result.counts["candidates"],
        "overpass_skipped_object_count": result.counts["skipped"],
        "overpass_fetched_at": request.prepared_at or _utc_now(),
    }
    _write_json(project_path, updated)


def _build_layer_preparation_manifest(
    request: LayerPreparationRequest,
    *,
    workspace_file_mutation_allowed: bool,
) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    _validate_request(request)
    project_root = _resolve_project_root(request)
    project_path = project_root / "project.json"
    project = _load_json(project_path)
    route_summary = _load_project_ref(
        project_root,
        project,
        "route_summary_ref",
        required=True,
    )
    route_bbox = normalize_bbox_wgs84(request.bbox or route_summary["bbox_wgs84"])
    bbox = _expand_bbox_by_meters(route_bbox, request.route_corridor_m)
    normalized_layers = _normalize_layer_ids(request.layers)
    prepared_at = request.prepared_at or _utc_now()
    job_id = f"layer_preparation.{request.project_id}.{_job_timestamp(prepared_at)}"

    source_refs = _project_source_refs(project_root, project)
    route_corridor = _route_corridor_record(
        project=project,
        route_summary=route_summary,
        route_bbox=route_bbox,
        query_bbox=bbox,
        request=request,
    )
    layers = [
        _build_layer_record(
            layer_id,
            project_root=project_root,
            project=project,
            bbox=bbox,
            route_corridor=route_corridor,
            route_summary=route_summary,
            request=request,
            source_refs=source_refs,
        )
        for layer_id in normalized_layers
    ]
    validation = _validation_report(
        request=request,
        layers=layers,
        project_root=project_root,
        workspace_file_mutation_allowed=workspace_file_mutation_allowed,
    )
    counts = _layer_counts(layers, validation)
    network_calls_made = bool(project.get("overpass_fetched_at"))
    boundary = _boundary(
        request,
        workspace_file_mutation_allowed=workspace_file_mutation_allowed,
        external_api_calls_made=network_calls_made,
    )
    network_policy = _network_policy(request, network_calls_made=network_calls_made)
    stage_statuses = _stage_statuses(layers)
    outputs = dict(OUTPUT_REFS)

    manifest = {
        "artifact_kind": "pretrip_layer_preparation_manifest",
        "schema_version": LAYER_PREPARATION_VERSION,
        "job_id": job_id,
        "project_id": request.project_id,
        "profile": request.profile,
        "network_mode": request.network_mode,
        "requested_layers": list(request.layers),
        "normalized_layers": normalized_layers,
        "started_at": prepared_at,
        "finished_at": prepared_at,
        "route_bbox_wgs84": route_bbox,
        "bbox_wgs84": bbox,
        "route_corridor": route_corridor,
        "inputs": {
            "project_ref": "project.json",
            "source_refs": source_refs,
            "route_summary": {
                "route_name": route_summary.get("route_name"),
                "point_count": route_summary.get("point_count"),
                "distance_m": route_summary.get("distance_m"),
            },
        },
        "outputs": outputs,
        "network_policy": network_policy,
        "stage_statuses": stage_statuses,
        "counts": counts,
        "layers": layers,
        "validation": validation,
        "boundary": boundary,
        "notes": [
            (
                "LayerPreparationJob（圖層準備工作）writes pretrip workspace "
                "artifacts only."
            ),
            (
                "No live network calls are made in this slice; explicit-fetch "
                "only records policy intent."
            ),
            (
                "Large raster, DEM, GPX, and tile payloads are referenced by "
                "path/checksum when available, not embedded."
            ),
        ],
    }
    return manifest, project_root, project


def load_layer_preparation_manifest(project_root: Path) -> dict[str, Any] | None:
    project_path = Path(project_root) / "project.json"
    if not project_path.exists():
        raise FileNotFoundError(f"project.json not found: {project_path}")
    project = _load_json(project_path)
    manifest_ref = project.get("layer_preparation_manifest_ref")
    if not manifest_ref:
        return None
    manifest_path = Path(project_root) / manifest_ref
    if not manifest_path.exists():
        return None
    return _load_json(manifest_path)


def build_layer_preparation_not_prepared_view(
    project_id: str,
    *,
    project_root: Path,
) -> dict[str, Any]:
    project = _load_json(Path(project_root) / "project.json")
    route_summary = _load_project_ref(
        Path(project_root),
        project,
        "route_summary_ref",
        required=True,
    )
    bbox = normalize_bbox_wgs84(route_summary["bbox_wgs84"])
    route_corridor = _route_corridor_record(
        project=project,
        route_summary=route_summary,
        route_bbox=bbox,
        query_bbox=_expand_bbox_by_meters(bbox, 500.0),
        request=LayerPreparationRequest(project_id=project_id, project_root=project_root),
    )
    return {
        "artifact_kind": "pretrip_layer_preparation_summary",
        "schema_version": LAYER_PREPARATION_VERSION,
        "project_id": project_id,
        "source_id": f"layer_preparation.{project_id}.not_prepared",
        "source_path": "project.json#layer-preparation-not-prepared",
        "evidence_type": "pretrip_layer_preparation_summary",
        "status": "not_prepared",
        "route_bbox_wgs84": bbox,
        "bbox_wgs84": route_corridor["query_bbox_wgs84"],
        "route_corridor": route_corridor,
        "counts": {
            "layer_count": 0,
            "ready_layer_count": 0,
            "blocked_layer_count": 0,
            "missing_layer_count": 0,
            "warning_count": 0,
            "blocker_count": 0,
        },
        "layers": [],
        "network_policy": {
            "network_mode": "no-network",
            "allow_network_fetch": False,
            "network_calls_made": False,
        },
        "boundary": _boundary(
            LayerPreparationRequest(project_id=project_id, project_root=project_root),
            workspace_file_mutation_allowed=False,
        ),
        "notes": [
            (
                "LayerPreparationJob（圖層準備工作）has not been run for this "
                "workspace yet."
            )
        ],
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Prepare Scout pretrip map and evidence layers for a project workspace."
    )
    parser.add_argument("--project-id")
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--project-root", type=Path)
    parser.add_argument(
        "--layers",
        default=",".join(DEFAULT_LAYERS),
        help="Comma-separated layer ids, for example osm,overpass,terrain,imagery,weather.",
    )
    parser.add_argument(
        "--profile",
        choices=("mac-workstation", "pi-offline", "pi-online-explicit"),
        default="pi-offline",
    )
    parser.add_argument(
        "--network-mode",
        choices=("no-network", "explicit-fetch"),
        default="no-network",
    )
    parser.add_argument("--allow-network-fetch", action="store_true")
    parser.add_argument(
        "--bbox",
        help="Optional bbox as south,west,north,east. Defaults to route summary bbox.",
    )
    parser.add_argument("--route-corridor-m", type=float, default=500.0)
    parser.add_argument("--prepared-at")
    args = parser.parse_args(argv)

    if args.project_root is None and not args.project_id:
        parser.error("--project-id is required unless --project-root is supplied")
    layers = tuple(
        layer.strip()
        for layer in args.layers.split(",")
        if layer.strip()
    )
    bbox = _parse_cli_bbox(args.bbox) if args.bbox else None
    request = LayerPreparationRequest(
        project_id=args.project_id or Path(args.project_root).name,
        workspace_root=args.workspace_root,
        project_root=args.project_root,
        layers=layers,
        profile=args.profile,
        network_mode=args.network_mode,
        allow_network_fetch=args.allow_network_fetch,
        bbox=bbox,
        route_corridor_m=args.route_corridor_m,
        prepared_at=args.prepared_at,
    )
    manifest = run_layer_preparation(request)
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))


def _build_layer_record(
    layer_id: str,
    *,
    project_root: Path,
    project: dict[str, Any],
    bbox: dict[str, float],
    route_corridor: dict[str, Any],
    route_summary: dict[str, Any],
    request: LayerPreparationRequest,
    source_refs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    common = {
        "layer_id": layer_id,
        "adapter": f"pretrip_layer_preparation.{layer_id}",
        "adapter_version": LAYER_PREPARATION_VERSION,
        "bbox_wgs84": bbox,
        "route_corridor": route_corridor,
        "route_corridor_m": request.route_corridor_m,
        "network_policy": _network_policy(request),
        "source_refs": [],
        "output_refs": {},
        "counts": {},
        "warnings": [],
        "blockers": [],
        "stale_risk": "unknown",
    }
    if layer_id == "osm":
        return _osm_layer_record(common, bbox, request)
    if layer_id == "overpass":
        return _overpass_layer_record(
            common,
            project_root=project_root,
            project=project,
            request=request,
            route_corridor=route_corridor,
        )
    if layer_id == "terrain":
        return _project_ref_layer_record(
            common,
            project_root=project_root,
            project=project,
            ref_key="segment_dtm_coverage_ref",
            status_if_missing="missing_source",
            counts_from_payload=_terrain_counts,
            stale_risk="medium",
            missing_warning="Terrain/DTM coverage summary is missing.",
        )
    if layer_id == "imagery":
        return _imagery_layer_record(common, project)
    if layer_id == "weather":
        return _project_ref_layer_record(
            common,
            project_root=project_root,
            project=project,
            ref_key="weather_daylight_evidence_ref",
            status_if_missing="missing_source",
            counts_from_payload=_weather_counts,
            stale_risk="medium",
            missing_warning="Weather/daylight evidence summary is missing.",
        )
    if layer_id == "reference-tracks":
        return _project_ref_layer_record(
            common,
            project_root=project_root,
            project=project,
            ref_key="reference_tracks_ref",
            status_if_missing="missing_source",
            counts_from_payload=lambda payload: {
                "reference_track_count": payload.get("reference_track_count", 0)
            },
            stale_risk="low",
            output_refs={
                "reference_track_display_geometry_ref": project.get(
                    "reference_track_display_geometry_ref",
                    "",
                )
            },
            missing_warning="Reference track summary is missing.",
        )
    if layer_id == "route":
        record = {
            **common,
            "status": "ready_from_project_ref",
            "source_refs": [
                source_refs.get(
                    "route_summary_ref",
                    {"ref": project.get("route_summary_ref", "")},
                )
            ],
            "counts": {
                "route_point_count": route_summary.get("point_count", 0),
                "distance_m": route_summary.get("distance_m", 0),
            },
            "stale_risk": "low",
        }
        return _with_lifecycle(record)
    layer_ref_key = {
        "segments": "segment_candidates_ref",
        "checkpoints": "checkpoint_candidates_ref",
        "pois": "map_candidates_ref",
        "hazards": "map_candidates_ref",
        "corridors": "map_candidates_ref",
        "retreat": "retreat_routes_ref",
        "route-notes": "route_note_candidates_ref",
    }[layer_id]
    return _project_ref_layer_record(
        common,
        project_root=project_root,
        project=project,
        ref_key=layer_ref_key,
        status_if_missing="missing_source",
        counts_from_payload=lambda payload: _generic_project_counts(layer_id, payload),
        stale_risk="low",
        missing_warning=f"{layer_id} project ref is missing.",
    )


def _osm_layer_record(
    common: dict[str, Any],
    bbox: dict[str, float],
    request: LayerPreparationRequest,
) -> dict[str, Any]:
    contract = build_osm_basemap_contract(
        bbox,
        max_tiles=64,
        tile_url_template="/admin/tiles/osm/{z}/{x}/{y}.png",
    )
    record = {
        **common,
        "status": "projection_ready",
        "source_refs": [
            {
                "ref": "/admin/tiles/osm/{z}/{x}/{y}.png",
                "source_kind": "local_osm_tile_proxy",
                "external_network_required": False,
            }
        ],
        "output_refs": {
            "local_proxy_tile_url_template": "/admin/tiles/osm/{z}/{x}/{y}.png"
        },
        "counts": {
            "tile_count": contract["tile_count"],
            "zoom": contract["zoom"],
            "max_tiles": contract["max_tiles"],
        },
        "warnings": [
            (
                "Public OSM bulk/offline tile download is prohibited; this "
                "job records a local proxy/cache contract only."
            )
        ],
        "stale_risk": "medium",
    }
    if request.network_mode == "explicit-fetch":
        record["warnings"].append(
            "explicit-fetch was requested, but OSM tile fetching is not implemented in this slice."
        )
    return _with_lifecycle(record)


def _imagery_layer_record(
    common: dict[str, Any],
    project: dict[str, Any],
) -> dict[str, Any]:
    refs = [
        key
        for key in (
            "imagery_manifest_ref",
            "local_raster_manifest_ref",
            "raster_tile_manifest_ref",
        )
        if project.get(key)
    ]
    status = "ready_from_project_ref" if refs else "ready_with_fallback"
    warnings = [] if refs else [
        (
            "No local imagery raster manifest is registered; admin tile "
            "endpoint may render a deterministic fallback tile."
        )
    ]
    record = {
        **common,
        "status": status,
        "source_refs": [{"ref": project[key], "project_ref_key": key} for key in refs],
        "output_refs": {
            "local_raster_tile_url_template": (
                "/admin/tiles/imagery/{project_id}/{layer_id}/{z}/{x}/{y}.png"
            )
        },
        "counts": {
            "registered_raster_manifest_count": len(refs),
            "fallback_tile_available": not refs,
        },
        "warnings": warnings,
        "stale_risk": "medium",
    }
    return _with_lifecycle(record)


def _overpass_layer_record(
    common: dict[str, Any],
    *,
    project_root: Path,
    project: dict[str, Any],
    request: LayerPreparationRequest,
    route_corridor: dict[str, Any],
) -> dict[str, Any]:
    planned_request = _planned_overpass_request(
        bbox=common["bbox_wgs84"],
        request=request,
        route_corridor=route_corridor,
    )
    record = _project_ref_layer_record(
        common,
        project_root=project_root,
        project=project,
        ref_key="overpass_evidence_ref",
        status_if_missing="missing_source",
        counts_from_payload=_overpass_counts,
        stale_risk="medium",
        output_refs={
            "normalized_geojson_ref": project.get("overpass_map_context_ref", ""),
            "planned_query_ref": planned_request["query_body_ref"],
        },
        missing_warning="Overpass evidence is not available in this workspace.",
    )
    record["planned_request"] = planned_request
    record["route_corridor"] = route_corridor
    if project.get("overpass_fetched_at"):
        record["network_policy"] = _network_policy(request, network_calls_made=True)
        record["lifecycle"]["fetch"]["status"] = "completed_live_fetch"
        record["lifecycle"]["fetch"]["external_network_calls_made"] = True
        record["lifecycle"]["fetch"]["fetched_at"] = project["overpass_fetched_at"]
    record["lifecycle"]["fetch"]["planned_request_ref"] = planned_request[
        "query_body_ref"
    ]
    record["lifecycle"]["fetch"]["route_corridor_source"] = "golden_route_bbox"
    return record


def _project_ref_layer_record(
    common: dict[str, Any],
    *,
    project_root: Path,
    project: dict[str, Any],
    ref_key: str,
    status_if_missing: str,
    counts_from_payload: Any,
    stale_risk: str,
    output_refs: dict[str, str] | None = None,
    missing_warning: str,
) -> dict[str, Any]:
    ref = project.get(ref_key)
    warnings: list[str] = []
    blockers: list[str] = []
    source_refs: list[dict[str, Any]] = []
    counts: dict[str, Any] = {}
    status = status_if_missing
    if ref:
        path = project_root / ref
        if path.exists():
            payload = _load_json(path)
            source_refs.append(_source_ref(ref, path, ref_key))
            counts = counts_from_payload(payload)
            status = "ready_from_project_ref"
        else:
            warnings.append(f"{ref_key} points to a missing file: {ref}")
    else:
        warnings.append(missing_warning)
    record = {
        **common,
        "status": status,
        "source_refs": source_refs,
        "output_refs": output_refs or {},
        "counts": counts,
        "warnings": warnings,
        "blockers": blockers,
        "stale_risk": stale_risk,
    }
    return _with_lifecycle(record)


def _with_lifecycle(record: dict[str, Any]) -> dict[str, Any]:
    status = record["status"]
    source_available = bool(record.get("source_refs"))
    fetch_status = "skipped_no_network"
    if status == "ready_from_project_ref":
        fetch_status = "read_local_project_ref"
    elif status == "projection_ready":
        fetch_status = "not_required_local_proxy"
    elif status == "ready_with_fallback":
        fetch_status = "not_required_deterministic_fallback"
    elif status == "missing_source":
        fetch_status = "blocked_missing_source"
    record["lifecycle"] = {
        "plan": {"status": "completed", "layer_id": record["layer_id"]},
        "fetch": {
            "status": fetch_status,
            "external_network_calls_made": False,
        },
        "import": {
            "status": "completed" if source_available else "skipped",
            "source_ref_count": len(record.get("source_refs", [])),
        },
        "normalize": {
            "status": "completed" if status in READY_STATUSES else "skipped",
            "output_refs": record.get("output_refs", {}),
        },
        "summarize": {
            "status": "completed",
            "counts": record.get("counts", {}),
        },
        "validate": {
            "status": "passed" if not record.get("blockers") else "blocked",
            "warning_count": len(record.get("warnings", [])),
            "blocker_count": len(record.get("blockers", [])),
        },
        "project": {
            "status": "planned",
            "writes_workspace_outputs": True,
        },
    }
    return record


def _summary_from_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_kind": "pretrip_layer_preparation_summary",
        "schema_version": LAYER_PREPARATION_VERSION,
        "source_id": manifest["job_id"],
        "source_path": manifest["outputs"]["layer_preparation_summary_ref"],
        "evidence_type": "pretrip_layer_preparation_summary",
        "project_id": manifest["project_id"],
        "status": manifest["validation"]["status"],
        "profile": manifest["profile"],
        "network_mode": manifest["network_mode"],
        "prepared_at": manifest["finished_at"],
        "bbox_wgs84": manifest["bbox_wgs84"],
        "counts": manifest["counts"],
        "layers": [
            {
                "layer_id": layer["layer_id"],
                "status": layer["status"],
                "counts": layer["counts"],
                "warning_count": len(layer["warnings"]),
                "blocker_count": len(layer["blockers"]),
                "stale_risk": layer["stale_risk"],
            }
            for layer in manifest["layers"]
        ],
        "network_policy": manifest["network_policy"],
        "boundary": manifest["boundary"],
        "notes": manifest["notes"],
    }


def _adapter_manifest_from_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_kind": "pretrip_layer_adapter_manifest",
        "schema_version": LAYER_PREPARATION_VERSION,
        "job_id": manifest["job_id"],
        "project_id": manifest["project_id"],
        "adapters": [
            {
                "layer_id": layer["layer_id"],
                "adapter": layer["adapter"],
                "adapter_version": layer["adapter_version"],
                "status": layer["status"],
                "source_refs": layer["source_refs"],
                "output_refs": layer["output_refs"],
                "network_policy": layer["network_policy"],
                "lifecycle": layer["lifecycle"],
            }
            for layer in manifest["layers"]
        ],
        "boundary": manifest["boundary"],
    }


def _map_projection_from_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_kind": "pretrip_map_layer_projection",
        "schema_version": LAYER_PREPARATION_VERSION,
        "project_id": manifest["project_id"],
        "source_id": manifest["job_id"],
        "source_path": manifest["outputs"]["layer_map_projection_ref"],
        "evidence_type": "pretrip_map_layer_projection",
        "bbox_wgs84": manifest["bbox_wgs84"],
        "projection_only": True,
        "layers": [
            {
                "layer_id": layer["layer_id"],
                "status": layer["status"],
                "source_refs": layer["source_refs"],
                "output_refs": layer["output_refs"],
                "counts": layer["counts"],
            }
            for layer in manifest["layers"]
        ],
        "boundary": manifest["boundary"],
    }


def _debug_events_from_manifest(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    base_payload = {
        "project_id": manifest["project_id"],
        "job_id": manifest["job_id"],
        "profile": manifest["profile"],
        "network_mode": manifest["network_mode"],
        "network_calls_made": False,
        "projection_only": True,
        "runtime_safety_truth": False,
        "boundary": manifest["boundary"],
    }
    events: list[dict[str, Any]] = []

    def append(kind: str, summary: str, payload: dict[str, Any]) -> None:
        sequence = len(events) + 1
        events.append(
            {
                "event_id": (
                    f"debug_event.layer_preparation."
                    f"{manifest['project_id']}.{sequence:06d}"
                ),
                "session_id": f"layer_preparation.{manifest['project_id']}",
                "mission_id": None,
                "timestamp": manifest["finished_at"],
                "sequence": sequence,
                "kind": kind,
                "source": "pretrip_layer_preparation",
                "phase": "phase4",
                "severity": payload.pop("severity", "info"),
                "subject_ref": payload.pop("subject_ref", manifest["project_id"]),
                "correlation_refs": [manifest["job_id"]],
                "summary": summary,
                "payload": {**base_payload, **payload},
            }
        )

    append(
        "debug_session_started",
        "Layer preparation loaded pretrip project metadata.",
        {"subject_ref": f"project.{manifest['project_id']}"},
    )
    for layer in manifest["layers"]:
        severity = "warning" if layer["warnings"] else "info"
        if layer["blockers"]:
            severity = "error"
        append(
            "provider_status_recorded",
            f"Layer {layer['layer_id']} prepared with status {layer['status']}.",
            {
                "subject_ref": f"layer.{layer['layer_id']}",
                "layer_id": layer["layer_id"],
                "status": layer["status"],
                "counts": layer["counts"],
                "warnings": layer["warnings"],
                "blockers": layer["blockers"],
                "severity": severity,
            },
        )
    append(
        "debug_session_completed",
        "Layer preparation projected workspace layer readiness without runtime mutation.",
        {
            "subject_ref": manifest["job_id"],
            "status": manifest["validation"]["status"],
            "counts": manifest["counts"],
        },
    )
    return events


def _job_payload_from_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_kind": "pretrip_layer_preparation_job",
        "schema_version": LAYER_PREPARATION_VERSION,
        "job_id": manifest["job_id"],
        "project_id": manifest["project_id"],
        "profile": manifest["profile"],
        "network_mode": manifest["network_mode"],
        "requested_layers": manifest["requested_layers"],
        "normalized_layers": manifest["normalized_layers"],
        "started_at": manifest["started_at"],
        "finished_at": manifest["finished_at"],
        "stage_statuses": manifest["stage_statuses"],
        "outputs": manifest["outputs"],
        "boundary": manifest["boundary"],
    }


def _validation_report(
    *,
    request: LayerPreparationRequest,
    layers: list[dict[str, Any]],
    project_root: Path,
    workspace_file_mutation_allowed: bool,
) -> dict[str, Any]:
    warnings = [
        {
            "layer_id": layer["layer_id"],
            "message": warning,
        }
        for layer in layers
        for warning in layer.get("warnings", [])
    ]
    blockers = [
        {
            "layer_id": layer["layer_id"],
            "message": blocker,
        }
        for layer in layers
        for blocker in layer.get("blockers", [])
    ]
    if request.network_mode == "explicit-fetch" and not request.allow_network_fetch:
        blockers.append(
            {
                "layer_id": "network_policy",
                "message": (
                    "explicit-fetch requires allow_network_fetch=true; no "
                    "network calls were made."
                ),
            }
        )
    for layer in layers:
        if (
            layer["layer_id"] in HEAVY_LOCAL_LAYER_IDS
            and layer["status"] == "missing_source"
        ):
            warnings.append(
                {
                    "layer_id": layer["layer_id"],
                    "message": (
                        "Heavy local layer source is missing; Pi mode keeps "
                        "this as a warning unless project policy marks it required."
                    ),
                }
            )
    network_calls_made = any(
        layer.get("lifecycle", {})
        .get("fetch", {})
        .get("external_network_calls_made", False)
        for layer in layers
    )
    return {
        "artifact_kind": "pretrip_layer_validation_report",
        "schema_version": LAYER_PREPARATION_VERSION,
        "project_id": request.project_id,
        "status": "blocked" if blockers else "ready_with_warnings" if warnings else "ready",
        "project_root": str(project_root.resolve()),
        "warning_count": len(warnings),
        "blocker_count": len(blockers),
        "warnings": warnings,
        "blockers": blockers,
        "network_policy": _network_policy(request, network_calls_made=network_calls_made),
        "boundary": _boundary(
            request,
            workspace_file_mutation_allowed=workspace_file_mutation_allowed,
            external_api_calls_made=network_calls_made,
        ),
    }


def _layer_counts(
    layers: list[dict[str, Any]],
    validation: dict[str, Any],
) -> dict[str, Any]:
    return {
        "layer_count": len(layers),
        "ready_layer_count": sum(1 for layer in layers if layer["status"] in READY_STATUSES),
        "blocked_layer_count": sum(
            1
            for layer in layers
            if layer["status"].startswith("blocked") or layer.get("blockers")
        ),
        "missing_layer_count": sum(1 for layer in layers if layer["status"] == "missing_source"),
        "warning_count": validation["warning_count"],
        "blocker_count": validation["blocker_count"],
    }


def _stage_statuses(layers: list[dict[str, Any]]) -> dict[str, Any]:
    stages = ("plan", "fetch", "import", "normalize", "summarize", "validate", "project")
    return {
        stage: {
            "completed_count": sum(
                1
                for layer in layers
                if layer["lifecycle"][stage]["status"]
                in {
                    "completed",
                    "completed_live_fetch",
                    "passed",
                    "planned",
                    "read_local_project_ref",
                    "not_required_local_proxy",
                }
            ),
            "blocked_count": sum(
                1
                for layer in layers
                if "blocked" in layer["lifecycle"][stage]["status"]
            ),
            "skipped_count": sum(
                1
                for layer in layers
                if layer["lifecycle"][stage]["status"] == "skipped"
            ),
        }
        for stage in stages
    }


def _update_project_refs(
    project_path: Path,
    project: dict[str, Any],
    outputs: dict[str, str],
    prepared_at: str,
) -> None:
    updated = {
        **project,
        **outputs,
        "layer_preparation_updated_at": prepared_at,
        "layer_preparation_schema_version": LAYER_PREPARATION_VERSION,
    }
    _write_json(project_path, updated)


def _normalize_layer_ids(layers: tuple[str, ...]) -> list[str]:
    normalized: list[str] = []
    for raw in layers:
        layer_id = LAYER_ALIASES.get(raw.strip().lower(), raw.strip().lower())
        if layer_id not in ALLOWED_LAYERS:
            raise ValueError(f"unsupported layer id: {raw}")
        if layer_id not in normalized:
            normalized.append(layer_id)
    return normalized


def _project_source_refs(project_root: Path, project: dict[str, Any]) -> dict[str, dict[str, Any]]:
    refs: dict[str, dict[str, Any]] = {}
    for key, value in sorted(project.items()):
        if not key.endswith("_ref") or not isinstance(value, str):
            continue
        path = project_root / value
        refs[key] = _source_ref(value, path, key) if path.exists() else {
            "ref": value,
            "project_ref_key": key,
            "exists": False,
        }
    return refs


def _source_ref(ref: str, path: Path, ref_key: str) -> dict[str, Any]:
    stat = path.stat()
    return {
        "ref": ref,
        "project_ref_key": ref_key,
        "exists": True,
        "size_bytes": stat.st_size,
        "sha256": _sha256_file(path),
    }


def _overpass_counts(payload: dict[str, Any]) -> dict[str, Any]:
    counts = payload.get("counts", {})
    return {
        "candidate_count": counts.get("candidates", len(payload.get("candidates", []))),
        "skipped_object_count": counts.get("skipped", len(payload.get("skipped_objects", []))),
    }


def _terrain_counts(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "segment_count": payload.get("segment_count", 0),
        "candidate_tile_count": payload.get("candidate_tile_count", 0),
    }


def _weather_counts(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": payload.get("status", "unknown"),
        "external_api_calls_made": bool(payload.get("external_api_calls_made")),
        "hazard_note_count": len(
            (payload.get("weather_window") or {}).get("hazard_notes", [])
        ),
    }


def _generic_project_counts(layer_id: str, payload: Any) -> dict[str, Any]:
    if isinstance(payload, list):
        return {f"{layer_id.replace('-', '_')}_count": len(payload)}
    if not isinstance(payload, dict):
        return {f"{layer_id.replace('-', '_')}_count": 0}
    if layer_id in {"pois", "hazards", "corridors"}:
        counts = payload.get("counts", {})
        return {
            "corridor_candidates": counts.get("corridor_candidates", 0),
            "hazard_candidates": counts.get("hazard_candidates", 0),
            "poi_candidates": counts.get("poi_candidates", 0),
        }
    return payload.get("counts") or {f"{layer_id.replace('-', '_')}_count": 1}


def _route_corridor_record(
    *,
    project: dict[str, Any],
    route_summary: dict[str, Any],
    route_bbox: dict[str, float],
    query_bbox: dict[str, float],
    request: LayerPreparationRequest,
) -> dict[str, Any]:
    route_geometry_refs = {
        key: project[key]
        for key in (
            "segment_display_geometry_ref",
            "map_context_ref",
            "reference_track_display_geometry_ref",
        )
        if project.get(key)
    }
    return {
        "route_ref": route_summary.get("artifact_id"),
        "route_summary_ref": project.get("route_summary_ref"),
        "route_geometry_refs": route_geometry_refs,
        "corridor_m": request.route_corridor_m,
        "route_bbox_wgs84": route_bbox,
        "query_bbox_wgs84": query_bbox,
        "bbox_boundary": query_bbox,
        "basis": "selected_golden_route_reference",
        "notes": (
            "Overpass evidence（OSM 向量證據）is planned from the selected "
            "golden route corridor/bbox and remains candidate-only."
        ),
    }


def _planned_overpass_request(
    *,
    bbox: dict[str, float],
    request: LayerPreparationRequest,
    route_corridor: dict[str, Any],
) -> dict[str, Any]:
    return {
        "source": "route_corridor_bbox",
        "query_body_ref": "outputs/layers/plans/overpass_query.ql",
        "query_body": _build_overpass_query_body(bbox),
        "bbox_wgs84": bbox,
        "route_corridor": route_corridor,
        "endpoint": "https://overpass-api.de/api/interpreter",
        "network_mode": request.network_mode,
        "allow_network_fetch": request.allow_network_fetch,
        "network_calls_made": False,
        "live_fetch_stage": "fetch",
        "raw_payload_target_ref": "normalized/map/overpass_phase_a_raw.json",
        "normalized_artifact_target_ref": "normalized/map/overpass_vector_evidence.geojson",
    }


def _build_overpass_query_body(bbox: dict[str, float]) -> str:
    south = bbox["south"]
    west = bbox["west"]
    north = bbox["north"]
    east = bbox["east"]
    bbox_expr = f"({south:.7f},{west:.7f},{north:.7f},{east:.7f})"
    return "\n".join(
        [
            "[out:json][timeout:40];",
            "(",
            f'  way["highway"~"^(path|footway|track|steps|bridleway|pedestrian)$"]{bbox_expr};',
            f'  relation["type"="route"]["route"="hiking"]{bbox_expr};',
            f'  relation["route"="hiking"]{bbox_expr};',
            f'  node["tourism"~"^(wilderness_hut|alpine_hut)$"]{bbox_expr};',
            f'  node["amenity"~"^(shelter|drinking_water|parking)$"]{bbox_expr};',
            f'  node["natural"~"^(spring|peak)$"]{bbox_expr};',
            f'  way["natural"~"^(cliff|scree|bare_rock)$"]{bbox_expr};',
            f'  way["geological"="landslide"]{bbox_expr};',
            ");",
            "out tags geom;",
            "",
        ]
    )


def _expand_bbox_by_meters(
    bbox: dict[str, float],
    corridor_m: float,
) -> dict[str, float]:
    mid_lat = (bbox["south"] + bbox["north"]) / 2.0
    lat_delta = corridor_m / 111_320.0
    lon_scale = max(math.cos(math.radians(mid_lat)), 0.01)
    lon_delta = corridor_m / (111_320.0 * lon_scale)
    return normalize_bbox_wgs84(
        {
            "south": max(-90.0, bbox["south"] - lat_delta),
            "west": max(-180.0, bbox["west"] - lon_delta),
            "north": min(90.0, bbox["north"] + lat_delta),
            "east": min(180.0, bbox["east"] + lon_delta),
        }
    )


def _write_layer_plan_files(project_root: Path, manifest: dict[str, Any]) -> None:
    for layer in manifest.get("layers", []):
        planned_request = layer.get("planned_request")
        if not planned_request or layer.get("layer_id") != "overpass":
            continue
        _write_text(
            project_root / planned_request["query_body_ref"],
            planned_request["query_body"],
        )


def _fetch_overpass_raw_payload(planned_request: dict[str, Any]) -> tuple[bytes, int]:
    encoded = urllib.parse.urlencode({"data": planned_request["query_body"]}).encode(
        "utf-8"
    )
    request = urllib.request.Request(
        planned_request["endpoint"],
        data=encoded,
        headers={
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
            "User-Agent": "Scout-Fusion-Pretrip-Alpha/0.1",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read(), int(response.status)


def _reject_fixture_fetch(project_root: Path) -> None:
    normalized = project_root.resolve().as_posix()
    if "/tests/fixtures/" in normalized:
        raise ValueError("explicit Overpass fetch cannot write repo fixtures")


def _network_policy(
    request: LayerPreparationRequest,
    *,
    network_calls_made: bool = False,
) -> dict[str, Any]:
    return {
        "network_mode": request.network_mode,
        "allow_network_fetch": request.allow_network_fetch,
        "network_calls_made": network_calls_made,
        "external_api_calls_made": network_calls_made,
        "live_fetch_stage": "fetch",
        "explicit_fetch_requires_allow_network_fetch": True,
        "public_osm_bulk_tile_download_allowed": False,
    }


def _boundary(
    request: LayerPreparationRequest,
    *,
    workspace_file_mutation_allowed: bool,
    external_api_calls_made: bool = False,
) -> dict[str, Any]:
    return {
        "pretrip_candidate_evidence_only": True,
        "projection_only": True,
        "runtime_safety_truth": False,
        "source_mutation_allowed": False,
        "package_mutation_allowed": False,
        "mission_graph_mutation_allowed": False,
        "final_mission_graph_compiled": False,
        "phase1_runtime_mutation_allowed": False,
        "phase2_writeback_allowed": False,
        "phase2_brain_writeback_allowed": False,
        "incident_store_mutation_allowed": False,
        "real_outbound_transport_allowed": False,
        "workspace_file_mutation_allowed": workspace_file_mutation_allowed,
        "fixture_file_mutation_allowed": False,
        "large_raw_raster_copied_to_repo": False,
        "raw_gpx_embedded_in_json": False,
        "network_calls_allowed": (
            request.network_mode == "explicit-fetch"
            and request.allow_network_fetch
        ),
        "external_api_calls_made": external_api_calls_made,
    }


def _validate_request(request: LayerPreparationRequest) -> None:
    _validate_project_id(request.project_id)
    if request.project_root is None and request.workspace_root is None:
        raise ValueError("workspace_root or project_root is required")
    if request.route_corridor_m <= 0:
        raise ValueError("route_corridor_m must be greater than 0")
    _normalize_layer_ids(request.layers)
    if request.profile == "pi-online-explicit" and request.network_mode != "explicit-fetch":
        raise ValueError("pi-online-explicit requires network_mode=explicit-fetch")


def _validate_project_id(project_id: str) -> None:
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-")
    if (
        not project_id
        or project_id in {".", ".."}
        or any(char not in allowed for char in project_id)
    ):
        raise ValueError(f"project_id contains unsafe characters: {project_id}")


def _resolve_project_root(request: LayerPreparationRequest) -> Path:
    if request.project_root is not None:
        project_root = request.project_root.expanduser().resolve()
    else:
        project_root = (request.workspace_root.expanduser() / request.project_id).resolve()
    project_path = project_root / "project.json"
    if not project_path.exists():
        raise FileNotFoundError(f"project.json not found: {project_path}")
    project = _load_json(project_path)
    if project.get("project_id") != request.project_id:
        raise ValueError(
            f"project_id mismatch: expected {request.project_id}, found {project.get('project_id')}"
        )
    return project_root


def _load_project_ref(
    project_root: Path,
    project: dict[str, Any],
    ref_key: str,
    *,
    required: bool,
) -> Any:
    ref = project.get(ref_key)
    if not ref:
        if required:
            raise KeyError(ref_key)
        return None
    path = project_root / str(ref)
    if not path.exists():
        if required:
            raise FileNotFoundError(f"{ref_key} not found: {path}")
        return None
    return _load_json(path)


def _parse_cli_bbox(value: str) -> dict[str, float]:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 4:
        raise ValueError("--bbox must be south,west,north,east")
    south, west, north, east = [float(part) for part in parts]
    return {"south": south, "west": west, "north": north, "east": east}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, events: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )


def _write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def _write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _job_timestamp(value: str) -> str:
    return (
        value.replace(":", "")
        .replace("-", "")
        .replace("+", "")
        .replace(".", "")
        .replace("Z", "")
    )


if __name__ == "__main__":
    main()
