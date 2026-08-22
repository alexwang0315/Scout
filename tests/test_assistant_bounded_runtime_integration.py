from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

import assistant_pydantic_provider as provider_module
from assistant_api import _pretrip_workspace_project_root_from_env
from assistant_models import AssistantObservability, AssistantSourceRef, ScoutAssistantQuery
from assistant_pydantic_provider import (
    GLOBAL_ASSISTANT_PROMPT,
    WORKSPACE_TOOL_PROMPT,
    PydanticAIEnvRunner,
    ScoutWorkspaceToolContext,
    _public_assistant_sources,
    _read_workspace_context,
    build_bounded_assistant_prompt,
)
from assistant_workspace_total_info import (
    TOTAL_INFO_SOURCE_ID,
    build_workspace_total_info_source_ref,
)
from scout.schemas.agent_runtime import (
    AgentRunBudget,
    AgentRunLedger,
    ContextHandle,
    EvidenceCard,
    QuestionClass,
)
from scout.services.bounded_agent_runtime import BoundedAgentRuntime
from scout_risk_score_tool import RISK_SCORE_TOOL_ID
from scout_workspace_search_tools import ROUTE_STRUCTURE_TOOL_ID


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
ROUTE_STRUCTURE_TOOL_NAME = provider_module.REGISTERED_WORKSPACE_TOOL_NAMES[
    ROUTE_STRUCTURE_TOOL_ID
]
WORKSPACE_QUERY_TOOL_NAME = provider_module.REGISTERED_WORKSPACE_TOOL_NAMES[
    provider_module.WORKSPACE_QUERY_TOOL_ID
]
WEATHER_WINDOW_TOOL_NAME = provider_module.REGISTERED_WORKSPACE_TOOL_NAMES[
    provider_module.WEATHER_WINDOW_TOOL_ID
]
CWA_ENVIRONMENT_TOOL_NAME = provider_module.REGISTERED_WORKSPACE_TOOL_NAMES[
    provider_module.CWA_ENVIRONMENT_TOOL_ID
]


def _checkpoint_count_response(
    info: AgentInfo,
    *,
    final_text: str,
) -> ModelResponse:
    tool_names = {tool.name for tool in info.function_tools}
    if ROUTE_STRUCTURE_TOOL_NAME in tool_names:
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=ROUTE_STRUCTURE_TOOL_NAME,
                    args={"query": "route checkpoints", "limit": 6},
                )
            ]
        )
    if WORKSPACE_QUERY_TOOL_NAME in tool_names:
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=WORKSPACE_QUERY_TOOL_NAME,
                    args={
                        "request": {
                            "operation": "count",
                            "artifact": {
                                "project_ref_key": "checkpoint_candidates_ref"
                            },
                        }
                    },
                )
            ]
        )
    return ModelResponse(parts=[TextPart(final_text)])


def test_bounded_prompt_contains_handles_not_duplicate_fixed_prompts() -> None:
    query = ScoutAssistantQuery(
        surface="pretrip",
        question="How many checkpoints are there?",
        project_id="chilai_nanhua_day1",
    )
    sources = [
        AssistantSourceRef(
            source_id="assistant_context.total_info",
            source_path="assistant_workspace_total_info",
            evidence_type="assistant_workspace_total_info",
            selected=True,
            context_summary={"raw": "x" * 20_000, "secret_token": "must-not-appear"},
        ),
        AssistantSourceRef(
            source_id="route.summary",
            source_path="outputs/route/summary.json",
            evidence_type="route_summary",
            selected=True,
            context_summary={"checkpoint_count": 124, "raw": "y" * 20_000},
        ),
    ]

    prompt = build_bounded_assistant_prompt(query, sources=sources, max_context_chars=2000)

    assert GLOBAL_ASSISTANT_PROMPT not in prompt
    assert WORKSPACE_TOOL_PROMPT not in prompt
    assert "secret_token" not in prompt
    assert '"checkpoint_count": 124' not in prompt
    assert '"raw"' not in prompt
    assert "outputs/route/summary.json" in prompt
    assert "context_handles" in prompt
    assert len(prompt) <= 2000


