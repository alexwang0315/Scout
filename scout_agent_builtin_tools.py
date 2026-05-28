from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
from typing import Any, Sequence

from runtime_debug_log import FileRuntimeDebugEventLog, MemoryRuntimeDebugEventLog
from runtime_debug_models import RuntimeDebugEvent
from scout_agent_trace import load_agent_trace


NOTE_TAXONOMY: dict[str, dict[str, Any]] = {
    "agent_note": {
        "category": "agent_context",
        "retention_profile": "debug_trace_standard",
        "ttl_days": 90,
        "replay_priority": "normal",
    },
    "user_report": {
        "category": "field_user_report",
        "retention_profile": "field_report_extended",
        "ttl_days": 365,
        "replay_priority": "high",
    },
    "operator_decision": {
        "category": "operator_decision",
        "retention_profile": "audit_extended",
        "ttl_days": 730,
        "replay_priority": "high",
    },
    "safety_advisory": {
        "category": "advisory_decision_support",
        "retention_profile": "safety_advisory_audit",
        "ttl_days": 365,
        "replay_priority": "high",
    },
    "environment_observation": {
        "category": "local_environment_observation",
        "retention_profile": "evidence_standard",
        "ttl_days": 180,
        "replay_priority": "normal",
    },
    "hardware_observation": {
        "category": "hardware_readiness_observation",
        "retention_profile": "debug_trace_standard",
        "ttl_days": 90,
        "replay_priority": "normal",
    },
    "system_diagnostic": {
        "category": "system_diagnostic",
        "retention_profile": "debug_trace_short",
        "ttl_days": 30,
        "replay_priority": "low",
    },
}


def run_builtin_tool(argv: Sequence[str] | None = None) -> tuple[int, dict[str, Any]]:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "debug-trace-tail":
        return _debug_trace_tail(args)
    if args.command == "local-evidence-status":
        return _local_evidence_status(args)
    if args.command == "evidence-sensorlog-to-gpx":
        return _evidence_sensorlog_to_gpx(args)
    if args.command == "checks-pretrip-release":
        return _checks_pretrip_release(args)
    if args.command == "checks-runtime-readiness":
        return _checks_runtime_readiness(args)
    if args.command == "map-raster-source":
        return _map_raster_source(args)
    if args.command == "map-raster-tiles":
        return _map_raster_tiles(args)
    if args.command == "map-tile-cache-plan":
        return _map_tile_cache_plan(args)
    if args.command == "kb-pretrip-view-summary":
        return _kb_pretrip_view_summary(args)
    if args.command == "kb-hardware-readiness-summary":
        return _kb_hardware_readiness_summary(args)
    if args.command == "kb-build":
        return _kb_build(args)
    if args.command == "kb-query":
        return _kb_query(args)
    if args.command == "note-append-flight-recorder":
        return _note_append_flight_recorder(args)
    if args.command == "cp-propose-add":
        return _cp_proposal_preview(args, forced_operation="propose_add")
    if args.command == "cp-propose-delete":
        return _cp_proposal_preview(args, forced_operation="propose_delete")
    if args.command == "cp-proposal-preview":
        return _cp_proposal_preview(args)
    if args.command == "cp-apply-reviewed-delta":
        return _cp_apply_reviewed_delta(args)
    if args.command == "spatial-imprint-trigger-dry-run":
        return _spatial_imprint_trigger_dry_run(args)
    if args.command == "spatial-imprint-export-pretrip":
        return _spatial_imprint_export_pretrip(args)
    if args.command == "spatial-imprint-store-list":
        return _spatial_imprint_store_list(args)
    if args.command == "spatial-imprint-plant":
        return _spatial_imprint_plant(args)
    if args.command == "spatial-imprint-expire":
        return _spatial_imprint_expire(args)
    if args.command == "spatial-imprint-delete":
        return _spatial_imprint_delete(args)
    if args.command == "voice-preview":
        return _voice_preview(args)
    if args.command == "voice-mock-queue":
        return _voice_mock_queue(args)
    if args.command == "voice-mock-transition":
        return _voice_mock_transition(args)
    if args.command == "outbound-mock-queue":
        return _outbound_mock_queue(args)
    if args.command == "outbound-mock-transition":
        return _outbound_mock_transition(args)
    if args.command == "risk-attribution":
        return _risk_attribution(args)
    if args.command == "risk-heatmap":
        return _risk_heatmap(args)
    if args.command == "safety-action-shelter-direction":
        return _safety_action_shelter_direction(args)
    if args.command == "sos-playbook-run":
        return _sos_playbook_run(args)
    if args.command == "pretrip-workspace-edit":
        return _pretrip_workspace_edit(args)
    if args.command == "pretrip-import-gpx":
        return _pretrip_import_gpx(args)
    if args.command == "pretrip-prepare-layers":
        return _pretrip_prepare_layers(args)
    if args.command == "pretrip-artifact-manifest":
        return _pretrip_artifact_manifest(args)
    if args.command == "pretrip-readiness":
        return _pretrip_readiness(args)
    if args.command == "pretrip-decision-register":
        return _pretrip_decision_register(args)
    if args.command == "pretrip-review-append-decisions":
        return _pretrip_review_append_decisions(args)
    if args.command == "pretrip-departure-reviewed-candidates":
        return _pretrip_departure_reviewed_candidates(args)
    if args.command == "pretrip-runtime-handoff":
        return _pretrip_runtime_handoff(args)
    if args.command == "pretrip-runtime-export":
        return _pretrip_runtime_export(args)
    if args.command == "runtime-activation-preflight":
        return _runtime_activation_preflight(args)
    if args.command == "runtime-load-dry-run":
        return _runtime_load_dry_run(args)
    return 2, _error_payload("unsupported builtin tool")


