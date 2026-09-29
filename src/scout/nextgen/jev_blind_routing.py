"""Label-blinded question input and JEV-authoritative route selection.

The blind input deliberately has no expected route or standard answer.  It is
safe to pass to JEV and the runtime because the route is selected only after
JEV returns a typed choice.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import ConfigDict, Field

from scout.nextgen.jev_decisions import (
    JevChoiceAnswer,
    JevChoiceQuestion,
    JevDecisionRequest,
    JevDecisionResponse,
)
from scout.nextgen.jev_model_routing import ModelRoute, RoutingCapability
from scout.schemas.base import NonEmptyStr, SchemaModel


class BlindQuestion(SchemaModel):
    """A user-supplied question with no answer key or route label."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    question_id: NonEmptyStr
    question: NonEmptyStr
    category: NonEmptyStr | None = None
    capabilities: tuple[RoutingCapability, ...] = ()
    required_tools: tuple[NonEmptyStr, ...] = ()
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


class BlindQuestionSet(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["scout.ai.jev_blind_questions.v1"]
    questions: tuple[BlindQuestion, ...] = Field(min_length=1, max_length=100)
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


def load_blind_questions(path: Path) -> BlindQuestionSet:
    """Load user questions and reject answer-key fields at the schema boundary."""

    value = json.loads(path.read_text(encoding="utf-8"))
    return BlindQuestionSet.model_validate(value)


def build_blind_jev_route_request(
    question: BlindQuestion,
    *,
    model_id: str,
    workspace_context: dict[str, Any] | None = None,
) -> JevDecisionRequest:
    """Build the JEV request without any expected answer or route label."""

    state: dict[str, Any] = {
        "question_id": question.question_id,
        "question": question.question,
        "category": question.category,
        "capabilities": [item.value for item in question.capabilities],
        "required_tools": list(question.required_tools),
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    if workspace_context is not None:
        state["workspace"] = workspace_context
    return JevDecisionRequest(
        model=model_id,
        state=state,
        questions={
            "model_route": JevChoiceQuestion(
                type="choice",
                instructions=(
                    "Choose the execution route after considering the workspace "
                    "evidence status. Local can answer a short static fact when "
                    "read-only deterministic Scout tools have already completed "
                    "and their evidence can be supplied to the local model. Do not "
                    "choose cloud merely because a completed workspace tool is "
                    "listed. Use cloud for live data, web research, missing evidence, "
                    "or complex joins. Use human_review for ambiguous or "
                    "authority-bearing requests. This choice does not execute a route."
                ),
                criteria={
                    "local": "Short static fact with completed read-only workspace evidence available to the local model; no live external dependency.",
                    "cloud": "Live data, web search, unresolved evidence, or complex cross-artifact reasoning is required.",
                    "human_review": "The request is ambiguous or authority-bearing and needs human review.",
                },
            )
        },
    )


def parse_jev_route(response: JevDecisionResponse) -> ModelRoute:
    """Parse the only route authority for a blind run."""

    answer = response.answers.get("model_route")
    if not isinstance(answer, JevChoiceAnswer):
        raise TypeError("JEV response did not contain a typed model_route choice")
    try:
        return ModelRoute(answer.choice)
    except ValueError as exc:
        raise ValueError(f"JEV returned unsupported route: {answer.choice!r}") from exc


__all__ = [
    "BlindQuestion",
    "BlindQuestionSet",
    "build_blind_jev_route_request",
    "load_blind_questions",
    "parse_jev_route",
]