def test_pydantic_agent_progressively_discloses_and_then_removes_tools(
    monkeypatch,
) -> None:
    monkeypatch.setenv("SCOUT_PRETRIP_WORKSPACE_ROOT", str(PROJECT_ROOT.parent))

    def model_function(_messages: list[object], info: AgentInfo) -> ModelResponse:
        return _checkpoint_count_response(
            info,
            final_text=(
                "There are checkpoints in the route evidence "
                "[candidates/checkpoints.json]."
            ),
        )

    monkeypatch.setattr(
        provider_module,
        "build_chat_model",
        lambda **_kwargs: FunctionModel(model_function),
    )
    query = ScoutAssistantQuery(
        surface="pretrip",
        question="目前這條 route 有多少個 CP？",
        context_ref=PROJECT_ROOT.name,
        project_id=PROJECT_ROOT.name,
    )
    tool_context = ScoutWorkspaceToolContext.from_query_and_env(query, sources=[])
    runner = PydanticAIEnvRunner(
        model_name="test:model",
        profile_name="local",
        workspace_tools_enabled=True,
    )

    output = runner._run_model_with_workspace_tools(
        build_bounded_assistant_prompt(query, sources=[], max_context_chars=2000),
        tool_context,
        request_timeout_seconds=10,
    )

    ledger = runner.last_agent_run_ledger
    assert output == (
        "There are checkpoints in the route evidence "
        "[candidates/checkpoints.json]."
    )
    assert ledger["request_count"] == 3
    assert ledger["selected_tool_ids"] == [
        ROUTE_STRUCTURE_TOOL_ID,
        provider_module.WORKSPACE_QUERY_TOOL_ID,
    ]
    assert ledger["executed_tool_ids"] == [
        ROUTE_STRUCTURE_TOOL_ID,
        provider_module.WORKSPACE_QUERY_TOOL_ID,
    ]
    assert ledger["tool_call_count"] == 2
    assert ledger["requests"][0]["tool_schema_chars"] > 0
    assert ledger["requests"][0]["tool_schema_count"] == 1
    assert ledger["requests"][1]["tool_schema_chars"] > 0
    assert ledger["requests"][1]["tool_schema_count"] == 1
    assert ledger["requests"][2]["tool_schema_chars"] == 0
    assert ledger["requests"][2]["tool_schema_count"] == 0
    assert ledger["tool_schema_chars"] < 20_000
    assert ledger["tool_result_chars"] > 0
    assert ledger["tool_result_chars"] < 20_000
    assert ledger["budget_stop_reason"] is None
    selected_context_ids = [
        item["context_id"] for item in runner.last_context_handles
    ]
    assert "scout.context.route_structure" in selected_context_ids
    assert len(selected_context_ids) <= 10
    assert [item["tool_id"] for item in runner.last_workspace_tool_invocations] == [
        ROUTE_STRUCTURE_TOOL_ID,
        provider_module.WORKSPACE_QUERY_TOOL_ID,
    ]


def test_pydantic_agent_returns_weather_tool_evidence_without_spurious_count(
    monkeypatch,
) -> None:
    monkeypatch.setenv("SCOUT_PRETRIP_WORKSPACE_ROOT", str(PROJECT_ROOT.parent))

    def model_function(_messages: list[object], info: AgentInfo) -> ModelResponse:
        tool_names = {tool.name for tool in info.function_tools}
        if WEATHER_WINDOW_TOOL_NAME in tool_names:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name=WEATHER_WINDOW_TOOL_NAME,
                        args={"query": "今天的雨量預計是多少"},
                    )
                ]
            )
        if CWA_ENVIRONMENT_TOOL_NAME in tool_names:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name=CWA_ENVIRONMENT_TOOL_NAME,
                        args={"query": "今天的雨量預計是多少"},
                    )
                ]
            )
        return ModelResponse(
            parts=[
                TextPart(
                    "Direct QPF corridor summary：max 為 32.0 mm、"
                    "mean 為 18.4 mm、p95 為 29.1 mm、peak window 為 "
                    "2026-06-24T12:00:00Z/2026-06-24T18:00:00Z "
                    "[evidence:1]。"
                )
            ]
        )

    monkeypatch.setattr(
        provider_module,
        "build_chat_model",
        lambda **_kwargs: FunctionModel(model_function),
    )
    query = ScoutAssistantQuery(
        surface="pretrip",
        question="今天的雨量預計是多少",
        context_ref=PROJECT_ROOT.name,
        project_id=PROJECT_ROOT.name,
    )
    tool_context = ScoutWorkspaceToolContext.from_query_and_env(query, sources=[])
    runner = PydanticAIEnvRunner(
        model_name="test:model",
        profile_name="cloud",
        workspace_tools_enabled=True,
    )

    output = runner._run_model_with_workspace_tools(
        build_bounded_assistant_prompt(query, sources=[], max_context_chars=2_000),
        tool_context,
        request_timeout_seconds=10,
    )

    assert "max 為 32.0 mm" in output
    assert "[evidence:1]" not in output
    assert "[outputs/environment/cwa/qpf_corridor_summary.json]" in output
    assert "所選 Scout 工具的證據" not in output
    assert runner.last_agent_run_ledger["selected_tool_ids"] == [
        provider_module.WEATHER_WINDOW_TOOL_ID,
        provider_module.CWA_ENVIRONMENT_TOOL_ID,
    ]
    assert runner.last_agent_run_ledger["executed_tool_ids"] == [
        provider_module.WEATHER_WINDOW_TOOL_ID,
        provider_module.CWA_ENVIRONMENT_TOOL_ID,
    ]
    assert [
        item["tool_id"] for item in runner.last_workspace_tool_invocations
    ] == [
        provider_module.WEATHER_WINDOW_TOOL_ID,
        provider_module.CWA_ENVIRONMENT_TOOL_ID,
    ]


