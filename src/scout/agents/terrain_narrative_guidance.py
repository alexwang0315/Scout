"""Typed Scout AI facade for historical narrative TRH guidance."""

from __future__ import annotations

import json

from scout.agents.deps import (
    ScoutAgentProvider,
    ScoutAgentRequest,
    ScoutDeps,
    build_toolbox,
    validate_provider_output,
)
from terrain_route_guidance import (
    TerrainNarrativeGuidancePlan,
    validate_narrative_guidance_plan,
)


TERRAIN_NARRATIVE_GUIDANCE_INSTRUCTIONS = """\
You are TerrainNarrativeGuidanceAgent for Scout Terrain Route Hypothesis.
Return only a TerrainNarrativeGuidancePlan-compatible object.
Rules:
- Extract explicit route-language evidence and preserve exact source spans.
- Keep ambiguous distance, elevation, sequence, and place references unresolved.
- Historical markers, hunting paths, vegetation, wetness, bridges, ropes, and
  engineered structures are context observations, not DEM route truth.
- Never label an output existing_trail, confirmed_trail, safe_route, passable,
  legally_accessible, or recommended_route.
- Always keep authority=candidate_only and runtime_safety_truth=false.
- Do not choose map anchors, execute GRASS, write workspace files, mutate route
  truth, or make navigation/safety decisions.
"""


class TerrainNarrativeGuidanceAgent:
    """Interpret prose into a typed candidate plan without spatial execution."""

    def __init__(self, provider: ScoutAgentProvider) -> None:
        self._provider = provider

    def interpret(
        self,
        narrative: str,
        *,
        source_id: str,
        deps: ScoutDeps,
        source_date: str | None = None,
    ) -> TerrainNarrativeGuidancePlan:
        normalized = narrative.strip()
        if not normalized:
            raise ValueError("terrain route narrative is required")
        if len(normalized) > 32_000:
            raise ValueError("terrain route narrative exceeds 32000 characters")
        if not source_id.strip():
            raise ValueError("terrain route narrative source_id is required")
        prompt = json.dumps(
            {
                "task": "interpret_terrain_route_narrative",
                "source_id": source_id.strip(),
                "source_date": source_date,
                "narrative": normalized,
                "output": "TerrainNarrativeGuidancePlan",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        request = ScoutAgentRequest(
            agent_name="TerrainNarrativeGuidanceAgent",
            instructions=TERRAIN_NARRATIVE_GUIDANCE_INSTRUCTIONS,
            prompt=prompt,
            output_type=TerrainNarrativeGuidancePlan,
            tools=build_toolbox(deps, allowed_tools=set()),
            context={
                "narrative": normalized,
                "source_id": source_id.strip(),
                "source_date": source_date,
            },
        )
        plan = validate_provider_output(
            self._provider.run(request),
            TerrainNarrativeGuidancePlan,
        )
        if plan.source_id != source_id.strip():
            raise ValueError("model changed the narrative source_id")
        validate_narrative_guidance_plan(plan, normalized)
        return plan


__all__ = [
    "TERRAIN_NARRATIVE_GUIDANCE_INSTRUCTIONS",
    "TerrainNarrativeGuidanceAgent",
]
