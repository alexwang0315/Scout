from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any


ARTIFACT_KIND = "scout_mobile_wearable_ingress_debug_status"
ARTIFACT_VERSION = "mobile_wearable_ingress_debug_status.v0"
RESET_ARTIFACT_KIND = "scout_mobile_wearable_ingress_debug_reset"
RESET_ARTIFACT_VERSION = "mobile_wearable_ingress_debug_reset.v0"
_PERSISTED_INGRESS_SUMMARY_CACHE: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}


def load_mobile_wearable_ingress_debug_status(
    status_path: Path | str | None,
) -> dict[str, Any]:
    if status_path is None:
        return _empty_status(reason="status_path_not_configured")

    resolved_path = Path(status_path).expanduser()
    if not resolved_path.exists():
        return _empty_status(
            reason="status_file_missing",
            status_path=str(resolved_path),
        )

    try:
        observer_status = json.loads(resolved_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _empty_status(
            reason="status_file_unreadable",
            status_path=str(resolved_path),
            error=str(exc),
        )

    reset_marker = _load_reset_marker(resolved_path)
    ingress = _observer_ingress_summary(observer_status)
    persisted_ingress = _persisted_ingress_summary(observer_status)
    if reset_marker and persisted_ingress:
        ingress = {
            **ingress,
            **persisted_ingress,
            "boundary": {
                **dict(ingress.get("boundary") or {}),
                **dict(persisted_ingress.get("boundary") or {}),
            },
        }
    raw_records = list(ingress.get("records") or [])
    records = [
        _sanitize_ingress_record(record)
        for record in raw_records
        if _record_visible_after_reset(record, reset_marker)
    ]
    latest_record = records[-1] if records else None
    observer_boundary = dict(observer_status.get("boundary") or {})
    ingress_boundary = dict((ingress.get("boundary") or {}))
    observer_message_count = _count_after_reset(
        observer_status.get("message_count"),
        reset_marker,
        "message_count",
    )
    observer_invalid_message_count = _count_after_reset(
        observer_status.get("invalid_message_count"),
        reset_marker,
        "invalid_message_count",
    )
    ingress_record_count = _count_after_reset(
        ingress.get("record_count"),
        reset_marker,
        "ingress_record_count",
    )
    ingress_accepted_count = _count_after_reset(
        ingress.get("accepted_count"),
        reset_marker,
        "ingress_accepted_count",
    )
    ingress_rejected_count = _count_after_reset(
        ingress.get("rejected_count"),
        reset_marker,
        "ingress_rejected_count",
    )
    ingress_unrecognized_count = _count_after_reset(
        ingress.get("unrecognized_count"),
        reset_marker,
        "ingress_unrecognized_count",
    )
    message_count = max(observer_message_count, ingress_accepted_count)
    invalid_message_count = max(
        observer_invalid_message_count,
        ingress_rejected_count + ingress_unrecognized_count,
    )
    sensor_names = (
        _sensor_names_from_records(records)
        if reset_marker
        else list(observer_status.get("sensor_names") or [])
    )
    sessions = (
        _sessions_from_records(records)
        if reset_marker
        else [_sanitize_session(session) for session in observer_status.get("sessions") or []]
    )

    return {
        "artifact_kind": ARTIFACT_KIND,
        "artifact_version": ARTIFACT_VERSION,
        "status": "ok",
        "read_only": True,
        "source_tool": observer_status.get("source_tool"),
        "status_path": str(resolved_path),
        "message_count": message_count,
        "invalid_message_count": invalid_message_count,
        "sensor_names": sensor_names,
        "sessions": sessions,
        "mqtt_state": _sanitize_mqtt_state(observer_status.get("mqtt_state") or {}),
        "mqtt": _sanitize_mqtt_config(observer_status.get("mqtt") or {}),
        "ingress": {
            "record_count": ingress_record_count,
            "accepted_count": ingress_accepted_count,
            "rejected_count": ingress_rejected_count,
            "unrecognized_count": ingress_unrecognized_count,
            "ingress_transports": (
                sorted({str(record.get("ingress_transport")) for record in records})
                if reset_marker
                else list(ingress.get("ingress_transports") or [])
            ),
            "source_adapters": (
                sorted({str(record.get("source_adapter")) for record in records})
                if reset_marker
                else list(ingress.get("source_adapters") or [])
            ),
            "latest_record": latest_record,
            "recent_records": [],
        },
        "memo": _ingress_memo(
            message_count=message_count,
            invalid_message_count=invalid_message_count,
            ingress_record_count=ingress_record_count,
            latest_record=latest_record,
            sensor_names=sensor_names,
            mqtt_state=observer_status.get("mqtt_state") or {},
            reset_marker=reset_marker,
            unavailable=False,
            reason=None,
        ),
        "projection_reset": _sanitize_reset_marker(reset_marker),
        "evidence": {
            "evidence_dir": (observer_status.get("evidence") or {}).get("evidence_dir"),
            "raw_jsonl_path": (observer_status.get("evidence") or {}).get("raw_jsonl_path"),
            "ingress_index_jsonl_path": (observer_status.get("evidence") or {}).get("ingress_index_jsonl_path"),
            "debug_reset_marker_path": str(_reset_marker_path(resolved_path)),
            "status_path": (observer_status.get("evidence") or {}).get("status_path"),
        },
        "boundary": {
            "read_only": True,
            "debug_projection_reset_applied": bool(reset_marker),
            "raw_evidence_cleared": False,
            "observer_process_restarted": False,
            "raw_payload_embedded": False,
            "credential_value_exposed": False,
            "runtime_admission_performed": bool(
                ingress_boundary.get("runtime_admission_performed", False)
            ),
            "phase1_l0_l4_state_mutated": bool(
                observer_boundary.get("phase1_l0_l4_state_mutated", False)
                or ingress_boundary.get("phase1_l0_l4_state_mutated", False)
            ),
            "safety_api_called": bool(
                observer_boundary.get("safety_api_called", False)
                or ingress_boundary.get("safety_api_called", False)
            ),
            "phase2_brain_writeback": bool(
                observer_boundary.get("phase2_brain_writeback", False)
                or ingress_boundary.get("phase2_brain_writeback", False)
            ),
        },
    }


def reset_mobile_wearable_ingress_debug_projection(
    status_path: Path | str | None,
) -> dict[str, Any]:
    if status_path is None:
        return {
            "status": "unavailable",
            "reason": "status_path_not_configured",
            "reset_applied": False,
            "boundary": _reset_boundary(reset_applied=False),
            "mobile_wearable_ingress": _empty_status(reason="status_path_not_configured"),
        }

    resolved_path = Path(status_path).expanduser()
    observer_status = _read_observer_status_for_reset(resolved_path)
    ingress = _observer_ingress_summary(observer_status) if observer_status else {}
    reset_marker = {
        "artifact_kind": RESET_ARTIFACT_KIND,
        "artifact_version": RESET_ARTIFACT_VERSION,
        "reset_at": _now_iso(),
        "status_path": str(resolved_path),
        "baseline": {
            "message_count": _int((observer_status or {}).get("message_count")),
            "invalid_message_count": _int((observer_status or {}).get("invalid_message_count")),
            "ingress_record_count": _int(ingress.get("record_count")),
            "ingress_accepted_count": _int(ingress.get("accepted_count")),
            "ingress_rejected_count": _int(ingress.get("rejected_count")),
            "ingress_unrecognized_count": _int(ingress.get("unrecognized_count")),
        },
        "boundary": _reset_boundary(reset_applied=True),
    }
    marker_path = _reset_marker_path(resolved_path)
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text(
        json.dumps(reset_marker, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return {
        "status": "reset",
        "reset_applied": True,
        "reset_marker_path": str(marker_path),
        "baseline": reset_marker["baseline"],
        "boundary": _reset_boundary(reset_applied=True),
        "mobile_wearable_ingress": load_mobile_wearable_ingress_debug_status(resolved_path),
    }


def _empty_status(
    *,
    reason: str,
    status_path: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "artifact_kind": ARTIFACT_KIND,
        "artifact_version": ARTIFACT_VERSION,
        "status": "unavailable",
        "read_only": True,
        "unavailable": True,
        "reason": reason,
        "error": error,
        "status_path": status_path,
        "message_count": 0,
        "invalid_message_count": 0,
        "sensor_names": [],
        "sessions": [],
        "mqtt_state": {},
        "mqtt": {},
        "ingress": {
            "record_count": 0,
            "accepted_count": 0,
            "rejected_count": 0,
            "unrecognized_count": 0,
            "ingress_transports": [],
            "source_adapters": [],
            "latest_record": None,
            "recent_records": [],
        },
        "memo": _ingress_memo(
            message_count=0,
            invalid_message_count=0,
            ingress_record_count=0,
            latest_record=None,
            sensor_names=[],
            mqtt_state={},
            reset_marker=None,
            unavailable=True,
            reason=reason,
        ),
        "projection_reset": None,
        "evidence": {},
        "boundary": {
            "read_only": True,
            "debug_projection_reset_applied": False,
            "raw_evidence_cleared": False,
            "observer_process_restarted": False,
            "raw_payload_embedded": False,
            "credential_value_exposed": False,
            "runtime_admission_performed": False,
            "phase1_l0_l4_state_mutated": False,
            "safety_api_called": False,
            "phase2_brain_writeback": False,
        },
    }


def _sanitize_ingress_record(record: dict[str, Any]) -> dict[str, Any]:
    summary = dict(record.get("normalized_summary") or {})
    metadata = dict(record.get("transport_metadata") or {})
    return {
        "ingress_id": record.get("ingress_id"),
        "ingress_transport": record.get("ingress_transport"),
        "source_adapter": record.get("source_adapter"),
        "received_at": record.get("received_at"),
        "payload_sha256": record.get("payload_sha256"),
        "payload_byte_count": _int(record.get("payload_byte_count")),
        "parse_status": record.get("parse_status"),
        "reject_reason": record.get("reject_reason"),
        "raw_artifact_path": record.get("raw_artifact_path"),
        "transport_metadata": _sanitize_transport_metadata(metadata),
        "normalized_summary": _sanitize_summary(summary),
        "credential_value_exposed": False,
    }


def _observer_ingress_summary(observer_status: dict[str, Any]) -> dict[str, Any]:
    ingress = dict(observer_status.get("ingress") or {})
    if ingress.get("records"):
        return ingress

    legacy_records = _legacy_observer_ingress_records(observer_status)
    if not legacy_records:
        return ingress

    accepted_count = sum(1 for record in legacy_records if record.get("parse_status") == "accepted")
    rejected_count = sum(1 for record in legacy_records if record.get("parse_status") == "rejected")
    unrecognized_count = sum(
        1 for record in legacy_records if record.get("parse_status") == "unrecognized"
    )
    return {
        **ingress,
        "record_count": len(legacy_records),
        "accepted_count": accepted_count,
        "rejected_count": rejected_count,
        "unrecognized_count": unrecognized_count,
        "ingress_transports": sorted(
            {str(record.get("ingress_transport")) for record in legacy_records}
        ),
        "source_adapters": sorted({str(record.get("source_adapter")) for record in legacy_records}),
        "records": legacy_records,
        "boundary": {
            "evidence_only": True,
            "runtime_admission_performed": False,
            "phase1_l0_l4_state_mutated": False,
            "safety_api_called": False,
            "phase2_brain_writeback": False,
            "raw_payload_embedded_in_summary": False,
            "credential_value_exposed": False,
            **dict(ingress.get("boundary") or {}),
        },
    }


def _persisted_ingress_summary(observer_status: dict[str, Any]) -> dict[str, Any] | None:
    evidence = observer_status.get("evidence") or {}
    index_path_value = evidence.get("ingress_index_jsonl_path")
    if not index_path_value:
        return None

    index_path = Path(str(index_path_value)).expanduser()
    try:
        stat = index_path.stat()
    except OSError:
        return None
    cache_key = str(index_path)
    file_signature = (stat.st_mtime_ns, stat.st_size)
    cached = _PERSISTED_INGRESS_SUMMARY_CACHE.get(cache_key)
    if cached and cached[0] == file_signature:
        return cached[1]

    try:
        lines = index_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    record_count = 0
    accepted_count = 0
    rejected_count = 0
    unrecognized_count = 0
    ingress_transports: set[str] = set()
    source_adapters: set[str] = set()
    latest_record: dict[str, Any] | None = None
    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        record_count += 1
        parse_status = str(record.get("parse_status") or "")
        if parse_status == "accepted":
            accepted_count += 1
        elif parse_status == "rejected":
            rejected_count += 1
        elif parse_status == "unrecognized":
            unrecognized_count += 1
        if record.get("ingress_transport"):
            ingress_transports.add(str(record["ingress_transport"]))
        if record.get("source_adapter"):
            source_adapters.add(str(record["source_adapter"]))
        latest_record = record

    if record_count == 0:
        return None

    summary = {
        "record_count": record_count,
        "accepted_count": accepted_count,
        "rejected_count": rejected_count,
        "unrecognized_count": unrecognized_count,
        "ingress_transports": sorted(ingress_transports),
        "source_adapters": sorted(source_adapters),
        "records": [latest_record] if latest_record else [],
        "persisted_index_reconciled": True,
        "boundary": {
            "evidence_only": True,
            "runtime_admission_performed": False,
            "phase1_l0_l4_state_mutated": False,
            "safety_api_called": False,
            "phase2_brain_writeback": False,
            "raw_payload_embedded_in_summary": False,
            "credential_value_exposed": False,
        },
    }
    _PERSISTED_INGRESS_SUMMARY_CACHE[cache_key] = (file_signature, summary)
    return summary


def _legacy_observer_ingress_records(observer_status: dict[str, Any]) -> list[dict[str, Any]]:
    evidence = observer_status.get("evidence") or {}
    raw_path_value = evidence.get("raw_jsonl_path")
    if not raw_path_value:
        return []

    raw_path = Path(str(raw_path_value)).expanduser()
    try:
        lines = raw_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    records: list[dict[str, Any]] = []
    observer_mqtt = dict(observer_status.get("mqtt") or {})
    configured_topic = observer_mqtt.get("topic")
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            legacy = json.loads(line)
        except json.JSONDecodeError:
            continue
        if legacy.get("artifact_kind") != "scout_sensorlogger_mqtt_raw_message":
            continue

        parse_status = "accepted" if legacy.get("accepted") else "rejected"
        topic = legacy.get("topic") or configured_topic
        transport_mqtt = dict(observer_mqtt)
        if topic is not None:
            transport_mqtt["topic"] = topic
        if configured_topic is not None:
            transport_mqtt["configured_topic"] = configured_topic
        payload_sha256 = _legacy_payload_sha256(legacy, fallback=line)
        record = {
            "ingress_id": _legacy_ingress_id(raw_path=raw_path, index=index, payload_sha256=payload_sha256),
            "ingress_transport": "wan_mqtt",
            "source_adapter": "sensorlogger",
            "received_at": legacy.get("received_at"),
            "payload_sha256": payload_sha256,
            "payload_byte_count": _legacy_payload_byte_count(legacy),
            "parse_status": parse_status,
            "reject_reason": legacy.get("reject_reason"),
            "raw_artifact_path": str(raw_path),
            "transport_metadata": {
                "mqtt": transport_mqtt,
                "legacy_status_backfill": True,
            },
            "normalized_summary": _legacy_normalized_summary(legacy),
            "credential_value_exposed": False,
        }
        records.append(record)
    return records


def _legacy_payload_sha256(legacy: dict[str, Any], *, fallback: str) -> str:
    value = legacy.get("payload_sha256")
    if isinstance(value, str) and len(value) == 64:
        return value
    return hashlib.sha256(fallback.encode("utf-8")).hexdigest()


def _legacy_ingress_id(*, raw_path: Path, index: int, payload_sha256: str) -> str:
    source = f"{raw_path}:{index}:{payload_sha256}"
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:24]


def _legacy_payload_byte_count(legacy: dict[str, Any]) -> int:
    raw_message = legacy.get("raw_message")
    if isinstance(raw_message, (dict, list)):
        return len(
            json.dumps(raw_message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
    raw_payload_text = legacy.get("raw_payload_text")
    if isinstance(raw_payload_text, str):
        return len(raw_payload_text.encode("utf-8"))
    return _int(legacy.get("payload_byte_count"))


def _legacy_normalized_summary(legacy: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {"legacy_status_backfill": True}
    for key in ("device_id", "session_id", "message_id", "payload_count"):
        if key in legacy:
            summary[key] = legacy.get(key)
    sensor_names = legacy.get("sensor_names")
    if isinstance(sensor_names, list):
        summary["sensor_names"] = list(sensor_names)
    return summary


def _sanitize_session(session: dict[str, Any]) -> dict[str, Any]:
    return {
        "device_id": session.get("device_id"),
        "session_id": session.get("session_id"),
        "message_count": _int(session.get("message_count")),
        "payload_count": _int(session.get("payload_count")),
        "sensor_names": list(session.get("sensor_names") or []),
        "last_message_id": session.get("last_message_id"),
        "last_seen_at": session.get("last_seen_at"),
        "message_id_gaps": list(session.get("message_id_gaps") or []),
        "duplicate_message_ids": list(session.get("duplicate_message_ids") or []),
        "out_of_order_message_ids": list(session.get("out_of_order_message_ids") or []),
    }


def _sanitize_mqtt_config(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "host": payload.get("host"),
        "port": payload.get("port"),
        "topic": payload.get("topic"),
        "transport": payload.get("transport"),
        "use_tls": payload.get("use_tls"),
        "websocket_path": payload.get("websocket_path"),
        "username_configured": bool(payload.get("username_configured")),
        "credential_configured": bool(
            payload.get("credential_configured") or payload.get("password_configured")
        ),
    }


def _sanitize_mqtt_state(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "connected": bool(payload.get("connected")),
        "subscribed": bool(payload.get("subscribed")),
        "ever_connected": bool(payload.get("ever_connected")),
        "ever_subscribed": bool(payload.get("ever_subscribed")),
        "connected_at": payload.get("connected_at"),
        "subscribed_at": payload.get("subscribed_at"),
        "connect_reason": payload.get("connect_reason"),
        "subscribe_reason": payload.get("subscribe_reason"),
    }


def _sanitize_transport_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    clean = _sanitize_summary(payload)
    mqtt = clean.get("mqtt")
    if isinstance(mqtt, dict):
        clean["mqtt"] = _sanitize_mqtt_config(mqtt)
        if "topic" in mqtt:
            clean["mqtt"]["topic"] = mqtt["topic"]
        if "configured_topic" in mqtt:
            clean["mqtt"]["configured_topic"] = mqtt["configured_topic"]
    return clean


def _sanitize_summary(payload: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in payload.items():
        key_text = str(key)
        lowered = key_text.lower()
        if (
            lowered == "payload"
            or lowered.startswith("raw_payload")
            or lowered == "raw_message"
            or "password" in lowered
            or "secret" in lowered
            or "access_token" in lowered
            or "private_key" in lowered
        ):
            continue
        if isinstance(value, dict):
            clean[key_text] = _sanitize_summary(value)
        elif isinstance(value, list):
            clean[key_text] = [
                _sanitize_summary(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            clean[key_text] = value
    return clean


def _read_observer_status_for_reset(status_path: Path) -> dict[str, Any] | None:
    if not status_path.exists():
        return None
    try:
        return json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _reset_marker_path(status_path: Path) -> Path:
    return status_path.with_name("sensorlogger_mqtt_debug_reset.json")


def _load_reset_marker(status_path: Path) -> dict[str, Any] | None:
    marker_path = _reset_marker_path(status_path)
    if not marker_path.exists():
        return None
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if marker.get("artifact_kind") != RESET_ARTIFACT_KIND:
        return None
    baseline = marker.get("baseline")
    if not isinstance(baseline, dict):
        return None
    return marker


def _sanitize_reset_marker(marker: dict[str, Any] | None) -> dict[str, Any] | None:
    if not marker:
        return None
    baseline = dict(marker.get("baseline") or {})
    return {
        "artifact_kind": marker.get("artifact_kind"),
        "artifact_version": marker.get("artifact_version"),
        "reset_at": marker.get("reset_at"),
        "baseline": {
            "message_count": _int(baseline.get("message_count")),
            "invalid_message_count": _int(baseline.get("invalid_message_count")),
            "ingress_record_count": _int(baseline.get("ingress_record_count")),
            "ingress_accepted_count": _int(baseline.get("ingress_accepted_count")),
            "ingress_rejected_count": _int(baseline.get("ingress_rejected_count")),
            "ingress_unrecognized_count": _int(baseline.get("ingress_unrecognized_count")),
        },
        "boundary": _reset_boundary(reset_applied=True),
    }


def _count_after_reset(
    value: Any,
    marker: dict[str, Any] | None,
    baseline_key: str,
) -> int:
    count = _int(value)
    if not marker:
        return count
    baseline = _int((marker.get("baseline") or {}).get(baseline_key))
    return max(count - baseline, 0)


def _record_visible_after_reset(
    record: dict[str, Any],
    marker: dict[str, Any] | None,
) -> bool:
    if not marker:
        return True
    reset_at = marker.get("reset_at")
    received_at = record.get("received_at")
    if not reset_at or not received_at:
        return False
    return str(received_at) >= str(reset_at)


def _sensor_names_from_records(records: list[dict[str, Any]]) -> list[str]:
    names: set[str] = set()
    for record in records:
        summary = record.get("normalized_summary") or {}
        for name in summary.get("sensor_names") or []:
            names.add(str(name))
    return sorted(names)


def _sessions_from_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sessions: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records:
        summary = record.get("normalized_summary") or {}
        device_id = str(summary.get("device_id") or "unknown-device")
        session_id = str(summary.get("session_id") or "unknown-session")
        key = (device_id, session_id)
        session = sessions.setdefault(
            key,
            {
                "device_id": device_id,
                "session_id": session_id,
                "message_count": 0,
                "payload_count": 0,
                "sensor_names": set(),
                "last_message_id": None,
                "last_seen_at": None,
                "message_id_gaps": [],
                "duplicate_message_ids": [],
                "out_of_order_message_ids": [],
            },
        )
        session["message_count"] += 1
        session["payload_count"] += _int(summary.get("payload_count"))
        session["sensor_names"].update(str(name) for name in summary.get("sensor_names") or [])
        session["last_message_id"] = summary.get("message_id")
        session["last_seen_at"] = record.get("received_at")

    return [
        {
            **session,
            "sensor_names": sorted(session["sensor_names"]),
        }
        for session in sessions.values()
    ]


def _ingress_memo(
    *,
    message_count: int,
    invalid_message_count: int,
    ingress_record_count: int,
    latest_record: dict[str, Any] | None,
    sensor_names: list[str],
    mqtt_state: dict[str, Any],
    reset_marker: dict[str, Any] | None,
    unavailable: bool,
    reason: str | None,
) -> str:
    if unavailable:
        return f"status=unavailable | reason={reason or 'unknown'}"

    latest = latest_record or {}
    summary = latest.get("normalized_summary") or {}
    mqtt_status = (
        "subscribed"
        if mqtt_state.get("ever_subscribed")
        else ("connected" if mqtt_state.get("ever_connected") else "not_connected")
    )
    parts = [
        f"mqtt={mqtt_status}",
        f"messages={message_count}",
        f"ingress={ingress_record_count}",
        f"invalid={invalid_message_count}",
        f"latest={latest.get('parse_status') or 'none'}",
    ]
    if latest.get("received_at"):
        parts.append(f"received={latest['received_at']}")
    if summary.get("device_id"):
        parts.append(f"device={summary['device_id']}")
    if summary.get("session_id"):
        parts.append(f"session={summary['session_id']}")
    if summary.get("payload_count") is not None:
        parts.append(f"payload_count={summary['payload_count']}")

    shown_sensors = sensor_names[:8]
    if shown_sensors:
        suffix = f"+{len(sensor_names) - len(shown_sensors)}" if len(sensor_names) > len(shown_sensors) else ""
        parts.append(f"sensors={','.join(shown_sensors)}{suffix}")
    if reset_marker:
        parts.append(f"reset_at={reset_marker.get('reset_at')}")
    return " | ".join(parts)


def _reset_boundary(*, reset_applied: bool) -> dict[str, bool]:
    return {
        "debug_projection_reset": reset_applied,
        "raw_evidence_cleared": False,
        "observer_process_restarted": False,
        "runtime_admission_performed": False,
        "phase1_l0_l4_state_mutated": False,
        "safety_api_called": False,
        "phase2_brain_writeback": False,
        "credential_value_exposed": False,
    }


def _now_iso() -> str:
    timestamp = time.time()
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(timestamp)) + (
        f".{int((timestamp % 1) * 1_000_000):06d}Z"
    )


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
