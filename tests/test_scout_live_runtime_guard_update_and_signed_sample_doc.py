from __future__ import annotations

from pathlib import Path


REPORT_PATH = Path("docs/admin/scout-live-runtime-guard-update-and-signed-sample.md")


def read_report() -> str:
    return REPORT_PATH.read_text(encoding="utf-8")


def test_guard_update_report_records_failed_build_and_successful_deploy() -> None:
    source = read_report()

    for token in (
        "`003e4bf6 fix: harden phase45 live runtime demo guards`",
        "`5cfead95 fix: include signed sample client in live image context`",
        "`/data/scout/deployments/live-guard-update-20260520T110519Z`",
        "`status=build_failed`",
        "`runtime_stream_signed_sample_client.py`",
        "production `9099` was not replaced by this failed build",
        "`/data/scout/deployments/live-guard-update-20260520T110822Z`",
        "`scout-fusion/pi-runtime:rollback-before-live-guard-update-20260520T110822Z`",
        "`status=deployed`",
        "`runtime_profile=pi-field-live`",
        "`sample_client_packaged=true`",
    ):
        assert token in source


def test_guard_update_report_records_signed_http_push_sample() -> None:
    source = read_report()

    for token in (
        "`/data/scout/deployments/signed-http-push-sample-20260520T111146Z`",
        "`signed-http-push.dry-run.json`",
        "`signed-http-push.sent.json`",
        "`dry_run_status=dry_run_ready`",
        "`send_status=sent`",
        "`http_status_code=200`",
        "`response_status=accepted`",
        "`response_admission_status=admitted_not_forwarded`",
        "`response_transport_surface=http_push`",
        "`observations_accepted=1`",
        "`safety_level=L0_NORMAL`",
    ):
        assert token in source


def test_guard_update_report_records_packaged_client_smoke_after_rebuild() -> None:
    source = read_report()

    for token in (
        "`/data/scout/deployments/packaged-signed-sample-client-20260521T001534Z`",
        "`sample-observation.validated.json`",
        "`packaged-signed-sample-client-summary.json`",
        "`artifact_kind=scout_live_runtime_packaged_signed_sample_client_smoke`",
        "`status=passed`",
        "`client_path=/app/runtime_stream_signed_sample_client.py`",
        "`dry_run_status=dry_run_ready`",
        "`dry_run_network_send_attempted=false`",
        "`send_status=sent`",
        "`http_status_code=200`",
        "`response_status=accepted`",
        "`response_admission_status=admitted_not_forwarded`",
        "`response_transport_surface=http_push`",
        "`observations_accepted=1`",
        "`safety_level=L0_NORMAL`",
        "`network_send_attempted=true`",
        "`send_performed=true`",
        "`health_status=ok`",
        "`runtime_profile=pi-field-live`",
        "`runtime_stream_transport_enabled=true`",
        "`remote_provider_live_send_enabled=true`",
        "`hardware_provider_control_enabled=true`",
        "`telemetry_http_accepted_delta=1`",
        "`telemetry_http_rejected_delta=0`",
        "`incident_file_delta=0`",
        "`incident_bridge_enabled=false`",
        "`phase2_writeback_count=0`",
        "`raw_payloads_embedded=false`",
        "`secret_values_embedded=false`",
        "`endpoint_secret_embedded=false`",
        "`new_observations_sent=true`",
        "`stream_control_mutation_performed=false`",
        "`remote_provider_send_performed=false`",
        "`hardware_control_performed=false`",
        "`phase2_writeback_performed=false`",
        "verified packaged `/app/runtime_stream_signed_sample_client.py`",
    ):
        assert token in source


def test_guard_update_report_records_boundaries() -> None:
    source = read_report()

    for token in (
        "`raw_payloads_embedded=false`",
        "`secret_values_embedded=false`",
        "`incident_file_delta=0`",
        "`incident_bridge_enabled=false`",
        "`phase2_writeback_count=0`",
        "no Telegram send",
        "no SOS send",
        "no SMS send",
        "no satellite send",
        "no automatic incident escalation",
        "no incident bridge opt-in",
        "no hardware provider action",
        "no Phase 2 Brain writeback",
        "no ObservedFact write",
        "no HumanReview or review decision mutation",
        "no raw secret value written to committed docs",
    ):
        assert token in source
