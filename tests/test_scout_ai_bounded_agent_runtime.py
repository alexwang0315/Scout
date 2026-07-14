from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from scout.schemas.agent_runtime import (
    AgentRequestLedger,
    AgentRunBudget,
    AgentRunLedger,
    ContextHandle,
    EvidenceCard,
    PlannedToolCall,
    ToolCard,
    ToolPlan,
)
from scout.services.bounded_agent_runtime import BoundedAgentRuntime


def _context_handle(index: int, *, relevance: float = 0.5) -> ContextHandle:
    return ContextHandle(
        context_id=f"context-{index}",
        domain_id="route",
        artifact_kind="route_summary",
        title=f"Route summary {index}",
        source_ref=f"outputs/route/summary-{index}.json",
        observed_at=datetime(2026, 7, 13, tzinfo=UTC),
        freshness="fresh",
        scope_metadata={"project_id": "fixture"},
        time_metadata={"window": "pretrip"},
        spatial_metadata={"route_km": index},
        relevance_score=relevance,
        estimated_tokens=40,
        sensitivity="internal",
    )


def _tool_card(index: int, *, purpose: str | None = None) -> ToolCard:
    return ToolCard(
        tool_id=f"scout.tool.{index}.v0",
        purpose=purpose or f"Find route checkpoint evidence {index}",
        required_inputs=["query", "project_root"],
        output_artifact_kind="scout_tool_evidence",
        risk_level="low",
        estimated_cost=0.0,
        availability="available",
        implementation_status="ready_current_tool",
    )


def _evidence_card(
    *,
    claim_summary: str,
    source_ref: str,
    key_values: dict[str, object],
) -> EvidenceCard:
    return EvidenceCard(
        tool_id="scout.tool.fixture.v0",
        claim_summary=claim_summary,
        key_values=key_values,
        source_refs=[source_ref],
    )


def test_runtime_contracts_are_small_and_preserve_safety_boundary() -> None:
    handle = _context_handle(1)
    card = _tool_card(1)

    assert handle.candidate_only is True
    assert handle.runtime_safety_truth is False
    assert card.model_dump().keys().isdisjoint(
        {"argument_schema", "input_schema", "json_schema", "policy"}
    )
    assert len(card.model_dump_json()) < 600

    with pytest.raises(ValidationError):
        ContextHandle.model_validate(
            {
                **handle.model_dump(mode="json"),
                "runtime_safety_truth": True,
            }
        )


def test_tool_plan_rejects_more_than_five_tools() -> None:
    calls = [
        PlannedToolCall(
            tool_id=f"scout.tool.{index}.v0",
            arguments={"query": "route"},
            reason="Required evidence",
            expected_evidence=["route evidence"],
        )
        for index in range(6)
    ]

    with pytest.raises(ValidationError, match="at most 5"):
        ToolPlan(
            selected_tool_ids=[call.tool_id for call in calls],
            tool_calls=calls,
            estimated_input_tokens=1000,
            estimated_output_tokens=500,
            required_bundle_expansion=[],
            stop_or_replan_condition="Stop when evidence is sufficient.",
        )


def test_context_find_is_top_k_and_token_bounded_at_ten_x_growth() -> None:
    handles = [
        _context_handle(index, relevance=1.0 if index == 7 else 0.1)
        for index in range(100)
    ]
    runtime = BoundedAgentRuntime(context_handles=handles)

    selected = runtime.context_find(
        "route summary 7 checkpoint",
        filters={"domain_id": "route"},
        top_k=3,
        token_budget=100,
    )

    assert selected[0].context_id == "context-7"
    assert len(selected) <= 3
    assert sum(item.estimated_tokens for item in selected) <= 100
    assert runtime.last_context_catalog_scan_count == 100
    assert runtime.last_context_returned_tokens <= 100


def test_context_find_returns_no_handle_when_query_has_zero_relevance() -> None:
    runtime = BoundedAgentRuntime(context_handles=[_context_handle(index) for index in range(10)])

    selected = runtime.context_find("嗨", top_k=3, token_budget=200)

    assert selected == []


