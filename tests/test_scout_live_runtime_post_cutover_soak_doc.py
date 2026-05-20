from __future__ import annotations

from pathlib import Path


REPORT_PATH = Path("docs/admin/scout-live-runtime-post-cutover-soak.md")


def read_report() -> str:
    return REPORT_PATH.read_text(encoding="utf-8")


def test_post_cutover_soak_records_sampling_scope() -> None:
    source = read_report()

    for token in (
        "`/data/scout/deployments/post-cutover-soak-20260520T102748Z`",
        "`sample_count=3`",
        "`interval_seconds=5`",
        "`samples_all_ok=true`",
        "`status=passed`",
        "`GET /health`",
        "`GET /assistant/status`",
        "`GET /runtime/streams/status-read-only`",
        "`GET /runtime/streams/control/status`",
        "`GET /providers/control/status`",
    ):
        assert token in source


def test_post_cutover_soak_records_final_status_summary() -> None:
    source = read_report()

    for token in (
        "`runtime_profile=pi-field-live`",
        "`assistant_provider=pydantic_ai`",
        "`assistant_startup_connection_status=connected:cloud`",
        "`assistant_token_values_exposed=false`",
        "`stream_control_status=observing`",
        "`stream_control_record_count=3`",
        "`stream_telemetry_totals.accepted_count=4`",
        "`stream_telemetry_totals.rejected_count=4`",
        "`stream_telemetry_totals.queued_count=0`",
        "`stream_telemetry_totals.active_websocket_connections=0`",
        "`provider_control_status=enabled`",
        "`provider_control_allowed_actions=[read_provider_status]`",
        "`provider_control_token_value_exposed=false`",
    ):
        assert token in source


def test_post_cutover_soak_records_read_only_boundaries() -> None:
    source = read_report()

    for token in (
        "`raw_payloads_embedded=false`",
        "`secret_values_embedded=false`",
        "`pre_incident_file_count=1`",
        "`post_incident_file_count=1`",
        "`incident_file_delta=0`",
        "no new observations sent",
        "no stream control mutation performed",
        "no remote provider send",
        "no Telegram send",
        "no SOS send",
        "no hardware control action",
        "no Phase 2 Brain writeback",
        "no ObservedFact write",
        "no HumanReview or review decision mutation",
    ):
        assert token in source
