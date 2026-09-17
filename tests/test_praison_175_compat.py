"""Praison SDK contracts, not model-quality or hardware qualification."""

from __future__ import annotations

import asyncio
import copy
import json
import socket
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock
from importlib import import_module

import pytest
import httpx2
from openai import AsyncOpenAI, OpenAI
from openai.types.chat import ChatCompletion, ChatCompletionChunk
from pydantic import BaseModel


@pytest.fixture(autouse=True)
def fixture_environment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for name, value in {
        "HOME": str(tmp_path), "PRAISONAI_HOME": str(tmp_path / ".praisonai"),
        "OPENAI_API_KEY": "fixture-only", "OPENAI_BASE_URL": "http://127.0.0.1:9/v1",
        "PRAISONAI_TELEMETRY_DISABLED": "true", "DO_NOT_TRACK": "true",
    }.items():
        monkeypatch.setenv(name, value)

    def no_connect(*args, **kwargs):
        pytest.fail("A fixture attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", no_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", no_connect)
    monkeypatch.setattr(socket, "create_connection", no_connect)
    pytest.importorskip("praisonaiagents")


def test_agentteam_rejects_cross_thread_reentry_and_releases_guard(monkeypatch):
    from praisonaiagents import Agent, AgentTeam

    agent = Agent(name="team-fixture", model="scout-deterministic-replay")
    team = AgentTeam(agents=[agent], process="sequential")
    entered, release = Event(), Event()

    def execute(**kwargs):
        entered.set()
        assert release.wait(10), "Fixture worker was not released"
        return "fixture-finished"

    monkeypatch.setattr(team, "_start_impl", execute)
    with ThreadPoolExecutor(max_workers=1) as pool:
        running = pool.submit(team.start)
        try:
            assert entered.wait(10)
            with pytest.raises(RuntimeError, match="already running"):
                team.start()
        finally:
            release.set()
        assert running.result() == "fixture-finished"
    assert team.start() == "fixture-finished"
    agent.close()


@pytest.mark.parametrize("async_close", [False, True])
def test_closing_same_named_agent_releases_only_its_approval_scope(monkeypatch, async_close):
    from praisonaiagents import Agent
    from praisonaiagents import approval
    from praisonaiagents.approval.registry import ApprovalRegistry

    registry = ApprovalRegistry()
    monkeypatch.setattr(approval, "get_approval_registry", lambda: registry)
    first = Agent(name="same-name", model="scout-deterministic-replay")
    second = Agent(name="same-name", model="scout-deterministic-replay")
    scopes = [agent._approval_scope_id for agent in (first, second)]
    assert scopes[0] != scopes[1]
    async def scenario():
        # Approval cache is ContextVar-scoped: close in the run that granted it.
        for scope in scopes:
            registry.auto_approve_tool("fixture_read", scope)
            registry.mark_approved("fixture_read", {"id": 7}, scope_id=scope)
        assert not registry.is_auto_approved("fixture_read", "third-agent")
        if async_close:
            await first.aclose()
        else:
            first.close()
        for scope, expected in zip(scopes, (False, True), strict=True):
            assert registry.is_auto_approved("fixture_read", scope) is expected
            assert registry.is_already_approved(
                "fixture_read", {"id": 7}, scope_id=scope,
            ) is expected
    try:
        asyncio.run(scenario())
    finally:
        first.close()
        second.close()


def test_async_handoffs_serialize_history_and_restore_target(monkeypatch):
    from praisonaiagents import Agent
    from praisonaiagents.agent.handoff import ContextPolicy, Handoff, HandoffConfig

    async def scenario():
        target = Agent(name="target", model="scout-deterministic-replay")
        original = [{"role": "user", "content": "target-original"}]
        target.chat_history = copy.deepcopy(original)
        sources = [Agent(name=name, model="scout-deterministic-replay") for name in ("A", "B")]
        for source in sources:
            source.chat_history = [{"role": "user", "content": f"source-{source.name}"}]
        entered, release = asyncio.Event(), asyncio.Event()
        observed = []

        async def respond(prompt, **kwargs):
            before = copy.deepcopy(target.chat_history)
            observed.append(before)
            if len(observed) == 1:
                entered.set()
                await release.wait()
            assert target.chat_history == before
            return before[0]["content"]

        monkeypatch.setattr(target, "achat", respond)
        transfer = Handoff(target, config=HandoffConfig(
            context_policy=ContextPolicy.FULL, max_concurrent=10,
        ))
        first = asyncio.create_task(transfer.execute_async(sources[0], "Read A"))
        await entered.wait()
        second = asyncio.create_task(transfer.execute_async(sources[1], "Read B"))
        try:
            await asyncio.sleep(0)
            assert len(observed) == 1
            assert target.chat_history[0]["content"] == "source-A"
        finally:
            release.set()
        results = await asyncio.gather(first, second)
        assert all(result.success for result in results)
        assert [result.response for result in results] == ["source-A", "source-B"]
        assert target.chat_history == original
        for agent in [target, *sources]:
            await agent.aclose()

    asyncio.run(scenario())


class FixtureAnswer(BaseModel):
    checkpoint: str
    candidate_only: bool


FIXTURE_TOOL = {
    "type": "function", "function": {
        "name": "fixture_read", "description": "Read a fixture checkpoint.",
        "parameters": {"type": "object", "properties": {"id": {"type": "integer"}},
                       "required": ["id"]},
    },
}


def _reply(index, *, tool=False):
    message = {"role": "assistant", "content": None}
    if tool:
        message["tool_calls"] = [{
            "id": f"fixture-call-{index}", "type": "function",
            "function": {"name": "fixture_read", "arguments": '{"id":7}'},
        }]
    else:
        message["content"] = '{"checkpoint":"CP-7","candidate_only":true}'
    return ChatCompletion.model_validate({
        "id": f"fixture-response-{index}", "object": "chat.completion", "created": 1,
        "model": "scout-fixture", "choices": [{
            "index": 0, "message": message, "finish_reason": "tool_calls" if tool else "stop",
        }], "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
    })


def _chunks(reply, *, arguments_in_first_chunk=False):
    message = reply.choices[0].message
    delta = {"role": "assistant", "content": message.content}
    if message.tool_calls:
        delta["tool_calls"] = [dict(call.model_dump(), index=index)
                               for index, call in enumerate(message.tool_calls)]
    payloads = [(delta, None)]
    if message.tool_calls and not arguments_in_first_chunk:
        for call in delta["tool_calls"]:
            call["function"]["arguments"] = ""
        payloads.append(({"tool_calls": [
            {"index": index, "function": {"arguments": call.function.arguments}}
            for index, call in enumerate(message.tool_calls)
        ]}, None))
    payloads.append(({}, reply.choices[0].finish_reason))
    for payload, finish in payloads:
        yield ChatCompletionChunk.model_validate({
            "id": reply.id, "object": "chat.completion.chunk", "created": 1,
            "model": reply.model, "choices": [{"index": 0, "delta": payload,
                                               "finish_reason": finish}],
        })


@pytest.mark.parametrize("async_mode,stream", [(False, False), (False, True), (True, False), (True, True)])
@pytest.mark.parametrize("fail_first", [False, True])
def test_sdk_tool_loops_return_evidence_and_recover_errors(monkeypatch, async_mode, stream, fail_first):
    from praisonaiagents import main
    from praisonaiagents.llm.openai_client import OpenAIClient

    client = OpenAIClient(api_key="fixture-only", base_url="http://127.0.0.1:9/v1")
    requests, executions, events = [], [], []
    tool_turns = 2 if fail_first else 1
    monkeypatch.setattr(main, "execute_sync_callback", lambda event, **data: events.append((event, data)))

    def completion(request):
        payload = json.loads(request.content)
        requests.append(payload)
        reply = _reply(len(requests), tool=len(requests) <= tool_turns)
        if payload.get("stream"):
            body = "".join(f"data: {chunk.model_dump_json()}\n\n" for chunk in _chunks(reply))
            return httpx2.Response(200, headers={"content-type": "text/event-stream"},
                                   content=body + "data: [DONE]\n\n")
        return httpx2.Response(200, json=reply.model_dump())

    def execute(name, arguments, **kwargs):
        executions.append((name, arguments, kwargs.get("tool_call_id")))
        assert name == "fixture_read" and arguments == {"id": 7}
        if fail_first and len(executions) == 1:
            raise OSError("fixture temporarily unavailable")
        return {"checkpoint": "CP-7", "source_ref": "fixture.json#/7", "candidate_only": True}

    async def async_execute(*args, **kwargs):
        return execute(*args, **kwargs)

    # Mock the transport, not SDK methods: stream and non-stream use different paths.
    client._sync_client = OpenAI(api_key="fixture-only", base_url="http://127.0.0.1:9/v1",
        http_client=httpx2.Client(transport=httpx2.MockTransport(completion)))
    client._async_client = AsyncOpenAI(api_key="fixture-only", base_url="http://127.0.0.1:9/v1",
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(completion)))
    history = [{"role": "user", "content": "Read fixture CP 7"}]
    options = dict(messages=history, model="scout-fixture", tools=[FIXTURE_TOOL],
                   stream=stream, verbose=False, max_iterations=10)
    if async_mode:
        result = asyncio.run(client.achat_completion_with_tools(
            **options, execute_tool_fn=async_execute, agent_name="scout-fixture",
        ))
    else:
        result = client.chat_completion_with_tools(**options, execute_tool_fn=execute)
    answer = FixtureAnswer.model_validate_json(result.choices[0].message.content)
    assert answer.checkpoint == "CP-7" and answer.candidate_only
    assert len(executions) == tool_turns
    assert len(requests) == tool_turns + 1
    tool_returns = [m for m in requests[-1]["messages"] if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_returns] == [x[2] for x in executions]
    assert "fixture.json#/7" in tool_returns[-1]["content"]
    if fail_first:
        assert "fixture temporarily unavailable" in tool_returns[0]["content"]
    assert history == [{"role": "user", "content": "Read fixture CP 7"}]
    starts = [data for event, data in events if event == "llm_start"]
    ends = [data for event, data in events if event == "llm_end"]
    assert len(starts) == len(ends) == len(requests)
    if async_mode:
        assert all(data["latency_ms"] >= 0 for data in ends)
    client._sync_client.close()
    asyncio.run(client._async_client.close())


