from __future__ import annotations

import json
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from admin_api import create_admin_app
from scout_runtime_physiologic_integration import (
    PHYSIOLOGIC_ARTIFACT_INDEX_FILENAME,
    PHYSIOLOGIC_REDUCER_DRY_RUN_FILENAME,
    PHYSIOLOGIC_SAFETY_GATE_EVENT_FILENAME,
    build_windowed_replay_from_sensorlogger_jsonl,
    run_physio_integration_replay,
    write_physio_review_from_health_auto_export,
)


def test_health_auto_export_review_writes_artifact_index_without_raw_payload(tmp_path: Path) -> None:
    zip_path = _write_health_auto_export_zip(tmp_path / "HealthAutoExport_fixture.zip")
    output_dir = tmp_path / "physio-review"

    result = write_physio_review_from_health_auto_export(
        zip_path,
        output_dir=output_dir,
        activity_type="walking",
        window_minutes=15,
    )

    analysis_path = Path(result["paths"]["analysis"])
    capsule_path = Path(result["paths"]["capsule"])
    index_path = output_dir / PHYSIOLOGIC_ARTIFACT_INDEX_FILENAME
    index = json.loads(index_path.read_text(encoding="utf-8"))
    serialized = json.dumps(index, sort_keys=True)

    assert analysis_path.exists()
    assert capsule_path.exists()
    assert index["artifact_kind"] == "scout_physiologic_artifact_index"
    assert index["artifact_count"] == 2
    assert {item["handoff_role"] for item in index["artifacts"]} == {
        "review_evidence",
        "admin_review_capsule",
    }
    assert index["privacy"]["raw_health_payload_shared"] is False
    assert index["privacy"]["exact_timestamps_shared"] is False
    assert index["boundary"]["medical_diagnosis"] is False
    assert index["boundary"]["phase1_runtime_safety_truth"] is False
    assert "heartRateData" not in serialized
    assert "private-route.gpx" not in serialized
    assert "/safety/" not in serialized


def test_sensorlogger_replay_builds_15_minute_windows_gate_event_and_reducer(tmp_path: Path) -> None:
    vitals_path = _write_sensorlogger_vitals_jsonl(tmp_path / "sensorlogger_mqtt_sensor_vitals_records.jsonl")
    output_dir = tmp_path / "physio-gate"

    replay = build_windowed_replay_from_sensorlogger_jsonl(
        vitals_path,
        window_minutes=15,
        reference_pace_mps=0.75,
    )
    result = run_physio_integration_replay(
        vitals_path,
        output_dir=output_dir,
        route_context={
            "route_id": "fixture.route",
            "segment_id": "fixture.segment",
            "distance_to_next_checkpoint_m": 1200,
            "estimated_minutes_to_next_checkpoint": 45,
            "estimated_minutes_to_planned_camp": 140,
            "daylight_buffer_minutes": 50,
            "altitude_m": 2300,
            "external_pressure_flags": ["companion_pace_pressure"],
        },
        baseline_context={
            "personal_envelope_available": True,
            "reserve_band": "watch",
            "reserve_score": 42,
            "expected_heart_rate_bpm": 136,
            "expected_pace_mps": 0.75,
            "reset_cue_work_output_kj": 240,
            "stable_baseline_activity_count": 38,
        },
        window_minutes=15,
        max_records=100,
    )

    event = json.loads((output_dir / PHYSIOLOGIC_SAFETY_GATE_EVENT_FILENAME).read_text(encoding="utf-8"))
    reducer = json.loads((output_dir / PHYSIOLOGIC_REDUCER_DRY_RUN_FILENAME).read_text(encoding="utf-8"))
    status = json.loads(Path(result.paths["status"]).read_text(encoding="utf-8"))
    serialized = json.dumps(status, sort_keys=True)

    assert replay.window_minutes == 15
    assert replay.window_count == 2
    assert replay.windows[0].movement_efficiency_ratio_to_session_reference < 0.7
    assert result.window_count == 2
    assert result.gate_output_count == 2
    assert event["artifact_kind"] == "scout_physiologic_safety_gate_event"
    assert event["gate_id"] == "physiologic_gate"
    assert event["state_candidate"] in {"stop_and_rest", "retreat_suggested", "alert_candidate"}
    assert event["severity"] in {"rest", "retreat_review", "alert_review"}
    assert event["safety_reducer_required"] is True
    assert event["phase1_l0_l4_state_mutated"] is False
    assert event["safety_api_called"] is False
    assert reducer["artifact_kind"] == "scout_physiologic_reducer_dry_run"
    assert reducer["recommendation"] in {"stop_and_rest", "retreat_review", "alert_review"}
    assert reducer["phase1_l0_l4_state_mutated"] is False
    assert status["boundary"]["phase1_l0_l4_state_mutated"] is False
    assert status["boundary"]["safety_api_called"] is False
    assert "2026-06-22" not in serialized
    assert "raw_payload" not in serialized
    assert "/safety/" not in serialized


