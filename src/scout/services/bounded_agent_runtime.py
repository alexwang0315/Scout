"""Deterministic bounded-context and progressive-tool runtime helpers."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from scout.schemas.agent_runtime import (
    AgentProgressState,
    AgentRequestLedger,
    AgentRunBudget,
    AgentRunLedger,
    ContextHandle,
    ContextReadResult,
    EvidenceCard,
    EvidenceRecord,
    GroundingVerification,
    PlannedToolCall,
    ToolCard,
    ToolPlan,
)


_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_.-]+|[\u3400-\u9fff]")
_CITATION_PATTERN = re.compile(
    r"\[([^\[\]]+)\]|【([^【】]+)】"
)
_NUMBER_PATTERN = re.compile(r"(?<![A-Za-z])\d+(?:\.\d+)?")
_DATETIME_LIKE_PATTERN = re.compile(
    r"\b\d{4}-\d{2}-\d{2}[Tt][0-9:.+-]+(?:Z|[+-]\d{2}:\d{2})?\b"
)
_SENSITIVE_KEY_FRAGMENTS = (
    "api_key",
    "authorization",
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
)
_SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{6,}"),
    re.compile(r"(?i)\b(?:sk-|gh[pousr]_|github_pat_|xox[baprs]-)[A-Za-z0-9_-]{8,}"),
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    re.compile(
        r"(?i)\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)"
        r"\s*[:=]\s*\S+"
    ),
)
_PRIVATE_SENSITIVITY_VALUES = frozenset(
    {"confidential", "private", "restricted", "secret"}
)
_REDACTED_VALUE = "[REDACTED]"
_GROUNDING_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "available",
    "by",
    "evidence",
    "for",
    "from",
    "in",
    "is",
    "of",
    "on",
    "or",
    "that",
    "the",
    "there",
    "this",
    "to",
    "was",
    "were",
    "with",
}
_SAFETY_CONCEPT_TOKENS = {
    "emergency": frozenset({"emergencies", "emergency", "sos"}),
    "evacuation": frozenset(
        {"evacuate", "evacuated", "evacuation", "retreat"}
    ),
    "fatality": frozenset(
        {"dead", "death", "deaths", "fatalities", "fatality", "killed"}
    ),
    "hazard": frozenset(
        {"danger", "dangerous", "hazard", "hazardous", "hazards"}
    ),
    "injury": frozenset(
        {"casualties", "casualty", "injured", "injuries", "injury"}
    ),
    "rescue": frozenset({"rescue", "rescued"}),
    "risk": frozenset({"risk", "risks", "risky"}),
    "safe": frozenset({"safe", "safely", "safety"}),
    "unsafe": frozenset({"unsafe"}),
}
_SAFETY_CONCEPT_PHRASES = {
    "emergency": ("緊急",),
    "evacuation": ("撤離", "折返"),
    "fatality": ("死亡", "罹難", "致命"),
    "hazard": ("危險", "危害"),
    "injury": ("傷亡", "受傷"),
    "rescue": ("救援",),
    "risk": ("風險",),
    "safe": ("安全",),
    "unsafe": ("不安全",),
}
_GROUNDING_CONCEPT_ALIASES = {
    "checkpoint": ("checkpoint", "checkpoints", "cp", "檢查點", "控制點"),
    "mileage": ("mileage", "kilometer", "kilometre", "里程", "公里", "k標"),
    "route": ("route", "track", "trail", "路線", "路徑", "航跡"),
    "risk_score": ("risk_score", "score", "風險分數", "風險值"),
    "terrain": ("terrain", "slope", "地形", "坡度"),
    "weather": ("weather", "rain", "wind", "天氣", "降雨", "風勢"),
}


def estimate_tokens(value: str | bytes | object) -> int:
    """Return a conservative, provider-independent token estimate."""

    if isinstance(value, bytes):
        chars = len(value.decode("utf-8", errors="replace"))
    elif isinstance(value, str):
        chars = len(value)
    else:
        chars = len(_json_dumps(value))
    return math.ceil(chars / 4)


class BoundedAgentRuntime:
    """Small deterministic waist between discovery, tools, and model synthesis."""

    def __init__(
        self,
        *,
        context_handles: Sequence[ContextHandle] = (),
        context_payloads: Mapping[str, Any] | None = None,
        tool_cards: Sequence[ToolCard] = (),
        tool_schemas: Mapping[str, dict[str, Any]] | None = None,
        budget: AgentRunBudget | None = None,
    ) -> None:
        self._context_handles = tuple(context_handles)
        self._context_payloads = dict(context_payloads or {})
        self._tool_cards = tuple(tool_cards)
        self._tool_schemas = dict(tool_schemas or {})
        self.budget = budget or AgentRunBudget()
        self.last_context_catalog_scan_count = 0
        self.last_context_returned_tokens = 0
        self.last_described_tool_count = 0

    def context_find(
        self,
        query: str,
        *,
        filters: Mapping[str, object] | None = None,
        top_k: int = 10,
        token_budget: int | None = None,
    ) -> list[ContextHandle]:
        """Return only compact handles, ranked and bounded by top-k and tokens."""

        resolved_top_k = max(1, min(int(top_k), 10))
        resolved_budget = None if token_budget is None else max(1, int(token_budget))
        filter_values = dict(filters or {})
        self.last_context_catalog_scan_count = len(self._context_handles)
        ranked = sorted(
            (
                (self._context_score(handle, query), handle)
                for handle in self._context_handles
                if _matches_context_filters(handle, filter_values)
            ),
            key=lambda item: (-item[0], item[1].context_id),
        )
        selected: list[ContextHandle] = []
        used_tokens = 0
        for score, handle in ranked:
            if len(selected) >= resolved_top_k:
                break
            if score <= 0.0:
                continue
            cost = max(1, handle.estimated_tokens)
            if resolved_budget is not None and used_tokens + cost > resolved_budget:
                continue
            selected.append(handle.model_copy(update={"relevance_score": min(1.0, score)}))
            used_tokens += cost
        self.last_context_returned_tokens = used_tokens
        return selected

    def context_read(
        self,
        context_id: str,
        *,
        selector: str | None = None,
        token_budget: int | None = None,
    ) -> ContextReadResult:
        """Read one selected context and return a bounded projection."""

        handle = next(
            (item for item in self._context_handles if item.context_id == context_id),
            None,
        )
        if handle is None:
            raise KeyError(f"unknown context handle: {context_id}")
        payload = self._context_payloads.get(context_id)
        selected = _select_payload(payload, selector)
        serialized = _json_dumps(selected)
        max_chars = None if token_budget is None else max(80, int(token_budget) * 4)
        truncated = max_chars is not None and len(serialized) > max_chars
        if truncated:
            assert max_chars is not None
            preview_limit = max(20, max_chars - 160)
            content: Any = {"preview": serialized[:preview_limit]}
        else:
            content = selected
        continuation = (
            _continuation_handle("context", context_id, serialized) if truncated else None
        )
        estimated_tokens = estimate_tokens(_json_dumps(content))
        estimated = (
            estimated_tokens
            if token_budget is None
            else min(int(token_budget), estimated_tokens)
        )
        return ContextReadResult(
            context_id=context_id,
            source_ref=handle.source_ref,
            selector=selector,
            content=content,
            truncated=truncated,
            continuation_handle=continuation,
            estimated_tokens=estimated,
        )

    def tool_find(
        self,
        *,
        intent: str,
        domain: str | None = None,
        risk: str | None = None,
        top_k: int = 3,
    ) -> list[ToolCard]:
        """Rank compact cards without touching their full schemas."""

        resolved_top_k = max(1, min(int(top_k), 12))
        candidates = [
            card
            for card in self._tool_cards
            if card.availability == "available"
            and (risk is None or card.risk_level == risk)
        ]
        scored = [
            (
                _lexical_score(
                    intent,
                    " ".join(
                        (
                            card.tool_id,
                            card.purpose,
                            " ".join(card.required_inputs),
                            card.output_artifact_kind,
                            domain or "",
                        )
                    ),
                ),
                card,
            )
            for card in candidates
        ]
        ranked = sorted(
            (item for item in scored if item[0] > 0.0),
            key=lambda item: (
                -item[0],
                item[1].tool_id,
            ),
        )
        return [card for _, card in ranked[:resolved_top_k]]

    def tool_describe(self, tool_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
        """Load full schemas only for an already bounded shortlist."""

        selected_ids = list(dict.fromkeys(tool_ids))[:12]
        described = {
            tool_id: self._tool_schemas[tool_id]
            for tool_id in selected_ids
            if tool_id in self._tool_schemas
        }
        self.last_described_tool_count = len(described)
        return described

    def build_tool_plan(
        self,
        *,
        selected_tool_ids: Sequence[str],
        arguments_by_tool: Mapping[str, dict[str, Any]] | None = None,
        reasons_by_tool: Mapping[str, str] | None = None,
        expected_evidence_by_tool: Mapping[str, list[str]] | None = None,
        compound: bool = False,
    ) -> ToolPlan:
        """Create a typed plan and apply the general/compound hard cap."""

        hard_cap = self.budget.max_tool_calls
        selected = list(dict.fromkeys(selected_tool_ids))[:hard_cap]
        arguments = dict(arguments_by_tool or {})
        reasons = dict(reasons_by_tool or {})
        expected = dict(expected_evidence_by_tool or {})
        calls = [
            PlannedToolCall(
                tool_id=tool_id,
                arguments=arguments.get(tool_id, {}),
                reason=reasons.get(tool_id, "Selected by bounded tool discovery."),
                expected_evidence=expected.get(tool_id, []),
            )
            for tool_id in selected
        ]
        return ToolPlan(
            selected_tool_ids=selected,
            tool_calls=calls,
            estimated_input_tokens=sum(
                estimate_tokens(call.model_dump_json()) for call in calls
            ),
            estimated_output_tokens=(
                0
                if self.budget.max_tool_result_tokens is None
                else self.budget.max_tool_result_tokens * len(calls)
            ),
            required_bundle_expansion=[],
            stop_or_replan_condition=(
                "Stop after sufficient verified evidence; otherwise continue useful "
                "supplemental retrievals within this stage's 10-call budget."
            ),
        )

    def evidence_from_tool_result(
        self,
        tool_id: str,
        result: Any,
        *,
        token_budget: int | None = None,
    ) -> EvidenceCard:
        """Project a raw server-side result into one bounded EvidenceCard."""

        configured_budget = (
            token_budget
            if token_budget is not None
            else self.budget.max_tool_result_tokens
        )
        resolved_budget = (
            None
            if configured_budget is None
            else max(50, int(configured_budget))
        )
        raw_result = result if isinstance(result, dict) else {"value": result}
        sensitivity = str(raw_result.get("sensitivity") or "").strip().casefold()
        if sensitivity in _PRIVATE_SENSITIVITY_VALUES:
            result_dict: dict[str, Any] = {
                "status": "withheld",
                "quality": "withheld",
                "missing_fields": ["private_evidence_withheld"],
            }
        else:
            sanitized = _sanitize_model_value(
                raw_result,
                depth=0,
                bounded=self.budget.enforce_resource_limits,
            )
            result_dict = sanitized if isinstance(sanitized, dict) else {}
        serialized = _json_dumps(result_dict)
        source_refs = _extract_source_refs(result_dict)
        evidence_records = _extract_evidence_records(
            result_dict,
            bounded=self.budget.enforce_resource_limits,
        )
        missing_fields = _string_list(result_dict.get("missing_fields"))
        claim_summary = _claim_summary(result_dict)
        result_count = _result_count(result_dict)
        key_values = _bounded_key_values(
            result_dict,
            bounded=self.budget.enforce_resource_limits,
        )
        card = EvidenceCard(
            tool_id=tool_id,
            claim_summary=claim_summary,
            key_values=key_values,
            missing_fields=missing_fields,
            freshness=_freshness(result_dict),
            quality=_quality(result_dict),
            source_refs=source_refs,
            evidence_records=evidence_records,
            result_count=result_count,
            truncated=False,
            estimated_tokens=0,
        )
        card_tokens = estimate_tokens(card.model_dump_json())
        truncated = self.budget.enforce_resource_limits and resolved_budget is not None and (
            len(serialized) > resolved_budget * 4 or card_tokens > resolved_budget
        )
        continuation = (
            _continuation_handle("tool", tool_id, serialized) if truncated else None
        )
        card = card.model_copy(
            update={
                "truncated": truncated,
                "continuation_handle": continuation,
            }
        )
        if truncated:
            assert resolved_budget is not None
            card = _fit_evidence_card_to_budget(card, resolved_budget)
        final_tokens = estimate_tokens(card.model_dump_json())
        card = card.model_copy(update={"estimated_tokens": final_tokens})
        final_tokens = estimate_tokens(card.model_dump_json())
        return card.model_copy(update={"estimated_tokens": final_tokens})

    def record_tool_progress(
        self,
        state: AgentProgressState,
        *,
        tool_id: str,
        arguments: Mapping[str, Any],
        evidence_ids: Sequence[str],
        root_cause: str | None = None,
        safe_retry: bool = False,
    ) -> AgentProgressState:
        """Return a new state and stop deterministic no-progress loops."""

        canonical_key = hashlib.sha256(
            _json_dumps({"tool_id": tool_id, "arguments": arguments}).encode("utf-8")
        ).hexdigest()
        stage_counts = dict(state.stage_tool_call_counts)
        stage_counts[state.stage] = stage_counts.get(state.stage, 0) + 1
        if canonical_key in state.canonical_call_keys:
            return state.model_copy(
                update={
                    "stage_tool_call_counts": stage_counts,
                    "stop_reason": "duplicate_canonical_tool_call",
                }
            )
        known_evidence = set(state.evidence_ids)
        new_evidence = [item for item in evidence_ids if item not in known_evidence]
        no_progress = (
            0
            if new_evidence
            else state.consecutive_calls_without_new_evidence + 1
        )
        root_causes = list(state.safe_retry_root_causes)
        stop_reason: str | None = None
        stage_limit = self.budget.stage_budget.tool_call_limit(state.stage)
        if stage_counts[state.stage] > stage_limit:
            stop_reason = f"stage_tool_call_limit_exceeded:{state.stage.value}"
        elif root_cause and not safe_retry:
            stop_reason = f"terminal_evidence_gap:{root_cause}"
        elif root_cause and root_cause in root_causes:
            stop_reason = f"repeated_safe_retry_root_cause:{root_cause}"
        elif no_progress >= 2:
            stop_reason = "two_tool_calls_without_new_evidence"
        if root_cause and safe_retry:
            root_causes.append(root_cause)
        return AgentProgressState(
            stage=state.stage,
            canonical_call_keys=[*state.canonical_call_keys, canonical_key],
            evidence_ids=_dedupe([*state.evidence_ids, *new_evidence]),
            consecutive_calls_without_new_evidence=no_progress,
            safe_retry_root_causes=root_causes,
            stage_tool_call_counts=stage_counts,
            stop_reason=stop_reason,
        )

    def record_request(
        self,
        ledger: AgentRunLedger,
        request: AgentRequestLedger,
        *,
        selected_tool_ids: Sequence[str] = (),
        executed_tool_ids: Sequence[str] = (),
    ) -> AgentRunLedger:
        """Return a new aggregate ledger and deterministic stop decision."""

        requests = [*ledger.requests, request]
        selected = _dedupe([*ledger.selected_tool_ids, *selected_tool_ids])
        executed = _dedupe([*ledger.executed_tool_ids, *executed_tool_ids])
        totals = {
            field: sum(getattr(item, field) for item in requests)
            for field in (
                "system_chars",
                "tool_schema_count",
                "tool_schema_chars",
                "user_history_chars",
                "tool_result_chars",
                "input_tokens",
                "cache_write_tokens",
                "cache_read_tokens",
                "output_tokens",
                "tool_call_count",
                "retry_count",
                "repair_count",
                "estimated_cost",
            )
        }
        budget = ledger.budget
        stop_reason = _budget_stop_reason(budget, len(requests), totals)
        remaining: dict[str, int | float | None] = {
            "requests": max(0, budget.max_requests - len(requests)),
            "tool_calls": max(0, budget.max_tool_calls - int(totals["tool_call_count"])),
            "input_tokens": _remaining_optional_limit(
                budget.max_input_tokens,
                int(totals["input_tokens"]),
            ),
            "output_tokens": _remaining_optional_limit(
                budget.max_output_tokens,
                int(totals["output_tokens"]),
            ),
            "total_tokens": _remaining_optional_limit(
                budget.max_total_tokens,
                int(totals["input_tokens"]) + int(totals["output_tokens"]),
            ),
            "repairs": max(0, budget.max_repairs - int(totals["repair_count"])),
            "estimated_cost": (
                None
                if budget.max_estimated_cost is None
                else max(
                    0.0,
                    budget.max_estimated_cost - float(totals["estimated_cost"]),
                )
            ),
        }
        return AgentRunLedger(
            budget=budget,
            requests=requests,
            request_count=len(requests),
            tool_call_count=int(totals["tool_call_count"]),
            system_chars=int(totals["system_chars"]),
            tool_schema_count=int(totals["tool_schema_count"]),
            tool_schema_chars=int(totals["tool_schema_chars"]),
            user_history_chars=int(totals["user_history_chars"]),
            tool_result_chars=int(totals["tool_result_chars"]),
            input_tokens=int(totals["input_tokens"]),
            cache_write_tokens=int(totals["cache_write_tokens"]),
            cache_read_tokens=int(totals["cache_read_tokens"]),
            output_tokens=int(totals["output_tokens"]),
            estimated_cost=float(totals["estimated_cost"]),
            cost_estimate_available=(
                bool(requests)
                and all(item.cost_estimate_available for item in requests)
            ),
            budget_remaining=remaining,
            budget_stop_reason=stop_reason,
            selected_tool_ids=selected,
            executed_tool_ids=executed,
            retry_count=int(totals["retry_count"]),
            repair_count=int(totals["repair_count"]),
        )

    @staticmethod
    def can_continue(ledger: AgentRunLedger) -> bool:
        return (
            ledger.budget_stop_reason is None
            and ledger.request_count < ledger.budget.max_requests
            and ledger.tool_call_count < ledger.budget.max_tool_calls
        )

    def build_no_tool_synthesis_prompt(
        self,
        *,
        question: str,
        evidence_cards: Sequence[EvidenceCard],
        missing_evidence: Sequence[str],
        token_budget: int | None = None,
    ) -> str:
        """Build a bounded final prompt with evidence only and no tool definitions."""

        payload = {
            "question": question,
            "evidence_cards": [card.model_dump(mode="json") for card in evidence_cards],
            "missing_evidence": list(missing_evidence),
            "answer_contract": (
                "Answer only from evidence_cards in at most three short sentences. "
                "After every concrete claim, cite exact strings from source_refs as "
                "[exact/source/ref] or a record as [evidence:exact_evidence_id]. "
                "Never cite continuation_handle, tool_id, "
                "or add a source: prefix. Report only missing evidence listed in "
                "missing_evidence. Candidate evidence is not runtime safety truth. "
                "Do not use headings or lists. Do not call tools."
            ),
        }
        prompt = "SCOUT_BOUNDED_SYNTHESIS_V1\n" + _json_dumps(payload)
        return (
            prompt
            if token_budget is None
            else prompt[: max(200, int(token_budget) * 4)]
        )

    def build_grounding_repair_prompt(
        self,
        *,
        question: str,
        draft_answer: str,
        verification: GroundingVerification,
        evidence_cards: Sequence[EvidenceCard],
        token_budget: int | None = None,
    ) -> str:
        """Build the sole allowed repair request from failures and evidence delta."""

        evidence_delta = [
            {
                "tool_id": card.tool_id,
                "claim_summary": card.claim_summary,
                "key_values": card.key_values,
                "missing_fields": card.missing_fields,
                "freshness": card.freshness,
                "quality": card.quality,
                "source_refs": card.source_refs,
                "evidence_records": [
                    item.model_dump(mode="json") for item in card.evidence_records
                ],
            }
            for card in evidence_cards
        ]
        payload = {
            "question": question,
            "draft_answer": draft_answer,
            "repair_items": verification.repair_items,
            "evidence_delta": evidence_delta,
            "answer_contract": (
                "Rewrite only the unsupported or invalidly cited statements. "
                "If repair_items contains missing_exact_field_fact, restore every "
                "listed literal and preserve all clauses of each priority-100 "
                "field_answer. "
                "Every factual sentence must cite an exact listed source_ref using "
                "[exact/source/ref] or a record using [evidence:exact_evidence_id]. "
                "Never cite continuation_handle, tool_id, or add a "
                "source: prefix. Use at most three short sentences. Do not add facts, "
                "tools, or unstated numbers."
            ),
        }
        prompt = "SCOUT_BOUNDED_SYNTHESIS_REPAIR_V1\n" + _json_dumps(payload)
        return (
            prompt
            if token_budget is None
            else prompt[: max(200, int(token_budget) * 4)]
        )

    @staticmethod
    def verify_synthesis(
        answer: str,
        *,
        evidence_cards: Sequence[EvidenceCard],
    ) -> GroundingVerification:
        """Reject factual sentences without valid evidence citations."""

        valid_refs = {
            ref for card in evidence_cards for ref in card.source_refs
        } | {
            f"evidence:{record.evidence_id}"
            for card in evidence_cards
            for record in card.evidence_records
        }
        cited = _dedupe(_citation_refs(answer))
        invalid = [ref for ref in cited if ref not in valid_refs]
        unsupported: list[str] = []
        answer_sentences = _answer_sentences(answer)
        if not answer_sentences:
            unsupported.append("answer_contains_no_factual_claim")
        for sentence in answer_sentences:
            sentence_refs = _citation_refs(sentence)
            if not any(ref in valid_refs for ref in sentence_refs):
                unsupported.append(sentence.strip())
                continue
            supporting_cards = [
                card
                for card in evidence_cards
                if any(
                    ref in card.source_refs
                    or any(
                        ref == f"evidence:{record.evidence_id}"
                        for record in card.evidence_records
                    )
                    for ref in sentence_refs
                )
            ]
            if not _claim_has_evidence_overlap(sentence, supporting_cards):
                unsupported.append(sentence.strip())
                continue
            claim_text = _strip_citations(sentence)
            numbers = _NUMBER_PATTERN.findall(claim_text)
            evidence_numbers = set(
                _NUMBER_PATTERN.findall(_grounding_evidence_text(supporting_cards))
            )
            evidence_text = _grounding_evidence_text(supporting_cards)
            exact_datetimes = _DATETIME_LIKE_PATTERN.findall(claim_text)
            if any(value not in evidence_text for value in exact_datetimes):
                unsupported.append(sentence.strip())
                continue
            if any(
                not _number_is_grounded(number, evidence_numbers)
                for number in numbers
            ):
                unsupported.append(sentence.strip())
        unsupported = _dedupe([item for item in unsupported if item])
        unsupported_safety_claims = [
            claim
            for claim in unsupported
            if _safety_concepts(_strip_citations(claim))
        ]
        missing_exact_facts = _missing_priority_exact_field_facts(
            answer,
            evidence_cards,
        )
        missing_exact_sources = _missing_priority_exact_field_sources(
            answer,
            evidence_cards,
        )
        repair_items = [
            *(f"invalid_source_ref:{ref}" for ref in invalid),
            *(f"unsupported_claim:{claim}" for claim in unsupported),
            *(f"missing_exact_field_fact:{fact}" for fact in missing_exact_facts),
            *(
                f"missing_exact_field_source_ref:{source_ref}"
                for source_ref in missing_exact_sources
            ),
        ]
        passed = (
            not invalid
            and not unsupported
            and not missing_exact_facts
            and not missing_exact_sources
        )
        if passed:
            output_disposition = "grounded"
        elif unsupported_safety_claims:
            output_disposition = "fail_closed"
        else:
            output_disposition = "needs_repair"
        return GroundingVerification(
            passed=passed,
            output_disposition=output_disposition,
            cited_source_refs=[ref for ref in cited if ref in valid_refs],
            invalid_source_refs=invalid,
            unsupported_claims=unsupported,
            rejected_draft_claims=unsupported_safety_claims,
            repair_items=repair_items,
        )

    @classmethod
    def attach_verified_source_refs(
        cls,
        answer: str,
        *,
        evidence_cards: Sequence[EvidenceCard],
    ) -> str:
        """Attach provenance without changing model-authored factual text.

        Small local models often return a supported sentence but omit the
        requested citation. A source ref is attached only when that exact
        sentence passes the normal grounding verifier against one evidence
        card. Unsupported facts and numbers remain unchanged and fail closed.
        """

        ordered_cards = sorted(
            enumerate(evidence_cards),
            key=lambda item: (-_field_answer_priority(item[1]), item[0]),
        )
        for _, card in ordered_cards:
            if _field_answer_priority(card) < 100:
                continue
            preferred_refs = _priority_field_answer_source_refs(card)
            for source_ref in preferred_refs:
                candidate = answer
                for sentence in _answer_sentences(answer):
                    if _citation_refs(sentence):
                        continue
                    candidate = candidate.replace(
                        sentence,
                        _append_source_ref(sentence, source_ref),
                        1,
                    )
                if cls.verify_synthesis(
                    candidate,
                    evidence_cards=evidence_cards,
                ).passed:
                    return candidate

        repaired = answer
        for sentence in _answer_sentences(answer):
            if _citation_refs(sentence):
                continue
            cited_sentence = _first_verified_citation_candidate(
                sentence,
                evidence_cards=evidence_cards,
            )
            if cited_sentence is None:
                continue
            repaired = repaired.replace(sentence, cited_sentence, 1)
        if repaired == answer:
            return answer
        return (
            repaired
            if cls.verify_synthesis(repaired, evidence_cards=evidence_cards).passed
            else answer
        )

    @staticmethod
    def _context_score(handle: ContextHandle, query: str) -> float:
        lexical = _lexical_score(
            query,
            " ".join(
                (
                    handle.context_id,
                    handle.domain_id,
                    handle.artifact_kind,
                    handle.title,
                    handle.source_ref,
                    _json_dumps(handle.scope_metadata),
                    _json_dumps(handle.time_metadata),
                    _json_dumps(handle.spatial_metadata),
                )
            ),
        )
        if lexical <= 0.0:
            return 0.0
        scope_tool_ids = handle.scope_metadata.get("tool_ids")
        exact_tool_scope = (
            any(
                str(tool_id).casefold() in query.casefold()
                for tool_id in scope_tool_ids
            )
            if isinstance(scope_tool_ids, list)
            else False
        )
        if exact_tool_scope:
            return min(
                1.0,
                0.65 + handle.relevance_score * 0.1 + lexical * 0.25,
            )
        return min(1.0, handle.relevance_score * 0.35 + lexical * 0.65)


def _matches_context_filters(
    handle: ContextHandle,
    filters: Mapping[str, object],
) -> bool:
    for key in ("context_id", "domain_id", "artifact_kind", "freshness", "sensitivity"):
        expected = filters.get(key)
        if expected is not None and getattr(handle, key) != expected:
            return False
    return True


def _lexical_score(query: str, text: str) -> float:
    query_tokens = _search_tokens(query)
    if not query_tokens:
        return 0.0
    text_tokens = _search_tokens(text)
    overlap = len(query_tokens & text_tokens) / len(query_tokens)
    phrase_bonus = 0.25 if query.casefold() in text.casefold() else 0.0
    return min(1.0, overlap + phrase_bonus)


def _search_tokens(value: str) -> set[str]:
    tokens: set[str] = set()
    for raw in _TOKEN_PATTERN.findall(value.casefold()):
        pieces = [raw, *re.split(r"[_.-]+", raw)]
        for piece in pieces:
            if not piece:
                continue
            tokens.add(piece)
            if len(piece) > 3 and piece.endswith("s"):
                tokens.add(piece[:-1])
            if len(piece) > 4 and piece.endswith("ed"):
                tokens.add(piece[:-1])
                tokens.add(piece[:-2])
    return tokens


def _select_payload(payload: Any, selector: str | None) -> Any:
    if selector is None or not isinstance(payload, Mapping):
        return payload
    current: Any = payload
    for part in selector.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _bounded_key_values(
    payload: Mapping[str, Any],
    *,
    bounded: bool,
) -> dict[str, Any]:
    excluded = {
        "boundary",
        "candidate_only",
        "runtime_safety_truth",
        "artifact_ref",
        "path",
        "source_path",
        "source_ref",
        "sources",
        "source_refs",
        "source_report",
        "missing_fields",
        "sensitivity",
    }
    output: dict[str, Any] = {}
    for key, value in payload.items():
        if key in excluded or _is_sensitive_key(key):
            continue
        if bounded and len(output) >= 10:
            break
        output[str(key)] = (
            _bounded_value(value, depth=0)
            if bounded
            else _sanitize_model_value(value, depth=0, bounded=False)
        )
    return output


def _bounded_value(value: Any, *, depth: int) -> Any:
    if depth >= 3:
        return "[nested content omitted]"
    if isinstance(value, str):
        return value if len(value) <= 240 else f"{value[:237]}..."
    if isinstance(value, Mapping):
        return {
            str(key): _bounded_value(item, depth=depth + 1)
            for key, item in list(value.items())[:8]
            if not _is_sensitive_key(key)
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_bounded_value(item, depth=depth + 1) for item in list(value)[:5]]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:240]


def _fit_evidence_card_to_budget(
    card: EvidenceCard,
    token_budget: int,
) -> EvidenceCard:
    """Drop bounded previews until the serialized card fits its model budget."""

    records = [
        record.model_copy(
            update={
                "data": (
                    bounded
                    if isinstance(
                        bounded := _bounded_value(record.data, depth=0),
                        dict,
                    )
                    else {}
                )
            }
        )
        for record in card.evidence_records[:8]
    ]
    key_values = {
        key: _bounded_value(value, depth=0)
        for key, value in list(card.key_values.items())[:3]
    }
    source_refs = list(card.source_refs)
    missing_fields = list(card.missing_fields)
    claim_summary = card.claim_summary[:240]

    for _ in range(128):
        candidate = card.model_copy(
            update={
                "claim_summary": claim_summary,
                "key_values": key_values,
                "missing_fields": missing_fields,
                "source_refs": source_refs,
                "evidence_records": records,
                "estimated_tokens": token_budget,
            }
        )
        if estimate_tokens(candidate.model_dump_json()) <= token_budget:
            return candidate
        if len(records) > 1:
            records = records[:-1]
            continue
        if records and records[0].data:
            data_items = list(records[0].data.items())
            compact_data = (
                {str(data_items[0][0]): _bounded_value(data_items[0][1], depth=0)}
                if len(data_items) > 1
                else {}
            )
            records = [records[0].model_copy(update={"data": compact_data})]
            continue
        if records:
            records = []
            continue
        if key_values:
            key_values = dict(list(key_values.items())[:-1])
            continue
        if len(source_refs) > 1:
            source_refs = source_refs[:1]
            continue
        if len(missing_fields) > 1:
            missing_fields = missing_fields[:1]
            continue
        if len(claim_summary) > 80:
            claim_summary = claim_summary[:80]
            continue
        if claim_summary:
            claim_summary = ""
            continue
        return candidate
    return candidate


def _sanitize_model_value(value: Any, *, depth: int, bounded: bool) -> Any:
    if depth > (6 if bounded else 32):
        return "[nested content omitted]"
    if isinstance(value, Mapping):
        return {
            str(key): _sanitize_model_value(
                item,
                depth=depth + 1,
                bounded=bounded,
            )
            for key, item in value.items()
            if not _is_sensitive_key(key)
        }
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return [
            _sanitize_model_value(
                item,
                depth=depth + 1,
                bounded=bounded,
            )
            for item in (list(value)[:100] if bounded else value)
        ]
    if isinstance(value, str):
        stripped = value.strip()
        if any(pattern.search(stripped) for pattern in _SENSITIVE_VALUE_PATTERNS):
            return _REDACTED_VALUE
        if "://" in stripped:
            parsed = urlsplit(stripped)
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                if parsed.username is not None or parsed.password is not None:
                    return _REDACTED_VALUE
                return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
        return value
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = str(value)
    return text[:240] if bounded else text


def _extract_source_refs(value: Any) -> list[str]:
    refs: list[str] = []

    if isinstance(value, Mapping):
        preferred = value.get("field_answer_source_ref")
        if isinstance(preferred, str) and (safe_ref := _safe_source_ref(preferred)):
            refs.append(safe_ref)
        preferred_many = value.get("field_answer_source_refs")
        if isinstance(preferred_many, Sequence) and not isinstance(
            preferred_many,
            (str, bytes, bytearray),
        ):
            for preferred_ref in preferred_many:
                if isinstance(preferred_ref, str) and (
                    safe_ref := _safe_source_ref(preferred_ref)
                ):
                    refs.append(safe_ref)

    def visit(item: Any, *, depth: int) -> None:
        if depth > 32:
            return
        if isinstance(item, Mapping):
            for key, child in item.items():
                normalized = str(key).casefold()
                if normalized in {
                    "source_ref",
                    "source_path",
                    "path",
                    "artifact_ref",
                } and isinstance(child, str) and child.strip():
                    if safe_ref := _safe_source_ref(child):
                        refs.append(safe_ref)
                elif normalized in {"source_refs", "source_paths"}:
                    if isinstance(child, Mapping):
                        for ref in child.values():
                            if isinstance(ref, str) and (
                                safe_ref := _safe_source_ref(ref)
                            ):
                                refs.append(safe_ref)
                    elif isinstance(child, Sequence) and not isinstance(
                        child, (str, bytes, bytearray)
                    ):
                        for ref in child:
                            if isinstance(ref, str) and (
                                safe_ref := _safe_source_ref(ref)
                            ):
                                refs.append(safe_ref)
                else:
                    visit(child, depth=depth + 1)
        elif isinstance(item, Sequence) and not isinstance(
            item, (str, bytes, bytearray)
        ):
            for child in item:
                visit(child, depth=depth + 1)

    visit(value, depth=0)
    return _dedupe(refs)


def _extract_evidence_records(
    payload: Mapping[str, Any],
    *,
    bounded: bool,
) -> list[EvidenceRecord]:
    raw_records = payload.get("results")
    if not isinstance(raw_records, Sequence) or isinstance(
        raw_records, (str, bytes, bytearray)
    ):
        return []
    records: list[EvidenceRecord] = []
    resolved_records = list(raw_records)[:100] if bounded else raw_records
    for raw in resolved_records:
        if not isinstance(raw, Mapping):
            continue
        required = {
            "evidence_id",
            "source_ref",
            "record_id",
            "locator",
            "source_hash",
        }
        if not required.issubset(raw):
            continue
        safe_ref = _safe_source_ref(str(raw.get("source_ref") or ""))
        if safe_ref is None:
            continue
        try:
            bounded_data = (
                _bounded_value(raw.get("data", {}), depth=0)
                if bounded
                else _sanitize_model_value(
                    raw.get("data", {}),
                    depth=0,
                    bounded=False,
                )
            )
            records.append(
                EvidenceRecord.model_validate(
                    {
                        **{
                            key: raw.get(key)
                            for key in (
                                "evidence_id",
                                "record_id",
                                "locator",
                                "source_hash",
                                "observed_at",
                                "valid_from",
                                "valid_to",
                                "candidate_only",
                                "runtime_safety_truth",
                            )
                            if key in raw
                        },
                        "data": bounded_data if isinstance(bounded_data, dict) else {},
                        "source_ref": safe_ref,
                    }
                )
            )
        except (TypeError, ValueError):
            continue
    return records


def _is_sensitive_key(value: object) -> bool:
    normalized = str(value).casefold()
    return any(fragment in normalized for fragment in _SENSITIVE_KEY_FRAGMENTS)


def _safe_source_ref(value: str) -> str | None:
    ref = value.strip()
    if not ref or ref == _REDACTED_VALUE:
        return None
    if "://" not in ref:
        path = Path(ref)
        if path.is_absolute() or ".." in path.parts:
            return None
        if any(part.startswith(".") for part in path.parts):
            return None
        return path.as_posix()
    parsed = urlsplit(ref)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _answer_sentences(answer: str) -> list[str]:
    sentences = re.split(r"(?<=[.!?。！？])(?:\s+|$)|\n+", answer)
    return [
        sentence.strip()
        for sentence in sentences
        if _TOKEN_PATTERN.search(_strip_citations(sentence))
    ]


def _citation_refs(value: str) -> list[str]:
    return [
        ref
        for match in _CITATION_PATTERN.finditer(value)
        if (ref := (match.group(1) or match.group(2)).strip())
        and _looks_like_citation_ref(ref)
    ]


def _strip_citations(value: str) -> str:
    return _CITATION_PATTERN.sub(
        lambda match: (
            ""
            if _looks_like_citation_ref(
                (match.group(1) or match.group(2)).strip()
            )
            else match.group(0)
        ),
        value,
    )


def _looks_like_citation_ref(value: str) -> bool:
    """Distinguish provenance refs from numeric arrays such as route bbox."""

    return bool(re.search(r"[A-Za-z_\u3400-\u9fff]", value))


def _first_verified_citation_candidate(
    sentence: str,
    *,
    evidence_cards: Sequence[EvidenceCard],
) -> str | None:
    ordered_cards = sorted(
        enumerate(evidence_cards),
        key=lambda item: (-_field_answer_priority(item[1]), item[0]),
    )
    for _, card in ordered_cards:
        for source_ref in card.source_refs:
            candidate = _append_source_ref(sentence, source_ref)
            if BoundedAgentRuntime.verify_synthesis(
                candidate,
                evidence_cards=[card],
            ).passed:
                return candidate
        for record in card.evidence_records:
            candidate = _append_source_ref(
                sentence,
                f"evidence:{record.evidence_id}",
            )
            if BoundedAgentRuntime.verify_synthesis(
                candidate,
                evidence_cards=[card],
            ).passed:
                return candidate
    return None


def _field_answer_priority(card: EvidenceCard) -> int:
    try:
        return max(0, min(100, int(card.key_values.get("field_answer_priority", 0))))
    except (TypeError, ValueError):
        return 0


def _priority_field_answer_source_refs(card: EvidenceCard) -> list[str]:
    key_values = card.key_values
    refs: list[str] = []
    preferred_many = key_values.get("field_answer_source_refs")
    if isinstance(preferred_many, list):
        refs.extend(
            str(item).strip()
            for item in preferred_many
            if str(item).strip() in card.source_refs
        )
    preferred_one = str(key_values.get("field_answer_source_ref") or "").strip()
    if preferred_one and preferred_one in card.source_refs:
        refs.insert(0, preferred_one)
    refs.extend(card.source_refs)
    return _dedupe(refs)


def _append_source_ref(sentence: str, source_ref: str) -> str:
    citation = f" [{source_ref}]"
    if sentence and sentence[-1] in ".!?。！？":
        return f"{sentence[:-1].rstrip()}{citation}{sentence[-1]}"
    return f"{sentence.rstrip()}{citation}"


def _claim_has_evidence_overlap(
    sentence: str,
    evidence_cards: Sequence[EvidenceCard],
) -> bool:
    claim_text = _strip_citations(sentence)
    claim_tokens = _search_tokens(claim_text)
    informative = {
        token
        for token in claim_tokens - _GROUNDING_STOP_WORDS
        if _NUMBER_PATTERN.fullmatch(token) is None
    }
    if not informative:
        return True
    evidence_text = _grounding_evidence_text(evidence_cards)
    if not _safety_concepts(claim_text).issubset(_safety_concepts(evidence_text)):
        return False
    if _safety_polarity_conflicts(claim_text, evidence_text):
        return False
    if _availability_polarity_conflicts(claim_text, evidence_text):
        return False
    claim_concepts = _grounding_concepts(claim_text)
    evidence_concepts = _grounding_concepts(evidence_text)
    if claim_concepts and claim_concepts.issubset(evidence_concepts):
        return True
    evidence_tokens = _search_tokens(evidence_text)
    overlap_count = len(informative & evidence_tokens)
    return overlap_count >= 2 or overlap_count / len(informative) >= 0.34


def _safety_polarity_conflicts(claim: str, evidence: str) -> bool:
    claim_polarity = _safety_polarity(claim)
    evidence_polarity = _safety_polarity(evidence)
    return bool(
        (
            claim_polarity["safe"]
            and evidence_polarity["unsafe"]
        )
        or (
            claim_polarity["unsafe"]
            and evidence_polarity["safe"]
            and not evidence_polarity["unsafe"]
        )
        or (
            claim_polarity["no_risk"]
            and evidence_polarity["risk"]
        )
        or (
            claim_polarity["risk"]
            and evidence_polarity["no_risk"]
            and not evidence_polarity["risk"]
        )
    )


def _availability_polarity_conflicts(claim: str, evidence: str) -> bool:
    normalized_claim = re.sub(r"\s+", " ", claim.casefold())
    normalized_evidence = re.sub(r"\s+", " ", evidence.casefold())
    denies_saved_evidence = bool(
        re.search(r"未保存|沒有保存|無保存|not stored|no saved", normalized_claim)
    )
    explicitly_live_only = bool(
        re.search(r"live|即時|即刻|現場", normalized_claim)
    )
    confirms_saved_evidence = bool(
        re.search(
            r"saved trace evidence|已保存|有保存|record_count['\" :]?\s*[1-9]",
            normalized_evidence,
        )
    )
    return denies_saved_evidence and not explicitly_live_only and confirms_saved_evidence


def _safety_polarity(value: str) -> dict[str, bool]:
    normalized = value.casefold()
    unsafe_phrases = (
        "not safe",
        "isn't safe",
        "is not safe",
        "unsafe",
        "dangerous",
        "hazardous",
        "不安全",
        "並不安全",
        "不是安全",
        "危險",
    )
    no_risk_phrases = (
        "no risk",
        "without risk",
        "not risky",
        "沒有風險",
        "無風險",
        "不具風險",
    )
    unsafe = any(phrase in normalized for phrase in unsafe_phrases)
    no_risk = any(phrase in normalized for phrase in no_risk_phrases)
    positive_text = normalized
    for phrase in (*unsafe_phrases, *no_risk_phrases):
        positive_text = positive_text.replace(phrase, "")
    safe = bool(re.search(r"\bsafe(?:ly)?\b", positive_text)) or (
        "安全" in positive_text
    )
    risk = (
        bool(re.search(r"\b(?:risk|risks|risky|hazard|danger)\b", positive_text))
        or "風險" in positive_text
        or "危害" in positive_text
    )
    return {
        "safe": safe,
        "unsafe": unsafe,
        "risk": risk,
        "no_risk": no_risk,
    }


def _grounding_evidence_text(evidence_cards: Sequence[EvidenceCard]) -> str:
    claim_payloads = [
        {
            "tool_id": card.tool_id,
            "claim_summary": card.claim_summary,
            "freshness": card.freshness,
            "key_values": card.key_values,
            "missing_fields": card.missing_fields,
            "quality": card.quality,
            "result_count": card.result_count,
            "source_refs": card.source_refs,
            "evidence_records": [
                item.model_dump(mode="json") for item in card.evidence_records
            ],
        }
        for card in evidence_cards
    ]
    return _json_dumps(claim_payloads)


def _missing_priority_exact_field_facts(
    answer: str,
    evidence_cards: Sequence[EvidenceCard],
) -> list[str]:
    answer_folded = answer.casefold()
    required: list[str] = []
    for card in evidence_cards:
        priority = card.key_values.get("field_answer_priority")
        try:
            is_exact = int(priority or 0) >= 100
        except (TypeError, ValueError):
            is_exact = False
        field_answer = str(card.key_values.get("field_answer") or "").strip()
        if not is_exact or not field_answer:
            continue
        required.extend(_priority_exact_field_literals(field_answer))
    return _dedupe(
        literal
        for literal in required
        if literal.casefold() not in answer_folded
    )


def _missing_priority_exact_field_sources(
    answer: str,
    evidence_cards: Sequence[EvidenceCard],
) -> list[str]:
    cited = set(_citation_refs(answer))
    missing: list[str] = []
    for card in evidence_cards:
        if _field_answer_priority(card) < 100:
            continue
        key_values = card.key_values
        preferred: list[str] = []
        preferred_many = key_values.get("field_answer_source_refs")
        if isinstance(preferred_many, list):
            preferred.extend(
                str(item).strip()
                for item in preferred_many
                if str(item).strip() in card.source_refs
            )
        preferred_one = str(
            key_values.get("field_answer_source_ref") or ""
        ).strip()
        if preferred_one and preferred_one in card.source_refs:
            preferred.insert(0, preferred_one)
        preferred = _dedupe(preferred)
        if preferred and not cited.intersection(preferred):
            missing.append(preferred[0])
    return _dedupe(missing)


def _priority_exact_field_literals(value: str) -> list[str]:
    patterns = (
        r"\b(?:seg|cp|mcp)\.[A-Za-z0-9_.-]+",
        r"\b[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+){2,}\b",
        r"\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b",
        r"(?<![A-Za-z0-9_.])\d+(?:\.\d+)?(?:%|K|km|m)?\b",
    )
    return _dedupe(
        match.group(0)
        for pattern in patterns
        for match in re.finditer(pattern, value, flags=re.IGNORECASE)
    )


def _grounding_concepts(value: str) -> set[str]:
    normalized = value.casefold().replace(" ", "")
    concepts = {
        concept
        for concept, aliases in _GROUNDING_CONCEPT_ALIASES.items()
        if any(alias.casefold().replace(" ", "") in normalized for alias in aliases)
    }
    if len(concepts) > 1:
        concepts.discard("route")
    return concepts


def _number_is_grounded(number: str, evidence_numbers: set[str]) -> bool:
    try:
        claim_value = float(number)
    except ValueError:
        return False
    for raw in evidence_numbers:
        try:
            evidence_value = float(raw)
        except ValueError:
            continue
        if math.isclose(claim_value, evidence_value, rel_tol=1e-3, abs_tol=0.02):
            return True
    return False


def _safety_concepts(value: str) -> set[str]:
    normalized = value.casefold()
    tokens = _search_tokens(normalized)
    concepts = {
        concept
        for concept, aliases in _SAFETY_CONCEPT_TOKENS.items()
        if tokens & aliases
    }
    for concept, phrases in _SAFETY_CONCEPT_PHRASES.items():
        searchable = normalized
        if concept == "safe":
            searchable = searchable.replace("不安全", "")
        if any(phrase in searchable for phrase in phrases):
            concepts.add(concept)
    return concepts


def _claim_summary(payload: Mapping[str, Any]) -> str:
    for key in ("field_answer", "claim_summary", "answer", "summary", "message"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    status = str(payload.get("status") or "unknown")
    kind = str(payload.get("artifact_kind") or payload.get("output_artifact_kind") or "evidence")
    return f"{kind}: status={status}"


def _result_count(payload: Mapping[str, Any]) -> int:
    for key in ("result_count", "count"):
        value = payload.get(key)
        if isinstance(value, int) and value >= 0:
            return value
    results = payload.get("results")
    return len(results) if isinstance(results, list) else 0


def _freshness(payload: Mapping[str, Any]) -> str:
    value = payload.get("freshness") or payload.get("stale_risk")
    if isinstance(value, str) and value.strip():
        return value.strip()
    if payload.get("stale") is True:
        return "stale"
    return "unknown"


def _quality(payload: Mapping[str, Any]) -> str:
    value = payload.get("quality") or payload.get("confidence")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "high" if payload.get("status") == "completed" else "unknown"


def _budget_stop_reason(
    budget: AgentRunBudget,
    request_count: int,
    totals: Mapping[str, int | float],
) -> str | None:
    if budget.enforce_resource_limits:
        if (
            budget.max_input_tokens is not None
            and int(totals["input_tokens"]) > budget.max_input_tokens
        ):
            return "input_tokens budget exceeded"
        if (
            budget.max_output_tokens is not None
            and int(totals["output_tokens"]) > budget.max_output_tokens
        ):
            return "output_tokens budget exceeded"
        if (
            budget.max_total_tokens is not None
            and int(totals["input_tokens"]) + int(totals["output_tokens"])
            > budget.max_total_tokens
        ):
            return "total_tokens budget exceeded"
    if int(totals["tool_call_count"]) > budget.max_tool_calls:
        return "tool_call_count budget exceeded"
    if int(totals["repair_count"]) > budget.max_repairs:
        return "repair_count budget exceeded"
    if (
        budget.enforce_resource_limits
        and budget.max_estimated_cost is not None
        and float(totals["estimated_cost"]) > budget.max_estimated_cost
    ):
        return "estimated_cost budget exceeded"
    if request_count > budget.max_requests:
        return "request_count budget exceeded"
    return None


def _remaining_optional_limit(limit: int | None, used: int) -> int | None:
    return None if limit is None else max(0, limit - used)


def _continuation_handle(kind: str, identity: str, payload: str) -> str:
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]
    return f"{kind}:{identity}:{digest}"


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return _dedupe([str(item) for item in value if str(item).strip()])


def _dedupe(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


__all__ = ["BoundedAgentRuntime", "estimate_tokens"]
