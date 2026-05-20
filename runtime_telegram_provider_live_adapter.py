from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from enum import StrEnum
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field

from runtime_remote_provider_live_adapter import RuntimeRemoteSecretResolver
from runtime_remote_provider_policy import RuntimeRemoteMessageClass


class TelegramProviderLiveAdapterModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TelegramProviderLiveSendStatus(StrEnum):
    SENT = "sent"
    BLOCKED = "telegram_live_send_blocked"
    PROVIDER_ERROR = "provider_error"


class TelegramProviderSendIntent(TelegramProviderLiveAdapterModel):
    artifact_kind: Literal["telegram_provider_send_intent"] = "telegram_provider_send_intent"
    status: Literal["queued_not_sent", "send_intent_blocked"]
    send_intent_queued: bool
    intent_id: str = Field(min_length=1)
    message_class: RuntimeRemoteMessageClass
    body_preview: str = Field(min_length=1, max_length=4096)
    payload_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    queued_by_operator_id: str = Field(min_length=1)
    queued_at_iso: str = Field(min_length=1)
    correlation_refs: list[str] = Field(default_factory=list)
    blocker_reasons: list[str] = Field(default_factory=list)
    manual_send_authorization_required: Literal[True] = True
    summary_only: Literal[True] = True
    raw_payloads_embedded: Literal[False] = False
    secret_values_loaded: Literal[False] = False
    token_value_embedded: Literal[False] = False
    chat_id_embedded: Literal[False] = False
    sends_network_request: Literal[False] = False

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n"


class TelegramProviderLiveSendOptions(TelegramProviderLiveAdapterModel):
    provider_adapter_enabled: bool = False
    live_network_send_enabled: bool = False
    manual_send_authorization: bool = False
    timeout_seconds: float = 10.0
    response_preview_max_chars: int = 240


class TelegramHttpRequest(TelegramProviderLiveAdapterModel):
    method: Literal["POST"] = "POST"
    endpoint_url: str
    body: dict[str, Any]
    timeout_seconds: float


class TelegramHttpResponse(TelegramProviderLiveAdapterModel):
    status_code: int
    response_body: str = ""
    provider_message_ref: str | None = None


class TelegramProviderLiveSendResult(TelegramProviderLiveAdapterModel):
    artifact_kind: Literal["telegram_provider_live_send_result"] = (
        "telegram_provider_live_send_result"
    )
    status: TelegramProviderLiveSendStatus
    intent_id: str
    message_class: RuntimeRemoteMessageClass
    payload_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    request_body_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    queued_by_operator_id: str
    live_network_send_attempted: bool
    send_performed: bool
    remote_notification_send_count: int
    http_status_code: int | None = None
    provider_message_ref: str | None = None
    provider_response_preview: str | None = None
    blocker_count: int = 0
    blocker_reasons: list[str] = Field(default_factory=list)
    provider_error: str | None = None
    secret_values_loaded: bool = False
    secret_values_loaded_count: int = 0
    summary_only: Literal[True] = True
    raw_payloads_embedded: Literal[False] = False
    raw_secret_values_embedded: Literal[False] = False
    endpoint_url_embedded: Literal[False] = False
    token_value_embedded: Literal[False] = False
    chat_id_embedded: Literal[False] = False
    incident_bridge_enable_count: Literal[0] = 0
    phase2_writeback_count: Literal[0] = 0

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n"


