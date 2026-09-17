from __future__ import annotations

import asyncio
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from scout.nextgen.model_gateway import (
    ModelGatewayExecutionError, ModelInferenceCancelled, ModelInferenceRequest,
    ModelInferenceTimeout, PydanticAIStructuredBackend, ScoutModelGateway,
)
from scout.nextgen.model_runtime import ModelRuntimeCapability
from scout.nextgen.openai_compatible_backend import OpenAICompatibleBackendConfig, OpenAICompatiblePydanticBackend
from scout.nextgen.model_qualification import (
    ModelRuntimeQualificationCase, _run_basic_chat_probe, _run_tool_calling_probe,
    TOOL_CALLING_PROBE_NAME, TOOL_CALLING_EVIDENCE_REF, TOOL_CALLING_OUTPUT_MARKER,
)


class Output(BaseModel):
    value: str


class Trace:
    def __init__(self):
        self.events = []
        self.loops = set()
        self.clients = []
        self.lock = threading.Lock()
        self.release = threading.Event()
        self.started = threading.Event()
        self.both_started = threading.Event()
        self.active = 0
        self.max_active = 0

    def record(self, stage):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        with self.lock:
            if loop is not None:
                self.loops.add(loop)
            self.events.append((stage, loop, threading.get_ident(), self.active))

    def cleanup_observed_original_loops(self):
        self.release.set()
        for client in self.clients:
            if not client.is_closed():
                with asyncio.Runner() as runner:
                    runner.run(client.close())
        for loop in self.loops:
            if not loop.is_closed() and not loop.is_running():
                loop.run_until_complete(loop.shutdown_asyncgens())
                loop.run_until_complete(loop.shutdown_default_executor())
                loop.close()


@pytest.fixture
def trace(monkeypatch):
    import openai
    value = Trace()
    original = openai.AsyncOpenAI.__init__
    def traced_init(instance, *args, **kwargs):
        value.record('client_create')
        original(instance, *args, **kwargs)
        value.clients.append(instance)
    monkeypatch.setattr(openai.AsyncOpenAI, '__init__', traced_init)
    yield value
    value.cleanup_observed_original_loops()


