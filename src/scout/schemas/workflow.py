"""Workflow schema contracts for Scout AI OS."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field

from scout.schemas.base import NonEmptyStr, SchemaModel
from scout.schemas.permissions import PermissionSpec


class WorkflowLifecycle(str, Enum):
    ONE_SHOT = "one_shot"
    SESSION_SCOPED = "session_scoped"
    TRIP_SCOPED = "trip_scoped"
    PERMANENT = "permanent"


class RuntimeTarget(str, Enum):
    DEVICE = "device"
    PI = "pi"
    CLOUD = "cloud"
    BROWSER = "browser"
    SANDBOX = "sandbox"
    HYBRID = "hybrid"


class TriggerType(str, Enum):
    MANUAL = "manual"
    TIME = "time"
    LOCATION = "location"
    SENSOR = "sensor"
    EMAIL = "email"
    CALENDAR = "calendar"
    WEB_CHANGE = "web_change"
    API_EVENT = "api_event"
    FILE_CHANGE = "file_change"
    COMPOUND = "compound"


class ActionType(str, Enum):
    NOTIFY = "notify"
    ASK_USER = "ask_user"
    CREATE_TASK = "create_task"
    UPDATE_CHECKLIST = "update_checklist"
    CALL_API = "call_api"
    RUN_CAPABILITY = "run_capability"
    RUN_SANDBOX_SCRIPT = "run_sandbox_script"
    SAVE_TEMPLATE = "save_template"


class TriggerSpec(SchemaModel):
    type: TriggerType
    description: NonEmptyStr
    config: dict[str, Any] = Field(default_factory=dict)


class ConditionSpec(SchemaModel):
    description: NonEmptyStr
    expression: NonEmptyStr
    required_data_sources: list[NonEmptyStr] = Field(default_factory=list)


class ActionSpec(SchemaModel):
    type: ActionType
    description: NonEmptyStr
    config: dict[str, Any] = Field(default_factory=dict)


class WorkflowSpec(SchemaModel):
    id: str | None = None
    name: NonEmptyStr
    source_utterance: NonEmptyStr
    user_goal: NonEmptyStr
    trigger: TriggerSpec
    conditions: list[ConditionSpec] = Field(default_factory=list)
    actions: list[ActionSpec] = Field(min_length=1)
    lifecycle: WorkflowLifecycle
    runtime: RuntimeTarget
    permissions: PermissionSpec
    fallback_policy: dict[str, Any] = Field(default_factory=dict)
    verification_plan: list[NonEmptyStr] = Field(default_factory=list)
    learning_candidates: list[NonEmptyStr] = Field(default_factory=list)


__all__ = [
    "ActionSpec",
    "ActionType",
    "ConditionSpec",
    "RuntimeTarget",
    "TriggerSpec",
    "TriggerType",
    "WorkflowLifecycle",
    "WorkflowSpec",
]