@pytest.mark.parametrize("provider,base", [("ollama", "http://127.0.0.1:11434"),
                                         ("openai", "http://127.0.0.1:1234/v1")])
def test_configured_local_embedding_applies_to_documents_and_queries(monkeypatch, tmp_path, provider, base):
    from praisonaiagents.knowledge.adapters.factories import ChromaKnowledgeAdapter

    embedding = import_module("praisonaiagents.embedding")
    calls = []

    def embed(text, *, model, **kwargs):
        calls.append({"text": text, "model": model, **kwargs})
        return SimpleNamespace(embeddings=[[0.1, 0.2, 0.3]])

    monkeypatch.setattr(embedding, "embedding", embed)
    monkeypatch.setenv("OPENAI_EMBEDDING_MODEL", "must-not-select-cloud-embedding")
    chroma = MagicMock()
    collection = chroma.PersistentClient.return_value.get_collection.return_value
    collection.query.return_value = {
        "ids": [["fixture-7"]], "documents": [["CP-7 fixture evidence"]],
        "metadatas": [[{"source_ref": "fixture.json#/7"}]], "distances": [[0.0]],
    }
    adapter = ChromaKnowledgeAdapter(chroma, MagicMock(), config={
        "vector_store": {"config": {"path": str(tmp_path / "fixture-vector-store")}},
        "embedder": {"provider": provider, "config": {"model": "fixture-embedding", "api_base": base}},
    })
    assert adapter.add("CP-7 fixture evidence").success
    result = adapter.search("Where is CP-7?", agent_id="fixture-agent")
    assert result.results[0].text == "CP-7 fixture evidence"
    assert [call["text"] for call in calls] == ["CP-7 fixture evidence", "Where is CP-7?"]
    assert all(call["api_base"] == base for call in calls)
    assert all("fixture-embedding" in call["model"] for call in calls)
    assert collection.query.call_args.kwargs["where"] == {"agent_id": "fixture-agent"}


