"""Capability schema contracts for Scout AI OS."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field

from scout.schemas.base import NonEmptyStr, SchemaModel


class CapabilityRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CapabilityRuntime(str, Enum):
    PYTHON = "python"
    DEVICE_NATIVE = "device_native"
    PI_SERVICE = "pi_service"
    CLOUD_WORKER = "cloud_worker"
    BROWSER = "browser"
    MCP = "mcp"


class InstallScope(str, Enum):
    SESSION = "session"
    USER = "user"
    GLOBAL = "global"


class CapabilitySpec(SchemaModel):
    name: NonEmptyStr
    description: NonEmptyStr
    version: NonEmptyStr = "0.1.0"
    runtime: CapabilityRuntime
    risk_level: CapabilityRisk
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    permissions: list[NonEmptyStr] = Field(default_factory=list)
    dependencies: list[NonEmptyStr] = Field(default_factory=list)
    examples: list[dict[str, Any]] = Field(default_factory=list)
    test_cases: list[dict[str, Any]] = Field(default_factory=list)
    install_scope: InstallScope = InstallScope.USER


class CapabilityBuildRequest(SchemaModel):
    capability_name: NonEmptyStr
    purpose: NonEmptyStr
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    constraints: list[NonEmptyStr] = Field(default_factory=list)
    test_cases: list[dict[str, Any]] = Field(default_factory=list)
    risk_level: CapabilityRisk


class GeneratedCapabilityPackage(SchemaModel):
    spec: CapabilitySpec
    files: dict[NonEmptyStr, str]
    tests: dict[NonEmptyStr, str]
    install_notes: NonEmptyStr
    security_notes: list[NonEmptyStr] = Field(default_factory=list)


__all__ = [
    "CapabilityBuildRequest",
    "CapabilityRisk",
    "CapabilityRuntime",
    "CapabilitySpec",
    "GeneratedCapabilityPackage",
    "InstallScope",
]
