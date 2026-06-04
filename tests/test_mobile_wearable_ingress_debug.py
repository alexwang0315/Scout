from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from debug_api import create_debug_app
from ingress_evidence import IngressEvidenceRecorder
from mobile_wearable_ingress_debug import load_mobile_wearable_ingress_debug_status


def test_mobile_wearable_ingress_debug_status_sanitizes_observer_status(tmp_path: Path) -> None:
    status_path = _write_observer_status(tmp_path, password_value="do-not-leak")

    payload = load_mobile_wearable_ingress_debug_status(status_path)
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    assert payload["artifact_kind"] == "scout_mobile_wearable_ingress_debug_status"
    assert payload["status"] == "ok"
    assert payload["message_count"] == 1
    assert payload["ingress"]["record_count"] == 1
    assert payload["ingress"]["accepted_count"] == 1
    assert payload["ingress"]["latest_record"]["ingress_transport"] == "wan_mqtt"
    assert payload["ingress"]["latest_record"]["parse_status"] == "accepted"
    assert payload["ingress"]["latest_record"]["normalized_summary"]["payload_count"] == 1
    assert payload["mqtt"]["credential_configured"] is True
    assert payload["boundary"]["read_only"] is True
    assert payload["boundary"]["raw_payload_embedded"] is False
    assert payload["boundary"]["credential_value_exposed"] is False
    assert payload["boundary"]["safety_api_called"] is False
    assert "do-not-leak" not in serialized
    assert "raw_payload_text" not in serialized
    assert "raw_payload_base64" not in serialized
    assert "raw_message" not in serialized
    assert '"payload":' not in serialized
    assert "password_configured" not in serialized


def test_debug_api_exposes_mobile_wearable_ingress_read_only_endpoint(tmp_path: Path) -> None:
    status_path = _write_observer_status(tmp_path)
    client = TestClient(
        create_debug_app(mobile_wearable_ingress_status_path=status_path)
    )

    response = client.get("/debug/mobile-wearable/ingress")
    blocked_post = client.post("/debug/mobile-wearable/ingress", json={})

    assert response.status_code == 200
    payload = response.json()
    assert payload["read_only"] is True
    assert payload["ingress"]["ingress_transports"] == ["wan_mqtt"]
    assert payload["ingress"]["latest_record"]["source_adapter"] == "sensorlogger"
    assert blocked_post.status_code == 405


