from pydantic_ai_runtime_compat import (
    build_chat_model,
    pydantic_agent_runtime_kwargs,
    pydantic_ai_runtime_version,
)
from scout.agents.pydantic_ai_compat import (
    build_chat_model as build_packaged_chat_model,
    pydantic_ai_runtime_version as packaged_runtime_version,
)


def test_pydantic_ai_runtime_version_supports_slim_install() -> None:
    assert pydantic_ai_runtime_version() != "not-installed"
    assert packaged_runtime_version() == pydantic_ai_runtime_version()


def test_agent_runtime_kwargs_preserve_scout_tool_end_strategy() -> None:
    assert pydantic_agent_runtime_kwargs() == {"end_strategy": "early"}


def test_openrouter_alias_builds_openrouter_model_without_network() -> None:
    model = build_chat_model(
        model_name="openrouter:openai/gpt-4o-mini",
        api_key="test-token",
    )

    assert type(model).__name__ == "OpenRouterModel"
    assert model.model_name == "openai/gpt-4o-mini"
    assert model.system == "openrouter"


def test_packaged_openrouter_helper_matches_root_helper() -> None:
    model = build_packaged_chat_model(
        model_name="openrouter:openai/gpt-4o-mini",
        api_key="test-token",
    )

    assert type(model).__name__ == "OpenRouterModel"
    assert model.model_name == "openai/gpt-4o-mini"
