from __future__ import annotations

from scout.agents.local_web_search import _result_allowed, _search_query


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
