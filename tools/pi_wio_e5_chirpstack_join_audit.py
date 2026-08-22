from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from tools.pi_grove_led_bar_smoke import DEFAULT_PORT as DEFAULT_LED_PORT
    from tools.pi_grove_led_bar_smoke import PORT_DEFAULTS, clear_led_bar, make_gpio_writer, write_led_bar_bits
    from tools.pi_oled_i2c_smoke import parse_address, write_display
    from tools.pi_wio_e5_lorawan_uplink_trial_plan import normalize_eui
except ImportError:  # pragma: no cover - used when executed directly from tools/ on a Pi.
    from pi_grove_led_bar_smoke import DEFAULT_PORT as DEFAULT_LED_PORT
    from pi_grove_led_bar_smoke import PORT_DEFAULTS, clear_led_bar, make_gpio_writer, write_led_bar_bits
    from pi_oled_i2c_smoke import parse_address, write_display
    from pi_wio_e5_lorawan_uplink_trial_plan import normalize_eui


SOURCE = "pi_wio_e5_chirpstack_join_audit"
HARDWARE_KIND = "wio_e5_chirpstack_join_provisioning_audit"
DEFAULT_WIO_AT_JSONL = Path("/data/scout/providers/wio_e5/wio-e5-at-smoke.jsonl")
DEFAULT_RF_TRIAL_JSONL = Path("/data/scout/providers/lora/wio-e5-rf-trial.jsonl")
DEFAULT_UPLINK_JSONL = Path("/data/scout/providers/lora/sx1303-gateway-uplink.jsonl")
DEFAULT_TAIL_STATUS_JSONL = Path("/data/scout/providers/lora/sx1303-gateway-uplink-tail-status.jsonl")
DEFAULT_OUTPUT_JSONL = Path("/data/scout/providers/lora/wio-e5-chirpstack-join-audit.jsonl")
DEFAULT_CHIRPSTACK_CONTAINER = "chirpstack-docker-chirpstack-1"
DEFAULT_GATEWAY_BRIDGE_CONTAINER = "chirpstack-docker-chirpstack-gateway-bridge-1"
DEFAULT_POSTGRES_CONTAINER = "chirpstack-docker-postgres-1"
DEFAULT_LED_NO_JOIN_HINT_BIT = 1
DEFAULT_LED_JOIN_SEEN_BIT = 8
DEFAULT_LED_UPLINK_BIT = 9
DEFAULT_LED_REJECTED_BIT = 10


def boundary_fields() -> dict[str, Any]:
    return {
        "read_only": True,
        "rf_tx_allowed": False,
        "rf_tx_executed": False,
        "join_allowed": False,
        "join_executed": False,
        "downlink_allowed": False,
        "lorawan_uplink_allowed": False,
        "lorawan_uplink_executed": False,
        "chirpstack_config_changed": False,
        "device_registry_changed": False,
        "postgres_write_performed": False,
        "mqtt_publish_performed": False,
        "phase1_safety_decision_change_allowed": False,
        "phase1_l0_l4_state_mutated": False,
        "safety_api_called": False,
        "remote_outbound_allowed": False,
        "outbound_send_performed": False,
        "hardware_control_scope": "read_only_lorawan_join_provisioning_audit",
    }


def parse_positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
    return parsed


def parse_non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return parsed


def parse_led_bit(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 10:
        raise argparse.ArgumentTypeError("LED bit must be between 1 and 10")
    return parsed


def hash_identifier(value: str, *, salt: str) -> str:
    digest = hashlib.sha256(f"{salt}:{value}".encode("utf-8")).hexdigest()
    return f"sha256:{digest[:16]}"


def read_jsonl(path: Path, *, max_records: int = 500) -> tuple[list[dict[str, Any]], int, bool]:
    if not path.exists():
        return [], 0, False
    records: list[dict[str, Any]] = []
    invalid_count = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-max_records:]:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            invalid_count += 1
            continue
        if isinstance(payload, dict):
            records.append(payload)
        else:
            invalid_count += 1
    return records, invalid_count, True


