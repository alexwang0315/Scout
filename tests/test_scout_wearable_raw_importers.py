import json
import struct
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from scout_wearable_raw_importers import (
    inspect_provider_archive,
    summarize_raw_wearable_file,
    write_sanitized_import_batch_from_provider_api_fixture,
    write_sanitized_import_batch_from_provider_archive,
    write_sanitized_import_batch_from_raw_file,
    write_sanitized_import_from_raw_file,
)
from scout_wearable_validator import validate_wearable_activity_summary_contract


ROOT = Path(__file__).resolve().parents[1]


def test_summarizes_raw_gpx_to_sanitized_import_without_embedding_track(tmp_path):
    gpx_path = _write_raw_gpx(tmp_path / "activity.gpx")

    envelope = summarize_raw_wearable_file(
        gpx_path,
        source_format="gpx",
        activity_id="raw.gpx.fixture.001",
    )
    payload = envelope.model_dump(mode="json")

    assert payload["artifact_kind"] == "scout_wearable_sanitized_import"
    assert payload["source_format"] == "gpx_derived_summary"
    assert payload["activity_date"] == "2026-05-27"
    assert payload["duration_s"] == 600
    assert payload["moving_time_s"] == 600
    assert payload["distance_m"] > 0
    assert payload["ascent_m"] == 20
    assert payload["heart_rate"]["sample_count"] == 3
    assert payload["heart_rate"]["samples"] == []
    assert payload["privacy"]["raw_track_shared"] is False
    assert payload["privacy"]["raw_health_payload_shared"] is False
    assert payload["privacy"]["exact_timestamps_shared"] is False
    assert payload["boundary"]["medical_diagnosis"] is False
    assert payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert "2026-05-27T" not in json.dumps(payload)
    assert "<trkpt" not in json.dumps(payload)
    assert "LatitudeDegrees" not in json.dumps(payload)


def test_summarizes_raw_tcx_to_sanitized_import_without_embedding_track(tmp_path):
    tcx_path = _write_raw_tcx(tmp_path / "activity.tcx")

    result = write_sanitized_import_from_raw_file(
        tcx_path,
        source_format="tcx",
        output_dir=tmp_path / "sanitized",
        activity_id="raw.tcx.fixture.001",
    )
    payload = result["sanitized_import"]

    assert result["artifact_kind"] == "scout_wearable_raw_import_summary_result"
    assert result["mutation"]["raw_payload_committed"] is False
    assert Path(result["sanitized_import_path"]).exists()
    assert payload["source_format"] == "tcx_derived_summary"
    assert payload["activity_date"] == "2026-05-27"
    assert payload["duration_s"] == 600
    assert payload["distance_m"] > 0
    assert payload["ascent_m"] == 25
    assert payload["heart_rate"]["sample_count"] == 3
    assert payload["privacy"]["raw_track_shared"] is False
    assert payload["boundary"]["safety_api_calls_allowed"] is False
    assert "2026-05-27T" not in json.dumps(payload)
    assert "Trackpoint" not in json.dumps(payload)


def test_summarizes_apple_health_export_xml_without_embedding_raw_health_payload(tmp_path):
    xml_path = _write_apple_health_export_xml(tmp_path / "apple_health_export.xml")

    result = write_sanitized_import_from_raw_file(
        xml_path,
        source_format="apple_health_export",
        output_dir=tmp_path / "sanitized",
        activity_id="raw.apple_health.fixture.001",
    )
    payload = result["sanitized_import"]
    serialized = json.dumps(payload)

    assert result["artifact_kind"] == "scout_wearable_raw_import_summary_result"
    assert result["mutation"]["raw_payload_committed"] is False
    assert result["mutation"]["raw_health_payload_shared"] is False
    assert payload["source_format"] == "apple_health_export_summary"
    assert payload["activity_date"] == "2026-05-27"
    assert payload["duration_s"] == 3600
    assert payload["moving_time_s"] == 3600
    assert payload["distance_m"] == 4200
    assert payload["heart_rate"]["sample_count"] == 3
    assert payload["heart_rate"]["avg_bpm"] == 132
    assert payload["heart_rate"]["samples"] == []
    assert payload["privacy"]["raw_health_payload_shared"] is False
    assert payload["privacy"]["raw_track_shared"] is False
    assert payload["privacy"]["exact_timestamps_shared"] is False
    assert payload["boundary"]["medical_diagnosis"] is False
    assert payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert "2026-05-27 07:" not in serialized
    assert "HKQuantityTypeIdentifierHeartRate" not in serialized
    assert "Record" not in serialized
    assert "startDate" not in serialized


def test_summarizes_garmin_connect_export_json_without_promoting_provider_values(tmp_path):
    json_path = _write_garmin_connect_export_json(tmp_path / "garmin_activity.json")

    result = write_sanitized_import_from_raw_file(
        json_path,
        source_format="garmin_connect_export",
        output_dir=tmp_path / "sanitized",
        activity_id="raw.garmin.fixture.001",
    )
    payload = result["sanitized_import"]
    serialized = json.dumps(payload)

    assert result["artifact_kind"] == "scout_wearable_raw_import_summary_result"
    assert result["mutation"]["raw_payload_committed"] is False
    assert result["mutation"]["raw_health_payload_shared"] is False
    assert payload["source_format"] == "garmin_connect_activity_summary"
    assert payload["activity_date"] == "2026-05-27"
    assert payload["duration_s"] == 5400
    assert payload["moving_time_s"] == 5000
    assert payload["distance_m"] == 5600
    assert payload["ascent_m"] == 320
    assert payload["descent_m"] == 315
    assert payload["heart_rate"]["sample_count"] == 4
    assert payload["heart_rate"]["samples"] == []
    assert payload["body_energy_provider_values"]["garmin_body_battery_start"] == 68
    assert payload["body_energy_provider_values"]["garmin_body_battery_end"] == 38
    assert payload["body_energy_provider_values"]["garmin_stress_avg"] == 59
    assert payload["body_energy_provider_values"]["source_value_only"] is True
    assert payload["body_energy_provider_values"]["scout_truth"] is False
    assert payload["privacy"]["raw_health_payload_shared"] is False
    assert payload["privacy"]["raw_track_shared"] is False
    assert payload["privacy"]["exact_timestamps_shared"] is False
    assert payload["boundary"]["medical_diagnosis"] is False
    assert payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert "2026-05-27T" not in serialized
    assert "startTimeGMT" not in serialized
    assert "heartRateSamples" not in serialized
    assert "geoPolylineDTO" not in serialized


