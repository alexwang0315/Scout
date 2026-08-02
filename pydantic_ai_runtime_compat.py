"""Compatibility helpers for Scout's Pydantic AI runtime integration."""

from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError, version
from typing import Any


OPENAI_KEY_ENV = "OPENAI_API_KEY"
OPENROUTER_KEY_ENV = "OPENROUTER_API_KEY"
NVIDIA_KEY_ENV = "NVIDIA_API_KEY"
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
AI_HAT_PLUS_2_HAILO_OLLAMA_BASE_URL = "http://127.0.0.1:8000/v1"
LOCAL_OPENAI_COMPATIBLE_API_KEY = "scout-local-openai-compatible"


def pydantic_ai_runtime_version() -> str:
    """Return the installed Pydantic AI runtime package version.

    Scout uses the slim Pydantic AI package on constrained runtimes, so the
    distribution name may be ``pydantic-ai-slim`` rather than ``pydantic-ai``.
    """

    for package_name in ("pydantic-ai", "pydantic-ai-slim"):
        try:
            return version(package_name)
        except PackageNotFoundError:
            continue
    return "not-installed"


def pydantic_agent_runtime_kwargs() -> dict[str, Any]:
    """Return Scout's deterministic defaults for ``pydantic_ai.Agent``."""

    return {"end_strategy": "early"}


def pydantic_usage_limits_from_budget(
    budget: Any,
    *,
    request_limit: int | None = None,
    tool_calls_limit: int | None = None,
    input_tokens_limit: int | None = None,
    output_tokens_limit: int | None = None,
    total_tokens_limit: int | None = None,
) -> Any:
    """Map Scout's typed run budget to Pydantic AI enforcement limits."""

    from scout.agents.pydantic_ai_compat import (
        pydantic_usage_limits_from_budget as packaged_usage_limits_from_budget,
    )

    return packaged_usage_limits_from_budget(
        budget,
        request_limit=request_limit,
        tool_calls_limit=tool_calls_limit,
        input_tokens_limit=input_tokens_limit,
        output_tokens_limit=output_tokens_limit,
        total_tokens_limit=total_tokens_limit,
    )


def pydantic_result_output(result: Any) -> Any:
    """Read the output field used by Pydantic AI v2, with v1 fallback."""

    return getattr(result, "output", getattr(result, "data", result))


def pydantic_native_research_capabilities(policy: Any) -> list[Any]:
    """Build no-approval native research capabilities for trusted Scout runs."""

    from scout.agents.pydantic_ai_compat import (
        pydantic_native_research_capabilities as packaged_capabilities,
    )

    return packaged_capabilities(policy)


