"""Local notification gateway for Scout AI OS MVP."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import json
import time
from urllib import request as urlrequest
from urllib.parse import urlparse
from typing import Any, Callable, Protocol
from uuid import uuid4

from pydantic import ValidationError

from scout.schemas.outbound import OutboundActionIntent, OutboundStandingGrant
from scout.services.outbound_standing_grant import evaluate_outbound_standing_grant
from scout.services.workflow_store import WorkflowStore

OPERATOR_NOTIFICATION_APPROVAL_PHRASE = "SEND SCOUT NOTIFICATION"
LOW_RISK_NOTIFICATION_PRIORITIES = {"low", "normal"}


@dataclass(frozen=True)
class NotificationResult:
    notification_id: str
    user_id: str
    title: str
    body: str
    priority: str
    provider: str
    sent: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OperatorNotificationApproval:
    """Human approval record required before live external notification send."""

    approved_by: str
    recipient_id: str
    phrase: str
    risk_level: str = "low"
    reason: str = ""
    approved_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass(frozen=True)
class NotificationAuditRecord:
    """Non-secret audit entry for external notification send decisions."""

    audit_id: str
    notification_id: str
    provider: str
    user_id_hash: str
    priority: str
    sent: bool
    blocked_reason: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)


class NotificationProvider(Protocol):
    name: str

    def deliver(self, result: NotificationResult) -> NotificationResult:
        """Deliver or record a notification result."""


class StdoutNotificationProvider:
    name = "stdout"

    def deliver(self, result: NotificationResult) -> NotificationResult:
        print(f"[scout-notification:{result.priority}] {result.title}: {result.body}")
        return result


class MemoryNotificationProvider:
    name = "memory"

    def __init__(self) -> None:
        self.notifications: list[NotificationResult] = []

    def deliver(self, result: NotificationResult) -> NotificationResult:
        self.notifications.append(result)
        return result


class DryRunNotificationProvider:
    """Record an external notification intent without sending it."""

    def __init__(self, transport: str) -> None:
        transport_name = transport.strip()
        if not transport_name:
            raise ValueError("transport must be non-empty")
        self.transport = transport_name
        self.name = f"dry_run:{transport_name}"
        self.notifications: list[NotificationResult] = []

    def deliver(self, result: NotificationResult) -> NotificationResult:
        delivered = NotificationResult(
            notification_id=result.notification_id,
            user_id=result.user_id,
            title=result.title,
            body=result.body,
            priority=result.priority,
            provider=self.name,
            sent=False,
            metadata={
                **result.metadata,
                "dry_run": True,
                "transport": self.transport,
            },
        )
        self.notifications.append(delivered)
        return delivered


class MemoryExternalNotificationTransport:
    """Test transport that exercises the live external send path without network."""

    name = "external_memory"

    def __init__(self) -> None:
        self.notifications: list[NotificationResult] = []

    def deliver(self, result: NotificationResult) -> NotificationResult:
        delivered = NotificationResult(
            notification_id=result.notification_id,
            user_id=result.user_id,
            title=result.title,
            body=result.body,
            priority=result.priority,
            provider=self.name,
            sent=True,
            metadata=dict(result.metadata),
        )
        self.notifications.append(delivered)
        return delivered


class HttpsJsonNotificationTransport:
    """HTTPS JSON transport for operator-confirmed low-risk notifications."""

    name = "https_json"

    def __init__(
        self,
        endpoint_url: str,
        *,
        allowed_hosts: set[str] | None = None,
        authorization_header: str | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        parsed = urlparse(endpoint_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("external notification endpoint must be an HTTPS URL")
        if allowed_hosts is not None and parsed.hostname not in allowed_hosts:
            raise ValueError("external notification endpoint host is not allowlisted")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.endpoint_url = endpoint_url
        self.authorization_header = authorization_header
        self.timeout_seconds = timeout_seconds

    def deliver(self, result: NotificationResult) -> NotificationResult:
        payload = json.dumps(
            {
                "notification_id": result.notification_id,
                "user_id": result.user_id,
                "title": result.title,
                "body": result.body,
                "priority": result.priority,
                "metadata": _redact_notification_metadata(result.metadata),
            }
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.authorization_header:
            headers["Authorization"] = self.authorization_header
        req = urlrequest.Request(
            self.endpoint_url,
            data=payload,
            headers=headers,
            method="POST",
        )
        with urlrequest.urlopen(req, timeout=self.timeout_seconds) as response:
            status_code = int(response.status)
        return NotificationResult(
            notification_id=result.notification_id,
            user_id=result.user_id,
            title=result.title,
            body=result.body,
            priority=result.priority,
            provider=self.name,
            sent=200 <= status_code < 300,
            metadata={
                **result.metadata,
                "http_status": status_code,
                "endpoint_host": urlparse(self.endpoint_url).hostname,
                "authorization_header_present": self.authorization_header is not None,
            },
        )


class TelegramNotificationTransport:
    """Telegram Bot API transport for operator-confirmed low-risk notifications."""

    name = "telegram"

    def __init__(
        self,
        *,
        bot_token: str,
        chat_id: str,
        api_base_url: str = "https://api.telegram.org",
        allowed_hosts: set[str] | None = None,
        timeout_seconds: float = 10.0,
        urlopen: Callable[..., Any] | None = None,
    ) -> None:
        token = bot_token.strip()
        recipient = chat_id.strip()
        if not token:
            raise ValueError("bot_token must be non-empty")
        if not recipient:
            raise ValueError("chat_id must be non-empty")
        parsed = urlparse(api_base_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("Telegram API base URL must be HTTPS")
        allowlist = allowed_hosts or {"api.telegram.org"}
        if parsed.hostname not in allowlist:
            raise ValueError("Telegram API host is not allowlisted")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.bot_token = token
        self.chat_id = recipient
        self.api_base_url = api_base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._urlopen = urlopen or urlrequest.urlopen

    def deliver(self, result: NotificationResult) -> NotificationResult:
        endpoint_url = f"{self.api_base_url}/bot{self.bot_token}/sendMessage"
        payload = json.dumps(
            {
                "chat_id": self.chat_id,
                "text": f"{result.title}\n\n{result.body}",
                "disable_web_page_preview": True,
            }
        ).encode("utf-8")
        req = urlrequest.Request(
            endpoint_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self._urlopen(req, timeout=self.timeout_seconds) as response:
            status_code = int(response.status)
        parsed = urlparse(self.api_base_url)
        return NotificationResult(
            notification_id=result.notification_id,
            user_id=result.user_id,
            title=result.title,
            body=result.body,
            priority=result.priority,
            provider=self.name,
            sent=200 <= status_code < 300,
            metadata={
                **result.metadata,
                "http_status": status_code,
                "telegram_api_host": parsed.hostname,
                "telegram_bot_token_present": True,
                "telegram_chat_id_hash": _stable_secret_hash(self.chat_id),
            },
        )


class OperatorConfirmedNotificationProvider:
    """External notification provider guarded by explicit operator approval."""

    def __init__(
        self,
        transport: NotificationProvider,
        *,
        approval: OperatorNotificationApproval,
        allowed_user_ids: set[str],
        allowed_priorities: set[str] | None = None,
        required_phrase: str = OPERATOR_NOTIFICATION_APPROVAL_PHRASE,
        min_interval_seconds: float = 0.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if not allowed_user_ids:
            raise ValueError("allowed_user_ids must be non-empty")
        self.transport = transport
        self.approval = approval
        self.allowed_user_ids = set(allowed_user_ids)
        self.allowed_priorities = set(allowed_priorities or LOW_RISK_NOTIFICATION_PRIORITIES)
        self.required_phrase = required_phrase
        if min_interval_seconds < 0:
            raise ValueError("min_interval_seconds cannot be negative")
        self.min_interval_seconds = min_interval_seconds
        self._clock = clock or time.monotonic
        self._last_sent_at_by_user: dict[str, float] = {}
        self.name = f"operator_confirmed:{transport.name}"
        self.notifications: list[NotificationResult] = []
        self.audit_log: list[NotificationAuditRecord] = []

    def deliver(self, result: NotificationResult) -> NotificationResult:
        blocked_reason = self._blocked_reason(result)
        if blocked_reason is not None:
            delivered = _copy_notification_result(
                result,
                provider=self.name,
                sent=False,
                metadata={
                    **result.metadata,
                    "operator_confirmed": False,
                    "blocked_reason": blocked_reason,
                },
            )
            self.notifications.append(delivered)
            self._record_audit(delivered, blocked_reason=blocked_reason)
            return delivered

        transport_result = self.transport.deliver(
            _copy_notification_result(
                result,
                provider=self.transport.name,
                sent=True,
                metadata={
                    **result.metadata,
                    "operator_confirmed": True,
                    "approval_by": self.approval.approved_by,
                    "approval_at": self.approval.approved_at,
                    "approval_reason_present": bool(self.approval.reason),
                    "approval_risk_level": self.approval.risk_level,
                },
            )
        )
        delivered = _copy_notification_result(
            transport_result,
            provider=self.name,
            sent=transport_result.sent,
            metadata={
                **transport_result.metadata,
                "transport": self.transport.name,
                "operator_confirmed": True,
                "live_external_send_path": True,
            },
        )
        self.notifications.append(delivered)
        if delivered.sent:
            self._last_sent_at_by_user[delivered.user_id] = self._clock()
        self._record_audit(delivered, blocked_reason=None if delivered.sent else "transport_failed")
        return delivered

    def _blocked_reason(self, result: NotificationResult) -> str | None:
        if self.approval.phrase != self.required_phrase:
            return "approval_phrase_mismatch"
        if self.approval.recipient_id != result.user_id:
            return "approval_recipient_mismatch"
        if result.user_id not in self.allowed_user_ids:
            return "recipient_not_allowlisted"
        if result.priority not in self.allowed_priorities:
            return "priority_not_low_risk"
        if self.approval.risk_level != "low":
            return "approval_risk_not_low"
        last_sent_at = self._last_sent_at_by_user.get(result.user_id)
        if (
            last_sent_at is not None
            and self.min_interval_seconds > 0
            and self._clock() - last_sent_at < self.min_interval_seconds
        ):
            return "rate_limited"
        return None

    def _record_audit(
        self,
        result: NotificationResult,
        *,
        blocked_reason: str | None,
    ) -> None:
        self.audit_log.append(
            NotificationAuditRecord(
                audit_id=str(uuid4()),
                notification_id=result.notification_id,
                provider=result.provider,
                user_id_hash=_stable_secret_hash(result.user_id),
                priority=result.priority,
                sent=result.sent,
                blocked_reason=blocked_reason,
                metadata=_redact_notification_metadata(result.metadata),
            )
        )


class StandingGrantNotificationProvider:
    """Execute typed non-safety notifications within one reviewed grant."""

    def __init__(
        self,
        transport: NotificationProvider,
        *,
        provider_ref: str,
        grant: OutboundStandingGrant,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not provider_ref.strip():
            raise ValueError("provider_ref must be non-empty")
        self.transport = transport
        self.provider_ref = provider_ref
        self.grant = grant
        self._clock = clock or (lambda: datetime.now(UTC))
        self._send_count = 0
        self._sent_idempotency_keys: frozenset[str] = frozenset()
        self.name = f"standing_grant:{transport.name}"
        self.notifications: list[NotificationResult] = []
        self.audit_log: list[NotificationAuditRecord] = []

    @property
    def send_count(self) -> int:
        return self._send_count

    def deliver(self, result: NotificationResult) -> NotificationResult:
        intent = self._intent_from_result(result)
        if intent is None:
            return self._blocked(result, "typed_outbound_intent_missing")

        decision = evaluate_outbound_standing_grant(
            intent,
            grant=self.grant,
            now=self._clock(),
            prior_send_count=self._send_count,
        )
        local_blockers: list[str] = []
        if intent.provider_ref != self.provider_ref:
            local_blockers.append("notification_provider_intent_mismatch")
        if result.user_id != intent.recipient_ref:
            local_blockers.append("notification_recipient_intent_mismatch")
        if result.priority != intent.priority.value:
            local_blockers.append("notification_priority_intent_mismatch")
        if notification_payload_hash(
            title=result.title,
            body=result.body,
            priority=result.priority,
        ) != intent.payload_hash:
            local_blockers.append("notification_payload_hash_mismatch")
        if intent.idempotency_key in self._sent_idempotency_keys:
            local_blockers.append("duplicate_idempotency_key")
        blockers = [*decision.blocker_reasons, *local_blockers]
        if blockers:
            return self._blocked(result, ",".join(dict.fromkeys(blockers)), intent=intent)

        safe_metadata = _standing_grant_metadata(result.metadata, intent, self.grant)
        transport_result = self.transport.deliver(
            _copy_notification_result(
                result,
                provider=self.transport.name,
                sent=True,
                metadata=safe_metadata,
            )
        )
        delivered = _copy_notification_result(
            transport_result,
            provider=self.name,
            sent=transport_result.sent,
            metadata={
                **transport_result.metadata,
                "transport": self.transport.name,
                "standing_grant_id": self.grant.grant_id,
                "outbound_intent_id": intent.intent_id,
                "auto_execute_allowed": True,
                "live_external_send_path": True,
            },
        )
        self.notifications.append(delivered)
        if delivered.sent:
            self._send_count += 1
            self._sent_idempotency_keys = frozenset(
                {*self._sent_idempotency_keys, intent.idempotency_key}
            )
        self._record_audit(
            delivered,
            blocked_reason=None if delivered.sent else "transport_failed",
        )
        return delivered

    @staticmethod
    def _intent_from_result(result: NotificationResult) -> OutboundActionIntent | None:
        payload = result.metadata.get("outbound_intent")
        try:
            return OutboundActionIntent.model_validate(payload)
        except (ValidationError, TypeError, ValueError):
            return None

    def _blocked(
        self,
        result: NotificationResult,
        blocked_reason: str,
        *,
        intent: OutboundActionIntent | None = None,
    ) -> NotificationResult:
        metadata = dict(result.metadata)
        metadata.pop("outbound_intent", None)
        if intent is not None:
            metadata.update(_standing_grant_metadata(result.metadata, intent, self.grant))
        delivered = _copy_notification_result(
            result,
            provider=self.name,
            sent=False,
            metadata={
                **metadata,
                "standing_grant_id": self.grant.grant_id,
                "auto_execute_allowed": False,
                "blocked_reason": blocked_reason,
            },
        )
        self.notifications.append(delivered)
        self._record_audit(delivered, blocked_reason=blocked_reason)
        return delivered

    def _record_audit(
        self,
        result: NotificationResult,
        *,
        blocked_reason: str | None,
    ) -> None:
        self.audit_log.append(
            NotificationAuditRecord(
                audit_id=str(uuid4()),
                notification_id=result.notification_id,
                provider=result.provider,
                user_id_hash=_stable_secret_hash(result.user_id),
                priority=result.priority,
                sent=result.sent,
                blocked_reason=blocked_reason,
                metadata=_redact_notification_metadata(result.metadata),
            )
        )


class NotificationGateway:
    """MVP notification gateway that logs locally and records workflow events."""

    def __init__(
        self,
        workflow_store: WorkflowStore | None = None,
        *,
        provider: NotificationProvider | None = None,
    ) -> None:
        self._workflow_store = workflow_store
        self._provider = provider or StdoutNotificationProvider()

    def send(
        self,
        user_id: str,
        title: str,
        body: str,
        priority: str = "normal",
        metadata: dict[str, Any] | None = None,
    ) -> NotificationResult:
        result = NotificationResult(
            notification_id=str(uuid4()),
            user_id=user_id,
            title=title,
            body=body,
            priority=priority,
            provider=self._provider.name,
            metadata=dict(metadata or {}),
        )
        delivered = self._provider.deliver(result)

        workflow_id = delivered.metadata.get("workflow_id")
        if workflow_id and self._workflow_store is not None:
            self._workflow_store.record_event(
                workflow_id,
                "notification.sent",
                {
                    "notification_id": delivered.notification_id,
                    "title": title,
                    "priority": priority,
                    "provider": delivered.provider,
                    "sent": delivered.sent,
                },
            )
        return delivered


def _copy_notification_result(
    result: NotificationResult,
    *,
    provider: str,
    sent: bool,
    metadata: dict[str, Any],
) -> NotificationResult:
    return NotificationResult(
        notification_id=result.notification_id,
        user_id=result.user_id,
        title=result.title,
        body=result.body,
        priority=result.priority,
        provider=provider,
        sent=sent,
        metadata=metadata,
    )


def notification_payload_hash(*, title: str, body: str, priority: str) -> str:
    payload = json.dumps(
        {"body": body, "priority": priority, "title": title},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _standing_grant_metadata(
    metadata: dict[str, Any],
    intent: OutboundActionIntent,
    grant: OutboundStandingGrant,
) -> dict[str, Any]:
    safe_metadata = dict(metadata)
    safe_metadata.pop("outbound_intent", None)
    safe_metadata.update(
        {
            "standing_grant_id": grant.grant_id,
            "outbound_intent_id": intent.intent_id,
            "outbound_message_class": intent.message_class,
            "outbound_provider_ref": intent.provider_ref,
            "outbound_recipient_ref": intent.recipient_ref,
            "outbound_payload_hash": intent.payload_hash,
            "outbound_data_classes": [item.value for item in intent.data_classes],
            "outbound_scope_ref": intent.scope_ref,
        }
    )
    return safe_metadata


def _redact_notification_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in metadata.items():
        normalized = key.casefold()
        if any(token in normalized for token in ("key", "secret", "token", "password")):
            redacted[key] = "[redacted]"
        else:
            redacted[key] = value
    return redacted


def _stable_secret_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


__all__ = [
    "DryRunNotificationProvider",
    "HttpsJsonNotificationTransport",
    "LOW_RISK_NOTIFICATION_PRIORITIES",
    "MemoryNotificationProvider",
    "MemoryExternalNotificationTransport",
    "NotificationAuditRecord",
    "NotificationGateway",
    "NotificationProvider",
    "NotificationResult",
    "notification_payload_hash",
    "OPERATOR_NOTIFICATION_APPROVAL_PHRASE",
    "OperatorConfirmedNotificationProvider",
    "OperatorNotificationApproval",
    "StdoutNotificationProvider",
    "StandingGrantNotificationProvider",
    "TelegramNotificationTransport",
]