def test_batch_summarizes_apple_health_export_without_embedding_raw_records(tmp_path):
    xml_path = _write_apple_health_batch_export_xml(tmp_path / "apple_health_export.xml")

    result = write_sanitized_import_batch_from_raw_file(
        xml_path,
        source_format="apple_health_export",
        output_dir=tmp_path / "sanitized",
        activity_id_prefix="raw.apple_health.batch",
    )
    serialized = json.dumps(result)

    assert result["artifact_kind"] == "scout_wearable_raw_import_batch_summary_result"
    assert result["activity_count"] == 2
    assert result["source_provider"] == "apple_health_export_summary"
    assert result["mutation"]["raw_payload_committed"] is False
    assert result["mutation"]["raw_health_payload_shared"] is False
    assert [item["activity_id"] for item in result["results"]] == [
        "raw.apple_health.batch.001",
        "raw.apple_health.batch.002",
    ]
    assert [item["sanitized_import"]["activity_date"] for item in result["results"]] == [
        "2026-05-26",
        "2026-05-27",
    ]
    assert all(Path(path).exists() for path in result["sanitized_import_paths"])
    assert all(item["privacy"]["exact_timestamps_shared"] is False for item in result["results"])
    assert all(item["boundary"]["phase1_runtime_safety_truth"] is False for item in result["results"])
    assert "HKQuantityTypeIdentifierHeartRate" not in serialized
    assert "startDate" not in serialized
    assert "Record" not in serialized


def test_provider_archive_discovers_apple_health_export_directory_without_extracting_raw_payload(tmp_path):
    archive_dir = tmp_path / "apple_export_archive"
    export_path = archive_dir / "apple_health" / "export.xml"
    export_path.parent.mkdir(parents=True)
    _write_apple_health_batch_export_xml(export_path)

    result = write_sanitized_import_batch_from_provider_archive(
        archive_dir,
        source_format="apple_health_export",
        output_dir=tmp_path / "sanitized",
        activity_id_prefix="archive.apple_health",
    )
    serialized = json.dumps(result)

    assert result["artifact_kind"] == "scout_wearable_provider_archive_import_result"
    assert result["archive_kind"] == "directory"
    assert result["archive_member_path"] == "apple_health/export.xml"
    assert len(result["archive_member_sha256"]) == 64
    assert len(result["sha256"]) == 64
    assert result["activity_count"] == 2
    assert result["mutation"]["archive_extracted_to_workspace"] is False
    assert result["mutation"]["raw_payload_committed"] is False
    assert all(Path(path).exists() for path in result["sanitized_import_paths"])
    assert "HKQuantityTypeIdentifierHeartRate" not in serialized
    assert "startDate" not in serialized
    assert "Record" not in serialized


def test_provider_archive_manifest_maps_garmin_production_zip_without_raw_payload(tmp_path):
    activities_path = _write_garmin_connect_batch_export_json(tmp_path / "activities.json")
    activity_detail_path = _write_garmin_connect_export_json(tmp_path / "activity_987654323.json")
    wellness_path = tmp_path / "wellness.json"
    wellness_path.write_text(
        json.dumps({"sleep": {"startTimeGMT": "2026-05-27T12:00:00Z"}}),
        encoding="utf-8",
    )
    fit_path = _write_raw_fit(tmp_path / "activity.fit")
    zip_path = tmp_path / "garmin-production-export.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.write(activities_path, "DI-Connect-Fitness/Activities/activities.json")
        archive.write(activity_detail_path, "DI-Connect-Fitness/ActivityDetails/activity_987654323.json")
        archive.write(wellness_path, "DI-Connect-Wellness/Wellness/wellness.json")
        archive.write(fit_path, "DI-Connect-Fitness/Activities/activity.fit")
        archive.writestr("__MACOSX/._activities.json", "{}")

    manifest = inspect_provider_archive(
        zip_path,
        source_format="garmin_connect_export",
    )
    serialized = json.dumps(manifest)

    assert manifest["artifact_kind"] == "scout_wearable_provider_archive_manifest"
    assert manifest["archive_kind"] == "zip"
    assert manifest["source_provider"] == "garmin_connect_provider_archive"
    assert manifest["candidate_count"] == 4
    assert manifest["supported_member_count"] == 3
    assert manifest["deferred_member_count"] == 0
    assert manifest["selected_member_path"] == "DI-Connect-Fitness/Activities/activities.json"
    assert [member["member_path"] for member in manifest["supported_members"]] == [
        "DI-Connect-Fitness/Activities/activities.json",
        "DI-Connect-Fitness/ActivityDetails/activity_987654323.json",
        "DI-Connect-Fitness/Activities/activity.fit",
    ]
    fit_members = [
        member for member in manifest["members"] if member["provider_role"] == "garmin_fit_activity_file"
    ]
    assert fit_members[0]["supported_for_import"] is True
    assert fit_members[0]["deferred"] is False
    assert fit_members[0]["source_format"] == "fit"
    assert manifest["mutation"]["archive_extracted_to_workspace"] is False
    assert manifest["mutation"]["raw_payload_committed"] is False
    assert manifest["privacy"]["raw_health_payload_shared"] is False
    assert manifest["privacy"]["raw_track_shared"] is False
    assert manifest["boundary"]["phase1_runtime_safety_truth"] is False
    assert "__MACOSX" not in serialized
    assert "startTimeGMT" not in serialized
    assert "geoPolylineDTO" not in serialized
    assert "heartRateSamples" not in serialized


def test_raw_importer_cli_inspects_provider_archive_without_writing_imports(tmp_path):
    activities_path = _write_garmin_connect_batch_export_json(tmp_path / "activities.json")
    fit_path = _write_raw_fit(tmp_path / "activity.fit")
    zip_path = tmp_path / "garmin-production-export.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.write(activities_path, "DI-Connect-Fitness/Activities/activities.json")
        archive.write(fit_path, "DI-Connect-Fitness/Activities/activity.fit")

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "inspect-provider-archive",
            "--input",
            str(zip_path),
            "--source-format",
            "garmin_connect_export",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(completed.stdout)
    serialized = json.dumps(payload)

    assert payload["artifact_kind"] == "scout_wearable_provider_archive_manifest"
    assert payload["supported_member_count"] == 2
    assert payload["deferred_member_count"] == 0
    assert payload["mutation"]["raw_payload_committed"] is False
    assert not list(tmp_path.glob("*.sanitized_import.json"))
    assert "heartRateSamples" not in serialized
    assert "startTimeGMT" not in serialized


