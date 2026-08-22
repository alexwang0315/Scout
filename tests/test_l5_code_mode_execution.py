from __future__ import annotations

import json
from pathlib import Path

from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from scout.schemas.l5_code_mode import L5ActivationRequest
from scout.services.l5_code_mode import build_l5_code_mode_capability
from scout.services.l5_code_mode_execution import (
    L5_ALLOWED_TOOL_IDS,
    L5_ALLOWED_TOOL_NAMES,
    build_l5_execution_receipt,
    l5_tool_metadata,
)


def _workspace(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    project = workspace / "fixture"
    project.mkdir(parents=True)
    (project / "project.json").write_text(
        json.dumps({"project_id": "fixture"}), encoding="utf-8"
    )
    return workspace, project


def test_l5_allowlist_contains_only_workspace_query() -> None:
    assert L5_ALLOWED_TOOL_IDS == frozenset({"scout.ai.workspace.query.v1"})
    assert L5_ALLOWED_TOOL_NAMES == frozenset({"query_scout_workspace"})
    metadata = l5_tool_metadata("scout.ai.workspace.query.v1")
    assert metadata["l5_code_mode"] is True
    assert metadata["workspace_confined"] is True
    assert metadata["network_access"] is False


def test_l5_tool_metadata_rejects_unreviewed_tool() -> None:
    import pytest

    with pytest.raises(PermissionError, match="not admitted"):
        l5_tool_metadata("scout.ai.notification.send.v0")


def test_real_monty_code_mode_executes_allowlisted_tool_and_builds_receipt(
    tmp_path: Path,
) -> None:
    workspace, project = _workspace(tmp_path)
    calls: list[dict[str, object]] = []

    def model(messages: list[object], info: AgentInfo) -> ModelResponse:
        returned = any(
            isinstance(part, ToolReturnPart) and part.tool_name == "run_code"
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
        )
        if returned:
            return ModelResponse(parts=[TextPart("count=3 [outputs/checkpoints.json]")])
        assert [tool.name for tool in info.function_tools] == ["run_code"]
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="run_code",
                    args={
                        "code": (
                            "count_result = await query_scout_workspace(request={"
                            "'operation': 'count', 'artifact': {"
                            "'project_ref_key': 'checkpoint_candidates_ref'}})\n"
                            "max_result = await query_scout_workspace(request={"
                            "'operation': 'argmax', 'artifact': {"
                            "'project_ref_key': 'segment_candidates_ref'}, "
                            "'field': 'distance_m'})\n"
                            "{'count': count_result, 'longest': max_result}"
                        )
                    },
                    tool_call_id="l5-smoke",
                )
            ]
        )

    capability = build_l5_code_mode_capability(
        project_root=project,
        workspace_root=workspace,
        activation_request=L5ActivationRequest(under_construction=True),
    )
    agent = Agent(FunctionModel(model), capabilities=[capability])

    @agent.tool_plain(
        name="query_scout_workspace",
        metadata=l5_tool_metadata("scout.ai.workspace.query.v1"),
    )
    def query_scout_workspace(request: dict[str, object]) -> dict[str, object]:
        calls.append(request)
        operation = request["operation"]
        return {
            "status": "success",
            "summary": "count=3" if operation == "count" else "max=2008.6",
            "source_refs": [
                "outputs/checkpoints.json"
                if operation == "count"
                else "outputs/segments.json"
            ],
            "evidence_records": [
                {"evidence_id": "ev_1" if operation == "count" else "ev_2"}
            ],
        }

    result = agent.run_sync("Count checkpoints")
    receipt = build_l5_execution_receipt(
        result=result,
        activation_request=L5ActivationRequest(under_construction=True),
        project_id="fixture",
        prompt="Count checkpoints",
        duration_ms=1.0,
    )

    assert calls == [
        {
            "operation": "count",
            "artifact": {"project_ref_key": "checkpoint_candidates_ref"},
        },
        {
            "operation": "argmax",
            "artifact": {"project_ref_key": "segment_candidates_ref"},
            "field": "distance_m",
        },
    ]
    assert receipt.status == "success"
    assert receipt.allowed_tool_ids == ["scout.ai.workspace.query.v1"]
    assert receipt.code_mode_call_count == 1
    assert receipt.nested_tool_call_count == 2
    assert receipt.nested_tool_calls[0].tool_id == "scout.ai.workspace.query.v1"
    assert receipt.nested_tool_calls[0].source_refs == ["outputs/checkpoints.json"]
    assert receipt.nested_tool_calls[1].operation == "argmax"
    assert receipt.source_refs == [
        "outputs/checkpoints.json",
        "outputs/segments.json",
    ]
    assert receipt.generated_code_sha256
    assert receipt.generated_code is None
