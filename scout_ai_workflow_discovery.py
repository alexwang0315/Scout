from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from assistant_models import AssistantSurface, ScoutAssistantQuery
from scout_ai_context_registry import discover_scout_ai_context_sources
from scout_ai_tool_contracts import (
    ScoutAiToolBaseModel,
    ScoutAiToolBoundary,
    tool_registry_output,
)
from scout_ai_tool_planner import (
    ScoutAiToolPlanItemStatus,
    plan_scout_ai_tools,
)


ARTIFACT_KIND = "scout_ai_workflow_discovery_plan"
ARTIFACT_VERSION = "scout_ai_workflow_discovery_plan.v0"


class ScoutAiWorkflowExecutionPolicy(ScoutAiToolBaseModel):
    deterministic_discovery_only: Literal[True] = True
    ready_tools_executed: Literal[False] = False
    model_synthesis_performed: Literal[False] = False
    workspace_file_write_allowed: Literal[False] = False
    safety_api_called: Literal[False] = False
    phase1_l0_l4_state_mutated: Literal[False] = False
    outbound_send_performed: Literal[False] = False
    hardware_control_performed: Literal[False] = False


class ScoutAiWorkflowDiscoveryOutput(ScoutAiToolBaseModel):
    artifact_kind: Literal["scout_ai_workflow_discovery_plan"] = ARTIFACT_KIND
    artifact_version: Literal["scout_ai_workflow_discovery_plan.v0"] = (
        ARTIFACT_VERSION
    )
    project_id: str
    project_root: str
    surface: str
    question: str
    context_registry: dict[str, Any]
    tool_registry_summary: dict[str, Any]
    tool_plan: dict[str, Any]
    selected_tool_count: int = Field(ge=0)
    selected_tool_ids: list[str] = Field(default_factory=list)
    ready_to_execute_tool_ids: list[str] = Field(default_factory=list)
    contract_gap_tool_ids: list[str] = Field(default_factory=list)
    missing_input_tool_ids: list[str] = Field(default_factory=list)
    execution_policy: ScoutAiWorkflowExecutionPolicy = Field(
        default_factory=ScoutAiWorkflowExecutionPolicy
    )
    boundary: ScoutAiToolBoundary = Field(default_factory=ScoutAiToolBoundary)


def build_scout_ai_workflow_discovery_plan(
    question: str,
    *,
    project_root: str | Path,
    project_id: str | None = None,
    surface: str | AssistantSurface = AssistantSurface.PRETRIP,
    limit: int = 6,
    include_missing_context_sources: bool = True,
    include_not_implemented_tools: bool = True,
) -> ScoutAiWorkflowDiscoveryOutput:
    root = Path(project_root)
    resolved_project_id = project_id or _project_id_from_root(root)
    resolved_surface = _assistant_surface(surface)
    query = ScoutAssistantQuery(
        surface=resolved_surface,
        question=question,
        project_id=resolved_project_id,
        context_ref=resolved_project_id,
    )

    context_registry = discover_scout_ai_context_sources(
        root,
        include_missing=include_missing_context_sources,
    )
    tool_registry = tool_registry_output(
        include_not_implemented=include_not_implemented_tools,
    )
    tool_plan = plan_scout_ai_tools(query, project_root=root, limit=limit)
    selected_tool_ids = [item.tool_id for item in tool_plan.selected_tools]

    return ScoutAiWorkflowDiscoveryOutput(
        project_id=resolved_project_id,
        project_root=str(root),
        surface=resolved_surface.value,
        question=question,
        context_registry=context_registry.model_dump(mode="json"),
        tool_registry_summary=_compact_tool_registry(tool_registry.model_dump(mode="json")),
        tool_plan=tool_plan.model_dump(mode="json"),
        selected_tool_count=len(selected_tool_ids),
        selected_tool_ids=selected_tool_ids,
        ready_to_execute_tool_ids=[
            item.tool_id
            for item in tool_plan.selected_tools
            if item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
        ],
        contract_gap_tool_ids=[
            item.tool_id
            for item in tool_plan.selected_tools
            if item.status
            == ScoutAiToolPlanItemStatus.CONTRACT_ONLY_MISSING_EVIDENCE
        ],
        missing_input_tool_ids=[
            item.tool_id
            for item in tool_plan.selected_tools
            if item.status == ScoutAiToolPlanItemStatus.MISSING_INPUT
        ],
    )


def _compact_tool_registry(registry: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_kind": registry.get("artifact_kind"),
        "artifact_version": registry.get("artifact_version"),
        "tool_count": registry.get("tool_count", 0),
        "ready_current_tool_count": registry.get("ready_current_tool_count", 0),
        "executable_tool_count": registry.get("executable_tool_count", 0),
        "contract_only_tool_count": registry.get("contract_only_tool_count", 0),
        "implementation_status_counts": registry.get(
            "implementation_status_counts",
            {},
        ),
        "tool_ids_by_status": registry.get("tool_ids_by_status", {}),
        "missing_evidence_fields_by_tool": registry.get(
            "missing_evidence_fields_by_tool",
            {},
        ),
        "boundary": registry.get("boundary", {}),
    }


def _assistant_surface(surface: str | AssistantSurface) -> AssistantSurface:
    if isinstance(surface, AssistantSurface):
        return surface
    return AssistantSurface(str(surface or AssistantSurface.PRETRIP.value))


def _project_id_from_root(root: Path) -> str:
    project_path = root / "project.json"
    if project_path.exists():
        try:
            import json

            project = json.loads(project_path.read_text(encoding="utf-8"))
            if isinstance(project, dict):
                value = project.get("project_id") or project.get("id")
                if value:
                    return str(value)
        except Exception:
            pass
    return root.name
