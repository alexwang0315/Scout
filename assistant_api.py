from __future__ import annotations

import json
import os
import time
from typing import Callable

from fastapi import APIRouter, FastAPI

from assistant_context import AssistantContextResolver, query_source_refs
from assistant_models import (
    AssistantBoundary,
    AssistantObservability,
    AssistantSourceRef,
    ScoutAssistantQuery,
    ScoutAssistantResponse,
)
from assistant_provider import FailedAssistantProvider, MockAssistantProvider, ScoutAssistantProvider


def create_assistant_app(
    *,
    provider: ScoutAssistantProvider | None = None,
    context_resolver: AssistantContextResolver | None = None,
    provider_status: dict[str, object] | None = None,
) -> FastAPI:
    app = FastAPI(title="Scout Cross-Surface Assistant API")
    app.include_router(
        create_assistant_router(
            provider=provider,
            context_resolver=context_resolver,
            provider_status=provider_status,
        )
    )
    return app


def create_assistant_router(
    *,
    provider: ScoutAssistantProvider | None = None,
    context_resolver: AssistantContextResolver | None = None,
    provider_status: dict[str, object] | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/assistant", tags=["assistant"])
    resolved_provider = provider or MockAssistantProvider()
    resolved_context = context_resolver or query_source_refs
    resolved_provider_status = provider_status or create_assistant_provider_status(
        provider=resolved_provider
    )

    @router.post("/query")
    def query_assistant(query: ScoutAssistantQuery) -> ScoutAssistantResponse:
        started_at = time.perf_counter()
        sources = resolved_context(query)
        try:
            response = resolved_provider.answer(query, sources=sources)
            return _with_observability(
                response,
                provider=resolved_provider,
                sources=sources,
                started_at=started_at,
                safe_failure=isinstance(resolved_provider, FailedAssistantProvider),
            )
        except Exception as exc:
            response = ScoutAssistantResponse(
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
            return _with_observability(
                response,
                provider=resolved_provider,
                sources=sources,
                started_at=started_at,
                safe_failure=True,
            )

    @router.get("/status")
    def assistant_status() -> dict[str, object]:
        return dict(resolved_provider_status)

    return router


def create_assistant_provider_status(
    *,
    provider: ScoutAssistantProvider,
    environ: dict[str, str] | None = None,
) -> dict[str, object]:
    resolved_environ = environ or os.environ
    provider_name = resolved_environ.get("SCOUT_AI_ASSISTANT_PROVIDER", "mock").strip().lower()
    runtime_profile = resolved_environ.get("SCOUT_RUNTIME_PROFILE", "dev").strip() or "dev"
    status: dict[str, object] = {
        "read_only": True,
        "model_interpretation": True,
        "provider": provider_name,
        "provider_class": type(provider).__name__,
        "runtime_profile": runtime_profile,
        "startup_connection_status": getattr(provider, "startup_connection_status", "not_checked"),
        "config_path_configured": bool(resolved_environ.get("SCOUT_AI_ASSISTANT_CONFIG_PATH")),
        "config_loaded": False,
        "cloud_only": False,
        "local_fallback_enabled": False,
        "local_fallback_mode": "disabled",
        "manual_verification_required": False,
        "local_fallback_max_concurrency": 1,
        "readiness_starts_local_model": False,
        "local_model_listener_required_for_readiness": False,
        "status_model_switch_allowed": False,
        "token_values_exposed": False,
    }
    config_path = resolved_environ.get("SCOUT_AI_ASSISTANT_CONFIG_PATH")
    if not config_path:
        return status

    try:
        from assistant_model_config import load_assistant_model_config

        model_config = load_assistant_model_config(config_path)
    except Exception as exc:
        status.update(
            {
                "config_error_type": type(exc).__name__,
                "config_loaded": False,
            }
        )
        return status

    local_fallback_enabled = model_config.fallback_to_local_on_error
    pi_field_profile = runtime_profile == "pi-field"
    if not local_fallback_enabled:
        local_fallback_mode = "disabled"
    elif pi_field_profile:
        local_fallback_mode = "pi_field_manual_opt_in"
    else:
        local_fallback_mode = "configured_not_pi_field"

    status.update(
        {
            "config_loaded": True,
            "active_profile": model_config.active_profile,
            "cloud_model": model_config.cloud_model.model_name,
            "local_model": model_config.local_model.model_name,
            "timeout_seconds": model_config.timeout_seconds,
            "max_context_chars": model_config.max_context_chars,
            "connect_on_startup": model_config.connect_on_startup,
            "local_fallback_enabled": local_fallback_enabled,
            "local_fallback_fixed_schema": model_config.local_fallback_fixed_schema,
            "local_fallback_mode": local_fallback_mode,
            "manual_verification_required": local_fallback_enabled and pi_field_profile,
            "cloud_only": model_config.active_profile == "cloud"
            and not local_fallback_enabled,
        }
    )
    return status


def _with_observability(
    response: ScoutAssistantResponse,
    *,
    provider: ScoutAssistantProvider,
    sources: list[AssistantSourceRef],
    started_at: float,
    safe_failure: bool,
) -> ScoutAssistantResponse:
    latency_ms = max(0, int((time.perf_counter() - started_at) * 1000))
    if safe_failure:
        latency_class = "timeout_or_error"
    elif latency_ms >= 2000:
        latency_class = "slow"
    else:
        latency_class = "fast"
    context_size_chars = len(
        json.dumps(
            [source.model_dump(mode="json") for source in sources],
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    observability = AssistantObservability(
        provider_class=type(provider).__name__,
        source_count=len(sources),
        selected_source_count=sum(1 for source in sources if source.selected),
        context_size_chars=context_size_chars,
        latency_ms=latency_ms,
        latency_class=latency_class,
        safe_failure=safe_failure,
        model_profile_used=_provider_metadata(provider, "last_profile"),
        failover_reason=_provider_metadata(provider, "last_failover_reason"),
        local_model_name=_provider_metadata(provider, "local_model_name"),
    )
    return response.model_copy(update={"observability": observability})


def _provider_metadata(provider: ScoutAssistantProvider, name: str) -> str | None:
    value = getattr(provider, name, None)
    if value is None:
        runner = getattr(provider, "runner", None)
        value = getattr(runner, name, None)
    return str(value) if value is not None else None


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

        try:
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
        except Exception as exc:
            return FailedAssistantProvider(
                error_type=type(exc).__name__,
                error_message=str(exc),
            )

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
