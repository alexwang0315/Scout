"""Repeatable Pydantic AI compatibility smoke for Scout AI OS."""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import os
import re
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel
from pydantic_ai import Agent, ModelRetry, Tool, ToolFailed, UsageLimits
from pydantic_ai.capabilities.web_fetch import WebFetch
from pydantic_ai.capabilities.web_search import WebSearch
from pydantic_ai.exceptions import ModelHTTPError, UserError
from pydantic_ai.messages import (
    CompactionPart,
    ModelMessagesTypeAdapter,
    ModelResponse,
    NativeToolCallPart,
    NativeToolReturnPart,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.native_tools import AdvisorTool, WebSearchTool

from scout.agents.local_web_fetch import build_local_web_fetch
from scout.agents.local_web_search import build_local_web_search
from scout.agents.model_policy import resolve_model_policy
from scout.agents.pydantic_ai_compat import (
    build_chat_model,
    pydantic_agent_runtime_kwargs,
    pydantic_native_research_capabilities,
)

REQUIRED_VERSION = "2.33.0"
DEFAULT_OPENROUTER_MODEL = "deepseek/deepseek-v3.2"
DEFAULT_TIMEOUT_SECONDS = 120.0


class StructuredSmokeOutput(BaseModel):
    status: Literal["ok"]
    evidence_count: int


class LiveStructuredSmokeOutput(BaseModel):
    status: Literal["ok"]
    runtime_version: str


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run Scout's Pydantic AI offline and OpenRouter compatibility smoke."
        )
    )
    parser.add_argument(
        "--live-openrouter",
        action="store_true",
        help="Also execute real OpenRouter model, tool, MCP, and web checks.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="OpenRouter vendor/model id. Defaults to SCOUT_AI_OS_MODEL.",
    )
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Server-side env file used only to load the OpenRouter credential.",
    )
    args = parser.parse_args(argv)
    report = asyncio.run(
        run_compatibility_smoke(
            live_openrouter=args.live_openrouter,
            model_name=args.model,
            env_file=Path(args.env_file),
        )
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


async def run_compatibility_smoke(
    *,
    live_openrouter: bool = False,
    model_name: str | None = None,
    env_file: Path | None = None,
) -> dict[str, Any]:
    if env_file is not None:
        _load_env_file(env_file)
    checks = await _run_checks(_offline_checks())
    resolved_model = _normalize_openrouter_model(
        model_name or os.getenv("SCOUT_AI_OS_MODEL") or DEFAULT_OPENROUTER_MODEL
    )
    if live_openrouter:
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            checks.append(
                {
                    "name": "live_openrouter_credentials",
                    "status": "failed",
                    "error_type": "MissingCredential",
                    "error": "OPENROUTER_API_KEY is not configured.",
                }
            )
        else:
            model = build_chat_model(model_name=resolved_model, api_key=api_key)
            checks.extend(await _run_checks(_live_checks(model)))
    failed = [item for item in checks if item["status"] != "passed"]
    return {
        "artifact_kind": "scout_pydantic_ai_compatibility_smoke",
        "schema_version": "scout.pydantic_ai.compatibility_smoke.v1",
        "status": "passed" if not failed else "failed",
        "required_version": REQUIRED_VERSION,
        "package_versions": _package_versions(),
        "live_openrouter_requested": live_openrouter,
        "openrouter_credential_present": bool(os.getenv("OPENROUTER_API_KEY")),
        "model": resolved_model if live_openrouter else None,
        "check_count": len(checks),
        "passed_count": len(checks) - len(failed),
        "failed_count": len(failed),
        "checks": checks,
    }


def _offline_checks() -> list[tuple[str, Callable[[], Any]]]:
    return [
        ("runtime_versions", _offline_runtime_versions),
        ("v232_capability_contract", _offline_v232_capability_contract),
        ("openrouter_web_search_annotations", _offline_openrouter_annotations),
        ("instrumentation_v6_tool_role", _offline_instrumentation_v6_tool_role),
        ("function_tool_call", _offline_function_tool_call),
        ("blocking_sync_tool_timeout", _offline_blocking_sync_tool_timeout),
        ("nested_sync_agent_run_rejected", _offline_nested_sync_agent_run_rejected),
        ("structured_output", _offline_structured_output),
        ("mcp_instructions_and_tool", _offline_mcp_instructions),
        ("web_capability_contract", _offline_web_capabilities),
        ("stream_events_and_compaction", _offline_stream_events_and_compaction),
        ("agent_web_content_type_guard", _offline_agent_web_content_type_guard),
        ("agent_web_host_guard", _offline_agent_web_host_guard),
        ("tool_failed_visible_without_retry", _offline_tool_failed),
        ("model_retry_then_success", _offline_model_retry),
        ("external_cancellation", _offline_cancellation),
        ("model_http_error_retry_metadata", _offline_model_http_error),
    ]


def _live_checks(model: Any) -> list[tuple[str, Callable[[], Any]]]:
    return [
        ("live_openrouter_function_tool", lambda: _live_function_tool(model)),
        ("live_openrouter_structured_output", lambda: _live_structured_output(model)),
        ("live_openrouter_mcp", lambda: _live_mcp(model)),
        ("live_openrouter_stream_events", lambda: _live_stream_events(model)),
        ("live_openrouter_web_search", lambda: _live_web_search(model)),
        ("live_openrouter_web_fetch", lambda: _live_web_fetch(model)),
        ("live_openrouter_tool_failed", lambda: _live_tool_failed(model)),
        ("live_openrouter_model_retry", lambda: _live_model_retry(model)),
    ]


async def _run_checks(
    checks: list[tuple[str, Callable[[], Any]]],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for name, check in checks:
        try:
            value = check()
            details = await value if inspect.isawaitable(value) else value
            results.append({"name": name, "status": "passed", "details": details})
        except Exception as exc:  # noqa: BLE001 - each smoke must report independently.
            results.append(
                {
                    "name": name,
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": _redact_error(str(exc)),
                }
            )
    return results


def _offline_runtime_versions() -> dict[str, str]:
    versions = _package_versions()
    for package_name in ("pydantic-ai-slim", "pydantic-evals", "pydantic-graph"):
        if versions[package_name] != REQUIRED_VERSION:
            raise AssertionError(
                f"{package_name}={versions[package_name]}, expected {REQUIRED_VERSION}"
            )
    return versions


def _offline_v232_capability_contract() -> dict[str, Any]:
    from pydantic_ai import RunContext
    from pydantic_ai.mcp import MCPToolset
    from pydantic_ai.toolsets._tool_search import ToolSearchToolset

    limits = UsageLimits(request_limit=10, tool_calls_limit=10)
    mcp_parameters = inspect.signature(MCPToolset).parameters
    tool_search_parameters = inspect.signature(ToolSearchToolset).parameters
    to_web_parameters = inspect.signature(Agent.to_web).parameters
    _require(
        limits.per_request_input_tokens_limit is None,
        "per-request input token limit must remain disabled",
    )
    _require(
        hasattr(RunContext, "is_tool_available"),
        "RunContext.is_tool_available is unavailable",
    )
    _require("prefer_tasks" in mcp_parameters, "MCP prefer_tasks is unavailable")
    _require(
        "max_retries" in tool_search_parameters,
        "ToolSearchToolset max_retries is unavailable",
    )
    _require(
        "allowed_hosts" in to_web_parameters,
        "Agent.to_web allowed_hosts is unavailable",
    )
    return {
        "per_request_input_tokens_limit": None,
        "run_context_tool_availability": True,
        "mcp_prefer_tasks_default": mcp_parameters["prefer_tasks"].default,
        "tool_search_max_retries": True,
        "agent_web_allowed_hosts": True,
    }


def _offline_openrouter_annotations() -> dict[str, Any]:
    from pydantic_ai.models.openrouter import (
        OpenRouterModel,
        OpenRouterProvider,
        _OpenRouterChatCompletion,
    )

    source_url = "https://example.com/scout-weather"
    response = _OpenRouterChatCompletion.model_validate(
        {
            "id": "scout-openrouter-annotation-smoke",
            "choices": [
                {
                    "finish_reason": "stop",
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "rain",
                        "annotations": [
                            {
                                "type": "url_citation",
                                "url_citation": {
                                    "url": source_url,
                                    "title": "Scout weather fixture",
                                    "content": "rain",
                                    "start_index": 0,
                                    "end_index": 4,
                                },
                            }
                        ],
                    },
                }
            ],
            "created": 0,
            "model": "openai/gpt-4o-mini",
            "object": "chat.completion",
            "provider": "fixture-provider",
        }
    )
    model = OpenRouterModel(
        "openai/gpt-4o-mini",
        provider=OpenRouterProvider(api_key="-".join(("fixture", "value"))),
    )
    mapped = model._process_response(response)
    provider_details = mapped.provider_details or {}
    annotations = provider_details.get("annotations") or []

    _require(len(annotations) == 1, "OpenRouter citation annotation was dropped")
    citation = annotations[0].get("url_citation") or {}
    _require(citation.get("url") == source_url, "OpenRouter citation URL changed")
    return {
        "annotation_count": len(annotations),
        "annotation_type": annotations[0].get("type"),
        "source_url": citation.get("url"),
    }


def _offline_instrumentation_v6_tool_role() -> dict[str, Any]:
    from pydantic_ai.models.instrumented import (
        InstrumentationSettings,
        _otel_message_role,
    )

    tool_return = ToolReturnPart(
        tool_name="scout_weather_fixture",
        content={"rain_mm": 12},
        tool_call_id="scout-tool-call-1",
    )
    settings = InstrumentationSettings(version=6)
    role = _otel_message_role(tool_return, settings.version)

    _require(role == "tool", "instrumentation v6 did not emit the tool role")
    _require(
        _otel_message_role(tool_return, 5) == "user",
        "instrumentation v5 compatibility role changed unexpectedly",
    )
    return {
        "instrumentation_version": settings.version,
        "tool_return_role": role,
        "legacy_tool_return_role": "user",
    }


async def _offline_stream_events_and_compaction() -> dict[str, Any]:
    agent = Agent(TestModel(), **pydantic_agent_runtime_kwargs())
    event_types: list[str] = []
    async with agent.run_stream_events("Return the stream smoke result.") as events:
        async for event in events:
            event_types.append(type(event).__name__)

    messages = [ModelResponse(parts=[CompactionPart(content="bounded Scout context")])]
    encoded = ModelMessagesTypeAdapter.dump_json(messages)
    decoded = ModelMessagesTypeAdapter.validate_json(encoded)
    compacted = decoded[0].parts[0]

    _require("FinalResultEvent" in event_types, "stream omitted final result event")
    _require("AgentRunResultEvent" in event_types, "stream omitted run result event")
    _require(
        isinstance(compacted, CompactionPart), "compaction part did not round-trip"
    )
    _require(
        compacted.content == "bounded Scout context",
        "compaction content changed during serialization",
    )
    return {
        "event_types": event_types,
        "compaction_round_trip": True,
    }


def _offline_agent_web_content_type_guard() -> dict[str, Any]:
    from starlette.testclient import TestClient

    client = TestClient(
        Agent(TestModel()).to_web(allowed_hosts=["testserver"]),
        raise_server_exceptions=False,
    )
    response = client.post(
        "/api/chat",
        content="{}",
        headers={"content-type": "text/plain"},
    )
    _require(response.status_code == 415, "non-JSON chat request was not rejected")
    _require(
        "application/json" in response.text,
        "content-type rejection did not explain the JSON requirement",
    )
    return {
        "status_code": response.status_code,
        "model_request_prevented": True,
    }


def _offline_agent_web_host_guard() -> dict[str, Any]:
    from starlette.testclient import TestClient

    client = TestClient(Agent(TestModel()).to_web(), raise_server_exceptions=False)
    response = client.post(
        "/api/chat",
        json={"messages": []},
        headers={"host": "attacker.invalid"},
    )
    _require(
        response.status_code in {400, 403, 421},
        "untrusted Host header was not rejected",
    )
    return {
        "status_code": response.status_code,
        "untrusted_host_rejected": True,
        "model_request_prevented": True,
    }


async def _offline_function_tool_call() -> dict[str, Any]:
    def read_marker() -> str:
        """Read a deterministic Scout marker."""

        return "CP-07"

    def model_function(messages: list[object], info: AgentInfo) -> ModelResponse:
        if _has_part(messages, ToolReturnPart):
            return ModelResponse(parts=[TextPart("CP-07")])
        return ModelResponse(parts=[ToolCallPart(info.function_tools[0].name, {})])

    agent = Agent(
        FunctionModel(model_function),
        tools=[read_marker],
        **pydantic_agent_runtime_kwargs(),
    )
    result = await agent.run("Read the marker.")
    trace = _message_trace(result)
    _require(result.output == "CP-07", "function tool output mismatch")
    _require(trace["tool_call_count"] == 1, "function tool was not called once")
    return trace


async def _offline_blocking_sync_tool_timeout() -> dict[str, Any]:
    from threading import Event
    from time import monotonic

    release = Event()
    calls = 0

    def blocking_tool() -> str:
        """Wait for a release signal longer than the configured tool timeout."""

        nonlocal calls
        calls += 1
        release.wait(timeout=1)
        return "unexpected"

    def model_function(messages: list[object], info: AgentInfo) -> ModelResponse:
        del info
        if _has_part(messages, RetryPromptPart):
            return ModelResponse(parts=[TextPart("timeout observed")])
        return ModelResponse(parts=[ToolCallPart("blocking_tool", {})])

    agent = Agent(
        FunctionModel(model_function),
        tools=[Tool(blocking_tool, timeout=0.05)],
        **pydantic_agent_runtime_kwargs(),
    )
    started_at = monotonic()
    try:
        result = await agent.run("Exercise the blocking sync tool timeout.")
    finally:
        release.set()
    elapsed_seconds = monotonic() - started_at
    trace = _message_trace(result)

    _require(calls == 1, "blocking sync tool was called more than once")
    _require(trace["retry_prompt_count"] == 1, "sync timeout did not reach the model")
    _require(result.output == "timeout observed", "sync timeout recovery output mismatch")
    _require(elapsed_seconds < 0.5, "blocking sync tool ignored its timeout")
    return {
        **trace,
        "elapsed_seconds": round(elapsed_seconds, 4),
        "timeout_seconds": 0.05,
    }


async def _offline_nested_sync_agent_run_rejected() -> dict[str, Any]:
    nested_agent = Agent(TestModel())

    def call_nested_agent() -> str:
        """Exercise the unsupported nested synchronous delegation path."""

        return str(nested_agent.run_sync("Return nested output.").output)

    def model_function(messages: list[object], info: AgentInfo) -> ModelResponse:
        del messages
        return ModelResponse(
            parts=[ToolCallPart(info.function_tools[0].name, {})],
        )

    outer_agent = Agent(
        FunctionModel(model_function),
        tools=[call_nested_agent],
        **pydantic_agent_runtime_kwargs(),
    )
    try:
        await outer_agent.run("Exercise nested synchronous delegation.")
    except UserError as exc:
        message = str(exc)
        _require(
            "cannot be used inside a synchronous tool" in message,
            "nested sync rejection did not include migration guidance",
        )
        return {
            "error_type": type(exc).__name__,
            "async_delegation_required": True,
        }
    raise AssertionError("nested synchronous agent run was not rejected")


async def _offline_structured_output() -> dict[str, Any]:
    agent = Agent(
        TestModel(custom_output_args={"status": "ok", "evidence_count": 2}),
        output_type=StructuredSmokeOutput,
        **pydantic_agent_runtime_kwargs(),
    )
    result = await agent.run("Return the typed smoke result.")
    _require(result.output.status == "ok", "structured status mismatch")
    _require(result.output.evidence_count == 2, "structured evidence count mismatch")
    return result.output.model_dump(mode="json")


async def _offline_mcp_instructions() -> dict[str, Any]:
    from mcp.server.fastmcp import FastMCP
    from pydantic_ai.mcp import MCPToolset

    marker = "SCOUT_MCP_SMOKE_INSTRUCTION"
    server = FastMCP("scout-compat-smoke", instructions=f"{marker}: call route_marker.")

    @server.tool()
    def route_marker() -> str:
        """Return the fixture route marker."""

        return "CP-07"

    captured_instructions: list[str | None] = []

    def model_function(messages: list[object], info: AgentInfo) -> ModelResponse:
        del info
        captured_instructions.extend(
            getattr(message, "instructions", None) for message in messages
        )
        if _has_part(messages, ToolReturnPart):
            return ModelResponse(parts=[TextPart("CP-07")])
        return ModelResponse(parts=[ToolCallPart("route_marker", {})])

    agent = Agent(
        FunctionModel(model_function),
        toolsets=[MCPToolset(server, include_instructions=True)],
        **pydantic_agent_runtime_kwargs(),
    )
    result = await agent.run("Use the MCP route marker.")
    trace = _message_trace(result)
    _require(
        any(marker in (item or "") for item in captured_instructions),
        "MCP instructions were not added to the model request",
    )
    _require(trace["tool_call_count"] == 1, "MCP tool was not called once")
    return {**trace, "instructions_present": True}


def _offline_web_capabilities() -> dict[str, Any]:
    policy = resolve_model_policy(
        "openrouter:deepseek/deepseek-v3.2",
        env={"SCOUT_AI_OS_NATIVE_RESEARCH": "1"},
    )
    search, fetch = pydantic_native_research_capabilities(policy)
    from pydantic_ai.models.openrouter import OpenRouterModel

    native_tools = OpenRouterModel.supported_native_tools()
    _require(search.native is False, "OpenRouter search must use local evidence")
    _require(search.local is not None, "WebSearch local fallback is missing")
    _require(fetch.native is False, "OpenRouter fetch must use local evidence")
    _require(fetch.local is not None, "WebFetch local fallback is missing")
    _require(WebSearchTool in native_tools, "OpenRouter WebSearch support is missing")
    _require(AdvisorTool in native_tools, "OpenRouter AdvisorTool support is missing")
    return {
        "search_mode": "local",
        "search_max_uses": policy.native_research_max_searches,
        "fetch_mode": "local",
        "fetch_max_uses": policy.native_research_max_fetches,
        "fetch_unbounded_content": fetch.max_content_tokens is None,
        "openrouter_native_tools": sorted(item.__name__ for item in native_tools),
    }


async def _offline_tool_failed() -> dict[str, Any]:
    calls = 0

    def unavailable_tool() -> str:
        nonlocal calls
        calls += 1
        raise ToolFailed("candidate evidence unavailable")

    def model_function(messages: list[object], info: AgentInfo) -> ModelResponse:
        del info
        if _has_part(messages, ToolReturnPart):
            return ModelResponse(parts=[TextPart("failure observed")])
        return ModelResponse(parts=[ToolCallPart("unavailable_tool", {})])

    agent = Agent(
        FunctionModel(model_function),
        tools=[unavailable_tool],
        **pydantic_agent_runtime_kwargs(),
    )
    result = await agent.run("Call the unavailable tool once.")
    trace = _message_trace(result)
    _require(calls == 1, "ToolFailed unexpectedly retried the tool")
    _require(trace["retry_prompt_count"] == 0, "ToolFailed became ModelRetry")
    _require(
        "candidate evidence unavailable" in trace["tool_return_contents"],
        "failure was hidden",
    )
    return trace


async def _offline_model_retry() -> dict[str, Any]:
    calls = 0

    def transient_tool() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ModelRetry("temporary evidence read failure")
        return "ready"

    def model_function(messages: list[object], info: AgentInfo) -> ModelResponse:
        del info
        if any(
            isinstance(part, ToolReturnPart) and part.content == "ready"
            for message in messages
            for part in getattr(message, "parts", ())
        ):
            return ModelResponse(parts=[TextPart("ready")])
        return ModelResponse(parts=[ToolCallPart("transient_tool", {})])

    agent = Agent(
        FunctionModel(model_function),
        tools=[transient_tool],
        **pydantic_agent_runtime_kwargs(),
    )
    result = await agent.run("Retry the transient tool.")
    trace = _message_trace(result)
    _require(calls == 2, "transient tool did not recover on the second call")
    _require(trace["retry_prompt_count"] == 1, "retry prompt count mismatch")
    return trace


async def _offline_cancellation() -> dict[str, Any]:
    started = asyncio.Event()

    async def slow_model(
        messages: list[object],
        info: AgentInfo,
    ) -> ModelResponse:
        del messages, info
        started.set()
        await asyncio.sleep(30)
        return ModelResponse(parts=[TextPart("unexpected")])

    agent = Agent(FunctionModel(slow_model), **pydantic_agent_runtime_kwargs())
    task = asyncio.create_task(agent.run("Wait until cancelled."))
    await asyncio.wait_for(started.wait(), timeout=2)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return {"cancelled_error_propagated": True}
    raise AssertionError("external cancellation was swallowed")


def _offline_model_http_error() -> dict[str, Any]:
    error = ModelHTTPError(
        status_code=429,
        model_name="smoke-model",
        body="rate limited",
        headers={"retry-after": "2"},
    )
    _require(error.retry_after == 2.0, "retry_after was not parsed")
    return {
        "status_code": error.status_code,
        "retry_after": error.retry_after,
        "headers_present": bool(error.headers),
    }


async def _live_function_tool(model: Any) -> dict[str, Any]:
    def scout_runtime_version() -> str:
        """Return the installed Scout Pydantic AI version."""

        return REQUIRED_VERSION

    agent = Agent(
        model,
        instructions=(
            "Call scout_runtime_version exactly once before answering. "
            "Return only the version from the tool."
        ),
        tools=[scout_runtime_version],
        **pydantic_agent_runtime_kwargs(),
    )
    result = await _live_run(agent, "What Scout Pydantic AI version is installed?")
    trace = _message_trace(result)
    _require("scout_runtime_version" in trace["tool_names"], "live tool was not called")
    _require(REQUIRED_VERSION in str(result.output), "live tool result was not used")
    return {**trace, "output": str(result.output)}


async def _live_structured_output(model: Any) -> dict[str, Any]:
    agent = Agent(
        model,
        output_type=LiveStructuredSmokeOutput,
        instructions=(
            f"Return status='ok' and runtime_version='{REQUIRED_VERSION}' "
            "using the required structured output."
        ),
        **pydantic_agent_runtime_kwargs(),
    )
    result = await _live_run(agent, "Produce the compatibility result.")
    _require(result.output.status == "ok", "live structured status mismatch")
    _require(
        result.output.runtime_version == REQUIRED_VERSION,
        "live structured version mismatch",
    )
    return result.output.model_dump(mode="json")


async def _live_mcp(model: Any) -> dict[str, Any]:
    from mcp.server.fastmcp import FastMCP
    from pydantic_ai.mcp import MCPToolset

    marker = "SCOUT_LIVE_MCP_INSTRUCTION"
    server = FastMCP("scout-live-smoke", instructions=f"{marker}: call route_marker.")

    @server.tool()
    def route_marker() -> str:
        """Return the live smoke route marker."""

        return "MCP-CP-07"

    agent = Agent(
        model,
        instructions="Follow the MCP server instructions before answering.",
        toolsets=[MCPToolset(server, include_instructions=True)],
        **pydantic_agent_runtime_kwargs(),
    )
    result = await _live_run(agent, "Which route marker does the MCP server expose?")
    trace = _message_trace(result)
    instructions = [
        getattr(message, "instructions", None) for message in result.all_messages()
    ]
    _require(
        any(marker in (item or "") for item in instructions),
        "live MCP instructions were not attached",
    )
    _require("route_marker" in trace["tool_names"], "live MCP tool was not called")
    return {**trace, "output": str(result.output), "instructions_present": True}


async def _live_stream_events(model: Any) -> dict[str, Any]:
    agent = Agent(
        model,
        instructions="Return exactly STREAM-OK.",
        **pydantic_agent_runtime_kwargs(),
    )
    event_types: list[str] = []
    async with agent.run_stream_events(
        "Produce the streaming compatibility marker.",
        usage_limits=UsageLimits(request_limit=10, tool_calls_limit=10),
        model_settings={
            "temperature": 0,
            "timeout": DEFAULT_TIMEOUT_SECONDS,
        },
    ) as events:
        async for event in events:
            event_types.append(type(event).__name__)

    _require("PartDeltaEvent" in event_types, "live stream omitted content deltas")
    _require(
        "FinalResultEvent" in event_types, "live stream omitted final result event"
    )
    _require(
        "AgentRunResultEvent" in event_types, "live stream omitted run result event"
    )
    return {"event_types": event_types}


async def _live_web_search(model: Any) -> dict[str, Any]:
    search = WebSearch(
        native=False,
        local=build_local_web_search(
            allowed_domains=["pydantic.dev"],
            max_uses=10,
        ),
    )
    agent = Agent(
        model,
        instructions=(
            "Call scout_web_search exactly once to find the official Pydantic AI "
            "changelog. Return one result title and its pydantic.dev URL."
        ),
        capabilities=[search],
        **pydantic_agent_runtime_kwargs(),
    )
    result = await _live_run(agent, "Search the web now for the Pydantic AI changelog.")
    trace = _message_trace(result)
    output = str(result.output)
    _require(
        "scout_web_search" in trace["tool_names"], "local WebSearch was not called"
    )
    _require("pydantic" in output.lower(), "web search output lacks Pydantic result")
    return {**trace, "output": output}


async def _live_web_fetch(model: Any) -> dict[str, Any]:
    fetch = WebFetch(
        native=False,
        local=build_local_web_fetch(
            allowed_domains=["pydantic.dev"],
            max_uses=10,
        ),
        allowed_domains=["pydantic.dev"],
        max_content_tokens=None,
    )
    agent = Agent(
        model,
        instructions=(
            "Call scout_web_fetch exactly once with the exact URL, then return "
            "the page title only."
        ),
        capabilities=[fetch],
        **pydantic_agent_runtime_kwargs(),
    )
    result = await _live_run(
        agent,
        "Fetch https://pydantic.dev/docs/ai/project/changelog/ now.",
    )
    trace = _message_trace(result)
    _require("scout_web_fetch" in trace["tool_names"], "local WebFetch was not called")
    _require(
        "pydantic" in str(result.output).lower(), "WebFetch output lacks page title"
    )
    return {**trace, "output": str(result.output)}


async def _live_tool_failed(model: Any) -> dict[str, Any]:
    calls = 0

    def unavailable_candidate() -> str:
        """Return a candidate that is deliberately unavailable for this smoke."""

        nonlocal calls
        calls += 1
        raise ToolFailed("candidate evidence unavailable")

    agent = Agent(
        model,
        instructions=(
            "Call unavailable_candidate exactly once. Explain that its failure "
            "was visible and do not invent a value."
        ),
        tools=[unavailable_candidate],
        **pydantic_agent_runtime_kwargs(),
    )
    result = await _live_run(agent, "Inspect the unavailable candidate.")
    trace = _message_trace(result)
    _require(calls == 1, "live ToolFailed caused an unexpected tool retry")
    _require(trace["retry_prompt_count"] == 0, "live ToolFailed became ModelRetry")
    return {**trace, "output": str(result.output)}


async def _live_model_retry(model: Any) -> dict[str, Any]:
    calls = 0

    def transient_candidate() -> str:
        """Return a candidate after one deliberate transient failure."""

        nonlocal calls
        calls += 1
        if calls == 1:
            raise ModelRetry("temporary evidence read failure; call again")
        return "retry-recovered"

    agent = Agent(
        model,
        instructions=(
            "Call transient_candidate. If the tool requests a retry, call it "
            "again, then answer with the recovered value."
        ),
        tools=[transient_candidate],
        **pydantic_agent_runtime_kwargs(),
    )
    result = await _live_run(agent, "Read the transient candidate.")
    trace = _message_trace(result)
    _require(calls == 2, f"live retry used {calls} tool calls instead of 2")
    _require("retry-recovered" in str(result.output), "live retry result was not used")
    return {**trace, "output": str(result.output)}


async def _live_run(agent: Agent[Any, Any], prompt: str) -> Any:
    return await agent.run(
        prompt,
        usage_limits=UsageLimits(request_limit=10, tool_calls_limit=10),
        model_settings={
            "temperature": 0,
            "timeout": DEFAULT_TIMEOUT_SECONDS,
        },
    )


def _message_trace(result: Any) -> dict[str, Any]:
    parts = [
        part
        for message in result.all_messages()
        for part in getattr(message, "parts", ())
    ]
    tool_calls = [
        part for part in parts if isinstance(part, (ToolCallPart, NativeToolCallPart))
    ]
    native_calls = [part for part in parts if isinstance(part, NativeToolCallPart)]
    native_returns = [part for part in parts if isinstance(part, NativeToolReturnPart)]
    tool_returns = [part for part in parts if isinstance(part, ToolReturnPart)]
    retries = [part for part in parts if isinstance(part, RetryPromptPart)]
    return {
        "part_types": [type(part).__name__ for part in parts],
        "tool_names": [str(getattr(part, "tool_name", "")) for part in tool_calls],
        "tool_call_count": len(tool_calls),
        "tool_return_count": len(tool_returns) + len(native_returns),
        "native_tool_call_count": len(native_calls),
        "native_tool_return_count": len(native_returns),
        "retry_prompt_count": len(retries),
        "tool_return_contents": _bounded_text(
            " | ".join(str(part.content) for part in tool_returns),
        ),
    }


def _has_part(messages: list[object], part_type: type[Any]) -> bool:
    return any(
        isinstance(part, part_type)
        for message in messages
        for part in getattr(message, "parts", ())
    )


def _bounded_text(value: str, *, max_characters: int = 2_000) -> str:
    if len(value) <= max_characters:
        return value
    return f"{value[:max_characters]}...[truncated {len(value) - max_characters} chars]"


def _package_versions() -> dict[str, str]:
    result: dict[str, str] = {}
    for name in ("pydantic-ai-slim", "pydantic-evals", "pydantic-graph"):
        try:
            result[name] = version(name)
        except PackageNotFoundError:
            result[name] = "not-installed"
    return result


def _normalize_openrouter_model(model_name: str) -> str:
    value = model_name.strip()
    if value.startswith("openrouter:"):
        return value
    if value.startswith(("nvidia:", "openai:", "openai-chat:", "hailo:")):
        value = value.split(":", 1)[1]
    return f"openrouter:{value}"


def _load_env_file(path: Path) -> bool:
    if not path.exists():
        return False
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            os.environ.setdefault(key, value.strip().strip('"').strip("'"))
    return True


def _redact_error(message: str) -> str:
    redacted = message
    for key in ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "NVIDIA_API_KEY"):
        secret = os.getenv(key)
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    redacted = re.sub(
        r"(?i)(authorization\s*[:=]\s*(?:bearer\s+)?)[^\s,;]+",
        r"\1[REDACTED]",
        redacted,
    )
    return redacted[:2_000]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


__all__ = [
    "DEFAULT_OPENROUTER_MODEL",
    "REQUIRED_VERSION",
    "main",
    "run_compatibility_smoke",
]


if __name__ == "__main__":
    raise SystemExit(main())
