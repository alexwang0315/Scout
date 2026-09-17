from __future__ import annotations

import json
import select
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

import pytest
from pydantic import BaseModel

from scout.nextgen.model_gateway import (
    ModelInferenceCancelled,
    ModelInferenceRequest,
    ScoutModelGateway,
)
from scout.nextgen.model_runtime import ModelRuntimeTier
from scout.nextgen.openai_compatible_backend import (
    OpenAICompatibleBackendConfig,
    OpenAICompatiblePydanticBackend,
)


class _Answer(BaseModel):
    value: str


@contextmanager
def _cancellable_endpoint(*, headers_first: bool):
    started = threading.Event()
    disconnected = threading.Event()
    release = threading.Event()
    requests: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            payload = json.loads(
                self.rfile.read(int(self.headers["Content-Length"]))
            )
            requests.append(payload)
            body = json.dumps(
                {
                    "id": "cancel-probe",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": payload["model"],
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": '{"value":"next-request-ok"}',
                            },
                            "finish_reason": "stop",
                        }
                    ],
                }
            ).encode()
            first_request = len(requests) == 1
            if first_request and headers_first:
                self._headers(len(body))
                self.wfile.flush()
            if first_request:
                started.set()
                while not release.is_set():
                    ready, _, _ = select.select([self.connection], [], [], 0.02)
                    if ready and self.connection.recv(1, socket.MSG_PEEK) == b"":
                        disconnected.set()
                        return
            if not (first_request and headers_first):
                self._headers(len(body))
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                disconnected.set()

        def _headers(self, size: int) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(size))
            self.end_headers()

        def log_message(self, *args) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield (
            f"http://127.0.0.1:{server.server_port}/v1",
            started,
            disconnected,
            release,
            requests,
        )
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _request(parent_id):
    return ModelInferenceRequest(
        parent_request_id=parent_id,
        task="HTTP cancellation qualification",
        prompt="Return a candidate typed value.",
        allowed_tiers=frozenset({ModelRuntimeTier.LOCAL_FAST}),
        requires_offline=True,
        timeout_seconds=20,
    )


@pytest.mark.parametrize("headers_first", [False, True])
def test_cancel_aborts_http_and_releases_single_slot(headers_first: bool) -> None:
    with _cancellable_endpoint(headers_first=headers_first) as endpoint:
        base_url, started, disconnected, release, requests = endpoint
        config = OpenAICompatibleBackendConfig(
            runtime_id="local.cancel.probe",
            provider="openai-compatible-replay",
            model_id="cancel-probe",
            base_url=base_url,
            transport_scope="loopback",
            tier="local_fast",
            locality="edge",
            accelerator="cpu",
            context_limit_tokens=2048,
            max_concurrency=1,
            offline_capable=True,
            privacy_preserving=True,
            structured_output_mode="native",
        )
        backend = OpenAICompatiblePydanticBackend(config=config, environ={})
        with ScoutModelGateway(
            profiles=(config.to_runtime_profile(),),
            backends=(backend,),
            max_local_concurrency=1,
        ) as gateway, ThreadPoolExecutor(max_workers=1) as executor:
            parent_id = uuid4()
            session = gateway.open_session(
                parent_request_id=parent_id, max_model_requests=10
            )
            future = executor.submit(
                session.infer, _request(parent_id), output_type=_Answer
            )
            try:
                assert started.wait(3)
                cancelled_at = time.monotonic()
                session.cancel()
                with pytest.raises(ModelInferenceCancelled):
                    future.result(timeout=2)
                assert time.monotonic() - cancelled_at < 2
                assert disconnected.wait(1), "the HTTP socket remained open"
                assert session.records[-1].status == "cancelled"
                assert session.records[-1].model_request_count == 1

                next_id = uuid4()
                next_session = gateway.open_session(
                    parent_request_id=next_id, max_model_requests=10
                )
                result = next_session.infer(_request(next_id), output_type=_Answer)
                assert result.output.value == "next-request-ok"
                assert result.execution_record.model_request_count == 1
                assert len(requests) == 2
                assert gateway.scheduler_snapshots()[0].max_observed_concurrency == 1
            finally:
                release.set()
