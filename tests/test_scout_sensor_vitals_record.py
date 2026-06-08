from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from application_router import ApplicationObservation, observations_from_sensorlogger_message
from ingress_evidence import IngressTransport
from scout_sensor_vitals_record import (
    ScoutSensorVitalsRecord,
    append_sensor_vitals_records_jsonl,
    energy_vitals_snapshot_from_sensor_vitals_records,
    energy_vitals_time_window_from_sensor_vitals_records,
    load_project_sensor_vitals_records,
    load_sensor_vitals_records_jsonl,
    query_sensor_vitals_records,
    sensor_vitals_records_from_observations,
)


def test_sensor_vitals_records_normalize_sensorlogger_observations() -> None:
    observations = observations_from_sensorlogger_message(
        {
            "messageId": 11,
            "sessionId": "session-1",
            "deviceId": "watch-1",
            "payload": [
                {
                    "name": "location",
                    "time": 1780555781517000000,
                    "values": {
                        "latitude": 24.12,
                        "longitude": 121.28,
                        "horizontalAccuracy": 8.0,
                    },
                },
                {
                    "name": "accelerometer",
                    "time": 1780555782517000000,
                    "values": {"x": 0.1, "y": 0.2, "z": 0.3},
                },
                {
                    "name": "heart_rate",
                    "time": 1780555783517000000,
                    "values": {"heartRate": 92},
                },
            ],
        },
        ingress_transport=IngressTransport.WAN_MQTT,
        source_adapter="sensorlogger",
        received_at="2026-06-05T00:00:00Z",
        payload_sha256="a" * 64,
        ingress_id="ingress-1",
    )

    record_set = sensor_vitals_records_from_observations(observations)
    records = list(record_set.records)

    assert record_set.artifact_kind == "scout_sensor_vitals_record_set"
    assert record_set.record_count == 3
    assert record_set.session_id == "session-1"
    assert records[0].artifact_kind == "scout_sensor_vitals_record"
    assert records[0].observation_name == "location"
    assert records[0].privacy_class == "private_location"
    assert records[0].unit_map == {
        "horizontalAccuracy": "m",
        "latitude": "deg",
        "longitude": "deg",
    }
    assert records[0].quality == {
        "gps_like_location": True,
        "horizontal_accuracy_m": 8.0,
    }
    assert records[1].capability_tags == ("imu",)
    assert records[1].unit_map == {"x": "m/s^2", "y": "m/s^2", "z": "m/s^2"}
    assert records[2].privacy_class == "private_vitals"
    assert records[2].unit_map == {"heartRate": "bpm"}
    assert record_set.summary["observation_name_counts"] == {
        "accelerometer": 1,
        "heart_rate": 1,
        "location": 1,
    }
    assert record_set.boundary.safety_api_called is False
    assert record_set.boundary.medical_diagnosis is False


def test_sensor_vitals_records_append_load_and_query_jsonl(tmp_path: Path) -> None:
    observations = [
        ApplicationObservation(
            observation_id="obs-location",
            source_adapter="sensorlogger",
            ingress_transport=IngressTransport.WAN_MQTT,
            observation_name="location",
            values={"latitude": 24.0, "longitude": 121.0, "horizontalAccuracy": 5.0},
            observed_at="2026-06-05T00:00:01Z",
            timestamp_s=1780555781.0,
            received_at="2026-06-05T00:00:02Z",
            session_id="session-1",
            device_id="watch-1",
            raw_evidence_refs=("ingress-1:payload[0]",),
            payload_sha256="b" * 64,
            capability_tags=("gps", "location"),
        ),
        ApplicationObservation(
            observation_id="obs-hr",
            source_adapter="sensorlogger",
            ingress_transport=IngressTransport.WAN_MQTT,
            observation_name="heart_rate",
            values={"heartRate": 88},
            observed_at="2026-06-05T00:00:03Z",
            timestamp_s=1780555783.0,
            received_at="2026-06-05T00:00:04Z",
            session_id="session-1",
            device_id="watch-1",
            raw_evidence_refs=("ingress-1:payload[1]",),
            payload_sha256="b" * 64,
            capability_tags=("health", "resource", "vitals"),
        ),
    ]
    record_set = sensor_vitals_records_from_observations(observations)
    path = tmp_path / "sensor_vitals.jsonl"

    append_sensor_vitals_records_jsonl(path, record_set)
    loaded = load_sensor_vitals_records_jsonl(path)
    vitals = query_sensor_vitals_records(loaded, capability_tags={"vitals"})
    route_window = query_sensor_vitals_records(
        loaded,
        observation_names={"location"},
        device_id="watch-1",
        session_id="session-1",
        start_timestamp_s=1780555780.0,
        end_timestamp_s=1780555782.0,
    )

    assert len(path.read_text(encoding="utf-8").splitlines()) == 2
    assert len(loaded) == 2
    assert vitals[0].observation_name == "heart_rate"
    assert route_window[0].observation_name == "location"
    assert json.loads(path.read_text(encoding="utf-8").splitlines()[0])["credential_value_exposed"] is False


