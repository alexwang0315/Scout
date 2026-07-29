from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import signal
import shutil
import statistics
import subprocess
import sys
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from admin_imagery_sources import (
    DEFAULT_REGISTRY_ID,
    imagery_source_for_project,
    load_imagery_source_registry,
    wmts_source_metadata,
)
from admin_basemap_tiles import build_osm_basemap_contract, normalize_bbox_wgs84
from admin_local_raster_tiles import (
    DEFAULT_IMAGERY_TILE_CACHE_MAX_ZOOM,
    DEFAULT_IMAGERY_TILE_CACHE_MIN_ZOOM,
    build_imagery_tile_cache_plan,
    seed_imagery_tile_cache,
)
from cwa_route_identity import load_cwa_route_identity
from pretrip_models import RouteBBox
from pretrip_osm_pbf_ingest import (
    build_osm_pbf_feature_index,
    extract_osm_pbf_to_osm_json,
    import_osm_pbf_evidence_candidates,
    osm_json_to_geojson_feature_collection,
)
from pretrip_overpass_ingest import (
    ROUTE_CORRIDOR_HIGHWAY_PATTERN,
    import_overpass_evidence_candidates,
)
from pretrip_source_ingest import wgs84_to_twd97


LAYER_PREPARATION_VERSION = "0.1.0"
RISK_PROVENANCE_STAMP_VERSION = "pretrip_risk_provenance.v0.1"
DEFAULT_OSM_PBF_CACHE_TTL_DAYS = 30
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
    "cwa-qpf",
    "soil-moisture",
    "antecedent-rain",
    "cwa-weather",
    "weather",
    "reference-tracks",
    "route",
    "segments",
    "checkpoints",
    "mcp",
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
    "terrain_visualization_ref": (
        "outputs/layers/normalized/terrain_visualization.geojson"
    ),
    "terrain_hillshade_overlay_ref": (
        "outputs/layers/normalized/terrain_hillshade.png"
    ),
    "terrain_elevation_tint_overlay_ref": (
        "outputs/layers/normalized/terrain_elevation_tint.png"
    ),
    "terrain_slope_shading_overlay_ref": (
        "outputs/layers/normalized/terrain_slope_shading.png"
    ),
    "terrain_contours_overlay_ref": (
        "outputs/layers/normalized/terrain_contours.png"
    ),
    "environment_evidence_package_ref": (
        "outputs/environment/environment_evidence_package.json"
    ),
    "environment_factor_matrix_ref": (
        "outputs/environment/environment_factor_matrix.json"
    ),
    "go_no_go_review_draft_ref": "outputs/environment/go_no_go_review_draft.json",
    "cwa_weather_evidence_ref": "outputs/environment/cwa/cwa_weather_evidence.json",
    "cwa_warnings_geojson_ref": "outputs/environment/cwa/warnings.geojson",
    "cwa_observations_geojson_ref": "outputs/environment/cwa/observations.geojson",
    "cwa_qpf_grid_ref": "outputs/environment/cwa/qpf_grid.geojson",
    "cwa_qpf_route_timeline_ref": "outputs/environment/cwa/qpf_route_timeline.json",
    "cwa_qpf_corridor_summary_ref": "outputs/environment/cwa/qpf_corridor_summary.json",
    "cwa_rainfall_grid_manifest_ref": (
        "outputs/environment/cwa/rainfall/rainfall_grid_manifest.json"
    ),
    "cwa_rainfall_route_projection_ref": (
        "outputs/environment/cwa/rainfall/route_grid_projection.geojson"
    ),
    "cwa_rainfall_route_trend_ref": (
        "outputs/environment/cwa/rainfall/route_precipitation_trend.json"
    ),
    "team_target_rainfall_trend_ref": (
        "outputs/environment/cwa/rainfall/route_precipitation_trend.json"
    ),
    "cwa_forecast_timeline_ref": "outputs/environment/cwa/forecast_timeline.json",
    "cwa_astronomy_timeline_ref": "outputs/environment/cwa/astronomy_timeline.json",
    "cwa_tide_marine_timeline_ref": "outputs/environment/cwa/tide_marine_timeline.json",
    "cwa_imagery_registry_ref": "outputs/environment/cwa/imagery/registry_snapshot.json",
    "cwa_radar_frames_manifest_ref": "outputs/environment/cwa/imagery/radar_frames_manifest.json",
    "cwa_satellite_frames_manifest_ref": "outputs/environment/cwa/imagery/satellite_frames_manifest.json",
    "route_imagery_sampling_ref": "outputs/environment/cwa/imagery/route_imagery_sampling.json",
    "radar_motion_estimate_ref": "outputs/environment/cwa/imagery/radar_motion_estimate.json",
    "cwa_weather_imagery_manifest_ref": "outputs/environment/cwa/imagery/weather_imagery_manifest.json",
    "route_weather_risk_package_ref": "outputs/route_weather_risk_package.json",
    "route_weather_lora_alert_ref": "outputs/route_weather_lora_alert.json",
    "soil_moisture_grid_ref": "outputs/environment/gee/soil_moisture_grid.geojson",
    "smap_l4_timeseries_ref": "outputs/environment/gee/smap_l4_timeseries.json",
    "smap_l4_corridor_summary_ref": (
        "outputs/environment/gee/smap_l4_corridor_summary.json"
    ),
    "antecedent_rain_grid_ref": "outputs/environment/gee/antecedent_rain_grid.geojson",
    "gee_gpm_imerg_raw_summary_ref": (
        "outputs/environment/gee/gpm_imerg_raw_summary.json"
    ),
    "gpm_imerg_timeseries_ref": "outputs/environment/gee/gpm_imerg_timeseries.json",
    "gpm_imerg_corridor_summary_ref": (
        "outputs/environment/gee/gpm_imerg_corridor_summary.json"
    ),
    "gee_feature_package_ref": "outputs/environment/gee/scout_gee_feature_package.json",
    "environment_risk_derivatives_ref": (
        "outputs/environment/derived/environment_risk_derivatives.json"
    ),
    "new_landslide_candidates_ref": (
        "outputs/environment/derived/new_landslide_candidates.geojson"
    ),
    "wetness_flash_flood_susceptibility_ref": (
        "outputs/environment/derived/wetness_flash_flood_susceptibility.geojson"
    ),
    "trail_obscurity_risk_ref": (
        "outputs/environment/derived/trail_obscurity_risk.geojson"
    ),
    "practical_darkness_time_ref": (
        "outputs/environment/derived/practical_darkness_time.geojson"
    ),
    "route_revalidation_report_ref": (
        "outputs/environment/derived/route_revalidation_report.json"
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
RASTER_LABEL_OCR_OUTPUT_REF = "outputs/layers/raster_label_ocr_output.json"
RASTER_LABEL_ADAPTER_MANIFEST_REF = "outputs/layers/raster_label_adapter_manifest.json"
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
    "mcp",
    "pois",
    "hazards",
    "corridors",
    "retreat",
    "route-notes",
    "risk-score",
    "risk-ribbon",
    "risk-heatmap",
    "risk-delta",
    "cwa-qpf",
    "soil-moisture",
    "antecedent-rain",
    "cwa-weather",
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
    "cwa": "cwa-weather",
    "owdp": "cwa-weather",
    "cwa-weather-api": "cwa-weather",
    "cwa-warning": "cwa-weather",
    "cwa-warnings": "cwa-weather",
    "qpf": "cwa-qpf",
    "cwa-qpf-grid": "cwa-qpf",
    "smap": "soil-moisture",
    "smap-soil-moisture": "soil-moisture",
    "gee-soil-moisture": "soil-moisture",
    "gpm": "antecedent-rain",
    "gpm-imerg": "antecedent-rain",
    "gee-antecedent-rain": "antecedent-rain",
    "reference_tracks": "reference-tracks",
    "references": "reference-tracks",
    "ref-gpx": "reference-tracks",
    "reference-gpx": "reference-tracks",
}
READY_STATUSES = {
    "ready",
    "ready_from_project_ref",
    "ready_with_fallback",
    "ready_with_remote_source",
    "wmts_runtime_only",
    "projection_ready",
    "planned_no_network",
}
HEAVY_LOCAL_LAYER_IDS = {"terrain"}
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
SCOUT_RISK_ROUTE_BASE_SAMPLING_STRATEGY = (
    "reference_progress_projected_to_nearest_overpass_segment.v1"
)
DEFAULT_OVERPASS_ALIGNMENT_MAX_PROJECTION_DISTANCE_M = 50.0
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
TERRAIN_VISUALIZATION_MODES = (
    "hillshade",
    "elevation_tint",
    "slope_shading",
    "contours",
)
TERRAIN_SLOPE_CLASSES = (
    {
        "class_id": "slope-0-10",
        "min_degrees": 0.0,
        "max_degrees": 10.0,
        "label": "0-10 deg",
        "color": "#b7e4a8",
    },
    {
        "class_id": "slope-10-20",
        "min_degrees": 10.0,
        "max_degrees": 20.0,
        "label": "10-20 deg",
        "color": "#d9ef8b",
    },
    {
        "class_id": "slope-20-30",
        "min_degrees": 20.0,
        "max_degrees": 30.0,
        "label": "20-30 deg",
        "color": "#fee08b",
    },
    {
        "class_id": "slope-30-40",
        "min_degrees": 30.0,
        "max_degrees": 40.0,
        "label": "30-40 deg",
        "color": "#fdae61",
    },
    {
        "class_id": "slope-40-50",
        "min_degrees": 40.0,
        "max_degrees": 50.0,
        "label": "40-50 deg",
        "color": "#f46d43",
    },
    {
        "class_id": "slope-gt-50",
        "min_degrees": 50.0,
        "max_degrees": None,
        "label": ">50 deg",
        "color": "#d73027",
    },
)
TERRAIN_CONTOUR_INTERVAL_M = 100.0
TERRAIN_DTM_CELL_RESOLUTION_M = 20.0
TERRAIN_DTM_CORRIDOR_HALF_WIDTH_M = 500.0
TERRAIN_DTM_CORRIDOR_TOTAL_WIDTH_M = TERRAIN_DTM_CORRIDOR_HALF_WIDTH_M * 2.0
TERRAIN_DTM_SEGMENT_BUCKET_M = 500.0
TERRAIN_DTM_CONTOUR_TOLERANCE_M = 5.0
RASTER_LABEL_PREFERRED_OCR_SOURCE_IDS = (
    "happyman_rudy_twmap",
    "happyman_rudy",
)
RASTER_LABEL_EXTRACTION_TARGETS = (
    "trail_mileage_k_anchor",
    "road_mileage_stone",
    "trail_name_label",
    "named_place_label",
    "cellular_communication_point",
    "trail_annotation_label",
    "contour_elevation_label",
    "hazard_annotation_label",
)
RASTER_LABEL_MILEAGE_ANCHOR_GROUPING_POLICY = {
    "standalone_mileage_anchor_allowed": False,
    "route_context_key_fields": (
        "project_id",
        "source_id",
        "trail_name_label",
        "nearest_named_point",
        "projected_centerline_id",
    ),
    "required_context_any": (
        "trail_name_label",
        "route_family_from_workspace",
        "named_place_label",
        "route_centerline_projection",
    ),
    "same_tile_bbox_grouping_px": 256,
    "route_distance_grouping_window_m": 300.0,
    "duplicate_resolution_key": (
        "route_context_key",
        "normalized_mileage_k",
    ),
    "road_mileage_stone_policy": (
        "公路公里樁與步道 K 不同；保留為 road_mileage_stone evidence，"
        "不得合併進 trail_mileage_k_anchor。"
    ),
    "ambiguous_anchor_review_required": True,
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
    prepare_cwa_imagery: bool = False
    bbox: dict[str, Any] | None = None
    route_evidence_bundle: Path | None = None
    route_corridor_m: float = 500.0
    reference_track_corridor_m: float = 300.0
    ai_mode: AiMode = "fixture-or-precomputed"
    ai_output_policy: str = "hash-and-summary"
    imagery_min_zoom: int = DEFAULT_IMAGERY_TILE_CACHE_MIN_ZOOM
    imagery_max_zoom: int = DEFAULT_IMAGERY_TILE_CACHE_MAX_ZOOM
    seed_imagery_cache: bool = False
    run_post_layer_enrichments: bool = True
    run_map_preparation_spec_artifacts: bool = True
    imagery_provider_allows_offline_prefetch: bool = False
    imagery_seed_max_tiles: int | None = None
    imagery_cache_fallback_project_ids: tuple[str, ...] = ()
    osm_pbf_path: Path | None = None
    osm_pbf_source_url: str | None = None
    osm_pbf_cache_ttl_days: int = DEFAULT_OSM_PBF_CACHE_TTL_DAYS
    osmium_bin: str = "osmium"
    prepared_at: str | None = None


def run_layer_preparation(request: LayerPreparationRequest) -> dict[str, Any]:
    _validate_request(request)
    _maybe_prepare_local_osm_pbf_evidence(request)
    _maybe_fetch_overpass_evidence(request)
    _maybe_seed_imagery_tile_cache(request)
    manifest, project_root, project = _build_layer_preparation_manifest(
        request,
        workspace_file_mutation_allowed=True,
    )
    outputs = manifest["outputs"]
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
    if request.run_map_preparation_spec_artifacts:
        _write_map_preparation_spec_artifacts(project_root, manifest)
        map_preparation_spec_artifacts = {
            "status": "completed",
            "name": "map_preparation_spec_artifacts",
        }
    else:
        map_preparation_spec_artifacts = _skipped_connected_refresh_post_enrichment(
            "map_preparation_spec_artifacts"
        )
    manifest["map_preparation_spec_artifacts"] = map_preparation_spec_artifacts
    outputs.update(_write_planned_overpass_evidence(project_root, manifest))
    _update_project_refs(project_root / "project.json", project, outputs, manifest["finished_at"])
    raster_label_preparation = (
        _run_raster_label_preparation_after_layer_preparation(
            project_root=project_root,
            manifest=manifest,
        )
        if request.run_post_layer_enrichments
        else _skipped_connected_refresh_post_enrichment("raster_label_preparation")
    )
    manifest["raster_label_preparation"] = raster_label_preparation
    outputs.update(raster_label_preparation.get("output_refs", {}))
    if raster_label_preparation.get("project_refs_updated"):
        _update_project_refs(
            project_root / "project.json",
            project,
            outputs,
            manifest["finished_at"],
        )
    boss_point_synthesis = (
        _run_boss_point_synthesis_after_layer_preparation(
            project_root=project_root,
            manifest=manifest,
        )
        if request.run_post_layer_enrichments
        else _skipped_connected_refresh_post_enrichment("boss_point_synthesis")
    )
    manifest["boss_point_synthesis"] = boss_point_synthesis
    if boss_point_synthesis.get("status") == "completed":
        outputs.update(boss_point_synthesis.get("output_refs", {}))
        outputs["boss_point_synthesis_status"] = "completed"
        outputs["boss_point_synthesis_updated_at"] = manifest["finished_at"]
        outputs["boss_point_synthesis_trigger"] = boss_point_synthesis.get(
            "trigger",
            "prepare_layers_with_risk",
        )
        outputs["boss_point_count"] = boss_point_synthesis.get("boss_point_count", 0)
        outputs["route_pressure_sample_count"] = boss_point_synthesis.get(
            "route_pressure_sample_count",
            0,
        )
        outputs["route_pressure_peak_count"] = boss_point_synthesis.get(
            "route_pressure_peak_count",
            0,
        )
        _update_project_refs(
            project_root / "project.json",
            project,
            outputs,
            manifest["finished_at"],
        )
    mileage_tag_alignment = (
        _run_mileage_tag_alignment_after_layer_preparation(
            project_root=project_root,
            manifest=manifest,
        )
        if request.run_post_layer_enrichments
        else _skipped_connected_refresh_post_enrichment("mileage_tag_alignment")
    )
    manifest["mileage_tag_alignment"] = mileage_tag_alignment
    if mileage_tag_alignment.get("status") == "completed":
        outputs.update(mileage_tag_alignment.get("output_refs", {}))
        outputs["mileage_tag_alignment_count"] = mileage_tag_alignment.get(
            "tag_count",
            0,
        )
        _update_project_refs(
            project_root / "project.json",
            project,
            outputs,
            manifest["finished_at"],
        )
    architecture_preparation = (
        _run_architecture_preparation_after_layer_preparation(
            project_root=project_root,
            manifest=manifest,
        )
        if request.run_post_layer_enrichments
        else _skipped_connected_refresh_post_enrichment(
            "architecture_preparation"
        )
    )
    manifest["architecture_preparation"] = architecture_preparation
    outputs.update(architecture_preparation.get("output_refs", {}))
    summary = _summary_from_manifest(manifest)
    map_preparation_summary = _map_preparation_summary_from_manifest(manifest)
    adapter_manifest = _adapter_manifest_from_manifest(manifest)
    map_projection = _map_projection_from_manifest(manifest)
    debug_events = _debug_events_from_manifest(manifest)
    job_payload = _job_payload_from_manifest(manifest)
    _write_json(project_root / outputs["layer_preparation_manifest_ref"], manifest)
    _write_json(project_root / outputs["layer_preparation_job_ref"], job_payload)
    _write_json(project_root / outputs["layer_preparation_summary_ref"], summary)
    _write_json(project_root / outputs["map_preparation_summary_ref"], map_preparation_summary)
    _write_json(project_root / outputs["layer_adapter_manifest_ref"], adapter_manifest)
    _write_json(project_root / outputs["layer_map_projection_ref"], map_projection)
    _write_jsonl(project_root / outputs["layer_debug_projection_events_ref"], debug_events)
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


def _maybe_prepare_local_osm_pbf_evidence(request: LayerPreparationRequest) -> None:
    if request.osm_pbf_path is None:
        return
    normalized_layers = set(_normalize_layer_ids(request.layers))
    if not {"osm", "overpass"} & normalized_layers:
        return
    project_root = _resolve_project_root(request)
    _reject_fixture_fetch(project_root)
    project_path = project_root / "project.json"
    project = _load_json(project_path)
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
    pbf_path = request.osm_pbf_path.expanduser().resolve()
    prepared_at = request.prepared_at or _utc_now()
    pbf_cache = _osm_pbf_cache_metadata(
        pbf_path,
        source_url=request.osm_pbf_source_url,
        ttl_days=request.osm_pbf_cache_ttl_days,
        now_iso=prepared_at,
    )
    raw_ref = "normalized/map/osm_pbf_phase_a_raw.osm.json"
    raw_path = project_root / raw_ref
    raw_bytes, extraction_plan = _extract_osm_pbf_raw_payload(
        pbf_path=pbf_path,
        bbox=query_bbox,
        raw_payload_path=raw_path,
        osmium_bin=request.osmium_bin,
    )
    raw_payload = json.loads(raw_bytes.decode("utf-8"))
    normalized_ref = planned_request["normalized_artifact_target_ref"]
    evidence_ref = "candidates/overpass_evidence.json"
    pbf_sha256 = _sha256_file(pbf_path) if pbf_path.exists() else None
    render_extract = _local_osm_render_extract_metadata(
        project_root=project_root,
        extraction_plan=extraction_plan,
        raw_payload_ref=raw_ref,
        raw_payload=raw_payload,
        pbf_cache=pbf_cache,
    )
    feature_index_ref = "outputs/layers/normalized/osm_pbf_feature_index.json"
    render_geojson = _export_local_osm_render_geojson(
        project_root=project_root,
        extraction_plan=extraction_plan,
        osmium_bin=request.osmium_bin,
        raw_payload=raw_payload,
        raw_payload_ref=raw_ref,
    )
    feature_index_source_ref = render_geojson["ref"] if render_geojson else raw_ref
    feature_index_payload = render_geojson["payload"] if render_geojson else raw_payload
    feature_index = build_osm_pbf_feature_index(
        feature_index_payload,
        source_ref=feature_index_source_ref,
        render_source_ref=render_extract["preferred_render_source_ref"],
        request_timestamp=prepared_at,
        route_corridor=route_corridor,
        pbf_cache_metadata=pbf_cache,
        pbf_source_uri=pbf_path.as_posix(),
        pbf_download_url=request.osm_pbf_source_url,
        pbf_source_sha256=pbf_sha256,
    )
    evidence = import_osm_pbf_evidence_candidates(
        raw_payload,
        query_body=json.dumps(extraction_plan, ensure_ascii=False, sort_keys=True),
        bbox_wgs84=RouteBBox(
            min_lat=query_bbox["south"],
            min_lon=query_bbox["west"],
            max_lat=query_bbox["north"],
            max_lon=query_bbox["east"],
        ),
        route_corridor=route_corridor,
        request_timestamp=prepared_at,
        endpoint=f"local-osm-pbf://{pbf_path.as_posix()}",
        raw_payload_uri=raw_ref,
        raw_response_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        normalized_artifact_path=normalized_ref,
        source_ref=raw_ref,
        pbf_source_uri=pbf_path.as_posix(),
        pbf_download_url=request.osm_pbf_source_url,
        pbf_source_sha256=pbf_sha256,
        pbf_cache_metadata=pbf_cache,
        extraction_plan=extraction_plan,
    )
    _write_json(project_root / raw_ref, raw_payload)
    _write_json(project_root / normalized_ref, evidence["normalized_geojson"])
    _write_json(project_root / evidence_ref, evidence)
    _write_json(project_root / feature_index_ref, feature_index)
    updated = {
        **project,
        "overpass_evidence_ref": evidence_ref,
        "overpass_map_context_ref": normalized_ref,
        "overpass_raw_payload_ref": raw_ref,
        "overpass_candidate_count": evidence["counts"]["candidates"],
        "overpass_skipped_object_count": evidence["counts"]["skipped"],
        "osm_pbf_source_ref": pbf_path.as_posix(),
        "osm_pbf_source_url": request.osm_pbf_source_url,
        "osm_pbf_source_sha256": pbf_sha256,
        "osm_pbf_raw_payload_ref": raw_ref,
        "osm_pbf_extracted_at": prepared_at,
        "osm_pbf_route_extract_ref": render_extract.get("pbf_extract_ref"),
        "osm_pbf_render_extract_ref": render_extract["preferred_render_source_ref"],
        "osm_pbf_render_extract_manifest_ref": render_extract["manifest_ref"],
        "osm_pbf_render_extract_source_kind": render_extract[
            "preferred_render_source_kind"
        ],
        "osm_pbf_render_extract_feature_count": render_extract["feature_count"],
        "osm_pbf_render_geojson_ref": (
            render_geojson["ref"] if render_geojson is not None else None
        ),
        "osm_pbf_feature_index_ref": feature_index_ref,
        "osm_pbf_feature_index_feature_count": feature_index["counts"][
            "item_count"
        ],
        "osm_pbf_feature_index_category_counts": feature_index["counts"][
            "category_counts"
        ],
        "osm_pbf_cache_ttl_days": pbf_cache["cache_ttl_days"],
        "osm_pbf_cache_status": pbf_cache["cache_status"],
        "osm_pbf_cache_expires_at": pbf_cache["expires_at"],
        "osm_pbf_refresh_required": pbf_cache["refresh_required"],
    }
    _write_json(project_path, updated)


def _maybe_fetch_overpass_evidence(request: LayerPreparationRequest) -> None:
    normalized_layers = _normalize_layer_ids(request.layers)
    if "overpass" not in normalized_layers:
        return
    if request.osm_pbf_path is not None:
        return
    if request.network_mode != "explicit-fetch" or not request.allow_network_fetch:
        return
    project_root = _resolve_project_root(request)
    _reject_fixture_fetch(project_root)
    project_path = project_root / "project.json"
    project = _load_json(project_path)
    existing_overpass_ref = project.get("overpass_evidence_ref")
    if existing_overpass_ref:
        existing_overpass_path = project_root / str(existing_overpass_ref)
        if existing_overpass_path.exists():
            existing_overpass = _load_json(existing_overpass_path)
            if existing_overpass.get("status") != "planned_no_network":
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


def _maybe_prepare_environment_evidence(request: LayerPreparationRequest) -> None:
    normalized_layers = set(_normalize_layer_ids(request.layers))
    requested_cwa = bool({"cwa-weather", "cwa-qpf"} & normalized_layers)
    requested_gee = bool({"soil-moisture", "antecedent-rain"} & normalized_layers)
    if not requested_cwa and not requested_gee:
        return

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
    query_bbox = _expand_bbox_by_meters(route_bbox, request.route_corridor_m)
    prepared_at = request.prepared_at or _utc_now()
    outputs: dict[str, Any] = {}

    if requested_cwa:
        outputs.update(
            _prepare_cwa_environment_artifacts(
                project_root=project_root,
                project=project,
                route_summary=route_summary,
                bbox=query_bbox,
                request=request,
                prepared_at=prepared_at,
            )
        )
    if requested_gee:
        outputs.update(
            _prepare_gee_environment_artifacts(
                project_root=project_root,
                project=project,
                route_summary=route_summary,
                bbox=query_bbox,
                request=request,
                prepared_at=prepared_at,
                cwa_time_metadata=outputs.get("cwa_time_metadata")
                if isinstance(outputs.get("cwa_time_metadata"), dict)
                else None,
            )
        )

    if outputs:
        current_project = _load_json(project_path)
        outputs.update(
            _write_environment_synthesis_artifacts(
                project_root=project_root,
                project={**project, **current_project, **outputs},
                route_summary=route_summary,
                bbox=query_bbox,
                prepared_at=prepared_at,
                requested_cwa=requested_cwa,
                requested_gee=requested_gee,
            )
        )

    if outputs:
        current_project = _load_json(project_path)
        _write_json(
            project_path,
            {
                **project,
                **current_project,
                **outputs,
                "environment_evidence_updated_at": prepared_at,
            },
        )


def _prepare_cwa_environment_artifacts(
    *,
    project_root: Path,
    project: dict[str, Any],
    route_summary: dict[str, Any],
    bbox: dict[str, float],
    request: LayerPreparationRequest,
    prepared_at: str,
) -> dict[str, Any]:
    cwa_dir = project_root / "outputs" / "environment" / "cwa"
    weather_points: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    fetch_results: list[dict[str, Any]] = []
    external_calls_made = False
    external_fetch_requested = (
        request.network_mode == "explicit-fetch" and request.allow_network_fetch
    )
    source_run_id = f"cwa.{project.get('project_id') or request.project_id}.{_job_timestamp(prepared_at)}"
    cache_policy = _cwa_no_cache_policy()

    if external_fetch_requested:
        try:
            from scout_weather_integration import (
                CWA_36H_FORECAST,
                fetch_cwa_dataset,
                normalize_cwa_weather_points,
            )

            forecast_payload = fetch_cwa_dataset(CWA_36H_FORECAST, timeout_s=20.0)
            weather_points = normalize_cwa_weather_points(
                CWA_36H_FORECAST,
                forecast_payload,
                source_run_id=source_run_id,
            )
            fetch_results.append(
                _environment_fetch_result(CWA_36H_FORECAST, status="ready")
            )
        except Exception as exc:  # pragma: no cover - exercised through live smoke.
            fetch_results.append(
                _environment_fetch_result(
                    "F-C0032-001",
                    status="failed",
                    error=_safe_exception_summary(exc),
                )
            )
        try:
            from scout_weather_integration import (
                CWA_WEATHER_WARNING,
                fetch_cwa_dataset,
                normalize_cwa_warnings,
            )

            warning_payload = fetch_cwa_dataset(CWA_WEATHER_WARNING, timeout_s=20.0)
            warnings = normalize_cwa_warnings(
                warning_payload,
                source_run_id=source_run_id,
            )
            fetch_results.append(
                _environment_fetch_result(CWA_WEATHER_WARNING, status="ready")
            )
        except Exception as exc:  # pragma: no cover - exercised through live smoke.
            fetch_results.append(
                _environment_fetch_result(
                    "W-C0033-001",
                    status="failed",
                    error=_safe_exception_summary(exc),
                )
            )
        try:
            from scout_weather_integration import fetch_cwa_dataset

            rain_payload = fetch_cwa_dataset("O-A0002-001", timeout_s=20.0)
            observations = _normalize_cwa_rain_observations(
                rain_payload,
                bbox=bbox,
                source_run_id=source_run_id,
            )
            fetch_results.append(
                _environment_fetch_result("O-A0002-001", status="ready")
            )
        except Exception as exc:  # pragma: no cover - exercised through live smoke.
            fetch_results.append(
                _environment_fetch_result(
                    "O-A0002-001",
                    status="failed",
                    error=_safe_exception_summary(exc),
                )
            )
    else:
        fetch_results.append(
            _environment_fetch_result(
                "cwa_opendata",
                status="not_fetched",
                error={
                    "reason": "network_mode_not_explicit_fetch_or_allow_network_fetch_false"
                },
            )
            )

    rainfall_grid_outputs = _maybe_prepare_cwa_precipitation_grid_job(
        project_root=project_root,
        project=project,
        request=request,
        bbox=bbox,
        prepared_at=prepared_at,
    )
    if rainfall_grid_outputs.get("cwa_rainfall_grid_status") == "ready":
        fetch_results.extend(
            _environment_fetch_result(dataset_id, status="ready")
            for dataset_id in ("O-B0045-001", "F-B0046-001")
        )
    external_calls_made = any(item.get("status") == "ready" for item in fetch_results)
    time_metadata = _cwa_time_metadata(
        prepared_at=prepared_at,
        api_request_attempted=external_fetch_requested,
        external_calls_made=external_calls_made,
        weather_points=weather_points,
        warnings=warnings,
        observations=observations,
    )
    qpf_features = _cwa_qpf_features_from_weather_points(
        weather_points,
        bbox=bbox,
        source_run_id=source_run_id,
        prepared_at=prepared_at,
        time_metadata=time_metadata,
    )
    observation_features = _cwa_observation_features(
        observations,
        time_metadata=time_metadata,
    )
    warning_features = _cwa_warning_features(
        warnings,
        bbox=bbox,
        source_run_id=source_run_id,
        time_metadata=time_metadata,
    )
    if not qpf_features and not observation_features and not warning_features:
        qpf_features.append(
            _environment_status_feature(
                bbox=bbox,
                layer_id="cwa-qpf",
                label="CWA QPF not available",
                status="not_available",
                provider="cwa_opendata",
                source_run_id=source_run_id,
                prepared_at=prepared_at,
                detail="CWA fetch did not return route-visible forecast or station data.",
                extra={**time_metadata, "cwa_time_metadata": time_metadata},
            )
        )

    cwa_evidence = {
        "artifact_kind": "cwa_weather_environment_evidence",
        "schema_version": LAYER_PREPARATION_VERSION,
        "project_id": project.get("project_id") or request.project_id,
        "generated_at": prepared_at,
        "request_timestamp": prepared_at,
        "source_run_id": source_run_id,
        "provider": "cwa_opendata",
        "source_family": "cwa_weather_environment",
        "status": "ready" if any(item["status"] == "ready" for item in fetch_results) else "not_available",
        "external_api_calls_made": external_calls_made,
        "api_request_attempted": external_fetch_requested,
        "cache_policy": cache_policy,
        **time_metadata,
        "cwa_time_metadata": time_metadata,
        "temporal_coverage": time_metadata,
        "datasets": fetch_results,
        "counts": {
            "weather_point_count": len(weather_points),
            "warning_count": len(warnings),
            "rain_observation_count": len(observations),
            "qpf_feature_count": len(qpf_features),
        },
        "weather_points": weather_points[:80],
        "warnings": warnings[:80],
        "observations": observations[:120],
        "qpf_source_note": (
            "This backward-compatible qpf_grid.geojson exposes forecast-derived "
            "point candidates. Official O-B0045-001 QPE and F-B0046-001 QPF "
            "numeric grids, when prepared, are stored under the rainfall refs."
        ),
        "rainfall_grids": {
            "status": rainfall_grid_outputs.get(
                "cwa_rainfall_grid_status", "not_requested"
            ),
            "manifest_ref": rainfall_grid_outputs.get(
                "cwa_rainfall_grid_manifest_ref"
            ),
            "route_projection_ref": rainfall_grid_outputs.get(
                "cwa_rainfall_route_projection_ref"
            ),
            "route_trend_ref": rainfall_grid_outputs.get(
                "cwa_rainfall_route_trend_ref"
            ),
            "processing_target": "server_side_job",
            "raspberry_pi_grid_processing": False,
            "mobile_grid_processing": False,
        },
        "boundary": _environment_boundary(external_calls_made=external_calls_made),
    }
    qpf_geojson = _feature_collection(
        "cwa_qpf_grid",
        qpf_features,
        project_id=project.get("project_id") or request.project_id,
        generated_at=prepared_at,
        bbox=bbox,
        external_calls_made=external_calls_made,
    )
    qpf_geojson["temporal_coverage"] = time_metadata
    warnings_geojson = _feature_collection(
        "cwa_weather_warnings",
        warning_features,
        project_id=project.get("project_id") or request.project_id,
        generated_at=prepared_at,
        bbox=bbox,
        external_calls_made=external_calls_made,
    )
    warnings_geojson["temporal_coverage"] = time_metadata
    observations_geojson = _feature_collection(
        "cwa_rain_observations",
        observation_features,
        project_id=project.get("project_id") or request.project_id,
        generated_at=prepared_at,
        bbox=bbox,
        external_calls_made=external_calls_made,
    )
    observations_geojson["temporal_coverage"] = time_metadata
    qpf_timeline = _cwa_qpf_timeline(
        qpf_features,
        project_id=project.get("project_id") or request.project_id,
        generated_at=prepared_at,
        time_metadata=time_metadata,
        external_calls_made=external_calls_made,
    )
    qpf_summary = _cwa_qpf_corridor_summary(
        qpf_features,
        observations,
        project_id=project.get("project_id") or request.project_id,
        route_summary=route_summary,
        generated_at=prepared_at,
        bbox=bbox,
        time_metadata=time_metadata,
        external_calls_made=external_calls_made,
    )
    forecast_timeline = _cwa_forecast_timeline(
        weather_points,
        project_id=project.get("project_id") or request.project_id,
        generated_at=prepared_at,
        time_metadata=time_metadata,
        external_calls_made=external_calls_made,
    )
    astronomy_timeline = _cwa_astronomy_timeline(
        project_id=project.get("project_id") or request.project_id,
        generated_at=prepared_at,
        time_metadata=time_metadata,
        external_calls_made=external_calls_made,
    )
    tide_marine_timeline = _cwa_tide_marine_timeline(
        project_id=project.get("project_id") or request.project_id,
        generated_at=prepared_at,
        time_metadata=time_metadata,
        external_calls_made=external_calls_made,
    )
    for artifact in (
        qpf_geojson,
        warnings_geojson,
        observations_geojson,
        qpf_timeline,
        qpf_summary,
        forecast_timeline,
        astronomy_timeline,
        tide_marine_timeline,
    ):
        artifact["cache_policy"] = cache_policy
        artifact["cwa_time_metadata"] = time_metadata

    imagery_outputs = _maybe_prepare_cwa_imagery_server_job(
        project_root=project_root,
        project=project,
        request=request,
        prepared_at=prepared_at,
    )
    cwa_evidence["weather_imagery"] = {
        "status": imagery_outputs.get("cwa_weather_imagery_status", "not_requested"),
        "manifest_ref": imagery_outputs.get("cwa_weather_imagery_manifest_ref"),
        "route_weather_risk_package_ref": imagery_outputs.get(
            "route_weather_risk_package_ref"
        ),
        "processing_target": "server_side_job",
        "raspberry_pi_image_processing": False,
        "mobile_image_processing": False,
    }

    _write_json(cwa_dir / "cwa_weather_evidence.json", cwa_evidence)
    _write_json(cwa_dir / "qpf_grid.geojson", qpf_geojson)
    _write_json(cwa_dir / "warnings.geojson", warnings_geojson)
    _write_json(cwa_dir / "observations.geojson", observations_geojson)
    _write_json(cwa_dir / "qpf_route_timeline.json", qpf_timeline)
    _write_json(cwa_dir / "qpf_corridor_summary.json", qpf_summary)
    _write_json(cwa_dir / "forecast_timeline.json", forecast_timeline)
    _write_json(cwa_dir / "astronomy_timeline.json", astronomy_timeline)
    _write_json(cwa_dir / "tide_marine_timeline.json", tide_marine_timeline)

    return {
        "cwa_weather_evidence_ref": OUTPUT_REFS["cwa_weather_evidence_ref"],
        "cwa_warnings_geojson_ref": OUTPUT_REFS["cwa_warnings_geojson_ref"],
        "cwa_observations_geojson_ref": OUTPUT_REFS["cwa_observations_geojson_ref"],
        "cwa_qpf_grid_ref": OUTPUT_REFS["cwa_qpf_grid_ref"],
        "cwa_qpf_route_timeline_ref": OUTPUT_REFS["cwa_qpf_route_timeline_ref"],
        "cwa_qpf_corridor_summary_ref": OUTPUT_REFS[
            "cwa_qpf_corridor_summary_ref"
        ],
        "cwa_forecast_timeline_ref": OUTPUT_REFS["cwa_forecast_timeline_ref"],
        "cwa_astronomy_timeline_ref": OUTPUT_REFS["cwa_astronomy_timeline_ref"],
        "cwa_tide_marine_timeline_ref": OUTPUT_REFS["cwa_tide_marine_timeline_ref"],
        "cwa_weather_point_count": len(weather_points),
        "cwa_warning_count": len(warnings),
        "cwa_rain_observation_count": len(observations),
        "cwa_qpf_feature_count": len(qpf_features),
        "cwa_api_request_attempted": external_fetch_requested,
        "cwa_api_request_attempted_at": (
            time_metadata.get("api_request_attempted_at", "") or ""
        ),
        "cwa_api_request_attempted_at_hour": (
            time_metadata.get("api_request_attempted_at_hour", "") or ""
        ),
        "cwa_fetched_at": prepared_at if external_calls_made else "",
        "cwa_fetched_at_hour": time_metadata.get("fetched_at_hour", ""),
        "cwa_valid_from_hour": time_metadata.get("valid_from_hour", ""),
        "cwa_valid_until_hour": time_metadata.get("valid_until_hour", ""),
        "cwa_external_api_calls_made": external_calls_made,
        "cwa_cache_policy": cache_policy,
        "cwa_cacheable": False,
        "cwa_ttl_seconds": 0,
        "cwa_time_metadata": time_metadata,
        **rainfall_grid_outputs,
        **imagery_outputs,
    }


def _maybe_prepare_cwa_precipitation_grid_job(
    *,
    project_root: Path,
    project: dict[str, Any],
    request: LayerPreparationRequest,
    bbox: dict[str, float],
    prepared_at: str,
) -> dict[str, Any]:
    if "cwa-qpf" not in _normalize_layer_ids(request.layers):
        return {"cwa_rainfall_grid_status": "not_requested"}
    if request.network_mode != "explicit-fetch" or not request.allow_network_fetch:
        return {"cwa_rainfall_grid_status": "not_requested_no_explicit_fetch"}
    if request.profile != "mac-workstation":
        return {
            "cwa_rainfall_grid_status": "blocked_server_side_grid_preparation_required",
            "cwa_rainfall_grid_blocker": "profile_must_be_mac_workstation",
        }
    try:
        route_identity, route_points = load_cwa_route_identity(project_root, project)
    except (OSError, ValueError):
        return {
            "cwa_rainfall_grid_status": "blocked_missing_route_geometry",
            "cwa_rainfall_grid_blocker": "segment_display_geometry_ref_missing_or_empty",
        }
    try:
        from cwa_precipitation_grid_ingestor import (
            prepare_cwa_precipitation_workspace,
        )

        return prepare_cwa_precipitation_workspace(
            project_root=project_root,
            project_id=route_identity["projectId"],
            route_points=route_points,
            route_bbox=bbox,
            route_source_ref=route_identity["routeRef"],
            route_source_sha256=route_identity["routeSha256"],
            route_basis=route_identity["routeBasis"],
            fetched_at=prepared_at,
        )
    except Exception as exc:  # pragma: no cover - live provider/server worker path.
        return {
            "cwa_rainfall_grid_status": "fetch_or_processing_failed",
            "cwa_rainfall_grid_error": _safe_exception_summary(exc),
        }


def _maybe_prepare_cwa_imagery_server_job(
    *,
    project_root: Path,
    project: dict[str, Any],
    request: LayerPreparationRequest,
    prepared_at: str,
) -> dict[str, Any]:
    if not request.prepare_cwa_imagery:
        return {"cwa_weather_imagery_status": "not_requested"}
    if request.profile != "mac-workstation":
        return {
            "cwa_weather_imagery_status": "blocked_server_side_imagery_preparation_required",
            "cwa_weather_imagery_blocker": "profile_must_be_mac_workstation",
        }
    if request.network_mode != "explicit-fetch" or not request.allow_network_fetch:
        return {
            "cwa_weather_imagery_status": "blocked_explicit_network_fetch_required",
            "cwa_weather_imagery_blocker": "explicit_fetch_and_allow_network_fetch_required",
        }
    try:
        route_identity, route_points = load_cwa_route_identity(project_root, project)
    except (OSError, ValueError):
        return {
            "cwa_weather_imagery_status": "blocked_missing_route_geometry",
            "cwa_weather_imagery_blocker": "segment_display_geometry_ref_missing_or_empty",
        }
    try:
        from cwa_imagery_registry import build_cwa_imagery_registry
        from cwa_radar_ingestor import CwaRadarIngestor
        from cwa_satellite_ingestor import CwaSatelliteIngestor
        from radar_satellite_risk_extractor import run_server_side_cwa_imagery_job
        from weather_imagery_tile_cache import WeatherImageryTileCache

        true_color_urls = {
            extent: value
            for extent, value in {
                "full_disk": os.environ.get("SCOUT_CWA_TRUE_COLOR_FULL_DISK_URL"),
                "east_asia": os.environ.get("SCOUT_CWA_TRUE_COLOR_EAST_ASIA_URL"),
                "taiwan": os.environ.get("SCOUT_CWA_TRUE_COLOR_TAIWAN_URL"),
            }.items()
            if value
        }
        registry = build_cwa_imagery_registry(true_color_urls=true_color_urls)
        cache_root = Path(
            os.environ.get(
                "SCOUT_CWA_IMAGERY_CACHE_ROOT",
                "~/.scout-fusion/cwa-weather-imagery-cache",
            )
        ).expanduser()
        cache = WeatherImageryTileCache(cache_root)
        refs = run_server_side_cwa_imagery_job(
            project_root=project_root,
            route_id=str(project.get("project_id") or request.project_id),
            route_identity=route_identity,
            route_points=route_points,
            terrain_segments=_terrain_segments_for_weather_imagery(project_root, project),
            radar_ingestor=CwaRadarIngestor.from_cwa_opendata(
                registry=registry,
                cache=cache,
            ),
            satellite_ingestor=CwaSatelliteIngestor.from_cwa_opendata(
                registry=registry,
                cache=cache,
            ),
            cache=cache,
            registry=registry,
            radar_product_id=os.environ.get(
                "SCOUT_CWA_RADAR_PRODUCT_ID",
                "radar.integrated.taiwan.transparent",
            ),
            satellite_product_id=os.environ.get(
                "SCOUT_CWA_SATELLITE_PRODUCT_ID",
                "satellite.enhanced_color.taiwan",
            ),
            evaluated_at=prepared_at,
            allow_network_fetch=True,
            processing_profile=request.profile,
            route_buffer_m=request.route_corridor_m,
            server_capability_attested=(
                os.environ.get("SCOUT_CWA_SERVER_IMAGERY_CAPABLE") == "1"
            ),
        )
        return {**refs, "cwa_weather_imagery_status": "ready"}
    except Exception as exc:  # pragma: no cover - live provider/server worker path.
        return {
            "cwa_weather_imagery_status": "fetch_or_processing_failed",
            "cwa_weather_imagery_error": _safe_exception_summary(exc),
        }


def _route_points_for_weather_imagery(
    project_root: Path,
    project: dict[str, Any],
    *,
    max_points: int = 2_000,
) -> list[tuple[float, float]]:
    try:
        _, route_points = load_cwa_route_identity(
            project_root,
            project,
            max_points=max_points,
        )
    except (OSError, ValueError):
        return []
    return route_points


def _terrain_segments_for_weather_imagery(
    project_root: Path,
    project: dict[str, Any],
) -> list[dict[str, Any]]:
    for ref_key in ("risk_score_points_ref", "risk_route_profile_ref"):
        ref = project.get(ref_key)
        if not isinstance(ref, str) or not ref:
            continue
        path = _safe_project_relative_path(project_root, ref)
        if path is None or not path.exists():
            continue
        payload = _load_json(path)
        features = payload.get("features", []) if isinstance(payload, dict) else []
        segments: list[dict[str, Any]] = []
        for index, feature in enumerate(features):
            properties = dict(feature.get("properties") or {}) if isinstance(feature, dict) else {}
            hazards = properties.get("hazard_types") or properties.get("hazardTypes") or []
            if not isinstance(hazards, list):
                hazards = []
            segments.append(
                {
                    "segmentId": properties.get("segment_id")
                    or properties.get("segmentId")
                    or f"terrain.{index:05d}",
                    "teii_20m": properties.get("teii_20m"),
                    "hazardTypes": hazards,
                    "gradePercent": properties.get("grade_percent")
                    or properties.get("gradePercent"),
                    "terrainSourceRefs": [ref],
                }
            )
        return segments
    return []


def _safe_project_relative_path(project_root: Path, ref: str) -> Path | None:
    path = (project_root / ref).resolve()
    try:
        path.relative_to(project_root.resolve())
    except ValueError:
        return None
    return path


def _prepare_gee_environment_artifacts(
    *,
    project_root: Path,
    project: dict[str, Any],
    route_summary: dict[str, Any],
    bbox: dict[str, float],
    request: LayerPreparationRequest,
    prepared_at: str,
    cwa_time_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    del route_summary
    gee_dir = project_root / "outputs" / "environment" / "gee"
    project_id = project.get("project_id") or request.project_id
    gee_project_id = (
        os.environ.get("SCOUT_GEE_PROJECT_ID")
        or os.environ.get("SCOUT_GEE_PROJECT")
        or os.environ.get("GOOGLE_CLOUD_PROJECT")
        or str(project_id)
    )
    try:
        from scout_gee_integration import (
            SMAP_L4_BANDS,
            SMAP_L4_COLLECTION_ID,
            SMAP_L4_SPATIAL_RESOLUTION_M,
            SMAP_L4_TEMPORAL_RESOLUTION,
            build_gee_runtime_status,
            fetch_gee_environment_evidence,
            gee_environment_dataset_catalog,
            gee_numeric_no_cache_policy,
            write_environment_risk_derivative_artifacts,
            write_scout_gee_feature_package,
        )

        gee_status = build_gee_runtime_status().to_dict()
        dataset_catalog = gee_environment_dataset_catalog()
        cache_policy = gee_numeric_no_cache_policy()
    except Exception as exc:  # pragma: no cover - import should be stable.
        gee_status = {
            "provider": "google_earth_engine",
            "enabled": False,
            "ready": False,
            "blocker_reasons": [f"gee_status_import_failed:{type(exc).__name__}"],
            "secret_value_embedded": False,
            "external_api_call_performed": False,
            "runtime_safety_truth": False,
        }
        dataset_catalog = []
        cache_policy = {
            "cacheable": False,
            "ttl_seconds": 0,
            "must_refetch_on_prepare": True,
            "reuse_previous_numeric_values": False,
            "artifact_role": "current_run_evidence_snapshot",
            "reason": "GEE values are time-sensitive and must be refetched.",
        }
        write_scout_gee_feature_package = None
        write_environment_risk_derivative_artifacts = None
        SMAP_L4_COLLECTION_ID = "NASA/SMAP/SPL4SMGP/008"
        SMAP_L4_TEMPORAL_RESOLUTION = "3h"
        SMAP_L4_SPATIAL_RESOLUTION_M = 11000
        SMAP_L4_BANDS = (
            "sm_surface",
            "sm_rootzone",
            "sm_profile",
            "sm_surface_wetness",
            "sm_rootzone_wetness",
            "sm_profile_wetness",
            "surface_temp",
            "sm_rootzone_pctl",
            "sm_profile_pctl",
            "sm_surface_anomaly",
        )

    fetch_result: dict[str, Any] | None = None
    external_calls_made = False
    if request.network_mode == "explicit-fetch" and request.allow_network_fetch:
        try:
            fetch_result = fetch_gee_environment_evidence(
                project_id=str(gee_project_id),
                bbox_wgs84=bbox,
                prepared_at=prepared_at,
            ).to_dict()
        except Exception as exc:  # pragma: no cover - defensive integration boundary.
            fetch_result = {
                "status": "fetch_failed",
                "blocker_reasons": [f"gee_fetch_failed:{type(exc).__name__}"],
                "external_api_calls_made": True,
                "raw_summary": {
                    "provider": "google_earth_engine",
                    "error_type": type(exc).__name__,
                    "cache_policy": cache_policy,
                    "secret_value_embedded": False,
                    "runtime_safety_truth": False,
                },
                "soil_moisture": {},
                "antecedent_rain": {},
                "smap_timeseries": {},
                "gpm_timeseries": {},
            }
        external_calls_made = bool(fetch_result.get("external_api_calls_made"))

    if fetch_result:
        status = str(fetch_result.get("status") or "fetch_failed")
        blockers = list(fetch_result.get("blocker_reasons") or [])
        soil_summary = dict(fetch_result.get("soil_moisture") or {})
        rain_summary = dict(fetch_result.get("antecedent_rain") or {})
        raw_summary = dict(fetch_result.get("raw_summary") or {})
    else:
        status = (
            "configured_pending_explicit_fetch"
            if gee_status.get("ready")
            else "missing_credentials"
        )
        blockers = list(gee_status.get("blocker_reasons") or [])
        if not blockers and status == "configured_pending_explicit_fetch":
            blockers = ["gee_fetch_requires_explicit_network"]
        soil_summary = {
            "dataset_family": "SMAP",
            "collection_id": SMAP_L4_COLLECTION_ID,
            "source_collection_id": SMAP_L4_COLLECTION_ID,
            "layer_id": "soil-moisture",
            "sm_surface": None,
            "sm_rootzone": None,
            "sm_profile": None,
            "sm_surface_wetness": None,
            "sm_rootzone_wetness": None,
            "sm_profile_wetness": None,
            "antecedent_wetness_percentile": None,
            "band_names": list(SMAP_L4_BANDS),
            "temporal_resolution": SMAP_L4_TEMPORAL_RESOLUTION,
            "spatial_resolution_m": SMAP_L4_SPATIAL_RESOLUTION_M,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "human_review_required": True,
        }
        rain_summary = {
            "dataset_family": "GPM_IMERG",
            "collection_id": "NASA/GPM_L3/IMERG_V07",
            "last_3h_mm": None,
            "last_24h_mm": None,
            "last_72h_mm": None,
        }
        raw_summary = {
            "provider": "google_earth_engine",
            "status": status,
            "blocker_reasons": blockers,
            "cache_policy": cache_policy,
            "secret_value_embedded": False,
            "runtime_safety_truth": False,
        }
    raw_summary["cache_policy"] = cache_policy
    raw_summary_bytes = json.dumps(
        raw_summary,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    raw_summary_hash = hashlib.sha256(raw_summary_bytes).hexdigest()
    raw_summary_ref = "outputs/environment/gee/gee_raw_summary.json"
    smap_route_scope = {
        "scope_kind": "route_bbox_corridor_proxy",
        "bbox_wgs84": bbox,
        "route_corridor_m": request.route_corridor_m,
        "aggregation_geometry": "bbox_wgs84",
        "corridor_geometry_available": False,
        "note": (
            "SMAP L4 is coarse 11km hydrologic background summarized for the "
            "route bbox/corridor proxy; it is candidate evidence only."
        ),
    }
    smap_source_metadata = {
        "provider": "google_earth_engine",
        "collection_id": SMAP_L4_COLLECTION_ID,
        "official_catalog_url": (
            "https://developers.google.com/earth-engine/datasets/catalog/"
            "NASA_SMAP_SPL4SMGP_008"
        ),
        "band_names": list(SMAP_L4_BANDS),
        "temporal_resolution": SMAP_L4_TEMPORAL_RESOLUTION,
        "spatial_resolution_m": SMAP_L4_SPATIAL_RESOLUTION_M,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "human_review_required": True,
    }
    soil_route_scope = {
        **smap_route_scope,
        **(
            soil_summary.get("route_scope")
            if isinstance(soil_summary.get("route_scope"), dict)
            else {}
        ),
        "bbox_wgs84": bbox,
        "route_corridor_m": request.route_corridor_m,
        "aggregation_geometry": "bbox_wgs84",
    }
    soil_summary.update(
        {
            "source_collection_id": SMAP_L4_COLLECTION_ID,
            "layer_id": "soil-moisture",
            "band_names": list(SMAP_L4_BANDS),
            "temporal_resolution": SMAP_L4_TEMPORAL_RESOLUTION,
            "spatial_resolution_m": SMAP_L4_SPATIAL_RESOLUTION_M,
            "route_scope": soil_route_scope,
            "source_metadata": soil_summary.get("source_metadata")
            or smap_source_metadata,
            "external_api_calls_made": external_calls_made,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "human_review_required": True,
        }
    )
    gpm_raw_summary_ref = OUTPUT_REFS["gee_gpm_imerg_raw_summary_ref"]
    gpm_raw_summary = _gee_gpm_imerg_raw_summary(
        raw_summary=raw_summary,
        project_id=str(project_id),
        generated_at=prepared_at,
        status=status,
        blockers=blockers,
        external_calls_made=external_calls_made,
        cache_policy=cache_policy,
        raw_summary_ref=raw_summary_ref,
        raw_summary_sha256=raw_summary_hash,
    )
    gpm_raw_summary_hash = _stable_projection_hash(gpm_raw_summary)

    soil_feature = _environment_status_feature(
        bbox=bbox,
        layer_id="soil-moisture",
        label="SMAP soil moisture",
        status=status,
        provider="google_earth_engine",
        source_run_id=f"gee.{project_id}.{_job_timestamp(prepared_at)}",
        prepared_at=prepared_at,
        detail=(
            "SMAP/GEE coarse route bbox/corridor hydrologic background evidence."
            if status == "fetched"
            else "SMAP/GEE source status; numeric soil moisture requires configured GEE credentials and explicit fetch."
        ),
        extra={
            **soil_summary,
            "gee_status": gee_status,
            "blocker_reasons": blockers,
            "raw_summary_ref": raw_summary_ref,
            "raw_summary_sha256": raw_summary_hash,
            "raw_response_hash": f"sha256:{raw_summary_hash}",
            "normalized_artifact_ref": OUTPUT_REFS["soil_moisture_grid_ref"],
            "cache_policy": cache_policy,
            "external_api_calls_made": external_calls_made,
            "source_collection_id": SMAP_L4_COLLECTION_ID,
            "collection_id": SMAP_L4_COLLECTION_ID,
            "route_scope": soil_route_scope,
            "source_metadata": smap_source_metadata,
            "human_review_required": True,
        },
    )
    rain_feature = _environment_status_feature(
        bbox=bbox,
        layer_id="antecedent-rain",
        label="GPM antecedent rain",
        status=status,
        provider="google_earth_engine",
        source_run_id=f"gee.{project_id}.{_job_timestamp(prepared_at)}",
        prepared_at=prepared_at,
        detail=(
            "GPM IMERG/GEE bbox-reduced antecedent rain evidence."
            if status == "fetched"
            else "GPM IMERG/GEE source status; numeric antecedent rain requires configured GEE credentials and explicit fetch."
        ),
        extra={
            **rain_summary,
            "gee_status": gee_status,
            "blocker_reasons": blockers,
            "raw_summary_ref": raw_summary_ref,
            "raw_summary_sha256": raw_summary_hash,
            "cache_policy": cache_policy,
            "external_api_calls_made": external_calls_made,
        },
    )
    soil_geojson = _feature_collection(
        "gee_soil_moisture_grid",
        [soil_feature],
        project_id=project_id,
        generated_at=prepared_at,
        bbox=bbox,
        external_calls_made=external_calls_made,
    )
    soil_geojson["cache_policy"] = cache_policy
    soil_geojson.update(
        {
            "layer_id": "soil-moisture",
            "collection_id": SMAP_L4_COLLECTION_ID,
            "source_collection_id": SMAP_L4_COLLECTION_ID,
            "band_names": list(SMAP_L4_BANDS),
            "temporal_resolution": SMAP_L4_TEMPORAL_RESOLUTION,
            "spatial_resolution_m": SMAP_L4_SPATIAL_RESOLUTION_M,
            "route_scope": soil_route_scope,
            "source_metadata": smap_source_metadata,
            "raw_summary_ref": raw_summary_ref,
            "raw_summary_sha256": raw_summary_hash,
            "raw_response_hash": f"sha256:{raw_summary_hash}",
            "normalized_artifact_ref": OUTPUT_REFS["soil_moisture_grid_ref"],
            "candidate_only": True,
            "runtime_safety_truth": False,
            "human_review_required": True,
            "external_api_calls_made": external_calls_made,
        }
    )
    rain_geojson = _feature_collection(
        "gee_antecedent_rain_grid",
        [rain_feature],
        project_id=project_id,
        generated_at=prepared_at,
        bbox=bbox,
        external_calls_made=external_calls_made,
    )
    rain_geojson["cache_policy"] = cache_policy
    smap_summary = _gee_environment_summary(
        project_id=project_id,
        layer_id="soil-moisture",
        generated_at=prepared_at,
        bbox=bbox,
        gee_status=gee_status,
        dataset_catalog=dataset_catalog,
        status=status,
        blockers=blockers,
        external_calls_made=external_calls_made,
        raw_summary_ref=raw_summary_ref,
        raw_summary_sha256=raw_summary_hash,
        cache_policy=cache_policy,
        values=soil_summary,
    )
    gpm_summary = _gee_environment_summary(
        project_id=project_id,
        layer_id="antecedent-rain",
        generated_at=prepared_at,
        bbox=bbox,
        gee_status=gee_status,
        dataset_catalog=dataset_catalog,
        status=status,
        blockers=blockers,
        external_calls_made=external_calls_made,
        raw_summary_ref=raw_summary_ref,
        raw_summary_sha256=raw_summary_hash,
        cache_policy=cache_policy,
        values=rain_summary,
    )

    smap_timeseries = (
        fetch_result.get("smap_timeseries")
        if fetch_result and fetch_result.get("smap_timeseries")
        else _gee_timeseries_placeholder(
            project_id=project_id,
            layer_id="soil-moisture",
            generated_at=prepared_at,
            status=status,
            blockers=blockers,
            cache_policy=cache_policy,
            external_calls_made=external_calls_made,
        )
    )
    if isinstance(smap_timeseries, dict):
        smap_timeseries["cache_policy"] = cache_policy
        smap_timeseries.setdefault("collection_id", SMAP_L4_COLLECTION_ID)
        smap_timeseries.setdefault("source_collection_id", SMAP_L4_COLLECTION_ID)
        smap_timeseries.setdefault("band_names", list(SMAP_L4_BANDS))
        smap_timeseries.setdefault("temporal_resolution", SMAP_L4_TEMPORAL_RESOLUTION)
        smap_timeseries.setdefault("spatial_resolution_m", SMAP_L4_SPATIAL_RESOLUTION_M)
        smap_timeseries.setdefault("source_metadata", smap_source_metadata)
        smap_timeseries["route_scope"] = {
            **soil_route_scope,
            **(
                smap_timeseries.get("route_scope")
                if isinstance(smap_timeseries.get("route_scope"), dict)
                else {}
            ),
            "bbox_wgs84": bbox,
            "route_corridor_m": request.route_corridor_m,
        }
        smap_timeseries["external_api_calls_made"] = external_calls_made
        smap_timeseries["candidate_only"] = True
        smap_timeseries["runtime_safety_truth"] = False
        smap_timeseries["human_review_required"] = True
    gpm_timeseries = (
        fetch_result.get("gpm_timeseries")
        if fetch_result and fetch_result.get("gpm_timeseries")
        else _gee_timeseries_placeholder(
            project_id=project_id,
            layer_id="antecedent-rain",
            generated_at=prepared_at,
            status=status,
            blockers=blockers,
            cache_policy=cache_policy,
            external_calls_made=external_calls_made,
        )
    )
    if isinstance(gpm_timeseries, dict):
        gpm_timeseries["cache_policy"] = cache_policy

    _write_json(gee_dir / "gee_raw_summary.json", raw_summary)
    _write_json(gee_dir / "gpm_imerg_raw_summary.json", gpm_raw_summary)
    _write_json(gee_dir / "soil_moisture_grid.geojson", soil_geojson)
    _write_json(gee_dir / "antecedent_rain_grid.geojson", rain_geojson)
    _write_json(gee_dir / "smap_l4_corridor_summary.json", smap_summary)
    _write_json(gee_dir / "gpm_imerg_corridor_summary.json", gpm_summary)
    _write_json(gee_dir / "smap_l4_timeseries.json", smap_timeseries)
    _write_json(gee_dir / "gpm_imerg_timeseries.json", gpm_timeseries)

    feature_package_path = gee_dir / "scout_gee_feature_package.json"
    feature_package_status = "not_written"
    feature_package_segment_count = 0
    feature_package_for_derivatives: dict[str, Any] | None = None
    if write_scout_gee_feature_package is None:
        feature_package_for_derivatives = _blocked_gee_feature_package(
            project_id=str(project_id),
            prepared_at=prepared_at,
            status="gee_import_failed",
            blockers=["gee_feature_package_writer_unavailable"],
        )
        _write_json(feature_package_path, feature_package_for_derivatives)
        feature_package_status = "gee_import_failed"
    else:
        route_gpx_path = _reference_gpx_path_for_risk_generation(
            project_root=project_root,
            project=project,
        )
        risk_path = _project_ref_path(project_root, project, "risk_route_profile_ref")
        if route_gpx_path is None:
            feature_package_for_derivatives = _blocked_gee_feature_package(
                project_id=str(project_id),
                prepared_at=prepared_at,
                status="missing_route_gpx",
                blockers=["route_gpx_ref_missing"],
            )
            _write_json(feature_package_path, feature_package_for_derivatives)
            feature_package_status = "missing_route_gpx"
        else:
            try:
                feature_package = write_scout_gee_feature_package(
                    gpx_path=route_gpx_path,
                    output_path=feature_package_path,
                    project_id=str(project_id),
                    prepared_at=prepared_at,
                    buffer_m=float(request.route_corridor_m),
                    route_risk_geojson_path=risk_path,
                    allow_live_fetch=(
                        request.network_mode == "explicit-fetch"
                        and request.allow_network_fetch
                    ),
                )
                feature_package_status = str(feature_package.get("status") or "ready")
                feature_package_segment_count = int(
                    feature_package.get("counts", {}).get("segment_count") or 0
                )
                feature_package_for_derivatives = feature_package
            except Exception as exc:  # pragma: no cover - defensive package boundary.
                feature_package_for_derivatives = _blocked_gee_feature_package(
                    project_id=str(project_id),
                    prepared_at=prepared_at,
                    status="feature_package_failed",
                    blockers=[f"gee_feature_package_failed:{type(exc).__name__}"],
                )
                _write_json(feature_package_path, feature_package_for_derivatives)
                feature_package_status = "feature_package_failed"

    derivatives_summary: dict[str, Any] = {
        "status": "not_written",
        "counts": {},
        "headline": "",
    }
    if (
        write_environment_risk_derivative_artifacts is not None
        and isinstance(feature_package_for_derivatives, dict)
    ):
        try:
            derivative_cwa_time_metadata = _project_cwa_time_metadata(
                project_root=project_root,
                project=project,
                fallback=cwa_time_metadata,
            )
            derivatives_summary = write_environment_risk_derivative_artifacts(
                feature_package=feature_package_for_derivatives,
                output_dir=project_root / "outputs" / "environment" / "derived",
                project_id=str(project_id),
                generated_at=prepared_at,
                cwa_time_metadata=derivative_cwa_time_metadata,
            )
        except Exception as exc:  # pragma: no cover - defensive derivative boundary.
            derivatives_summary = {
                "artifact_kind": "scout_environment_risk_derivatives",
                "schema_version": "scout_environment_risk_derivatives.v0.1",
                "project_id": str(project_id),
                "generated_at": prepared_at,
                "status": "derivative_failed",
                "blocker_reasons": [
                    f"environment_risk_derivatives_failed:{type(exc).__name__}"
                ],
                "counts": {},
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
            _write_json(
                project_root
                / OUTPUT_REFS["environment_risk_derivatives_ref"],
                derivatives_summary,
            )

    return {
        "soil_moisture_grid_ref": OUTPUT_REFS["soil_moisture_grid_ref"],
        "smap_l4_timeseries_ref": OUTPUT_REFS["smap_l4_timeseries_ref"],
        "smap_l4_corridor_summary_ref": OUTPUT_REFS[
            "smap_l4_corridor_summary_ref"
        ],
        "antecedent_rain_grid_ref": OUTPUT_REFS["antecedent_rain_grid_ref"],
        "gpm_imerg_timeseries_ref": OUTPUT_REFS["gpm_imerg_timeseries_ref"],
        "gpm_imerg_corridor_summary_ref": OUTPUT_REFS[
            "gpm_imerg_corridor_summary_ref"
        ],
        "soil_moisture_feature_count": 1,
        "antecedent_rain_feature_count": 1,
        "gee_environment_status": status,
        "gee_external_api_calls_made": external_calls_made,
        "gee_numeric_cacheable": False,
        "gee_numeric_ttl_seconds": 0,
        "gee_cache_policy": cache_policy,
        "gee_raw_summary_ref": raw_summary_ref,
        "gee_raw_summary_sha256": raw_summary_hash,
        "gee_gpm_imerg_raw_summary_ref": gpm_raw_summary_ref,
        "gee_gpm_imerg_raw_summary_sha256": gpm_raw_summary_hash,
        "gee_feature_package_ref": OUTPUT_REFS["gee_feature_package_ref"],
        "gee_feature_package_status": feature_package_status,
        "gee_feature_package_segment_count": feature_package_segment_count,
        "environment_risk_derivatives_ref": OUTPUT_REFS[
            "environment_risk_derivatives_ref"
        ],
        "new_landslide_candidates_ref": OUTPUT_REFS[
            "new_landslide_candidates_ref"
        ],
        "wetness_flash_flood_susceptibility_ref": OUTPUT_REFS[
            "wetness_flash_flood_susceptibility_ref"
        ],
        "trail_obscurity_risk_ref": OUTPUT_REFS["trail_obscurity_risk_ref"],
        "practical_darkness_time_ref": OUTPUT_REFS["practical_darkness_time_ref"],
        "route_revalidation_report_ref": OUTPUT_REFS[
            "route_revalidation_report_ref"
        ],
        "environment_risk_derivative_status": derivatives_summary.get("status"),
        "environment_risk_derivative_counts": derivatives_summary.get("counts", {}),
        "environment_risk_derivative_headline": derivatives_summary.get("headline", ""),
    }


def _write_environment_synthesis_artifacts(
    *,
    project_root: Path,
    project: dict[str, Any],
    route_summary: dict[str, Any],
    bbox: dict[str, float],
    prepared_at: str,
    requested_cwa: bool,
    requested_gee: bool,
) -> dict[str, Any]:
    env_dir = project_root / "outputs" / "environment"
    env_dir.mkdir(parents=True, exist_ok=True)
    source_refs = _environment_source_refs(project_root, project)
    cwa_qpf = _load_project_ref_if_exists(
        project_root,
        project,
        "cwa_qpf_corridor_summary_ref",
    )
    cwa_weather = _load_project_ref_if_exists(
        project_root,
        project,
        "cwa_weather_evidence_ref",
    )
    smap = _load_project_ref_if_exists(
        project_root,
        project,
        "smap_l4_corridor_summary_ref",
    )
    gpm = _load_project_ref_if_exists(
        project_root,
        project,
        "gpm_imerg_corridor_summary_ref",
    )
    cwa_time = (
        cwa_weather.get("temporal_coverage")
        if isinstance(cwa_weather.get("temporal_coverage"), dict)
        else cwa_qpf
    )
    if not isinstance(cwa_time, dict):
        cwa_time = {}
    missing_evidence = _environment_missing_evidence(
        requested_cwa=requested_cwa,
        requested_gee=requested_gee,
        project=project,
        cwa_qpf=cwa_qpf,
        cwa_weather=cwa_weather,
        smap=smap,
        gpm=gpm,
    )
    package = {
        "artifact_kind": "environment_evidence_package",
        "schema_version": "scout_environment_evidence_package.v0",
        "project_id": project.get("project_id"),
        "route_name": route_summary.get("route_name"),
        "generated_at": prepared_at,
        "request_timestamp": prepared_at,
        "generated_at_hour": _iso_hour(prepared_at),
        "time_precision": "hour",
        "timezone": "UTC",
        "cwa_time_metadata": cwa_time,
        "bbox_wgs84": bbox,
        "status": "ready_with_data_gaps" if missing_evidence else "ready",
        "candidate_only": True,
        "runtime_safety_truth": False,
        "human_review_required": True,
        "source_refs": source_refs,
        "missing_evidence": missing_evidence,
        "temporal_coverage": {
            "cwa": cwa_time,
            "gee": {
                "request_timestamp": prepared_at,
                "request_timestamp_hour": _iso_hour(prepared_at),
                "api_fetched_at": prepared_at
                if project.get("gee_external_api_calls_made")
                else None,
                "api_fetched_at_hour": _iso_hour(prepared_at)
                if project.get("gee_external_api_calls_made")
                else None,
                "time_precision": "hour",
                "timezone": "UTC",
            },
        },
        "provider_status": {
            "cwa_external_api_calls_made": bool(
                project.get("cwa_external_api_calls_made")
            ),
            "gee_external_api_calls_made": bool(
                project.get("gee_external_api_calls_made")
            ),
            "gee_environment_status": project.get("gee_environment_status"),
        },
        "boundary": _environment_boundary(
            external_calls_made=bool(
                project.get("cwa_external_api_calls_made")
                or project.get("gee_external_api_calls_made")
            )
        ),
    }
    factor_matrix = _environment_factor_matrix(
        project=project,
        route_summary=route_summary,
        generated_at=prepared_at,
        cwa_qpf=cwa_qpf,
        cwa_weather=cwa_weather,
        smap=smap,
        gpm=gpm,
        missing_evidence=missing_evidence,
    )
    go_no_go = _environment_go_no_go_review_draft(
        project=project,
        route_summary=route_summary,
        generated_at=prepared_at,
        source_refs=source_refs,
        factor_matrix=factor_matrix,
        missing_evidence=missing_evidence,
    )
    _write_json(env_dir / "environment_evidence_package.json", package)
    _write_json(env_dir / "environment_factor_matrix.json", factor_matrix)
    _write_json(env_dir / "go_no_go_review_draft.json", go_no_go)
    return {
        "environment_evidence_package_ref": OUTPUT_REFS[
            "environment_evidence_package_ref"
        ],
        "environment_factor_matrix_ref": OUTPUT_REFS["environment_factor_matrix_ref"],
        "go_no_go_review_draft_ref": OUTPUT_REFS["go_no_go_review_draft_ref"],
    }


def _environment_source_refs(project_root: Path, project: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for key in (
        "cwa_weather_evidence_ref",
        "cwa_warnings_geojson_ref",
        "cwa_observations_geojson_ref",
        "cwa_qpf_grid_ref",
        "cwa_qpf_route_timeline_ref",
        "cwa_qpf_corridor_summary_ref",
        "cwa_forecast_timeline_ref",
        "cwa_astronomy_timeline_ref",
        "cwa_tide_marine_timeline_ref",
        "soil_moisture_grid_ref",
        "smap_l4_timeseries_ref",
        "smap_l4_corridor_summary_ref",
        "antecedent_rain_grid_ref",
        "gee_gpm_imerg_raw_summary_ref",
        "gpm_imerg_timeseries_ref",
        "gpm_imerg_corridor_summary_ref",
    ):
        value = project.get(key)
        if isinstance(value, str) and value and (project_root / value).exists():
            refs.append(value)
    return refs


def _load_project_ref_if_exists(
    project_root: Path,
    project: dict[str, Any],
    ref_key: str,
) -> dict[str, Any]:
    value = project.get(ref_key)
    if not isinstance(value, str) or not value:
        return {}
    path = project_root / value
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = _load_json(path)
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _environment_missing_evidence(
    *,
    requested_cwa: bool,
    requested_gee: bool,
    project: dict[str, Any],
    cwa_qpf: dict[str, Any],
    cwa_weather: dict[str, Any],
    smap: dict[str, Any],
    gpm: dict[str, Any],
) -> list[dict[str, Any]]:
    missing: list[dict[str, Any]] = []
    if requested_cwa and not cwa_weather:
        missing.append({"source_kind": "cwa_weather_evidence", "reason": "missing"})
    if requested_cwa and not cwa_qpf:
        missing.append({"source_kind": "cwa_qpf_corridor_summary", "reason": "missing"})
    if requested_cwa and not project.get("cwa_external_api_calls_made"):
        missing.append(
            {
                "source_kind": "cwa_live_fetch",
                "reason": "not_fetched_in_current_run",
            }
        )
    if requested_gee and not smap:
        missing.append({"source_kind": "gee_smap_l4_corridor_summary", "reason": "missing"})
    if requested_gee and not gpm:
        missing.append({"source_kind": "gee_gpm_imerg_corridor_summary", "reason": "missing"})
    if requested_gee and project.get("gee_environment_status") != "fetched":
        missing.append(
            {
                "source_kind": "gee_live_fetch",
                "reason": str(project.get("gee_environment_status") or "not_fetched"),
            }
        )
    return missing


def _environment_factor_matrix(
    *,
    project: dict[str, Any],
    route_summary: dict[str, Any],
    generated_at: str,
    cwa_qpf: dict[str, Any],
    cwa_weather: dict[str, Any],
    smap: dict[str, Any],
    gpm: dict[str, Any],
    missing_evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    smap_values = smap.get("values") if isinstance(smap.get("values"), dict) else {}
    gpm_values = gpm.get("values") if isinstance(gpm.get("values"), dict) else {}
    cwa_time = (
        cwa_weather.get("temporal_coverage")
        if isinstance(cwa_weather.get("temporal_coverage"), dict)
        else cwa_qpf
    )
    if not isinstance(cwa_time, dict):
        cwa_time = {}
    return {
        "artifact_kind": "environment_factor_matrix",
        "schema_version": "scout_environment_factor_matrix.v0",
        "project_id": project.get("project_id"),
        "route_name": route_summary.get("route_name"),
        "generated_at": generated_at,
        "generated_at_hour": _iso_hour(generated_at),
        "time_precision": "hour",
        "timezone": "UTC",
        "cwa_time_metadata": cwa_time,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "official_warning": {
            "warning_count": project.get("cwa_warning_count", 0),
            "source_ref": project.get("cwa_warnings_geojson_ref"),
            "api_fetched_at_hour": cwa_time.get("api_fetched_at_hour"),
        },
        "rain_observed": {
            "max_24h_mm": cwa_qpf.get("max_observed_24h_mm"),
            "mean_24h_mm": cwa_qpf.get("mean_observed_24h_mm"),
            "latest_observation_at_hour": cwa_time.get("latest_observation_at_hour"),
            "source_ref": project.get("cwa_observations_geojson_ref"),
        },
        "rain_forecast": {
            "max_rain_probability": cwa_qpf.get("max_rain_probability"),
            "qpf_feature_count": project.get("cwa_qpf_feature_count", 0),
            "forecast_valid_from_hour": cwa_time.get("forecast_valid_from_hour"),
            "forecast_valid_until_hour": cwa_time.get("forecast_valid_until_hour"),
            "source_ref": project.get("cwa_qpf_corridor_summary_ref"),
        },
        "qpf_accumulation": "forecast-derived route-area QPF candidates",
        "qpf_peak_window": _qpf_peak_window_from_cwa_time(cwa_time),
        "qpf_update_cadence": "current_run_cwa_fetch",
        "qpf_lead_time": "derived_from_cwa_forecast_valid_window",
        "qpf_uncertainty": "mountain_orographic_and_convective_uncertainty",
        "severe_weather_intensified_operation": False,
        "antecedent_wetness": {
            "sm_surface_wetness": smap_values.get("sm_surface_wetness"),
            "sm_rootzone_wetness": smap_values.get("sm_rootzone_wetness"),
            "source_ref": project.get("smap_l4_corridor_summary_ref"),
        },
        "antecedent_rain": {
            "last_3h_mm": gpm_values.get("last_3h_mm"),
            "last_24h_mm": gpm_values.get("last_24h_mm"),
            "last_72h_mm": gpm_values.get("last_72h_mm"),
            "source_ref": project.get("gpm_imerg_corridor_summary_ref"),
        },
        "satellite_precipitation": {
            "gee_environment_status": project.get("gee_environment_status"),
            "api_fetched_at_hour": _iso_hour(generated_at)
            if project.get("gee_external_api_calls_made")
            else None,
        },
        "missing_evidence": missing_evidence,
    }


def _qpf_peak_window_from_cwa_time(cwa_time: dict[str, Any]) -> str | None:
    start = cwa_time.get("forecast_valid_from_hour") or cwa_time.get("valid_from_hour")
    end = cwa_time.get("forecast_valid_until_hour") or cwa_time.get("valid_until_hour")
    if start and end:
        return f"{start}/{end}"
    return None


def _environment_go_no_go_review_draft(
    *,
    project: dict[str, Any],
    route_summary: dict[str, Any],
    generated_at: str,
    source_refs: list[str],
    factor_matrix: dict[str, Any],
    missing_evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    warning_candidates: list[dict[str, Any]] = []
    if project.get("cwa_warning_count", 0):
        warning_candidates.append(
            {
                "category": "official_warning",
                "label": "CWA warning evidence requires human review",
                "source_ref": project.get("cwa_warnings_geojson_ref"),
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )
    max_pop = (
        factor_matrix.get("rain_forecast", {}).get("max_rain_probability")
        if isinstance(factor_matrix.get("rain_forecast"), dict)
        else None
    )
    if isinstance(max_pop, (int, float)) and max_pop >= 70:
        warning_candidates.append(
            {
                "category": "qpf_review",
                "label": "CWA forecast rain probability is elevated",
                "value": max_pop,
                "valid_from_hour": factor_matrix["rain_forecast"].get(
                    "forecast_valid_from_hour"
                ),
                "valid_until_hour": factor_matrix["rain_forecast"].get(
                    "forecast_valid_until_hour"
                ),
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )
    return {
        "artifact_kind": "go_no_go_review_draft",
        "schema_version": "scout_go_no_go_review_draft.v0",
        "project_id": project.get("project_id"),
        "route_name": route_summary.get("route_name"),
        "generated_at": generated_at,
        "generated_at_hour": _iso_hour(generated_at),
        "time_precision": "hour",
        "timezone": "UTC",
        "cwa_time_metadata": factor_matrix.get("cwa_time_metadata", {}),
        "review_window": {
            "planned_start": None,
            "planned_end": None,
            "time_precision": "hour",
        },
        "decision_state": "hold" if missing_evidence else "needs_human_review",
        "data_freshness_summary": {
            "cwa_api_request_attempted_at_hour": project.get(
                "cwa_api_request_attempted_at_hour"
            ),
            "cwa_api_fetched_at_hour": project.get("cwa_fetched_at_hour"),
            "cwa_valid_from_hour": project.get("cwa_valid_from_hour"),
            "cwa_valid_until_hour": project.get("cwa_valid_until_hour"),
            "gee_api_fetched_at_hour": _iso_hour(generated_at)
            if project.get("gee_external_api_calls_made")
            else None,
            "time_precision": "hour",
        },
        "blocker_candidates": [
            {
                "category": "missing_environment_evidence",
                "label": item["source_kind"],
                "reason": item["reason"],
                "candidate_only": True,
                "runtime_safety_truth": False,
                "human_review_required": True,
            }
            for item in missing_evidence
        ],
        "warning_candidates": warning_candidates,
        "missing_evidence": missing_evidence,
        "evidence_source_refs": source_refs,
        "operator_decision": None,
        "operator_decision_at": None,
        "human_review_required": True,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "boundary": _environment_boundary(
            external_calls_made=bool(
                project.get("cwa_external_api_calls_made")
                or project.get("gee_external_api_calls_made")
            )
        ),
    }


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
            route_corridor_m=request.route_corridor_m,
        )
        project = _sync_calibrated_risk_outputs(
            project_root=project_root,
            project=project,
        )
    if workspace_file_mutation_allowed and "overpass" in normalized_layers:
        _stamp_overpass_evidence_provenance(project_root=project_root, project=project)
    overpass_route_alignment: dict[str, Any] | None = None
    alignment_outputs: dict[str, Any] = {}
    if workspace_file_mutation_allowed and set(normalized_layers) & {
        "overpass",
        "risk-ribbon",
        "risk-score",
    }:
        overpass_route_alignment = _run_overpass_route_alignment_after_layer_preparation(
            project_root=project_root,
            manifest={
                "normalized_layers": normalized_layers,
                "finished_at": prepared_at,
            },
        )
        if overpass_route_alignment.get("status") == "completed":
            alignment_outputs.update(
                overpass_route_alignment.get("output_refs", {})
            )
            alignment_outputs["overpass_route_alignment_snapped_point_count"] = (
                overpass_route_alignment.get("counts", {}).get(
                    "snapped_point_count", 0
                )
            )
            alignment_outputs["overpass_route_alignment_kept_gpx_point_count"] = (
                overpass_route_alignment.get("counts", {}).get(
                    "kept_gpx_point_count", 0
                )
            )
            _update_project_refs(
                project_path,
                project,
                alignment_outputs,
                prepared_at,
            )
            project = _load_json(project_path)
    environment_layers_requested = bool(
        {"cwa-weather", "cwa-qpf", "soil-moisture", "antecedent-rain"}
        & set(normalized_layers)
    )
    if workspace_file_mutation_allowed and environment_layers_requested:
        _write_json(project_root / "project.json", project)
        _maybe_prepare_environment_evidence(request)
        project = _load_json(project_root / "project.json")
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
    network_calls_made = bool(
        project.get("overpass_fetched_at")
        or project.get("cwa_external_api_calls_made")
        or project.get("gee_external_api_calls_made")
    )
    boundary = _boundary(
        request,
        workspace_file_mutation_allowed=workspace_file_mutation_allowed,
        external_api_calls_made=network_calls_made,
    )
    network_policy = _network_policy(request, network_calls_made=network_calls_made)
    stage_statuses = _stage_statuses(layers)
    outputs = {
        **OUTPUT_REFS,
        **_project_state_output_refs(project),
        **alignment_outputs,
    }

    manifest = {
        "artifact_kind": "pretrip_layer_preparation_manifest",
        "schema_version": LAYER_PREPARATION_VERSION,
        "job_id": job_id,
        "project_id": request.project_id,
        "profile": request.profile,
        "network_mode": request.network_mode,
        "run_post_layer_enrichments": request.run_post_layer_enrichments,
        "run_map_preparation_spec_artifacts": (
            request.run_map_preparation_spec_artifacts
        ),
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
        "overpass_route_alignment": overpass_route_alignment,
        "boundary": boundary,
        "notes": [
            (
                "LayerPreparationJob（圖層準備工作）writes pretrip workspace "
                "artifacts only."
            ),
            (
                "Connected preparation fetches Overpass vector evidence only "
                "when explicit-fetch and allow-network-fetch are both set; OSM "
                "raster tiles remain optional visual basemap support."
                if request.network_mode == "explicit-fetch"
                else "No live network calls are made in no-network preparation."
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
        help="Comma-separated layer ids, for example osm,overpass,terrain,weather.",
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
        "--prepare-cwa-imagery",
        action="store_true",
        help=(
            "Run the one-shot server-side CWA radar/satellite worker. Requires "
            "--profile mac-workstation, explicit-fetch, and --allow-network-fetch."
        ),
    )
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
    parser.add_argument(
        "--imagery-min-zoom",
        type=int,
        default=DEFAULT_IMAGERY_TILE_CACHE_MIN_ZOOM,
        help="Minimum zoom when explicit imagery tile cache seeding is enabled.",
    )
    parser.add_argument(
        "--imagery-max-zoom",
        type=int,
        default=DEFAULT_IMAGERY_TILE_CACHE_MAX_ZOOM,
        help="Maximum zoom when explicit imagery tile cache seeding is enabled.",
    )
    parser.add_argument(
        "--seed-imagery-cache",
        action="store_true",
        help=(
            "Seed imagery tiles for map-preparation OCR. Requires explicit-fetch "
            "network mode and --imagery-provider-allows-offline-prefetch."
        ),
    )
    parser.add_argument(
        "--imagery-provider-allows-offline-prefetch",
        action="store_true",
        help=(
            "Confirm the selected imagery provider allows offline prefetch for this workspace."
        ),
    )
    parser.add_argument(
        "--imagery-seed-max-tiles",
        type=int,
        help="Optional tile limit for explicit imagery seeding.",
    )
    parser.add_argument(
        "--imagery-cache-fallback-project-id",
        action="append",
        default=[],
        help=(
            "Optional project namespace to reuse fresh raw imagery tiles from "
            "before remote fetching. May be supplied more than once."
        ),
    )
    parser.add_argument(
        "--osm-pbf-path",
        type=Path,
        help=(
            "Optional local .osm.pbf source. When supplied, Scout extracts the "
            "route corridor locally with osmium and writes Overpass-compatible "
            "OSM vector evidence without live network access."
        ),
    )
    parser.add_argument(
        "--osm-pbf-source-url",
        help=(
            "Original download URL for --osm-pbf-path, preserved in provenance "
            "metadata. Example: http://download.geofabrik.de/asia/taiwan-latest.osm.pbf"
        ),
    )
    parser.add_argument(
        "--osm-pbf-cache-ttl-days",
        type=int,
        default=DEFAULT_OSM_PBF_CACHE_TTL_DAYS,
        help=(
            "Reuse a local --osm-pbf-path snapshot for this many days before "
            "marking it refresh_required. Default: 30."
        ),
    )
    parser.add_argument(
        "--osmium-bin",
        default="osmium",
        help="osmium CLI binary used with --osm-pbf-path.",
    )
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
        prepare_cwa_imagery=args.prepare_cwa_imagery,
        bbox=bbox,
        route_evidence_bundle=args.route_evidence_bundle,
        route_corridor_m=args.route_corridor_m,
        reference_track_corridor_m=args.reference_track_corridor_m,
        ai_mode=args.ai_mode,
        ai_output_policy=args.ai_output_policy,
        imagery_min_zoom=args.imagery_min_zoom,
        imagery_max_zoom=args.imagery_max_zoom,
        seed_imagery_cache=args.seed_imagery_cache,
        imagery_provider_allows_offline_prefetch=(
            args.imagery_provider_allows_offline_prefetch
        ),
        imagery_seed_max_tiles=args.imagery_seed_max_tiles,
        imagery_cache_fallback_project_ids=tuple(
            item
            for item in args.imagery_cache_fallback_project_id
            if str(item).strip()
        ),
        osm_pbf_path=args.osm_pbf_path,
        osm_pbf_source_url=args.osm_pbf_source_url,
        osm_pbf_cache_ttl_days=args.osm_pbf_cache_ttl_days,
        osmium_bin=args.osmium_bin,
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
        return _osm_layer_record(
            common,
            bbox,
            request,
            project_root=project_root,
            project=project,
        )
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
            output_refs={
                "terrain_route_samples_ref": OUTPUT_REFS["terrain_route_samples_ref"],
                "terrain_visualization_ref": OUTPUT_REFS["terrain_visualization_ref"],
                "terrain_visualization_modes": list(TERRAIN_VISUALIZATION_MODES),
                "slope_class_breaks": list(TERRAIN_SLOPE_CLASSES),
                "contour_interval_m": TERRAIN_CONTOUR_INTERVAL_M,
            },
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
            request=request,
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
    if layer_id == "cwa-weather":
        record = _multi_project_ref_layer_record(
            common,
            project_root=project_root,
            project=project,
            ref_keys=(
                "cwa_weather_evidence_ref",
                "route_weather_package_ref",
                "weather_source_manifest_ref",
                "weather_decision_candidates_ref",
            ),
            counts_from_payload=lambda payload: _environment_evidence_counts(
                "cwa_weather",
                payload,
            ),
            stale_risk="medium",
            output_refs={
                "cwa_weather_evidence_ref": OUTPUT_REFS["cwa_weather_evidence_ref"],
                "cwa_warnings_geojson_ref": OUTPUT_REFS["cwa_warnings_geojson_ref"],
                "cwa_observations_geojson_ref": OUTPUT_REFS[
                    "cwa_observations_geojson_ref"
                ],
                "route_weather_package_ref": project.get("route_weather_package_ref", ""),
                "weather_source_manifest_ref": project.get("weather_source_manifest_ref", ""),
                "weather_decision_candidates_ref": project.get(
                    "weather_decision_candidates_ref",
                    "",
                ),
                "server_side_api_key_env": "SCOUT_CWA_API_KEY",
                "client_api_key_allowed": False,
            },
            missing_warning=(
                "CWA weather artifacts are missing; run weather-decision collection "
                "or explicit CWA map preparation before enabling this layer."
            ),
        )
        return _with_environment_fetch_lifecycle(record, project=project)
    if layer_id == "cwa-qpf":
        record = _multi_project_ref_layer_record(
            common,
            project_root=project_root,
            project=project,
            ref_keys=(
                "cwa_qpf_grid_ref",
                "qpf_grid_ref",
                "cwa_qpf_route_timeline_ref",
                "qpf_route_timeline_ref",
                "cwa_qpf_corridor_summary_ref",
                "qpf_corridor_summary_ref",
            ),
            counts_from_payload=lambda payload: _environment_evidence_counts(
                "cwa_qpf",
                payload,
            ),
            stale_risk="medium",
            output_refs={
                "cwa_qpf_grid_ref": OUTPUT_REFS["cwa_qpf_grid_ref"],
                "cwa_qpf_route_timeline_ref": OUTPUT_REFS[
                    "cwa_qpf_route_timeline_ref"
                ],
                "cwa_qpf_corridor_summary_ref": OUTPUT_REFS[
                    "cwa_qpf_corridor_summary_ref"
                ],
                "server_side_api_key_env": "SCOUT_CWA_API_KEY",
                "client_api_key_allowed": False,
            },
            missing_warning=(
                "CWA QPF grid/timeline artifacts are missing; run explicit CWA QPF "
                "preparation before enabling this layer."
            ),
        )
        return _with_environment_fetch_lifecycle(record, project=project)
    if layer_id == "soil-moisture":
        return _multi_project_ref_layer_record(
            common,
            project_root=project_root,
            project=project,
            ref_keys=(
                "soil_moisture_grid_ref",
                "smap_soil_moisture_ref",
                "smap_l4_corridor_summary_ref",
                "smap_l4_timeseries_ref",
            ),
            counts_from_payload=lambda payload: _environment_evidence_counts(
                "soil_moisture",
                payload,
            ),
            stale_risk="medium",
            output_refs={
                "soil_moisture_grid_ref": OUTPUT_REFS["soil_moisture_grid_ref"],
                "smap_l4_timeseries_ref": OUTPUT_REFS["smap_l4_timeseries_ref"],
                "smap_l4_corridor_summary_ref": OUTPUT_REFS[
                    "smap_l4_corridor_summary_ref"
                ],
                "gee_project_env": "SCOUT_GEE_PROJECT_ID",
                "gee_fetch_requires_explicit_network": True,
            },
            missing_warning=(
                "SMAP/GEE soil moisture artifacts are missing; run explicit GEE "
                "map preparation or provide a fixture summary."
            ),
        )
    if layer_id == "antecedent-rain":
        return _multi_project_ref_layer_record(
            common,
            project_root=project_root,
            project=project,
            ref_keys=(
                "antecedent_rain_grid_ref",
                "gpm_imerg_precipitation_ref",
                "gpm_imerg_corridor_summary_ref",
                "gpm_imerg_timeseries_ref",
            ),
            counts_from_payload=lambda payload: _environment_evidence_counts(
                "antecedent_rain",
                payload,
            ),
            stale_risk="medium",
            output_refs={
                "antecedent_rain_grid_ref": OUTPUT_REFS["antecedent_rain_grid_ref"],
                "gpm_imerg_timeseries_ref": OUTPUT_REFS["gpm_imerg_timeseries_ref"],
                "gpm_imerg_corridor_summary_ref": OUTPUT_REFS[
                    "gpm_imerg_corridor_summary_ref"
                ],
                "gee_project_env": "SCOUT_GEE_PROJECT_ID",
                "gee_fetch_requires_explicit_network": True,
            },
            missing_warning=(
                "GPM IMERG/GEE antecedent rain artifacts are missing; run explicit "
                "GEE map preparation or provide a fixture summary."
            ),
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
        "mcp": (
            "overpass_aligned_mcp_candidates_ref"
            if project.get("overpass_aligned_mcp_candidates_ref")
            else "mcp_candidates_ref"
        ),
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
    *,
    project_root: Path,
    project: dict[str, Any],
) -> dict[str, Any]:
    contract = build_osm_basemap_contract(
        bbox,
        max_tiles=64,
        tile_url_template="/admin/tiles/osm/{z}/{x}/{y}.png",
    )
    project_id = request.project_id or project_root.name
    cache_manifest_ref = (
        f"outputs/layers/manifests/{project_id}.osm_tile_cache_manifest.json"
    )
    cache_manifest_path = project_root / cache_manifest_ref
    cache_manifest = (
        _load_json(cache_manifest_path) if cache_manifest_path.exists() else None
    )
    cache_plan = cache_manifest.get("plan", {}) if isinstance(cache_manifest, dict) else {}
    seed_summary = (
        cache_manifest.get("seed_summary", {}) if isinstance(cache_manifest, dict) else {}
    )
    cached_tile_count = int(seed_summary.get("tiles_written") or 0) + int(
        seed_summary.get("tiles_skipped_existing") or 0
    )
    source_refs = [
        {
            "ref": "/admin/tiles/osm/{z}/{x}/{y}.png",
            "source_kind": "local_osm_tile_proxy",
            "external_network_required": False,
        }
    ]
    output_refs = {
        "local_proxy_tile_url_template": "/admin/tiles/osm/{z}/{x}/{y}.png"
    }
    counts = {
        "tile_count": contract["tile_count"],
        "zoom": contract["zoom"],
        "max_tiles": contract["max_tiles"],
        "osm_raster_tile_fetch_required": False,
    }
    status = "projection_ready"
    overpass_refs = [
        (key, project.get(key))
        for key in (
            "overpass_evidence_ref",
            "overpass_map_context_ref",
            "overpass_raw_payload_ref",
        )
        if project.get(key)
    ]
    render_extract_ref = project.get("osm_pbf_render_extract_ref")
    render_manifest_ref = project.get("osm_pbf_render_extract_manifest_ref")
    feature_index_ref = project.get("osm_pbf_feature_index_ref")
    if isinstance(render_extract_ref, str) and render_extract_ref:
        source_refs.append(
            {
                "ref": render_extract_ref,
                "source_kind": project.get(
                    "osm_pbf_render_extract_source_kind",
                    "local_osm_pbf_render_extract",
                ),
                "project_ref_key": "osm_pbf_render_extract_ref",
                "external_network_required": False,
                "network_calls_made": False,
                "cache_status": project.get("osm_pbf_cache_status", ""),
                "refresh_required": bool(
                    project.get("osm_pbf_refresh_required", False)
                ),
            }
        )
        output_refs["local_osm_render_extract_ref"] = render_extract_ref
        output_refs["local_osm_render_extract_source_kind"] = project.get(
            "osm_pbf_render_extract_source_kind",
            "local_osm_pbf_render_extract",
        )
        output_refs["osm_rendering_policy"] = "workspace_local_osm_extract_available"
        counts["local_osm_render_extract_feature_count"] = project.get(
            "osm_pbf_render_extract_feature_count",
            0,
        )
        status = "ready_from_project_ref"
    if isinstance(feature_index_ref, str) and feature_index_ref:
        source_refs.append(
            {
                "ref": feature_index_ref,
                "source_kind": "local_osm_pbf_feature_index",
                "project_ref_key": "osm_pbf_feature_index_ref",
                "external_network_required": False,
                "network_calls_made": False,
            }
        )
        output_refs["local_osm_feature_index_ref"] = feature_index_ref
        counts["local_osm_feature_index_feature_count"] = project.get(
            "osm_pbf_feature_index_feature_count",
            0,
        )
        counts["local_osm_feature_index_category_counts"] = project.get(
            "osm_pbf_feature_index_category_counts",
            {},
        )
        status = "ready_from_project_ref"
    if isinstance(render_manifest_ref, str) and render_manifest_ref:
        source_refs.append(
            {
                "ref": render_manifest_ref,
                "source_kind": "local_osm_render_extract_manifest",
                "project_ref_key": "osm_pbf_render_extract_manifest_ref",
                "external_network_required": False,
                "network_calls_made": False,
            }
        )
        output_refs["local_osm_render_extract_manifest_ref"] = render_manifest_ref
    for ref_key, ref in overpass_refs:
        source_refs.append(
            {
                "ref": ref,
                "source_kind": "overpass_vector_evidence",
                "project_ref_key": ref_key,
                "external_network_required": False,
                "network_calls_made": False,
            }
        )
    if overpass_refs:
        output_refs["osm_data_evidence_policy"] = "covered_by_overpass_vector_evidence"
        output_refs["overpass_vector_evidence_ref"] = project.get("overpass_map_context_ref")
        counts["overpass_candidate_count"] = project.get("overpass_candidate_count", 0)
        status = "ready_from_project_ref"
    if cache_manifest:
        source_refs.append(
            {
                "ref": cache_manifest_ref,
                "source_kind": "osm_tile_cache_manifest",
                "external_network_required": False,
                "network_calls_made": bool(cached_tile_count),
            }
        )
        output_refs["osm_tile_cache_manifest_ref"] = cache_manifest_ref
        output_refs["osm_tile_cache_root"] = cache_plan.get("cache_root")
        counts["planned_tile_count"] = cache_plan.get("total_tile_count", 0)
        counts["cached_tile_count"] = cached_tile_count
        counts["seed_tiles_seen"] = seed_summary.get("tiles_seen", 0)
        status = (
            "ready_from_project_ref"
            if seed_summary.get("status") == "seed_complete"
            else "projection_ready"
        )
    record = {
        **common,
        "status": status,
        "source_refs": source_refs,
        "output_refs": output_refs,
        "counts": counts,
        "policy_notes": [
            (
                "Public OSM bulk/offline tile download is prohibited; this "
                "job records a local proxy/cache contract and only accepts "
                "pre-seeded tiles from a permitted provider."
            ),
            (
                "Overpass vector evidence covers OSM data acquisition for "
                "pretrip preparation; OSM raster tiles are optional visual "
                "basemap support and are not required when Overpass is present."
            ),
        ],
        "warnings": [],
        "stale_risk": "medium",
    }
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
    request: LayerPreparationRequest,
) -> dict[str, Any]:
    imagery_source = imagery_source_for_project(project)
    record = {
        **common,
        "status": "wmts_runtime_only",
        "source_refs": [
            {
                "source_id": imagery_source["source_id"],
                "source_kind": imagery_source["source_kind"],
                "provider": imagery_source.get("provider"),
                "registry_id": project.get("imagery_source_registry_id")
                or DEFAULT_REGISTRY_ID,
                "project_ref_key": "imagery_source_id",
                "url_template_sha256": hashlib.sha256(
                    str(imagery_source.get("url_template") or "").encode("utf-8")
                ).hexdigest(),
                "raw_url_template_embedded": False,
            }
        ],
        "output_refs": {
            "tile_delivery": "direct_wmts_runtime",
            "imagery_source_registry_id": project.get("imagery_source_registry_id")
            or DEFAULT_REGISTRY_ID,
        },
        "counts": {
            "registered_raster_manifest_count": 0,
            "fallback_tile_available": False,
            "remote_imagery_source_registered": True,
            "imagery_tile_cache_plan_tile_count": 0,
            "imagery_tile_cache_plan_zoom_count": 0,
        },
        "warnings": [
            (
                "Imagery tile cache was not seeded in this preparation run; "
                "map display will use allowlisted WMTS sources at runtime."
            )
        ],
        "stale_risk": "medium",
        "imagery_source_id": imagery_source["source_id"],
        "imagery_source_kind": imagery_source["source_kind"],
        "imagery_source_registry_id": project.get("imagery_source_registry_id")
        or DEFAULT_REGISTRY_ID,
        "remote_fetch_requires_explicit_enable": False,
        "raster_tile_delivery": "direct_wmts_runtime",
        "tile_cutting_required": False,
        "downloads_tiles_into_repo": False,
    }
    cache_manifest_ref = project.get("imagery_tile_cache_manifest_ref")
    if cache_manifest_ref:
        cache_manifest_path = project_root / str(cache_manifest_ref)
        cache_manifest = (
            _load_json(cache_manifest_path) if cache_manifest_path.exists() else {}
        )
        plan = cache_manifest.get("plan") if isinstance(cache_manifest, dict) else {}
        seed_summary = (
            cache_manifest.get("seed_summary") if isinstance(cache_manifest, dict) else {}
        )
        plan = plan if isinstance(plan, dict) else {}
        seed_summary = seed_summary if isinstance(seed_summary, dict) else {}
        cached_tile_count = int(seed_summary.get("tiles_written") or 0) + int(
            seed_summary.get("tiles_skipped_existing") or 0
        )
        record["status"] = (
            "ready_from_project_ref"
            if seed_summary.get("status") == "seed_complete"
            else "tile_cache_plan_ready"
        )
        record["source_refs"].append(
            {
                "ref": str(cache_manifest_ref),
                "source_kind": "imagery_tile_cache_manifest",
                "project_ref_key": "imagery_tile_cache_manifest_ref",
                "external_network_required": False,
                "network_calls_made": bool(cached_tile_count),
            }
        )
        record["output_refs"].update(
            {
                "imagery_tile_cache_manifest_ref": str(cache_manifest_ref),
                "imagery_tile_cache_plan_ref": project.get("imagery_tile_cache_plan_ref"),
                "imagery_tile_cache_root": plan.get("cache_root"),
                "local_raster_tile_url_template": (
                    f"/admin/tiles/imagery/{request.project_id}/imagery/{{z}}/{{x}}/{{y}}.png"
                ),
                "tile_delivery": "local_cache_then_wmts_runtime",
            }
        )
        raster_bbox = _normalized_optional_bbox(plan.get("bbox_wgs84"))
        if raster_bbox is not None:
            record["raster_bbox_wgs84"] = raster_bbox
            record["raster_coverage_policy"] = "render_intersecting_tiles_only"
        for source_key, target_key in (
            ("zoom_range", "raster_tile_zoom_range"),
            ("cache_root", "raster_tile_cache_root"),
            ("total_tile_count", "raster_tile_count"),
            ("min_zoom", "raster_tile_min_zoom"),
            ("max_zoom", "raster_tile_max_zoom"),
        ):
            if source_key in plan:
                record[target_key] = plan[source_key]
        record["counts"].update(
            {
                "imagery_tile_cache_plan_tile_count": plan.get("total_tile_count", 0),
                "imagery_tile_cache_plan_zoom_count": len(plan.get("zoom_ranges") or []),
                "cached_tile_count": cached_tile_count,
                "seed_tiles_seen": seed_summary.get("tiles_seen", 0),
            }
        )
        record["warnings"] = [
            warning
            for warning in record["warnings"]
            if "Imagery tile cache was not seeded" not in warning
        ]
        record["raster_tile_delivery"] = "local_cache_then_wmts_runtime"
        record["remote_fetch_requires_explicit_enable"] = True
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
    imagery_bbox = _normalized_optional_bbox(project.get("imagery_bbox_wgs84"))
    if bbox is None:
        bbox = imagery_bbox

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
    if imagery_bbox:
        metadata["imagery_bbox_wgs84"] = imagery_bbox
        metadata["imagery_bbox_policy"] = project.get(
            "imagery_bbox_policy",
            "gpx_bbox_scaled_115_percent",
        )
        metadata["imagery_bbox_scale_factor"] = project.get(
            "imagery_bbox_scale_factor",
            1.15,
        )
    if project.get("imagery_source_id"):
        metadata["imagery_source_id"] = project["imagery_source_id"]
    if project.get("imagery_source_registry_id"):
        metadata["imagery_source_registry_id"] = project["imagery_source_registry_id"]
    return metadata


def _maybe_seed_imagery_tile_cache(
    request: LayerPreparationRequest,
) -> dict[str, Any] | None:
    if not request.seed_imagery_cache:
        return None
    if request.network_mode != "explicit-fetch" or not request.allow_network_fetch:
        raise ValueError(
            "seed_imagery_cache requires network_mode=explicit-fetch and allow_network_fetch=true"
        )
    if not request.imagery_provider_allows_offline_prefetch:
        raise ValueError(
            "imagery_provider_allows_offline_prefetch must be true before seeding"
        )
    project_root = _resolve_project_root(request)
    _reject_fixture_fetch(project_root)
    project_path = project_root / "project.json"
    project = _load_json(project_path)
    route_summary = _load_project_ref(
        project_root,
        project,
        "route_summary_ref",
        required=True,
    )
    route_bbox = normalize_bbox_wgs84(request.bbox or route_summary["bbox_wgs84"])
    bbox = (
        _normalized_optional_bbox(project.get("imagery_bbox_wgs84"))
        or _expand_bbox_by_meters(route_bbox, request.route_corridor_m)
    )
    imagery_source = imagery_source_for_project(
        {
            **project,
            "imagery_source_id": _imagery_seed_source_id(project),
        }
    )
    plan = build_imagery_tile_cache_plan(
        bbox,
        project_id=request.project_id or project_root.name,
        layer_id="imagery",
        imagery_source=imagery_source,
        cache_root=_imagery_tile_cache_root(),
        min_zoom=request.imagery_min_zoom,
        max_zoom=request.imagery_max_zoom,
    )
    seed_summary = seed_imagery_tile_cache(
        plan,
        imagery_source=imagery_source,
        provider_allows_offline_prefetch=True,
        dry_run=False,
        max_tiles=request.imagery_seed_max_tiles,
        fallback_cache_project_ids=request.imagery_cache_fallback_project_ids,
    )
    project_id = request.project_id or str(project.get("project_id") or project_root.name)
    plan_ref = f"outputs/layers/manifests/{project_id}.imagery_tile_cache_plan.json"
    manifest_ref = f"outputs/layers/manifests/{project_id}.imagery_tile_cache_manifest.json"
    tile_manifest = {
        "artifact_kind": "pretrip_imagery_tile_cache_manifest",
        "schema_version": "route_corridor_map_preparation.v1",
        "project_id": project_id,
        "generated_at": request.prepared_at or _utc_now(),
        "source_path": manifest_ref,
        "plan_ref": plan_ref,
        "plan": plan,
        "seed_summary": seed_summary,
        "imagery_source_id": imagery_source.get("source_id"),
        "imagery_source_kind": imagery_source.get("source_kind"),
        "imagery_cache_fallback_project_ids": list(
            request.imagery_cache_fallback_project_ids
        ),
        "candidate_only": True,
        "runtime_safety_truth": False,
        "raw_tile_embedded": False,
        "downloads_tiles_into_repo": False,
    }
    _write_json(project_root / plan_ref, plan)
    _write_json(project_root / manifest_ref, tile_manifest)
    updated = {
        **project,
        "imagery_tile_cache_plan_ref": plan_ref,
        "imagery_tile_cache_manifest_ref": manifest_ref,
        "imagery_tile_cache_root": plan.get("cache_root"),
        "imagery_tile_cache_source_id": imagery_source.get("source_id"),
        "imagery_tile_cache_source_role": "raster_label_ocr_preferred_source",
        "imagery_tile_cache_plan_tile_count": plan.get("total_tile_count", 0),
        "imagery_tile_cache_seed_status": seed_summary.get("status"),
        "imagery_tile_cache_seed_tiles_seen": seed_summary.get("tiles_seen", 0),
        "imagery_tile_cache_seed_tiles_written": seed_summary.get("tiles_written", 0),
        "imagery_tile_cache_seed_tiles_skipped_existing": seed_summary.get(
            "tiles_skipped_existing",
            0,
        ),
    }
    _write_json(project_path, updated)
    return tile_manifest


def _imagery_seed_source_id(project: dict[str, Any]) -> str:
    source_id = str(project.get("imagery_source_id") or "").strip()
    if source_id in RASTER_LABEL_PREFERRED_OCR_SOURCE_IDS:
        return source_id
    return RASTER_LABEL_PREFERRED_OCR_SOURCE_IDS[0]


def _imagery_tile_cache_root() -> Path:
    value = os.getenv("SCOUT_ADMIN_RASTER_TILE_CACHE_ROOT")
    if value and value.strip():
        return Path(value).expanduser()
    return DEFAULT_SCOUT_DATA_ROOT / "raster-tiles"


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
    if project.get("osm_pbf_extracted_at"):
        record["network_policy"] = _network_policy(request, network_calls_made=False)
        record["lifecycle"]["fetch"]["status"] = "completed_local_osm_pbf_extract"
        record["lifecycle"]["fetch"]["external_network_calls_made"] = False
        record["lifecycle"]["fetch"]["fetched_at"] = project["osm_pbf_extracted_at"]
        record["lifecycle"]["fetch"]["local_pbf_source_ref"] = project.get(
            "osm_pbf_source_ref",
            "",
        )
        record["lifecycle"]["fetch"]["local_pbf_source_url"] = project.get(
            "osm_pbf_source_url",
            "",
        )
        record["lifecycle"]["fetch"]["local_pbf_cache_status"] = project.get(
            "osm_pbf_cache_status",
            "",
        )
        record["lifecycle"]["fetch"]["local_pbf_cache_expires_at"] = project.get(
            "osm_pbf_cache_expires_at",
            "",
        )
        record["lifecycle"]["fetch"]["local_pbf_refresh_required"] = bool(
            project.get("osm_pbf_refresh_required", False)
        )
        record["source_refs"].append(
            {
                "ref": project.get("osm_pbf_raw_payload_ref", ""),
                "source_kind": "local_osm_pbf_osmjson_extract",
                "external_network_required": False,
                "network_calls_made": False,
                "cache_status": project.get("osm_pbf_cache_status", ""),
                "refresh_required": bool(
                    project.get("osm_pbf_refresh_required", False)
                ),
            }
        )
        record["output_refs"]["local_osm_pbf_source_ref"] = project.get(
            "osm_pbf_source_ref",
            "",
        )
        record["output_refs"]["local_osm_pbf_source_url"] = project.get(
            "osm_pbf_source_url",
            "",
        )
        record["output_refs"]["local_osm_pbf_cache_status"] = project.get(
            "osm_pbf_cache_status",
            "",
        )
        record["output_refs"]["local_osm_pbf_cache_expires_at"] = project.get(
            "osm_pbf_cache_expires_at",
            "",
        )
        record["output_refs"]["local_osm_pbf_refresh_required"] = bool(
            project.get("osm_pbf_refresh_required", False)
        )
        record.setdefault("policy_notes", []).append(
            (
                "OSM vector evidence was extracted from a local .osm.pbf route "
                "corridor, not fetched from live Overpass."
            )
        )
        if project.get("osm_pbf_refresh_required"):
            record.setdefault("warnings", []).append(
                (
                    "Local OSM PBF cache is older than the configured TTL; "
                    "refresh recommended before new pretrip fetch."
                )
            )
    elif project.get("overpass_fetched_at"):
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
    output_refs: dict[str, Any] | None = None,
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


def _multi_project_ref_layer_record(
    common: dict[str, Any],
    *,
    project_root: Path,
    project: dict[str, Any],
    ref_keys: tuple[str, ...],
    counts_from_payload: Any,
    stale_risk: str,
    output_refs: dict[str, Any],
    missing_warning: str,
) -> dict[str, Any]:
    warnings: list[str] = []
    source_refs: list[dict[str, Any]] = []
    primary_payload: Any | None = None
    for ref_key in ref_keys:
        ref = project.get(ref_key)
        if not isinstance(ref, str) or not ref:
            continue
        path = project_root / ref
        if not path.exists():
            warnings.append(f"{ref_key} points to a missing file: {ref}")
            continue
        if primary_payload is None:
            primary_payload = _load_json(path)
        source_refs.append(_source_ref(ref, path, ref_key))

    status = "ready_from_project_ref" if source_refs else "missing_source"
    if not source_refs and not warnings:
        warnings.append(missing_warning)
    return _with_lifecycle(
        {
            **common,
            "status": status,
            "source_refs": source_refs,
            "output_refs": output_refs,
            "counts": counts_from_payload(primary_payload)
            if primary_payload is not None
            else {},
            "warnings": warnings,
            "blockers": [],
            "stale_risk": stale_risk,
            "boundary": {
                "candidate_only": True,
                "runtime_safety_truth": False,
                "client_secret_value_embedded": False,
            },
        }
    )


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


def _with_environment_fetch_lifecycle(
    record: dict[str, Any],
    *,
    project: dict[str, Any],
) -> dict[str, Any]:
    if not project.get("cwa_external_api_calls_made"):
        return record
    record["lifecycle"].setdefault("fetch", {})
    record["lifecycle"]["fetch"]["status"] = "completed_live_fetch"
    record["lifecycle"]["fetch"]["external_network_calls_made"] = True
    record["lifecycle"]["fetch"]["provider"] = "cwa_opendata"
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
        "overpass_route_alignment": manifest.get("overpass_route_alignment"),
        "raster_label_preparation": manifest.get("raster_label_preparation"),
        "boss_point_synthesis": manifest.get("boss_point_synthesis"),
        "mileage_tag_alignment": manifest.get("mileage_tag_alignment"),
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
                "terrain_visualization_ref",
                "web_case_evidence_ref",
                "raster_label_ocr_output_ref",
                "raster_label_evidence_ref",
                "raster_label_adapter_manifest_ref",
                "gis_semantic_input_bundle_ref",
                "gis_perception_ai_judgements_ref",
                "gis_checkpoint_candidates_ref",
                "ln_proposals_ref",
                "poi_candidates_ref",
                "terrain_risk_candidates_ref",
                "detour_route_candidates_ref",
                "layer_map_projection_ref",
                "layer_debug_projection_events_ref",
                "route_context_evidence_ref",
                "route_context_source_manifest_ref",
                "route_context_pack_ref",
                "route_context_crawl_seed_plan_ref",
                "route_context_media_manifest_ref",
                "route_context_points_ref",
                "route_mileage_k_anchors_ref",
                "overpass_route_alignment_ref",
                "overpass_aligned_checkpoint_candidates_ref",
                "overpass_aligned_segment_candidates_ref",
                "overpass_aligned_segment_display_geometry_ref",
                "overpass_aligned_mcp_candidates_ref",
                "boss_points_ref",
                "boss_points_geojson_ref",
                "route_pressure_profile_ref",
                "route_pressure_profile_geojson_ref",
                "mileage_tag_alignment_ref",
                "mileage_tag_alignment_geojson_ref",
            )
            if key in outputs
        },
        "gpx_speed_filter": manifest["inputs"]["gpx_speed_filter"],
        "overpass_route_alignment": manifest.get("overpass_route_alignment"),
        "raster_label_preparation": manifest.get("raster_label_preparation"),
        "boss_point_synthesis": manifest.get("boss_point_synthesis"),
        "mileage_tag_alignment": manifest.get("mileage_tag_alignment"),
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
    layers = [_map_projection_layer(layer) for layer in manifest["layers"]]
    _augment_map_projection_layers(manifest, layers)
    return {
        "artifact_kind": "pretrip_map_layer_projection",
        "schema_version": LAYER_PREPARATION_VERSION,
        "project_id": manifest["project_id"],
        "source_id": manifest["job_id"],
        "source_path": manifest["outputs"]["layer_map_projection_ref"],
        "evidence_type": "pretrip_map_layer_projection",
        "bbox_wgs84": manifest["bbox_wgs84"],
        "projection_only": True,
        "layers": layers,
        "boundary": manifest["boundary"],
    }


def _augment_map_projection_layers(
    manifest: dict[str, Any],
    layers: list[dict[str, Any]],
) -> None:
    by_id = {str(layer.get("layer_id")): layer for layer in layers}
    overpass_alignment = manifest.get("overpass_route_alignment")
    if isinstance(overpass_alignment, dict) and overpass_alignment.get("status") == "completed":
        output_refs = overpass_alignment.get("output_refs") or {}
        counts = overpass_alignment.get("counts") or {}
        if "checkpoints" in by_id:
            by_id["checkpoints"].setdefault("output_refs", {}).update(
                {
                    key: output_refs[key]
                    for key in ("overpass_aligned_checkpoint_candidates_ref",)
                    if key in output_refs
                }
            )
            by_id["checkpoints"].setdefault("counts", {}).update(
                {
                    "overpass_aligned": True,
                    "overpass_alignment_snapped_point_count": counts.get(
                        "snapped_point_count",
                        0,
                    ),
                }
            )
        if "segments" in by_id:
            by_id["segments"].setdefault("output_refs", {}).update(
                {
                    key: output_refs[key]
                    for key in (
                        "overpass_aligned_segment_candidates_ref",
                        "overpass_aligned_segment_display_geometry_ref",
                    )
                    if key in output_refs
                }
            )
            by_id["segments"].setdefault("counts", {}).update(
                {
                    "overpass_aligned": True,
                    "overpass_alignment_snapped_point_count": counts.get(
                        "snapped_point_count",
                        0,
                    ),
                }
            )
        if "mcp" in by_id:
            by_id["mcp"].setdefault("output_refs", {}).update(
                {
                    key: output_refs[key]
                    for key in ("overpass_aligned_mcp_candidates_ref",)
                    if key in output_refs
                }
            )
            by_id["mcp"].setdefault("counts", {}).update(
                {
                    "overpass_aligned": True,
                    "overpass_alignment_snapped_point_count": counts.get(
                        "snapped_point_count",
                        0,
                    ),
                }
            )

    boss = manifest.get("boss_point_synthesis")
    if isinstance(boss, dict) and boss.get("status") == "completed":
        layers.append(
            {
                "layer_id": "boss-points",
                "status": "ready_from_project_ref",
                "source_refs": [],
                "output_refs": boss.get("output_refs") or {},
                "counts": {
                    "boss_point_count": boss.get("boss_point_count", 0),
                    "route_pressure_sample_count": boss.get(
                        "route_pressure_sample_count",
                        0,
                    ),
                    "route_pressure_peak_count": boss.get(
                        "route_pressure_peak_count",
                        0,
                    ),
                    "overpass_aligned": True,
                },
            }
        )


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
        "raster_tile_min_zoom",
        "raster_tile_max_zoom",
        "raster_tile_delivery",
        "imagery_tile_cache_plan_ref",
        "imagery_bbox_wgs84",
        "imagery_bbox_policy",
        "imagery_bbox_scale_factor",
        "imagery_source_id",
        "imagery_source_kind",
        "imagery_source_registry_id",
        "remote_fetch_requires_explicit_enable",
        "remote_fetch_env",
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
    current = _load_json(project_path) if project_path.exists() else {}
    updated = {
        **project,
        **current,
        **outputs,
        "layer_preparation_updated_at": prepared_at,
        "layer_preparation_schema_version": LAYER_PREPARATION_VERSION,
    }
    if updated.get("risk_score_generation_status") == "completed":
        _clear_risk_generation_failure_metadata(updated)
    _write_json(project_path, updated)


def _project_state_output_refs(project: dict[str, Any]) -> dict[str, Any]:
    keys = (
        *SCOUT_RISK_OUTPUT_REFS.keys(),
        *CALIBRATED_RISK_OUTPUT_REFS.keys(),
        "cwa_weather_evidence_ref",
        "cwa_warnings_geojson_ref",
        "cwa_observations_geojson_ref",
        "cwa_qpf_grid_ref",
        "cwa_qpf_route_timeline_ref",
        "cwa_qpf_corridor_summary_ref",
        "soil_moisture_grid_ref",
        "smap_l4_timeseries_ref",
        "smap_l4_corridor_summary_ref",
        "antecedent_rain_grid_ref",
        "gpm_imerg_timeseries_ref",
        "gpm_imerg_corridor_summary_ref",
        "risk_score_point_count",
        "risk_score_source_feature_count",
        "risk_route_sample_count",
        "risk_ribbon_segment_count",
        "risk_score_source_profile",
        "risk_score_updated_at",
        "risk_score_generation_status",
        "risk_score_generation_basis",
        "risk_score_generation_skipped_reason",
        "risk_score_generation_error",
        "calibrated_risk_heatmap_segment_count",
        "calibrated_risk_heatmap_warning_cp_overlay_count",
        "risk_attribution_diagnostic_checkpoint_count",
        "calibrated_risk_heatmap_sync_error",
    )
    return {key: project[key] for key in keys if key in project}


def _run_overpass_route_alignment_after_layer_preparation(
    *,
    project_root: Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    boundary = {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "review_gated": True,
        "phase1_runtime_mutation_allowed": False,
        "phase2_brain_writeback_allowed": False,
        "workspace_file_mutation_allowed": True,
        "safety_api_called": False,
    }
    normalized_layers = set(manifest.get("normalized_layers") or [])
    if not (normalized_layers & {"overpass", "risk-ribbon", "risk-score"}):
        return {
            "status": "not_requested",
            "reason": "overpass_or_risk_layers_not_requested",
            "trigger": "prepare_layers_with_overpass_or_risk",
            "boundary": boundary,
        }
    project_path = project_root / "project.json"
    if not project_path.exists():
        return {
            "status": "skipped_missing_project",
            "trigger": "prepare_layers_with_overpass_or_risk",
            "boundary": boundary,
        }
    try:
        from pretrip_overpass_route_alignment import align_workspace_route_to_overpass

        max_projection_distance_m = _as_float(
            os.environ.get("SCOUT_OVERPASS_ALIGNMENT_MAX_PROJECTION_DISTANCE_M")
        )
        if max_projection_distance_m is None:
            max_projection_distance_m = DEFAULT_OVERPASS_ALIGNMENT_MAX_PROJECTION_DISTANCE_M
        result = align_workspace_route_to_overpass(
            project_root,
            max_projection_distance_m=max_projection_distance_m,
            generated_at=manifest["finished_at"],
        )
    except Exception as exc:  # pragma: no cover - defensive manifest reporting
        return {
            "status": "failed",
            "error": str(exc),
            "trigger": "prepare_layers_with_overpass_or_risk",
            "boundary": boundary,
        }
    return {
        "trigger": "prepare_layers_with_overpass_or_risk",
        "boundary": boundary,
        **result,
    }


def _skipped_connected_refresh_post_enrichment(name: str) -> dict[str, Any]:
    return {
        "status": "skipped_connected_refresh",
        "reason": "non_weather_post_enrichment_is_not_part_of_recurring_api_refresh",
        "trigger": "dashboard_connected_refresh",
        "component": name,
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "workspace_file_mutation_allowed": False,
        },
    }


def _run_raster_label_preparation_after_layer_preparation(
    *,
    project_root: Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    boundary = {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "review_gated": True,
        "phase1_runtime_mutation_allowed": False,
        "phase2_brain_writeback_allowed": False,
        "workspace_file_mutation_allowed": True,
        "safety_api_called": False,
    }
    project_path = project_root / "project.json"
    if not project_path.exists():
        return {
            "status": "skipped_missing_project",
            "trigger": "prepare_layers_rudy_tw_ocr_route_context",
            "boundary": boundary,
        }

    output_refs = {
        "raster_label_ocr_output_ref": RASTER_LABEL_OCR_OUTPUT_REF,
        "raster_label_evidence_ref": OUTPUT_REFS["raster_label_evidence_ref"],
        "raster_label_adapter_manifest_ref": RASTER_LABEL_ADAPTER_MANIFEST_REF,
    }
    ocr_status = "not_started"
    adapter_status = "not_started"
    route_context_status = "not_started"
    route_context_output_refs: dict[str, str] = {}
    route_context_counts: dict[str, Any] = {}

    try:
        from pretrip_raster_label_ocr import extract_raster_label_ocr

        ocr_result = extract_raster_label_ocr(
            project_root,
            raster_label_plan_path=manifest["outputs"]["raster_label_plan_ref"],
            output_ref=RASTER_LABEL_OCR_OUTPUT_REF,
            source_ids=RASTER_LABEL_PREFERRED_OCR_SOURCE_IDS,
            collected_at=manifest.get("finished_at"),
        )
    except Exception as exc:  # pragma: no cover - defensive manifest reporting
        ocr_result = {
            "status": "failed",
            "error": str(exc),
            "output_ref": RASTER_LABEL_OCR_OUTPUT_REF,
            "label_count": 0,
            "tile_record_count": 0,
            "tile_skipped_count": 0,
            "missing_dependencies": [],
        }
    ocr_status = str(ocr_result.get("status") or "unknown")

    adapter_result: dict[str, Any] | None = None
    if ocr_status == "completed":
        try:
            from pretrip_raster_label_adapter import build_raster_label_evidence

            adapter_result = build_raster_label_evidence(
                project_root,
                source_path=ocr_result.get("output_ref") or RASTER_LABEL_OCR_OUTPUT_REF,
                output_ref=OUTPUT_REFS["raster_label_evidence_ref"],
                manifest_ref=RASTER_LABEL_ADAPTER_MANIFEST_REF,
                collected_at=manifest.get("finished_at"),
            )
        except Exception as exc:  # pragma: no cover - defensive manifest reporting
            adapter_result = {
                "status": "failed",
                "error": str(exc),
                "output_ref": OUTPUT_REFS["raster_label_evidence_ref"],
                "manifest_ref": RASTER_LABEL_ADAPTER_MANIFEST_REF,
                "feature_count": 0,
            }
        adapter_status = str(adapter_result.get("status") or "unknown")
    else:
        adapter_status = "skipped_ocr_not_completed"

    should_refresh_route_context = adapter_status == "completed" or ocr_status.startswith(
        "blocked"
    )
    if should_refresh_route_context:
        try:
            from pretrip_route_context_collection import collect_pretrip_route_context

            route_context_result = collect_pretrip_route_context(
                project_root,
                include_route_notes=True,
                route_note_point_policy="seed_only",
                write_briefing=False,
                collected_at=manifest.get("finished_at"),
            )
        except Exception as exc:  # pragma: no cover - defensive manifest reporting
            route_context_result = {
                "status": "failed",
                "error": str(exc),
                "output_refs": {},
                "counts": {},
            }
        route_context_status = str(route_context_result.get("status") or "unknown")
        route_context_outputs = route_context_result.get("outputs") or {}
        route_context_output_refs = {
            key: value
            for key, value in {
                "route_context_evidence_ref": route_context_outputs.get(
                    "route_context_evidence_ref"
                ),
                "route_context_source_manifest_ref": route_context_outputs.get(
                    "route_context_source_manifest_ref"
                ),
                "route_context_pack_ref": route_context_outputs.get(
                    "route_context_pack_ref"
                ),
                "route_context_crawl_seed_plan_ref": route_context_outputs.get(
                    "route_context_crawl_seed_plan_ref"
                ),
                "route_context_media_manifest_ref": route_context_outputs.get(
                    "route_context_media_manifest_ref"
                ),
                "route_context_points_ref": route_context_outputs.get(
                    "route_context_points_ref"
                ),
                "route_mileage_k_anchors_ref": route_context_outputs.get(
                    "route_mileage_k_anchors_ref"
                ),
            }.items()
            if isinstance(value, str) and value
        }
        route_context_counts = route_context_result.get("counts") or {}
        output_refs.update(route_context_output_refs)
    else:
        route_context_status = "skipped_adapter_not_completed"

    project_refs_updated = (
        (ocr_status not in {"not_started", "failed"})
        or adapter_status == "completed"
        or route_context_status == "completed"
    )
    return {
        "status": (
            "completed_with_ocr_blocked"
            if route_context_status == "completed" and ocr_status.startswith("blocked")
            else
            "completed"
            if route_context_status == "completed"
            else "blocked"
            if ocr_status.startswith("blocked")
            else route_context_status
        ),
        "trigger": "prepare_layers_rudy_tw_ocr_route_context",
        "ocr": {
            "status": ocr_status,
            "output_ref": ocr_result.get("output_ref") or RASTER_LABEL_OCR_OUTPUT_REF,
            "label_count": int(ocr_result.get("label_count") or 0),
            "tile_record_count": int(ocr_result.get("tile_record_count") or 0),
            "tile_skipped_count": int(ocr_result.get("tile_skipped_count") or 0),
            "missing_dependencies": ocr_result.get("missing_dependencies") or [],
        },
        "adapter": adapter_result
        or {
            "status": adapter_status,
            "output_ref": OUTPUT_REFS["raster_label_evidence_ref"],
            "manifest_ref": RASTER_LABEL_ADAPTER_MANIFEST_REF,
            "feature_count": 0,
        },
        "route_context_collection": {
            "status": route_context_status,
            "counts": route_context_counts,
            "output_refs": route_context_output_refs,
        },
        "output_refs": output_refs,
        "project_refs_updated": project_refs_updated,
        "boundary": boundary,
    }


def _run_boss_point_synthesis_after_layer_preparation(
    *,
    project_root: Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    boundary = {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "review_gated": True,
        "phase1_runtime_mutation_allowed": False,
        "phase2_brain_writeback_allowed": False,
        "workspace_file_mutation_allowed": True,
    }
    normalized_layers = set(manifest.get("normalized_layers") or [])
    risk_requested = bool(
        normalized_layers
        & {"risk-score", "risk-ribbon", "risk-heatmap", "risk-delta"}
    )
    if not risk_requested:
        return {
            "status": "not_requested",
            "reason": "risk_layers_not_requested",
            "trigger": "prepare_layers_with_risk",
            "boundary": boundary,
        }

    project_path = project_root / "project.json"
    if not project_path.exists():
        return {
            "status": "skipped_missing_project",
            "trigger": "prepare_layers_with_risk",
            "boundary": boundary,
        }
    project = _load_json(project_path)
    risk_ref = project.get("risk_ribbon_ref")
    risk_path = (
        project_root / risk_ref if isinstance(risk_ref, str) and risk_ref else None
    )
    if risk_path is None or not risk_path.exists():
        return {
            "status": "skipped_missing_risk_ribbon",
            "trigger": "prepare_layers_with_risk",
            "required_ref": "risk_ribbon_ref",
            "boundary": boundary,
        }

    try:
        from pretrip_boss_point_synthesis import (
            BOSS_POINTS_GEOJSON_REF,
            BOSS_POINTS_REF,
            ROUTE_PRESSURE_PROFILE_GEOJSON_REF,
            ROUTE_PRESSURE_PROFILE_REF,
            synthesize_pretrip_boss_points,
        )

        timeout_s = _post_process_timeout_s("SCOUT_BOSS_SYNTHESIS_TIMEOUT_S", 90.0)
        with _wall_clock_timeout(timeout_s):
            result = synthesize_pretrip_boss_points(
                project_root,
                generated_at=manifest.get("finished_at"),
            )
        pressure_policy = {}
        pressure_path = project_root / ROUTE_PRESSURE_PROFILE_REF
        if pressure_path.exists():
            pressure_payload = _load_json(pressure_path)
            pressure_policy = pressure_payload.get("policy") or {}
    except TimeoutError:
        return {
            "status": "skipped_timeout",
            "trigger": "prepare_layers_with_risk",
            "timeout_s": _post_process_timeout_s(
                "SCOUT_BOSS_SYNTHESIS_TIMEOUT_S",
                90.0,
            ),
            "reason": "boss_point_synthesis_exceeded_wall_clock_timeout",
            "boundary": boundary,
        }
    except Exception as exc:
        return {
            "status": "failed",
            "trigger": "prepare_layers_with_risk",
            "error": str(exc),
            "boundary": boundary,
        }

    pressure_summary = result.get("route_pressure_profile_summary") or {}
    challenge_fit = result.get("challenge_fit_summary") or {}
    return {
        "status": "completed",
        "trigger": "prepare_layers_with_risk",
        "artifact_kind": result.get("artifact_kind"),
        "schema_version": result.get("schema_version"),
        "boss_point_count": result.get("boss_point_count", 0),
        "route_pressure_sample_count": pressure_summary.get("sample_count", 0),
        "route_pressure_peak_count": pressure_summary.get("peak_count", 0),
        "challenge_fit_decision": challenge_fit.get("decision"),
        "centerline_policy": pressure_policy.get("centerline"),
        "route_pressure_policy": pressure_policy,
        "output_refs": {
            "boss_points_ref": BOSS_POINTS_REF,
            "boss_points_geojson_ref": BOSS_POINTS_GEOJSON_REF,
            "route_pressure_profile_ref": ROUTE_PRESSURE_PROFILE_REF,
            "route_pressure_profile_geojson_ref": ROUTE_PRESSURE_PROFILE_GEOJSON_REF,
        },
        "boundary": result.get("boundary") or boundary,
    }


def _run_mileage_tag_alignment_after_layer_preparation(
    *,
    project_root: Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    boundary = {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "review_gated": True,
        "phase1_runtime_mutation_allowed": False,
        "phase2_brain_writeback_allowed": False,
        "workspace_file_mutation_allowed": True,
    }
    project_path = project_root / "project.json"
    if not project_path.exists():
        return {
            "status": "skipped_missing_project",
            "trigger": "prepare_layers_workspace_mileage_tags",
            "boundary": boundary,
        }

    try:
        from pretrip_mileage_tag_alignment import (
            MILEAGE_TAG_ALIGNMENT_GEOJSON_REF,
            MILEAGE_TAG_ALIGNMENT_REF,
            align_pretrip_workspace_mileage_tags,
        )

        timeout_s = _post_process_timeout_s("SCOUT_MILEAGE_ALIGNMENT_TIMEOUT_S", 90.0)
        with _wall_clock_timeout(timeout_s):
            result = align_pretrip_workspace_mileage_tags(
                project_root,
                generated_at=manifest.get("finished_at"),
            )
    except TimeoutError:
        return {
            "status": "skipped_timeout",
            "trigger": "prepare_layers_workspace_mileage_tags",
            "timeout_s": _post_process_timeout_s(
                "SCOUT_MILEAGE_ALIGNMENT_TIMEOUT_S",
                90.0,
            ),
            "reason": "mileage_tag_alignment_exceeded_wall_clock_timeout",
            "boundary": boundary,
        }
    except Exception as exc:
        return {
            "status": "failed",
            "trigger": "prepare_layers_workspace_mileage_tags",
            "error": str(exc),
            "boundary": boundary,
        }

    counts = result.get("counts") or {}
    return {
        "status": result.get("status", "completed"),
        "trigger": "prepare_layers_workspace_mileage_tags",
        "artifact_kind": result.get("artifact_kind"),
        "schema_version": result.get("schema_version"),
        "tag_count": counts.get("tag_count", 0),
        "aligned_tag_count": counts.get("aligned_tag_count", 0),
        "usable_anchor_count": counts.get("usable_anchor_count", 0),
        "source_kind_counts": counts.get("source_kind_counts", {}),
        "raw_source_summary": result.get("raw_source_summary") or {},
        "output_refs": {
            "mileage_tag_alignment_ref": MILEAGE_TAG_ALIGNMENT_REF,
            "mileage_tag_alignment_geojson_ref": MILEAGE_TAG_ALIGNMENT_GEOJSON_REF,
        },
        "boundary": result.get("boundary") or boundary,
    }


def _run_architecture_preparation_after_layer_preparation(
    *,
    project_root: Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    from pretrip_architecture_preparation import (
        prepare_route_architecture_intelligence,
    )

    result = prepare_route_architecture_intelligence(
        project_root,
        generated_at=str(manifest.get("finished_at") or _utc_now()),
    )
    return {
        "name": "architecture_preparation",
        "status": result["status"],
        "preparation_stage": result["preparation_stage"],
        "reused": result["reused"],
        "fresh": result["fresh"],
        "browseable": result["browseable"],
        "input_sha256": result["input_sha256"],
        "observed_route_bin_count": result["observed_route_bin_count"],
        "guidance_eligible_route_bin_count": result[
            "guidance_eligible_route_bin_count"
        ],
        "checkpoint_passage_timing_node_count": result[
            "checkpoint_passage_timing_node_count"
        ],
        "output_refs": result["output_refs"],
        "data_quality": result["data_quality"],
        "boundary": result["boundary"],
        "error": result["error"],
    }


class _wall_clock_timeout:
    def __init__(self, seconds: float) -> None:
        self.seconds = max(0.0, float(seconds))
        self._previous_handler: Any = None
        self._previous_timer: tuple[float, float] | None = None

    def __enter__(self) -> None:
        if self.seconds <= 0 or not hasattr(signal, "SIGALRM"):
            return None
        self._previous_handler = signal.getsignal(signal.SIGALRM)
        signal.signal(signal.SIGALRM, self._raise_timeout)
        self._previous_timer = signal.setitimer(signal.ITIMER_REAL, self.seconds)
        return None

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        if self.seconds > 0 and hasattr(signal, "SIGALRM"):
            signal.setitimer(signal.ITIMER_REAL, 0)
            if self._previous_timer is not None and self._previous_timer[0] > 0:
                signal.setitimer(signal.ITIMER_REAL, *self._previous_timer)
            if self._previous_handler is not None:
                signal.signal(signal.SIGALRM, self._previous_handler)
        return False

    @staticmethod
    def _raise_timeout(signum: int, frame: Any) -> None:
        raise TimeoutError("post-process exceeded wall-clock timeout")


def _post_process_timeout_s(env_name: str, default_s: float) -> float:
    value = os.environ.get(env_name)
    if value is None or not value.strip():
        return default_s
    try:
        parsed = float(value)
    except ValueError:
        return default_s
    return max(0.0, parsed)


def _sync_scout_risk_outputs(
    *,
    project_root: Path,
    project: dict[str, Any],
    prepared_at: str,
    route_corridor_m: float = 500.0,
) -> dict[str, Any]:
    if _workspace_scout_risk_outputs_ready(
        project_root=project_root,
        project=project,
        route_corridor_m=route_corridor_m,
    ):
        updated = _project_with_scout_risk_refs(project)
        _clear_risk_generation_failure_metadata(updated)
        _stamp_synced_risk_output_provenance(project_root=project_root, project=updated)
        return _project_with_scout_risk_metadata_counts(
            project_root=project_root,
            project=updated,
            prepared_at=prepared_at,
            source_profile="scout_risk_engine_workspace",
        )

    source_root = SCOUT_RISK_OUTPUT_SOURCES.get(str(project.get("project_id", "")))
    if source_root is None or not source_root.exists():
        return _generate_scout_risk_outputs_from_workspace(
            project_root=project_root,
            project=project,
            prepared_at=prepared_at,
            route_corridor_m=route_corridor_m,
        )

    required = (
        "route_risk.geojson",
        "route_risk.metadata.json",
        "risk_score_points.geojson",
        "risk_score_points.metadata.json",
    )
    if any(not (source_root / filename).exists() for filename in required):
        return _generate_scout_risk_outputs_from_workspace(
            project_root=project_root,
            project=project,
            prepared_at=prepared_at,
            route_corridor_m=route_corridor_m,
        )
    if not _scout_risk_route_base_metadata_matches_policy(
        source_root / "route_risk.metadata.json",
        route_corridor_m=route_corridor_m,
    ):
        return _generate_scout_risk_outputs_from_workspace(
            project_root=project_root,
            project=project,
            prepared_at=prepared_at,
            route_corridor_m=route_corridor_m,
        )

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
    _clear_risk_generation_failure_metadata(updated)

    return _project_with_scout_risk_metadata_counts(
        project_root=project_root,
        project=updated,
        prepared_at=prepared_at,
        source_profile="scout_risk_engine_overpass_route_profile",
    )


def _project_with_scout_risk_refs(project: dict[str, Any]) -> dict[str, Any]:
    return {**project, **SCOUT_RISK_OUTPUT_REFS}


def _workspace_scout_risk_outputs_ready(
    *,
    project_root: Path,
    project: dict[str, Any],
    route_corridor_m: float = 500.0,
) -> bool:
    for ref_key in (
        "risk_route_profile_ref",
        "risk_route_profile_metadata_ref",
        "risk_score_points_ref",
        "risk_score_points_metadata_ref",
    ):
        ref = project.get(ref_key) or SCOUT_RISK_OUTPUT_REFS.get(ref_key)
        if not isinstance(ref, str) or not ref:
            return False
        if not (project_root / ref).exists():
            return False
    route_metadata_ref = (
        project.get("risk_route_profile_metadata_ref")
        or SCOUT_RISK_OUTPUT_REFS["risk_route_profile_metadata_ref"]
    )
    route_metadata_path = project_root / route_metadata_ref
    return _scout_risk_route_base_metadata_matches_policy(
        route_metadata_path,
        route_corridor_m=route_corridor_m,
    )


def _scout_risk_route_base_metadata_matches_policy(
    route_metadata_path: Path,
    *,
    route_corridor_m: float,
) -> bool:
    try:
        route_metadata = _load_json(route_metadata_path)
    except (OSError, json.JSONDecodeError):
        return False
    route_base = route_metadata.get("route_base")
    if isinstance(route_base, dict) and route_base.get("route_base") == (
        "overpass_vector_evidence"
    ):
        if (
            route_base.get("sampling_strategy")
            != SCOUT_RISK_ROUTE_BASE_SAMPLING_STRATEGY
        ):
            return False
        corridor_m = _as_float(route_base.get("corridor_m"))
        if corridor_m is None:
            return False
        return abs(corridor_m - float(route_corridor_m)) < 0.001
    return True


def _project_with_scout_risk_metadata_counts(
    *,
    project_root: Path,
    project: dict[str, Any],
    prepared_at: str,
    source_profile: str,
) -> dict[str, Any]:
    updated = dict(project)
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
    updated["risk_score_source_profile"] = source_profile
    updated["risk_score_updated_at"] = prepared_at
    return updated


def _generate_scout_risk_outputs_from_workspace(
    *,
    project_root: Path,
    project: dict[str, Any],
    prepared_at: str,
    route_corridor_m: float = 500.0,
) -> dict[str, Any]:
    inputs = _workspace_scout_risk_generation_inputs(
        project_root=project_root,
        project=project,
    )
    if inputs.get("status") != "ready":
        return {
            **project,
            "risk_score_generation_status": "skipped",
            "risk_score_generation_skipped_reason": inputs.get(
                "reason",
                "workspace_risk_generation_inputs_missing",
            ),
        }

    try:
        _ensure_scout_risk_package_importable()
        from scout_risk.fusion.pretrip import build_overpass_pretrip_route_profile
        from scout_risk.route.outputs import write_route_csv, write_route_geojson
        from scout_risk.route.risk_score_map import (
            build_risk_ribbon_from_geojson,
            build_risk_score_point_map_from_geojson,
            write_risk_ribbon_geojson,
            write_risk_ribbon_metadata,
            write_risk_score_csv,
            write_risk_score_geojson,
            write_risk_score_metadata,
            write_risk_score_xyz,
        )

        refs = SCOUT_RISK_OUTPUT_REFS
        route_risk_path = project_root / refs["risk_route_profile_ref"]
        route_csv_path = project_root / refs["risk_route_profile_csv_ref"]
        route_metadata_path = project_root / refs["risk_route_profile_metadata_ref"]
        score_geojson_path = project_root / refs["risk_score_points_ref"]
        score_csv_path = project_root / refs["risk_score_points_csv_ref"]
        score_xyz_path = project_root / refs["risk_score_points_xyz_ref"]
        score_metadata_path = project_root / refs["risk_score_points_metadata_ref"]
        ribbon_path = project_root / refs["risk_ribbon_ref"]
        ribbon_metadata_path = project_root / refs["risk_ribbon_metadata_ref"]

        profile, route_metadata = build_overpass_pretrip_route_profile(
            dtm_coverage_path=inputs["dtm_coverage_path"],
            overpass_geojson_path=inputs["overpass_geojson_path"],
            reference_gpx_path=inputs["reference_gpx_path"],
            route_id=f"{project.get('project_id', 'route')}.overpass_risk_ribbon",
            corridor_m=route_corridor_m,
        )
        write_route_geojson(profile, route_risk_path, metadata=route_metadata)
        write_route_csv(profile, route_csv_path)
        route_metadata_path.parent.mkdir(parents=True, exist_ok=True)
        route_metadata_path.write_text(
            json.dumps(route_metadata, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )

        point_map = build_risk_score_point_map_from_geojson(route_risk_path)
        write_risk_score_csv(point_map, score_csv_path)
        write_risk_score_xyz(point_map, score_xyz_path)
        write_risk_score_geojson(point_map, score_geojson_path)
        write_risk_score_metadata(point_map, score_metadata_path)

        ribbon = build_risk_ribbon_from_geojson(route_risk_path)
        write_risk_ribbon_geojson(ribbon, ribbon_path)
        write_risk_ribbon_metadata(ribbon, ribbon_metadata_path)
    except Exception as exc:  # pragma: no cover - surfaced in workspace metadata.
        return {
            **project,
            "risk_score_generation_status": "failed",
            "risk_score_generation_error": str(exc),
        }

    updated = {
        **project,
        **SCOUT_RISK_OUTPUT_REFS,
        "risk_score_generation_status": "completed",
        "risk_score_generation_basis": "workspace_dtm_overpass_reference_gpx",
    }
    _clear_risk_generation_failure_metadata(updated)
    _stamp_synced_risk_output_provenance(project_root=project_root, project=updated)
    return _project_with_scout_risk_metadata_counts(
        project_root=project_root,
        project=updated,
        prepared_at=prepared_at,
        source_profile="scout_risk_engine_workspace_generated_overpass_route_profile",
    )


def _clear_risk_generation_failure_metadata(project: dict[str, Any]) -> None:
    for key in ("risk_score_generation_error", "risk_score_generation_skipped_reason"):
        project.pop(key, None)


def _ensure_scout_risk_package_importable() -> None:
    package_src = (
        Path(__file__).resolve().parent
        / "scout-risk-engine"
        / "scout_codex_package"
        / "src"
    )
    if package_src.exists() and package_src.as_posix() not in sys.path:
        sys.path.insert(0, package_src.as_posix())


def _workspace_scout_risk_generation_inputs(
    *,
    project_root: Path,
    project: dict[str, Any],
) -> dict[str, Any]:
    dtm_path = _project_ref_path(
        project_root,
        project,
        "dtm_coverage_summary_ref",
    )
    if dtm_path is None:
        return {"status": "missing", "reason": "dtm_coverage_summary_ref_missing"}

    overpass_path = _first_existing_project_ref_path(
        project_root,
        project,
        ("overpass_map_context_ref", "overpass_vector_evidence_ref"),
    )
    if overpass_path is None:
        return {"status": "missing", "reason": "overpass_geojson_ref_missing"}

    reference_gpx_path = _reference_gpx_path_for_risk_generation(
        project_root=project_root,
        project=project,
    )
    if reference_gpx_path is None:
        return {"status": "missing", "reason": "reference_gpx_ref_missing"}

    return {
        "status": "ready",
        "dtm_coverage_path": dtm_path,
        "overpass_geojson_path": overpass_path,
        "reference_gpx_path": reference_gpx_path,
    }


def _project_ref_path(
    project_root: Path,
    project: dict[str, Any],
    ref_key: str,
) -> Path | None:
    ref = project.get(ref_key)
    if not isinstance(ref, str) or not ref:
        return None
    path = Path(ref).expanduser()
    if not path.is_absolute():
        path = project_root / path
    return path if path.exists() else None


def _first_existing_project_ref_path(
    project_root: Path,
    project: dict[str, Any],
    ref_keys: tuple[str, ...],
) -> Path | None:
    for ref_key in ref_keys:
        path = _project_ref_path(project_root, project, ref_key)
        if path is not None:
            return path
    return None


def _reference_gpx_path_for_risk_generation(
    *,
    project_root: Path,
    project: dict[str, Any],
) -> Path | None:
    bundle_path = _project_ref_path(project_root, project, "route_evidence_bundle_ref")
    if bundle_path is not None:
        bundle = _load_json(bundle_path)
        golden_route = bundle.get("golden_route", {})
        if isinstance(golden_route, dict):
            for key in ("filtered_geometry_ref", "source_path"):
                value = golden_route.get(key)
                if not isinstance(value, str) or not value:
                    continue
                path = Path(value).expanduser()
                if not path.is_absolute():
                    path = project_root / path
                if path.exists():
                    return path
    return _project_ref_path(project_root, project, "golden_route_gpx_ref")


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
    if path.is_dir():
        entry_count = 0
        size_bytes = 0
        for child in path.rglob("*"):
            if not child.is_file():
                continue
            entry_count += 1
            try:
                size_bytes += child.stat().st_size
            except OSError:
                continue
        return {
            "ref": ref,
            "project_ref_key": ref_key,
            "exists": True,
            "source_kind": "directory",
            "entry_count": entry_count,
            "size_bytes": size_bytes,
            "sha256": None,
        }
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


def _environment_evidence_counts(layer_key: str, payload: Any) -> dict[str, Any]:
    prefix = layer_key.replace("-", "_")
    if isinstance(payload, list):
        return {f"{prefix}_item_count": len(payload)}
    if not isinstance(payload, dict):
        return {f"{prefix}_item_count": 0}
    counts = payload.get("counts")
    if isinstance(counts, dict):
        return dict(counts)
    features = payload.get("features")
    if isinstance(features, list):
        return {
            f"{prefix}_feature_count": len(features),
            "geojson_feature_count": len(features),
        }
    segments = payload.get("segments")
    if isinstance(segments, list):
        return {
            f"{prefix}_segment_count": len(segments),
            "route_weather_segment_count": len(segments),
        }
    candidates = payload.get("candidates")
    if isinstance(candidates, list):
        return {
            f"{prefix}_candidate_count": len(candidates),
            "candidate_count": len(candidates),
        }
    documents = payload.get("documents")
    if isinstance(documents, list):
        return {
            f"{prefix}_document_count": len(documents),
            "document_count": len(documents),
        }
    return {f"{prefix}_item_count": 1}


def _environment_fetch_result(
    dataset_id: str,
    *,
    status: str,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "dataset_id": dataset_id,
        "status": status,
        "error": error,
        "secret_value_embedded": False,
    }


def _iso_hour(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        parsed = _parse_iso_datetime(str(value))
    except (TypeError, ValueError):
        return None
    return (
        parsed.replace(minute=0, second=0, microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _iso_or_none(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        return _parse_iso_datetime(str(value)).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError):
        return str(value)


def _min_iso(values: list[Any]) -> str | None:
    parsed: list[datetime] = []
    for value in values:
        if value in (None, ""):
            continue
        try:
            parsed.append(_parse_iso_datetime(str(value)))
        except (TypeError, ValueError):
            continue
    if not parsed:
        return None
    return min(parsed).isoformat().replace("+00:00", "Z")


def _max_iso(values: list[Any]) -> str | None:
    parsed: list[datetime] = []
    for value in values:
        if value in (None, ""):
            continue
        try:
            parsed.append(_parse_iso_datetime(str(value)))
        except (TypeError, ValueError):
            continue
    if not parsed:
        return None
    return max(parsed).isoformat().replace("+00:00", "Z")


def _cwa_time_metadata(
    *,
    prepared_at: str,
    api_request_attempted: bool,
    external_calls_made: bool,
    weather_points: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    observations: list[dict[str, Any]],
) -> dict[str, Any]:
    forecast_valid_from = _min_iso([point.get("validFrom") for point in weather_points])
    forecast_valid_until = _max_iso([point.get("validTo") for point in weather_points])
    warning_valid_from = _min_iso([warning.get("valid_from") for warning in warnings])
    warning_valid_until = _max_iso([warning.get("valid_to") for warning in warnings])
    latest_observation_at = _max_iso([item.get("obs_time") for item in observations])
    valid_from = _min_iso([forecast_valid_from, warning_valid_from, latest_observation_at])
    valid_until = _max_iso([forecast_valid_until, warning_valid_until, latest_observation_at])
    attempted_at = prepared_at if api_request_attempted else None
    fetched_at = prepared_at if external_calls_made else None
    metadata = {
        "request_timestamp": prepared_at,
        "request_timestamp_hour": _iso_hour(prepared_at),
        "generated_at_hour": _iso_hour(prepared_at),
        "api_request_attempted": api_request_attempted,
        "api_request_attempted_at": attempted_at,
        "api_request_attempted_at_hour": _iso_hour(attempted_at),
        "api_fetched_at": fetched_at,
        "api_fetched_at_hour": _iso_hour(fetched_at),
        "fetched_at": fetched_at,
        "fetched_at_hour": _iso_hour(fetched_at),
        "forecast_valid_from": forecast_valid_from,
        "forecast_valid_from_hour": _iso_hour(forecast_valid_from),
        "forecast_valid_until": forecast_valid_until,
        "forecast_valid_until_hour": _iso_hour(forecast_valid_until),
        "warning_valid_from": warning_valid_from,
        "warning_valid_from_hour": _iso_hour(warning_valid_from),
        "warning_valid_until": warning_valid_until,
        "warning_valid_until_hour": _iso_hour(warning_valid_until),
        "latest_observation_at": latest_observation_at,
        "latest_observation_at_hour": _iso_hour(latest_observation_at),
        "valid_from": valid_from,
        "valid_from_hour": _iso_hour(valid_from),
        "valid_to": valid_until,
        "valid_to_hour": _iso_hour(valid_until),
        "valid_until": valid_until,
        "valid_until_hour": _iso_hour(valid_until),
        "time_precision": "hour",
        "timezone": "UTC",
        "time_metadata_required": True,
    }
    return metadata


def _extract_cwa_time_metadata(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    for key in ("cwa_time_metadata", "temporal_coverage"):
        value = payload.get(key)
        if isinstance(value, dict):
            cwa_value = value.get("cwa")
            return dict(cwa_value if isinstance(cwa_value, dict) else value)
    keys = (
        "request_timestamp",
        "request_timestamp_hour",
        "generated_at_hour",
        "api_request_attempted",
        "api_request_attempted_at",
        "api_request_attempted_at_hour",
        "api_fetched_at",
        "api_fetched_at_hour",
        "fetched_at",
        "fetched_at_hour",
        "forecast_valid_from",
        "forecast_valid_from_hour",
        "forecast_valid_until",
        "forecast_valid_until_hour",
        "warning_valid_from",
        "warning_valid_from_hour",
        "warning_valid_until",
        "warning_valid_until_hour",
        "latest_observation_at",
        "latest_observation_at_hour",
        "valid_from",
        "valid_from_hour",
        "valid_to",
        "valid_to_hour",
        "valid_until",
        "valid_until_hour",
        "time_precision",
        "timezone",
        "time_metadata_required",
    )
    metadata = {key: payload.get(key) for key in keys if key in payload}
    return metadata if metadata else {}


def _project_cwa_time_metadata(
    *,
    project_root: Path,
    project: dict[str, Any],
    fallback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if isinstance(fallback, dict) and fallback:
        return dict(fallback)
    for ref_key in (
        "cwa_weather_evidence_ref",
        "cwa_qpf_corridor_summary_ref",
        "cwa_qpf_grid_ref",
        "cwa_forecast_timeline_ref",
    ):
        payload = _load_project_ref_if_exists(project_root, project, ref_key)
        metadata = _extract_cwa_time_metadata(payload)
        if metadata:
            return metadata
    return {}


def _safe_exception_summary(exc: Exception) -> dict[str, Any]:
    return {
        "error_type": type(exc).__name__,
        "http_status": getattr(exc, "code", None),
        "reason": str(getattr(exc, "reason", "") or getattr(exc, "msg", "") or ""),
        "secret_value_embedded": False,
    }


def _environment_boundary(*, external_calls_made: bool) -> dict[str, Any]:
    return {
        "candidate_only": True,
        "pretrip_candidate_evidence_only": True,
        "runtime_safety_truth": False,
        "phase1_runtime_mutation_allowed": False,
        "phase2_brain_writeback_allowed": False,
        "source_mutation_allowed": False,
        "external_api_calls_made": external_calls_made,
        "secret_value_embedded": False,
    }


def _cwa_no_cache_policy() -> dict[str, Any]:
    return {
        "cacheable": False,
        "ttl_seconds": 0,
        "must_refetch_on_prepare": True,
        "reuse_previous_values": False,
        "artifact_role": "current_run_evidence_snapshot",
        "reason": (
            "CWA weather, warning, observation, and QPF evidence is "
            "time-sensitive and must be refetched during every explicit map "
            "preparation run."
        ),
    }


def _feature_collection(
    artifact_kind: str,
    features: list[dict[str, Any]],
    *,
    project_id: str,
    generated_at: str,
    bbox: dict[str, float],
    external_calls_made: bool = False,
) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "artifact_kind": artifact_kind,
        "schema_version": LAYER_PREPARATION_VERSION,
        "project_id": project_id,
        "generated_at": generated_at,
        "bbox_wgs84": bbox,
        "feature_count": len(features),
        "features": features,
        "boundary": _environment_boundary(external_calls_made=external_calls_made),
    }


def _environment_status_feature(
    *,
    bbox: dict[str, float],
    layer_id: str,
    label: str,
    status: str,
    provider: str,
    source_run_id: str,
    prepared_at: str,
    detail: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    lat, lon = _bbox_center(bbox)
    return {
        "type": "Feature",
        "id": f"{layer_id}.status",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "source_id": f"{layer_id}.status",
            "layer_id": layer_id,
            "label": label,
            "status": status,
            "provider": provider,
            "source_run_id": source_run_id,
            "prepared_at": prepared_at,
            "detail": detail,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "secret_value_embedded": False,
            **(extra or {}),
        },
    }


def _bbox_center(bbox: dict[str, float]) -> tuple[float, float]:
    return (
        (float(bbox["south"]) + float(bbox["north"])) / 2.0,
        (float(bbox["west"]) + float(bbox["east"])) / 2.0,
    )


def _point_in_bbox(lat: float, lon: float, bbox: dict[str, float]) -> bool:
    return (
        float(bbox["south"]) <= lat <= float(bbox["north"])
        and float(bbox["west"]) <= lon <= float(bbox["east"])
    )


def _normalize_cwa_rain_observations(
    payload: dict[str, Any],
    *,
    bbox: dict[str, float],
    source_run_id: str,
) -> list[dict[str, Any]]:
    expanded_bbox = _expand_bbox_by_meters(bbox, 100_000.0)
    records = payload.get("records") if isinstance(payload.get("records"), dict) else {}
    stations = records.get("Station") or records.get("station") or []
    if not isinstance(stations, list):
        return []
    observations: list[dict[str, Any]] = []
    for index, station in enumerate(stations):
        if not isinstance(station, dict):
            continue
        coordinate = _cwa_station_coordinate(station)
        if coordinate is None:
            continue
        lat, lon = coordinate
        if not _point_in_bbox(lat, lon, expanded_bbox):
            continue
        rainfall = (
            station.get("RainfallElement")
            if isinstance(station.get("RainfallElement"), dict)
            else {}
        )
        obs_time = (
            station.get("ObsTime")
            if isinstance(station.get("ObsTime"), dict)
            else {}
        )
        station_name = str(
            station.get("StationName")
            or station.get("stationName")
            or station.get("StationID")
            or f"CWA rain station {index + 1}"
        )
        observations.append(
            {
                "source": "O-A0002-001",
                "source_run_id": source_run_id,
                "station_id": str(station.get("StationID") or station.get("stationID") or ""),
                "station_name": station_name,
                "label": station_name,
                "lat": lat,
                "lon": lon,
                "obs_time": obs_time.get("DateTime") or obs_time.get("dateTime"),
                "last_10m_mm": _as_float(
                    rainfall.get("Past10Min") or rainfall.get("past10Min")
                ),
                "last_1h_mm": _as_float(
                    rainfall.get("Past1hr")
                    or rainfall.get("Past1H")
                    or rainfall.get("past1hr")
                ),
                "last_3h_mm": _as_float(
                    rainfall.get("Past3hr")
                    or rainfall.get("Past3H")
                    or rainfall.get("past3hr")
                ),
                "last_24h_mm": _as_float(
                    rainfall.get("Past24hr")
                    or rainfall.get("Past24H")
                    or rainfall.get("past24hr")
                ),
                "status": "observed",
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )
    observations.sort(
        key=lambda item: (
            item.get("last_24h_mm") or 0.0,
            item.get("last_3h_mm") or 0.0,
            item.get("last_1h_mm") or 0.0,
        ),
        reverse=True,
    )
    return observations[:120]


def _cwa_station_coordinate(station: dict[str, Any]) -> tuple[float, float] | None:
    geo = station.get("GeoInfo") if isinstance(station.get("GeoInfo"), dict) else {}
    for raw in geo.get("Coordinates") or geo.get("coordinates") or []:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("CoordinateName") or raw.get("coordinateName") or "").upper()
        if "WGS" not in name and name:
            continue
        lat = _as_float(
            raw.get("StationLatitude")
            or raw.get("stationLatitude")
            or raw.get("Latitude")
            or raw.get("lat")
        )
        lon = _as_float(
            raw.get("StationLongitude")
            or raw.get("stationLongitude")
            or raw.get("Longitude")
            or raw.get("lon")
        )
        if lat is not None and lon is not None:
            return lat, lon
    lat = _as_float(
        geo.get("StationLatitude")
        or geo.get("stationLatitude")
        or station.get("lat")
        or station.get("latitude")
    )
    lon = _as_float(
        geo.get("StationLongitude")
        or geo.get("stationLongitude")
        or station.get("lon")
        or station.get("longitude")
    )
    if lat is None or lon is None:
        return None
    return lat, lon


def _cwa_observation_features(
    observations: list[dict[str, Any]],
    *,
    time_metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    for index, observation in enumerate(observations):
        lat = _as_float(observation.get("lat"))
        lon = _as_float(observation.get("lon"))
        if lat is None or lon is None:
            continue
        features.append(
            {
                "type": "Feature",
                "id": observation.get("station_id") or f"cwa.rain.{index:03d}",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    **observation,
                    "source_id": observation.get("station_id") or f"cwa.rain.{index:03d}",
                    "layer_id": "cwa-weather",
                    "provider": "cwa_opendata",
                    "evidence_type": "cwa_rain_observation",
                    "api_fetched_at": time_metadata.get("api_fetched_at"),
                    "api_fetched_at_hour": time_metadata.get("api_fetched_at_hour"),
                    "fetched_at": time_metadata.get("fetched_at"),
                    "fetched_at_hour": time_metadata.get("fetched_at_hour"),
                    "cwa_time_metadata": time_metadata,
                    "obs_time_hour": _iso_hour(observation.get("obs_time")),
                    "source_observed_at": observation.get("obs_time"),
                    "source_observed_at_hour": _iso_hour(observation.get("obs_time")),
                    "time_precision": "hour",
                },
            }
        )
    return features


def _cwa_qpf_features_from_weather_points(
    weather_points: list[dict[str, Any]],
    *,
    bbox: dict[str, float],
    source_run_id: str,
    prepared_at: str,
    time_metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    if not weather_points:
        return []
    preferred = [
        point
        for point in weather_points
        if any(
            token in str(point.get("areaName") or point.get("county") or "")
            for token in ("南投", "花蓮", "仁愛", "秀林", "萬榮")
        )
    ]
    selected = preferred or weather_points[:4]
    by_area: dict[str, dict[str, Any]] = {}
    for point in selected:
        area = str(point.get("areaName") or point.get("county") or "CWA forecast")
        current = by_area.get(area)
        pop = _as_float(point.get("rainProbability")) or 0.0
        if current is None or pop > (_as_float(current.get("rainProbability")) or 0.0):
            by_area[area] = point

    lat_center, lon_center = _bbox_center(bbox)
    lat_span = max(float(bbox["north"]) - float(bbox["south"]), 0.01)
    lon_span = max(float(bbox["east"]) - float(bbox["west"]), 0.01)
    features: list[dict[str, Any]] = []
    for index, (area, point) in enumerate(sorted(by_area.items())[:6]):
        col = (index % 3) - 1
        row = (index // 3) - 0.5
        lat = min(max(lat_center + row * lat_span * 0.10, bbox["south"]), bbox["north"])
        lon = min(max(lon_center + col * lon_span * 0.10, bbox["west"]), bbox["east"])
        rain_probability = _as_float(point.get("rainProbability"))
        weather_text = point.get("weatherText") or point.get("weather")
        features.append(
            {
                "type": "Feature",
                "id": f"cwa.qpf.{index:03d}",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "source_id": f"cwa.qpf.{index:03d}",
                    "source": point.get("source") or "F-C0032-001",
                    "source_run_id": source_run_id,
                    "layer_id": "cwa-qpf",
                    "provider": "cwa_opendata",
                    "evidence_type": "cwa_forecast_derived_qpf_candidate",
                    "label": f"CWA QPF {area}",
                    "area_name": area,
                    "status": "forecast_derived",
                    "rain_probability": rain_probability,
                    "rainfall_mm": _as_float(point.get("rainfallMm")),
                    "weather_text": weather_text,
                    "valid_from": point.get("validFrom"),
                    "valid_from_hour": _iso_hour(point.get("validFrom")),
                    "valid_to": point.get("validTo"),
                    "valid_to_hour": _iso_hour(point.get("validTo")),
                    "valid_until": point.get("validTo"),
                    "valid_until_hour": _iso_hour(point.get("validTo")),
                    "prepared_at": prepared_at,
                    "generated_at_hour": _iso_hour(prepared_at),
                    "model_inference_generated_at": prepared_at,
                    "model_inference_generated_at_hour": _iso_hour(prepared_at),
                    "api_request_attempted_at": time_metadata.get(
                        "api_request_attempted_at"
                    ),
                    "api_request_attempted_at_hour": time_metadata.get(
                        "api_request_attempted_at_hour"
                    ),
                    "api_fetched_at": time_metadata.get("api_fetched_at"),
                    "api_fetched_at_hour": time_metadata.get("api_fetched_at_hour"),
                    "fetched_at": time_metadata.get("fetched_at"),
                    "fetched_at_hour": time_metadata.get("fetched_at_hour"),
                    "cwa_time_metadata": time_metadata,
                    "time_precision": "hour",
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                    "qpf_direct_grid": False,
                    "qpf_source_note": "Forecast-derived candidate from CWA forecast/rain evidence.",
                },
            }
        )
    return features


def _cwa_warning_features(
    warnings: list[dict[str, Any]],
    *,
    bbox: dict[str, float],
    source_run_id: str,
    time_metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    lat, lon = _bbox_center(bbox)
    features: list[dict[str, Any]] = []
    for index, warning in enumerate(warnings[:40]):
        features.append(
            {
                "type": "Feature",
                "id": warning.get("warning_id") or f"cwa.warning.{index:03d}",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    **warning,
                    "source_id": warning.get("warning_id")
                    or f"cwa.warning.{index:03d}",
                    "source_run_id": warning.get("source_run_id") or source_run_id,
                    "layer_id": "cwa-weather",
                    "provider": "cwa_opendata",
                    "evidence_type": "cwa_weather_warning",
                    "label": warning.get("headline") or "CWA weather warning",
                    "valid_from_hour": _iso_hour(warning.get("valid_from")),
                    "valid_to_hour": _iso_hour(warning.get("valid_to")),
                    "valid_until": warning.get("valid_to"),
                    "valid_until_hour": _iso_hour(warning.get("valid_to")),
                    "api_fetched_at": time_metadata.get("api_fetched_at"),
                    "api_fetched_at_hour": time_metadata.get("api_fetched_at_hour"),
                    "fetched_at": time_metadata.get("fetched_at"),
                    "fetched_at_hour": time_metadata.get("fetched_at_hour"),
                    "cwa_time_metadata": time_metadata,
                    "time_precision": "hour",
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                },
            }
        )
    return features


def _cwa_qpf_timeline(
    features: list[dict[str, Any]],
    *,
    project_id: str,
    generated_at: str,
    time_metadata: dict[str, Any],
    external_calls_made: bool,
) -> dict[str, Any]:
    items = []
    for feature in features:
        props = feature.get("properties", {})
        items.append(
            {
                "event_id": props.get("source_id"),
                "label": props.get("label"),
                "valid_from": props.get("valid_from"),
                "valid_from_hour": props.get("valid_from_hour"),
                "valid_to": props.get("valid_to"),
                "valid_to_hour": props.get("valid_to_hour"),
                "valid_until": props.get("valid_until"),
                "valid_until_hour": props.get("valid_until_hour"),
                "rain_probability": props.get("rain_probability"),
                "rainfall_mm": props.get("rainfall_mm"),
                "weather_text": props.get("weather_text"),
                "api_fetched_at": props.get("api_fetched_at"),
                "api_fetched_at_hour": props.get("api_fetched_at_hour"),
                "cwa_time_metadata": time_metadata,
                "model_inference_generated_at": props.get("model_inference_generated_at"),
                "model_inference_generated_at_hour": props.get(
                    "model_inference_generated_at_hour"
                ),
                "time_precision": "hour",
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )
    return {
        "artifact_kind": "cwa_qpf_route_timeline",
        "schema_version": LAYER_PREPARATION_VERSION,
        "project_id": project_id,
        "generated_at": generated_at,
        "request_timestamp": generated_at,
        **time_metadata,
        "item_count": len(items),
        "items": items,
        "boundary": _environment_boundary(external_calls_made=external_calls_made),
    }


def _cwa_qpf_corridor_summary(
    features: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    *,
    project_id: str,
    route_summary: dict[str, Any],
    generated_at: str,
    bbox: dict[str, float],
    time_metadata: dict[str, Any],
    external_calls_made: bool,
) -> dict[str, Any]:
    rain_probabilities = [
        value
        for feature in features
        if (value := _as_float(feature.get("properties", {}).get("rain_probability")))
        is not None
    ]
    observed_24h = [
        value
        for observation in observations
        if (value := _as_float(observation.get("last_24h_mm"))) is not None
    ]
    return {
        "artifact_kind": "cwa_qpf_corridor_summary",
        "schema_version": LAYER_PREPARATION_VERSION,
        "project_id": project_id,
        "route_name": route_summary.get("route_name"),
        "generated_at": generated_at,
        "request_timestamp": generated_at,
        **time_metadata,
        "bbox_wgs84": bbox,
        "status": "ready" if features or observations else "not_available",
        "counts": {
            "qpf_feature_count": len(features),
            "rain_observation_count": len(observations),
        },
        "max_rain_probability": max(rain_probabilities) if rain_probabilities else None,
        "max_observed_24h_mm": max(observed_24h) if observed_24h else None,
        "mean_observed_24h_mm": statistics.mean(observed_24h) if observed_24h else None,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "boundary": _environment_boundary(external_calls_made=external_calls_made),
    }


def _cwa_forecast_timeline(
    weather_points: list[dict[str, Any]],
    *,
    project_id: str,
    generated_at: str,
    time_metadata: dict[str, Any],
    external_calls_made: bool,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    for index, point in enumerate(weather_points[:120]):
        event = {
            "event_id": f"cwa.forecast.{index:03d}",
            "event": "township_or_area_forecast",
            "dataset_id": point.get("source") or "F-C0032-001",
            "area_name": point.get("areaName") or point.get("county"),
            "valid_from": point.get("validFrom"),
            "valid_from_hour": _iso_hour(point.get("validFrom")),
            "valid_to": point.get("validTo"),
            "valid_to_hour": _iso_hour(point.get("validTo")),
            "valid_until": point.get("validTo"),
            "valid_until_hour": _iso_hour(point.get("validTo")),
            "rain_probability_percent": point.get("rainProbability"),
            "rainfall_mm": point.get("rainfallMm"),
            "weather_text": point.get("weatherText") or point.get("weather"),
            "api_fetched_at": time_metadata.get("api_fetched_at"),
            "api_fetched_at_hour": time_metadata.get("api_fetched_at_hour"),
            "cwa_time_metadata": time_metadata,
            "time_precision": "hour",
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
        events.append({key: value for key, value in event.items() if value is not None})
    return {
        "artifact_kind": "cwa_forecast_timeline",
        "schema_version": LAYER_PREPARATION_VERSION,
        "project_id": project_id,
        "generated_at": generated_at,
        "request_timestamp": generated_at,
        **time_metadata,
        "dataset_ids": sorted(
            {str(point.get("source") or "F-C0032-001") for point in weather_points}
        ),
        "raw_response_hash": f"sha256:{_stable_projection_hash(weather_points)}",
        "status": "ready" if events else "not_available",
        "stale_risk": "low" if external_calls_made else "missing_source",
        "event_count": len(events),
        "events": events,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "boundary": _environment_boundary(external_calls_made=external_calls_made),
    }


def _cwa_astronomy_timeline(
    *,
    project_id: str,
    generated_at: str,
    time_metadata: dict[str, Any],
    external_calls_made: bool,
) -> dict[str, Any]:
    event = {
        "event": "not_available_in_current_preparation",
        "reason": (
            "No CWA astronomy adapter is configured in this preparation step; "
            "use weather_daylight_evidence for daylight review until a CWA "
            "astronomy fetcher is wired."
        ),
        "api_fetched_at": time_metadata.get("api_fetched_at"),
        "api_fetched_at_hour": time_metadata.get("api_fetched_at_hour"),
        "cwa_time_metadata": time_metadata,
        "generated_at": generated_at,
        "generated_at_hour": _iso_hour(generated_at),
        "time_precision": "hour",
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    return {
        "artifact_kind": "cwa_astronomy_timeline",
        "schema_version": LAYER_PREPARATION_VERSION,
        "project_id": project_id,
        "generated_at": generated_at,
        "request_timestamp": generated_at,
        **time_metadata,
        "dataset_ids": ["A-B0062-001", "A-B0063-001"],
        "raw_response_hash": f"sha256:{_stable_projection_hash(event)}",
        "status": "not_available",
        "stale_risk": "low",
        "events": [event],
        "candidate_only": True,
        "runtime_safety_truth": False,
        "boundary": _environment_boundary(external_calls_made=external_calls_made),
    }


def _cwa_tide_marine_timeline(
    *,
    project_id: str,
    generated_at: str,
    time_metadata: dict[str, Any],
    external_calls_made: bool,
) -> dict[str, Any]:
    event = {
        "event": "not_applicable_inland_route",
        "reason": "Current route is treated as inland mountain pretrip planning.",
        "api_fetched_at": time_metadata.get("api_fetched_at"),
        "api_fetched_at_hour": time_metadata.get("api_fetched_at_hour"),
        "cwa_time_metadata": time_metadata,
        "generated_at": generated_at,
        "generated_at_hour": _iso_hour(generated_at),
        "time_precision": "hour",
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    return {
        "artifact_kind": "cwa_tide_marine_timeline",
        "schema_version": LAYER_PREPARATION_VERSION,
        "project_id": project_id,
        "generated_at": generated_at,
        "request_timestamp": generated_at,
        **time_metadata,
        "dataset_ids": ["F-A0021-001", "O-B0075-001"],
        "raw_response_hash": f"sha256:{_stable_projection_hash(event)}",
        "status": "not_applicable",
        "stale_risk": "low",
        "events": [event],
        "candidate_only": True,
        "runtime_safety_truth": False,
        "boundary": _environment_boundary(external_calls_made=external_calls_made),
    }


def _gee_gpm_imerg_raw_summary(
    *,
    raw_summary: dict[str, Any],
    project_id: str,
    generated_at: str,
    status: str,
    blockers: list[str],
    external_calls_made: bool,
    cache_policy: dict[str, Any],
    raw_summary_ref: str,
    raw_summary_sha256: str,
) -> dict[str, Any]:
    response = (
        (raw_summary.get("responses") or {}).get("gpm_imerg_precipitation")
        if isinstance(raw_summary.get("responses"), dict)
        else None
    )
    result = response.get("result") if isinstance(response, dict) else {}
    image_count = result.get("image_count") if isinstance(result, dict) else None
    return {
        "artifact_kind": "gee_gpm_imerg_raw_summary",
        "schema_version": LAYER_PREPARATION_VERSION,
        "project_id": project_id,
        "provider": "google_earth_engine",
        "collection_id": "NASA/GPM_L3/IMERG_V07",
        "generated_at": generated_at,
        "request_timestamp": generated_at,
        "request_timestamp_hour": _iso_hour(generated_at),
        "api_fetched_at": generated_at if external_calls_made else None,
        "api_fetched_at_hour": _iso_hour(generated_at) if external_calls_made else None,
        "status": status,
        "blocker_reasons": blockers,
        "image_count": image_count,
        "source_raw_summary_ref": raw_summary_ref,
        "source_raw_summary_sha256": raw_summary_sha256,
        "raw_response_hash": f"sha256:{raw_summary_sha256}",
        "cache_policy": cache_policy,
        "stale_risk": "low" if external_calls_made else "missing_source",
        "candidate_only": True,
        "runtime_safety_truth": False,
        "secret_value_embedded": False,
        "boundary": _environment_boundary(external_calls_made=external_calls_made),
    }


def _gee_environment_summary(
    *,
    project_id: str,
    layer_id: str,
    generated_at: str,
    bbox: dict[str, float],
    gee_status: dict[str, Any],
    dataset_catalog: list[dict[str, Any]],
    status: str,
    blockers: list[str],
    external_calls_made: bool,
    raw_summary_ref: str,
    raw_summary_sha256: str,
    cache_policy: dict[str, Any],
    values: dict[str, Any],
) -> dict[str, Any]:
    return {
        "artifact_kind": f"gee_{layer_id.replace('-', '_')}_corridor_summary",
        "schema_version": LAYER_PREPARATION_VERSION,
        "project_id": project_id,
        "layer_id": layer_id,
        "generated_at": generated_at,
        "bbox_wgs84": bbox,
        "status": status,
        "blocker_reasons": blockers,
        "raw_summary_ref": raw_summary_ref,
        "raw_summary_sha256": raw_summary_sha256,
        "cache_policy": cache_policy,
        "values": values,
        "gee_runtime_status": gee_status,
        "dataset_catalog": dataset_catalog,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "human_review_required": True,
        "external_api_calls_made": external_calls_made,
        "boundary": _environment_boundary(external_calls_made=external_calls_made),
    }


def _blocked_gee_feature_package(
    *,
    project_id: str,
    prepared_at: str,
    status: str,
    blockers: list[str],
) -> dict[str, Any]:
    return {
        "artifact_kind": "scout_gee_feature_package",
        "schema_version": "scout_gee_feature_package.v0.1",
        "project_id": project_id,
        "generated_at": prepared_at,
        "status": status,
        "provider": "google_earth_engine",
        "server_side_only": True,
        "mobile_runtime_dependency": False,
        "raspberry_pi_runtime_dependency": False,
        "segments": [],
        "source_datasets": [],
        "stale_data_warnings": [],
        "blocker_reasons": list(blockers),
        "counts": {
            "route_point_count": 0,
            "segment_count": 0,
            "raw_segment_feature_count": 0,
            "stale_warning_count": 0,
        },
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "phase1_runtime_mutation_allowed": False,
            "mobile_runtime_gee_dependency": False,
            "raspberry_pi_runtime_gee_dependency": False,
            "external_api_calls_made": False,
            "server_side_export_required": True,
            "compact_route_feature_package": True,
        },
    }


def _gee_timeseries_placeholder(
    *,
    project_id: str,
    layer_id: str,
    generated_at: str,
    status: str,
    blockers: list[str],
    cache_policy: dict[str, Any],
    external_calls_made: bool = False,
) -> dict[str, Any]:
    return {
        "artifact_kind": f"gee_{layer_id.replace('-', '_')}_timeseries",
        "schema_version": LAYER_PREPARATION_VERSION,
        "project_id": project_id,
        "layer_id": layer_id,
        "generated_at": generated_at,
        "status": status,
        "samples": [],
        "blocker_reasons": blockers,
        "cache_policy": cache_policy,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "human_review_required": True,
        "external_api_calls_made": external_calls_made,
        "boundary": _environment_boundary(external_calls_made=external_calls_made),
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
    if layer_id == "mcp":
        candidates = payload.get("mcp_candidates")
        return {
            "mcp_candidate_count": len(candidates) if isinstance(candidates, list) else 0
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
            f'  way["highway"~"{ROUTE_CORRIDOR_HIGHWAY_PATTERN}"]{bbox_expr};',
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


def _extract_osm_pbf_raw_payload(
    *,
    pbf_path: Path,
    bbox: dict[str, float],
    raw_payload_path: Path,
    osmium_bin: str,
) -> tuple[bytes, dict[str, Any]]:
    return extract_osm_pbf_to_osm_json(
        pbf_path=pbf_path,
        bbox_wgs84=bbox,
        raw_osm_json_path=raw_payload_path,
        osmium_bin=osmium_bin,
    )


def _osm_pbf_cache_metadata(
    pbf_path: Path,
    *,
    source_url: str | None,
    ttl_days: int,
    now_iso: str,
) -> dict[str, Any]:
    if ttl_days <= 0:
        raise ValueError("osm_pbf_cache_ttl_days must be greater than 0")
    stat = pbf_path.stat()
    now = _parse_iso_datetime(now_iso)
    file_modified_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
    expires_at = file_modified_at + timedelta(days=ttl_days)
    age_seconds = max(0.0, (now - file_modified_at).total_seconds())
    refresh_required = now > expires_at
    return {
        "cache_policy": "download_once_reuse_until_ttl_expires",
        "cache_ttl_days": ttl_days,
        "cache_ttl_seconds": ttl_days * 24 * 60 * 60,
        "cache_status": (
            "stale_refresh_recommended" if refresh_required else "fresh"
        ),
        "refresh_required": refresh_required,
        "source_url": source_url,
        "source_url_semantics": "latest_at_download_time",
        "local_path": pbf_path.as_posix(),
        "file_modified_at": file_modified_at.isoformat(),
        "downloaded_at": file_modified_at.isoformat(),
        "age_days": round(age_seconds / (24 * 60 * 60), 3),
        "checked_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "notes": (
            "taiwan-latest.osm.pbf is treated as a local snapshot. Scout "
            "reuses it within the TTL and only marks refresh_required after "
            "the TTL expires."
        ),
    }


def _local_osm_render_extract_metadata(
    *,
    project_root: Path,
    extraction_plan: dict[str, Any],
    raw_payload_ref: str,
    raw_payload: dict[str, Any],
    pbf_cache: dict[str, Any],
) -> dict[str, Any]:
    pbf_extract_ref: str | None = None
    extracted_pbf_path_value = extraction_plan.get("extracted_pbf_path")
    if isinstance(extracted_pbf_path_value, str) and extracted_pbf_path_value:
        extracted_pbf_path = Path(extracted_pbf_path_value)
        if extracted_pbf_path.is_file():
            try:
                pbf_extract_ref = extracted_pbf_path.resolve().relative_to(
                    project_root.resolve()
                ).as_posix()
            except ValueError:
                pbf_extract_ref = extracted_pbf_path.resolve().as_posix()
    preferred_ref = pbf_extract_ref or raw_payload_ref
    preferred_kind = (
        "local_osm_pbf_route_bbox_extract"
        if pbf_extract_ref
        else "local_osm_filtered_osmjson_extract"
    )
    feature_count = len(raw_payload.get("elements", []))
    manifest_ref = "normalized/map/osm_pbf_render_extract_manifest.json"
    manifest = {
        "artifact_kind": "pretrip_local_osm_render_extract_manifest",
        "schema_version": LAYER_PREPARATION_VERSION,
        "status": "ready",
        "preferred_render_source_ref": preferred_ref,
        "preferred_render_source_kind": preferred_kind,
        "pbf_extract_ref": pbf_extract_ref,
        "osmjson_extract_ref": raw_payload_ref,
        "feature_count": feature_count,
        "source_plan": extraction_plan,
        "pbf_cache": pbf_cache,
        "rendering_scope": "route_bbox_osm_vector_extract",
        "candidate_only": True,
        "runtime_safety_truth": False,
        "notes": (
            "Small workspace-local OSM extract prepared from the cached Taiwan "
            "PBF. It can support future OSM layer vector rendering without "
            "reading the full-region PBF at render time."
        ),
    }
    _write_json(project_root / manifest_ref, manifest)
    return {
        "manifest_ref": manifest_ref,
        "preferred_render_source_ref": preferred_ref,
        "preferred_render_source_kind": preferred_kind,
        "pbf_extract_ref": pbf_extract_ref,
        "feature_count": feature_count,
    }


def _export_local_osm_render_geojson(
    *,
    project_root: Path,
    extraction_plan: dict[str, Any],
    osmium_bin: str,
    raw_payload: dict[str, Any] | None = None,
    raw_payload_ref: str | None = None,
) -> dict[str, Any] | None:
    extracted_pbf_path_value = extraction_plan.get("extracted_pbf_path")
    output_ref = "normalized/map/osm_pbf_route_bbox_full.geojson"
    output_path = project_root / output_ref
    if not isinstance(extracted_pbf_path_value, str) or not extracted_pbf_path_value:
        return _export_osmjson_render_geojson(
            output_path=output_path,
            output_ref=output_ref,
            raw_payload=raw_payload,
            raw_payload_ref=raw_payload_ref,
        )
    extracted_pbf_path = Path(extracted_pbf_path_value)
    if not extracted_pbf_path.is_file():
        return _export_osmjson_render_geojson(
            output_path=output_path,
            output_ref=output_ref,
            raw_payload=raw_payload,
            raw_payload_ref=raw_payload_ref,
        )
    osmium_path = Path(osmium_bin).expanduser()
    if not osmium_path.is_file() and shutil.which(osmium_bin) is None:
        return _export_osmjson_render_geojson(
            output_path=output_path,
            output_ref=output_ref,
            raw_payload=raw_payload,
            raw_payload_ref=raw_payload_ref,
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        osmium_bin,
        "export",
        "--overwrite",
        "--output-format",
        "geojson",
        "--geometry-types",
        "point,linestring,polygon",
        "--attributes",
        "type,id",
        "--output",
        output_path.as_posix(),
        extracted_pbf_path.as_posix(),
    ]
    try:
        subprocess.run(
            command,
            check=True,
            cwd=project_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return _export_osmjson_render_geojson(
            output_path=output_path,
            output_ref=output_ref,
            raw_payload=raw_payload,
            raw_payload_ref=raw_payload_ref,
        )
    if not output_path.is_file():
        return _export_osmjson_render_geojson(
            output_path=output_path,
            output_ref=output_ref,
            raw_payload=raw_payload,
            raw_payload_ref=raw_payload_ref,
        )
    try:
        payload = _load_json(output_path)
    except (OSError, json.JSONDecodeError):
        return _export_osmjson_render_geojson(
            output_path=output_path,
            output_ref=output_ref,
            raw_payload=raw_payload,
            raw_payload_ref=raw_payload_ref,
        )
    return {
        "ref": output_ref,
        "path": output_path,
        "payload": payload,
        "command": command,
    }


def _export_osmjson_render_geojson(
    *,
    output_path: Path,
    output_ref: str,
    raw_payload: dict[str, Any] | None,
    raw_payload_ref: str | None,
) -> dict[str, Any] | None:
    if raw_payload is None:
        return None
    payload = osm_json_to_geojson_feature_collection(raw_payload)
    payload.setdefault("properties", {})
    payload["properties"].update(
        {
            "render_source_ref": raw_payload_ref,
            "render_source_kind": "local_osm_pbf_osmjson_extract",
        }
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(output_path, payload)
    return {
        "ref": output_ref,
        "path": output_path,
        "payload": payload,
        "command": None,
    }


def _write_planned_overpass_evidence(
    project_root: Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    overpass_layer = _layer_by_id(manifest, "overpass")
    layer_status = overpass_layer.get("status")
    if layer_status != "planned_no_network":
        source_refs = manifest["inputs"].get("source_refs", {})
        existing_ref_record = source_refs.get("overpass_evidence_ref", {})
        existing_ref = (
            existing_ref_record.get("ref")
            if isinstance(existing_ref_record, dict)
            else None
        )
        existing_path = project_root / existing_ref if isinstance(existing_ref, str) else None
        if layer_status != "ready_from_project_ref" or existing_path is None:
            return {}
        existing_payload = _load_json(existing_path) if existing_path.exists() else {}
        if existing_payload.get("status") != "planned_no_network":
            return {}
    planned_request = overpass_layer.get("planned_request")
    if not isinstance(planned_request, dict):
        return {}

    evidence_ref = "candidates/overpass_evidence.json"
    normalized_ref = str(
        overpass_layer.get("output_refs", {}).get("normalized_geojson_ref")
        or OUTPUT_REFS["overpass_vector_evidence_ref"]
    )
    evidence = {
        "artifact_kind": "pretrip_overpass_evidence",
        "schema_version": "route_corridor_map_preparation.v1",
        "project_id": manifest["project_id"],
        "status": "planned_no_network",
        "source_artifact": {
            "artifact_id": f"overpass.planned.{manifest['project_id']}",
            "artifact_kind": "pretrip_overpass_query_plan",
            "source_kind": "overpass_query_plan",
            "source_ref": planned_request["query_body_ref"],
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
        "request": {
            "endpoint": planned_request.get("endpoint"),
            "query_body_ref": planned_request.get("query_body_ref"),
            "query_body_sha256": hashlib.sha256(
                str(planned_request.get("query_body", "")).encode("utf-8")
            ).hexdigest(),
            "raw_response_sha256": None,
            "conversion_rule_version": "planned_no_network",
            "route_corridor": manifest["route_corridor"],
            "network_calls_made": False,
        },
        "object_evidence": [],
        "skipped_objects": [],
        "candidates": [],
        "counts": {
            "candidates": 0,
            "skipped": 0,
            "feature_count": 0,
            "network_calls_made": 0,
        },
        "normalized_geojson_ref": normalized_ref,
        "source_refs": [
            {
                "ref": planned_request["query_body_ref"],
                "source_kind": "overpass_query_plan",
                "external_network_required": False,
                "network_calls_made": False,
            }
        ],
        "boundary": {
            "candidate_only": True,
            "runtime_truth": False,
            "runtime_safety_truth": False,
            "live_network_required": False,
            "network_mode": manifest["network_policy"]["network_mode"],
            "phase1_runtime_mutation_allowed": False,
            "phase2_brain_writeback_allowed": False,
        },
    }
    _write_json(project_root / evidence_ref, evidence)
    return {
        "overpass_evidence_ref": evidence_ref,
        "overpass_map_context_ref": normalized_ref,
        "overpass_query_ref": planned_request["query_body_ref"],
        "overpass_candidate_count": 0,
        "overpass_skipped_object_count": 0,
        "overpass_planned_at": manifest["finished_at"],
    }


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
        _overpass_vector_evidence_from_project(project_root, manifest),
    )
    _write_json(
        project_root / outputs["terrain_route_samples_ref"],
        _terrain_route_samples_from_project(project_root, manifest),
    )
    _write_json(
        project_root / outputs["terrain_visualization_ref"],
        _terrain_visualization_from_project(project_root, manifest),
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
    ocr_candidate_sources = _raster_label_ocr_candidate_sources()
    return {
        "artifact_kind": "pretrip_raster_label_plan",
        "schema_version": "route_corridor_map_preparation.v1",
        "project_id": manifest["project_id"],
        "source_id": manifest["job_id"] + ".raster_label_plan",
        "source_path": manifest["outputs"]["raster_label_plan_ref"],
        "status": "planned_for_map_preparation_ocr",
        "route_scope_ref": manifest["inputs"]["route_evidence_bundle"].get(
            "source_ref"
        ),
        "route_corridor": manifest["route_corridor"],
        "raster_source_refs": imagery_layer.get("source_refs", []),
        "ocr_candidate_sources": ocr_candidate_sources,
        "ocr_candidate_source_count": len(ocr_candidate_sources),
        "preferred_ocr_source_ids": list(RASTER_LABEL_PREFERRED_OCR_SOURCE_IDS),
        "label_extraction_targets": list(RASTER_LABEL_EXTRACTION_TARGETS),
        "mileage_anchor_grouping_policy": {
            key: list(value) if isinstance(value, tuple) else value
            for key, value in RASTER_LABEL_MILEAGE_ANCHOR_GROUPING_POLICY.items()
        },
        "raster_bbox_wgs84": imagery_layer.get("raster_bbox_wgs84"),
        "ocr_or_vision_performed": False,
        "imagery_processing_enabled": True,
        "tile_display_mode": "runtime_wmts",
        "ocr_engine": {
            "entrypoint": "pretrip_raster_label_ocr.py",
            "cli": (
                "python -m pretrip_raster_label_ocr "
                "--project-root <project_root> --tile-manifest <tile_plan_or_manifest>"
            ),
            "preferred_engine": "tesseract",
            "supported_engines": ["tesseract"],
            "mac_optional_engine": "apple_vision_pyobjc",
            "output_ref": RASTER_LABEL_OCR_OUTPUT_REF,
            "adapter_input_ref": RASTER_LABEL_OCR_OUTPUT_REF,
            "adapter_entrypoint": "pretrip_raster_label_adapter.py",
            "runtime_dependency_policy": (
                "if OCR runtime dependencies are missing, emit blocked_dependency_missing "
                "instead of fabricated OCR labels"
            ),
            "raw_tiles_embedded_in_output": False,
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
        "execution_policy": {
            "ocr_runs_as_map_preparation_stage": True,
            "ocr_requires_explicit_adapter_run": False,
            "ocr_engine_output_must_feed_adapter": True,
            "network_fetch_requires_explicit_fetch_mode": True,
            "raw_tiles_embedded_in_json": False,
            "preferred_role": "map_ocr_mileage_anchor_and_named_place_seed",
        },
        "notes_zh": [
            "Raster label OCR 是 map preparation 的內建階段；若缺少 OCR dependency 或 tile cache，會留下 blocked manifest。",
            "Rudy+TW / Rudy 圖磚優先作為里程 K、地名、等高線與路況標註的 OCR 候選來源。",
            "OCR 結果只能成為 CP/MCP/hazard/boss 的 pretrip candidate evidence，不能成為 runtime safety truth。",
        ],
        "output_ref": manifest["outputs"]["raster_label_evidence_ref"],
        "boundary": _map_preparation_candidate_boundary(manifest),
    }


def _raster_label_ocr_candidate_sources() -> list[dict[str, Any]]:
    registry = load_imagery_source_registry()
    sources = registry.get("sources") or {}
    candidates: list[dict[str, Any]] = []
    for source_id in RASTER_LABEL_PREFERRED_OCR_SOURCE_IDS:
        source = sources.get(source_id)
        if not isinstance(source, dict) or not source.get("ocr_capable"):
            continue
        candidates.append(
            {
                "source_id": source["source_id"],
                "label": source.get("label"),
                "label_zh": source.get("label_zh"),
                "provider": source.get("provider"),
                "source_kind": source.get("source_kind"),
                "ocr_capable": True,
                "label_extraction_roles": list(
                    source.get("label_extraction_roles") or ()
                ),
                "map_label_source_priority": source.get(
                    "map_label_source_priority"
                ),
                "map_label_evidence_policy": source.get(
                    "map_label_evidence_policy"
                ),
                "tile_order": source.get("tile_order"),
                "min_zoom": source.get("min_zoom"),
                "max_zoom": source.get("max_zoom"),
                "url_template_sha256": hashlib.sha256(
                    str(source.get("url_template") or "").encode("utf-8")
                ).hexdigest(),
                **wmts_source_metadata(source),
                "raw_url_template_embedded": False,
            }
        )
    return candidates


def _overpass_vector_evidence_from_project(
    project_root: Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    source_refs = manifest["inputs"]["source_refs"]
    map_ref_record = source_refs.get("overpass_map_context_ref", {})
    map_ref = map_ref_record.get("ref") if isinstance(map_ref_record, dict) else None
    if isinstance(map_ref, str) and map_ref and (project_root / map_ref).exists():
        payload = _load_json(project_root / map_ref)
        features = []
        type_counts: Counter[str] = Counter()
        for index, feature in enumerate(payload.get("features", [])):
            if not isinstance(feature, dict):
                continue
            properties = dict(feature.get("properties") or {})
            candidate_type = str(
                properties.get("candidate_type")
                or properties.get("feature_type")
                or "overpass_candidate"
            )
            type_counts[candidate_type] += 1
            features.append(
                {
                    "type": "Feature",
                    "geometry": feature.get("geometry"),
                    "properties": {
                        **properties,
                        "overpass_vector_evidence_id": properties.get("id")
                        or f"overpass.vector.{index + 1:06d}",
                        "evidence_type": "pretrip_overpass_vector_candidate",
                        "source_kind": "overpass_vector_evidence",
                        "source_overpass_map_context_ref": map_ref,
                        "route_scope_ref": manifest["inputs"][
                            "route_evidence_bundle"
                        ].get("source_ref"),
                        "candidate_only": True,
                        "requires_human_review": True,
                        "runtime_safety_truth": False,
                    },
                }
            )
        artifact = _empty_geojson_evidence_from_manifest(
            manifest,
            artifact_kind="pretrip_overpass_vector_evidence",
            evidence_type="pretrip_overpass_vector_candidate",
            status="ready_from_project_ref" if features else "empty_project_ref",
            source_plan_ref="outputs/layers/plans/overpass_query.ql",
        )
        artifact["features"] = features
        artifact["counts"] = {
            "feature_count": len(features),
            "candidate_count": len(features),
            "candidate_type_counts": dict(sorted(type_counts.items())),
            "runtime_safety_truth_count": 0,
        }
        artifact["source_refs"] = [
            ref
            for ref in (
                source_refs.get("overpass_evidence_ref"),
                map_ref_record,
                source_refs.get("overpass_raw_payload_ref"),
                source_refs.get("overpass_query_ref"),
            )
            if isinstance(ref, dict)
        ]
        artifact["boundary"] = {
            **artifact["boundary"],
            "pretrip_candidate_evidence_only": True,
            "runtime_safety_truth": False,
            "phase1_runtime_mutation_allowed": False,
        }
        return artifact

    return _empty_geojson_evidence_from_manifest(
        manifest,
        artifact_kind="pretrip_overpass_vector_evidence",
        evidence_type="pretrip_overpass_vector_candidate",
        status=_layer_status(manifest, "overpass"),
        source_plan_ref="outputs/layers/plans/overpass_query.ql",
    )


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
    risk_ref_key, risk_ref_record, risk_ref, risk_path = _terrain_source_ref(
        project_root,
        manifest,
    )
    if not isinstance(risk_ref, str) or not risk_ref:
        return _empty_geojson_evidence_from_manifest(
            manifest,
            artifact_kind="pretrip_terrain_route_samples",
            evidence_type="pretrip_terrain_route_sample",
            status=_layer_status(manifest, "terrain"),
            source_plan_ref=None,
        )
    if risk_path is None or not risk_path.exists():
        return _empty_geojson_evidence_from_manifest(
            manifest,
            artifact_kind="pretrip_terrain_route_samples",
            evidence_type="pretrip_terrain_route_sample",
            status="missing_risk_source",
            source_plan_ref=None,
        )
    payload = _load_json(risk_path)
    source_samples = _terrain_source_samples(payload)
    features = []
    for index, sample in enumerate(source_samples):
        properties = dict(sample.get("properties") or {})
        terrain_feature = {
            "type": "Feature",
            "geometry": sample.get("geometry"),
            "properties": {
                **properties,
                "terrain_sample_id": sample.get("sample_id")
                or properties.get("sample_id")
                or f"terrain_route_sample.{index + 1:06d}",
                "evidence_type": "pretrip_terrain_route_sample",
                "source_kind": "scout_risk_engine_terrain_sample",
                "source_risk_ref_key": risk_ref_key,
                "source_risk_ref": risk_ref,
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
        status=f"ready_from_{risk_ref_key.removesuffix('_ref')}"
        if features
        else "empty_risk_source",
        source_plan_ref=None,
    )
    artifact["features"] = features
    artifact["counts"] = {
        "feature_count": len(features),
        "source_risk_feature_count": len(payload.get("features", [])),
        "runtime_safety_truth_count": 0,
    }
    artifact["source_refs"] = [
        ref
        for ref in (
            risk_ref_record,
            manifest["inputs"]["source_refs"].get("risk_score_points_metadata_ref"),
            manifest["inputs"]["source_refs"].get("risk_route_profile_ref"),
            manifest["inputs"]["source_refs"].get("risk_route_profile_metadata_ref"),
            manifest["inputs"]["source_refs"].get("risk_ribbon_metadata_ref"),
        )
        if isinstance(ref, dict)
    ]
    return artifact


def _terrain_visualization_from_project(
    project_root: Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    bitmap_artifact = _dtm_corridor_bitmap_terrain_visualization(
        project_root,
        manifest,
    )
    if bitmap_artifact is not None:
        return bitmap_artifact
    return _route_aligned_terrain_visualization_from_project(project_root, manifest)


def _route_aligned_terrain_visualization_from_project(
    project_root: Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    risk_ref_key, risk_ref_record, risk_ref, risk_path = _terrain_source_ref(
        project_root,
        manifest,
    )
    if not isinstance(risk_ref, str) or not risk_ref or risk_path is None:
        return _empty_terrain_visualization(
            manifest,
            status=_layer_status(manifest, "terrain"),
            warning="No risk route profile or risk score source is available.",
        )
    if not risk_path.exists():
        return _empty_terrain_visualization(
            manifest,
            status="missing_risk_source",
            warning=f"{risk_ref_key} points to a missing file: {risk_ref}",
        )

    payload = _load_json(risk_path)
    source_features = _terrain_source_samples(payload)
    if not source_features:
        return _empty_terrain_visualization(
            manifest,
            status="empty_risk_source",
            warning=f"{risk_ref_key} has no route-aligned point samples.",
        )

    elevations = [
        sample["elevation_m"]
        for sample in source_features
        if isinstance(sample.get("elevation_m"), float)
    ]
    elevation_min = min(elevations) if elevations else None
    elevation_max = max(elevations) if elevations else None
    features: list[dict[str, Any]] = []
    slope_counts: Counter[str] = Counter()
    contour_marker_count = 0
    for index, sample in enumerate(source_features):
        slope_degrees = _route_aligned_slope_degrees(source_features, index)
        slope_class = _slope_class_for_degrees(slope_degrees)
        if slope_class:
            slope_counts[str(slope_class["class_id"])] += 1
        elevation_m = sample.get("elevation_m")
        contour_index_m = (
            _contour_index_m(elevation_m) if isinstance(elevation_m, float) else None
        )
        if contour_index_m is not None:
            contour_marker_count += 1
        sample_id = str(sample["sample_id"])
        feature_id = f"terrain_visualization.{index + 1:06d}"
        properties = {
            **sample["properties"],
            "terrain_visualization_id": feature_id,
            "terrain_sample_id": sample_id,
            "evidence_type": "pretrip_terrain_visualization_sample",
            "source_kind": "scout_risk_engine_route_aligned_terrain",
            "source_risk_ref_key": risk_ref_key,
            "source_risk_ref": risk_ref,
            "visualization_modes": list(TERRAIN_VISUALIZATION_MODES),
            "terrain_visualization_layer": True,
            "risk_heat_layer": False,
            "hillshade_method": "route_aligned_slope_proxy",
            "hillshade_value": _hillshade_value_from_slope(slope_degrees),
            "elevation_tint_method": "route_aligned_elevation_band",
            "elevation_tint_color": _elevation_tint_color(
                elevation_m,
                elevation_min=elevation_min,
                elevation_max=elevation_max,
            ),
            "slope_method": "route_elevation_delta_degrees",
            "slope_degrees": round(slope_degrees, 2)
            if isinstance(slope_degrees, float)
            else None,
            "slope_source": "route_risk_profile_elevation_delta"
            if isinstance(slope_degrees, float)
            else "unavailable",
            "slope_class": slope_class["class_id"] if slope_class else "unavailable",
            "slope_class_label": slope_class["label"] if slope_class else "unavailable",
            "slope_color": slope_class["color"] if slope_class else "#94a3b8",
            "contour_interval_m": TERRAIN_CONTOUR_INTERVAL_M,
            "contour_index_m": contour_index_m,
            "contour_marker": contour_index_m is not None,
            "route_scope_ref": manifest["inputs"]["route_evidence_bundle"].get(
                "source_ref"
            ),
            "candidate_only": True,
            "requires_human_review": True,
            "runtime_safety_truth": False,
        }
        features.append(
            {
                "type": "Feature",
                "geometry": sample["geometry"],
                "properties": properties,
            }
        )

    artifact = _empty_geojson_evidence_from_manifest(
        manifest,
        artifact_kind="pretrip_terrain_visualization",
        evidence_type="pretrip_terrain_visualization_sample",
        status=f"ready_from_{risk_ref_key.removesuffix('_ref')}",
        source_plan_ref=None,
    )
    artifact["features"] = features
    artifact["visualization_spec"] = {
        "modes": list(TERRAIN_VISUALIZATION_MODES),
        "slope_class_breaks": list(TERRAIN_SLOPE_CLASSES),
        "contour_interval_m": TERRAIN_CONTOUR_INTERVAL_M,
        "terrain_visualization_layer": True,
        "risk_heat_layer": False,
        "route_aligned_proxy": True,
        "full_raster_hillshade_generated": False,
        "raw_dem_embedded_in_json": False,
    }
    artifact["counts"] = {
        "feature_count": len(features),
        "source_risk_feature_count": len(payload.get("features", [])),
        "mode_count": len(TERRAIN_VISUALIZATION_MODES),
        "slope_class_counts": dict(sorted(slope_counts.items())),
        "contour_marker_count": contour_marker_count,
        "runtime_safety_truth_count": 0,
    }
    artifact["source_refs"] = [
        ref
        for ref in (
            risk_ref_record,
            manifest["inputs"]["source_refs"].get("risk_route_profile_metadata_ref"),
            manifest["inputs"]["source_refs"].get("risk_score_points_metadata_ref"),
            manifest["inputs"]["source_refs"].get("segment_dtm_coverage_ref"),
        )
        if isinstance(ref, dict)
    ]
    artifact["boundary"] = {
        **artifact["boundary"],
        "terrain_visualization_layer": True,
        "risk_heat_layer": False,
        "route_aligned_proxy": True,
        "bitmap_overlay": False,
    }
    return artifact


def _dtm_corridor_bitmap_terrain_visualization(
    project_root: Path,
    manifest: dict[str, Any],
) -> dict[str, Any] | None:
    dtm_ref_record = manifest["inputs"]["source_refs"].get("dtm_coverage_summary_ref")
    dtm_ref = dtm_ref_record.get("ref") if isinstance(dtm_ref_record, dict) else None
    if not isinstance(dtm_ref, str) or not dtm_ref:
        return None
    dtm_path = project_root / dtm_ref
    if not dtm_path.exists():
        return None

    risk_ref_key, risk_ref_record, risk_ref, risk_path = _terrain_source_ref(
        project_root,
        manifest,
    )
    if not isinstance(risk_ref, str) or not risk_ref or risk_path is None:
        return None
    if not risk_path.exists():
        return None

    risk_payload = _load_json(risk_path)
    source_samples = _terrain_source_samples(risk_payload)
    route_points = _terrain_route_points_twd97(source_samples)
    if len(route_points) < 2:
        return None

    dtm_payload = _load_json(dtm_path)
    candidate_tiles = _dtm_candidate_tiles(
        dtm_payload,
        route_points,
        corridor_half_width_m=TERRAIN_DTM_CORRIDOR_HALF_WIDTH_M,
    )
    if not candidate_tiles:
        return None

    elevation_by_xy = _read_dtm_grid_elevations(candidate_tiles)
    if not elevation_by_xy:
        return None

    segment_index = _route_segment_index(
        route_points,
        corridor_half_width_m=TERRAIN_DTM_CORRIDOR_HALF_WIDTH_M,
    )
    cells = _dtm_corridor_cells(
        elevation_by_xy,
        segment_index,
        corridor_half_width_m=TERRAIN_DTM_CORRIDOR_HALF_WIDTH_M,
        resolution_m=TERRAIN_DTM_CELL_RESOLUTION_M,
    )
    if not cells:
        return None

    elevation_values = [cell["elevation_m"] for cell in cells]
    elevation_min = min(elevation_values)
    elevation_max = max(elevation_values)
    dtm_cells_bbox_twd97 = _dtm_cells_bbox_twd97(cells)
    bbox_twd97 = _route_corridor_bbox_twd97(
        route_points,
        corridor_half_width_m=TERRAIN_DTM_CORRIDOR_HALF_WIDTH_M,
    )
    bbox_wgs84 = _projected_bbox_twd97_to_wgs84(bbox_twd97)
    slope_counts = Counter(str(cell["slope_class"]["class_id"]) for cell in cells)
    contour_cell_count = sum(1 for cell in cells if cell["contour_marker"])
    overlays = _write_dtm_corridor_bitmap_overlays(
        project_root=project_root,
        manifest=manifest,
        cells=cells,
        route_points=route_points,
        bbox_twd97=bbox_twd97,
        bbox_wgs84=bbox_wgs84,
        elevation_min=elevation_min,
        elevation_max=elevation_max,
    )
    gdal_pipeline = _gdal_terrain_pipeline_availability()

    artifact = _empty_geojson_evidence_from_manifest(
        manifest,
        artifact_kind="pretrip_terrain_visualization",
        evidence_type="pretrip_terrain_visualization_bitmap_overlay",
        status="ready_from_dtm_20m_corridor_bitmap",
        source_plan_ref=None,
    )
    artifact["features"] = []
    artifact["raster_overlays"] = overlays
    artifact["visualization_spec"] = {
        "modes": list(TERRAIN_VISUALIZATION_MODES),
        "slope_class_breaks": list(TERRAIN_SLOPE_CLASSES),
        "contour_interval_m": TERRAIN_CONTOUR_INTERVAL_M,
        "terrain_visualization_layer": True,
        "risk_heat_layer": False,
        "route_aligned_proxy": False,
        "bitmap_overlay": True,
        "preferred_processor": "gdal",
        "actual_processor": "python_dtm_bitmap_fallback",
        "gdal_pipeline": gdal_pipeline,
        "bitmap_cell_resolution_m": TERRAIN_DTM_CELL_RESOLUTION_M,
        "corridor_half_width_m": TERRAIN_DTM_CORRIDOR_HALF_WIDTH_M,
        "corridor_total_width_m": TERRAIN_DTM_CORRIDOR_TOTAL_WIDTH_M,
        "slope_method": "dtm_grid_20m_central_difference",
        "hillshade_method": "dtm_slope_proxy_grayscale",
        "elevation_tint_method": "dtm_elevation_band",
        "contour_method": "dtm_near_interval_cell_marker",
        "missing_dtm_corridor_underlay": True,
        "full_raster_hillshade_generated": False,
        "raw_dem_embedded_in_json": False,
        "raw_dem_committed_to_repo": False,
    }
    artifact["counts"] = {
        "feature_count": 0,
        "bitmap_overlay_count": len(overlays),
        "cell_count": len(cells),
        "rendered_dom_cell_count": 0,
        "source_dtm_tile_count": len(candidate_tiles),
        "source_dtm_grid_cell_count": len(elevation_by_xy),
        "source_risk_feature_count": len(risk_payload.get("features", [])),
        "mode_count": len(TERRAIN_VISUALIZATION_MODES),
        "slope_class_counts": dict(sorted(slope_counts.items())),
        "contour_marker_count": contour_cell_count,
        "runtime_safety_truth_count": 0,
    }
    artifact["source_refs"] = [
        ref
        for ref in (
            dtm_ref_record,
            risk_ref_record,
            manifest["inputs"]["source_refs"].get("risk_route_profile_metadata_ref"),
            manifest["inputs"]["source_refs"].get("risk_score_points_metadata_ref"),
            manifest["inputs"]["source_refs"].get("segment_dtm_coverage_ref"),
        )
        if isinstance(ref, dict)
    ]
    artifact["boundary"] = {
        **artifact["boundary"],
        "terrain_visualization_layer": True,
        "risk_heat_layer": False,
        "route_aligned_proxy": False,
        "bitmap_overlay": True,
        "pretrip_candidate_evidence_only": True,
        "runtime_safety_truth": False,
        "raw_dem_embedded_in_json": False,
        "phase1_runtime_mutation_allowed": False,
    }
    artifact["dtm_grid"] = {
        "crs": "TWD97 / TM2 zone 121 (EPSG:3826-compatible)",
        "cell_resolution_m": TERRAIN_DTM_CELL_RESOLUTION_M,
        "corridor_half_width_m": TERRAIN_DTM_CORRIDOR_HALF_WIDTH_M,
        "corridor_total_width_m": TERRAIN_DTM_CORRIDOR_TOTAL_WIDTH_M,
        "bbox_twd97": bbox_twd97,
        "bbox_wgs84": bbox_wgs84,
        "selected_cell_count": len(cells),
        "source_tile_count": len(candidate_tiles),
        "dtm_cells_bbox_twd97": dtm_cells_bbox_twd97,
        "full_route_corridor_bbox_twd97": bbox_twd97,
        "raw_grid_embedded_in_json": False,
        "preferred_pipeline": gdal_pipeline,
    }
    return artifact


def _terrain_route_points_twd97(
    source_samples: list[dict[str, Any]],
) -> list[dict[str, float]]:
    route_points: list[dict[str, float]] = []
    for sample in source_samples:
        coordinates = sample.get("geometry", {}).get("coordinates", [])
        if len(coordinates) < 2:
            continue
        lon = _as_float(coordinates[0])
        lat = _as_float(coordinates[1])
        if not isinstance(lat, float) or not isinstance(lon, float):
            continue
        x, y = wgs84_to_twd97(lat, lon)
        if route_points and abs(route_points[-1]["x"] - x) < 0.001 and abs(
            route_points[-1]["y"] - y
        ) < 0.001:
            continue
        route_points.append(
            {
                "x": x,
                "y": y,
                "lat": lat,
                "lon": lon,
                "distance_m": sample.get("distance_m") or float(len(route_points)),
            }
        )
    return route_points


def _dtm_candidate_tiles(
    dtm_payload: dict[str, Any],
    route_points: list[dict[str, float]],
    *,
    corridor_half_width_m: float,
) -> list[dict[str, Any]]:
    route_bbox = {
        "min_x": min(point["x"] for point in route_points) - corridor_half_width_m,
        "min_y": min(point["y"] for point in route_points) - corridor_half_width_m,
        "max_x": max(point["x"] for point in route_points) + corridor_half_width_m,
        "max_y": max(point["y"] for point in route_points) + corridor_half_width_m,
    }
    candidates = []
    for tile in dtm_payload.get("candidate_tiles", []):
        if not isinstance(tile, dict):
            continue
        bbox = tile.get("bbox_twd97") or {}
        if not _twd97_bbox_intersects(route_bbox, bbox):
            continue
        grid_path = _dtm_grid_path(tile)
        if grid_path is None or not grid_path.exists():
            continue
        candidates.append({**tile, "_grid_path": grid_path})
    return candidates


def _twd97_bbox_intersects(
    a: dict[str, Any],
    b: dict[str, Any],
) -> bool:
    values = (
        _as_float(a.get("min_x")),
        _as_float(a.get("min_y")),
        _as_float(a.get("max_x")),
        _as_float(a.get("max_y")),
        _as_float(b.get("min_x")),
        _as_float(b.get("min_y")),
        _as_float(b.get("max_x")),
        _as_float(b.get("max_y")),
    )
    if any(value is None for value in values):
        return False
    amin_x, amin_y, amax_x, amax_y, bmin_x, bmin_y, bmax_x, bmax_y = values
    assert amin_x is not None and amin_y is not None and amax_x is not None
    assert amax_y is not None and bmin_x is not None and bmin_y is not None
    assert bmax_x is not None and bmax_y is not None
    return not (amax_x < bmin_x or amin_x > bmax_x or amax_y < bmin_y or amin_y > bmax_y)


def _dtm_grid_path(tile: dict[str, Any]) -> Path | None:
    for key in ("grid_uri", "grid_path", "path"):
        value = tile.get(key)
        if isinstance(value, str) and value:
            return Path(value).expanduser()
    return None


def _read_dtm_grid_elevations(
    candidate_tiles: list[dict[str, Any]],
) -> dict[tuple[int, int], float]:
    elevations: dict[tuple[int, int], float] = {}
    for tile in candidate_tiles:
        grid_path = tile.get("_grid_path")
        if not isinstance(grid_path, Path):
            continue
        with grid_path.open(encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) < 3:
                    continue
                x = _as_float(parts[0])
                y = _as_float(parts[1])
                elevation = _as_float(parts[2])
                if not isinstance(x, float) or not isinstance(y, float):
                    continue
                if not isinstance(elevation, float):
                    continue
                elevations[(int(round(x)), int(round(y)))] = elevation
    return elevations


def _route_segment_index(
    route_points: list[dict[str, float]],
    *,
    corridor_half_width_m: float,
) -> dict[str, Any]:
    segments: list[dict[str, float]] = []
    buckets: dict[tuple[int, int], list[int]] = {}
    bucket_size = TERRAIN_DTM_SEGMENT_BUCKET_M
    for point_a, point_b in zip(route_points, route_points[1:]):
        ax = point_a["x"]
        ay = point_a["y"]
        bx = point_b["x"]
        by = point_b["y"]
        if abs(ax - bx) + abs(ay - by) < 0.001:
            continue
        segment = {
            "ax": ax,
            "ay": ay,
            "bx": bx,
            "by": by,
            "min_x": min(ax, bx) - corridor_half_width_m,
            "min_y": min(ay, by) - corridor_half_width_m,
            "max_x": max(ax, bx) + corridor_half_width_m,
            "max_y": max(ay, by) + corridor_half_width_m,
        }
        index = len(segments)
        segments.append(segment)
        for ix in range(
            math.floor(segment["min_x"] / bucket_size),
            math.floor(segment["max_x"] / bucket_size) + 1,
        ):
            for iy in range(
                math.floor(segment["min_y"] / bucket_size),
                math.floor(segment["max_y"] / bucket_size) + 1,
            ):
                buckets.setdefault((ix, iy), []).append(index)
    return {"segments": segments, "buckets": buckets, "bucket_size_m": bucket_size}


def _dtm_corridor_cells(
    elevation_by_xy: dict[tuple[int, int], float],
    segment_index: dict[str, Any],
    *,
    corridor_half_width_m: float,
    resolution_m: float,
) -> list[dict[str, Any]]:
    cells: list[dict[str, Any]] = []
    max_distance_sq = corridor_half_width_m * corridor_half_width_m
    for x, y in sorted(elevation_by_xy.keys(), key=lambda item: (item[1], item[0])):
        distance_sq = _nearest_route_distance_sq(x, y, segment_index)
        if distance_sq is None or distance_sq > max_distance_sq:
            continue
        elevation_m = elevation_by_xy[(x, y)]
        slope_degrees = _dtm_grid_slope_degrees(
            elevation_by_xy,
            x,
            y,
            resolution_m=resolution_m,
        )
        slope_class = _slope_class_for_degrees(slope_degrees) or TERRAIN_SLOPE_CLASSES[0]
        contour_index_m = _contour_index_m(elevation_m)
        contour_marker = (
            contour_index_m is not None
            and abs(elevation_m - contour_index_m) <= TERRAIN_DTM_CONTOUR_TOLERANCE_M
        )
        cells.append(
            {
                "x": x,
                "y": y,
                "elevation_m": elevation_m,
                "slope_degrees": slope_degrees,
                "slope_class": slope_class,
                "contour_index_m": contour_index_m,
                "contour_marker": contour_marker,
                "distance_to_route_m": math.sqrt(distance_sq),
            }
        )
    return cells


def _nearest_route_distance_sq(
    x: float,
    y: float,
    segment_index: dict[str, Any],
) -> float | None:
    bucket_size = float(segment_index["bucket_size_m"])
    bucket = (math.floor(x / bucket_size), math.floor(y / bucket_size))
    segment_ids = segment_index["buckets"].get(bucket, [])
    if not segment_ids:
        return None
    nearest: float | None = None
    for segment_id in segment_ids:
        segment = segment_index["segments"][segment_id]
        if x < segment["min_x"] or x > segment["max_x"]:
            continue
        if y < segment["min_y"] or y > segment["max_y"]:
            continue
        distance_sq = _point_segment_distance_sq(
            x,
            y,
            segment["ax"],
            segment["ay"],
            segment["bx"],
            segment["by"],
        )
        if nearest is None or distance_sq < nearest:
            nearest = distance_sq
    return nearest


def _point_segment_distance_sq(
    px: float,
    py: float,
    ax: float,
    ay: float,
    bx: float,
    by: float,
) -> float:
    vx = bx - ax
    vy = by - ay
    wx = px - ax
    wy = py - ay
    denominator = vx * vx + vy * vy
    if denominator <= 0:
        return (px - ax) ** 2 + (py - ay) ** 2
    ratio = max(0.0, min(1.0, (wx * vx + wy * vy) / denominator))
    qx = ax + ratio * vx
    qy = ay + ratio * vy
    return (px - qx) ** 2 + (py - qy) ** 2


def _dtm_grid_slope_degrees(
    elevation_by_xy: dict[tuple[int, int], float],
    x: int,
    y: int,
    *,
    resolution_m: float,
) -> float | None:
    step = int(round(resolution_m))
    center = elevation_by_xy.get((x, y))
    if center is None:
        return None
    east = elevation_by_xy.get((x + step, y))
    west = elevation_by_xy.get((x - step, y))
    north = elevation_by_xy.get((x, y + step))
    south = elevation_by_xy.get((x, y - step))
    dz_dx = _gradient_component(center, east, west, resolution_m)
    dz_dy = _gradient_component(center, north, south, resolution_m)
    if dz_dx is None and dz_dy is None:
        return None
    rise = math.sqrt((dz_dx or 0.0) ** 2 + (dz_dy or 0.0) ** 2)
    return math.degrees(math.atan(rise))


def _gradient_component(
    center: float,
    forward: float | None,
    backward: float | None,
    resolution_m: float,
) -> float | None:
    if isinstance(forward, float) and isinstance(backward, float):
        return (forward - backward) / (2.0 * resolution_m)
    if isinstance(forward, float):
        return (forward - center) / resolution_m
    if isinstance(backward, float):
        return (center - backward) / resolution_m
    return None


def _dtm_cells_bbox_twd97(cells: list[dict[str, Any]]) -> dict[str, float]:
    xs = [float(cell["x"]) for cell in cells]
    ys = [float(cell["y"]) for cell in cells]
    half_cell = TERRAIN_DTM_CELL_RESOLUTION_M / 2.0
    return {
        "min_x": min(xs) - half_cell,
        "min_y": min(ys) - half_cell,
        "max_x": max(xs) + half_cell,
        "max_y": max(ys) + half_cell,
    }


def _route_corridor_bbox_twd97(
    route_points: list[dict[str, float]],
    *,
    corridor_half_width_m: float,
) -> dict[str, float]:
    return {
        "min_x": min(point["x"] for point in route_points) - corridor_half_width_m,
        "min_y": min(point["y"] for point in route_points) - corridor_half_width_m,
        "max_x": max(point["x"] for point in route_points) + corridor_half_width_m,
        "max_y": max(point["y"] for point in route_points) + corridor_half_width_m,
    }


def _projected_bbox_twd97_to_wgs84(
    bbox_twd97: dict[str, float],
) -> dict[str, float]:
    corners = [
        _twd97_to_wgs84(bbox_twd97["min_x"], bbox_twd97["min_y"]),
        _twd97_to_wgs84(bbox_twd97["min_x"], bbox_twd97["max_y"]),
        _twd97_to_wgs84(bbox_twd97["max_x"], bbox_twd97["min_y"]),
        _twd97_to_wgs84(bbox_twd97["max_x"], bbox_twd97["max_y"]),
    ]
    return normalize_bbox_wgs84(
        {
            "south": min(lat for lat, _ in corners),
            "west": min(lon for _, lon in corners),
            "north": max(lat for lat, _ in corners),
            "east": max(lon for _, lon in corners),
        }
    )


def _twd97_to_wgs84(x: float, y: float) -> tuple[float, float]:
    lat = y / 110_900.0
    lon = 121.0 + (x - 250_000.0) / (
        111_320.0 * max(math.cos(math.radians(lat)), 0.1)
    )
    for _ in range(10):
        projected_x, projected_y = wgs84_to_twd97(lat, lon)
        dx = x - projected_x
        dy = y - projected_y
        if abs(dx) + abs(dy) < 0.001:
            break
        delta = 1e-5
        projected_lon_x, projected_lon_y = wgs84_to_twd97(lat, lon + delta)
        projected_lat_x, projected_lat_y = wgs84_to_twd97(lat + delta, lon)
        a = (projected_lon_x - projected_x) / delta
        b = (projected_lat_x - projected_x) / delta
        c = (projected_lon_y - projected_y) / delta
        d = (projected_lat_y - projected_y) / delta
        determinant = a * d - b * c
        if abs(determinant) < 1e-9:
            break
        lon += (dx * d - b * dy) / determinant
        lat += (a * dy - dx * c) / determinant
    return lat, lon


def _write_dtm_corridor_bitmap_overlays(
    *,
    project_root: Path,
    manifest: dict[str, Any],
    cells: list[dict[str, Any]],
    route_points: list[dict[str, float]],
    bbox_twd97: dict[str, float],
    bbox_wgs84: dict[str, float],
    elevation_min: float,
    elevation_max: float,
) -> list[dict[str, Any]]:
    try:
        from PIL import Image, ImageDraw
    except Exception as exc:  # pragma: no cover - environment guard
        raise RuntimeError("Pillow is required for DTM bitmap overlays") from exc

    width = int(round((bbox_twd97["max_x"] - bbox_twd97["min_x"]) / TERRAIN_DTM_CELL_RESOLUTION_M))
    height = int(round((bbox_twd97["max_y"] - bbox_twd97["min_y"]) / TERRAIN_DTM_CELL_RESOLUTION_M))
    width = max(1, width)
    height = max(1, height)
    images = {
        "hillshade": Image.new("RGBA", (width, height), (0, 0, 0, 0)),
        "elevation_tint": Image.new("RGBA", (width, height), (0, 0, 0, 0)),
        "slope_shading": Image.new("RGBA", (width, height), (0, 0, 0, 0)),
        "contours": Image.new("RGBA", (width, height), (0, 0, 0, 0)),
    }
    pixels = {mode: image.load() for mode, image in images.items()}
    route_pixels = _terrain_route_pixels(route_points, bbox_twd97)
    if len(route_pixels) >= 2:
        corridor_width_px = max(
            1,
            int(round(TERRAIN_DTM_CORRIDOR_TOTAL_WIDTH_M / TERRAIN_DTM_CELL_RESOLUTION_M)),
        )
        underlay_defs = {
            "hillshade": (148, 163, 184, 52),
            "elevation_tint": (203, 213, 225, 54),
            "slope_shading": (203, 213, 225, 42),
        }
        for mode, color in underlay_defs.items():
            ImageDraw.Draw(images[mode]).line(route_pixels, fill=color, width=corridor_width_px)
    for cell in cells:
        col = int(
            math.floor(
                (float(cell["x"]) - bbox_twd97["min_x"])
                / TERRAIN_DTM_CELL_RESOLUTION_M
            )
        )
        row = int(
            math.floor(
                (bbox_twd97["max_y"] - float(cell["y"]))
                / TERRAIN_DTM_CELL_RESOLUTION_M
            )
        )
        if col < 0 or row < 0 or col >= width or row >= height:
            continue
        slope_degrees = cell.get("slope_degrees")
        hillshade = _hillshade_value_from_slope(
            slope_degrees if isinstance(slope_degrees, float) else None
        )
        if hillshade is not None:
            pixels["hillshade"][col, row] = (hillshade, hillshade, hillshade, 132)
        pixels["elevation_tint"][col, row] = _rgba_from_hex(
            _elevation_tint_color(
                cell.get("elevation_m"),
                elevation_min=elevation_min,
                elevation_max=elevation_max,
            ),
            alpha=132,
        )
        pixels["slope_shading"][col, row] = _rgba_from_hex(
            str(cell["slope_class"]["color"]),
            alpha=188,
        )
        if cell.get("contour_marker"):
            pixels["contours"][col, row] = (17, 24, 39, 230)

    overlay_defs = [
        ("hillshade", "terrain_hillshade_overlay_ref", True, 0.28),
        ("elevation_tint", "terrain_elevation_tint_overlay_ref", True, 0.32),
        ("slope_shading", "terrain_slope_shading_overlay_ref", True, 0.78),
        ("contours", "terrain_contours_overlay_ref", True, 0.88),
    ]
    overlays = []
    for mode, ref_key, default_visible, opacity in overlay_defs:
        source_ref = manifest["outputs"][ref_key]
        output_path = project_root / source_ref
        output_path.parent.mkdir(parents=True, exist_ok=True)
        images[mode].save(output_path, format="PNG")
        overlays.append(
            {
                "overlay_id": mode,
                "mode": mode,
                "source_path": source_ref,
                "runtime_href": (
                    f"/admin/pretrip/projects/{manifest['project_id']}"
                    f"/terrain-overlays/{mode}.png"
                ),
                "media_type": "image/png",
                "sha256": _sha256_file(output_path),
                "bbox_wgs84": bbox_wgs84,
                "bbox_twd97": bbox_twd97,
                "pixel_width": width,
                "pixel_height": height,
                "cell_resolution_m": TERRAIN_DTM_CELL_RESOLUTION_M,
                "corridor_half_width_m": TERRAIN_DTM_CORRIDOR_HALF_WIDTH_M,
                "corridor_total_width_m": TERRAIN_DTM_CORRIDOR_TOTAL_WIDTH_M,
                "default_visible": default_visible,
                "opacity": opacity,
                "image_rendering": "pixelated",
                "candidate_only": True,
                "runtime_safety_truth": False,
                "raw_dem_embedded_in_json": False,
            }
        )
    return overlays


def _terrain_route_pixels(
    route_points: list[dict[str, float]],
    bbox_twd97: dict[str, float],
) -> list[tuple[int, int]]:
    pixels: list[tuple[int, int]] = []
    for point in route_points:
        col = int(
            round(
                (float(point["x"]) - bbox_twd97["min_x"])
                / TERRAIN_DTM_CELL_RESOLUTION_M
            )
        )
        row = int(
            round(
                (bbox_twd97["max_y"] - float(point["y"]))
                / TERRAIN_DTM_CELL_RESOLUTION_M
            )
        )
        if pixels and pixels[-1] == (col, row):
            continue
        pixels.append((col, row))
    return pixels


def _gdal_terrain_pipeline_availability() -> dict[str, Any]:
    commands = {
        "gdal_translate": shutil.which("gdal_translate"),
        "gdaldem": shutil.which("gdaldem"),
        "gdal_contour": shutil.which("gdal_contour"),
        "gdal2tiles.py": shutil.which("gdal2tiles.py") or shutil.which("gdal2tiles"),
    }
    return {
        "pipeline_id": "dem_dtm_geotiff_gdal_terrain_visualization.v1",
        "available": all(commands.values()),
        "commands": commands,
        "steps": [
            "DEM/DTM source normalized to GeoTIFF",
            "gdaldem hillshade -> terrain_hillshade raster",
            "gdaldem slope -> terrain_slope degrees raster",
            "gdaldem color-relief -> terrain_slope_shading raster",
            "gdal_contour -> terrain_contours GeoJSON",
            "gdal2tiles or local tile cutter -> /admin/pretrip display overlays",
        ],
        "fallback_when_unavailable": "python_dtm_bitmap_fallback",
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _rgba_from_hex(color: str, *, alpha: int) -> tuple[int, int, int, int]:
    clean = color.strip().lstrip("#")
    if len(clean) != 6:
        return (148, 163, 184, alpha)
    try:
        return (
            int(clean[0:2], 16),
            int(clean[2:4], 16),
            int(clean[4:6], 16),
            alpha,
        )
    except ValueError:
        return (148, 163, 184, alpha)


def _empty_terrain_visualization(
    manifest: dict[str, Any],
    *,
    status: str,
    warning: str,
) -> dict[str, Any]:
    artifact = _empty_geojson_evidence_from_manifest(
        manifest,
        artifact_kind="pretrip_terrain_visualization",
        evidence_type="pretrip_terrain_visualization_sample",
        status=status,
        source_plan_ref=None,
    )
    artifact["visualization_spec"] = {
        "modes": list(TERRAIN_VISUALIZATION_MODES),
        "slope_class_breaks": list(TERRAIN_SLOPE_CLASSES),
        "contour_interval_m": TERRAIN_CONTOUR_INTERVAL_M,
        "terrain_visualization_layer": True,
        "risk_heat_layer": False,
        "route_aligned_proxy": True,
        "full_raster_hillshade_generated": False,
        "raw_dem_embedded_in_json": False,
    }
    artifact["counts"] = {
        **artifact["counts"],
        "mode_count": len(TERRAIN_VISUALIZATION_MODES),
        "contour_marker_count": 0,
        "runtime_safety_truth_count": 0,
    }
    artifact["warnings"] = [warning]
    return artifact


def _terrain_source_ref(
    project_root: Path,
    manifest: dict[str, Any],
) -> tuple[str, dict[str, Any] | None, str | None, Path | None]:
    first_candidate: (
        tuple[str, dict[str, Any] | None, str | None, Path | None] | None
    ) = None
    for ref_key in ("risk_route_profile_ref", "risk_score_points_ref", "risk_ribbon_ref"):
        ref_record = manifest["inputs"]["source_refs"].get(ref_key, {})
        ref = ref_record.get("ref") if isinstance(ref_record, dict) else None
        if isinstance(ref, str) and ref:
            path = project_root / ref
            candidate = (ref_key, ref_record, ref, path)
            if path.exists():
                return candidate
            if first_candidate is None:
                first_candidate = candidate
    if first_candidate is not None:
        return first_candidate
    return "", None, None, None


def _terrain_source_samples(payload: dict[str, Any]) -> list[dict[str, Any]]:
    samples = []
    for index, feature in enumerate(payload.get("features", [])):
        if not isinstance(feature, dict):
            continue
        geometry = feature.get("geometry") or {}
        geometry_type = geometry.get("type")
        coordinates = geometry.get("coordinates") or []
        properties = dict(feature.get("properties") or {})
        if geometry_type == "Point" and len(coordinates) >= 2:
            sample_id = str(
                properties.get("sample_id") or f"terrain_source.{index + 1:06d}"
            )
            samples.append(
                {
                    "sample_id": sample_id,
                    "geometry": geometry,
                    "properties": properties,
                    "distance_m": _as_float(properties.get("distance_m")),
                    "elevation_m": _as_float(properties.get("elevation_m")),
                }
            )
            continue
        if geometry_type == "LineString":
            samples.extend(
                _terrain_source_samples_from_line(
                    coordinates,
                    properties=properties,
                    feature_index=index,
                )
            )
            continue
        if geometry_type == "MultiLineString":
            for part_index, line in enumerate(coordinates):
                samples.extend(
                    _terrain_source_samples_from_line(
                        line,
                        properties=properties,
                        feature_index=index,
                        part_index=part_index,
                    )
                )
    return samples


def _terrain_source_samples_from_line(
    coordinates: list[Any],
    *,
    properties: dict[str, Any],
    feature_index: int,
    part_index: int | None = None,
) -> list[dict[str, Any]]:
    line_samples: list[dict[str, Any]] = []
    valid_coordinates = [
        coordinate
        for coordinate in coordinates
        if isinstance(coordinate, list | tuple) and len(coordinate) >= 2
    ]
    if not valid_coordinates:
        return line_samples
    start_distance = _as_float(properties.get("start_distance_m"))
    end_distance = _as_float(properties.get("end_distance_m"))
    distance_span = (
        end_distance - start_distance
        if isinstance(start_distance, float)
        and isinstance(end_distance, float)
        and end_distance >= start_distance
        else None
    )
    part_suffix = f".part{part_index + 1:02d}" if isinstance(part_index, int) else ""
    denominator = max(1, len(valid_coordinates) - 1)
    for point_index, coordinate in enumerate(valid_coordinates):
        lon = _as_float(coordinate[0])
        lat = _as_float(coordinate[1])
        if not isinstance(lat, float) or not isinstance(lon, float):
            continue
        ratio = point_index / denominator
        distance_m = (
            start_distance + distance_span * ratio
            if isinstance(start_distance, float) and isinstance(distance_span, float)
            else None
        )
        sample_id = (
            properties.get("sample_id")
            or properties.get("from_sample_id")
            or properties.get("segment_id")
            or f"terrain_source.{feature_index + 1:06d}"
        )
        line_samples.append(
            {
                "sample_id": f"{sample_id}{part_suffix}.pt{point_index + 1:02d}",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    **properties,
                    "source_geometry_type": "LineString",
                    "line_point_index": point_index,
                },
                "distance_m": distance_m,
                "elevation_m": _as_float(properties.get("elevation_m")),
            }
        )
    return line_samples


def _route_aligned_slope_degrees(
    samples: list[dict[str, Any]],
    index: int,
) -> float | None:
    current = samples[index]
    current_distance = current.get("distance_m")
    current_elevation = current.get("elevation_m")
    if not isinstance(current_distance, float) or not isinstance(current_elevation, float):
        return None
    neighbors = []
    if index > 0:
        neighbors.append(samples[index - 1])
    if index + 1 < len(samples):
        neighbors.append(samples[index + 1])
    slopes = []
    for neighbor in neighbors:
        neighbor_distance = neighbor.get("distance_m")
        neighbor_elevation = neighbor.get("elevation_m")
        if not isinstance(neighbor_distance, float) or not isinstance(
            neighbor_elevation,
            float,
        ):
            continue
        distance_delta = abs(neighbor_distance - current_distance)
        if distance_delta <= 0:
            continue
        elevation_delta = abs(neighbor_elevation - current_elevation)
        slopes.append(math.degrees(math.atan(elevation_delta / distance_delta)))
    if not slopes:
        return None
    return max(slopes)


def _slope_class_for_degrees(slope_degrees: float | None) -> dict[str, Any] | None:
    if not isinstance(slope_degrees, float):
        return None
    for slope_class in TERRAIN_SLOPE_CLASSES:
        min_degrees = float(slope_class["min_degrees"])
        max_degrees = slope_class["max_degrees"]
        if slope_degrees < min_degrees:
            continue
        if max_degrees is None or slope_degrees < float(max_degrees):
            return slope_class
    return TERRAIN_SLOPE_CLASSES[-1]


def _hillshade_value_from_slope(slope_degrees: float | None) -> int | None:
    if not isinstance(slope_degrees, float):
        return None
    return max(70, min(240, round(230 - min(slope_degrees, 70.0) * 2.3)))


def _elevation_tint_color(
    elevation_m: float | None,
    *,
    elevation_min: float | None,
    elevation_max: float | None,
) -> str:
    if not isinstance(elevation_m, float) or not isinstance(
        elevation_min,
        float,
    ) or not isinstance(elevation_max, float):
        return "#cbd5e1"
    span = max(elevation_max - elevation_min, 1.0)
    ratio = (elevation_m - elevation_min) / span
    if ratio < 0.2:
        return "#b7e4a8"
    if ratio < 0.4:
        return "#d9ef8b"
    if ratio < 0.6:
        return "#fee08b"
    if ratio < 0.8:
        return "#fdae61"
    return "#8d6e63"


def _contour_index_m(elevation_m: float | None) -> float | None:
    if not isinstance(elevation_m, float):
        return None
    return round(elevation_m / TERRAIN_CONTOUR_INTERVAL_M) * TERRAIN_CONTOUR_INTERVAL_M


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


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
        "pretrip_terrain_visualization": "terrain_visualization_ref",
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
        "dtm_coverage_summary_ref",
        "segment_dtm_coverage_ref",
        "risk_route_profile_ref",
        "risk_route_profile_metadata_ref",
        "risk_score_points_ref",
        "risk_score_points_metadata_ref",
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
    if request.imagery_min_zoom > request.imagery_max_zoom:
        raise ValueError("imagery_min_zoom must be <= imagery_max_zoom")
    if request.imagery_seed_max_tiles is not None and request.imagery_seed_max_tiles < 1:
        raise ValueError("imagery_seed_max_tiles must be positive when set")
    if request.osm_pbf_cache_ttl_days <= 0:
        raise ValueError("osm_pbf_cache_ttl_days must be greater than 0")


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


def _stable_projection_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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