def main(argv: Sequence[str] | None = None) -> int:
    exit_code, payload = run_builtin_tool(argv)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return exit_code


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scout Agent builtin placeholder tools.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    trace_parser = subparsers.add_parser("debug-trace-tail")
    trace_parser.add_argument("--input", type=Path, required=True)
    trace_parser.add_argument("--json", action="store_true")

    evidence_parser = subparsers.add_parser("local-evidence-status")
    evidence_parser.add_argument("--input", type=Path, required=True)
    evidence_parser.add_argument("--json", action="store_true")

    sensorlog_parser = subparsers.add_parser("evidence-sensorlog-to-gpx")
    sensorlog_parser.add_argument("--input", type=Path, required=True)
    sensorlog_parser.add_argument("--output", type=Path, default=None)
    sensorlog_parser.add_argument("--dry-run", action="store_true")
    sensorlog_parser.add_argument("--json", action="store_true")

    pretrip_check_parser = subparsers.add_parser("checks-pretrip-release")
    pretrip_check_parser.add_argument("--input", type=Path, required=True)
    pretrip_check_parser.add_argument("--json", action="store_true")

    runtime_check_parser = subparsers.add_parser("checks-runtime-readiness")
    runtime_check_parser.add_argument("--input", type=Path, required=True)
    runtime_check_parser.add_argument("--json", action="store_true")

    raster_source_parser = subparsers.add_parser("map-raster-source")
    raster_source_parser.add_argument("--input", type=Path, required=True)
    raster_source_parser.add_argument("--json", action="store_true")

    raster_tiles_parser = subparsers.add_parser("map-raster-tiles")
    raster_tiles_parser.add_argument("--input", type=Path, required=True)
    raster_tiles_parser.add_argument("--dry-run", action="store_true")
    raster_tiles_parser.add_argument("--json", action="store_true")

    tile_cache_parser = subparsers.add_parser("map-tile-cache-plan")
    tile_cache_parser.add_argument("--input", type=Path, required=True)
    tile_cache_parser.add_argument("--json", action="store_true")

    pretrip_summary_parser = subparsers.add_parser("kb-pretrip-view-summary")
    pretrip_summary_parser.add_argument("--input", type=Path, required=True)
    pretrip_summary_parser.add_argument("--json", action="store_true")

    hardware_summary_parser = subparsers.add_parser("kb-hardware-readiness-summary")
    hardware_summary_parser.add_argument("--input", type=Path, required=True)
    hardware_summary_parser.add_argument("--json", action="store_true")

    kb_query_parser = subparsers.add_parser("kb-query")
    kb_query_parser.add_argument("--input", type=Path, required=True)
    kb_query_parser.add_argument("--json", action="store_true")

    kb_build_parser = subparsers.add_parser("kb-build")
    kb_build_parser.add_argument("--input", type=Path, required=True)
    kb_build_parser.add_argument("--output", type=Path, default=None)
    kb_build_parser.add_argument("--dry-run", action="store_true")
    kb_build_parser.add_argument("--json", action="store_true")

    note_parser = subparsers.add_parser("note-append-flight-recorder")
    note_parser.add_argument("--input", type=Path, required=True)
    note_parser.add_argument("--json", action="store_true")

    cp_add_parser = subparsers.add_parser("cp-propose-add")
    cp_add_parser.add_argument("--input", type=Path, required=True)
    cp_add_parser.add_argument("--output", type=Path, default=None)
    cp_add_parser.add_argument("--dry-run", action="store_true")
    cp_add_parser.add_argument("--json", action="store_true")

    cp_delete_parser = subparsers.add_parser("cp-propose-delete")
    cp_delete_parser.add_argument("--input", type=Path, required=True)
    cp_delete_parser.add_argument("--output", type=Path, default=None)
    cp_delete_parser.add_argument("--dry-run", action="store_true")
    cp_delete_parser.add_argument("--json", action="store_true")

    proposal_parser = subparsers.add_parser("cp-proposal-preview")
    proposal_parser.add_argument("--input", type=Path, required=True)
    proposal_parser.add_argument("--output", type=Path, default=None)
    proposal_parser.add_argument("--dry-run", action="store_true")
    proposal_parser.add_argument("--json", action="store_true")

    cp_reviewed_delta_parser = subparsers.add_parser("cp-apply-reviewed-delta")
    cp_reviewed_delta_parser.add_argument("--input", type=Path, required=True)
    cp_reviewed_delta_parser.add_argument("--dry-run", action="store_true")
    cp_reviewed_delta_parser.add_argument("--json", action="store_true")

    imprint_parser = subparsers.add_parser("spatial-imprint-trigger-dry-run")
    imprint_parser.add_argument("--input", type=Path, required=True)
    imprint_parser.add_argument("--json", action="store_true")

    imprint_export_parser = subparsers.add_parser("spatial-imprint-export-pretrip")
    imprint_export_parser.add_argument("--input", type=Path, required=True)
    imprint_export_parser.add_argument("--dry-run", action="store_true")
    imprint_export_parser.add_argument("--json", action="store_true")

    imprint_store_list_parser = subparsers.add_parser("spatial-imprint-store-list")
    imprint_store_list_parser.add_argument("--input", type=Path, required=True)
    imprint_store_list_parser.add_argument("--json", action="store_true")

    imprint_plant_parser = subparsers.add_parser("spatial-imprint-plant")
    imprint_plant_parser.add_argument("--input", type=Path, required=True)
    imprint_plant_parser.add_argument("--dry-run", action="store_true")
    imprint_plant_parser.add_argument("--json", action="store_true")

    imprint_expire_parser = subparsers.add_parser("spatial-imprint-expire")
    imprint_expire_parser.add_argument("--input", type=Path, required=True)
    imprint_expire_parser.add_argument("--dry-run", action="store_true")
    imprint_expire_parser.add_argument("--json", action="store_true")

    imprint_delete_parser = subparsers.add_parser("spatial-imprint-delete")
    imprint_delete_parser.add_argument("--input", type=Path, required=True)
    imprint_delete_parser.add_argument("--dry-run", action="store_true")
    imprint_delete_parser.add_argument("--json", action="store_true")

    voice_parser = subparsers.add_parser("voice-preview")
    voice_parser.add_argument("--input", type=Path, required=True)
    voice_parser.add_argument("--output", type=Path, default=None)
    voice_parser.add_argument("--json", action="store_true")

    voice_queue_parser = subparsers.add_parser("voice-mock-queue")
    voice_queue_parser.add_argument("--input", type=Path, required=True)
    voice_queue_parser.add_argument("--dry-run", action="store_true")
    voice_queue_parser.add_argument("--json", action="store_true")

    voice_transition_parser = subparsers.add_parser("voice-mock-transition")
    voice_transition_parser.add_argument("--input", type=Path, required=True)
    voice_transition_parser.add_argument("--dry-run", action="store_true")
    voice_transition_parser.add_argument("--json", action="store_true")

    outbound_queue_parser = subparsers.add_parser("outbound-mock-queue")
    outbound_queue_parser.add_argument("--input", type=Path, required=True)
    outbound_queue_parser.add_argument("--dry-run", action="store_true")
    outbound_queue_parser.add_argument("--json", action="store_true")

    outbound_transition_parser = subparsers.add_parser("outbound-mock-transition")
    outbound_transition_parser.add_argument("--input", type=Path, required=True)
    outbound_transition_parser.add_argument("--dry-run", action="store_true")
    outbound_transition_parser.add_argument("--json", action="store_true")

    risk_attribution_parser = subparsers.add_parser("risk-attribution")
    risk_attribution_parser.add_argument("--input", type=Path, required=True)
    risk_attribution_parser.add_argument("--output", type=Path, default=None)
    risk_attribution_parser.add_argument("--dry-run", action="store_true")
    risk_attribution_parser.add_argument("--json", action="store_true")

    risk_heatmap_parser = subparsers.add_parser("risk-heatmap")
    risk_heatmap_parser.add_argument("--input", type=Path, required=True)
    risk_heatmap_parser.add_argument("--output", type=Path, default=None)
    risk_heatmap_parser.add_argument("--dry-run", action="store_true")
    risk_heatmap_parser.add_argument("--json", action="store_true")

    shelter_parser = subparsers.add_parser("safety-action-shelter-direction")
    shelter_parser.add_argument("--input", type=Path, required=True)
    shelter_parser.add_argument("--json", action="store_true")

    sos_parser = subparsers.add_parser("sos-playbook-run")
    sos_parser.add_argument("--input", type=Path, required=True)
    sos_parser.add_argument("--dry-run", action="store_true")
    sos_parser.add_argument("--json", action="store_true")

    workspace_edit_parser = subparsers.add_parser("pretrip-workspace-edit")
    workspace_edit_parser.add_argument("--input", type=Path, required=True)
    workspace_edit_parser.add_argument("--dry-run", action="store_true")
    workspace_edit_parser.add_argument("--json", action="store_true")

    pretrip_import_parser = subparsers.add_parser("pretrip-import-gpx")
    pretrip_import_parser.add_argument("--input", type=Path, required=True)
    pretrip_import_parser.add_argument("--dry-run", action="store_true")
    pretrip_import_parser.add_argument("--json", action="store_true")

    prepare_layers_parser = subparsers.add_parser("pretrip-prepare-layers")
    prepare_layers_parser.add_argument("--input", type=Path, required=True)
    prepare_layers_parser.add_argument("--dry-run", action="store_true")
    prepare_layers_parser.add_argument("--json", action="store_true")

    artifact_manifest_parser = subparsers.add_parser("pretrip-artifact-manifest")
    artifact_manifest_parser.add_argument("--input", type=Path, required=True)
    artifact_manifest_parser.add_argument("--json", action="store_true")

    readiness_parser = subparsers.add_parser("pretrip-readiness")
    readiness_parser.add_argument("--input", type=Path, required=True)
    readiness_parser.add_argument("--json", action="store_true")

    decision_register_parser = subparsers.add_parser("pretrip-decision-register")
    decision_register_parser.add_argument("--input", type=Path, required=True)
    decision_register_parser.add_argument("--json", action="store_true")

    review_append_parser = subparsers.add_parser("pretrip-review-append-decisions")
    review_append_parser.add_argument("--input", type=Path, required=True)
    review_append_parser.add_argument("--dry-run", action="store_true")
    review_append_parser.add_argument("--json", action="store_true")

    departure_reviewed_parser = subparsers.add_parser("pretrip-departure-reviewed-candidates")
    departure_reviewed_parser.add_argument("--input", type=Path, required=True)
    departure_reviewed_parser.add_argument("--dry-run", action="store_true")
    departure_reviewed_parser.add_argument("--json", action="store_true")

    runtime_export_parser = subparsers.add_parser("pretrip-runtime-export")
    runtime_export_parser.add_argument("--input", type=Path, required=True)
    runtime_export_parser.add_argument("--dry-run", action="store_true")
    runtime_export_parser.add_argument("--json", action="store_true")

    runtime_handoff_parser = subparsers.add_parser("pretrip-runtime-handoff")
    runtime_handoff_parser.add_argument("--input", type=Path, required=True)
    runtime_handoff_parser.add_argument("--dry-run", action="store_true")
    runtime_handoff_parser.add_argument("--json", action="store_true")

    activation_preflight_parser = subparsers.add_parser("runtime-activation-preflight")
    activation_preflight_parser.add_argument("--input", type=Path, required=True)
    activation_preflight_parser.add_argument("--json", action="store_true")

    load_dry_run_parser = subparsers.add_parser("runtime-load-dry-run")
    load_dry_run_parser.add_argument("--input", type=Path, required=True)
    load_dry_run_parser.add_argument("--json", action="store_true")
    return parser


