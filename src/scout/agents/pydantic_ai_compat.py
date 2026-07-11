"""Pydantic AI compatibility helpers for packaged Scout agents."""

from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from scout.agents.model_policy import ModelPolicy


OPENAI_KEY_ENV = "OPENAI_API_KEY"
OPENROUTER_KEY_ENV = "OPENROUTER_API_KEY"
NVIDIA_KEY_ENV = "NVIDIA_API_KEY"
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
AI_HAT_PLUS_2_HAILO_OLLAMA_BASE_URL = "http://127.0.0.1:8000/v1"
LOCAL_OPENAI_COMPATIBLE_API_KEY = "scout-local-openai-compatible"


def pydantic_ai_runtime_version() -> str:
    for package_name in ("pydantic-ai", "pydantic-ai-slim"):
        try:
            return version(package_name)
        except PackageNotFoundError:
            continue
    return "not-installed"


def pydantic_agent_runtime_kwargs() -> dict[str, Any]:
    return {"end_strategy": "early"}


def pydantic_result_output(result: Any) -> Any:
    return getattr(result, "output", getattr(result, "data", result))


def pydantic_native_research_capabilities(policy: ModelPolicy) -> list[Any]:
    """Build no-approval native research capabilities for trusted Scout runs.

    These are provider/model capabilities, not Scout runtime safety tools.
    Results must remain candidate evidence unless a deterministic Scout
    preparation step later reviews and materializes them.
    """

    if (
        not policy.native_research_enabled
        or getattr(policy.mode, "value", policy.mode) != "external_pydantic_ai"
    ):
        return []

    capabilities: list[Any] = []
    if policy.native_web_search_enabled:
        from pydantic_ai.capabilities.web_search import WebSearch

        capabilities.append(
            WebSearch(
                native=True,
                max_uses=policy.native_research_max_searches,
                allowed_domains=policy.native_research_allowed_domains or None,
                blocked_domains=policy.native_research_blocked_domains or None,
                description=(
                    "Scout trusted native web search. No per-query approval is "
                    "required, but findings are candidate-only and are not "
                    "runtime safety truth."
                ),
            )
        )
    if policy.native_web_fetch_enabled:
        from pydantic_ai.capabilities.web_fetch import WebFetch
        from scout.agents.local_web_fetch import build_local_web_fetch

        capabilities.append(
            WebFetch(
                native=True,
                local=build_local_web_fetch(
                    allowed_domains=policy.native_research_allowed_domains or None,
                    blocked_domains=policy.native_research_blocked_domains or None,
                    max_uses=policy.native_research_max_fetches,
                ),
                allowed_domains=policy.native_research_allowed_domains or None,
                blocked_domains=policy.native_research_blocked_domains or None,
                enable_citations=True,
                max_content_tokens=12000,
                description=(
                    "Scout trusted native web fetch. No per-query approval is "
                    "required, but fetched content is candidate-only and is not "
                    "runtime safety truth."
                ),
            )
        )
    return capabilities


def build_chat_model(
    *,
    model_name: str,
    base_url: str | None = None,
    api_key: str | None = None,
) -> Any:
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
            model_name = normalized_name
            base_url = base_url or "https://openrouter.ai/api/v1"
    if _is_nvidia_model(model_name=model_name, base_url=base_url):
        model_name = _strip_nvidia_prefix(model_name)
        base_url = base_url or NVIDIA_BASE_URL
        api_key = api_key or os.getenv(NVIDIA_KEY_ENV)
    if _is_hailo_ollama_model(model_name=model_name, base_url=base_url):
        model_name = _strip_hailo_prefix(model_name)
        base_url = base_url or AI_HAT_PLUS_2_HAILO_OLLAMA_BASE_URL

    try:
        from pydantic_ai.models.openai import OpenAIChatModel
    except ImportError:  # pragma: no cover - compatibility with older pydantic-ai.
        from pydantic_ai.models.openai import OpenAIModel as OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    return OpenAIChatModel(
        _strip_openai_chat_prefix(model_name),
        provider=OpenAIProvider(
            base_url=base_url,
            api_key=_resolve_openai_compatible_api_key(base_url=base_url, api_key=api_key),
        ),
    )


def normalize_chat_model_name(model_name: str) -> str:
    """Normalize Scout cloud aliases to chat-model semantics.

    Pydantic AI v2 uses the OpenAI Responses API for the ``openai:`` model
    string prefix. Scout's existing provider path is intentionally
    Chat-Completions-like and side-effect constrained, so ``openai:`` is
    normalized to ``openai-chat:`` before constructing a model object.
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
