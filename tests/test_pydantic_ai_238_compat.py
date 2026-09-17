"""Fixture-backed upgrade gates; no provider or workspace network access."""

from __future__ import annotations

import asyncio
import json
from importlib.metadata import version
from uuid import uuid4

import httpx2
import pytest
from openai import AsyncOpenAI
from packaging.version import Version
from pydantic_ai import Agent, CancellationToken, UsageLimits, capture_run_messages
from pydantic_ai.capabilities import WebFetch, WebSearch
from pydantic_ai.exceptions import ModelAPIError, RunCancelled
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers.deepseek import DeepSeekProvider
from pydantic_ai.providers.openai import OpenAIProvider

from scout.agents.model_policy import resolve_model_policy
from scout.agents.pydantic_ai_compat import pydantic_native_research_capabilities

pytestmark = pytest.mark.skipif(
    Version(version("pydantic-ai-slim")) < Version("2.38.0"),
    reason="Upgrade-candidate contracts require Pydantic AI 2.38 or newer",
)


def test_one_off_merge_preserves_collections_and_later_scalar() -> None:
    first = WebSearch(allowed_domains=["pydantic.dev"], max_uses=10)
    second = WebSearch(allowed_domains=["github.com", "pydantic.dev"], max_uses=20)

    merged = WebSearch.combine([first, second])

    assert merged.id == "web_search"
    assert merged.allowed_domains == ["pydantic.dev", "github.com"]
    assert merged.max_uses == 20
    assert first.max_uses == 10


def _returned_tools(result) -> list[str]:
    return [
        part.tool_name
        for message in result.all_messages()
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]


def test_duplicate_search_keeps_later_local_fallback_and_fetch() -> None:
    def first_search(query: str) -> str:
        return "old search"

    def second_search(query: str) -> str:
        return "new search"

    def fetch_source(url: str) -> str:
        return "source evidence"

    agent = Agent(
        TestModel(),
        capabilities=[
            WebSearch(native=False, local=first_search),
            WebSearch(native=False, local=second_search),
            WebFetch(native=False, local=fetch_source),
        ],
    )
    result = agent.run_sync(
        "Inspect evidence",
        usage_limits=UsageLimits(request_limit=10, tool_calls_limit=10),
    )

    assert set(_returned_tools(result)) == {"second_search", "fetch_source"}


def test_run_level_search_override_keeps_unrelated_agent_fetch() -> None:
    def agent_search(query: str) -> str:
        return "agent source"

    def run_search(query: str) -> str:
        return "run source"

    def fetch_source(url: str) -> str:
        return "fetched source"

    agent = Agent(
        TestModel(),
        capabilities=[
            WebSearch(native=False, local=agent_search),
            WebFetch(native=False, local=fetch_source),
        ],
    )
    result = agent.run_sync(
        "Inspect evidence", capabilities=[WebSearch(native=False, local=run_search)]
    )

    assert set(_returned_tools(result)) == {"run_search", "fetch_source"}


def test_explicit_distinct_ids_preserve_separate_search_tools() -> None:
    def route_search(query: str) -> str:
        return "route source"

    def weather_search(query: str) -> str:
        return "weather source"

    agent = Agent(
        TestModel(),
        capabilities=[
            WebSearch(id="route", native=False, local=route_search),
            WebSearch(id="weather", native=False, local=weather_search),
        ],
    )

    result = agent.run_sync("Inspect both sources")

    assert set(_returned_tools(result)) == {"route_search", "weather_search"}


def test_scout_capability_builder_retains_both_traced_fallbacks() -> None:
    policy = resolve_model_policy("openrouter:deepseek/deepseek-v4-flash-0731", env={})
    search, fetch = pydantic_native_research_capabilities(policy)

    assert (search.id, fetch.id) == ("web_search", "web_fetch")
    assert search.native is False and search.local is not None
    assert fetch.native is False and fetch.local is not None
    assert fetch.max_content_tokens is None
    assert policy.native_research_max_searches >= 10
    assert policy.native_research_max_fetches >= 10


@pytest.mark.parametrize(
    "strict,finish_reason", [(False, None), (True, None), (True, "stop")]
)
def test_missing_stream_finish_reason_is_opt_in_and_preserves_partial(
    strict, finish_reason
) -> None:
    async def run_case():
        def respond(request: httpx2.Request) -> httpx2.Response:
            assert json.loads(request.content)["stream"] is True
            chunk = {
                "id": "fixture-stream",
                "created": 0,
                "model": "fixture-model",
                "object": "chat.completion.chunk",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": finish_reason,
                        "delta": {
                            "role": "assistant",
                            "content": "partial Scout evidence",
                        },
                    }
                ],
            }
            return httpx2.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n",
            )

        async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as http:
            async with AsyncOpenAI(
                base_url="https://fixture.invalid/v1",
                api_key=uuid4().hex,
                http_client=http,
            ) as client:
                model = OpenAIChatModel(
                    "fixture-model",
                    provider=OpenAIProvider(openai_client=client),
                    profile=OpenAIModelProfile(
                        openai_chat_streaming_requires_finish_reason=strict
                    ),
                )
                with capture_run_messages() as messages:
                    try:
                        async with Agent(model).run_stream("Read evidence") as run:
                            await run.get_output()
                    except ModelAPIError as exc:
                        assert strict and finish_reason is None
                        assert "finish_reason" in str(exc)
                    else:
                        assert not strict or finish_reason == "stop"
                responses = [m for m in messages if isinstance(m, ModelResponse)]
                assert responses
                assert "partial Scout evidence" in "".join(
                    p.content for p in responses[-1].parts if isinstance(p, TextPart)
                )
                if strict and finish_reason is None:
                    # Agent history records a provider stream failure as interrupted.
                    assert responses[-1].state == "interrupted"

    asyncio.run(run_case())


def test_cancel_during_first_tool_call_keeps_resumable_history() -> None:
    async def run_case():
        entered = asyncio.Event()

        async def read_evidence() -> str:
            entered.set()
            await asyncio.Event().wait()
            return "unreachable"

        def model_function(messages, info):
            if any(
                isinstance(part, ToolReturnPart)
                for message in messages
                for part in message.parts
            ):
                return ModelResponse(
                    parts=[TextPart("interrupted evidence remains unknown")]
                )
            return ModelResponse(
                parts=[ToolCallPart("read_evidence", {}, tool_call_id="first-read")]
            )

        agent = Agent(FunctionModel(model_function), tools=[read_evidence])
        token = CancellationToken()
        task = asyncio.create_task(agent.run("Read", cancellation_token=token))
        try:
            await asyncio.wait_for(entered.wait(), timeout=10)
            token.cancel()
            with pytest.raises(RunCancelled) as cancelled:
                await asyncio.wait_for(task, timeout=10)
            history = cancelled.value.all_messages()
            assert any(isinstance(p, ToolCallPart) for m in history for p in m.parts)
            result = await agent.run(message_history=history)
            assert result.output == "interrupted evidence remains unknown"
            assert any(
                isinstance(p, ToolReturnPart) and p.outcome == "interrupted"
                for m in result.all_messages()
                for p in m.parts
            )
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run_case())


def test_deepseek_direct_profile_scopes_forced_tools_to_non_thinking() -> None:
    profile = DeepSeekProvider.model_profile("deepseek-v4-flash")

    assert profile["openai_supports_tool_choice_required"] is True
    assert profile["openai_supports_forced_tool_choice_with_thinking"] is False
    assert profile["openai_responses_supports_json_schema_output"] is True