def test_context_find_can_match_compact_scope_metadata() -> None:
    handle = _context_handle(1).model_copy(
        update={
            "scope_metadata": {
                "tool_ids": ["pydantic_ai.tool.search_scout_route_structure.v0"]
            }
        }
    )
    runtime = BoundedAgentRuntime(context_handles=[handle])

    selected = runtime.context_find(
        "pydantic_ai.tool.search_scout_route_structure.v0",
        top_k=3,
        token_budget=200,
    )

    assert [item.context_id for item in selected] == [handle.context_id]


def test_context_find_prioritizes_exact_selected_tool_scope_over_generic_overlap() -> None:
    weather = _context_handle(1, relevance=0.1).model_copy(
        update={
            "context_id": "weather",
            "domain_id": "weather",
            "title": "Weather evidence",
            "scope_metadata": {
                "tool_ids": ["scout.ai.weather_window.assess.v0"]
            },
        }
    )
    route = _context_handle(2, relevance=1.0).model_copy(
        update={
            "context_id": "route",
            "scope_metadata": {
                "tool_ids": ["scout.ai.route_architecture.assess.v0"]
            },
        }
    )
    runtime = BoundedAgentRuntime(context_handles=[route, weather])

    selected = runtime.context_find(
        "terrain question scout.ai.weather_window.assess.v0",
        top_k=2,
        token_budget=200,
    )

    assert selected[0].context_id == "weather"


def test_context_read_returns_a_bounded_slice_with_continuation() -> None:
    handle = _context_handle(1)
    runtime = BoundedAgentRuntime(
        context_handles=[handle],
        context_payloads={handle.context_id: {"records": ["x" * 600 for _ in range(20)]}},
    )

    result = runtime.context_read(handle.context_id, selector="records", token_budget=120)

    assert result.context_id == handle.context_id
    assert result.estimated_tokens <= 120
    assert result.truncated is True
    assert result.continuation_handle
    assert result.source_ref == handle.source_ref
    assert "x" * 600 not in result.model_dump_json()


def test_tool_find_never_loads_all_schemas_when_catalog_grows_ten_x() -> None:
    cards = [
        _tool_card(
            index,
            purpose=(
                "Find checkpoint and route structure evidence"
                if index == 17
                else f"Unrelated capability {index}"
            ),
        )
        for index in range(270)
    ]
    runtime = BoundedAgentRuntime(
        tool_cards=cards,
        tool_schemas={card.tool_id: {"type": "object", "marker": card.tool_id} for card in cards},
    )

    selected = runtime.tool_find(
        intent="checkpoint route structure",
        domain="route",
        risk="low",
        top_k=3,
    )
    described = runtime.tool_describe([card.tool_id for card in selected])

    assert selected[0].tool_id == "scout.tool.17.v0"
    assert len(selected) <= 3
    assert set(described) == {card.tool_id for card in selected}
    assert runtime.last_described_tool_count <= 3
    assert runtime.last_described_tool_count < len(cards)


def test_tool_find_returns_no_tools_when_every_card_has_zero_relevance() -> None:
    runtime = BoundedAgentRuntime(tool_cards=[_tool_card(index) for index in range(20)])

    selected = runtime.tool_find(
        intent="嗨",
        domain="pretrip",
        risk="low",
        top_k=3,
    )

    assert selected == []


