from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ARTIFACT_KIND = "scout_mobile_wearable_ingress_debug_status"
ARTIFACT_VERSION = "mobile_wearable_ingress_debug_status.v0"


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

    ingress = _observer_ingress_summary(observer_status)
    records = [_sanitize_ingress_record(record) for record in ingress.get("records") or []]
    latest_record = records[-1] if records else None
    observer_boundary = dict(observer_status.get("boundary") or {})
    ingress_boundary = dict((ingress.get("boundary") or {}))

    return {
        "artifact_kind": ARTIFACT_KIND,
        "artifact_version": ARTIFACT_VERSION,
        "status": "ok",
        "read_only": True,
        "source_tool": observer_status.get("source_tool"),
        "status_path": str(resolved_path),
        "message_count": _int(observer_status.get("message_count")),
        "invalid_message_count": _int(observer_status.get("invalid_message_count")),
        "sensor_names": list(observer_status.get("sensor_names") or []),
        "sessions": [_sanitize_session(session) for session in observer_status.get("sessions") or []],
        "mqtt_state": _sanitize_mqtt_state(observer_status.get("mqtt_state") or {}),
        "mqtt": _sanitize_mqtt_config(observer_status.get("mqtt") or {}),
        "ingress": {
            "record_count": _int(ingress.get("record_count")),
            "accepted_count": _int(ingress.get("accepted_count")),
            "rejected_count": _int(ingress.get("rejected_count")),
            "unrecognized_count": _int(ingress.get("unrecognized_count")),
            "ingress_transports": list(ingress.get("ingress_transports") or []),
            "source_adapters": list(ingress.get("source_adapters") or []),
            "latest_record": latest_record,
            "recent_records": records[-10:],
        },
        "evidence": {
            "evidence_dir": (observer_status.get("evidence") or {}).get("evidence_dir"),
            "raw_jsonl_path": (observer_status.get("evidence") or {}).get("raw_jsonl_path"),
            "ingress_index_jsonl_path": (observer_status.get("evidence") or {}).get("ingress_index_jsonl_path"),
            "status_path": (observer_status.get("evidence") or {}).get("status_path"),
        },
        "boundary": {
            "read_only": True,
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
        "evidence": {},
        "boundary": {
            "read_only": True,
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


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
