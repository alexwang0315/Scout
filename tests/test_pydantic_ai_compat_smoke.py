from __future__ import annotations

import asyncio
import tomllib
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace

import pytest
from packaging.requirements import Requirement
from pydantic_ai.models.test import TestModel

from scout.cli import pydantic_compat_smoke as smoke
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
    installed_version = version("pydantic-ai-slim")
    report = asyncio.run(run_compatibility_smoke(expected_version=installed_version))

    assert report["status"] == "passed"
    assert report["required_version"] == installed_version
    assert report["configured_version"] == REQUIRED_VERSION
    assert report["check_count"] == 25
    assert report["passed_count"] == 25
    assert report["failed_count"] == 0
    assert report["live_openrouter_requested"] is False
    assert {item["name"] for item in report["checks"]} == {
        "runtime_versions",
        "v236_capability_contract",
        "v237_zai_finish_reasons",
        "v241_capability_contract",
        "v242_deferred_approvals",
        "v242_tool_content_history",
        "v242_code_mode_refs",
        "v243_stream_boundaries",
        "v243_banner_output",
        "openrouter_web_search_annotations",
        "instrumentation_v6_tool_role",
        "function_tool_call",
        "blocking_sync_tool_timeout",
        "nested_sync_agent_run_rejected",
        "structured_output",
        "mcp_instructions_and_tool",
        "web_capability_contract",
        "agent_event_hook",
        "stream_events_and_compaction",
        "agent_web_content_type_guard",
        "agent_web_host_guard",
        "tool_failed_visible_without_retry",
        "model_retry_then_success",
        "external_cancellation",
        "model_http_error_retry_metadata",
    }
    by_name = {item["name"]: item for item in report["checks"]}
    capability_details = by_name["v236_capability_contract"]["details"]
    assert capability_details["instruction_part_id"] == "scout-instruction-v236"
    assert capability_details["durable_operation_name"] == "scout.route.read"
    v241 = by_name["v241_capability_contract"]["details"]
    assert v241["fallback_parameter"] == "fallback_subagent_model"
    assert v241["image_provider"] == "test"
    assert v241["network_performed"] is False
    assert v241["subscription_authentication_performed"] is False
    assert by_name["v242_deferred_approvals"]["details"]["invalid_approval_rejected"]
    assert by_name["v242_tool_content_history"]["details"]["source_refs_preserved"]
    assert by_name["v242_code_mode_refs"]["details"]["non_object_refs_inlined"]
    streams = by_name["v243_stream_boundaries"]["details"]
    assert streams["case_count"] == 8
    assert streams["network_performed"] is False
    assert all(case["stream_lifecycle_valid"] for case in streams["cases"])
    banners = by_name["v243_banner_output"]["details"]
    assert len(banners["cases"]) == 4
    assert all(case["stdout_json_valid"] for case in banners["cases"])
    mcp_details = by_name["mcp_instructions_and_tool"]["details"]
    assert "FunctionToolCallEvent" in mcp_details["event_types"]
    assert "FunctionToolResultEvent" in mcp_details["event_types"]
    termination_details = by_name["v237_zai_finish_reasons"]["details"]
    assert termination_details["network_performed"] is False
    assert termination_details["case_count"] == 6
    expected_reasons = {
        "sensitive": "content_filter",
        "model_context_window_exceeded": "length",
        "network_error": "error",
    }
    for case in termination_details["cases"]:
        assert case["partial_answer_preserved"] is True
        assert case["finish_reason"] == expected_reasons[case["provider_finish_reason"]]


def test_runtime_and_deployment_dependency_pins_stay_aligned() -> None:
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())["project"]
    dependency_sets = {
        "project": project["dependencies"],
        **project["optional-dependencies"],
        **{
            path.name: path.read_text().splitlines()
            for path in REPO_ROOT.glob("requirements.pi.*.txt")
        },
    }
    assert {
        "requirements.pi.admin.txt",
        "requirements.pi.live.txt",
    } <= dependency_sets.keys()
    expected_versions = {
        "pydantic-ai-slim": "2.45.0",
        "pydantic-evals": "2.45.0",
        "praisonaiagents": "1.7.6",
    }
    seen = set()
    for surface, dependencies in dependency_sets.items():
        for dependency in dependencies:
            if not dependency.strip() or dependency.lstrip().startswith("#"):
                continue
            requirement = Requirement(dependency)
            if requirement.name in expected_versions:
                expected = expected_versions[requirement.name]
                assert str(requirement.specifier) == f"=={expected}", surface
                seen.add(requirement.name)
    assert seen == expected_versions.keys()
    assert REQUIRED_VERSION == expected_versions["pydantic-ai-slim"]


