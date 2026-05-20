from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from assistant_ui_smoke_check import build_assistant_ui_smoke_check


REPO_ROOT = Path(__file__).resolve().parent

ASSISTANT_FOUNDATION_PATHS = (
    "assistant_model_config.py",
    "assistant_models.py",
    "assistant_provider.py",
    "assistant_pydantic_provider.py",
    "assistant_context.py",
    "assistant_api.py",
    "debug_assistant_context.py",
    "admin_assistant_context.py",
    "pretrip_assistant_context.py",
    "hardware_readiness_assistant_context.py",
    "hardware_readiness_admin_view.py",
    "hardware_readiness_api.py",
)

REQUIRED_PATHS = (
    "docs/specs/scout-cross-surface-ai-assistant.md",
    "docs/specs/pi5-local-ai-runtime-experiment.md",
    *ASSISTANT_FOUNDATION_PATHS,
    "server.py",
    "docs/admin/cross-surface-ai-assistant-runbook.md",
    "docs/admin/scout-assistant-ui.js",
    "docs/admin/phase-3-5-runtime-debug.html",
    "docs/admin/phase1-after-action.html",
    "docs/admin/phase4-pretrip-planning.html",
    "docs/admin/phase-3-6-hardware-readiness.html",
    "docs/admin/hardware-readiness-assistant-runbook.md",
    "docs/admin/assistant-browser-smoke.md",
    "docs/admin/screenshots/assistant-browser-live-debug.jpg",
    "docs/admin/screenshots/assistant-browser-live-pretrip.jpg",
    "docs/admin/screenshots/assistant-browser-live-admin.jpg",
    "docs/admin/screenshots/assistant-browser-live-hardware-readiness.jpg",
    "assistant_ui_smoke_check.py",
    "tests/fixtures/hardware/readiness_context.json",
    "tests/test_assistant_models.py",
    "tests/test_assistant_model_config.py",
    "tests/test_assistant_provider.py",
    "tests/test_assistant_pydantic_provider.py",
    "tests/test_assistant_api.py",
    "tests/test_assistant_context.py",
    "tests/test_assistant_page.py",
    "tests/test_assistant_readiness_check.py",
    "tests/test_assistant_ui_smoke_check.py",
    "tests/test_assistant_browser_smoke_doc.py",
    "tests/test_hardware_readiness_api.py",
    "tests/test_hardware_readiness_runbook.py",
)

SPEC_GUARDRAILS = (
    "Milestone 10",
    "Phase 1 remains the deterministic live safety authority",
    "first implementation should be mock-backed and deterministic",
    "read-only model interpretation",
    "irreversible runtime, store, review, outbound, or hardware actions",
    "call `/safety/*` mutation endpoints",
    "write `ObservedFact`",
    "control hardware, sensors, providers, transport, SOS, SMS, or satellite",
    "Pydantic AI provider is opt-in",
    "no assistant response can mutate Phase 1, Phase 2 Brain, IncidentStore",
    "這不是 Scout safety runtime",
    "這不是 ObservedFact writer",
    "這不是 outbound action surface",
    "跨介面資料狀態助理",
)

MILESTONE_10_2_FAILOVER_CONTRACT_TOKENS = (
    "Milestone 10.2: Cloud-to-Local Assistant Failover Guardrail",
    "docs/specs/pi5-local-ai-runtime-experiment.md",
    "qwen2.5:0.5b",
    "fallback_to_local_on_error=true",
    "Pi field profile",
    "Mac/dev default remains mock or cloud-only",
    "max local concurrency = 1",
    "short timeout, initially 6-10s",
    "no unbounded queue",
    "discard stale model requests",
    "model_profile_used",
    "failover_reason",
    "local_model_name",
    "no local model listener is started by readiness checks",
    "never let local AI directly change L0-L4 safety state",
)

MILESTONE_10_2_FAILOVER_HARDENING_TOKENS: dict[str, tuple[str, ...]] = {
    "assistant_pydantic_provider.py": (
        "max_fallback_concurrency",
        "LocalFallbackBusy",
        "local_busy:discard_stale_request",
        "local_run_error",
        "primary_run_error",
        "local_model_name",
    ),
    "assistant_models.py": (
        "model_profile_used",
        "failover_reason",
        "local_model_name",
    ),
    "assistant_api.py": (
        "_provider_metadata",
        "model_profile_used",
        "failover_reason",
        "local_model_name",
    ),
}

