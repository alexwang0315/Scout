from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from tools.pi_grove_led_bar_smoke import DEFAULT_PORT as DEFAULT_LED_PORT
    from tools.pi_grove_led_bar_smoke import PORT_DEFAULTS, clear_led_bar, make_gpio_writer, write_led_bar_bits
    from tools.pi_oled_i2c_smoke import parse_address, write_display
except ImportError:  # pragma: no cover - used when copied beside tools on the Pi.
    from pi_grove_led_bar_smoke import DEFAULT_PORT as DEFAULT_LED_PORT
    from pi_grove_led_bar_smoke import PORT_DEFAULTS, clear_led_bar, make_gpio_writer, write_led_bar_bits
    from pi_oled_i2c_smoke import parse_address, write_display


ARTIFACT_KIND = "scout_lorawan_client_observer_status"
ARTIFACT_VERSION = "lorawan_client_observer_status.v0"
SOURCE_TOOL = "scout_lorawan_client_observer"

DEFAULT_EVIDENCE_DIR = Path("/data/scout/admin/ingress/lorawan_client")
DEFAULT_KEY_SYNC_JSONL = Path("/data/scout/providers/lora/wio-e5-chirpstack-key-sync.jsonl")
DEFAULT_PROFILE_PROVISION_JSONL = Path("/data/scout/providers/lora/wio-e5-chirpstack-profile-provision.jsonl")
DEFAULT_TRIAL_PLAN_JSONL = Path("/data/scout/providers/lora/wio-e5-uplink-trial-plan.jsonl")
DEFAULT_RF_TRIAL_JSONL = Path("/data/scout/providers/lora/wio-e5-rf-trial.jsonl")
DEFAULT_JOIN_AUDIT_JSONL = Path("/data/scout/providers/lora/wio-e5-chirpstack-join-audit.jsonl")
DEFAULT_JOIN_STATE_DIAGNOSTIC_JSONL = Path("/data/scout/providers/lora/wio-e5-chirpstack-join-state-diagnostic.jsonl")
DEFAULT_UPLINK_JSONL = Path("/data/scout/providers/lora/sx1303-gateway-uplink.jsonl")
DEFAULT_TAIL_STATUS_JSONL = Path("/data/scout/providers/lora/sx1303-gateway-uplink-tail-status.jsonl")
DEFAULT_WIO_AT_JSONL = Path("/data/scout/providers/wio_e5/wio-e5-at-smoke.jsonl")
DEFAULT_LED_OK_BIT = 9
DEFAULT_LED_WARN_BIT = 1
DEFAULT_LED_FAIL_BIT = 10