def test_pydantic_agent_fails_closed_when_selected_tool_is_not_executed(
    monkeypatch,
) -> None:
    monkeypatch.setenv("SCOUT_PRETRIP_WORKSPACE_ROOT", str(PROJECT_ROOT.parent))
    selected_ids = [ROUTE_STRUCTURE_TOOL_ID, RISK_SCORE_TOOL_ID]
    selected_names = [
        provider_module.REGISTERED_WORKSPACE_TOOL_NAMES[tool_id]
        for tool_id in selected_ids
    ]
    monkeypatch.setattr(
        provider_module,
        "_progressive_tool_runtime",
        lambda _tool_context: (
            BoundedAgentRuntime(),
            selected_ids,
            selected_names,
            [SimpleNamespace(tool_id=tool_id) for tool_id in selected_ids],
            SimpleNamespace(expected_operations=[]),
        ),
    )
    request_count = 0

    def model_function(messages: list[object], info: AgentInfo) -> ModelResponse:
        del messages
        nonlocal request_count
        request_count += 1
        tool_names = [tool.name for tool in info.function_tools]
        if request_count == 1:
            assert tool_names == selected_names
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name=selected_names[0],
                        args={"query": "route checkpoints"},
                    )
                ]
            )
        assert tool_names == [selected_names[1]]
        return ModelResponse(
            parts=[
                TextPart(
                    "The route has checkpoint evidence "
                    "[candidates/checkpoints.json]."
                )
            ]
        )

    monkeypatch.setattr(
        provider_module,
        "build_chat_model",
        lambda **_kwargs: FunctionModel(model_function),
    )
    query = ScoutAssistantQuery(
        surface="pretrip",
        question="哪些 CP 的風險最高？",
        context_ref=PROJECT_ROOT.name,
        project_id=PROJECT_ROOT.name,
    )
    tool_context = ScoutWorkspaceToolContext.from_query_and_env(query, sources=[])
    runner = PydanticAIEnvRunner(
        model_name="test:model",
        profile_name="local",
        workspace_tools_enabled=True,
    )

    output = runner._run_model_with_workspace_tools(
        build_bounded_assistant_prompt(query, sources=[], max_context_chars=2_000),
        tool_context,
        request_timeout_seconds=10,
    )

    assert "checkpoint evidence" not in output
    assert runner.last_grounding_verification["passed"] is False
    assert runner.last_grounding_verification["output_disposition"] == "fail_closed"
    assert (
        f"missing_selected_tool_evidence:{RISK_SCORE_TOOL_ID}"
        in runner.last_grounding_verification["repair_items"]
    )
    assert runner.last_agent_run_ledger["executed_tool_ids"] == [
        ROUTE_STRUCTURE_TOOL_ID
    ]
    assert runner.last_agent_run_ledger["budget_stop_reason"] == (
        "selected_tools_partially_executed"
    )


def test_pydantic_agent_direct_answer_uses_one_request_and_no_tool_schema(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        provider_module,
        "build_chat_model",
        lambda **_kwargs: TestModel(custom_output_text="嗨，我是 Scout AI。"),
    )
    query = ScoutAssistantQuery(surface="pretrip", question="嗨")
    tool_context = ScoutWorkspaceToolContext.from_query_and_env(query, sources=[])
    runner = PydanticAIEnvRunner(
        model_name="test:model",
        profile_name="local",
        workspace_tools_enabled=True,
    )

    output = runner._run_model_with_workspace_tools(
        build_bounded_assistant_prompt(query, sources=[], max_context_chars=2000),
        tool_context,
        request_timeout_seconds=10,
    )

    assert output == "嗨，我是 Scout AI。"
    assert runner.last_agent_run_ledger["request_count"] == 1
    assert runner.last_agent_run_ledger["tool_call_count"] == 0
    assert runner.last_agent_run_ledger["tool_schema_count"] == 0
    assert runner.last_agent_run_ledger["selected_tool_ids"] == []


