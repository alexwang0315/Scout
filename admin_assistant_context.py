from __future__ import annotations

from pathlib import Path
from typing import Any

from admin_after_action import ROOT, build_admin_case_view


def build_admin_assistant_context(
    case_id: str,
    *,
    root: Path = ROOT,
    selected_source_id: str | None = None,
    max_timeline_items: int = 20,
    max_capsules: int = 12,
) -> dict[str, Any]:
    view = build_admin_case_view(case_id, root=root)
    compact_view = _compact_admin_view(
        view,
        max_timeline_items=max_timeline_items,
        max_capsules=max_capsules,
    )
    sources = _collect_sources(compact_view)
    return {
        "surface": "admin",
        "context_kind": "assistant_context",
        "read_only": True,
        "bounded": True,
        "auditable": True,
        "boundary": _boundary(),
        "summary": {
            "case_id": view["case_id"],
            "description": view["summary"].get("description"),
            "route_point_count": view["route"]["point_count"],
            "timeline_item_count": len(view.get("safety_timeline", [])),
            "segment_capsule_count": len(view.get("segment_capsules", [])),
            "incident_count": len(view.get("incident_packages", [])),
            "safety_level": view["replay"].get("safety_level"),
            "checkpoint_hit_count": view["replay"].get("checkpoint_hit_count"),
        },
        "selected_evidence": _find_source(compact_view, selected_source_id),
        "compact_view": compact_view,
        "sources": sources,
        "limitations": [
            "Context is a compact after-action view projection.",
            "Route point samples and historical raw payloads are not embedded.",
            "No historical evidence or writeback target is mutated.",
        ],
    }


def _compact_admin_view(
    view: dict[str, Any],
    *,
    max_timeline_items: int,
    max_capsules: int,
) -> dict[str, Any]:
    return {
        "case_id": view["case_id"],
        "summary": _compact_case_summary(view["summary"]),
        "artifacts": dict(view.get("artifacts", {})),
        "mission": {
            "mission_id": view["mission"]["mission_id"],
            "name": view["mission"]["name"],
            "route_source": view["mission"]["route_source"],
            "checkpoint_count": len(view["mission"].get("checkpoints", [])),
            "segment_count": len(view["mission"].get("segments", [])),
            "control_zone_count": len(view["mission"].get("control_zones", [])),
        },
        "route": {
            "source_id": "field_route",
            "source_path": view["route"]["source_path"],
            "evidence_type": "field_route_summary",
            "bounds": view["route"]["bounds"],
            "point_count": view["route"]["point_count"],
            "total_progress_m": view["route"]["total_progress_m"],
        },
        "map": {
            "source_id": "field_map_context",
            "source_path": view["map"]["source_path"],
            "evidence_type": "map_context_summary",
            "metadata": view["map"].get("metadata", {}),
            "corridor_count": len(view["map"].get("corridors", [])),
            "hazard_count": len(view["map"].get("hazards", [])),
            "poi_count": len(view["map"].get("pois", [])),
        },
        "risk_rules": {
            "rule_count": len(view.get("risk_rules", [])),
            "sources": [
                _source_ref(rule)
                for rule in view.get("risk_rules", [])
                if _source_ref(rule) is not None
            ],
        },
        "replay": dict(view["replay"]),
        "safety_timeline": [
            _compact_timeline_item(item)
            for item in view.get("safety_timeline", [])[:max_timeline_items]
        ],
        "segment_capsules": [
            _compact_capsule(capsule)
            for capsule in view.get("segment_capsules", [])[:max_capsules]
        ],
        "incident_packages": [
            _compact_package(package)
            for package in view.get("incident_packages", [])
        ],
    }


def _compact_case_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "description": summary.get("description"),
        "source_files": summary.get("source_files", []),
        "map_context": summary.get("map_context"),
        "bbox": summary.get("bbox"),
        "segment_count": len(summary.get("segments", [])),
        "segments": [
            {
                "id": segment.get("id"),
                "duration_s": segment.get("duration_s"),
                "records": segment.get("records"),
                "valid_location_records": segment.get("valid_location_records"),
                "source_id": segment.get("source_id"),
                "source_path": segment.get("source_path"),
                "evidence_type": "field_case_segment_summary",
            }
            for segment in summary.get("segments", [])
        ],
    }


def _compact_timeline_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item.get(key)
        for key in (
            "timestamp",
            "label",
            "reason",
            "from_level",
            "to_level",
            "source_id",
            "source_path",
            "evidence_type",
        )
        if key in item
    }


def _compact_capsule(capsule: dict[str, Any]) -> dict[str, Any]:
    return {
        key: capsule.get(key)
        for key in (
            "capsule_id",
            "segment_id",
            "started_at",
            "ended_at",
            "sample_count",
            "incident_id",
            "source_id",
            "source_path",
            "evidence_type",
        )
        if key in capsule
    }


def _compact_package(package: dict[str, Any]) -> dict[str, Any]:
    return {
        key: package.get(key)
        for key in (
            "incident_id",
            "trigger_level",
            "triggered_at",
            "raw_window_start",
            "raw_window_end",
            "raw_sample_count",
            "segment_capsule_ids",
            "source_id",
            "source_path",
            "evidence_type",
        )
        if key in package
    }


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
        "timestamp",
        "label",
        "reason",
        "summary",
        "counts",
        "status",
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
