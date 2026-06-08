from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field

from runtime_remote_provider_config_preflight import RuntimeRemoteProviderConfig
from runtime_remote_provider_policy import (
    RuntimeRemoteMessageClass,
    RuntimeRemoteProviderKind,
)
from runtime_remote_provider_send_queue import (
    RuntimeRemoteProviderSendIntent,
    RuntimeRemoteProviderSendIntentStatus,
)


class RuntimeRemoteProviderLiveAdapterModel(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")


class RuntimeRemoteProviderLiveSendStatus(StrEnum):
    SENT = "sent"
    BLOCKED = "live_send_blocked"
    PROVIDER_ERROR = "provider_error"


class RuntimeRemoteSecretRefScheme(StrEnum):
    ENV = "env"
    FILE = "file"
    KEYCHAIN = "keychain"


@dataclass
class RuntimeRemoteSecretResolver:
    env: dict[str, str] | None = None
    keychain_resolver: Callable[[str, str], str] | None = None
    file_reader: Callable[[Path], str] | None = None

    def read_env(self, name: str) -> str | None:
        if self.env is not None:
            return self.env.get(name)
        return os.environ.get(name)

    def read_file(self, path: Path) -> str:
        if self.file_reader is not None:
            return self.file_reader(path)
        return path.read_text(encoding="utf-8")

    def read_keychain(self, service: str, account: str) -> str:
        if self.keychain_resolver is not None:
            return self.keychain_resolver(service, account)
        return _read_macos_keychain_secret(service, account)


class RuntimeRemoteResolvedSecret(RuntimeRemoteProviderLiveAdapterModel):
    artifact_kind: Literal["runtime_remote_resolved_secret"] = (
        "runtime_remote_resolved_secret"
    )
    secret_ref: str = Field(min_length=1)
    scheme: RuntimeRemoteSecretRefScheme
    value_loaded: Literal[True] = True
    value_length: int
    value_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    value: str = Field(exclude=True, repr=False)


class RuntimeRemoteProviderLiveSendOptions(RuntimeRemoteProviderLiveAdapterModel):
    provider_adapter_enabled: bool = False
    live_network_send_enabled: bool = False
    manual_send_authorization: bool = False
    timeout_seconds: float = 10.0
    response_preview_max_chars: int = 240


@dataclass
class RuntimeRemoteWebhookHttpRequest:
    method: str
    endpoint_url: str
    headers: dict[str, str]
    body: dict[str, Any]
    timeout_seconds: float


@dataclass
class RuntimeRemoteWebhookHttpResponse:
    status_code: int
    response_body: str = ""
    provider_message_ref: str | None = None


class RuntimeRemoteProviderLiveSendResult(RuntimeRemoteProviderLiveAdapterModel):
    artifact_kind: Literal["runtime_remote_provider_live_send_result"] = (
        "runtime_remote_provider_live_send_result"
    )
    status: RuntimeRemoteProviderLiveSendStatus
    provider_id: str
    provider_kind: RuntimeRemoteProviderKind
    endpoint_ref: str
    recipient_ref: str
    delivery_target_secret_ref: str | None = None
    message_class: RuntimeRemoteMessageClass
    payload_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    request_body_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    queued_intent_id: str
    queued_by_operator_id: str
    live_network_send_attempted: bool
    send_performed: bool
    remote_notification_send_count: int
    http_status_code: int | None = None
    provider_message_ref: str | None = None
    provider_response_body_sha256: str | None = Field(
        default=None,
        pattern=r"^[a-f0-9]{64}$",
    )
    provider_response_preview: str | None = None
    secret_values_loaded: bool = False
    secret_values_loaded_count: int = 0
    secret_ref_schemes: list[RuntimeRemoteSecretRefScheme] = Field(
        default_factory=list
    )
    blocker_count: int = 0
    blocker_reasons: list[str] = Field(default_factory=list)
    provider_error: str | None = None
    summary_only: Literal[True] = True
    raw_payloads_embedded: Literal[False] = False
    raw_secret_values_embedded: Literal[False] = False
    endpoint_url_embedded: Literal[False] = False
    token_value_embedded: Literal[False] = False
    creates_provider_adapter: Literal[False] = False
    sends_network_request: bool = False
    incident_bridge_enable_count: Literal[0] = 0
    phase2_writeback_count: Literal[0] = 0

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n"


def resolve_runtime_remote_secret_ref(
    secret_ref: str,
    *,
    resolver: RuntimeRemoteSecretResolver | None = None,
) -> RuntimeRemoteResolvedSecret:
    active_resolver = resolver or RuntimeRemoteSecretResolver()
    scheme, ref_body = _split_secret_ref(secret_ref)
    if scheme == RuntimeRemoteSecretRefScheme.ENV:
        value = active_resolver.read_env(ref_body)
        if value is None:
            raise ValueError(f"missing env secret ref: {secret_ref}")
    elif scheme == RuntimeRemoteSecretRefScheme.FILE:
        value = active_resolver.read_file(Path(ref_body)).strip()
        if not value:
            raise ValueError(f"empty file secret ref: {secret_ref}")
    elif scheme == RuntimeRemoteSecretRefScheme.KEYCHAIN:
        service, account = _split_keychain_ref(ref_body)
        value = active_resolver.read_keychain(service, account).strip()
        if not value:
            raise ValueError(f"empty keychain secret ref: {secret_ref}")
    else:
        raise ValueError(f"unsupported secret ref scheme: {secret_ref}")

    return RuntimeRemoteResolvedSecret(
        secret_ref=secret_ref,
        scheme=scheme,
        value=value,
        value_length=len(value),
        value_sha256=hashlib.sha256(value.encode("utf-8")).hexdigest(),
    )


def send_runtime_remote_provider_webhook_intent(
    config: RuntimeRemoteProviderConfig,
    send_intent: RuntimeRemoteProviderSendIntent,
    *,
    options: RuntimeRemoteProviderLiveSendOptions | None = None,
    resolver: RuntimeRemoteSecretResolver | None = None,
    transport: Callable[[RuntimeRemoteWebhookHttpRequest], Any] | None = None,
) -> RuntimeRemoteProviderLiveSendResult:
    active_options = options or RuntimeRemoteProviderLiveSendOptions()
    blockers = _live_send_blockers(send_intent, active_options)
    if blockers:
        return _live_send_result(
            config,
            send_intent,
            status=RuntimeRemoteProviderLiveSendStatus.BLOCKED,
            blockers=blockers,
            live_network_send_attempted=False,
            send_performed=False,
            remote_notification_send_count=0,
        )

    try:
        endpoint_secret = resolve_runtime_remote_secret_ref(
            config.endpoint.endpoint_url_secret_ref,
            resolver=resolver,
        )
        auth_secret = resolve_runtime_remote_secret_ref(
            config.auth.auth_secret_ref,
            resolver=resolver,
        )
        signature_secret = (
            resolve_runtime_remote_secret_ref(
                config.auth.signature_secret_ref,
                resolver=resolver,
            )
            if config.auth.signature_secret_ref
            else None
        )
        delivery_secret = resolve_runtime_remote_secret_ref(
            send_intent.delivery_target_secret_ref or "",
            resolver=resolver,
        )
    except Exception as exc:
        return _live_send_result(
            config,
            send_intent,
            status=RuntimeRemoteProviderLiveSendStatus.BLOCKED,
            blockers=[f"secret_resolution_failed:{type(exc).__name__}"],
            live_network_send_attempted=False,
            send_performed=False,
            remote_notification_send_count=0,
            provider_error=str(exc),
        )

    body = _build_webhook_body(send_intent, delivery_secret.value)
    body_hash = _canonical_hash(body)
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {auth_secret.value}",
        "X-Scout-Payload-Hash": body_hash,
    }
    if signature_secret is not None:
        headers["X-Scout-Payload-Signature"] = _hmac_signature(
            signature_secret.value,
            body,
        )
    request = RuntimeRemoteWebhookHttpRequest(
        method="POST",
        endpoint_url=endpoint_secret.value,
        headers=headers,
        body=body,
        timeout_seconds=active_options.timeout_seconds,
    )
    secret_audits = [
        endpoint_secret,
        auth_secret,
        *( [signature_secret] if signature_secret is not None else [] ),
        delivery_secret,
    ]
    active_transport = transport or _urllib_json_post_transport
    try:
        response = _normalize_transport_response(active_transport(request))
    except Exception as exc:
        return _live_send_result(
            config,
            send_intent,
            status=RuntimeRemoteProviderLiveSendStatus.PROVIDER_ERROR,
            blockers=[],
            live_network_send_attempted=True,
            send_performed=False,
            remote_notification_send_count=0,
            request_body_hash=body_hash,
            provider_error=str(exc),
            secret_audits=secret_audits,
        )

    sent = 200 <= response.status_code < 300
    return _live_send_result(
        config,
        send_intent,
        status=(
            RuntimeRemoteProviderLiveSendStatus.SENT
            if sent
            else RuntimeRemoteProviderLiveSendStatus.PROVIDER_ERROR
        ),
        blockers=[] if sent else [f"provider_http_status:{response.status_code}"],
        live_network_send_attempted=True,
        send_performed=sent,
        remote_notification_send_count=1 if sent else 0,
        request_body_hash=body_hash,
        http_status_code=response.status_code,
        provider_message_ref=response.provider_message_ref,
        provider_response_body_sha256=_response_body_hash(response.response_body),
        provider_response_preview=None,
        secret_audits=secret_audits,
    )


