"""Model selection policy for Scout AI OS Pydantic AI providers."""

from __future__ import annotations

import os
from enum import Enum
from typing import Any

from scout.schemas.base import SchemaModel


DEFAULT_LOCAL_MODEL_LABEL = "local FunctionModel"
SCOUT_MODEL_ENV = "SCOUT_AI_OS_MODEL"
OPENROUTER_KEY_ENV = "OPENROUTER_API_KEY"
MODEL_TIMEOUT_ENV = "SCOUT_AI_OS_MODEL_TIMEOUT_SECONDS"
MODEL_MAX_COST_ENV = "SCOUT_AI_OS_MODEL_MAX_COST_USD"
MODEL_ESTIMATED_CALL_COST_ENV = "SCOUT_AI_OS_MODEL_ESTIMATED_CALL_COST_USD"
MODEL_FALLBACK_ENV = "SCOUT_AI_OS_MODEL_FALLBACK"
DEFAULT_MODEL_TIMEOUT_SECONDS = 30.0
DEFAULT_EXTERNAL_MODEL_ESTIMATED_CALL_COST_USD = 0.001


class ModelPolicyMode(str, Enum):
    LOCAL_FUNCTION = "local_function"
    EXTERNAL_PYDANTIC_AI = "external_pydantic_ai"


class ModelPolicySource(str, Enum):
    DEFAULT = "default"
    ENV = "env"
    EXPLICIT = "explicit"


class ModelPolicy(SchemaModel):
    """Resolved model choice without carrying secret values."""

    mode: ModelPolicyMode
    source: ModelPolicySource
    requested_model: str | None = None
    pydantic_ai_model: str | None = None
    display_name: str
    requires_network: bool
    required_credential_env: list[str] = []
    missing_credential_env: list[str] = []
    timeout_seconds: float = DEFAULT_MODEL_TIMEOUT_SECONDS
    max_cost_usd: float | None = None
    estimated_call_cost_usd: float = 0.0
    fallback_model: str = DEFAULT_LOCAL_MODEL_LABEL

    @property
    def model_for_agent(self) -> str | None:
        return self.pydantic_ai_model


def resolve_model_policy(
    model: Any | None = None,
    *,
    env: dict[str, str] | None = None,
) -> ModelPolicy:
    """Resolve model precedence for Pydantic AI smoke and API wiring."""

    env_map = os.environ if env is None else env
    timeout_seconds = _float_env(
        env_map,
        MODEL_TIMEOUT_ENV,
        default=DEFAULT_MODEL_TIMEOUT_SECONDS,
        minimum=0.001,
    )
    max_cost_usd = _optional_float_env(
        env_map,
        MODEL_MAX_COST_ENV,
        minimum=0.0,
    )
    estimated_call_cost_usd = _optional_float_env(
        env_map,
        MODEL_ESTIMATED_CALL_COST_ENV,
        minimum=0.0,
    )
    fallback_model = _normalize_fallback_model(env_map.get(MODEL_FALLBACK_ENV))
    if model is not None:
        requested = str(model).strip()
        source = ModelPolicySource.EXPLICIT
    else:
        requested = str(env_map.get(SCOUT_MODEL_ENV) or "").strip()
        source = ModelPolicySource.ENV if requested else ModelPolicySource.DEFAULT

    if not requested or _is_local_model_alias(requested):
        return ModelPolicy(
            mode=ModelPolicyMode.LOCAL_FUNCTION,
            source=source,
            requested_model=requested or None,
            pydantic_ai_model=None,
            display_name=DEFAULT_LOCAL_MODEL_LABEL,
            requires_network=False,
            timeout_seconds=timeout_seconds,
            max_cost_usd=max_cost_usd,
            estimated_call_cost_usd=estimated_call_cost_usd or 0.0,
            fallback_model=fallback_model,
        )

    normalized_model = _normalize_external_model(requested)
    required_credential_env = _required_credential_env(normalized_model)
    missing_credential_env = [
        name for name in required_credential_env if not env_map.get(name)
    ]
    return ModelPolicy(
        mode=ModelPolicyMode.EXTERNAL_PYDANTIC_AI,
        source=source,
        requested_model=requested,
        pydantic_ai_model=normalized_model,
        display_name=normalized_model,
        requires_network=True,
        required_credential_env=required_credential_env,
        missing_credential_env=missing_credential_env,
        timeout_seconds=timeout_seconds,
        max_cost_usd=max_cost_usd,
        estimated_call_cost_usd=(
            estimated_call_cost_usd
            if estimated_call_cost_usd is not None
            else DEFAULT_EXTERNAL_MODEL_ESTIMATED_CALL_COST_USD
        ),
        fallback_model=fallback_model,
    )


def _is_local_model_alias(value: str) -> bool:
    normalized = value.strip().casefold().replace("-", "_").replace(" ", "_")
    return normalized in {
        "local",
        "function",
        "function_model",
        "functionmodel",
        "local_function",
        "local_function_model",
    }


def _normalize_external_model(value: str) -> str:
    normalized = value.strip()
    aliases = {
        "gpt-4o-mini": "openrouter:openai/gpt-4o-mini",
        "openai/gpt-4o-mini": "openrouter:openai/gpt-4o-mini",
        "glm-5.2": "openrouter:z-ai/glm-5.2",
        "z-ai/glm-5.2": "openrouter:z-ai/glm-5.2",
        "gemma-3-27b": "openrouter:google/gemma-3-27b-it",
        "gemma3-27b": "openrouter:google/gemma-3-27b-it",
        "google/gemma-3-27b-it": "openrouter:google/gemma-3-27b-it",
    }
    return aliases.get(normalized.casefold(), normalized)


def _required_credential_env(model: str) -> list[str]:
    if model.startswith("openrouter:"):
        return [OPENROUTER_KEY_ENV]
    return []


def _float_env(
    env: dict[str, str],
    name: str,
    *,
    default: float,
    minimum: float,
) -> float:
    raw_value = env.get(name)
    if not raw_value:
        return default
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum:g}")
    return value


def _optional_float_env(
    env: dict[str, str],
    name: str,
    *,
    minimum: float,
) -> float | None:
    raw_value = env.get(name)
    if not raw_value:
        return None
    return _float_env(env, name, default=minimum, minimum=minimum)


def _normalize_fallback_model(value: str | None) -> str:
    if value is None or not value.strip() or _is_local_model_alias(value):
        return DEFAULT_LOCAL_MODEL_LABEL
    return _normalize_external_model(value)


__all__ = [
    "DEFAULT_LOCAL_MODEL_LABEL",
    "DEFAULT_MODEL_TIMEOUT_SECONDS",
    "MODEL_FALLBACK_ENV",
    "MODEL_MAX_COST_ENV",
    "MODEL_TIMEOUT_ENV",
    "ModelPolicy",
    "ModelPolicyMode",
    "ModelPolicySource",
    "OPENROUTER_KEY_ENV",
    "SCOUT_MODEL_ENV",
    "resolve_model_policy",
]
