from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any, Sequence

from scout_agent_cli import run_scout_agent_cli
from scout_agent_models import ScoutAgentToolBoundary


DEFAULT_MANIFEST_DIR = Path(__file__).resolve().parent / "tools" / "scout_agent_tool_manifests"


def run_scout_cli(argv: Sequence[str] | None = None) -> tuple[int, dict[str, Any]]:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command_group == "tools":
            return _run_tools_delegate(args)
        tool_id, request = _tool_request_for_args(args)
        return _run_registered_tool(
            tool_id,
            request=request,
            manifest_dir=args.manifest_dir,
            trace_log=args.trace_log,
            output=args.output,
            dry_run=getattr(args, "dry_run", False),
            authorized_by=getattr(args, "authorized_by", None),
            agent_run_id=args.agent_run_id,
            action_id=args.action_id,
        )
    except Exception as exc:  # noqa: BLE001 - CLI must return structured failures.
        return 2, {
            "artifact_kind": "scout_cli_error",
            "status": "failed",
            "error": str(exc),
            "boundary": ScoutAgentToolBoundary().model_dump(mode="json"),
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scout command-group CLI facade.")
    parser.add_argument("--manifest-dir", type=Path, default=DEFAULT_MANIFEST_DIR)
    parser.add_argument("--trace-log", type=Path, default=None)
    parser.add_argument("--agent-run-id", default="agent_run.scout_cli.manual")
    parser.add_argument("--action-id", default="agent_action.scout_cli.manual")
    parser.add_argument("--json", action="store_true")
    subparsers = parser.add_subparsers(dest="command_group", required=True)

    _add_tools_group(subparsers)
    _add_evidence_group(subparsers)
    _add_kb_group(subparsers)
    _add_hardware_group(subparsers)
    _add_checks_group(subparsers)
    _add_map_group(subparsers)
    _add_pretrip_group(subparsers)
    _add_cp_group(subparsers)
    _add_risk_group(subparsers)
    _add_debug_group(subparsers)
    _add_note_group(subparsers)
    _add_voice_group(subparsers)
    _add_outbound_group(subparsers)
    _add_imprint_group(subparsers)
    _add_safety_action_group(subparsers)
    _add_sos_group(subparsers)
    _add_runtime_group(subparsers)
    return parser


def _add_tools_group(subparsers: argparse._SubParsersAction) -> None:
    tools_parser = subparsers.add_parser("tools")
    tools_sub = tools_parser.add_subparsers(dest="tool_command", required=True)
    tools_sub.add_parser("list").add_argument("--json", action="store_true")
    describe = tools_sub.add_parser("describe")
    describe.add_argument("tool_id")
    describe.add_argument("--json", action="store_true")
    run = tools_sub.add_parser("run")
    run.add_argument("tool_id")
    run.add_argument("--input", type=Path, default=None)
    run.add_argument("--output", type=Path, default=None)
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--authorized-by", default=None)
    run.add_argument("--json", action="store_true")


def _add_evidence_group(subparsers: argparse._SubParsersAction) -> None:
    evidence = subparsers.add_parser("evidence")
    evidence_sub = evidence.add_subparsers(dest="evidence_command", required=True)
    sensorlog = evidence_sub.add_parser("sensorlog-to-gpx")
    sensorlog.add_argument("--input", "--sensorlog", dest="sensorlog_path", type=Path, required=True)
    sensorlog.add_argument("--output", type=Path, required=True)
    sensorlog.add_argument("--track-name", default=None)
    sensorlog.add_argument("--max-horizontal-accuracy", type=float, default=None)
    sensorlog.add_argument("--dry-run", action="store_true")
    sensorlog.add_argument("--authorized-by", default=None)
    sensorlog.add_argument("--json", action="store_true")


def _add_kb_group(subparsers: argparse._SubParsersAction) -> None:
    kb_parser = subparsers.add_parser("kb")
    kb_sub = kb_parser.add_subparsers(dest="kb_command", required=True)
    build = kb_sub.add_parser("build")
    build.add_argument("--project-root", "--trip-root", dest="project_root", type=Path, required=True)
    build.add_argument("--out", "--output", dest="output", type=Path, required=True)
    build.add_argument("--dry-run", action="store_true")
    build.add_argument("--authorized-by", default=None)
    build.add_argument("--json", action="store_true")
    query = kb_sub.add_parser("query")
    query.add_argument("--project-root", type=Path, default=None)
    query.add_argument("--index-path", type=Path, default=None)
    query.add_argument("--query", required=True)
    query.add_argument("--limit", type=int, default=8)
    query.add_argument("--evidence-type", action="append", default=[])
    query.add_argument("--output", type=Path, default=None)
    query.add_argument("--json", action="store_true")
    summary = kb_sub.add_parser("pretrip-view-summary")
    summary.add_argument("--project-root", type=Path, default=None)
    summary.add_argument("--view-path", type=Path, default=None)
    summary.add_argument("--output", type=Path, default=None)
    summary.add_argument("--json", action="store_true")
    hardware = kb_sub.add_parser("hardware-readiness-summary")
    hardware.add_argument("--fixture-path", type=Path, default=None)
    hardware.add_argument("--selected-provider-ref", default=None)
    hardware.add_argument("--output", type=Path, default=None)
    hardware.add_argument("--json", action="store_true")


def _add_hardware_group(subparsers: argparse._SubParsersAction) -> None:
    hardware = subparsers.add_parser("hardware")
    hardware_sub = hardware.add_subparsers(dest="hardware_command", required=True)
    summary = hardware_sub.add_parser("readiness-summary")
    summary.add_argument("--fixture-path", type=Path, default=None)
    summary.add_argument("--selected-provider-ref", default=None)
    summary.add_argument("--output", type=Path, default=None)
    summary.add_argument("--json", action="store_true")


def _add_checks_group(subparsers: argparse._SubParsersAction) -> None:
    checks = subparsers.add_parser("checks")
    checks_sub = checks.add_subparsers(dest="checks_command", required=True)
    pretrip = checks_sub.add_parser("pretrip-release")
    pretrip.add_argument("--repo-root", type=Path, default=None)
    pretrip.add_argument(
        "--project-json",
        "--project-json-path",
        dest="project_json_path",
        type=Path,
        default=None,
    )
    pretrip.add_argument("--output", type=Path, default=None)
    pretrip.add_argument("--json", action="store_true")
    runtime = checks_sub.add_parser("runtime-readiness")
    runtime.add_argument("--repo-root", type=Path, default=None)
    runtime.add_argument("--output", type=Path, default=None)
    runtime.add_argument("--json", action="store_true")


def _add_map_group(subparsers: argparse._SubParsersAction) -> None:
    map_parser = subparsers.add_parser("map")
    map_sub = map_parser.add_subparsers(dest="map_command", required=True)

    raster_source = map_sub.add_parser("raster-source")
    raster_source.add_argument("--source-geotiff", type=Path, required=True)
    raster_source.add_argument("--project-id", default=None)
    raster_source.add_argument("--layer-id", default=None)
    raster_source.add_argument("--recommended-cache-root", type=Path, default=None)
    raster_source.add_argument("--output", type=Path, default=None)
    raster_source.add_argument("--json", action="store_true")

    raster_tiles = map_sub.add_parser("raster-tiles")
    raster_tiles.add_argument(
        "--source-manifest",
        "--source-manifest-path",
        dest="source_manifest_path",
        type=Path,
        required=True,
    )
    raster_tiles.add_argument("--cache-root", type=Path, default=None)
    raster_tiles.add_argument("--min-zoom", type=int, default=None)
    raster_tiles.add_argument("--max-zoom", type=int, default=None)
    raster_tiles.add_argument("--capacity-gib", type=float, default=None)
    raster_tiles.add_argument("--max-tiles", type=int, default=None)
    raster_tiles.add_argument("--dry-run", action="store_true")
    raster_tiles.add_argument("--authorized-by", default=None)
    raster_tiles.add_argument("--output", type=Path, default=None)
    raster_tiles.add_argument("--json", action="store_true")

    tile_cache = map_sub.add_parser("tile-cache-plan")
    tile_cache.add_argument("--project-root", type=Path, default=None)
    tile_cache.add_argument("--bbox", "--bbox-wgs84", dest="bbox_wgs84", default=None)
    tile_cache.add_argument("--cache-root", type=Path, default=None)
    tile_cache.add_argument("--min-zoom", type=int, default=None)
    tile_cache.add_argument("--max-zoom", type=int, default=None)
    tile_cache.add_argument("--bbox-expansion-ratio", type=float, default=None)
    tile_cache.add_argument("--capacity-gib", type=float, default=None)
    tile_cache.add_argument("--tile-url-template", default=None)
    tile_cache.add_argument("--plan-id", default=None)
    tile_cache.add_argument("--output", type=Path, default=None)
    tile_cache.add_argument("--json", action="store_true")


def _add_pretrip_group(subparsers: argparse._SubParsersAction) -> None:
    pretrip = subparsers.add_parser("pretrip")
    pretrip_sub = pretrip.add_subparsers(dest="pretrip_command", required=True)
    import_gpx = pretrip_sub.add_parser("import-gpx")
    import_gpx.add_argument("--project-id", required=True)
    import_gpx.add_argument("--golden-route-gpx", type=Path, required=True)
    import_gpx.add_argument("--workspace-root", type=Path, required=True)
    import_gpx.add_argument("--reference-dir", type=Path, default=None)
    import_gpx.add_argument("--dry-run", action="store_true")
    import_gpx.add_argument("--authorized-by", default=None)
    import_gpx.add_argument("--output", type=Path, default=None)
    import_gpx.add_argument("--json", action="store_true")
    route_context = pretrip_sub.add_parser("route-context-collect")
    route_context.add_argument("--project-root", type=Path, default=None)
    route_context.add_argument("--project-id", default=None)
    route_context.add_argument("--workspace-root", type=Path, default=None)
    route_context.add_argument("--limit-route-notes", type=int, default=80)
    route_context.add_argument("--no-route-notes", action="store_true")
    route_context.add_argument("--collected-at", default=None)
    route_context.add_argument("--dry-run", action="store_true")
    route_context.add_argument("--authorized-by", default=None)
    route_context.add_argument("--output", type=Path, default=None)
    route_context.add_argument("--json", action="store_true")
    route_architecture = pretrip_sub.add_parser("route-architecture-collect")
    route_architecture.add_argument("--project-root", type=Path, default=None)
    route_architecture.add_argument("--project-id", default=None)
    route_architecture.add_argument("--workspace-root", type=Path, default=None)
    route_architecture.add_argument("--current-cp-id", default=None)
    route_architecture.add_argument("--current-time", default=None)
    route_architecture.add_argument("--target-cp-id", default=None)
    route_architecture.add_argument("--limit", type=int, default=12)
    route_architecture.add_argument("--generated-at", default=None)
    route_architecture.add_argument("--dry-run", action="store_true")
    route_architecture.add_argument("--authorized-by", default=None)
    route_architecture.add_argument("--output", type=Path, default=None)
    route_architecture.add_argument("--json", action="store_true")
    weather_decision = pretrip_sub.add_parser("weather-decision-collect")
    weather_decision.add_argument("--project-root", type=Path, default=None)
    weather_decision.add_argument("--project-id", default=None)
    weather_decision.add_argument("--workspace-root", type=Path, default=None)
    weather_decision.add_argument("--weather-points", dest="weather_points_path", default=None)
    weather_decision.add_argument("--warnings", dest="warnings_path", default=None)
    weather_decision.add_argument("--route-segments", dest="route_segments_path", default=None)
    weather_decision.add_argument("--default-township", default=None)
    weather_decision.add_argument("--generated-at", default=None)
    weather_decision.add_argument("--valid-until", default=None)
    weather_decision.add_argument("--provider", default="workspace_local_weather_points")
    weather_decision.add_argument("--dry-run", action="store_true")
    weather_decision.add_argument("--authorized-by", default=None)
    weather_decision.add_argument("--output", type=Path, default=None)
    weather_decision.add_argument("--json", action="store_true")
    contextual_permission = pretrip_sub.add_parser("contextual-permission-collect")
    contextual_permission.add_argument("--project-root", type=Path, default=None)
    contextual_permission.add_argument("--project-id", default=None)
    contextual_permission.add_argument("--workspace-root", type=Path, default=None)
    contextual_permission.add_argument("--current-time", default=None)
    contextual_permission.add_argument("--current-cp-id", default=None)
    contextual_permission.add_argument("--next-cp-id", default=None)
    contextual_permission.add_argument("--communication-status", default=None)
    contextual_permission.add_argument("--equipment-status", default=None)
    contextual_permission.add_argument("--remaining-safety-buffer-minutes", default=None)
    contextual_permission.add_argument("--requested-duration-minutes", default=None)
    contextual_permission.add_argument("--current-delay-minutes", default=None)
    contextual_permission.add_argument("--next-segment-uncertainty-minutes", default=None)
    contextual_permission.add_argument("--weather-reserve-minutes", default=None)
    contextual_permission.add_argument("--daylight-reserve-minutes", default=None)
    contextual_permission.add_argument("--retreat-reserve-minutes", default=None)
    contextual_permission.add_argument("--slowest-member-reserve-minutes", default=None)
    contextual_permission.add_argument("--generated-at", default=None)
    contextual_permission.add_argument("--dry-run", action="store_true")
    contextual_permission.add_argument("--authorized-by", default=None)
    contextual_permission.add_argument("--output", type=Path, default=None)
    contextual_permission.add_argument("--json", action="store_true")
    layers = pretrip_sub.add_parser("prepare-layers")
    layers.add_argument("--project-root", type=Path, default=None)
    layers.add_argument("--project-id", default=None)
    layers.add_argument("--workspace-root", type=Path, default=None)
    layers.add_argument("--layers", default=None)
    layers.add_argument("--profile", default="pi-offline")
    layers.add_argument("--dry-run", action="store_true")
    layers.add_argument("--authorized-by", default=None)
    layers.add_argument("--output", type=Path, default=None)
    layers.add_argument("--json", action="store_true")
    artifact_manifest = pretrip_sub.add_parser("artifact-manifest")
    artifact_manifest.add_argument("--project-root", type=Path, default=None)
    artifact_manifest.add_argument("--project-json", "--project-json-path", dest="project_json_path", type=Path, default=None)
    artifact_manifest.add_argument("--output", type=Path, default=None)
    artifact_manifest.add_argument("--json", action="store_true")
    readiness = pretrip_sub.add_parser("readiness")
    readiness.add_argument("--route-plan", type=Path, default=None)
    readiness.add_argument("--config", "--skill-config-manifest", dest="skill_config_manifest_path", type=Path, default=None)
    readiness.add_argument("--output", type=Path, default=None)
    readiness.add_argument("--json", action="store_true")
    decision_register = pretrip_sub.add_parser("decision-register")
    decision_register.add_argument("--register", "--register-path", dest="register_path", type=Path, default=None)
    decision_register.add_argument("--output", type=Path, default=None)
    decision_register.add_argument("--json", action="store_true")
    edit = pretrip_sub.add_parser("workspace-edit")
    edit.add_argument("--input", type=Path, required=True)
    edit.add_argument("--dry-run", action="store_true")
    edit.add_argument("--authorized-by", default=None)
    edit.add_argument("--output", type=Path, default=None)
    edit.add_argument("--json", action="store_true")
    review = pretrip_sub.add_parser("review")
    review_sub = review.add_subparsers(dest="pretrip_review_command", required=True)
    append_decision = review_sub.add_parser("append-decision")
    append_decision.add_argument("--project-root", type=Path, default=None)
    append_decision.add_argument("--log-path", type=Path, default=None)
    append_decision.add_argument("--input", type=Path, default=None)
    append_decision.add_argument("--record", type=Path, default=None)
    append_decision.add_argument("--dry-run", action="store_true")
    append_decision.add_argument("--authorized-by", default=None)
    append_decision.add_argument("--output", type=Path, default=None)
    append_decision.add_argument("--json", action="store_true")
    append_decisions = review_sub.add_parser("append-decisions")
    append_decisions.add_argument("--project-root", type=Path, default=None)
    append_decisions.add_argument("--log-path", type=Path, default=None)
    append_decisions.add_argument("--input", type=Path, default=None)
    append_decisions.add_argument("--records", type=Path, default=None)
    append_decisions.add_argument("--dry-run", action="store_true")
    append_decisions.add_argument("--authorized-by", default=None)
    append_decisions.add_argument("--output", type=Path, default=None)
    append_decisions.add_argument("--json", action="store_true")
    departure_reviewed = pretrip_sub.add_parser("departure-reviewed-candidates")
    departure_reviewed.add_argument("--project-root", type=Path, required=True)
    departure_reviewed.add_argument("--dry-run", action="store_true")
    departure_reviewed.add_argument("--authorized-by", default=None)
    departure_reviewed.add_argument("--output", type=Path, default=None)
    departure_reviewed.add_argument("--json", action="store_true")
    runtime_export = pretrip_sub.add_parser("runtime-export")
    runtime_export.add_argument("--workspace-root", "--project-root", dest="workspace_root", type=Path, required=True)
    runtime_export.add_argument("--final-mission-graph", "--final-mission-graph-path", dest="final_mission_graph_path", type=Path, required=True)
    runtime_export.add_argument("--runtime-handoff", "--runtime-handoff-path", dest="runtime_handoff_path", type=Path, required=True)
    runtime_export.add_argument("--export-id", required=True)
    runtime_export.add_argument("--dry-run", action="store_true")
    runtime_export.add_argument("--authorized-by", default=None)
    runtime_export.add_argument("--output", type=Path, default=None)
    runtime_export.add_argument("--json", action="store_true")
    runtime_handoff = pretrip_sub.add_parser("runtime-handoff")
    runtime_handoff.add_argument("--workspace-root", "--project-root", dest="workspace_root", type=Path, required=True)
    runtime_handoff.add_argument("--departure-gate", "--departure-gate-path", dest="departure_gate_path", type=Path, required=True)
    runtime_handoff.add_argument("--final-mission-graph", "--final-mission-graph-path", dest="final_mission_graph_path", type=Path, required=True)
    runtime_handoff.add_argument("--handoff-id", required=True)
    runtime_handoff.add_argument("--approved-by", required=True)
    runtime_handoff.add_argument("--approved-at", required=True)
    runtime_handoff.add_argument("--handoff-target", type=Path, required=True)
    runtime_handoff.add_argument("--rollback-reference", type=Path, required=True)
    runtime_handoff.add_argument("--output-ref", default="outputs/runtime_handoff_manifest.json")
    runtime_handoff.add_argument("--dry-run", action="store_true")
    runtime_handoff.add_argument("--authorized-by", default=None)
    runtime_handoff.add_argument("--output", type=Path, default=None)
    runtime_handoff.add_argument("--json", action="store_true")


def _add_cp_group(subparsers: argparse._SubParsersAction) -> None:
    cp = subparsers.add_parser("cp")
    cp_sub = cp.add_subparsers(dest="cp_command", required=True)
    for name in ("propose-add", "propose-delete", "proposal-preview"):
        command = cp_sub.add_parser(name)
        command.add_argument("--input", type=Path, default=None)
        command.add_argument("--candidate-ref", default=None)
        command.add_argument("--label", default=None)
        command.add_argument("--reason", default=None)
        command.add_argument("--dry-run", action="store_true")
        command.add_argument("--authorized-by", default=None)
        command.add_argument("--output", type=Path, default=None)
        command.add_argument("--json", action="store_true")
    apply_reviewed = cp_sub.add_parser("apply-reviewed-delta")
    apply_reviewed.add_argument("--project-root", type=Path, required=True)
    apply_reviewed.add_argument("--apply-plan", "--delta", dest="apply_plan_path", type=Path, default=None)
    apply_reviewed.add_argument("--output-ref", default=None)
    apply_reviewed.add_argument("--dry-run", action="store_true")
    apply_reviewed.add_argument("--authorized-by", default=None)
    apply_reviewed.add_argument("--output", type=Path, default=None)
    apply_reviewed.add_argument("--json", action="store_true")


def _add_risk_group(subparsers: argparse._SubParsersAction) -> None:
    risk = subparsers.add_parser("risk")
    risk_sub = risk.add_subparsers(dest="risk_command", required=True)
    for name in ("attribution", "heatmap"):
        command = risk_sub.add_parser(name)
        command.add_argument("--input", type=Path, default=None)
        command.add_argument("--route-risk-path", type=Path, default=None)
        command.add_argument("--diagnostic-path", type=Path, default=None)
        command.add_argument("--workspace", type=Path, default=None)
        command.add_argument("--dry-run", action="store_true")
        command.add_argument("--authorized-by", default=None)
        command.add_argument("--output", type=Path, default=None)
        command.add_argument("--json", action="store_true")


def _add_debug_group(subparsers: argparse._SubParsersAction) -> None:
    debug = subparsers.add_parser("debug")
    debug_sub = debug.add_subparsers(dest="debug_command", required=True)
    tail = debug_sub.add_parser("trace-tail")
    tail.add_argument("--trace-path", type=Path, required=True)
    tail.add_argument("--trace-kind", default="runtime_debug")
    tail.add_argument("--limit", type=int, default=20)
    tail.add_argument("--output", type=Path, default=None)
    tail.add_argument("--json", action="store_true")


def _add_note_group(subparsers: argparse._SubParsersAction) -> None:
    note = subparsers.add_parser("note")
    note_sub = note.add_subparsers(dest="note_command", required=True)
    append = note_sub.add_parser("append-flight-recorder")
    append.add_argument("--debug-log-path", type=Path, required=True)
    append.add_argument("--text", required=True)
    append.add_argument("--note-kind", default="user_report")
    append.add_argument("--source", default="scout_cli")
    append.add_argument("--authorized-by", default=None)
    append.add_argument("--output", type=Path, default=None)
    append.add_argument("--json", action="store_true")


def _add_voice_group(subparsers: argparse._SubParsersAction) -> None:
    voice = subparsers.add_parser("voice")
    voice_sub = voice.add_subparsers(dest="voice_command", required=True)
    preview = voice_sub.add_parser("preview")
    preview.add_argument("--text", "--text-zh", dest="text_zh", required=True)
    preview.add_argument("--out", "--audio-file", dest="audio_file", default="/tmp/scout-voice-preview.wav")
    preview.add_argument("--engine", default="piper")
    preview.add_argument("--output", type=Path, default=None)
    preview.add_argument("--json", action="store_true")
    queue = voice_sub.add_parser("mock-queue")
    queue.add_argument("--voice-log-path", type=Path, required=True)
    queue.add_argument("--debug-log-path", type=Path, default=None)
    queue.add_argument("--cue-id", required=True)
    queue.add_argument("--text", "--text-zh", dest="text_zh", required=True)
    queue.add_argument("--priority", default="info")
    queue.add_argument("--category", default="team")
    queue.add_argument("--engine", default="mock")
    queue.add_argument("--render-mock", action="store_true")
    queue.add_argument("--dry-run", action="store_true")
    queue.add_argument("--output", type=Path, default=None)
    queue.add_argument("--json", action="store_true")
    transition = voice_sub.add_parser("mock-transition")
    transition.add_argument("--voice-log-path", type=Path, required=True)
    transition.add_argument("--debug-log-path", type=Path, default=None)
    transition.add_argument("--cue-id", required=True)
    transition.add_argument("--state", required=True)
    transition.add_argument("--reason", default=None)
    transition.add_argument("--dry-run", action="store_true")
    transition.add_argument("--output", type=Path, default=None)
    transition.add_argument("--json", action="store_true")


def _add_outbound_group(subparsers: argparse._SubParsersAction) -> None:
    outbound = subparsers.add_parser("outbound")
    outbound_sub = outbound.add_subparsers(dest="outbound_command", required=True)
    queue = outbound_sub.add_parser("mock-queue")
    queue.add_argument("--outbound-log-path", type=Path, required=True)
    queue.add_argument("--debug-log-path", type=Path, default=None)
    queue.add_argument("--category", default="skill_output_notice")
    queue.add_argument("--recipient-ref", required=True)
    queue.add_argument("--body-preview", required=True)
    queue.add_argument("--subject-ref", default=None)
    queue.add_argument("--dry-run", action="store_true")
    queue.add_argument("--output", type=Path, default=None)
    queue.add_argument("--json", action="store_true")
    transition = outbound_sub.add_parser("mock-transition")
    transition.add_argument("--outbound-log-path", type=Path, required=True)
    transition.add_argument("--debug-log-path", type=Path, default=None)
    transition.add_argument("--message-id", required=True)
    transition.add_argument("--state", required=True)
    transition.add_argument("--reason", default=None)
    transition.add_argument("--dry-run", action="store_true")
    transition.add_argument("--output", type=Path, default=None)
    transition.add_argument("--json", action="store_true")


def _add_imprint_group(subparsers: argparse._SubParsersAction) -> None:
    imprint = subparsers.add_parser("imprint")
    imprint_sub = imprint.add_subparsers(dest="imprint_command", required=True)
    list_cmd = imprint_sub.add_parser("list")
    list_cmd.add_argument("--store", "--store-path", dest="store_path", type=Path, required=True)
    list_cmd.add_argument("--trip-id", default=None)
    list_cmd.add_argument("--include-inactive", action="store_true")
    list_cmd.add_argument("--output", type=Path, default=None)
    list_cmd.add_argument("--json", action="store_true")
    dry = imprint_sub.add_parser("trigger-dry-run")
    dry.add_argument("--imprint-set", type=Path, required=True)
    dry.add_argument("--context", type=Path, required=True)
    dry.add_argument("--previous-trigger-key", action="append", default=[])
    dry.add_argument("--output", type=Path, default=None)
    dry.add_argument("--json", action="store_true")
    export = imprint_sub.add_parser("export-pretrip")
    export.add_argument("--project-root", type=Path, required=True)
    export.add_argument("--dry-run", action="store_true")
    export.add_argument("--authorized-by", default=None)
    export.add_argument("--output", type=Path, default=None)
    export.add_argument("--json", action="store_true")
    for name in ("plant", "expire", "delete"):
        command = imprint_sub.add_parser(name)
        command.add_argument("--input", type=Path, required=True)
        command.add_argument("--dry-run", action="store_true")
        command.add_argument("--authorized-by", default=None)
        command.add_argument("--output", type=Path, default=None)
        command.add_argument("--json", action="store_true")


def _add_safety_action_group(subparsers: argparse._SubParsersAction) -> None:
    safety = subparsers.add_parser("safety-action")
    safety_sub = safety.add_subparsers(dest="safety_action_command", required=True)
    shelter = safety_sub.add_parser("shelter-direction")
    shelter.add_argument("--project-root", "--trip-root", dest="project_root", type=Path, required=True)
    shelter.add_argument("--position", type=Path, default=None)
    shelter.add_argument("--lat", type=float, default=None)
    shelter.add_argument("--lon", type=float, default=None)
    shelter.add_argument("--query", default="")
    shelter.add_argument("--limit", type=int, default=3)
    shelter.add_argument("--ttl-seconds", type=int, default=600)
    shelter.add_argument("--output", type=Path, default=None)
    shelter.add_argument("--json", action="store_true")


def _add_sos_group(subparsers: argparse._SubParsersAction) -> None:
    sos = subparsers.add_parser("sos")
    sos_sub = sos.add_subparsers(dest="sos_command", required=True)
    playbook = sos_sub.add_parser("playbook-run")
    playbook.add_argument("--sos-event", type=Path, required=True)
    playbook.add_argument("--debug-log-path", type=Path, default=None)
    playbook.add_argument("--voice-log-path", type=Path, default=None)
    playbook.add_argument("--recipient-ref", action="append", default=[])
    playbook.add_argument("--mock-deliver", action="store_true")
    playbook.add_argument("--no-render-voice-mock", dest="render_voice_mock", action="store_false")
    playbook.set_defaults(render_voice_mock=True)
    playbook.add_argument("--dry-run", action="store_true")
    playbook.add_argument("--authorized-by", default=None)
    playbook.add_argument("--output", type=Path, default=None)
    playbook.add_argument("--json", action="store_true")


def _add_runtime_group(subparsers: argparse._SubParsersAction) -> None:
    runtime = subparsers.add_parser("runtime")
    runtime_sub = runtime.add_subparsers(dest="runtime_command", required=True)
    for name in ("activation-preflight", "load-dry-run"):
        command = runtime_sub.add_parser(name)
        command.add_argument("--export-root", type=Path, required=True)
        command.add_argument("--output", type=Path, default=None)
        command.add_argument("--json", action="store_true")


def _run_tools_delegate(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    argv = ["tools", args.tool_command, "--manifest-dir", str(args.manifest_dir)]
    if args.tool_command == "describe":
        argv.insert(2, args.tool_id)
    elif args.tool_command == "run":
        argv.insert(2, args.tool_id)
        _append_optional_path(argv, "--input", args.input)
        _append_optional_path(argv, "--output", args.output)
        _append_optional_path(argv, "--trace-log", args.trace_log)
        argv.extend(["--agent-run-id", args.agent_run_id, "--action-id", args.action_id])
        if args.dry_run:
            argv.append("--dry-run")
        if args.authorized_by:
            argv.extend(["--authorized-by", args.authorized_by])
    argv.append("--json")
    return run_scout_agent_cli(argv)


def _tool_request_for_args(args: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    group = args.command_group
    if group == "evidence" and args.evidence_command == "sensorlog-to-gpx":
        request: dict[str, Any] = {
            "input_path": str(args.sensorlog_path),
            "output_path": str(args.output),
        }
        if args.track_name:
            request["track_name"] = args.track_name
        if args.max_horizontal_accuracy is not None:
            request["max_horizontal_accuracy"] = args.max_horizontal_accuracy
        return "scout.evidence.sensorlog_to_gpx", request
    if group == "kb" and args.kb_command == "build":
        return "scout.kb.build", {
            "project_root": str(args.project_root),
            "output_path": str(args.output),
        }
    if group == "kb" and args.kb_command == "query":
        request = {
            "query": args.query,
            "limit": args.limit,
            "evidence_types": args.evidence_type,
        }
        _set_path(request, "project_root", args.project_root)
        _set_path(request, "index_path", args.index_path)
        return "scout.kb.query", request
    if group == "kb" and args.kb_command == "pretrip-view-summary":
        request = {}
        _set_path(request, "project_root", args.project_root)
        _set_path(request, "view_path", args.view_path)
        return "scout.kb.pretrip_view_summary", request
    if group == "kb" and args.kb_command == "hardware-readiness-summary":
        return "scout.kb.hardware_readiness_summary", _hardware_readiness_request(args)
    if group == "hardware" and args.hardware_command == "readiness-summary":
        return "scout.kb.hardware_readiness_summary", _hardware_readiness_request(args)
    if group == "checks" and args.checks_command == "pretrip-release":
        request = {}
        _set_path(request, "repo_root", args.repo_root)
        _set_path(request, "project_json_path", args.project_json_path)
        return "scout.checks.pretrip_release", request
    if group == "checks" and args.checks_command == "runtime-readiness":
        request = {}
        _set_path(request, "repo_root", args.repo_root)
        return "scout.checks.runtime_readiness", request
    if group == "map":
        return _map_tool_request_for_args(args)
    if group == "pretrip" and args.pretrip_command == "import-gpx":
        return "scout.pretrip.import_gpx", {
            "project_id": args.project_id,
            "golden_route_gpx": str(args.golden_route_gpx),
            "workspace_root": str(args.workspace_root),
            **({"reference_dir": str(args.reference_dir)} if args.reference_dir else {}),
        }
    if group == "pretrip" and args.pretrip_command == "route-context-collect":
        request = {
            "include_route_notes": not args.no_route_notes,
            "limit_route_notes": args.limit_route_notes,
        }
        _set_path(request, "project_root", args.project_root)
        _set_path(request, "workspace_root", args.workspace_root)
        if args.project_id:
            request["project_id"] = args.project_id
        if args.collected_at:
            request["collected_at"] = args.collected_at
        return "scout.pretrip.route_context_collect", request
    if group == "pretrip" and args.pretrip_command == "route-architecture-collect":
        request = {"limit": args.limit}
        _set_path(request, "project_root", args.project_root)
        _set_path(request, "workspace_root", args.workspace_root)
        if args.project_id:
            request["project_id"] = args.project_id
        if args.current_cp_id:
            request["current_cp_id"] = args.current_cp_id
        if args.current_time:
            request["current_time"] = args.current_time
        if args.target_cp_id:
            request["target_cp_id"] = args.target_cp_id
        if args.generated_at:
            request["generated_at"] = args.generated_at
        return "scout.pretrip.route_architecture_collect", request
    if group == "pretrip" and args.pretrip_command == "weather-decision-collect":
        request = {"provider": args.provider}
        _set_path(request, "project_root", args.project_root)
        _set_path(request, "workspace_root", args.workspace_root)
        if args.project_id:
            request["project_id"] = args.project_id
        if args.weather_points_path:
            request["weather_points_path"] = args.weather_points_path
        if args.warnings_path:
            request["warnings_path"] = args.warnings_path
        if args.route_segments_path:
            request["route_segments_path"] = args.route_segments_path
        if args.default_township:
            request["default_township"] = args.default_township
        if args.generated_at:
            request["generated_at"] = args.generated_at
        if args.valid_until:
            request["valid_until"] = args.valid_until
        return "scout.pretrip.weather_decision_collect", request
    if group == "pretrip" and args.pretrip_command == "contextual-permission-collect":
        request = {}
        _set_path(request, "project_root", args.project_root)
        _set_path(request, "workspace_root", args.workspace_root)
        if args.project_id:
            request["project_id"] = args.project_id
        for key in (
            "current_time",
            "current_cp_id",
            "next_cp_id",
            "communication_status",
            "equipment_status",
            "remaining_safety_buffer_minutes",
            "requested_duration_minutes",
            "current_delay_minutes",
            "next_segment_uncertainty_minutes",
            "weather_reserve_minutes",
            "daylight_reserve_minutes",
            "retreat_reserve_minutes",
            "slowest_member_reserve_minutes",
            "generated_at",
        ):
            value = getattr(args, key)
            if value is not None:
                request[key] = value
        return "scout.pretrip.contextual_permission_collect", request
    if group == "pretrip" and args.pretrip_command == "prepare-layers":
        request = {"profile": args.profile}
        _set_path(request, "project_root", args.project_root)
        _set_path(request, "workspace_root", args.workspace_root)
        if args.project_id:
            request["project_id"] = args.project_id
        if args.layers:
            request["layers"] = args.layers
        return "scout.pretrip.prepare_layers", request
    if group == "pretrip" and args.pretrip_command == "artifact-manifest":
        request = {}
        _set_path(request, "project_root", args.project_root)
        _set_path(request, "project_json_path", args.project_json_path)
        return "scout.pretrip.artifact_manifest", request
    if group == "pretrip" and args.pretrip_command == "readiness":
        request = {}
        _set_path(request, "route_plan_path", args.route_plan)
        _set_path(request, "skill_config_manifest_path", args.skill_config_manifest_path)
        return "scout.pretrip.readiness", request
    if group == "pretrip" and args.pretrip_command == "decision-register":
        request = {}
        _set_path(request, "register_path", args.register_path)
        return "scout.pretrip.decision_register", request
    if group == "pretrip" and args.pretrip_command == "workspace-edit":
        return "scout.pretrip.workspace_edit", _load_json(args.input)
    if group == "pretrip" and args.pretrip_command == "review":
        return "scout.pretrip.review_append_decisions", _review_append_decisions_request(args)
    if group == "pretrip" and args.pretrip_command == "departure-reviewed-candidates":
        return "scout.pretrip.departure_reviewed_candidates", {
            "project_root": str(args.project_root)
        }
    if group == "pretrip" and args.pretrip_command == "runtime-export":
        return "scout.pretrip.runtime_export", {
            "workspace_root": str(args.workspace_root),
            "final_mission_graph_path": str(args.final_mission_graph_path),
            "runtime_handoff_path": str(args.runtime_handoff_path),
            "export_id": args.export_id,
        }
    if group == "pretrip" and args.pretrip_command == "runtime-handoff":
        return "scout.pretrip.runtime_handoff", {
            "workspace_root": str(args.workspace_root),
            "departure_gate_path": str(args.departure_gate_path),
            "final_mission_graph_path": str(args.final_mission_graph_path),
            "handoff_id": args.handoff_id,
            "approved_by": args.approved_by,
            "approved_at": args.approved_at,
            "handoff_target": _load_json(args.handoff_target),
            "rollback_reference": _load_json(args.rollback_reference),
            "output_ref": args.output_ref,
        }
    if group == "cp" and args.cp_command == "apply-reviewed-delta":
        request = {"project_root": str(args.project_root)}
        _set_path(request, "apply_plan_path", args.apply_plan_path)
        if args.output_ref:
            request["output_ref"] = args.output_ref
        return "scout.cp.apply_reviewed_delta", request
    if group == "cp":
        tool_id = {
            "propose-add": "scout.cp.propose_add",
            "propose-delete": "scout.cp.propose_delete",
            "proposal-preview": "scout.cp.proposal_preview",
        }[args.cp_command]
        request = _load_json(args.input) if args.input else {}
        if args.candidate_ref:
            request["candidate_ref"] = args.candidate_ref
        if args.label:
            request["label"] = args.label
        if args.reason:
            request["reason"] = args.reason
        return tool_id, request
    if group == "risk":
        tool_id = {
            "attribution": "scout.risk.attribution",
            "heatmap": "scout.risk.heatmap",
        }[args.risk_command]
        request = _load_json(args.input) if args.input else {}
        _set_path(request, "route_risk_path", args.route_risk_path)
        _set_path(request, "diagnostic_path", args.diagnostic_path)
        _set_path(request, "workspace", args.workspace)
        return tool_id, request
    if group == "debug" and args.debug_command == "trace-tail":
        return "scout.debug.trace_tail", {
            "trace_path": str(args.trace_path),
            "trace_kind": args.trace_kind,
            "limit": args.limit,
        }
    if group == "note" and args.note_command == "append-flight-recorder":
        return "scout.note.append_flight_recorder", {
            "debug_log_path": str(args.debug_log_path),
            "text": args.text,
            "note_kind": args.note_kind,
            "source": args.source,
        }
    if group == "voice" and args.voice_command == "preview":
        return "scout.voice.preview", {
            "text_zh": args.text_zh,
            "audio_file": args.audio_file,
            "engine": args.engine,
        }
    if group == "voice" and args.voice_command == "mock-queue":
        request = {
            "voice_log_path": str(args.voice_log_path),
            "cue_id": args.cue_id,
            "text_zh": args.text_zh,
            "priority": args.priority,
            "category": args.category,
            "engine": args.engine,
            "render_mock": args.render_mock,
        }
        _set_path(request, "debug_log_path", args.debug_log_path)
        return "scout.voice.mock_queue", request
    if group == "voice" and args.voice_command == "mock-transition":
        request = {
            "voice_log_path": str(args.voice_log_path),
            "cue_id": args.cue_id,
            "state": args.state,
        }
        if args.reason:
            request["reason"] = args.reason
        _set_path(request, "debug_log_path", args.debug_log_path)
        return "scout.voice.mock_transition", request
    if group == "outbound" and args.outbound_command == "mock-queue":
        request = {
            "outbound_log_path": str(args.outbound_log_path),
            "category": args.category,
            "recipient_ref": args.recipient_ref,
            "body_preview": args.body_preview,
        }
        if args.subject_ref:
            request["subject_ref"] = args.subject_ref
        _set_path(request, "debug_log_path", args.debug_log_path)
        return "scout.outbound.mock_queue", request
    if group == "outbound" and args.outbound_command == "mock-transition":
        request = {
            "outbound_log_path": str(args.outbound_log_path),
            "message_id": args.message_id,
            "state": args.state,
        }
        if args.reason:
            request["reason"] = args.reason
        _set_path(request, "debug_log_path", args.debug_log_path)
        return "scout.outbound.mock_transition", request
    if group == "imprint":
        return _imprint_tool_request_for_args(args)
    if group == "safety-action" and args.safety_action_command == "shelter-direction":
        return "scout.safety_action.shelter_direction", {
            "project_root": str(args.project_root),
            "position": _position_payload(args),
            "query": args.query,
            "limit": args.limit,
            "ttl_seconds": args.ttl_seconds,
        }
    if group == "sos" and args.sos_command == "playbook-run":
        request = {
            "sos_event_path": str(args.sos_event),
            "recipient_refs": args.recipient_ref,
            "mock_deliver": args.mock_deliver,
            "render_voice_mock": args.render_voice_mock,
        }
        _set_path(request, "debug_log_path", args.debug_log_path)
        _set_path(request, "voice_log_path", args.voice_log_path)
        return "scout.sos.playbook_run", request
    if group == "runtime" and args.runtime_command == "activation-preflight":
        return "scout.runtime.activation_preflight", {"export_root": str(args.export_root)}
    if group == "runtime" and args.runtime_command == "load-dry-run":
        return "scout.runtime.load_dry_run", {"export_root": str(args.export_root)}
    raise ValueError("unsupported scout command")


def _imprint_tool_request_for_args(args: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    if args.imprint_command == "list":
        return "scout.imprint.store_list", {
            "store_path": str(args.store_path),
            "trip_id": args.trip_id,
            "include_inactive": args.include_inactive,
        }
    if args.imprint_command == "trigger-dry-run":
        return "scout.imprint.trigger_dry_run", {
            "imprint_set_path": str(args.imprint_set),
            "context_path": str(args.context),
            "previous_trigger_keys": args.previous_trigger_key,
        }
    if args.imprint_command == "export-pretrip":
        return "scout.imprint.export_pretrip", {"project_root": str(args.project_root)}
    if args.imprint_command == "plant":
        return "scout.imprint.plant", _load_json(args.input)
    if args.imprint_command == "expire":
        return "scout.imprint.expire", _load_json(args.input)
    if args.imprint_command == "delete":
        return "scout.imprint.delete", _load_json(args.input)
    raise ValueError("unsupported imprint command")


def _map_tool_request_for_args(args: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    if args.map_command == "raster-source":
        request: dict[str, Any] = {"source_geotiff": str(args.source_geotiff)}
        if args.project_id:
            request["project_id"] = args.project_id
        if args.layer_id:
            request["layer_id"] = args.layer_id
        _set_path(request, "recommended_cache_root", args.recommended_cache_root)
        return "scout.map.raster_source", request
    if args.map_command == "raster-tiles":
        request = {"source_manifest_path": str(args.source_manifest_path)}
        _set_path(request, "cache_root", args.cache_root)
        if args.min_zoom is not None:
            request["min_zoom"] = args.min_zoom
        if args.max_zoom is not None:
            request["max_zoom"] = args.max_zoom
        if args.capacity_gib is not None:
            request["capacity_gib"] = args.capacity_gib
        if args.max_tiles is not None:
            request["max_tiles"] = args.max_tiles
        return "scout.map.raster_tiles", request
    if args.map_command == "tile-cache-plan":
        request = {}
        _set_path(request, "project_root", args.project_root)
        _set_path(request, "cache_root", args.cache_root)
        if args.bbox_wgs84:
            request["bbox_wgs84"] = json.loads(args.bbox_wgs84)
        if args.min_zoom is not None:
            request["min_zoom"] = args.min_zoom
        if args.max_zoom is not None:
            request["max_zoom"] = args.max_zoom
        if args.bbox_expansion_ratio is not None:
            request["bbox_expansion_ratio"] = args.bbox_expansion_ratio
        if args.capacity_gib is not None:
            request["capacity_gib"] = args.capacity_gib
        if args.tile_url_template:
            request["tile_url_template"] = args.tile_url_template
        if args.plan_id:
            request["plan_id"] = args.plan_id
        return "scout.map.tile_cache_plan", request
    raise ValueError("unsupported map command")


def _run_registered_tool(
    tool_id: str,
    *,
    request: dict[str, Any],
    manifest_dir: Path,
    trace_log: Path | None,
    output: Path | None,
    dry_run: bool,
    authorized_by: str | None,
    agent_run_id: str,
    action_id: str,
) -> tuple[int, dict[str, Any]]:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
        json.dump(request, handle, ensure_ascii=False)
        input_path = Path(handle.name)
    try:
        argv = [
            "tools",
            "run",
            tool_id,
            "--manifest-dir",
            str(manifest_dir),
            "--input",
            str(input_path),
            "--agent-run-id",
            agent_run_id,
            "--action-id",
            action_id,
        ]
        _append_optional_path(argv, "--trace-log", trace_log)
        _append_optional_path(argv, "--output", output)
        if dry_run:
            argv.append("--dry-run")
        if authorized_by:
            argv.extend(["--authorized-by", authorized_by])
        argv.append("--json")
        return run_scout_agent_cli(argv)
    finally:
        input_path.unlink(missing_ok=True)


def _position_payload(args: argparse.Namespace) -> dict[str, Any]:
    if args.position:
        return _load_json(args.position)
    if args.lat is None or args.lon is None:
        raise ValueError("shelter-direction requires --position or both --lat and --lon")
    return {"lat": args.lat, "lon": args.lon, "source": "scout_cli"}


def _hardware_readiness_request(args: argparse.Namespace) -> dict[str, Any]:
    request: dict[str, Any] = {}
    _set_path(request, "fixture_path", args.fixture_path)
    if args.selected_provider_ref:
        request["selected_provider_ref"] = args.selected_provider_ref
    return request


def _review_append_decisions_request(args: argparse.Namespace) -> dict[str, Any]:
    request = _load_json(args.input) if args.input else {}
    _set_path(request, "project_root", args.project_root)
    _set_path(request, "log_path", args.log_path)
    if args.pretrip_review_command == "append-decision" and args.record:
        request["record"] = _load_json(args.record)
    if args.pretrip_review_command == "append-decisions" and args.records:
        payload = _load_json_value(args.records)
        request["records"] = payload["records"] if isinstance(payload, dict) and "records" in payload else payload
    if "record" not in request and "records" not in request:
        raise ValueError("pretrip review append requires --record, --records, or --input with record(s)")
    return request


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON file must contain an object: {path}")
    return payload


def _load_json_value(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _set_path(payload: dict[str, Any], key: str, value: Path | None) -> None:
    if value is not None:
        payload[key] = str(value)


def _append_optional_path(argv: list[str], flag: str, value: Path | None) -> None:
    if value is not None:
        argv.extend([flag, str(value)])


def main(argv: Sequence[str] | None = None) -> int:
    exit_code, payload = run_scout_cli(argv)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