def test_tool_result_is_compacted_to_evidence_card_without_raw_payload() -> None:
    runtime = BoundedAgentRuntime()
    result = {
        "status": "completed",
        "field_answer": "CP 12 is the highest candidate risk point.",
        "results": [
            {
                "cp": index,
                "score": 99.5 - index,
                "detail": "large detail " * 300,
            }
            for index in range(30)
        ],
        "missing_fields": ["issued_at"],
        "sources": [
            {"source_ref": "outputs/risk/risk_score_points.geojson"},
            {"source_path": "outputs/weather/cwa_summary.json"},
        ],
        "candidate_only": True,
        "runtime_safety_truth": False,
    }

    card = runtime.evidence_from_tool_result(
        "pydantic_ai.tool.search_scout_risk_scores.v0",
        result,
        token_budget=220,
    )

    assert isinstance(card, EvidenceCard)
    assert card.estimated_tokens <= 220
    assert card.truncated is True
    assert card.continuation_handle
    assert card.source_refs == [
        "outputs/risk/risk_score_points.geojson",
        "outputs/weather/cwa_summary.json",
    ]
    assert card.missing_fields == ["issued_at"]
    assert card.candidate_only is True
    assert card.runtime_safety_truth is False
    assert "large detail " * 30 not in card.model_dump_json()


def test_bounded_evidence_redacts_sensitive_keys_and_source_query_strings() -> None:
    runtime = BoundedAgentRuntime()

    card = runtime.evidence_from_tool_result(
        "scout.tool.safe_projection.v0",
        {
            "status": "completed",
            "claim_summary": "Prepared evidence is available.",
            "api_key": "must-not-appear",
            "access_token": "must-not-appear",
            "password": "must-not-appear",
            "source_ref": "https://example.test/evidence.json?token=must-not-appear",
        },
    )

    serialized = card.model_dump_json()
    assert "must-not-appear" not in serialized
    assert "api_key" not in card.key_values
    assert "access_token" not in card.key_values
    assert "password" not in card.key_values
    assert card.source_refs == ["https://example.test/evidence.json"]


def test_bounded_evidence_never_reintroduces_secret_values_in_truncated_preview() -> None:
    runtime = BoundedAgentRuntime()

    card = runtime.evidence_from_tool_result(
        "scout.tool.safe_projection.v0",
        {
            "status": "completed",
            "claim_summary": "Prepared evidence is available.",
            "innocent_note": "Bearer must-not-appear-secret-token",
            "oversized": "route evidence " * 2_000,
            "source_ref": "outputs/route/summary.json",
        },
        token_budget=80,
    )

    serialized = card.model_dump_json()
    assert card.truncated is True
    assert "must-not-appear-secret-token" not in serialized
    assert "Bearer" not in serialized
    assert "preview" not in card.key_values


def test_bounded_evidence_rejects_credentialed_urls_and_withholds_private_cards() -> None:
    runtime = BoundedAgentRuntime()

    card = runtime.evidence_from_tool_result(
        "scout.tool.private.v0",
        {
            "status": "completed",
            "sensitivity": "private",
            "field_answer": "heart rate 170 and token sk-must-not-appear",
            "source_ref": "https://user:password@example.test/private.json?token=x",
        },
    )

    serialized = card.model_dump_json()
    assert "170" not in serialized
    assert "must-not-appear" not in serialized
    assert "password" not in serialized
    assert card.source_refs == []
    assert card.missing_fields == ["private_evidence_withheld"]


def test_evidence_card_preserves_nested_source_path_mapping() -> None:
    runtime = BoundedAgentRuntime()

    card = runtime.evidence_from_tool_result(
        "pydantic_ai.tool.search_scout_route_structure.v0",
        {
            "status": "completed",
            "summaries": {
                "checkpoint_count": 124,
                "source_paths": {
                    "route_summary": "normalized/routes/route_summary.json",
                    "checkpoints": "candidates/checkpoints.json",
                },
            },
        },
    )

    assert card.source_refs == [
        "normalized/routes/route_summary.json",
        "candidates/checkpoints.json",
    ]


