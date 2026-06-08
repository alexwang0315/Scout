import json
import subprocess
import sys
from pathlib import Path

import pytest

from scout_energy_models import load_wearable_activity_summaries
from scout_energy_reserve import write_energy_reserve_artifacts
from scout_wearable_live_frames import write_field_observations_from_live_frame_fixture
from scout_wearable_stream_admission import run_wearable_stream_admission_dry_run


ROOT = Path(__file__).resolve().parents[1]
WEARABLE_ROOT = ROOT / "tests" / "fixtures" / "wearables"
WEARABLE_FIXTURES = [
    WEARABLE_ROOT / "apple_health_clean_activity.json",
    WEARABLE_ROOT / "apple_health_missing_hr_interval.json",
    WEARABLE_ROOT / "garmin_body_battery_provider_values.json",
]


def test_apple_live_frame_fixture_normalizes_to_stream_admission_observations(tmp_path):
    live_fixture_path = _write_apple_live_frame_fixture(tmp_path / "apple-live-frame-fixture.json")

    result = write_field_observations_from_live_frame_fixture(
        live_fixture_path,
        provider="apple_healthkit_live_fixture",
        output_dir=tmp_path / "observations",
        stream_id="stream.apple.fixture.001",
        route_segment_ref="segment.local.fixture.climb",
        expected_baseline_bpm=136,
    )
    serialized = json.dumps(result, sort_keys=True)

    assert result["artifact_kind"] == "scout_wearable_live_frame_fixture_import_result"
    assert result["source_provider"] == "apple_healthkit_live_fixture"
    assert result["transport"] == "local_live_frame_fixture"
    assert result["observation_count"] == 2
    assert result["observations"][0]["offset_s"] == 0
    assert result["observations"][1]["offset_s"] == 900
    assert result["observations"][1]["heart_rate_bpm"] == 158
    assert result["observations"][1]["expected_baseline_bpm"] == 136
    assert all(Path(path).exists() for path in result["observation_paths"])
    assert result["mutation"]["network_request_performed"] is False
    assert result["mutation"]["real_provider_api_called"] is False
    assert result["mutation"]["runtime_ingest_performed"] is False
    assert result["mutation"]["safety_api_called"] is False
    assert result["privacy"]["raw_health_payload_shared"] is False
    assert result["privacy"]["exact_timestamps_shared"] is False
    assert result["boundary"]["medical_diagnosis"] is False
    assert result["boundary"]["phase1_runtime_safety_truth"] is False
    assert "2026-05-28T" not in serialized
    assert "HKQuantityTypeIdentifierHeartRate" not in serialized
    assert "frames" not in serialized
    assert "healthkit-live-token" not in serialized
    assert "/safety/" not in serialized

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
                "stream_id": "stream.apple.fixture.001",
                "source_provider": "apple_healthkit_live_fixture",
                "transport": "local_fixture_batch",
                "baseline_path": energy["baseline_path"],
                "observation_paths": result["observation_paths"],
                "operator_confirmed_local_replay": True,
                "allow_network_fetch": False,
                "remote_provider_api_allowed": False,
                "runtime_ingest_allowed": False,
            }
        ),
        encoding="utf-8",
    )

    report = run_wearable_stream_admission_dry_run(
        request_path,
        output_dir=tmp_path / "stream_cues",
        root=tmp_path,
    ).model_dump(mode="json")

    assert report["admission_status"] == "admitted"
    assert report["admitted_observation_count"] == 2
    assert report["cue_count"] == 2
    assert report["network_fetch_performed"] is False
    assert report["remote_provider_api_used"] is False
    assert report["runtime_ingest_performed"] is False
    assert report["safety_api_called"] is False
    assert report["boundary"]["phase1_runtime_safety_truth"] is False
    assert "/safety/" not in json.dumps(report)


