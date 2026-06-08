from __future__ import annotations

import json
from pathlib import Path

from scout_sensorlogger_mqtt_observer import (
    SensorLoggerMqttObserver,
    SensorLoggerMqttObserverConfig,
    boundary_fields,
    build_arg_parser,
    config_from_args,
    normalize_sensorlogger_mqtt_message,
)
from route_matching import load_gpx_route


ROOT = Path(__file__).resolve().parents[1]
ROUTE_PATH = ROOT / "tests" / "fixtures" / "routes" / "normal_climb.gpx"


def test_observer_writes_raw_jsonl_and_status_for_sensor_logger_message(tmp_path: Path) -> None:
    observer = SensorLoggerMqttObserver(_config(tmp_path, password="not-written"))

    record = observer.handle_message(
        topic="scout/test/alex/sensorlogger",
        payload=json.dumps(_message(message_id=7)).encode(),
        received_at=1780555780.5,
    )

    assert record["accepted"] is True
    assert record["parse_status"] == "accepted"
    assert record["ingress_transport"] == "wan_mqtt"
    assert record["source_adapter"] == "sensorlogger"
    assert record["message_id"] == 7
    assert record["session_id"] == "session-1"
    assert record["device_id"] == "device-1"
    assert record["payload_count"] == 2
    assert record["sensor_names"] == ["accelerometer", "location"]
    assert len(record["payload_sha256"]) == 64
    assert record["sensor_vitals_record_count"] == 2

    raw_lines = observer.raw_jsonl_path.read_text(encoding="utf-8").splitlines()
    assert len(raw_lines) == 1
    raw = json.loads(raw_lines[0])
    assert raw["artifact_kind"] == "scout_ingress_raw_evidence"
    assert raw["ingress_id"] == record["ingress_id"]
    assert json.loads(raw["raw_payload_text"])["messageId"] == 7

    index_lines = observer.ingress_index_jsonl_path.read_text(encoding="utf-8").splitlines()
    assert len(index_lines) == 1
    index_record = json.loads(index_lines[0])
    assert index_record["artifact_kind"] == "scout_ingress_evidence_record"
    assert index_record["parse_status"] == "accepted"
    assert index_record["raw_artifact_path"] == str(observer.raw_jsonl_path)
    assert index_record["normalized_summary"]["payload_count"] == 2

    status = json.loads(observer.status_path.read_text(encoding="utf-8"))
    assert status["artifact_kind"] == "scout_sensorlogger_mqtt_observer_status"
    assert status["message_count"] == 1
    assert status["invalid_message_count"] == 0
    assert status["sensor_names"] == ["accelerometer", "location"]
    assert status["sessions"][0]["last_message_id"] == 7
    assert status["ingress"]["artifact_kind"] == "scout_ingress_evidence_index"
    assert status["ingress"]["record_count"] == 1
    assert status["ingress"]["accepted_count"] == 1
    assert status["ingress"]["rejected_count"] == 0
    assert status["ingress"]["unrecognized_count"] == 0
    assert status["ingress"]["ingress_transports"] == ["wan_mqtt"]
    assert status["ingress"]["records"][0]["credential_value_exposed"] is False
    assert status["evidence"]["latency_jsonl_path"] == str(observer.latency_jsonl_path)
    assert status["evidence"]["sensor_vitals_records_jsonl_path"] == str(
        observer.sensor_vitals_records_jsonl_path
    )
    assert status["sensor_vitals_records"]["record_count"] == 2
    assert status["sensor_vitals_records"]["latest_summary"]["observation_name_counts"] == {
        "accelerometer": 1,
        "location": 1,
    }
    assert status["sensor_vitals_records"]["boundary"]["raw_payload_embedded"] is False
    assert status["latency"]["sample_count"] == 1
    assert status["latency"]["latest"]["message_id"] == 7
    assert status["latency"]["latest"]["sensor_payload_latest_time_s"] == 1780555781.517
    assert status["latency"]["stats"]["mqtt_receive_to_route_complete_ms"]["count"] == 1
    assert status["boundary"] == boundary_fields()
    assert status["mqtt"]["password_configured"] is True
    assert status["mqtt_state"] == {
        "connected": False,
        "subscribed": False,
        "ever_connected": False,
        "ever_subscribed": False,
        "connected_at": None,
        "subscribed_at": None,
        "connect_reason": None,
        "subscribe_reason": None,
    }
    status_text = json.dumps(status)
    assert "not-written" not in status_text
    assert "raw_payload_text" not in status_text
    assert "raw_message" not in status_text

    latency_lines = observer.latency_jsonl_path.read_text(encoding="utf-8").splitlines()
    assert len(latency_lines) == 1
    latency = json.loads(latency_lines[0])
    assert latency["artifact_kind"] == "scout_sensorlogger_mqtt_routing_latency"
    assert latency["ingress_id"] == record["ingress_id"]
    assert latency["message_id"] == 7
    assert latency["payload_count"] == 2
    assert latency["observation_count"] == 2
    assert latency["routing_duration_ms"] >= 0
    assert latency["mqtt_receive_to_route_complete_ms"] == record["routing_latency"]["mqtt_receive_to_route_complete_ms"]
    assert latency["boundary"]["safety_api_called"] is False

    sensor_vitals_lines = observer.sensor_vitals_records_jsonl_path.read_text(encoding="utf-8").splitlines()
    assert len(sensor_vitals_lines) == 2
    sensor_vitals = [json.loads(line) for line in sensor_vitals_lines]
    assert sensor_vitals[0]["artifact_kind"] == "scout_sensor_vitals_record"
    assert sensor_vitals[0]["observation_name"] == "accelerometer"
    assert sensor_vitals[1]["observation_name"] == "location"
    assert sensor_vitals[1]["privacy_class"] == "private_location"
    assert sensor_vitals[1]["raw_evidence_refs"] == [f"{record['ingress_id']}:payload[1]"]


