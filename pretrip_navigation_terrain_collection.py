from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


NAVIGATION_TERRAIN_COLLECTION_ARTIFACT_KIND = "pretrip_navigation_terrain_collection"
OFFLINE_MAP_MANIFEST_ARTIFACT_KIND = "pretrip_offline_map_manifest"
INS_DR_READINESS_ARTIFACT_KIND = "pretrip_ins_dr_readiness"
NAVIGATION_TERRAIN_SCHEMA_VERSION = "navigation_terrain_collection.v1"

OFFLINE_MAP_MANIFEST_REF = "normalized/navigation/offline_map_manifest.json"
INS_DR_READINESS_REF = "normalized/navigation/ins_dr_readiness.json"


SEC11_ALIGNMENT = {
    "standard": "SCOUT_OUTDOOR_AI_AGENT_STANDARD",
    "sections": [
        "Sec. 11 Navigation & Terrain Intelligence",
        "Sec. 18.1 required inputs",
        "Sec. 18.2 required outputs",
        "Sec. 23 acceptance criteria",
    ],
    "workspace_layout_refs": [
        "normalized/terrain/*",
        "outputs/layers/normalized/terrain_*.png",
        "outputs/layers/normalized/terrain_contours.geojson",
        "outputs/risk/*",
        OFFLINE_MAP_MANIFEST_REF,
        INS_DR_READINESS_REF,
    ],
}