def test_request_ledger_aggregates_overhead_and_stops_over_budget() -> None:
    budget = AgentRunBudget(
        max_requests=2,
        max_tool_calls=3,
        max_input_tokens=2000,
        max_output_tokens=500,
        max_total_tokens=2400,
        max_repairs=1,
        max_tool_result_tokens=800,
        max_estimated_cost=0.05,
    )
    runtime = BoundedAgentRuntime(budget=budget)
    ledger = AgentRunLedger(budget=budget)
    ledger = runtime.record_request(
        ledger,
        AgentRequestLedger(
            request_index=1,
            system_chars=1000,
            tool_schema_chars=1200,
            user_history_chars=800,
            tool_result_chars=0,
            input_tokens=900,
            cache_write_tokens=0,
            cache_read_tokens=100,
            output_tokens=120,
            tool_call_count=2,
            estimated_cost=0.01,
        ),
        selected_tool_ids=["a", "b"],
        executed_tool_ids=["a", "b"],
    )

    assert ledger.request_count == 1
    assert ledger.tool_call_count == 2
    assert ledger.tool_schema_chars == 1200
    assert ledger.input_tokens == 900
    assert ledger.cache_read_tokens == 100
    assert ledger.selected_tool_ids == ["a", "b"]
    assert ledger.executed_tool_ids == ["a", "b"]
    assert ledger.budget_stop_reason is None
    assert ledger.budget_remaining["input_tokens"] == 1100

    stopped = runtime.record_request(
        ledger,
        AgentRequestLedger(
            request_index=2,
            system_chars=1000,
            tool_schema_chars=0,
            user_history_chars=900,
            tool_result_chars=700,
            input_tokens=1300,
            cache_write_tokens=0,
            cache_read_tokens=0,
            output_tokens=200,
            tool_call_count=2,
            estimated_cost=0.02,
        ),
        executed_tool_ids=["c", "d"],
    )

    assert stopped.budget_stop_reason
    assert "input_tokens" in stopped.budget_stop_reason
    assert runtime.can_continue(stopped) is False


def test_no_tool_synthesis_prompt_and_citation_verifier_are_bounded() -> None:
    runtime = BoundedAgentRuntime()
    evidence = EvidenceCard(
        tool_id="scout.tool.route.v0",
        claim_summary="The route has 12 checkpoints.",
        key_values={"checkpoint_count": 12},
        missing_fields=[],
        freshness="fresh",
        quality="high",
        source_refs=["outputs/route/summary.json"],
        result_count=1,
        estimated_tokens=50,
    )

    prompt = runtime.build_no_tool_synthesis_prompt(
        question="How many checkpoints are there?",
        evidence_cards=[evidence],
        missing_evidence=[],
        token_budget=400,
    )

    assert "tool schema" not in prompt.lower()
    assert "arguments" not in prompt.lower()
    assert "outputs/route/summary.json" in prompt
    assert len(prompt) <= 1600

    passed = runtime.verify_synthesis(
        "There are 12 checkpoints [outputs/route/summary.json].",
        evidence_cards=[evidence],
    )
    failed = runtime.verify_synthesis(
        "There are 14 checkpoints.",
        evidence_cards=[evidence],
    )
    uncited_text = runtime.verify_synthesis(
        "The route crosses a steep exposed ridge.",
        evidence_cards=[evidence],
    )
    cited_but_unsupported_text = runtime.verify_synthesis(
        "The route crosses a steep exposed ridge [outputs/route/summary.json].",
        evidence_cards=[evidence],
    )

    assert passed.passed is True
    assert passed.unsupported_claims == []
    assert failed.passed is False
    assert failed.unsupported_claims
    assert uncited_text.passed is False
    assert uncited_text.unsupported_claims
    assert cited_but_unsupported_text.passed is False
    assert cited_but_unsupported_text.unsupported_claims


