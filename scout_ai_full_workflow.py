from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from assistant_models import AssistantSurface
from scout_ai_answer_synthesis import (
    ScoutAiAnswerSynthesisOutput,
    collect_and_synthesize_scout_ai_answer,
)
from scout_ai_tool_contracts import ScoutAiToolBaseModel, ScoutAiToolBoundary


ARTIFACT_KIND = "scout_ai_full_workflow"
ARTIFACT_VERSION = "scout_ai_full_workflow.v0"


class ScoutAiFullWorkflowPolicy(ScoutAiToolBaseModel):
    context_registry_discovered: Literal[True] = True
    tool_plan_created: Literal[True] = True
    evidence_collection_performed: Literal[True] = True
    answer_synthesis_performed: Literal[True] = True
    deterministic_tools_executed: bool = False
    model_provider_used: Literal[False] = False
    model_synthesis_performed: Literal[False] = False
    workspace_file_write_allowed: Literal[False] = False
    safety_api_called: Literal[False] = False
    phase1_l0_l4_state_mutated: Literal[False] = False
    outbound_send_performed: Literal[False] = False
    hardware_control_performed: Literal[False] = False


class ScoutAiFullWorkflowStep(ScoutAiToolBaseModel):
    step_id: str = Field(min_length=1)
    artifact_kind: str = Field(min_length=1)
    artifact_version: str = Field(min_length=1)
    status: str = Field(min_length=1)
    summary: dict[str, Any] = Field(default_factory=dict)


class ScoutAiFullWorkflowOutput(ScoutAiToolBaseModel):
    artifact_kind: Literal["scout_ai_full_workflow"] = ARTIFACT_KIND
    artifact_version: Literal["scout_ai_full_workflow.v0"] = ARTIFACT_VERSION
    project_id: str
    project_root: str
    surface: str
    question: str
    answerability: str
    answer: str
    decision_output: dict[str, Any] = Field(default_factory=dict)
    workflow_steps: list[ScoutAiFullWorkflowStep] = Field(default_factory=list)
    discovery_plan: dict[str, Any]
    evidence_collection: dict[str, Any]
    answer_synthesis: dict[str, Any]
    selected_tool_count: int = Field(ge=0)
    executed_tool_count: int = Field(ge=0)
    completed_tool_count: int = Field(ge=0)
    contract_gap_count: int = Field(ge=0)
    missing_input_count: int = Field(ge=0)
    failed_tool_count: int = Field(ge=0)
    missing_evidence_count: int = Field(ge=0)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    missing_evidence: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    workflow_policy: ScoutAiFullWorkflowPolicy = Field(
        default_factory=ScoutAiFullWorkflowPolicy
    )
    boundary: ScoutAiToolBoundary = Field(default_factory=ScoutAiToolBoundary)


def run_scout_ai_full_workflow(
    question: str,
    *,
    project_root: str | Path,
    project_id: str | None = None,
    surface: str | AssistantSurface = AssistantSurface.PRETRIP,
    limit: int = 6,
    include_missing_context_sources: bool = True,
    include_not_implemented_tools: bool = True,
    max_result_items_per_tool: int = 6,
) -> ScoutAiFullWorkflowOutput:
    answer_synthesis = collect_and_synthesize_scout_ai_answer(
        question,
        project_root=project_root,
        project_id=project_id,
        surface=surface,
        limit=limit,
        include_missing_context_sources=include_missing_context_sources,
        include_not_implemented_tools=include_not_implemented_tools,
        max_result_items_per_tool=max_result_items_per_tool,
    )
    return full_workflow_from_answer_synthesis(answer_synthesis)


def full_workflow_from_answer_synthesis(
    answer_synthesis: ScoutAiAnswerSynthesisOutput | dict[str, Any],
) -> ScoutAiFullWorkflowOutput:
    answer = _parse_answer_synthesis(answer_synthesis)
    answer_payload = answer.model_dump(mode="json")
    evidence = answer.evidence_collection
    discovery = (
        evidence.get("discovery_plan", {})
        if isinstance(evidence.get("discovery_plan"), dict)
        else {}
    )
    executed_count = _int_value(evidence.get("executed_tool_count"))

    return ScoutAiFullWorkflowOutput(
        project_id=answer.project_id,
        project_root=answer.project_root,
        surface=answer.surface,
        question=answer.question,
        answerability=answer.answerability,
        answer=answer.answer,
        decision_output=dict(answer.decision_output),
        workflow_steps=_workflow_steps(
            discovery=discovery,
            evidence=evidence,
            answer=answer_payload,
        ),
        discovery_plan=discovery,
        evidence_collection=evidence,
        answer_synthesis=answer_payload,
        selected_tool_count=_int_value(evidence.get("selected_tool_count")),
        executed_tool_count=executed_count,
        completed_tool_count=_int_value(evidence.get("completed_tool_count")),
        contract_gap_count=_int_value(evidence.get("contract_gap_count")),
        missing_input_count=_int_value(evidence.get("missing_input_count")),
        failed_tool_count=_int_value(evidence.get("failed_tool_count")),
        missing_evidence_count=answer.missing_evidence_count,
        sources=[source.model_dump(mode="json") for source in answer.sources],
        missing_evidence=list(answer.missing_evidence),
        limitations=list(answer.limitations),
        workflow_policy=ScoutAiFullWorkflowPolicy(
            deterministic_tools_executed=executed_count > 0,
        ),
    )


