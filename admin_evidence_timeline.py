from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any

from scout_agent_tools import load_tool_manifests, summarize_tool_manifest


ROOT = Path(__file__).resolve().parent
DEFAULT_AGENT_MANIFEST_DIR = ROOT / "tools" / "scout_agent_tool_manifests"

EVIDENCE_TIMELINE_CATEGORY_ORDER = (
    "route",
    "checkpoints",
    "segments",
    "route_timing",
    "capability_timeline",
    "rest_intervals",
    "mcp",
    "gis_cp",
    "risk",
    "map_context",
    "mileage",
    "reference_tracks",
    "review",
    "runtime_handoff",
)

EVIDENCE_TIMELINE_CATEGORY_LABELS = {
    "route": "Route",
    "checkpoints": "Checkpoints",
    "segments": "Segments",
    "route_timing": "Route Timing",
    "capability_timeline": "Capability Timeline",
    "rest_intervals": "Rest Intervals",
    "mcp": "Major Critical Points",
    "gis_cp": "GIS CP Evidence",
    "risk": "Risk Evidence",
    "map_context": "Map Context",
    "mileage": "Mileage Tags",
    "reference_tracks": "Reference GPX",
    "review": "Review Evidence",
    "runtime_handoff": "Runtime Handoff",
}


def build_pretrip_evidence_timeline(view: dict[str, Any]) -> dict[str, Any]:
    capability = view.get("capability_timeline_import") or {}
    mcp = view.get("major_critical_points") or {}
    gis = view.get("gis_perception_timeline") or {}
    review_queue = view.get("review_queue") or {}
    review_workbench = view.get("review_workbench") or {}
    route_notes = view.get("route_notes") or {}
    map_candidates = view.get("map_candidates") or {}
    overpass = view.get("overpass_evidence") or {}
    environment_values = view.get("environment_values") or {}
    route = view.get("route") or {}
    mileage = view.get("mileage_tag_alignment") or {}
    reference_segment_timing = view.get("reference_segment_timing") or {}
    counts = {
        "route": 1 if route else 0,
        "checkpoints": _len(view.get("checkpoints")),
        "segments": _len(view.get("segments")),
        "route_timing": int(
            (reference_segment_timing.get("counts") or {}).get("usable_segment_count")
            or _len(reference_segment_timing.get("segments"))
        ),
        "capability_timeline": _len(capability.get("edges")),
        "rest_intervals": int(
            (capability.get("counts") or {}).get("rest_interval_count")
            or (capability.get("summary") or {}).get("rest_interval_count")
            or _len(capability.get("rest_intervals"))
        ),
        "mcp": int((mcp.get("counts") or {}).get("mcp_candidate_count") or _len(mcp.get("candidates"))),
        "gis_cp": int(
            (gis.get("counts") or {}).get("checkpoint_candidate_count")
            or _len(gis.get("checkpoint_candidates"))
        )
        + int((gis.get("counts") or {}).get("nearby_group_count") or _len(gis.get("nearby_groups"))),
        "risk": _len((view.get("risk_score") or {}).get("points"))
        + _len((view.get("risk_ribbon") or {}).get("segments"))
        + _len((view.get("risk_heatmap") or {}).get("segments"))
        + _len((view.get("risk_delta") or {}).get("segments")),
        "map_context": int((overpass.get("counts") or {}).get("candidates") or 0)
        + int((map_candidates.get("counts") or {}).get("corridor_candidates") or 0)
        + int((map_candidates.get("counts") or {}).get("hazard_candidates") or 0)
        + int((map_candidates.get("counts") or {}).get("poi_candidates") or 0)
        + int((environment_values.get("counts") or {}).get("item_count") or 0),
        "mileage": int((mileage.get("counts") or {}).get("tag_count") or 0),
        "reference_tracks": int(
            (view.get("reference_tracks") or {}).get("reference_track_count")
            or _len((view.get("reference_tracks") or {}).get("reference_tracks"))
        ),
        "review": int((review_queue.get("counts") or {}).get("item_count") or _len(review_queue.get("items")))
        + int((review_workbench.get("counts") or {}).get("category_group_count") or _len(review_workbench.get("category_groups")))
        + int((route_notes.get("counts") or {}).get("note_candidate_count") or 0),
        "runtime_handoff": 1 if view.get("runtime_handoff") or view.get("departure_bundle") else 0,
    }
    return _timeline_payload("admin/pretrip", counts)


