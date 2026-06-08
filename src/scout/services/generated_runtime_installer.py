"""Lifecycle gate for generated capability runtime installation."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import Field

from scout.schemas.base import NonEmptyStr, SchemaModel
from scout.schemas.capability import CapabilityRisk, GeneratedCapabilityPackage
from scout.services.sandbox_runner import SandboxRunner


GENERATED_RUNTIME_INSTALL_APPROVAL_PHRASE = "INSTALL SCOUT GENERATED RUNTIME"

InstallStatus = Literal["blocked", "ready", "installed", "revoked", "rolled_back"]


class RuntimeIsolationProfile(SchemaModel):
    """Required isolation properties for generated runtime code."""

    profile_id: NonEmptyStr
    kind: Literal["container", "os_sandbox", "wasm"]
    network_allowed: bool = False
    read_only_root: bool = True
    secrets_mounted: bool = False
    host_paths_writable: bool = False
    revoke_supported: bool = True
    rollback_supported: bool = True


class GeneratedRuntimeInstallApproval(SchemaModel):
    """Operator approval required before generated runtime install."""

    approved_by: NonEmptyStr
    phrase: NonEmptyStr
    risk_accepted: CapabilityRisk = CapabilityRisk.LOW
    approved_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    reason: str = ""


class GeneratedRuntimeInstallPlan(SchemaModel):
    artifact_kind: Literal["scout_generated_runtime_install_plan.v0"] = (
        "scout_generated_runtime_install_plan.v0"
    )
    capability_name: NonEmptyStr
    artifact_hash: NonEmptyStr
    status: Literal["blocked", "ready"]
    block_reasons: list[str] = Field(default_factory=list)
    isolation_profile: RuntimeIsolationProfile
    sandbox_passed: bool
    runtime_code_executed: bool = False
    active_runtime_dispatch_enabled: bool = False


class GeneratedRuntimeInstallRecord(SchemaModel):
    artifact_kind: Literal["scout_generated_runtime_install_record.v0"] = (
        "scout_generated_runtime_install_record.v0"
    )
    install_id: NonEmptyStr = Field(default_factory=lambda: f"install-{uuid4()}")
    capability_name: NonEmptyStr
    version: NonEmptyStr
    artifact_hash: NonEmptyStr
    status: InstallStatus
    isolation_profile: RuntimeIsolationProfile
    installed_at: str | None = None
    revoked_at: str | None = None
    rolled_back_at: str | None = None
    rollback_of: str | None = None
    runtime_code_executed: bool = False
    active_runtime_dispatch_enabled: bool = False


class GeneratedRuntimeInstaller:
    """Install lifecycle manager for generated code under a strict gate."""

    def __init__(self, sandbox: SandboxRunner | None = None) -> None:
        self.sandbox = sandbox or SandboxRunner()
        self.records: dict[str, GeneratedRuntimeInstallRecord] = {}

    def verify_install_ready(
        self,
        package: GeneratedCapabilityPackage,
        *,
        isolation_profile: RuntimeIsolationProfile,
        approval: GeneratedRuntimeInstallApproval,
    ) -> GeneratedRuntimeInstallPlan:
        sandbox_result = self.sandbox.verify(package)
        block_reasons = _block_reasons(
            package=package,
            isolation_profile=isolation_profile,
            approval=approval,
            sandbox_passed=sandbox_result.passed,
        )
        return GeneratedRuntimeInstallPlan(
            capability_name=package.spec.name,
            artifact_hash=generated_package_hash(package),
            status="blocked" if block_reasons else "ready",
            block_reasons=block_reasons,
            isolation_profile=isolation_profile,
            sandbox_passed=sandbox_result.passed,
        )

    def install(
        self,
        package: GeneratedCapabilityPackage,
        *,
        isolation_profile: RuntimeIsolationProfile,
        approval: GeneratedRuntimeInstallApproval,
    ) -> GeneratedRuntimeInstallRecord:
        plan = self.verify_install_ready(
            package,
            isolation_profile=isolation_profile,
            approval=approval,
        )
        if plan.status != "ready":
            raise ValueError(f"generated runtime install blocked: {plan.block_reasons}")
        record = GeneratedRuntimeInstallRecord(
            capability_name=package.spec.name,
            version=package.spec.version,
            artifact_hash=plan.artifact_hash,
            status="installed",
            isolation_profile=isolation_profile,
            installed_at=datetime.now(UTC).isoformat(),
        )
        self.records[record.install_id] = record
        return record

    def revoke(self, install_id: str) -> GeneratedRuntimeInstallRecord:
        record = self._get_record(install_id)
        revoked = record.model_copy(
            update={
                "status": "revoked",
                "revoked_at": datetime.now(UTC).isoformat(),
                "active_runtime_dispatch_enabled": False,
            }
        )
        self.records[install_id] = revoked
        return revoked

    def rollback(self, install_id: str) -> GeneratedRuntimeInstallRecord:
        record = self._get_record(install_id)
        rolled_back = record.model_copy(
            update={
                "install_id": f"rollback-{uuid4()}",
                "status": "rolled_back",
                "rolled_back_at": datetime.now(UTC).isoformat(),
                "rollback_of": install_id,
                "active_runtime_dispatch_enabled": False,
            }
        )
        self.records[rolled_back.install_id] = rolled_back
        return rolled_back

    def _get_record(self, install_id: str) -> GeneratedRuntimeInstallRecord:
        try:
            return self.records[install_id]
        except KeyError as exc:
            raise KeyError(f"generated runtime install not found: {install_id}") from exc


def generated_package_hash(package: GeneratedCapabilityPackage) -> str:
    payload = package.model_dump(mode="json")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _block_reasons(
    *,
    package: GeneratedCapabilityPackage,
    isolation_profile: RuntimeIsolationProfile,
    approval: GeneratedRuntimeInstallApproval,
    sandbox_passed: bool,
) -> list[str]:
    reasons: list[str] = []
    if not sandbox_passed:
        reasons.append("sandbox_failed")
    if package.spec.risk_level is not CapabilityRisk.LOW:
        reasons.append("capability_risk_not_low")
    if approval.phrase != GENERATED_RUNTIME_INSTALL_APPROVAL_PHRASE:
        reasons.append("approval_phrase_mismatch")
    if approval.risk_accepted is not CapabilityRisk.LOW:
        reasons.append("approval_risk_not_low")
    if isolation_profile.network_allowed:
        reasons.append("network_must_be_disabled")
    if not isolation_profile.read_only_root:
        reasons.append("root_must_be_read_only")
    if isolation_profile.secrets_mounted:
        reasons.append("secrets_must_not_be_mounted")
    if isolation_profile.host_paths_writable:
        reasons.append("host_paths_must_not_be_writable")
    if not isolation_profile.revoke_supported:
        reasons.append("revoke_must_be_supported")
    if not isolation_profile.rollback_supported:
        reasons.append("rollback_must_be_supported")
    return reasons


__all__ = [
    "GENERATED_RUNTIME_INSTALL_APPROVAL_PHRASE",
    "GeneratedRuntimeInstallApproval",
    "GeneratedRuntimeInstallPlan",
    "GeneratedRuntimeInstallRecord",
    "GeneratedRuntimeInstaller",
    "InstallStatus",
    "RuntimeIsolationProfile",
    "generated_package_hash",
]