MILESTONE_10_2_PI_PROFILE_STATUS_TOKENS: dict[str, tuple[str, ...]] = {
    "assistant_api.py": (
        "SCOUT_RUNTIME_PROFILE",
        "runtime_profile",
        "local_fallback_mode",
        "pi_field_manual_opt_in",
        "configured_not_pi_field",
        "manual_verification_required",
        "readiness_starts_local_model",
        "local_model_listener_required_for_readiness",
        "status_model_switch_allowed",
    ),
    "docs/specs/scout-cross-surface-ai-assistant.md": (
        "Milestone 10.2 Slice 3: Pi Field Profile Status + Manual Failover Runbook",
        "SCOUT_RUNTIME_PROFILE=pi-field",
        "manual Pi/Ollama verification",
        "not part of the assistant readiness gate",
        "readiness_starts_local_model=false",
        "local_model_listener_required_for_readiness=false",
        "status_model_switch_allowed=false",
    ),
    "docs/admin/cross-surface-ai-assistant-runbook.md": (
        "Milestone 10.2 Slice 3",
        "SCOUT_RUNTIME_PROFILE=pi-field",
        "manual Pi/Ollama verification",
        "curl --max-time",
        "readiness_starts_local_model=false",
        "local_model_listener_required_for_readiness=false",
        "status_model_switch_allowed=false",
    ),
}

ASSISTANT_FOUNDATION_FORBIDDEN_TOKENS = (
    "SafetyRuntimeSession",
    "BrainFileStore",
    "IncidentStore",
    "ObservedFactWriter",
    "ObservedFact writer",
    "ObservedFact writeback",
    "observed_fact_writer",
    "observed_fact_writeback",
    "write_observed_fact",
    "record_observed_fact",
    "requests",
    "httpx",
    "urllib",
    "socket",
    "twilio",
    "@router.put",
    "@router.patch",
    "@router.delete",
)

SERVER_OPT_IN_MOUNT_TOKENS = (
    "SCOUT_AI_ASSISTANT_ENABLED",
    "SCOUT_AI_ASSISTANT_PROVIDER",
    "SCOUT_AI_ASSISTANT_CONFIG_PATH",
    "create_assistant_router",
    "create_assistant_context_resolver",
    "_include_assistant_router",
    "mock",
    "context_resolver=create_assistant_context_resolver",
)

RUNBOOK_TOKENS = (
    "mock provider",
    "SCOUT_AI_ASSISTANT_PROVIDER=mock",
    "SCOUT_AI_ASSISTANT_PROVIDER=pydantic_ai",
    "SCOUT_AI_ASSISTANT_CONFIG_PATH",
    "SCOUT_AI_ASSISTANT_ENABLED=1",
    "Pydantic AI opt-in",
    "cloud_model",
    "local_model",
    "token_id",
    "fallback to local model",
    "read-only model interpretation",
    "ModelInterpretation",
    "不可寫 Phase 1",
    "不可寫 Phase 2",
    "不可寫 Phase 4",
    "不可送 outbound",
    "不可控制 hardware",
    "assistant_readiness_check.py --pretty",
    "/assistant/query",
    "/assistant/status",
    "/admin/hardware-readiness",
    "AssistantObservability",
    "POST 只是查詢 body",
)

HARDWARE_READINESS_RUNBOOK_TOKENS = (
    "/admin/hardware-readiness",
    "/admin/hardware-readiness/context",
    "fixture-backed/read-only",
    "read-only model interpretation",
    "不啟動 Pi",
    "不啟動 Docker",
    "不啟動 k3s",
    "不啟動 MQTT",
    "不啟動 NATS",
    "不啟動 Coral",
    "不啟動 Jetson",
    "不控制 provider",
    "不切換 model provider",
    "不讀取 token value",
    "不送真 SOS",
    "不送真 SMS",
    "不送真 satellite",
    "不呼叫 `/safety/*` mutation",
    "不寫 ObservedFact",
    "不寫 Brain",
    "不寫 IncidentStore",
    "不寫 review decision",
    "不核准 departure",
)

