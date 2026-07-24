"""Minimal Sufficient Environmental Representation contracts.

MSER is the decision-facing projection that sits between Scout's raw evidence
surfaces and the bounded agent runtime. Models may reason over these contracts,
but deterministic services own projection, sufficiency checks, provenance, and
tool execution.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, ClassVar, Literal

from pydantic import Field, model_validator

from scout.schemas.base import NonEmptyStr, SchemaModel


class DecisionType(StrEnum):
    NAVIGATION = "navigation"
    HAZARD = "hazard"
    PHOTOGRAPHY = "photography"
    REST = "rest"
    SUMMIT = "summit"
    RETREAT = "retreat"
    CAMP = "camp"
    MEDICAL = "medical"
    COMMUNICATION = "communication"
    WEATHER = "weather"
    WATER = "water"
    WILDLIFE = "wildlife"
    HISTORY = "history"
    ROUTE_PLANNING = "route_planning"
    READINESS_PACE = "readiness_pace_fit"
    GENERAL = "general"


class DecisionCriticality(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


class CompactDimension(StrEnum):
    EXPOSURE_RISK = "terrain.exposure_risk"
    SLIP_RISK = "terrain.slip_risk"
    ROCKFALL_RISK = "terrain.rockfall_risk"
    ESCAPE_COST = "terrain.escape_cost"
    VISIBILITY = "terrain.visibility"
    TERRAIN_COMPLEXITY = "terrain.complexity"
    TERRAIN_CONFIDENCE = "terrain.confidence"
    WEATHER_STABILITY = "weather.stability"
    WEATHER_TREND = "weather.trend"
    DANGER_WINDOW = "weather.danger_window"
    FORECAST_CONFIDENCE = "weather.forecast_confidence"
    FATIGUE_INDEX = "human.fatigue_index"
    ENERGY_RESERVE = "human.energy_reserve"
    COGNITIVE_CONFIDENCE = "human.cognitive_confidence"
    SAFETY_MARGIN = "human.safety_margin"
    MEDICAL_URGENCY = "human.medical_urgency"
    COMMUNICATION_RELIABILITY = "communication.reliability"
    COVERAGE_CONFIDENCE = "communication.coverage_confidence"
    EMERGENCY_REACHABILITY = "communication.emergency_reachability"
    GPS_CONFIDENCE = "navigation.gps_confidence"
    ROUTE_ALIGNMENT = "navigation.route_alignment"
    ROUTE_PROGRESS = "navigation.route_progress"
    CURRENT_HAZARD = "operation.current_hazard"
    TEAM_DISTANCE = "operation.team_distance"
    REMAINING_DAYLIGHT = "operation.remaining_daylight"
    SHELTER_REACHABILITY = "operation.shelter_reachability"
    WATER_MARGIN = "operation.water_margin"
    CAMP_VIABILITY = "operation.camp_viability"
    MISSION_MARGIN = "operation.mission_margin"
    ROUTE_FEASIBILITY = "operation.route_feasibility"
    WILDLIFE_PRESSURE = "operation.wildlife_pressure"
    HISTORICAL_CONTEXT_RELEVANCE = "knowledge.historical_context_relevance"


class SignalAvailability(StrEnum):
    AVAILABLE = "available"
    MISSING = "missing"
    STALE = "stale"
    INVALID = "invalid"


class SufficiencyStatus(StrEnum):
    SUFFICIENT = "sufficient"
    INSUFFICIENT = "insufficient"
    CONTRADICTORY = "contradictory"
    AMBIGUOUS_DECISION = "ambiguous_decision"


class GapKind(StrEnum):
    MISSING = "missing"
    STALE = "stale"
    LOW_CONFIDENCE = "low_confidence"
    CONTRADICTORY = "contradictory"


class DecisionIntent(SchemaModel):
    question: NonEmptyStr
    primary_type: DecisionType
    alternative_types: tuple[DecisionType, ...] = ()
    confidence: float = Field(ge=0.0, le=1.0)
    criticality: DecisionCriticality
    rationale: NonEmptyStr
    classifier: NonEmptyStr = "deterministic_mser_classifier.v0"


class CompactSignal(SchemaModel):
    """One normalized state variable with explicit uncertainty and provenance."""

    signal_id: NonEmptyStr
    dimension: CompactDimension
    value: bool | int | float | str | tuple[str, ...] | dict[str, Any] | None = None
    unit: str | None = None
    availability: SignalAvailability = SignalAvailability.AVAILABLE
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    risk_upper_bound: float | None = Field(default=None, ge=0.0, le=1.0)
    observed_at: datetime | None = None
    valid_until: datetime | None = None
    source_refs: tuple[NonEmptyStr, ...] = ()
    evidence_ids: tuple[NonEmptyStr, ...] = ()
    conflicts_with: tuple[NonEmptyStr, ...] = ()
    derivation: str | None = None
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @model_validator(mode="after")
    def validate_evidence_shape(self) -> "CompactSignal":
        if self.availability == SignalAvailability.AVAILABLE:
            if self.value is None:
                raise ValueError("available compact signal must have a value")
            if not self.source_refs:
                raise ValueError("available compact signal must preserve source_refs")
        return self


class CompactDomainState(SchemaModel):
    """Base class that checks field-to-dimension bindings."""

    _EXPECTED_DIMENSIONS: ClassVar[dict[str, CompactDimension]] = {}

    @model_validator(mode="after")
    def validate_bound_dimensions(self) -> "CompactDomainState":
        for field_name, expected in self._EXPECTED_DIMENSIONS.items():
            signal = getattr(self, field_name)
            if signal is not None and signal.dimension != expected:
                raise ValueError(
                    f"{field_name} must contain dimension {expected.value}, "
                    f"got {signal.dimension.value}"
                )
        return self

    def signals(self) -> tuple[CompactSignal, ...]:
        return tuple(
            signal
            for field_name in self._EXPECTED_DIMENSIONS
            if (signal := getattr(self, field_name)) is not None
        )


class TerrainLatentState(CompactDomainState):
    exposure_risk: CompactSignal | None = None
    slip_risk: CompactSignal | None = None
    rockfall_risk: CompactSignal | None = None
    escape_cost: CompactSignal | None = None
    visibility: CompactSignal | None = None
    terrain_complexity: CompactSignal | None = None
    terrain_confidence: CompactSignal | None = None

    _EXPECTED_DIMENSIONS = {
        "exposure_risk": CompactDimension.EXPOSURE_RISK,
        "slip_risk": CompactDimension.SLIP_RISK,
        "rockfall_risk": CompactDimension.ROCKFALL_RISK,
        "escape_cost": CompactDimension.ESCAPE_COST,
        "visibility": CompactDimension.VISIBILITY,
        "terrain_complexity": CompactDimension.TERRAIN_COMPLEXITY,
        "terrain_confidence": CompactDimension.TERRAIN_CONFIDENCE,
    }


class WeatherLatentState(CompactDomainState):
    weather_stability: CompactSignal | None = None
    weather_trend: CompactSignal | None = None
    danger_window: CompactSignal | None = None
    forecast_confidence: CompactSignal | None = None

    _EXPECTED_DIMENSIONS = {
        "weather_stability": CompactDimension.WEATHER_STABILITY,
        "weather_trend": CompactDimension.WEATHER_TREND,
        "danger_window": CompactDimension.DANGER_WINDOW,
        "forecast_confidence": CompactDimension.FORECAST_CONFIDENCE,
    }


class HumanLatentState(CompactDomainState):
    fatigue_index: CompactSignal | None = None
    energy_reserve: CompactSignal | None = None
    cognitive_confidence: CompactSignal | None = None
    safety_margin: CompactSignal | None = None
    medical_urgency: CompactSignal | None = None

    _EXPECTED_DIMENSIONS = {
        "fatigue_index": CompactDimension.FATIGUE_INDEX,
        "energy_reserve": CompactDimension.ENERGY_RESERVE,
        "cognitive_confidence": CompactDimension.COGNITIVE_CONFIDENCE,
        "safety_margin": CompactDimension.SAFETY_MARGIN,
        "medical_urgency": CompactDimension.MEDICAL_URGENCY,
    }


class CommunicationLatentState(CompactDomainState):
    communication_reliability: CompactSignal | None = None
    coverage_confidence: CompactSignal | None = None
    emergency_reachability: CompactSignal | None = None

    _EXPECTED_DIMENSIONS = {
        "communication_reliability": CompactDimension.COMMUNICATION_RELIABILITY,
        "coverage_confidence": CompactDimension.COVERAGE_CONFIDENCE,
        "emergency_reachability": CompactDimension.EMERGENCY_REACHABILITY,
    }


class OperationalLatentState(CompactDomainState):
    gps_confidence: CompactSignal | None = None
    route_alignment: CompactSignal | None = None
    route_progress: CompactSignal | None = None
    current_hazard: CompactSignal | None = None
    team_distance: CompactSignal | None = None
    remaining_daylight: CompactSignal | None = None
    shelter_reachability: CompactSignal | None = None
    water_margin: CompactSignal | None = None
    camp_viability: CompactSignal | None = None
    mission_margin: CompactSignal | None = None
    route_feasibility: CompactSignal | None = None
    wildlife_pressure: CompactSignal | None = None
    historical_context_relevance: CompactSignal | None = None

    _EXPECTED_DIMENSIONS = {
        "gps_confidence": CompactDimension.GPS_CONFIDENCE,
        "route_alignment": CompactDimension.ROUTE_ALIGNMENT,
        "route_progress": CompactDimension.ROUTE_PROGRESS,
        "current_hazard": CompactDimension.CURRENT_HAZARD,
        "team_distance": CompactDimension.TEAM_DISTANCE,
        "remaining_daylight": CompactDimension.REMAINING_DAYLIGHT,
        "shelter_reachability": CompactDimension.SHELTER_REACHABILITY,
        "water_margin": CompactDimension.WATER_MARGIN,
        "camp_viability": CompactDimension.CAMP_VIABILITY,
        "mission_margin": CompactDimension.MISSION_MARGIN,
        "route_feasibility": CompactDimension.ROUTE_FEASIBILITY,
        "wildlife_pressure": CompactDimension.WILDLIFE_PRESSURE,
        "historical_context_relevance": CompactDimension.HISTORICAL_CONTEXT_RELEVANCE,
    }


class EnvironmentalRepresentation(SchemaModel):
    """Unified compact state presented to the decision layer."""

    representation_id: NonEmptyStr
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    terrain: TerrainLatentState = Field(default_factory=TerrainLatentState)
    weather: WeatherLatentState = Field(default_factory=WeatherLatentState)
    human: HumanLatentState = Field(default_factory=HumanLatentState)
    communication: CommunicationLatentState = Field(
        default_factory=CommunicationLatentState
    )
    operation: OperationalLatentState = Field(default_factory=OperationalLatentState)
    additional_signals: tuple[CompactSignal, ...] = ()
    source_refs: tuple[NonEmptyStr, ...] = ()
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    def all_signals(self) -> tuple[CompactSignal, ...]:
        return (
            *self.terrain.signals(),
            *self.weather.signals(),
            *self.human.signals(),
            *self.communication.signals(),
            *self.operation.signals(),
            *self.additional_signals,
        )


class DimensionRequirement(SchemaModel):
    dimension: CompactDimension
    reason: NonEmptyStr
    minimum_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    max_age_seconds: int | None = Field(default=None, ge=1)
    mandatory: bool = True
    preserve_conflicts: bool = True


class DecisionCompactProfile(SchemaModel):
    profile_id: NonEmptyStr
    decision_type: DecisionType
    requirements: tuple[DimensionRequirement, ...]
    risk_preservation_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    minimum_coverage_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    criticality: DecisionCriticality

    @model_validator(mode="after")
    def validate_unique_requirements(self) -> "DecisionCompactProfile":
        dimensions = [requirement.dimension for requirement in self.requirements]
        if len(dimensions) != len(set(dimensions)):
            raise ValueError("decision profile requirements must be unique")
        return self


class DimensionCoverage(SchemaModel):
    requirement: DimensionRequirement
    selected_signal_ids: tuple[NonEmptyStr, ...] = ()
    status: GapKind | Literal["covered"]
    explanation: NonEmptyStr


class InformationNeed(SchemaModel):
    dimension: CompactDimension
    gap_kind: GapKind
    reason: NonEmptyStr
    minimum_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    max_age_seconds: int | None = Field(default=None, ge=1)
    suggested_capabilities: tuple[NonEmptyStr, ...] = ()


class SufficiencyCertificate(SchemaModel):
    status: SufficiencyStatus
    required_dimension_count: int = Field(ge=0)
    covered_dimension_count: int = Field(ge=0)
    coverage_ratio: float = Field(ge=0.0, le=1.0)
    coverage: tuple[DimensionCoverage, ...]
    missing_dimensions: tuple[CompactDimension, ...] = ()
    stale_dimensions: tuple[CompactDimension, ...] = ()
    low_confidence_dimensions: tuple[CompactDimension, ...] = ()
    contradictory_dimensions: tuple[CompactDimension, ...] = ()
    counterfactual_required_dimensions: tuple[CompactDimension, ...] = ()
    preserved_high_risk_signal_ids: tuple[NonEmptyStr, ...] = ()
    source_refs: tuple[NonEmptyStr, ...] = ()
    explanation: NonEmptyStr


class MinimalSufficientContext(SchemaModel):
    context_id: NonEmptyStr
    intent: DecisionIntent
    profile_id: NonEmptyStr
    selected_signals: tuple[CompactSignal, ...]
    discarded_dimensions: tuple[CompactDimension, ...]
    information_needs: tuple[InformationNeed, ...]
    certificate: SufficiencyCertificate
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


class ToolCapability(SchemaModel):
    tool_id: NonEmptyStr
    produces_dimensions: tuple[CompactDimension, ...]
    availability: Literal["available", "unavailable"] = "available"
    expected_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    expected_latency_ms: int = Field(default=0, ge=0)
    estimated_cost: float = Field(default=0.0, ge=0.0)
    read_only: Literal[True] = True


class PlannedCompactTool(SchemaModel):
    tool_id: NonEmptyStr
    fills_dimensions: tuple[CompactDimension, ...]
    reason: NonEmptyStr


class MinimalToolPlan(SchemaModel):
    selected_tools: tuple[PlannedCompactTool, ...]
    uncovered_dimensions: tuple[CompactDimension, ...]
    coverage_complete: bool
    objective: NonEmptyStr
    max_tool_calls: int = Field(default=10, ge=10)


class MemoryEvent(SchemaModel):
    event_id: NonEmptyStr
    event_type: NonEmptyStr
    observed_at: datetime
    summary: NonEmptyStr
    source_refs: tuple[NonEmptyStr, ...]
    decision_types: tuple[DecisionType, ...] = ()
    importance: float = Field(default=0.0, ge=0.0, le=1.0)
    surprise: float = Field(default=0.0, ge=0.0, le=1.0)
    hazard_severity: float = Field(default=0.0, ge=0.0, le=1.0)
    anomaly: bool = False
    decision_point: bool = False
    detour: bool = False
    stop: bool = False
    cluster_key: str | None = None


class ReducedMemory(SchemaModel):
    selected_events: tuple[MemoryEvent, ...]
    omitted_event_count: int = Field(ge=0)
    raw_event_refs_preserved: tuple[NonEmptyStr, ...]
    reduction_rule: NonEmptyStr


class KnowledgeCandidate(SchemaModel):
    knowledge_id: NonEmptyStr
    summary: NonEmptyStr
    source_refs: tuple[NonEmptyStr, ...]
    supports_dimensions: tuple[CompactDimension, ...]
    decision_types: tuple[DecisionType, ...] = ()
    authority: float = Field(default=0.5, ge=0.0, le=1.0)
    freshness: float = Field(default=0.5, ge=0.0, le=1.0)
    spatial_relevance: float = Field(default=0.5, ge=0.0, le=1.0)
    temporal_relevance: float = Field(default=0.5, ge=0.0, le=1.0)


class ReducedKnowledge(SchemaModel):
    selected_candidates: tuple[KnowledgeCandidate, ...]
    covered_dimensions: tuple[CompactDimension, ...]
    uncovered_dimensions: tuple[CompactDimension, ...]
    source_refs_verified: bool
    reduction_rule: NonEmptyStr


class MSERStage(StrEnum):
    QUESTION_RECEIVED = "question_received"
    DECISION_CLASSIFIED = "decision_classified"
    ENVIRONMENT_PROJECTED = "environment_projected"
    SUFFICIENCY_CHECKED = "sufficiency_checked"
    TOOL_PLAN_READY = "tool_plan_ready"
    RETRIEVING = "retrieving"
    REPROJECTING = "reprojecting"
    READY_TO_REASON = "ready_to_reason"
    ANSWER_VERIFIED = "answer_verified"
    AMBIGUOUS_DECISION = "ambiguous_decision"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CONTRADICTORY_STATE = "contradictory_state"


class MSERTransition(SchemaModel):
    from_stage: MSERStage
    to_stage: MSERStage
    guard: NonEmptyStr
    deterministic_owner: Literal[True] = True


class MSERDecisionPacket(SchemaModel):
    intent: DecisionIntent
    compact_context: MinimalSufficientContext
    tool_plan: MinimalToolPlan
    next_stage: MSERStage


__all__ = [
    "CompactDimension",
    "CompactSignal",
    "CommunicationLatentState",
    "DecisionCompactProfile",
    "DecisionCriticality",
    "DecisionIntent",
    "DecisionType",
    "DimensionCoverage",
    "DimensionRequirement",
    "EnvironmentalRepresentation",
    "GapKind",
    "HumanLatentState",
    "InformationNeed",
    "KnowledgeCandidate",
    "MSERDecisionPacket",
    "MSERStage",
    "MSERTransition",
    "MemoryEvent",
    "MinimalSufficientContext",
    "MinimalToolPlan",
    "OperationalLatentState",
    "PlannedCompactTool",
    "ReducedKnowledge",
    "ReducedMemory",
    "SignalAvailability",
    "SufficiencyCertificate",
    "SufficiencyStatus",
    "TerrainLatentState",
    "ToolCapability",
    "WeatherLatentState",
]
