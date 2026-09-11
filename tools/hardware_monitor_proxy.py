"""Read-only Dashboard proxy for the Scout hardware monitor API.

The browser is intentionally kept on the Dashboard origin.  This adapter is
the only place in the Dashboard process that knows the temporary local Scout
upstream at 127.0.0.1:9151; it forwards JSON responses, including a stale 503,
without turning telemetry into a control surface.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

HARDWARE_MONITOR_UPSTREAM = "http://127.0.0.1:9151"
HARDWARE_MONITOR_PROXY_PREFIX = "/admin/dashboard/scout-monitor"
HARDWARE_MONITOR_TIMEOUT_SECONDS = 8.0
HARDWARE_MONITOR_MAX_RESPONSE_BYTES = 2 * 1024 * 1024

HardwareMonitorFetcher = Callable[[str, Mapping[str, str]], tuple[int, Any]]
_ENDPOINTS = frozenset(
    f"/api/v1/hardware-monitor/{kind}" for kind in ("status", "history", "events")
)


class HardwareMonitorUpstreamError(RuntimeError):
    """A typed, non-secret error while reading the fixed Scout upstream."""


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HardwareMonitorUpstreamError("hardware monitor redirect refused")


def _reject_nonfinite_json(value: str) -> None:
    raise ValueError("non-finite JSON number")


def _read_response_body(response: Any) -> bytes:
    body = response.read(HARDWARE_MONITOR_MAX_RESPONSE_BYTES + 1)
    if len(body) > HARDWARE_MONITOR_MAX_RESPONSE_BYTES:
        raise HardwareMonitorUpstreamError("hardware monitor response is too large")
    return body


def _decode_json(body: bytes) -> Any:
    try:
        payload = json.loads(body.decode("utf-8"), parse_constant=_reject_nonfinite_json)
        if not isinstance(payload, dict):
            raise ValueError("JSON response must be an object")
        return payload
    except (UnicodeDecodeError, ValueError) as exc:
        raise HardwareMonitorUpstreamError(
            "hardware monitor upstream returned invalid JSON"
        ) from exc


def fetch_hardware_monitor_json(
    endpoint: str,
    params: Mapping[str, str],
    *,
    upstream_base_url: str = HARDWARE_MONITOR_UPSTREAM,
) -> tuple[int, Any]:
    """GET one allow-listed hardware-monitor endpoint and decode its JSON."""

    if endpoint not in _ENDPOINTS:
        raise HardwareMonitorUpstreamError("hardware monitor endpoint refused")
    url = f"{upstream_base_url.rstrip('/')}{endpoint}"
    query = urlencode(dict(params))
    if query:
        url = f"{url}?{query}"
    request = Request(
        url,
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        # Do not let ambient proxy settings or redirects change the fixed upstream.
        opener = build_opener(ProxyHandler({}), _NoRedirects())
        with opener.open(request, timeout=HARDWARE_MONITOR_TIMEOUT_SECONDS) as response:
            status_code = int(response.getcode())
            return status_code, _decode_json(_read_response_body(response))
    except HTTPError as exc:
        try:
            body = _read_response_body(exc)
        except (OSError, HardwareMonitorUpstreamError) as body_exc:
            raise HardwareMonitorUpstreamError(
                "hardware monitor upstream error response was unreadable"
            ) from body_exc
        finally:
            exc.close()
        return int(exc.code), _decode_json(body)
    except (OSError, URLError, TimeoutError) as exc:
        raise HardwareMonitorUpstreamError(
            "hardware monitor upstream is unavailable"
        ) from exc


def _server_time() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _unavailable_payload(*, kind: str, limit: int | None = None) -> dict[str, Any]:
    meta: dict[str, Any] | None = None
    if limit is not None:
        meta = {
            "limit": limit,
            "count": 0,
            "order": "oldest_first",
            "has_more": False,
            "scan_truncated": False,
            "skipped_invalid_records": 0,
        }
    payload: dict[str, Any] = {
        "schema_version": "scout.hardware-monitor.api.v1",
        "server_time": _server_time(),
        "status": "unavailable",
        "summary": "無法連線至 Scout 硬體監控 API",
        "read_only": True,
    }
    if kind == "status":
        payload.update(
            {
                "freshness": {
                    "state": "unreadable",
                    "captured_at": None,
                    "age_seconds": None,
                    "sample_interval_seconds": 60,
                    "stale_after_seconds": 150,
                },
                "data": None,
                "next_steps": ["確認 Scout API 與本機 SSH 轉接是否仍在執行"],
            }
        )
    else:
        payload.update({"items": [], "meta": meta})
    return payload


def create_hardware_monitor_proxy_router(
    *,
    prefix: str = HARDWARE_MONITOR_PROXY_PREFIX,
    upstream_base_url: str = HARDWARE_MONITOR_UPSTREAM,
    fetcher: HardwareMonitorFetcher | None = None,
) -> APIRouter:
    """Create fixed GET-only proxy routes under the Dashboard monitor page."""

    resolved_fetcher = fetcher
    if resolved_fetcher is None:

        def resolved_fetcher(endpoint: str, params: Mapping[str, str]) -> tuple[int, Any]:
            return fetch_hardware_monitor_json(
                endpoint,
                params,
                upstream_base_url=upstream_base_url,
            )

    router = APIRouter(prefix=prefix, tags=["hardware-monitor-proxy"])

    def proxy(endpoint: str, *, kind: str, limit: int | None = None) -> JSONResponse:
        params = {} if limit is None else {"limit": str(limit)}
        try:
            upstream_status, payload = resolved_fetcher(endpoint, params)
        except HardwareMonitorUpstreamError:
            return JSONResponse(
                status_code=503,
                content=_unavailable_payload(kind=kind, limit=limit),
                headers={"Cache-Control": "no-store"},
            )
        return JSONResponse(
            status_code=upstream_status,
            content=payload,
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/api/v1/hardware-monitor/status")
    def status() -> JSONResponse:
        return proxy("/api/v1/hardware-monitor/status", kind="status")

    @router.get("/api/v1/hardware-monitor/history")
    def history(limit: int = Query(default=60, ge=1, le=1440)) -> JSONResponse:
        return proxy(
            "/api/v1/hardware-monitor/history",
            kind="history",
            limit=limit,
        )

    @router.get("/api/v1/hardware-monitor/events")
    def events(limit: int = Query(default=50, ge=1, le=200)) -> JSONResponse:
        return proxy(
            "/api/v1/hardware-monitor/events",
            kind="events",
            limit=limit,
        )

    return router


__all__ = [
    "HARDWARE_MONITOR_PROXY_PREFIX",
    "HARDWARE_MONITOR_TIMEOUT_SECONDS",
    "HARDWARE_MONITOR_UPSTREAM",
    "HardwareMonitorFetcher",
    "HardwareMonitorUpstreamError",
    "create_hardware_monitor_proxy_router",
    "fetch_hardware_monitor_json",
]
