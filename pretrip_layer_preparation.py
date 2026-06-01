from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from admin_basemap_tiles import build_osm_basemap_contract, normalize_bbox_wgs84
from pretrip_models import RouteBBox
from pretrip_overpass_ingest import import_overpass_evidence_candidates


LAYER_PREPARATION_VERSION = "0.1.0"
RISK_PROVENANCE_STAMP_VERSION = "pretrip_risk_provenance.v0.1"
LayerProfile = Literal["mac-workstation", "pi-offline", "pi-online-explicit"]
NetworkMode = Literal["no-network", "explicit-fetch"]
AiMode = Literal["fixture-or-precomputed", "pydantic-cloud-explicit"]
DEFAULT_SCOUT_DATA_ROOT = Path("/data/scout")

DEFAULT_LAYERS = (
    "osm",
    "overpass",
    "terrain",
    "risk-score",
    "risk-ribbon",
    "risk-heatmap",
    "risk-delta",
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
    "map_preparation_summary_ref": "outputs/layers/map_preparation_summary.json",
    "layer_adapter_manifest_ref": "outputs/layers/layer_adapter_manifest.json",
    "layer_validation_report_ref": "outputs/layers/layer_validation_report.json",
    "web_case_query_plan_ref": "outputs/layers/plans/web_case_query_plan.json",
    "raster_label_plan_ref": "outputs/layers/plans/raster_label_plan.json",
    "overpass_vector_evidence_ref": (
        "outputs/layers/normalized/overpass_vector_evidence.geojson"
    ),
    "terrain_route_samples_ref": (
        "outputs/layers/normalized/terrain_route_samples.geojson"
    ),
    "web_case_evidence_ref": "outputs/layers/normalized/web_case_evidence.json",
    "raster_label_evidence_ref": (
        "outputs/layers/normalized/raster_label_evidence.geojson"
    ),
    "gis_semantic_input_bundle_ref": (
        "outputs/layers/semantic/gis_semantic_input_bundle.json"
    ),
    "gis_perception_ai_judgements_ref": (
        "outputs/layers/semantic/gis_perception_ai_judgements.json"
    ),
    "gis_checkpoint_candidates_ref": (
        "outputs/layers/candidates/gis_checkpoint_candidates.json"
    ),
    "ln_proposals_ref": "outputs/layers/candidates/ln_proposals.json",
    "poi_candidates_ref": "outputs/layers/candidates/poi_candidates.json",
    "terrain_risk_candidates_ref": (
        "outputs/layers/candidates/terrain_risk_candidates.json"
    ),
    "detour_route_candidates_ref": (
        "outputs/layers/candidates/detour_route_candidates.json"
    ),
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
    "risk-score",
    "risk-ribbon",
    "risk-heatmap",
    "risk-delta",
}
LAYER_ALIASES = {
    "dem": "terrain",
    "dtm": "terrain",
    "risk": "risk-score",
    "route-risk": "risk-score",
    "risk-score-map": "risk-score",
    "risk-ribbon-map": "risk-ribbon",
    "route-risk-ribbon": "risk-ribbon",
    "calibrated-risk": "risk-heatmap",
    "calibrated-risk-heatmap": "risk-heatmap",
    "risk-heat": "risk-heatmap",
    "risk-difference": "risk-delta",
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
    "planned_no_network",
}
HEAVY_LOCAL_LAYER_IDS = {"terrain", "imagery"}
SCOUT_RISK_OUTPUT_SOURCES = {
    "chilai_nanhua_day1": (
        Path(__file__).resolve().parent
        / "scout-risk-engine"
        / "scout_codex_package"
        / "out"
        / "chilai_overpass"
    )
}
SCOUT_RISK_OUTPUT_REFS = {
    "risk_route_profile_ref": "outputs/risk/route_risk.geojson",
    "risk_route_profile_csv_ref": "outputs/risk/route_risk.csv",
    "risk_route_profile_metadata_ref": "outputs/risk/route_risk.metadata.json",
    "risk_score_points_ref": "outputs/risk/risk_score_points.geojson",
    "risk_score_points_csv_ref": "outputs/risk/risk_score_points.csv",
    "risk_score_points_xyz_ref": "outputs/risk/risk_score_points.xyz",
    "risk_score_points_metadata_ref": "outputs/risk/risk_score_points.metadata.json",
    "risk_ribbon_ref": "outputs/risk/risk_ribbon.geojson",
    "risk_ribbon_metadata_ref": "outputs/risk/risk_ribbon.metadata.json",
}
CALIBRATED_RISK_OUTPUT_REFS = {
    "risk_attribution_diagnostic_ref": "outputs/risk/risk_attribution_diagnostic.json",
    "excluded_extreme_warning_cp_proposals_ref": (
        "outputs/risk/excluded_extreme_warning_cp_proposals.json"
    ),
    "calibrated_risk_heatmap_ref": "outputs/risk/calibrated_risk_heatmap.geojson",
    "calibrated_risk_heatmap_metadata_ref": (
        "outputs/risk/calibrated_risk_heatmap.metadata.json"
    ),
}


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
    route_evidence_bundle: Path | None = None
    route_corridor_m: float = 500.0
    reference_track_corridor_m: float = 300.0
    ai_mode: AiMode = "fixture-or-precomputed"
    ai_output_policy: str = "hash-and-summary"
    prepared_at: str | None = None


