"""Deterministic application router for Scout AI OS requests."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from scout.schemas.permissions import PermissionDecision
from scout.services.permission_gate import PermissionGate


UI_ACTION_TOOL_ID = "scout.ui.action_plan"
UI_ACTION_ARTIFACT_VERSION = "scout_ui_action_plan.v0"
ROUTE_READINESS_TOOL_ID = "scout.ai.route_readiness.assess.v0"


class RequestRoute(str, Enum):
    UI_OPERATION = "ui_operation"
    EVIDENCE_QUERY = "evidence_query"
    ROUTE_READINESS = "route_readiness"
    WORKFLOW_AUTOMATION = "workflow_automation"
    BOUNDARY_EXPLAINER = "boundary_explainer"


@dataclass(frozen=True)
class RoutedRequest:
    route_class: RequestRoute
    reason: str
    tool_id: str | None = None
    output_artifact_version: str | None = None
    surface: str | None = None
    artifact: dict[str, Any] | None = None
    permission: PermissionDecision | None = None

    def model_dump(self) -> dict[str, Any]:
        return {
            "route_class": self.route_class.value,
            "reason": self.reason,
            "tool_id": self.tool_id,
            "output_artifact_version": self.output_artifact_version,
            "surface": self.surface,
            "artifact": self.artifact,
            "permission": (
                self.permission.model_dump(mode="json") if self.permission else None
            ),
        }


class ApplicationRouter:
    """Route requests before model synthesis or workflow compilation.

    The router is intentionally deterministic. First-party UI actions are
    allowlisted and can be planned before a general model answer, while
    workflow automation continues through the existing compiler and permission
    gate.
    """

    def __init__(self, permission_gate: PermissionGate | None = None) -> None:
        self._permission_gate = permission_gate or PermissionGate()

    def route(
        self,
        user_text: str,
        *,
        active_context: dict[str, Any] | None = None,
    ) -> RoutedRequest:
        context = dict(active_context or {})
        request = user_text.strip()
        surface = _surface_from_context_or_text(context, request)

        if _looks_like_boundary_request(request):
            artifact = _build_ui_action_plan(surface, request) if surface else None
            permission = (
                self._permission_gate.evaluate_ui_action_plan(artifact)
                if artifact
                else _boundary_denial()
            )
            return RoutedRequest(
                route_class=RequestRoute.BOUNDARY_EXPLAINER,
                reason="Request asks for safety, outbound, runtime, or hardware action outside the UI bridge boundary.",
                tool_id=UI_ACTION_TOOL_ID if artifact else None,
                output_artifact_version=UI_ACTION_ARTIFACT_VERSION if artifact else None,
                surface=surface,
                artifact=artifact,
                permission=permission,
            )

        if _looks_like_ui_operation(request, context):
            if surface is None:
                surface = "pretrip"
            artifact = _build_ui_action_plan(surface, request)
            return RoutedRequest(
                route_class=RequestRoute.UI_OPERATION,
                reason="Request matches a first-party session-local UI operation.",
                tool_id=UI_ACTION_TOOL_ID,
                output_artifact_version=UI_ACTION_ARTIFACT_VERSION,
                surface=surface,
                artifact=artifact,
                permission=self._permission_gate.evaluate_ui_action_plan(artifact),
            )

        if _looks_like_route_readiness_request(request):
            return RoutedRequest(
                route_class=RequestRoute.ROUTE_READINESS,
                reason="Request asks for route readiness, live position, or route edge assessment.",
                tool_id=ROUTE_READINESS_TOOL_ID,
                output_artifact_version=ROUTE_READINESS_TOOL_ID,
                permission=_read_only_allowed("route readiness request"),
            )

        if _looks_like_workflow_request(request):
            return RoutedRequest(
                route_class=RequestRoute.WORKFLOW_AUTOMATION,
                reason="Request asks Scout AI OS to install or manage workflow automation.",
                permission=_read_only_allowed("workflow compiler route selected"),
            )

        return RoutedRequest(
            route_class=RequestRoute.EVIDENCE_QUERY,
            reason="Request should use read-only context, tool planning, and evidence collection.",
            permission=_read_only_allowed("read-only evidence query"),
        )


def _build_ui_action_plan(surface: str, request_text: str) -> dict[str, Any]:
    from scout.ui_action_plan import build_scout_ui_action_plan

    return build_scout_ui_action_plan(
        surface=surface,
        request_text=request_text,
    )


def _surface_from_context_or_text(
    context: dict[str, Any],
    request_text: str,
) -> str | None:
    candidates = [
        context.get("surface"),
        context.get("ui_surface"),
        context.get("admin_surface"),
        context.get("route"),
        context.get("path"),
    ]
    for candidate in candidates:
        surface = _normalize_surface(candidate)
        if surface:
            return surface

    text = request_text.casefold()
    if "debug" in text or "timeline" in text or "debug_event" in text:
        return "debug"
    if "after-action" in text or "after action" in text or "admin" in text:
        return "admin"
    if "pretrip" in text or "pre-trip" in text or "review" in text or "cp" in text:
        return "pretrip"
    return None


def _normalize_surface(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold().replace("-", "_")
    aliases = {
        "/admin": "admin",
        "/admin/debug": "debug",
        "/admin/pretrip": "pretrip",
        "admin_after_action": "admin",
        "after_action": "admin",
        "afteraction": "admin",
        "runtime_debug": "debug",
        "admin_debug": "debug",
        "pre_trip": "pretrip",
        "admin_pretrip": "pretrip",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized in {"admin", "debug", "pretrip"}:
        return normalized
    return None


def _looks_like_ui_operation(request_text: str, context: dict[str, Any]) -> bool:
    if str(context.get("request_kind") or "").casefold() in {
        "ui_operation",
        "ui_action",
        "action_plan",
    }:
        return True
    text = request_text.casefold()
    return _has_any(
        text,
        (
            "圖層",
            "地圖",
            "底圖",
            "影像",
            "osm",
            "rudy",
            "zoom",
            "fit route",
            "縮放",
            "放大",
            "縮小",
            "risk score",
            "baseline",
            "calibrated",
            "delta",
            "timeline",
            "debug_event",
            "selected evidence",
            "目前選取",
            "review",
            "頁籤",
            "workspace",
            "搜尋",
            "cp003",
            "checkpoint",
            "新增一個 cp",
            "刪除目前選取的 cp",
        ),
    )


def _looks_like_boundary_request(request_text: str) -> bool:
    return _has_any(
        request_text.casefold(),
        (
            "/safety/",
            "sos",
            "sms",
            "satellite",
            "telegram",
            "beacon",
            "發送 sos",
            "發送sms",
            "發送 sms",
            "通報",
            "報案",
            "觸發ln",
            "觸發 ln",
            "runtime mutation",
            "hardware control",
            "gpioset",
        ),
    )


def _looks_like_route_readiness_request(request_text: str) -> bool:
    text = request_text.casefold()
    return _has_any(
        text,
        (
            "route readiness",
            "route_readiness",
            "路線準備",
            "是否可以出發",
            "能不能出發",
            "偏離路線",
            "現在是不是偏離",
            "配速",
            "補水",
            "補給",
            "水剩多少",
            "今天的體能",
            "太硬",
        ),
    )


def _looks_like_workflow_request(request_text: str) -> bool:
    text = request_text.casefold()
    return _has_any(
        text,
        (
            "remind me",
            "reminder",
            "notify me",
            "提醒我",
            "通知我",
            "每次",
            "每天",
            "每週",
            "自動",
            "automation",
            "workflow",
            "monitor",
        ),
    )


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _read_only_allowed(reason: str) -> PermissionDecision:
    return PermissionDecision(
        allowed=True,
        requires_user_approval=False,
        reason=reason,
        user_message="Routed without changing Scout runtime safety truth.",
    )


def _boundary_denial() -> PermissionDecision:
    return PermissionDecision(
        allowed=False,
        requires_user_approval=False,
        reason="request is outside Scout AI UI operation boundary",
        user_message=(
            "Scout AI cannot perform safety mutation, outbound send, runtime mutation, "
            "or hardware control through this route."
        ),
    )


__all__ = [
    "ApplicationRouter",
    "ROUTE_READINESS_TOOL_ID",
    "RequestRoute",
    "RoutedRequest",
    "UI_ACTION_ARTIFACT_VERSION",
    "UI_ACTION_TOOL_ID",
]
