"""Advisory JEV routing for local-versus-cloud question evaluation.

This module deliberately does not make a model, tool, or JEV response a safety
authority.  A deterministic question contract decides whether a case requires
external evidence.  JEV may recommend escalating a local-eligible case, but it
cannot downgrade a cloud-required case to the local model.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import ConfigDict, Field

from scout.nextgen.jev_decisions import (
    JevChoiceAnswer,
    JevChoiceQuestion,
    JevDecisionRequest,
    JevDecisionResponse,
)
from scout.schemas.base import NonEmptyStr, SchemaModel


class ModelRoute(StrEnum):
    LOCAL = "local"
    CLOUD = "cloud"
    HUMAN_REVIEW = "human_review"


class RoutingCapability(StrEnum):
    STATIC_FACT = "static_fact"
    DETERMINISTIC_ARITHMETIC = "deterministic_arithmetic"
    STRUCTURED_EXTRACTION = "structured_extraction"
    BOUNDARY_RECOGNITION = "boundary_recognition"
    WEB_SEARCH = "web_search"
    TOOL_USE = "tool_use"
    FRESH_LIVE_DATA = "fresh_live_data"
    CROSS_ARTIFACT_JOIN = "cross_artifact_join"
    SPATIAL_QUERY = "spatial_query"
    SAFETY_SENSITIVE = "safety_sensitive"


CLOUD_REQUIRED_CAPABILITIES = frozenset(
    {
        RoutingCapability.WEB_SEARCH,
        RoutingCapability.TOOL_USE,
        RoutingCapability.FRESH_LIVE_DATA,
        RoutingCapability.CROSS_ARTIFACT_JOIN,
        RoutingCapability.SPATIAL_QUERY,
        RoutingCapability.SAFETY_SENSITIVE,
    }
)


class AnswerContract(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["exact", "choice", "structured", "evidence_grounded"]
    expected: str | None = None
    required_fields: tuple[NonEmptyStr, ...] = ()
    must_state_unknowns: bool = False


class RoutingQuestion(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    question_id: NonEmptyStr
    question: NonEmptyStr
    category: NonEmptyStr
    expected_route: ModelRoute
    capabilities: tuple[RoutingCapability, ...] = Field(min_length=1)
    standard_answer: NonEmptyStr
    answer_contract: AnswerContract
    source_refs: tuple[NonEmptyStr, ...] = Field(min_length=1)
    required_tools: tuple[NonEmptyStr, ...] = ()
    cloud_reason: NonEmptyStr | None = None
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


class RoutingCorpus(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["scout.ai.local_cloud_routing_corpus.v1"]
    workspace_id: NonEmptyStr
    description: NonEmptyStr
    routing_authority: Literal["deterministic_gate_with_jev_advisory"]
    # The canonical corpus has 100 cases, while smoke and replay slices may be
    # smaller.  The producer for each artifact owns its exact count check.
    questions: tuple[RoutingQuestion, ...] = Field(min_length=1, max_length=100)
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


class RoutingDecision(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    question_id: NonEmptyStr
    deterministic_route: ModelRoute
    jev_choice: ModelRoute | None = None
    final_route: ModelRoute
    jev_status: Literal["not_called", "advisory", "invalid", "missing"]
    downgrade_blocked: bool
    reason: NonEmptyStr
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


def deterministic_route(question: RoutingQuestion) -> ModelRoute:
    """Return the minimum safe model route from the typed question contract."""

    if question.expected_route is ModelRoute.HUMAN_REVIEW:
        return ModelRoute.HUMAN_REVIEW
    if any(item in CLOUD_REQUIRED_CAPABILITIES for item in question.capabilities):
        return ModelRoute.CLOUD
    if question.required_tools or question.cloud_reason:
        return ModelRoute.CLOUD
    if question.expected_route is not ModelRoute.LOCAL:
        return ModelRoute.HUMAN_REVIEW
    return ModelRoute.LOCAL


def build_jev_route_request(
    question: RoutingQuestion, *, model_id: str
) -> JevDecisionRequest:
    """Build a label-blinded JEV request; expected answers never enter it."""

    state: dict[str, Any] = {
        "question_id": question.question_id,
        "question": question.question,
        "category": question.category,
        "capabilities": [item.value for item in question.capabilities],
        "required_tools": list(question.required_tools),
        "answer_contract_kind": question.answer_contract.kind,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    return JevDecisionRequest(
        model=model_id,
        state=state,
        questions={
            "model_route": JevChoiceQuestion(
                type="choice",
                instructions=(
                    "Suggest whether this question should use local or cloud. "
                    "This is advisory only; deterministic Scout code owns the "
                    "final route and JEV cannot authorize hardware or safety actions."
                ),
                criteria={
                    "local": "The supplied facts have a short, deterministic standard answer and no external tool is needed.",
                    "cloud": "Web search, live data, or a Scout tool/evidence join is required.",
                    "human_review": "The request is ambiguous or authority-bearing and needs human review.",
                },
            )
        },
    )


def evaluate_jev_route(
    question: RoutingQuestion,
    response: JevDecisionResponse | None = None,
) -> RoutingDecision:
    """Apply JEV as an advisory escalation layer over the deterministic gate."""

    required = deterministic_route(question)
    choice: ModelRoute | None = None
    status: Literal["not_called", "advisory", "invalid", "missing"] = "not_called"
    if response is not None:
        answer = response.answers.get("model_route")
        if isinstance(answer, JevChoiceAnswer):
            try:
                choice = ModelRoute(answer.choice)
                status = "advisory"
            except ValueError:
                status = "invalid"
        else:
            status = "invalid"
    elif required is ModelRoute.LOCAL:
        status = "missing"

    if required is not ModelRoute.LOCAL:
        final = required
        blocked = choice is ModelRoute.LOCAL
        reason = "deterministic_contract_requires_external_evidence_or_review"
    elif choice is ModelRoute.CLOUD:
        final = ModelRoute.CLOUD
        blocked = False
        reason = "jev_advisory_escalation_for_local_eligible_question"
    elif choice is ModelRoute.HUMAN_REVIEW:
        final = ModelRoute.HUMAN_REVIEW
        blocked = False
        reason = "jev_advisory_requests_human_review"
    elif status in {"invalid", "missing"}:
        final = ModelRoute.CLOUD
        blocked = False
        reason = "jev_unavailable_or_invalid_fail_closed_to_cloud"
    else:
        final = ModelRoute.LOCAL
        blocked = False
        reason = "local_contract_and_jev_advice_are_compatible"

    return RoutingDecision(
        question_id=question.question_id,
        deterministic_route=required,
        jev_choice=choice,
        final_route=final,
        jev_status=status,
        downgrade_blocked=blocked,
        reason=reason,
    )


def load_routing_corpus(path: Path) -> RoutingCorpus:
    value = json.loads(path.read_text(encoding="utf-8"))
    return RoutingCorpus.model_validate(value)


def validate_routing_corpus(corpus: RoutingCorpus) -> list[str]:
    """Return deterministic contract violations for CI and CLI use."""

    errors: list[str] = []
    ids = [item.question_id for item in corpus.questions]
    if len(set(ids)) != len(ids):
        errors.append("question_id values must be unique")
    for item in corpus.questions:
        route = deterministic_route(item)
        has_cloud_capability = any(
            capability in CLOUD_REQUIRED_CAPABILITIES for capability in item.capabilities
        )
        if item.expected_route is ModelRoute.LOCAL:
            if route is not ModelRoute.LOCAL:
                errors.append(f"{item.question_id}: local case requires cloud evidence")
            if item.required_tools or item.cloud_reason:
                errors.append(f"{item.question_id}: local case declares cloud dependency")
            if item.answer_contract.kind not in {"exact", "choice", "structured"}:
                errors.append(f"{item.question_id}: local answer contract is not deterministic")
            if has_cloud_capability:
                errors.append(f"{item.question_id}: local case has cloud capability")
        elif item.expected_route is ModelRoute.CLOUD:
            if route is not ModelRoute.CLOUD:
                errors.append(f"{item.question_id}: cloud case lacks cloud capability")
            if not item.cloud_reason:
                errors.append(f"{item.question_id}: cloud case needs cloud_reason")
            if not item.required_tools and not has_cloud_capability:
                errors.append(f"{item.question_id}: cloud case needs a tool or cloud capability")
            if item.answer_contract.kind != "evidence_grounded":
                errors.append(f"{item.question_id}: cloud answer contract must be evidence_grounded")
    return errors