def collect_pretrip_navigation_terrain(
    project_root: Path | str,
    *,
    dry_run: bool = False,
    offline_map_downloaded: bool | str | None = None,
    gpx_loaded_on_device: bool | str | None = None,
    contour_skill_confirmed: bool | str | None = None,
    terrain_feature_skill_confirmed: bool | str | None = None,
    retreat_direction_understood: bool | str | None = None,
    backup_positioning_available: bool | str | None = None,
    team_map_user_count: int | str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Collect Sec. 11 map, terrain, and positioning readiness evidence.

    This collector turns existing pretrip map/terrain/risk artifacts plus
    operator-provided readiness answers into candidate-only planning evidence.
    It does not read live sensors, control hardware, or authorize runtime
    navigation.
    """

    root = Path(project_root)
    project_path = root / "project.json"
    project = _load_json_object(project_path)
    project_id = str(project.get("project_id") or project.get("id") or root.name)
    collected_at = generated_at or _utc_now()
    offline_ref = str(project.get("offline_map_manifest_ref") or OFFLINE_MAP_MANIFEST_REF)
    ins_dr_ref = str(project.get("ins_dr_readiness_ref") or INS_DR_READINESS_REF)
    planned_refs = [offline_ref, ins_dr_ref]
    boundary = _closed_boundary(workspace_file_mutation_allowed=not dry_run)

    source_report = _source_report(root, project)
    workspace = _workspace_readiness(source_report)
    capability = {
        "offline_map_downloaded": _bool_or_none(offline_map_downloaded),
        "gpx_loaded_on_device": _bool_or_none(gpx_loaded_on_device),
        "contour_skill_confirmed": _bool_or_none(contour_skill_confirmed),
        "terrain_feature_skill_confirmed": _bool_or_none(terrain_feature_skill_confirmed),
        "retreat_direction_understood": _bool_or_none(retreat_direction_understood),
        "backup_positioning_available": _bool_or_none(backup_positioning_available),
        "team_map_user_count": _int_or_none(team_map_user_count),
    }
    demand = _navigation_demand(workspace)
    missing_fields = [
        key for key, value in capability.items() if key != "team_map_user_count" and value is None
    ]
    required_actions = _required_actions(capability, workspace=workspace)
    decision = _decision(
        demand=demand,
        capability=capability,
        missing_fields=missing_fields,
        workspace=workspace,
    )
    answerability = (
        "navigation_terrain_missing_user_readiness"
        if missing_fields
        else "navigation_terrain_decision_available"
    )

    offline_payload = {
        "artifact_kind": OFFLINE_MAP_MANIFEST_ARTIFACT_KIND,
        "schema_version": NAVIGATION_TERRAIN_SCHEMA_VERSION,
        "project_id": project_id,
        "generated_at": collected_at,
        "decision": decision,
        "answerability": answerability,
        "navigation_demand": demand,
        "map_readiness": {
            "offline_map_downloaded": capability["offline_map_downloaded"],
            "gpx_loaded_on_device": capability["gpx_loaded_on_device"],
            "map_context_available": workspace["map_context_available"],
            "reference_track_available": workspace["reference_track_available"],
            "retreat_routes_available": workspace["retreat_routes_available"],
            "risk_layers_available": workspace["risk_layers_available"],
            "terrain_layers_available": workspace["terrain_layers_available"],
            "offline_tile_manifest_available": workspace["offline_tile_manifest_available"],
            "wmts_runtime_imagery_only": workspace["wmts_runtime_imagery_only"],
        },
        "terrain_readiness": {
            "dtm_coverage_available": workspace["dtm_coverage_available"],
            "segment_dtm_coverage_available": workspace["segment_dtm_coverage_available"],
            "risk_ribbon_available": workspace["risk_ribbon_available"],
            "map_feature_count": workspace["map_feature_count"],
            "segment_count": workspace["segment_count"],
            "checkpoint_count": workspace["checkpoint_count"],
            "risk_ribbon_segment_count": workspace["risk_ribbon_segment_count"],
            "dtm_candidate_tile_count": workspace["dtm_candidate_tile_count"],
        },
        "missing_fields": missing_fields,
        "required_actions": required_actions,
        "source_report": source_report,
        "human_review_required": True,
        "standard_alignment": SEC11_ALIGNMENT,
        "boundary": boundary,
    }
    ins_dr_payload = {
        "artifact_kind": INS_DR_READINESS_ARTIFACT_KIND,
        "schema_version": NAVIGATION_TERRAIN_SCHEMA_VERSION,
        "project_id": project_id,
        "generated_at": collected_at,
        "decision": decision,
        "answerability": answerability,
        "positioning_readiness": {
            "backup_positioning_available": capability["backup_positioning_available"],
            "team_map_user_count": capability["team_map_user_count"],
            "retreat_direction_understood": capability["retreat_direction_understood"],
            "gnss_live_probe_required_before_runtime": True,
            "imu_pdr_live_probe_required_before_runtime": True,
            "live_sensor_probe_performed": False,
            "hardware_control_performed": False,
        },
        "map_skill_readiness": {
            "contour_skill_confirmed": capability["contour_skill_confirmed"],
            "terrain_feature_skill_confirmed": capability[
                "terrain_feature_skill_confirmed"
            ],
            "high_demand_requires_guided_or_training": demand["demand_level"] == "high",
        },
        "missing_fields": missing_fields,
        "required_actions": required_actions,
        "source_report": source_report,
        "human_review_required": True,
        "standard_alignment": SEC11_ALIGNMENT,
        "boundary": boundary,
    }
    collection_payload = {
        "artifact_kind": NAVIGATION_TERRAIN_COLLECTION_ARTIFACT_KIND,
        "schema_version": NAVIGATION_TERRAIN_SCHEMA_VERSION,
        "status": "completed",
        "dry_run": dry_run,
        "project_id": project_id,
        "writes_performed": False,
        "planned_refs": planned_refs,
        "outputs": {
            "offline_map_manifest_ref": offline_ref,
            "ins_dr_readiness_ref": ins_dr_ref,
        },
        "decision": decision,
        "answerability": answerability,
        "navigation_demand_level": demand["demand_level"],
        "missing_fields": missing_fields,
        "required_action_count": len(required_actions),
        "source_report": source_report,
        "standard_alignment": SEC11_ALIGNMENT,
        "boundary": boundary,
    }

    if not dry_run:
        _write_json(root / offline_ref, offline_payload)
        _write_json(root / ins_dr_ref, ins_dr_payload)
        _update_project_refs(
            project_path,
            project,
            {
                "offline_map_manifest_ref": offline_ref,
                "ins_dr_readiness_ref": ins_dr_ref,
                "navigation_terrain_decision": decision,
                "navigation_terrain_required_action_count": len(required_actions),
                "navigation_terrain_collection_updated_at": collected_at,
                "navigation_terrain_collection_schema_version": (
                    NAVIGATION_TERRAIN_SCHEMA_VERSION
                ),
            },
        )
        collection_payload["writes_performed"] = True
        collection_payload["written_refs"] = planned_refs

    return collection_payload


def _source_report(root: Path, project: dict[str, Any]) -> list[dict[str, Any]]:
    sources = [
        ("route_summary", project.get("route_summary_ref") or "normalized/routes/route_summary.json"),
        ("checkpoint_candidates", project.get("checkpoint_candidates_ref") or "candidates/checkpoints.json"),
        ("segment_candidates", project.get("segment_candidates_ref") or "candidates/segments.json"),
        ("reference_tracks", project.get("reference_tracks_ref") or "outputs/reference_tracks.json"),
        ("map_context", project.get("map_context_ref") or "normalized/map/map_context.geojson"),
        ("dtm_coverage_summary", project.get("dtm_coverage_summary_ref") or "normalized/terrain/dtm_coverage_summary.json"),
        ("segment_dtm_coverage", project.get("segment_dtm_coverage_ref") or "normalized/terrain/segment_dtm_coverage.json"),
        ("retreat_routes", project.get("retreat_routes_ref") or "candidates/retreat_routes.json"),
        ("risk_ribbon", project.get("risk_ribbon_ref") or "outputs/risk_ribbon.geojson"),
        ("risk_ribbon_metadata", project.get("risk_ribbon_metadata_ref") or "outputs/risk_ribbon.metadata.json"),
        ("calibrated_risk_heatmap", project.get("calibrated_risk_heatmap_ref")),
        ("imagery_manifest", project.get("imagery_manifest_ref")),
        ("raster_tile_manifest", project.get("raster_tile_manifest_ref")),
    ]
    report = []
    for source_kind, ref in sources:
        if not ref:
            report.append(
                {
                    "source_kind": source_kind,
                    "status": "missing_ref",
                    "source_path": None,
                    "loaded_count": 0,
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                }
            )
            continue
        path = Path(str(ref)) if Path(str(ref)).is_absolute() else root / str(ref)
        if not path.exists():
            report.append(
                {
                    "source_kind": source_kind,
                    "status": "missing",
                    "source_path": str(ref),
                    "loaded_count": 0,
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                }
            )
            continue
        payload = _load_json_or_text(path)
        report.append(
            {
                "source_kind": source_kind,
                "status": "loaded",
                "source_path": str(ref),
                "artifact_kind": _artifact_kind(payload),
                "loaded_count": _loaded_count(payload),
                "sha256_present": path.is_file(),
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )
    return report


def _workspace_readiness(source_report: list[dict[str, Any]]) -> dict[str, Any]:
    by_kind = {item["source_kind"]: item for item in source_report}
    return {
        "map_context_available": _loaded(by_kind, "map_context"),
        "reference_track_available": _loaded(by_kind, "reference_tracks"),
        "retreat_routes_available": _loaded(by_kind, "retreat_routes"),
        "dtm_coverage_available": _loaded(by_kind, "dtm_coverage_summary"),
        "segment_dtm_coverage_available": _loaded(by_kind, "segment_dtm_coverage"),
        "risk_ribbon_available": _loaded(by_kind, "risk_ribbon"),
        "risk_layers_available": _loaded(by_kind, "risk_ribbon")
        or _loaded(by_kind, "calibrated_risk_heatmap"),
        "terrain_layers_available": _loaded(by_kind, "dtm_coverage_summary")
        and _loaded(by_kind, "segment_dtm_coverage"),
        "offline_tile_manifest_available": _loaded(by_kind, "raster_tile_manifest"),
        "wmts_runtime_imagery_only": not _loaded(by_kind, "raster_tile_manifest")
        and not _loaded(by_kind, "imagery_manifest"),
        "map_feature_count": _count(by_kind, "map_context"),
        "segment_count": _count(by_kind, "segment_candidates"),
        "checkpoint_count": _count(by_kind, "checkpoint_candidates"),
        "risk_ribbon_segment_count": _count(by_kind, "risk_ribbon"),
        "dtm_candidate_tile_count": _count(by_kind, "dtm_coverage_summary"),
    }


def _navigation_demand(workspace: dict[str, Any]) -> dict[str, Any]:
    score = 0
    reasons = []
    if int(workspace["segment_count"] or 0) >= 50:
        score += 2
        reasons.append("many_route_segments")
    if int(workspace["checkpoint_count"] or 0) >= 50:
        score += 1
        reasons.append("many_checkpoints")
    if int(workspace["risk_ribbon_segment_count"] or 0) > 0:
        score += 2
        reasons.append("risk_ribbon_available")
    if int(workspace["dtm_candidate_tile_count"] or 0) > 0:
        score += 1
        reasons.append("terrain_dtm_required")
    if workspace["retreat_routes_available"]:
        score += 1
        reasons.append("retreat_route_reasoning_required")
    demand_level = "high" if score >= 4 else "medium" if score >= 2 else "low"
    return {"demand_level": demand_level, "score": score, "reasons": reasons}


def _required_actions(
    capability: dict[str, Any],
    *,
    workspace: dict[str, Any],
) -> list[str]:
    actions = []
    if capability["offline_map_downloaded"] is not True:
        actions.append("Confirm every navigation device has offline map tiles downloaded.")
    if capability["gpx_loaded_on_device"] is not True:
        actions.append("Load GPX/reference track on every navigation device.")
    if capability["contour_skill_confirmed"] is not True:
        actions.append("Confirm contour-reading competence or assign a guide.")
    if capability["terrain_feature_skill_confirmed"] is not True:
        actions.append("Confirm ridge/valley/saddle terrain-feature recognition.")
    if capability["retreat_direction_understood"] is not True:
        actions.append("Review retreat direction and nearest retreat candidates.")
    if capability["backup_positioning_available"] is not True:
        actions.append("Prepare backup positioning before relying on GNSS/phone navigation.")
    if not workspace["risk_layers_available"]:
        actions.append("Generate or review risk heat/ribbon layers before departure.")
    if not workspace["terrain_layers_available"]:
        actions.append("Generate or review DTM/terrain coverage before departure.")
    return actions


def _decision(
    *,
    demand: dict[str, Any],
    capability: dict[str, Any],
    missing_fields: list[str],
    workspace: dict[str, Any],
) -> str:
    if not workspace["map_context_available"] or not workspace["reference_track_available"]:
        return "CHANGE_PLAN"
    if demand["demand_level"] == "high" and any(
        capability[key] is False
        for key in (
            "offline_map_downloaded",
            "gpx_loaded_on_device",
            "contour_skill_confirmed",
            "terrain_feature_skill_confirmed",
            "retreat_direction_understood",
            "backup_positioning_available",
        )
    ):
        return "GUIDED_ONLY"
    if missing_fields:
        return "CONDITIONAL_GO"
    if not workspace["risk_layers_available"] or not workspace["terrain_layers_available"]:
        return "CHANGE_PLAN"
    return "GO"


def _loaded(by_kind: dict[str, dict[str, Any]], source_kind: str) -> bool:
    return by_kind.get(source_kind, {}).get("status") == "loaded"


def _count(by_kind: dict[str, dict[str, Any]], source_kind: str) -> int:
    return int(by_kind.get(source_kind, {}).get("loaded_count") or 0)


def _load_json_or_text(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return path.read_text(encoding="utf-8", errors="ignore")


def _loaded_count(payload: Any) -> int:
    if isinstance(payload, dict):
        for key in ("features", "candidates", "segments", "checkpoints", "items", "tracks"):
            value = payload.get(key)
            if isinstance(value, list):
                return len(value)
        for key in ("segment_count", "point_count", "candidate_tile_count", "scanned_header_count"):
            value = _int_or_none(payload.get(key))
            if value is not None:
                return value
        return 1
    if isinstance(payload, list):
        return len(payload)
    return 1 if payload else 0


def _artifact_kind(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    return str(payload.get("artifact_kind") or payload.get("type") or "") or None


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _update_project_refs(
    project_path: Path,
    project: dict[str, Any],
    updates: dict[str, Any],
) -> None:
    if not project_path.exists():
        return
    _write_json(project_path, {**project, **updates})


def _closed_boundary(*, workspace_file_mutation_allowed: bool) -> dict[str, Any]:
    return {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "phase1_runtime_mutation_allowed": False,
        "phase2_brain_writeback_allowed": False,
        "live_safety_api_calls_allowed": False,
        "safety_api_called": False,
        "external_api_calls_made": False,
        "outbound_send_allowed": False,
        "hardware_control_allowed": False,
        "live_sensor_read_allowed": False,
        "live_sensor_probe_performed": False,
        "workspace_file_mutation_allowed": workspace_file_mutation_allowed,
        "raw_payloads_embedded": False,
    }


def _bool_or_none(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return None
    lowered = str(value).strip().lower()
    if lowered in {"true", "1", "yes", "y"}:
        return True
    if lowered in {"false", "0", "no", "n"}:
        return False
    return None


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect Scout navigation terrain readiness.")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--offline-map-downloaded", default=None)
    parser.add_argument("--gpx-loaded-on-device", default=None)
    parser.add_argument("--contour-skill-confirmed", default=None)
    parser.add_argument("--terrain-feature-skill-confirmed", default=None)
    parser.add_argument("--retreat-direction-understood", default=None)
    parser.add_argument("--backup-positioning-available", default=None)
    parser.add_argument("--team-map-user-count", default=None)
    parser.add_argument("--generated-at", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    payload = collect_pretrip_navigation_terrain(
        args.project_root,
        dry_run=args.dry_run,
        offline_map_downloaded=args.offline_map_downloaded,
        gpx_loaded_on_device=args.gpx_loaded_on_device,
        contour_skill_confirmed=args.contour_skill_confirmed,
        terrain_feature_skill_confirmed=args.terrain_feature_skill_confirmed,
        retreat_direction_understood=args.retreat_direction_understood,
        backup_positioning_available=args.backup_positioning_available,
        team_map_user_count=args.team_map_user_count,
        generated_at=args.generated_at,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