def test_pydantic_agent_fails_closed_when_substantive_question_has_no_evidence(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        provider_module,
        "_progressive_tool_runtime",
        lambda _tool_context: (
            BoundedAgentRuntime(),
            [],
            [],
            [],
            SimpleNamespace(expected_operations=[]),
        ),
    )
    monkeypatch.setattr(
        provider_module,
        "build_chat_model",
        lambda **_kwargs: TestModel(custom_output_text="這條路線有 124 個 CP。"),
    )
    query = ScoutAssistantQuery(
        surface="pretrip",
        question="這條路線有多少個 CP？",
    )
    tool_context = ScoutWorkspaceToolContext.from_query_and_env(query, sources=[])
    runner = PydanticAIEnvRunner(
        model_name="test:model",
        profile_name="local",
        workspace_tools_enabled=True,
    )

    output = runner._run_model_with_workspace_tools(
        build_bounded_assistant_prompt(query, sources=[], max_context_chars=2_000),
        tool_context,
        request_timeout_seconds=10,
    )

    assert "124" not in output
    assert "沒有取得可驗證的 Scout 證據" in output
    assert runner.last_grounding_verification["passed"] is False
    assert runner.last_grounding_verification["output_disposition"] == "fail_closed"


def test_pydantic_agent_does_not_discard_answer_for_token_telemetry(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        provider_module,
        "build_chat_model",
        lambda **_kwargs: TestModel(custom_output_text="嗨，我是 Scout AI。"),
    )
    monkeypatch.setattr(
        provider_module,
        "_response_usage_fields",
        lambda _response: {
            "input_tokens": 1,
            "output_tokens": 1_000_000,
        },
    )
    query = ScoutAssistantQuery(surface="pretrip", question="嗨")
    tool_context = ScoutWorkspaceToolContext.from_query_and_env(query, sources=[])
    runner = PydanticAIEnvRunner(
        model_name="test:model",
        profile_name="local",
        workspace_tools_enabled=True,
    )

    output = runner._run_model_with_workspace_tools(
        build_bounded_assistant_prompt(query, sources=[], max_context_chars=2_000),
        tool_context,
        request_timeout_seconds=10,
    )

    assert output == "嗨，我是 Scout AI。"
    assert runner.last_agent_run_ledger["budget_stop_reason"] is None


def test_bounded_plain_model_does_not_discard_answer_for_token_telemetry(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        provider_module,
        "build_chat_model",
        lambda **_kwargs: TestModel(custom_output_text="unbounded answer"),
    )
    monkeypatch.setattr(
        provider_module,
        "_serialize_pydantic_result_usage",
        lambda _result: {
            "requests": 1,
            "tool_calls": 0,
            "input_tokens": 1,
            "output_tokens": 1_000_000,
        },
    )
    runner = PydanticAIEnvRunner(
        model_name="test:model",
        profile_name="local",
        workspace_tools_enabled=False,
    )

    output = runner._run_model("question", request_timeout_seconds=10)

    assert output == "unbounded answer"
    assert runner.last_agent_run_ledger["budget_stop_reason"] is None


def test_workspace_external_limit_checkpoints_and_continues_with_fresh_budget(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        provider_module,
        "build_chat_model",
        lambda **_kwargs: TestModel(
            custom_output_text=(
                "最高候選是 CP 213 [outputs/risk/candidates.json]。"
            )
        ),
    )
    runner = PydanticAIEnvRunner(
        model_name="test:model",
        profile_name="local",
        workspace_tools_enabled=True,
    )
    budget = AgentRunBudget(question_class=QuestionClass.CROSS_ARTIFACT_JOIN)
    initial_ledger = AgentRunLedger(
        budget=budget,
        budget_stop_reason="provider_usage_limit_before_request:UsageLimitExceeded",
    )
    card = EvidenceCard(
        tool_id=RISK_SCORE_TOOL_ID,
        claim_summary="CP 213 is the highest candidate route-risk location.",
        key_values={"cp": "CP 213"},
        source_refs=["outputs/risk/candidates.json"],
        result_count=1,
    )

    output = runner._recover_workspace_external_limit(
        question="哪個 CP 的候選風險最高？",
        question_class=QuestionClass.CROSS_ARTIFACT_JOIN,
        model_id="test:model",
        initial_ledger=initial_ledger,
        evidence_cards=[card.model_dump(mode="json")],
        call_trace=[{"operation": "argmax", "status": "completed"}],
        reason="provider_usage_limit_before_request:UsageLimitExceeded",
        timeout_seconds=None,
    )

    recovery = runner.last_agent_recovery
    attempts = recovery["attempts"]
    assert "budget exhausted" not in output.casefold()
    assert output == "最高候選是 CP 213 [outputs/risk/candidates.json]。"
    assert recovery["status"] == "continued_successfully"
    assert recovery["checkpoint"]["external_limit"] is True
    assert [item["recovery_stage"] for item in attempts] == [
        "initial",
        "continuation",
    ]
    assert [item["attempt_index"] for item in attempts] == [1, 2]
    assert all(item["budget"]["max_tool_calls"] >= 10 for item in attempts)
    assert all(item["budget"]["max_requests"] >= 10 for item in attempts)
    assert attempts[0]["status"] == "external_limit"
    assert attempts[1]["status"] == "succeeded"
    assert runner.last_grounding_verification["passed"] is True


