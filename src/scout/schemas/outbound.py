"""Typed standing-grant contracts for deterministic Scout outbound actions."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from scout.schemas.base import NonEmptyStr, SchemaModel


class OutboundGrantScope(str, Enum):
    SESSION = "session"
    TRIP = "trip"


class OutboundPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class OutboundDataClass(str, Enum):
    STATUS_SUMMARY = "status_summary"
    DEVICE_TELEMETRY = "device_telemetry"
    OPERATOR_TEXT = "operator_text"
    APPROXIMATE_LOCATION = "approximate_location"
    PRECISE_LOCATION = "precise_location"
    HEALTH_SUMMARY = "health_summary"
    RAW_HEALTH = "raw_health"


class OutboundDecisionStatus(str, Enum):
    ALLOWED = "allowed"
    NEEDS_APPROVAL = "needs_approval"
    BLOCKED = "blocked"


class OutboundStandingGrant(SchemaModel):
    """One reviewed authorization envelope for repeated non-safety sends."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    grant_id: NonEmptyStr
    scope: OutboundGrantScope
    scope_ref: NonEmptyStr
    approved_by: NonEmptyStr
    issued_at: datetime
    expires_at: datetime
    allowed_provider_refs: tuple[NonEmptyStr, ...] = Field(min_length=1)
    allowed_recipient_refs: tuple[NonEmptyStr, ...] = Field(min_length=1)
    allowed_message_classes: tuple[NonEmptyStr, ...] = Field(min_length=1)
    allowed_topic_refs: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)
    allowed_data_classes: tuple[OutboundDataClass, ...] = Field(min_length=1)
    allowed_priorities: tuple[OutboundPriority, ...] = Field(min_length=1)
    max_send_count: int = Field(gt=0)
    active: bool = True
    safety_mutation_allowed: Literal[False] = False
    sos_allowed: Literal[False] = False
    arbitrary_target_allowed: Literal[False] = False
    secret_material_allowed: Literal[False] = False

    @field_validator(
        "allowed_provider_refs",
        "allowed_recipient_refs",
        "allowed_message_classes",
        "allowed_topic_refs",
    )
    @classmethod
    def reject_duplicate_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("standing grant reference lists must not contain duplicates")
        return values

    @field_validator("allowed_message_classes")
    @classmethod
    def reject_safety_message_classes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(is_safety_message_class(value) for value in values):
            raise ValueError("standing grant cannot authorize safety message classes")
        return values

    @model_validator(mode="after")
    def validate_time_window(self) -> "OutboundStandingGrant":
        if self.issued_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("standing grant timestamps must be timezone-aware")
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be after issued_at")
        return self


class OutboundActionIntent(SchemaModel):
    """Summary-only action intent; it never embeds endpoint secrets or payloads."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    intent_id: NonEmptyStr
    scope_ref: NonEmptyStr
    provider_ref: NonEmptyStr
    recipient_ref: NonEmptyStr
    message_class: NonEmptyStr
    priority: OutboundPriority
    topic_ref: str | None = None
    data_classes: tuple[OutboundDataClass, ...] = Field(min_length=1)
    payload_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    idempotency_key: NonEmptyStr
    safety_related: bool = False
    safety_mutation_requested: bool = False
    phase1_l0_l4_state_mutation_requested: bool = False
    contains_secret_material: bool = False

    @field_validator("data_classes")
    @classmethod
    def reject_duplicate_data_classes(
        cls,
        values: tuple[OutboundDataClass, ...],
    ) -> tuple[OutboundDataClass, ...]:
        if len(values) != len(set(values)):
            raise ValueError("outbound intent data classes must not contain duplicates")
        return values


class OutboundGrantDecision(SchemaModel):
    """Deterministic decision produced before any sender is invoked."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: OutboundDecisionStatus
    intent_id: NonEmptyStr
    grant_id: str | None = None
    auto_execute_allowed: bool
    requires_user_approval: bool
    blocker_reasons: list[NonEmptyStr] = Field(default_factory=list)
    send_performed: Literal[False] = False
    safety_mutation_performed: Literal[False] = False
    raw_payload_embedded: Literal[False] = False
    secret_material_embedded: Literal[False] = False


def is_safety_message_class(message_class: str) -> bool:
    normalized = message_class.strip().casefold().replace("-", "_")
    return normalized in {
        "sos",
        "incident_alert",
        "emergency_alert",
        "safety_mutation",
        "l4_direct_trigger",
    } or normalized.startswith(("safety_", "safety.", "sos_", "emergency_"))


__all__ = [
    "OutboundActionIntent",
    "OutboundDataClass",
    "OutboundDecisionStatus",
    "OutboundGrantDecision",
    "OutboundGrantScope",
    "OutboundPriority",
    "OutboundStandingGrant",
    "is_safety_message_class",
]
