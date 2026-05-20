from __future__ import annotations

from pathlib import Path


REPORT_PATH = Path("docs/admin/scout-live-runtime-long-soak-automation.md")


def read_report() -> str:
    return REPORT_PATH.read_text(encoding="utf-8")


def test_long_soak_doc_records_checker_and_read_only_surfaces() -> None:
    source = read_report()

    for token in (
        "`live_runtime_soak_check.py`",
        "`GET /health`",
        "`GET /assistant/status`",
        "`GET /runtime/streams/status-read-only`",
        "`GET /runtime/streams/control/status`",
        "`GET /providers/control/status`",
        "/data/scout/secrets/hardware-provider-control-token",
        "The token value is used only in the Authorization header",
    ):
        assert token in source


def test_long_soak_doc_records_latest_short_live_smoke() -> None:
    source = read_report()

    for token in (
        "`/data/scout/deployments/live-runtime-soak-check-20260520T110648Z`",
        "`artifact_kind=scout_live_runtime_soak_check`",
        "`status=passed`",
        "`sample_count=3`",
        "`samples_recorded=3`",
        "`samples_all_ok=true`",
        "`runtime_profile=pi-field-live`",
        "`assistant_provider=pydantic_ai`",
        "`assistant_startup_connection_status=connected:cloud`",
        "`assistant_token_values_exposed=false`",
        "`provider_control_checked=true`",
        "`provider_control_status=enabled`",
        "`provider_control_allowed_actions=[read_provider_status]`",
        "`provider_control_token_value_exposed=false`",
        "`stream_control_status=observing`",
        "`raw_payloads_embedded=false`",
        "`secret_values_embedded=false`",
    ):
        assert token in source


def test_long_soak_doc_records_overnight_started_state_without_completion_claim() -> None:
    source = read_report()

    for token in (
        "`/data/scout/deployments/live-runtime-soak-overnight-20260520T110838Z`",
        "`artifact_kind=scout_live_runtime_overnight_soak_start`",
        "`status=started`",
        "`deploy_dir=/data/scout/deployments/live-runtime-soak-overnight-20260520T110838Z`",
        "`host_nohup_pid=45009`",
        "`sample_count=480`",
        "`interval_seconds=60`",
        "`read_only_soak=true`",
        "`new_observations_sent=false`",
        "`stream_control_mutation_performed=false`",
        "`remote_provider_send_performed=false`",
        "`hardware_control_performed=false`",
        "已啟動但尚未完成",
        "`live-runtime-soak-check-summary.json`",
    ):
        assert token in source


def test_long_soak_doc_records_post_guard_bounded_soak() -> None:
    source = read_report()

    for token in (
        "`/data/scout/deployments/live-runtime-soak-post-guard-20260520T153214Z`",
        "`/tmp/live_runtime_soak_check.py`",
        "避免中斷正在跑的 overnight soak",
        "`status=passed`",
        "`sample_count=6`",
        "`interval_seconds=10`",
        "`samples_all_ok=true`",
        "`runtime_profile=pi-field-live`",
        "`health_status=ok`",
        "`assistant_provider=pydantic_ai`",
        "`assistant_startup_connection_status=connected:cloud`",
        "`assistant_token_values_exposed=false`",
        "`stream_control_status=observing`",
        "`stream_telemetry_totals.accepted_count=0`",
        "`stream_telemetry_totals.rejected_count=0`",
        "`stream_telemetry_totals.queued_count=0`",
        "`stream_telemetry_totals.active_websocket_connections=0`",
        "`provider_control_status=enabled`",
        "`provider_control_allowed_actions=[read_provider_status]`",
        "`provider_control_token_value_exposed=false`",
        "`overnight_soak_still_running=true`",
        "`read_only_soak=true`",
        "`phase2_writeback_performed=false`",
    ):
        assert token in source


def test_long_soak_doc_records_packaging_and_longer_run_command() -> None:
    source = read_report()

    for token in (
        "`Dockerfile.pi.live` copies `live_runtime_soak_check.py`",
        "`.dockerignore` explicitly allows `live_runtime_soak_check.py`",
        "python /app/live_runtime_soak_check.py",
        "--sample-count 120",
        "--interval-seconds 60",
        "roughly two hours",
    ):
        assert token in source


def test_long_soak_doc_keeps_boundaries_explicit() -> None:
    source = read_report()

    for token in (
        "no new observations sent",
        "no stream control mutation performed",
        "no remote provider send",
        "no Telegram send",
        "no SOS send",
        "no hardware control action",
        "no rollback",
        "no Phase 2 Brain writeback",
        "no ObservedFact write",
        "no HumanReview or review decision mutation",
    ):
        assert token in source