def test_observer_accepts_sensor_logger_test_publish_as_connectivity_smoke(tmp_path: Path) -> None:
    observer = SensorLoggerMqttObserver(_config(tmp_path))

    record = observer.handle_message(
        topic="scout/test/alex/sensorlogger",
        payload='{"time":0,"name":"test","values":[]}',
        received_at=1780555780.5,
    )

    assert record["accepted"] is True
    assert record["device_id"] == "sensor-logger-test"
    assert record["session_id"] == "test-publish"
    assert record["sensor_names"] == ["test"]
    assert observer.status()["sessions"][0]["sensor_names"] == ["test"]


def test_observer_routes_sensorlogger_mqtt_location_and_pdr_to_ins_dr(tmp_path: Path) -> None:
    observer = SensorLoggerMqttObserver(_config(tmp_path, application_route_path=ROUTE_PATH))
    route = load_gpx_route(ROUTE_PATH)
    anchor = route.points[100]

    first = observer.handle_message(
        topic="scout/test/alex/sensorlogger",
        payload=json.dumps(
            {
                "messageId": 1,
                "sessionId": "session-1",
                "deviceId": "watch-1",
                "payload": [
                    {
                        "name": "location",
                        "time": 1780555780000000000,
                        "values": {
                            "latitude": anchor.lat,
                            "longitude": anchor.lon,
                            "horizontalAccuracy": 5.0,
                        },
                    },
                    {
                        "name": "pedometer",
                        "time": 1780555780000000000,
                        "values": {"pedometerDistance": 100.0},
                    },
                ],
            }
        ),
        received_at=1780555780.5,
    )
    second = observer.handle_message(
        topic="scout/test/alex/sensorlogger",
        payload=json.dumps(
            {
                "messageId": 2,
                "sessionId": "session-1",
                "deviceId": "watch-1",
                "payload": [
                    {
                        "name": "pedometer",
                        "time": 1780555790000000000,
                        "values": {"pedometerDistance": 112.0},
                    }
                ],
            }
        ),
        received_at=1780555790.5,
    )

    route_lines = [
        json.loads(line)
        for line in observer.application_routes_jsonl_path.read_text(encoding="utf-8").splitlines()
    ]
    output_lines = [
        json.loads(line)
        for line in observer.filter_outputs_jsonl_path.read_text(encoding="utf-8").splitlines()
    ]
    status = json.loads(observer.status_path.read_text(encoding="utf-8"))

    assert first["application_route_targets"] == ["navigation.ins_dr"]
    assert first["application_dispatch_status_counts"] == {"accepted": 1, "deferred": 1}
    assert second["application_dispatch_status_counts"] == {"accepted": 1}
    assert route_lines[-1]["route_target"] == "navigation.ins_dr"
    assert route_lines[-1]["dispatch_status"] == "accepted"
    assert output_lines[0]["output_summary"]["estimate_source"] == "gnss"
    assert output_lines[-1]["output_summary"]["estimate_source"] == "dead_reckoning"
    assert output_lines[-1]["output_summary"]["dr_distance_since_anchor_m"] == 12.0
    assert first["sensor_vitals_record_count"] == 2
    assert second["sensor_vitals_record_count"] == 1
    assert status["sensor_vitals_records"]["record_count"] == 3
    assert status["application_router"]["registered_targets"] == [
        "beacon.tracer",
        "navigation.ins_dr",
        "raw.archive",
        "resource.energy_reserve",
        "weather.route_advisor",
    ]
    assert status["application_router"]["filter_output_kind_counts"]["navigation_estimate"] == 2
    assert status["application_router"]["boundary"]["safety_api_called"] is False