def _parse_answer_synthesis(
    answer_synthesis: ScoutAiAnswerSynthesisOutput | dict[str, Any],
) -> ScoutAiAnswerSynthesisOutput:
    if isinstance(answer_synthesis, ScoutAiAnswerSynthesisOutput):
        return answer_synthesis
    payload = dict(answer_synthesis)
    payload.pop("status", None)
    return ScoutAiAnswerSynthesisOutput.model_validate(payload)


def _workflow_steps(
    *,
    discovery: dict[str, Any],
    evidence: dict[str, Any],
    answer: dict[str, Any],
) -> list[ScoutAiFullWorkflowStep]:
    return [
        ScoutAiFullWorkflowStep(
            step_id="context_registry_and_tool_plan",
            artifact_kind=str(discovery.get("artifact_kind") or "unknown"),
            artifact_version=str(discovery.get("artifact_version") or "unknown"),
            status="completed",
            summary=_discovery_summary(discovery),
        ),
        ScoutAiFullWorkflowStep(
            step_id="evidence_collection",
            artifact_kind=str(evidence.get("artifact_kind") or "unknown"),
            artifact_version=str(evidence.get("artifact_version") or "unknown"),
            status=_evidence_status(evidence),
            summary=_evidence_summary(evidence),
        ),
        ScoutAiFullWorkflowStep(
            step_id="answer_synthesis",
            artifact_kind=str(answer.get("artifact_kind") or "unknown"),
            artifact_version=str(answer.get("artifact_version") or "unknown"),
            status="completed",
            summary=_answer_summary(answer),
        ),
    ]


def _discovery_summary(discovery: dict[str, Any]) -> dict[str, Any]:
    context_registry = (
        discovery.get("context_registry")
        if isinstance(discovery.get("context_registry"), dict)
        else {}
    )
    return {
        "source_count": _int_value(context_registry.get("source_count")),
        "available_source_count": _int_value(
            context_registry.get("available_source_count")
        ),
        "selected_tool_count": _int_value(discovery.get("selected_tool_count")),
        "selected_tool_ids": list(discovery.get("selected_tool_ids", [])),
        "ready_to_execute_tool_ids": list(
            discovery.get("ready_to_execute_tool_ids", [])
        ),
        "contract_gap_tool_ids": list(discovery.get("contract_gap_tool_ids", [])),
        "missing_input_tool_ids": list(discovery.get("missing_input_tool_ids", [])),
    }


def _evidence_summary(evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "selected_tool_count": _int_value(evidence.get("selected_tool_count")),
        "executed_tool_count": _int_value(evidence.get("executed_tool_count")),
        "completed_tool_count": _int_value(evidence.get("completed_tool_count")),
        "contract_gap_count": _int_value(evidence.get("contract_gap_count")),
        "missing_input_count": _int_value(evidence.get("missing_input_count")),
        "failed_tool_count": _int_value(evidence.get("failed_tool_count")),
    }


def _answer_summary(answer: dict[str, Any]) -> dict[str, Any]:
    decision_output = (
        answer.get("decision_output")
        if isinstance(answer.get("decision_output"), dict)
        else {}
    )
    return {
        "answerability": str(answer.get("answerability") or ""),
        "completed_source_count": _int_value(answer.get("completed_source_count")),
        "missing_evidence_count": _int_value(answer.get("missing_evidence_count")),
        "failed_source_count": _int_value(answer.get("failed_source_count")),
        "decision_output_schema": str(
            decision_output.get("decisionObjectSchema") or ""
        ),
        "decision_output_source_tool": str(
            decision_output.get("answerSourceToolId") or ""
        ),
        "model_provider_used": False,
        "runtime_safety_truth": False,
    }


def _evidence_status(evidence: dict[str, Any]) -> str:
    return (
        "completed_with_failures"
        if _int_value(evidence.get("failed_tool_count")) > 0
        else "completed"
    )


def _int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
