"""Server-owned conservative response composition for verified MSER gaps."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import ConfigDict, Field, model_validator

from scout.schemas.base import SchemaModel
from scout.services.mser_answer_verifier import (
    ClaimViolationCode,
    MSERAnswerVerification,
    ReasoningDisposition,
)
from scout.services.mser_pipeline import MSERPipelineState


class MSERComposedCandidateResponse(SchemaModel):
    """Candidate response whose decision is owned by deterministic Scout policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["scout.mser.composed_candidate_response.v0"] = (
        "scout.mser.composed_candidate_response.v0"
    )
    scenario_id: str = Field(min_length=1)
    decision: Literal["DELAY"] = "DELAY"
    answer: str = Field(min_length=1)
    decisive_evidence: tuple[str, ...] = ()
    opposing_evidence: tuple[str, ...] = ()
    evidence_gaps: tuple[str, ...] = Field(min_length=1)
    decision_change_conditions: tuple[str, ...] = Field(min_length=1)
    source_refs: tuple[str, ...] = Field(min_length=1)
    claims: tuple[str, ...] = (
        "candidate_only",
        "runtime_safety_truth=false",
        "server_owned_deterministic_composition",
    )
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


class MSERConservativeResponseComposition(SchemaModel):
    """Auditable result of attempting deterministic gap-response composition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["scout.mser.conservative_response_composition.v0"] = (
        "scout.mser.conservative_response_composition.v0"
    )
    status: Literal["composed", "rejected", "not_applicable"]
    reason_code: str = Field(min_length=1)
    policy_id: Literal["mser.gap.delay.v0"] = "mser.gap.delay.v0"
    state_snapshot_id: str = Field(min_length=1)
    context_id: str = Field(min_length=1)
    original_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    original_decision: str | None = None
    composed_decision: Literal["DELAY"] | None = None
    selected_gap_receipt_ids: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    effective_response: MSERComposedCandidateResponse | None = None
    provider_output_preserved: Literal[True] = True
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @model_validator(mode="after")
    def _validate_status_payload(self) -> "MSERConservativeResponseComposition":
        if self.status == "composed":
            if self.composed_decision != "DELAY" or self.effective_response is None:
                raise ValueError("composed status requires a DELAY effective response")
            if not self.selected_gap_receipt_ids or not self.source_refs:
                raise ValueError("composed status requires typed gap provenance")
        elif self.composed_decision is not None or self.effective_response is not None:
            raise ValueError("non-composed status cannot contain an effective response")
        return self


def compose_conservative_gap_response(
    *,
    state: MSERPipelineState,
    output: Mapping[str, Any] | None,
    verification: MSERAnswerVerification | Mapping[str, Any] | None,
    base_contract_valid: bool,
) -> MSERConservativeResponseComposition:
    """Replace only an optimistic gap decision with server-owned DELAY policy."""

    output_payload = dict(output or {})
    common = {
        "state_snapshot_id": state.state_snapshot_id,
        "context_id": state.packet.compact_context.context_id,
        "original_output_sha256": _payload_sha256(output_payload),
        "original_decision": _normalized_decision(output_payload.get("decision")),
    }

    if state.reasoning.disposition != ReasoningDisposition.READY_TO_EXPLAIN_GAP:
        return MSERConservativeResponseComposition(
            status="not_applicable",
            reason_code="reasoning_not_in_gap_mode",
            **common,
        )
    if not base_contract_valid:
        return MSERConservativeResponseComposition(
            status="rejected",
            reason_code="base_contract_invalid",
            **common,
        )
    violation_codes = _verification_codes(verification)
    if ClaimViolationCode.NON_CONSERVATIVE_GAP_DECISION.value not in violation_codes:
        return MSERConservativeResponseComposition(
            status="not_applicable",
            reason_code="no_non_conservative_gap_decision",
            **common,
        )
    if violation_codes != (ClaimViolationCode.NON_CONSERVATIVE_GAP_DECISION.value,):
        return MSERConservativeResponseComposition(
            status="rejected",
            reason_code="verification_not_single_non_conservative",
            **common,
        )
    if not state.gap_evidence_receipts:
        return MSERConservativeResponseComposition(
            status="rejected",
            reason_code="missing_typed_gap_receipt",
            **common,
        )
    if not _candidate_boundary_valid(output_payload):
        return MSERConservativeResponseComposition(
            status="rejected",
            reason_code="candidate_boundary_invalid",
            **common,
        )
    original_decision = common["original_decision"]
    if original_decision not in {"GO", "CONDITIONAL_GO", "GUIDED_ONLY"}:
        return MSERConservativeResponseComposition(
            status="rejected",
            reason_code="unsupported_original_decision",
            **common,
        )
    scenario_id = str(output_payload.get("scenario_id") or "").strip()
    if not scenario_id:
        return MSERConservativeResponseComposition(
            status="rejected",
            reason_code="missing_scenario_binding",
            **common,
        )

    receipts = state.gap_evidence_receipts
    receipt_ids = tuple(dict.fromkeys(receipt.receipt_id for receipt in receipts))
    source_refs = tuple(dict.fromkeys(receipt.tool_id for receipt in receipts))
    evidence_gaps = _gap_labels(state)
    gap_summary = "、".join(evidence_gaps[:4])
    effective_response = MSERComposedCandidateResponse(
        scenario_id=scenario_id,
        answer=(
            f"關鍵證據仍有缺口（{gap_summary}），目前維持 UNKNOWN 並延後此判斷；"
            "補齊證據後須由 deterministic reducer 重新評估。"
        ),
        decisive_evidence=(
            "MSER sufficiency certificate remains insufficient.",
            f"Typed gap receipts: {', '.join(receipt_ids)}",
        ),
        opposing_evidence=(
            f"模型原始決策 {original_decision} 未通過 evidence-gap policy。",
        ),
        evidence_gaps=evidence_gaps,
        decision_change_conditions=(
            "補齊缺失或過期證據，並通過 deterministic reducer 後重新評估。",
        ),
        source_refs=source_refs,
    )
    return MSERConservativeResponseComposition(
        status="composed",
        reason_code="non_conservative_gap_decision_delayed",
        composed_decision="DELAY",
        selected_gap_receipt_ids=receipt_ids,
        source_refs=source_refs,
        effective_response=effective_response,
        **common,
    )


def _verification_codes(
    verification: MSERAnswerVerification | Mapping[str, Any] | None,
) -> tuple[str, ...]:
    if verification is None:
        return ()
    if isinstance(verification, MSERAnswerVerification):
        codes = (item.code.value for item in verification.violations)
    else:
        codes = (
            str(item.get("code") or "")
            for item in verification.get("violations") or ()
            if isinstance(item, Mapping)
        )
    return tuple(dict.fromkeys(code for code in codes if code))


def _candidate_boundary_valid(output: Mapping[str, Any]) -> bool:
    claims = {str(item).strip().casefold() for item in output.get("claims") or ()}
    return (
        "candidate_only" in claims
        and output.get("runtime_safety_truth") is not True
        and "runtime_safety_truth=true" not in claims
    )


def _gap_labels(state: MSERPipelineState) -> tuple[str, ...]:
    labels: list[str] = []
    for receipt in state.gap_evidence_receipts:
        labels.extend(str(item) for item in receipt.missing_fields if str(item))
        if not receipt.missing_fields:
            labels.extend(item.value for item in receipt.dimensions)
    return tuple(dict.fromkeys(labels)) or ("typed_evidence_gap",)


def _normalized_decision(value: Any) -> str | None:
    normalized = str(value or "").strip().upper()
    return normalized or None


def _payload_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "MSERComposedCandidateResponse",
    "MSERConservativeResponseComposition",
    "compose_conservative_gap_response",
]
