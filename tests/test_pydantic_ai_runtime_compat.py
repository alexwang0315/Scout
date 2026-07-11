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
    assert pydantic_ai_runtime_version() == "2.8.0"
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


def test_nvidia_prefix_builds_openai_compatible_chat_model() -> None:
    model = build_chat_model(
        model_name="nvidia:z-ai/glm-5.2",
        api_key="test-token",
    )
    packaged_model = build_packaged_chat_model(
        model_name="nvidia:z-ai/glm-5.2",
        api_key="test-token",
    )

    assert type(model).__name__ == "OpenAIChatModel"
    assert type(packaged_model).__name__ == "OpenAIChatModel"
    assert model.model_name == "z-ai/glm-5.2"
    assert packaged_model.model_name == model.model_name


def test_hailo_prefix_builds_local_openai_compatible_chat_model_without_cloud_key() -> None:
    model = build_chat_model(model_name="hailo:qwen2.5:1.5b")
    packaged_model = build_packaged_chat_model(model_name="hailo:qwen2.5:1.5b")

    assert type(model).__name__ == "OpenAIChatModel"
    assert type(packaged_model).__name__ == "OpenAIChatModel"
    assert model.model_name == "qwen2.5:1.5b"
    assert packaged_model.model_name == model.model_name


def test_local_base_url_builds_openai_compatible_chat_model_without_cloud_key() -> None:
    model = build_chat_model(
        model_name="qwen2.5:1.5b",
        base_url="http://127.0.0.1:8000/v1",
    )
    packaged_model = build_packaged_chat_model(
        model_name="qwen2.5:1.5b",
        base_url="http://127.0.0.1:8000/v1",
    )

    assert type(model).__name__ == "OpenAIChatModel"
    assert type(packaged_model).__name__ == "OpenAIChatModel"
    assert model.model_name == "qwen2.5:1.5b"
    assert packaged_model.model_name == model.model_name


def test_native_research_capabilities_are_on_by_default_for_external_models() -> None:
    policy = resolve_model_policy("openrouter:z-ai/glm-5.2", env={})

    assert policy.native_research_enabled is True
    assert policy.native_web_search_enabled is True
    assert policy.native_web_fetch_enabled is True
    assert [type(item).__name__ for item in pydantic_native_research_capabilities(policy)] == [
        "WebSearch",
        "WebFetch",
    ]
    assert [type(item).__name__ for item in packaged_native_research_capabilities(policy)] == [
        "WebSearch",
        "WebFetch",
    ]


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
    assert capabilities[1].max_uses is None
    assert capabilities[1].local is not None
    assert capabilities[0].allowed_domains == ["pydantic.dev", "openrouter.ai"]
    assert capabilities[1].blocked_domains == ["example.com"]
