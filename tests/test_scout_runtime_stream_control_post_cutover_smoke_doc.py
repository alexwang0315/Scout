from __future__ import annotations

from pathlib import Path


REPORT_PATH = Path("docs/admin/scout-runtime-stream-control-post-cutover-smoke.md")


def read_report() -> str:
    return REPORT_PATH.read_text(encoding="utf-8")


def test_control_smoke_records_pause_resume_and_drain_sequence() -> None:
    source = read_report()

    for token in (
        "`/data/scout/deployments/runtime-stream-control-smoke-20260520T102538Z`",
        "`artifact_kind=scout_runtime_stream_control_post_cutover_smoke`",
        "`status=passed`",
        "`runtime_profile=pi-field-live`",
        "`pre_control_status=observing`",
        "`pause_status_code=200`",
        "`pause_status_after=paused`",
        "`paused_observation_status_code=409`",
        "`paused_observation_rejection_reason=runtime_stream_paused`",
        "`resume_status_code=200`",
        "`resume_status_after=observing`",
        "`accepted_observation_status_code=200`",
        "`accepted_observation_status=accepted`",
        "`accepted_observation_transport_surface=http_push`",
        "`accepted_observation_admission_status=admitted_not_forwarded`",
        "`drain_status_code=200`",
        "`drain_queue_depth_before=0`",
        "`drain_queue_depth_after=0`",
        "`post_control_status=observing`",
    ):
        assert token in source


def test_control_smoke_records_telemetry_delta_and_control_boundary() -> None:
    source = read_report()

    for token in (
        "`telemetry_http_accepted_count_before=2`",
        "`telemetry_http_accepted_count_after=3`",
        "`telemetry_http_accepted_delta=1`",
        "`telemetry_http_rejected_count_before=2`",
        "`telemetry_http_rejected_count_after=3`",
        "`telemetry_http_rejected_delta=1`",
        "`telemetry_last_rejection_reason=runtime_stream_paused`",
        "`telemetry_raw_payload_embedded=false`",
        "`telemetry_incident_bridge_enabled=false`",
        "`telemetry_phase2_writeback_count=0`",
        "`stream_control_calls_safety_api=false`",
        "`stream_control_controls_device_hardware=false`",
        "`stream_control_remote_notifications_enabled=false`",
        "`stream_control_phase2_writeback_count=0`",
    ):
        assert token in source


def test_control_smoke_records_incident_and_secret_boundaries() -> None:
    source = read_report()

    for token in (
        "`secret_value_embedded=false`",
        "`raw_payload_embedded=false`",
        "`raw_payload_leak_detected=false`",
        "`pre_incident_file_count=1`",
        "`post_incident_file_count=1`",
        "`incident_file_delta=0`",
        "`incident_ids_returned_count=0`",
        "`stored_incident_paths_count=0`",
    ):
        assert token in source


def test_control_smoke_records_operator_auth_hardening() -> None:
    source = read_report()

    for token in (
        "`/data/scout/deployments/live-control-auth-20260521T002419Z`",
        "`/data/scout/deployments/runtime-stream-control-auth-smoke-20260521T002445Z`",
        "`runtime-stream-control-auth-smoke-summary.json`",
        "`artifact_kind=scout_runtime_stream_control_auth_smoke`",
        "`status=passed`",
        "`repo_commit=af02ce4f`",
        "`health_status=ok`",
        "`runtime_profile=pi-field-live`",
        "`runtime_stream_transport_enabled=true`",
        "`remote_provider_live_send_enabled=true`",
        "`hardware_provider_control_enabled=true`",
        "`operator_authorization_required_before=true`",
        "`token_value_exposed_before=false`",
        "`missing_token_status_code=401`",
        "`missing_token_reason=runtime_stream_control_auth_required`",
        "`wrong_token_status_code=401`",
        "`wrong_token_reason=runtime_stream_control_auth_required`",
        "`authorized_pause_status_code=200`",
        "`authorized_pause_status_after=paused`",
        "`authorized_resume_status_code=200`",
        "`authorized_resume_status_after=observing`",
        "`post_control_status=observing`",
        "`post_control_record_count=2`",
        "`status_surface_control_status=observing`",
        "`token_value_exposed_after=false`",
        "`secret_values_embedded=false`",
        "`new_observations_sent=false`",
        "`stream_control_mutation_performed=true`",
        "`stream_control_final_status_restored=true`",
        "`remote_provider_send_performed=false`",
        "`hardware_control_performed=false`",
        "`phase2_writeback_performed=false`",
        "SCOUT_RUNTIME_STREAM_CONTROL_TOKEN(_FILE)",
        "falls back to",
    ):
        assert token in source


def test_control_smoke_keeps_runtime_boundaries_explicit() -> None:
    source = read_report()

    for token in (
        "no `end` control action on production",
        "no assistant query or assistant action",
        "no remote provider send",
        "no Telegram send",
        "no SOS send",
        "no SMS send",
        "no satellite send",
        "no hardware control action",
        "no Phase 2 Brain writeback",
        "no ObservedFact write",
        "no HumanReview or review decision mutation",
    ):
        assert token in source
