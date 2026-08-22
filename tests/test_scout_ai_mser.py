from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pydantic import ValidationError

from scout.schemas.mser import (
    CompactDimension,
    CompactSignal,
    DecisionType,
    EnvironmentalRepresentation,
    KnowledgeCandidate,
    MemoryEvent,
    OperationalLatentState,
    SufficiencyStatus,
    TerrainLatentState,
    ToolCapability,
    WeatherLatentState,
    HumanLatentState,
)
from scout.services.mser_engine import (
    DecisionTypeClassifier,
    KnowledgeReductionEngine,
    MSEREngine,
    MemoryReductionEngine,
)


NOW = datetime(2026, 7, 24, 8, 0, tzinfo=UTC)


def _signal(
    dimension: CompactDimension,
    value: float | str,
    *,
    confidence: float = 0.9,
    risk_upper_bound: float | None = None,
    observed_at: datetime = NOW,
    conflicts_with: tuple[str, ...] = (),
    suffix: str = "fixture",
) -> CompactSignal:
    return CompactSignal(
        signal_id=f"{dimension.value}.{suffix}",
        dimension=dimension,
        value=value,
        confidence=confidence,
        risk_upper_bound=risk_upper_bound,
        observed_at=observed_at,
        valid_until=NOW + timedelta(hours=3),
        source_refs=(f"fixture://{dimension.value}/{suffix}",),
        conflicts_with=conflicts_with,
    )


def _complete_rest_environment() -> EnvironmentalRepresentation:
    return EnvironmentalRepresentation(
        representation_id="rest-complete",
        terrain=TerrainLatentState(
            exposure_risk=_signal(CompactDimension.EXPOSURE_RISK, 0.2),
            escape_cost=_signal(CompactDimension.ESCAPE_COST, 0.3),
            rockfall_risk=_signal(CompactDimension.ROCKFALL_RISK, 0.1),
        ),
        weather=WeatherLatentState(
            weather_stability=_signal(CompactDimension.WEATHER_STABILITY, 0.8),
        ),
        human=HumanLatentState(
            fatigue_index=_signal(CompactDimension.FATIGUE_INDEX, 0.55),
            energy_reserve=_signal(CompactDimension.ENERGY_RESERVE, 0.62),
        ),
        operation=OperationalLatentState(
            team_distance=_signal(CompactDimension.TEAM_DISTANCE, 18.0),
            remaining_daylight=_signal(CompactDimension.REMAINING_DAYLIGHT, 210.0),
            historical_context_relevance=_signal(
                CompactDimension.HISTORICAL_CONTEXT_RELEVANCE,
                "nearby trail history",
            ),
        ),
    )


def test_decision_classifier_selects_adaptive_profiles() -> None:
    classifier = DecisionTypeClassifier()

    assert classifier.classify("可以停十分鐘嗎？").primary_type == DecisionType.REST
    assert classifier.classify("今天能不能攻頂？").primary_type == DecisionType.SUMMIT
    assert classifier.classify("我要不要撤退？").primary_type == DecisionType.RETREAT
    assert (
        classifier.classify("這裡適合停下來拍照嗎？").primary_type
        == DecisionType.PHOTOGRAPHY
    )
    assert (
        classifier.classify("show terrain profile").primary_type != DecisionType.WEATHER
    )
    assert (
        classifier.classify("午後大雨下這段路還適合走嗎？").primary_type
        == DecisionType.WEATHER
    )
    assert (
        classifier.classify("我可以走到旁邊那塊岩石取景嗎？").primary_type
        == DecisionType.PHOTOGRAPHY
    )
    assert (
        classifier.classify("我們可以在這裡吃午餐嗎？").primary_type
        == DecisionType.REST
    )
    assert (
        classifier.classify("我可以先到下一個地標等隊友嗎？").primary_type
        == DecisionType.REST
    )
    assert (
        classifier.classify("我們現在可以改走替代線嗎？").primary_type
        == DecisionType.ROUTE_PLANNING
    )


def test_validated_decision_hint_sets_primary_and_keeps_question_label_as_modifier() -> (
    None
):
    intent = DecisionTypeClassifier().classify(
        "這條路線除了登頂，最值得理解的是什麼？",
        decision_hint=DecisionType.HISTORY,
    )

    assert intent.primary_type == DecisionType.HISTORY
    assert DecisionType.SUMMIT in intent.alternative_types
    assert intent.confidence == 0.9


def test_compound_question_adds_only_secondary_modifier_requirements() -> None:
    packet = MSEREngine().prepare(
        question="哪些地方下雨後會變危險？",
        environment=EnvironmentalRepresentation(representation_id="compound-empty"),
        now=NOW,
    )
    needed = {need.dimension for need in packet.compact_context.information_needs}

    assert packet.intent.primary_type == DecisionType.HAZARD
    assert packet.intent.alternative_types == (DecisionType.WEATHER,)
    assert CompactDimension.CURRENT_HAZARD in needed
    assert CompactDimension.WEATHER_TREND in needed
    assert CompactDimension.DANGER_WINDOW in needed
    assert CompactDimension.FORECAST_CONFIDENCE in needed
    assert CompactDimension.WEATHER_STABILITY not in needed


