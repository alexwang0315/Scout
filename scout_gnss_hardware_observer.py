from __future__ import annotations

import argparse
import json
import os
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.pi_grove_led_bar_smoke import DEFAULT_PORT as DEFAULT_LED_PORT
from tools.pi_grove_led_bar_smoke import PORT_DEFAULTS, clear_led_bar, make_gpio_writer, write_led_bar_bits
from tools.pi_oled_i2c_smoke import parse_address, write_display


ARTIFACT_KIND = "scout_gnss_hardware_observer_status"
ARTIFACT_VERSION = "gnss_hardware_observer_status.v0"
SOURCE_TOOL = "scout_gnss_hardware_observer"

DEFAULT_EVIDENCE_DIR = Path("/data/scout/admin/ingress/gnss_hardware")
DEFAULT_GATEWAY_JSONL = Path("/data/scout/providers/lora/sx1303-gateway-gps-nmea-smoke.jsonl")
DEFAULT_GROVE_JSONL = Path("/data/scout/providers/gnss/manual-smoke.jsonl")


@dataclass(frozen=True)
class GnssSourceSpec:
    source_id: str
    role: str
    hardware_kind: str
    jsonl_path: Path
    priority: int


@dataclass(frozen=True)
class GnssHardwareObserverConfig:
    evidence_dir: Path = DEFAULT_EVIDENCE_DIR
    gateway_jsonl: Path = DEFAULT_GATEWAY_JSONL
    grove_jsonl: Path = DEFAULT_GROVE_JSONL
    poll_seconds: float = 2.0
    max_records: int = 200
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
    led_fix_bit: int = 10
    led_no_fix_bit: int = 1
    led_blink_count: int = 1
    led_blink_seconds: float = 0.15

    @classmethod
    def from_env(cls, prefix: str = "SCOUT_GNSS_HARDWARE_") -> "GnssHardwareObserverConfig":
        def read(name: str, default: str | None = None) -> str | None:
            return os.environ.get(f"{prefix}{name}", default)

        return cls(
            evidence_dir=Path(read("EVIDENCE_DIR", str(DEFAULT_EVIDENCE_DIR)) or DEFAULT_EVIDENCE_DIR).expanduser(),
            gateway_jsonl=Path(read("GATEWAY_JSONL", str(DEFAULT_GATEWAY_JSONL)) or DEFAULT_GATEWAY_JSONL).expanduser(),
            grove_jsonl=Path(read("GROVE_JSONL", str(DEFAULT_GROVE_JSONL)) or DEFAULT_GROVE_JSONL).expanduser(),
            poll_seconds=_positive_float(read("POLL_SECONDS"), default=2.0),
            max_records=_positive_int(read("MAX_RECORDS"), default=200),
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
            led_fix_bit=_led_bit(read("LED_FIX_BIT"), default=10),
            led_no_fix_bit=_led_bit(read("LED_NO_FIX_BIT"), default=1),
            led_blink_count=_positive_int(read("LED_BLINK_COUNT"), default=1),
            led_blink_seconds=_non_negative_float(read("LED_BLINK_SECONDS"), default=0.15),
        )