class Transport(httpx.AsyncBaseTransport):
    def __init__(self, trace, *, concurrent=False, hold=False, request_error=False, close_error=False):
        self.trace, self.concurrent, self.hold = trace, concurrent, hold
        self.request_error, self.close_error = request_error, close_error

    async def handle_async_request(self, request):
        t = self.trace
        with t.lock:
            t.active += 1
            t.max_active = max(t.max_active, t.active)
            if t.active >= 2:
                t.both_started.set()
        t.record('request')
        t.started.set()
        try:
            if self.concurrent:
                while not t.both_started.is_set():
                    await asyncio.sleep(0.01)
            if self.hold:
                while not t.release.is_set():
                    await asyncio.sleep(0.01)
            if self.request_error:
                raise httpx.ConnectError('fixture transport failed', request=request)
            payload = json.loads(await request.aread())
            tools = payload.get('tools') or []
            names = {tool['function']['name'] for tool in tools}
            tool_result = any(message.get('role') == 'tool' for message in payload.get('messages', []))
            if TOOL_CALLING_PROBE_NAME in names and not tool_result:
                name, arguments = TOOL_CALLING_PROBE_NAME, {'evidence_ref': TOOL_CALLING_EVIDENCE_REF}
            elif tools and TOOL_CALLING_PROBE_NAME not in names:
                name, arguments = tools[0]['function']['name'], {'value': 'fixture'}
            else:
                name, arguments = None, None
            if name:
                message = {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'call-fixture', 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(arguments)}}]}
                finish = 'tool_calls'
            else:
                message = {'role': 'assistant', 'content': TOOL_CALLING_OUTPUT_MARKER if tool_result else 'SCOUT_BASIC_CHAT_OK'}
                finish = 'stop'
            return httpx.Response(200, request=request, json={'id': 'chatcmpl-fixture', 'object': 'chat.completion', 'created': 1, 'model': payload['model'], 'choices': [{'index': 0, 'message': message, 'finish_reason': finish}], 'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}})
        finally:
            with t.lock:
                t.active -= 1
            t.record('request_cleanup')

    async def aclose(self):
        self.trace.record('client_close')
        if self.close_error:
            raise RuntimeError('fixture client close failed')


def config(concurrent=False):
    payload = dict(runtime_id='fixture.model', provider='fixture', model_id='fixture-model', base_url='http://127.0.0.1:1/v1', transport_scope='loopback', tier='local_fast', locality='edge', context_limit_tokens=8192, max_concurrency=1, offline_capable=True, privacy_preserving=True)
    env = {}
    if concurrent:
        payload.update(base_url='https://fixture-model.invalid/v1', transport_scope='remote_https', tier='cloud_reasoning', locality='cloud', max_concurrency=2, offline_capable=False, privacy_preserving=False, api_key_env='SCOUT_FIXTURE_KEY')
        env = {'SCOUT_FIXTURE_KEY': 'fixture-only'}
    return OpenAICompatibleBackendConfig(**payload), env


def backend_for(trace, **transport_options):
    cfg, env = config(transport_options.get('concurrent', False))
    client = httpx.AsyncClient(transport=Transport(trace, **transport_options), trust_env=False)
    return OpenAICompatiblePydanticBackend(config=cfg, environ=env, http_client=client)


def gateway_for(backend):
    return ScoutModelGateway(profiles=(backend.config.to_runtime_profile(),), backends=(backend,), max_local_concurrency=1, max_cloud_concurrency=2)


def infer(gateway, backend, *, timeout=20):
    cfg = backend.config
    session = gateway.open_session(parent_request_id=uuid4(), max_model_requests=10)
    request = ModelInferenceRequest(parent_request_id=session.parent_request_id, task='fixture lifecycle', prompt='Return the fixture typed result.', required_capabilities=frozenset({ModelRuntimeCapability.CHAT, ModelRuntimeCapability.STRUCTURED_OUTPUT}), allowed_tiers=frozenset({cfg.tier}), prefer_local=cfg.locality.value != 'cloud', allow_cloud=cfg.locality.value == 'cloud', requires_offline=cfg.offline_capable, privacy_sensitive=cfg.privacy_preserving, timeout_seconds=timeout)
    result = session.infer(request, output_type=Output)
    assert result.output == Output(value='fixture')
    assert result.execution_record.model_request_count == 1
    assert session.remaining_model_requests == 9
    return result


def assert_one_closed_owner(trace):
    relevant = [event for event in trace.events if event[0] in {'client_create', 'request', 'client_close'}]
    assert relevant and all(event[1] is not None for event in relevant)
    assert len({(event[1], event[2]) for event in relevant}) == 1
    assert all(loop.is_closed() for loop in trace.loops)
    assert not any(event[3] for event in trace.events if event[0] == 'client_close')


def test_resident_client_serial_creation_use_close_share_one_loop(trace):
    backend = backend_for(trace)
    with gateway_for(backend) as gateway:
        infer(gateway, backend)
        first_agents = tuple(map(id, backend._delegate._agents.values()))
        infer(gateway, backend)
        assert tuple(map(id, backend._delegate._agents.values())) == first_agents
        assert len(first_agents) == 1
    assert backend._client.is_closed()
    assert_one_closed_owner(trace)


def test_resident_client_keeps_two_concurrent_requests_on_same_loop(trace):
    backend = backend_for(trace, concurrent=True)
    with gateway_for(backend) as gateway, ThreadPoolExecutor(max_workers=2) as callers:
        futures = [callers.submit(infer, gateway, backend) for _ in range(2)]
        for future in futures:
            future.result(timeout=20)
        assert trace.max_active == 2
        assert gateway.scheduler_snapshots()[1].max_observed_concurrency == 2
        assert len(backend._delegate._agents) == 1
    assert_one_closed_owner(trace)


def test_function_model_gateway_closes_owned_loop_and_keeps_resident_agent(trace):
    async def answer(messages, info):
        trace.record('function_request')
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {'value': 'fixture'})], model_name='fixture-model')
    cfg, _ = config()
    model = FunctionModel(answer)
    backend = PydanticAIStructuredBackend(runtime_id=cfg.runtime_id, model_id=cfg.model_id, model=model)
    backend.config = cfg
    with gateway_for(backend) as gateway:
        infer(gateway, backend)
        first_agents = tuple(map(id, backend._agents.values()))
        infer(gateway, backend)
        assert backend.resident_model is model
        assert tuple(map(id, backend._agents.values())) == first_agents
    assert len(trace.loops) == 1
    assert all(loop.is_closed() for loop in trace.loops)


def test_request_error_closes_client_and_loop_without_hiding_failure(trace):
    backend = backend_for(trace, request_error=True)
    with gateway_for(backend) as gateway:
        with pytest.raises(ModelGatewayExecutionError) as failure:
            infer(gateway, backend)
        assert failure.value.record.model_request_count == 1
    assert_one_closed_owner(trace)


def test_timeout_cancels_owned_http_before_slot_and_client_release(trace):
    backend = backend_for(trace, hold=True)
    with gateway_for(backend) as gateway:
        with pytest.raises(ModelInferenceTimeout):
            infer(gateway, backend, timeout=0.1)
        deadline = time.monotonic() + 2
        while trace.active and time.monotonic() < deadline:
            time.sleep(0.01)
        assert trace.active == 0
        trace.release.set()
        infer(gateway, backend)
    assert_one_closed_owner(trace)


