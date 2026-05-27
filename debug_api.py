from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, Response

from runtime_debug_log import MemoryRuntimeDebugEventLog
from runtime_debug_models import RuntimeDebugEventKind
from scout_agent_debug_projection import load_agent_trace_debug_events
from spatial_imprint_debug_projection import load_spatial_imprint_debug_events


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


class ClearableDebugEventLog(DebugEventLog, Protocol):
    def clear(self) -> int:
        ...


class DebugMessageSource(Protocol):
    def list_messages(self) -> list[Any]:
        ...


def create_debug_app(
    *,
    debug_log: DebugEventLog | None = None,
    message_source: DebugMessageSource | None = None,
    agent_trace_log_path: Path | str | None = None,
    spatial_imprint_store_path: Path | str | None = None,
    spatial_imprint_trigger_report_path: Path | str | None = None,
    debug_page_path: Path | str = DEFAULT_DEBUG_PAGE,
) -> FastAPI:
    app = FastAPI(title="Scout Phase 3.5 Debug API")
    app.include_router(
        create_debug_router(
            debug_log=debug_log,
            message_source=message_source,
            agent_trace_log_path=agent_trace_log_path,
            spatial_imprint_store_path=spatial_imprint_store_path,
            spatial_imprint_trigger_report_path=spatial_imprint_trigger_report_path,
        )
    )
    app.include_router(create_debug_page_router(debug_page_path=debug_page_path))
    return app


