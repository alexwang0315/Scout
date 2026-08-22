from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SOURCE = "pi_wio_e5_chirpstack_join_state_reset"
HARDWARE_KIND = "wio_e5_chirpstack_join_state_reset"
APPROVAL_TOKEN = "I_ACCEPT_CHIRPSTACK_JOIN_STATE_RESET_AS923_2"
DEFAULT_OUTPUT_JSONL = Path("/data/scout/providers/lora/wio-e5-chirpstack-join-state-reset.jsonl")
DEFAULT_POSTGRES_CONTAINER = "chirpstack-docker-postgres-1"
DEFAULT_DATABASE = "chirpstack"
DEFAULT_DB_USER = "chirpstack"
DEFAULT_DEVICE_NAME = "scout-wio-e5-client"


@dataclass(frozen=True)
class DbCommandResult:
    returncode: int
    stdout: str
    stderr: str


def boundary_fields(*, approved: bool, executed: bool) -> dict[str, Any]:
    return {
        "read_only": not executed,
        "operator_approval_required": True,
        "operator_approval_recorded": approved,
        "operator_approval_token_stored": False,
        "postgres_write_allowed": approved,
        "postgres_write_performed": executed,
        "chirpstack_config_changed": executed,
        "device_registry_changed": executed,
        "device_identity_changed": False,
        "device_keys_changed": False,
        "device_session_cleared": executed,
        "dev_nonces_cleared": executed,
        "join_nonce_reset": executed,
        "rf_tx_allowed": False,
        "rf_tx_executed": False,
        "join_executed": False,
        "lorawan_uplink_allowed": False,
        "lorawan_uplink_executed": False,
        "downlink_allowed": False,
        "mqtt_publish_performed": False,
        "outbound_send_performed": False,
        "remote_outbound_allowed": False,
        "raw_device_identity_exposed": False,
        "raw_key_exposed": False,
        "phase1_safety_decision_change_allowed": False,
        "phase1_l0_l4_state_mutated": False,
        "safety_api_called": False,
        "hardware_control_scope": "operator_approved_chirpstack_join_state_reset_only",
    }


def build_summary_sql(device_name: str) -> str:
    escaped = device_name.replace("'", "''")
    return f"""
WITH selected AS (
  SELECT d.dev_eui
  FROM device d
  WHERE d.name = '{escaped}'
),
joined AS (
  SELECT
    d.name AS device_name,
    md5(encode(d.dev_eui, 'hex')) AS dev_eui_hash,
    md5(encode(d.join_eui, 'hex')) AS join_eui_hash,
    d.is_disabled,
    d.f_cnt_up,
    d.last_seen_at IS NOT NULL AS has_last_seen,
    d.dev_addr IS NOT NULL AS has_dev_addr,
    d.device_session IS NOT NULL AS has_device_session,
    dp.name AS profile_name,
    dp.region,
    dp.region_config_id,
    dp.mac_version,
    dp.reg_params_revision,
    dp.supports_otaa,
    dk.dev_eui IS NOT NULL AS has_device_keys,
    length(dk.nwk_key) AS nwk_key_len,
    length(dk.app_key) AS app_key_len,
    (dk.nwk_key = dk.app_key) AS nwk_app_keys_equal,
    jsonb_typeof(dk.dev_nonces) AS dev_nonces_type,
    CASE WHEN jsonb_typeof(dk.dev_nonces) = 'array' THEN jsonb_array_length(dk.dev_nonces) ELSE NULL END AS dev_nonces_count,
    CASE WHEN jsonb_typeof(dk.dev_nonces) = 'object' THEN (SELECT count(*) FROM jsonb_object_keys(dk.dev_nonces)) ELSE NULL END AS dev_nonces_key_count,
    dk.join_nonce
  FROM device d
  LEFT JOIN device_profile dp ON dp.id = d.device_profile_id
  LEFT JOIN device_keys dk ON dk.dev_eui = d.dev_eui
  WHERE d.dev_eui IN (SELECT dev_eui FROM selected)
)
SELECT jsonb_build_object(
  'device_name', '{escaped}',
  'matched_device_count', (SELECT count(*) FROM selected),
  'matched_device_key_count', (SELECT count(*) FROM device_keys WHERE dev_eui IN (SELECT dev_eui FROM selected)),
  'devices', COALESCE((SELECT jsonb_agg(to_jsonb(joined) ORDER BY device_name) FROM joined), '[]'::jsonb)
)::text;
"""