def extract_wio_identity(records: list[dict[str, Any]], *, hash_salt: str) -> dict[str, Any]:
    identity: dict[str, str] = {}
    for record in records:
        for line in record.get("response_lines", []):
            if not isinstance(line, str):
                continue
            match = re.match(r"^\+ID:\s*([^,]+),\s*(.+)$", line, flags=re.IGNORECASE)
            if not match:
                continue
            key = match.group(1).strip().lower()
            value = normalize_eui(match.group(2)) if key in {"deveui", "appeui"} else match.group(2).strip()
            if value:
                identity[key] = value
    dev_eui = identity.get("deveui")
    app_eui = identity.get("appeui")
    return {
        "dev_eui_present": bool(dev_eui),
        "dev_eui_hash": hash_identifier(dev_eui, salt=hash_salt) if dev_eui else None,
        "app_eui_present": bool(app_eui),
        "app_eui_hash": hash_identifier(app_eui, salt=hash_salt) if app_eui else None,
        "dev_addr_present": "devaddr" in identity,
        "raw_identity_embedded": False,
    }


def latest_real_rf_trial(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    for record in reversed(records):
        if record.get("source") == "pi_wio_e5_lorawan_rf_trial" and record.get("dry_run") is not True:
            return record
    return None


def summarize_rf_trial(records: list[dict[str, Any]], *, invalid_count: int, file_exists: bool) -> dict[str, Any]:
    latest = latest_real_rf_trial(records)
    command_results = latest.get("command_results", []) if latest else []
    lines = [
        line
        for result in command_results
        for line in result.get("response_lines", [])
        if isinstance(line, str)
    ]
    upper_text = "\n".join(lines).upper()
    return {
        "path": str(DEFAULT_RF_TRIAL_JSONL),
        "file_exists": file_exists,
        "record_count_scanned": len(records),
        "invalid_json_line_count": invalid_count,
        "latest_real_trial_at": latest.get("captured_at") if latest else None,
        "latest_real_trial_status": latest.get("status") if latest else None,
        "latest_real_trial_found": latest is not None,
        "join_failed_response_seen": "JOIN FAILED" in upper_text,
        "network_joined_response_seen": "NETWORK JOINED" in upper_text,
        "please_join_network_first_seen": "PLEASE JOIN NETWORK FIRST" in upper_text,
        "rf_tx_executed": bool(latest and latest.get("rf_tx_executed") is True),
        "join_executed": bool(latest and latest.get("join_executed") is True),
        "lorawan_uplink_executed": bool(latest and latest.get("lorawan_uplink_executed") is True),
        "raw_response_lines_embedded": False,
    }


def summarize_uplink(records: list[dict[str, Any]], *, invalid_count: int, file_exists: bool) -> dict[str, Any]:
    uplink_count = sum(1 for record in records if record.get("status") == "uplink_observed")
    return {
        "path": str(DEFAULT_UPLINK_JSONL),
        "file_exists": file_exists,
        "record_count_scanned": len(records),
        "invalid_json_line_count": invalid_count,
        "uplink_like_record_count": uplink_count,
        "latest_record_at": records[-1].get("captured_at") if records else None,
    }


def summarize_tail_status(records: list[dict[str, Any]], *, invalid_count: int, file_exists: bool) -> dict[str, Any]:
    latest = records[-1] if records else {}
    return {
        "path": str(DEFAULT_TAIL_STATUS_JSONL),
        "file_exists": file_exists,
        "record_count_scanned": len(records),
        "invalid_json_line_count": invalid_count,
        "latest_status": latest.get("status"),
        "latest_observed_uplink_count": latest.get("observed_uplink_count"),
        "latest_uplink_jsonl_written": latest.get("uplink_jsonl_written"),
        "latest_record_at": latest.get("captured_at"),
    }


def strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def compact_eui(value: str | None) -> str | None:
    if not value:
        return None
    normalized = normalize_eui(value)
    return normalized.replace(":", "") if normalized else None


def summarize_log_text(text: str, *, dev_eui: str | None, source: str) -> dict[str, Any]:
    clean = strip_ansi(text)
    lower = clean.lower()
    compact = compact_eui(dev_eui)
    colon = normalize_eui(dev_eui)
    dev_eui_seen = False
    if compact:
        dev_eui_seen = compact.lower() in re.sub(r"[^0-9a-fA-F]", "", clean).lower()
    if colon and colon.lower() in lower:
        dev_eui_seen = True
    join_request_patterns = (
        r"join[-_ ]?request",
        r"join request",
        r"mtype[^a-z0-9]+join",
        r"join.*dev.?eui",
    )
    join_accept_patterns = (r"join[-_ ]?accept", r"network joined")
    reject_patterns = (
        r"join failed",
        r"device.*not.*found",
        r"unknown.*device",
        r"not found",
        r"mic",
        r"appkey",
        r"invalid",
    )
    return {
        "source": source,
        "line_count_scanned": len(clean.splitlines()),
        "join_request_hint_count": sum(len(re.findall(pattern, lower)) for pattern in join_request_patterns),
        "join_accept_hint_count": sum(len(re.findall(pattern, lower)) for pattern in join_accept_patterns),
        "join_reject_hint_count": sum(len(re.findall(pattern, lower)) for pattern in reject_patterns),
        "uplink_event_hint_count": lower.count("event/up") + lower.count("uplink"),
        "as923_2_hint_count": lower.count("as923_2"),
        "dev_eui_seen_in_logs": dev_eui_seen,
        "raw_log_lines_embedded": False,
    }


def parse_docker_ps(text: str) -> dict[str, Any]:
    containers = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        name = parts[0] if parts else line.strip()
        status = parts[1] if len(parts) > 1 else ""
        containers.append({"name": name, "status": status, "running": "up" in status.lower()})
    names = {container["name"]: container for container in containers}
    return {
        "container_count": len(containers),
        "chirpstack_running": bool(names.get(DEFAULT_CHIRPSTACK_CONTAINER, {}).get("running")),
        "gateway_bridge_running": bool(names.get(DEFAULT_GATEWAY_BRIDGE_CONTAINER, {}).get("running")),
        "postgres_running": bool(names.get(DEFAULT_POSTGRES_CONTAINER, {}).get("running")),
        "containers": containers,
    }


def run_command(command: list[str], *, timeout_seconds: float) -> tuple[str, str | None, int]:
    try:
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except Exception as exc:
        return "", f"{type(exc).__name__}: {exc}", -1
    text = "\n".join(part for part in (result.stdout, result.stderr) if part)
    return text, None, result.returncode


def docker_ps_text(fixture: str | None, *, timeout_seconds: float) -> tuple[str, str | None, int]:
    if fixture is not None:
        return fixture, None, 0
    return run_command(["docker", "ps", "--format", "{{.Names}}\t{{.Status}}\t{{.Ports}}"], timeout_seconds=timeout_seconds)


def docker_logs_text(container: str, fixture: str | None, *, since: str, tail: int, timeout_seconds: float) -> tuple[str, str | None, int]:
    if fixture is not None:
        return fixture, None, 0
    return run_command(["docker", "logs", "--since", since, "--tail", str(tail), container], timeout_seconds=timeout_seconds)


def parse_postgres_device_output(text: str, *, dev_eui: str | None, hash_salt: str) -> dict[str, Any]:
    compact_target = compact_eui(dev_eui)
    devices = [normalize_eui(match.group(0)) for match in re.finditer(r"\b[0-9a-fA-F]{16}\b", text)]
    devices = [device for device in devices if device]
    hashes = [hash_identifier(device, salt=hash_salt) for device in devices]
    match_found = bool(compact_target and compact_target.lower() in {device.replace(":", "") for device in devices})
    return {
        "query_attempted": True,
        "device_count_seen": len(devices),
        "device_registry_match": match_found,
        "device_eui_hashes": hashes[:20],
        "raw_device_eui_embedded": False,
    }


def postgres_device_lookup(
    fixture: str | None,
    *,
    skip: bool,
    dev_eui: str | None,
    hash_salt: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    if skip:
        return {"query_attempted": False, "status": "skipped", "device_registry_match": None}
    if fixture is not None:
        summary = parse_postgres_device_output(fixture, dev_eui=dev_eui, hash_salt=hash_salt)
        summary["status"] = "ok"
        return summary
    sql = "select encode(dev_eui, 'hex') from device limit 200;"
    text, error, returncode = run_command(
        ["docker", "exec", DEFAULT_POSTGRES_CONTAINER, "psql", "-U", "chirpstack", "-d", "chirpstack", "-Atc", sql],
        timeout_seconds=timeout_seconds,
    )
    if error is not None or returncode != 0:
        return {
            "query_attempted": True,
            "status": "query_error",
            "returncode": returncode,
            "error": error or "psql returned non-zero",
            "device_registry_match": None,
            "raw_device_eui_embedded": False,
        }
    summary = parse_postgres_device_output(text, dev_eui=dev_eui, hash_salt=hash_salt)
    summary["status"] = "ok"
    return summary


def decide_audit(
    *,
    wio_identity: dict[str, Any],
    rf_trial_summary: dict[str, Any],
    uplink_summary: dict[str, Any],
    log_summaries: list[dict[str, Any]],
    postgres_summary: dict[str, Any],
) -> str:
    if uplink_summary["uplink_like_record_count"] > 0:
        return "uplink_observed"
    if not wio_identity["dev_eui_present"]:
        return "missing_wio_identity"
    if not rf_trial_summary["latest_real_trial_found"]:
        return "no_real_rf_trial_evidence"
    join_request_hints = sum(summary["join_request_hint_count"] for summary in log_summaries)
    join_reject_hints = sum(summary["join_reject_hint_count"] for summary in log_summaries)
    if postgres_summary.get("status") == "ok" and postgres_summary.get("device_registry_match") is False:
        return "client_dev_eui_not_registered_in_chirpstack"
    if rf_trial_summary["join_failed_response_seen"] and join_reject_hints > 0:
        return "client_join_failed_network_server_rejected"
    if rf_trial_summary["join_failed_response_seen"] and join_request_hints == 0:
        return "client_join_failed_no_gateway_join_hint"
    if rf_trial_summary["join_failed_response_seen"] and join_request_hints > 0:
        return "client_join_failed_join_seen_check_keys_profile"
    if rf_trial_summary["network_joined_response_seen"] and uplink_summary["uplink_like_record_count"] == 0:
        return "client_reported_joined_no_application_uplink"
    return "provisioning_audit_inconclusive"


def next_actions_for_decision(decision: str) -> list[str]:
    if decision == "client_dev_eui_not_registered_in_chirpstack":
        return [
            "create or verify the ChirpStack device using the Wio-E5 DevEUI hash shown in this audit",
            "verify OTAA AppEUI/AppKey and device profile for AS923_2",
            "rerun read-only audit before another RF trial",
        ]
    if decision == "client_join_failed_no_gateway_join_hint":
        return [
            "check Wio-E5 frequency/channel plan and AS923_2 settings",
            "check antenna placement and gateway packet-forwarder logs",
            "do not repeat RF trials until receive path or provisioning is clearer",
        ]
    if decision == "client_join_failed_network_server_rejected":
        return [
            "inspect ChirpStack device keys and device profile",
            "confirm AppKey and JoinEUI/AppEUI on Wio-E5 match ChirpStack",
            "rerun passive MQTT tail while testing one new join",
        ]
    if decision == "uplink_observed":
        return [
            "promote the uplink JSONL evidence into the Scout last-heard review path",
            "record RSSI/SNR/frequency and compare against field placement",
        ]
    return [
        "inspect ChirpStack UI or API for device profile and keys",
        "keep RF trials single-shot and operator approved",
        "collect a fresh passive tail plus RF trial after provisioning is corrected",
    ]


def build_audit_payload(
    *,
    wio_at_path: Path,
    rf_trial_path: Path,
    uplink_path: Path,
    tail_status_path: Path,
    wio_records: list[dict[str, Any]],
    wio_invalid_count: int,
    wio_file_exists: bool,
    rf_trial_summary: dict[str, Any],
    uplink_summary: dict[str, Any],
    tail_summary: dict[str, Any],
    docker_ps_summary: dict[str, Any],
    docker_errors: list[dict[str, Any]],
    log_summaries: list[dict[str, Any]],
    postgres_summary: dict[str, Any],
    hash_salt: str,
) -> dict[str, Any]:
    wio_identity = extract_wio_identity(wio_records, hash_salt=hash_salt)
    decision = decide_audit(
        wio_identity=wio_identity,
        rf_trial_summary=rf_trial_summary,
        uplink_summary=uplink_summary,
        log_summaries=log_summaries,
        postgres_summary=postgres_summary,
    )
    payload = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": SOURCE,
        "hardware_kind": HARDWARE_KIND,
        "decision": decision,
        "wio_at_summary": {
            "path": str(wio_at_path),
            "file_exists": wio_file_exists,
            "record_count_scanned": len(wio_records),
            "invalid_json_line_count": wio_invalid_count,
            **wio_identity,
        },
        "rf_trial_summary": {**rf_trial_summary, "path": str(rf_trial_path)},
        "uplink_summary": {**uplink_summary, "path": str(uplink_path)},
        "tail_status_summary": {**tail_summary, "path": str(tail_status_path)},
        "docker_ps_summary": docker_ps_summary,
        "docker_errors": docker_errors,
        "log_summaries": log_summaries,
        "postgres_device_summary": postgres_summary,
        "next_actions": next_actions_for_decision(decision),
        "raw_log_lines_embedded": False,
        "raw_device_eui_embedded": False,
        "approval_token_embedded": False,
    }
    payload.update(boundary_fields())
    return payload


def append_jsonl(payload: dict[str, Any], output_path: Path | None) -> None:
    if output_path is None:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def audit_oled_message(audit: dict[str, Any]) -> str:
    decision = audit["decision"]
    if decision == "uplink_observed":
        state = "UL OK"
    elif "not_registered" in decision:
        state = "DEV MISSING"
    elif "no_gateway" in decision:
        state = "NO JOIN HINT"
    elif "rejected" in decision:
        state = "JOIN REJECT"
    else:
        state = "AUDIT CHECK"
    lines = [
        "SCOUT LORA AUD",
        state,
        "READ ONLY",
        f"LOG {sum(item['join_request_hint_count'] for item in audit['log_summaries'])}",
        f"UL {audit['uplink_summary']['uplink_like_record_count']}",
        "NO RF TX",
    ]
    return "\n".join(line[:16] for line in lines)


def build_oled_status_payload(
    *,
    audit: dict[str, Any],
    bus: Path,
    address: int,
    driver: str,
    driver_attempted: str | None,
    write_status: str,
    dry_run: bool,
    error: str | None = None,
) -> dict[str, Any]:
    payload = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": "pi_wio_e5_chirpstack_join_audit_oled_status",
        "hardware_kind": "grove_oled_96x96_i2c",
        "bus": str(bus),
        "address": f"0x{address:02x}",
        "driver": driver,
        "driver_attempted": driver_attempted,
        "write_status": write_status,
        "dry_run": dry_run,
        "message": audit_oled_message(audit),
        "audit_decision": audit["decision"],
    }
    payload.update(boundary_fields())
    payload["hardware_control_scope"] = "diagnostic_display_only"
    if error is not None:
        payload["error"] = error
    return payload


