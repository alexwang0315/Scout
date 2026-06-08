from __future__ import annotations

import json
from pathlib import Path
from typing import Any


LIVE_NAVIGATION_STATE_TOOL_ID = "scout.ai.live_navigation_state.assess.v0"
LIVE_NAVIGATION_STATE_OUTPUT_KIND = "scout_ai_live_navigation_state_tool_output"

LIVE_NAVIGATION_REQUIRED_FIELDS = (
    "observed_at",
    "lat",
    "lon",
    "elevation_m",
    "source",
    "hdop",
    "horizontal_accuracy_m",
    "fix_quality",
    "satellite_count",
    "max_cno_dbhz",
    "heading_deg",
    "course_deg",
    "speed_mps",
    "nearest_route_distance_m",
    "route_progress_m",
    "nearest_cp_id",
    "ins_dr_source",
    "confidence",
    "uncertainty_m",
    "last_anchor_at",
)


def assess_scout_live_navigation_state(
    project_root: Path | str,
    *,
    query: str = "",
    observed_at: str | None = None,
    lat: float | int | str | None = None,
    lon: float | int | str | None = None,
    elevation_m: float | int | str | None = None,
    source: str | None = None,
    hdop: float | int | str | None = None,
    horizontal_accuracy_m: float | int | str | None = None,
    fix_quality: str | None = None,
    satellite_count: int | str | None = None,
    max_cno_dbhz: float | int | str | None = None,
    heading_deg: float | int | str | None = None,
    course_deg: float | int | str | None = None,
    speed_mps: float | int | str | None = None,
    nearest_route_distance_m: float | int | str | None = None,
    route_progress_m: float | int | str | None = None,
    nearest_cp_id: str | None = None,
    ins_dr_source: str | None = None,
    confidence: float | int | str | None = None,
    uncertainty_m: float | int | str | None = None,
    last_anchor_at: str | None = None,
) -> dict[str, Any]:
    """Assess a caller-provided live navigation snapshot without reading runtime state."""

    root = Path(project_root)
    project = _load_project(root)
    project_id = str(project.get("project_id") or project.get("id") or root.name)
    provided = {
        "observed_at": observed_at,
        "lat": lat,
        "lon": lon,
        "elevation_m": elevation_m,
        "source": source,
        "hdop": hdop,
        "horizontal_accuracy_m": horizontal_accuracy_m,
        "fix_quality": fix_quality,
        "satellite_count": satellite_count,
        "max_cno_dbhz": max_cno_dbhz,
        "heading_deg": heading_deg,
        "course_deg": course_deg,
        "speed_mps": speed_mps,
        "nearest_route_distance_m": nearest_route_distance_m,
        "route_progress_m": route_progress_m,
        "nearest_cp_id": nearest_cp_id,
        "ins_dr_source": ins_dr_source,
        "confidence": confidence,
        "uncertainty_m": uncertainty_m,
        "last_anchor_at": last_anchor_at,
    }
    missing_fields = [
        field for field in LIVE_NAVIGATION_REQUIRED_FIELDS if _is_missing(provided[field])
    ]
    available_position = not _is_missing(lat) and not _is_missing(lon)
    return {
        "tool_id": LIVE_NAVIGATION_STATE_TOOL_ID,
        "status": "completed",
        "project_id": project_id,
        "query": query,
        "assessment_kind": "read_only_live_navigation_snapshot",
        "answerability": (
            "snapshot_evidence_available"
            if not missing_fields
            else "snapshot_missing_required_fields"
        ),
        "missing_fields": missing_fields,
        "provided_fields": {
            field: value
            for field, value in provided.items()
            if not _is_missing(value)
        },
        "route_query_plan": _route_query_plan(
            available_position=available_position,
            missing_fields=missing_fields,
        ),
        "quality_flags": _quality_flags(
            hdop=hdop,
            horizontal_accuracy_m=horizontal_accuracy_m,
            fix_quality=fix_quality,
            satellite_count=satellite_count,
            uncertainty_m=uncertainty_m,
        ),
        "results": [
            {
                "label": "live navigation state assessor",
                "snippet": (
                    "caller-provided snapshot only; no live hardware read; "
                    "must not mutate /safety/* or send outbound; missing_fields="
                    + ",".join(missing_fields)
                ),
            }
        ],
        "source_report": [
            {
                "source_kind": "deterministic_live_navigation_snapshot_policy",
                "status": "loaded",
                "source_path": (
                    "scout_live_navigation_state_tool."
                    "assess_scout_live_navigation_state"
                ),
                "loaded_count": 1,
            }
        ],
        "boundary": _closed_boundary(),
    }


def _route_query_plan(
    *,
    available_position: bool,
    missing_fields: list[str],
) -> dict[str, Any]:
    if not available_position:
        return {
            "status": "insufficient_position",
            "next_tools": [],
            "missing_position_fields": [
                field for field in ("lat", "lon") if field in missing_fields
            ],
        }
    return {
        "status": "position_available_for_followup",
        "next_tools": [
            "pydantic_ai.tool.search_scout_risk_scores.v0",
            "pydantic_ai.tool.search_scout_terrain_scores.v0",
            "scout.ai.safety_boundary.explain.v0",
        ],
        "note": "Use the provided coordinate as candidate evidence only.",
    }


def _quality_flags(
    *,
    hdop: object,
    horizontal_accuracy_m: object,
    fix_quality: object,
    satellite_count: object,
    uncertainty_m: object,
) -> dict[str, Any]:
    flags: dict[str, Any] = {}
    hdop_value = _float_or_none(hdop)
    accuracy_value = _float_or_none(horizontal_accuracy_m)
    satellites_value = _int_or_none(satellite_count)
    uncertainty_value = _float_or_none(uncertainty_m)
    if hdop_value is not None:
        flags["hdop"] = hdop_value
        flags["hdop_usable"] = hdop_value <= 2.5
    if accuracy_value is not None:
        flags["horizontal_accuracy_m"] = accuracy_value
        flags["horizontal_accuracy_usable"] = accuracy_value <= 15.0
    if satellites_value is not None:
        flags["satellite_count"] = satellites_value
        flags["satellite_count_usable"] = satellites_value >= 4
    if uncertainty_value is not None:
        flags["uncertainty_m"] = uncertainty_value
        flags["uncertainty_usable"] = uncertainty_value <= 20.0
    if not _is_missing(fix_quality):
        normalized = str(fix_quality).strip().lower()
        flags["fix_quality"] = str(fix_quality)
        flags["fix_quality_usable"] = normalized not in {"0", "invalid", "none", "no_fix"}
    return flags


def _load_project(root: Path) -> dict[str, Any]:
    path = root / "project.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return not value
    return False


def _float_or_none(value: object) -> float | None:
    if _is_missing(value):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _int_or_none(value: object) -> int | None:
    if _is_missing(value):
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _closed_boundary() -> dict[str, bool]:
    return {
        "read_only": True,
        "runtime_safety_truth": False,
        "live_safety_api_calls_allowed": False,
        "phase1_safety_mutation_allowed": False,
        "remote_outbound_send_allowed": False,
        "hardware_control_allowed": False,
        "raw_payloads_embedded": False,
        "model_output_is_runtime_truth": False,
        "safety_api_called": False,
        "phase1_l0_l4_state_mutated": False,
        "outbound_send_performed": False,
        "live_hardware_read_performed": False,
    }