def test_shutdown_cancels_inflight_http_before_closing_client(trace):
    backend = backend_for(trace, hold=True)
    gateway = gateway_for(backend)
    with ThreadPoolExecutor(max_workers=1) as callers:
        future = callers.submit(infer, gateway, backend)
        assert trace.started.wait(10)
        try:
            gateway.close()
            assert trace.active == 0
            with pytest.raises(ModelInferenceCancelled):
                future.result(timeout=10)
        finally:
            trace.release.set()
            gateway.close()
    assert_one_closed_owner(trace)


@pytest.mark.parametrize('tool', [False, True])
def test_qualification_probe_uses_backend_owner_and_same_loop_cleanup(trace, tool):
    backend = backend_for(trace)
    case = ModelRuntimeQualificationCase.from_json_file(Path(__file__).parent / 'fixtures/nextgen/model_runtime_qualification_case.json')
    try:
        with ThreadPoolExecutor(max_workers=1) as callers:
            result = callers.submit(_run_tool_calling_probe if tool else _run_basic_chat_probe, backend, backend.config, case).result(timeout=20)
        assert result.status.value == 'passed'
        assert result.model_request_count == (2 if tool else 1)
        assert result.tool_call_count == (1 if tool else 0)
        assert result.candidate_only is True and result.runtime_safety_truth is False
    finally:
        backend.close()
    assert_one_closed_owner(trace)


def test_owned_loop_preserves_sdk_nested_sync_rejection(trace):
    backend = backend_for(trace)
    cfg = backend.config
    async def outer_response(messages, info):
        return ModelResponse(parts=[ToolCallPart('nested', {})])
    outer = Agent(FunctionModel(outer_response), retries=10)
    @outer.tool_plain
    def nested():
        backend.infer(request=ModelInferenceRequest(parent_request_id=uuid4(), task='nested', prompt='nested', required_capabilities=frozenset({ModelRuntimeCapability.CHAT}), allowed_tiers=frozenset({cfg.tier}), allow_cloud=False, requires_offline=True), output_type=Output, model_request_limit=10, cancellation_event=threading.Event())
        return 'unexpected'
    try:
        with asyncio.Runner() as runner:
            with pytest.raises(Exception) as failure:
                runner.run(outer.run('Use nested.'))
            chain = []
            cause = failure.value
            while cause is not None:
                chain.append(str(cause))
                cause = cause.__cause__
            assert any('cannot be used inside a synchronous tool' in message for message in chain)
        assert not any(event[0] == 'request' for event in trace.events)
    finally:
        backend.close()
    assert_one_closed_owner(trace)


def test_close_failure_is_reported_and_loop_is_still_closed(trace):
    backend = backend_for(trace, close_error=True)
    gateway = gateway_for(backend)
    try:
        infer(gateway, backend)
        with pytest.raises(RuntimeError, match='fixture client close failed'):
            backend.close()
        with pytest.raises(RuntimeError, match='fixture client close failed'):
            backend.close()
    finally:
        try:
            gateway.close()
        except RuntimeError as failure:
            assert str(failure) == 'fixture client close failed'
    assert all(loop.is_closed() for loop in trace.loops)


def test_one_backend_close_error_does_not_leave_other_backend_open(trace):
    first = backend_for(trace, close_error=True)
    cfg, env = config()
    cfg = cfg.model_copy(update={'runtime_id': 'fixture.second'})
    second = OpenAICompatiblePydanticBackend(config=cfg, environ=env, http_client=httpx.AsyncClient(transport=Transport(trace), trust_env=False))
    gateway = ScoutModelGateway(profiles=(first.config.to_runtime_profile(), second.config.to_runtime_profile()), backends=(first, second))
    try:
        with pytest.raises(RuntimeError, match='fixture client close failed'):
            gateway.close()
        assert second._client.is_closed()
        assert len([event for event in trace.events if event[0] == 'client_close']) == 2
        assert all(loop.is_closed() for loop in trace.loops)
    finally:
        second.close()


def test_model_initialization_failure_closes_partial_client_and_owner(trace, monkeypatch):
    import pydantic_ai.models.openai
    def fail_model(*args, **kwargs):
        raise ValueError('fixture model initialization failed')
    monkeypatch.setattr(pydantic_ai.models.openai, 'OpenAIChatModel', fail_model)
    with pytest.raises(ValueError, match='fixture model initialization failed'):
        backend_for(trace)
    assert [event[0] for event in trace.events] == ['client_create', 'client_close']
    assert_one_closed_owner(trace)
