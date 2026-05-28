import json
from pathlib import Path

import pytest

from scout_energy_models import load_wearable_activity_summaries
from scout_energy_reserve import write_energy_reserve_artifacts
from scout_wearable_stream_admission import run_wearable_stream_admission_dry_run


ROOT = Path(__file__).resolve().parents[1]
WEARABLE_ROOT = ROOT / "tests" / "fixtures" / "wearables"
WEARABLE_FIXTURES = [
    WEARABLE_ROOT / "apple_health_clean_activity.json",
    WEARABLE_ROOT / "apple_health_missing_hr_interval.json",
    WEARABLE_ROOT / "garmin_body_battery_provider_values.json",
]
FIELD_OBSERVATION = (
    WEARABLE_ROOT
    / "field_observations"
    / "high_hr_drift.json"
)


def test_local_wearable_stream_admission_dry_run_writes_advisory_cues(tmp_path):
    energy = write_energy_reserve_artifacts(
        load_wearable_activity_summaries(WEARABLE_FIXTURES, root=ROOT),
        output_dir=tmp_path / "energy",
    )
    request_path = tmp_path / "stream_admission_request.json"
    request_path.write_text(
        json.dumps(
            {
                "artifact_kind": "scout_wearable_stream_admission_request",
                "artifact_version": "wearable_stream_admission_request.v1",
                "stream_id": "stream.local.fixture.energy.001",
                "source_provider": "local_fixture_batch",
                "transport": "local_fixture_batch",
                "baseline_path": energy["baseline_path"],
                "observation_paths": [str(FIELD_OBSERVATION)],
                "operator_confirmed_local_replay": True,
                "allow_network_fetch": False,
                "remote_provider_api_allowed": False,
                "runtime_ingest_allowed": False,
                "data_quality": {
                    "heart_rate_confidence": "medium",
                    "gps_confidence": "low",
                    "missing_hr_seconds": 0,
                    "missing_hr_intervals": [],
                    "sample_cadence_s": 60,
                    "provider_value_confidence": "low",
                    "limitations": ["fixture batch admission request"],
                },
            }
        ),
        encoding="utf-8",
    )

    report = run_wearable_stream_admission_dry_run(
        request_path,
        output_dir=tmp_path / "stream_cues",
        root=tmp_path,
    )
    payload = report.model_dump(mode="json")

    assert payload["artifact_kind"] == "scout_wearable_stream_admission_report"
    assert payload["transport"] == "local_fixture_batch"
    assert payload["admission_status"] == "admitted"
    assert payload["admitted_observation_count"] == 1
    assert payload["rejected_observation_count"] == 0
    assert payload["cue_count"] == 1
    assert Path(payload["cue_paths"][0]).exists()
    assert payload["cue_summaries"][0]["cue_band"] == "rest_suggested"
    assert payload["voice_cues"][0]["boundary"]["endpoint_calls"] == []
    assert payload["voice_cues"][0]["boundary"]["safety_decision_change_allowed"] is False
    assert payload["network_fetch_performed"] is False
    assert payload["remote_provider_api_used"] is False
    assert payload["runtime_ingest_performed"] is False
    assert payload["safety_api_called"] is False
    assert payload["privacy"]["raw_health_payload_shared"] is False
    assert payload["privacy"]["raw_track_shared"] is False
    assert payload["privacy"]["exact_timestamps_shared"] is False
    assert payload["boundary"]["medical_diagnosis"] is False
    assert payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert payload["boundary"]["safety_api_calls_allowed"] is False
    assert "/safety/" not in json.dumps(payload)


def test_wearable_stream_admission_rejects_provider_api_or_runtime_ingest(tmp_path):
    energy = write_energy_reserve_artifacts(
        load_wearable_activity_summaries(WEARABLE_FIXTURES, root=ROOT),
        output_dir=tmp_path / "energy",
    )
    request_path = tmp_path / "stream_admission_request.json"
    request_path.write_text(
        json.dumps(
            {
                "artifact_kind": "scout_wearable_stream_admission_request",
                "artifact_version": "wearable_stream_admission_request.v1",
                "stream_id": "stream.provider.live.rejected",
                "source_provider": "apple_healthkit_live_api",
                "transport": "local_fixture_batch",
                "baseline_path": energy["baseline_path"],
                "observation_paths": [str(FIELD_OBSERVATION)],
                "operator_confirmed_local_replay": True,
                "allow_network_fetch": True,
                "remote_provider_api_allowed": True,
                "runtime_ingest_allowed": True,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as exc:
        run_wearable_stream_admission_dry_run(
            request_path,
            output_dir=tmp_path / "stream_cues",
            root=tmp_path,
        )

    assert "must not fetch network data" in str(exc.value)
