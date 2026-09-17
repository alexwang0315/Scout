"""Empty terrain evidence must retain its own bounded decision in fallback."""
from copy import deepcopy
from pathlib import Path

import pytest

from assistant_models import AssistantSourceRef, ScoutAssistantQuery
from assistant_pydantic_provider import (
    MAJOR_POINT_TOOL_ID,
    TERRAIN_SCORE_TOOL_ID,
    _build_terrain_score_tool_fallback_response,
    build_workspace_tool_fallback_response,
)
from scout_agent_builtin_tools import _resolve_assistant_workflow_eval_case
from scout_ai_tool_executor import execute_scout_ai_tool


PROJECT_ROOT = (
    Path(__file__).resolve().parents[1]
    / "tests/fixtures/pretrip/projects/chilai_nanhua_day1"
)
QUESTION = "哪些 CP 附近坡度最高？"


def _tool_source(tool_id, latest):
    return AssistantSourceRef(
        source_id=tool_id,
        selected=True,
        context_summary={"tool_id": tool_id, "latest": latest},
    )


def _terrain_payload():
    result = execute_scout_ai_tool(
        {
            "tool_id": TERRAIN_SCORE_TOOL_ID,
            "project_root": str(PROJECT_ROOT),
            "query": QUESTION,
            "limit": 3,
        }
    )
    assert result.status == "completed"
    assert result.payload["results"] == []
    assert result.payload["decision"] == "DELAY"
    assert result.payload["missing_fields"] == ["terrain_score_results"]
    return result.payload


@pytest.mark.parametrize("terrain_first", [True, False])
def test_empty_terrain_decision_precedes_unrelated_major_point_summary(terrain_first):
    latest = _terrain_payload()
    major = execute_scout_ai_tool(
        {
            "tool_id": MAJOR_POINT_TOOL_ID,
            "project_root": str(PROJECT_ROOT),
            "query": QUESTION,
            "limit": 3,
        }
    )
    assert major.payload["results"] == []
    assert major.payload["summaries"]
    sources = [
        _tool_source(TERRAIN_SCORE_TOOL_ID, latest),
        _tool_source(MAJOR_POINT_TOOL_ID, major.payload),
    ]
    if not terrain_first:
        sources.reverse()
    original = deepcopy([source.model_dump() for source in sources])

    response = build_workspace_tool_fallback_response(
        ScoutAssistantQuery(surface="pretrip", question=QUESTION),
        sources=sources,
        provider_error_type="RuntimeError",
    )

    assert response is not None
    assert f"resolved_by={TERRAIN_SCORE_TOOL_ID}" in response.limitations
    assert latest["decision_output"]["firstLayer"]["decision"] in response.answer
    assert latest["decision_output"]["firstLayer"]["reason"] in response.answer
    assert latest["decision_output"]["firstLayer"]["nextStep"] in response.answer
    assert "terrain_score_results" in response.answer
    assert "major_point_count" not in response.answer
    assert "runtime safety truth" in response.answer
    assert [source.model_dump() for source in sources] == original
    assert response.boundary.phase1_mutation_allowed is False
    assert response.boundary.outbound_send_allowed is False


def test_builtin_provider_failure_preserves_empty_terrain_as_evidence_only():
    response = _resolve_assistant_workflow_eval_case(
        QUESTION,
        project_id="chilai_nanhua_day1",
        project_root=PROJECT_ROOT,
        limit=3,
    )
    assert "model answer unavailable" in response.answer
    assert "暫緩地形分數判斷" not in response.answer
    assert "deterministic_tool_fallback_only=true" in response.limitations
    assert f"resolved_by={TERRAIN_SCORE_TOOL_ID}" in response.limitations
    assert "暫緩地形分數判斷" in response.evidence_backed_answer
    assert "terrain_score_results" in response.evidence_backed_answer
    assert "major_point_count" not in response.evidence_backed_answer
    assert response.observability.safe_failure is True
    assert response.boundary.phase1_mutation_allowed is False
    assert response.boundary.outbound_send_allowed is False
    terrain = next(source for source in response.sources if source.source_id == TERRAIN_SCORE_TOOL_ID)
    latest = terrain.context_summary["latest"]
    assert latest["results"] == []
    assert latest["decision_output"]["decision"] == "DELAY"
    assert latest["decision_output"]["allowed"] is False
    assert latest["boundary"]["runtime_safety_truth"] is False


@pytest.mark.parametrize("kind", ["typed_decision", "field_answer"])
def test_empty_terrain_fallback_preserves_available_evidence_form(kind):
    latest = _terrain_payload()
    if kind == "typed_decision":
        latest.pop("field_answer")
    else:
        latest.pop("decision_output")
    original = deepcopy(latest)
    response = _build_terrain_score_tool_fallback_response(
        ScoutAssistantQuery(surface="pretrip", question=QUESTION),
        sources=[_tool_source(TERRAIN_SCORE_TOOL_ID, latest)],
        provider_error_type="RuntimeError",
    )
    assert response is not None
    assert "terrain_score_results" in response.answer
    if kind == "typed_decision":
        assert latest["decision_output"]["firstLayer"]["nextStep"] in response.answer
    else:
        assert latest["field_answer"] in response.answer
    assert latest == original


@pytest.mark.parametrize(
    "latest",
    [
        {"status": "failed", "results": [], "field_answer": "unusable failure text"},
        {"status": "completed", "results": []},
        {"status": "completed", "results": [], "field_answer": "   "},
        {"status": "completed", "results": [], "field_answer": {"not": "text"}},
        {"status": "completed", "results": [], "decision_output": {}},
    ],
)
def test_empty_terrain_without_usable_evidence_does_not_invent_a_decision(latest):
    response = _build_terrain_score_tool_fallback_response(
        ScoutAssistantQuery(surface="pretrip", question=QUESTION),
        sources=[_tool_source(TERRAIN_SCORE_TOOL_ID, latest)],
        provider_error_type="RuntimeError",
    )
    assert response is None