def send_telegram_provider_intent(
    send_intent: TelegramProviderSendIntent,
    *,
    options: TelegramProviderLiveSendOptions | None = None,
    resolver: RuntimeRemoteSecretResolver | None = None,
    transport: Callable[[TelegramHttpRequest], Any] | None = None,
) -> TelegramProviderLiveSendResult:
    active_options = options or TelegramProviderLiveSendOptions()
    blockers = _send_blockers(send_intent, active_options)
    if blockers:
        return _result(
            send_intent,
            status=TelegramProviderLiveSendStatus.BLOCKED,
            blockers=blockers,
            live_network_send_attempted=False,
            send_performed=False,
            remote_notification_send_count=0,
        )

    active_resolver = resolver or RuntimeRemoteSecretResolver()
    try:
        bot_token = active_resolver.read_env("SCOUT_TELEGRAM_BOT_TOKEN")
        chat_id = active_resolver.read_env("SCOUT_TELEGRAM_TARGET_CHAT_ID")
        if not bot_token:
            raise ValueError("missing env secret ref: env:SCOUT_TELEGRAM_BOT_TOKEN")
        if not chat_id:
            raise ValueError("missing env secret ref: env:SCOUT_TELEGRAM_TARGET_CHAT_ID")
    except Exception as exc:
        return _result(
            send_intent,
            status=TelegramProviderLiveSendStatus.BLOCKED,
            blockers=[f"secret_resolution_failed:{type(exc).__name__}"],
            live_network_send_attempted=False,
            send_performed=False,
            remote_notification_send_count=0,
            provider_error=str(exc),
        )

    body = {
        "chat_id": chat_id,
        "text": send_intent.body_preview,
        "disable_web_page_preview": True,
    }
    body_hash = _canonical_hash(body)
    request = TelegramHttpRequest(
        endpoint_url=f"https://api.telegram.org/bot{bot_token}/sendMessage",
        body=body,
        timeout_seconds=active_options.timeout_seconds,
    )
    try:
        response = _normalize_response((transport or _telegram_transport)(request))
    except Exception as exc:
        return _result(
            send_intent,
            status=TelegramProviderLiveSendStatus.PROVIDER_ERROR,
            blockers=[],
            live_network_send_attempted=True,
            send_performed=False,
            remote_notification_send_count=0,
            request_body_hash=body_hash,
            provider_error=str(exc),
            secret_values_loaded=True,
            secret_values_loaded_count=2,
        )

    sent = 200 <= response.status_code < 300
    return _result(
        send_intent,
        status=TelegramProviderLiveSendStatus.SENT
        if sent
        else TelegramProviderLiveSendStatus.PROVIDER_ERROR,
        blockers=[] if sent else [f"provider_http_status:{response.status_code}"],
        live_network_send_attempted=True,
        send_performed=sent,
        remote_notification_send_count=1 if sent else 0,
        request_body_hash=body_hash,
        http_status_code=response.status_code,
        provider_message_ref=response.provider_message_ref,
        provider_response_preview=response.response_body[
            : active_options.response_preview_max_chars
        ],
        secret_values_loaded=True,
        secret_values_loaded_count=2,
    )


def _send_blockers(
    send_intent: TelegramProviderSendIntent,
    options: TelegramProviderLiveSendOptions,
) -> list[str]:
    blockers: list[str] = []
    if send_intent.status != "queued_not_sent":
        blockers.append("send_intent_not_queued")
    if not send_intent.send_intent_queued:
        blockers.append("send_intent_queued_flag_false")
    blockers.extend(send_intent.blocker_reasons)
    if not options.provider_adapter_enabled:
        blockers.append("provider_adapter_not_enabled")
    if not options.live_network_send_enabled:
        blockers.append("live_network_send_not_enabled")
    if not options.manual_send_authorization:
        blockers.append("manual_send_authorization_missing")
    return list(dict.fromkeys(blockers))


def _telegram_transport(request: TelegramHttpRequest) -> TelegramHttpResponse:
    body = json.dumps(
        request.body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    urllib_request = urllib.request.Request(
        request.endpoint_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method=request.method,
    )
    try:
        with urllib.request.urlopen(urllib_request, timeout=request.timeout_seconds) as response:
            return TelegramHttpResponse(
                status_code=int(response.status),
                response_body=response.read().decode("utf-8", errors="replace"),
            )
    except urllib.error.HTTPError as exc:
        return TelegramHttpResponse(
            status_code=int(exc.code),
            response_body=exc.read().decode("utf-8", errors="replace"),
        )


def _normalize_response(response: Any) -> TelegramHttpResponse:
    if isinstance(response, TelegramHttpResponse):
        return response
    if isinstance(response, dict):
        return TelegramHttpResponse(
            status_code=int(response.get("status_code", 0)),
            response_body=str(response.get("response_body", "")),
            provider_message_ref=response.get("provider_message_ref"),
        )
    raise TypeError("transport must return a dict or TelegramHttpResponse")


def _result(
    send_intent: TelegramProviderSendIntent,
    *,
    status: TelegramProviderLiveSendStatus,
    blockers: list[str],
    live_network_send_attempted: bool,
    send_performed: bool,
    remote_notification_send_count: int,
    request_body_hash: str | None = None,
    http_status_code: int | None = None,
    provider_message_ref: str | None = None,
    provider_response_preview: str | None = None,
    provider_error: str | None = None,
    secret_values_loaded: bool = False,
    secret_values_loaded_count: int = 0,
) -> TelegramProviderLiveSendResult:
    return TelegramProviderLiveSendResult(
        status=status,
        intent_id=send_intent.intent_id,
        message_class=send_intent.message_class,
        payload_hash=send_intent.payload_hash,
        request_body_hash=request_body_hash,
        queued_by_operator_id=send_intent.queued_by_operator_id,
        live_network_send_attempted=live_network_send_attempted,
        send_performed=send_performed,
        remote_notification_send_count=remote_notification_send_count,
        http_status_code=http_status_code,
        provider_message_ref=provider_message_ref,
        provider_response_preview=provider_response_preview,
        blocker_count=len(blockers),
        blocker_reasons=blockers,
        provider_error=provider_error,
        secret_values_loaded=secret_values_loaded,
        secret_values_loaded_count=secret_values_loaded_count,
    )


def _canonical_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
