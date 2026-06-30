from pydantic_ai_runtime_compat import (
    build_chat_model,
    normalize_chat_model_name,
    pydantic_agent_runtime_kwargs,
    pydantic_ai_runtime_version,
    pydantic_native_research_capabilities,
)
from scout.agents.model_policy import resolve_model_policy
from scout.agents.pydantic_ai_compat import (
    build_chat_model as build_packaged_chat_model,
    normalize_chat_model_name as normalize_packaged_chat_model_name,
    pydantic_native_research_capabilities as packaged_native_research_capabilities,
    pydantic_ai_runtime_version as packaged_runtime_version,
)


def test_pydantic_ai_runtime_version_supports_slim_install() -> None:
    assert pydantic_ai_runtime_version() != "not-installed"
    assert packaged_runtime_version() == pydantic_ai_runtime_version()


def test_agent_runtime_kwargs_preserve_scout_tool_end_strategy() -> None:
    assert pydantic_agent_runtime_kwargs() == {"end_strategy": "early"}


def test_openai_prefix_normalizes_to_chat_model_semantics() -> None:
    assert normalize_chat_model_name("openai:gpt-4o-mini") == "openai-chat:gpt-4o-mini"
    assert (
        normalize_packaged_chat_model_name("openai:gpt-4o-mini")
        == "openai-chat:gpt-4o-mini"
    )


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


def test_native_research_capabilities_are_off_by_default() -> None:
    policy = resolve_model_policy("openrouter:z-ai/glm-5.2", env={})

    assert policy.native_research_enabled is False
    assert pydantic_native_research_capabilities(policy) == []
    assert packaged_native_research_capabilities(policy) == []


def test_native_research_capabilities_skip_local_function_model() -> None:
    policy = resolve_model_policy(
        env={
            "SCOUT_AI_OS_NATIVE_RESEARCH": "1",
        },
    )

    assert policy.native_research_enabled is True
    assert policy.model_for_agent is None
    assert pydantic_native_research_capabilities(policy) == []
    assert packaged_native_research_capabilities(policy) == []


def test_native_research_capabilities_include_web_search_and_fetch() -> None:
    policy = resolve_model_policy(
        "openrouter:z-ai/glm-5.2",
        env={
            "SCOUT_AI_OS_NATIVE_RESEARCH": "1",
            "SCOUT_AI_OS_NATIVE_RESEARCH_MAX_SEARCHES": "2",
            "SCOUT_AI_OS_NATIVE_RESEARCH_MAX_FETCHES": "4",
            "SCOUT_AI_OS_NATIVE_RESEARCH_ALLOWED_DOMAINS": "pydantic.dev,openrouter.ai",
            "SCOUT_AI_OS_NATIVE_RESEARCH_BLOCKED_DOMAINS": "example.com",
        },
    )

    capabilities = packaged_native_research_capabilities(policy)

    assert policy.native_research_enabled is True
    assert policy.native_research_requires_approval is False
    assert policy.native_research_candidate_only is True
    assert policy.native_research_runtime_safety_truth is False
    assert [type(item).__name__ for item in capabilities] == ["WebSearch", "WebFetch"]
    assert capabilities[0].max_uses == 2
    assert capabilities[1].max_uses == 4
    assert capabilities[0].allowed_domains == ["pydantic.dev", "openrouter.ai"]
    assert capabilities[1].blocked_domains == ["example.com"]
