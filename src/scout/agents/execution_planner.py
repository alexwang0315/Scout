"""Typed ExecutionPlannerAgent facade for Scout AI OS Phase 5."""

from __future__ import annotations

import json
from typing import Any

from scout.agents.deps import (
    ScoutAgentProvider,
    ScoutAgentRequest,
    ScoutDeps,
    build_toolbox,
    validate_provider_output,
)
from scout.schemas.capability import CapabilityBuildRequest, CapabilityRisk
from scout.schemas.runtime import ExecutionPlan, PlanMode
from scout.schemas.workflow import WorkflowSpec


EXECUTION_PLANNER_INSTRUCTIONS = """\
You are ExecutionPlannerAgent for Scout AI OS Phase 5.
Return only an ExecutionPlan-compatible object.
Rules:
- Prefer existing capabilities.
- Compose capabilities before generating new code.
- Propose BUILD_NEW_CAPABILITY only for low-risk parser, formatter, classifier, calculator, validator, or data transformer capabilities.
- Never approve high-risk generated code.
- Must produce approval message when required.
- Must not execute workflows or install capabilities.
"""


class ExecutionPlannerAgent:
    """Plan how a ``WorkflowSpec`` candidate could be executed."""

    def __init__(self, provider: ScoutAgentProvider) -> None:
        self._provider = provider

    def plan(self, workflow: WorkflowSpec, deps: ScoutDeps) -> ExecutionPlan:
        """Return a validated execution plan candidate without running it."""

        request = ScoutAgentRequest(
            agent_name="ExecutionPlannerAgent",
            instructions=EXECUTION_PLANNER_INSTRUCTIONS,
            prompt=_planning_prompt(workflow=workflow, deps=deps),
            output_type=ExecutionPlan,
            deps=deps,
            tools=build_toolbox(deps),
            context={
                "workflow": workflow.model_dump(mode="json"),
                "active_context": dict(deps.active_context),
            },
        )
        plan = validate_provider_output(
            self._provider.run(request),
            ExecutionPlan,
        )
        _assert_execution_plan_safety(plan)
        return plan


def _planning_prompt(*, workflow: WorkflowSpec, deps: ScoutDeps) -> str:
    payload: dict[str, Any] = {
        "user_id": deps.user_id,
        "workflow": workflow.model_dump(mode="json"),
        "active_context": deps.active_context,
        "output": "ExecutionPlan",
    }
    return json.dumps(payload, sort_keys=True)


def _assert_execution_plan_safety(plan: ExecutionPlan) -> None:
    if plan.workflow.permissions.approval_required and not plan.approval_message:
        raise ValueError(
            "ExecutionPlannerAgent output must include approval_message when "
            "workflow approval is required."
        )

    if plan.mode is PlanMode.BUILD_NEW_CAPABILITY:
        if plan.build_request is None:
            raise ValueError(
                "ExecutionPlannerAgent BUILD_NEW_CAPABILITY plans must include "
                "a build_request."
            )
        build_request = CapabilityBuildRequest.model_validate(plan.build_request)
        if build_request.risk_level is not CapabilityRisk.LOW:
            raise ValueError(
                "ExecutionPlannerAgent may only request low-risk generated "
                "capabilities in Phase 5."
            )


__all__ = ["ExecutionPlannerAgent", "EXECUTION_PLANNER_INSTRUCTIONS"]
