"""Isolated SDK qualification, not live provider or answer-quality evidence."""

from __future__ import annotations

import asyncio
import importlib
import json
import math
import os
import socket
import sys
from importlib.metadata import version
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx2
import pytest
from openai import AuthenticationError, InternalServerError
from packaging.version import Version

pytestmark = pytest.mark.skipif(
    Version(version("praisonaiagents")) < Version("1.7.17")
    and os.getenv("SCOUT_RUN_CANDIDATE_BASELINE") != "1",
    reason="Requires an explicitly selected Praison 1.7.17 candidate",
)


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for key, value in {
        "HOME": str(tmp_path), "PRAISONAI_HOME": str(tmp_path / ".praisonai"),
        "OPENAI_API_KEY": "fixture-only", "OPENROUTER_API_KEY": "fixture-only",
        "OPENAI_BASE_URL": "http://127.0.0.1:9/v1",
        "PRAISONAI_TELEMETRY_DISABLED": "true", "DO_NOT_TRACK": "1",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("ALLOW_LOCAL_CRAWL", raising=False)

    def no_network(*args, **kwargs):
        pytest.fail("Fixture attempted an unmocked network connection")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket.socket, "connect_ex", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)


@pytest.mark.parametrize("async_mode", [False, True])
def test_team_reexecutes_fresh_question_without_previous_context(monkeypatch, async_mode):
    from praisonaiagents import Agent, AgentTeam, Task

    agent = Agent(name="fresh-fixture", model="scout-deterministic-replay")
    calls = []

    def answer(prompt, **kwargs):
        calls.append(prompt)
        return f"fixture-answer-{len(calls)}"

    async def async_answer(prompt, **kwargs):
        return answer(prompt, **kwargs)

    monkeypatch.setattr(agent, "chat", answer)
    monkeypatch.setattr(agent, "achat", async_answer)
    task = Task(name="read", action="Read current input", agent=agent,
                expected_output="fixture text", variables={"operator": "retained"})
    team = AgentTeam(agents=[agent], tasks=[task], process="sequential")
    try:
        if async_mode:
            async def run():
                await team.astart("question-A")
                assert task.result.raw == "fixture-answer-1"
                await team.astart("question-B")
            asyncio.run(run())
        else:
            team.start("question-A")
            assert task.result.raw == "fixture-answer-1"
            team.start("question-B")
        assert len(calls) == 2
        assert task.result.raw == "fixture-answer-2"
        assert "question-A" not in calls[1]
        assert "question-B" in calls[1]
        assert task.variables["operator"] == "retained"
    finally:
        agent.close()


def _provider_error(status):
    response = httpx2.Response(status, request=httpx2.Request(
        "POST", "https://openrouter.ai/api/v1/chat/completions"))
    cls = AuthenticationError if status == 401 else InternalServerError
    return cls("fixture provider error", response=response, body={"error": "fixture"})


@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("status", [503, 401])
def test_custom_fallback_classifies_error_and_preserves_primary(monkeypatch, async_mode, status):
    from praisonaiagents import Agent

    agent = Agent(name="fallback-fixture", model="scout-deterministic-replay")
    calls, events = [], []
    error = _provider_error(status)

    class Client:
        def __init__(self, primary):
            self.primary = primary

        def get_response(self, **kwargs):
            calls.append("primary" if self.primary else "fallback")
            if self.primary:
                raise error
            return '{"source_ref":"fixture.json#/7","candidate_only":true}'

        async def get_response_async(self, **kwargs):
            return self.get_response(**kwargs)

    primary = Client(True)
    agent.llm = "openrouter/primary-fixture"
    agent.llm_instance = primary
    agent.fallback_models = ["openrouter/fallback-fixture"]
    monkeypatch.setattr(agent, "_fallback_llm_for", lambda model: Client(False))
    monkeypatch.setattr(agent, "_emit_model_fallback", lambda *args: events.append(args))

    async def emit(*args):
        events.append(args)

    monkeypatch.setattr(agent, "_aemit_model_fallback", emit)

    def run():
        if async_mode:
            return asyncio.run(agent._custom_llm_get_response_async({"prompt": "fixture"}))
        return agent._custom_llm_get_response({"prompt": "fixture"})

    try:
        if status == 401:
            with pytest.raises(AuthenticationError):
                run()
            assert calls == ["primary"] and not events
        else:
            assert json.loads(run())["source_ref"] == "fixture.json#/7"
            assert calls == ["primary", "fallback"]
            assert events[0][:2] == ("openrouter/primary-fixture", "openrouter/fallback-fixture")
        assert agent.llm_instance is primary
        assert agent.llm == "openrouter/primary-fixture"
    finally:
        agent.close()


