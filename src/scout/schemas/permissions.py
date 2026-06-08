"""Permission schema contracts for Scout AI OS."""

from __future__ import annotations

from pydantic import Field

from scout.schemas.base import NonEmptyStr, SchemaModel


class PermissionSpec(SchemaModel):
    """Permissions requested by a workflow or capability.

    This model only describes requested permissions. Permission evaluation is a
    later phase and belongs in ``scout.services.permission_gate``.
    """

    required: list[NonEmptyStr] = Field(default_factory=list)
    approval_required: bool = False
    reason: str = ""


class PermissionDecision(SchemaModel):
    """Typed result shape for a future PermissionGate decision."""

    allowed: bool
    requires_user_approval: bool
    reason: NonEmptyStr
    user_message: NonEmptyStr


__all__ = ["PermissionDecision", "PermissionSpec"]
