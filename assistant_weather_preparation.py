from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

from assistant_models import AssistantSourceRef, ScoutAssistantQuery
from scout_ai_tool_planner import plan_scout_ai_tools
from scout_weather_window_tool import WEATHER_WINDOW_TOOL_ID


WEATHER_FRESH_PREPARATION_SOURCE_ID = (
    "assistant_context.weather_decision_fresh_preparation"
)


class ConnectedPreparationManager(Protocol):
    def refresh_for_assistant(
        self,
        project_id: str,
        *,
        reason: str,
    ) -> Mapping[str, Any]: ...


class WeatherDecisionFreshPreparation:
    """Refresh provider-backed weather evidence before Scout AI tool execution."""

    def __init__(
        self,
        *,
        manager: ConnectedPreparationManager,
        workspace_root: Path | str,
    ) -> None:
        self.manager = manager
        self.workspace_root = Path(workspace_root).expanduser()

    def __call__(self, query: ScoutAssistantQuery) -> AssistantSourceRef | None:
        project_id = str(query.project_id or "").strip()
        project_root = self.workspace_root / project_id if project_id else None
        plan = plan_scout_ai_tools(
            query,
            project_root=project_root,
            limit=10,
        )
        if WEATHER_WINDOW_TOOL_ID not in {
            item.tool_id for item in plan.selected_tools
        }:
            return None
        if not project_id:
            return _preparation_source(
                {
                    "status": "skipped_missing_project_id",
                    "requestActivityState": "not-started",
                    "externalApiCallsMade": False,
                    "networkCallsMade": False,
                    "cwaApiRequestAttempted": False,
                }
            )
        try:
            status = self.manager.refresh_for_assistant(
                project_id,
                reason="scout-ai-weather-decision",
            )
        except Exception as exc:
            status = {
                "status": "failed",
                "requestActivityState": "failed",
                "projectId": project_id,
                "externalApiCallsMade": False,
                "networkCallsMade": False,
                "cwaApiRequestAttempted": False,
                "lastError": {"type": type(exc).__name__},
            }
        return _preparation_source(status)


def _preparation_source(status: Mapping[str, Any]) -> AssistantSourceRef:
    public_status = _public_preparation_status(status)
    return AssistantSourceRef(
        source_id=WEATHER_FRESH_PREPARATION_SOURCE_ID,
        source_path="dashboard_connected_preparation",
        evidence_type="assistant_weather_fresh_preparation",
        selected=True,
        context_summary=public_status,
    )


def _public_preparation_status(status: Mapping[str, Any]) -> dict[str, Any]:
    state = str(status.get("status") or "unknown")
    activity = str(status.get("requestActivityState") or "unknown")
    external_calls = status.get("externalApiCallsMade")
    completed = state in {"ready", "partial"} and activity == "complete"
    if completed and external_calls is True:
        freshness = "fresh" if state == "ready" else "partial"
    elif state == "failed":
        freshness = "unavailable"
    else:
        freshness = "stale_or_unverified"
    last_error = status.get("lastError")
    last_error_type = (
        str(last_error.get("type") or "")
        if isinstance(last_error, Mapping)
        else ""
    )
    return {
        "artifact_kind": "assistant_weather_fresh_preparation",
        "artifact_version": "assistant_weather_fresh_preparation.v0",
        "status": state,
        "request_activity_state": activity,
        "prepared_before_answer": completed and external_calls is True,
        "freshness": freshness,
        "external_api_calls_made": _optional_bool(external_calls),
        "network_calls_made": _optional_bool(status.get("networkCallsMade")),
        "cwa_api_request_attempted": _optional_bool(
            status.get("cwaApiRequestAttempted")
        ),
        "completed_at": _optional_text(status.get("completedAt")),
        "component_statuses": _string_mapping(status.get("componentStatuses")),
        "failed_components": _string_list(status.get("failedComponents")),
        "artifact_refs": _safe_artifact_refs(status.get("artifactRefs")),
        "error_type": last_error_type or None,
        "candidate_only": True,
        "human_review_required": True,
        "runtime_safety_truth": False,
        "outbound_send_allowed": False,
        "hardware_control_allowed": False,
    }


def _optional_bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _string_mapping(value: object) -> dict[str, str | None]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key): (_optional_text(item) if item is not None else None)
        for key, item in value.items()
    }


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _safe_artifact_refs(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    refs: dict[str, str] = {}
    for key, item in value.items():
        ref = str(item or "").strip()
        if not ref:
            continue
        path = Path(ref)
        if path.is_absolute() or ".." in path.parts:
            continue
        refs[str(key)] = path.as_posix()
    return refs
