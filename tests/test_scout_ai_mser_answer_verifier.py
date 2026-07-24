from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from scout.schemas.mser import (
    CompactDimension,
    CompactSignal,
    DecisionCriticality,
    DecisionIntent,
    DecisionType,
    DimensionCoverage,
    DimensionRequirement,
    GapKind,
    InformationNeed,
    MinimalSufficientContext,
    SufficiencyCertificate,
    SufficiencyStatus,
)
from scout.services.mser_answer_verifier import (
    AnswerVerificationDisposition,
    ClaimViolationCode,
    MSERAnswerClaim,
    MSERAnswerDraft,
    MSERAnswerVerifier,
    ReasoningDisposition,
)


NOW = datetime(2026, 7, 24, 2, 0, tzinfo=UTC)


def _signal(
    signal_id: str,
    dimension: CompactDimension,
    source_ref: str,
    *,
    value: str | float = "stable",
    valid_until: datetime | None = None,
    conflicts_with: tuple[str, ...] = (),
) -> CompactSignal:
    return CompactSignal(
        signal_id=signal_id,
        dimension=dimension,
        value=value,
        confidence=0.91,
        observed_at=NOW,
        valid_until=valid_until or NOW + timedelta(hours=3),
        source_refs=(source_ref,),
        evidence_ids=(f"raw-evidence:{signal_id}",),
        derivation=f"derived from raw artifact for {signal_id}",
        conflicts_with=conflicts_with,
    )


def _context(
    *,
    status: SufficiencyStatus = SufficiencyStatus.SUFFICIENT,
    signals: tuple[CompactSignal, ...] | None = None,
) -> MinimalSufficientContext:
    selected = signals or (
        _signal(
            "weather-stability",
            CompactDimension.WEATHER_STABILITY,
            "workspace://weather/stability.json",
        ),
        _signal(
            "forecast-confidence",
            CompactDimension.FORECAST_CONFIDENCE,
            "workspace://weather/forecast.json",
            value=0.82,
        ),
    )
    requirements = (
        DimensionRequirement(
            dimension=CompactDimension.WEATHER_STABILITY,
            reason="Current operating window.",
            minimum_confidence=0.6,
            max_age_seconds=10_800,
        ),
        DimensionRequirement(
            dimension=CompactDimension.FORECAST_CONFIDENCE,
            reason="Forecast uncertainty must remain explicit.",
            minimum_confidence=0.6,
            max_age_seconds=10_800,
        ),
    )
    coverage = tuple(
        DimensionCoverage(
            requirement=requirement,
            selected_signal_ids=tuple(
                signal.signal_id
                for signal in selected
                if signal.dimension == requirement.dimension
            ),
            status="covered",
            explanation="Fresh sourced compact signal.",
        )
        for requirement in requirements
    )
    source_refs = tuple(
        dict.fromkeys(
            source_ref for signal in selected for source_ref in signal.source_refs
        )
    )
    missing_dimensions: tuple[CompactDimension, ...] = ()
    information_needs: tuple[InformationNeed, ...] = ()
    if status == SufficiencyStatus.INSUFFICIENT:
        missing_dimensions = (CompactDimension.WEATHER_STABILITY,)
        information_needs = (
            InformationNeed(
                dimension=CompactDimension.WEATHER_STABILITY,
                gap_kind=GapKind.MISSING,
                reason="Weather stability is missing.",
                minimum_confidence=0.6,
                max_age_seconds=10_800,
            ),
        )
    contradictory_dimensions: tuple[CompactDimension, ...] = ()
    if status == SufficiencyStatus.CONTRADICTORY:
        contradictory_dimensions = (CompactDimension.WEATHER_STABILITY,)
    intent_confidence = 0.35 if status == SufficiencyStatus.AMBIGUOUS_DECISION else 0.94
    return MinimalSufficientContext(
        context_id="mser-test-context",
        intent=DecisionIntent(
            question="現在天氣是否穩定？",
            primary_type=DecisionType.WEATHER,
            confidence=intent_confidence,
            criticality=DecisionCriticality.HIGH,
            rationale="Weather decision terms were detected.",
        ),
        profile_id="scout.mser.profile.weather.v0",
        selected_signals=selected,
        discarded_dimensions=(),
        information_needs=information_needs,
        certificate=SufficiencyCertificate(
            status=status,
            required_dimension_count=2,
            covered_dimension_count=(
                2 if status == SufficiencyStatus.SUFFICIENT else 1
            ),
            coverage_ratio=(1.0 if status == SufficiencyStatus.SUFFICIENT else 0.5),
            coverage=coverage,
            missing_dimensions=missing_dimensions,
            contradictory_dimensions=contradictory_dimensions,
            counterfactual_required_dimensions=tuple(
                requirement.dimension for requirement in requirements
            ),
            source_refs=source_refs,
            explanation=f"Fixture certificate: {status.value}.",
        ),
    )


