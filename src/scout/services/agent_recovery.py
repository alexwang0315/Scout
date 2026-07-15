"""Deterministic recovery-stage orchestration for Scout agent attempts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Any

from scout.schemas.agent_runtime import (
    AgentAttemptState,
    AgentAttemptStatus,
    AgentContinuationCheckpoint,
    AgentKnownIssue,
    AgentRecoveryRootCause,
    AgentRecoveryStage,
    AgentReviewArtifact,
    AgentRunBudget,
    AgentRunLedger,
    QuestionClass,
)
from scout.services.agent_budget_policy import AgentBudgetPolicy


_NEXT_RECOVERY_STAGE: dict[AgentRecoveryStage, AgentRecoveryStage] = {
    AgentRecoveryStage.INITIAL: AgentRecoveryStage.TOOL_REPAIR,
    AgentRecoveryStage.TOOL_REPAIR: AgentRecoveryStage.MODEL_SWITCH,
    AgentRecoveryStage.MODEL_SWITCH: AgentRecoveryStage.CODEX_REVIEW,
    AgentRecoveryStage.CODEX_REVIEW: AgentRecoveryStage.KNOWN_ISSUE,
}


class AgentRecoveryOrchestrator:
    """Issue fresh budgets and enforce Scout's fixed failure escalation order."""

    def start_attempt(
        self,
        *,
        question: str,
        question_class: QuestionClass | str | None,
        model_id: str | None,
        budget: AgentRunBudget | None = None,
    ) -> AgentAttemptState:
        resolved_budget = budget or AgentBudgetPolicy.for_query(
            question_class=question_class
        )
        return self._attempt(
            question=question,
            budget=resolved_budget,
            model_id=model_id,
        )

    def continue_attempt(
        self,
        *,
        prior_attempt: AgentAttemptState,
        checkpoint: AgentContinuationCheckpoint,
    ) -> AgentAttemptState:
        if checkpoint.attempt_id != prior_attempt.attempt_id:
            raise ValueError("continuation checkpoint does not match prior attempt")
        budget = AgentBudgetPolicy.for_recovery(
            prior_budget=prior_attempt.budget,
            recovery_stage=AgentRecoveryStage.CONTINUATION,
        )
        return self._attempt(
            question=prior_attempt.question,
            budget=budget,
            model_id=prior_attempt.model_id,
            continuation_of=checkpoint.checkpoint_id,
            parent_recovery_stage=self._effective_stage(prior_attempt),
        )

    def advance_attempt(
        self,
        *,
        prior_attempt: AgentAttemptState,
        recovery_stage: AgentRecoveryStage,
        model_id: str | None,
    ) -> AgentAttemptState:
        current_stage = self._effective_stage(prior_attempt)
        expected = _NEXT_RECOVERY_STAGE.get(current_stage)
        if recovery_stage != expected:
            expected_value = expected.value if expected is not None else "none"
            raise ValueError(
                f"next recovery stage after {current_stage.value} must be "
                f"{expected_value}"
            )
        budget = AgentBudgetPolicy.for_recovery(
            prior_budget=prior_attempt.budget,
            recovery_stage=recovery_stage,
        )
        return self._attempt(
            question=prior_attempt.question,
            budget=budget,
            model_id=model_id,
            continuation_of=prior_attempt.attempt_id,
        )

    def checkpoint_external_limit(
        self,
        *,
        attempt: AgentAttemptState,
        reason: str,
        evidence: Sequence[dict[str, Any]],
        source_refs: Sequence[str],
        call_trace: Sequence[dict[str, Any]],
        state: dict[str, Any],
    ) -> AgentContinuationCheckpoint:
        payload = {
            "attempt_id": attempt.attempt_id,
            "reason": reason,
            "source_refs": list(source_refs),
            "state": state,
        }
        return AgentContinuationCheckpoint(
            checkpoint_id=_stable_id("checkpoint", payload),
            attempt_id=attempt.attempt_id,
            question=attempt.question,
            recovery_stage=attempt.recovery_stage,
            attempt_index=attempt.attempt_index,
            reason=reason,
            evidence=[dict(item) for item in evidence],
            source_refs=list(dict.fromkeys(source_refs)),
            call_trace=[dict(item) for item in call_trace],
            state=dict(state),
        )

    def build_review_artifact(
        self,
        *,
        attempt: AgentAttemptState,
        expected_answer_or_success_condition: str,
        evidence: Sequence[dict[str, Any]],
        source_refs: Sequence[str],
        call_trace: Sequence[dict[str, Any]],
        tool_outputs: Sequence[dict[str, Any]],
        models_used: Sequence[str],
        repairs_applied: Sequence[str],
        actual_failure_symptom: str,
        candidate_answer: str | None,
    ) -> AgentReviewArtifact:
        if attempt.recovery_stage != AgentRecoveryStage.CODEX_REVIEW:
            raise ValueError("review artifact requires the codex_review stage")
        payload = {
            "attempt_id": attempt.attempt_id,
            "question": attempt.question,
            "symptom": actual_failure_symptom,
        }
        return AgentReviewArtifact(
            review_id=_stable_id("review", payload),
            original_question=attempt.question,
            expected_answer_or_success_condition=(
                expected_answer_or_success_condition
            ),
            available_evidence=[dict(item) for item in evidence],
            source_references=list(dict.fromkeys(source_refs)),
            complete_call_trace=[dict(item) for item in call_trace],
            tool_outputs=[dict(item) for item in tool_outputs],
            models_used=list(dict.fromkeys(models_used)),
            repairs_applied=list(dict.fromkeys(repairs_applied)),
            actual_failure_symptom=actual_failure_symptom,
            candidate_answer=candidate_answer,
        )

    def build_known_issue(
        self,
        *,
        review: AgentReviewArtifact,
        root_cause: AgentRecoveryRootCause,
        reproduction: str,
        last_evidence: Sequence[dict[str, Any]],
        tool_repairs_tried: Sequence[str],
        models_tried: Sequence[str],
        current_blocker: str,
        explicit_unblock_condition: str,
    ) -> AgentKnownIssue:
        payload = {
            "review_id": review.review_id,
            "question": review.original_question,
            "blocker": current_blocker,
        }
        return AgentKnownIssue(
            stable_id=_stable_id("known-issue", payload),
            original_question=review.original_question,
            root_cause=root_cause,
            reproduction=reproduction,
            last_evidence=[dict(item) for item in last_evidence],
            tool_repairs_tried=list(dict.fromkeys(tool_repairs_tried)),
            models_tried=list(dict.fromkeys(models_tried)),
            current_blocker=current_blocker,
            explicit_unblock_condition=explicit_unblock_condition,
        )

    @staticmethod
    def _effective_stage(attempt: AgentAttemptState) -> AgentRecoveryStage:
        if attempt.recovery_stage == AgentRecoveryStage.CONTINUATION:
            return attempt.parent_recovery_stage or AgentRecoveryStage.INITIAL
        return attempt.recovery_stage

    @staticmethod
    def _attempt(
        *,
        question: str,
        budget: AgentRunBudget,
        model_id: str | None,
        continuation_of: str | None = None,
        parent_recovery_stage: AgentRecoveryStage | None = None,
    ) -> AgentAttemptState:
        payload = {
            "question": question,
            "stage": budget.recovery_stage.value,
            "attempt_index": budget.attempt_index,
            "continuation_of": continuation_of,
        }
        ledger = AgentRunLedger(budget=budget)
        return AgentAttemptState(
            attempt_id=_stable_id("attempt", payload),
            question=question,
            question_class=budget.question_class,
            recovery_stage=budget.recovery_stage,
            attempt_index=budget.attempt_index,
            budget=budget,
            ledger=ledger,
            status=AgentAttemptStatus.RUNNING,
            model_id=model_id,
            continuation_of=continuation_of,
            parent_recovery_stage=parent_recovery_stage,
        )


def _stable_id(kind: str, payload: dict[str, Any]) -> str:
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:20]
    return f"scout-{kind}-{digest}"


__all__ = ["AgentRecoveryOrchestrator"]
