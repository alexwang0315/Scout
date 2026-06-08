"""Reviewable learning artifact schema contracts."""

from __future__ import annotations

from enum import Enum
from typing import Any

from scout.schemas.base import NonEmptyStr, SchemaModel


class LearningArtifactType(str, Enum):
    MEMORY = "memory"
    WORKFLOW_TEMPLATE = "workflow_template"
    SKILL = "skill"
    CAPABILITY = "capability"
    EVAL_CASE = "eval_case"


class LearningArtifact(SchemaModel):
    type: LearningArtifactType
    title: NonEmptyStr
    reason: NonEmptyStr
    content: dict[str, Any]
    requires_review: bool = True


class LearningBundle(SchemaModel):
    artifacts: list[LearningArtifact]
    summary: NonEmptyStr


__all__ = [
    "LearningArtifact",
    "LearningArtifactType",
    "LearningBundle",
]
