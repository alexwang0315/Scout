from __future__ import annotations

import hashlib
from pathlib import Path

from runtime_remote_provider_policy import RuntimeRemoteMessageClass
from runtime_telegram_provider_live_adapter import TelegramProviderSendIntent
from runtime_telegram_provider_live_send_cli import run_telegram_provider_live_send_cli


def _intent() -> TelegramProviderSendIntent:
    body = "Scout live provider smoke: read-only remote status."
    return TelegramProviderSendIntent(
        status="queued_not_sent",
        send_intent_queued=True,
        intent_id="telegram_provider_send_intent.live_shadow.remote_status.v0",
        message_class=RuntimeRemoteMessageClass.REMOTE_STATUS,
        body_preview=body,
        payload_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        queued_by_operator_id="operator.admin.local",
        queued_at_iso="2026-05-20T17:20:00+08:00",
        correlation_refs=["scout-live-shadow-smoke"],
    )


def test_telegram_provider_live_send_cli_blocks_without_explicit_flags(tmp_path: Path) -> None:
    intent_path = tmp_path / "telegram-intent.json"
    output_path = tmp_path / "telegram-result.json"
    intent_path.write_text(_intent().to_json(), encoding="utf-8")

    exit_code, result = run_telegram_provider_live_send_cli(
        ["--intent", str(intent_path), "--output", str(output_path)],
        transport=lambda request: {"status_code": 200},
    )

    assert exit_code == 2
    assert result.status == "telegram_live_send_blocked"
    assert "provider_adapter_not_enabled" in result.blocker_reasons
    assert output_path.read_text(encoding="utf-8")


def test_telegram_provider_live_send_cli_blocks_missing_intent_artifact(
    tmp_path: Path,
) -> None:
    missing_intent_path = tmp_path / "missing-telegram-intent.json"
    output_path = tmp_path / "telegram-result.json"
    transport_calls = []

    exit_code, result = run_telegram_provider_live_send_cli(
        [
            "--intent",
            str(missing_intent_path),
            "--output",
            str(output_path),
            "--enable-provider-adapter",
            "--enable-live-network-send",
            "--authorize-manual-send",
        ],
        transport=lambda request: transport_calls.append(request),
    )
    serialized = output_path.read_text(encoding="utf-8")

    assert exit_code == 2
    assert result.status == "operator_request_blocked"
    assert result.blocker_reasons == ["missing_send_intent_artifact"]
    assert result.live_network_send_attempted is False
    assert result.send_performed is False
    assert result.remote_notification_send_count == 0
    assert transport_calls == []
    assert "raw_secret_values_embedded" in serialized
    assert "secret-token" not in serialized
    assert "secret-chat-id" not in serialized
