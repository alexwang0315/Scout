from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scout_route_architecture_tool import assess_scout_route_architecture


ROUTE_ARCHITECTURE_COLLECTION_ARTIFACT_KIND = "pretrip_route_architecture_collection"
ROUTE_ARCHITECTURE_ARTIFACT_KIND = "pretrip_route_architecture"
ROUTE_ARCHITECTURE_SCHEMA_VERSION = "route_architecture_collection.v1"
ROUTE_ARCHITECTURE_REF = "normalized/architecture/route_architecture.json"


SEC9_ALIGNMENT = {
    "standard": "SCOUT_OUTDOOR_AI_AGENT_STANDARD",
    "sections": [
        "Sec. 9 Route Architecture Intelligence",
        "Sec. 12 Checkpoint Graph",
        "Sec. 18.2 required pretrip outputs",
        "Sec. 19 on-route recalculation",
        "Sec. 23 acceptance criteria",
    ],
    "workspace_layout_refs": [
        ROUTE_ARCHITECTURE_REF,
        "candidates/retreat_routes.json",
        "candidates/segments.json",
        "outputs/segment_policy_candidates.json",
        "outputs/compiled_mission_graph.*.json",
    ],
}


def collect_pretrip_route_architecture(
    project_root: Path | str,
    *,
    dry_run: bool = False,
    current_cp_id: str | None = None,
    current_time: str | None = None,
    target_cp_id: str | None = None,
    limit: int = 12,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Collect Sec. 9 Route Architecture Intelligence into the workspace.

    This materializes the deterministic CP Graph / retreat / hard-point analysis
    as candidate-only pretrip evidence. It does not mutate MissionGraph, runtime
    state, /safety/*, outbound transports, or hardware.
    """

    root = Path(project_root)
    project_path = root / "project.json"
    project = _load_json_object(project_path)
    project_id = str(project.get("project_id") or project.get("id") or root.name)
    collected_at = generated_at or _utc_now()
    architecture_ref = str(project.get("route_architecture_ref") or ROUTE_ARCHITECTURE_REF)

    assessment = assess_scout_route_architecture(
        root,
        query="這條路線的難點、撤退點、折返時間與替代方案是什麼?",
        current_cp_id=current_cp_id,
        current_time=current_time,
        target_cp_id=target_cp_id,
        limit=limit,
    )
    architecture = (
        assessment.get("route_architecture")
        if isinstance(assessment.get("route_architecture"), dict)
        else {}
    )
    decision = (
        assessment.get("route_decision")
        if isinstance(assessment.get("route_decision"), dict)
        else {}
    )
    cp_graph = (
        assessment.get("cp_graph")
        if isinstance(assessment.get("cp_graph"), dict)
        else {}
    )
    counts = _counts(architecture=architecture, cp_graph=cp_graph, assessment=assessment)
    boundary = _closed_boundary(workspace_file_mutation_allowed=not dry_run)
    artifact_payload = {
        "artifact_kind": ROUTE_ARCHITECTURE_ARTIFACT_KIND,
        "schema_version": ROUTE_ARCHITECTURE_SCHEMA_VERSION,
        "project_id": project_id,
        "generated_at": collected_at,
        "answerability": assessment.get("answerability"),
        "decision": assessment.get("decision"),
        "field_answer": assessment.get("field_answer"),
        "route_architecture": architecture,
        "route_decision": decision,
        "cp_graph": _compact_cp_graph(cp_graph),
        "counts": counts,
        "source_report": list(assessment.get("source_report") or []),
        "human_review_required": True,
        "route_structure_checks": {
            "route_type_checked": True,
            "hard_point_position_checked": bool(architecture.get("hard_points")),
            "retreat_points_checked": True,
            "supply_points_checked": "water_available" in _hard_point_fields(architecture),
            "time_pressure_checked": bool(architecture.get("turn_back")),
            "terrain_change_checked": True,
            "forgiveness_checked": True,
            "alternative_plan_checked": bool(architecture.get("alternative_plan_options")),
        },
        "standard_alignment": SEC9_ALIGNMENT,
        "boundary": boundary,
    }
    collection_payload = {
        "artifact_kind": ROUTE_ARCHITECTURE_COLLECTION_ARTIFACT_KIND,
        "schema_version": ROUTE_ARCHITECTURE_SCHEMA_VERSION,
        "status": "completed",
        "dry_run": dry_run,
        "project_id": project_id,
        "writes_performed": False,
        "planned_refs": [architecture_ref],
        "outputs": {"route_architecture_ref": architecture_ref},
        "decision": assessment.get("decision"),
        "answerability": assessment.get("answerability"),
        "hard_point_count": counts["hard_point_count"],
        "retreat_option_count": counts["retreat_option_count"],
        "missing_fields": list(assessment.get("missing_fields") or []),
        "source_report": list(assessment.get("source_report") or []),
        "standard_alignment": SEC9_ALIGNMENT,
        "boundary": boundary,
    }

    if not dry_run:
        _write_json(root / architecture_ref, artifact_payload)
        _update_project_refs(
            project_path,
            project,
            {
                "route_architecture_ref": architecture_ref,
                "route_architecture_decision": assessment.get("decision"),
                "route_architecture_hard_point_count": counts["hard_point_count"],
                "route_architecture_retreat_option_count": counts[
                    "retreat_option_count"
                ],
                "route_architecture_collection_updated_at": collected_at,
                "route_architecture_collection_schema_version": (
                    ROUTE_ARCHITECTURE_SCHEMA_VERSION
                ),
            },
        )
        collection_payload["writes_performed"] = True
        collection_payload["written_refs"] = [architecture_ref]

    return collection_payload


def _counts(
    *,
    architecture: dict[str, Any],
    cp_graph: dict[str, Any],
    assessment: dict[str, Any],
) -> dict[str, Any]:
    hard_points = architecture.get("hard_points")
    retreat_options = architecture.get("retreat_options")
    alternatives = architecture.get("alternative_plan_options")
    return {
        "checkpoint_count": int(cp_graph.get("node_count") or 0),
        "segment_count": int(cp_graph.get("edge_count") or 0),
        "sampled_node_count": len(cp_graph.get("nodes") or []),
        "sampled_edge_count": len(cp_graph.get("edges") or []),
        "hard_point_count": len(hard_points) if isinstance(hard_points, list) else 0,
        "retreat_option_count": int(architecture.get("retreat_option_count") or 0),
        "sampled_retreat_option_count": len(retreat_options)
        if isinstance(retreat_options, list)
        else 0,
        "alternative_plan_option_count": len(alternatives)
        if isinstance(alternatives, list)
        else 0,
        "missing_field_count": len(assessment.get("missing_fields") or []),
        "source_report_count": len(assessment.get("source_report") or []),
    }


def _compact_cp_graph(cp_graph: dict[str, Any]) -> dict[str, Any]:
    source_paths = cp_graph.get("source_paths")
    source_paths = source_paths if isinstance(source_paths, dict) else {}
    return {
        "node_count": cp_graph.get("node_count"),
        "edge_count": cp_graph.get("edge_count"),
        "nodes": list(cp_graph.get("nodes") or []),
        "edges": list(cp_graph.get("edges") or []),
        "candidate_only": True,
        "runtime_safety_truth": False,
        "source_paths": source_paths,
        "raw_route_geometry_embedded": False,
    }


def _hard_point_fields(architecture: dict[str, Any]) -> set[str]:
    fields: set[str] = set()
    for point in architecture.get("hard_points") or []:
        if isinstance(point, dict):
            fields.update(point.keys())
    return fields


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


def _closed_boundary(
    *,
    workspace_file_mutation_allowed: bool,
) -> dict[str, Any]:
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
        "workspace_file_mutation_allowed": workspace_file_mutation_allowed,
        "raw_payloads_embedded": False,
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect Scout route architecture.")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--current-cp-id", default=None)
    parser.add_argument("--current-time", default=None)
    parser.add_argument("--target-cp-id", default=None)
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--generated-at", default=None)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    payload = collect_pretrip_route_architecture(
        args.project_root,
        dry_run=args.dry_run,
        current_cp_id=args.current_cp_id,
        current_time=args.current_time,
        target_cp_id=args.target_cp_id,
        limit=args.limit,
        generated_at=args.generated_at,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(
            f"{payload['status']}: decision={payload.get('decision')} "
            f"hard_points={payload.get('hard_point_count')} "
            f"writes={payload.get('writes_performed')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
