from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_PORT = 9111
DEFAULT_BASE_URL = f"http://127.0.0.1:{DEFAULT_PORT}"
DEFAULT_WAIT_SECONDS = 20.0


class AdminHardwarePrototypeSmokeBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host_side_local_only: bool = True
    target_network_calls_performed: bool = False
    safety_mutation_performed: bool = False
    phase1_safety_decision_mutation_allowed: bool = False
    outbound_messages_allowed: bool = False
    local_model_start_allowed: bool = False
    hardware_provider_control_allowed: bool = False
    real_sos_sms_satellite_allowed: bool = False
    provider_profile: Literal["mock"] = "mock"


class AdminHardwarePrototypeSmokeStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str
    status: Literal["passed", "failed", "skipped"]
    command: list[str] = []
    summary: str
    returncode: int | None = None
    missing_required_artifacts: list[str] = []


class AdminHardwarePrototypeSmokeCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: int
    failed: int
    skipped: int
    step_count: int


class AdminHardwarePrototypeSmokeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: Literal["admin_hardware_prototype_smoke_result"] = (
        "admin_hardware_prototype_smoke_result"
    )
    status: Literal["passed", "failed"]
    base_url: str
    port: int
    server_started: bool
    browser_mode: Literal["auto", "required", "skip"]
    boundary: AdminHardwarePrototypeSmokeBoundary
    steps: list[AdminHardwarePrototypeSmokeStep]
    counts: AdminHardwarePrototypeSmokeCounts


