"""Keep Pydantic provider worker loops scoped to each synchronous attempt."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event, get_ident
from types import SimpleNamespace

from pydantic import BaseModel
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

import scout.agents.pydantic_provider as provider_module
from scout.agents.deps import ScoutAgentRequest, ScoutToolbox
from scout.agents.model_gateway import ModelProviderHealthMonitor
from scout.agents.model_policy import resolve_model_policy


class LifecycleOutput(BaseModel):
    value: str


def _request() -> ScoutAgentRequest:
    return ScoutAgentRequest(
        agent_name="loop-lifecycle-test",
        instructions="Return the provided typed value without external effects.",
        prompt="Return primary.",
        output_type=LifecycleOutput,
        tools=ScoutToolbox(
            search_memory=lambda _query: [],
            search_capabilities=lambda _query: [],
            get_active_context=lambda: {},
            get_capability=lambda _name: None,
            allowed_tools=frozenset(),
        ),
        context={},
    )


def _response(info):
    return ModelResponse(parts=[
        ToolCallPart(info.output_tools[0].name, {"value": "primary"})
    ])


class Fallback:
    def __init__(self, loops):
        self.loops = loops
        self.closed_at_fallback = []

    def run(self, _request):
        self.closed_at_fallback.append([loop.is_closed() for loop in self.loops])
        return LifecycleOutput(value="fallback")


def _provider(callback, loops, **kwargs):
    return provider_module.PydanticScoutAgentProvider(
        model=FunctionModel(callback),
        local_provider=Fallback(loops),
        model_policy=kwargs.pop("model_policy", resolve_model_policy(env={})),
        **kwargs,
    )


def test_success_closes_each_worker_loop_and_reuses_injected_function_model():
    loops = []
    threads = []

    async def model(_messages, info):
        loops.append(asyncio.get_running_loop())
        threads.append(get_ident())
        return _response(info)

    provider = _provider(model, loops)
    supplied_model = provider._model
    for _ in range(2):
        assert provider.run(_request()) == LifecycleOutput(value="primary")
        assert provider.last_sla_result.status == "completed"
        assert provider.last_sla_result.fallback_used is False
        assert loops[-1].is_closed()
    assert provider._model is supplied_model
    assert len({id(loop) for loop in loops}) == 2
    assert all(thread != get_ident() for thread in threads)


def test_provider_error_closes_all_attempt_loops_before_existing_fallback():
    loops = []

    async def model(_messages, _info):
        loops.append(asyncio.get_running_loop())
        raise RuntimeError("controlled provider failure")

    provider = _provider(model, loops)
    assert provider.run(_request()) == LifecycleOutput(value="fallback")
    result = provider.last_sla_result
    assert result.status == "error_fallback"
    assert result.fallback_used is True
    assert result.attempts == len(loops) == 10
    assert result.provider_health["state"] == "open_circuit"
    assert all(loop.is_closed() for loop in loops)
    assert provider._local_provider.closed_at_fallback == [[True] * 10]


def test_timeout_drains_running_worker_and_closes_loop_before_fallback(monkeypatch):
    loops = []
    entered = Event()
    timed_out = Event()
    release = Event()
    completed = Event()
    original_failure = ModelProviderHealthMonitor.record_failure

    def observe_failure(self, error):
        original_failure(self, error)
        if "model call exceeded" in error:
            timed_out.set()

    monkeypatch.setattr(ModelProviderHealthMonitor, "record_failure", observe_failure)

    async def model(_messages, info):
        loops.append(asyncio.get_running_loop())
        entered.set()
        await asyncio.to_thread(release.wait)
        completed.set()
        return _response(info)

    policy = resolve_model_policy(env={
        "SCOUT_AI_OS_AGGRESSIVE_CONSTRUCTION_MODE": "0",
        "SCOUT_AI_OS_MODEL_TIMEOUT_SECONDS": "0.01",
    })
    provider = _provider(model, loops, model_policy=policy)
    with ThreadPoolExecutor(max_workers=1) as caller:
        result = caller.submit(provider.run, _request())
        try:
            assert entered.wait(5)
            assert timed_out.wait(5)
            assert not result.done()
            assert not completed.is_set()
            assert not loops[0].is_closed()
        finally:
            release.set()
        assert result.result(timeout=5) == LifecycleOutput(value="fallback")
    assert completed.is_set()
    assert loops[0].is_closed()
    assert provider.last_sla_result.status == "timeout_fallback"
    assert provider.last_sla_result.attempts == 1
    assert provider._local_provider.closed_at_fallback == [[True]]


def test_existing_idle_caller_loop_remains_current_and_open():
    loops = []

    async def model(_messages, info):
        loops.append(asyncio.get_running_loop())
        return _response(info)

    caller_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(caller_loop)
    try:
        provider = _provider(model, loops)
        assert provider.run(_request()).value == "primary"
        assert asyncio.get_event_loop() is caller_loop
        assert not caller_loop.is_closed()
        assert loops[0] is not caller_loop
        assert loops[0].is_closed()
    finally:
        asyncio.set_event_loop(None)
        caller_loop.close()


def test_running_caller_loop_is_not_closed_or_replaced():
    loops = []

    async def model(_messages, info):
        loops.append(asyncio.get_running_loop())
        return _response(info)

    async def call_from_async_context():
        caller_loop = asyncio.get_running_loop()
        provider = _provider(model, loops)
        assert provider.run(_request()).value == "primary"
        assert asyncio.get_running_loop() is caller_loop
        assert not caller_loop.is_closed()
        assert loops[0] is not caller_loop
        assert loops[0].is_closed()

    asyncio.run(call_from_async_context())


def test_run_sync_only_agent_adapter_remains_supported(monkeypatch):
    loops = []

    class SyncOnlyAgent:
        def __init__(self, _model, **_kwargs):
            pass

        def run_sync(self, _prompt):
            loops.append(asyncio.get_event_loop())
            return SimpleNamespace(output=LifecycleOutput(value="primary"))

    monkeypatch.setattr(provider_module, "Agent", SyncOnlyAgent)
    provider = provider_module.PydanticScoutAgentProvider(
        local_provider=Fallback(loops),
        model_policy=resolve_model_policy(env={}),
    )
    assert provider.run(_request()).value == "primary"
    assert provider.last_sla_result.status == "completed"
    assert len(loops) == 1
    assert loops[0].is_closed()