def test_garmin_live_frame_fixture_normalizes_without_provider_truth_or_raw_payload(tmp_path):
    live_fixture_path = _write_garmin_live_frame_fixture(tmp_path / "garmin-live-frame-fixture.json")

    result = write_field_observations_from_live_frame_fixture(
        live_fixture_path,
        provider="garmin_live_fixture",
        output_dir=tmp_path / "observations",
        stream_id="stream.garmin.fixture.001",
        expected_baseline_bpm=138,
    )
    serialized = json.dumps(result, sort_keys=True)

    assert result["source_provider"] == "garmin_live_fixture"
    assert result["observation_count"] == 2
    assert result["observations"][0]["movement_state"] == "moving"
    assert result["observations"][1]["movement_state"] == "stopped"
    assert result["observations"][1]["reserve_band_hint"] == "watch"
    assert result["observations"][1]["data_quality"]["provider_value_confidence"] == "low"
    assert result["boundary"]["provider_values_are_scout_truth"] is False
    assert result["mutation"]["raw_payload_committed"] is False
    assert "2026-05-28T" not in serialized
    assert "heartRateInBeatsPerMinute" not in serialized
    assert "providerBodyBattery" not in serialized
    assert "garmin-live-token" not in serialized
    assert '"samples":' not in serialized


def test_live_frame_fixture_cli_writes_sanitized_observations(tmp_path):
    live_fixture_path = _write_apple_live_frame_fixture(tmp_path / "apple-live-frame-fixture.json")

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "summarize-live-frame-fixture",
            "--input",
            str(live_fixture_path),
            "--provider",
            "apple_healthkit_live_fixture",
            "--output-dir",
            str(tmp_path / "observations"),
            "--stream-id",
            "stream.apple.cli.fixture.001",
            "--route-segment-ref",
            "segment.local.fixture.climb",
            "--expected-baseline-bpm",
            "136",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(completed.stdout)
    serialized = json.dumps(payload, sort_keys=True)

    assert payload["artifact_kind"] == "scout_wearable_live_frame_fixture_import_result"
    assert payload["source_provider"] == "apple_healthkit_live_fixture"
    assert payload["observation_count"] == 2
    assert all(Path(path).exists() for path in payload["observation_paths"])
    assert payload["mutation"]["network_request_performed"] is False
    assert payload["mutation"]["runtime_ingest_performed"] is False
    assert payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert "2026-05-28T" not in serialized
    assert "healthkit-live-token" not in serialized


def test_live_frame_fixture_import_rejects_live_network_or_runtime_flags(tmp_path):
    live_fixture_path = tmp_path / "live-network-flags.json"
    live_fixture_path.write_text(
        json.dumps(
            {
                "network_request_performed": True,
                "real_provider_api_called": True,
                "runtime_ingest_performed": True,
                "frames": [
                    {
                        "timestamp": "2026-05-28T07:00:00+08:00",
                        "bpm": 142,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as exc:
        write_field_observations_from_live_frame_fixture(
            live_fixture_path,
            provider="apple_healthkit_live_fixture",
            output_dir=tmp_path / "observations",
            stream_id="stream.rejected",
        )

    assert "local fixture import must not perform live network, provider API, or runtime ingest" in str(exc.value)


def _write_apple_live_frame_fixture(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "provider": "apple_healthkit",
                "auth_token_ref": "healthkit-live-token",
                "quantity_type": "HKQuantityTypeIdentifierHeartRate",
                "frames": [
                    {
                        "timestamp": "2026-05-28T07:00:00+08:00",
                        "bpm": 142,
                        "movement_state": "moving",
                    },
                    {
                        "timestamp": "2026-05-28T07:15:00+08:00",
                        "bpm": 158,
                        "movement_state": "moving",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_garmin_live_frame_fixture(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "provider": "garmin",
                "auth_token_ref": "garmin-live-token",
                "samples": [
                    {
                        "sample_time": "2026-05-28T07:00:00+08:00",
                        "heartRateInBeatsPerMinute": 144,
                        "speedMetersPerSecond": 1.1,
                        "providerBodyBattery": 47,
                    },
                    {
                        "sample_time": "2026-05-28T07:10:00+08:00",
                        "heartRateInBeatsPerMinute": 151,
                        "speedMetersPerSecond": 0.0,
                        "reserveBand": "watch",
                        "providerBodyBattery": 44,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return path
