from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from fastapi import APIRouter, FastAPI, Query
from fastapi.responses import HTMLResponse, Response

from runtime_debug_log import MemoryRuntimeDebugEventLog
from runtime_debug_models import RuntimeDebugEventKind


DEFAULT_DEBUG_PAGE = Path(__file__).resolve().parent / "docs" / "admin" / "phase-3-5-runtime-debug.html"
DEFAULT_ASSISTANT_UI_SCRIPT = Path(__file__).resolve().parent / "docs" / "admin" / "scout-assistant-ui.js"


class DebugEventLog(Protocol):
    def list_events(
        self,
        *,
        kind: RuntimeDebugEventKind | None = None,
        since_sequence: int | None = None,
        limit: int | None = None,
    ) -> list[Any]:
        ...


class DebugMessageSource(Protocol):
    def list_messages(self) -> list[Any]:
        ...


def create_debug_app(
    *,
    debug_log: DebugEventLog | None = None,
    message_source: DebugMessageSource | None = None,
    debug_page_path: Path | str = DEFAULT_DEBUG_PAGE,
) -> FastAPI:
    app = FastAPI(title="Scout Phase 3.5 Debug API")
    app.include_router(create_debug_router(debug_log=debug_log, message_source=message_source))
    app.include_router(create_debug_page_router(debug_page_path=debug_page_path))
    return app


def create_debug_router(
    *,
    debug_log: DebugEventLog | None = None,
    message_source: DebugMessageSource | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/debug", tags=["debug"])
    resolved_log = debug_log or MemoryRuntimeDebugEventLog()

    @router.get("")
    def debug_root() -> dict[str, Any]:
        events = resolved_log.list_events()
        messages = _messages(message_source, events)
        return {
            "status": "ok",
            "surface": "phase35-runtime-debug",
            "read_only": True,
            "event_count": len(events),
            "message_count": len(messages),
            "debug_boundary": _debug_boundary(),
        }

    @router.get("/events")
    def events(
        kind: RuntimeDebugEventKind | None = None,
        since_sequence: int | None = Query(default=None, ge=0),
        limit: int | None = Query(default=None, ge=0),
    ) -> dict[str, Any]:
        return {
            "events": [
                event.model_dump(mode="json")
                for event in resolved_log.list_events(
                    kind=kind,
                    since_sequence=since_sequence,
                    limit=limit,
                )
            ],
            "debug_boundary": _debug_boundary(),
        }

    @router.get("/state")
    def state() -> dict[str, Any]:
        events = resolved_log.list_events()
        messages = _messages(message_source, events)
        latest_completed = _latest_event_payload(events, "debug_session_completed")
        latest_safety = _latest_event_payload(events, "safety_event_emitted")
        latest_provider = _latest_event_payload(events, "provider_status_recorded")
        latest_bridge = _latest_event_payload(events, "phase3_bridge_result")
        safety_level = (
            latest_completed.get("safety_level")
            or latest_safety.get("safety_level")
            or "unknown"
        )
        return {
            "debug_session_id": events[-1].session_id if events else None,
            "runtime_profile": "phase35-debug",
            "safety_level": safety_level,
            "latest_transition": _latest_event_payload(events, "safety_transition_recorded") or None,
            "observations_processed": latest_completed.get("observations_processed"),
            "event_count": len(events),
            "provider_status": latest_provider,
            "phase3_bridge": latest_bridge,
            "message_count": len(messages),
            "debug_boundary": _debug_boundary(),
        }

    @router.get("/messages")
    def messages(state: str | None = None) -> dict[str, Any]:
        events = resolved_log.list_events()
        messages_payload = _messages(message_source, events)
        if state is not None:
            messages_payload = [
                message for message in messages_payload if message.get("state") == state
            ]
        return {
            "messages": messages_payload,
            "debug_boundary": _debug_boundary(),
        }

    return router


def create_debug_page_router(
    *,
    debug_page_path: Path | str = DEFAULT_DEBUG_PAGE,
    assistant_ui_script_path: Path | str = DEFAULT_ASSISTANT_UI_SCRIPT,
) -> APIRouter:
    router = APIRouter(prefix="/admin", tags=["debug"])
    resolved_debug_page_path = Path(debug_page_path)
    resolved_assistant_ui_script_path = Path(assistant_ui_script_path)

    @router.get("/debug", response_class=HTMLResponse)
    def debug_page() -> str:
        return resolved_debug_page_path.read_text(encoding="utf-8")

    @router.get("/scout-assistant-ui.js")
    def assistant_ui_script() -> Response:
        return Response(
            resolved_assistant_ui_script_path.read_text(encoding="utf-8"),
            media_type="application/javascript",
        )

    return router


def _messages(
    message_source: DebugMessageSource | None,
    events: list[Any] | None = None,
) -> list[dict[str, Any]]:
    if message_source is None:
        return _messages_from_outbound_events(events or [])
    return [
        message.model_dump(mode="json") if hasattr(message, "model_dump") else dict(message)
        for message in message_source.list_messages()
    ]


def _messages_from_outbound_events(events: list[Any]) -> list[dict[str, Any]]:
    messages_by_id: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.kind not in {"outbound_message_queued", "outbound_message_state_changed"}:
            continue
        payload = dict(event.payload)
        message_id = payload.get("message_id") or event.subject_ref
        if not message_id:
            continue
        current = messages_by_id.get(message_id, {})
        created_at = current.get("created_at") or event.timestamp
        boundary = {
            "real_sos_sent": False,
            "real_sms_sent": False,
            "real_satellite_sent": False,
        }
        boundary.update(dict(payload.get("boundary") or {}))
        messages_by_id[message_id] = {
            "message_id": message_id,
            "session_id": current.get("session_id") or event.session_id,
            "created_at": created_at,
            "updated_at": event.timestamp,
            "category": payload.get("category") or current.get("category") or "remote_status",
            "transport": payload.get("transport") or current.get("transport") or "mock",
            "state": payload.get("state") or payload.get("status") or current.get("state") or "queued",
            "recipient_ref": payload.get("recipient_ref")
            or current.get("recipient_ref")
            or "debug_recipient.unknown",
            "subject_ref": payload.get("subject_ref") or current.get("subject_ref") or event.subject_ref,
            "body_preview": payload.get("body_preview")
            or current.get("body_preview")
            or event.summary,
            "payload": payload.get("payload") or current.get("payload") or {},
            "boundary": boundary,
        }
    return list(messages_by_id.values())


def _latest_event_payload(events: list[Any], kind: str) -> dict[str, Any]:
    for event in reversed(events):
        if event.kind == kind:
            return dict(event.payload)
    return {}


def _debug_boundary() -> dict[str, bool]:
    return {
        "read_only": True,
        "phase1_mutation_allowed": False,
        "phase2_writeback_allowed": False,
        "real_outbound_transport_allowed": False,
    }
