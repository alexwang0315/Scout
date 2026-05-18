from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parent
PreTripViewBuilder = Callable[..., dict[str, Any]]


def build_pretrip_assistant_context(
    project_id: str,
    *,
    root: Path = ROOT,
    project_root: Path | None = None,
    selected_source_id: str | None = None,
    max_sections: int = 24,
    view_builder: PreTripViewBuilder | None = None,
) -> dict[str, Any]:
    resolved_view_builder = view_builder or _load_pretrip_view_builder()
    if resolved_view_builder is None:
        return _unavailable_pretrip_context(project_id)
    try:
        view = resolved_view_builder(project_id, root=root, project_root=project_root)
    except ModuleNotFoundError:
        return _unavailable_pretrip_context(project_id)
    compact_view = _compact_pretrip_view(view, max_sections=max_sections)
    sources = _collect_sources(compact_view)
    return {
        "surface": "pretrip",
        "context_kind": "assistant_context",
        "read_only": True,
        "bounded": True,
        "auditable": True,
        "boundary": _boundary(),
        "summary": {
            "project_id": view["project_id"],
            "route_name": view["summary"].get("route_name"),
            "package_id": view["summary"].get("package_id"),
            "status": view["summary"].get("status"),
            "readiness_status": view["readiness"].get("status"),
            "review_queue_status": view["review_queue"].get("status"),
            "review_queue_counts": view["review_queue"].get("counts", {}),
            "raw_payloads_embedded": view["raw_sample_summary"].get(
                "raw_payloads_embedded"
            ),
        },
        "selected_evidence": _find_source(compact_view, selected_source_id),
        "compact_view": compact_view,
        "sources": sources,
        "limitations": [
            "Context is a compact pre-trip admin view projection.",
            "Candidate and review summaries are explanatory only.",
            "No review state, runtime handoff, or fact writeback target is mutated.",
        ],
    }


def _load_pretrip_view_builder() -> PreTripViewBuilder | None:
    try:
        from pretrip_admin_view import build_pretrip_admin_view
    except ModuleNotFoundError:
        return None
    return build_pretrip_admin_view


def _unavailable_pretrip_context(project_id: str) -> dict[str, Any]:
    return {
        "surface": "pretrip",
        "context_kind": "assistant_context",
        "read_only": True,
        "bounded": True,
        "auditable": True,
        "boundary": _boundary(),
        "summary": {
            "project_id": project_id,
            "status": "unavailable",
            "readiness_status": "unknown",
            "review_queue_status": "unknown",
            "review_queue_counts": {},
        },
        "selected_evidence": None,
        "compact_view": {},
        "sources": [
            {
                "source_id": f"pretrip_project.{project_id}",
                "source_path": "pretrip_assistant_context",
                "evidence_type": "pretrip_context_unavailable",
            }
        ],
        "limitations": [
            "Pre-trip admin view is not available in this runtime.",
            "No candidate, review, readiness, runtime handoff, or fact state is mutated.",
        ],
    }


def _compact_pretrip_view(
    view: dict[str, Any],
    *,
    max_sections: int,
) -> dict[str, Any]:
    planning = view["tabs"]["pre_trip_planning"]
    post = view["tabs"]["post_analysis"]
    return {
        "project_id": view["project_id"],
        "summary": dict(view["summary"]),
        "artifacts": dict(view.get("artifacts", {})),
        "route": _compact_route(view["route"]),
        "readiness": dict(view["readiness"]),
        "review_queue": _compact_review_queue(view["review_queue"]),
        "review_draft_log": _compact_review_log(view["review_draft_log"]),
        "review_decision_log": _compact_review_log(view["review_decision_log"]),
        "review_decision_apply_plan": _compact_review_log(
            view["review_decision_apply_plan"]
        ),
        "external_import_queue": _compact_review_log(view["external_import_queue"]),
        "expert_contributions": _compact_review_log(view["expert_contributions"]),
        "departure_bundle": _compact_review_log(view["departure_bundle"]),
        "resources": dict(view["resources"]),
        "weather": dict(view["weather"]),
        "contours": dict(view["contours"]),
        "raw_sample_summary": dict(view["raw_sample_summary"]),
        "planning_sections": planning.get("sections", [])[:max_sections],
        "post_analysis_sections": post.get("sections", [])[:max_sections],
    }


