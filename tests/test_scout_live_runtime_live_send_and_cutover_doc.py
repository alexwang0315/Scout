from __future__ import annotations

from pathlib import Path


REPORT_PATH = Path("docs/admin/scout-live-runtime-live-send-and-cutover.md")


def read_report() -> str:
    return REPORT_PATH.read_text(encoding="utf-8")


def test_live_send_report_records_sanitized_telegram_send_result() -> None:
    source = read_report()

    for token in (
        "`/data/scout/deployments/telegram-live-send-20260520T100157Z`",
        "`artifact_kind=telegram_provider_live_send_result`",
        "`status=sent`",
        "`http_status_code=200`",
        "`blocker_count=0`",
        "`blocker_reasons=[]`",
        "`live_network_send_attempted=true`",
        "`send_performed=true`",
        "`remote_notification_send_count=1`",
        "`message_class=remote_status`",
        "`raw_secret_values_embedded=false`",
        "`token_value_embedded=false`",
        "`chat_id_embedded=false`",
        "`endpoint_url_embedded=false`",
    ):
        assert token in source


def test_live_send_report_records_cutover_to_9099_with_rollback_tag() -> None:
    source = read_report()

    for token in (
        "`/data/scout/deployments/live-cutover-20260520T100435Z`",
        "`scout-fusion/pi-runtime:rollback-before-live-20260520T100435Z`",
        "`scout-pi-runtime-live`: `scout-fusion/pi-runtime:live`, `9099 -> 9099`",
        "`9120` no longer accepts connections",
        "`status=cutover_ready`",
        "`runtime_profile=pi-field-live`",
        "`live_runtime_enabled=true`",
        "`runtime_stream_transport_enabled=true`",
        "`remote_provider_live_send_enabled=true`",
        "`hardware_provider_control_enabled=true`",
    ):
        assert token in source


def test_live_send_report_records_assistant_and_stream_boundaries() -> None:
    source = read_report()

    for token in (
        "`read_only=true`",
        "`model_interpretation=true`",
        "`provider=pydantic_ai`",
        "`startup_connection_status=connected:cloud`",
        "`token_values_exposed=false`",
        "`stream_transport_routes_mounted=true`",
        "`stream_safety_mutation_allowed=false`",
        "`stream_phase2_writeback_allowed=false`",
        "`safety_mutation_allowed=false`",
        "`incident_bridge_enable_allowed=false`",
        "`phase2_writeback_allowed=false`",
        "`raw_payloads_embedded=false`",
    ):
        assert token in source


def test_live_send_report_keeps_phase_boundaries_explicit() -> None:
    source = read_report()

    for token in (
        "no SOS send",
        "no real SMS send",
        "no real satellite send",
        "no automatic incident escalation",
        "no `/safety/*` mutation from assistant",
        "no Phase 1 safety decision change",
        "no IncidentStore mutation from assistant or provider smoke",
        "no Phase 2 Brain writeback",
        "no ObservedFact write",
        "no HumanReview or review decision mutation",
        "no hardware provider action beyond read-only status",
    ):
        assert token in source
