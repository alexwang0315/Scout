from __future__ import annotations

import time
from threading import Event
from pathlib import Path

from scout.agents import (
    ModelCallLedger,
    ModelProviderHealthMonitor,
    ModelSlaGateway,
    ModelPolicyMode,
    PydanticScoutAgentProvider,
    WorkflowCompilerAgent,
    resolve_model_policy,
)
from tests.test_scout_ai_os_agents import make_deps


def test_model_sla_gateway_budget_fallback_skips_provider_call() -> None:
    policy = resolve_model_policy(
        "openrouter:openai/gpt-4o-mini",
        env={
            "OPENROUTER_API_KEY": "sk-test",
            "SCOUT_AI_OS_AGGRESSIVE_CONSTRUCTION_MODE": "0",
            "SCOUT_AI_OS_MODEL_MAX_COST_USD": "0",
            "SCOUT_AI_OS_MODEL_ESTIMATED_CALL_COST_USD": "0.001",
        },
    )
    called = False

    def provider_call() -> str:
        nonlocal called
        called = True
        return "provider"

    result = ModelSlaGateway(policy).run_sync(
        "budget-test",
        provider_call,
        fallback_call=lambda: "fallback",
    )

    assert result.output == "fallback"
    assert result.status == "budget_fallback"
    assert result.fallback_used is True
    assert called is False


def test_model_sla_gateway_timeout_fallback() -> None:
    policy = resolve_model_policy(
        "openrouter:openai/gpt-4o-mini",
        env={
            "OPENROUTER_API_KEY": "sk-test",
            "SCOUT_AI_OS_AGGRESSIVE_CONSTRUCTION_MODE": "0",
            "SCOUT_AI_OS_MODEL_TIMEOUT_SECONDS": "0.01",
        },
    )

    provider_completed = Event()

    def slow_provider_call() -> str:
        time.sleep(0.03)
        provider_completed.set()
        return "provider"

    result = ModelSlaGateway(
        policy,
        ledger=ModelCallLedger(max_cost_usd=policy.max_cost_usd),
    ).run_sync(
        "timeout-test",
        slow_provider_call,
        fallback_call=lambda: "fallback",
        max_retries=0,
    )

    assert result.output == "fallback"
    assert result.status == "timeout_fallback"
    assert result.fallback_used is True
    assert provider_completed.is_set()


def test_model_sla_gateway_retries_and_records_telemetry() -> None:
    policy = resolve_model_policy(
        "openrouter:openai/gpt-4o-mini",
        env={"OPENROUTER_API_KEY": "sk-test"},
    )
    calls = 0

    def flaky_provider_call() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient upstream error")
        return "provider"

    result = ModelSlaGateway(
        policy,
        health_monitor=ModelProviderHealthMonitor(failure_threshold=3),
    ).run_sync(
        "retry-test",
        flaky_provider_call,
        fallback_call=lambda: "fallback",
        max_retries=1,
    )

    assert result.output == "provider"
    assert result.status == "completed"
    assert result.attempts == 2
    assert result.provider_health["state"] == "healthy"
    assert result.telemetry is not None
    assert result.telemetry.attempts == 2


def test_model_sla_gateway_redacts_credentials_from_error_telemetry() -> None:
    policy = resolve_model_policy(
        "openrouter:openai/gpt-4o-mini",
        env={"OPENROUTER_API_KEY": "configured"},
    )

    def failing_provider_call() -> str:
        raise RuntimeError("Authorization: Bearer super-secret-token-value")

    result = ModelSlaGateway(policy).run_sync(
        "redaction-test",
        failing_provider_call,
        fallback_call=lambda: "fallback",
        max_retries=0,
    )

    assert result.error is not None
    assert "super-secret-token-value" not in result.error
    assert "[REDACTED]" in result.error
    assert result.telemetry is not None
    assert result.telemetry.error == result.error


