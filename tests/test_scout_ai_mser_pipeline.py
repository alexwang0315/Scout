from __future__ import annotations

from datetime import UTC, datetime

import pytest

from scout.schemas.mser import (
    CompactDimension,
    DecisionType,
    MSERAnswerMode,
    MSERGapEvidenceReceipt,
    SufficiencyStatus,
)
from scout.services.mser_answer_verifier import (
    MSERAnswerClaim,
    ReasoningDisposition,
    _verify_gap_receipt_claim,
)
from scout.services.mser_pipeline import (
    MSERExecutionMode,
    MSERPipeline,
    compact_pipeline_context,
    decision_hint_for_force,
    mser_enforcement_errors,
    task_contract_for_question,
)
from scout.services.mser_response_composer import (
    compose_conservative_gap_response,
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


def test_task_router_separates_fact_gap_and_safety_modes() -> None:
    location = task_contract_for_question(
        "我現在在路線的哪一個位置？",
        decision_hint=DecisionType.NAVIGATION,
        answer_mode_hint="compound",
    )
    pace = task_contract_for_question(
        "我現在的速度比預估慢多少？",
        decision_hint=DecisionType.READINESS_PACE,
        answer_mode_hint="compound",
    )
    checkpoint = task_contract_for_question(
        "下一個 CP 是什麼，距離多遠？",
        decision_hint=DecisionType.ROUTE_PLANNING,
        answer_mode_hint="compound",
    )
    gap = task_contract_for_question(
        "哪一項天氣資料缺失，讓 Scout 不能支持出發？",
        decision_hint=DecisionType.WEATHER,
        answer_mode_hint="decision",
    )
    safety = task_contract_for_question(
        "Scout 現在是否應該否決我繼續前進的想法？",
        answer_mode_hint="decision",
    )

    assert location.answer_mode == MSERAnswerMode.FACTUAL_LOOKUP
    assert {item.dimension for item in location.requirements} == {
        CompactDimension.CURRENT_POSITION,
        CompactDimension.GPS_CONFIDENCE,
    }
    assert pace.requirements[0].dimension == CompactDimension.PACE_VARIANCE
    assert checkpoint.requirements[0].dimension == CompactDimension.NEXT_CHECKPOINT
    assert gap.answer_mode == MSERAnswerMode.EVIDENCE_GAP_EXPLANATION
    assert safety.answer_mode == MSERAnswerMode.SAFETY_DECISION
    assert safety.safety_relevant is True


def test_task_router_keeps_permission_compounds_in_safety_mode() -> None:
    checkpoint_fact = task_contract_for_question(
        "下一個 CP 是什麼，距離多遠？",
        decision_hint=DecisionType.ROUTE_PLANNING,
        answer_mode_hint="compound",
        safety_relevant_hint=True,
    )
    checkpoint_timing = task_contract_for_question(
        "如果現在休息十分鐘，還能守住下一個 CP 的時間嗎？",
        answer_mode_hint="compound",
        safety_relevant_hint=True,
    )
    reroute = task_contract_for_question(
        "現在改線的風險比照原路前進低嗎？",
        answer_mode_hint="compound",
        safety_relevant_hint=True,
    )

    assert checkpoint_fact.answer_mode == MSERAnswerMode.FACTUAL_LOOKUP
    assert checkpoint_timing.answer_mode == MSERAnswerMode.SAFETY_DECISION
    assert checkpoint_timing.safety_relevant is True
    assert reroute.answer_mode == MSERAnswerMode.SAFETY_DECISION


def test_permission_profiles_preserve_margin_and_explicit_six_dimension_scope() -> None:
    rest_question = "我現在可以在這裡停下來休息嗎？"
    rest_contract = task_contract_for_question(
        rest_question,
        answer_mode_hint="decision",
        safety_relevant_hint=True,
    )
    rest_state = MSERPipeline().prepare(
        question=rest_question,
        scenario=_scenario(),
        task_contract=rest_contract,
        now=NOW,
    )
    rest_dimensions = {
        item.requirement.dimension
        for item in rest_state.packet.compact_context.certificate.coverage
    }

    comprehensive_question = (
        "請用位置、時間、體能、天氣、地形與 buffer 給目前行動一個明確決策。"
    )
    comprehensive_contract = task_contract_for_question(
        comprehensive_question,
        answer_mode_hint="decision",
        safety_relevant_hint=True,
    )
    comprehensive_state = MSERPipeline().prepare(
        question=comprehensive_question,
        scenario=_scenario(),
        task_contract=comprehensive_contract,
        now=NOW,
    )
    comprehensive_dimensions = {
        item.requirement.dimension
        for item in comprehensive_state.packet.compact_context.certificate.coverage
    }

    assert CompactDimension.MISSION_MARGIN in rest_dimensions
    assert {
        CompactDimension.CURRENT_HAZARD,
        CompactDimension.GPS_CONFIDENCE,
        CompactDimension.FATIGUE_INDEX,
        CompactDimension.WEATHER_TREND,
        CompactDimension.REMAINING_DAYLIGHT,
        CompactDimension.MISSION_MARGIN,
    }.issubset(comprehensive_dimensions)
    assert len(comprehensive_state.packet.tool_plan.selected_tools) >= 3


def test_current_position_lookup_does_not_inherit_terrain_decision_profile() -> None:
    pipeline = MSERPipeline()
    task_contract = task_contract_for_question(
        "我現在在路線的哪一個位置？",
        decision_hint=DecisionType.NAVIGATION,
        answer_mode_hint="compound",
    )

    state = pipeline.prepare(
        question="我現在在路線的哪一個位置？",
        scenario=_scenario(),
        decision_hint=DecisionType.NAVIGATION,
        task_contract=task_contract,
        now=NOW,
    )

    assert state.packet.compact_context.certificate.status == SufficiencyStatus.SUFFICIENT
    assert state.reasoning.disposition == ReasoningDisposition.READY_TO_REASON
    assert {
        item.requirement.dimension
        for item in state.packet.compact_context.certificate.coverage
    } == {
        CompactDimension.CURRENT_POSITION,
        CompactDimension.GPS_CONFIDENCE,
    }

    verification = pipeline.verify_model_output(
        state=state,
        output={
            "answer": "目前位於 route progress 1000m，定位誤差約 5m。",
            "decision": None,
            "evidence_gaps": [],
            "source_refs": ["scenario://route.rank-1.v1"],
        },
        now=NOW,
    )
    assert verification.passed is True


def test_critical_decision_cannot_use_factual_lookup_contract() -> None:
    factual_contract = task_contract_for_question(
        "我現在在路線的哪一個位置？",
        decision_hint=DecisionType.NAVIGATION,
        answer_mode_hint="compound",
    )

    with pytest.raises(ValueError, match="critical decisions"):
        MSERPipeline().prepare(
            question="我現在是否應該撤退？",
            scenario=_scenario(),
            decision_hint=DecisionType.RETREAT,
            task_contract=factual_contract,
            now=NOW,
        )


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

    assert passed.passed is True, passed.model_dump(mode="json")
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
    assert final.gap_evidence_receipts == ()


def test_server_bound_scenario_can_prove_contextual_permission_tool_origin() -> None:
    pipeline = MSERPipeline()
    initial = pipeline.prepare(
        question="我現在可以在這裡停下來休息嗎？",
        scenario=_scenario(),
        decision_hint=DecisionType.REST,
        now=NOW,
    )
    final, payloads = pipeline.reproject_tools(
        previous=initial,
        tool_results=[
            {
                "tool_id": "scout.ai.contextual_permission.assess.v0",
                "status": "completed",
                "decision": "CHANGE_PLAN",
                "field_answer": "依目前情境改變計畫。",
                "scenario_context": {
                    "scenario_id": "route.rank-1.v1",
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                },
                "missing_fields": [],
            }
        ],
        now=NOW,
    )

    assert payloads[0].source_refs == ("scenario://route.rank-1.v1",)
    assert payloads[0].reprojection_ready is True
    assert any(
        isinstance(signal.value, dict)
        and signal.value.get("decision") == "CHANGE_PLAN"
        and signal.source_refs == ("scenario://route.rank-1.v1",)
        for signal in final.environment.all_signals()
    )


def test_explicit_missing_answerability_cannot_certify_next_checkpoint() -> None:
    pipeline = MSERPipeline()
    task_contract = task_contract_for_question(
        "下一個 CP 是什麼，距離多遠？",
        decision_hint=DecisionType.ROUTE_PLANNING,
        answer_mode_hint="compound",
    )
    initial = pipeline.prepare(
        question="下一個 CP 是什麼，距離多遠？",
        scenario=_scenario(),
        decision_hint=DecisionType.ROUTE_PLANNING,
        task_contract=task_contract,
        now=NOW,
    )
    final, _ = pipeline.reproject_tools(
        previous=initial,
        tool_results=[
            {
                "tool_id": "pydantic_ai.tool.search_scout_major_points.v0",
                "status": "completed",
                "answerability": "major_points_missing_evidence",
                "field_answer": "目前工作區沒有可匹配的 MCP / named point。",
                "missing_fields": [],
                "source_report": [
                    {
                        "source_path": "outputs/mcp/named_point_evidence.json",
                        "status": "loaded",
                    }
                ],
            }
        ],
        now=NOW,
    )

    certificate = final.packet.compact_context.certificate
    assert certificate.status == SufficiencyStatus.INSUFFICIENT
    assert CompactDimension.NEXT_CHECKPOINT in certificate.missing_dimensions
    assert final.reasoning.disposition == ReasoningDisposition.READY_TO_EXPLAIN_GAP

    assert len(final.gap_evidence_receipts) == 1
    receipt = final.gap_evidence_receipts[0]
    assert receipt.tool_id == "pydantic_ai.tool.search_scout_major_points.v0"
    assert receipt.availability.value == "missing"
    assert receipt.candidate_only is True
    assert receipt.runtime_safety_truth is False
    assert CompactDimension.NEXT_CHECKPOINT in receipt.dimensions
    assert final.reasoning.gap_payload is not None
    assert final.reasoning.gap_payload.gap_evidence_receipts == (receipt,)
    assert compact_pipeline_context(final)["gap_evidence_receipts"] == [
        receipt.model_dump(mode="json")
    ]

    passed = pipeline.verify_model_output(
        state=final,
        output={
            "answer": "目前沒有足夠證據辨識下一個 CP，答案維持 UNKNOWN。",
            "decision": "DELAY",
            "evidence_gaps": ["navigation.next_checkpoint is missing"],
            "source_refs": [
                "pydantic_ai.tool.search_scout_major_points.v0",
            ],
        },
        now=NOW,
    )
    unsafe = pipeline.verify_model_output(
        state=final,
        output={
            "answer": "目前沒有足夠證據辨識下一個 CP，但可以繼續。",
            "decision": "GO",
            "evidence_gaps": ["navigation.next_checkpoint is missing"],
            "source_refs": [
                "pydantic_ai.tool.search_scout_major_points.v0",
            ],
        },
        now=NOW,
    )

    assert passed.passed is True, passed.model_dump(mode="json")
    assert unsafe.passed is False
    assert {item.code.value for item in unsafe.violations} == {
        "non_conservative_gap_decision"
    }


def test_typed_negative_search_receipt_resolves_candidate_analysis_unknown() -> None:
    tool_id = "pydantic_ai.tool.search_scout_evidence_fulltext.v0"
    receipt_ref = "receipts/negative-search/exp031.json"
    pipeline = MSERPipeline()
    task_contract = task_contract_for_question(
        "這一帶的原住民族地名代表什麼意思？",
        decision_hint=DecisionType.HISTORY,
        answer_mode_hint="factual_context",
    )
    initial = pipeline.prepare(
        question="這一帶的原住民族地名代表什麼意思？",
        scenario=_scenario(),
        decision_hint=DecisionType.HISTORY,
        task_contract=task_contract,
        now=NOW,
    )
    final, payloads = pipeline.reproject_tools(
        previous=initial,
        tool_results=[
            {
                "tool_id": tool_id,
                "status": "completed",
                "answerability": "evidence_fulltext_no_match",
                "quality": "verified",
                "freshness": "workspace_snapshot",
                "result_count": 0,
                "searched_record_count": 42,
                "missing_fields": ["matching_scoped_evidence"],
                "source_refs": [receipt_ref],
                "negative_search_receipt": {
                    "source_ref": receipt_ref,
                    "result_count": 0,
                    "searched_record_count": 42,
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                },
            }
        ],
        now=NOW,
    )

    assert payloads[0].reprojection_ready is True
    assert payloads[0].source_refs == (receipt_ref,)
    assert final.reasoning.disposition == ReasoningDisposition.READY_TO_EXPLAIN_GAP
    assert len(final.gap_evidence_receipts) == 1
    assert final.gap_evidence_receipts[0].tool_id == tool_id

    verified = pipeline.verify_model_output(
        state=final,
        output={
            "answer": "工作區查詢沒有找到題目專屬證據，因此維持 UNKNOWN，不臆測地名含義。",
            "decision": None,
            "evidence_gaps": ["缺少原住民族地名含義的工作區證據"],
            "source_refs": [tool_id],
        },
        now=NOW,
    )

    assert verified.passed is True, verified.model_dump(mode="json")


def test_safety_gap_can_explain_only_server_owned_conservative_decision() -> None:
    pipeline = MSERPipeline()
    task_contract = task_contract_for_question(
        "我現在可以在這裡停下來休息嗎？",
        decision_hint=DecisionType.REST,
        answer_mode_hint="decision",
    )
    initial = pipeline.prepare(
        question="我現在可以在這裡停下來休息嗎？",
        scenario=_scenario(),
        decision_hint=DecisionType.REST,
        task_contract=task_contract,
        now=NOW,
    )
    final, _ = pipeline.reproject_tools(
        previous=initial,
        tool_results=[
            {
                "tool_id": "scout.ai.pace_guardian.assess.v0",
                "status": "completed",
                "decision": "CHANGE_PLAN",
                "field_answer": "後隊儲備不足，deterministic tool 建議 CHANGE_PLAN。",
                "field_answer_source_ref": "outputs/team_status.json",
                "missing_fields": [],
            },
            {
                "tool_id": "scout.ai.weather_window.assess.v0",
                "status": "completed",
                "decision": "DELAY",
                "field_answer": "fresh route weather evidence 缺失，建議 DELAY。",
                "field_answer_source_ref": "outputs/weather/route_weather.json",
                "missing_fields": ["fresh_route_weather_evidence"],
            },
        ],
        now=NOW,
    )

    assert final.reasoning.disposition == ReasoningDisposition.READY_TO_EXPLAIN_GAP
    assert final.reasoning.gap_payload is not None
    assert final.reasoning.gap_payload.allowed_decisions == (
        "DELAY",
        "CHANGE_PLAN",
    )
    assert compact_pipeline_context(final)["reasoning_allowed_decisions"] == [
        "DELAY",
        "CHANGE_PLAN",
    ]

    supported = pipeline.verify_model_output(
        state=final,
        output={
            "answer": "天氣仍是 UNKNOWN；依腳程工具先改變原計畫。",
            "decision": "CHANGE_PLAN",
            "evidence_gaps": ["fresh_route_weather_evidence is missing"],
            "source_refs": [
                "scout.ai.pace_guardian.assess.v0",
                "scout.ai.weather_window.assess.v0",
            ],
        },
        now=NOW,
    )
    unsupported = pipeline.verify_model_output(
        state=final,
        output={
            "answer": "天氣仍是 UNKNOWN，但可以照原計畫前進。",
            "decision": "GO",
            "evidence_gaps": ["fresh_route_weather_evidence is missing"],
            "source_refs": [
                "scout.ai.pace_guardian.assess.v0",
                "scout.ai.weather_window.assess.v0",
            ],
        },
        now=NOW,
    )

    assert supported.passed is True, supported.model_dump(mode="json")
    assert unsupported.passed is False
    assert {item.code.value for item in unsupported.violations} == {
        "non_conservative_gap_decision"
    }


def test_server_owned_composer_delays_nonconservative_gap_decision() -> None:
    pipeline = MSERPipeline()
    task_contract = task_contract_for_question(
        "我現在可以在這裡停下來休息嗎？",
        decision_hint=DecisionType.REST,
        answer_mode_hint="decision",
    )
    initial = pipeline.prepare(
        question="我現在可以在這裡停下來休息嗎？",
        scenario=_scenario(),
        decision_hint=DecisionType.REST,
        task_contract=task_contract,
        now=NOW,
    )
    tool_id = "scout.ai.weather_window.assess.v0"
    final, _ = pipeline.reproject_tools(
        previous=initial,
        tool_results=[
            {
                "tool_id": "scout.ai.pace_guardian.assess.v0",
                "status": "completed",
                "decision": "CHANGE_PLAN",
                "field_answer": "後隊儲備不足，deterministic tool 建議 CHANGE_PLAN。",
                "field_answer_source_ref": "outputs/team_status.json",
                "missing_fields": [],
            },
            {
                "tool_id": tool_id,
                "status": "completed",
                "decision": "DELAY",
                "field_answer": "fresh route weather evidence is missing; DELAY.",
                "field_answer_source_ref": "outputs/weather/route_weather.json",
                "missing_fields": ["fresh_route_weather_evidence"],
            }
        ],
        now=NOW,
    )
    original_output = {
        "scenario_id": "route.rank-1.v1",
        "answer": "可以在這裡休息。",
        "decision": "GO",
        "decisive_evidence": ["candidate permission"],
        "opposing_evidence": ["weather evidence missing"],
        "evidence_gaps": ["fresh_route_weather_evidence"],
        "decision_change_conditions": ["weather evidence changes"],
        "source_refs": ["scout.ai.pace_guardian.assess.v0", tool_id],
        "claims": ["candidate_only", "runtime_safety_truth=false"],
    }
    original_copy = dict(original_output)
    verification = pipeline.verify_model_output(
        state=final,
        output=original_output,
        now=NOW,
    )

    composition = compose_conservative_gap_response(
        state=final,
        output=original_output,
        verification=verification,
        base_contract_valid=True,
    )

    assert composition.status == "composed", {
        "composition": composition.model_dump(mode="json"),
        "verification_codes": [item.code.value for item in verification.violations],
    }
    assert composition.policy_id == "mser.gap.delay.v0"
    assert composition.original_decision == "GO"
    assert composition.composed_decision == "DELAY"
    assert composition.provider_output_preserved is True
    assert composition.candidate_only is True
    assert composition.runtime_safety_truth is False
    assert original_output == original_copy
    assert composition.effective_response is not None
    effective = composition.effective_response.model_dump(mode="json")
    assert effective["decision"] == "DELAY"
    assert effective["source_refs"] == [tool_id]
    assert effective["candidate_only"] is True
    assert effective["runtime_safety_truth"] is False
    assert (
        pipeline.verify_model_output(state=final, output=effective, now=NOW).passed
        is True
    )
    boundary_rejected = compose_conservative_gap_response(
        state=final,
        output={**original_output, "claims": []},
        verification=verification,
        base_contract_valid=True,
    )
    assert boundary_rejected.status == "rejected"
    assert boundary_rejected.reason_code == "candidate_boundary_invalid"
    assert boundary_rejected.effective_response is None

    base_rejected = compose_conservative_gap_response(
        state=final,
        output=original_output,
        verification=verification,
        base_contract_valid=False,
    )
    assert base_rejected.status == "rejected"
    assert base_rejected.reason_code == "base_contract_invalid"
    assert base_rejected.effective_response is None


def test_gap_receipt_can_bind_to_a_required_dimension_already_covered() -> None:
    question = "我現在可以在這裡停下來休息嗎？"
    pipeline = MSERPipeline()
    task_contract = task_contract_for_question(
        question,
        answer_mode_hint="decision",
        safety_relevant_hint=True,
    )
    initial = pipeline.prepare(
        question=question,
        scenario=_scenario(),
        task_contract=task_contract,
        now=NOW,
    )
    final, _ = pipeline.reproject_tools(
        previous=initial,
        tool_results=[
            {
                "tool_id": "scout.ai.pace_guardian.assess.v0",
                "status": "completed",
                "decision": "CHANGE_PLAN",
                "field_answer": "Pace evidence supplies a mission-margin signal.",
                "field_answer_source_ref": "outputs/team_status.json",
                "missing_fields": [],
            },
        ],
        now=NOW,
    )

    mission_margin_coverage = next(
        item
        for item in final.packet.compact_context.certificate.coverage
        if item.requirement.dimension == CompactDimension.MISSION_MARGIN
    )
    assert mission_margin_coverage.status == "covered"
    context = final.packet.compact_context
    scoped_information_needs = tuple(
        item
        for item in context.information_needs
        if item.dimension != CompactDimension.MISSION_MARGIN
    )
    assert scoped_information_needs
    certificate = context.certificate.model_copy(
        update={
            field: tuple(
                item
                for item in getattr(context.certificate, field)
                if item != CompactDimension.MISSION_MARGIN
            )
            for field in (
                "missing_dimensions",
                "stale_dimensions",
                "low_confidence_dimensions",
                "contradictory_dimensions",
            )
        }
    )
    scoped_context = context.model_copy(
        update={
            "information_needs": scoped_information_needs,
            "certificate": certificate,
        }
    )

    permission_receipt = MSERGapEvidenceReceipt(
        receipt_id="mser.gap.permission-buffer",
        tool_id="scout.ai.contextual_permission.assess.v0",
        dimensions=(CompactDimension.MISSION_MARGIN,),
        signal_ids=("mser.tool.permission.mission-margin",),
        availability="missing",
        missing_fields=("remaining_safety_buffer_minutes",),
        freshness="unknown",
        quality="high",
        observed_at=NOW,
        source_refs=("scenario://route.rank-1.v1",),
    )
    claim = MSERAnswerClaim(
        claim_id="permission-gap",
        statement="remaining_safety_buffer_minutes is missing.",
        gap_receipt_ids=(permission_receipt.receipt_id,),
        source_refs=permission_receipt.source_refs,
    )
    violations = _verify_gap_receipt_claim(
        claim=claim,
        receipt_by_id={permission_receipt.receipt_id: permission_receipt},
        context=scoped_context,
    )

    unrelated_receipt = permission_receipt.model_copy(
        update={
            "receipt_id": "mser.gap.unrelated",
            "dimensions": (CompactDimension.HISTORICAL_CONTEXT_RELEVANCE,),
            "missing_fields": ("unrelated_history_field",),
        }
    )
    unrelated_claim = claim.model_copy(
        update={"gap_receipt_ids": (unrelated_receipt.receipt_id,)}
    )
    unrelated_violations = _verify_gap_receipt_claim(
        claim=unrelated_claim,
        receipt_by_id={unrelated_receipt.receipt_id: unrelated_receipt},
        context=scoped_context,
    )

    assert violations == ()
    assert {item.code.value for item in unrelated_violations} == {
        "gap_receipt_dimension_mismatch"
    }


def test_server_owned_composer_fails_closed_for_multiple_violations() -> None:
    pipeline = MSERPipeline()
    task_contract = task_contract_for_question(
        "我現在可以在這裡停下來休息嗎？",
        decision_hint=DecisionType.REST,
        answer_mode_hint="decision",
    )
    initial = pipeline.prepare(
        question="我現在可以在這裡停下來休息嗎？",
        scenario=_scenario(),
        decision_hint=DecisionType.REST,
        task_contract=task_contract,
        now=NOW,
    )
    tool_id = "scout.ai.weather_window.assess.v0"
    final, _ = pipeline.reproject_tools(
        previous=initial,
        tool_results=[
            {
                "tool_id": "scout.ai.pace_guardian.assess.v0",
                "status": "completed",
                "decision": "CHANGE_PLAN",
                "field_answer": "後隊儲備不足，deterministic tool 建議 CHANGE_PLAN。",
                "field_answer_source_ref": "outputs/team_status.json",
                "missing_fields": [],
            },
            {
                "tool_id": tool_id,
                "status": "completed",
                "decision": "DELAY",
                "field_answer": "fresh route weather evidence is missing; DELAY.",
                "field_answer_source_ref": "outputs/weather/route_weather.json",
                "missing_fields": ["fresh_route_weather_evidence"],
            }
        ],
        now=NOW,
    )
    output = {
        "scenario_id": "route.rank-1.v1",
        "answer": "可以在這裡休息。",
        "decision": "GO",
        "decisive_evidence": [],
        "opposing_evidence": [],
        "evidence_gaps": [],
        "decision_change_conditions": [],
        "source_refs": [tool_id],
        "claims": ["candidate_only"],
    }
    verification = pipeline.verify_model_output(
        state=final,
        output=output,
        now=NOW,
    )

    composition = compose_conservative_gap_response(
        state=final,
        output=output,
        verification=verification,
        base_contract_valid=True,
    )

    assert composition.status == "rejected"
    assert composition.reason_code == "verification_not_single_non_conservative"
    assert composition.effective_response is None
    assert composition.candidate_only is True
    assert composition.runtime_safety_truth is False