def test_bounded_workspace_path_does_not_disclose_unselected_native_capabilities(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        provider_module,
        "build_chat_model",
        lambda **_kwargs: TestModel(custom_output_text="嗨，我是 Scout AI。"),
    )
    query = ScoutAssistantQuery(surface="pretrip", question="嗨")
    tool_context = ScoutWorkspaceToolContext.from_query_and_env(query, sources=[])
    runner = PydanticAIEnvRunner(
        model_name="openrouter:openrouter/free",
        workspace_tools_enabled=True,
    )

    def fail_if_called() -> list[object]:
        raise AssertionError("unselected native capabilities must not be disclosed")

    monkeypatch.setattr(runner, "_native_capabilities", fail_if_called)

    output = runner._run_model_with_workspace_tools(
        build_bounded_assistant_prompt(query, sources=[], max_context_chars=2_000),
        tool_context,
        request_timeout_seconds=10,
    )

    assert output == "嗨，我是 Scout AI。"
    assert runner.last_agent_run_ledger["tool_schema_count"] == 0


def test_workspace_artifact_context_is_read_through_progressive_tools(
    monkeypatch,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "context_project"
    (project_root / "outputs").mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "project_id": project_root.name,
                "readiness_report_ref": "outputs/readiness_report.json",
            }
        ),
        encoding="utf-8",
    )
    (project_root / "outputs" / "readiness_report.json").write_text(
        json.dumps(
            {
                "status": "review_required",
                "blockers": ["missing weather issue time"],
                "warnings": ["daylight margin is partial"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SCOUT_PRETRIP_WORKSPACE_ROOT", str(tmp_path))
    catalog_tool_name = provider_module.REGISTERED_WORKSPACE_TOOL_NAMES[
        provider_module.WORKSPACE_CATALOG_TOOL_ID
    ]

    def model_function(_messages: list[object], info: AgentInfo) -> ModelResponse:
        tool_names = {tool.name for tool in info.function_tools}
        if catalog_tool_name in tool_names:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name=catalog_tool_name,
                        args={"query": "readiness report", "limit": 6},
                    )
                ]
            )
        if WORKSPACE_QUERY_TOOL_NAME in tool_names:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name=WORKSPACE_QUERY_TOOL_NAME,
                        args={
                            "request": {
                                "operation": "inspect",
                                "artifact": {
                                    "source_ref": "outputs/readiness_report.json"
                                },
                            }
                        },
                    )
                ]
            )
        return ModelResponse(
            parts=[
                TextPart(
                    "Readiness still requires review "
                    "[outputs/readiness_report.json]."
                )
            ]
        )

    monkeypatch.setattr(
        provider_module,
        "build_chat_model",
        lambda **_kwargs: FunctionModel(model_function),
    )
    query = ScoutAssistantQuery(
        surface="pretrip",
        question="readiness report 目前列出的 blocker 與 warning 各有哪些？",
        context_ref=project_root.name,
        project_id=project_root.name,
    )
    tool_context = ScoutWorkspaceToolContext.from_query_and_env(query, sources=[])
    runner = PydanticAIEnvRunner(
        model_name="test:model",
        profile_name="local",
        workspace_tools_enabled=True,
    )

    output = runner._run_model_with_workspace_tools(
        build_bounded_assistant_prompt(query, sources=[], max_context_chars=2_000),
        tool_context,
        request_timeout_seconds=10,
    )

    assert output == (
        "Readiness still requires review [outputs/readiness_report.json]."
    )
    assert runner.last_agent_run_ledger["request_count"] == 3
    assert runner.last_agent_run_ledger["tool_schema_count"] == 2
    assert runner.last_agent_run_ledger["selected_tool_ids"] == [
        provider_module.WORKSPACE_CATALOG_TOOL_ID,
        provider_module.WORKSPACE_QUERY_TOOL_ID,
    ]
    assert runner.last_context_reads == []
    assert runner.last_grounding_verification["passed"] is True


def test_private_context_handle_cannot_be_read_without_permission(
    tmp_path: Path,
) -> None:
    private_path = tmp_path / "outputs" / "health.json"
    private_path.parent.mkdir(parents=True)
    private_path.write_text('{"heart_rate": 120}', encoding="utf-8")
    handle = ContextHandle(
        context_id="workspace.artifact.health_ref",
        domain_id="health",
        artifact_kind="health",
        title="health",
        source_ref="outputs/health.json",
        sensitivity="private",
    )

    result = _read_workspace_context(tmp_path, handle, token_budget=500)

    assert result is None


