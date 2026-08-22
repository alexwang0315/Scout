from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tools.pi_wio_e5_lorawan_rf_trial import (
    APPROVAL_TOKEN,
    build_command_sequence,
    exit_code_for_trial_status,
    join_successful,
    led_bits_for_trial,
    run_trial,
    validate_payload_text,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "pi_wio_e5_lorawan_rf_trial.py"


def write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n", encoding="utf-8")


def ready_plan() -> dict[str, object]:
    return {
        "captured_at": "2026-07-06T05:00:00+00:00",
        "source": "pi_wio_e5_lorawan_uplink_trial_plan",
        "status": "ready_for_manual_uplink_trial",
        "operator_approval_recorded": True,
        "frequency_hz": 923_200_000,
        "region_profile": "AS923_2",
        "rf_tx_executed": False,
        "lorawan_uplink_executed": False,
    }


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


class FakeSession:
    def __init__(self, responses: dict[str, list[str]]) -> None:
        self.responses = responses
        self.commands: list[str] = []

    def transact(self, *, command: str, timeout_seconds: float, quiet_seconds: float) -> list[str]:
        self.commands.append(command)
        return self.responses.get(command, ["+AT: OK"])

    def close(self) -> None:
        return None


def test_cli_without_execute_flag_does_not_transmit_even_with_ready_plan_and_token(tmp_path: Path) -> None:
    plan = tmp_path / "plan.jsonl"
    output = tmp_path / "trial.jsonl"
    write_jsonl(plan, [ready_plan()])

    result = run_cli(
        "--plan-jsonl",
        str(plan),
        "--output-jsonl",
        str(output),
        "--operator-approval-token",
        APPROVAL_TOKEN,
        "--oled-status",
        "--oled-dry-run",
        "--led-status",
        "--led-dry-run",
    )

    assert result.returncode == 2
    trial = json.loads(result.stdout)
    persisted = json.loads(output.read_text(encoding="utf-8").splitlines()[-1])
    assert persisted["status"] == "blocked_rf_trial_preflight"
    assert "execute_rf_tx_flag_missing" in trial["blockers"]
    assert trial["rf_tx_allowed"] is False
    assert trial["rf_tx_executed"] is False
    assert trial["join_executed"] is False
    assert trial["lorawan_uplink_executed"] is False
    assert trial["join_only"] is False
    assert trial["oled_status_updates"][0]["write_status"] == "dry_run"
    assert "BLOCKED" in trial["oled_status_updates"][0]["message"]
    assert trial["led_status_updates"][0]["bits"] == "0x001"


def test_cli_dry_run_simulates_join_and_uplink_without_rf(tmp_path: Path) -> None:
    plan = tmp_path / "plan.jsonl"
    output = tmp_path / "trial.jsonl"
    write_jsonl(plan, [ready_plan()])

    result = run_cli(
        "--plan-jsonl",
        str(plan),
        "--output-jsonl",
        str(output),
        "--operator-approval-token",
        APPROVAL_TOKEN,
        "--execute-rf-tx",
        "--dry-run",
    )

    assert result.returncode == 0, result.stderr
    trial = json.loads(result.stdout)
    assert trial["status"] == "dry_run_no_rf_tx"
    assert trial["rf_tx_allowed"] is False
    assert trial["rf_tx_executed"] is False
    assert trial["lorawan_uplink_executed"] is False
    assert trial["join_only"] is False
    assert [command["command"] for command in trial["planned_commands"]] == ["AT", "AT+JOIN", 'AT+MSG="SCOUT"']
    assert len(trial["command_results"]) == 3


def test_cli_join_only_dry_run_plans_join_without_uplink(tmp_path: Path) -> None:
    plan = tmp_path / "plan.jsonl"
    output = tmp_path / "trial.jsonl"
    write_jsonl(plan, [ready_plan()])

    result = run_cli(
        "--plan-jsonl",
        str(plan),
        "--output-jsonl",
        str(output),
        "--operator-approval-token",
        APPROVAL_TOKEN,
        "--execute-rf-tx",
        "--join-only",
        "--dry-run",
        "--oled-status",
        "--oled-dry-run",
        "--led-status",
        "--led-dry-run",
    )

    assert result.returncode == 0, result.stderr
    trial = json.loads(result.stdout)
    assert trial["status"] == "dry_run_no_rf_tx"
    assert trial["join_only"] is True
    assert trial["rf_tx_executed"] is False
    assert trial["join_executed"] is False
    assert trial["lorawan_uplink_executed"] is False
    assert [command["command"] for command in trial["planned_commands"]] == ["AT", "AT+JOIN"]
    assert all(command["uplink_command"] is False for command in trial["planned_commands"])
    assert len(trial["command_results"]) == 2
    assert "DRY RUN" in trial["oled_status_updates"][0]["message"]


def test_run_trial_executes_rf_only_after_ready_plan_token_and_execute_flag(tmp_path: Path) -> None:
    plan = tmp_path / "plan.jsonl"
    write_jsonl(plan, [ready_plan()])
    fake = FakeSession(
        {
            "AT": ["+AT: OK"],
            "AT+JOIN": ["+JOIN: Start", "+JOIN: Network joined", "+JOIN: Done"],
            'AT+MSG="SCOUT"': ["+MSG: Start", "+MSG: Done"],
        }
    )

    trial = run_trial(
        plan_jsonl=plan,
        port="/dev/ttyUSB0",
        baud=9600,
        region_profile="AS923_2",
        frequency_hz=923_200_000,
        payload_text="SCOUT",
        skip_join=False,
        join_only=False,
        execute_rf_tx=True,
        dry_run=False,
        operator_approval_token=APPROVAL_TOKEN,
        command_timeout_seconds=1.0,
        command_quiet_seconds=0.1,
        join_timeout_seconds=1.0,
        join_quiet_seconds=0.1,
        continue_after_join_failure=False,
        session_factory=lambda: fake,
    )

    assert trial["status"] == "rf_trial_uplink_command_sent"
    assert trial["join_only"] is False
    assert fake.commands == ["AT", "AT+JOIN", 'AT+MSG="SCOUT"']
    assert trial["rf_tx_allowed"] is True
    assert trial["rf_tx_executed"] is True
    assert trial["join_allowed"] is True
    assert trial["join_executed"] is True
    assert trial["lorawan_uplink_allowed"] is True
    assert trial["lorawan_uplink_executed"] is True
    assert trial["phase1_safety_decision_change_allowed"] is False
    assert trial["safety_api_called"] is False


def test_join_only_success_never_sends_uplink(tmp_path: Path) -> None:
    plan = tmp_path / "plan.jsonl"
    write_jsonl(plan, [ready_plan()])
    fake = FakeSession(
        {
            "AT": ["+AT: OK"],
            "AT+JOIN": ["+JOIN: Start", "+JOIN: Network joined", "+JOIN: Done"],
            'AT+MSG="SCOUT"': ["+MSG: Start", "+MSG: Done"],
        }
    )

    trial = run_trial(
        plan_jsonl=plan,
        port="/dev/ttyUSB0",
        baud=9600,
        region_profile="AS923_2",
        frequency_hz=923_200_000,
        payload_text="SCOUT",
        skip_join=False,
        join_only=True,
        execute_rf_tx=True,
        dry_run=False,
        operator_approval_token=APPROVAL_TOKEN,
        command_timeout_seconds=1.0,
        command_quiet_seconds=0.1,
        join_timeout_seconds=1.0,
        join_quiet_seconds=0.1,
        continue_after_join_failure=False,
        session_factory=lambda: fake,
    )

    assert trial["status"] == "rf_trial_join_confirmed_no_uplink"
    assert trial["join_only"] is True
    assert fake.commands == ["AT", "AT+JOIN"]
    assert [command["command"] for command in trial["planned_commands"]] == ["AT", "AT+JOIN"]
    assert trial["rf_tx_allowed"] is True
    assert trial["rf_tx_executed"] is True
    assert trial["join_executed"] is True
    assert trial["lorawan_uplink_allowed"] is True
    assert trial["lorawan_uplink_executed"] is False
    assert trial["phase1_safety_decision_change_allowed"] is False
    assert trial["safety_api_called"] is False
    assert exit_code_for_trial_status(trial["status"]) == 0


def test_join_failure_stops_before_uplink_by_default(tmp_path: Path) -> None:
    plan = tmp_path / "plan.jsonl"
    write_jsonl(plan, [ready_plan()])
    fake = FakeSession(
        {
            "AT": ["+AT: OK"],
            "AT+JOIN": ["+JOIN: Start", "+JOIN: NORMAL", "+JOIN: Join failed", "+JOIN: Done"],
            'AT+MSG="SCOUT"': ["+MSG: Start", "+MSG: Done"],
        }
    )

    trial = run_trial(
        plan_jsonl=plan,
        port="/dev/ttyUSB0",
        baud=9600,
        region_profile="AS923_2",
        frequency_hz=923_200_000,
        payload_text="SCOUT",
        skip_join=False,
        join_only=False,
        execute_rf_tx=True,
        dry_run=False,
        operator_approval_token=APPROVAL_TOKEN,
        command_timeout_seconds=1.0,
        command_quiet_seconds=0.1,
        join_timeout_seconds=1.0,
        join_quiet_seconds=0.1,
        continue_after_join_failure=False,
        session_factory=lambda: fake,
    )

    assert trial["status"] == "rf_trial_join_not_confirmed"
    assert fake.commands == ["AT", "AT+JOIN"]
    assert trial["command_results"][-1]["response_status"] == "error"
    assert trial["rf_tx_executed"] is True
    assert trial["join_executed"] is True
    assert trial["lorawan_uplink_executed"] is False


def test_blocked_when_plan_is_not_ready_or_frequency_mismatches(tmp_path: Path) -> None:
    plan = tmp_path / "plan.jsonl"
    output = tmp_path / "trial.jsonl"
    not_ready = {**ready_plan(), "status": "waiting_for_operator_approval", "operator_approval_recorded": False}
    write_jsonl(plan, [not_ready])

    result = run_cli(
        "--plan-jsonl",
        str(plan),
        "--output-jsonl",
        str(output),
        "--operator-approval-token",
        APPROVAL_TOKEN,
        "--execute-rf-tx",
    )

    assert result.returncode == 2
    trial = json.loads(result.stdout)
    assert "plan_not_ready:waiting_for_operator_approval" in trial["blockers"]
    assert "plan_operator_approval_not_recorded" in trial["blockers"]
    assert trial["rf_tx_executed"] is False


def test_join_only_cannot_be_combined_with_skip_join(tmp_path: Path) -> None:
    plan = tmp_path / "plan.jsonl"
    output = tmp_path / "trial.jsonl"
    write_jsonl(plan, [ready_plan()])

    result = run_cli(
        "--plan-jsonl",
        str(plan),
        "--output-jsonl",
        str(output),
        "--operator-approval-token",
        APPROVAL_TOKEN,
        "--execute-rf-tx",
        "--join-only",
        "--skip-join",
    )

    assert result.returncode == 2
    assert "--join-only cannot be combined with --skip-join" in result.stderr
    assert not output.exists()


def test_helpers_validate_payload_and_led_mapping() -> None:
    assert validate_payload_text("SCOUT") == "SCOUT"
    commands = build_command_sequence(
        payload_text="SCOUT",
        skip_join=True,
        join_only=False,
        command_timeout_seconds=1.0,
        command_quiet_seconds=0.1,
        join_timeout_seconds=2.0,
        join_quiet_seconds=0.2,
    )
    assert [command.command for command in commands] == ["AT", 'AT+MSG="SCOUT"']
    assert join_successful(None) is False
    dry_trial = {"status": "dry_run_no_rf_tx"}
    sent_trial = {"status": "rf_trial_uplink_command_sent"}
    fail_trial = {"status": "rf_trial_join_not_confirmed"}
    assert led_bits_for_trial(dry_trial, blocked_bit=1, dry_run_bit=2, tx_attempt_bit=9, fail_bit=10) == 0x002
    assert led_bits_for_trial(sent_trial, blocked_bit=1, dry_run_bit=2, tx_attempt_bit=9, fail_bit=10) == 0x100
    assert led_bits_for_trial(fail_trial, blocked_bit=1, dry_run_bit=2, tx_attempt_bit=9, fail_bit=10) == 0x200
    assert exit_code_for_trial_status("blocked_rf_trial_preflight") == 2
    assert exit_code_for_trial_status("rf_trial_uplink_command_sent") == 0
    assert exit_code_for_trial_status("rf_trial_join_confirmed_no_uplink") == 0
    assert exit_code_for_trial_status("rf_trial_join_not_confirmed") == 1
