"""Action execution for supported Scout AI OS MVP actions."""

from __future__ import annotations

from typing import Any

from scout.schemas.capability import CapabilitySpec
from scout.schemas.workflow import ActionSpec, ActionType, WorkflowSpec
from scout.services.capability_registry import CapabilityRegistry
from scout.services.notification_gateway import NotificationGateway
from scout.services.workflow_store import WorkflowRecord


class ActionExecutor:
    """Execute supported deterministic MVP actions."""

    def __init__(
        self,
        notification_gateway: NotificationGateway,
        capability_registry: CapabilityRegistry,
    ) -> None:
        self._notification_gateway = notification_gateway
        self._capability_registry = capability_registry

    def execute(self, record: WorkflowRecord, action: ActionSpec) -> dict[str, Any]:
        if action.type is ActionType.NOTIFY:
            return self._execute_notify(record, action)
        if action.type is ActionType.ASK_USER:
            return self._execute_ask_user(record, action)
        if action.type is ActionType.RUN_CAPABILITY:
            return self._execute_builtin_capability(record.workflow, action)
        return {
            "status": "unsupported",
            "action_type": action.type.value,
            "message": "Action type is stubbed in the MVP runtime.",
        }

    def _execute_notify(
        self,
        record: WorkflowRecord,
        action: ActionSpec,
    ) -> dict[str, Any]:
        title = str(action.config.get("title") or record.workflow.name)
        body = str(action.config.get("body") or action.description)
        priority = str(action.config.get("priority") or "normal")
        result = self._notification_gateway.send(
            record.user_id,
            title,
            body,
            priority=priority,
            metadata={"workflow_id": record.id, "action_type": action.type.value},
        )
        return {
            "status": "sent",
            "notification_id": result.notification_id,
            "sent": result.sent,
        }

    def _execute_ask_user(
        self,
        record: WorkflowRecord,
        action: ActionSpec,
    ) -> dict[str, Any]:
        result = self._notification_gateway.send(
            record.user_id,
            str(action.config.get("title") or "Scout needs input"),
            str(action.config.get("body") or action.description),
            priority="high",
            metadata={"workflow_id": record.id, "action_type": action.type.value},
        )
        return {
            "status": "asked",
            "notification_id": result.notification_id,
        }

    def _execute_builtin_capability(
        self,
        workflow: WorkflowSpec,
        action: ActionSpec,
    ) -> dict[str, Any]:
        capability_name = str(action.config.get("capability") or "")
        spec = self._capability_registry.get(capability_name)
        if spec is None:
            raise KeyError(f"capability not found: {capability_name}")
        return self._run_supported_builtin(spec, action.config.get("input") or {})

    @staticmethod
    def _run_supported_builtin(
        spec: CapabilitySpec,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if spec.name == "json_transform":
            return {"status": "completed", "payload": payload.get("payload", payload)}
        if spec.name in {"manual_notification", "time_reminder"}:
            return {"status": "metadata_only", "capability": spec.name}
        return {"status": "unsupported", "capability": spec.name}


__all__ = ["ActionExecutor"]