def test_context_reduction_is_decision_specific_and_sufficient() -> None:
    packet = MSEREngine().prepare(
        question="可以停十分鐘嗎？",
        environment=_complete_rest_environment(),
        now=NOW,
    )

    selected = {signal.dimension for signal in packet.compact_context.selected_signals}
    assert packet.intent.primary_type == DecisionType.REST
    assert packet.compact_context.certificate.status == SufficiencyStatus.SUFFICIENT
    assert packet.compact_context.certificate.coverage_ratio == 1.0
    assert CompactDimension.FATIGUE_INDEX in selected
    assert CompactDimension.REMAINING_DAYLIGHT in selected
    assert CompactDimension.HISTORICAL_CONTEXT_RELEVANCE not in selected
    assert (
        CompactDimension.HISTORICAL_CONTEXT_RELEVANCE
        in packet.compact_context.discarded_dimensions
    )
    assert packet.tool_plan.selected_tools == ()


def test_missing_state_is_a_proof_obligation_not_a_low_risk_default() -> None:
    environment = _complete_rest_environment().model_copy(
        update={
            "operation": _complete_rest_environment().operation.model_copy(
                update={"remaining_daylight": None}
            )
        }
    )
    capabilities = (
        ToolCapability(
            tool_id="scout.context.total_info.v1",
            produces_dimensions=(
                CompactDimension.REMAINING_DAYLIGHT,
                CompactDimension.GPS_CONFIDENCE,
            ),
            expected_confidence=0.9,
        ),
    )

    packet = MSEREngine().prepare(
        question="可以停十分鐘嗎？",
        environment=environment,
        capabilities=capabilities,
        now=NOW,
    )

    assert packet.compact_context.certificate.status == SufficiencyStatus.INSUFFICIENT
    assert packet.compact_context.certificate.missing_dimensions == (
        CompactDimension.REMAINING_DAYLIGHT,
    )
    assert packet.tool_plan.coverage_complete is True
    assert len(packet.tool_plan.selected_tools) == 1
    assert packet.tool_plan.selected_tools[0].fills_dimensions == (
        CompactDimension.REMAINING_DAYLIGHT,
    )


def test_required_freshness_without_any_time_bound_is_not_sufficient() -> None:
    environment = _complete_rest_environment()
    undated_daylight = environment.operation.remaining_daylight.model_copy(
        update={"observed_at": None, "valid_until": None}
    )
    environment = environment.model_copy(
        update={
            "operation": environment.operation.model_copy(
                update={"remaining_daylight": undated_daylight}
            )
        }
    )

    packet = MSEREngine().prepare(
        question="可以停十分鐘嗎？",
        environment=environment,
        now=NOW,
    )

    assert packet.compact_context.certificate.status == SufficiencyStatus.INSUFFICIENT
    assert packet.compact_context.certificate.stale_dimensions == (
        CompactDimension.REMAINING_DAYLIGHT,
    )


def test_tool_planner_chooses_one_covering_tool_instead_of_searching_everything() -> (
    None
):
    environment = EnvironmentalRepresentation(representation_id="empty")
    capabilities = (
        ToolCapability(
            tool_id="scout.context.total_info.v1",
            produces_dimensions=(
                CompactDimension.EXPOSURE_RISK,
                CompactDimension.WEATHER_STABILITY,
                CompactDimension.TEAM_DISTANCE,
                CompactDimension.REMAINING_DAYLIGHT,
                CompactDimension.ESCAPE_COST,
                CompactDimension.GPS_CONFIDENCE,
            ),
            expected_confidence=0.85,
            expected_latency_ms=40,
        ),
        ToolCapability(
            tool_id="scout.weather.only.v0",
            produces_dimensions=(CompactDimension.WEATHER_STABILITY,),
            expected_confidence=0.95,
            expected_latency_ms=10,
        ),
    )

    packet = MSEREngine().prepare(
        question="這裡適合停下來拍照嗎？",
        environment=environment,
        capabilities=capabilities,
        now=NOW,
    )

    assert len(packet.compact_context.information_needs) == 6
    assert [tool.tool_id for tool in packet.tool_plan.selected_tools] == [
        "scout.context.total_info.v1"
    ]
    assert packet.tool_plan.coverage_complete is True


def test_high_risk_signal_survives_even_when_not_in_low_risk_profile() -> None:
    environment = EnvironmentalRepresentation(
        representation_id="history-with-hazard",
        terrain=TerrainLatentState(
            exposure_risk=_signal(
                CompactDimension.EXPOSURE_RISK,
                0.92,
                risk_upper_bound=0.96,
            )
        ),
        operation=OperationalLatentState(
            route_progress=_signal(CompactDimension.ROUTE_PROGRESS, 13.2),
            historical_context_relevance=_signal(
                CompactDimension.HISTORICAL_CONTEXT_RELEVANCE,
                "old police route",
            ),
        ),
    )

    packet = MSEREngine().prepare(
        question="這段古道有什麼歷史？",
        environment=environment,
        now=NOW,
    )

    assert packet.compact_context.certificate.status == SufficiencyStatus.SUFFICIENT
    assert (
        "terrain.exposure_risk.fixture"
        in packet.compact_context.certificate.preserved_high_risk_signal_ids
    )
    assert CompactDimension.EXPOSURE_RISK in {
        signal.dimension for signal in packet.compact_context.selected_signals
    }


