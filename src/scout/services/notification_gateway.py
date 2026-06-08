"""Local notification gateway for Scout AI OS MVP."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from scout.services.workflow_store import WorkflowStore


@dataclass(frozen=True)
class NotificationResult:
    notification_id: str
    user_id: str
    title: str
    body: str
    priority: str
    sent: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


class NotificationGateway:
    """MVP notification gateway that logs locally and records workflow events."""

    def __init__(self, workflow_store: WorkflowStore | None = None) -> None:
        self._workflow_store = workflow_store

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
            metadata=dict(metadata or {}),
        )
        print(f"[scout-notification:{priority}] {title}: {body}")

        workflow_id = result.metadata.get("workflow_id")
        if workflow_id and self._workflow_store is not None:
            self._workflow_store.record_event(
                workflow_id,
                "notification.sent",
                {
                    "notification_id": result.notification_id,
                    "title": title,
                    "priority": priority,
                },
            )
        return result


__all__ = ["NotificationGateway", "NotificationResult"]
