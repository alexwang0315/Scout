"""Action execution for supported Scout AI OS MVP actions."""

from __future__ import annotations

from typing import Any

from scout.schemas.capability import CapabilitySpec
from scout.schemas.workflow import ActionSpec, ActionType, WorkflowSpec
from scout.services.capability_registry import CapabilityRegistry
from scout.services.notification_gateway import NotificationGateway
from scout.services.workflow_store import WorkflowRecord
from scout.ui_action_plan import (
    ARTIFACT_KIND,
    ARTIFACT_VERSION,
    build_scout_ui_action_plan,
)


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
        if action.type is ActionType.UI_ACTION:
            return self._execute_ui_action(action)
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
        metadata: dict[str, Any] = {
            "workflow_id": record.id,
            "action_type": action.type.value,
        }
        outbound_intent = action.config.get("outbound_intent")
        if isinstance(outbound_intent, dict):
            metadata = {**metadata, "outbound_intent": dict(outbound_intent)}
        result = self._notification_gateway.send(
            record.user_id,
            title,
            body,
            priority=priority,
            metadata=metadata,
        )
        response = {
            "status": "sent",
            "notification_id": result.notification_id,
            "sent": result.sent,
        }
        standing_grant_id = result.metadata.get("standing_grant_id")
        if standing_grant_id is not None:
            response["standing_grant_id"] = standing_grant_id
        return response

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

    def _execute_ui_action(self, action: ActionSpec) -> dict[str, Any]:
        plan = action.config.get("ui_action_plan")
        if not isinstance(plan, dict):
            surface = str(action.config.get("surface") or "")
            request_text = str(action.config.get("request_text") or action.description)
            if not surface:
                return {
                    "status": "unsupported",
                    "action_type": action.type.value,
                    "message": "UI action requires ui_action_plan or surface/request_text config.",
                }
            try:
                plan = build_scout_ui_action_plan(
                    surface=surface,
                    request_text=request_text,
                    preset=_string_or_none(action.config.get("preset")),
                    target_kind=_string_or_none(action.config.get("target_kind")),
                    target_ref=_string_or_none(action.config.get("target_ref")),
                    query=_string_or_none(action.config.get("query")),
                    tab=_string_or_none(action.config.get("tab")),
                )
            except ValueError as exc:
                return {
                    "status": "unsupported",
                    "action_type": action.type.value,
                    "message": str(exc),
                }

        return {
            "status": str(plan.get("status") or "planned"),
            "action_type": action.type.value,
            "artifact_kind": str(plan.get("artifact_kind") or ARTIFACT_KIND),
            "artifact_version": str(plan.get("artifact_version") or ARTIFACT_VERSION),
            "application_required": (
                plan.get("front_end_executor", {}).get("global")
                if isinstance(plan.get("front_end_executor"), dict)
                else None
            ),
            "session_only": True,
            "ui_action_plan": plan,
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


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


__all__ = ["ActionExecutor"]