def test_provider_archive_import_summarizes_multiple_garmin_supported_members(tmp_path):
    activities_path = _write_garmin_connect_batch_export_json(tmp_path / "activities.json")
    activity_detail_path = _write_garmin_connect_export_json(tmp_path / "activity_987654323.json")
    fit_path = _write_raw_fit(tmp_path / "activity.fit")
    zip_path = tmp_path / "garmin-production-export.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.write(activities_path, "DI-Connect-Fitness/Activities/activities.json")
        archive.write(activity_detail_path, "DI-Connect-Fitness/ActivityDetails/activity_987654323.json")
        archive.write(fit_path, "DI-Connect-Fitness/Activities/activity.fit")

    result = write_sanitized_import_batch_from_provider_archive(
        zip_path,
        source_format="garmin_connect_export",
        output_dir=tmp_path / "sanitized",
        activity_id_prefix="archive.garmin.production",
    )
    serialized = json.dumps(result)

    assert result["artifact_kind"] == "scout_wearable_provider_archive_import_result"
    assert result["archive_kind"] == "zip"
    assert result["activity_count"] == 4
    assert result["archive_member_path"] == "DI-Connect-Fitness/Activities/activities.json"
    assert [member["member_path"] for member in result["archive_members"]] == [
        "DI-Connect-Fitness/Activities/activities.json",
        "DI-Connect-Fitness/ActivityDetails/activity_987654323.json",
        "DI-Connect-Fitness/Activities/activity.fit",
    ]
    assert [item["activity_id"] for item in result["results"]] == [
        "archive.garmin.production.001.001",
        "archive.garmin.production.001.002",
        "archive.garmin.production.002.001",
        "archive.garmin.production.003.001",
    ]
    assert result["results"][-1]["sanitized_import"]["source_format"] == "fit_derived_summary"
    assert all(Path(path).exists() for path in result["sanitized_import_paths"])
    assert result["archive_manifest"]["deferred_member_count"] == 0
    assert result["mutation"]["archive_extracted_to_workspace"] is False
    assert result["mutation"]["raw_payload_committed"] is False
    assert result["mutation"]["raw_track_shared"] is False
    assert result["boundary"]["medical_diagnosis"] is False
    assert "geoPolylineDTO" not in serialized
    assert "heartRateSamples" not in serialized
    assert "startTimeGMT" not in serialized
    assert "fit_records" not in serialized


def test_summarizes_raw_fit_to_sanitized_import_without_embedding_track(tmp_path):
    fit_path = _write_raw_fit(tmp_path / "activity.fit")

    result = write_sanitized_import_from_raw_file(
        fit_path,
        source_format="fit",
        output_dir=tmp_path / "sanitized",
        activity_id="raw.fit.fixture.001",
    )
    payload = result["sanitized_import"]
    serialized = json.dumps(payload)

    assert result["artifact_kind"] == "scout_wearable_raw_import_summary_result"
    assert result["mutation"]["raw_payload_committed"] is False
    assert result["mutation"]["source_file_mutated"] is False
    assert payload["source_format"] == "fit_derived_summary"
    assert payload["activity_date"] == "2026-05-27"
    assert payload["duration_s"] == 600
    assert payload["distance_m"] > 0
    assert payload["ascent_m"] == 20
    assert payload["heart_rate"]["sample_count"] == 3
    assert payload["heart_rate"]["samples"] == []
    assert payload["privacy"]["raw_track_shared"] is False
    assert payload["privacy"]["raw_health_payload_shared"] is False
    assert payload["privacy"]["exact_timestamps_shared"] is False
    assert payload["boundary"]["medical_diagnosis"] is False
    assert payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert "2026-05-27T" not in serialized
    assert "position_lat" not in serialized
    assert "position_long" not in serialized
    assert "fit_records" not in serialized


def test_summarizes_fit_session_summary_without_track_points(tmp_path):
    fit_path = _write_raw_fit_session_summary(tmp_path / "session-summary.fit")

    result = write_sanitized_import_from_raw_file(
        fit_path,
        source_format="fit",
        output_dir=tmp_path / "sanitized",
        activity_id="raw.fit.session.fixture.001",
    )
    payload = result["sanitized_import"]
    serialized = json.dumps(payload)

    assert result["artifact_kind"] == "scout_wearable_raw_import_summary_result"
    assert result["mutation"]["raw_payload_committed"] is False
    assert payload["source_format"] == "fit_derived_summary"
    assert payload["activity_date"] == "2026-05-27"
    assert payload["duration_s"] == 3600
    assert payload["moving_time_s"] == 3400
    assert payload["distance_m"] == 4200
    assert payload["ascent_m"] == 310
    assert payload["descent_m"] == 305
    assert payload["heart_rate"]["sample_count"] == 1
    assert payload["heart_rate"]["avg_bpm"] == 128
    assert payload["heart_rate"]["samples"] == []
    assert payload["data_quality"]["gps_confidence"] == "low"
    assert payload["privacy"]["raw_track_shared"] is False
    assert payload["privacy"]["exact_timestamps_shared"] is False
    assert payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert "2026-05-27T" not in serialized
    assert "total_elapsed_time" not in serialized
    assert "start_time" not in serialized
    assert "fit_records" not in serialized


def test_summarizes_fit_lap_summary_without_track_points_or_session(tmp_path):
    fit_path = _write_raw_fit_lap_summary(tmp_path / "lap-summary.fit")

    result = write_sanitized_import_from_raw_file(
        fit_path,
        source_format="fit",
        output_dir=tmp_path / "sanitized",
        activity_id="raw.fit.lap.fixture.001",
    )
    payload = result["sanitized_import"]
    serialized = json.dumps(payload)

    assert result["artifact_kind"] == "scout_wearable_raw_import_summary_result"
    assert result["mutation"]["raw_payload_committed"] is False
    assert payload["source_format"] == "fit_derived_summary"
    assert payload["activity_date"] == "2026-05-27"
    assert payload["duration_s"] == 2700
    assert payload["moving_time_s"] == 2550
    assert payload["distance_m"] == 3100
    assert payload["ascent_m"] == 240
    assert payload["descent_m"] == 236
    assert payload["heart_rate"]["sample_count"] == 1
    assert payload["heart_rate"]["avg_bpm"] == 132
    assert payload["heart_rate"]["samples"] == []
    assert payload["data_quality"]["gps_confidence"] == "low"
    assert payload["privacy"]["raw_track_shared"] is False
    assert payload["privacy"]["exact_timestamps_shared"] is False
    assert payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert "2026-05-27T" not in serialized
    assert "total_elapsed_time" not in serialized
    assert "start_time" not in serialized
    assert "lap-summary.fit" not in serialized
    assert "fit_records" not in serialized


