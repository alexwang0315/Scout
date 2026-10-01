"""Fixture-backed 2.52 WebFetch security and decision-retry contracts."""

from __future__ import annotations

import asyncio
import hashlib
from email.message import Message
from importlib.metadata import version

import httpx2
import pytest
from packaging.version import Version
from pydantic_ai import Agent, UsageLimits
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import FunctionModel

from scout.agents.model_policy import resolve_model_policy
from scout.agents.pydantic_ai_compat import pydantic_native_research_capabilities

pytestmark = pytest.mark.skipif(
    Version(version("pydantic-ai-slim")) < Version("2.52.0"),
    reason="Run with the Pydantic AI 2.52 security-patched candidate",
)


def test_default_web_fetch_retains_normal_page_content(monkeypatch):
    from pydantic_ai.common_tools import web_fetch

    async def download(url, **kwargs):
        assert url == "https://fixture.example/route"
        assert kwargs["allow_local"] is False
        return httpx2.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text='<title>Route source</title><h1>Trail</h1><a href="/cp">CP</a>',
        )

    monkeypatch.setattr(web_fetch, "safe_download", download)
    fetch = web_fetch.WebFetchLocalTool(
        max_content_length=None, allow_local_urls=False, timeout=30
    )
    result = asyncio.run(fetch("https://fixture.example/route"))

    assert result["title"] == "Route source"
    assert "Trail" in result["content"]
    assert "[CP](/cp)" in result["content"]


def test_default_web_fetch_rejects_expensive_html_as_retry(monkeypatch):
    from pydantic_ai.common_tools import web_fetch

    payload = "<dd>" * 30 + "x<br>" * 10_000 + "</dd>" * 30

    async def download(url, **kwargs):
        return httpx2.Response(
            200, headers={"content-type": "text/html"}, text=payload
        )

    monkeypatch.setattr(web_fetch, "safe_download", download)
    fetch = web_fetch.WebFetchLocalTool(
        max_content_length=None, allow_local_urls=False, timeout=30
    )
    with pytest.raises(ModelRetry, match="document is too complex"):
        asyncio.run(fetch("https://fixture.example/nested"))


def test_scout_custom_fetch_bypasses_default_converter_and_keeps_provenance(
    monkeypatch,
):
    from pydantic_ai.common_tools import web_fetch

    payload = b"<div>" * 1_000 + b"fixture route" + b"</div>" * 1_000
    headers = Message()
    headers["Content-Type"] = "text/html; charset=utf-8"

    class Response:
        status = 200

        def __init__(self):
            self.headers = headers

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def geturl(self):
            return "https://fixture.example/route"

        def read(self):
            return payload

    def unexpected_conversion(*args):
        raise AssertionError("Scout must use its configured fetch callable")

    monkeypatch.setattr(web_fetch, "_convert_html", unexpected_conversion)
    monkeypatch.setattr(
        "scout.agents.local_web_fetch._open_url", lambda *args, **kwargs: Response()
    )
    monkeypatch.setattr(
        "scout.agents.local_web_fetch._require_public_dns_resolution",
        lambda *args: None,
    )
    returns = []

    async def model(messages, info):
        tool_results = [
            part
            for message in messages
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        ]
        if not tool_results:
            assert "scout_web_fetch" in {tool.name for tool in info.function_tools}
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "scout_web_fetch", {"url": "https://fixture.example/route"}
                    )
                ]
            )
        returns.extend(tool_results)
        return ModelResponse(parts=[TextPart("fixture route received")])

    async def run():
        policy = resolve_model_policy(
            "openrouter:deepseek/deepseek-v4-flash-0731", env={}
        )
        agent = Agent(
            FunctionModel(model),
            capabilities=pydantic_native_research_capabilities(policy),
        )
        return await agent.run(
            "Fetch the route source",
            usage_limits=UsageLimits(request_limit=10, tool_calls_limit=10),
        )

    result = asyncio.run(run())
    assert result.output == "fixture route received"
    assert len(returns) == 1
    card = returns[0].content
    assert card["content"] == payload.decode()
    assert card["content_hash"] == "sha256:" + hashlib.sha256(payload).hexdigest()
    assert card["url"] == "https://fixture.example/route"
    assert card["truncated"] is False
    assert card["candidate_only"] is True
    assert card["runtime_safety_truth"] is False


def test_decision_retry_keeps_original_question_under_judgement():
    from pydantic_ai.models.decision import _map_messages

    question = "How many route checkpoints does the workspace contain?"
    state = _map_messages(
        [
            ModelRequest(parts=[UserPromptPart(question)]),
            ModelResponse(parts=[TextPart("invalid candidate")]),
            ModelRequest(parts=[RetryPromptPart("Return a verified source")]),
        ],
        turn=True,
    )

    assert state["text"] == question
    assert state["done"][0] == {"assistant": "invalid candidate"}
    assert "Return a verified source" in state["done"][1]["retry"]