@pytest.mark.parametrize("legacy", [False, True])
def test_rag_normalizes_sdk_and_legacy_search_results(monkeypatch, legacy):
    from praisonaiagents import Agent
    from praisonaiagents.knowledge.models import SearchResult, SearchResultItem

    payload = SearchResult(results=[SearchResultItem(text="CP-7 source-backed fixture")])
    knowledge = SimpleNamespace(search=lambda *args, **kwargs: payload.to_dict() if legacy else payload,
                                add=lambda *args, **kwargs: None)
    agent = Agent(name="fixture-rag", model="scout-deterministic-replay", knowledge=knowledge)
    try:
        context, _ = agent._get_knowledge_context("CP-7")
        assert "CP-7 source-backed fixture" in context
    finally:
        agent.close()


class ReviewState(BaseModel):
    checkpoint: str = "CP-7"
    score: int = 0
    input: str = ""
    inspect_fixture_output: str = ""


def test_typed_workflow_executes_and_validates_updated_variables():
    from praisonaiagents import AgentFlow
    from praisonaiagents.workflows.state import WorkflowStateError
    from praisonaiagents.workflows.workflows import StepResult

    def inspect_fixture(ctx):
        return StepResult(output=f"Reviewed {ctx.variables['checkpoint']}", variables={"score": 7})

    flow = AgentFlow(steps=[inspect_fixture], state_model=ReviewState,
                     variables={"checkpoint": "CP-7"})
    result = flow.run("Review fixture")
    assert "CP-7" in str(result)
    assert result["variables"]["score"] == 7
    flow.variables.update(result["variables"])
    flow.validate_variables()
    assert flow.state.score == 7
    flow.variables["score"] = "not-an-integer"
    with pytest.raises(WorkflowStateError, match="do not fit"):
        flow.validate_variables()