def test_provider_archive_import_summarizes_fit_session_summary_member(tmp_path):
    fit_path = _write_raw_fit_session_summary(tmp_path / "session-summary.fit")
    zip_path = tmp_path / "garmin-fit-session-export.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.write(fit_path, "DI-Connect-Fitness/Activities/session-summary.fit")

    manifest = inspect_provider_archive(
        zip_path,
        source_format="garmin_connect_export",
    )
    result = write_sanitized_import_batch_from_provider_archive(
        zip_path,
        source_format="garmin_connect_export",
        output_dir=tmp_path / "sanitized",
        activity_id_prefix="archive.garmin.fit_session",
    )
    serialized = json.dumps(result)

    assert manifest["supported_member_count"] == 1
    assert manifest["supported_members"][0]["source_format"] == "fit"
    assert result["activity_count"] == 1
    assert result["archive_members"][0]["member_path"] == "DI-Connect-Fitness/Activities/session-summary.fit"
    assert result["results"][0]["activity_id"] == "archive.garmin.fit_session.001"
    assert result["results"][0]["sanitized_import"]["distance_m"] == 4200
    assert result["results"][0]["sanitized_import"]["heart_rate"]["avg_bpm"] == 128
    assert result["mutation"]["archive_extracted_to_workspace"] is False
    assert result["mutation"]["raw_payload_committed"] is False
    assert "session-summary.fit" in serialized
    assert "total_elapsed_time" not in serialized
    assert "start_time" not in serialized


def test_provider_archive_import_summarizes_fit_lap_summary_member(tmp_path):
    fit_path = _write_raw_fit_lap_summary(tmp_path / "lap-summary.fit")
    zip_path = tmp_path / "garmin-fit-lap-export.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.write(fit_path, "DI-Connect-Fitness/Activities/lap-summary.fit")

    result = write_sanitized_import_batch_from_provider_archive(
        zip_path,
        source_format="garmin_connect_export",
        output_dir=tmp_path / "sanitized",
        activity_id_prefix="archive.garmin.fit_lap",
    )
    serialized = json.dumps(result)

    assert result["activity_count"] == 1
    assert result["archive_members"][0]["member_path"] == "DI-Connect-Fitness/Activities/lap-summary.fit"
    assert result["results"][0]["activity_id"] == "archive.garmin.fit_lap.001"
    assert result["results"][0]["sanitized_import"]["distance_m"] == 3100
    assert result["results"][0]["sanitized_import"]["heart_rate"]["avg_bpm"] == 132
    assert result["mutation"]["archive_extracted_to_workspace"] is False
    assert result["mutation"]["raw_payload_committed"] is False
    assert "total_elapsed_time" not in serialized
    assert "start_time" not in serialized
    assert "fit_records" not in serialized


def test_provider_api_fixture_import_requires_explicit_consent(tmp_path):
    api_response_path = _write_garmin_connect_batch_export_json(tmp_path / "garmin-api-response.json")

    try:
        write_sanitized_import_batch_from_provider_api_fixture(
            api_response_path,
            provider="garmin_health_api",
            output_dir=tmp_path / "sanitized",
            activity_id_prefix="api.garmin",
            explicit_consent=False,
            auth_token_ref="secret-token-value",
        )
    except ValueError as exc:
        assert "explicit consent" in str(exc)
    else:
        raise AssertionError("provider API fixture import should require explicit consent")

    assert not (tmp_path / "sanitized").exists()


def test_provider_api_fixture_import_redacts_token_and_normalizes_garmin_response(tmp_path):
    api_response_path = _write_garmin_connect_batch_export_json(tmp_path / "garmin-api-response.json")

    result = write_sanitized_import_batch_from_provider_api_fixture(
        api_response_path,
        provider="garmin_health_api",
        output_dir=tmp_path / "sanitized",
        activity_id_prefix="api.garmin",
        explicit_consent=True,
        auth_token_ref="secret-token-value",
        scopes=["activity:read", "heart_rate:read"],
    )
    serialized = json.dumps(result)

    assert result["artifact_kind"] == "scout_wearable_provider_api_fixture_import_result"
    assert result["source_provider"] == "garmin_health_api_fixture"
    assert result["activity_count"] == 2
    assert result["authorization"]["account_authorized"] is True
    assert result["authorization"]["explicit_consent"] is True
    assert result["authorization"]["network_mode"] == "offline_fixture"
    assert result["authorization"]["token_value_exposed"] is False
    assert result["authorization"]["token_ref_sha256"] is not None
    assert result["authorization"]["scopes"] == ["activity:read", "heart_rate:read"]
    assert all(Path(path).exists() for path in result["sanitized_import_paths"])
    assert result["mutation"]["network_request_performed"] is False
    assert result["mutation"]["real_provider_api_called"] is False
    assert result["mutation"]["raw_payload_committed"] is False
    assert result["privacy"]["raw_health_payload_shared"] is False
    assert result["privacy"]["exact_timestamps_shared"] is False
    assert result["boundary"]["medical_diagnosis"] is False
    assert result["boundary"]["phase1_runtime_safety_truth"] is False
    assert "secret-token-value" not in serialized
    assert "geoPolylineDTO" not in serialized
    assert "heartRateSamples" not in serialized
    assert "startTimeGMT" not in serialized
    assert "/safety/" not in serialized


def test_provider_api_fixture_import_normalizes_apple_healthkit_response(tmp_path):
    api_response_path = _write_apple_healthkit_api_fixture_json(tmp_path / "apple-healthkit-response.json")

    result = write_sanitized_import_batch_from_provider_api_fixture(
        api_response_path,
        provider="apple_healthkit_api",
        output_dir=tmp_path / "sanitized",
        activity_id_prefix="api.apple_healthkit",
        explicit_consent=True,
        auth_token_ref="healthkit-grant-ref",
        scopes=["HKWorkoutType", "HKQuantityTypeIdentifierHeartRate"],
    )
    serialized = json.dumps(result)

    assert result["artifact_kind"] == "scout_wearable_provider_api_fixture_import_result"
    assert result["source_provider"] == "apple_healthkit_api_fixture"
    assert result["activity_count"] == 2
    assert result["authorization"]["provider"] == "apple_healthkit_api"
    assert result["authorization"]["token_value_exposed"] is False
    assert result["authorization"]["network_mode"] == "offline_fixture"
    assert result["results"][0]["sanitized_import"]["source_format"] == "apple_healthkit_workout_summary"
    assert result["results"][0]["sanitized_import"]["activity_date"] == "2026-05-26"
    assert result["results"][0]["sanitized_import"]["heart_rate"]["sample_count"] == 2
    assert result["results"][1]["sanitized_import"]["distance_m"] == 4200
    assert all(Path(path).exists() for path in result["sanitized_import_paths"])
    assert result["mutation"]["real_provider_api_called"] is False
    assert result["mutation"]["raw_payload_committed"] is False
    assert result["privacy"]["raw_health_payload_shared"] is False
    assert result["boundary"]["phase1_runtime_safety_truth"] is False
    assert "healthkit-grant-ref" not in serialized
    assert "HKQuantityTypeIdentifierHeartRate" not in serialized
    assert "heart_rate_samples" not in serialized
    assert "2026-05-26T" not in serialized
    assert "/safety/" not in serialized