def run_layer_preparation(request: LayerPreparationRequest) -> dict[str, Any]:
    _maybe_fetch_overpass_evidence(request)
    manifest, project_root, project = _build_layer_preparation_manifest(
        request,
        workspace_file_mutation_allowed=True,
    )
    summary = _summary_from_manifest(manifest)
    map_preparation_summary = _map_preparation_summary_from_manifest(manifest)
    adapter_manifest = _adapter_manifest_from_manifest(manifest)
    map_projection = _map_projection_from_manifest(manifest)
    debug_events = _debug_events_from_manifest(manifest)
    job_payload = _job_payload_from_manifest(manifest)
    semantic_input_bundle = _build_gis_semantic_input_bundle(
        project_root=project_root,
        project=project,
        manifest=manifest,
        route_evidence_bundle=manifest["inputs"]["route_evidence_bundle"],
        gpx_filter=manifest["inputs"]["gpx_speed_filter"],
        source_refs=manifest["inputs"]["source_refs"],
    )
    semantic_judgements = _build_gis_perception_ai_judgements(
        manifest=manifest,
        semantic_input_bundle=semantic_input_bundle,
    )
    layer_candidate_artifacts = _build_layer_candidate_artifacts(
        project_root=project_root,
        project=project,
        manifest=manifest,
        semantic_input_bundle=semantic_input_bundle,
        semantic_judgements=semantic_judgements,
    )
    outputs = manifest["outputs"]

    _write_json(project_root / outputs["layer_preparation_manifest_ref"], manifest)
    _write_json(project_root / outputs["layer_preparation_job_ref"], job_payload)
    _write_json(project_root / outputs["layer_preparation_summary_ref"], summary)
    _write_json(project_root / outputs["map_preparation_summary_ref"], map_preparation_summary)
    _write_json(project_root / outputs["layer_adapter_manifest_ref"], adapter_manifest)
    _write_json(project_root / outputs["layer_validation_report_ref"], manifest["validation"])
    _write_json(project_root / outputs["gis_semantic_input_bundle_ref"], semantic_input_bundle)
    _write_json(project_root / outputs["gis_perception_ai_judgements_ref"], semantic_judgements)
    for ref_key, artifact in layer_candidate_artifacts.items():
        _write_json(project_root / outputs[ref_key], artifact)
    _write_json(project_root / outputs["layer_map_projection_ref"], map_projection)
    _write_jsonl(project_root / outputs["layer_debug_projection_events_ref"], debug_events)
    _write_layer_plan_files(project_root, manifest)
    _write_map_preparation_spec_artifacts(project_root, manifest)
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
    route_evidence_bundle = _route_evidence_bundle_context(
        project_root=project_root,
        project=project,
        request=request,
    )
    route_bbox = normalize_bbox_wgs84(request.bbox or route_summary["bbox_wgs84"])
    bbox = _bbox_from_route_evidence_bundle(route_evidence_bundle) or _expand_bbox_by_meters(
        route_bbox,
        request.route_corridor_m,
    )
    normalized_layers = _normalize_layer_ids(request.layers)
    prepared_at = request.prepared_at or _utc_now()
    job_id = f"layer_preparation.{request.project_id}.{_job_timestamp(prepared_at)}"
    risk_layers_requested = bool(
        {"risk-score", "risk-ribbon", "risk-heatmap", "risk-delta"} & set(normalized_layers)
    )
    if workspace_file_mutation_allowed and risk_layers_requested:
        project = _sync_scout_risk_outputs(
            project_root=project_root,
            project=project,
            prepared_at=prepared_at,
        )
        project = _sync_calibrated_risk_outputs(
            project_root=project_root,
            project=project,
        )
    if workspace_file_mutation_allowed and "overpass" in normalized_layers:
        _stamp_overpass_evidence_provenance(project_root=project_root, project=project)
    project = _infer_local_imagery_project_refs(
        project_root=project_root,
        project=project,
        allow_manifest_copy=workspace_file_mutation_allowed,
    )

    source_refs = _project_source_refs(project_root, project)
    gpx_filter = _gpx_filter_context(project_root, project)
    route_corridor = _route_corridor_record(
        project=project,
        route_summary=route_summary,
        route_bbox=route_bbox,
        query_bbox=bbox,
        request=request,
        gpx_filter=gpx_filter,
        route_evidence_bundle=route_evidence_bundle,
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
            gpx_filter=gpx_filter,
        )
        for layer_id in normalized_layers
    ]
    validation = _validation_report(
        request=request,
        layers=layers,
        project_root=project_root,
        workspace_file_mutation_allowed=workspace_file_mutation_allowed,
        route_evidence_bundle=route_evidence_bundle,
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
            "gpx_speed_filter": gpx_filter,
            "route_evidence_bundle": route_evidence_bundle,
        },
        "ai_policy": {
            "ai_mode": request.ai_mode,
            "ai_output_policy": request.ai_output_policy,
            "candidate_only": True,
            "runtime_safety_truth": False,
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
            (
                "Route, checkpoint, segment, and reference-track layers use "
                "the workspace project refs; when gpx_speed_filter_report_ref "
                "is present it is recorded as the filter provenance for those layers."
            ),
        ],
    }
    semantic_input_bundle = _build_gis_semantic_input_bundle(
        project_root=project_root,
        project=project,
        manifest=manifest,
        route_evidence_bundle=route_evidence_bundle,
        gpx_filter=gpx_filter,
        source_refs=source_refs,
    )
    manifest["semantic_input_bundle"] = {
        "source_ref": outputs["gis_semantic_input_bundle_ref"],
        "artifact_kind": semantic_input_bundle["artifact_kind"],
        "schema_version": semantic_input_bundle["schema_version"],
        "evidence_item_count": semantic_input_bundle["counts"]["evidence_item_count"],
        "source_kind_counts": semantic_input_bundle["counts"]["source_kind_counts"],
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    semantic_judgements = _build_gis_perception_ai_judgements(
        manifest=manifest,
        semantic_input_bundle=semantic_input_bundle,
    )
    manifest["semantic_ai_judgements"] = {
        "source_ref": outputs["gis_perception_ai_judgements_ref"],
        "artifact_kind": semantic_judgements["artifact_kind"],
        "schema_version": semantic_judgements["schema_version"],
        "judgement_count": semantic_judgements["judgement_count"],
        "input_bundle_ref": semantic_judgements["input_bundle_ref"],
        "live_model_call_performed": False,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    layer_candidate_artifacts = _build_layer_candidate_artifacts(
        project_root=project_root,
        project=project,
        manifest=manifest,
        semantic_input_bundle=semantic_input_bundle,
        semantic_judgements=semantic_judgements,
    )
    manifest["layer_candidate_artifacts"] = {
        ref_key: {
            "source_ref": outputs[ref_key],
            "artifact_kind": artifact["artifact_kind"],
            "schema_version": artifact["schema_version"],
            "candidate_count": artifact["counts"]["candidate_count"],
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
        for ref_key, artifact in layer_candidate_artifacts.items()
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
    parser.add_argument(
        "--route-evidence-bundle",
        type=Path,
        help=(
            "Route evidence bundle ref/path from the historical GPX importer. "
            "Relative paths are resolved under project root."
        ),
    )
    parser.add_argument("--route-corridor-m", type=float, default=500.0)
    parser.add_argument("--reference-track-corridor-m", type=float, default=300.0)
    parser.add_argument(
        "--ai-mode",
        choices=("fixture-or-precomputed", "pydantic-cloud-explicit"),
        default="fixture-or-precomputed",
    )
    parser.add_argument("--ai-output-policy", default="hash-and-summary")
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
        route_evidence_bundle=args.route_evidence_bundle,
        route_corridor_m=args.route_corridor_m,
        reference_track_corridor_m=args.reference_track_corridor_m,
        ai_mode=args.ai_mode,
        ai_output_policy=args.ai_output_policy,
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
    gpx_filter: dict[str, Any],
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
    if layer_id == "risk-score":
        return _risk_score_layer_record(
            common,
            project_root=project_root,
            project=project,
        )
    if layer_id == "risk-ribbon":
        return _risk_ribbon_layer_record(
            common,
            project_root=project_root,
            project=project,
        )
    if layer_id == "risk-heatmap":
        return _risk_heatmap_layer_record(
            common,
            project_root=project_root,
            project=project,
        )
    if layer_id == "risk-delta":
        return _risk_delta_layer_record(
            common,
            project_root=project_root,
            project=project,
        )
    if layer_id == "imagery":
        return _imagery_layer_record(
            common,
            project=project,
            project_root=project_root,
        )
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
        return _with_gpx_filter_provenance(
            _project_ref_layer_record(
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
            ),
            gpx_filter=gpx_filter,
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
        return _with_gpx_filter_provenance(_with_lifecycle(record), gpx_filter=gpx_filter)
    layer_ref_key = {
        "segments": "segment_candidates_ref",
        "checkpoints": "checkpoint_candidates_ref",
        "pois": "map_candidates_ref",
        "hazards": "map_candidates_ref",
        "corridors": "map_candidates_ref",
        "retreat": "retreat_routes_ref",
        "route-notes": "normalized_route_note_candidates_ref",
    }[layer_id]
    record = _project_ref_layer_record(
        common,
        project_root=project_root,
        project=project,
        ref_key=layer_ref_key,
        status_if_missing="missing_source",
        counts_from_payload=lambda payload: _generic_project_counts(layer_id, payload),
        stale_risk="low",
        missing_warning=f"{layer_id} project ref is missing.",
    )
    if (
        layer_id == "route-notes"
        and project.get("route_note_candidates_ref")
        and project.get("route_note_candidates_ref") != project.get(layer_ref_key)
    ):
        legacy_ref = project["route_note_candidates_ref"]
        legacy_path = project_root / legacy_ref
        if legacy_path.exists():
            record["source_refs"].append(
                _source_ref(legacy_ref, legacy_path, "route_note_candidates_ref")
            )
            _refresh_lifecycle(record)
    if layer_id in {"segments", "checkpoints"}:
        return _with_gpx_filter_provenance(record, gpx_filter=gpx_filter)
    return record


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
        "policy_notes": [
            (
                "Public OSM bulk/offline tile download is prohibited; this "
                "job records a local proxy/cache contract only."
            )
        ],
        "warnings": [],
        "stale_risk": "medium",
    }
    if request.network_mode == "explicit-fetch":
        record["warnings"].append(
            "explicit-fetch was requested, but OSM tile fetching is not implemented in this slice."
        )
    return _with_lifecycle(record)


def _infer_local_imagery_project_refs(
    *,
    project_root: Path,
    project: dict[str, Any],
    allow_manifest_copy: bool,
) -> dict[str, Any]:
    project_id = str(project.get("project_id") or project_root.name)
    manifest_dir = project_root / "outputs" / "layers" / "manifests"
    local_manifest_ref = (
        f"outputs/layers/manifests/{project_id}.local_raster_source_manifest.json"
    )
    tile_plan_ref = (
        f"outputs/layers/manifests/{project_id}.raster_tile_pyramid_plan.json"
    )
    local_manifest_path = project_root / local_manifest_ref
    tile_plan_path = project_root / tile_plan_ref
    if allow_manifest_copy:
        _copy_known_local_imagery_manifests(
            project_id=project_id,
            destination_dir=manifest_dir,
            local_manifest_path=local_manifest_path,
            tile_plan_path=tile_plan_path,
        )
    if not local_manifest_path.exists() and not tile_plan_path.exists():
        return project

    updated = dict(project)
    if local_manifest_path.exists():
        updated.setdefault("imagery_manifest_ref", local_manifest_ref)
        updated.setdefault("local_raster_manifest_ref", local_manifest_ref)
        local_manifest = _load_json(local_manifest_path)
        source_file = local_manifest.get("source_file") or {}
        handoff = local_manifest.get("handoff") or {}
        source_path = source_file.get("path") or handoff.get("scout_source_path")
        kmz_path = handoff.get("scout_kmz_path")
        if source_path:
            updated.setdefault("imagery_source_tiff_ref", source_path)
        if kmz_path:
            updated.setdefault("imagery_source_kmz_ref", kmz_path)
        if local_manifest.get("source_kind"):
            updated.setdefault(
                "imagery_source_kind",
                "user_provided_local_geotiff",
            )
    if tile_plan_path.exists():
        updated.setdefault("raster_tile_manifest_ref", tile_plan_ref)
        tile_plan = _load_json(tile_plan_path)
        if tile_plan.get("cache_root"):
            updated.setdefault("imagery_tile_cache_root", tile_plan["cache_root"])
    return updated


def _copy_known_local_imagery_manifests(
    *,
    project_id: str,
    destination_dir: Path,
    local_manifest_path: Path,
    tile_plan_path: Path,
) -> None:
    source_name = f"{project_id}.local_raster_source_manifest.json"
    tile_name = f"{project_id}.raster_tile_pyramid_plan.json"
    candidates = [
        (
            DEFAULT_SCOUT_DATA_ROOT
            / "admin"
            / "pretrip-workspaces"
            / project_id
            / "outputs"
            / "layers"
            / "manifests"
        ),
        (
            DEFAULT_SCOUT_DATA_ROOT
            / "offline-map-handoff-stash"
            / project_id
            / "outputs"
            / "layers"
            / "manifests"
        ),
    ]
    handoff_path = DEFAULT_SCOUT_DATA_ROOT / "offline_map_handoff_manifest.json"
    if handoff_path.exists():
        try:
            handoff = _load_json(handoff_path)
        except (OSError, json.JSONDecodeError):
            handoff = {}
        manifest_paths = handoff.get("manifests") or {}
        for key in ("source_manifest", "tile_plan"):
            value = manifest_paths.get(key)
            if value:
                candidates.append(Path(value).parent)

    for source_dir in candidates:
        if not local_manifest_path.exists():
            source = source_dir / source_name
            if source.exists():
                destination_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, local_manifest_path)
        if not tile_plan_path.exists():
            source = source_dir / tile_name
            if source.exists():
                destination_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, tile_plan_path)
        if local_manifest_path.exists() and tile_plan_path.exists():
            return


def _imagery_layer_record(
    common: dict[str, Any],
    *,
    project: dict[str, Any],
    project_root: Path,
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
    record.update(_local_raster_layer_metadata(project_root=project_root, project=project))
    return _with_lifecycle(record)


def _local_raster_layer_metadata(
    *,
    project_root: Path,
    project: dict[str, Any],
) -> dict[str, Any]:
    local_ref = project.get("local_raster_manifest_ref") or project.get(
        "imagery_manifest_ref"
    )
    tile_ref = project.get("raster_tile_manifest_ref")
    local_manifest = _load_project_ref_by_value(project_root, local_ref)
    tile_manifest = _load_project_ref_by_value(project_root, tile_ref)
    bbox = _normalized_optional_bbox(
        (local_manifest or {}).get("georeference", {}).get("bbox_wgs84")
    ) or _normalized_optional_bbox((tile_manifest or {}).get("bbox_wgs84"))

    metadata: dict[str, Any] = {}
    if local_ref:
        metadata["local_raster_manifest_ref"] = local_ref
    if tile_ref:
        metadata["raster_tile_manifest_ref"] = tile_ref
    if bbox:
        metadata["raster_bbox_wgs84"] = bbox
        metadata["raster_coverage_policy"] = "render_intersecting_tiles_only"
    if tile_manifest:
        for source_key, target_key in (
            ("zoom_range", "raster_tile_zoom_range"),
            ("cache_root", "raster_tile_cache_root"),
            ("total_tile_count", "raster_tile_count"),
        ):
            if source_key in tile_manifest:
                metadata[target_key] = tile_manifest[source_key]
    return metadata


def _risk_score_layer_record(
    common: dict[str, Any],
    *,
    project_root: Path,
    project: dict[str, Any],
) -> dict[str, Any]:
    metadata_ref = project.get("risk_score_points_metadata_ref", "")
    route_metadata_ref = project.get("risk_route_profile_metadata_ref", "")
    score_ref = project.get("risk_score_points_ref", "")
    route_ref = project.get("risk_route_profile_ref", "")
    warnings: list[str] = []
    source_refs: list[dict[str, Any]] = []
    counts: dict[str, Any] = {}
    status = "missing_source"

    metadata_path = project_root / metadata_ref if metadata_ref else None
    if metadata_path is not None and metadata_path.exists():
        metadata = _load_json(metadata_path)
        source_refs.append(
            _source_ref(
                metadata_ref,
                metadata_path,
                "risk_score_points_metadata_ref",
            )
        )
        counts.update(_risk_score_counts(metadata))
        status = "ready_from_project_ref"
    else:
        warnings.append(
            "Scout Risk Engine risk-score metadata is missing; run layer preparation with risk-score after route risk generation."
        )

    for ref_key, ref in (
        ("risk_score_points_ref", score_ref),
        ("risk_route_profile_ref", route_ref),
        ("risk_route_profile_metadata_ref", route_metadata_ref),
    ):
        if not ref:
            continue
        path = project_root / ref
        if path.exists():
            source_refs.append(_source_ref(ref, path, ref_key))
        else:
            warnings.append(f"{ref_key} points to a missing file: {ref}")

    record = {
        **common,
        "status": status,
        "source_refs": source_refs,
        "output_refs": {
            key: project.get(key, "")
            for key in SCOUT_RISK_OUTPUT_REFS
            if project.get(key)
        },
        "counts": counts,
        "warnings": warnings,
        "blockers": [],
        "stale_risk": "medium",
        "score_profile": project.get(
            "risk_score_source_profile",
            "scout_risk_engine_overpass_route_profile",
        ),
    }
    return _with_lifecycle(record)


def _risk_ribbon_layer_record(
    common: dict[str, Any],
    *,
    project_root: Path,
    project: dict[str, Any],
) -> dict[str, Any]:
    metadata_ref = project.get("risk_ribbon_metadata_ref", "")
    ribbon_ref = project.get("risk_ribbon_ref", "")
    warnings: list[str] = []
    source_refs: list[dict[str, Any]] = []
    counts: dict[str, Any] = {}
    status = "missing_source"

    metadata_path = project_root / metadata_ref if metadata_ref else None
    if metadata_path is not None and metadata_path.exists():
        metadata = _load_json(metadata_path)
        source_refs.append(
            _source_ref(
                metadata_ref,
                metadata_path,
                "risk_ribbon_metadata_ref",
            )
        )
        counts.update(_risk_ribbon_counts(metadata))
        status = "ready_from_project_ref"
    else:
        warnings.append(
            "Scout Risk Engine risk-ribbon metadata is missing; run layer preparation with risk-ribbon after route risk generation."
        )

    if ribbon_ref:
        ribbon_path = project_root / ribbon_ref
        if ribbon_path.exists():
            source_refs.append(
                _source_ref(ribbon_ref, ribbon_path, "risk_ribbon_ref")
            )
        else:
            warnings.append(f"risk_ribbon_ref points to a missing file: {ribbon_ref}")

    record = {
        **common,
        "status": status,
        "source_refs": source_refs,
        "output_refs": {
            key: project.get(key, "")
            for key in ("risk_ribbon_ref", "risk_ribbon_metadata_ref")
            if project.get(key)
        },
        "counts": counts,
        "warnings": warnings,
        "blockers": [],
        "stale_risk": "medium",
        "score_profile": project.get(
            "risk_score_source_profile",
            "scout_risk_engine_overpass_route_profile",
        ),
    }
    return _with_lifecycle(record)


def _risk_heatmap_layer_record(
    common: dict[str, Any],
    *,
    project_root: Path,
    project: dict[str, Any],
) -> dict[str, Any]:
    metadata_ref = project.get("calibrated_risk_heatmap_metadata_ref", "")
    heatmap_ref = project.get("calibrated_risk_heatmap_ref", "")
    diagnostic_ref = project.get("risk_attribution_diagnostic_ref", "")
    warning_ref = project.get("excluded_extreme_warning_cp_proposals_ref", "")
    warnings: list[str] = []
    source_refs: list[dict[str, Any]] = []
    counts: dict[str, Any] = {}
    status = "missing_source"

    metadata_path = project_root / metadata_ref if metadata_ref else None
    if metadata_path is not None and metadata_path.exists():
        metadata = _load_json(metadata_path)
        source_refs.append(
            _source_ref(
                metadata_ref,
                metadata_path,
                "calibrated_risk_heatmap_metadata_ref",
            )
        )
        counts.update(_risk_heatmap_counts(metadata))
        status = "ready_from_project_ref"
    else:
        warnings.append(
            "Calibrated risk heatmap metadata is missing; run layer preparation with risk-heatmap after route risk and attribution diagnostic generation."
        )

    for ref_key, ref in (
        ("calibrated_risk_heatmap_ref", heatmap_ref),
        ("risk_attribution_diagnostic_ref", diagnostic_ref),
        ("excluded_extreme_warning_cp_proposals_ref", warning_ref),
    ):
        if not ref:
            continue
        path = project_root / ref
        if path.exists():
            source_refs.append(_source_ref(ref, path, ref_key))
        else:
            warnings.append(f"{ref_key} points to a missing file: {ref}")

    record = {
        **common,
        "status": status,
        "source_refs": source_refs,
        "output_refs": {
            key: project.get(key, "")
            for key in CALIBRATED_RISK_OUTPUT_REFS
            if project.get(key)
        },
        "counts": counts,
        "warnings": warnings,
        "blockers": [],
        "stale_risk": "medium",
        "score_profile": "scout_risk_engine_route_specific_calibration",
    }
    return _with_lifecycle(record)


def _risk_delta_layer_record(
    common: dict[str, Any],
    *,
    project_root: Path,
    project: dict[str, Any],
) -> dict[str, Any]:
    baseline_metadata_ref = project.get("risk_ribbon_metadata_ref", "")
    calibrated_metadata_ref = project.get("calibrated_risk_heatmap_metadata_ref", "")
    baseline_ref = project.get("risk_ribbon_ref", "")
    calibrated_ref = project.get("calibrated_risk_heatmap_ref", "")
    warnings: list[str] = []
    source_refs: list[dict[str, Any]] = []
    counts: dict[str, Any] = {}
    status = "missing_source"

    baseline_metadata = _load_optional_project_json(
        project_root,
        baseline_metadata_ref,
        "risk_ribbon_metadata_ref",
        source_refs,
        warnings,
    )
    calibrated_metadata = _load_optional_project_json(
        project_root,
        calibrated_metadata_ref,
        "calibrated_risk_heatmap_metadata_ref",
        source_refs,
        warnings,
    )
    for ref_key, ref in (
        ("risk_ribbon_ref", baseline_ref),
        ("calibrated_risk_heatmap_ref", calibrated_ref),
    ):
        if not ref:
            continue
        path = project_root / ref
        if path.exists():
            source_refs.append(_source_ref(ref, path, ref_key))
        else:
            warnings.append(f"{ref_key} points to a missing file: {ref}")

    if baseline_metadata and calibrated_metadata and baseline_ref and calibrated_ref:
        baseline_count = int(baseline_metadata.get("segment_count", 0) or 0)
        calibrated_count = int(calibrated_metadata.get("segment_count", 0) or 0)
        counts.update(
            {
                "baseline_segment_count": baseline_count,
                "calibrated_segment_count": calibrated_count,
                "segment_count": min(baseline_count, calibrated_count),
                "score_surface_type": "baseline_vs_calibrated_delta",
            }
        )
        status = "ready_from_project_ref"
    else:
        warnings.append(
            "Risk delta requires both risk-ribbon and calibrated risk heatmap artifacts."
        )

    record = {
        **common,
        "status": status,
        "source_refs": source_refs,
        "output_refs": {
            key: project.get(key, "")
            for key in (
                "risk_ribbon_ref",
                "risk_ribbon_metadata_ref",
                "calibrated_risk_heatmap_ref",
                "calibrated_risk_heatmap_metadata_ref",
            )
            if project.get(key)
        },
        "counts": counts,
        "warnings": warnings,
        "blockers": [],
        "stale_risk": "medium",
        "score_profile": "scout_risk_engine_delta_comparison",
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
    if (
        record["status"] == "missing_source"
        and request.network_mode == "no-network"
        and not project.get("overpass_fetched_at")
    ):
        record["status"] = "planned_no_network"
        record["warnings"] = []
        record["counts"] = {
            "feature_count": 0,
            "candidate_count": 0,
            "network_calls_made": 0,
        }
        record["source_refs"] = [
            {
                "ref": planned_request["query_body_ref"],
                "source_kind": "overpass_query_plan",
                "external_network_required": False,
                "network_calls_made": False,
            }
        ]
        record["output_refs"]["normalized_geojson_ref"] = (
            OUTPUT_REFS["overpass_vector_evidence_ref"]
        )
        record["policy_notes"] = [
            (
                "No-network map preparation writes an explicit empty planned "
                "Overpass evidence artifact instead of live fetching or "
                "inventing source-backed OSM features."
            )
        ]
        record = _with_lifecycle(record)

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
    elif status == "planned_no_network":
        fetch_status = "planned_no_network"
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


def _refresh_lifecycle(record: dict[str, Any]) -> dict[str, Any]:
    if "lifecycle" not in record:
        return _with_lifecycle(record)
    source_count = len(record.get("source_refs", []))
    record["lifecycle"].setdefault("import", {})
    record["lifecycle"]["import"]["source_ref_count"] = source_count
    record["lifecycle"]["import"]["status"] = (
        "completed" if source_count else "skipped"
    )
    record["lifecycle"].setdefault("summarize", {})
    record["lifecycle"]["summarize"]["counts"] = record.get("counts", {})
    record["lifecycle"].setdefault("validate", {})
    record["lifecycle"]["validate"]["warning_count"] = len(record.get("warnings", []))
    record["lifecycle"]["validate"]["blocker_count"] = len(record.get("blockers", []))
    record["lifecycle"]["validate"]["status"] = (
        "passed" if not record.get("blockers") else "blocked"
    )
    return record


def _with_gpx_filter_provenance(
    record: dict[str, Any],
    *,
    gpx_filter: dict[str, Any],
) -> dict[str, Any]:
    record["gpx_speed_filter"] = gpx_filter
    if gpx_filter.get("applied") and gpx_filter.get("source_ref"):
        record.setdefault("source_refs", []).append(gpx_filter["source_ref"])
        record.setdefault("counts", {})["gpx_filter_removed_track_point_count"] = (
            gpx_filter.get("removed_track_point_count", 0)
        )
        return _refresh_lifecycle(record)
    record.setdefault("warnings", []).append(
        "gpx_speed_filter_report_ref is missing; this layer cannot prove it was prepared from filtered GPX."
    )
    return _refresh_lifecycle(record)


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


def _map_preparation_summary_from_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    outputs = manifest["outputs"]
    source_artifacts = _map_preparation_source_artifacts(manifest)
    return {
        "artifact_kind": "pretrip_route_corridor_map_preparation_summary",
        "schema_version": "route_corridor_map_preparation.v1",
        "source_id": manifest["job_id"] + ".map_preparation",
        "source_path": outputs["map_preparation_summary_ref"],
        "evidence_type": "pretrip_route_corridor_map_preparation_summary",
        "project_id": manifest["project_id"],
        "status": manifest["validation"]["status"],
        "profile": manifest["profile"],
        "network_mode": manifest["network_mode"],
        "prepared_at": manifest["finished_at"],
        "route_scope_ref": manifest["inputs"]["route_evidence_bundle"].get(
            "source_ref"
        ),
        "route_corridor": manifest["route_corridor"],
        "bbox_wgs84": manifest["bbox_wgs84"],
        "counts": manifest["counts"],
        "source_artifacts": source_artifacts,
        "output_refs": {
            key: outputs[key]
            for key in (
                "web_case_query_plan_ref",
                "raster_label_plan_ref",
                "overpass_vector_evidence_ref",
                "terrain_route_samples_ref",
                "web_case_evidence_ref",
                "raster_label_evidence_ref",
                "gis_semantic_input_bundle_ref",
                "gis_perception_ai_judgements_ref",
                "gis_checkpoint_candidates_ref",
                "ln_proposals_ref",
                "poi_candidates_ref",
                "terrain_risk_candidates_ref",
                "detour_route_candidates_ref",
                "layer_map_projection_ref",
                "layer_debug_projection_events_ref",
            )
        },
        "gpx_speed_filter": manifest["inputs"]["gpx_speed_filter"],
        "network_policy": manifest["network_policy"],
        "boundary": {
            **manifest["boundary"],
            "candidate_only": True,
            "review_gated": True,
            "raw_dem_embedded_in_json": False,
            "raw_tile_embedded_in_json": False,
            "large_scraped_text_embedded": False,
        },
        "notes": [
            "Route-Corridor Map Preparation starts from the importer route evidence bundle.",
            "Missing adapters write explicit empty evidence artifacts instead of silent or fake map output.",
        ],
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
        "layers": [_map_projection_layer(layer) for layer in manifest["layers"]],
        "boundary": manifest["boundary"],
    }


def _map_projection_layer(layer: dict[str, Any]) -> dict[str, Any]:
    projected = {
        "layer_id": layer["layer_id"],
        "status": layer["status"],
        "source_refs": layer["source_refs"],
        "output_refs": layer["output_refs"],
        "counts": layer["counts"],
    }
    for key in (
        "bbox_wgs84",
        "raster_bbox_wgs84",
        "raster_coverage_policy",
        "local_raster_manifest_ref",
        "raster_tile_manifest_ref",
        "raster_tile_zoom_range",
        "raster_tile_cache_root",
        "raster_tile_count",
    ):
        if key in layer:
            projected[key] = layer[key]
    if layer.get("layer_id") == "imagery":
        template = (layer.get("output_refs") or {}).get("local_raster_tile_url_template")
        if template:
            projected["local_raster_tile_url_template"] = template
    if layer.get("layer_id") == "osm":
        template = (layer.get("output_refs") or {}).get("local_proxy_tile_url_template")
        if template:
            projected["local_proxy_tile_url_template"] = template
    return projected


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
    route_evidence_bundle: dict[str, Any],
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
    if not route_evidence_bundle.get("available"):
        warnings.append(
            {
                "layer_id": "route_evidence_bundle",
                "message": route_evidence_bundle.get(
                    "warning",
                    "route evidence bundle is unavailable.",
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


def _sync_scout_risk_outputs(
    *,
    project_root: Path,
    project: dict[str, Any],
    prepared_at: str,
) -> dict[str, Any]:
    source_root = SCOUT_RISK_OUTPUT_SOURCES.get(str(project.get("project_id", "")))
    if source_root is None or not source_root.exists():
        return project

    required = (
        "route_risk.geojson",
        "route_risk.metadata.json",
        "risk_score_points.geojson",
        "risk_score_points.metadata.json",
    )
    if any(not (source_root / filename).exists() for filename in required):
        return project

    updated = dict(project)
    for ref_key, ref in SCOUT_RISK_OUTPUT_REFS.items():
        source_path = source_root / Path(ref).name
        if not source_path.exists():
            continue
        destination = project_root / ref
        if source_path.resolve() != destination.resolve():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination)
        updated[ref_key] = ref

    _stamp_synced_risk_output_provenance(project_root=project_root, project=updated)

    metadata_path = project_root / SCOUT_RISK_OUTPUT_REFS["risk_score_points_metadata_ref"]
    route_metadata_path = project_root / SCOUT_RISK_OUTPUT_REFS[
        "risk_route_profile_metadata_ref"
    ]
    ribbon_metadata_path = project_root / SCOUT_RISK_OUTPUT_REFS[
        "risk_ribbon_metadata_ref"
    ]
    if metadata_path.exists():
        metadata = _load_json(metadata_path)
        updated["risk_score_point_count"] = int(metadata.get("point_count", 0))
        updated["risk_score_source_feature_count"] = int(
            metadata.get("source_feature_count", 0)
        )
    if route_metadata_path.exists():
        route_metadata = _load_json(route_metadata_path)
        route_samples = route_metadata.get("route_risk_sample_count")
        if isinstance(route_samples, int):
            updated["risk_route_sample_count"] = route_samples
    if ribbon_metadata_path.exists():
        ribbon_metadata = _load_json(ribbon_metadata_path)
        ribbon_segments = ribbon_metadata.get("segment_count")
        if isinstance(ribbon_segments, int):
            updated["risk_ribbon_segment_count"] = ribbon_segments
    updated["risk_score_source_profile"] = "scout_risk_engine_overpass_route_profile"
    updated["risk_score_updated_at"] = prepared_at
    return updated


def _sync_calibrated_risk_outputs(
    *,
    project_root: Path,
    project: dict[str, Any],
) -> dict[str, Any]:
    route_ref = project.get("risk_route_profile_ref")
    if not isinstance(route_ref, str) or not route_ref:
        return project
    route_path = project_root / route_ref
    if not route_path.exists():
        return project

    gis_ref = project.get("gis_perception_candidates_ref")
    route_note_ref = project.get("route_note_ln_proposals_ref")
    gis_path = project_root / gis_ref if isinstance(gis_ref, str) and gis_ref else None
    route_note_path = (
        project_root / route_note_ref
        if isinstance(route_note_ref, str) and route_note_ref
        else None
    )
    diagnostic_path = project_root / CALIBRATED_RISK_OUTPUT_REFS[
        "risk_attribution_diagnostic_ref"
    ]
    warning_path = project_root / CALIBRATED_RISK_OUTPUT_REFS[
        "excluded_extreme_warning_cp_proposals_ref"
    ]
    heatmap_path = project_root / CALIBRATED_RISK_OUTPUT_REFS[
        "calibrated_risk_heatmap_ref"
    ]
    heatmap_metadata_path = project_root / CALIBRATED_RISK_OUTPUT_REFS[
        "calibrated_risk_heatmap_metadata_ref"
    ]

    try:
        from pretrip_risk_attribution_diagnostic import (
            build_risk_attribution_diagnostic,
            write_diagnostic,
            write_warning_cp_proposals,
        )
        from pretrip_risk_heatmap import (
            build_calibrated_risk_heatmap,
            write_heatmap_geojson,
            write_heatmap_metadata,
        )

        diagnostic = build_risk_attribution_diagnostic(
            route_risk_path=route_path,
            gis_perception_path=gis_path if gis_path and gis_path.exists() else None,
            route_note_ln_proposals_path=(
                route_note_path if route_note_path and route_note_path.exists() else None
            ),
        )
        write_diagnostic(diagnostic, diagnostic_path)
        write_warning_cp_proposals(diagnostic, warning_path)
        heatmap = build_calibrated_risk_heatmap(
            route_risk_path=route_path,
            risk_attribution_diagnostic_path=diagnostic_path,
            warning_cp_proposals_path=warning_path,
        )
        write_heatmap_geojson(heatmap, heatmap_path)
        write_heatmap_metadata(heatmap, heatmap_metadata_path)
    except Exception as exc:  # pragma: no cover - covered by layer warnings in callers.
        updated = dict(project)
        updated["calibrated_risk_heatmap_sync_error"] = str(exc)
        return updated

    _stamp_calibrated_risk_provenance(project_root=project_root, project={
        **project,
        **CALIBRATED_RISK_OUTPUT_REFS,
    })

    metadata = heatmap["metadata"]
    updated = {
        **project,
        **CALIBRATED_RISK_OUTPUT_REFS,
        "calibrated_risk_heatmap_segment_count": metadata.get("segment_count", 0),
        "calibrated_risk_heatmap_warning_cp_overlay_count": metadata.get(
            "warning_cp_overlay_count",
            0,
        ),
        "risk_attribution_diagnostic_checkpoint_count": diagnostic.get(
            "counts",
            {},
        ).get("semantic_checkpoint_count", 0),
    }
    return updated


def _stamp_synced_risk_output_provenance(
    *,
    project_root: Path,
    project: dict[str, Any],
) -> None:
    _stamp_risk_geojson_provenance(
        project_root=project_root,
        project=project,
        ref_key="risk_route_profile_ref",
        metadata_ref_key="risk_route_profile_metadata_ref",
        artifact_kind="scout_risk_overpass_route_profile",
        evidence_type="pretrip_route_risk_sample",
        source_kind="scout_risk_engine_route_profile",
        source_ref_keys=(
            "risk_route_profile_metadata_ref",
            "risk_route_profile_csv_ref",
        ),
        default_confidence="medium",
        default_stale_risk="medium",
    )
    _stamp_risk_geojson_provenance(
        project_root=project_root,
        project=project,
        ref_key="risk_score_points_ref",
        metadata_ref_key="risk_score_points_metadata_ref",
        artifact_kind="scout_risk_score_point_map",
        evidence_type="pretrip_risk_score_point",
        source_kind="scout_risk_engine_route_sample",
        source_ref_keys=(
            "risk_route_profile_ref",
            "risk_route_profile_metadata_ref",
            "risk_score_points_metadata_ref",
        ),
        default_confidence="medium",
        default_stale_risk="medium",
    )
    _stamp_risk_geojson_provenance(
        project_root=project_root,
        project=project,
        ref_key="risk_ribbon_ref",
        metadata_ref_key="risk_ribbon_metadata_ref",
        artifact_kind="scout_risk_route_ribbon",
        evidence_type="pretrip_risk_ribbon_segment",
        source_kind="scout_risk_engine_route_ribbon",
        source_ref_keys=(
            "risk_route_profile_ref",
            "risk_route_profile_metadata_ref",
            "risk_ribbon_metadata_ref",
        ),
        default_confidence="medium",
        default_stale_risk="medium",
    )


def _stamp_calibrated_risk_provenance(
    *,
    project_root: Path,
    project: dict[str, Any],
) -> None:
    _stamp_risk_geojson_provenance(
        project_root=project_root,
        project=project,
        ref_key="calibrated_risk_heatmap_ref",
        metadata_ref_key="calibrated_risk_heatmap_metadata_ref",
        artifact_kind="pretrip_calibrated_risk_heatmap",
        evidence_type="pretrip_calibrated_risk_heatmap_segment",
        source_kind="scout_risk_engine_calibrated_heatmap",
        source_ref_keys=(
            "risk_route_profile_ref",
            "risk_attribution_diagnostic_ref",
            "excluded_extreme_warning_cp_proposals_ref",
            "calibrated_risk_heatmap_metadata_ref",
        ),
        default_confidence="medium",
        default_stale_risk="medium",
    )


def _stamp_overpass_evidence_provenance(
    *,
    project_root: Path,
    project: dict[str, Any],
) -> None:
    ref = project.get("overpass_evidence_ref")
    if not isinstance(ref, str) or not ref:
        return
    path = project_root / ref
    if not path.exists():
        return
    payload = _load_json(path)
    if not isinstance(payload, dict):
        return
    raw_ref = (
        payload.get("request", {}).get("normalized_artifact_path")
        or payload.get("request", {}).get("raw_payload_uri")
        or project.get("overpass_raw_payload_ref")
        or ref
    )
    source_refs = _risk_source_refs(
        project_root,
        {
            **project,
            "overpass_evidence_ref": ref,
            "overpass_raw_payload_ref": raw_ref,
        },
        ("overpass_evidence_ref", "overpass_raw_payload_ref"),
    )
    for candidate in payload.get("candidates", []):
        if not isinstance(candidate, dict):
            continue
        candidate_id = str(candidate.get("candidate_id") or "")
        confidence = candidate.get("confidence", "medium")
        stale_risk = candidate.get("stale_risk", "medium")
        source_attribution = [
            {
                "source_kind": "overpass_osm_vector",
                "source_ref": raw_ref,
                "source_candidate_id": candidate_id,
                "source_artifact_id": "pretrip_overpass_vector_evidence",
                "source_label": candidate.get("label", candidate_id),
                "evidence_type": "pretrip_overpass_vector_candidate",
                "confidence": confidence,
                "stale_risk": stale_risk,
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        ]
        provenance_hash = hashlib.sha256(
            json.dumps(
                {
                    "candidate_id": candidate_id,
                    "osm_type": candidate.get("osm_type"),
                    "osm_id": candidate.get("osm_id"),
                    "source_refs": [
                        {"ref": item.get("ref"), "sha256": item.get("sha256")}
                        for item in source_refs
                    ],
                    "conversion_rule_version": candidate.get(
                        "conversion_rule_version",
                        "overpass-vector-evidence.v1",
                    ),
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        candidate["source_refs"] = candidate.get("source_refs") or [raw_ref]
        candidate["source_attribution"] = source_attribution
        candidate["extractor_version"] = candidate.get(
            "conversion_rule_version",
            "overpass-vector-evidence.v1",
        )
        candidate["pydantic_ai_prompt_version"] = (
            "not_applicable_deterministic_overpass_ingest"
        )
        candidate["model_output_sha256"] = provenance_hash
        candidate["model_output_summary"] = (
            "Deterministic Overpass/OSM vector normalization produced a "
            "pretrip planning candidate; not runtime safety truth."
        )
        candidate["review_state"] = candidate.get("review_state", "needs_review")
        candidate["candidate_only"] = True
        candidate["runtime_safety_truth"] = False
        feature_properties = candidate.get("geojson_feature", {}).get("properties")
        if isinstance(feature_properties, dict):
            feature_properties.update(
                {
                    "source_refs": candidate["source_refs"],
                    "source_attribution": source_attribution,
                    "extractor_version": candidate["extractor_version"],
                    "pydantic_ai_prompt_version": candidate[
                        "pydantic_ai_prompt_version"
                    ],
                    "model_output_sha256": provenance_hash,
                    "model_output_summary": candidate["model_output_summary"],
                    "review_state": candidate["review_state"],
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                }
            )
    _write_json(path, payload)


def _stamp_risk_geojson_provenance(
    *,
    project_root: Path,
    project: dict[str, Any],
    ref_key: str,
    metadata_ref_key: str,
    artifact_kind: str,
    evidence_type: str,
    source_kind: str,
    source_ref_keys: tuple[str, ...],
    default_confidence: str,
    default_stale_risk: str,
) -> None:
    ref = project.get(ref_key)
    if not isinstance(ref, str) or not ref:
        return
    path = project_root / ref
    if not path.exists():
        return
    payload = _load_json(path)
    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        return
    source_refs = _risk_source_refs(project_root, project, source_ref_keys)
    metadata_ref = project.get(metadata_ref_key)
    metadata_path = project_root / metadata_ref if isinstance(metadata_ref, str) else None
    metadata = payload.setdefault("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
        payload["metadata"] = metadata
    metadata.setdefault("artifact_kind", artifact_kind)
    metadata.setdefault("status", "candidate_only")
    metadata["source_refs"] = source_refs
    metadata["extractor_version"] = RISK_PROVENANCE_STAMP_VERSION
    metadata["pydantic_ai_prompt_version"] = (
        "not_applicable_deterministic_pretrip_risk"
    )
    metadata["model_output_summary"] = (
        f"{evidence_type} generated by deterministic Scout Risk Engine heuristics; "
        "pretrip candidate-only evidence, not runtime safety truth."
    )
    metadata["confidence"] = metadata.get("confidence", default_confidence)
    metadata["stale_risk"] = metadata.get("stale_risk", default_stale_risk)
    metadata["review_state"] = metadata.get("review_state", "needs_review")
    metadata["candidate_only"] = True
    metadata["runtime_safety_truth"] = False
    boundary = metadata.setdefault("boundary", {})
    if isinstance(boundary, dict):
        boundary["candidate_only"] = True
        boundary["runtime_safety_truth"] = False

    metadata_hash = _sha256_file(metadata_path) if metadata_path and metadata_path.exists() else ""
    for index, feature in enumerate(payload.get("features", [])):
        if not isinstance(feature, dict):
            continue
        properties = feature.setdefault("properties", {})
        if not isinstance(properties, dict):
            properties = {}
            feature["properties"] = properties
        candidate_id = _risk_feature_candidate_id(properties, index, evidence_type)
        properties.setdefault("candidate_id", candidate_id)
        properties.setdefault("evidence_type", evidence_type)
        properties["source_refs"] = source_refs
        properties["source_attribution"] = [
            {
                "source_kind": source_kind,
                "source_profile": "scout_risk_engine",
                "source_candidate_id": candidate_id,
                "source_artifact_id": artifact_kind,
                "source_label": _risk_feature_label(properties, evidence_type),
                "evidence_type": evidence_type,
                "confidence": properties.get("confidence", default_confidence),
                "stale_risk": properties.get("stale_risk", default_stale_risk),
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        ]
        properties["extractor_version"] = RISK_PROVENANCE_STAMP_VERSION
        properties["pydantic_ai_prompt_version"] = (
            "not_applicable_deterministic_pretrip_risk"
        )
        properties["model_output_summary"] = metadata["model_output_summary"]
        properties["model_output_sha256"] = _risk_feature_provenance_hash(
            properties,
            source_refs=source_refs,
            metadata_hash=metadata_hash,
        )
        properties["confidence"] = properties.get("confidence", default_confidence)
        properties["stale_risk"] = properties.get("stale_risk", default_stale_risk)
        properties["review_state"] = properties.get("review_state", "needs_review")
        properties["candidate_only"] = True
        properties["runtime_safety_truth"] = False

    _write_json(path, payload)


def _risk_source_refs(
    project_root: Path,
    project: dict[str, Any],
    source_ref_keys: tuple[str, ...],
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref_key in source_ref_keys:
        ref = project.get(ref_key)
        if not isinstance(ref, str) or not ref or ref in seen:
            continue
        seen.add(ref)
        path = project_root / ref
        if path.exists():
            refs.append(_source_ref(ref, path, ref_key))
        else:
            refs.append({"ref": ref, "project_ref_key": ref_key, "exists": False})
    return refs


def _risk_feature_candidate_id(
    properties: dict[str, Any],
    index: int,
    evidence_type: str,
) -> str:
    for key in ("candidate_id", "segment_id", "sample_id"):
        value = properties.get(key)
        if value:
            return str(value)
    return f"{evidence_type}.{index:04d}"


def _risk_feature_label(properties: dict[str, Any], evidence_type: str) -> str:
    score = properties.get("rs", properties.get("pretrip_risk"))
    if score is not None:
        try:
            return f"{evidence_type} {float(score):.1f}"
        except (TypeError, ValueError):
            pass
    return evidence_type


def _risk_feature_provenance_hash(
    properties: dict[str, Any],
    *,
    source_refs: list[dict[str, Any]],
    metadata_hash: str,
) -> str:
    material = {
        "candidate_id": properties.get("candidate_id"),
        "segment_id": properties.get("segment_id"),
        "sample_id": properties.get("sample_id"),
        "rs": properties.get("rs"),
        "score_field": properties.get("score_field"),
        "source_refs": [
            {
                "ref": ref.get("ref"),
                "sha256": ref.get("sha256"),
                "exists": ref.get("exists"),
            }
            for ref in source_refs
        ],
        "metadata_sha256": metadata_hash,
    }
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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


def _gpx_filter_context(project_root: Path, project: dict[str, Any]) -> dict[str, Any]:
    ref = project.get("gpx_speed_filter_report_ref")
    if not isinstance(ref, str) or not ref:
        return {
            "applied": False,
            "source_ref": None,
            "warning": "project.json has no gpx_speed_filter_report_ref",
        }
    path = project_root / ref
    if not path.exists():
        return {
            "applied": False,
            "source_ref": {
                "ref": ref,
                "project_ref_key": "gpx_speed_filter_report_ref",
                "exists": False,
            },
            "warning": f"gpx_speed_filter_report_ref points to a missing file: {ref}",
        }
    payload = _load_json(path)
    primary = payload.get("primary", {})
    source_ref = _source_ref(ref, path, "gpx_speed_filter_report_ref")
    return {
        "applied": True,
        "source_ref": source_ref,
        "max_reasonable_speed_kmh": payload.get("max_reasonable_speed_kmh"),
        "max_previous_speed_ratio": payload.get("max_previous_speed_ratio"),
        "route_note_protection_radius_m": payload.get(
            "route_note_protection_radius_m"
        ),
        "original_track_point_count": payload.get("original_track_point_count"),
        "filtered_track_point_count": payload.get("filtered_track_point_count"),
        "removed_track_point_count": payload.get("removed_track_point_count"),
        "exempted_track_point_count": payload.get("exempted_track_point_count"),
        "primary_filtered_track_point_count": primary.get("filtered_track_point_count"),
        "primary_removed_track_point_count": primary.get("removed_track_point_count"),
        "filtered_primary_gpx_path": primary.get("output_path"),
        "candidate_only": payload.get("boundary", {}).get(
            "pretrip_candidate_evidence_only",
            True,
        ),
        "runtime_safety_truth": payload.get("boundary", {}).get(
            "runtime_safety_truth",
            False,
        ),
    }


def _route_evidence_bundle_context(
    *,
    project_root: Path,
    project: dict[str, Any],
    request: LayerPreparationRequest,
) -> dict[str, Any]:
    ref = request.route_evidence_bundle or project.get("route_evidence_bundle_ref")
    if not ref:
        return {
            "available": False,
            "source_ref": None,
            "warning": (
                "route_evidence_bundle_ref is missing; map preparation is "
                "using legacy route_summary bbox fallback."
            ),
        }
    path = Path(ref)
    if not path.is_absolute():
        path = project_root / path
    source_ref_text = _relative_project_ref(project_root, path)
    if not path.exists():
        return {
            "available": False,
            "source_ref": {
                "ref": str(ref),
                "project_ref_key": "route_evidence_bundle_ref",
                "exists": False,
            },
            "warning": f"route_evidence_bundle_ref points to a missing file: {ref}",
        }
    payload = _load_json(path)
    scope = payload.get("route_scope_for_map_preparation", {})
    return {
        "available": True,
        "source_ref": source_ref_text,
        "source_ref_record": _source_ref(
            source_ref_text,
            path,
            "route_evidence_bundle_ref",
        ),
        "artifact_kind": payload.get("artifact_kind"),
        "schema_version": payload.get("schema_version"),
        "route_scope_for_map_preparation": scope,
        "gpx_filter_refs": payload.get("gpx_filter_refs", {}),
        "note_candidate_refs": payload.get("note_candidate_refs", []),
        "boundary": payload.get("boundary", {}),
        "candidate_only": payload.get("boundary", {}).get("candidate_only", True),
        "runtime_safety_truth": payload.get("boundary", {}).get(
            "runtime_safety_truth",
            False,
        ),
    }


def _bbox_from_route_evidence_bundle(
    route_evidence_bundle: dict[str, Any],
) -> dict[str, float] | None:
    if not route_evidence_bundle.get("available"):
        return None
    value = route_evidence_bundle.get("route_scope_for_map_preparation", {}).get(
        "bbox_wgs84"
    )
    if isinstance(value, list) and len(value) == 4:
        west, south, east, north = value
        return {
            "south": float(south),
            "west": float(west),
            "north": float(north),
            "east": float(east),
        }
    if isinstance(value, dict):
        return normalize_bbox_wgs84(value)
    return None


def _relative_project_ref(project_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


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


def _build_gis_semantic_input_bundle(
    *,
    project_root: Path,
    project: dict[str, Any],
    manifest: dict[str, Any],
    route_evidence_bundle: dict[str, Any],
    gpx_filter: dict[str, Any],
    source_refs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    evidence_items: list[dict[str, Any]] = []
    source_kind_counts: Counter[str] = Counter()

    route_note_ref = project.get("normalized_route_note_candidates_ref") or project.get(
        "route_note_candidates_ref"
    )
    if isinstance(route_note_ref, str) and route_note_ref:
        route_note_path = project_root / route_note_ref
        if route_note_path.exists():
            route_notes = _load_json(route_note_path)
            for index, candidate in enumerate(route_notes.get("candidates", [])):
                if not isinstance(candidate, dict):
                    continue
                candidate_id = str(
                    candidate.get("candidate_id")
                    or f"gpx_route_note.{index + 1:06d}"
                )
                item = {
                    "evidence_id": candidate_id,
                    "source_kind": "gpx_route_note",
                    "candidate_type": candidate.get("note_category", "route_note"),
                    "text": _compact_text(
                        candidate.get("normalized_note")
                        or candidate.get("name")
                        or candidate.get("desc")
                        or ""
                    ),
                    "semantic_hints": _semantic_hints_from_route_note(candidate),
                    "distance_to_golden_route_m": candidate.get(
                        "distance_to_golden_route_m"
                    ),
                    "nearest_route_distance_m": candidate.get(
                        "nearest_route_distance_m"
                    ),
                    "coordinates": _candidate_coordinates(candidate),
                    "source_refs": [f"{route_note_ref}#{candidate_id}"],
                    "source_attribution": candidate.get("source_attribution", []),
                    "confidence": candidate.get("confidence", "medium"),
                    "stale_risk": candidate.get("stale_risk", "medium"),
                    "review_state": candidate.get("review_state", "needs_review"),
                    "requires_human_review": candidate.get(
                        "requires_human_review",
                        True,
                    ),
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                }
                evidence_items.append(item)
                source_kind_counts[item["source_kind"]] += 1

    overpass_ref = project.get("overpass_evidence_ref")
    if isinstance(overpass_ref, str) and overpass_ref:
        overpass_path = project_root / overpass_ref
        if overpass_path.exists():
            overpass_evidence = _load_json(overpass_path)
            normalized_ref = overpass_evidence.get(
                "normalized_geojson_ref",
                project.get("overpass_map_context_ref", ""),
            )
            for index, candidate in enumerate(overpass_evidence.get("candidates", [])):
                if not isinstance(candidate, dict):
                    continue
                candidate_id = str(
                    candidate.get("candidate_id")
                    or candidate.get("source_id")
                    or f"overpass.candidate.{index + 1:06d}"
                )
                tags = candidate.get("tags", {})
                item = {
                    "evidence_id": candidate_id,
                    "source_kind": "overpass_candidate",
                    "candidate_type": candidate.get("candidate_type")
                    or candidate.get("checkpoint_type")
                    or candidate.get("feature_type")
                    or "overpass_candidate",
                    "tags": tags if isinstance(tags, dict) else {},
                    "distance_to_golden_route_m": candidate.get(
                        "distance_to_golden_route_m"
                    ),
                    "nearest_route_distance_m": candidate.get(
                        "nearest_route_distance_m"
                    ),
                    "source_refs": (
                        [f"{normalized_ref}#{candidate_id}"]
                        if normalized_ref
                        else [f"{overpass_ref}#{candidate_id}"]
                    ),
                    "confidence": candidate.get("confidence", "medium"),
                    "stale_risk": candidate.get("stale_risk", "medium"),
                    "review_state": candidate.get("review_state", "needs_review"),
                    "requires_human_review": candidate.get(
                        "requires_human_review",
                        True,
                    ),
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                }
                evidence_items.append(item)
                source_kind_counts[item["source_kind"]] += 1

    rest_area_ref = project.get("rest_area_candidates_ref")
    if isinstance(rest_area_ref, str) and rest_area_ref:
        rest_area_path = project_root / rest_area_ref
        if rest_area_path.exists():
            rest_area_report = _load_json(rest_area_path)
            for index, candidate in enumerate(rest_area_report.get("candidates", [])):
                if not isinstance(candidate, dict):
                    continue
                candidate_id = str(
                    candidate.get("candidate_id")
                    or f"rest_area_candidate.{index + 1:06d}"
                )
                item = {
                    "evidence_id": candidate_id,
                    "source_kind": "rest_area_candidate",
                    "candidate_type": candidate.get(
                        "checkpoint_type",
                        "rest_area",
                    ),
                    "text": _compact_text(candidate.get("label") or "Rest/camp area"),
                    "semantic_hints": [
                        "water_or_camp_hint",
                        "rest_area_candidate",
                    ],
                    "distance_to_golden_route_m": candidate.get(
                        "distance_to_filtered_route_m"
                    ),
                    "nearest_route_distance_m": candidate.get("route_point_index"),
                    "coordinates": _candidate_coordinates(candidate),
                    "source_refs": [f"{rest_area_ref}#{candidate_id}"],
                    "source_attribution": candidate.get("source_attribution", []),
                    "confidence": candidate.get("confidence", "medium"),
                    "stale_risk": candidate.get("stale_risk", "medium"),
                    "review_state": candidate.get("review_state", "needs_review"),
                    "requires_human_review": True,
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                    "rest_area_metrics": {
                        "duration_seconds": candidate.get("duration_seconds"),
                        "mean_speed_m_per_min": candidate.get(
                            "mean_speed_m_per_min"
                        ),
                        "source_point_count": candidate.get("source_point_count"),
                    },
                }
                evidence_items.append(item)
                source_kind_counts[item["source_kind"]] += 1

    source_ref_records = [
        ref
        for key, ref in source_refs.items()
        if key
        in {
            "route_evidence_bundle_ref",
            "normalized_route_note_candidates_ref",
            "route_note_candidates_ref",
            "overpass_evidence_ref",
            "overpass_map_context_ref",
            "gpx_speed_filter_report_ref",
            "rest_area_candidates_ref",
            "resume_segment_report_ref",
        }
    ]
    route_scope_ref = route_evidence_bundle.get("source_ref")
    if isinstance(route_scope_ref, dict):
        route_scope_ref = route_scope_ref.get("ref")
    route_scope_ref = route_scope_ref or project.get("route_evidence_bundle_ref")
    return {
        "artifact_kind": "pretrip_gis_semantic_input_bundle",
        "schema_version": "route_corridor_map_preparation.v1",
        "project_id": manifest["project_id"],
        "source_id": manifest["job_id"] + ".semantic_input",
        "source_path": manifest["outputs"]["gis_semantic_input_bundle_ref"],
        "route_scope_ref": route_scope_ref,
        "route_corridor": manifest["route_corridor"],
        "gpx_speed_filter": {
            "applied": bool(gpx_filter.get("applied")),
            "source_ref": gpx_filter.get("source_ref"),
            "removed_track_point_count": gpx_filter.get("removed_track_point_count"),
            "runtime_safety_truth": gpx_filter.get("runtime_safety_truth", False),
        },
        "evidence_items": evidence_items,
        "counts": {
            "evidence_item_count": len(evidence_items),
            "source_kind_counts": dict(sorted(source_kind_counts.items())),
            "route_note_evidence_count": source_kind_counts.get("gpx_route_note", 0),
            "overpass_evidence_count": source_kind_counts.get("overpass_candidate", 0),
        },
        "source_refs": source_ref_records,
        "ai_policy": manifest["ai_policy"],
        "boundary": {
            "candidate_only": True,
            "observed_fact": False,
            "runtime_safety_truth": False,
            "phase1_runtime_mutation_allowed": False,
            "phase2_brain_writeback_allowed": False,
            "raw_gpx_embedded_in_json": False,
            "raw_raster_embedded_in_json": False,
            "oversized_web_text_embedded": False,
        },
    }


def _build_gis_perception_ai_judgements(
    *,
    manifest: dict[str, Any],
    semantic_input_bundle: dict[str, Any],
) -> dict[str, Any]:
    input_bundle_ref = manifest["outputs"]["gis_semantic_input_bundle_ref"]
    input_bundle_sha256 = _sha256_json(semantic_input_bundle)
    prompt_version = "gis_semantic_classifier.v1"
    prompt_hash = hashlib.sha256(
        json.dumps(
            {
                "prompt_version": prompt_version,
                "input_bundle_sha256": input_bundle_sha256,
                "ai_policy": manifest.get("ai_policy", {}),
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    judgements: list[dict[str, Any]] = []
    source_refs = _unique_strings(
        ref.get("ref")
        for ref in semantic_input_bundle.get("source_refs", [])
        if isinstance(ref, dict)
    )
    for index, item in enumerate(semantic_input_bundle.get("evidence_items", [])):
        if not isinstance(item, dict):
            continue
        evidence_id = str(item.get("evidence_id") or f"semantic_evidence.{index:06d}")
        semantic_key = _semantic_key_for_judgement(item)
        proposed_ln_level = _ln_level_for_semantic_key(semantic_key)
        cp_needed = proposed_ln_level in {"L2_candidate", "L3_candidate"}
        candidate_kind = (
            "checkpoint_candidate"
            if cp_needed or item.get("source_kind") == "gpx_route_note"
            else "poi_candidate"
        )
        judgement = {
            "judgement_id": f"gis_judgement.{index + 1:06d}",
            "candidate_id": evidence_id,
            "source_candidate_id": evidence_id,
            "source_kind": item.get("source_kind", "semantic_evidence"),
            "source_evidence_refs": [evidence_id],
            "source_refs": item.get("source_refs", []),
            "proposed_candidate_kind": candidate_kind,
            "proposed_semantic_key": semantic_key,
            "proposed_ln_level": proposed_ln_level,
            "checkpoint_type": _checkpoint_type_for_semantic_key(semantic_key),
            "suggested_ln_scope": _ln_scope_for_semantic_key(semantic_key),
            "cp_needed": cp_needed,
            "reason": _semantic_judgement_reason(item, semantic_key),
            "reason_zh": _semantic_judgement_reason(item, semantic_key),
            "confidence": item.get("confidence", "medium"),
            "stale_risk": item.get("stale_risk", "medium"),
            "requires_human_review": True,
            "human_review_required": True,
            "candidate_only": True,
            "observed_fact": False,
            "runtime_safety_truth": False,
            "phase1_runtime_mutation_allowed": False,
        }
        judgements.append(judgement)

    counts = {
        "input_count": semantic_input_bundle.get("counts", {}).get(
            "evidence_item_count",
            len(judgements),
        ),
        "judgement_count": len(judgements),
        "candidate_only_count": len(judgements),
        "human_review_required_count": len(judgements),
        "runtime_safety_truth_count": 0,
        "observed_fact_count": 0,
        "package_mutation_count": 0,
        "mission_graph_mutation_count": 0,
        "runtime_mutation_count": 0,
        "phase1_runtime_mutation_count": 0,
        "phase2_writeback_count": 0,
        "raw_model_output_count": 0,
        "source_ref_count": len(source_refs),
    }
    return {
        "artifact_kind": "gis_perception_ai_judgements",
        "schema_version": "gis_perception_ai_judgements.v1",
        "project_id": manifest["project_id"],
        "source_id": manifest["job_id"] + ".semantic_judgements",
        "source_path": manifest["outputs"]["gis_perception_ai_judgements_ref"],
        "model_provider": "deterministic-fixture",
        "provider_kind": "fixture-or-precomputed",
        "model_name": "no-live-model.fixture-or-precomputed",
        "prompt_version": prompt_version,
        "prompt_hash": prompt_hash,
        "prompt_sha256": prompt_hash,
        "input_bundle_ref": input_bundle_ref,
        "input_bundle_sha256": input_bundle_sha256,
        "input_count": counts["input_count"],
        "judgement_count": counts["judgement_count"],
        "source_refs": source_refs,
        "counts": counts,
        "judgements": judgements,
        "live_model_call_performed": False,
        "network_calls_allowed": False,
        "raw_model_output_embedded": False,
        "ai_policy": manifest.get("ai_policy", {}),
        "boundary": {
            "candidate_only": True,
            "observed_fact": False,
            "observed_fact_allowed": False,
            "runtime_safety_truth": False,
            "runtime_safety_truth_allowed": False,
            "phase1_runtime_mutation_allowed": False,
            "phase2_brain_writeback_allowed": False,
            "package_mutation_allowed": False,
            "mission_graph_mutation_allowed": False,
            "runtime_mutation_allowed": False,
            "raw_model_output_embedded": False,
            "raw_gpx_embedded": False,
            "raw_raster_embedded": False,
        },
    }


def _build_layer_candidate_artifacts(
    *,
    project_root: Path,
    project: dict[str, Any],
    manifest: dict[str, Any],
    semantic_input_bundle: dict[str, Any],
    semantic_judgements: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    evidence_by_id = {
        str(item.get("evidence_id")): item
        for item in semantic_input_bundle.get("evidence_items", [])
        if isinstance(item, dict) and item.get("evidence_id")
    }
    checkpoint_candidates: list[dict[str, Any]] = []
    ln_proposals: list[dict[str, Any]] = []
    poi_candidates: list[dict[str, Any]] = []
    detour_candidates: list[dict[str, Any]] = []

    for judgement in semantic_judgements.get("judgements", []):
        if not isinstance(judgement, dict):
            continue
        evidence_id = str(judgement.get("source_candidate_id") or "")
        evidence = evidence_by_id.get(evidence_id, {})
        base = _candidate_base_from_judgement(judgement, evidence)
        if judgement.get("proposed_candidate_kind") == "checkpoint_candidate":
            checkpoint_candidates.append(
                {
                    **base,
                    "candidate_kind": "gis_checkpoint_candidate",
                    "checkpoint_type": judgement.get("checkpoint_type"),
                    "proposed_semantic_key": judgement.get("proposed_semantic_key"),
                    "proposed_ln_level": judgement.get("proposed_ln_level"),
                    "cp_needed": bool(judgement.get("cp_needed")),
                }
            )
        elif judgement.get("proposed_candidate_kind") == "poi_candidate":
            poi_candidates.append(
                {
                    **base,
                    "candidate_kind": "poi_candidate",
                    "poi_type": judgement.get("proposed_semantic_key"),
                }
            )
        if judgement.get("suggested_ln_scope") != "review_only":
            ln_proposals.append(
                {
                    **base,
                    "proposal_id": f"ln_candidate.{judgement.get('judgement_id')}",
                    "candidate_kind": "ln_proposal_candidate",
                    "proposed_ln_scope": judgement.get("suggested_ln_scope"),
                    "proposed_ln_level": judgement.get("proposed_ln_level"),
                    "proposed_semantic_key": judgement.get("proposed_semantic_key"),
                }
            )
        semantic_key = str(judgement.get("proposed_semantic_key") or "").lower()
        if "detour" in semantic_key:
            detour_candidates.append(
                {
                    **base,
                    "candidate_kind": "detour_route_candidate",
                    "detour_reason": judgement.get("reason"),
                    "proposed_semantic_key": judgement.get("proposed_semantic_key"),
                }
            )

    terrain_risk_candidates = _terrain_risk_candidates_from_project(
        project_root=project_root,
        project=project,
    )
    return {
        "gis_checkpoint_candidates_ref": _layer_candidate_artifact(
            manifest=manifest,
            ref_key="gis_checkpoint_candidates_ref",
            artifact_kind="pretrip_layer_gis_checkpoint_candidates",
            candidate_key="candidates",
            candidates=checkpoint_candidates,
            source_refs=[
                manifest["outputs"]["gis_perception_ai_judgements_ref"],
                manifest["outputs"]["gis_semantic_input_bundle_ref"],
            ],
        ),
        "ln_proposals_ref": _layer_candidate_artifact(
            manifest=manifest,
            ref_key="ln_proposals_ref",
            artifact_kind="pretrip_layer_ln_proposals",
            candidate_key="proposals",
            candidates=ln_proposals,
            source_refs=[
                manifest["outputs"]["gis_perception_ai_judgements_ref"],
                manifest["outputs"]["gis_semantic_input_bundle_ref"],
            ],
        ),
        "poi_candidates_ref": _layer_candidate_artifact(
            manifest=manifest,
            ref_key="poi_candidates_ref",
            artifact_kind="pretrip_layer_poi_candidates",
            candidate_key="candidates",
            candidates=poi_candidates,
            source_refs=[
                manifest["outputs"]["gis_perception_ai_judgements_ref"],
                manifest["outputs"]["gis_semantic_input_bundle_ref"],
            ],
        ),
        "terrain_risk_candidates_ref": _layer_candidate_artifact(
            manifest=manifest,
            ref_key="terrain_risk_candidates_ref",
            artifact_kind="pretrip_layer_terrain_risk_candidates",
            candidate_key="candidates",
            candidates=terrain_risk_candidates,
            source_refs=[
                project.get("excluded_extreme_warning_cp_proposals_ref", ""),
                project.get("risk_attribution_diagnostic_ref", ""),
            ],
        ),
        "detour_route_candidates_ref": _layer_candidate_artifact(
            manifest=manifest,
            ref_key="detour_route_candidates_ref",
            artifact_kind="pretrip_layer_detour_route_candidates",
            candidate_key="candidates",
            candidates=detour_candidates,
            source_refs=[
                manifest["outputs"]["gis_perception_ai_judgements_ref"],
                manifest["outputs"]["gis_semantic_input_bundle_ref"],
            ],
        ),
    }


def _candidate_base_from_judgement(
    judgement: dict[str, Any],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    coords = evidence.get("coordinates") if isinstance(evidence, dict) else None
    if not isinstance(coords, dict):
        coords = {}
    return {
        "candidate_id": str(judgement.get("candidate_id") or judgement.get("judgement_id")),
        "source_evidence_refs": judgement.get("source_evidence_refs", []),
        "source_refs": judgement.get("source_refs", []),
        "source_kind": judgement.get("source_kind"),
        "source_judgement_id": judgement.get("judgement_id"),
        "lat": coords.get("lat"),
        "lon": coords.get("lon"),
        "reason": judgement.get("reason"),
        "confidence": judgement.get("confidence", "medium"),
        "stale_risk": judgement.get("stale_risk", "medium"),
        "review_state": "needs_review",
        "requires_human_review": True,
        "candidate_only": True,
        "observed_fact": False,
        "runtime_safety_truth": False,
        "phase1_runtime_mutation_allowed": False,
    }


def _terrain_risk_candidates_from_project(
    *,
    project_root: Path,
    project: dict[str, Any],
) -> list[dict[str, Any]]:
    ref = project.get("excluded_extreme_warning_cp_proposals_ref")
    if not isinstance(ref, str) or not ref:
        return []
    path = project_root / ref
    if not path.exists():
        return []
    payload = _load_json(path)
    candidates: list[dict[str, Any]] = []
    for proposal in payload.get("proposals", []):
        if not isinstance(proposal, dict):
            continue
        candidates.append(
            {
                "candidate_id": proposal.get("proposal_id"),
                "candidate_kind": "terrain_risk_candidate",
                "source_refs": [f"{ref}#{proposal.get('proposal_id')}"],
                "source_kind": proposal.get("source", "excluded_extreme_risk_dimension"),
                "lat": proposal.get("lat"),
                "lon": proposal.get("lon"),
                "reason": proposal.get("reason_zh"),
                "risk_dimensions": proposal.get("risk_dimensions", {}),
                "confidence": proposal.get("confidence", "medium"),
                "stale_risk": proposal.get("stale_risk", "medium"),
                "review_state": "needs_review",
                "requires_human_review": True,
                "candidate_only": True,
                "observed_fact": False,
                "runtime_safety_truth": False,
                "phase1_runtime_mutation_allowed": False,
            }
        )
    return candidates


def _layer_candidate_artifact(
    *,
    manifest: dict[str, Any],
    ref_key: str,
    artifact_kind: str,
    candidate_key: str,
    candidates: list[dict[str, Any]],
    source_refs: list[str],
) -> dict[str, Any]:
    clean_source_refs = [ref for ref in source_refs if isinstance(ref, str) and ref]
    return {
        "artifact_kind": artifact_kind,
        "schema_version": "route_corridor_map_preparation.candidates.v1",
        "project_id": manifest["project_id"],
        "source_id": f"{manifest['job_id']}.{ref_key}",
        "source_path": manifest["outputs"][ref_key],
        "source_refs": clean_source_refs,
        candidate_key: candidates,
        "counts": {
            "candidate_count": len(candidates),
            "source_ref_count": len(clean_source_refs),
            "candidate_only_count": sum(
                1 for candidate in candidates if candidate.get("candidate_only") is True
            ),
            "runtime_safety_truth_count": sum(
                1
                for candidate in candidates
                if candidate.get("runtime_safety_truth") is not False
            ),
            "human_review_required_count": sum(
                1
                for candidate in candidates
                if candidate.get("requires_human_review") is True
            ),
        },
        "boundary": {
            "candidate_only": True,
            "observed_fact": False,
            "runtime_safety_truth": False,
            "phase1_runtime_mutation_allowed": False,
            "phase2_brain_writeback_allowed": False,
            "mission_graph_mutation_allowed": False,
            "package_mutation_allowed": False,
            "human_review_required_before_use": True,
        },
    }


def _semantic_key_for_judgement(item: dict[str, Any]) -> str:
    hints = item.get("semantic_hints")
    if isinstance(hints, list) and hints:
        return str(hints[0])
    candidate_type = item.get("candidate_type")
    if isinstance(candidate_type, str) and candidate_type:
        return candidate_type
    return str(item.get("source_kind") or "semantic_evidence")


def _ln_level_for_semantic_key(value: str) -> str:
    key = value.lower()
    if any(token in key for token in ("collapse", "hazard", "detour", "warning")):
        return "L2_candidate"
    if any(token in key for token in ("water", "camp", "shelter", "junction")):
        return "L2_candidate"
    return "L1_candidate"


def _checkpoint_type_for_semantic_key(value: str) -> str:
    key = value.lower()
    if any(token in key for token in ("collapse", "hazard", "detour", "warning")):
        return "warning_review"
    if any(token in key for token in ("water", "camp", "shelter")):
        return "water_or_camp_review"
    if "junction" in key:
        return "hint_review"
    return "hint_review"


def _ln_scope_for_semantic_key(value: str) -> str:
    key = value.lower()
    if any(token in key for token in ("collapse", "hazard", "detour", "warning")):
        return "warning_coverage"
    if any(token in key for token in ("water", "camp", "shelter", "junction")):
        return "hint_coverage"
    return "review_only"


def _semantic_judgement_reason(item: dict[str, Any], semantic_key: str) -> str:
    source_kind = item.get("source_kind", "semantic evidence")
    text = _compact_text(item.get("text") or item.get("candidate_type") or "", limit=120)
    if text:
        return (
            f"{source_kind} suggests {semantic_key}; source-backed pretrip "
            f"candidate only: {text}"
        )
    return f"{source_kind} suggests {semantic_key}; source-backed pretrip candidate only."


def _unique_strings(values: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _semantic_hints_from_route_note(candidate: dict[str, Any]) -> list[str]:
    hints: list[str] = []
    category = candidate.get("note_category")
    if isinstance(category, str) and category:
        hints.append(category)
    if candidate.get("potential_ln_signal"):
        hints.append("potential_ln_signal")
    text = " ".join(
        str(candidate.get(key) or "")
        for key in ("normalized_note", "name", "desc", "model_output_summary")
    )
    keyword_hints = {
        "崩": "collapse_hazard",
        "高繞": "technical_detour",
        "水": "water_or_camp_hint",
        "營地": "water_or_camp_hint",
        "山屋": "shelter_hint",
        "叉": "junction_hint",
        "岔": "junction_hint",
        "展望": "viewpoint_hint",
    }
    for keyword, hint in keyword_hints.items():
        if keyword in text:
            hints.append(hint)
    return sorted(set(hints))


def _candidate_coordinates(candidate: dict[str, Any]) -> dict[str, float] | None:
    lat = candidate.get("lat")
    lon = candidate.get("lon")
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        return {"lat": float(lat), "lon": float(lon)}
    return None


def _compact_text(value: Any, *, limit: int = 280) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _risk_score_counts(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "point_count": metadata.get("point_count", 0),
        "source_feature_count": metadata.get("source_feature_count", 0),
        "score_field": metadata.get("score_field", "pretrip_risk"),
        "snap_grid_m": metadata.get("snap_grid_m", 0),
    }


def _risk_ribbon_counts(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "segment_count": metadata.get("segment_count", 0),
        "source_sample_count": metadata.get("source_sample_count", 0),
        "skipped_pair_count": metadata.get("skipped_pair_count", 0),
        "score_field": metadata.get("score_field", "pretrip_risk"),
        "score_surface_type": metadata.get(
            "score_surface_type",
            "route_aligned_risk_ribbon",
        ),
    }


def _risk_heatmap_counts(metadata: dict[str, Any]) -> dict[str, Any]:
    counts = _risk_ribbon_counts(metadata)
    counts["score_field"] = metadata.get(
        "score_field",
        "calibrated_risk_candidate",
    )
    counts["score_surface_type"] = metadata.get(
        "score_surface_type",
        "route_aligned_calibrated_heatmap",
    )
    counts["warning_cp_overlay_count"] = metadata.get("warning_cp_overlay_count", 0)
    score_stats = metadata.get("score_stats", {})
    if isinstance(score_stats, dict):
        counts["max_calibrated_risk"] = score_stats.get("max")
        counts["mean_calibrated_risk"] = score_stats.get("mean")
    return counts


def _load_optional_project_json(
    project_root: Path,
    ref: Any,
    ref_key: str,
    source_refs: list[dict[str, Any]],
    warnings: list[str],
) -> dict[str, Any] | None:
    if not isinstance(ref, str) or not ref:
        warnings.append(f"{ref_key} is missing.")
        return None
    path = project_root / ref
    if not path.exists():
        warnings.append(f"{ref_key} points to a missing file: {ref}")
        return None
    source_refs.append(_source_ref(ref, path, ref_key))
    payload = _load_json(path)
    return payload if isinstance(payload, dict) else None


def _route_corridor_record(
    *,
    project: dict[str, Any],
    route_summary: dict[str, Any],
    route_bbox: dict[str, float],
    query_bbox: dict[str, float],
    request: LayerPreparationRequest,
    gpx_filter: dict[str, Any] | None = None,
    route_evidence_bundle: dict[str, Any] | None = None,
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
        "reference_track_corridor_m": request.reference_track_corridor_m,
        "corridor_policy": (
            (route_evidence_bundle or {})
            .get("route_scope_for_map_preparation", {})
            .get("corridor_policy", "bbox_fetch_then_along_track_filter")
        ),
        "route_bbox_wgs84": route_bbox,
        "query_bbox_wgs84": query_bbox,
        "bbox_boundary": query_bbox,
        "route_evidence_bundle_ref": (
            route_evidence_bundle or {}
        ).get("source_ref"),
        "basis": "selected_golden_route_reference",
        "gpx_speed_filter": gpx_filter or {"applied": False},
        "route_evidence_bundle": route_evidence_bundle or {"available": False},
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


def _write_map_preparation_spec_artifacts(
    project_root: Path,
    manifest: dict[str, Any],
) -> None:
    outputs = manifest["outputs"]
    _write_json(
        project_root / outputs["web_case_query_plan_ref"],
        _web_case_query_plan_from_manifest(manifest),
    )
    _write_json(
        project_root / outputs["raster_label_plan_ref"],
        _raster_label_plan_from_manifest(manifest),
    )
    _write_json(
        project_root / outputs["overpass_vector_evidence_ref"],
        _empty_geojson_evidence_from_manifest(
            manifest,
            artifact_kind="pretrip_overpass_vector_evidence",
            evidence_type="pretrip_overpass_vector_candidate",
            status=_layer_status(manifest, "overpass"),
            source_plan_ref="outputs/layers/plans/overpass_query.ql",
        ),
    )
    _write_json(
        project_root / outputs["terrain_route_samples_ref"],
        _terrain_route_samples_from_project(project_root, manifest),
    )
    _write_json(
        project_root / outputs["web_case_evidence_ref"],
        _web_case_evidence_from_manifest(manifest),
    )
    _write_json(
        project_root / outputs["raster_label_evidence_ref"],
        _empty_geojson_evidence_from_manifest(
            manifest,
            artifact_kind="pretrip_raster_label_evidence",
            evidence_type="pretrip_raster_label_candidate",
            status="planned_not_extracted",
            source_plan_ref=outputs["raster_label_plan_ref"],
        ),
    )


def _web_case_query_plan_from_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    route_scope_ref = manifest["inputs"]["route_evidence_bundle"].get("source_ref")
    return {
        "artifact_kind": "pretrip_web_case_query_plan",
        "schema_version": "route_corridor_map_preparation.v1",
        "project_id": manifest["project_id"],
        "source_id": manifest["job_id"] + ".web_case_plan",
        "source_path": manifest["outputs"]["web_case_query_plan_ref"],
        "status": "planned_no_network",
        "route_scope_ref": route_scope_ref,
        "route_corridor": manifest["route_corridor"],
        "query_scope": {
            "route_family_terms_from_importer": [],
            "route_note_terms_source_ref": manifest["inputs"]["source_refs"]
            .get("normalized_route_note_candidates_ref", {})
            .get("ref"),
            "web_case_keyword_distance_m": 1000.0,
        },
        "network_policy": {
            **manifest["network_policy"],
            "live_web_search_requires_explicit_network_mode": True,
        },
        "output_ref": manifest["outputs"]["web_case_evidence_ref"],
        "boundary": _map_preparation_candidate_boundary(manifest),
    }


def _raster_label_plan_from_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    imagery_layer = _layer_by_id(manifest, "imagery")
    return {
        "artifact_kind": "pretrip_raster_label_plan",
        "schema_version": "route_corridor_map_preparation.v1",
        "project_id": manifest["project_id"],
        "source_id": manifest["job_id"] + ".raster_label_plan",
        "source_path": manifest["outputs"]["raster_label_plan_ref"],
        "status": "planned_local_raster_label_not_run",
        "route_scope_ref": manifest["inputs"]["route_evidence_bundle"].get(
            "source_ref"
        ),
        "route_corridor": manifest["route_corridor"],
        "raster_source_refs": imagery_layer.get("source_refs", []),
        "raster_bbox_wgs84": imagery_layer.get("raster_bbox_wgs84"),
        "ocr_or_vision_performed": False,
        "output_ref": manifest["outputs"]["raster_label_evidence_ref"],
        "boundary": _map_preparation_candidate_boundary(manifest),
    }


def _web_case_evidence_from_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_kind": "pretrip_web_case_evidence",
        "schema_version": "route_corridor_map_preparation.v1",
        "project_id": manifest["project_id"],
        "source_id": manifest["job_id"] + ".web_case_evidence",
        "source_path": manifest["outputs"]["web_case_evidence_ref"],
        "status": "empty_no_network",
        "route_scope_ref": manifest["inputs"]["route_evidence_bundle"].get(
            "source_ref"
        ),
        "source_plan_ref": manifest["outputs"]["web_case_query_plan_ref"],
        "evidence_items": [],
        "counts": {"evidence_item_count": 0},
        "network_policy": manifest["network_policy"],
        "boundary": _map_preparation_candidate_boundary(manifest),
    }


def _terrain_route_samples_from_project(
    project_root: Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    risk_ref_record = manifest["inputs"]["source_refs"].get("risk_score_points_ref", {})
    risk_ref = risk_ref_record.get("ref") if isinstance(risk_ref_record, dict) else None
    if not isinstance(risk_ref, str) or not risk_ref:
        return _empty_geojson_evidence_from_manifest(
            manifest,
            artifact_kind="pretrip_terrain_route_samples",
            evidence_type="pretrip_terrain_route_sample",
            status=_layer_status(manifest, "terrain"),
            source_plan_ref=None,
        )
    risk_path = project_root / risk_ref
    if not risk_path.exists():
        return _empty_geojson_evidence_from_manifest(
            manifest,
            artifact_kind="pretrip_terrain_route_samples",
            evidence_type="pretrip_terrain_route_sample",
            status="missing_risk_source",
            source_plan_ref=None,
        )
    payload = _load_json(risk_path)
    features = []
    for index, feature in enumerate(payload.get("features", [])):
        if not isinstance(feature, dict):
            continue
        properties = dict(feature.get("properties") or {})
        terrain_feature = {
            "type": "Feature",
            "geometry": feature.get("geometry"),
            "properties": {
                **properties,
                "terrain_sample_id": properties.get("sample_id")
                or f"terrain_route_sample.{index + 1:06d}",
                "evidence_type": "pretrip_terrain_route_sample",
                "source_kind": "scout_risk_engine_terrain_sample",
                "source_risk_score_ref": risk_ref,
                "route_scope_ref": manifest["inputs"]["route_evidence_bundle"].get(
                    "source_ref"
                ),
                "candidate_only": True,
                "requires_human_review": True,
                "runtime_safety_truth": False,
            },
        }
        features.append(terrain_feature)
    artifact = _empty_geojson_evidence_from_manifest(
        manifest,
        artifact_kind="pretrip_terrain_route_samples",
        evidence_type="pretrip_terrain_route_sample",
        status="ready_from_risk_score_points" if features else "empty_risk_source",
        source_plan_ref=None,
    )
    artifact["features"] = features
    artifact["counts"] = {
        "feature_count": len(features),
        "source_risk_score_feature_count": len(payload.get("features", [])),
        "runtime_safety_truth_count": 0,
    }
    artifact["source_refs"] = [
        ref
        for ref in (
            risk_ref_record,
            manifest["inputs"]["source_refs"].get("risk_score_points_metadata_ref"),
            manifest["inputs"]["source_refs"].get("risk_route_profile_ref"),
            manifest["inputs"]["source_refs"].get("risk_route_profile_metadata_ref"),
        )
        if isinstance(ref, dict)
    ]
    return artifact


def _empty_geojson_evidence_from_manifest(
    manifest: dict[str, Any],
    *,
    artifact_kind: str,
    evidence_type: str,
    status: str,
    source_plan_ref: str | None,
) -> dict[str, Any]:
    source_refs = _map_preparation_source_artifacts(manifest)
    return {
        "type": "FeatureCollection",
        "artifact_kind": artifact_kind,
        "schema_version": "route_corridor_map_preparation.v1",
        "project_id": manifest["project_id"],
        "source_id": f"{manifest['job_id']}.{artifact_kind}",
        "source_path": _geojson_source_path_for_artifact(manifest, artifact_kind),
        "evidence_type": evidence_type,
        "status": status,
        "route_scope_ref": manifest["inputs"]["route_evidence_bundle"].get(
            "source_ref"
        ),
        "route_corridor": manifest["route_corridor"],
        "source_plan_ref": source_plan_ref,
        "features": [],
        "counts": {"feature_count": 0},
        "source_refs": source_refs,
        "network_policy": manifest["network_policy"],
        "boundary": _map_preparation_candidate_boundary(manifest),
    }


def _geojson_source_path_for_artifact(
    manifest: dict[str, Any],
    artifact_kind: str,
) -> str:
    mapping = {
        "pretrip_overpass_vector_evidence": "overpass_vector_evidence_ref",
        "pretrip_terrain_route_samples": "terrain_route_samples_ref",
        "pretrip_raster_label_evidence": "raster_label_evidence_ref",
    }
    return manifest["outputs"][mapping[artifact_kind]]


def _map_preparation_source_artifacts(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    wanted = {
        "route_evidence_bundle_ref",
        "gpx_speed_filter_report_ref",
        "resume_segment_report_ref",
        "rest_area_candidates_ref",
        "normalized_route_note_candidates_ref",
        "route_note_candidates_ref",
        "imagery_manifest_ref",
        "raster_tile_manifest_ref",
        "risk_score_points_ref",
        "risk_ribbon_ref",
        "calibrated_risk_heatmap_ref",
    }
    return [
        ref
        for key, ref in sorted(manifest["inputs"]["source_refs"].items())
        if key in wanted and isinstance(ref, dict)
    ]


def _map_preparation_candidate_boundary(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_only": True,
        "review_gated": True,
        "observed_fact": False,
        "runtime_safety_truth": False,
        "phase1_runtime_mutation_allowed": False,
        "phase2_brain_writeback_allowed": False,
        "safety_api_called": False,
        "network_calls_allowed": manifest["boundary"]["network_calls_allowed"],
        "raw_gpx_embedded_in_json": False,
        "raw_dem_embedded_in_json": False,
        "raw_tile_embedded_in_json": False,
        "large_scraped_text_embedded": False,
    }


def _layer_by_id(manifest: dict[str, Any], layer_id: str) -> dict[str, Any]:
    return next(
        (
            layer
            for layer in manifest.get("layers", [])
            if isinstance(layer, dict) and layer.get("layer_id") == layer_id
        ),
        {},
    )


def _layer_status(manifest: dict[str, Any], layer_id: str) -> str:
    return str(_layer_by_id(manifest, layer_id).get("status") or "not_requested")


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
    if request.reference_track_corridor_m <= 0:
        raise ValueError("reference_track_corridor_m must be greater than 0")
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


def _load_project_ref_by_value(project_root: Path, ref: Any) -> Any | None:
    if not isinstance(ref, str) or not ref:
        return None
    path = project_root / ref
    if not path.exists():
        return None
    return _load_json(path)


def _normalized_optional_bbox(value: Any) -> dict[str, float] | None:
    if not value:
        return None
    try:
        return normalize_bbox_wgs84(value)
    except (KeyError, TypeError, ValueError):
        return None


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


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