def test_public_total_info_projection_excludes_location_health_and_sensor_values() -> None:
    source = AssistantSourceRef(
        source_id=TOTAL_INFO_SOURCE_ID,
        source_path="workspace.total_info_entry",
        evidence_type="assistant_workspace_total_info",
        selected=True,
        context_summary={
            "artifact_kind": "assistant_workspace_total_info_context",
            "project_id": "fixture",
            "location_context": {"status": "available", "lat": 23.1, "lon": 121.2},
            "body_resource_context": {"status": "available", "heart_rate": 170},
            "sensor_snapshot_context": {"status": "available", "imu": [1, 2, 3]},
            "route_context": {"status": "available", "distance_km": 20},
            "missing_or_partial_context": ["weather_environment_context"],
        },
    )

    public = _public_assistant_sources([source])[0].context_summary

    assert public["artifact_kind"] == "assistant_workspace_total_info_context"
    assert public["context_statuses"] == {
        "body_resource_context": "available",
        "location_context": "available",
        "route_context": "available",
        "sensor_snapshot_context": "available",
    }
    assert public["missing_or_partial_context_count"] == 1
    serialized = json.dumps(public, sort_keys=True)
    assert "23.1" not in serialized
    assert "121.2" not in serialized
    assert "170" not in serialized
    assert "imu" not in serialized