def test_raw_importer_cli_summarizes_provider_api_fixture_without_live_api(tmp_path):
    api_response_path = _write_garmin_connect_batch_export_json(tmp_path / "garmin-api-response.json")
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "summarize-provider-api-fixture",
            "--input",
            str(api_response_path),
            "--provider",
            "garmin_health_api",
            "--output-dir",
            str(tmp_path / "sanitized"),
            "--activity-id-prefix",
            "api.garmin.cli",
            "--scope",
            "activity:read",
            "--auth-token-ref",
            "secret-token-value",
            "--explicit-consent",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(completed.stdout)
    serialized = json.dumps(payload)

    assert payload["artifact_kind"] == "scout_wearable_provider_api_fixture_import_result"
    assert payload["activity_count"] == 2
    assert payload["authorization"]["network_mode"] == "offline_fixture"
    assert payload["authorization"]["real_provider_api_called"] is False
    assert payload["mutation"]["network_request_performed"] is False
    assert payload["mutation"]["real_provider_api_called"] is False
    assert payload["boundary"]["safety_api_calls_allowed"] is False
    assert "secret-token-value" not in serialized
    assert "heartRateSamples" not in serialized
    assert "startTimeGMT" not in serialized


def test_raw_importer_cli_summarizes_apple_provider_api_fixture(tmp_path):
    api_response_path = _write_apple_healthkit_api_fixture_json(tmp_path / "apple-healthkit-response.json")
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "summarize-provider-api-fixture",
            "--input",
            str(api_response_path),
            "--provider",
            "apple_healthkit_api",
            "--output-dir",
            str(tmp_path / "sanitized"),
            "--activity-id-prefix",
            "api.apple.cli",
            "--scope",
            "HKWorkoutType",
            "--auth-token-ref",
            "healthkit-grant-ref",
            "--explicit-consent",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(completed.stdout)
    serialized = json.dumps(payload)

    assert payload["source_provider"] == "apple_healthkit_api_fixture"
    assert payload["activity_count"] == 2
    assert payload["authorization"]["real_provider_api_called"] is False
    assert payload["mutation"]["network_request_performed"] is False
    assert payload["boundary"]["medical_diagnosis"] is False
    assert "healthkit-grant-ref" not in serialized
    assert "heart_rate_samples" not in serialized