def build_smoke_environment(
    environ: dict[str, str] | None = None,
    *,
    port: int = DEFAULT_PORT,
) -> dict[str, str]:
    env = dict(environ or os.environ)
    env.update(
        {
            "SCOUT_PORT": str(port),
            "SCOUT_SAFETY_ENABLED": "false",
            "SCOUT_DEBUG_API_ENABLED": "1",
            "SCOUT_AI_ASSISTANT_ENABLED": "1",
            "SCOUT_AI_ASSISTANT_PROVIDER": "mock",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    env.pop("SCOUT_AI_ASSISTANT_CONFIG_PATH", None)
    return env


def planned_steps(*, browser_mode: str) -> list[AdminHardwarePrototypeSmokeStep]:
    steps = [
        AdminHardwarePrototypeSmokeStep(
            step_id="assistant_status",
            status="skipped",
            summary="GET /assistant/status on localhost only",
        ),
        AdminHardwarePrototypeSmokeStep(
            step_id="assistant_ui_static_gate",
            status="skipped",
            command=[sys.executable, "assistant_ui_smoke_check.py", "--pretty"],
            summary="static assistant UI shell and no-action-button gate",
        ),
        AdminHardwarePrototypeSmokeStep(
            step_id="assistant_readiness_gate",
            status="skipped",
            command=[sys.executable, "assistant_readiness_check.py", "--pretty"],
            summary="Milestone 10 read-only assistant readiness gate",
        ),
    ]
    if browser_mode != "skip":
        steps.append(
            AdminHardwarePrototypeSmokeStep(
                step_id="assistant_browser_gate",
                status="skipped",
                command=[sys.executable, "assistant_browser_smoke_check.py", "--pretty"],
                summary="desktop/mobile browser gate over admin, debug, pretrip, and hardware readiness surfaces",
            )
        )
    return steps


def run_admin_hardware_prototype_smoke(
    *,
    python_executable: str,
    node_executable: str,
    node_path: str | None,
    port: int,
    browser_mode: Literal["auto", "required", "skip"],
    wait_seconds: float,
) -> AdminHardwarePrototypeSmokeResult:
    base_url = f"http://127.0.0.1:{port}"
    env = build_smoke_environment(port=port)
    server = subprocess.Popen(
        [python_executable, "server.py"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        text=True,
    )
    steps: list[AdminHardwarePrototypeSmokeStep] = []
    server_started = True
    try:
        steps.append(_wait_for_assistant_status(base_url, wait_seconds))
        if steps[-1].status == "passed":
            steps.append(
                _run_json_gate(
                    "assistant_ui_static_gate",
                    [python_executable, "assistant_ui_smoke_check.py", "--pretty"],
                    "static assistant UI shell and no-action-button gate",
                )
            )
            steps.append(
                _run_json_gate(
                    "assistant_readiness_gate",
                    [python_executable, "assistant_readiness_check.py", "--pretty"],
                    "Milestone 10 read-only assistant readiness gate",
                )
            )
            steps.append(
                _run_browser_gate(
                    python_executable=python_executable,
                    node_executable=node_executable,
                    node_path=node_path,
                    base_url=base_url,
                    browser_mode=browser_mode,
                )
            )
    finally:
        _stop_process(server)

    return build_smoke_result(
        base_url=base_url,
        port=port,
        server_started=server_started,
        browser_mode=browser_mode,
        steps=steps,
    )


def build_plan_only_result(
    *,
    port: int,
    browser_mode: Literal["auto", "required", "skip"],
) -> AdminHardwarePrototypeSmokeResult:
    return build_smoke_result(
        base_url=f"http://127.0.0.1:{port}",
        port=port,
        server_started=False,
        browser_mode=browser_mode,
        steps=planned_steps(browser_mode=browser_mode),
    )


def _wait_for_assistant_status(
    base_url: str,
    wait_seconds: float,
) -> AdminHardwarePrototypeSmokeStep:
    deadline = time.monotonic() + wait_seconds
    last_error = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/assistant/status", timeout=2) as response:
                payload = json.loads(response.read().decode("utf-8"))
            missing = _assistant_status_missing(payload)
            return AdminHardwarePrototypeSmokeStep(
                step_id="assistant_status",
                status="failed" if missing else "passed",
                summary="assistant status is mock, read-only, and token-safe"
                if not missing
                else "assistant status did not match the local mock read-only boundary",
                missing_required_artifacts=missing,
            )
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            last_error = str(exc)
            time.sleep(0.25)
    return AdminHardwarePrototypeSmokeStep(
        step_id="assistant_status",
        status="failed",
        summary=f"server did not expose /assistant/status before timeout: {last_error}",
        missing_required_artifacts=["assistant_status_unavailable"],
    )


def _assistant_status_missing(payload: dict[str, Any]) -> list[str]:
    expected = {
        "read_only": True,
        "model_interpretation": True,
        "provider": "mock",
        "provider_class": "MockAssistantProvider",
        "token_values_exposed": False,
        "readiness_starts_local_model": False,
        "status_model_switch_allowed": False,
    }
    missing: list[str] = []
    for key, value in expected.items():
        if payload.get(key) != value:
            missing.append(f"assistant_status:{key}!={value}")
    return missing


def _run_json_gate(
    step_id: str,
    command: list[str],
    summary: str,
) -> AdminHardwarePrototypeSmokeStep:
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError as exc:
        return AdminHardwarePrototypeSmokeStep(
            step_id=step_id,
            status="failed",
            command=command,
            summary=f"{summary}: command not found",
            missing_required_artifacts=[f"{step_id}:command_not_found:{exc.filename}"],
        )
    except subprocess.TimeoutExpired:
        return AdminHardwarePrototypeSmokeStep(
            step_id=step_id,
            status="failed",
            command=command,
            summary=f"{summary}: timed out",
            missing_required_artifacts=[f"{step_id}:timeout"],
        )
    missing = _missing_from_json_stdout(completed.stdout)
    if completed.returncode != 0 and not missing:
        missing = [f"{step_id}:nonzero_returncode:{completed.returncode}"]
    return AdminHardwarePrototypeSmokeStep(
        step_id=step_id,
        status="passed" if completed.returncode == 0 and not missing else "failed",
        command=command,
        summary=summary,
        returncode=completed.returncode,
        missing_required_artifacts=missing,
    )


def _run_browser_gate(
    *,
    python_executable: str,
    node_executable: str,
    node_path: str | None,
    base_url: str,
    browser_mode: Literal["auto", "required", "skip"],
) -> AdminHardwarePrototypeSmokeStep:
    if browser_mode == "skip":
        return AdminHardwarePrototypeSmokeStep(
            step_id="assistant_browser_gate",
            status="skipped",
            summary="browser smoke skipped by operator request",
        )

    if browser_mode == "auto" and not node_path and not os.getenv("SCOUT_BROWSER_NODE_PATH"):
        return AdminHardwarePrototypeSmokeStep(
            step_id="assistant_browser_gate",
            status="skipped",
            summary="browser smoke skipped because SCOUT_BROWSER_NODE_PATH was not configured",
            missing_required_artifacts=["assistant_browser_gate_auto_skipped:no_node_path"],
        )

    command = [
        python_executable,
        "assistant_browser_smoke_check.py",
        "--base-url",
        base_url,
        "--node",
        node_executable,
        "--pretty",
    ]
    resolved_node_path = node_path or os.getenv("SCOUT_BROWSER_NODE_PATH")
    if resolved_node_path:
        command.extend(["--node-path", resolved_node_path])

    return _run_json_gate(
        "assistant_browser_gate",
        command,
        "desktop/mobile browser gate over admin, debug, pretrip, and hardware readiness surfaces",
    )


def _missing_from_json_stdout(stdout: str) -> list[str]:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return ["json_stdout_unparseable"]
    if payload.get("ok") is True:
        return []
    missing = payload.get("missing_required_artifacts")
    if isinstance(missing, list):
        return [str(item) for item in missing]
    return ["json_gate_not_ok"]


def build_smoke_result(
    *,
    base_url: str,
    port: int,
    server_started: bool,
    browser_mode: Literal["auto", "required", "skip"],
    steps: list[AdminHardwarePrototypeSmokeStep],
) -> AdminHardwarePrototypeSmokeResult:
    failed = sum(1 for step in steps if step.status == "failed")
    skipped = sum(1 for step in steps if step.status == "skipped")
    passed = sum(1 for step in steps if step.status == "passed")
    return AdminHardwarePrototypeSmokeResult(
        status="failed" if failed else "passed",
        base_url=base_url,
        port=port,
        server_started=server_started,
        browser_mode=browser_mode,
        boundary=AdminHardwarePrototypeSmokeBoundary(),
        steps=steps,
        counts=AdminHardwarePrototypeSmokeCounts(
            passed=passed,
            failed=failed,
            skipped=skipped,
            step_count=len(steps),
        ),
    )


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the local read-only admin/hardware prototype smoke gate."
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--node", default=os.getenv("SCOUT_BROWSER_NODE", "node"))
    parser.add_argument("--node-path", default=os.getenv("SCOUT_BROWSER_NODE_PATH"))
    parser.add_argument(
        "--browser-mode",
        choices=("auto", "required", "skip"),
        default="auto",
    )
    parser.add_argument("--wait-seconds", type=float, default=DEFAULT_WAIT_SECONDS)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    if args.plan_only:
        result = build_plan_only_result(port=args.port, browser_mode=args.browser_mode)
    else:
        result = run_admin_hardware_prototype_smoke(
            python_executable=args.python,
            node_executable=args.node,
            node_path=args.node_path,
            port=args.port,
            browser_mode=args.browser_mode,
            wait_seconds=args.wait_seconds,
        )

    print(result.model_dump_json(indent=2 if args.pretty else None))
    return 0 if result.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
