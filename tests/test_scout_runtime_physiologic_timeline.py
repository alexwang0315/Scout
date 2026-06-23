from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from scout_runtime_physiologic_integration import (
    PHYSIOLOGIC_GATE_EVIDENCE_JSONL,
    run_physio_integration_replay,
    write_physio_review_from_health_auto_export,
)
from scout_runtime_physiologic_timeline import (
    build_physio_timeline_projection,
    write_physio_timeline_projection,
)


def test_physio_timeline_projection_builds_ui_ready_events_without_raw_payload(tmp_path: Path) -> None:
    vitals_path = _write_sensorlogger_vitals_jsonl(tmp_path / "sensorlogger_mqtt_sensor_vitals_records.jsonl")
    output_dir = tmp_path / "physio-gate"
    run_physio_integration_replay(
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

    projection = build_physio_timeline_projection(
        artifact_dir=output_dir,
        session_id="debug.physio.fixture",
        mission_id="fixture.route",
    )
    serialized = json.dumps(projection.model_dump(mode="json"), sort_keys=True)
    events = projection.events

    assert projection.artifact_kind == "scout_physiologic_timeline_projection"
    assert projection.event_count == 4
    assert projection.boundary.medical_diagnosis is False
    assert projection.boundary.phase1_runtime_safety_truth is False
    assert projection.boundary.safety_api_called is False
    assert {event.kind for event in events} == {
        "physiologic_gate_window",
        "physiologic_gate_safety_event",
        "physiologic_gate_reducer_dry_run",
    }
    assert [event.sequence for event in events] == [1, 2, 3, 4]
    assert all(event.timestamp.startswith("offset:") for event in events)
    assert events[0].payload["window_index"] == 1
    assert events[0].payload["segment_id"] == "fixture.segment"
    assert "fixture.segment" in events[0].map_refs
    assert events[0].payload["boundary"]["medical_diagnosis"] is False
    assert events[0].payload["boundary"]["runtime_safety_truth"] is False
    assert events[0].payload["source_refs"]
    assert projection.counts["by_kind"]["physiologic_gate_window"] == 2
    assert projection.counts["with_map_ref_count"] == 4
    assert "raw_payload" not in serialized
    assert "heartRateData" not in serialized
    assert "private-route.gpx" not in serialized
    assert "/safety/" not in serialized
    assert "2026-06-22" not in serialized
    assert "latitude" not in serialized
    assert "longitude" not in serialized


def test_physio_timeline_projection_writes_review_capsule_event(tmp_path: Path) -> None:
    zip_path = _write_health_auto_export_zip(tmp_path / "HealthAutoExport_fixture.zip")
    output_dir = tmp_path / "physio-review"
    write_physio_review_from_health_auto_export(
        zip_path,
        output_dir=output_dir,
        activity_type="walking",
        window_minutes=15,
    )

    output_path = output_dir / "physiologic_timeline_projection.json"
    projection = write_physio_timeline_projection(
        output_path=output_path,
        artifact_dir=output_dir,
        session_id="debug.physio.review",
    )
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert output_path.exists()
    assert projection.event_count == 1
    assert projection.events[0].kind == "physiologic_review_capsule"
    assert projection.events[0].phase == "phase4"
    assert projection.events[0].timestamp == "offset:batch-review"
    assert payload["events"][0]["payload"]["projection_only"] is True
    assert "heartRateData" not in json.dumps(payload, sort_keys=True)
    assert "private-route.gpx" not in json.dumps(payload, sort_keys=True)


def test_physio_timeline_projection_rejects_raw_payload_fields(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "bad-physio-gate"
    artifact_dir.mkdir()
    (artifact_dir / PHYSIOLOGIC_GATE_EVIDENCE_JSONL).write_text(
        json.dumps({"artifact_kind": "bad", "raw_payload": {"heartRateData": []}}) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="forbidden raw physiologic artifact fields"):
        build_physio_timeline_projection(artifact_dir=artifact_dir)


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