def test_raw_importer_cli_summarizes_fit_then_normalizes_and_builds(tmp_path):
    fit_path = _write_raw_fit(tmp_path / "activity.fit")
    sanitized_dir = tmp_path / "sanitized"
    raw_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "summarize-raw",
            "--input",
            str(fit_path),
            "--source-format",
            "fit",
            "--output-dir",
            str(sanitized_dir),
            "--activity-id",
            "raw.fit.fixture.cli.001",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    raw_payload = json.loads(raw_completed.stdout)
    normalized_dir = tmp_path / "normalized"
    normalize_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "normalize",
            "--input",
            raw_payload["sanitized_import_path"],
            "--output-dir",
            str(normalized_dir),
            "--root",
            str(tmp_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    normalized_payload = json.loads(normalize_completed.stdout)
    normalized_path = Path(normalized_payload["normalized_paths"][0])
    report = validate_wearable_activity_summary_contract(normalized_path, root=tmp_path)
    build_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "build",
            "--activity",
            str(normalized_path),
            "--output-dir",
            str(tmp_path / "energy"),
            "--reference-date",
            "2026-05-27",
            "--root",
            str(tmp_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    build_payload = json.loads(build_completed.stdout)

    assert raw_payload["sanitized_import"]["source_format"] == "fit_derived_summary"
    assert raw_payload["mutation"]["raw_track_shared"] is False
    assert normalized_payload["artifact_kind"] == "scout_wearable_adapter_normalization_batch"
    assert report.valid is True
    assert build_payload["baseline"]["activity_count"] == 1
    assert build_payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert "/safety/" not in json.dumps(raw_payload)
    assert "position_lat" not in json.dumps(raw_payload)


def test_raw_importer_cli_summarizes_apple_health_then_normalizes_and_builds(tmp_path):
    xml_path = _write_apple_health_export_xml(tmp_path / "apple_health_export.xml")
    sanitized_dir = tmp_path / "sanitized"
    raw_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "summarize-raw",
            "--input",
            str(xml_path),
            "--source-format",
            "apple_health_export",
            "--output-dir",
            str(sanitized_dir),
            "--activity-id",
            "raw.apple_health.fixture.cli.001",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    raw_payload = json.loads(raw_completed.stdout)
    normalized_dir = tmp_path / "normalized"
    normalize_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "normalize",
            "--input",
            raw_payload["sanitized_import_path"],
            "--output-dir",
            str(normalized_dir),
            "--root",
            str(tmp_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    normalized_payload = json.loads(normalize_completed.stdout)
    normalized_path = Path(normalized_payload["normalized_paths"][0])
    report = validate_wearable_activity_summary_contract(normalized_path, root=tmp_path)
    build_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "build",
            "--activity",
            str(normalized_path),
            "--output-dir",
            str(tmp_path / "energy"),
            "--reference-date",
            "2026-05-27",
            "--root",
            str(tmp_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    build_payload = json.loads(build_completed.stdout)

    assert raw_payload["sanitized_import"]["source_format"] == "apple_health_export_summary"
    assert raw_payload["mutation"]["raw_health_payload_shared"] is False
    assert normalized_payload["results"][0]["source_provider"] == "apple_health_export"
    assert report.valid is True
    assert build_payload["baseline"]["activity_count"] == 1
    assert build_payload["boundary"]["medical_diagnosis"] is False
    assert "HKQuantityTypeIdentifierHeartRate" not in json.dumps(raw_payload)
    assert "startDate" not in json.dumps(raw_payload)


def test_raw_importer_cli_summarizes_garmin_then_normalizes_and_builds(tmp_path):
    json_path = _write_garmin_connect_export_json(tmp_path / "garmin_activity.json")
    sanitized_dir = tmp_path / "sanitized"
    raw_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "summarize-raw",
            "--input",
            str(json_path),
            "--source-format",
            "garmin_connect_export",
            "--output-dir",
            str(sanitized_dir),
            "--activity-id",
            "raw.garmin.fixture.cli.001",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    raw_payload = json.loads(raw_completed.stdout)
    normalized_dir = tmp_path / "normalized"
    normalize_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "normalize",
            "--input",
            raw_payload["sanitized_import_path"],
            "--output-dir",
            str(normalized_dir),
            "--root",
            str(tmp_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    normalized_payload = json.loads(normalize_completed.stdout)
    normalized_path = Path(normalized_payload["normalized_paths"][0])
    normalized_activity = json.loads(normalized_path.read_text(encoding="utf-8"))
    report = validate_wearable_activity_summary_contract(normalized_path, root=tmp_path)
    build_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "build",
            "--activity",
            str(normalized_path),
            "--output-dir",
            str(tmp_path / "energy"),
            "--reference-date",
            "2026-05-27",
            "--root",
            str(tmp_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    build_payload = json.loads(build_completed.stdout)

    assert raw_payload["sanitized_import"]["source_format"] == "garmin_connect_activity_summary"
    assert raw_payload["mutation"]["raw_track_shared"] is False
    assert normalized_payload["results"][0]["source_provider"] == "garmin_connect_export"
    assert normalized_activity["body_energy_provider_values"]["garmin_body_battery_end"] == 38
    assert normalized_activity["body_energy_provider_values"]["scout_truth"] is False
    assert report.valid is True
    assert build_payload["baseline"]["activity_count"] == 1
    assert build_payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert "geoPolylineDTO" not in json.dumps(raw_payload)
    assert "startTimeGMT" not in json.dumps(raw_payload)


def test_raw_importer_cli_batch_summarizes_garmin_then_normalizes_and_builds(tmp_path):
    json_path = _write_garmin_connect_batch_export_json(tmp_path / "garmin_activities.json")
    sanitized_dir = tmp_path / "sanitized"
    raw_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "summarize-raw-batch",
            "--input",
            str(json_path),
            "--source-format",
            "garmin_connect_export",
            "--output-dir",
            str(sanitized_dir),
            "--activity-id-prefix",
            "raw.garmin.batch",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    raw_payload = json.loads(raw_completed.stdout)
    normalized_dir = tmp_path / "normalized"
    normalize_command = [
        sys.executable,
        "-m",
        "scout_energy_reserve",
        "normalize",
        "--output-dir",
        str(normalized_dir),
        "--root",
        str(tmp_path),
    ]
    for path in raw_payload["sanitized_import_paths"]:
        normalize_command.extend(["--input", path])
    normalize_completed = subprocess.run(
        normalize_command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    normalized_payload = json.loads(normalize_completed.stdout)
    normalized_paths = [Path(path) for path in normalized_payload["normalized_paths"]]
    build_command = [
        sys.executable,
        "-m",
        "scout_energy_reserve",
        "build",
        "--output-dir",
        str(tmp_path / "energy"),
        "--reference-date",
        "2026-05-27",
        "--root",
        str(tmp_path),
    ]
    for path in normalized_paths:
        build_command.extend(["--activity", str(path)])
    build_completed = subprocess.run(
        build_command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    build_payload = json.loads(build_completed.stdout)

    assert raw_payload["activity_count"] == 2
    assert raw_payload["source_provider"] == "garmin_connect_activity_summary"
    assert raw_payload["mutation"]["raw_track_shared"] is False
    assert normalized_payload["activity_count"] == 2
    assert normalized_payload["source_provider"] == "garmin_connect_export"
    assert build_payload["baseline"]["activity_count"] == 2
    assert build_payload["boundary"]["medical_diagnosis"] is False
    assert "geoPolylineDTO" not in json.dumps(raw_payload)
    assert "startTimeGMT" not in json.dumps(raw_payload)


def test_raw_importer_cli_discovers_garmin_zip_archive_then_normalizes_and_builds(tmp_path):
    json_path = _write_garmin_connect_batch_export_json(tmp_path / "activities.json")
    zip_path = tmp_path / "garmin-export.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.write(json_path, "DI-Connect-Fitness/Activities/activities.json")
    sanitized_dir = tmp_path / "sanitized"
    raw_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "summarize-provider-archive",
            "--input",
            str(zip_path),
            "--source-format",
            "garmin_connect_export",
            "--output-dir",
            str(sanitized_dir),
            "--activity-id-prefix",
            "archive.garmin",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    raw_payload = json.loads(raw_completed.stdout)
    normalized_dir = tmp_path / "normalized"
    normalize_command = [
        sys.executable,
        "-m",
        "scout_energy_reserve",
        "normalize",
        "--output-dir",
        str(normalized_dir),
        "--root",
        str(tmp_path),
    ]
    for path in raw_payload["sanitized_import_paths"]:
        normalize_command.extend(["--input", path])
    normalize_completed = subprocess.run(
        normalize_command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    normalized_payload = json.loads(normalize_completed.stdout)
    build_command = [
        sys.executable,
        "-m",
        "scout_energy_reserve",
        "build",
        "--output-dir",
        str(tmp_path / "energy"),
        "--reference-date",
        "2026-05-27",
        "--root",
        str(tmp_path),
    ]
    for path in normalized_payload["normalized_paths"]:
        build_command.extend(["--activity", path])
    build_completed = subprocess.run(
        build_command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    build_payload = json.loads(build_completed.stdout)

    assert raw_payload["artifact_kind"] == "scout_wearable_provider_archive_import_result"
    assert raw_payload["archive_kind"] == "zip"
    assert raw_payload["archive_member_path"] == "DI-Connect-Fitness/Activities/activities.json"
    assert len(raw_payload["archive_member_sha256"]) == 64
    assert len(raw_payload["sha256"]) == 64
    assert raw_payload["activity_count"] == 2
    assert raw_payload["mutation"]["archive_extracted_to_workspace"] is False
    assert raw_payload["mutation"]["raw_track_shared"] is False
    assert normalized_payload["activity_count"] == 2
    assert build_payload["baseline"]["activity_count"] == 2
    assert build_payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert "geoPolylineDTO" not in json.dumps(raw_payload)
    assert "startTimeGMT" not in json.dumps(raw_payload)


def test_wearable_fixtures_do_not_commit_raw_track_files():
    fixture_root = ROOT / "tests" / "fixtures" / "wearables"
    raw_fixture_paths = sorted(
        path
        for suffix in ("*.gpx", "*.tcx", "*.fit", "*.xml", "*.zip")
        for path in fixture_root.rglob(suffix)
    )

    assert raw_fixture_paths == []


def _write_raw_gpx(path: Path) -> Path:
    path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="Scout test" xmlns="http://www.topografix.com/GPX/1/1"
     xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1">
  <trk><name>fixture</name><trkseg>
    <trkpt lat="24.0000" lon="121.0000"><ele>100</ele><time>2026-05-27T00:00:00Z</time><extensions><gpxtpx:TrackPointExtension><gpxtpx:hr>110</gpxtpx:hr></gpxtpx:TrackPointExtension></extensions></trkpt>
    <trkpt lat="24.0005" lon="121.0005"><ele>115</ele><time>2026-05-27T00:05:00Z</time><extensions><gpxtpx:TrackPointExtension><gpxtpx:hr>132</gpxtpx:hr></gpxtpx:TrackPointExtension></extensions></trkpt>
    <trkpt lat="24.0010" lon="121.0010"><ele>120</ele><time>2026-05-27T00:10:00Z</time><extensions><gpxtpx:TrackPointExtension><gpxtpx:hr>145</gpxtpx:hr></gpxtpx:TrackPointExtension></extensions></trkpt>
  </trkseg></trk>
</gpx>
""",
        encoding="utf-8",
    )
    return path


def _write_raw_tcx(path: Path) -> Path:
    path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
  <Activities><Activity Sport="Other"><Lap StartTime="2026-05-27T00:00:00Z"><Track>
    <Trackpoint><Time>2026-05-27T00:00:00Z</Time><Position><LatitudeDegrees>24.0000</LatitudeDegrees><LongitudeDegrees>121.0000</LongitudeDegrees></Position><AltitudeMeters>100</AltitudeMeters><HeartRateBpm><Value>108</Value></HeartRateBpm></Trackpoint>
    <Trackpoint><Time>2026-05-27T00:05:00Z</Time><Position><LatitudeDegrees>24.0004</LatitudeDegrees><LongitudeDegrees>121.0006</LongitudeDegrees></Position><AltitudeMeters>118</AltitudeMeters><HeartRateBpm><Value>130</Value></HeartRateBpm></Trackpoint>
    <Trackpoint><Time>2026-05-27T00:10:00Z</Time><Position><LatitudeDegrees>24.0008</LatitudeDegrees><LongitudeDegrees>121.0012</LongitudeDegrees></Position><AltitudeMeters>125</AltitudeMeters><HeartRateBpm><Value>142</Value></HeartRateBpm></Trackpoint>
  </Track></Lap></Activity></Activities>
</TrainingCenterDatabase>
""",
        encoding="utf-8",
    )
    return path


def _write_apple_health_export_xml(path: Path) -> Path:
    path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<HealthData locale="en_US">
  <Workout workoutActivityType="HKWorkoutActivityTypeHiking"
           duration="60" durationUnit="min"
           totalDistance="4.2" totalDistanceUnit="km"
           startDate="2026-05-27 07:00:00 +0800"
           endDate="2026-05-27 08:00:00 +0800">
    <WorkoutStatistics type="HKQuantityTypeIdentifierHeartRate"
                       average="132" minimum="108" maximum="149"
                       unit="count/min"/>
  </Workout>
  <Record type="HKQuantityTypeIdentifierHeartRate"
          sourceName="Apple Watch"
          unit="count/min"
          creationDate="2026-05-27 07:00:05 +0800"
          startDate="2026-05-27 07:00:00 +0800"
          endDate="2026-05-27 07:00:00 +0800"
          value="110"/>
  <Record type="HKQuantityTypeIdentifierHeartRate"
          sourceName="Apple Watch"
          unit="count/min"
          creationDate="2026-05-27 07:30:05 +0800"
          startDate="2026-05-27 07:30:00 +0800"
          endDate="2026-05-27 07:30:00 +0800"
          value="136"/>
  <Record type="HKQuantityTypeIdentifierHeartRate"
          sourceName="Apple Watch"
          unit="count/min"
          creationDate="2026-05-27 08:00:05 +0800"
          startDate="2026-05-27 08:00:00 +0800"
          endDate="2026-05-27 08:00:00 +0800"
          value="150"/>
</HealthData>
""",
        encoding="utf-8",
    )
    return path


def _write_apple_health_batch_export_xml(path: Path) -> Path:
    path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<HealthData locale="en_US">
  <Workout workoutActivityType="HKWorkoutActivityTypeHiking"
           duration="45" durationUnit="min"
           totalDistance="3.1" totalDistanceUnit="km"
           startDate="2026-05-26 07:00:00 +0800"
           endDate="2026-05-26 07:45:00 +0800"/>
  <Workout workoutActivityType="HKWorkoutActivityTypeHiking"
           duration="60" durationUnit="min"
           totalDistance="4.2" totalDistanceUnit="km"
           startDate="2026-05-27 07:00:00 +0800"
           endDate="2026-05-27 08:00:00 +0800"/>
  <Record type="HKQuantityTypeIdentifierHeartRate"
          sourceName="Apple Watch"
          unit="count/min"
          startDate="2026-05-26 07:10:00 +0800"
          endDate="2026-05-26 07:10:00 +0800"
          value="118"/>
  <Record type="HKQuantityTypeIdentifierHeartRate"
          sourceName="Apple Watch"
          unit="count/min"
          startDate="2026-05-26 07:40:00 +0800"
          endDate="2026-05-26 07:40:00 +0800"
          value="132"/>
  <Record type="HKQuantityTypeIdentifierHeartRate"
          sourceName="Apple Watch"
          unit="count/min"
          startDate="2026-05-27 07:05:00 +0800"
          endDate="2026-05-27 07:05:00 +0800"
          value="110"/>
  <Record type="HKQuantityTypeIdentifierHeartRate"
          sourceName="Apple Watch"
          unit="count/min"
          startDate="2026-05-27 07:35:00 +0800"
          endDate="2026-05-27 07:35:00 +0800"
          value="136"/>
</HealthData>
""",
        encoding="utf-8",
    )
    return path


def _write_garmin_connect_export_json(path: Path) -> Path:
    payload = {
        "activity": {
            "activityId": 987654321,
            "activityName": "Private local hike",
            "activityType": {"typeKey": "hiking"},
            "startTimeGMT": "2026-05-27T00:00:00Z",
            "startTimeLocal": "2026-05-27 08:00:00",
            "duration": 5400,
            "movingDuration": 5000,
            "distance": 5600,
            "elevationGain": 320,
            "elevationLoss": 315,
            "heartRateSamples": [
                {"timeOffsetSeconds": 0, "heartRate": 98},
                {"timeOffsetSeconds": 1400, "heartRate": 126},
                {"timeOffsetSeconds": 3200, "heartRate": 142},
                {"timeOffsetSeconds": 5000, "heartRate": 119},
            ],
            "bodyBattery": {"start": 68, "end": 38},
            "stress": {"avg": 59},
            "geoPolylineDTO": {"polyline": "_p~iF~ps|U_ulLnnqC_mqNvxq`@"},
        }
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_garmin_connect_batch_export_json(path: Path) -> Path:
    payload = {
        "activities": [
            {
                "activityId": 987654321,
                "startTimeGMT": "2026-05-26T00:00:00Z",
                "duration": 3600,
                "movingDuration": 3400,
                "distance": 4100,
                "elevationGain": 180,
                "elevationLoss": 175,
                "heartRateSamples": [
                    {"timeOffsetSeconds": 0, "heartRate": 105},
                    {"timeOffsetSeconds": 1800, "heartRate": 128},
                    {"timeOffsetSeconds": 3400, "heartRate": 119},
                ],
                "bodyBattery": {"start": 72, "end": 51},
                "stress": {"avg": 42},
                "geoPolylineDTO": {"polyline": "private-route-one"},
            },
            {
                "activityId": 987654322,
                "startTimeGMT": "2026-05-27T00:00:00Z",
                "duration": 5400,
                "movingDuration": 5000,
                "distance": 5600,
                "elevationGain": 320,
                "elevationLoss": 315,
                "heartRateSamples": [
                    {"timeOffsetSeconds": 0, "heartRate": 98},
                    {"timeOffsetSeconds": 1400, "heartRate": 126},
                    {"timeOffsetSeconds": 3200, "heartRate": 142},
                    {"timeOffsetSeconds": 5000, "heartRate": 119},
                ],
                "bodyBattery": {"start": 68, "end": 38},
                "stress": {"avg": 59},
                "geoPolylineDTO": {"polyline": "private-route-two"},
            },
        ]
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_apple_healthkit_api_fixture_json(path: Path) -> Path:
    payload = {
        "workouts": [
            {
                "uuid": "apple-workout-001",
                "workoutActivityType": "HKWorkoutActivityTypeHiking",
                "startDate": "2026-05-26T07:00:00+08:00",
                "endDate": "2026-05-26T07:45:00+08:00",
                "duration_s": 2700,
                "distance_m": 3100,
                "heart_rate_samples": [
                    {"startDate": "2026-05-26T07:10:00+08:00", "bpm": 118},
                    {"startDate": "2026-05-26T07:40:00+08:00", "bpm": 132},
                ],
            },
            {
                "uuid": "apple-workout-002",
                "workoutActivityType": "HKWorkoutActivityTypeHiking",
                "startDate": "2026-05-27T07:00:00+08:00",
                "endDate": "2026-05-27T08:00:00+08:00",
                "duration_s": 3600,
                "distance_m": 4200,
                "heart_rate_samples": [
                    {"startDate": "2026-05-27T07:05:00+08:00", "bpm": 110},
                    {"startDate": "2026-05-27T07:35:00+08:00", "bpm": 136},
                ],
                "quantity_type": "HKQuantityTypeIdentifierHeartRate",
            },
        ]
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_raw_fit(path: Path) -> Path:
    data_section = _fit_definition_message() + b"".join(
        _fit_data_message(offset_s, lat, lon, altitude_m, heart_rate)
        for offset_s, lat, lon, altitude_m, heart_rate in [
            (0, 24.0000, 121.0000, 100, 110),
            (300, 24.0005, 121.0005, 115, 132),
            (600, 24.0010, 121.0010, 120, 145),
        ]
    )
    header = struct.pack("<BBHI4sH", 14, 16, 2110, len(data_section), b".FIT", 0)
    path.write_bytes(header + data_section + struct.pack("<H", 0))
    return path


def _write_raw_fit_session_summary(path: Path) -> Path:
    data_section = _fit_session_definition_message() + _fit_session_data_message()
    header = struct.pack("<BBHI4sH", 14, 16, 2110, len(data_section), b".FIT", 0)
    path.write_bytes(header + data_section + struct.pack("<H", 0))
    return path


def _write_raw_fit_lap_summary(path: Path) -> Path:
    data_section = _fit_lap_definition_message() + _fit_lap_data_message()
    header = struct.pack("<BBHI4sH", 14, 16, 2110, len(data_section), b".FIT", 0)
    path.write_bytes(header + data_section + struct.pack("<H", 0))
    return path


def _fit_definition_message() -> bytes:
    field_definitions = [
        (253, 4, 0x86),
        (0, 4, 0x85),
        (1, 4, 0x85),
        (2, 2, 0x84),
        (3, 1, 0x02),
    ]
    definition = bytearray([0x40, 0, 0])
    definition.extend(struct.pack("<H", 20))
    definition.append(len(field_definitions))
    for field_number, size, base_type in field_definitions:
        definition.extend([field_number, size, base_type])
    return bytes(definition)


def _fit_lap_definition_message() -> bytes:
    field_definitions = [
        (253, 4, 0x86),
        (2, 4, 0x86),
        (7, 4, 0x86),
        (8, 4, 0x86),
        (9, 4, 0x86),
        (21, 2, 0x84),
        (22, 2, 0x84),
        (15, 1, 0x02),
    ]
    definition = bytearray([0x42, 0, 0])
    definition.extend(struct.pack("<H", 19))
    definition.append(len(field_definitions))
    for field_number, size, base_type in field_definitions:
        definition.extend([field_number, size, base_type])
    return bytes(definition)


def _fit_session_definition_message() -> bytes:
    field_definitions = [
        (253, 4, 0x86),
        (2, 4, 0x86),
        (7, 4, 0x86),
        (8, 4, 0x86),
        (9, 4, 0x86),
        (22, 2, 0x84),
        (23, 2, 0x84),
        (16, 1, 0x02),
    ]
    definition = bytearray([0x41, 0, 0])
    definition.extend(struct.pack("<H", 18))
    definition.append(len(field_definitions))
    for field_number, size, base_type in field_definitions:
        definition.extend([field_number, size, base_type])
    return bytes(definition)


def _fit_session_data_message() -> bytes:
    start = datetime(2026, 5, 27, tzinfo=timezone.utc)
    fit_epoch = datetime(1989, 12, 31, tzinfo=timezone.utc)
    start_timestamp = int((start - fit_epoch).total_seconds())
    end_timestamp = start_timestamp + 3600
    return bytes([0x01]) + struct.pack(
        "<IIIIIHHB",
        end_timestamp,
        start_timestamp,
        3_600_000,
        3_400_000,
        420_000,
        310,
        305,
        128,
    )


def _fit_lap_data_message() -> bytes:
    start = datetime(2026, 5, 27, tzinfo=timezone.utc)
    fit_epoch = datetime(1989, 12, 31, tzinfo=timezone.utc)
    start_timestamp = int((start - fit_epoch).total_seconds())
    end_timestamp = start_timestamp + 2700
    return bytes([0x02]) + struct.pack(
        "<IIIIIHHB",
        end_timestamp,
        start_timestamp,
        2_700_000,
        2_550_000,
        310_000,
        240,
        236,
        132,
    )


def _fit_data_message(
    offset_s: int,
    lat: float,
    lon: float,
    altitude_m: int,
    heart_rate: int,
) -> bytes:
    start = datetime(2026, 5, 27, tzinfo=timezone.utc)
    fit_epoch = datetime(1989, 12, 31, tzinfo=timezone.utc)
    timestamp = int((start - fit_epoch).total_seconds()) + offset_s
    return bytes([0x00]) + struct.pack(
        "<IiiHB",
        timestamp,
        _fit_semicircles(lat),
        _fit_semicircles(lon),
        int((altitude_m + 500) * 5),
        heart_rate,
    )


def _fit_semicircles(degrees: float) -> int:
    return round(degrees * (2**31) / 180.0)