@pytest.mark.parametrize("fallback,same_provider", [
    ("openrouter/secondary", True), ("anthropic/secondary", False),
    ("secondary", True),
])
def test_fallback_connection_settings_do_not_cross_providers(monkeypatch, fallback, same_provider):
    from praisonaiagents import Agent

    module = importlib.import_module("praisonaiagents.llm.llm")
    observed = []
    monkeypatch.setattr(module, "LLM", lambda **kwargs: observed.append(kwargs) or kwargs)
    agent = Agent(name="credential-fixture", model="scout-deterministic-replay")
    primary = "primary" if "/" not in fallback else "openrouter/primary"
    agent._llm_init_params = {
        "model": primary, "base_url": "https://openrouter.ai/api/v1",
        "api_key": "fixture-only", "auth": "fixture-auth", "max_iter": 10,
    }
    try:
        agent._fallback_llm_for(fallback)
        assert observed[0]["model"] == fallback
        assert observed[0]["max_iter"] == 10
        for key in ("base_url", "api_key", "auth"):
            assert (key in observed[0]) is same_provider
        assert agent._llm_init_params["model"] == primary
    finally:
        agent.close()


@pytest.mark.parametrize("async_mode", [False, True])
def test_fallback_never_replays_a_tool_after_it_executed(monkeypatch, async_mode):
    from praisonaiagents import Agent

    agent = Agent(name="no-replay-fixture", model="scout-deterministic-replay")
    error, executions = _provider_error(503), []

    class Client:
        def get_response(self, **kwargs):
            kwargs["execute_tool_fn"]("fixture_read", {})
            raise error

        async def get_response_async(self, **kwargs):
            await kwargs["execute_tool_fn"]("fixture_read", {})
            raise error

    agent.llm_instance = Client()
    agent.fallback_models = ["openrouter/fallback"]
    fallback = MagicMock()
    monkeypatch.setattr(agent, "_fallback_llm_for", fallback)

    def execute(*args, **kwargs):
        executions.append(args)
        return {"source_ref": "fixture.json"}

    async def async_execute(*args, **kwargs):
        return execute(*args, **kwargs)

    try:
        with pytest.raises(InternalServerError):
            if async_mode:
                asyncio.run(agent._custom_llm_get_response_async({"execute_tool_fn": async_execute}))
            else:
                agent._custom_llm_get_response({"execute_tool_fn": execute})
        assert len(executions) == 1
        fallback.assert_not_called()
    finally:
        agent.close()


def test_rag_per_call_overrides_do_not_mutate_shared_configuration(monkeypatch):
    from praisonaiagents.rag import RAG
    from praisonaiagents.rag.models import RAGConfig

    rag = RAG(knowledge=object(), config=RAGConfig(top_k=10, rerank=False))
    observed = []
    monkeypatch.setattr(rag, "_retrieve", lambda **kwargs: observed.append(kwargs) or [])
    monkeypatch.setattr(rag, "_rerank", lambda query, rows, **kwargs: rows)
    first = rag.retrieve("A", top_k=12, rerank=True)
    second = rag.retrieve("B")
    assert [item["top_k"] for item in observed] == [12, 10]
    assert first.metadata["reranked"] is True and second.metadata["reranked"] is False
    assert rag.config.top_k == 10 and rag.config.rerank is False


def test_invalid_retrieval_filter_fails_before_knowledge_access():
    from praisonaiagents.rag.retriever import SmartRetriever

    knowledge = MagicMock()
    with pytest.raises(ValueError, match="Invalid path_filter"):
        SmartRetriever(knowledge=knowledge).retrieve("fixture", path_filter="[")
    knowledge.search.assert_not_called()


