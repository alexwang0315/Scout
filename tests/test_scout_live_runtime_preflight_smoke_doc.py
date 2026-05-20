from __future__ import annotations

from pathlib import Path


REPORT_PATH = Path("docs/admin/scout-live-runtime-preflight-smoke.md")


def read_report() -> str:
    return REPORT_PATH.read_text(encoding="utf-8")


def test_live_runtime_preflight_smoke_records_ready_and_blocked_gates() -> None:
    source = read_report()

    for token in (
        "`/data/scout/deployments/live-preflight-20260520T090121Z`",
        "`status=live_enablement_blocked`",
        "`ready=false`",
        "`ready_gates=[hardware_provider_control, local_model_ollama_fallback, runtime_stream]`",
        "`blocked_gates=[remote_provider_live_send]`",
        "`blocker_reasons=[missing_remote_provider_secret_refs]`",
        "`secret_values_embedded=false`",
        "`network_send_performed=false`",
        "`hardware_control_performed=false`",
    ):
        assert token in source


def test_live_runtime_preflight_smoke_keeps_step1_runtime_unchanged() -> None:
    source = read_report()

    for token in (
        "`scout-pi-runtime`: `scout-fusion/pi-runtime:local`, healthy",
        "`runtime_profile=pi-field`",
        "`live_hardware_enabled=false`",
        "`ai_inference_enabled=false`",
        "`local_model_enabled=false`",
        "provider `control_allowed=false`",
        "沒有替換現有",
        "沒有佔用 `9099`",
        "沒有啟動 live service",
    ):
        assert token in source


def test_live_runtime_preflight_smoke_lists_missing_remote_provider_refs() -> None:
    source = read_report()

    for token in (
        "`env:SCOUT_REMOTE_WEBHOOK_URL`",
        "`env:SCOUT_REMOTE_WEBHOOK_TOKEN`",
        "`env:SCOUT_REMOTE_WEBHOOK_HMAC_SECRET`",
        "`env:SCOUT_REMOTE_PRIMARY_TARGET_REF`",
        "`env:SCOUT_REMOTE_BACKUP_TARGET_REF`",
        "不能用 Telegram token",
        "Scout-compatible webhook",
    ):
        assert token in source


def test_live_runtime_preflight_smoke_preserves_runtime_boundaries() -> None:
    source = read_report()

    for token in (
        "no `/safety/*` mutation",
        "no assistant query against live profile",
        "no remote provider send",
        "no hardware control POST",
        "no driver invocation",
        "no Phase 2 Brain writeback",
        "no ObservedFact write",
        "no HumanReview or review decision mutation",
    ):
        assert token in source
