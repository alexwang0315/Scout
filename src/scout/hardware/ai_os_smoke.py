"""Hardware-safe Scout AI OS smoke profile and runner."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from importlib import import_module
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal

from fastapi.testclient import TestClient

from scout.agents import resolve_model_policy
from scout.agents.model_gateway import ModelCallLedger, ModelSlaGateway
from scout.agents.model_policy import ModelPolicy
from scout.api.routes import create_app
from scout.cli.pydantic_smoke import run_smoke
from pydantic import Field

from scout.schemas.base import SchemaModel
from scout.schemas.capability import (
    CapabilityRisk,
    CapabilityRuntime,
    CapabilitySpec,
    GeneratedCapabilityPackage,
)
from scout.services import (
    DryRunNotificationProvider,
    GENERATED_RUNTIME_INSTALL_APPROVAL_PHRASE,
    GeneratedRuntimeInstallApproval,
    GeneratedRuntimeInstaller,
    MemoryExternalNotificationTransport,
    NotificationGateway,
    OPERATOR_NOTIFICATION_APPROVAL_PHRASE,
    OperatorConfirmedNotificationProvider,
    OperatorNotificationApproval,
    RuntimeIsolationProfile,
)
from scout.services.sandbox_runner import SandboxRunner


CheckStatus = Literal["passed", "blocked", "skipped", "failed"]

HARDWARE_SMOKE_BOUNDARY: dict[str, Any] = {
    "profile_scope": "scout_ai_os_hardware_smoke",
    "hardware_control_allowed": False,
    "hardware_control_performed": False,
    "provider_control_allowed": False,
    "outbound_send_allowed": False,
    "outbound_sent": False,
    "phase1_l0_l4_state_mutation_allowed": False,
    "phase1_l0_l4_state_mutated": False,
    "safety_api_mutation_allowed": False,
    "safety_api_called": False,
    "generated_runtime_code_install_allowed": False,
}

HARDWARE_SMOKE_PHASES: list[dict[str, Any]] = [
    {
        "phase_id": "H0",
        "name": "Hardware smoke profile",
        "default_state": "implemented",
        "acceptance": "A single JSON report defines allowed checks and forbidden runtime effects.",
    },
    {
        "phase_id": "H1",
        "name": "Scout AI OS local hardware API smoke",
        "default_state": "implemented",
        "acceptance": "FastAPI/TestClient, capabilities, scheduler, and local Pydantic AI smoke pass without network.",
    },
    {
        "phase_id": "H2",
        "name": "External model smoke",
        "default_state": "opt_in",
        "acceptance": "OpenRouter or another external model is used only when explicitly enabled.",
    },
    {
        "phase_id": "H3",
        "name": "Session-local UI operation smoke",
        "default_state": "implemented",
        "acceptance": "UI operation requests produce scout_ui_action_plan.v0 without browser or runtime mutation.",
    },
    {
        "phase_id": "H4",
        "name": "Mobile and wearable evidence ingress",
        "default_state": "probe_json_optional",
        "acceptance": "Real-device evidence remains advisory/debug/candidate-only.",
    },
    {
        "phase_id": "H5",
        "name": "Notification dry-run and operator-confirmed transport",
        "default_state": "implemented",
        "acceptance": "External notification intent is dry-run by default and live-send capable only with low-risk operator confirmation.",
    },
    {
        "phase_id": "H6",
        "name": "Sandbox hardening gate",
        "default_state": "implemented_as_gate",
        "acceptance": "Dangerous generated packages are rejected before execution.",
    },
    {
        "phase_id": "H7",
        "name": "Generated runtime install gate",
        "default_state": "implemented_as_lifecycle_gate",
        "acceptance": "Runtime install requires sandbox pass, artifact hash, operator approval, isolation profile, revoke, and rollback.",
    },
    {
        "phase_id": "H8",
        "name": "External model SLA gate",
        "default_state": "implemented_as_gateway",
        "acceptance": "Timeout, budget, and fallback settings are enforced through the model SLA gateway.",
    },
]

_FORBIDDEN_TRUE_KEYS = {
    "hardware_control_allowed",
    "hardware_control_performed",
    "provider_control_allowed",
    "outbound_send_allowed",
    "outbound_sent",
    "phase1_l0_l4_state_mutation_allowed",
    "phase1_l0_l4_state_mutated",
    "phase1_runtime_safety_truth",
    "phase1_runtime_mutated",
    "safety_api_called",
    "runtime_ingest_performed",
    "provider_values_are_scout_truth",
    "generated_runtime_code_install_allowed",
}


class HardwareSmokeCheck(SchemaModel):
    check_id: str
    phase_id: str
    status: CheckStatus
    message: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    boundary: dict[str, Any] = Field(default_factory=dict)


class HardwareSmokeReport(SchemaModel):
    artifact_kind: str = "scout_ai_os_hardware_smoke_report"
    profile_id: str = "scout_ai_os_hardware_smoke.v0"
    generated_at: str
    repo_root: str
    hardware_target: str
    env_file_loaded: bool
    model_policy: dict[str, Any]
    boundary: dict[str, Any]
    phases: list[dict[str, Any]]
    checks: list[HardwareSmokeCheck]
    summary: dict[str, Any]
    next_phase_gates: list[str]


def build_hardware_smoke_profile(
    *,
    repo_root: Path,
    hardware_target: str = "scout_hardware",
    model: Any | None = None,
    allow_external_model: bool = False,
    env_file: Path | None = None,
) -> dict[str, Any]:
    loaded_env_file = _load_env_file(env_file or repo_root / ".env")
    selected_model = _selected_model(model, allow_external_model)
    model_policy = resolve_model_policy(selected_model)
    return {
        "artifact_kind": "scout_ai_os_hardware_smoke_profile",
        "profile_id": "scout_ai_os_hardware_smoke.v0",
        "repo_root": str(repo_root),
        "hardware_target": hardware_target,
        "env_file_loaded": loaded_env_file,
        "allow_external_model": allow_external_model,
        "model_policy": model_policy.model_dump(mode="json"),
        "boundary": dict(HARDWARE_SMOKE_BOUNDARY),
        "phases": list(HARDWARE_SMOKE_PHASES),
        "default_commands": [
            "./venv/bin/scout-ai-os-hardware-smoke --repo-root /Users/alexwang0315/scout-fusion",
            "./venv/bin/scout-ai-os-hardware-smoke --repo-root /Users/alexwang0315/scout-fusion --allow-external-model --model gpt-4o-mini",
            "npm run scout-ui:operation-smoke",
        ],
    }


def run_hardware_smoke(
    *,
    repo_root: Path,
    hardware_target: str = "scout_hardware",
    model: Any | None = None,
    allow_external_model: bool = False,
    env_file: Path | None = None,
    evidence_json: Path | None = None,
) -> HardwareSmokeReport:
    repo_root = repo_root.resolve()
    loaded_env_file = _load_env_file(env_file or repo_root / ".env")
    selected_model = _selected_model(model, allow_external_model)
    model_policy = resolve_model_policy(selected_model)

    checks = [
        _check_importability(repo_root),
        _check_api_smoke(repo_root),
        _check_pydantic_smoke(
            repo_root=repo_root,
            model=selected_model,
            env_file=env_file,
        ),
        _check_ui_action_smoke(repo_root),
        _check_capability_metadata_gate(repo_root),
        _check_notification_dry_run(),
        _check_operator_confirmed_notification_gate(),
        _check_sandbox_gate(),
        _check_hardware_evidence(evidence_json),
        _check_generated_runtime_install_gate(),
        _check_external_model_sla_gate(model_policy.model_dump(mode="json")),
    ]
    return HardwareSmokeReport(
        generated_at=datetime.now(UTC).isoformat(),
        repo_root=str(repo_root),
        hardware_target=hardware_target,
        env_file_loaded=loaded_env_file,
        model_policy=model_policy.model_dump(mode="json"),
        boundary=dict(HARDWARE_SMOKE_BOUNDARY),
        phases=list(HARDWARE_SMOKE_PHASES),
        checks=checks,
        summary=_summary(checks),
        next_phase_gates=[
            "Keep generated runtime active dispatch disabled until the executor is isolated from Scout safety/runtime mutation.",
            "Wire a real external notification adapter only through the operator-confirmed low-risk provider.",
            "Extend provider-health circuit breaking with production telemetry once live model volume is available.",
            "Treat mobile/wearable data as evidence/debug/candidate-only until an explicit Phase 1 promotion gate exists.",
        ],
    )


def _selected_model(model: Any | None, allow_external_model: bool) -> Any:
    if allow_external_model:
        return model
    return "local"


def _check_importability(repo_root: Path) -> HardwareSmokeCheck:
    del repo_root
    modules = [
        "scout",
        "scout.api.routes",
        "scout.agents.model_policy",
        "scout.services.sandbox_runner",
        "scout.services.notification_gateway",
        "scout.ui_action_plan",
    ]
    imported = []
    try:
        for module_name in modules:
            import_module(module_name)
            imported.append(module_name)
    except Exception as exc:
        return _check(
            "importability",
            "H1",
            "failed",
            f"Scout AI OS module import failed: {exc}",
            {"imported": imported},
        )
    return _check(
        "importability",
        "H1",
        "passed",
        "Scout AI OS modules are importable.",
        {
            "imported": imported,
            "pydantic_ai_version": version("pydantic-ai"),
        },
    )


def _check_api_smoke(repo_root: Path) -> HardwareSmokeCheck:
    try:
        with TemporaryDirectory(prefix="scout-ai-os-hardware-api-") as tmp:
            app = create_app(Path(tmp) / "hardware.sqlite", root=repo_root)
            client = TestClient(app)
            capabilities = client.get("/capabilities")
            scheduler = client.get("/runtime/scheduler")
            refused = client.post(
                "/request-router/preview",
                json={
                    "user_id": "hardware-smoke-user",
                    "user_text": "請控制 Scout 硬體並直接發送 SOS",
                    "active_context": {"surface": "debug"},
                },
            )
            for response in (capabilities, scheduler, refused):
                response.raise_for_status()
            capability_names = {
                item["name"] for item in capabilities.json()["capabilities"]
            }
            route = refused.json()["route"]
            if route["route_class"] != "boundary_explainer":
                return _check(
                    "api_boundary_router",
                    "H1",
                    "failed",
                    "Hardware/outbound mutation request did not route to the boundary explainer.",
                    {"route": route},
                )
    except Exception as exc:
        return _check(
            "api_smoke",
            "H1",
            "failed",
            f"Scout AI OS API smoke failed: {exc}",
        )
    return _check(
        "api_smoke",
        "H1",
        "passed",
        "Scout AI OS API smoke passed with hardware/outbound boundary refusal.",
        {
            "capability_count": len(capability_names),
            "required_capabilities_present": sorted(
                capability_names
                & {"manual_notification", "time_reminder", "scout.ui.action_plan"}
            ),
            "scheduler": scheduler.json(),
            "boundary_route_class": route["route_class"],
        },
    )


def _check_pydantic_smoke(
    *,
    repo_root: Path,
    model: Any | None,
    env_file: Path | None,
) -> HardwareSmokeCheck:
    try:
        result = run_smoke(
            user_text="Remind me in 10 minutes.",
            user_id="hardware-smoke-user",
            now="2026-06-08T00:00:00+00:00",
            repo_root=repo_root,
            env_file=env_file,
            model=model,
        )
    except Exception as exc:
        return _check(
            "pydantic_ai_smoke",
            "H2",
            "failed",
            f"Pydantic AI smoke failed: {exc}",
        )

    status = result["request_status"]
    if status == "model_config_blocked":
        return _check(
            "pydantic_ai_smoke",
            "H2",
            "blocked",
            "External model smoke blocked by missing credential configuration.",
            {
                "request_status": status,
                "model": result["model"],
                "model_policy": result["model_policy"],
            },
        )
    if status not in {"installed", "needs_approval"}:
        return _check(
            "pydantic_ai_smoke",
            "H2",
            "failed",
            f"Unexpected Pydantic AI smoke status: {status}",
            _redact_smoke_result(result),
        )
    return _check(
        "pydantic_ai_smoke",
        "H2",
        "passed",
        "Pydantic AI smoke completed without secret exposure.",
        _redact_smoke_result(result),
    )


def _check_ui_action_smoke(repo_root: Path) -> HardwareSmokeCheck:
    try:
        result = run_smoke(
            user_text="請幫我關掉所有地圖圖層，只留下 risk score 相關圖層。",
            user_id="hardware-smoke-user",
            now="2026-06-08T00:00:00+00:00",
            surface="pretrip",
            repo_root=repo_root,
            model="local",
        )
    except Exception as exc:
        return _check(
            "ui_action_smoke",
            "H3",
            "failed",
            f"Session-local UI action smoke failed: {exc}",
        )
    if result["request_status"] != "ui_action_planned":
        return _check(
            "ui_action_smoke",
            "H3",
            "failed",
            "UI action request did not produce a planning-only action.",
            _redact_smoke_result(result),
        )
    return _check(
        "ui_action_smoke",
        "H3",
        "passed",
        "Session-local UI action plan was produced without applying browser or runtime effects.",
        _redact_smoke_result(result),
    )


def _check_capability_metadata_gate(repo_root: Path) -> HardwareSmokeCheck:
    try:
        with TemporaryDirectory(prefix="scout-ai-os-hardware-capability-") as tmp:
            client = TestClient(create_app(Path(tmp) / "capability.sqlite", root=repo_root))
            created = client.post(
                "/capabilities/build-candidate",
                json={
                    "user_id": "hardware-smoke-user",
                    "capability_name": "hardware_payload_echo",
                    "purpose": "Echo a low-risk JSON payload for hardware smoke.",
                    "input_schema": {"type": "object"},
                    "output_schema": {"type": "object"},
                    "risk_level": "low",
                },
            )
            created.raise_for_status()
            created_payload = created.json()
            approved = client.post(
                "/capabilities/hardware_payload_echo/approve",
                json={"user_id": "hardware-smoke-user", "approval_note": "Hardware smoke."},
            )
            approved.raise_for_status()
            approved_payload = approved.json()
    except Exception as exc:
        return _check(
            "capability_metadata_gate",
            "H7",
            "failed",
            f"Generated capability metadata gate failed: {exc}",
        )
    if (
        created_payload["status"] != "needs_approval"
        or approved_payload["capability"]["source"] != "generated_approved"
    ):
        return _check(
            "capability_metadata_gate",
            "H7",
            "failed",
            "Generated capability candidate did not stay in approval-gated metadata flow.",
            {
                "created_status": created_payload.get("status"),
                "approved_source": (approved_payload.get("capability") or {}).get("source"),
            },
        )
    return _check(
        "capability_metadata_gate",
        "H7",
        "passed",
        "Generated capability approval remains metadata-only.",
        {
            "created_status": created_payload["status"],
            "approved_status": approved_payload["capability"]["status"],
            "approved_source": approved_payload["capability"]["source"],
            "runtime_install_performed": False,
        },
    )


def _check_notification_dry_run() -> HardwareSmokeCheck:
    provider = DryRunNotificationProvider("telegram")
    gateway = NotificationGateway(provider=provider)
    result = gateway.send(
        "hardware-smoke-user",
        "Scout hardware smoke",
        "Dry-run external notification.",
        priority="normal",
        metadata={"workflow_id": "hardware-smoke-workflow"},
    )
    if result.sent:
        return _check(
            "notification_dry_run",
            "H5",
            "failed",
            "Dry-run notification provider marked the message as sent.",
            result.__dict__,
        )
    return _check(
        "notification_dry_run",
        "H5",
        "passed",
        "External notification intent was recorded without sending.",
        {
            "provider": result.provider,
            "sent": result.sent,
            "dry_run": result.metadata.get("dry_run"),
            "transport": result.metadata.get("transport"),
        },
    )


def _check_operator_confirmed_notification_gate() -> HardwareSmokeCheck:
    transport = MemoryExternalNotificationTransport()
    provider = OperatorConfirmedNotificationProvider(
        transport,
        approval=OperatorNotificationApproval(
            approved_by="hardware-smoke-operator",
            recipient_id="hardware-smoke-user",
            phrase=OPERATOR_NOTIFICATION_APPROVAL_PHRASE,
            reason="Hardware smoke low-risk notification path.",
        ),
        allowed_user_ids={"hardware-smoke-user"},
    )
    gateway = NotificationGateway(provider=provider)
    result = gateway.send(
        "hardware-smoke-user",
        "Scout hardware smoke",
        "Operator-confirmed external notification path.",
        priority="low",
        metadata={"workflow_id": "hardware-smoke-workflow", "risk": "low"},
    )
    if not result.sent or not result.metadata.get("operator_confirmed"):
        return _check(
            "operator_confirmed_notification_gate",
            "H5",
            "failed",
            "Operator-confirmed notification provider did not deliver the low-risk message.",
            result.__dict__,
        )
    return _check(
        "operator_confirmed_notification_gate",
        "H5",
        "passed",
        "Low-risk notification can use a live-send path only after operator confirmation.",
        {
            "provider": result.provider,
            "sent": result.sent,
            "operator_confirmed": result.metadata.get("operator_confirmed"),
            "transport": result.metadata.get("transport"),
            "live_network_verified": False,
        },
    )


def _check_sandbox_gate() -> HardwareSmokeCheck:
    package = GeneratedCapabilityPackage(
        spec=CapabilitySpec(
            name="network_tool",
            description="Attempt network access.",
            runtime=CapabilityRuntime.PYTHON,
            risk_level=CapabilityRisk.LOW,
            input_schema={"type": "object"},
            output_schema={"type": "object"},
        ),
        files={"network_tool.py": "import requests\n\ndef run(payload): return payload\n"},
        tests={"test_network_tool.py": "def test_placeholder(): assert True\n"},
        install_notes="Should be rejected before execution.",
    )
    result = SandboxRunner().verify(package)
    if result.passed:
        return _check(
            "sandbox_gate",
            "H6",
            "failed",
            "Sandbox accepted a generated package containing disallowed network patterns.",
            result.model_dump(mode="json"),
        )
    return _check(
        "sandbox_gate",
        "H6",
        "passed",
        "Sandbox rejected disallowed generated package before execution.",
        result.model_dump(mode="json"),
    )


def _check_hardware_evidence(evidence_json: Path | None) -> HardwareSmokeCheck:
    if evidence_json is None:
        return _check(
            "hardware_evidence_boundary",
            "H4",
            "skipped",
            "No hardware evidence JSON was provided; live/mobile ingress remains unverified in this run.",
            {"expected_flag": "--evidence-json"},
        )

    try:
        payload = json.loads(evidence_json.read_text(encoding="utf-8"))
    except Exception as exc:
        return _check(
            "hardware_evidence_boundary",
            "H4",
            "failed",
            f"Hardware evidence JSON could not be read: {exc}",
            {"path": str(evidence_json)},
        )

    boundary_values = _collect_boundary_values(payload)
    forbidden_true = {
        key: value
        for key, value in boundary_values.items()
        if key in _FORBIDDEN_TRUE_KEYS and value is True
    }
    if forbidden_true:
        return _check(
            "hardware_evidence_boundary",
            "H4",
            "blocked",
            "Hardware evidence tried to enable or report forbidden runtime effects.",
            {"path": str(evidence_json), "forbidden_true": forbidden_true},
        )
    if not boundary_values:
        return _check(
            "hardware_evidence_boundary",
            "H4",
            "blocked",
            "Hardware evidence JSON did not include boundary metadata.",
            {"path": str(evidence_json)},
        )
    return _check(
        "hardware_evidence_boundary",
        "H4",
        "passed",
        "Hardware evidence boundary metadata stayed advisory/debug/candidate-only.",
        {
            "path": str(evidence_json),
            "boundary_keys": sorted(boundary_values),
        },
    )


def _check_generated_runtime_install_gate() -> HardwareSmokeCheck:
    package = GeneratedCapabilityPackage(
        spec=CapabilitySpec(
            name="hardware_payload_echo",
            description="Echo a low-risk JSON payload for hardware smoke.",
            runtime=CapabilityRuntime.PYTHON,
            risk_level=CapabilityRisk.LOW,
            input_schema={"type": "object"},
            output_schema={"type": "object"},
        ),
        files={"hardware_payload_echo.py": "def run(payload):\n    return payload\n"},
        tests={
            "test_hardware_payload_echo.py": (
                "from hardware_payload_echo import run\n\n"
                "def test_echo():\n"
                "    assert run({'ok': True}) == {'ok': True}\n"
            )
        },
        install_notes="Hardware smoke lifecycle fixture.",
    )
    installer = GeneratedRuntimeInstaller(SandboxRunner())
    isolation_profile = RuntimeIsolationProfile(
        profile_id="hardware-smoke-container-profile",
        kind="container",
        network_allowed=False,
        read_only_root=True,
        secrets_mounted=False,
        host_paths_writable=False,
        revoke_supported=True,
        rollback_supported=True,
    )
    approval = GeneratedRuntimeInstallApproval(
        approved_by="hardware-smoke-operator",
        phrase=GENERATED_RUNTIME_INSTALL_APPROVAL_PHRASE,
        reason="Hardware smoke generated runtime lifecycle.",
    )
    plan = installer.verify_install_ready(
        package,
        isolation_profile=isolation_profile,
        approval=approval,
    )
    if plan.status != "ready":
        return _check(
            "generated_runtime_install_gate",
            "H7",
            "failed",
            "Generated runtime install lifecycle plan was blocked unexpectedly.",
            plan.model_dump(mode="json"),
        )
    installed = installer.install(
        package,
        isolation_profile=isolation_profile,
        approval=approval,
    )
    revoked = installer.revoke(installed.install_id)
    rolled_back = installer.rollback(installed.install_id)
    if (
        installed.runtime_code_executed
        or installed.active_runtime_dispatch_enabled
        or revoked.status != "revoked"
        or rolled_back.status != "rolled_back"
    ):
        return _check(
            "generated_runtime_install_gate",
            "H7",
            "failed",
            "Generated runtime install lifecycle crossed the runtime dispatch boundary.",
            {
                "installed": installed.model_dump(mode="json"),
                "revoked": revoked.model_dump(mode="json"),
                "rolled_back": rolled_back.model_dump(mode="json"),
            },
        )
    return _check(
        "generated_runtime_install_gate",
        "H7",
        "passed",
        "Generated runtime install lifecycle verified with sandbox, hash, revoke, and rollback while active dispatch stays disabled.",
        {
            "metadata_approval_supported": True,
            "runtime_install_lifecycle_supported": True,
            "runtime_code_executed": installed.runtime_code_executed,
            "active_runtime_dispatch_enabled": installed.active_runtime_dispatch_enabled,
            "artifact_hash": installed.artifact_hash,
            "install_status": installed.status,
            "revoke_status": revoked.status,
            "rollback_status": rolled_back.status,
        },
    )


def _check_external_model_sla_gate(model_policy: dict[str, Any]) -> HardwareSmokeCheck:
    policy = ModelPolicy.model_validate(model_policy)
    enforced_policy = policy.model_copy(
        update={
            "max_cost_usd": 0.0,
            "estimated_call_cost_usd": 0.001,
        }
    )
    provider_called = False

    def blocked_provider_call() -> str:
        nonlocal provider_called
        provider_called = True
        return "provider"

    result = ModelSlaGateway(
        enforced_policy,
        ledger=ModelCallLedger(max_cost_usd=enforced_policy.max_cost_usd),
    ).run_sync(
        "hardware-smoke-sla-budget",
        blocked_provider_call,
        fallback_call=lambda: "fallback",
    )
    if result.status != "budget_fallback" or provider_called:
        return _check(
            "external_model_sla_gate",
            "H8",
            "failed",
            "Model SLA gateway did not enforce budget before provider execution.",
            {
                "provider_called": provider_called,
                "model_sla": result.to_metadata(),
            },
        )
    return _check(
        "external_model_sla_gate",
        "H8",
        "passed",
        "External model timeout, budget, and fallback are enforced through the model SLA gateway.",
        {
            "timeout_seconds": model_policy["timeout_seconds"],
            "max_cost_usd": model_policy["max_cost_usd"],
            "estimated_call_cost_usd": model_policy["estimated_call_cost_usd"],
            "fallback_model": model_policy["fallback_model"],
            "live_sla_enforced": True,
            "budget_preflight_verified": True,
            "provider_called": provider_called,
            "model_sla": result.to_metadata(),
        },
    )


def _collect_boundary_values(payload: Any) -> dict[str, Any]:
    collected: dict[str, Any] = {}
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key == "boundary" and isinstance(value, dict):
                collected.update(value)
            if key in _FORBIDDEN_TRUE_KEYS:
                collected[key] = value
            collected.update(_collect_boundary_values(value))
    elif isinstance(payload, list):
        for item in payload:
            collected.update(_collect_boundary_values(item))
    return collected


def _redact_smoke_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in result.items()
        if key
        in {
            "provider",
            "pydantic_ai_version",
            "model",
            "model_policy",
            "model_sla",
            "env_file_loaded",
            "openrouter_api_key_present",
            "request_status",
            "workflow_id",
            "workflow_name",
            "trigger_type",
            "permission_required",
            "approval_required",
            "workflow_count",
            "route_class",
            "ui_action_plan_status",
            "ui_action_kind",
            "capability_count",
        }
    }


def _check(
    check_id: str,
    phase_id: str,
    status: CheckStatus,
    message: str,
    evidence: dict[str, Any] | None = None,
) -> HardwareSmokeCheck:
    return HardwareSmokeCheck(
        check_id=check_id,
        phase_id=phase_id,
        status=status,
        message=message,
        evidence=dict(evidence or {}),
        boundary=dict(HARDWARE_SMOKE_BOUNDARY),
    )


def _summary(checks: list[HardwareSmokeCheck]) -> dict[str, Any]:
    counts = {status: 0 for status in ("passed", "blocked", "skipped", "failed")}
    for check in checks:
        counts[check.status] += 1
    return {
        **counts,
        "check_count": len(checks),
        "hardware_ready_for_safe_smoke": counts["failed"] == 0,
        "runtime_install_ready": _check_status(checks, "generated_runtime_install_gate")
        == "passed",
        "generated_runtime_dispatch_ready": False,
        "live_external_notification_ready": _check_status(
            checks,
            "operator_confirmed_notification_gate",
        )
        == "passed",
        "live_external_notification_network_verified": False,
        "external_model_sla_ready": _check_status(checks, "external_model_sla_gate")
        == "passed",
    }


def _check_status(checks: list[HardwareSmokeCheck], check_id: str) -> str | None:
    for check in checks:
        if check.check_id == check_id:
            return check.status
    return None


def _load_env_file(path: Path) -> bool:
    if not path.exists():
        return False

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        os.environ.setdefault(key, value.strip().strip('"').strip("'"))
    return True


__all__ = [
    "HARDWARE_SMOKE_BOUNDARY",
    "HARDWARE_SMOKE_PHASES",
    "HardwareSmokeCheck",
    "HardwareSmokeReport",
    "build_hardware_smoke_profile",
    "run_hardware_smoke",
]
