"""Explicit OpenAI-compatible backend for the experimental Scout Model Gateway."""

from __future__ import annotations

import asyncio
import contextvars
import ipaddress
import os
import re
import threading
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, model_validator

from scout.nextgen.model_gateway import (
    BackendInferenceResult,
    ModelInferenceRequest,
    ModelThinkingSetting,
    PydanticAIStructuredBackend,
    ScoutModelGateway,
)
from scout.nextgen.model_runtime import (
    AcceleratorKind,
    Locality,
    ModelRuntimeCapability,
    ModelRuntimeProfile,
    ModelRuntimeTier,
)
from scout.schemas.base import NonEmptyStr, SchemaModel

if TYPE_CHECKING:
    from scout.nextgen.praison_service import PraisonModelGatewayRuntime

LOCAL_PLACEHOLDER_API_KEY = "scout-local-openai-compatible"
MAX_RUNTIME_CONFIG_BYTES = 64 * 1024
_ENV_NAME_PATTERN = re.compile(r"^SCOUT_[A-Z0-9_]*(?:KEY|TOKEN)$")
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class OpenAICompatibleTransportScope(StrEnum):
    LOOPBACK = "loopback"
    PRIVATE_NETWORK = "private_network"
    REMOTE_HTTPS = "remote_https"


class OpenAICompatibleConfigurationError(RuntimeError):
    pass