def build_chat_model(
    *,
    model_name: str,
    base_url: str | None = None,
    api_key: str | None = None,
) -> Any:
    """Build a Pydantic AI model for Scout cloud calls.

    OpenRouter is handled through Pydantic AI's dedicated v2 provider when the
    configured base URL or model alias indicates OpenRouter. Other OpenAI-like
    endpoints remain on ``OpenAIChatModel`` to preserve the existing Scout
    runtime contract.
    """

    model_name = normalize_chat_model_name(model_name)
    if _is_openrouter_model(model_name=model_name, base_url=base_url):
        normalized_name = _strip_openrouter_prefix(model_name)
        try:
            from pydantic_ai.models.openrouter import OpenRouterModel
            from pydantic_ai.providers.openrouter import OpenRouterProvider

            return OpenRouterModel(
                normalized_name,
                provider=OpenRouterProvider(api_key=api_key or os.getenv(OPENROUTER_KEY_ENV)),
            )
        except ImportError:
            # Older Pydantic AI releases did not expose the dedicated
            # OpenRouter provider; keep the OpenAI-compatible path available.
            model_name = normalized_name
            base_url = base_url or "https://openrouter.ai/api/v1"
    is_nvidia_model = _is_nvidia_model(model_name=model_name, base_url=base_url)
    if is_nvidia_model:
        model_name = _strip_nvidia_prefix(model_name)
        base_url = base_url or NVIDIA_BASE_URL
        api_key = api_key or os.getenv(NVIDIA_KEY_ENV)
    is_hailo_model = _is_hailo_ollama_model(
        model_name=model_name,
        base_url=base_url,
    )
    if is_hailo_model:
        model_name = _strip_hailo_prefix(model_name)
        base_url = base_url or AI_HAT_PLUS_2_HAILO_OLLAMA_BASE_URL
        api_key = api_key or LOCAL_OPENAI_COMPATIBLE_API_KEY

    try:
        from pydantic_ai.models.openai import OpenAIChatModel
    except ImportError:  # pragma: no cover - compatibility with older pydantic-ai.
        from pydantic_ai.models.openai import OpenAIModel as OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    resolved_api_key = _resolve_openai_compatible_api_key(
        base_url=base_url,
        api_key=api_key,
    )
    if is_nvidia_model:
        from openai import AsyncOpenAI

        provider = OpenAIProvider(
            openai_client=AsyncOpenAI(
                base_url=base_url,
                api_key=resolved_api_key,
                max_retries=0,
            )
        )
    else:
        provider = OpenAIProvider(
            base_url=base_url,
            api_key=resolved_api_key,
        )

    if is_hailo_model:
        from scout.agents.pydantic_ai_compat import ScoutHailoOpenAIChatModel

        model_type = ScoutHailoOpenAIChatModel
    else:
        model_type = OpenAIChatModel
    return model_type(
        _strip_openai_chat_prefix(model_name),
        provider=provider,
    )


def normalize_chat_model_name(model_name: str) -> str:
    """Normalize Scout cloud aliases to chat-model semantics.

    Pydantic AI v2 assigns the ``openai:`` model string prefix to the OpenAI
    Responses API. Scout's current assistant/tooling contract is
    Chat-Completions-like, so explicit or env-provided ``openai:`` model names
    are routed through ``OpenAIChatModel`` instead.
    """

    if model_name.startswith("openai:"):
        return "openai-chat:" + model_name.removeprefix("openai:")
    return model_name


def _is_openrouter_model(*, model_name: str, base_url: str | None) -> bool:
    return model_name.startswith("openrouter:") or bool(
        base_url and "openrouter.ai" in base_url
    )


def _is_nvidia_model(*, model_name: str, base_url: str | None) -> bool:
    return model_name.startswith("nvidia:") or bool(
        base_url and "integrate.api.nvidia.com" in base_url
    )


def _is_hailo_ollama_model(*, model_name: str, base_url: str | None) -> bool:
    return model_name.startswith("hailo:") or bool(
        base_url and _is_local_openai_compatible_base_url(base_url)
    )


def _strip_openrouter_prefix(model_name: str) -> str:
    if model_name.startswith("openrouter:"):
        return model_name.removeprefix("openrouter:")
    return model_name


def _strip_nvidia_prefix(model_name: str) -> str:
    if model_name.startswith("nvidia:"):
        return model_name.removeprefix("nvidia:")
    return model_name


def _strip_hailo_prefix(model_name: str) -> str:
    if model_name.startswith("hailo:"):
        return model_name.removeprefix("hailo:")
    return model_name


def _strip_openai_chat_prefix(model_name: str) -> str:
    if model_name.startswith("openai-chat:"):
        return model_name.removeprefix("openai-chat:")
    return model_name


def _resolve_openai_compatible_api_key(
    *,
    base_url: str | None,
    api_key: str | None,
) -> str | None:
    if api_key:
        return api_key
    if base_url and _is_local_openai_compatible_base_url(base_url):
        return LOCAL_OPENAI_COMPATIBLE_API_KEY
    return os.getenv(OPENAI_KEY_ENV)


def _is_local_openai_compatible_base_url(base_url: str) -> bool:
    normalized = base_url.strip().lower()
    return normalized.startswith(("http://127.0.0.1", "http://localhost"))