def test_admin_wearable_physio_sensorlogger_replay_endpoint(tmp_path: Path, monkeypatch) -> None:
    data_root = tmp_path / "data"
    monkeypatch.setenv("SCOUT_DATA_ROOT", str(data_root))
    vitals_path = _write_sensorlogger_vitals_jsonl(tmp_path / "vitals.jsonl")
    client = TestClient(create_admin_app())

    response = client.post(
        "/admin/wearables/physio-sensorlogger-replay",
        json={
            "sensorlogger_vitals_path": str(vitals_path),
            "route_context": {
                "route_id": "fixture.route",
                "segment_id": "fixture.segment",
                "distance_to_next_checkpoint_m": 500,
                "estimated_minutes_to_next_checkpoint": 25,
                "estimated_minutes_to_planned_camp": 90,
                "daylight_buffer_minutes": 80,
            },
            "baseline_context": {
                "personal_envelope_available": True,
                "reserve_band": "watch",
                "expected_heart_rate_bpm": 136,
                "expected_pace_mps": 0.75,
                "reset_cue_work_output_kj": 240,
            },
            "output_dir": "physio-api-test",
        },
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["artifact_kind"] == "scout_physiologic_integration_run_result"
    assert payload["boundary"]["medical_diagnosis"] is False
    assert payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert Path(payload["paths"]["safety_gate_event"]).exists()


def _write_sensorlogger_vitals_jsonl(path: Path) -> Path:
    rows = []
    cumulative_distance = 0.0
    for index in range(30):
        cumulative_distance += 5.0 if index < 15 else 12.0
        rows.append(
            {
                "elapsed_s": index * 60,
                "values": {
                    "heartRate": 172 if index < 15 else 166,
                    "pedometerDistance": cumulative_distance,
                    "activeEnergyDeltaKJ": 20.0 if index < 15 else 14.0,
                    "cadence": 72 if index < 15 else 78,
                },
            }
        )
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return path


def _write_health_auto_export_zip(path: Path) -> Path:
    payload = {
        "data": {
            "workouts": [
                _walk_workout(
                    "walk-001",
                    day="2026-06-02",
                    distances_km=[0.55, 0.62],
                    active_energy_kj=[80, 90],
                    heart_rates=[118] * 15 + [126] * 15,
                )
            ],
            "metrics": [{"name": "vo2_max", "data": [{"qty": 36.9, "units": "ml/kg/min"}]}],
        }
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("HealthAutoExport.json", json.dumps(payload, ensure_ascii=False))
        archive.writestr("private-route.gpx", "<gpx />")
    return path


def _walk_workout(
    workout_id: str,
    *,
    day: str,
    distances_km: list[float],
    active_energy_kj: list[int],
    heart_rates: list[int],
) -> dict:
    duration_min = len(heart_rates)
    distance_rows = []
    energy_rows = []
    hr_rows = []
    for minute, heart_rate in enumerate(heart_rates):
        window = minute // 15
        row_date = f"{day} 08:{minute:02d}:00 +0800"
        distance_rows.append({"date": row_date, "qty": distances_km[window] / 15.0, "units": "km"})
        energy_rows.append({"date": row_date, "qty": active_energy_kj[window] / 15.0, "units": "kJ"})
        hr_rows.append({"date": row_date, "Avg": heart_rate, "Max": heart_rate, "Min": heart_rate, "units": "bpm"})
    return {
        "id": workout_id,
        "name": "步行",
        "start": f"{day} 08:00:00 +0800",
        "end": f"{day} 08:{duration_min:02d}:00 +0800",
        "duration": duration_min * 60,
        "distance": {"qty": sum(distances_km), "units": "km"},
        "activeEnergyBurned": {"qty": sum(active_energy_kj), "units": "kJ"},
        "walkingAndRunningDistance": distance_rows,
        "activeEnergy": energy_rows,
        "heartRateData": hr_rows,
        "route": [{"latitude": 24.0, "longitude": 121.0, "timestamp": f"{day}T08:00:00+08:00"}],
    }
