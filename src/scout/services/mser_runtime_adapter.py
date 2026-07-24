"""Bridge MSER capability plans into Scout's bounded read-only runtime.

This module deliberately uses explicit capability metadata. Tool names, labels,
and user text are never interpreted as capability evidence. Unknown tools fail
closed until their produced MSER dimensions are reviewed and registered here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any, Literal

from pydantic import Field

from scout.schemas.agent_runtime import (
    AgentRunBudget,
    EvidenceCard,
    EvidenceRecord,
    ToolCard,
    ToolPlan,
)
from scout.schemas.base import NonEmptyStr, SchemaModel
from scout.schemas.mser import (
    CompactDimension,
    MinimalToolPlan,
    ToolCapability,
)
from scout.services.bounded_agent_runtime import BoundedAgentRuntime
from scout_ai_tool_contracts import (
    ScoutAiToolContract,
    ScoutAiToolRegistryOutput,
    resolve_scout_ai_tool_id,
    tool_registry_output,
)

MINIMUM_CONSTRUCTION_CALL_CAPACITY = 10
MAX_REPROJECTION_SOURCE_REFS = 32
MAX_REPROJECTION_EVIDENCE_RECORDS = 64
MAX_REPROJECTION_MISSING_FIELDS = 64
MAX_REPROJECTION_KEY_VALUES = 64


class UnknownMSERToolCapabilityError(LookupError):
    """Raised when no reviewed MSER capability metadata exists for a tool."""


class UnsafeMSERToolCapabilityError(ValueError):
    """Raised when a registry contract crosses the read-only MSER boundary."""


class BoundedReprojectionPayload(SchemaModel):
    """Small deterministic payload consumed by a later MSER reprojector."""

    tool_id: NonEmptyStr
    produces_dimensions: tuple[CompactDimension, ...]
    claim_summary: str = ""
    key_values: dict[str, Any] = Field(default_factory=dict)
    missing_fields: tuple[str, ...] = ()
    freshness: NonEmptyStr = "unknown"
    quality: NonEmptyStr = "unknown"
    source_refs: tuple[NonEmptyStr, ...] = ()
    evidence_records: tuple[EvidenceRecord, ...] = ()
    result_count: int = Field(default=0, ge=0)
    truncated: bool = False
    continuation_handle: str | None = None
    reprojection_ready: bool = False
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


def _dimensions(*values: CompactDimension) -> tuple[CompactDimension, ...]:
    return values


# Reviewed, deterministic metadata for every currently executable Scout tool.
# A broad search tool intentionally receives only the dimensions its direct
# output can support; catalog discovery is not treated as environmental proof.
TOOL_CAPABILITY_DIMENSIONS: Mapping[str, tuple[CompactDimension, ...]] = (
    MappingProxyType(
        {
            "assistant_skill.live_navigation.nmea_route_risk.v0": _dimensions(
                CompactDimension.GPS_CONFIDENCE,
                CompactDimension.ROUTE_ALIGNMENT,
                CompactDimension.ROUTE_PROGRESS,
                CompactDimension.CURRENT_HAZARD,
            ),
            "pydantic_ai.tool.search_scout_evidence_fulltext.v0": _dimensions(
                CompactDimension.CURRENT_HAZARD,
                CompactDimension.HISTORICAL_CONTEXT_RELEVANCE,
            ),
            "pydantic_ai.tool.search_scout_major_points.v0": _dimensions(
                CompactDimension.ROUTE_PROGRESS,
                CompactDimension.SHELTER_REACHABILITY,
            ),
            "pydantic_ai.tool.search_scout_map_perception.v0": _dimensions(
                CompactDimension.ROUTE_ALIGNMENT,
                CompactDimension.CURRENT_HAZARD,
                CompactDimension.VISIBILITY,
                CompactDimension.TERRAIN_COMPLEXITY,
                CompactDimension.TERRAIN_CONFIDENCE,
            ),
            "pydantic_ai.tool.search_scout_risk_scores.v0": _dimensions(
                CompactDimension.CURRENT_HAZARD,
                CompactDimension.EXPOSURE_RISK,
                CompactDimension.SLIP_RISK,
                CompactDimension.ROCKFALL_RISK,
            ),
            "pydantic_ai.tool.search_scout_route_structure.v0": _dimensions(
                CompactDimension.ROUTE_ALIGNMENT,
                CompactDimension.ROUTE_PROGRESS,
                CompactDimension.ROUTE_FEASIBILITY,
                CompactDimension.ESCAPE_COST,
                CompactDimension.SHELTER_REACHABILITY,
            ),
            "pydantic_ai.tool.search_scout_terrain_scores.v0": _dimensions(
                CompactDimension.EXPOSURE_RISK,
                CompactDimension.SLIP_RISK,
                CompactDimension.ROCKFALL_RISK,
                CompactDimension.ESCAPE_COST,
                CompactDimension.TERRAIN_COMPLEXITY,
                CompactDimension.TERRAIN_CONFIDENCE,
            ),
            "pydantic_ai.tool.search_scout_workspace_catalog.v0": _dimensions(
                CompactDimension.ROUTE_PROGRESS,
                CompactDimension.HISTORICAL_CONTEXT_RELEVANCE,
            ),
            "scout.ai.contextual_permission.assess.v0": _dimensions(
                CompactDimension.CURRENT_HAZARD,
                CompactDimension.ESCAPE_COST,
                CompactDimension.SAFETY_MARGIN,
                CompactDimension.MISSION_MARGIN,
            ),
            "scout.ai.cwa_environment.assess.v0": _dimensions(
                CompactDimension.WEATHER_STABILITY,
                CompactDimension.WEATHER_TREND,
                CompactDimension.DANGER_WINDOW,
                CompactDimension.FORECAST_CONFIDENCE,
                CompactDimension.REMAINING_DAYLIGHT,
            ),
            "scout.ai.energy_vitals.assess.v0": _dimensions(
                CompactDimension.FATIGUE_INDEX,
                CompactDimension.ENERGY_RESERVE,
                CompactDimension.COGNITIVE_CONFIDENCE,
                CompactDimension.SAFETY_MARGIN,
                CompactDimension.MEDICAL_URGENCY,
            ),
            "scout.ai.equipment_resource.assess.v0": _dimensions(
                CompactDimension.WATER_MARGIN,
                CompactDimension.COMMUNICATION_RELIABILITY,
                CompactDimension.MISSION_MARGIN,
                CompactDimension.SAFETY_MARGIN,
            ),
            "scout.ai.gee_environment.assess.v0": _dimensions(
                CompactDimension.SLIP_RISK,
                CompactDimension.ROCKFALL_RISK,
                CompactDimension.CURRENT_HAZARD,
                CompactDimension.TERRAIN_CONFIDENCE,
                CompactDimension.WEATHER_TREND,
            ),
            "scout.ai.ins_dr_trace.analyze.v0": _dimensions(
                CompactDimension.GPS_CONFIDENCE,
                CompactDimension.ROUTE_ALIGNMENT,
                CompactDimension.ROUTE_PROGRESS,
            ),
            "scout.ai.live_navigation_state.assess.v0": _dimensions(
                CompactDimension.GPS_CONFIDENCE,
                CompactDimension.ROUTE_ALIGNMENT,
                CompactDimension.ROUTE_PROGRESS,
                CompactDimension.CURRENT_HAZARD,
            ),
            "scout.ai.media_literacy.assess.v0": _dimensions(
                CompactDimension.HISTORICAL_CONTEXT_RELEVANCE,
                CompactDimension.FORECAST_CONFIDENCE,
            ),
            "scout.ai.navigation_terrain.assess.v0": _dimensions(
                CompactDimension.GPS_CONFIDENCE,
                CompactDimension.ROUTE_ALIGNMENT,
                CompactDimension.ROUTE_PROGRESS,
                CompactDimension.EXPOSURE_RISK,
                CompactDimension.SLIP_RISK,
                CompactDimension.ROCKFALL_RISK,
                CompactDimension.ESCAPE_COST,
                CompactDimension.TERRAIN_COMPLEXITY,
                CompactDimension.TERRAIN_CONFIDENCE,
            ),
            "scout.ai.pace_guardian.assess.v0": _dimensions(
                CompactDimension.FATIGUE_INDEX,
                CompactDimension.ENERGY_RESERVE,
                CompactDimension.TEAM_DISTANCE,
                CompactDimension.ROUTE_PROGRESS,
                CompactDimension.MISSION_MARGIN,
            ),
            "scout.ai.post_trip_review.assess.v0": _dimensions(
                CompactDimension.CURRENT_HAZARD,
                CompactDimension.ROUTE_PROGRESS,
                CompactDimension.ROUTE_ALIGNMENT,
                CompactDimension.TEAM_DISTANCE,
                CompactDimension.ENERGY_RESERVE,
            ),
            "scout.ai.review_gap.assess.v0": _dimensions(
                CompactDimension.TERRAIN_CONFIDENCE,
                CompactDimension.FORECAST_CONFIDENCE,
                CompactDimension.COVERAGE_CONFIDENCE,
                CompactDimension.GPS_CONFIDENCE,
            ),
            "scout.ai.route_architecture.assess.v0": _dimensions(
                CompactDimension.ROUTE_PROGRESS,
                CompactDimension.ROUTE_FEASIBILITY,
                CompactDimension.ESCAPE_COST,
                CompactDimension.SHELTER_REACHABILITY,
                CompactDimension.CAMP_VIABILITY,
            ),
            "scout.ai.route_context.assess.v0": _dimensions(
                CompactDimension.ROUTE_PROGRESS,
                CompactDimension.HISTORICAL_CONTEXT_RELEVANCE,
            ),
            "scout.ai.route_readiness.assess.v0": _dimensions(
                CompactDimension.ROUTE_FEASIBILITY,
                CompactDimension.MISSION_MARGIN,
                CompactDimension.WEATHER_STABILITY,
                CompactDimension.SAFETY_MARGIN,
            ),
            "scout.ai.runtime_ingress_status.search.v0": _dimensions(
                CompactDimension.COMMUNICATION_RELIABILITY,
                CompactDimension.COVERAGE_CONFIDENCE,
                CompactDimension.GPS_CONFIDENCE,
            ),
            "scout.ai.safety_boundary.explain.v0": _dimensions(
                CompactDimension.CURRENT_HAZARD,
                CompactDimension.SAFETY_MARGIN,
                CompactDimension.MISSION_MARGIN,
            ),
            "scout.ai.survival_incident_playbook.explain.v0": _dimensions(
                CompactDimension.EMERGENCY_REACHABILITY,
                CompactDimension.SHELTER_REACHABILITY,
                CompactDimension.CAMP_VIABILITY,
            ),
            "scout.ai.team_status.assess.v0": _dimensions(
                CompactDimension.TEAM_DISTANCE,
                CompactDimension.COMMUNICATION_RELIABILITY,
                CompactDimension.COVERAGE_CONFIDENCE,
                CompactDimension.EMERGENCY_REACHABILITY,
                CompactDimension.FATIGUE_INDEX,
            ),
            "scout.ai.weather_window.assess.v0": _dimensions(
                CompactDimension.WEATHER_STABILITY,
                CompactDimension.WEATHER_TREND,
                CompactDimension.DANGER_WINDOW,
                CompactDimension.FORECAST_CONFIDENCE,
                CompactDimension.REMAINING_DAYLIGHT,
            ),
            "scout.ai.workspace.query.v1": _dimensions(
                CompactDimension.ROUTE_PROGRESS,
                CompactDimension.ROUTE_FEASIBILITY,
                CompactDimension.MISSION_MARGIN,
                CompactDimension.HISTORICAL_CONTEXT_RELEVANCE,
            ),
        }
    )
)


def build_tool_capabilities(
    *,
    registry: ScoutAiToolRegistryOutput | None = None,
    selected_tool_cards: Sequence[ToolCard] = (),
) -> tuple[ToolCapability, ...]:
    """Build capabilities from reviewed metadata and current registry state."""

    selected_ids = tuple(
        dict.fromkeys(
            resolve_scout_ai_tool_id(card.tool_id) for card in selected_tool_cards
        )
    )
    resolved_registry = registry or tool_registry_output(
        include_not_implemented=False,
        tool_ids=list(selected_ids) if selected_ids else None,
    )
    contracts = {contract.tool_id: contract for contract in resolved_registry.tools}
    card_by_id = {
        resolve_scout_ai_tool_id(card.tool_id): card for card in selected_tool_cards
    }
    requested_ids = selected_ids or tuple(contracts)

    capabilities: list[ToolCapability] = []
    for tool_id in requested_ids:
        dimensions = TOOL_CAPABILITY_DIMENSIONS.get(tool_id)
        if dimensions is None:
            raise UnknownMSERToolCapabilityError(
                f"no reviewed MSER capability metadata for tool: {tool_id}"
            )
        contract = contracts.get(tool_id)
        if contract is None:
            raise UnknownMSERToolCapabilityError(
                f"tool is not present in the executable Scout registry: {tool_id}"
            )
        _validate_read_only_contract(contract)
        card = card_by_id.get(tool_id)
        available = card is None or (
            card.availability == "available"
            and card.implementation_status == "ready_current_tool"
        )
        capabilities.append(
            ToolCapability(
                tool_id=tool_id,
                produces_dimensions=dimensions,
                availability="available" if available else "unavailable",
                expected_confidence=_expected_confidence(tool_id),
                expected_latency_ms=_expected_latency_ms(tool_id),
                estimated_cost=max(0.0, card.estimated_cost) if card else 0.0,
            )
        )
    return tuple(capabilities)


class MSERRuntimeAdapter:
    """Adapt reviewed MSER plans and evidence to bounded runtime contracts."""

    def __init__(
        self,
        *,
        registry: ScoutAiToolRegistryOutput | None = None,
        selected_tool_cards: Sequence[ToolCard] = (),
        budget: AgentRunBudget | None = None,
    ) -> None:
        self.budget = budget or AgentRunBudget()
        if self.budget.max_tool_calls < MINIMUM_CONSTRUCTION_CALL_CAPACITY:
            raise ValueError("MSER runtime requires at least 10 tool calls per attempt")
        self._capabilities = build_tool_capabilities(
            registry=registry,
            selected_tool_cards=selected_tool_cards,
        )
        self._capability_by_id = {
            capability.tool_id: capability for capability in self._capabilities
        }
        self._runtime = BoundedAgentRuntime(
            tool_cards=selected_tool_cards,
            budget=self.budget,
        )

    @property
    def capabilities(self) -> tuple[ToolCapability, ...]:
        return self._capabilities

    def capability_for(self, tool_id: str) -> ToolCapability:
        capability = self._capability_by_id.get(tool_id)
        if capability is None:
            canonical_id = resolve_scout_ai_tool_id(tool_id)
            capability = self._capability_by_id.get(canonical_id)
        if capability is None:
            raise UnknownMSERToolCapabilityError(
                f"tool is not available to this MSER adapter: {tool_id}"
            )
        return capability

    def to_bounded_tool_plan(
        self,
        plan: MinimalToolPlan,
        *,
        arguments_by_tool: Mapping[str, dict[str, Any]] | None = None,
    ) -> ToolPlan:
        """Validate an MSER plan and convert it to the existing ToolPlan."""

        if plan.max_tool_calls < MINIMUM_CONSTRUCTION_CALL_CAPACITY:
            raise ValueError("MSER plan must preserve at least 10-call capacity")
        if plan.max_tool_calls > self.budget.max_tool_calls:
            raise ValueError(
                "bounded runtime budget is smaller than the MSER plan capacity"
            )
        if len(plan.selected_tools) > self.budget.max_tool_calls:
            raise ValueError("MSER tool plan exceeds the bounded runtime capacity")

        selected_ids: list[str] = []
        reasons: dict[str, str] = {}
        expectations: dict[str, list[str]] = {}
        for compact_tool in plan.selected_tools:
            capability = self.capability_for(compact_tool.tool_id)
            if capability.availability != "available":
                raise ValueError(f"MSER tool is unavailable: {capability.tool_id}")
            undeclared = set(compact_tool.fills_dimensions).difference(
                capability.produces_dimensions
            )
            if undeclared:
                values = ", ".join(sorted(dimension.value for dimension in undeclared))
                raise ValueError(
                    f"{capability.tool_id} does not declare MSER dimensions: {values}"
                )
            selected_ids.append(capability.tool_id)
            reasons[capability.tool_id] = (
                f"{compact_tool.reason} Execute as read-only candidate evidence; "
                "do not mutate Phase 1 safety state."
            )
            expectations[capability.tool_id] = [
                *(dimension.value for dimension in compact_tool.fills_dimensions),
                "source_refs",
                "evidence_records",
                "freshness",
                "quality",
                "candidate_only=true",
                "runtime_safety_truth=false",
            ]

        bounded = self._runtime.build_tool_plan(
            selected_tool_ids=selected_ids,
            arguments_by_tool=arguments_by_tool,
            reasons_by_tool=reasons,
            expected_evidence_by_tool=expectations,
            compound=len(selected_ids) > 1,
        )
        missing_dimensions = [
            dimension.value for dimension in plan.uncovered_dimensions
        ]
        return bounded.model_copy(
            update={
                "required_bundle_expansion": missing_dimensions,
                "stop_or_replan_condition": (
                    "Stop after sufficient, source-verified MSER evidence; otherwise "
                    f"reproject and continue within this stage's "
                    f"{self.budget.max_tool_calls}-call capacity (minimum 10)."
                ),
            }
        )

    def to_reprojection_payload(
        self,
        evidence: EvidenceCard | Any,
        *,
        tool_id: str | None = None,
    ) -> BoundedReprojectionPayload:
        """Convert a card or raw tool result into a bounded reprojector input."""

        if isinstance(evidence, EvidenceCard):
            card = evidence
            if (
                tool_id is not None
                and self.capability_for(tool_id).tool_id
                != self.capability_for(card.tool_id).tool_id
            ):
                raise ValueError("tool_id does not match EvidenceCard.tool_id")
        else:
            if tool_id is None:
                raise ValueError("tool_id is required for a raw tool output")
            canonical_id = self.capability_for(tool_id).tool_id
            card = self._runtime.evidence_from_tool_result(canonical_id, evidence)

        capability = self.capability_for(card.tool_id)
        source_refs = tuple(dict.fromkeys(card.source_refs))[
            :MAX_REPROJECTION_SOURCE_REFS
        ]
        missing_fields = list(dict.fromkeys(card.missing_fields))
        if not source_refs and "source_refs" not in missing_fields:
            missing_fields.append("source_refs")
        missing_fields = missing_fields[:MAX_REPROJECTION_MISSING_FIELDS]
        evidence_records = tuple(card.evidence_records)[
            :MAX_REPROJECTION_EVIDENCE_RECORDS
        ]
        key_values = dict(list(card.key_values.items())[:MAX_REPROJECTION_KEY_VALUES])
        invalid_quality = card.quality.casefold() in {
            "invalid",
            "withheld",
            "unavailable",
        }
        return BoundedReprojectionPayload(
            tool_id=capability.tool_id,
            produces_dimensions=capability.produces_dimensions,
            claim_summary=card.claim_summary,
            key_values=key_values,
            missing_fields=tuple(missing_fields),
            freshness=card.freshness,
            quality=card.quality,
            source_refs=source_refs,
            evidence_records=evidence_records,
            result_count=card.result_count,
            truncated=card.truncated,
            continuation_handle=card.continuation_handle,
            reprojection_ready=bool(source_refs) and not invalid_quality,
        )


def _validate_read_only_contract(contract: ScoutAiToolContract) -> None:
    boundary = contract.boundary
    forbidden = {
        "read_only": not boundary.read_only,
        "runtime_safety_truth": boundary.runtime_safety_truth,
        "live_safety_api_calls_allowed": boundary.live_safety_api_calls_allowed,
        "phase1_safety_mutation_allowed": boundary.phase1_safety_mutation_allowed,
        "remote_outbound_send_allowed": boundary.remote_outbound_send_allowed,
        "hardware_control_allowed": boundary.hardware_control_allowed,
        "model_output_is_runtime_truth": boundary.model_output_is_runtime_truth,
    }
    violations = sorted(name for name, violated in forbidden.items() if violated)
    if violations:
        raise UnsafeMSERToolCapabilityError(
            f"tool crosses MSER read-only boundary: {contract.tool_id}: "
            f"{', '.join(violations)}"
        )


def _expected_confidence(tool_id: str) -> float:
    if tool_id in {
        "scout.ai.live_navigation_state.assess.v0",
        "assistant_skill.live_navigation.nmea_route_risk.v0",
        "scout.ai.runtime_ingress_status.search.v0",
    }:
        return 0.65
    if tool_id in {
        "scout.ai.cwa_environment.assess.v0",
        "scout.ai.gee_environment.assess.v0",
        "scout.ai.weather_window.assess.v0",
    }:
        return 0.7
    return 0.75


def _expected_latency_ms(tool_id: str) -> int:
    if tool_id in {
        "scout.ai.cwa_environment.assess.v0",
        "scout.ai.gee_environment.assess.v0",
    }:
        return 750
    return 250


__all__ = [
    "BoundedReprojectionPayload",
    "MINIMUM_CONSTRUCTION_CALL_CAPACITY",
    "MSERRuntimeAdapter",
    "TOOL_CAPABILITY_DIMENSIONS",
    "UnknownMSERToolCapabilityError",
    "UnsafeMSERToolCapabilityError",
    "build_tool_capabilities",
]
