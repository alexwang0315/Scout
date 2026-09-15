"""Exercise Assistant worker lifecycle with the actual offline Pydantic SDK."""
from __future__ import annotations

import asyncio
from threading import Event, get_ident

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

import assistant_pydantic_provider as provider_module
from assistant_models import ScoutAssistantQuery
from assistant_pydantic_provider import ScoutWorkspaceToolContext


def _runner(monkeypatch, callback):
    model = FunctionModel(callback)
    monkeypatch.setattr(provider_module, "build_chat_model", lambda **_kwargs: model)
    return provider_module.PydanticAIEnvRunner(
        model_name="openrouter:z-ai/glm-5.2",
        profile_name="cloud",
        workspace_tools_enabled=False,
    )


def _context(tmp_path):
    return ScoutWorkspaceToolContext(
        query=ScoutAssistantQuery(
            surface="pretrip",
            question="目前哪個 CP 最危險？",
            project_id="missing-project",
        ),
        sources=[],
        pretrip_workspace_root=tmp_path,
    )


@pytest.mark.parametrize("operation", ["basic", "workspace"])
def test_real_model_result_and_worker_loop_cleanup(monkeypatch, tmp_path, operation):
    loops = []
    threads = []

    async def model(_messages, _info):
        loops.append(asyncio.get_running_loop())
        threads.append(get_ident())
        return ModelResponse(parts=[TextPart(
            "bounded answer" if operation == "basic" else "CP 3 是目前最危險的位置。"
        )])

    runner = _runner(monkeypatch, model)
    if operation == "basic":
        output = runner.run("bounded prompt", timeout_seconds=10)
        assert output == "bounded answer"
    else:
        # Keep the real workspace path enabled so the SDK executes before its
        # ungrounded answer is rejected; an early no-evidence return is no proof.
        runner.workspace_tools_enabled = True
        output = runner.run_with_workspace_tools(
            "bounded prompt", timeout_seconds=10, tool_context=_context(tmp_path)
        )
        assert output == "目前沒有取得所選 Scout 工具的證據，因此不會提供未驗證答案。"
        assert runner.last_grounding_verification["passed"] is False
    assert loops
    assert all(thread != get_ident() for thread in threads)
    assert all(loop.is_closed() for loop in loops)
    assert runner.last_agent_run_ledger["budget"]["max_requests"] == 10


def test_provider_exception_closes_worker_loop_without_changing_error(monkeypatch):
    loops = []

    async def model(_messages, _info):
        loops.append(asyncio.get_running_loop())
        raise RuntimeError("controlled assistant model failure")

    runner = _runner(monkeypatch, model)
    with pytest.raises(RuntimeError, match="controlled assistant model failure"):
        runner.run("bounded prompt", timeout_seconds=10)
    assert len(loops) == 1
    assert loops[0].is_closed()


def test_workspace_stages_share_one_worker_loop_until_complete(monkeypatch, tmp_path):
    loops = []

    async def model(_messages, _info):
        loops.append(asyncio.get_running_loop())
        return ModelResponse(parts=[TextPart("stage result")])

    runner = _runner(monkeypatch, model)
    stages = Agent(FunctionModel(model))

    def two_stages(_prompt, _context, _timeout, _allow_workspace_tools):
        first = stages.run_sync("first stage").output
        second = stages.run_sync("second stage").output
        assert loops[0] is loops[1]
        assert not loops[0].is_closed()
        return first + "/" + second

    monkeypatch.setattr(runner, "_run_model_with_workspace_tools", two_stages)
    assert runner.run_with_workspace_tools(
        "bounded prompt", timeout_seconds=10, tool_context=_context(tmp_path)
    ) == "stage result/stage result"
    assert loops[0].is_closed()


def test_timeout_keeps_active_worker_then_closes_its_loop_when_it_finishes(monkeypatch):
    loops = []
    entered = Event()
    release = Event()
    loop_closed = Event()
    original_close = asyncio.BaseEventLoop.close

    def observe_close(loop):
        original_close(loop)
        if any(loop is owned for owned in loops):
            loop_closed.set()

    monkeypatch.setattr(asyncio.BaseEventLoop, "close", observe_close)

    async def model(_messages, _info):
        loops.append(asyncio.get_running_loop())
        entered.set()
        await asyncio.to_thread(release.wait)
        return ModelResponse(parts=[TextPart("bounded answer")])

    runner = _runner(monkeypatch, model)
    try:
        with pytest.raises(TimeoutError, match="pydantic assistant provider timed out"):
            runner.run("bounded prompt", timeout_seconds=0.01)
        assert entered.wait(5)
        assert not loops[0].is_closed()
    finally:
        release.set()
    assert loop_closed.wait(5)
    assert loops[0].is_closed()


@pytest.mark.parametrize("running", [False, True])
def test_existing_caller_loop_remains_owned_by_caller(monkeypatch, running):
    loops = []

    async def model(_messages, _info):
        loops.append(asyncio.get_running_loop())
        return ModelResponse(parts=[TextPart("bounded answer")])

    runner = _runner(monkeypatch, model)

    def verify(caller_loop):
        assert runner.run("bounded prompt", timeout_seconds=10) == "bounded answer"
        assert asyncio.get_event_loop() is caller_loop
        assert not caller_loop.is_closed()
        assert loops[0] is not caller_loop
        assert loops[0].is_closed()

    if running:
        async def active():
            verify(asyncio.get_running_loop())
        asyncio.run(active())
    else:
        caller_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(caller_loop)
        try:
            verify(caller_loop)
        finally:
            asyncio.set_event_loop(None)
            caller_loop.close()