BROWSER_SMOKE_DOC_TOKENS = (
    "browser-backed visual QA",
    "read-only model interpretation",
    "/assistant/query",
    "/assistant/status",
    "http://127.0.0.1:9110/admin/debug",
    "http://127.0.0.1:9110/admin/pretrip",
    "http://127.0.0.1:9110/admin",
    "http://127.0.0.1:9110/admin/hardware-readiness",
    "不呼叫 `/safety/*` mutation",
    "不寫 ObservedFact",
    "不寫 Phase 2 Brain",
    "不寫 IncidentStore",
    "不接受或拒絕 pretrip candidate",
    "不送 outbound message",
    "不控制 hardware",
    "不啟動本地模型",
    "11434",
    "cloud_only",
    "local_fallback_enabled",
    "token_values_exposed",
)


def build_readiness_check(repo_root: Path | str = REPO_ROOT) -> dict[str, Any]:
    root = Path(repo_root)
    checks: dict[str, Any] = {}
    missing_required: list[str] = []

    required_paths = _check_required_paths(root, REQUIRED_PATHS)
    checks["required_paths"] = required_paths
    missing_required.extend(required_paths["missing"])

    spec_guardrails = _check_spec_guardrails(root)
    checks["spec_guardrails"] = spec_guardrails
    missing_required.extend(spec_guardrails["missing"])

    failover_contract = _check_milestone_10_2_failover_contract(root)
    checks["milestone_10_2_failover_contract"] = failover_contract
    missing_required.extend(failover_contract["missing"])

    failover_hardening = _check_milestone_10_2_failover_hardening(root)
    checks["milestone_10_2_failover_hardening"] = failover_hardening
    missing_required.extend(failover_hardening["missing"])

    pi_profile_status = _check_milestone_10_2_pi_profile_status(root)
    checks["milestone_10_2_pi_profile_status"] = pi_profile_status
    missing_required.extend(pi_profile_status["missing"])

    assistant_foundation = _check_assistant_foundation_static_boundaries(root)
    checks["assistant_foundation_static_boundaries"] = assistant_foundation
    missing_required.extend(assistant_foundation["missing"])

    server_mount = _check_server_opt_in_mount(root)
    checks["server_opt_in_mount"] = server_mount
    missing_required.extend(server_mount["missing"])

    runbook = _check_runbook(root)
    checks["runbook"] = runbook
    missing_required.extend(runbook["missing"])

    hardware_runbook = _check_hardware_readiness_runbook(root)
    checks["hardware_readiness_runbook"] = hardware_runbook
    missing_required.extend(hardware_runbook["missing"])

    assistant_ui_smoke_gate = _check_assistant_ui_smoke_gate(root)
    checks["assistant_ui_smoke_gate"] = assistant_ui_smoke_gate
    missing_required.extend(assistant_ui_smoke_gate["missing"])

    browser_smoke_doc = _check_browser_smoke_doc(root)
    checks["browser_smoke_doc"] = browser_smoke_doc
    missing_required.extend(browser_smoke_doc["missing"])

    failed_checks = sorted(name for name, check in checks.items() if not check["ok"])
    missing_required = sorted(set(missing_required))
    return {
        "ok": not failed_checks,
        "repo_root": str(root),
        "checks": checks,
        "failed_checks": failed_checks,
        "missing_required_artifacts": missing_required,
    }


def _check_required_paths(root: Path, required_paths: Sequence[str]) -> dict[str, Any]:
    missing = sorted(path for path in required_paths if not (root / path).exists())
    return {
        "ok": not missing,
        "required": len(required_paths),
        "present": len(required_paths) - len(missing),
        "missing": missing,
    }


def _check_spec_guardrails(root: Path) -> dict[str, Any]:
    spec_path = root / "docs/specs/scout-cross-surface-ai-assistant.md"
    if not spec_path.exists():
        return {"ok": False, "missing": [spec_path.relative_to(root).as_posix()]}

    source = spec_path.read_text(encoding="utf-8")
    missing = [
        f"spec_guardrail:{guardrail}"
        for guardrail in SPEC_GUARDRAILS
        if guardrail not in source
    ]
    return {"ok": not missing, "missing": missing}


def _check_milestone_10_2_failover_contract(root: Path) -> dict[str, Any]:
    spec_path = root / "docs/specs/scout-cross-surface-ai-assistant.md"
    if not spec_path.exists():
        return {"ok": False, "missing": [spec_path.relative_to(root).as_posix()]}

    source = spec_path.read_text(encoding="utf-8")
    missing = [
        f"milestone_10_2_failover_contract_token:{token}"
        for token in MILESTONE_10_2_FAILOVER_CONTRACT_TOKENS
        if token not in source
    ]
    return {"ok": not missing, "missing": missing}