def _compact_route(route: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": route["source_id"],
        "source_path": route["source_path"],
        "evidence_type": route["evidence_type"],
        "route_name": route["route_name"],
        "bounds": route["bounds"],
        "point_count": route["point_count"],
        "distance_m": route["distance_m"],
        "elevation_min_m": route.get("elevation_min_m"),
        "elevation_max_m": route.get("elevation_max_m"),
        "started_at": route.get("started_at"),
        "ended_at": route.get("ended_at"),
    }


def _compact_review_queue(review_queue: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": review_queue["source_id"],
        "source_path": review_queue["source_path"],
        "evidence_type": review_queue["evidence_type"],
        "status": review_queue["status"],
        "counts": review_queue["counts"],
        "boundary": dict(review_queue["boundary"]),
        "items": [
            {
                "source_id": item["source_id"],
                "source_path": item["source_path"],
                "evidence_type": item["evidence_type"],
                "category": item.get("category"),
                "priority": item.get("priority"),
                "status": item.get("status"),
                "candidate_ref": item.get("candidate_ref"),
                "review_focus": item.get("review_focus", []),
                "map_target_ids": item.get("map_target_ids", []),
            }
            for item in review_queue.get("items", [])[:12]
        ],
    }


def _compact_review_log(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if payload is None:
        return None
    compact = {
        "source_id": payload["source_id"],
        "source_path": payload["source_path"],
        "evidence_type": payload["evidence_type"],
        "status": payload.get("status"),
        "counts": payload.get("counts", {}),
    }
    if "boundary" in payload:
        compact["boundary"] = dict(payload["boundary"])
    for key in (
        "apply_summary",
        "category_counts",
        "plan_id",
        "package_id",
        "package_status",
    ):
        if key in payload:
            compact[key] = payload[key]
    return compact


def _find_source(value: Any, selected_source_id: str | None) -> dict[str, Any] | None:
    if selected_source_id is None:
        return None
    if isinstance(value, dict):
        if value.get("source_id") == selected_source_id:
            return _compact_selected_source(value)
        for item in value.values():
            found = _find_source(item, selected_source_id)
            if found is not None:
                return found
    if isinstance(value, list):
        for item in value:
            found = _find_source(item, selected_source_id)
            if found is not None:
                return found
    return None


def _compact_selected_source(value: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "source_id",
        "source_path",
        "evidence_type",
        "title",
        "status",
        "counts",
        "summary",
        "boundary",
        "candidate_ref",
        "review_focus",
    }
    return {key: item for key, item in value.items() if key in allowed}


def _collect_sources(value: Any) -> list[dict[str, str]]:
    seen: set[tuple[str, str, str]] = set()
    sources: list[dict[str, str]] = []
    for source in _iter_sources(value):
        key = (
            source["source_id"],
            source["source_path"],
            source["evidence_type"],
        )
        if key in seen:
            continue
        seen.add(key)
        sources.append(source)
    return sources


def _iter_sources(value: Any) -> list[dict[str, str]]:
    if isinstance(value, dict):
        ref = _source_ref(value)
        refs = [ref] if ref is not None else []
        for item in value.values():
            refs.extend(_iter_sources(item))
        return refs
    if isinstance(value, list):
        refs: list[dict[str, str]] = []
        for item in value:
            refs.extend(_iter_sources(item))
        return refs
    return []


def _source_ref(value: dict[str, Any]) -> dict[str, str] | None:
    source_id = value.get("source_id")
    source_path = value.get("source_path")
    evidence_type = value.get("evidence_type")
    if not source_id or not source_path or not evidence_type:
        return None
    return {
        "source_id": str(source_id),
        "source_path": str(source_path),
        "evidence_type": str(evidence_type),
    }


def _boundary() -> dict[str, bool]:
    return {
        "read_only": True,
        "phase1_mutation_allowed": False,
        "phase2_writeback_allowed": False,
        "observed_fact_write_allowed": False,
        "pretrip_review_mutation_allowed": False,
        "incident_store_write_allowed": False,
        "outbound_send_allowed": False,
        "hardware_control_allowed": False,
    }