def build_reset_sql(device_name: str) -> str:
    escaped = device_name.replace("'", "''")
    return f"""
WITH selected AS (
  SELECT dev_eui
  FROM device
  WHERE name = '{escaped}'
),
updated_device AS (
  UPDATE device
  SET
    device_session = NULL,
    dev_addr = NULL,
    secondary_dev_addr = NULL,
    f_cnt_up = 0,
    updated_at = now()
  WHERE dev_eui IN (SELECT dev_eui FROM selected)
  RETURNING dev_eui
),
updated_keys AS (
  UPDATE device_keys
  SET
    dev_nonces = '{{}}'::jsonb,
    join_nonce = 0,
    updated_at = now()
  WHERE dev_eui IN (SELECT dev_eui FROM selected)
  RETURNING dev_eui
)
SELECT jsonb_build_object(
  'device_name', '{escaped}',
  'matched_device_count', (SELECT count(*) FROM selected),
  'updated_device_count', (SELECT count(*) FROM updated_device),
  'updated_device_keys_count', (SELECT count(*) FROM updated_keys)
)::text;
"""


def run_psql(
    *,
    sql: str,
    postgres_container: str,
    database: str,
    db_user: str,
    runner=subprocess.run,
) -> DbCommandResult:
    result = runner(
        ["docker", "exec", "-i", postgres_container, "psql", "-U", db_user, "-d", database, "-At"],
        input=sql,
        text=True,
        capture_output=True,
        check=False,
    )
    return DbCommandResult(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)


def parse_psql_json(result: DbCommandResult) -> dict[str, Any]:
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"psql returned {result.returncode}")
    stripped = result.stdout.strip()
    if not stripped:
        raise RuntimeError("psql returned no JSON")
    return json.loads(stripped)


def run_reset(
    *,
    device_name: str,
    execute: bool,
    approval_token: str | None,
    postgres_container: str,
    database: str,
    db_user: str,
    runner=subprocess.run,
) -> dict[str, Any]:
    approved = execute and approval_token == APPROVAL_TOKEN
    before = parse_psql_json(
        run_psql(
            sql=build_summary_sql(device_name),
            postgres_container=postgres_container,
            database=database,
            db_user=db_user,
            runner=runner,
        )
    )
    blockers: list[str] = []
    if before.get("matched_device_count") != 1:
        blockers.append("expected_exactly_one_matching_device")
    if before.get("matched_device_key_count") != 1:
        blockers.append("expected_exactly_one_matching_device_key")
    if execute and approval_token != APPROVAL_TOKEN:
        blockers.append("operator_approval_token_missing_or_invalid")
    reset_result: dict[str, Any] | None = None
    executed = False
    if execute and not blockers:
        reset_result = parse_psql_json(
            run_psql(
                sql=build_reset_sql(device_name),
                postgres_container=postgres_container,
                database=database,
                db_user=db_user,
                runner=runner,
            )
        )
        executed = reset_result.get("updated_device_count") == 1 and reset_result.get("updated_device_keys_count") == 1
    after = None
    if executed:
        after = parse_psql_json(
            run_psql(
                sql=build_summary_sql(device_name),
                postgres_container=postgres_container,
                database=database,
                db_user=db_user,
                runner=runner,
            )
        )
    if blockers:
        status = "blocked_join_state_reset"
    elif executed:
        status = "join_state_reset_applied"
    elif execute:
        status = "join_state_reset_not_applied"
    else:
        status = "dry_run_join_state_reset_planned"
    payload = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": SOURCE,
        "hardware_kind": HARDWARE_KIND,
        "status": status,
        "blockers": blockers,
        "device_name": device_name,
        "postgres_container": postgres_container,
        "database": database,
        "db_user": db_user,
        "before": before,
        "reset_result": reset_result,
        "after": after,
    }
    payload.update(boundary_fields(approved=approved and not blockers, executed=executed))
    return payload


def append_jsonl(payload: dict[str, Any], output_path: Path | None) -> None:
    if output_path is None:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reset ChirpStack join/session state for the Scout Wio-E5 client.")
    parser.add_argument("--device-name", default=DEFAULT_DEVICE_NAME)
    parser.add_argument("--postgres-container", default=DEFAULT_POSTGRES_CONTAINER)
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--db-user", default=DEFAULT_DB_USER)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--operator-approval-token")
    parser.add_argument("--output-jsonl", type=Path, default=DEFAULT_OUTPUT_JSONL)
    args = parser.parse_args(argv)

    payload = run_reset(
        device_name=args.device_name,
        execute=args.execute,
        approval_token=args.operator_approval_token,
        postgres_container=args.postgres_container,
        database=args.database,
        db_user=args.db_user,
    )
    append_jsonl(payload, args.output_jsonl)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    if payload["status"].startswith("blocked") or payload["status"] == "join_state_reset_not_applied":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
