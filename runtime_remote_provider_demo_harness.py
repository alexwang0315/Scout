from __future__ import annotations

import hashlib
import json
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterator


@dataclass(frozen=True)
class LocalWebhookCapturedRequest:
    method: str
    path: str
    headers: dict[str, str]
    body_json: Any
    body_hash: str
    provider_message_ref: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LocalWebhookDemoHarness:
    def __init__(self, *, host: str = "127.0.0.1", port: int = 0) -> None:
        self.host = host
        self.port = port
        self._server: _LocalWebhookHttpServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._captures: list[LocalWebhookCapturedRequest] = []

    @property
    def url(self) -> str:
        return self.webhook_url()

    @property
    def captured_requests(self) -> list[LocalWebhookCapturedRequest]:
        with self._lock:
            return list(self._captures)

    @property
    def capture_count(self) -> int:
        with self._lock:
            return len(self._captures)

    def webhook_url(self, path: str = "/webhook") -> str:
        if self._server is None:
            raise RuntimeError("local webhook demo harness is not running")
        normalized_path = path if path.startswith("/") else f"/{path}"
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}{normalized_path}"

    def start(self) -> "LocalWebhookDemoHarness":
        if self._server is not None:
            return self
        self._server = _LocalWebhookHttpServer((self.host, self.port), self)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="scout-local-webhook-demo-harness",
            daemon=True,
        )
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._server is None:
            return
        server = self._server
        thread = self._thread
        self._server = None
        self._thread = None
        server.shutdown()
        server.server_close()
        if thread is not None:
            thread.join(timeout=2)

    def _capture(
        self,
        *,
        method: str,
        path: str,
        headers: dict[str, str],
        body_json: Any,
    ) -> LocalWebhookCapturedRequest:
        body_hash = _canonical_json_hash(body_json)
        with self._lock:
            provider_message_ref = (
                f"local-webhook-demo-{len(self._captures) + 1:04d}-"
                f"{body_hash[:12]}"
            )
            captured = LocalWebhookCapturedRequest(
                method=method,
                path=path,
                headers=headers,
                body_json=body_json,
                body_hash=body_hash,
                provider_message_ref=provider_message_ref,
            )
            self._captures.append(captured)
            return captured


@contextmanager
def run_local_webhook_demo_harness(
    *, host: str = "127.0.0.1", port: int = 0
) -> Iterator[LocalWebhookDemoHarness]:
    harness = LocalWebhookDemoHarness(host=host, port=port).start()
    try:
        yield harness
    finally:
        harness.stop()


class _LocalWebhookHttpServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        harness: LocalWebhookDemoHarness,
    ) -> None:
        self.harness = harness
        super().__init__(server_address, _LocalWebhookRequestHandler)


class _LocalWebhookRequestHandler(BaseHTTPRequestHandler):
    server: _LocalWebhookHttpServer

    def do_GET(self) -> None:
        self._write_json_response(
            405,
            {"status": "method_not_allowed", "allowed_methods": ["POST"]},
        )

    def do_PUT(self) -> None:
        self._write_json_response(
            405,
            {"status": "method_not_allowed", "allowed_methods": ["POST"]},
        )

    def do_DELETE(self) -> None:
        self._write_json_response(
            405,
            {"status": "method_not_allowed", "allowed_methods": ["POST"]},
        )

    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", "0"))
        body_bytes = self.rfile.read(content_length)
        try:
            body_json = json.loads(body_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._write_json_response(
                400,
                {"status": "invalid_json", "provider_message_ref": None},
            )
            return

        captured = self.server.harness._capture(
            method="POST",
            path=self.path,
            headers={key: value for key, value in self.headers.items()},
            body_json=body_json,
        )
        self._write_json_response(
            202,
            {
                "status": "captured",
                "provider_message_ref": captured.provider_message_ref,
                "body_hash": captured.body_hash,
                "captured_count": self.server.harness.capture_count,
            },
        )

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _write_json_response(self, status_code: int, payload: dict[str, Any]) -> None:
        response_bytes = (
            json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
        ).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_bytes)))
        self.end_headers()
        self.wfile.write(response_bytes)


def _canonical_json_hash(payload: Any) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