def test_typed_workflow_rejects_unknown_keys_without_changing_legacy_flows():
    from praisonaiagents import AgentFlow
    from praisonaiagents.workflows.state import WorkflowStateError

    with pytest.raises(WorkflowStateError, match="Unknown workflow variable"):
        AgentFlow(steps=[], state_model=ReviewState, variables={"chekpoint": "CP-7"})
    legacy = AgentFlow(steps=[], variables={"arbitrary": "fixture"})
    assert legacy.state is None
    legacy.validate_variables()


def test_small_model_tool_json_recovery_does_not_reinterpret_hosted_prose():
    from praisonaiagents.llm.adapters import DefaultAdapter, LocalOpenAIAdapter, OllamaAdapter

    text = '{"name":"fixture_read","arguments":{"id":7}}'
    for adapter in (OllamaAdapter(), LocalOpenAIAdapter()):
        calls = adapter.recover_tool_calls_from_text(text, [FIXTURE_TOOL])
        assert calls and calls[0]["function"]["name"] == "fixture_read"
    assert DefaultAdapter().recover_tool_calls_from_text(text, [FIXTURE_TOOL]) is None
    # Recovery is syntax parsing, not tool authorization; Scout's registry remains authoritative.


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="PRAISON-SYNC-LATENCY-CLOCK-001: SDK mixes wall and monotonic clocks")
def test_sdk_sync_latency_is_nonnegative(monkeypatch):
    from praisonaiagents import main
    from praisonaiagents.llm.openai_client import OpenAIClient

    events = []
    monkeypatch.setattr(main, "execute_sync_callback", lambda event, **data: events.append((event, data)))
    client = OpenAIClient(api_key="fixture-only")
    monkeypatch.setattr(client, "create_completion", lambda **kwargs: _reply(1))
    client.chat_completion_with_tools(messages=[{"role": "user", "content": "Fixture"}],
                                      stream=False, verbose=False, max_iterations=10)
    assert all(data["latency_ms"] >= 0 for event, data in events if event == "llm_end")


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="PRAISON-ASYNC-TEAM-REENTRY-001: guard identifies thread, not asyncio task")
def test_shared_team_rejects_same_event_loop_concurrent_runs(monkeypatch):
    from praisonaiagents import Agent, AgentTeam

    async def scenario():
        agent = Agent(name="async-team-fixture", model="scout-deterministic-replay")
        team = AgentTeam(agents=[agent], process="sequential")
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def execute():
            calls.append("entered")
            entered.set()
            await release.wait()

        monkeypatch.setattr(team, "arun_all_tasks", execute)
        first = asyncio.create_task(team.astart("first"))
        await entered.wait()
        second = asyncio.create_task(team.astart("second"))
        try:
            await asyncio.sleep(0)
        finally:
            release.set()
        results = await asyncio.gather(first, second, return_exceptions=True)
        await agent.aclose()
        assert isinstance(results[1], RuntimeError), f"Concurrent calls entered: {calls}"

    asyncio.run(scenario())


@pytest.mark.xfail(strict=True, raises=json.JSONDecodeError,
                   reason="PRAISON-STREAM-FIRST-ARGS-001: first SSE tool-call arguments are dropped")
def test_stream_parser_preserves_arguments_in_initial_chunk():
    from praisonaiagents.llm.openai_client import process_stream_chunks

    result = process_stream_chunks(list(_chunks(_reply(1, tool=True), arguments_in_first_chunk=True)))
    call = result.choices[0].message.tool_calls[0]
    assert json.loads(call.function["arguments"]) == {"id": 7}
