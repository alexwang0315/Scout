"""Actual sync entrypoints borrow caller loops and close sessions they create."""

from __future__ import annotations

import asyncio
import importlib
import json
import socket
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel as OfflineTestModel

from scout.agents.pydantic_model_lifecycle import pydantic_model_session
from test_pydantic_model_resource_lifecycle import (
    build_model,
    empty_offline_credential,
    offline_http,
)


def _entrypoint(name, monkeypatch):
    module_name = {
        "review": "pretrip_route_context_scout_ai_review",
        "regenerate": "pretrip_route_context_scout_ai_regenerate",
        "hailo": "tools.scout_ai_aihat2_fallback_eval",
        "grounded": "tools.scout_ai_cloud_grounded_eval",
    }[name]
    module = importlib.import_module(module_name)
    if name == "review":
        output = {
            "verdict": "PASS", "readability_score": 3, "summary": "offline",
            "strengths": ["offline"],
            "criterion_assessments": [
                {"criterion_id": key, "rating": "pass", "evidence": "offline", "reason": "offline"}
                for key in sorted(module.CRITERION_IDS)
            ],
        }
    elif name == "regenerate":
        output = {
            "artifact_kind": "scout_ai_route_context_editorial_plan",
            "schema_version": module.EDITORIAL_PLAN_SCHEMA_VERSION,
            "title": "offline", "eyebrow": "offline", "subtitle": "offline",
            "section_order": list(module.SECTION_IDS),
            "section_headings": {key: "offline" for key in module.SECTION_IDS},
            "reader_questions": ["one?", "two?", "three?"],
            "closing_note": "offline",
        }
    else:
        output = None
    if hasattr(module, "build_chat_model"):
        monkeypatch.setattr(
            module, "build_chat_model",
            lambda **_: OfflineTestModel(call_tools=[], custom_output_args=output)
            if output is not None
            else OfflineTestModel(call_tools=[], custom_output_text="offline response"),
        )
    if name in {"review", "regenerate"}:
        return lambda: module._call_live_model(
            prompt="offline", model_name="openrouter:z-ai/glm-5.2",
            base_url=None, api_key="", timeout_seconds=10,
        )
    if name == "hailo":
        return lambda: module.call_hailo_model_via_pydantic_ai(
            endpoint="http://127.0.0.1:1", model="openrouter:z-ai/glm-5.2",
            prompt="offline", timeout_seconds=10,
            hailo_call=lambda **_: ("offline response", {"offline": True}),
        )
    runner = module.NvidiaCloudGroundedRunner(
        model_name="openrouter:z-ai/glm-5.2", api_key="", max_tokens=None
    )
    return lambda: runner.run("offline", timeout_seconds=10)


@pytest.mark.parametrize("name", ["review", "regenerate", "hailo", "grounded"])
@pytest.mark.parametrize("borrowed", [False, True])
def test_actual_entrypoint_owns_only_its_missing_session_loop(name, borrowed, monkeypatch):
    observed = []
    for model_type in (OfflineTestModel, FunctionModel):
        original = model_type.request

        async def observe(self, *args, _original=original, **kwargs):
            observed.append((asyncio.get_running_loop(), threading.get_ident()))
            return await _original(self, *args, **kwargs)

        monkeypatch.setattr(model_type, "request", observe)
    operation = _entrypoint(name, monkeypatch)

    def invoke():
        owner = asyncio.new_event_loop() if borrowed else None
        asyncio.set_event_loop(owner)
        thread_id = threading.get_ident()
        try:
            for _ in range(2):
                if name == "regenerate":
                    with pytest.raises(Exception, match="required WebSearch -> WebFetch"):
                        operation()
                else:
                    assert operation() is not None
            assert len(observed) == 2
            assert all(thread == thread_id for _, thread in observed)
            if owner is not None:
                assert all(loop is owner for loop, _ in observed)
                assert asyncio.get_event_loop() is owner
                assert not owner.is_closed()
            else:
                assert all(loop.is_closed() for loop, _ in observed)
        finally:
            if owner is not None:
                asyncio.set_event_loop(None)
                owner.close()

    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(invoke).result(timeout=15)


def test_real_main_thread_without_a_loop_closes_its_session(tmp_path):
    script = """
import asyncio,json
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel
from scout.agents.pydantic_model_lifecycle import pydantic_model_session
with pydantic_model_session():
    loop=asyncio.get_event_loop()
    assert Agent(TestModel(call_tools=[],custom_output_text="offline")).run_sync("offline").output=="offline"
assert loop.is_closed()
print(json.dumps({"closed":loop.is_closed()}))
"""
    result = subprocess.run(
        [sys.executable, "-W", "error", "-c", script],
        cwd=tmp_path, capture_output=True, text=True, timeout=15, check=True,
    )
    assert json.loads(result.stdout) == {"closed": True}
    assert not result.stderr


