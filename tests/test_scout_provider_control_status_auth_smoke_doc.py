from __future__ import annotations

from pathlib import Path


REPORT_PATH = Path("docs/admin/scout-provider-control-status-auth-smoke.md")


def read_report() -> str:
    return REPORT_PATH.read_text(encoding="utf-8")


def test_provider_control_status_auth_smoke_records_deployment_and_result() -> None:
    source = read_report()

    for token in (
        "`/data/scout/deployments/live-provider-control-auth-20260521T003333Z`",
        "`/data/scout/deployments/provider-control-status-auth-smoke-20260521T003406Z`",
        "`artifact_kind=scout_provider_control_status_auth_smoke`",
        "`status=passed`",
        "`repo_commit=7c95fd6f`",
        "`health_status=ok`",
        "`runtime_profile=pi-field-live`",
        "`runtime_stream_transport_enabled=true`",
        "`remote_provider_live_send_enabled=true`",
        "`hardware_provider_control_enabled=true`",
        "`unauthorized_status_code=401`",
        "`unauthorized_reason=hardware_control_auth_required`",
        "`authorized_status_code=200`",
        "`provider_control_status=enabled`",
        "`provider_control_allowed_actions=[read_provider_status]`",
        "`operator_authorization_required=true`",
        "`token_value_exposed=false`",
        "`stream_control_status=observing`",
    ):
        assert token in source


def test_provider_control_status_auth_smoke_keeps_boundaries_explicit() -> None:
    source = read_report()

    for token in (
        "`secret_values_embedded=false`",
        "`new_observations_sent=false`",
        "`stream_control_mutation_performed=false`",
        "`remote_provider_send_performed=false`",
        "`hardware_control_performed=false`",
        "`phase2_writeback_performed=false`",
        "no provider control action",
        "no hardware driver invocation",
        "no Telegram send",
        "no SOS send",
        "no SMS send",
        "no satellite send",
        "no Phase 2 Brain writeback",
        "no ObservedFact write",
        "no HumanReview or review decision mutation",
        "no raw secret value written to committed docs",
    ):
        assert token in source
