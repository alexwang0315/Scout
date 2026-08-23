"""Feature-flagged shadow routing for Scout's read-only assistant path.

This module observes what the experimental runtime router would select. It does
not invoke a model, replace the configured provider, or change any Scout state.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from scout.nextgen.model_runtime import (
    Locality,
    ModelRuntimeCapability,
    ModelRuntimeProfile,
    ModelRuntimeRequest,
    ModelRuntimeTier,
    ScoutModelRuntimeRouter,
    default_runtime_profiles,
)
from scout.schemas.base import NonEmptyStr, SchemaModel

RUNTIME_SHADOW_ENV = "SCOUT_AI_NEXTGEN_RUNTIME_SHADOW"
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


class RuntimeShadowStatus(StrEnum):
    SELECTED = "selected"
    NO_MATCH = "no_match"
    ERROR = "error"


class ModelRuntimeShadowTrace(SchemaModel):
    """Public, non-authoritative trace of one shadow routing decision."""

    schema_version: Literal["scout.model_runtime_shadow.v0"] = (
        "scout.model_runtime_shadow.v0"
    )
    status: RuntimeShadowStatus
    request_id: UUID
    task: NonEmptyStr
    selected_runtime_id: NonEmptyStr | None = None
    selected_tier: ModelRuntimeTier | None = None
    selected_locality: Locality | None = None
    reason: NonEmptyStr
    considered_runtime_ids: tuple[NonEmptyStr, ...] = ()
    rejected_reasons: dict[NonEmptyStr, NonEmptyStr] = Field(default_factory=dict)
    error_type: NonEmptyStr | None = None
    availability_verified: Literal[False] = False
    execution_changed: Literal[False] = False
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @model_validator(mode="after")
    def validate_selection_shape(self) -> "ModelRuntimeShadowTrace":
        selected_fields = (
            self.selected_runtime_id,
            self.selected_tier,
            self.selected_locality,
        )
        if self.status == RuntimeShadowStatus.SELECTED and any(
            value is None for value in selected_fields
        ):
            raise ValueError("selected shadow traces require runtime metadata")
        if self.status != RuntimeShadowStatus.SELECTED and any(
            value is not None for value in selected_fields
        ):
            raise ValueError("non-selected shadow traces cannot name a runtime")
        if self.status == RuntimeShadowStatus.ERROR and self.error_type is None:
            raise ValueError("error shadow traces require error_type")
        return self


def runtime_shadow_enabled(environ: Mapping[str, str] | None = None) -> bool:
    resolved = os.environ if environ is None else environ
    return str(resolved.get(RUNTIME_SHADOW_ENV, "")).strip().casefold() in _TRUE_VALUES


def maybe_build_assistant_runtime_shadow_trace(
    *,
    task: str,
    runtime_preference: str | None,
    estimated_context_tokens: int,
    environ: Mapping[str, str] | None = None,
    profiles: Sequence[ModelRuntimeProfile] | None = None,
    request_id: UUID | None = None,
) -> ModelRuntimeShadowTrace | None:
    """Return a shadow decision when enabled, without touching execution."""

    if not runtime_shadow_enabled(environ):
        return None

    resolved_request_id = request_id or uuid4()
    resolved_task = str(task).strip() or "assistant.unknown"
    try:
        request = _assistant_runtime_request(
            request_id=resolved_request_id,
            task=resolved_task,
            runtime_preference=runtime_preference,
            estimated_context_tokens=estimated_context_tokens,
        )
        selection = ScoutModelRuntimeRouter(
            tuple(profiles) if profiles is not None else default_runtime_profiles()
        ).select(request)
    except Exception as exc:
        return ModelRuntimeShadowTrace(
            status=RuntimeShadowStatus.ERROR,
            request_id=resolved_request_id,
            task=resolved_task,
            reason=f"shadow routing failed closed: {type(exc).__name__}",
            error_type=type(exc).__name__,
        )

    selected = selection.selected_runtime
    if selected is None:
        return ModelRuntimeShadowTrace(
            status=RuntimeShadowStatus.NO_MATCH,
            request_id=resolved_request_id,
            task=request.task,
            reason=selection.reason,
            considered_runtime_ids=selection.considered_runtime_ids,
            rejected_reasons=selection.rejected_reasons,
        )
    return ModelRuntimeShadowTrace(
        status=RuntimeShadowStatus.SELECTED,
        request_id=resolved_request_id,
        task=request.task,
        selected_runtime_id=selected.runtime_id,
        selected_tier=selected.tier,
        selected_locality=selected.locality,
        reason=selection.reason,
        considered_runtime_ids=selection.considered_runtime_ids,
        rejected_reasons=selection.rejected_reasons,
    )


def _assistant_runtime_request(
    *,
    request_id: UUID,
    task: str,
    runtime_preference: str | None,
    estimated_context_tokens: int,
) -> ModelRuntimeRequest:
    normalized_preference = (
        str(runtime_preference).strip().casefold() if runtime_preference else None
    )
    capabilities = {
        ModelRuntimeCapability.CHAT,
        ModelRuntimeCapability.STRUCTURED_OUTPUT,
    }
    if normalized_preference == "cloud":
        allowed_tiers = {
            ModelRuntimeTier.CLOUD_REASONING,
            ModelRuntimeTier.CLOUD_RESEARCH,
        }
        prefer_local = False
        allow_cloud = True
        requires_offline = False
    elif normalized_preference == "ai_hat_plus_2_fallback":
        allowed_tiers = {ModelRuntimeTier.HAILO_LOCAL}
        capabilities.add(ModelRuntimeCapability.OFFLINE)
        prefer_local = True
        allow_cloud = False
        requires_offline = True
    elif normalized_preference is None:
        allowed_tiers = {
            ModelRuntimeTier.HAILO_LOCAL,
            ModelRuntimeTier.MAX_LOCAL_OR_SERVER,
            ModelRuntimeTier.CLOUD_REASONING,
        }
        prefer_local = True
        allow_cloud = True
        requires_offline = False
    else:
        raise ValueError("unsupported assistant runtime preference")

    return ModelRuntimeRequest(
        request_id=request_id,
        task=task,
        required_capabilities=frozenset(capabilities),
        allowed_tiers=frozenset(allowed_tiers),
        prefer_local=prefer_local,
        allow_cloud=allow_cloud,
        requires_offline=requires_offline,
        min_context_tokens=max(1, int(estimated_context_tokens)),
        max_model_requests=10,
    )


__all__ = [
    "ModelRuntimeShadowTrace",
    "RUNTIME_SHADOW_ENV",
    "RuntimeShadowStatus",
    "maybe_build_assistant_runtime_shadow_trace",
    "runtime_shadow_enabled",
]
