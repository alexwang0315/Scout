from __future__ import annotations

import pytest

from scout.schemas.agent_runtime import (
    AgentAttemptStatus,
    AgentRecoveryRootCause,
    AgentRecoveryStage,
    QuestionClass,
)
from scout.services.agent_recovery import AgentRecoveryOrchestrator


def test_recovery_ladder_rejects_out_of_order_model_switch() -> None:
    orchestrator = AgentRecoveryOrchestrator()
    initial = orchestrator.start_attempt(
        question="本次路徑的 15K 在哪裡？",
        question_class=QuestionClass.CROSS_ARTIFACT_JOIN,
        model_id="model-a",
    )

    with pytest.raises(ValueError, match="tool_repair"):
        orchestrator.advance_attempt(
            prior_attempt=initial,
            recovery_stage=AgentRecoveryStage.MODEL_SWITCH,
            model_id="model-b",
        )


def test_review_artifact_and_known_issue_preserve_required_failure_evidence() -> None:
    orchestrator = AgentRecoveryOrchestrator()
    initial = orchestrator.start_attempt(
        question="本次路徑的 15K 在哪裡？",
        question_class=QuestionClass.CROSS_ARTIFACT_JOIN,
        model_id="model-a",
    )
    repaired = orchestrator.advance_attempt(
        prior_attempt=initial.model_copy(
            update={"status": AgentAttemptStatus.STAGE_COMPLETE}
        ),
        recovery_stage=AgentRecoveryStage.TOOL_REPAIR,
        model_id="model-a",
    )
    switched = orchestrator.advance_attempt(
        prior_attempt=repaired.model_copy(
            update={"status": AgentAttemptStatus.STAGE_COMPLETE}
        ),
        recovery_stage=AgentRecoveryStage.MODEL_SWITCH,
        model_id="model-b",
    )
    review_attempt = orchestrator.advance_attempt(
        prior_attempt=switched.model_copy(
            update={"status": AgentAttemptStatus.STAGE_COMPLETE}
        ),
        recovery_stage=AgentRecoveryStage.CODEX_REVIEW,
        model_id="codex",
    )
    review = orchestrator.build_review_artifact(
        attempt=review_attempt,
        expected_answer_or_success_condition="Locate 15K and nearest CP with citations.",
        evidence=[{"evidence_id": "ev-15k"}],
        source_refs=["outputs/route/mileage.json"],
        call_trace=[{"operation": "filter"}, {"operation": "nearest"}],
        tool_outputs=[{"status": "success"}],
        models_used=["model-a", "model-b"],
        repairs_applied=["fixed mileage artifact adapter"],
        actual_failure_symptom="nearest CP citation still missing",
        candidate_answer="15K is near CP 12.",
    )
    known_issue = orchestrator.build_known_issue(
        review=review,
        root_cause=AgentRecoveryRootCause.MISSING_EVIDENCE,
        reproduction="Run replay case workspace-20260713-032.",
        last_evidence=[{"evidence_id": "ev-15k"}],
        tool_repairs_tried=["fixed mileage artifact adapter"],
        models_tried=["model-a", "model-b", "codex"],
        current_blocker="checkpoint artifact has no stable join key",
        explicit_unblock_condition="regenerate checkpoints with route distance",
    )

    assert review.recovery_stage == AgentRecoveryStage.CODEX_REVIEW
    assert review.complete_call_trace[-1]["operation"] == "nearest"
    assert review.candidate_answer == "15K is near CP 12."
    assert known_issue.status == "KNOWN_ISSUE"
    assert known_issue.root_cause == AgentRecoveryRootCause.MISSING_EVIDENCE
    assert known_issue.stable_id.startswith("scout-known-issue-")
    assert known_issue.explicit_unblock_condition