class GnssHardwareObserver:
    def __init__(self, config: GnssHardwareObserverConfig):
        self.config = config
        self.started_at = _now_iso()
        self.refresh_count = 0
        self.last_status: dict[str, Any] | None = None

    @property
    def status_path(self) -> Path:
        return self.config.evidence_dir / "gnss_hardware_observer_status.json"

    @property
    def snapshot_path(self) -> Path:
        return self.config.evidence_dir / "live_navigation_snapshot.json"

    def source_specs(self) -> list[GnssSourceSpec]:
        return [
            GnssSourceSpec(
                source_id="lorawan_gateway_gps",
                role="leader_gateway_location",
                hardware_kind="sx1303_gateway_hat_l76k_gnss_uart",
                jsonl_path=self.config.gateway_jsonl,
                priority=20,
            ),
            GnssSourceSpec(
                source_id="grove_gps_module",
                role="direct_grove_gnss_receiver",
                hardware_kind="grove_gps_ublox5_uart",
                jsonl_path=self.config.grove_jsonl,
                priority=10,
            ),
        ]

    def refresh(self) -> dict[str, Any]:
        self.refresh_count += 1
        updated_at = _now_iso()
        source_statuses = [self._source_status(spec) for spec in self.source_specs()]
        candidates = [
            source_status["latest_valid_candidate"]
            for source_status in source_statuses
            if isinstance(source_status.get("latest_valid_candidate"), dict)
        ]
        selected = choose_best_candidate(candidates)
        snapshot = build_live_navigation_snapshot(
            selected,
            updated_at=updated_at,
            source_statuses=source_statuses,
        )
        self._write_json(self.snapshot_path, snapshot)
        oled_status_updates = self._oled_status_updates(snapshot)
        led_status_updates = self._led_status_updates(snapshot)

        status = {
            "artifact_kind": ARTIFACT_KIND,
            "artifact_version": ARTIFACT_VERSION,
            "source_tool": SOURCE_TOOL,
            "started_at": self.started_at,
            "updated_at": updated_at,
            "refresh_count": self.refresh_count,
            "evidence": {
                "evidence_dir": str(self.config.evidence_dir),
                "status_path": str(self.status_path),
                "live_navigation_snapshot_path": str(self.snapshot_path),
                "gateway_jsonl_path": str(self.config.gateway_jsonl),
                "grove_jsonl_path": str(self.config.grove_jsonl),
            },
            "poll_seconds": self.config.poll_seconds,
            "max_records": self.config.max_records,
            "listening_source_count": len(source_statuses),
            "active_listening_source_count": sum(
                1 for item in source_statuses if item["file_exists"] and item["record_count_scanned"] > 0
            ),
            "valid_source_count": sum(1 for item in source_statuses if item["valid_candidate_count"] > 0),
            "selected_source": selected.get("source_id") if selected else None,
            "selected_observed_at": selected.get("observed_at") if selected else None,
            "decision": "gnss_fix_available" if selected else _decision_without_selection(source_statuses),
            "answerability": "live_gnss_snapshot_available" if selected else "live_gnss_snapshot_missing_fix",
            "live_navigation_snapshot": snapshot,
            "listening_sources": source_statuses,
            "oled_status_updates": oled_status_updates,
            "led_status_updates": led_status_updates,
            "boundary": boundary_fields(),
        }
        self._write_json(self.status_path, status)
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
                            "event": "gnss_hardware_observer_ready",
                            "status_path": str(self.status_path),
                            "live_navigation_snapshot_path": str(self.snapshot_path),
                            "listening_source_count": status["listening_source_count"],
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    flush=True,
                )
                ready_printed = True
            time.sleep(self.config.poll_seconds)

    def _source_status(self, spec: GnssSourceSpec) -> dict[str, Any]:
        records, invalid_line_count = load_jsonl_tail(spec.jsonl_path, max_records=self.config.max_records)
        candidates = [candidate for record in records if (candidate := candidate_from_record(record, spec)) is not None]
        valid_candidates = [candidate for candidate in candidates if candidate["position_valid"] and candidate["fix_valid"]]
        latest_candidate = choose_best_candidate(candidates)
        latest_valid_candidate = choose_best_candidate(valid_candidates)
        return {
            "source_id": spec.source_id,
            "role": spec.role,
            "hardware_kind": spec.hardware_kind,
            "jsonl_path": str(spec.jsonl_path),
            "file_exists": spec.jsonl_path.exists(),
            "record_count_scanned": len(records),
            "invalid_json_line_count": invalid_line_count,
            "candidate_count": len(candidates),
            "valid_candidate_count": len(valid_candidates),
            "latest_candidate": latest_candidate,
            "latest_valid_candidate": latest_valid_candidate,
            "status": _source_status_value(spec.jsonl_path, len(records), len(candidates), len(valid_candidates)),
            "boundary": boundary_fields(),
        }

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _oled_status_updates(self, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        if not self.config.oled_status:
            return []
        return [
            write_observer_oled_status(
                snapshot=snapshot,
                dry_run=self.config.oled_dry_run,
                bus=self.config.oled_bus,
                address=self.config.oled_address,
                driver=self.config.oled_driver,
            )
        ]

    def _led_status_updates(self, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        if not self.config.led_status:
            return []
        defaults = PORT_DEFAULTS[self.config.led_port]
        data_gpio = self.config.led_data_gpio if self.config.led_data_gpio is not None else defaults["data_gpio"]
        clock_gpio = self.config.led_clock_gpio if self.config.led_clock_gpio is not None else defaults["clock_gpio"]
        return [
            blink_observer_led_status(
                snapshot=snapshot,
                port=self.config.led_port,
                data_gpio=data_gpio,
                clock_gpio=clock_gpio,
                fix_bit=self.config.led_fix_bit,
                no_fix_bit=self.config.led_no_fix_bit,
                blink_count=self.config.led_blink_count,
                blink_seconds=self.config.led_blink_seconds,
                dry_run=self.config.led_dry_run,
            )
        ]


def candidate_from_record(record: dict[str, Any], spec: GnssSourceSpec) -> dict[str, Any] | None:
    if spec.source_id == "lorawan_gateway_gps":
        return _candidate_from_gateway_record(record, spec)
    if spec.source_id == "grove_gps_module":
        return _candidate_from_grove_record(record, spec)
    return None


def _candidate_from_gateway_record(record: dict[str, Any], spec: GnssSourceSpec) -> dict[str, Any] | None:
    best = record.get("best_candidate")
    if not isinstance(best, dict):
        return None

    fix_summary = best.get("gnss_fix_summary") if isinstance(best.get("gnss_fix_summary"), dict) else {}
    signal_summary = best.get("gnss_signal_summary") if isinstance(best.get("gnss_signal_summary"), dict) else {}
    payload = fix_summary.get("latest_valid_fix")
    payload_is_summary_fix = isinstance(payload, dict)
    if not payload_is_summary_fix:
        payload = best.get("first_nmea_payload")
    if not isinstance(payload, dict):
        return None

    return _candidate_from_payload(
        payload,
        spec=spec,
        record=record,
        selected_port=_text(record.get("selected_port")) or _text(best.get("port")),
        selected_baud=_int_or_none(record.get("selected_baud")) or _int_or_none(best.get("baud")),
        record_status=_text(record.get("status")) or _text(best.get("status")),
        signal_summary=signal_summary,
        payload_is_summary_fix=payload_is_summary_fix,
    )


def _candidate_from_grove_record(record: dict[str, Any], spec: GnssSourceSpec) -> dict[str, Any] | None:
    source = _text(record.get("source"))
    if source not in {"pi_gnss_nmea_smoke", "pi_gnss_nmea_stream_status"}:
        return None
    return _candidate_from_payload(
        record,
        spec=spec,
        record=record,
        selected_port=_text(record.get("device_port")),
        selected_baud=_int_or_none(record.get("baud")),
        record_status=_text(record.get("nmea_stream_state")) or "nmea_observed",
        signal_summary=record.get("satellite_signal") if isinstance(record.get("satellite_signal"), dict) else {},
        payload_is_summary_fix=False,
    )


def _candidate_from_payload(
    payload: dict[str, Any],
    *,
    spec: GnssSourceSpec,
    record: dict[str, Any],
    selected_port: str | None,
    selected_baud: int | None,
    record_status: str | None,
    signal_summary: dict[str, Any],
    payload_is_summary_fix: bool,
) -> dict[str, Any]:
    position = payload.get("position") if isinstance(payload.get("position"), dict) else {}
    motion = payload.get("motion") if isinstance(payload.get("motion"), dict) else {}
    fix_quality = payload.get("fix_quality") if isinstance(payload.get("fix_quality"), dict) else {}
    lat = _float_or_none(position.get("lat"))
    lon = _float_or_none(position.get("lon"))
    elevation_m = _float_or_none(position.get("altitude_m") or position.get("elevation_m"))
    quality = _first_present(payload.get("quality"), fix_quality.get("quality"))
    status = _first_present(payload.get("status"), fix_quality.get("status"))
    satellites = _int_or_none(_first_present(payload.get("satellites"), fix_quality.get("satellites")))
    hdop = _float_or_none(_first_present(payload.get("hdop"), fix_quality.get("hdop")))
    checksum_valid = payload.get("checksum_valid")
    valid_from_quality = fix_quality.get("valid")
    if valid_from_quality is None and payload_is_summary_fix:
        valid_from_quality = True
    position_valid = lat is not None and lon is not None
    fix_valid = bool(position_valid and valid_from_quality is True and checksum_valid is not False)
    observed_at = _observed_at(record, payload)
    max_cno = _float_or_none(
        _first_present(
            signal_summary.get("max_cno_dbhz"),
            signal_summary.get("gps_max_cno_dbhz"),
            payload.get("max_cno_dbhz"),
        )
    )
    return {
        "source_id": spec.source_id,
        "role": spec.role,
        "hardware_kind": spec.hardware_kind,
        "source_priority": spec.priority,
        "observed_at": observed_at,
        "gnss_time_utc": payload.get("gnss_time_utc"),
        "record_source": record.get("source"),
        "record_status": record_status,
        "selected_port": selected_port,
        "selected_baud": selected_baud,
        "sentence_type": payload.get("sentence_type"),
        "lat": lat,
        "lon": lon,
        "elevation_m": elevation_m,
        "position_valid": position_valid,
        "fix_valid": fix_valid,
        "fix_quality": "valid" if fix_valid else "invalid",
        "fix_quality_value": quality,
        "fix_status": status,
        "satellite_count": satellites,
        "hdop": hdop,
        "max_cno_dbhz": max_cno,
        "course_deg": _float_or_none(motion.get("course_deg")),
        "speed_mps": _float_or_none(motion.get("speed_mps")),
        "checksum_valid": checksum_valid,
        "raw_evidence_path": str(spec.jsonl_path),
        "runtime_safety_truth": False,
        "phase1_l0_l4_state_mutated": False,
        "safety_api_called": False,
    }


def build_live_navigation_snapshot(
    candidate: dict[str, Any] | None,
    *,
    updated_at: str,
    source_statuses: list[dict[str, Any]],
) -> dict[str, Any]:
    base = {
        "artifact_kind": "scout_live_navigation_snapshot",
        "artifact_version": "live_navigation_snapshot.raw_gnss_observer.v0",
        "source_tool": SOURCE_TOOL,
        "updated_at": updated_at,
        "snapshot_status": "valid_fix" if candidate else "no_valid_fix",
        "listening_sources": [
            {
                "source_id": item["source_id"],
                "status": item["status"],
                "record_count_scanned": item["record_count_scanned"],
                "valid_candidate_count": item["valid_candidate_count"],
            }
            for item in source_statuses
        ],
        "boundary": boundary_fields(),
    }
    if candidate is None:
        return base

    snapshot = {
        **base,
        "observed_at": candidate["observed_at"],
        "lat": candidate["lat"],
        "lon": candidate["lon"],
        "elevation_m": candidate["elevation_m"],
        "source": candidate["source_id"],
        "hdop": candidate["hdop"],
        "fix_quality": candidate["fix_quality"],
        "satellite_count": candidate["satellite_count"],
        "max_cno_dbhz": candidate["max_cno_dbhz"],
        "course_deg": candidate["course_deg"],
        "speed_mps": candidate["speed_mps"],
        "last_anchor_at": candidate["observed_at"],
        "raw_evidence_path": candidate["raw_evidence_path"],
        "selected_port": candidate["selected_port"],
        "selected_baud": candidate["selected_baud"],
        "runtime_safety_truth": False,
        "phase1_l0_l4_state_mutated": False,
        "safety_api_called": False,
    }
    return {key: value for key, value in snapshot.items() if value is not None}


def choose_best_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda candidate: (
            bool(candidate.get("fix_valid")),
            _timestamp_rank(candidate.get("observed_at")),
            int(candidate.get("source_priority") or 0),
        ),
    )


def load_jsonl_tail(path: Path, *, max_records: int) -> tuple[list[dict[str, Any]], int]:
    if max_records < 1:
        raise ValueError("max_records must be at least 1")
    if not path.exists():
        return [], 0
    lines: deque[str] = deque(maxlen=max_records)
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.strip():
                lines.append(line)
    records: list[dict[str, Any]] = []
    invalid_line_count = 0
    for line in lines:
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            invalid_line_count += 1
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
    return records, invalid_line_count


def boundary_fields() -> dict[str, bool]:
    return {
        "evidence_only": True,
        "live_hardware_read_performed": False,
        "runtime_safety_truth": False,
        "phase1_l0_l4_state_mutated": False,
        "safety_api_called": False,
        "outbound_send_performed": False,
        "rf_tx_allowed": False,
        "lorawan_uplink_allowed": False,
        "hardware_control_allowed": False,
        "credential_value_exposed": False,
    }


def observer_oled_message(snapshot: dict[str, Any]) -> str:
    has_fix = snapshot.get("snapshot_status") == "valid_fix"
    source = str(snapshot.get("source") or "none").replace("_", " ").upper()
    source_label = "GATEWAY" if snapshot.get("source") == "lorawan_gateway_gps" else "GROVE" if snapshot.get("source") == "grove_gps_module" else source
    port = Path(str(snapshot.get("selected_port") or "")).name.upper()[:16] or "--"
    baud = snapshot.get("selected_baud") or "--"
    satellites = snapshot.get("satellite_count")
    max_cno = snapshot.get("max_cno_dbhz")
    lines = [
        "SCOUT GNSS",
        "FIX OK" if has_fix else "NO FIX",
        f"SRC {source_label}"[:16],
        f"SAT {_display_value(satellites)} CNO {_display_value(max_cno)}"[:16],
        f"PORT {port}"[:16],
        f"{baud} BAUD"[:16],
        "JSONL ONLY",
    ]
    return "\n".join(line[:16] for line in lines)


def write_observer_oled_status(
    *,
    snapshot: dict[str, Any],
    dry_run: bool,
    bus: Path,
    address: int,
    driver: str,
) -> dict[str, Any]:
    message = observer_oled_message(snapshot)
    if dry_run:
        return build_observer_oled_payload(
            snapshot=snapshot,
            bus=bus,
            address=address,
            driver=driver,
            driver_attempted=driver,
            write_status="dry_run",
            dry_run=True,
            message=message,
        )
    try:
        driver_attempted = write_display(bus=bus, address=address, driver=driver, message=message)
        return build_observer_oled_payload(
            snapshot=snapshot,
            bus=bus,
            address=address,
            driver=driver,
            driver_attempted=driver_attempted,
            write_status="ok",
            dry_run=False,
            message=message,
        )
    except Exception as exc:
        return build_observer_oled_payload(
            snapshot=snapshot,
            bus=bus,
            address=address,
            driver=driver,
            driver_attempted=None,
            write_status="error",
            dry_run=False,
            message=message,
            error=f"{type(exc).__name__}: {exc}",
        )


def build_observer_oled_payload(
    *,
    snapshot: dict[str, Any],
    bus: Path,
    address: int,
    driver: str,
    driver_attempted: str | None,
    write_status: str,
    dry_run: bool,
    message: str,
    error: str | None = None,
) -> dict[str, Any]:
    payload = {
        "captured_at": _now_iso(),
        "source": "scout_gnss_hardware_observer_oled_status",
        "hardware_kind": "grove_oled_96x96_i2c",
        "bus": str(bus),
        "address": f"0x{address:02x}",
        "driver": driver,
        "driver_attempted": driver_attempted,
        "write_status": write_status,
        "dry_run": dry_run,
        "message": message,
        "snapshot_status": snapshot.get("snapshot_status"),
        "selected_source": snapshot.get("source"),
        "selected_port": snapshot.get("selected_port"),
        "selected_baud": snapshot.get("selected_baud"),
        "hardware_control_scope": "diagnostic_display_only",
        "runtime_safety_truth": False,
        "phase1_l0_l4_state_mutated": False,
        "safety_api_called": False,
        "rf_tx_allowed": False,
        "lorawan_uplink_allowed": False,
        "outbound_send_performed": False,
    }
    if error is not None:
        payload["error"] = error
    return payload


def led_bits_for_snapshot(snapshot: dict[str, Any], *, fix_bit: int, no_fix_bit: int) -> int:
    bit = fix_bit if snapshot.get("snapshot_status") == "valid_fix" else no_fix_bit
    return 1 << (bit - 1)


def blink_observer_led_status(
    *,
    snapshot: dict[str, Any],
    port: str,
    data_gpio: int,
    clock_gpio: int,
    fix_bit: int,
    no_fix_bit: int,
    blink_count: int,
    blink_seconds: float,
    dry_run: bool,
) -> dict[str, Any]:
    if dry_run:
        return build_observer_led_payload(
            snapshot=snapshot,
            port=port,
            data_gpio=data_gpio,
            clock_gpio=clock_gpio,
            fix_bit=fix_bit,
            no_fix_bit=no_fix_bit,
            blink_count=blink_count,
            blink_seconds=blink_seconds,
            write_status="dry_run",
            dry_run=True,
        )
    writer = None
    try:
        writer = make_gpio_writer()
        bits = led_bits_for_snapshot(snapshot, fix_bit=fix_bit, no_fix_bit=no_fix_bit)
        for _ in range(blink_count):
            write_led_bar_bits(writer, data_gpio=data_gpio, clock_gpio=clock_gpio, bits=bits)
            time.sleep(blink_seconds)
            clear_led_bar(writer, data_gpio=data_gpio, clock_gpio=clock_gpio)
            time.sleep(blink_seconds)
        return build_observer_led_payload(
            snapshot=snapshot,
            port=port,
            data_gpio=data_gpio,
            clock_gpio=clock_gpio,
            fix_bit=fix_bit,
            no_fix_bit=no_fix_bit,
            blink_count=blink_count,
            blink_seconds=blink_seconds,
            write_status="ok",
            dry_run=False,
        )
    except Exception as exc:
        return build_observer_led_payload(
            snapshot=snapshot,
            port=port,
            data_gpio=data_gpio,
            clock_gpio=clock_gpio,
            fix_bit=fix_bit,
            no_fix_bit=no_fix_bit,
            blink_count=blink_count,
            blink_seconds=blink_seconds,
            write_status="error",
            dry_run=False,
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        if writer is not None:
            writer.close()


def build_observer_led_payload(
    *,
    snapshot: dict[str, Any],
    port: str,
    data_gpio: int,
    clock_gpio: int,
    fix_bit: int,
    no_fix_bit: int,
    blink_count: int,
    blink_seconds: float,
    write_status: str,
    dry_run: bool,
    error: str | None = None,
) -> dict[str, Any]:
    bits = led_bits_for_snapshot(snapshot, fix_bit=fix_bit, no_fix_bit=no_fix_bit)
    payload = {
        "captured_at": _now_iso(),
        "source": "scout_gnss_hardware_observer_led_status",
        "hardware_kind": "grove_led_bar_v2_my9221",
        "port": port,
        "data_gpio": data_gpio,
        "clock_gpio": clock_gpio,
        "bits": f"0x{bits:03x}",
        "fix_led_bit": fix_bit,
        "no_fix_led_bit": no_fix_bit,
        "blink_count": blink_count,
        "blink_seconds": blink_seconds,
        "write_status": write_status,
        "dry_run": dry_run,
        "snapshot_status": snapshot.get("snapshot_status"),
        "selected_source": snapshot.get("source"),
        "selected_port": snapshot.get("selected_port"),
        "selected_baud": snapshot.get("selected_baud"),
        "hardware_control_scope": "diagnostic_indicator_only",
        "runtime_safety_truth": False,
        "phase1_l0_l4_state_mutated": False,
        "safety_api_called": False,
        "rf_tx_allowed": False,
        "lorawan_uplink_allowed": False,
        "outbound_send_performed": False,
    }
    if error is not None:
        payload["error"] = error
    return payload


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Observe Scout GNSS JSONL evidence from SX1303 gateway GPS and Grove GPS sources."
    )
    env_config = GnssHardwareObserverConfig.from_env()
    parser.add_argument("--evidence-dir", type=Path, default=env_config.evidence_dir)
    parser.add_argument("--gateway-jsonl", type=Path, default=env_config.gateway_jsonl)
    parser.add_argument("--grove-jsonl", type=Path, default=env_config.grove_jsonl)
    parser.add_argument("--poll-seconds", type=float, default=env_config.poll_seconds)
    parser.add_argument("--max-records", type=int, default=env_config.max_records)
    parser.add_argument("--once", action="store_true", help="Refresh once, write status/snapshot, and exit.")
    parser.add_argument("--print-ready", action="store_true", help="Print a readiness event after the first refresh.")
    parser.add_argument("--oled-status", action="store_true", default=env_config.oled_status)
    parser.add_argument("--oled-bus", type=Path, default=env_config.oled_bus)
    parser.add_argument("--oled-address", type=parse_address, default=env_config.oled_address)
    parser.add_argument("--oled-driver", choices=("sh1107g", "ssd1327", "auto"), default=env_config.oled_driver)
    parser.add_argument("--oled-dry-run", action="store_true", default=env_config.oled_dry_run)
    parser.add_argument("--led-status", action="store_true", default=env_config.led_status)
    parser.add_argument("--led-port", choices=sorted(PORT_DEFAULTS), default=env_config.led_port)
    parser.add_argument("--led-data-gpio", type=int, default=env_config.led_data_gpio)
    parser.add_argument("--led-clock-gpio", type=int, default=env_config.led_clock_gpio)
    parser.add_argument("--led-fix-bit", type=_parse_led_bit, default=env_config.led_fix_bit)
    parser.add_argument("--led-no-fix-bit", type=_parse_led_bit, default=env_config.led_no_fix_bit)
    parser.add_argument("--led-blink-count", type=int, default=env_config.led_blink_count)
    parser.add_argument("--led-blink-seconds", type=float, default=env_config.led_blink_seconds)
    parser.add_argument("--led-dry-run", action="store_true", default=env_config.led_dry_run)
    return parser


def config_from_args(args: argparse.Namespace) -> GnssHardwareObserverConfig:
    if args.poll_seconds <= 0:
        raise ValueError("--poll-seconds must be positive")
    if args.max_records < 1:
        raise ValueError("--max-records must be at least 1")
    if args.led_blink_count < 1:
        raise ValueError("--led-blink-count must be at least 1")
    if args.led_blink_seconds < 0:
        raise ValueError("--led-blink-seconds must be non-negative")
    return GnssHardwareObserverConfig(
        evidence_dir=args.evidence_dir.expanduser(),
        gateway_jsonl=args.gateway_jsonl.expanduser(),
        grove_jsonl=args.grove_jsonl.expanduser(),
        poll_seconds=float(args.poll_seconds),
        max_records=int(args.max_records),
        print_ready=bool(args.print_ready),
        oled_status=bool(args.oled_status),
        oled_dry_run=bool(args.oled_dry_run),
        oled_bus=args.oled_bus.expanduser(),
        oled_address=int(args.oled_address),
        oled_driver=str(args.oled_driver),
        led_status=bool(args.led_status),
        led_dry_run=bool(args.led_dry_run),
        led_port=str(args.led_port),
        led_data_gpio=args.led_data_gpio,
        led_clock_gpio=args.led_clock_gpio,
        led_fix_bit=int(args.led_fix_bit),
        led_no_fix_bit=int(args.led_no_fix_bit),
        led_blink_count=int(args.led_blink_count),
        led_blink_seconds=float(args.led_blink_seconds),
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        config = config_from_args(args)
    except ValueError as exc:
        parser.error(str(exc))

    observer = GnssHardwareObserver(config)
    if args.once:
        status = observer.refresh()
        print(json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    try:
        observer.run_forever()
    except KeyboardInterrupt:
        if observer.last_status is not None:
            print(json.dumps(observer.last_status, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    return 0


def _decision_without_selection(source_statuses: list[dict[str, Any]]) -> str:
    if any(item["file_exists"] and item["record_count_scanned"] > 0 for item in source_statuses):
        return "gnss_listening_without_valid_fix"
    if any(item["file_exists"] for item in source_statuses):
        return "gnss_sources_configured_without_records"
    return "gnss_sources_missing"


def _source_status_value(path: Path, record_count: int, candidate_count: int, valid_candidate_count: int) -> str:
    if not path.exists():
        return "missing_jsonl"
    if record_count == 0:
        return "empty_jsonl"
    if valid_candidate_count > 0:
        return "fix_available"
    if candidate_count > 0:
        return "listening_no_valid_fix"
    return "records_without_fix_candidate"


def _observed_at(record: dict[str, Any], payload: dict[str, Any]) -> str:
    for value in (record.get("captured_at"), payload.get("captured_at"), record.get("updated_at")):
        if isinstance(value, str) and value.strip():
            return value
    return _now_iso()


def _timestamp_rank(value: Any) -> float:
    if not isinstance(value, str) or not value.strip():
        return 0.0
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return 0.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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


def _positive_int(value: str | None, *, default: int) -> int:
    if value in (None, ""):
        return default
    parsed = int(value)
    if parsed < 1:
        raise ValueError("value must be at least 1")
    return parsed


def _optional_int(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _led_bit(value: str | None, *, default: int) -> int:
    if value in (None, ""):
        return default
    return _parse_led_bit(value)


def _parse_led_bit(value: str | int) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 10:
        raise argparse.ArgumentTypeError("LED bit must be between 1 and 10")
    return parsed


def _display_value(value: Any) -> str:
    if value in (None, ""):
        return "--"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else f"{value:.1f}"
    return str(value)


def _bool_env(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "y", "on"}


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