def _live_send_blockers(
    send_intent: RuntimeRemoteProviderSendIntent,
    options: RuntimeRemoteProviderLiveSendOptions,
) -> list[str]:
    blockers: list[str] = []
    if send_intent.status != RuntimeRemoteProviderSendIntentStatus.QUEUED_NOT_SENT:
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


def _live_send_result(
    config: RuntimeRemoteProviderConfig,
    send_intent: RuntimeRemoteProviderSendIntent,
    *,
    status: RuntimeRemoteProviderLiveSendStatus,
    blockers: list[str],
    live_network_send_attempted: bool,
    send_performed: bool,
    remote_notification_send_count: int,
    request_body_hash: str | None = None,
    http_status_code: int | None = None,
    provider_message_ref: str | None = None,
    provider_response_body_sha256: str | None = None,
    provider_response_preview: str | None = None,
    provider_error: str | None = None,
    secret_audits: list[RuntimeRemoteResolvedSecret] | None = None,
) -> RuntimeRemoteProviderLiveSendResult:
    active_secret_audits = secret_audits or []
    return RuntimeRemoteProviderLiveSendResult(
        status=status,
        provider_id=send_intent.provider_id,
        provider_kind=send_intent.provider_kind,
        endpoint_ref=send_intent.endpoint_ref,
        recipient_ref=send_intent.recipient_ref,
        delivery_target_secret_ref=send_intent.delivery_target_secret_ref,
        message_class=send_intent.message_class,
        payload_hash=send_intent.payload_hash,
        request_body_hash=request_body_hash,
        queued_intent_id=send_intent.intent_id,
        queued_by_operator_id=send_intent.queued_by_operator_id,
        live_network_send_attempted=live_network_send_attempted,
        send_performed=send_performed,
        remote_notification_send_count=remote_notification_send_count,
        http_status_code=http_status_code,
        provider_message_ref=provider_message_ref,
        provider_response_body_sha256=provider_response_body_sha256,
        provider_response_preview=provider_response_preview,
        secret_values_loaded=bool(active_secret_audits),
        secret_values_loaded_count=len(active_secret_audits),
        secret_ref_schemes=[secret.scheme for secret in active_secret_audits],
        blocker_count=len(blockers),
        blocker_reasons=blockers,
        provider_error=provider_error,
        sends_network_request=live_network_send_attempted,
    )