def test_sensor_vitals_records_build_energy_vitals_snapshot_from_project_jsonl(tmp_path: Path) -> None:
    observations = [
        ApplicationObservation(
            observation_id="obs-hr",
            source_adapter="sensorlogger",
            ingress_transport=IngressTransport.WAN_MQTT,
            observation_name="heart_rate",
            values={"heartRate": 162},
            observed_at="2026-06-07T08:00:00Z",
            timestamp_s=1780828800.0,
            received_at="2026-06-07T08:00:01Z",
            session_id="session-energy",
            device_id="watch-1",
            raw_evidence_refs=("ingress-energy:payload[0]",),
            payload_sha256="c" * 64,
            capability_tags=("health", "vitals"),
        ),
        ApplicationObservation(
            observation_id="obs-energy",
            source_adapter="sensorlogger",
            ingress_transport=IngressTransport.WAN_MQTT,
            observation_name="energy_reserve",
            values={
                "hrvMs": 42,
                "bodyBattery": 35,
                "paceMps": 0.72,
                "cadence": 88,
                "activityLoad": 130.5,
                "baselineWindowDays": 90,
                "reserveScore": 38,
                "reserveBand": "rest_suggested",
                "heartRateDriftRatio": 0.174,
            },
            observed_at="2026-06-07T08:00:02Z",
            timestamp_s=1780828802.0,
            received_at="2026-06-07T08:00:03Z",
            session_id="session-energy",
            device_id="watch-1",
            raw_evidence_refs=("ingress-energy:payload[1]",),
            payload_sha256="d" * 64,
            capability_tags=("health", "resource", "vitals"),
        ),
    ]
    project_root = tmp_path / "project"
    project_root.mkdir()
    path = project_root / "outputs" / "sensorlogger_mqtt_sensor_vitals_records.jsonl"
    append_sensor_vitals_records_jsonl(
        path,
        sensor_vitals_records_from_observations(observations),
    )

    records, resolved_path = load_project_sensor_vitals_records(project_root)
    payload = energy_vitals_snapshot_from_sensor_vitals_records(records)
    snapshot = payload["energy_vitals_snapshot"]

    assert resolved_path == path
    assert payload["artifact_kind"] == "scout_energy_vitals_snapshot"
    assert payload["record_count"] == 2
    assert payload["selected_record_count"] == 2
    assert snapshot["subject_id"] == "session-energy"
    assert snapshot["observed_at"] == "2026-06-07T08:00:02Z"
    assert snapshot["heart_rate_bpm"] == 162
    assert snapshot["hrv_ms"] == 42
    assert snapshot["body_battery_or_provider_energy"] == 35
    assert snapshot["pace_mps"] == 0.72
    assert snapshot["cadence"] == 88
    assert snapshot["activity_load"] == 130.5
    assert snapshot["baseline_window_days"] == 90
    assert snapshot["reserve_score"] == 38
    assert snapshot["reserve_band"] == "rest_suggested"
    assert snapshot["heart_rate_drift_ratio"] == 0.174
    assert snapshot["privacy_scope"] == "private_vitals"
    assert snapshot["source_provider"] == "sensorlogger"
    assert payload["boundary"]["safety_api_called"] is False
    assert payload["boundary"]["medical_diagnosis"] is False