def build_admin_evidence_timeline(view: dict[str, Any]) -> dict[str, Any]:
    capability = view.get("capability_timeline") or view.get("capability_timeline_import") or {}
    mcp = view.get("major_critical_points") or {}
    gis = view.get("gis_perception_timeline") or {}
    review_queue = view.get("review_queue") or {}
    review_workbench = view.get("review_workbench") or {}
    route_notes = view.get("route_notes") or {}
    map_payload = view.get("map") or {}
    overpass = view.get("overpass_evidence") or {}
    map_candidates = view.get("map_candidates") or {}
    environment_values = view.get("environment_values") or {}
    mileage = view.get("mileage_tag_alignment") or {}
    reference_segment_timing = view.get("reference_segment_timing") or {}
    counts = {
        "route": 1 if view.get("route") else 0,
        "checkpoints": _len((view.get("mission") or {}).get("checkpoints")),
        "segments": _len((view.get("mission") or {}).get("segments")),
        "route_timing": int(
            (reference_segment_timing.get("counts") or {}).get("usable_segment_count")
            or _len(reference_segment_timing.get("segments"))
        ),
        "capability_timeline": int(capability.get("edge_count") or _len(capability.get("edges"))),
        "rest_intervals": int(
            (capability.get("summary") or {}).get("rest_interval_count")
            or capability.get("rest_interval_count")
            or _len(capability.get("rest_intervals"))
        ),
        "mcp": int((mcp.get("counts") or {}).get("mcp_candidate_count") or _len(mcp.get("candidates"))),
        "gis_cp": int(
            (gis.get("counts") or {}).get("checkpoint_candidate_count")
            or _len(gis.get("checkpoint_candidates"))
        )
        + int((gis.get("counts") or {}).get("nearby_group_count") or _len(gis.get("nearby_groups"))),
        "risk": _len((view.get("risk_score") or {}).get("points"))
        + _len((view.get("risk_ribbon") or {}).get("segments"))
        + _len((view.get("risk_heatmap") or {}).get("segments"))
        + _len((view.get("risk_delta") or {}).get("segments"))
        + _len(view.get("risk_rules")),
        "map_context": int((overpass.get("counts") or {}).get("candidates") or 0)
        + int((map_candidates.get("counts") or {}).get("corridor_candidates") or 0)
        + int((map_candidates.get("counts") or {}).get("hazard_candidates") or 0)
        + int((map_candidates.get("counts") or {}).get("poi_candidates") or 0)
        + int((environment_values.get("counts") or {}).get("item_count") or 0)
        or _len(map_payload.get("corridors"))
        + _len(map_payload.get("hazards"))
        + _len(map_payload.get("pois")),
        "mileage": int((mileage.get("counts") or {}).get("tag_count") or 0),
        "reference_tracks": int(
            (view.get("reference_tracks") or {}).get("reference_track_count")
            or _len((view.get("reference_tracks") or {}).get("reference_tracks"))
        ),
        "review": int((review_queue.get("counts") or {}).get("item_count") or _len(review_queue.get("items")))
        + int((review_workbench.get("counts") or {}).get("category_group_count") or _len(review_workbench.get("category_groups")))
        + int((route_notes.get("counts") or {}).get("note_candidate_count") or 0),
        "runtime_handoff": 1
        if view.get("departure_bundle") or view.get("runtime_handoff")
        else _len(view.get("safety_timeline")) + _len(view.get("incident_packages")),
    }
    return _timeline_payload("admin", counts)