def test_live_mcp_path_repairs_missing_call_and_requires_actual_return():
    from pydantic_ai.messages import ToolCallPart
    from pydantic_ai.models.function import DeltaToolCall, FunctionModel

    requests = []

    async def stream(messages, info):
        requests.append(messages)
        if len(requests) == 1:
            yield "I have not read the marker yet."
        elif len(requests) == 2:
            yield {0: DeltaToolCall(name="route_marker", json_args="{}")}
        else:
            yield "MCP-CP-07"

    details = asyncio.run(smoke._live_mcp(FunctionModel(stream_function=stream)))
    assert len(requests) == 3
    assert details["server_execution_count"] == 1
    assert details["result_used"]
    assert details["retry_prompt_count"] == 1
    assert details["tool_names"] == ["route_marker"]
    assert details["tool_return_contents"] == "MCP-CP-07"
    assert any(isinstance(part, ToolCallPart) for message in requests[-1] for part in message.parts)


def test_smoke_failure_retains_diagnostic_trace():
    def fail():
        raise smoke.SmokeCheckFailure("MCP result missing", {"tool_call_count": 0})

    report = asyncio.run(smoke._run_checks([("fixture-mcp", fail)]))
    assert report[0]["status"] == "failed"
    assert report[0]["details"] == {"tool_call_count": 0}


def test_candidate_version_is_verified_without_changing_runtime_pin(monkeypatch):
    monkeypatch.setattr(smoke, "REQUIRED_VERSION", "2.37.0")
    packages = smoke._package_versions()
    candidate = {
        **packages,
        **{
            name: "2.38.0"
            for name in ("pydantic-ai-slim", "pydantic-evals", "pydantic-graph")
        },
    }
    monkeypatch.setattr(smoke, "_package_versions", lambda: candidate)

    report = asyncio.run(run_compatibility_smoke(expected_version="2.38.0"))

    assert report["status"] == "passed"
    assert report["required_version"] == "2.38.0"
    assert report["configured_version"] == "2.37.0"
    assert smoke.REQUIRED_VERSION == "2.37.0"


def test_candidate_version_does_not_hide_misaligned_graph(monkeypatch):
    monkeypatch.setattr(
        smoke,
        "_package_versions",
        lambda: {
            "pydantic-ai-slim": "2.38.0",
            "pydantic-evals": "2.38.0",
            "pydantic-graph": "2.37.0",
        },
    )

    with pytest.raises(AssertionError, match="pydantic-graph=2.37.0"):
        smoke._offline_runtime_versions(expected_version="2.38.0")


def test_default_version_gate_still_rejects_unapproved_candidate(monkeypatch):
    monkeypatch.setattr(
        smoke,
        "_package_versions",
        lambda: {
            name: "0.0.0"
            for name in ("pydantic-ai-slim", "pydantic-evals", "pydantic-graph")
        },
    )

    with pytest.raises(AssertionError, match=f"expected {REQUIRED_VERSION}"):
        smoke._offline_runtime_versions()


def test_native_web_smoke_keeps_ten_use_capacity_and_transport_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = []
    native_tool = smoke.NativeTool

    def record_tool(tool):
        tools.append(tool)
        return native_tool(tool)

    async def run_fixture(agent, prompt):
        return SimpleNamespace(
            output="Pydantic AI: https://pydantic.dev/docs/ai/project/changelog/",
            all_messages=lambda: [],
        )

    monkeypatch.setattr(smoke, "NativeTool", record_tool)
    monkeypatch.setattr(smoke, "_live_run", run_fixture)

    result = asyncio.run(smoke._live_native_web_search(TestModel()))

    assert len(tools) == 1
    assert tools[0].max_uses == result["native_search_max_uses"] == 10
    assert result["qualification_scope"] == "provider_transport_only"
    assert result["provider_exposed_native_parts"] is False


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
            expected_version=version("pydantic-ai-slim"),
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