def test_synthesis_verifier_validates_numbers_only_against_cited_cards() -> None:
    runtime = BoundedAgentRuntime()
    twelve_checkpoints = _evidence_card(
        claim_summary="The route has 12 checkpoints.",
        source_ref="outputs/route/twelve.json",
        key_values={"checkpoint_count": 12},
    )
    fourteen_checkpoints = _evidence_card(
        claim_summary="The alternate route has 14 checkpoints.",
        source_ref="outputs/route/fourteen.json",
        key_values={"checkpoint_count": 14},
    )

    wrong_card = runtime.verify_synthesis(
        "There are 14 checkpoints [outputs/route/twelve.json].",
        evidence_cards=[twelve_checkpoints, fourteen_checkpoints],
    )
    right_card = runtime.verify_synthesis(
        "There are 14 checkpoints [outputs/route/fourteen.json].",
        evidence_cards=[twelve_checkpoints, fourteen_checkpoints],
    )

    assert wrong_card.passed is False
    assert wrong_card.unsupported_claims == [
        "There are 14 checkpoints [outputs/route/twelve.json]."
    ]
    assert right_card.passed is True


def test_synthesis_verifier_rejects_matching_number_for_unrelated_fact() -> None:
    runtime = BoundedAgentRuntime()
    checkpoint_evidence = _evidence_card(
        claim_summary="The route has 12 checkpoints.",
        source_ref="outputs/route/summary.json",
        key_values={"checkpoint_count": 12},
    )

    verification = runtime.verify_synthesis(
        "There were 12 fatalities [outputs/route/summary.json].",
        evidence_cards=[checkpoint_evidence],
    )

    assert verification.passed is False
    assert verification.unsupported_claims == [
        "There were 12 fatalities [outputs/route/summary.json]."
    ]


def test_synthesis_verifier_fails_closed_for_unsupported_safety_claim() -> None:
    runtime = BoundedAgentRuntime()
    checkpoint_evidence = _evidence_card(
        claim_summary="The route has 12 checkpoints.",
        source_ref="outputs/route/summary.json",
        key_values={"checkpoint_count": 12},
    )
    claim = "The route is safe [outputs/route/summary.json]."

    verification = runtime.verify_synthesis(
        claim,
        evidence_cards=[checkpoint_evidence],
    )

    assert verification.passed is False
    assert verification.output_disposition == "fail_closed"
    assert verification.unsupported_claims == [claim]
    assert verification.rejected_draft_claims == [claim]


def test_synthesis_verifier_rejects_safety_polarity_contradiction() -> None:
    runtime = BoundedAgentRuntime()
    route_evidence = _evidence_card(
        claim_summary="The route is not safe because of rockfall.",
        source_ref="outputs/risk/route-summary.json",
        key_values={"hazard": "rockfall", "assessment": "not safe"},
    )
    claim = (
        "The route is safe despite rockfall "
        "[outputs/risk/route-summary.json]."
    )

    verification = runtime.verify_synthesis(
        claim,
        evidence_cards=[route_evidence],
    )

    assert verification.passed is False
    assert verification.output_disposition == "fail_closed"
    assert verification.unsupported_claims == [claim]
    assert verification.rejected_draft_claims == [claim]


def test_synthesis_verifier_does_not_infer_safety_from_citation_path() -> None:
    runtime = BoundedAgentRuntime()
    checkpoint_evidence = _evidence_card(
        claim_summary="The route has 12 checkpoints.",
        source_ref="outputs/risk/route-summary.json",
        key_values={"checkpoint_count": 12},
    )

    verification = runtime.verify_synthesis(
        "There are 14 checkpoints [outputs/risk/route-summary.json].",
        evidence_cards=[checkpoint_evidence],
    )

    assert verification.passed is False
    assert verification.output_disposition == "needs_repair"
    assert verification.rejected_draft_claims == []


def test_synthesis_verifier_accepts_full_width_chinese_citation_brackets() -> None:
    runtime = BoundedAgentRuntime()
    evidence = EvidenceCard(
        tool_id="workspace.catalog",
        claim_summary="Workspace project identity.",
        key_values={"project_id": "chilai_nanhua_day1_scoutAI"},
        source_refs=["project.json"],
    )

    verification = runtime.verify_synthesis(
        "Project ID 是 chilai_nanhua_day1_scoutAI【project.json】。",
        evidence_cards=[evidence],
    )

    assert verification.passed is True
    assert verification.cited_source_refs == ["project.json"]
