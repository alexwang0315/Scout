"""Complete route inventory for flat and lazily included FastAPI routers."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import fastapi.routing
from starlette.routing import Mount, Route, WebSocketRoute

_INCLUDED_ROUTER = getattr(fastapi.routing, "_IncludedRouter", ())


@dataclass(frozen=True)
class RegisteredRoute:
    path: str
    methods: frozenset[str]
    kind: str


def _walk(routes, prefix=""):
    for route in routes:
        if isinstance(route, _INCLUDED_ROUTER):
            # FastAPI's include context combines prefixes by concatenation and
            # path_for adds that prefix to each original path. Walk originals so
            # an unsupported included child cannot disappear from the inventory.
            yield from _walk(route.original_router.routes, prefix + route.include_context.prefix)
        elif isinstance(route, Mount):
            path = prefix + route.path
            yield RegisteredRoute(path, frozenset(), "mount")
            yield from _walk(route.routes, path)
        elif isinstance(route, Route):
            yield RegisteredRoute(prefix + route.path, frozenset(route.methods or {"*"}), "http")
        elif isinstance(route, WebSocketRoute):
            yield RegisteredRoute(prefix + route.path, frozenset(), "websocket")
        else:
            raise AssertionError(f"Unsupported registered route type: {type(route).__name__}")


def registered_routes(app) -> tuple[RegisteredRoute, ...]:
    """Preserve every route; reject duplicate operations before maps/sets hide them."""
    rows = tuple(_walk(app.routes))
    seen = defaultdict(set)
    for row in rows:
        operations = row.methods if row.kind == "http" else {row.kind.upper()}
        previous = seen[(row.kind, row.path)]
        overlap = previous & operations
        if overlap or (previous and ("*" in previous or "*" in operations)):
            raise AssertionError(f"Duplicate registered operation at {row.path}: {sorted(previous | operations)}")
        previous.update(operations)
    return rows


def registered_route_paths(app) -> set[str]:
    return {row.path for row in registered_routes(app)}


def registered_route_methods(app, *, prefix="") -> dict[str, list[str]]:
    methods = defaultdict(set)
    for row in registered_routes(app):
        if row.path.startswith(prefix):
            methods[row.path].update(row.methods if row.kind == "http" else {row.kind.upper()})
    return {path: sorted(verbs) for path, verbs in sorted(methods.items())}
