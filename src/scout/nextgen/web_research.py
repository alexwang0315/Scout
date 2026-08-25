"""Bounded live web tools for candidate-only Praison research specialists."""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit, urlunsplit

from pydantic import Field

from scout.nextgen.intelligence_gateway import (
    IntelligenceRequest,
    IntelligenceTaskType,
    Uncertainty,
    WebEvidenceProvenance,
    WebResearchScope,
)
from scout.schemas.base import NonEmptyStr, SchemaModel

SEARCH_PROVIDER = "scout-bounded-web-search"


class CapabilityRecorder(Protocol):
    def __call__(self, capability: str) -> None: ...


class WebSearchBackend(Protocol):
    def __call__(
        self,
        query: str,
        **kwargs: Any,
    ) -> Sequence[Mapping[str, Any]]: ...


class WebFetchBackend(Protocol):
    def __call__(self, url: str, **kwargs: Any) -> Mapping[str, Any]: ...


class WebSearchHit(SchemaModel):
    title: NonEmptyStr
    url: NonEmptyStr
    snippet: str = ""
    rank: int = Field(ge=1)


class WebResearchArtifact(SchemaModel):
    evidence_id: NonEmptyStr
    source_ref: NonEmptyStr
    content_hash: NonEmptyStr
    summary: NonEmptyStr
    generated_at: datetime
    web: WebEvidenceProvenance
    attributes: dict[str, Any] = Field(default_factory=dict)


class WebResearchRun(SchemaModel):
    query: NonEmptyStr
    artifacts: tuple[WebResearchArtifact, ...] = ()
    uncertainties: tuple[Uncertainty, ...] = ()
    search_result_count: int = Field(default=0, ge=0)
    fetch_attempt_count: int = Field(default=0, ge=0)
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


class BoundedLiveWebResearchTools:
    """Search and fetch public pages inside a request-owned capability scope."""

    def __init__(
        self,
        *,
        search_backend: WebSearchBackend | None = None,
        fetch_backend: WebFetchBackend | None = None,
    ) -> None:
        self._search_backend = search_backend or _default_search_backend
        self._fetch_backend = fetch_backend or _default_fetch_backend

    def collect(
        self,
        *,
        request: IntelligenceRequest,
        record_tool_call: CapabilityRecorder,
        cancellation_event: threading.Event | None = None,
    ) -> WebResearchRun:
        if request.task_type is not IntelligenceTaskType.DEEP_RESEARCH:
            raise ValueError("live web tools are limited to deep_research")
        scope = request.web_research_scope
        if scope is None:
            raise ValueError("deep_research request omitted web scope")
        _raise_if_cancelled(cancellation_event)
        record_tool_call("web.search")
        try:
            raw_results = self._search_backend(
                request.question,
                allowed_domains=list(scope.allowed_domains),
                blocked_domains=list(scope.blocked_domains),
                max_results=scope.max_search_results,
                timeout_seconds=scope.search_timeout_seconds,
            )
            hits = _normalize_hits(raw_results, scope=scope)
        except Exception as exc:  # The typed result preserves UNKNOWN.
            return WebResearchRun(
                query=request.question,
                uncertainties=(
                    _uncertainty(
                        "web_search_unavailable",
                        "The bounded live web search provider was unavailable.",
                        "no live web candidate evidence was collected",
                        type(exc).__name__,
                    ),
                ),
            )

        if not hits:
            return WebResearchRun(
                query=request.question,
                uncertainties=(
                    _uncertainty(
                        "web_search_no_results",
                        "The bounded live web search returned no in-scope results.",
                        "no live web candidate evidence was collected",
                        "in_scope_web_search_result",
                    ),
                ),
                search_result_count=0,
            )

        artifacts: list[WebResearchArtifact] = []
        failures: list[str] = []
        fetch_attempt_count = 0
        for hit in hits[: scope.max_fetches]:
            _raise_if_cancelled(cancellation_event)
            record_tool_call("web.fetch")
            fetch_attempt_count += 1
            try:
                payload = self._fetch_backend(
                    hit.url,
                    allowed_domains=list(scope.allowed_domains),
                    blocked_domains=list(scope.blocked_domains),
                    max_content_tokens=max(
                        250,
                        (scope.max_content_characters + 3) // 4,
                    ),
                    timeout_seconds=scope.fetch_timeout_seconds,
                )
                artifacts.append(
                    _artifact_from_fetch(
                        request=request,
                        scope=scope,
                        hit=hit,
                        payload=payload,
                    )
                )
            except Exception:
                failures.append(hit.url)

        uncertainties: list[Uncertainty] = []
        if failures:
            uncertainties.append(
                Uncertainty(
                    uncertainty_id="web_fetch_unavailable",
                    description="One or more in-scope web pages could not be fetched.",
                    missing_evidence=tuple(failures),
                    impact="deep research candidate evidence may be incomplete",
                    recommended_next_evidence=("retry_web_fetch",),
                )
            )
        if not artifacts and not uncertainties:
            uncertainties.append(
                _uncertainty(
                    "web_fetch_no_evidence",
                    "No fetched page produced a valid typed evidence artifact.",
                    "deep research could not produce grounded candidate findings",
                    "valid_fetched_web_page",
                )
            )
        return WebResearchRun(
            query=request.question,
            artifacts=tuple(artifacts),
            uncertainties=tuple(uncertainties),
            search_result_count=len(hits),
            fetch_attempt_count=fetch_attempt_count,
        )