def _draft(
    *,
    signal_ids: tuple[str, ...] = ("weather-stability",),
    source_refs: tuple[str, ...] = ("workspace://weather/stability.json",),
) -> MSERAnswerDraft:
    return MSERAnswerDraft(
        answer_text="目前天氣狀態穩定。",
        claims=(
            MSERAnswerClaim(
                claim_id="claim-weather-stability",
                statement="目前天氣狀態穩定。",
                signal_ids=signal_ids,
                source_refs=source_refs,
            ),
        ),
    )


def test_answer_draft_rejects_text_not_represented_by_claims() -> None:
    with pytest.raises(ValueError, match="deterministic concatenation"):
        MSERAnswerDraft(
            answer_text="目前天氣狀態穩定。可以放心前進。",
            claims=(
                MSERAnswerClaim(
                    claim_id="claim-weather-stability",
                    statement="目前天氣狀態穩定。",
                    signal_ids=("weather-stability",),
                    source_refs=("workspace://weather/stability.json",),
                ),
            ),
        )


def test_model_payload_contains_only_compact_signals() -> None:
    envelope = MSERAnswerVerifier().prepare_reasoning(
        context=_context(),
        now=NOW,
    )

    assert envelope.disposition == ReasoningDisposition.READY_TO_REASON
    assert envelope.model_payload is not None
    assert envelope.candidate_only is True
    assert envelope.runtime_safety_truth is False
    payload = envelope.model_payload.model_dump(mode="json")
    serialized = envelope.model_payload.model_dump_json()
    assert payload["signals"][0]["signal_id"] == "weather-stability"
    assert payload["signals"][0]["source_refs"] == [
        "workspace://weather/stability.json"
    ]
    assert "evidence_ids" not in serialized
    assert "derivation" not in serialized
    assert "raw-evidence:" not in serialized
    assert "derived from raw artifact" not in serialized


@pytest.mark.parametrize(
    ("status", "expected_disposition"),
    (
        (SufficiencyStatus.INSUFFICIENT, ReasoningDisposition.EVIDENCE_GAP),
        (SufficiencyStatus.CONTRADICTORY, ReasoningDisposition.CONTRADICTION),
        (
            SufficiencyStatus.AMBIGUOUS_DECISION,
            ReasoningDisposition.CLARIFICATION_REQUIRED,
        ),
    ),
)
def test_only_sufficient_context_can_enter_normal_reasoning(
    status: SufficiencyStatus,
    expected_disposition: ReasoningDisposition,
) -> None:
    envelope = MSERAnswerVerifier().prepare_reasoning(
        context=_context(status=status),
        now=NOW,
    )

    assert envelope.disposition == expected_disposition
    assert envelope.model_payload is None
    assert envelope.message
    if status == SufficiencyStatus.INSUFFICIENT:
        assert envelope.information_needs
    if status == SufficiencyStatus.CONTRADICTORY:
        assert envelope.contradictory_dimensions
    if status == SufficiencyStatus.AMBIGUOUS_DECISION:
        assert envelope.clarification_question


def test_valid_claim_and_source_pass_verification() -> None:
    verification = MSERAnswerVerifier().verify(
        context=_context(),
        draft=_draft(),
        now=NOW,
    )

    assert verification.passed is True
    assert verification.disposition == AnswerVerificationDisposition.VERIFIED_CANDIDATE
    assert verification.verified_claim_ids == ("claim-weather-stability",)
    assert verification.violations == ()
    assert verification.candidate_only is True
    assert verification.runtime_safety_truth is False


@pytest.mark.parametrize(
    ("draft", "expected_code"),
    (
        (
            _draft(signal_ids=("invented-signal",)),
            ClaimViolationCode.UNKNOWN_SIGNAL_ID,
        ),
        (
            _draft(source_refs=("workspace://fabricated/source.json",)),
            ClaimViolationCode.INVALID_SOURCE_REF,
        ),
        (
            _draft(source_refs=("workspace://weather/forecast.json",)),
            ClaimViolationCode.SOURCE_NOT_LINKED_TO_SIGNAL,
        ),
    ),
)
def test_verifier_rejects_fabricated_or_misbound_references(
    draft: MSERAnswerDraft,
    expected_code: ClaimViolationCode,
) -> None:
    verification = MSERAnswerVerifier().verify(
        context=_context(),
        draft=draft,
        now=NOW,
    )

    assert verification.passed is False
    assert verification.disposition == AnswerVerificationDisposition.NEEDS_REPAIR
    assert expected_code in {item.code for item in verification.violations}


