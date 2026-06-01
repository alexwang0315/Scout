from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any


REQUIRED_PROJECT_REFS = {
    "source_inbox_manifest_ref": "inbox/source_manifest.json",
    "historical_gpx_source_index_ref": "sources/historical_gpx_source_index.json",
    "route_evidence_bundle_ref": "normalized/routes/route_evidence_bundle.json",
    "normalized_route_note_candidates_ref": "normalized/notes/gpx_route_note_candidates.json",
    "route_note_candidates_ref": "candidates/route_note_candidates.json",
    "gpx_speed_filter_report_ref": "outputs/gpx_speed_filter_report.json",
    "layer_preparation_manifest_ref": "outputs/layers/layer_preparation_manifest.json",
    "layer_preparation_summary_ref": "outputs/layers/layer_preparation_summary.json",
    "map_preparation_summary_ref": "outputs/layers/map_preparation_summary.json",
    "layer_map_projection_ref": "outputs/layers/projections/pretrip_map_layers.json",
    "web_case_query_plan_ref": "outputs/layers/plans/web_case_query_plan.json",
    "raster_label_plan_ref": "outputs/layers/plans/raster_label_plan.json",
    "overpass_vector_evidence_ref": "outputs/layers/normalized/overpass_vector_evidence.geojson",
    "terrain_route_samples_ref": "outputs/layers/normalized/terrain_route_samples.geojson",
    "web_case_evidence_ref": "outputs/layers/normalized/web_case_evidence.json",
    "raster_label_evidence_ref": "outputs/layers/normalized/raster_label_evidence.geojson",
    "gis_semantic_input_bundle_ref": "outputs/layers/semantic/gis_semantic_input_bundle.json",
    "gis_perception_ai_judgements_ref": "outputs/layers/semantic/gis_perception_ai_judgements.json",
    "gis_checkpoint_candidates_ref": "outputs/layers/candidates/gis_checkpoint_candidates.json",
    "ln_proposals_ref": "outputs/layers/candidates/ln_proposals.json",
    "poi_candidates_ref": "outputs/layers/candidates/poi_candidates.json",
    "terrain_risk_candidates_ref": "outputs/layers/candidates/terrain_risk_candidates.json",
    "detour_route_candidates_ref": "outputs/layers/candidates/detour_route_candidates.json",
    "risk_score_points_ref": "outputs/risk/risk_score_points.geojson",
    "risk_ribbon_ref": "outputs/risk/risk_ribbon.geojson",
    "calibrated_risk_heatmap_ref": "outputs/risk/calibrated_risk_heatmap.geojson",
    "imagery_manifest_ref": "",
    "raster_tile_manifest_ref": "",
}

