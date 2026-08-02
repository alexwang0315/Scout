from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from scout.cli.pydantic_compat_smoke import (
    REQUIRED_VERSION,
    _bounded_text,
    _normalize_openrouter_model,
    _redact_error,
    run_compatibility_smoke,
)


def test_offline_pydantic_ai_compatibility_smoke_passes() -> None:
    report = asyncio.run(run_compatibility_smoke())

    assert report["status"] == "passed"
    assert report["required_version"] == REQUIRED_VERSION
    assert report["check_count"] == 10
    assert report["passed_count"] == 10
    assert report["failed_count"] == 0
    assert report["live_openrouter_requested"] is False
    assert {item["name"] for item in report["checks"]} == {
        "runtime_versions",
        "v222_capability_contract",
        "function_tool_call",
        "structured_output",
        "mcp_instructions_and_tool",
        "web_capability_contract",
        "tool_failed_visible_without_retry",
        "model_retry_then_success",
        "external_cancellation",
        "model_http_error_retry_metadata",
    }


def test_live_smoke_fails_closed_without_openrouter_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    report = asyncio.run(
        run_compatibility_smoke(
            live_openrouter=True,
            model_name="deepseek/deepseek-v3.2",
            env_file=tmp_path / "missing.env",
        )
    )

    assert report["status"] == "failed"
    assert report["model"] == "openrouter:deepseek/deepseek-v3.2"
    assert report["openrouter_credential_present"] is False
    assert report["failed_count"] == 1
    assert report["checks"][-1]["error_type"] == "MissingCredential"


def test_normalizes_openrouter_model_without_changing_vendor_model_id() -> None:
    assert _normalize_openrouter_model("deepseek/deepseek-v3.2") == (
        "openrouter:deepseek/deepseek-v3.2"
    )
    assert _normalize_openrouter_model("openrouter:z-ai/glm-5.2") == (
        "openrouter:z-ai/glm-5.2"
    )


def test_redacts_provider_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "fixture-secret")

    redacted = _redact_error(
        "Authorization: Bearer fixture-secret request failed"
    )

    assert "fixture-secret" not in redacted
    assert "[REDACTED]" in redacted


def test_bounds_large_tool_trace_content() -> None:
    bounded = _bounded_text("x" * 2_100, max_characters=100)

    assert bounded.startswith("x" * 100)
    assert bounded.endswith("[truncated 2000 chars]")
