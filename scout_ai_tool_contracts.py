from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scout_safety_boundary_tool import (
    SAFETY_ADMISSION_OPTIONAL_FIELDS,
    SAFETY_ADMISSION_REQUIRED_FIELDS,
    SAFETY_BOUNDARY_OUTPUT_KIND,
    SAFETY_BOUNDARY_TOOL_ID,
)
from scout_live_navigation_state_tool import (
    LIVE_NAVIGATION_OPTIONAL_FIELDS,
    LIVE_NAVIGATION_REQUIRED_FIELDS,
    LIVE_NAVIGATION_STATE_OUTPUT_KIND,
    LIVE_NAVIGATION_STATE_TOOL_ID,
    NMEA_ROUTE_RISK_PROBE_TOOL_ID,
)
from scout_navigation_terrain_tool import (
    NAVIGATION_TERRAIN_OPTIONAL_FIELDS,
    NAVIGATION_TERRAIN_OUTPUT_KIND,
    NAVIGATION_TERRAIN_TOOL_ID,
)
from scout_ins_dr_trace_tool import (
    INS_DR_TRACE_OUTPUT_KIND,
    INS_DR_TRACE_TOOL_ID,
)
from scout_energy_vitals_tool import (
    ENERGY_VITALS_OUTPUT_KIND,
    ENERGY_VITALS_OPTIONAL_FIELDS,
    ENERGY_VITALS_REQUIRED_FIELDS,
    ENERGY_VITALS_TOOL_ID,
)
from scout_weather_window_tool import (
    WEATHER_WINDOW_OPTIONAL_FIELDS,
    WEATHER_WINDOW_OUTPUT_KIND,
    WEATHER_WINDOW_REQUIRED_FIELDS,
    WEATHER_WINDOW_TOOL_ID,
)
from scout_cwa_environment_tool import (
    CWA_ENVIRONMENT_OPTIONAL_FIELDS,
    CWA_ENVIRONMENT_OUTPUT_KIND,
    CWA_ENVIRONMENT_TOOL_ID,
)
from scout_gee_environment_tool import (
    GEE_ENVIRONMENT_OPTIONAL_FIELDS,
    GEE_ENVIRONMENT_OUTPUT_KIND,
    GEE_ENVIRONMENT_TOOL_ID,
)
from scout_route_readiness_tool import (
    ROUTE_READINESS_OPTIONAL_FIELDS,
    ROUTE_READINESS_OUTPUT_KIND,
    ROUTE_READINESS_TOOL_ID,
)
from scout_contextual_permission_tool import (
    CONTEXTUAL_PERMISSION_OPTIONAL_FIELDS,
    CONTEXTUAL_PERMISSION_OUTPUT_KIND,
    CONTEXTUAL_PERMISSION_TOOL_ID,
)
from scout_route_context_tool import (
    ROUTE_CONTEXT_OPTIONAL_FIELDS,
    ROUTE_CONTEXT_OUTPUT_KIND,
    ROUTE_CONTEXT_TOOL_ID,
)
from scout_pace_guardian_tool import (
    PACE_GUARDIAN_OPTIONAL_FIELDS,
    PACE_GUARDIAN_OUTPUT_KIND,
    PACE_GUARDIAN_TOOL_ID,
)
from scout_equipment_resource_tool import (
    EQUIPMENT_RESOURCE_OPTIONAL_FIELDS,
    EQUIPMENT_RESOURCE_OUTPUT_KIND,
    EQUIPMENT_RESOURCE_TOOL_ID,
)
from scout_team_status_tool import (
    TEAM_STATUS_OPTIONAL_FIELDS,
    TEAM_STATUS_OUTPUT_KIND,
    TEAM_STATUS_TOOL_ID,
)
from scout_post_trip_review_tool import (
    POST_TRIP_REVIEW_OPTIONAL_FIELDS,
    POST_TRIP_REVIEW_OUTPUT_KIND,
    POST_TRIP_REVIEW_TOOL_ID,
)
from scout_review_gap_tool import (
    REVIEW_GAP_OPTIONAL_FIELDS,
    REVIEW_GAP_OUTPUT_KIND,
    REVIEW_GAP_REQUIRED_FIELDS,
    REVIEW_GAP_TOOL_ID,
)
from scout_route_architecture_tool import (
    ROUTE_ARCHITECTURE_OPTIONAL_FIELDS,
    ROUTE_ARCHITECTURE_OUTPUT_KIND,
    ROUTE_ARCHITECTURE_TOOL_ID,
)
from scout_media_literacy_tool import (
    MEDIA_LITERACY_OPTIONAL_FIELDS,
    MEDIA_LITERACY_OUTPUT_KIND,
    MEDIA_LITERACY_TOOL_ID,
)
from scout_survival_incident_playbook_tool import (
    SURVIVAL_INCIDENT_PLAYBOOK_OPTIONAL_FIELDS,
    SURVIVAL_INCIDENT_PLAYBOOK_OUTPUT_KIND,
    SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID,
)
from scout_runtime_ingress_status_tool import (
    RUNTIME_INGRESS_STATUS_OPTIONAL_FIELDS,
    RUNTIME_INGRESS_STATUS_OUTPUT_KIND,
    RUNTIME_INGRESS_STATUS_REQUIRED_FIELDS,
    RUNTIME_INGRESS_STATUS_TOOL_ID,
)
from scout_workspace_query_tool import (
    WORKSPACE_QUERY_OUTPUT_KIND,
    WORKSPACE_QUERY_TOOL_ID,
    workspace_query_request_json_schema,
)