def test_workspace_project_manifest_symlink_is_rejected(
    monkeypatch,
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspaces"
    project_root = workspace_root / "fixture"
    project_root.mkdir(parents=True)
    external_manifest = tmp_path / "external-project.json"
    external_manifest.write_text('{"project_id":"fixture"}', encoding="utf-8")
    (project_root / "project.json").symlink_to(external_manifest)
    monkeypatch.setenv("SCOUT_PRETRIP_WORKSPACE_ROOT", str(workspace_root))
    query = ScoutAssistantQuery(
        surface="pretrip",
        question="workspace 有什麼？",
        project_id="fixture",
    )

    assert _pretrip_workspace_project_root_from_env(query) is None
    assert (
        build_workspace_total_info_source_ref(
            query,
            project_root=project_root,
        )
        is None
    )


def test_ten_x_workspace_growth_keeps_user_turn_tokens_within_ten_percent(
    monkeypatch,
) -> None:
    monkeypatch.setenv("SCOUT_PRETRIP_WORKSPACE_ROOT", str(PROJECT_ROOT.parent))

    def model_function(_messages: list[object], info: AgentInfo) -> ModelResponse:
        return _checkpoint_count_response(
            info,
            final_text=(
                "Route evidence is available [candidates/checkpoints.json]."
            ),
        )

    monkeypatch.setattr(
        provider_module,
        "build_chat_model",
        lambda **_kwargs: FunctionModel(model_function),
    )
    query = ScoutAssistantQuery(
        surface="pretrip",
        question="目前這條 route 有多少個 CP？",
        context_ref=PROJECT_ROOT.name,
        project_id=PROJECT_ROOT.name,
    )
    stable_sources = [
        AssistantSourceRef(
            source_id="route.summary",
            source_path="normalized/routes/route_summary.json",
            evidence_type="route_summary",
            selected=True,
            context_summary={"checkpoint_count": 124},
        ),
        *[
            AssistantSourceRef(
                source_id=f"archive.{index}",
                source_path=f"outputs/archive/{index}.json",
                evidence_type="unrelated_archive",
                selected=False,
                context_summary={"payload": "x" * 2_000},
            )
            for index in range(9)
        ],
    ]
    expanded_sources = [
        *stable_sources,
        *[
            AssistantSourceRef(
                source_id=f"expanded.{index}",
                source_path=f"outputs/expanded/{index}.json",
                evidence_type="unrelated_archive",
                selected=False,
                context_summary={"payload": "y" * 2_000},
            )
            for index in range(90)
        ],
    ]

    def run_with_sources(sources: list[AssistantSourceRef]) -> dict[str, object]:
        runner = PydanticAIEnvRunner(
            model_name="test:model",
            profile_name="local",
            workspace_tools_enabled=True,
        )
        tool_context = ScoutWorkspaceToolContext.from_query_and_env(
            query,
            sources=sources,
        )
        runner._run_model_with_workspace_tools(
            build_bounded_assistant_prompt(
                query,
                sources=sources,
                max_context_chars=2_000,
            ),
            tool_context,
            request_timeout_seconds=10,
        )
        return runner.last_agent_run_ledger

    baseline = run_with_sources(stable_sources)
    expanded = run_with_sources(expanded_sources)

    assert int(expanded["input_tokens"]) <= int(baseline["input_tokens"]) * 1.10
    assert expanded["tool_schema_count"] == baseline["tool_schema_count"] == 2
    assert int(expanded["tool_schema_chars"]) == int(baseline["tool_schema_chars"])


def test_pydantic_agent_runs_one_no_tool_grounding_repair(monkeypatch) -> None:
    monkeypatch.setenv("SCOUT_PRETRIP_WORKSPACE_ROOT", str(PROJECT_ROOT.parent))
    repair_max_tokens: list[int | None] = []

    def model_function(messages: list[object], info: AgentInfo) -> ModelResponse:
        if info.function_tools:
            return _checkpoint_count_response(
                info,
                final_text="unused while tools are available",
            )
        if "SCOUT_BOUNDED_SYNTHESIS_REPAIR_V1" in str(messages):
            repair_max_tokens.append(info.model_settings.get("max_tokens"))
            return ModelResponse(
                parts=[
                    TextPart(
                        "這條路線有 124 個檢查點 "
                        "[candidates/checkpoints.json]。"
                    )
                ]
            )
        return ModelResponse(parts=[TextPart("這條路線有 999 個檢查點。")])

    monkeypatch.setattr(
        provider_module,
        "build_chat_model",
        lambda **_kwargs: FunctionModel(model_function),
    )
    query = ScoutAssistantQuery(
        surface="pretrip",
        question="目前這條 route 有多少個 CP？",
        context_ref=PROJECT_ROOT.name,
        project_id=PROJECT_ROOT.name,
    )
    tool_context = ScoutWorkspaceToolContext.from_query_and_env(query, sources=[])
    runner = PydanticAIEnvRunner(
        model_name="test:model",
        profile_name="local",
        workspace_tools_enabled=True,
    )

    output = runner._run_model_with_workspace_tools(
        build_bounded_assistant_prompt(query, sources=[], max_context_chars=2000),
        tool_context,
        request_timeout_seconds=10,
    )

    assert output == "這條路線有 124 個檢查點 [candidates/checkpoints.json]。"
    assert runner.last_agent_run_ledger["request_count"] == 4
    assert runner.last_agent_run_ledger["repair_count"] == 1
    assert runner.last_agent_run_ledger["requests"][3]["tool_schema_count"] == 0
    assert runner.last_agent_run_ledger["requests"][3]["repair_count"] == 1
    assert runner.last_grounding_verification["passed"] is True
    assert repair_max_tokens == [None]


def test_cloud_profile_grounding_repair_supports_unbounded_model_max_tokens(
    monkeypatch,
) -> None:
    monkeypatch.setenv("SCOUT_PRETRIP_WORKSPACE_ROOT", str(PROJECT_ROOT.parent))
    repair_max_tokens: list[int | None] = []

    def model_function(messages: list[object], info: AgentInfo) -> ModelResponse:
        if info.function_tools:
            return _checkpoint_count_response(
                info,
                final_text="unused while tools are available",
            )
        if "SCOUT_BOUNDED_SYNTHESIS_REPAIR_V1" in str(messages):
            repair_max_tokens.append(info.model_settings.get("max_tokens"))
            return ModelResponse(
                parts=[
                    TextPart(
                        "這條路線有 124 個檢查點 "
                        "[candidates/checkpoints.json]。"
                    )
                ]
            )
        return ModelResponse(parts=[TextPart("這條路線有 999 個檢查點。")])

    monkeypatch.setattr(
        provider_module,
        "build_chat_model",
        lambda **_kwargs: FunctionModel(model_function),
    )
    query = ScoutAssistantQuery(
        surface="pretrip",
        question="目前這條 route 有多少個 CP？",
        context_ref=PROJECT_ROOT.name,
        project_id=PROJECT_ROOT.name,
    )
    tool_context = ScoutWorkspaceToolContext.from_query_and_env(query, sources=[])
    runner = PydanticAIEnvRunner(
        model_name="openrouter:test/model",
        profile_name="cloud",
        workspace_tools_enabled=True,
        workspace_model_max_tokens=None,
    )

    output = runner._run_model_with_workspace_tools(
        build_bounded_assistant_prompt(query, sources=[], max_context_chars=2_000),
        tool_context,
        request_timeout_seconds=10,
    )

    assert output == "這條路線有 124 個檢查點 [candidates/checkpoints.json]。"
    assert runner.last_grounding_verification["passed"] is True
    assert repair_max_tokens
    assert repair_max_tokens[0] is None


def test_pydantic_agent_allows_one_schema_retry_before_bounded_synthesis(
    monkeypatch,
) -> None:
    monkeypatch.setenv("SCOUT_PRETRIP_WORKSPACE_ROOT", str(PROJECT_ROOT.parent))
    route_request_count = 0

    def model_function(messages: list[object], info: AgentInfo) -> ModelResponse:
        del messages
        nonlocal route_request_count
        tool_names = {tool.name for tool in info.function_tools}
        if ROUTE_STRUCTURE_TOOL_NAME in tool_names:
            route_request_count += 1
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name=ROUTE_STRUCTURE_TOOL_NAME,
                        args={
                            "query": "route checkpoints",
                            "limit": (
                                "invalid" if route_request_count == 1 else 3
                            ),
                        },
                    )
                ]
            )
        if WORKSPACE_QUERY_TOOL_NAME in tool_names:
            return _checkpoint_count_response(
                info,
                final_text="unused while tools are available",
            )
        return ModelResponse(
            parts=[
                TextPart(
                    "Route evidence is available "
                    "[candidates/checkpoints.json]."
                )
            ]
        )

    monkeypatch.setattr(
        provider_module,
        "build_chat_model",
        lambda **_kwargs: FunctionModel(model_function),
    )
    query = ScoutAssistantQuery(
        surface="pretrip",
        question="目前這條 route 有多少個 CP？",
        context_ref=PROJECT_ROOT.name,
        project_id=PROJECT_ROOT.name,
    )
    tool_context = ScoutWorkspaceToolContext.from_query_and_env(query, sources=[])
    runner = PydanticAIEnvRunner(
        model_name="test:model",
        profile_name="local",
        workspace_tools_enabled=True,
    )

    output = runner._run_model_with_workspace_tools(
        build_bounded_assistant_prompt(query, sources=[], max_context_chars=2_000),
        tool_context,
        request_timeout_seconds=10,
    )

    assert output == (
        "Route evidence is available [candidates/checkpoints.json]."
    )
    assert runner.last_agent_run_ledger["request_count"] == 4
    assert runner.last_agent_run_ledger["retry_count"] == 1
    assert runner.last_agent_run_ledger["repair_count"] == 0
    assert runner.last_agent_run_ledger["budget_stop_reason"] is None
    assert runner.last_grounding_verification["passed"] is True


