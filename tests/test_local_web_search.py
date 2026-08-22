from __future__ import annotations

from scout.agents.local_web_search import (
    DEFAULT_SEARCH_REGION,
    DEFAULT_TEXT_BACKENDS,
    _BingResultParser,
    _result_allowed,
    _search,
    _search_query,
)


def test_bing_result_parser_extracts_search_result_links() -> None:
    parser = _BingResultParser()
    parser.feed(
        '<ol><li class="b_algo"><h2><a href="https://www.bing.com/ck/a?'
        "u=a1aHR0cHM6Ly93d3cuY3dhLmdvdi50dy9WOC9DLw&amp;ntb=1\">"
        "中央氣象署</a></h2></li></ol>"
    )

    assert parser.results == [
        {
            "title": "中央氣象署",
            "url": "https://www.cwa.gov.tw/V8/C/",
            "snippet": "中央氣象署",
        }
    ]


def test_search_query_adds_allowed_and_blocked_domain_terms() -> None:
    query = _search_query(
        "Pydantic AI changelog",
        allowed_domains=["pydantic.dev", "*.openrouter.ai"],
        blocked_domains=["example.com"],
    )

    assert "site:pydantic.dev" in query
    assert "site:openrouter.ai" in query
    assert "-site:example.com" in query


def test_search_result_filter_enforces_domain_policy() -> None:
    assert _result_allowed(
        "https://ai.pydantic.dev/changelog/",
        allowed_domains=["pydantic.dev"],
        blocked_domains=None,
    )
    assert not _result_allowed(
        "https://example.com/pydantic",
        allowed_domains=["pydantic.dev"],
        blocked_domains=None,
    )
    assert not _result_allowed(
        "https://private.pydantic.dev/internal",
        allowed_domains=None,
        blocked_domains=["pydantic.dev"],
    )


def test_search_uses_web_backends_instead_of_auto_encyclopedia_priority(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_text(self, query: str, **kwargs: object) -> list[dict[str, str]]:
        captured.update({"query": query, **kwargs})
        return [
            {
                "title": "Official weather warning",
                "href": "https://www.cwa.gov.tw/V8/C/P/Warning/W26.html",
                "body": "Central Weather Administration",
            }
        ]

    monkeypatch.setattr("ddgs.ddgs.DDGS.text", fake_text)
    monkeypatch.setattr(
        "scout.agents.local_web_search._bing_search",
        lambda query, *, max_results, timeout_seconds: [],
    )

    results = _search(
        "CWA warning",
        allowed_domains=["cwa.gov.tw"],
        blocked_domains=None,
        max_results=5,
    )

    assert captured["backend"] == DEFAULT_TEXT_BACKENDS
    assert captured["region"] == DEFAULT_SEARCH_REGION
    assert "wikipedia" not in str(captured["backend"])
    assert results[0]["url"] == "https://www.cwa.gov.tw/V8/C/P/Warning/W26.html"


def test_search_ddgs_fallback_avoids_site_operator_and_filters_domain(
    monkeypatch,
) -> None:
    queries: list[str] = []

    def fake_text(self, query: str, **kwargs: object) -> list[dict[str, str]]:
        queries.append(query)
        return [
            {
                "title": "Unofficial summary",
                "href": "https://example.com/trail",
                "body": "not accepted",
            },
            {
                "title": "Taroko National Park",
                "href": "https://www.taroko.gov.tw/ch",
                "body": "official site",
            },
        ]

    monkeypatch.setattr("ddgs.ddgs.DDGS.text", fake_text)
    monkeypatch.setattr(
        "scout.agents.local_web_search._bing_search",
        lambda query, *, max_results, timeout_seconds: [],
    )

    results = _search(
        "Taroko trail closure",
        allowed_domains=["taroko.gov.tw"],
        blocked_domains=None,
        max_results=5,
    )

    assert len(queries) == 1
    assert "site:taroko.gov.tw" not in queries[0]
    assert [item["url"] for item in results] == ["https://www.taroko.gov.tw/ch"]


def test_search_prefers_bing_html_before_ddgs_backends(
    monkeypatch,
) -> None:
    ddgs_called = False
    bing_queries: list[str] = []

    def unexpected_text(self, query: str, **kwargs: object) -> list[dict[str, str]]:
        nonlocal ddgs_called
        ddgs_called = True
        return []

    monkeypatch.setattr("ddgs.ddgs.DDGS.text", unexpected_text)
    def fake_bing_search(
        query: str,
        *,
        max_results: int,
        timeout_seconds: float,
    ) -> list[dict[str, str]]:
        del max_results, timeout_seconds
        bing_queries.append(query)
        return [
            {
                "title": "Taroko National Park",
                "url": "https://www.taroko.gov.tw/ch",
                "snippet": "Official site",
            }
        ]

    monkeypatch.setattr(
        "scout.agents.local_web_search._bing_search",
        fake_bing_search,
    )

    results = _search(
        "Taroko trail closure",
        allowed_domains=["taroko.gov.tw"],
        blocked_domains=None,
        max_results=5,
    )

    assert [item["url"] for item in results] == ["https://www.taroko.gov.tw/ch"]
    assert "site:taroko.gov.tw" in bing_queries[0]
    assert not ddgs_called