ARTIFACT_KIND_REGISTRY = "scout_ai_tool_registry"
ARTIFACT_VERSION_REGISTRY = "scout_ai_tool_registry.v0"
ARTIFACT_KIND_RESULT = "scout_ai_tool_result"
ARTIFACT_VERSION_RESULT = "scout_ai_tool_result.v0"

REPO_ROOT = Path(__file__).resolve().parent
MATRIX_PATH = REPO_ROOT / "docs/specs/scout-ai-135-tool-data-workflow-matrix.json"

SENSITIVE_KEY_FRAGMENTS = (
    "api_key",
    "auth",
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
)


class ScoutAiToolBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScoutAiToolStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    MISSING_INPUT = "missing_input"
    NOT_IMPLEMENTED = "not_implemented"


class ScoutAiToolImplementationStatus(StrEnum):
    READY_CURRENT_TOOL = "ready_current_tool"
    PARTIAL_EXISTING_SURFACE = "partial_existing_surface"
    NEW_AGENT_TOOL_NEEDED = "new_agent_tool_needed"
    BOUNDARY_EXPLAIN_ONLY = "boundary_explain_only"


class ScoutAiToolBoundary(ScoutAiToolBaseModel):
    read_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    live_safety_api_calls_allowed: Literal[False] = False
    phase1_safety_mutation_allowed: Literal[False] = False
    remote_outbound_send_allowed: Literal[False] = False
    hardware_control_allowed: Literal[False] = False
    raw_payloads_embedded: Literal[False] = False
    model_output_is_runtime_truth: Literal[False] = False


class ScoutAiToolContract(ScoutAiToolBaseModel):
    tool_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    implementation_status: ScoutAiToolImplementationStatus
    description: str = Field(min_length=1)
    data_bundles: list[str] = Field(default_factory=list)
    required_fields: list[str] = Field(default_factory=list)
    optional_fields: list[str] = Field(default_factory=list)
    workflow_steps: list[str] = Field(default_factory=list)
    existing_support: list[str] = Field(default_factory=list)
    implementation_gap: str | None = None
    argument_schema: dict[str, Any] = Field(default_factory=dict)
    output_artifact_kind: str = "scout_ai_tool_payload"
    aliases: list[str] = Field(default_factory=list)
    boundary: ScoutAiToolBoundary = Field(default_factory=ScoutAiToolBoundary)


class ScoutAiToolRequest(ScoutAiToolBaseModel):
    tool_id: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    project_root: str | None = None
    query: str | None = None
    limit: int | None = Field(default=None, ge=1, le=50)
    request_id: str | None = None
    agent_run_id: str | None = None

    @model_validator(mode="after")
    def reject_secret_like_argument_keys(self) -> "ScoutAiToolRequest":
        _reject_secret_like_keys(self.arguments, path="arguments")
        return self


class ScoutAiToolResult(ScoutAiToolBaseModel):
    artifact_kind: Literal["scout_ai_tool_result"] = ARTIFACT_KIND_RESULT
    artifact_version: Literal["scout_ai_tool_result.v0"] = ARTIFACT_VERSION_RESULT
    tool_id: str = Field(min_length=1)
    request_id: str | None = None
    agent_run_id: str | None = None
    status: ScoutAiToolStatus
    implementation_status: ScoutAiToolImplementationStatus | None = None
    output_artifact_kind: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    boundary: ScoutAiToolBoundary = Field(default_factory=ScoutAiToolBoundary)


