"""Provider SSE and CLI-output regressions using real SDKs with local fixtures."""

import asyncio

import pytest

from scout.cli.pydantic_243_checks import banner_output_case, stream_boundary_case


@pytest.mark.parametrize("provider", ["openai", "openrouter"])
@pytest.mark.parametrize("thinking", [False, True])
@pytest.mark.parametrize("tool_count", [1, 2])
def test_stream_text_tool_text_preserves_lifecycle_and_evidence(
    provider, thinking, tool_count
):
    case = asyncio.run(
        stream_boundary_case(provider, thinking=thinking, tool_count=tool_count)
    )
    assert case["model_requests"] == 2
    assert case["tool_calls"] == tool_count
    assert case["stream_lifecycle_valid"] and case["source_refs_preserved"]
    assert not case["network_performed"]


@pytest.mark.parametrize("mode", ["enabled", "api_disabled", "env_disabled", "ci"])
def test_banner_never_contaminates_json_stdout_or_repeats(mode):
    case = banner_output_case(mode)
    assert case["stdout_json_valid"]
    assert case["banner_count"] == (1 if mode == "enabled" else 0)
    assert not case["network_performed"]
