from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scout_lorawan_client_observer import (
    LorawanClientObserver,
    LorawanClientObserverConfig,
    boundary_fields,
    client_oled_message,
    led_bits_for_sample,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scout_lorawan_client_observer.py"


def write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n", encoding="utf-8")


def test_observer_reports_stale_join_state_with_visual_dry_run(tmp_path: Path) -> None:
    plan_jsonl = tmp_path / "trial-plan.jsonl"
    rf_jsonl = tmp_path / "rf-trial.jsonl"
    audit_jsonl = tmp_path / "join-audit.jsonl"
    join_state_jsonl = tmp_path / "join-state.jsonl"
    tail_jsonl = tmp_path / "tail-status.jsonl"
    write_jsonl(
        plan_jsonl,
        [
            {
                "captured_at": "2026-07-06T06:20:00+00:00",
                "source": "pi_wio_e5_lorawan_uplink_trial_plan",
                "status": "ready_for_manual_uplink_trial",
                "operator_approval_recorded": True,
            }
        ],
    )
    write_jsonl(
        rf_jsonl,
        [
            {
                "captured_at": "2026-07-06T06:33:00+00:00",
                "source": "pi_wio_e5_lorawan_rf_trial",
                "status": "rf_trial_join_not_confirmed",
                "rf_tx_executed": True,
                "join_executed": True,
                "lorawan_uplink_executed": False,
                "command_results": [
                    {"label": "serial_preflight", "response_status": "ok", "response_lines": ["+AT: OK"]},
                    {
                        "label": "lorawan_join",
                        "response_status": "error",
                        "response_lines": ["+JOIN: Join failed"],
                    },
                ],
            }
        ],
    )
    write_jsonl(audit_jsonl, [{"decision": "client_join_failed_network_server_rejected"}])
    write_jsonl(
        join_state_jsonl,
        [
            {
                "captured_at": "2026-07-06T06:56:00+00:00",
                "status": "stale_join_state_suspected",
                "diagnostic_flags": ["server_has_session_but_latest_join_failed"],
                "chirpstack_state": {"device_count": 1, "devices": [{"has_device_session": True}]},
                "raw_device_identity_exposed": False,
                "raw_key_exposed": False,
            }
        ],
    )
    write_jsonl(tail_jsonl, [{"status": "no_uplink_observed", "observed_uplink_count": 0}])

    observer = LorawanClientObserver(
        LorawanClientObserverConfig(
            evidence_dir=tmp_path / "observer",
            trial_plan_jsonl=plan_jsonl,
            rf_trial_jsonl=rf_jsonl,
            join_audit_jsonl=audit_jsonl,
            join_state_diagnostic_jsonl=join_state_jsonl,
            tail_status_jsonl=tail_jsonl,
            uplink_jsonl=tmp_path / "missing-uplink.jsonl",
            oled_status=True,
            oled_dry_run=True,
            led_status=True,
            led_dry_run=True,
        )
    )

    status = observer.refresh()
    sample = json.loads(observer.evidence_jsonl_path.read_text(encoding="utf-8").splitlines()[-1])
    persisted = json.loads(observer.status_path.read_text(encoding="utf-8"))

    assert status["artifact_kind"] == "scout_lorawan_client_observer_status"
    assert status["decision"] == "stale_join_state_suspected"
    assert status["answerability"] == "chirpstack_join_state_repair_required_before_retry"
    assert status["client_health"]["trial_plan_status"] == "ready_for_manual_uplink_trial"
    assert status["client_health"]["rf_trial_status"] == "rf_trial_join_not_confirmed"
    assert status["client_health"]["join_state_status"] == "stale_join_state_suspected"
    assert status["client_health"]["tail_observed_uplink_count"] == 0
    assert status["sources"]["join_state_diagnostic"]["latest"]["raw_key_exposed"] is False
    assert status["boundary"] == boundary_fields()
    assert status["boundary"]["rf_tx_allowed"] is False
    assert status["boundary"]["lorawan_uplink_allowed"] is False
    assert status["boundary"]["safety_api_called"] is False
    assert sample["decision"] == status["decision"]
    assert persisted["decision"] == status["decision"]
    assert status["oled_status_updates"][0]["write_status"] == "dry_run"
    assert "JOIN STALE" in status["oled_status_updates"][0]["message"]
    assert status["led_status_updates"][0]["write_status"] == "dry_run"
    assert status["led_status_updates"][0]["bits"] == "0x200"


def test_observer_prioritizes_uplink_over_failed_join_state(tmp_path: Path) -> None:
    uplink_jsonl = tmp_path / "uplink.jsonl"
    rf_jsonl = tmp_path / "rf-trial.jsonl"
    join_state_jsonl = tmp_path / "join-state.jsonl"
    write_jsonl(uplink_jsonl, [{"captured_at": "2026-07-06T06:58:00+00:00", "status": "uplink_observed"}])
    write_jsonl(rf_jsonl, [{"status": "rf_trial_join_not_confirmed"}])
    write_jsonl(join_state_jsonl, [{"status": "stale_join_state_suspected"}])
    observer = LorawanClientObserver(
        LorawanClientObserverConfig(
            evidence_dir=tmp_path / "observer",
            uplink_jsonl=uplink_jsonl,
            rf_trial_jsonl=rf_jsonl,
            join_state_diagnostic_jsonl=join_state_jsonl,
        )
    )

    status = observer.refresh()

    assert status["decision"] == "uplink_observed"
    assert status["answerability"] == "client_uplink_evidence_available"
    assert status["client_health"]["uplink_record_count"] == 1


def test_observer_reports_join_confirmed_waiting_for_uplink(tmp_path: Path) -> None:
    plan_jsonl = tmp_path / "trial-plan.jsonl"
    rf_jsonl = tmp_path / "rf-trial.jsonl"
    write_jsonl(plan_jsonl, [{"status": "ready_for_manual_uplink_trial"}])
    write_jsonl(
        rf_jsonl,
        [
            {
                "status": "rf_trial_join_confirmed_no_uplink",
                "join_only": True,
                "rf_tx_executed": True,
                "join_executed": True,
                "lorawan_uplink_executed": False,
            }
        ],
    )
    observer = LorawanClientObserver(
        LorawanClientObserverConfig(evidence_dir=tmp_path / "observer", trial_plan_jsonl=plan_jsonl, rf_trial_jsonl=rf_jsonl)
    )

    status = observer.refresh()

    assert status["decision"] == "join_confirmed_waiting_for_uplink"
    assert status["client_health"]["rf_trial_join_only"] is True
    assert status["boundary"]["lorawan_uplink_executed"] is False


def test_oled_and_led_helpers_keep_client_status_short_and_bounded() -> None:
    sample = {"decision": "join_confirmed_waiting_for_uplink", "sources": {"rf_trial": {"latest": {"status": "rf_trial_join_confirmed_no_uplink"}}}}

    message = client_oled_message(sample)

    assert "SCOUT LORA CL" in message
    assert "JOIN OK" in message
    assert all(len(line) <= 16 for line in message.splitlines())
    assert led_bits_for_sample(sample, ok_bit=9, warn_bit=1, fail_bit=10) == 0x100

    stale = {**sample, "decision": "stale_join_state_suspected"}
    assert "JOIN STALE" in client_oled_message(stale)
    assert led_bits_for_sample(stale, ok_bit=9, warn_bit=1, fail_bit=10) == 0x200

    incomplete = {**sample, "decision": "client_evidence_incomplete"}
    assert led_bits_for_sample(incomplete, ok_bit=9, warn_bit=1, fail_bit=10) == 0x001


def test_cli_once_writes_status_without_hardware(tmp_path: Path) -> None:
    rf_jsonl = tmp_path / "rf-trial.jsonl"
    write_jsonl(rf_jsonl, [{"status": "rf_trial_join_confirmed_no_uplink", "join_only": True}])

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--once",
            "--evidence-dir",
            str(tmp_path / "observer"),
            "--rf-trial-jsonl",
            str(rf_jsonl),
            "--oled-status",
            "--oled-dry-run",
            "--led-status",
            "--led-dry-run",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    status = json.loads(result.stdout)
    assert status["artifact_kind"] == "scout_lorawan_client_observer_status"
    assert status["decision"] == "join_confirmed_waiting_for_uplink"
    assert status["boundary"]["rf_tx_allowed"] is False
    assert status["oled_status_updates"][0]["write_status"] == "dry_run"
    assert status["led_status_updates"][0]["write_status"] == "dry_run"