class ScoutAiToolRegistryOutput(ScoutAiToolBaseModel):
    artifact_kind: Literal["scout_ai_tool_registry"] = ARTIFACT_KIND_REGISTRY
    artifact_version: Literal["scout_ai_tool_registry.v0"] = ARTIFACT_VERSION_REGISTRY
    tool_count: int = Field(ge=0)
    ready_current_tool_count: int = Field(default=0, ge=0)
    executable_tool_count: int = Field(default=0, ge=0)
    contract_only_tool_count: int = Field(default=0, ge=0)
    implementation_status_counts: dict[str, int] = Field(default_factory=dict)
    tool_ids_by_status: dict[str, list[str]] = Field(default_factory=dict)
    missing_evidence_fields_by_tool: dict[str, list[str]] = Field(default_factory=dict)
    tools: list[ScoutAiToolContract] = Field(default_factory=list)
    boundary: ScoutAiToolBoundary = Field(default_factory=ScoutAiToolBoundary)


EXECUTABLE_TOOL_ALIASES: dict[str, list[str]] = {
    WORKSPACE_QUERY_TOOL_ID: [
        "scout.ai.workspace_query",
        "scout.ai.workspace.query",
    ],
    "pydantic_ai.tool.search_scout_workspace_catalog.v0": [
        "scout.ai.workspace_catalog.search",
    ],
    "pydantic_ai.tool.search_scout_route_structure.v0": [
        "scout.ai.route_structure.search",
    ],
    "pydantic_ai.tool.search_scout_major_points.v0": [
        "scout.ai.major_points.search",
    ],
    "pydantic_ai.tool.search_scout_evidence_fulltext.v0": [
        "scout.ai.evidence_fulltext.search",
    ],
    "pydantic_ai.tool.search_scout_risk_scores.v0": [
        "scout.ai.risk_scores.search",
        "scout.ai.risk_score.search",
    ],
    "pydantic_ai.tool.search_scout_terrain_scores.v0": [
        "scout.ai.terrain_scores.search",
        "scout.ai.slope_scores.search",
    ],
    "pydantic_ai.tool.search_scout_map_perception.v0": [
        "scout.ai.map_perception.search",
    ],
    INS_DR_TRACE_TOOL_ID: [
        "scout.ai.ins_dr_trace.analyze",
    ],
    LIVE_NAVIGATION_STATE_TOOL_ID: [
        "scout.ai.live_navigation_state.assess",
    ],
    NMEA_ROUTE_RISK_PROBE_TOOL_ID: [
        "assistant_skill.live_navigation.nmea_route_risk",
        "scout.ai.nmea_live_navigation_probe.assess",
        "scout.ai.live_navigation.nmea_route_risk",
    ],
    NAVIGATION_TERRAIN_TOOL_ID: [
        "scout.ai.navigation_terrain.assess",
        "scout.ai.map_readiness.assess",
        "scout.ai.navigation_readiness.assess",
    ],
    SAFETY_BOUNDARY_TOOL_ID: [
        "scout.ai.safety_boundary.explain",
        "scout.ai.safety_boundary.assess",
        "scout.ai.runtime_admission.assess",
        "scout.ai.admission_boundary.assess",
    ],
    ENERGY_VITALS_TOOL_ID: [
        "scout.ai.energy_vitals.assess",
    ],
    WEATHER_WINDOW_TOOL_ID: [
        "scout.ai.weather_window.assess",
    ],
    CWA_ENVIRONMENT_TOOL_ID: [
        "scout.ai.cwa_environment.assess",
        "scout.ai.cwa_weather_environment.assess",
        "scout.ai.cwa_weather.assess",
    ],
    GEE_ENVIRONMENT_TOOL_ID: [
        "scout.ai.gee_environment.assess",
        "scout.ai.smap_gpm_environment.assess",
        "scout.ai.hydrology_environment.assess",
    ],
    ROUTE_READINESS_TOOL_ID: [
        "scout.ai.route_readiness.assess",
        "scout.ai.departure_gate.assess",
        "scout.ai.pretrip_go_no_go.assess",
    ],
    CONTEXTUAL_PERMISSION_TOOL_ID: [
        "scout.ai.contextual_permission.assess",
        "scout.ai.micro_decision.assess",
        "scout.ai.risk_budget.permission",
    ],
    ROUTE_CONTEXT_TOOL_ID: [
        "scout.ai.route_context.assess",
        "scout.ai.experience_guide.assess",
    ],
    PACE_GUARDIAN_TOOL_ID: [
        "scout.ai.pace_guardian.assess",
        "scout.ai.team_pace_fit.assess",
        "scout.ai.readiness_pace_fit.assess",
    ],
    EQUIPMENT_RESOURCE_TOOL_ID: [
        "scout.ai.equipment_resource.assess",
        "scout.ai.device_resource.assess",
        "scout.ai.gear_readiness.assess",
    ],
    TEAM_STATUS_TOOL_ID: [
        "scout.ai.team_status.assess",
        "scout.ai.team_guardian.assess",
        "scout.ai.remote_contact.assess",
    ],
    POST_TRIP_REVIEW_TOOL_ID: [
        "scout.ai.post_trip_review.assess",
        "scout.ai.after_action.assess",
        "scout.ai.learning_review.assess",
    ],
    REVIEW_GAP_TOOL_ID: [
        "scout.ai.review_gap.assess",
        "scout.ai.provenance_gap.assess",
        "scout.ai.review_provenance.assess",
    ],
    ROUTE_ARCHITECTURE_TOOL_ID: [
        "scout.ai.route_architecture.assess",
        "scout.ai.cp_graph.assess",
        "scout.ai.turn_back.assess",
    ],
    MEDIA_LITERACY_TOOL_ID: [
        "scout.ai.media_literacy.assess",
        "scout.ai.media_bias.assess",
        "scout.ai.bias_sentinel.assess",
    ],
    SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID: [
        "scout.ai.survival_incident_playbook.explain",
        "scout.ai.incident_playbook.explain",
        "scout.ai.sos_playbook.explain",
    ],
    RUNTIME_INGRESS_STATUS_TOOL_ID: [
        "scout.ai.runtime_ingress_status.search",
        "scout.ai.ingress_status.search",
        "scout.ai.router_status.search",
        "scout.ai.sensorlogger_status.search",
    ],
}


