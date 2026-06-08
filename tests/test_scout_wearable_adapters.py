import json
import subprocess
import sys
from pathlib import Path

import pytest

from scout_wearable_adapters import (
    normalize_wearable_import_envelope,
    write_normalized_wearable_imports,
)
from scout_wearable_validator import validate_wearable_activity_summary_contract


ROOT = Path(__file__).resolve().parents[1]
ADAPTER_ROOT = ROOT / "tests" / "fixtures" / "wearables" / "adapters"
ADAPTER_FIXTURES = [
    ADAPTER_ROOT / "apple_health_sanitized_workout.json",
    ADAPTER_ROOT / "garmin_connect_sanitized_activity.json",
    ADAPTER_ROOT / "gpx_derived_summary.json",
    ADAPTER_ROOT / "fit_derived_summary.json",
    ADAPTER_ROOT / "tcx_derived_summary.json",
]


def test_normalizes_sanitized_apple_health_export_to_provider_neutral_summary():
    activity = normalize_wearable_import_envelope(ADAPTER_FIXTURES[0], root=ROOT)
    payload = activity.model_dump(mode="json")

    assert activity.artifact_kind == "scout_wearable_activity_summary"
    assert activity.source_provider == "apple_health_export"
    assert activity.source_path == "tests/fixtures/wearables/adapters/apple_health_sanitized_workout.json"
    assert len(activity.sha256) == 64
    assert activity.heart_rate.sample_count == 5
    assert activity.data_quality.heart_rate_confidence == "high"
    assert "normalized from sanitized source summary" in " ".join(activity.data_quality.limitations)
    assert payload["privacy"]["raw_health_payload_shared"] is False
    assert payload["privacy"]["raw_track_shared"] is False
    assert payload["privacy"]["exact_timestamps_shared"] is False
    assert payload["boundary"]["medical_diagnosis"] is False
    assert payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert payload["boundary"]["safety_api_calls_allowed"] is False
    assert "started_at" not in json.dumps(payload)
    assert "<trkpt" not in json.dumps(payload)


def test_normalizes_garmin_source_values_without_promoting_them_to_scout_truth():
    activity = normalize_wearable_import_envelope(ADAPTER_FIXTURES[1], root=ROOT)

    assert activity.source_provider == "garmin_connect_export"
    assert activity.body_energy_provider_values.garmin_body_battery_end == 38
    assert activity.body_energy_provider_values.garmin_stress_avg == 59
    assert activity.body_energy_provider_values.source_value_only is True
    assert activity.body_energy_provider_values.scout_truth is False


def test_normalizes_file_derived_gpx_fit_tcx_summaries_without_raw_tracks():
    activities = [
        normalize_wearable_import_envelope(path, root=ROOT)
        for path in ADAPTER_FIXTURES[2:]
    ]

    assert [activity.source_provider for activity in activities] == [
        "gpx_derived_summary",
        "fit_derived_summary",
        "tcx_derived_summary",
    ]
    for activity in activities:
        payload = activity.model_dump(mode="json")
        assert activity.source_path.startswith("tests/fixtures/wearables/adapters/")
        assert len(activity.sha256) == 64
        assert payload["privacy"]["raw_track_shared"] is False
        assert payload["privacy"]["exact_timestamps_shared"] is False
        assert payload["boundary"]["phase1_runtime_safety_truth"] is False
        assert "<trkpt" not in json.dumps(payload)


def test_rejects_raw_provider_payload_or_exact_time_fields(tmp_path):
    source = json.loads(ADAPTER_FIXTURES[0].read_text(encoding="utf-8"))
    source["started_at"] = "2026-05-25T00:00:00Z"
    source["raw_health_payload"] = {"forbidden": True}
    bad_path = tmp_path / "bad_adapter_input.json"
    bad_path.write_text(json.dumps(source), encoding="utf-8")

    with pytest.raises(ValueError) as exc:
        normalize_wearable_import_envelope(bad_path, root=tmp_path)

    assert "forbidden raw adapter fields present" in str(exc.value)
    assert "started_at" in str(exc.value)
    assert "raw_health_payload" in str(exc.value)


def test_writes_normalized_summaries_and_validates_contract(tmp_path):
    output_dir = tmp_path / "normalized"
    result = write_normalized_wearable_imports(
        ADAPTER_FIXTURES,
        output_dir=output_dir,
        root=ROOT,
    )

    assert result["artifact_kind"] == "scout_wearable_adapter_normalization_batch"
    assert result["source_provider"] == "mixed_wearable_adapter_inputs"
    assert result["source_path"] == "aggregate:tests/fixtures/wearables/adapters"
    assert len(result["sha256"]) == 64
    assert result["activity_count"] == 5
    assert result["privacy"]["raw_health_payload_shared"] is False
    assert result["boundary"]["medical_diagnosis"] is False
    for normalized_path in result["normalized_paths"]:
        report = validate_wearable_activity_summary_contract(Path(normalized_path), root=ROOT)
        assert report.valid is True


def test_energy_reserve_cli_normalizes_then_builds_from_adapter_outputs(tmp_path):
    normalized_dir = tmp_path / "normalized"
    normalize_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "normalize",
            "--input",
            str(ADAPTER_FIXTURES[0]),
            "--input",
            str(ADAPTER_FIXTURES[1]),
            "--input",
            str(ADAPTER_FIXTURES[2]),
            "--output-dir",
            str(normalized_dir),
            "--root",
            str(ROOT),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    normalize_payload = json.loads(normalize_completed.stdout)
    build_dir = tmp_path / "energy"
    build_args = [
        sys.executable,
        "-m",
        "scout_energy_reserve",
        "build",
    ]
    for normalized_path in normalize_payload["normalized_paths"]:
        build_args.extend(["--activity", normalized_path])
    build_args.extend(
        [
            "--output-dir",
            str(build_dir),
            "--reference-date",
            "2026-05-27",
            "--root",
            str(tmp_path),
        ]
    )
    build_completed = subprocess.run(
        build_args,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    build_payload = json.loads(build_completed.stdout)

    assert normalize_payload["artifact_kind"] == "scout_wearable_adapter_normalization_batch"
    assert normalize_payload["data_quality"]["missing_hr_seconds"] == 4500
    assert normalize_payload["privacy"]["raw_track_shared"] is False
    assert normalize_payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert build_payload["artifact_kind"] == "scout_energy_reserve_artifact_export"
    assert build_payload["baseline"]["activity_count"] == 3
    assert build_payload["privacy"]["raw_samples_embedded"] is False
    assert build_payload["boundary"]["safety_api_calls_allowed"] is False
    assert "/safety/" not in json.dumps(normalize_payload)
    assert "<trkpt" not in json.dumps(build_payload)
