"""Typed WorkflowCompilerAgent facade for Scout AI OS Phase 5."""

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
from scout.schemas.workflow import (
    ActionType,
    TriggerType,
    WorkflowLifecycle,
    WorkflowSpec,
)


WORKFLOW_COMPILER_INSTRUCTIONS = """\
You are WorkflowCompilerAgent for Scout AI OS Phase 5.
Return only a WorkflowSpec-compatible object.
Rules:
- Must not execute actions.
- Must not claim the workflow is installed.
- Must mark required permissions.
- Must set approval_required = true for sensitive or persistent workflows.
- If details are ambiguous, put assumptions in fallback_policy and checks in verification_plan.
- Prefer safe defaults.
"""


SENSITIVE_TRIGGER_TYPES = {
    TriggerType.LOCATION,
    TriggerType.EMAIL,
    TriggerType.CALENDAR,
    TriggerType.WEB_CHANGE,
    TriggerType.FILE_CHANGE,
}

SENSITIVE_ACTION_TYPES = {
    ActionType.CALL_API,
    ActionType.RUN_SANDBOX_SCRIPT,
}

SENSITIVE_PERMISSION_TERMS = (
    "location",
    "private",
    "email",
    "calendar",
    "file",
    "web",
    "scrape",
    "monitor",
    "generated",
)


class WorkflowCompilerAgent:
    """Compile a user utterance into a typed ``WorkflowSpec`` candidate."""

    def __init__(self, provider: ScoutAgentProvider) -> None:
        self._provider = provider

    def compile(self, utterance: str, deps: ScoutDeps) -> WorkflowSpec:
        """Return a validated workflow candidate without executing it."""

        prompt = _workflow_prompt(utterance=utterance, deps=deps)
        request = ScoutAgentRequest(
            agent_name="WorkflowCompilerAgent",
            instructions=WORKFLOW_COMPILER_INSTRUCTIONS,
            prompt=prompt,
            output_type=WorkflowSpec,
            deps=deps,
            tools=build_toolbox(deps),
            context={"utterance": utterance, "active_context": dict(deps.active_context)},
        )
        workflow = validate_provider_output(
            self._provider.run(request),
            WorkflowSpec,
        )
        _assert_workflow_safety(workflow)
        return workflow


def _workflow_prompt(*, utterance: str, deps: ScoutDeps) -> str:
    payload: dict[str, Any] = {
        "user_id": deps.user_id,
        "source_utterance": utterance,
        "active_context": deps.active_context,
        "output": "WorkflowSpec",
    }
    return json.dumps(payload, sort_keys=True)


def _assert_workflow_safety(workflow: WorkflowSpec) -> None:
    if _requires_approval(workflow) and not workflow.permissions.approval_required:
        raise ValueError(
            "WorkflowCompilerAgent output must require approval for sensitive "
            "or persistent workflows."
        )


def _requires_approval(workflow: WorkflowSpec) -> bool:
    permission_text = " ".join(workflow.permissions.required).lower()
    return (
        workflow.lifecycle is WorkflowLifecycle.PERMANENT
        or workflow.trigger.type in SENSITIVE_TRIGGER_TYPES
        or any(action.type in SENSITIVE_ACTION_TYPES for action in workflow.actions)
        or any(term in permission_text for term in SENSITIVE_PERMISSION_TERMS)
    )


__all__ = ["WorkflowCompilerAgent", "WORKFLOW_COMPILER_INSTRUCTIONS"]