EXECUTABLE_OUTPUT_KINDS: dict[str, str] = {
    WORKSPACE_QUERY_TOOL_ID: WORKSPACE_QUERY_OUTPUT_KIND,
    "pydantic_ai.tool.search_scout_workspace_catalog.v0": "scout_ai_workspace_catalog_tool_output",
    "pydantic_ai.tool.search_scout_route_structure.v0": "scout_ai_route_structure_tool_output",
    "pydantic_ai.tool.search_scout_major_points.v0": "scout_ai_major_points_tool_output",
    "pydantic_ai.tool.search_scout_evidence_fulltext.v0": "scout_ai_evidence_fulltext_tool_output",
    "pydantic_ai.tool.search_scout_risk_scores.v0": "scout_ai_risk_scores_tool_output",
    "pydantic_ai.tool.search_scout_terrain_scores.v0": "scout_ai_terrain_scores_tool_output",
    "pydantic_ai.tool.search_scout_map_perception.v0": "scout_ai_map_perception_tool_output",
    INS_DR_TRACE_TOOL_ID: INS_DR_TRACE_OUTPUT_KIND,
    LIVE_NAVIGATION_STATE_TOOL_ID: LIVE_NAVIGATION_STATE_OUTPUT_KIND,
    NMEA_ROUTE_RISK_PROBE_TOOL_ID: LIVE_NAVIGATION_STATE_OUTPUT_KIND,
    NAVIGATION_TERRAIN_TOOL_ID: NAVIGATION_TERRAIN_OUTPUT_KIND,
    SAFETY_BOUNDARY_TOOL_ID: SAFETY_BOUNDARY_OUTPUT_KIND,
    ENERGY_VITALS_TOOL_ID: ENERGY_VITALS_OUTPUT_KIND,
    WEATHER_WINDOW_TOOL_ID: WEATHER_WINDOW_OUTPUT_KIND,
    CWA_ENVIRONMENT_TOOL_ID: CWA_ENVIRONMENT_OUTPUT_KIND,
    GEE_ENVIRONMENT_TOOL_ID: GEE_ENVIRONMENT_OUTPUT_KIND,
    ROUTE_READINESS_TOOL_ID: ROUTE_READINESS_OUTPUT_KIND,
    CONTEXTUAL_PERMISSION_TOOL_ID: CONTEXTUAL_PERMISSION_OUTPUT_KIND,
    ROUTE_CONTEXT_TOOL_ID: ROUTE_CONTEXT_OUTPUT_KIND,
    PACE_GUARDIAN_TOOL_ID: PACE_GUARDIAN_OUTPUT_KIND,
    EQUIPMENT_RESOURCE_TOOL_ID: EQUIPMENT_RESOURCE_OUTPUT_KIND,
    TEAM_STATUS_TOOL_ID: TEAM_STATUS_OUTPUT_KIND,
    POST_TRIP_REVIEW_TOOL_ID: POST_TRIP_REVIEW_OUTPUT_KIND,
    REVIEW_GAP_TOOL_ID: REVIEW_GAP_OUTPUT_KIND,
    ROUTE_ARCHITECTURE_TOOL_ID: ROUTE_ARCHITECTURE_OUTPUT_KIND,
    MEDIA_LITERACY_TOOL_ID: MEDIA_LITERACY_OUTPUT_KIND,
    SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID: SURVIVAL_INCIDENT_PLAYBOOK_OUTPUT_KIND,
    RUNTIME_INGRESS_STATUS_TOOL_ID: RUNTIME_INGRESS_STATUS_OUTPUT_KIND,
}