def _build_webhook_body(
    send_intent: RuntimeRemoteProviderSendIntent,
    delivery_target: str,
) -> dict[str, Any]:
    return {
        "provider_id": send_intent.provider_id,
        "recipient_ref": send_intent.recipient_ref,
        "delivery_target": delivery_target,
        "message_class": send_intent.message_class.value,
        "body_preview": send_intent.body_preview,
        "payload_hash": send_intent.payload_hash,
        "queued_intent_id": send_intent.intent_id,
        "queued_at_iso": send_intent.queued_at_iso,
        "correlation_refs": send_intent.correlation_refs,
    }


def _urllib_json_post_transport(
    request: RuntimeRemoteWebhookHttpRequest,
) -> RuntimeRemoteWebhookHttpResponse:
    body_bytes = json.dumps(
        request.body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    urllib_request = urllib.request.Request(
        request.endpoint_url,
        data=body_bytes,
        headers=request.headers,
        method=request.method,
    )
    try:
        with urllib.request.urlopen(
            urllib_request,
            timeout=request.timeout_seconds,
        ) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            return RuntimeRemoteWebhookHttpResponse(
                status_code=int(response.status),
                response_body=response_body,
            )
    except urllib.error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        return RuntimeRemoteWebhookHttpResponse(
            status_code=int(exc.code),
            response_body=response_body,
        )


def _normalize_transport_response(response: Any) -> RuntimeRemoteWebhookHttpResponse:
    if isinstance(response, RuntimeRemoteWebhookHttpResponse):
        return response
    if isinstance(response, dict):
        return RuntimeRemoteWebhookHttpResponse(
            status_code=int(response.get("status_code", 0)),
            response_body=str(response.get("response_body", "")),
            provider_message_ref=response.get("provider_message_ref"),
        )
    raise TypeError("transport must return a dict or RuntimeRemoteWebhookHttpResponse")


def _split_secret_ref(secret_ref: str) -> tuple[RuntimeRemoteSecretRefScheme, str]:
    if ":" not in secret_ref:
        raise ValueError(f"secret ref must include a scheme: {secret_ref}")
    raw_scheme, ref_body = secret_ref.split(":", 1)
    try:
        scheme = RuntimeRemoteSecretRefScheme(raw_scheme)
    except ValueError as exc:
        raise ValueError(f"unsupported secret ref scheme: {secret_ref}") from exc
    if not ref_body:
        raise ValueError(f"secret ref body is empty: {secret_ref}")
    return scheme, ref_body


def _split_keychain_ref(ref_body: str) -> tuple[str, str]:
    if "/" in ref_body:
        service, account = ref_body.split("/", 1)
    elif ":" in ref_body:
        service, account = ref_body.split(":", 1)
    else:
        raise ValueError("keychain secret ref must be keychain:service/account")
    if not service or not account:
        raise ValueError("keychain secret ref requires service and account")
    return service, account


def _read_macos_keychain_secret(service: str, account: str) -> str:
    completed = subprocess.run(
        [
            "security",
            "find-generic-password",
            "-s",
            service,
            "-a",
            account,
            "-w",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def _hmac_signature(secret: str, body: dict[str, Any]) -> str:
    canonical = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _canonical_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _response_body_hash(value: str) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_preview(value: str, *, max_chars: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 3].rstrip() + "..."
