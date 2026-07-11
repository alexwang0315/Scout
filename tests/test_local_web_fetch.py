from __future__ import annotations

import pytest

from scout.agents.local_web_fetch import _domain_matches, _validate_url


def test_domain_matching_accepts_exact_and_subdomain_hosts() -> None:
    assert _domain_matches("pydantic.dev", "pydantic.dev") is True
    assert _domain_matches("ai.pydantic.dev", "*.pydantic.dev") is True
    assert _domain_matches("notpydantic.dev", "pydantic.dev") is False


def test_validate_url_applies_allowed_and_blocked_domain_policy() -> None:
    _validate_url(
        "https://ai.pydantic.dev/changelog/",
        allowed_domains=["pydantic.dev"],
        blocked_domains=None,
    )

    with pytest.raises(ValueError, match="blocked"):
        _validate_url(
            "https://private.example.com/data",
            allowed_domains=None,
            blocked_domains=["example.com"],
        )


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "https://user:password@example.com/private",
        "not-a-url",
    ],
)
def test_validate_url_rejects_non_http_and_credential_urls(url: str) -> None:
    with pytest.raises(ValueError):
        _validate_url(url, allowed_domains=None, blocked_domains=None)
