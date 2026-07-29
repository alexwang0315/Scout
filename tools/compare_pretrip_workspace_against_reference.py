#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


DEFAULT_KEY_METRICS = (
    "checkpoint_candidate_count",
    "segment_candidate_count",
    "route_note_candidate_count",
    "reference_track_count",
    "gpx_speed_filter_removed_track_point_count",
    "mcp_candidate_count",
    "mcp_ocr_label_count",
    "dtm_candidate_tile_count",
    "raster_label_ocr_status",
    "raster_label_ocr_label_count",
    "imagery_tile_cache_seed_status",
    "imagery_tile_cache_plan_tile_count",
    "overpass_candidate_count",
    "overpass_route_alignment_kept_gpx_point_count",
    "overpass_route_alignment_snapped_point_count",
    "risk_score_point_count",
    "risk_ribbon_segment_count",
    "calibrated_risk_heatmap_segment_count",
    "route_mileage_k_anchor_count",
    "mileage_tag_alignment_count",
    "reference_segment_timing_measurement_count",
    "reference_segment_timing_segment_count",
    "boss_point_count",
    "route_pressure_peak_count",
    "route_pressure_sample_count",
    "architecture_preparation_status",
    "architecture_preparation_stage",
    "architecture_observed_route_bin_count",
    "architecture_guidance_eligible_route_bin_count",
    "architecture_checkpoint_passage_timing_node_count",
)

TIME_SENSITIVE_ENVIRONMENT_METRICS = (
    "environment_risk_derivative_status",
    "cwa_external_api_calls_made",
    "cwa_fetched_at",
    "cwa_qpf_feature_count",
    "cwa_rain_observation_count",
    "cwa_warning_count",
    "cwa_weather_point_count",
    "gee_environment_status",
    "gee_external_api_calls_made",
    "gee_feature_package_segment_count",
    "gee_feature_package_status",
    "gee_raw_summary_sha256",
    "soil_moisture_feature_count",
    "antecedent_rain_feature_count",
)

REQUIRED_REFS = (
    "import_manifest_ref",
    "route_evidence_bundle_ref",
    "reference_segment_timing_ref",
    "layer_preparation_manifest_ref",
    "layer_validation_report_ref",
    "layer_map_projection_ref",
    "overpass_evidence_ref",
    "overpass_map_context_ref",
    "overpass_route_alignment_ref",
    "overpass_aligned_segment_candidates_ref",
    "risk_score_points_ref",
    "risk_ribbon_ref",
    "calibrated_risk_heatmap_ref",
    "environment_risk_derivatives_ref",
    "raster_label_ocr_output_ref",
    "raster_label_evidence_ref",
    "route_mileage_k_anchors_ref",
    "mileage_tag_alignment_ref",
    "boss_points_ref",
    "route_pressure_profile_ref",
    "reference_pace_energy_analysis_ref",
    "reference_pace_energy_map_geojson_ref",
    "architecture_preparation_manifest_ref",
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare a rebuilt Scout pretrip workspace against a reference."
    )
    parser.add_argument("--reference-root", required=True, type=Path)
    parser.add_argument("--candidate-root", required=True, type=Path)
    parser.add_argument(
        "--strict-counts",
        action="store_true",
        help="Fail when key metric values differ from the reference.",
    )
    args = parser.parse_args()

    reference = _load_project(args.reference_root)
    candidate = _load_project(args.candidate_root)
    report = {
        "artifact_kind": "pretrip_workspace_reference_comparison",
        "reference_root": str(args.reference_root),
        "candidate_root": str(args.candidate_root),
        "strict_counts": args.strict_counts,
        "missing_refs": _missing_refs(args.candidate_root, candidate),
        "metric_diffs": _metric_diffs(reference, candidate),
        "time_sensitive_metrics_excluded": list(TIME_SENSITIVE_ENVIRONMENT_METRICS),
        "file_counts": {
            "reference": _file_count(args.reference_root),
            "candidate": _file_count(args.candidate_root),
        },
    }
    report["status"] = "pass"
    if report["missing_refs"]:
        report["status"] = "fail"
    if args.strict_counts and report["metric_diffs"]:
        report["status"] = "fail"

    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


def _load_project(root: Path) -> dict[str, Any]:
    project_path = root / "project.json"
    if not project_path.is_file():
        raise SystemExit(f"project.json not found: {project_path}")
    return json.loads(project_path.read_text(encoding="utf-8"))


def _missing_refs(root: Path, project: dict[str, Any]) -> dict[str, str]:
    missing: dict[str, str] = {}
    for key in REQUIRED_REFS:
        ref = project.get(key)
        if not isinstance(ref, str) or not ref:
            missing[key] = "<missing project ref>"
            continue
        if not (root / ref).is_file():
            missing[key] = ref
    return missing


def _metric_diffs(
    reference: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    diffs: dict[str, dict[str, Any]] = {}
    for key in DEFAULT_KEY_METRICS:
        ref_value = reference.get(key)
        candidate_value = candidate.get(key)
        if ref_value != candidate_value:
            diffs[key] = {
                "reference": ref_value,
                "candidate": candidate_value,
            }
    return diffs


def _file_count(root: Path) -> int:
    return sum(1 for path in root.rglob("*") if path.is_file())


if __name__ == "__main__":
    sys.exit(main())