def test_model_sla_gateway_redacts_common_credential_representations() -> None:
    policy = resolve_model_policy(
        "openrouter:openai/gpt-4o-mini",
        env={"OPENROUTER_API_KEY": "configured"},
    )
    examples = (
        "headers={'X-Api-Key': 'fixture-plain-value-123456'}",
        "NVIDIA_API_KEY=nvapi-fixture-value-123456",
        "Authorization: 'Token fixture-authorization-value-123456'",
    )

    for index, error_text in enumerate(examples):
        result = ModelSlaGateway(policy).run_sync(
            f"redaction-variant-{index}",
            lambda error_text=error_text: (_ for _ in ()).throw(
                RuntimeError(error_text)
            ),
            fallback_call=lambda: "fallback",
            max_retries=0,
        )

        assert result.error is not None
        assert "fixture-plain-value" not in result.error
        assert "nvapi-fixture-value" not in result.error
        assert "fixture-authorization-value" not in result.error
        assert "[REDACTED]" in result.error


def test_model_sla_gateway_circuit_breaker_fallback_skips_provider_call() -> None:
    policy = resolve_model_policy(
        "openrouter:openai/gpt-4o-mini",
        env={"OPENROUTER_API_KEY": "sk-test"},
    )
    monitor = ModelProviderHealthMonitor(failure_threshold=1)
    calls = 0

    def failing_provider_call() -> str:
        nonlocal calls
        calls += 1
        raise RuntimeError("provider unavailable")

    first = ModelSlaGateway(policy, health_monitor=monitor).run_sync(
        "circuit-open",
        failing_provider_call,
        fallback_call=lambda: "fallback",
    )
    second = ModelSlaGateway(policy, health_monitor=monitor).run_sync(
        "circuit-fallback",
        failing_provider_call,
        fallback_call=lambda: "fallback",
    )

    assert first.status == "error_fallback"
    assert first.provider_health["state"] == "open_circuit"
    assert second.status == "circuit_fallback"
    assert second.attempts == 0
    assert second.provider_health["state"] == "open_circuit"
    assert calls == 1


def test_pydantic_provider_uses_sla_fallback_before_external_budget_call(
    tmp_path: Path,
) -> None:
    policy = resolve_model_policy(
        "openrouter:openai/gpt-4o-mini",
        env={
            "OPENROUTER_API_KEY": "sk-test",
            "SCOUT_AI_OS_AGGRESSIVE_CONSTRUCTION_MODE": "0",
            "SCOUT_AI_OS_MODEL_MAX_COST_USD": "0",
            "SCOUT_AI_OS_MODEL_ESTIMATED_CALL_COST_USD": "0.001",
        },
    )
    provider = PydanticScoutAgentProvider(
        model="openrouter:openai/gpt-4o-mini",
        model_policy=policy,
    )

    workflow = WorkflowCompilerAgent(provider).compile(
        "Remind me in 10 minutes.",
        make_deps(tmp_path),
    )

    assert workflow.name == "Remind me in 10 minutes"
    assert provider.last_sla_result is not None
    assert provider.last_sla_result.status == "budget_fallback"
    assert policy.mode is ModelPolicyMode.EXTERNAL_PYDANTIC_AI


def test_model_sla_gateway_treats_cost_and_timeout_as_telemetry_in_construction() -> None:
    policy = resolve_model_policy(
        "openrouter:openai/gpt-4o-mini",
        env={
            "OPENROUTER_API_KEY": "sk-test",
            "SCOUT_AI_OS_MODEL_MAX_COST_USD": "0",
            "SCOUT_AI_OS_MODEL_TIMEOUT_SECONDS": "0.01",
            "SCOUT_AI_OS_MODEL_ESTIMATED_CALL_COST_USD": "0.001",
        },
    )
    called = False

    def provider_call() -> str:
        nonlocal called
        called = True
        time.sleep(0.02)
        return "provider"

    result = ModelSlaGateway(policy).run_sync(
        "construction-unbounded",
        provider_call,
        fallback_call=lambda: "fallback",
    )

    assert called is True
    assert result.output == "provider"
    assert result.status == "completed"
    assert result.timeout_seconds is None
    assert result.estimated_cost_usd == 0.001
