"""Shared Pydantic helpers for Scout AI OS schema contracts."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


NonEmptyStr = Annotated[str, Field(min_length=1)]


class SchemaModel(BaseModel):
    """Base class for typed Scout AI OS contracts."""

    model_config = ConfigDict(extra="forbid")


__all__ = ["NonEmptyStr", "SchemaModel"]
