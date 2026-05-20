from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from admin_hardware_prototype_smoke_check import (
    AdminHardwarePrototypeSmokeStep,
    build_plan_only_result,
    build_smoke_environment,
    build_smoke_result,
)


ROOT = Path(__file__).resolve().parents[1]


def test_smoke_environment_is_local_mock_and_read_only() -> None:
    env = build_smoke_environment(
        {
            "SCOUT_AI_ASSISTANT_CONFIG_PATH": "/tmp/should-not-survive.json",
            "SCOUT_AI_ASSISTANT_PROVIDER": "pydantic_ai",
            "SCOUT_SAFETY_ENABLED": "true",
        },
        port=9123,
    )

    assert env["SCOUT_PORT"] == "9123"
    assert env["SCOUT_SAFETY_ENABLED"] == "false"
    assert env["SCOUT_DEBUG_API_ENABLED"] == "1"
    assert env["SCOUT_AI_ASSISTANT_ENABLED"] == "1"
    assert env["SCOUT_AI_ASSISTANT_PROVIDER"] == "mock"
    assert "SCOUT_AI_ASSISTANT_CONFIG_PATH" not in env


def test_plan_only_result_keeps_hardware_and_safety_boundaries_closed() -> None:
    result = build_plan_only_result(port=9111, browser_mode="required")

    assert result.status == "passed"
    assert result.server_started is False
    assert result.boundary.host_side_local_only is True
    assert result.boundary.target_network_calls_performed is False
    assert result.boundary.safety_mutation_performed is False
    assert result.boundary.local_model_start_allowed is False
    assert result.boundary.hardware_provider_control_allowed is False
    assert result.boundary.provider_profile == "mock"
    assert [step.step_id for step in result.steps] == [
        "assistant_status",
        "assistant_ui_static_gate",
        "assistant_readiness_gate",
        "assistant_browser_gate",
    ]


def test_plan_only_skip_browser_omits_browser_step() -> None:
    result = build_plan_only_result(port=9111, browser_mode="skip")

    assert [step.step_id for step in result.steps] == [
        "assistant_status",
        "assistant_ui_static_gate",
        "assistant_readiness_gate",
    ]
    assert result.counts.skipped == 3


def test_cli_plan_only_outputs_json_without_starting_server() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "admin_hardware_prototype_smoke_check.py"),
            "--plan-only",
            "--browser-mode",
            "required",
            "--pretty",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["artifact_kind"] == "admin_hardware_prototype_smoke_result"
    assert payload["server_started"] is False
    assert payload["boundary"]["target_network_calls_performed"] is False
    assert payload["boundary"]["safety_mutation_performed"] is False
    assert payload["boundary"]["local_model_start_allowed"] is False


def test_failed_step_makes_result_failed() -> None:
    failed_step = AdminHardwarePrototypeSmokeStep(
        step_id="assistant_status",
        status="failed",
        summary="assistant status unavailable",
        missing_required_artifacts=["assistant_status_unavailable"],
    )
    result = build_smoke_result(
        base_url="http://127.0.0.1:9111",
        port=9111,
        server_started=True,
        browser_mode="skip",
        steps=[
            failed_step,
            AdminHardwarePrototypeSmokeStep(
                step_id="assistant_ui_static_gate",
                status="skipped",
                summary="not reached",
            ),
        ],
    )

    assert result.status == "failed"
    assert result.counts.failed == 1
    assert result.counts.skipped == 1
    assert result.steps[0].missing_required_artifacts == ["assistant_status_unavailable"]
