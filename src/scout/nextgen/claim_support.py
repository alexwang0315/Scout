"""Opt-in exact support contracts for model-selected, deterministically rendered facts.

This is not a natural-language entailment judge. Canonical statements and source
bindings come from Scout's verified projection, never from the intelligence reply.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from functools import lru_cache
from typing import Any, Literal

from pydantic import ConfigDict, Field, StrictFloat, StrictInt, StrictStr, ValidationError, create_model, model_validator

from scout.schemas.base import NonEmptyStr, SchemaModel


class ClaimFact(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: NonEmptyStr
    value: StrictInt | StrictFloat | StrictStr | None

    @model_validator(mode="after")
    def finite_value(self) -> "ClaimFact":
        if isinstance(self.value, float) and not math.isfinite(self.value):
            raise ValueError("claim facts cannot contain nonfinite values")
        return self


def evidence_payload_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(
        dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode()).hexdigest()


class ClaimEvidenceBinding(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: NonEmptyStr
    source_ref: NonEmptyStr
    content_hash: NonEmptyStr
    payload_hash: str = Field(pattern=r"^[a-f0-9]{64}$")

    @classmethod
    def from_evidence(cls, payload: Mapping[str, Any]) -> "ClaimEvidenceBinding":
        return cls(
            evidence_id=payload["evidence_id"], source_ref=payload["source_ref"],
            content_hash=payload["content_hash"], payload_hash=evidence_payload_hash(payload),
        )


class SupportedClaim(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: NonEmptyStr
    statement: NonEmptyStr
    evidence_id: NonEmptyStr
    kind: NonEmptyStr
    facts: tuple[ClaimFact, ...] = Field(min_length=1)


class UnavailableClaim(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: NonEmptyStr
    kind: NonEmptyStr
    reason: Literal["missing", "stale", "conflicted"]
    evidence_ids: tuple[NonEmptyStr, ...] = ()
    facts: tuple[ClaimFact, ...] = ()


class ClaimSupportContract(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["scout.claim_support.v0", "scout.claim_support.v1"] = "scout.claim_support.v1"
    input_hash: NonEmptyStr
    evidence: tuple[ClaimEvidenceBinding, ...]
    claims: tuple[SupportedClaim, ...]
    unavailable: tuple[UnavailableClaim, ...] = ()
    context_uncertainty_hashes: tuple[NonEmptyStr, ...] = ()
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @model_validator(mode="after")
    def unique_bound_claims(self) -> "ClaimSupportContract":
        ids = [item.evidence_id for item in self.evidence]
        claim_ids = [item.claim_id for item in (*self.claims, *self.unavailable)]
        if len(ids) != len(set(ids)) or len(claim_ids) != len(set(claim_ids)):
            raise ValueError("claim support requires unique evidence and claim ids")
        if "uncovered_query" in claim_ids:
            raise ValueError("uncovered_query is reserved for unmatched questions")
        if any(claim.evidence_id not in ids for claim in self.claims):
            raise ValueError("claim support cites unbound evidence")
        for unavailable in self.unavailable:
            refs = unavailable.evidence_ids
            if len(refs) != len(set(refs)) or any(ref not in ids for ref in refs):
                raise ValueError("unavailable claim cites duplicate or unbound evidence")
            if unavailable.reason == "conflicted" and len(refs) < 2:
                raise ValueError("conflicted claim requires at least two bound sources")
        statements = [claim.statement for claim in self.claims]
        if len(statements) != len(set(statements)):
            raise ValueError("claim support requires unambiguous canonical statements")
        return self


def render_supported_claim(claim: SupportedClaim) -> dict[str, Any]:
    return {
        "finding_id": f"terrain:selection:{claim.claim_id}",
        "claim": claim.statement, "evidence_ids": [claim.evidence_id], "confidence": 1.0,
        "limitations": [
            "model-selected typed fact; deterministic rendering, not model-authored prose",
            "exact source aggregation, not terrain or safety certainty",
        ],
        "candidate_only": True, "runtime_safety_truth": False,
    }


def claim_support_reasons(
    contract: ClaimSupportContract,
    *,
    findings: Sequence[Mapping[str, Any]],
    evidence: Sequence[Mapping[str, Any]],
    uncertainties: Sequence[Mapping[str, Any]] | None = None,
    conflicts: Sequence[Mapping[str, Any]] = (),
) -> tuple[str, ...]:
    reasons = []
    v1_result = contract.schema_version == "scout.claim_support.v1" and uncertainties is not None
    if (v1_result and not findings and not evidence and not conflicts and len(uncertainties) == 1
            and dict(uncertainties[0]) == render_claim_degradation(uncertainties[0]["uncertainty_id"])):
        return ()
    expected_sources = {item.evidence_id: item for item in contract.evidence}
    seen_sources = set()
    for item in evidence:
        evidence_id = item["evidence_id"]
        expected = expected_sources.get(evidence_id)
        if evidence_id in seen_sources:
            reasons.append(f"claim_support:duplicate_evidence:{evidence_id}")
        seen_sources.add(evidence_id)
        if expected is None or evidence_payload_hash(item) != expected.payload_hash:
            reasons.append(f"claim_support:source_binding_mismatch:{evidence_id}")
    model_abstentions = tuple(item for item in uncertainties or ()
                             if item["uncertainty_id"].startswith("terrain:abstention:"))
    if findings or model_abstentions or conflicts:
        for missing in sorted(expected_sources.keys() - seen_sources):
            reasons.append(f"claim_support:missing_lineage_source:{missing}")
    by_statement = {claim.statement: claim for claim in contract.claims}
    seen_claims = set()
    for finding in findings:
        expected = by_statement.get(finding["claim"])
        if expected is None:
            reasons.append(f"claim_support:unverified_statement:{finding['finding_id']}")
            continue
        if tuple(finding["evidence_ids"]) != (expected.evidence_id,):
            reasons.append(f"claim_support:wrong_evidence:{expected.claim_id}")
        rendered = render_supported_claim(expected)
        if any(finding[key] != rendered[key] for key in ("finding_id", "confidence", "limitations")):
            reasons.append(f"claim_support:rendering_mismatch:{expected.claim_id}")
        if expected.evidence_id not in seen_sources:
            reasons.append(f"claim_support:missing_evidence:{expected.claim_id}")
        if expected.claim_id in seen_claims:
            reasons.append(f"claim_support:duplicate_claim:{expected.claim_id}")
        seen_claims.add(expected.claim_id)
    if v1_result:
        context_hashes = [evidence_payload_hash(item) for item in uncertainties
                          if not item["uncertainty_id"].startswith("terrain:abstention:")]
        if (len(context_hashes) != len(set(context_hashes))
                or set(context_hashes) != set(contract.context_uncertainty_hashes)):
            reasons.append("claim_support:context_uncertainty_mismatch")
    selections = [
        {"claim_id": by_statement[item["claim"]].claim_id, "evidence_id": by_statement[item["claim"]].evidence_id}
        for item in findings if item["claim"] in by_statement
    ]
    reasons.extend(_abstention_support_reasons(
        contract, model_abstentions, conflicts, selections=selections,
        validate_decision_set=v1_result or bool(model_abstentions),
    ))
    return tuple(reasons)


class ClaimSelection(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: NonEmptyStr
    evidence_id: NonEmptyStr


class ClaimAbstention(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: NonEmptyStr
    reason: Literal["missing", "stale", "conflicted", "no_relevant_evidence"]


class ClaimSelectionOutput(SchemaModel):
    selections: tuple[ClaimSelection, ...] = ()
    abstentions: tuple[ClaimAbstention, ...] = ()


class ClaimSubjectSelection(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_ids: tuple[NonEmptyStr, ...]


@lru_cache(maxsize=32)
def _bound_subject_type(ids: tuple[str, ...]) -> type[ClaimSubjectSelection]:
    class SelectedClaimSubjects(ClaimSubjectSelection):
        @model_validator(mode="after")
        def validate_subjects(self) -> "SelectedClaimSubjects":
            if len(self.claim_ids) != len(set(self.claim_ids)) or not set(self.claim_ids).issubset(ids):
                raise ValueError("choose unique subject ids from the supplied rows")
            return self

    return create_model(
        "SelectedClaimSubjects", __base__=SelectedClaimSubjects,
        claim_ids=(tuple[Literal[ids] if ids else NonEmptyStr, ...], Field(max_length=None if ids else 0)),
    )


def claim_subject_output_type(contract: ClaimSupportContract) -> type[ClaimSubjectSelection]:
    return _bound_subject_type(tuple(item.claim_id for item in (*contract.claims, *contract.unavailable)))


def ground_claim_subjects(contract: ClaimSupportContract, subjects: ClaimSubjectSelection) -> ClaimSelectionOutput:
    subjects = claim_subject_output_type(contract).model_validate(subjects.model_dump())
    available = {item.claim_id: item for item in contract.claims}
    unavailable = {item.claim_id: item for item in contract.unavailable}
    selections = tuple(ClaimSelection(claim_id=key, evidence_id=available[key].evidence_id)
                       for key in subjects.claim_ids if key in available)
    abstentions = tuple(ClaimAbstention(claim_id=key, reason=unavailable[key].reason)
                        for key in subjects.claim_ids if key in unavailable)
    if not subjects.claim_ids:
        abstentions = (ClaimAbstention(claim_id="uncovered_query", reason="no_relevant_evidence"),)
    return claim_selection_output_type(contract).model_validate({
        "selections": [item.model_dump() for item in selections],
        "abstentions": [item.model_dump() for item in abstentions],
    })


def claim_subject_prompt(question: str, contract: ClaimSupportContract) -> str:
    rows = [
        {"claim_id": item.claim_id, "subject": item.kind, "status": "available", "facts": [fact.model_dump() for fact in item.facts]}
        for item in contract.claims
    ] + [
        {"claim_id": item.claim_id, "subject": item.kind, "status": item.reason, "facts": [fact.model_dump() for fact in item.facts]}
        for item in contract.unavailable
    ]
    return (
        "Select the evidence subjects requested by the question. Return JSON with only claim_ids, "
        "an array of matching claim_id strings from ROWS. Use [] when no subject answers the question. "
        "Select a requested subject even if its status is missing, stale or conflicted; Scout handles "
        "that status deterministically. Do not select unrelated subjects. Historical sample data can "
        "answer historical sample questions, but cannot prove current conditions, saddle locations "
        "or safe trails. No prose, source IDs or status fields in your output.\n"
        f"Question: {question}\nROWS={json.dumps(rows, separators=(',', ':'))}"
    )


def claim_selection_output_type(contract: ClaimSupportContract) -> type[ClaimSelectionOutput]:
    return _bound_selection_type(
        tuple((claim.claim_id, claim.evidence_id) for claim in contract.claims),
        tuple((claim.claim_id, claim.reason) for claim in contract.unavailable),
    )


@lru_cache(maxsize=32)
def _bound_selection_type(
    pairs: tuple[tuple[str, str], ...], unavailable: tuple[tuple[str, str], ...],
) -> type[ClaimSelectionOutput]:
    allowed = dict(pairs)
    unknowns = {**dict(unavailable), "uncovered_query": "no_relevant_evidence"}

    class SupportedClaimSelections(ClaimSelectionOutput):
        @model_validator(mode="after")
        def validate_support(self) -> "SupportedClaimSelections":
            if not self.selections and not self.abstentions:
                raise ValueError("select supported facts or explicitly abstain")
            seen = set()
            for selection in self.selections:
                if allowed.get(selection.claim_id) != selection.evidence_id:
                    raise ValueError("selected claim and evidence do not match the supplied fact table")
                if selection.claim_id in seen:
                    raise ValueError("duplicate claim selection")
                seen.add(selection.claim_id)
            for abstention in self.abstentions:
                if unknowns.get(abstention.claim_id) != abstention.reason:
                    raise ValueError("abstention must match a supplied unavailable fact and its reason")
                if abstention.claim_id in seen:
                    raise ValueError("duplicate or contradictory claim decision")
                seen.add(abstention.claim_id)
            if "uncovered_query" in seen and len(seen) != 1:
                raise ValueError("uncovered_query is only for a question with no matching fact")
            return self

    selection_type = create_model(
        "SupportedFactSelection", __base__=ClaimSelection,
        claim_id=(Literal[tuple(allowed)] if allowed else NonEmptyStr, ...),
        evidence_id=(Literal[tuple(dict.fromkeys(allowed.values()))] if allowed else NonEmptyStr, ...),
    )
    abstention_type = create_model(
        "SupportedAbstention", __base__=ClaimAbstention,
        claim_id=(Literal[tuple(unknowns)], ...),
        reason=(Literal[tuple(dict.fromkeys(unknowns.values()))], ...),
    )
    return create_model(
        "SupportedClaimSelections", __base__=SupportedClaimSelections,
        selections=(tuple[selection_type, ...], Field(default=(), max_length=None if allowed else 0)),
        abstentions=(tuple[abstention_type, ...], ()),
    )


def render_claim_abstention(contract: ClaimSupportContract, abstention: ClaimAbstention) -> dict[str, Any]:
    claim_selection_output_type(contract).model_validate({"abstentions": [abstention.model_dump()]})
    next_step = {
        "missing": "obtain_missing_evidence", "stale": "refresh_evidence",
        "conflicted": "review_conflicting_sources", "no_relevant_evidence": "obtain_question_relevant_evidence",
    }[abstention.reason]
    return {
        "uncertainty_id": f"terrain:abstention:{abstention.claim_id}:{abstention.reason}",
        "description": f"Model selected abstention for {abstention.claim_id}: {abstention.reason}; "
                       "no supported conclusion was rendered.",
        "missing_evidence": [f"{abstention.claim_id}:{abstention.reason}"],
        "impact": "UNKNOWN", "recommended_next_evidence": [next_step],
    }


def render_claim_conflict(
    contract: ClaimSupportContract, abstention: ClaimAbstention,
) -> dict[str, Any] | None:
    if abstention.reason != "conflicted":
        return None
    claim_selection_output_type(contract).model_validate({"abstentions": [abstention.model_dump()]})
    unavailable = next(item for item in contract.unavailable if item.claim_id == abstention.claim_id)
    return {
        "conflict_id": f"terrain:conflict:{abstention.claim_id}",
        "description": f"Unresolved evidence conflict for {abstention.claim_id}; "
                       "no source was selected as truth.",
        "evidence_ids": list(unavailable.evidence_ids), "unresolved": True,
    }


_DEGRADED_REASONS = frozenset({
    "intelligence_unavailable", "intelligence_task_unsupported", "intelligence_capability_expired",
    "intelligence_evidence_unavailable", "intelligence_backpressure", "intelligence_capability_violation",
    "praison_runtime_unavailable", "intelligence_execution_failed", "intelligence_output_invalid", "intelligence_cancelled",
})


def render_claim_degradation(reason: str) -> dict[str, Any]:
    reason = reason if reason in _DEGRADED_REASONS else "intelligence_unavailable"
    return {
        "uncertainty_id": reason, "description": f"No supported intelligence result: {reason}.",
        "missing_evidence": ["validated_intelligence_result"], "impact": "UNKNOWN",
        "recommended_next_evidence": ["refresh_evidence_or_retry_service"],
    }


def _abstention_support_reasons(
    contract, abstentions, conflicts, *, selections, validate_decision_set,
) -> tuple[str, ...]:
    possible = [ClaimAbstention(claim_id=item.claim_id, reason=item.reason) for item in contract.unavailable]
    possible.append(ClaimAbstention(claim_id="uncovered_query", reason="no_relevant_evidence"))
    expected = {render_claim_abstention(contract, item)["uncertainty_id"]: item for item in possible}
    reasons, seen, required_conflicts, decisions = [], set(), {}, []
    for item in abstentions:
        key = item["uncertainty_id"]
        match = expected.get(key)
        if key in seen or match is None or dict(item) != render_claim_abstention(contract, match):
            reasons.append(f"claim_support:invalid_abstention:{key}")
            continue
        seen.add(key)
        decisions.append(match.model_dump(mode="json"))
        conflict = render_claim_conflict(contract, match)
        if conflict is not None:
            required_conflicts[conflict["conflict_id"]] = conflict
    seen_conflicts = set()
    for conflict in conflicts:
        key = conflict["conflict_id"]
        if key in seen_conflicts or dict(conflict) != required_conflicts.get(key):
            reasons.append(f"claim_support:invalid_conflict:{key}")
        seen_conflicts.add(key)
    for missing in required_conflicts.keys() - seen_conflicts:
        reasons.append(f"claim_support:missing_conflict:{missing}")
    if validate_decision_set:
        try:
            claim_selection_output_type(contract).model_validate({"selections": selections, "abstentions": decisions})
        except ValidationError:
            reasons.append("claim_support:invalid_decision_set")
    return tuple(reasons)


def claim_selection_prompt(question: str, contract: ClaimSupportContract) -> str:
    # Canonical prose stays outside the model prompt; this evaluates fact selection.
    facts = [claim.model_dump(mode="json", exclude={"statement"}) for claim in contract.claims]
    return (
        "Task: select evidence rows for the question, not give route advice. "
        "For each requested subject: if it is in FACTS, copy claim_id and evidence_id "
        "into selections; if it is in UNAVAILABLE, copy claim_id and reason into abstentions. "
        "Ignore unrequested subjects in both tables. Available historical/candidate data "
        "CAN answer historical sample questions; it is not missing merely because it is historical. "
        "Only when neither table has a subject answering the question, abstain with "
        "claim_id=uncovered_query and reason=no_relevant_evidence. "
        "Sample counts cannot establish current conditions, saddle locations, verified trails or safety. "
        "Return one JSON object with selections and abstentions arrays; unused arrays are empty. "
        "No prose, calculations or invented fields.\n"
        f"Question: {question}\nFACTS={json.dumps(facts, separators=(',', ':'))}\n"
        f"UNAVAILABLE={json.dumps([item.model_dump(mode='json') for item in contract.unavailable], separators=(',', ':'))}"
    )