def default_tool_contracts() -> dict[str, ScoutAiToolContract]:
    contracts = _load_matrix_contracts()
    _add_question_eval_tools(contracts)
    return dict(sorted(contracts.items()))


def resolve_scout_ai_tool_id(tool_id_or_alias: str) -> str:
    contracts = default_tool_contracts()
    if tool_id_or_alias in contracts:
        return tool_id_or_alias
    for tool_id, contract in contracts.items():
        if tool_id_or_alias in contract.aliases:
            return tool_id
    return tool_id_or_alias


def tool_registry_output(
    *,
    include_not_implemented: bool = True,
    tool_ids: list[str] | None = None,
) -> ScoutAiToolRegistryOutput:
    contracts = default_tool_contracts()
    resolved_ids = (
        [resolve_scout_ai_tool_id(tool_id) for tool_id in tool_ids]
        if tool_ids is not None
        else None
    )
    selected: list[ScoutAiToolContract] = []
    for tool_id, contract in contracts.items():
        if resolved_ids is not None and tool_id not in resolved_ids:
            continue
        if (
            not include_not_implemented
            and contract.implementation_status
            != ScoutAiToolImplementationStatus.READY_CURRENT_TOOL
        ):
            continue
        selected.append(contract)
    summary = _registry_summary(selected)
    return ScoutAiToolRegistryOutput(
        tool_count=len(selected),
        tools=selected,
        **summary,
    )


def _registry_summary(
    contracts: list[ScoutAiToolContract],
) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    tool_ids_by_status: dict[str, list[str]] = {}
    missing_evidence_fields_by_tool: dict[str, list[str]] = {}
    executable_tool_count = 0
    contract_only_tool_count = 0

    for contract in contracts:
        status = contract.implementation_status.value
        status_counts[status] = status_counts.get(status, 0) + 1
        tool_ids_by_status.setdefault(status, []).append(contract.tool_id)
        if contract.aliases:
            executable_tool_count += 1
            continue
        contract_only_tool_count += 1
        if contract.required_fields:
            missing_evidence_fields_by_tool[contract.tool_id] = list(
                contract.required_fields
            )

    return {
        "ready_current_tool_count": status_counts.get(
            ScoutAiToolImplementationStatus.READY_CURRENT_TOOL.value,
            0,
        ),
        "executable_tool_count": executable_tool_count,
        "contract_only_tool_count": contract_only_tool_count,
        "implementation_status_counts": dict(sorted(status_counts.items())),
        "tool_ids_by_status": {
            key: sorted(value) for key, value in sorted(tool_ids_by_status.items())
        },
        "missing_evidence_fields_by_tool": dict(
            sorted(missing_evidence_fields_by_tool.items())
        ),
    }


def _load_matrix_contracts() -> dict[str, ScoutAiToolContract]:
    if not MATRIX_PATH.exists():
        return {}
    payload = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
    raw_contracts = payload.get("tool_contracts")
    if not isinstance(raw_contracts, dict):
        return {}
    contracts: dict[str, ScoutAiToolContract] = {}
    for tool_id, raw in raw_contracts.items():
        if not isinstance(raw, dict):
            continue
        contracts[str(tool_id)] = _contract_from_raw(str(tool_id), raw)
    return contracts


