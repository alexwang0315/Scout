from __future__ import annotations

import os
from typing import Callable

from fastapi import APIRouter, FastAPI

from assistant_context import AssistantContextResolver, query_source_refs
from assistant_models import AssistantBoundary, AssistantSourceRef, ScoutAssistantQuery, ScoutAssistantResponse
from assistant_provider import MockAssistantProvider, ScoutAssistantProvider


def create_assistant_app(
    *,
    provider: ScoutAssistantProvider | None = None,
    context_resolver: AssistantContextResolver | None = None,
) -> FastAPI:
    app = FastAPI(title="Scout Cross-Surface Assistant API")
    app.include_router(create_assistant_router(provider=provider, context_resolver=context_resolver))
    return app


def create_assistant_router(
    *,
    provider: ScoutAssistantProvider | None = None,
    context_resolver: AssistantContextResolver | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/assistant", tags=["assistant"])
    resolved_provider = provider or MockAssistantProvider()
    resolved_context = context_resolver or query_source_refs

    @router.post("/query")
    def query_assistant(query: ScoutAssistantQuery) -> ScoutAssistantResponse:
        sources = resolved_context(query)
        try:
            return resolved_provider.answer(query, sources=sources)
        except Exception as exc:
            return ScoutAssistantResponse(
                surface=query.surface,
                answer=(
                    "Assistant provider failed safely. This response is still a "
                    "read-only model interpretation and no Scout state was changed."
                ),
                sources=sources,
                boundary=AssistantBoundary(surface=query.surface),
                limitations=[
                    f"provider_error_type={type(exc).__name__}",
                    "Provider failure was isolated from the source surface.",
                    "No runtime, planning, outbound, review, or hardware state was changed.",
                ],
            )

    return router


def create_assistant_provider_from_env(
    environ: dict[str, str] | None = None,
    *,
    pydantic_runner: object | None = None,
) -> ScoutAssistantProvider:
    resolved_environ = environ or os.environ
    provider_name = resolved_environ.get("SCOUT_AI_ASSISTANT_PROVIDER", "mock").strip().lower()
    if provider_name != "pydantic_ai":
        return MockAssistantProvider()

    from assistant_pydantic_provider import (
        DEFAULT_MAX_CONTEXT_CHARS,
        DEFAULT_TIMEOUT_SECONDS,
        PydanticAIAssistantProvider,
        PydanticAIEnvRunner,
        create_configured_pydantic_runner,
    )

    config_path = resolved_environ.get("SCOUT_AI_ASSISTANT_CONFIG_PATH")
    if config_path:
        from assistant_model_config import load_assistant_model_config

        model_config = load_assistant_model_config(config_path)
        runner = pydantic_runner or create_configured_pydantic_runner(
            model_config,
            environ=resolved_environ,
        )
        provider = PydanticAIAssistantProvider(
            runner=runner,
            timeout_seconds=model_config.timeout_seconds,
            max_context_chars=model_config.max_context_chars,
        )
        if model_config.connect_on_startup:
            _connect_provider_safely(provider)
        return provider

    timeout_seconds = _int_from_env(
        resolved_environ,
        "SCOUT_AI_ASSISTANT_TIMEOUT_SECONDS",
        DEFAULT_TIMEOUT_SECONDS,
    )
    max_context_chars = _int_from_env(
        resolved_environ,
        "SCOUT_AI_ASSISTANT_MAX_CONTEXT_CHARS",
        DEFAULT_MAX_CONTEXT_CHARS,
    )
    provider = PydanticAIAssistantProvider(
        runner=pydantic_runner or PydanticAIEnvRunner(),
        timeout_seconds=timeout_seconds,
        max_context_chars=max_context_chars,
    )
    return provider


def _int_from_env(environ: dict[str, str], key: str, default: int) -> int:
    try:
        return int(environ.get(key, str(default)))
    except (TypeError, ValueError):
        return default


def _connect_provider_safely(provider: object) -> None:
    connector = getattr(provider, "connect", None)
    if not callable(connector):
        return
    try:
        connector()
    except Exception as exc:
        setattr(provider, "startup_connection_status", f"failed:{type(exc).__name__}")
