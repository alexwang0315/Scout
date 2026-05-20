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
