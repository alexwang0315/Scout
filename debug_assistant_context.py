from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from runtime_debug_models import RuntimeDebugEventKind


class RuntimeDebugEventLog(Protocol):
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


def build_debug_assistant_context(
    event_log: RuntimeDebugEventLog,
    *,
    selected_event_id: str | None = None,
    message_source: DebugMessageSource | None = None,
    max_events: int = 50,
    max_messages: int = 20,
) -> dict[str, Any]:
    events = event_log.list_events(limit=max_events)
    messages = _list_messages(message_source, max_messages=max_messages)
    source_path = _event_log_source_path(event_log)
    timeline = [_event_summary(event, source_path=source_path) for event in events]
    selected_event = _selected_event(timeline, selected_event_id)
    message_summaries = [_message_summary(message) for message in messages]

    sources = _dedupe_sources(
        [*_source_refs(timeline), *_source_refs(message_summaries)]
    )
    return {
        "surface": "debug",
        "context_kind": "assistant_context",
        "read_only": True,
        "bounded": True,
        "auditable": True,
        "boundary": _boundary(),
        "summary": {
            "event_count": len(timeline),
            "message_count": len(message_summaries),
            "selected_event_id": selected_event_id,
            "latest_safety_level": _latest_payload_value(
                events,
                keys=("safety_level", "level"),
                kinds=("debug_session_completed", "safety_event_emitted"),
            ),
            "latest_provider_status": _latest_payload(events, "provider_status_recorded"),
            "latest_bridge_result": _latest_payload(events, "phase3_bridge_result"),
        },
        "selected_event": selected_event,
        "timeline": timeline,
        "messages": message_summaries,
        "sources": sources,
        "limitations": [
            "Context is built from bounded debug events and optional mock message summaries.",
            "No runtime state, outbound transport, or writeback target is mutated.",
        ],
    }


def _event_summary(event: Any, *, source_path: str) -> dict[str, Any]:
    payload = dict(getattr(event, "payload", {}) or {})
    return {
        "event_id": getattr(event, "event_id", None),
        "session_id": getattr(event, "session_id", None),
        "timestamp": getattr(event, "timestamp", None),
        "sequence": getattr(event, "sequence", None),
        "kind": getattr(event, "kind", None),
        "phase": getattr(event, "phase", None),
        "severity": getattr(event, "severity", None),
        "subject_ref": getattr(event, "subject_ref", None),
        "summary": _truncate(getattr(event, "summary", None), limit=280),
        "payload": _compact_value(payload),
        "source_id": getattr(event, "event_id", None),
        "source_path": source_path,
        "evidence_type": "runtime_debug_event",
    }


def _message_summary(message: Any) -> dict[str, Any]:
    payload = _as_dict(message)
    boundary = dict(payload.get("boundary") or {})
    return {
        "message_id": payload.get("message_id"),
        "transport": payload.get("transport"),
        "state": payload.get("state"),
        "category": payload.get("category"),
        "recipient_ref": payload.get("recipient_ref"),
        "subject_ref": payload.get("subject_ref"),
        "body_preview": _truncate(payload.get("body_preview"), limit=280),
        "boundary": {
            "real_sos_sent": bool(boundary.get("real_sos_sent", False)),
            "real_sms_sent": bool(boundary.get("real_sms_sent", False)),
            "real_satellite_sent": bool(boundary.get("real_satellite_sent", False)),
        },
        "source_id": payload.get("message_id"),
        "source_path": "debug_message_source",
        "evidence_type": "debug_message",
    }


def _list_messages(
    message_source: DebugMessageSource | None,
    *,
    max_messages: int,
) -> list[Any]:
    if message_source is None or max_messages <= 0:
        return []
    return list(message_source.list_messages())[-max_messages:]


def _selected_event(
    timeline: list[dict[str, Any]],
    selected_event_id: str | None,
) -> dict[str, Any] | None:
    if selected_event_id is None:
        return timeline[-1] if timeline else None
    for item in timeline:
        if item.get("event_id") == selected_event_id:
            return item
    return None


def _latest_payload(events: list[Any], kind: str) -> dict[str, Any] | None:
    for event in reversed(events):
        if getattr(event, "kind", None) == kind:
            return _compact_value(dict(getattr(event, "payload", {}) or {}))
    return None


def _latest_payload_value(
    events: list[Any],
    *,
    keys: tuple[str, ...],
    kinds: tuple[str, ...],
) -> Any:
    for event in reversed(events):
        if getattr(event, "kind", None) not in kinds:
            continue
        payload = dict(getattr(event, "payload", {}) or {})
        for key in keys:
            if key in payload:
                return payload[key]
    return None


def _source_refs(items: list[dict[str, Any]]) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for item in items:
        source_id = item.get("source_id")
        source_path = item.get("source_path")
        evidence_type = item.get("evidence_type")
        if source_id and source_path and evidence_type:
            refs.append(
                {
                    "source_id": str(source_id),
                    "source_path": str(source_path),
                    "evidence_type": str(evidence_type),
                }
            )
    return refs


def _dedupe_sources(sources: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[dict[str, str]] = []
    for source in sources:
        key = (
            source["source_id"],
            source["source_path"],
            source["evidence_type"],
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(source)
    return deduped


def _event_log_source_path(event_log: RuntimeDebugEventLog) -> str:
    path = getattr(event_log, "path", None)
    if path is None:
        return "runtime_debug_event_log"
    return str(Path(path))


def _as_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return dict(value)


def _compact_value(value: Any, *, max_items: int = 12) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _compact_value(item, max_items=max_items)
            for key, item in list(value.items())[:max_items]
        }
    if isinstance(value, list):
        return [_compact_value(item, max_items=max_items) for item in value[:max_items]]
    if isinstance(value, str):
        return _truncate(value, limit=500)
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return _truncate(str(value), limit=280)


def _truncate(value: Any, *, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


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
