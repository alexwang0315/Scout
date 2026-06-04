from __future__ import annotations

import json
from pathlib import Path

import pytest

from ingress_evidence import (
    IngressEvidenceRecord,
    IngressEvidenceRecorder,
    IngressParseStatus,
    IngressTransport,
)


def test_ingress_recorder_preserves_wan_mqtt_raw_payload_and_summary_index(tmp_path: Path) -> None:
    recorder = _recorder(tmp_path)

    record = recorder.record(
        ingress_transport=IngressTransport.WAN_MQTT,
        source_adapter="sensorlogger",
        raw_payload=json.dumps(
            {
                "messageId": 1,
                "sessionId": "session-1",
                "deviceId": "device-1",
                "payload": [{"name": "accelerometer", "values": {"x": 0.1}}],
            }
        ),
        parse_status=IngressParseStatus.ACCEPTED,
        received_at=1780555780.5,
        transport_metadata={
            "mqtt": {
                "broker_host": "mqtt.example.test",
                "port": 8884,
                "topic": "scout/test/alex/sensorlogger",
                "qos": 0,
                "use_tls": True,
                "credential_configured": True,
            }
        },
        normalized_summary={
            "device_id": "device-1",
            "session_id": "session-1",
            "message_id": 1,
            "sensor_names": ["accelerometer"],
            "payload_count": 1,
        },
    )

    raw = json.loads((tmp_path / "raw.jsonl").read_text(encoding="utf-8").splitlines()[0])
    index_line = json.loads((tmp_path / "index.jsonl").read_text(encoding="utf-8").splitlines()[0])
    index = recorder.build_index().model_dump(mode="json")

    assert record.ingress_transport == IngressTransport.WAN_MQTT
    assert raw["artifact_kind"] == "scout_ingress_raw_evidence"
    assert raw["ingress_id"] == record.ingress_id
    assert json.loads(raw["raw_payload_text"])["payload"][0]["values"]["x"] == 0.1
    assert index_line["artifact_kind"] == "scout_ingress_evidence_record"
    assert index_line["parse_status"] == "accepted"
    assert index["record_count"] == 1
    assert index["accepted_count"] == 1
    assert index["boundary"]["evidence_only"] is True
    assert index["boundary"]["safety_api_called"] is False


def test_ingress_recorder_preserves_unrecognized_wan_mqtt_without_raw_payload_in_index(tmp_path: Path) -> None:
    recorder = _recorder(tmp_path)

    recorder.record(
        ingress_transport="wan_mqtt",
        source_adapter="sensorlogger",
        raw_payload='{"not":"sensorlogger","access_token":"secret-value-should-stay-raw"}',
        parse_status="unrecognized",
        received_at=1780555780.5,
        reject_reason="unsupported_message_shape",
        transport_metadata={"mqtt": {"topic": "scout/test/alex/sensorlogger"}},
        normalized_summary={"message_byte_count": 65},
    )

    raw_text = (tmp_path / "raw.jsonl").read_text(encoding="utf-8")
    index = recorder.build_index().model_dump(mode="json")
    index_text = json.dumps(index, ensure_ascii=False, sort_keys=True)

    assert "secret-value-should-stay-raw" in raw_text
    assert index["unrecognized_count"] == 1
    assert index["records"][0]["parse_status"] == "unrecognized"
    assert "secret-value-should-stay-raw" not in index_text
    assert "raw_payload_text" not in index_text
    assert "access_token" not in index_text


