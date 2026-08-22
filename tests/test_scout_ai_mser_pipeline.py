from __future__ import annotations

from datetime import UTC, datetime

from scout.schemas.mser import DecisionType, SufficiencyStatus
from scout.services.mser_answer_verifier import ReasoningDisposition
from scout.services.mser_pipeline import (
    MSERExecutionMode,
    MSERPipeline,
    compact_pipeline_context,
    decision_hint_for_force,
    mser_enforcement_errors,
)
from scout_ai_six_forces_scenarios import ScenarioContext, SourceArtifactRef


NOW = datetime(2026, 7, 24, 8, 0, tzinfo=UTC)


def _scenario() -> ScenarioContext:
    return ScenarioContext(
        scenario_id="route.rank-1.v1",
        source_mode="synthetic_replay",
        project_id="demo",
        observed_at=NOW.isoformat(),
        boss_point_id="boss.001",
        boss_rank=1,
        lat=24.05,
        lon=121.22,
        horizontal_accuracy_m=5,
        fix_quality="synthetic_route_interpolation",
        route_progress_m=1000,
        distance_to_boss_along_route_m=500,
        nearest_route_distance_m=0,
        heading_deg=90,
        travel_direction="increasing_route_progress",
        risk_terrain_candidate={
            "risk_score": 88,
            "exposure_risk": 0.82,
            "slip_risk": 0.77,
            "rockfall_risk": 0.72,
            "terrain_complexity": 0.76,
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
        source_refs=[
            SourceArtifactRef(
                role="risk",
                path="outputs/risk/risk_ribbon.geojson",
                sha256="a" * 64,
            )
        ],
        condition_overlay_refs=["daylight:ample"],
    )


def test_force_hints_preserve_contextual_permission_question_classification() -> None:
    assert decision_hint_for_force("EXP") == DecisionType.HISTORY
    assert decision_hint_for_force("RPF") == DecisionType.READINESS_PACE
    assert decision_hint_for_force("WTH") == DecisionType.WEATHER
    assert decision_hint_for_force("PER") is None


def test_pipeline_selects_minimal_gap_tools_before_retrieval() -> None:
    pipeline = MSERPipeline()

    state = pipeline.prepare(
        question="哪些地方下雨後會變危險？",
        scenario=_scenario(),
        decision_hint=DecisionType.HAZARD,
        now=NOW,
    )

    assert state.packet.intent.primary_type == DecisionType.HAZARD
    assert (
        state.packet.compact_context.certificate.status
        == SufficiencyStatus.INSUFFICIENT
    )
    assert state.packet.tool_plan.coverage_complete is True
    assert len(state.packet.tool_plan.selected_tools) <= 10
    assert {item.tool_id for item in state.packet.tool_plan.selected_tools} == {
        "scout.ai.weather_window.assess.v0",
    }
    assert (
        mser_enforcement_errors(
            mode=MSERExecutionMode.SHADOW,
            state=state,
            verification=None,
        )
        == ()
    )
    assert mser_enforcement_errors(
        mode=MSERExecutionMode.ENFORCE,
        state=state,
        verification=None,
    ) == ("mser_reasoning_blocked:evidence_gap",)


def test_tool_reprojection_can_complete_weather_hazard_proof() -> None:
    pipeline = MSERPipeline()
    initial = pipeline.prepare(
        question="哪些地方下雨後會變危險？",
        scenario=_scenario(),
        decision_hint=DecisionType.HAZARD,
        now=NOW,
    )
    final, payloads = pipeline.reproject_tools(
        previous=initial,
        tool_results=[
            {
                "tool_id": "pydantic_ai.tool.search_scout_risk_scores.v0",
                "status": "completed",
                "quality": "high",
                "freshness": "fresh",
                "field_answer": "高風險候選位於 CP 18 附近，score=88。",
                "field_answer_source_ref": "outputs/risk/risk_ribbon.geojson",
                "missing_fields": [],
            },
            {
                "tool_id": "scout.ai.weather_window.assess.v0",
                "status": "completed",
                "quality": "high",
                "freshness": "fresh",
                "field_answer": "降雨趨勢正在增強，未來三小時是危險窗口。",
                "field_answer_source_ref": "outputs/weather/route_weather_package.json",
                "provided_fields": {"observed_at": NOW.isoformat()},
                "missing_fields": [],
            },
        ],
        now=NOW,
    )

    assert len(payloads) == 2
    assert (
        final.packet.compact_context.certificate.status == SufficiencyStatus.SUFFICIENT
    )
    assert final.reasoning.disposition == ReasoningDisposition.READY_TO_REASON
    assert final.tool_signal_bindings["scout.ai.weather_window.assess.v0"]
    compact = compact_pipeline_context(final)
    assert compact["sufficiency"]["status"] == "sufficient"
    assert compact["candidate_only"] is True
    assert compact["runtime_safety_truth"] is False


def test_model_answer_must_cite_a_tool_bound_to_selected_mser_signal() -> None:
    pipeline = MSERPipeline()
    initial = pipeline.prepare(
        question="哪些地方下雨後會變危險？",
        scenario=_scenario(),
        decision_hint=DecisionType.HAZARD,
        now=NOW,
    )
    final, _ = pipeline.reproject_tools(
        previous=initial,
        tool_results=[
            {
                "tool_id": "pydantic_ai.tool.search_scout_risk_scores.v0",
                "status": "completed",
                "quality": "high",
                "freshness": "fresh",
                "field_answer": "高風險候選位於 CP 18 附近，score=88。",
                "field_answer_source_ref": "outputs/risk/risk_ribbon.geojson",
                "missing_fields": [],
            },
            {
                "tool_id": "scout.ai.weather_window.assess.v0",
                "status": "completed",
                "quality": "high",
                "freshness": "fresh",
                "field_answer": "降雨趨勢正在增強，未來三小時是危險窗口。",
                "field_answer_source_ref": "outputs/weather/route_weather_package.json",
                "provided_fields": {"observed_at": NOW.isoformat()},
                "missing_fields": [],
            },
        ],
        now=NOW,
    )

    passed = pipeline.verify_model_output(
        state=final,
        output={
            "answer": "CP 18 附近在降雨增強時是最高風險候選。",
            "source_refs": [
                "pydantic_ai.tool.search_scout_risk_scores.v0",
                "scout.ai.weather_window.assess.v0",
            ],
        },
        now=NOW,
    )
    failed = pipeline.verify_model_output(
        state=final,
        output={
            "answer": "網路說這裡很危險。",
            "source_refs": ["invented.web.result"],
        },
        now=NOW,
    )

    assert passed.passed is True, passed
    assert failed.passed is False
    assert (
        mser_enforcement_errors(
            mode=MSERExecutionMode.ENFORCE,
            state=final,
            verification=passed,
        )
        == ()
    )
    assert mser_enforcement_errors(
        mode=MSERExecutionMode.ENFORCE,
        state=final,
        verification=failed,
    )[0].startswith("mser_answer_verification_failed:")


def test_enforce_fails_closed_when_mser_pipeline_is_unavailable() -> None:
    assert mser_enforcement_errors(
        mode=MSERExecutionMode.ENFORCE,
        state=None,
        verification=None,
        pipeline_error="mser_prepare_error:ValueError",
    ) == ("mser_pipeline_error",)


def test_missing_tool_provenance_cannot_become_a_sufficient_signal() -> None:
    pipeline = MSERPipeline()
    initial = pipeline.prepare(
        question="現在天氣適合繼續嗎？",
        scenario=_scenario(),
        decision_hint=DecisionType.WEATHER,
        now=NOW,
    )
    final, payloads = pipeline.reproject_tools(
        previous=initial,
        tool_results=[
            {
                "tool_id": "scout.ai.weather_window.assess.v0",
                "status": "completed",
                "field_answer": "沒有來源的天氣結論。",
                "missing_fields": [],
            }
        ],
        now=NOW,
    )

    assert payloads[0].reprojection_ready is False
    assert (
        final.packet.compact_context.certificate.status
        == SufficiencyStatus.INSUFFICIENT
    )
    assert final.reasoning.disposition == ReasoningDisposition.EVIDENCE_GAP