def build_scout_agent_skill_summary(
    *,
    root: Path = ROOT,
    manifest_dir: Path | None = None,
) -> dict[str, Any]:
    resolved_manifest_dir = manifest_dir or root / "tools" / "scout_agent_tool_manifests"
    manifests = load_tool_manifests(resolved_manifest_dir)
    tools = [
        _agent_tool_projection_record(
            summarize_tool_manifest(manifest),
            source_path=_relpath(resolved_manifest_dir, root),
        )
        for manifest in manifests
    ]
    mode_counts = Counter(str(tool["mode"]) for tool in tools)
    authorization_counts = Counter(str(tool["requires_authorization"]) for tool in tools)
    write_capable_count = sum(1 for tool in tools if tool.get("allowed_writes"))
    return {
        "artifact_kind": "scout_agent_skill_registry_summary",
        "schema_version": "0.1.0",
        "source_path": _relpath(resolved_manifest_dir, root),
        "counts": {
            "tool_count": len(tools),
            "mode_counts": dict(sorted(mode_counts.items())),
            "authorization_counts": dict(sorted(authorization_counts.items())),
            "write_capable_count": write_capable_count,
        },
        "tools": tools,
        "boundary": {
            "read_only_registry_projection": True,
            "tool_execution_allowed_from_ui": False,
            "runtime_safety_truth": False,
            "live_safety_api_calls_allowed": False,
            "phase1_safety_mutation_allowed": False,
        },
    }


def _timeline_payload(surface: str, counts: dict[str, int]) -> dict[str, Any]:
    categories = [
        {
            "category_id": category_id,
            "source_id": f"{surface}.evidence_timeline.{category_id}",
            "source_path": "view.evidence_timeline",
            "evidence_type": "cross_surface_evidence_timeline_category",
            "label": EVIDENCE_TIMELINE_CATEGORY_LABELS[category_id],
            "count": int(counts.get(category_id, 0)),
            "available": int(counts.get(category_id, 0)) > 0,
            **_projection_metadata(
                source_path="view.evidence_timeline",
                evidence_type="cross_surface_evidence_timeline_category",
                source_kind="evidence_timeline_category",
                source_id=f"{surface}.evidence_timeline.{category_id}",
                source_refs=["view.evidence_timeline", category_id],
                extractor_version="cross_surface_evidence_timeline.projection.v1",
                summary=(
                    "Cross-surface evidence timeline category projection; "
                    "candidate-only UI evidence, not runtime safety truth."
                ),
            ),
        }
        for category_id in EVIDENCE_TIMELINE_CATEGORY_ORDER
    ]
    return {
        "artifact_kind": "scout_cross_surface_evidence_timeline",
        "schema_version": "0.1.0",
        "surface": surface,
        "category_order": list(EVIDENCE_TIMELINE_CATEGORY_ORDER),
        "categories": categories,
        "counts": {
            "category_count": len(categories),
            "available_category_count": sum(1 for item in categories if item["available"]),
            "total_evidence_count": sum(item["count"] for item in categories),
        },
        "boundary": {
            "projection_only": True,
            "pretrip_candidate_evidence_only": True,
            "runtime_safety_truth": False,
            "phase1_runtime_mutation_allowed": False,
            "phase2_brain_writeback_allowed": False,
        },
    }


def _len(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _agent_tool_projection_record(
    tool: dict[str, Any],
    *,
    source_path: str,
) -> dict[str, Any]:
    tool_id = str(tool.get("id") or "unknown_tool")
    return {
        **tool,
        **_projection_metadata(
            source_path=source_path,
            evidence_type="scout_agent_skill_registry_tool",
            source_kind="scout_agent_tool_manifest",
            source_id=tool_id,
            source_refs=[source_path, tool_id],
            extractor_version="scout_agent_skill_registry.projection.v1",
            summary=(
                "Scout agent skill registry projection; listing only, not tool "
                "execution or runtime safety truth."
            ),
        ),
    }


def _projection_metadata(
    *,
    source_path: str,
    evidence_type: str,
    source_kind: str,
    source_id: str,
    source_refs: list[str],
    extractor_version: str,
    summary: str,
) -> dict[str, Any]:
    identity = {
        "source_id": source_id,
        "source_path": source_path,
        "evidence_type": evidence_type,
        "source_refs": source_refs,
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return {
        "source_id": source_id,
        "source_path": source_path,
        "evidence_type": evidence_type,
        "source_refs": source_refs,
        "source_attribution": [
            {
                "source_kind": source_kind,
                "source_ref": source_path,
                "source_candidate_id": source_id,
                "confidence": "medium",
                "stale_risk": "medium",
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        ],
        "confidence": "medium",
        "stale_risk": "medium",
        "review_state": "projection_only",
        "candidate_only": True,
        "runtime_safety_truth": False,
        "extractor_version": extractor_version,
        "pydantic_ai_prompt_version": "not_applicable_deterministic_registry_projection.v1",
        "model_output_sha256": digest,
        "model_output_summary": summary,
    }


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
