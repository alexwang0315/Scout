"""Scout-owned model runtime contracts for local, MAX, Hailo, and cloud backends.

The router in this module is deliberately small: it selects a runtime profile
and records the reason, but it never calls a provider. Existing Pydantic AI
providers and `ModelSlaGateway` remain the executable model path until a backend
is explicitly adapted behind this contract.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field, model_validator

from scout.schemas.base import NonEmptyStr, SchemaModel


class ModelRuntimeTier(StrEnum):
    """Logical model role. Agent code should depend on this, not providers."""

    LOCAL_FAST = "local_fast"
    LOCAL_REASONING = "local_reasoning"
    LOCAL_VLM = "local_vlm"
    HAILO_LOCAL = "hailo_local"
    MAX_LOCAL_OR_SERVER = "max_local_or_server"
    CLOUD_REASONING = "cloud_reasoning"
    CLOUD_RESEARCH = "cloud_research"


class Locality(StrEnum):
    EDGE = "edge"
    MAC_SERVER = "mac_server"
    CLOUD = "cloud"


class ModelRuntimeHostKind(StrEnum):
    """Execution host required by a runtime profile."""

    GENERIC = "generic"
    RASPBERRY_PI = "raspberry_pi"


def detect_model_runtime_host_kind() -> ModelRuntimeHostKind:
    """Detect a Raspberry Pi without trusting a caller-provided environment flag."""

    try:
        model = Path("/proc/device-tree/model").read_text(
            encoding="utf-8",
            errors="ignore",
        )
    except OSError:
        return ModelRuntimeHostKind.GENERIC
    return (
        ModelRuntimeHostKind.RASPBERRY_PI
        if "raspberry pi" in model.lower()
        else ModelRuntimeHostKind.GENERIC
    )


class AcceleratorKind(StrEnum):
    CPU = "cpu"
    GPU = "gpu"
    HAILO_10H = "hailo_10h"
    NONE = "none"


class ModelRuntimeCapability(StrEnum):
    CHAT = "chat"
    STREAMING = "streaming"
    STRUCTURED_OUTPUT = "structured_output"
    SMALL_TYPED_OUTPUT = "small_typed_output"
    SLOW_BACKGROUND_REASONING = "slow_background_reasoning"
    TOOL_CALLING = "tool_calling"
    VISION = "vision"
    AUDIO = "audio"
    EMBEDDINGS = "embeddings"
    OFFLINE = "offline"


class ModelCapabilityAttestation(SchemaModel):
    """Time-bounded proof that a server-owned qualification passed."""

    schema_version: Literal["scout.model_capability_attestation.v0"] = (
        "scout.model_capability_attestation.v0"
    )
    runtime_id: NonEmptyStr
    provider: NonEmptyStr
    model_id: NonEmptyStr
    runtime_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    qualification_report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    capabilities: frozenset[ModelRuntimeCapability] = Field(min_length=1)
    qualified_at: datetime
    expires_at: datetime
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @model_validator(mode="after")
    def validate_attestation(self) -> "ModelCapabilityAttestation":
        if self.capabilities.difference({ModelRuntimeCapability.TOOL_CALLING}):
            raise ValueError("unsupported model capability attestation")
        if self.qualified_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("model capability attestation timestamps must be aware")
        if self.expires_at <= self.qualified_at:
            raise ValueError("model capability attestation must expire after qualification")
        return self

    def is_expired(self, *, now: datetime | None = None) -> bool:
        checked_at = now or datetime.now(UTC)
        if checked_at.tzinfo is None:
            raise ValueError("attestation expiry check requires an aware timestamp")
        return checked_at >= self.expires_at


class ModelRuntimeProfile(SchemaModel):
    """Static capability record for a selectable model runtime."""

    runtime_id: NonEmptyStr
    tier: ModelRuntimeTier
    provider: NonEmptyStr
    model_id: NonEmptyStr
    locality: Locality
    required_host_kind: ModelRuntimeHostKind = ModelRuntimeHostKind.GENERIC
    accelerator: AcceleratorKind = AcceleratorKind.NONE
    endpoint: str | None = None
    capabilities: frozenset[ModelRuntimeCapability]
    capability_attestation_refs: tuple[NonEmptyStr, ...] = ()
    context_limit_tokens: int = Field(ge=1)
    max_concurrency: int = Field(default=1, ge=1)
    estimated_latency_ms: int | None = Field(default=None, ge=0)
    estimated_memory_mb: int | None = Field(default=None, ge=0)
    offline_capable: bool = False
    privacy_preserving: bool = False
    experimental: bool = True
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @model_validator(mode="after")
    def validate_runtime_boundary(self) -> "ModelRuntimeProfile":
        if (
            self.required_host_kind is ModelRuntimeHostKind.RASPBERRY_PI
            and self.locality is not Locality.EDGE
        ):
            raise ValueError("Raspberry Pi runtimes must declare edge locality")
        if self.locality == Locality.CLOUD and self.offline_capable:
            raise ValueError("cloud model runtimes cannot be offline_capable")
        if self.tier == ModelRuntimeTier.HAILO_LOCAL:
            if self.accelerator != AcceleratorKind.HAILO_10H:
                raise ValueError("hailo_local runtimes must declare HAILO_10H")
            if not self.offline_capable:
                raise ValueError("hailo_local runtimes must be offline capable")
            if not {
                ModelRuntimeCapability.CHAT,
                ModelRuntimeCapability.SMALL_TYPED_OUTPUT,
            }.issubset(self.capabilities):
                raise ValueError(
                    "hailo_local runtimes require chat and small typed output"
                )
            if ModelRuntimeCapability.STRUCTURED_OUTPUT in self.capabilities:
                raise ValueError(
                    "hailo_local runtimes cannot claim unrestricted structured output"
                )
        if (
            self.tier == ModelRuntimeTier.MAX_LOCAL_OR_SERVER
            and self.accelerator == AcceleratorKind.HAILO_10H
        ):
            raise ValueError("MAX and Hailo are sibling runtime backends")
        if self.offline_capable and ModelRuntimeCapability.OFFLINE not in self.capabilities:
            raise ValueError("offline_capable profiles must include OFFLINE capability")
        if ModelRuntimeCapability.SLOW_BACKGROUND_REASONING in self.capabilities:
            if (
                self.provider.lower() != "ollama"
                or self.accelerator != AcceleratorKind.CPU
                or self.locality != Locality.EDGE
                or self.required_host_kind is not ModelRuntimeHostKind.RASPBERRY_PI
            ):
                raise ValueError(
                    "slow background reasoning is reserved for a Raspberry Pi edge runtime"
                )
            endpoint_host = urlsplit(self.endpoint or "").hostname
            if endpoint_host not in {"127.0.0.1", "localhost", "::1"}:
                raise ValueError(
                    "Raspberry Pi CPU background reasoning must use loopback Ollama"
                )
        if len(self.capability_attestation_refs) != len(
            set(self.capability_attestation_refs)
        ):
            raise ValueError("capability attestation refs must be unique")
        return self

    def supports(self, required: Iterable[ModelRuntimeCapability]) -> bool:
        return set(required).issubset(self.capabilities)


class ModelRuntimeRequest(SchemaModel):
    """A provider-neutral request used for runtime selection."""

    request_id: UUID
    task: NonEmptyStr
    required_capabilities: frozenset[ModelRuntimeCapability] = frozenset(
        {ModelRuntimeCapability.CHAT}
    )
    allowed_tiers: frozenset[ModelRuntimeTier] | None = None
    prefer_local: bool = True
    allow_cloud: bool = False
    requires_offline: bool = False
    privacy_sensitive: bool = False
    max_latency_ms: int | None = Field(default=None, ge=1)
    min_context_tokens: int = Field(default=1, ge=1)
    max_model_requests: int = Field(default=10, ge=10)
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


class ModelRuntimeSelection(SchemaModel):
    request_id: UUID
    selected_runtime: ModelRuntimeProfile | None
    reason: NonEmptyStr
    considered_runtime_ids: tuple[NonEmptyStr, ...]
    rejected_reasons: dict[NonEmptyStr, NonEmptyStr] = Field(default_factory=dict)
    selected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @property
    def selected(self) -> bool:
        return self.selected_runtime is not None


class ScoutModelRuntimeRouter:
    """Deterministically pick a runtime profile without invoking a model."""

    def __init__(
        self,
        profiles: Sequence[ModelRuntimeProfile],
        *,
        current_host_kind: ModelRuntimeHostKind | None = None,
    ) -> None:
        if not profiles:
            raise ValueError("at least one model runtime profile is required")
        ids = [profile.runtime_id for profile in profiles]
        if len(set(ids)) != len(ids):
            raise ValueError("model runtime profile ids must be unique")
        self._profiles = tuple(profiles)
        self._current_host_kind = (
            current_host_kind or detect_model_runtime_host_kind()
        )

    @property
    def profiles(self) -> tuple[ModelRuntimeProfile, ...]:
        return self._profiles

    def select(self, request: ModelRuntimeRequest) -> ModelRuntimeSelection:
        considered: list[str] = []
        rejected: dict[str, str] = {}
        eligible: list[ModelRuntimeProfile] = []
        for profile in self._profiles:
            considered.append(profile.runtime_id)
            if (
                profile.required_host_kind is not ModelRuntimeHostKind.GENERIC
                and profile.required_host_kind is not self._current_host_kind
            ):
                rejected[profile.runtime_id] = (
                    f"runtime requires host kind {profile.required_host_kind.value}"
                )
                continue
            reason = _rejection_reason(profile, request)
            if reason:
                rejected[profile.runtime_id] = reason
                continue
            eligible.append(profile)

        if not eligible:
            return ModelRuntimeSelection(
                request_id=request.request_id,
                selected_runtime=None,
                reason="no runtime profile satisfied the typed request constraints",
                considered_runtime_ids=tuple(considered),
                rejected_reasons=rejected,
            )

        ranked = sorted(eligible, key=lambda profile: _rank_key(profile, request))
        selected = ranked[0]
        return ModelRuntimeSelection(
            request_id=request.request_id,
            selected_runtime=selected,
            reason=_selection_reason(selected, request),
            considered_runtime_ids=tuple(considered),
            rejected_reasons=rejected,
        )


def default_runtime_profiles() -> tuple[ModelRuntimeProfile, ...]:
    """Return Scout's initial logical runtime catalog.

    These profiles describe intended slots only. They do not prove that a local
    MAX server, Hailo model, or cloud credential is configured.
    """

    return (
        ModelRuntimeProfile(
            runtime_id="local.fast.function",
            tier=ModelRuntimeTier.LOCAL_FAST,
            provider="scout",
            model_id="local FunctionModel",
            locality=Locality.EDGE,
            accelerator=AcceleratorKind.CPU,
            capabilities=frozenset(
                {
                    ModelRuntimeCapability.CHAT,
                    ModelRuntimeCapability.STRUCTURED_OUTPUT,
                    ModelRuntimeCapability.OFFLINE,
                }
            ),
            context_limit_tokens=4096,
            max_concurrency=1,
            offline_capable=True,
            privacy_preserving=True,
            experimental=False,
        ),
        ModelRuntimeProfile(
            runtime_id="edge.hailo.local",
            tier=ModelRuntimeTier.HAILO_LOCAL,
            provider="hailo_ollama",
            model_id="hailo:qwen3:1.7b",
            locality=Locality.EDGE,
            required_host_kind=ModelRuntimeHostKind.RASPBERRY_PI,
            accelerator=AcceleratorKind.HAILO_10H,
            endpoint="http://127.0.0.1:18000",
            capabilities=frozenset(
                {
                    ModelRuntimeCapability.CHAT,
                    ModelRuntimeCapability.SMALL_TYPED_OUTPUT,
                    ModelRuntimeCapability.OFFLINE,
                }
            ),
            context_limit_tokens=8192,
            max_concurrency=1,
            offline_capable=True,
            privacy_preserving=True,
        ),
        ModelRuntimeProfile(
            runtime_id="edge.pi.ollama.cpu.background",
            tier=ModelRuntimeTier.LOCAL_REASONING,
            provider="ollama",
            model_id="configured-by-ollama",
            locality=Locality.EDGE,
            required_host_kind=ModelRuntimeHostKind.RASPBERRY_PI,
            accelerator=AcceleratorKind.CPU,
            endpoint="http://127.0.0.1:11434/v1",
            capabilities=frozenset(
                {
                    ModelRuntimeCapability.CHAT,
                    ModelRuntimeCapability.STRUCTURED_OUTPUT,
                    ModelRuntimeCapability.SLOW_BACKGROUND_REASONING,
                    ModelRuntimeCapability.OFFLINE,
                }
            ),
            context_limit_tokens=4096,
            max_concurrency=1,
            offline_capable=True,
            privacy_preserving=True,
        ),
        ModelRuntimeProfile(
            runtime_id="server.max.openai_compatible",
            tier=ModelRuntimeTier.MAX_LOCAL_OR_SERVER,
            provider="max",
            model_id="configured-by-max-serve",
            locality=Locality.MAC_SERVER,
            accelerator=AcceleratorKind.GPU,
            endpoint="http://127.0.0.1:8000/v1",
            capabilities=frozenset(
                {
                    ModelRuntimeCapability.CHAT,
                    ModelRuntimeCapability.STRUCTURED_OUTPUT,
                    ModelRuntimeCapability.STREAMING,
                }
            ),
            context_limit_tokens=32768,
            max_concurrency=1,
            offline_capable=False,
            privacy_preserving=True,
        ),
        ModelRuntimeProfile(
            runtime_id="cloud.reasoning",
            tier=ModelRuntimeTier.CLOUD_REASONING,
            provider="openai_compatible",
            model_id="configured-cloud-reasoning",
            locality=Locality.CLOUD,
            accelerator=AcceleratorKind.NONE,
            capabilities=frozenset(
                {
                    ModelRuntimeCapability.CHAT,
                    ModelRuntimeCapability.STRUCTURED_OUTPUT,
                    ModelRuntimeCapability.TOOL_CALLING,
                    ModelRuntimeCapability.STREAMING,
                }
            ),
            context_limit_tokens=131072,
            max_concurrency=2,
            offline_capable=False,
            privacy_preserving=False,
        ),
    )


def _rejection_reason(
    profile: ModelRuntimeProfile,
    request: ModelRuntimeRequest,
) -> str | None:
    if request.allowed_tiers is not None and profile.tier not in request.allowed_tiers:
        return "runtime tier is outside the request allowlist"
    if request.requires_offline and not profile.offline_capable:
        return "request requires offline-capable runtime"
    if profile.locality == Locality.CLOUD and not request.allow_cloud:
        return "cloud runtime not allowed by request"
    if request.privacy_sensitive and not profile.privacy_preserving:
        return "runtime is not privacy-preserving"
    if not profile.supports(request.required_capabilities):
        missing = sorted(
            capability.value
            for capability in request.required_capabilities
            if capability not in profile.capabilities
        )
        return f"runtime missing capabilities: {', '.join(missing)}"
    if profile.context_limit_tokens < request.min_context_tokens:
        return "runtime context limit is below request minimum"
    if (
        request.max_latency_ms is not None
        and profile.estimated_latency_ms is not None
        and profile.estimated_latency_ms > request.max_latency_ms
    ):
        return "runtime estimated latency exceeds request budget"
    return None


def _rank_key(
    profile: ModelRuntimeProfile,
    request: ModelRuntimeRequest,
) -> tuple[int, int, int, int, str]:
    locality_rank: dict[Locality, int]
    if request.prefer_local:
        locality_rank = {Locality.EDGE: 0, Locality.MAC_SERVER: 1, Locality.CLOUD: 2}
    else:
        locality_rank = {Locality.CLOUD: 0, Locality.MAC_SERVER: 1, Locality.EDGE: 2}
    experimental_rank = 1 if profile.experimental else 0
    latency = profile.estimated_latency_ms if profile.estimated_latency_ms is not None else 999999
    return (
        locality_rank[profile.locality],
        experimental_rank,
        latency,
        -profile.context_limit_tokens,
        profile.runtime_id,
    )


def _selection_reason(
    profile: ModelRuntimeProfile,
    request: ModelRuntimeRequest,
) -> str:
    scope = "local-first" if request.prefer_local else "capability-first"
    return (
        f"selected {profile.runtime_id} by {scope} typed runtime routing; "
        f"tier={profile.tier.value}, locality={profile.locality.value}"
    )


__all__ = [
    "AcceleratorKind",
    "Locality",
    "ModelCapabilityAttestation",
    "ModelRuntimeCapability",
    "ModelRuntimeProfile",
    "ModelRuntimeRequest",
    "ModelRuntimeSelection",
    "ModelRuntimeTier",
    "ScoutModelRuntimeRouter",
    "default_runtime_profiles",
]
