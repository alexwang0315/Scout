from pydantic_ai_runtime_compat import (
    build_chat_model,
    normalize_chat_model_name,
    pydantic_agent_runtime_kwargs,
    pydantic_ai_runtime_version,
    pydantic_native_research_capabilities,
    pydantic_usage_limits_from_budget,
)
from scout.schemas.agent_runtime import AgentRunBudget
from scout.agents.model_policy import resolve_model_policy
from scout.agents.pydantic_ai_compat import (
    build_chat_model as build_packaged_chat_model,
    normalize_chat_model_name as normalize_packaged_chat_model_name,
    pydantic_native_research_capabilities as packaged_native_research_capabilities,
    pydantic_ai_runtime_version as packaged_runtime_version,
    pydantic_usage_limits_from_budget as packaged_usage_limits_from_budget,
)


def test_pydantic_ai_runtime_version_supports_slim_install() -> None:
    assert pydantic_ai_runtime_version() == "2.20.0"
    assert packaged_runtime_version() == pydantic_ai_runtime_version()


def test_agent_runtime_kwargs_preserve_scout_tool_end_strategy() -> None:
    assert pydantic_agent_runtime_kwargs() == {"end_strategy": "early"}


def test_usage_limits_are_derived_from_scout_agent_budget() -> None:
    budget = AgentRunBudget(
        max_requests=10,
        max_tool_calls=10,
        max_repairs=10,
        max_input_tokens=12_000,
        max_output_tokens=2_000,
        max_total_tokens=14_000,
    )

    root_limits = pydantic_usage_limits_from_budget(budget)
    packaged_limits = packaged_usage_limits_from_budget(budget)

    assert root_limits.request_limit == budget.max_requests
    assert root_limits.tool_calls_limit == budget.max_tool_calls
    assert root_limits.input_tokens_limit is None
    assert root_limits.output_tokens_limit is None
    assert root_limits.total_tokens_limit is None
    assert packaged_limits == root_limits


def test_repair_usage_limits_keep_fresh_ten_call_capacity() -> None:
    budget = AgentRunBudget(
        max_requests=10,
        max_tool_calls=10,
        max_repairs=10,
        max_input_tokens=16_000,
        max_output_tokens=3_000,
        max_total_tokens=19_000,
    )

    limits = pydantic_usage_limits_from_budget(
        budget,
        request_limit=10,
        tool_calls_limit=10,
        input_tokens_limit=2_000,
        output_tokens_limit=256,
        total_tokens_limit=2_256,
    )

    assert limits.request_limit == 10
    assert limits.tool_calls_limit == 10
    assert limits.input_tokens_limit is None
    assert limits.output_tokens_limit is None
    assert limits.total_tokens_limit is None


def test_productization_can_explicitly_enforce_token_limits() -> None:
    budget = AgentRunBudget(
        enforce_resource_limits=True,
        max_input_tokens=12_000,
        max_output_tokens=2_000,
        max_total_tokens=14_000,
    )

    limits = pydantic_usage_limits_from_budget(budget)

    assert limits.input_tokens_limit == budget.max_input_tokens
    assert limits.output_tokens_limit == budget.max_output_tokens
    assert limits.total_tokens_limit == budget.max_total_tokens


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
    assert model._provider._client.max_retries == 0
    assert packaged_model._provider._client.max_retries == 0


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
    for capability in pydantic_native_research_capabilities(policy):
        assert capability.native is False
        assert capability.local is not None
    for capability in packaged_native_research_capabilities(policy):
        assert capability.native is False
        assert capability.local is not None


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
            "SCOUT_AI_OS_NATIVE_RESEARCH_MAX_SEARCHES": "10",
            "SCOUT_AI_OS_NATIVE_RESEARCH_MAX_FETCHES": "10",
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
    assert capabilities[0].native is False
    assert capabilities[0].local is not None
    assert capabilities[0].max_uses is None
    assert capabilities[1].native is False
    assert capabilities[1].max_uses is None
    assert capabilities[1].max_content_tokens is None
    assert capabilities[1].local is not None
    assert capabilities[0].allowed_domains is None
    assert capabilities[1].blocked_domains == ["example.com"]


def test_openai_chat_keeps_native_search_but_uses_local_fetch() -> None:
    policy = resolve_model_policy(
        "openai-chat:gpt-4o-mini",
        env={
            "SCOUT_AI_OS_NATIVE_RESEARCH": "1",
            "SCOUT_AI_OS_NATIVE_RESEARCH_ALLOWED_DOMAINS": "pydantic.dev",
        },
    )

    capabilities = packaged_native_research_capabilities(policy)

    assert capabilities[0].native is not False
    assert capabilities[0].local is None
    assert capabilities[0].max_uses == 10
    assert capabilities[0].allowed_domains == ["pydantic.dev"]
    assert capabilities[1].native is False
    assert capabilities[1].local is not None
    assert capabilities[1].max_uses is None
    assert capabilities[1].allowed_domains == ["pydantic.dev"]
