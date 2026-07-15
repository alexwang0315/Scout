"""Scout AI adapter for deterministic bounded workspace queries."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping


WORKSPACE_QUERY_TOOL_ID = "scout.ai.workspace.query.v1"
WORKSPACE_QUERY_OUTPUT_KIND = "scout_ai_workspace_query_tool_output"


def workspace_query_request_json_schema() -> dict[str, Any]:
    """Return the full operation-discriminated request schema lazily.

    Keeping Scout package imports inside the function preserves the standalone
    tool-registry subprocess path while still exposing every bounded operation
    to Pydantic AI when the package runtime is available.
    """

    from pydantic import TypeAdapter

    from scout.schemas.workspace_query import WorkspaceQueryRequest

    return TypeAdapter(WorkspaceQueryRequest).json_schema()


def query_project_workspace(
    project_root: str | Path,
    *,
    request: Mapping[str, Any],
) -> dict[str, Any]:
    from scout.services.workspace_query import WorkspaceQueryService

    response = WorkspaceQueryService(project_root).execute(request)
    return {
        "artifact_kind": WORKSPACE_QUERY_OUTPUT_KIND,
        "tool_id": WORKSPACE_QUERY_TOOL_ID,
        **response.model_dump(mode="json"),
        "boundary": {
            "read_only": True,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "network_access": False,
            "workspace_write_allowed": False,
            "phase1_safety_mutation_allowed": False,
        },
    }


__all__ = [
    "WORKSPACE_QUERY_OUTPUT_KIND",
    "WORKSPACE_QUERY_TOOL_ID",
    "query_project_workspace",
    "workspace_query_request_json_schema",
]