def test_sensor_vitals_records_build_energy_vitals_time_window_trend() -> None:
    observations = [
        ApplicationObservation(
            observation_id="obs-hr-1",
            source_adapter="sensorlogger",
            ingress_transport=IngressTransport.WAN_MQTT,
            observation_name="heart_rate",
            values={"heartRate": 120, "hrvMs": 54},
            observed_at="2026-06-07T08:00:00Z",
            timestamp_s=1780828800.0,
            received_at="2026-06-07T08:00:01Z",
            session_id="session-energy",
            device_id="watch-1",
            raw_evidence_refs=("ingress-energy:payload[0]",),
            payload_sha256="e" * 64,
            capability_tags=("health", "vitals"),
        ),
        ApplicationObservation(
            observation_id="obs-hr-2",
            source_adapter="sensorlogger",
            ingress_transport=IngressTransport.WAN_MQTT,
            observation_name="heart_rate",
            values={"heartRate": 130, "hrvMs": 50},
            observed_at="2026-06-07T08:01:00Z",
            timestamp_s=1780828860.0,
            received_at="2026-06-07T08:01:01Z",
            session_id="session-energy",
            device_id="watch-1",
            raw_evidence_refs=("ingress-energy:payload[1]",),
            payload_sha256="f" * 64,
            capability_tags=("health", "vitals"),
        ),
        ApplicationObservation(
            observation_id="obs-hr-3",
            source_adapter="sensorlogger",
            ingress_transport=IngressTransport.WAN_MQTT,
            observation_name="heart_rate",
            values={"heartRate": 145, "hrvMs": 46},
            observed_at="2026-06-07T08:04:00Z",
            timestamp_s=1780829040.0,
            received_at="2026-06-07T08:04:01Z",
            session_id="session-energy",
            device_id="watch-1",
            raw_evidence_refs=("ingress-energy:payload[2]",),
            payload_sha256="1" * 64,
            capability_tags=("health", "vitals"),
        ),
    ]
    record_set = sensor_vitals_records_from_observations(observations)

    payload = energy_vitals_time_window_from_sensor_vitals_records(
        record_set.records,
        window_s=600,
        reference_timestamp_s=1780829100.0,
        gap_threshold_s=120,
    )
    summary = payload["summary"]

    assert payload["artifact_kind"] == "scout_energy_vitals_time_window"
    assert payload["window_record_count"] == 3
    assert summary["heart_rate_trend"]["sample_count"] == 3
    assert summary["heart_rate_trend"]["trend"] == "increasing"
    assert summary["heart_rate_trend"]["first"] == 120.0
    assert summary["heart_rate_trend"]["last"] == 145.0
    assert summary["heart_rate_trend"]["delta"] == 25.0
    assert summary["hrv_trend"]["trend"] == "decreasing"
    assert summary["hrv_trend"]["delta"] == -8.0
    assert summary["record_gap_count"] == 1
    assert summary["max_gap_s"] == 180.0
    assert summary["staleness_s"] == 60.0
    assert payload["boundary"]["safety_api_called"] is False
    assert payload["boundary"]["medical_diagnosis"] is False


def test_sensor_vitals_records_build_energy_vitals_last_n_record_window() -> None:
    observations = [
        ApplicationObservation(
            observation_id="obs-hr-1",
            source_adapter="sensorlogger",
            ingress_transport=IngressTransport.WAN_MQTT,
            observation_name="heart_rate",
            values={"heartRate": 120},
            observed_at="2026-06-07T08:00:00Z",
            timestamp_s=1780828800.0,
            received_at="2026-06-07T08:00:01Z",
            session_id="session-energy",
            device_id="watch-1",
            raw_evidence_refs=("ingress-energy:payload[0]",),
            payload_sha256="2" * 64,
            capability_tags=("health", "vitals"),
        ),
        ApplicationObservation(
            observation_id="obs-hr-2",
            source_adapter="sensorlogger",
            ingress_transport=IngressTransport.WAN_MQTT,
            observation_name="heart_rate",
            values={"heartRate": 135},
            observed_at="2026-06-07T08:01:00Z",
            timestamp_s=1780828860.0,
            received_at="2026-06-07T08:01:01Z",
            session_id="session-energy",
            device_id="watch-1",
            raw_evidence_refs=("ingress-energy:payload[1]",),
            payload_sha256="3" * 64,
            capability_tags=("health", "vitals"),
        ),
        ApplicationObservation(
            observation_id="obs-hr-3",
            source_adapter="sensorlogger",
            ingress_transport=IngressTransport.WAN_MQTT,
            observation_name="heart_rate",
            values={"heartRate": 150},
            observed_at="2026-06-07T08:02:00Z",
            timestamp_s=1780828920.0,
            received_at="2026-06-07T08:02:01Z",
            session_id="session-energy",
            device_id="watch-1",
            raw_evidence_refs=("ingress-energy:payload[2]",),
            payload_sha256="4" * 64,
            capability_tags=("health", "vitals"),
        ),
    ]
    record_set = sensor_vitals_records_from_observations(observations)

    payload = energy_vitals_time_window_from_sensor_vitals_records(
        record_set.records,
        max_records=2,
    )
    summary = payload["summary"]

    assert payload["selection_mode"] == "last_n_records"
    assert payload["max_records"] == 2
    assert payload["window_record_count"] == 2
    assert summary["heart_rate_trend"]["sample_count"] == 2
    assert summary["heart_rate_trend"]["first"] == 135.0
    assert summary["heart_rate_trend"]["last"] == 150.0
    assert summary["heart_rate_trend"]["delta"] == 15.0
    assert summary["heart_rate_trend"]["trend"] == "increasing"
    assert summary["record_gap_count"] == 0
    assert payload["boundary"]["safety_api_called"] is False


def test_sensor_vitals_record_rejects_credential_like_values() -> None:
    with pytest.raises(ValidationError):
        ScoutSensorVitalsRecord(
            record_id="sensor_vitals_record:bad",
            observation_ref="obs-bad",
            source_adapter="sensorlogger",
            ingress_transport=IngressTransport.WAN_MQTT,
            observation_name="unknown",
            received_at="2026-06-05T00:00:00Z",
            values={"access_token": "must-not-be-normalized"},
            privacy_class="private_sensor",
        )