def test_observer_sanitizes_credential_like_sensor_values_before_router_status(tmp_path: Path) -> None:
    observer = SensorLoggerMqttObserver(_config(tmp_path))

    record = observer.handle_message(
        topic="scout/test/alex/sensorlogger",
        payload=json.dumps(
            {
                "messageId": 3,
                "sessionId": "session-1",
                "deviceId": "watch-1",
                "payload": [
                    {
                        "name": "unknownFutureSensor",
                        "time": 1780555790000000000,
                        "values": {
                            "sample": 1,
                            "access_token": "raw-secret-stays-in-raw-evidence",
                        },
                    }
                ],
            }
        ),
        received_at=1780555790.5,
    )

    status_text = observer.status_path.read_text(encoding="utf-8")
    raw_text = observer.raw_jsonl_path.read_text(encoding="utf-8")
    sensor_vitals_text = observer.sensor_vitals_records_jsonl_path.read_text(encoding="utf-8")

    assert record["accepted"] is True
    assert record["application_dispatch_status_counts"] == {"raw_archive_only": 1}
    assert "raw-secret-stays-in-raw-evidence" in raw_text
    assert "raw-secret-stays-in-raw-evidence" not in status_text
    assert "raw-secret-stays-in-raw-evidence" not in sensor_vitals_text
    assert "access_token" not in status_text
    assert "access_token" not in sensor_vitals_text
    assert "raw_payload_text" not in status_text


def test_observer_can_emit_throttled_oled_latency_status_as_dry_run(tmp_path: Path) -> None:
    observer = SensorLoggerMqttObserver(
        _config(
            tmp_path,
            oled_status=True,
            oled_dry_run=True,
            oled_min_interval_seconds=0,
        )
    )

    record = observer.handle_message(
        topic="scout/test/alex/sensorlogger",
        payload=json.dumps(_message(message_id=9)),
        received_at=1780555780.5,
    )

    oled_lines = observer.oled_status_jsonl_path.read_text(encoding="utf-8").splitlines()
    oled = json.loads(oled_lines[0])
    status = json.loads(observer.status_path.read_text(encoding="utf-8"))

    assert record["accepted"] is True
    assert oled["artifact_kind"] == "scout_sensorlogger_mqtt_oled_status"
    assert oled["write_status"] == "dry_run"
    assert oled["dry_run"] is True
    assert oled["message"].startswith("MQTT ROUTE\nMSG 9")
    assert oled["hardware_control_scope"] == "diagnostic_display_only"
    assert oled["phase1_safety_decision_change_allowed"] is False
    assert status["oled"]["enabled"] is True
    assert status["oled"]["dry_run"] is True


def test_observer_rejects_invalid_json_without_throwing(tmp_path: Path) -> None:
    observer = SensorLoggerMqttObserver(_config(tmp_path))

    record = observer.handle_message(
        topic="scout/test/alex/sensorlogger",
        payload="{not-json",
        received_at=1780555780.5,
    )

    assert record["accepted"] is False
    assert record["reject_reason"] == "invalid_json"
    assert record["parse_status"] == "unrecognized"
    status = observer.status()
    assert status["message_count"] == 0
    assert status["invalid_message_count"] == 1
    assert status["last_error"].startswith("invalid_json:")
    assert status["ingress"]["unrecognized_count"] == 1
    raw = json.loads(observer.raw_jsonl_path.read_text(encoding="utf-8").splitlines()[0])
    assert raw["raw_payload_text"] == "{not-json"


def test_observer_tracks_gaps_duplicates_and_out_of_order_message_ids(tmp_path: Path) -> None:
    observer = SensorLoggerMqttObserver(_config(tmp_path))

    for message_id in (1, 3, 3, 2, 5):
        observer.handle_message(
            topic="scout/test/alex/sensorlogger",
            payload=json.dumps(_message(message_id=message_id)),
            received_at=1780555780.5 + message_id,
        )

    session = observer.status()["sessions"][0]
    assert session["message_count"] == 5
    assert session["last_message_id"] == 5
    assert session["message_id_gaps"] == [
        {"from_message_id": 2, "to_message_id": 2, "missing_count": 1},
        {"from_message_id": 4, "to_message_id": 4, "missing_count": 1},
    ]
    assert session["duplicate_message_ids"] == [3]
    assert session["out_of_order_message_ids"] == [2]