def test_contradictory_signals_are_preserved_and_block_reasoning() -> None:
    first_id = "weather.trend.station"
    second_id = "weather.trend.qpf"
    environment = EnvironmentalRepresentation(
        representation_id="weather-conflict",
        weather=WeatherLatentState(
            weather_stability=_signal(CompactDimension.WEATHER_STABILITY, 0.4),
            weather_trend=_signal(
                CompactDimension.WEATHER_TREND,
                "improving",
                conflicts_with=(second_id,),
                suffix="station",
            ),
            danger_window=_signal(
                CompactDimension.DANGER_WINDOW,
                "10:00-12:00",
            ),
            forecast_confidence=_signal(
                CompactDimension.FORECAST_CONFIDENCE,
                0.7,
            ),
        ),
        additional_signals=(
            _signal(
                CompactDimension.WEATHER_TREND,
                "deteriorating",
                suffix="qpf",
            ),
        ),
    )

    packet = MSEREngine().prepare(
        question="接下來天氣會變差嗎？",
        environment=environment,
        now=NOW,
    )

    assert packet.compact_context.certificate.status == SufficiencyStatus.CONTRADICTORY
    assert packet.compact_context.certificate.contradictory_dimensions == (
        CompactDimension.WEATHER_TREND,
    )
    assert {
        signal.signal_id
        for signal in packet.compact_context.selected_signals
        if signal.dimension == CompactDimension.WEATHER_TREND
    } == {first_id, second_id}


def test_memory_reduction_keeps_decisions_hazards_and_anomalies() -> None:
    events = (
        MemoryEvent(
            event_id="raw-1",
            event_type="gps_sample",
            observed_at=NOW,
            summary="ordinary sample",
            source_refs=("raw://gps/1",),
            cluster_key="ordinary-gps",
            importance=0.1,
        ),
        MemoryEvent(
            event_id="hazard-1",
            event_type="hazard",
            observed_at=NOW + timedelta(seconds=1),
            summary="slip event",
            source_refs=("raw://imu/2",),
            hazard_severity=0.8,
        ),
        MemoryEvent(
            event_id="decision-1",
            event_type="decision",
            observed_at=NOW + timedelta(seconds=2),
            summary="turned back",
            source_refs=("raw://decision/3",),
            decision_point=True,
            decision_types=(DecisionType.RETREAT,),
        ),
        MemoryEvent(
            event_id="stop-1",
            event_type="stop",
            observed_at=NOW + timedelta(seconds=3),
            summary="material stop",
            source_refs=("raw://stop/4",),
            stop=True,
        ),
    )

    reduced = MemoryReductionEngine().reduce(
        events=events,
        decision_type=DecisionType.RETREAT,
    )

    assert [event.event_id for event in reduced.selected_events] == [
        "hazard-1",
        "decision-1",
        "stop-1",
    ]
    assert reduced.omitted_event_count == 1
    assert set(reduced.raw_event_refs_preserved) == {
        "raw://gps/1",
        "raw://imu/2",
        "raw://decision/3",
        "raw://stop/4",
    }


def test_knowledge_reduction_covers_dimensions_and_prunes_redundancy() -> None:
    candidates = (
        KnowledgeCandidate(
            knowledge_id="combined",
            summary="Route weather and terrain note",
            source_refs=("workspace://combined",),
            supports_dimensions=(
                CompactDimension.WEATHER_TREND,
                CompactDimension.EXPOSURE_RISK,
            ),
            decision_types=(DecisionType.RETREAT,),
            authority=0.9,
        ),
        KnowledgeCandidate(
            knowledge_id="weather-only",
            summary="Weather note",
            source_refs=("workspace://weather",),
            supports_dimensions=(CompactDimension.WEATHER_TREND,),
            decision_types=(DecisionType.RETREAT,),
            authority=0.8,
        ),
    )

    reduced = KnowledgeReductionEngine().reduce(
        candidates=candidates,
        decision_type=DecisionType.RETREAT,
        required_dimensions=(
            CompactDimension.WEATHER_TREND,
            CompactDimension.EXPOSURE_RISK,
        ),
    )

    assert [item.knowledge_id for item in reduced.selected_candidates] == ["combined"]
    assert reduced.uncovered_dimensions == ()
    assert reduced.source_refs_verified is True


def test_mser_contract_cannot_be_promoted_to_runtime_safety_truth() -> None:
    signal = _signal(CompactDimension.EXPOSURE_RISK, 0.2)

    try:
        CompactSignal.model_validate(
            {
                **signal.model_dump(mode="json"),
                "runtime_safety_truth": True,
            }
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("MSER signal must remain candidate-only")