def write_oled_status(*, audit: dict[str, Any], dry_run: bool, bus: Path, address: int, driver: str) -> dict[str, Any]:
    if dry_run:
        return build_oled_status_payload(
            audit=audit,
            bus=bus,
            address=address,
            driver=driver,
            driver_attempted=driver,
            write_status="dry_run",
            dry_run=True,
        )
    try:
        driver_attempted = write_display(bus=bus, address=address, driver=driver, message=audit_oled_message(audit))
        return build_oled_status_payload(
            audit=audit,
            bus=bus,
            address=address,
            driver=driver,
            driver_attempted=driver_attempted,
            write_status="ok",
            dry_run=False,
        )
    except Exception as exc:
        return build_oled_status_payload(
            audit=audit,
            bus=bus,
            address=address,
            driver=driver,
            driver_attempted=None,
            write_status="error",
            dry_run=False,
            error=f"{type(exc).__name__}: {exc}",
        )


def led_bits_for_audit(audit: dict[str, Any], *, no_join_hint_bit: int, join_seen_bit: int, uplink_bit: int, rejected_bit: int) -> int:
    decision = audit["decision"]
    if decision == "uplink_observed":
        bit = uplink_bit
    elif "rejected" in decision or "not_registered" in decision:
        bit = rejected_bit
    elif "no_gateway" in decision or "missing" in decision:
        bit = no_join_hint_bit
    else:
        bit = join_seen_bit
    return 1 << (bit - 1)