@dataclass(frozen=True)
class LorawanClientObserverConfig:
    evidence_dir: Path = DEFAULT_EVIDENCE_DIR
    key_sync_jsonl: Path = DEFAULT_KEY_SYNC_JSONL
    profile_provision_jsonl: Path = DEFAULT_PROFILE_PROVISION_JSONL
    trial_plan_jsonl: Path = DEFAULT_TRIAL_PLAN_JSONL
    rf_trial_jsonl: Path = DEFAULT_RF_TRIAL_JSONL
    join_audit_jsonl: Path = DEFAULT_JOIN_AUDIT_JSONL
    join_state_diagnostic_jsonl: Path = DEFAULT_JOIN_STATE_DIAGNOSTIC_JSONL
    uplink_jsonl: Path = DEFAULT_UPLINK_JSONL
    tail_status_jsonl: Path = DEFAULT_TAIL_STATUS_JSONL
    wio_at_jsonl: Path = DEFAULT_WIO_AT_JSONL
    poll_seconds: float = 10.0
    max_jsonl_records: int = 200
    print_ready: bool = False
    oled_status: bool = False
    oled_dry_run: bool = False
    oled_bus: Path = Path("/dev/i2c-1")
    oled_address: int = 0x3C
    oled_driver: str = "sh1107g"
    led_status: bool = False
    led_dry_run: bool = False
    led_port: str = DEFAULT_LED_PORT
    led_data_gpio: int | None = None
    led_clock_gpio: int | None = None
    led_ok_bit: int = DEFAULT_LED_OK_BIT
    led_warn_bit: int = DEFAULT_LED_WARN_BIT
    led_fail_bit: int = DEFAULT_LED_FAIL_BIT
    led_blink_count: int = 1
    led_blink_seconds: float = 0.15

    @classmethod
    def from_env(cls, prefix: str = "SCOUT_LORAWAN_CLIENT_") -> "LorawanClientObserverConfig":
        def read(name: str, default: str | None = None) -> str | None:
            return os.environ.get(f"{prefix}{name}", default)

        return cls(
            evidence_dir=Path(read("EVIDENCE_DIR", str(DEFAULT_EVIDENCE_DIR)) or DEFAULT_EVIDENCE_DIR).expanduser(),
            key_sync_jsonl=Path(read("KEY_SYNC_JSONL", str(DEFAULT_KEY_SYNC_JSONL)) or DEFAULT_KEY_SYNC_JSONL).expanduser(),
            profile_provision_jsonl=Path(
                read("PROFILE_PROVISION_JSONL", str(DEFAULT_PROFILE_PROVISION_JSONL)) or DEFAULT_PROFILE_PROVISION_JSONL
            ).expanduser(),
            trial_plan_jsonl=Path(read("TRIAL_PLAN_JSONL", str(DEFAULT_TRIAL_PLAN_JSONL)) or DEFAULT_TRIAL_PLAN_JSONL).expanduser(),
            rf_trial_jsonl=Path(read("RF_TRIAL_JSONL", str(DEFAULT_RF_TRIAL_JSONL)) or DEFAULT_RF_TRIAL_JSONL).expanduser(),
            join_audit_jsonl=Path(read("JOIN_AUDIT_JSONL", str(DEFAULT_JOIN_AUDIT_JSONL)) or DEFAULT_JOIN_AUDIT_JSONL).expanduser(),
            join_state_diagnostic_jsonl=Path(
                read("JOIN_STATE_DIAGNOSTIC_JSONL", str(DEFAULT_JOIN_STATE_DIAGNOSTIC_JSONL))
                or DEFAULT_JOIN_STATE_DIAGNOSTIC_JSONL
            ).expanduser(),
            uplink_jsonl=Path(read("UPLINK_JSONL", str(DEFAULT_UPLINK_JSONL)) or DEFAULT_UPLINK_JSONL).expanduser(),
            tail_status_jsonl=Path(read("TAIL_STATUS_JSONL", str(DEFAULT_TAIL_STATUS_JSONL)) or DEFAULT_TAIL_STATUS_JSONL).expanduser(),
            wio_at_jsonl=Path(read("WIO_AT_JSONL", str(DEFAULT_WIO_AT_JSONL)) or DEFAULT_WIO_AT_JSONL).expanduser(),
            poll_seconds=_positive_float(read("POLL_SECONDS"), default=10.0),
            max_jsonl_records=_positive_int(read("MAX_JSONL_RECORDS"), default=200),
            print_ready=_bool_env(read("PRINT_READY", "false")),
            oled_status=_bool_env(read("OLED_STATUS", "false")),
            oled_dry_run=_bool_env(read("OLED_DRY_RUN", "false")),
            oled_bus=Path(read("OLED_BUS", "/dev/i2c-1") or "/dev/i2c-1").expanduser(),
            oled_address=parse_address(read("OLED_ADDRESS", "0x3c") or "0x3c"),
            oled_driver=read("OLED_DRIVER", "sh1107g") or "sh1107g",
            led_status=_bool_env(read("LED_STATUS", "false")),
            led_dry_run=_bool_env(read("LED_DRY_RUN", "false")),
            led_port=read("LED_PORT", DEFAULT_LED_PORT) or DEFAULT_LED_PORT,
            led_data_gpio=_optional_int(read("LED_DATA_GPIO")),
            led_clock_gpio=_optional_int(read("LED_CLOCK_GPIO")),
            led_ok_bit=_led_bit(read("LED_OK_BIT"), default=DEFAULT_LED_OK_BIT),
            led_warn_bit=_led_bit(read("LED_WARN_BIT"), default=DEFAULT_LED_WARN_BIT),
            led_fail_bit=_led_bit(read("LED_FAIL_BIT"), default=DEFAULT_LED_FAIL_BIT),
            led_blink_count=_positive_int(read("LED_BLINK_COUNT"), default=1),
            led_blink_seconds=_non_negative_float(read("LED_BLINK_SECONDS"), default=0.15),
        )