@pytest.mark.parametrize("host", ["169.254.169.254", "10.0.0.1", "[::ffff:169.254.169.254]", "0177.0.0.1"])
def test_oauth_blocks_private_numeric_hosts_before_http(monkeypatch, host):
    from praisonaiagents.mcp.oauth_discovery import _get_json

    requests = importlib.import_module("requests")
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 0)),
    ])
    get = MagicMock()
    monkeypatch.setattr(requests, "get", get)
    with pytest.raises(ValueError):
        _get_json(f"https://{host}/metadata")
    get.assert_not_called()


def test_oauth_redirect_is_checked_before_second_http_request(monkeypatch):
    from praisonaiagents.mcp.oauth_discovery import _get_json

    requests = importlib.import_module("requests")
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, *args, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (
            "93.184.216.34" if host == "fixture.example" else "169.254.169.254", 0)),
    ])
    get = MagicMock(return_value=SimpleNamespace(
        status_code=302, headers={"Location": "https://169.254.169.254/token"}))
    monkeypatch.setattr(requests, "get", get)
    with pytest.raises(ValueError):
        _get_json("https://fixture.example/metadata")
    assert get.call_count == 1
    assert get.call_args.kwargs["allow_redirects"] is False


def test_webfetch_urllib_fallback_checks_redirect_before_request(monkeypatch):
    import urllib.error
    import urllib.request

    module = importlib.import_module("praisonaiagents.tools.web_crawl_tools")
    monkeypatch.setitem(sys.modules, "httpx", None)
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, *args, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (
            "93.184.216.34" if host == "fixture.example" else "169.254.169.254", 0)),
    ])
    opener = MagicMock()
    opener.open.side_effect = urllib.error.HTTPError(
        "https://fixture.example/page", 302, "redirect",
        {"Location": "https://169.254.169.254/token"}, None)
    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: opener)
    result = module._crawl_with_httpx(["https://fixture.example/page"])
    assert result[0]["content"] == ""
    assert "SSRF" in result[0]["error"]
    assert opener.open.call_count == 1


def test_unlimited_turn_time_keeps_ten_progressing_tool_calls(monkeypatch):
    from praisonaiagents import Agent
    from praisonaiagents.config import ExecutionConfig

    module = importlib.import_module("praisonaiagents.escalation.loop_guard")
    now = [1000.0]
    monkeypatch.setattr(module.time, "time", lambda: now[0])
    agent = Agent(name="construction-fixture", model="scout-deterministic-replay",
                  execution=ExecutionConfig(max_iter=10, max_execution_time=0))
    try:
        guard = agent._ensure_loop_guard()
        assert math.isinf(guard.config.max_time_per_turn)
        assert agent.max_iter >= 10
        guard.reset_turn()
        for index in range(10):
            now[0] += 10000
            assert not guard.check("read_fixture", {"index": index}).should_block()
            guard.record("read_fixture", {"index": index}, True, {"current": index})
    finally:
        agent.close()


def test_real_flow_trace_has_parent_links_and_redacts_fixture_credentials():
    from praisonaiagents import AgentFlow, ContextListSink, ContextTraceEmitter
    from praisonaiagents.trace.context_events import trace_context

    sink = ContextListSink()
    emitter = ContextTraceEmitter(sink=sink, session_id="scout-1717-fixture", redact=True,
                                  full_content=True)

    def read_fixture(ctx):
        emitter.tool_call_start("fixture-agent", "read_fixture", {
            "api_key": "synthetic-private-marker", "source_ref": "fixture.json#/7",
        })
        emitter.tool_call_end("fixture-agent", "read_fixture", result=json.dumps({
            "source_ref": "fixture.json#/7", "value": 7, "candidate_only": True,
        }))
        return "fixture.json#/7"

    with trace_context(emitter):
        emitter.session_start()
        result = AgentFlow(steps=[read_fixture]).run("fixture question")
        emitter.session_end()
    assert "fixture.json#/7" in str(result)
    events = [event.to_dict() for event in sink.get_events()]
    serialized = json.dumps(events)
    assert "synthetic-private-marker" not in serialized
    assert "fixture.json#/7" in serialized
    starts = [event for event in events if event["event_type"] == "step_start"]
    ends = [event for event in events if event["event_type"] == "step_end"]
    assert starts and ends
    assert ends[0]["parent_seq"] == starts[0]["sequence_num"]
    assert starts[0]["node_id"] and starts[0]["run_id"]
    assert len({event["sequence_num"] for event in events}) == len(events)