def create_debug_router(
    *,
    debug_log: DebugEventLog | None = None,
    message_source: DebugMessageSource | None = None,
    agent_trace_log_path: Path | str | None = None,
    spatial_imprint_store_path: Path | str | None = None,
    spatial_imprint_trigger_report_path: Path | str | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/debug", tags=["debug"])
    resolved_log = debug_log or MemoryRuntimeDebugEventLog()

    @router.get("")
    def debug_root() -> dict[str, Any]:
        events = _combined_events(
            resolved_log,
            agent_trace_log_path=agent_trace_log_path,
            spatial_imprint_store_path=spatial_imprint_store_path,
            spatial_imprint_trigger_report_path=spatial_imprint_trigger_report_path,
        )
        messages = _messages(message_source, events)
        return {
            "status": "ok",
            "surface": "phase35-runtime-debug",
            "read_only": True,
            "event_count": len(events),
            "agent_tool_count": _agent_tool_count(events),
            "spatial_imprint_event_count": _spatial_imprint_event_count(events),
            "message_count": len(messages),
            "debug_boundary": _debug_boundary(),
        }

    @router.get("/events")
    def events(
        kind: RuntimeDebugEventKind | None = None,
        since_sequence: int | None = Query(default=None, ge=0),
        limit: int | None = Query(default=None, ge=0),
    ) -> dict[str, Any]:
        events_payload = _combined_events(
            resolved_log,
            agent_trace_log_path=agent_trace_log_path,
            spatial_imprint_store_path=spatial_imprint_store_path,
            spatial_imprint_trigger_report_path=spatial_imprint_trigger_report_path,
            kind=kind,
            since_sequence=since_sequence,
            limit=limit,
        )
        return {
            "events": [
                event.model_dump(mode="json")
                for event in events_payload
            ],
            "debug_boundary": _debug_boundary(),
        }

    @router.get("/state")
    def state() -> dict[str, Any]:
        events = _combined_events(
            resolved_log,
            agent_trace_log_path=agent_trace_log_path,
            spatial_imprint_store_path=spatial_imprint_store_path,
            spatial_imprint_trigger_report_path=spatial_imprint_trigger_report_path,
        )
        messages = _messages(message_source, events)
        latest_completed = _latest_event_payload(events, "debug_session_completed")
        latest_safety = _latest_event_payload(events, "safety_event_emitted")
        latest_provider = _latest_event_payload(events, "provider_status_recorded")
        latest_bridge = _latest_event_payload(events, "phase3_bridge_result")
        latest_agent_tool = _latest_event_payload(events, "agent_tool_invocation")
        latest_spatial_imprint = _latest_spatial_imprint_payload(events)
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
            "agent_tool_count": _agent_tool_count(events),
            "latest_agent_tool": latest_agent_tool,
            "spatial_imprint_event_count": _spatial_imprint_event_count(events),
            "latest_spatial_imprint": latest_spatial_imprint,
            "provider_status": latest_provider,
            "phase3_bridge": latest_bridge,
            "message_count": len(messages),
            "debug_boundary": _debug_boundary(),
        }

    @router.get("/monitoring")
    def monitoring() -> dict[str, Any]:
        events = _combined_events(
            resolved_log,
            agent_trace_log_path=agent_trace_log_path,
            spatial_imprint_store_path=spatial_imprint_store_path,
            spatial_imprint_trigger_report_path=spatial_imprint_trigger_report_path,
        )
        messages = _messages(message_source, events)
        return _monitoring_center_payload(events, messages)

    @router.get("/messages")
    def messages(state: str | None = None) -> dict[str, Any]:
        events = _combined_events(
            resolved_log,
            agent_trace_log_path=agent_trace_log_path,
            spatial_imprint_store_path=spatial_imprint_store_path,
            spatial_imprint_trigger_report_path=spatial_imprint_trigger_report_path,
        )
        messages_payload = _messages(message_source, events)
        if state is not None:
            messages_payload = [
                message for message in messages_payload if message.get("state") == state
            ]
        return {
            "messages": messages_payload,
            "debug_boundary": _debug_boundary(),
        }

    @router.api_route("/clear", methods=["POST"])
    def clear_debug_projection(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not (payload or {}).get("confirm_debug_projection_clear"):
            raise HTTPException(
                status_code=400,
                detail="confirm_debug_projection_clear=true is required",
            )
        if not hasattr(resolved_log, "clear"):
            raise HTTPException(status_code=409, detail="debug log does not support clear")
        cleared_count = resolved_log.clear()
        return {
            "status": "cleared",
            "cleared_event_count": cleared_count,
            "agent_trace_cleared": False,
            "spatial_imprint_artifacts_cleared": False,
            "debug_boundary": _debug_clear_boundary(),
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


def _combined_events(
    debug_log: DebugEventLog,
    *,
    agent_trace_log_path: Path | str | None,
    spatial_imprint_store_path: Path | str | None,
    spatial_imprint_trigger_report_path: Path | str | None,
    kind: RuntimeDebugEventKind | None = None,
    since_sequence: int | None = None,
    limit: int | None = None,
) -> list[Any]:
    runtime_events = list(debug_log.list_events())
    sequence_offset = max(
        [int(getattr(event, "sequence", 0) or 0) for event in runtime_events],
        default=0,
    )
    agent_events = load_agent_trace_debug_events(
        agent_trace_log_path,
        sequence_offset=sequence_offset,
    )
    spatial_sequence_offset = max(
        [int(getattr(event, "sequence", 0) or 0) for event in [*runtime_events, *agent_events]],
        default=sequence_offset,
    )
    spatial_events = load_spatial_imprint_debug_events(
        store_path=spatial_imprint_store_path,
        trigger_report_path=spatial_imprint_trigger_report_path,
        sequence_offset=spatial_sequence_offset,
    )
    events: list[Any] = [*runtime_events, *agent_events, *spatial_events]
    if kind is not None:
        events = [event for event in events if event.kind == kind]
    if since_sequence is not None:
        events = [event for event in events if event.sequence > since_sequence]
    events = sorted(events, key=lambda event: (event.sequence, event.timestamp, event.event_id))
    if limit is not None:
        if limit <= 0:
            return []
        events = events[-limit:]
    return events


def _agent_tool_count(events: list[Any]) -> int:
    return sum(1 for event in events if event.kind == "agent_tool_invocation")


def _spatial_imprint_event_count(events: list[Any]) -> int:
    return sum(1 for event in events if str(event.kind).startswith("spatial_imprint_"))


def _latest_spatial_imprint_payload(events: list[Any]) -> dict[str, Any]:
    for event in reversed(events):
        if str(event.kind).startswith("spatial_imprint_"):
            return dict(event.payload)
    return {}


def _monitoring_center_payload(events: list[Any], messages: list[dict[str, Any]]) -> dict[str, Any]:
    agent_events = [event for event in events if event.kind == "agent_tool_invocation"]
    release_events = [
        event
        for event in agent_events
        if str(event.payload.get("tool_id", "")).startswith("scout.checks.")
    ]
    map_events = [
        event
        for event in agent_events
        if str(event.payload.get("tool_id", "")).startswith("scout.map.")
        or event.payload.get("tool_id") == "scout.pretrip.prepare_layers"
    ]
    voice_events = [
        event
        for event in events
        if event.kind in {"voice_cue_queued", "voice_cue_state_changed"}
    ]
    outbound_events = [
        event
        for event in events
        if event.kind in {"outbound_message_queued", "outbound_message_state_changed"}
    ]
    spatial_events = [
        event for event in events if str(event.kind).startswith("spatial_imprint_")
    ]
    provider_events = [
        event for event in events if event.kind == "provider_status_recorded"
    ]
    failed_agent_events = [
        event
        for event in agent_events
        if str(event.payload.get("status", "")).endswith(("failed", "blocked", "partial"))
        or event.severity in {"warning", "error"}
    ]
    latest_agent = _payload_summary(agent_events[-1]) if agent_events else {}
    latest_release = _payload_summary(release_events[-1]) if release_events else {}
    latest_map = _payload_summary(map_events[-1]) if map_events else {}
    latest_voice = _payload_summary(voice_events[-1]) if voice_events else {}
    latest_spatial = _payload_summary(spatial_events[-1]) if spatial_events else {}
    latest_provider = _payload_summary(provider_events[-1]) if provider_events else {}
    latest_message = messages[-1] if messages else {}
    return {
        "artifact_kind": "scout_debug_monitoring_center",
        "status": "ok",
        "surface": "phase35-runtime-debug-monitoring",
        "read_only": True,
        "counts": {
            "event_count": len(events),
            "agent_tool_count": len(agent_events),
            "agent_tool_attention_count": len(failed_agent_events),
            "release_check_count": len(release_events),
            "map_preparation_count": len(map_events),
            "provider_status_count": len(provider_events),
            "voice_event_count": len(voice_events),
            "outbound_event_count": len(outbound_events),
            "mock_message_count": len(messages),
            "spatial_imprint_event_count": len(spatial_events),
        },
        "sections": {
            "agent_tools": {
                "latest": latest_agent,
                "attention": [_payload_summary(event) for event in failed_agent_events[-5:]],
            },
            "release_checks": {"latest": latest_release},
            "map_preparation": {"latest": latest_map},
            "hardware_readiness": {
                "latest_provider_status": latest_provider,
                "context_endpoint": "/admin/hardware-readiness/context",
                "source_of_truth": "hardware-readiness",
            },
            "voice": {"latest": latest_voice},
            "outbound": {
                "latest_message": latest_message,
                "latest_event": _payload_summary(outbound_events[-1]) if outbound_events else {},
            },
            "spatial_imprints": {"latest": latest_spatial},
        },
        "debug_boundary": _debug_boundary(),
    }


def _payload_summary(event: Any) -> dict[str, Any]:
    payload = dict(event.payload)
    return {
        "event_id": event.event_id,
        "sequence": event.sequence,
        "kind": event.kind,
        "severity": event.severity,
        "summary": event.summary,
        "subject_ref": event.subject_ref,
        "tool_id": payload.get("tool_id"),
        "status": payload.get("status"),
        "mode": payload.get("mode"),
        "returncode": payload.get("returncode"),
        "imprint_id": payload.get("imprint_id"),
        "message_id": payload.get("message_id"),
        "cue_id": payload.get("cue_id"),
        "provider_ref": payload.get("provider_ref") or payload.get("provider"),
        "boundary": payload.get("boundary") or {},
    }


def _debug_boundary() -> dict[str, bool]:
    return {
        "read_only": True,
        "phase1_mutation_allowed": False,
        "phase2_writeback_allowed": False,
        "real_outbound_transport_allowed": False,
    }


def _debug_clear_boundary() -> dict[str, bool]:
    return {
        "debug_projection_cleared": True,
        "runtime_state_mutation_allowed": False,
        "phase1_mutation_allowed": False,
        "phase2_writeback_allowed": False,
        "real_outbound_transport_allowed": False,
        "incident_store_mutation_allowed": False,
        "hardware_control_allowed": False,
    }