def _debug_trace_tail(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    request = _load_json(args.input)
    trace_path = request.get("trace_path")
    if not trace_path:
        return 2, _error_payload("debug trace-tail requires trace_path")
    trace_kind = request.get("trace_kind", "runtime_debug")
    limit = max(0, int(request.get("limit", 20)))
    path = Path(trace_path)
    if trace_kind == "agent_tool":
        records = [item.model_dump(mode="json") for item in load_agent_trace(path)[-limit:]]
    else:
        records = [
            item.model_dump(mode="json")
            for item in FileRuntimeDebugEventLog(path).list_events(limit=limit)
        ]
    return (
        0,
        {
            "artifact_kind": "scout_debug_trace_tail",
            "status": "completed",
            "trace_kind": trace_kind,
            "trace_path": str(path),
            "limit": limit,
            "record_count": len(records),
            "records": records,
            "boundary": _closed_boundary(),
        },
    )


def _local_evidence_status(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    request = _load_json(args.input)
    payload = {
        "artifact_kind": "scout_agent_builtin_tool_output",
        "capability": "local_evidence_status",
        "status": "completed",
        "offline_only": True,
        "request_keys": sorted(request.keys()),
        "available_indexes": [
            "pretrip_admin_view",
            "hardware_readiness_summary",
            "runtime_debug_trace",
        ],
        "boundary": _closed_boundary(),
    }
    return 0, payload


def _evidence_sensorlog_to_gpx(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    from sensorlog_to_gpx import _records_from_payload, _valid_location, sensorlog_json_to_gpx

    request = _load_json(args.input)
    input_path = request.get("input_path") or request.get("sensorlog_path")
    if not input_path:
        return 2, _error_payload("sensorlog-to-gpx requires input_path")
    output_path = args.output or _optional_path(request.get("output_path"))
    if output_path is None:
        output_path = Path(str(input_path)).with_suffix(".gpx")
    max_horizontal_accuracy = request.get("max_horizontal_accuracy")
    max_accuracy = (
        float(max_horizontal_accuracy)
        if max_horizontal_accuracy not in (None, "", "null")
        else None
    )
    track_name = request.get("track_name")

    try:
        if args.dry_run:
            payload = json.loads(Path(str(input_path)).read_text(encoding="utf-8"))
            records = _records_from_payload(payload)
            point_count = sum(
                1 for record in records if _valid_location(record, max_accuracy) is not None
            )
            if point_count == 0:
                raise ValueError("No valid GPS points found")
        else:
            point_count = sensorlog_json_to_gpx(
                Path(str(input_path)),
                Path(output_path),
                track_name=track_name,
                max_horizontal_accuracy=max_accuracy,
            )
    except Exception as exc:  # noqa: BLE001 - CLI wrapper returns structured failures.
        return 2, _error_payload(str(exc))

    return (
        0,
        {
            "artifact_kind": "scout_evidence_sensorlog_to_gpx",
            "status": "completed",
            "dry_run": args.dry_run,
            "input_path": str(input_path),
            "output_path": str(output_path),
            "track_point_count": point_count,
            "boundary": {
                **_closed_boundary(),
                "workspace_file_mutation_allowed": not args.dry_run,
                "runtime_safety_truth": False,
                "phase1_safety_mutation_allowed": False,
                "live_safety_api_calls_allowed": False,
            },
        },
    )


def _checks_pretrip_release(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    from phase4_pretrip_release_check import build_release_check

    request = _load_json(args.input)
    repo_root = Path(str(request.get("repo_root", Path(__file__).resolve().parent)))
    project_json_path = request.get("project_json_path") or request.get("project_json")
    report = build_release_check(
        repo_root,
        project_json_path=project_json_path,
    )
    return (
        0,
        {
            "artifact_kind": "scout_check_pretrip_release",
            "status": "completed",
            "report": report,
            "boundary": {
                **_closed_boundary(),
                "read_only": True,
                "runtime_activation_allowed": False,
                "workspace_file_mutation_allowed": False,
            },
        },
    )


def _checks_runtime_readiness(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    from phase35_runtime_readiness_check import build_release_check

    request = _load_json(args.input)
    repo_root = Path(str(request.get("repo_root", Path(__file__).resolve().parent)))
    report = build_release_check(repo_root)
    return (
        0,
        {
            "artifact_kind": "scout_check_runtime_readiness",
            "status": "completed",
            "report": report,
            "boundary": {
                **_closed_boundary(),
                "read_only": True,
                "runtime_activation_allowed": False,
                "workspace_file_mutation_allowed": False,
            },
        },
    )


def _map_raster_source(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    from admin_local_raster_source import build_local_raster_source_manifest

    request = _load_json(args.input)
    source_geotiff = request.get("source_geotiff")
    if not source_geotiff:
        return 2, _error_payload("map raster-source requires source_geotiff")
    kwargs: dict[str, Any] = {}
    for key in ("project_id", "layer_id", "recommended_cache_root"):
        if request.get(key) is not None:
            kwargs[key] = request[key]
    try:
        manifest = build_local_raster_source_manifest(source_geotiff, **kwargs)
    except Exception as exc:  # noqa: BLE001 - map wrapper reports structured failures.
        return 2, _error_payload(str(exc))
    return (
        0,
        {
            "artifact_kind": "scout_map_raster_source_tool_output",
            "status": "completed",
            "manifest": manifest,
            "boundary": {
                **_closed_boundary(),
                "read_only": True,
                "external_network_required": False,
                "workspace_file_mutation_allowed": False,
                "raw_raster_committed_to_repo_allowed": False,
                "tile_cutting_performed": False,
            },
        },
    )


def _map_raster_tiles(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    from admin_local_raster_tiles import (
        build_raster_tile_pyramid_plan,
        cut_raster_tile_pyramid,
    )

    request = _load_json(args.input)
    try:
        source_manifest = _source_manifest_from_request(request)
        plan_kwargs = _raster_tile_plan_kwargs(request)
        plan = build_raster_tile_pyramid_plan(source_manifest, **plan_kwargs)
        cut_summary = cut_raster_tile_pyramid(
            source_manifest,
            plan,
            dry_run=args.dry_run,
            max_tiles=_optional_int(request.get("max_tiles")),
        )
    except Exception as exc:  # noqa: BLE001 - map wrapper reports structured failures.
        return 2, _error_payload(str(exc))
    return (
        0,
        {
            "artifact_kind": "scout_map_raster_tiles_tool_output",
            "status": "completed",
            "dry_run": args.dry_run,
            "plan": plan,
            "cut_summary": cut_summary,
            "boundary": {
                **_closed_boundary(),
                "workspace_file_mutation_allowed": not args.dry_run,
                "local_tile_cache_write_allowed": not args.dry_run,
                "external_network_required": False,
                "repo_fixture_write_allowed": False,
                "raw_raster_committed_to_repo_allowed": False,
            },
        },
    )


def _map_tile_cache_plan(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    from admin_tile_cache_builder import (
        build_tile_cache_hardware_manifest,
        build_tile_cache_plan,
        load_pretrip_project_route_bbox,
    )

    request = _load_json(args.input)
    try:
        if request.get("bbox_wgs84"):
            bbox = request["bbox_wgs84"]
        elif request.get("project_root"):
            bbox = load_pretrip_project_route_bbox(request["project_root"])
        else:
            return 2, _error_payload("map tile-cache-plan requires project_root or bbox_wgs84")
        kwargs = _tile_cache_plan_kwargs(request)
        plan = build_tile_cache_plan(bbox, **kwargs)
        hardware_manifest = build_tile_cache_hardware_manifest(plan)
    except Exception as exc:  # noqa: BLE001 - map wrapper reports structured failures.
        return 2, _error_payload(str(exc))
    return (
        0,
        {
            "artifact_kind": "scout_map_tile_cache_plan_tool_output",
            "status": "completed",
            "plan": plan,
            "hardware_manifest": hardware_manifest,
            "boundary": {
                **_closed_boundary(),
                "read_only": True,
                "workspace_file_mutation_allowed": False,
                "external_network_fetch_allowed": False,
                "bulk_download_started": False,
                "repo_fixture_write_allowed": False,
            },
        },
    )


def _kb_pretrip_view_summary(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    request = _load_json(args.input)
    if request.get("view_path"):
        view_path = Path(request["view_path"])
        view = _load_json(view_path)
        summary = _summary_from_pretrip_view(view, source_path=view_path)
    elif request.get("project_root"):
        project_root = Path(request["project_root"])
        summary = _summary_from_pretrip_project_root(project_root)
    else:
        return 2, _error_payload("pretrip view summary requires view_path or project_root")
    summary["boundary"] = _closed_boundary()
    return 0, summary


def _kb_hardware_readiness_summary(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    from hardware_readiness_admin_view import build_hardware_readiness_admin_view

    request = _load_json(args.input)
    kwargs: dict[str, Any] = {}
    if request.get("fixture_path"):
        kwargs["fixture_path"] = request["fixture_path"]
    if request.get("selected_provider_ref"):
        kwargs["selected_provider_ref"] = request["selected_provider_ref"]
    view = build_hardware_readiness_admin_view(**kwargs)
    return (
        0,
        {
            "artifact_kind": "scout_kb_hardware_readiness_summary",
            "status": "completed",
            "surface": view["surface"],
            "read_only": view["read_only"],
            "summary": view["summary"],
            "selected_provider": view["selected_provider"],
            "interface_inventory": view["interface_inventory"],
            "provider_health": view["provider_health"],
            "runtime_debug_events": view["runtime_debug_events"],
            "mock_transport_queue": view["mock_transport_queue"],
            "sources": view["sources"],
            "limitations": view["limitations"],
            "boundary": {
                **_closed_boundary(),
                **view["boundary"],
                "hardware_control_allowed": False,
                "provider_control_allowed": False,
            },
        },
    )


def _kb_query(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    from scout_agent_kb import (
        build_local_evidence_index,
        load_local_evidence_index,
        query_local_evidence_index,
    )

    request = _load_json(args.input)
    query = request.get("query")
    if not isinstance(query, str) or not query.strip():
        return 2, _error_payload("kb query requires non-empty query")
    if request.get("index_path"):
        index = load_local_evidence_index(request["index_path"])
    elif request.get("project_root"):
        index = build_local_evidence_index(request["project_root"])
    else:
        return 2, _error_payload("kb query requires project_root or index_path")
    evidence_types = request.get("evidence_types")
    result = query_local_evidence_index(
        index,
        query=query,
        limit=int(request.get("limit", 8)),
        evidence_types=set(evidence_types) if evidence_types else None,
    )
    return (
        0,
        {
            "artifact_kind": "scout_kb_query_tool_output",
            "status": "completed",
            "index": {
                "artifact_kind": index.artifact_kind,
                "project_id": index.project_id,
                "record_count": index.record_count,
                "source_root": index.source_root,
            },
            "query_result": result.model_dump(mode="json"),
            "boundary": {
                **_closed_boundary(),
                "offline_only": True,
                "local_evidence_only": True,
                "raw_payloads_embedded": False,
            },
        },
    )


def _kb_build(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    from scout_agent_kb import build_local_evidence_index, write_local_evidence_index

    request = _load_json(args.input)
    project_root = request.get("project_root") or request.get("trip_root")
    if not project_root:
        return 2, _error_payload("kb build requires project_root or trip_root")
    output_path = args.output or _optional_path(request.get("output_path"))
    if output_path is None and not args.dry_run:
        return 2, _error_payload("kb build requires output_path or --output unless dry-run")
    try:
        if args.dry_run:
            index = build_local_evidence_index(project_root)
        else:
            index = write_local_evidence_index(project_root, output_path)
    except Exception as exc:  # noqa: BLE001 - CLI wrapper returns structured failures.
        return 2, _error_payload(str(exc))

    return (
        0,
        {
            "artifact_kind": "scout_kb_build_tool_output",
            "status": "completed",
            "dry_run": args.dry_run,
            "index": {
                "artifact_kind": index.artifact_kind,
                "schema_version": index.schema_version,
                "project_id": index.project_id,
                "record_count": index.record_count,
                "source_root": index.source_root,
                "evidence_types": sorted({record.evidence_type for record in index.records}),
            },
            "artifact_refs": [] if args.dry_run or output_path is None else [str(output_path)],
            "boundary": {
                **_closed_boundary(),
                "offline_only": True,
                "local_evidence_only": True,
                "workspace_file_mutation_allowed": not args.dry_run,
                "raw_payloads_embedded": False,
                "runtime_activation_allowed": False,
            },
        },
    )


def _note_append_flight_recorder(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    request = _load_json(args.input)
    debug_log_path = request.get("debug_log_path")
    text = request.get("text")
    if not debug_log_path or not text:
        return 2, _error_payload("flight recorder note requires debug_log_path and text")
    note_kind = str(request.get("note_kind", "agent_note"))
    taxonomy = NOTE_TAXONOMY.get(note_kind)
    if taxonomy is None:
        return 2, _error_payload(
            f"unsupported note_kind: {note_kind}; expected one of {sorted(NOTE_TAXONOMY)}"
        )
    retention_policy = {
        "profile": request.get("retention_profile") or taxonomy["retention_profile"],
        "ttl_days": int(request.get("retention_ttl_days", taxonomy["ttl_days"])),
        "delete_after_export": bool(request.get("delete_after_export", False)),
        "policy_scope": "flight_recorder_debug_trace",
    }
    event = RuntimeDebugEvent(
        event_id=request.get("event_id", "debug_event.agent_note.000001"),
        session_id=request.get("session_id", "agent_note_session.local"),
        mission_id=request.get("mission_id"),
        timestamp=request.get("timestamp", _utc_now()),
        sequence=max(0, int(request.get("sequence", 1))),
        kind="agent_note_appended",
        source=request.get("source", "scout_agent_builtin_tools"),
        phase="phase35",
        severity=request.get("severity", "info"),
        subject_ref=request.get("subject_ref"),
        correlation_refs=list(request.get("correlation_refs", []) or []),
        summary=str(text)[:280],
        payload={
            "note_kind": note_kind,
            "note_category": taxonomy["category"],
            "text": text,
            "retention_policy": retention_policy,
            "replay_priority": taxonomy["replay_priority"],
            "source_refs": list(request.get("source_refs", []) or []),
            "boundary": _closed_boundary(),
        },
    )
    FileRuntimeDebugEventLog(debug_log_path).append(event)
    return (
        0,
        {
            "artifact_kind": "scout_flight_recorder_note_append",
            "status": "completed",
            "event": event.model_dump(mode="json"),
            "debug_log_path": str(debug_log_path),
            "note_taxonomy": {
                "supported_note_kinds": sorted(NOTE_TAXONOMY),
                "selected_note_kind": note_kind,
                "selected_category": taxonomy["category"],
            },
            "retention_policy": retention_policy,
            "boundary": {
                **_closed_boundary(),
                "phase1_runtime_mutation_allowed": False,
                "phase2_observed_fact_write_allowed": False,
            },
        },
    )


def _cp_proposal_preview(
    args: argparse.Namespace,
    *,
    forced_operation: str | None = None,
) -> tuple[int, dict[str, Any]]:
    request = _load_json(args.input)
    candidate_ref = request.get("candidate_ref") or request.get("cp_ref") or "candidate.unspecified"
    label = request.get("label") or request.get("title") or candidate_ref
    operation = forced_operation or request.get("operation", "propose_add")
    payload = {
        "artifact_kind": "scout_cp_proposal_preview",
        "status": "completed",
        "dry_run": args.dry_run,
        "candidate_ref": candidate_ref,
        "label": label,
        "operation": operation,
        "proposal_boundary": {
            "candidate_only": True,
            "requires_review_before_package": True,
            "runtime_safety_truth": False,
            "phase1_safety_mutation_allowed": False,
            "live_safety_api_calls_allowed": False,
        },
        "boundary": _closed_boundary(),
    }
    if args.output is not None and not args.dry_run:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0, payload


def _cp_apply_reviewed_delta(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    from pretrip_cp_reviewed_delta import (
        DEFAULT_CP_REVIEWED_DELTA_REF,
        build_cp_reviewed_delta_for_workspace,
        write_cp_reviewed_delta_for_workspace,
    )

    request = _load_json(args.input)
    project_root = request.get("project_root")
    if not project_root:
        return 2, _error_payload("CP reviewed delta requires project_root")
    apply_plan_path = (
        request.get("apply_plan_path")
        or request.get("delta_path")
        or request.get("delta")
    )
    output_ref = request.get("output_ref") or DEFAULT_CP_REVIEWED_DELTA_REF
    try:
        if args.dry_run:
            delta = build_cp_reviewed_delta_for_workspace(
                project_root,
                apply_plan_path=apply_plan_path,
            )
            destination = Path(str(project_root)) / str(output_ref)
        else:
            delta, destination = write_cp_reviewed_delta_for_workspace(
                project_root,
                apply_plan_path=apply_plan_path,
                output_ref=str(output_ref),
            )
    except Exception as exc:  # noqa: BLE001 - validation failures stay JSON-shaped.
        return 2, _error_payload(str(exc))
    return (
        0,
        {
            "artifact_kind": "scout_cp_apply_reviewed_delta_tool_output",
            "status": "completed",
            "dry_run": args.dry_run,
            "delta": delta.model_dump(mode="json"),
            "artifact_refs": [] if args.dry_run else [str(destination)],
            "boundary": {
                **_closed_boundary(),
                "workspace_file_mutation_allowed": not args.dry_run,
                "delta_artifact_only": True,
                "reversible": True,
                "candidate_only": True,
                "package_mutation_allowed": False,
                "runtime_mutation_allowed": False,
                "phase1_runtime_mutation_allowed": False,
                "phase2_writeback_allowed": False,
                "live_safety_api_calls_allowed": False,
            },
        },
    )


def _voice_preview(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    from voice_tts_provider import configured_provider_for_engine

    request = _load_json(args.input)
    text_zh = request.get("text_zh")
    if not text_zh:
        return 2, _error_payload("voice preview requires text_zh")
    audio_file = request.get("audio_file", "/tmp/scout-voice-preview.wav")
    provider = configured_provider_for_engine(
        request.get("engine", "piper"),
        piper_binary=request.get("piper_binary", "piper"),
        piper_model_path=request.get(
            "piper_model_path",
            "/data/scout/providers/voice_cue/piper/default.onnx",
        ),
        espeak_binary=request.get("espeak_binary", "espeak-ng"),
        espeak_voice=request.get("espeak_voice", "zh"),
        playback_binary=request.get("playback_binary", "aplay"),
    )
    plan = provider.command_plan(text_zh=text_zh, audio_file=audio_file)
    payload = {
        "artifact_kind": "scout_voice_preview",
        "status": "completed",
        "executes_audio": False,
        "sends_remote_outbound": False,
        "plan": plan.model_dump(mode="json"),
        "boundary": _closed_boundary(),
    }
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0, payload


def _voice_mock_queue(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    from mock_voice_transport import MockVoiceTransport
    from voice_cue_models import VoiceCue, VoiceCueRepeatPolicy

    request = _load_json(args.input)
    voice_log_path = request.get("voice_log_path")
    cue_payload = request.get("cue")
    if request.get("cue_path"):
        cue_payload = _load_json(Path(request["cue_path"]))
    if cue_payload is None:
        cue_payload = {
            "cue_id": request.get("cue_id"),
            "priority": request.get("priority", "info"),
            "category": request.get("category", "team"),
            "text_zh": request.get("text_zh"),
            "source_event_refs": list(request.get("source_event_refs", []) or []),
            "source_kind": request.get("source_kind", "operator_note"),
            "confidence": float(request.get("confidence", 1.0)),
            "repeat_policy": {
                "dedupe_key": request.get("dedupe_key"),
                "min_interval_seconds": int(request.get("min_interval_seconds", 300)),
                "max_repeats": request.get("max_repeats", 1),
            },
            "require_ack": bool(request.get("require_ack", False)),
        }
        if cue_payload["repeat_policy"]["dedupe_key"] is None:
            cue_payload["repeat_policy"].pop("dedupe_key")
    if not isinstance(cue_payload, dict):
        return 2, _error_payload("voice mock queue requires cue or cue fields")
    cue_payload["repeat_policy"] = VoiceCueRepeatPolicy.model_validate(
        cue_payload.get("repeat_policy", {})
    ).model_dump(mode="json")
    cue = VoiceCue.model_validate(cue_payload)
    if not voice_log_path:
        return 2, _error_payload("voice mock queue requires voice_log_path")
    if args.dry_run:
        return (
            0,
            {
                "artifact_kind": "scout_voice_mock_queue_dry_run",
                "status": "completed",
                "dry_run": True,
                "cue": cue.model_dump(mode="json"),
                "boundary": {
                    **_closed_boundary(),
                    "voice_log_write_allowed": False,
                    "audio_playback_allowed": False,
                },
            },
        )
    debug_log = _debug_log_or_memory(request.get("debug_log_path"))
    transport = MockVoiceTransport(
        output_jsonl=voice_log_path,
        debug_log=debug_log,
        session_id=request.get("session_id", "voice_cue_session.agent_tool"),
        mission_id=request.get("mission_id"),
        timestamp_factory=_timestamp_factory(request),
    )
    record = transport.queue_voice_cue(
        cue,
        engine=request.get("engine", "mock"),
        audio_file=request.get("audio_file"),
    )
    if request.get("render_mock", False):
        record = transport.mark_rendered(
            record.cue_id,
            engine=request.get("engine", "mock"),
            audio_file=request.get("audio_file"),
        )
    return (
        0,
        {
            "artifact_kind": "scout_voice_mock_queue_tool_output",
            "status": "completed",
            "dry_run": False,
            "record": record.model_dump(mode="json"),
            "voice_log_path": str(voice_log_path),
            "debug_log_path": request.get("debug_log_path"),
            "boundary": {
                **_closed_boundary(),
                "voice_log_write_allowed": True,
                "audio_playback_allowed": False,
            },
        },
    )


def _voice_mock_transition(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    from mock_voice_transport import MockVoiceTransportRecord

    request = _load_json(args.input)
    voice_log_path = request.get("voice_log_path")
    cue_id = request.get("cue_id")
    state = request.get("state")
    if not voice_log_path or not cue_id or state not in {"rendered", "played", "failed"}:
        return 2, _error_payload("voice mock transition requires voice_log_path, cue_id, and state")
    current = MockVoiceTransportRecord.model_validate(
        _latest_jsonl_record(Path(str(voice_log_path)), "cue_id", str(cue_id))
    )
    timestamp = request.get("transitioned_at", _utc_now())
    update: dict[str, Any] = {"state": state, "failure_reason": None}
    if state == "rendered":
        update["rendered_at"] = timestamp
        update["engine"] = request.get("engine", current.engine)
        if request.get("audio_file") is not None:
            update["audio_file"] = request["audio_file"]
    elif state == "played":
        update["played_at"] = timestamp
    else:
        update["failed_at"] = timestamp
        update["failure_reason"] = request.get("reason", "mock voice transition failed")
    record = current.model_copy(update=update)
    if args.dry_run:
        return (
            0,
            {
                "artifact_kind": "scout_voice_mock_transition_dry_run",
                "status": "completed",
                "dry_run": True,
                "record": record.model_dump(mode="json"),
                "boundary": {
                    **_closed_boundary(),
                    "voice_log_write_allowed": False,
                    "audio_playback_allowed": False,
                },
            },
        )
    _append_jsonl(Path(str(voice_log_path)), record.model_dump(mode="json"))
    debug_log_path = request.get("debug_log_path")
    if debug_log_path:
        _append_transport_transition_debug_event(
            debug_log_path=debug_log_path,
            event_prefix="debug_event.mock_voice_transition",
            kind="voice_cue_state_changed",
            source="scout_agent_builtin_tools",
            session_id=request.get("session_id", "voice_cue_session.agent_tool"),
            mission_id=request.get("mission_id"),
            timestamp=timestamp,
            subject_ref=record.cue_id,
            summary=f"Mock voice cue {record.state}.",
            payload=record.model_dump(mode="json"),
        )
    return (
        0,
        {
            "artifact_kind": "scout_voice_mock_transition_tool_output",
            "status": "completed",
            "dry_run": False,
            "record": record.model_dump(mode="json"),
            "voice_log_path": str(voice_log_path),
            "debug_log_path": debug_log_path,
            "boundary": {
                **_closed_boundary(),
                "voice_log_write_allowed": True,
                "audio_playback_allowed": False,
            },
        },
    )


def _outbound_mock_queue(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    from mock_outbound_transport import MockOutboundTransport

    request = _load_json(args.input)
    outbound_log_path = request.get("outbound_log_path")
    recipient_ref = request.get("recipient_ref")
    body_preview = request.get("body_preview")
    category = request.get("category", "skill_output_notice")
    if not outbound_log_path or not recipient_ref or not body_preview:
        return 2, _error_payload("outbound mock queue requires outbound_log_path, recipient_ref, and body_preview")
    if args.dry_run:
        return (
            0,
            {
                "artifact_kind": "scout_outbound_mock_queue_dry_run",
                "status": "completed",
                "dry_run": True,
                "message": {
                    "category": category,
                    "recipient_ref": recipient_ref,
                    "body_preview": body_preview,
                    "transport": "mock",
                    "state": "queued",
                },
                "boundary": {
                    **_closed_boundary(),
                    "mock_outbound_log_write_allowed": False,
                    "real_outbound_send_allowed": False,
                },
            },
        )
    debug_log = _debug_log_or_memory(request.get("debug_log_path"))
    transport = MockOutboundTransport(
        session_id=request.get("session_id", "outbound_session.agent_tool"),
        mission_id=request.get("mission_id"),
        debug_log=debug_log,
        timestamp_factory=_timestamp_factory(request),
    )
    message = transport.queue_message(
        category=category,
        recipient_ref=recipient_ref,
        subject_ref=request.get("subject_ref"),
        body_preview=body_preview,
        payload=dict(request.get("payload", {}) or {}),
        correlation_refs=list(request.get("correlation_refs", []) or []),
    )
    _append_jsonl(Path(str(outbound_log_path)), message.model_dump(mode="json"))
    return (
        0,
        {
            "artifact_kind": "scout_outbound_mock_queue_tool_output",
            "status": "completed",
            "dry_run": False,
            "message": message.model_dump(mode="json"),
            "outbound_log_path": str(outbound_log_path),
            "debug_log_path": request.get("debug_log_path"),
            "boundary": {
                **_closed_boundary(),
                "mock_outbound_log_write_allowed": True,
                "real_outbound_send_allowed": False,
            },
        },
    )


def _outbound_mock_transition(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    from mock_outbound_transport import MockOutboundMessage

    request = _load_json(args.input)
    outbound_log_path = request.get("outbound_log_path")
    message_id = request.get("message_id")
    state = request.get("state")
    if not outbound_log_path or not message_id or state not in {"sent", "failed", "mock-delivered", "cancelled"}:
        return 2, _error_payload("outbound mock transition requires outbound_log_path, message_id, and state")
    current = MockOutboundMessage.model_validate(
        _latest_jsonl_record(Path(str(outbound_log_path)), "message_id", str(message_id))
    )
    timestamp = request.get("transitioned_at", _utc_now())
    message = current.model_copy(update={"state": state, "updated_at": timestamp})
    if args.dry_run:
        return (
            0,
            {
                "artifact_kind": "scout_outbound_mock_transition_dry_run",
                "status": "completed",
                "dry_run": True,
                "message": message.model_dump(mode="json"),
                "boundary": {
                    **_closed_boundary(),
                    "mock_outbound_log_write_allowed": False,
                    "real_outbound_send_allowed": False,
                },
            },
        )
    _append_jsonl(Path(str(outbound_log_path)), message.model_dump(mode="json"))
    debug_log_path = request.get("debug_log_path")
    if debug_log_path:
        payload = message.model_dump(mode="json")
        if request.get("reason"):
            payload["reason"] = request["reason"]
        _append_transport_transition_debug_event(
            debug_log_path=debug_log_path,
            event_prefix="debug_event.mock_outbound_transition",
            kind="outbound_message_state_changed",
            source="scout_agent_builtin_tools",
            session_id=request.get("session_id", message.session_id),
            mission_id=request.get("mission_id"),
            timestamp=timestamp,
            subject_ref=message.message_id,
            summary=f"Mock outbound message {message.state}.",
            payload=payload,
        )
    return (
        0,
        {
            "artifact_kind": "scout_outbound_mock_transition_tool_output",
            "status": "completed",
            "dry_run": False,
            "message": message.model_dump(mode="json"),
            "outbound_log_path": str(outbound_log_path),
            "debug_log_path": debug_log_path,
            "boundary": {
                **_closed_boundary(),
                "mock_outbound_log_write_allowed": True,
                "real_outbound_send_allowed": False,
            },
        },
    )


def _spatial_imprint_trigger_dry_run(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    from spatial_imprint_cli import run_spatial_imprint_cli

    request = _load_json(args.input)
    imprint_set_path = request.get("imprint_set_path")
    context_path = request.get("context_path")
    if not imprint_set_path or not context_path:
        return 2, _error_payload("spatial imprint dry-run requires imprint_set_path and context_path")
    argv = [
        "trigger-dry-run",
        "--imprint-set",
        str(imprint_set_path),
        "--context",
        str(context_path),
    ]
    for key in request.get("previous_trigger_keys", []) or []:
        argv.extend(["--previous-trigger-key", str(key)])
    return run_spatial_imprint_cli(argv)


def _spatial_imprint_export_pretrip(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    from pretrip_spatial_imprint_export import (
        build_pretrip_spatial_imprint_export_for_workspace,
        write_pretrip_spatial_imprint_export_for_workspace,
    )

    request = _load_json(args.input)
    project_root = request.get("project_root")
    if not project_root:
        return 2, _error_payload("spatial imprint export requires project_root")
    if args.dry_run:
        _, imprint_set, manifest, _, _ = build_pretrip_spatial_imprint_export_for_workspace(
            project_root
        )
        return (
            0,
            {
                "artifact_kind": "scout_spatial_imprint_export_pretrip_dry_run",
                "status": "completed",
                "dry_run": True,
                "manifest": manifest.model_dump(mode="json"),
                "reviewed_imprint_count": len(imprint_set.imprints),
                "boundary": {
                    **_closed_boundary(),
                    "workspace_file_mutation_allowed": False,
                    "candidate_only": True,
                },
            },
        )
    manifest = write_pretrip_spatial_imprint_export_for_workspace(project_root)
    return (
        0,
        {
            "artifact_kind": "scout_spatial_imprint_export_pretrip_tool_output",
            "status": "completed",
            "dry_run": False,
            "manifest": manifest.model_dump(mode="json"),
            "boundary": {
                **_closed_boundary(),
                "workspace_file_mutation_allowed": True,
                "candidate_only": True,
                "runtime_activation_allowed": False,
            },
        },
    )


def _spatial_imprint_store_list(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    from spatial_imprint_store import (
        load_spatial_imprint_store,
        spatial_imprint_set_from_store,
    )

    request = _load_json(args.input)
    store_path = request.get("store_path")
    if not store_path:
        return 2, _error_payload("spatial imprint store list requires store_path")
    store = load_spatial_imprint_store(store_path, trip_id=request.get("trip_id"))
    imprint_set = spatial_imprint_set_from_store(
        store,
        include_inactive=bool(request.get("include_inactive", False)),
    )
    return (
        0,
        {
            "artifact_kind": "scout_spatial_imprint_store_list",
            "status": "completed",
            "store": store.model_dump(mode="json"),
            "active_imprint_set": imprint_set.model_dump(mode="json"),
            "boundary": _closed_boundary(),
        },
    )


def _spatial_imprint_plant(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    from spatial_imprint_models import SpatialImprint
    from spatial_imprint_store import plant_spatial_imprint

    request = _load_json(args.input)
    store_path = request.get("store_path")
    trip_id = request.get("trip_id")
    actor_ref = request.get("actor_ref") or request.get("authorized_by")
    imprint_payload = request.get("imprint")
    if request.get("imprint_path"):
        imprint_payload = _load_json(Path(request["imprint_path"]))
    if not store_path or not trip_id or not actor_ref or not isinstance(imprint_payload, dict):
        return 2, _error_payload("spatial imprint plant requires store_path, trip_id, actor_ref, and imprint")
    imprint = SpatialImprint.model_validate(imprint_payload)
    if args.dry_run:
        return (
            0,
            {
                "artifact_kind": "scout_spatial_imprint_plant_dry_run",
                "status": "completed",
                "dry_run": True,
                "imprint": imprint.model_dump(mode="json"),
                "boundary": {
                    **_closed_boundary(),
                    "workspace_file_mutation_allowed": False,
                    "advisory_cue_store": True,
                },
            },
        )
    store = plant_spatial_imprint(
        store_path,
        imprint,
        trip_id=trip_id,
        authorized_by=actor_ref,
        planted_at=request.get("planted_at"),
        reason=request.get("reason"),
        allow_admin_persistent=bool(request.get("allow_admin_persistent", False)),
    )
    return (
        0,
        {
            "artifact_kind": "scout_spatial_imprint_plant_tool_output",
            "status": "completed",
            "dry_run": False,
            "store": store.model_dump(mode="json"),
            "boundary": {
                **_closed_boundary(),
                "workspace_file_mutation_allowed": True,
                "advisory_cue_store": True,
            },
        },
    )


def _spatial_imprint_expire(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    from spatial_imprint_store import expire_spatial_imprint, load_spatial_imprint_store

    request = _load_json(args.input)
    store_path = request.get("store_path")
    imprint_id = request.get("imprint_id")
    actor_ref = request.get("actor_ref") or request.get("authorized_by")
    if not store_path or not imprint_id or not actor_ref:
        return 2, _error_payload("spatial imprint expire requires store_path, imprint_id, and actor_ref")
    if args.dry_run:
        store = load_spatial_imprint_store(store_path)
        if not any(imprint.imprint_id == imprint_id for imprint in store.imprints):
            return 2, _error_payload(f"unknown spatial imprint: {imprint_id}")
        return (
            0,
            {
                "artifact_kind": "scout_spatial_imprint_expire_dry_run",
                "status": "completed",
                "dry_run": True,
                "imprint_id": imprint_id,
                "boundary": {
                    **_closed_boundary(),
                    "workspace_file_mutation_allowed": False,
                    "advisory_cue_store": True,
                },
            },
        )
    store = expire_spatial_imprint(
        store_path,
        imprint_id=imprint_id,
        authorized_by=actor_ref,
        expired_at=request.get("expired_at"),
        reason=request.get("reason"),
    )
    return (
        0,
        {
            "artifact_kind": "scout_spatial_imprint_expire_tool_output",
            "status": "completed",
            "dry_run": False,
            "store": store.model_dump(mode="json"),
            "boundary": {
                **_closed_boundary(),
                "workspace_file_mutation_allowed": True,
                "advisory_cue_store": True,
            },
        },
    )


def _spatial_imprint_delete(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    from spatial_imprint_store import (
        delete_spatial_imprint_tombstone,
        load_spatial_imprint_store,
    )

    request = _load_json(args.input)
    store_path = request.get("store_path")
    imprint_id = request.get("imprint_id")
    actor_ref = request.get("actor_ref") or request.get("authorized_by")
    if not store_path or not imprint_id or not actor_ref:
        return 2, _error_payload("spatial imprint delete requires store_path, imprint_id, and actor_ref")
    if args.dry_run:
        store = load_spatial_imprint_store(store_path)
        if not any(imprint.imprint_id == imprint_id for imprint in store.imprints):
            return 2, _error_payload(f"unknown spatial imprint: {imprint_id}")
        return (
            0,
            {
                "artifact_kind": "scout_spatial_imprint_delete_dry_run",
                "status": "completed",
                "dry_run": True,
                "imprint_id": imprint_id,
                "boundary": {
                    **_closed_boundary(),
                    "workspace_file_mutation_allowed": False,
                    "advisory_cue_store": True,
                },
            },
        )
    store = delete_spatial_imprint_tombstone(
        store_path,
        imprint_id=imprint_id,
        authorized_by=actor_ref,
        deleted_at=request.get("deleted_at"),
        reason=request.get("reason"),
    )
    return (
        0,
        {
            "artifact_kind": "scout_spatial_imprint_delete_tool_output",
            "status": "completed",
            "dry_run": False,
            "store": store.model_dump(mode="json"),
            "boundary": {
                **_closed_boundary(),
                "workspace_file_mutation_allowed": True,
                "advisory_cue_store": True,
            },
        },
    )


def _risk_attribution(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    from pretrip_risk_attribution_diagnostic import (
        build_risk_attribution_diagnostic,
        write_diagnostic,
        write_warning_cp_proposals,
    )

    request = _load_json(args.input)
    route_risk_path = request.get("route_risk_path")
    if not route_risk_path:
        return 2, _error_payload("risk attribution requires route_risk_path")
    diagnostic = build_risk_attribution_diagnostic(
        route_risk_path=route_risk_path,
        gis_perception_path=request.get("gis_perception_path"),
        route_note_ln_proposals_path=request.get("route_note_ln_proposals_path"),
        join_radius_m=float(request.get("join_radius_m", 100.0)),
        top_n=int(request.get("top_n", 10)),
    )
    output_path = args.output or _optional_path(request.get("output_path"))
    warning_output_path = _optional_path(request.get("warning_cp_output_path"))
    artifact_refs: list[str] = []
    if not args.dry_run and output_path is not None:
        write_diagnostic(diagnostic, output_path)
        artifact_refs.append(str(output_path))
    if not args.dry_run and warning_output_path is not None:
        write_warning_cp_proposals(diagnostic, warning_output_path)
        artifact_refs.append(str(warning_output_path))
    return (
        0,
        {
            "artifact_kind": "scout_risk_attribution_tool_output",
            "status": "completed",
            "dry_run": args.dry_run,
            "diagnostic": diagnostic,
            "artifact_refs": artifact_refs,
            "boundary": {
                **_closed_boundary(),
                "candidate_only": True,
                "weighted_risk_score_mutation_allowed": False,
            },
        },
    )


def _risk_heatmap(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    from pretrip_risk_heatmap import (
        build_calibrated_risk_heatmap,
        update_workspace_project_refs,
        write_heatmap_geojson,
        write_heatmap_metadata,
        write_heatmap_preview_png,
    )

    request = _load_json(args.input)
    route_risk_path = request.get("route_risk_path")
    diagnostic_path = request.get("risk_attribution_diagnostic_path") or request.get("diagnostic_path")
    if not route_risk_path or not diagnostic_path:
        return 2, _error_payload("risk heatmap requires route_risk_path and diagnostic_path")
    heatmap = build_calibrated_risk_heatmap(
        route_risk_path=route_risk_path,
        risk_attribution_diagnostic_path=diagnostic_path,
        warning_cp_proposals_path=request.get("warning_cp_proposals_path"),
    )
    output_path = args.output or _optional_path(request.get("output_path"))
    metadata_path = _optional_path(request.get("metadata_output_path"))
    preview_path = _optional_path(request.get("preview_png_path"))
    artifact_refs: list[str] = []
    if not args.dry_run and output_path is not None:
        write_heatmap_geojson(heatmap, output_path)
        artifact_refs.append(str(output_path))
    if not args.dry_run and metadata_path is not None:
        write_heatmap_metadata(heatmap, metadata_path)
        artifact_refs.append(str(metadata_path))
    if not args.dry_run and preview_path is not None:
        write_heatmap_preview_png(heatmap, preview_path)
        artifact_refs.append(str(preview_path))
    workspace = _optional_path(request.get("workspace"))
    if (
        not args.dry_run
        and workspace is not None
        and output_path is not None
        and metadata_path is not None
        and preview_path is not None
        and request.get("update_project_refs", False)
    ):
        update_workspace_project_refs(
            workspace=workspace,
            heatmap_path=output_path,
            metadata_path=metadata_path,
            preview_path=preview_path,
            heatmap=heatmap,
        )
    return (
        0,
        {
            "artifact_kind": "scout_risk_heatmap_tool_output",
            "status": "completed",
            "dry_run": args.dry_run,
            "metadata": heatmap["metadata"],
            "feature_count": len(heatmap.get("features", [])),
            "warning_cp_overlay_count": len(heatmap.get("warning_cp_overlay", [])),
            "artifact_refs": artifact_refs,
            "boundary": {
                **_closed_boundary(),
                "candidate_only": True,
                "route_aligned_samples_only": True,
            },
        },
    )


def _safety_action_shelter_direction(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    from scout_safety_action import build_shelter_direction

    request = _load_json(args.input)
    project_root = request.get("project_root")
    position = request.get("position")
    if not project_root or not isinstance(position, dict):
        return 2, _error_payload("shelter direction requires project_root and position")
    result = build_shelter_direction(
        project_root=project_root,
        position=position,
        query=str(request.get("query", "")),
        limit=int(request.get("limit", 3)),
        ttl_seconds=int(request.get("ttl_seconds", 600)),
    )
    return (0 if result["status"] == "completed" else 2, result)


def _sos_playbook_run(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    from scout_sos_playbook import run_mock_sos_playbook

    request = _load_json(args.input)
    sos_event = request.get("sos_event")
    if request.get("sos_event_path"):
        sos_event = _load_json(Path(request["sos_event_path"]))
    if not isinstance(sos_event, dict):
        return 2, _error_payload("SOS playbook requires sos_event or sos_event_path")
    result = run_mock_sos_playbook(
        sos_event=sos_event,
        debug_log_path=request.get("debug_log_path"),
        voice_log_path=request.get("voice_log_path"),
        recipient_refs=list(request.get("recipient_refs", []) or []),
        dry_run=args.dry_run,
        mock_deliver=bool(request.get("mock_deliver", False)),
        render_voice_mock=bool(request.get("render_voice_mock", True)),
    )
    return (0 if result.status == "completed" else 2, result.model_dump(mode="json"))


def _pretrip_workspace_edit(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    from pretrip_workspace_edit import (
        PreTripWorkspaceEditRequest,
        append_pretrip_workspace_edit,
        apply_pretrip_workspace_edit_to_workspace,
    )

    request = _load_json(args.input)
    project_root = request.get("project_root")
    edit_payload = request.get("edit_request") or request.get("request")
    if not project_root or not isinstance(edit_payload, dict):
        return 2, _error_payload("pretrip workspace edit requires project_root and edit_request")
    edit_request = PreTripWorkspaceEditRequest.model_validate(edit_payload)
    if args.dry_run:
        return (
            0,
            {
                "artifact_kind": "scout_pretrip_workspace_edit_dry_run",
                "status": "completed",
                "dry_run": True,
                "operation": edit_request.operation,
                "validated_request": edit_request.model_dump(mode="json"),
                "boundary": {
                    **_closed_boundary(),
                    "candidate_only": True,
                    "workspace_file_mutation_allowed": False,
                },
            },
        )
    if request.get("apply_to_workspace", False):
        result = apply_pretrip_workspace_edit_to_workspace(project_root, edit_request)
    else:
        log = append_pretrip_workspace_edit(project_root, edit_request)
        result = log.model_dump(mode="json")
    return (
        0,
        {
            "artifact_kind": "scout_pretrip_workspace_edit_tool_output",
            "status": "completed",
            "dry_run": False,
            "result": result,
            "boundary": {
                **_closed_boundary(),
                "candidate_only": True,
                "workspace_file_mutation_allowed": True,
                "package_mutation_allowed": False,
                "mission_graph_mutation_allowed": False,
            },
        },
    )


def _pretrip_import_gpx(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    from pretrip_import import PretripImportRequest, run_pretrip_import

    request = _load_json(args.input)
    project_id = request.get("project_id")
    gpx_path = request.get("golden_route_gpx") or request.get("primary_gpx")
    workspace_root = request.get("workspace_root")
    if not project_id or not gpx_path or not workspace_root:
        return 2, _error_payload("pretrip import requires project_id, golden_route_gpx, and workspace_root")
    import_request = PretripImportRequest(
        project_id=str(project_id),
        primary_gpx=Path(str(gpx_path)),
        workspace_root=Path(str(workspace_root)),
        reference_dir=_optional_path(request.get("reference_dir")),
        reference_gpx_paths=tuple(
            Path(str(path)) for path in request.get("reference_gpx_paths", []) or []
        ),
        profile=request.get("profile", "pi-offline"),
        template_project_root=_optional_path(request.get("template_project_root")),
        checkpoint_spacing_m=float(request.get("checkpoint_spacing_m", 1500.0)),
        max_reference_display_points=int(
            request.get("max_reference_display_points", 1000)
        ),
        overwrite=bool(request.get("overwrite", False)),
        import_timestamp=request.get("import_timestamp"),
        import_stage=request.get("import_stage", "pretrip"),
    )
    if args.dry_run:
        return (
            0,
            {
                "artifact_kind": "scout_pretrip_import_gpx_dry_run",
                "status": "completed",
                "dry_run": True,
                "project_id": import_request.project_id,
                "workspace_root": str(import_request.workspace_root),
                "profile": import_request.profile,
                "import_stage": import_request.import_stage,
                "boundary": {
                    **_closed_boundary(),
                    "workspace_file_mutation_allowed": False,
                    "candidate_only": True,
                    "raw_gpx_embedded": False,
                },
            },
        )
    manifest = run_pretrip_import(import_request)
    return (
        0,
        {
            "artifact_kind": "scout_pretrip_import_gpx_tool_output",
            "status": "completed",
            "dry_run": False,
            "manifest": manifest,
            "boundary": {
                **_closed_boundary(),
                "workspace_file_mutation_allowed": True,
                "candidate_only": True,
                "raw_gpx_embedded": False,
            },
        },
    )


def _pretrip_prepare_layers(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    from pretrip_layer_preparation import LayerPreparationRequest, run_layer_preparation

    request = _load_json(args.input)
    if request.get("allow_network_fetch") or request.get("network_mode") == "explicit-fetch":
        return 2, _error_payload("agent layer preparation wrapper is no-network only")
    project_root = _optional_path(request.get("project_root"))
    project_id = request.get("project_id") or (project_root.name if project_root else None)
    if not project_id and not project_root:
        return 2, _error_payload("pretrip layer preparation requires project_id or project_root")
    layers = _layers_from_request(request.get("layers"))
    layer_request = LayerPreparationRequest(
        project_id=str(project_id),
        workspace_root=_optional_path(request.get("workspace_root")),
        project_root=project_root,
        layers=layers,
        profile=request.get("profile", "pi-offline"),
        network_mode="no-network",
        allow_network_fetch=False,
        bbox=request.get("bbox"),
        route_corridor_m=float(request.get("route_corridor_m", 500.0)),
        prepared_at=request.get("prepared_at"),
    )
    if args.dry_run:
        return (
            0,
            {
                "artifact_kind": "scout_pretrip_prepare_layers_dry_run",
                "status": "completed",
                "dry_run": True,
                "project_id": layer_request.project_id,
                "layers": list(layer_request.layers),
                "network_mode": layer_request.network_mode,
                "boundary": {
                    **_closed_boundary(),
                    "workspace_file_mutation_allowed": False,
                    "candidate_only": True,
                    "network_calls_made": False,
                },
            },
        )
    manifest = run_layer_preparation(layer_request)
    return (
        0,
        {
            "artifact_kind": "scout_pretrip_prepare_layers_tool_output",
            "status": "completed",
            "dry_run": False,
            "manifest": manifest,
            "boundary": {
                **_closed_boundary(),
                "workspace_file_mutation_allowed": True,
                "candidate_only": True,
                "network_calls_made": False,
            },
        },
    )


def _pretrip_artifact_manifest(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    from pretrip_artifact_manifest import build_pretrip_artifact_manifest

    request = _load_json(args.input)
    project_json_path = _project_json_path_from_request(request)
    try:
        manifest = build_pretrip_artifact_manifest(project_json_path).to_dict()
    except Exception as exc:  # noqa: BLE001 - keep agent tool output structured.
        return 2, _error_payload(str(exc))
    return (
        0,
        {
            "artifact_kind": "scout_pretrip_artifact_manifest_tool_output",
            "status": "completed",
            "project_json_path": str(project_json_path),
            "manifest": manifest,
            "boundary": {
                **_closed_boundary(),
                "read_only": True,
                "workspace_file_mutation_allowed": False,
                "candidate_only": True,
            },
        },
    )


def _pretrip_readiness(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    from pretrip_readiness import (
        evaluate_pretrip_readiness,
        load_skill_config_manifest,
    )

    request = _load_json(args.input)
    route_plan = request.get("route_plan")
    if request.get("route_plan_path"):
        route_plan = _load_json(Path(str(request["route_plan_path"])))
    if not isinstance(route_plan, dict):
        return 2, _error_payload("pretrip readiness requires route_plan or route_plan_path")

    config = None
    if request.get("skill_config_manifest_path") or request.get("config_path"):
        config = load_skill_config_manifest(
            Path(str(request.get("skill_config_manifest_path") or request["config_path"]))
        )
    try:
        report = evaluate_pretrip_readiness(route_plan, skill_config_manifest=config)
    except Exception as exc:  # noqa: BLE001 - keep agent tool output structured.
        return 2, _error_payload(str(exc))
    findings = [asdict(finding) for finding in report.findings]
    return (
        0,
        {
            "artifact_kind": "scout_pretrip_readiness_tool_output",
            "status": "completed",
            "readiness": {
                "status": report.status.value,
                "finding_count": len(findings),
                "findings": findings,
            },
            "boundary": {
                **_closed_boundary(),
                "read_only": True,
                "decision_support_only": True,
                "workspace_file_mutation_allowed": False,
                "hard_readiness_mutation_allowed": False,
            },
        },
    )


def _pretrip_decision_register(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    from pretrip_decision_register import load_pretrip_decision_register

    request = _load_json(args.input)
    register_path = (
        _optional_path(request.get("register_path"))
        or Path(__file__).resolve().parent
        / "tests"
        / "fixtures"
        / "pretrip"
        / "decision_register.json"
    )
    try:
        register = load_pretrip_decision_register(register_path)
    except Exception as exc:  # noqa: BLE001 - keep agent tool output structured.
        return 2, _error_payload(str(exc))
    payload = register.model_dump(mode="json")
    return (
        0,
        {
            "artifact_kind": "scout_pretrip_decision_register_tool_output",
            "status": "completed",
            "register_path": str(register_path),
            "summary": {
                "register_id": register.register_id,
                "resolved_count": len(register.resolved_decisions),
                "open_question_count": len(register.open_questions),
                "metadata_only": register.metadata_only,
                "alpha_workable_mode": register.alpha_workable_mode,
                "runtime_operator_confirmation_required": (
                    register.runtime_operator_confirmation_required
                ),
            },
            "register": payload,
            "boundary": {
                **_closed_boundary(),
                "read_only": True,
                "workspace_file_mutation_allowed": False,
                "runtime_activation_allowed": False,
            },
        },
    )


def _pretrip_review_append_decisions(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    from pretrip_review_decision_log import (
        ReviewDecisionRecord,
        load_review_decision_log,
    )
    from pretrip_review_decision_store import (
        append_review_decisions,
        rebuild_review_decision_log,
    )

    request = _load_json(args.input)
    try:
        log_path = _review_decision_log_path_from_request(request)
        records = [
            ReviewDecisionRecord.model_validate(record)
            for record in _review_decision_record_payloads(request)
        ]
    except Exception as exc:  # noqa: BLE001 - return structured tool failures.
        return 2, _error_payload(str(exc))

    try:
        if args.dry_run:
            current = load_review_decision_log(log_path)
            rebuilt = rebuild_review_decision_log(current, [*current.decisions, *records])
        else:
            rebuilt = append_review_decisions(log_path, records)
    except Exception as exc:  # noqa: BLE001 - validation failures stay JSON-shaped.
        return 2, _error_payload(str(exc))

    return (
        0,
        {
            "artifact_kind": "scout_pretrip_review_append_decisions_tool_output",
            "status": "completed",
            "dry_run": args.dry_run,
            "log_path": str(log_path),
            "decision_count_added": len(records),
            "decision_ids": [record.decision_id for record in records],
            "counts": rebuilt.counts.model_dump(mode="json"),
            "apply_summary": rebuilt.apply_summary.model_dump(mode="json"),
            "boundary": {
                **_closed_boundary(),
                "append_only": True,
                "workspace_file_mutation_allowed": not args.dry_run,
                "source_mutation_allowed": False,
                "package_mutation_allowed": False,
                "runtime_mutation_allowed": False,
                "phase1_runtime_mutation_allowed": False,
                "phase2_writeback_allowed": False,
                "compiles_mission_graph": False,
                "raw_payloads_embedded": False,
            },
        },
    )


def _pretrip_departure_reviewed_candidates(
    args: argparse.Namespace,
) -> tuple[int, dict[str, Any]]:
    from pretrip_departure_reviewed_candidates import (
        build_departure_reviewed_candidates_from_apply_plan,
        write_departure_reviewed_candidates_for_workspace,
    )
    from pretrip_review_decision_apply import load_review_decision_apply_plan

    request = _load_json(args.input)
    project_root = request.get("project_root")
    if not project_root:
        return 2, _error_payload("departure reviewed candidates requires project_root")
    if args.dry_run:
        root = Path(str(project_root))
        project = _load_json(root / "project.json")
        apply_plan_ref = str(
            project.get("review_decision_apply_plan_ref", "outputs/review_decision_apply_plan.json")
        )
        package = build_departure_reviewed_candidates_from_apply_plan(
            project_id=str(project.get("project_id") or root.name),
            source_apply_plan_ref=apply_plan_ref,
            apply_plan=load_review_decision_apply_plan(root / apply_plan_ref),
        )
        return (
            0,
            {
                "artifact_kind": "scout_pretrip_departure_reviewed_candidates_dry_run",
                "status": "completed",
                "dry_run": True,
                "package": package.model_dump(mode="json"),
                "boundary": {
                    **_closed_boundary(),
                    "workspace_file_mutation_allowed": False,
                    "package_addendum_only": True,
                    "runtime_activation_allowed": False,
                },
            },
        )
    package = write_departure_reviewed_candidates_for_workspace(project_root)
    return (
        0,
        {
            "artifact_kind": "scout_pretrip_departure_reviewed_candidates_tool_output",
            "status": "completed",
            "dry_run": False,
            "package": package.model_dump(mode="json"),
            "boundary": {
                **_closed_boundary(),
                "workspace_file_mutation_allowed": True,
                "package_addendum_only": True,
                "runtime_activation_allowed": False,
            },
        },
    )


def _pretrip_runtime_export(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    from pretrip_final_mission_graph import FinalMissionGraphArtifact
    from pretrip_runtime_export import (
        build_runtime_export_bundle_manifest,
        write_runtime_export_bundle_for_workspace,
    )
    from pretrip_runtime_handoff import RuntimeHandoffManifest

    request = _load_json(args.input)
    workspace_root = request.get("workspace_root") or request.get("project_root")
    final_mission_graph_path = request.get("final_mission_graph_path")
    runtime_handoff_path = request.get("runtime_handoff_path")
    export_id = request.get("export_id")
    if not workspace_root or not final_mission_graph_path or not runtime_handoff_path or not export_id:
        return 2, _error_payload(
            "runtime export requires workspace_root, final_mission_graph_path, runtime_handoff_path, and export_id"
        )
    final_graph = FinalMissionGraphArtifact.model_validate_json(
        Path(str(final_mission_graph_path)).read_text(encoding="utf-8")
    )
    handoff = RuntimeHandoffManifest.model_validate_json(
        Path(str(runtime_handoff_path)).read_text(encoding="utf-8")
    )
    if args.dry_run:
        manifest = build_runtime_export_bundle_manifest(
            final_graph,
            handoff,
            export_id=str(export_id),
        )
        return (
            0,
            {
                "artifact_kind": "scout_pretrip_runtime_export_dry_run",
                "status": "completed",
                "dry_run": True,
                "manifest": manifest.model_dump(mode="json"),
                "boundary": {
                    **_closed_boundary(),
                    "runtime_file_write_allowed": False,
                    "runtime_activation_allowed": False,
                    "safety_api_calls_allowed": False,
                },
            },
        )
    manifest = write_runtime_export_bundle_for_workspace(
        workspace_root,
        final_graph,
        handoff,
        export_id=str(export_id),
    )
    return (
        0,
        {
            "artifact_kind": "scout_pretrip_runtime_export_tool_output",
            "status": "completed",
            "dry_run": False,
            "manifest": manifest.model_dump(mode="json"),
            "boundary": {
                **_closed_boundary(),
                "runtime_file_write_allowed": True,
                "runtime_activation_allowed": False,
                "safety_api_calls_allowed": False,
            },
        },
    )


def _pretrip_runtime_handoff(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    from pretrip_departure_gate import PreTripDepartureGateManifest
    from pretrip_final_mission_graph import FinalMissionGraphArtifact
    from pretrip_runtime_handoff import (
        build_runtime_handoff_manifest_from_final_graph,
        write_runtime_handoff_manifest_for_workspace,
    )

    request = _load_json(args.input)
    workspace_root = request.get("workspace_root") or request.get("project_root")
    departure_gate_path = request.get("departure_gate_path")
    final_mission_graph_path = request.get("final_mission_graph_path")
    handoff_id = request.get("handoff_id")
    approved_by = request.get("approved_by")
    approved_at = request.get("approved_at")
    handoff_target = request.get("handoff_target")
    rollback_reference = request.get("rollback_reference")
    if (
        not workspace_root
        or not departure_gate_path
        or not final_mission_graph_path
        or not handoff_id
        or not approved_by
        or not approved_at
        or not isinstance(handoff_target, dict)
        or not isinstance(rollback_reference, dict)
    ):
        return 2, _error_payload(
            "runtime handoff requires workspace_root, departure_gate_path, final_mission_graph_path, "
            "handoff_id, approved_by, approved_at, handoff_target, and rollback_reference"
        )
    departure_gate = PreTripDepartureGateManifest.model_validate_json(
        Path(str(departure_gate_path)).read_text(encoding="utf-8")
    )
    final_graph = FinalMissionGraphArtifact.model_validate_json(
        Path(str(final_mission_graph_path)).read_text(encoding="utf-8")
    )
    if args.dry_run:
        manifest = build_runtime_handoff_manifest_from_final_graph(
            departure_gate,
            final_graph,
            handoff_id=str(handoff_id),
            approved_by=str(approved_by),
            approved_at=str(approved_at),
            handoff_target=handoff_target,
            rollback_reference=rollback_reference,
        )
        return (
            0,
            {
                "artifact_kind": "scout_pretrip_runtime_handoff_dry_run",
                "status": "completed",
                "dry_run": True,
                "manifest": manifest.model_dump(mode="json"),
                "boundary": {
                    **_closed_boundary(),
                    "workspace_file_mutation_allowed": False,
                    "metadata_only": True,
                    "runtime_activation_allowed": False,
                },
            },
        )
    manifest = write_runtime_handoff_manifest_for_workspace(
        workspace_root,
        departure_gate,
        final_graph,
        handoff_id=str(handoff_id),
        approved_by=str(approved_by),
        approved_at=str(approved_at),
        handoff_target=handoff_target,
        rollback_reference=rollback_reference,
        output_ref=str(request.get("output_ref", "outputs/runtime_handoff_manifest.json")),
    )
    return (
        0,
        {
            "artifact_kind": "scout_pretrip_runtime_handoff_tool_output",
            "status": "completed",
            "dry_run": False,
            "manifest": manifest.model_dump(mode="json"),
            "boundary": {
                **_closed_boundary(),
                "workspace_file_mutation_allowed": True,
                "metadata_only": True,
                "runtime_activation_allowed": False,
            },
        },
    )


def _runtime_activation_preflight(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    from pretrip_runtime_activation_preflight import (
        build_runtime_activation_preflight_report,
    )

    request = _load_json(args.input)
    export_root = request.get("export_root")
    if not export_root:
        return 2, _error_payload("runtime activation preflight requires export_root")
    report = build_runtime_activation_preflight_report(export_root)
    return (
        0,
        {
            "artifact_kind": "scout_runtime_activation_preflight_tool_output",
            "status": "completed",
            "report": report.model_dump(mode="json"),
            "boundary": {
                **_closed_boundary(),
                "runtime_activation_allowed": False,
                "dry_run_only": True,
            },
        },
    )


def _runtime_load_dry_run(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    from runtime_load_dry_run import build_runtime_load_dry_run_report

    request = _load_json(args.input)
    export_root = request.get("export_root")
    if not export_root:
        return 2, _error_payload("runtime load dry-run requires export_root")
    report = build_runtime_load_dry_run_report(export_root)
    return (
        0,
        {
            "artifact_kind": "scout_runtime_load_dry_run_tool_output",
            "status": "completed",
            "report": report.model_dump(mode="json"),
            "boundary": {
                **_closed_boundary(),
                "runtime_activation_allowed": False,
                "dry_run_only": True,
            },
        },
    )


def _debug_log_or_memory(value: Any) -> FileRuntimeDebugEventLog | MemoryRuntimeDebugEventLog:
    if value:
        return FileRuntimeDebugEventLog(str(value))
    return MemoryRuntimeDebugEventLog()


def _timestamp_factory(request: dict[str, Any]):
    timestamp = request.get("timestamp") or request.get("created_at")
    if timestamp:
        return lambda: str(timestamp)
    return _utc_now


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _latest_jsonl_record(path: Path, key: str, value: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"missing JSONL log: {path}")
    matched: dict[str, Any] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if isinstance(payload, dict) and payload.get(key) == value:
            matched = payload
    if matched is None:
        raise ValueError(f"no record with {key}={value} in {path}")
    return matched


def _append_transport_transition_debug_event(
    *,
    debug_log_path: str | Path,
    event_prefix: str,
    kind: str,
    source: str,
    session_id: str,
    mission_id: str | None,
    timestamp: str,
    subject_ref: str,
    summary: str,
    payload: dict[str, Any],
) -> None:
    log = FileRuntimeDebugEventLog(debug_log_path)
    sequence = len(log.list_events()) + 1
    event = RuntimeDebugEvent(
        event_id=f"{event_prefix}.{sequence:06d}",
        session_id=session_id,
        mission_id=mission_id,
        timestamp=timestamp,
        sequence=sequence,
        kind=kind,  # type: ignore[arg-type]
        source=source,
        phase="phase35",
        severity="error" if payload.get("state") == "failed" else "info",
        subject_ref=subject_ref,
        correlation_refs=list(payload.get("source_event_refs", []) or []),
        summary=summary,
        payload=payload,
    )
    log.append(event)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON input must be an object: {path}")
    return payload


def _review_decision_log_path_from_request(request: dict[str, Any]) -> Path:
    if request.get("log_path"):
        return Path(str(request["log_path"]))
    project_root = request.get("project_root")
    if not project_root:
        raise ValueError("review append decisions requires log_path or project_root")
    root = Path(str(project_root))
    project_path = root if root.name == "project.json" else root / "project.json"
    project = _load_json(project_path)
    log_ref = project.get("review_decision_log_ref")
    if not isinstance(log_ref, str) or not log_ref:
        raise ValueError("project.json missing required review_decision_log_ref")
    log_ref_path = Path(log_ref)
    if log_ref_path.is_absolute() or ".." in log_ref_path.parts:
        raise ValueError("review_decision_log_ref must be project-relative")
    return project_path.parent / log_ref_path


def _review_decision_record_payloads(request: dict[str, Any]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    if request.get("record") is not None:
        payloads.append(_require_json_object(request["record"], "record"))
    if request.get("records") is not None:
        records = request["records"]
        if not isinstance(records, list):
            raise ValueError("records must be a list")
        payloads.extend(_require_json_object(record, "records[]") for record in records)
    if not payloads:
        raise ValueError("review append decisions requires record or records")
    return payloads


def _require_json_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _project_json_path_from_request(request: dict[str, Any]) -> Path:
    project_json_path = request.get("project_json_path") or request.get("project_json")
    if project_json_path:
        return Path(str(project_json_path))
    project_root = request.get("project_root")
    if project_root:
        root = Path(str(project_root))
        return root if root.name == "project.json" else root / "project.json"
    raise ValueError("pretrip artifact manifest requires project_json_path or project_root")


def _optional_path(value: Any) -> Path | None:
    if value is None or value == "":
        return None
    return Path(str(value))


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _source_manifest_from_request(request: dict[str, Any]) -> dict[str, Any]:
    if isinstance(request.get("source_manifest"), dict):
        return request["source_manifest"]
    source_manifest_path = (
        request.get("source_manifest_path")
        or request.get("source_manifest_file")
        or request.get("source_manifest")
    )
    if not source_manifest_path:
        raise ValueError("map raster-tiles requires source_manifest or source_manifest_path")
    return _load_json(Path(str(source_manifest_path)))


def _raster_tile_plan_kwargs(request: dict[str, Any]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    for key in (
        "cache_root",
        "min_zoom",
        "max_zoom",
        "capacity_limit_bytes",
        "estimated_tile_bytes",
        "tile_size",
    ):
        if request.get(key) is not None:
            kwargs[key] = request[key]
    if request.get("capacity_gib") is not None:
        kwargs["capacity_limit_bytes"] = _gib_to_bytes(request["capacity_gib"])
    return kwargs


def _tile_cache_plan_kwargs(request: dict[str, Any]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    for key in (
        "cache_root",
        "expansion_ratio",
        "min_zoom",
        "max_zoom",
        "capacity_limit_bytes",
        "estimated_tile_bytes",
        "tile_url_template",
        "plan_id",
    ):
        if request.get(key) is not None:
            kwargs[key] = request[key]
    if request.get("bbox_expansion_ratio") is not None:
        kwargs["expansion_ratio"] = request["bbox_expansion_ratio"]
    if request.get("capacity_gib") is not None:
        kwargs["capacity_limit_bytes"] = _gib_to_bytes(request["capacity_gib"])
    return kwargs


def _gib_to_bytes(value: Any) -> int:
    return int(float(value) * 1024 * 1024 * 1024)


def _layers_from_request(value: Any) -> tuple[str, ...]:
    if value is None:
        return ("osm", "overpass", "terrain", "imagery", "weather")
    if isinstance(value, str):
        return tuple(layer.strip() for layer in value.split(",") if layer.strip())
    return tuple(str(layer) for layer in value)


def _summary_from_pretrip_view(view: dict[str, Any], *, source_path: Path) -> dict[str, Any]:
    return {
        "artifact_kind": "scout_kb_pretrip_view_summary",
        "status": "completed",
        "project_id": view.get("project_id"),
        "source_path": str(source_path),
        "source_artifact_kind": view.get("artifact_kind"),
        "candidate_counts": view.get("candidate_counts") or {},
        "surface_targets": view.get("surface_targets") or {},
        "projection_only": bool(view.get("projection_only", True)),
    }


def _summary_from_pretrip_project_root(project_root: Path) -> dict[str, Any]:
    project = _load_json(project_root / "project.json")
    candidate_counts = {
        "checkpoints": _count_json_records(project_root / "candidates" / "checkpoints.json"),
        "segments": _count_json_records(project_root / "candidates" / "segments.json"),
        "map_candidate_groups": _count_json_records(project_root / "candidates" / "map_candidates.json"),
        "route_notes": _count_json_records(project_root / "candidates" / "route_note_candidates.json"),
    }
    review_queue = _load_json(project_root / "outputs" / "review_queue_manifest.json")
    admin_projection_path = project_root / "outputs" / "admin_projection.json"
    admin_projection = (
        _load_json(admin_projection_path) if admin_projection_path.exists() else {}
    )
    return {
        "artifact_kind": "scout_kb_pretrip_view_summary",
        "status": "completed",
        "project_id": project.get("project_id") or project.get("id"),
        "source_path": str(project_root),
        "candidate_counts": candidate_counts,
        "review_queue_item_count": len(review_queue.get("items", [])),
        "review_queue_status": review_queue.get("status"),
        "admin_projection_ref": str(admin_projection_path) if admin_projection else None,
        "projection_only": bool(admin_projection.get("projection_only", True)),
    }


def _count_json_records(path: Path) -> int:
    if not path.exists():
        return 0
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        if "items" in payload and isinstance(payload["items"], list):
            return len(payload["items"])
        return len(payload)
    return 0


def _closed_boundary() -> dict[str, bool]:
    return {
        "runtime_safety_truth": False,
        "live_safety_api_calls_allowed": False,
        "phase1_safety_mutation_allowed": False,
        "remote_outbound_send_allowed": False,
        "hardware_control_allowed": False,
    }


def _error_payload(message: str) -> dict[str, Any]:
    return {
        "artifact_kind": "scout_agent_builtin_tool_error",
        "status": "failed",
        "error": message,
        "boundary": _closed_boundary(),
    }


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
