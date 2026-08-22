from __future__ import annotations

from datetime import UTC, datetime

import pytest

from scout.schemas.agent_runtime import (
    AgentRunBudget,
    EvidenceCard,
    EvidenceRecord,
    ToolCard,
)
from scout.schemas.mser import (
    CompactDimension,
    MinimalToolPlan,
    PlannedCompactTool,
)
from scout.services.mser_runtime_adapter import (
    MSERRuntimeAdapter,
    UnknownMSERToolCapabilityError,
    build_tool_capabilities,
)
from scout_ai_tool_contracts import tool_registry_output


RISK_TOOL_ID = "pydantic_ai.tool.search_scout_risk_scores.v0"
CWA_TOOL_ID = "scout.ai.cwa_environment.assess.v0"


def _tool_card(tool_id: str) -> ToolCard:
    return ToolCard(
        tool_id=tool_id,
        purpose="Read bounded Scout evidence.",
        required_inputs=["project_root", "query"],
        output_artifact_kind="scout_ai_tool_output",
        risk_level="low",
        availability="available",
        implementation_status="ready_current_tool",
    )


def _minimal_plan() -> MinimalToolPlan:
    return MinimalToolPlan(
        selected_tools=(
            PlannedCompactTool(
                tool_id=RISK_TOOL_ID,
                fills_dimensions=(
                    CompactDimension.CURRENT_HAZARD,
                    CompactDimension.SLIP_RISK,
                ),
                reason="Fill terrain hazard gaps.",
            ),
            PlannedCompactTool(
                tool_id=CWA_TOOL_ID,
                fills_dimensions=(
                    CompactDimension.WEATHER_TREND,
                    CompactDimension.DANGER_WINDOW,
                ),
                reason="Fill current weather gaps.",
            ),
        ),
        uncovered_dimensions=(),
        coverage_complete=True,
        objective="Cover the unresolved MSER dimensions with read-only tools.",
        max_tool_calls=10,
    )


def test_registry_builds_known_read_only_capabilities_with_dimension_coverage() -> None:
    registry = tool_registry_output(include_not_implemented=False)

    capabilities = build_tool_capabilities(registry=registry)
    by_id = {capability.tool_id: capability for capability in capabilities}

    assert set(by_id) == {contract.tool_id for contract in registry.tools}
    assert CompactDimension.CURRENT_HAZARD in by_id[RISK_TOOL_ID].produces_dimensions
    assert CompactDimension.SLIP_RISK in by_id[RISK_TOOL_ID].produces_dimensions
    assert CompactDimension.WEATHER_TREND in by_id[CWA_TOOL_ID].produces_dimensions
    assert CompactDimension.DANGER_WINDOW in by_id[CWA_TOOL_ID].produces_dimensions
    assert all(capability.read_only is True for capability in capabilities)


def test_selected_tool_cards_build_only_selected_capabilities_and_reject_unknown() -> (
    None
):
    capabilities = build_tool_capabilities(
        selected_tool_cards=(_tool_card(RISK_TOOL_ID), _tool_card(CWA_TOOL_ID))
    )

    assert [capability.tool_id for capability in capabilities] == [
        RISK_TOOL_ID,
        CWA_TOOL_ID,
    ]

    with pytest.raises(UnknownMSERToolCapabilityError, match="unknown.tool.v0"):
        build_tool_capabilities(selected_tool_cards=(_tool_card("unknown.tool.v0"),))


def test_minimal_plan_becomes_bounded_plan_with_ten_call_capacity_and_expectations() -> (
    None
):
    adapter = MSERRuntimeAdapter(
        selected_tool_cards=(_tool_card(RISK_TOOL_ID), _tool_card(CWA_TOOL_ID)),
        budget=AgentRunBudget(max_tool_calls=10, max_requests=10),
    )

    plan = adapter.to_bounded_tool_plan(
        _minimal_plan(),
        arguments_by_tool={
            RISK_TOOL_ID: {"project_root": "/workspace", "query": "rain risk"},
            CWA_TOOL_ID: {"project_root": "/workspace", "query": "rain window"},
        },
    )

    assert adapter.budget.max_tool_calls == 10
    assert plan.selected_tool_ids == [RISK_TOOL_ID, CWA_TOOL_ID]
    assert "10-call" in plan.stop_or_replan_condition
    assert all("source_refs" in call.expected_evidence for call in plan.tool_calls)
    assert all("evidence_records" in call.expected_evidence for call in plan.tool_calls)
    assert "operation.current_hazard" in plan.tool_calls[0].expected_evidence
    assert "weather.danger_window" in plan.tool_calls[1].expected_evidence


