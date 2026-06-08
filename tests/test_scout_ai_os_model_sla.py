from __future__ import annotations

import time
from pathlib import Path

from scout.agents import (
    ModelCallLedger,
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
            "SCOUT_AI_OS_MODEL_TIMEOUT_SECONDS": "0.01",
        },
    )

    def slow_provider_call() -> str:
        time.sleep(0.1)
        return "provider"

    result = ModelSlaGateway(
        policy,
        ledger=ModelCallLedger(max_cost_usd=policy.max_cost_usd),
    ).run_sync(
        "timeout-test",
        slow_provider_call,
        fallback_call=lambda: "fallback",
    )

    assert result.output == "fallback"
    assert result.status == "timeout_fallback"
    assert result.fallback_used is True


def test_pydantic_provider_uses_sla_fallback_before_external_budget_call(
    tmp_path: Path,
) -> None:
    policy = resolve_model_policy(
        "openrouter:openai/gpt-4o-mini",
        env={
            "OPENROUTER_API_KEY": "sk-test",
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