def build_led_status_payload(
    *,
    audit: dict[str, Any],
    port: str,
    data_gpio: int,
    clock_gpio: int,
    no_join_hint_bit: int,
    join_seen_bit: int,
    uplink_bit: int,
    rejected_bit: int,
    blink_count: int,
    blink_seconds: float,
    write_status: str,
    dry_run: bool,
    error: str | None = None,
) -> dict[str, Any]:
    payload = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": "pi_wio_e5_chirpstack_join_audit_led_status",
        "hardware_kind": "grove_led_bar_v2_my9221",
        "port": port,
        "data_gpio": data_gpio,
        "clock_gpio": clock_gpio,
        "bits": f"0x{led_bits_for_audit(audit, no_join_hint_bit=no_join_hint_bit, join_seen_bit=join_seen_bit, uplink_bit=uplink_bit, rejected_bit=rejected_bit):03x}",
        "audit_decision": audit["decision"],
        "no_join_hint_led_bit": no_join_hint_bit,
        "join_seen_led_bit": join_seen_bit,
        "uplink_led_bit": uplink_bit,
        "rejected_led_bit": rejected_bit,
        "blink_count": blink_count,
        "blink_seconds": blink_seconds,
        "write_status": write_status,
        "dry_run": dry_run,
    }
    payload.update(boundary_fields())
    payload["hardware_control_scope"] = "diagnostic_indicator_only"
    if error is not None:
        payload["error"] = error
    return payload


