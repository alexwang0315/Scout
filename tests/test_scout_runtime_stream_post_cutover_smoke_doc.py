from __future__ import annotations

from pathlib import Path


REPORT_PATH = Path("docs/admin/scout-runtime-stream-post-cutover-smoke.md")


def read_report() -> str:
    return REPORT_PATH.read_text(encoding="utf-8")


def test_post_cutover_smoke_records_signed_http_admission_success() -> None:
    source = read_report()

    for token in (
        "`/data/scout/deployments/runtime-stream-admission-smoke-20260520T101957Z`",
        "`artifact_kind=scout_runtime_stream_post_cutover_smoke`",
        "`status=passed`",
        "`runtime_profile=pi-field-live`",
        "`health_sample_count=3`",
        "`health_samples_all_ok=true`",
        "`http_push_status_code=200`",
        "`http_push_status=accepted`",
        "`http_push_transport_surface=http_push`",
        "`http_push_observations_accepted=1`",
        "`http_push_admission_status=admitted_not_forwarded`",
        "`http_push_signature_verified=true`",
        "`http_push_policy_matched=true`",
        "`http_push_token_scope_allowed=true`",
        "`dedupe_key_recorded=true`",
    ):
        assert token in source


def test_post_cutover_smoke_records_duplicate_rejection_and_telemetry_delta() -> None:
    source = read_report()

    for token in (
        "`duplicate_status_code=409`",
        "`duplicate_admission_status=rejected_duplicate`",
        "`telemetry_last_rejection_reason=dedupe_key_already_seen`",
        "`telemetry_http_accepted_count_before=1`",
        "`telemetry_http_accepted_count_after=2`",
        "`telemetry_http_accepted_delta=1`",
        "`telemetry_http_rejected_count_before=1`",
        "`telemetry_http_rejected_count_after=2`",
        "`telemetry_http_rejected_delta=1`",
        "`telemetry_raw_payload_embedded=false`",
        "`telemetry_incident_bridge_enabled=false`",
        "`telemetry_phase2_writeback_count=0`",
    ):
        assert token in source


def test_post_cutover_smoke_records_incident_and_secret_boundaries() -> None:
    source = read_report()

    for token in (
        "`secret_value_embedded=false`",
        "Secret values were not printed, committed, or copied into the repo.",
        "`raw_payload_embedded=false`",
        "`raw_payload_leak_detected=false`",
        "`pre_incident_file_count=1`",
        "`post_incident_file_count=1`",
        "`incident_file_delta=0`",
        "`incident_ids_returned_count=0`",
        "`stored_incident_paths_count=0`",
    ):
        assert token in source


def test_post_cutover_smoke_keeps_runtime_boundaries_explicit() -> None:
    source = read_report()

    for token in (
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
