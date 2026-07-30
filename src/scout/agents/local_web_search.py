"""Bounded DuckDuckGo WebSearch fallback for Pydantic AI capabilities."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from typing import Any
from urllib.parse import urlsplit

from pydantic_ai import RunContext
from pydantic_ai.exceptions import ModelRetry

from scout.agents.local_web_fetch import _domain_matches


DEFAULT_MAX_RESULTS = 8
_MAX_TRACKED_RUNS = 1_024


def _search_query(
    query: str,
    *,
    allowed_domains: list[str] | None,
    blocked_domains: list[str] | None,
) -> str:
    terms = [query.strip()]
    if allowed_domains:
        allowed = " OR ".join(
            f"site:{domain.strip().removeprefix('*.')}"
            for domain in allowed_domains
            if domain.strip().removeprefix("*.")
        )
        if allowed:
            terms.append(f"({allowed})")
    if blocked_domains:
        terms.extend(
            f"-site:{domain.strip().removeprefix('*.')}"
            for domain in blocked_domains
            if domain.strip().removeprefix("*.")
        )
    return " ".join(terms)


def _result_allowed(
    url: str,
    *,
    allowed_domains: list[str] | None,
    blocked_domains: list[str] | None,
) -> bool:
    hostname = (urlsplit(url).hostname or "").lower()
    if not hostname:
        return False
    if blocked_domains and any(
        _domain_matches(hostname, pattern) for pattern in blocked_domains
    ):
        return False
    return not allowed_domains or any(
        _domain_matches(hostname, pattern) for pattern in allowed_domains
    )


def _search(
    query: str,
    *,
    allowed_domains: list[str] | None,
    blocked_domains: list[str] | None,
    max_results: int,
) -> list[dict[str, str]]:
    from ddgs import DDGS

    results = DDGS().text(
        _search_query(
            query,
            allowed_domains=allowed_domains,
            blocked_domains=blocked_domains,
        ),
        max_results=max_results,
    )
    normalized: list[dict[str, str]] = []
    for result in results:
        url = str(result.get("href") or result.get("url") or "")
        if not _result_allowed(
            url,
            allowed_domains=allowed_domains,
            blocked_domains=blocked_domains,
        ):
            continue
        normalized.append(
            {
                "title": str(result.get("title") or ""),
                "url": url,
                "snippet": str(result.get("body") or result.get("snippet") or ""),
            }
        )
    return normalized


def build_local_web_search(
    *,
    allowed_domains: list[str] | None = None,
    blocked_domains: list[str] | None = None,
    max_uses: int = 10,
    max_results: int = DEFAULT_MAX_RESULTS,
) -> Any:
    """Return a per-run bounded local fallback accepted by ``WebSearch``."""

    run_counts: OrderedDict[str, int] = OrderedDict()

    async def scout_web_search(
        ctx: RunContext[Any],
        query: str,
    ) -> list[dict[str, str]]:
        """Search public web pages for trusted Scout candidate research."""

        run_id = str(ctx.run_id)
        current = run_counts.get(run_id, 0)
        if current >= max_uses:
            raise ModelRetry(f"Web search use limit reached for this run ({max_uses})")
        run_counts[run_id] = current + 1
        run_counts.move_to_end(run_id)
        while len(run_counts) > _MAX_TRACKED_RUNS:
            run_counts.popitem(last=False)
        return await asyncio.to_thread(
            _search,
            query,
            allowed_domains=allowed_domains,
            blocked_domains=blocked_domains,
            max_results=max_results,
        )

    return scout_web_search
