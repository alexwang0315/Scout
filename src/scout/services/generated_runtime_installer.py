"""Lifecycle gate for generated capability runtime installation."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field

from scout.schemas.base import NonEmptyStr, SchemaModel
from scout.schemas.capability import CapabilityRisk, GeneratedCapabilityPackage
from scout.services.sandbox_runner import (
    SandboxRunner,
    _safe_relative_path,
    _write_network_blocker,
    _write_package_files,
)


GENERATED_RUNTIME_INSTALL_APPROVAL_PHRASE = "INSTALL SCOUT GENERATED RUNTIME"

InstallStatus = Literal["blocked", "ready", "installed", "revoked", "rolled_back"]
DispatchStatus = Literal["blocked", "completed", "failed"]

GENERATED_RUNTIME_DISPATCH_BOUNDARY: dict[str, bool] = {
    "proof_only": True,
    "active_runtime_dispatch_enabled": False,
    "phase1_l0_l4_state_mutation_allowed": False,
    "phase1_l0_l4_state_mutated": False,
    "safety_api_mutation_allowed": False,
    "safety_api_called": False,
    "outbound_send_allowed": False,
    "outbound_sent": False,
    "hardware_control_allowed": False,
    "hardware_control_performed": False,
}


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


class GeneratedRuntimeDispatchRequest(SchemaModel):
    artifact_kind: Literal["scout_generated_runtime_dispatch_request.v0"] = (
        "scout_generated_runtime_dispatch_request.v0"
    )
    install_id: NonEmptyStr
    capability_name: NonEmptyStr
    payload: dict[str, object] = Field(default_factory=dict)
    proof_only: bool = True
    operator_approved: bool = True
    requested_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class GeneratedRuntimeDispatchResult(SchemaModel):
    artifact_kind: Literal["scout_generated_runtime_dispatch_result.v0"] = (
        "scout_generated_runtime_dispatch_result.v0"
    )
    dispatch_id: NonEmptyStr = Field(default_factory=lambda: f"dispatch-{uuid4()}")
    install_id: NonEmptyStr
    capability_name: NonEmptyStr
    artifact_hash: NonEmptyStr
    status: DispatchStatus
    output: object | None = None
    block_reasons: list[str] = Field(default_factory=list)
    error: str | None = None
    elapsed_seconds: float = 0.0
    runtime_code_executed: bool = False
    proof_runtime_code_executed: bool = False
    active_runtime_dispatch_enabled: bool = False
    safety_api_called: bool = False
    outbound_sent: bool = False
    boundary: dict[str, bool] = Field(
        default_factory=lambda: dict(GENERATED_RUNTIME_DISPATCH_BOUNDARY)
    )


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


class GeneratedRuntimeDispatcher:
    """Proof-only generated runtime dispatcher for isolated local validation."""

    def __init__(
        self,
        sandbox: SandboxRunner | None = None,
        *,
        timeout_seconds: float = 10.0,
        python_executable: str | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.sandbox = sandbox or SandboxRunner(timeout_seconds=timeout_seconds)
        self.timeout_seconds = timeout_seconds
        self.python_executable = python_executable or sys.executable

    def dispatch_proof(
        self,
        *,
        package: GeneratedCapabilityPackage,
        install_record: GeneratedRuntimeInstallRecord,
        request: GeneratedRuntimeDispatchRequest,
    ) -> GeneratedRuntimeDispatchResult:
        started_at = time.monotonic()
        block_reasons = self._block_reasons(
            package=package,
            install_record=install_record,
            request=request,
        )
        if block_reasons:
            return _dispatch_result(
                install_record=install_record,
                request=request,
                status="blocked",
                started_at=started_at,
                block_reasons=block_reasons,
            )

        sandbox_result = self.sandbox.verify(package)
        if not sandbox_result.passed:
            return _dispatch_result(
                install_record=install_record,
                request=request,
                status="blocked",
                started_at=started_at,
                block_reasons=["sandbox_failed"],
                error=sandbox_result.test_summary,
            )

        try:
            output = self._execute_package(package, request.payload)
        except subprocess.TimeoutExpired as exc:
            return _dispatch_result(
                install_record=install_record,
                request=request,
                status="failed",
                started_at=started_at,
                error=f"dispatch timed out after {self.timeout_seconds:g}s: {exc}",
            )
        except Exception as exc:
            return _dispatch_result(
                install_record=install_record,
                request=request,
                status="failed",
                started_at=started_at,
                error=str(exc),
            )

        return _dispatch_result(
            install_record=install_record,
            request=request,
            status="completed",
            started_at=started_at,
            output=output,
            runtime_code_executed=True,
        )

    def _block_reasons(
        self,
        *,
        package: GeneratedCapabilityPackage,
        install_record: GeneratedRuntimeInstallRecord,
        request: GeneratedRuntimeDispatchRequest,
    ) -> list[str]:
        reasons: list[str] = []
        if install_record.status != "installed":
            reasons.append("install_record_not_installed")
        if request.install_id != install_record.install_id:
            reasons.append("request_install_id_mismatch")
        if request.capability_name != install_record.capability_name:
            reasons.append("request_capability_name_mismatch")
        if package.spec.name != install_record.capability_name:
            reasons.append("package_capability_name_mismatch")
        if generated_package_hash(package) != install_record.artifact_hash:
            reasons.append("artifact_hash_mismatch")
        if not request.proof_only:
            reasons.append("proof_only_required")
        if not request.operator_approved:
            reasons.append("operator_approval_required")
        if install_record.active_runtime_dispatch_enabled:
            reasons.append("active_runtime_dispatch_must_stay_disabled")
        reasons.extend(_isolation_block_reasons(install_record.isolation_profile))
        return reasons

    def _execute_package(
        self,
        package: GeneratedCapabilityPackage,
        payload: dict[str, object],
    ) -> object:
        entrypoint = _entrypoint_file(package)
        with tempfile.TemporaryDirectory(prefix="scout-generated-dispatch-") as temp_dir:
            sandbox_path = Path(temp_dir)
            _write_package_files(sandbox_path, package.files)
            _write_network_blocker(sandbox_path)
            runner_path = sandbox_path / "scout_dispatch_runner.py"
            runner_path.write_text(_DISPATCH_RUNNER, encoding="utf-8")
            completed = subprocess.run(
                [
                    self.python_executable,
                    str(runner_path),
                    str(sandbox_path / entrypoint),
                ],
                cwd=sandbox_path,
                env=_dispatch_env(sandbox_path),
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                check=False,
                timeout=self.timeout_seconds,
            )
        if completed.returncode != 0:
            stderr = completed.stderr.strip()
            stdout = completed.stdout.strip()
            raise RuntimeError(stderr or stdout or "generated runtime dispatch failed")
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        if not lines:
            return None
        return json.loads(lines[-1])


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


def _isolation_block_reasons(isolation_profile: RuntimeIsolationProfile) -> list[str]:
    reasons: list[str] = []
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


def _dispatch_result(
    *,
    install_record: GeneratedRuntimeInstallRecord,
    request: GeneratedRuntimeDispatchRequest,
    status: DispatchStatus,
    started_at: float,
    output: object | None = None,
    block_reasons: list[str] | None = None,
    error: str | None = None,
    runtime_code_executed: bool = False,
) -> GeneratedRuntimeDispatchResult:
    return GeneratedRuntimeDispatchResult(
        install_id=request.install_id,
        capability_name=request.capability_name,
        artifact_hash=install_record.artifact_hash,
        status=status,
        output=output,
        block_reasons=list(block_reasons or []),
        error=error,
        elapsed_seconds=time.monotonic() - started_at,
        runtime_code_executed=runtime_code_executed,
        proof_runtime_code_executed=runtime_code_executed and request.proof_only,
        active_runtime_dispatch_enabled=False,
        safety_api_called=False,
        outbound_sent=False,
    )


def _entrypoint_file(package: GeneratedCapabilityPackage) -> Path:
    preferred = f"{package.spec.name}.py"
    candidates = [preferred, *sorted(package.files)]
    for relative_path in candidates:
        if relative_path not in package.files or not relative_path.endswith(".py"):
            continue
        safe_path = _safe_relative_path(relative_path)
        if safe_path is not None:
            return safe_path
    raise ValueError("generated runtime package has no safe Python entrypoint")


def _dispatch_env(sandbox_path: Path) -> dict[str, str]:
    return {
        "HOME": str(sandbox_path / "home"),
        "NO_PROXY": "*",
        "PATH": os.environ.get("PATH", ""),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(sandbox_path),
    }


_DISPATCH_RUNNER = "\n".join(
    [
        "from __future__ import annotations",
        "import importlib.util",
        "import json",
        "import sys",
        "from pathlib import Path",
        "",
        "sys.path.insert(0, str(Path.cwd()))",
        "payload = json.loads(sys.stdin.read() or '{}')",
        "module_path = Path(sys.argv[1])",
        "spec = importlib.util.spec_from_file_location(module_path.stem, module_path)",
        "if spec is None or spec.loader is None:",
        "    raise RuntimeError('generated runtime entrypoint could not be loaded')",
        "module = importlib.util.module_from_spec(spec)",
        "spec.loader.exec_module(module)",
        "run = getattr(module, 'run', None)",
        "if run is None:",
        "    raise RuntimeError('generated runtime entrypoint does not define run(payload)')",
        "print(json.dumps(run(payload), sort_keys=True))",
        "",
    ]
)


__all__ = [
    "GENERATED_RUNTIME_INSTALL_APPROVAL_PHRASE",
    "GENERATED_RUNTIME_DISPATCH_BOUNDARY",
    "DispatchStatus",
    "GeneratedRuntimeDispatcher",
    "GeneratedRuntimeDispatchRequest",
    "GeneratedRuntimeDispatchResult",
    "GeneratedRuntimeInstallApproval",
    "GeneratedRuntimeInstallPlan",
    "GeneratedRuntimeInstallRecord",
    "GeneratedRuntimeInstaller",
    "InstallStatus",
    "RuntimeIsolationProfile",
    "generated_package_hash",
]