def test_mobile_wearable_ingress_debug_backfills_legacy_observer_raw_index(tmp_path: Path) -> None:
    raw_path = tmp_path / "sensorlogger_mqtt_raw.jsonl"
    raw_path.write_text(
        json.dumps(
            {
                "artifact_kind": "scout_sensorlogger_mqtt_raw_message",
                "artifact_version": "sensorlogger_mqtt_raw_message.v0",
                "accepted": True,
                "received_at": "2026-06-04T08:04:13.133307Z",
                "topic": "scout/test/alex/sensorlogger",
                "device_id": "device-legacy",
                "session_id": "session-legacy",
                "message_id": 7,
                "payload_count": 2,
                "payload_sha256": "a" * 64,
                "sensor_names": ["accelerometer", "watch location"],
                "raw_message": {
                    "messageId": 7,
                    "sessionId": "session-legacy",
                    "deviceId": "device-legacy",
                    "payload": [
                        {"name": "accelerometer", "values": {"x": 0.1}},
                        {"name": "watch location", "values": {"lat": 24.1}},
                    ],
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    status_path = tmp_path / "sensorlogger_mqtt_status.json"
    status_path.write_text(
        json.dumps(
            {
                "artifact_kind": "scout_sensorlogger_mqtt_observer_status",
                "source_tool": "scout_sensorlogger_mqtt_observer",
                "message_count": 1,
                "invalid_message_count": 0,
                "sensor_names": ["accelerometer", "watch location"],
                "sessions": [],
                "mqtt": {
                    "host": "mqtt.example.test",
                    "port": 8884,
                    "topic": "scout/test/alex/sensorlogger",
                    "transport": "websockets",
                    "use_tls": True,
                    "password_configured": True,
                },
                "evidence": {
                    "evidence_dir": str(tmp_path),
                    "raw_jsonl_path": str(raw_path),
                    "ingress_index_jsonl_path": None,
                    "status_path": str(status_path),
                },
                "boundary": {
                    "evidence_only": True,
                    "phase1_l0_l4_state_mutated": False,
                    "safety_api_called": False,
                    "phase2_brain_writeback": False,
                },
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    payload = load_mobile_wearable_ingress_debug_status(status_path)
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    assert payload["ingress"]["record_count"] == 1
    assert payload["ingress"]["accepted_count"] == 1
    assert payload["ingress"]["latest_record"]["ingress_transport"] == "wan_mqtt"
    assert payload["ingress"]["latest_record"]["source_adapter"] == "sensorlogger"
    assert payload["ingress"]["latest_record"]["normalized_summary"] == {
        "device_id": "device-legacy",
        "legacy_status_backfill": True,
        "message_id": 7,
        "payload_count": 2,
        "sensor_names": ["accelerometer", "watch location"],
        "session_id": "session-legacy",
    }
    assert payload["mqtt"]["credential_configured"] is True
    assert "raw_message" not in serialized
    assert "raw_payload_text" not in serialized
    assert '"values":' not in serialized
    assert "password_configured" not in serialized


def test_mobile_wearable_ingress_debug_status_handles_missing_file() -> None:
    payload = load_mobile_wearable_ingress_debug_status(
        "/tmp/scout-missing-mobile-wearable-ingress-status.json"
    )

    assert payload["status"] == "unavailable"
    assert payload["reason"] == "status_file_missing"
    assert payload["message_count"] == 0
    assert payload["ingress"]["record_count"] == 0
    assert payload["boundary"]["safety_api_called"] is False


def test_mobile_wearable_ingress_debug_module_stays_off_safety_and_brain() -> None:
    source = Path("mobile_wearable_ingress_debug.py").read_text(encoding="utf-8")

    for token in (
        "import safety_api",
        "from safety_api",
        "SafetyRuntimeSession",
        "/safety/",
        "ObservedFact",
        "requests.post",
        "httpx.",
    ):
        assert token not in source


def _write_observer_status(
    tmp_path: Path,
    *,
    password_value: str | None = None,
) -> Path:
    recorder = IngressEvidenceRecorder(
        raw_jsonl_path=tmp_path / "sensorlogger_mqtt_raw.jsonl",
        index_jsonl_path=tmp_path / "sensorlogger_mqtt_ingress_index.jsonl",
    )
    recorder.record(
        ingress_transport="wan_mqtt",
        source_adapter="sensorlogger",
        raw_payload=json.dumps(
            {
                "messageId": 1,
                "sessionId": "session-1",
                "deviceId": "device-1",
                "payload": [{"name": "accelerometer", "values": {"x": 0.1}}],
                "password": password_value,
            }
        ),
        parse_status="accepted",
        received_at=1780555780.5,
        transport_metadata={
            "mqtt": {
                "host": "mqtt.example.test",
                "port": 8884,
                "topic": "scout/test/alex/sensorlogger",
                "transport": "websockets",
                "use_tls": True,
                "credential_configured": True,
            }
        },
        normalized_summary={
            "device_id": "device-1",
            "session_id": "session-1",
            "message_id": 1,
            "payload_count": 1,
            "sensor_names": ["accelerometer"],
        },
    )
    ingress_index = recorder.build_index().model_dump(mode="json")
    status_path = tmp_path / "sensorlogger_mqtt_status.json"
    status_path.write_text(
        json.dumps(
            {
                "artifact_kind": "scout_sensorlogger_mqtt_observer_status",
                "source_tool": "scout_sensorlogger_mqtt_observer",
                "message_count": 1,
                "invalid_message_count": 0,
                "sensor_names": ["accelerometer"],
                "sessions": [
                    {
                        "device_id": "device-1",
                        "session_id": "session-1",
                        "message_count": 1,
                        "payload_count": 1,
                        "sensor_names": ["accelerometer"],
                        "last_message_id": 1,
                        "last_seen_at": "2026-06-04T08:09:40.500000Z",
                    }
                ],
                "mqtt": {
                    "host": "mqtt.example.test",
                    "port": 8884,
                    "topic": "scout/test/alex/sensorlogger",
                    "transport": "websockets",
                    "use_tls": True,
                    "password_configured": True,
                },
                "mqtt_state": {
                    "ever_connected": True,
                    "ever_subscribed": True,
                    "subscribe_reason": "Granted QoS 0",
                },
                "ingress": ingress_index,
                "evidence": {
                    "evidence_dir": str(tmp_path),
                    "raw_jsonl_path": str(tmp_path / "sensorlogger_mqtt_raw.jsonl"),
                    "ingress_index_jsonl_path": str(tmp_path / "sensorlogger_mqtt_ingress_index.jsonl"),
                    "status_path": str(status_path),
                },
                "boundary": {
                    "evidence_only": True,
                    "phase1_l0_l4_state_mutated": False,
                    "safety_api_called": False,
                    "phase2_brain_writeback": False,
                },
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return status_path
