from __future__ import annotations

import hashlib
import inspect
import json

from runtime_remote_provider_live_adapter import RuntimeRemoteSecretResolver
from runtime_remote_provider_policy import RuntimeRemoteMessageClass
from runtime_telegram_provider_live_adapter import (
    TelegramProviderLiveSendOptions,
    TelegramProviderSendIntent,
    send_telegram_provider_intent,
)


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


def test_telegram_provider_send_blocks_by_default_without_transport_call() -> None:
    transport_calls = []

    result = send_telegram_provider_intent(
        _intent(),
        resolver=RuntimeRemoteSecretResolver(
            env={
                "SCOUT_TELEGRAM_BOT_TOKEN": "secret-token",
                "SCOUT_TELEGRAM_TARGET_CHAT_ID": "secret-chat-id",
            }
        ),
        transport=lambda request: transport_calls.append(request),
    )

    assert result.status == "telegram_live_send_blocked"
    assert "provider_adapter_not_enabled" in result.blocker_reasons
    assert "live_network_send_not_enabled" in result.blocker_reasons
    assert "manual_send_authorization_missing" in result.blocker_reasons
    assert result.live_network_send_attempted is False
    assert result.send_performed is False
    assert transport_calls == []


def test_telegram_provider_send_uses_telegram_payload_without_serializing_secrets() -> None:
    captured_requests = []

    def transport(request):
        captured_requests.append(request)
        return {
            "status_code": 200,
            "response_body": '{"ok":true}',
            "provider_message_ref": "telegram-message-001",
        }

    result = send_telegram_provider_intent(
        _intent(),
        options=TelegramProviderLiveSendOptions(
            provider_adapter_enabled=True,
            live_network_send_enabled=True,
            manual_send_authorization=True,
        ),
        resolver=RuntimeRemoteSecretResolver(
            env={
                "SCOUT_TELEGRAM_BOT_TOKEN": "secret-token",
                "SCOUT_TELEGRAM_TARGET_CHAT_ID": "secret-chat-id",
            }
        ),
        transport=transport,
    )
    serialized = result.to_json()

    assert result.status == "sent"
    assert result.live_network_send_attempted is True
    assert result.send_performed is True
    assert result.remote_notification_send_count == 1
    assert result.provider_message_ref == "telegram-message-001"
    assert len(captured_requests) == 1
    assert captured_requests[0].endpoint_url == "https://api.telegram.org/botsecret-token/sendMessage"
    assert captured_requests[0].body["chat_id"] == "secret-chat-id"
    assert captured_requests[0].body["text"] == _intent().body_preview
    assert "secret-token" not in serialized
    assert "secret-chat-id" not in serialized
    assert "api.telegram.org" not in serialized


def test_telegram_provider_source_has_no_safety_or_phase2_imports() -> None:
    import runtime_telegram_provider_live_adapter

    source = inspect.getsource(runtime_telegram_provider_live_adapter)

    assert "urllib.request" in source
    assert "requests." not in source
    assert "httpx." not in source
    assert "safety_api" not in source
    assert "IncidentStore" not in source
    assert "ObservedFact" not in source
    assert "Phase2Brain" not in source
