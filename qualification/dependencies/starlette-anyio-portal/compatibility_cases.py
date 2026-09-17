"""Behavioral compatibility for the isolated Starlette portal backport.

Run unchanged against the original package (warning retained) and candidate
(-W error). No warning filters, import monkeypatching, or network are used.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, nullcontext
from contextvars import ContextVar
import threading

import anyio
import pytest
from fastapi import FastAPI, Request, WebSocket
from pydantic import BaseModel
from starlette.background import BackgroundTask
from starlette.responses import JSONResponse, RedirectResponse, StreamingResponse
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

context_value = ContextVar("compat_value", default="unset")


class Payload(BaseModel):
    value: int


@pytest.fixture
def service():
    events = []
    state = {}

    @asynccontextmanager
    async def lifespan(app):
        state["portal_thread"] = threading.get_ident()
        events.append("startup")
        yield {"token": "lifespan-state"}
        events.append("shutdown")

    app = FastAPI(lifespan=lifespan)

    @app.get("/info")
    async def info(request: Request):
        return {
            "thread": threading.get_ident(),
            "context": context_value.get(),
            "state": getattr(request.state, "token", None),
            "root_path": request.scope["root_path"],
            "header": request.headers.get("x-probe"),
            "cookie": request.cookies.get("probe"),
        }

    @app.get("/sync")
    def sync_endpoint():
        return {"thread": threading.get_ident(), "context": context_value.get()}

    @app.post("/json")
    async def json_endpoint(payload: Payload):
        return {"value": payload.value + 1}

    @app.post("/body")
    async def body_endpoint(request: Request):
        return {"body": (await request.body()).decode()}

    @app.get("/redirect")
    async def redirect():
        return RedirectResponse("/info", status_code=307)

    @app.get("/explode")
    async def explode():
        raise RuntimeError("request-compat-failure")

    @app.get("/stream/{kind}")
    async def stream(kind: str):
        async def async_chunks():
            for chunk in (b"alpha\n", b"beta\n"):
                await anyio.sleep(0)
                yield chunk

        def sync_chunks():
            yield b"alpha\n"
            yield b"beta\n"

        return StreamingResponse(
            async_chunks() if kind == "async" else sync_chunks(),
            media_type="text/plain",
        )

    @app.get("/background/{kind}")
    async def background(kind: str):
        def sync_background():
            events.append("background-sync")

        async def async_background():
            await anyio.sleep(0)
            events.append("background-async")

        return JSONResponse(
            {"queued": True},
            background=BackgroundTask(async_background if kind == "async" else sync_background),
        )

    @app.get("/background-error")
    async def background_error():
        def fail():
            raise RuntimeError("background-compat-failure")

        return JSONResponse({"queued": True}, background=BackgroundTask(fail))

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        await websocket.accept()
        payload = await websocket.receive_json()
        await websocket.send_json({"echo": payload, "thread": threading.get_ident()})
        await websocket.close(code=1000)

    return app, events, state


@pytest.mark.parametrize("in_context", [False, True])
def test_api_without_and_with_lifespan_headers_cookies_validation(service, in_context):
    app, events, state = service
    client = TestClient(app, headers={"x-probe": "header-value"}, cookies={"probe": "cookie-value"})
    try:
        with client if in_context else nullcontext(client):
            reply = client.get("/info")
            assert reply.status_code == 200
            data = reply.json()
            assert data["header"] == "header-value"
            assert data["cookie"] == "cookie-value"
            assert data["state"] == ("lifespan-state" if in_context else None)
            assert client.post("/json", json={"value": 4}).json() == {"value": 5}
            assert client.post("/json", json={"value": "not-an-int"}).status_code == 422
            assert events == (["startup"] if in_context else [])
    finally:
        client.close()
    assert events == (["startup", "shutdown"] if in_context else [])
    assert client.portal is None


def test_root_path_and_redirect_control(service):
    app, _, _ = service
    with TestClient(app, root_path="/prefix") as client:
        assert client.get("/info").json()["root_path"] == "/prefix"
        assert client.get("/redirect", follow_redirects=False).status_code == 307
        reply = client.get("/redirect")
        assert reply.status_code == 200
        assert len(reply.history) == 1


def test_context_threadpool_and_shared_portal_concurrent_requests(service):
    app, events, state = service
    token = context_value.set("from-caller")
    try:
        with TestClient(app) as client:
            info = client.get("/info").json()
            sync = client.get("/sync").json()
            assert info["thread"] == state["portal_thread"]
            assert info["context"] == sync["context"] == "from-caller"
            assert sync["thread"] != state["portal_thread"]
            assert state["portal_thread"] != threading.get_ident()
            with ThreadPoolExecutor(max_workers=4) as pool:
                replies = list(pool.map(lambda n: client.post("/json", json={"value": n}), range(24)))
            assert [r.json()["value"] for r in replies] == list(range(1, 25))
            assert all(r.status_code == 200 for r in replies)
        assert events == ["startup", "shutdown"]
        assert client.portal is None
        assert client.task.done()
        assert not any(t.ident == state["portal_thread"] and t.is_alive() for t in threading.enumerate())
    finally:
        context_value.reset(token)


@pytest.mark.parametrize("kind", ["sync", "async"])
def test_stream_body_is_delivered_and_client_recovers(service, kind):
    app, _, _ = service
    with TestClient(app) as client:
        with client.stream("GET", f"/stream/{kind}") as reply:
            assert reply.status_code == 200
            assert b"".join(reply.iter_bytes()) == b"alpha\nbeta\n"
        assert client.get("/info").status_code == 200


def test_request_stream_generator(service):
    app, _, _ = service
    with TestClient(app) as client:
        reply = client.post("/body", content=iter([b"first-", b"second"]))
        assert reply.status_code == 200
        assert reply.json() == {"body": "first-second"}


@pytest.mark.parametrize("kind", ["sync", "async"])
def test_background_tasks_finish_before_return(service, kind):
    app, events, _ = service
    with TestClient(app) as client:
        assert client.get(f"/background/{kind}").json() == {"queued": True}
        assert events == ["startup", f"background-{kind}"]
    assert events[-1] == "shutdown"


@pytest.mark.parametrize("raise_server_exceptions", [True, False])
def test_request_exception_contract_and_next_request(service, raise_server_exceptions):
    app, _, _ = service
    with TestClient(app, raise_server_exceptions=raise_server_exceptions) as client:
        if raise_server_exceptions:
            with pytest.raises(RuntimeError, match="request-compat-failure"):
                client.get("/explode")
        else:
            response = client.get("/explode")
            assert response.status_code == 500
            assert response.text == "Internal Server Error"
        assert client.get("/info").status_code == 200


def test_background_exception_propagates_without_breaking_next_request(service):
    app, _, _ = service
    with TestClient(app) as client:
        with pytest.raises(RuntimeError, match="background-compat-failure"):
            client.get("/background-error")
        assert client.get("/info").status_code == 200


@pytest.mark.parametrize("phase", ["startup", "shutdown"])
def test_lifespan_failure_propagates_and_portal_cleans_up(phase):
    events = []

    @asynccontextmanager
    async def lifespan(app):
        events.append("startup")
        if phase == "startup":
            raise RuntimeError("lifespan-startup")
        yield
        events.append("shutdown")
        raise RuntimeError("lifespan-shutdown")

    app = FastAPI(lifespan=lifespan)
    client = TestClient(app)
    with pytest.raises(RuntimeError, match=f"lifespan-{phase}"):
        with client:
            assert events == ["startup"]
    assert client.portal is None
    assert events == (["startup"] if phase == "startup" else ["startup", "shutdown"])
    client.close()


def test_websocket_bidirectional_json_and_close(service):
    app, _, state = service
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"number": 7})
            assert ws.receive_json() == {"echo": {"number": 7}, "thread": state["portal_thread"]}
            with pytest.raises(WebSocketDisconnect) as raised:
                ws.receive_json()
            assert raised.value.code == 1000


def test_asgi2_request_wrapper_without_lifespan():
    class ASGI2:
        def __init__(self, scope):
            self.scope = scope

        async def __call__(self, receive, send):
            assert self.scope["type"] == "http"
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"asgi2-ok"})

    client = TestClient(ASGI2)
    try:
        assert client.get("/").text == "asgi2-ok"
    finally:
        client.close()
