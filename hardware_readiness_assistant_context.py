from __future__ import annotations

from typing import Any


def build_hardware_readiness_assistant_context(
    *,
    interface_inventory: list[dict[str, Any]] | None = None,
    provider_health: list[dict[str, Any]] | None = None,
    sample_replay_timeline: list[dict[str, Any]] | None = None,
    runtime_debug_events: list[dict[str, Any]] | None = None,
    mock_transport_queue: list[dict[str, Any]] | None = None,
    selected_provider_ref: str | None = None,
    max_items: int = 20,
) -> dict[str, Any]:
    interfaces = [
        _interface_summary(item)
        for item in list(interface_inventory or [])[:max_items]
    ]
    providers = [
        _provider_summary(item)
        for item in list(provider_health or [])[:max_items]
    ]
    replay = [
        _event_summary(item, evidence_type="hardware_sample_replay_event")
        for item in list(sample_replay_timeline or [])[:max_items]
    ]
    debug = [
        _event_summary(item, evidence_type="runtime_debug_event")
        for item in list(runtime_debug_events or [])[:max_items]
    ]
    messages = [
        _message_summary(item)
        for item in list(mock_transport_queue or [])[:max_items]
    ]
    selected_provider = _selected_provider(providers, selected_provider_ref)
    sources = _dedupe_sources(
        [
            *_source_refs(interfaces),
            *_source_refs(providers),
            *_source_refs(replay),
            *_source_refs(debug),
            *_source_refs(messages),
        ]
    )
    degraded = [
        provider
        for provider in providers
        if str(provider.get("status", "")).lower() in {"degraded", "failed", "unavailable"}
    ]
    interface_statuses = {
        str(item.get("status", "unknown")).lower()
        for item in interfaces
    }
    return {
        "surface": "hardware_readiness",
        "context_kind": "assistant_context",
        "read_only": True,
        "bounded": True,
        "auditable": True,
        "boundary": _boundary(),
        "summary": {
            "interface_count": len(interfaces),
            "interface_statuses": sorted(interface_statuses),
            "provider_count": len(providers),
            "degraded_provider_count": len(degraded),
            "sample_replay_event_count": len(replay),
            "runtime_debug_event_count": len(debug),
            "mock_message_count": len(messages),
            "selected_provider_ref": selected_provider_ref,
        },
        "selected_provider": selected_provider,
        "interface_inventory": interfaces,
        "provider_health": providers,
        "sample_replay_timeline": replay,
        "runtime_debug_events": debug,
        "mock_transport_queue": messages,
        "sources": sources,
        "limitations": [
            "Context is a bounded hardware-readiness projection.",
            "Interface inventory is metadata-only unless a later lab/live probe explicitly records otherwise.",
            "Provider health and mock queue entries are explanatory only.",
            "No hardware provider, deployment target, or outbound transport is controlled.",
        ],
    }


def _interface_summary(item: dict[str, Any]) -> dict[str, Any]:
    interface_ref = item.get("interface_ref") or item.get("source_id")
    return {
        "interface_ref": interface_ref,
        "interface_type": item.get("interface_type"),
        "status": item.get("status"),
        "signal_activity": item.get("signal_activity"),
        "last_seen_at": item.get("last_seen_at"),
        "manual_drive_allowed": bool(item.get("manual_drive_allowed", False)),
        "manual_read_allowed": bool(item.get("manual_read_allowed", False)),
        "manual_write_allowed": bool(item.get("manual_write_allowed", False)),
        "observed_lines": _compact_value(item.get("observed_lines", []), max_items=64),
        "detected_addresses": _compact_value(item.get("detected_addresses", [])),
        "paired_devices": _compact_value(item.get("paired_devices", [])),
        "connected_devices": _compact_value(item.get("connected_devices", [])),
        "devices": _compact_value(item.get("devices", [])),
        "details": _compact_value(
            {
                key: value
                for key, value in item.items()
                if key
                not in {
                    "interface_ref",
                    "interface_type",
                    "status",
                    "signal_activity",
                    "last_seen_at",
                    "manual_drive_allowed",
                    "observed_lines",
                    "detected_addresses",
                    "paired_devices",
                    "connected_devices",
                    "devices",
                    "boundary",
                    "source_id",
                    "source_path",
                    "evidence_type",
                }
            }
        ),
        "boundary": _compact_value(item.get("boundary", {}), max_items=32),
        "source_id": item.get("source_id") or interface_ref,
        "source_path": item.get("source_path") or "hardware_readiness_interface_fixture",
        "evidence_type": item.get("evidence_type") or "hardware_interface_inventory",
    }


def _provider_summary(item: dict[str, Any]) -> dict[str, Any]:
    provider_ref = item.get("provider_ref") or item.get("provider") or item.get("source_id")
    return {
        "provider_ref": provider_ref,
        "provider_type": item.get("provider_type"),
        "status": item.get("status"),
        "last_seen_at": item.get("last_seen_at"),
        "degraded_reason": _truncate(item.get("degraded_reason") or item.get("reason"), limit=280),
        "sample_window": _compact_value(item.get("sample_window")),
        "source_id": item.get("source_id") or provider_ref,
        "source_path": item.get("source_path") or "hardware_readiness_provider_fixture",
        "evidence_type": item.get("evidence_type") or "hardware_provider_health",
    }


def _event_summary(item: dict[str, Any], *, evidence_type: str) -> dict[str, Any]:
    source_id = item.get("source_id") or item.get("event_id") or item.get("id")
    return {
        "event_id": item.get("event_id") or item.get("id"),
        "timestamp": item.get("timestamp"),
        "kind": item.get("kind"),
        "status": item.get("status"),
        "summary": _truncate(item.get("summary"), limit=280),
        "payload": _compact_value(item.get("payload", {})),
        "source_id": source_id,
        "source_path": item.get("source_path") or "hardware_readiness_runtime_fixture",
        "evidence_type": item.get("evidence_type") or evidence_type,
    }


def _message_summary(item: dict[str, Any]) -> dict[str, Any]:
    boundary = dict(item.get("boundary") or {})
    message_id = item.get("message_id") or item.get("source_id")
    return {
        "message_id": message_id,
        "transport": item.get("transport", "mock"),
        "state": item.get("state"),
        "category": item.get("category"),
        "subject_ref": item.get("subject_ref"),
        "body_preview": _truncate(item.get("body_preview"), limit=280),
        "boundary": {
            "real_sos_sent": bool(boundary.get("real_sos_sent", False)),
            "real_sms_sent": bool(boundary.get("real_sms_sent", False)),
            "real_satellite_sent": bool(boundary.get("real_satellite_sent", False)),
        },
        "source_id": message_id,
        "source_path": item.get("source_path") or "hardware_readiness_mock_queue",
        "evidence_type": item.get("evidence_type") or "hardware_mock_transport_message",
    }


def _selected_provider(
    providers: list[dict[str, Any]],
    selected_provider_ref: str | None,
) -> dict[str, Any] | None:
    if selected_provider_ref is None:
        return providers[0] if providers else None
    for provider in providers:
        if provider.get("provider_ref") == selected_provider_ref:
            return provider
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


def _compact_value(value: Any, *, max_items: int = 8) -> Any:
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
        "real_sos_allowed": False,
        "real_sms_allowed": False,
        "real_satellite_allowed": False,
        "hardware_control_allowed": False,
        "gpio_lab_mode_drive_policy_allowed": True,
        "gpio_drive_requires_wiring_manifest": True,
        "gpio_drive_implementation_enabled": False,
        "gpio_drive_operator_confirmation_required": True,
        "provider_control_allowed": False,
    }