class LorawanClientObserver:
    def __init__(self, config: LorawanClientObserverConfig) -> None:
        self.config = config
        self.started_at = _now_iso()
        self.refresh_count = 0
        self.last_status: dict[str, Any] | None = None

    @property
    def status_path(self) -> Path:
        return self.config.evidence_dir / "lorawan_client_observer_status.json"

    @property
    def evidence_jsonl_path(self) -> Path:
        return self.config.evidence_dir / "lorawan_client_observer_samples.jsonl"

    def refresh(self) -> dict[str, Any]:
        self.refresh_count += 1
        captured_at = _now_iso()
        sources = read_sources(self.config)
        decision = client_decision(sources)
        sample = {
            "captured_at": captured_at,
            "source": SOURCE_TOOL,
            "hardware_kind": "wio_e5_lorawan_client_evidence_observer",
            "decision": decision,
            "sources": sources,
            "boundary": boundary_fields(),
        }
        append_jsonl(self.evidence_jsonl_path, sample)
        oled_status_updates = self._oled_status_updates(sample)
        led_status_updates = self._led_status_updates(sample)
        status = {
            "artifact_kind": ARTIFACT_KIND,
            "artifact_version": ARTIFACT_VERSION,
            "source_tool": SOURCE_TOOL,
            "started_at": self.started_at,
            "updated_at": captured_at,
            "refresh_count": self.refresh_count,
            "decision": decision,
            "answerability": answerability_for_decision(decision),
            "poll_seconds": self.config.poll_seconds,
            "evidence": {
                "evidence_dir": str(self.config.evidence_dir),
                "status_path": str(self.status_path),
                "samples_jsonl_path": str(self.evidence_jsonl_path),
                "key_sync_jsonl": str(self.config.key_sync_jsonl),
                "profile_provision_jsonl": str(self.config.profile_provision_jsonl),
                "trial_plan_jsonl": str(self.config.trial_plan_jsonl),
                "rf_trial_jsonl": str(self.config.rf_trial_jsonl),
                "join_audit_jsonl": str(self.config.join_audit_jsonl),
                "join_state_diagnostic_jsonl": str(self.config.join_state_diagnostic_jsonl),
                "uplink_jsonl": str(self.config.uplink_jsonl),
                "tail_status_jsonl": str(self.config.tail_status_jsonl),
                "wio_at_jsonl": str(self.config.wio_at_jsonl),
            },
            "client_health": client_health_summary(sources),
            "sources": sources,
            "oled_status_updates": oled_status_updates,
            "led_status_updates": led_status_updates,
            "boundary": boundary_fields(),
        }
        write_json(self.status_path, status)
        self.last_status = status
        return status

    def run_forever(self) -> dict[str, Any]:
        ready_printed = False
        while True:
            status = self.refresh()
            if self.config.print_ready and not ready_printed:
                print(
                    json.dumps(
                        {
                            "event": "lorawan_client_observer_ready",
                            "status_path": str(self.status_path),
                            "samples_jsonl_path": str(self.evidence_jsonl_path),
                            "decision": status["decision"],
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    flush=True,
                )
                ready_printed = True
            time.sleep(self.config.poll_seconds)

    def _oled_status_updates(self, sample: dict[str, Any]) -> list[dict[str, Any]]:
        if not self.config.oled_status:
            return []
        return [
            write_client_oled_status(
                sample=sample,
                dry_run=self.config.oled_dry_run,
                bus=self.config.oled_bus,
                address=self.config.oled_address,
                driver=self.config.oled_driver,
            )
        ]

    def _led_status_updates(self, sample: dict[str, Any]) -> list[dict[str, Any]]:
        if not self.config.led_status:
            return []
        defaults = PORT_DEFAULTS[self.config.led_port]
        data_gpio = self.config.led_data_gpio if self.config.led_data_gpio is not None else defaults["data_gpio"]
        clock_gpio = self.config.led_clock_gpio if self.config.led_clock_gpio is not None else defaults["clock_gpio"]
        return [
            blink_client_led_status(
                sample=sample,
                port=self.config.led_port,
                data_gpio=data_gpio,
                clock_gpio=clock_gpio,
                ok_bit=self.config.led_ok_bit,
                warn_bit=self.config.led_warn_bit,
                fail_bit=self.config.led_fail_bit,
                blink_count=self.config.led_blink_count,
                blink_seconds=self.config.led_blink_seconds,
                dry_run=self.config.led_dry_run,
            )
        ]


def read_sources(config: LorawanClientObserverConfig) -> dict[str, Any]:
    return {
        "key_sync": summarize_jsonl(config.key_sync_jsonl, max_records=config.max_jsonl_records),
        "profile_provision": summarize_jsonl(config.profile_provision_jsonl, max_records=config.max_jsonl_records),
        "trial_plan": summarize_jsonl(config.trial_plan_jsonl, max_records=config.max_jsonl_records),
        "rf_trial": summarize_jsonl(config.rf_trial_jsonl, max_records=config.max_jsonl_records),
        "join_audit": summarize_jsonl(config.join_audit_jsonl, max_records=config.max_jsonl_records),
        "join_state_diagnostic": summarize_jsonl(config.join_state_diagnostic_jsonl, max_records=config.max_jsonl_records),
        "uplink": summarize_jsonl(config.uplink_jsonl, max_records=config.max_jsonl_records),
        "tail_status": summarize_jsonl(config.tail_status_jsonl, max_records=config.max_jsonl_records),
        "wio_at": summarize_jsonl(config.wio_at_jsonl, max_records=config.max_jsonl_records),
    }


def summarize_jsonl(path: Path, *, max_records: int) -> dict[str, Any]:
    invalid_count = 0
    record_count = 0
    latest: dict[str, Any] | None = None
    if not path.exists():
        return {
            "path": str(path),
            "exists": False,
            "record_count_scanned": 0,
            "invalid_json_line_count": 0,
            "latest": None,
        }
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in lines[-max_records:]:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            invalid_count += 1
            continue
        if not isinstance(payload, dict):
            invalid_count += 1
            continue
        record_count += 1
        latest = compact_record(payload)
    return {
        "path": str(path),
        "exists": True,
        "record_count_scanned": record_count,
        "invalid_json_line_count": invalid_count,
        "latest": latest,
    }


def compact_record(payload: dict[str, Any]) -> dict[str, Any]:
    keep = {
        "captured_at",
        "source",
        "status",
        "decision",
        "hardware_kind",
        "plan_status",
        "operator_approval_recorded",
        "frequency_hz",
        "region_profile",
        "blockers",
        "diagnostic_flags",
        "next_recommended_action",
        "rf_tx_allowed",
        "rf_tx_executed",
        "join_executed",
        "join_only",
        "lorawan_uplink_allowed",
        "lorawan_uplink_executed",
        "observed_uplink_count",
        "uplink_observed",
        "raw_device_identity_exposed",
        "raw_key_exposed",
        "safety_api_called",
        "phase1_l0_l4_state_mutated",
    }
    compact = {key: payload.get(key) for key in keep if key in payload}
    if "command_results" in payload:
        compact["command_results"] = [
            {
                key: result.get(key)
                for key in (
                    "label",
                    "response_status",
                    "join_command",
                    "uplink_command",
                    "command_executed",
                    "response_lines",
                )
                if key in result
            }
            for result in payload.get("command_results", [])
            if isinstance(result, dict)
        ]
    if "chirpstack_state" in payload:
        compact["chirpstack_state"] = payload.get("chirpstack_state")
    return compact


def client_decision(sources: dict[str, Any]) -> str:
    latest_uplink = latest_source(sources, "uplink")
    latest_rf = latest_source(sources, "rf_trial")
    latest_join_state = latest_source(sources, "join_state_diagnostic")
    latest_audit = latest_source(sources, "join_audit")
    latest_plan = latest_source(sources, "trial_plan")
    latest_key_sync = latest_source(sources, "key_sync")
    latest_profile = latest_source(sources, "profile_provision")

    if latest_uplink:
        return "uplink_observed"
    if latest_rf.get("status") == "rf_trial_join_confirmed_no_uplink":
        return "join_confirmed_waiting_for_uplink"
    if latest_join_state.get("status") == "stale_join_state_suspected":
        return "stale_join_state_suspected"
    if latest_audit.get("decision") == "client_join_failed_network_server_rejected":
        return "join_rejected"
    if latest_rf.get("status") == "rf_trial_join_not_confirmed":
        return "join_not_confirmed"
    if latest_plan.get("status") == "ready_for_manual_uplink_trial":
        return "ready_for_join_only"
    if latest_key_sync.get("status") == "key_sync_applied" or latest_profile.get("status") in {
        "profile_provisioned",
        "profile_updated",
        "profile_verified",
    }:
        return "client_configured_waiting_for_plan"
    return "client_evidence_incomplete"


def latest_source(sources: dict[str, Any], name: str) -> dict[str, Any]:
    latest = sources.get(name, {}).get("latest")
    return latest if isinstance(latest, dict) else {}


def client_health_summary(sources: dict[str, Any]) -> dict[str, Any]:
    latest_rf = latest_source(sources, "rf_trial")
    latest_audit = latest_source(sources, "join_audit")
    latest_join_state = latest_source(sources, "join_state_diagnostic")
    latest_tail = latest_source(sources, "tail_status")
    latest_uplink = latest_source(sources, "uplink")
    latest_plan = latest_source(sources, "trial_plan")
    return {
        "trial_plan_status": latest_plan.get("status"),
        "rf_trial_status": latest_rf.get("status"),
        "rf_trial_join_only": latest_rf.get("join_only"),
        "join_audit_decision": latest_audit.get("decision"),
        "join_state_status": latest_join_state.get("status"),
        "join_state_flags": latest_join_state.get("diagnostic_flags", []),
        "tail_status": latest_tail.get("status"),
        "tail_observed_uplink_count": latest_tail.get("observed_uplink_count"),
        "uplink_record_count": sources.get("uplink", {}).get("record_count_scanned", 0),
        "last_uplink_seen_at": latest_uplink.get("captured_at"),
        "latest_rf_seen_at": latest_rf.get("captured_at"),
        "latest_join_state_seen_at": latest_join_state.get("captured_at"),
    }


def answerability_for_decision(decision: str) -> str:
    return {
        "uplink_observed": "client_uplink_evidence_available",
        "join_confirmed_waiting_for_uplink": "join_evidence_available_waiting_for_application_uplink",
        "stale_join_state_suspected": "chirpstack_join_state_repair_required_before_retry",
        "join_rejected": "network_server_rejected_latest_join",
        "join_not_confirmed": "client_join_not_confirmed",
        "ready_for_join_only": "ready_for_operator_approved_join_only_trial",
        "client_configured_waiting_for_plan": "client_configured_but_trial_plan_missing",
    }.get(decision, "client_evidence_incomplete")


def boundary_fields() -> dict[str, Any]:
    return {
        "read_only": True,
        "serial_opened": False,
        "rf_tx_allowed": False,
        "rf_tx_executed": False,
        "join_allowed": False,
        "join_executed": False,
        "lorawan_uplink_allowed": False,
        "lorawan_uplink_executed": False,
        "downlink_allowed": False,
        "outbound_send_performed": False,
        "chirpstack_config_changed": False,
        "device_registry_changed": False,
        "postgres_write_performed": False,
        "credential_value_exposed": False,
        "raw_device_identity_exposed": False,
        "raw_key_exposed": False,
        "phase1_safety_decision_change_allowed": False,
        "phase1_l0_l4_state_mutated": False,
        "safety_api_called": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "lorawan_client_evidence_observer_only",
    }


def client_oled_message(sample: dict[str, Any]) -> str:
    decision = sample["decision"]
    state = {
        "uplink_observed": "UPLINK OK",
        "join_confirmed_waiting_for_uplink": "JOIN OK",
        "stale_join_state_suspected": "JOIN STALE",
        "join_rejected": "JOIN REJECT",
        "join_not_confirmed": "JOIN FAIL",
        "ready_for_join_only": "READY JOIN",
        "client_configured_waiting_for_plan": "PLAN WAIT",
    }.get(decision, "EVIDENCE?")
    health = client_health_summary(sample["sources"])
    lines = [
        "SCOUT LORA CL",
        state,
        str(health.get("trial_plan_status") or "PLAN?")[:16],
        str(health.get("rf_trial_status") or "RF?")[:16],
        str(health.get("join_state_status") or health.get("join_audit_decision") or "JOIN?")[:16],
        "SAFETY NO",
    ]
    return "\n".join(line[:16] for line in lines)


def write_client_oled_status(
    *,
    sample: dict[str, Any],
    dry_run: bool,
    bus: Path,
    address: int,
    driver: str,
) -> dict[str, Any]:
    message = client_oled_message(sample)
    payload = {
        "captured_at": _now_iso(),
        "source": "scout_lorawan_client_observer_oled_status",
        "hardware_kind": "grove_oled_96x96_i2c",
        "bus": str(bus),
        "address": f"0x{address:02x}",
        "driver": driver,
        "driver_attempted": driver if dry_run else None,
        "write_status": "dry_run" if dry_run else "pending",
        "dry_run": dry_run,
        "message": message,
        "decision": sample["decision"],
    }
    payload.update(boundary_fields())
    payload["hardware_control_scope"] = "diagnostic_display_only"
    if dry_run:
        return payload
    try:
        payload["driver_attempted"] = write_display(bus=bus, address=address, driver=driver, message=message)
        payload["write_status"] = "ok"
    except Exception as exc:
        payload["write_status"] = "error"
        payload["error"] = f"{type(exc).__name__}: {exc}"
    return payload


def led_bits_for_sample(sample: dict[str, Any], *, ok_bit: int, warn_bit: int, fail_bit: int) -> int:
    decision = sample["decision"]
    if decision in {"uplink_observed", "join_confirmed_waiting_for_uplink", "ready_for_join_only"}:
        bit = ok_bit
    elif decision in {"stale_join_state_suspected", "join_rejected", "join_not_confirmed"}:
        bit = fail_bit
    else:
        bit = warn_bit
    return 1 << (bit - 1)


def blink_client_led_status(
    *,
    sample: dict[str, Any],
    port: str,
    data_gpio: int,
    clock_gpio: int,
    ok_bit: int,
    warn_bit: int,
    fail_bit: int,
    blink_count: int,
    blink_seconds: float,
    dry_run: bool,
) -> dict[str, Any]:
    bits = led_bits_for_sample(sample, ok_bit=ok_bit, warn_bit=warn_bit, fail_bit=fail_bit)
    payload = {
        "captured_at": _now_iso(),
        "source": "scout_lorawan_client_observer_led_status",
        "hardware_kind": "grove_led_bar_v2_my9221",
        "port": port,
        "data_gpio": data_gpio,
        "clock_gpio": clock_gpio,
        "bits": f"0x{bits:03x}",
        "decision": sample["decision"],
        "ok_led_bit": ok_bit,
        "warn_led_bit": warn_bit,
        "fail_led_bit": fail_bit,
        "blink_count": blink_count,
        "blink_seconds": blink_seconds,
        "write_status": "dry_run" if dry_run else "pending",
        "dry_run": dry_run,
    }
    payload.update(boundary_fields())
    payload["hardware_control_scope"] = "diagnostic_indicator_only"
    if dry_run:
        return payload
    writer = None
    try:
        writer = make_gpio_writer()
        for _ in range(blink_count):
            write_led_bar_bits(writer, data_gpio=data_gpio, clock_gpio=clock_gpio, bits=bits)
            time.sleep(blink_seconds)
            clear_led_bar(writer, data_gpio=data_gpio, clock_gpio=clock_gpio)
            time.sleep(blink_seconds)
        payload["write_status"] = "ok"
    except Exception as exc:
        payload["write_status"] = "error"
        payload["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if writer is not None:
            writer.close()
    return payload


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _positive_int(value: str | None, *, default: int) -> int:
    if value in (None, ""):
        return default
    parsed = int(value)
    if parsed < 1:
        raise ValueError("value must be at least 1")
    return parsed


def _positive_float(value: str | None, *, default: float) -> float:
    if value in (None, ""):
        return default
    parsed = float(value)
    if parsed <= 0:
        raise ValueError("value must be positive")
    return parsed


def _non_negative_float(value: str | None, *, default: float) -> float:
    if value in (None, ""):
        return default
    parsed = float(value)
    if parsed < 0:
        raise ValueError("value must be non-negative")
    return parsed


def _optional_int(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _led_bit(value: str | None, *, default: int) -> int:
    parsed = _positive_int(value, default=default)
    if not 1 <= parsed <= 10:
        raise ValueError("LED bit must be between 1 and 10")
    return parsed


def _bool_env(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Scout LoRaWAN client evidence observer.")
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE_DIR)
    parser.add_argument("--key-sync-jsonl", type=Path, default=DEFAULT_KEY_SYNC_JSONL)
    parser.add_argument("--profile-provision-jsonl", type=Path, default=DEFAULT_PROFILE_PROVISION_JSONL)
    parser.add_argument("--trial-plan-jsonl", type=Path, default=DEFAULT_TRIAL_PLAN_JSONL)
    parser.add_argument("--rf-trial-jsonl", type=Path, default=DEFAULT_RF_TRIAL_JSONL)
    parser.add_argument("--join-audit-jsonl", type=Path, default=DEFAULT_JOIN_AUDIT_JSONL)
    parser.add_argument("--join-state-diagnostic-jsonl", type=Path, default=DEFAULT_JOIN_STATE_DIAGNOSTIC_JSONL)
    parser.add_argument("--uplink-jsonl", type=Path, default=DEFAULT_UPLINK_JSONL)
    parser.add_argument("--tail-status-jsonl", type=Path, default=DEFAULT_TAIL_STATUS_JSONL)
    parser.add_argument("--wio-at-jsonl", type=Path, default=DEFAULT_WIO_AT_JSONL)
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    parser.add_argument("--max-jsonl-records", type=int, default=200)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--print-ready", action="store_true")
    parser.add_argument("--oled-status", action="store_true")
    parser.add_argument("--oled-bus", type=Path, default=Path("/dev/i2c-1"))
    parser.add_argument("--oled-address", type=parse_address, default=parse_address("0x3c"))
    parser.add_argument("--oled-driver", choices=("sh1107g", "ssd1327", "auto"), default="sh1107g")
    parser.add_argument("--oled-dry-run", action="store_true")
    parser.add_argument("--led-status", action="store_true")
    parser.add_argument("--led-port", choices=sorted(PORT_DEFAULTS), default=DEFAULT_LED_PORT)
    parser.add_argument("--led-data-gpio", type=int)
    parser.add_argument("--led-clock-gpio", type=int)
    parser.add_argument("--led-ok-bit", type=int, default=DEFAULT_LED_OK_BIT)
    parser.add_argument("--led-warn-bit", type=int, default=DEFAULT_LED_WARN_BIT)
    parser.add_argument("--led-fail-bit", type=int, default=DEFAULT_LED_FAIL_BIT)
    parser.add_argument("--led-blink-count", type=int, default=1)
    parser.add_argument("--led-blink-seconds", type=float, default=0.15)
    parser.add_argument("--led-dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = LorawanClientObserverConfig(
        evidence_dir=args.evidence_dir,
        key_sync_jsonl=args.key_sync_jsonl,
        profile_provision_jsonl=args.profile_provision_jsonl,
        trial_plan_jsonl=args.trial_plan_jsonl,
        rf_trial_jsonl=args.rf_trial_jsonl,
        join_audit_jsonl=args.join_audit_jsonl,
        join_state_diagnostic_jsonl=args.join_state_diagnostic_jsonl,
        uplink_jsonl=args.uplink_jsonl,
        tail_status_jsonl=args.tail_status_jsonl,
        wio_at_jsonl=args.wio_at_jsonl,
        poll_seconds=args.poll_seconds,
        max_jsonl_records=args.max_jsonl_records,
        print_ready=args.print_ready,
        oled_status=args.oled_status,
        oled_dry_run=args.oled_dry_run,
        oled_bus=args.oled_bus,
        oled_address=args.oled_address,
        oled_driver=args.oled_driver,
        led_status=args.led_status,
        led_dry_run=args.led_dry_run,
        led_port=args.led_port,
        led_data_gpio=args.led_data_gpio,
        led_clock_gpio=args.led_clock_gpio,
        led_ok_bit=args.led_ok_bit,
        led_warn_bit=args.led_warn_bit,
        led_fail_bit=args.led_fail_bit,
        led_blink_count=args.led_blink_count,
        led_blink_seconds=args.led_blink_seconds,
    )
    observer = LorawanClientObserver(config)
    if args.once:
        status = observer.refresh()
        print(json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    observer.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
