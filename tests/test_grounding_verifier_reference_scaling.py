from __future__ import annotations

import re

import pytest

from scout.schemas.agent_runtime import EvidenceCard
from scout.services import bounded_agent_runtime as runtime


def test_unsupported_claim_is_not_retokenized_for_every_alias(monkeypatch):
    card = EvidenceCard(
        tool_id="workspace.catalog",
        claim_summary="A route catalog.",
        key_values={"route_name": "Example route", "distance_km": 36.5},
        source_refs=[f"outputs/catalog/{chr(97 + i)}.json" for i in range(20)],
    )
    original = runtime.BoundedAgentRuntime.verify_synthesis
    calls = []

    def verify(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(runtime.BoundedAgentRuntime, "verify_synthesis", verify)
    result = runtime._first_verified_citation_candidate(
        "A spacecraft landed on Mars.", evidence_cards=[card]
    )
    assert result is None
    assert len(calls) == 1


def test_reference_specific_failure_still_checks_the_required_source():
    card = EvidenceCard(
        tool_id="route",
        claim_summary="Route distance is 36.5 km.",
        key_values={
            "field_answer": "Route distance is 36.5 km.",
            "field_answer_priority": 100,
            "field_answer_source_ref": "outputs/primary.json",
        },
        source_refs=["outputs/secondary.json", "outputs/primary.json"],
    )
    result = runtime._first_verified_citation_candidate(
        "Route distance is 36.5 km.", evidence_cards=[card]
    )
    assert result is not None and "outputs/primary.json" in result
    assert runtime.BoundedAgentRuntime.verify_synthesis(
        result, evidence_cards=[card]
    ).passed


def test_attachment_preserves_model_named_source_instead_of_incidental_alias():
    card = EvidenceCard(
        tool_id="route",
        key_values={"route_name": "Example route", "distance_km": 36.5},
        source_refs=[
            "outputs/resume_segments.json",
            "normalized/routes/route_summary.json",
        ],
    )
    raw = "Example route is 36.5 km. Source: `normalized/routes/route_summary.json`."
    answer = runtime.BoundedAgentRuntime.attach_verified_source_refs(
        raw, evidence_cards=[card]
    )
    assert "[normalized/routes/route_summary.json]" in answer
    assert "outputs/resume_segments.json" not in answer
    assert runtime.BoundedAgentRuntime.verify_synthesis(
        answer, evidence_cards=[card]
    ).passed


def test_model_source_preference_never_validates_an_unsupported_quantity():
    card = EvidenceCard(
        tool_id="route",
        key_values={"distance_km": 36.5},
        source_refs=["normalized/routes/route_summary.json"],
    )
    raw = "Route distance is 999 km. Source: `normalized/routes/route_summary.json`."
    assert (
        runtime.BoundedAgentRuntime.attach_verified_source_refs(
            raw, evidence_cards=[card]
        )
        == raw
    )


def test_existing_citation_is_not_rewritten_by_attachment():
    card = EvidenceCard(
        tool_id="route",
        key_values={"distance_km": 36.5},
        source_refs=["outputs/other.json", "normalized/routes/route_summary.json"],
    )
    raw = "Route distance is 36.5 km [normalized/routes/route_summary.json]."
    assert (
        runtime.BoundedAgentRuntime.attach_verified_source_refs(
            raw, evidence_cards=[card]
        )
        == raw
    )


@pytest.mark.parametrize("formatted", ["4,439", "4,439.0", "4439.0"])
def test_grouped_numeric_claim_is_one_quantity(formatted):
    card = EvidenceCard(
        tool_id="route",
        key_values={"total_ascent_m": 4439.0},
        source_refs=["normalized/routes/route_summary.json"],
    )
    result = runtime.BoundedAgentRuntime.verify_synthesis(
        f"Total ascent is {formatted} m [normalized/routes/route_summary.json].",
        evidence_cards=[card],
    )
    assert result.passed, result.repair_items


def test_grouped_numeric_claim_cannot_borrow_separate_numbers():
    card = EvidenceCard(
        tool_id="route",
        key_values={"section_count": 4, "total_ascent_m": 439},
        source_refs=["normalized/routes/route_summary.json"],
    )
    result = runtime.BoundedAgentRuntime.verify_synthesis(
        "Total ascent is 4,439 m [normalized/routes/route_summary.json].",
        evidence_cards=[card],
    )
    assert not result.passed


@pytest.mark.parametrize(
    "source_value,claim_value", [("4,439m", "4439m"), ("4439m", "4,439m")]
)
def test_exact_numeric_evidence_accepts_grouping_only(source_value, claim_value):
    card = EvidenceCard(
        tool_id="route",
        key_values={
            "field_answer": f"Total ascent is {source_value}.",
            "field_answer_priority": 100,
            "field_answer_source_ref": "outputs/route.json",
        },
        source_refs=["outputs/route.json"],
    )
    result = runtime.BoundedAgentRuntime.verify_synthesis(
        f"Total ascent is {claim_value} [outputs/route.json].", evidence_cards=[card]
    )
    assert result.passed, result.repair_items


@pytest.mark.parametrize(
    "value",
    [
        "雨量與高山道路" * 1000,
        "cp.042_path-ids recorded road slopes 0.0",
        "",
        "— 山_路",
    ],
)
def test_tokenization_preserves_existing_grounding_semantics(value):
    expected = set()
    for raw in runtime._TOKEN_PATTERN.findall(value.casefold()):
        for piece in [raw, *re.split(r"[_.-]+", raw)]:
            if not piece:
                continue
            expected.add(piece)
            if len(piece) > 3 and piece.endswith("s"):
                expected.add(piece[:-1])
            if len(piece) > 4 and piece.endswith("ed"):
                expected.update((piece[:-1], piece[:-2]))
    assert runtime._search_tokens(value) == expected
