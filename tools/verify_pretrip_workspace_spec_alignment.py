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

WORKSPACE_LAYOUT_SCHEMA_VERSION = "scout.workspace.v1"

REQUIRED_PRETRIP_DIRS = {
    "inbox",
    "sources",
    "normalized",
    "candidates",
    "reviews",
    "outputs",
}

REQUIRED_RUNTIME_SESSION_PATHS = {
    "session_manifest": "session_manifest.json",
    "event_index": "events/event_index.jsonl",
    "team_status": "team/team_status_events.jsonl",
    "recorder_manifest": "recorder/recorder_manifest.json",
    "integrity_chain": "recorder/append_only_integrity_chain.jsonl",
    "transport_ingress": "transports/ingress_evidence_index.jsonl",
    "transport_egress": "transports/egress_evidence_index.jsonl",
    "hardware_access": "hardware/hardware_resource_access_events.jsonl",
    "black_box_manifest": "black_box/black_box_manifest.json",
    "black_box_event_index": "black_box/black_box_event_index.jsonl",
}

REQUIRED_COMPLETED_TRIP_PATHS = {
    "trip_manifest": "trip_manifest.json",
    "recording_set_manifest": "recorded/recording_set_manifest.json",
}

REQUIRED_COMPLETED_TRIP_OUTPUTS = {
    "capability_timeline": "outputs/capability_timeline.json",
    "capability_capsule": "outputs/capability_capsule.json",
}

