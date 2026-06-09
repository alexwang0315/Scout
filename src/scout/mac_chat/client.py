"""HTTP client for the Mac Scout AI chat proxy."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


DEFAULT_SCOUT_SERVER_URL = "http://scout.local:9120"

UrlOpen = Callable[..., Any]


@dataclass(frozen=True)
class ScoutServerResult:
    ok: bool
    status_code: int | None
    payload: dict[str, Any] | None
    error: str | None
    elapsed_ms: int


class ScoutServerClient:
    """Small JSON-only client for a Scout AI OS FastAPI server."""

    def __init__(
        self,
        base_url: str = DEFAULT_SCOUT_SERVER_URL,
        *,
        timeout_seconds: float = 8.0,
        urlopen_func: UrlOpen = urlopen,
    ) -> None:
        self.base_url = normalize_server_url(base_url)
        self.timeout_seconds = timeout_seconds
        self._urlopen = urlopen_func

    def capabilities(self) -> ScoutServerResult:
        return self.request_json("GET", "/capabilities")

    def create_request(
        self,
        *,
        user_id: str,
        user_text: str,
        active_context: dict[str, Any],
    ) -> ScoutServerResult:
        return self.request_json(
            "POST",
            "/requests",
            {
                "user_id": user_id,
                "user_text": user_text,
                "active_context": active_context,
            },
        )

    def request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> ScoutServerResult:
        start = time.monotonic()
        url = urljoin(f"{self.base_url}/", path.lstrip("/"))
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(url, data=body, headers=headers, method=method.upper())
        try:
            with self._urlopen(request, timeout=self.timeout_seconds) as response:
                status_code = int(getattr(response, "status", 200))
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            return ScoutServerResult(
                ok=False,
                status_code=exc.code,
                payload=_decode_error_payload(exc),
                error=f"Scout server returned HTTP {exc.code}",
                elapsed_ms=_elapsed_ms(start),
            )
        except (OSError, URLError, TimeoutError) as exc:
            return ScoutServerResult(
                ok=False,
                status_code=None,
                payload=None,
                error=f"Scout server unavailable: {_safe_error(exc)}",
                elapsed_ms=_elapsed_ms(start),
            )

        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return ScoutServerResult(
                ok=False,
                status_code=status_code,
                payload=None,
                error="Scout server returned non-JSON response",
                elapsed_ms=_elapsed_ms(start),
            )
        if not isinstance(parsed, dict):
            return ScoutServerResult(
                ok=False,
                status_code=status_code,
                payload=None,
                error="Scout server returned a JSON value that is not an object",
                elapsed_ms=_elapsed_ms(start),
            )
        return ScoutServerResult(
            ok=200 <= status_code < 300,
            status_code=status_code,
            payload=parsed,
            error=None if 200 <= status_code < 300 else f"HTTP {status_code}",
            elapsed_ms=_elapsed_ms(start),
        )


def normalize_server_url(value: str | None) -> str:
    candidate = (value or DEFAULT_SCOUT_SERVER_URL).strip().rstrip("/")
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Scout server URL must be an http(s) URL")
    return candidate


def _decode_error_payload(exc: HTTPError) -> dict[str, Any] | None:
    try:
        raw = exc.read().decode("utf-8")
        parsed = json.loads(raw) if raw else None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _safe_error(exc: BaseException) -> str:
    message = str(exc).strip()
    return message or exc.__class__.__name__


def _elapsed_ms(start: float) -> int:
    return max(0, round((time.monotonic() - start) * 1000))


__all__ = [
    "DEFAULT_SCOUT_SERVER_URL",
    "ScoutServerClient",
    "ScoutServerResult",
    "normalize_server_url",
]