def test_borrowed_loop_closes_owned_factory_clients_without_closing_caller(offline_http):
    clients, requests, closes = offline_http
    with asyncio.Runner() as caller:
        loop = caller.get_loop()
        for _ in range(2):
            with pydantic_model_session():
                model = build_model("pydantic_ai_runtime_compat", "nvidia:z-ai/glm-5.2")
                assert Agent(model).run_sync("offline").output == "offline response"
            assert asyncio.get_event_loop() is loop
            assert not loop.is_closed()
            assert all(client.is_closed for client in clients)
    assert len(clients) == len(requests) == len(closes) == 2
    assert all(request_loop is loop for _, request_loop in requests)
    assert loop.is_closed()


def test_grounded_batch_reuses_its_owned_client_until_the_batch_session_ends(offline_http):
    from tools.scout_ai_cloud_grounded_eval import NvidiaCloudGroundedRunner

    clients, requests, closes = offline_http
    with pydantic_model_session():
        runner = NvidiaCloudGroundedRunner(
            model_name="nvidia:z-ai/glm-5.2",
            api_key=empty_offline_credential, max_tokens=None,
        )
        for _ in range(2):
            assert runner.run("offline", timeout_seconds=10)[0] == "offline response"
            assert len(clients) == 1
            assert not clients[0].is_closed
            assert not closes
    assert len(requests) == 2
    assert closes == [requests[0]]
    assert clients[0].is_closed
    assert requests[0][1].is_closed()


def test_grounded_standalone_calls_reopen_owned_clients_on_the_new_session_loop(offline_http):
    from tools.scout_ai_cloud_grounded_eval import NvidiaCloudGroundedRunner

    clients, requests, closes = offline_http

    def invoke():
        runner = NvidiaCloudGroundedRunner(
            model_name="nvidia:z-ai/glm-5.2",
            api_key=empty_offline_credential, max_tokens=None,
        )
        for _ in range(2):
            assert runner.run("offline", timeout_seconds=10)[0] == "offline response"
            assert all(client.is_closed for client in clients)

    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(invoke).result(timeout=15)
    assert len(clients) == len(requests) == len(closes) == 2
    assert clients[0] is not clients[1]
    assert requests[0][1] is not requests[1][1]
    assert all(loop.is_closed() for _, loop in requests)


@pytest.mark.parametrize(
    "factory_module", ["pydantic_ai_runtime_compat", "scout.agents.pydantic_ai_compat"]
)
def test_nvidia_owned_context_preserves_original_transport_on_reopen(factory_module, monkeypatch):
    from openai import AsyncOpenAI
    from scout.agents.pydantic_ai_compat import NVIDIA_BASE_URL

    def forbidden(*_args, **_kwargs):
        raise AssertionError("No network is allowed in this constructor comparison.")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    original = AsyncOpenAI(
        base_url=NVIDIA_BASE_URL, api_key=empty_offline_credential, max_retries=0
    )
    model = importlib.import_module(factory_module).build_chat_model(
        model_name="nvidia:z-ai/glm-5.2", api_key=empty_offline_credential
    )

    def transport_values(client):
        pool = client._client._transport._pool
        return (
            client.max_retries, client.timeout.as_dict(),
            client._client.timeout.as_dict(),
            pool._max_connections, pool._max_keepalive_connections, pool._keepalive_expiry,
        )

    expected = transport_values(original)

    async def verify():
        try:
            for _ in range(2):
                async with model:
                    assert transport_values(model.provider.client) == expected
                    assert not model.provider.client.is_closed()
                    async with model:
                        assert not model.provider.client.is_closed()
                    assert not model.provider.client.is_closed()
                assert model.provider.client.is_closed()
        finally:
            await original.close()

    with asyncio.Runner() as owner:
        owner.run(verify())


def test_session_keeps_sdk_nested_sync_callback_rejection(monkeypatch):
    import tools.scout_ai_aihat2_fallback_eval as module

    invoked_transport = []

    def callback(_messages, _info):
        _, metadata = module.call_hailo_model_via_pydantic_ai(
            endpoint="http://127.0.0.1:1", model="openrouter:z-ai/glm-5.2",
            prompt="offline", timeout_seconds=10,
            hailo_call=lambda **_: invoked_transport.append(True),
        )
        error = metadata["pydantic_ai"]["error"]
        assert "cannot be used inside a synchronous tool" in error
        return ModelResponse(parts=[TextPart("nested sync was rejected")])

    with pydantic_model_session():
        result = Agent(FunctionModel(callback)).run_sync("offline")
    assert result.output == "nested sync was rejected"
    assert not invoked_transport
