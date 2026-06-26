"""FastAPI app for the Mac Scout AI chat interface."""

from __future__ import annotations

from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal, Protocol

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from scout.mac_chat.client import (
    DEFAULT_SCOUT_SERVER_URL,
    ScoutServerClient,
    normalize_server_url,
)


Surface = Literal["admin", "debug", "pretrip"]


class MacChatLocalFallback(Protocol):
    def answer(self, request: "MacChatRequest", active_context: dict[str, Any]) -> dict[str, Any]:
        ...


class MacChatRequest(BaseModel):
    message: str = Field(min_length=1)
    user_id: str = Field(default="mac-chat-user", min_length=1)
    surface: Surface = "pretrip"
    active_context: dict[str, Any] = Field(default_factory=dict)


def create_mac_chat_app(
    *,
    target_url: str = DEFAULT_SCOUT_SERVER_URL,
    scout_client: ScoutServerClient | None = None,
    local_fallback_enabled: bool = False,
    local_fallback_provider: MacChatLocalFallback | None = None,
) -> FastAPI:
    """Create the Mac-local UI/proxy app for a remote Scout AI OS server."""

    normalized_target_url = normalize_server_url(target_url)
    client = scout_client or ScoutServerClient(normalized_target_url)
    static_root = _static_root()

    app = FastAPI(title="Scout AI Mac Chat", version="0.1.0")
    app.state.scout_target_url = normalized_target_url
    app.state.scout_client = client
    app.state.local_fallback_enabled = local_fallback_enabled
    app.state.local_fallback_provider = local_fallback_provider
    app.mount("/static", StaticFiles(directory=static_root), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(static_root / "index.html")

    @app.get("/api/config")
    def config() -> dict[str, Any]:
        return {
            "target_url": normalized_target_url,
            "surfaces": ["pretrip", "debug", "admin"],
            "default_surface": "pretrip",
            "local_fallback_enabled": local_fallback_enabled,
            "boundary": _boundary(local_fallback_enabled=local_fallback_enabled),
        }

    @app.get("/api/server")
    def server_status() -> dict[str, Any]:
        result = client.capabilities()
        capabilities = []
        if result.payload and isinstance(result.payload.get("capabilities"), list):
            capabilities = result.payload["capabilities"]
        capability_names = [
            str(item.get("name"))
            for item in capabilities
            if isinstance(item, dict) and item.get("name")
        ]
        return {
            "connected": result.ok,
            "target_url": normalized_target_url,
            "status_code": result.status_code,
            "latency_ms": result.elapsed_ms,
            "error": result.error,
            "capability_count": len(capability_names),
            "ui_action_capability_present": "scout.ui.action_plan" in capability_names,
            "capabilities": capability_names[:24],
            "local_fallback_enabled": local_fallback_enabled,
            "local_fallback_available": local_fallback_provider is not None,
            "boundary": _boundary(local_fallback_enabled=local_fallback_enabled),
        }

    @app.post("/api/chat")
    def chat(payload: MacChatRequest) -> dict[str, Any]:
        active_context = {
            **payload.active_context,
            "surface": payload.surface,
            "client": "scout_mac_chat",
            "client_timestamp": datetime.now(UTC).isoformat(),
        }
        result = client.create_request(
            user_id=payload.user_id,
            user_text=payload.message,
            active_context=active_context,
        )
        response_payload = result.payload or {}
        if not result.ok and local_fallback_enabled and local_fallback_provider is not None:
            return _local_fallback_chat_response(
                fallback_provider=local_fallback_provider,
                payload=payload,
                active_context=active_context,
                target_url=normalized_target_url,
                remote_result=result,
                local_fallback_enabled=local_fallback_enabled,
            )
        return {
            "ok": result.ok,
            "response_source": "scout_hardware" if result.ok else "scout_hardware_error",
            "target_url": normalized_target_url,
            "status_code": result.status_code,
            "latency_ms": result.elapsed_ms,
            "error": result.error,
            "request": {
                "user_id": payload.user_id,
                "surface": payload.surface,
                "message": payload.message,
                "active_context": active_context,
            },
            "response": response_payload,
            "summary": _summarize_response(response_payload, result.error),
            "boundary": _boundary(local_fallback_enabled=local_fallback_enabled),
        }

    return app


def _local_fallback_chat_response(
    *,
    fallback_provider: MacChatLocalFallback,
    payload: MacChatRequest,
    active_context: dict[str, Any],
    target_url: str,
    remote_result: Any,
    local_fallback_enabled: bool,
) -> dict[str, Any]:
    try:
        fallback_payload = fallback_provider.answer(payload, active_context)
    except Exception as exc:
        error = (
            f"{remote_result.error or 'Scout server unavailable'}; "
            f"Mac local fallback unavailable: {_safe_exception_label(exc)}"
        )
        return {
            "ok": False,
            "response_source": "unavailable",
            "target_url": target_url,
            "status_code": remote_result.status_code,
            "latency_ms": remote_result.elapsed_ms,
            "error": error,
            "remote_error": remote_result.error,
            "local_fallback_error": _safe_exception_label(exc),
            "request": {
                "user_id": payload.user_id,
                "surface": payload.surface,
                "message": payload.message,
                "active_context": active_context,
            },
            "response": {},
            "summary": {
                "status": "disconnected",
                "title": "Scout server unavailable",
                "body": error,
            },
            "boundary": _boundary(local_fallback_enabled=local_fallback_enabled),
        }

    return {
        "ok": True,
        "response_source": "mac_local_pydantic_ai_v2",
        "target_url": target_url,
        "status_code": remote_result.status_code,
        "latency_ms": remote_result.elapsed_ms,
        "error": None,
        "remote_error": remote_result.error,
        "request": {
            "user_id": payload.user_id,
            "surface": payload.surface,
            "message": payload.message,
            "active_context": active_context,
        },
        "response": fallback_payload,
        "summary": _summarize_response(fallback_payload, None),
        "boundary": _boundary(local_fallback_enabled=local_fallback_enabled),
    }


def _summarize_response(payload: dict[str, Any], error: str | None) -> dict[str, Any]:
    if error:
        return {
            "status": "disconnected",
            "title": "Scout server unavailable",
            "body": error,
        }

    status = str(payload.get("status") or "unknown")
    route = payload.get("route") if isinstance(payload.get("route"), dict) else {}
    permission = route.get("permission") if isinstance(route.get("permission"), dict) else {}
    action_plan = (
        payload.get("ui_action_plan")
        if isinstance(payload.get("ui_action_plan"), dict)
        else None
    )
    workflow_id = payload.get("workflow_id")

    if action_plan:
        actions = action_plan.get("actions") if isinstance(action_plan.get("actions"), list) else []
        first_action = actions[0] if actions and isinstance(actions[0], dict) else {}
        return {
            "status": status,
            "title": "UI action plan",
            "body": first_action.get("label") or permission.get("user_message") or status,
            "route_class": route.get("route_class"),
            "tool_id": route.get("tool_id"),
            "action_kind": first_action.get("action_kind"),
            "requires_confirmation": bool(first_action.get("requires_confirmation")),
        }

    if workflow_id:
        return {
            "status": status,
            "title": "Workflow",
            "body": str(payload.get("message") or "Workflow response returned."),
            "workflow_id": workflow_id,
            "route_class": route.get("route_class"),
        }

    return {
        "status": status,
        "title": status.replace("_", " ").title(),
        "body": str(payload.get("message") or "Scout AI server returned a response."),
        "route_class": route.get("route_class"),
        "tool_id": route.get("tool_id"),
    }


def _boundary(*, local_fallback_enabled: bool = False) -> dict[str, bool]:
    return {
        "mac_ui_local_only": True,
        "remote_scout_server_required": not local_fallback_enabled,
        "mac_local_pydantic_ai_fallback_enabled": local_fallback_enabled,
        "model_output_is_runtime_truth": False,
        "local_fallback_model_output_is_runtime_truth": False,
        "safety_api_called_by_mac_ui": False,
        "safety_api_called_by_local_fallback": False,
        "phase1_l0_l4_state_mutated_by_mac_ui": False,
        "phase1_l0_l4_state_mutated_by_local_fallback": False,
        "outbound_send_performed_by_mac_ui": False,
        "outbound_send_performed_by_local_fallback": False,
        "hardware_control_performed_by_mac_ui": False,
        "hardware_control_performed_by_local_fallback": False,
    }


def _safe_exception_label(exc: Exception) -> str:
    text = str(exc).replace("\n", " ").strip()
    for marker in ("OPENROUTER_API_KEY=", "OPENAI_API_KEY="):
        if marker in text:
            text = text.split(marker, 1)[0] + f"{marker}<redacted>"
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def _static_root() -> Path:
    return Path(str(files("scout.mac_chat") / "static"))


__all__ = ["create_mac_chat_app"]
