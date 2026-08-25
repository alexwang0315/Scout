"""Deterministic workflow executor for Scout AI OS MVP."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from scout.runtime.actions import ActionExecutor
from scout.runtime.triggers import TriggerEvaluator
from scout.schemas.workflow import TriggerType, WorkflowLifecycle
from scout.services.permission_gate import PermissionGate
from scout.services.workflow_store import WorkflowRecord, WorkflowStore


@dataclass(frozen=True)
class WorkflowRunResult:
    workflow_id: str
    status: str
    events: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class RuntimeTickResult:
    checked: int
    ran: int
    paused: int
    failed: int
    results: list[WorkflowRunResult] = field(default_factory=list)


class RuntimeExecutor:
    """Run due workflows through deterministic MVP trigger/action logic."""

    def __init__(
        self,
        workflow_store: WorkflowStore,
        permission_gate: PermissionGate,
        action_executor: ActionExecutor,
        trigger_evaluator: TriggerEvaluator | None = None,
    ) -> None:
        self._workflow_store = workflow_store
        self._permission_gate = permission_gate
        self._action_executor = action_executor
        self._trigger_evaluator = trigger_evaluator or TriggerEvaluator()

    def tick(self, now: datetime | None = None) -> RuntimeTickResult:
        tick_time = now or datetime.now(UTC)
        due_workflows = self._workflow_store.list_due_workflows(tick_time)
        results = [self.run_workflow(record, tick_time) for record in due_workflows]
        return RuntimeTickResult(
            checked=len(due_workflows),
            ran=sum(result.status in {"completed", "scheduled"} for result in results),
            paused=sum(result.status == "paused" for result in results),
            failed=sum(result.status == "failed" for result in results),
            results=results,
        )

    def run_workflow(
        self,
        record: WorkflowRecord,
        now: datetime | None = None,
    ) -> WorkflowRunResult:
        run_time = now or datetime.now(UTC)
        decision = self._permission_gate.evaluate_workflow(record.workflow)
        if not decision.allowed:
            self._workflow_store.pause(record.id, decision.reason)
            return WorkflowRunResult(
                workflow_id=record.id,
                status="paused",
                events=[{"permission": decision.model_dump(mode="json")}],
            )
        if (
            decision.requires_user_approval
            and not self._workflow_store.is_approved(record.id)
        ):
            self._workflow_store.pause(record.id, decision.reason)
            return WorkflowRunResult(
                workflow_id=record.id,
                status="paused",
                events=[{"permission": decision.model_dump(mode="json")}],
            )

        if not self._trigger_evaluator.is_satisfied(record.workflow.trigger, run_time):
            self._workflow_store.set_next_run_at(record.id, run_time + timedelta(minutes=1))
            return WorkflowRunResult(workflow_id=record.id, status="not_due")

        try:
            action_events = []
            for action in record.workflow.actions:
                payload = self._action_executor.execute(record, action)
                if payload.get("status") == "unsupported":
                    raise RuntimeError(
                        "unsupported action result: "
                        + str(payload.get("message") or action.type.value)
                    )
                self._workflow_store.record_event(
                    record.id,
                    "action.executed",
                    {"action_type": action.type.value, "result": payload},
                )
                action_events.append(payload)

            if record.workflow.lifecycle is WorkflowLifecycle.ONE_SHOT:
                self._workflow_store.complete(record.id)
                status = "completed"
            else:
                self._workflow_store.set_next_run_at(
                    record.id,
                    _next_run_at(record, run_time),
                )
                status = "scheduled"
            return WorkflowRunResult(
                workflow_id=record.id,
                status=status,
                events=action_events,
            )
        except Exception as exc:
            self._workflow_store.record_failure(record.id, str(exc))
            return WorkflowRunResult(
                workflow_id=record.id,
                status="failed",
                events=[{"error": str(exc)}],
            )


def _next_run_at(record: WorkflowRecord, run_time: datetime) -> datetime:
    recurrence = record.workflow.trigger.config.get("recurrence")
    if (
        record.workflow.trigger.type is TriggerType.TIME
        and recurrence == "daily"
        and record.next_run_at is not None
    ):
        next_run_at = record.next_run_at
        while next_run_at <= run_time:
            next_run_at += timedelta(days=1)
        return next_run_at
    return run_time + timedelta(hours=1)


__all__ = ["RuntimeExecutor", "RuntimeTickResult", "WorkflowRunResult"]
