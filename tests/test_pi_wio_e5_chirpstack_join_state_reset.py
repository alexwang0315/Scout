from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tools.pi_wio_e5_chirpstack_join_state_reset import (
    APPROVAL_TOKEN,
    build_reset_sql,
    build_summary_sql,
    run_reset,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "pi_wio_e5_chirpstack_join_state_reset.py"


def summary_payload(*, session: bool = True, nonces: int = 1) -> dict[str, object]:
    return {
        "device_name": "scout-wio-e5-client",
        "matched_device_count": 1,
        "matched_device_key_count": 1,
        "devices": [
            {
                "device_name": "scout-wio-e5-client",
                "dev_eui_hash": "md5-redacted",
                "join_eui_hash": "md5-redacted",
                "has_device_session": session,
                "has_dev_addr": session,
                "dev_nonces_type": "object",
                "dev_nonces_key_count": nonces,
                "join_nonce": 9 if nonces else 0,
                "nwk_key_len": 16,
                "app_key_len": 16,
                "nwk_app_keys_equal": True,
                "raw_device_identity_exposed": False,
                "raw_key_exposed": False,
            }
        ],
    }


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, command, **kwargs):
        sql = kwargs["input"]
        self.calls.append(sql)
        if "UPDATE device" in sql:
            payload = {"matched_device_count": 1, "updated_device_count": 1, "updated_device_keys_count": 1}
        elif len(self.calls) >= 3:
            payload = summary_payload(session=False, nonces=0)
        else:
            payload = summary_payload(session=True, nonces=1)
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")


def test_dry_run_plans_reset_without_postgres_write() -> None:
    runner = FakeRunner()

    payload = run_reset(
        device_name="scout-wio-e5-client",
        execute=False,
        approval_token=None,
        postgres_container="postgres",
        database="chirpstack",
        db_user="chirpstack",
        runner=runner,
    )

    assert payload["status"] == "dry_run_join_state_reset_planned"
    assert len(runner.calls) == 1
    assert "UPDATE device" not in runner.calls[0]
    assert payload["postgres_write_performed"] is False
    assert payload["device_registry_changed"] is False
    assert payload["device_session_cleared"] is False
    assert payload["raw_key_exposed"] is False
    assert payload["raw_device_identity_exposed"] is False
    assert payload["rf_tx_allowed"] is False
    assert payload["safety_api_called"] is False


def test_execute_requires_explicit_reset_token() -> None:
    runner = FakeRunner()

    payload = run_reset(
        device_name="scout-wio-e5-client",
        execute=True,
        approval_token="wrong",
        postgres_container="postgres",
        database="chirpstack",
        db_user="chirpstack",
        runner=runner,
    )

    assert payload["status"] == "blocked_join_state_reset"
    assert "operator_approval_token_missing_or_invalid" in payload["blockers"]
    assert len(runner.calls) == 1
    assert payload["postgres_write_performed"] is False
    assert payload["operator_approval_recorded"] is False


def test_execute_with_token_clears_session_and_dev_nonces_only() -> None:
    runner = FakeRunner()

    payload = run_reset(
        device_name="scout-wio-e5-client",
        execute=True,
        approval_token=APPROVAL_TOKEN,
        postgres_container="postgres",
        database="chirpstack",
        db_user="chirpstack",
        runner=runner,
    )

    assert payload["status"] == "join_state_reset_applied"
    assert len(runner.calls) == 3
    assert "device_session = NULL" in runner.calls[1]
    assert "dev_nonces = '{}'" in runner.calls[1]
    assert "nwk_key" not in build_reset_sql("scout-wio-e5-client").split("SET", 1)[1]
    assert payload["postgres_write_performed"] is True
    assert payload["device_registry_changed"] is True
    assert payload["device_identity_changed"] is False
    assert payload["device_keys_changed"] is False
    assert payload["device_session_cleared"] is True
    assert payload["dev_nonces_cleared"] is True
    assert payload["after"]["devices"][0]["has_device_session"] is False


def test_sql_escapes_device_name_and_does_not_select_raw_keys() -> None:
    summary_sql = build_summary_sql("scout'wio")
    reset_sql = build_reset_sql("scout'wio")

    assert "scout''wio" in summary_sql
    assert "scout''wio" in reset_sql
    assert "md5(encode(d.dev_eui" in summary_sql
    assert "md5(encode(d.join_eui" in summary_sql
    assert "encode(dk.nwk_key" not in summary_sql
    assert "encode(dk.app_key" not in summary_sql


def test_cli_dry_run_writes_jsonl(tmp_path: Path) -> None:
    output = tmp_path / "reset.jsonl"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--postgres-container",
            "missing-postgres",
            "--output-jsonl",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert not output.exists()