def _add_question_eval_tools(contracts: dict[str, ScoutAiToolContract]) -> None:
    from scout_ai_question_eval import CURRENT_TOOLS, RECOMMENDED_TOOLS

    for tool_id, raw in CURRENT_TOOLS.items():
        if tool_id in contracts:
            existing = contracts[tool_id]
            contracts[tool_id] = existing.model_copy(
                update={
                    "implementation_status": ScoutAiToolImplementationStatus.READY_CURRENT_TOOL,
                    "aliases": _aliases_for(tool_id),
                    "argument_schema": _argument_schema_for(tool_id),
                    "output_artifact_kind": EXECUTABLE_OUTPUT_KINDS.get(
                        tool_id,
                        existing.output_artifact_kind,
                    ),
                }
            )
            continue
        contracts[tool_id] = ScoutAiToolContract(
            tool_id=tool_id,
            label=str(raw.get("label") or tool_id),
            implementation_status=ScoutAiToolImplementationStatus.READY_CURRENT_TOOL,
            description=str(raw.get("evidence_scope") or raw.get("label") or tool_id),
            data_bundles=[str(raw.get("evidence_scope") or "local Scout workspace evidence")],
            required_fields=(
                ["project_root", "request"]
                if tool_id == WORKSPACE_QUERY_TOOL_ID
                else ["project_root"]
            ),
            optional_fields=_optional_fields_for(tool_id),
            workflow_steps=[
                "resolve project root",
                "apply query and optional filters",
                "return compact read-only evidence with boundary flags",
            ],
            existing_support=[f"{tool_id} deterministic search surface"],
            argument_schema=_argument_schema_for(tool_id),
            output_artifact_kind=EXECUTABLE_OUTPUT_KINDS.get(
                tool_id,
                "scout_ai_tool_payload",
            ),
            aliases=_aliases_for(tool_id),
        )

    for tool_id, raw in RECOMMENDED_TOOLS.items():
        if tool_id in contracts:
            continue
        evidence = _as_str_list(raw.get("evidence_required"))
        contracts[tool_id] = ScoutAiToolContract(
            tool_id=tool_id,
            label=str(raw.get("label") or tool_id),
            implementation_status=ScoutAiToolImplementationStatus.NEW_AGENT_TOOL_NEEDED,
            description="Registered contract for a future Scout AI agent tool.",
            data_bundles=evidence,
            required_fields=evidence,
            workflow_steps=[
                "collect required evidence fields",
                "run deterministic domain assessment",
                "return advisory result without mutating runtime safety state",
            ],
            existing_support=[],
            implementation_gap="Contract registered, but no executor is implemented yet.",
            argument_schema=_future_argument_schema(evidence),
            output_artifact_kind="scout_ai_assessment_tool_output",
        )


def _contract_from_raw(tool_id: str, raw: dict[str, Any]) -> ScoutAiToolContract:
    status = _implementation_status(str(raw.get("status") or "new_agent_tool_needed"))
    if tool_id == INS_DR_TRACE_TOOL_ID:
        status = ScoutAiToolImplementationStatus.READY_CURRENT_TOOL
    if tool_id == WEATHER_WINDOW_TOOL_ID:
        status = ScoutAiToolImplementationStatus.READY_CURRENT_TOOL
        required_fields = list(WEATHER_WINDOW_REQUIRED_FIELDS)
        implementation_gap = None
        existing_support = [
            *_as_str_list(raw.get("existing_support")),
            "scout_weather_window_tool.py read-only route weather package assessor",
        ]
    elif tool_id == ENERGY_VITALS_TOOL_ID:
        status = ScoutAiToolImplementationStatus.READY_CURRENT_TOOL
        required_fields = list(ENERGY_VITALS_REQUIRED_FIELDS)
        implementation_gap = None
        existing_support = [
            *_as_str_list(raw.get("existing_support")),
            "scout_energy_vitals_tool.py read-only energy/vitals assessor",
        ]
    elif tool_id == REVIEW_GAP_TOOL_ID:
        status = ScoutAiToolImplementationStatus.READY_CURRENT_TOOL
        required_fields = list(REVIEW_GAP_REQUIRED_FIELDS)
        implementation_gap = None
        existing_support = [
            *_as_str_list(raw.get("existing_support")),
            "scout_review_gap_tool.py compact review/provenance gap assessor",
        ]
    elif tool_id == NMEA_ROUTE_RISK_PROBE_TOOL_ID:
        status = ScoutAiToolImplementationStatus.READY_CURRENT_TOOL
        required_fields = list(LIVE_NAVIGATION_REQUIRED_FIELDS)
        implementation_gap = None
        existing_support = [
            *_as_str_list(raw.get("existing_support")),
            "scout_live_navigation_state_tool.py general read-only live navigation assessor supersedes the scenario probe gap",
        ]
    elif tool_id == RUNTIME_INGRESS_STATUS_TOOL_ID:
        status = ScoutAiToolImplementationStatus.READY_CURRENT_TOOL
        required_fields = list(RUNTIME_INGRESS_STATUS_REQUIRED_FIELDS)
        implementation_gap = None
        existing_support = [
            *_as_str_list(raw.get("existing_support")),
            "scout_runtime_ingress_status_tool.py read-only ingress/router trace assessor",
        ]
    elif tool_id == SAFETY_BOUNDARY_TOOL_ID:
        status = ScoutAiToolImplementationStatus.READY_CURRENT_TOOL
        required_fields = list(SAFETY_ADMISSION_REQUIRED_FIELDS)
        implementation_gap = None
        existing_support = [
            *_as_str_list(raw.get("existing_support")),
            "scout_safety_boundary_tool.py read-only current safety admission boundary assessor",
        ]
    else:
        required_fields = _as_str_list(raw.get("required_fields"))
        implementation_gap = (
            str(raw["implementation_gap"]) if raw.get("implementation_gap") else None
        )
        existing_support = _as_str_list(raw.get("existing_support"))
    return ScoutAiToolContract(
        tool_id=tool_id,
        label=str(raw.get("label") or tool_id),
        implementation_status=status,
        description=_description_for_raw(tool_id, raw),
        data_bundles=_as_str_list(raw.get("data_bundles")),
        required_fields=required_fields,
        optional_fields=_optional_fields_for(tool_id),
        workflow_steps=_as_str_list(raw.get("workflow_steps")),
        existing_support=existing_support,
        implementation_gap=implementation_gap,
        argument_schema=_argument_schema_for(tool_id)
        if tool_id in EXECUTABLE_TOOL_ALIASES
        else _future_argument_schema(_as_str_list(raw.get("required_fields"))),
        output_artifact_kind=EXECUTABLE_OUTPUT_KINDS.get(
            tool_id,
            "scout_ai_assessment_tool_output",
        ),
        aliases=_aliases_for(tool_id),
    )


