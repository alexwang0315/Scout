from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from scout.cli.pydantic_compat_smoke import (
    REPO_ROOT,
    REQUIRED_VERSION,
    _bounded_text,
    _live_env_candidates,
    _normalize_openrouter_model,
    _redact_error,
    run_compatibility_smoke,
)


def test_offline_pydantic_ai_compatibility_smoke_passes() -> None:
    report = asyncio.run(run_compatibility_smoke())

    assert report["status"] == "passed"
    assert report["required_version"] == REQUIRED_VERSION
    assert report["check_count"] == 17
    assert report["passed_count"] == 17
    assert report["failed_count"] == 0
    assert report["live_openrouter_requested"] is False
    assert {item["name"] for item in report["checks"]} == {
        "runtime_versions",
        "v235_capability_contract",
        "openrouter_web_search_annotations",
        "instrumentation_v6_tool_role",
        "function_tool_call",
        "blocking_sync_tool_timeout",
        "nested_sync_agent_run_rejected",
        "structured_output",
        "mcp_instructions_and_tool",
        "web_capability_contract",
        "stream_events_and_compaction",
        "agent_web_content_type_guard",
        "agent_web_host_guard",
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
            model_name="deepseek/deepseek-v4-flash-0731",
            env_file=tmp_path / "missing.env",
        )
    )

    assert report["status"] == "failed"
    assert report["model"] == "openrouter:deepseek/deepseek-v4-flash-0731"
    assert report["openrouter_credential_present"] is False
    assert report["failed_count"] == 1
    assert report["checks"][-1]["error_type"] == "MissingCredential"


def test_live_env_defaults_to_repo_then_persistent_scout_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SCOUT_ENV_FILE", raising=False)

    candidates = _live_env_candidates(None)

    assert candidates == (REPO_ROOT / ".env", Path.home() / ".scout" / ".env")


def test_explicit_live_env_file_does_not_fall_through_to_operator_secrets(
    tmp_path: Path,
) -> None:
    explicit = tmp_path / "fixture.env"

    assert _live_env_candidates(explicit) == (explicit,)


def test_normalizes_openrouter_model_without_changing_vendor_model_id() -> None:
    assert _normalize_openrouter_model("deepseek/deepseek-v4-flash-0731") == (
        "openrouter:deepseek/deepseek-v4-flash-0731"
    )
    assert _normalize_openrouter_model("openrouter:z-ai/glm-5.2") == (
        "openrouter:z-ai/glm-5.2"
    )


def test_redacts_provider_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "fixture-secret")

    redacted = _redact_error("Authorization: Bearer fixture-secret request failed")

    assert "fixture-secret" not in redacted
    assert "[REDACTED]" in redacted


def test_bounds_large_tool_trace_content() -> None:
    bounded = _bounded_text("x" * 2_100, max_characters=100)

    assert bounded.startswith("x" * 100)
    assert bounded.endswith("[truncated 2000 chars]")
