"""Exercise GIS agent loop ownership using the real SDK and offline models."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from threading import Event, get_ident
from types import SimpleNamespace

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

import pretrip_gis_perception as gis


BATCH = {
    "model_role": "route_note_to_cp_intermediary",
    "corpus_boundary": "pretrip_candidate_only",
    "judgements": [],
}


@pytest.fixture
def lifecycle(monkeypatch):
    loops = []
    threads = []
    executors = []
    policy = asyncio.get_event_loop_policy()
    new_loop = policy.new_event_loop

    def tracked_loop():
        loop = new_loop()
        loops.append(loop)
        threads.append(get_ident())
        return loop

    def tracked_executor(*args, **kwargs):
        executor = ThreadPoolExecutor(*args, **kwargs)
        executors.append(executor)
        return executor

    monkeypatch.setattr(policy, "new_event_loop", tracked_loop)
    monkeypatch.setattr(gis, "ThreadPoolExecutor", tracked_executor)
    async def model_response(_messages, info):
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, BATCH)])

    model = FunctionModel(model_response)
    model_calls = []

    def build_model(**kwargs):
        model_calls.append(kwargs)
        return model

    monkeypatch.setattr(gis, "build_chat_model", build_model)
    state = SimpleNamespace(loops=loops, threads=threads, executors=executors,
                            model=model, model_calls=model_calls)
    yield state
    # Negative-replay cleanup prevents a legacy leaked loop from polluting later tests.
    for executor in executors:
        executor.shutdown(wait=True, cancel_futures=True)
    for loop in loops:
        if loop.is_closed():
            continue
        assert not loop.is_running()
        tasks = asyncio.all_tasks(loop)
        for task in tasks:
            task.cancel()
        if tasks:
            loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.run_until_complete(loop.shutdown_default_executor())
        loop.close()
    asyncio.set_event_loop(None)


def _cloud(timeout=5):
    return gis.PydanticAICloudGisPerceptionProvider(
        model_name="openai-chat:fixture-model", base_url="https://fixture.invalid/v1",
        timeout_seconds=timeout, max_candidates=200,
    )


def _call_cloud(provider):
    return provider._run_route_note_agent({"route_notes": []}, api_key="fixture-unused-key")


def test_test_provider_closes_each_owned_loop_when_no_loop_is_installed(lifecycle):
    asyncio.set_event_loop(None)
    provider = gis.PydanticAITestGisPerceptionProvider()
    for _ in range(2):
        result = provider.judge_route_notes([])
        assert result.judgement_count == 0
        assert result.live_model_call_performed is False
        assert result.network_calls_allowed is False
        assert lifecycle.loops[-1].is_closed()
    assert len(lifecycle.loops) == 2
    assert len({id(loop) for loop in lifecycle.loops}) == 2


def test_test_provider_preserves_idle_caller_loop(lifecycle):
    caller_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(caller_loop)
    try:
        result = gis.PydanticAITestGisPerceptionProvider().judge_route_notes([])
        assert result.judgement_count == 0
        assert asyncio.get_event_loop() is caller_loop
        assert not caller_loop.is_closed()
        assert all(loop.is_closed() for loop in lifecycle.loops if loop is not caller_loop)
    finally:
        asyncio.set_event_loop(None)
        caller_loop.close()


def test_test_provider_keeps_running_caller_loop_and_sync_rejection(lifecycle):
    async def call():
        caller_loop = asyncio.get_running_loop()
        before = asyncio.all_tasks()
        with pytest.raises(RuntimeError, match="running"):
            gis.PydanticAITestGisPerceptionProvider().judge_route_notes([])
        await asyncio.sleep(0)
        assert asyncio.get_running_loop() is caller_loop
        assert not caller_loop.is_closed()
        assert asyncio.all_tasks() == before

    asyncio.run(call())
    assert all(loop.is_closed() for loop in lifecycle.loops)


def _failing_agent(monkeypatch):
    drained = Event()
    entered = Event()

    async def child():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            drained.set()

    async def fail(self, *args, **kwargs):
        asyncio.create_task(child())
        await asyncio.sleep(0)
        raise RuntimeError("controlled GIS model failure")

    monkeypatch.setattr(Agent, "run", fail)
    return entered, drained


def test_test_provider_error_drains_owned_tasks_and_closes_loop(monkeypatch, lifecycle):
    asyncio.set_event_loop(None)
    entered, drained = _failing_agent(monkeypatch)
    with pytest.raises(RuntimeError, match="controlled GIS model failure"):
        gis.PydanticAITestGisPerceptionProvider().judge_route_notes([])
    assert entered.is_set()
    assert drained.is_set()
    assert all(loop.is_closed() for loop in lifecycle.loops)


def test_cloud_worker_closes_each_loop_and_preserves_model_settings(monkeypatch, lifecycle):
    calls = []
    original_run_sync = Agent.run_sync

    def observe(self, *args, **kwargs):
        calls.append((self.model, args, kwargs))
        return original_run_sync(self, *args, **kwargs)

    monkeypatch.setattr(Agent, "run_sync", observe)
    provider = _cloud()
    for _ in range(2):
        assert _call_cloud(provider).model_dump(mode="json") == BATCH
        assert lifecycle.loops[-1].is_closed()
    assert len(lifecycle.loops) == 2
    assert all(thread != get_ident() for thread in lifecycle.threads)
    assert all(model is lifecycle.model for model, _, _ in calls)
    assert all(kwargs == {"model_settings": {"max_tokens": 5000, "temperature": 0}}
               for _, _, kwargs in calls)
    assert lifecycle.model_calls == [{"model_name": "openai-chat:fixture-model",
        "base_url": "https://fixture.invalid/v1", "api_key": "fixture-unused-key"}] * 2
    assert provider.max_candidates == 200
    assert provider.timeout_seconds == 5


def test_cloud_error_drains_owned_tasks_before_propagating(monkeypatch, lifecycle):
    entered, drained = _failing_agent(monkeypatch)
    with pytest.raises(RuntimeError, match="controlled GIS model failure"):
        _call_cloud(_cloud())
    assert entered.is_set()
    assert drained.is_set()
    assert all(loop.is_closed() for loop in lifecycle.loops)


def test_cloud_timeout_eventually_drains_worker_without_closing_idle_caller(monkeypatch, lifecycle):
    entered = Event()
    release = Event()
    completed = Event()

    async def delayed(self, *args, **kwargs):
        entered.set()
        await asyncio.to_thread(release.wait)
        completed.set()
        return SimpleNamespace(output=BATCH)

    monkeypatch.setattr(Agent, "run", delayed)
    caller_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(caller_loop)
    try:
        with pytest.raises(TimeoutError, match="cloud GIS Pydantic AI judgement timed out"):
            _call_cloud(_cloud(timeout=0.01))
        assert entered.wait(2)
        assert not completed.is_set()
        assert asyncio.get_event_loop() is caller_loop
        assert not caller_loop.is_closed()
    finally:
        release.set()
        for executor in lifecycle.executors:
            executor.shutdown(wait=True, cancel_futures=True)
        asyncio.set_event_loop(None)
        caller_loop.close()
    assert completed.is_set()
    assert all(loop.is_closed() for loop in lifecycle.loops)


def test_cloud_worker_preserves_running_caller_loop(lifecycle):
    async def call():
        caller_loop = asyncio.get_running_loop()
        assert _call_cloud(_cloud()).model_dump(mode="json") == BATCH
        assert asyncio.get_running_loop() is caller_loop
        assert not caller_loop.is_closed()
        assert all(loop.is_closed() for loop in lifecycle.loops if loop is not caller_loop)

    asyncio.run(call())
    assert all(loop.is_closed() for loop in lifecycle.loops)


@pytest.mark.parametrize("provider_kind", ["test", "cloud"])
def test_run_sync_only_adapter_remains_supported(monkeypatch, lifecycle, provider_kind):
    caller_context = ContextVar("gis_lifecycle_fixture", default=None)
    caller_context.set("caller-value")
    class SyncOnlyAgent:
        def __init__(self, model, **kwargs):
            if provider_kind == "cloud":
                assert model is lifecycle.model

        def run_sync(self, *args, **kwargs):
            if provider_kind == "test":
                assert caller_context.get() == "caller-value"
            assert not asyncio.get_event_loop().is_closed()
            return SimpleNamespace(output=BATCH)

    monkeypatch.setattr("pydantic_ai.Agent", SyncOnlyAgent)
    if provider_kind == "cloud":
        result = _call_cloud(_cloud())
    else:
        result = gis.PydanticAITestGisPerceptionProvider()._run_test_agent([])
    assert result.model_dump(mode="json") == BATCH
    assert len(lifecycle.loops) == 1
    assert lifecycle.loops[0].is_closed()


def test_test_provider_preserves_sdk_nested_sync_callback_guard(lifecycle):
    from pydantic_ai import _utils
    from pydantic_ai.exceptions import UserError

    token = _utils._in_sync_callback.set(True)
    try:
        with pytest.raises(UserError, match="synchronous tool"):
            gis.PydanticAITestGisPerceptionProvider().judge_route_notes([])
    finally:
        _utils._in_sync_callback.reset(token)
    assert all(loop.is_closed() for loop in lifecycle.loops)
