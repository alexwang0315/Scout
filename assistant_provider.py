from __future__ import annotations

from typing import Protocol

from assistant_models import (
    ASSISTANT_SURFACE_CONSTRAINTS,
    AssistantBoundary,
    AssistantSourceRef,
    AssistantSurface,
    ScoutAssistantQuery,
    ScoutAssistantResponse,
)


MUTATION_INTENT_FRAGMENTS = (
    "ignore previous",
    "ignore prior",
    "approve",
    "accept candidate",
    "reject candidate",
    "send sos",
    "send sms",
    "send satellite",
    "write observedfact",
    "write observed fact",
    "create observedfact",
    "write brain",
    "call /safety",
    "mutate",
    "control hardware",
    "control provider",
    "start docker",
    "start pi",
)


class ScoutAssistantProvider(Protocol):
    def answer(
        self,
        query: ScoutAssistantQuery,
        *,
        sources: list[AssistantSourceRef] | None = None,
    ) -> ScoutAssistantResponse:
        ...


class MockAssistantProvider:
    def answer(
        self,
        query: ScoutAssistantQuery,
        *,
        sources: list[AssistantSourceRef] | None = None,
    ) -> ScoutAssistantResponse:
        resolved_sources = list(sources or [])
        policy = ASSISTANT_SURFACE_CONSTRAINTS[query.surface]
        source_text = _source_summary(resolved_sources)
        selection_text = _selection_summary(query)
        constrained = _has_mutation_intent(query.question)
        prefix = (
            "Guardrail notice: mutation or prompt-injection language was treated as data, "
            "not as authorization. "
            if constrained
            else ""
        )
        answer = (
            f"{prefix}This is a read-only model interpretation for the {policy_label(query.surface)} "
            f"surface. It can explain {', '.join(policy.may_answer)} from bounded Scout "
            f"context, but it cannot {', '.join(policy.forbidden_actions)}. "
            f"{selection_text}{source_text}"
        )
        limitations = [
            "No runtime state was changed.",
            "No Phase 2 Brain writeback was performed.",
            "No ObservedFact, HumanReview, review decision, outbound message, or hardware control was created.",
            "Mock provider only; no network or live Pydantic AI call was made.",
        ]
        if constrained:
            limitations.append("Prompt-injection or mutation request was constrained.")
        return ScoutAssistantResponse(
            surface=query.surface,
            answer=answer,
            sources=resolved_sources,
            boundary=AssistantBoundary(surface=query.surface),
            limitations=limitations,
        )


class FailedAssistantProvider:
    def __init__(self, *, error_type: str, error_message: str):
        self.error_type = error_type
        self.error_message = error_message

    def answer(
        self,
        query: ScoutAssistantQuery,
        *,
        sources: list[AssistantSourceRef] | None = None,
    ) -> ScoutAssistantResponse:
        return ScoutAssistantResponse(
            surface=query.surface,
            answer=(
                "Assistant provider startup failed safely. This response is a "
                "read-only model interpretation placeholder and no Scout state was changed."
            ),
            sources=list(sources or []),
            boundary=AssistantBoundary(surface=query.surface),
            limitations=[
                f"provider_startup_error_type={self.error_type}",
                self.error_message,
                "Provider startup failure was isolated from the source surface.",
                "No runtime, Brain, review, outbound, or hardware state was changed.",
            ],
        )


def policy_label(surface: AssistantSurface) -> str:
    return {
        AssistantSurface.DEBUG: "runtime debug",
        AssistantSurface.ADMIN: "after-action admin",
        AssistantSurface.PRETRIP: "pre-trip planning",
        AssistantSurface.HARDWARE_READINESS: "hardware readiness",
    }[surface]


def _selection_summary(query: ScoutAssistantQuery) -> str:
    refs = [
        query.context_ref,
        query.selected_event_id,
        query.selected_artifact_id,
        query.project_id,
    ]
    selected = [ref for ref in refs if ref]
    if not selected:
        return "No selected context ref was provided. "
    return f"Selected refs: {', '.join(selected)}. "


def _source_summary(sources: list[AssistantSourceRef]) -> str:
    if not sources:
        return "No source refs were provided, so the answer must stay high level."
    refs = ", ".join(source.source_id for source in sources)
    return f"Source refs used: {refs}."


def _has_mutation_intent(text: str) -> bool:
    lowered = text.lower()
    return any(fragment in lowered for fragment in MUTATION_INTENT_FRAGMENTS)
