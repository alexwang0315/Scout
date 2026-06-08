"""Runtime planning and sandbox result schema contracts."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field

from scout.schemas.base import NonEmptyStr, SchemaModel
from scout.schemas.capability import InstallScope
from scout.schemas.workflow import WorkflowSpec


class PlanMode(str, Enum):
    USE_EXISTING = "use_existing"
    COMPOSE_EXISTING = "compose_existing"
    BUILD_NEW_CAPABILITY = "build_new_capability"
    ASK_PERMISSION = "ask_permission"
    ASK_CLARIFICATION = "ask_clarification"
    REFUSE_AUTOMATION = "refuse_automation"


class ExecutionPlan(SchemaModel):
    mode: PlanMode
    reason: NonEmptyStr
    workflow: WorkflowSpec
    required_capabilities: list[NonEmptyStr] = Field(default_factory=list)
    missing_capabilities: list[NonEmptyStr] = Field(default_factory=list)
    approval_message: str | None = None
    build_request: dict[str, Any] | None = None
    safety_notes: list[NonEmptyStr] = Field(default_factory=list)
    next_steps: list[NonEmptyStr] = Field(default_factory=list)


class SandboxResult(SchemaModel):
    passed: bool
    stdout: str = ""
    stderr: str = ""
    test_summary: str = ""
    security_findings: list[NonEmptyStr] = Field(default_factory=list)
    resource_usage: dict[str, Any] = Field(default_factory=dict)


class InstallDecision(SchemaModel):
    approved_for_install: bool
    reason: NonEmptyStr
    install_scope: InstallScope | None = None
    required_user_approval: bool = False


__all__ = [
    "ExecutionPlan",
    "InstallDecision",
    "PlanMode",
    "SandboxResult",
]
