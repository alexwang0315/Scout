"""Bounded provenance projection for Navigation & Terrain Intelligence."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Sequence

from navigation_terrain_dem import WorkspaceTerrainEvidenceError

DEFAULT_MAX_GPX_SOURCES = 32
DEFAULT_MAX_ORDERED_CLUES = 16
TRACEABLE_NARRATIVE_FAMILIES = {
    "official_historical_baseline",
    "official_historical_survey",
    "archival_map",
    "historical_prose",
    "professional_route_narrative",
    "public_route_report",
    "public_completed_trip_gpx",
}


def build_workspace_source_ledger(
    project_root: Path,
    project: dict[str, Any],
    *,
    max_gpx_sources: int = DEFAULT_MAX_GPX_SOURCES,
    max_ordered_clues: int = DEFAULT_MAX_ORDERED_CLUES,
) -> dict[str, Any]:
    """Build a bounded P0/P1/P2 ledger from workspace-owned references."""

    if max_gpx_sources < 1 or max_gpx_sources > 100:
        raise WorkspaceTerrainEvidenceError(
            "max_gpx_sources must be between 1 and 100"
        )
    if max_ordered_clues < 1 or max_ordered_clues > 100:
        raise WorkspaceTerrainEvidenceError(
            "max_ordered_clues must be between 1 and 100"
        )
    project_root = project_root.resolve()
    project_id = str(project.get("project_id") or project_root.name)
    coverage_ref = _optional_project_ref(project, "dtm_coverage_summary_ref")
    source_index_ref = _optional_project_ref(
        project,
        "historical_gpx_source_index_ref",
    )
    narrative_ledger_ref = _optional_project_ref(
        project,
        "historical_route_source_ledger_ref",
    )
    route_notes_ref = _optional_project_ref(
        project,
        "normalized_route_note_candidates_ref",
    )
    coverage = _read_if_present(project_root, coverage_ref)
    source_index = _read_if_present(project_root, source_index_ref)
    narrative_ledger = _read_if_present(project_root, narrative_ledger_ref)
    route_notes = _read_if_present(project_root, route_notes_ref)

    sources: list[dict[str, Any]] = []
    candidate_tiles = coverage.get("candidate_tiles", [])
    if coverage_ref and isinstance(candidate_tiles, list):
        horizontal_datums = sorted(
            {
                str(tile.get("horizontal_datum"))
                for tile in candidate_tiles
                if isinstance(tile, dict) and tile.get("horizontal_datum")
            }
        )
        vertical_datums = sorted(
            {
                str(tile.get("vertical_datum"))
                for tile in candidate_tiles
                if isinstance(tile, dict) and tile.get("vertical_datum")
            }
        )
        sources.append(
            {
                "id": f"dtm.coverage.{project_id}",
                "tier": "P0",
                "family": "official_dem_baseline",
                "provider": "Taiwan 20m DTM material inventory",
                "source_ref": coverage_ref,
                "claim": (
                    f"{len(candidate_tiles)} candidate DTM grid records cover "
                    "the prepared route extent."
                ),
                "coordinate_reference_system": "EPSG:3826",
                "horizontal_datums": horizontal_datums,
                "vertical_datums": vertical_datums,
                "limitations": (
                    "DEM morphology does not resolve path existence, vegetation, "
                    "surface stability, access, or current conditions."
                ),
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )

    sources.extend(
        _project_traceable_narrative_sources(
            narrative_ledger,
            source_ref=narrative_ledger_ref,
        )
    )
    sources.extend(
        _project_gpx_sources(
            source_index,
            source_ref=source_index_ref,
            limit=max_gpx_sources,
        )
    )
    sources = _dedupe_sources(sources)

    ordered_clues = _ordered_waypoint_clues(
        route_notes,
        source_ref=route_notes_ref,
        limit=max_ordered_clues,
    )
    tier_counts = {
        tier: sum(source["tier"] == tier for source in sources)
        for tier in ("P0", "P1", "P2")
    }
    evidence_gaps = []
    if not any(
        source["family"] in TRACEABLE_NARRATIVE_FAMILIES
        for source in sources
    ):
        evidence_gaps.append(
            "No archival or historical prose source, public/professional "
            "narrative, or completed-trip landing page is linked to this "
            "workspace."
        )
    if source_index_ref and any(
        source["provider"] == "operator_supplied_local_file"
        for source in sources
        if source["family"] == "gpx_route_observation"
    ):
        evidence_gaps.append(
            "Some operator-supplied GPX records have no source landing-page "
            "provenance."
        )
    if not ordered_clues:
        evidence_gaps.append(
            "No bounded ordered waypoint clue chain was prepared."
        )

    return {
        "schema_version": "scout_navigation_source_ledger.v0",
        "artifact_kind": "navigation_terrain_source_ledger",
        "project_id": project_id,
        "status": (
            "ready"
            if sources and tier_counts["P1"] > 0
            else "ready_with_historical_source_gap"
            if sources
            else "unavailable"
        ),
        "sources": sources,
        "source_tier_counts": tier_counts,
        "source_count": len(sources),
        "ordered_clue_chain_kind": (
            "gpx_waypoint_clues" if ordered_clues else "not_prepared"
        ),
        "ordered_clues": ordered_clues,
        "coordinate_audit": {
            "dtm": {
                "crs": "EPSG:3826",
                "datum": "TWD97 / TM2 zone 121",
                "vertical_datum": _common_vertical_datum(candidate_tiles),
                "source_ref": coverage_ref,
            },
            "gpx": {
                "crs": "EPSG:4326",
                "datum": "WGS84",
                "source_ref": source_index_ref,
            },
            "comparison_transform": {
                "method": "wgs84_to_twd97_transverse_mercator",
                "survey_grade": False,
                "review_required": True,
            },
        },
        "contradictions": [],
        "evidence_gaps": evidence_gaps,
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "safe_or_walkable": "not_determined",
            "raw_gpx_embedded": False,
            "raw_dem_embedded": False,
            "exact_timestamps_embedded": False,
            "absolute_source_paths_exposed": False,
            "human_review_required": True,
        },
    }


def _project_traceable_narrative_sources(
    payload: dict[str, Any],
    *,
    source_ref: str | None,
) -> list[dict[str, Any]]:
    if not payload:
        return []
    if (
        payload.get("candidate_only") is not True
        or payload.get("runtime_safety_truth") is not False
    ):
        raise WorkspaceTerrainEvidenceError(
            "historical route source ledger violates candidate boundary"
        )
    raw_sources = payload.get("sources", [])
    if not isinstance(raw_sources, list):
        raise WorkspaceTerrainEvidenceError(
            "historical route source ledger sources must be a list"
        )
    projected = []
    for item in raw_sources[:100]:
        if not isinstance(item, dict):
            continue
        source_id = str(item.get("id") or "").strip()
        tier = str(item.get("tier") or "").strip()
        family = str(item.get("family") or "").strip()
        if not source_id or tier not in {"P0", "P1"} or not family:
            continue
        if (
            item.get("candidate_only") is not True
            or item.get("runtime_safety_truth") is not False
        ):
            raise WorkspaceTerrainEvidenceError(
                f"historical source {source_id} violates candidate boundary"
            )
        projected.append(
            {
                "id": source_id,
                "tier": tier,
                "family": family,
                "provider": _bounded_text(item.get("provider"), 160),
                "url": _bounded_http_url(item.get("url")),
                "source_location": _bounded_text(
                    item.get("source_location"),
                    240,
                ),
                "source_ref": source_ref,
                "retrieved_at": _bounded_text(item.get("retrieved_at"), 40),
                "publication_date": _bounded_text(
                    item.get("publication_date"),
                    40,
                ),
                "coordinate_reference_system": _bounded_text(
                    item.get("coordinate_reference_system"),
                    80,
                ),
                "claim": _bounded_text(item.get("claim"), 500),
                "sha256": _sha256_or_none(item.get("sha256")),
                "limitations": _bounded_text(item.get("limitations"), 500),
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )
    return projected


def _project_gpx_sources(
    payload: dict[str, Any],
    *,
    source_ref: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    raw_sources = payload.get("sources", [])
    if not isinstance(raw_sources, list):
        return []
    projected = []
    for item in raw_sources[:limit]:
        if not isinstance(item, dict):
            continue
        source_id = str(item.get("source_id") or "")
        if not source_id:
            continue
        provider = str(item.get("provider") or "unknown")
        projected.append(
            {
                "id": source_id,
                "tier": _workspace_source_tier(provider),
                "family": "gpx_route_observation",
                "provider": provider,
                "source_ref": source_ref,
                "role": str(item.get("role") or "reference_track"),
                "route_role": str(item.get("route_role") or "reference_track"),
                "sha256": _sha256_or_none(item.get("sha256")),
                "retrieved_at": item.get("imported_at"),
                "coordinate_reference_system": "EPSG:4326",
                "claim": "A GPX file was supplied as candidate route evidence.",
                "limitations": (
                    "A recorded trace does not prove current access or "
                    "walkability; landing-page provenance may be unknown."
                ),
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )
    return projected


def _ordered_waypoint_clues(
    payload: dict[str, Any],
    *,
    source_ref: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    candidates = payload.get("candidates", [])
    if not isinstance(candidates, list):
        return []
    ordered = []
    seen_labels: set[str] = set()
    for item in candidates:
        if not isinstance(item, dict):
            continue
        waypoint_index = item.get("source_waypoint_index")
        if not isinstance(waypoint_index, int):
            continue
        attribution = item.get("source_attribution", [])
        if isinstance(attribution, list) and attribution:
            source_keys = {
                str(record.get("source_key") or "")
                for record in attribution
                if isinstance(record, dict)
            }
            if source_keys and "golden_route" not in source_keys:
                continue
        label = str(
            item.get("normalized_note")
            or item.get("name")
            or item.get("desc")
            or ""
        ).strip()
        if not label or label in seen_labels:
            continue
        seen_labels.add(label)
        refs = [
            str(value)
            for value in item.get("source_refs", [])
            if isinstance(value, str) and value.strip()
        ]
        if source_ref:
            refs.append(source_ref)
        ordered.append(
            {
                "id": str(item.get("candidate_id") or f"clue-{waypoint_index}"),
                "order": waypoint_index,
                "label": label,
                "clue_type": str(item.get("note_category") or "waypoint_note"),
                "elevation_m": _finite_number(item.get("ele_m")),
                "source_refs": list(dict.fromkeys(refs)),
                "evidence_kind": "gpx_waypoint_clue",
                "requires_human_review": True,
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )
    ordered.sort(key=lambda item: (item["order"], item["id"]))
    return ordered[:limit]


def _read_if_present(project_root: Path, ref: str | None) -> dict[str, Any]:
    return _read_project_json(project_root, ref) if ref else {}


def _optional_project_ref(project: dict[str, Any], key: str) -> str | None:
    value = project.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise WorkspaceTerrainEvidenceError(f"{key} must be a relative path")
    ref = value.strip()
    candidate = Path(ref)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise WorkspaceTerrainEvidenceError(f"{key} must stay inside workspace")
    return ref


def _read_project_json(project_root: Path, ref: str) -> dict[str, Any]:
    path = (project_root / ref).resolve()
    try:
        path.relative_to(project_root)
    except ValueError as exc:
        raise WorkspaceTerrainEvidenceError(
            "workspace reference escapes project root"
        ) from exc
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkspaceTerrainEvidenceError(
            f"workspace artifact could not be read: {ref}"
        ) from exc
    if not isinstance(payload, dict):
        raise WorkspaceTerrainEvidenceError(
            f"workspace artifact must be a JSON object: {ref}"
        )
    return payload


def _dedupe_sources(sources: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return list({source["id"]: source for source in reversed(sources)}.values())[::-1]


def _workspace_source_tier(provider: str) -> str:
    lowered = provider.lower()
    if "official" in lowered or "government" in lowered:
        return "P0"
    if "operator" in lowered or "scout" in lowered:
        return "P2"
    return "P1"


def _common_vertical_datum(tiles: Any) -> str | None:
    if not isinstance(tiles, list):
        return None
    values = {
        str(tile.get("vertical_datum"))
        for tile in tiles
        if isinstance(tile, dict) and tile.get("vertical_datum")
    }
    return values.pop() if len(values) == 1 else None


def _bounded_text(value: Any, limit: int) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()[:limit]


def _bounded_http_url(value: Any) -> str | None:
    text = _bounded_text(value, 1000)
    if text is None or not text.startswith(("https://", "http://")):
        return None
    return text


def _sha256_or_none(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if len(normalized) != 64:
        return None
    if any(character not in "0123456789abcdef" for character in normalized):
        return None
    return normalized


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