def blink_led_status(
    *,
    audit: dict[str, Any],
    port: str,
    data_gpio: int,
    clock_gpio: int,
    no_join_hint_bit: int,
    join_seen_bit: int,
    uplink_bit: int,
    rejected_bit: int,
    blink_count: int,
    blink_seconds: float,
    dry_run: bool,
) -> dict[str, Any]:
    if dry_run:
        return build_led_status_payload(
            audit=audit,
            port=port,
            data_gpio=data_gpio,
            clock_gpio=clock_gpio,
            no_join_hint_bit=no_join_hint_bit,
            join_seen_bit=join_seen_bit,
            uplink_bit=uplink_bit,
            rejected_bit=rejected_bit,
            blink_count=blink_count,
            blink_seconds=blink_seconds,
            write_status="dry_run",
            dry_run=True,
        )
    writer = None
    try:
        writer = make_gpio_writer()
        bits = led_bits_for_audit(
            audit,
            no_join_hint_bit=no_join_hint_bit,
            join_seen_bit=join_seen_bit,
            uplink_bit=uplink_bit,
            rejected_bit=rejected_bit,
        )
        import time

        for _ in range(blink_count):
            write_led_bar_bits(writer, data_gpio=data_gpio, clock_gpio=clock_gpio, bits=bits)
            time.sleep(blink_seconds)
            clear_led_bar(writer, data_gpio=data_gpio, clock_gpio=clock_gpio)
            time.sleep(blink_seconds)
        return build_led_status_payload(
            audit=audit,
            port=port,
            data_gpio=data_gpio,
            clock_gpio=clock_gpio,
            no_join_hint_bit=no_join_hint_bit,
            join_seen_bit=join_seen_bit,
            uplink_bit=uplink_bit,
            rejected_bit=rejected_bit,
            blink_count=blink_count,
            blink_seconds=blink_seconds,
            write_status="ok",
            dry_run=False,
        )
    except Exception as exc:
        return build_led_status_payload(
            audit=audit,
            port=port,
            data_gpio=data_gpio,
            clock_gpio=clock_gpio,
            no_join_hint_bit=no_join_hint_bit,
            join_seen_bit=join_seen_bit,
            uplink_bit=uplink_bit,
            rejected_bit=rejected_bit,
            blink_count=blink_count,
            blink_seconds=blink_seconds,
            write_status="error",
            dry_run=False,
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        if writer is not None:
            writer.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Wio-E5 / ChirpStack join provisioning audit.")
    parser.add_argument("--wio-at-jsonl", type=Path, default=DEFAULT_WIO_AT_JSONL)
    parser.add_argument("--rf-trial-jsonl", type=Path, default=DEFAULT_RF_TRIAL_JSONL)
    parser.add_argument("--uplink-jsonl", type=Path, default=DEFAULT_UPLINK_JSONL)
    parser.add_argument("--tail-status-jsonl", type=Path, default=DEFAULT_TAIL_STATUS_JSONL)
    parser.add_argument("--output-jsonl", type=Path, default=DEFAULT_OUTPUT_JSONL)
    parser.add_argument("--hash-salt", default="scout-local-wio-chirpstack-audit-v0")
    parser.add_argument("--docker-since", default="45m")
    parser.add_argument("--docker-tail", type=parse_positive_int, default=800)
    parser.add_argument("--docker-timeout-seconds", type=parse_non_negative_float, default=8.0)
    parser.add_argument("--docker-ps-output")
    parser.add_argument("--chirpstack-log-output")
    parser.add_argument("--gateway-bridge-log-output")
    parser.add_argument("--postgres-device-output")
    parser.add_argument("--skip-postgres-device-query", action="store_true")
    parser.add_argument("--oled-status", action="store_true")
    parser.add_argument("--oled-bus", type=Path, default=Path("/dev/i2c-1"))
    parser.add_argument("--oled-address", type=parse_address, default=parse_address("0x3c"))
    parser.add_argument("--oled-driver", choices=("sh1107g", "ssd1327", "auto"), default="sh1107g")
    parser.add_argument("--oled-dry-run", action="store_true")
    parser.add_argument("--led-status", action="store_true")
    parser.add_argument("--led-port", choices=sorted(PORT_DEFAULTS), default=DEFAULT_LED_PORT)
    parser.add_argument("--led-data-gpio", type=int)
    parser.add_argument("--led-clock-gpio", type=int)
    parser.add_argument("--led-no-join-hint-bit", type=parse_led_bit, default=DEFAULT_LED_NO_JOIN_HINT_BIT)
    parser.add_argument("--led-join-seen-bit", type=parse_led_bit, default=DEFAULT_LED_JOIN_SEEN_BIT)
    parser.add_argument("--led-uplink-bit", type=parse_led_bit, default=DEFAULT_LED_UPLINK_BIT)
    parser.add_argument("--led-rejected-bit", type=parse_led_bit, default=DEFAULT_LED_REJECTED_BIT)
    parser.add_argument("--led-blink-count", type=parse_positive_int, default=2)
    parser.add_argument("--led-blink-seconds", type=parse_non_negative_float, default=0.25)
    parser.add_argument("--led-dry-run", action="store_true")
    args = parser.parse_args(argv)

    wio_records, wio_invalid, wio_exists = read_jsonl(args.wio_at_jsonl)
    rf_records, rf_invalid, rf_exists = read_jsonl(args.rf_trial_jsonl)
    uplink_records, uplink_invalid, uplink_exists = read_jsonl(args.uplink_jsonl)
    tail_records, tail_invalid, tail_exists = read_jsonl(args.tail_status_jsonl)
    wio_identity = extract_wio_identity(wio_records, hash_salt=args.hash_salt)
    dev_eui = None
    if wio_identity["dev_eui_present"]:
        for record in reversed(wio_records):
            for line in record.get("response_lines", []):
                if isinstance(line, str) and line.lower().startswith("+id: deveui"):
                    dev_eui = normalize_eui(line.split(",", 1)[1])
                    break
            if dev_eui:
                break

    docker_errors: list[dict[str, Any]] = []
    ps_text, ps_error, ps_returncode = docker_ps_text(args.docker_ps_output, timeout_seconds=args.docker_timeout_seconds)
    if ps_error is not None or ps_returncode != 0:
        docker_errors.append({"source": "docker_ps", "returncode": ps_returncode, "error": ps_error or "non-zero return"})
    docker_ps_summary = parse_docker_ps(ps_text)

    chirpstack_text, chirpstack_error, chirpstack_returncode = docker_logs_text(
        DEFAULT_CHIRPSTACK_CONTAINER,
        args.chirpstack_log_output,
        since=args.docker_since,
        tail=args.docker_tail,
        timeout_seconds=args.docker_timeout_seconds,
    )
    if chirpstack_error is not None or chirpstack_returncode != 0:
        docker_errors.append({"source": "chirpstack_logs", "returncode": chirpstack_returncode, "error": chirpstack_error or "non-zero return"})
    gateway_text, gateway_error, gateway_returncode = docker_logs_text(
        DEFAULT_GATEWAY_BRIDGE_CONTAINER,
        args.gateway_bridge_log_output,
        since=args.docker_since,
        tail=args.docker_tail,
        timeout_seconds=args.docker_timeout_seconds,
    )
    if gateway_error is not None or gateway_returncode != 0:
        docker_errors.append({"source": "gateway_bridge_logs", "returncode": gateway_returncode, "error": gateway_error or "non-zero return"})

    log_summaries = [
        summarize_log_text(chirpstack_text, dev_eui=dev_eui, source="chirpstack"),
        summarize_log_text(gateway_text, dev_eui=dev_eui, source="gateway_bridge"),
    ]
    postgres_summary = postgres_device_lookup(
        args.postgres_device_output,
        skip=args.skip_postgres_device_query,
        dev_eui=dev_eui,
        hash_salt=args.hash_salt,
        timeout_seconds=args.docker_timeout_seconds,
    )
    audit = build_audit_payload(
        wio_at_path=args.wio_at_jsonl,
        rf_trial_path=args.rf_trial_jsonl,
        uplink_path=args.uplink_jsonl,
        tail_status_path=args.tail_status_jsonl,
        wio_records=wio_records,
        wio_invalid_count=wio_invalid,
        wio_file_exists=wio_exists,
        rf_trial_summary=summarize_rf_trial(rf_records, invalid_count=rf_invalid, file_exists=rf_exists),
        uplink_summary=summarize_uplink(uplink_records, invalid_count=uplink_invalid, file_exists=uplink_exists),
        tail_summary=summarize_tail_status(tail_records, invalid_count=tail_invalid, file_exists=tail_exists),
        docker_ps_summary=docker_ps_summary,
        docker_errors=docker_errors,
        log_summaries=log_summaries,
        postgres_summary=postgres_summary,
        hash_salt=args.hash_salt,
    )

    led_defaults = PORT_DEFAULTS[args.led_port]
    led_data_gpio = args.led_data_gpio if args.led_data_gpio is not None else led_defaults["data_gpio"]
    led_clock_gpio = args.led_clock_gpio if args.led_clock_gpio is not None else led_defaults["clock_gpio"]
    audit["oled_status_updates"] = []
    audit["led_status_updates"] = []
    if args.oled_status:
        audit["oled_status_updates"].append(
            write_oled_status(
                audit=audit,
                dry_run=args.oled_dry_run,
                bus=args.oled_bus,
                address=args.oled_address,
                driver=args.oled_driver,
            )
        )
    if args.led_status:
        audit["led_status_updates"].append(
            blink_led_status(
                audit=audit,
                port=args.led_port,
                data_gpio=led_data_gpio,
                clock_gpio=led_clock_gpio,
                no_join_hint_bit=args.led_no_join_hint_bit,
                join_seen_bit=args.led_join_seen_bit,
                uplink_bit=args.led_uplink_bit,
                rejected_bit=args.led_rejected_bit,
                blink_count=args.led_blink_count,
                blink_seconds=args.led_blink_seconds,
                dry_run=args.led_dry_run,
            )
        )
    append_jsonl(audit, args.output_jsonl)
    print(json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