def _implementation_status(value: str) -> ScoutAiToolImplementationStatus:
    try:
        return ScoutAiToolImplementationStatus(value)
    except ValueError:
        return ScoutAiToolImplementationStatus.NEW_AGENT_TOOL_NEEDED


def _description_for_raw(tool_id: str, raw: dict[str, Any]) -> str:
    if raw.get("description"):
        return str(raw["description"])
    support = _as_str_list(raw.get("existing_support"))
    gap = str(raw.get("implementation_gap") or "")
    if support:
        return "; ".join(support[:2])
    if gap:
        return gap
    return tool_id


def _aliases_for(tool_id: str) -> list[str]:
    return list(EXECUTABLE_TOOL_ALIASES.get(tool_id, []))


def _argument_schema_for(tool_id: str) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "project_root": {"type": "string"},
        "query": {"type": "string"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
    }
    for field in _optional_fields_for(tool_id):
        properties[field] = {"type": ["string", "number", "boolean", "array", "null"]}
    required = ["project_root"]
    if tool_id == WORKSPACE_QUERY_TOOL_ID:
        try:
            request_schema = workspace_query_request_json_schema()
        except ImportError:
            request_schema = {
                "type": "object",
                "description": (
                    "Typed deterministic workspace query request with an "
                    "operation discriminator."
                ),
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": [
                            "inspect",
                            "exists",
                            "count",
                            "distinct",
                            "filter",
                            "group_by",
                            "top_k",
                            "argmax",
                            "diff",
                            "freshness",
                            "nearest",
                            "interval",
                            "route_forward",
                        ],
                    }
                },
                "required": ["operation"],
            }
        definitions = request_schema.pop("$defs", {})
        properties = {
            "project_root": {"type": "string"},
            "request": request_schema,
        }
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["project_root", "request"],
            "properties": properties,
        }
        if definitions:
            schema["$defs"] = definitions
        return schema
    if tool_id == "pydantic_ai.tool.search_scout_evidence_fulltext.v0":
        required.append("query")
    return {
        "type": "object",
        "additionalProperties": True,
        "required": required,
        "properties": properties,
    }


def _future_argument_schema(required_fields: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": True,
        "properties": {
            "evidence": {
                "type": "object",
                "description": "Caller-provided evidence bundle keyed by required field name.",
            },
            "project_root": {"type": "string"},
            "query": {"type": "string"},
        },
        "required_evidence_fields": required_fields,
    }


