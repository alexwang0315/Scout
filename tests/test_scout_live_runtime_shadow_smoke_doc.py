from __future__ import annotations

from pathlib import Path


REPORT_PATH = Path("docs/admin/scout-live-runtime-shadow-smoke.md")


def read_report() -> str:
    return REPORT_PATH.read_text(encoding="utf-8")


def test_live_runtime_shadow_smoke_records_telegram_refs_without_values() -> None:
    source = read_report()

    for token in (
        "`OPENROUTER_API_KEY`",
        "`TELEGRAM_BOT_TOKEN`",
        "`TELEGRAM_HOME_CHANNEL`",
        "`SCOUT_REMOTE_PROVIDER_KIND=telegram_bot`",
        "`SCOUT_TELEGRAM_BOT_TOKEN`",
        "`SCOUT_TELEGRAM_TARGET_CHAT_ID`",
        "They were not printed, committed, or embedded in JSON evidence.",
    ):
        assert token in source


def test_live_runtime_shadow_smoke_records_all_gates_ready() -> None:
    source = read_report()

    for token in (
        "`/data/scout/deployments/live-preflight-telegram-20260520T092040Z`",
        "`status=live_enablement_ready`",
        "`ready=true`",
        "`blocked_gates=[]`",
        "`missing_secret_refs=[]`",
        "`ready_gates=[hardware_provider_control, local_model_ollama_fallback, remote_provider_live_send, runtime_stream]`",
        "`secret_values_embedded=false`",
        "`network_send_performed=false`",
        "`hardware_control_performed=false`",
    ):
        assert token in source


def test_live_runtime_shadow_smoke_records_shadow_runtime_without_cutover() -> None:
    source = read_report()

    for token in (
        "`scout-pi-runtime-live-shadow`",
        "`9120 -> 9099`",
        "`scout-pi-runtime`: `scout-fusion/pi-runtime:local`, `9099 -> 9099`",
        "`status=ok`",
        "`runtime_profile=pi-field-live`",
        "`runtime_stream_transport_enabled=true`",
        "`remote_provider_live_send_enabled=true`",
        "`hardware_provider_control_enabled=true`",
        "no production cutover from `9099`",
    ):
        assert token in source


def test_live_runtime_shadow_smoke_records_local_fallback_and_read_only_assistant() -> None:
    source = read_report()

    for token in (
        "`provider=pydantic_ai`",
        "`startup_connection_status=connected:local`",
        "`local_model=qwen2.5:0.5b`",
        "`local_fallback_enabled=true`",
        "`token_values_exposed=false`",
        "`model_interpretation=true`",
        "`read_only=true`",
        "`boundary.safety_mutation_allowed=false`",
        "`boundary.hardware_control_allowed=false`",
    ):
        assert token in source


def test_live_runtime_shadow_smoke_records_telegram_cli_blocked_by_default() -> None:
    source = read_report()

    for token in (
        "`/data/scout/deployments/telegram-cli-blocked-20260520T093157Z`",
        "`status=telegram_live_send_blocked`",
        "`blocker_reasons=[provider_adapter_not_enabled, live_network_send_not_enabled, manual_send_authorization_missing]`",
        "`live_network_send_attempted=false`",
        "`send_performed=false`",
        "`remote_notification_send_count=0`",
        "`token_value_embedded=false`",
        "`chat_id_embedded=false`",
        "no true Telegram send",
    ):
        assert token in source
