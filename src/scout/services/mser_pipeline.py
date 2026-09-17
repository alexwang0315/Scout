"""Executable MSER bridge for Scout scenario, total-info, tools, and answers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from scout.schemas.base import SchemaModel
from scout.schemas.mser import (
    CompactDimension,
    CompactSignal,
    DecisionCriticality,
    DecisionType,
    DimensionRequirement,
    EnvironmentalRepresentation,
    MSERAnswerMode,
    MSERDecisionPacket,
    MSERGapEvidenceReceipt,
    MSERTaskContract,
    SignalAvailability,
)
from scout.services.mser_answer_verifier import (
    AnswerVerificationDisposition,
    ClaimViolationCode,
    MSERAnswerClaim,
    MSERAnswerDraft,
    MSERAnswerVerification,
    MSERAnswerVerifier,
    MSERClaimViolation,
    MSERReasoningEnvelope,
    ReasoningDisposition,
)
from scout.services.mser_engine import DECISION_PROFILES, MSEREngine
from scout.services.mser_projectors import (
    project_scenario_context,
    project_total_info,
)
from scout.services.mser_runtime_adapter import (
    BoundedReprojectionPayload,
    MSERRuntimeAdapter,
)
from scout.services.mser_state_store import MSERStateStore


class MSERExecutionMode(StrEnum):
    OFF = "off"
    SHADOW = "shadow"
    ENFORCE = "enforce"


def mser_enforcement_errors(
    *,
    mode: MSERExecutionMode | str,
    state: "MSERPipelineState | None",
    verification: MSERAnswerVerification | Mapping[str, Any] | None,
    pipeline_error: str | None = None,
) -> tuple[str, ...]:
    """Return fail-closed errors for an enforce-mode MSER answer stage."""

    resolved_mode = (
        mode if isinstance(mode, MSERExecutionMode) else MSERExecutionMode(mode)
    )
    if resolved_mode != MSERExecutionMode.ENFORCE:
        return ()
    if pipeline_error:
        return ("mser_pipeline_error",)
    if state is None:
        return ("mser_state_unavailable",)
    disposition = state.reasoning.disposition.value
    if disposition not in {"ready_to_reason", "ready_to_explain_gap"}:
        return (f"mser_reasoning_blocked:{disposition}",)
    if verification is None:
        return ("mser_answer_verification_missing",)
    if isinstance(verification, MSERAnswerVerification):
        passed = verification.passed
        violations = verification.violations
        violation_codes = tuple(item.code.value for item in violations)
    else:
        passed = bool(verification.get("passed", False))
        violation_codes = tuple(
            str(item.get("code") or "unknown")
            for item in verification.get("violations") or ()
            if isinstance(item, Mapping)
        )
    if passed:
        return ()
    return tuple(
        dict.fromkeys(
            f"mser_answer_verification_failed:{code}"
            for code in violation_codes or ("unknown",)
        )
    )


class MSERPipelineState(SchemaModel):
    """One immutable decision stage before or after deterministic tool execution."""

    environment: EnvironmentalRepresentation
    packet: MSERDecisionPacket
    reasoning: MSERReasoningEnvelope
    state_snapshot_id: str
    tool_signal_bindings: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    gap_evidence_receipts: tuple[MSERGapEvidenceReceipt, ...] = ()


class MSERPipelineTrace(SchemaModel):
    """Auditable MSER trajectory embedded into a Scout answer/eval record."""

    schema_version: str = "scout.mser.pipeline_trace.v0"
    mode: MSERExecutionMode
    initial: MSERPipelineState
    final: MSERPipelineState | None = None
    reprojection_payloads: tuple[BoundedReprojectionPayload, ...] = ()
    selected_tool_ids: tuple[str, ...] = ()
    legacy_selected_tool_ids: tuple[str, ...] = ()
    candidate_only: bool = True
    runtime_safety_truth: bool = False


_FORCE_DECISION_HINTS: Mapping[str, DecisionType] = {
    "EXP": DecisionType.HISTORY,
    "RPF": DecisionType.READINESS_PACE,
    "RTE": DecisionType.ROUTE_PLANNING,
    "WTH": DecisionType.WEATHER,
    "NAV": DecisionType.NAVIGATION,
}

_RISK_DIMENSIONS = frozenset(
    {
        CompactDimension.CURRENT_HAZARD,
        CompactDimension.EXPOSURE_RISK,
        CompactDimension.SLIP_RISK,
        CompactDimension.ROCKFALL_RISK,
        CompactDimension.MEDICAL_URGENCY,
    }
)


def decision_hint_for_force(force_code: str | None) -> DecisionType | None:
    """Return a broad eval-family hint without overriding question modifiers."""

    return _FORCE_DECISION_HINTS.get(str(force_code or "").strip().upper())


def _task_requirement(
    dimension: CompactDimension,
    reason: str,
    *,
    confidence: float,
    max_age_seconds: int,
) -> DimensionRequirement:
    return DimensionRequirement(
        dimension=dimension,
        reason=reason,
        minimum_confidence=confidence,
        max_age_seconds=max_age_seconds,
    )


def task_contract_for_question(
    question: str,
    *,
    decision_hint: DecisionType | None = None,
    answer_mode_hint: str | None = None,
    safety_relevant_hint: bool = False,
) -> MSERTaskContract:
    """Compile a deterministic task scope; model text cannot select this mode."""

    text = " ".join(question.casefold().split())
    hint = str(answer_mode_hint or "").strip().casefold()
    asks_for_gap = any(
        term in text
        for term in (
            "哪一項天氣資料缺失",
            "哪項天氣資料缺失",
            "缺少哪",
            "缺失哪",
            "什麼證據不足",
            "哪些證據不足",
            "what evidence is missing",
            "which evidence is missing",
        )
    )
    if asks_for_gap:
        decision_type = decision_hint or DecisionType.GENERAL
        return MSERTaskContract(
            task_id=f"evidence-gap.{decision_type.value}.v0",
            answer_mode=MSERAnswerMode.EVIDENCE_GAP_EXPLANATION,
            requirements=DECISION_PROFILES[decision_type].requirements,
        )
    if any(
        term in text
        for term in (
            "現在在路線的哪一個位置",
            "目前在路線的哪一個位置",
            "where am i on the route",
            "current route position",
        )
    ):
        return MSERTaskContract(
            task_id="factual.current-position.v0",
            answer_mode=MSERAnswerMode.FACTUAL_LOOKUP,
            requirements=(
                _task_requirement(
                    CompactDimension.CURRENT_POSITION,
                    "A current-position answer needs the route-bound position fact.",
                    confidence=0.65,
                    max_age_seconds=300,
                ),
                _task_requirement(
                    CompactDimension.GPS_CONFIDENCE,
                    "Position facts must retain current GNSS uncertainty.",
                    confidence=0.65,
                    max_age_seconds=300,
                ),
            ),
        )
    if any(
        term in text
        for term in (
            "速度比預估慢多少",
            "速度比預計慢多少",
            "配速比預估慢多少",
            "pace variance",
            "pace delta",
        )
    ):
        return MSERTaskContract(
            task_id="factual.pace-variance.v0",
            answer_mode=MSERAnswerMode.FACTUAL_LOOKUP,
            requirements=(
                _task_requirement(
                    CompactDimension.PACE_VARIANCE,
                    "A pace comparison needs the measured plan-versus-actual delta.",
                    confidence=0.55,
                    max_age_seconds=900,
                ),
            ),
        )
    next_checkpoint_mentioned = any(
        term in text
        for term in (
            "下一個 cp",
            "下一個檢查點",
            "next checkpoint",
        )
    )
    asks_for_checkpoint_fact = any(
        term in text
        for term in (
            "是什麼",
            "是哪一個",
            "在哪",
            "距離",
            "多遠",
            "還要多久",
            "which checkpoint",
            "where is",
            "how far",
        )
    )
    if next_checkpoint_mentioned and asks_for_checkpoint_fact:
        return MSERTaskContract(
            task_id="factual.next-checkpoint.v0",
            answer_mode=MSERAnswerMode.FACTUAL_LOOKUP,
            requirements=(
                _task_requirement(
                    CompactDimension.NEXT_CHECKPOINT,
                    "The answer needs a sourced next-checkpoint identity and distance.",
                    confidence=0.6,
                    max_age_seconds=300,
                ),
                _task_requirement(
                    CompactDimension.ROUTE_PROGRESS,
                    "Checkpoint ordering must be bound to current route progress.",
                    confidence=0.6,
                    max_age_seconds=300,
                ),
            ),
        )
    if hint == "decision" or (hint == "compound" and safety_relevant_hint):
        return MSERTaskContract(
            task_id=f"safety-decision.{(decision_hint or DecisionType.GENERAL).value}.v0",
            answer_mode=MSERAnswerMode.SAFETY_DECISION,
            safety_relevant=True,
        )
    return MSERTaskContract(
        task_id=(
            f"candidate-analysis.{(decision_hint or DecisionType.GENERAL).value}.v0"
        ),
        answer_mode=MSERAnswerMode.CANDIDATE_ANALYSIS,
    )


def merge_environment_representations(
    *representations: EnvironmentalRepresentation,
    generated_at: datetime | None = None,
) -> EnvironmentalRepresentation:
    """Preserve every compact signal while keeping one deterministic envelope."""

    if not representations:
        raise ValueError("at least one environmental representation is required")
    primary = representations[0]
    extra_signals: list[CompactSignal] = list(primary.additional_signals)
    seen_ids = {signal.signal_id for signal in primary.all_signals()}
    for representation in representations[1:]:
        for signal in representation.all_signals():
            if signal.signal_id not in seen_ids:
                extra_signals.append(signal)
                seen_ids.add(signal.signal_id)
    refs = tuple(
        dict.fromkeys(
            ref
            for representation in representations
            for ref in representation.source_refs
        )
    )
    digest_input = "|".join(item.representation_id for item in representations)
    digest = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()[:16]
    return primary.model_copy(
        update={
            "representation_id": f"mser.merged.{digest}",
            "generated_at": _as_utc(generated_at or primary.generated_at),
            "additional_signals": tuple(extra_signals),
            "source_refs": refs,
        }
    )


class MSERPipeline:
    """Run projection, sufficiency, minimal planning, and answer verification."""

    def __init__(
        self,
        *,
        engine: MSEREngine | None = None,
        runtime_adapter: MSERRuntimeAdapter | None = None,
        answer_verifier: MSERAnswerVerifier | None = None,
        state_store: MSERStateStore | None = None,
    ) -> None:
        self.engine = engine or MSEREngine()
        self.runtime_adapter = runtime_adapter or MSERRuntimeAdapter()
        self.answer_verifier = answer_verifier or MSERAnswerVerifier()
        self.state_store = state_store or MSERStateStore()

    def prepare(
        self,
        *,
        question: str,
        scenario: object | None = None,
        total_info: object | None = None,
        decision_hint: DecisionType | None = None,
        task_contract: MSERTaskContract | None = None,
        now: datetime | None = None,
    ) -> MSERPipelineState:
        reference_time = _as_utc(now or datetime.now(UTC))
        representations: list[EnvironmentalRepresentation] = []
        if scenario is not None:
            representations.append(
                project_scenario_context(scenario, now=reference_time)
            )
        if total_info is not None:
            representations.append(project_total_info(total_info, now=reference_time))
        if not representations:
            raise ValueError("scenario or total_info is required for MSER projection")
        environment = merge_environment_representations(
            *representations,
            generated_at=reference_time,
        )
        snapshot = self.state_store.publish(
            environment,
            reason="project scenario and total-info into MSER",
            expected_version=self.state_store.version,
        )
        packet = self.engine.prepare(
            question=question,
            environment=environment,
            capabilities=self.runtime_adapter.capabilities,
            decision_hint=decision_hint,
            task_contract=task_contract,
            now=reference_time,
        )
        if (
            task_contract is not None
            and packet.intent.criticality == DecisionCriticality.CRITICAL
            and task_contract.answer_mode != MSERAnswerMode.SAFETY_DECISION
        ):
            raise ValueError(
                "critical decisions cannot use a non-safety MSER answer mode"
            )
        reasoning = self.answer_verifier.prepare_reasoning(
            context=packet.compact_context,
            answer_mode=(
                task_contract.answer_mode
                if task_contract is not None
                else MSERAnswerMode.SAFETY_DECISION
            ),
            now=reference_time,
        )
        return MSERPipelineState(
            environment=environment,
            packet=packet,
            reasoning=reasoning,
            state_snapshot_id=snapshot.snapshot_id,
        )

    def reproject_tools(
        self,
        *,
        previous: MSERPipelineState,
        tool_results: Sequence[Mapping[str, Any]],
        now: datetime | None = None,
    ) -> tuple[MSERPipelineState, tuple[BoundedReprojectionPayload, ...]]:
        reference_time = _as_utc(now or datetime.now(UTC))
        payloads: list[BoundedReprojectionPayload] = []
        projected_signals: list[CompactSignal] = []
        bindings: dict[str, tuple[str, ...]] = {}
        gap_evidence_receipts: list[MSERGapEvidenceReceipt] = []
        for result in tool_results:
            tool_id = str(result.get("tool_id") or "").strip()
            if not tool_id:
                continue
            payload = self.runtime_adapter.to_reprojection_payload(
                dict(result),
                tool_id=tool_id,
            )
            payload = _bind_server_context_source(
                payload=payload,
                environment=previous.environment,
            )
            payloads.append(payload)
            capability = self.runtime_adapter.capability_for(tool_id)
            tool_signals = tuple(
                _tool_signal(
                    payload=payload,
                    dimension=dimension,
                    expected_confidence=capability.expected_confidence,
                    now=reference_time,
                )
                for dimension in capability.produces_dimensions
            )
            projected_signals.extend(tool_signals)
            bindings[capability.tool_id] = tuple(
                signal.signal_id for signal in tool_signals
            )
            gap_receipt = _gap_evidence_receipt(
                payload=payload,
                signals=tool_signals,
                now=reference_time,
            )
            if gap_receipt is not None:
                gap_evidence_receipts.append(gap_receipt)

        tool_environment = EnvironmentalRepresentation(
            representation_id=_tool_environment_id(payloads),
            generated_at=reference_time,
            additional_signals=tuple(projected_signals),
            source_refs=tuple(
                dict.fromkeys(
                    ref for payload in payloads for ref in payload.source_refs
                )
            ),
        )
        environment = merge_environment_representations(
            previous.environment,
            tool_environment,
            generated_at=reference_time,
        )
        snapshot = self.state_store.publish(
            environment,
            reason="reproject bounded deterministic tool evidence into MSER",
            expected_version=self.state_store.version,
        )
        packet = self.engine.prepare(
            question=previous.packet.intent.question,
            environment=environment,
            capabilities=self.runtime_adapter.capabilities,
            decision_hint=previous.packet.intent.primary_type,
            task_contract=previous.packet.task_contract,
            now=reference_time,
        )
        reasoning = self.answer_verifier.prepare_reasoning(
            context=packet.compact_context,
            answer_mode=(
                packet.task_contract.answer_mode
                if packet.task_contract is not None
                else MSERAnswerMode.SAFETY_DECISION
            ),
            gap_evidence_receipts=tuple(gap_evidence_receipts),
            now=reference_time,
        )
        return (
            MSERPipelineState(
                environment=environment,
                packet=packet,
                reasoning=reasoning,
                state_snapshot_id=snapshot.snapshot_id,
                tool_signal_bindings=bindings,
                gap_evidence_receipts=tuple(gap_evidence_receipts),
            ),
            tuple(payloads),
        )

    def verify_model_output(
        self,
        *,
        state: MSERPipelineState,
        output: Mapping[str, Any] | None,
        now: datetime | None = None,
    ) -> MSERAnswerVerification:
        if not output or not str(output.get("answer") or "").strip():
            return _failed_answer_verification(
                ClaimViolationCode.NO_CLAIMS,
                "The model returned no answer text for MSER verification.",
                source_refs=state.packet.compact_context.certificate.source_refs,
            )
        selected_by_id = {
            signal.signal_id: signal
            for signal in state.packet.compact_context.selected_signals
        }
        cited_refs = tuple(
            str(item).strip()
            for item in output.get("source_refs") or ()
            if str(item).strip()
        )
        signal_ids: list[str] = []
        gap_mode = (
            state.reasoning.disposition
            == ReasoningDisposition.READY_TO_EXPLAIN_GAP
        )
        gap_receipt_ids: list[str] = []
        for ref in cited_refs:
            signal_ids.extend(state.tool_signal_bindings.get(ref, ()))
            signal_ids.extend(
                signal.signal_id
                for signal in selected_by_id.values()
                if ref in signal.source_refs
            )
            if gap_mode:
                gap_receipt_ids.extend(
                    receipt.receipt_id
                    for receipt in state.gap_evidence_receipts
                    if ref
                    in {
                        receipt.receipt_id,
                        receipt.tool_id,
                        *receipt.source_refs,
                    }
                )
        selected_signal_ids = tuple(
            signal_id
            for signal_id in dict.fromkeys(signal_ids)
            if signal_id in selected_by_id
        )
        selected_gap_receipt_ids = tuple(dict.fromkeys(gap_receipt_ids))
        if not selected_signal_ids and not selected_gap_receipt_ids:
            return _failed_answer_verification(
                ClaimViolationCode.UNKNOWN_SIGNAL_ID,
                (
                    "No cited model source resolves to a selected MSER signal "
                    "or typed gap evidence receipt."
                ),
                source_refs=state.packet.compact_context.certificate.source_refs,
            )
        receipt_by_id = {
            receipt.receipt_id: receipt for receipt in state.gap_evidence_receipts
        }
        resolved_source_refs = tuple(
            dict.fromkeys(
                (
                    *(
                        ref
                        for signal_id in selected_signal_ids
                        for ref in selected_by_id[signal_id].source_refs
                        if ref
                        in state.packet.compact_context.certificate.source_refs
                    ),
                    *(
                        ref
                        for receipt_id in selected_gap_receipt_ids
                        for ref in receipt_by_id[receipt_id].source_refs
                    ),
                )
            )
        )
        if not resolved_source_refs:
            return _failed_answer_verification(
                ClaimViolationCode.INVALID_SOURCE_REF,
                "Cited MSER signals have no source in the sufficiency certificate.",
                source_refs=state.packet.compact_context.certificate.source_refs,
            )
        answer = str(output["answer"]).strip()
        answer_mode = (
            state.packet.task_contract.answer_mode
            if state.packet.task_contract is not None
            else MSERAnswerMode.SAFETY_DECISION
        )
        draft = MSERAnswerDraft(
            answer_text=answer,
            answer_mode=answer_mode,
            decision=(
                str(output.get("decision")).strip()
                if output.get("decision") is not None
                else None
            ),
            evidence_gaps=tuple(
                str(item).strip()
                for item in output.get("evidence_gaps") or ()
                if str(item).strip()
            ),
            claims=(
                MSERAnswerClaim(
                    claim_id="model-answer",
                    statement=answer,
                    signal_ids=selected_signal_ids,
                    gap_receipt_ids=selected_gap_receipt_ids,
                    source_refs=resolved_source_refs,
                ),
            ),
        )
        return self.answer_verifier.verify(
            context=state.packet.compact_context,
            draft=draft,
            answer_mode=answer_mode,
            gap_evidence_receipts=state.gap_evidence_receipts,
            now=_as_utc(now or datetime.now(UTC)),
        )


def compact_pipeline_context(state: MSERPipelineState) -> dict[str, Any]:
    """Return only model-safe compact state, proof obligations, and tool plan."""

    context = state.packet.compact_context
    return {
        "schema_version": "scout.mser.compact_prompt_context.v0",
        "decision": {
            "type": state.packet.intent.primary_type.value,
            "modifiers": [item.value for item in state.packet.intent.alternative_types],
            "confidence": state.packet.intent.confidence,
            "criticality": state.packet.intent.criticality.value,
        },
        "task": {
            "task_id": (
                state.packet.task_contract.task_id
                if state.packet.task_contract is not None
                else "legacy-full-profile"
            ),
            "answer_mode": (
                state.packet.task_contract.answer_mode.value
                if state.packet.task_contract is not None
                else MSERAnswerMode.SAFETY_DECISION.value
            ),
            "safety_relevant": (
                state.packet.task_contract.safety_relevant
                if state.packet.task_contract is not None
                else True
            ),
        },
        "sufficiency": {
            "status": context.certificate.status.value,
            "coverage_ratio": context.certificate.coverage_ratio,
            "required_dimensions": [
                item.requirement.dimension.value
                for item in context.certificate.coverage
            ],
            "covered_dimensions": [
                item.requirement.dimension.value
                for item in context.certificate.coverage
                if item.status == "covered"
            ],
            "information_needs": [
                {
                    "dimension": need.dimension.value,
                    "gap_kind": need.gap_kind.value,
                    "reason": need.reason,
                }
                for need in context.information_needs
            ],
            "source_refs": list(context.certificate.source_refs),
        },
        "gap_evidence_receipts": [
            receipt.model_dump(mode="json")
            for receipt in state.gap_evidence_receipts
        ],
        "signals": [
            {
                "signal_id": signal.signal_id,
                "dimension": signal.dimension.value,
                "value": signal.value,
                "unit": signal.unit,
                "availability": signal.availability.value,
                "confidence": signal.confidence,
                "risk_upper_bound": signal.risk_upper_bound,
                "observed_at": (
                    signal.observed_at.isoformat() if signal.observed_at else None
                ),
                "valid_until": (
                    signal.valid_until.isoformat() if signal.valid_until else None
                ),
                "source_refs": list(signal.source_refs),
            }
            for signal in context.selected_signals
        ],
        "tool_plan": {
            "selected_tool_ids": [
                item.tool_id for item in state.packet.tool_plan.selected_tools
            ],
            "coverage_complete": state.packet.tool_plan.coverage_complete,
            "uncovered_dimensions": [
                item.value for item in state.packet.tool_plan.uncovered_dimensions
            ],
            "max_tool_calls": state.packet.tool_plan.max_tool_calls,
        },
        "reasoning_disposition": state.reasoning.disposition.value,
        "reasoning_allowed_decisions": (
            list(state.reasoning.gap_payload.allowed_decisions)
            if state.reasoning.gap_payload is not None
            else []
        ),
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _bind_server_context_source(
    *,
    payload: BoundedReprojectionPayload,
    environment: EnvironmentalRepresentation,
) -> BoundedReprojectionPayload:
    """Bind a deterministic decision to an already-certified scenario input."""

    if payload.source_refs:
        return payload
    decision = str(payload.key_values.get("decision") or "").strip().upper()
    scenario = payload.key_values.get("scenario_context")
    if not decision or not isinstance(scenario, Mapping):
        return payload
    scenario_id = str(scenario.get("scenario_id") or "").strip()
    if not scenario_id:
        return payload
    source_ref = f"scenario://{scenario_id}"
    if source_ref not in environment.source_refs:
        return payload
    invalid_quality = payload.quality.casefold() in {
        "invalid",
        "withheld",
        "unavailable",
    }
    return payload.model_copy(
        update={
            "source_refs": (source_ref,),
            "missing_fields": tuple(
                field for field in payload.missing_fields if field != "source_refs"
            ),
            "reprojection_ready": not invalid_quality,
        }
    )


def _gap_evidence_receipt(
    *,
    payload: BoundedReprojectionPayload,
    signals: tuple[CompactSignal, ...],
    now: datetime,
) -> MSERGapEvidenceReceipt | None:
    gap_signals = tuple(
        signal
        for signal in signals
        if signal.availability != SignalAvailability.AVAILABLE
    )
    if not gap_signals or not payload.source_refs:
        return None
    availabilities = {signal.availability for signal in gap_signals}
    availability = (
        next(iter(availabilities))
        if len(availabilities) == 1
        else SignalAvailability.INVALID
    )
    observed_at = max(
        (signal.observed_at for signal in gap_signals if signal.observed_at),
        default=now,
    )
    identity = json.dumps(
        {
            "tool_id": payload.tool_id,
            "signal_ids": [signal.signal_id for signal in gap_signals],
            "availability": availability.value,
            "missing_fields": payload.missing_fields,
            "source_refs": payload.source_refs,
        },
        ensure_ascii=True,
        sort_keys=True,
    )
    return MSERGapEvidenceReceipt(
        receipt_id=(
            "mser.gap."
            f"{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]}"
        ),
        tool_id=payload.tool_id,
        dimensions=tuple(signal.dimension for signal in gap_signals),
        signal_ids=tuple(signal.signal_id for signal in gap_signals),
        availability=availability,
        missing_fields=payload.missing_fields,
        freshness=payload.freshness,
        quality=payload.quality,
        observed_at=observed_at,
        source_refs=payload.source_refs,
    )


def _tool_signal(
    *,
    payload: BoundedReprojectionPayload,
    dimension: CompactDimension,
    expected_confidence: float,
    now: datetime,
) -> CompactSignal:
    answerability = str(payload.key_values.get("answerability") or "").casefold()
    status = str(payload.key_values.get("status") or "").casefold()
    freshness = payload.freshness.casefold()
    missing_answer = bool(payload.missing_fields) or any(
        marker in answerability
        for marker in (
            "missing",
            "no_match",
            "no_matching",
            "not_available",
            "unavailable",
            "unknown",
        )
    )
    if not payload.reprojection_ready or status not in {"completed", "available", "ok"}:
        availability = SignalAvailability.INVALID
    elif missing_answer:
        availability = SignalAvailability.MISSING
    elif "stale" in freshness or "expired" in freshness:
        availability = SignalAvailability.STALE
    else:
        availability = SignalAvailability.AVAILABLE

    observed_at = _tool_observed_at(payload) or now
    confidence = expected_confidence
    if freshness in {"", "unknown"}:
        confidence = min(confidence, 0.7)
    if payload.missing_fields:
        confidence = min(confidence, 0.49)
    if availability != SignalAvailability.AVAILABLE:
        confidence = 0.0
    source_refs = payload.source_refs
    value: dict[str, Any] | None = None
    if availability == SignalAvailability.AVAILABLE:
        value = {
            "tool_id": payload.tool_id,
            "summary": payload.claim_summary[:480],
            "quality": payload.quality,
            "freshness": payload.freshness,
            "result_count": payload.result_count,
        }
        decision = str(payload.key_values.get("decision") or "").strip().upper()
        if decision in {
            "GO",
            "CONDITIONAL_GO",
            "CHANGE_PLAN",
            "DELAY",
            "NO_GO",
            "ESCALATE",
            "GUIDED_ONLY",
        }:
            value["decision"] = decision
    risk_upper_bound = (
        _risk_upper_bound(payload.key_values) if dimension in _RISK_DIMENSIONS else None
    )
    identity = json.dumps(
        [
            payload.tool_id,
            dimension.value,
            source_refs,
            payload.claim_summary,
        ],
        ensure_ascii=True,
        sort_keys=True,
    )
    return CompactSignal(
        signal_id=(
            f"mser.tool.{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]}"
        ),
        dimension=dimension,
        value=value,
        availability=availability,
        confidence=confidence,
        risk_upper_bound=risk_upper_bound,
        observed_at=observed_at,
        source_refs=source_refs,
        evidence_ids=tuple(record.evidence_id for record in payload.evidence_records),
        derivation=(
            f"reviewed capability projection from {payload.tool_id}; "
            f"quality={payload.quality}; freshness={payload.freshness}"
        ),
    )


def _tool_observed_at(payload: BoundedReprojectionPayload) -> datetime | None:
    values: list[object] = []
    for key in ("observed_at", "generated_at", "updated_at", "fetched_at"):
        values.append(payload.key_values.get(key))
    for nested_key in ("provided_fields", "scenario_context", "resource_state"):
        nested = payload.key_values.get(nested_key)
        if isinstance(nested, Mapping):
            values.extend(
                nested.get(key)
                for key in ("observed_at", "generated_at", "updated_at", "fetched_at")
            )
    values.extend(record.observed_at for record in payload.evidence_records)
    parsed = tuple(item for value in values if (item := _parse_datetime(value)))
    return max(parsed) if parsed else None


def _risk_upper_bound(payload: Mapping[str, Any]) -> float | None:
    candidates: list[float] = []

    def visit(value: object, *, depth: int = 0) -> None:
        if depth > 5:
            return
        if isinstance(value, Mapping):
            for key, item in value.items():
                normalized = str(key).casefold()
                if normalized in {
                    "max_score",
                    "risk_score",
                    "score",
                    "risk_upper_bound",
                }:
                    try:
                        number = float(item)
                    except (TypeError, ValueError):
                        continue
                    if number > 1.0 and number <= 100.0:
                        number /= 100.0
                    if 0.0 <= number <= 1.0:
                        candidates.append(number)
                else:
                    visit(item, depth=depth + 1)
        elif isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        ):
            for item in value[:20]:
                visit(item, depth=depth + 1)

    visit(payload)
    return max(candidates) if candidates else None


def _tool_environment_id(
    payloads: Sequence[BoundedReprojectionPayload],
) -> str:
    identity = "|".join(
        f"{payload.tool_id}:{','.join(payload.source_refs)}" for payload in payloads
    )
    return f"mser.tools.{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]}"


def _failed_answer_verification(
    code: ClaimViolationCode,
    message: str,
    *,
    source_refs: tuple[str, ...],
) -> MSERAnswerVerification:
    return MSERAnswerVerification(
        passed=False,
        disposition=AnswerVerificationDisposition.NEEDS_REPAIR,
        violations=(MSERClaimViolation(code=code, message=message),),
        certificate_source_refs=source_refs,
    )


def _parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return _as_utc(value)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return _as_utc(datetime.fromisoformat(value.strip().replace("Z", "+00:00")))
    except ValueError:
        return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "MSERExecutionMode",
    "MSERPipeline",
    "MSERPipelineState",
    "MSERPipelineTrace",
    "compact_pipeline_context",
    "decision_hint_for_force",
    "merge_environment_representations",
    "mser_enforcement_errors",
    "task_contract_for_question",
]