def test_plan_rejects_dimensions_not_declared_by_tool_capability() -> None:
    adapter = MSERRuntimeAdapter(
        selected_tool_cards=(_tool_card(RISK_TOOL_ID),),
    )
    invalid = MinimalToolPlan(
        selected_tools=(
            PlannedCompactTool(
                tool_id=RISK_TOOL_ID,
                fills_dimensions=(CompactDimension.ENERGY_RESERVE,),
                reason="Invalid cross-domain claim.",
            ),
        ),
        uncovered_dimensions=(),
        coverage_complete=True,
        objective="Invalid fixture.",
        max_tool_calls=10,
    )

    with pytest.raises(ValueError, match="does not declare"):
        adapter.to_bounded_tool_plan(invalid)


def test_evidence_card_becomes_bounded_reprojection_payload_with_source_refs() -> None:
    adapter = MSERRuntimeAdapter(
        selected_tool_cards=(_tool_card(RISK_TOOL_ID),),
    )
    observed_at = datetime(2026, 7, 24, 1, 30, tzinfo=UTC)
    card = EvidenceCard(
        tool_id=RISK_TOOL_ID,
        claim_summary="Two rain-sensitive route points were found.",
        key_values={"max_score": 0.91, "risk_bucket": "very_high"},
        freshness="fresh",
        quality="verified",
        source_refs=[
            "outputs/risk/calibrated_risk_heatmap.geojson",
            "outputs/weather/route_weather_package.json",
        ],
        evidence_records=[
            EvidenceRecord(
                evidence_id="risk-point-17",
                source_ref="outputs/risk/calibrated_risk_heatmap.geojson",
                record_id="feature-17",
                locator="features[17]",
                source_hash="sha256:fixture",
                data={"score": 0.91},
                observed_at=observed_at,
            )
        ],
        result_count=2,
    )

    payload = adapter.to_reprojection_payload(card)

    assert payload.tool_id == RISK_TOOL_ID
    assert payload.reprojection_ready is True
    assert (
        payload.produces_dimensions
        == adapter.capability_for(RISK_TOOL_ID).produces_dimensions
    )
    assert payload.source_refs == tuple(card.source_refs)
    assert payload.evidence_records[0].source_ref == card.source_refs[0]
    assert payload.candidate_only is True
    assert payload.runtime_safety_truth is False


def test_raw_tool_output_is_bounded_and_missing_sources_fail_reprojection_gate() -> (
    None
):
    adapter = MSERRuntimeAdapter(
        selected_tool_cards=(_tool_card(CWA_TOOL_ID),),
    )

    payload = adapter.to_reprojection_payload(
        {
            "status": "completed",
            "summary": "Forecast evidence exists but has no source reference.",
            "weather_trend": "deteriorating",
        },
        tool_id=CWA_TOOL_ID,
    )

    assert payload.reprojection_ready is False
    assert "source_refs" in payload.missing_fields
    assert payload.source_refs == ()
    assert payload.runtime_safety_truth is False


def test_canonical_capability_lookup_does_not_rebuild_tool_contracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = MSERRuntimeAdapter(
        selected_tool_cards=(_tool_card(RISK_TOOL_ID),),
    )

    def fail_alias_resolution(_tool_id: str) -> str:
        raise AssertionError("canonical IDs must use the prebuilt capability index")

    monkeypatch.setattr(
        "scout.services.mser_runtime_adapter.resolve_scout_ai_tool_id",
        fail_alias_resolution,
    )

    capability = adapter.capability_for(RISK_TOOL_ID)
    payload = adapter.to_reprojection_payload(
        {
            "status": "completed",
            "quality": "verified",
            "source_refs": ["outputs/risk/calibrated_risk_heatmap.geojson"],
            "max_score": 0.91,
        },
        tool_id=RISK_TOOL_ID,
    )

    assert capability.tool_id == RISK_TOOL_ID
    assert payload.tool_id == RISK_TOOL_ID
    assert payload.reprojection_ready is True
