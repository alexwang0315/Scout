"""Deterministic runtime compiler for the candidate Jev decision plane.

Jev may provide bounded routing and recovery suggestions, but this module is
the Scout-owned compiler between those suggestions and runtime effects.  The
MSER certificate, authority class, Praison information-need requirement, and
MAX readiness gate remain deterministic inputs.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field

from scout.nextgen.jev_decision_service import (
    JevAuthorityClass,
    JevEscalationDisposition,
    JevMSERCertificate,
    JevParsedSignals,
    JevQuestionContract,
    JevToolFamily,
)
from scout.nextgen.max_runtime_preflight import MaxRuntimeReadinessDisposition
from scout.schemas.base import NonEmptyStr, SchemaModel
from scout.schemas.mser import (
    InformationNeed,
    SufficiencyStatus,
)
from scout.services.mser_pipeline import MSERPipelineState


class JevRuntimePath(StrEnum):
    DETERMINISTIC_FAST_LANE = "deterministic_fast_lane"
    DETERMINISTIC_EVIDENCE = "deterministic_evidence"
    PRAISON_INFORMATION_NEED = "praison_information_need"
    MAX_SYNTHESIS_RECOVERY = "max_synthesis_recovery"
    HUMAN_REVIEW = "human_review"


class JevRuntimeInput(SchemaModel):
    """Inputs that are safe to expose to the runtime policy compiler."""

    contract: JevQuestionContract
    mser_certificate: JevMSERCertificate
    information_needs: tuple[InformationNeed, ...] = ()
    synthesis_failed: bool = False
    max_readiness: MaxRuntimeReadinessDisposition | None = None
    jev: JevParsedSignals | None = None
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


class JevRuntimePlan(SchemaModel):
    """Compiled route and escalation plan; it contains no execution arguments."""

    path: JevRuntimePath
    disposition: JevEscalationDisposition
    selected_tool_family: JevToolFamily
    mser_gate_passed: bool
    information_need_count: int = Field(ge=0)
    praison_allowed: bool
    max_allowed: bool
    human_review_required: bool
    jev_signal_accepted: bool
    over_escalation: bool
    reason_codes: tuple[NonEmptyStr, ...]
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


def runtime_input_from_mser(
    *,
    state: MSERPipelineState,
    contract: JevQuestionContract,
    synthesis_failed: bool = False,
    max_readiness: MaxRuntimeReadinessDisposition | None = None,
    jev: JevParsedSignals | None = None,
) -> JevRuntimeInput:
    """Project the real MSER pipeline state into the Jev runtime boundary."""

    certificate = state.packet.compact_context.certificate
    status = {
        SufficiencyStatus.SUFFICIENT: "sufficient",
        SufficiencyStatus.INSUFFICIENT: "insufficient",
        SufficiencyStatus.CONTRADICTORY: "contradictory",
        SufficiencyStatus.AMBIGUOUS_DECISION: "ambiguous",
    }[certificate.status]
    return JevRuntimeInput(
        contract=contract,
        mser_certificate=JevMSERCertificate(
            status=status,
            information_need=bool(state.packet.compact_context.information_needs),
            synthesis_failed=synthesis_failed,
        ),
        information_needs=state.packet.compact_context.information_needs,
        synthesis_failed=synthesis_failed,
        max_readiness=max_readiness,
        jev=jev,
    )


def compile_jev_runtime_plan(runtime_input: JevRuntimeInput) -> JevRuntimePlan:
    """Compile Jev suggestions through MSER and authority policy."""

    contract = runtime_input.contract
    certificate = runtime_input.mser_certificate
    jev = runtime_input.jev
    selected_tool = contract.allowed_tool_families[0]
    reasons: list[str] = ["jev_candidate_only", "deterministic_contract_authoritative"]
    if jev is None:
        jev_signal_accepted = False
        reasons.append("jev_signal_unavailable")
    else:
        jev_signal_accepted = (
            jev.question_class is contract.question_class
            and jev.artifact_family is contract.artifact_family
            and jev.tool_family in contract.allowed_tool_families
        )
        reasons.append(
            "jev_signal_accepted" if jev_signal_accepted else "jev_signal_repaired"
        )

    low_risk = contract.authority_class is JevAuthorityClass.LOW_RISK_CANDIDATE
    status = certificate.status.value
    mser_ready = status == "sufficient"
    information_need_count = len(runtime_input.information_needs)
    over_escalation = bool(
        low_risk
        and mser_ready
        and not runtime_input.synthesis_failed
        and jev is not None
        and (
            jev.evidence_sufficient is False
            or jev.semantic_contradiction is True
            or jev.escalation
            in {
                JevEscalationDisposition.COLLECT_MORE_EVIDENCE,
                JevEscalationDisposition.HUMAN_REVIEW,
            }
        )
    )
    if over_escalation:
        reasons.append("jev_over_escalation_recorded_non_authoritative")

    if not low_risk:
        reasons.append("authority_or_safety_requires_human_review")
        return JevRuntimePlan(
            path=JevRuntimePath.HUMAN_REVIEW,
            disposition=JevEscalationDisposition.HUMAN_REVIEW,
            selected_tool_family=JevToolFamily.HUMAN_REVIEW,
            mser_gate_passed=mser_ready,
            information_need_count=information_need_count,
            praison_allowed=False,
            max_allowed=False,
            human_review_required=True,
            jev_signal_accepted=jev_signal_accepted,
            over_escalation=False,
            reason_codes=tuple(reasons),
        )

    if status == "ambiguous":
        reasons.append("mser_ambiguous_requires_clarification")
        return JevRuntimePlan(
            path=JevRuntimePath.HUMAN_REVIEW,
            disposition=JevEscalationDisposition.HUMAN_REVIEW,
            selected_tool_family=JevToolFamily.HUMAN_REVIEW,
            mser_gate_passed=False,
            information_need_count=information_need_count,
            praison_allowed=False,
            max_allowed=False,
            human_review_required=True,
            jev_signal_accepted=jev_signal_accepted,
            over_escalation=over_escalation,
            reason_codes=tuple(reasons),
        )

    if not mser_ready:
        praison_allowed = bool(
            information_need_count
            and JevToolFamily.PRAISONAI_INFORMATION_NEED
            in contract.allowed_tool_families
        )
        reasons.append("mser_hard_gate_not_sufficient")
        if praison_allowed:
            reasons.append("praison_requires_mser_information_need")
            path = JevRuntimePath.PRAISON_INFORMATION_NEED
            tool = JevToolFamily.PRAISONAI_INFORMATION_NEED
        else:
            reasons.append("no_praison_without_information_need")
            path = JevRuntimePath.DETERMINISTIC_EVIDENCE
            tool = selected_tool
        return JevRuntimePlan(
            path=path,
            disposition=JevEscalationDisposition.COLLECT_MORE_EVIDENCE,
            selected_tool_family=tool,
            mser_gate_passed=False,
            information_need_count=information_need_count,
            praison_allowed=praison_allowed,
            max_allowed=False,
            human_review_required=False,
            jev_signal_accepted=jev_signal_accepted,
            over_escalation=over_escalation,
            reason_codes=tuple(reasons),
        )

    if runtime_input.synthesis_failed:
        max_allowed = (
            runtime_input.max_readiness
            is MaxRuntimeReadinessDisposition.READY_FOR_BEHAVIOR_QUALIFICATION
            and JevToolFamily.MAX_REASONING in contract.allowed_tool_families
        )
        if max_allowed:
            reasons.extend(("mser_sufficient", "max_preflight_ready"))
            return JevRuntimePlan(
                path=JevRuntimePath.MAX_SYNTHESIS_RECOVERY,
                disposition=JevEscalationDisposition.USE_STRONGER_MODEL,
                selected_tool_family=JevToolFamily.MAX_REASONING,
                mser_gate_passed=True,
                information_need_count=information_need_count,
                praison_allowed=False,
                max_allowed=True,
                human_review_required=False,
                jev_signal_accepted=jev_signal_accepted,
                over_escalation=False,
                reason_codes=tuple(reasons),
            )
        reasons.append("max_blocked_until_preflight_ready")
        return JevRuntimePlan(
            path=JevRuntimePath.HUMAN_REVIEW,
            disposition=JevEscalationDisposition.HUMAN_REVIEW,
            selected_tool_family=JevToolFamily.HUMAN_REVIEW,
            mser_gate_passed=True,
            information_need_count=information_need_count,
            praison_allowed=False,
            max_allowed=False,
            human_review_required=True,
            jev_signal_accepted=jev_signal_accepted,
            over_escalation=False,
            reason_codes=tuple(reasons),
        )

    reasons.append("mser_sufficient_auto_candidate")
    return JevRuntimePlan(
        path=JevRuntimePath.DETERMINISTIC_FAST_LANE
        if contract.question_class.value in {"static_fact", "aggregate"}
        else JevRuntimePath.DETERMINISTIC_EVIDENCE,
        disposition=JevEscalationDisposition.AUTO,
        selected_tool_family=selected_tool,
        mser_gate_passed=True,
        information_need_count=information_need_count,
        praison_allowed=False,
        max_allowed=False,
        human_review_required=False,
        jev_signal_accepted=jev_signal_accepted,
        over_escalation=over_escalation,
        reason_codes=tuple(reasons),
    )


__all__ = [
    "JevRuntimeInput",
    "JevRuntimePath",
    "JevRuntimePlan",
    "compile_jev_runtime_plan",
    "runtime_input_from_mser",
]