def _default_search_backend(query: str, **kwargs: Any) -> Sequence[Mapping[str, Any]]:
    from scout.agents.local_web_search import _search

    return _search(query, **kwargs)


def _default_fetch_backend(url: str, **kwargs: Any) -> Mapping[str, Any]:
    from scout.agents.local_web_fetch import _fetch_url

    return _fetch_url(url, **kwargs)


def _normalize_hits(
    raw_results: Sequence[Mapping[str, Any]],
    *,
    scope: WebResearchScope,
) -> tuple[WebSearchHit, ...]:
    hits: list[WebSearchHit] = []
    seen: set[str] = set()
    for raw in raw_results:
        if not isinstance(raw, Mapping):
            continue
        title = " ".join(str(raw.get("title") or "").split())
        url = _canonical_url(str(raw.get("url") or raw.get("href") or ""))
        if not title or url is None or url in seen:
            continue
        if not _url_allowed(url, scope=scope):
            continue
        seen.add(url)
        hits.append(
            WebSearchHit(
                title=title[:500],
                url=url,
                snippet=" ".join(
                    str(raw.get("snippet") or raw.get("body") or "").split()
                )[:2_000],
                rank=len(hits) + 1,
            )
        )
    return tuple(hits)


def _artifact_from_fetch(
    *,
    request: IntelligenceRequest,
    scope: WebResearchScope,
    hit: WebSearchHit,
    payload: Mapping[str, Any],
) -> WebResearchArtifact:
    if payload.get("candidate_only") is not True:
        raise ValueError("web fetch omitted candidate-only marker")
    if payload.get("runtime_safety_truth") is not False:
        raise ValueError("web fetch claimed runtime safety truth")
    final_url = _canonical_url(str(payload.get("url") or ""))
    if final_url is None or not _url_allowed(final_url, scope=scope):
        raise ValueError("web fetch redirected outside the request scope")
    content_hash = str(payload.get("content_hash") or "").strip()
    if not content_hash:
        raise ValueError("web fetch omitted content hash")
    fetched_at = _parse_datetime(payload.get("fetched_at"))
    content = str(payload.get("content") or "")
    excerpt = _plain_text(content)[: scope.max_content_characters]
    summary = ". ".join(item for item in (hit.title, hit.snippet) if item).strip()
    if not summary:
        summary = f"Fetched candidate web page from {final_url}"
    evidence_id = "web:" + hashlib.sha256(final_url.encode("utf-8")).hexdigest()[:20]
    web = WebEvidenceProvenance(
        query=request.question,
        url=final_url,
        title=hit.title,
        search_provider=SEARCH_PROVIDER,
        search_rank=hit.rank,
        fetched_at=fetched_at,
        http_status=int(payload.get("status") or 0),
        content_type=str(payload.get("content_type") or "unknown"),
        content_bytes=int(payload.get("content_bytes") or 0),
        truncated=bool(payload.get("truncated")),
    )
    return WebResearchArtifact(
        evidence_id=evidence_id,
        source_ref=final_url,
        content_hash=content_hash,
        summary=summary[:4_000],
        generated_at=fetched_at,
        web=web,
        attributes={
            "candidate_claim": summary[:4_000],
            "search_query": request.question,
            "web_content_excerpt": excerpt,
            "untrusted_external_content": True,
            "prompt_injection_treated_as_data": True,
        },
    )


def _canonical_url(value: str) -> str | None:
    parsed = urlsplit(value.strip())
    hostname = (parsed.hostname or "").casefold().rstrip(".")
    if parsed.scheme not in {"http", "https"} or not hostname:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    netloc = hostname
    try:
        port = parsed.port
    except ValueError:
        return None
    if port is not None:
        default_port = 443 if parsed.scheme == "https" else 80
        if port != default_port:
            netloc = f"{hostname}:{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path or "/", parsed.query, ""))


def _url_allowed(url: str, *, scope: WebResearchScope) -> bool:
    hostname = (urlsplit(url).hostname or "").casefold()
    if not hostname:
        return False
    if any(_domain_matches(hostname, item) for item in scope.blocked_domains):
        return False
    return any(_domain_matches(hostname, item) for item in scope.allowed_domains)


def _domain_matches(hostname: str, pattern: str) -> bool:
    normalized = pattern.strip().casefold().removeprefix("*.")
    return bool(normalized) and (
        hostname == normalized or hostname.endswith(f".{normalized}")
    )


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del attrs
        if tag in {"script", "style", "noscript", "svg"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)


def _plain_text(content: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(content)
        text = " ".join(parser.parts)
    except Exception:
        text = content
    return " ".join(text.split())


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    else:
        raise ValueError("web fetch omitted fetched_at")
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _uncertainty(
    uncertainty_id: str,
    description: str,
    impact: str,
    missing: str,
) -> Uncertainty:
    return Uncertainty(
        uncertainty_id=uncertainty_id,
        description=description,
        missing_evidence=(missing,),
        impact=impact,
        recommended_next_evidence=("retry_bounded_web_research",),
    )


def _raise_if_cancelled(event: threading.Event | None) -> None:
    if event is not None and event.is_set():
        raise RuntimeError("bounded web research was cancelled")


__all__ = [
    "BoundedLiveWebResearchTools",
    "SEARCH_PROVIDER",
    "WebResearchArtifact",
    "WebResearchRun",
    "WebSearchHit",
]
