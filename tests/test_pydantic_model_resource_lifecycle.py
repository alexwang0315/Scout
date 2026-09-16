"""Real SDK/HTTP lifecycle regressions with all traffic kept in MockTransport."""

from __future__ import annotations

import asyncio
import importlib
import json
import socket
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError

import httpx2
import openai
import pytest
from openai import Omit
from pydantic_ai import Agent
import pydantic_ai.providers._openai_compatible as sdk_provider

from scout.agents.pydantic_model_lifecycle import (
    pydantic_model_resources,
    run_in_model_worker,
)


@pytest.fixture
def offline_http(monkeypatch):
    clients = []
    requests = []
    closes = []

    def forbidden_network(*_args, **_kwargs):
        raise AssertionError("This lifecycle test must never open a network connection.")

    monkeypatch.setattr(socket.socket, "connect", forbidden_network)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden_network)

    class OfflineNoAuthOpenAI(sdk_provider.AsyncOpenAI):
        # Test-only authentication seam; the real client uses only MockTransport.
        def _validate_headers(self, headers, custom_headers):
            return None

    def offline_openai(*args, **kwargs):
        if kwargs.get("http_client") is None:
            kwargs["http_client"] = new_client()
        kwargs["default_headers"] = {
            **(kwargs.get("default_headers") or {}),
            "Authorization": Omit(),
        }
        return OfflineNoAuthOpenAI(*args, **kwargs)

    monkeypatch.setattr(sdk_provider, "AsyncOpenAI", offline_openai)
    monkeypatch.setattr(openai, "AsyncOpenAI", offline_openai)

    class TrackingClient(httpx2.AsyncClient):
        async def aclose(self):
            closes.append((self, asyncio.get_running_loop()))
            await super().aclose()

    def new_client():
        async def handler(request):
            loop = asyncio.get_running_loop()
            data = json.loads(request.content)
            requests.append((client, loop))
            return httpx2.Response(
                200,
                json={
                    "id": "offline-lifecycle",
                    "object": "chat.completion",
                    "created": 1760000000,
                    "model": data["model"],
                    "choices": [{
                        "index": 0,
                        "message": {"role": "assistant", "content": "offline response"},
                        "finish_reason": "stop",
                    }],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                },
            )

        client = TrackingClient(transport=httpx2.MockTransport(handler))
        clients.append(client)
        return client

    monkeypatch.setattr(sdk_provider, "create_async_httpx2_client", new_client)
    return clients, requests, closes


async def empty_offline_credential():
    return ""


def build_model(factory_module, model_name):
    factory = importlib.import_module(factory_module)
    return factory.build_chat_model(
        model_name=model_name,
        base_url="https://offline.invalid/v1",
        api_key=empty_offline_credential,
    )


@pytest.mark.parametrize(
    "factory_module", ["pydantic_ai_runtime_compat", "scout.agents.pydantic_ai_compat"]
)
@pytest.mark.parametrize("model_name", ["openai-chat:gpt-4o", "nvidia:z-ai/glm-5.2"])
@pytest.mark.parametrize("raise_after_requests", [False, True])
def test_factory_client_is_shared_by_stages_and_closed_before_worker_loop(
    offline_http, factory_module, model_name, raise_after_requests
):
    clients, requests, closes = offline_http

    def call():
        model = build_model(factory_module, model_name)
        if model_name.startswith("nvidia:"):
            assert model.provider.client.max_retries == 0
        agent = Agent(model)
        assert agent.run_sync("first stage").output == "offline response"
        assert not clients[0].is_closed
        assert not closes
        assert agent.run_sync("second stage").output == "offline response"
        if raise_after_requests:
            raise RuntimeError("unchanged callback failure")
        return "completed"

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(run_in_model_worker, call)
        if raise_after_requests:
            with pytest.raises(RuntimeError, match="unchanged callback failure"):
                future.result(timeout=10)
        else:
            assert future.result(timeout=10) == "completed"

    assert len(clients) == 1
    assert len(requests) == 2
    assert requests[0][0] is requests[1][0] is clients[0]
    assert requests[0][1] is requests[1][1]
    assert closes == [requests[0]]
    assert clients[0].is_closed
    assert requests[0][1].is_closed()


@pytest.mark.parametrize(
    "factory_module", ["pydantic_ai_runtime_compat", "scout.agents.pydantic_ai_compat"]
)
def test_timed_out_caller_does_not_close_a_running_workers_client(
    offline_http, factory_module
):
    clients, requests, closes = offline_http
    request_finished = threading.Event()
    release_worker = threading.Event()

    def call():
        model = build_model(factory_module, "nvidia:z-ai/glm-5.2")
        output = Agent(model).run_sync("offline response").output
        request_finished.set()
        assert release_worker.wait(timeout=10)
        return output

    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(run_in_model_worker, call)
    try:
        assert request_finished.wait(timeout=10)
        with pytest.raises(TimeoutError):
            future.result(timeout=0.01)
        assert not clients[0].is_closed
        assert not requests[0][1].is_closed()
        assert not closes
        release_worker.set()
        assert future.result(timeout=10) == "offline response"
    finally:
        release_worker.set()
        executor.shutdown(wait=True)

    assert closes == [requests[0]]
    assert clients[0].is_closed
    assert requests[0][1].is_closed()


def test_model_created_outside_scope_remains_with_its_caller(offline_http):
    clients, requests, closes = offline_http
    model = build_model("scout.agents.pydantic_ai_compat", "openai-chat:gpt-4o")

    # A caller-provided idle loop and externally created model remain caller-owned.
    with asyncio.Runner() as owner:
        loop = owner.get_loop()
        with pydantic_model_resources(loop):
            assert Agent(model).run_sync("offline response").output == "offline response"
        assert asyncio.get_event_loop() is loop
        assert not loop.is_closed()
        assert not clients[0].is_closed
        assert not closes

        async def caller_closes_model():
            async with model:
                pass

        owner.run(caller_closes_model())

    assert closes == [requests[0]]
    assert clients[0].is_closed
    assert loop.is_closed()


@pytest.mark.parametrize(
    "factory_module", ["pydantic_ai_runtime_compat", "scout.agents.pydantic_ai_compat"]
)
def test_factory_in_async_worker_callback_uses_the_running_loop(
    offline_http, factory_module
):
    clients, requests, closes = offline_http

    def call():
        async def callback():
            model = build_model(factory_module, "openai-chat:gpt-4o")
            return (await Agent(model).run("offline response")).output

        return asyncio.get_event_loop().run_until_complete(callback())

    with ThreadPoolExecutor(max_workers=1) as executor:
        assert executor.submit(run_in_model_worker, call).result(timeout=10) == "offline response"

    assert len(requests) == 1
    assert closes == [requests[0]]
    assert clients[0].is_closed
    assert requests[0][1].is_closed()
