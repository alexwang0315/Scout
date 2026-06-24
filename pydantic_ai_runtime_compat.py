"""Compatibility helpers for Scout's Pydantic AI runtime integration."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Any


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


def pydantic_result_output(result: Any) -> Any:
    """Read the output field used by Pydantic AI v2, with v1 fallback."""

    return getattr(result, "output", getattr(result, "data", result))


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

    if _is_openrouter_model(model_name=model_name, base_url=base_url):
        normalized_name = _strip_openrouter_prefix(model_name)
        try:
            from pydantic_ai.models.openrouter import OpenRouterModel
            from pydantic_ai.providers.openrouter import OpenRouterProvider

            return OpenRouterModel(
                normalized_name,
                provider=OpenRouterProvider(api_key=api_key),
            )
        except ImportError:
            # Older Pydantic AI releases did not expose the dedicated
            # OpenRouter provider; keep the OpenAI-compatible path available.
            model_name = normalized_name
            base_url = base_url or "https://openrouter.ai/api/v1"

    try:
        from pydantic_ai.models.openai import OpenAIChatModel
    except ImportError:  # pragma: no cover - compatibility with older pydantic-ai.
        from pydantic_ai.models.openai import OpenAIModel as OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    return OpenAIChatModel(
        model_name,
        provider=OpenAIProvider(base_url=base_url, api_key=api_key),
    )


def _is_openrouter_model(*, model_name: str, base_url: str | None) -> bool:
    return model_name.startswith("openrouter:") or bool(
        base_url and "openrouter.ai" in base_url
    )


def _strip_openrouter_prefix(model_name: str) -> str:
    if model_name.startswith("openrouter:"):
        return model_name.removeprefix("openrouter:")
    return model_name