def test_ingress_recorder_indexes_lan_http_and_websocket_without_runtime_admission(tmp_path: Path) -> None:
    recorder = _recorder(tmp_path)

    recorder.record(
        ingress_transport="lan_http",
        source_adapter="manual-lab-tool",
        raw_payload='{"kind":"lan-http-smoke","payload":{"battery":97}}',
        parse_status="accepted",
        received_at=1780555780.5,
        transport_metadata={
            "lan": {
                "endpoint_path": "/runtime/mobile-wearable/ingress",
                "peer_address_class": "private_lan",
                "use_tls": False,
                "local_interface": "en0",
            }
        },
        normalized_summary={"message_kind": "lan-http-smoke", "field_count": 1},
    )
    recorder.record(
        ingress_transport="lan_websocket",
        source_adapter="local-gateway",
        raw_payload='{"kind":"lan-websocket-smoke","payload":{"watch_present":true}}',
        parse_status="accepted",
        received_at=1780555781.5,
        transport_metadata={
            "lan": {
                "endpoint_path": "/runtime/mobile-wearable/ws",
                "peer_address_class": "private_lan",
                "use_tls": False,
                "local_interface": "en0",
            }
        },
        normalized_summary={"message_kind": "lan-websocket-smoke", "field_count": 1},
    )

    index = recorder.build_index().model_dump(mode="json")
    index_text = json.dumps(index, ensure_ascii=False, sort_keys=True)

    assert index["record_count"] == 2
    assert index["ingress_transports"] == ["lan_http", "lan_websocket"]
    assert index["boundary"]["runtime_admission_performed"] is False
    assert index["boundary"]["phase1_l0_l4_state_mutated"] is False
    assert "battery" not in index_text
    assert "watch_present" not in index_text


def test_ingress_recorder_indexes_lora_gateway_low_rate_beacon_metadata(tmp_path: Path) -> None:
    recorder = _recorder(tmp_path)

    recorder.record(
        ingress_transport=IngressTransport.LORA_GATEWAY,
        source_adapter="lora-gateway",
        raw_payload=b"\x01SCOUT-BEACON:team-alpha:last-heard",
        parse_status=IngressParseStatus.ACCEPTED,
        received_at=1780555780.5,
        transport_metadata={
            "lora": {
                "gateway_id": "sx1303-gateway-1",
                "region": "AS923-TW",
                "band_mhz": "920-925",
                "rssi_dbm": -93,
                "snr_db": 7.5,
                "spreading_factor": 7,
                "packet_counter": 42,
                "gateway_timestamp": "2026-06-04T08:09:40.500000Z",
                "last_heard_location_metadata": "gateway_site_only",
            }
        },
        normalized_summary={
            "message_kind": "last_heard_beacon",
            "team_ref": "team-alpha",
        },
    )

    raw = json.loads((tmp_path / "raw.jsonl").read_text(encoding="utf-8").splitlines()[0])
    index = recorder.build_index().model_dump(mode="json")
    lora_metadata = index["records"][0]["transport_metadata"]["lora"]

    assert raw["raw_payload_encoding"] == "utf-8"
    assert raw["raw_payload_text"] == "\x01SCOUT-BEACON:team-alpha:last-heard"
    assert index["record_count"] == 1
    assert index["ingress_transports"] == ["lora_gateway"]
    assert lora_metadata["gateway_id"] == "sx1303-gateway-1"
    assert lora_metadata["region"] == "AS923-TW"
    assert lora_metadata["rssi_dbm"] == -93
    assert lora_metadata["snr_db"] == 7.5
    assert lora_metadata["spreading_factor"] == 7
    assert index["boundary"]["safety_api_called"] is False


def test_ingress_summary_rejects_raw_payload_or_credential_fields() -> None:
    with pytest.raises(ValueError, match="summary-forbidden"):
        IngressEvidenceRecord(
            ingress_id="bad-summary",
            ingress_transport="wan_mqtt",
            source_adapter="sensorlogger",
            received_at="2026-06-04T08:09:40.500000Z",
            payload_sha256="a" * 64,
            payload_byte_count=10,
            parse_status="accepted",
            raw_artifact_path="/tmp/raw.jsonl",
            normalized_summary={"raw_payload_text": "must not be in summary"},
        )

    with pytest.raises(ValueError, match="summary-forbidden"):
        IngressEvidenceRecord(
            ingress_id="bad-credential",
            ingress_transport="wan_mqtt",
            source_adapter="sensorlogger",
            received_at="2026-06-04T08:09:40.500000Z",
            payload_sha256="b" * 64,
            payload_byte_count=10,
            parse_status="accepted",
            raw_artifact_path="/tmp/raw.jsonl",
            transport_metadata={"mqtt": {"password": "must-not-appear"}},
        )


def test_ingress_evidence_module_stays_evidence_only() -> None:
    source = Path("ingress_evidence.py").read_text(encoding="utf-8")

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


def _recorder(tmp_path: Path) -> IngressEvidenceRecorder:
    return IngressEvidenceRecorder(
        raw_jsonl_path=tmp_path / "raw.jsonl",
        index_jsonl_path=tmp_path / "index.jsonl",
    )
