"""Bounded standard-library WebFetch fallback for Pydantic AI capabilities."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
from collections import OrderedDict
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from pydantic_ai import RunContext
from pydantic_ai.exceptions import ModelRetry

DEFAULT_TIMEOUT_SECONDS: float | None = None
DEFAULT_MAX_CONTENT_TOKENS: int | None = None
_MAX_TRACKED_RUNS = 1_024


def _domain_matches(hostname: str, pattern: str) -> bool:
    normalized = pattern.strip().lower().removeprefix("*.")
    return bool(normalized) and (
        hostname == normalized or hostname.endswith(f".{normalized}")
    )


def _validate_url(
    url: str,
    *,
    allowed_domains: list[str] | None,
    blocked_domains: list[str] | None,
) -> None:
    parsed = urlsplit(url)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not hostname:
        raise ValueError("Web fetch URL must use http or https and include a host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Web fetch URL must not contain credentials")
    if not _public_hostname(hostname):
        raise ValueError(f"Web fetch host must be public: {hostname}")
    if blocked_domains and any(
        _domain_matches(hostname, pattern) for pattern in blocked_domains
    ):
        raise ValueError(f"Web fetch host is blocked: {hostname}")
    if allowed_domains and not any(
        _domain_matches(hostname, pattern) for pattern in allowed_domains
    ):
        raise ValueError(f"Web fetch host is not allowed: {hostname}")


def _public_hostname(hostname: str) -> bool:
    normalized = hostname.strip().rstrip(".").casefold()
    if (
        not normalized
        or normalized == "localhost"
        or normalized.endswith((".localhost", ".local", ".internal"))
    ):
        return False
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return True
    return address.is_global


def _fetch_url(
    url: str,
    *,
    allowed_domains: list[str] | None,
    blocked_domains: list[str] | None,
    max_content_tokens: int | None,
    timeout_seconds: float | None,
) -> dict[str, Any]:
    _validate_url(
        url,
        allowed_domains=allowed_domains,
        blocked_domains=blocked_domains,
    )
    request = Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/json,text/plain;q=0.9,*/*;q=0.5",
            "User-Agent": "ScoutAI/1.0 trusted-research-fetch",
        },
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        final_url = response.geturl()
        _validate_url(
            final_url,
            allowed_domains=allowed_domains,
            blocked_domains=blocked_domains,
        )
        if max_content_tokens is None:
            payload = response.read()
            truncated = False
        else:
            max_bytes = max(1, max_content_tokens) * 4
            payload = response.read(max_bytes + 1)
            truncated = len(payload) > max_bytes
            payload = payload[:max_bytes]
        charset = response.headers.get_content_charset() or "utf-8"
        text = payload.decode(charset, errors="replace")
        return {
            "url": final_url,
            "status": getattr(response, "status", 200),
            "content_type": response.headers.get_content_type(),
            "content": text,
            "content_bytes": len(payload),
            "content_hash": "sha256:" + hashlib.sha256(payload).hexdigest(),
            "fetched_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "truncated": truncated,
            "candidate_only": True,
            "runtime_safety_truth": False,
        }


def build_local_web_fetch(
    *,
    allowed_domains: list[str] | None = None,
    blocked_domains: list[str] | None = None,
    max_uses: int = 10,
    max_content_tokens: int | None = DEFAULT_MAX_CONTENT_TOKENS,
    timeout_seconds: float | None = DEFAULT_TIMEOUT_SECONDS,
) -> Any:
    """Return a per-run bounded local fallback accepted by ``WebFetch``."""

    run_counts: OrderedDict[str, int] = OrderedDict()

    async def scout_web_fetch(ctx: RunContext[Any], url: str) -> dict[str, Any]:
        """Fetch a public HTTP(S) URL for trusted Scout research."""

        run_id = str(ctx.run_id)
        current = run_counts.get(run_id, 0)
        if current >= max_uses:
            raise ModelRetry(f"Web fetch use limit reached for this run ({max_uses})")
        run_counts[run_id] = current + 1
        run_counts.move_to_end(run_id)
        while len(run_counts) > _MAX_TRACKED_RUNS:
            run_counts.popitem(last=False)
        try:
            return await asyncio.to_thread(
                _fetch_url,
                url,
                allowed_domains=allowed_domains,
                blocked_domains=blocked_domains,
                max_content_tokens=max_content_tokens,
                timeout_seconds=timeout_seconds,
            )
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            raise ModelRetry(
                "Web fetch request rejected or temporarily unavailable "
                f"({type(exc).__name__})"
            ) from exc

    return scout_web_fetch
