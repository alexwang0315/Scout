"""Bounded DuckDuckGo WebSearch fallback for Pydantic AI capabilities."""

from __future__ import annotations

import asyncio
import base64
import binascii
from collections import OrderedDict
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

from pydantic_ai import RunContext
from pydantic_ai.exceptions import ModelRetry

from scout.agents.local_web_fetch import _domain_matches


DEFAULT_MAX_RESULTS = 8
DEFAULT_DDGS_FALLBACK_TIMEOUT_SECONDS = 5.0
DEFAULT_SEARCH_REGION = "tw-tzh"
DEFAULT_SEARCH_TIMEOUT_SECONDS = 15.0
DEFAULT_TEXT_BACKENDS = (
    "google,brave,duckduckgo,mojeek,yahoo,startpage,yandex"
)
_MAX_TRACKED_RUNS = 1_024


def _unwrap_bing_url(url: str) -> str:
    parts = urlsplit(url)
    if not _domain_matches((parts.hostname or "").lower(), "bing.com"):
        return url
    encoded = parse_qs(parts.query).get("u", [""])[0]
    if not encoded.startswith("a1"):
        return url
    payload = encoded[2:]
    payload += "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return url
    target = urlsplit(decoded)
    if target.scheme not in {"http", "https"} or not target.hostname:
        return url
    return decoded


class _BingResultParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._in_result = False
        self._in_heading = False
        self._url = ""
        self._title_parts: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        values = dict(attrs)
        if tag == "li" and "b_algo" in (values.get("class") or "").split():
            self._in_result = True
        elif self._in_result and tag == "h2":
            self._in_heading = True
        elif self._in_heading and tag == "a":
            self._url = _unwrap_bing_url(str(values.get("href") or ""))
            self._title_parts = []

    def handle_data(self, data: str) -> None:
        if self._url:
            self._title_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._url:
            title = " ".join("".join(self._title_parts).split())
            self.results.append(
                {"title": title, "url": self._url, "snippet": title}
            )
            self._url = ""
            self._title_parts = []
        elif tag == "h2":
            self._in_heading = False
        elif tag == "li":
            self._in_result = False


def _bing_search(
    query: str,
    *,
    max_results: int,
    timeout_seconds: float,
) -> list[dict[str, str]]:
    url = "https://www.bing.com/search?" + urlencode(
        {"q": query, "count": max(10, max_results)}
    )
    request = Request(
        url,
        headers={
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.7",
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 "
                "Chrome/124 Safari/537.36"
            ),
        },
    )
    with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
        body = response.read(2_000_000).decode("utf-8", errors="replace")
    parser = _BingResultParser()
    parser.feed(body)
    return parser.results[:max_results]


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
    timeout_seconds: float = DEFAULT_SEARCH_TIMEOUT_SECONDS,
) -> list[dict[str, str]]:
    from ddgs import DDGS

    try:
        bing_results = _bing_search(
            _search_query(
                query,
                allowed_domains=allowed_domains,
                blocked_domains=blocked_domains,
            ),
            max_results=max_results,
            timeout_seconds=timeout_seconds,
        )
    except (OSError, TimeoutError):
        bing_results = []
    filtered_bing_results = [
        result
        for result in bing_results
        if _result_allowed(
            result["url"],
            allowed_domains=allowed_domains,
            blocked_domains=blocked_domains,
        )
    ]
    if filtered_bing_results:
        return filtered_bing_results

    client = DDGS(
        timeout=min(timeout_seconds, DEFAULT_DDGS_FALLBACK_TIMEOUT_SECONDS)
    )
    results = client.text(
        _search_query(
            query,
            allowed_domains=None,
            blocked_domains=blocked_domains,
        ),
        max_results=max_results,
        region=DEFAULT_SEARCH_REGION,
        backend=DEFAULT_TEXT_BACKENDS,
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
    timeout_seconds: float = DEFAULT_SEARCH_TIMEOUT_SECONDS,
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
        try:
            return await asyncio.to_thread(
                _search,
                query,
                allowed_domains=allowed_domains,
                blocked_domains=blocked_domains,
                max_results=max_results,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            # DDGS provider failures are recoverable evidence-path failures. Surface
            # them to the model as a retry instead of aborting the whole agent run.
            from ddgs.exceptions import DDGSException

            if isinstance(exc, DDGSException):
                raise ModelRetry(
                    f"Web search backend temporarily unavailable ({type(exc).__name__})"
                ) from exc
            raise

    return scout_web_search