class OpenAICompatibleBackendConfig(SchemaModel):
    runtime_id: NonEmptyStr
    provider: NonEmptyStr
    model_id: NonEmptyStr
    base_url: NonEmptyStr
    transport_scope: OpenAICompatibleTransportScope
    tier: ModelRuntimeTier
    locality: Locality
    accelerator: AcceleratorKind = AcceleratorKind.NONE
    context_limit_tokens: int = Field(ge=1)
    max_concurrency: int = Field(default=1, ge=1)
    offline_capable: bool = False
    privacy_preserving: bool = False
    api_key_env: str | None = None
    accepted_observed_model_ids: tuple[NonEmptyStr, ...] = ()
    max_output_tokens: int | None = Field(default=None, ge=1)
    temperature: float | None = Field(default=None, ge=0, le=2)
    thinking: ModelThinkingSetting | None = None
    supports_reasoning_control: bool = False
    uses_max_completion_tokens: bool = True
    structured_output_mode: Literal["tool", "native"] = "tool"
    experimental: Literal[True] = True
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @model_validator(mode="after")
    def validate_transport_and_runtime(self) -> "OpenAICompatibleBackendConfig":
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("base_url must be an absolute HTTP(S) URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("base_url must not contain credentials")
        if parsed.query or parsed.fragment:
            raise ValueError("base_url must not contain query or fragment data")
        hostname = parsed.hostname.lower()
        if self.transport_scope is OpenAICompatibleTransportScope.LOOPBACK:
            if hostname not in _LOOPBACK_HOSTS:
                raise ValueError("loopback transport requires a loopback hostname")
            if self.locality is Locality.CLOUD:
                raise ValueError("loopback transport cannot declare cloud locality")
        elif self.transport_scope is OpenAICompatibleTransportScope.PRIVATE_NETWORK:
            if not _is_private_network_host(hostname):
                raise ValueError(
                    "private_network transport requires a private IP or .local host"
                )
            if self.locality is Locality.CLOUD:
                raise ValueError("private network transport cannot declare cloud locality")
        else:
            if parsed.scheme != "https":
                raise ValueError("remote_https requires HTTPS")
            if hostname in _LOOPBACK_HOSTS or _is_private_network_host(hostname):
                raise ValueError(
                    "remote_https cannot target a loopback or private-network host"
                )
        if self.transport_scope is OpenAICompatibleTransportScope.REMOTE_HTTPS:
            if not self.api_key_env:
                raise ValueError("remote_https requires api_key_env")
        if self.api_key_env and not _ENV_NAME_PATTERN.fullmatch(self.api_key_env):
            raise ValueError(
                "api_key_env must be a Scout-owned *_KEY or *_TOKEN variable"
            )
        if self.api_key_env and parsed.scheme != "https":
            raise ValueError("named model credentials require HTTPS")
        if len(self.accepted_observed_model_ids) != len(
            set(self.accepted_observed_model_ids)
        ):
            raise ValueError("accepted observed model ids must be unique")
        if self.thinking is not None and not self.supports_reasoning_control:
            raise ValueError(
                "thinking requires explicit provider reasoning control support"
            )
        if self.offline_capable and self.transport_scope is (
            OpenAICompatibleTransportScope.REMOTE_HTTPS
        ):
            raise ValueError("remote_https backends cannot be offline capable")
        if self.locality is not Locality.CLOUD and self.max_concurrency != 1:
            raise ValueError("edge and local-server model concurrency must be one")
        self.to_runtime_profile()
        return self

    @classmethod
    def from_json_file(cls, path: Path) -> "OpenAICompatibleBackendConfig":
        raw = path.read_bytes()
        if len(raw) > MAX_RUNTIME_CONFIG_BYTES:
            raise ValueError("model runtime config exceeds the Scout size limit")
        return cls.model_validate_json(raw)

    @property
    def normalized_base_url(self) -> str:
        return self.base_url.rstrip("/")

    def to_runtime_profile(self) -> ModelRuntimeProfile:
        capabilities = {
            ModelRuntimeCapability.CHAT,
            ModelRuntimeCapability.STRUCTURED_OUTPUT,
        }
        if self.offline_capable:
            capabilities.add(ModelRuntimeCapability.OFFLINE)
        return ModelRuntimeProfile(
            runtime_id=self.runtime_id,
            tier=self.tier,
            provider=self.provider,
            model_id=self.model_id,
            locality=self.locality,
            accelerator=self.accelerator,
            endpoint=self.normalized_base_url,
            capabilities=frozenset(capabilities),
            context_limit_tokens=self.context_limit_tokens,
            max_concurrency=self.max_concurrency,
            offline_capable=self.offline_capable,
            privacy_preserving=self.privacy_preserving,
            experimental=True,
        )

    def model_settings(self, *, timeout_seconds: float | None = None) -> dict[str, Any]:
        settings: dict[str, Any] = {}
        if timeout_seconds is not None:
            settings["timeout"] = timeout_seconds
        if self.max_output_tokens is not None:
            settings["max_tokens"] = self.max_output_tokens
        if self.temperature is not None:
            settings["temperature"] = self.temperature
        if self.thinking is not None:
            settings["thinking"] = self.thinking
        return settings


class OpenAICompatiblePydanticBackend:
    """Execute typed Pydantic AI calls against one explicit HTTP endpoint."""

    def __init__(
        self,
        *,
        config: OpenAICompatibleBackendConfig,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        from openai import AsyncOpenAI
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.profiles.openai import OpenAIModelProfile
        from pydantic_ai.providers.openai import OpenAIProvider

        self.config = config
        self.runtime_id = config.runtime_id
        self.model_id = config.model_id
        api_key = _resolve_api_key(config, environ if environ is not None else os.environ)
        self._client = AsyncOpenAI(
            base_url=config.normalized_base_url,
            api_key=api_key,
            max_retries=0,
        )
        provider = OpenAIProvider(openai_client=self._client)
        provider_model = OpenAIChatModel(
            config.model_id,
            provider=provider,
            profile=OpenAIModelProfile(
                supports_tools=True,
                supports_json_schema_output=(
                    config.structured_output_mode == "native"
                ),
                default_structured_output_mode=config.structured_output_mode,
                supports_thinking=config.supports_reasoning_control,
                openai_supports_reasoning=config.supports_reasoning_control,
                openai_supports_reasoning_effort_none=(
                    config.supports_reasoning_control
                ),
                openai_chat_supports_max_completion_tokens=(
                    config.uses_max_completion_tokens
                ),
            ),
        )
        counted_model = _RequestCountingModel(provider_model)
        self._delegate = PydanticAIStructuredBackend(
            runtime_id=config.runtime_id,
            model_id=config.model_id,
            model=counted_model,
            default_model_settings=config.model_settings(),
        )
        self.resident_model = counted_model
        self._closed = False

    def infer(
        self,
        *,
        request: ModelInferenceRequest,
        output_type: type[BaseModel],
        model_request_limit: int,
        cancellation_event: threading.Event,
    ) -> BackendInferenceResult:
        return self._delegate.infer(
            request=request,
            output_type=output_type,
            model_request_limit=model_request_limit,
            cancellation_event=cancellation_event,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if not self._client.is_closed():
            asyncio.run(self._client.close())


def build_praison_openai_compatible_runtime(
    *,
    config: OpenAICompatibleBackendConfig,
    environ: Mapping[str, str] | None = None,
) -> "PraisonModelGatewayRuntime":
    from scout.nextgen.praison_service import PraisonModelGatewayRuntime

    backend = OpenAICompatiblePydanticBackend(
        config=config,
        environ=environ,
    )
    gateway = ScoutModelGateway(
        profiles=(config.to_runtime_profile(),),
        backends=(backend,),
        max_local_concurrency=1,
        max_cloud_concurrency=(
            config.max_concurrency if config.locality is Locality.CLOUD else 1
        ),
    )
    return PraisonModelGatewayRuntime(
        gateway=gateway,
        allowed_tiers=frozenset({config.tier}),
        prefer_local=config.locality is not Locality.CLOUD,
        allow_cloud=config.locality is Locality.CLOUD,
        requires_offline=config.offline_capable,
    )


def _resolve_api_key(
    config: OpenAICompatibleBackendConfig,
    environ: Mapping[str, str],
) -> str:
    if config.api_key_env is not None:
        value = environ.get(config.api_key_env)
        if not value:
            raise OpenAICompatibleConfigurationError(
                "configured credential environment variable is unavailable"
            )
        return value
    if config.transport_scope is OpenAICompatibleTransportScope.REMOTE_HTTPS:
        raise OpenAICompatibleConfigurationError(
            "remote model credential configuration is unavailable"
        )
    return LOCAL_PLACEHOLDER_API_KEY


def _is_private_network_host(hostname: str) -> bool:
    if hostname.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return address.is_private or address.is_link_local


def _RequestCountingModel(inner_model: Any) -> Any:  # noqa: N802 - model factory
    from pydantic_ai.models import Model

    class RequestCountingModel(Model):
        def __init__(self, inner: Any) -> None:
            super().__init__(settings=inner.settings, profile=inner.profile)
            self.inner = inner
            self.request_count = 0
            self._request_count_lock = threading.Lock()
            self._request_scope: contextvars.ContextVar[list[int] | None] = (
                contextvars.ContextVar(
                    f"scout_model_request_scope_{id(self)}",
                    default=None,
                )
            )

        @property
        def model_name(self) -> str:
            return self.inner.model_name

        @property
        def system(self) -> str:
            return self.inner.system

        @property
        def provider(self) -> Any:
            return self.inner.provider

        @property
        def base_url(self) -> str | None:
            return self.inner.base_url

        def customize_request_parameters(self, parameters: Any) -> Any:
            return self.inner.customize_request_parameters(parameters)

        def begin_request_scope(self) -> tuple[Any, list[int]]:
            counter = [0]
            token = self._request_scope.set(counter)
            return token, counter

        def finish_request_scope(self, scope: tuple[Any, list[int]]) -> int:
            token, counter = scope
            self._request_scope.reset(token)
            return counter[0]

        async def request(
            self,
            messages: list[Any],
            model_settings: Any,
            model_request_parameters: Any,
        ) -> Any:
            with self._request_count_lock:
                self.request_count += 1
            scoped_counter = self._request_scope.get()
            if scoped_counter is not None:
                scoped_counter[0] += 1
            return await self.inner.request(
                messages,
                model_settings,
                model_request_parameters,
            )

        async def count_tokens(
            self,
            messages: list[Any],
            model_settings: Any,
            model_request_parameters: Any,
        ) -> Any:
            return await self.inner.count_tokens(
                messages,
                model_settings,
                model_request_parameters,
            )

    return RequestCountingModel(inner_model)


__all__ = [
    "OpenAICompatibleBackendConfig",
    "OpenAICompatibleConfigurationError",
    "OpenAICompatiblePydanticBackend",
    "OpenAICompatibleTransportScope",
    "build_praison_openai_compatible_runtime",
]
