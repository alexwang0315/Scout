from __future__ import annotations

import pytest
from pydantic_ai.exceptions import ModelRetry

from scout.agents.local_web_fetch import (
    _SafeRedirectHandler,
    _domain_matches,
    _fetch_url,
    _validate_url,
    build_local_web_fetch,
)


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
        "http://localhost/private",
        "http://127.0.0.1/private",
        "http://10.0.0.2/private",
        "http://[::1]/private",
        "not-a-url",
    ],
)
def test_validate_url_rejects_non_http_and_credential_urls(url: str) -> None:
    with pytest.raises(ValueError):
        _validate_url(url, allowed_domains=None, blocked_domains=None)


def test_validate_url_rejects_hostname_resolving_to_private_address(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "scout.agents.local_web_fetch.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("127.0.0.1", 443))],
    )

    with pytest.raises(ValueError, match="public IP"):
        _validate_url(
            "https://attacker.example/path",
            allowed_domains=["attacker.example"],
            blocked_domains=None,
            resolve_hostname=True,
        )


def test_redirect_handler_rejects_private_or_out_of_scope_target() -> None:
    handler = _SafeRedirectHandler(
        allowed_domains=["pydantic.dev"],
        blocked_domains=None,
        resolve_hostname=False,
    )

    with pytest.raises(ValueError, match="public"):
        handler.redirect_request(
            None,
            None,
            302,
            "redirect",
            {},
            "http://127.0.0.1/private",
        )

    with pytest.raises(ValueError, match="not allowed"):
        handler.redirect_request(
            None,
            None,
            302,
            "redirect",
            {},
            "https://example.com/out-of-scope",
        )


@pytest.mark.anyio
async def test_local_web_fetch_returns_invalid_model_url_for_retry() -> None:
    class Context:
        run_id = "invalid-url-retry"

    fetch = build_local_web_fetch()

    with pytest.raises(ModelRetry, match="request rejected"):
        await fetch(Context(), "not-a-url")


def test_fetch_url_returns_provenance_metadata(monkeypatch) -> None:
    class Headers:
        def get_content_charset(self) -> str:
            return "utf-8"

        def get_content_type(self) -> str:
            return "text/html"

    class Response:
        headers = Headers()
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            del exc_type, exc, traceback

        def geturl(self) -> str:
            return "https://www.cwa.gov.tw/V8/C/W/Warning.html"

        def read(self, size: int | None = None) -> bytes:
            del size
            return "<h1>南投縣豪雨特報</h1>".encode()

    monkeypatch.setattr(
        "scout.agents.local_web_fetch._open_url",
        lambda *args, **kwargs: Response(),
    )

    result = _fetch_url(
        "https://www.cwa.gov.tw/V8/C/W/Warning.html",
        allowed_domains=["cwa.gov.tw"],
        blocked_domains=None,
        max_content_tokens=None,
        timeout_seconds=5.0,
        resolve_hostname=False,
    )

    assert result["status"] == 200
    assert result["content_hash"].startswith("sha256:")
    assert result["fetched_at"].endswith("Z")
    assert result["content_bytes"] > 0
    assert result["candidate_only"] is True
    assert result["runtime_safety_truth"] is False