def _check_milestone_10_2_failover_hardening(root: Path) -> dict[str, Any]:
    missing: list[str] = []
    for relative_path, tokens in MILESTONE_10_2_FAILOVER_HARDENING_TOKENS.items():
        path = root / relative_path
        if not path.exists():
            missing.append(relative_path)
            continue
        source = path.read_text(encoding="utf-8")
        missing.extend(
            f"milestone_10_2_failover_hardening_token:{relative_path}:{token}"
            for token in tokens
            if token not in source
        )
    return {"ok": not missing, "missing": missing}


def _check_milestone_10_2_pi_profile_status(root: Path) -> dict[str, Any]:
    missing: list[str] = []
    for relative_path, tokens in MILESTONE_10_2_PI_PROFILE_STATUS_TOKENS.items():
        path = root / relative_path
        if not path.exists():
            missing.append(relative_path)
            continue
        source = path.read_text(encoding="utf-8")
        missing.extend(
            f"milestone_10_2_pi_profile_status_token:{relative_path}:{token}"
            for token in tokens
            if token not in source
        )
    return {"ok": not missing, "missing": missing}


def _check_assistant_foundation_static_boundaries(root: Path) -> dict[str, Any]:
    missing: list[str] = []
    scanned_paths: list[str] = []

    for relative_path in ASSISTANT_FOUNDATION_PATHS:
        path = root / relative_path
        if not path.exists():
            continue
        scanned_paths.append(relative_path)
        source = path.read_text(encoding="utf-8")
        missing.extend(
            f"assistant_foundation_forbidden_token:{relative_path}:{token}"
            for token in ASSISTANT_FOUNDATION_FORBIDDEN_TOKENS
            if token in source
        )

    return {
        "ok": not missing,
        "scanned": scanned_paths,
        "missing": sorted(missing),
    }


def _check_server_opt_in_mount(root: Path) -> dict[str, Any]:
    server_path = root / "server.py"
    if not server_path.exists():
        return {"ok": False, "missing": ["server.py"]}

    source = server_path.read_text(encoding="utf-8")
    missing = [
        f"server_opt_in_mount_token:{token}"
        for token in SERVER_OPT_IN_MOUNT_TOKENS
        if token not in source
    ]
    return {"ok": not missing, "missing": missing}


def _check_runbook(root: Path) -> dict[str, Any]:
    runbook_path = root / "docs/admin/cross-surface-ai-assistant-runbook.md"
    if not runbook_path.exists():
        return {"ok": False, "missing": [runbook_path.relative_to(root).as_posix()]}

    source = runbook_path.read_text(encoding="utf-8")
    missing = [
        f"runbook_token:{token}"
        for token in RUNBOOK_TOKENS
        if token not in source
    ]
    return {"ok": not missing, "missing": missing}


def _check_hardware_readiness_runbook(root: Path) -> dict[str, Any]:
    runbook_path = root / "docs/admin/hardware-readiness-assistant-runbook.md"
    if not runbook_path.exists():
        return {"ok": False, "missing": [runbook_path.relative_to(root).as_posix()]}

    source = runbook_path.read_text(encoding="utf-8")
    missing = [
        f"hardware_readiness_runbook_token:{token}"
        for token in HARDWARE_READINESS_RUNBOOK_TOKENS
        if token not in source
    ]
    return {"ok": not missing, "missing": missing}


def _check_assistant_ui_smoke_gate(root: Path) -> dict[str, Any]:
    result = build_assistant_ui_smoke_check(root)
    return {
        "ok": result["ok"],
        "failed_checks": result["failed_checks"],
        "missing": result["missing_required_artifacts"],
    }


def _check_browser_smoke_doc(root: Path) -> dict[str, Any]:
    doc_path = root / "docs/admin/assistant-browser-smoke.md"
    if not doc_path.exists():
        return {"ok": False, "missing": [doc_path.relative_to(root).as_posix()]}

    source = doc_path.read_text(encoding="utf-8")
    missing = [
        f"browser_smoke_doc_token:{token}"
        for token in BROWSER_SMOKE_DOC_TOKENS
        if token not in source
    ]
    return {"ok": not missing, "missing": missing}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the Scout Milestone 10 cross-surface AI assistant readiness check."
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    result = build_readiness_check(args.repo_root)
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
