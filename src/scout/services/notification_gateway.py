"""Local notification gateway for Scout AI OS MVP."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
from urllib import request as urlrequest
from urllib.parse import urlparse
from typing import Any, Protocol
from uuid import uuid4

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
    ) -> None:
        if not allowed_user_ids:
            raise ValueError("allowed_user_ids must be non-empty")
        self.transport = transport
        self.approval = approval
        self.allowed_user_ids = set(allowed_user_ids)
        self.allowed_priorities = set(allowed_priorities or LOW_RISK_NOTIFICATION_PRIORITIES)
        self.required_phrase = required_phrase
        self.name = f"operator_confirmed:{transport.name}"
        self.notifications: list[NotificationResult] = []

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
        return None


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


def _redact_notification_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in metadata.items():
        normalized = key.casefold()
        if any(token in normalized for token in ("key", "secret", "token", "password")):
            redacted[key] = "[redacted]"
        else:
            redacted[key] = value
    return redacted


__all__ = [
    "DryRunNotificationProvider",
    "HttpsJsonNotificationTransport",
    "LOW_RISK_NOTIFICATION_PRIORITIES",
    "MemoryNotificationProvider",
    "MemoryExternalNotificationTransport",
    "NotificationGateway",
    "NotificationProvider",
    "NotificationResult",
    "OPERATOR_NOTIFICATION_APPROVAL_PHRASE",
    "OperatorConfirmedNotificationProvider",
    "OperatorNotificationApproval",
    "StdoutNotificationProvider",
]