REQUIRED_READY_LAYERS = {
    "imagery",
    "risk-score",
    "risk-ribbon",
    "risk-heatmap",
    "risk-delta",
    "route",
    "segments",
    "checkpoints",
    "reference-tracks",
    "route-notes",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--admin-base-url", default="")
    parser.add_argument("--admin-bearer-token-file", type=Path)
    parser.add_argument("--imagery-tile", default="14/13708/7063")
    args = parser.parse_args(argv)

    project_root = args.workspace_root.expanduser() / args.project_id
    errors: list[str] = []
    warnings: list[str] = []

    project = _load_json(project_root / "project.json", errors)
    if not project:
        _finish(errors, warnings, {})
        return 1

    _check_required_project_refs(project_root, project, errors)
    source_index = _load_json(
        project_root / project.get("historical_gpx_source_index_ref", ""),
        errors,
    )
    source_inbox = _load_json(
        project_root / project.get("source_inbox_manifest_ref", ""),
        errors,
    )
    route_bundle = _load_json(
        project_root / project.get("route_evidence_bundle_ref", ""),
        errors,
    )
    layer_manifest = _load_json(
        project_root / project.get("layer_preparation_manifest_ref", ""),
        errors,
    )
    layer_summary = _load_json(
        project_root / project.get("layer_preparation_summary_ref", ""),
        errors,
    )
    semantic_bundle = _load_json(
        project_root / project.get("gis_semantic_input_bundle_ref", ""),
        errors,
    )
    semantic_judgements = _load_json(
        project_root / project.get("gis_perception_ai_judgements_ref", ""),
        errors,
    )
    layer_candidate_artifacts = {
        key: _load_json(project_root / project.get(key, ""), errors)
        for key in (
            "gis_checkpoint_candidates_ref",
            "ln_proposals_ref",
            "poi_candidates_ref",
            "terrain_risk_candidates_ref",
            "detour_route_candidates_ref",
        )
    }
    layer_projection = _load_json(
        project_root / project.get("layer_map_projection_ref", ""),
        errors,
    )
    map_preparation_artifacts = {
        key: _load_json(project_root / project.get(key, ""), errors)
        for key in (
            "map_preparation_summary_ref",
            "web_case_query_plan_ref",
            "raster_label_plan_ref",
            "overpass_vector_evidence_ref",
            "terrain_route_samples_ref",
            "web_case_evidence_ref",
            "raster_label_evidence_ref",
        )
    }

    _check_source_indexes(source_index, source_inbox, errors)
    _check_route_evidence_bundle(route_bundle, errors)
    _check_layer_preparation(layer_manifest, layer_summary, errors, warnings)
    _check_map_preparation_artifacts(map_preparation_artifacts, route_bundle, errors)
    _check_layer_projection(layer_projection, errors)
    _check_semantic_input_bundle(semantic_bundle, route_bundle, project, errors)
    _check_semantic_judgements(
        semantic_judgements,
        semantic_bundle,
        project.get("gis_semantic_input_bundle_ref"),
        errors,
    )
    _check_layer_candidate_artifacts(layer_candidate_artifacts, errors)
    _check_risk_refs(project_root, project, errors)
    admin_headers = _admin_headers(args.admin_bearer_token_file, errors)
    api_summary = _check_admin_api(
        args.admin_base_url,
        args.project_id,
        admin_headers,
        errors,
        warnings,
    )
    tile_summary = _check_imagery_tile(
        args.admin_base_url,
        args.project_id,
        args.imagery_tile,
        admin_headers,
        errors,
        warnings,
    )

    summary = {
        "project_id": args.project_id,
        "project_root": project_root.as_posix(),
        "checkpoint_count": project.get("checkpoint_candidate_count"),
        "segment_count": project.get("segment_candidate_count"),
        "source_file_count": project.get("source_inbox_file_count"),
        "route_note_candidate_count": project.get("route_note_candidate_count"),
        "risk_score_point_count": project.get("risk_score_point_count"),
        "risk_ribbon_segment_count": project.get("risk_ribbon_segment_count"),
        "calibrated_risk_heatmap_segment_count": project.get(
            "calibrated_risk_heatmap_segment_count"
        ),
        "admin_api": api_summary,
        "imagery_tile": tile_summary,
        "imagery_projection": _imagery_projection_summary(layer_projection),
        "map_preparation": _map_preparation_artifact_summary(
            map_preparation_artifacts
        ),
        "semantic_judgements": _semantic_judgement_summary(semantic_judgements),
        "layer_candidates": {
            key: _candidate_artifact_summary(value)
            for key, value in layer_candidate_artifacts.items()
        },
    }
    return _finish(errors, warnings, summary)


def _load_json(path: Path, errors: list[str]) -> Any:
    if not path.is_file():
        errors.append(f"missing JSON artifact: {path}")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - diagnostic path
        errors.append(f"invalid JSON artifact: {path}: {exc}")
        return None


def _check_required_project_refs(
    project_root: Path,
    project: dict[str, Any],
    errors: list[str],
) -> None:
    for key, expected in REQUIRED_PROJECT_REFS.items():
        ref = project.get(key)
        if not ref:
            errors.append(f"project missing ref key: {key}")
            continue
        if key in {"imagery_manifest_ref", "raster_tile_manifest_ref"}:
            # Raster manifest refs are project-local in the current alpha fixture,
            # but this verifier allows future absolute data paths.
            path = Path(ref) if Path(ref).is_absolute() else project_root / ref
        else:
            path = project_root / ref
        if not path.exists():
            errors.append(f"project ref does not exist: {key}={ref}")
        if expected and ref != expected:
            errors.append(f"unexpected ref for {key}: {ref} != {expected}")


def _check_source_indexes(
    source_index: dict[str, Any] | None,
    source_inbox: dict[str, Any] | None,
    errors: list[str],
) -> None:
    if not source_index or not source_inbox:
        return
    if source_index.get("artifact_kind") != "pretrip_historical_gpx_source_index":
        errors.append("historical source index artifact_kind mismatch")
    if source_index.get("schema_version") != "historical_gpx_importer.v1":
        errors.append("historical source index schema_version mismatch")
    if source_index.get("raw_payloads_embedded") is not False:
        errors.append("historical source index embeds raw payloads")
    if source_index.get("source_file_count") != source_inbox.get("source_file_count"):
        errors.append("historical source index count does not match source inbox")
    for source in source_index.get("sources", []):
        if source.get("raw_payload_embedded_in_json") is not False:
            errors.append("historical source index source embeds raw GPX payload")
            break


def _check_route_evidence_bundle(
    route_bundle: dict[str, Any] | None,
    errors: list[str],
) -> None:
    if not route_bundle:
        return
    if route_bundle.get("artifact_kind") != "pretrip_historical_gpx_route_evidence_bundle":
        errors.append("route evidence bundle artifact_kind mismatch")
    if route_bundle.get("schema_version") != "historical_gpx_importer.v1":
        errors.append("route evidence bundle schema_version mismatch")
    refs = route_bundle.get("note_candidate_refs", [])
    if not refs or refs[0] != "normalized/notes/gpx_route_note_candidates.json":
        errors.append("route evidence bundle does not prioritize normalized route notes")
    scope = route_bundle.get("route_scope_for_map_preparation", {})
    if scope.get("corridor_policy") != "bbox_fetch_then_along_track_filter":
        errors.append("route evidence bundle corridor policy mismatch")
    if scope.get("route_corridor_m") != 500.0:
        errors.append("route evidence bundle route corridor mismatch")
    if scope.get("reference_track_corridor_m") != 300.0:
        errors.append("route evidence bundle reference corridor mismatch")
    boundary = route_bundle.get("boundary", {})
    if boundary.get("runtime_safety_truth") is not False:
        errors.append("route evidence bundle claims runtime safety truth")
    if boundary.get("safety_api_called") is not False:
        errors.append("route evidence bundle called safety API")


def _check_layer_preparation(
    layer_manifest: dict[str, Any] | None,
    layer_summary: dict[str, Any] | None,
    errors: list[str],
    warnings: list[str],
) -> None:
    if not layer_manifest or not layer_summary:
        return
    boundary = layer_manifest.get("boundary", {})
    if boundary.get("runtime_safety_truth") is not False:
        errors.append("layer preparation claims runtime safety truth")
    if boundary.get("phase1_runtime_mutation_allowed") is not False:
        errors.append("layer preparation allows Phase 1 runtime mutation")
    if layer_manifest.get("network_policy", {}).get("network_calls_made") is not False:
        errors.append("layer preparation made network calls")

    layers = {layer.get("layer_id"): layer for layer in layer_manifest.get("layers", [])}
    missing = sorted(REQUIRED_READY_LAYERS - set(layers))
    if missing:
        errors.append(f"layer preparation missing layer records: {missing}")
    for layer_id in sorted(REQUIRED_READY_LAYERS & set(layers)):
        layer = layers[layer_id]
        status = layer.get("status")
        if status not in {"ready", "ready_from_project_ref", "projection_ready"}:
            errors.append(f"layer {layer_id} not ready: {status}")
        source_ref_count = len(layer.get("source_refs", []))
        lifecycle_ref_count = (
            layer.get("lifecycle", {}).get("import", {}).get("source_ref_count")
        )
        if lifecycle_ref_count is not None and lifecycle_ref_count != source_ref_count:
            errors.append(
                f"layer {layer_id} lifecycle source_ref_count mismatch: "
                f"{lifecycle_ref_count} != {source_ref_count}"
            )
        lifecycle_counts = layer.get("lifecycle", {}).get("summarize", {}).get("counts")
        if isinstance(lifecycle_counts, dict) and lifecycle_counts != layer.get("counts", {}):
            errors.append(f"layer {layer_id} lifecycle summarize counts are stale")

    route_notes = layers.get("route-notes", {})
    note_ref_keys = [ref.get("project_ref_key") for ref in route_notes.get("source_refs", [])]
    if note_ref_keys[:1] != ["normalized_route_note_candidates_ref"]:
        errors.append("route-notes layer does not prioritize normalized route notes")
    if "route_note_candidates_ref" not in note_ref_keys:
        warnings.append("route-notes layer no longer includes legacy route note ref")

    validation = layer_manifest.get("validation", {})
    if validation.get("blocker_count") not in {0, None}:
        errors.append(f"layer validation blockers present: {validation.get('blocker_count')}")
    warning_count = validation.get("warning_count")
    if warning_count:
        warnings.append(f"layer validation warnings present: {warning_count}")


def _check_layer_projection(
    layer_projection: dict[str, Any] | None,
    errors: list[str],
) -> None:
    if not layer_projection:
        return
    layers = {
        layer.get("layer_id"): layer
        for layer in layer_projection.get("layers", [])
        if isinstance(layer, dict)
    }
    imagery = layers.get("imagery")
    if not imagery:
        errors.append("map layer projection missing imagery layer")
        return
    bbox = imagery.get("raster_bbox_wgs84")
    if not isinstance(bbox, dict):
        errors.append("imagery projection missing raster_bbox_wgs84")
    elif not all(key in bbox for key in ("west", "south", "east", "north")):
        errors.append("imagery projection raster_bbox_wgs84 is incomplete")
    if imagery.get("raster_coverage_policy") != "render_intersecting_tiles_only":
        errors.append("imagery projection missing intersecting-tile coverage policy")
    if not imagery.get("raster_tile_zoom_range"):
        errors.append("imagery projection missing raster_tile_zoom_range")
    if not imagery.get("local_raster_tile_url_template"):
        errors.append("imagery projection missing local raster tile template")


def _check_map_preparation_artifacts(
    artifacts: dict[str, dict[str, Any] | None],
    route_bundle: dict[str, Any] | None,
    errors: list[str],
) -> None:
    expected_route_scope_ref = (
        (route_bundle or {}).get("source_ref")
        or "normalized/routes/route_evidence_bundle.json"
    )
    summary = artifacts.get("map_preparation_summary_ref")
    if summary:
        if summary.get("artifact_kind") != "pretrip_route_corridor_map_preparation_summary":
            errors.append("map preparation summary artifact_kind mismatch")
        if summary.get("schema_version") != "route_corridor_map_preparation.v1":
            errors.append("map preparation summary schema_version mismatch")
        if summary.get("route_scope_ref") != expected_route_scope_ref:
            errors.append("map preparation summary route_scope_ref mismatch")
        _check_candidate_boundary(summary, "map preparation summary", errors)

    for key, artifact_kind in {
        "web_case_query_plan_ref": "pretrip_web_case_query_plan",
        "raster_label_plan_ref": "pretrip_raster_label_plan",
        "web_case_evidence_ref": "pretrip_web_case_evidence",
    }.items():
        artifact = artifacts.get(key)
        if not artifact:
            continue
        if artifact.get("artifact_kind") != artifact_kind:
            errors.append(f"{key} artifact_kind mismatch")
        if artifact.get("schema_version") != "route_corridor_map_preparation.v1":
            errors.append(f"{key} schema_version mismatch")
        if artifact.get("route_scope_ref") != expected_route_scope_ref:
            errors.append(f"{key} route_scope_ref mismatch")
        _check_candidate_boundary(artifact, key, errors)

    for key, artifact_kind in {
        "overpass_vector_evidence_ref": "pretrip_overpass_vector_evidence",
        "terrain_route_samples_ref": "pretrip_terrain_route_samples",
        "raster_label_evidence_ref": "pretrip_raster_label_evidence",
    }.items():
        artifact = artifacts.get(key)
        if not artifact:
            continue
        if artifact.get("type") != "FeatureCollection":
            errors.append(f"{key} is not a GeoJSON FeatureCollection")
        if artifact.get("artifact_kind") != artifact_kind:
            errors.append(f"{key} artifact_kind mismatch")
        if artifact.get("schema_version") != "route_corridor_map_preparation.v1":
            errors.append(f"{key} schema_version mismatch")
        if artifact.get("route_scope_ref") != expected_route_scope_ref:
            errors.append(f"{key} route_scope_ref mismatch")
        _check_candidate_boundary(artifact, key, errors)


def _check_candidate_boundary(
    artifact: dict[str, Any],
    label: str,
    errors: list[str],
) -> None:
    boundary = artifact.get("boundary", {})
    if boundary.get("candidate_only") is not True:
        errors.append(f"{label} is not candidate-only")
    if boundary.get("runtime_safety_truth") is not False:
        errors.append(f"{label} claims runtime safety truth")
    if boundary.get("phase1_runtime_mutation_allowed") is not False:
        errors.append(f"{label} allows Phase 1 runtime mutation")
    if boundary.get("raw_gpx_embedded_in_json") is not False:
        errors.append(f"{label} embeds raw GPX")


def _check_semantic_input_bundle(
    semantic_bundle: dict[str, Any] | None,
    route_bundle: dict[str, Any] | None,
    project: dict[str, Any],
    errors: list[str],
) -> None:
    if not semantic_bundle:
        return
    if semantic_bundle.get("artifact_kind") != "pretrip_gis_semantic_input_bundle":
        errors.append("semantic input bundle artifact_kind mismatch")
    if semantic_bundle.get("schema_version") != "route_corridor_map_preparation.v1":
        errors.append("semantic input bundle schema_version mismatch")
    route_scope_ref = semantic_bundle.get("route_scope_ref")
    expected_route_scope_ref = (
        (route_bundle or {}).get("source_ref")
        or "normalized/routes/route_evidence_bundle.json"
    )
    if route_bundle and route_scope_ref != expected_route_scope_ref:
        errors.append(
            "semantic input bundle route_scope_ref does not match route evidence bundle"
        )
    counts = semantic_bundle.get("counts", {})
    if int(counts.get("evidence_item_count") or 0) <= 0:
        errors.append("semantic input bundle has no evidence items")
    source_kind_counts = counts.get("source_kind_counts", {})
    if int(source_kind_counts.get("gpx_route_note") or 0) <= 0:
        errors.append("semantic input bundle has no GPX route-note evidence")
    expected_rest_area_count = int(project.get("rest_area_candidate_count") or 0)
    if expected_rest_area_count:
        actual_rest_area_count = int(source_kind_counts.get("rest_area_candidate") or 0)
        if actual_rest_area_count != expected_rest_area_count:
            errors.append(
                "semantic input bundle rest-area evidence count mismatch: "
                f"{actual_rest_area_count} != {expected_rest_area_count}"
            )
    boundary = semantic_bundle.get("boundary", {})
    if boundary.get("candidate_only") is not True:
        errors.append("semantic input bundle is not candidate-only")
    if boundary.get("runtime_safety_truth") is not False:
        errors.append("semantic input bundle claims runtime safety truth")
    if boundary.get("raw_gpx_embedded_in_json") is not False:
        errors.append("semantic input bundle embeds raw GPX")
    if boundary.get("raw_raster_embedded_in_json") is not False:
        errors.append("semantic input bundle embeds raw raster")
    for item in semantic_bundle.get("evidence_items", [])[:200]:
        if not item.get("source_refs"):
            errors.append("semantic input evidence item missing source_refs")
            break
        if item.get("runtime_safety_truth") is not False:
            errors.append("semantic input evidence item claims runtime safety truth")
            break


def _check_semantic_judgements(
    semantic_judgements: dict[str, Any] | None,
    semantic_bundle: dict[str, Any] | None,
    input_bundle_ref: str | None,
    errors: list[str],
) -> None:
    if not semantic_judgements:
        return
    if semantic_judgements.get("artifact_kind") != "gis_perception_ai_judgements":
        errors.append("semantic judgements artifact_kind mismatch")
    if semantic_judgements.get("schema_version") != "gis_perception_ai_judgements.v1":
        errors.append("semantic judgements schema_version mismatch")
    if semantic_judgements.get("input_bundle_ref") != input_bundle_ref:
        errors.append("semantic judgements input_bundle_ref mismatch")
    input_count = int(
        (semantic_bundle or {}).get("counts", {}).get("evidence_item_count") or 0
    )
    judgement_count = int(semantic_judgements.get("judgement_count") or 0)
    if input_count and judgement_count != input_count:
        errors.append(
            f"semantic judgement count mismatch: {judgement_count} != {input_count}"
        )
    if semantic_judgements.get("live_model_call_performed") is not False:
        errors.append("semantic judgements performed a live model call")
    if semantic_judgements.get("network_calls_allowed") is not False:
        errors.append("semantic judgements allow network calls in fixture mode")
    if semantic_judgements.get("raw_model_output_embedded") is not False:
        errors.append("semantic judgements embed raw model output")
    boundary = semantic_judgements.get("boundary", {})
    if boundary.get("candidate_only") is not True:
        errors.append("semantic judgements are not candidate-only")
    if boundary.get("observed_fact") is not False:
        errors.append("semantic judgements claim observed facts")
    if boundary.get("runtime_safety_truth") is not False:
        errors.append("semantic judgements claim runtime safety truth")
    if boundary.get("phase1_runtime_mutation_allowed") is not False:
        errors.append("semantic judgements allow Phase 1 runtime mutation")
    for judgement in semantic_judgements.get("judgements", [])[:200]:
        if not judgement.get("source_evidence_refs"):
            errors.append("semantic judgement missing source_evidence_refs")
            break
        if judgement.get("requires_human_review") is not True:
            errors.append("semantic judgement bypasses human review")
            break
        if judgement.get("runtime_safety_truth") is not False:
            errors.append("semantic judgement claims runtime safety truth")
            break


def _check_layer_candidate_artifacts(
    artifacts: dict[str, dict[str, Any] | None],
    errors: list[str],
) -> None:
    expected = {
        "gis_checkpoint_candidates_ref": (
            "pretrip_layer_gis_checkpoint_candidates",
            "candidates",
        ),
        "ln_proposals_ref": ("pretrip_layer_ln_proposals", "proposals"),
        "poi_candidates_ref": ("pretrip_layer_poi_candidates", "candidates"),
        "terrain_risk_candidates_ref": (
            "pretrip_layer_terrain_risk_candidates",
            "candidates",
        ),
        "detour_route_candidates_ref": (
            "pretrip_layer_detour_route_candidates",
            "candidates",
        ),
    }
    for ref_key, (artifact_kind, candidate_key) in expected.items():
        artifact = artifacts.get(ref_key)
        if not artifact:
            continue
        if artifact.get("artifact_kind") != artifact_kind:
            errors.append(f"{ref_key} artifact_kind mismatch")
        if artifact.get("schema_version") != "route_corridor_map_preparation.candidates.v1":
            errors.append(f"{ref_key} schema_version mismatch")
        boundary = artifact.get("boundary", {})
        if boundary.get("candidate_only") is not True:
            errors.append(f"{ref_key} is not candidate-only")
        if boundary.get("runtime_safety_truth") is not False:
            errors.append(f"{ref_key} claims runtime safety truth")
        if boundary.get("phase1_runtime_mutation_allowed") is not False:
            errors.append(f"{ref_key} allows Phase 1 runtime mutation")
        candidates = artifact.get(candidate_key, [])
        if not isinstance(candidates, list):
            errors.append(f"{ref_key} candidate list is not a list")
            continue
        counts = artifact.get("counts", {})
        if int(counts.get("candidate_count") or 0) != len(candidates):
            errors.append(f"{ref_key} candidate_count mismatch")
        if int(counts.get("runtime_safety_truth_count") or 0) != 0:
            errors.append(f"{ref_key} has runtime safety truth candidates")
        for candidate in candidates[:200]:
            if candidate.get("candidate_only") is not True:
                errors.append(f"{ref_key} candidate is not candidate-only")
                break
            if candidate.get("runtime_safety_truth") is not False:
                errors.append(f"{ref_key} candidate claims runtime safety truth")
                break
            if candidate.get("requires_human_review") is not True:
                errors.append(f"{ref_key} candidate bypasses human review")
                break
            if not candidate.get("source_refs") and not candidate.get("source_evidence_refs"):
                errors.append(f"{ref_key} candidate missing source refs")
                break


def _check_risk_refs(project_root: Path, project: dict[str, Any], errors: list[str]) -> None:
    for key in (
        "risk_score_points_ref",
        "risk_ribbon_ref",
        "risk_ribbon_metadata_ref",
        "calibrated_risk_heatmap_ref",
        "calibrated_risk_heatmap_metadata_ref",
    ):
        ref = project.get(key)
        if not ref or not (project_root / ref).is_file():
            errors.append(f"missing risk ref: {key}={ref}")
    if int(project.get("risk_score_point_count") or 0) <= 0:
        errors.append("risk score point count is empty")
    if int(project.get("risk_ribbon_segment_count") or 0) <= 0:
        errors.append("risk ribbon segment count is empty")
    if int(project.get("calibrated_risk_heatmap_segment_count") or 0) <= 0:
        errors.append("calibrated risk heatmap segment count is empty")


def _check_admin_api(
    admin_base_url: str,
    project_id: str,
    headers: dict[str, str],
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    if not admin_base_url:
        return {"checked": False}
    url = admin_base_url.rstrip("/") + f"/admin/pretrip/projects/{project_id}"
    try:
        request = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        errors.append(f"admin API check failed: {url}: {exc}")
        return {"checked": True, "ok": False}
    risk_counts = {
        key: payload.get(key, {}).get("counts", {})
        for key in ("risk_score", "risk_ribbon", "risk_heatmap", "risk_delta")
    }
    for key, risk in risk_counts.items():
        if risk.get("runtime_safety_truth") is True:
            errors.append(f"admin API {key} claims runtime safety truth")
    if len(payload.get("checkpoints", [])) <= 0:
        errors.append("admin API returned no checkpoints")
    if len(payload.get("segments", [])) <= 0:
        errors.append("admin API returned no segments")
    return {
        "checked": True,
        "ok": True,
        "checkpoint_count": len(payload.get("checkpoints", [])),
        "segment_count": len(payload.get("segments", [])),
        "risk_counts": risk_counts,
    }


def _check_imagery_tile(
    admin_base_url: str,
    project_id: str,
    tile: str,
    headers: dict[str, str],
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    if not admin_base_url:
        return {"checked": False}
    zxy = tile.strip("/")
    url = (
        admin_base_url.rstrip("/")
        + f"/admin/tiles/imagery/{project_id}/imagery/{zxy}.png?verify=1"
    )
    try:
        request = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read()
            source = response.headers.get("x-scout-tile-source", "")
            content_type = response.headers.get("content-type", "")
    except Exception as exc:
        errors.append(f"imagery tile check failed: {url}: {exc}")
        return {"checked": True, "ok": False}
    if source != "local_cache":
        errors.append(f"imagery tile is not local_cache: {source}")
    if content_type != "image/png":
        errors.append(f"imagery tile content-type is not image/png: {content_type}")
    if len(body) <= 1024:
        errors.append(f"imagery tile payload too small: {len(body)} bytes")
    return {
        "checked": True,
        "ok": source == "local_cache" and content_type == "image/png" and len(body) > 1024,
        "source": source,
        "content_type": content_type,
        "bytes": len(body),
        "url": url,
    }


def _imagery_projection_summary(layer_projection: dict[str, Any] | None) -> dict[str, Any]:
    if not layer_projection:
        return {"available": False}
    imagery = next(
        (
            layer
            for layer in layer_projection.get("layers", [])
            if isinstance(layer, dict) and layer.get("layer_id") == "imagery"
        ),
        {},
    )
    return {
        "available": bool(imagery),
        "raster_bbox_wgs84": imagery.get("raster_bbox_wgs84"),
        "raster_tile_zoom_range": imagery.get("raster_tile_zoom_range"),
        "raster_tile_count": imagery.get("raster_tile_count"),
        "coverage_policy": imagery.get("raster_coverage_policy"),
    }


def _semantic_judgement_summary(
    semantic_judgements: dict[str, Any] | None,
) -> dict[str, Any]:
    if not semantic_judgements:
        return {"available": False}
    return {
        "available": True,
        "artifact_kind": semantic_judgements.get("artifact_kind"),
        "schema_version": semantic_judgements.get("schema_version"),
        "input_bundle_ref": semantic_judgements.get("input_bundle_ref"),
        "judgement_count": semantic_judgements.get("judgement_count"),
        "live_model_call_performed": semantic_judgements.get(
            "live_model_call_performed"
        ),
        "network_calls_allowed": semantic_judgements.get("network_calls_allowed"),
    }


def _candidate_artifact_summary(artifact: dict[str, Any] | None) -> dict[str, Any]:
    if not artifact:
        return {"available": False}
    return {
        "available": True,
        "artifact_kind": artifact.get("artifact_kind"),
        "schema_version": artifact.get("schema_version"),
        "candidate_count": artifact.get("counts", {}).get("candidate_count"),
        "runtime_safety_truth_count": artifact.get("counts", {}).get(
            "runtime_safety_truth_count"
        ),
    }


def _map_preparation_artifact_summary(
    artifacts: dict[str, dict[str, Any] | None],
) -> dict[str, Any]:
    return {
        key: {
            "available": bool(value),
            "artifact_kind": (value or {}).get("artifact_kind"),
            "schema_version": (value or {}).get("schema_version"),
            "status": (value or {}).get("status"),
            "feature_count": (value or {}).get("counts", {}).get("feature_count"),
            "evidence_item_count": (value or {})
            .get("counts", {})
            .get("evidence_item_count"),
        }
        for key, value in artifacts.items()
    }


def _admin_headers(token_file: Path | None, errors: list[str]) -> dict[str, str]:
    if token_file is None:
        return {}
    try:
        token = token_file.expanduser().read_text(encoding="utf-8").strip()
    except Exception as exc:
        errors.append(f"admin bearer token file unreadable: {token_file}: {exc}")
        return {}
    if not token:
        errors.append(f"admin bearer token file is empty: {token_file}")
        return {}
    return {"Authorization": f"Bearer {token}"}


def _finish(errors: list[str], warnings: list[str], summary: dict[str, Any]) -> int:
    result = {
        "ok": not errors,
        "summary": summary,
        "warning_count": len(warnings),
        "warnings": warnings,
        "error_count": len(errors),
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