def test_observer_status_keeps_recent_records_but_preserves_full_evidence_index(
    tmp_path: Path,
) -> None:
    observer = SensorLoggerMqttObserver(_config(tmp_path))

    for message_id in range(1, 56):
        observer.handle_message(
            topic="scout/test/alex/sensorlogger",
            payload=json.dumps(_message(message_id=message_id)),
            received_at=1780555780.5 + message_id,
        )

    status = json.loads(observer.status_path.read_text(encoding="utf-8"))
    index_lines = observer.ingress_index_jsonl_path.read_text(encoding="utf-8").splitlines()

    assert status["message_count"] == 55
    assert status["ingress"]["record_count"] == 55
    assert status["ingress"]["accepted_count"] == 55
    assert status["ingress"]["records_truncated"] is True
    assert status["ingress"]["recent_record_limit"] == 50
    assert len(status["ingress"]["records"]) == 50
    assert len(index_lines) == 55
    assert status["ingress"]["records"][0]["normalized_summary"]["message_id"] == 6
    assert status["ingress"]["records"][-1]["normalized_summary"]["message_id"] == 55


def test_normalizer_accepts_future_android_client_when_wire_shape_matches() -> None:
    normalized = normalize_sensorlogger_mqtt_message(
        {
            "messageId": 1,
            "sessionId": "android-session",
            "deviceId": "android-device",
            "payload": [
                {
                    "name": "accelerometer",
                    "time": 1780555780517000000,
                    "values": {"x": 0.1, "y": 0.2, "z": 0.3},
                }
            ],
        }
    )

    assert normalized["accepted"] is True
    assert normalized["device_id"] == "android-device"
    assert normalized["session_id"] == "android-session"
    assert normalized["sensor_names"] == ["accelerometer"]


def test_config_from_env_file_reads_demo_vite_mqtt_settings(tmp_path: Path, monkeypatch) -> None:
    for key in (
        "SCOUT_SENSORLOGGER_MQTT_HOST",
        "SCOUT_SENSORLOGGER_MQTT_PORT",
        "SCOUT_SENSORLOGGER_MQTT_TOPIC",
        "SCOUT_SENSORLOGGER_MQTT_USERNAME",
        "SCOUT_SENSORLOGGER_MQTT_PASSWORD",
        "VITE_MQTT_BROKER_URL",
        "VITE_MQTT_USERNAME",
        "VITE_MQTT_PASSWORD",
        "VITE_MQTT_TOPIC",
    ):
        monkeypatch.delenv(key, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "VITE_MQTT_BROKER_URL=wss://cluster.example.test:8884/mqtt",
                "VITE_MQTT_USERNAME=demo-user",
                "VITE_MQTT_PASSWORD=demo-password",
                "VITE_MQTT_TOPIC=scout/test/alex/sensorlogger",
            ]
        ),
        encoding="utf-8",
    )

    parser = build_arg_parser()
    args = parser.parse_args(["--env-file", str(env_file), "--evidence-dir", str(tmp_path), "--print-ready"])
    config = config_from_args(args)

    assert config.host == "cluster.example.test"
    assert config.port == 8884
    assert config.use_tls is True
    assert config.transport == "websockets"
    assert config.websocket_path == "/mqtt"
    assert config.username == "demo-user"
    assert config.password == "demo-password"
    assert config.topic == "scout/test/alex/sensorlogger"
    assert config.print_ready is True


def test_observer_code_does_not_import_safety_runtime_or_safety_api() -> None:
    source = Path("scout_sensorlogger_mqtt_observer.py").read_text(encoding="utf-8")

    forbidden_imports = (
        "import safety_api",
        "from safety_api",
        "import safety_runtime_session",
        "from safety_runtime_session",
        "SafetyRuntimeSession",
    )
    for token in forbidden_imports:
        assert token not in source


def _config(
    tmp_path: Path,
    *,
    password: str | None = None,
    application_route_path: Path | None = None,
    oled_status: bool = False,
    oled_dry_run: bool = False,
    oled_min_interval_seconds: float = 2.0,
) -> SensorLoggerMqttObserverConfig:
    return SensorLoggerMqttObserverConfig(
        host="mqtt.example.test",
        topic="scout/test/alex/sensorlogger",
        username="observer",
        password=password,
        evidence_dir=tmp_path,
        application_route_path=application_route_path,
        oled_status=oled_status,
        oled_dry_run=oled_dry_run,
        oled_min_interval_seconds=oled_min_interval_seconds,
    )


def _message(*, message_id: int) -> dict[str, object]:
    return {
        "messageId": message_id,
        "sessionId": "session-1",
        "deviceId": "device-1",
        "payload": [
            {
                "name": "accelerometer",
                "time": 1780555780517000000,
                "values": {"x": 0.1, "y": 0.2, "z": 0.3},
            },
            {
                "name": "location",
                "time": 1780555781517000000,
                "values": {"latitude": 24.12, "longitude": 121.28, "horizontalAccuracy": 8.0},
            },
        ],
    }