def test_stale_signal_blocks_reasoning_and_answer_verification() -> None:
    stale = _signal(
        "weather-stability",
        CompactDimension.WEATHER_STABILITY,
        "workspace://weather/stability.json",
        valid_until=NOW - timedelta(seconds=1),
    )
    context = _context(
        signals=(
            stale,
            _signal(
                "forecast-confidence",
                CompactDimension.FORECAST_CONFIDENCE,
                "workspace://weather/forecast.json",
                value=0.82,
            ),
        )
    )
    verifier = MSERAnswerVerifier()

    envelope = verifier.prepare_reasoning(context=context, now=NOW)
    verification = verifier.verify(context=context, draft=_draft(), now=NOW)

    assert envelope.disposition == ReasoningDisposition.EVIDENCE_GAP
    assert envelope.model_payload is None
    assert CompactDimension.WEATHER_STABILITY in envelope.stale_dimensions
    assert verification.passed is False
    assert (
        verification.disposition
        == AnswerVerificationDisposition.BLOCKED_BEFORE_REASONING
    )
    assert ClaimViolationCode.STALE_SIGNAL in {
        item.code for item in verification.violations
    }


def test_conflicting_signals_block_reasoning_and_answer_verification() -> None:
    first = _signal(
        "weather-stability",
        CompactDimension.WEATHER_STABILITY,
        "workspace://weather/stability.json",
        conflicts_with=("weather-stability-conflict",),
    )
    conflict = _signal(
        "weather-stability-conflict",
        CompactDimension.WEATHER_STABILITY,
        "workspace://weather/stability-conflict.json",
        value="unstable",
        conflicts_with=("weather-stability",),
    )
    context = _context(
        signals=(
            first,
            conflict,
            _signal(
                "forecast-confidence",
                CompactDimension.FORECAST_CONFIDENCE,
                "workspace://weather/forecast.json",
                value=0.82,
            ),
        )
    )
    verifier = MSERAnswerVerifier()

    envelope = verifier.prepare_reasoning(context=context, now=NOW)
    verification = verifier.verify(context=context, draft=_draft(), now=NOW)

    assert envelope.disposition == ReasoningDisposition.CONTRADICTION
    assert envelope.model_payload is None
    assert CompactDimension.WEATHER_STABILITY in envelope.contradictory_dimensions
    assert verification.passed is False
    assert ClaimViolationCode.CONTRADICTORY_SIGNAL in {
        item.code for item in verification.violations
    }


def test_non_sufficient_context_rejects_even_well_formed_claims() -> None:
    verification = MSERAnswerVerifier().verify(
        context=_context(status=SufficiencyStatus.INSUFFICIENT),
        draft=_draft(),
        now=NOW,
    )

    assert verification.passed is False
    assert (
        verification.disposition
        == AnswerVerificationDisposition.BLOCKED_BEFORE_REASONING
    )
    assert ClaimViolationCode.REASONING_NOT_ALLOWED in {
        item.code for item in verification.violations
    }


def test_forged_sufficient_certificate_is_rejected() -> None:
    context = _context()
    forged_coverage = context.certificate.coverage[0].model_copy(
        update={"selected_signal_ids": ("invented-signal",)}
    )
    forged_certificate = context.certificate.model_copy(
        update={
            "coverage": (
                forged_coverage,
                context.certificate.coverage[1],
            )
        }
    )
    forged_context = context.model_copy(update={"certificate": forged_certificate})
    verifier = MSERAnswerVerifier()

    envelope = verifier.prepare_reasoning(context=forged_context, now=NOW)
    verification = verifier.verify(
        context=forged_context,
        draft=_draft(),
        now=NOW,
    )

    assert envelope.disposition == ReasoningDisposition.EVIDENCE_GAP
    assert "certificate:coverage_unknown_signal:invented-signal" in (
        envelope.boundary_issues
    )
    assert ClaimViolationCode.CERTIFICATE_INCONSISTENT in {
        item.code for item in verification.violations
    }
