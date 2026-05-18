from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence


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
)

REQUIRED_PATHS = (
    "docs/specs/scout-cross-surface-ai-assistant.md",
    *ASSISTANT_FOUNDATION_PATHS,
    "server.py",
    "docs/admin/cross-surface-ai-assistant-runbook.md",
    "tests/test_assistant_models.py",
    "tests/test_assistant_model_config.py",
    "tests/test_assistant_provider.py",
    "tests/test_assistant_pydantic_provider.py",
    "tests/test_assistant_api.py",
    "tests/test_assistant_context.py",
    "tests/test_assistant_page.py",
    "tests/test_assistant_readiness_check.py",
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
    "POST 只是查詢 body",
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

    assistant_foundation = _check_assistant_foundation_static_boundaries(root)
    checks["assistant_foundation_static_boundaries"] = assistant_foundation
    missing_required.extend(assistant_foundation["missing"])

    server_mount = _check_server_opt_in_mount(root)
    checks["server_opt_in_mount"] = server_mount
    missing_required.extend(server_mount["missing"])

    runbook = _check_runbook(root)
    checks["runbook"] = runbook
    missing_required.extend(runbook["missing"])

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