REQUIRED_BLACK_BOX_EXPORT_PATHS = {
    "export_manifest": "black_box_export_manifest.json",
    "redaction_policy": "redaction_policy.json",
    "checksums": "checksums.sha256",
    "timeline_index": "timeline_index.jsonl",
    "source_session_manifest": "bundle/session_manifest.json",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--project-id")
    parser.add_argument(
        "--skip-pretrip",
        action="store_true",
        help="Skip active pretrip workspace checks and only run optional scopes.",
    )
    parser.add_argument("--runtime-session-root", type=Path)
    parser.add_argument("--runtime-session-id")
    parser.add_argument("--completed-trip-root", type=Path)
    parser.add_argument("--trip-id")
    parser.add_argument("--black-box-export-root", type=Path)
    parser.add_argument("--black-box-session-id")
    parser.add_argument("--admin-base-url", default="")
    parser.add_argument("--admin-bearer-token-file", type=Path)
    parser.add_argument("--imagery-tile", default="14/13708/7063")
    parser.add_argument(
        "--allow-network-calls",
        action="store_true",
        help=(
            "Allow connected preparation manifests that record external fetches. "
            "Keep this off for CI fixtures and no-network alpha checks."
        ),
    )
    args = parser.parse_args(argv)

    errors: list[str] = []
    warnings: list[str] = []

    _validate_scope_args(parser, args)

    project: dict[str, Any] = {}
    project_root: Path | None = None
    route_bundle: dict[str, Any] | None = None
    layer_projection: dict[str, Any] | None = None
    layer_manifest: dict[str, Any] | None = None
    semantic_judgements: dict[str, Any] | None = None
    map_preparation_artifacts: dict[str, dict[str, Any] | None] = {}
    layer_candidate_artifacts: dict[str, dict[str, Any] | None] = {}
    api_summary = {"checked": False}
    tile_summary = {"checked": False}

    if not args.skip_pretrip:
        assert args.workspace_root is not None
        assert args.project_id is not None
        project_root = args.workspace_root.expanduser() / args.project_id
        project = _load_json(project_root / "project.json", errors) or {}
        if project:
            _check_pretrip_workspace_layout(project_root, project, errors, warnings)
            _check_required_project_refs(project_root, project, errors)
            source_index = _load_json_ref(
                project_root,
                project,
                "historical_gpx_source_index_ref",
                errors,
            )
            source_inbox = _load_json_ref(
                project_root,
                project,
                "source_inbox_manifest_ref",
                errors,
            )
            route_bundle = _load_json_ref(
                project_root,
                project,
                "route_evidence_bundle_ref",
                errors,
            )
            layer_manifest = _load_json_ref(
                project_root,
                project,
                "layer_preparation_manifest_ref",
                errors,
            )
            layer_summary = _load_json_ref(
                project_root,
                project,
                "layer_preparation_summary_ref",
                errors,
            )
            semantic_bundle = _load_json_ref(
                project_root,
                project,
                "gis_semantic_input_bundle_ref",
                errors,
            )
            semantic_judgements = _load_json_ref(
                project_root,
                project,
                "gis_perception_ai_judgements_ref",
                errors,
            )
            layer_candidate_artifacts = {
                key: _load_json_ref(project_root, project, key, errors)
                for key in (
                    "gis_checkpoint_candidates_ref",
                    "ln_proposals_ref",
                    "poi_candidates_ref",
                    "terrain_risk_candidates_ref",
                    "detour_route_candidates_ref",
                )
            }
            layer_projection = _load_json_ref(
                project_root,
                project,
                "layer_map_projection_ref",
                errors,
            )
            map_preparation_artifacts = {
                key: _load_json_ref(project_root, project, key, errors)
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
            _check_layer_preparation(
                layer_manifest,
                layer_summary,
                errors,
                warnings,
                allow_network_calls=args.allow_network_calls,
            )
            _check_map_preparation_artifacts(
                map_preparation_artifacts,
                route_bundle,
                errors,
            )
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

    runtime_session_summary = _check_runtime_session_scope(args, errors, warnings)
    completed_trip_summary = _check_completed_trip_scope(args, errors, warnings)
    black_box_export_summary = _check_black_box_export_scope(args, errors, warnings)

    if args.skip_pretrip and not any(
        item.get("checked")
        for item in (
            runtime_session_summary,
            completed_trip_summary,
            black_box_export_summary,
        )
    ):
        errors.append("no verifier scope selected")

    summary = {
        "layout_contract": WORKSPACE_LAYOUT_SCHEMA_VERSION,
        "project_id": args.project_id,
        "project_root": project_root.as_posix() if project_root else None,
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
        "network_policy": (layer_manifest or {}).get("network_policy", {}),
        "map_preparation": _map_preparation_artifact_summary(
            map_preparation_artifacts
        ),
        "semantic_judgements": _semantic_judgement_summary(semantic_judgements),
        "layer_candidates": {
            key: _candidate_artifact_summary(value)
            for key, value in layer_candidate_artifacts.items()
        },
        "runtime_session": runtime_session_summary,
        "completed_trip": completed_trip_summary,
        "black_box_export": black_box_export_summary,
    }
    return _finish(errors, warnings, summary)


def _validate_scope_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if not args.skip_pretrip and (not args.workspace_root or not args.project_id):
        parser.error("--workspace-root and --project-id are required unless --skip-pretrip")
    if bool(args.runtime_session_root) != bool(args.runtime_session_id):
        parser.error("--runtime-session-root and --runtime-session-id must be provided together")
    if bool(args.completed_trip_root) != bool(args.trip_id):
        parser.error("--completed-trip-root and --trip-id must be provided together")
    if args.black_box_export_root and not (
        args.black_box_session_id or args.runtime_session_id
    ):
        parser.error(
            "--black-box-export-root requires --black-box-session-id or --runtime-session-id"
        )
    if args.black_box_session_id and not args.black_box_export_root:
        parser.error("--black-box-session-id requires --black-box-export-root")


def _load_json(path: Path, errors: list[str]) -> Any:
    if not path.is_file():
        errors.append(f"missing JSON artifact: {path}")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - diagnostic path
        errors.append(f"invalid JSON artifact: {path}: {exc}")
        return None


def _load_json_ref(
    project_root: Path,
    project: dict[str, Any],
    ref_key: str,
    errors: list[str],
) -> Any:
    ref = project.get(ref_key)
    if not ref:
        return None
    path = Path(ref) if Path(ref).is_absolute() else project_root / ref
    return _load_json(path, errors)


def _check_pretrip_workspace_layout(
    project_root: Path,
    project: dict[str, Any],
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    missing_dirs = [
        name for name in sorted(REQUIRED_PRETRIP_DIRS) if not (project_root / name).is_dir()
    ]
    for name in missing_dirs:
        errors.append(f"pretrip workspace missing required directory: {name}")

    schema_version = project.get("schema_version")
    if schema_version and schema_version != WORKSPACE_LAYOUT_SCHEMA_VERSION:
        errors.append(f"project schema_version mismatch: {schema_version}")
    elif not schema_version:
        warnings.append("project missing schema_version for workspace layout contract")

    workspace_kind = project.get("workspace_kind")
    if workspace_kind and workspace_kind != "pretrip":
        errors.append(f"project workspace_kind mismatch: {workspace_kind}")
    elif not workspace_kind:
        warnings.append("project missing workspace_kind=pretrip")

    _check_optional_false_boundary(
        project,
        "runtime_safety_truth",
        "project",
        errors,
        warnings,
    )
    _check_optional_false_boundary(
        project,
        "phase1_runtime_mutation_allowed",
        "project",
        errors,
        warnings,
    )
    _check_optional_false_boundary(
        project,
        "phase2_brain_writeback_allowed",
        "project",
        errors,
        warnings,
    )

    ai_root = project_root / "ai"
    if ai_root.exists():
        _check_workspace_ai_assets(ai_root, project_root, errors)

    return {
        "checked": True,
        "missing_dirs": missing_dirs,
        "schema_version": schema_version,
        "workspace_kind": workspace_kind,
    }


def _check_optional_false_boundary(
    payload: dict[str, Any],
    key: str,
    label: str,
    errors: list[str],
    warnings: list[str],
) -> None:
    value = payload.get(key)
    if value is True:
        errors.append(f"{label} sets {key}=true")
    elif value is None:
        warnings.append(f"{label} missing {key}=false boundary flag")


def _check_workspace_ai_assets(
    ai_root: Path,
    project_root: Path,
    errors: list[str],
) -> None:
    approved_root = ai_root / "approved"
    if not approved_root.exists():
        return
    decision_log = project_root / "reviews" / "ai_asset_install_decisions.jsonl"
    if any(approved_root.rglob("*")) and not decision_log.is_file():
        errors.append(
            "workspace ai approved assets exist without reviews/ai_asset_install_decisions.jsonl"
        )


def _check_runtime_session_scope(
    args: argparse.Namespace,
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    if not args.runtime_session_root or not args.runtime_session_id:
        return {"checked": False}
    session_root = args.runtime_session_root.expanduser() / args.runtime_session_id
    return _check_runtime_session_layout(session_root, errors, warnings)


def _check_runtime_session_layout(
    session_root: Path,
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "checked": True,
        "session_root": session_root.as_posix(),
        "required_path_count": len(REQUIRED_RUNTIME_SESSION_PATHS),
    }
    if not session_root.is_dir():
        errors.append(f"runtime session root does not exist: {session_root}")
        summary["exists"] = False
        return summary
    summary["exists"] = True

    missing = _check_required_paths(session_root, REQUIRED_RUNTIME_SESSION_PATHS, errors)
    summary["missing_required_paths"] = missing

    session_manifest = _load_json(session_root / "session_manifest.json", errors)
    recorder_manifest = _load_json(
        session_root / "recorder" / "recorder_manifest.json",
        errors,
    )
    black_box_manifest = _load_json(
        session_root / "black_box" / "black_box_manifest.json",
        errors,
    )
    if isinstance(session_manifest, dict):
        if session_manifest.get("workspace_kind") not in {None, "runtime_session"}:
            errors.append("runtime session_manifest workspace_kind mismatch")
        _check_optional_false_boundary(
            session_manifest,
            "pretrip_candidate_mutation_allowed",
            "runtime session_manifest",
            errors,
            warnings,
        )
    if isinstance(recorder_manifest, dict):
        if recorder_manifest.get("append_only") is not True:
            errors.append("runtime recorder manifest must declare append_only=true")
    if isinstance(black_box_manifest, dict):
        if black_box_manifest.get("source_of_safety_decisions") is True:
            errors.append("black box manifest claims safety decision authority")

    jsonl_summaries = {
        "event_index": _check_jsonl_records(
            session_root / "events" / "event_index.jsonl",
            "runtime event_index",
            errors,
            warnings,
            required_any_timestamp=True,
            required_fields=("sequence", "event_id"),
        ),
        "transport_ingress": _check_jsonl_records(
            session_root / "transports" / "ingress_evidence_index.jsonl",
            "runtime transport ingress",
            errors,
            warnings,
            required_any_timestamp=True,
            required_fields=("sequence",),
            false_fields=("credential_value_exposed",),
            one_of_fields=(("payload_sha256", "payload_hash", "raw_artifact_path"),),
        ),
        "transport_egress": _check_jsonl_records(
            session_root / "transports" / "egress_evidence_index.jsonl",
            "runtime transport egress",
            errors,
            warnings,
            required_any_timestamp=True,
            required_fields=("sequence",),
            false_fields=("credential_value_exposed",),
            one_of_fields=(("payload_sha256", "payload_hash", "raw_artifact_path"),),
        ),
        "hardware_access": _check_jsonl_records(
            session_root / "hardware" / "hardware_resource_access_events.jsonl",
            "runtime hardware access",
            errors,
            warnings,
            required_any_timestamp=True,
            required_fields=("sequence", "hardware_interface", "access_status"),
        ),
        "team_status": _check_jsonl_records(
            session_root / "team" / "team_status_events.jsonl",
            "runtime team status",
            errors,
            warnings,
            required_any_timestamp=True,
            required_fields=("sequence", "member_ref", "status"),
        ),
        "black_box_event_index": _check_jsonl_records(
            session_root / "black_box" / "black_box_event_index.jsonl",
            "runtime black box event index",
            errors,
            warnings,
            required_any_timestamp=True,
            required_fields=("sequence", "event_ref"),
        ),
    }
    summary["jsonl"] = jsonl_summaries

    svr_root = session_root / "sensor_logs" / "journey.scout-svr"
    if svr_root.exists():
        _check_scout_sensor_vitals_record(svr_root, errors, warnings)
        summary["scout_svr_checked"] = True
    else:
        summary["scout_svr_checked"] = False
    return summary


def _check_scout_sensor_vitals_record(
    svr_root: Path,
    errors: list[str],
    warnings: list[str],
) -> None:
    required = {
        "manifest": "manifest.json",
        "observations": "observations.jsonl",
        "application_routes": "application_routes.jsonl",
        "filter_outputs": "filter_outputs.jsonl",
        "navigation_estimates": "navigation_estimates.jsonl",
        "vitals": "vitals.jsonl",
        "transport_ingress": "transport_ingress_index.jsonl",
        "transport_egress": "transport_egress_index.jsonl",
    }
    _check_required_paths(svr_root, required, errors)
    manifest = _load_json(svr_root / "manifest.json", errors)
    if isinstance(manifest, dict):
        if manifest.get("artifact_kind") != "scout_sensor_vitals_record":
            errors.append("Scout SVR manifest artifact_kind mismatch")
        if manifest.get("artifact_version") != "scout_sensor_vitals_record.v0":
            errors.append("Scout SVR manifest artifact_version mismatch")
    _check_jsonl_records(
        svr_root / "observations.jsonl",
        "Scout SVR observations",
        errors,
        warnings,
        required_any_timestamp=True,
        required_fields=("sequence",),
    )


def _check_completed_trip_scope(
    args: argparse.Namespace,
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    if not args.completed_trip_root or not args.trip_id:
        return {"checked": False}
    trip_root = args.completed_trip_root.expanduser() / args.trip_id
    return _check_completed_trip_layout(trip_root, errors, warnings)


def _check_completed_trip_layout(
    trip_root: Path,
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    summary: dict[str, Any] = {"checked": True, "trip_root": trip_root.as_posix()}
    if not trip_root.is_dir():
        errors.append(f"completed trip root does not exist: {trip_root}")
        summary["exists"] = False
        return summary
    summary["exists"] = True
    summary["missing_required_paths"] = _check_required_paths(
        trip_root,
        REQUIRED_COMPLETED_TRIP_PATHS,
        errors,
    )

    trip_manifest = _load_json(trip_root / "trip_manifest.json", errors)
    recording_manifest = _load_json(
        trip_root / "recorded" / "recording_set_manifest.json",
        errors,
    )
    if isinstance(trip_manifest, dict):
        if trip_manifest.get("workspace_kind") not in {None, "completed_trip"}:
            errors.append("completed trip_manifest workspace_kind mismatch")
        _check_optional_false_boundary(
            trip_manifest,
            "pretrip_candidate_mutation_allowed",
            "completed trip_manifest",
            errors,
            warnings,
        )
    if isinstance(recording_manifest, dict):
        if recording_manifest.get("recording_set_storage_allows_multiple_gpx") is False:
            errors.append("recording set manifest disallows multiple GPX storage")

    gpx_files = sorted((trip_root / "recorded").rglob("*.gpx"))
    summary["recorded_gpx_count"] = len(gpx_files)
    if not gpx_files:
        errors.append("completed trip recorded set contains no GPX files")

    outputs_root = trip_root / "outputs"
    if outputs_root.exists():
        summary["missing_output_paths"] = _check_required_paths(
            trip_root,
            REQUIRED_COMPLETED_TRIP_OUTPUTS,
            errors,
        )
    else:
        warnings.append("completed trip workspace has no outputs directory yet")
        summary["missing_output_paths"] = []

    runtime_root = trip_root / "runtime"
    if runtime_root.exists():
        imported_manifest = runtime_root / "imported_session_manifest.json"
        if not imported_manifest.is_file():
            errors.append(
                "completed trip runtime import missing imported_session_manifest.json"
            )
        for name in (
            "events",
            "team",
            "recorder",
            "transports",
            "sensor_logs",
            "hardware",
            "communications",
            "navigation",
            "black_box",
        ):
            if not (runtime_root / name).exists():
                errors.append(f"completed trip runtime import missing {name}/")
        summary["runtime_import_checked"] = True
    else:
        summary["runtime_import_checked"] = False
    return summary


def _check_black_box_export_scope(
    args: argparse.Namespace,
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    if not args.black_box_export_root:
        return {"checked": False}
    session_id = args.black_box_session_id or args.runtime_session_id
    export_root = args.black_box_export_root.expanduser() / str(session_id)
    return _check_black_box_export_layout(export_root, errors, warnings)


def _check_black_box_export_layout(
    export_root: Path,
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "checked": True,
        "export_root": export_root.as_posix(),
    }
    if not export_root.is_dir():
        errors.append(f"black-box export root does not exist: {export_root}")
        summary["exists"] = False
        return summary
    summary["exists"] = True
    summary["missing_required_paths"] = _check_required_paths(
        export_root,
        REQUIRED_BLACK_BOX_EXPORT_PATHS,
        errors,
    )
    manifest = _load_json(export_root / "black_box_export_manifest.json", errors)
    redaction = _load_json(export_root / "redaction_policy.json", errors)
    if isinstance(manifest, dict):
        if not manifest.get("source_runtime_session_ref"):
            errors.append("black-box export manifest missing source_runtime_session_ref")
        if manifest.get("pretrip_template_package") is True:
            errors.append("black-box export claims to be a pretrip template package")
    if isinstance(redaction, dict):
        if not redaction.get("audience"):
            errors.append("black-box export redaction policy missing audience")
        if not redaction.get("purpose"):
            errors.append("black-box export redaction policy missing purpose")
    _check_jsonl_records(
        export_root / "timeline_index.jsonl",
        "black-box export timeline index",
        errors,
        warnings,
        required_any_timestamp=True,
        required_fields=("sequence", "source_ref"),
    )
    return summary


def _check_required_paths(
    root: Path,
    required_paths: dict[str, str],
    errors: list[str],
) -> list[str]:
    missing: list[str] = []
    for label, relative in required_paths.items():
        if not (root / relative).exists():
            missing.append(relative)
            errors.append(f"missing {label}: {root / relative}")
    return missing


def _check_jsonl_records(
    path: Path,
    label: str,
    errors: list[str],
    warnings: list[str],
    *,
    required_fields: tuple[str, ...] = (),
    false_fields: tuple[str, ...] = (),
    one_of_fields: tuple[tuple[str, ...], ...] = (),
    required_any_timestamp: bool = False,
    max_records: int = 20,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "path": path.as_posix(),
        "exists": path.is_file(),
        "checked_records": 0,
    }
    if not path.is_file():
        errors.append(f"missing JSONL artifact: {path}")
        return summary
    checked = 0
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except Exception as exc:
                errors.append(f"invalid JSONL record in {label}:{line_number}: {exc}")
                break
            if not isinstance(record, dict):
                errors.append(f"{label}:{line_number} record is not an object")
                break
            checked += 1
            _check_record_shape(
                record,
                f"{label}:{line_number}",
                errors,
                required_fields=required_fields,
                false_fields=false_fields,
                one_of_fields=one_of_fields,
                required_any_timestamp=required_any_timestamp,
            )
            if checked >= max_records:
                break
    if checked == 0:
        warnings.append(f"{label} JSONL is empty: {path}")
    summary["checked_records"] = checked
    return summary


def _check_record_shape(
    record: dict[str, Any],
    label: str,
    errors: list[str],
    *,
    required_fields: tuple[str, ...],
    false_fields: tuple[str, ...],
    one_of_fields: tuple[tuple[str, ...], ...],
    required_any_timestamp: bool,
) -> None:
    for field in required_fields:
        if field not in record:
            errors.append(f"{label} missing required field: {field}")
    if required_any_timestamp and not any(
        field in record
        for field in ("timestamp", "recorded_at", "received_at", "queued_at", "sent_at")
    ):
        errors.append(f"{label} missing timestamp/recorded_at/received_at")
    for field in false_fields:
        if record.get(field) is not False:
            errors.append(f"{label} must set {field}=false")
    for choices in one_of_fields:
        if not any(record.get(field) for field in choices):
            errors.append(f"{label} missing one of: {', '.join(choices)}")


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
    *,
    allow_network_calls: bool = False,
) -> None:
    if not layer_manifest or not layer_summary:
        return
    boundary = layer_manifest.get("boundary", {})
    if boundary.get("runtime_safety_truth") is not False:
        errors.append("layer preparation claims runtime safety truth")
    if boundary.get("phase1_runtime_mutation_allowed") is not False:
        errors.append("layer preparation allows Phase 1 runtime mutation")
    network_calls_made = layer_manifest.get("network_policy", {}).get(
        "network_calls_made"
    )
    if network_calls_made is not False and not allow_network_calls:
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
