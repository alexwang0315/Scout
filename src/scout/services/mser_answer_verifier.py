"""MSER model-facing reasoning and deterministic answer verification boundary.

Raw evidence remains behind deterministic Scout services. A model receives only
compact signals that passed a current sufficiency check, and its answer remains
candidate-only until every structured claim cites certified signal provenance.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from scout.schemas.base import NonEmptyStr, SchemaModel
from scout.schemas.mser import (
    CompactDimension,
    CompactSignal,
    DecisionCriticality,
    DecisionType,
    GapKind,
    InformationNeed,
    MinimalSufficientContext,
    SignalAvailability,
    SufficiencyStatus,
)


class ReasoningDisposition(StrEnum):
    READY_TO_REASON = "ready_to_reason"
    EVIDENCE_GAP = "evidence_gap"
    CONTRADICTION = "contradiction"
    CLARIFICATION_REQUIRED = "clarification_required"


class AnswerVerificationDisposition(StrEnum):
    VERIFIED_CANDIDATE = "verified_candidate"
    NEEDS_REPAIR = "needs_repair"
    BLOCKED_BEFORE_REASONING = "blocked_before_reasoning"


class ClaimViolationCode(StrEnum):
    NO_CLAIMS = "no_claims"
    MISSING_SIGNAL_ID = "missing_signal_id"
    UNKNOWN_SIGNAL_ID = "unknown_signal_id"
    MISSING_SOURCE_REF = "missing_source_ref"
    INVALID_SOURCE_REF = "invalid_source_ref"
    SOURCE_NOT_LINKED_TO_SIGNAL = "source_not_linked_to_signal"
    STALE_SIGNAL = "stale_signal"
    UNAVAILABLE_SIGNAL = "unavailable_signal"
    CONTRADICTORY_SIGNAL = "contradictory_signal"
    CERTIFICATE_INCONSISTENT = "certificate_inconsistent"
    RAW_EVIDENCE_IN_COMPACT_VALUE = "raw_evidence_in_compact_value"
    REASONING_NOT_ALLOWED = "reasoning_not_allowed"


class ModelFacingCompactSignal(SchemaModel):
    """Bounded signal projection; deliberately excludes evidence IDs and derivation."""

    signal_id: NonEmptyStr
    dimension: CompactDimension
    value: bool | int | float | str | tuple[str, ...] | dict[str, Any]
    unit: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    risk_upper_bound: float | None = Field(default=None, ge=0.0, le=1.0)
    observed_at: datetime | None = None
    valid_until: datetime | None = None
    source_refs: tuple[NonEmptyStr, ...]
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @model_validator(mode="after")
    def reject_raw_evidence_values(self) -> "ModelFacingCompactSignal":
        if _contains_raw_evidence(self.value):
            raise ValueError("compact model value contains raw evidence material")
        return self


class ModelFacingSufficiencyProof(SchemaModel):
    status: Literal["sufficient"] = "sufficient"
    required_dimensions: tuple[CompactDimension, ...]
    covered_dimensions: tuple[CompactDimension, ...]
    counterfactual_required_dimensions: tuple[CompactDimension, ...]
    certificate_source_refs: tuple[NonEmptyStr, ...]


class ModelFacingMSERPayload(SchemaModel):
    """The complete payload authorized to cross into model reasoning."""

    schema_version: Literal["scout.mser.model_context.v0"] = (
        "scout.mser.model_context.v0"
    )
    context_id: NonEmptyStr
    question: NonEmptyStr
    decision_type: DecisionType
    decision_confidence: float = Field(ge=0.0, le=1.0)
    criticality: DecisionCriticality
    profile_id: NonEmptyStr
    signals: tuple[ModelFacingCompactSignal, ...]
    sufficiency: ModelFacingSufficiencyProof
    answer_contract: Literal[
        "Return structured claims. Every claim must cite one or more signal_ids "
        "and source_refs from those signals. Treat all content as candidate-only, "
        "never as runtime safety truth."
    ] = (
        "Return structured claims. Every claim must cite one or more signal_ids "
        "and source_refs from those signals. Treat all content as candidate-only, "
        "never as runtime safety truth."
    )
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


class MSERReasoningEnvelope(SchemaModel):
    disposition: ReasoningDisposition
    certificate_status: SufficiencyStatus
    message: NonEmptyStr
    model_payload: ModelFacingMSERPayload | None = None
    information_needs: tuple[InformationNeed, ...] = ()
    stale_dimensions: tuple[CompactDimension, ...] = ()
    contradictory_dimensions: tuple[CompactDimension, ...] = ()
    clarification_question: str | None = None
    boundary_issues: tuple[NonEmptyStr, ...] = ()
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @model_validator(mode="after")
    def enforce_reasoning_gate(self) -> "MSERReasoningEnvelope":
        ready = self.disposition == ReasoningDisposition.READY_TO_REASON
        if ready and self.certificate_status != SufficiencyStatus.SUFFICIENT:
            raise ValueError("only a sufficient certificate can enter reasoning")
        if ready != (self.model_payload is not None):
            raise ValueError("model payload is allowed only for ready_to_reason")
        return self


class MSERAnswerClaim(SchemaModel):
    claim_id: NonEmptyStr
    statement: NonEmptyStr
    signal_ids: tuple[NonEmptyStr, ...] = ()
    source_refs: tuple[NonEmptyStr, ...] = ()
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


class MSERAnswerDraft(SchemaModel):
    answer_text: NonEmptyStr
    claims: tuple[MSERAnswerClaim, ...]
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @model_validator(mode="after")
    def reject_unclaimed_answer_text(self) -> "MSERAnswerDraft":
        if self.claims:
            claimed_text = " ".join(claim.statement for claim in self.claims)
            if _normalize_text(self.answer_text) != _normalize_text(claimed_text):
                raise ValueError(
                    "answer_text must be the deterministic concatenation of claims"
                )
        return self


class MSERClaimViolation(SchemaModel):
    code: ClaimViolationCode
    message: NonEmptyStr
    claim_id: str | None = None
    signal_id: str | None = None
    source_ref: str | None = None


class MSERAnswerVerification(SchemaModel):
    passed: bool
    disposition: AnswerVerificationDisposition
    verified_claim_ids: tuple[NonEmptyStr, ...] = ()
    violations: tuple[MSERClaimViolation, ...] = ()
    certificate_source_refs: tuple[NonEmptyStr, ...] = ()
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @model_validator(mode="after")
    def validate_disposition(self) -> "MSERAnswerVerification":
        if self.passed:
            if self.disposition != AnswerVerificationDisposition.VERIFIED_CANDIDATE:
                raise ValueError("passed answer must be a verified candidate")
            if self.violations:
                raise ValueError("passed answer cannot contain violations")
        elif self.disposition == AnswerVerificationDisposition.VERIFIED_CANDIDATE:
            raise ValueError("failed answer cannot be a verified candidate")
        return self


class _ContextInspection(SchemaModel):
    stale_dimensions: tuple[CompactDimension, ...] = ()
    unavailable_dimensions: tuple[CompactDimension, ...] = ()
    contradictory_dimensions: tuple[CompactDimension, ...] = ()
    low_confidence_dimensions: tuple[CompactDimension, ...] = ()
    certificate_mismatch_signal_ids: tuple[NonEmptyStr, ...] = ()
    raw_value_signal_ids: tuple[NonEmptyStr, ...] = ()
    duplicate_signal_ids: tuple[NonEmptyStr, ...] = ()
    certificate_issues: tuple[NonEmptyStr, ...] = ()

    @property
    def has_gap(self) -> bool:
        return any(
            (
                self.stale_dimensions,
                self.unavailable_dimensions,
                self.low_confidence_dimensions,
                self.certificate_mismatch_signal_ids,
                self.raw_value_signal_ids,
                self.duplicate_signal_ids,
                self.certificate_issues,
            )
        )


class MSERAnswerVerifier:
    """Owns the deterministic boundary before and after model reasoning."""

    def prepare_reasoning(
        self,
        *,
        context: MinimalSufficientContext,
        now: datetime | None = None,
    ) -> MSERReasoningEnvelope:
        reference_time = _as_utc(now or datetime.now(UTC))
        status = context.certificate.status

        if status == SufficiencyStatus.AMBIGUOUS_DECISION:
            return MSERReasoningEnvelope(
                disposition=ReasoningDisposition.CLARIFICATION_REQUIRED,
                certificate_status=status,
                message=(
                    "The decision type is ambiguous; normal reasoning is blocked "
                    "until the user clarifies the intended decision."
                ),
                clarification_question=(
                    "你想判斷的是繼續、撤退、休息、導航，還是其他行動？"
                ),
                boundary_issues=("ambiguous_decision_type",),
            )
        if status == SufficiencyStatus.CONTRADICTORY:
            dimensions = _ordered_dimensions(
                context.certificate.contradictory_dimensions
            )
            return MSERReasoningEnvelope(
                disposition=ReasoningDisposition.CONTRADICTION,
                certificate_status=status,
                message=(
                    "Conflicting compact evidence must be resolved before normal "
                    "reasoning."
                ),
                contradictory_dimensions=dimensions,
                boundary_issues=tuple(
                    f"contradictory:{dimension.value}" for dimension in dimensions
                ),
            )
        if status != SufficiencyStatus.SUFFICIENT:
            return MSERReasoningEnvelope(
                disposition=ReasoningDisposition.EVIDENCE_GAP,
                certificate_status=status,
                message=_gap_message(context.information_needs),
                information_needs=context.information_needs,
                stale_dimensions=_ordered_dimensions(
                    context.certificate.stale_dimensions
                ),
                boundary_issues=tuple(
                    f"{need.gap_kind.value}:{need.dimension.value}"
                    for need in context.information_needs
                ),
            )

        inspection = _inspect_context(context=context, now=reference_time)
        if inspection.contradictory_dimensions:
            return MSERReasoningEnvelope(
                disposition=ReasoningDisposition.CONTRADICTION,
                certificate_status=status,
                message=(
                    "The certificate says sufficient, but selected compact signals "
                    "still contain unresolved conflicts."
                ),
                contradictory_dimensions=inspection.contradictory_dimensions,
                boundary_issues=tuple(
                    f"contradictory:{dimension.value}"
                    for dimension in inspection.contradictory_dimensions
                ),
            )
        if inspection.has_gap:
            needs = _inspection_needs(context=context, inspection=inspection)
            return MSERReasoningEnvelope(
                disposition=ReasoningDisposition.EVIDENCE_GAP,
                certificate_status=status,
                message=(
                    "The sufficiency certificate is no longer usable at the "
                    "reasoning boundary; refresh or repair the listed evidence."
                ),
                information_needs=needs,
                stale_dimensions=inspection.stale_dimensions,
                boundary_issues=_inspection_issue_strings(inspection),
            )

        payload = _build_model_payload(context)
        return MSERReasoningEnvelope(
            disposition=ReasoningDisposition.READY_TO_REASON,
            certificate_status=status,
            message=(
                "Current compact state passed sufficiency, freshness, conflict, "
                "and provenance checks and may enter candidate answer reasoning."
            ),
            model_payload=payload,
        )

    def verify(
        self,
        *,
        context: MinimalSufficientContext,
        draft: MSERAnswerDraft,
        now: datetime | None = None,
    ) -> MSERAnswerVerification:
        reference_time = _as_utc(now or datetime.now(UTC))
        envelope = self.prepare_reasoning(context=context, now=reference_time)
        certificate_refs = context.certificate.source_refs
        if envelope.disposition != ReasoningDisposition.READY_TO_REASON:
            violations = [
                MSERClaimViolation(
                    code=ClaimViolationCode.REASONING_NOT_ALLOWED,
                    message=(
                        f"Normal answer reasoning is blocked by "
                        f"{envelope.disposition.value}."
                    ),
                )
            ]
            violations.extend(_boundary_violations(envelope))
            return MSERAnswerVerification(
                passed=False,
                disposition=AnswerVerificationDisposition.BLOCKED_BEFORE_REASONING,
                violations=_dedupe_violations(violations),
                certificate_source_refs=certificate_refs,
            )

        signal_by_id = {signal.signal_id: signal for signal in context.selected_signals}
        valid_certificate_refs = set(certificate_refs)
        violations: list[MSERClaimViolation] = []
        verified_claim_ids: list[str] = []
        if not draft.claims:
            violations.append(
                MSERClaimViolation(
                    code=ClaimViolationCode.NO_CLAIMS,
                    message="The answer contains no structured claims to verify.",
                )
            )

        for claim in draft.claims:
            claim_violations = self._verify_claim(
                claim=claim,
                signal_by_id=signal_by_id,
                certificate_refs=valid_certificate_refs,
                context=context,
                now=reference_time,
            )
            violations.extend(claim_violations)
            if not claim_violations:
                verified_claim_ids.append(claim.claim_id)

        deduped = _dedupe_violations(violations)
        passed = not deduped and len(verified_claim_ids) == len(draft.claims)
        return MSERAnswerVerification(
            passed=passed,
            disposition=(
                AnswerVerificationDisposition.VERIFIED_CANDIDATE
                if passed
                else AnswerVerificationDisposition.NEEDS_REPAIR
            ),
            verified_claim_ids=tuple(verified_claim_ids),
            violations=deduped,
            certificate_source_refs=certificate_refs,
        )

    @staticmethod
    def _verify_claim(
        *,
        claim: MSERAnswerClaim,
        signal_by_id: dict[str, CompactSignal],
        certificate_refs: set[str],
        context: MinimalSufficientContext,
        now: datetime,
    ) -> tuple[MSERClaimViolation, ...]:
        violations: list[MSERClaimViolation] = []
        if not claim.signal_ids:
            violations.append(
                MSERClaimViolation(
                    code=ClaimViolationCode.MISSING_SIGNAL_ID,
                    claim_id=claim.claim_id,
                    message="Every claim must cite at least one compact signal_id.",
                )
            )
        if not claim.source_refs:
            violations.append(
                MSERClaimViolation(
                    code=ClaimViolationCode.MISSING_SOURCE_REF,
                    claim_id=claim.claim_id,
                    message="Every claim must cite at least one certified source_ref.",
                )
            )

        known_signals: list[CompactSignal] = []
        for signal_id in claim.signal_ids:
            signal = signal_by_id.get(signal_id)
            if signal is None:
                violations.append(
                    MSERClaimViolation(
                        code=ClaimViolationCode.UNKNOWN_SIGNAL_ID,
                        claim_id=claim.claim_id,
                        signal_id=signal_id,
                        message=f"Claim cites unknown signal_id {signal_id!r}.",
                    )
                )
                continue
            known_signals.append(signal)
            violations.extend(
                _signal_claim_violations(
                    claim_id=claim.claim_id,
                    signal=signal,
                    selected_signal_ids=set(signal_by_id),
                    context=context,
                    now=now,
                )
            )

        for source_ref in claim.source_refs:
            if source_ref not in certificate_refs:
                violations.append(
                    MSERClaimViolation(
                        code=ClaimViolationCode.INVALID_SOURCE_REF,
                        claim_id=claim.claim_id,
                        source_ref=source_ref,
                        message=(
                            f"Source ref {source_ref!r} is not in the sufficiency "
                            "certificate."
                        ),
                    )
                )
                continue
            if known_signals and not any(
                source_ref in signal.source_refs for signal in known_signals
            ):
                violations.append(
                    MSERClaimViolation(
                        code=ClaimViolationCode.SOURCE_NOT_LINKED_TO_SIGNAL,
                        claim_id=claim.claim_id,
                        source_ref=source_ref,
                        message=(
                            f"Source ref {source_ref!r} does not belong to any "
                            "signal cited by this claim."
                        ),
                    )
                )

        cited_refs = set(claim.source_refs)
        for signal in known_signals:
            if not cited_refs.intersection(signal.source_refs):
                violations.append(
                    MSERClaimViolation(
                        code=ClaimViolationCode.SOURCE_NOT_LINKED_TO_SIGNAL,
                        claim_id=claim.claim_id,
                        signal_id=signal.signal_id,
                        message=(
                            f"Claim cites signal {signal.signal_id!r} without one "
                            "of that signal's certified source refs."
                        ),
                    )
                )
        return _dedupe_violations(violations)


def _build_model_payload(
    context: MinimalSufficientContext,
) -> ModelFacingMSERPayload:
    required_dimensions = tuple(
        coverage.requirement.dimension for coverage in context.certificate.coverage
    )
    covered_dimensions = tuple(
        coverage.requirement.dimension
        for coverage in context.certificate.coverage
        if coverage.status == "covered"
    )
    signals = tuple(
        ModelFacingCompactSignal(
            signal_id=signal.signal_id,
            dimension=signal.dimension,
            value=signal.value,
            unit=signal.unit,
            confidence=signal.confidence,
            risk_upper_bound=signal.risk_upper_bound,
            observed_at=signal.observed_at,
            valid_until=signal.valid_until,
            source_refs=signal.source_refs,
        )
        for signal in context.selected_signals
        if signal.value is not None
    )
    return ModelFacingMSERPayload(
        context_id=context.context_id,
        question=context.intent.question,
        decision_type=context.intent.primary_type,
        decision_confidence=context.intent.confidence,
        criticality=context.intent.criticality,
        profile_id=context.profile_id,
        signals=signals,
        sufficiency=ModelFacingSufficiencyProof(
            required_dimensions=_ordered_dimensions(required_dimensions),
            covered_dimensions=_ordered_dimensions(covered_dimensions),
            counterfactual_required_dimensions=_ordered_dimensions(
                context.certificate.counterfactual_required_dimensions
            ),
            certificate_source_refs=context.certificate.source_refs,
        ),
    )


def _inspect_context(
    *,
    context: MinimalSufficientContext,
    now: datetime,
) -> _ContextInspection:
    certificate = context.certificate
    requirements = {
        coverage.requirement.dimension: coverage.requirement
        for coverage in certificate.coverage
    }
    certificate_refs = set(certificate.source_refs)
    signal_ids = [signal.signal_id for signal in context.selected_signals]
    duplicate_ids = {
        signal_id for signal_id in signal_ids if signal_ids.count(signal_id) > 1
    }
    selected_ids = set(signal_ids)
    signal_by_id = {signal.signal_id: signal for signal in context.selected_signals}
    stale: set[CompactDimension] = set(certificate.stale_dimensions)
    unavailable: set[CompactDimension] = set(certificate.missing_dimensions)
    low_confidence: set[CompactDimension] = set(certificate.low_confidence_dimensions)
    contradictory: set[CompactDimension] = set(certificate.contradictory_dimensions)
    certificate_mismatch: set[str] = set()
    raw_values: set[str] = set()
    certificate_issues = _certificate_issues(
        context=context,
        signal_by_id=signal_by_id,
    )

    if certificate.coverage_ratio < 1.0:
        unavailable.update(certificate.counterfactual_required_dimensions)

    for signal in context.selected_signals:
        requirement = requirements.get(signal.dimension)
        if signal.availability != SignalAvailability.AVAILABLE:
            unavailable.add(signal.dimension)
        elif _signal_is_stale(signal, requirement=requirement, now=now):
            stale.add(signal.dimension)
        if (
            requirement is not None
            and signal.confidence < requirement.minimum_confidence
        ):
            low_confidence.add(signal.dimension)
        if not set(signal.source_refs).issubset(certificate_refs):
            certificate_mismatch.add(signal.signal_id)
        if signal.conflicts_with:
            contradictory.add(signal.dimension)
            for conflict_id in signal.conflicts_with:
                conflict = next(
                    (
                        candidate
                        for candidate in context.selected_signals
                        if candidate.signal_id == conflict_id
                    ),
                    None,
                )
                if conflict is not None:
                    contradictory.add(conflict.dimension)
                elif conflict_id not in selected_ids:
                    contradictory.add(signal.dimension)
        if _contains_raw_evidence(signal.value):
            raw_values.add(signal.signal_id)

    return _ContextInspection(
        stale_dimensions=_ordered_dimensions(stale),
        unavailable_dimensions=_ordered_dimensions(unavailable),
        contradictory_dimensions=_ordered_dimensions(contradictory),
        low_confidence_dimensions=_ordered_dimensions(low_confidence),
        certificate_mismatch_signal_ids=tuple(sorted(certificate_mismatch)),
        raw_value_signal_ids=tuple(sorted(raw_values)),
        duplicate_signal_ids=tuple(sorted(duplicate_ids)),
        certificate_issues=certificate_issues,
    )


def _inspection_needs(
    *,
    context: MinimalSufficientContext,
    inspection: _ContextInspection,
) -> tuple[InformationNeed, ...]:
    requirements = {
        coverage.requirement.dimension: coverage.requirement
        for coverage in context.certificate.coverage
    }
    gaps: dict[CompactDimension, GapKind] = {}
    for dimension in inspection.unavailable_dimensions:
        gaps[dimension] = GapKind.MISSING
    for dimension in inspection.stale_dimensions:
        gaps[dimension] = GapKind.STALE
    for dimension in inspection.low_confidence_dimensions:
        gaps[dimension] = GapKind.LOW_CONFIDENCE
    needs: list[InformationNeed] = []
    for dimension, kind in sorted(gaps.items(), key=lambda item: item[0].value):
        requirement = requirements.get(dimension)
        needs.append(
            InformationNeed(
                dimension=dimension,
                gap_kind=kind,
                reason=(
                    f"{dimension.value} failed the reasoning-boundary "
                    f"{kind.value} check."
                ),
                minimum_confidence=(
                    requirement.minimum_confidence if requirement else 0.5
                ),
                max_age_seconds=(requirement.max_age_seconds if requirement else None),
            )
        )
    return tuple(needs)


def _boundary_violations(
    envelope: MSERReasoningEnvelope,
) -> tuple[MSERClaimViolation, ...]:
    violations: list[MSERClaimViolation] = []
    for dimension in envelope.stale_dimensions:
        violations.append(
            MSERClaimViolation(
                code=ClaimViolationCode.STALE_SIGNAL,
                message=f"Compact signal for {dimension.value} is stale.",
            )
        )
    for dimension in envelope.contradictory_dimensions:
        violations.append(
            MSERClaimViolation(
                code=ClaimViolationCode.CONTRADICTORY_SIGNAL,
                message=f"Compact signals for {dimension.value} conflict.",
            )
        )
    for issue in envelope.boundary_issues:
        if issue.startswith(("certificate_ref:", "duplicate_signal:", "certificate:")):
            violations.append(
                MSERClaimViolation(
                    code=ClaimViolationCode.CERTIFICATE_INCONSISTENT,
                    message=issue,
                )
            )
        elif issue.startswith("raw_value:"):
            violations.append(
                MSERClaimViolation(
                    code=ClaimViolationCode.RAW_EVIDENCE_IN_COMPACT_VALUE,
                    message=issue,
                )
            )
    return _dedupe_violations(violations)


def _signal_claim_violations(
    *,
    claim_id: str,
    signal: CompactSignal,
    selected_signal_ids: set[str],
    context: MinimalSufficientContext,
    now: datetime,
) -> tuple[MSERClaimViolation, ...]:
    violations: list[MSERClaimViolation] = []
    requirements = {
        coverage.requirement.dimension: coverage.requirement
        for coverage in context.certificate.coverage
    }
    if signal.availability != SignalAvailability.AVAILABLE:
        violations.append(
            MSERClaimViolation(
                code=ClaimViolationCode.UNAVAILABLE_SIGNAL,
                claim_id=claim_id,
                signal_id=signal.signal_id,
                message=f"Signal {signal.signal_id!r} is not available.",
            )
        )
    elif _signal_is_stale(
        signal,
        requirement=requirements.get(signal.dimension),
        now=now,
    ):
        violations.append(
            MSERClaimViolation(
                code=ClaimViolationCode.STALE_SIGNAL,
                claim_id=claim_id,
                signal_id=signal.signal_id,
                message=f"Signal {signal.signal_id!r} is stale.",
            )
        )
    if signal.conflicts_with:
        conflict_text = ", ".join(signal.conflicts_with)
        present = selected_signal_ids.intersection(signal.conflicts_with)
        detail = f"selected conflicts: {sorted(present)}" if present else conflict_text
        violations.append(
            MSERClaimViolation(
                code=ClaimViolationCode.CONTRADICTORY_SIGNAL,
                claim_id=claim_id,
                signal_id=signal.signal_id,
                message=f"Signal {signal.signal_id!r} has unresolved {detail}.",
            )
        )
    return tuple(violations)


def _signal_is_stale(
    signal: CompactSignal,
    *,
    requirement: Any,
    now: datetime,
) -> bool:
    if signal.availability == SignalAvailability.STALE:
        return True
    if signal.valid_until is not None and _as_utc(signal.valid_until) < now:
        return True
    max_age_seconds = requirement.max_age_seconds if requirement is not None else None
    if max_age_seconds is None:
        return False
    if signal.observed_at is None:
        return True
    return (now - _as_utc(signal.observed_at)).total_seconds() > max_age_seconds


_RAW_KEYS = {
    "raw",
    "raw_data",
    "raw_evidence",
    "raw_response",
    "response_body",
    "request_body",
    "evidence_ids",
    "evidence_records",
    "artifact_content",
    "binary_blob",
    "samples",
}


def _contains_raw_evidence(value: Any) -> bool:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return True
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in _RAW_KEYS or normalized.startswith("raw_"):
                return True
            if _contains_raw_evidence(item):
                return True
        return False
    if isinstance(value, (list, tuple, set)):
        return any(_contains_raw_evidence(item) for item in value)
    return False


def _inspection_issue_strings(
    inspection: _ContextInspection,
) -> tuple[str, ...]:
    return (
        *(f"stale:{item.value}" for item in inspection.stale_dimensions),
        *(f"unavailable:{item.value}" for item in inspection.unavailable_dimensions),
        *(
            f"low_confidence:{item.value}"
            for item in inspection.low_confidence_dimensions
        ),
        *(
            f"certificate_ref:{signal_id}"
            for signal_id in inspection.certificate_mismatch_signal_ids
        ),
        *(f"raw_value:{signal_id}" for signal_id in inspection.raw_value_signal_ids),
        *(
            f"duplicate_signal:{signal_id}"
            for signal_id in inspection.duplicate_signal_ids
        ),
        *(f"certificate:{issue}" for issue in inspection.certificate_issues),
    )


def _gap_message(needs: tuple[InformationNeed, ...]) -> str:
    if not needs:
        return (
            "MSER is insufficient; the certificate must be repaired before "
            "normal reasoning."
        )
    rendered = ", ".join(
        f"{need.dimension.value} ({need.gap_kind.value})" for need in needs
    )
    return f"MSER evidence gaps block normal reasoning: {rendered}."


def _certificate_issues(
    *,
    context: MinimalSufficientContext,
    signal_by_id: dict[str, CompactSignal],
) -> tuple[str, ...]:
    certificate = context.certificate
    issues: list[str] = []
    if certificate.required_dimension_count != len(certificate.coverage):
        issues.append("required_dimension_count_mismatch")
    covered = [item for item in certificate.coverage if item.status == "covered"]
    if certificate.covered_dimension_count != len(covered):
        issues.append("covered_dimension_count_mismatch")
    expected_ratio = (
        len(covered) / len(certificate.coverage) if certificate.coverage else 1.0
    )
    if abs(certificate.coverage_ratio - expected_ratio) > 1e-9:
        issues.append("coverage_ratio_mismatch")
    for item in certificate.coverage:
        dimension = item.requirement.dimension
        if item.requirement.mandatory and item.status != "covered":
            issues.append(f"mandatory_not_covered:{dimension.value}")
        if item.status == "covered" and not item.selected_signal_ids:
            issues.append(f"covered_without_signal:{dimension.value}")
        for signal_id in item.selected_signal_ids:
            signal = signal_by_id.get(signal_id)
            if signal is None:
                issues.append(f"coverage_unknown_signal:{signal_id}")
            elif signal.dimension != dimension:
                issues.append(
                    f"coverage_dimension_mismatch:{signal_id}:{dimension.value}"
                )
    signal_refs = {
        source_ref
        for signal in context.selected_signals
        for source_ref in signal.source_refs
    }
    certificate_refs = set(certificate.source_refs)
    if signal_refs != certificate_refs:
        issues.append("certificate_source_set_mismatch")
    return tuple(dict.fromkeys(issues))


def _ordered_dimensions(
    dimensions: Any,
) -> tuple[CompactDimension, ...]:
    return tuple(sorted(set(dimensions), key=lambda item: item.value))


def _normalize_text(value: str) -> str:
    return " ".join(value.split())


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _dedupe_violations(
    violations: list[MSERClaimViolation] | tuple[MSERClaimViolation, ...],
) -> tuple[MSERClaimViolation, ...]:
    result: list[MSERClaimViolation] = []
    seen: set[tuple[str, str | None, str | None, str | None]] = set()
    for violation in violations:
        key = (
            violation.code.value,
            violation.claim_id,
            violation.signal_id,
            violation.source_ref,
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(violation)
    return tuple(result)


__all__ = [
    "AnswerVerificationDisposition",
    "ClaimViolationCode",
    "MSERAnswerClaim",
    "MSERAnswerDraft",
    "MSERAnswerVerification",
    "MSERAnswerVerifier",
    "MSERClaimViolation",
    "MSERReasoningEnvelope",
    "ModelFacingCompactSignal",
    "ModelFacingMSERPayload",
    "ModelFacingSufficiencyProof",
    "ReasoningDisposition",
]