def _optional_fields_for(tool_id: str) -> list[str]:
    if tool_id == WORKSPACE_QUERY_TOOL_ID:
        return []
    if tool_id == "pydantic_ai.tool.search_scout_workspace_catalog.v0":
        return ["domains", "include_missing"]
    if tool_id == "pydantic_ai.tool.search_scout_route_structure.v0":
        return ["cp", "segment"]
    if tool_id == "pydantic_ai.tool.search_scout_major_points.v0":
        return ["cp", "point_kinds"]
    if tool_id == "pydantic_ai.tool.search_scout_evidence_fulltext.v0":
        return ["evidence_types"]
    if tool_id == "pydantic_ai.tool.search_scout_risk_scores.v0":
        return [
            "surface",
            "min_score",
            "risk_bucket",
            "distance_km_min",
            "distance_km_max",
            "cp",
            "lat",
            "lon",
            "radius_m",
            "sort",
        ]
    if tool_id == "pydantic_ai.tool.search_scout_terrain_scores.v0":
        return [
            "metric",
            "min_score",
            "min_slope_degrees",
            "distance_km_min",
            "distance_km_max",
            "cp",
            "lat",
            "lon",
            "radius_m",
            "sort",
        ]
    if tool_id == "pydantic_ai.tool.search_scout_map_perception.v0":
        return ["evidence_types", "cp", "lat", "lon", "radius_m", "sort"]
    if tool_id == INS_DR_TRACE_TOOL_ID:
        return [
            "estimates_path",
            "gps_path",
            "evidence_dir",
            "max_records",
            "max_horizontal_accuracy_m",
            "max_interpolation_gap_s",
        ]
    if tool_id == LIVE_NAVIGATION_STATE_TOOL_ID:
        return list(LIVE_NAVIGATION_OPTIONAL_FIELDS)
    if tool_id == NMEA_ROUTE_RISK_PROBE_TOOL_ID:
        return list(LIVE_NAVIGATION_OPTIONAL_FIELDS)
    if tool_id == NAVIGATION_TERRAIN_TOOL_ID:
        return list(NAVIGATION_TERRAIN_OPTIONAL_FIELDS)
    if tool_id == SAFETY_BOUNDARY_TOOL_ID:
        return list(SAFETY_ADMISSION_OPTIONAL_FIELDS)
    if tool_id == ENERGY_VITALS_TOOL_ID:
        return [
            *ENERGY_VITALS_REQUIRED_FIELDS,
            *ENERGY_VITALS_OPTIONAL_FIELDS,
        ]
    if tool_id == WEATHER_WINDOW_TOOL_ID:
        return list(WEATHER_WINDOW_OPTIONAL_FIELDS)
    if tool_id == CWA_ENVIRONMENT_TOOL_ID:
        return list(CWA_ENVIRONMENT_OPTIONAL_FIELDS)
    if tool_id == GEE_ENVIRONMENT_TOOL_ID:
        return list(GEE_ENVIRONMENT_OPTIONAL_FIELDS)
    if tool_id == ROUTE_READINESS_TOOL_ID:
        return list(ROUTE_READINESS_OPTIONAL_FIELDS)
    if tool_id == CONTEXTUAL_PERMISSION_TOOL_ID:
        return list(CONTEXTUAL_PERMISSION_OPTIONAL_FIELDS)
    if tool_id == ROUTE_CONTEXT_TOOL_ID:
        return list(ROUTE_CONTEXT_OPTIONAL_FIELDS)
    if tool_id == PACE_GUARDIAN_TOOL_ID:
        return list(PACE_GUARDIAN_OPTIONAL_FIELDS)
    if tool_id == EQUIPMENT_RESOURCE_TOOL_ID:
        return list(EQUIPMENT_RESOURCE_OPTIONAL_FIELDS)
    if tool_id == TEAM_STATUS_TOOL_ID:
        return list(TEAM_STATUS_OPTIONAL_FIELDS)
    if tool_id == POST_TRIP_REVIEW_TOOL_ID:
        return list(POST_TRIP_REVIEW_OPTIONAL_FIELDS)
    if tool_id == REVIEW_GAP_TOOL_ID:
        return list(REVIEW_GAP_OPTIONAL_FIELDS)
    if tool_id == ROUTE_ARCHITECTURE_TOOL_ID:
        return list(ROUTE_ARCHITECTURE_OPTIONAL_FIELDS)
    if tool_id == MEDIA_LITERACY_TOOL_ID:
        return list(MEDIA_LITERACY_OPTIONAL_FIELDS)
    if tool_id == SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID:
        return list(SURVIVAL_INCIDENT_PLAYBOOK_OPTIONAL_FIELDS)
    if tool_id == RUNTIME_INGRESS_STATUS_TOOL_ID:
        return list(RUNTIME_INGRESS_STATUS_OPTIONAL_FIELDS)
    return []


def _as_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item is not None and str(item).strip()]
    if isinstance(value, tuple):
        return [str(item) for item in value if item is not None and str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value]
    return []


def _reject_secret_like_keys(value: Any, *, path: str) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).lower()
            if any(fragment in normalized for fragment in SENSITIVE_KEY_FRAGMENTS):
                raise ValueError(f"{path}.{key} is a secret-like key and cannot be passed to Scout AI tools")
            _reject_secret_like_keys(nested, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_secret_like_keys(nested, path=f"{path}[{index}]")
