"""Typed LearningAgent facade for Scout AI OS Phase 5."""

from __future__ import annotations

import json
import re
from typing import Any

from scout.agents.deps import (
    ScoutAgentProvider,
    ScoutAgentRequest,
    ScoutDeps,
    build_toolbox,
    validate_provider_output,
)
from scout.schemas.learning import LearningBundle
from scout.schemas.runtime import ExecutionPlan
from scout.schemas.workflow import WorkflowSpec


LEARNING_AGENT_INSTRUCTIONS = """\
You are LearningAgent for Scout AI OS Phase 5.
Return only a LearningBundle-compatible object.
Rules:
- Do not save secrets.
- Do not convert a one-off detail into a permanent preference.
- Prefer candidates requiring review.
- Produce eval cases for workflow compiler regression.
- Produce workflow templates only when the pattern is reusable.
- Do not mutate memory, workflow stores, or runtime safety truth.
"""


class LearningAgent:
    """Propose reviewable learning artifacts without persisting them."""

    def __init__(self, provider: ScoutAgentProvider) -> None:
        self._provider = provider

    def propose(
        self,
        workflow: WorkflowSpec,
        deps: ScoutDeps,
        *,
        execution_plan: ExecutionPlan | None = None,
        outcome_summary: str = "",
    ) -> LearningBundle:
        """Return a validated learning bundle candidate."""

        request = ScoutAgentRequest(
            agent_name="LearningAgent",
            instructions=LEARNING_AGENT_INSTRUCTIONS,
            prompt=_learning_prompt(
                workflow=workflow,
                deps=deps,
                execution_plan=execution_plan,
                outcome_summary=outcome_summary,
            ),
            output_type=LearningBundle,
            tools=build_toolbox(deps, allowed_tools=()),
            context={
                "workflow": workflow.model_dump(mode="json"),
                "execution_plan": (
                    execution_plan.model_dump(mode="json")
                    if execution_plan is not None
                    else None
                ),
                "outcome_summary": outcome_summary,
                "active_context": dict(deps.active_context),
            },
        )
        bundle = validate_provider_output(
            self._provider.run(request),
            LearningBundle,
        )
        _assert_learning_bundle_reviewable(bundle)
        return bundle


def _learning_prompt(
    *,
    workflow: WorkflowSpec,
    deps: ScoutDeps,
    execution_plan: ExecutionPlan | None,
    outcome_summary: str,
) -> str:
    payload: dict[str, Any] = {
        "user_id": deps.user_id,
        "workflow": workflow.model_dump(mode="json"),
        "execution_plan": (
            execution_plan.model_dump(mode="json")
            if execution_plan is not None
            else None
        ),
        "outcome_summary": outcome_summary,
        "active_context": deps.active_context,
        "output": "LearningBundle",
    }
    return json.dumps(payload, sort_keys=True)


def _assert_learning_bundle_reviewable(bundle: LearningBundle) -> None:
    if any(not artifact.requires_review for artifact in bundle.artifacts):
        raise ValueError("LearningAgent artifacts must require review in Phase 5.")
    if _contains_sensitive_content(bundle.model_dump(mode="json")):
        raise ValueError("LearningAgent candidate contains sensitive content.")


_SENSITIVE_KEY_PARTS = (
    "api_key",
    "authorization",
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
)
_SENSITIVE_VALUES = (
    re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{6,}"),
    re.compile(
        r"(?i)\b(?:sk-|nvapi-|gh[pousr]_|github_pat_|xox[baprs]-)"
        r"[A-Za-z0-9_-]{8,}"
    ),
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
)


def _contains_sensitive_content(value: Any, *, key: str = "") -> bool:
    if any(part in key.casefold() for part in _SENSITIVE_KEY_PARTS):
        return True
    if isinstance(value, dict):
        return any(
            _contains_sensitive_content(item, key=str(item_key))
            for item_key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_sensitive_content(item, key=key) for item in value)
    if isinstance(value, str):
        return any(pattern.search(value) for pattern in _SENSITIVE_VALUES)
    return False


__all__ = ["LearningAgent", "LEARNING_AGENT_INSTRUCTIONS"]
