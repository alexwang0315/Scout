"""Local notification gateway for Scout AI OS MVP."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import uuid4

from scout.services.workflow_store import WorkflowStore


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


__all__ = [
    "DryRunNotificationProvider",
    "MemoryNotificationProvider",
    "NotificationGateway",
    "NotificationProvider",
    "NotificationResult",
    "StdoutNotificationProvider",
]
