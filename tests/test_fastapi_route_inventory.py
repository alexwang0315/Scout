"""Inventory coverage is checked against actual HTTP and WebSocket dispatch."""
from __future__ import annotations

import pytest
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, WebSocket
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import BaseRoute, Match, Route

from fastapi_route_inventory import registered_route_methods, registered_route_paths, registered_routes


def test_flat_fastapi_and_starlette_routes_keep_exact_http_methods():
    app = FastAPI()

    @app.get("/plain")
    def read():
        return {"ok": True}

    assert registered_route_methods(app, prefix="/plain") == {"/plain": ["GET"]}
    with TestClient(app) as client:
        assert client.get("/plain").status_code == 200
        assert client.post("/plain").status_code == 405

    legacy = Starlette(routes=[Route("/legacy", lambda request: JSONResponse({"ok": True}), methods=["GET"])])
    assert registered_route_methods(legacy) == {"/legacy": ["GET", "HEAD"]}
    with TestClient(legacy) as client:
        assert client.get("/legacy").status_code == client.head("/legacy").status_code == 200
        assert client.post("/legacy").status_code == 405


def test_nested_inclusion_preserves_prefixes_hidden_routes_websocket_and_guard():
    app = FastAPI()
    leaf = APIRouter(prefix="/leaf")

    def guard(x_fixture_admission: str | None = Header(default=None)):
        if x_fixture_admission != "allowed":
            raise HTTPException(status_code=401)

    @leaf.get("/hidden", include_in_schema=False)
    def hidden():
        return {"admitted": True}

    @leaf.websocket("/events")
    async def events(socket: WebSocket):
        await socket.accept()
        await socket.send_json({"event": "fixture"})
        await socket.close()

    parent = APIRouter(prefix="/v1")
    parent.include_router(leaf, prefix="/nested", dependencies=[Depends(guard)])
    app.include_router(parent, prefix="/api")
    expected = {"/api/v1/nested/leaf/hidden": ["GET"], "/api/v1/nested/leaf/events": ["WEBSOCKET"]}
    assert registered_route_methods(app, prefix="/api") == expected
    with TestClient(app) as client:
        assert "/api/v1/nested/leaf/hidden" not in client.get("/openapi.json").json()["paths"]
        assert client.get("/api/v1/nested/leaf/hidden").status_code == 401
        assert client.post("/api/v1/nested/leaf/hidden").status_code == 405
        headers = {"x-fixture-admission": "allowed"}
        assert client.get("/api/v1/nested/leaf/hidden", headers=headers).json() == {"admitted": True}
        with client.websocket_connect("/api/v1/nested/leaf/events", headers=headers) as socket:
            assert socket.receive_json() == {"event": "fixture"}


def test_mounted_application_retains_mount_and_child_routes():
    app, child = FastAPI(), FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @child.get("/value")
    def read():
        return {"value": 1}

    app.mount("/mounted", child)
    assert registered_route_methods(app, prefix="/mounted") == {"/mounted": ["MOUNT"], "/mounted/value": ["GET"]}
    with TestClient(app) as client:
        assert client.get("/mounted/value").json() == {"value": 1}
        assert client.post("/mounted/value").status_code == 405


def test_same_path_different_verbs_are_aggregated_without_overwriting():
    app = FastAPI()
    first, second = APIRouter(), APIRouter()
    first.add_api_route("/shared", lambda: {"method": "POST"}, methods=["POST"])
    second.add_api_route("/shared", lambda: {"method": "GET"}, methods=["GET"])
    app.include_router(first)
    app.include_router(second)
    assert registered_route_methods(app, prefix="/shared") == {"/shared": ["GET", "POST"]}
    with TestClient(app) as client:
        assert client.get("/shared").json() == {"method": "GET"}
        assert client.post("/shared").json() == {"method": "POST"}
        assert client.put("/shared").status_code == 405


@pytest.mark.parametrize("include", [False, True])
def test_duplicate_get_operations_are_rejected_before_set_or_dict_collapse(include):
    app, router = FastAPI(), APIRouter()
    target = router if include else app
    target.add_api_route("/duplicate", lambda: {"route": "first"}, methods=["GET"])
    target.add_api_route("/duplicate", lambda: {"route": "second"}, methods=["GET"])
    if include:
        app.include_router(router, prefix="/prefix")
    path = "/prefix/duplicate" if include else "/duplicate"
    with TestClient(app) as client:
        assert client.get(path).json() == {"route": "first"}
    for inventory in [registered_routes, registered_route_paths, registered_route_methods]:
        with pytest.raises(AssertionError, match="Duplicate registered operation"):
            inventory(app)


def test_duplicate_websocket_operations_are_rejected():
    app, router = FastAPI(), APIRouter()
    async def events(socket: WebSocket):
        await socket.accept()
        await socket.close()
    router.add_api_websocket_route("/events", events)
    router.add_api_websocket_route("/events", events)
    app.include_router(router)
    with pytest.raises(AssertionError, match="Duplicate registered operation"):
        registered_route_paths(app)


@pytest.mark.parametrize("include", [False, True])
def test_unknown_routes_fail_closed_even_inside_an_included_router(include):
    class UnknownRoute(BaseRoute):
        path = "/unknown"
        def matches(self, scope):
            return Match.NONE, {}
        async def handle(self, scope, receive, send):
            raise AssertionError("Unknown route must not execute")

    app, router = FastAPI(), APIRouter()
    if include:
        router.routes.append(UnknownRoute())
        app.include_router(router)
    else:
        app.routes.append(UnknownRoute())
    with pytest.raises(AssertionError, match="Unsupported registered route type: UnknownRoute"):
        registered_route_paths(app)
