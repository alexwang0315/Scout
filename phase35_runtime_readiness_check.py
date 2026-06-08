from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parent

REQUIRED_PATHS = (
    "docs/specs/phase-3-5-runtime-readiness-debug-tooling.md",
    "runtime_debug_models.py",
    "runtime_debug_log.py",
    "runtime_simulator.py",
    "runtime_debug_replay_demo.py",
    "runtime_debug_ui_demo.py",
    "phase35_debug_demo_loader.py",
    "mock_outbound_transport.py",
    "debug_api.py",
    "docs/admin/phase-3-5-runtime-debug.html",
    "docs/admin/phase-3-5-debug-runbook.md",
    "tests/test_runtime_debug_event_log.py",
    "tests/test_runtime_simulator.py",
    "tests/test_runtime_debug_ui_demo.py",
    "tests/test_mock_outbound_transport.py",
    "tests/test_debug_api.py",
    "tests/test_debug_api_mount.py",
    "tests/test_debug_page.py",
    "tests/test_phase35_debug_runbook.py",
    "tests/test_phase35_runtime_readiness_check.py",
)

SPEC_GUARDRAILS = (
    "這不是一般使用者 UI",
    "這不是 pre-trip planning",
    "hardware/debug/readiness tooling",
    "`/debug` 必須 read-only",
    "debug event 不能影響 Scout safety runtime",
    "outbound message 初期必須是 mock transport",
)

FORBIDDEN_DEBUG_API_TOKENS = (
    "SafetyRuntimeSession",
    "safety_runtime_session",
    "BrainFileStore",
    "IncidentStore",
    "@router.post",
    "@router.patch",
    "@router.put",
    "@router.delete",
)

FORBIDDEN_MOCK_TRANSPORT_TOKENS = (
    "requests",
    "httpx",
    "urllib",
    "twilio",
    "socket",
)

SERVER_MOUNT_TOKENS = (
    "SCOUT_DEBUG_API_ENABLED",
    "SCOUT_DEBUG_LOG_PATH",
    "FileRuntimeDebugEventLog",
    "create_debug_router",
    "create_debug_page_router",
    "_include_debug_router",
)

RUNBOOK_TOKENS = (
    "phase35_debug_demo_loader.py --pretty",
    "SCOUT_DEBUG_API_ENABLED=1",
    "SCOUT_DEBUG_LOG_PATH",
    "SCOUT_SAFETY_ENABLED=false",
    "/admin/debug",
    "/debug/events",
    "/debug/state",
    "/debug/messages",
    "這不是一般使用者 UI",
    "debug event 不能影響 Scout safety runtime",
    "mock transport",
)


@dataclass(frozen=True)
class PathCheck:
    name: str
    required_paths: tuple[str, ...]


def build_release_check(repo_root: Path | str = REPO_ROOT) -> dict[str, Any]:
    root = Path(repo_root)
    checks: dict[str, Any] = {}
    missing_required: list[str] = []

    required_paths = _check_required_paths(root, REQUIRED_PATHS)
    checks["required_paths"] = required_paths
    missing_required.extend(required_paths["missing"])

    spec_guardrails = _check_spec_guardrails(root)
    checks["spec_guardrails"] = spec_guardrails
    missing_required.extend(spec_guardrails["missing"])

    static_boundaries = _check_static_boundaries(root)
    checks["static_boundaries"] = static_boundaries
    missing_required.extend(static_boundaries["missing"])

    server_mount = _check_server_mount(root)
    checks["server_mount"] = server_mount
    missing_required.extend(server_mount["missing"])

    runbook = _check_runbook(root)
    checks["runbook"] = runbook
    missing_required.extend(runbook["missing"])

    missing_required = sorted(set(missing_required))
    return {
        "ok": not missing_required,
        "repo_root": str(root),
        "checks": checks,
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
    spec_path = root / "docs/specs/phase-3-5-runtime-readiness-debug-tooling.md"
    if not spec_path.exists():
        return {"ok": False, "missing": [str(spec_path.relative_to(root))]}
    source = spec_path.read_text(encoding="utf-8")
    missing = [
        f"spec_guardrail:{guardrail}"
        for guardrail in SPEC_GUARDRAILS
        if guardrail not in source
    ]
    return {"ok": not missing, "missing": missing}


def _check_static_boundaries(root: Path) -> dict[str, Any]:
    missing: list[str] = []
    debug_api = root / "debug_api.py"
    mock_transport = root / "mock_outbound_transport.py"
    debug_models = root / "runtime_debug_models.py"
    debug_log = root / "runtime_debug_log.py"

    if debug_api.exists():
        source = debug_api.read_text(encoding="utf-8")
        missing.extend(
            f"debug_api_forbidden_token:{token}"
            for token in FORBIDDEN_DEBUG_API_TOKENS
            if token in source
        )
    if mock_transport.exists():
        source = mock_transport.read_text(encoding="utf-8")
        missing.extend(
            f"mock_transport_forbidden_token:{token}"
            for token in FORBIDDEN_MOCK_TRANSPORT_TOKENS
            if token in source
        )
    for path in (debug_models, debug_log):
        if path.exists() and "SafetyRuntimeSession" in path.read_text(encoding="utf-8"):
            missing.append(f"debug_foundation_imports_safety_runtime:{path.name}")

    return {"ok": not missing, "missing": sorted(missing)}


def _check_server_mount(root: Path) -> dict[str, Any]:
    server_path = root / "server.py"
    if not server_path.exists():
        return {"ok": False, "missing": ["server.py"]}
    source = server_path.read_text(encoding="utf-8")
    missing = [
        f"server_mount_token:{token}"
        for token in SERVER_MOUNT_TOKENS
        if token not in source
    ]
    return {"ok": not missing, "missing": missing}


def _check_runbook(root: Path) -> dict[str, Any]:
    runbook_path = root / "docs" / "admin" / "phase-3-5-debug-runbook.md"
    if not runbook_path.exists():
        return {"ok": False, "missing": [str(runbook_path.relative_to(root))]}
    source = runbook_path.read_text(encoding="utf-8")
    missing = [
        f"runbook_token:{token}"
        for token in RUNBOOK_TOKENS
        if token not in source
    ]
    return {"ok": not missing, "missing": missing}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Scout Phase 3.5 runtime readiness check.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)
    result = build_release_check(args.repo_root)
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