def test_pydantic_agent_fails_closed_after_one_bad_repair(monkeypatch) -> None:
    monkeypatch.setenv("SCOUT_PRETRIP_WORKSPACE_ROOT", str(PROJECT_ROOT.parent))

    def model_function(_messages: list[object], info: AgentInfo) -> ModelResponse:
        return _checkpoint_count_response(
            info,
            final_text="這條路線有 999 個檢查點。",
        )

    monkeypatch.setattr(
        provider_module,
        "build_chat_model",
        lambda **_kwargs: FunctionModel(model_function),
    )
    query = ScoutAssistantQuery(
        surface="pretrip",
        question="目前這條 route 有多少個 CP？",
        context_ref=PROJECT_ROOT.name,
        project_id=PROJECT_ROOT.name,
    )
    tool_context = ScoutWorkspaceToolContext.from_query_and_env(query, sources=[])
    runner = PydanticAIEnvRunner(
        model_name="test:model",
        profile_name="local",
        workspace_tools_enabled=True,
    )

    output = runner._run_model_with_workspace_tools(
        build_bounded_assistant_prompt(query, sources=[], max_context_chars=2000),
        tool_context,
        request_timeout_seconds=10,
    )

    assert "999" not in output
    assert "未通過證據引用檢查" in output
    assert runner.last_agent_run_ledger["request_count"] == 4
    assert runner.last_agent_run_ledger["repair_count"] == 1
    assert runner.last_agent_run_ledger["budget_stop_reason"] == (
        "grounding_verification_failed_after_repair"
    )
    assert runner.last_grounding_verification["passed"] is False
    assert runner.last_grounding_verification["output_disposition"] == "fail_closed"
    assert runner.last_grounding_verification["unsupported_claims"] == []
    assert runner.last_grounding_verification["rejected_draft_claims"] == [
        "這條路線有 999 個檢查點。"
    ]


def test_assistant_observability_accepts_additive_bounded_runtime_fields() -> None:
    observability = AssistantObservability(
        provider_class="PydanticAIAssistantProvider",
        source_count=4,
        selected_source_count=3,
        context_size_chars=900,
        latency_ms=50,
        latency_class="fast",
        request_count=2,
        tool_call_count=1,
        input_tokens=2100,
        cache_write_tokens=0,
        cache_read_tokens=500,
        output_tokens=220,
        system_chars=900,
        tool_schema_chars=1800,
        user_history_chars=1200,
        tool_result_chars=800,
        selected_tool_ids=[ROUTE_STRUCTURE_TOOL_ID],
        executed_tool_ids=[ROUTE_STRUCTURE_TOOL_ID],
        retry_count=0,
        repair_count=0,
        budget_stop_reason=None,
    )

    payload = observability.model_dump(mode="json")
    assert payload["request_count"] == 2
    assert payload["tool_schema_chars"] == 1800
    assert payload["selected_tool_ids"] == [ROUTE_STRUCTURE_TOOL_ID]
