from __future__ import annotations

from datetime import UTC, datetime

from scout.nextgen.jev_decision_service import (
    JevArtifactFamily,
    JevAuthorityClass,
    JevEscalationDisposition,
    JevParsedSignals,
    JevQuestionClass,
    JevQuestionContract,
    JevToolFamily,
)
from scout.nextgen.jev_runtime_integration import (
    JevRuntimePath,
    compile_jev_runtime_plan,
    runtime_input_from_mser,
)
from scout.nextgen.max_runtime_preflight import MaxRuntimeReadinessDisposition
from scout.schemas.mser import DecisionType, SufficiencyStatus
from scout.services.mser_pipeline import MSERPipeline, task_contract_for_question
from scout_ai_six_forces_scenarios import ScenarioContext, SourceArtifactRef


NOW = datetime(2026, 7, 24, 8, 0, tzinfo=UTC)


def _scenario() -> ScenarioContext:
    return ScenarioContext(
        scenario_id="route.jev.integration.v1",
        source_mode="synthetic_replay",
        project_id="jev-integration",
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


def _contract(
    *,
    question_class: JevQuestionClass,
    tool_family: JevToolFamily,
    authority_class: JevAuthorityClass = JevAuthorityClass.LOW_RISK_CANDIDATE,
    artifact_family: JevArtifactFamily = JevArtifactFamily.ROUTE,
) -> JevQuestionContract:
    return JevQuestionContract(
        question_class=question_class,
        artifact_family=artifact_family,
        allowed_tool_families=(tool_family,),
        authority_class=authority_class,
        required_domains=("route",),
    )


def _state(
    question: str,
    *,
    decision_hint: DecisionType | None = None,
    answer_mode_hint: str = "compound",
):
    contract = task_contract_for_question(
        question,
        decision_hint=decision_hint,
        answer_mode_hint=answer_mode_hint,
    )
    return MSERPipeline().prepare(
        question=question,
        scenario=_scenario(),
        decision_hint=decision_hint,
        task_contract=contract,
        now=NOW,
    )


def _jev_signal(
    contract: JevQuestionContract,
    *,
    escalation: JevEscalationDisposition,
    sufficient: bool,
    contradiction: bool = False,
) -> JevParsedSignals:
    return JevParsedSignals(
        artifact_family=contract.artifact_family,
        question_class=contract.question_class,
        tool_family=contract.allowed_tool_families[0],
        relevance=1.0,
        completeness=1.0,
        semantic_contradiction=contradiction,
        evidence_sufficient=sufficient,
        escalation=escalation,
        confidence=1.0,
    )


def test_mser_sufficient_keeps_jev_conservatism_non_authoritative() -> None:
    state = _state("我現在在路線的哪一個位置？", decision_hint=DecisionType.NAVIGATION)
    assert state.packet.compact_context.certificate.status is SufficiencyStatus.SUFFICIENT
    contract = _contract(
        question_class=JevQuestionClass.STATIC_FACT,
        tool_family=JevToolFamily.DATABASE_READ,
    )
    runtime_input = runtime_input_from_mser(
        state=state,
        contract=contract,
        jev=_jev_signal(
            contract,
            escalation=JevEscalationDisposition.COLLECT_MORE_EVIDENCE,
            sufficient=False,
        ),
    )

    plan = compile_jev_runtime_plan(runtime_input)

    assert plan.path is JevRuntimePath.DETERMINISTIC_FAST_LANE
    assert plan.disposition is JevEscalationDisposition.AUTO
    assert plan.over_escalation is True
    assert plan.praison_allowed is False
    assert plan.max_allowed is False
    assert plan.runtime_safety_truth is False


def test_praison_is_available_only_for_an_actual_mser_information_need() -> None:
    state = _state(
        "哪些地方下雨後會變危險？",
        decision_hint=DecisionType.HAZARD,
        answer_mode_hint="decision",
    )
    assert state.packet.compact_context.information_needs
    contract = _contract(
        question_class=JevQuestionClass.CROSS_ARTIFACT_JOIN,
        tool_family=JevToolFamily.PRAISONAI_INFORMATION_NEED,
        artifact_family=JevArtifactFamily.WEATHER,
    )
    plan = compile_jev_runtime_plan(
        runtime_input_from_mser(state=state, contract=contract)
    )

    assert plan.path is JevRuntimePath.PRAISON_INFORMATION_NEED
    assert plan.praison_allowed is True
    assert plan.max_allowed is False
    assert plan.mser_gate_passed is False

    sufficient_state = _state(
        "我現在在路線的哪一個位置？",
        decision_hint=DecisionType.NAVIGATION,
    )
    sufficient_plan = compile_jev_runtime_plan(
        runtime_input_from_mser(state=sufficient_state, contract=contract)
    )
    assert sufficient_plan.praison_allowed is False


def test_max_requires_mser_sufficiency_synthesis_failure_and_preflight() -> None:
    state = _state("我現在在路線的哪一個位置？", decision_hint=DecisionType.NAVIGATION)
    contract = _contract(
        question_class=JevQuestionClass.RECOVERY,
        tool_family=JevToolFamily.MAX_REASONING,
    )
    ready = compile_jev_runtime_plan(
        runtime_input_from_mser(
            state=state,
            contract=contract,
            synthesis_failed=True,
            max_readiness=MaxRuntimeReadinessDisposition.READY_FOR_BEHAVIOR_QUALIFICATION,
        )
    )
    unavailable = compile_jev_runtime_plan(
        runtime_input_from_mser(
            state=state,
            contract=contract,
            synthesis_failed=True,
            max_readiness=MaxRuntimeReadinessDisposition.ENDPOINT_UNAVAILABLE,
        )
    )

    assert ready.path is JevRuntimePath.MAX_SYNTHESIS_RECOVERY
    assert ready.disposition is JevEscalationDisposition.USE_STRONGER_MODEL
    assert ready.max_allowed is True
    assert unavailable.path is JevRuntimePath.HUMAN_REVIEW
    assert unavailable.max_allowed is False
    assert unavailable.human_review_required is True


def test_authority_bearing_mser_sufficient_case_cannot_auto_route() -> None:
    state = _state("我現在在路線的哪一個位置？", decision_hint=DecisionType.NAVIGATION)
    contract = _contract(
        question_class=JevQuestionClass.STATIC_FACT,
        tool_family=JevToolFamily.HUMAN_REVIEW,
        authority_class=JevAuthorityClass.AUTHORITY_BEARING,
        artifact_family=JevArtifactFamily.PERMISSION,
    )
    plan = compile_jev_runtime_plan(
        runtime_input_from_mser(
            state=state,
            contract=contract,
            jev=_jev_signal(
                contract,
                escalation=JevEscalationDisposition.AUTO,
                sufficient=True,
            ),
        )
    )

    assert plan.path is JevRuntimePath.HUMAN_REVIEW
    assert plan.disposition is JevEscalationDisposition.HUMAN_REVIEW
    assert plan.human_review_required is True
    assert plan.max_allowed is False
    assert plan.praison_allowed is False
