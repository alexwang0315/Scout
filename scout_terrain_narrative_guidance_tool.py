"""Read-only Scout AI tool for typed historical narrative TRH guidance."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scout.agents import PydanticScoutAgentProvider, ScoutDeps, TerrainNarrativeGuidanceAgent


TERRAIN_NARRATIVE_GUIDANCE_TOOL_ID = (
    "scout.ai.terrain_narrative_guidance.interpret.v0"
)
TERRAIN_NARRATIVE_GUIDANCE_OUTPUT_KIND = (
    "scout_ai_terrain_narrative_guidance_plan"
)
TERRAIN_NARRATIVE_GUIDANCE_REQUIRED_FIELDS = (
    "project_root",
    "narrative",
    "source_id",
)
TERRAIN_NARRATIVE_GUIDANCE_OPTIONAL_FIELDS = ("source_date",)


def interpret_scout_terrain_narrative_guidance(
    project_root: Path | str,
    *,
    narrative: str,
    source_id: str,
    source_date: str | None = None,
) -> dict[str, Any]:
    """Return a typed preview; never resolve anchors, run GIS, or write files."""

    root = Path(project_root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"project_root is not a directory: {root}")
    deps = ScoutDeps(
        capability_registry=None,
        memory_store=None,
        workflow_store=None,
        sandbox=None,
        permission_gate=None,
        notification_gateway=None,
        docs_search=None,
        user_id="terrain-narrative-guidance-tool",
        active_context={"project_root": str(root)},
    )
    provider = PydanticScoutAgentProvider()
    plan = TerrainNarrativeGuidanceAgent(provider).interpret(
        narrative,
        source_id=source_id,
        source_date=source_date,
        deps=deps,
    )
    return {
        "artifact_kind": TERRAIN_NARRATIVE_GUIDANCE_OUTPUT_KIND,
        "tool_id": TERRAIN_NARRATIVE_GUIDANCE_TOOL_ID,
        "status": "completed",
        "assessment_kind": "read_only_candidate_constraint_interpretation",
        "project_root": str(root),
        "guidance_plan": plan.model_dump(mode="json"),
        "constraint_count": len(plan.constraints),
        "unknown_count": len(plan.unknowns),
        "conflict_count": len(plan.conflicts),
        "review_required": True,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "writes_performed": [],
        "next_actions": [
            "Resolve constraints against DEM-derived candidate features.",
            "Review unresolved candidate zones and confirm map anchors.",
            "Only then submit the reviewed plan for an R4 guided hypothesis.",
        ],
        "warnings": list(plan.warnings),
        "boundary": {
            "read_only": True,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "model_output_is_runtime_truth": False,
            "grass_execution_allowed": False,
            "workspace_write_allowed": False,
            "route_truth_mutation_allowed": False,
        },
    }


__all__ = [
    "TERRAIN_NARRATIVE_GUIDANCE_OPTIONAL_FIELDS",
    "TERRAIN_NARRATIVE_GUIDANCE_OUTPUT_KIND",
    "TERRAIN_NARRATIVE_GUIDANCE_REQUIRED_FIELDS",
    "TERRAIN_NARRATIVE_GUIDANCE_TOOL_ID",
    "interpret_scout_terrain_narrative_guidance",
]
